"""> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

Mechanism B (bounded lists: dead-slot reuse, eviction of the list minimum,
drop) and Mechanism C (per-block inflation byte) simulated in memory over a
subset of lists T of one shard, quarter by quarter.

Insert order inside a list's term-sorted batch: weight descending, doc id
ascending. Dead slots are filled lowest slot index first. After the dead
slots run out, the i-th remaining insert evicts the i-th smallest live
posting (weight ascending, slot ascending) iff its weight is strictly
greater; the first failure ends the batch for that list (every later insert
is smaller). This equals the brief's sequential rule (take a dead slot, else
evict the current minimum if strictly greater, else drop).

Inflation byte (plan S0-3): per block, on each placed insert,
m_b := max(m_b, max over components c of the OLD summary of b that the new
doc carries of max(old_c, w_c) / old_c); code = ceil((m_b - 1) * 32),
saturated when code > 255.
"""
from __future__ import annotations

import numpy as np

from .shard import ShardView


def ranges(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ln = b - a
    tot = int(ln.sum())
    if tot == 0:
        return np.zeros(0, dtype=np.int64)
    cs = np.cumsum(ln)
    return np.repeat(a - (cs - ln), ln) + np.arange(tot, dtype=np.int64)


class Pool:
    """CSR of insert vectors (shard token ids, f32 weights) + transpose."""

    def __init__(self, cptr: np.ndarray, comp: np.ndarray, val: np.ndarray, dim: int):
        self.cptr = cptr.astype(np.int64)
        self.comp = comp.astype(np.int64)
        self.val = val.astype(np.float32)
        self.n = len(cptr) - 1
        self.dim = dim
        doc = np.repeat(np.arange(self.n), np.diff(self.cptr))
        order = np.lexsort((doc, -self.val, self.comp))
        self.t_doc = doc[order]
        self.t_val = self.val[order]
        self.t_ptr = np.zeros(dim + 2, dtype=np.int64)
        np.add.at(self.t_ptr, self.comp + 1, 1)
        self.t_ptr = np.cumsum(self.t_ptr)
        self.keys = doc * (dim + 1) + self.comp
        assert np.all(np.diff(self.keys) > 0)

    def weight_on(self, pdocs: np.ndarray, comps: np.ndarray) -> np.ndarray:
        k = pdocs.astype(np.int64) * (self.dim + 1) + comps.astype(np.int64)
        pos = np.searchsorted(self.keys, k)
        pos[pos >= len(self.keys)] = 0
        hit = self.keys[pos] == k
        return np.where(hit, self.val[pos], 0.0).astype(np.float32)

    def dots(self, qdense: np.ndarray) -> np.ndarray:
        prod = self.val * qdense[self.comp]
        return np.bincount(np.repeat(np.arange(self.n), np.diff(self.cptr)), weights=prod,
                           minlength=self.n).astype(np.float32)


class InplaceSim:
    def __init__(self, sh: ShardView, ptr, prow, pw, T: np.ndarray, pool: Pool, track_inflation: bool = True):
        self.sh = sh
        self.N = sh.n_docs
        self.T = np.asarray(T, dtype=np.int64)
        self.pool = pool
        self.ids: dict[int, np.ndarray] = {}
        self.w: dict[int, np.ndarray] = {}
        self.dead: dict[int, np.ndarray] = {}
        self.bo: dict[int, np.ndarray] = {}
        self.code: dict[int, np.ndarray] = {}
        self.m: dict[int, np.ndarray] = {}
        rr, tt, ss = [], [], []
        for t in self.T.tolist():
            a, b = int(ptr[t]), int(ptr[t + 1])
            self.ids[t] = prow[a:b].astype(np.int64)
            self.w[t] = pw[a:b].astype(np.float32)
            self.dead[t] = np.zeros(b - a, dtype=bool)
            self.bo[t] = sh.block_offsets(t)
            nb = len(self.bo[t]) - 1
            self.m[t] = np.ones(max(nb, 0), dtype=np.float64)
            rr.append(prow[a:b].astype(np.int64))
            tt.append(np.full(b - a, t, dtype=np.int64))
            ss.append(np.arange(b - a, dtype=np.int64))
        r = np.concatenate(rr)
        o = np.argsort(r, kind="stable")
        self.idx_row = r[o]
        self.idx_t = np.concatenate(tt)[o]
        self.idx_slot = np.concatenate(ss)[o]
        self.track = track_inflation
        self.stats: list[dict] = []
        self.next_id = self.N
        self.ins_pool: list[np.ndarray] = []
        self.placed_log: list[dict] = []

    def delete(self, rows: np.ndarray) -> dict:
        rows = np.unique(rows)
        a = np.searchsorted(self.idx_row, rows, side="left")
        b = np.searchsorted(self.idx_row, rows, side="right")
        ix = ranges(a, b)
        tt, ss, rr = self.idx_t[ix], self.idx_slot[ix], self.idx_row[ix]
        o = np.argsort(tt, kind="stable")
        tt, ss, rr = tt[o], ss[o], rr[o]
        bounds = np.flatnonzero(np.diff(tt)) + 1
        freed = already_evicted = 0
        for g0, g1 in zip(np.concatenate([[0], bounds]), np.concatenate([bounds, [len(tt)]])):
            if g1 <= g0:
                continue
            t = int(tt[g0])
            s, r = ss[g0:g1], rr[g0:g1]
            hit = (self.ids[t][s] == r) & ~self.dead[t][s]
            self.dead[t][s[hit]] = True
            freed += int(hit.sum())
            already_evicted += int((~hit).sum())
        return {"rows": int(len(rows)), "slots_freed_T": freed, "postings_already_evicted": already_evicted}

    def insert(self, pool_idx: np.ndarray, summaries=None, sample_blocks: dict | None = None) -> dict:
        """Insert docs whose vectors are pool rows `pool_idx` (fresh ids in
        call order). Returns counters. `summaries(t)` -> Summary for the
        inflation byte."""
        n = len(pool_idx)
        ids = self.next_id + np.arange(n, dtype=np.int64)
        self.next_id += n
        self.ins_pool.append(np.asarray(pool_idx, dtype=np.int64))
        o = np.argsort(pool_idx, kind="stable")
        sp = pool_idx[o]
        sid = ids[o]
        gs = np.searchsorted(sp, np.arange(self.pool.n), side="left")
        ge = np.searchsorted(sp, np.arange(self.pool.n), side="right")
        c = {"docs": int(n), "postings_T": 0, "to_dead_slot": 0, "evicting": 0, "dropped": 0,
             "evicted_base": 0, "evicted_inserted": 0, "own_term_absent_from_block_summary": 0,
             "blind_components": 0, "blind_mass": 0.0, "placed": 0, "saturated_new": 0}
        P = self.pool
        for t in self.T.tolist():
            a, b = int(P.t_ptr[t]), int(P.t_ptr[t + 1])
            if a == b:
                continue
            pd = P.t_doc[a:b]
            pv = P.t_val[a:b]
            cnt = ge[pd] - gs[pd]
            keep = cnt > 0
            if not keep.any():
                continue
            pd, pv, cnt = pd[keep], pv[keep], cnt[keep]
            total = int(cnt.sum())
            c["postings_T"] += total
            dead = self.dead[t]
            ids_t, w_t = self.ids[t], self.w[t]
            need = int(dead.sum()) + len(w_t)
            cum = np.cumsum(cnt)
            j = int(np.searchsorted(cum, need, side="left"))
            if j < len(pv):
                j = int(np.searchsorted(-pv, -pv[j], side="right"))
            pd, pv, cnt = pd[:j], pv[:j], cnt[:j]
            gi = ranges(gs[pd], ge[pd])
            ins_id = sid[gi]
            ins_w = np.repeat(pv, cnt)
            ins_p = np.repeat(pd, cnt)
            order = np.lexsort((ins_id, -ins_w))
            ins_id, ins_w, ins_p = ins_id[order], ins_w[order], ins_p[order]
            k = len(ins_id)
            c["dropped"] += total - k
            dslots = np.flatnonzero(dead)
            D = len(dslots)
            nd = min(D, k)
            ids_t[dslots[:nd]] = ins_id[:nd]
            w_t[dslots[:nd]] = ins_w[:nd]
            dead[dslots[:nd]] = False
            slots_new = [dslots[:nd]]
            take = [np.arange(nd)]
            if k > D:
                rem = np.arange(D, k)
                full = np.lexsort((np.arange(len(w_t)), w_t))
                mcap = min(len(rem), len(full))
                if mcap:
                    ok = ins_w[rem[:mcap]] > w_t[full[:mcap]]
                    acc = int(np.argmin(ok)) if not ok.all() else mcap
                else:
                    acc = 0
                ev_slots = full[:acc]
                ev_ids = ids_t[ev_slots]
                c["evicted_base"] += int((ev_ids < self.N).sum())
                c["evicted_inserted"] += int((ev_ids >= self.N).sum())
                ids_t[ev_slots] = ins_id[rem[:acc]]
                w_t[ev_slots] = ins_w[rem[:acc]]
                slots_new.append(ev_slots)
                take.append(rem[:acc])
                c["evicting"] += acc
                c["dropped"] += len(rem) - acc
            c["to_dead_slot"] += nd
            sl = np.concatenate(slots_new).astype(np.int64)
            tk = np.concatenate(take).astype(np.int64)
            c["placed"] += len(sl)
            if self.track and len(sl) and summaries is not None:
                self._inflate(t, sl, ins_p[tk], summaries(t), c, sample_blocks)
        return c

    def _inflate(self, t, slots, pdocs, summ, c, sample_blocks):
        bo = self.bo[t]
        blk = np.searchsorted(bo, slots, side="right") - 1
        D1 = summ.dim + 1
        nb = len(bo) - 1
        if not hasattr(summ, "_bkeys"):
            bid = summ.block_ids
            comp_of = np.repeat(np.arange(len(summ.comp_starts) - 1), np.diff(summ.comp_starts))
            keys = bid * D1 + comp_of
            o = np.argsort(keys)
            summ._bkeys = keys[o]
            summ._bval = summ.deq[o]
            bmin = np.full(nb, np.inf, dtype=np.float32)
            np.minimum.at(bmin, bid, summ.deq)
            summ._bmin = bmin
        own = blk * D1 + t
        pos = np.searchsorted(summ._bkeys, own)
        pos[pos >= len(summ._bkeys)] = 0
        c["own_term_absent_from_block_summary"] += int((summ._bkeys[pos] != own).sum())
        P = self.pool
        pa = P.cptr[pdocs]
        pb = P.cptr[pdocs + 1]
        gi = ranges(pa, pb)
        which = np.repeat(np.arange(len(pdocs)), pb - pa)
        comps = P.comp[gi]
        vals = P.val[gi]
        bb = blk[which]
        keys = bb * D1 + comps
        pos = np.searchsorted(summ._bkeys, keys)
        pos[pos >= len(summ._bkeys)] = 0
        hit = summ._bkeys[pos] == keys
        old = np.where(hit, summ._bval[pos], 1.0)
        ratio = np.where(hit & (old > 0), np.maximum(vals / np.maximum(old, 1e-12), 1.0), 1.0)
        mi = np.ones(len(pdocs))
        np.maximum.at(mi, which, ratio)
        m = self.m[t]
        before_sat = (np.ceil((m[blk] - 1) * 32) > 255)
        np.maximum.at(m, blk, mi)
        after_sat = (np.ceil((m[blk] - 1) * 32) > 255)
        c["saturated_new"] += int((after_sat & ~before_sat).sum())
        blind = (~hit) & (vals >= summ._bmin[bb])
        c["blind_components"] += int(blind.sum())
        c["blind_mass"] += float(vals[blind].sum())
        if sample_blocks is not None and len(pdocs):
            sample_blocks.setdefault(t, []).append((blk.copy(), pdocs.copy()))

    def codes(self, t: int) -> np.ndarray:
        """Quantised inflation codes; -1 = saturated."""
        m = self.m[t]
        code = np.ceil(np.round((m - 1) * 32, 9)).astype(np.int64)
        code[code > 255] = -1
        return code

    def snapshot_lists(self) -> dict[int, np.ndarray]:
        out = {}
        for t in self.T.tolist():
            x = self.ids[t].copy()
            x[self.dead[t]] = -1
            out[t] = x
        return out

    def dead_fraction(self) -> float:
        d = sum(int(v.sum()) for v in self.dead.values())
        s = sum(len(v) for v in self.dead.values())
        return d / max(1, s)
