#!/usr/bin/env python3
"""Trace evidence for levers #5 (session prefetch) and #6 (partial result +
continuation handle) of docs/SPECULATIVE_RETRIEVAL_UPGRADES.md.

Three questions, each answered from what is on disk or in code, never estimated:

Q1  Within a session, how often does a get_paper_summary / get_references /
    get_full_text_link call name a document that was in the previous search's
    top-10?  Needs a trace line per tool call carrying (session, tool, doc id)
    and the preceding search's top-10 ids.
Q2  How often does a session run a second search within a short window, and
    how does its result set overlap the first (Jaccard of result ids)?
Q3  Does the in-process works cache that tools._cache_works fills after a
    search already serve the follow-up tools for those ids?  Answered by
    static inspection (ast) of src/lib/tools.py: which cache/remote calls
    each follow-up handler makes.

Trace sources inventoried (every one found in the repo on 2026-09-25):
  - tools._log_query JSONL      (SFU_FEATURE_QUERY_LOG_ENABLED + SFU_QUERY_LOG_PATH)
  - tools._persist_metric JSONL (SFU_METRICS_LOG_PATH; default in-repo logs/mcp_metrics.jsonl)
  - serve query-log             (data/eval_results/serve_query_log.jsonl, lib/serve_query_log.py)
  - engagement log              (SFU_ENGAGEMENT_LOG_PATH, default logs/engagement_log.jsonl;
                                 backs web/src/analytics.jsx via lib/analytics.py)
  - any data/eval_results file naming a follow-up tool (Playwright / eval drives)

Read-only.  Does not touch data/thinclient_index.
"""
from __future__ import annotations

import ast
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "src/lib/tools.py"
SERVE_LOG = ROOT / "data/eval_results/serve_query_log.jsonl"
METRICS_LOG = ROOT / "logs/mcp_metrics.jsonl"
ENGAGEMENT_LOG = Path(os.environ.get("SFU_ENGAGEMENT_LOG_PATH",
                                     str(ROOT / "logs/engagement_log.jsonl")))
QUERY_LOG = os.environ.get("SFU_QUERY_LOG_PATH", "")
EVAL_DIR = ROOT / "data/eval_results"
OUT = EVAL_DIR / f"mcp_followup_trace_analysis_{date.today().isoformat()}.json"

FOLLOWUP_TOOLS = ("get_paper_summary", "get_references", "get_full_text_link")
WINDOWS_S = (30, 60, 300)


