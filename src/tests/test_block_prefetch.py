"""Unit tests for `lib.thinclient.block_prefetch` (speculative lever #4).

Synthetic `.mmap/` shard dirs only (manifest.json + token_to_id_map.bin +
a posting_lists.bin of exactly the walked size); no model, no real index,
no page-cache side effects (advise calls are monkeypatched).

Run:  .venv/bin/python3 -m pytest src/tests/test_block_prefetch.py -q
"""

import json
import os
import struct
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.thinclient import block_prefetch as bp  # noqa: E402
from lib.thinclient.sharded_seismic_backend import _postings_nav_runs  # noqa: E402

TOKENS = ["neural", "network", "protein", "folding", "climate", "policy", "ocean", "salt"]


def _pl_record(i: int) -> dict:
    return {
        "packed_postings_words": 600 + 97 * i,
        "block_offsets_len": 5 + i,
        "ef_high_bits_n_words": 3 + i,
        "inv_block_inventory_len": 2,
        "inv_subblock_inventory_len": 7 + i,
        "inv_overflow_positions_len": i % 2,
        "ef_low_bits_n_words": 2,
        "summaries_ids_n_words": 40 + 11 * i,
        "values_len": 900 + 301 * i,
        "minimums_len": 4 + i,
        "quants_len": 4 + i,
        "has_component_ids": bool(i % 3 == 0),
        "component_ids_len": 13 if i % 3 == 0 else 0,
    }


def _write_token_map(path: Path, tok2id: dict) -> None:
    buf = bytearray(struct.pack("<Q", len(tok2id)))
    for tok, tid in tok2id.items():
        b = tok.encode("utf-8")
        buf += struct.pack("<Q", len(b)) + b + struct.pack("<Q", tid)
    path.write_bytes(bytes(buf))


def _make_shard(root: Path, name: str, id_shift: int) -> Path:
    d = root / f"{name}.mmap"
    d.mkdir(parents=True)
    n = len(TOKENS)
    manifest = {"n_posting_lists": n, "posting_lists": [_pl_record(i) for i in range(n)]}
    (d / "manifest.json").write_text(json.dumps(manifest))
    _write_token_map(d / "token_to_id_map.bin",
                     {t: (i + id_shift) % n for i, t in enumerate(TOKENS)})
    _, walked = _postings_nav_runs(str(d))
    with open(d / "posting_lists.bin", "wb") as fh:
        fh.truncate(walked)
    return d


@pytest.fixture
def shards(tmp_path):
    return [_make_shard(tmp_path, "s0", 0), _make_shard(tmp_path, "s1", 3)]


def _encoder(text):
    weights = {"neural": 2.0, "network": 1.5, "protein": 1.5, "folding": 0.7,
               "climate": 0.3, "policy": 0.2, "unseen": 5.0}
    return {t: w for t, w in weights.items() if any(t[:3] in x for x in text.lower().split()) or t == "unseen"}


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv("SFU_BLOCK_PREFETCH", "1")
    monkeypatch.delenv("SFU_BLOCK_PREFETCH_MAX_MB", raising=False)


@pytest.fixture
def advise_log(monkeypatch):
    calls = {"fadvise": [], "madvise": []}
    monkeypatch.setattr(bp.os, "posix_fadvise",
                        lambda fd, off, ln, adv: calls["fadvise"].append((fd, off, ln, adv)))
    monkeypatch.setattr(bp, "_madvise_willneed",
                        lambda addr, ln: calls["madvise"].append((addr, ln)) or True)
    return calls


def test_layout_walk_matches_backend_nav_runs(shards):
    lay = bp.ShardLayout(shards[0])
    nav, walked = _postings_nav_runs(str(shards[0]))
    assert walked == lay.size
    man = json.loads((shards[0] / "manifest.json").read_text())
    extents, _ = bp.list_extents(man)
    for (p_off, p_len, s_off, s_len), (n_off, n_len) in zip(extents, nav):
        assert s_off == n_off
        assert s_off + s_len >= n_off + n_len
        assert p_off + p_len <= s_off
    assert extents[-1][2] + extents[-1][3] == walked


def test_layout_refuses_size_mismatch(shards):
    with open(shards[0] / "posting_lists.bin", "ab") as fh:
        fh.write(b"\0" * 8)
    with pytest.raises(ValueError):
        bp.ShardLayout(shards[0])


