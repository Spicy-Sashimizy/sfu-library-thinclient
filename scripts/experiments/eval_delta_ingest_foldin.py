#!/usr/bin/env python3
r"""Delta-ingest fold-in harness (doc 10): F2 quality parity of a fold, plus the
F4 recorder for the fold build. Written 2026-10-03, BEFORE any fold was built.

Spec: docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md (FROZEN). Its §6 is
copied verbatim at the end of this header (doc 10 §5 requires that before the
first run). Order of work: spike/delta_ingest/FOLDIN_GATES_FINDINGS.md §"First
fold measurement".

Subcommands (run with /home/vscode/work/venv_local/bin/python3, cwd = repo):
  encode     QT (120 topics) + QD (100 diverse) are taken bit-identical from the
             drift baseline's queries.json (so the saved R and A0 outputs of
             that run are the Q-b reference); QA (240 judged paraphrases of
             dense_ablation_queries.json) is encoded here, same convention
             (encode_splade(q, "models/splade_onnx_fp16"), top-64 terms).
  build      runs `spike.delta_ingest.cli fold-build` as a child and records
             F4's raw numbers: wall, stage seconds (fold.json), peak RSS +
             VmSwap of the process tree, peak scratch bytes, output bytes.
             The publish stage is NOT part of this record.
  preview    writes the F arm's serving state WITHOUT publishing: a preview
             root whose generations.json is the fixture's with (i) the composed
             manifest naming s' at the shard's position (foldin.
             compose_fold_manifest over the fixture's own composed manifest)
             and (ii) mask.newest_by_leg.seismic = {member id: "fold:s:k"} for
             the members publish_fold would mark (live AND last_seen ==
             staged_at). Generation dirs are shared with the fixture by path;
             the fixture root and its ledger are opened read-only.
  measure    one process, two retrievers (L = fixture root, F = preview root),
             every query on both arms. Federated SPLADE leg, E8 conventions:
             k = k' = 200, query_cut = len(terms), heap_factor 0.8,
             SFU_SEISMIC_PREFLOOR=2; per-shard results through the product
             path (backend._fan_out -> backend._shard_result_filter ->
             _merge_topk -> DeltaLayer.filter_ids). QA additionally runs
             search_rrf(top_k=50) + tools._maybe_rerank(limit 10).
  summarize  bars Q-a..Q-d -> data/eval_results/delta_ingest_foldin_<date>.json
             key F2.
  run        measure (child, blanked gate env, shared latency lock) + summarize.

Implementation readings of the frozen F2 row (fixed here before the first run;
none changes a threshold):
  * "shard 0's own results" = for one arm, the merge of position s's results
    and the delta-position results whose id routes to shard s (ledger
    route_shard), after that arm's masks. Same rule on L and F.
  * Q-a is read on the FEDERATED leg for each of QT and QD; the shard-own
    overlap is recorded beside it with its own clears/does-not-clear flag.
    Both bar readings (A: min(0.99, m_set) - 0.005 with m_set from the drift
    baseline's build-vs-build result; B: 0.99) are computed. The verdict is
    read only for the reading given with --bar-reading; without it the F2
    verdict is NOT READ (owner decision, FOLDIN_GATES_FINDINGS.md last section).
  * Q-b reference overlap@10(R, A0) exists at shard level only (R is one
    shard): it is recomputed from the drift run's saved outputs
    (q_build1_dv.json = M9's rebuild, q_served_dv.json = served shard 0), on
    the same encoded queries. Q-b must hold on the shard-own overlap AND on
    the federated overlap against that one reference.
    OWNER DECISION 2026-10-04 (doc 10 addendum of that date, taken AFTER the
    fold-1 and fold-2 runs were read): the federated level is binding for
    Q-b, the shard level is not. `--q-b-level federated` reads Q-b that way;
    the default keeps the reading above so the 2026-10-03 records reproduce.
    The shard-own pass flag is recorded under both.
  * Q-c is read on NDCG@10 of the final (reranked) top-10; a topic's value is
    the mean over its judged paraphrases; unjudged docs gain 0. The fused
    top-10 NDCG is recorded.
  * Q-d counts, over the 460 federated-leg queries on F, any result that
    survives the masks and is (i) a tombstoned id, (ii) at a position that is
    not the id's newest SEISMIC origin per the ledger, or (iii) served from
    two positions; plus tombstoned ids in the 240 fused/final lists.
  * Health: both arms' delta buffers must be empty (the preview root has no
    ledger, so a buffered doc would be served by L only).

---- doc 10 §6, verbatim (frozen 2e674773) ----
## 6. Measurements and frozen bars

Arms: **A0** served shard 0, no delta; **L** (live) = A0 + the fold delta
served as delta generation(s) + masks; **F** (folded) = *s′* + masks with
the folded docs' SEISMIC origin moved (G4); **R** = M9's plain rebuild of
shard 0 without delta (exists: `/var/tmp/sfu_delta_D_20260929/`).

| # | Question | Metric | Bar (frozen) | Lock |
|---|---|---|---|---|
| **F0** | Size dependence of one consolidated generation's tax (calibrates (b)) | paired Δ(arm, n0) in-process as 09 §1.1, arms n0, n1 (160,347 docs, existing), g1M (one 1,000,000-doc generation of base docs re-ingested as updates with twin vectors, no GPU; corpus builder to write) | recorded; PASS-line for using a single consolidated generation as the long-lived sections tier: Δ(g1M) − Δ(n1) ≤ **8.0 ms** (CI upper bound). FAIL → the sections tier also needs a fold or a split, recorded | exclusive |
| **F1** | Trigger bookkeeping is exact | (a), (d), (c) computed by the trigger vs a brute-force recount over the ledger + livedocs on the F-fixture and on `root_n8` | identical on **100%** of 20 checkpoints (after each of 20 synthetic publishes) | none |
| **F2** | Quality parity of the fold | per set QT, QD: mean overlap@10 of F vs L on the federated SPLADE leg (8 shards, shard 0 = *s′* vs base 0 + delta), and on shard 0's own results; QA: NDCG@10 of F and L, paired bootstrap of mean(F − L) over 120 topics, 10,000 resamples, seed 0 | **Q-a:** overlap@10(F, L) ≥ `bar_set` (G1 NOISE: min(0.99, m_set) − 0.005; under a G1 remedy: 0.99) on EACH of QT, QD, federated; **Q-b:** overlap@10(F, L) ≥ overlap@10(R, A0) − **0.005** per set (the fold loses nothing beyond a plain rebuild); **Q-c:** the 95% CI of ΔNDCG@10 contains 0 or lies above 0; **Q-d:** mask leak 0 (no deleted id and no superseded base copy in any F result, 460 queries). PASS = all four | shared OK (no timing) |
| **F3** | Latency returns to n0 | `search_rrf` p50, 120 topics (M4 set), in-process arms n0, L (base + fold delta + consolidated sections tier), F (*s′* + consolidated sections tier), design and statistics = 09 §1 / §1.1 | p50(F) ≤ **1.05 × p50(n0)** AND bootstrap CI upper bound of Δ(F, n0) ≤ **+8.0 ms** (at most one generation's budget left after the fold); Δ(L, F) recorded | exclusive |
| **F4** | Fold cost per shard (profile `desktop_gpu`, quiet host) | wall per stage (dump, build, c1a, dotvbyte, publish), peak RSS (incl. `VmSwap`), scratch and output bytes | wall ≤ **90 min** total; peak RSS ≤ **10 GB** (< the 12 GB `desktop_gpu` abort); scratch ≤ **60 GB**; output ≤ **1.10 ×** (served dv-v2 + f16 twin bytes of *s*) × (docs of *s′* ÷ docs of *s*). Duty cycle at the adopted (a): Σ fold wall over 8 shards per (a)-period ≤ **25%** of that period (*est.* from F4 × §2) | exclusive (timing) |
| **F5** | Crash safety | 50 SIGKILL trials at uniform-random times over the fold wall on a reduced fixture (first 1,000,000 docs of twin 0 + the fold delta routed into it; fixture builder to write), plus 10 kills inside `publish-fold` on the full shard-0 fold output | **60 / 60**: (i) served state after restart is exactly the pre-fold or the post-fold state — every live delta doc routed to *s* is servable from exactly one SEISMIC origin, checked by state inspection + 200 own-id lookups per trial; (ii) the G3 baseline is unchanged; (iii) re-running the fold after a kill completes and its output passes F2 Q-a against L | none (fixture) |
| **F6** | Repeated folds do not compound drift | a second fold of *s′* from its own c1a output + a second delta batch (corpus (b) half not used in fold 1, or Stage-0 Q2 synthetic) | F2's Q-a and Q-b hold for fold 2 vs its live reference; overlap@10(fold 2, A0) on base-only docs recorded | shared OK |
| **F7** | Trigger values per profile | choose (a), (d), (b), (c) defaults from §1 candidates | rule (fixed): the SMALLEST (a) (most frequent fold) whose F4 duty cycle ≤ 25%; if the modelled tax (F0, 09 R1) at that (a)'s fold moment > 8 ms × the adopted `G_max`, the profile is flagged (no default ships ON); (d) = the smallest candidate ≥ the (d) value reached when (a) fires; (c) = 30 days unless F4 duty cycle at (c)-driven folds > 25%; (b) = 8 ms | none |
| **F8** | Reload after a fold publish | M5 metric on the F arm: `reload()` wall, first-query p50 vs warm p50, 5 reps, with the operator prefault of *s′* | the M5 bars, unchanged: reload ≤ **15 s**; first-query p50 ≤ **2 ×** warm p50 | exclusive |

Runtime *est.*: F0 ≈ 2.5 h (corpus build ~1 h + 3 arms in-process ~1.5 h);
F1 ≈ 15 min; F2 fold build ≈ 45–60 min + parity ≈ 30 min; F3 ≈ 1.5 h; F4
inside F2's build when run on a quiet host, else a separate ≈ 1 h; F5 ≈
60 × ~6 min on the 1M fixture ≈ 6 h (light, 2 cores) + 10 publish kills
≈ 30 min; F6 ≈ 1.5 h; F8 ≈ 30 min. At most one SEISMIC shard build at a time
on this host.
---- end of doc 10 §6 ----
"""
from __future__ import annotations

