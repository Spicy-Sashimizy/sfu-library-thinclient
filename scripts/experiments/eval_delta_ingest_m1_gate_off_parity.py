#!/usr/bin/env python3
"""Delta-ingest M1: gate-off parity (docs/delta_ingest/03_SPIKE_PLAN.md M1).

Pre-registered bar (2026-09-29, verbatim): "fused + final top-10, 120 topics,
`SFU_DELTA_ROOT` unset vs set with an EMPTY delta root -> byte-identical
120/120 (the gate must be a no-op when there is nothing to serve)".

Arms (each its own fresh process, so `DeltaLayer.load_if_enabled` runs in
`_load()` exactly as in the served process):
  * gate_off   : SFU_DELTA_ROOT removed from the child env.
  * empty_root : SFU_DELTA_ROOT=<fresh empty dir under /var/tmp/sfu_delta_A_20260929/>.
    The directory is asserted empty before and after the arm.
  * gate_off_control (optional, third process): a second gate_off process, so
    any cross-process non-determinism shows up as gate_off vs gate_off_control
    and can be separated from a real gate effect.

Per topic and pass the child records
  fused = retriever.search_rrf(q, top_k=50)            (the RRF output, serving flags)
  final = lib.tools._maybe_rerank(deepcopy(fused), q, 10)   (serving rerank pipeline)
serialised with json.dumps(sort_keys=True). "Byte-identical" compares those
serialisations (every field, every score). Fused top-10 and id-only views are
also reported to localise any difference.

Code under test: the driver exports `git archive HEAD src` to
/var/tmp/sfu_delta_A_20260929/code_<commit8>/ (models/, data/, .env symlinked
to the repo) and the children import `lib` from there, so uncommitted edits
other agents make in the shared working tree are NOT what is measured. The
result file records the commit, the snapshot path, per-module sha256 and the
dirty source/ files at run time.

Determinism controls:
  * remote abstracts: the retriever's `_fetch_remote_abstracts` is replaced by
    a stub returning {} (no OpenAlex call), identical in every arm; otherwise
    a network miss/hit would change the CE input text between arms.
  * SFU_SEARCH_SPECULATIVE_RERANK and SFU_SEISMIC_SHARD_MANIFEST removed from
    the child env (serving default); SFU_RESULT_CACHE is irrelevant because
    search_rrf never reads the result cache.
  * every child runs --passes passes; pass>=2 vs pass 1 in the same process is
    the within-process determinism control.

Topics: data/eval_results/dense_ablation_qrels_20260817.json topics[*].natural
(the 120 natural topics used by the serve-path evals, e.g.
scripts/experiments/eval_hydrate_once_ab.py).

Run (each child takes the shared latency lock itself):
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m1_gate_off_parity.py drive \
      --passes 2 --arms gate_off,empty_root
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
DATE = "2026-09-29"
SCRATCH = Path("/var/tmp/sfu_delta_A_20260929")
OUT = REPO / "data/eval_results/delta_ingest_M1_20260929.json"
LOCK = "/tmp/sfu_latency_measure.lock"
TOP_K = 50
LIMIT = 10
ENV_DROP = ("SFU_DELTA_ROOT", "SFU_SEARCH_SPECULATIVE_RERANK", "SFU_SEISMIC_SHARD_MANIFEST")


def dump(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def load_topics(limit: int) -> list[tuple[str, str]]:
    topics = json.loads(TOPICS.read_text())["topics"]
    items = [(k, v["natural"]) for k, v in topics.items()]
    return items[:limit] if limit else items


def dir_listing(p: Path) -> list[str]:
    return sorted(str(x.relative_to(p)) for x in p.rglob("*")) if p.exists() else ["<missing>"]


def child(args) -> int:
    t_start = time.time()
    sys.path.insert(0, args.src)
    import lib.tools as tools
    import lib.thinclient.retriever as rmod
    import lib.thinclient.delta_layer as dmod
    code = {m.__name__: {"file": m.__file__, "sha256": hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}
            for m in (tools, rmod, dmod)}
    feats = dict(tools._get_features())
    retriever = tools._get_thinclient_retriever()
    if retriever is None:
        print("search backend is not thinclient; abort", file=sys.stderr)
        return 2
    retriever._fetch_remote_abstracts = lambda ids: {}
    t0 = time.perf_counter()
    retriever._load()
    load_s = time.perf_counter() - t0
    delta = retriever._delta
    delta_state = None if delta is None else {
        "root": str(delta.root), "stamp": delta.stamp, "generations": len(delta.generations),
        "deleted": len(delta.deleted), "superseded": len(delta.superseded),
        "shard_manifest": delta.shard_manifest_path(), "buffer_size": delta.buffer_size(),
        "section_dirs": [s[0] for s in delta.section_dirs()], "info": delta.info()}
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        det = {"cudnn_deterministic": torch.backends.cudnn.deterministic,
               "cudnn_benchmark": torch.backends.cudnn.benchmark,
               "torch_threads": torch.get_num_threads()}
    except Exception:
        device, det = "unknown", {}
    items = load_topics(args.limit_topics)
    rows_out = Path(args.rows_out)
    meta = {"arm": args.arm, "pid": os.getpid(),
            "env": {k: os.environ.get(k) for k in sorted(os.environ) if k.startswith("SFU_") and
                    not any(s in k for s in ("KEY", "TOKEN", "AUTH", "SECRET", "PASS"))},
            "sfu_delta_root_set": "SFU_DELTA_ROOT" in os.environ,
            "delta_layer": delta_state, "features": feats, "torch_device": device,
            "torch_determinism": det, "load_s": round(load_s, 2),
            "seismic_backend": type(getattr(retriever, "_seismic", None)).__name__,
            "code_under_test": code}
    passes = []
    for p in range(args.passes):
        rows = []
        tp = time.time()
        passes.append({"pass": p + 1, "wall_s": None, "rows": rows})
        for i, (key, q) in enumerate(items):
            t = time.perf_counter()
            fused = retriever.search_rrf(q, top_k=TOP_K)
            t1 = time.perf_counter()
            fused_s = dump(fused)
            final = tools._maybe_rerank(copy.deepcopy(fused), q, LIMIT) if fused else []
            t2 = time.perf_counter()
            rows.append({"topic": key, "query": q, "fused": fused_s,
                         "fused_top10": dump(fused[:LIMIT]), "final": dump(final),
                         "fused_ids": [d.get("openalex_id") for d in fused],
                         "final_ids": [d.get("openalex_id") for d in final],
                         "rrf_ms": round((t1 - t) * 1000, 1), "rerank_ms": round((t2 - t1) * 1000, 1)})
            print(f"[{args.arm} p{p+1} {i+1}/{len(items)}] rrf={rows[-1]['rrf_ms']:.0f}ms "
                  f"rerank={rows[-1]['rerank_ms']:.0f}ms n={len(fused)}", flush=True)
            passes[-1]["wall_s"] = round(time.time() - tp, 1)
            done = p + 1 == args.passes and i + 1 == len(items)
            rows_out.write_text(json.dumps({**meta, "partial": not done,
                                            "wall_s": round(time.time() - t_start, 1),
                                            "passes": passes}) + "\n")
    rec = {**meta, "partial": False, "wall_s": round(time.time() - t_start, 1), "passes": passes}
    rows_out.write_text(json.dumps(rec) + "\n")
    return 0


def rerank_control(args) -> int:
    """Rerank-stage determinism control without loading the index: feed the
    gate_off arm's recorded fused lists back through `_maybe_rerank` twice in a
    fresh process and compare with the recorded final top-10."""
    t_start = time.time()
    sys.path.insert(0, args.src)
    import lib.tools as tools
    rec = json.loads((SCRATCH / "gate_off.json").read_text())
    rows = rec["passes"][0]["rows"]
    reps = []
    for r in range(args.reps):
        finals = []
        for i, row in enumerate(rows):
            fused = json.loads(row["fused"])
            final = tools._maybe_rerank(fused, row["query"], LIMIT) if fused else []
            finals.append(dump(final))
        reps.append(finals)
        print(f"[rerank-control rep {r+1}] done", flush=True)
    out = {"what": "rerank-stage determinism: recorded gate_off fused list -> _maybe_rerank in a fresh "
                   "process (no index loaded), compared with the recorded gate_off final",
           "features": dict(tools._get_features()), "reps": args.reps, "n": len(rows),
           "identical_to_recorded_final_per_rep": [sum(f == row["final"] for f, row in zip(fs, rows))
                                                   for fs in reps],
           "rep1_vs_rep2_identical": (sum(a == b for a, b in zip(reps[0], reps[1]))
                                      if len(reps) > 1 else None),
           "differing_topics_rep1": [row["topic"] for f, row in zip(reps[0], rows) if f != row["final"]],
           "wall_s": round(time.time() - t_start, 1)}
    (SCRATCH / "rerank_control.json").write_text(json.dumps(out) + "\n")
    print(json.dumps(out, indent=1))
    return 0


SIGNATURES = ("Cannot allocate memory", "CrossEncoder unavailable", "Failed to load embedding model",
              "Reranker failed", "Traceback", "delta layer off", "SFU_SEISMIC_SHARD_MANIFEST is set")


def annotate(args) -> int:
    """Scan run logs for failure signatures that would silently change the
    rerank stage (model-load ENOMEM -> CE skipped / fallback order) and attach
    the counts per log to the results file."""
    res = json.loads(Path(args.out).read_text())
    scan = {}
    for spec in args.log:
        label, path = spec.split("=", 1)
        text = Path(path).read_text(errors="replace") if Path(path).exists() else ""
        scan[label] = {"path": path, "exists": bool(text),
                       "signature_counts": {sg: text.count(sg) for sg in SIGNATURES}}
    res["log_scan"] = scan
    g_rows = json.loads((SCRATCH / "gate_off.json").read_text())["passes"][0]["rows"]
    for spec in args.compare:
        label, path = spec.split("=", 1)
        rec = json.loads(Path(path).read_text())
        rows = rec["passes"][0]["rows"]
        res.setdefault("extra_comparisons", {})[label] = {
            "path": path, "partial": rec.get("partial"), "delta_layer": rec.get("delta_layer"),
            "env_SFU_DELTA_ROOT": rec.get("env", {}).get("SFU_DELTA_ROOT"),
            "vs_gate_off": compare(g_rows[:len(rows)], rows)}
    for spec in args.attach:
        label, path = spec.split("=", 1)
        res.setdefault("attached_controls", {})[label] = json.loads(Path(path).read_text())
    if args.note:
        res.setdefault("notes", []).extend(args.note)
    Path(args.out).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(scan, indent=1))
    return 0


def compare(a_rows, b_rows) -> dict:
    out = {"n": min(len(a_rows), len(b_rows)), "n_a": len(a_rows), "n_b": len(b_rows)}
    for field in ("fused", "fused_top10", "final"):
        same = [ra[field] == rb[field] for ra, rb in zip(a_rows, b_rows)]
        out[f"{field}_identical"] = sum(same)
    out["fused_ids_identical"] = sum(ra["fused_ids"] == rb["fused_ids"] for ra, rb in zip(a_rows, b_rows))
    out["final_ids_identical"] = sum(ra["final_ids"] == rb["final_ids"] for ra, rb in zip(a_rows, b_rows))
    diffs = []
    for ra, rb in zip(a_rows, b_rows):
        if ra["fused"] != rb["fused"] or ra["final"] != rb["final"]:
            diffs.append({"topic": ra["topic"], "query": ra["query"],
                          "fused_identical": ra["fused"] == rb["fused"],
                          "final_identical": ra["final"] == rb["final"],
                          "fused_ids_identical": ra["fused_ids"] == rb["fused_ids"],
                          "final_ids_identical": ra["final_ids"] == rb["final_ids"],
                          "a": {"fused_ids": ra["fused_ids"], "final_ids": ra["final_ids"],
                                "fused_sha256": sha(ra["fused"]), "final": json.loads(ra["final"])},
                          "b": {"fused_ids": rb["fused_ids"], "final_ids": rb["final_ids"],
                                "fused_sha256": sha(rb["fused"]), "final": json.loads(rb["final"])},
                          "first_differing_fused_field": first_diff(json.loads(ra["fused"]),
                                                                    json.loads(rb["fused"]))})
    out["differing_topics"] = diffs
    return out


def first_diff(a: list, b: list):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            keys = sorted(set(x) | set(y))
            return {"rank": i + 1, "fields": {k: [x.get(k), y.get(k)] for k in keys if x.get(k) != y.get(k)}}
    if len(a) != len(b):
        return {"length": [len(a), len(b)]}
    return None


def drive(args) -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    empty_root = SCRATCH / "empty_root"
    if empty_root.exists():
        for x in sorted(empty_root.rglob("*"), reverse=True):
            x.rmdir() if x.is_dir() else x.unlink()
        empty_root.rmdir()
    empty_root.mkdir()
    deadline = time.time() + args.max_seconds if args.max_seconds else None
    arms = args.arms.split(",")
    commit = args.commit or git_commit()
    snap = SCRATCH / f"code_{commit[:8]}"
    if not (snap / "source").exists():
        snap.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(f"git -C {REPO} archive {commit} src | tar -x -C {snap}", shell=True)
        for name in ("models", "data", ".env"):
            (snap / name).symlink_to(REPO / name)
    dirty = subprocess.check_output(["git", "-C", str(REPO), "status", "--short", "source"], text=True).splitlines()
    records = {}
    listing = {}
    stopped = {}
    t0 = time.time()
    for arm in arms:
        env = {k: v for k, v in os.environ.items() if k not in ENV_DROP}
        if arm == "empty_root":
            env["SFU_DELTA_ROOT"] = str(empty_root)
            listing["before"] = dir_listing(empty_root)
        rows_out = SCRATCH / f"{arm}.json"
        want = len(load_topics(args.limit_topics))
        if (args.resume and rows_out.exists() and not json.loads(rows_out.read_text()).get("partial")
                and all(len(p["rows"]) == want for p in json.loads(rows_out.read_text())["passes"])
                and len(json.loads(rows_out.read_text())["passes"]) >= args.passes):
            rec = json.loads(rows_out.read_text())
            rec["reused_from_earlier_driver_invocation"] = True
            records[arm] = rec
            continue
        cmd = ["flock", LOCK, sys.executable, str(Path(__file__).resolve()), "child",
               "--arm", arm, "--passes", str(args.passes), "--rows-out", str(rows_out),
               "--limit-topics", str(args.limit_topics), "--src", str(snap / "source")]
        tw = time.time()
        proc = subprocess.Popen(cmd, env=env, cwd=str(REPO))
        try:
            rc = proc.wait(timeout=max(1, deadline - time.time()) if deadline else None)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = "killed_at_deadline"
            stopped[arm] = rc
        if arm == "empty_root":
            listing["after"] = dir_listing(empty_root)
        if not rows_out.exists():
            print(f"arm {arm} produced no rows rc={rc}", file=sys.stderr)
            stopped[arm] = f"no rows (rc={rc}; lock never acquired or load failed)"
            break
        if rc not in (0, "killed_at_deadline"):
            stopped[arm] = f"rc={rc}"
        rec = json.loads(rows_out.read_text())
        rec["wall_incl_lock_wait_s"] = round(time.time() - tw, 1)
        records[arm] = rec
    total_wall = round(time.time() - t0, 1)

    first = lambda arm: records[arm]["passes"][0]["rows"] if arm in records else []
    primary = compare(first("gate_off"), first("empty_root"))
    n = primary["n"]
    complete = n == 120 and not stopped
    all_same = primary["fused_identical"] == n and primary["final_identical"] == n
    verdict = ("PASS" if complete and all_same else "FAIL" if not all_same
               else f"INCOMPLETE ({n}/120 topics compared, {n} identical so far; bar not decided)")
    controls = {}
    for arm, rec in records.items():
        for p in rec["passes"][1:]:
            c = compare(rec["passes"][0]["rows"], p["rows"])
            controls[f"{arm}_pass1_vs_pass{p['pass']}"] = c
    if "gate_off_control" in records:
        controls["gate_off_vs_gate_off_control"] = compare(first("gate_off"), first("gate_off_control"))
    extra_pairs = {}
    if args.passes > 1:
        for p in range(1, args.passes):
            if all(a in records and len(records[a]["passes"]) > p for a in ("gate_off", "empty_root")):
                extra_pairs[f"gate_off_vs_empty_root_pass{p+1}"] = compare(
                    records["gate_off"]["passes"][p]["rows"], records["empty_root"]["passes"][p]["rows"])

    def strip(rec):
        r = {k: v for k, v in rec.items() if k != "passes"}
        r["passes"] = [{"pass": p["pass"], "wall_s": p["wall_s"],
                        "n_rows": len(p["rows"]),
                        "rrf_ms_p50": sorted(x["rrf_ms"] for x in p["rows"])[len(p["rows"]) // 2] if p["rows"] else None,
                        "rerank_ms_p50": sorted(x["rerank_ms"] for x in p["rows"])[len(p["rows"]) // 2] if p["rows"] else None,
                        "fused_sha256_all": sha("".join(x["fused"] for x in p["rows"])),
                        "final_sha256_all": sha("".join(x["final"] for x in p["rows"]))}
                       for p in rec["passes"]]
        return r

    out = {
        "what": "Delta-ingest M1 gate-off parity: SFU_DELTA_ROOT unset vs set to an EMPTY delta root",
        "bar_preregistered": ("03_SPIKE_PLAN.md M1: fused + final top-10, 120 topics, SFU_DELTA_ROOT unset "
                              "vs set with an EMPTY delta root -> byte-identical 120/120"),
        "verdict": verdict,
        "arms_stopped_early": stopped,
        "date": DATE, "git_commit": commit,
        "script": "scripts/experiments/eval_delta_ingest_m1_gate_off_parity.py",
        "topics_file": str(TOPICS.relative_to(REPO)), "query_field": "natural", "n_topics": n,
        "method": {"call": f"ThinClientRetriever.search_rrf(q, top_k={TOP_K})",
                   "final": f"lib.tools._maybe_rerank(deepcopy(fused), q, {LIMIT})",
                   "byte_identity": "json.dumps(docs, sort_keys=True) string equality, every field incl. scores",
                   "remote_abstracts": "retriever._fetch_remote_abstracts stubbed to {} in every arm (0 OpenAlex calls)",
                   "env_removed_in_children": list(ENV_DROP),
                   "passes_per_arm": args.passes, "arms_order": arms,
                   "lock": f"each child under flock {LOCK}"},
        "code_snapshot": {"path": str(snap), "how": f"git archive {commit} src (clean HEAD, not the "
                          "shared working tree); models/, data/, .env symlinked to the repo",
                          "working_tree_src_dirty_at_run_not_measured": dirty},
        "empty_root": {"path": str(empty_root), "listing_before": listing.get("before"),
                       "listing_after": listing.get("after")},
        "primary_gate_off_vs_empty_root_pass1": primary,
        "secondary_pairs": extra_pairs,
        "determinism_controls": controls,
        "rerank_stage_control": (json.loads((SCRATCH / "rerank_control.json").read_text())
                                 if (SCRATCH / "rerank_control.json").exists() else None),
        "arms": {arm: strip(rec) for arm, rec in records.items()},
        "total_wall_s": total_wall,
        "scratch_rows": {arm: str(SCRATCH / f"{arm}.json") for arm in arms},
    }
    Path(args.out).write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": out["verdict"],
                      "primary": {k: v for k, v in primary.items() if k != "differing_topics"},
                      "controls": {k: {kk: vv for kk, vv in v.items() if kk != "differing_topics"}
                                   for k, v in controls.items()},
                      "secondary": {k: {kk: vv for kk, vv in v.items() if kk != "differing_topics"}
                                    for k, v in extra_pairs.items()}}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drive")
    d.add_argument("--passes", type=int, default=2)
    d.add_argument("--arms", default="gate_off,empty_root")
    d.add_argument("--limit-topics", type=int, default=0)
    d.add_argument("--out", default=str(OUT))
    d.add_argument("--resume", action="store_true")
    d.add_argument("--commit", default="")
    d.add_argument("--max-seconds", type=int, default=0)
    c = sub.add_parser("child")
    c.add_argument("--arm", required=True)
    c.add_argument("--passes", type=int, default=2)
    c.add_argument("--rows-out", required=True)
    c.add_argument("--limit-topics", type=int, default=0)
    c.add_argument("--src", default=str(REPO / "source"))
    an = sub.add_parser("annotate")
    an.add_argument("--out", default=str(OUT))
    an.add_argument("--log", action="append", default=[], help="label=path")
    an.add_argument("--note", action="append", default=[])
    an.add_argument("--compare", action="append", default=[], help="label=arm rows json")
    an.add_argument("--attach", action="append", default=[], help="label=json")
    rc = sub.add_parser("rerank-control")
    rc.add_argument("--reps", type=int, default=2)
    rc.add_argument("--src", default=str(SCRATCH / "code_aa0fc405" / "src"))
    args = ap.parse_args()
    return {"drive": drive, "child": child, "rerank-control": rerank_control,
            "annotate": annotate}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
