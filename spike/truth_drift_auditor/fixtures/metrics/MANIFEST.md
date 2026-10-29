# fixtures/metrics — copied measured results for testing

Copied verbatim on 2026-10-29 from the SFU library thin client's
`data/eval_results/` (read-only source; these copies are the spike's own and
travel with it). They are the *numerical technical base of truth* for the demo
and the tests. Paths in `config.example.toml` `[[metrics.aliases]]` point into
them as `<file stem>:<dotted.path>`.

| File | What it measured | Cited by (in the thin-client repo) | Useful paths |
|---|---|---|---|
| `dict_effect_at_scale_2026-10-19.json` | per-script zstd dictionary effect on every block of the served abstract sidecar; 150M projection; cold-section scan | `spike/dict_effect_at_scale/README.md`, `docs/STORAGE_BUDGET_150M.md` §6 | `hot.totals.arms.{a_shipped,b_nodict,c_shared,d_latin}.{gb,pct_vs_b_nodict,decode_us_mean}`, `whole_database_projection.arms_gb_at_150m_est.*` |
| `c5_lance_vs_sqlite_20260802_0636.json` | Lance vs SQLite id-fetch latency on a 20M-row fixture | `docs/seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` | `results.{100,1000,...}.lance_over_sqlite`, `.sqlite.p50_ms`, `.lance.p50_ms` |
| `seismic_build_scale_20m.json` | SEISMIC index build at 20M docs (time, nnz, peak RSS) | `docs/seismic_150m_testbed/` | `build_seconds`, `peak_rss_gb`, `avg_nnz_per_doc` |
| `e8_stage0_perdoc_scale_20260708.json` | per-doc value scale vs fixed u8 quantisation, overlap@10 on two shards | `docs/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` | `shards.<shard>.{perdoc,fixedu8}.overlap@10_mean` |
| `ce_batch_invariance_2026-09-25.json` | cross-encoder batch invariance (max abs diff, ranking changed) | `docs/THIN_CLIENT_SWAP.md` rerank section | `cross_encoder.arms[i].max_abs_diff` |
| `delta_ingest_M4F_P2_20261001.json` | delta-ingest P2 quality re-check (M3 rank drift, M2 overlap, mask leak) | `docs/delta_ingest/` | `m3.part_a.{median_rank_change,share_same}`, `m3.part_b.displaced_share` |

To refresh or extend: copy more `*.json` files into this directory; the store
flattens every numeric leaf automatically (`tda metrics search <regex>` lists
them). Nothing here writes back to the thin client.
