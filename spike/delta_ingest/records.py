"""Canonical document record — the contract every source adapter must meet.

The served artifacts (tantivy section, meta.sqlite row, abstract sidecar block,
SEISMIC forward record) only ever see a `DocRecord`, so the ingest path is
source-agnostic by construction: OpenAlex, arXiv, Zotero, a CSV, a watched
folder of PDFs — each is an adapter that yields these.

Id namespace (load-bearing, mirrors `builder.encode_meta_id`):
  - OpenAlex works keep their bare W-id ("W2031234567") — INTEGER PK in meta.
  - Everything else is "<namespace>:<local id>" (e.g. "arxiv:2401.01234",
    "zotero:ABCD1234", "doi:10.1000/xyz") and lands in `docs_other` (TEXT PK).
    Non-W ids have NO remote abstract fallback (OpenAlex fetch), so the delta
    sidecar is mandatory for them — `generation.build` always writes hot
    sections for delta generations.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

from lib.thinclient.sections import classify_doc, era_of

W_ID_RE = re.compile(r"^W[1-9]\d*$")
OPENALEX_PREFIX = "https://openalex.org/"
DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                "http://dx.doi.org/", "doi.org/", "dx.doi.org/", "doi:")
BASE_MIN_YEAR = 2010
LAYOUTS = ("per_base_section", "per_era", "single")
DELTA_SECTION = "delta"

# Fields whose change must re-emit an artifact (title/abstract → re-encode +
# re-index; year/type/is_oa/doi → meta + tantivy fast fields). Citation counts
# and other OpenAlex churn are deliberately NOT here — see 01_RESEARCH.md §1
# (~15% of records are touched per month, mostly citation bumps).
CONTENT_FIELDS = ("title", "abstract", "year", "type", "is_oa", "doi")


@dataclass
class DocRecord:
    id: str
    title: str = ""
    abstract: str = ""
    year: int | None = None
    type: str = ""
    is_oa: bool = False
    doi: str = ""
    source: str = ""
    updated_at: str = ""
    sparse_field: dict[str, float] | None = None
    extra: dict = field(default_factory=dict)

    # ── identity / change detection ──────────────────────────────────────
    def content_hash(self) -> str:
        payload = json.dumps([getattr(self, f) for f in CONTENT_FIELDS],
                             ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def encode_hash(self) -> str:
        """Hash of the encoder input only: an update that changes year/doi but
        not title/abstract must NOT re-encode (GPU is the expensive step)."""
        return hashlib.sha1(self.encoder_text().encode("utf-8")).hexdigest()

    # ── what the artifacts consume ───────────────────────────────────────
    def encoder_text(self) -> str:
        # Byte-identical to the retired splade_indexer (f"{title} {abstract}".strip())
        # so delta vectors live in the same score space as the 150M base.
        return f"{self.title or ''} {self.abstract or ''}".strip()

    def section(self, layout: str = "per_base_section") -> str:
        """Section this record is written to in a delta generation.

        `layout` (09 lever L2, a profile dial): `per_base_section` (default,
        `<base>__<era>` as the served base), `per_era` (`delta__<era>`, keeps
        the retriever's era-suffix skip) or `single` (`delta`, never
        era-skipped). The ledger keeps the default name; only the generation
        build passes a layout."""
        if layout == "per_base_section":
            return f"{classify_doc(self.title, self.abstract)}__{era_of(self.year)}"
        if layout == "per_era":
            return f"{DELTA_SECTION}__{era_of(self.year)}"
        if layout == "single":
            return DELTA_SECTION
        raise ValueError(f"unknown layout {layout!r}; expected one of {LAYOUTS}")

    def builder_doc(self) -> dict:
        """The dict `SectionBuilder.add` expects. No `sparse_field`: the delta
        SPLADE leg is SEISMIC, and the builder has ignored sparse weights since
        its BMP shard emission was removed 2026-10-11."""
        return {"id": self.id, "title": self.title or "", "abstract": self.abstract or "",
                "publication_year": self.year, "type": self.type or "",
                "is_oa": bool(self.is_oa), "doi": self.doi or ""}

    def seismic_line(self) -> str | None:
        if not self.sparse_field:
            return None
        return json.dumps({"id": self.id, "vector": self.sparse_field},
                          separators=(",", ":"))

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, s: str) -> "DocRecord":
        d = json.loads(s)
        return cls(**d)


def canonical_id(namespace: str, local_id: str) -> str:
    """A bare W-id (or an openalex.org URL) is canonical from ANY source — a
    local file that says "W5" is asserting it describes that OpenAlex work and
    supersedes it (newest-wins). Everything else is namespaced."""
    local_id = (local_id or "").strip()
    if local_id.startswith(OPENALEX_PREFIX):
        local_id = local_id[len(OPENALEX_PREFIX):]
    if W_ID_RE.match(local_id):
        return local_id
    return f"{namespace}:{local_id}"


def normalize_doi(doi) -> str:
    """The ONE DOI normalisation every path uses (adapters, generic rows, the
    base-hash seed): trim, lowercase, strip a resolver/`doi:` prefix. The base
    meta.sqlite stores `https://doi.org/...` while snapshot records were
    stripped, which alone changed the content hash of 33,600 of 34,584 in-base
    docs in the M7 primary partition (issue O5, 02_DESIGN.md §3.1)."""
    d = str(doi or "").strip().lower()
    for p in DOI_PREFIXES:
        if d.startswith(p):
            d = d[len(p):]
            break
    return d.strip()


def coerce_year(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        s = str(v).strip()
        return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else int(s)
    except (TypeError, ValueError):
        return None


def reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """OpenAlex ships `abstract_inverted_index` (word -> positions); both the
    API and the snapshot still do (01_RESEARCH.md §4). Same join as
    `lib.openalex.reconstruct_abstract` and the retired sync script."""
    if not inverted_index or not isinstance(inverted_index, dict):
        return None
    positions: list[tuple[int, str]] = []
    for word, pos in inverted_index.items():
        if isinstance(pos, list):
            positions.extend((p, word) for p in pos)
    if not positions:
        return None
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


def normalize_openalex_work(work: dict, *, source: str = "openalex",
                            min_abstract_chars: int = 50,
                            allow_xpac: bool = False) -> DocRecord | None:
    """OpenAlex work JSON (API or snapshot line) -> DocRecord, or None when the
    work falls outside the served slice (no usable abstract, xpac corpus)."""
    if not allow_xpac and work.get("is_xpac"):
        return None
    abstract = work.get("abstract") or reconstruct_abstract(
        work.get("abstract_inverted_index"))
    if not abstract or len(abstract) < min_abstract_chars:
        return None
    wid = canonical_id("openalex", work.get("id") or "")
    if not W_ID_RE.match(wid):
        return None
    doi = normalize_doi(work.get("doi"))
    oa = work.get("open_access") or {}
    return DocRecord(
        id=wid, title=work.get("title") or work.get("display_name") or "",
        abstract=abstract, year=coerce_year(work.get("publication_year")),
        type=work.get("type") or "", is_oa=bool(oa.get("is_oa", work.get("is_oa", False))),
        doi=doi, source=source, updated_at=str(work.get("updated_date") or ""),
        extra={"is_retracted": bool(work.get("is_retracted", False)),
               "cited_by_count": work.get("cited_by_count")},
    )


def normalize_generic(row: dict, *, namespace: str, source: str,
                      mapping: dict[str, str] | None = None) -> DocRecord | None:
    """Any flat dict (CSV row, JSONL line, Zotero item, arXiv entry) -> DocRecord.
    `mapping` renames source columns onto canonical field names, e.g.
    {"arxiv_id": "id", "summary": "abstract", "published": "year"}."""
    m = mapping or {}
    get = lambda k: row.get(next((s for s, c in m.items() if c == k), k))  # noqa: E731
    local = get("id")
    if local in (None, ""):
        return None
    abstract = get("abstract") or ""
    title = get("title") or ""
    if not (title or abstract):
        return None
    sparse = row.get("sparse_field")
    return DocRecord(
        id=canonical_id(namespace, str(local)), title=str(title), abstract=str(abstract),
        year=coerce_year(get("year") if get("year") is not None else get("publication_year")),
        type=str(get("type") or ""), is_oa=bool(get("is_oa") or False),
        doi=normalize_doi(get("doi")), source=source, updated_at=str(get("updated_at") or ""),
        sparse_field=dict(sparse) if isinstance(sparse, dict) and sparse else None,
    )
