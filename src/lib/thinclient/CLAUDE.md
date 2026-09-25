# lib/thinclient — serving + index-build package

Module map: `sections.py` (subject classifier, era sub-sections `<base>__recent`/
`__archive` boundary 2010, era-qualified PERSONAS) · `builder.py` (per-section
tantivy + BMP shards + sidecars; per-slice `slice_checkpoint()`/resume — meta &
abstracts are WAL, BMP shards never span spool slices; kill/resume parity test:
`scripts/tests/test_build_resume.py`) · `retriever.py` (drop-in ThinClientRetriever,
RRF k=60, era pruning) · `abstracts.py` (v3 script-bucketed 32KB zstd-dict
blocks; reads v1/v2 too; N5 flat sidecar + ordinal block locator + rehomed dicts with a fail-closed
identity gate — doc 18 §17-§18; serves SQLite-free with abstracts.sqlite
deleted, only the build-time emit is left; optional locator pre-fault at open,
`SFU_ABSTRACTS_PREFAULT=1`, default OFF, fail-open — doc 18 §23, efficacy
unmeasured)
· `packer.py` (hot/cold tar+zstd-19 on built artifacts)
· `dense_cache.py` (query-driven warm cache, `SFU_DENSE_WARMCACHE`; inert by
default since 2026-08-18 — the dense leg gate `SFU_DENSE_LEG` is DEFAULT OFF,
only literal `1` enables, per the ablation DROP verdict; v2 2026-09-25: usearch
delta index above `SFU_DENSE_DELTA_USEARCH_MIN`, int8 ONNX encoder behind
`SFU_DENSE_ENCODER_ONNX`, both default-inert)
· `dense_delta_merge.py` (`merge_dense_delta`: fold the SQLite delta into the
seed artifacts atomically, then truncate; 2026-09-25, serving efficacy unmeasured)
· `doc_encoder.py` (GPU TRT batch SPLADE encoder for monthly rebuilds).

Run anything with the venv: `/workspaces/sfu-library-thinclient/.venv/bin/python3`.

Code is comment-free (policy 2026-09-01): the full constraints/invariants
ledger for this package is `docs/CODE_INVARIANTS.md`; gates are in
`docs/ENV_GATES.md`.

BMP 0.2.6 hard-won quirks (do not "simplify" these away):
- `QUANT_SCALE = 70` — u8 impacts saturate at 255; scale 100 clips, 1000
  collapses recall to 0.28.
- Panics if NO query term exists in a shard → `*.vocab.zst` sidecars + skip.
- `beta=0.0` panics; indexes < ~500 docs return empty → tail shards < 5k
  absorbed into the previous shard.
- `bsize=256` + chunked top-term clustering: measured −54% size, −61% latency.

meta.sqlite is v2 (INTEGER-PK W-ids + `docs_other` TEXT overflow); the
retriever auto-detects v1/v2. Tests: `scripts/tests/test_thinclient_stack.py`.

Any change to architecture, defaults, or measured numbers in this package MUST
update `docs/THIN_CLIENT_SWAP.md` (and the doc stating the old value) in the
SAME commit — see the doc-freshness rules in the root CLAUDE.md.
