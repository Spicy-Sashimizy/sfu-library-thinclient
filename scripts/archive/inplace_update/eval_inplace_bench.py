#!/usr/bin/env python3
# CLOSED MEASURED 2026-09-30 — in-place bit-update spike harness (docs/archive/inplace_update/); evidence kept, pre-registered bars live in source
"""In-place bit updater, Stage 1 benchmark harness: bars B2-B7, arms A0/A1/A2/A2b/A3
(+ supplementary A2-2p, A2b-2p). Written 2026-09-29 BEFORE any measured run.

Bars (verbatim from docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md, Stage 1 table,
commit 8c239e99; frozen):

  | **B2 apply cost** | wall time and device bytes written (`/proc/<pid>/io`
  `write_bytes`, incl. fsync) to apply Q1: A2 (batches + epoch flip) vs A1 N=1
  (generation build from cached vectors, SEISMIC chain + tantivy/meta) vs A3
  (dump + build + c1a + dotvbyte); 3 reps, median | A2 <= A1(N=1) on BOTH wall
  time and bytes written | PASS both; PARTIAL one of the two; FAIL neither. A3
  recorded |
  | **B3 query latency** | `search_rrf` p50 and p95 over QT, top_k = 50,
  serving flags, per §"Latency discipline", arms A0 / A1 (N = 1, 4, 8) / A2 /
  A3, parallel AND sequential backend | A2 p50 <= 1.05 x A0 p50 AND A2 p95 <=
  1.05 x A0 p95, on each backend | PASS all four; PARTIAL p50 both backends but
  a p95 misses; FAIL otherwise. A1 recorded (cross-check vs M4) |
  | **B4 storage** | bytes (st_size and allocated st_blocks x 512) of every
  file the arm serves for shard 0 incl. side files, after Q1 and after Q1-Q4;
  A1 reported SEISMIC-only and full generation | report | RECORDED (no bar) |
  | **B5 publish** | A2: wall time of the epoch flip until a new query sees
  epoch e+1; A1: `reload_index` drop + re-mmap until the first query returns
  (= M5's quantity); 5 reps each. Residency of shard-0 files (`mincore`)
  before vs after publish | timing: report. Residency: A2 keeps >= 99 % of
  resident pages and does not re-mmap | residency PASS/FAIL; timing RECORDED |
  | **B6 quality** | overlap@10(A2, A3) on each of QA, QT, QD; NDCG@10 on QA
  for A1 (N=1), A2, A3; paired bootstrap CI of mean(NDCG_A2 - NDCG_A1) |
  overlap@10(A2, A3) >= 0.99 on each set AND the 95 % CI of dNDCG contains 0
  or lies above 0 | see "B6 dual reference" |
  | **B7 crash safety** | 100 trials on a fresh copy at epoch e: SIGKILL the
  updater at a uniform-random time in [0, T_apply]; reopen with the v3
  decoder; (a) header epoch in {e, e+1}, e+1 only if the flip completed; (b)
  QT top-k' ids and scores bit-identical to a clean reference at that epoch;
  (c) a concurrent reader process querying QT in a loop during the batch
  returns results identical to the epoch-e reference until the flip, with zero
  decode errors or crashes | 100/100 trials satisfy (a), (b), (c) | PASS
  100/100; otherwise FAIL with the failing trials listed. |

Addenda read with them (same file): first (B7 power-loss arm, 100/100 on BOTH
arms; write order data, sync, header, sync; dead-at-epoch rule), second (A2b
supplementary, own column), third (A2 stays ONE flip; A2-2p two-phase variant
with sub-variants old-at-free / old-at-fill, gap and overlap at e+1 and e+2;
per-flip readings of B7(a) {e, e+1, e+2}, B2 both flips incl. reader-table
wait, B5 each flip + batch start to inserts visible; reader registration with
re-read; A2b primary one flip), fourth (documents offered / placed / unplaced
and postings inserted / dropped / evicted per arm; B6 on the full offered set;
power loss: model (i) every un-synced write lost AND model (ii) each un-synced
4 KiB page kept with p = 0.5, both 100/100; hybrid rule NOT applied (recorded
deviation); B2 reports device bytes AND logical bytes).

What this harness measures and how (fixed before any run):
- Doc set ("Q1 sample"): the Stage-0 ENCODED SUBSAMPLE, not the full quarter:
  every `partsout/*.npz` (non-route) under /home/vscode/work/inplace_update/
  stage0 at copy time (records: in-slice routed docs sampled at the per-file
  encode rate, their SPLADE vectors in token ids), plus every deletion of
  `deleted_rows_2026-06-17_2026-09-15.npz` (twin rows -> W-ids via
  shard_ids.npy; the deleted_ids file starts 2026-08-14). Copied into
  stage2/docs with a manifest (paths, sizes, sha256, UTC time). Order: all
  deletions first, then upserts by (updated_date of the part file, id).
  Quarters Q2..Q4 (B4 only): synthetic, deletions sampled uniformly from live
  base ids at Q1's deletion+update count (seed inplace-q<k>), inserts = Q1's
  vectors re-drawn with fresh ids (`synthetic_reuse: true`).
- A2 family: the Rust updater `spike/inplace_update/updater` (CLI
  `inplace-updater apply`), on a COPY of the encoder agent's v3 shard 0
  (stage2/pristine, cp --sparse=always), restored after each run from the
  pristine copy over every range of the op log. Safety rule, reuse gate and
  writer I/O are named in every report ("dead-at-epoch only, no undo record";
  readers.bin gate; MAP_SHARED atomic stores + msync/fdatasync).
- Device bytes: `ru_oublock` x 512 of the waited-for child tree
  (RUSAGE_CHILDREN delta; Linux fills it from task io write_bytes), for every
  arm, plus the updater's own /proc/self/io. Logical bytes: the updater's op
  log total (A2 family); bytes of the files created (A1, A3).
- A1 N=1: `spike/delta_ingest.generation.build_generation` of the same upserts
  (title = the encoder text, cached vectors as `sparse_field`), in a child
  process, into stage2/a1/root_rep<k>; deletions are delta masks (not built
  here; their cost is a ledger write, recorded as 0 build bytes).
- A3: twin dump minus deleted/updated rows plus the upserts -> jsonl ->
  `generation.build_seismic_shard` (G2 params, c1a, dotvbyte perdoc).
  Heavy (~20 min, ~10 GB); only with --with-a3.
- B5 A2 timing: header-write start (CLOCK_MONOTONIC, from the updater's
  progress file) to the first header poll (same clock, 1 ms poll, the
  first step of every query) that returns the new epoch; residency: mincore
  over every shard file, pages resident before the batch vs after the flip.
  The "reader" is the header poll, NOT the v3 decoder (stated in results).
- B7: SIGKILL arm (uniform time in [0, T_apply], T_apply from a clean run;
  concurrent registered reader processes: one slow reader and one that
  starts a new pass every 0.3 s so passes start during the flips) and
  power-loss arm (op log replay, models drop and pages, 100 cuts each).
  (a)/(b) are checked with the updater's EXACT reference search (`search
  --epoch published`, bit patterns of f32 scores) against clean references
  at e, e+1(, e+2) computed from a clean run; with --decoder also with the
  v3 decoder once it can read the arm's lists. (c): every registered query of
  the concurrent readers must equal the reference at the epoch it registered,
  zero errors.
- B3, B6: need the v3 decoder behind `search_rrf` (and, for A2b, the unit
  read path) plus A3; recorded NOT RUN with the missing prerequisite until
  they exist.
- Synthetic mode (--synthetic): the same procedures on a synthetic v3 shard
  built by the crate. Output goes to data/eval_results/
  inplace_b_updater_synthetic_<UTCDATE>.json with label "SYNTHETIC - not a
  bar result"; never merged into the bar file.
- 2026-09-30 additions (behaviour of every earlier code path unchanged):
  `+tail` arms (ARMS keys "<arm>+tail" -> updater arm "<arm>-tail", FORMAT_V3
  §3.R4 / rev. 6; the default arm lists stay the six base arms), the tail
  and heap-reuse fields of the apply report when the binary emits them,
  `--batches N` for b4 (default 4), `--no-heap-reuse` (A2b bump-only, for a
  before/after of R7), synth-prep `--tail-words/--tail-rows/--heap-factor`,
  and environment overrides for a run outside the queue's tree:
  INPLACE_BENCH_ROOT (work root, default stage2), INPLACE_BENCH_BIN (updater
  binary, default <root>/target/release/inplace-updater), INPLACE_BENCH_DOCS
  (batch dir, default <root>/docs), INPLACE_BENCH_TAG (results file name
  part: inplace_b_updater_<tag>_<UTCDATE>.json, e.g. "indicative_v31").

Results: data/eval_results/inplace_b_updater_<UTCDATE>.json, keys B2..B7
(the encoder agent writes B1 into inplace_b_<UTCDATE>.json; this file is
separate so neither clobbers the other).

Host discipline: run every measured subcommand under
`flock /tmp/sfu_latency_measure.lock taskset -c 0-7` with
CARGO_BUILD_JOBS=8 RAYON_NUM_THREADS=8 OMP_NUM_THREADS=8; SFU_SEISMIC_STAGE_DIR
is forced empty in every child; nothing is written outside
/home/vscode/work/inplace_update/stage2 and the results file.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import mmap
import os
import random
import resource
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path("/home/vscode/work/inplace_update")
STAGE0 = WORK / "stage0"
STAGE2 = Path(os.environ.get("INPLACE_BENCH_ROOT") or (WORK / "stage2"))
BIN = Path(os.environ.get("INPLACE_BENCH_BIN") or (STAGE2 / "target/release/inplace-updater"))
DOCS = Path(os.environ.get("INPLACE_BENCH_DOCS") or (STAGE2 / "docs"))
TWIN = REPO / "data/seismic_150m/index/plan01/global_shard0of8.mmap"
DEFAULT_V3 = WORK / "stage1/v3"
QUERIES = STAGE0 / "queries.json"
BASE_ARMS = {
    "A2": "a2",
    "A2-2p/old-at-free": "a2-2p-free",
    "A2-2p/old-at-fill": "a2-2p-fill",
    "A2b": "a2b",
    "A2b-2p/old-at-free": "a2b-2p-free",
    "A2b-2p/old-at-fill": "a2b-2p-fill",
}
TAIL_ARMS = {f"{k}+tail": f"{v}-tail" for k, v in BASE_ARMS.items()}
ARMS = {**BASE_ARMS, **TAIL_ARMS}
PRIMARY = ["A2", "A2b"]
APPLY_EXTRA_KEYS = ["docs_placed_hole", "docs_placed_tail", "tail", "tail_reserve_words", "tail_reserve_rows",
                    "tail_words_before", "tail_words_after", "tail_rows_before", "tail_rows_after", "heap_reuse",
                    "heap_reused_units", "heap_reused_bytes", "heap_bumped_bytes", "heap_superseded_bytes",
                    "heap_free_entries_before", "heap_free_bytes_before", "heap_free_entries_after",
                    "heap_free_bytes_after"]
K_PRIME = 200
UTC = datetime.now(timezone.utc).strftime("%Y%m%d")
FILES = ["posting_lists.bin", "inplace_header.bin", "block_inflation.bin", "list_dir.bin",
         "row_id_override.bin", "list_min.bin", "forward_data.bin", "posting_heap.bin", "readers.bin"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def child_env() -> dict:
    e = dict(os.environ)
    e["SFU_SEISMIC_STAGE_DIR"] = ""
    e["SFU_DELTA_ROOT"] = ""
    e["SFU_META_STAGE_DIR"] = ""
    e.setdefault("RAYON_NUM_THREADS", "8")
    return e


def out_path(synthetic: bool) -> Path:
    if os.environ.get("INPLACE_BENCH_SMOKE"):
        return STAGE2 / f"smoke_{'synthetic' if synthetic else 'real'}_{UTC}.json"
    tag = "inplace_b_updater_synthetic_" if synthetic else "inplace_b_updater_"
    if os.environ.get("INPLACE_BENCH_TAG"):
        tag = f"inplace_b_updater_{os.environ['INPLACE_BENCH_TAG']}_"
    return REPO / "data/eval_results" / f"{tag}{UTC}.json"


def merge_result(synthetic: bool, key: str, value: dict) -> Path:
    p = out_path(synthetic)
    d = json.loads(p.read_text()) if p.exists() else {}
    if synthetic:
        d["label"] = "SYNTHETIC - not a bar result"
    d.setdefault("meta", {}).update({
        "harness": "scripts/experiments/eval_inplace_bench.py",
        "plan": "docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md (frozen bars + addenda 1-4)",
        "updater": "spike/inplace_update/updater (UPDATER_DESIGN.md)",
        "git_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "written_utc": datetime.now(timezone.utc).isoformat(),
    })
    if isinstance(d.get(key), dict) and isinstance(d[key].get("arms"), dict) and isinstance(value.get("arms"), dict):
        arms = dict(d[key]["arms"])
        arms.update(value["arms"])
        value = {**value, "arms": arms}
    d[key] = value
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1))
    os.replace(tmp, p)
    return p


def host_state() -> dict:
    la = os.getloadavg()
    return {"loadavg": la, "nproc": os.cpu_count(),
            "lock_note": "run under flock /tmp/sfu_latency_measure.lock (caller)"}


def run_bin(*args, check=True, env=None, timeout=36000) -> dict:
    p = subprocess.run([str(BIN), *map(str, args)], capture_output=True, text=True, env=env or child_env(), timeout=timeout)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        out = {"error": f"no json: rc={p.returncode} stderr={p.stderr[-800:]}"}
    if check and (p.returncode != 0 or "error" in out):
        raise RuntimeError(f"{args[0]} failed: {out} {p.stderr[-800:]}")
    return out


def children_oublock() -> int:
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_oublock


# --------------------------------------------------------------- batch files

def write_batch(path: Path, recs: list[tuple[int, int, list[int], list[float]]]) -> None:
    body = bytearray()
    for op, wid, comps, vals in recs:
        start = len(body)
        body += struct.pack("<B3xIQ", op, len(comps), wid)
        body += struct.pack(f"<{len(comps)}H", *comps)
        while (len(body) - start) % 4:
            body += b"\0"
        body += struct.pack(f"<{len(vals)}f", *vals)
        while len(body) % 8:
            body += b"\0"
    h = 0xcbf29ce484222325
    for b in bytes(body):
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    hdr = struct.pack("<QIIQQ", int.from_bytes(b"SFUBAT1\0", "little"), 1, 0, len(recs), h)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(hdr + bytes(body))
    os.replace(tmp, path)


# ------------------------------------------------------------------ prep-docs

def _texts_one(name: str) -> str:
    """Encoder text + year of every encoded (sel) doc of one part file, re-read
    from the raw part (stage0/parts, read-only) with spike/inplace_update/prep
    .parse_part, for the A1 build (titles/abstracts feed BM25 sections)."""
    import numpy as np
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "source"))
    from spike.inplace_update import prep
    z = np.load(DOCS / name, allow_pickle=True)
    want = {int(z["num"][i]) for i in z["sel"]}
    raw = STAGE0 / "parts" / ("works_" + name[:-4] + ".gz")
    _, recs = prep.parse_part(raw, 2010)
    got = {r["id"]: (r["text"] or "", r["year"]) for r in recs if r["id"] in want}
    ids = sorted(want)
    np.savez(DOCS / (name[:-4] + ".texts.npz"), ids=np.array(ids, dtype=np.int64),
             texts=np.array([got.get(i, ("", None))[0] for i in ids], dtype=object),
             years=np.array([got.get(i, ("", None))[1] or 0 for i in ids], dtype=np.int64))
    return f"{name}: {len(got)}/{len(want)} texts"


def cmd_prep_docs(a):
    import numpy as np
    DOCS.mkdir(parents=True, exist_ok=True)
    src_parts = sorted(p for p in (STAGE0 / "partsout").glob("*.npz") if not p.name.endswith(".route.npz"))
    copied = []
    for p in src_parts + [STAGE0 / "deleted_rows_2026-06-17_2026-09-15.npz", STAGE0 / "shard_ids.npy", QUERIES]:
        dst = DOCS / p.name
        shutil.copy2(p, dst)
        copied.append({"src": str(p), "bytes": dst.stat().st_size,
                       "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
                       "src_mtime_utc": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()})
    from multiprocessing import Pool
    with Pool(1) as pool:
        for msg in pool.imap_unordered(_texts_one, [p.name for p in src_parts]):
            log("texts", msg)
    ids = np.load(DOCS / "shard_ids.npy")
    dz = np.load(DOCS / "deleted_rows_2026-06-17_2026-09-15.npz", allow_pickle=True)
    del_ids = sorted(int(ids[r]) for r in dz["rows"])
    ups = []
    for p in sorted(x for x in DOCS.glob("updated_date=*.npz") if not x.name.endswith(".texts.npz")):
        date = p.name.split("=")[1][:10]
        z = np.load(p, allow_pickle=True)
        num, sel, cptr, comp, val = z["num"], z["sel"], z["cptr"], z["comp"], z["val"]
        for i in range(len(sel)):
            a0, b0 = int(cptr[i]), int(cptr[i + 1])
            cs = [int(x) for x in comp[a0:b0]]
            vs = [float(x) for x in val[a0:b0].astype(np.float32)]
            pairs = sorted({c: v for c, v in zip(cs, vs) if v > 0}.items())
            ups.append((date, int(num[sel[i]]), [c for c, _ in pairs], [v for _, v in pairs]))
    ups.sort(key=lambda x: (x[0], x[1]))
    recs = [(1, i, [], []) for i in del_ids] + [(2, i, c, v) for _, i, c, v in ups]
    write_batch(DOCS / "q1.sfubat", recs)
    base_ids = set(int(x) for x in ids)
    del_set = set(del_ids)
    upd = sum(1 for _, i, _, _ in ups if i in base_ids)
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "copied": copied,
                "q1": {"deletes": len(del_ids), "upserts": len(ups), "upserts_in_base": upd,
                       "upserts_new": len(ups) - upd, "order": "deletions, then upserts by (part-file updated_date, id)",
                       "note": "Stage-0 ENCODED SUBSAMPLE of 7 part files + full-window deletions; NOT the full quarter"}}
    rng = random.Random("inplace-q")
    live = sorted(base_ids - del_set)
    n_q = len(del_ids) + upd
    for k in (2, 3, 4):
        r = random.Random(f"inplace-q{k}")
        dk = r.sample(live, min(n_q, len(live)))
        dks = set(dk)
        live = [x for x in live if x not in dks]
        ins = [(2, 10**12 * k + j, c, v) for j, (_, _, c, v) in enumerate(ups)]
        write_batch(DOCS / f"q{k}.sfubat", [(1, i, [], []) for i in sorted(dk)] + ins)
        manifest[f"q{k}"] = {"deletes": len(dk), "inserts": len(ins), "synthetic_reuse": True,
                             "seed": f"inplace-q{k}"}
    _ = rng
    qs = json.loads(QUERIES.read_text())
    for s in ("QA", "QT", "QD"):
        out = [{"id": f"{s}{i}", "comps": q["terms"], "vals": q["w"]} for i, q in enumerate(qs[s])]
        (DOCS / f"queries_{s}.json").write_text(json.dumps(out))
    (DOCS / "docset.json").write_text(json.dumps(manifest, indent=1))
    log("prep-docs", manifest["q1"])


# ----------------------------------------------------------------- copies

def cp_sparse(src: Path, dst: Path) -> None:
    """Copy a shard dir (sparse-preserving, no links) and give the copy its own
    `.inplace_work_copy` sentinel through the updater's guarded CLI."""
    assert str(dst.resolve()).startswith(str(STAGE2)), dst
    if dst.exists():
        shutil.rmtree(dst)
    subprocess.run(["cp", "-r", "--sparse=always", "--no-preserve=links", str(src), str(dst)], check=True)
    man = json.loads((dst / "manifest.json").read_text())
    fnv = (man.get("inplace_v3", {}).get("source", {}) or {}).get("manifest_fnv64") or "unknown"
    run_bin("sentinel", "--dir", dst, "--source-fnv", fnv)


