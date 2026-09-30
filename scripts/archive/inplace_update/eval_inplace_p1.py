#!/usr/bin/env python3
"""Supplementary P1 — vector-diff change filter (NOT a pre-registered bar).

Definitions (verbatim from docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md,
second addendum 2026-09-29, commit d4ba6b87):

  - **Definitions.** For a touched in-base doc, compare the newly encoded
    sparse vector with the stored vector of the f16 twin forward record.
    `unchanged_exact`: identical component set and every value equal after the
    f16 cast. `unchanged_tol`: identical component set and max |Δw| ≤ 1 f16
    ulp.
  - **Required control, reported before any P1 number is interpreted.** The
    stored vectors come from the build's encoder runtime, today's from a
    possibly different one (open issue O8). On docs whose title+abstract are
    byte-identical to the base text, the share NOT `unchanged_exact` and NOT
    `unchanged_tol` is measured. If it exceeds 1 %, the vector diff is
    recorded UNRELIABLE AS DEFINED; the smallest tolerance that brings the
    control under 1 % may be reported, labelled post hoc.
  - **Recorded, under `supplementary.P1` of the Stage-0 results file:**
    `new_vd(L)` / `dead_vd(L)` (only vector-changed docs count) beside the
    frozen S0-1 pair; M7 touched:must-encode re-scored by vector diff on
    M7's two part files, as a third number beside the two recorded FAILs.
    M7's verdict does not change.

Implementation:
  control  shard-0 docs of the hot section social_sciences__recent (the only
           section with a local abstract sidecar): seeded sample
           ("inplace-p1-control") of shard-0 ids probed against the sidecar,
           first 3,000 found; text = DocRecord(title from meta.sqlite,
           abstract from the sidecar).encoder_text(), i.e. the base text
           itself; encoded with lib.thinclient.doc_encoder (PyTorch fp16 on
           CUDA, max_length 128) and compared with the twin row.
  m7       M7's two files, restricted to records routed to shard 0 (hash
           routing is content-agnostic, so this is a uniform 1/8 subsample),
           M7's slice (min_year 2015). Every in-base (in served shard 0)
           record is encoded and diffed; touched_in_slice : (new +
           vector-changed) under exact and tol, plus the post-hoc tolerance
           if the control needs one.
  new_vd / dead_vd are computed by eval_inplace_s0_1.py run from the same
  encoded sample it scores (supplementary key).
Both subcommands must run under flock /tmp/sfu_latency_measure.lock (GPU).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts/experiments"))

from spike.inplace_update import prep  # noqa: E402
from spike.inplace_update.shard import ShardView, load_token_to_id  # noqa: E402
import eval_inplace_s0_1 as s01  # noqa: E402

WORK = s01.WORK
HOT = REPO / "data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite"
META = REPO / "data/thinclient_index/meta.sqlite"
M7_FILES = ["/var/tmp/sfu_delta_B_20260929/works_updated_date=2026-09-15_part_0001.gz",
            "/var/tmp/sfu_delta_B_20260929/works_updated_date=2026-09-22_part_0054.gz"]
TOL_GRID_ULPS = [1, 2, 4, 8, 16, 64, 256, 1e9]
TOL_GRID_SETW = [0.0, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 1e9]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def encoder():
    import torch
    torch.set_num_threads(4)
    from lib.thinclient.doc_encoder import make_doc_encoder
    enc = make_doc_encoder(backend="pytorch", device="cuda", batch_size=64)
    assert enc.model is not None and str(enc.device) == "cuda"
    return enc


def encode_csr(enc, texts, tok):
    cptr, cc, cv = [0], [], []
    unk = 0
    for b in range(0, len(texts), 64):
        for v in enc.encode_batch(texts[b:b + 64]):
            items = sorted((tok[t], w) for t, w in (v or {}).items() if t in tok)
            unk += sum(1 for t in (v or {}) if t not in tok)
            cc.extend(c for c, _ in items)
            cv.extend(w for _, w in items)
            cptr.append(len(cc))
    return np.array(cptr, np.int64), np.array(cc, np.int64), np.array(cv, np.float32), unk


def summarize_diff(d):
    n = len(d["exact"])
    tol = d["same_set"] & (d["max_ulps"] <= 1)
    out = {"n": int(n), "not_unchanged_exact_share": float(1 - d["exact"].mean()) if n else None,
           "not_unchanged_tol_share": float(1 - tol.mean()) if n else None,
           "component_set_differs_share": float(1 - d["same_set"].mean()) if n else None,
           "max_abs_diff_pct": {p: float(np.percentile(d["max_abs_diff"], p)) for p in (50, 90, 99, 100)} if n else None,
           "max_ulps_pct": {p: float(np.percentile(d["max_ulps"], p)) for p in (50, 90, 99, 100)} if n else None,
           "symdiff_count_pct": {p: float(np.percentile(d["symdiff"], p)) for p in (50, 90, 99, 100)} if n else None,
           "symdiff_max_weight_pct": {p: float(np.percentile(d["symdiff_max_weight"], p)) for p in (50, 90, 99, 100)} if n else None}
    return out


def changed_under(d, ulps, setw):
    return ~((d["max_ulps"] <= ulps) & (d["symdiff_max_weight"] <= setw))


def cmd_control(a):
    from spike.delta_ingest.records import DocRecord
    from lib.thinclient.abstracts import AbstractStore
    sh = ShardView(s01.TWIN)
    tok = load_token_to_id(s01.TWIN)
    ids = np.load(WORK / "shard_ids.npy")
    rng = np.random.default_rng(list(b"inplace-p1-control"))
    cand = rng.permutation(len(ids))
    db = sqlite3.connect(f"file:{HOT}?mode=ro", uri=True, timeout=60)
    found = []
    for i in range(0, len(cand), 5000):
        rows = cand[i:i + 5000]
        wids = [f"W{int(ids[r])}" for r in rows]
        have = {x for (x,) in db.execute(f"SELECT id FROM docs WHERE id IN ({','.join('?' * len(wids))})", wids)}
        found += [int(r) for r, w in zip(rows, wids) if w in have]
        if len(found) >= a.n:
            break
    db.close()
    found = found[:a.n]
    store = AbstractStore(HOT)
    wmap = {f"W{int(ids[r])}": r for r in found}
    abs_ = store.fetch(list(wmap))
    mdb = sqlite3.connect(f"file:{META}?mode=ro", uri=True, timeout=120)
    titles = {}
    keys = [int(ids[r]) for r in found]
    for i in range(0, len(keys), 500):
        ch = keys[i:i + 500]
        for rid, title in mdb.execute(f"SELECT id,title FROM docs WHERE id IN ({','.join('?' * len(ch))})", ch):
            titles[rid] = title or ""
    mdb.close()
    rows, texts = [], []
    for w, r in wmap.items():
        if w in abs_ and int(w[1:]) in titles:
            rows.append(r)
            texts.append(DocRecord(id=w, title=titles[int(w[1:])], abstract=abs_[w]).encoder_text())
    enc = encoder()
    t0 = time.time()
    cptr, cc, cv, unk = encode_csr(enc, texts, tok)
    d = prep.vector_diff(sh, np.array(rows), cptr, cc, cv)
    summ = summarize_diff(d)
    grid = []
    for u in TOL_GRID_ULPS:
        for sw in TOL_GRID_SETW:
            grid.append({"max_ulps": u, "setdiff_max_weight": sw, "false_change_share": float(changed_under(d, u, sw).mean())})
    ok = [g for g in grid if g["false_change_share"] < 0.01]
    best = min(ok, key=lambda g: (g["max_ulps"], g["setdiff_max_weight"])) if ok else None
    unreliable = (summ["not_unchanged_exact_share"] > 0.01) or (summ["not_unchanged_tol_share"] > 0.01)
    out = {"what": "P1 control: base text re-encoded with today's runtime vs stored twin vector",
           "sample_seed": "inplace-p1-control", "docs": len(rows), "encode_seconds": round(time.time() - t0, 1),
           "unknown_token_entries": unk, "encoder": "lib.thinclient.doc_encoder PyTorch fp16 CUDA, max_length 128",
           "diff": summ, "verdict": "UNRELIABLE AS DEFINED" if unreliable else "RELIABLE",
           "post_hoc_tolerance_grid": grid, "post_hoc_smallest_tolerance_under_1pct": best,
           "post_hoc_label": "post hoc: chosen after seeing the control; grid = (max |dw| in ulps of the stored f16) x (largest weight allowed among differing components)"}
    (WORK / "p1_control.json").write_text(json.dumps(out, indent=1))
    np.savez(WORK / "p1_control_diff.npz", **d)
    log(json.dumps({k: out[k] for k in ("docs", "diff", "verdict", "post_hoc_smallest_tolerance_under_1pct")}))


def cmd_m7(a):
    sh = ShardView(s01.TWIN)
    tok = load_token_to_id(s01.TWIN)
    ids = np.load(WORK / "shard_ids.npy")
    order = np.argsort(ids)
    sid = ids[order]
    ctrl = json.loads((WORK / "p1_control.json").read_text())
    best = ctrl.get("post_hoc_smallest_tolerance_under_1pct")
    enc = encoder()
    res = {}
    for f in M7_FILES:
        counters, recs = prep.parse_part(Path(f), 2015)
        recs = [r for r in recs if r["out"] is None]
        num = np.array([r["id"] for r in recs], dtype=np.int64)
        pos = np.searchsorted(sid, num)
        pos[pos >= len(sid)] = 0
        inb = sid[pos] == num
        rows = order[pos[inb]]
        texts = [recs[i]["text"] for i in np.flatnonzero(inb)]
        cptr, cc, cv, unk = encode_csr(enc, texts, tok)
        d = prep.vector_diff(sh, rows, cptr, cc, cv)
        n_touch = len(recs)
        n_new = int((~inb).sum())
        ch_exact = int((~d["exact"]).sum())
        ch_tol = int((~(d["same_set"] & (d["max_ulps"] <= 1))).sum())
        r = {"file": f, "slice": "M7 adapter slice, min_year 2015, records routed to shard 0 only",
             "touched_in_slice_shard0": n_touch, "new": n_new, "in_base": int(inb.sum()),
             "vector_changed_exact": ch_exact, "vector_changed_tol": ch_tol,
             "ratio_touched_to_must_encode_exact": n_touch / max(1, n_new + ch_exact),
             "ratio_touched_to_must_encode_tol": n_touch / max(1, n_new + ch_tol),
             "in_base_ratio_touched_to_changed_exact": int(inb.sum()) / max(1, ch_exact),
             "in_base_ratio_touched_to_changed_tol": int(inb.sum()) / max(1, ch_tol),
             "diff": summarize_diff(d)}
        if best:
            chp = int(changed_under(d, best["max_ulps"], best["setdiff_max_weight"]).sum())
            r["post_hoc_tolerance"] = best
            r["vector_changed_post_hoc"] = chp
            r["ratio_touched_to_must_encode_post_hoc"] = n_touch / max(1, n_new + chp)
            r["in_base_ratio_touched_to_changed_post_hoc"] = int(inb.sum()) / max(1, chp)
        res[Path(f).name] = r
        log(json.dumps({k: v for k, v in r.items() if k != "diff"}))
    (WORK / "p1_m7.json").write_text(json.dumps(res, indent=1))


def cmd_record(a):
    out = Path(a.out)
    blob = json.loads(out.read_text()) if out.exists() else {}
    sup = blob.setdefault("supplementary", {}).setdefault("P1", {})
    sup["label"] = "not pre-registered as a bar; definitions pre-registered in 06_INPLACE_SPIKE_PLAN.md second addendum (d4ba6b87) before any P1 number"
    sup["control"] = json.loads((WORK / "p1_control.json").read_text())
    sup["m7_vector"] = json.loads((WORK / "p1_m7.json").read_text())
    sup["git_commit_at_record"] = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    out.write_text(json.dumps(blob, indent=1, default=float) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("control")
    c.add_argument("--n", type=int, default=3000)
    sub.add_parser("m7")
    r = sub.add_parser("record")
    r.add_argument("--out", required=True)
    a = ap.parse_args()
    {"control": cmd_control, "m7": cmd_m7, "record": cmd_record}[a.cmd](a)


if __name__ == "__main__":
    main()
