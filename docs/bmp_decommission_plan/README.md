# bmp_decommission_plan/ — BMP→Qdrant decommission plan + metrics suite

Historical track: the decommission of the BMP sparse backend in favor of
Qdrant, with its go/no-go gates and presentation metrics. Superseded in spirit
by the later SEISMIC promotion (`docs/SEISMIC_ARCHIVE_SPLIT.md`, 2026-07-06)
but the measured numbers here remain referenced (e.g. `DO_SIZING.md` RAM
floors quoted by `docs/seismic_150m_testbed/`).

| Doc | What it is |
|---|---|
| `PLAN.md` | Workstream plan + progress tracker |
| `METRICS_CATALOG.md` | Metric → script → result file → baseline → delta, with dates and measured/est/unmeasured tags |
| `PRESENTATION_METRICS.md` | Presentation-ready tables + narrative |
| `VALIDATION_REPORT.md` | BMP-vs-Qdrant go/no-go gate table |
| `DO_SIZING.md` | Droplet RAM/disk/cost sizing from measured page-cache behaviour (Qdrant@150M: 205 GB disk, needs ≥64 GB RAM) |

Canonical JSON ledger: `data/eval_results/METRICS_CATALOG.json`.
