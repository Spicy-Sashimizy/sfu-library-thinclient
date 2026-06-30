#!/usr/bin/env python3
"""SEISMIC testbed — Plan 01 Gate: is federated query result-safe?

`docs/seismic_150m_testbed/build_plans/01_SHARDED_BUILD_FEDERATED_QUERY.md` Risks:
"Per-shard vs global pruning (the one real quality variable). SEISMIC computes its
posting-pruning and k-means *within* each shard, so K-shard top-k is **not
bit-identical** to a single index. The perturbation MUST be measured before trusting
a G6 result on the sharded index."

**Pre-registered verdict (from the plan):**
  - overlap@10 (2-shard federated) vs (1-shard single) ≥ 0.98 → federation is
    result-safe → proceed to a 150M sharded build.
  - < 0.95 → fan-out itself perturbs results → shard count must drop (STOP, report).

This is the ONE quality variable Plan 01 introduces. It does not need Qdrant or a
judge — it compares two SEISMIC configs (2-shard federated vs 1-shard single) over
the SAME docs, so any top-k delta is purely per-shard pruning/k-means, which is the
only thing federation perturbs.

**Design (economical — reuses the existing persona index).** The single 929k
med_bio index already exists (`/tmp/seismic_testbed/index/med_bio_929k.index.seismic`,
the G1 baseline). We hash-partition its *jsonl* into 2 shards (shard0 ∪ shard1 == the
EXACT 929k docs — no spool re-read, no new corpus), build the 2 shards, and compare
the federated top-k to the single index's top-k over the SAME query set. The single
index is the control; the federation is the treatment. Identical encoder, identical
qvecs, identical docs → overlap = pure federation perturbation.

Reuses `eval_seismic_parity.overlap()` and `load_queries` for apples-to-apples
semantics with the G2 harness.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/g_federation_overlap.py \
        --single-index /tmp/seismic_testbed/index/med_bio_929k \
        --source-jsonl /tmp/seismic_testbed/jsonl/med_bio_929000.jsonl \
        --shard-dir /tmp/seismic_testbed/index/shards \
        --queries 60 \
        --result-file data/eval_results/seismic_federation_overlap_929k.json
"""
import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_seismic_parity import overlap, load_queries  # noqa: E402
from seismic_federated import ShardedSeismicBackend  # noqa: E402
import seismic_backend  # noqa: E402  (canonical SeismicBackend via the shim)

log = logging.getLogger("federation_overlap")

TOP_K = 50          # fetch @50 (matches eval_seismic_parity TOP_K)
NDCG_K = 10        # overlap is computed @10
K_SHARDS = 2
HASH_SEED = "sfu-seismic-plan01"  # MUST match shard_spool.py for consistency
FED_BAR = 0.98      # pre-registered result-safe bar (≥0.98)
FED_STOP = 0.95     # pre-registered STOP bar (<0.95 → perturbing)


