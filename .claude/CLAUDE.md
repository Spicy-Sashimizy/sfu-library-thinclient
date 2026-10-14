---
## MANDATORY: GIT WORKFLOW - READ THIS FIRST
---

**THIS IS NON-NEGOTIABLE. BEFORE DOING ANYTHING ELSE, FOLLOW THIS WORKFLOW.**

### BEFORE ANY Edit/Write Tool Call:
```
Step 1: Run `git pull` FIRST (or check if remote exists)
Step 2: Only THEN proceed with edits
```

### IMMEDIATELY AFTER Any Edit/Write Tool Call:
```
Step 3: Run `git add <the specific files you changed>`  — NEVER `git add .`
Step 4: Run `git commit -m "description"`
Step 5: Run `git push` (if remote configured)
```

### REQUIRED SEQUENCE (No Exceptions):
1. `git pull` -> 2. Edit file -> 3. `git add <files> && git commit && git push`

**STAGE EXPLICITLY — NEVER `git add .` / `git add -A`:**
This working tree always contains multi-GB runtime state (index artifacts,
spools, caches, checkpoints). Blanket staging writes every touched file into
git's object store even if the commit is later undone — measured 2026-06-11:
~47 GB of orphaned objects in .git from exactly this. Stage only the files
you actually edited; `git status --short` first if unsure.

**DO NOT:**
- Skip the pull step
- Use `git add .`, `git add -A`, or `git commit -a`
- Make multiple edits without committing
- Forget to push after committing
- Say "I'll commit later" - commit IMMEDIATELY

**IF NO REMOTE:** Still commit locally. Inform user no remote is configured.

**SUBSTANTIAL CHANGES (policy 2026-10-11, `docs/infrastructure/SCRIPT_HYGIENE_POLICY.md`):**
a commit of ≥10 files, ≥500 lines, or ANY delete/rename of code under
`source/ scripts/ spike/ web/` requires, after the final `git add` and before
`git commit`: `.venv/bin/python3 scripts/repo_tools/preflight.py run --slug <what>`
(creates/reuses a pushed restore tag `pre-<slug>-<date>`, runs the fast tests
and the function inventory against the tag, stamps the staged tree). The
pre-commit hook and the Bash gate refuse the commit otherwise. Destructive
git/rm commands need a fresh restore tag (`preflight.py tag --slug <what>`).
New scripts need a family directory + `Lifecycle:` docstring line (write guard).