def test_completed_words():
    assert bp.completed_words("neural netw") == "neural"
    assert bp.completed_words("neural network ") == "neural network"
    assert bp.completed_words("neur") == ""
    assert bp.completed_words("") == ""


def test_plan_is_deterministic(gate_on, shards):
    a = bp.BlockPrefetcher(shards, encode_fn=_encoder, max_bytes=1 << 30)
    b = bp.BlockPrefetcher(list(reversed(shards)), encode_fn=_encoder, max_bytes=1 << 30)
    p1 = a.plan_prefetch("neural network protein fold")
    p2 = a.plan_prefetch("neural network protein fold")
    p3 = b.plan_prefetch("neural network protein fold")
    assert p1 and p1 == p2 == p3
    assert p1 == sorted(p1)
    for path, off, ln in p1:
        assert path.endswith("posting_lists.bin")
        assert off % bp.PAGE == 0 and ln > 0
    assert a.top_terms("neural network protein") == ["unseen", "neural", "network", "protein"]


def test_plan_drops_unfinished_word(gate_on, shards):
    pf = bp.BlockPrefetcher(shards, encode_fn=_encoder, max_bytes=1 << 30)
    seen = []
    pf._encode_fn = lambda t: seen.append(t) or _encoder(t)
    pf.plan_prefetch("neural netw")
    assert seen == ["neural"]
    assert pf.plan_prefetch("neur") == []


def test_byte_cap_enforced(gate_on, shards, advise_log):
    full = bp.BlockPrefetcher(shards, encode_fn=_encoder, max_bytes=1 << 30)
    total = sum(n for _, _, n in full.plan_prefetch("neural network protein folding "))
    cap = 2 * bp.PAGE
    assert total > cap
    small = bp.BlockPrefetcher(shards, encode_fn=_encoder, max_bytes=cap)
    plan = small.plan_prefetch("neural network protein folding ")
    assert 0 < sum(n for _, _, n in plan) <= cap
    out = small.issue_prefetch(full.plan_prefetch("neural network protein folding "))
    assert out["issued"] and out["bytes"] <= cap
    assert sum(c[2] for c in advise_log["fadvise"]) <= cap


def test_byte_cap_from_env(monkeypatch):
    monkeypatch.setenv("SFU_BLOCK_PREFETCH_MAX_MB", "2")
    assert bp.max_bytes_from_env() == 2 << 20
    monkeypatch.setenv("SFU_BLOCK_PREFETCH_MAX_MB", "garbage")
    assert bp.max_bytes_from_env() == int(bp.DEFAULT_MAX_MB * (1 << 20))
    monkeypatch.setenv("SFU_BLOCK_PREFETCH_MAX_MB", "-1")
    assert bp.max_bytes_from_env() == int(bp.DEFAULT_MAX_MB * (1 << 20))


def test_summary_runs_come_before_postings_under_cap(gate_on, shards):
    lay = bp.ShardLayout(shards[0])
    p_off, p_len, s_off, s_len = lay.extents["neural"]
    one = bp.BlockPrefetcher([shards[0]], encode_fn=lambda t: {"neural": 1.0},
                             max_bytes=bp.PAGE)
    plan = one.plan_prefetch("neural ")
    assert len(plan) == 1
    _, off, _ = plan[0]
    assert off == s_off - (s_off % bp.PAGE)


def test_single_slot_drops_not_queues(gate_on, shards, monkeypatch):
    pf = bp.BlockPrefetcher(shards, encode_fn=_encoder, max_bytes=1 << 30)
    plan = pf.plan_prefetch("neural network ")
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow(fd, off, ln, adv):
        calls.append(off)
        entered.set()
        release.wait(5)

    monkeypatch.setattr(bp.os, "posix_fadvise", slow)
    t = threading.Thread(target=pf.issue_prefetch, args=(plan,))
    t.start()
    assert entered.wait(5)
    assert pf.issue_prefetch(plan) == {"issued": False, "reason": "busy"}
    assert pf.speculate("neural network ") is False
    assert pf.stats["dropped"] == 2
    release.set()
    t.join(5)
    assert len(calls) == len(plan)
    assert pf.issue_prefetch(plan)["issued"] is True


