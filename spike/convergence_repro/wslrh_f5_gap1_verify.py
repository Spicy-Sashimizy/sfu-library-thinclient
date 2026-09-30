#!/usr/bin/env python3
"""WSL2 re-host §6 gap 1 — F5 `release_pages_except` mechanism check on the
REAL stack (the 8 served dv-v2 shards), rebuilt-.so arm vs served-.so arm.

Pre-registration: spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md
§5 item 3 / §6 gap 1.  This driver is the *mechanism* check only — it runs
UNCAPPED (this container has no cgroup write access, no docker, no
systemd-run), so it is NOT the §5 calibration record "F5 classic at 16 GB".
What it can establish on this host:

  (a) released bytes vs the residue the call is meant to remove
      (prereg expectation: footprint − hot set ≈ 9.3 GB *under a cap*; at
      load, uncapped, the residue is RssFile_pre − hot-set-kept bytes — both
      are recorded, neither is silently substituted for the other);
  (b) RssFile ACTUALLY falls (the 2026-07-14 null reported "released
      16.45 GB" with RssFile unchanged — this is the regression test);
  (c) what leaves is residue, not hot set: post-release hot-set residency
      ≥ 90 % of its pre-release value.

Residency is measured two ways, on the .so's OWN mappings (base address from
/proc/self/maps, matched by slab path):

  * `mapped_pct`     — /proc/self/pagemap bit 63 ("page present" in THIS
                       process's page table).  MADV_DONTNEED on a shared
                       file mapping drops exactly these, so this is the
                       measure the F5 claim is about.
  * `pagecache_pct`  — mincore(2).  Uncapped, DONTNEED does NOT evict a
                       clean file page from the page cache, so this is
                       expected to stay ~100 % in both arms; it is recorded
                       so the two mechanisms are never conflated again.

Per-slab RssFile is taken from /proc/self/smaps (the .so's mappings of the
five slab files per shard, summed over the 8 shards) so the structural
residue — the thing the 2026-08-31 scope fix addresses — is visible
slab-by-slab in BOTH arms, even on the served .so that lacks the
`release_pages_except_by_slab` reporting hook.

Two arms, each its own subprocess under `flock /tmp/sfu_latency_measure.lock`
(never skipped — another agent may hold it):

  fixed    — the rebuilt portable .so (fork 2c4d863, -C target-cpu=x86-64-v3)
             loaded by sys.path prepend of `--so-dir`; served binary untouched.
  control  — the served .so (pre-fix hook: forward slab only).

Both arms load with SFU_SEISMIC_PREFLOOR_HOTSET=1 (the residue-bearing
production load path, hot50_1.6gb prefault), release with the SAME pinned
extents the backend prefaulted (budget 1.6e9/8 per shard, gap-coalesced via
the backend's `_coalesce_extents`), then run the 40 pre-encoded e7b queries
once to confirm the index still serves; the fixed arm's top-10 is compared to
the control arm's (overlap@10) as a parity side-check.

Usage (from repo root; the driver mode runs both arms and writes the combined
record):

  .venv/bin/python3 spike/convergence_repro/wslrh_f5_gap1_verify.py \
      --so-dir /path/to/dir/containing/seismic_pkg \
      --out data/eval_results/wslrh_f5_gap1_verify_2026-09-29.json
"""
import argparse
import ctypes
import hashlib
import json
import logging
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
ENCODED = REPO / "data/eval_results/e7b_encoded_queries.json"
LOCK = "/tmp/sfu_latency_measure.lock"
SLABS = ("forward_data.bin", "forward_offsets.bin", "posting_lists.bin",
         "document_mapping_strings.bin", "document_mapping_offsets.bin")
PAGE = 4096

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("wslrh_f5")


# ── process accounting ─────────────────────────────────────────────────────

def read_vm() -> dict:
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        for k in ("VmRSS", "VmSwap", "RssFile", "RssAnon", "RssShmem"):
            if line.startswith(k + ":"):
                out[k.lower() + "_kb"] = int(line.split()[1])
    return out


def read_majflt() -> int:
    return int(Path("/proc/self/stat").read_text().split()[11])