import argparse
import calendar
import copy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
E = os.environ.get
FOLD_ROOT = Path(E("SFU_FOLDIN_ROOT", "/home/vscode/work/delta_ingest/foldin"))
FIXTURE = Path(E("SFU_FOLDIN_FIXTURE", str(FOLD_ROOT / "fixture_n8")))
WORK = Path(E("SFU_FOLDIN_WORK", str(FOLD_ROOT / "f2")))
DRIFT_WORK = Path(E("SFU_FOLDIN_DRIFT_WORK", "/home/vscode/work/delta_ingest/twin_drift"))
DRIFT_RESULT = REPO / "data/eval_results/delta_ingest_twin_drift_baseline_20261001.json"
QA_QUERIES = REPO / "data/eval_results/dense_ablation_queries.json"
QA_QRELS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
LOCK = E("SFU_FOLDIN_LOCK", "/tmp/sfu_latency_measure.lock")
SETS = {"QT": "topics120", "QD": "diverse100"}
K = 200
HEAP_FACTOR = 0.8
TOP_K = 50
LIMIT = 10
BOOT_N = 10_000
BOOT_SEED = 0
M_SET_RECORDED = {"QT": 0.9908, "QD": 0.985}
# peak_rss_gb is the FROZEN 2026-10-01 bar; peak_rss_gb_amended is the owner's amendment of 2026-10-05
# (doc 10 addendum of that date, taken after folds 1-3 were measured), read on peak tree VmRSS + VmSwap.
F4_BARS = {"wall_s": 90 * 60, "peak_rss_gb": 10.0, "peak_rss_gb_amended": 11.5, "scratch_gb": 60.0,
           "output_ratio": 1.10}
BLANK_ENV = ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR", "SFU_SEISMIC_SHARD_MANIFEST", "SFU_DELTA_ROOT",
             "SFU_THINCLIENT_ORDINALS", "SFU_SEARCH_SPECULATIVE_RERANK", "SFU_DELTA_ABS_ROUTE",
             "SFU_BM25F_PARSE_ONCE", "SFU_SEISMIC_DELTA_GROUP", "SFU_OA_BITMAP", "SFU_SEISMIC_SHARD_FAULT_BOUNDARY")
