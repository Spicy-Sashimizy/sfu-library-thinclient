#!/usr/bin/env python3
# CLOSED MEASURED 2026-09-30 — in-place bit-update spike harness (docs/archive/inplace_update/); evidence kept, pre-registered bars live in source
"""In-place v3.1 decoder: forward TAIL APPEND read path (+tail) test.

Task (coordinator, 2026-09-30): format v3.1 (FORMAT_V3.md §3.R4 as built in
revision 6) reserves a sparse tail region of `forward_data.bin`,
`forward_offsets.bin` and `row_id_override.bin` so that a record which fits
no hole can be appended; the decoder resolves a winner whose START lies in
the tail by binary search over the published tail rows and takes its
external id from the override array. Two identity tests, no bar:

  synthetic  (160,347-doc dv-v2 SEISMIC generation built by spike/delta_ingest
             for M4; read-only source
             /home/vscode/work/inplace_update/m4/root_n1/g0001/seismic/delta_g0001.dotvbyte.v2.mmap)
    1. prepare:  copy the source (cp --sparse=always) and convert it to v3.1
                 with the encoder defaults (tail reserve 10 % words / rows,
                 rounded up to 512); the copied prefix of the extended files
                 must be byte-identical to the source.
    2. v2ref:    side .so, v2 decoder on the unconverted copy, 460 queries
                 (QA+QT+QD of the Stage-0 query file, token ids mapped to
                 strings through shard 0's token map), E8 recall-max params.
    3. baseline: v3.1 decoder on the v3.1 copy at epoch 0 (zero patches,
                 empty tail) — must equal v2ref on 460/460 (zero-patch
                 parity of the v3.1 layout). Chooses the N = 64 base docs
                 that occur most often in the baseline top-200 lists.
    4. fixture (Rust `inplace_v3_tail_fixture`): appends a copy of each
                 chosen doc's record to the tail with a fresh id, repoints
                 every posting word of that doc at the tail copy (TAG = 1),
                 publishes epoch 1 (header slot 1: tail words used, tail rows
                 = N); writes a dv-v2 ORACLE dir carrying the same content
                 natively (tail records appended, N real offsets, slab
                 extended, same posting words with TAG cleared).
    5. check:    v3.1 decoder on the fixture (E = 1) vs the v2 decoder on the
                 oracle, same side build: ordered top-200 (doc id, f32 score
                 bits) identical on 460/460 = PASS. Non-vacuity: queries with
                 >= 1 fresh (tail) id in their top-200 and queries whose
                 result changed vs the epoch-0 baseline; both must be > 0.
                 readers.bin must be free after the queries.

  shard0     zero-patch parity of the v3.1 conversion of the real shard-0
             input (/home/vscode/work/inplace_update/stage1/v2copy, read-only)
             vs A0 = the served .so on that same copy (B1's definition):
             460/460 identical = PASS. The v3.1 copy is written to
             /home/vscode/work/inplace_update/stage3/encoder/v3_1 with its
             encode report beside it (encode_report_v3_1.json) for the
             updater agent's integration.

Every per-query time recorded here is indicative only (host shared with the
latency-lock queue on cores 0-7; this harness runs on cores 8-15 and never
takes /tmp/sfu_latency_measure.lock). Results:
data/eval_results/inplace_tail_read_<UTCDATE>.json (keys "synthetic",
"shard0"; merged if the file exists).
"""
from __future__ import annotations

import argparse
import collections
import filecmp
import hashlib
import json
import os
import shutil
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
S3 = Path("/home/vscode/work/inplace_update/stage3/encoder")
SYN = S3 / "synth"
SRC = Path("/home/vscode/work/inplace_update/m4/root_n1/g0001/seismic/delta_g0001.dotvbyte.v2.mmap")
SO = S3 / "so_tail"
V2COPY = Path("/home/vscode/work/inplace_update/stage1/v2copy")
V31 = S3 / "v3_1"
SERVED_PKG = REPO / ".venv/lib/python3.11/site-packages/seismic"
QUERIES = Path("/home/vscode/work/inplace_update/stage0/queries.json")
K = 200
HF = 0.8
N_TAIL_DOCS = 64
SETS = ["QA", "QT", "QD"]
FWD = ["forward_data.bin", "forward_offsets.bin"]
COPIED = ["config.json", "forward_data.bin", "forward_offsets.bin", "forward_encoder.bin",
          "posting_lists.bin", "token_to_id_map.bin", "document_mapping_strings.bin",
          "document_mapping_offsets.bin"]
