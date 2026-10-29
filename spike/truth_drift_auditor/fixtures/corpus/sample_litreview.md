# Sample base-of-truth corpus (text form)

This file stands in for a literature review or a set of reference notes. It is
built from measured statements in the SFU library thin client's own documents
(spike/dict_effect_at_scale/README.md, docs/STORAGE_BUDGET_150M.md, dated
2026-10-19 / 2026-08-02 / 2026-06-26) so that the offline demo has something
true to retrieve against. Replace it with your own corpus.

## Abstract sidecar compression (measured 2026-10-19)

A census of every block of the served social_sciences__recent abstract sidecar
(1,062,917 blocks, 23,398,073 docs) compared four compression arms. Shipped
per-script zstd-19 dictionaries store 11.132 GB, 475.7 bytes per doc, a 3.248x
ratio over the raw payload, and are 17.58 % smaller than the no-dictionary arm
(13.505 GB). The dictionaries save 2.374 GB on the served section.

"Any dictionary" is the lever: a single shared dictionary trained on a random
20k sample is 18.36 % smaller than no dictionary, and routing by script on top
of it is worth 37.6 MB on this section because non-Latin buckets are 1.3 % of
its docs.

Decode cost is higher with dictionaries, not lower: mean decode time per block
is 189.5 us with the shipped dictionaries against 83.5 us without any
dictionary (p50 146 us vs 69 us), measured under full 16-thread compression
load rather than serving conditions.

Projected to the 150,413,098-work corpus by bytes per doc, the sidecar is
estimated at 71.56 GB with shipped dictionaries and 86.82 GB without, an
estimated saving of 15.26 GB. The projection assumes the whole corpus has the
hot section's script mix. The earlier 2026-06-11 figure of 64.7 to 52.9 GB was a
20k-sample projection and is superseded.

Cold sections carry no abstract sidecar at all (abstracts_stored == 0 by the
cold policy), so the dictionary effect there cannot be measured.

## Metadata store benchmark (measured 2026-08-02)

On a 20,000,000-row fixture, fetching 100 rows by id took 39.25 ms p50 from
SQLite and 67.67 ms p50 from Lance, so Lance was 1.72x slower than SQLite at
that batch size. The absolute milliseconds are optimistic versus 150M-row
production; the ratio is the claim.

## SEISMIC build at 20M documents (measured 2026-06-26)

Building the standard-variant SEISMIC index for the med_bio_20m section from
stored sparse vectors (no re-encode) took 1021.76 s plus 15.6 s to save, over
20,000,000 docs with 1,534,643,337 non-zeros (76.73 per doc) and a peak RSS of
9.535 GB.
