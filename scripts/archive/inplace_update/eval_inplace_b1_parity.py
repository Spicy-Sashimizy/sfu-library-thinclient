#!/usr/bin/env python3
# CLOSED MEASURED 2026-09-30 — in-place bit-update spike harness (docs/archive/inplace_update/); evidence kept, pre-registered bars live in source
"""In-place bit updater, Stage 1 bar B1: format-v3 zero-patch parity.

BAR (verbatim from docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md, Stage 1 table,
commit 8c239e99):

  | **B1 parity** | v3 decoder on the v3 copy with ZERO patches vs A0: top-k′
  (k′ = 200) doc ids AND f32 score bit patterns, E8 recall-max params, every
  query of QA ∪ QT ∪ QD (460) | identical on 460/460 | PASS 460/460; anything
  else FAIL |

ADDENDUM (same file, "Addendum 2026-09-29", commit dc20bf2a):

  - **B1 and B3** additionally REPORT the per-query cost of the added mask
    checks and multiply (decoder v3 vs v2 on an unpatched shard). Reported
    only; B3's 1.05 x threshold already bounds it.

Run AHEAD of the GO gate at the owner's request (encoder/decoder agent,
2026-09-29); the GO rule is not affected. Format: spike/inplace_update/FORMAT_V3.md.

Arms (each in its own subprocess; two builds of the `seismic` module cannot
share one interpreter):
  A0       served .so (.venv site-packages, never rebuilt) on V2COPY, a byte
           copy of the served dv-v2 shard 0 (source:
           data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap,
           manifest byte-identical to the staged served shard).
  V3       side-built .so (patch spike/seismic_upstream_inplace_v3.patch,
           -C target-cpu=x86-64-v3) on V3DIR = the encoder's v3 conversion of
           V2COPY, zero patches (epoch 0, all tags/flags 0, inflation 0).
  V2SIDE   side .so on V2COPY through its unchanged v2 path (build control:
           separates a build difference from a v3-decoder difference).
  REJECT   served .so opening V3DIR must raise (v2 reader rejects v3).
  COST     side .so, one process, both dirs loaded and warmed; per query
           v2 path (V2COPY) vs v3 path (V3DIR), same content, same build;
           1 discarded warm-up pass + 2 measured passes, order alternated per
           query (ABBA); paired per-query ratio and difference.

Search params (E8 recall-max, 03_SPIKE_PLAN.md M9 block): MmapSeismicIndex,
k = k' = 200, query_cut = len(terms), heap_factor = 0.8, sorted first term,
SFU_SEISMIC_M8_BATCH unset (served default). Queries: the Stage-0 encoded
sets /home/vscode/work/inplace_update/stage0/queries.json (QA 240, QT 120,
QD 100; top-64 SPLADE terms by weight, terms known to the token map), token
ids mapped back to token strings through V2COPY's token_to_id_map.bin.

Parity = for every query, the full ordered top-200 list of (doc id string,
f32 score bit pattern) identical to A0. A failure is recorded with the first
differing query and field. Every process asserts which .so it loaded before
the first query and aborts otherwise (ENOMEM-on-9p guard, issue O12).

Results: data/eval_results/inplace_b_<UTCDATE>.json, key "B1" (merged if
the file exists). Run under `flock /tmp/sfu_latency_measure.lock taskset -c 0-7`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
S1 = Path("/home/vscode/work/inplace_update/stage1")
V2COPY = S1 / "v2copy"
V3DIR = S1 / "v3"
SIDE_SO = S1 / "so_v3"
QUERIES = Path("/home/vscode/work/inplace_update/stage0/queries.json")
SERVED_PKG = REPO / ".venv/lib/python3.11/site-packages/seismic"
K = 200
HEAP_FACTOR = 0.8
SETS = ["QA", "QT", "QD"]
COPIED = ["config.json", "forward_offsets.bin", "forward_data.bin", "forward_encoder.bin",
          "posting_lists.bin", "token_to_id_map.bin", "document_mapping_strings.bin",
          "document_mapping_offsets.bin"]


sys.path.insert(0, str(REPO))
from spike.inplace_update.guard import check_live_unchanged, clean_env  # noqa: E402


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def import_seismic(so_dir: str | None):
    if so_dir:
        sys.path.insert(0, so_dir)
    import numpy as np  # noqa: F401
    import seismic
    f = Path(seismic.__file__).resolve()
    want = (Path(so_dir) / "seismic").resolve() if so_dir else SERVED_PKG.resolve()
    assert f.parent == want, f"loaded seismic from {f}, expected {want}"
    assert hasattr(seismic, "MmapSeismicIndex"), "seismic module incomplete"
    if so_dir:
        assert hasattr(seismic, "inplace_v3_convert"), "side .so lacks the v3 patch"
    so = next(f.parent.glob("seismic*.so"))
    return seismic, str(so), hashlib.sha256(so.read_bytes()).hexdigest()


def load_queries():
    import numpy as np
    sys.path.insert(0, str(REPO))
    from spike.inplace_update.shard import load_token_to_id
    tok = load_token_to_id(V2COPY)
    inv = {v: k for k, v in tok.items()}
    Q = json.loads(QUERIES.read_text())
    out = []
    for s in SETS:
        for i, q in enumerate(Q[s]):
            terms = [inv[t] for t in q["terms"]]
            out.append((f"{s}:{i}", terms, np.array(q["w"], dtype=np.float32)))
    assert len(out) == 460, len(out)
    return out


def run_queries(seismic, idx, queries):
    import numpy as np
    dt = seismic.get_seismic_string()
    res = {}
    times = []
    for qid, terms, w in queries:
        comps = np.array(terms, dtype=dt)
        t = time.perf_counter_ns()
        r = idx.search(qid, comps, w, K, len(terms), HEAP_FACTOR)
        times.append(time.perf_counter_ns() - t)
        res[qid] = [[d, struct.unpack("<I", struct.pack("<f", s))[0]] for (_, s, d) in r]
    return res, times


def worker(a):
    clean_env()
    os.environ.pop("SFU_SEISMIC_M8_BATCH", None)
    seismic, so, so_sha = import_seismic(a.so_dir)
    queries = load_queries()
    out = {"arm": a.arm, "so": so, "so_sha256": so_sha, "pid": os.getpid()}
    if a.arm == "encode":
        t = time.time()
        rep = json.loads(seismic.inplace_v3_convert(str(V2COPY), str(V3DIR)))
        out["encoder_report"] = rep
        out["wall_s"] = time.time() - t
    elif a.arm == "reject":
        try:
            seismic.MmapSeismicIndex(str(V3DIR))
            out["rejected"] = False
        except Exception as e:  # noqa: BLE001
            out["rejected"] = True
            out["error"] = f"{type(e).__name__}: {e}"
    elif a.arm in ("A0", "V2SIDE", "V3"):
        d = V3DIR if a.arm == "V3" else V2COPY
        idx = seismic.MmapSeismicIndex(str(d))
        out["forward_format"] = idx.forward_format
        out["n_docs"] = idx.len
        if a.arm == "V3":
            out["inplace_epoch"] = idx.inplace_epoch
            out["inplace_header_info"] = idx.inplace_header_info()
            assert idx.inplace_epoch == 0, "v3 copy is not at epoch 0"
            info = idx.inplace_header_info()
            assert info[2] == 0 and info[3] == 0, f"v3 copy carries patches: {info}"
        idx.touch_slab()
        res, times = run_queries(seismic, idx, queries)
        out["results"] = res
        out["times_ns"] = times
    elif a.arm == "cost":
        i2 = seismic.MmapSeismicIndex(str(V2COPY))
        i3 = seismic.MmapSeismicIndex(str(V3DIR))
        assert i2.forward_format == "dotvbyte_fixedu8_v2"
        assert i3.forward_format == "dotvbyte_fixedu8_v2_inplace_v3" and i3.inplace_epoch == 0
        i2.touch_slab(); i3.touch_slab()
        import numpy as np
        dt = seismic.get_seismic_string()
        rng = random.Random(20260929)
        passes = []
        for p in range(3):
            order = list(range(len(queries)))
            rng.shuffle(order)
            rows = []
            for j, qi in enumerate(order):
                qid, terms, w = queries[qi]
                comps = np.array(terms, dtype=dt)
                tt = {}
                seq = ["v2", "v3"] if (j + p) % 2 == 0 else ["v3", "v2"]
                for arm in seq:
                    ix = i2 if arm == "v2" else i3
                    t = time.perf_counter_ns()
                    ix.search(qid, comps, w, K, len(terms), HEAP_FACTOR)
                    tt[arm] = time.perf_counter_ns() - t
                rows.append([qid, tt["v2"], tt["v3"], seq[0]])
            passes.append(rows)
            log("cost pass", p, "done")
        out["passes"] = passes
    Path(a.out).write_text(json.dumps(out))


def sub(arm, so_dir, out, timeout):
    env = clean_env(dict(os.environ))
    env.pop("SFU_SEISMIC_M8_BATCH", None)
    cmd = [sys.executable, __file__, "worker", "--arm", arm, "--out", str(out)]
    if so_dir:
        cmd += ["--so-dir", str(so_dir)]
    log("start", arm)
    t = time.time()
    subprocess.run(cmd, env=env, check=True, timeout=timeout)
    log("done", arm, round(time.time() - t, 1), "s")
    return json.loads(Path(out).read_text())


def compare(ref, got):
    n_ok = 0
    first = None
    for qid in ref:
        a, b = ref[qid], got.get(qid)
        if a == b:
            n_ok += 1
            continue
        if first is None:
            info = {"query": qid, "len_ref": len(a), "len_got": None if b is None else len(b)}
            if b is not None:
                for r, (x, y) in enumerate(zip(a, b)):
                    if x != y:
                        info.update({"rank": r, "field": "doc_id" if x[0] != y[0] else "score_bits",
                                     "ref": x, "got": y})
                        break
            first = info
    return n_ok, first


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q / 100 * (len(xs) - 1))))]


def cost_summary(passes):
    meas = passes[1:]
    per_q = {}
    for rows in meas:
        for qid, t2, t3, _ in rows:
            per_q.setdefault(qid, []).append((t2, t3))
    r = []
    d = []
    v2m, v3m = [], []
    for qid, xs in per_q.items():
        m2 = statistics.median([x[0] for x in xs])
        m3 = statistics.median([x[1] for x in xs])
        v2m.append(m2); v3m.append(m3)
        r.append(m3 / m2); d.append((m3 - m2) / 1e6)
    rng = random.Random(0)
    boots = []
    for _ in range(10000):
        s = [r[rng.randrange(len(r))] for _ in r]
        boots.append(statistics.fmean(s))
    boots.sort()
    return {
        "n_queries": len(r), "measured_passes": len(meas), "discarded_warmup_passes": 1,
        "v2_ms": {"p50": pct(v2m, 50) / 1e6, "p95": pct(v2m, 95) / 1e6, "mean": statistics.fmean(v2m) / 1e6},
        "v3_ms": {"p50": pct(v3m, 50) / 1e6, "p95": pct(v3m, 95) / 1e6, "mean": statistics.fmean(v3m) / 1e6},
        "ratio_of_p50": pct(v3m, 50) / pct(v2m, 50),
        "per_query_ratio": {"median": statistics.median(r), "mean": statistics.fmean(r),
                            "p5": pct(r, 5), "p95": pct(r, 95),
                            "mean_ci95_bootstrap": [boots[249], boots[9749]]},
        "per_query_diff_ms": {"median": statistics.median(d), "mean": statistics.fmean(d)},
        "includes": "3 masks + visibility XOR per posting (both passes), inflation load + multiply per block, "
                    "list_dir load + compare per query term, header read + 2x FNV per query, row override "
                    "load per winner",
    }


def driver(a):
    utc = time.strftime("%Y%m%d", time.gmtime())
    out_path = Path(a.out or REPO / f"data/eval_results/inplace_b_{utc}.json")
    clean_env()
    guard_start = check_live_unchanged("b1-start")
    tmp = S1 / "b1_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    assert (V2COPY / ".copy_ok").exists(), "V2COPY missing"
    assert (SIDE_SO / "seismic").is_dir(), "side .so missing"
    src_man = (REPO / "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap/manifest.json").read_bytes()
    assert (V2COPY / "manifest.json").read_bytes() == src_man
    enc = None
    if not (V3DIR / "inplace_header.bin").exists():
        assert not V3DIR.exists(), f"{V3DIR} exists without a header (partial encode): remove it by hand"
        enc = sub("encode", SIDE_SO, tmp / "encode.json", 3600)
        (S1 / "encode_report.json").write_text(json.dumps(enc["encoder_report"], indent=2))
    else:
        enc = {"encoder_report": json.loads((S1 / "encode_report.json").read_text()), "reused": True}
    import filecmp
    identical = {f: filecmp.cmp(V2COPY / f, V3DIR / f, shallow=False) for f in COPIED}
    log("copied files identical:", all(identical.values()))

    rej = sub("reject", None, tmp / "reject.json", 600)
    a0 = sub("A0", None, tmp / "a0.json", 7200)
    v3 = sub("V3", SIDE_SO, tmp / "v3.json", 7200)
    v2s = sub("V2SIDE", SIDE_SO, tmp / "v2side.json", 7200)
    cost = sub("cost", SIDE_SO, tmp / "cost.json", 14400)

    n_v3, first_v3 = compare(a0["results"], v3["results"])
    n_v2s, first_v2s = compare(a0["results"], v2s["results"])
    per_set = {}
    for s in SETS:
        ks = [q for q in a0["results"] if q.startswith(s + ":")]
        per_set[s] = {"n": len(ks), "identical": sum(1 for q in ks if a0["results"][q] == v3["results"].get(q))}
    lens = [len(v) for v in a0["results"].values()]
    verdict = "PASS" if n_v3 == 460 else "FAIL"
    b1 = {
        "bar": "B1 parity: v3 decoder on v3 copy, zero patches, vs A0; top-200 ids + f32 score bits; "
               "E8 recall-max; 460 queries; PASS 460/460 else FAIL",
        "run_ahead_of_go": True,
        "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
        "params": {"k": K, "query_cut": "len(terms)", "heap_factor": HEAP_FACTOR, "sorted": True,
                   "m8_batch": "unset (served default)"},
        "dirs": {"v2copy": str(V2COPY), "v3": str(V3DIR),
                 "source": "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap"},
        "builds": {"served": {"so": a0["so"], "sha256": a0["so_sha256"]},
                   "side_v3": {"so": v3["so"], "sha256": v3["so_sha256"], "patch": "spike/seismic_upstream_inplace_v3.patch",
                               "rustflags": "-C target-cpu=x86-64-v3"}},
        "encoder": enc["encoder_report"],
        "copied_files_byte_identical": identical,
        "v2_reader_rejects_v3": rej,
        "v3_state": {"forward_format": v3["forward_format"], "inplace_epoch": v3["inplace_epoch"],
                     "header_info(slot0,slot1,nonzero_infl,non_native_lists)": v3["inplace_header_info"]},
        "result_lengths": {"min": min(lens), "max": max(lens)},
        "parity_v3_vs_A0": {"identical": n_v3, "of": 460, "per_set": per_set, "first_difference": first_v3},
        "control_v2side_vs_A0": {"identical": n_v2s, "of": 460, "first_difference": first_v2s},
        "mask_cost": cost_summary(cost["passes"]),
        "mask_cost_note": "decoder v3 vs v2 (same side build, same content: V3DIR vs V2COPY); latency "
                          "run under the latency lock, one process, taskset 0-7; host quiet-gating as the "
                          "lock provides, no separate quiet gate",
        "single_pass_ms_p50": {"A0": pct(a0["times_ns"], 50) / 1e6, "V3": pct(v3["times_ns"], 50) / 1e6,
                               "V2SIDE": pct(v2s["times_ns"], 50) / 1e6},
        "verdict": verdict,
        "wall_s": round(time.time() - t0, 1),
        "live_index_guard": [guard_start, check_live_unchanged("b1-end")],
        "v3_sentinel": json.loads((V3DIR / ".inplace_work_copy").read_text()),
    }
    doc = json.loads(out_path.read_text()) if out_path.exists() else {}
    doc["B1"] = b1
    out_path.write_text(json.dumps(doc, indent=2))
    log("wrote", out_path, "verdict", verdict, n_v3, "/ 460; control", n_v2s)
    print(json.dumps({"verdict": verdict, "identical": n_v3, "control": n_v2s,
                      "first_difference": first_v3, "mask_cost": b1["mask_cost"]["per_query_ratio"],
                      "rejected": rej.get("rejected")}))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    w = sp.add_parser("worker")
    w.add_argument("--arm", required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--so-dir", default=None)
    r = sp.add_parser("run")
    r.add_argument("--out", default=None)
    a = ap.parse_args()
    worker(a) if a.cmd == "worker" else driver(a)


if __name__ == "__main__":
    main()