def test_speculate_runs_in_background(gate_on, shards, advise_log):
    pf = bp.BlockPrefetcher(shards, encode_fn=_encoder, max_bytes=1 << 30)
    assert pf.speculate("neural network ") is True
    for _ in range(500):
        if pf.stats["issued"]:
            break
        threading.Event().wait(0.01)
    assert pf.stats["issued"] == 1
    assert advise_log["fadvise"]


def test_gate_off_is_noop(monkeypatch, shards, advise_log):
    monkeypatch.delenv("SFU_BLOCK_PREFETCH", raising=False)
    enc_calls = []
    pf = bp.BlockPrefetcher(shards, encode_fn=lambda t: enc_calls.append(t) or _encoder(t))
    assert pf.plan_prefetch("neural network ") == []
    assert pf.issue_prefetch([(str(shards[0] / "posting_lists.bin"), 0, 4096)])["issued"] is False
    assert pf.speculate("neural network ") is False
    assert enc_calls == [] and advise_log == {"fadvise": [], "madvise": []}
    for val in ("0", "true", "yes", " 1"):
        monkeypatch.setenv("SFU_BLOCK_PREFETCH", val)
        assert pf.plan_prefetch("neural network ") == []
    assert bp.plan_prefetch("neural network ") == []
    assert bp.speculate("neural network ") is False


def test_non_mmap_mode_is_noop(gate_on, shards, advise_log):
    pf = bp.BlockPrefetcher(shards, encode_fn=_encoder, load_mode="stock")
    assert pf.plan_prefetch("neural network ") == []
    assert pf.issue_prefetch([(str(shards[0] / "posting_lists.bin"), 0, 4096)])["issued"] is False
    assert advise_log == {"fadvise": [], "madvise": []}
    assert bp.BlockPrefetcher([], encode_fn=_encoder).plan_prefetch("neural network ") == []


def test_fadvise_issued_for_unmapped_file(gate_on, shards, advise_log):
    pf = bp.BlockPrefetcher(shards, encode_fn=_encoder, max_bytes=1 << 30)
    plan = pf.plan_prefetch("neural network ")
    out = pf.issue_prefetch(plan)
    assert out["issued"] and out["fadvise"] == len(plan) and out["madvise"] == 0
    assert [(c[1], c[2]) for c in advise_log["fadvise"]] == [(o, n) for _, o, n in plan]
    assert all(c[3] == os.POSIX_FADV_WILLNEED for c in advise_log["fadvise"])
    pf.close()


def test_madvise_issued_for_mapped_file(gate_on, shards, advise_log):
    import mmap
    path = shards[0] / "posting_lists.bin"
    with open(path, "rb") as fh:
        mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
    try:
        pf = bp.BlockPrefetcher([shards[0]], encode_fn=_encoder, max_bytes=1 << 30)
        plan = pf.plan_prefetch("neural network ")
        out = pf.issue_prefetch(plan)
        assert out["issued"] and out["madvise"] == len(plan) and out["fadvise"] == 0
        base = pf._bases[str(path.resolve())]
        assert [(a - base, n) for a, n in advise_log["madvise"]] == [(o, n) for _, o, n in plan]
    finally:
        mm.close()


def test_errors_are_silent(gate_on, shards, monkeypatch):
    def boom(*a):
        raise OSError("EIO")
    monkeypatch.setattr(bp.os, "posix_fadvise", boom)
    pf = bp.BlockPrefetcher(shards, encode_fn=_encoder, max_bytes=1 << 30)
    out = pf.issue_prefetch(pf.plan_prefetch("neural network "))
    assert out["issued"] is True and out["bytes"] == 0 and pf.stats["errors"] > 0
    bad = bp.BlockPrefetcher(shards, encode_fn=lambda t: 1 / 0)
    assert bad.plan_prefetch("neural network ") == []
    broken = bp.BlockPrefetcher([shards[0].parent / "missing.mmap"], encode_fn=_encoder)
    assert broken.plan_prefetch("neural network ") == []


def test_configure_from_backend(gate_on, shards, advise_log):
    class FakeBackend:
        _shard_mmap_dirs = [str(s) for s in shards]
        load_mode = "mmap"
        splade_model_path = "unused"
    pf = bp.configure(backend=FakeBackend(), encode_fn=_encoder, max_bytes=1 << 30)
    try:
        assert bp.get_prefetcher() is pf
        plan = bp.plan_prefetch("neural network ")
        assert plan and bp.issue_prefetch(plan)["issued"] is True
    finally:
        bp._default = None