def shard_id(oaid: str) -> int:
    """Identical hash to shard_spool.shard_id — keeps this partition consistent
    with the spool-level splitter (a doc here = the doc there)."""
    h = hashlib.blake2b((HASH_SEED + str(oaid)).encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big") % K_SHARDS


def partition_jsonl(src_jsonl: Path, shard_dir: Path) -> list[Path]:
    """Hash-route an existing SEISMIC jsonl into K shards. shard0 ∪ ... ∪ shard{K-1}
    == the source doc set EXACTLY (every doc goes to exactly one shard)."""
    shard_dir.mkdir(parents=True, exist_ok=True)
    out = [shard_dir / f"shard{i}of{K_SHARDS}.jsonl" for i in range(K_SHARDS)]
    fouts = [open(p, "w") for p in out]
    n_per = [0] * K_SHARDS
    t0 = time.perf_counter()
    try:
        with open(src_jsonl) as f:
            for line in f:
                rec = json.loads(line)
                doc_id = rec.get("id")
                if doc_id is None:
                    continue
                sid = shard_id(doc_id)
                # pass the record through UNCHANGED (id + vector) — NO re-encode.
                fouts[sid].write(line if line.endswith("\n") else line + "\n")
                n_per[sid] += 1
    finally:
        for f in fouts:
            f.close()
    log.info("partitioned %s -> %d shards in %.1fs (per-shard: %s, balance max/min=%.3f)",
             src_jsonl.name, K_SHARDS, time.perf_counter() - t0, n_per,
             max(n_per) / min(n_per) if min(n_per) else 0)
    return out


def build_shard(jsonl: Path, index_stem: Path, build_args: dict) -> tuple[Path, dict]:
    """Build one SEISMIC shard with the parity DEFAULTS (same params as the single
    index, so overlap isolates per-shard-pruning, not a param diff). Reuses
    build_persona_seismic.build via its CLI."""
    import subprocess
    cmd = [sys.executable, str(REPO / "scripts/seismic_testbed/build_persona_seismic.py"),
           "--jsonl", str(jsonl), "--index-path", str(index_stem)]
    for k, v in build_args.items():
        if v is not None:
            cmd += [f"--{k.replace('_', '-')}", str(v)]
    log.info("  building %s -> %s", jsonl.name, index_stem)
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if r.returncode != 0:
        log.error("build failed (%.1fs): %s\n%s", dt, r.stderr[-2000:], r.stdout[-1000:])
        raise RuntimeError(f"shard build failed for {jsonl}")
    log.info("  built in %.1fs", dt)
    # parse the printed json summary line
    summary = {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and "index_path" in line:
            try:
                summary = json.loads(line)
            except Exception:
                pass
    return Path(str(index_stem) + ".index.seismic"), summary


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--single-index", required=True,
                    help="the control: a single SEISMIC index stem (.index.seismic)")
    ap.add_argument("--source-jsonl", required=True,
                    help="the jsonl the single index was built from (will be partitioned)")
    ap.add_argument("--shard-dir", required=True, help="where to write shard jsonls + indexes")
    ap.add_argument("--queries", type=int, default=60,
                    help="n diverse queries to probe (overlap, not NDCG — judge coverage irrelevant)")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--k-prime", type=int, default=None, help="per-shard over-fetch (default 4×k)")
    ap.add_argument("--query-cut", type=int, default=None)
    ap.add_argument("--heap-factor", type=float, default=0.8)
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--skip-build", action="store_true",
                    help="reuse shard indexes already in --shard-dir (don't rebuild)")
    ap.add_argument("--load-mode", choices=("stock", "mmap"), default="stock",
                    help="how the FEDERATED treatment loads its shards: 'stock' (Path-A, "
                         "default, the recorded 0.9967 result) or 'mmap' (Path-C, needs "
                         "converted X.mmap/ dirs — re-checks federation is result-safe "
                         "under the C2.5 mmap reader). The single control stays stock.")
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    single_fp = (args.single_index if args.single_index.endswith(".index.seismic")
                 else f"{args.single_index}.index.seismic")
    assert Path(single_fp).exists(), f"single index missing: {single_fp}"

    # ── 1. partition the source jsonl into K shards (shard0 ∪ shard1 == single docs) ──
    shard_jsonls = partition_jsonl(Path(args.source_jsonl), Path(args.shard_dir))

    # ── 2. build each shard with the parity DEFAULTS (one at a time — never stack RSS) ──
    build_args = dict(n_postings=3500, centroid_fraction=0.1, summary_energy=0.4,
                      max_fraction=1.5, doc_cut=15)
    shard_stems = [Path(args.shard_dir) / f"med_bio_shard{i}_929k" for i in range(K_SHARDS)]
    shard_indexes = []
    for i, (jl, stem) in enumerate(zip(shard_jsonls, shard_stems)):
        fp = Path(str(stem) + ".index.seismic")
        if args.skip_build and fp.exists():
            log.info("  (skip-build) reuse %s", fp)
            shard_indexes.append(fp)
            continue
        built, _ = build_shard(jl, stem, build_args)
        shard_indexes.append(built)

    # ── 3. load both backends: the single control + the federated treatment ──
    log.info("loading single control index: %s", single_fp)
    single = seismic_backend.SeismicBackend(args.single_index, args.model_path)
    log.info("loading federated treatment (%d shards, load_mode=%s)", len(shard_indexes), args.load_mode)
    fed = ShardedSeismicBackend([str(p) for p in shard_indexes],
                                splade_model_path=args.model_path,
                                load_mode=args.load_mode)

    queries = load_queries(args.queries)
    log.info("%d queries; overlap@10 target ≥%.2f (STOP if <%.2f)", len(queries), FED_BAR, FED_STOP)

    # Warmup both (load models/page cache).
    if queries:
        _ = single.search(queries[0]["paraphrase"], args.top_k,
                          query_cut=args.query_cut, heap_factor=args.heap_factor)
        _ = fed.search(queries[0]["paraphrase"], args.top_k,
                       query_cut=args.query_cut, heap_factor=args.heap_factor, k_prime=args.k_prime)

    rows = []
    ovs = []
    for i, rec in enumerate(queries):
        q = rec["paraphrase"]
        s_res = single.search(q, args.top_k, query_cut=args.query_cut, heap_factor=args.heap_factor)
        f_res = fed.search(q, args.top_k, query_cut=args.query_cut,
                           heap_factor=args.heap_factor, k_prime=args.k_prime)
        s_ids = [d for d, _ in s_res]
        f_ids = [d for d, _ in f_res]
        # overlap is symmetric in set-membership; pass single as 'a', federated as 'b'.
        ov = overlap(f_ids, s_ids, NDCG_K)
        ovs.append(ov)
        # how many docs each returned (a 0-hit query is uninformative — track it)
        rows.append({"query": q, "judge_key": rec.get("judge_key", q),
                     "single_top10": s_ids[:NDCG_K], "federated_top10": f_ids[:NDCG_K],
                     "overlap@10": round(ov, 4),
                     "single_n": len(s_ids), "federated_n": len(f_ids)})
        if (i + 1) % 10 == 0 or i == len(queries) - 1:
            nonempty = [r for r in rows if r["single_n"] and r["federated_n"]]
            mean_ov = (sum(r["overlap@10"] for r in nonempty) / len(nonempty)) if nonempty else 0
            log.info("[%d/%d] mean overlap@10 (nonempty)=%.3f, nonempty=%d/%d",
                     i + 1, len(queries), mean_ov, len(nonempty), len(rows))

    nonempty = [r for r in rows if r["single_n"] and r["federated_n"]]
    avg = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    mean_ov_all = avg([r["overlap@10"] for r in rows]) or 0
    mean_ov_nonempty = avg([r["overlap@10"] for r in nonempty]) or 0
    verdict = ("FEDERATION_RESULT_SAFE" if mean_ov_nonempty >= FED_BAR
              else ("FEDERATION_PERTURBING" if mean_ov_nonempty < FED_STOP
                    else "FEDERATION_BORDERLINE"))
    summary = {
        "meta": {"engine": "seismic-pyseismic-lsr (Plan 01 federation gate)",
                 "comparison": "2-shard federated vs 1-shard single over the SAME "
                               "929k med_bio docs (delta = per-shard pruning/k-means only)",
                 "federated_load_mode": args.load_mode,
                 "built_utc": "2026-06-28",
                 "params": {"k_shards": K_SHARDS, "hash_seed": HASH_SEED,
                            "top_k": args.top_k, "k_prime": args.k_prime or args.top_k * 4,
                            "heap_factor": args.heap_factor, "query_cut": args.query_cut,
                            "build_params": build_args},
                 "bar_ge": FED_BAR, "bar_stop_lt": FED_STOP,
                 "purpose": "Plan 01: is fan-out result-safe before a 150M sharded build?"},
        "overlap@10": {"mean_all_queries": mean_ov_all, "n_all": len(rows),
                       "mean_nonempty": mean_ov_nonempty, "n_nonempty": len(nonempty),
                       "bar_ge": FED_BAR, "bar_stop_lt": FED_STOP},
        "verdict": verdict,
        "per_query": rows,
        "shards": [{"jsonl": str(p), "index": str(ip)}
                   for p, ip in zip(shard_jsonls, shard_indexes)],
        "single_index": single_fp,
    }
    log.info("overlap@10: mean_all=%.3f (n=%d), mean_nonempty=%.3f (n=%d) | verdict=%s",
             mean_ov_all, len(rows), mean_ov_nonempty, len(nonempty), verdict)

    rpath = (Path(args.result_file) if args.result_file
             else REPO / f"data/eval_results/seismic_federation_overlap_{int(time.time())}.json")
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"verdict": verdict,
                      "overlap@10_mean_nonempty": mean_ov_nonempty, "n_nonempty": len(nonempty),
                      "bar": f"≥{FED_BAR} / <{FED_STOP}", "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