VMSTAT_KEYS = ("pgscan_kswapd", "pgsteal_kswapd", "pgscan_direct", "pgsteal_direct",
               "workingset_refault_file", "pgmajfault")


def read_vmstat() -> dict:
    """Host-wide reclaim counters (cumulative). Recorded so an 'uncapped'
    cell can show whether kswapd was reclaiming during it — on this 31 GB
    host the page cache itself is the ceiling (measured 2026-09-29: MemFree
    ~350 MB, Cached ~27.5 GB while the warm arm ran)."""
    out = {}
    try:
        for line in Path("/proc/vmstat").read_text().splitlines():
            k, _, v = line.partition(" ")
            if k in VMSTAT_KEYS:
                out[k] = int(v)
    except OSError:
        pass
    return out


def read_meminfo_brief() -> dict:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            if k in ("MemFree", "MemAvailable", "Cached", "Active(file)", "Inactive(file)"):
                out[k + "_kb"] = int(v.split()[0])
    except OSError:
        pass
    return out


def slab_mappings(shard_dirs) -> dict:
    """{(shard_name, slab_file): (vaddr_start, vaddr_end, file_offset)} for
    the .so's mappings of each slab file (from /proc/self/maps)."""
    want = {}
    for d in shard_dirs:
        for s in SLABS:
            want[str(Path(d) / s)] = (Path(d).name, s)
    out = {}
    for line in Path("/proc/self/maps").read_text().splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        path = parts[5].strip()
        if path in want:
            a, b = parts[0].split("-")
            key = want[path]
            # memmap2 maps the whole file once; keep the offset-0 entry.
            if key not in out or int(parts[2], 16) == 0:
                out[key] = (int(a, 16), int(b, 16), int(parts[2], 16))
    return out


def slab_rss_from_smaps(shard_dirs) -> dict:
    """Per-slab Rss (kB) summed over shards, from /proc/self/smaps."""
    want = {}
    for d in shard_dirs:
        for s in SLABS:
            want[str(Path(d) / s)] = s
    totals = {s: 0 for s in SLABS}
    cur = None
    for line in Path("/proc/self/smaps").read_text().splitlines():
        if line and not line[0].isupper():
            parts = line.split(None, 5)
            cur = want.get(parts[5].strip()) if len(parts) >= 6 else None
        elif cur and line.startswith("Rss:"):
            totals[cur] += int(line.split()[1])
    return totals


libc = ctypes.CDLL(None, use_errno=True)
libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p]
libc.mincore.restype = ctypes.c_int


def residency(base: int, extents) -> dict:
    """Over `extents` = [(page_start, page_len), …] of the forward slab mapped
    at `base`: pages present in this process's page table (pagemap bit 63)
    and pages resident in the page cache (mincore bit 0)."""
    n_pages = 0
    n_mapped = 0
    n_cached = 0
    with open("/proc/self/pagemap", "rb", buffering=0) as pm:
        for s, ln in extents:
            if ln <= 0:
                continue
            vaddr = base + s * PAGE
            vpn = vaddr // PAGE
            buf = os.pread(pm.fileno(), 8 * ln, 8 * vpn)
            got = len(buf) // 8
            n_pages += got
            for i in range(got):
                if buf[8 * i + 7] & 0x80:
                    n_mapped += 1
            vec = ctypes.create_string_buffer(ln)
            rc = libc.mincore(ctypes.c_void_p(vaddr), ctypes.c_size_t(ln * PAGE), vec)
            if rc == 0:
                n_cached += sum(1 for b in vec.raw[:got] if b & 1)
    return {"pages": n_pages,
            "mapped_pages": n_mapped,
            "mapped_pct": round(100.0 * n_mapped / max(1, n_pages), 4),
            "pagecache_pages": n_cached,
            "pagecache_pct": round(100.0 * n_cached / max(1, n_pages), 4)}


