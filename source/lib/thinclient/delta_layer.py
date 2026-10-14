"""Serving-side reader for the delta-ingest layer (docs/delta_ingest/).

Reads what `spike/delta_ingest` publishes under `<index_root>/delta/`:
`generations.json` (stamp, published generations, newest-wins masks, the
composed shard manifest) plus the mutable L0 buffer (a tantivy index the
ingest process commits to, and the SPLADE vectors of buffered docs read from
the ingest ledger). Gate: `SFU_DELTA_ROOT` (unset = inert; literal `1` =
`<index_root>/delta`; else a path). Invariants: docs/CODE_INVARIANTS.md
§"delta_layer".

Deletes and superseded base copies (2026-09-29, item C): when
`generations.json` carries a `livedocs` entry, the base copy of every
tombstoned or updated W-id is masked through a bitset over the base ordinal
space (`livedocs.py`), resolved with the ordinal arrays it names. It is applied
per shard BEFORE the federated SEISMIC merge (`shard_result_filter`, so a base
copy can no longer outscore the newer delta-shard copy, issue S5), to base
BM25F hits (`filter_hits`), and post-merge on SPLADE backends without the
per-shard hook (`filter_ids`). `mask.deleted` then only lists ids with no base
ordinal; roots published before item C (no `livedocs` key) are served from the
JSON lists exactly as before.

Fold-in (doc 10 §3 G4, 2026-10-01): a base shard s replaced by its fold s′
through a composed manifest record carrying `fold_origin` ("fold:s:k") has
that string as its origin in `shard_origins`. `mask.newest_by_leg.seismic`
({id: "fold:s:k"}) names the SEISMIC leg's newest copy where it differs from
`superseded` (which stays the sections / meta / abstract leg's newest
generation): the per-shard SEISMIC filter keys on it first, so a folded doc is
served from s′ only, while its delta-generation tantivy/meta/abstract copy and
the livedocs bit that masks its base tantivy copy are unchanged. Without
either key every filter is exactly as before.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path

from lib.thinclient.builder import encode_meta_id

logger = logging.getLogger("sfu_library_mcp")

BUFFER_SECTION = "delta_buffer"
BUFFER_ORIGIN = "buffer"

REPO_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
READ_ONLY_DATA_DIRS = ("seismic_150m",)


def resolve_delta_root(index_root, value: str | None = None, *, for_write: bool = False) -> Path:
    """Resolve the delta root (O16). `value` = an explicit path (CLI
    `--delta-root`), literal `1` (= `<index_root>/delta`), or empty/None, in
    which case `SFU_DELTA_ROOT` is consulted with the same meaning, then
    `<index_root>/delta`. Serving (`for_write=False`) only resolves. Writers
    (`for_write=True`) are refused with ValueError when the root lies inside a
    read-only data dir (`data/seismic_150m`), and when nothing explicit was
    given (no value, env unset or `1`) and the implicit `<index_root>/delta`
    lies under the repo's `data/` tree (9p here, not to be written casually)."""
    v = value or os.environ.get("SFU_DELTA_ROOT", "")
    implicit = v in ("", "1")
    root = Path(index_root) / "delta" if implicit else Path(v)
    if for_write:
        r = root.resolve()
        for name in READ_ONLY_DATA_DIRS:
            ro = (REPO_DATA_DIR / name).resolve()
            if r == ro or ro in r.parents:
                raise ValueError(f"delta root {root} is inside read-only {ro}")
        data = REPO_DATA_DIR.resolve()
        if implicit and (r == data or data in r.parents):
            raise ValueError(
                f"implicit delta root {root} is under {data}; pass --delta-root or set "
                "SFU_DELTA_ROOT to a local-disk path (e.g. /var/tmp/sfu_delta)")
    return root


class _ExactSparse:
    def __init__(self):
        self.ids: list[str] = []
        self.postings: dict[str, list[tuple[int, float]]] = {}

    def add(self, doc_id: str, vec: dict[str, float]) -> None:
        i = len(self.ids)
        self.ids.append(doc_id)
        for t, w in vec.items():
            if w > 0:
                self.postings.setdefault(t, []).append((i, float(w)))

    def search(self, qvec: dict[str, float], k: int) -> list[tuple[str, float]]:
        acc: dict[int, float] = {}
        for t, qw in qvec.items():
            for i, w in self.postings.get(t, ()):
                acc[i] = acc.get(i, 0.0) + qw * w
        best = sorted(((s, i) for i, s in acc.items()), reverse=True)[:k]
        return [(self.ids[i], s) for s, i in best]


