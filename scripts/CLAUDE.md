# scripts/ — rules for agents (the human map is README.md)

- Family map and what each family is: `README.md` here. Keep it in sync with
  any move, in the same commit.
- The root holds operator entry points only (listed in `README.md`). New
  scripts go IN a family dir, never at the root.
- `experiments/` and `archive/` are evidence: superseded-but-cited. Never
  delete or "clean up" — docs cite these paths and pre-registered bars live
  in source at pinned commits (comment-policy exempt).
- `demo_broker/` is DEPLOYED (reopened 2026-10-06; the running copy is on the
  broker box). Edits here change nothing until redeployed.
- `seismic_testbed/` is active research; `tests/` is the pytest suite half
  that lives here (`pytest.ini` at the root runs both halves).
- Moving or renaming any file: `git mv`, then repoint every citing doc in the
  same commit (`git grep -n '<name>' -- docs scripts spike web .claude src`).
- Always run python via the venv: `.venv/bin/python3`.