def sha256(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── the pinned set (identical derivation to the backend's prefault_hotset /
#    r1_ram_ladder --release-except-hotset) ───────────────────────────────────

def pinned_extents_for(shard_dir: str, budget_name: str, per_shard_budget: int,
                       coalesce):
    sc = json.loads((Path(shard_dir) / f"hotset_{budget_name}.json").read_text())
    assert sc.get("schema") == "seismic.hotset.v1", sc.get("schema")
    take, acc = [], 0
    for s, ln in sc["extents"]:
        nb = ln * PAGE
        if acc + nb > per_shard_budget and acc > 0:
            break
        take.append((s, ln))
        acc += nb
    raw_pages = sum(ln for _, ln in take)
    # NOTE (measured 2026-09-29, shard 0): the backend's `_coalesce_extents`
    # (2048-extent cap, gap escalating to 4096 pages) inflates hot50's 48,825
    # raw pages to ~440k pages per shard (~1.8 GB/shard, ~14 GB over 8 shards)
    # — this IS what `prefault_hotset` faults in under PREFLOOR_HOTSET=1 even
    # though it logs the raw 1.60 GB. Both sets are measured: `take` is the
    # true sidecar hot set, `merged` is what was prefaulted and is kept.
    merged = coalesce(take)
    return merged, raw_pages, sc, take


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


# ── one arm ────────────────────────────────────────────────────────────────

def run_arm(args) -> dict:
    os.environ.setdefault("SFU_SEISMIC_PREFLOOR_HOTSET", "1")
    if args.so_dir:
        sys.path.insert(0, args.so_dir)
    sys.path.insert(0, str(REPO / "src"))
    import seismic  # noqa: E402  (resolved through sys.path above)
    so_path = Path(seismic.__file__).parent / "seismic.cpython-311-x86_64-linux-gnu.so"
    M = seismic.MmapSeismicIndex
    has_by_slab = hasattr(M, "release_pages_except_by_slab")
    rec = {"arm": args.arm_name or args.arm,
           "so_variant": args.arm,
           "so_path": str(so_path),
           "so_sha256": sha256(so_path),
           "so_has_release_pages_except_by_slab": has_by_slab,
           "env": {k: os.environ.get(k) for k in (
               "SFU_SEISMIC_PREFLOOR_HOTSET", "SFU_SEISMIC_PIN_BUDGET_GB",
               "SFU_SEISMIC_MLOCK_FLOOR", "SFU_SEISMIC_PREFLOOR_AT_LOAD")},
           "sidecar_budget": args.sidecar_budget,
           "pin_mode": "raw_sidecar_extents" if args.pin_raw else "backend_coalesced_extents",
           "warm_passes": args.warm_passes,
           "queries": args.queries, "top_k": args.top_k,
           "uncapped": True,
           "cgroup_memory_max": _read("/sys/fs/cgroup/memory.max"),
           "lru_gen_enabled": _read("/sys/kernel/mm/lru_gen/enabled"),
           "kernel": os.uname().release}
    log.info("arm=%s so=%s sha=%s by_slab=%s", args.arm, so_path,
             rec["so_sha256"][:12], has_by_slab)

    from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
        HybridSeismicBackend, _coalesce_extents)

    terms = json.loads(ENCODED.read_text())["terms"][:args.queries]
    t0 = time.perf_counter()
    mf0 = read_majflt()
    sb = HybridSeismicBackend.from_manifest(str(MANIFEST), load_mode="mmap")
    rec["load_s"] = round(time.perf_counter() - t0, 2)
    rec["load_majflt"] = read_majflt() - mf0
    # /proc/self/maps and smaps print ABSOLUTE paths; the manifest's mmap_dir
    # fields are repo-relative, so resolve before matching.
    shard_dirs = [str(Path(d).resolve()) for d in sb._shard_mmap_dirs]
    rec["n_shards"] = len(shard_dirs)
    maps = slab_mappings(shard_dirs)
    missing = [k for d in shard_dirs for s in SLABS
               if (k := (Path(d).name, s)) not in maps]
    rec["slab_mappings_missing"] = [f"{a}/{b}" for a, b in missing]
    rec["slab_file_bytes"] = {s: sum(os.path.getsize(Path(d) / s) for d in shard_dirs)
                              for s in SLABS}

    per_shard_budget = int(1.6e9 / max(1, len(shard_dirs)))
    plan = []
    kept_pages_raw = 0
    kept_pages_coalesced = 0
    for idx, d in zip(sb.shards, shard_dirs):
        ext, raw_pages, _, raw = pinned_extents_for(d, args.sidecar_budget,
                                                    per_shard_budget, _coalesce_extents)
        kept_pages_raw += raw_pages
        kept_pages_coalesced += sum(ln for _, ln in ext)
        plan.append((idx, d, ext, raw))
    # `keep` = what is passed to release_pages_except: the backend-identical
    # coalesced set (default; what PREFLOOR_HOTSET prefaulted) or, with
    # --pin-raw, the raw sidecar extents (the true hot set — the coalescing
    # gap filler is then released too).
    plan = [(idx, d, ext, raw, (raw if args.pin_raw else ext)) for idx, d, ext, raw in plan]
    rec["kept_extents_total"] = sum(len(k) for *_, k in plan)
    rec["kept_bytes_raw"] = kept_pages_raw * PAGE
    rec["kept_bytes_coalesced"] = kept_pages_coalesced * PAGE
    rec["kept_bytes"] = kept_pages_raw * PAGE if args.pin_raw else kept_pages_coalesced * PAGE

    def snapshot(tag):
        snap = {"vm": read_vm(), "slab_rss_kb": slab_rss_from_smaps(shard_dirs),
                "host_vmstat": read_vmstat(), "host_meminfo": read_meminfo_brief()}
        hot = {"pages": 0, "mapped_pages": 0, "pagecache_pages": 0}
        hot_co = {"pages": 0, "mapped_pages": 0, "pagecache_pages": 0}
        hot_raw = {"pages": 0, "mapped_pages": 0, "pagecache_pages": 0}
        full = {"pages": 0, "mapped_pages": 0, "pagecache_pages": 0}
        for _, d, ext, raw, keep in plan:
            base = maps[(Path(d).name, "forward_data.bin")][0]
            for acc, extents in ((hot, keep), (hot_co, ext), (hot_raw, raw)):
                r = residency(base, extents)
                for k in acc:
                    acc[k] += r[k]
            ft = json.loads((Path(d) / "hotset_full_touched.json").read_text())["extents"]
            r2 = residency(base, [tuple(e) for e in ft])
            for k in full:
                full[k] += r2[k]
        for h in (hot, hot_co, hot_raw, full):
            h["mapped_pct"] = round(100.0 * h["mapped_pages"] / max(1, h["pages"]), 4)
            h["pagecache_pct"] = round(100.0 * h["pagecache_pages"] / max(1, h["pages"]), 4)
        snap["hot_kept_residency"] = hot
        snap["hot_coalesced_residency"] = hot_co
        snap["hot_raw_sidecar_residency"] = hot_raw
        snap["full_touched_residency"] = full
        log.info("[%s] RssFile %.3f GB RssAnon %.3f GB | slab Rss GB %s | "
                 "hot-kept mapped %.2f%% cached %.2f%% | full-touched mapped "
                 "%.2f%% cached %.2f%%", tag,
                 snap["vm"]["rssfile_kb"] / 1e6, snap["vm"]["rssanon_kb"] / 1e6,
                 {k[:12]: round(v / 1e6, 3) for k, v in snap["slab_rss_kb"].items()},
                 hot["mapped_pct"], hot["pagecache_pct"],
                 full["mapped_pct"], full["pagecache_pct"])
        return snap

    def query_pass(tag):
        lat, empty, topk = [], 0, {}
        mf0 = read_majflt()
        vs0 = read_vmstat()
        t_pass = time.perf_counter()
        for qi, q in enumerate(terms):
            t = time.perf_counter()
            res = sb.search_encoded(q, args.top_k)
            lat.append((time.perf_counter() - t) * 1000.0)
            if not res:
                empty += 1
            topk[str(qi)] = [[oaid, round(float(s), 6)] for oaid, s in res[:10]]
        vs1 = read_vmstat()
        out = {"n_queries": len(terms), "empty_results": empty,
               "host_vmstat_delta": {k: vs1[k] - vs0[k] for k in vs1 if k in vs0},
               "host_meminfo_end": read_meminfo_brief(),
               "p50_ms": round(statistics.median(lat), 2),
               "p95_ms": round(pctl(lat, 95), 2), "max_ms": round(max(lat), 2),
               "majflt": read_majflt() - mf0,
               "wall_s": round(time.perf_counter() - t_pass, 2),
               "vm": read_vm()}
        log.info("%s: %d queries, %d empty, p50 %.1f ms p95 %.1f ms majflt %d",
                 tag, len(terms), empty, out["p50_ms"], out["p95_ms"], out["majflt"])
        return out, topk

    # --warm-passes N: run N query passes BEFORE the release so query-touched
    # pages (posting lists, forward records outside the keep set) are
    # resident — the uncapped analogue of "footprint − hot set".
    rec["warm_passes_before_release"] = []
    for wp in range(args.warm_passes):
        out, _ = query_pass(f"warm pass {wp + 1}/{args.warm_passes} (pre-release)")
        rec["warm_passes_before_release"].append(out)

    rec["pre"] = snapshot("pre-release")

    # ── the call under test ────────────────────────────────────────────────
    released_by_slab = {}
    released_total = 0
    status = "ok"
    t0 = time.perf_counter()
    try:
        for idx, d, _, _, keep in plan:
            if has_by_slab:
                rows = idx.release_pages_except_by_slab(keep, False)
                for name, n in rows:
                    released_by_slab[name] = released_by_slab.get(name, 0) + int(n)
                released_total += sum(int(n) for _, n in rows)
            else:
                try:
                    n = idx.release_pages_except(keep, False)
                except TypeError:
                    n = idx.release_pages_except(keep)
                released_by_slab["forward_data"] = (
                    released_by_slab.get("forward_data", 0) + int(n))
                released_total += int(n)
    except Exception as exc:  # recorded, never raised — a FAIL is a deliverable
        status = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - t0
    pre_vm = rec["pre"]["vm"]
    hot_kept_resident_bytes = rec["pre"]["hot_kept_residency"]["mapped_pages"] * PAGE
    scope_bytes = (rec["slab_file_bytes"]["forward_data.bin"] - rec["kept_bytes"]
                   if not has_by_slab else
                   sum(rec["slab_file_bytes"].values()) - rec["kept_bytes"])
    rec["release"] = {
        "requested_bytes_residue": pre_vm["rssfile_kb"] * 1024 - hot_kept_resident_bytes,
        "requested_bytes_residue_def": "RssFile_pre - hot-kept mapped bytes: the load "
                                       "residue the call is meant to remove (uncapped)",
        "prereg_expected_bytes": int(9.3e9),
        "prereg_expected_def": "§5 check 3 (a): footprint 19.4 GB - hot set 10.1 GB, "
                               "a CAPPED-cell quantity; recorded for reference only",
        "advised_scope_bytes": scope_bytes,
        "advised_scope_def": "slab bytes in the hook's scope minus kept extents "
                             "(what MADV_DONTNEED is asked to cover, resident or not)",
        "released_bytes": released_total,
        "released_bytes_def": "the hook's return value = bytes madvise accepted "
                              "(resident or not); NOT bytes that were resident",
        "released_by_slab": released_by_slab,
        "write_status": status,
        "elapsed_s": round(elapsed, 3)}
    log.info("release: status=%s released %.3f GB in %.2fs by_slab=%s", status,
             released_total / 1e9, elapsed,
             {k: round(v / 1e9, 3) for k, v in released_by_slab.items()})

    rec["post"] = snapshot("post-release")

    # ── serve check ────────────────────────────────────────────────────────
    rec["serve_after_release"], topk = query_pass("serve after release")
    empty = rec["serve_after_release"]["empty_results"]
    rec["topk_after_release"] = topk

    # ── checks (a)(b)(c) ───────────────────────────────────────────────────
    post_vm = rec["post"]["vm"]
    drop = (pre_vm["rssfile_kb"] - post_vm["rssfile_kb"]) * 1024
    residue = rec["release"]["requested_bytes_residue"]
    hot_pre = rec["pre"]["hot_kept_residency"]["mapped_pct"]
    hot_post = rec["post"]["hot_kept_residency"]["mapped_pct"]
    tol = args.tolerance
    rec["checks"] = {
        "a_released_vs_residue": {
            "released_bytes": released_total, "residue_bytes": residue,
            "ratio": round(released_total / max(1, residue), 4),
            "pass": abs(released_total - residue) <= tol * residue,
            "note": "released_bytes counts advised (resident or not) bytes; see "
                    "released_bytes_def — the RssFile drop in (b) is the "
                    "physical quantity"},
        "b_rssfile_drop_vs_residue": {
            "rssfile_pre_bytes": pre_vm["rssfile_kb"] * 1024,
            "rssfile_post_bytes": post_vm["rssfile_kb"] * 1024,
            "drop_bytes": drop, "residue_bytes": residue,
            "ratio": round(drop / max(1, residue), 4),
            "pass": abs(drop - residue) <= tol * residue,
            "slab_rss_drop_kb": {s: rec["pre"]["slab_rss_kb"][s] - rec["post"]["slab_rss_kb"][s]
                                 for s in SLABS}},
        "c_hot_kept_stays_mapped": {
            "pre_mapped_pct": hot_pre, "post_mapped_pct": hot_post,
            "ratio": round(hot_post / max(1e-9, hot_pre), 4),
            "pass": hot_post >= 0.9 * hot_pre,
            "pre_pagecache_pct": rec["pre"]["hot_kept_residency"]["pagecache_pct"],
            "post_pagecache_pct": rec["post"]["hot_kept_residency"]["pagecache_pct"]},
        "serves_after_release": {"pass": empty == 0 and status == "ok"},
        "tolerance_frac": tol}
    log.info("checks: a=%s (ratio %.3f) b=%s (drop %.3f GB / residue %.3f GB) "
             "c=%s (%.2f%% -> %.2f%%) serves=%s",
             rec["checks"]["a_released_vs_residue"]["pass"],
             rec["checks"]["a_released_vs_residue"]["ratio"],
             rec["checks"]["b_rssfile_drop_vs_residue"]["pass"], drop / 1e9,
             residue / 1e9, rec["checks"]["c_hot_kept_stays_mapped"]["pass"],
             hot_pre, hot_post, rec["checks"]["serves_after_release"]["pass"])
    return rec


def _read(p):
    try:
        return Path(p).read_text().strip()
    except OSError:
        return None


# ── driver: both arms, each under flock ────────────────────────────────────

def overlap_at_10(a: dict, b: dict) -> float:
    ov = []
    for k in a:
        sa = {x[0] for x in a[k]}
        sb_ = {x[0] for x in b.get(k, [])}
        ov.append(len(sa & sb_) / 10.0)
    return round(sum(ov) / max(1, len(ov)), 4)


def run_driver(args) -> None:
    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(args.tmp_dir or out_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    arms = {}
    if args.merge and Path(args.out).is_file():
        arms = json.loads(Path(args.out).read_text()).get("arms", {})
    for arm in args.arms.split(","):
        # arm name grammar: <fixed|control>[_raw][_warmN]
        parts = arm.split("_")
        base = parts[0]
        assert base in ("fixed", "control"), arm
        pin_raw = "raw" in parts[1:]
        warm = next((int(x[4:]) for x in parts[1:] if x.startswith("warm")), 0)
        arm_out = tmp / f"wslrh_f5_gap1_arm_{arm}.json"
        cmd = ["flock", LOCK, sys.executable, __file__, "--arm", base,
               "--arm-name", arm, "--warm-passes", str(warm),
               "--out", str(arm_out), "--queries", str(args.queries),
               "--top-k", str(args.top_k), "--sidecar-budget", args.sidecar_budget,
               "--tolerance", str(args.tolerance)]
        if pin_raw:
            cmd += ["--pin-raw"]
        if base == "fixed":
            cmd += ["--so-dir", args.so_dir]
        env = dict(os.environ, SFU_SEISMIC_PREFLOOR_HOTSET="1")
        log.info("=== arm %s: %s", arm, " ".join(cmd))
        t0 = time.perf_counter()
        rc = subprocess.run(cmd, env=env).returncode
        log.info("=== arm %s exit %d in %.0fs", arm, rc, time.perf_counter() - t0)
        if arm_out.is_file():
            arms[arm] = json.loads(arm_out.read_text())
        else:
            arms[arm] = {"arm": arm, "error": f"subprocess exit {rc}, no output"}
        arms[arm]["subprocess_rc"] = rc
    combined = {
        "record": "WSL2 re-host §6 gap 1 — F5 release_pages_except mechanism check, "
                  "UNCAPPED (not the §5 calibration record)",
        "date": "2026-09-29",
        "prereg": "spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md §5 item 3 / §6 gap 1",
        "fork_commit": _git_head(REPO / "spike/seismic_upstream"),
        "manifest": str(MANIFEST.relative_to(REPO)),
        "encoded_queries": str(ENCODED.relative_to(REPO)),
        "served_so_untouched": True,
        "host": {"kernel": os.uname().release,
                 "meminfo": _meminfo(),
                 "cgroup_memory_max": _read("/sys/fs/cgroup/memory.max"),
                 "lru_gen_enabled": _read("/sys/kernel/mm/lru_gen/enabled")},
        "arms": arms}
    if "fixed" in arms and "control" in arms and \
            "topk_after_release" in arms["fixed"] and "topk_after_release" in arms["control"]:
        combined["fixed_vs_control_overlap_at_10"] = overlap_at_10(
            arms["fixed"]["topk_after_release"], arms["control"]["topk_after_release"])
    elif args.merge:
        prev = json.loads(Path(args.out).read_text()) if Path(args.out).is_file() else {}
        if "fixed_vs_control_overlap_at_10" in prev:
            combined["fixed_vs_control_overlap_at_10"] = prev["fixed_vs_control_overlap_at_10"]
    for a in arms.values():
        a.pop("topk_after_release", None)
    Path(args.out).write_text(json.dumps(combined, indent=1))
    log.info("wrote %s", args.out)
    for arm, a in arms.items():
        c = a.get("checks")
        if c:
            log.info("%s: a=%s b=%s c=%s serves=%s", arm,
                     c["a_released_vs_residue"]["pass"],
                     c["b_rssfile_drop_vs_residue"]["pass"],
                     c["c_hot_kept_stays_mapped"]["pass"],
                     c["serves_after_release"]["pass"])
    if "fixed_vs_control_overlap_at_10" in combined:
        log.info("fixed vs control overlap@10 = %.4f",
                 combined["fixed_vs_control_overlap_at_10"])


def _git_head(d):
    try:
        return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        return None


def _meminfo():
    out = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        if k in ("MemTotal", "MemAvailable", "Cached", "SwapTotal", "SwapFree"):
            out[k + "_kb"] = int(v.split()[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("fixed", "control"), default=None,
                    help="run ONE arm in this process (used by the driver)")
    ap.add_argument("--so-dir", default=None,
                    help="dir containing a side-loadable `seismic/` package "
                         "(the rebuilt .so); omitted => the served .so")
    ap.add_argument("--arms", default="fixed,control",
                    help="driver: comma list of <fixed|control>[_raw][_warmN]")
    ap.add_argument("--merge", action="store_true",
                    help="driver: keep arms already in --out, add/replace these")
    ap.add_argument("--arm-name", default=None, help="(driver-internal) arm label")
    ap.add_argument("--pin-raw", action="store_true",
                    help="release with the RAW sidecar extents (true hot set) "
                         "instead of the backend's coalesced set")
    ap.add_argument("--warm-passes", type=int, default=0,
                    help="query passes to run BEFORE the release")
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--sidecar-budget", default="hot50_1.6gb")
    ap.add_argument("--tolerance", type=float, default=0.20,
                    help="relative tolerance for checks (a)/(b)")
    ap.add_argument("--tmp-dir", default=None,
                    help="driver: where per-arm JSONs go (default: beside --out)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.arm:
        rec = run_arm(args)
        Path(args.out).write_text(json.dumps(rec, indent=1))
        log.info("wrote %s", args.out)
        return
    if not args.so_dir and any(a.startswith("fixed") for a in args.arms.split(",")):
        ap.error("--so-dir is required for a fixed arm")
    run_driver(args)


if __name__ == "__main__":
    main()
