#!/usr/bin/env python3
"""R3 instrument 4 (2026-07-16; doc 15 §1/§3): between-pass per-extent
residency snapshot via cachestat(2) syscall 451 (kernel ≥ 6.5), with a
mincore(2) fallback if REQ-1 reported cachestat unavailable.

A literal picture of where the residue sits at pass k under 12 GB vs 16 GB:
per fixed 2 MiB extent across every shard's forward_data.bin slab, snapshot
  cache              — pages currently resident
  evicted            — pages evicted at least once (cumulative)
  recently_evicted   — evicted and not re-touched since (shadow-entry half)

The between-pass maps are the "kernel still sorting" state of 04-doc §2 drawn
as a map (doc 15 §1 expectation #3). Two snapshots (pre-cell, post-pass-k)
bracket each pass; the delta = what that pass evicted.

Extent size = 2 MiB: large enough that the snapshot is cheap (one cachestat
call per extent per shard, ~16k extents total vs ~8M pages via mincore), small
enough to localize residue placement for the per-query attribution join. 2 MiB
matches the kernel's huge-page readahead unit, so it's the natural fault
granularity boundary. < 2 MiB over-resolves; > 8 MiB loses the inversion's
per-query resolution.

cachestat(2): int cachestat(int fd, struct cachestat_range *crange,
                            struct cachestat *cstat, unsigned int flags).
  struct cachestat_range { __u64 off, len; }
  struct cachestat       { __u64 nr_cache, nr_dirty, nr_writeback,
                            nr_evicted, nr_recently_evicted; }
The fallback (mincore) gives only the residency bit (nr_cache); the evicted /
recently_evicted halves are lost — recorded (doc 15 §1: "the maps lose the
shadow-entry half").
"""
import argparse
import ctypes
import errno
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

EXTENT = 2 * 1024 * 1024   # 2 MiB fixed extent (documented above)
NR_CACHESTAT = 451        # x86_64 syscall number

_libc = ctypes.CDLL(None, use_errno=True)


class _cachestat_range(ctypes.Structure):
    _fields_ = [("off", ctypes.c_uint64), ("len", ctypes.c_uint64)]


class _cachestat(ctypes.Structure):
    _fields_ = [("nr_cache", ctypes.c_uint64), ("nr_dirty", ctypes.c_uint64),
                ("nr_writeback", ctypes.c_uint64),
                ("nr_evicted", ctypes.c_uint64),
                ("nr_recently_evicted", ctypes.c_uint64)]


def cachestat(fd: int, off: int, length: int):
    """Issue cachestat(2) on [off, off+length) of `fd`. Returns the _cachestat
    struct, or None on EPERM/ENOSYS (→ caller falls back to mincore)."""
    _libc.syscall.restype = ctypes.c_long
    _libc.syscall.argtypes = [ctypes.c_long, ctypes.c_int,
                              ctypes.POINTER(_cachestat_range),
                              ctypes.POINTER(_cachestat), ctypes.c_uint]
    r = _cachestat_range(off, length)
    s = _cachestat(0, 0, 0, 0, 0)
    _libc.syscall(NR_CACHESTAT, fd, ctypes.byref(r), ctypes.byref(s), 0)
    e = ctypes.get_errno()
    if e in (errno.EPERM, errno.ENOSYS, errno.EINVAL):
        return None
    return s


