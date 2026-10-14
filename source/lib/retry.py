"""Circuit breaker shared by the external API clients (OpenAlex, Semantic Scholar, Zotero)."""

import logging
import threading
import time

logger = logging.getLogger("sfu_library_mcp")


class CircuitBreaker:
    """Circuit breaker to prevent repeated calls to a failing service.

    States:
        CLOSED: Normal operation, requests pass through.
        OPEN: Service is considered down, requests fail immediately.
        HALF_OPEN: After timeout, allow one test request through.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, threshold: int = 5, timeout: float = 60.0):
        self.threshold = threshold
        self.timeout = timeout
        self.failure_count = 0
        self.state = self.CLOSED
        self.last_failure_time: float = 0.0
        self._probe_in_flight = False
        self._lock = threading.Lock()

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self.failure_count = 0
            self.state = self.CLOSED
            self._probe_in_flight = False

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            self._probe_in_flight = False
            if self.failure_count >= self.threshold:
                self.state = self.OPEN
                logger.warning(
                    "Circuit breaker OPEN after %d failures", self.failure_count
                )

    def can_proceed(self) -> bool:
        """Check if a request should be allowed through."""
        with self._lock:
            if self.state == self.CLOSED:
                return True

            if self.state == self.OPEN:
                elapsed = time.time() - self.last_failure_time
                if elapsed >= self.timeout:
                    self.state = self.HALF_OPEN
                    self._probe_in_flight = True
                    logger.info("Circuit breaker HALF_OPEN, allowing test request")
                    return True
                return False

            if not self._probe_in_flight:
                self._probe_in_flight = True
                return True
            return False
