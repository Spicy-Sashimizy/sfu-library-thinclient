#!/usr/bin/env python3
"""WSL2 re-host (wslrh) convergence ladder cell — the judged R2 driver
(`r2_convergence_ladder.py`, untouched) plus the three §3 lever arms of
`spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md` (2026-09-29, §6 gap 2).

What is byte-for-byte the R2 driver (so old R2 cells stay comparable):
  * the load (`HybridSeismicBackend.from_manifest(load_mode="mmap")` under
    whatever `SFU_SEISMIC_PREFLOOR_HOTSET` the orchestrator exported),
  * the pass loop, the 40-query fixed mix, the convergence rule (after
    >= --min-passes: near-zero OR plateau x2, else maxpass), the per-pass
    record, the F6 empty-result refusal (exit 3), the VmSwap rule.

What is added (every addition is a new JSON key; no R2 key changes meaning):
  * --arm {classic,mglru}: recorded AND verified against
    /sys/kernel/mm/lru_gen/enabled (t23 rule; mismatch exits 4 before the
    index is touched — N8 protocol pin);
  * --postload-reclaim-bytes N: the L3 map-blind one-shot nudge, the
    `t23_convergence_ladder.py` implementation verbatim (memory.reclaim write;
    short write / EAGAIN / EBUSY recorded in write_status, never raised);
  * --f5-release-except SIDECAR: the F5 map-guided residue eviction — after
    load and before pass 1, call the fork's `release_pages_except(<hot
    extents>)` on every shard, keeping exactly the extents
    `prefault_hotset()` prefaulted (same budget clamp, same
    `_coalesce_extents`), so what stays resident by name is what the F6
    prefault put there. SIDECAR is a sidecar filename resolved under every
    shard's `.mmap/` dir (e.g. `hotset_hot50_1.6gb.json`, the one the
    `SFU_SEISMIC_PREFLOOR_HOTSET=1` load prefaults at budget 1.6 GB) or a
    path to one shard's sidecar, whose basename is used for all shards. A
    missing, wrong-schema or version-mismatched sidecar exits 5: an F5 cell
    without its map is not an F5 cell and must not produce a plausible
    record;
  * the F5 and L3 blocks share one shape (`requested_bytes`, `freed_bytes`,
    `write_status`, `pre_gauges`, `post_gauges`, `elapsed_s`, plus
    `rssfile_pre`/`rssfile_post` in BYTES and `hot_resident_pct_pre`/`_post`)
    so W7 compares them field-for-field. F5 additionally records
    `released_bytes` (the hook's own return), the per-slab breakdown when the
    served `.so` carries the 2026-08-31 scope fix
    (`release_pages_except_by_slab`), and `scope`, which names which hook
    answered: `all_slabs` (fixed `.so`) or `forward_slab_only_prefix_hook`
    (pre-fix `.so` — the 2026-07-14 NULL scope; the cell is then NOT a valid
    test of the parent claim and says so in its JSON);
  * `hot_resident_pct` = 100 x (resident pages / pages) over the kept hot
    extents of every shard's `forward_data.bin`, read with mincore(2) on a
    private read-only mapping of the file (page-cache residency is per file,
    so a fresh mapping sees what the index's mapping sees; mincore never
    faults a page in). Pre = after load, post = after the lever;
  * the §9 `rehost` block (host facts, the §2 constants, lever, cap, arm,
    replicate, the f5_release block, vmswap max, the figure-8
    classification: near-zero | transient | plateau; `timeout` is the
    orchestrator's, written only from a shed);
  * after either lever the cgroup / vmstat baselines are re-read so pass-1
    deltas are query-only (the t23 L3 rule; the lever's own scan/steal
    activity lives in its pre/post gauges, not in pass 1).

The cell does NOT cap itself. `spike/convergence_repro/wslrh_orchestrator.sh`
wraps it in a memory-capped sibling (docker `--memory` from the Windows host,
the R2 mechanism, or a `systemd-run` scope as root in the WSL2 distro) and
drops the shared page cache before each cell. The cgroup dir is resolved from
/proc/self/cgroup (t23 rule), which is the namespace root `/sys/fs/cgroup`
inside a docker sibling — the R2 assumption, unchanged there.

Usage (inside the capped sibling, from repo root):
  .venv/bin/python3 scripts/seismic_testbed/wslrh_convergence_ladder.py \
      --arm classic --cap-label 12g --replicate 1 \
      --result-file data/eval_results/wslrh_L0_classic_cap12g_rep1_20260929.json
  ... --f5-release-except hotset_hot50_1.6gb.json      (lever F5)
  ... --postload-reclaim-bytes 9300000000              (lever L3)
"""
import argparse
import ctypes
import errno
import json
import logging
import os
import re
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("wslrh")

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
ENCODED = "data/eval_results/e7b_encoded_queries.json"
LRU_GEN = Path("/sys/kernel/mm/lru_gen/enabled")
PAGE = 4096

