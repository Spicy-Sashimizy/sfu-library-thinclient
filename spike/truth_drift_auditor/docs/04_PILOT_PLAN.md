# Pilot plan

**Status:** ACTIVE (pre-registered order; nothing run against real models yet)

The pilot runs on topics the components were not tuned for. Most of the stack
is topic-neutral; two parts are not (check-worthiness by genre, and any
encoder classifier — which is why LettuceDetect was dropped), and one
assumption is dangerous ("not contradicted" ≠ supported). Hence this order.

## Step 1 — coverage probe (retrieval only, no model, minutes)

```bash
python -m truth_drift_auditor.cli probe-coverage --draft <20 real paragraphs>.md --min-score 1.0
```

Read what comes back. If most paragraphs retrieve nothing relevant, the
problem is the corpus, not the pipeline. Record: coverage fraction, and which
topics are uncovered. Decision gate: proceed only if coverage ≥ 0.6 on the
pilot topics, else grow the corpus (Zotero collection, lit review) first.

## Step 2 — judged set and calibration (one afternoon)

Build `eval/judged_set.jsonl` with 50–100 paragraphs in the pilot topics,
labelled `drifted` or `ok`, each with a note saying *why*. Include: correct
numbers, wrong numbers, meaning drift with correct numbers, opinions/plans
(must not be flagged), and claims the corpus does not cover (`NO_EVIDENCE`
expected). Then:

```bash
python -m truth_drift_auditor.cli eval --judged eval/judged_set.jsonl --out reports/eval_<date>.json
```

Record precision/recall/F1 and the per-row confusion. Tune:
`[escalation] low_confidence`, alias tolerances, the tier-1 system prompt's
check-worthiness paragraph for the genre. Gate: precision ≥ 0.8 on `drifted`
before any writer sees output (a nagging tool gets switched off).

## Step 3 — batch mode on exported documents

```bash
python -m truth_drift_auditor.cli batch --draft export.md --out reports/batch_<date>.jsonl
python -m truth_drift_auditor.cli batch --draft export.md --tier2        # escalation on
```

Same pipeline as the watcher without polling or comment plumbing. Ask the
writer to rate each flagged item useful / not. Record tier-1 token usage from
the report (`tier1_usage`) to replace the cost estimate with a measurement.

## Step 4 — watcher, last

```bash
python -m truth_drift_auditor.cli watch --doc-id <id>                 # print only
python -m truth_drift_auditor.cli watch --doc-id <id> --post-comments # comments on drift
```

Only once batch verdicts are worth reading. Measure: poll-to-comment latency,
comments per hour, writer acceptance.

## What to record (every real run)

| Field | Where |
|---|---|
| date (absolute), config hash, model ids, corpus description and size | `reports/<date>.json` header |
| coverage fraction (step 1) | report |
| precision / recall / F1 / confusion (step 2) | `eval --out` |
| tier-1 tokens and cost per paragraph; tier-2 invocations | report `tier1_usage`, tier-2 count |
| writer acceptance of flags (steps 3–4) | report |

Then update README §7 "Measured so far". No efficacy claim without a dated
results file.

## Pilot decisions to make explicitly

1. What the UI does with `NO_EVIDENCE` (silent, soft marker, or listed).
2. Whether numeric mismatches escalate to tier 2 (`numeric_mismatch_escalates`).
3. Whether the thin-client leg is on (adds coverage; adds "wider literature"
   verdicts that may disagree with the curated corpus — keep them labelled by
   `source`).