BASELINE = WORK / "baseline_20260929T2015Z"
PROTECTED_LISTINGS = {"data_seismic_150m.tsv": REPO / "data/seismic_150m",
                      "data_thinclient_index.tsv": REPO / "data/thinclient_index",
                      "_var_tmp_seismic_stage.tsv": Path("/var/tmp/seismic_stage")}
BASELINE_IGNORE = {"meta.sqlite-wal", "meta.sqlite-shm", "staged_manifest.json", ".staged_ok"}


def _baseline_diffs() -> tuple[list, list]:
    """(missing, changed) against the baseline listing. MISSING = expected file
    whose stat failed (errno recorded) or not found by the walk; CHANGED = size
    or mtime differs, or a new file appeared."""
    missing, changed = [], []
    for tsv, root in PROTECTED_LISTINGS.items():
        want = {}
        for line in (BASELINE / tsv).read_text().splitlines():
            size, mt, path = line.split("\t", 2)
            p = Path(path) if path.startswith("/") else REPO / path
            want[str(p)] = (int(size), float(mt))
        seen = set()
        for dp, _, fns in os.walk(root):
            for fn in fns:
                seen.add(os.path.join(dp, fn))
        for p in sorted(set(want) | seen):
            if os.path.basename(p) in BASELINE_IGNORE:
                continue
            try:
                st = os.stat(p)
                have = (st.st_size, st.st_mtime)
            except OSError as ex:
                if p in want:
                    missing.append({"path": p, "baseline": want[p], "errno": ex.errno, "error": ex.strerror})
                continue
            w = want.get(p)
            if w is None or w[0] != have[0] or abs(w[1] - have[1]) > 1e-3:
                changed.append({"path": p, "baseline": w, "now": have})
    return missing, changed


