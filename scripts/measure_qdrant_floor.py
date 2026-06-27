#!/usr/bin/env python3
"""
Qdrant config-tuning — A1 measure-first: the anon floor before vs after a
force-optimize to green.

Research context (docs/qdrant_config_tuning/MEASURE_FIRST.md):
  - Qdrant's 6.55 GB anon floor at 150M is the per-point id tracker, structural.
  - PR #6023 ships a ~2x SMALLER compressed id tracker, but ONLY on immutable
    (fully-optimized) segments. Appendable segments hold the uncompressed map
    in RAM.
  - splade_150m built via parallel upsert; live state is status=grey, opt=ok ->
    likely appendable-segment overhead still resident. Force the compaction to
    green and re-measure RssAnon to see how much of the floor is reclaimable.

This is non-destructive: it does NOT delete or re-ingest. It (1) snapshots the
qdrant process's RssAnon/RssFile, (2) nudges the optimizer to flush appendable
segments to immutable (indexing_threshold=0 + max_optimization_threads), (3)
polls to status=green && optimizer_status=ok, (4) re-snapshots, (5) writes a
verdict JSON. Mirrors the structure of spike/mmap_bmp/measure_p3a_inverted_floor.py.

Run from repo root (project venv):

    .venv/bin/python3 scripts/measure_qdrant_floor.py \
        --collection splade_150m \
        --qdrant-url http://localhost:6333 \
        --result-file data/eval_results/qdrant_floor_optimize.json
"""
import argparse, json, os, sys, time, subprocess

from qdrant_client import QdrantClient, models  # module-level so _restore_optimizer_config can see `models`

# --- optional proc info -------------------------------------------------------
def _find_qdrant_pid():
    """Best-effort: find the qdrant server PID. None if not found."""
    try:
        out = subprocess.check_output(["pgrep", "-f", "qdrant"], text=True).split()
        return int(out[0]) if out else None
    except Exception:
        return None


def _status_kv(pid):
    """Return RssAnon/RssFile/VmRSS in GB from /proc/<pid>/status, or None."""
    if not pid:
        return None
    path = f"/proc/{pid}/status"
    if not os.path.exists(path):
        return None
    kv = {}
    try:
        for line in open(path):
            if line.startswith(("VmRSS:", "RssAnon:", "RssFile:")):
                # VmRSS/RssAnon/RssFile are in kB
                kv[line.split(":")[0]] = int(line.split()[1]) / 1024 / 1024  # -> GB
    except Exception:
        return None
    return kv or None


# --- qdrant /metrics memory gauges (the sharper reclaim lens) -----------------
#
# Why these matter: process /proc RSS lingers because the OS does not always
# immediately reclaim freed anon pages. But Qdrant exposes jemalloc-backed
# gauges on /metrics that reflect what Qdrant's OWN allocator considers
# resident/active/retained — a compaction that releases id-tracker anon drops
# these gauges immediately if jemalloc returns pages to the OS, REGARDLESS of
# which collection allocated them. So on a shared process (par30+150m in one
# pid), memory_resident_bytes is a sharper, Qdrant-internal reclaim signal than
# OS RssAnon. Captured in both the before and after snapshots below.

_JEMALLOC_METRICS = ("memory_active_bytes", "memory_allocated_bytes",
                     "memory_metadata_bytes", "memory_resident_bytes",
                     "memory_retained_bytes")


def _qdrant_mem_gauges(url):
    """Return {gauge_name: GB} from Qdrant /metrics, or None on failure.

    gauges are bytes -> GB. Returns None if /metrics is unreachable or parse fails,
    so callers degrade gracefully (process RSS only).
    """
    try:
        import urllib.request
        with urllib.request.urlopen(url.rstrip("/") + "/metrics", timeout=15) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    kv = {}
    for line in text.splitlines():
        # metric lines look like "memory_resident_bytes 22201180160"
        # (no labels on these gauges); skip #HELP/#TYPE comments
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        name, val = parts[0], parts[1]
        if name in _JEMALLOC_METRICS:
            try:
                kv[name] = float(val) / 1e9  # bytes -> GB
            except ValueError:
                continue
    return kv or None


