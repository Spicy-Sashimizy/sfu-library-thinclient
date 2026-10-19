# spike/dict_effect_at_scale — per-script zstd dictionaries measured on the production sidecar

**Status:** CLOSED MEASURED 2026-10-19 (census complete; this file is the spike's
pre-registration and findings record)

**Kind:** timed information-retrieval spike. Not product code. The script
imports nothing from `source/`, reads `data/thinclient_index/` read-only,
writes only under `data/eval_results/` and never touches mainline code.

## Question

The abstract-sidecar dictionary lever (`source/lib/thinclient/abstracts.py`,
format v3: script-bucketed ~32 KB blocks, zstd-19, one 112 KB dictionary
trained per script bucket) was measured only on a 20,000-abstract sample on
2026-06-11 (`scripts/experiments/eval_text_compression.py` →
`data/eval_results/text_compression_eval.json`;
`scripts/experiments/eval_per_language_dicts.py` →
`data/eval_results/per_language_dicts_20260611.json`). The storage docs quote
"64.7 → 52.9 GB at 150M", which is that sample ratio projected, not measured.
What do the shipped dictionaries actually save on the served store?

## Method (pre-registered 2026-10-19, before the full run)

Script: `eval_dict_effect_at_scale.py` (this directory). Seed 20261019.

**Hot section `social_sciences__recent`, every block (census).** Source:
`data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite.flat/`
(flat store `01ce8b7f-b9f3-442a-8c23-2ff5997651aa`, 1,062,917 blocks,
23,398,073 docs, 7 shipped dictionaries). Per block: `pread` the stored bytes,
decompress with the shipped dictionary, then at zstd-19:

