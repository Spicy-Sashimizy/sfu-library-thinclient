"""Build the base-side `is_oa` bitmap (issue O17 option (a)) from any source of
`(doc_id, is_oa)` pairs, in one streaming, resumable pass.

Read side + artifact format: `source/lib/thinclient/oa_overlay.py` (gate
`SFU_OA_BITMAP`). Findings: `spike/delta_ingest/OA_BITMAP_FINDINGS.md`.

Pipeline
  unit   = one resumable piece of the source (a snapshot partition, a file,
           an adapter run). `OABitmapBuilder.ingest_unit(name, pairs)` maps
           every pair whose W-id is a base doc to its base ordinal and writes
           `<work>/units/<name>.npz` atomically. A unit file present = done.
  final  = `finalize()` replays the unit files in name order (snapshot
           partitions sort by `updated_date`, so a later copy of a work wins)
           into two bit arrays over the base ordinals and writes the artifact.

Sources (all yield `(doc_id, is_oa)`; doc_id "W123", "https://openalex.org/W123"
or the int 123):
  iter_openalex_lines   fast scanner over OpenAlex works JSONL (bytes lines);
                        regex on the compact snapshot layout with a json
                        fallback for lines the regex does not match
  open_partition        local gz path or http(s)/s3 URL, streamed, no spool
  pairs_from_adapter    any `spike/delta_ingest/adapters.py` adapter
                        (DocRecord.is_oa), e.g. JsonlAdapter for a custom file

Memory: one partition's base hits (<= ~1M pairs) + the mmapped `wids.npy`
page cache; finalize holds two uint8 arrays of `rows` bytes (~300 MB at 150M).

CLI
  python -m spike.delta_ingest.oa_bitmap scan --manifest M --work W --ordinals O
         [--workers 2] [--max-parts N] [--deadline-utc ISO] [--parts-glob G]
  python -m spike.delta_ingest.oa_bitmap finalize --work W --ordinals O
         --out DIR --meta PATH
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import gzip
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "source") not in sys.path:
    sys.path.insert(0, str(REPO / "source"))

from lib.thinclient.oa_overlay import (  # noqa: E402
    FORMAT, KNOWN_FILE, OA_FILE, ORDINAL_STAMP, STAMP_FILE, meta_fingerprint)

log = logging.getLogger("delta_ingest.oa_bitmap")

_ID_RE = re.compile(rb'^\{"id":"https://openalex\.org/W(\d+)"')
_OA_RE = re.compile(rb'"open_access":\{"is_oa":(true|false)')
CHUNK = 1 << 18


def _num(doc_id) -> int | None:
    if isinstance(doc_id, (int, np.integer)):
        return int(doc_id)
    s = str(doc_id).rsplit("/", 1)[-1]
    if s[:1] in ("W", "w") and s[1:].isdigit():
        return int(s[1:])
    return None


def iter_openalex_lines(lines: Iterable[bytes], stats: dict | None = None
                        ) -> Iterator[tuple[int, bool]]:
    """`(W-number, open_access.is_oa)` per OpenAlex work line. A work with no
    `open_access` object is skipped (it stays unknown), never read as False."""
    st = stats if stats is not None else {}
    for line in lines:
        if not line or line.isspace():
            continue
        st["records"] = st.get("records", 0) + 1
        m, o = _ID_RE.match(line), _OA_RE.search(line)
        if m and o:
            yield int(m.group(1)), o.group(1) == b"true"
            continue
        st["json_fallback"] = st.get("json_fallback", 0) + 1
        try:
            w = json.loads(line)
        except ValueError:
            st["bad_json"] = st.get("bad_json", 0) + 1
            continue
        n = _num(w.get("id") or "")
        oa = (w.get("open_access") or {}).get("is_oa") if isinstance(w.get("open_access"), dict) else None
        if n is None or oa is None:
            st["no_oa_field"] = st.get("no_oa_field", 0) + 1
            continue
        yield n, bool(oa)


def https_url(url: str) -> str:
    if url.startswith("s3://openalex/"):
        return "https://openalex.s3.amazonaws.com/" + url[len("s3://openalex/"):]
    return url


@contextlib.contextmanager
def open_partition(url: str, session=None, timeout: float = 120.0):
    """Binary line iterator over a gzip'd partition: local path / file:// read
    in place, remote URL streamed through the decompressor (nothing spooled)."""
    if url.startswith("file://"):
        url = url[len("file://"):]
    if not url.startswith(("http://", "https://", "s3://")):
        with gzip.open(url, "rb") as fh:
            yield fh
        return
    import requests
    sess = session or requests.Session()
    r = sess.get(https_url(url), stream=True, timeout=(30, timeout))
    try:
        r.raise_for_status()
        r.raw.decode_content = False
        with gzip.GzipFile(fileobj=r.raw) as fh:
            yield fh
    finally:
        r.close()


def pairs_from_adapter(adapter, state: dict | None = None) -> Iterator[tuple[str, bool]]:
    """Any delta-ingest adapter (records carry `is_oa`)."""
    st = state if state is not None else {}
    for rec in adapter.iter_records(st):
        yield rec.id, bool(rec.is_oa)


def unit_file_name(unit: str) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]+", "__", unit) + ".npz"


class OABitmapBuilder:
    def __init__(self, work_dir: str | Path, ordinal_dir: str | Path):
        self.work = Path(work_dir)
        self.units = self.work / "units"
        self.units.mkdir(parents=True, exist_ok=True)
        self.ordinal_dir = Path(ordinal_dir)
        self.ostamp = json.loads((self.ordinal_dir / ORDINAL_STAMP).read_text())
        self.rows = int(self.ostamp["rows"])
        self.wids = np.load(self.ordinal_dir / "wids.npy", mmap_mode="r")
        if len(self.wids) != self.rows:
            raise ValueError("wids.npy length != ordinal stamp rows")

    def unit_path(self, unit: str) -> Path:
        return self.units / unit_file_name(unit)

    def done(self, unit: str) -> bool:
        return self.unit_path(unit).exists()

    def _map(self, nums: list[int], bits: list[bool], ords: list, vals: list, stats: dict) -> None:
        a = np.asarray(nums, dtype=np.int64)
        pos = np.clip(np.searchsorted(self.wids, a), 0, self.rows - 1)
        hit = np.asarray(self.wids[pos]) == a
        ords.append(pos[hit].astype(np.uint32))
        vals.append(np.asarray(bits, dtype=bool)[hit])
        stats["base_hits"] = stats.get("base_hits", 0) + int(hit.sum())
        stats["not_in_base"] = stats.get("not_in_base", 0) + int((~hit).sum())

    def ingest_unit(self, unit: str, pairs: Iterable, extra: dict | None = None) -> dict:
        """Map one unit's pairs to base ordinals and commit its file atomically."""
        t0 = time.time()
        stats: dict = extra if extra is not None else {}
        nums: list[int] = []
        bits: list[bool] = []
        ords: list = []
        vals: list = []
        for doc_id, is_oa in pairs:
            n = _num(doc_id)
            stats["pairs"] = stats.get("pairs", 0) + 1
            if n is None:
                stats["bad_id"] = stats.get("bad_id", 0) + 1
                continue
            nums.append(n)
            bits.append(bool(is_oa))
            if len(nums) >= CHUNK:
                self._map(nums, bits, ords, vals, stats)
                nums, bits = [], []
        if nums:
            self._map(nums, bits, ords, vals, stats)
        o = np.concatenate(ords) if ords else np.zeros(0, np.uint32)
        v = np.concatenate(vals) if vals else np.zeros(0, bool)
        stats["oa_true"] = int(v.sum())
        stats["seconds"] = round(time.time() - t0, 3)
        stats["unit"] = unit
        dst = self.unit_path(unit)
        tmp = dst.with_name(dst.name + ".tmp.npz")
        np.savez(tmp, ord=o, oa=v, stats=np.frombuffer(json.dumps(stats).encode(), dtype=np.uint8))
        os.replace(tmp, dst)
        return stats

    def finalize(self, out_dir: str | Path, meta_path: str | Path, source: dict) -> dict:
        """Replay unit files in name order (later wins) into the artifact."""
        t0 = time.time()
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        known = np.zeros(self.rows, dtype=np.uint8)
        oa = np.zeros(self.rows, dtype=np.uint8)
        files = sorted(p for p in self.units.glob("*.npz") if not p.name.endswith(".tmp.npz"))
        dup = 0
        for p in files:
            with np.load(p) as z:
                o, v = z["ord"], z["oa"]
            dup += int(known[o].sum())
            known[o] = 1
            oa[o] = v.astype(np.uint8)
        kb = np.packbits(known, bitorder="little")
        ob = np.packbits(oa & known, bitorder="little")
        h = hashlib.sha256()
        h.update(self.ostamp["ordinal_space_id"].encode())
        h.update(kb.tobytes())
        h.update(ob.tobytes())
        n_known = int(known.sum())
        n_oa = int((oa & known).sum())
        stamp = {
            "format": FORMAT,
            "rows": self.rows,
            "ordinal_space_id": self.ostamp["ordinal_space_id"],
            "ordinal_dir": str(self.ordinal_dir.resolve()),
            "meta_source": meta_fingerprint(meta_path),
            "bitmap_id": h.hexdigest()[:16],
            "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "coverage": {"known": n_known, "oa": n_oa, "not_oa": n_known - n_oa,
                         "unknown": self.rows - n_known, "units": len(files),
                         "repeat_hits": dup},
            "source": source,
        }
        for name, arr in ((KNOWN_FILE, kb), (OA_FILE, ob)):
            tmp = out / (name + ".tmp.npy")
            np.save(tmp, arr)
            os.replace(tmp, out / name)
        (out / (STAMP_FILE + ".tmp")).write_text(json.dumps(stamp, indent=2))
        os.replace(out / (STAMP_FILE + ".tmp"), out / STAMP_FILE)
        stamp["finalize_s"] = round(time.time() - t0, 3)
        return stamp


