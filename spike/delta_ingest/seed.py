"""Base-hash seed for the ingest ledger (issue O4, docs/delta_ingest/02_DESIGN.md
§3.1 and §4 item 1).

Without it the ledger holds no hashes for base documents, so `classify`
returns "updated" for every in-base id of a snapshot partition (M7: ledger as
coded 1.00:1). The seed rebuilds, for each base doc, the SAME `DocRecord` the
snapshot adapter would build for that work — title/doi/year/type/is_oa from the
base `meta.sqlite`, abstract from the section's abstract sidecar, DOI through
`records.normalize_doi`, a year of 0 read as "no year" — and writes its
`content_hash` / `encode_hash` (64-bit prefixes) into `base_hashes`.

Sources (read-only, never written):
  meta      `$SFU_META_STAGE_DIR/meta.sqlite` when that env var is non-blank
            and the file exists, else `<index_root>/meta.sqlite`
  abstracts `<root>/<section>/abstracts.sqlite` (+ `.flat`) for the first root
            in `sidecar_roots` (default `<index_root>/sections`) that has it.
            On this host only the hot section keeps a local sidecar; packed
            sections must be unpacked to a local root first. Docs whose
            section has no sidecar are skipped and counted, never guessed.

Modes: `seed_ids` (an explicit id list) and `seed_range` (meta id range
[lo, hi), resumable through the ledger `sources` cursor, committed together
with each batch's hashes). Memory is bounded by `batch` rows plus the
AbstractStore block cache and its mmapped locator.
"""
from __future__ import annotations

import collections
import os
import resource
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

from lib.thinclient.abstracts import DICTS_STAMP, AbstractStore

from .ledger import IngestLedger
from .records import DocRecord, coerce_year, normalize_doi

SEED_SOURCE = "base_seed"


def base_record(wid: str, title, doi, year, type_, is_oa, abstract: str) -> DocRecord:
    """The DocRecord `normalize_openalex_work` would yield for this work, from
    base fields. meta stores a missing year as 0; the adapter's is None."""
    return DocRecord(id=wid, title=title or "", abstract=abstract or "",
                     year=coerce_year(year) if year else None, type=type_ or "",
                     is_oa=bool(is_oa), doi=normalize_doi(doi), source="base")


def resolve_meta(index_root: str | Path) -> Path:
    stage = (os.environ.get("SFU_META_STAGE_DIR") or "").strip()
    if stage and (Path(stage) / "meta.sqlite").exists():
        return Path(stage) / "meta.sqlite"
    return Path(index_root) / "meta.sqlite"


def _proc_io() -> dict:
    out = {}
    try:
        for line in Path("/proc/self/io").read_text().splitlines():
            k, v = line.split(":")
            out[k.strip()] = int(v)
    except OSError:
        pass
    ru = resource.getrusage(resource.RUSAGE_SELF)
    out["majflt"] = ru.ru_majflt
    out["maxrss_kb"] = ru.ru_maxrss
    return out


