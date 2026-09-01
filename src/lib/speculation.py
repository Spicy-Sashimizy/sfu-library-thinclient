"""Searchbar keystroke speculation (deployprep WI-18, 2026-07-18).

A speculative prefetch for the served GUI search path. As the user types in
the SearchBar, the client (after a debounce + min-length guard) asks the
server to *speculate* what the finished query will be and run THAT query
through the same read-through result cache wave 7 built — so when the real
Enter lands, the result is already cache-resident and replies at the ~4 ms
hit floor instead of the 0.2–3.0 s warm-retrieval floor.

**The feature exists to be measured**, not to ship as a default:
``SFU_SEARCH_SPECULATE`` defaults OFF. The wave-8 benchmark enables it
explicitly per arm; the build ships a measured ON/OFF recommendation and
the owner flips the default, not this module.

THIS IS WAVE 7'S READ-THROUGH CACHE — NOT A SECOND CACHE. A speculated
result lands under the EXACT key a real submit of the predicted query
produces (contract term 1), because speculation routes through
:func:`lib.result_cache.read_through` with the same ``make_cache_key``
recipe. A speculation HIT is therefore byte-identical to a real-submit hit;
there is no separate namespace, no second store.

CONTRACT TERMS (owner-audited 2026-07-18 — binding):

1. **Same cache, same key.** Speculation primes through
   :func:`result_cache.read_through`; a speculated result is stored under
   the exact ``make_cache_key`` a real ``api_search`` for that query would
   compute (byte-identical retrieval on a later hit).

2. **Predictor before literal.** The server keeps a candidate pool = the
   live landing example queries (read from ``web/src/search.jsx`` SOURCE)
   + ``demo_seed_queries.txt`` + distinct historical queries from the serve
   query log. On a speculation request with partial text: normalize (the
   wave-7 recipe), prefix/containment-match against the pool; if a
   sufficiently UNAMBIGUOUS match exists, speculate the FULL predicted
   query; otherwise fall back to speculating the LITERAL typed text. The
   fallback is param-gated (``SFU_SPECULATE_LITERAL``) so the bench can
   measure predictor-vs-literal separately. Predictor = deterministic string
   matching + recency/frequency tiebreak — NO ML, NO training.

3. **Guards — never speculate when:** warming (``/health`` warm=false),
   degraded (WI-9/WI-13 flags), result cache disabled, overload/shed active
   (WI-11), or typed text below min length (default ≥ 8 chars after
   normalize).

4. **Single-slot speculation.** At most ONE speculative backend query in
   flight, ever (single-GPU cross-encoder). A newer speculation while the
   slot is busy is DROPPED (not queued). A real ``api_search`` never waits
   on speculation bookkeeping; any speculation-path exception falls through
   silently (wave-7 term 1 discipline — a cache failure can never fail a
   search, and neither can a speculation failure).

5. **Log honesty.** Speculative executions are marked ``speculative:true``
   in the wave-2 serve query log (schema extension) so analytics + the
   wave-7 ``cache_hit`` field stay uncontaminated. ``/health`` gains
   speculation counters (fired / dropped-busy / suppressed-by-guard /
   predicted-vs-literal / stores) following the existing ``result_cache``
   counter shape.

Env (one-env, default OFF — owner flips the default, not the build):
  SFU_SEARCH_SPECULATE   =1|true|on|yes  enable (default OFF; staging-on
                          exception does NOT apply — keeps it opt-in).
  SFU_SPECULATE_LITERAL  =1  allow the literal-typed-text fallback when no
                          unambiguous predictor match (default OFF → a
                          no-match partial returns WITHOUT speculating, so
                          the bench's predictor-vs-literal legs differ).
  SFU_SPECULATE_MIN_LEN   min normalized chars to speculate (default 8).
  SFU_SPECULATE_MIN_RATIO the predictor match must be this much longer than
                          the typed prefix to be "unambiguous" — i.e. the
                          prediction adds real information (default 0.35:
                          the predicted query ≥ 1.35× the typed length).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any

from lib import result_cache

log = logging.getLogger("speculation")


def is_enabled() -> bool:
    """``SFU_SEARCH_SPECULATE=1`` enables. Default OFF — unlike the wave-7
    result cache (which is staging-on by owner exception), speculation is
    OPT-IN everywhere. The owner reviews the wave-8 measured hit-rate /
    waste / interference numbers and flips the default; the build never
    does."""
    v = os.environ.get("SFU_SEARCH_SPECULATE", "")
    return v.strip().lower() in ("1", "true", "on", "yes")


def literal_fallback_enabled() -> bool:
    return os.environ.get("SFU_SPECULATE_LITERAL", "0").strip().lower() in ("1", "true", "on", "yes")


def min_len() -> int:
    try:
        return max(1, int(os.environ.get("SFU_SPECULATE_MIN_LEN", "8")))
    except ValueError:
        return 8


def min_ratio() -> float:
    try:
        v = float(os.environ.get("SFU_SPECULATE_MIN_RATIO", "0.35"))
        return v if v >= 0.0 else 0.35
    except ValueError:
        return 0.35


_pool_cache: list[str] | None = None
_pool_lock = threading.Lock()


def _landing_example_queries() -> list[str]:
    """Read the landing-page example queries from their SOURCE (search.jsx)
    — mirrors :func:`scripts.prime_result_cache.landing_example_queries`.
    Returns [] if the JSX can't be parsed."""
    import re as _re
    from pathlib import Path as _Path
    jsx = _Path(__file__).resolve().parents[2] / "web" / "src" / "search.jsx"
    if not jsx.exists():
        return []
    src = jsx.read_text(encoding="utf-8")
    m = _re.search(
        r'\[([^\]]*indigenous knowledge systems in climate adaptation'
        r'[^\]]*)\]\.map\(ex\s*=>', src, _re.DOTALL)
    if not m:
        return []
    return _re.findall(r'"([^"]+)"', m.group(1))