def mincore_residency(fd: int, off: int, length: int, page=4096) -> int:
    """Fallback: count resident PAGES in [off, off+length) via mincore(2) on a
    private read-only mmap of that file range. Returns nr_cache-equivalent
    (page count); the evicted / recently_evicted halves are UNAVAILABLE under
    mincore (the shadow-entry half lost — doc 15 §1 recorded limitation).
    Returns -1 if mincore cannot be issued (page-cache not mmap-able)."""
    import mmap
    n_pages = (length + page - 1) // page
    if n_pages == 0:
        return 0
    # mmap the whole file (off-relative mmap of a slice isn't directly
    # supported by Python's mmap; we map the file from 0 and mincore the
    # [off, off+length) sub-range via the vector — but Python mmap lacks the
    # raw kernel addr. Use ctypes to mmap ourselves so we hold the pointer.
    libc_mmap = _libc.mmap
    libc_mmap.restype = ctypes.c_void_p
    libc_mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_long]
    PROT_READ, MAP_PRIVATE = 1, 2
    addr = libc_mmap(None, off + length, PROT_READ, MAP_PRIVATE, fd, 0)
    if not addr or addr == ctypes.c_void_p(-1).value:
        return -1
    try:
        vec = (ctypes.c_ubyte * n_pages)()
        _libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_ubyte)]
        _libc.mincore.restype = ctypes.c_int
        rc = _libc.mincore(ctypes.c_void_p(addr + off), length, vec)
        if rc != 0:
            return -1
        return int(sum(1 for b in vec if b & 1))
    finally:
        _libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        _libc.munmap(ctypes.c_void_p(addr), off + length)


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_inode_map(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def snapshot_one_extent(fd: int, off: int, length: int, mode: str) -> dict:
    """Residency record for one extent under `mode`."""
    rec = {}
    if mode == "cachestat":
        cs = cachestat(fd, off, length)
        if cs is None:
            return {"nr_cache": None, "nr_evicted": None,
                    "nr_recently_evicted": None,
                    "note": "cachestat-denied"}
        rec = {"nr_cache": int(cs.nr_cache),
               "nr_dirty": int(cs.nr_dirty),
               "nr_evicted": int(cs.nr_evicted),
               "nr_recently_evicted": int(cs.nr_recently_evicted)}
    else:  # mincore fallback
        n = mincore_residency(fd, off, length)
        rec = {"nr_cache": n if n >= 0 else None,
               "nr_evicted": None,
               "nr_recently_evicted": None,
               "note": "mincore-residency-only" if n >= 0
                       else "mincore-unavailable"}
    return rec


def snapshot(ino_map: dict, mode: str, label: str, extent: int = EXTENT):
    """Snapshot residency per (shard, extent) for every forward slab.
    mode = 'cachestat' | 'mincore'. On first cachestat denial, the caller
    (main) re-runs in mincore mode — snapshot does NOT auto-switch (keeps
    one clean mode per output file for the join's bookkeeping)."""
    recs = []
    for f in ino_map["files"]:
        if f["slab"] != "forward":
            continue  # only forward_data.bin carries the repeat set
        path = REPO / f["path"]
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError as e:
            log(f"  {f['path']}: open failed {e}")
            continue
        try:
            size = f["size"]
            off = 0
            ext_idx = 0
            while off < size:
                length = min(extent, size - off)
                rec = {"shard": f["shard"], "ino": f["ino"],
                       "extent": ext_idx, "off": off, "len": length}
                rec.update(snapshot_one_extent(fd, off, length, mode))
                recs.append(rec)
                off += extent
                ext_idx += 1
        finally:
            os.close(fd)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inode-map", default="data/eval_results/_r3_inode_map.json")
    ap.add_argument("--label", required=True,
                    help="cell + pass label for the output file, e.g. 12g_instr_preload")
    ap.add_argument("--mode", choices=("cachestat", "mincore", "auto"),
                    default="auto",
                    help="cachestat: syscall 451 (full). mincore: residency "
                         "bit only (fallback when REQ-1 said cachestat-FAIL). "
                         "auto: try cachestat, fall back on first EPERM.")
    ap.add_argument("--out-dir", default="data/eval_results")
    args = ap.parse_args()

    ino_map = load_inode_map(REPO / args.inode_map)
    mode = args.mode
    if mode == "auto":
        mode = "cachestat"  # snapshot() flips to mincore on denial
    log(f"cachestat snapshot label={args.label} mode={mode} "
        f"extent=2MiB over {sum(1 for f in ino_map['files'] if f['slab']=='forward')} fwd slabs")

    t0 = time.perf_counter()
    recs = snapshot(ino_map, mode, args.label)
    dt = time.perf_counter() - t0

    # auto: if cachestat denied on every extent (recs carry the denied note),
    # re-run in mincore so the between-pass map still has a residency signal.
    if mode == "cachestat" and recs and all(
            r.get("note") == "cachestat-denied" for r in recs):
        log("cachestat denied on all extents — falling back to mincore")
        mode = "mincore"
        recs = snapshot(ino_map, mode, args.label)
        dt = time.perf_counter() - t0

    n_cache = sum(r["nr_cache"] or 0 for r in recs
                  if isinstance(r.get("nr_cache"), int))
    n_evi = sum(r["nr_evicted"] or 0 for r in recs
                if isinstance(r.get("nr_evicted"), int))
    n_rec = sum(r["nr_recently_evicted"] or 0 for r in recs
                if isinstance(r.get("nr_recently_evicted"), int))
    out = {"probe": "r3_cachestat_map", "date": time.strftime("%Y-%m-%d"),
           "label": args.label, "mode": mode, "extent_bytes": EXTENT,
           "n_extents": len(recs),
           "totals": {"nr_cache_pages": n_cache, "nr_evicted_pages": n_evi,
                      "nr_recently_evicted_pages": n_rec},
           "cache_gb": round(n_cache * 4096 / 1e9, 4),
           "evicted_gb": round(n_evi * 4096 / 1e9, 4),
           "snapshot_s": round(dt, 1),
           "extents": recs}
    outp = Path(args.out_dir) / f"_r3_cachestat_{args.label}.json"
    outp.write_text(json.dumps(out, indent=2))
    log(f"wrote {outp}: {len(recs)} extents cache={out['cache_gb']}GB "
        f"evicted={out['evicted_gb']}GB mode={mode} in {dt:.1f}s")


if __name__ == "__main__":
    main()
