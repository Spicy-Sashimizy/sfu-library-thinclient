# scripts/reproduce/ — rebuild a servable index from the public OpenAlex snapshot

The outsider's path into this project: raw OpenAlex `works` part files in,
every served artifact type out, one command, then a real search through the
retriever to prove it serves. Doc: `docs/REPRODUCIBILITY.md` (recipe,
prerequisites, measured record, limits).

| Script | What |
|---|---|
| `rebuild_from_openalex.py` | `--download N` (from the live manifest) or `--part file.gz` → delta-ingest chain against an empty base → one published generation (tantivy sections, `meta.sqlite`, abstract sidecars, SEISMIC dotvbyte-v2 shard, manifest) → `serve.env` → verify → `rebuild_report.json` |
| `verify_rebuild.py` | loads `ThinClientRetriever` on `SFU_THINCLIENT_INDEX_ROOT` + `SFU_SEISMIC_SHARD_MANIFEST`, runs fused searches with provenance, PASS only if both legs contribute, every hit is hydrated and no leg fell back |

```bash
.venv/bin/python3 scripts/reproduce/rebuild_from_openalex.py --work /var/tmp/duck_rebuild --download 1 --limit 50000
set -a; . /var/tmp/duck_rebuild/serve.env; set +a
scripts/serve_http.sh
```

Measured 2026-10-10 on this host: 50,000 input works → 21,122 kept → built
in ≈ 162 s (244 s with the driver's verify step, whose cost is the one-time
query-model load), serve check PASS
(`data/eval_results/reproduce_openalex_50k_2026-10-10.json`).

Rules: the work dir must be local disk outside the repo's `data/` tree; the
driver forces one generation per run (`--flush-docs`/`--buffer-max-docs`
raised), so keep a run under ~1 M works on a 32 GB host (*est.*); it needs
the two Rust tools under `spike/seismic_upstream/target/release/` and the
`seismic` wheel in the venv (`docs/REPRODUCIBILITY.md` §3).
