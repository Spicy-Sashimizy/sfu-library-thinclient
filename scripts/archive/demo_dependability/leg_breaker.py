#!/usr/bin/env python3
# CLOSED DEAD 2026-09-25 — demo-dependability WI harness for the OCI deployment that was gone on 2026-09-25 (docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md); evidence kept, bars live in source at pinned commits
"""WI-9 (deployprep wave 3, 2026-07-17) — leg-level graceful degradation +
circuit breaker for the staging serve. STAGING ONLY (env-gated OFF by default).

THE GAP THIS CLOSES (the wave-3 drive prompt WI-9): today a dead/hung leg fails
the WHOLE query. The served path is `ThinClientRetriever.search_rrf` — 3 legs
(BM25F/tantivy + SPLADE/SEISMIC-8-shard + dense/usearch) RRF-fused. The retriever
ALREADY degrades SPLADE/encoder failure to a BM25F mirror silently
(`_splade_leg_seismic` → `_bm25f_leg` on exception) — but:

  - there is NO per-leg timeout, so a HUNG leg (a wedged pyseismic `.search`,
    a stuck ONNX encode) hangs the whole query until the client times out;
  - there is NO circuit breaker, so a persistently-failing leg is retried every
    query (the failure cost paid N times, not once);
  - the BM25F leg throwing (a tantivy corruptions, a section load) → the whole
    `search_rrf` raises → the staging serve returns 500 (a 5xx storm under load);
  - the degrade is SILENT — the client/health can't tell a leg is down.

`LegGuardian` adds, env-gated behind `SFU_DEMO_LEG_BREAKER=1` (default OFF =
byte-identical to wave-1 behavior — the served path is never changed unless a
staging run opts in):

  - **per-leg timeout budget** (`SFU_DEMO_LEG_TIMEOUT_S`, default 30): each leg
    runs in a worker thread; if it exceeds the budget it is treated as failed
    (the hung-leg case). BM25F + dense share the budget; the SPLADE leg (the
    8-shard federation) gets `SFU_DEMO_LEG_TIMEOUT_SPLADE_S` (default = the same
    budget) since it is structurally the slowest.
  - **circuit breaker** (`SFU_DEMO_LEG_BREAKER_N`, default 3 consecutive fails →
    OPEN): once a leg fails N times in a row it is marked OPEN (skipped — returns
    `[]` immediately, no call made) for `SFU_DEMO_LEG_BREAKER_COOLDOWN_S`
    (default 8). After cooldown one PROBE query re-admits it; a probe failure
    re-arms the cooldown, a probe success CLOSES the breaker.
  - **RRF over surviving legs**: `search_rrf_degraded` drops the OPEN leg's
    contribution entirely and fuses the rest; RRF is rank-based so dropping a leg
    just removes its vote (the surviving legs' rankings re-weight naturally).
  - **`degraded` surface**: every search returns `degraded: [leg,...]` (the legs
    currently OPEN or that failed THIS query); `/health` gains a `degraded` state
    between `ok` and `dead` so the monitor sees a partly-down serve (not green,
    not red — amber).

The encoder-down contract: `_encode_splade_top` failure already returns None →
the SPLADE leg mirrors BM25F. The guardian treats a mirrored/empty SPLADE leg as
NOT-failed (it still returned results — the mirror is a successful degrade), so
the breaker only trips on a leg that threw or timed out, not on a graceful
mirror. The guardian NEVER touches scoring or the merge — it only gates whether
a leg's result list is used. T1-parity-irrelevant (it is a serve-layer gate, not
a federation/merge change), and OFF by default so the parity harnesses are
byte-identical.

Owner constraints (2026-07-16): staging/prep only; no public deploy, no spend.
"""
import os
import threading
import time


def breaker_enabled() -> bool:
    return os.environ.get("SFU_DEMO_LEG_BREAKER", "0") == "1"

def leg_timeout_s(leg: str) -> float:
    base = float(os.environ.get("SFU_DEMO_LEG_TIMEOUT_S", "30"))
    if leg == "splade":
        s = os.environ.get("SFU_DEMO_LEG_TIMEOUT_SPLADE_S")
        if s:
            try:
                return float(s)
            except ValueError:
                pass
    return base

