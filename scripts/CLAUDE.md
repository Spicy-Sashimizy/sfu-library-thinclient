# scripts/ — rules for agents (the human map is README.md)

- Family map and what each family is: `README.md` here. Keep it in sync with
  any move, in the same commit.
- The root holds operator entry points only (listed in `README.md`). New
  scripts go IN a family dir, never at the root.
- `experiments/` and `archive/` are evidence: superseded-but-cited. Never
  delete or "clean up" anything a doc or results file points at — pre-registered
  bars live in source at pinned commits (comment-policy exempt). A file that
  nothing names, that produced no recorded result and cannot run is clutter;
  it is deleted only through the triage ledger (hash recorded) and the
  preflight gate (`docs/infrastructure/SCRIPT_HYGIENE_POLICY.md` §5).
- `demo_broker/` is DEPLOYED (reopened 2026-10-06; the running copy is on the
  broker box). Edits here change nothing until redeployed.
- `seismic_testbed/` is active research; `tests/` is the pytest suite half
  that lives here (`pytest.ini` at the root runs both halves).
- Moving or renaming any file: `git mv`, then repoint every citing doc in the
  same commit (`git grep -n '<name>' -- docs scripts spike web .claude src`).
- Always run python via the venv: `.venv/bin/python3`.
- New `.py` here needs a `Lifecycle:` docstring line (`operator|library|tool|harness|one-off`;
  `harness`/`one-off` add `Doc:`, `one-off` adds `Results:` and lives only in `experiments/`).
  `repo_tools/check_script_placement.py --paths <file>` tells you before the hook does.
- Before committing ≥10 files, ≥500 lines, or any delete/rename of code: stage the final
  set, then `.venv/bin/python3 scripts/repo_tools/preflight.py run --slug <what>` (restore
  tag + fast tests + function inventory). The commit is refused without it.
  Policy: `docs/infrastructure/SCRIPT_HYGIENE_POLICY.md`.
