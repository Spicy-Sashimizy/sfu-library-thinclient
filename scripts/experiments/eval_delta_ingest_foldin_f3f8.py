#!/usr/bin/env python3
r"""Delta-ingest fold-in F8 (reload after a fold publish) and F3 (latency
returns to n0), doc 10 §6. Written 2026-10-08 BEFORE any F3/F8 number existed.

Spec: docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md (FROZEN); its
F3/F8 rows are copied verbatim at the end of this header. Implementation
readings (arm construction, rep design) are fixed in doc 10's addendum
"2026-10-08 — F3/F8 implementation reading", committed before the run.

Subcommands (run with /home/vscode/work/venv_local/bin/python3, cwd = repo;
the launcher `/home/vscode/work/delta_ingest/foldin/f3f8/run_f3f8.sh` holds
/tmp/sfu_latency_measure.lock EXCLUSIVELY around setup -> smoke -> f8 -> f3):
  setup      COPIES of fixture_n8 (never the original) under WORK:
             root_f3 = compact gens 1-8 with --no-seismic (the consolidated
             sections tier) over the staged base manifest, mark fold 1 READY
             (F2 evidence), `cli.py publish-fold --shard 0 --fold 1 --confirm`;
             root_f8 = republish over the staged base manifest, mark fold 2
             READY (published inside `f8`, rep 1). G3 baseline snapshot saved
             before, checked after. Idempotent (per-root marker).
  f8         child: one retriever on root_f8 (L3+L4+L5 ON, parallel), M5
             metric: warm-up pass (pre-fold state); rep 1 = the real operator
             step (`cli.py publish-fold`, which prefaults s' first), reload()
             timed, first query + 9 recovery; warm-up + warm pass on the
             post-fold state (warm p50); reps 2-5 = restore the pre-fold
             files -> reload() -> 1 query (rollback, recorded) -> prefault s'
             -> restore the post-fold files -> reload() timed -> first query +
             9 recovery; 2 controls (reload without a change). --smoke = load,
             health, 3 queries, no publish.
  f3         child: `eval_delta_ingest_m4f.py inproc` (09 §1/§1.1 design:
             one process, one retriever per arm + prime, 1 warm-up + 2
             measured passes, arm order shuffled per query, quiet gate,
             memory guard) with arms n0, n0x, L, F resolved here.
  summarize  bars -> data/eval_results/delta_ingest_foldin_f3f8_<date>.json,
             keys setup, F8, F3 (raw per-query timings included).

Arms (F3):
  n0   gate off, staged base manifest (as 09's n0)
  n0x  n0 + SFU_BM25F_PARSE_ONCE (the lever of the stack that acts on the base);
       recorded, Δ(F, n0x) recorded
  L    /home/vscode/work/inplace_update/m4/root_n8c + L3,L4,L5 (09's x8c root:
       the 160,347 fold-delta docs in ONE generation with its SEISMIC shard and
       sections tier, staged base)
  F    root_f3 + L3,L4,L5: s' (fold 1) at shard position 0, staged base shards
       1-7, the same 160,347 docs as ONE generation with seismic=False (the
       consolidated sections tier), masks with the folded docs' SEISMIC origin
       fold:0:1. No delta SEISMIC shard.

---- doc 10 §6, rows F3 and F8, verbatim (frozen 2e674773) ----
| # | Question | Metric | Bar (frozen) | Lock |
|---|---|---|---|---|
| **F3** | Latency returns to n0 | `search_rrf` p50, 120 topics (M4 set), in-process arms n0, L (base + fold delta + consolidated sections tier), F (*s′* + consolidated sections tier), design and statistics = 09 §1 / §1.1 | p50(F) ≤ **1.05 × p50(n0)** AND bootstrap CI upper bound of Δ(F, n0) ≤ **+8.0 ms** (at most one generation's budget left after the fold); Δ(L, F) recorded | exclusive |
| **F8** | Reload after a fold publish | M5 metric on the F arm: `reload()` wall, first-query p50 vs warm p50, 5 reps, with the operator prefault of *s′* | the M5 bars, unchanged: reload ≤ **15 s**; first-query p50 ≤ **2 ×** warm p50 | exclusive |
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import resource
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "experiments"))
import eval_delta_ingest_m4_read_amp as m4  # noqa: E402

FOLDIN = Path("/home/vscode/work/delta_ingest/foldin")
WORK = FOLDIN / "f3f8"
SRC_FIXTURE = FOLDIN / "fixture_n8"
ROOT_F3 = WORK / "root_f3"
ROOT_F8 = WORK / "root_f8"
ROOT_L = m4.WORK / "root_n8c"
M4BASE = m4.BASE_MANIFEST
SHARD = 0
F3_FOLD = 1
F8_FOLD = 2
N_BASE = 8
LEVERS = ["L3", "L4", "L5"]
LEVER_ENV = {"L3": "SFU_DELTA_ABS_ROUTE", "L4": "SFU_BM25F_PARSE_ONCE", "L5": "SFU_SEISMIC_DELTA_GROUP"}
F2_EVIDENCE = {
    1: "data/eval_results/delta_ingest_foldin_20261003.json#F2 + #F2_qb_federated (fold 1, F2 PASS at the owner's "
       "federated Q-b level, doc 10 addendum 2026-10-04)",
    2: "data/eval_results/delta_ingest_foldin_20261004.json#F2_fold2 + #F2_fold2_qb_federated (fold 2, F2 PASS at "
       "the federated level)",
}
REPS = 5
CONTROL_REPS = 2
RECOVERY = 9
F3_BAR_RATIO = 1.05
F3_BAR_CI_MS = 8.0
F8_BAR_RELOAD_S = 15.0
F8_BAR_FIRST_RATIO = 2.0


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    print(f"[{utc()}] {msg}", flush=True)


def dump_json(path: Path, obj) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=1, default=str) + "\n")
    os.replace(tmp, path)


def git_head() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def git_dirty_spike() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "status", "--short", "--", "spike/delta_ingest", "src"],
                         capture_output=True, text=True).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def cli(args: list[str], timeout: int = 3600) -> dict:
    """Run `spike.delta_ingest.cli` as a child; return rc, wall, parsed JSON stdout."""
    t = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "spike.delta_ingest.cli", *args], cwd=str(REPO),
                       capture_output=True, text=True, timeout=timeout)
    out = None
    try:
        out = json.loads(p.stdout[p.stdout.index("{"):]) if "{" in p.stdout else None
    except ValueError:
        out = None
    return {"argv": args, "rc": p.returncode, "s": round(time.perf_counter() - t, 2), "out": out,
            "stderr_tail": p.stderr[-1500:] if p.returncode else "",
            "enomem": "Cannot allocate memory" in (p.stderr + p.stdout)}


# ── setup ───────────────────────────────────────────────────────────────────
def copy_fixture(dst: Path) -> dict:
    """Copy fixture_n8 (read-only source) to `dst`; the copy's ledger is
    checkpointed so it is self-contained."""
    if dst.exists():
        raise SystemExit(f"{dst} exists without a setup marker; inspect and remove it by hand")
    t = time.perf_counter()
    shutil.copytree(SRC_FIXTURE, dst, symlinks=True)
    db = sqlite3.connect(str(dst / "ledger.sqlite"))
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    return {"src": str(SRC_FIXTURE), "dst": str(dst), "copy_s": round(time.perf_counter() - t, 2)}


def fold_row(root: Path, fold: int) -> tuple:
    db = sqlite3.connect(f"file:{root / 'ledger.sqlite'}?mode=ro", uri=True)
    row = db.execute("SELECT state, dir, manifest, info FROM folds WHERE shard=? AND fold=?", (SHARD, fold)).fetchone()
    db.close()
    if row is None:
        raise SystemExit(f"{root}: no fold {SHARD}/{fold}")
    return row[0], row[1], row[2], json.loads(row[3] or "{}")


def mark_ready(root: Path, fold: int) -> dict:
    sys.path.insert(0, str(REPO))
    from spike.delta_ingest import foldin
    from spike.delta_ingest.ledger import IngestLedger
    led = IngestLedger(root / "ledger.sqlite")
    try:
        foldin.mark_fold_ready(led, SHARD, fold, {"F2": F2_EVIDENCE[fold], "by": "f3f8 setup, on a copy", "utc": utc()})
    finally:
        led.close()
    return {"fold": fold, "state": fold_row(root, fold)[0]}


def preset_existing_fold_manifest(root: Path, fold: int) -> dict | None:
    """A composed fold manifest is never overwritten. On a re-run of setup the
    manifest from the earlier run already exists; it is reused only if it was
    composed from the same base manifest with this fold's served dir."""
    out = FOLDIN / "manifests" / f"shard_manifest.fold_s{SHARD}_k{fold}.json"
    state, _, prev, info = fold_row(root, fold)
    if not out.exists() or prev:
        return None
    m = json.loads(out.read_text())
    recs = [r for r in m.get("shards") or [] if r.get("fold_origin") == f"fold:{SHARD}:{fold}"]
    if m.get("composed_from") != str(M4BASE) or len(recs) != 1 or recs[0].get("mmap_dir") != info.get("mmap_dir"):
        raise SystemExit(f"{out} exists and was composed from other inputs; remove it by hand after checking")
    db = sqlite3.connect(str(root / "ledger.sqlite"))
    with db:
        db.execute("UPDATE folds SET manifest=? WHERE shard=? AND fold=?", (str(out), SHARD, fold))
    db.close()
    return {"reused_manifest": str(out)}


