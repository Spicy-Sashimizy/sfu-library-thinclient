# Contributing

This project is a research testbed maintained by one person with AI
assistance. Contributions are welcome as issues and pull requests; the rules
below are the ones every change here has followed since 2026-06, human or
agent. The full text is `.claude/CLAUDE.md`.

## Where things are

`README.md` has the repository map; every top-level directory has its own
README. The architecture is `docs/THIN_CLIENT_SWAP.md`; the index of all
documentation is `docs/README.md`.

## Run and test

```bash
.venv/bin/python3 -m pytest -q              # whole suite: src/tests + scripts/tests (pytest.ini)
.venv/bin/python3 -m pytest src/tests -q    # the fast half
/usr/local/bin/ruff check src --select F    # unused imports / names
```

Some `scripts/tests` need the local index or a memory profile and skip or
fail without them; the suite baseline is recorded in
`docs/infrastructure/REPO_REORG_2026-10-10.md`.

## Rules for a change

First thing after cloning: `scripts/repo_tools/install_git_hooks.sh` installs the
tracked pre-commit hook (big-file guard, gitleaks, script placement policy,
substantial-change gate). Policy and the exact rules:
`docs/infrastructure/SCRIPT_HYGIENE_POLICY.md`.

1. **Code wins over docs.** If a doc contradicts the code, fix the doc in the
   same commit you noticed it.
2. **Same-commit doc rule.** A commit that changes architecture, defaults,
   measured numbers, env gates or file locations updates the affected doc in
   that commit (`docs/THIN_CLIENT_SWAP.md`, `docs/STORAGE_BUDGET_150M.md`,
   `docs/README.md`, the `CODE_INVARIANTS*` ledgers).
3. **Measured claims only.** A new module or lever is not done until its
   efficacy is recorded: metric, numbers before → after, eval script path,
   results file under `data/eval_results/`, absolute date. Otherwise mark it
   *est.* or "IMPLEMENTED, EFFICACY UNMEASURED".
4. **No inline comments in product code** (policy 2026-09-01). Docstrings
   stay. Constraints go in `docs/CODE_INVARIANTS.md` /
   `docs/CODE_INVARIANTS_SCRIPTS.md` / `docs/ENV_GATES.md`.
5. **Closed tracks are moved, not deleted.** Banner `> **CLOSED <kind>
   <date>**`, move to `docs/archive/` or `docs/deprecated/` (code to
   `scripts/archive/` or `spike/archive/`), repoint every reference, move its
   `docs/README.md` row. `scripts/tests/test_doc_status.py` enforces the
   status vocabulary.
6. **Moving files:** `git mv`, then repoint every citing path in the same
   commit (`git grep -n '<name>' -- docs scripts spike web .claude src`).
7. **Git hygiene:** stage files explicitly (never `git add .` — the working
   tree holds multi-GB runtime state), commit immediately, push. Absolute
   dates only (2026-10-10, never "today").
8. **Never touch `data/seismic_150m/`.** It is the irreplaceable served
   index; `docs/infrastructure/INDEX_WRITE_PROTECTION.md`.

## Python environment

Use the project venv only: `/workspaces/sfu-library-thinclient/.venv/bin/python3`.
Installs: `sudo .venv/bin/python3 -m pip install <package>`.
