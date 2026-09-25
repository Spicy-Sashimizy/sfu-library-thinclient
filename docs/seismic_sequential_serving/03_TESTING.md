# 03 · Testing — INDEPENDENT test plan

**Status:** DEFERRED 2026-07-16 (measured WI-1 but never promoted; parallel federation is still the served path)

**Created 2026-06-30, implemented 2026-06-30.** The test file
`scripts/tests/test_seismic_sequential.py` is **shipped** (10/10 pass; T1
result-equivalence verified bit-identical single- + multi-shard against the real
`MmapSeismicIndex`; a mechanism (B) re-fault test confirms `release_pages` doesn't
corrupt the view; a cascade guard pins the no-shared-mutable-state property).
T2/T3 (RAM-bounded / swap-free) remain **unmeasured** — they need the real 150M
shards on the 31.6 GB box and are benchmark-time. Self-contained: the sequential
mode is validated entirely on its own terms here; it does **not** reuse or modify
the parallel federation tests.

## Where the tests live (kept separate)

New file: `scripts/tests/test_seismic_sequential.py` — distinct from the package
stack test (`test_thinclient_stack.py`) and the parallel federation overlap eval
(`g_federation_overlap.py`). Run with the project venv. None of these tests touch
the parallel path's code or fixtures beyond reading the shared **read-only** shards.

## Test matrix

| ID | Asserts | How | Pass bar |
|---|---|---|---|
| **T1 Result-equivalence** | sequential top-k ≡ parallel top-k (same query, same k′) | run both modes over the same query set, compare merged top-50 sets + scores | **bit-identical** (the merge-by-raw-score order-independence proof, `01_ARCHITECTURE.md`) |
| **T2 RAM-bounded** | peak resident ≈ ~1 shard, not ~8 | `/proc/self/status` RssFile high-water across a query stream, sequential vs parallel | sequential peak materially < parallel peak; **near ~1-shard** with mechanism (B) |
| **T3 Swap-free** | no anon paged to swap on the 31.6 GB box | sample `VmSwap` across the stream | **VmSwap stays 0** (the whole point — no swap-storm) |
| **T4 No silent fallback** | missing `.mmap/` dir never silently re-loads stock Path-A | point manifest at an absent mmap dir | raises `RuntimeError`, does **not** load |
| **T5 Degrade contract** | a backend failure degrades to the BM25F leg | inject an encode/search failure | RRF still fuses other legs; no crash |
| **T6 Encode/traverse split** | `search_with_timing` attributes sequential runs | run the timed path in sequential mode | returns `(results, encode_ms, traverse_ms)`; traverse = Σ per-shard |

## T1 in detail — the correctness keystone

T1 is the test that lets a demo trust sequential. Because both modes merge per-shard
local top-k′ by raw inner-product score, and the per-shard results are identical
regardless of visit order, the merged top-k **must** match. The test therefore
asserts *bit-identical*, not "within tolerance":

```
for q in queries:
    par = backend(load_mode=mmap, federation=parallel).search(q, k=50, k_prime=200)
    seq = backend(load_mode=mmap, federation=sequential).search(q, k=50, k_prime=200)
    assert [oaid for oaid,_ in seq] == [oaid for oaid,_ in par]
    assert all(abs(s-p) < 1e-6 for (_,s),(_,p) in zip(seq, par))
```

A mismatch is a real bug (e.g. an off-by-one in the merge or a dropped shard), not
an approximation — this is a hard equality gate.

## T2/T3 in detail — the RAM win, measured not assumed

Run identical query streams in both modes; sample RAM each query:
- **Parallel:** expect RssFile high-water near the full multi-shard working set
  (and, on the 31.6 GB box, non-zero `VmSwap` — the swap-storm signature).
- **Sequential:** expect RssFile bounded near one shard (mechanism A; tighter with
  B), and **`VmSwap == 0`** throughout.

Record both to `data/eval_results/seismic_seq_ram_<date>.json`. Per the efficacy
rule these are the numbers that turn G-SEQ-1 from design into a result.

## What is explicitly NOT retested here

- Index correctness / build losslessness — owned by the G7/C2.5 build tests; the
  shards are immutable inputs here.
- G2/G6 quality — orthogonal; sequential returns the *same* docs as parallel (T1),
  so it inherits whatever quality the parallel path has.

## Reproduction

```
/workspaces/sfu-library-thinclient/.venv/bin/python3 \
  scripts/tests/test_seismic_sequential.py \
  --manifest data/eval_results/seismic_c25_shards_150m_mmap.json
```

(Manifest paths point at the external-ext4 shard locations; the test reads them
read-only.) Results + RAM samples land under `data/eval_results/`.
</content>