def published_manifest(root: Path) -> dict:
    gj = json.loads((root / "generations.json").read_text())
    sm = json.loads(Path(gj["shard_manifest"]).read_text()) if gj.get("shard_manifest") else {}
    return {"stamp": gj.get("stamp"), "generations": [(g["gen"], g["docs"], g["seismic"]) for g in gj["generations"]],
            "shard_manifest": gj.get("shard_manifest"), "base_shard_manifest": gj.get("base_shard_manifest"),
            "n_shards": len(sm.get("shards") or []),
            "origins": [r.get("delta_generation") if r.get("delta_generation") is not None else r.get("fold_origin")
                        for r in sm.get("shards") or []],
            "position0_mmap_dir": (sm.get("shards") or [{}])[0].get("mmap_dir"),
            "newest_by_leg_seismic": len(((gj.get("mask") or {}).get("newest_by_leg") or {}).get("seismic") or {})}


def setup_f3(rec: dict) -> None:
    rec["copy"] = copy_fixture(ROOT_F3)
    db = sqlite3.connect(f"file:{ROOT_F3 / 'ledger.sqlite'}?mode=ro", uri=True)
    gens = [r[0] for r in db.execute("SELECT gen FROM generations WHERE state='published' ORDER BY gen")]
    db.close()
    rec["compact"] = cli(["compact", "--delta-root", str(ROOT_F3), "--gens", ",".join(map(str, gens)), "--no-seismic",
                          "--base-shard-manifest", str(M4BASE), "--profile", "desktop_gpu"])
    if rec["compact"]["rc"] != 0:
        raise SystemExit(f"compact failed: {rec['compact']['stderr_tail']}")
    rec["after_compact"] = published_manifest(ROOT_F3)
    g = rec["after_compact"]["generations"]
    if len(g) != 1 or g[0][1] != 160347 or g[0][2] != "disabled":
        raise SystemExit(f"root_f3 after compaction is not one seismic=False generation of 160,347 docs: {g}")
    rec["ready"] = mark_ready(ROOT_F3, F3_FOLD)
    rec["manifest_preset"] = preset_existing_fold_manifest(ROOT_F3, F3_FOLD)
    rec["publish_fold"] = cli(["publish-fold", "--delta-root", str(ROOT_F3), "--shard", str(SHARD), "--fold",
                               str(F3_FOLD), "--confirm", "--base-shard-manifest", str(M4BASE)])
    if rec["publish_fold"]["rc"] != 0:
        raise SystemExit(f"publish-fold failed: {rec['publish_fold']['stderr_tail']}")
    rec["after_publish_fold"] = published_manifest(ROOT_F3)
    a = rec["after_publish_fold"]
    if a["n_shards"] != N_BASE or a["origins"][0] != f"fold:{SHARD}:{F3_FOLD}" or any(a["origins"][1:]):
        raise SystemExit(f"root_f3 after publish-fold: unexpected served shards {a['origins']}")


