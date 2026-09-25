"""Speculative rerank (lever #1, SFU_SEARCH_SPECULATIVE_RERANK) — parity + slot tests.

The fake embedder forward (``lib.embedding._embed_batch``) and the fake
cross-encoder model a transformer's float behaviour: every row is shifted by
an amount derived from the padded tensor shape of its call, large enough to
reorder candidates when rows from two differently shaped calls are mixed.
With ``fixed_shape=True`` the fake's "tokenizer" pads to a constant length,
so the shape is (batch, constant) and the chunking in
``encode_texts`` / ``_ce_score_pairs`` (constant batch, dummy-filled) makes
every row's score a pure function of its own input. With
``fixed_shape=False`` the fake pads to the longest input in the call, as the
pre-2026-09-25 path did, and per-candidate reuse visibly breaks parity
(``test_per_candidate_reuse_breaks_without_fixed_shape``). So the parity
tests pass because of fixed shape, not because the fakes are lenient.
"""

import contextlib
import hashlib
import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

import lib.embedding
from lib import reranker, speculative_rerank, speculation, result_cache
from lib import tools
from lib.federated_search import FederatedSearchRouter, SearchSource

_REAL_COMPUTE_SIMILARITY = lib.embedding.compute_similarity


def _h(s: str) -> float:
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _shape_shift(n_rows: int, lengths, fixed_shape: bool) -> float:
    """Fixed: shape is (n_rows, constant). Otherwise model the pre-2026-09-25
    call: no dummy rows (zero-length inputs) and padding to the longest."""
    if fixed_shape:
        return _h(f"shape|{n_rows}|FIXED")
    real = [n for n in lengths if n]
    return _h(f"shape|{len(real)}|{max(real, default=0)}")


_DIM = 8


def _vec(text: str) -> np.ndarray:
    return np.array([_h(f"{text}#{k}") for k in range(_DIM)]) * 0.1


class FakeEmbed:
    """Spy on ``compute_similarity`` + fake fixed/longest-padded encoder forward."""

    def __init__(self, fail_off_main=False, gate=None, fixed_shape=True):
        self.calls = []
        self.batches = []
        self.ctx_seen = []
        self.spec_flag_seen = []
        self.fail_off_main = fail_off_main
        self.gate = gate
        self.fixed_shape = fixed_shape
        self._lock = threading.Lock()

    def __call__(self, query, texts, model_path=None):
        off_main = threading.current_thread() is not threading.main_thread()
        with self._lock:
            self.calls.append((query, tuple(texts), model_path, off_main))
            self.ctx_seen.append(speculative_rerank.current())
            self.spec_flag_seen.append(speculation._speculative())
        if self.gate is not None and off_main:
            self.gate.wait(5)
        if self.fail_off_main and off_main:
            raise RuntimeError("draft embedder boom")
        return _REAL_COMPUTE_SIMILARITY(query, texts, model_path)

    def forward(self, model, texts):
        with self._lock:
            self.batches.append(tuple(texts))
        shift = _shape_shift(len(texts), [len(t) for t in texts], self.fixed_shape) * 0.9
        return np.stack([_vec(t) + shift for t in texts]).astype(np.float32)


class FakeCE:
    """CrossEncoder stand-in: per-pair logit + a shift derived from the call's padded shape."""

    def __init__(self, block=None, fixed_shape=True):
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.block = block
        self.fixed_shape = fixed_shape
        self._lock = threading.Lock()

    def predict(self, pairs, show_progress_bar=False):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append((tuple(pairs),
                               threading.current_thread() is not threading.main_thread()))
        try:
            if self.block is not None and threading.current_thread() is not threading.main_thread():
                self.block.wait(5)
            shift = _shape_shift(len(pairs), [len(q) + len(t) for q, t in pairs],
                                 self.fixed_shape) * 3.0
            return np.array([_h(q + t) + shift for q, t in pairs])
        finally:
            with self._lock:
                self.active -= 1


