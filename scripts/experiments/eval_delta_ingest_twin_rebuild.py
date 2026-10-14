#!/usr/bin/env python3
"""Delta-ingest item D (2026-09-29): can one served SEISMIC shard be rebuilt
from its f16 twin alone?

Subcommands (run in order; every output goes under --work, default
/var/tmp/sfu_delta_D_20260929/; data/seismic_150m/ is opened read-only):

  verify   stats on the f16 twin (doc count, nnz distribution, value range,
           f16 grid evidence) -> <work>/verify.json
  dump     twin forward rows + doc ids -> <work>/twin_shard{K}.jsonl in the
           exact {"id","vector"} line format shard_spool.py fed the original
           build (values written as the exact decimal of the stored f16, so the
           rebuild's f32->f16 ingest reproduces the stored bits)
  build    SeismicIndex.build(jsonl, **generation.SEISMIC_PARAMS) + save, in a
           child process; wall time + peak RSS (ru_maxrss of the child, and a
           2 s VmRSS poll) -> <work>/build.json
  convert  c1a_mmap_index then convert_f16_to_dotvbyte --value-scale perdoc,
           the same argv as spike/delta_ingest/generation.build_seismic_shard
           -> <work>/convert.json
  parity   rebuilt dv-v2 shard vs served dv-v2 shard, top-10 overlap
           -> <work>/parity.json
  record   merge the above into data/eval_results/delta_ingest_twin_rebuild_20260929.json

PRE-REGISTERED PARITY BAR (written 2026-09-29 before any comparison ran):
  query sets     : the 120 topics (data/sfu_eval_queries.json, "query" field,
                   the n120 set) + n=100 diverse queries
                   (data/eval_results/diverse_queries.json via
                   e6_forward_codec_proto.load_queries, first 100 distinct
                   paraphrases).
  encoding       : E8 harness conventions (scripts/seismic_testbed/e8_dvv2_gates.py):
                   encode_splade(q, "models/splade_onnx_fp16"), top-64 terms by
                   weight, all 64 passed to the engine.
  search params  : E8 recall-max params, identical on both shards:
                   seismic.MmapSeismicIndex, k=k'=200, query_cut=len(terms),
                   heap_factor=0.8, SFU_SEISMIC_PREFLOOR=2 in the environment.
  metric         : overlap@10 = |top10_rebuilt ∩ top10_served| / 10 per query
                   on doc-id strings (the E5 row permutation of the served
                   shard is therefore irrelevant).
  PASS iff       : mean overlap@10 >= 0.99 on EACH query set, the E8 per-shard
                   bar (served dv-v2 vs its f16 twin measured 0.993-0.997).
  Reported, not gated: min overlap@10, count of queries with identical top-10
                   (as a set and in order).
  A FAIL is recorded as a FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import struct
import subprocess
import sys
import threading
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
PLAN01 = REPO / "data/seismic_150m/index/plan01"
PY = REPO / ".venv/bin/python3"
RELEASE = REPO / "spike/seismic_upstream/target/release"
C1A_BIN = RELEASE / "c1a_mmap_index"
DOTVBYTE_BIN = RELEASE / "convert_f16_to_dotvbyte"
SEISMIC_PARAMS = dict(n_postings=3500, centroid_fraction=0.1, min_cluster_size=2,
                      summary_energy=0.4, max_fraction=1.5, doc_cut=15)
RESULT = REPO / "data/eval_results/delta_ingest_twin_rebuild_20260929.json"
BAR = 0.99


def twin_dir(k: int) -> Path:
    return PLAN01 / f"global_shard{k}of8.mmap"


def served_dir(k: int) -> Path:
    return PLAN01 / f"global_shard{k}of8.dotvbyte.e5.v2.mmap"


def load_token_to_id(mmap_dir: Path) -> dict[str, int]:
    raw = (mmap_dir / "token_to_id_map.bin").read_bytes()
    off = 0
    (count,) = struct.unpack_from("<Q", raw, off); off += 8
    out = {}
    for _ in range(count):
        (slen,) = struct.unpack_from("<Q", raw, off); off += 8
        s = raw[off:off + slen].decode("utf-8"); off += slen
        (v,) = struct.unpack_from("<Q", raw, off); off += 8
        out[s] = v
    assert off == len(raw)
    return out


def open_twin(k: int):
    d = twin_dir(k)
    offs = np.memmap(d / "forward_offsets.bin", dtype=np.uint64, mode="r")
    comps = np.memmap(d / "forward_components.bin", dtype=np.uint16, mode="r")
    vals = np.memmap(d / "forward_values.bin", dtype=np.float16, mode="r")
    moffs = np.memmap(d / "document_mapping_offsets.bin", dtype=np.uint64, mode="r")
    return offs, comps, vals, moffs


def jnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── verify ──────────────────────────────────────────────────────────────────
def cmd_verify(a):
    k = a.shard
    offs, comps, vals, moffs = open_twin(k)
    man = json.loads((twin_dir(k) / "manifest.json").read_text())
    cfg = json.loads((twin_dir(k) / "config.json").read_text())
    n = len(offs) - 1
    o = np.asarray(offs, dtype=np.int64)
    nnz = np.diff(o)
    tok = load_token_to_id(twin_dir(k))
    rng = np.random.default_rng(42)
    sample_rows = rng.choice(n, size=200_000, replace=False)
    sample_rows.sort()
    sv, sc, sorted_ok = [], [], 0
    for r in sample_rows:
        c = np.asarray(comps[o[r]:o[r + 1]])
        v = np.asarray(vals[o[r]:o[r + 1]])
        sv.append(v)
        sc.append(c)
        sorted_ok += int(np.all(np.diff(c.astype(np.int64)) > 0))
    sv = np.concatenate(sv).astype(np.float32)
    sc = np.concatenate(sc)
    per_doc_min = []
    for r in sample_rows[:20000]:
        v = np.asarray(vals[o[r]:o[r + 1]]).astype(np.float32)
        per_doc_min.append(float(v.min()))
    per_doc_min = np.array(per_doc_min)
    hist = np.bincount(np.minimum(nnz, 400))
    top_counts = sorted(((int(c), int(i)) for i, c in enumerate(hist) if c), reverse=True)[:10]
    out = {
        "shard": k, "twin_dir": str(twin_dir(k)), "measured_utc": jnow(),
        "config": cfg,
        "n_docs_offsets": int(n), "n_docs_manifest": int(man["n_docs"]),
        "n_doc_mapping": int(len(moffs) - 1),
        "nnz_total": int(o[-1]), "manifest_forward_components_len": int(man["forward_components_len"]),
        "nnz_mean": float(nnz.mean()), "nnz_min": int(nnz.min()), "nnz_max": int(nnz.max()),
        "nnz_percentiles": {p: float(np.percentile(nnz, p)) for p in (1, 5, 25, 50, 75, 95, 99, 99.9)},
        "nnz_zero_docs": int((nnz == 0).sum()),
        "nnz_most_common": [{"nnz": i, "docs": c} for c, i in top_counts],
        "docs_at_nnz_max": int((nnz == nnz.max()).sum()),
        "vocab_size_token_map": len(tok), "max_component_id_sample": int(sc.max()),
        "sample_docs": int(len(sample_rows)),
        "sample_components_strictly_increasing_frac": sorted_ok / len(sample_rows),
        "sample_value_min": float(sv.min()), "sample_value_max": float(sv.max()),
        "sample_value_percentiles": {p: float(np.percentile(sv, p)) for p in (0.1, 1, 5, 50, 95, 99)},
        "sample_nonpositive_values": int((sv <= 0).sum()),
        "sample_distinct_value_bitpatterns": int(len(np.unique(sv.astype(np.float16).view(np.uint16)))),
        "sample_per_doc_min_value_percentiles": {p: float(np.percentile(per_doc_min, p)) for p in (1, 5, 50, 95, 99)},
    }
    Path(a.work).mkdir(parents=True, exist_ok=True)
    (Path(a.work) / "verify.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


# ── dump ────────────────────────────────────────────────────────────────────
_G: dict = {}


def _init_worker(k: int):
    offs, comps, vals, moffs = open_twin(k)
    tok = load_token_to_id(twin_dir(k))
    id2tok = [None] * (max(tok.values()) + 1)
    for s, i in tok.items():
        id2tok[i] = json.dumps(s, ensure_ascii=False) + ":"
    bits = np.arange(65536, dtype=np.uint16).view(np.float16).astype(np.float64)
    vstr = [repr(float(x)) if np.isfinite(x) else "null" for x in bits]
    _G.update(offs=offs, comps=comps, vals=vals, moffs=moffs, id2tok=id2tok, vstr=vstr,
              strings=str(twin_dir(k) / "document_mapping_strings.bin"))


def _dump_range(args):
    lo, hi, path = args
    offs, comps, vals, moffs = _G["offs"], _G["comps"], _G["vals"], _G["moffs"]
    id2tok, vstr = _G["id2tok"], _G["vstr"]
    o = np.asarray(offs[lo:hi + 1], dtype=np.int64)
    m = np.asarray(moffs[lo:hi + 1], dtype=np.int64)
    with open(_G["strings"], "rb") as fh:
        fh.seek(int(m[0]))
        blob = fh.read(int(m[-1] - m[0]))
    c_all = np.asarray(comps[o[0]:o[-1]]).tolist()
    v_all = np.asarray(vals[o[0]:o[-1]]).view(np.uint16).tolist()
    base_o, base_m = int(o[0]), int(m[0])
    lines = []
    nnz = 0
    with open(path, "w", encoding="utf-8") as w:
        for i in range(hi - lo):
            a0, a1 = int(o[i]) - base_o, int(o[i + 1]) - base_o
            did = blob[int(m[i]) - base_m:int(m[i + 1]) - base_m].decode("utf-8")
            body = ",".join([id2tok[c] + vstr[v] for c, v in zip(c_all[a0:a1], v_all[a0:a1])])
            lines.append('{"id":' + json.dumps(did, ensure_ascii=False) + ',"vector":{' + body + "}}\n")
            nnz += a1 - a0
            if len(lines) >= 20000:
                w.write("".join(lines))
                lines = []
        w.write("".join(lines))
    return hi - lo, nnz


def cmd_dump(a):
    k = a.shard
    work = Path(a.work)
    parts = work / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    offs, _, _, moffs = open_twin(k)
    n = len(offs) - 1
    assert len(moffs) - 1 == n
    step = 60_000
    jobs = [(lo, min(lo + step, n), str(parts / f"part_{lo:09d}.jsonl")) for lo in range(0, n, step)]
    t0 = time.time()
    docs = nnz = 0
    with Pool(a.workers, initializer=_init_worker, initargs=(k,)) as pool:
        for d, z in pool.imap(_dump_range, jobs):
            docs += d
            nnz += z
            print(f"[dump] {docs}/{n} docs {time.time() - t0:.0f}s", flush=True)
    t_parts = time.time() - t0
    out = work / f"twin_shard{k}.jsonl"
    with open(out, "wb") as w:
        for _, _, p in jobs:
            with open(p, "rb") as r:
                while True:
                    b = r.read(64 << 20)
                    if not b:
                        break
                    w.write(b)
            os.unlink(p)
    parts.rmdir()
    wall = time.time() - t0
    lines = 0
    with open(out, "rb") as r:
        while True:
            b = r.read(64 << 20)
            if not b:
                break
            lines += b.count(b"\n")
    rec = {"shard": k, "path": str(out), "docs": docs, "lines": lines, "nnz": nnz,
           "twin_nnz": int(offs[-1]), "bytes": out.stat().st_size, "workers": a.workers,
           "parts_seconds": round(t_parts, 1), "wall_seconds": round(wall, 1),
           "finished_utc": jnow(),
           "format": 'jsonl, one line per twin row in twin row order: {"id": <doc id string from '
                     'document_mapping_strings.bin>, "vector": {<token string>: <exact decimal of stored f16>}}'}
    assert docs == n == lines and nnz == int(offs[-1]), rec
    import random
    rng = random.Random(7)
    picks = sorted(rng.sample(range(n), 200))
    _init_worker(k)
    o = np.asarray(offs, dtype=np.int64)
    tok = load_token_to_id(twin_dir(k))
    want = set(picks)
    checked = 0
    with open(out, encoding="utf-8") as r:
        for i, line in enumerate(r):
            if i in want:
                d = json.loads(line)
                c = np.asarray(_G["comps"][o[i]:o[i + 1]])
                v = np.asarray(_G["vals"][o[i]:o[i + 1]])
                got_c = np.array([tok[t] for t in d["vector"]], dtype=np.uint16)
                got_v = np.array(list(d["vector"].values()), dtype=np.float32).astype(np.float16)
                assert np.array_equal(got_c, c) and np.array_equal(got_v.view(np.uint16), v.view(np.uint16)), i
                checked += 1
            if i > picks[-1]:
                break
    rec["roundtrip_checked_docs"] = checked
    (work / "dump.json").write_text(json.dumps(rec, indent=1))
    (work / "DUMP_READY.txt").write_text(str(out) + "\n")
    print(json.dumps(rec, indent=1))


# ── build ───────────────────────────────────────────────────────────────────
def cmd_build_child(a):
    import seismic
    t0 = time.perf_counter()
    idx = seismic.SeismicIndex.build(a.jsonl, num_threads=a.threads, **SEISMIC_PARAMS)
    tb = time.perf_counter() - t0
    info = {"docs": int(idx.len), "dim": int(idx.dim), "nnz": int(idx.nnz), "build_seconds": round(tb, 1)}
    t1 = time.perf_counter()
    idx.save(a.stem)
    info["save_seconds"] = round(time.perf_counter() - t1, 1)
    info["ru_maxrss_gb_self"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    print("CHILD_JSON " + json.dumps(info), flush=True)


def _poll_rss(pid, box, stop):
    p = Path(f"/proc/{pid}/status")
    while not stop.is_set():
        try:
            for line in p.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    box[0] = max(box[0], int(line.split()[1]) / 1024 / 1024)
        except OSError:
            pass
        stop.wait(2)


def cmd_build(a):
    work = Path(a.work)
    jsonl = Path((work / "DUMP_READY.txt").read_text().strip())
    stem = work / f"rebuilt_shard{a.shard}"
    t0 = time.time()
    p = subprocess.Popen([str(PY), __file__, "build-child", "--jsonl", str(jsonl), "--stem", str(stem),
                          "--threads", str(a.threads)], stdout=subprocess.PIPE, text=True)
    box, stop = [0.0], threading.Event()
    th = threading.Thread(target=_poll_rss, args=(p.pid, box, stop), daemon=True)
    th.start()
    out = p.communicate()[0]
    stop.set()
    wall = time.time() - t0
    child = {}
    for line in out.splitlines():
        if line.startswith("CHILD_JSON "):
            child = json.loads(line[len("CHILD_JSON "):])
    rec = {"shard": a.shard, "jsonl": str(jsonl), "stem": str(stem), "params": SEISMIC_PARAMS,
           "threads": a.threads, "returncode": p.returncode, "wall_seconds": round(wall, 1),
           "peak_rss_gb_ru_maxrss_children": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024 / 1024,
           "peak_rss_gb_vmrss_poll": round(box[0], 3), "child": child, "finished_utc": jnow()}
    stock = Path(f"{stem}.index.seismic")
    rec["stock_bytes"] = stock.stat().st_size if stock.exists() else None
    (work / "build.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))
    if p.returncode != 0:
        sys.exit(p.returncode)


def dir_bytes(d: Path) -> int:
    return sum(f.stat().st_size for f in d.iterdir() if f.is_file())


def cmd_convert(a):
    work = Path(a.work)
    stem = work / f"rebuilt_shard{a.shard}"
    stock = Path(f"{stem}.index.seismic")
    mmap_dir = Path(f"{stem}.mmap")
    dv_dir = Path(f"{stem}.dotvbyte.v2.mmap")
    rec = {"shard": a.shard}
    t0 = time.time()
    p = subprocess.run([str(C1A_BIN), "--index-book", str(stock), "--mmap-dir", str(mmap_dir),
                        "--n-queries", "5"], capture_output=True, text=True)
    rec["c1a"] = {"argv": ["c1a_mmap_index", "--index-book", str(stock), "--mmap-dir", str(mmap_dir), "--n-queries", "5"],
                  "rc": p.returncode, "seconds": round(time.time() - t0, 1), "stderr_tail": p.stderr[-600:],
                  "stdout_tail": p.stdout[-600:]}
    if p.returncode == 0:
        rec["c1a"]["bytes"] = dir_bytes(mmap_dir)
        t0 = time.time()
        p = subprocess.run([str(DOTVBYTE_BIN), "--src-mmap-dir", str(mmap_dir), "--dst-mmap-dir", str(dv_dir),
                            "--value-scale", "perdoc", "--sanity-docs", "500"], capture_output=True, text=True)
        rec["dotvbyte"] = {"argv": ["convert_f16_to_dotvbyte", "--src-mmap-dir", str(mmap_dir), "--dst-mmap-dir",
                                    str(dv_dir), "--value-scale", "perdoc", "--sanity-docs", "500"],
                           "rc": p.returncode, "seconds": round(time.time() - t0, 1),
                           "stderr_tail": p.stderr[-600:], "stdout_tail": p.stdout[-600:]}
        if p.returncode == 0:
            rec["dotvbyte"]["bytes"] = dir_bytes(dv_dir)
    rec["served_dv_v2_bytes"] = dir_bytes(served_dir(a.shard))
    rec["served_dv_v2_bytes_core"] = sum(f.stat().st_size for f in served_dir(a.shard).iterdir()
                                         if f.is_file() and not f.name.startswith("hotset_"))
    rec["twin_f16_bytes"] = dir_bytes(twin_dir(a.shard))
    rec["finished_utc"] = jnow()
    (work / "convert.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))


# ── parity ──────────────────────────────────────────────────────────────────
def cmd_parity(a):
    os.environ.setdefault("SFU_SEISMIC_PREFLOOR", "2")
    sys.path.insert(0, str(REPO / "source"))
    sys.path.insert(0, str(REPO / "scripts/seismic_testbed"))
    from e6_forward_codec_proto import load_queries
    from lib.opensearch_retriever import encode_splade
    import seismic
    work = Path(a.work)
    rebuilt = Path(a.rebuilt) if a.rebuilt else work / f"rebuilt_shard{a.shard}.dotvbyte.v2.mmap"
    served = served_dir(a.shard)
    sets = {"topics120": [r["query"] for r in json.loads((REPO / "data/sfu_eval_queries.json").read_text())],
            "diverse100": load_queries(100, REPO / "data/eval_results/diverse_queries.json")}
    assert len(sets["topics120"]) == 120 and len(sets["diverse100"]) == 100
    enc = {name: [dict(sorted(encode_splade(q, "models/splade_onnx_fp16").items(), key=lambda x: -x[1])[:64])
                  for q in qs] for name, qs in sets.items()}
    sd = seismic.get_seismic_string()

    def run(mmap_dir: Path):
        idx = seismic.MmapSeismicIndex(str(mmap_dir))
        meta = {"forward_format": idx.forward_format, "len": int(idx.len), "nnz": int(idx.nnz)}
        res = {}
        t0 = time.time()
        for name, qs in enc.items():
            out = []
            for terms in qs:
                r = idx.search(query_id="q", query_components=np.array(list(terms.keys()), dtype=sd),
                               query_values=np.array([float(v) for v in terms.values()], dtype=np.float32),
                               k=200, query_cut=len(terms), heap_factor=0.8)
                out.append([(d, float(s)) for (_q, s, d) in r])
            res[name] = out
        meta["search_seconds"] = round(time.time() - t0, 1)
        del idx
        return res, meta

    rb, rb_meta = run(rebuilt)
    sv, sv_meta = run(served)
    rec = {"shard": a.shard, "rebuilt": str(rebuilt), "served": str(served), "bar_mean_overlap10": BAR,
           "rebuilt_meta": rb_meta, "served_meta": sv_meta,
           "search": {"engine": "MmapSeismicIndex", "k_prime": 200, "overlap_k": 10, "query_cut": "len(terms)",
                      "heap_factor": 0.8, "query_terms": 64,
                      "SFU_SEISMIC_PREFLOOR": os.environ.get("SFU_SEISMIC_PREFLOOR")}, "sets": {}}
    passed = True
    for name in enc:
        tops = [([d for d, _ in x[:10]], [d for d, _ in y[:10]]) for x, y in zip(rb[name], sv[name])]
        ov = [len(set(x) & set(y)) / 10 for x, y in tops]
        m = float(np.mean(ov))
        rec["sets"][name] = {"n": len(ov), "overlap10_mean": round(m, 4), "overlap10_min": min(ov),
                             "identical_top10_ordered": sum(1 for x, y in tops if x == y),
                             "identical_top10_set": sum(1 for x, y in tops if set(x) == set(y)),
                             "overlap200_mean": round(float(np.mean([len({d for d, _ in x} & {d for d, _ in y}) / max(1, len(y))
                                                                     for x, y in zip(rb[name], sv[name])])), 4),
                             "pass": m >= BAR}
        passed &= m >= BAR
    rec["verdict"] = "PASS" if passed else "FAIL"
    rec["finished_utc"] = jnow()
    (work / "parity.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))


def cmd_record(a):
    work = Path(a.work)
    out = {"item": "delta-ingest D: twin-shard rebuild proof", "date": "2026-09-29",
           "script": "scripts/experiments/eval_delta_ingest_twin_rebuild.py", "work_dir": str(work),
           "pre_registered_bar": f"mean overlap@10 >= {BAR} on each query set (120 topics, 100 diverse)"}
    for name in ("verify", "dump", "build", "convert", "fwdcheck", "parity", "e5"):
        f = work / f"{name}.json"
        if f.exists():
            out[name] = json.loads(f.read_text())
    if a.note:
        out["notes"] = a.note
    RESULT.write_text(json.dumps(out, indent=1))
    print(RESULT)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("verify", "dump", "build", "convert", "parity", "record", "build-child"):
        s = sub.add_parser(name)
        s.add_argument("--shard", type=int, default=0)
        s.add_argument("--work", default="/var/tmp/sfu_delta_D_20260929")
        s.add_argument("--workers", type=int, default=12)
        s.add_argument("--threads", type=int, default=8)
        s.add_argument("--jsonl")
        s.add_argument("--stem")
        s.add_argument("--rebuilt")
        s.add_argument("--note", action="append")
    a = ap.parse_args()
    {"verify": cmd_verify, "dump": cmd_dump, "build": cmd_build, "convert": cmd_convert,
     "parity": cmd_parity, "record": cmd_record, "build-child": cmd_build_child}[a.cmd](a)


if __name__ == "__main__":
    main()