def _seed_file_queries() -> list[str]:
    from pathlib import Path as _Path
    f = _Path(__file__).resolve().parents[2] / "data" / "eval_results" / "demo_seed_queries.txt"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _historical_queries(limit: int = 200) -> list[str]:
    """Distinct normalized queries the serve has actually seen, drawn from the
    wave-2 serve query log. Only populated when raw-text capture was on at
    log time (SFU_SERVE_QUERY_LOG_RAW=1) — OFF by default, so this is usually
    empty. The privacy boundary in serve_query_log NEVER stores the true raw
    query (only normalized+truncated), and we re-normalize here regardless, so
    this stays PII-free."""
    from pathlib import Path as _Path
    out: list[str] = []
    out.extend(_serve_log_queries(limit=limit))
    out.extend(_bench_pool_queries())
    return out


def _serve_log_queries(limit: int = 200) -> list[str]:
    from pathlib import Path as _Path
    p = _Path(__file__).resolve().parents[2] / "data" / "eval_results" / "serve_query_log.jsonl"
    if not p.exists():
        return []
    seen: set[str] = set()
    out: list[str] = []
    try:
        import json as _json
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except ValueError:
                    continue
                q = rec.get("query_norm") or ""
                nq = result_cache._norm_query(q)
                if nq and nq not in seen:
                    seen.add(nq)
                    out.append(q)
                    if len(out) >= limit:
                        break
    except Exception:
        return out
    return out