def read_jsonl(p: Path) -> list[dict]:
    rows = []
    if not p.is_file():
        return rows
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def inventory() -> dict:
    """Every trace source: does it exist, rows, which fields, follow-up calls."""
    out = {}

    serve = read_jsonl(SERVE_LOG)
    keys = sorted({k for r in serve for k in r})
    out["serve_query_log"] = {
        "path": str(SERVE_LOG.relative_to(ROOT)),
        "exists": SERVE_LOG.is_file(),
        "rows": len(serve),
        "fields": keys,
        "has_tool_name": "tool" in keys or "handler" in keys,
        "has_result_ids": "result_oaids" in keys,
        "has_result_fingerprint": "result_fp" in keys,
        "has_session": "session" in keys,
        "modes": dict(Counter(r.get("mode") for r in serve)),
        "sessions": len({r.get("session") for r in serve}),
        "date_range": [serve[0]["ts"], serve[-1]["ts"]] if serve else None,
        "emitters": [
            "src/lib/tools.py search_academic_structured (GUI /api/search only)",
            "src/sfu_library_mcp_http.py _log_cache_served_hit (GUI result-cache hits)",
        ],
        "mcp_tool_rows": 0,
        "note": ("Written only by the GUI structured search path and its "
                 "result-cache hit path. The MCP text handlers "
                 "(_handle_search_academic et al.) never call log_serve_query, "
                 "so no MCP tool call can appear here. result_oaids is an "
                 "argument to log(), not a logged field: only its sha1 "
                 "(result_fp, over the ranked list as given, not sorted) is "
                 "written."),
    }

    metrics = read_jsonl(METRICS_LOG)
    mkeys = sorted({k for r in metrics for k in r})
    out["metrics_log"] = {
        "path": str(METRICS_LOG.relative_to(ROOT)),
        "exists": METRICS_LOG.is_file(),
        "rows": len(metrics),
        "fields": mkeys,
        "tools": dict(Counter(r.get("tool") for r in metrics)),
        "followup_rows": sum(1 for r in metrics if r.get("tool") in FOLLOWUP_TOOLS),
        "has_session": "session" in mkeys,
        "has_doc_ids": False,
        "date_range": [metrics[0]["ts"], metrics[-1]["ts"]] if metrics else None,
        "note": ("The only log with a per-call tool name "
                 "(tools.handle_tool_call -> _record_metric -> _persist_metric). "
                 "No arguments, no result ids, no session."),
    }

    eng = read_jsonl(ENGAGEMENT_LOG)
    out["engagement_log"] = {
        "path": str(ENGAGEMENT_LOG),
        "exists": ENGAGEMENT_LOG.is_file(),
        "rows": len(eng),
        "kinds": dict(Counter(r.get("kind") for r in eng)),
        "note": ("Backs web/src/analytics.jsx (lib/analytics.py position_bias "
                 "and session_replay panels). Has session_id + doc_id + "
                 "action_type (abstract|tldr|pdf|citation|zotero) but is "
                 "client-posted GUI engagement, not MCP tool calls."),
    }

    qpath = Path(QUERY_LOG) if QUERY_LOG else None
    qrows = read_jsonl(qpath) if qpath else []
    out["tools_query_log"] = {
        "path": QUERY_LOG or "(SFU_QUERY_LOG_PATH unset)",
        "exists": bool(qpath and qpath.is_file()),
        "rows": len(qrows),
        "note": ("tools._log_query: searches only (handler, top-10 doi); no "
                 "session, no follow-up tools. Off unless "
                 "SFU_FEATURE_QUERY_LOG_ENABLED."),
    }

    hits = []
    for p in sorted(EVAL_DIR.rglob("*")):
        if not p.is_file() or p == OUT or p.stat().st_size > 50_000_000:
            continue
        if p.name.startswith("mcp_followup_trace_analysis_"):
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        if any(t in text for t in FOLLOWUP_TOOLS):
            hits.append(str(p.relative_to(ROOT)))
    out["eval_results_mentioning_followup_tools"] = hits
    return out


def q1(inv: dict) -> dict:
    n_follow = inv["metrics_log"]["followup_rows"]
    return {
        "question": "follow-up call references a doc in the previous search's top-10",
        "n_followup_calls_with_doc_id": 0,
        "n_followup_calls_any": n_follow,
        "hit_rate": None,
        "status": "UNMEASURABLE",
        "missing": (
            "No trace records a follow-up MCP tool call together with its doc "
            "id and a session. The metrics log has the tool name but no "
            "arguments/results; the serve log has sessions but only GUI "
            "searches; the engagement log is GUI click events."),
        "one_field_fix": (
            "Add `ids` to the _persist_metric line (logs/mcp_metrics.jsonl): for "
            "search_* tools the ranked top-10 openalex_id/doi list, for "
            "get_paper_summary/get_references/get_full_text_link the "
            "normalize_doi() of the argument. Under stdio transport one server "
            "process is one client conversation, so a per-process `session` "
            "(as serve_query_log already mints) closes the join for HTTP."),
    }


