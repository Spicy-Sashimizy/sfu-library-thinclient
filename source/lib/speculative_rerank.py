"""Speculative rerank work on the BM25F draft (lever #1, SPECULATIVE_RETRIEVAL_UPGRADES.md).

Gate: ``SFU_SEARCH_SPECULATIVE_RERANK`` — literal ``1`` enables, anything
else (including unset) leaves every code path exactly as it was.

Draft / verify shape:

* **Draft.** In the LOCAL_RRF path of ``FederatedSearchRouter.search`` the
  BM25F leg returns first. :func:`on_draft` hands its hydrated top-k to one
  background worker, which runs the real serve rerank pipeline
  (``lib.tools._maybe_rerank_impl``) over the pool the router *would* return
  if the SPLADE leg added nothing (``_rrf_merge(bm25f, [], top_k)``). While it
  runs, every model call the pipeline makes — the stage-1
  ``compute_similarity`` batch and the cross-encoder batch — is recorded as a
  future together with the items it scores.
* **Early CE.** The CE pair text is a function of (query, doc) only, not of
  the stage-1 order, so when the cross-encoder is enabled the job starts the
  draft CE batch over the pool (``rerank_with_crossencoder`` on its own
  thread) at the same moment as the stage-1 embedding instead of after it.
  The two drafted calls are independent futures; the real pass consumes
  whichever is recorded, each on its own. When the pipeline's own CE call
  in the draft is reached and the early batch already scored every pair it
  needs, the draft ends there (``draft_ce_covered``) instead of scoring the
  same pairs twice.
* **Verify.** After fusion the router :func:`bind`\\ s the draft to the fused
  list. The real ``_maybe_rerank`` then runs the unchanged pipeline inside
  :func:`consume`; each model call first looks up every item it needs (a
  document text for stage-1, a (query, text) pair for the CE) in the draft's
  recorded calls with the same query and model. Drafted items are reused
  (waiting for the recorded call if it is still in flight); only the
  remainder is scored, and the scores are spliced back in request order.

Parity strategy (§5 risk 1, owner decision 2026-09-25): **per-candidate reuse
over fixed-shape scoring.** ``lib.embedding.encode_texts`` and
``lib.reranker._ce_score_pairs`` score in constant (batch, seq_len) tensors
with dummy rows filling a short batch, on the gate-off and gate-on paths
alike, so one item's score is a pure function of (query, item, model) and does
not depend on which other items share its call. A drafted score spliced into
a fused request is therefore bit-identical to the score the gate-off path
computes for it. See ``docs/CODE_INVARIANTS.md`` ("Fixed-shape scoring" and
this module's subsection).

Single CE slot (WI-18 term 4 discipline): at most one draft job in flight
process-wide (a new draft while busy is dropped, never queued); a draft CE
batch starts only when no real CE pass is active, and a real CE pass that
arrives while a draft batch runs waits for that one batch. The early CE
batch and the pipeline's own draft CE call never overlap: the latter waits
for the early batch to finish and only runs if it did not cover its pairs. Every failure in
this module is swallowed: a speculation failure never fails a search.
"""
from __future__ import annotations

import contextvars
import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import Future
from typing import Any, Callable

log = logging.getLogger("sfu_library_mcp")

GATE_ENV = "SFU_SEARCH_SPECULATIVE_RERANK"

_REGISTRY_MAX = 32
_WAIT_TIMEOUT_S = 30.0

_CTX: contextvars.ContextVar = contextvars.ContextVar("sfu_speculative_rerank", default=None)

_counters_lock = threading.Lock()
_counters: dict[str, int] = {
    "drafts_started": 0,
    "dropped_busy": 0,
    "skipped_rerank_off": 0,
    "job_errors": 0,
    "abandoned": 0,
    "bound": 0,
    "consumed_with_draft": 0,
    "candidates_drafted": 0,
    "candidates_accepted": 0,
    "embed_hits": 0,
    "embed_misses": 0,
    "embed_calls_skipped": 0,
    "ce_hits": 0,
    "ce_misses": 0,
    "ce_calls_skipped": 0,
    "draft_ce_dropped_slot": 0,
    "draft_ce_batches": 0,
    "draft_ce_early": 0,
    "draft_ce_covered": 0,
    "real_ce_waited": 0,
}


