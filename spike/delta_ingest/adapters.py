"""Source adapters: anything that can yield `DocRecord`s and deletions.

Adapter contract (duck-typed, no base class needed):
    name: str
    iter_records(state: dict) -> Iterator[DocRecord]
    iter_deletions(state: dict) -> Iterator[str]        # canonical ids
    state after iteration holds the resume cursor (the ledger persists it)

Shipped adapters:
  - JsonlAdapter        any JSONL/CSV file (generic mapping) — the "any datapoint" path
  - OpenAlexSnapshotAdapter  free quarterly snapshot: `updated_date=` partitions
                        newer than the watermark + deleted_ids.csv.gz
  - OpenAlexApiAdapter  REST cursor paging over a filter (paid tiers only for
                        from_updated_date / from_created_date — 01_RESEARCH.md §2)
Network I/O is injected (`session`), so every adapter is unit-testable offline.
"""
from __future__ import annotations

import contextlib
import csv
import gzip
import json
import logging
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlparse

from .records import BASE_MIN_YEAR, DocRecord, canonical_id, normalize_generic, normalize_openalex_work

log = logging.getLogger("delta_ingest.adapters")

OPENALEX_WORKS_MANIFEST = "https://openalex.s3.amazonaws.com/data/jsonl/works/manifest.json"
OPENALEX_DELETED_IDS = "https://openalex.s3.amazonaws.com/data/jsonl/works/deleted_ids.csv.gz"
OPENALEX_API = "https://api.openalex.org/works"


# ── generic files ──────────────────────────────────────────────────────────
class JsonlAdapter:
    """One record per line (JSONL) or row (CSV/TSV). `mapping` renames source
    columns to canonical names; `namespace` prefixes non-OpenAlex ids.
    A line with {"_delete": "<id>"} is a deletion. Resume cursor = byte offset."""

    def __init__(self, path: str | Path, *, namespace: str = "local",
                 source: str | None = None, mapping: dict[str, str] | None = None,
                 openalex_shape: bool = False):
        self.path = Path(path)
        self.namespace = namespace
        self.name = source or f"file:{self.path.name}"
        self.mapping = mapping
        self.openalex_shape = openalex_shape
        self._deletions: list[str] = []

    def _rows(self, state: dict) -> Iterator[dict]:
        suffix = self.path.suffix.lower()
        opener = gzip.open if suffix == ".gz" else open
        if suffix in (".csv", ".tsv"):
            with opener(self.path, "rt", encoding="utf-8", newline="") as fh:
                yield from csv.DictReader(fh, delimiter="\t" if suffix == ".tsv" else ",")
            return
        start = int(state.get("offset", 0))
        with opener(self.path, "rb") as fh:
            fh.seek(start)
            while True:
                line = fh.readline()
                if not line:
                    break
                state["offset"] = fh.tell()
                line = line.strip()
                if line:
                    yield json.loads(line)

    def iter_records(self, state: dict) -> Iterator[DocRecord]:
        for row in self._rows(state):
            if "_delete" in row:
                self._deletions.append(canonical_id(self.namespace, str(row["_delete"])))
                continue
            rec = (normalize_openalex_work(row, source=self.name) if self.openalex_shape
                   else normalize_generic(row, namespace=self.namespace,
                                          source=self.name, mapping=self.mapping))
            if rec is not None:
                yield rec

    def iter_deletions(self, state: dict) -> Iterator[str]:
        yield from self._deletions
        self._deletions = []


# ── OpenAlex snapshot (free path) ──────────────────────────────────────────
def partition_of(url: str) -> str:
    """Stable identity of a snapshot part independent of host/signing: the
    `updated_date=YYYY-MM-DD/part_NNNN.gz` suffix (recovered from the retired
    scripts/opensearch_sync.py — keying on the raw URL re-ingests everything
    on each republish)."""
    path = url.split("?", 1)[0]
    i = path.find("updated_date=")
    return path[i:] if i != -1 else path.rsplit("/", 1)[-1]


def partition_date(url: str) -> str:
    p = partition_of(url)
    return p[len("updated_date="):len("updated_date=") + 10] if p.startswith("updated_date=") else ""


def select_new_parts(manifest: dict, watermark_date: str, synced: set[str]) -> list[dict]:
    """Parts whose partition date > watermark and not already synced. The
    manifest's per-part `meta.record_count` lets a caller size the delta
    before downloading (01_RESEARCH.md §1)."""
    out = []
    for e in manifest.get("entries") or manifest.get("files") or []:
        url = e.get("url", "")
        if partition_of(url) in synced:
            continue
        if watermark_date and partition_date(url) <= watermark_date:
            continue
        out.append(e)
    out.sort(key=lambda e: partition_of(e.get("url", "")))
    return out