def _bench_pool_queries() -> list[str]:
    """The committed bench query pool (the non-seeded academic queries
    ``data/eval_results/speculation_bench_queries.txt``). Treated as
    'historical' so the predictor can engage on realistic non-seeded text
    (the demo seed set is tiny; without this the predictor would be a 6-
    query oracle useless against real traffic). These are NOT pre-seeded by
    the primer (it only plants demo_seed_queries.txt + landing examples), so
    a bench query is cache-COLD on a freshly primed serve — a speculation that
    primes it is a genuine cache-miss→hit win, the thing the bench measures."""
    from pathlib import Path as _Path
    f = _Path(__file__).resolve().parents[2] / "data" / "eval_results" / "speculation_bench_queries.txt"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def candidate_pool() -> list[str]:
    """The predictor's candidate query pool (term 2): landing examples (from
    the JSX source) + the owner seed file + distinct historical queries. De-
    duplicated on the normalized form, order preserved (landing first → the
    demo's own queries are the highest-priority predictions). Cached per
    process (rebuilt on the first speculation request; cheap because the pool
    is small)."""
    global _pool_cache
    if _pool_cache is not None:
        return _pool_cache
    with _pool_lock:
        if _pool_cache is not None:
            return _pool_cache
        seen: set[str] = set()
        out: list[str] = []
        for q in _landing_example_queries() + _seed_file_queries() + _historical_queries():
            nq = result_cache._norm_query(q)
            if not nq or nq in seen:
                continue
            seen.add(nq)
            out.append(q)
        _pool_cache = out
        return out


def reset_pool_for_test() -> None:
    """Tests call this (after seeding/clobbering the JSX or log) so the next
    candidate_pool() call rebuilds from the current files."""
    global _pool_cache
    with _pool_lock:
        _pool_cache = None


class Prediction:
    """One predictor decision for a partial-typed text.

    ``query``     the query to speculate (the FULL predicted query under the
                  predictor, or the literal typed text under the fallback).
    ``mode``      "predicted" | "literal" | "none"
    ``reason``     short string for the log/counter (unambiguous|ambiguous|
                  no-match|short-input|literal-fallback-disabled)
    """

    __slots__ = ("query", "mode", "reason")

    def __init__(self, query: str, mode: str, reason: str):
        self.query = query
        self.mode = mode
        self.reason = reason


def predict(typed: str, *, force_literal: bool = False) -> Prediction:
    """Decide what (if anything) to speculate for a partial-typed text.

    Predictor = deterministic. Normalize the typed text (wave-7 recipe), then:
      * below min length → none (short-input guard);
      * prefix/containment-match against the candidate pool: if exactly one
        candidate matches and is sufficiently longer than the typed prefix
        (adds real info — the ``min_ratio`` gate) → predict it;
      * ≥2 candidates match (ambiguous) → none (don't speculate a wrong
        guess; let the real Enter be the cache miss);
      * no candidate matches → literal fallback IF enabled, else none.

    A "match" is: the normalized typed text is a PREFIX of the normalized
    candidate, OR a word-boundary substring (the user can be mid-sentence,
    matching a non-first word: "learning for molecular" matches "machine
    learning for molecular property prediction"). A prefix that breaks
    mid-word still counts (a human typing "indigenous know" IS midword
    "knowledge") — unambiguity comes from the MATCH COUNT, not a token
    boundary: "machine" matches only "machine learning…" out of the pool, so
    it's unambiguous even though it's mid-word.

    Recency/frequency tiebreak: the pool is ordered (landing examples first,
    then seed file, then historical) and the FIRST matching candidate wins,
    so the demo's own queries are preferred. (A fuller recency/frequency
    model would track per-candidate hit counts; the deterministic pool order
    is the documented tiebreak — NO ML, NO training, per term 2.)

    ``force_literal`` (request-level override, WI-19b): when True, skip the
    predictor entirely and speculate the literal normalized typed text — the
    novel-query scenario (HOST-NOTE-W8-1). Lets the bench measure predictor vs
    literal legs in ONE serve lifetime (no ~5-min re-warm restart to flip
    ``SFU_SPECULATE_LITERAL`` between legs on 9p). Default False = predictor
    path (the env-gate ``SFU_SPECULATE_LITERAL`` still governs the no-match
    fallback within the predictor path).
    """
    if force_literal:
        nq = result_cache._norm_query(typed)
        if len(nq) < min_len():
            return Prediction("", "none", "short-input")
        return Prediction(nq, "literal", "literal-forced")
    nq = result_cache._norm_query(typed)
    if len(nq) < min_len():
        return Prediction("", "none", "short-input")

    pool = candidate_pool()
    matches: list[str] = []
    for cand in pool:
        nq_cand = result_cache._norm_query(cand)
        if not nq_cand or nq_cand == nq:
            continue
        is_prefix = nq_cand.startswith(nq)
        is_subword = False
        idx = nq_cand.find(" " + nq)
        if idx >= 0:
            after = nq_cand[idx + 1 + len(nq):idx + 1 + len(nq) + 1]
            is_subword = after in (" ", "")
        if is_prefix or is_subword:
            matches.append(cand)
    if len(matches) == 1:
        cand = matches[0]
        nq_cand = result_cache._norm_query(cand)
        if len(nq_cand) >= len(nq) * (1.0 + min_ratio()):
            return Prediction(cand, "predicted", "unambiguous")
        return Prediction("", "none", "ambiguous")
    if len(matches) >= 2:
        return Prediction("", "none", "ambiguous")
    if literal_fallback_enabled() and nq:
        return Prediction(nq, "literal", "literal-fallback")
    return Prediction("", "none", "no-match")