def _doc(i, tag=""):
    return {
        "openalex_id": f"W{i}",
        "doi": f"https://doi.org/10.1/{i}",
        "title": f"Paper {i} on topic {tag}{i % 7}",
        "abstract": f"Abstract {i} " + "words " * (i % 11),
        "date": str(2000 + i % 25),
        "type": "article" if i % 3 else "book",
        "authors": ["A"] if i % 2 else [],
        "is_oa": bool(i % 4),
        "oa_url": "",
        "cited_by_count": i,
    }


class FakeRetriever:
    def __init__(self, bm25f, splade, splade_raises=False, wait_for_draft=True,
                 with_scope=False):
        self.bm25f = bm25f
        self.splade = splade
        self.splade_raises = splade_raises
        self.wait_for_draft = wait_for_draft
        self.search_calls = []
        self.scope_enters = 0
        self.scope_exits = 0
        self._in_scope = False
        if with_scope:
            self.hydrate_scope = self._hydrate_scope

    @contextlib.contextmanager
    def _hydrate_scope(self):
        self.scope_enters += 1
        self._in_scope = True
        try:
            yield None
        finally:
            self._in_scope = False
            self.scope_exits += 1

    def search(self, query, top_k=50, mode="bm25f", filters=None):
        self.search_calls.append((mode, self._in_scope))
        if mode == "bm25f":
            return [dict(d) for d in self.bm25f[:top_k]]
        if self.wait_for_draft:
            deadline = time.monotonic() + 5
            while speculative_rerank._job_busy and time.monotonic() < deadline:
                time.sleep(0.002)
        if self.splade_raises:
            raise RuntimeError("splade down")
        return [dict(d) for d in self.splade[:top_k]]


FEATURES = {"rerank_enabled": True, "crossencoder_enabled": True,
            "lambdamart_enabled": False, "rrf_enabled": False}
CFG = SimpleNamespace(embedding_model_path="", lambdamart_model_path="")


def _install_embed(monkeypatch, embed):
    monkeypatch.setattr(lib.embedding, "_load_model", lambda model_path=None: object())
    monkeypatch.setattr(lib.embedding, "_embed_batch", embed.forward)
    monkeypatch.setattr(lib.embedding, "compute_similarity", embed)


def _install(env, fixed_shape):
    env.embed = FakeEmbed(fixed_shape=fixed_shape)
    env.ce = FakeCE(fixed_shape=fixed_shape)
    _install_embed(env.mp, env.embed)
    env.mp.setattr(reranker, "_get_cross_encoder", lambda: env.ce)


@pytest.fixture
def env(monkeypatch):
    speculative_rerank.reset_for_test()
    feats = dict(FEATURES)
    embed = FakeEmbed()
    ce = FakeCE()
    _install_embed(monkeypatch, embed)
    monkeypatch.setattr(reranker, "_get_cross_encoder", lambda: ce)
    monkeypatch.setattr(tools, "_get_features", lambda: feats)
    monkeypatch.setattr(tools, "_get_config", lambda: CFG)
    monkeypatch.delenv(speculative_rerank.GATE_ENV, raising=False)
    ns = SimpleNamespace(embed=embed, ce=ce, feats=feats, mp=monkeypatch)
    yield ns
    for _ in range(500):
        if not speculative_rerank._job_busy:
            break
        time.sleep(0.01)
    speculative_rerank.reset_for_test()


def _serve(retriever, query, limit):
    """The handler's federated sequence: router.search → _maybe_rerank."""
    router = FederatedSearchRouter(openalex_client=None, opensearch_retriever=retriever)
    fetch_k = tools._retrieval_top_k(limit)
    results = router.search(query, {}, top_k=fetch_k, force_source=SearchSource.LOCAL_RRF)
    tools._cache_works(results)
    return tools._maybe_rerank(results, query, limit)


def _dump(docs):
    return json.dumps(docs, sort_keys=True)


