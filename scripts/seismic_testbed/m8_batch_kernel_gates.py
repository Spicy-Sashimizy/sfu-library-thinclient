#!/usr/bin/env python3
"""M8 register-blocked batch kernel gates — pre-registered in
`.claude/plans/m8-register-blocked-kernel.md` (bars fixed 2026-07-10, before
the build; pre-gate GO: survivors-per-block median 18 vs bar 4).

Three subcommands, run from repo root with `.venv/bin/python3`:

  baseline  With the PRE-M8 .so still installed: scored passes (k'=100,
            hf=0.8, 64-term queries, n=100 diverse) on shards 1-2, f16 +
            served dv (e5.v2) twins. Saves results AND the encoded query
            term-dicts so later arms replay identical inputs (no encoder
            nondeterminism across the .so swap).

  gatea     With the NEW .so: replays the saved queries, batch ON (env
            unset) and OFF (SFU_SEISMIC_M8_BATCH=0), tie-aware-compares
            every list vs baseline. Bar: hard=0 AND tie_swaps=0, 100/100,
            both shards, both codecs, both arms.

  gatec     Warm traverse p50, ONE process, ON/OFF arms alternating with
            order swapped each rep (x3 reps), dv shards 1-2, pre-encoded
            queries. Bar: PROMOTE ratio<=0.95 both shards; KEEP-unpromoted
            <1.00 consistently; REVERT >=1.00.

The env gate is read by the Rust side once per posting-list scan, so
os.environ mutation between idx.search calls flips it live in-process
(asserted by the fork's m8_env_gate_is_live test).
"""
import argparse
import datetime as _dt
import json
import os
import statistics
import struct
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import load_queries  # noqa: E402
from e5_shard_gates import scored_pass, tie_aware_compare  # noqa: E402

K_PRIME = 100  # M8 plan gate a/c: k'=100 (not the e8 200)
HEAP_FACTOR = 0.8
SPLADE_QUERY_TERMS = 64
REPS = 3
N_QUERIES = 100
PLAN01 = REPO / "data/seismic_150m/index/plan01"
SHARDS = (1, 2)
CODEC_DIRS = {  # codec -> dir template (served dv = the e5-reordered v2 dirs)
    "f16": "global_shard{n}of8.mmap",
    "dv": "global_shard{n}of8.dotvbyte.e5.v2.mmap",
}
ENV = "SFU_SEISMIC_M8_BATCH"


def _load_indexes(codecs):
    import seismic
    string_dtype = seismic.get_seismic_string()
    idxs = {}
    for n in SHARDS:
        for codec in codecs:
            d = PLAN01 / CODEC_DIRS[codec].format(n=n)
            idxs[(n, codec)] = (seismic.MmapSeismicIndex(str(d)), d)
    return string_dtype, idxs


def _set_arm(arm):
    # Post-gate-c default flip (REVERT 2026-08-10): unset = single-pass, so
    # the ON arm must opt in explicitly.
    if arm == "on":
        os.environ[ENV] = "1"
    else:
        os.environ.pop(ENV, None)


def cmd_baseline(args):
    assert ENV not in os.environ, f"unset {ENV} for the baseline capture"
    from lib.opensearch_retriever import encode_splade  # torch first (ENOMEM lesson)
    string_dtype, idxs = _load_indexes(("f16", "dv"))
    queries = load_queries(N_QUERIES, Path(args.query_workload))
    per_q_terms = []
    for q in queries:
        sparse = encode_splade(q, args.model_path)
        per_q_terms.append(dict(sorted(sparse.items(),
                                       key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]))
    print(f"[m8-baseline] {len(queries)} queries encoded", flush=True)
    out = {"date": args.date, "k_prime": K_PRIME, "heap_factor": HEAP_FACTOR,
           "n_queries": len(queries),
           "so_note": "pre-M8 .so (installed 2026-07-14, E8 Stage-2 era)",
           "queries": per_q_terms, "scored": {}}
    for (n, codec), (idx, d) in sorted(idxs.items()):
        t0 = time.time()
        scored = scored_pass(idx, string_dtype, per_q_terms, K_PRIME)
        out["scored"][f"shard{n}.{codec}"] = scored
        print(f"[m8-baseline] shard{n}.{codec} ({d.name}): "
              f"{time.time()-t0:.1f}s", flush=True)
    Path(args.baseline_file).write_text(json.dumps(out))
    print(f"[m8-baseline] wrote {args.baseline_file}", flush=True)