REHOST_CONSTANTS = {"hot_set_gb": 10.1, "anon_gb": 1.2,
                    "lower_boundary_gb": 11.3, "footprint_gb": 19.4,
                    "source": "R1/R2/R3 2026-07-14/15/16"}
TRANSIENT_FACTOR = 5.0

CG_COUNTERS = ("pgfault", "pgmajfault", "pgscan", "pgsteal",
               "pgscan_kswapd", "pgscan_direct",
               "pgsteal_kswapd", "pgsteal_direct",
               "workingset_refault_file", "workingset_activate_file",
               "workingset_restore_file", "workingset_nodereclaim")
CG_GAUGES = ("anon", "file", "file_mapped", "active_file", "inactive_file",
             "unevictable")
VMSTAT_KEYS = ("pgscan_kswapd", "pgscan_direct", "pgsteal_kswapd",
               "pgsteal_direct", "pgmajfault", "workingset_refault_file",
               "workingset_activate_file")

F5_SLABS_ALL = ("forward_data.bin", "forward_offsets.bin", "posting_lists.bin",
                "document_mapping_offsets.bin", "document_mapping_strings.bin")
F5_SLABS_FORWARD_ONLY = ("forward_data.bin",)


def own_cgroup_dir() -> Path:
    """The cgroup-v2 dir this process is charged to. `0::/` (a docker sibling)
    resolves to the namespace root /sys/fs/cgroup, the R2 assumption."""
    try:
        line = Path("/proc/self/cgroup").read_text().strip()
    except OSError:
        return Path("/sys/fs/cgroup")
    rel = line.split("::", 1)[1] if "::" in line else "/"
    return Path("/sys/fs/cgroup") / rel.lstrip("/")


CG = own_cgroup_dir()


def read_majflt() -> int:
    return int(Path("/proc/self/stat").read_text().split()[11])


def read_vm() -> dict:
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        for k in ("VmRSS", "VmSwap", "RssFile", "RssAnon"):
            if line.startswith(k + ":"):
                out[k.lower() + "_kb"] = int(line.split()[1])
    return out


def read_cgstat() -> dict:
    """This cgroup's memory.stat (+ memory.current), or {}."""
    try:
        d = {}
        for line in (CG / "memory.stat").read_text().splitlines():
            k, _, v = line.partition(" ")
            d[k] = int(v)
        d["memory_current"] = int((CG / "memory.current").read_text())
        return d
    except (OSError, ValueError) as e:
        log.warning("cgroup memory.stat unreadable at %s: %s", CG, e)
        return {}


def read_vmstat() -> dict:
    try:
        d = {}
        for line in Path("/proc/vmstat").read_text().splitlines():
            k, _, v = line.partition(" ")
            if k in VMSTAT_KEYS:
                d[k] = int(v)
        return d
    except OSError:
        return {}


def read_meminfo_kb(key: str):
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith(key + ":"):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def deltas(now: dict, prev: dict, keys) -> dict:
    return {k: now[k] - prev[k] for k in keys if k in now and k in prev}


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


_libc = None


def _libc_handle():
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(None, use_errno=True)
        _libc.mmap.restype = ctypes.c_void_p
        _libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_long]
        _libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        _libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_ubyte)]
        _libc.mincore.restype = ctypes.c_int
    return _libc