def q2() -> dict:
    rows = read_jsonl(SERVE_LOG)
    user = [r for r in rows if not r.get("speculative")]
    by = defaultdict(list)
    for r in user:
        by[r["session"]].append(r)
    pairs = []
    for s, rs in by.items():
        rs.sort(key=lambda r: r["ts"])
        for a, b in zip(rs, rs[1:]):
            pairs.append({
                "session": s,
                "dt": (ts(b["ts"]) - ts(a["ts"])).total_seconds(),
                "same_query": a["query_hash"] == b["query_hash"],
                "same_fp": bool(a["result_fp"]) and a["result_fp"] == b["result_fp"],
            })
    res = {
        "source": str(SERVE_LOG.relative_to(ROOT)),
        "rows_total": len(rows),
        "rows_speculative_excluded": len(rows) - len(user),
        "rows_submitted": len(user),
        "sessions": len(by),
        "sessions_with_ge2_searches": sum(1 for v in by.values() if len(v) >= 2),
        "consecutive_pairs": len(pairs),
        "windows": {},
        "jaccard": None,
        "jaccard_status": "UNMEASURABLE: only result_fp (sha1 of the ranked id list) is logged; equal fp => Jaccard 1, unequal fp => any value in [0,1)",
    }
    for w in WINDOWS_S:
        inw = [p for p in pairs if p["dt"] <= w]
        refined = [p for p in inw if not p["same_query"]]
        res["windows"][f"le_{w}s"] = {
            "pairs": len(inw),
            "share_of_pairs": round(len(inw) / len(pairs), 4) if pairs else None,
            "different_query": len(refined),
            "different_query_identical_result_fp": sum(1 for p in refined if p["same_fp"]),
            "same_query_repeat": len(inw) - len(refined),
        }
    size = Counter(len(v) for v in by.values())
    res["session_size_histogram"] = dict(sorted(size.items()))
    res["rows_by_date"] = dict(sorted(Counter(r["ts"][:10] for r in rows).items()))
    res["provenance"] = (
        "The session field is a per-server-process random id. The multi-search "
        "sessions (2026-07-18, 2026-07-28) are each one server process driven by the speculation A/B "
        "benchmark (speculation_ab_2026-07-18.json / _2026-07-28.json) through "
        "the GUI /api/search path: replayed topic lists, not agent sessions. "
        "Inter-search gaps are the driver's pacing, and query order is the "
        "topic list's, so the pair counts characterise the harness, not agent "
        "refinement behaviour. Later rows (2026-08 onward) are 1-3-row sessions "
        "from smoke/test processes. No MCP search session exists in any trace.")
    return res


def _calls_in(fn: ast.AsyncFunctionDef) -> list[str]:
    names = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.append(f.id)
            elif isinstance(f, ast.Attribute):
                names.append(f.attr)
    return names


def q3() -> dict:
    tree = ast.parse(TOOLS.read_text())
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    handlers = {
        "get_paper_summary": "_handle_get_paper_summary",
        "get_references": "_handle_get_references",
        "get_full_text_link": "_handle_get_full_text_link",
        "find_open_access": "_handle_find_open_access",
    }
    per = {}
    for tool, fname in handlers.items():
        fn = fns.get(fname)
        if fn is None:
            per[tool] = {"handler": fname, "found": False}
            continue
        calls = _calls_in(fn)
        per[tool] = {
            "handler": fname,
            "line": fn.lineno,
            "reads_work_cache": "_lookup_work" in calls,
            "remote_calls": sorted({c for c in calls if c in (
                "get_tldr", "get_references", "get_citations",
                "get_work_by_doi", "_check_unpaywall")}),
        }
    cache_callers = sorted({
        name for name, fn in fns.items()
        if "_cache_works" in _calls_in(fn) and name != "_cache_works"})
    return {
        "handlers": per,
        "cache_works_callers": cache_callers,
        "work_cache_capacity_keys": 500,
        "verdict": (
            "get_full_text_link already reads _work_cache first (_lookup_work) "
            "and every search handler calls _cache_works on the full fetch_k "
            "list BEFORE rerank, so a top-10 follow-up is already a cache hit "
            "with no remote call: #5 is moot for it (and for find_open_access's "
            "OpenAlex fallback). get_paper_summary does NOT read the works cache "
            "or any abstract: it always calls Semantic Scholar get_tldr; "
            "get_references always calls S2 get_references. Neither payload is "
            "in any cache, so #5 is not moot for them, but the only thing to "
            "warm is remote S2 calls (10 per search), which share the S2 "
            "client's circuit breaker and 429 backoff with user calls."),
    }


def main() -> None:
    inv = inventory()
    result = {
        "date": date.today().isoformat(),
        "script": "scripts/experiments/mcp_followup_trace_analysis.py",
        "sources": inv,
        "q1_followup_hits_prev_top10": q1(inv),
        "q2_second_search": q2(),
        "q3_works_cache_serves_followups": q3(),
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in (
        "q1_followup_hits_prev_top10", "q2_second_search")}, indent=2))
    print(json.dumps(result["q3_works_cache_serves_followups"]["handlers"], indent=2))
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