class BaseSeeder:
    def __init__(self, index_root: str | Path, ledger: IngestLedger, *,
                 sidecar_roots: list[str | Path] | None = None,
                 meta_path: str | Path | None = None, batch: int = 5000):
        self.index_root = Path(index_root)
        self.ledger = ledger
        self.meta_path = Path(meta_path) if meta_path else resolve_meta(self.index_root)
        self.db = sqlite3.connect(f"file:{self.meta_path}?mode=ro", uri=True, timeout=60)
        self.roots = [Path(r) for r in (sidecar_roots or [self.index_root / "sections"])]
        self.batch = batch
        self._stores: dict[str, AbstractStore | None] = {}
        self.stats: collections.Counter = collections.Counter()
        self.skipped_by_section: collections.Counter = collections.Counter()
        self.timers: collections.Counter = collections.Counter()

    def close(self) -> None:
        self.db.close()

    def store_for(self, section: str) -> AbstractStore | None:
        if section not in self._stores:
            self._stores[section] = None
            for root in self.roots:
                p = root / section / "abstracts.sqlite"
                if p.exists() or (p.with_suffix(".sqlite.flat") / DICTS_STAMP).exists():
                    self._stores[section] = AbstractStore(p)
                    break
        return self._stores[section]

    def records_for_rows(self, rows: list[tuple]) -> list[DocRecord]:
        """meta rows (id, title, doi, year, type, is_oa, section) -> DocRecords
        for the rows whose abstract is available locally."""
        by_sec: dict[str, list[tuple]] = collections.defaultdict(list)
        for row in rows:
            by_sec[row[6] or ""].append(row)
        out = []
        for sec, sec_rows in by_sec.items():
            store = self.store_for(sec)
            if store is None:
                self.skipped_by_section[sec] += len(sec_rows)
                self.stats["skipped_no_local_sidecar"] += len(sec_rows)
                continue
            ids = [f"W{r[0]}" for r in sec_rows]
            t = time.perf_counter()
            abstracts = store.fetch(ids)
            self.timers["abstract_fetch_s"] += time.perf_counter() - t
            for wid, r in zip(ids, sec_rows):
                ab = abstracts.get(wid)
                if ab is None:
                    self.stats["skipped_abstract_missing"] += 1
                    continue
                out.append(base_record(wid, r[1], r[2], r[3], r[4], r[5], ab))
        return out

    def _write(self, recs: list[DocRecord], state: tuple[str, dict] | None) -> None:
        t = time.perf_counter()
        rows = [(r.id, r.content_hash(), r.encode_hash()) for r in recs]
        t1 = time.perf_counter()
        self.ledger.seed_base(rows, state)
        self.timers["hash_s"] += t1 - t
        self.timers["ledger_write_s"] += time.perf_counter() - t1
        self.stats["seeded"] += len(recs)

    def seed_ids(self, ids: Iterable[str]) -> dict:
        """Seed an explicit list of W-ids (pilot / targeted repair)."""
        t0, io0 = self._start()
        nums = sorted({int(i[1:]) for i in ids if i.startswith("W") and i[1:].isdigit()})
        for s in range(0, len(nums), self.batch):
            chunk = nums[s:s + self.batch]
            rows = []
            for i in range(0, len(chunk), 500):
                sub = chunk[i:i + 500]
                t = time.perf_counter()
                rows += self.db.execute(
                    f"SELECT id, title, doi, year, type, is_oa, section FROM docs "
                    f"WHERE id IN ({','.join('?' * len(sub))})", sub).fetchall()
                self.timers["meta_s"] += time.perf_counter() - t
            self.stats["meta_rows"] += len(rows)
            self.stats["meta_missing"] += len(chunk) - len(rows)
            self._write(self.records_for_rows(rows), None)
        return self._report(t0, io0)

    def seed_range(self, lo: int, hi: int, *, limit: int | None = None,
                   sections: set[str] | None = None) -> dict:
        """Seed meta ids in [lo, hi) in id order. Resumes from the ledger cursor
        `base_seed:<lo>-<hi>`; `limit` caps meta rows scanned in this call.
        `sections` restricts seeding to those sections (others are skipped
        and counted, so a partial seed is explicit)."""
        t0, io0 = self._start()
        key = f"{SEED_SOURCE}:{lo}-{hi}"
        st = self.ledger.source_state(key)
        cursor = int(st.get("cursor", lo - 1))
        scanned = 0
        while True:
            n = self.batch if limit is None else min(self.batch, limit - scanned)
            if n <= 0:
                break
            t = time.perf_counter()
            rows = self.db.execute(
                "SELECT id, title, doi, year, type, is_oa, section FROM docs "
                "WHERE id > ? AND id < ? ORDER BY id LIMIT ?", (cursor, hi, n)).fetchall()
            self.timers["meta_s"] += time.perf_counter() - t
            if not rows:
                st["done"] = True
                self.ledger.save_source_state(key, {**st, "cursor": cursor})
                break
            scanned += len(rows)
            self.stats["meta_rows"] += len(rows)
            keep = rows
            if sections is not None:
                keep = [r for r in rows if r[6] in sections]
                self.stats["skipped_section_filter"] += len(rows) - len(keep)
            cursor = rows[-1][0]
            st = {**st, "cursor": cursor, "lo": lo, "hi": hi}
            self._write(self.records_for_rows(keep), (key, st))
        return {**self._report(t0, io0), "cursor": cursor, "done": bool(st.get("done"))}

    def _start(self) -> tuple[float, dict]:
        self.stats.clear()
        self.skipped_by_section.clear()
        self.timers.clear()
        return time.time(), _proc_io()

    def _report(self, t0: float, io0: dict) -> dict:
        io1 = _proc_io()
        return {"stats": dict(self.stats), "skipped_by_section": dict(self.skipped_by_section),
                "wall_s": round(time.time() - t0, 3),
                "timers_s": {k: round(v, 3) for k, v in self.timers.items()},
                "io_delta": {k: io1.get(k, 0) - io0.get(k, 0)
                             for k in ("rchar", "read_bytes", "syscr", "majflt")},
                "maxrss_kb": io1.get("maxrss_kb"), "meta_path": str(self.meta_path),
                "sidecar_roots": [str(r) for r in self.roots]}
