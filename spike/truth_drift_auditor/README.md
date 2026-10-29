# truth_drift_auditor — tiered "base of truth" drift auditor (pilot spike)

**Status:** ACTIVE — scaffold IMPLEMENTED 2026-10-29, EFFICACY UNMEASURED
(offline fake-model harness passes; no run against real models, PaperQA2, Zotero
or a Google Doc yet). Out of scope for the SFU library thin client: this
directory is **self-contained and is meant to be moved** to its own project
(see §8). Nothing in it imports from or writes to the thin client; the only
link is an optional HTTP call to its search endpoint, off by default.

## 1. What this is

A writing-time auditor. While someone drafts technical or research prose (first
in exported files, later live in a Google Doc), every changed paragraph is
checked against two bases of truth:

- a **factual corpus** — a Zotero library and/or a literature review, retrieved
  with PaperQA2 (or the built-in local text scorer), optionally backed by the
  thin client's 150M-work scholarly search;
- a **numerical metrics store** — measured-results JSON (here: six copied
  thin-client `eval_results` files) addressed by dotted path.

Checks run cheapest-first: deterministic code, then Claude Haiku 5.5 through
the SDK for per-claim verdicts, then (only on escalation) a headless Claude
Code session with tools and Claude Fable 5.1 for a whole-document review. The
output is per-paragraph verdicts — `SUPPORTED`, `CONTRADICTED`,
`NO_EVIDENCE`, `NOT_CHECKABLE` — plus numeric mismatches, and optionally a
comment posted back to the Google Doc.

Research that led here (connector behaviour, comparable products, OSS
replacements for Loki and Pituitary, maintenance checks) is in
`docs/01_RESEARCH_2026-10-29.md`. Design decisions are in
`docs/02_ARCHITECTURE.md`. How to call the thin client, if you want its
corpus as evidence, is in `docs/03_THIN_CLIENT_INTERFACE.md`. The pilot order
and what to record is in `docs/04_PILOT_PLAN.md`.

## 2. Layout

```
truth_drift_auditor/            Python package (no thin-client imports)
  config.py                     TOML config + env secrets
  models.py                     Paragraph / Evidence / ClaimVerdict / ParagraphReport
  metrics_store.py              flatten *.json -> "<file>:<dotted.path>" = number
  numeric_check.py              DETERMINISTIC: numbers in prose vs metrics via aliases
  vale_runner.py                DETERMINISTIC: Vale prose linter (if installed)
  evidence/local_text.py        dependency-free retriever over .md/.txt (lit review)
  evidence/paperqa.py           PaperQA2 manual mode over PDFs + Zotero (UNTESTED here)
  evidence/thinclient.py        POST /api/search on the thin client (optional leg)
  tier1_haiku.py                Haiku 5.5 via SDK, structured verdicts, cached system prompt
  tier2_claude_code.py          headless `claude -p` escalation reviewer
  pipeline.py                   Auditor: deterministic -> evidence -> tier1 -> policy -> tier2
  docs_watcher.py               Google Docs poller + Drive comments
  cli.py                        probe-coverage | batch | watch | metrics | eval
eval/score.py, eval/judged_set.example.jsonl   precision/recall harness
fixtures/metrics/*.json + MANIFEST.md          copied measured results (base of truth, numbers)
fixtures/corpus/sample_litreview.md            sample text corpus (base of truth, facts)
fixtures/drafts/sample_draft.md                sample draft with planted drift
tests/                                         14 offline tests, no network, no keys
scripts/setup.sh, scripts/run_offline_demo.sh
config.example.toml, .env.example, requirements.txt, pyproject.toml
```

## 3. Quick start (fresh container)

```bash
scripts/setup.sh                 # venv, pip install -e ".[dev,google]", copies config + .env
scripts/run_offline_demo.sh      # no keys needed: metrics, coverage probe, batch, eval
python -m pytest -q tests
```

Then edit `config.toml` and `.env`:

```bash
export ANTHROPIC_API_KEY=...
python -m truth_drift_auditor.cli batch --draft path/to/export.md             # real Haiku tier 1
python -m truth_drift_auditor.cli batch --draft path/to/export.md --tier2     # + Claude Code escalation
python -m truth_drift_auditor.cli watch --doc-id <GOOGLE_DOC_ID> --post-comments
```

