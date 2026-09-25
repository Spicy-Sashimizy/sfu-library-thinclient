"""Production query-log capture for the served SEISMIC/thin-client search path.

**One env to turn on, one env to turn off.** The served search path becomes
*observably query-shape-aware* — the gate the disk-streaming research track
(`docs/disk_streaming_research/`) is explicitly blocked on (LRU/pin + PILOT
prefetch need a production query log to size the hot set; see Q12/Q12b which
synthesize a production-like log because none existed).

WHAT IS LOGGED (privacy-sane — never the true raw query text):
  - ts              UTC ISO8601 timestamp (second precision)
  - query_norm      EMPTY by default (""). Only populated when
                    SFU_SERVE_QUERY_LOG_RAW=1 (opt-in, default off), AND even
                    then it is the NORMALIZED text (lowercased, whitespace-
                    collapsed, outer-punctuation-trimmed, truncated to 200
                    chars) — NEVER the true raw query. The normalization is the
                    privacy boundary: "Machine Learning!" → "machine, learning".
                    Default "" keeps the log PII-free (only the hash below).
  - query_hash      sha1(query_norm)[:16] — ALWAYS logged. The stable, linkable
                    id for replay + dedup + the skew key, computed from the
                    normalized text. This is the join key for cross-pass
                    repeat-traffic analysis when raw text isn't stored.
  - k               the served top_k
  - mode            'federated'|'thinclient'|'openalex' (the dispatch path)
  - backend         the SPLADE leg backend in effect (seismic|qdrant|…) or ''
  - federation      SFU_SEISMIC_FEDERATION in effect (parallel|sequential|hybrid)
                    when the seismic backend served; else ''
  - leg_ms          {bm25f, splade, dense, rrf, total} — per-leg latency in ms
                    (None when a leg didn't run; total = wall end-to-end)
  - n_results       result-set size (the federated top-k returned)
  - result_fp       sha1 of the rank-ordered top-k oaid list [:16] — the result-set
                    fingerprint (repeat/replay detection: same fingerprint across
                    queries ⟹ same answer set ⟹ cacheable; distribution of
                    distinct fingerprints ⟹ the working-set shape the LRU/pin
                    tier must cover)
  - filters         boolean presence of year/type/OA filters (shape only, not values)
  - session         a short random id per server process (group-by for within-
                    session repeat Traffic; not a user id)
  - cache_hit       (WI-17) True when this query was served from the read-
                    through result cache (no retrieval work done); False when it
                    ran the full retrieval path; absent/None when the result
                    cache is disabled. Lets the cache efficacy + the ratio of
                    repeat-to-fresh traffic be measured from the existing log.
  - speculative     (WI-18) True when this execution was a searchbar keystroke
                    speculation (the result-cache priming the speculation path
                    fires), NOT a real Enter-submit. Absent/None for ordinary
                    traffic so analytics + the cache_hit field stay
                    uncontaminated (a speculation that lands a cache HIT is
                    cache_hit=true AND speculative=true; a fresh store is
                    cache_hit=false + speculative=true). Lets the speculation
                    hit-rate / waste / interference be measured from the log.

LATENCY: ≈0 on the hot path. The search path hands the logger a dict of already-
measured leg latencies (the retriever already calls `_record_leg`; this just
*sinks* them) + the result oaids. All file I/O is done by a single background
daemon thread consuming a bounded queue; `log()` is a non-blocking `put_nowait`
that drops (counts) on backpressure rather than ever stalling a query. The
oaid fingerprint + query hash are sha1 (µs for the sizes here).

ROTATION: each file capped at `max_bytes`; on overflow the current file is
rotated to `.1` (previous `.1` dropped) and a new file opened. Bounded disk use
= safe to leave ON in staging indefinitely. Synchronous flush only at shutdown
(best-effort) — the OS page cache absorbs the write; a crash loses only the
in-flight buffer, never corrupts a committed line.

ENV:
  SFU_SERVE_QUERY_LOG       =1|true  enable (default ON in staging — see _staging_default)
  SFU_SERVE_QUERY_LOG=0       .disable in one env (the kill switch)
  SFU_SERVE_QUERY_LOG_PATH  path (default data/eval_results/serve_query_log.jsonl)
  SFU_SERVE_QUERY_LOG_MAX_BYTES  per-file cap (default 64 MiB)
  SFU_SERVE_QUERY_LOG_RAW   =1 store the NORMALIZED query text (truncated 200,
                              lowercased/whitespace-collapsed — never the true
                              raw query; default OFF for PII minimality)
  SFU_SERVE_QUERY_LOG_BUFFER  queue depth before drop (default 8192)

Goes into the owning doc per the same-commit doc rule: `docs/THIN_CLIENT_SWAP.md`
gets a serving-path section (this is a served-path observability module).
"""
import hashlib
import json
import logging
import os
import queue
import threading
import time
from pathlib import Path