def _both(env, make_retriever, query, limit):
    env.mp.delenv(speculative_rerank.GATE_ENV, raising=False)
    off = _serve(make_retriever(), query, limit)
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    on = _serve(make_retriever(), query, limit)
    env.mp.delenv(speculative_rerank.GATE_ENV, raising=False)
    return off, on


BM = [_doc(i) for i in range(30)]
SCENARIOS = {
    "splade_empty": lambda: FakeRetriever(BM, []),
    "splade_fails": lambda: FakeRetriever(BM, [], splade_raises=True),
    "splade_identical": lambda: FakeRetriever(BM, [dict(d) for d in BM]),
    "partial_overlap": lambda: FakeRetriever(BM, [_doc(i) for i in range(15, 45)]),
    "disjoint": lambda: FakeRetriever(BM, [_doc(i, "s") for i in range(100, 130)]),
    "reordered_overlap": lambda: FakeRetriever(BM, list(reversed(BM))),
}


def _order(sc):
    return sorted(range(len(sc)), key=lambda i: sc[i], reverse=True)


def _splice_vs_full(q, fused, drafted_texts):
    """Scores for ``fused`` spliced from a drafted call + a remainder call, vs one full call."""
    sim = lib.embedding.compute_similarity
    drafted = dict(zip(drafted_texts, sim(q, drafted_texts)))
    rest = [t for t in fused if t not in drafted]
    fresh = dict(zip(rest, sim(q, rest)))
    spliced = [drafted.get(t, fresh.get(t)) for t in fused]
    full = sim(q, fused)
    pairs = [(q, t) for t in fused]
    ce = reranker._get_cross_encoder()
    d_pairs = [(q, t) for t in drafted_texts]
    ce_drafted = dict(zip(d_pairs, reranker._ce_score_pairs(ce, d_pairs)))
    r_pairs = [p for p in pairs if p not in ce_drafted]
    ce_fresh = dict(zip(r_pairs, reranker._ce_score_pairs(ce, r_pairs)))
    ce_spliced = [ce_drafted.get(p, ce_fresh.get(p)) for p in pairs]
    ce_full = reranker._ce_score_pairs(ce, pairs)
    return spliced, full, ce_spliced, ce_full


_FUSED = [f"text {i} " + "w" * (i * 3 % 17) for i in range(20)]
_DRAFTED = _FUSED[:12] + [f"other {i} " + "z" * (i * 5 % 23) for i in range(8)]


def test_fakes_are_batch_sensitive_without_fixed_shape(env):
    """Longest-padding fakes: a per-candidate splice does NOT reproduce the
    full call's ranking, for both models. Guards against lenient fakes."""
    _install(env, fixed_shape=False)
    spliced, full, ce_spliced, ce_full = _splice_vs_full("graph neural networks", _FUSED, _DRAFTED)
    assert _order(spliced) != _order(full)
    assert _order(ce_spliced) != _order(ce_full)


def test_fixed_shape_makes_per_candidate_scores_bit_stable(env):
    """Fixed-shape fakes through the real chunkers: every item scores the
    same bits alone, in a remainder call, in a full call, or reversed."""
    spliced, full, ce_spliced, ce_full = _splice_vs_full("graph neural networks", _FUSED, _DRAFTED)
    assert spliced == full and ce_spliced == ce_full
    q = "graph neural networks"
    sim = lib.embedding.compute_similarity
    assert [sim(q, [t])[0] for t in _FUSED] == full
    assert sim(q, _FUSED[::-1])[::-1] == full
    ce = reranker._get_cross_encoder()
    assert [reranker._ce_score_pairs(ce, [(q, t)])[0] for t in _FUSED] == ce_full
    assert all(len(p) == reranker._CE_BATCH for p, _ in env.ce.calls)
    assert all(len(b) == lib.embedding._EMBED_BATCH for b in env.embed.batches)


def test_per_candidate_reuse_breaks_without_fixed_shape(env):
    """The same serve sequence with longest-padding fakes: gate-on output
    differs from gate-off, i.e. the parity below is owed to fixed shape."""
    _install(env, fixed_shape=False)
    off, on = _both(env, SCENARIOS["partial_overlap"], "graph neural networks", 10)
    assert _dump(on) != _dump(off)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