def file_residency_bits(path: Path):
    """Page-cache residency bitmap (one uint8 per page, low bit = resident) of
    `path`, via mincore(2) on a private read-only mapping of the whole file.
    Returns None when the file cannot be mapped or mincore is refused."""
    import numpy as np
    libc = _libc_handle()
    size = path.stat().st_size
    if size == 0:
        return np.zeros(0, dtype=np.uint8)
    n_pages = (size + PAGE - 1) // PAGE
    fd = os.open(str(path), os.O_RDONLY)
    try:
        addr = libc.mmap(None, size, 1, 2, fd, 0)
    finally:
        os.close(fd)
    if not addr or addr == ctypes.c_void_p(-1).value:
        return None
    try:
        vec = (ctypes.c_ubyte * n_pages)()
        rc = libc.mincore(ctypes.c_void_p(addr), size, vec)
        if rc != 0:
            return None
        return np.frombuffer(bytes(vec), dtype=np.uint8) & 1
    finally:
        libc.munmap(ctypes.c_void_p(addr), size)


def hot_residency(plan) -> dict:
    """Resident-vs-total pages over each shard's kept hot extents of
    forward_data.bin. `plan` rows: (shard_dir, idx, extents, kept_bytes)."""
    resident = total = 0
    unreadable = 0
    for shard_dir, _idx, extents, _kept in plan:
        bits = file_residency_bits(Path(shard_dir) / "forward_data.bin")
        if bits is None:
            unreadable += 1
            continue
        n = len(bits)
        for s, ln in extents:
            lo, hi = min(s, n), min(s + ln, n)
            total += hi - lo
            resident += int(bits[lo:hi].sum())
    pct = round(100.0 * resident / total, 4) if total else None
    return {"hot_pages_total": total, "hot_pages_resident": resident,
            "hot_resident_pct": pct, "shards_unreadable": unreadable}


def build_hot_plan(sb, sidecar_arg: str, strict: bool):
    """Per shard, the hot extents F6's `prefault_hotset()` prefaulted from
    the named sidecar — same budget clamp, same `_coalesce_extents`. Returns
    (plan, sidecar_name). With strict=True a missing / wrong-schema /
    version-mismatched sidecar exits 5 (an F5 cell without its map is not an
    F5 cell); with strict=False (the residency readout for L0/L3) the shard is
    skipped and the readout degrades to the shards that have a map."""
    from lib.thinclient.sharded_seismic_backend import (
        _coalesce_extents, _hotset_version_mismatch)
    sidecar_name = Path(sidecar_arg).name
    plan = []
    for idx, shard_dir in zip(sb.shards, sb._shard_mmap_dirs):
        if idx is None or not shard_dir:
            if strict:
                log.error("F5: shard has no mmap dir / failed to load — exit 5")
                sys.exit(5)
            continue
        sidecar_path = Path(shard_dir) / sidecar_name
        if not sidecar_path.is_file():
            if strict:
                log.error("F5: sidecar absent %s — exit 5", sidecar_path)
                sys.exit(5)
            continue
        sc = json.loads(sidecar_path.read_text())
        if sc.get("schema") != "seismic.hotset.v1":
            if strict:
                log.error("F5: %s schema %r != seismic.hotset.v1 — exit 5",
                          sidecar_path, sc.get("schema"))
                sys.exit(5)
            continue
        try:
            shard_man = json.loads((Path(shard_dir) / "manifest.json").read_text())
        except OSError:
            shard_man = {}
        miss = _hotset_version_mismatch(sc.get("version_keys", {}), shard_man)
        if miss:
            if strict:
                log.error("F5: REFUSING %s — version-key mismatch: %s — exit 5",
                          sidecar_path, miss)
                sys.exit(5)
            continue
        budget = int(sc.get("budget_bytes_per_shard")
                     or (1.6e9 / max(1, len(sb.shards))))
        take, acc = [], 0
        for page_start, page_len in sc.get("extents", []):
            nbytes = page_len * PAGE
            if acc + nbytes > budget and acc > 0:
                break
            take.append((page_start, page_len))
            acc += nbytes
        take = [tuple(e) for e in _coalesce_extents(take)]
        kept = sum(ln for _, ln in take) * PAGE
        plan.append((shard_dir, idx, take, kept))
    return plan, sidecar_name


def slab_bytes(shard_dir, names) -> int:
    total = 0
    for n in names:
        try:
            total += (Path(shard_dir) / n).stat().st_size
        except OSError:
            pass
    return total


def residency_snapshot(plan) -> dict:
    rss = read_vm().get("rssfile_kb")
    hot = hot_residency(plan) if plan else {"hot_pages_total": 0,
                                            "hot_pages_resident": 0,
                                            "hot_resident_pct": None,
                                            "shards_unreadable": 0}
    return {"rssfile": rss * 1024 if rss is not None else None, **hot}