def baseline_check(when: str) -> dict:
    """Compare size+mtime of every file under the protected trees with the
    coordinator's baseline listing. A CHANGED file aborts at once. MISSING /
    unreadable files (stat error, e.g. a transient 9p failure) are re-checked up
    to 5 times over ~2 minutes; if still missing, abort. Both the first and the
    final listing are recorded."""
    missing, changed = _baseline_diffs()
    first = {"missing": missing[:50], "n_missing": len(missing), "changed": changed[:50], "n_changed": len(changed)}
    retries = 0
    while missing and not changed and retries < 5:
        retries += 1
        log(f"baseline: {len(missing)} MISSING/unreadable at {when}, retry {retries}/5 in 24 s")
        time.sleep(24)
        missing, changed = _baseline_diffs()
    final = {"missing": missing[:50], "n_missing": len(missing), "changed": changed[:50], "n_changed": len(changed)}
    rec = {"when": when, "checked_utc": datetime.now(timezone.utc).isoformat(), "retries": retries,
           "first": first, "final": final, "n_differences": len(missing) + len(changed)}
    if missing or changed:
        (STAGE2 / f"baseline_abort_{datetime.now(timezone.utc).strftime('%H%M%S')}.json").write_text(json.dumps(rec, indent=1))
        log("BASELINE DIFFERENCE — aborting:", json.dumps({"final": final})[:2000])
        raise SystemExit(f"protected tree differs at {when}: {len(changed)} CHANGED, {len(missing)} MISSING after {retries} retries; run aborted")
    return rec


