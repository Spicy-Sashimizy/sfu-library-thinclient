#!/usr/bin/env python3
"""E7 Fix #5 pre-check: from the existing dotvbyte shard0, predict the gate-c
effect of page-boundary-aware record placement (intra-record padding).

Two measurements:
 1. Pack-weighted page-span distribution: every packed-posting u64 carries
    (word-offset:48 | word-len:16) into forward_data.bin. Each pack occurrence
    is one potential candidate read, so the pack-weighted mean page span is the
    access-weighted cost per candidate. Compare span-now vs minimal span
    ceil(len/512) (what boundary alignment achieves).
 2. Padding cost: simulate the placement walk over the doc-ordered forward
    offsets -> total padded words vs original (file growth %).
"""
import json
import sys
import numpy as np
from pathlib import Path

DV = Path("/workspaces/sfu-library-thinclient/data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.mmap")
PAGE_WORDS = 512  # 4096 B / 8 B per u64 word

def align(cur, a):
    return cur + (a - (cur % a)) % a

def main():
    man = json.loads((DV / "manifest.json").read_text())
    pl = np.memmap(DV / "posting_lists.bin", dtype=np.uint8, mode="r")
    pl_u64 = pl.view(np.uint64)

    # --- walk the per-list layout, mirroring read_pod/skip_pod alignment ---
    packs = []
    cursor = 0
    for plm in man["posting_lists"]:
        cursor = align(cursor, 8)
        n = plm["packed_postings_words"]
        packs.append(pl_u64[cursor // 8: cursor // 8 + n])
        cursor += n * 8
        cursor = align(cursor, 8); cursor += plm["block_offsets_len"] * 8      # usize
        cursor = align(cursor, 8); cursor += plm["ef_high_bits_n_words"] * 8   # u64
        cursor = align(cursor, 8); cursor += plm["inv_block_inventory_len"] * 8  # i64
        cursor = align(cursor, 2); cursor += plm["inv_subblock_inventory_len"] * 2  # u16
        cursor = align(cursor, 8); cursor += plm["inv_overflow_positions_len"] * 8  # usize
        cursor = align(cursor, 8); cursor += plm["ef_low_bits_n_words"] * 8    # u64
        cursor = align(cursor, 8); cursor += plm["summaries_ids_n_words"] * 8  # u64
        cursor += plm["values_len"]                                            # u8, no align
        cursor = align(cursor, 4); cursor += plm["minimums_len"] * 4           # f32
        cursor = align(cursor, 4); cursor += plm["quants_len"] * 4             # f32
        if plm["has_component_ids"]:
            cursor = align(cursor, 2); cursor += plm["component_ids_len"] * 2  # u16
    assert cursor <= len(pl) and len(pl) - cursor < 8, (cursor, len(pl))
    packs = np.concatenate(packs)
    print(f"packs extracted: {len(packs):,}", file=sys.stderr)

    off = (packs >> np.uint64(16)).astype(np.int64)
    ln = (packs & np.uint64(0xFFFF)).astype(np.int64)
    assert ln.min() > 0

    span_now = (off + ln - 1) // PAGE_WORDS - off // PAGE_WORDS + 1
    span_min = -(-ln // PAGE_WORDS)  # ceil
    straddlers = (span_now > span_min)

    # --- padding-cost simulation over doc order ---
    offsets = np.memmap(DV / "forward_offsets.bin", dtype=np.uint64, mode="r").astype(np.int64)
    lens = np.diff(offsets)
    w = 0
    pad_total = 0
    n_padded = 0
    # python loop over 18.8M docs is slow-ish; vectorize is hard (sequential), chunk it
    for L in lens:
        L = int(L)
        r = w % PAGE_WORDS
        if r != 0:
            room = PAGE_WORDS - r
            if L > room:
                span_at_w = 1 + -(-(L - room) // PAGE_WORDS)
                span_at_b = -(-L // PAGE_WORDS)
                if span_at_b < span_at_w:
                    pad_total += room
                    n_padded += 1
                    w += room
        w += L
    orig_words = int(offsets[-1])
    print(json.dumps({
        "n_packs": int(len(packs)),
        "record_len_words": {"mean": float(ln.mean()), "p50": int(np.median(ln)),
                              "p90": int(np.percentile(ln, 90)), "p99": int(np.percentile(ln, 99)),
                              "max": int(ln.max())},
        "pack_weighted": {
            "mean_span_now": float(span_now.mean()),
            "mean_span_aligned": float(span_min.mean()),
            "straddle_fraction": float(straddlers.mean()),
            "span_ratio_aligned_over_now": float(span_min.mean() / span_now.mean()),
        },
        "doc_weighted": {
            "mean_len_words": float(lens.mean()),
            "straddle_fraction_docs": float(
                (((offsets[:-1] + lens - 1) // PAGE_WORDS - offsets[:-1] // PAGE_WORDS + 1)
                 > -(-lens // PAGE_WORDS)).mean()),
        },
        "padding_sim": {
            "orig_words": orig_words,
            "pad_words": int(pad_total),
            "growth_pct": 100.0 * pad_total / orig_words,
            "docs_padded_before": int(n_padded),
        },
        "gate_c_projection": {
            "dv_majflt_fwd_now": 64051,
            "f16_majflt_fwd": 111882,
            "dv_majflt_fwd_predicted": 64051 * float(span_min.mean() / span_now.mean()),
            "ratio_predicted_prefloor_on": 64051 * float(span_min.mean() / span_now.mean()) / 111882,
            "ratio_predicted_prefloor_off":
                (64051 * float(span_min.mean() / span_now.mean()) + 5096) / (111882 + 5093),
        },
    }, indent=2))

if __name__ == "__main__":
    main()