UNSET_ENV = ("SFU_SEISMIC_K_PRIME", "SFU_SEISMIC_QUERY_CUT", "SFU_SEISMIC_HEAP_FACTOR")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ts(s: str) -> float:
    return float(calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")))


def log(msg: str) -> None:
    print(f"{utc()} {msg}", flush=True)


def dump_json(path: Path, obj) -> None:
    tmp = Path(str(path) + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(obj, default=str) + "\n")
    os.replace(tmp, path)


def git_head() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def load_m4f():
    spec = importlib.util.spec_from_file_location("m4f", REPO / "scripts/experiments/eval_delta_ingest_m4f.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def take_lock(mode: str, giveup_s: float) -> tuple:
    """Blocking flock on the shared latency lock. Returns (handle, record)."""
    if mode == "none":
        return None, {"mode": "none"}
    fh = open(LOCK, "a+")
    flag = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
    t0 = time.time()
    while True:
        try:
            fcntl.flock(fh, flag | fcntl.LOCK_NB)
            return fh, {"mode": mode, "acquired_utc": utc(), "waited_s": round(time.time() - t0)}
        except BlockingIOError:
            if time.time() - t0 > giveup_s:
                fh.close()
                return None, {"mode": f"NOT ACQUIRED ({mode}) after {round(giveup_s)} s", "gave_up_utc": utc()}
            time.sleep(15)


# ── pure statistics ─────────────────────────────────────────────────────────
def overlap10(a: list, b: list) -> float:
    return len(set(a[:10]) & set(b[:10])) / 10


def ndcg10(ids: list, gains: dict) -> float:
    dcg = sum(gains.get(d, 0.0) / math.log2(i + 2) for i, d in enumerate(ids[:10]))
    ideal = sorted(gains.values(), reverse=True)[:10]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def paired_bootstrap(deltas: list, n: int = BOOT_N, seed: int = BOOT_SEED) -> dict:
    d = np.asarray(deltas, dtype=np.float64)
    if not len(d):
        return {"n": 0, "mean": None, "ci95": None}
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, len(d), size=(n, len(d)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"n": int(len(d)), "mean": float(d.mean()), "ci95": [float(lo), float(hi)], "resamples": n, "seed": seed}


def find_leaks(per_shard: list, origins: list, tomb: set, truth: dict) -> list:
    """`per_shard[pos]` = surviving `(score, id)` at that served position.
    A leak is a tombstoned id, an id served from a position that is not its
    newest SEISMIC origin (`truth`), or an id served from two positions."""
    out, seen = [], {}
    for pos, res in enumerate(per_shard):
        o = origins[pos] if pos < len(origins) else None
        for _s, d in res:
            if d in tomb:
                out.append({"id": d, "pos": pos, "kind": "deleted"})
            elif d in truth and truth[d] != o:
                out.append({"id": d, "pos": pos, "kind": "stale_copy", "origin": o, "newest": truth[d]})
            if d in seen and seen[d] != pos:
                out.append({"id": d, "pos": pos, "kind": "double_served", "other_pos": seen[d]})
            seen.setdefault(d, pos)
    return out


def q_a_bars(m_set: dict) -> dict:
    return {s: {"m_set": m_set.get(s), "A": (round(min(0.99, m_set[s]) - 0.005, 6) if m_set.get(s) is not None else None),
                "B": 0.99} for s in SETS}


# ── encode ──────────────────────────────────────────────────────────────────
def cmd_encode(a) -> int:
    src = json.loads((DRIFT_WORK / "queries.json").read_text())
    enc = {s: src["encoded"][name] for s, name in SETS.items()}
    texts = {s: src["texts"][name] for s, name in SETS.items()}
    assert len(enc["QT"]) == 120 and len(enc["QD"]) == 100
    sys.path.insert(0, str(REPO / "source"))
    os.chdir(REPO)
    from lib.opensearch_retriever import encode_splade
    qa = json.loads(QA_QUERIES.read_text())
    topics = json.loads(QA_QRELS.read_text())["topics"]
    assert len(qa) == 240 and all(r["judge_key"] in topics for r in qa)
    rows = []
    for r in qa:
        d = dict(sorted(encode_splade(r["paraphrase"], "models/splade_onnx_fp16").items(), key=lambda x: -x[1])[:64])
        rows.append([[t, float(np.float32(v))] for t, v in d.items()])
    assert min(len(r) for r in rows) > 0, "SPLADE produced an empty query: model not loaded"
    enc["QA"] = rows
    texts["QA"] = [r["paraphrase"] for r in qa]
    out = {"created_utc": utc(), "model": "models/splade_onnx_fp16", "top_terms": 64, "texts": texts,
           "encoded": enc, "qa_keys": [r["judge_key"] for r in qa],
           "qt_qd_source": str(DRIFT_WORK / "queries.json"), "qt_qd_source_sha256": src.get("sha256"),
           "sha256": hashlib.sha256(json.dumps(enc, sort_keys=True).encode()).hexdigest()}
    WORK.mkdir(parents=True, exist_ok=True)
    dump_json(WORK / "queries.json", out)
    print(json.dumps({k: out[k] for k in ("created_utc", "sha256", "qt_qd_source_sha256")}
                     | {"n": {s: len(v) for s, v in enc.items()}}))
    return 0


# ── F4 recorder around fold-build ───────────────────────────────────────────
def _tree_mem_gb(pid: int) -> tuple:
    kids: dict = {}
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                stat = Path(f"/proc/{p}/stat").read_text()
                kids.setdefault(int(stat.rsplit(")", 1)[1].split()[1]), []).append(int(p))
            except (OSError, IndexError, ValueError):
                pass
    todo, rss, swap, top = [pid], 0, 0, 0
    while todo:
        cur = todo.pop()
        todo.extend(kids.get(cur, []))
        try:
            r = s = 0
            for line in Path(f"/proc/{cur}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    r = int(line.split()[1])
                elif line.startswith("VmSwap:"):
                    s = int(line.split()[1])
            rss, swap, top = rss + r, swap + s, max(top, r + s)
        except OSError:
            pass
    return rss / 1048576, swap / 1048576, top / 1048576


def _tree_detail(pid: int) -> list:
    """Per process of the tree: comm, VmRSS, RssAnon, RssFile, VmSwap, Pss (GiB).
    Added 2026-10-04 for the per-stage memory timeline; the F4 fields above
    keep their 2026-10-03 definitions."""
    kids: dict = {}
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                stat = Path(f"/proc/{p}/stat").read_text()
                kids.setdefault(int(stat.rsplit(")", 1)[1].split()[1]), []).append(int(p))
            except (OSError, IndexError, ValueError):
                pass
    todo, out = [pid], []
    while todo:
        cur = todo.pop()
        todo.extend(kids.get(cur, []))
        try:
            d = {"pid": cur, "comm": Path(f"/proc/{cur}/comm").read_text().strip()}
            for line in Path(f"/proc/{cur}/status").read_text().splitlines():
                k = line.split(":")[0]
                if k in ("VmRSS", "RssAnon", "RssFile", "VmSwap"):
                    d[k] = round(int(line.split()[1]) / 1048576, 3)
            for line in Path(f"/proc/{cur}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    d["Pss"] = round(int(line.split()[1]) / 1048576, 3)
            out.append(d)
        except OSError:
            pass
    return out


def dir_bytes(d: Path) -> int:
    n = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            try:
                n += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return n


def cmd_build(a) -> int:
    fh, lock = take_lock(a.lock, a.lock_giveup_s)
    if a.lock != "none" and fh is None:
        log(f"lock {lock}")
        return 9
    shard_dir = Path(a.fold_root) / f"shard{a.shard}"
    argv = [sys.executable, "-m", "spike.delta_ingest.cli", "fold-build", "--delta-root", a.delta_root,
            "--shard", str(a.shard), "--fold-input", a.fold_input, "--token-map-dir", a.token_map_dir,
            "--fold-root", str(a.fold_root), "--fold-workers", str(a.fold_workers), "--profile", a.profile,
            "--seismic-threads", str(a.seismic_threads)]
    env = dict(os.environ, OMP_NUM_THREADS=str(a.seismic_threads), RAYON_NUM_THREADS=str(a.seismic_threads),
               SFU_SEISMIC_STAGE_DIR="", SFU_META_STAGE_DIR="", SFU_DELTA_ROOT="")
    before = {p.name for p in shard_dir.glob("fold*")} if shard_dir.exists() else set()
    box = {"rss": 0.0, "swap": 0.0, "sum": 0.0, "one": 0.0, "scratch": 0, "min_avail": 1e9}
    stop = threading.Event()
    t0 = time.time()
    logf = open(Path(a.log), "w") if a.log else None
    p = subprocess.Popen(argv, cwd=REPO, env=env, stdout=logf, stderr=subprocess.STDOUT if logf else None)

    timeline = open(Path(a.log + ".mem.jsonl"), "w") if a.log else None
    det = {"anon": 0.0, "file": 0.0, "pss": 0.0, "by_comm": {}}

    def poll():
        i = 0
        while not stop.is_set():
            rss, swap, one = _tree_mem_gb(p.pid)
            procs = _tree_detail(p.pid)
            det.update(anon=max(det["anon"], sum(x.get("RssAnon", 0) + x.get("VmSwap", 0) for x in procs)),
                       file=max(det["file"], sum(x.get("RssFile", 0) for x in procs)),
                       pss=max(det["pss"], sum(x.get("Pss", 0) + x.get("VmSwap", 0) for x in procs)))
            for x in procs:
                c = det["by_comm"].setdefault(x["comm"], {"rss_plus_swap": 0.0, "anon_plus_swap": 0.0})
                c["rss_plus_swap"] = max(c["rss_plus_swap"], x.get("VmRSS", 0) + x.get("VmSwap", 0))
                c["anon_plus_swap"] = max(c["anon_plus_swap"], x.get("RssAnon", 0) + x.get("VmSwap", 0))
            if timeline:
                timeline.write(json.dumps({"t": round(time.time() - t0, 1), "tree_rss": round(rss, 3),
                                           "tree_swap": round(swap, 3), "procs": procs}) + "\n")
                timeline.flush()
            box.update(rss=max(box["rss"], rss), swap=max(box["swap"], swap), sum=max(box["sum"], rss + swap),
                       one=max(box["one"], one))
            for line in open("/proc/meminfo"):
                if line.startswith("MemAvailable:"):
                    box["min_avail"] = min(box["min_avail"], int(line.split()[1]) / 1048576)
            if i % 5 == 0 and shard_dir.exists():
                box["scratch"] = max(box["scratch"], sum(dir_bytes(d) for d in shard_dir.glob("fold*")
                                                         if d.name not in before))
            i += 1
            stop.wait(2)
    th = threading.Thread(target=poll, daemon=True)
    th.start()
    rc = p.wait()
    stop.set()
    th.join(timeout=30)
    wall = time.time() - t0
    new = sorted(d for d in shard_dir.glob("fold*") if d.name not in before) if shard_dir.exists() else []
    fold = json.loads((new[-1] / "fold.json").read_text()) if new and (new[-1] / "fold.json").exists() else {}
    out_bytes = dir_bytes(new[-1]) if new else None
    rec = {"item": "doc 10 F4 raw numbers of one fold build (publish stage not included)", "date_utc": utc(),
           "script": "scripts/experiments/eval_delta_ingest_foldin.py", "git_head": git_head(), "argv": argv,
           "rc": rc, "lock": lock, "quiet_host": lock.get("mode") == "exclusive", "wall_s": round(wall, 1),
           "peak_tree_vmrss_gb": round(box["rss"], 3), "peak_tree_vmswap_gb": round(box["swap"], 3),
           "peak_tree_rss_plus_swap_gb": round(box["sum"], 3), "peak_single_process_rss_plus_swap_gb": round(box["one"], 3),
           "peak_tree_anon_plus_swap_gb": round(det["anon"], 3), "peak_tree_rssfile_gb": round(det["file"], 3),
           "peak_tree_pss_plus_swap_gb": round(det["pss"], 3), "peak_by_comm_gb": det["by_comm"],
           "mem_timeline": (a.log + ".mem.jsonl") if a.log else None,
           "min_host_memavail_gb": round(box["min_avail"], 2), "peak_fold_dir_bytes": box["scratch"],
           "final_fold_dir_bytes": out_bytes, "fold_dir": str(new[-1]) if new else None,
           "fold_json": {k: v for k, v in fold.items() if k not in ("token_map_appended_sample",)}}
    try:
        base = json.loads(Path(a.base_manifest).read_text())["shards"]
        srec = next(r for j, r in enumerate(base) if r.get("shard", j) == a.shard and r.get("delta_generation") is None)
        mm = Path(srec["mmap_dir"])
        served = dir_bytes(mm if mm.is_absolute() else REPO / mm) + dir_bytes(Path(a.fold_input))
        docs_new = int((fold.get("dump") or {}).get("docs") or 0)
        allowed = F4_BARS["output_ratio"] * served * docs_new / int(srec["n_docs"])
        rec["output_bar"] = {"served_dv_plus_f16_bytes": served, "docs_s": int(srec["n_docs"]), "docs_s_prime": docs_new,
                             "allowed_bytes": int(allowed), "pass": bool(out_bytes is not None and docs_new and out_bytes <= allowed)}
    except Exception as exc:
        rec["output_bar"] = {"error": repr(exc)}
    rec["bars"] = {"wall_le_90min": wall <= F4_BARS["wall_s"],
                   "peak_rss_incl_swap_le_10gb": box["sum"] <= F4_BARS["peak_rss_gb"],
                   "peak_tree_rss_incl_swap_le_11p5gb_amended_20261005": box["sum"] <= F4_BARS["peak_rss_gb_amended"],
                   "scratch_le_60gb": box["scratch"] <= F4_BARS["scratch_gb"] * 1e9,
                   "output": rec["output_bar"].get("pass"),
                   "note": "read as F4 only on a quiet host (exclusive lock) and with the publish stage added"}
    res = Path(a.out or REPO / f"data/eval_results/delta_ingest_foldin_{time.strftime('%Y%m%d', time.gmtime())}.json")
    data = json.loads(res.read_text()) if res.exists() else {}
    data[a.key] = rec
    res.write_text(json.dumps(data, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in rec.items() if k != "fold_json"}, indent=1, default=str))
    return 0 if rc == 0 and fold.get("state") == "built" else 4


# ── F-arm preview root ──────────────────────────────────────────────────────
def make_preview(delta_root: Path, shard: int, fold: int | None, fold_root: Path, out_dir: Path, cfg=None) -> dict:
    sys.path.insert(0, str(REPO / "source"))
    sys.path.insert(0, str(REPO))
    from spike.delta_ingest import foldin
    delta_root = Path(delta_root)
    db = sqlite3.connect(f"file:{delta_root / 'ledger.sqlite'}?mode=ro", uri=True)
    if "route_shard" not in [r[1] for r in db.execute("PRAGMA table_info(docs)")]:
        raise SystemExit(f"{delta_root}: ledger has no route_shard column (run cli.py backfill-routes on the fixture copy)")
    rows = db.execute("SELECT fold, state, dir, info FROM folds WHERE shard=? ORDER BY fold", (shard,)).fetchall()
    rows = [r for r in rows if fold is None or r[0] == fold]
    if not rows:
        raise SystemExit(f"no fold of shard {shard} (fold={fold}) in {delta_root}/ledger.sqlite")
    k, state, fdir, info = rows[-1][0], rows[-1][1], rows[-1][2], json.loads(rows[-1][3] or "{}")
    if state not in ("built", "ready"):
        raise SystemExit(f"fold {shard}/{k} is {state}; the preview needs a built, unpublished fold")
    mmap = Path(info.get("mmap_dir") or "")
    if not mmap.is_dir():
        raise SystemExit(f"fold {shard}/{k}: served dir {mmap} missing")
    origin = foldin.fold_origin(shard, k)
    moved = [r[0] for r in db.execute(
        "SELECT d.id FROM docs d JOIN fold_members m ON m.id=d.id WHERE m.shard=? AND m.fold=? "
        "AND d.status='live' AND d.last_seen=m.staged_at ORDER BY d.id", (shard, k))]
    members = db.execute("SELECT COUNT(*) FROM fold_members WHERE shard=? AND fold=?", (shard, k)).fetchone()[0]
    db.close()
    gj = json.loads((delta_root / "generations.json").read_text())
    lman = gj.get("shard_manifest")
    if not lman or not Path(lman).exists():
        raise SystemExit(f"{delta_root}/generations.json names no existing composed shard manifest")
    for g in gj.get("generations") or []:
        if not Path(g["dir"]).is_absolute() or not Path(g["dir"]).is_dir():
            raise SystemExit(f"generation dir {g['dir']} is not an existing absolute path")
    cfg = cfg or foldin.GuardConfig(fold_root=Path(fold_root))
    man = Path(fold_root) / "manifests" / f"f2_preview.fold_s{shard}_k{k}.json"
    if man.exists():
        old = json.loads(man.read_text())
        rec = [r for r in old["shards"] if r.get("fold_origin") == origin]
        if old.get("composed_from") != str(lman) or len(rec) != 1 or rec[0]["mmap_dir"] != str(mmap):
            raise SystemExit(f"{man} exists and was composed from other inputs; remove it by hand after checking")
    else:
        foldin.compose_fold_manifest(Path(lman), shard, k, mmap, int((info.get("dump") or {}).get("docs") or 0),
                                     man, cfg, info.get("format") or "dotvbyte_fixedu8_v2")
    pg = dict(gj)
    mask = dict(gj.get("mask") or {})
    nb = dict(mask.get("newest_by_leg") or {})
    sm = dict(nb.get("seismic") or {})
    sm.update({i: origin for i in moved})
    nb["seismic"] = sm
    mask["newest_by_leg"] = nb
    pg.update(mask=mask, shard_manifest=str(man), stamp=f"{gj.get('stamp')}+f2preview-{origin}")
    if pg.get("livedocs") and not Path(pg["livedocs"]["path"]).is_absolute():
        pg["livedocs"] = dict(pg["livedocs"], path=str(delta_root / pg["livedocs"]["path"]))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_json(out_dir / "generations.json", pg)
    rec = {"created_utc": utc(), "delta_root": str(delta_root), "preview_root": str(out_dir), "shard": shard, "fold": k,
           "origin": origin, "fold_state": state, "fold_dir": fdir, "fold_mmap_dir": str(mmap), "manifest": str(man),
           "composed_from": str(lman), "members": members, "moved": len(moved), "moved_ids": moved,
           "token_map_appended": info.get("token_map_appended"), "fold_docs": (info.get("dump") or {}).get("docs")}
    dump_json(out_dir / "preview.json", rec)
    return rec


def cmd_preview(a) -> int:
    rec = make_preview(Path(a.delta_root), a.shard, a.fold, Path(a.fold_root), Path(a.preview_root))
    print(json.dumps({k: v for k, v in rec.items() if k != "moved_ids"}, indent=1))
    return 0


# ── measure ─────────────────────────────────────────────────────────────────
def ledger_truth(delta_root: Path) -> dict:
    db = sqlite3.connect(f"file:{Path(delta_root) / 'ledger.sqlite'}?mode=ro", uri=True)
    live = db.execute("SELECT id, generation, route_shard FROM docs WHERE status='live'").fetchall()
    out = {"tomb": {r[0] for r in db.execute("SELECT id FROM tombstones")},
           "gen": {i: int(g) for i, g, _ in live}, "route": {i: (int(s) if s is not None else None) for i, _, s in live},
           "superseded": db.execute("SELECT COUNT(*) FROM docs WHERE status='live' AND (in_base=1 OR id IN "
                                    "(SELECT id FROM history))").fetchone()[0]}
    db.close()
    return out


def open_arm(name: str, root: Path, cfg, bad) -> tuple:
    from lib.thinclient.retriever import ThinClientRetriever
    os.environ["SFU_DELTA_ROOT"] = str(root)
    try:
        r = ThinClientRetriever(index_root=cfg.thinclient_index_root, splade_model_path=cfg.splade_model_path,
                                openalex_mailto=cfg.openalex_mailto, query_log_path="",
                                openalex_api_key=cfg.openalex_api_key, remote_abstract_fetcher=None)
        r._fetch_remote_abstracts = lambda ids: {}
        r._load()
        b = r._seismic_backend()
    finally:
        os.environ["SFU_DELTA_ROOT"] = ""
    d = r._delta
    if d is None:
        bad(f"{name}: delta layer not loaded")
        return r, b, [], {}
    origins = d.shard_origins(len(b.shards), r._seismic_manifest)
    info = {"root": str(root), "backend": type(b).__name__, "n_shards": len(b.shards), "origins": origins,
            "manifest": r._seismic_manifest, "stamp": d.stamp, "generations": len(d.generations),
            "buffer_size": d.buffer_size(), "deleted": len(d.deleted), "superseded": len(d.superseded),
            "seismic_newest": len(d.seismic_newest), "livedocs": d.livedocs is not None,
            "shard_filter_attached": getattr(b, "_shard_result_filter", None) is not None}
    if type(b).__name__ != "ParallelSeismicBackend":
        bad(f"{name}: backend {type(b).__name__} != ParallelSeismicBackend")
    if any(x is None for x in b.shards):
        bad(f"{name}: a shard failed to load")
    if getattr(b, "_fault_boundary", False):
        bad(f"{name}: shard fault boundary is ON")
    if d.buffer_size() != 0:
        bad(f"{name}: delta buffer holds {d.buffer_size()} docs (must be empty)")
    return r, b, origins, info


def leg_query(r, b, origins: list, terms: list, shard: int, truth: dict, route: dict) -> dict:
    from lib.thinclient.sharded_seismic_backend import _merge_topk, _prepare_query
    q = {t: v for t, v in terms}
    qcomp, qvals, qc, kp = _prepare_query(q, K, b._string_dtype, len(q), K)
    per = b._fan_out(lambda idx: idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                                            k=kp, query_cut=qc, heap_factor=HEAP_FACTOR))
    raw_n = sum(len(x) for x in per)
    f = getattr(b, "_shard_result_filter", None)
    if f is not None:
        per = f(per)
    d = r._delta
    fed = d.filter_ids(_merge_topk(per, K))
    own_in = [res if pos == shard else ([x for x in res if route.get(x[2]) == shard] if origins[pos] is not None
                                        and not isinstance(origins[pos], str) else [])
              for pos, res in enumerate(per)]
    own = d.filter_ids(_merge_topk(own_in, K))
    keep = {i for i, _ in d.filter_ids([(x[2], float(x[1])) for res in per for x in res])}
    surv = [[(float(x[1]), x[2]) for x in res if x[2] in keep] for res in per]
    return {"fed": fed, "own": own, "raw_candidates": raw_n, "survivors": sum(len(s) for s in surv),
            "leaks": find_leaks(surv, origins, truth["tomb"], truth["newest"])}


def cmd_measure(a) -> int:
    t_start = time.time()
    sys.path.insert(0, str(REPO / "source"))
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)
    import logging
    m4f = load_m4f()
    cap = m4f.M4._WarnCapture()
    logging.getLogger().addHandler(cap)
    guard = m4f.MemGuard()
    guard.start()
    health = {"ok": True, "problems": []}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)
        log(f"HEALTH: {msg}")

    if os.environ.get("SFU_SEISMIC_PREFLOOR") != "2":
        bad(f"SFU_SEISMIC_PREFLOOR={os.environ.get('SFU_SEISMIC_PREFLOOR')!r} (E8 convention is 2; use `run`)")
    fh, lock = take_lock(a.lock, a.lock_giveup_s)
    if a.lock != "none" and fh is None:
        bad(f"lock: {lock}")
    prev = json.loads((Path(a.preview_root) / "preview.json").read_text())
    if Path(prev["delta_root"]).resolve() != Path(a.delta_root).resolve():
        bad(f"preview was made from {prev['delta_root']}, not {a.delta_root}")
    shard, origin = int(prev["shard"]), prev["origin"]
    qs = json.loads((WORK / "queries.json").read_text())
    led = ledger_truth(Path(a.delta_root))
    moved = set(prev["moved_ids"])
    truth = {"L": {"tomb": led["tomb"], "newest": dict(led["gen"])},
             "F": {"tomb": led["tomb"], "newest": {i: (origin if i in moved else g) for i, g in led["gen"].items()}}}
    h, cfg = m4f._common_health(bad)
    health.update(h)
    import lib.tools as tools
    out = {"run": "F2", "script": "scripts/experiments/eval_delta_ingest_foldin.py", "git_head": git_head(),
           "start_utc": utc(), "lock": lock, "preview": {k: v for k, v in prev.items() if k != "moved_ids"},
           "queries_sha256": qs["sha256"], "search": {"k": K, "k_prime": K, "heap_factor": HEAP_FACTOR,
                                                      "query_cut": "len(terms)", "prefloor": os.environ.get("SFU_SEISMIC_PREFLOOR")},
           "ledger": {"live": len(led["gen"]), "tombstones": len(led["tomb"]), "superseded": led["superseded"],
                      "routed_to_shard": sum(1 for s in led["route"].values() if s == shard), "moved": len(moved)},
           "tomb_ids": sorted(led["tomb"]), "limit": a.limit, "health": health, "arms": {}, "leg": [], "qa": [], "selfcheck": []}
    arms = {}
    for name, root in (("L", Path(a.delta_root)), ("F", Path(a.preview_root))):
        try:
            r, b, origins, info = open_arm(name, root, cfg, bad)
        except Exception as exc:
            bad(f"{name}: open raised {exc!r}")
            continue
        arms[name] = (r, b, origins)
        out["arms"][name] = info
        log(f"arm {name}: {info}")
    if len(arms) == 2:
        oL, oF = arms["L"][2], arms["F"][2]
        if oF[shard:shard + 1] != [origin]:
            bad(f"F: position {shard} origin {oF[shard:shard + 1]} != {origin}")
        if [o for j, o in enumerate(oF) if j != shard] != [o for j, o in enumerate(oL) if j != shard]:
            bad("F and L differ at a position other than the folded shard")
        # F6 (doc 10 addendum 2026-10-09): L may serve a previously PUBLISHED fold of s at position s
        _db = sqlite3.connect(f"file:{Path(a.delta_root) / 'ledger.sqlite'}?mode=ro", uri=True)
        try:
            _pub = [f"fold:{shard}:{k}" for (k,) in _db.execute(
                "SELECT fold FROM folds WHERE shard=? AND state='published' ORDER BY fold DESC LIMIT 1", (shard,))]
        except sqlite3.OperationalError:
            _pub = []
        finally:
            _db.close()
        if oL[shard:shard + 1] not in ([None], _pub):
            bad(f"L: position {shard} is neither the base shard nor the root's published fold ({oL[shard:shard + 1]})")
        if out["arms"]["F"].get("seismic_newest") != len(moved):
            bad(f"F: seismic_newest {out['arms']['F'].get('seismic_newest')} != moved {len(moved)}")
        if not out["arms"]["F"].get("shard_filter_attached"):
            bad("F: the per-shard origin filter is not attached")
    if any(any(s in w for s in m4f.SIGNATURES) for w in cap.records):
        bad("failure signature logged at load")
    dump_json(Path(a.rows_out), out)
    if not health["ok"]:
        log(f"HEALTH FAIL {health['problems']}")
        return 3
    deadline = ts(a.deadline) if a.deadline else None
    stop = None

    def halted():
        if guard.tripped:
            return f"memory abort: {guard.tripped}"
        if deadline and time.time() > deadline:
            return "deadline reached"
        return None

    for s in ("QT", "QD", "QA"):
        rows = qs["encoded"][s][: a.limit or None]
        for i, terms in enumerate(rows):
            stop = halted()
            if stop:
                break
            row = {"set": s, "i": i}
            for name, (r, b, origins) in arms.items():
                res = leg_query(r, b, origins, terms, shard, truth[name], led["route"])
                if s == "QT" and i < 5:
                    ref = b.search_encoded({t: v for t, v in terms}, K, query_cut=len(terms),
                                           heap_factor=HEAP_FACTOR, k_prime=K)
                    out["selfcheck"].append({"arm": name, "i": i, "equal_to_search_encoded":
                                             [d for d, _ in r._delta.filter_ids(ref)] == [d for d, _ in res["fed"]]})
                row[name] = {"fed10": [[d, float(x)] for d, x in res["fed"][:10]], "fed_ids": [d for d, _ in res["fed"]],
                             "own10": [[d, float(x)] for d, x in res["own"][:10]], "raw_candidates": res["raw_candidates"],
                             "survivors": res["survivors"], "leaks": res["leaks"]}
            out["leg"].append(row)
            if (i + 1) % 20 == 0:
                log(f"leg {s} {i + 1}/{len(rows)} avail {guard.avail_gb():.1f} GB")
                dump_json(Path(a.rows_out), {**out, "partial": True, "mem": guard.state()})
        if stop:
            break
    if not stop:
        texts = qs["texts"]["QA"][: a.limit or None]
        for i, q in enumerate(texts):
            stop = halted()
            if stop:
                break
            row = {"i": i, "key": qs["qa_keys"][i], "query": q}
            for name, (r, _b, _o) in arms.items():
                fused = r.search_rrf(q, top_k=TOP_K)
                final = tools._maybe_rerank(copy.deepcopy(fused), q, LIMIT) if fused else []
                row[name] = {"fused_ids": [d.get("openalex_id") for d in fused],
                             "final_ids": [d.get("openalex_id") for d in final]}
            out["qa"].append(row)
            if (i + 1) % 20 == 0:
                log(f"qa {i + 1}/{len(texts)} avail {guard.avail_gb():.1f} GB")
                dump_json(Path(a.rows_out), {**out, "partial": True, "mem": guard.state()})
    if any(not c["equal_to_search_encoded"] for c in out["selfcheck"]):
        bad("self-check: the harness leg differs from backend.search_encoded + filter_ids")
    sig = [w for w in cap.records if any(s in w for s in m4f.SIGNATURES)]
    if sig:
        bad(f"failure signatures during the run: {sig[:5]}")
    out.update(stop=stop, mem=guard.state(), wall_s=round(time.time() - t_start, 1), end_utc=utc(),
               warnings=len(cap.records))
    dump_json(Path(a.rows_out), out)
    log(f"done stop={stop} health_ok={health['ok']} wall={out['wall_s']}s")
    return 4 if stop else (0 if health["ok"] else 3)


