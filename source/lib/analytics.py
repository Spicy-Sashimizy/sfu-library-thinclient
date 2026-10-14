"""Analytics bundle for the Research Analytics GUI (Phase N tracking layer).

build_analytics_bundle() assembles the exact JSON shapes the design's dashboard
panels consume, from artifacts already on disk (read-only, no heavy compute):

  ndcg_by_subject   <- data/eval_results/benchmark_llm_judge_final.json
  reranker_signal   <- heuristic reranker weights (LambdaMART tier removed 2026-10-11)
  position_bias     <- logs/engagement_log.jsonl  (P(click|rank) + propensity)
  model_versions    <- models/model_registry.json (via lib.model_registry)
  session_replay    <- logs/engagement_log.jsonl  (query -> result -> action tree)
  kpis              <- benchmark summary (per-method NDCG@k/MRR/P@k) + judge-cache size
  index_shape       <- <index root>/manifest.json (per-section doc counts), the era
                       boundary (lib.thinclient.sections) and the RRF constant
                       (lib.federated_search._RRF_K)

Panels with no data source yet return {"status": "stub"|"awaiting_click_data"} so the
contract is explicit rather than silently empty. Served by GET /analytics.

Engagement rows come from two writers: the search GUI (one session id per browser
tab) and the MCP text path (tools._log_query, session "server", impressions only,
behind SFU_FEATURE_ENGAGEMENT_LOG_ENABLED). The click-fed panels count only the GUI
rows whenever any GUI impression exists, so a GUI search that also reaches
_log_query is not counted twice; the panel says which writer it counted in
"source" ("gui" | "server" | "none").
"""

import json
import logging
import os
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("sfu_library_mcp")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARK = _REPO_ROOT / "data/eval_results/benchmark_llm_judge_final.json"
_JUDGE_CACHE = _REPO_ROOT / "data/eval_results/llm_judge_cache.json"

_DEFAULT_INDEX_ROOT = _REPO_ROOT / "data" / "thinclient_index"

_MIN_CLICKS_FOR_PROPENSITY = 20

SERVER_SESSION = "server"

_SUBJECT_LABELS = {
    "social_sciences": "Social sciences",
    "med_bio": "Medicine & biology",
    "phys_eng": "Physical sciences & engineering",
    "cs_math": "Computing & mathematics",
    "other": "Other / unrouted",
}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _panel_ndcg_by_subject() -> dict:
    bench = _read_json(_BENCHMARK)
    if not bench:
        return {"status": "stub", "reason": "benchmark file missing"}
    breakdown = bench.get("subject_breakdown") or {}
    primary = breakdown.get("rrf") or {}
    subjects = sorted(
        ({"subject": s, "ndcg": v} for s, v in primary.items()),
        key=lambda r: r["ndcg"],
    )
    return {
        "status": "ok",
        "primary_method": "rrf",
        "subjects": subjects,
        "by_method": breakdown,
        "timestamp": bench.get("timestamp"),
    }


def _panel_reranker_signal() -> dict:
    try:
        from lib.reranker import _WEIGHTS_WITH_EMBEDDING
        axes = [{"signal": k, "weight": v} for k, v in _WEIGHTS_WITH_EMBEDDING.items()]
        return {"status": "ok", "source": "heuristic_weights", "axes": axes}
    except Exception:
        return {"status": "stub"}


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def engagement_source(events: list[dict]) -> tuple[str, list[dict]]:
    """Pick the writer the click-fed panels count, and the rows they count.

    GUI rows win whenever any non-server impression exists; the "server" session's
    rows are then dropped. With no GUI impression the server rows are counted
    as-is. Returns ("gui"|"server"|"none", rows).
    """
    gui_imp = any(e.get("kind") == "impression" and e.get("session_id") != SERVER_SESSION
                  for e in events)
    if gui_imp:
        return "gui", [e for e in events if e.get("session_id") != SERVER_SESSION]
    if events:
        has_server = any(e.get("session_id") == SERVER_SESSION for e in events)
        return ("server" if has_server else "gui"), events
    return "none", events