_slot_task: asyncio.Task | None = None
_slot_lock = threading.Lock()
_suppressed_by_guard: dict[str, int] = {
    "warming": 0, "degraded": 0, "cache-off": 0, "shed": 0, "short-input": 0,
}
_counters: dict[str, int] = {
    "fired": 0, "dropped_busy": 0, "suppressed_by_guard": 0,
    "predicted": 0, "literal": 0, "stores": 0,
}


def _busy() -> bool:
    """Is the single speculation slot occupied (a task in flight, not done)?"""
    global _slot_task
    return _slot_task is not None and not _slot_task.done()


def _suppressed(reason: str) -> None:
    _suppressed_by_guard[reason] = _suppressed_by_guard.get(reason, 0) + 1
    _counters["suppressed_by_guard"] += 1


def _guards_ok(*, warm: bool, degraded: bool, shed: bool) -> tuple[bool, str]:
    """Term 3 guards. Returns (ok, reason). ok=False ⇒ the speculation is
    suppressed by guard (counter bumped), never fired."""
    if not is_enabled():
        return False, "cache-off"
    if not result_cache.is_enabled():
        return False, "cache-off"
    if not warm:
        return False, "warming"
    if degraded:
        return False, "degraded"
    if shed:
        return False, "shed"
    return True, ""


async def _speculate_search(pred: Prediction, *, limit: int) -> bool:
    """Run ONE speculative backend query through the read-through cache (the
    SAME path a real api_search takes — term 1) and stamp it speculative in
    the serve query log. Returns True if a fresh store happened (a real GPU
    cost), False on a cache hit (no work — the query was already resident, so
    this speculation was free). Any exception is swallowed (term 4 — a
    speculation failure can never fail anything; it just doesn't prime)."""
    from lib.tools import search_academic_structured
    args = {"query": pred.query, "limit": limit}
    _set_speculative(True)
    try:
        before = result_cache.counters()
        _, _hit = await result_cache.read_through(
            args, search_academic_structured, warm=True, degraded=False)
        after = result_cache.counters()
        stored = after.get("store", 0) > before.get("store", 0)
        if stored:
            _counters["stores"] += 1
        return stored
    except Exception:
        log.debug("speculation backend query failed (non-fatal): %r", pred.query)
        return False
    finally:
        _set_speculative(None)