def setup_f8(rec: dict) -> None:
    rec["copy"] = copy_fixture(ROOT_F8)
    rec["publish"] = cli(["publish", "--delta-root", str(ROOT_F8), "--base-shard-manifest", str(M4BASE)])
    if rec["publish"]["rc"] != 0:
        raise SystemExit(f"publish failed: {rec['publish']['stderr_tail']}")
    rec["after_publish"] = published_manifest(ROOT_F8)
    a = rec["after_publish"]
    if a["n_shards"] != N_BASE + 8 or any(a["origins"][:N_BASE]) or a["base_shard_manifest"] != str(M4BASE):
        raise SystemExit(f"root_f8 pre-fold state unexpected: {a}")
    rec["ready"] = mark_ready(ROOT_F8, F8_FOLD)
    rec["manifest_preset"] = preset_existing_fold_manifest(ROOT_F8, F8_FOLD)


def cmd_setup(a) -> int:
    sys.path.insert(0, str(REPO))
    from spike.delta_ingest import foldin
    WORK.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(WORK).free / 1e9
    if free < 20:
        raise SystemExit(f"only {free:.1f} GB free under {WORK}")
    for p in (SRC_FIXTURE / "generations.json", ROOT_L / "generations.json", M4BASE):
        if not p.exists():
            raise SystemExit(f"missing {p}")
    bfile = WORK / "baseline_before.json"
    if not bfile.exists():
        dump_json(bfile, {"utc": utc(), "roots": [str(r) for r in foldin.default_baseline_roots()],
                          "snapshot": foldin.baseline_snapshot(foldin.default_baseline_roots())})
    before = json.loads(bfile.read_text())["snapshot"]
    out = {"utc": utc(), "git_head": git_head(), "git_dirty_spike_src": git_dirty_spike(), "roots": {}}
    for name, fn in (("root_f3", setup_f3), ("root_f8", setup_f8)):
        marker = WORK / f"{name}.setup.json"
        if marker.exists():
            out["roots"][name] = {"skipped": "marker exists", **json.loads(marker.read_text())}
            continue
        rec = {"utc_start": utc()}
        fn(rec)
        rec["utc_end"] = utc()
        dump_json(marker, rec)
        out["roots"][name] = rec
        log(f"setup {name} done")
    out["baseline_after_setup"] = foldin.baseline_check(before, foldin.default_baseline_roots())
    dump_json(WORK / "setup.json", out)
    print(json.dumps({k: (v if k != "roots" else {n: {kk: vv for kk, vv in r.items() if kk in
                      ("after_publish_fold", "after_publish", "skipped")} for n, r in v.items()})
                      for k, v in out.items()}, indent=1, default=str))
    return 0


# ── F8 ──────────────────────────────────────────────────────────────────────
def state_files(root: Path) -> list[Path]:
    """The files a reader keys off: generations.json, the composed manifest it
    names, and the livedocs bitset it names (if any). Order = restore order
    (generations.json LAST, as publish writes it)."""
    gj = json.loads((root / "generations.json").read_text())
    out = []
    if gj.get("shard_manifest"):
        out.append(Path(gj["shard_manifest"]))
    lv = gj.get("livedocs") or {}
    if lv.get("path"):
        p = Path(lv["path"])
        out.append(p if p.is_absolute() else root / p)
    out.append(root / "generations.json")
    return out


def snapshot_state(root: Path, dst: Path) -> dict:
    dst.mkdir(parents=True, exist_ok=True)
    files = []
    for i, p in enumerate(state_files(root)):
        c = dst / f"{i:02d}_{p.name}"
        shutil.copy2(p, c)
        files.append({"path": str(p), "copy": str(c)})
    rec = {"stamp": json.loads((root / "generations.json").read_text()).get("stamp"), "files": files}
    dump_json(dst / "state.json", rec)
    return rec


def restore_state(snap: dict) -> None:
    for f in snap["files"]:
        tmp = Path(f["path"] + f".restore-{os.getpid()}")
        shutil.copy2(f["copy"], tmp)
        os.replace(tmp, f["path"])


