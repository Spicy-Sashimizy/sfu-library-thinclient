#!/usr/bin/env python3
"""O17 option (a) efficacy: base is_oa bitmap (SFU_OA_BITMAP) gate OFF vs ON.

Arms (each a child process under `flock -s` on the latency lock -> timings
INVALID by declaration):
  pre    src = HEAD snapshot with the O17 serving commit reverse-applied
         (retriever/result_cache/oa_overlay as before the gate existed),
         SFU_OA_BITMAP absent.
  offon  src = HEAD snapshot. Pass "off": SFU_OA_BITMAP absent at _load
         (retriever._oa is None). Pass "on" (only with --bitmap): the overlay
         is attached with the same `oa_overlay.load_if_enabled` that `_load`
         calls, with SFU_OA_BITMAP set to the bitmap dir.

Per topic (120 topics of data/eval_results/dense_ablation_qrels_20260817.json,
natural-language form) and per pass:
  fused      search_rrf(q, top_k=50)                     (unfiltered)
  final      tools._maybe_rerank(fused, q, 10)
  fused_oa   search_rrf_detailed(q, top_k=50, filters={"open_access.is_oa": "true"})
             ["results"] minus the `rrf_legs` key (== search_rrf with the same
             filters, by the search_rrf_detailed contract); one retrieval pass
  final_oa   tools._maybe_rerank(fused_oa, q, 10)
  legs_oa    the same call's ["legs"] lengths

Metrics (summarize):
  M-id   pre vs off: fused/final/fused_oa/final_oa byte-identical per topic
         (bar 120/120, the M1 property for the new gate).
  M-oa   OA-filtered result counts off vs on (fused, final, per leg).
  M-neu  on vs off unfiltered: fused ids+scores identical (the overlay must
         not move the RRF ranking); count of is_oa field changes; final
         top-10 changes (rerank reads is_oa via has_fulltext).
  M-q    nDCG@10 of final (pool qrels, unjudged = gain 0) off vs on,
         unfiltered and OA-filtered.
  M-prec sample of OA-filtered returned ids + known-not-OA ids checked
         against the OpenAlex API (open_access.is_oa now; snapshot 2026-09-23).

Run:
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_o17_oa_bitmap.py drive \
      --arms pre,offon --deadline ...          (identity run, no bitmap)
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_o17_oa_bitmap.py drive \
      --arms off,on --bitmap DIR --scratch S2 --deadline ...
      ("on" loads with SFU_OA_BITMAP set, i.e. through ThinClientRetriever._load)
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_o17_oa_bitmap.py summarize [--api-check 200]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import math
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
SCRATCH = Path("/home/vscode/work/delta_ingest/oa/eval")
OUT = REPO / "data/eval_results/delta_ingest_O17_oa_bitmap_20261001.json"
LOCK = "/tmp/sfu_latency_measure.lock"
O17_SERVING_COMMIT = "ef206dde"
O17_FILES = ("src/lib/thinclient/retriever.py", "src/lib/result_cache.py",
             "src/lib/thinclient/oa_overlay.py")
PY = "/home/vscode/work/venv_local/bin/python3"
MODEL_ENV = {"SFU_SPLADE_MODEL_PATH": "/home/vscode/work/models_local/splade_onnx_fused",
             "SFU_CE_MODEL_PATH": "/home/vscode/work/models_local/sfu-cross-encoder-v1",
             "SFU_EMBEDDING_MODEL_PATH": "/home/vscode/work/delta_ingest/m1/models/sfu-academic-embed-v5"}
ENV_DROP = ("SFU_DELTA_ROOT", "SFU_SEARCH_SPECULATIVE_RERANK", "SFU_SEISMIC_SHARD_MANIFEST",
            "SFU_OA_BITMAP", "SFU_THINCLIENT_ORDINALS")
ENV_BLANK = ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR")
TOP_K, LIMIT = 50, 10
OA_FILTER = {"open_access.is_oa": "true"}
SIGNATURES = ("Cannot allocate memory", "Errno 12", "CrossEncoder unavailable",
              "Failed to load embedding model", "Reranker failed", "Traceback",
              "falling back to BM25F", "SPLADE leg failed", "SPLADE encoder failed",
              "thinclient index unavailable")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(o) -> str:
    return json.dumps(o, sort_keys=True, default=str)


def topics() -> list[tuple[str, str]]:
    t = json.loads(TOPICS.read_text())["topics"]
    return [(k, v["natural"]) for k, v in t.items()]


class _Warn(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, r):
        try:
            self.records.append(f"{r.name}: {r.getMessage()}"[:300])
        except Exception:
            pass


def child(args) -> int:
    scratch = Path(args.scratch)
    rows_path = scratch / f"{args.arm}.rows.jsonl"
    meta_path = scratch / f"{args.arm}.meta.json"
    rows_path.write_text("")
    cap = _Warn()
    root_log = logging.getLogger()
    root_log.addHandler(cap)
    root_log.setLevel(logging.WARNING)
    sys.path.insert(0, args.src)
    deadline = (datetime.strptime(args.deadline, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp() if args.deadline else None)
    meta: dict = {"arm": args.arm, "start_utc": utc(), "src": args.src, "timings_valid": False,
                  "problems": []}
    import lib.tools as tools
    import lib.thinclient.retriever as rmod
    from lib.reranker import _get_cross_encoder
    meta["code"] = {m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                    for m in (tools, rmod)}
    if not rmod.__file__.startswith(args.src):
        meta["problems"].append("retriever not imported from snapshot")
    if args.arm == "on":
        os.environ["SFU_OA_BITMAP"] = args.bitmap
    r = tools._get_thinclient_retriever()
    r._fetch_remote_abstracts = lambda ids: {}
    t0 = time.perf_counter()
    r._load()
    meta["load_s"] = round(time.perf_counter() - t0, 2)
    if args.arm == "on":
        if getattr(r, "_oa", None) is None:
            meta["problems"].append("overlay not loaded in the gate-on arm")
        else:
            meta["bitmap_id"] = r._oa.bitmap_id
            meta["bitmap_coverage"] = r._oa.stamp.get("coverage")
    elif getattr(r, "_oa", None) is not None:
        meta["problems"].append("overlay loaded in a gate-off load")
    if _get_cross_encoder() is None:
        meta["problems"].append("cross-encoder not loaded")
    try:
        meta["backend"] = type(r._seismic_backend()).__name__
    except Exception as exc:
        meta["problems"].append(f"seismic backend: {exc!r}")
    if any(any(s in w for s in SIGNATURES) for w in cap.records):
        meta["problems"].append("failure signature at load")
    meta["warnings_at_load"] = cap.records[:20]
    passes = (["off"] + (["on"] if args.bitmap else [])) if args.arm == "offon" else [args.arm]
    meta_path.write_text(json.dumps(meta, indent=1))
    if meta["problems"]:
        print("HEALTH FAIL", meta["problems"], flush=True)
        return 3
    items = topics()[: args.limit_topics or None]
    stopped = None
    with rows_path.open("a") as fh:
        for pname in passes:
            if pname == "on":
                os.environ["SFU_OA_BITMAP"] = args.bitmap
                from lib.thinclient.oa_overlay import load_if_enabled
                t = time.perf_counter()
                r._oa = load_if_enabled(r.root, r._manifest())
                meta["overlay_attach_s"] = round(time.perf_counter() - t, 3)
                meta["bitmap_id"] = r._oa.bitmap_id
                meta["bitmap_coverage"] = r._oa.stamp.get("coverage")
            for i, (key, q) in enumerate(items):
                if deadline and time.time() >= deadline:
                    stopped = f"deadline at {pname} topic {i + 1}"
                    break
                n0 = len(cap.records)
                t = time.perf_counter()
                fused = r.search_rrf(q, top_k=TOP_K)
                t1 = time.perf_counter()
                final = tools._maybe_rerank(copy.deepcopy(fused), q, LIMIT) if fused else []
                t2 = time.perf_counter()
                det = r.search_rrf_detailed(q, top_k=TOP_K, filters=dict(OA_FILTER))
                fused_oa = [{k: v for k, v in d.items() if k != "rrf_legs"} for d in det["results"]]
                t3 = time.perf_counter()
                final_oa = tools._maybe_rerank(copy.deepcopy(fused_oa), q, LIMIT) if fused_oa else []
                t4 = time.perf_counter()
                warns = cap.records[n0:]
                row = {"pass": pname, "topic": key, "query": q,
                       "fused": dump(fused), "final": dump(final),
                       "fused_oa": dump(fused_oa), "final_oa": dump(final_oa),
                       "fused_ids": [d.get("openalex_id") for d in fused],
                       "fused_scores": [d.get("score") for d in fused],
                       "fused_is_oa": [d.get("is_oa") for d in fused],
                       "final_ids": [d.get("openalex_id") for d in final],
                       "final_is_oa": [d.get("is_oa") for d in final],
                       "fused_oa_ids": [d.get("openalex_id") for d in fused_oa],
                       "fused_oa_is_oa": [d.get("is_oa") for d in fused_oa],
                       "final_oa_ids": [d.get("openalex_id") for d in final_oa],
                       "legs_oa": {k: len(v) for k, v in det["legs"].items()},
                       "ms": {"rrf": round((t1 - t) * 1e3, 1), "rerank": round((t2 - t1) * 1e3, 1),
                              "rrf_oa": round((t3 - t2) * 1e3, 1),
                              "rerank_oa": round((t4 - t3) * 1e3, 1)},
                       "warnings": warns[:5],
                       "degraded": any(any(s in w for s in SIGNATURES) for w in warns)}
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                print(f"[{args.arm}/{pname} {i + 1}/{len(items)}] n={len(fused)} n_oa={len(fused_oa)} "
                      f"legs_oa={row['legs_oa']}{' DEGRADED' if row['degraded'] else ''}", flush=True)
            if stopped:
                break
    meta["stopped"] = stopped
    meta["end_utc"] = utc()
    meta_path.write_text(json.dumps(meta, indent=1))
    return 0


def git(*a, cwd=REPO) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *a], text=True)


def snapshots(scratch: Path, need_pre: bool = True) -> dict:
    head = git("rev-parse", "HEAD").strip()
    snap = scratch / f"code_{head[:8]}"
    if not (snap / "src").exists():
        snap.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(f"git -C {REPO} archive {head} src | tar -x -C {snap}", shell=True)
        for name in ("models", "data", ".env"):
            if not (snap / name).exists():
                (snap / name).symlink_to(REPO / name)
    pre = scratch / f"code_{head[:8]}_pre_o17"
    if need_pre and not (pre / "src").exists():
        pre.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(f"git -C {REPO} archive {head} src | tar -x -C {pre}", shell=True)
        for name in ("models", "data", ".env"):
            if not (pre / name).exists():
                (pre / name).symlink_to(REPO / name)
        patch = git("diff", f"{O17_SERVING_COMMIT}^", O17_SERVING_COMMIT, "--", *O17_FILES)
        subprocess.run(["git", "apply", "-R", "-p1"], input=patch, text=True, cwd=pre, check=True)
    return {"head": head, "snap": str(snap), "pre": str(pre)}


def drive(args) -> int:
    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    sn = snapshots(scratch, need_pre="pre" in args.arms.split(","))
    env = {k: v for k, v in os.environ.items() if k not in ENV_DROP}
    env.update({k: "" for k in ENV_BLANK})
    env.update(MODEL_ENV)
    env["PYTHONPATH"] = ""
    env.setdefault("OMP_NUM_THREADS", "4")
    rec = {"start_utc": utc(), **sn, "lock": f"flock -s {LOCK}", "timings_valid": False,
           "bitmap": args.bitmap, "arms": {}}
    procs = []
    cpus = {"pre": "0-3", "off": "0-3", "offon": "4-7", "on": "4-7"}
    for arm in args.arms.split(","):
        src = (sn["pre"] if arm == "pre" else sn["snap"]) + "/src"
        cmd = ["flock", "-s", LOCK, "nice", "-n", "10", "taskset", "-c", cpus[arm], PY,
               str(Path(__file__).resolve()), "child", "--arm", arm, "--src", src,
               "--scratch", str(scratch), "--limit-topics", str(args.limit_topics)]
        if args.deadline:
            cmd += ["--deadline", args.deadline]
        if arm in ("offon", "on") and args.bitmap:
            cmd += ["--bitmap", args.bitmap]
        log = open(scratch / f"{arm}.log", "w")
        procs.append((arm, subprocess.Popen(cmd, env=env, cwd=src.rsplit("/src", 1)[0],
                                            stdout=log, stderr=subprocess.STDOUT), cmd))
    for arm, p, cmd in procs:
        rec["arms"][arm] = {"cmd": cmd, "rc": p.wait()}
    rec["end_utc"] = utc()
    (scratch / "drive.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))
    return 0


def _rows(scratch: Path, arm: str) -> dict:
    out: dict = {}
    p = scratch / f"{arm}.rows.jsonl"
    if p.exists():
        for ln in p.read_text().splitlines():
            r = json.loads(ln)
            out.setdefault(r["pass"], {})[r["topic"]] = r
    return out


def ndcg10(ids: list[str], gains: dict[str, float]) -> float:
    dcg = sum(gains.get(d, 0.0) / math.log2(i + 2) for i, d in enumerate(ids[:10]))
    ideal = sorted(gains.values(), reverse=True)[:10]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def api_check(ids: list[str]) -> dict:
    import requests
    key = ""
    for ln in (REPO / ".env").read_text().splitlines():
        if ln.startswith("OPENALEX_API_KEY="):
            key = ln.split("=", 1)[1].strip().strip('"')
    out: dict = {}
    for s in range(0, len(ids), 50):
        chunk = ids[s:s + 50]
        r = requests.get("https://api.openalex.org/works", timeout=60, params={
            "filter": "openalex_id:" + "|".join(chunk), "per-page": "50",
            "select": "id,open_access", "api_key": key})
        r.raise_for_status()
        for w in r.json().get("results", []):
            out[w["id"].rsplit("/", 1)[-1]] = (w.get("open_access") or {}).get("is_oa")
    return out


def summarize(args) -> int:
    scratch = Path(args.scratch)
    pre = _rows(Path(args.pre_scratch or scratch), "pre").get("pre", {})
    oo = _rows(scratch, "offon")
    off = _rows(scratch, "off").get("off") or oo.get("off", {})
    on = _rows(scratch, "on").get("on") or oo.get("on", {})
    qrels = json.loads(TOPICS.read_text())["topics"]
    res: dict = {"date": "2026-10-01", "script": str(Path(__file__).relative_to(REPO)),
                 "topics_file": str(TOPICS.relative_to(REPO)), "timings_valid": False,
                 "timing_note": "children ran under flock -s (shared) with other agents' jobs: "
                                "latency INVALID by declaration",
                 "drive": json.loads((scratch / "drive.json").read_text())
                 if (scratch / "drive.json").exists() else None}
    for arm in ("pre", "offon", "off", "on"):
        mp = (Path(args.pre_scratch) if arm == "pre" and args.pre_scratch else scratch) / f"{arm}.meta.json"
        if mp.exists():
            res[f"meta_{arm}"] = json.loads(mp.read_text())
    common = sorted(set(pre) & set(off))
    ident = {f: sum(pre[t][f] == off[t][f] for t in common)
             for f in ("fused", "final", "fused_oa", "final_oa")}
    res["M_id_pre_vs_off"] = {"n": len(common), "byte_identical": ident,
                             "degraded_rows": sum(pre[t]["degraded"] or off[t]["degraded"] for t in common),
                             "bar": "120/120 byte-identical (fused, final; also OA-filtered)",
                             "verdict": ("PASS" if len(common) == 120 and all(v == 120 for v in ident.values())
                                         else "PARTIAL" if len(common) < 120 else "FAIL")}

    def oa_counts(rows: dict) -> dict:
        legs: dict = {}
        for r in rows.values():
            for k, v in r["legs_oa"].items():
                legs[k] = legs.get(k, 0) + v
        return {"topics": len(rows),
                "fused_oa_total": sum(len(r["fused_oa_ids"]) for r in rows.values()),
                "final_oa_total": sum(len(r["final_oa_ids"]) for r in rows.values()),
                "topics_with_zero_oa": sum(not r["fused_oa_ids"] for r in rows.values()),
                "legs_oa_total": legs}
    res["M_oa_counts"] = {"pre": oa_counts(pre), "off": oa_counts(off), "on": oa_counts(on)}
    both = sorted(set(off) & set(on))
    if both:
        same_rank = sum(off[t]["fused_ids"] == on[t]["fused_ids"]
                        and off[t]["fused_scores"] == on[t]["fused_scores"] for t in both)
        flips = sum(sum(a != b for a, b in zip(off[t]["fused_is_oa"], on[t]["fused_is_oa"])) for t in both)
        states: dict = {}
        for t in both:
            for v in on[t]["fused_is_oa"]:
                states[str(v)] = states.get(str(v), 0) + 1
        fin_changed = sum(off[t]["final_ids"] != on[t]["final_ids"] for t in both)
        res["M_neutral_on_vs_off"] = {
            "n": len(both), "fused_ids_and_scores_identical": same_rank,
            "fused_is_oa_field_changes": flips, "fused_is_oa_states_on": states,
            "final_top10_changed_topics": fin_changed,
            "final_oa_nonempty_on": sum(bool(on[t]["final_oa_ids"]) for t in both),
            "on_oa_rows_all_true": all(all(v is True for v in on[t]["fused_oa_is_oa"]) for t in both)}

        def gains(t):
            return {d["openalex_id"]: float(d["gain"]) for d in qrels[t]["docs"]}
        q = {}
        for name, field in (("final", "final_ids"), ("final_oa", "final_oa_ids")):
            for arm, rows in (("off", off), ("on", on)):
                vals = [ndcg10(rows[t][field], gains(t)) for t in both]
                q[f"{name}_{arm}"] = round(sum(vals) / len(vals), 4)
        judged = {}
        for arm, rows in (("off", off), ("on", on)):
            tot = sum(len(rows[t]["final_oa_ids"]) for t in both)
            hit = sum(sum(d in gains(t) for d in rows[t]["final_oa_ids"]) for t in both)
            judged[arm] = {"final_oa_docs": tot, "judged": hit}
        q["final_oa_judged_coverage"] = judged
        q["note"] = ("pool qrels from the 2026-08-17 dense ablation (Haiku judge); unjudged docs "
                     "count as gain 0, so OA-filtered nDCG is a lower bound")
        res["M_quality_ndcg10"] = q
        lat = {}
        for arm, rows in (("off", off), ("on", on)):
            for k in ("rrf", "rrf_oa"):
                v = sorted(r["ms"][k] for r in rows.values())
                lat[f"{k}_{arm}_p50_ms"] = v[len(v) // 2] if v else None
        res["latency_INVALID_shared_lock"] = lat
        if args.api_check:
            rng = random.Random(20261001)
            oa_ids = sorted({d for t in both for d in on[t]["fused_oa_ids"]})
            not_ids = sorted({d for t in both for d, v in zip(on[t]["fused_ids"], on[t]["fused_is_oa"])
                              if v is False})
            unk_ids = sorted({d for t in both for d, v in zip(on[t]["fused_ids"], on[t]["fused_is_oa"])
                              if v is None})
            n = args.api_check // 2
            s_oa = rng.sample(oa_ids, min(n, len(oa_ids)))
            s_not = rng.sample(not_ids, min(n, len(not_ids)))
            s_unk = rng.sample(unk_ids, min(50, len(unk_ids)))
            got = api_check(s_oa + s_not + s_unk)
            res["M_precision_api"] = {
                "checked_utc": utc(), "source": "api.openalex.org/works open_access.is_oa (live), "
                "bitmap built from snapshot 2026-09-23",
                "known_oa_sample": len(s_oa), "known_oa_api_true": sum(got.get(d) is True for d in s_oa),
                "known_oa_api_missing": sum(d not in got for d in s_oa),
                "known_not_oa_sample": len(s_not),
                "known_not_oa_api_false": sum(got.get(d) is False for d in s_not),
                "known_not_oa_api_missing": sum(d not in got for d in s_not),
                "unknown_sample": len(s_unk), "unknown_api_found": sum(d in got for d in s_unk),
                "unknown_api_true": sum(got.get(d) is True for d in s_unk),
                "disagreements": [d for d in s_oa if got.get(d) is False]
                + [d for d in s_not if got.get(d) is True]}
    res["generated_utc"] = utc()
    out = Path(args.out)
    out.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if not k.startswith(("meta_", "drive"))}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["drive", "child", "summarize"])
    ap.add_argument("--arm")
    ap.add_argument("--arms", default="pre,offon")
    ap.add_argument("--pre-scratch", default="")
    ap.add_argument("--src")
    ap.add_argument("--bitmap", default="")
    ap.add_argument("--scratch", default=str(SCRATCH))
    ap.add_argument("--deadline", default="")
    ap.add_argument("--limit-topics", type=int, default=0)
    ap.add_argument("--api-check", type=int, default=0)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    return {"drive": drive, "child": child, "summarize": summarize}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