# ── summarize ───────────────────────────────────────────────────────────────
def reference_r_vs_a0() -> dict:
    """overlap@10(R, A0) per set at shard level, from the drift run's saved outputs."""
    fr, fa = DRIFT_WORK / "q_build1_dv.json", DRIFT_WORK / "q_served_dv.json"
    if fr.exists() and fa.exists():
        r, s = json.loads(fr.read_text())["results"][0], json.loads(fa.read_text())["results"][0]
        return {k: {"overlap10_mean": float(np.mean([overlap10([d for d, _ in x], [d for d, _ in y])
                                                     for x, y in zip(r[name], s[name])])), "n": len(r[name]),
                    "source": f"{fr.name} vs {fa.name} (recomputed)"} for k, name in SETS.items()}
    try:
        lvl = json.loads(DRIFT_RESULT.read_text())["served_level"]["build1_dv_vs_served (M9 rerun, unpinned)"]
        return {k: {"overlap10_mean": lvl[name]["overlap10_mean"], "n": lvl[name]["n"],
                    "source": f"{DRIFT_RESULT.name} served_level (recorded)"} for k, name in SETS.items()}
    except (OSError, KeyError, ValueError):
        return {k: {"overlap10_mean": None, "n": 0, "source": "MISSING"} for k in SETS}