def _snapshot_mem(pid, qdrant_url):
    """Combined memory snapshot: OS /proc RSS + Qdrant /metrics jemalloc gauges.

    Both as GB (None-best-effort per field). Used for before/after so the verdict
    can cite BOTH the OS view (lingers) and the allocator view (sharp reclaim).
    """
    return {
        "proc_status": _status_kv(pid),          # OS view: VmRSS/RssAnon/RssFile
        "qdrant_gauges": _qdrant_mem_gauges(qdrant_url),  # jemalloc view: resident/active/retained
    }


# --- qdrant client ------------------------------------------------------------
def _get_state(client, name):
    """Return (points, status, optimizer_status, segments_count) — best-effort."""
    info = client.get_collection(name)
    return {
        "points": int(info.points_count) if info.points_count else None,
        "status": str(info.status),                       # e.g. 'green'/'grey'
        "optimizer_status": str(info.optimizer_status),   # e.g. 'ok'
        "segments_count": getattr(info, "segments_count", None),
    }


def _capture_optimizer_config(client, name):
    """Read the LIVE optimizer_config so we can restore it exactly after the nudge.

    Returns a dict of the fields we touch (indexing_threshold, max_optimization_threads).
    Note: the read path is `info.config.optimizer_config` (singular 'optimizer'),
    while the write path uses OptimizersConfigDiff. We capture the *original* values,
    not a hardcoded default — different collections have different thresholds
    (splade_150m = 20000, splade_par30 = 10000), so presuming 20000 would mutate
    par30. Restoring the originals is what makes the run reversible/honest.
    """
    info = client.get_collection(name)
    oc = info.config.optimizer_config
    return {
        "indexing_threshold": getattr(oc, "indexing_threshold", None),
        "max_optimization_threads": getattr(oc, "max_optimization_threads", None),
        "default_segment_number": getattr(oc, "default_segment_number", None),
    }


def _restore_optimizer_config(client, name, original):
    """Restore the optimizer config that _capture_optimizer_config returned.

    Only restores fields that were present and not None. Best-effort: if the
    restore call throws, we surface it loudly rather than silently leaving the
    collection mutated (the 'churning overnight' risk from the first A1 run).
    """
    diff = models.OptimizersConfigDiff(
        indexing_threshold=original.get("indexing_threshold"),
        max_optimization_threads=original.get("max_optimization_threads"),
    )
    client.update_collection(collection_name=name, optimizers_config=diff)