BREAKER_N = lambda: int(os.environ.get("SFU_DEMO_LEG_BREAKER_N", "3"))
COOLDOWN_S = lambda: float(os.environ.get("SFU_DEMO_LEG_BREAKER_COOLDOWN_S", "8"))


class _LegState:
    """Per-leg breaker state. The breaker is CLOSED (calls go through) until N
    consecutive failures → OPEN (calls short-circuit to [] for cooldown) → after
    cooldown one HALF-OPEN probe is allowed (a success closes, a fail re-opens).
    Thread-safe (the staging serve is a ThreadingHTTPServer)."""

    __slots__ = ("leg", "consec_fails", "opened_at", "probe_pending",
                 "last_fail_reason", "_lock")

    def __init__(self, leg: str):
        self.leg = leg
        self.consec_fails = 0
        self.opened_at: float | None = None
        self.probe_pending = False
        self.last_fail_reason: str | None = None
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            return {"consec_fails": self.consec_fails,
                    "open": self.opened_at is not None,
                    "probe_pending": self.probe_pending,
                    "last_fail_reason": self.last_fail_reason}

    def is_open(self) -> bool:
        """True if the leg should be SKIPPED this query (open + still in cooldown,
        OR open + a probe is already in flight). Sets probe_pending when the
        cooldown has elapsed (the next call is the probe)."""
        with self._lock:
            if self.opened_at is None:
                return False
            if self.probe_pending:
                return True
            elapsed = time.monotonic() - self.opened_at
            if elapsed >= COOLDOWN_S():
                self.probe_pending = True
                return False
            return True

    def is_degraded_report(self) -> bool:
        """Whether the leg is in the STEADY-STATE degraded set for /health + the
        `degraded` response flag. Distinct from `is_open()` (the skip decision):
        this does NOT trip probe_pending and does NOT count a probe that the
        current query is itself conducting (a probe-in-flight is a re-admission
        IN PROGRESS, not a still-down leg). So a leg whose cooldown just elapsed
        and is being probed THIS query reports NOT degraded — the bar 'breaker
        recovers' sees the leg clear the moment it is being re-admitted."""
        with self._lock:
            if self.opened_at is None:
                return False
            if self.probe_pending:
                return False
            return (time.monotonic() - self.opened_at) < COOLDOWN_S()

    def on_success(self):
        with self._lock:
            self.consec_fails = 0
            self.opened_at = None
            self.probe_pending = False
            self.last_fail_reason = None

    def on_fail(self, reason: str):
        with self._lock:
            if self.probe_pending:
                self.opened_at = time.monotonic()
                self.probe_pending = False
                self.last_fail_reason = reason
                return
            self.consec_fails += 1
            self.last_fail_reason = reason
            if self.consec_fails >= BREAKER_N():
                self.opened_at = time.monotonic()
                self.probe_pending = False


