# spike/dict_effect_at_scale — per-script zstd dictionaries measured on the production sidecar

**Status:** ACTIVE (measurement started 2026-10-19; this file is the spike's
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

## Findings

Filled in after the run — see the results file and
`docs/STORAGE_BUDGET_150M.md` §"Dictionary effect measured at scale (2026-10-19)".

Results: `data/eval_results/dict_effect_at_scale_2026-10-19.json` (summary),
`..._hot_blocks.npz` (per-block rows), `..._shared.zdict` (the arm-c dictionary).
