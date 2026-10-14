"""> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

Python re-implementation of the MmapSeismicIndex traversal over an
optionally modified list/summary state.

Engine semantics mirrored (spike/seismic_upstream/src/mmap_io.rs
search_raw_visited, mmap_index.rs sort_and_search / search /
evaluate_posting_block, utils.rs KHeap):
  * query terms visited in descending weight order (k_largest_by, query_cut);
  * the first term's blocks in descending summary-dot order, every other
    term's blocks in natural order;
  * a block is skipped iff the heap is full and dot < heap_factor * heap_min;
  * an evaluated block scores every posting whose doc was not yet visited
    (exact dot product of the f16 forward row with the f32 query) and pushes
    it into a size-k heap (replace the min iff strictly greater).

State overlays (all in memory, never written to disk):
  * ListState per modified list: slot->row array (-1 = dead slot), the block
    offsets (unchanged: capacity never grows), and summary adjustments.
  * Side forward: rows >= n_base hold re-encoded / new records.
  * Summary adjustment modes: 'raise' (per (block, component) value raised to
    max(old, new); entries absent from the build summary are only added when
    add_absent=True), and a per-block multiplier (the brief's inflation byte).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np

from .shard import ShardView


@dataclass
class ListState:
    rows: np.ndarray
    bo: np.ndarray
    raise_b: list = field(default_factory=list)
    raise_c: list = field(default_factory=list)
    raise_v: list = field(default_factory=list)
    mult: np.ndarray | None = None


class SideForward:
    """Append-only CSR for rows >= n_base."""

    def __init__(self, n_base: int):
        self.n_base = n_base
        self.comps: list[np.ndarray] = []
        self.vals: list[np.ndarray] = []
        self._cat = None

    def add(self, comps: np.ndarray, vals: np.ndarray) -> int:
        self.comps.append(np.asarray(comps, dtype=np.uint16))
        self.vals.append(np.asarray(vals, dtype=np.float16))
        self._cat = None
        return self.n_base + len(self.comps) - 1

    def __len__(self):
        return len(self.comps)

    def cat(self):
        if self._cat is None:
            if self.comps:
                lens = np.array([len(c) for c in self.comps], dtype=np.int64)
                o = np.concatenate([[0], np.cumsum(lens)])
                self._cat = (o, np.concatenate(self.comps), np.concatenate(self.vals))
            else:
                self._cat = (np.zeros(1, dtype=np.int64), np.zeros(0, np.uint16), np.zeros(0, np.float16))
        return self._cat


def _gather_ranges(starts: np.ndarray, lens: np.ndarray) -> np.ndarray:
    tot = int(lens.sum())
    if tot == 0:
        return np.zeros(0, dtype=np.int64)
    cs = np.cumsum(lens)
    rep = np.repeat(starts - (cs - lens), lens)
    return rep + np.arange(tot, dtype=np.int64)


class IndexState:
    def __init__(self, shard: ShardView):
        self.shard = shard
        self.lists: dict[int, ListState] = {}
        self.side = SideForward(shard.n_docs)
        self.dead_rows = np.zeros(0, dtype=np.int64)
        self._summ_cache: dict[int, object] = {}

    def summary(self, t: int):
        s = self._summ_cache.get(t)
        if s is None:
            s = self.shard.summary(t)
            if len(self._summ_cache) > 20000:
                self._summ_cache.clear()
            self._summ_cache[t] = s
        return s

    def list_state(self, t: int, create: bool = False) -> ListState | None:
        ls = self.lists.get(t)
        if ls is None and create:
            ls = ListState(rows=self.shard.list_rows(t).astype(np.int64), bo=self.shard.block_offsets(t))
            self.lists[t] = ls
        return ls

    def rows_of(self, t: int) -> np.ndarray:
        ls = self.lists.get(t)
        return ls.rows if ls is not None else self.shard.list_rows(t)

    def bo_of(self, t: int) -> np.ndarray:
        ls = self.lists.get(t)
        return ls.bo if ls is not None else self.shard.block_offsets(t)

    def block_dots(self, t: int, qc: np.ndarray, qv: np.ndarray, qdense: np.ndarray) -> np.ndarray:
        s = self.summary(t)
        d = s.dots(qc, qv)
        ls = self.lists.get(t)
        if ls is not None:
            if ls.raise_b:
                b = np.asarray(ls.raise_b, dtype=np.int64)
                c = np.asarray(ls.raise_c, dtype=np.int64)
                v = np.asarray(ls.raise_v, dtype=np.float32)
                w = qdense[c]
                m = w != 0
                if m.any():
                    np.add.at(d, b[m], (v[m] * w[m]).astype(np.float32))
            if ls.mult is not None:
                d = (d * ls.mult).astype(np.float32)
        return d

    def score_rows(self, rows: np.ndarray, qdense: np.ndarray) -> np.ndarray:
        sh = self.shard
        out = np.zeros(len(rows), dtype=np.float32)
        base = rows < sh.n_docs
        if base.any():
            r = rows[base]
            o = sh.offs_i64
            st, ln = o[r], o[r + 1] - o[r]
            idx = _gather_ranges(st, ln)
            c = np.asarray(sh.comps[idx]).astype(np.int64)
            v = np.asarray(sh.vals[idx]).astype(np.float32)
            prod = v * qdense[c]
            seg = np.repeat(np.arange(len(r)), ln)
            out[base] = np.bincount(seg, weights=prod, minlength=len(r)).astype(np.float32)
        if (~base).any():
            so, sc, sv = self.side.cat()
            r = rows[~base] - sh.n_docs
            st, ln = so[r], so[r + 1] - so[r]
            idx = _gather_ranges(st, ln)
            prod = sv[idx].astype(np.float32) * qdense[sc[idx].astype(np.int64)]
            seg = np.repeat(np.arange(len(r)), ln)
            out[~base] = np.bincount(seg, weights=prod, minlength=len(r)).astype(np.float32)
        return out


def search(state: IndexState, qc: np.ndarray, qv: np.ndarray, k: int = 200, heap_factor: float = 0.8,
           query_cut: int | None = None, first_sorted: bool = True, stats: dict | None = None):
    """Returns [(score, row)] sorted by score desc. qc = shard token ids (sorted
    ascending, unique), qv = f32 weights. stats (optional) receives
    blocks_evaluated, blocks_total, candidates_scored."""
    sh = state.shard
    dim = len(sh.plm)
    qdense = np.zeros(dim + 1, dtype=np.float32)
    qdense[qc] = qv
    qc = np.asarray(qc, dtype=np.int64)
    qv = np.asarray(qv, dtype=np.float32)
    order = np.argsort(-qv, kind="stable")
    if query_cut is not None:
        order = order[:query_cut]
    terms = [int(qc[i]) for i in order]

    all_rows = [state.rows_of(t) for t in terms]
    cat = np.concatenate(all_rows) if all_rows else np.zeros(0, np.int64)
    cat = cat[cat >= 0]
    uniq = np.unique(cat)
    uscore = state.score_rows(uniq, qdense) if len(uniq) else np.zeros(0, np.float32)

    heap: list = []
    visited: set = set()
    be = bt = cs = 0
    hf = np.float32(heap_factor)
    for i, t in enumerate(terms):
        rows = all_rows[i]
        bo = state.bo_of(t)
        nb = len(bo) - 1
        if nb <= 0:
            continue
        dots = state.block_dots(t, qc, qv, qdense)
        bt += nb
        if i == 0 and first_sorted:
            border = np.argsort(-dots, kind="stable")
        else:
            border = range(nb)
        for b in border:
            b = int(b)
            if len(heap) == k and dots[b] < hf * heap[0][0]:
                continue
            be += 1
            blk = rows[bo[b]:bo[b + 1]]
            blk = blk[blk >= 0]
            if len(blk) == 0:
                continue
            new = [r for r in blk.tolist() if r not in visited]
            if not new:
                continue
            visited.update(new)
            na = np.asarray(new, dtype=np.int64)
            sc = uscore[np.searchsorted(uniq, na)]
            cs += len(new)
            for s, r in zip(sc.tolist(), new):
                if len(heap) < k:
                    heapq.heappush(heap, (s, r))
                elif s > heap[0][0]:
                    heapq.heapreplace(heap, (s, r))
    if stats is not None:
        stats["blocks_evaluated"] = be
        stats["blocks_total"] = bt
        stats["candidates_scored"] = cs
    return sorted(heap, key=lambda x: (-x[0], x[1]))