TIMING_NOTE = "host shared, not a measurement (cores 8-15, latency lock not taken)"


sys.path.insert(0, str(REPO))
from spike.inplace_update.guard import check_live_unchanged, clean_env  # noqa: E402


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def imp(so_dir: Path | None):
    if so_dir:
        sys.path.insert(0, str(so_dir))
    import numpy  # noqa: F401
    import seismic
    f = Path(seismic.__file__).resolve()
    want = (so_dir / "seismic").resolve() if so_dir else SERVED_PKG.resolve()
    assert f.parent == want, f"loaded {f}, expected {want}"
    if so_dir:
        assert hasattr(seismic, "inplace_v3_tail_fixture"), "side .so lacks the tail path"
    so = next(f.parent.glob("seismic*.so"))
    return seismic, str(so), hashlib.sha256(so.read_bytes()).hexdigest()


def queries():
    import numpy as np
    from spike.inplace_update.shard import load_token_to_id
    inv = {v: k for k, v in load_token_to_id(V2COPY).items()}
    Q = json.loads(QUERIES.read_text())
    out = [(f"{s}:{i}", [inv[t] for t in q["terms"]], np.array(q["w"], dtype=np.float32))
           for s in SETS for i, q in enumerate(Q[s])]
    assert len(out) == 460, len(out)
    return out


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


def compare(ref, got):
    n_ok, first = 0, None
    for qid in ref:
        a, b = ref[qid], got.get(qid)
        if a == b:
            n_ok += 1
            continue
        if first is None:
            first = {"query": qid, "len_ref": len(a), "len_got": None if b is None else len(b)}
            if b is not None:
                for r, (x, y) in enumerate(zip(a, b)):
                    if x != y:
                        first.update({"rank": r, "field": "doc_id" if x[0] != y[0] else "score_bits",
                                      "ref": x, "got": y})
                        break
    return n_ok, first


def per_set(ref, got):
    return {s: {"n": sum(1 for q in ref if q.startswith(s + ":")),
                "identical": sum(1 for q in ref if q.startswith(s + ":") and ref[q] == got.get(q))}
            for s in SETS}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q / 100 * (len(xs) - 1))))]


def prefix_identical(src: Path, dst: Path, n: int) -> bool:
    with open(src, "rb") as a, open(dst, "rb") as b:
        left = n
        while left:
            k = min(left, 8 << 20)
            x, y = a.read(k), b.read(k)
            if x != y or len(x) != k:
                return False
            left -= k
    return True