def cmd_f8(a) -> int:
    import logging
    t_start = time.time()
    host0 = m4.host_state()
    sys.path.insert(0, a.src)
    sys.path.insert(1, str(REPO))
    cap = m4._WarnCapture()
    logging.getLogger().addHandler(cap)
    health: dict = {"ok": True, "problems": []}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    root = Path(os.environ.get("SFU_DELTA_ROOT") or "")
    out = {"root": str(root), "fold": F8_FOLD, "pid": os.getpid(), "host_start": host0, "health": health,
           "smoke": a.smoke, "src": a.src,
           "env": {k: os.environ.get(k) for k in sorted(os.environ) if k.startswith("SFU_") and
                   not any(s in k for s in ("KEY", "TOKEN", "AUTH", "SECRET", "PASS"))}}
    if root.resolve() != ROOT_F8.resolve():
        bad(f"SFU_DELTA_ROOT={root} is not {ROOT_F8}")
    for lv, var in LEVER_ENV.items():
        if os.environ.get(var) != "1":
            bad(f"{var} is not 1 (fallback stack lever {lv})")
    if os.environ.get("SFU_SEISMIC_STAGE_DIR") or os.environ.get("SFU_META_STAGE_DIR") \
            or os.environ.get("SFU_SEISMIC_SHARD_MANIFEST"):
        bad("a stage dir or an explicit shard manifest is set in the child env")
    state, fdir, _, finfo = fold_row(ROOT_F8, F8_FOLD)
    s_prime = Path(finfo.get("mmap_dir") or "")
    if state != "ready":
        bad(f"fold {SHARD}/{F8_FOLD} on {ROOT_F8} is {state}, expected ready (unpublished)")
    if not health["ok"]:
        dump_json(Path(a.rows_out), out)
        return 3
    try:
        import onnxruntime
        health["onnxruntime"] = onnxruntime.__version__
    except Exception as exc:
        bad(f"onnxruntime import failed: {exc!r}")
    import lib.tools as tools
    from lib.embedding import _load_model
    from lib.opensearch_retriever import encode_splade
    from lib.reranker import _get_cross_encoder
    from spike.delta_ingest import foldin
    retriever = tools._get_thinclient_retriever()
    if retriever is None:
        bad("not thinclient")
        dump_json(Path(a.rows_out), out)
        return 3
    retriever._fetch_remote_abstracts = lambda ids: {}
    retriever._load()
    if not encode_splade("warm up query for sparse encoder", retriever.splade_model_path):
        bad("encode_splade empty")
    if _get_cross_encoder() is None:
        bad("cross-encoder not loaded")
    if _load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None) is None:
        bad("embedding model not loaded")

    def check_backend(tag: str, folded: bool):
        b = retriever._seismic
        if b is None:
            bad(f"{tag}: backend not loaded")
            return
        if type(b).__name__ != "ParallelSeismicBackend":
            bad(f"{tag}: backend {type(b).__name__}")
        d = retriever._delta
        if len(b.shards) != N_BASE + 8 or any(s is None for s in b.shards):
            bad(f"{tag}: shards {len(b.shards)} != {N_BASE + 8}")
        if d is None or len(d.generations) != 8:
            bad(f"{tag}: delta layer generations wrong")
            return
        if getattr(retriever, "_seismic_manifest", None) != d.shard_manifest_path():
            bad(f"{tag}: served manifest is not the delta composed manifest")
        origins = d.shard_origins(len(b.shards), retriever._seismic_manifest)
        want0 = f"fold:{SHARD}:{F8_FOLD}" if folded else None
        if origins[0] != want0 or any(o is not None for o in origins[1:N_BASE]) \
                or [o for o in origins[N_BASE:]] != list(range(1, 9)):
            bad(f"{tag}: shard origins {origins} (want position 0 = {want0})")
        if getattr(b, "_delta_group", None) != list(range(N_BASE, N_BASE + 8)):
            bad(f"{tag}: L5 delta group {getattr(b, '_delta_group', None)}")
        if not (retriever._delta_abs_route and retriever._bm25f_parse_once):
            bad(f"{tag}: L3/L4 gates not on")

    retriever._seismic_backend()
    check_backend("initial", folded=False)
    if any(any(s in w for s in m4.SIGNATURES) for w in cap.records):
        bad("failure signature in warnings during load")
    out["warnings_at_load"] = list(cap.records)
    items = m4.load_topics()

    def run(q):
        ru0 = resource.getrusage(resource.RUSAGE_SELF)
        t = time.perf_counter()
        fused = retriever.search_rrf(q, top_k=m4.TOP_K)
        ms = (time.perf_counter() - t) * 1000
        return round(ms, 2), resource.getrusage(resource.RUSAGE_SELF).ru_majflt - ru0.ru_majflt, len(fused)

    if a.smoke or not health["ok"]:
        if health["ok"]:
            out["smoke_queries"] = [dict(zip(("ms", "majflt", "n"), run(q)), topic=k) for k, q in items[:3]]
        out["host_end"] = m4.host_state()
        dump_json(Path(a.rows_out), out)
        return 0 if health["ok"] else 3

    orig_backend = type(retriever)._seismic_backend
    reopen: dict = {}

    def timed_backend(self=retriever):
        was_none = self._seismic is None
        t = time.perf_counter()
        r = orig_backend(self)
        if was_none:
            reopen["s"] = time.perf_counter() - t
        return r
    retriever._seismic_backend = timed_backend

    def full_pass(tag: str) -> list:
        rows = []
        for key, q in items:
            ms, mf, n = run(q)
            rows.append({"topic": key, "ms": ms, "majflt": mf, "n": n})
        log(f"[f8] {tag} p50={m4.pct([r['ms'] for r in rows], 50)}")
        return rows

    def reload_and_query(tag: str, folded: bool, base_topic: int, n_after: int) -> dict:
        old_stamp = retriever._delta.stamp if retriever._delta else None
        reopen.clear()
        ru0 = resource.getrusage(resource.RUSAGE_SELF)
        t = time.perf_counter()
        retriever.reload()
        reload_s = time.perf_counter() - t
        dropped = retriever._seismic is None
        new_stamp = retriever._delta.stamp if retriever._delta else None
        if old_stamp == new_stamp:
            bad(f"{tag}: stamp unchanged across a state change")
        if not dropped:
            bad(f"{tag}: backend not dropped after a stamp change")
        seq = [items[(base_topic + i) % len(items)] for i in range(n_after)]
        after = []
        for i, (key, q) in enumerate(seq):
            ms, mf, n = run(q)
            after.append({"topic": key, "ms": ms, "majflt": mf, "n": n, "warm_ms": warm.get(key)})
            if i == 0:
                check_backend(tag, folded)
        return {"stamp_before": old_stamp, "stamp_after": new_stamp, "reload_s": round(reload_s, 3),
                "backend_dropped": dropped,
                "backend_reopen_s": round(reopen["s"], 3) if "s" in reopen else None,
                "reload_plus_reopen_s": round(reload_s + reopen.get("s", 0.0), 3),
                "majflt_reload": resource.getrusage(resource.RUSAGE_SELF).ru_majflt - ru0.ru_majflt,
                "first_query": after[0], "recovery": after[1:]}

    out["quiet_gate"] = m4.quiet_gate(a.quiet_wait)
    warm: dict = {}
    pre_rows = full_pass("warm-up pass, pre-fold state")
    out["warmup_pass_pre"] = {"p50_ms": m4.pct([r["ms"] for r in pre_rows], 50), "rows": pre_rows}
    pre = snapshot_state(ROOT_F8, WORK / "f8_state" / "pre")
    n_warn = len(cap.records)
    reps = []
    time.sleep(1.1)
    pub = cli(["publish-fold", "--delta-root", str(ROOT_F8), "--shard", str(SHARD), "--fold", str(F8_FOLD),
               "--confirm", "--base-shard-manifest", str(M4BASE)], timeout=1800)
    if pub["rc"] != 0:
        bad(f"rep 1: publish-fold rc={pub['rc']}: {pub['stderr_tail'][-400:]}")
        out.update(publish_fold=pub, host_end=m4.host_state())
        dump_json(Path(a.rows_out), out)
        return 3
    post = snapshot_state(ROOT_F8, WORK / "f8_state" / "post")
    r1 = reload_and_query("rep 1", True, 0, 1 + RECOVERY)
    reps.append({"rep": 1, "kind": "fold_publish_operator_step", "publish_fold": pub,
                 "prefault": (pub.get("out") or {}).get("prefault"), **r1})
    log(f"[f8] rep 1 reload={r1['reload_s']}s reopen={r1['backend_reopen_s']} first={r1['first_query']['ms']}ms")
    post_rows_w = full_pass("warm-up pass, post-fold state")
    post_rows = full_pass("warm pass, post-fold state")
    warm.update({r["topic"]: r["ms"] for r in post_rows})
    for r in reps:
        for x in [r["first_query"], *r["recovery"]]:
            x["warm_ms"] = warm.get(x["topic"])
    out["warmup_pass_post"] = {"p50_ms": m4.pct([r["ms"] for r in post_rows_w], 50), "rows": post_rows_w}
    out["warm_pass"] = {"p50_ms": m4.pct([r["ms"] for r in post_rows], 50),
                        "p95_ms": m4.pct([r["ms"] for r in post_rows], 95),
                        "majflt_mean": round(statistics.fmean([r["majflt"] for r in post_rows]), 1),
                        "rows": post_rows}
    for rep in range(2, REPS + 1):
        if not health["ok"]:
            break
        time.sleep(1.1)
        restore_state(pre)
        rb = reload_and_query(f"rep {rep} rollback", False, (rep - 1) * 24 + 12, 1)
        pf = foldin.prefault_dir(s_prime)
        time.sleep(1.1)
        restore_state(post)
        rr = reload_and_query(f"rep {rep}", True, (rep - 1) * 24, 1 + RECOVERY)
        reps.append({"rep": rep, "kind": "fold_republish_from_snapshot", "rollback": rb, "prefault": pf, **rr})
        log(f"[f8] rep {rep} reload={rr['reload_s']}s reopen={rr['backend_reopen_s']} "
            f"first={rr['first_query']['ms']}ms warm={rr['first_query']['warm_ms']}")
    for c in range(CONTROL_REPS):
        if not health["ok"]:
            break
        reopen.clear()
        t = time.perf_counter()
        retriever.reload()
        rs = time.perf_counter() - t
        key, q = items[(c * 24 + 6) % len(items)]
        ms, mf, n = run(q)
        reps.append({"rep": REPS + 1 + c, "kind": "control_no_change", "reload_s": round(rs, 3),
                     "backend_dropped": retriever._seismic is None,
                     "first_query": {"topic": key, "ms": ms, "majflt": mf, "n": n, "warm_ms": warm.get(key)}})
    warn_meas = cap.records[n_warn:]
    if any(any(s in w for s in m4.SIGNATURES) for w in warn_meas):
        bad("failure signature in warnings during reps")
    out.update({"pre_state": pre, "post_state": post, "warnings_during_reps": warn_meas[:50], "reps": reps,
                "host_end": m4.host_state(), "wall_s": round(time.time() - t_start, 1)})
    dump_json(Path(a.rows_out), out)
    return 0 if health["ok"] else 3


