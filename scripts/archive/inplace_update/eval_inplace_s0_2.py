#!/usr/bin/env python3
# CLOSED MEASURED 2026-09-30 — in-place bit-update spike harness (docs/archive/inplace_update/); evidence kept, pre-registered bars live in source
"""In-place bit updater, Stage 0 bar S0-2: quality under synthetic churn.
Also runs the S0-3 bookkeeping (see eval_inplace_s0_3.py) in the same pass.

BAR (verbatim from docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md, commit 8c239e99):

  ### S0-2 — quality under synthetic churn (Mechanism B, §2.3 of the brief)

  - **Simulation:** apply Q1, then Q1–Q3, then Q1–Q6 to shard 0's posting
    lists per brief §2.3 — deletes free slots; each insert posting takes a
    dead slot, else evicts the list's minimum-weight posting if its weight
    exceeds it, else is dropped; inserts in term-sorted batches per quarter;
    list lengths never grow.
  - **Scoring procedure (identical in every arm):** list-restricted exact
    retrieval — candidates = union of docs in the (simulated) lists of the
    query's 64 terms; score = exact dot product with the doc's forward vector
    (twin f16 values for base docs, the encoded vector for new docs); top-10.
    This isolates list membership (Mechanism B); block/summary approximation
    is S0-3's job.
  - **Rebuild reference R_sim(k):** the same doc set after k quarters, lists
    re-selected by the build's pruning rule (global top `n_postings × dim`
    postings, then per-list cap), same scoring procedure. Deterministic, so
    it carries no build drift.
  - **Base reference A0:** the same scoring procedure on the unchurned served
    lists, with deleted/merged/updated-old ids removed from its ranking and
    the top-10 backfilled from deeper ranks.
  - **Gated metric:** overlap@10(in-place(k), R_sim(k)) on EACH of QA, QT,
    QD, for k ∈ {1, 3, 6}. NDCG@10 on QA for in-place, R_sim and A0,
    recorded, not gated.
  - **Dual-reference reporting:** the verdict comes from R_sim only.
    Recorded beside it for every k: overlap@10(in-place, A0),
    overlap@10(R_sim, A0) (the churn-only gap) and their difference, and the
    real-rebuild ceiling 0.9858 / 0.9870 as context. The ceiling is not
    applied to R_sim (R_sim is a deterministic re-selection, not a real
    SEISMIC build).
  - **Thresholds.** "Passes at k" = overlap@10 ≥ 0.99 on each of QA, QT, QD
    at k quarters. PASS: passes at k = 3. PARTIAL: passes at k = 1, fails at
    k = 3. FAIL: fails at k = 1. Record the first k in {1, 3, 6} where it
    breaks.

Churn model (plan §"Fixed inputs"; everything below is recorded in the
results file):
  Q1 deletions: the real deleted_ids rows in shard 0 with deleted_date in
  [2026-06-17, 2026-09-15], plus N_upd base docs sampled uniformly without
  replacement (seed "inplace-q1") standing in for the updated docs' old
  versions (N_upd = S0-1's ratio estimate for the quarter, *est.*).
  Q1 inserts: N_new + N_upd vectors re-drawn with fresh ids from the pool of
  real encoded Q1-window vectors produced by eval_inplace_s0_1.py prep-encode
  (new-work draws from the new-work vectors, update draws from the updated-
  doc vectors, each weighted by inverse inclusion probability, seed
  "inplace-q1") -> synthetic_reuse: true.
  Q2..Q6: deletions sampled uniformly from live base docs (seed
  "inplace-q<k>") at Q1's RATE (real deletions + update-olds, as a fraction
  of the base) applied to the live base docs; update re-inserts at Q1's
  update rate x live base docs, new works = N_NEW; all re-drawn from the
  same pool (synthetic_reuse: true). A rate, not a count, because a Q1 count
  that is a large share of the base would exhaust the base within a quarter
  or two (decided 2026-09-29 before the first full run, after seeing only
  the first sample file's counters).
  Ties in every top-10: score descending, then doc id ascending (base rows
  before inserted docs), identically in every arm.
  R_sim tie at the global threshold: entries equal to tau are admitted for
  base rows below a row cut chosen so the admitted count matches the quota
  under a uniform-over-rows assumption (the engine's k_largest_by keeps the
  earliest in forward order); R_sim(0) vs the served lists is recorded as the
  fidelity of this re-selection.

Subcommands: prep-queries, run.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts/seismic_testbed"))
sys.path.insert(0, str(REPO / "scripts/experiments"))

from spike.inplace_update import prep  # noqa: E402
from spike.inplace_update.shard import ShardView, load_token_to_id  # noqa: E402
from spike.inplace_update.sim import InplaceSim, Pool, ranges  # noqa: E402
import eval_inplace_s0_1 as s01  # noqa: E402
import eval_inplace_s0_3 as s03  # noqa: E402

TWIN = s01.TWIN
WORK = s01.WORK
CAP_TIES_NOTE = "score desc, id asc"
REBUILD_CEILING = {"QT": 0.9858, "QD": 0.9870}
KS = [1, 2, 3, 4, 5, 6]
KS_QUALITY = [1, 3, 6]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def cmd_prep_queries(a):
    from e6_forward_codec_proto import load_queries
    from lib.opensearch_retriever import encode_splade
    import onnxruntime  # noqa: F401
    qa = json.loads((REPO / "data/eval_results/dense_ablation_queries.json").read_text())
    sets = {"QA": [r["paraphrase"] for r in qa],
            "QT": [r["query"] for r in json.loads((REPO / "data/sfu_eval_queries.json").read_text())],
            "QD": load_queries(100, REPO / "data/eval_results/diverse_queries.json")}
    assert len(sets["QA"]) == 240 and len(sets["QT"]) == 120 and len(sets["QD"]) == 100
    tok = load_token_to_id(TWIN)
    out = {}
    for name, qs in sets.items():
        rows = []
        for q in qs:
            v = encode_splade(q, "models/splade_onnx_fp16")
            assert v, f"empty SPLADE encoding for {q!r} (encoder not loaded?)"
            top = sorted(v.items(), key=lambda x: -x[1])[:64]
            known = sorted((int(tok[t]), float(w)) for t, w in top if t in tok)
            rows.append({"q": q, "terms": [t for t, _ in known], "w": [w for _, w in known],
                         "n_top": len(top), "n_known": len(known)})
        out[name] = rows
    out["_meta"] = {"qa_meta": [{"judge_key": r["judge_key"], "query_type": r["query_type"]} for r in qa]}
    (WORK / "queries.json").write_text(json.dumps(out))
    log({k: len(v) for k, v in out.items() if k != "_meta"})


def load_pool(files: list[str], dim: int):
    cp, cc, cv, cls, wt, src = [0], [], [], [], [], []
    for k in files:
        d = s01.load_part(k)
        cptr = d["cptr"]
        for i in range(len(d["cls_upd"])):
            a, b = int(cptr[i]), int(cptr[i + 1])
            if b == a:
                continue
            cc.append(d["comp"][a:b])
            cv.append(d["val"][a:b])
            cp.append(cp[-1] + (b - a))
            cls.append(bool(d["cls_upd"][i]))
            wt.append(1.0 / float(d["prob"][i]))
            src.append(k)
    pool = Pool(np.array(cp), np.concatenate(cc), np.concatenate(cv).astype(np.float32), dim)
    return pool, np.array(cls), np.array(wt), src


def pool_hist(pool: Pool, counts: np.ndarray) -> np.ndarray:
    w = np.repeat(counts.astype(np.float64), np.diff(pool.cptr))
    bits = pool.val.astype(np.float16).view(np.uint16)
    return np.bincount(bits, weights=w, minlength=65536)


def rows_hist(sh: ShardView, rows: np.ndarray) -> np.ndarray:
    h = np.zeros(65536, dtype=np.int64)
    o = sh.offs_i64
    rows = np.sort(rows)
    for i in range(0, len(rows), 200_000):
        r = rows[i:i + 200_000]
        idx = ranges(o[r], o[r + 1])
        h += np.bincount(np.asarray(sh.vals[idx]).view(np.uint16), minlength=65536)
    return h


def f16_order():
    """uint16 bit patterns of non-negative finite f16 sorted by value."""
    bits = np.arange(0, 0x7C00, dtype=np.uint16)
    return bits


def tau_from_hist(hist: np.ndarray, K: int):
    """Global threshold of k_largest over non-negative f16 values: returns
    (tau as f16, count strictly above, count equal)."""
    bits = f16_order()
    h = hist[bits]
    above = np.cumsum(h[::-1])[::-1]
    idx = int(np.flatnonzero(above >= K)[-1])
    gt = float(above[idx + 1]) if idx + 1 < len(bits) else 0.0
    eq = float(h[idx])
    return np.uint16(bits[idx]).view(np.float16), gt, eq


def lock_pages(log):
    """mlockall(MCL_CURRENT | MCL_FUTURE | MCL_ONFAULT): the 2026-09-30 18:15Z full-scale run had 15.3 GB of its
    working set swapped out during the R_sim sort and scored at ~40 queries/45 min paging it back in (swap partition
    16 GB, full; container cannot swapoff). Pages touched by this process stay resident; the peak is bounded by the
    RSim constructor (inputs 5.4 GB + argsort permutation 5.4 GB + one permuted copy) instead of the old 21 GB."""
    import ctypes
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    if soft != hard:
        resource.setrlimit(resource.RLIMIT_MEMLOCK, (hard, hard))
    libc = ctypes.CDLL(None, use_errno=True)
    rc = libc.mlockall(1 | 2 | 4)
    log("mlockall", "ok" if rc == 0 else f"failed errno {ctypes.get_errno()} (running unlocked)")


class RSim:
    """R_sim list selection for the lists in T, from the forward-scan entries
    (base) and the inserted copies."""

    def __init__(self, sh, T, frow, fcomp, fval, cap, K):
        self.sh = sh
        self.cap = cap
        self.K = K
        self.N = sh.n_docs
        m = np.isin(fcomp, T)
        if not m.all():
            frow, fcomp, fval = frow[m], fcomp[m], fval[m]
        del m
        o = np.argsort(fcomp, kind="stable")
        c = fcomp[o]
        fcomp = None
        r = frow[o]
        frow = None
        v = fval[o]
        fval = None
        del o
        ptr = np.searchsorted(c, np.arange(len(sh.plm) + 1))
        for t in np.flatnonzero(np.diff(ptr)).tolist():
            a, b = int(ptr[t]), int(ptr[t + 1])
            oo = np.lexsort((r[a:b], -v[a:b].astype(np.float32)))
            r[a:b] = r[a:b][oo]
            v[a:b] = v[a:b][oo]
        self.r, self.c, self.v, self.ptr = r, c, v, ptr

    def lists(self, T, tau, gt, eq, del_q, k, ins, pool, include_inserts=True):
        """del_q: int8 per base row (0 = alive through quarter 6, else the
        quarter it was deleted). ins: dict with arrays ids, pool, quarter.
        Returns dict t -> ids (slot order irrelevant)."""
        quota = self.K - gt
        rcut = self.N * min(1.0, max(0.0, quota / eq)) if eq > 0 else 0
        tau32 = np.float32(tau)
        out = {}
        P = pool
        if include_inserts and ins is not None:
            iq = ins["quarter"]
            live_ins = iq <= k
            o = np.argsort(ins["pool"][live_ins], kind="stable")
            sp = ins["pool"][live_ins][o]
            sid = ins["ids"][live_ins][o]
            gs = np.searchsorted(sp, np.arange(P.n), side="left")
            ge = np.searchsorted(sp, np.arange(P.n), side="right")
        for t in T.tolist():
            a, b = int(self.ptr[t]), int(self.ptr[t + 1])
            r, v = self.r[a:b], self.v[a:b]
            alive = (del_q[r] == 0) | (del_q[r] > k)
            v32 = v.astype(np.float32)
            keep = alive & ((v32 > tau32) | ((v32 == tau32) & (r < rcut)))
            br, bv = r[keep], v32[keep]
            if include_inserts and ins is not None:
                pa, pb = int(P.t_ptr[t]), int(P.t_ptr[t + 1])
                pd, pv = P.t_doc[pa:pb], P.t_val[pa:pb]
                sel = (pv >= tau32) & (ge[pd] > gs[pd])
                pd, pv = pd[sel], pv[sel]
                cum = np.cumsum(ge[pd] - gs[pd])
                j = int(np.searchsorted(cum, self.cap, side="left"))
                if j < len(pv):
                    j = int(np.searchsorted(-pv, -pv[j], side="right"))
                pd, pv = pd[:j], pv[:j]
                gi = ranges(gs[pd], ge[pd])
                iid = sid[gi]
                iv = np.repeat(pv, ge[pd] - gs[pd])
                ids = np.concatenate([br, iid])
                vals = np.concatenate([bv, iv])
            else:
                ids, vals = br, bv
            if len(ids) > self.cap:
                o = np.lexsort((ids, -vals))[: self.cap]
                ids = ids[o]
            out[t] = ids.astype(np.int64, copy=False)
        return out


def score_base_rows(sh, rows, qdense):
    o = sh.offs_i64
    out = np.zeros(len(rows), dtype=np.float32)
    for i in range(0, len(rows), 100_000):
        r = rows[i:i + 100_000]
        st, ln = o[r], o[r + 1] - o[r]
        idx = ranges(st, st + ln)
        c = np.asarray(sh.comps[idx]).astype(np.int64)
        v = np.asarray(sh.vals[idx]).astype(np.float32)
        seg = np.repeat(np.arange(len(r)), ln)
        out[i:i + len(r)] = np.bincount(seg, weights=v * qdense[c], minlength=len(r))
    return out


def topk(ids: np.ndarray, sc: np.ndarray, k: int):
    if len(ids) == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.float32)
    o = np.lexsort((ids, -sc))[:k]
    return ids[o], sc[o]


def ndcg10(ranked_wids: list[int], grades: dict[int, int], ideal_pool: list[int]) -> float | None:
    gains = [2 ** grades.get(w, 0) - 1 for w in ranked_wids[:10]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted((2 ** grades[w] - 1 for w in ideal_pool), reverse=True)[:10]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else None


def cmd_run(a):
    t_start = time.time()
    lock_pages(log)
    rng_master = {}
    sh = ShardView(TWIN)
    n_lists = sh.n_lists
    cfg = json.loads((TWIN / "config.json").read_text())
    gt_cfg = cfg["pruning"]["GlobalThreshold"]
    cap = int(gt_cfg["n_postings"] * gt_cfg["max_fraction"])
    K = int(gt_cfg["n_postings"]) * n_lists
    ptr, prow, pw = prep.postings_table(sh, WORK)
    N = sh.n_docs
    Q = json.loads((WORK / "queries.json").read_text())
    sets = ["QA", "QT", "QD"]
    T = np.unique(np.concatenate([np.array(q["terms"], dtype=np.int64) for s in sets for q in Q[s]]))
    log("T lists", len(T), "postings in T", int(sum(ptr[t + 1] - ptr[t] for t in T)))

    tau0_min = float(pw.astype(np.float32).min())
    floor = a.floor_frac * tau0_min
    tmask = np.zeros(n_lists + 1, dtype=bool)
    tmask[T] = True
    hist0, frow, fcomp, fval = prep.scan_forward(sh, tmask, floor, WORK, f"T{len(T)}_floor{floor:.4f}", log=log)
    tau0, gt0, eq0 = tau_from_hist(hist0, K)
    log("tau0", float(tau0), "min posting", tau0_min, "gt", gt0, "eq", eq0)

    man = json.loads((WORK / "manifest_works_2026-09-23.json").read_text())
    wf = s01.window_files(man)
    N_window = sum(e["meta"]["record_count"] for e in wf)
    keys = [s01.part_key(e["url"]) for e in s01.sample_files(man)]
    keys = [k for k in keys if (s01.PARTS_OUT / (k.replace('/', '_') + '.npz')).exists()]
    recs = {s01.part_key(e["url"]): e["meta"]["record_count"] for e in man["files"]}
    R = sum(recs[k] for k in keys)
    n_upd_q = N_window / R * sum(s01.load_part(k)["counters"]["updated"] for k in keys)
    n_new_q = N_window / R * sum(s01.load_part(k)["counters"]["new"] for k in keys)
    N_UPD, N_NEW = int(round(n_upd_q)), int(round(n_new_q))
    dl = prep.deleted_rows(np.load(WORK / "shard_ids.npy"), WORK / "deleted_ids.csv.gz",
                           s01.WINDOW[0], s01.WINDOW[1], WORK)
    real_del = dl["rows"]
    log("Q1 est: updated", N_UPD, "new", N_NEW, "real deletions in shard", len(real_del))

    pool_files = keys
    pool, pcls, pwt, psrc = load_pool(pool_files, n_lists)
    log("pool vectors", pool.n, "upd", int(pcls.sum()), "new", int((~pcls).sum()))

    scale = a.scale
    del_q = np.zeros(N, dtype=np.int8)
    ins = {"ids": [], "pool": [], "quarter": []}
    sim = InplaceSim(sh, ptr, prow, pw, T, pool, track_inflation=True)
    summ_cache: dict = {}

    def summaries(t):
        s = summ_cache.get(t)
        if s is None:
            if len(summ_cache) > 3000:
                summ_cache.clear()
            s = sh.summary(t)
            summ_cache[t] = s
        return s

    hist = hist0.copy()
    per_q = {}
    snaps = {}
    codes = {}
    taus = {}
    ins_hist_cum = np.zeros(65536)
    sample_blocks = {}
    rate_del = len(real_del) / N
    rate_upd = min(1.0, N_UPD / N)
    sched = {}
    for k in KS:
        rng = np.random.default_rng(list(f"inplace-q{k}".encode()))
        alive = np.flatnonzero(del_q == 0)
        if k == 1:
            rd = real_del if scale >= 1 else rng.choice(real_del, int(round(scale * len(real_del))), replace=False)
            rest = np.setdiff1d(alive, rd, assume_unique=False)
            n_upd_k = min(len(rest), int(round(scale * N_UPD)))
            upd_old = rng.choice(rest, n_upd_k, replace=False)
            drows = np.concatenate([rd, upd_old])
        else:
            n_upd_k = int(round(rate_upd * len(alive)))
            n_d = min(len(alive), int(round((rate_del + rate_upd) * len(alive))))
            drows = rng.choice(alive, n_d, replace=False)
        del_q[drows] = k
        dstat = sim.delete(drows)
        hist -= rows_hist(sh, drows)
        n_ins_new = int(round(scale * N_NEW))
        n_ins_upd = n_upd_k
        sched[k] = {"deleted_base_rows": int(len(drows)), "of_which_update_old": int(n_upd_k),
                    "inserted_new": n_ins_new, "inserted_update": n_ins_upd, "alive_base_before": int(len(alive))}
        pn = np.flatnonzero(~pcls)
        pu = np.flatnonzero(pcls)
        draw = np.concatenate([
            rng.choice(pn, n_ins_new, replace=True, p=pwt[pn] / pwt[pn].sum()) if n_ins_new else np.zeros(0, np.int64),
            rng.choice(pu, n_ins_upd, replace=True, p=pwt[pu] / pwt[pu].sum()) if n_ins_upd else np.zeros(0, np.int64)])
        first_id = sim.next_id
        istat = sim.insert(draw, summaries=summaries, sample_blocks=sample_blocks if k == 1 else None)
        ins["ids"].append(first_id + np.arange(len(draw), dtype=np.int64))
        ins["pool"].append(draw)
        ins["quarter"].append(np.full(len(draw), k, dtype=np.int8))
        ins_hist_cum += pool_hist(pool, np.bincount(draw, minlength=pool.n))
        hist_k = hist + ins_hist_cum
        tau_k, gt_k, eq_k = tau_from_hist(hist_k, K)
        tau_del, gt_del, eq_del = tau_from_hist(hist, K)
        assert float(tau_k) >= floor and float(tau_del) >= floor, ("tau below scan floor", float(tau_k), float(tau_del), floor)
        taus[k] = {"tau": float(tau_k), "gt": gt_k, "eq": eq_k, "tau_delonly": float(tau_del), "gt_delonly": gt_del, "eq_delonly": eq_del}
        codes[k] = {t: sim.codes(t) for t in T.tolist()}
        per_q[k] = {"deletions": dstat, "inserts": istat, "dead_fraction_T": sim.dead_fraction(),
                    "mean_m_T_blocks": float(np.mean(np.concatenate([sim.m[t] for t in T.tolist() if len(sim.m[t])]))),
                    "saturated_blocks_T": int(sum(int((codes[k][t] < 0).sum()) for t in T.tolist())),
                    "blocks_T": int(sum(len(codes[k][t]) for t in T.tolist())),
                    "tau": taus[k]}
        if k in KS_QUALITY:
            snaps[k] = sim.snapshot_lists()
        log("quarter", k, json.dumps(per_q[k]))
        gc.collect()
    for key in ins:
        ins[key] = np.concatenate(ins[key])

    prng = np.random.default_rng(list(b"inplace-placement"))
    pairs = [(t, b_, p_) for t, lst in sample_blocks.items() for blk, pd in lst for b_, p_ in zip(blk.tolist(), pd.tolist())]
    sample_blocks.clear()
    pick = prng.choice(len(pairs), min(2000, len(pairs)), replace=False) if pairs else []
    other = 0
    for i in pick:
        t, b_, p_ = pairs[int(i)]
        a_, e_ = int(pool.cptr[p_]), int(pool.cptr[p_ + 1])
        dts = summaries(t).dots(pool.comp[a_:e_], pool.val[a_:e_])
        other += int(int(np.argmax(dts)) != b_)
    placement = {"sampled_placed_postings_Q1": int(len(pick)), "placed_in_other_block_than_best_summary_dot": other,
                 "share": other / max(1, len(pick)),
                 "proxy": "best block = argmax_b dot(old summary_b, new doc vector) over the list's blocks; "
                          "a fresh RandomKmeans clustering is not re-run (not simulated)", "seed": "inplace-placement"}
    del pairs
    log("placement", placement)

    st = {"T": T, "del_q": del_q, "ins_ids": ins["ids"], "ins_pool": ins["pool"], "ins_quarter": ins["quarter"]}
    for k in KS_QUALITY:
        st[f"snap{k}_ptr"] = np.concatenate([[0], np.cumsum([len(snaps[k][t]) for t in T.tolist()])])
        st[f"snap{k}_ids"] = np.concatenate([snaps[k][t] for t in T.tolist()])
        st[f"code{k}_ptr"] = np.concatenate([[0], np.cumsum([len(codes[k][t]) for t in T.tolist()])])
        st[f"code{k}"] = np.concatenate([codes[k][t] for t in T.tolist()]).astype(np.int16)
    np.savez(WORK / f"sim_state_scale{scale}.npz", **st)
    del st
    rs = RSim(sh, T, frow, fcomp, fval, cap, K)
    del frow, fcomp, fval
    gc.collect()
    rsim0 = rs.lists(T, tau0, gt0, eq0, np.zeros(N, np.int8), 0, None, pool, include_inserts=False)
    fid_same = fid_tot = fid_inter = 0
    for t in T.tolist():
        base = prow[ptr[t]:ptr[t + 1]]
        fid_tot += len(base)
        fid_inter += len(np.intersect1d(base, rsim0[t]))
        fid_same += int(len(base) == len(rsim0[t]) and np.array_equal(np.sort(base), np.sort(rsim0[t])))
    fidelity = {"lists_T": int(len(T)), "lists_identical": fid_same, "postings_base_T": fid_tot,
                "postings_shared": fid_inter, "share": fid_inter / max(1, fid_tot)}
    log("R_sim(0) fidelity", fidelity)
    rsim = {}
    rsim_del = {}
    for k in KS_QUALITY:
        tk = taus[k]
        rsim[k] = rs.lists(T, np.float16(tk["tau"]), tk["gt"], tk["eq"], del_q, k, ins, pool)
        rsim_del[k] = rs.lists(T, np.float16(tk["tau_delonly"]), tk["gt_delonly"], tk["eq_delonly"], del_q, k, None,
                               pool, include_inserts=False)
    log("R_sim lists built")

    wid = np.load(WORK / "shard_ids.npy")
    qrels = json.loads((REPO / "data/eval_results/dense_ablation_qrels_20260817.json").read_text())["topics"]
    qa_meta = Q["_meta"]["qa_meta"]
    wid_sorted = np.sort(wid)

    def in_shard(ws):
        a_ = np.array(ws, dtype=np.int64)
        p = np.searchsorted(wid_sorted, a_)
        p[p >= len(wid_sorted)] = 0
        return wid_sorted[p] == a_

    res_q = {s: [] for s in sets}
    ins_ids = ins["ids"]
    ins_pool_arr = ins["pool"]
    ins_q = ins["quarter"]
    n_eval = 0
    for s in sets:
        for qi, q in enumerate(Q[s]):
            terms = np.array(q["terms"], dtype=np.int64)
            qw = np.array(q["w"], dtype=np.float32)
            qdense = np.zeros(n_lists + 1, dtype=np.float32)
            qdense[terms] = qw
            pdots = pool.dots(qdense)
            lists_by_arm = {"A0_0": [prow[ptr[t]:ptr[t + 1]].astype(np.int64) for t in terms]}
            for k in KS_QUALITY:
                lists_by_arm[f"IP_{k}"] = [snaps[k][t][snaps[k][t] >= 0] for t in terms]
                lists_by_arm[f"RS_{k}"] = [rsim[k][t] for t in terms]
                lists_by_arm[f"RD_{k}"] = [rsim_del[k][t] for t in terms]
            allc = np.unique(np.concatenate([np.concatenate(v) if v else np.zeros(0, np.int64)
                                             for v in lists_by_arm.values()]))
            base_c = allc[allc < N]
            ins_c = allc[allc >= N]
            sc_base = score_base_rows(sh, base_c, qdense)
            sc_ins = pdots[ins_pool_arr[ins_c - N]] if len(ins_c) else np.zeros(0, np.float32)
            cand = np.concatenate([base_c, ins_c])
            csc = np.concatenate([sc_base, sc_ins]).astype(np.float32)

            def rank(ids_list, k_=10, alive_k=None):
                ids = np.unique(np.concatenate(ids_list)) if ids_list else np.zeros(0, np.int64)
                if alive_k is not None:
                    b = ids[ids < N]
                    ids = b[(del_q[b] == 0) | (del_q[b] > alive_k)]
                pos = np.searchsorted(cand, ids)
                return topk(ids, csc[pos], k_)

            a0_ids200, a0_sc200 = rank(lists_by_arm["A0_0"], 200)
            theta = float(a0_sc200[-1]) if len(a0_sc200) == 200 else 0.0
            row = {"theta": theta, "top10": {}}
            row["top10"]["A0_0"] = a0_ids200[:10].tolist()
            for k in KS_QUALITY:
                row["top10"][f"A0_{k}"] = rank(lists_by_arm["A0_0"], 10, alive_k=k)[0].tolist()
                for arm in ("IP", "RS", "RD"):
                    row["top10"][f"{arm}_{k}"] = rank(lists_by_arm[f"{arm}_{k}"])[0].tolist()
            dots_t = []
            for t in terms.tolist():
                s_ = sh.summary(t)
                dots_t.append(s_.dots(terms, qw))
            row["miss"] = {}
            base_set = lists_by_arm["A0_0"]
            base_u = np.unique(np.concatenate(base_set)) if base_set else np.zeros(0, np.int64)
            for k in KS_QUALITY:
                ipl = lists_by_arm[f"IP_{k}"]
                ip_u = np.unique(np.concatenate(ipl)) if ipl else np.zeros(0, np.int64)
                ip_top = set(row["top10"][f"IP_{k}"])
                mc = {"missing_slots_total": 0, "inserted_not_in_inplace_lists": 0,
                      "base_evicted_by_insert": 0, "base_never_in_base_lists_refilled_by_rebuild": 0,
                      "candidate_but_displaced": 0}
                for d_ in row["top10"][f"RS_{k}"]:
                    if d_ in ip_top:
                        continue
                    mc["missing_slots_total"] += 1
                    in_ip = len(ip_u) and ip_u[min(np.searchsorted(ip_u, d_), len(ip_u) - 1)] == d_
                    if in_ip:
                        mc["candidate_but_displaced"] += 1
                    elif d_ >= N:
                        mc["inserted_not_in_inplace_lists"] += 1
                    elif len(base_u) and base_u[min(np.searchsorted(base_u, d_), len(base_u) - 1)] == d_:
                        mc["base_evicted_by_insert"] += 1
                    else:
                        mc["base_never_in_base_lists_refilled_by_rebuild"] += 1
                row["miss"][k] = mc
            row["V0"] = s03.visits_for_query(dots_t, [None] * len(terms), theta)
            row["V"] = {k: s03.visits_for_query(dots_t, [codes[k][t] for t in terms.tolist()], theta) for k in KS}
            if s == "QA":
                jk = qa_meta[qi]["judge_key"]
                docs = qrels[jk]["docs"]
                grades = {int(d_["openalex_id"][1:]): int(d_["grade"]) for d_ in docs}
                judged_ids = list(grades)
                ins_mask = in_shard(judged_ids)
                pool_ideal = [w for w, m_ in zip(judged_ids, ins_mask) if m_]
                row["ndcg"] = {}
                row["judged10"] = {}
                for arm, ids in row["top10"].items():
                    wl = [int(wid[i]) if i < N else -1 for i in ids]
                    row["ndcg"][arm] = ndcg10(wl, grades, pool_ideal)
                    row["judged10"][arm] = sum(1 for w in wl if w in grades)
                row["topic"] = jk
            res_q[s].append(row)
            n_eval += 1
            if n_eval % 40 == 0:
                log("evaluated", n_eval)

    def ov(x, y):
        return len(set(x) & set(y)) / 10.0

    s02 = {"per_k": {}, "sets": sets}
    passes = {}
    for k in KS_QUALITY:
        pk = {}
        ok = True
        for s in sets:
            rows = res_q[s]
            o_ip_rs = float(np.mean([ov(r["top10"][f"IP_{k}"], r["top10"][f"RS_{k}"]) for r in rows]))
            o_ip_a0 = float(np.mean([ov(r["top10"][f"IP_{k}"], r["top10"][f"A0_{k}"]) for r in rows]))
            o_rs_a0 = float(np.mean([ov(r["top10"][f"RS_{k}"], r["top10"][f"A0_{k}"]) for r in rows]))
            o_rd_a0 = float(np.mean([ov(r["top10"][f"A0_{k}"], r["top10"][f"RD_{k}"]) for r in rows]))
            o_ip_a00 = float(np.mean([ov(r["top10"][f"IP_{k}"], r["top10"]["A0_0"]) for r in rows]))
            def ck(ids):
                return {i if i < N else N + int(ins_pool_arr[i - N]) for i in ids}
            o_ck = float(np.mean([len(ck(r["top10"][f"IP_{k}"]) & ck(r["top10"][f"RS_{k}"])) / max(1, len(ck(r["top10"][f"RS_{k}"])))
                                  for r in rows]))
            pk.setdefault("supp_content_key_overlap_note", "not pre-registered: inserted copies of one pool vector collapsed "
                          "to one key; share of R_sim's distinct top-10 contents present in in-place's top-10")
            pk[s] = {"overlap10_inplace_vs_Rsim": o_ip_rs, "supp_content_key_overlap_inplace_vs_Rsim": o_ck,
                     "Rsim_top10_inserted_share": float(np.mean([sum(1 for i in r["top10"][f"RS_{k}"] if i >= N) / 10 for r in rows])), "overlap10_inplace_vs_A0": o_ip_a0,
                     "overlap10_Rsim_vs_A0": o_rs_a0, "diff_inplaceA0_minus_RsimA0": o_ip_a0 - o_rs_a0,
                     "overlap10_inplace_vs_A0_unchurned": o_ip_a00,
                     "min_overlap10_inplace_vs_Rsim": float(min(ov(r["top10"][f"IP_{k}"], r["top10"][f"RS_{k}"]) for r in rows)),
                     "passes_0.99": o_ip_rs >= 0.99,
                     "supp_deletions_only_overlap10_A0_vs_Rsim_delonly": o_rd_a0}
            ok &= o_ip_rs >= 0.99
        pk["passes_all_sets"] = ok
        passes[k] = ok
        qa = res_q["QA"]
        topics = sorted({r["topic"] for r in qa})
        nd = {}
        for arm in ("IP", "RS", "A0"):
            per_topic = []
            for tp in topics:
                vals = [r["ndcg"][f"{arm}_{k}"] for r in qa if r["topic"] == tp and r["ndcg"][f"{arm}_{k}"] is not None]
                per_topic.append(np.mean(vals) if vals else np.nan)
            nd[arm] = np.array(per_topic)
        boot = np.random.default_rng(0)
        valid = ~np.isnan(nd["IP"]) & ~np.isnan(nd["RS"]) & ~np.isnan(nd["A0"])
        idx = np.flatnonzero(valid)
        bs = boot.integers(0, len(idx), (10_000, len(idx)))
        def ci(x):
            m = x[idx][bs].mean(axis=1)
            return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]
        pk["ndcg10_QA"] = {arm: {"mean": float(np.nanmean(nd[arm][idx])), "ci95": ci(nd[arm])} for arm in nd}
        pk["ndcg10_QA"]["delta_IP_minus_RS"] = {"mean": float((nd["IP"] - nd["RS"])[idx].mean()), "ci95": ci(nd["IP"] - nd["RS"])}
        pk["ndcg10_QA"]["delta_IP_minus_A0"] = {"mean": float((nd["IP"] - nd["A0"])[idx].mean()), "ci95": ci(nd["IP"] - nd["A0"])}
        pk["ndcg10_QA"]["topics_used"] = int(len(idx))
        pk["judged10_QA_mean"] = {arm: float(np.mean([r["judged10"][f"{arm}_{k}"] for r in qa])) for arm in ("IP", "RS", "A0")}
        cats = {}
        for s in sets:
            for r in res_q[s]:
                for c_, v_ in r["miss"][k].items():
                    cats[c_] = cats.get(c_, 0) + v_
        pk["supp_missing_slot_attribution_vs_Rsim"] = cats
        s02["per_k"][k] = pk
    first_break = next((k for k in KS_QUALITY if not passes[k]), None)
    verdict = "PASS" if passes[3] and passes[1] else ("PARTIAL" if passes[1] else "FAIL")

    ratios = {s: {} for s in sets}
    s03res = {"per_set": {}}
    for s in sets:
        V0 = sum(r["V0"] for r in res_q[s])
        s03res["per_set"][s] = {"V0": V0}
        for k in KS:
            Vk = sum(r["V"][k] for r in res_q[s])
            ratios[s][k] = Vk / V0 - 1 if V0 else float("inf")
            s03res["per_set"][s][f"V{k}"] = Vk
            s03res["per_set"][s][f"ratio_minus_1_k{k}"] = ratios[s][k]
    v3, tstar = s03.verdict(ratios)
    s03res.update({"T_star": tstar, "verdict": v3,
                   "at_T_star": ({"dead_fraction_T": per_q[tstar]["dead_fraction_T"],
                                  "mean_m_T_blocks": per_q[tstar]["mean_m_T_blocks"]} if tstar else None),
                   "per_quarter_inflation": {k: {x: per_q[k][x] for x in ("mean_m_T_blocks", "saturated_blocks_T", "blocks_T", "dead_fraction_T")}
                                             | {"blind_components": per_q[k]["inserts"]["blind_components"],
                                                "blind_mass": per_q[k]["inserts"]["blind_mass"],
                                                "own_term_absent_from_block_summary": per_q[k]["inserts"]["own_term_absent_from_block_summary"],
                                                "placed": per_q[k]["inserts"]["placed"]} for k in KS},
                   "theta": "k'=200-th score of the unchurned A0 list-restricted exact run",
                   "heap_factor": s03.HEAP_FACTOR})

    commit = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    common = {"measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "git_commit_at_run": commit,
              "script": "scripts/experiments/eval_inplace_s0_2.py", "scale": scale,
              "churn": {"Q1_real_deletions_in_shard": int(len(real_del)), "N_UPD_est": N_UPD, "N_NEW_est": N_NEW,
                        "schedule": {str(k): sched[k] for k in KS},
                        "later_quarter_rule": "k>=2: deletions = (real Q1 deletion rate + Q1 update rate) x live base docs, "
                                              "update re-inserts = Q1 update rate x live base docs, new = N_NEW (rates = Q1 counts / base docs)",
                        "pool_vectors": int(pool.n), "pool_upd": int(pcls.sum()), "pool_new": int((~pcls).sum()),
                        "pool_files": pool_files, "synthetic_reuse": True,
                        "reuse_factor_Q1_inserts_per_pool_vector": (sched[1]["inserted_new"] + sched[1]["inserted_update"]) / max(1, pool.n),
                        "deletions_meta": dl["meta"]},
              "lists_T": int(len(T)), "cap": cap, "K_global": K, "tau0": float(tau0), "tau0_gt": gt0, "tau0_eq": eq0,
              "Rsim0_fidelity_vs_served_lists": fidelity, "per_quarter": {str(k): per_q[k] for k in KS},
              "supp_placement": placement}
    out = Path(a.out)
    blob = json.loads(out.read_text()) if out.exists() else {}
    blob["s0_2"] = {"bar": "S0-2 quality under synthetic churn (06_INPLACE_SPIKE_PLAN.md @ 8c239e99)", **common,
                    "results": {str(k): v for k, v in s02["per_k"].items()}, "first_break_k": first_break,
                    "rebuild_ceiling_context": REBUILD_CEILING, "verdict": verdict,
                    "threshold": "passes at k = overlap@10(in-place, R_sim) >= 0.99 on each of QA, QT, QD; PASS k=3, PARTIAL k=1 only, FAIL k=1"}
    blob["s0_3"] = {"bar": "S0-3 block visits vs bound inflation (06_INPLACE_SPIKE_PLAN.md @ 8c239e99)", **{k_: common[k_] for k_ in ("measured_utc", "git_commit_at_run", "scale")},
                    "script": "scripts/experiments/eval_inplace_s0_3.py (visit counter, verdict) via eval_inplace_s0_2.py run",
                    **s03res, "threshold": "PASS T* >= 1 (V(1)/V(0)-1 <= 0.10 on each of QA, QT, QD)"}
    blob.setdefault("_per_query", {})["s0_2"] = {s: [{"theta": r["theta"], "V0": r["V0"], "V": r["V"]} for r in res_q[s]] for s in sets}
    out.write_text(json.dumps(blob, indent=1, default=float) + "\n")
    import pickle
    with open(WORK / f"s0_2_perquery_scale{scale}.pkl", "wb") as fh:
        pickle.dump({"res_q": res_q, "N": N}, fh)
    log("S0-2", verdict, "first break", first_break, "S0-3", v3, "T*", tstar, "wall", round(time.time() - t_start))


def exhaustive_base_topM(sh, qs, M, log=log):
    """Exact dot-product top-M base rows per query over the whole forward."""
    import scipy.sparse as sp
    n_lists = sh.n_lists
    nq = len(qs)
    Qm = np.zeros((n_lists + 1, nq), dtype=np.float32)
    for i, (terms, w) in enumerate(qs):
        Qm[terms, i] = w
    tmask = Qm.any(axis=1)
    best_r = np.full((nq, 0), -1, dtype=np.int64)
    best_s = np.full((nq, 0), -np.inf, dtype=np.float32)
    o = sh.offs_i64
    N = sh.n_docs
    step = 300_000
    t0 = time.time()
    for r0 in range(0, N, step):
        r1 = min(N, r0 + step)
        a, b = int(o[r0]), int(o[r1])
        c = np.asarray(sh.comps[a:b]).astype(np.int64)
        v = np.asarray(sh.vals[a:b]).astype(np.float32)
        rr = np.repeat(np.arange(r1 - r0, dtype=np.int64), np.diff(o[r0:r1 + 1]))
        m = tmask[c]
        X = sp.csr_matrix((v[m], (rr[m], c[m])), shape=(r1 - r0, n_lists + 1))
        S = np.asarray(X @ Qm).T
        kk = min(M, r1 - r0)
        part = np.argpartition(-S, kk - 1, axis=1)[:, :kk]
        ps = np.take_along_axis(S, part, axis=1)
        allr = np.concatenate([best_r, part + r0], axis=1)
        alls = np.concatenate([best_s, ps], axis=1)
        keep = np.argsort(-alls, axis=1, kind="stable")[:, :M]
        best_r = np.take_along_axis(allr, keep, axis=1)
        best_s = np.take_along_axis(alls, keep, axis=1)
        if (r0 // step) % 10 == 0:
            log(f"[exhaustive] rows {r1}/{N} {time.time() - t0:.0f}s")
    return best_r, best_s


def cmd_supp_traversal(a):
    """SUPPLEMENTARY (not pre-registered; added 2026-09-29 at the
    coordinator's request, before the first S0 real-data run): overlap@10 of
    the engine traversal (Python replay of MmapSeismicIndex: first term
    sorted, heap_factor 0.8, k'=200) over the in-place state with the
    inflation byte applied, vs exhaustive exact scoring of the same doc set.
    QT only (120 queries), k in {0, 1, 3, 6}."""
    from spike.inplace_update.search import IndexState, ListState, search
    sh = ShardView(TWIN)
    N = sh.n_docs
    n_lists = sh.n_lists
    scale = a.scale
    z = np.load(WORK / f"sim_state_scale{scale}.npz")
    T = z["T"]
    del_q = z["del_q"]
    ins_ids, ins_pool, ins_q = z["ins_ids"], z["ins_pool"], z["ins_quarter"]
    man = json.loads((WORK / "manifest_works_2026-09-23.json").read_text())
    keys = [s01.part_key(e["url"]) for e in s01.sample_files(man)]
    keys = [k for k in keys if (s01.PARTS_OUT / (k.replace('/', '_') + '.npz')).exists()]
    pool, pcls, pwt, psrc = load_pool(keys, n_lists)
    Q = json.loads((WORK / "queries.json").read_text())
    qs = [(np.array(q["terms"], dtype=np.int64), np.array(q["w"], dtype=np.float32)) for q in Q["QT"]]
    M = 3000
    ex_r, ex_s = exhaustive_base_topM(sh, qs, M)
    log("exhaustive done")

    class State(IndexState):
        def __init__(self, sh, pdots, ipool):
            super().__init__(sh)
            self.pdots = pdots
            self.ipool = ipool

        def summary(self, t):
            s = self._summ_cache.get(t)
            if s is None:
                if len(self._summ_cache) > 1500:
                    self._summ_cache.clear()
                s = self.shard.summary(t)
                self._summ_cache[t] = s
            return s

        def score_rows(self, rows, qdense):
            out = np.zeros(len(rows), dtype=np.float32)
            b = rows < N
            if b.any():
                out[b] = score_base_rows(self.shard, rows[b], qdense)
            if (~b).any():
                out[~b] = self.pdots[self.ipool[rows[~b] - N]]
            return out

        def block_dots(self, t, qc, qv, qdense):
            d = self.summary(t).dots(qc, qv)
            ls = self.lists.get(t)
            if ls is not None and ls.mult is not None:
                sat = np.isinf(ls.mult)
                d = (d * np.where(sat, 1.0, ls.mult)).astype(np.float32)
                d[sat] = np.inf
            return d

    out = {}
    tpos = {int(t): i for i, t in enumerate(T.tolist())}
    for k in [0] + KS_QUALITY:
        ov, rec = [], []
        for qi, (terms, w) in enumerate(qs):
            qdense = np.zeros(n_lists + 1, dtype=np.float32)
            qdense[terms] = w
            pdots = pool.dots(qdense)
            stt = State(sh, pdots, ins_pool)
            if k:
                sp_, si_ = z[f"snap{k}_ptr"], z[f"snap{k}_ids"]
                cp_, cc_ = z[f"code{k}_ptr"], z[f"code{k}"]
                for t in terms.tolist():
                    i = tpos[t]
                    rows = si_[sp_[i]:sp_[i + 1]].astype(np.int64)
                    code = cc_[cp_[i]:cp_[i + 1]].astype(np.float64)
                    mult = np.where(code < 0, np.inf, 1.0 + np.maximum(code, 0) / 32.0)
                    stt.lists[t] = ListState(rows=rows, bo=sh.block_offsets(t), mult=mult)
            res = search(stt, terms, w, k=200, heap_factor=0.8)
            trav = [r for _, r in res[:10]]
            br, bs = ex_r[qi], ex_s[qi]
            alive = (del_q[br] == 0) | (del_q[br] > k) if k else np.ones(len(br), bool)
            cand_ids = br[alive]
            cand_sc = bs[alive]
            if k:
                live_ins = ins_q <= k
                ii = ins_ids[live_ins]
                isc = pdots[ins_pool[live_ins]]
                top_i = np.lexsort((ii, -isc))[:10]
                cand_ids = np.concatenate([cand_ids, ii[top_i]])
                cand_sc = np.concatenate([cand_sc, isc[top_i]])
            assert int(alive.sum()) >= 10, "exhaustive top-M exhausted by deletions"
            exact = topk(cand_ids, cand_sc, 10)[0].tolist()
            ov.append(len(set(trav) & set(exact)) / 10)
        out[str(k)] = {"overlap10_traversal_vs_exhaustive_mean": float(np.mean(ov)), "min": float(min(ov)),
                       "identical_sets": int(sum(1 for x in ov if x == 1.0)), "n": len(ov)}
        log("traversal k", k, out[str(k)])
    res_path = Path(a.out)
    blob = json.loads(res_path.read_text()) if res_path.exists() else {}
    blob.setdefault("supplementary", {})["s0_3_traversal_vs_exhaustive"] = {
        "label": "not pre-registered, added 2026-09-29 before the first S0 real-data run (coordinator request)",
        "what": cmd_supp_traversal.__doc__, "exhaustive_topM_base": M, "per_k": out,
        "git_commit_at_run": subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip(),
        "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    res_path.write_text(json.dumps(blob, indent=1, default=float) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep-queries")
    st = sub.add_parser("supp-traversal")
    st.add_argument("--out", default=str(WORK / "inplace_s0_draft.json"))
    st.add_argument("--scale", type=float, default=1.0)
    r = sub.add_parser("run")
    r.add_argument("--out", default=str(WORK / "inplace_s0_draft.json"))
    r.add_argument("--scale", type=float, default=1.0,
                   help="fraction of the estimated quarter volume to simulate (1.0 = full; <1 only for smoke tests)")
    r.add_argument("--floor-frac", type=float, default=0.8,
                   help="forward-scan floor as a fraction of the base minimum posting weight (candidate pool for "
                        "R_sim). 0.8 was the 2026-09-29 value; the 2026-09-30 smoke showed the deletion-only tau "
                        "falls below it from the second full-rate quarter (1.047 vs 1.101 at 05:21Z), so the full "
                        "run uses a lower floor. A lower floor only enlarges the candidate pool; it changes no bar.")
    a = ap.parse_args()
    {"prep-queries": cmd_prep_queries, "run": cmd_run, "supp-traversal": cmd_supp_traversal}[a.cmd](a)


if __name__ == "__main__":
    main()
