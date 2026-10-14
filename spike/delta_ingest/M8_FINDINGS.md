# M8 findings: abstract-sidecar bytes/abstract at delta size

**Status:** ACTIVE

Measured 2026-09-30 (UTC) on this host, CPU/IO only (no retriever, no index
load), niced on cores 8-15 beside a B7 run and an S0-2 process. Bar is that of
`docs/delta_ingest/03_SPIKE_PLAN.md` M8, unchanged. Numbers are copied from
the results file, which is authoritative.

- Results: `data/eval_results/delta_ingest_M8_20260930.json`
- Harness: `scripts/experiments/eval_delta_ingest_m8_sidecar_ratio.py`
  (pre-registered header commit d50fb45b; post-hoc revision + result of record
  commit 2df2a0d2)
- No timing is a deliverable (`timings_valid: false` everywhere).

## Setup

Stores measured are the per-section `gNNNN/sections/<section>/abstracts.sqlite`
(format v3, `lib.thinclient.abstracts.AbstractStoreWriter`: per script bucket,
dict trained at 20,000 docs or at `finish()` when the bucket has >= 300 docs,
otherwise the section's latin dict if it has one, else plain zstd-19; 32 KB
blocks). Generations are the M4 ones built 2026-09-29 from corpus (b), opened
read-only: "200k" arm = `root_n1/g0001` (160,347 docs; the partition yields
fewer than 200k, deviation), "20k" arm = `root_n8/g0001..g0008` (20,043-20,044
docs each). Every block was decompressed with the reader's dict rule to count
raw bytes and characters.

The 351.8 B/doc reference (`storage_levers_eval.json` `abstracts_full_config`,
2026-06-11) is **compressed block payload only** over 20,000 sampled abstracts
(all with text), per-language dicts trained in-sample, dict bytes and locator
excluded, raw/payload 3.42x. So:

- H = on-disk store bytes / abstract (headline; includes dicts, SQLite locator
  `docs` table and page envelope), R_H = H / 351.8
- P = payload / abstract (like-for-like with 351.8), R_P = P / 351.8
- R_N = 3.42 / (raw/payload) — length-normalised, since corpus lengths differ

Context, not the bar: the served base store (one section,
`social_sciences__recent`, 23,398,073 rows) is 475.7 B/abstract payload
(`blocks.bin`), 575.7 B/abstract as SQLite, 493.7 flat + locator; a seeded
1,000-block sample gives raw/payload 3.254 and an estimated 1,526 chars per
abstract.

## Result of record (pre-registered)

| arm | docs | H B/abs | P B/abs | R_H | R_P | R_N | mean chars |
|---|---|---|---|---|---|---|---|
| 200k (root_n1/g0001) | 160,347 | 109.1 | 51.2 | 0.310 | 0.145 | 0.579 | 296.1 |
| 20k mean of 8 | 20,043-20,044 | 127.75 | 49.7 | 0.363 | 0.141 | 0.554 | 296.1 |
| 20k min / max | | 116.5 / 163.9 | 41.3 / 85.2 | 0.331 / 0.466 | 0.117 / 0.242 | 0.500 / 0.750 | 275.8 / 375.8 |

**Verdict: RECORDED. Dict-reuse lever NOT triggered** (R_H and R_N <= 1.3 in
both arms). The pre-registered lever arm (control vs base-dict-seeded rebuild of
chunk 0) was therefore not run.

**This result says almost nothing about dictionary economics.** Corpus (b) is
89.8% `type=dataset` (143,984 of 160,347) and 143,999 of its abstracts (89.8%)
are exact duplicates of an earlier abstract in the corpus (in
`other__recent` of the 200k arm: 90,995 latin abstracts, 4,830 distinct —
boilerplate plasma-experiment dataset descriptions). Mean abstract is 296
chars vs ~1,526 in the base. Duplicates inside a 32 KB block compress to
nearly nothing (latin raw/payload 9-10x in `other__recent`/`phys_eng__recent`),
which is what drives R_H far below 1.

