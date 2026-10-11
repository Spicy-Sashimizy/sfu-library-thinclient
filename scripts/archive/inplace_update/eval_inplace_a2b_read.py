#!/usr/bin/env python3
# CLOSED MEASURED 2026-09-30 — in-place bit-update spike harness (docs/archive/inplace_update/); evidence kept, pre-registered bars live in source
"""In-place v3 decoder: A2b heap-unit read path + reader registration test.

Task (coordinator, 2026-09-29, after B1; plan 06 "Addendum 2026-09-29
(third)", "Decoder scope extension (A2b read path)"): the v3 decoder reads a
list from an A2b heap unit when the active `list_dir` entry is not native,
with the unit's own scalars authoritative (block count may change), no
inflation applied, views cached per (list, offset), and reader registration
in `readers.bin` (FORMAT_V3.md revision 4). Test on a synthetic shard with one
rewritten list whose block count changed; report two costs separately from
B1's mask cost: reader registration per query and unit-view build on first
touch. This is a correctness test plus cost probes, not a pre-registered bar.

Synthetic shard: a COPY of a 160,347-doc dv-v2 SEISMIC generation built by
spike/delta_ingest for M4 (read-only source
/home/vscode/work/inplace_update/m4/root_n1/g0001/seismic/delta_g0001.dotvbyte.v2.mmap),
converted to v3 by the side-built encoder.

Procedure (each step in its own subprocess, side .so only):
  1. baseline: v3 copy, zero patches, 460 queries (QA+QT+QD of the Stage-0
     query file; token ids mapped to strings through shard 0's token map and
     re-resolved by the synthetic shard's map), E8 recall-max params.
  2. fixture (Rust `inplace_v3_a2b_fixture`): list t = the list with >= 3
     blocks that occurs in the most queries; block n_blocks // 2 removed
     (its postings dropped, summary rebuilt from the remaining blocks);
     written as a heap unit and published in both list_dir banks at epoch 0;
     the active-bank inflation codes of list t's native blocks set to 255
     (must be ignored); an oracle dv-v2 dir carrying the same list body
     natively (spliced) is written beside it.
  3. check: v3 decoder (unit) vs v2 decoder on the oracle, same side build:
     ordered top-200 (doc id, f32 score bits) identical on 460/460 = PASS.
     Non-vacuity: number of queries whose v3 result differs from step 1.
     After the queries every readers.bin slot must be free.
  4. costs: `bench_registration(100000)` (register + unregister, ns);
     `bench_unit_build(t, 200)` (uncached parse + checksum + view build, and
     checksum alone, ns); first-touch query time after clearing the unit
     cache vs the same query cached; paired per-query time with registration
     on vs off (1 discarded + 2 measured passes, ABBA order).

Results: data/eval_results/inplace_a2b_read_<UTCDATE>.json. Run under
`flock /tmp/sfu_latency_measure.lock taskset -c 0-7`.

Rerun 2026-09-30 (coordinator, after the 04:11Z run came back vacuous: the
dropped block n_blocks // 2 of list 742 held 5 postings that reached no
top-200, and a second rerun dropping the block whose docs appear most in the
top-200 was ALSO vacuous — every such doc is still visited through another
query term's list and scored identically): the fixture now drops the (list,
block) pair that maximises the number of baseline queries with a top-200 doc
reached ONLY through that list (no other term list of the query holds the
doc), so the drop must remove it from those queries' results. Work root overridable with SFU_INPLACE_A2B_ROOT (the rerun uses
/home/vscode/work/inplace_update/stage3/encoder/a2b, cores 8-15, no lock);
everything else identical.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import random
import shutil
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
S1 = Path("/home/vscode/work/inplace_update/stage1")
ROOT = Path(os.environ.get("SFU_INPLACE_A2B_ROOT") or S1)
SYN = ROOT / "synth"
SRC = Path("/home/vscode/work/inplace_update/m4/root_n1/g0001/seismic/delta_g0001.dotvbyte.v2.mmap")
SO = ROOT / "so_a2b"
SHARD0_TOK = S1 / "v2copy"
QUERIES = Path("/home/vscode/work/inplace_update/stage0/queries.json")
K = 200
HF = 0.8


sys.path.insert(0, str(REPO))
from spike.inplace_update.guard import check_live_unchanged, clean_env  # noqa: E402


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def imp():
    sys.path.insert(0, str(SO))
    import numpy  # noqa: F401
    import seismic
    f = Path(seismic.__file__).resolve()
    assert f.parent == (SO / "seismic").resolve(), f"loaded {f}"
    assert hasattr(seismic, "inplace_v3_a2b_fixture"), "side .so lacks the A2b read path"
    return seismic


def queries():
    import numpy as np
    sys.path.insert(0, str(REPO))
    from spike.inplace_update.shard import load_token_to_id
    inv = {v: k for k, v in load_token_to_id(SHARD0_TOK).items()}
    Q = json.loads(QUERIES.read_text())
    return [(f"{s}:{i}", [inv[t] for t in q["terms"]], np.array(q["w"], dtype=np.float32))
            for s in ["QA", "QT", "QD"] for i, q in enumerate(Q[s])]


def run(seismic, idx, qs):
    import numpy as np
    dt = seismic.get_seismic_string()
    out, times = {}, []
    for qid, terms, w in qs:
        t = time.perf_counter_ns()
        r = idx.search(qid, np.array(terms, dtype=dt), w, K, len(terms), HF)
        times.append(time.perf_counter_ns() - t)
        out[qid] = [[d, struct.unpack("<I", struct.pack("<f", s))[0]] for (_, s, d) in r]
    return out, times


def worker(a):
    clean_env()
    os.environ.pop("SFU_SEISMIC_M8_BATCH", None)
    seismic = imp()
    qs = queries()
    res = {"step": a.step}
    if a.step == "prepare":
        if SYN.exists():
            shutil.rmtree(SYN)
        (SYN / "v2").mkdir(parents=True)
        for f in SRC.iterdir():
            shutil.copy2(f, SYN / "v2" / f.name)
        res["encoder_report"] = json.loads(seismic.inplace_v3_convert(str(SYN / "v2"), str(SYN / "v3")))
    elif a.step == "baseline":
        idx = seismic.MmapSeismicIndex(str(SYN / "v3"))
        assert idx.inplace_epoch == 0 and idx.inplace_header_info()[3] == 0
        res["results"], _ = run(seismic, idx, qs)
        man = json.loads((SYN / "v3" / "manifest.json").read_text())
        from spike.inplace_update.shard import load_token_to_id
        tok = load_token_to_id(SYN / "v3")
        cnt = collections.Counter()
        for _, terms, _ in qs:
            for t in set(terms):
                if t in tok and man["posting_lists"][tok[t]]["n_summaries"] >= 3:
                    cnt[tok[t]] += 1
        from spike.inplace_update.shard import ShardView
        view = ShardView(SYN / "v2", forward="dv")
        ids = view.doc_ids()
        row_of = {}
        for r_, d_ in enumerate(ids.tolist()):
            row_of.setdefault(d_, r_)
        rows_cache, bo_cache = {}, {}
        def rows_of(t_):
            if t_ not in rows_cache:
                rr = view.list_rows_checked(t_)
                rows_cache[t_] = (set(rr.tolist()), rr)
                bo_cache[t_] = view.block_offsets(t_)
            return rows_cache[t_]
        affected = collections.defaultdict(set)
        pairs = collections.Counter()
        for qid, terms, _ in qs:
            lists = sorted({tok[x] for x in terms if x in tok})
            sets = {t_: rows_of(t_)[0] for t_ in lists}
            for d, _ in res["results"][qid]:
                r_ = row_of.get(int(d[1:]))
                if r_ is None:
                    continue
                holders = [t_ for t_ in lists if r_ in sets[t_]]
                if len(holders) != 1:
                    continue
                t_ = holders[0]
                if man["posting_lists"][t_]["n_summaries"] < 3:
                    continue
                import numpy as np
                slot = int(np.searchsorted(rows_of(t_)[1], r_)) if False else int(np.nonzero(rows_of(t_)[1] == r_)[0][0])
                blk = int(np.searchsorted(bo_cache[t_], slot, side="right") - 1)
                affected[(t_, blk)].add(qid)
                pairs[(t_, blk)] += 1
        (t, blk), qset = max(affected.items(), key=lambda kv: (len(kv[1]), pairs[kv[0]]))
        res["chosen_list"] = t
        res["chosen_list_queries"] = cnt[t]
        res["chosen_list_blocks"] = man["posting_lists"][t]["n_summaries"]
        res["chosen_block"] = blk
        res["chosen_block_affected_queries"] = len(qset)
        res["chosen_block_sole_path_hits"] = pairs[(t, blk)]
        res["chosen_block_postings"] = int(bo_cache[t][blk + 1] - bo_cache[t][blk])
        res["most_queried_list_with_3_blocks"] = cnt.most_common(1)[0]
        res["block_choice_rule"] = ("(list, block) pair maximising the number of baseline queries with a top-200 doc "
                                    "reached ONLY through that list (its other query terms' lists do not hold the doc); "
                                    "ties: most such (query, doc) pairs; lists with >= 3 blocks")
    elif a.step == "fixture":
        b = json.loads(Path(a.base).read_text())
        t = b["chosen_list"]
        res["fixture"] = json.loads(seismic.inplace_v3_a2b_fixture(
            str(SYN / "v3"), t, b.get("chosen_block", b["chosen_list_blocks"] // 2), str(SYN / "oracle"), True))
    elif a.step == "check":
        b = json.loads(Path(a.base).read_text())
        t = b["chosen_list"]
        v3 = seismic.MmapSeismicIndex(str(SYN / "v3"))
        orc = seismic.MmapSeismicIndex(str(SYN / "oracle"))
        assert orc.forward_format == "dotvbyte_fixedu8_v2"
        info = v3.inplace_header_info()
        res["header_info"] = info
        assert info[3] == 1, f"expected one non-native list, got {info}"
        res["registration_state"] = v3.reader_registration_state()
        r3, _ = run(seismic, v3, qs)
        ro, _ = run(seismic, orc, qs)
        same = sum(1 for q in ro if ro[q] == r3.get(q))
        first = next((q for q in ro if ro[q] != r3.get(q)), None)
        changed = sum(1 for q in ro if b["results"][q] != r3[q])
        rb = (SYN / "v3" / "readers.bin").read_bytes()
        busy = [i for i in range(256) if struct.unpack_from("<Q", rb, 64 * i)[0] != 0]
        res["parity_unit_vs_oracle"] = {"identical": same, "of": len(ro), "first_difference": first}
        res["queries_changed_vs_zero_patch_baseline"] = changed
        res["readers_busy_after_queries"] = busy
        res["unit_cache_len"] = v3.unit_cache_len()
        res["verdict"] = "PASS" if same == len(ro) and changed > 0 and not busy else "FAIL"
        res["cost_registration_ns_per_query"] = v3.bench_registration(100000)
        bu, ck = v3.bench_unit_build(t, 200)
        res["cost_unit_build_ns"] = {"build_incl_checksum": bu, "checksum_only": ck}
        import numpy as np
        dt = seismic.get_seismic_string()
        from spike.inplace_update.shard import load_token_to_id
        tok = load_token_to_id(SYN / "v3")
        with_t = [q for q in qs if any(tok.get(x) == t for x in q[1])]
        ft = []
        for qid, terms, w in with_t[:40]:
            comps = np.array(terms, dtype=dt)
            v3.unit_cache_clear()
            s0 = time.perf_counter_ns(); v3.search(qid, comps, w, K, len(terms), HF); s1 = time.perf_counter_ns()
            v3.search(qid, comps, w, K, len(terms), HF); s2 = time.perf_counter_ns()
            ft.append(((s1 - s0) - (s2 - s1)) / 1e6)
        res["first_touch_minus_cached_ms"] = {"n": len(ft), "median": statistics.median(ft),
                                              "mean": statistics.fmean(ft)}
        rng = random.Random(20260929)
        per = collections.defaultdict(list)
        for p in range(3):
            order = list(range(len(qs)))
            rng.shuffle(order)
            for j, qi in enumerate(order):
                qid, terms, w = qs[qi]
                comps = np.array(terms, dtype=dt)
                tt = {}
                for arm in (["on", "off"] if (j + p) % 2 == 0 else ["off", "on"]):
                    v3.set_reader_registration(arm == "on")
                    s0 = time.perf_counter_ns()
                    v3.search(qid, comps, w, K, len(terms), HF)
                    tt[arm] = time.perf_counter_ns() - s0
                if p > 0:
                    per[qid].append((tt["on"], tt["off"]))
        v3.set_reader_registration(True)
        d = [statistics.median(x[0] for x in v) / 1e3 - statistics.median(x[1] for x in v) / 1e3 for v in per.values()]
        res["registration_on_minus_off_us_per_query"] = {"n": len(d), "median": statistics.median(d),
                                                          "mean": statistics.fmean(d)}
    Path(a.out).write_text(json.dumps(res))


def sub(step, out, base=None):
    env = clean_env(dict(os.environ))
    env.pop("SFU_SEISMIC_M8_BATCH", None)
    cmd = [sys.executable, __file__, "worker", "--step", step, "--out", str(out)]
    if base:
        cmd += ["--base", str(base)]
    log("start", step)
    subprocess.run(cmd, env=env, check=True, timeout=7200)
    return json.loads(Path(out).read_text())


def driver(a):
    clean_env()
    guard_start = check_live_unchanged("a2b-start")
    tmp = ROOT / "a2b_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    prep = sub("prepare", tmp / "prepare.json")
    base = sub("baseline", tmp / "baseline.json")
    fix = sub("fixture", tmp / "fixture.json", tmp / "baseline.json")
    chk = sub("check", tmp / "check.json", tmp / "baseline.json")
    out = {
        "what": "A2b heap-unit read path + readers.bin registration (decoder), synthetic shard; "
                "correctness test and cost probes, not a pre-registered bar",
        "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
        "synthetic_source": str(SRC),
        "encoder": prep["encoder_report"],
        "chosen_list": {k: base[k] for k in base if k.startswith("chosen_") or k == "block_choice_rule"},
        "work_root": str(ROOT),
        "so_sha256": hashlib.sha256(next((SO / "seismic").glob("seismic*.so")).read_bytes()).hexdigest(),
        "fixture": fix["fixture"],
        **{k: v for k, v in chk.items() if k != "step"},
        "params": {"k": K, "heap_factor": HF, "query_cut": "len(terms)"},
        "wall_s": round(time.time() - t0, 1),
        "live_index_guard": [guard_start, check_live_unchanged("a2b-end")],
    }
    utc = time.strftime("%Y%m%d", time.gmtime())
    p = Path(a.out or REPO / f"data/eval_results/inplace_a2b_read_{utc}.json")
    p.write_text(json.dumps(out, indent=2))
    log("wrote", p, out["verdict"])
    print(json.dumps({k: out[k] for k in ["verdict", "parity_unit_vs_oracle", "queries_changed_vs_zero_patch_baseline",
                                          "cost_registration_ns_per_query", "cost_unit_build_ns",
                                          "first_touch_minus_cached_ms", "registration_on_minus_off_us_per_query"]}))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    w = sp.add_parser("worker")
    w.add_argument("--step", required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--base", default=None)
    r = sp.add_parser("run")
    r.add_argument("--out", default=None)
    a = ap.parse_args()
    worker(a) if a.cmd == "worker" else driver(a)


if __name__ == "__main__":
    main()