def drift_m_set() -> dict:
    """m_set = build-vs-build mean overlap@10 of the drift baseline's FULL run (unpinned build 2 vs M9's
    build 1, stock level), recomputed from its saved query outputs; else the values recorded in
    spike/delta_ingest/TWIN_DRIFT_BASELINE_FINDINGS.md (the committed results file holds the later prefix run)."""
    f2, f1 = DRIFT_WORK / "q_build2_stock.json", DRIFT_WORK / "q_build1_stock.json"
    if f2.exists() and f1.exists():
        x, y = json.loads(f2.read_text())["results"][0], json.loads(f1.read_text())["results"][0]
        return {k: round(float(np.mean([overlap10([d for d, _ in a], [d for d, _ in b])
                                        for a, b in zip(x[name], y[name])])), 4) for k, name in SETS.items()} | {
            "source": f"{f2.name} vs {f1.name} (recomputed)"}
    return dict(M_SET_RECORDED, source="TWIN_DRIFT_BASELINE_FINDINGS.md (recorded)")


def compute_f2(rows: dict, qrels: dict, m_set: dict, ref: dict, planned: dict, reading: str | None,
               q_b_level: str = "shard_and_federated") -> dict:
    leg, qa = rows.get("leg") or [], rows.get("qa") or []
    bars = q_a_bars(m_set)
    res = {"Q_a": {}, "Q_b": {}}
    for s in SETS:
        rs = [r for r in leg if r["set"] == s]
        fed = [overlap10([d for d, _ in r["F"]["fed10"]], [d for d, _ in r["L"]["fed10"]]) for r in rs]
        own = [overlap10([d for d, _ in r["F"]["own10"]], [d for d, _ in r["L"]["own10"]]) for r in rs]
        fm, om = (float(np.mean(fed)) if fed else None), (float(np.mean(own)) if own else None)
        res["Q_a"][s] = {"n": len(rs), "federated_overlap10_mean": fm, "shard_own_overlap10_mean": om,
                         "federated_min": min(fed) if fed else None, "shard_own_min": min(own) if own else None,
                         "identical_top10_federated": sum(1 for x in fed if x == 1.0),
                         "identical_top10_shard_own": sum(1 for x in own if x == 1.0), **bars[s]}
        for rd in ("A", "B"):
            b = bars[s][rd]
            res["Q_a"][s][f"pass_{rd}"] = bool(fm is not None and b is not None and fm >= b)
            res["Q_a"][s][f"shard_own_clears_{rd}"] = bool(om is not None and b is not None and om >= b)
        rv = ref[s]["overlap10_mean"]
        thr = rv - 0.005 if rv is not None else None
        res["Q_b"][s] = {"reference_R_vs_A0": ref[s], "threshold": thr, "shard_own_overlap10_mean": om,
                         "federated_overlap10_mean": fm, "level": q_b_level,
                         "pass_shard_own": bool(thr is not None and om is not None and om >= thr),
                         "pass_federated": bool(thr is not None and fm is not None and fm >= thr),
                         "pass": bool(thr is not None and fm is not None and fm >= thr
                                      and (q_b_level == "federated" or (om is not None and om >= thr)))}
    by_topic: dict = {}
    for r in qa:
        gains = {d["openalex_id"]: float(d["gain"]) for d in qrels[r["key"]]["docs"]}
        by_topic.setdefault(r["key"], []).append(
            {f"{arm}_{field}": ndcg10(r[arm][f"{field}_ids"], gains) for arm in ("F", "L") for field in ("final", "fused")})
    tm = {t: {k: float(np.mean([v[k] for v in vs])) for k in vs[0]} for t, vs in by_topic.items()}
    qc = {}
    for field in ("final", "fused"):
        boot = paired_bootstrap([tm[t][f"F_{field}"] - tm[t][f"L_{field}"] for t in sorted(tm)])
        qc[field] = {"topics": len(tm), "queries": len(qa),
                     "ndcg10_F": float(np.mean([v[f"F_{field}"] for v in tm.values()])) if tm else None,
                     "ndcg10_L": float(np.mean([v[f"L_{field}"] for v in tm.values()])) if tm else None,
                     "delta_F_minus_L": boot}
    qc["pass"] = bool(qc["final"]["delta_F_minus_L"]["ci95"] is not None and qc["final"]["delta_F_minus_L"]["ci95"][1] >= 0)
    qc["identical_final_top10"] = sum(1 for r in qa if r["F"]["final_ids"] == r["L"]["final_ids"])
    res["Q_c"] = qc
    tomb = set(rows.get("tomb_ids") or [])
    leaks_f = [dict(x, set=r["set"], i=r["i"]) for r in leg for x in r["F"]["leaks"]]
    leaks_l = sum(len(r["L"]["leaks"]) for r in leg)
    qa_tomb = sum(1 for r in qa for f in ("fused_ids", "final_ids") for d in r["F"][f] if d in tomb)
    led = rows.get("ledger") or {}
    res["Q_d"] = {"federated_leg_queries": len(leg), "leaks_F": len(leaks_f), "leak_examples_F": leaks_f[:10],
                  "leaks_L_control": leaks_l, "tombstoned_in_F_fused_or_final": qa_tomb,
                  "pass": len(leaks_f) == 0 and qa_tomb == 0,
                  "coverage_note": (f"fixture has {led.get('tombstones')} tombstones and {led.get('superseded')} superseded "
                                    "docs; with 0 of both, Q-d exercises only the double-serving of folded docs")}
    done = {s: sum(1 for r in leg if r["set"] == s) for s in ("QT", "QD", "QA")} | {"QA_pipeline": len(qa)}
    complete = done == planned and not rows.get("stop") and not rows.get("partial")
    healthy = bool((rows.get("health") or {}).get("ok"))
    res.update(done=done, planned=planned, complete=complete, healthy=healthy)
    common = res["Q_c"]["pass"] and res["Q_d"]["pass"] and all(res["Q_b"][s]["pass"] for s in SETS)
    by = {rd: ("PASS" if common and all(res["Q_a"][s][f"pass_{rd}"] for s in SETS) else "FAIL") for rd in ("A", "B")}
    res["verdict_by_reading"] = by
    if not (complete and healthy):
        res["verdict"] = "NOT READ: run not complete/healthy"
    elif reading not in ("A", "B"):
        res["verdict"] = "NOT READ: the owner's choice of the Q-a bar reading (A or B) is not recorded"
    else:
        res["verdict"] = f"{by[reading]} (Q-a reading {reading})"
    return res


