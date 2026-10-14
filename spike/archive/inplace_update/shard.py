"""> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

Read-only decoder for one c1a-layout SEISMIC mmap shard (f16 twin format).

Layout of posting_lists.bin (spike/seismic_upstream/src/mmap_io.rs,
read_posting_lists): per list, in manifest order, POD sections each aligned to
its element size (read_pod pads the cursor):
  packed_postings u64 (start<<16 | len into the forward arrays)
  block_offsets usize
  EF high_bits words u64, inventories: block i64, subblock u16, overflow usize
  EF low_bits words u64
  summaries_ids bitfield words u64
  values u8 (alignment 1), minimums f32, quants f32, component_ids u16 (opt.)
Bit vectors and bit fields are LSB-first inside little-endian u64 words
(toolkit_fork bitvector.rs get_bits). EF select(k) =
((pos of k-th set bit in high) - k) << low_len | low[k].
Summary with dense offsets (has_component_ids == False): the entries of
component c are positions select(c)-c .. select(c+1)-(c+1); entry p belongs to
block summaries_ids[p] with value values[p]*quants[b] + minimums[b].

Everything is opened read-only (np.memmap mode='r').
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def _align(cur: int, a: int) -> int:
    return cur + ((a - cur % a) % a)


def load_token_to_id(mmap_dir: Path) -> dict[str, int]:
    raw = (Path(mmap_dir) / "token_to_id_map.bin").read_bytes()
    off = 0
    (count,) = struct.unpack_from("<Q", raw, off)
    off += 8
    out = {}
    for _ in range(count):
        (slen,) = struct.unpack_from("<Q", raw, off)
        off += 8
        s = raw[off:off + slen].decode("utf-8")
        off += slen
        (v,) = struct.unpack_from("<Q", raw, off)
        off += 8
        out[s] = v
    assert off == len(raw)
    return out


def _bits(words: np.ndarray, n_bits: int) -> np.ndarray:
    b = np.unpackbits(np.ascontiguousarray(words).view(np.uint8), bitorder="little")
    return b[:n_bits]


def _bitfield(words: np.ndarray, n_bits: int, width: int, n: int) -> np.ndarray:
    if width == 0 or n == 0:
        return np.zeros(n, dtype=np.int64)
    b = _bits(words, n_bits).astype(np.int64)
    idx = np.arange(n, dtype=np.int64) * width
    out = np.zeros(n, dtype=np.int64)
    for j in range(width):
        out |= b[idx + j] << j
    return out


@dataclass
class ListLayout:
    pp: int
    bo: int
    hb: int
    lb: int
    sids: int
    values: int
    mins: int
    quants: int
    cids: int


class Summary:
    """Decoded block summary of one list: per component, (block ids, f32 values)."""

    def __init__(self, n_blocks: int, dim: int, comp_starts: np.ndarray, block_ids: np.ndarray,
                 deq: np.ndarray):
        self.n_blocks = n_blocks
        self.dim = dim
        self.comp_starts = comp_starts
        self.block_ids = block_ids
        self.deq = deq

    def entries(self, c: int):
        a, b = int(self.comp_starts[c]), int(self.comp_starts[c + 1])
        return self.block_ids[a:b], self.deq[a:b]

    def dots(self, qc: np.ndarray, qv: np.ndarray) -> np.ndarray:
        acc = np.zeros(self.n_blocks, dtype=np.float32)
        for c, v in zip(qc.tolist(), qv.tolist()):
            if c >= self.dim:
                break
            bids, deq = self.entries(c)
            if len(bids):
                np.add.at(acc, bids, (deq * np.float32(v)).astype(np.float32))
        return acc


class ShardView:
    """One c1a mmap shard directory, read-only."""

    def __init__(self, mmap_dir: Path, forward: str = "f16"):
        self.dir = Path(mmap_dir)
        self.man = json.loads((self.dir / "manifest.json").read_text())
        self.n_lists = int(self.man["n_posting_lists"])
        self.n_docs = int(self.man["n_docs"])
        self.plm = self.man["posting_lists"]
        self.pl = np.memmap(self.dir / "posting_lists.bin", dtype=np.uint8, mode="r")
        self.offs = np.memmap(self.dir / "forward_offsets.bin", dtype=np.uint64, mode="r")
        self.forward = forward
        if forward == "f16":
            self.comps = np.memmap(self.dir / "forward_components.bin", dtype=np.uint16, mode="r")
            self.vals = np.memmap(self.dir / "forward_values.bin", dtype=np.float16, mode="r")
        self._offs_i64 = None
        self.layout = self._layout()
        self.list_len = np.array([p["packed_postings_words"] for p in self.plm], dtype=np.int64)
        self.n_blocks = np.array([p["n_summaries"] for p in self.plm], dtype=np.int64)

    def _layout(self) -> list[ListLayout]:
        cur = 0
        out = []
        for p in self.plm:
            pp = _align(cur, 8); cur = pp + 8 * p["packed_postings_words"]
            bo = _align(cur, 8); cur = bo + 8 * p["block_offsets_len"]
            hb = _align(cur, 8); cur = hb + 8 * p["ef_high_bits_n_words"]
            cur = _align(cur, 8) + 8 * p["inv_block_inventory_len"]
            cur = _align(cur, 2) + 2 * p["inv_subblock_inventory_len"]
            cur = _align(cur, 8) + 8 * p["inv_overflow_positions_len"]
            lb = _align(cur, 8); cur = lb + 8 * p["ef_low_bits_n_words"]
            sids = _align(cur, 8); cur = sids + 8 * p["summaries_ids_n_words"]
            values = cur; cur = values + p["values_len"]
            mins = _align(cur, 4); cur = mins + 4 * p["minimums_len"]
            quants = _align(cur, 4); cur = quants + 4 * p["quants_len"]
            cids = cur
            if p["has_component_ids"]:
                cids = _align(cur, 2); cur = cids + 2 * p["component_ids_len"]
            out.append(ListLayout(pp, bo, hb, lb, sids, values, mins, quants, cids))
        assert cur == len(self.pl), (cur, len(self.pl))
        return out

    def _pod(self, off: int, dtype, n: int) -> np.ndarray:
        dt = np.dtype(dtype)
        return np.frombuffer(self.pl, dtype=dt, count=n, offset=off)

    @property
    def offs_i64(self) -> np.ndarray:
        if self._offs_i64 is None:
            self._offs_i64 = np.asarray(self.offs, dtype=np.int64)
        return self._offs_i64

    def packed(self, t: int) -> np.ndarray:
        return self._pod(self.layout[t].pp, np.uint64, self.plm[t]["packed_postings_words"])

    def block_offsets(self, t: int) -> np.ndarray:
        return self._pod(self.layout[t].bo, np.uint64, self.plm[t]["block_offsets_len"]).astype(np.int64)

    def list_rows(self, t: int) -> np.ndarray:
        """Forward rows of list t's postings, in slot order."""
        pk = self.packed(t)
        starts = (pk >> np.uint64(16)).astype(np.int64)
        rows = np.searchsorted(self.offs_i64, starts, side="left")
        return rows

    def list_rows_checked(self, t: int) -> np.ndarray:
        pk = self.packed(t)
        starts = (pk >> np.uint64(16)).astype(np.int64)
        lens = (pk & np.uint64(0xFFFF)).astype(np.int64)
        rows = np.searchsorted(self.offs_i64, starts, side="left")
        o = self.offs_i64
        assert np.array_equal(o[rows], starts) and np.array_equal(o[rows + 1] - o[rows], lens), t
        return rows

    def summary(self, t: int) -> Summary:
        p = self.plm[t]
        L = self.layout[t]
        nb = p["n_summaries"]
        nv = p["ef_num_vals"]
        hb_words = self._pod(L.hb, np.uint64, p["ef_high_bits_n_words"])
        ones = np.flatnonzero(_bits(hb_words, p["ef_high_bits_n_bits"]))[:nv].astype(np.int64)
        lb_words = self._pod(L.lb, np.uint64, p["ef_low_bits_n_words"])
        low = _bitfield(lb_words, p["ef_low_bits_n_bits"], p["ef_low_bits_field_width"], nv)
        ll = p["ef_low_len"]
        sel = ((ones - np.arange(nv, dtype=np.int64)) << ll) | low
        if p["has_component_ids"]:
            cids = self._pod(L.cids, np.uint16, p["component_ids_len"]).astype(np.int64)
            dim = p["dim"]
            counts = np.zeros(dim + 1, dtype=np.int64)
            counts[cids] = np.diff(sel)[:len(cids)]
            first = np.zeros(dim + 1, dtype=np.int64)
            first[cids] = sel[:len(cids)]
            comp_starts = np.zeros(dim + 1, dtype=np.int64)
            comp_starts[1:] = np.cumsum(counts[:dim])
            perm = np.concatenate([np.arange(first[c], first[c] + counts[c]) for c in range(dim) if counts[c]]
                                  ) if len(cids) else np.zeros(0, np.int64)
        else:
            comp_starts = sel - np.arange(nv, dtype=np.int64)
            perm = None
        nvals = p["values_len"]
        sid_words = self._pod(L.sids, np.uint64, p["summaries_ids_n_words"])
        bids = _bitfield(sid_words, p["summaries_ids_n_bits"], p["summaries_ids_field_width"], nvals)
        vals = self._pod(L.values, np.uint8, nvals).astype(np.float32)
        mins = self._pod(L.mins, np.float32, p["minimums_len"])
        quants = self._pod(L.quants, np.float32, p["quants_len"])
        deq = (vals * quants[bids] + mins[bids]).astype(np.float32)
        if perm is not None and len(perm):
            bids, deq = bids[perm], deq[perm]
        return Summary(nb, p["dim"], comp_starts, bids, deq)

    def row_vector(self, r: int):
        a, b = int(self.offs[r]), int(self.offs[r + 1])
        return np.asarray(self.comps[a:b]), np.asarray(self.vals[a:b])

    def weights_of(self, rows: np.ndarray, t: int) -> np.ndarray:
        """f16 weight of term t in each forward row (0 if absent), vectorised
        binary search over each row's sorted component slice."""
        o = self.offs_i64
        lo = o[rows].copy()
        hi = o[rows + 1].copy()
        tt = np.uint16(t)
        while True:
            act = lo < hi
            if not act.any():
                break
            mid = (lo + hi) >> 1
            cm = np.asarray(self.comps[mid[act]])
            less = cm < tt
            lo_a, hi_a, mid_a = lo[act], hi[act], mid[act]
            lo_a = np.where(less, mid_a + 1, lo_a)
            hi_a = np.where(less, hi_a, mid_a)
            lo[act] = lo_a
            hi[act] = hi_a
        end = o[rows + 1]
        ok = lo < end
        w = np.zeros(len(rows), dtype=np.float16)
        if ok.any():
            idx = lo[ok]
            hit = np.asarray(self.comps[idx]) == tt
            vv = np.asarray(self.vals[idx])
            tmp = np.zeros(ok.sum(), dtype=np.float16)
            tmp[hit] = vv[hit]
            w[ok] = tmp
        return w

    def doc_ids(self) -> np.ndarray:
        """Numeric OpenAlex ids (int64, the W stripped) per forward row."""
        mo = np.memmap(self.dir / "document_mapping_offsets.bin", dtype=np.uint64, mode="r")
        blob = np.fromfile(self.dir / "document_mapping_strings.bin", dtype=np.uint8)
        mo = np.asarray(mo, dtype=np.int64)
        n = len(mo) - 1
        lens = np.diff(mo)
        assert (blob[mo[:-1]] == ord("W")).all()
        out = np.zeros(n, dtype=np.int64)
        maxlen = int(lens.max())
        for j in range(1, maxlen):
            m = lens > j
            d = blob[mo[:-1][m] + j].astype(np.int64) - 48
            assert ((d >= 0) & (d <= 9)).all()
            out[m] = out[m] * 10 + d
        return out
