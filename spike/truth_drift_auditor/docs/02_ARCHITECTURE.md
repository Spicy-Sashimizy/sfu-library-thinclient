# Architecture

**Status:** ACTIVE (design + scaffold; efficacy unmeasured)

## 1. Tiers

```
 changed paragraph
      │
      ▼
 ┌──────────────────────────────────────────────────────────┐
 │ TIER 0 — deterministic, local, free                      │
 │  hash diff → numeric_check (aliases → metrics store)     │
 │  → Vale rules → evidence retrieval (local text /         │
 │    PaperQA2 sparse|dense, skip_summary / thin client)    │
 └──────────────────────────────┬───────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────┐
 │ TIER 1 — Claude Haiku 5.5 via Anthropic SDK              │
 │  one call: paragraph + evidence + numeric notes          │
 │  → per-claim {quote, verdict, evidence_ids, confidence}  │
 │  effort=low, static cached system prompt, JSON schema    │
 └──────────────────────────────┬───────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────┐
 │ ESCALATION POLICY — deterministic                        │
 │  low-confidence CONTRADICTED | ≥N contradicted in window │
 │  | (opt) numeric mismatch | model's own escalate flag    │
 └──────────────────────────────┬───────────────────────────┘
                                ▼ (only when triggered)
 ┌──────────────────────────────────────────────────────────┐
 │ TIER 2 — headless Claude Code, Claude Fable 5.1, tools   │
 │  claude -p --output-format json --model ... --mcp-config │
 │  re-verifies, looks for structural/meaning drift,        │
 │  writes ONE consolidated comment                         │
 └──────────────────────────────────────────────────────────┘
```

## 2. What is deterministic and what is not

| Stage | Mechanism | Model? |
|---|---|---|
| change detection | SHA-1 of paragraph text | no |
| numeric check | regex number+unit extraction; alias phrase (substring/regex) → metrics path; nearest-number-to-phrase; relative tolerance | no |
| Vale | YAML rules, subprocess, JSON alerts | no |
| local text retriever | token overlap with IDF weighting over blank-line chunks | no |
| PaperQA2 retriever | chunk + `sparse` keyword embedding (no model) or local sentence-transformers (ML embedding, not an LLM); `evidence_skip_summary=True` disables the per-chunk LLM summary | no LLM when `skip_summary=true` and embedding is `sparse`/local |
| thin client retriever | HTTP to BM25F + SPLADE/SEISMIC + RRF fusion; the thin client's own optional cross-encoder rerank is ML, not an LLM | no LLM |
| tier 1 | Haiku 5.5 | **yes** |
| escalation policy | thresholds in `EscalationPolicy` | no |
| tier 2 | Claude Code + Fable 5.1 | **yes** |

Answer to "is it just local RAG over Zotero plus the quant store?": the
deterministic layer is (a) the numeric comparison against the metrics store
(a flattened JSON lookup today; SQLite would be a drop-in), (b) Vale, and (c)
retrieval from up to three legs — your Zotero/lit-review corpus, and
optionally the thin client's scholarly index. Retrieval produces passages, not
verdicts. The first verdict on a non-numeric claim is tier 1's.

## 3. Verdict semantics

`SUPPORTED` / `CONTRADICTED` / `NO_EVIDENCE` / `NOT_CHECKABLE`. "Not
contradicted" is never treated as support. `NO_EVIDENCE` is expected to
dominate on thin topics; its UI handling is a pilot decision. Numeric
mismatches are reported separately from claim verdicts and are exact.

## 4. Why the SDK for tier 1 and Claude Code for tier 2

Headless Claude Code spawns a process, loads a harness prompt, tool
definitions, CLAUDE.md and MCP servers per invocation: seconds of latency and
thousands of billed tokens before the paragraph is seen, and a tool surface the
fast path should not have. The SDK call is ~40 lines, cacheable and tool-less.
Tier 2 is the opposite case: it benefits from tools (PaperQA2, Vale, the
metrics store, the thin client search) and a stronger model, and runs rarely.
If a single runtime is insisted on, the Claude Agent SDK with a persistent
session is the compromise (startup paid once, harness tokens still paid).

## 5. Cost sketch (estimate, unmeasured)

| Item | Value |
|---|---|
| tier 1 input per paragraph | ~3,000 tokens (evidence dominates) |
| tier 1 output | ~300 tokens |
| tier 1 cost per paragraph (Haiku 5.5 rates) | ~$0.0005 |
| per writing hour at 1 changed paragraph / 30 s | ~$0.06 |
| tier 2 | minutes and dollars per run; keep it rare |

## 6. Google Docs loop

Poll `documents.get` (quota 300/min/user; we use 3–5 s), flatten paragraphs
with `startIndex`/`endIndex`, hash, audit changed ones, post findings with
Drive `comments.create` including `quotedFileContent`. Anchored comments use an
undocumented anchor format and are not attempted; Suggesting-mode edits are
impossible through the API.

## 7. Dependencies by stage

| Stage | Required | Optional |
|---|---|---|
| tier 0 | Python 3.11 stdlib | Vale binary; `paper-qa[zotero,local]` |
| tier 1 | `anthropic` | — |
| tier 2 | `claude` CLI on PATH, API key | MCP config for tools |
| watcher | `google-api-python-client`, `google-auth-oauthlib`, OAuth client | — |