Commit-message template (trailer = the actually-serving model):
```bash
git commit -m "$(cat <<'EOF'
Description of changes

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

Subtrees (shared code): pull subtree updates before starting (Dashboard →
Git → Subtrees → Pull); after modifying shared code, consider pushing back
to the source project.

---

## MANDATORY: Documentation Freshness & Efficacy Recording

**History: docs drifted from code and gave the user contradictory/stale answers.
These rules exist so that never happens again. They are as binding as the git
workflow above.**

### Source-of-truth hierarchy (use when docs conflict or when answering questions)

1. **The code is always right.** If a doc contradicts the code, the code wins —
   fix the doc in the same session you noticed the conflict.
2. `docs/README.md` is the **index** of all documentation. `docs/THIN_CLIENT_SWAP.md`
   is the **canonical current-architecture doc** ("start here").
3. Newer measured numbers supersede older ones. The superseded doc gets a dated
   status note pointing at the newer doc — never leave two live docs disagreeing
   silently.
4. Anything in `docs/archive/` (historical) or `docs/deprecated/` (OpenSearch-era,
   obsolete for this container) is NOT current — never answer user questions from
   those without saying so.

### Same-commit doc rule

A commit that changes any of the following MUST update the affected doc **in the
same commit** (not "later", not next session):

| Change | Doc that must be updated |
|---|---|
| Architecture, engines, index layout, serving path, env-var gates, MCP tools | `docs/THIN_CLIENT_SWAP.md` |
| Storage/size numbers, compression levers, quantization parameters | `docs/STORAGE_BUDGET_150M.md` (and the research doc that measured it) |
| New/moved/deleted doc | `docs/README.md` index |
| Defaults changed in code (for example, QUANT_SCALE, bsize, alpha/beta) | every doc + docstring that states the old value — `grep -rn '<old value>' docs/ source/ scripts/` before committing |

### New-module efficacy rule

A new module, lever, or feature is **not done** until its measured efficacy is
recorded in the appropriate doc:

- WHAT was measured (metric + dataset/corpus size), the NUMBERS (before → after),
  the eval script path, the results-file path under `data/eval_results/`, and the
  absolute date.
- "Should improve X" without numbers is forbidden in docs. Unmeasured claims must
  be explicitly marked `*est.*` or "unmeasured / design only".
- If a module ships before its eval, the doc entry must say "IMPLEMENTED,
  EFFICACY UNMEASURED" so stale optimism can't masquerade as a result.

### Session-end doc sync (major pushes)

Before ending any session that pushed multiple feature/research commits:

1. Re-read `docs/THIN_CLIENT_SWAP.md` and `docs/README.md` against what was
   actually built this session; update anything the session made stale.
2. Move superseded docs to `archive/` or `deprecated/` **with a dated
   `> **SUPERSEDED**` banner** at the top explaining what replaced them, and
   repoint every reference (`grep -rln '<filename>' docs/ source/ scripts/`).
3. Use absolute dates only (for example, 2026-06-11), never "today"/"recently".
4. Commit the doc sync (it may be its own commit at session end, but it ships
   in the same push as the work it documents).

### Freshness check when answering the user from docs

Before quoting a doc, compare its last-modified date (`git log -1 --format=%ci
-- <doc>`) against recent code commits touching the same subsystem. If code
moved after the doc, verify the claim in code first — and fix the doc.

---

## MANDATORY: Virtual Environment (venv)

**The MCP server runs using the project venv, NOT the system Python.**

- Venv path: `/workspaces/sfu-library-thinclient/.venv/bin/python3`
- The MCP server is launched via Docker exec using this venv
- **ALL package installs MUST target the venv:**
  ```bash
  # Correct — installs into the venv
  sudo /workspaces/sfu-library-thinclient/.venv/bin/python3 -m pip install <package>

  # WRONG — installs into system Python, MCP server won't see it
  pip install <package>
  pip3 install <package>
  ```
- **After installing new packages:** The MCP server process must be restarted
  (restart Claude Desktop or close/reopen conversation). Verify:
  `.venv/bin/python3 -c "import <package>; print('OK')"`
- The venv is owned by root, so `sudo` is required for pip installs

---

## MANDATORY: Closed tracks (policy 2026-09-25)

**History: on 2026-09-25 a superseded spike (`qdrant_uint8_sparse`, moot since
SEISMIC's 2026-07-06 promotion) was dispatched as pending work because its
index row still read "SCAFFOLD, UNMEASURED". These rules exist so a closed
track can never be mistaken for open work again.**

- Every `.md` under `docs/` outside `archive/` and `deprecated/` carries a
  `**Status:**` line within its first 8 lines, from this vocabulary only:
  `ACTIVE`, `DEFERRED <date> (<by whom/why>)`, or
  `CLOSED <MEASURED|SUPERSEDED|DEAD|KILLED> <date>`.
  `scripts/tests/test_doc_status.py` enforces this and fails the suite when a
  CLOSED doc sits outside `archive/`/`deprecated/` or when an Active row of
  `docs/README.md` names a closed track.
- The moment a decision closes a track (engine promoted, host lost, verdict
  KILL/DROP, design abandoned), the SAME commit: (1) banners every doc of the
  losing track `> **CLOSED <kind> <date>** — <what replaced it>`; (2) moves it
  to `docs/archive/<track>/` (research record) or `docs/deprecated/` (obsolete
  infra); (3) repoints every reference (`grep -rln '<path>' docs/ source/
  scripts/ spike/ web/`); (4) moves its `docs/README.md` row from an Active
  table to the "Closed tracks" table; (5) moves its code to `scripts/archive/`
  or `spike/archive/` unless a live serving path imports it (state which).
- Pending-work triage reads ONLY the Active tables of `docs/README.md`.
  Anything in a Closed-tracks table, in `archive/`/`deprecated/`, or carrying a
  CLOSED status is never pending, never dispatched to an agent, and never
  quoted as current without saying so.
- Before dispatching any agent on a doc-listed item, verify in
  `docs/THIN_CLIENT_SWAP.md` §"What runs here now" that the item's premise
  (which engine, which host, which gate) is still live.

## No internal code comments (policy 2026-09-01)

Product/ops code carries no `#`/`//` comments — constraints live in the docs
tree (`docs/CODE_INVARIANTS.md`, `docs/CODE_INVARIANTS_SCRIPTS.md`,
`docs/ENV_GATES.md`, `docs/EXTERNAL_API_CONTRACT.md`). When writing code,
record any new constraint there, not inline. Docstrings stay. EXEMPT (keep
their comments): `spike/`, `scripts/seismic_testbed/`,
`scripts/experiments/`, `scripts/archive/` (evidence harnesses —
pre-registered bars live in source at pinned commits), `**/vendor/`
(licenses), and config-as-interface files (`*.env`, `*.example.env`,
`*.service`, supervisor `*.conf`, `*.ps1`, `*.bat`, compose YAML,
requirements pins).

## Code search: Pommel MCP tools FIRST

Semantic/intent search (architecture, "how does X work", related code):
- `mcp__pommel__pommel_search_local` — current project (FASTEST; Explore
  agents start here)
- `mcp__pommel__pommel_search_project` / `_search_all` / `_list_projects` /
  `_reindex` (after major changes)

Grep/Glob only for: exact strings, simple patterns, filename searches.
HTTP fallback + the cross-container port map (when MCP unavailable):
`docs/infrastructure/POMMEL_ACCESS.md` (local, untracked since 2026-10-10).

---

## Repo navigation (scoped context)

- Human map: root `README.md`. Doc index: `docs/README.md`.
- Directory-scoped CLAUDE.md files carry local rules and load automatically
  when working there: `source/lib/thinclient/`, `data/`, `scripts/`, `web/`,
  `spike/`.
- `data/seismic_150m/` is IRREPLACEABLE and READ-ONLY, always.
- Repository git facts: user `ClaudeBox (claudebox@local)`; default branch
  `sfu-library-thinclient` (do NOT create or rename to `main`); origin =
  github.com/Spicy-Sashimizy/sfu-library-thinclient.
