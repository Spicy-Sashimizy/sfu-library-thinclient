# Script hygiene + change gates — placement, lifecycle, restore tags, preflight (2026-10-11)

**Status:** ACTIVE

**Why this exists.** By 2026-10-11 `scripts/` held 395 tracked files and `spike/`
247, and the 2026-10-10 reorganization had already found loose one-off scripts at
the repository root and in `scripts/`. The owner asked (2026-10-11) for three
things: a line-by-line triage of every script (active / move / delete), hooks so
one-time scripts stop accumulating and product code stays where it belongs, and a
standing rule that any large change gets a verified restore point and a test run
before it is committed, without the owner having to ask. This document is the
policy; the code is `scripts/repo_tools/`; the triage ledger is
`SCRIPT_TRIAGE_2026-10-11.md` (written by the triage agent, audited on Fable).

Restore point for the whole 2026-10-11 wave: restore tag
`pre-rust-core-and-script-triage-2026-10-11`, kept by the owner.
Verified before anything changed: detached checkout of the tag holds 2,525
files, `scripts/tests/test_doc_status.py` passes there, the serve path imports,
and `symbol_inventory.py diff` against it shows 5,332 functions/classes with 0
removed.

## 1. Placement rules (enforced on NEW files)

| Location | Rule |
|---|---|
| repository root | no code files (`.py .sh .mjs .js .ps1 .bat .rs .ipynb`) |
| `scripts/` root | only the operator entry points listed in `scripts/README.md` (the allowlist in `check_script_placement.py` mirrors that table; change both in one commit) |
| `scripts/<family>/` | family must be one of: `archive data demo_broker experiments gui_testbed portable_linux portable_socsci repo_tools reproduce seismic_testbed tests`. A new family = a README row + the allowlist, same commit |
| `source/` | root holds only the two servers; code goes in `source/lib/` (or `source/lib/thinclient/`), tests in `source/tests/` |
| `spike/` | code lives in `spike/<track>/`; the root keeps README, CLAUDE.md, patches |
| `scripts/archive/`, `spike/archive/` | anything added there carries a `CLOSED`/`SUPERSEDED` banner in its first 20 lines (closed-tracks policy) |