def worker(a):
    clean_env()
    os.environ.pop("SFU_SEISMIC_M8_BATCH", None)
    seismic, so, so_sha = imp(None if a.so == "served" else SO)
    qs = queries()
    res = {"step": a.step, "so": so, "so_sha256": so_sha, "pid": os.getpid()}
    if a.step == "prepare":
        if SYN.exists():
            shutil.rmtree(SYN)
        SYN.mkdir(parents=True)
        subprocess.run(["cp", "-r", "--sparse=always", str(SRC), str(SYN / "v2")], check=True)
        t = time.time()
        rep = json.loads(seismic.inplace_v3_convert(str(SYN / "v2"), str(SYN / "v3")))
        res["encoder_report"] = rep
        res["encode_wall_s"] = time.time() - t
        ft = rep["forward_tail"]
        res["prefix_identical"] = {f: prefix_identical(SYN / "v2" / f, SYN / "v3" / f, (SYN / "v2" / f).stat().st_size)
                                   for f in FWD}
        res["other_files_identical"] = {f: filecmp.cmp(SYN / "v2" / f, SYN / "v3" / f, shallow=False)
                                        for f in COPIED if f not in FWD}
        res["sizes"] = {f: {"v2": (SYN / "v2" / f).stat().st_size, "v3": (SYN / "v3" / f).stat().st_size,
                            "v3_allocated": (SYN / "v3" / f).stat().st_blocks * 512} for f in FWD}
        res["sizes"]["row_id_override.bin"] = {"v3": (SYN / "v3" / "row_id_override.bin").stat().st_size,
                                               "v3_allocated": (SYN / "v3" / "row_id_override.bin").stat().st_blocks * 512}
        assert res["sizes"]["forward_data.bin"]["v3"] == 8 * (ft["base_words"] + ft["reserve_words"])
        assert res["sizes"]["forward_offsets.bin"]["v3"] == 8 * (rep["n_docs"] + 1 + ft["reserve_rows"])
    elif a.step == "v2ref":
        idx = seismic.MmapSeismicIndex(str(SYN / "v2"))
        assert idx.forward_format == "dotvbyte_fixedu8_v2"
        res["results"], res["times_ns"] = run(seismic, idx, qs)
    elif a.step == "baseline":
        idx = seismic.MmapSeismicIndex(str(SYN / "v3"))
        assert idx.forward_format == "dotvbyte_fixedu8_v2_inplace_v3"
        info = idx.inplace_header_info()
        tail = idx.inplace_tail_info()
        assert idx.inplace_epoch == 0 and info[2] == 0 and info[3] == 0, info
        assert tail[3] == 0 and tail[4] == 0 and tail[1] > 0 and tail[2] > 0, tail
        res["header_info"] = info
        res["tail_info"] = tail
        res["n_docs_reported"] = idx.len
        res["results"], res["times_ns"] = run(seismic, idx, qs)
        cnt = collections.Counter(d for r in res["results"].values() for d, _ in r)
        res["chosen_docs"] = [d for d, _ in cnt.most_common(N_TAIL_DOCS)]
        res["chosen_docs_top200_occurrences"] = [c for _, c in cnt.most_common(N_TAIL_DOCS)]
    elif a.step == "fixture":
        b = json.loads(Path(a.base).read_text())
        t = time.time()
        res["fixture"] = json.loads(seismic.inplace_v3_tail_fixture(str(SYN / "v3"), b["chosen_docs"], str(SYN / "oracle")))
        res["fixture_wall_s"] = time.time() - t
    elif a.step == "check":
        b = json.loads(Path(a.base).read_text())
        fx = json.loads(Path(a.fixture).read_text())["fixture"]
        v3 = seismic.MmapSeismicIndex(str(SYN / "v3"))
        orc = seismic.MmapSeismicIndex(str(SYN / "oracle"))
        assert orc.forward_format == "dotvbyte_fixedu8_v2"
        info = v3.inplace_header_info()
        tail = v3.inplace_tail_info()
        res["header_info"] = info
        res["tail_info"] = tail
        assert v3.inplace_epoch == 1 and info[0] == 0 and info[1] == 1 and info[3] == 0, info
        assert tail[3] == fx["tail_words_used"] and tail[4] == fx["tail_rows_published"], (tail, fx)
        res["n_docs_reported"] = {"v3": v3.len, "oracle": orc.len}
        assert orc.len == v3.len + fx["n_docs_appended"]
        r3, t3 = run(seismic, v3, qs)
        ro, to = run(seismic, orc, qs)
        fresh = set(fx["fresh_ids"])
        old = set(b["chosen_docs"])
        n_ok, first = compare(ro, r3)
        with_tail = sum(1 for q in r3 if any(d in fresh for d, _ in r3[q]))
        tail_hits = sum(1 for q in r3 for d, _ in r3[q] if d in fresh)
        old_still = sum(1 for q in r3 for d, _ in r3[q] if d in old)
        changed = sum(1 for q in r3 if b["results"][q] != r3[q])
        rb = (SYN / "v3" / "readers.bin").read_bytes()
        busy = [i for i in range(256) if struct.unpack_from("<Q", rb, 64 * i)[0] != 0]
        res["parity_v31_tail_vs_oracle"] = {"identical": n_ok, "of": len(ro), "per_set": per_set(ro, r3),
                                            "first_difference": first}
        res["non_vacuity"] = {"queries_with_tail_doc_in_top200": with_tail,
                              "tail_doc_hits_total": tail_hits,
                              "old_ids_of_moved_docs_still_returned": old_still,
                              "queries_changed_vs_epoch0_baseline": changed}
        res["readers_busy_after_queries"] = busy
        res["registration_state"] = v3.reader_registration_state()
        res["verdict"] = ("PASS" if n_ok == len(ro) and with_tail > 0 and changed > 0
                          and old_still == 0 and not busy else "FAIL")
        res["indicative_ms_p50"] = {"v31_tail": pct(t3, 50) / 1e6, "v2_oracle": pct(to, 50) / 1e6,
                                    "note": TIMING_NOTE}
    elif a.step == "encode_shard0":
        assert not V31.exists(), f"{V31} exists"
        t = time.time()
        rep = json.loads(seismic.inplace_v3_convert(str(V2COPY), str(V31)))
        (S3 / "encode_report_v3_1.json").write_text(json.dumps(rep, indent=2))
        res["encoder_report"] = rep
        res["encode_wall_s"] = time.time() - t
    elif a.step in ("A0", "V31"):
        d = V31 if a.step == "V31" else V2COPY
        idx = seismic.MmapSeismicIndex(str(d))
        res["forward_format"] = idx.forward_format
        res["n_docs"] = idx.len
        if a.step == "V31":
            info = idx.inplace_header_info()
            tail = idx.inplace_tail_info()
            assert idx.inplace_epoch == 0 and info[2] == 0 and info[3] == 0, info
            assert tail[3] == 0 and tail[4] == 0, tail
            res["header_info"] = info
            res["tail_info"] = tail
        idx.touch_slab()
        res["results"], res["times_ns"] = run(seismic, idx, qs)
    Path(a.out).write_text(json.dumps(res))