def f5_release_except(sb, plan, sidecar_name: str, keep_structural: bool) -> dict:
    """Lever F5: `release_pages_except(hot extents)` on every shard, with the
    residency accounting the 2026-07-14 NULL lacked (RssFile and hot-set
    residency before and after, per-slab breakdown, and the hook scope)."""
    by_slab_present = all(getattr(idx, "release_pages_except_by_slab", None)
                          is not None for _d, idx, _e, _k in plan)
    scope = "all_slabs" if by_slab_present and not keep_structural else (
        "forward_slab_only_keep_structural" if by_slab_present
        else "forward_slab_only_prefix_hook")
    slabs = F5_SLABS_ALL if scope == "all_slabs" else F5_SLABS_FORWARD_ONLY
    requested = sum(slab_bytes(d, slabs) - k for d, _i, _e, k in plan)
    kept_bytes = sum(k for _d, _i, _e, k in plan)
    kept_extents = sum(len(e) for _d, _i, e, _k in plan)
    if not by_slab_present:
        log.warning("F5: the loaded seismic .so predates the 2026-08-31 scope "
                    "fix (no release_pages_except_by_slab) — this cell "
                    "reproduces the 2026-07-14 NULL scope, not the fixed one")
    pre = residency_snapshot(plan)
    cg_pre = read_cgstat()
    released = 0
    by_slab: dict = {}
    status = "ok"
    t0 = time.perf_counter()
    try:
        for _d, idx, ext, _k in plan:
            fn = getattr(idx, "release_pages_except_by_slab", None)
            if fn is not None:
                rows = fn(ext, keep_structural)
                for name, nbytes in rows:
                    by_slab[name] = by_slab.get(name, 0) + int(nbytes)
                released += sum(int(n) for _n, n in rows)
            else:
                released += int(idx.release_pages_except(ext, keep_structural))
    except Exception as e:
        status = "%s: %s" % (type(e).__name__, e)
    elapsed = time.perf_counter() - t0
    cg_post = read_cgstat()
    post = residency_snapshot(plan)
    return {"requested_bytes": requested,
            "released_bytes": released,
            "freed_bytes": (cg_pre["memory_current"] - cg_post["memory_current"])
            if "memory_current" in cg_pre and "memory_current" in cg_post else None,
            "write_status": status,
            "pre_gauges": {k: cg_pre[k] for k in CG_GAUGES if k in cg_pre},
            "post_gauges": {k: cg_post[k] for k in CG_GAUGES if k in cg_post},
            "elapsed_s": round(elapsed, 3),
            "rssfile_pre": pre["rssfile"], "rssfile_post": post["rssfile"],
            "hot_resident_pct_pre": pre["hot_resident_pct"],
            "hot_resident_pct_post": post["hot_resident_pct"],
            "hot_pages_total": pre["hot_pages_total"],
            "hot_pages_resident_pre": pre["hot_pages_resident"],
            "hot_pages_resident_post": post["hot_pages_resident"],
            "sidecar": sidecar_name, "keep_structural": keep_structural,
            "kept_bytes": kept_bytes, "kept_extents": kept_extents,
            "shards": len(plan), "scope": scope,
            "scope_fix_present": by_slab_present,
            "by_slab": by_slab or None}


def postload_reclaim(nbytes: int, plan) -> dict:
    """Lever L3 (t23 implementation verbatim): write nbytes to this cgroup's
    memory.reclaim. A short write or EAGAIN/EBUSY is memory.reclaim's normal
    way of saying the kernel could not free the whole request — recorded in
    write_status, never raised. The residency readout (RssFile, hot-set
    residency) is added so the block is field-for-field comparable with F5."""
    pre_res = residency_snapshot(plan)
    pre = read_cgstat()
    payload = str(nbytes).encode()
    t0 = time.perf_counter()
    try:
        fd = os.open(str(CG / "memory.reclaim"), os.O_WRONLY)
        try:
            n = os.write(fd, payload)
        finally:
            os.close(fd)
        status = "ok" if n == len(payload) else \
            "short_write:%d/%d" % (n, len(payload))
    except OSError as e:
        status = "%s: %s" % (errno.errorcode.get(e.errno, e.errno), e.strerror)
    except Exception as e:
        status = "%s: %s" % (type(e).__name__, e)
    elapsed = time.perf_counter() - t0
    post = read_cgstat()
    post_res = residency_snapshot(plan)
    return {"requested_bytes": nbytes,
            "freed_bytes": (pre["memory_current"] - post["memory_current"])
            if "memory_current" in pre and "memory_current" in post else None,
            "write_status": status,
            "pre_gauges": {k: pre[k] for k in CG_GAUGES if k in pre},
            "post_gauges": {k: post[k] for k in CG_GAUGES if k in post},
            "elapsed_s": round(elapsed, 3),
            "rssfile_pre": pre_res["rssfile"], "rssfile_post": post_res["rssfile"],
            "hot_resident_pct_pre": pre_res["hot_resident_pct"],
            "hot_resident_pct_post": post_res["hot_resident_pct"],
            "hot_pages_total": pre_res["hot_pages_total"],
            "hot_pages_resident_pre": pre_res["hot_pages_resident"],
            "hot_pages_resident_post": post_res["hot_pages_resident"]}