def _panel_position_bias(events: list[dict]) -> dict:
    source, events = engagement_source(events)
    impressions = defaultdict(int)
    clicks = defaultdict(int)
    for e in events:
        rank = e.get("rank")
        if rank is None:
            continue
        if e.get("kind") == "impression":
            impressions[rank] += 1
        elif e.get("kind") == "result_click":
            clicks[rank] += 1

    total_clicks = sum(clicks.values())
    ranks = sorted(set(impressions) | set(clicks)) or list(range(1, 11))
    curve = []
    for r in ranks:
        imp = impressions.get(r, 0)
        clk = clicks.get(r, 0)
        curve.append({
            "rank": r,
            "impressions": imp,
            "clicks": clk,
            "click": round(clk / imp, 4) if imp else 0.0,
        })
    base = next((c["click"] for c in curve if c["rank"] == 1 and c["click"] > 0), 0.0)
    for c in curve:
        c["propensity"] = round(c["click"] / base, 4) if base else None

    status = "ok" if total_clicks >= _MIN_CLICKS_FOR_PROPENSITY else "awaiting_click_data"
    return {
        "status": status,
        "source": source,
        "total_clicks": total_clicks,
        "total_impressions": sum(impressions.values()),
        "min_clicks_required": _MIN_CLICKS_FOR_PROPENSITY,
        "curve": curve,
        "note": "Propensity feeds IPS debiasing of click labels.",
    }


def _panel_model_versions() -> dict:
    try:
        from lib.model_registry import list_versions, registry
        return {"status": "ok", "updated": registry().get("updated"),
                "versions": list_versions()}
    except Exception as e:
        return {"status": "stub", "reason": str(e)}


def _panel_session_replay(events: list[dict]) -> dict:
    """Reconstruct sessions as query -> result -> action trees (newest first).

    Impression rows never open a session node (they carry no user act), so the
    impressions-only "server" session does not appear as an empty session.
    """
    source, events = engagement_source(events)
    sessions: dict[str, dict] = {}
    for e in events:
        sid = e.get("session_id")
        if not sid or e.get("kind") not in ("query", "result_click", "action"):
            continue
        sess = sessions.setdefault(sid, {"session_id": sid, "start": e.get("ts"),
                                         "queries": {}, "n_queries": 0,
                                         "n_clicks": 0, "n_actions": 0})
        kind = e.get("kind")
        q = e.get("query") or ""
        if kind == "query":
            qnode = sess["queries"].setdefault(q, {"query": q, "ts": e.get("ts"), "results": {}})
            if e.get("refined_from") and not qnode.get("refined_from"):
                qnode["refined_from"] = e.get("refined_from")
            sess["n_queries"] = len(sess["queries"])
        elif kind == "result_click":
            qnode = sess["queries"].setdefault(q, {"query": q, "results": {}})
            doc = e.get("doc_id") or ""
            qnode["results"].setdefault(doc, {"doc_id": doc, "rank": e.get("rank"), "actions": []})
            sess["n_clicks"] += 1
        elif kind == "action":
            qnode = sess["queries"].setdefault(q, {"query": q, "results": {}})
            doc = e.get("doc_id") or ""
            rnode = qnode["results"].setdefault(doc, {"doc_id": doc, "rank": e.get("rank"), "actions": []})
            rnode["actions"].append(e.get("action_type"))
            sess["n_actions"] += 1

    out = []
    for sess in sessions.values():
        queries = []
        for qnode in sess["queries"].values():
            results = list(qnode.get("results", {}).values())
            queries.append({"query": qnode["query"], "ts": qnode.get("ts"),
                            "refined_from": qnode.get("refined_from"), "results": results})
        out.append({
            "session_id": sess["session_id"], "start": sess["start"],
            "n_queries": sess["n_queries"], "n_clicks": sess["n_clicks"],
            "n_actions": sess["n_actions"], "queries": queries,
        })
    out.sort(key=lambda s: s.get("start") or "", reverse=True)
    return {"status": "ok" if out else "awaiting_click_data", "source": source,
            "sessions": out}