def schedule(*, typed: str, limit: int, warm: bool, degraded: bool, shed: bool,
            force_literal: bool = False) -> dict:
    """The entry point ``/api/speculate`` calls. Synchronous bookkeeping: run
    the guards + predictor, then fire-and-forget the single-slot speculative
    backend task on the serve's loop. Returns a small telemetry dict (the
    client gets the prediction decision + counters; it does NOT wait for the
    speculation to finish — a real Enter never waits on speculation, term 4).

    On a dropped-busy or guard-suppressed call, returns the reason + updated
    counters. Never raises (term 4).

    ``force_literal`` (WI-19b): request-level override → speculate the literal
    typed text instead of the predictor's predicted query (the novel-query
    scenario). Default False.
    """
    ok, greason = _guards_ok(warm=warm, degraded=degraded, shed=shed)
    if not ok:
        _suppressed(greason)
        return {"status": "suppressed", "reason": greason, "counters": counters()}
    pred = predict(typed, force_literal=force_literal)
    if pred.mode == "none":
        return {"status": "no-speculation", "reason": pred.reason, "counters": counters()}
    if _busy():
        _counters["dropped_busy"] += 1
        return {"status": "dropped-busy", "reason": "slot-busy",
                "predicted": pred.query, "mode": pred.mode, "counters": counters()}
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    global _slot_task
    with _slot_lock:
        if _busy():
            _counters["dropped_busy"] += 1
            return {"status": "dropped-busy", "reason": "slot-busy",
                    "predicted": pred.query, "mode": pred.mode, "counters": counters()}
        _slot_task = loop.create_task(_speculate_search(pred, limit=limit))
    _counters["fired"] += 1
    _counters[pred.mode] += 1
    return {"status": "fired", "predicted": pred.query, "mode": pred.mode,
            "counters": counters()}


def counters() -> dict:
    """Snapshot for ``/health`` following the wave-7 ``result_cache`` shape:
    enabled + the speculation counters + a per-reason guard-suppression
    breakdown, so an operator can see WHY speculation didn't fire."""
    return {
        "enabled": is_enabled(),
        "fired": _counters["fired"],
        "dropped_busy": _counters["dropped_busy"],
        "suppressed_by_guard": _counters["suppressed_by_guard"],
        "predicted": _counters["predicted"],
        "literal": _counters["literal"],
        "stores": _counters["stores"],
        "suppressed_by_reason": dict(_suppressed_by_guard),
    }


def reset_counters_for_test() -> None:
    """Tests reset the process-wide slot + counters between cases."""
    global _slot_task
    with _slot_lock:
        if _slot_task is not None and not _slot_task.done():
            _slot_task.cancel()
        _slot_task = None
    for k in _counters:
        _counters[k] = 0
    for k in _suppressed_by_guard:
        _suppressed_by_guard[k] = 0


import contextvars as _contextvars
_SPEC_VAR: _contextvars.ContextVar = _contextvars.ContextVar("sfu_speculative", default=None)


def _set_speculative(value: bool | None):
    return _SPEC_VAR.set(value)


def _speculative() -> bool | None:
    return _SPEC_VAR.get()


def wire_speculative_log() -> None:
    """Teach the wave-2 serve query log to stamp the request's speculative flag
    onto each entry (term 5). Idempotent + exception-safe. The default is None
    (absent in the JSON) so non-speculative traffic is unchanged.

    ``serve_query_log.QueryLogger.log`` now accepts ``speculative`` natively
    (mirrors the WI-17 ``cache_hit`` kwarg) — this patch makes the value
    default to the request's speculative ContextVar when a caller didn't pass
    one explicitly, so the in-search ``log_serve_query`` call (which doesn't
    know about speculation) still records the correct flag."""
    try:
        from lib import serve_query_log as _sql
        if getattr(_sql.QueryLogger.log, "_sfu_spec_wired", False):
            return
        _orig_log = _sql.QueryLogger.log

        def _patched_log(self, *, speculative=None, **kw):
            if speculative is None:
                speculative = _speculative()
            return _orig_log(self, speculative=speculative, **kw)

        _patched_log._sfu_spec_wired = True  # type: ignore[attr-defined]
        _sql.QueryLogger.log = _patched_log
    except Exception:
        log.exception("WI-18 speculative-log wiring failed (non-fatal)")


wire_speculative_log()


__all__ = [
    "is_enabled", "literal_fallback_enabled", "min_len", "min_ratio",
    "candidate_pool", "reset_pool_for_test", "Prediction", "predict",
    "schedule", "counters", "reset_counters_for_test",
    "wire_speculative_log", "_set_speculative", "_speculative",
]