def cmd_summarize(a) -> int:
    rows = json.loads(Path(a.rows).read_text())
    qrels = json.loads(QA_QRELS.read_text())["topics"]
    planned = {"QT": 120, "QD": 100, "QA": 240, "QA_pipeline": 240}
    if "tomb_ids" not in rows:
        try:
            rows["tomb_ids"] = sorted(ledger_truth(Path(rows["preview"]["delta_root"]))["tomb"])
        except Exception:
            rows["tomb_ids"] = []
    m_set = drift_m_set()
    f2 = compute_f2(rows, qrels, m_set, reference_r_vs_a0(), planned, a.bar_reading,
                    getattr(a, "q_b_level", "shard_and_federated"))
    rec = {"item": "doc 10 F2 quality parity of the fold", "date_utc": utc(),
           "script": "scripts/experiments/eval_delta_ingest_foldin.py", "preregistration":
           "docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md §6", "rows_file": str(a.rows),
           "git_head_measured": rows.get("git_head"), "bar_reading": a.bar_reading, "log_scan": None,
           "m_set_source": m_set.get("source"),
           **{k: rows.get(k) for k in ("start_utc", "end_utc", "wall_s", "lock", "preview", "queries_sha256", "search",
                                       "ledger", "arms", "health", "selfcheck", "mem", "stop", "limit")}, **f2}
    if a.log and Path(a.log).exists():
        rec["log_scan"] = load_m4f().M4.scan_log(Path(a.log))
    res = Path(a.out or REPO / f"data/eval_results/delta_ingest_foldin_{time.strftime('%Y%m%d', time.gmtime())}.json")
    data = json.loads(res.read_text()) if res.exists() else {}
    data[a.key] = rec
    res.write_text(json.dumps(data, indent=1, default=str) + "\n")
    print(json.dumps({k: rec[k] for k in ("verdict", "verdict_by_reading", "done", "complete", "healthy")}
                     | {"Q_a": rec["Q_a"], "Q_b": {s: {k: v for k, v in x.items() if k != "reference_R_vs_A0"}
                                                   | {"reference": x["reference_R_vs_A0"]["overlap10_mean"]}
                                                   for s, x in rec["Q_b"].items()},
                        "Q_c_final": rec["Q_c"]["final"], "Q_c_pass": rec["Q_c"]["pass"],
                        "Q_d": {k: v for k, v in rec["Q_d"].items() if k != "leak_examples_F"}}, indent=1))
    return 0