class OpenAlexSnapshotAdapter:
    """Free quarterly snapshot, incremental by partition date.

    state = {"watermark": "YYYY-MM-DD", "synced": [partition ids],
             "deleted_ids_etag": str}
    Every record newer than the watermark is yielded; the ledger's content-hash
    diff decides what is actually new/changed (most "updates" are citation
    bumps that change no served artifact).

    `min_year` defaults to the base boundary `BASE_MIN_YEAR` (2010: the base
    holds year >= 2010 plus year-less works in the `__archive` sections); the
    old 2015 default dropped in-base works from the update stream (issue O6).
    None disables the gate. Year-less works always pass."""

    name = "openalex_snapshot"

    def __init__(self, session, *, min_year: int | None = BASE_MIN_YEAR, manifest_url: str = OPENALEX_WORKS_MANIFEST,
                 deleted_ids_url: str = OPENALEX_DELETED_IDS, max_parts: int | None = None,
                 allow_xpac: bool = False, retries: int = 3,
                 spool_dir: str | Path | None = None, chunk_bytes: int = 1 << 20,
                 retry_sleep_s: float = 2.0):
        self.session = session
        self.min_year = min_year
        self.manifest_url = manifest_url
        self.deleted_ids_url = deleted_ids_url
        self.max_parts = max_parts
        self.allow_xpac = allow_xpac
        self.retries = retries
        self.spool_dir = Path(spool_dir) if spool_dir else None
        self.chunk_bytes = chunk_bytes
        self.retry_sleep_s = retry_sleep_s

    @staticmethod
    def _https(url: str) -> str:
        # manifest.json lists parts as s3://openalex/...; requests cannot fetch
        # that scheme, so map to the public HTTPS endpoint (M7 run 2026-09-29).
        if url.startswith("s3://openalex/"):
            return "https://openalex.s3.amazonaws.com/" + url[len("s3://openalex/"):]
        return url

    @staticmethod
    def _local_path(url: str) -> Path | None:
        """A manifest entry may name a partition already on local disk
        (absolute path or file:// URL): it is then read in place, no copy."""
        if url.startswith("file://"):
            return Path(unquote(urlparse(url).path))
        if url.startswith("/") and Path(url).is_file():
            return Path(url)
        return None

    def _retry(self, url: str, attempt: int, exc: Exception) -> None:
        if attempt == self.retries:
            raise exc
        log.warning("GET %s failed (%s), retry %d", url, exc, attempt)
        if self.retry_sleep_s:
            time.sleep(self.retry_sleep_s ** attempt)

    def _get(self, url: str, **kw) -> bytes:
        """Small bodies only (the manifest). Partitions and deleted_ids go
        through `_open_gz`, which never holds a whole file in memory (O7)."""
        url = self._https(url)
        for attempt in range(1, self.retries + 1):
            try:
                r = self.session.get(url, timeout=kw.get("timeout", 120))
                r.raise_for_status()
                return r.content
            except Exception as exc:  # noqa: BLE001
                self._retry(url, attempt, exc)
        raise RuntimeError("unreachable")

    def _spool(self, url: str, fh) -> None:
        """Download `url` into the open spool file `fh` in `chunk_bytes`
        pieces (streamed response); a failed attempt truncates and retries."""
        for attempt in range(1, self.retries + 1):
            fh.seek(0)
            fh.truncate()
            try:
                r = self.session.get(url, stream=True, timeout=120)
                try:
                    r.raise_for_status()
                    if hasattr(r, "iter_content"):
                        for chunk in r.iter_content(chunk_size=self.chunk_bytes):
                            if chunk:
                                fh.write(chunk)
                    else:
                        fh.write(r.content)
                finally:
                    close = getattr(r, "close", None)
                    if close is not None:
                        close()
                fh.flush()
                fh.seek(0)
                return
            except Exception as exc:  # noqa: BLE001
                self._retry(url, attempt, exc)

    @contextlib.contextmanager
    def _open_gz(self, url: str):
        """Yield a text stream over the decompressed body of a gzip'd
        partition. Local partitions are read in place; remote ones are
        spooled compressed to `spool_dir` (default: the system temp dir) and
        the spool file is removed afterwards. Memory: one chunk + gzip's
        window + one line, independent of partition size (O7)."""
        local = self._local_path(url)
        if local is not None:
            with gzip.open(local, "rt", encoding="utf-8", errors="replace") as fh:
                yield fh
            return
        url = self._https(url)
        if self.spool_dir is not None:
            self.spool_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="oa_part_", suffix=".gz",
                                    dir=str(self.spool_dir) if self.spool_dir else None)
        try:
            with os.fdopen(fd, "w+b") as raw:
                self._spool(url, raw)
                with gzip.open(raw, "rt", encoding="utf-8", errors="replace") as fh:
                    yield fh
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name)

    def plan(self, state: dict) -> list[dict]:
        manifest = json.loads(self._get(self.manifest_url))
        parts = select_new_parts(manifest, state.get("watermark", ""), set(state.get("synced", [])))
        return parts[: self.max_parts] if self.max_parts else parts

    def iter_records(self, state: dict) -> Iterator[DocRecord]:
        synced = list(state.get("synced", []))
        for part in self.plan(state):
            url = part["url"]
            n = 0
            with self._open_gz(url) as lines:
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        work = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    year = work.get("publication_year")
                    if self.min_year is not None and isinstance(year, int) and year < self.min_year:
                        continue
                    rec = normalize_openalex_work(work, source=self.name, allow_xpac=self.allow_xpac)
                    if rec is not None:
                        n += 1
                        yield rec
            synced.append(partition_of(url))
            state["synced"] = synced
            state["watermark"] = max(state.get("watermark", ""), partition_date(url))
            log.info("snapshot part %s: %d records in slice", partition_of(url), n)

    def iter_deletions(self, state: dict) -> Iterator[str]:
        """`deleted_ids.csv.gz` (work_id, deleted_date) — the post-Walden
        successor of merged_ids/ (01_RESEARCH.md §3). Yields ids deleted after
        the last applied deleted_date."""
        since = state.get("deleted_since", "")
        newest = since
        try:
            ctx = self._open_gz(self.deleted_ids_url)
            fh = ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            log.warning("deleted_ids fetch failed: %s", exc)
            return
        try:
            for row in csv.DictReader(fh):
                d = row.get("deleted_date", "")
                if d and d <= since:
                    continue
                newest = max(newest, d)
                yield canonical_id("openalex", row.get("work_id", ""))
        finally:
            ctx.__exit__(None, None, None)
        state["deleted_since"] = newest