def cmd_prep_copy(a):
    src = Path(a.src)
    assert src.is_dir() and (src / "inplace_header.bin").exists(), f"no v3 dir at {src}"
    assert not str(src.resolve()).startswith("/var/tmp/seismic_stage") and "seismic_150m" not in str(src.resolve())
    free = shutil.disk_usage(STAGE2).free
    need = sum(f.stat().st_blocks * 512 for f in src.iterdir() if f.is_file())
    assert free > 3 * need + (20 << 30), f"not enough disk: free {free}, need 3x{need}"
    root = synth_root(a) if a.synthetic else STAGE2
    cp_sparse(src, root / "pristine")
    if not (root / "pristine/readers.bin").exists():
        (root / "pristine/readers.bin").write_bytes(b"\0" * 16384)
    log("prep-copy", src, "->", root / "pristine")


def synth_root(a) -> Path:
    return STAGE2 / "synthetic"


def work_dir(root: Path, name: str) -> Path:
    return root / f"work_{name}"


def fresh_work(root: Path, name: str) -> Path:
    w = work_dir(root, name)
    cp_sparse(root / "pristine", w)
    return w


def restore_work(root: Path, w: Path, oplog: Path) -> None:
    run_bin("restore", "--dir", w, "--pristine", root / "pristine", "--log", oplog)
    shutil.copy2(root / "pristine/readers.bin", w / "readers.bin")


def file_sizes(d: Path) -> dict:
    out = {}
    for f in sorted(d.iterdir()):
        if f.is_file():
            st = f.stat()
            out[f.name] = {"st_size": st.st_size, "allocated": st.st_blocks * 512}
    out["_total"] = {"st_size": sum(v["st_size"] for v in out.values()),
                     "allocated": sum(v["allocated"] for v in out.values())}
    return out


# ------------------------------------------------------------------- apply

def apply_once(w: Path, batch: Path, arm: str, oplog: Path | None = None, progress: Path | None = None,
               extra=()) -> dict:
    args = ["apply", "--dir", w, "--batch", batch, "--arm", ARMS[arm], *extra]
    if oplog:
        args += ["--op-log", oplog]
    env = child_env()
    if progress:
        env["INPLACE_PROGRESS"] = str(progress)
    ob0 = children_oublock()
    t0 = time.perf_counter()
    r = run_bin(*args, env=env)
    r["wall_s_harness"] = time.perf_counter() - t0
    r["device_bytes_ru_oublock"] = (children_oublock() - ob0) * 512
    return r


def summarize_apply(r: dict) -> dict:
    keys = ["arm", "safety", "writer_io", "reuse_gate", "start_epoch", "end_epoch", "deletes_offered", "deletes_applied",
            "docs_offered", "docs_placed", "docs_unplaced_no_hole", "docs_unplaced_no_posting", "postings_offered",
            "postings_inserted", "postings_dropped_capacity", "postings_dropped_unplaced", "postings_evicted",
            "postings_freed", "rows_freed", "rows_fully_evicted", "lists_touched", "infl_blocks_raised",
            "infl_saturated", "blind_components", "blind_mass", "a2b_lists_rewritten", "heap_bytes_before",
            "heap_bytes_after", "heap_reserve", "gap_s", "total_s", "plan_s", "logical_bytes", "write_ops",
            "wall_s_harness", "device_bytes_ru_oublock", "inserted_by_len_decile", "dropped_by_len_decile"]
    s = {k: r.get(k) for k in keys}
    s["proc_self_io_write_bytes"] = r.get("proc_self_io", {}).get("write_bytes")
    s["phases"] = r.get("phases")
    s["recovery"] = r.get("recovery")
    for k in APPLY_EXTRA_KEYS:
        if k in r:
            s[k] = r[k]
    return s


def apply_extra(a) -> tuple:
    """Extra updater flags from the command line (empty unless asked for)."""
    return ("--heap-reuse", "0") if getattr(a, "no_heap_reuse", False) else ()


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2]))


# ------------------------------------------------------------------------ A1

A1_CHILD = r'''
import json, os, sys, time, resource
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[1] + "/source")
from pathlib import Path
import numpy as np
from spike.delta_ingest.generation import build_generation
from spike.delta_ingest.profiles import PROFILES
from spike.delta_ingest.records import DocRecord
from spike.inplace_update.shard import load_token_to_id
tok = load_token_to_id(Path(sys.argv[2]))
inv = {v: k for k, v in tok.items()}
docs = Path(sys.argv[3]); root = Path(sys.argv[4])
recs = []
for p in sorted(x for x in docs.glob("updated_date=*.npz") if not x.name.endswith(".texts.npz")):
    z = np.load(p, allow_pickle=True)
    num, sel, cptr, comp, val = z["num"], z["sel"], z["cptr"], z["comp"], z["val"]
    tz = np.load(p.with_name(p.name[:-4] + ".texts.npz"), allow_pickle=True)
    tmap = {int(i): (str(t), int(y) or None) for i, t, y in zip(tz["ids"], tz["texts"], tz["years"])}
    for i in range(len(sel)):
        a, b = int(cptr[i]), int(cptr[i + 1])
        sf = {inv[int(c)]: float(v) for c, v in zip(comp[a:b], val[a:b].astype(np.float32)) if float(v) > 0}
        wid = int(num[sel[i]])
        text, year = tmap.get(wid, ("", None))
        recs.append(DocRecord(id=f"W{wid}", title=text, year=year, sparse_field=sf, source="inplace_bench"))
t0 = time.perf_counter()
g = build_generation(root, 1, recs, PROFILES["desktop_gpu"])
dt = time.perf_counter() - t0
logical = sum(f.stat().st_size for f in g.rglob("*") if f.is_file())
seis = sum(f.stat().st_size for f in (g / "seismic").rglob("*") if f.is_file()) if (g / "seismic").exists() else 0
io = dict(l.split(":") for l in open("/proc/self/io").read().splitlines())
print(json.dumps({"build_s": dt, "docs": len(recs), "logical_bytes": logical, "seismic_bytes": seis,
                  "proc_self_io_write_bytes": int(io["write_bytes"]), "gen": str(g)}))
'''


