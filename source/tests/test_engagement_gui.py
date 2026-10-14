"""GUI engagement wiring (owner decision 2026-10-12): the /engagement route takes the
batch the search GUI posts, `save` is a valid action, the click-fed analytics panels
drop the server session when GUI rows exist, and the client/server vocabularies match.
"""

import importlib
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_JS = REPO / "web" / "lib" / "api.js"

GUI_SESSION = "g-2318d4e1a2ad31d1b54bb0aa"


def _gui_batch():
    """The exact shape SFUApi.engagement flushes: {"events": [...]}, one object per
    event, keys limited to the validate_event vocabulary, ts as a JS ISO string."""
    ts = "2026-10-12T20:29:43.467Z"
    events = [{"ts": ts, "session_id": GUI_SESSION, "kind": "query",
               "query": "engagement query one"}]
    for rank in range(1, 4):
        events.append({"ts": ts, "session_id": GUI_SESSION, "kind": "impression",
                       "query": "engagement query one", "doc_id": f"10.0/p{rank}",
                       "rank": rank})
    events.append({"ts": ts, "session_id": GUI_SESSION, "kind": "result_click",
                   "query": "engagement query one", "doc_id": "10.0/p3", "rank": 3})
    for action in ("abstract", "pdf", "citation", "save"):
        events.append({"ts": ts, "session_id": GUI_SESSION, "kind": "action",
                       "query": "engagement query one", "doc_id": "10.0/p3", "rank": 3,
                       "action_type": action})
    events.append({"ts": ts, "session_id": GUI_SESSION, "kind": "query",
                   "query": "engagement query two",
                   "refined_from": "engagement query one"})
    return {"events": events}