def _scan_one(args: tuple) -> dict:
    url, unit, work, ordinals, retries = args
    b = OABitmapBuilder(work, ordinals)
    if b.done(unit):
        return {"unit": unit, "skipped": True}
    last = None
    for attempt in range(1, retries + 1):
        st: dict = {"attempt": attempt}
        try:
            with open_partition(url) as fh:
                return b.ingest_unit(unit, iter_openalex_lines(fh, st), extra=st)
        except Exception as exc:
            last = exc
            log.warning("unit %s attempt %d failed: %s", unit, attempt, exc)
            time.sleep(min(60, 5 * attempt))
    return {"unit": unit, "failed": repr(last)}


def partition_unit(url: str) -> str:
    path = url.split("?", 1)[0]
    i = path.find("updated_date=")
    return path[i:] if i != -1 else path.rsplit("/", 1)[-1]


def scan_manifest(manifest: dict, work: Path, ordinals: Path, *, workers: int = 2,
                  max_parts: int | None = None, deadline: dt.datetime | None = None,
                  retries: int = 3, log_path: Path | None = None) -> dict:
    """One pass over every manifest part not yet done; resumable."""
    import multiprocessing as mp

    entries = manifest.get("files") or manifest.get("entries") or []
    todo = []
    b = OABitmapBuilder(work, ordinals)
    for e in entries:
        unit = partition_unit(e["url"])
        if not b.done(unit):
            todo.append((e["url"], unit, str(work), str(ordinals), retries))
    if max_parts:
        todo = todo[:max_parts]
    summary = {"todo": len(todo), "done": 0, "failed": 0, "records": 0, "base_hits": 0,
               "stopped_at_deadline": False}
    logf = open(log_path, "a") if log_path else None
    try:
        with mp.get_context("spawn").Pool(workers) as pool:
            it = pool.imap_unordered(_scan_one, todo)
            for res in it:
                if res.get("failed"):
                    summary["failed"] += 1
                elif not res.get("skipped"):
                    summary["done"] += 1
                    summary["records"] += res.get("records", 0)
                    summary["base_hits"] += res.get("base_hits", 0)
                if logf:
                    res["t_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                    logf.write(json.dumps(res) + "\n")
                    logf.flush()
                if deadline and dt.datetime.now(dt.timezone.utc) >= deadline:
                    summary["stopped_at_deadline"] = True
                    pool.terminate()
                    break
    finally:
        if logf:
            logf.close()
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "finalize"])
    ap.add_argument("--manifest")
    ap.add_argument("--work", required=True)
    ap.add_argument("--ordinals", required=True)
    ap.add_argument("--out")
    ap.add_argument("--meta")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-parts", type=int, default=None)
    ap.add_argument("--deadline-utc", default=None)
    ap.add_argument("--source-note", default="")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    work = Path(args.work)
    if args.cmd == "scan":
        src = args.manifest
        if src.startswith(("http://", "https://")):
            import requests
            manifest = requests.get(src, timeout=120).json()
        else:
            manifest = json.loads(Path(src).read_text())
        deadline = (dt.datetime.fromisoformat(args.deadline_utc.replace("Z", "+00:00"))
                    if args.deadline_utc else None)
        res = scan_manifest(manifest, work, Path(args.ordinals), workers=args.workers,
                            max_parts=args.max_parts, deadline=deadline,
                            log_path=work / "scan_log.jsonl")
    else:
        b = OABitmapBuilder(work, Path(args.ordinals))
        res = b.finalize(args.out, args.meta, {"work": str(work), "note": args.source_note})
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