@pytest.mark.parametrize("limit", [5, 10, 20, 30])
def test_gate_on_output_byte_identical_to_gate_off(env, name, limit):
    off, on = _both(env, SCENARIOS[name], "graph neural networks", limit)
    assert _dump(on) == _dump(off)
    assert env.ce.max_active == 1


@pytest.mark.parametrize("feats", [
    {"crossencoder_enabled": False},
    {"rrf_enabled": True},
    {"crossencoder_enabled": False, "rrf_enabled": True},
])
@pytest.mark.parametrize("name", ["splade_empty", "partial_overlap"])
def test_parity_across_feature_combinations(env, feats, name):
    env.feats.update(feats)
    off, on = _both(env, SCENARIOS[name], "protein folding kinetics", 10)
    assert _dump(on) == _dump(off)


def test_full_acceptance_reuses_draft_calls(env):
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    out = _serve(FakeRetriever(BM, []), "q", 10)
    c = speculative_rerank.counters()
    assert out
    assert c["drafts_started"] == 1 and c["consumed_with_draft"] == 1
    assert c["embed_hits"] == 20 and c["embed_misses"] == 0 and c["embed_calls_skipped"] == 1
    assert c["ce_hits"] == 20 and c["ce_misses"] == 0 and c["ce_calls_skipped"] == 1
    main_embed = [call for call in env.embed.calls if not call[3]]
    main_ce = [call for call in env.ce.calls if not call[1]]
    assert main_embed == [] and main_ce == []


def test_partial_overlap_reuses_accepted_candidates(env):
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    retr = SCENARIOS["partial_overlap"]()
    router = FederatedSearchRouter(openalex_client=None, opensearch_retriever=retr)
    results = router.search("q", {}, top_k=20, force_source=SearchSource.LOCAL_RRF)
    drafted = {reranker._extract_doc_text(reranker._normalize_for_rerank(d)) for d in BM[:20]}
    fused_texts = [reranker._extract_doc_text(reranker._normalize_for_rerank(d)) for d in results]
    accepted = sum(1 for t in fused_texts if t in drafted)
    tools._maybe_rerank(results, "q", 10)
    c = speculative_rerank.counters()
    assert 0 < accepted < 20
    assert c["embed_hits"] == accepted and c["embed_misses"] == 20 - accepted
    main_embed = [call for call in env.embed.calls if not call[3]]
    assert len(main_embed) == 1 and len(main_embed[0][1]) == 20 - accepted
    assert set(main_embed[0][1]).isdisjoint(drafted)
    assert c["ce_hits"] > 0 and c["ce_hits"] + c["ce_misses"] == 20
    assert 0 < c["candidates_accepted"] < c["candidates_drafted"]


def test_draft_failure_never_fails_search(env):
    _install_embed(env.mp, FakeEmbed(fail_off_main=True))
    off, on = _both(env, SCENARIOS["splade_empty"], "q", 10)
    assert on and _dump(on) == _dump(off)


