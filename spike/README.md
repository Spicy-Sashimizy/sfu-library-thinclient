# spike/ — vendored engine forks and spike code

**Status:** ACTIVE

Experimental code and the vendored Rust engines the served stack is built on.
Rules for agents (portability flags, what never to merge) are in `CLAUDE.md`
here; this file is the human map. Pre-registered harnesses keep their inline
comments (policy exemption).

| Directory | What | Docs |
|---|---|---|
| `seismic_upstream/` | the LIVE SEISMIC Rust fork (gitignored nested repo; tracked as `seismic_upstream_fork.patch` + the four smaller patches). Build recipes in doc 10 §7.7 | `docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` |
| `seismic_testbed_instrumented/`, `toolkit_fork/`, `vectorium_fork/` | instrumented / vendored forks used by the testbed | `CLAUDE.md` |
| `delta_ingest/` | ACTIVE: source-agnostic trickle-update ingest (records → buffer → immutable generations → compaction → fold-in). Serving reader is `src/lib/thinclient/delta_layer.py` | `docs/delta_ingest/` |
| `convergence_repro/` | page-cache convergence reproduction harness, pre-registrations and RESULTS | `docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md` |
| `ebpf_pagecache/` | cache_ext eBPF eviction-policy spike (compiles; cannot load here) | its `README.md` |
| `bm25_seismic/` | BM25 served through SEISMIC spike | `docs/seismic_150m_testbed/17_BM25_THROUGH_SEISMIC_SPIKE.md` |
| `meta_consolidation/` | ordinal-addressing / metadata consolidation benches | `docs/seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` |
| `archive/` | closed spikes kept as evidence: `mmap_bmp/`, `smallmachine_levers/`, `block_prefetch/`, `inplace_update/`, `n2_mphf/` (MPHF viability for ordinal addressing, CLOSED MEASURED 2026-09-27, moved 2026-10-11; its `README.md`) | `docs/README.md` §Closed tracks |

Work directories (`work*/`, `.venv-lance/`) are gitignored build outputs.
