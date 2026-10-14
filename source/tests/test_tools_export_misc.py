"""Tests for low-risk tool fixes: Europe PMC single-parse (#11).

The CSV-escaping (#9) and limit-clamping (#8) tests left with the
export_search_results MCP tool (owner decision 2026-10-12)."""

from unittest.mock import MagicMock, patch


from lib.tools import _fetch_europe_pmc


class TestEuropePmcSingleParse:
    def test_resp_json_called_once(self):
        """Item #11: the response body is parsed exactly once."""
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "hitCount": 2,
            "resultList": {"result": [
                {"title": "T1", "pubYear": "2020"},
                {"title": "T2", "pubYear": "2021"},
            ]},
        }
        with patch("lib.tools.requests.get", return_value=fake_resp):
            out = _fetch_europe_pmc("cancer", 10)
        assert fake_resp.json.call_count == 1
        assert "2 results" in out