def sub(step, out, so="side", base=None, fixture=None, timeout=7200):
    env = clean_env(dict(os.environ))
    env.pop("SFU_SEISMIC_M8_BATCH", None)
    cmd = [sys.executable, __file__, "worker", "--step", step, "--out", str(out), "--so", so]
    if base:
        cmd += ["--base", str(base)]
    if fixture:
        cmd += ["--fixture", str(fixture)]
    log("start", step)
    t = time.time()
    subprocess.run(cmd, env=env, check=True, timeout=timeout)
    log("done", step, round(time.time() - t, 1), "s")
    return json.loads(Path(out).read_text())


def synthetic(tmp):
    t0 = time.time()
    prep = sub("prepare", tmp / "prepare.json")
    assert all(prep["prefix_identical"].values()) and all(prep["other_files_identical"].values()), prep
    v2ref = sub("v2ref", tmp / "v2ref.json")
    base = sub("baseline", tmp / "baseline.json")
    n_zp, first_zp = compare(v2ref["results"], base["results"])
    fix = sub("fixture", tmp / "fixture.json", base=tmp / "baseline.json")
    chk = sub("check", tmp / "check.json", base=tmp / "baseline.json", fixture=tmp / "fixture.json")
    zero_patch = {"identical": n_zp, "of": 460, "per_set": per_set(v2ref["results"], base["results"]),
                  "first_difference": first_zp}
    verdict = "PASS" if chk["verdict"] == "PASS" and n_zp == 460 else "FAIL"
    return {
        "what": "v3.1 forward tail read path (decoder) on the synthetic shard: zero-patch parity of the v3.1 "
                "layout + tail fixture vs native oracle; identity test, not a pre-registered bar",
        "synthetic_source": str(SRC),
        "dirs": {"v2": str(SYN / "v2"), "v3_1": str(SYN / "v3"), "oracle": str(SYN / "oracle")},
        "build": {"so": prep["so"], "sha256": prep["so_sha256"], "rustflags": "-C target-cpu=x86-64-v3",
                  "patch": "spike/seismic_upstream_inplace_v3_tail.patch"},
        "encoder": prep["encoder_report"],
        "encode_wall_s": {"value": prep["encode_wall_s"], "note": TIMING_NOTE},
        "copied_prefix_identical": prep["prefix_identical"],
        "other_files_identical": prep["other_files_identical"],
        "sizes": prep["sizes"],
        "baseline_epoch0": {"header_info(slot0,slot1,nonzero_infl,non_native_lists)": base["header_info"],
                            "tail_info(base_words,reserve_words,reserve_rows,used,rows)": base["tail_info"],
                            "n_docs_reported": base["n_docs_reported"]},
        "zero_patch_parity_v31_vs_v2": zero_patch,
        "chosen_docs": {"n": len(base["chosen_docs"]), "ids": base["chosen_docs"],
                        "top200_occurrences": base["chosen_docs_top200_occurrences"]},
        "fixture": fix["fixture"],
        "fixture_wall_s": {"value": fix["fixture_wall_s"], "note": TIMING_NOTE},
        **{k: v for k, v in chk.items() if k not in ("step", "so", "so_sha256", "pid")},
        "params": {"k": K, "heap_factor": HF, "query_cut": "len(terms)", "sorted": True, "m8_batch": "unset"},
        "verdict": verdict,
        "wall_s": round(time.time() - t0, 1),
    }


