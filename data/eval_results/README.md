# eval_results conventions

One flat dir of measurement evidence + campaign scratch. Rules:
- Naming: `<track>_<what>_<YYYYMMDD>[_<cell>].json` for results;
  `_<campaign>_*` underscore prefix for campaign scratch (queues, drive
  prompts/logs, status files).
- Results docs cite are CANONICAL — moving one requires repointing the doc
  in the same commit (grep first).
- Invalid runs: rename to `*.INVALID` + sidecar `.INVALID.note` explaining
  why (never delete — refuted expectations are valid results).
- Re-runs never clobber: thread a suffix (`_r3h` style) through outputs.
- `archive/` = unreferenced campaign scratch (bulk moves audited
  2026-07-17, REPO_AUDIT). New campaigns: move your scratch here at
  session end if nothing cites it.