class LegGuardian:
    """Wraps each leg callable with a timeout + circuit breaker. OFF → the
    retriever's own `search_rrf` is called unchanged (guardian is a no-op). ON →
    `search_rrf_degraded` runs each leg under the guardian and reports which legs
    are degraded (OPEN or failed-this-query)."""

    def __init__(self, retriever):
        self.r = retriever
        self._states = {leg: _LegState(leg) for leg in ("bm25f", "splade", "dense")}


    def states_snapshot(self) -> dict:
        return {leg: st.snapshot() for leg, st in self._states.items()}

    def degraded_legs(self) -> list[str]:
        """Legs currently in the steady-state degraded set (OPEN + still in
        cooldown, NOT a probe-in-flight). Surfaced to /health + the `degraded`
        response flag. Uses `is_degraded_report` (not `is_open`, which is the
        skip-decision + trips probe_pending)."""
        return sorted(leg for leg, st in self._states.items()
                      if st.is_degraded_report())

    def search_rrf_degraded(self, query: str, top_k: int = 50,
                           include_dense: bool = True,
                           filters: dict | None = None) -> dict:
        """3-leg RRF with per-leg timeout + breaker. Returns
        `{results, ms, degraded: [legs failed/OPEN this query]}`.

        A leg that is OPEN (breaker tripped + still in cooldown) is skipped — its
        result list is `[]` (no RRF vote). A leg that times out or throws counts
        as a failure (feeds the breaker). The BM25F leg failing is NOT fatal here:
        the query still answers from SPLADE+dense (degraded), instead of a 5xx."""
        from lib.thinclient.retriever import RRF_K
        leg_results: dict[str, list] = {}
        failed_this_query: list[str] = []
        legs = [("bm25f", lambda: self.r.search(query, top_k, mode="bm25f", filters=filters)),
                ("splade", lambda: self.r.search(query, top_k, mode="splade", filters=filters))]
        if include_dense and getattr(self.r, "_dense", None):
            legs.append(("dense", lambda: self.r.dense_search(query, top_k, filters=filters)))
        holders: dict[str, dict] = {leg: {} for leg, _ in legs}
        def _run_into(leg, fn, h):
            h["res"] = self._run_leg(leg, fn)
        orch = []
        for leg, fn in legs:
            t = threading.Thread(target=_run_into, args=(leg, fn, holders[leg]),
                                 name=f"leg-orch-{leg}", daemon=True)
            t.start(); orch.append((leg, t))
        for leg, t in orch:
            t.join()
            ok, payload = holders[leg].get("res", (False, "no-result"))
            if ok:
                leg_results[leg] = payload
            else:
                failed_this_query.append(leg)
                leg_results[leg] = []
        degraded = sorted(set(failed_this_query) | set(self.degraded_legs()))
        scores: dict[str, float] = {}
        by_id: dict[str, dict] = {}
        for leg, res in leg_results.items():
            for rank, doc in enumerate(res, start=1):
                did = doc["openalex_id"]
                scores[did] = scores.get(did, 0.0) + 1.0 / (RRF_K + rank)
                by_id.setdefault(did, doc)
        out = []
        for did in sorted(scores, key=lambda d: scores[did], reverse=True)[:top_k]:
            doc = dict(by_id[did])
            doc["score"] = scores[did]
            doc["source"] = "thinclient_rrf_degraded"
            out.append(doc)
        return {"results": out, "degraded": degraded}


    def _run_leg(self, leg: str, fn) -> tuple[bool, object]:
        """Run one leg under the breaker + timeout. Returns (ok, results) or
        (False, reason_str). OPEN → immediate (False, 'breaker_open').

        Uses a DEDICATED daemon thread per call (not a shared executor) so a hung
        leg's abandoned worker can NEVER starve another leg's worker — the WI-9
        first-attempt bug where a 60s hung SPLADE thread made BM25F/dense queue
        behind it + time out too (all 3 degraded). The abandoned thread dies on
        process exit (daemon); the request returns degraded, the serve stays up."""
        st = self._states[leg]
        if st.is_open():
            return False, "breaker_open"
        holder: dict = {}
        def _worker():
            try:
                holder["res"] = fn()
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    holder["exc"] = exc; return
                holder["exc"] = exc
        th = threading.Thread(target=_worker, name=f"leg-{leg}", daemon=True)
        th.start()
        th.join(timeout=leg_timeout_s(leg))
        if th.is_alive():
            st.on_fail("timeout")
            return False, "timeout"
        if "exc" in holder:
            exc = holder["exc"]
            st.on_fail(f"{type(exc).__name__}: {str(exc)[:80]}")
            return False, f"{type(exc).__name__}: {str(exc)[:80]}"
        st.on_success()
        return True, holder.get("res")


_GUARDIAN: LegGuardian | None = None
_GUARDIAN_LOCK = threading.Lock()


def get_guardian(retriever) -> LegGuardian | None:
    """Lazily build the guardian the first time the staging serve needs it. OFF
    (SFU_DEMO_LEG_BREAKER unset) → None, and the serve calls the retriever's own
    `search_rrf` unchanged (wave-1 behavior)."""
    global _GUARDIAN
    if not breaker_enabled():
        return None
    with _GUARDIAN_LOCK:
        if _GUARDIAN is None:
            _GUARDIAN = LegGuardian(retriever)
        return _GUARDIAN