## 8. Latency sketch per changed paragraph (estimates, unmeasured)

| Stage | Where | Est. latency |
|---|---|---|
| hash diff | local | microseconds |
| numeric check | local | < 1 ms |
| Vale | local subprocess | 50–200 ms |
| local text retriever | local, pure Python | 1–10 ms |
| PaperQA2 `sparse`, `skip_summary` | local | tens of ms |
| PaperQA2 local sentence-transformer, `skip_summary` | local CPU | 20–80 ms per query after a one-time model load of a few seconds |
| PaperQA2 default per-chunk LLM summary | API | seconds — the reason `skip_summary` defaults on |
| thin-client search leg | HTTP | that project records warm `/api/search` p50 ≈ 10 s; keep this leg out of the live loop (batch / tier 2 only) |
| tier 1 Haiku 5.5, effort low | API | ~1–3 s |
| tier 2 Claude Code + Fable 5.1 | API + tools | 30 s to minutes |
| Docs poll + reported sync lag | Google | 3–5 s + 1–3 s |

Embedding retrieval is one to two orders of magnitude faster than an LLM call,
but it is not a judgment: it returns the most similar passages and says nothing
about agreement. The only pre-LLM *judgment* is the numeric comparison. A
sub-second claim-level pre-judgment would be an encoder such as LettuceDetect
(~100–500 ms CPU), deliberately left out of the pilot until a judged set exists
to calibrate it. Expected writer-visible latency with the thin-client leg off:
a comment ~5–10 s after typing stops, dominated by the poll interval and tier 1.

## 9. Decision tree (every branch as implemented in `pipeline.py` / `docs_watcher.py`)

```
                 Google Doc  (poll documents.get every 3-5 s)   |   exported .md/.txt (batch)
                                   |                                        |
                                   +-------------------+--------------------+
                                                       v
                                      split into paragraphs; sha1(text) each
                                                       |
                                              hash seen before?
                                             /                  \
                                          yes                    no
                                           |                      |
                                         [skip]                   v
                                   ================= TIER 0: deterministic =================
                                   | 0a numeric_check                                      |
                                   |    extract numbers+units per sentence                 |
                                   |    alias phrase matches the sentence?                 |
                                   |      no  -> numeric = []                              |
                                   |      yes -> number nearest the phrase                 |
                                   |             |written-expected| / |expected| <= tol ?  |
                                   |               yes -> OK note                           |
                                   |               no  -> MISMATCH note (expected, path)    |
                                   | 0b Vale installed?                                    |
                                   |      no  -> skipped                                   |
                                   |      yes -> YAML rule alerts                          |
                                   | 0c evidence retrieval (chained)                       |
                                   |    leg 1: local text  /  PaperQA2 (sparse or local    |
                                   |           embedding, skip_summary => no LLM)          |
                                   |      hits >= min_hits -> stop                         |
                                   |      hits <  min_hits -> thin client enabled?         |
                                   |                            no  -> evidence as is      |
                                   |                            yes -> POST /api/search    |
                                   | 0d package: evidence + numeric notes + paragraph      |
                                   =========================================================
                                                       |
                                   ---------------- first model call ----------------------
                                   | TIER 1  Haiku 5.5 via SDK, effort low, cached system |
                                   |         prompt, JSON-schema output                   |
                                   |   stop_reason refusal / unparseable                  |
                                   |      -> claims = [], error recorded                  |
                                   |   ok -> per claim: verdict in {SUPPORTED,            |
                                   |         CONTRADICTED, NO_EVIDENCE, NOT_CHECKABLE},   |
                                   |         quote located by str.find -> span            |
                                   --------------------------------------------------------
                                                       |
                                   ============ escalation policy: deterministic ===========
                                   | any CONTRADICTED with confidence < low_confidence ? --+
                                   | >= min_contradicted paragraphs in last `window` ? ----+
                                   | numeric MISMATCH and numeric_mismatch_escalates ? ----+--> any yes
                                   | model returned escalate = true ? ---------------------+      |
                                   =========================================================      |
                                           | all no                                               v
                                           |                               ------------------------------------------
                                           |                               | TIER 2  claude -p --output-format json |
                                           |                               |   --model claude-fable-5-1, MCP tools  |
                                           |                               |   re-verify, structural drift,         |
                                           |                               |   ONE consolidated comment             |
                                           |                               |   (CLI missing -> "[tier2 skipped]")   |
                                           |                               ------------------------------------------
                                           +---------------------------+------------+
                                                                       v
                                            drifted? = any numeric MISMATCH or any CONTRADICTED
                                                     /                            \
                                                   no                              yes
                                                    |                               |
                                           mark hash seen;              --post-comments on?
                                           print report (batch)          /              \
                                                                       no                yes
                                                                        |                 |
                                                                print JSON report   Drive comments.create
                                                                                    (unanchored, quotedFileContent)
                                                                                    mark hash seen
```

`NO_EVIDENCE` and `NOT_CHECKABLE` never count as drift and never post a comment.
