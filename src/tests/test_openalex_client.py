"""Tests for OpenAlexClient retry logic and circuit breaker integration."""

import json
import time
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from lib.openalex import OpenAlexClient, DailyCallTracker
from lib.retry import CircuitBreaker


def _make_client(**kwargs) -> OpenAlexClient:
    """Return a client with a in-memory tracker (no /tmp writes) and fast retries."""
    defaults = dict(
        tracker_path="/tmp/test_openalex_tracker.json",
        max_retries=2,
        retry_base_delay=0.0,
        circuit_breaker_threshold=3,
        circuit_breaker_timeout=5.0,
    )
    defaults.update(kwargs)
    client = OpenAlexClient(**defaults)
    client._tracker._count = 0
    client._tracker._date = client._tracker._today()
    return client


def _ok_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def _error_response(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


class TestOpenAlexClientRetry:
    def test_successful_request_returns_data(self):
        client = _make_client()
        payload = {"results": [{"id": "W1"}], "meta": {"count": 1}}
        with patch("requests.get", return_value=_ok_response(payload)):
            result = client._get("/works", {"search": "test"})
        assert result == payload

    def test_retries_on_timeout_then_succeeds(self):
        client = _make_client(max_retries=2)
        payload = {"results": [], "meta": {}}
        with patch("requests.get", side_effect=[
            requests.Timeout("timeout"),
            _ok_response(payload),
        ]):
            result = client._get("/works", {})
        assert result == payload

    def test_retries_on_http_error_then_succeeds(self):
        client = _make_client(max_retries=2)
        payload = {"results": [], "meta": {}}
        with patch("requests.get", side_effect=[
            _error_response(503),
            _ok_response(payload),
        ]):
            result = client._get("/works", {})
        assert result == payload

    def test_returns_none_after_all_retries_exhausted(self):
        client = _make_client(max_retries=2)
        with patch("requests.get", side_effect=requests.Timeout("timeout")):
            result = client._get("/works", {})
        assert result is None

    def test_retries_on_429_with_4x_backoff(self):
        client = _make_client(max_retries=1, retry_base_delay=0.0)
        payload = {"results": [], "meta": {}}
        rate_limited = _ok_response({})
        rate_limited.status_code = 429
        rate_limited.raise_for_status.return_value = None
        with patch("requests.get", side_effect=[rate_limited, _ok_response(payload)]):
            result = client._get("/works", {})
        assert result == payload

    def test_returns_none_when_429_all_retries(self):
        client = _make_client(max_retries=1)
        rate_limited = _ok_response({})
        rate_limited.status_code = 429
        rate_limited.raise_for_status.return_value = None
        with patch("requests.get", return_value=rate_limited):
            result = client._get("/works", {})
        assert result is None

    def test_no_retry_on_unexpected_exception(self):
        client = _make_client(max_retries=3)
        with patch("requests.get", side_effect=ValueError("unexpected")):
            result = client._get("/works", {})
        assert result is None

    def test_attempt_count_matches_retries(self):
        client = _make_client(max_retries=2)
        with patch("requests.get", side_effect=requests.Timeout()) as mock_get:
            client._get("/works", {})
        assert mock_get.call_count == 3


class TestOpenAlexCircuitBreaker:
    def test_circuit_opens_after_threshold_failures(self):
        client = _make_client(circuit_breaker_threshold=3, max_retries=0)
        with patch("requests.get", side_effect=requests.Timeout()):
            for _ in range(3):
                client._get("/works", {})
        assert client._breaker.state == CircuitBreaker.OPEN

    def test_circuit_open_blocks_request_without_http_call(self):
        client = _make_client(circuit_breaker_threshold=1, max_retries=0)
        with patch("requests.get", side_effect=requests.Timeout()):
            client._get("/works", {})
        with patch("requests.get") as mock_get:
            result = client._get("/works", {})
        assert result is None
        mock_get.assert_not_called()

    def test_circuit_open_property_reflects_state(self):
        client = _make_client(circuit_breaker_threshold=1, max_retries=0)
        assert client.circuit_open is False
        with patch("requests.get", side_effect=requests.Timeout()):
            client._get("/works", {})
        assert client.circuit_open is True

    def test_circuit_resets_after_successful_request(self):
        client = _make_client(circuit_breaker_threshold=3, max_retries=0)
        payload = {"results": [], "meta": {}}
        with patch("requests.get", side_effect=requests.Timeout()):
            for _ in range(3):
                client._get("/works", {})
        assert client._breaker.state == CircuitBreaker.OPEN
        client._breaker.state = CircuitBreaker.HALF_OPEN
        with patch("requests.get", return_value=_ok_response(payload)):
            client._get("/works", {})
        assert client._breaker.state == CircuitBreaker.CLOSED

    def test_circuit_half_open_after_timeout(self):
        client = _make_client(circuit_breaker_threshold=1, circuit_breaker_timeout=0.05, max_retries=0)
        with patch("requests.get", side_effect=requests.Timeout()):
            client._get("/works", {})
        assert client._breaker.state == CircuitBreaker.OPEN
        time.sleep(0.1)
        assert client._breaker.can_proceed() is True
        assert client._breaker.state == CircuitBreaker.HALF_OPEN


class TestOpenAlexCircuitBreakerWithRetries:
    """Regression (Item 1): with retries enabled, one failing request must
    record exactly ONE breaker failure — not one per attempt.

    The existing breaker tests use max_retries=0, which hides the bug.
    """

    def test_one_failing_request_records_single_failure(self):
        client = _make_client(
            max_retries=3, retry_base_delay=0.0, circuit_breaker_threshold=5
        )
        with patch("requests.get", side_effect=requests.Timeout()) as mock_get:
            result = client._get("/works", {})
        assert result is None
        assert mock_get.call_count == 4
        assert client._breaker.failure_count == 1
        assert client._breaker.state == CircuitBreaker.CLOSED

    def test_http_error_records_single_failure(self):
        client = _make_client(
            max_retries=3, retry_base_delay=0.0, circuit_breaker_threshold=5
        )
        with patch("requests.get", side_effect=requests.HTTPError()):
            client._get("/works", {})
        assert client._breaker.failure_count == 1
        assert client._breaker.state == CircuitBreaker.CLOSED

    def test_breaker_opens_only_after_threshold_logical_requests(self):
        client = _make_client(
            max_retries=3, retry_base_delay=0.0, circuit_breaker_threshold=5
        )
        with patch("requests.get", side_effect=requests.Timeout()):
            for _ in range(4):
                client._get("/works", {})
        assert client._breaker.failure_count == 4
        assert client._breaker.state == CircuitBreaker.CLOSED
        with patch("requests.get", side_effect=requests.Timeout()):
            client._get("/works", {})
        assert client._breaker.state == CircuitBreaker.OPEN


class TestOpenAlexBudgetBlocking:
    def test_budget_exhausted_blocks_request(self):
        client = _make_client()
        client._tracker._count = client._tracker.limit
        with patch("requests.get") as mock_get:
            result = client._get("/works", {})
        assert result is None
        mock_get.assert_not_called()

    def test_budget_not_exhausted_allows_request(self):
        client = _make_client()
        client._tracker._count = 0
        payload = {"results": [], "meta": {}}
        with patch("requests.get", return_value=_ok_response(payload)):
            result = client._get("/works", {})
        assert result == payload

    def test_budget_counter_increments_on_success(self):
        client = _make_client()
        before = client._tracker._count
        with patch("requests.get", return_value=_ok_response({"results": [], "meta": {}})):
            client._get("/works", {})
        assert client._tracker._count == before + 1

    def test_budget_counter_not_incremented_on_failure(self):
        client = _make_client(max_retries=0)
        before = client._tracker._count
        with patch("requests.get", side_effect=requests.Timeout()):
            client._get("/works", {})
        assert client._tracker._count == before


class TestOpenAlexResponseCache:
    def test_cached_response_skips_http_call(self):
        client = _make_client()
        payload = {"results": [{"id": "W999"}], "meta": {}}
        with patch("requests.get", return_value=_ok_response(payload)):
            first = client._get("/works", {"search": "cached"})
        with patch("requests.get") as mock_get:
            second = client._get("/works", {"search": "cached"})
        assert second == payload
        mock_get.assert_not_called()

    def test_different_params_bypass_cache(self):
        client = _make_client()
        payload_a = {"results": [{"id": "W1"}], "meta": {}}
        payload_b = {"results": [{"id": "W2"}], "meta": {}}
        with patch("requests.get", side_effect=[_ok_response(payload_a), _ok_response(payload_b)]):
            r1 = client._get("/works", {"search": "alpha"})
            r2 = client._get("/works", {"search": "beta"})
        assert r1 == payload_a
        assert r2 == payload_b


_FAKE_KEY = "test-key-not-a-real-secret"


class TestFetchAbstractsByIds:
    def _inv(self, text: str) -> dict:
        inv: dict[str, list[int]] = {}
        for pos, word in enumerate(text.split()):
            inv.setdefault(word, []).append(pos)
        return inv

    def test_sends_key_select_and_chunks_by_50(self):
        client = _make_client(api_key=_FAKE_KEY, mailto="a@b.c")
        ids = [f"W{i}" for i in range(120)]
        with patch("requests.get", return_value=_ok_response({"results": [
            {"id": "https://openalex.org/W3", "abstract_inverted_index": self._inv("hello world")},
            {"id": "https://openalex.org/W4", "abstract_inverted_index": None},
        ]})) as mock_get:
            out = client.fetch_abstracts_by_ids(ids)
        assert mock_get.call_count == 3
        params = [c.kwargs["params"] for c in mock_get.call_args_list]
        assert all(p["api_key"] == _FAKE_KEY and "mailto" not in p for p in params)
        assert all(p["select"] == "id,abstract_inverted_index" for p in params)
        assert [p["per-page"] for p in params] == ["50", "50", "20"]
        assert params[0]["filter"] == "openalex_id:" + "|".join(ids[:50])
        assert all(c.kwargs["timeout"] == 15.0 for c in mock_get.call_args_list)
        assert out == {"W3": "hello world"}
        assert client.budget_status()["calls_today"] == 3

    def test_no_key_uses_mailto(self):
        client = _make_client(mailto="a@b.c")
        with patch("requests.get", return_value=_ok_response({"results": []})) as mock_get:
            client.fetch_abstracts_by_ids(["https://openalex.org/W1"])
        p = mock_get.call_args.kwargs["params"]
        assert p["mailto"] == "a@b.c" and "api_key" not in p
        assert p["filter"] == "openalex_id:W1"

    def test_429_returns_empty_without_retry_sleep(self):
        client = _make_client(api_key=_FAKE_KEY, retry_base_delay=30.0)
        resp = MagicMock()
        resp.status_code = 429
        with patch("requests.get", return_value=resp) as mock_get, \
                patch("time.sleep") as mock_sleep:
            out = client.fetch_abstracts_by_ids(["W1", "W2"])
        assert out == {}
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()
        assert client.budget_status()["calls_today"] == 0

    def test_budget_exhausted_blocks_without_http(self):
        client = _make_client(api_key=_FAKE_KEY, daily_call_limit=2)
        client._tracker._count = 2
        with patch("requests.get") as mock_get:
            assert client.fetch_abstracts_by_ids(["W1"]) == {}
        mock_get.assert_not_called()

    def test_breaker_open_blocks_without_http(self):
        client = _make_client(api_key=_FAKE_KEY)
        for _ in range(3):
            client._breaker.record_failure()
        with patch("requests.get") as mock_get:
            assert client.fetch_abstracts_by_ids(["W1"]) == {}
        mock_get.assert_not_called()

    def test_error_logs_redact_api_key(self, caplog):
        import logging
        client = _make_client(api_key=_FAKE_KEY)
        err = requests.ConnectionError(f"bad url /works?api_key={_FAKE_KEY}&x=1")
        with patch("requests.get", side_effect=err), \
                caplog.at_level(logging.ERROR, logger="sfu_library_mcp"):
            assert client.fetch_abstracts_by_ids(["W1"]) == {}
        assert "OpenAlex request failed" in caplog.text
        assert _FAKE_KEY not in caplog.text
