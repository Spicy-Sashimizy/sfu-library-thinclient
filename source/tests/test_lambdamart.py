"""Tests for engagement logging, the analytics bundle shape, and the model registry.

The LambdaMART tier and its feature module were removed 2026-10-11; the file name is
kept so the surviving engagement/analytics/registry tests keep their history.
"""

import pytest


def test_lambdamart_gate_removed():
    from lib.config import load_config
    cfg = load_config()
    assert "lambdamart_enabled" not in cfg.features
    assert not hasattr(cfg, "lambdamart_model_path")


def test_engagement_validation_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SFU_ENGAGEMENT_LOG_PATH", str(tmp_path / "eng.jsonl"))
    import importlib
    import lib.engagement as eng
    importlib.reload(eng)

    assert eng.record_engagement({"session_id": "s1", "kind": "result_click",
                                  "query": "q", "rank": 1, "doc_id": "d1"}) == 1
    n = eng.record_engagement({"events": [
        {"session_id": "s1", "kind": "action", "query": "q", "doc_id": "d1", "action_type": "pdf"},
        {"session_id": "s1", "kind": "action", "doc_id": "d1"},
        {"kind": "query"},
    ]})
    assert n == 1
    assert len(eng.load_events()) == 2


def test_engagement_rejects_bad_kind(tmp_path, monkeypatch):
    monkeypatch.setenv("SFU_ENGAGEMENT_LOG_PATH", str(tmp_path / "eng.jsonl"))
    import importlib
    import lib.engagement as eng
    importlib.reload(eng)
    assert eng.record_engagement({"session_id": "s1", "kind": "not_a_kind"}) == 0


def test_analytics_bundle_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("SFU_ENGAGEMENT_LOG_PATH", str(tmp_path / "eng.jsonl"))
    import importlib
    import lib.engagement as eng
    importlib.reload(eng)
    import lib.analytics as analytics
    importlib.reload(analytics)

    evs = []
    for s in range(3):
        for rank in range(1, 4):
            evs.append({"session_id": f"s{s}", "kind": "impression",
                        "query": "q", "rank": rank, "doc_id": f"d{rank}"})
    evs.append({"session_id": "s0", "kind": "result_click", "query": "q", "rank": 1, "doc_id": "d1"})
    evs.append({"session_id": "s0", "kind": "query", "query": "q"})
    eng.record_engagement({"events": evs})

    bundle = analytics.build_analytics_bundle()
    panels = bundle["panels"]
    for name in ("ndcg_by_subject", "reranker_signal", "position_bias",
                 "model_versions", "session_replay", "kpis"):
        assert name in panels
    pb = panels["position_bias"]
    rank1 = next(c for c in pb["curve"] if c["rank"] == 1)
    assert rank1["impressions"] == 3 and rank1["clicks"] == 1
    assert rank1["propensity"] == 1.0
    assert panels["reranker_signal"]["status"] == "ok"
    assert panels["model_versions"]["status"] == "ok"
    assert len(panels["model_versions"]["versions"]) >= 1


def test_analytics_single_panel():
    import lib.analytics as analytics
    out = analytics.build_analytics_bundle(panel="model_versions")
    assert out["panel"] == "model_versions"
    assert "data" in out


def test_model_registry_marks_availability():
    from lib.model_registry import list_versions
    rows = list_versions()
    assert not [r for r in rows if r["component"] == "lambdamart"]
    assert any(r["component"] == "cross_encoder" and "available" in r for r in rows)