def summarize_f8(rec: dict) -> dict:
    main = [r for r in rec.get("reps", []) if r["kind"] != "control_no_change"]
    ctrl = [r for r in rec.get("reps", []) if r["kind"] == "control_no_change"]
    ok = bool(rec.get("health", {}).get("ok")) and len(main) == REPS and "warm_pass" in rec
    res = {"status": "COMPLETE" if ok else "PARTIAL/INVALID", "health": rec.get("health"), "root": rec.get("root"),
           "fold": rec.get("fold"), "src": rec.get("src"), "wall_s": rec.get("wall_s")}
    if not main or "warm_pass" not in rec:
        return {**res, "verdict": "NOT READ"}
    warm_p50 = rec["warm_pass"]["p50_ms"]
    first = [r["first_query"]["ms"] for r in main]
    rl = [r["reload_s"] for r in main]
    paired = [r["first_query"]["ms"] / r["first_query"]["warm_ms"] for r in main if r["first_query"].get("warm_ms")]
    first_p50 = statistics.median(first)
    v_reload = "PASS" if max(rl) <= F8_BAR_RELOAD_S else "FAIL"
    v_first = "PASS" if first_p50 <= F8_BAR_FIRST_RATIO * warm_p50 else "FAIL"
    res.update({
        "warm_p50_ms_post_fold": warm_p50, "warm_p95_ms_post_fold": rec["warm_pass"]["p95_ms"],
        "warmup_pass_p50_ms_pre_fold": rec.get("warmup_pass_pre", {}).get("p50_ms"),
        "warmup_pass_p50_ms_post_fold": rec.get("warmup_pass_post", {}).get("p50_ms"),
        "reload_s": rl, "reload_s_max": max(rl), "reload_s_median": statistics.median(rl),
        "backend_reopen_s": [r["backend_reopen_s"] for r in main],
        "reload_plus_reopen_s": [r["reload_plus_reopen_s"] for r in main],
        "backend_dropped_all": all(r["backend_dropped"] for r in main),
        "first_query_ms": first, "first_query_p50_ms": round(first_p50, 2),
        "first_query_ratio_vs_warm_p50": round(first_p50 / warm_p50, 3),
        "first_query_paired_ratio_vs_same_topic_warm": [round(x, 3) for x in paired],
        "first_query_paired_ratio_median": round(statistics.median(paired), 3) if paired else None,
        "recovery_p50_ms_queries_2_to_10": m4.pct([x["ms"] for r in main for x in r["recovery"]], 50),
        "majflt_first_query": [r["first_query"]["majflt"] for r in main],
        "prefault": [r.get("prefault") for r in main],
        "publish_fold_cli_s": (main[0].get("publish_fold") or {}).get("s"),
        "rollback_reload_s": [r["rollback"]["reload_s"] for r in main if r.get("rollback")],
        "rollback_first_query_ms": [r["rollback"]["first_query"]["ms"] for r in main if r.get("rollback")],
        "controls_no_change": [{"reload_s": r["reload_s"], "backend_dropped": r["backend_dropped"],
                                "first_query_ms": r["first_query"]["ms"]} for r in ctrl],
        "bars": {"reload_le_15s": v_reload, "first_query_p50_le_2x_warm_p50": v_first},
        "verdict": ("PASS" if v_reload == v_first == "PASS" else "FAIL") if ok else "NOT READ (run not complete/healthy)",
        "quiet_gate": {k: v for k, v in (rec.get("quiet_gate") or {}).items() if k != "samples"},
        "host_start": rec.get("host_start"), "host_end": rec.get("host_end"),
        "reps": rec.get("reps"),
        "raw_warm_pass_post_fold": [(r["topic"], r["ms"]) for r in rec["warm_pass"].get("rows", [])],
    })
    return res


