"""Tests for the CircuitBreaker state machine (lib/retry.py)."""

import time

from lib.retry import CircuitBreaker


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(threshold=3)
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.can_proceed() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(threshold=3, timeout=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.can_proceed() is False

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.can_proceed() is True

    def test_success_resets_count(self):
        cb = CircuitBreaker(threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitBreaker.CLOSED

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(threshold=1, timeout=0.05)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        time.sleep(0.06)
        assert cb.can_proceed() is True
        assert cb.state == CircuitBreaker.HALF_OPEN
