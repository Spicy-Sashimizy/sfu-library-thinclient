#!/usr/bin/env python3
"""In-place bit updater, supplementary measurement W1: write unit of arm A2b.

DEFINITION (verbatim from docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md,
"Addendum 2026-09-29 (second)", commit d4ba6b87):

  - **Write unit = an OUTPUT of measurement W1, fixed before any A2b code.**
    W1 (read-only, shard 0, results
    `data/eval_results/inplace_writeunit_<YYYYMMDD>.json`): distribution
    (min, p50, p90, p99, max, total) of bytes per block and per list for
    packed postings, block offsets and the summary section; and whether one
    block's summary entries can be re-encoded without re-encoding the rest of
    its list's summary section. Rule: BLOCK if separable, else LIST. W1 is a
    structural measurement, not an efficacy result.

Coordinator additions (message 2026-09-29): also report how many offsets name
a unit (which single 8-byte store would publish it) and whether that offset
is itself inside an Elias-Fano or otherwise dense structure that cannot be
flipped in place (then A2b needs an indirection table in format v3).

Method. The layout walk mirrors the Rust reader
(spike/seismic_upstream/src/mmap_io.rs read_posting_lists: per list, POD
slices each aligned to its element size) and is cross-checked against the
second implementation in spike/inplace_update/shard.py (ShardView._layout,
imported read-only). Bytes per list and per block are read from the
manifest and from block_offsets; the summaries_ids bitfield of every list is
decoded to attribute summary entries to blocks and to measure how a block's
entries are laid out inside the list's summary section (the separability
evidence from data; the code facts are recorded beside it with file refs).

Byte attribution:
  per list  postings = 8 * packed_postings_words; block offsets = 8 *
            block_offsets_len; summary section = EF high words + inventories
            (i64 block, u16 subblock, usize overflow) + EF low words +
            summaries_ids words + u8 values + f32 minimums + f32 quants + u16
            component ids (payload), and the span incl. alignment padding up to
            the next list's packed postings.
  per block postings = 8 * (bo[b+1] - bo[b]); block offsets = 8;
            summary (attributable) = entries_b * (1 + w/8) + 8 (its f32
            minimum + f32 quant), w = summaries_ids field width in bits. The
            EF offsets and component ids are per component, not attributable
            to a block; they are reported per list only.

Read-only: every file is opened with np.memmap(mode='r'). Run under
`flock /tmp/sfu_latency_measure.lock taskset -c 0-7`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from spike.inplace_update.shard import ShardView  # noqa: E402
from spike.inplace_update.guard import check_live_unchanged, clean_env  # noqa: E402

SOURCE = REPO / "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap"
DEFAULT_SHARD = Path("/home/vscode/work/inplace_update/stage1/v2copy")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def al(cur: int, a: int) -> int:
    return cur + ((a - cur % a) % a)


def walk(plm: list[dict], file_len: int) -> list[dict]:
    """Per-list slice byte offsets, mirroring read_posting_lists."""
    cur = 0
    out = []
    for p in plm:
        d = {}
        d["pp"] = al(cur, 8); cur = d["pp"] + 8 * p["packed_postings_words"]
        d["bo"] = al(cur, 8); cur = d["bo"] + 8 * p["block_offsets_len"]
        d["hb"] = al(cur, 8); cur = d["hb"] + 8 * p["ef_high_bits_n_words"]
        d["bi"] = al(cur, 8); cur = d["bi"] + 8 * p["inv_block_inventory_len"]
        d["sbi"] = al(cur, 2); cur = d["sbi"] + 2 * p["inv_subblock_inventory_len"]
        d["ov"] = al(cur, 8); cur = d["ov"] + 8 * p["inv_overflow_positions_len"]
        d["lb"] = al(cur, 8); cur = d["lb"] + 8 * p["ef_low_bits_n_words"]
        d["sids"] = al(cur, 8); cur = d["sids"] + 8 * p["summaries_ids_n_words"]
        d["values"] = cur; cur = d["values"] + p["values_len"]
        d["mins"] = al(cur, 4); cur = d["mins"] + 4 * p["minimums_len"]
        d["quants"] = al(cur, 4); cur = d["quants"] + 4 * p["quants_len"]
        d["cids"] = cur
        if p["has_component_ids"]:
            d["cids"] = al(cur, 2); cur = d["cids"] + 2 * p["component_ids_len"]
        d["end"] = cur
        out.append(d)
    assert cur <= file_len and file_len - cur < 8, (cur, file_len)
    return out


def dist(x) -> dict:
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return {"n": 0}
    return {"n": int(x.size), "min": float(x.min()), "p50": float(np.percentile(x, 50)),
            "p90": float(np.percentile(x, 90)), "p99": float(np.percentile(x, 99)),
            "max": float(x.max()), "total": float(x.sum()), "mean": float(x.mean())}


def decode_bitfield(words: np.ndarray, width: int, n: int) -> np.ndarray:
    if width == 0 or n == 0:
        return np.zeros(n, dtype=np.int64)
    bits = np.unpackbits(np.ascontiguousarray(words).view(np.uint8), bitorder="little")[: n * width]
    w = (1 << np.arange(width, dtype=np.int64))
    return (bits.reshape(n, width).astype(np.int64) * w).sum(axis=1)


def sha256_head(path: Path, n: int = 1 << 24) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(n))
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default=str(DEFAULT_SHARD))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    clean_env()
    guard_start = check_live_unchanged("w1-start")
    t0 = time.time()
    shard = Path(a.shard)
    man_bytes = (shard / "manifest.json").read_bytes()
    src_man = (SOURCE / "manifest.json").read_bytes()
    assert man_bytes == src_man, "shard manifest differs from the read-only source manifest"
    man = json.loads(man_bytes)
    assert man["forward_format"] == "dotvbyte_fixedu8" and man["forward_format_version"] == 2
    plm = man["posting_lists"]
    pl = np.memmap(shard / "posting_lists.bin", dtype=np.uint8, mode="r")
    lay = walk(plm, len(pl))
    sv = ShardView(shard, forward="dv")
    for d, L in zip(lay, sv.layout):
        assert (d["pp"], d["bo"], d["hb"], d["lb"], d["sids"], d["values"], d["mins"], d["quants"]) == \
            (L.pp, L.bo, L.hb, L.lb, L.sids, L.values, L.mins, L.quants)
        if d["cids"] != L.cids:
            raise AssertionError("cids offset differs between the two layout walks")
    log("layout cross-check OK", len(lay), "lists")

    L_pp, L_bo, L_sum_payload, L_sum_span, L_total_span = [], [], [], [], []
    L_parts = {k: 0 for k in ["ef_high", "inventories", "ef_low", "summaries_ids", "values",
                              "minimums", "quants", "component_ids", "padding"]}
    B_pp, B_sum, B_entries = [], [], []
    span_frac, contig, interleaved_lists, lists_multi = [], 0, 0, 0
    runs_per_block = []
    shift_bytes_first_entry = []
    n_empty = 0
    widths = {}
    for t, (p, d) in enumerate(zip(plm, lay)):
        nxt = lay[t + 1]["pp"] if t + 1 < len(lay) else len(pl)
        if p["packed_postings_words"] == 0:
            n_empty += 1
            continue
        nb = p["n_summaries"]
        pp_b = 8 * p["packed_postings_words"]
        bo_b = 8 * p["block_offsets_len"]
        parts = {
            "ef_high": 8 * p["ef_high_bits_n_words"],
            "inventories": 8 * p["inv_block_inventory_len"] + 2 * p["inv_subblock_inventory_len"]
            + 8 * p["inv_overflow_positions_len"],
            "ef_low": 8 * p["ef_low_bits_n_words"],
            "summaries_ids": 8 * p["summaries_ids_n_words"],
            "values": p["values_len"],
            "minimums": 4 * p["minimums_len"],
            "quants": 4 * p["quants_len"],
            "component_ids": 2 * p["component_ids_len"] if p["has_component_ids"] else 0,
        }
        payload = sum(parts.values())
        span = nxt - d["hb"]
        parts["padding"] = span - payload
        for k, v in parts.items():
            L_parts[k] += v
        L_pp.append(pp_b); L_bo.append(bo_b); L_sum_payload.append(payload)
        L_sum_span.append(span); L_total_span.append(nxt - d["pp"])

        bo = np.frombuffer(pl, dtype=np.uint64, count=p["block_offsets_len"], offset=d["bo"]).astype(np.int64)
        assert bo[0] == 0 and bo[-1] == p["packed_postings_words"] and len(bo) == nb + 1
        B_pp.extend((8 * np.diff(bo)).tolist())
        w = p["summaries_ids_field_width"]
        widths[w] = widths.get(w, 0) + 1
        n = p["values_len"]
        words = np.frombuffer(pl, dtype=np.uint64, count=p["summaries_ids_n_words"], offset=d["sids"])
        sids = decode_bitfield(words, w, n)
        assert sids.max(initial=0) < nb
        ent = np.bincount(sids, minlength=nb)
        assert ent.sum() == n
        B_entries.extend(ent.tolist())
        B_sum.extend((ent * (1 + w / 8.0) + 8).tolist())
        runs_per_block.extend(ent.tolist())
        if nb >= 2 and n > 0:
            lists_multi += 1
            pos = np.arange(n, dtype=np.int64)
            first = np.full(nb, -1, dtype=np.int64)
            last = np.full(nb, -1, dtype=np.int64)
            rs = sids[::-1]
            u, fi = np.unique(sids, return_index=True)
            first[u] = fi
            u2, li = np.unique(rs, return_index=True)
            last[u2] = n - 1 - li
            has = ent > 0
            sp = (last[has] - first[has] + 1) / n
            span_frac.extend(sp.tolist())
            contig += int(((last[has] - first[has] + 1) == ent[has]).sum())
            if np.any(np.diff(sids) < 0):
                interleaved_lists += 1
            shift_bytes_first_entry.extend(((n - first[has]) * (1 + w / 8.0)).tolist())
        if t % 4000 == 0:
            log("list", t)

    blocks_with_entries = len(span_frac)
    res = {
        "meta": {
            "what": "W1 write-unit structural measurement (supplementary, arm A2b); not an efficacy result",
            "definition_source": "docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md Addendum 2026-09-29 (second), d4ba6b87",
            "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "shard_dir": str(shard),
            "source_dir": str(SOURCE),
            "manifest_identical_to_source": True,
            "posting_lists_bytes": int(len(pl)),
            "posting_lists_sha256_first16MiB": sha256_head(shard / "posting_lists.bin"),
            "layout_walks_agree": ["mmap_io.rs read_posting_lists (mirrored)", "spike/inplace_update/shard.py ShardView._layout"],
            "seconds": None,
        },
        "counts": {
            "n_lists": len(plm), "n_empty_lists": n_empty, "n_nonempty_lists": len(L_pp),
            "n_blocks": len(B_pp), "n_summary_entries": int(sum(B_entries)),
            "lists_with_ge2_blocks": lists_multi,
            "summaries_ids_width_hist": {str(k): v for k, v in sorted(widths.items())},
            "lists_dense_offsets": sum(1 for p in plm if p["packed_postings_words"] and not p["has_component_ids"]),
            "lists_sparse_offsets_component_ids": sum(1 for p in plm if p["packed_postings_words"] and p["has_component_ids"]),
        },
        "bytes_per_list": {
            "packed_postings": dist(L_pp), "block_offsets": dist(L_bo),
            "summary_section_payload": dist(L_sum_payload),
            "summary_section_span_incl_padding": dist(L_sum_span),
            "whole_list_span": dist(L_total_span),
            "summary_parts_total": L_parts,
        },
        "bytes_per_block": {
            "packed_postings": dist(B_pp),
            "block_offsets": {"each": 8, "total": 8 * len(B_pp), "note": "plus one terminal usize per non-empty list"},
            "summary_attributable": dist(B_sum),
            "summary_entries": dist(B_entries),
        },
        "separability_evidence": {
            "block_entry_span_fraction_of_list_summary": dist(span_frac),
            "blocks_with_contiguous_entries": contig,
            "blocks_with_entries_in_ge2_block_lists": blocks_with_entries,
            "share_contiguous": (contig / blocks_with_entries) if blocks_with_entries else None,
            "lists_whose_entries_interleave_blocks": interleaved_lists,
            "component_runs_touched_per_block": dist(runs_per_block),
            "summary_bytes_after_a_blocks_first_entry": dist(shift_bytes_first_entry),
            "reading": "each summary entry is one (component, block) pair stored in the run of its "
                       "component; a block's entries are spread over as many component runs as it has "
                       "entries. span_fraction = (last - first + 1) / values_len of the list.",
        },
        "code_facts": [
            "Summary layout is component-major: entries of component c occupy positions "
            "offsets.select(c)..offsets.select(c+1) (sparse: via component_ids index i; dense: "
            "select(c) - c) of values[] and summaries_ids[]; summaries_ids[p] is the block id of entry p "
            "(src/mmap_index.rs MmapQuantizedSummary::distances; src/quantized_summary.rs distances).",
            "offsets is ONE Elias-Fano sequence per list over all components (dense: dim+1 = 28,703 values; "
            "sparse: component_ids_len+1), with a DArray/Inventories select index "
            "(src/mmap_io.rs read_posting_lists; manifest ef_* / inv_* fields).",
            "summaries_ids is ONE fixed-width bitfield per list, width = bits(n_blocks - 1); values is one u8 "
            "array per list; minimums/quants are per-block f32 arrays indexed by block id.",
            "Whether a list uses dense offsets or component_ids is chosen per list by a size comparison "
            "(src/quantized_summary.rs space_usage for sparse vs dense offset strategy).",
            "Packed postings of block b are packed_postings[bo[b]..bo[b+1]]; block_offsets is a dense prefix "
            "array of usize, the end of block b is the start of block b+1 (src/mmap_index.rs block_slice).",
            "No on-disk field names a list: the reader derives every list's slices at load time by walking the "
            "manifest's per-list lengths with alignment padding (src/mmap_io.rs read_posting_lists); the "
            "manifest is JSON and the resulting &'static slices are fixed for the process lifetime.",
        ],
        "separable": {
            "block_summary": False,
            "why": [
                "Re-encoding one block's summary (the build recomputes its alpha-mass component set and its "
                "u8 quantisation) inserts or removes (component, block) entries in the middle of the list's "
                "component-major values[] / summaries_ids[] arrays whenever the block's component set changes, "
                "which shifts every later entry and changes the list's Elias-Fano offsets from that component on.",
                "Adding a component the list's summary does not yet carry also changes component_ids "
                "(sparse lists) and can flip the list between the dense and sparse offset strategies.",
                "A block's new block count or posting count is not representable either: summaries_ids width "
                "depends on the list's block count, and block_offsets is a prefix array.",
                "Only a same-component-set requantisation is fixed-width (the block's u8 values + its f32 "
                "min/quant), but those u8 values are scattered over the block's component runs "
                "(separability_evidence) and it is not what the build does when the component set changes.",
            ],
            "block_postings": "contiguous slice, but not relocatable alone: its extent is two neighbouring "
                              "entries of a dense prefix array (block_offsets[b], block_offsets[b+1])",
        },
        "data_consistent_with_code_verdict": bool(interleaved_lists > 0 and blocks_with_entries > contig),
        "write_unit": "LIST",
        "rule": "BLOCK if separable, else LIST (plan 06 second addendum)",
        "offset_flip": {
            "LIST": {
                "on_disk_offsets_naming_a_list_in_v2": 0,
                "finding": "no single 8-byte store can publish a rewritten list in the v2 format: a list's location "
                           "is the prefix sum of manifest lengths (JSON), computed once at load",
                "consequence": "A2b needs an indirection table in format v3: one fixed-width, 8-byte-aligned offset "
                               "per list (plus a self-describing unit header carrying the list's ~23 manifest scalars "
                               "and a checksum), read by the decoder at query time",
            },
            "BLOCK": {
                "offsets_naming_a_block": "postings: 2 entries of the dense block_offsets prefix array "
                                          "(bo[b], bo[b+1]; shared with the neighbours); summary: its entries' "
                                          "positions inside per-component Elias-Fano runs + the summaries_ids bitfield",
                "flippable_in_place": False,
                "finding": "the offsets that name a block are inside a dense prefix array and an Elias-Fano "
                           "sequence; neither can be flipped by one aligned 8-byte store",
            },
        },
    }
    res["meta"]["seconds"] = round(time.time() - t0, 1)
    res["meta"]["live_index_guard"] = [guard_start, check_live_unchanged("w1-end")]
    Path(a.out).write_text(json.dumps(res, indent=2))
    log("wrote", a.out, res["meta"]["seconds"], "s")
    print(json.dumps({"write_unit": res["write_unit"],
                      "per_list_total_span_p50": res["bytes_per_list"]["whole_list_span"].get("p50"),
                      "share_contiguous": res["separability_evidence"]["share_contiguous"],
                      "span_frac_p50": res["separability_evidence"]["block_entry_span_fraction_of_list_summary"].get("p50")}))


if __name__ == "__main__":
    main()
