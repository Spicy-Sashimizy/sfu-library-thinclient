# archive/ — historical, kept for the record

Nothing here is current. Never answer questions from these without saying so
(source-of-truth rules: `.claude/CLAUDE.md`). Kept because they document how
decisions were reached or hold dated eval results whose headlines were
restated in live docs.

| Doc | Why kept |
|---|---|
| `MASTER_TODO.md` | Pre-swap phase tracker (the old todo system; current work is tracked in session memory + the convergence-artifact publication gate) |
| `LLM_BENCHMARK_RESULTS_2026-05-16.md` | Dated eval results |
| `COMPRESSION_EVAL_RESULTS.md` | Original Lucene lossless levers + dense quantization; headlines restated in `docs/STORAGE_BUDGET_150M.md` |
| `SESSION_NOTES_2026-05-24.md` | Session notes |
| `SFU_EMBEDDING_MODEL_PLAN.md`, `STACKING_AND_DATA_FIX_PLAN.md` | Completed or superseded plan docs |

Added 2026-09-01: `SEARCH_ENGINE_ALTERNATIVES.md` (rescued from the deleted
`thin-client/` handoff directory — the June-era fork of the repo's own docs
whose other files were divergent duplicates of `docs/` copies; recoverable
from git history). Deleted the same day, also recoverable from history:
root `ollama-proxy.py` (superseded by the compose-heredoc live copy),
`setup_wsl.sh` (zero references), `deploy/backup.sh` + `deploy/restore.sh`
(copy-paste cruft from another project — "vanse" paths, Postgres; this repo
has neither).