def _panel_kpis() -> dict:
    bench = _read_json(_BENCHMARK) or {}
    summary = bench.get("summary") or {}
    methods = [
        {"method": name, "label": m.get("label") or name,
         "mean_ndcg": m.get("mean_ndcg"), "mean_mrr": m.get("mean_mrr"),
         "mean_p_at_k": m.get("mean_p_at_k")}
        for name, m in summary.items() if isinstance(m, dict)
    ]
    best = max(methods, key=lambda m: m["mean_ndcg"] or 0, default=None)
    judge = _read_json(_JUDGE_CACHE) or {}
    n_pairs = len(judge) if isinstance(judge, dict) else 0
    return {
        "status": "ok" if methods else "stub",
        "ndcg_mean_best": best["mean_ndcg"] if best else None,
        "best_method": best["method"] if best else None,
        "methods": methods,
        "k": bench.get("k"),
        "eval_queries": bench.get("num_queries"),
        "judged_pairs": n_pairs,
        "judge": bench.get("judge"),
        "timestamp": bench.get("timestamp"),
        "source": _rel(_BENCHMARK),
    }


def _index_root() -> Path:
    return Path(os.environ.get("SFU_THINCLIENT_INDEX_ROOT") or _DEFAULT_INDEX_ROOT)


def _panel_index_shape() -> dict:
    """Per-subject and per-era document counts from the served index manifest."""
    path = _index_root() / "manifest.json"
    manifest = _read_json(path)
    sections = (manifest or {}).get("sections") if isinstance(manifest, dict) else None
    if not isinstance(sections, dict) or not sections:
        return {"status": "stub", "reason": "index manifest not readable",
                "source": _rel(path)}
    try:
        from lib.thinclient.sections import ERA_BOUNDARY_YEAR as era_boundary
    except Exception:
        era_boundary = None
    try:
        from lib.federated_search import _RRF_K as rrf_k
    except Exception:
        rrf_k = None
    by_subject: dict[str, int] = defaultdict(int)
    by_era: dict[str, int] = defaultdict(int)
    rows = []
    for name, info in sections.items():
        docs = int((info or {}).get("docs") or 0)
        subject, _, era = name.partition("__")
        by_subject[subject] += docs
        by_era[era or "all"] += docs
        rows.append({"section": name, "subject": subject, "era": era or None,
                     "docs": docs, "state": (info or {}).get("state")})
    total = sum(r["docs"] for r in rows)
    subjects = sorted(
        ({"subject": k, "label": _SUBJECT_LABELS.get(k, k), "docs": v}
         for k, v in by_subject.items()),
        key=lambda r: (-r["docs"], r["subject"]),
    )
    eras = [{"era": k, "docs": v} for k, v in sorted(by_era.items())]
    return {
        "status": "ok",
        "total_docs": total,
        "docs_exported": manifest.get("docs_exported"),
        "n_sections": len(rows),
        "n_subjects": len(by_subject),
        "era_boundary_year": era_boundary,
        "rrf_k": rrf_k,
        "built": manifest.get("built"),
        "subjects": subjects,
        "eras": eras,
        "sections": rows,
        "source": _rel(path),
    }


_PANELS = {
    "ndcg_by_subject": lambda ev: _panel_ndcg_by_subject(),
    "reranker_signal": lambda ev: _panel_reranker_signal(),
    "position_bias": _panel_position_bias,
    "model_versions": lambda ev: _panel_model_versions(),
    "session_replay": _panel_session_replay,
    "kpis": lambda ev: _panel_kpis(),
    "index_shape": lambda ev: _panel_index_shape(),
    "embedding_drift": lambda ev: {"status": "stub", "reason": "UMAP export not wired"},
    "access_funnel": lambda ev: {"status": "stub", "reason": "access-resolver logging not wired"},
    "oa_equity": lambda ev: {"status": "stub", "reason": "OA-by-subject export not wired"},
}


def build_analytics_bundle(panel: str | None = None) -> dict:
    """Assemble the analytics bundle, or a single panel when `panel` is given."""
    from lib.engagement import load_events
    events = load_events()

    if panel:
        fn = _PANELS.get(panel)
        if fn is None:
            return {"error": f"unknown panel: {panel}", "panels": sorted(_PANELS)}
        return {"panel": panel, "data": fn(events)}

    return {
        "generated_for": "research_analytics_dashboard",
        "panels": {name: fn(events) for name, fn in _PANELS.items()},
    }