| arm | codec |
|---|---|
| a_shipped | the block's shipped per-script dictionary (what is on disk) |
| b_nodict | no dictionary |
| c_shared | one 112 KB dictionary trained here (same trainer, 20,000 docs sampled uniformly over the section's docs, so bucket shares follow the doc mix) |
| d_latin | the latin dictionary applied to every bucket |

Parity gate: recompressing the raw payload with the shipped dictionary must
reproduce the stored bytes byte-for-byte on every block (the zstd library is
1.5.7 on both sides); any non-identical block is also round-tripped. Docs per
block come from the ordinal locator (`loc_b.npy` bincount). Decode time per
arm per block is recorded. 16-process pool, blocks processed in `b` order.

**Cold sections.** The brief asked for a 1% stratified block sample per cold
section. There are no cold blocks: every packed section was built with
`abstracts_stored: 0` (`data/thinclient_index/build_status.json`; cold policy
is "fetch from the OpenAlex API before rerank"), and the archives under
`data/thinclient_index/packed/` hold SPLADE shards and tantivy only. The
script's `--cold-scan-only` mode streams every archive's member list and records
that in the results file so the gap is evidence, not an assertion. No bootstrap
interval is therefore possible; the hot figure is exact.

Searched 2026-10-19 for any other local source of cold-section abstracts
(read-only sweep of `data/`, `/var/tmp`, `/mnt`, `$HOME`, the spikes' work
directories, and the docs that name the corpus origin): none exists in bulk.
The OpenSearch source index was decommissioned 2026-06-11, `spool_backup/`
was reclaimed 2026-07-17, and the OpenAlex snapshot lives only on the NAS
named in `docs/ABSTRACT_SIDECAR_BACKFILL.md` (not mounted here). The sole
section-resolvable sample is `data/text_compression_sample.jsonl.gz` (20,000
docs, joined to `meta.sqlite` for the era: other__recent 9,199, med_bio__recent
2,270, cs_math__recent 2,093, phys_eng__recent 1,142, every archive section
under 450). That is the June sample scale this spike was meant to replace, so
no cold number is reported from it. A real cold measurement needs the NAS
snapshot and a cold sidecar build (about 1.5 h of zstd-19 on this host for
127M docs, after the parse).

**Projection.** Per-doc bytes per arm from the hot census × 150,413,098 docs,
marked est.: it assumes the corpus shares the hot section's script mix and raw
bytes per doc.

## Findings (2026-10-19, census complete)

Run: 16 procs, 42.4 min wall for the census (2,546 s), 2.0 s to train the
shared dictionary, cold-archive scan 16.9 min concurrently. zstd 1.5.7 via
python-zstandard 0.25.0, Ryzen 7 5700X3D, WSL2. **Parity: 1,062,917 /
1,062,917 blocks recompress byte-identical to the store** (stored bytes ==
arm-a bytes exactly).

| arm | hot section | B/doc | raw ÷ arm | vs no dict |
|---|--:|--:|--:|--:|
| a shipped per-script dicts | 11.132 GB | 475.7 | 3.248× | **−17.58 %** |
| b no dictionary | 13.505 GB | 577.2 | 2.677× | 0 |
| c one shared dict (random 20k sample) | 11.025 GB | 471.2 | 3.279× | −18.36 % |
| d latin dict on every bucket | 11.169 GB | 477.4 | 3.237× | −17.30 % |

Raw payload 36.15 GB = 1,545.1 B/doc over 23,398,073 docs (22.0 docs per
block). The dictionaries save **2.374 GB on the served section**.

Per bucket (B/doc, % vs no dict):

| bucket | blocks | docs | raw B/doc | a shipped | c shared | d latin |
|---|--:|--:|--:|--:|--:|--:|
| latin | 1,040,407 | 23,094,200 | 1,531 | 473.5 (−17.5) | 467.4 (−18.5) | = a |
| cyrillic | 11,948 | 163,203 | 2,547 | 592.9 (−25.0) | 697.6 (−11.8) | 710.4 (−10.2) |
| hangul | 3,795 | 62,936 | 2,051 | 568.2 (−22.2) | 689.5 (−5.6) | 688.7 (−5.7) |
| arabic | 3,870 | 36,873 | 3,696 | 903.8 (−22.7) | 1,044.5 (−10.6) | 1,043.2 (−10.7) |
| han | 1,961 | 30,400 | 2,263 | 755.2 (−20.9) | 856.5 (−10.3) | 859.7 (−10.0) |
| greek | 647 | 5,586 | 4,156 | 826.1 (−25.7) | 1,069.4 (−3.8) | 1,071.2 (−3.6) |
| kana | 289 | 4,875 | 2,177 | 534.5 (−33.5) | 754.6 (−6.2) | 756.7 (−5.9) |

What this says:

1. **"Any dictionary" is the lever: −17.3 % to −18.4 %.** The per-script
   routing on top of it is worth 37.6 MB on this section (a versus d, 0.34 %),
   because non-Latin buckets are 1.3 % of its docs. Per bucket the routing is
   large (−20.9 % to −33.5 % own dict versus −3.6 % to −10.7 % latin dict), so
   it would matter on a section with a different script mix; it is nearly
   free (1-byte dict id) and stays.
2. **A shared dictionary trained on a uniform random 20k-doc sample beat the
   shipped set by 107 MB (0.96 %).** The shipped latin dictionary was trained
   on the first 20,000 latin docs in ingest order (`AbstractStoreWriter._train`);
   the random sample is the better training set. Cheap follow-up, not a codec
   change: train per-script dictionaries on random samples (and try larger
   samples / dictionaries) at the next rebuild. Unmeasured beyond this one
   arm.
3. **The "64.7 → 52.9 GB at 150M" projection was wrong in absolute terms.**
   It came from 351.8 B/doc on a 20k sample whose abstracts averaged 1,203
   raw bytes; the served store averages 1,545 raw bytes per doc. Measured codec
   at 150M, est. (hot section's script mix): **71.6 GB with dictionaries vs
   86.8 GB without, dictionaries saving 15.3 GB**. The relative saving
   (−17.6 %) is close to what the sample implied (−18 %); the GB were 35 % low.
4. **Decode cost of the dictionary is ~7 µs per block.** Idle single-process
   decode of 3,000 random blocks × 3 (`..._decode_idle.json`): shipped dict
   48.6 µs mean (p50 46.1, p99 84.0), no dict 41.3 (38.9, 75.7), shared 47.6
   (45.2, 83.8). The census's per-block timings were taken under full
   16-thread compression load and show a ~100 µs gap between arm a/d and b/c
   that the idle run does not reproduce: arm a's timing also pays a fresh
   output allocation each block while b/c/d reuse the just-freed buffer, so
   those columns are load-and-allocation numbers, not dictionary cost.
5. **Cold sections: nothing to measure**, as pre-registered: all nine
   archives scanned (`..._cold_scan.json`), 0 abstract members in 684 tar
   members; `build_status.json` `abstracts_stored == 0` for each. The
   whole-database figures above are projections and carry no interval.

Results: `data/eval_results/dict_effect_at_scale_2026-10-19.json` (summary),
`..._hot_blocks.npz` (1,062,917 per-block rows: bytes per arm, docs, parity,
decode µs), `..._shared.zdict` (the arm-c dictionary),
`..._cold_scan.json`, `..._decode_idle.json`. Docs updated the same day:
`docs/STORAGE_BUDGET_150M.md` §6, `docs/LEXICAL_STORAGE_RESEARCH.md` §8.1,
`docs/THIN_CLIENT_SWAP.md`. Not touched (owner instruction 2026-10-19, no
mainline edits from this spike): the `source/lib/thinclient/abstracts.py`
docstring still reads "the measured 64.7 -> 52.9 GB config at 150M".

Results: `data/eval_results/dict_effect_at_scale_2026-10-19.json` (summary),
`..._hot_blocks.npz` (per-block rows), `..._shared.zdict` (the arm-c dictionary).