def test_gate_absent_takes_no_speculative_path(env):
    """Gate absent: no draft thread, no context in any model call, and the
    model calls are exactly the pre-change pipeline's (one stage-1 batch over
    the fused pool, one CE batch over its stage-1 top-20)."""
    for val in (None, "", "0", "true", "yes", " 1", "1 "):
        if val is None:
            env.mp.delenv(speculative_rerank.GATE_ENV, raising=False)
        else:
            env.mp.setenv(speculative_rerank.GATE_ENV, val)
        assert not speculative_rerank.is_enabled()
        env.embed.calls.clear(); env.embed.ctx_seen.clear(); env.ce.calls.clear()
        retr = SCENARIOS["partial_overlap"]()
        router = FederatedSearchRouter(openalex_client=None, opensearch_retriever=retr)
        results = router.search("q", {}, top_k=20, force_source=SearchSource.LOCAL_RRF)
        pool = [dict(d) for d in results]
        got = tools._maybe_rerank(results, "q", 10)
        stage1 = reranker.rerank_results(pool, "q", 20, use_embedding=True,
                                         use_rrf=False, embedding_model_path=None)
        want = reranker.rerank_with_crossencoder(stage1, "q", 10)
        assert _dump(got) == _dump(want)
        assert all(c is None for c in env.embed.ctx_seen)
        assert [c[3] for c in env.embed.calls] == [False, False]
        assert env.embed.calls[0][:3] == env.embed.calls[1][:3]
        ce_batches = [c[0] for c in env.ce.calls]
        half = len(ce_batches) // 2
        assert half and ce_batches[:half] == ce_batches[half:]
        assert all(len(b) == reranker._CE_BATCH for b in ce_batches)
        assert len(speculative_rerank._registry) == 0
    c = speculative_rerank.counters()
    assert c["drafts_started"] == 0 and c["embed_hits"] == 0 and c["embed_misses"] == 0


def test_rerank_disabled_starts_no_draft(env):
    env.feats["rerank_enabled"] = False
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    out = _serve(SCENARIOS["splade_empty"](), "q", 5)
    assert len(out) == 5
    assert speculative_rerank.counters()["drafts_started"] == 0
    assert env.embed.calls == []


def test_single_draft_slot_drops_when_busy(env):
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    gate = threading.Event()
    _install_embed(env.mp, FakeEmbed(gate=gate))
    first = speculative_rerank.on_draft("q1", [dict(d) for d in BM], 20)
    second = speculative_rerank.on_draft("q2", [dict(d) for d in BM], 20)
    assert first is not None and second is None
    assert speculative_rerank.counters()["dropped_busy"] == 1
    gate.set()
    assert first.wait(5)


def test_draft_ce_dropped_while_real_ce_active(env):
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    speculative_rerank.CE_SLOT.enter_real()
    try:
        h = speculative_rerank.on_draft("q", [dict(d) for d in BM], 20)
        assert h.wait(5)
    finally:
        speculative_rerank.CE_SLOT.exit_real()
    c = speculative_rerank.counters()
    assert c["draft_ce_dropped_slot"] == 2 and c["abandoned"] == 1
    assert c["draft_ce_batches"] == 0 and c["draft_ce_early"] == 0
    assert [call for call in env.ce.calls if call[1]] == []


def test_real_ce_waits_for_inflight_draft_batch(env):
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    block = threading.Event()
    ce = FakeCE(block=block)
    env.mp.setattr(reranker, "_get_cross_encoder", lambda: ce)
    h = speculative_rerank.on_draft("q", [dict(d) for d in BM], 20)
    deadline = time.monotonic() + 5
    while not ce.calls and time.monotonic() < deadline:
        time.sleep(0.002)
    assert ce.calls and ce.calls[0][1]
    done = []
    other = [_doc(i, "z") for i in range(200, 220)]
    t = threading.Thread(target=lambda: done.append(tools._maybe_rerank(other, "q", 5)))
    t.start()
    time.sleep(0.05)
    assert not done
    block.set()
    t.join(5)
    assert done and h.wait(5)
    assert ce.max_active == 1
    assert speculative_rerank.counters()["real_ce_waited"] == 1


def test_speculation_does_not_touch_wi18_or_cache_counters(env):
    before_spec = speculation.counters()
    before_cache = result_cache.counters()
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    _serve(SCENARIOS["splade_empty"](), "q", 10)
    assert speculation.counters() == before_spec
    assert result_cache.counters() == before_cache
    assert all(flag is None for flag in env.embed.spec_flag_seen)