def is_enabled() -> bool:
    """Literal ``1`` enables; unset or any other value is OFF."""
    return os.environ.get(GATE_ENV, "0") == "1"


def _bump(name: str, n: int = 1) -> None:
    with _counters_lock:
        _counters[name] = _counters.get(name, 0) + n


def counters() -> dict:
    """Snapshot for a ``/health``-style panel."""
    with _counters_lock:
        snap = dict(_counters)
    snap["enabled"] = is_enabled()
    return snap


class _Abandon(BaseException):
    """Stops a draft job without counting an error.

    A BaseException so the pipeline's own ``except Exception`` fallbacks do
    not swallow it and carry on (and log) inside the draft thread.
    """


class _Covered(BaseException):
    """Ends the draft's pipeline at its CE call when the early CE batch covered it."""


class _CeSlot:
    """Single CE slot shared by draft batches and real passes.

    Real passes may overlap each other (the gate-off path already allows
    that); a draft batch is exclusive with every real pass.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._real_active = 0
        self._draft_running = False

    def try_draft(self) -> bool:
        with self._cond:
            if self._draft_running or self._real_active:
                return False
            self._draft_running = True
            return True

    def release_draft(self) -> None:
        with self._cond:
            self._draft_running = False
            self._cond.notify_all()

    def enter_real(self) -> None:
        with self._cond:
            if self._draft_running:
                _bump("real_ce_waited")
            while self._draft_running:
                self._cond.wait()
            self._real_active += 1

    def exit_real(self) -> None:
        with self._cond:
            self._real_active -= 1
            self._cond.notify_all()


CE_SLOT = _CeSlot()


class DraftHandle:
    """Per-request draft state: recorded model calls plus lifecycle flags."""

    def __init__(self, query: str, pool: list[dict], top_k: int) -> None:
        self.query = query
        self.pool = pool
        self.top_k = top_k
        self.closed = False
        self.done = threading.Event()
        self._lock = threading.Lock()
        self._calls: list[tuple[tuple, tuple, Future]] = []

    def register(self, key: tuple, items: tuple) -> Future | None:
        with self._lock:
            if self.closed:
                return None
            fut: Future = Future()
            self._calls.append((key, items, fut))
            return fut

    def calls_for(self, key: tuple) -> list[tuple[tuple, Future]]:
        with self._lock:
            return [(items, fut) for k, items, fut in self._calls if k == key]

    def close(self) -> None:
        with self._lock:
            self.closed = True


class _RecordCtx:
    """Context active inside a draft job: computes and publishes each call."""

    def __init__(self, handle: DraftHandle, early_ce: threading.Event | None = None,
                 is_early: bool = False) -> None:
        self.handle = handle
        self.early_ce = early_ce
        self.is_early = is_early

    def _publish(self, key: tuple, items: tuple, compute: Callable[[], Any]) -> Any:
        fut = self.handle.register(key, items)
        if fut is None:
            raise _Abandon()
        try:
            value = compute()
        except BaseException as exc:
            fut.set_exception(exc)
            raise
        fut.set_result(value)
        return value

    def similarity(self, fn: Callable, query: str, texts: list[str], model_path: Any) -> Any:
        return self._publish(("embed", query, model_path), tuple(texts),
                             lambda: fn(query, texts, model_path))

    def _covered(self, ce: Any, pairs: list[tuple]) -> bool:
        wanted = set(pairs)
        for items, fut in self.handle.calls_for(("ce", id(ce))):
            if fut.done() and fut.exception() is None and wanted.issubset(items):
                return True
        return False

    def ce_scores(self, ce: Any, pairs: list[tuple], compute: Callable[[list], Any]) -> Any:
        if self.early_ce is not None:
            self.early_ce.wait(_WAIT_TIMEOUT_S)
            if self._covered(ce, pairs):
                raise _Covered()
        if self.handle.closed:
            raise _Abandon()
        if not CE_SLOT.try_draft():
            _bump("draft_ce_dropped_slot")
            raise _Abandon()
        try:
            fut = self.handle.register(("ce", id(ce)), tuple(pairs))
            if fut is None:
                raise _Abandon()
            _bump("draft_ce_batches")
            if self.is_early:
                _bump("draft_ce_early")
            try:
                value = compute(list(pairs))
            except BaseException as exc:
                fut.set_exception(exc)
                raise
            fut.set_result(value)
            return value
        finally:
            CE_SLOT.release_draft()


class _ConsumeCtx:
    """Context active inside the real ``_maybe_rerank``: per-candidate reuse."""

    def __init__(self, handle: DraftHandle | None) -> None:
        self.handle = handle

    def _drafted(self, key: tuple, wanted: set) -> dict:
        """Item -> drafted score for every wanted item a recorded call scored."""
        found: dict = {}
        if self.handle is None:
            return found
        for items, fut in self.handle.calls_for(key):
            if not wanted.intersection(items):
                continue
            try:
                value = fut.result(timeout=_WAIT_TIMEOUT_S)
            except Exception:
                continue
            if value is None or len(value) != len(items):
                continue
            for item, score in zip(items, value):
                if item in wanted and item not in found:
                    found[item] = score
        return found

    def _splice(self, key: tuple, items: list, compute: Callable[[list], Any],
                hit: str, miss: str, skipped: str) -> Any:
        drafted = self._drafted(key, set(items))
        remainder: list = []
        seen: set = set()
        for item in items:
            if item not in drafted and item not in seen:
                seen.add(item)
                remainder.append(item)
        computed: dict = {}
        if remainder:
            fresh = compute(remainder)
            if fresh is None or len(fresh) != len(remainder):
                _bump(miss, len(items))
                return fresh
            computed = dict(zip(remainder, fresh))
        else:
            _bump(skipped)
        n_hit = sum(1 for item in items if item in drafted)
        _bump(hit, n_hit)
        _bump(miss, len(items) - n_hit)
        return [drafted[item] if item in drafted else computed[item] for item in items]

    def similarity(self, fn: Callable, query: str, texts: list[str], model_path: Any) -> Any:
        return self._splice(("embed", query, model_path), list(texts),
                            lambda sub: fn(query, sub, model_path),
                            "embed_hits", "embed_misses", "embed_calls_skipped")

    def ce_scores(self, ce: Any, pairs: list[tuple], compute: Callable[[list], Any]) -> Any:
        CE_SLOT.enter_real()
        try:
            return self._splice(("ce", id(ce)), list(pairs), compute,
                                "ce_hits", "ce_misses", "ce_calls_skipped")
        finally:
            CE_SLOT.exit_real()


def current() -> Any:
    """The active record/consume context, or None (always None when gated off)."""
    return _CTX.get()


_job_lock = threading.Lock()
_job_busy = False
_registry_lock = threading.Lock()
_registry: "OrderedDict[int, tuple[list, DraftHandle]]" = OrderedDict()


def _pipeline() -> tuple[Callable, dict]:
    from lib import tools
    return tools._maybe_rerank_impl, tools._get_features()


def _run_early_ce(handle: DraftHandle, done: threading.Event) -> None:
    """Draft CE batch over the whole pool, started alongside the stage-1 draft."""
    token = _CTX.set(_RecordCtx(handle, is_early=True))
    try:
        from lib import reranker
        if handle.closed:
            raise _Abandon()
        reranker.rerank_with_crossencoder(handle.pool, handle.query, reranker._CE_CANDIDATE_POOL)
    except _Abandon:
        pass
    except Exception:
        _bump("job_errors")
        log.debug("speculative rerank early CE failed (non-fatal)", exc_info=True)
    finally:
        _CTX.reset(token)
        done.set()


def _start_early_ce(handle: DraftHandle, features: dict) -> tuple[threading.Thread | None, threading.Event | None]:
    if not features.get("crossencoder_enabled"):
        return None, None
    done = threading.Event()
    try:
        thread = threading.Thread(
            target=_run_early_ce, args=(handle, done), name="sfu-spec-rerank-ce", daemon=True)
        thread.start()
    except Exception:
        log.debug("speculative rerank early CE not started (non-fatal)", exc_info=True)
        return None, None
    return thread, done


def _run_job(handle: DraftHandle) -> None:
    global _job_busy
    ce_thread = None
    token = None
    try:
        impl, features = _pipeline()
        if handle.closed:
            raise _Abandon()
        ce_thread, ce_done = _start_early_ce(handle, features)
        token = _CTX.set(_RecordCtx(handle, ce_done))
        impl(handle.pool, handle.query, handle.top_k)
    except _Covered:
        _bump("draft_ce_covered")
    except _Abandon:
        _bump("abandoned")
    except Exception:
        _bump("job_errors")
        log.debug("speculative rerank draft failed (non-fatal)", exc_info=True)
    finally:
        if token is not None:
            _CTX.reset(token)
        if ce_thread is not None:
            ce_thread.join(_WAIT_TIMEOUT_S)
        handle.close()
        handle.done.set()
        with _job_lock:
            _job_busy = False


def on_draft(query: str, bm25f_results: list[dict], top_k: int) -> DraftHandle | None:
    """Start the draft job for the BM25F leg's results. Never raises.

    Returns None when gated off, when reranking is disabled, when the draft is
    empty, or when the single draft slot is busy (dropped, not queued).
    """
    global _job_busy
    try:
        if not is_enabled() or not bm25f_results:
            return None
        _impl, features = _pipeline()
        if not features.get("rerank_enabled"):
            _bump("skipped_rerank_off")
            return None
        from lib.federated_search import _rrf_merge
        pool = _rrf_merge(bm25f_results, [], top_k)
        if not pool:
            return None
        with _job_lock:
            if _job_busy:
                _bump("dropped_busy")
                return None
            _job_busy = True
        handle = DraftHandle(query, pool, top_k)
        try:
            thread = threading.Thread(
                target=_run_job, args=(handle,), name="sfu-spec-rerank", daemon=True)
            thread.start()
        except Exception:
            with _job_lock:
                _job_busy = False
            raise
        _bump("drafts_started")
        _bump("candidates_drafted", len(pool))
        return handle
    except Exception:
        log.debug("speculative rerank on_draft failed (non-fatal)", exc_info=True)
        return None


def _doc_key(doc: dict) -> str:
    from lib.federated_search import _normalize_doi
    return _normalize_doi(doc.get("doi", "")) or doc.get("openalex_id", "") or doc.get("title", "")


def bind(handle: DraftHandle | None, fused: list[dict]) -> None:
    """Attach a draft to the fused list the router is about to return. Never raises."""
    if handle is None:
        return
    try:
        fused_keys = {_doc_key(d) for d in fused}
        accepted = sum(1 for d in handle.pool if _doc_key(d) in fused_keys)
        _bump("candidates_accepted", accepted)
        with _registry_lock:
            _registry[id(fused)] = (fused, handle)
            while len(_registry) > _REGISTRY_MAX:
                _old_list, old_handle = _registry.popitem(last=False)[1]
                old_handle.close()
        _bump("bound")
    except Exception:
        log.debug("speculative rerank bind failed (non-fatal)", exc_info=True)


def _take(docs: list[dict]) -> DraftHandle | None:
    with _registry_lock:
        entry = _registry.get(id(docs))
        if entry is None or entry[0] is not docs:
            return None
        del _registry[id(docs)]
    return entry[1]


class consume:
    """Context manager wrapping the real ``_maybe_rerank`` when gated on."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self._token = None

    def __enter__(self) -> "consume":
        if _CTX.get() is not None:
            return self
        handle = None
        try:
            handle = _take(self._docs)
            if handle is not None:
                handle.close()
                _bump("consumed_with_draft")
        except Exception:
            handle = None
        self._token = _CTX.set(_ConsumeCtx(handle))
        return self

    def __exit__(self, *exc: Any) -> bool:
        if self._token is not None:
            _CTX.reset(self._token)
            self._token = None
        return False


def reset_for_test() -> None:
    """Clear counters, registry and the busy flag between test cases."""
    global _job_busy
    with _counters_lock:
        for k in _counters:
            _counters[k] = 0
    with _registry_lock:
        _registry.clear()
    with _job_lock:
        _job_busy = False


__all__ = [
    "GATE_ENV", "is_enabled", "counters", "current", "on_draft", "bind",
    "consume", "DraftHandle", "CE_SLOT", "reset_for_test",
]