log = logging.getLogger("serve_query_log")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = "data/eval_results/serve_query_log.jsonl"


def _staging_default() -> bool:
    """ON by default in a staging/dev context (the drive prompt's requirement),
    OFF in production unless explicitly enabled — so a production deploy that
    forgets the env does NOT silently start writing query logs. The staging
    detector: SFU_SERVE_QUERY_LOG_STAGING=1 forces on; SFU_ACTIVE_PROFILE !=
    'production' OR an unset SFU_ENV treats the deploy as staging. Override in
    either direction with SFU_SERVE_QUERY_LOG=0|1 (the explicit kill/enable)."""
    explicit = os.environ.get("SFU_SERVE_QUERY_LOG")
    if explicit is not None:
        return explicit.strip().lower() in ("1", "true", "yes", "on")
    if os.environ.get("SFU_SERVE_QUERY_LOG_STAGING", "").lower() in ("1", "true"):
        return True
    profile = os.environ.get("SFU_ACTIVE_PROFILE", "default")
    env = os.environ.get("SFU_ENV", "")
    return profile.lower() != "production" and env.lower() != "production"


class QueryLogger:
    """Singleton async JSONL query logger with size-capped rotation.

    Thread-safe (a single daemon thread drains a bounded queue). Construction
    is cheap and idempotent — `QueryLogger.get()` returns the process-wide
    instance, creating the writer thread on first use. When disabled (env off)
    `log()` is a hard no-op (the `enabled` gate is checked BEFORE the queue put
    so the hot path pays only one bool read when off)."""

    _instance: "QueryLogger | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, path: str, max_bytes: int, buffer: int,
                 store_raw: bool, enabled: bool):
        self.path = Path(path)
        if not self.path.is_absolute():
            self.path = _REPO_ROOT / self.path
        self.max_bytes = max_bytes
        self.store_raw = store_raw
        self.enabled = enabled
        self._session = os.environ.get("SFU_SERVE_QUERY_LOG_SESSION") or _rand_id()
        self._dropped = 0
        self._q: "queue.Queue[dict | None]" = queue.Queue(maxsize=max(1, buffer))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="serve-query-log",
                                        daemon=True)
        self._fh = None
        self._bytes_written = 0
        if enabled:
            self._thread.start()
            log.info("serve_query_log: ON -> %s (max %d MB, buffer %d, raw=%s, "
                     "session=%s)", self.path, max_bytes // (1024 * 1024),
                     buffer, store_raw, self._session)
        else:
            log.info("serve_query_log: OFF (SFU_SERVE_QUERY_LOG=0 or staging-default)")

    @classmethod
    def get(cls) -> "QueryLogger":
        if cls._instance is not None:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls._build()
            return cls._instance

    @classmethod
    def _build(cls) -> "QueryLogger":
        enabled = _staging_default()
        path = os.environ.get("SFU_SERVE_QUERY_LOG_PATH", _DEFAULT_PATH)
        max_bytes = _int_env("SFU_SERVE_QUERY_LOG_MAX_BYTES", 64 * 1024 * 1024)
        buffer = _int_env("SFU_SERVE_QUERY_LOG_BUFFER", 8192)
        store_raw = os.environ.get("SFU_SERVE_QUERY_LOG_RAW", "0").lower() in ("1", "true")
        return cls(path, max_bytes, buffer, store_raw, enabled)

    @classmethod
    def reset_for_test(cls):
        """Tests construct a fresh logger; the process singleton must be cleared
        so a fresh env config takes effect between cases."""
        with cls._instance_lock:
            inst = cls._instance
            cls._instance = None
        if inst is not None:
            inst.close()


    def log(self, *, query: str, k: int, mode: str, backend: str = "",
             federation: str = "", leg_ms: dict | None = None,
             n_results: int = 0, result_oaids: list | None = None,
             filtered: bool = False, cache_hit: bool | None = None,
             speculative: bool | None = None) -> None:
        """Non-blocking. Builds the entry (sha1 of norm query + result oaid list)
        on the CALLING thread (µs for the sizes here), then put_nowait to the
        writer queue. On backpressure (queue full) the entry is dropped and
        counted — a query is NEVER delayed by logging.

        ``speculative`` (WI-18): True when this execution was a searchbar
        keystroke speculation (not a real Enter-submit). Default None (absent
        in the JSON) so non-speculative traffic is unchanged — keeps the wave-7
        ``cache_hit`` field uncontaminated (a speculation that's a cache HIT is
        still cache_hit=true AND speculative=true; a fresh store is
        cache_hit=false + speculative=true). The caller (or the serve-side
        contextvar patch) sets it."""
        if not self.enabled:
            return
        qnorm = _normalize_query(query)
        qhash = _sha1(qnorm)
        oaids = result_oaids or []
        rfp = _sha1("\x1f".join(oaids)) if oaids else ""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "query_hash": qhash,
            "query_norm": qnorm[:200] if self.store_raw else "",
            "k": k,
            "mode": mode,
            "backend": backend,
            "federation": federation,
            "leg_ms": {k_: round(v, 2) for k_, v in (leg_ms or {}).items() if v is not None},
            "n_results": n_results,
            "result_fp": rfp,
            "filtered": bool(filtered),
            "session": self._session,
            "cache_hit": cache_hit,
            "speculative": speculative,
        }
        try:
            self._q.put_nowait(entry)
        except queue.Full:
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 1000 == 0:
                log.warning("serve_query_log: queue full, dropped %d entries "
                            "(buffer=%d); logging can't keep up (slow disk?)",
                            self._dropped, self._q.maxsize)


    def _open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")
        try:
            self._bytes_written = self.path.stat().st_size
        except OSError:
            self._bytes_written = 0

    def _rotate(self):
        if self._fh:
            self._fh.close()
            self._fh = None
        rot = self.path.with_suffix(self.path.suffix + ".1")
        try:
            if rot.exists():
                rot.unlink()
            self.path.rename(rot)
        except OSError as e:
            log.warning("serve_query_log: rotate failed (%s) — continuing on new file", e)
        self._open()

    def _run(self):
        self._open()
        while True:
            entry = self._q.get()
            if entry is None:
                break
            try:
                line = json.dumps(entry, ensure_ascii=False) + "\n"
                self._fh.write(line)
                self._bytes_written += len(line.encode("utf-8"))
                if self._bytes_written >= self.max_bytes:
                    self._fh.flush()
                    self._rotate()
            except Exception as e:
                log.warning("serve_query_log: write failed (%s) — entry lost", e)
        if self._fh:
            try:
                self._fh.flush()
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def close(self):
        """Best-effort shutdown: signal the writer to flush + exit. Called at
        process atexit; if the queue has pending entries they're drained (the
        sentinel drains synchronously before _run returns)."""
        if not self.enabled:
            return
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=5.0)


    def stats(self) -> dict:
        return {"enabled": self.enabled, "path": str(self.path),
                "max_bytes": self.max_bytes, "dropped": self._dropped,
                "session": self._session, "store_raw": self.store_raw}