def run_a1(rep: int, docs: Path) -> dict:
    root = STAGE2 / "a1" / f"root_rep{rep}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    env = child_env()
    env["PYTHONPATH"] = str(WORK / "pylocal")
    ob0 = children_oublock()
    t0 = time.perf_counter()
    p = subprocess.run([str(REPO / ".venv/bin/python3"), "-c", A1_CHILD, str(REPO), str(TWIN), str(docs), str(root)],
                       capture_output=True, text=True, env=env, timeout=4 * 3600)
    wall = time.perf_counter() - t0
    dev = (children_oublock() - ob0) * 512
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        raise RuntimeError(f"A1 build failed rc={p.returncode}: {p.stderr[-1500:]}")
    out.update({"wall_s_harness": wall, "device_bytes_ru_oublock": dev,
                "note": "build_generation (sections + meta + SEISMIC chain); deletions are masks, not built"})
    for line in p.stderr.splitlines():
        if "Traceback" in line or "Error" in line:
            out.setdefault("stderr_flags", []).append(line[:200])
    return out


# --------------------------------------------------------------------- B2

def cmd_b2(a):
    root = synth_root(a) if a.synthetic else STAGE2
    batch = Path(a.batch) if a.batch else (root / "q1.sfubat" if a.synthetic else DOCS / "q1.sfubat")
    arms = a.arms.split(",") if a.arms else list(BASE_ARMS)
    res = {"bar": "B2 apply cost", "host_before": host_state(), "batch": str(batch), "reps": a.reps, "arms": {}}
    for arm in arms:
        w = fresh_work(root, ARMS[arm])
        reps = []
        for k in range(a.reps):
            oplog = root / f"oplog_{ARMS[arm]}.bin"
            r = apply_once(w, batch, arm, oplog=oplog, extra=apply_extra(a))
            reps.append(summarize_apply(r))
            restore_work(root, w, oplog)
            log("B2", arm, k, f"wall {r['total_s']:.2f}s dev {r['device_bytes_ru_oublock']} logical {r['logical_bytes']}")
        res["arms"][arm] = {"reps": reps,
                            "median_wall_s": median([x["total_s"] for x in reps]),
                            "median_device_bytes": median([x["device_bytes_ru_oublock"] for x in reps]),
                            "median_logical_bytes": median([x["logical_bytes"] for x in reps])}
        shutil.rmtree(w)
    a1 = []
    if not a.synthetic and not a.skip_a1:
        merge_result(a.synthetic, "B2", {**res, "status": "A2 arms done, A1 running"})
        try:
            a1 = [run_a1(k, DOCS) for k in range(a.reps)]
        except Exception as ex:
            res["arms"]["A1(N=1)"] = {"status": "FAILED", "error": str(ex)[:1500]}
            log("A1 failed", str(ex)[:300])
    if a1:
        res["arms"]["A1(N=1)"] = {"reps": a1, "median_wall_s": median([x["wall_s_harness"] for x in a1]),
                                  "median_device_bytes": median([x["device_bytes_ru_oublock"] for x in a1]),
                                  "median_logical_bytes": median([x["logical_bytes"] for x in a1])}
        ref = res["arms"]["A1(N=1)"]
        for arm in arms:
            x = res["arms"][arm]
            wall_ok = x["median_wall_s"] <= ref["median_wall_s"]
            bytes_ok = x["median_device_bytes"] <= ref["median_device_bytes"]
            x["verdict_vs_A1"] = "PASS" if wall_ok and bytes_ok else ("PARTIAL" if wall_ok or bytes_ok else "FAIL")
            x["wall_ok"], x["bytes_ok"] = wall_ok, bytes_ok
    res["A3"] = "NOT RUN (run with --with-a3; heavy)" if (not a.with_a3 or a.synthetic) else [run_a3(root, k) for k in range(a.reps)]
    res["host_after"] = host_state()
    log("B2 ->", merge_result(a.synthetic, "B2", res))


