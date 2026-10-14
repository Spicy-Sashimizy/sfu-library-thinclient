"""Tests for persistent JSONL metrics logging in tools.py."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lib.tools import _record_metric, _persist_metric


class TestPersistMetric:
    def test_no_op_when_path_not_configured(self, tmp_path):
        """When SFU_METRICS_LOG_PATH is empty, no file is written."""
        from lib.config import ServerConfig
        cfg = ServerConfig(metrics_log_path="")
        with patch("lib.tools._get_config", return_value=cfg):
            _persist_metric("some_tool", 0.05, True)
        assert not any(tmp_path.iterdir())

    def test_writes_jsonl_entry_when_path_configured(self, tmp_path):
        log_file = tmp_path / "metrics.jsonl"
        from lib.config import ServerConfig
        cfg = ServerConfig(metrics_log_path=str(log_file))
        with patch("lib.tools._get_config", return_value=cfg):
            _persist_metric("search_academic", 0.123, True)
        assert log_file.exists()
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["tool"] == "search_academic"
        assert entry["success"] is True
        assert entry["latency_ms"] == pytest.approx(123.0, abs=1.0)

    def test_failure_entry_written_correctly(self, tmp_path):
        log_file = tmp_path / "metrics.jsonl"
        from lib.config import ServerConfig
        cfg = ServerConfig(metrics_log_path=str(log_file))
        with patch("lib.tools._get_config", return_value=cfg):
            _persist_metric("search_academic", 0.5, False)
        entry = json.loads(log_file.read_text().strip())
        assert entry["success"] is False

    def test_multiple_entries_appended(self, tmp_path):
        log_file = tmp_path / "metrics.jsonl"
        from lib.config import ServerConfig
        cfg = ServerConfig(metrics_log_path=str(log_file))
        with patch("lib.tools._get_config", return_value=cfg):
            _persist_metric("tool_a", 0.1, True)
            _persist_metric("tool_b", 0.2, False)
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["tool"] == "tool_a"
        assert json.loads(lines[1])["tool"] == "tool_b"

    def test_parent_dir_created_automatically(self, tmp_path):
        nested = tmp_path / "nested" / "dir" / "metrics.jsonl"
        from lib.config import ServerConfig
        cfg = ServerConfig(metrics_log_path=str(nested))
        with patch("lib.tools._get_config", return_value=cfg):
            _persist_metric("tool_x", 0.01, True)
        assert nested.exists()

    def test_bad_path_does_not_raise(self):
        """A path that cannot be created must not propagate an exception."""
        from lib.config import ServerConfig
        cfg = ServerConfig(metrics_log_path="/proc/cannot-write-here/metrics.jsonl")
        with patch("lib.tools._get_config", return_value=cfg):
            _persist_metric("tool_y", 0.01, True)

    def test_entry_contains_required_fields(self, tmp_path):
        log_file = tmp_path / "metrics.jsonl"
        from lib.config import ServerConfig
        cfg = ServerConfig(metrics_log_path=str(log_file))
        with patch("lib.tools._get_config", return_value=cfg):
            _persist_metric("search_academic", 0.05, True)
        entry = json.loads(log_file.read_text().strip())
        for field in ("ts", "tool", "latency_ms", "success", "server_version"):
            assert field in entry, f"Missing field: {field}"
        assert entry["ts"].endswith("Z")

    def test_record_metric_calls_persist(self, tmp_path):
        """_record_metric must also trigger _persist_metric."""
        log_file = tmp_path / "metrics.jsonl"
        from lib.config import ServerConfig
        cfg = ServerConfig(metrics_log_path=str(log_file))
        with patch("lib.tools._get_config", return_value=cfg):
            _record_metric("search_by_doi", 0.08, True)
        assert log_file.exists()


def _read_entries(log_file: Path) -> list[dict]:
    return [json.loads(line) for line in log_file.read_text().strip().splitlines()]


def _sample_works(n: int) -> list[dict]:
    works = []
    for i in range(n):
        w = {
            "title": f"Paper {i}",
            "authors": ["Doe, Jane"],
            "date": "2024",
            "source": "Nature",
            "openalex_id": f"https://openalex.org/W{1000 + i}",
            "doi": f"https://doi.org/10.1000/p{i}" if i % 2 == 0 else "",
            "is_oa": False,
            "cited_by_count": i,
            "abstract": "",
            "topics": [],
        }
        works.append(w)
    return works


class TestMetricIdsAndSession:
    """ids/session fields on the metrics log (added 2026-09-25, spec §4b)."""

    @pytest.fixture
    def cfg_log(self, tmp_path):
        from lib.config import ServerConfig
        log_file = tmp_path / "metrics.jsonl"
        cfg = ServerConfig(metrics_log_path=str(log_file))
        with patch("lib.tools._get_config", return_value=cfg), \
                patch("lib.tools._get_features", return_value={}):
            yield log_file

    @pytest.mark.asyncio
    async def test_search_tool_logs_ranked_top10_ids(self, cfg_log):
        from lib.tools import handle_tool_call
        works = _sample_works(12)
        with patch("lib.tools._get_openalex") as mock_oa:
            mock_oa.return_value.search_works.return_value = {
                "results": works, "meta": {"count": 12}}
            mock_oa.return_value.circuit_open = False
            await handle_tool_call("search_academic", {"query": "q", "limit": 12})
        entry = _read_entries(cfg_log)[-1]
        assert entry["tool"] == "search_academic"
        expected = [f"10.1000/p{i}" if i % 2 == 0 else f"https://openalex.org/W{1000 + i}"
                    for i in range(10)]
        assert entry["ids"] == expected

    @pytest.mark.asyncio
    async def test_doc_level_tool_logs_normalized_doi(self, cfg_log):
        from lib.tools import handle_tool_call
        with patch("lib.tools._get_s2") as mock_s2:
            mock_s2.return_value.get_tldr.return_value = "short"
            await handle_tool_call("get_paper_summary",
                                   {"doi": "https://doi.org/10.1038/abc"})
        entry = _read_entries(cfg_log)[-1]
        assert entry["tool"] == "get_paper_summary"
        assert entry["ids"] == ["10.1038/abc"]

    @pytest.mark.asyncio
    async def test_tool_without_ids_logs_null(self, cfg_log):
        from lib.tools import handle_tool_call
        await handle_tool_call("nonexistent_tool", {})
        await handle_tool_call("get_paper_summary", {"doi": ""})
        entries = _read_entries(cfg_log)
        for e in entries:
            assert e["ids"] is None
            for field in ("ts", "tool", "latency_ms", "success", "server_version", "session"):
                assert field in e

    def test_direct_persist_without_ids_is_valid(self, cfg_log):
        _persist_metric("some_tool", 0.01, True)
        entry = _read_entries(cfg_log)[-1]
        assert entry["ids"] is None
        assert isinstance(entry["session"], str) and len(entry["session"]) == 8

    def test_session_constant_within_process(self, cfg_log):
        _persist_metric("a", 0.01, True)
        _persist_metric("b", 0.01, True, ids=["x"])
        _record_metric("c", 0.01, True)
        sessions = {e["session"] for e in _read_entries(cfg_log)}
        assert len(sessions) == 1

    def test_bound_http_session_overrides_process_id(self, cfg_log):
        from lib.tools import set_metric_session, reset_metric_session
        token = set_metric_session("abc-http-session")
        try:
            _persist_metric("a", 0.01, True)
        finally:
            reset_metric_session(token)
        _persist_metric("b", 0.01, True)
        first, second = _read_entries(cfg_log)
        assert first["session"] == "abc-http-session"
        assert second["session"] != "abc-http-session"
        assert len(second["session"]) == 8

    def test_ids_capped_at_ten(self, cfg_log):
        _persist_metric("a", 0.01, True, ids=[str(i) for i in range(12)])
        assert len(_read_entries(cfg_log)[-1]["ids"]) == 10

    @pytest.mark.asyncio
    async def test_output_text_unchanged_by_metrics_log(self, tmp_path):
        """Tool text is byte-identical with the metrics log on and off."""
        from lib.config import ServerConfig
        from lib.tools import handle_tool_call
        works = _sample_works(5)
        texts = []
        for path in ("", str(tmp_path / "m.jsonl")):
            cfg = ServerConfig(metrics_log_path=path)
            with patch("lib.tools._get_config", return_value=cfg), \
                    patch("lib.tools._get_features", return_value={}), \
                    patch("lib.tools._get_openalex") as mock_oa, \
                    patch("lib.tools._get_s2") as mock_s2:
                mock_oa.return_value.search_works.return_value = {
                    "results": [dict(w) for w in works], "meta": {"count": 5}}
                mock_oa.return_value.circuit_open = False
                mock_s2.return_value.get_tldr.return_value = "tl;dr text"
                a = await handle_tool_call("search_academic", {"query": "q"})
                b = await handle_tool_call("get_paper_summary", {"doi": "10.1/x"})
            texts.append((a[0].text, b[0].text))
        assert texts[0] == texts[1]
        assert texts[0][1] == "TLDR for 10.1/x:\n\ntl;dr text"