def test_router_enters_hydrate_scope_once_per_local_rrf_request(env):
    plain = FakeRetriever(BM, SCENARIOS["partial_overlap"]().splade, wait_for_draft=False)
    scoped = FakeRetriever(BM, SCENARIOS["partial_overlap"]().splade,
                           wait_for_draft=False, with_scope=True)
    r_plain = FederatedSearchRouter(None, plain).search(
        "q", {}, top_k=20, force_source=SearchSource.LOCAL_RRF)
    r_scoped = FederatedSearchRouter(None, scoped).search(
        "q", {}, top_k=20, force_source=SearchSource.LOCAL_RRF)
    assert scoped.scope_enters == 1 and scoped.scope_exits == 1
    assert scoped.search_calls == [("bm25f", True), ("splade", True)]
    assert _dump(r_scoped) == _dump(r_plain)
    FederatedSearchRouter(None, scoped).search(
        "q", {}, top_k=20, force_source=SearchSource.LOCAL_INDEX)
    assert scoped.scope_enters == 1


def test_hydrate_scope_closes_before_draft_consumes(env):
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    retr = FakeRetriever(BM, [], with_scope=True)
    out = _serve(retr, "q", 10)
    assert out and retr.scope_enters == 1 and retr.scope_exits == 1
    assert [m for m, _ in retr.search_calls] == ["bm25f", "splade"]


def _wait_for(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not pred() and time.monotonic() < deadline:
        time.sleep(0.002)
    return pred()


def test_draft_ce_starts_before_stage1_finishes(env):
    """The draft CE batch runs while the draft stage-1 embedding is still
    blocked, and the draft does not score the same pairs a second time."""
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    gate = threading.Event()
    embed = FakeEmbed(gate=gate)
    _install_embed(env.mp, embed)
    h = speculative_rerank.on_draft("q", [dict(d) for d in BM], 20)
    assert _wait_for(lambda: speculative_rerank.counters()["draft_ce_batches"] == 1)
    assert not h.done.is_set()
    assert speculative_rerank.counters()["draft_ce_early"] == 1
    gate.set()
    assert h.wait(5)
    c = speculative_rerank.counters()
    assert c["draft_ce_covered"] == 1 and c["abandoned"] == 0 and c["job_errors"] == 0
    draft_ce = [call for call in env.ce.calls if call[1]]
    assert sum(len(p) for p, _ in draft_ce) == 20


def test_real_pass_reuses_early_ce_while_draft_stage1_in_flight(env):
    """Real pass arrives while the draft's stage-1 is still running: the CE
    is served entirely from the early draft batch, stage-1 from the in-flight
    draft call, and the output is byte-identical to gate-off."""
    off = _serve(SCENARIOS["splade_empty"](), "q", 10)
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    speculative_rerank.reset_for_test()
    gate = threading.Event()
    embed = FakeEmbed(gate=gate)
    _install_embed(env.mp, embed)
    env.ce.calls.clear()
    router = FederatedSearchRouter(openalex_client=None,
                                   opensearch_retriever=FakeRetriever(BM, [], wait_for_draft=False))
    fused = router.search("q", {}, top_k=20, force_source=SearchSource.LOCAL_RRF)
    assert _wait_for(lambda: speculative_rerank.counters()["draft_ce_batches"] == 1)
    threading.Timer(0.05, gate.set).start()
    tools._cache_works(fused)
    on = tools._maybe_rerank(fused, "q", 10)
    assert _dump(on) == _dump(off)
    c = speculative_rerank.counters()
    assert c["ce_hits"] == 20 and c["ce_misses"] == 0 and c["ce_calls_skipped"] == 1
    assert c["embed_hits"] == 20 and c["embed_misses"] == 0
    assert [call for call in env.ce.calls if not call[1]] == []
    assert env.ce.max_active == 1


def test_early_ce_skipped_when_crossencoder_disabled(env):
    env.feats["crossencoder_enabled"] = False
    env.mp.setenv(speculative_rerank.GATE_ENV, "1")
    h = speculative_rerank.on_draft("q", [dict(d) for d in BM], 20)
    assert h.wait(5)
    c = speculative_rerank.counters()
    assert c["draft_ce_early"] == 0 and c["draft_ce_batches"] == 0
    assert env.ce.calls == []