A3_BUILD_CHILD = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[1] + "/source")
from pathlib import Path
from spike.delta_ingest.generation import build_seismic_shard
t0 = time.perf_counter()
info = build_seismic_shard(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]))
print(json.dumps({"build_chain_s": time.perf_counter() - t0, "info": info}))
"""


def run_a3(root: Path, rep: int = 0) -> dict:
    """A3: twin dump (eval_delta_ingest_twin_rebuild.py dump) -> drop deleted and
    updated-old ids, append the upserts (values as exact f16 decimals, as the
    dump writes base docs) -> build_seismic_shard (G2 build, c1a, dotvbyte
    perdoc). Wall and device bytes (ru_oublock of the child tree) per stage."""
    import numpy as np
    w = root / "a3" / f"rep{rep}"
    if w.exists():
        shutil.rmtree(w)
    w.mkdir(parents=True)
    out = {"stages": {}}
    ob0, t0 = children_oublock(), time.perf_counter()
    p = subprocess.run([str(REPO / ".venv/bin/python3"), str(REPO / "scripts/experiments/eval_delta_ingest_twin_rebuild.py"),
                        "dump", "--shard", "0", "--work", str(w), "--workers", "8"],
                       capture_output=True, text=True, env=child_env(), timeout=4 * 3600)
    if p.returncode != 0:
        return {"status": "FAILED", "stage": "dump", "stderr": p.stderr[-1500:]}
    out["stages"]["dump"] = {"wall_s": time.perf_counter() - t0, "device_bytes": (children_oublock() - ob0) * 512}
    jsonl = Path((w / "DUMP_READY.txt").read_text().strip())
    t1 = time.perf_counter()
    import sys as _s
    _s.path.insert(0, str(REPO))
    from spike.inplace_update.shard import load_token_to_id
    inv = {v: k for k, v in load_token_to_id(TWIN).items()}
    removed = set()
    ups = []
    for q in sorted(x for x in DOCS.glob("updated_date=*.npz") if not x.name.endswith(".texts.npz")):
        z = np.load(q, allow_pickle=True)
        num, sel, cptr, comp, val = z["num"], z["sel"], z["cptr"], z["comp"], z["val"]
        for i in range(len(sel)):
            a0, b0 = int(cptr[i]), int(cptr[i + 1])
            wid = f"W{int(num[sel[i]])}"
            removed.add(wid)
            body = ",".join(json.dumps(inv[int(c)]) + ":" + repr(float(v)) for c, v in zip(comp[a0:b0], val[a0:b0]) if float(v) > 0)
            ups.append('{"id":"' + wid + '","vector":{' + body + "}}\n")
    ids = np.load(DOCS / "shard_ids.npy")
    dz = np.load(DOCS / "deleted_rows_2026-06-17_2026-09-15.npz", allow_pickle=True)
    removed.update(f"W{int(ids[r])}" for r in dz["rows"])
    fj = w / "a3_q1.jsonl"
    kept = 0
    with open(jsonl, encoding="utf-8") as r, open(fj, "w", encoding="utf-8") as o:
        for line in r:
            wid = line[7:line.index('"', 7)]
            if wid not in removed:
                o.write(line)
                kept += 1
        o.write("".join(ups))
    jsonl.unlink()
    out["stages"]["merge"] = {"wall_s": time.perf_counter() - t1, "base_kept": kept, "upserts": len(ups)}
    ob1, t2 = children_oublock(), time.perf_counter()
    env = child_env()
    env["PYTHONPATH"] = str(WORK / "pylocal")
    p = subprocess.run([str(REPO / ".venv/bin/python3"), "-c", A3_BUILD_CHILD, str(REPO), str(fj), str(w / "rebuilt_shard0"), "8"],
                       capture_output=True, text=True, env=env, timeout=6 * 3600)
    if p.returncode != 0:
        return {"status": "FAILED", "stage": "build", "stderr": p.stderr[-1500:], **out}
    out["stages"]["build"] = {"wall_s": time.perf_counter() - t2, "device_bytes": (children_oublock() - ob1) * 512,
                              "child": json.loads(p.stdout.strip().splitlines()[-1])}
    out["wall_s"] = time.perf_counter() - t0
    out["device_bytes"] = sum(v.get("device_bytes", 0) for v in out["stages"].values())
    out["status"] = "RUN"
    return out


# --------------------------------------------------------------------- B4

def cmd_b4(a):
    root = synth_root(a) if a.synthetic else STAGE2
    bdir = root if a.synthetic else DOCS
    arms = a.arms.split(",") if a.arms else list(BASE_ARMS)
    nb = a.batches
    res = {"bar": "B4 storage", "arms": {}, "batches": nb}
    for arm in arms:
        w = fresh_work(root, ARMS[arm])
        per = {"before": file_sizes(w), "batches": []}
        for k in range(1, nb + 1):
            try:
                r = apply_once(w, bdir / f"q{k}.sfubat", arm, extra=apply_extra(a))
            except RuntimeError as ex:
                per["batches"].append({"quarter": k, "synthetic_reuse": k > 1, "error": str(ex)[:600]})
                per[f"failed_at_q{k}"] = str(ex)[:300]
                break
            s = summarize_apply(r)
            per["batches"].append({"quarter": k, "synthetic_reuse": k > 1, "apply": s})
            if k in (1, nb):
                per[f"after_q1..q{k}" if k > 1 else "after_q1"] = file_sizes(w)
        per.setdefault(f"after_q1..q{nb}", file_sizes(w))
        okb = [b for b in per["batches"] if "apply" in b]
        if arm.startswith("A2b") and okb:
            used = [b["apply"]["heap_bytes_after"] - b["apply"]["heap_bytes_before"] for b in okb]
            reserve = okb[0]["apply"]["heap_reserve"]
            last = okb[-1]["apply"]["heap_bytes_after"]
            mean = sum(used) / len(used)
            per["heap"] = {"bytes_per_batch": used, "reserve": reserve, "used_after_q4": last,
                           "batches_to_exhaustion_from_empty": (reserve / mean) if mean else None,
                           "remaining_batches_after_q4": ((reserve - last) / mean) if mean else None}
            if "heap_reused_bytes" in okb[0]["apply"]:
                per["heap"]["accepted_batches"] = len(okb)
                per["heap"]["heap_reuse"] = okb[0]["apply"].get("heap_reuse")
                per["heap"]["reused_bytes_per_batch"] = [b["apply"]["heap_reused_bytes"] for b in okb]
                per["heap"]["superseded_bytes_per_batch"] = [b["apply"]["heap_superseded_bytes"] for b in okb]
                per["heap"]["free_bytes_after_last"] = okb[-1]["apply"]["heap_free_bytes_after"]
        if okb and "tail_words_after" in okb[-1]["apply"]:
            per["tail"] = {"words_used_after_last": okb[-1]["apply"]["tail_words_after"],
                           "rows_used_after_last": okb[-1]["apply"]["tail_rows_after"],
                           "reserve_words": okb[-1]["apply"]["tail_reserve_words"],
                           "reserve_rows": okb[-1]["apply"]["tail_reserve_rows"],
                           "placed_hole_per_batch": [b["apply"]["docs_placed_hole"] for b in okb],
                           "placed_tail_per_batch": [b["apply"]["docs_placed_tail"] for b in okb]}
        res["arms"][arm] = per
        shutil.rmtree(w)
    log("B4 ->", merge_result(a.synthetic, "B4", res))


# --------------------------------------------------------------------- B5

def published_epoch(hdr: bytes) -> int | None:
    best = None
    for s in (0, 1):
        r = hdr[s * 4096:s * 4096 + 128]
        if r[:8] != b"SFUIPV3\0" or struct.unpack_from("<I", r, 12)[0] != s:
            continue
        h = 0xcbf29ce484222325
        for b in r[:120]:
            h ^= b
            h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
        if h != struct.unpack_from("<Q", r, 120)[0]:
            continue
        e = struct.unpack_from("<Q", r, 16)[0]
        if best is None or e > best:
            best = e
    return best


def mincore_resident(path: Path) -> list[bool]:
    """Page-cache residency of a file via mmap(PROT_READ, MAP_SHARED) + mincore."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
    libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    size = path.stat().st_size
    if size == 0:
        return []
    fd = os.open(path, os.O_RDONLY)
    try:
        addr = libc.mmap(None, size, 1, 1, fd, 0)
        if addr in (None, ctypes.c_void_p(-1).value):
            return []
        npages = (size + 4095) // 4096
        vec = (ctypes.c_ubyte * npages)()
        rc = libc.mincore(addr, size, vec)
        out = [bool(v & 1) for v in vec] if rc == 0 else []
        libc.munmap(addr, size)
        return out
    finally:
        os.close(fd)