def cmd_run(a) -> int:
    m4f = load_m4f()
    env = {k: v for k, v in os.environ.items() if k not in UNSET_ENV}
    env.update({k: "" for k in (*m4f.M4.ENV_DROP, *BLANK_ENV)})
    env.update(m4f.MODEL_ENV)
    env.update(SFU_SEISMIC_FEDERATION="parallel", SFU_SEISMIC_PREFLOOR="2")
    WORK.mkdir(parents=True, exist_ok=True)
    rows, logp = Path(a.rows_out), Path(a.log or WORK / "measure.log")
    argv = [sys.executable, __file__, "measure", "--delta-root", a.delta_root, "--preview-root", a.preview_root,
            "--rows-out", str(rows), "--lock", a.lock, "--lock-giveup-s", str(a.lock_giveup_s), "--limit", str(a.limit)]
    if a.deadline:
        argv += ["--deadline", a.deadline]
    with open(logp, "w") as fh:
        rc = subprocess.run(argv, cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    log(f"measure rc={rc} log={logp}")
    a.rows, a.log = str(rows), str(logp)
    cmd_summarize(a)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="doc 10 fold-in harness: F2 parity + F4 build recorder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("encode")
    b = sub.add_parser("build")
    b.add_argument("--delta-root", default=str(FIXTURE))
    b.add_argument("--shard", type=int, default=0)
    b.add_argument("--fold-input", required=True)
    b.add_argument("--token-map-dir", required=True)
    b.add_argument("--fold-root", default=str(FOLD_ROOT))
    b.add_argument("--fold-workers", type=int, default=8)
    b.add_argument("--profile", default="desktop_gpu")
    b.add_argument("--seismic-threads", type=int, default=8)
    b.add_argument("--base-manifest", default="/home/vscode/work/inplace_update/m4/base_manifest.json")
    b.add_argument("--lock", choices=["exclusive", "shared", "none"], default="exclusive")
    b.add_argument("--lock-giveup-s", type=float, default=4 * 3600)
    b.add_argument("--log", default="")
    b.add_argument("--out", default="")
    b.add_argument("--key", default="F4_build")
    p = sub.add_parser("preview")
    for s in (p,):
        s.add_argument("--delta-root", default=str(FIXTURE))
        s.add_argument("--shard", type=int, default=0)
        s.add_argument("--fold", type=int, default=None)
        s.add_argument("--fold-root", default=str(FOLD_ROOT))
        s.add_argument("--preview-root", default=str(WORK / "preview_root"))
    for name in ("measure", "run"):
        m = sub.add_parser(name)
        m.add_argument("--delta-root", default=str(FIXTURE))
        m.add_argument("--preview-root", default=str(WORK / "preview_root"))
        m.add_argument("--rows-out", default=str(WORK / "rows.json"))
        m.add_argument("--lock", choices=["shared", "exclusive", "none"], default="shared")
        m.add_argument("--lock-giveup-s", type=float, default=4 * 3600)
        m.add_argument("--deadline", default="")
        m.add_argument("--limit", type=int, default=0, help="first N queries per set (smoke; verdict NOT READ)")
        if name == "run":
            m.add_argument("--log", default="")
            m.add_argument("--out", default="")
            m.add_argument("--key", default="F2")
            m.add_argument("--bar-reading", choices=["A", "B"], default=None)
            m.add_argument("--q-b-level", choices=["shard_and_federated", "federated"], default="shard_and_federated")
    s = sub.add_parser("summarize")
    s.add_argument("--rows", default=str(WORK / "rows.json"))
    s.add_argument("--log", default="")
    s.add_argument("--out", default="")
    s.add_argument("--key", default="F2")
    s.add_argument("--bar-reading", choices=["A", "B"], default=None)
    s.add_argument("--q-b-level", choices=["shard_and_federated", "federated"], default="shard_and_federated")
    a = ap.parse_args()
    return {"encode": cmd_encode, "build": cmd_build, "preview": cmd_preview, "measure": cmd_measure,
            "run": cmd_run, "summarize": cmd_summarize}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