def shard0(tmp):
    t0 = time.time()
    assert (V2COPY / ".copy_ok").exists(), "V2COPY missing"
    src_man = (REPO / "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap/manifest.json").read_bytes()
    assert (V2COPY / "manifest.json").read_bytes() == src_man
    if (V31 / "inplace_header.bin").exists():
        enc = {"encoder_report": json.loads((S3 / "encode_report_v3_1.json").read_text()), "reused": True}
    else:
        assert not V31.exists(), f"{V31} exists without a header (partial encode): remove it by hand"
        enc = sub("encode_shard0", tmp / "encode_shard0.json", timeout=7200)
    prefix = {f: prefix_identical(V2COPY / f, V31 / f, (V2COPY / f).stat().st_size) for f in FWD}
    others = {f: filecmp.cmp(V2COPY / f, V31 / f, shallow=False) for f in COPIED if f not in FWD}
    sizes = {f: {"v2": (V2COPY / f).stat().st_size, "v3_1": (V31 / f).stat().st_size,
                 "v3_1_allocated": (V31 / f).stat().st_blocks * 512} for f in FWD}
    sizes["row_id_override.bin"] = {"v3_1": (V31 / "row_id_override.bin").stat().st_size,
                                    "v3_1_allocated": (V31 / "row_id_override.bin").stat().st_blocks * 512}
    a0 = sub("A0", tmp / "a0.json", so="served")
    v31 = sub("V31", tmp / "v31.json")
    n_ok, first = compare(a0["results"], v31["results"])
    return {
        "what": "zero-patch parity of the v3.1 conversion of shard 0 vs A0 (served .so on the same v2 copy), "
                "B1's definition; identity test",
        "dirs": {"v2copy": str(V2COPY), "v3_1": str(V31), "encode_report": str(S3 / "encode_report_v3_1.json"),
                 "source": "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap"},
        "builds": {"served": {"so": a0["so"], "sha256": a0["so_sha256"]},
                   "side_v3_1": {"so": v31["so"], "sha256": v31["so_sha256"],
                                 "patch": "spike/seismic_upstream_inplace_v3_tail.patch",
                                 "rustflags": "-C target-cpu=x86-64-v3"}},
        "encoder": enc["encoder_report"],
        "encode_reused": enc.get("reused", False),
        "encode_wall_s": {"value": enc.get("encode_wall_s"), "note": TIMING_NOTE},
        "copied_prefix_identical": prefix,
        "other_files_identical": others,
        "sizes": sizes,
        "v3_1_state": {"forward_format": v31["forward_format"], "n_docs": v31["n_docs"],
                       "header_info(slot0,slot1,nonzero_infl,non_native_lists)": v31["header_info"],
                       "tail_info(base_words,reserve_words,reserve_rows,used,rows)": v31["tail_info"]},
        "parity_v31_vs_A0": {"identical": n_ok, "of": 460, "per_set": per_set(a0["results"], v31["results"]),
                             "first_difference": first},
        "indicative_ms_p50": {"A0": pct(a0["times_ns"], 50) / 1e6, "V31": pct(v31["times_ns"], 50) / 1e6,
                              "note": TIMING_NOTE},
        "params": {"k": K, "heap_factor": HF, "query_cut": "len(terms)", "sorted": True, "m8_batch": "unset"},
        "verdict": "PASS" if n_ok == 460 and all(prefix.values()) and all(others.values()) else "FAIL",
        "wall_s": round(time.time() - t0, 1),
        "v3_1_sentinel": json.loads((V31 / ".inplace_work_copy").read_text()),
    }


def driver(a):
    clean_env()
    guard_start = check_live_unchanged("tail-start")
    tmp = S3 / "tail_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    assert (SO / "seismic").is_dir(), "side .so missing"
    utc = time.strftime("%Y%m%d", time.gmtime())
    out_path = Path(a.out or REPO / f"data/eval_results/inplace_tail_read_{utc}.json")
    doc = json.loads(out_path.read_text()) if out_path.exists() else {}
    stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    if a.part in ("synthetic", "all"):
        doc["synthetic"] = {"measured_utc": stamp, **synthetic(tmp)}
        log("synthetic verdict", doc["synthetic"]["verdict"])
    if a.part in ("shard0", "all"):
        doc["shard0"] = {"measured_utc": stamp, **shard0(tmp)}
        log("shard0 verdict", doc["shard0"]["verdict"])
    doc["live_index_guard"] = [guard_start, check_live_unchanged("tail-end")]
    doc["timing_note"] = TIMING_NOTE
    out_path.write_text(json.dumps(doc, indent=2))
    log("wrote", out_path)
    print(json.dumps({k: doc[k]["verdict"] for k in ("synthetic", "shard0") if k in doc}))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    w = sp.add_parser("worker")
    w.add_argument("--step", required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--so", default="side")
    w.add_argument("--base", default=None)
    w.add_argument("--fixture", default=None)
    r = sp.add_parser("run")
    r.add_argument("--part", choices=["synthetic", "shard0", "all"], default="all")
    r.add_argument("--out", default=None)
    a = ap.parse_args()
    worker(a) if a.cmd == "worker" else driver(a)


if __name__ == "__main__":
    main()