def cmd_b5(a):
    root = synth_root(a) if a.synthetic else STAGE2
    batch = Path(a.batch) if a.batch else (root / "q1.sfubat" if a.synthetic else DOCS / "q1.sfubat")
    arms = a.arms.split(",") if a.arms else PRIMARY
    res = {"bar": "B5 publish", "reader": "header poll (1 ms, CLOCK_MONOTONIC), not the v3 decoder", "arms": {}}
    for arm in arms:
        w = fresh_work(root, ARMS[arm])
        files = FILES + (["forward_offsets.bin"] if "+tail" in arm else [])
        reps = []
        for k in range(a.reps):
            for f in files:
                with open(w / f, "rb") as fh:
                    while fh.read(1 << 24):
                        pass
            before = {f: mincore_resident(w / f) for f in files}
            prog = root / f"progress_{ARMS[arm]}.txt"
            prog.unlink(missing_ok=True)
            seen: list[tuple[int, int]] = []
            stop = threading.Event()

            def poll():
                last = None
                with open(w / "inplace_header.bin", "rb") as fh:
                    mm = mmap.mmap(fh.fileno(), 8192, prot=mmap.PROT_READ)
                    while not stop.is_set():
                        e = published_epoch(bytes(mm[:8192]))
                        if e != last:
                            seen.append((e, time.monotonic_ns()))
                            last = e
                        time.sleep(0.001)
                    mm.close()

            th = threading.Thread(target=poll)
            th.start()
            oplog = root / f"oplog_b5_{ARMS[arm]}.bin"
            r = apply_once(w, batch, arm, oplog=oplog, progress=prog)
            time.sleep(0.05)
            stop.set()
            th.join()
            after = {f: mincore_resident(w / f) for f in files}
            flips = []
            for line in prog.read_text().splitlines():
                p = line.split()
                ep, st = int(p[1]), int(p[4])
                first = next((t for e, t in seen if e is not None and e >= ep), None)
                flips.append({"epoch": ep, "publish_to_first_seen_ms": (first - st) / 1e6 if first else None,
                              "header_write_ms": (int(p[6]) - st) / 1e6})
            kept = sum(1 for f in files for i, v in enumerate(before[f]) if v and i < len(after[f]) and after[f][i])
            res_b = sum(1 for f in files for v in before[f] if v)
            reps.append({"flips": flips, "batch_start_to_inserts_visible_s": r["phases"][-1]["flip_done_at_s"],
                         "resident_before": res_b, "resident_kept": kept,
                         "kept_fraction": kept / res_b if res_b else None, "re_mmap": False,
                         "apply": summarize_apply(r)})
            restore_work(root, w, oplog)
        kf = [x["kept_fraction"] for x in reps if x["kept_fraction"] is not None]
        res["arms"][arm] = {"reps": reps, "residency_verdict": "PASS" if kf and min(kf) >= 0.99 else "FAIL"}
        shutil.rmtree(w)
    log("B5 ->", merge_result(a.synthetic, "B5", res))


# --------------------------------------------------------------------- B7

def refs_for(root: Path, arm: str, batch: Path, qfile: Path) -> tuple[dict, float, Path]:
    """Clean references at e, e+1(, e+2) and T_apply, from a clean run."""
    w = fresh_work(root, ARMS[arm] + "_ref")
    refs = {}
    r0 = run_bin("search", "--dir", w, "--queries", qfile, "--k", K_PRIME, "--epoch", "published")
    refs[r0["epoch"]] = r0["results"]
    oplog = root / f"oplog_b7_{ARMS[arm]}.bin"
    r = apply_once(w, batch, arm, oplog=oplog)
    for e in range(r["start_epoch"] + 1, r["end_epoch"] + 1):
        x = run_bin("search", "--dir", w, "--queries", qfile, "--k", K_PRIME, "--epoch", e)
        refs[e] = x["results"]
    shutil.rmtree(w)
    return refs, r["wall_s_harness"], oplog


def check_ab(w: Path, qfile: Path, refs: dict, start: int, flips_done: int, strict_epoch: bool) -> dict:
    x = run_bin("search", "--dir", w, "--queries", qfile, "--k", K_PRIME, "--epoch", "published", check=False)
    if "error" in x:
        return {"a": False, "b": False, "error": x["error"]}
    e = x["epoch"]
    n_ph = max(refs) - start
    a_ok = start <= e <= start + n_ph and e >= start + flips_done and (not strict_epoch or e == start + flips_done)
    b_ok = e in refs and x["results"] == refs[e]
    return {"a": a_ok, "b": b_ok, "epoch": e, "flips_done": flips_done}


def header_syncs(oplog: Path) -> list[int]:
    """Op indices of header syncs (kind 2, file 1) in an op log."""
    out = []
    with open(oplog, "rb") as f:
        i = 0
        while True:
            h = f.read(24)
            if len(h) < 24:
                break
            kind, fid, nl = h[0], h[1], struct.unpack_from("<H", h, 2)[0]
            dl = struct.unpack_from("<Q", h, 16)[0]
            f.seek(nl + dl, 1)
            if kind == 2 and fid == 1:
                out.append(i)
            i += 1
    return out


def check_readers(outs: list[Path], refs: dict) -> dict:
    n, bad, errs = 0, [], []
    for p in outs:
        if not p.exists():
            errs.append(f"{p.name}: no output")
            continue
        d = json.loads(p.read_text())
        for ps in d["passes"]:
            errs.extend(ps["errors"])
            for qid, r in ps["results"].items():
                n += 1
                if refs.get(r["epoch"], {}).get(qid) != r["hits"]:
                    bad.append((qid, r["epoch"]))
    return {"queries": n, "mismatches": len(bad), "first_mismatches": bad[:5], "errors": errs[:5], "n_errors": len(errs),
            "ok": n > 0 and not bad and not errs}