def cmd_gatea(args):
    base = json.loads(Path(args.baseline_file).read_text())
    per_q_terms = [{k: float(v) for k, v in t.items()} for t in base["queries"]]
    string_dtype, idxs = _load_indexes(("f16", "dv"))
    verdict = {"date": args.date, "gate": "a", "baseline_file": args.baseline_file,
               "bar": "hard=0 AND tie_swaps=0, 100/100, both shards/codecs/arms",
               "cells": {}, "pass": True}
    for arm in ("on", "off"):
        _set_arm(arm)
        for (n, codec), (idx, d) in sorted(idxs.items()):
            key = f"shard{n}.{codec}"
            scored = scored_pass(idx, string_dtype, per_q_terms, K_PRIME)
            hards = swapss = exact = 0
            for b, s in zip(base["scored"][key], scored):
                b = [(dd, ss) for dd, ss in b]
                h, sw = tie_aware_compare(b, s)
                hards += h
                swapss += sw
                exact += (h == 0 and sw == 0)
            cell = {"hard": hards, "tie_swaps": swapss,
                    "exact_lists": f"{exact}/{len(scored)}"}
            verdict["cells"][f"{key}.batch_{arm}"] = cell
            ok = hards == 0 and swapss == 0
            verdict["pass"] &= ok
            print(f"[m8-gatea] {key} batch={arm}: hard={hards} "
                  f"swaps={swapss} exact={exact}/{len(scored)} "
                  f"{'PASS' if ok else 'FAIL'}", flush=True)
    Path(args.result_file).write_text(json.dumps(verdict, indent=1))
    print(f"[m8-gatea] overall {'PASS' if verdict['pass'] else 'FAIL'} "
          f"-> {args.result_file}", flush=True)
    sys.exit(0 if verdict["pass"] else 1)


def cmd_gatec(args):
    base = json.loads(Path(args.baseline_file).read_text())
    per_q_terms = [{k: float(v) for k, v in t.items()} for t in base["queries"]]
    string_dtype, idxs = _load_indexes(("dv",))
    verdict = {"date": args.date, "gate": "c", "reps": REPS,
               "bar": "PROMOTE p50 ratio (on/off) <=0.95 both shards; "
                      "KEEP <1.00 consistently; REVERT >=1.00",
               "cells": {}}
    for (n, codec), (idx, d) in sorted(idxs.items()):
        # Warm both arms fully before timing (pages + code paths).
        for arm in ("on", "off"):
            _set_arm(arm)
            scored_pass(idx, string_dtype, per_q_terms, K_PRIME)
        times = {"on": [], "off": []}
        for rep in range(REPS):
            arms = ("on", "off") if rep % 2 == 0 else ("off", "on")
            for arm in arms:
                _set_arm(arm)
                for terms in per_q_terms:
                    qcomp = np.array(list(terms.keys()), dtype=string_dtype)
                    qvals = np.array(list(terms.values()), dtype=np.float32)
                    t0 = time.perf_counter()
                    idx.search(query_id="q", query_components=qcomp,
                               query_values=qvals, k=K_PRIME,
                               query_cut=len(terms), heap_factor=HEAP_FACTOR)
                    times[arm].append(time.perf_counter() - t0)
        p50 = {a: statistics.median(t) * 1000 for a, t in times.items()}
        ratio = p50["on"] / p50["off"]
        verdict["cells"][f"shard{n}"] = {
            "p50_on_ms": round(p50["on"], 3), "p50_off_ms": round(p50["off"], 3),
            "ratio": round(ratio, 4),
            "p90_on_ms": round(sorted(times["on"])[int(.9 * len(times["on"]))] * 1000, 3),
            "p90_off_ms": round(sorted(times["off"])[int(.9 * len(times["off"]))] * 1000, 3)}
        print(f"[m8-gatec] shard{n}: on {p50['on']:.2f}ms off {p50['off']:.2f}ms "
              f"ratio {ratio:.4f}", flush=True)
    ratios = [c["ratio"] for c in verdict["cells"].values()]
    verdict["verdict"] = ("PROMOTE" if all(r <= 0.95 for r in ratios) else
                          "KEEP-unpromoted" if all(r < 1.00 for r in ratios) else
                          "REVERT")
    Path(args.result_file).write_text(json.dumps(verdict, indent=1))
    print(f"[m8-gatec] verdict {verdict['verdict']} -> {args.result_file}",
          flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("baseline", "gatea", "gatec"))
    ap.add_argument("--baseline-file",
                    default=str(REPO / "data/eval_results/m8_pre_baseline.json"))
    ap.add_argument("--result-file", default=None)
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    args.date = args.date or _dt.date.today().isoformat()
    stamp = args.date.replace("-", "")
    if args.result_file is None:
        args.result_file = str(REPO / "data/eval_results" /
                               f"m8_batch_kernel_gate{args.cmd[-1]}_{stamp}.json")
    {"baseline": cmd_baseline, "gatea": cmd_gatea, "gatec": cmd_gatec}[args.cmd](args)


if __name__ == "__main__":
    main()