Also recorded: the on-disk length-normalised ratio R_N_disk
(3.42 / (raw / file bytes)) is 1.446 mean (1.401-1.488) for the 20k arm and
1.235 for the 200k arm. It was reported but was not part of the pre-registered
trigger.

Per-section structure (both arms): an empty-ish store has a 24,576-byte floor
(six 4 KB pages), so archive sections with 1-30 docs cost 1-25 KB/abstract;
a generation adds up to 7 x 112 KB trained dicts per section, and zstd trains
smaller dicts on repetitive samples (5.5-16.5 KB seen). The 20k arm spends
14.8 B/abstract on dicts (10.7-17.6) and 63.2 B/abstract (61.7-66.2) on
locator + envelope, against 49.7 B/abstract payload (`summary` in the results
file); the 200k arm 2.3 and 55.6 against 51.2.

## Post-hoc supplement (declared in the header after the run; not the verdict)

Same writer and section split, stores only (no tantivy/meta/SEISMIC), under
`/home/vscode/work/delta_ingest/m8/posthoc/`. S1 = corpus (b) records whose
abstract is the first occurrence (16,348); S2 = records with type != dataset
(16,363). Control = unmodified writer; seeded = every store pre-seeded with
the base's seven dicts (so none is trained); ref = seeded store with the
dict rows deleted and VACUUMed (a generation that references the base dicts).

| set / variant | H B/abs | P B/abs | R_H | R_P | R_N | mean chars |
|---|---|---|---|---|---|---|
| S1 control | 532.4 | 402.8 | 1.513 | 1.145 | 1.087 | 1214.9 |
| S1 seeded (dicts copied) | 1016.0 | 431.6 | 2.888 | 1.227 | 1.165 | 1214.9 |
| S1 seeded, dicts referenced | 524.9 | — | 1.492 | — | — | 1214.9 |
| S2 control | 516.7 | 387.9 | 1.469 | 1.103 | 1.072 | 1179.8 |
| S2 seeded (dicts copied) | 1002.5 | 419.6 | 2.850 | 1.193 | 1.160 | 1179.8 |
| S2 seeded, dicts referenced | 511.9 | — | 1.455 | — | — | 1179.8 |

Seeded vs control: payload +7.1% (S1) / +8.2% (S2), H with copied dicts
x1.91 / x1.94, H with referenced dicts x0.986 / x0.991.

Reading (post-hoc, for the coordinator):
- On article-like content a ~16k-doc generation is ~1.5x the 351.8 B/doc
  headline, but payload is only 1.10-1.15x and length-normalised 1.07-1.09x.
  The gap is the SQLite locator/envelope (93-95 B/abstract; the served base
  pays ~100 B/abstract for the same, 575.7 - 475.7) and per-section dicts
  (~35 B/abstract). Against the served base on disk per character: S1 0.438
  B/char vs base 0.377 B/char (1.16x).
- Pre-seeding the base dicts, the lever named in A1, does not help at this
  size: the base dicts compress 7-8% WORSE than dicts trained in-generation per
  section, copying them costs ~490 B/abstract, and even referencing them saves
  only 1-1.5% of H. Compaction into larger generations (amortising the dicts,
  the 24 KB section floor and fallback buckets) is the lever the numbers
  point to; it is unmeasured here.

## Not measured

- A 200k-doc generation of article-like content (corpus (b) has ~16k such
  records).
- The pre-registered lever arm (not triggered).
- Read latency of delta stores; flat/locator sidecar for generations (A3).
- Found, not fixed (not this item's file): `AbstractStoreWriter._train`
  (`source/lib/thinclient/abstracts.py:185-187`) compresses an untrained bucket
  with plain zstd when latin has no dict yet, while the reader
  (`_build_v3_dctxs`, `abstracts.py:721-725`) would decode that bucket with
  `zdict_latin` if latin is trained later in the same store. Reachable only
  when a non-latin bucket reaches 20,000 docs before latin is trained AND its
  own `train_dictionary` raises `ZstdError`; not observed in any store
  measured here (every block decoded).