# ── OpenAlex REST (small streams / paid since-date filters) ────────────────
class OpenAlexApiAdapter:
    """Cursor-paged /works over `filter`. Keys are mandatory since 2026-02-13;
    every response carries meta.cost_usd (01_RESEARCH.md §2). A merged-away
    id answers 301 on single-entity GET; this adapter reports no deletions
    (the uncalled id prober `probe_deleted` was removed 2026-10-11)."""

    name = "openalex_api"

    def __init__(self, session, api_key: str, *, filter_expr: str, per_page: int = 100,
                 max_records: int | None = None, allow_xpac: bool = False,
                 base_url: str = OPENALEX_API, sleep_s: float = 0.0):
        self.session = session
        self.api_key = api_key
        self.filter_expr = filter_expr
        self.per_page = min(per_page, 100)
        self.max_records = max_records
        self.allow_xpac = allow_xpac
        self.base_url = base_url
        self.sleep_s = sleep_s
        self.cost_usd = 0.0

    def iter_records(self, state: dict) -> Iterator[DocRecord]:
        cursor = state.get("cursor") or "*"
        n = 0
        while cursor:
            params = {"filter": self.filter_expr, "per-page": self.per_page,
                      "cursor": cursor, "api_key": self.api_key,
                      "select": "id,doi,title,display_name,publication_year,type,"
                                "open_access,abstract_inverted_index,updated_date,"
                                "is_retracted,cited_by_count,is_xpac"}
            r = self.session.get(self.base_url, params=params, timeout=60)
            if r.status_code == 429:
                time.sleep(5)
                continue
            r.raise_for_status()
            body = r.json()
            self.cost_usd += float((body.get("meta") or {}).get("cost_usd") or 0.0)
            for work in body.get("results", []):
                rec = normalize_openalex_work(work, source=self.name, allow_xpac=self.allow_xpac)
                if rec is not None:
                    n += 1
                    yield rec
                    if self.max_records and n >= self.max_records:
                        state["cursor"] = (body.get("meta") or {}).get("next_cursor")
                        return
            cursor = (body.get("meta") or {}).get("next_cursor")
            state["cursor"] = cursor
            if self.sleep_s:
                time.sleep(self.sleep_s)
        state["cursor"] = None

    def iter_deletions(self, state: dict) -> Iterator[str]:
        return iter(())