def _normalize_query(q: str) -> str:
    """Lowercase + collapse whitespace + strip outer punctuation. The
    repeat-traffic/skew key: 'machine learning!' and ' machine  learning ' map
    to the same hash → the Q12-style analysis counts them as one subject."""
    q = (q or "").lower().strip().strip("'\".,;:!?()[]")
    return " ".join(q.split())


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()[:16]


def _rand_id() -> str:
    import secrets
    return secrets.token_hex(4)


def _int_env(name: str, default: int) -> int:
    v = os.environ.get(name)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        log.warning("serve_query_log: %s=%r not int, using %d", name, v, default)
        return default


def log_serve_query(*, query: str, k: int, mode: str, backend: str = "",
                    federation: str = "", leg_ms: dict | None = None,
                    n_results: int = 0, result_oaids: list | None = None,
                    filtered: bool = False, cache_hit: bool | None = None,
                    speculative: bool | None = None) -> None:
    """Process-wide entry point. The served path calls this once per query with
    the leg latencies it already measured + the result oaid order; this sinks
    them to the JSONL. Returns immediately (non-blocking); no-op when disabled.
    ``cache_hit`` (WI-17) flows through verbatim; pass None when the result
    cache is off so the field is absent (not False) for pre-WI-17 parity.
    ``speculative`` (WI-18) likewise — pass True for a searchbar speculation
    execution so it's marked in the log; pass None (default) for ordinary
    traffic so the field is absent."""
    QueryLogger.get().log(query=query, k=k, mode=mode, backend=backend,
                          federation=federation, leg_ms=leg_ms,
                          n_results=n_results, result_oaids=result_oaids,
                          filtered=filtered, cache_hit=cache_hit,
                          speculative=speculative)


import atexit
atexit.register(lambda: QueryLogger.get().close() if QueryLogger._instance else None)