def cmd_b7(a):
    if a.decoder:
        raise SystemExit("--decoder: the v3-decoder check is not wired in this harness revision")
    root = synth_root(a) if a.synthetic else STAGE2
    batch = Path(a.batch) if a.batch else (root / "q1.sfubat" if a.synthetic else DOCS / "q1.sfubat")
    qfile = Path(a.queries) if a.queries else (root / "queries.json" if a.synthetic else DOCS / "queries_QT.json")
    arms = a.arms.split(",") if a.arms else PRIMARY
    rng = random.Random(a.seed)
    res = {"bar": "B7 crash safety", "checker": "updater exact reference search (bit-identical f32 scores)"
           + (" + v3 decoder" if a.decoder else "; v3 decoder NOT used (not available for this arm)"), "arms": {}}
    for arm in arms:
        refs, t_apply, oplog = refs_for(root, arm, batch, qfile)
        start = min(refs)
        refs = {int(k): v for k, v in refs.items()}
        per = {"T_apply_s": t_apply, "sigkill": [], "powerloss": {"drop": [], "pages": []}}
        w = fresh_work(root, ARMS[arm])
        slowq = root / "queries_slow.json"
        qs = json.loads(qfile.read_text())
        slowq.write_text(json.dumps(qs[:8]))
        for trial in range(a.trials):
            restore_work(root, w, oplog)
            prog = root / "progress_b7.txt"
            prog.unlink(missing_ok=True)
            outs = [root / f"reader_slow_{trial}.json", root / f"reader_fast_{trial}.json"]
            for o in outs:
                o.unlink(missing_ok=True)
            rd = [subprocess.Popen([str(BIN), "search", "--dir", str(w), "--queries", str(slowq), "--k", str(K_PRIME),
                                    "--loop-s", str(t_apply * 1.5 + 0.5), "--sleep-ms", "20", "--out", str(outs[0])],
                                   env=child_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                  subprocess.Popen([str(BIN), "search", "--dir", str(w), "--queries", str(slowq), "--k", str(K_PRIME),
                                    "--loop-s", str(t_apply * 1.5 + 0.5), "--out", str(outs[1])],
                                   env=child_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
            time.sleep(0.2)
            env = child_env()
            env["INPLACE_PROGRESS"] = str(prog)
            up = subprocess.Popen([str(BIN), "apply", "--dir", str(w), "--batch", str(batch), "--arm", ARMS[arm]],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            t_kill = rng.uniform(0, t_apply)
            time.sleep(t_kill)
            up.send_signal(signal.SIGKILL)
            up.wait()
            for p in rd:
                p.wait(timeout=600)
            flips = len(prog.read_text().splitlines()) if prog.exists() else 0
            ab = check_ab(w, qfile, refs, start, flips, strict_epoch=False)
            c = check_readers(outs, refs)
            ok = ab["a"] and ab["b"] and c["ok"]
            per["sigkill"].append({"trial": trial, "t_kill_s": t_kill, **ab, "c": c, "ok": ok})
            log("B7 sigkill", arm, trial, ok, ab.get("epoch"), c["queries"])
        ops_n = run_bin("nops", "--log", oplog)["n_ops"]
        hs = header_syncs(oplog)
        for model in ("drop", "pages"):
            for trial in range(a.trials):
                restore_work(root, w, oplog)
                cut = rng.randint(0, ops_n)
                img = run_bin("crash", "--dir", w, "--log", oplog, "--cut", cut, "--model", model, "--seed", 1000 + trial)
                done = sum(1 for i in hs if i < cut)
                ab = check_ab(w, qfile, refs, start, done, strict_epoch=(model == "drop"))
                if model == "pages" and "epoch" in ab:
                    ab["a"] = start + done <= ab["epoch"] <= min(start + done + 1, max(refs))
                if a.synthetic or trial % a.pl_verify_every == 0:
                    rec = run_bin("recover", "--dir", w, check=False)
                    ver = run_bin("verify", "--dir", w, check=False)
                else:
                    rec, ver = {"skipped": True}, {"n_violations": 0, "skipped": True}
                ok = ab["a"] and ab["b"] and ver.get("n_violations", 1) == 0 and "error" not in rec
                per["powerloss"][model].append({"trial": trial, "cut": cut, "n_ops": ops_n, **ab, "image": img,
                                                "verify_violations": ver.get("violations", [])[:3], "ok": ok})
                log("B7", model, arm, trial, ok, ab.get("epoch"))
        for k in ("sigkill",):
            n_ok = sum(1 for x in per[k] if x["ok"])
            per[f"{k}_pass"] = f"{n_ok}/{len(per[k])}"
        for m in ("drop", "pages"):
            n_ok = sum(1 for x in per["powerloss"][m] if x["ok"])
            per[f"powerloss_{m}_pass"] = f"{n_ok}/{len(per['powerloss'][m])}"
        allok = all(x["ok"] for x in per["sigkill"]) and all(x["ok"] for m in ("drop", "pages") for x in per["powerloss"][m])
        per["verdict"] = ("PASS" if allok and a.trials >= 100 else ("FAIL" if not allok else "INCOMPLETE (<100 trials)"))
        per["failing_trials"] = [x["trial"] for x in per["sigkill"] if not x["ok"]] + \
            [f"{m}:{x['trial']}" for m in ("drop", "pages") for x in per["powerloss"][m] if not x["ok"]]
        res["arms"][arm] = per
        shutil.rmtree(w)
    log("B7 ->", merge_result(a.synthetic, "B7", res))


# ------------------------------------------------------------------ B3 / B6

def cmd_blocked(a):
    key = a.cmd.upper()
    res = {"bar": key, "status": "NOT RUN",
           "reason": "needs the v3 decoder behind search_rrf (A2) and the A2b unit read path (A2b), plus A3 for B6; "
                     "neither exists at this harness revision"}
    log(key, "->", merge_result(a.synthetic, key, res))


# ---------------------------------------------------------------- synthetic

def cmd_synth_prep(a):
    import numpy as np
    root = synth_root(a)
    root.mkdir(parents=True, exist_ok=True)
    src = root / "built"
    if src.exists():
        shutil.rmtree(src)
    extra = []
    if a.tail_words or a.tail_rows:
        extra += ["--tail-words", a.tail_words, "--tail-rows", a.tail_rows]
    if a.heap_factor:
        extra += ["--heap-factor", a.heap_factor]
    run_bin("synth", "--out", src, "--docs", a.docs, "--dim", a.dim, "--cap", a.cap, "--block", 8, "--seed", a.seed, *extra)
    cp_sparse(src, root / "pristine")
    rng = np.random.default_rng(a.seed)
    ids = [1_000_000 + 7 * r for r in range(a.docs)]

    def rvec():
        n = int(rng.integers(4, 24))
        cs = sorted(set(int((rng.random() ** 2) * a.dim) for _ in range(n)))
        return cs, [float(0.05 + 2.95 * rng.random()) for _ in cs]

    live = list(ids)
    for k in range(1, max(4, a.batches) + 1):
        rng.shuffle(live)
        nd, nu = len(live) // 20, len(live) // 10
        recs = [(1, i, [], []) for i in live[:nd]]
        recs += [(2, i, *rvec()) for i in live[nd:nd + nu]]
        recs += [(2, 5_000_000 + 100_000 * k + j, *rvec()) for j in range(len(live) // 40)]
        live = live[nd:]
        write_batch(root / f"q{k}.sfubat", recs)
    qs = []
    for i in range(40):
        c, v = rvec()
        qs.append({"id": f"S{i}", "comps": c, "vals": v})
    (root / "queries.json").write_text(json.dumps(qs))
    log("synthetic prepared under", root)


BASELINE_LOG: list = []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep-docs", "prep-copy", "synth-prep", "b2", "b3", "b4", "b5", "b6", "b7"])
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--src", default=str(DEFAULT_V3))
    ap.add_argument("--arms", default="")
    ap.add_argument("--batch", default="")
    ap.add_argument("--queries", default="")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--trials", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--docs", type=int, default=20000)
    ap.add_argument("--dim", type=int, default=2000)
    ap.add_argument("--cap", type=int, default=200)
    ap.add_argument("--skip-a1", action="store_true")
    ap.add_argument("--with-a3", action="store_true")
    ap.add_argument("--decoder", action="store_true")
    ap.add_argument("--pl-verify-every", type=int, default=10,
                    help="real shard: run recover+verify (not part of the bar) on every n-th power-loss trial")
    ap.add_argument("--batches", type=int, default=4, help="b4 / synth-prep: number of batches (default 4)")
    ap.add_argument("--no-heap-reuse", action="store_true", help="A2b arms: bump-only heap (R7 before/after)")
    ap.add_argument("--tail-words", type=int, default=0, help="synth-prep: forward tail reserve words (v3.1)")
    ap.add_argument("--tail-rows", type=int, default=0, help="synth-prep: forward tail reserve rows (v3.1)")
    ap.add_argument("--heap-factor", type=int, default=0, help="synth-prep: heap reserve as a multiple of the posting file (crate default 6)")
    a = ap.parse_args()
    assert BIN.exists(), f"build the updater first: {BIN}"
    for k in ("SFU_DELTA_ROOT", "SFU_META_STAGE_DIR", "SFU_SEISMIC_STAGE_DIR"):
        assert not os.environ.get(k), f"{k} is set in the harness environment; unset it"
    measured = a.cmd in ("prep-copy", "b2", "b4", "b5", "b7")
    if measured:
        BASELINE_LOG.append(baseline_check(f"start {a.cmd}"))
    {"prep-docs": cmd_prep_docs, "prep-copy": cmd_prep_copy, "synth-prep": cmd_synth_prep, "b2": cmd_b2,
     "b3": cmd_blocked, "b4": cmd_b4, "b5": cmd_b5, "b6": cmd_blocked, "b7": cmd_b7}[a.cmd](a)
    if measured:
        BASELINE_LOG.append(baseline_check(f"end {a.cmd}"))
        merge_result(a.synthetic, f"baseline_{a.cmd}", {"checks": BASELINE_LOG})


if __name__ == "__main__":
    main()