class DeltaLayer:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.stamp: str | None = None
        self.generations: list[dict] = []
        self.deleted: set[str] = set()
        self.superseded: dict[str, int] = {}
        self.seismic_newest: dict[str, str] = {}
        self._shard_manifest: str | None = None
        self.livedocs = None
        self._ordinals = None
        self._shard_filter_attached = False
        self._meta: list[tuple[int, sqlite3.Connection, bool]] = []
        self._ledger: sqlite3.Connection | None = None
        self._buffer_sig: tuple[int, int] = (-1, -1)
        self._buffer_gens: set[int] = set()
        self._ledger_stat: tuple | None = None
        self._buffer_rows: dict[str, dict] = {}
        self._buffer_sparse = _ExactSparse()
        self._lock = threading.Lock()
        gj = self.root / "generations.json"
        if gj.exists():
            data = json.loads(gj.read_text())
            self.stamp = data.get("stamp")
            self.generations = list(data.get("generations") or [])
            mask = data.get("mask") or {}
            self.deleted = set(mask.get("deleted") or [])
            self.superseded = {k: int(v) for k, v in (mask.get("superseded") or {}).items()}
            self.seismic_newest = dict((mask.get("newest_by_leg") or {}).get("seismic") or {})
            self._shard_manifest = data.get("shard_manifest")
            if data.get("livedocs"):
                self._open_livedocs(data["livedocs"])
            for g in self.generations:
                mp = Path(g["dir"]) / "meta.sqlite"
                if mp.exists():
                    db = sqlite3.connect(f"file:{mp}?mode=ro&immutable=1", uri=True,
                                         check_same_thread=False)
                    cols = {r[1]: (r[2] or "").upper() for r in db.execute("PRAGMA table_info(docs)")}
                    self._meta.append((int(g["gen"]), db, cols.get("id", "").startswith("INT")))
        self._ledger_path = self.root / "ledger.sqlite"
        self.refresh_buffer()

    def _open_livedocs(self, ld: dict) -> None:
        from lib.thinclient.livedocs import Livedocs
        from lib.thinclient.ordinals import OrdinalSpace
        path = Path(ld["path"])
        if not path.is_absolute():
            path = self.root / path
        ords = OrdinalSpace(ld["ordinal_dir"], {"ordinal_space_id": ld["ordinal_space_id"]})
        self.livedocs = Livedocs(path, expect_space_id=ords.space_id,
                                 expect_crc32=ld.get("crc32"))
        self._ordinals = ords

    def base_dead(self, ids: list[str]) -> list[bool]:
        """Per id: True iff it has a base ordinal whose livedocs bit is set.
        Ids with no base ordinal are never dead here (they are masked by the
        JSON lists instead). A set bit means "base copy masked"; the id is
        deleted everywhere iff it is also absent from `superseded` (a live
        newer copy exists only for superseded ids)."""
        if self.livedocs is None or not ids:
            return [False] * len(ids)
        pos, found = self._ordinals.lookup(ids)
        return (found & self.livedocs.dead(pos)).tolist()

    def shard_origins(self, n_shards: int, manifest: str | None) -> list:
        """Origin per served shard position: `None` = base, `g` = delta
        generation g, `"fold:s:k"` = fold k of base shard s (G4). Only the
        composed manifest carries delta shards (base records first, then one
        per generation); any other manifest is all base."""
        mine = self.shard_manifest_path()
        if not mine or not manifest or Path(manifest).resolve() != Path(mine).resolve():
            return [None] * n_shards
        recs = json.loads(Path(mine).read_text()).get("shards") or []
        if len(recs) != n_shards:
            return [None] * n_shards
        return [int(r["delta_generation"]) if r.get("delta_generation") is not None
                else (str(r["fold_origin"]) if r.get("fold_origin") else None) for r in recs]

    def shard_result_filter(self, origins: list):
        """Return `f(per_shard) -> per_shard` for `_SeismicBackendBase`: on base
        shards drop results whose base ordinal is dead; on delta shards keep a
        doc only if that generation is its newest copy and it is not a
        bitset-deleted id; everywhere drop JSON `deleted` ids. Entries are SEISMIC `(query_id, score, doc_id)` triples;
        order within a shard is preserved. Delta and fold positions resolve a
        doc's newest SEISMIC origin as `seismic_newest`, else `superseded`."""
        deleted = self.deleted
        superseded = self.superseded
        seismic_newest = self.seismic_newest

        def _filter(per_shard: list) -> list:
            out = []
            for pos, res in enumerate(per_shard):
                if not res:
                    out.append(res)
                    continue
                origin = origins[pos] if pos < len(origins) else None
                dead = self.base_dead([r[2] for r in res])
                if origin is None:
                    out.append([r for r, x in zip(res, dead)
                                if not x and r[2] not in deleted])
                else:
                    out.append([r for r, x in zip(res, dead) if r[2] not in deleted
                                and not (x and r[2] not in superseded and r[2] not in seismic_newest)
                                and seismic_newest.get(r[2], superseded.get(r[2], origin)) == origin])
            return out
        return _filter

    def attach_seismic(self, backend, manifest: str | None) -> bool:
        """Install the per-shard filter on a federated SEISMIC backend when a
        livedocs bitset is loaded, or when a fold is served (G4). Returns
        whether it was installed; when not, `filter_ids` applies the bitset
        post-merge instead."""
        if not hasattr(backend, "_shard_result_filter"):
            return False
        if self.livedocs is None and not (self.seismic_newest or any(
                isinstance(o, str) for o in self.shard_origins(len(getattr(backend, "shards", ())), manifest))):
            return False
        backend._shard_result_filter = self.shard_result_filter(
            self.shard_origins(len(backend.shards), manifest))
        self._shard_filter_attached = True
        return True

    @classmethod
    def load_if_enabled(cls, index_root: Path) -> "DeltaLayer | None":
        gate = os.environ.get("SFU_DELTA_ROOT", "")
        if not gate:
            return None
        root = resolve_delta_root(index_root, gate)
        if not root.is_dir():
            logger.warning("SFU_DELTA_ROOT=%s but %s is not a directory; delta layer off", gate, root)
            return None
        return cls(root)

    def section_dirs(self) -> list[tuple[str, Path, object]]:
        out: list[tuple[str, Path, object]] = []
        for g in self.generations:
            for name in g.get("sections") or []:
                out.append((self.section_key(int(g["gen"]), name), Path(g["dir"]) / "sections" / name,
                            int(g["gen"])))
        buf = self.buffer_section_dir()
        if buf is not None:
            out.append((BUFFER_SECTION, buf, BUFFER_ORIGIN))
        return out

    @staticmethod
    def section_key(gen: int, name: str) -> str:
        """Retriever key of generation `gen`'s section `name` (in `_sections`
        and `_abstract_stores`)."""
        return f"delta_g{int(gen):04d}:{name}"

    def buffer_section_dir(self) -> Path | None:
        """The buffer's section dir once its tantivy index exists (the ingest
        process creates it on first ingest, possibly after this layer loaded)."""
        buf = self.root / "buffer" / BUFFER_SECTION
        return buf if (buf / "tantivy" / "meta.json").exists() else None

    def shard_manifest_path(self) -> str | None:
        return self._shard_manifest if self._shard_manifest and Path(self._shard_manifest).exists() else None

    def keep_hit(self, doc_id: str, origin) -> bool:
        if doc_id in self.deleted:
            return False
        if origin == BUFFER_ORIGIN and doc_id not in self._buffer_rows:
            return False
        newest = self.superseded.get(doc_id)
        if newest is None:
            return True
        if origin is None:
            return False
        if origin == BUFFER_ORIGIN:
            return newest == 0
        return newest == origin

    def filter_hits(self, hits: list[tuple[str, float, object]]) -> list[tuple[str, float]]:
        if any(h[2] == BUFFER_ORIGIN for h in hits):
            self.refresh_buffer()
        if self.livedocs is not None:
            dead = self.base_dead([h[0] for h in hits])
            return [(d, s) for (d, s, o), x in zip(hits, dead)
                    if not (x and (o is None or d not in self.superseded)) and self.keep_hit(d, o)]
        return [(d, s) for d, s, o in hits if self.keep_hit(d, o)]

    def filter_ids(self, ranked: list[tuple[str, float]]) -> list[tuple[str, float]]:
        if self.livedocs is not None and not self._shard_filter_attached and ranked:
            dead = self.base_dead([d for d, _ in ranked])
            ranked = [r for r, x in zip(ranked, dead)
                      if not x or self.superseded.get(r[0], 0) > 0]
        if not self.deleted and not self.superseded:
            return ranked
        return [(d, s) for d, s in ranked
                if d not in self.deleted and self.superseded.get(d, -1) != 0]

    def _ledger_file_stat(self) -> tuple | None:
        out = []
        for p in (self._ledger_path, self._ledger_path.with_name(self._ledger_path.name + "-wal")):
            try:
                st = os.stat(p)
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return None if out[0] is None else tuple(out)

    def refresh_buffer(self) -> None:
        """Re-read the buffer from the ingest ledger when it changed on disk.
        Cheap when nothing changed: two `stat` calls, no SQL. Opens the ledger
        lazily, so a layer loaded before the first ingest still sees it."""
        st = self._ledger_file_stat()
        if st is None or st == self._ledger_stat:
            return
        if self._ledger is None:
            try:
                self._ledger = sqlite3.connect(f"file:{self._ledger_path}?mode=ro", uri=True,
                                               check_same_thread=False, timeout=5)
            except sqlite3.Error as exc:
                logger.warning("delta ledger open failed: %s", exc)
                return
        try:
            gens = self._buffer_generations()
            marks = ",".join("?" * len(gens))
            row = self._ledger.execute(
                "SELECT COUNT(*), COALESCE(MAX(r.rowid),0) FROM records r JOIN docs d ON d.id=r.id "
                f"WHERE r.generation IN ({marks}) AND d.status='live'", gens).fetchone()
        except sqlite3.Error as exc:
            logger.warning("delta buffer poll failed: %s", exc)
            return
        sig = (int(row[0]), int(row[1]))
        if sig == self._buffer_sig and set(gens) >= self._buffer_gens:
            self._buffer_gens = set(gens)
            self._ledger_stat = st
            return
        with self._lock:
            if sig == self._buffer_sig and set(gens) >= self._buffer_gens:
                self._buffer_gens = set(gens)
                return
            q = ("SELECT r.rowid, r.record FROM records r JOIN docs d ON d.id=r.id "
                 f"WHERE r.generation IN ({marks}) AND d.status='live' AND r.rowid>? ORDER BY r.rowid")
            after = self._buffer_sig[1] if self._buffer_sig[0] >= 0 else -1
            rows = self._ledger.execute(q, (*gens, after)).fetchall()
            if (after < 0 or self._buffer_sig[0] + len(rows) != sig[0]
                    or not set(gens) >= self._buffer_gens):
                rows = self._ledger.execute(q, (*gens, -1)).fetchall()
                self._buffer_rows = {}
                self._buffer_sparse = _ExactSparse()
            for _, rec in rows:
                d = json.loads(rec)
                self._buffer_rows[d["id"]] = d
                if d.get("sparse_field"):
                    self._buffer_sparse.add(d["id"], d["sparse_field"])
            self._buffer_sig = sig
            self._buffer_gens = set(gens)
            self._ledger_stat = st

    def _buffer_generations(self) -> list[int]:
        """Ledger generations whose records form the buffer view: 0, plus
        every `building` or published-but-not-loaded generation that holds
        only docs this layer does not already serve from a loaded generation
        (O2: a freeze publishes before `reload()` loads it). A generation is
        buffer-derived when its `from_gens` (ledger `info`) are all 0 or
        themselves buffer-derived and unloaded; when `info` no longer carries
        `from_gens` (published rows), it counts as buffer-derived iff no loaded
        generation has been compacted since load, since only a compaction can
        move loaded docs into a newer generation."""
        loaded = {int(g["gen"]) for g in self.generations}
        rows = {int(g): (s, i) for g, s, i in
                self._ledger.execute("SELECT gen, state, info FROM generations")}
        loaded_compacted = any(rows.get(g, ("",))[0] == "compacted" for g in loaded)
        memo: dict[int, bool] = {}

        def derived(g: int, depth: int = 0) -> bool:
            if g == 0:
                return True
            if g in loaded or g not in rows or depth > len(rows):
                return False
            if g in memo:
                return memo[g]
            try:
                info = json.loads(rows[g][1] or "{}")
            except ValueError:
                info = {}
            src = info.get("from_gens") if isinstance(info, dict) else None
            ok = (all(derived(int(s), depth + 1) for s in src) if isinstance(src, list)
                  else not loaded_compacted)
            memo[g] = ok
            return ok

        return [0] + sorted(g for g, (state, _) in rows.items()
                            if g not in loaded and state in ("building", "published") and derived(g))

    def buffer_size(self) -> int:
        self.refresh_buffer()
        return len(self._buffer_rows)

    def buffer_search(self, qvec: dict[str, float], k: int) -> list[tuple[str, float]]:
        self.refresh_buffer()
        if not self._buffer_rows:
            return []
        with self._lock:
            return [(d, s) for d, s in self._buffer_sparse.search(qvec, k) if d not in self.deleted]

    def meta_rows(self, ids: list[str]) -> dict[str, tuple]:
        out: dict[str, tuple] = {}
        if not ids:
            return out
        for gen, db, numeric in reversed(self._meta):
            want = [i for i in ids if i not in out]
            if not want:
                break
            enc: dict[int, str] = {}
            other: list[str] = []
            for s in want:
                n = encode_meta_id(s) if numeric else None
                (other.append(s) if n is None else enc.__setitem__(n, s))
            for table, keys, back in (("docs", list(enc), enc), ("docs_other", other, None)):
                for i in range(0, len(keys), 500):
                    chunk = keys[i:i + 500]
                    marks = ",".join("?" * len(chunk))
                    for row in db.execute(
                            f"SELECT id, title, doi, year, type, is_oa, section FROM {table} "
                            f"WHERE id IN ({marks})", chunk):
                        did = back[row[0]] if back is not None else row[0]
                        if self.superseded.get(did, gen) == gen:
                            out[did] = (did,) + tuple(row[1:])
        self.refresh_buffer()
        for i in ids:
            if i in out:
                continue
            d = self._buffer_rows.get(i)
            if d is not None:
                out[i] = (i, d.get("title") or "", d.get("doi") or "", d.get("year"),
                          d.get("type") or "", bool(d.get("is_oa")), "delta_buffer")
        return out

    def abstract_owner(self, ids: list[str]) -> dict[str, tuple[int, str]]:
        """`{id: (generation, section)}` for the ids a loaded generation
        serves: the newest generation whose `meta.sqlite` holds the id and that
        `superseded` names as its newest copy (unsuperseded ids: the newest
        generation holding them). Ids no generation holds are absent (base,
        buffer or unknown). Lever L3 (`SFU_DELTA_ABS_ROUTE`)."""
        out: dict[str, tuple[int, str]] = {}
        if not ids:
            return out
        for gen, db, numeric in reversed(self._meta):
            want = [i for i in ids if i not in out]
            if not want:
                break
            enc: dict[int, str] = {}
            other: list[str] = []
            for s in want:
                n = encode_meta_id(s) if numeric else None
                (other.append(s) if n is None else enc.__setitem__(n, s))
            for table, keys, back in (("docs", list(enc), enc), ("docs_other", other, None)):
                for i in range(0, len(keys), 500):
                    chunk = keys[i:i + 500]
                    marks = ",".join("?" * len(chunk))
                    for row in db.execute(
                            f"SELECT id, section FROM {table} WHERE id IN ({marks})", chunk):
                        did = back[row[0]] if back is not None else row[0]
                        if self.superseded.get(did, gen) == gen:
                            out[did] = (gen, row[1])
        return out

    def buffer_abstracts(self, ids: list[str]) -> dict[str, str]:
        self.refresh_buffer()
        return {i: self._buffer_rows[i]["abstract"] for i in ids
                if i in self._buffer_rows and self._buffer_rows[i].get("abstract")}

    def info(self) -> dict:
        self.refresh_buffer()
        return {"root": str(self.root), "stamp": self.stamp,
                "generations": [{"gen": g["gen"], "docs": g["docs"], "seismic": g.get("seismic")}
                                for g in self.generations],
                "buffer_docs": len(self._buffer_rows), "buffer_vectors": len(self._buffer_sparse.ids),
                "deleted": len(self.deleted), "superseded": len(self.superseded),
                "livedocs": None if self.livedocs is None else {
                    "path": str(self.livedocs.path), "popcount": self.livedocs.popcount,
                    "nbits": self.livedocs.nbits, "per_shard": self._shard_filter_attached},
                "shard_manifest": self.shard_manifest_path()}

    def close(self) -> None:
        if self.livedocs is not None:
            self.livedocs.close()
        for _, db, _ in self._meta:
            try:
                db.close()
            except sqlite3.Error:
                pass
        if self._ledger is not None:
            self._ledger.close()