Optional heavy leg: `pip install -e ".[paperqa]"`, set
`[corpus.paperqa] enabled = true`, drop PDFs in `corpus_pdfs/`, and for Zotero
set `ZOTERO_USER_ID` / `ZOTERO_API_KEY` and `zotero = true`.

## 4. What runs before any model is called

In order, all deterministic, all local, all free:

1. **Change detection.** Paragraph text is hashed; only changed paragraphs proceed.
2. **Numeric check** (`numeric_check.py`). Numbers with units are extracted
   from each sentence. If the sentence matches a configured alias phrase, the
   number attached to that phrase is compared with the measured value at the
   alias' metrics path, within a per-alias tolerance. Output: exact
   mismatch with the expected value and the source path.
3. **Vale** (`vale_runner.py`), if installed: terminology, units, numeral style
   from your YAML rules.
4. **Evidence retrieval.** The local text scorer (pure Python token overlap),
   PaperQA2 with `evidence_skip_summary` (keyword or local-embedding ranking;
   an embedding model is ML, not an LLM, and `sparse` uses none), and the thin
   client's search endpoint. Chained: corpus first, thin client as fallback.
5. **Packaging.** Evidence passages plus the numeric notes become the one user
   message tier 1 receives.

Only then: tier 1 (Haiku, one call per paragraph). After it, the **escalation
policy** is deterministic code again (low-confidence contradiction, N
contradicted paragraphs in a window, optional numeric mismatch), and only a
positive decision starts tier 2.

## 5. Running against real models

- Tier 1 uses `claude-haiku-5-5`, effort `low`, a cache-controlled static
  system prompt, and `output_config.format` JSON-schema output with a fallback
  path for older SDKs. A refusal stop reason yields no verdicts, never a crash.
- Tier 2 shells out to `claude -p --output-format json --model claude-fable-5-1
  --max-turns N [--mcp-config ...] [--allowedTools ...]` (flags checked against
  Claude Code 2.1.312). Run it on an API key, not a consumer login.
- Cost sketch for tier 1 (estimate, unmeasured): ~3k input + ~300 output
  tokens per changed paragraph ≈ $0.0005; at one changed paragraph every 30 s
  ≈ $0.06 per writing hour.

## 6. Verdict semantics (read before trusting output)

`NO_EVIDENCE` is deliberately separate from `SUPPORTED`. On topics the corpus
covers thinly, most claims are "not contradicted" only because nothing speaks
to them. The tool never promotes that to support. Decide in the pilot what the
UI does with `NO_EVIDENCE` (docs/04_PILOT_PLAN.md).

The offline `FakeVerdictClient` is a plumbing stand-in: it cannot see meaning
drift (sample draft paragraph 3 is a planted example it misses by design).

## 7. Measured so far

| What | Where | Result (2026-10-29) |
|---|---|---|
| Offline tests | `tests/` | 14 pass (thin-client venv Python 3.11, no network) |
| Offline judged set, fake tier 1 | `eval/judged_set.example.jsonl` (8 rows) | precision 1.0, recall 0.667, F1 0.8 — the miss is the meaning-drift row the fake client cannot detect |
| Real Haiku / Fable / PaperQA2 / Zotero / Google Docs | — | **not run** |

Record every real run with `tda eval --out reports/<date>.json` and add a row.

## 8. Moving this out of the thin-client repo

The directory is the unit. To relocate:

```bash
cp -r spike/truth_drift_auditor /path/to/new-project/      # or git mv in the old repo + a tag first
cd /path/to/new-project/truth_drift_auditor && scripts/setup.sh
```

Nothing resolves relative to the thin-client root: config paths are relative
to `config.toml`, tests use their own `conftest.py`, fixtures are copies.
If you later remove the directory from the thin-client repo, that repo's
hygiene policy requires a restore tag first
(`.venv/bin/python3 scripts/repo_tools/preflight.py tag --slug <name>` there).

## 9. Known gaps

- `evidence/paperqa.py` and `docs_watcher.py` are written against documented
  APIs but have not executed here (packages not installed in this container).
- Google Docs comments are unanchored (anchor format is undocumented); the
  quoted paragraph text is attached so the comment card shows context.
- No Vale rule set ships; `vale.config` is a hook for yours.
- The thin-client leg assumes the response shape read on 2026-10-29
  (`docs/03_THIN_CLIENT_INTERFACE.md`); re-check if that project changes.