def _wait_green(client, name, timeout, poll=30):
    """Poll until status==green AND optimizer_status==ok, or timeout. Returns
    (final_state, waited_s, reached_green)."""
    t0 = time.perf_counter()
    last = None
    while True:
        last = _get_state(client, name)
        elapsed = time.perf_counter() - t0
        green = ("green" in last["status"]) and ("ok" in last["optimizer_status"])
        print(f"  [{elapsed:5.0f}s] status={last['status']} opt={last['optimizer_status']} "
              f"pts={last['points']}", flush=True)
        if green:
            return last, elapsed, True
        if elapsed >= timeout:
            return last, elapsed, False
        time.sleep(poll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default="splade_150m")
    ap.add_argument("--qdrant-url", default="http://localhost:6333")
    ap.add_argument("--result-file", default="data/eval_results/qdrant_floor_optimize.json")
    ap.add_argument("--timeout", type=int, default=1800, help="max seconds to wait for green")
    ap.add_argument("--poll", type=int, default=30)
    ap.add_argument("--opt-threads", type=int, default=8, help="max_optimization_threads for the nudge")
    ap.add_argument("--force", action="store_true", help="actually run the optimize nudge (default: dry-run snapshot only)")
    args = ap.parse_args()

    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=args.qdrant_url, timeout=120)
    pid = _find_qdrant_pid()
    print(f"qdrant pid={pid}  collection={args.collection}  force={args.force}", flush=True)

    # 1. before snapshot: BOTH OS /proc RSS and Qdrant /metrics jemalloc gauges.
    #    The gauges are the sharper reclaim lens on a shared process (see
    #    _snapshot_mem docstring); OS RSS lingers, jemalloc drops immediately.
    before_state = _get_state(client, args.collection)
    before_mem = _snapshot_mem(pid, args.qdrant_url)
    print(f"BEFORE: status={before_state['status']} opt={before_state['optimizer_status']} "
          f"pts={before_state['points']} | mem={before_mem}", flush=True)

    res = {
        "meta": {"engine": "qdrant-on_disk-sparse", "collection": args.collection,
                 "purpose": "A1: measure anon floor before vs after force-optimize to green (PR #6023 compressed id tracker is immutable-only)",
                 "built_utc": "2026-06-26", "qdrant_pid": pid, "force_run": args.force,
                 "mem_lenses": "proc_status=OS RssAnon/RssFile/VmRSS (lingers); qdrant_gauges=jemalloc resident/active/retained (sharp reclaim, collection-agnostic)"},
        "before": {"state": before_state, "mem_gb": before_mem},
    }

    if not args.force:
        res["note"] = ("dry-run snapshot (--force not set); to measure the reclaim, "
                       "rerun with --force to nudge indexing_threshold=0 + max_opt_threads "
                       "and poll to status=green.")
        print("\n[dry-run] rerun with --force to actually trigger the optimize.", flush=True)
        _write(args.result_file, res)
        return

    # 2. capture the ORIGINAL optimizer config so we can restore it exactly.
    #    Different collections have different thresholds (150m=20000, par30=10000),
    #    so we must not hardcode the restore value — that would mutate the collection.
    original_cfg = _capture_optimizer_config(client, args.collection)
    res["nudge"] = {
        "original_optimizer_config": original_cfg,
        "indexing_threshold_set_to": 0,
        "max_optimization_threads": args.opt_threads,
    }
    print(f"captured original optimizer_config: {original_cfg}", flush=True)

    # 3. nudge the optimizer: flush appendable segments to immutable.
    #    indexing_threshold=0 -> index everything immediately (no appendable hold),
    #    max_optimization_threads -> parallelize the compaction.
    #    Wrapped in try/finally so the config is ALWAYS restored, even if poll/snapshot
    #    throws — leaving indexing_threshold=0 behind is the 'churning overnight' risk.
    print(f"nudging optimizer: indexing_threshold=0, max_optimization_threads={args.opt_threads}", flush=True)
    restored_ok = False
    restore_error = None
    # pre-declare so the verdict path below is safe even if the try block throws
    final_state = before_state          # fall back: pretend no change
    after_mem = before_mem
    waited = 0.0
    reached = False
    try:
        client.update_collection(
            collection_name=args.collection,
            optimizers_config=models.OptimizersConfigDiff(
                indexing_threshold=0,
                max_optimization_threads=args.opt_threads,
            ),
        )

        # 4. poll to green
        final_state, waited, reached = _wait_green(client, args.collection, args.timeout, args.poll)

        # 6. after snapshot (give the OS a beat to release reclaimed anon)
        time.sleep(10)
        after_mem = _snapshot_mem(pid, args.qdrant_url)
        print(f"AFTER : status={final_state['status']} opt={final_state['optimizer_status']} "
              f"| mem={after_mem} (reached_green={reached}, waited={waited:.0f}s)", flush=True)
    finally:
        # restore the original optimizer config regardless of how the above exited.
        try:
            _restore_optimizer_config(client, args.collection, original_cfg)
            restored_ok = True
            print(f"RESTORED optimizer config to original: {original_cfg}", flush=True)
        except Exception as e:
            restore_error = repr(e)
            print(f"!! FAILED to restore optimizer config: {e}", flush=True)
    res["nudge"]["restored_ok"] = restored_ok
    res["nudge"]["restore_error"] = restore_error
    res["nudge"]["restored_to"] = original_cfg if restored_ok else None

    # 7. verdict — TWO reclaim lenses
    #    OS view (proc_status.RssAnon): lingers because the OS may not reclaim
    #      freed anon immediately; the historical signal the prior run relied on.
    #    jemalloc view (qdrant_gauges.memory_resident_bytes / memory_active_bytes):
    #      Qdrant's OWN allocator accounting — drops at once if compaction returns
    #      pages to the OS, regardless of which collection held them. This is the
    #      sharper lens on a shared process (par30+150m in one pid), where OS RSS
    #      is dominated by the OTHER collection.
    def _rss_anon(snap):
        ps = (snap or {}).get("proc_status") or {}
        return ps.get("RssAnon")

    def _gauge(snap, name):
        g = (snap or {}).get("qdrant_gauges") or {}
        return g.get(name)

    anon_before = _rss_anon(before_mem)
    anon_after = _rss_anon(after_mem)
    delta = (anon_after - anon_before) if (anon_before is not None and anon_after is not None) else None
    # jemalloc resident/active deltas — the sharper signal
    mr_before, mr_after = _gauge(before_mem, "memory_resident_bytes"), _gauge(after_mem, "memory_resident_bytes")
    ma_before, ma_after = _gauge(before_mem, "memory_active_bytes"), _gauge(after_mem, "memory_active_bytes")
    mr_delta = (mr_after - mr_before) if (mr_before is not None and mr_after is not None) else None
    ma_delta = (ma_after - ma_before) if (ma_before is not None and ma_after is not None) else None
    pts = before_state.get("points")
    b_per_pt_before = (anon_before * 1e9 / pts) if (anon_before is not None and pts) else None
    b_per_pt_after = (anon_after * 1e9 / pts) if (anon_after is not None and pts) else None

    verdict = "INCONCLUSIVE"
    if delta is not None:
        if delta <= -0.5:        # reclaim of >= 0.5 GB (OS view)
            verdict = ("RECLAIMED (OS RssAnon) — force-optimize to green dropped RssAnon by "
                       f"{abs(delta):.2f} GB ({anon_before:.2f}->{anon_after:.2f}); "
                       "part of the floor was appendable-segment overhead the PR #6023 "
                       "compressed id tracker reclaims on immutable segments.")
        elif abs(delta) < 0.5:
            verdict = ("STRUCTURAL (OS RssAnon) — anon unchanged within noise "
                       f"({anon_before:.2f}->{anon_after:.2f}, Δ={delta:+.2f} GB); the floor "
                       "is structural at green too. Only fewer points / sharding / SPLADE "
                       "pruning scale it down (see CONFIG_LEVERS.md §4).")
        else:
            verdict = (f"ANON ROSE ({anon_before:.2f}->{anon_after:.2f}, Δ={delta:+.2f} GB) "
                       "— unexpected; investigate before claiming (e.g. concurrent load).")

    res["after"] = {"state": final_state, "mem_gb": after_mem}
    res["optimize"] = {"waited_s": round(waited, 1), "reached_green": reached}
    res["summary"] = {
        "rssanon_before_gb": round(anon_before, 4) if anon_before is not None else None,
        "rssanon_after_gb": round(anon_after, 4) if anon_after is not None else None,
        "rssanon_delta_gb": round(delta, 4) if delta is not None else None,
        "anon_b_per_pt_before": round(b_per_pt_before, 1) if b_per_pt_before else None,
        "anon_b_per_pt_after": round(b_per_pt_after, 1) if b_per_pt_after else None,
        # jemalloc sharper-lens deltas (GB)
        "qdrant_memory_resident_before_gb": round(mr_before, 4) if mr_before is not None else None,
        "qdrant_memory_resident_after_gb": round(mr_after, 4) if mr_after is not None else None,
        "qdrant_memory_resident_delta_gb": round(mr_delta, 4) if mr_delta is not None else None,
        "qdrant_memory_active_delta_gb": round(ma_delta, 4) if ma_delta is not None else None,
    }
    # augment the verdict text with the jemalloc lens when available — it is the
    # primary reclaim signal on a shared process; OS-RssAnon alone is too coarse.
    if mr_delta is not None:
        res["jemalloc_note"] = (
            f"jemalloc memory_resident_bytes Δ = {mr_delta:+.4f} GB ({mr_before:.4f}->{mr_after:.4f}). "
            "This is the sharp, collection-agnostic reclaim signal: a negative delta means "
            "Qdrant's allocator returned pages to the OS after compaction. OS RssAnon can lag "
            "this by seconds-minutes because the kernel reclaims freed anon lazily."
        )
    res["verdict"] = verdict
    res["caveat"] = ("per-point id tracker is required-resident; this measures "
                     "whether appendable->immutable compaction reclaims any of it, "
                     "NOT whether Qdrant can serve below the green-state floor. The "
                     "anon_b_per_pt figure is only valid for an ISOLATED single-collection "
                     "process; on a shared pid it divides the whole-process anon by this "
                     "collection's points and is meaningless as a per-point number.")

    print("\n──────── A1 RESULT ────────")
    print(json.dumps(res["summary"], indent=2))
    print(f"\nVERDICT: {verdict}")

    _write(args.result_file, res)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w"), indent=2)
    print(f"\nwrote {path}", flush=True)


if __name__ == "__main__":
    main()