Files that existed at the restore tag are grandfathered for the lifecycle rule
below (the checker reads the tag's tree; `SFU_PLACEMENT_BASELINE_REF` overrides).
Placement rules apply to every file, and today's tree passes them.

## 2. Lifecycle header (required on every NEW `scripts/**/*.py`, except `tests/ archive/ data/`)

The module docstring's first 20 lines carry one of:

```
Lifecycle: operator      scripts/ root only — an entry point an operator runs by hand (listed in scripts/README.md)
Lifecycle: library       imported by other code; no results of its own
Lifecycle: tool          a maintenance/deploy command run by hand inside a family (not an eval); MUST carry  Doc: docs/<its doc>
Lifecycle: harness       re-runnable eval/benchmark; MUST also carry  Doc: docs/<the doc that cites it>
Lifecycle: one-off       ran once for one measurement; allowed ONLY under scripts/experiments/, and MUST carry
                         Results: data/eval_results/<file>   and   Doc: docs/<doc that records the outcome>
```

The point of `one-off`: the repository's efficacy rule requires the eval script path to
be recorded, so a measurement script is evidence and stays, but it must say
where its numbers went. Anything that cannot name a results file and a doc is
scratch work and belongs in the session scratchpad, never in the tree.

## 3. Substantial-change gate (restore tag + tests before commit)

A staged commit is **substantial** when any holds: ≥ 10 files
(`SFU_PREFLIGHT_MIN_FILES`), ≥ 500 lines added+deleted
(`SFU_PREFLIGHT_MIN_LINES`), or any delete/rename of a code file under
`source/ scripts/ spike/ web/`. A substantial commit is allowed only when
`.claude/.preflight_stamp.json` (gitignored) records a passing

```
.venv/bin/python3 scripts/repo_tools/preflight.py run --slug <short-name>
```

over exactly the staged tree (`git write-tree`; staging anything afterwards
invalidates the stamp). `run` does, in order:

1. **Restore tag.** Reuse a `pre-*` tag that is an ancestor of HEAD and either
   points at HEAD or is < 24 h old; otherwise create `pre-<slug>-<YYYY-MM-DD>`
   at HEAD and push it (push failure is reported, not fatal).
2. **Tests.** `SFU_PREFLIGHT_TESTS` or the default fast set:
   `scripts/tests/test_script_placement.py`, `scripts/tests/test_doc_status.py`,
   `source/tests/` (669 tests). The `scripts/tests/` half is not in the default
   because collecting it alone takes ~80 s and the `test_delta_*` files hit the
   3 GB RSS guard when run in one process (`REPO_REORG_2026-10-10.md` §5);
   run it per file when the change touches `scripts/`.
3. **Function inventory.** `symbol_inventory.py diff --base <tag>`: every
   `def`/`class` in `source/ scripts/ spike/ web/`, keyed `basename::qualname`, so
   `git mv` keeps symbols. Removal of a symbol under `source/`, `web/`, or a
   non-evidence `scripts/` family FAILS unless the run is given
   `--accept-removals <record.json>` (or `SFU_PREFLIGHT_ACCEPT`), a triage
   record whose `removed_symbols` list names every key being removed, built
   from the audited ledgers; accepted keys are stamped as
   `accepted_removals`, so a function
   can only leave a protected scope through a ledger row. Removals under
   `scripts/experiments/`, `scripts/seismic_testbed/`, `scripts/archive/`,
   `spike/` are listed for the ledger. Gotcha: renaming a FILE to a different
   basename shows as removal + addition; keep basenames on moves, or record
   the rename in the ledger and re-run with the move staged.
4. **Stamp.** Writes tree hash, tag, test tail, inventory result, `ok`.

Destructive shell commands (`git reset --hard`, `git checkout -- .`,
`git clean -f`, `git push --force`, `git branch -D`, `git rm -r`, `rm -r*`
outside `/tmp` and the scratchpad) need only step 1: a fresh restore tag that
is an ancestor of HEAD.

## 4. Where the rules run (three layers, one checker each)

| Layer | File | Fires on |
|---|---|---|
| git pre-commit (tracked copy; install with `scripts/repo_tools/install_git_hooks.sh`) | `scripts/repo_tools/hooks/pre-commit` | big-file guard, gitleaks, placement on ADDED files, substantial-change gate. One-time overrides: `ALLOW_BIG=1 SKIP_GITLEAKS=1 SKIP_PLACEMENT=1 SKIP_PREFLIGHT=1` |
| Claude Code PreToolUse `Write|Edit` | `.claude/hooks/script_placement_guard.sh` | denies creating a file that breaks §1/§2, with the reason and the fix |
| Claude Code PreToolUse `Bash` | `.claude/hooks/substantial_change_gate.sh` | denies `git commit` without a valid preflight when the change is substantial, and destructive commands without a fresh tag; the denial names the exact command to run |
| pytest | `scripts/tests/test_script_placement.py` | whole tracked tree passes §1 and post-baseline files pass §2; the checker still rejects the forbidden shapes |

Git hooks are not versioned by git itself, so a fresh clone must run
`install_git_hooks.sh` once (`CONTRIBUTING.md`); the pytest layer is the backstop
for a clone that did not.

## 5. Triage method (2026-10-11 wave; the ledger has the per-file rows)

Every file under `scripts/` is read and classified from evidence, not names:
git first-add date and commit count; references across `source/ scripts/ spike/
web/ docs/ deploy/ .claude/ pytest.ini` plus supervisor/systemd units and
`scripts/README.md`; whether its results file exists under `data/eval_results/`
and is cited by a doc; whether the operator entry points call it.

| Class | Meaning | Action |
|---|---|---|
| ACTIVE | on a serving/build/deploy path, or a live test | stays; gets no header retro-fit (grandfathered) |
| HARNESS (cited) | re-runnable eval whose doc/results exist | stays in `experiments/` or `seismic_testbed/`; never deleted (pre-registered bars live in source at pinned commits) |
| ONE-OFF (recorded) | ran once; results + doc exist; zero references | stays in `experiments/` as evidence (policy: evidence is never deleted) |
| MISPLACED | lives in the wrong family or at a root | `git mv` to the right family, references repointed, same commit |
| DEAD | zero references, no results file, no doc, track closed | `git mv` to `scripts/archive/<track>/` with a CLOSED banner; **deleted only** when all of: zero references, no recorded results, not named by any doc, not an operator entry point, listed in the ledger with its last commit hash. An `archive/` file is evidence only if some doc or results file points at it; one that meets all five conditions (2026-10-11: two OpenSearch-era Azure indexer wrappers calling a `splade_indexer.py` that no longer exists) is clutter and is deleted the same way, git history being the record |

Deletions and moves are applied per class in separate commits, each through
the §3 gate, so any one can be reverted alone. Audit of the result is a Fable
task (owner instruction 2026-10-11): re-run the reference search for every
moved/deleted row, re-run the function inventory, run the tests. The
reference re-derivation is mechanical: `scripts/repo_tools/triage_audit.py`
reads a wave's ledger tables (`--ledger-dir`), re-runs `git grep` for
every DEAD and MISPLACED row, checks the recorded last-commit hash, the
`data/eval_results/INDEX.md` mention and the root allowlist, and fails on any
DEAD row that does not meet all five conditions (results JSON under
`data/eval_results/script_triage_audit_<date>.json`).

## 6. Process sources consulted (2026-10-11)

No authoritative standard exists for script hygiene in a research repository; the
pattern below is what practitioners converge on, adapted to this repository's
closed-tracks and efficacy rules.

- Check usage before removal, archive before delete, verify with tests; git
  history is the real archive, a visible `archive/` directory is for things people
  will want to find ([repo-cleanup skill](https://skills.sh/vamseeachanta/workspace-hub/repo-cleanup);
  CPython's 2022 review of `Tools/scripts/`, which found 74 stale scripts and
  moved the build-needed ones instead of deleting them —
  [discuss.python.org](https://discuss.python.org/t/remove-outdated-tools-scripts-scripts/19571/32),
  [LWN](https://lwn.net/Articles/910898)).
- Scratch → proven → permanent "graduation" for one-off scripts
  ([TEMP_GRADUATION](https://git.azcomputerguru.com/azcomputerguru/claudetools/raw/commit/151e974a9b031e9ea83d8ceefeb45ab3d76ce6bb/.claude/TEMP_GRADUATION.md)).
- Pre-commit structure enforcement is an old idea
  ([SVN::Hooks::CheckStructure](https://metacpan.org/pod/SVN::Hooks::CheckStructure))
  but git hooks are per-clone and unversioned
  ([Code::TidyAll::Git::Precommit](https://metacpan.org/pod/Code::TidyAll::Git::Precommit)),
  so this repository tracks the hook, ships an installer, and backs it with a test.
- For the Rust-core spike: port the hot leaf behind a PyO3 import with call
  sites unchanged, freeze Python outputs as golden fixtures first, include
  edge cases ([InfoQ, incremental FFI refactoring](https://infoq.com/presentations/rust-refactoring);
  [corrode.dev Python→Rust guide](https://corrode.dev/migration-guides/python-to-rust);
  [parity & goldens](https://codingest.readthedocs.io/en/latest/parity-and-goldens.html);
  [Rust-first testing](https://robin-sparkless.readthedocs.io/en/latest/RUST_FIRST_TESTING/)).

## 7. Dead-code guard and the codebase-wide wave (2026-10-11)

The 2026-10-11 codebase triage (`CODEBASE_TRIAGE_2026-10-11.md`; restore tag
`pre-codebase-triage-2026-10-11`, kept by the owner) extended §5 from
`scripts/` to `source/ web/ spike/ deploy/ .claude/` and the root files, at
symbol level and with aggressive rules: test-only product code and gates whose
rollback target no longer exists in this container are removal candidates,
not automatic keeps (the 2026-10-10 audit's "tests are the specification" stance is
superseded for product code; explicit pending owner decisions are not
touched). Two tools carry the wave and stay as gates:

- `scripts/repo_tools/triage_audit.py --ledger-dir <dir> --scope <prefixes>`
  now audits any wave's ledgers, FILE rows and SYMBOL rows (a `Symbol` column):
  a DEAD symbol must have no live and no test reference, a TEST-ONLY symbol no
  live reference, re-derived with `git grep -w`; hits inside `archive/`,
  `docs/deprecated/`, the ledgers and the audit reports never keep anything
  alive. Default arguments reproduce the §5 script audit unchanged
  (re-checked 2026-10-11: 400/400, 0 failures).
- `scripts/repo_tools/dead_code_guard.py` (backstop test
  `scripts/tests/test_dead_code_guard.py`): every def/class in `source/` product
  code and every `web/lib/*.js` export must be referenced from live code;
  TEST-ONLY and DEAD symbols fail unless `dead_code_allow.json` names them
  with a reason, and stale allowlist entries fail. Baseline before the wave:
  675 symbols, 16 TEST-ONLY + 2 DEAD (5 s). End state 2026-10-12: 619
  symbols, 0 unreferenced, 2 allowlisted web seams (`dead_code_allow.json`);
  the test keeps it green.
- `scripts/tests/test_env_gates_doc.py` (added 2026-10-12): every `SFU_*`
  name in a product string literal (`source/` outside `source/tests/`, the dynamic
  `SFU_FEATURE_<KEY>` names expanded from `load_config`) has a live row in
  `docs/ENV_GATES.md`; no struck-through (retired) name is read by product
  code; every live row has a reader in `source/ scripts/ spike/ web/` outside
  `archive/` and the test dirs.