F5_OFF = {"requested_bytes": 0, "released_bytes": 0, "write_status": "off",
          "elapsed_s": 0.0, "rssfile_pre": None, "rssfile_post": None,
          "hot_resident_pct_pre": None, "hot_resident_pct_post": None}


def classify(passes, converged_kind: str, near_zero: int) -> str:
    """Figure-8 classifier: near-zero = final majflt <= threshold; transient =
    converged but some pass >= 2 has p50 > 5x the converged p50; plateau =
    never near-zero."""
    if converged_kind != "near_zero":
        return "plateau"
    conv_p50 = passes[-1]["p50_ms"]
    for rec in passes[1:-1]:
        if conv_p50 > 0 and rec["p50_ms"] > TRANSIENT_FACTOR * conv_p50:
            return "transient"
    return "near-zero"


def cap_gb_from_label(label: str):
    m = re.match(r"^(?:cap)?(\d+(?:\.\d+)?)g", label)
    return float(m.group(1)) if m else None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arm", required=True, choices=("mglru", "classic"),
                    help="kernel arm; verified against lru_gen/enabled")
    ap.add_argument("--cap-label", required=True,
                    help="external cap this cell runs under (e.g. 12g) — "
                         "recorded and cross-checked against memory.max")
    ap.add_argument("--replicate", type=int, default=1,
                    help="independent cold replicate number (recorded only)")
    ap.add_argument("--min-passes", type=int, default=3)
    ap.add_argument("--max-passes", type=int, default=12)
    ap.add_argument("--near-zero-majflt", type=int, default=2500)
    ap.add_argument("--plateau-rel", type=float, default=0.10)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--postload-reclaim-bytes", type=int, default=0,
                    help="lever L3: bytes written to the cgroup's "
                         "memory.reclaim after load, before pass 1 "
                         "(0 = lever off, no postload_reclaim key emitted)")
    ap.add_argument("--f5-release-except", default=None, metavar="SIDECAR",
                    help="lever F5: hot-set sidecar filename (resolved under "
                         "every shard's .mmap dir) or a path to one shard's "
                         "sidecar; after load, before pass 1, call the fork's "
                         "release_pages_except(<its extents>) per shard")
    ap.add_argument("--f5-keep-structural", action="store_true",
                    help="F5 variant: skip the structural slabs (posting "
                         "lists, forward offsets, doc mapping) — only with "
                         "an F4 floor pin ON; NOT the §3 F5 arm")
    ap.add_argument("--residency-sidecar", default="hotset_hot50_1.6gb.json",
                    help="sidecar used for the hot_resident_pct readout of "
                         "L3 cells (F5 cells use their own)")
    ap.add_argument("--result-file", required=True)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.postload_reclaim_bytes and args.f5_release_except:
        log.error("--postload-reclaim-bytes and --f5-release-except are "
                  "different levers (L3 vs F5); one per cell — exit 2")
        sys.exit(2)
    lever = "F5" if args.f5_release_except else (
        "L3" if args.postload_reclaim_bytes else "L0")

    try:
        lru_gen = LRU_GEN.read_text().strip()
    except OSError:
        lru_gen = "absent"
    mglru_on = lru_gen not in ("absent", "") and int(lru_gen, 0) != 0
    if args.arm == "mglru" and not mglru_on or \
            args.arm == "classic" and mglru_on:
        log.error("arm=%s but lru_gen/enabled=%s — toggle mismatch, "
                  "refusing to run the cell", args.arm, lru_gen)
        sys.exit(4)

    try:
        memory_max = (CG / "memory.max").read_text().strip()
    except OSError:
        memory_max = "unreadable"
    log.info("WSLRH cell lever=%s arm=%s lru_gen=%s cap=%s rep=%d (cgroup=%s "
             "memory.max=%s): min %d / max %d passes, near-zero %d, plateau "
             "<%.0f%% x2, postload_reclaim_bytes=%d, f5_release_except=%s",
             lever, args.arm, lru_gen, args.cap_label, args.replicate, CG,
             memory_max, args.min_passes, args.max_passes,
             args.near_zero_majflt, args.plateau_rel * 100,
             args.postload_reclaim_bytes, args.f5_release_except)

    from lib.thinclient.sharded_seismic_backend import HybridSeismicBackend

    terms = json.loads((REPO / ENCODED).read_text())["terms"][:args.queries]

    cg_preload = read_cgstat()
    t0 = time.perf_counter()
    sb = HybridSeismicBackend.from_manifest(str(REPO / MANIFEST),
                                            load_mode="mmap")
    load_s = time.perf_counter() - t0
    cg_postload = read_cgstat()
    cg_prev = cg_postload
    vmstat_prev = read_vmstat()
    log.info("loaded in %.1fs  vm=%s", load_s, read_vm())

    reclaim = None
    f5 = None
    if lever == "F5":
        plan, sidecar_name = build_hot_plan(sb, args.f5_release_except, strict=True)
        f5 = f5_release_except(sb, plan, sidecar_name, args.f5_keep_structural)
        log.info("F5 release_except[%s]: requested %d released %d freed %s "
                 "status=%s (%.2fs) rssfile %s -> %s hot_resident %s%% -> %s%% "
                 "scope=%s", sidecar_name, f5["requested_bytes"],
                 f5["released_bytes"], f5["freed_bytes"], f5["write_status"],
                 f5["elapsed_s"], f5["rssfile_pre"], f5["rssfile_post"],
                 f5["hot_resident_pct_pre"], f5["hot_resident_pct_post"],
                 f5["scope"])
        if f5["by_slab"]:
            log.info("F5 per-slab released (GB): %s",
                     {k: round(v / 1e9, 3) for k, v in f5["by_slab"].items()})
        cg_prev = read_cgstat()
        vmstat_prev = read_vmstat()
    elif lever == "L3":
        plan, _ = build_hot_plan(sb, args.residency_sidecar, strict=False)
        reclaim = postload_reclaim(args.postload_reclaim_bytes, plan)
        log.info("postload reclaim: requested %d freed %s status=%s (%.2fs) "
                 "rssfile %s -> %s hot_resident %s%% -> %s%%",
                 reclaim["requested_bytes"], reclaim["freed_bytes"],
                 reclaim["write_status"], reclaim["elapsed_s"],
                 reclaim["rssfile_pre"], reclaim["rssfile_post"],
                 reclaim["hot_resident_pct_pre"], reclaim["hot_resident_pct_post"])
        cg_prev = read_cgstat()
        vmstat_prev = read_vmstat()

    passes = []
    empty = 0
    converged_kind = "maxpass"
    plateau_streak = 0
    prev_majflt = None
    for p in range(args.max_passes):
        lat, mf0 = [], read_majflt()
        t_pass = time.perf_counter()
        for q in terms:
            t = time.perf_counter()
            res = sb.search_encoded(q, args.top_k)
            lat.append((time.perf_counter() - t) * 1000.0)
            if not res:
                empty += 1
        majflt = read_majflt() - mf0
        cg_now = read_cgstat()
        vmstat_now = read_vmstat()
        rec = {"pass": p + 1,
               "p50_ms": round(statistics.median(lat), 2),
               "p95_ms": round(pctl(lat, 95), 2),
               "mean_ms": round(statistics.mean(lat), 2),
               "max_ms": round(max(lat), 2),
               "majflt": majflt,
               "ms_per_fault": round(sum(lat) / majflt, 4) if majflt else None,
               "wall_s": round(time.perf_counter() - t_pass, 1),
               "vm": read_vm(),
               "cg_delta": deltas(cg_now, cg_prev, CG_COUNTERS),
               "cg_gauges": {k: cg_now[k] for k in CG_GAUGES if k in cg_now},
               "memory_current": cg_now.get("memory_current"),
               "vmstat_global_delta": deltas(vmstat_now, vmstat_prev,
                                             VMSTAT_KEYS)}
        passes.append(rec)
        cg_prev, vmstat_prev = cg_now, vmstat_now
        log.info("pass %d: p50 %.0f ms majflt %d (%.3f ms/flt) pgscan %s "
                 "ws_refault %s wall %.0fs", p + 1, rec["p50_ms"], majflt,
                 (sum(lat) / majflt) if majflt else 0.0,
                 rec["cg_delta"].get("pgscan", "n/a"),
                 rec["cg_delta"].get("workingset_refault_file", "n/a"),
                 rec["wall_s"])

        if prev_majflt is not None and prev_majflt > 0 and \
                abs(majflt - prev_majflt) / prev_majflt < args.plateau_rel:
            plateau_streak += 1
        else:
            plateau_streak = 0
        prev_majflt = majflt
        if p + 1 >= args.min_passes:
            if majflt <= args.near_zero_majflt:
                converged_kind = "near_zero"
                break
            if plateau_streak >= 2:
                converged_kind = "plateau"
                break

    if empty:
        log.error("%d empty results — serving path broken under this cap; "
                  "refusing to write a latency record (F6 lesson)", empty)
        sys.exit(3)

    final = passes[-1]
    swap_kb = max(p["vm"].get("vmswap_kb", 0) for p in passes)
    mem_total_kb = read_meminfo_kb("MemTotal")
    swap_total_kb = read_meminfo_kb("SwapTotal")
    out = {"probe": "wslrh_convergence_ladder",
           "date": time.strftime("%Y-%m-%d"),
           "lever": lever,
           "arm": args.arm, "lru_gen_enabled": lru_gen,
           "uname": " ".join(os.uname()),
           "cap": args.cap_label, "cgroup_memory_max": memory_max,
           "cgroup_dir": str(CG),
           "manifest": MANIFEST, "queries": len(terms), "top_k": args.top_k,
           "load_s": round(load_s, 1),
           "prefault_gate": os.environ.get("SFU_SEISMIC_PREFLOOR_HOTSET", "0"),
           "convergence": {
               "converged": converged_kind != "maxpass",
               "kind": converged_kind,
               "passes_to_converge": len(passes),
               "rule": {"min_passes": args.min_passes,
                        "max_passes": args.max_passes,
                        "near_zero_majflt": args.near_zero_majflt,
                        "plateau_rel": args.plateau_rel}},
           "converged_state": {"p50_ms": final["p50_ms"],
                               "p95_ms": final["p95_ms"],
                               "majflt": final["majflt"],
                               "ms_per_fault": final["ms_per_fault"]},
           "cg_load_delta": deltas(cg_postload, cg_preload, CG_COUNTERS),
           "cg_postload_gauges": {k: cg_postload[k] for k in CG_GAUGES
                                  if k in cg_postload},
           "per_pass": passes,
           "swap_confounded": swap_kb > 0,
           "vmswap_kb_max": swap_kb,
           "rehost": {
               "host": {"total_ram_gb": round(mem_total_kb / 1048576, 1)
                        if mem_total_kb else None,
                        "kernel": os.uname().release,
                        "lru_gen_enabled": lru_gen,
                        "swap_total_gb": round(swap_total_kb / 1048576, 1)
                        if swap_total_kb is not None else None,
                        "cores": os.cpu_count()},
               "constants": REHOST_CONSTANTS,
               "lever": lever,
               "cap_gb": cap_gb_from_label(args.cap_label),
               "arm": args.arm, "replicate": args.replicate,
               "f5_release": f5 if f5 is not None else dict(F5_OFF),
               "vmswap_max_kb": swap_kb,
               "classification": classify(passes, converged_kind,
                                          args.near_zero_majflt)}}
    if reclaim is not None:
        out["postload_reclaim"] = reclaim
    if f5 is not None:
        out["f5_release"] = f5
    Path(args.result_file).write_text(json.dumps(out, indent=2))
    log.info("wrote %s  lever=%s converged=%s(%s) in %d passes  final p50 "
             "%.0f ms  class=%s%s", args.result_file, lever,
             out["convergence"]["converged"], converged_kind, len(passes),
             final["p50_ms"], out["rehost"]["classification"],
             "  ** SWAP-CONFOUNDED **" if swap_kb else "")


if __name__ == "__main__":
    main()