@pytest.fixture
def eng_log(tmp_path, monkeypatch):
    path = tmp_path / "engagement.jsonl"
    monkeypatch.setenv("SFU_ENGAGEMENT_LOG_PATH", str(path))
    import lib.engagement as eng
    importlib.reload(eng)
    import lib.analytics as analytics
    importlib.reload(analytics)
    return path


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_engagement_route_accepts_gui_batch(eng_log):
    from starlette.testclient import TestClient
    import sfu_library_mcp_http as http_mod
    client = TestClient(http_mod._starlette)
    batch = _gui_batch()
    resp = client.post("/engagement", content=json.dumps(batch),
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json() == {"recorded": len(batch["events"])}
    rows = _rows(eng_log)
    assert len(rows) == len(batch["events"])
    assert {r["session_id"] for r in rows} == {GUI_SESSION}
    assert [r["action_type"] for r in rows if r["kind"] == "action"] == [
        "abstract", "pdf", "citation", "save"]
    assert rows[-1]["refined_from"] == "engagement query one"
    assert rows[0]["ts"] == "2026-10-12T20:29:43.467Z"


def test_engagement_route_beacon_body_without_json_content_type(eng_log):
    from starlette.testclient import TestClient
    import sfu_library_mcp_http as http_mod
    client = TestClient(http_mod._starlette)
    resp = client.post("/engagement", content=json.dumps(_gui_batch()),
                       headers={"Content-Type": "text/plain;charset=UTF-8"})
    assert resp.status_code == 200
    assert resp.json()["recorded"] == len(_gui_batch()["events"])


def test_engagement_route_skips_invalid_events_in_batch(eng_log):
    from starlette.testclient import TestClient
    import sfu_library_mcp_http as http_mod
    client = TestClient(http_mod._starlette)
    batch = {"events": [
        {"session_id": GUI_SESSION, "kind": "action", "action_type": "teleport"},
        {"session_id": GUI_SESSION, "kind": "action", "action_type": "save", "rank": 2},
    ]}
    resp = client.post("/engagement", json=batch)
    assert resp.json() == {"recorded": 1}
    bad = client.post("/engagement", content="{not json",
                      headers={"Content-Type": "application/json"})
    assert bad.status_code == 400


def test_save_is_a_valid_action_type(eng_log):
    import lib.engagement as eng
    assert "save" in eng.ACTION_TYPES
    out = eng.validate_event({"session_id": "s", "kind": "action", "action_type": "save"})
    assert out["action_type"] == "save"


def _js_list(name: str) -> set[str]:
    src = API_JS.read_text()
    m = re.search(r"const " + name + r" = \[([^\]]*)\];", src)
    assert m, f"{name} literal not found in web/lib/api.js"
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def test_client_server_vocabulary_parity():
    import lib.engagement as eng
    assert _js_list("ENGAGEMENT_ACTION_TYPES") == set(eng.ACTION_TYPES)
    assert _js_list("ENGAGEMENT_KINDS") == set(eng.KINDS)


def _server_impressions(n_queries=2, ranks=5):
    rows = []
    for q in range(n_queries):
        for rank in range(1, ranks + 1):
            rows.append({"session_id": "server", "kind": "impression",
                         "query": f"q{q}", "rank": rank, "doc_id": f"d{rank}"})
    return rows


def test_position_bias_drops_server_rows_when_gui_rows_exist(eng_log):
    import lib.analytics as analytics
    events = _server_impressions() + _gui_batch()["events"]
    pb = analytics._panel_position_bias(events)
    assert pb["source"] == "gui"
    assert pb["total_impressions"] == 3
    assert pb["total_clicks"] == 1
    rank3 = next(c for c in pb["curve"] if c["rank"] == 3)
    assert rank3["impressions"] == 1 and rank3["clicks"] == 1


def test_position_bias_counts_server_rows_without_gui_rows(eng_log):
    import lib.analytics as analytics
    pb = analytics._panel_position_bias(_server_impressions())
    assert pb["source"] == "server"
    assert pb["total_impressions"] == 10
    assert pb["status"] == "awaiting_click_data"
    assert pb["min_clicks_required"] == analytics._MIN_CLICKS_FOR_PROPENSITY


def test_position_bias_empty_log_says_none(eng_log):
    import lib.analytics as analytics
    pb = analytics._panel_position_bias([])
    assert pb["source"] == "none"
    assert pb["status"] == "awaiting_click_data"


def test_session_replay_excludes_server_session(eng_log):
    import lib.analytics as analytics
    events = _server_impressions() + _gui_batch()["events"]
    sr = analytics._panel_session_replay(events)
    assert sr["source"] == "gui"
    ids = [s["session_id"] for s in sr["sessions"]]
    assert ids == [GUI_SESSION]
    sess = sr["sessions"][0]
    assert sess["n_queries"] == 2 and sess["n_clicks"] == 1 and sess["n_actions"] == 4
    q2 = next(q for q in sess["queries"] if q["query"] == "engagement query two")
    assert q2["refined_from"] == "engagement query one"
    q1 = next(q for q in sess["queries"] if q["query"] == "engagement query one")
    assert q1["results"][0]["rank"] == 3
    assert q1["results"][0]["actions"] == ["abstract", "pdf", "citation", "save"]


def test_session_replay_server_only_has_no_empty_session(eng_log):
    import lib.analytics as analytics
    sr = analytics._panel_session_replay(_server_impressions())
    assert sr["source"] == "server"
    assert sr["sessions"] == []
    assert sr["status"] == "awaiting_click_data"


def test_bundle_end_to_end_from_route_written_log(eng_log):
    import lib.engagement as eng
    import lib.analytics as analytics
    eng.log_impressions("server", "q0", [{"doi": f"10.0/s{i}"} for i in range(4)])
    eng.record_engagement(_gui_batch())
    panels = analytics.build_analytics_bundle()["panels"]
    assert panels["position_bias"]["source"] == "gui"
    assert panels["position_bias"]["total_impressions"] == 3
    assert panels["session_replay"]["source"] == "gui"
    for name in ("kpis", "ndcg_by_subject", "reranker_signal", "model_versions",
                 "position_bias", "session_replay", "embedding_drift",
                 "access_funnel", "oa_equity", "index_shape"):
        assert name in panels and "status" in panels[name]


def test_index_shape_reads_manifest(tmp_path, monkeypatch):
    root = tmp_path / "idx"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({
        "built": "2026-06-16T03:00:21", "docs_exported": 31,
        "sections": {"med_bio__recent": {"docs": 10, "state": "live"},
                     "med_bio__archive": {"docs": 5, "state": "live"},
                     "other__recent": {"docs": 16, "state": "live"}}}))
    monkeypatch.setenv("SFU_THINCLIENT_INDEX_ROOT", str(root))
    import lib.analytics as analytics
    shape = analytics._panel_index_shape()
    assert shape["status"] == "ok"
    assert shape["total_docs"] == 31 and shape["n_sections"] == 3 and shape["n_subjects"] == 2
    assert {e["era"]: e["docs"] for e in shape["eras"]} == {"recent": 26, "archive": 5}
    assert shape["subjects"][0] == {"subject": "other", "label": "Other / unrouted", "docs": 16}
    assert shape["era_boundary_year"] == 2010
    assert shape["rrf_k"] == 60


def test_index_shape_missing_manifest_is_stub(tmp_path, monkeypatch):
    monkeypatch.setenv("SFU_THINCLIENT_INDEX_ROOT", str(tmp_path / "absent"))
    import lib.analytics as analytics
    shape = analytics._panel_index_shape()
    assert shape["status"] == "stub"
    assert "manifest" in shape["reason"]


def test_kpis_carry_per_method_rows_and_source():
    import lib.analytics as analytics
    kpis = analytics._panel_kpis()
    if kpis["status"] != "ok":
        pytest.skip("benchmark file not present in this checkout")
    assert kpis["source"].endswith("benchmark_llm_judge_final.json")
    assert kpis["best_method"] in {m["method"] for m in kpis["methods"]}
    assert kpis["ndcg_mean_best"] == max(m["mean_ndcg"] for m in kpis["methods"])
