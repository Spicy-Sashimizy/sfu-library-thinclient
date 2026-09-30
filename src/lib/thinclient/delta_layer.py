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
        self._shard_manifest: str | None = None
        self.livedocs = None
        self._ordinals = None
        self._shard_filter_attached = False
        self._meta: list[tuple[int, sqlite3.Connection, bool]] = []
        self._ledger: sqlite3.Connection | None = None
        self._buffer_sig: tuple[int, int] = (-1, -1)
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
        generation g. Only the composed manifest carries delta shards (base
        records first, then one per generation); any other manifest is all base."""
        mine = self.shard_manifest_path()
        if not mine or not manifest or Path(manifest).resolve() != Path(mine).resolve():
            return [None] * n_shards
        recs = json.loads(Path(mine).read_text()).get("shards") or []
        if len(recs) != n_shards:
            return [None] * n_shards
        return [int(r["delta_generation"]) if r.get("delta_generation") is not None else None
                for r in recs]

    def shard_result_filter(self, origins: list):
        """Return `f(per_shard) -> per_shard` for `_SeismicBackendBase`: on base
        shards drop results whose base ordinal is dead; on delta shards keep a
        doc only if that generation is its newest copy and it is not a
        bitset-deleted id; everywhere drop JSON `deleted` ids. Entries are SEISMIC `(query_id, score, doc_id)` triples;
        order within a shard is preserved."""
        deleted = self.deleted
        superseded = self.superseded

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
                                and not (x and r[2] not in superseded)
                                and superseded.get(r[2], origin) == origin])
            return out
        return _filter

    def attach_seismic(self, backend, manifest: str | None) -> bool:
        """Install the per-shard filter on a federated SEISMIC backend when a
        livedocs bitset is loaded. Returns whether it was installed; when not,
        `filter_ids` applies the bitset post-merge instead."""
        if self.livedocs is None or not hasattr(backend, "_shard_result_filter"):
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
        root = Path(index_root) / "delta" if gate == "1" else Path(gate)
        if not root.is_dir():
            logger.warning("SFU_DELTA_ROOT=%s but %s is not a directory; delta layer off", gate, root)
            return None
        return cls(root)

    def section_dirs(self) -> list[tuple[str, Path, object]]:
        out: list[tuple[str, Path, object]] = []
        for g in self.generations:
            for name in g.get("sections") or []:
                out.append((f"delta_g{int(g['gen']):04d}:{name}", Path(g["dir"]) / "sections" / name,
                            int(g["gen"])))
        buf = self.root / "buffer" / BUFFER_SECTION
        if (buf / "tantivy" / "meta.json").exists():
            out.append((BUFFER_SECTION, buf, BUFFER_ORIGIN))
        return out

    def shard_manifest_path(self) -> str | None:
        return self._shard_manifest if self._shard_manifest and Path(self._shard_manifest).exists() else None

    def keep_hit(self, doc_id: str, origin) -> bool:
        if doc_id in self.deleted:
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
            row = self._ledger.execute(
                "SELECT COUNT(*), COALESCE(MAX(r.rowid),0) FROM records r JOIN docs d ON d.id=r.id "
                "WHERE (r.generation=0 OR r.generation IN (SELECT gen FROM generations WHERE state='building')) "
                "AND d.status='live'").fetchone()
        except sqlite3.Error as exc:
            logger.warning("delta buffer poll failed: %s", exc)
            return
        sig = (int(row[0]), int(row[1]))
        if sig == self._buffer_sig:
            self._ledger_stat = st
            return
        with self._lock:
            if sig == self._buffer_sig:
                return
            q = ("SELECT r.rowid, r.record FROM records r JOIN docs d ON d.id=r.id "
                 "WHERE (r.generation=0 OR r.generation IN (SELECT gen FROM generations WHERE state='building')) "
                 "AND d.status='live' AND r.rowid>? ORDER BY r.rowid")
            after = self._buffer_sig[1] if self._buffer_sig[0] >= 0 else -1
            rows = self._ledger.execute(q, (after,)).fetchall()
            if after < 0 or self._buffer_sig[0] + len(rows) != sig[0]:
                rows = self._ledger.execute(q, (-1,)).fetchall()
                self._buffer_rows = {}
                self._buffer_sparse = _ExactSparse()
            for _, rec in rows:
                d = json.loads(rec)
                self._buffer_rows[d["id"]] = d
                if d.get("sparse_field"):
                    self._buffer_sparse.add(d["id"], d["sparse_field"])
            self._buffer_sig = sig
            self._ledger_stat = st

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