# ── F3 ──────────────────────────────────────────────────────────────────────
def _load_m4f():
    spec = importlib.util.spec_from_file_location("m4f", REPO / "scripts/experiments/eval_delta_ingest_m4f.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


F3_ARMS = {
    "n0": {"root": None, "levers": [], "n_seismic": 0, "n_gens": 0, "fold_positions": []},
    "n0x": {"root": None, "levers": ["L4"], "n_seismic": 0, "n_gens": 0, "fold_positions": []},
    "L": {"root": str(ROOT_L), "levers": LEVERS, "n_seismic": 1, "n_gens": 1, "fold_positions": []},
    "F": {"root": str(ROOT_F3), "levers": LEVERS, "n_seismic": 0, "n_gens": 1, "fold_positions": [SHARD]},
}


def resolve_f3(name: str, layout: str = "per_base_section", x_levers: tuple = ()) -> dict:
    a = F3_ARMS[name]
    return {"name": name, "tag": None if a["root"] is None else name, "root": a["root"], "n_gen": a["n_seismic"],
            "n_seismic": a["n_seismic"], "n_gens": a["n_gens"], "levers": sorted(a["levers"]),
            "fold_positions": list(a["fold_positions"])}


def make_open_arm_f3(M4F):
    """09's `open_arm` generalised to a fold position and a generation with no
    SEISMIC shard: delta SEISMIC positions = int origins, fold positions =
    "fold:s:k" origins (base-like, not in the L5 group)."""
    def open_arm_f3(spec: dict, cfg) -> tuple:
        from lib.thinclient.retriever import ThinClientRetriever
        probs = []
        os.environ["SFU_SEISMIC_FEDERATION"] = "parallel"
        os.environ["SFU_DELTA_ROOT"] = spec["root"] or ""
        os.environ["SFU_SEISMIC_SHARD_MANIFEST"] = "" if spec["root"] else str(M4F.BASE_MANIFEST)
        for lv, var in LEVER_ENV.items():
            os.environ[var] = "1" if lv in spec["levers"] else ""
        try:
            r = ThinClientRetriever(index_root=cfg.thinclient_index_root, splade_model_path=cfg.splade_model_path,
                                    openalex_mailto=cfg.openalex_mailto, query_log_path="",
                                    openalex_api_key=cfg.openalex_api_key, remote_abstract_fetcher=None)
            r._fetch_remote_abstracts = lambda ids: {}
            t0 = time.perf_counter()
            r._load()
            load_s = time.perf_counter() - t0
            t0 = time.perf_counter()
            try:
                b = r._seismic_backend()
            except Exception as exc:
                return r, None, [f"{spec['name']}: backend load raised {exc!r}"], {}
        finally:
            for var in LEVER_ENV.values():
                os.environ[var] = ""
            os.environ["SFU_DELTA_ROOT"] = ""
            os.environ["SFU_SEISMIC_SHARD_MANIFEST"] = ""
        name = spec["name"]
        n_seis = spec.get("n_seismic", spec["n_gen"])
        if type(b).__name__ != "ParallelSeismicBackend":
            probs.append(f"{name}: backend {type(b).__name__} != ParallelSeismicBackend")
        if len(b.shards) != N_BASE + n_seis or any(x is None for x in b.shards):
            probs.append(f"{name}: shards {len(b.shards)} != {N_BASE + n_seis}")
        d = r._delta
        origins = d.shard_origins(len(b.shards), r._seismic_manifest) if d is not None else [None] * len(b.shards)
        seis_pos = [i for i, o in enumerate(origins) if isinstance(o, int) and not isinstance(o, bool)]
        fold_pos = [i for i, o in enumerate(origins) if isinstance(o, str)]
        info = {"spec": spec, "load_s": round(load_s, 2), "backend_load_s": round(time.perf_counter() - t0, 2),
                "backend_class": type(b).__name__, "n_shards": len(b.shards), "sections": len(r._sections),
                "abstract_stores": len(r._abstract_stores), "origins": origins,
                "gates": {"L3": r._delta_abs_route, "L4": r._bm25f_parse_once,
                          "L5": getattr(b, "_delta_group", None)},
                "delta_shard_positions": seis_pos, "fold_positions": fold_pos}
        if r._delta_abs_route != ("L3" in spec["levers"]):
            probs.append(f"{name}: L3 gate {r._delta_abs_route} != spec")
        if r._bm25f_parse_once != ("L4" in spec["levers"]):
            probs.append(f"{name}: L4 gate {r._bm25f_parse_once} != spec")
        want_group = (seis_pos or None) if "L5" in spec["levers"] else None
        if getattr(b, "_delta_group", None) != want_group:
            probs.append(f"{name}: L5 group {getattr(b, '_delta_group', None)} != {want_group}")
        if fold_pos != spec.get("fold_positions", []):
            probs.append(f"{name}: fold positions {fold_pos} != {spec.get('fold_positions')}")
        if spec["root"] is None:
            if d is not None:
                probs.append(f"{name}: delta layer loaded on a gate-off arm")
        elif d is None:
            probs.append(f"{name}: delta layer not loaded")
        else:
            info.update({"delta_generations": [g["gen"] for g in d.generations], "delta_stamp": d.stamp,
                         "delta_manifest": d.shard_manifest_path(), "buffer_size": d.buffer_size(),
                         "delta_sections": sum(1 for s in r._sections.values() if "delta_origin" in s),
                         "livedocs": d.livedocs is not None, "deleted": len(d.deleted),
                         "superseded": len(d.superseded), "seismic_newest": len(d.seismic_newest)})
            if len(d.generations) != spec.get("n_gens", spec["n_gen"]):
                probs.append(f"{name}: generations {len(d.generations)} != {spec.get('n_gens')}")
            if len(seis_pos) != n_seis:
                probs.append(f"{name}: delta shard positions {len(seis_pos)} != {n_seis}")
            if getattr(r, "_seismic_manifest", None) != d.shard_manifest_path():
                probs.append(f"{name}: served manifest is not the delta composed manifest")
            if d.buffer_size() != 0:
                probs.append(f"{name}: delta buffer holds {d.buffer_size()} docs")
            if fold_pos:
                recs = json.loads(Path(d.shard_manifest_path()).read_text())["shards"]
                fm = fold_row(Path(spec["root"]), F3_FOLD)[3].get("mmap_dir")
                if recs[fold_pos[0]].get("mmap_dir") != fm:
                    probs.append(f"{name}: fold position serves {recs[fold_pos[0]].get('mmap_dir')} != {fm}")
                if not d.seismic_newest:
                    probs.append(f"{name}: no folded doc carries a fold SEISMIC origin")
        return r, b, probs, info
    return open_arm_f3


def cmd_f3(a) -> int:
    M4F = _load_m4f()
    M4F.resolve_arm = resolve_f3
    M4F.open_arm = make_open_arm_f3(M4F)
    ns = argparse.Namespace(run="F3", arms=",".join(F3_ARMS), layout="per_base_section", levers="",
                            passes=a.passes, warmup=a.warmup, rows_out=a.rows_out, limit_topics=a.limit_topics,
                            src=a.src, quiet_wait=a.quiet_wait, inline_wait=a.inline_wait, seed=M4F.SEED,
                            deadline=a.deadline)
    return M4F.inproc(ns)


def summarize_f3(rows_path: Path, commit: str, log_path: str, passes: int) -> dict:
    M4F = _load_m4f()
    tmp = WORK / "f3" / "m4f_summary.json"
    if tmp.exists():
        tmp.unlink()
    M4F.summarize(argparse.Namespace(rows=str(rows_path), out=str(tmp), key="F3", commit=commit, log=log_path,
                                     passes=passes))
    base = json.loads(tmp.read_text())["F3"]
    rec = json.loads(rows_path.read_text())
    mp = [ps for ps in rec.get("passes", []) if ps["kind"] == "measured"]
    rows = [dict(r, **{"pass": ps["pass"]}) for ps in mp for r in ps["rows"] if not r.get("prime")]
    units = M4F._units(rows)
    p50 = {k: v["p50_ms"] for k, v in base["arms"].items()}
    d_f_n0 = M4F.paired_diff(units, "F", "n0")
    diffs = {"F_minus_n0": d_f_n0, "L_minus_F": M4F.paired_diff(units, "L", "F"),
             "F_minus_n0x": M4F.paired_diff(units, "F", "n0x"), "L_minus_n0": M4F.paired_diff(units, "L", "n0"),
             "n0x_minus_n0": M4F.paired_diff(units, "n0x", "n0")}
    complete = base["status"] == "COMPLETE"
    ratio = round(p50["F"] / p50["n0"], 4) if p50.get("F") and p50.get("n0") else None
    b1 = ratio is not None and ratio <= F3_BAR_RATIO
    hi = d_f_n0["ci95"][1] if d_f_n0["ci95"] else None
    b2 = hi is not None and hi <= F3_BAR_CI_MS
    bars = {"p50_F_over_p50_n0": ratio, "ratio_bar": F3_BAR_RATIO, "ratio_ok": b1,
            "ci_upper_F_minus_n0_ms": hi, "ci_bar_ms": F3_BAR_CI_MS, "ci_ok": b2,
            "verdict": ("PASS" if b1 and b2 else "FAIL") if complete else "NOT READ (run not complete/healthy)"}
    raw = [[r["pass"], r["topic"], r["arm"], r["ms"]] for r in rows]
    return {**base, "item": "doc 10 F3 latency returns to n0", "harness": "scripts/experiments/eval_delta_ingest_foldin_f3f8.py",
            "design": "09 §1/§1.1 via eval_delta_ingest_m4f.py inproc", "arms_defined": F3_ARMS,
            "paired_differences": diffs, "bars": bars, "raw_rows_pass_topic_arm_ms": raw}


def cmd_summarize(a) -> int:
    sys.path.insert(0, str(REPO))
    from spike.delta_ingest import foldin
    out_path = Path(a.out)
    full = json.loads(out_path.read_text()) if out_path.exists() else {
        "measurement": "doc 10 §6 F3 + F8 (docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md)",
        "harness": "scripts/experiments/eval_delta_ingest_foldin_f3f8.py",
        "launcher": str(WORK / "run_f3f8.sh")}
    full["git_head_launch"] = a.commit
    full["date_utc"] = time.strftime("%Y-%m-%d", time.gmtime())
    if (WORK / "setup.json").exists():
        full["setup"] = json.loads((WORK / "setup.json").read_text())
    bfile = WORK / "baseline_before.json"
    if bfile.exists():
        try:
            full["baseline_end"] = foldin.baseline_check(json.loads(bfile.read_text())["snapshot"],
                                                         foldin.default_baseline_roots())
        except Exception as exc:
            full["baseline_end"] = {"error": repr(exc)}
    f8 = WORK / "f8" / "rows.json"
    if f8.exists():
        full["F8"] = {**summarize_f8(json.loads(f8.read_text())), "rows_file": str(f8), "git_head": a.commit}
    f3 = WORK / "f3" / "rows.json"
    if f3.exists():
        full["F3"] = {**summarize_f3(f3, a.commit, str(WORK / "f3" / "child.log"), a.passes), "rows_file": str(f3),
                      "git_head": a.commit}
    dump_json(out_path, full)
    print(json.dumps({k: ({kk: vv for kk, vv in v.items() if kk in ("status", "verdict", "bars", "reload_s",
                                                                       "first_query_p50_ms", "warm_p50_ms_post_fold")}
                          if isinstance(v, dict) and k in ("F3", "F8") else None)
                      for k, v in full.items() if k in ("F3", "F8")}, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    f8 = sub.add_parser("f8")
    f8.add_argument("--rows-out", required=True)
    f8.add_argument("--src", default=str(REPO / "src"))
    f8.add_argument("--smoke", action="store_true")
    f8.add_argument("--quiet-wait", type=int, default=600)
    f3 = sub.add_parser("f3")
    f3.add_argument("--rows-out", required=True)
    f3.add_argument("--src", default=str(REPO / "src"))
    f3.add_argument("--passes", type=int, default=2)
    f3.add_argument("--warmup", type=int, default=1)
    f3.add_argument("--limit-topics", type=int, default=0)
    f3.add_argument("--quiet-wait", type=int, default=900)
    f3.add_argument("--inline-wait", type=int, default=120)
    f3.add_argument("--deadline", default="")
    s = sub.add_parser("summarize")
    s.add_argument("--out", required=True)
    s.add_argument("--commit", default="")
    s.add_argument("--passes", type=int, default=2)
    a = ap.parse_args()
    return {"setup": cmd_setup, "f8": cmd_f8, "f3": cmd_f3, "summarize": cmd_summarize}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
