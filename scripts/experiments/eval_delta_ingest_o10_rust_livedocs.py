#!/usr/bin/env python3
"""Delta-ingest O10: Rust gather-time livedocs skip vs the Python per-shard filter (2026-10-01).

Design + findings: spike/delta_ingest/O10_RUST_LIVEDOCS_FINDINGS.md.
Fork branch `livedocs-skip` of spike/seismic_upstream (patch:
spike/delta_ingest/patches/seismic_livedocs_skip.patch). The side-built .so is
loaded from a side path by a CHILD interpreter (side path first on sys.path);
the installed .so is never touched.

Bars (written 2026-10-01 before the first run):
  P1 no-bitset parity: side branch .so `search` vs installed .so `search` on
     served shard 0 (dv-v2 e5, local staged copy cmp-verified), 120 topics +
     100 diverse (the M9 query file, encoded once 2026-10-01 04:13Z), k=200,
     query_cut=len(terms), heap_factor=0.8: json-serialised (doc, score) lists
     byte-identical 220/220. Also side `search_skip` with an EMPTY dead set ==
     side `search`, 220/220.
  S1 skip correctness, per fixture: 0 dead ids returned by `search_skip`
     (all queries). Reported (not gated): overlap@10 and identical-list counts
     skip vs Python filter (`DeltaLayer.shard_result_filter`, the delivered
     path), both vs an exact-then-filter reference (search k=2000, filter,
     truncate), and whether the Python list is a prefix of the skip list.
     Search shape = the served per-shard call: k'=100 (top_k=50), heap 0.8.
  C1 cost (report only; VALID only from an exclusive-lock run): per query,
     interleaved: plain `search` (branch .so), `search` + Python filter,
     `search_skip`; plus plain `search` on a control .so built from fork main
     2c4d863 with the same toolchain + flags, alternating processes, to show
     the no-livedocs path costs the same.

Fixtures:
  F1 synth = /var/tmp/sfu_delta_C_20260929/synth (the 2026-09-29 livedocs
     run's last bitset: seeded 0.1% random base ordinals + one topic's seeds,
     popcount 150,415).
  F2 bite  = F1 OR the top-3 shard-0 ids of every query's unmasked k'=100
     search (built by `fixture`), so every query loses >= 3 candidates.

Subcommands: fixture | parity | skip | cost | child (internal).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
PY = "/home/vscode/work/venv_local/bin/python3"
WORK = Path(os.environ.get("SFU_O10_WORK", "/home/vscode/work/delta_ingest/rust"))
SHARD = os.environ.get("SFU_O10_SHARD", "/var/tmp/seismic_stage/global_shard0of8.dotvbyte.e5.v2.mmap")
QUERIES = WORK / "queries.json"
SO = {"installed": None, "branch": str(WORK / "so/branch"), "ctl": str(WORK / "so/ctl")}
SYNTH_ROOT = Path("/var/tmp/sfu_delta_C_20260929/synth")
BITE_ROOT = WORK / "fixtures/bite"
KP = 100
HF = 0.8


def jnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_enc() -> dict:
    return json.loads(QUERIES.read_text())["encoded"]


def qarrays(seismic, terms):
    sd = seismic.get_seismic_string()
    return (np.array([t for t, _ in terms], dtype=sd), np.array([v for _, v in terms], dtype=np.float32))


def child_import(so: str):
    if so != "installed":
        sys.path.insert(0, SO[so])
    import seismic
    assert so == "installed" or seismic.__file__.startswith(SO[so]), seismic.__file__
    return seismic


def dead_ids_for_root(root: Path):
    sys.path.insert(0, str(REPO / "source"))
    from lib.thinclient.delta_layer import DeltaLayer
    layer = DeltaLayer(root)
    assert layer.livedocs is not None, root
    bits = np.unpackbits(layer.livedocs.bits, bitorder="little")[:layer.livedocs.nbits]
    ords = np.flatnonzero(bits)
    ids = [f"W{int(w)}" for w in layer._ordinals.wids[ords]]
    return layer, ids


def build_dead_set(idx, ids):
    t0 = time.perf_counter()
    local = idx.doc_indices_for_ids(ids)
    t1 = time.perf_counter()
    ds = idx.dead_set(local)
    t2 = time.perf_counter()
    return ds, {"ids_in": len(ids), "in_shard": int(sum(1 for x in local if x >= 0)),
                "counts_requested_seeded_oob_empty": list(ds.counts()),
                "resolve_s": round(t1 - t0, 3), "dead_set_s": round(t2 - t1, 4)}


def ser(res) -> list:
    return [[d, float(s)] for (_q, s, d) in res]


def child_main(a):
    seismic = child_import(a.so)
    enc = load_enc()
    idx = seismic.MmapSeismicIndex(SHARD)
    info = {"so": a.so, "seismic_file": seismic.__file__, "shard": SHARD, "docs": int(idx.len),
            "forward_format": idx.forward_format, "start_utc": jnow(),
            "has_search_skip": hasattr(idx, "search_skip")}
    flat = [(name, i, terms) for name, qs in enc.items() for i, terms in enumerate(qs)]

    def plain(terms, k):
        c, v = qarrays(seismic, terms)
        return idx.search(query_id="q", query_components=c, query_values=v, k=k,
                          query_cut=len(terms), heap_factor=HF)

    def skip(terms, k, ds):
        c, v = qarrays(seismic, terms)
        return idx.search_skip("q", c, v, k, len(terms), HF, ds)

    if a.task == "parity":
        info["search_k200"] = [ser(plain(t, 200)) for _, _, t in flat]
        if info["has_search_skip"]:
            empty = idx.dead_set([])
            info["skip_empty_k200"] = [ser(skip(t, 200, empty)) for _, _, t in flat]
    elif a.task == "fixture":
        info["top3"] = [[d for (_q, _s, d) in plain(t, KP)[:3]] for _, _, t in flat]
    elif a.task == "skip":
        info["fixtures"] = {}
        for fname, root in (("F1_synth", SYNTH_ROOT), ("F2_bite", BITE_ROOT)):
            layer, ids = dead_ids_for_root(root)
            ds, build = build_dead_set(idx, ids)
            dead = set(ids)
            pyf = layer.shard_result_filter([None])
            rows = []
            for name, i, t in flat:
                un = plain(t, KP)
                py = pyf([un])[0]
                sk = skip(t, KP, ds)
                ref = [r for r in pyf([plain(t, 2000)])[0]][:KP]
                rows.append({"set": name, "i": i, "unmasked": ser(un), "py": ser(py),
                             "skip": ser(sk), "ref": ser(ref),
                             "dead_in_skip": sum(1 for r in sk if r[2] in dead),
                             "dead_in_py": sum(1 for r in py if r[2] in dead),
                             "dead_in_unmasked": sum(1 for r in un if r[2] in dead)})
            info["fixtures"][fname] = {"root": str(root), "popcount": layer.livedocs.popcount,
                                       "build": build, "rows": rows}
            layer.close()
    elif a.task == "cost":
        layer, ids = dead_ids_for_root(SYNTH_ROOT if a.fixture == "F1_synth" else BITE_ROOT)
        ds, build = build_dead_set(idx, ids) if info["has_search_skip"] else (None, None)
        pyf = layer.shard_result_filter([None])
        info["build"] = build
        for _, _, t in flat[:a.warm]:
            plain(t, KP)
        rows = []
        for rep in range(a.reps):
            for name, i, t in flat:
                row = {"rep": rep, "set": name, "i": i, "skip_first": bool(ds is not None and rep % 2 == 1)}
                if row["skip_first"]:
                    s0 = time.perf_counter_ns()
                    skip(t, KP, ds)
                    s1 = time.perf_counter_ns()
                    row["skip_ms"] = (s1 - s0) / 1e6
                t0 = time.perf_counter_ns()
                un = plain(t, KP)
                t1 = time.perf_counter_ns()
                if ds is not None:
                    pyf([un])
                    t2 = time.perf_counter_ns()
                    row["filter_ms"] = (t2 - t1) / 1e6
                    if not row["skip_first"]:
                        skip(t, KP, ds)
                        t3 = time.perf_counter_ns()
                        row["skip_ms"] = (t3 - t2) / 1e6
                row["plain_ms"] = (t1 - t0) / 1e6
                rows.append(row)
        info["rows"] = rows
        layer.close()
    info["ru_maxrss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    info["finished_utc"] = jnow()
    Path(a.out).write_text(json.dumps(info))


def run_child(so: str, task: str, out: Path, extra: list[str] = ()) -> dict:
    env = dict(os.environ, SFU_SEISMIC_STAGE_DIR="", SFU_META_STAGE_DIR="", OMP_NUM_THREADS="1",
               RAYON_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("SFU_DELTA_ROOT", None)
    cmd = ["taskset", "-c", os.environ.get("SFU_O10_CPUS", "8-15"), PY, __file__, "child",
           "--so", so, "--task", task, "--out", str(out), *extra]
    t0 = time.time()
    subprocess.run(cmd, env=env, check=True, cwd=str(REPO))
    d = json.loads(out.read_text())
    d["wall_s"] = round(time.time() - t0, 1)
    return d


def ov10(a, b) -> float:
    return len({x[0] for x in a[:10]} & {x[0] for x in b[:10]}) / max(1, min(10, len(a), len(b)))


def ids(lst) -> list:
    return [x[0] for x in lst]


def provenance() -> dict:
    q = json.loads(QUERIES.read_text())
    def sha(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest() if p and Path(p).exists() else None
    so_files = {k: (str(next(Path(v).glob("seismic/*.so"))) if v else
                    str(REPO / ".venv/lib/python3.11/site-packages/seismic/seismic.cpython-311-x86_64-linux-gnu.so"))
                for k, v in SO.items() if not v or Path(v).exists()}
    fork = REPO / "spike/seismic_upstream"
    head = subprocess.run(["git", "-C", str(fork), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    outer = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return {"queries_file": str(QUERIES), "queries_sha256": q["sha256"], "queries_created_utc": q["created_utc"],
            "shard": SHARD, "so_sha256": {k: sha(v) for k, v in so_files.items()}, "so_files": so_files,
            "fork_head": head, "repo_head": outer, "kprime": KP, "heap_factor": HF}


def cmd_parity(a):
    out = {"item": "O10 P1 no-bitset parity", "date_utc": jnow(), **provenance()}
    inst = run_child("installed", "parity", WORK / "parity_installed.json")
    br = run_child("branch", "parity", WORK / "parity_branch.json")
    n = len(inst["search_k200"])
    same = sum(json.dumps(x) == json.dumps(y) for x, y in zip(inst["search_k200"], br["search_k200"]))
    same_skip = sum(json.dumps(x) == json.dumps(y) for x, y in zip(br["search_k200"], br["skip_empty_k200"]))
    out.update(n=n, branch_vs_installed_identical=same, skip_empty_vs_search_identical=same_skip,
               verdict="PASS" if same == n and same_skip == n else "FAIL",
               walls={"installed": inst["wall_s"], "branch": br["wall_s"]},
               has_search_skip={"installed": inst["has_search_skip"], "branch": br["has_search_skip"]})
    if Path(SO["ctl"]).exists():
        ctl = run_child("ctl", "parity", WORK / "parity_ctl.json")
        out["ctl_vs_installed_identical"] = sum(json.dumps(x) == json.dumps(y)
                                                for x, y in zip(inst["search_k200"], ctl["search_k200"]))
    (WORK / "result_parity.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def cmd_fixture(a):
    sys.path.insert(0, str(REPO / "source"))
    sys.path.insert(0, str(REPO / "spike"))
    from lib.thinclient.livedocs import Livedocs
    from lib.thinclient.ordinals import OrdinalSpace
    from delta_ingest.livedocs import write_livedocs
    d = run_child("branch", "fixture", WORK / "fixture_top3.json")
    top = sorted({x for row in d["top3"] for x in row})
    gj = json.loads((SYNTH_ROOT / "generations.json").read_text())
    ld = gj["livedocs"]
    src = Livedocs(SYNTH_ROOT / ld["path"], expect_space_id=ld["ordinal_space_id"])
    ords = OrdinalSpace(ld["ordinal_dir"], {"ordinal_space_id": ld["ordinal_space_id"]})
    pos, found = ords.lookup(top)
    assert found.all(), "a top-3 id has no base ordinal"
    dense = np.unpackbits(np.array(src.bits), bitorder="little")[:src.nbits].astype(bool)
    dense[pos] = True
    bits = np.packbits(dense, bitorder="little")
    rel = Path("livedocs/base-bite.liv")
    facts = write_livedocs(BITE_ROOT / rel, bits, src.nbits, ords.space_id)
    gj["stamp"] = "o10-bite"
    gj["livedocs"] = {**ld, "path": str(rel), **facts}
    (BITE_ROOT / "generations.json").write_text(json.dumps(gj))
    print(json.dumps({"bite_ids": len(top), "popcount": facts["popcount"], "synth_popcount": src.popcount}))


def cmd_skip(a):
    out = {"item": "O10 S1 skip correctness", "date_utc": jnow(), **provenance()}
    d = run_child("branch", "skip", WORK / "skip_branch.json")
    out["wall_s"] = d["wall_s"]
    for fname, fx in d["fixtures"].items():
        rows = fx["rows"]
        n = len(rows)
        s = {"root": fx["root"], "popcount": fx["popcount"], "build": fx["build"], "n": n,
             "dead_in_skip_total": sum(r["dead_in_skip"] for r in rows),
             "dead_in_py_total": sum(r["dead_in_py"] for r in rows),
             "queries_with_dead_in_unmasked": sum(r["dead_in_unmasked"] > 0 for r in rows),
             "dead_in_unmasked_total": sum(r["dead_in_unmasked"] for r in rows),
             "skip_len_min": min(len(r["skip"]) for r in rows),
             "py_len_min": min(len(r["py"]) for r in rows)}
        for lab, x, y in (("skip_vs_py", "skip", "py"), ("skip_vs_ref", "skip", "ref"), ("py_vs_ref", "py", "ref")):
            o = [ov10(r[x], r[y]) for r in rows]
            s[f"{lab}_overlap10_mean"] = round(float(np.mean(o)), 5)
            s[f"{lab}_overlap10_min"] = round(float(np.min(o)), 3)
            s[f"{lab}_top10_identical"] = sum(ids(r[x])[:10] == ids(r[y])[:10] for r in rows)
            m = [min(len(r[x]), len(r[y])) for r in rows]
            s[f"{lab}_common_prefix_identical"] = sum(ids(r[x])[:k] == ids(r[y])[:k] for r, k in zip(rows, m))
        s["py_is_prefix_of_skip"] = sum(ids(r["skip"])[:len(r["py"])] == ids(r["py"]) for r in rows)
        s["skip_full_identical_to_ref"] = sum(json.dumps(r["skip"]) == json.dumps(r["ref"]) for r in rows)
        s["verdict_S1"] = "PASS" if s["dead_in_skip_total"] == 0 else "FAIL"
        out[fname] = s
    (WORK / "result_skip.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def pct(xs, p):
    return round(float(np.percentile(xs, p)), 3) if xs else None


def cmd_cost(a):
    out = {"item": "O10 C1 cost", "date_utc": jnow(), "lock": a.lock_note, "fixture": a.fixture,
           "reps": a.reps, "rounds": a.rounds, **provenance()}
    runs = []
    for rnd in range(a.rounds):
        for so in (("ctl", "branch") if rnd % 2 == 0 else ("branch", "ctl")):
            if so == "ctl" and not Path(SO["ctl"]).exists():
                continue
            d = run_child(so, "cost", WORK / f"cost_{so}_{rnd}.json",
                          ["--reps", str(a.reps), "--warm", str(a.warm), "--fixture", a.fixture])
            runs.append({"so": so, "round": rnd, "build": d.get("build"), "rows": d["rows"]})
    summ = {}
    for so in ("ctl", "branch"):
        rr = [r for x in runs if x["so"] == so for r in x["rows"]]
        if not rr:
            continue
        s = {"n": len(rr), "plain_p50": pct([r["plain_ms"] for r in rr], 50),
             "plain_p95": pct([r["plain_ms"] for r in rr], 95)}
        if "skip_ms" in rr[0]:
            f = [r["filter_ms"] for r in rr]
            k = [r["skip_ms"] for r in rr]
            pf = [r["plain_ms"] + r["filter_ms"] for r in rr]
            s.update(filter_p50=pct(f, 50), filter_p95=pct(f, 95), plain_plus_filter_p50=pct(pf, 50),
                     plain_plus_filter_p95=pct(pf, 95), skip_p50=pct(k, 50), skip_p95=pct(k, 95),
                     skip_minus_plain_p50=pct([x - r["plain_ms"] for x, r in zip(k, rr)], 50),
                     skip_minus_plainfilter_p50=pct([x - y for x, y in zip(k, pf)], 50))
            for order in (False, True):
                sub = [r for r in rr if r.get("skip_first") == order]
                if sub:
                    s[f"skip_first_{order}"] = {
                        "n": len(sub), "plain_p50": pct([r["plain_ms"] for r in sub], 50),
                        "skip_p50": pct([r["skip_ms"] for r in sub], 50),
                        "skip_minus_plain_p50": pct([r["skip_ms"] - r["plain_ms"] for r in sub], 50)}
        summ[so] = s
    if "ctl" in summ and "branch" in summ:
        summ["branch_over_ctl_plain_p50"] = round(summ["branch"]["plain_p50"] / summ["ctl"]["plain_p50"], 4)
    out["summary"] = summ
    out["builds"] = [x["build"] for x in runs if x["build"]]
    path = WORK / f"result_cost_{a.tag}.json"
    path.write_text(json.dumps({**out, "runs": runs}))
    print(json.dumps(out, indent=1))


RESULT = REPO / "data/eval_results/delta_ingest_O10_rust_livedocs_20261001.json"


def cmd_finalize(a):
    def rd(name):
        p = WORK / name
        return json.loads(p.read_text()) if p.exists() else None
    par = rd("result_parity.json")
    for k in ("search_k200",):
        par.pop(k, None)
    skip = rd("result_skip.json")
    cost = {}
    for tag, note in (("shared_F1", "INVALID/indicative: shared lock, SERVE shared job concurrent; arms in fixed "
                                    "order plain -> filter -> skip (skip ran second on a warm query: order bias)"),
                      ("shared_F2", "INVALID/indicative: as shared_F1"),
                      ("shared_F1b", "INVALID/indicative: shared lock; skip-first/plain-first alternated per rep"),
                      ("shared_F2b", "INVALID/indicative: shared lock; skip-first/plain-first alternated per rep")):
        d = rd(f"result_cost_{tag}.json")
        cost[tag] = ({"status": note, "date_utc": d["date_utc"], "fixture": d["fixture"], "reps": d["reps"],
                      "rounds": d["rounds"], "summary": d["summary"], "dead_set_builds": d.get("builds")}
                     if d else {"status": "NOT RUN"})
    out = {"item": "delta-ingest O10 Rust gather-time livedocs skip", "date": "2026-10-01",
           "script": "scripts/experiments/eval_delta_ingest_o10_rust_livedocs.py",
           "findings": "spike/delta_ingest/O10_RUST_LIVEDOCS_FINDINGS.md",
           "patch": "spike/delta_ingest/patches/seismic_livedocs_skip.patch",
           "fork_branch": "livedocs-skip", "fork_commit": "620f1d2", "fork_base": "main 2c4d863",
           "build": "maturin build --release, RUSTFLAGS=-C target-cpu=x86-64-v3, side path "
                    "/home/vscode/work/delta_ingest/rust/so/{branch,ctl}; ctl = fork main 2c4d863, same toolchain/flags",
           "P1_no_bitset_parity": par, "S1_skip_correctness": skip,
           "disassembly_ctl_vs_branch": rd("disasm_cmp.json"),
           "C1_cost": cost,
           "efficacy": "IMPLEMENTED, EFFICACY UNMEASURED (no exclusive-lock timing; all cost numbers INVALID/indicative)",
           "finalized_utc": jnow()}
    RESULT.write_text(json.dumps(out, indent=1))
    print(f"wrote {RESULT}")
    for tag, c in cost.items():
        print(tag, json.dumps(c.get("summary", c.get("status"))))


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("child")
    c.add_argument("--so", required=True)
    c.add_argument("--task", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--reps", type=int, default=1)
    c.add_argument("--warm", type=int, default=20)
    c.add_argument("--fixture", default="F1_synth")
    sp.add_parser("parity")
    sp.add_parser("fixture")
    sp.add_parser("skip")
    sp.add_parser("finalize")
    k = sp.add_parser("cost")
    k.add_argument("--reps", type=int, default=2)
    k.add_argument("--warm", type=int, default=40)
    k.add_argument("--rounds", type=int, default=2)
    k.add_argument("--fixture", default="F1_synth")
    k.add_argument("--tag", default="shared")
    k.add_argument("--lock-note", default="SHARED lock: timings INVALID by declaration")
    a = p.parse_args()
    {"child": child_main, "parity": cmd_parity, "fixture": cmd_fixture, "skip": cmd_skip,
     "cost": cmd_cost, "finalize": cmd_finalize}[a.cmd](a)


if __name__ == "__main__":
    main()
