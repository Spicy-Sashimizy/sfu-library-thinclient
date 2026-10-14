"""Dense warm-cache v2 regression suite (2026-09-25).

Covers the three "Deferred to v2" items of docs/DENSE_WARMCACHE_RESEARCH.md:
delta->seed merge (`dense_delta_merge.merge_dense_delta`), the gated mutable
usearch delta index, and the gated int8 ONNX encoder's fallback contract.

Run: .venv/bin/python3 -m pytest scripts/tests/test_dense_cache_v2.py -q
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts"))

from lib.thinclient.builder import build_dense_leg  # noqa: E402
from lib.thinclient.dense_cache import DenseWarmCache  # noqa: E402
from lib.thinclient.dense_delta_merge import (DenseDeltaMergeError,  # noqa: E402
                                              merge_dense_delta)

DIM = 384


@pytest.fixture
def stub_encoder():
    rng = np.random.default_rng(11)
    cache: dict[str, np.ndarray] = {}

    def enc(texts):
        out = []
        for t in texts:
            if t not in cache:
                v = rng.standard_normal(DIM).astype(np.float32)
                cache[t] = v / np.linalg.norm(v)
            out.append(cache[t])
        return np.array(out)
    return enc


def _wait(pred, timeout=30):
    deadline = time.time() + timeout
    while not pred() and time.time() < deadline:
        time.sleep(0.05)
    assert pred()


def _seed_root(tmp_path: Path, n_seed: int = 400, seed: int = 3) -> Path:
    """Minimal synthetic index root: just a built dense/ leg."""
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n_seed, DIM)).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    np.save(tmp_path / "vecs.npy", X)
    (tmp_path / "ids.json").write_text(
        json.dumps([f"S{i}" for i in range(n_seed)]))
    build_dense_leg(tmp_path, tmp_path / "vecs.npy", tmp_path / "ids.json")
    return tmp_path


def _docs(n: int, offset: int = 0) -> list[dict]:
    return [{"openalex_id": f"D{i}", "title": f"delta doc {i}",
             "abstract": f"body {i}", "doi": f"10.9/{i}", "year": 2024,
             "type": "article", "is_oa": i % 2 == 0}
            for i in range(offset, offset + n)]


def _fill_delta(dense_dir: Path, stub_encoder, n: int, offset: int = 0):
    c = DenseWarmCache(dense_dir, seed_ids=[], model_path="",
                       encoder=stub_encoder)
    target = c.info()["docs"] + n
    c.enqueue(_docs(n, offset))
    _wait(lambda: c.info()["docs"] == target)
    c.close()
    return c


def _load_seed(dense_dir: Path):
    from usearch.index import Index
    ids = json.loads((dense_dir / "ids.json").read_text())
    rescore = np.load(dense_dir / "rescore_int8.npy")
    idx = Index.restore(str(dense_dir / "b1.usearch"), view=True)
    return ids, rescore, idx


def test_merge_folds_delta_into_seed(tmp_path, stub_encoder):
    root = _seed_root(tmp_path)
    dense = root / "dense"
    cache = _fill_delta(dense, stub_encoder, 60)
    before_ids, before_rescore, _ = _load_seed(dense)

    info = merge_dense_delta(root)
    assert info["status"] == "merged"
    assert (info["seed"], info["merged"], info["total"]) == (400, 60, 460)

    ids, rescore, idx = _load_seed(dense)
    assert len(ids) == 460 and rescore.shape == (460, DIM) and len(idx) == 460
    assert ids[:400] == before_ids
    assert np.array_equal(rescore[:400], before_rescore)
    assert ids[400:] == [f"D{i}" for i in range(60)]

    db = sqlite3.connect(dense / "delta.sqlite")
    assert db.execute("SELECT COUNT(*) FROM delta").fetchone()[0] == 0
    db.close()
    assert not list(dense.glob("*.tmp-*"))
    assert not (dense / ".merge.lock").exists()

    q = stub_encoder(["delta doc 42 body 42"])[0]
    hits = idx.search(np.packbits(q > 0), 5)
    top = ids[int(np.asarray(hits.keys).ravel()[0])]
    assert top == "D42"
    exact = (rescore.astype(np.float32) / 127.0) @ q
    assert ids[int(np.argmax(exact))] == "D42"
    cache.close()


def test_merge_is_idempotent_and_dedups_against_seed(tmp_path, stub_encoder):
    root = _seed_root(tmp_path, n_seed=120)
    dense = root / "dense"
    _fill_delta(dense, stub_encoder, 20).close()
    assert merge_dense_delta(root)["total"] == 140
    second = merge_dense_delta(root)
    assert second["status"] == "noop" and second["total"] == 140

    _fill_delta(dense, stub_encoder, 25).close()
    third = merge_dense_delta(root)
    assert third["merged"] == 5
    assert third["skipped"]["duplicate_of_seed"] == 20
    assert len(json.loads((dense / "ids.json").read_text())) == 145


def test_merge_survives_a_restarted_cache(tmp_path, stub_encoder):
    root = _seed_root(tmp_path, n_seed=80)
    dense = root / "dense"
    _fill_delta(dense, stub_encoder, 10).close()
    _fill_delta(dense, stub_encoder, 10, offset=10).close()
    assert merge_dense_delta(root)["merged"] == 20
    ids = json.loads((dense / "ids.json").read_text())
    assert ids[80:] == [f"D{i}" for i in range(20)]


def test_merge_fails_closed_on_disagreeing_seed(tmp_path, stub_encoder):
    root = _seed_root(tmp_path, n_seed=50)
    dense = root / "dense"
    _fill_delta(dense, stub_encoder, 5).close()
    ids = json.loads((dense / "ids.json").read_text())
    (dense / "ids.json").write_text(json.dumps(ids[:-1]))
    with pytest.raises(DenseDeltaMergeError):
        merge_dense_delta(root)
    assert not list(dense.glob("*.tmp-*"))
    assert not (dense / ".merge.lock").exists()
    db = sqlite3.connect(dense / "delta.sqlite")
    assert db.execute("SELECT COUNT(*) FROM delta").fetchone()[0] == 5
    db.close()

    (dense / "ids.json").write_text(json.dumps(ids))
    (root / "manifest.json").write_text(json.dumps({"dense": {"vectors": 7}}))
    with pytest.raises(DenseDeltaMergeError):
        merge_dense_delta(root)
    (root / "manifest.json").write_text(
        json.dumps({"dense": {"vectors": 50, "dim": DIM}}))
    assert merge_dense_delta(root)["merged"] == 5


def test_merge_refuses_incomplete_seed_and_concurrent_merge(tmp_path):
    root = _seed_root(tmp_path, n_seed=30)
    dense = root / "dense"
    (dense / ".merge.lock").write_text("999999")
    with pytest.raises(DenseDeltaMergeError):
        merge_dense_delta(root)
    (dense / ".merge.lock").unlink()
    (dense / "rescore_int8.npy").unlink()
    with pytest.raises(DenseDeltaMergeError):
        merge_dense_delta(root)


def _search_ids(cache, q, fetch):
    return [i for i, _ in cache.search(np.packbits(q > 0), q, fetch)]


def _planted_corpus(n_anchors=5, per_anchor=12, n_filler=740, seed=5):
    """Planted-neighbourhood synthetic corpus.

    Random 384-d unit vectors are near-orthogonal, so any candidate cut past
    rank 1 is noise and no two retrieval paths can be expected to agree. Each
    anchor here instead owns a graded neighbourhood (cos 0.95 → 0.62) well
    clear of the filler, which makes the top-k a property of the data rather
    than of the candidate cut.
    """
    rng = np.random.default_rng(seed)

    def unit(v):
        return (v / np.linalg.norm(v)).astype(np.float32)

    anchors = [unit(rng.standard_normal(DIM)) for _ in range(n_anchors)]
    texts, vecs = [], []
    for a, q in enumerate(anchors):
        for r in range(per_anchor):
            w = 0.95 - 0.03 * r
            vecs.append(unit(w * q + np.sqrt(1 - w * w)
                             * unit(rng.standard_normal(DIM))))
            texts.append(f"P{a}_{r}")
    for i in range(n_filler):
        vecs.append(unit(rng.standard_normal(DIM)))
        texts.append(f"F{i}")
    table = dict(zip(texts, vecs))

    def encoder(batch):
        return np.array([table[t.strip()] for t in batch])

    docs = [{"openalex_id": t, "title": t, "abstract": "", "doi": "",
             "year": 2024, "type": "article", "is_oa": True} for t in texts]
    return anchors, docs, encoder


def test_usearch_delta_matches_brute_force(tmp_path, monkeypatch):
    anchors, docs, encoder = _planted_corpus()

    monkeypatch.delenv("SFU_DENSE_DELTA_USEARCH_MIN", raising=False)
    brute = DenseWarmCache(tmp_path / "brute", seed_ids=[], model_path="",
                           encoder=encoder)
    assert brute.info()["delta_engine"] == "brute"
    brute.enqueue(docs)
    _wait(lambda: brute.info()["docs"] == len(docs), timeout=60)

    monkeypatch.setenv("SFU_DENSE_DELTA_USEARCH_MIN", "100")
    ann = DenseWarmCache(tmp_path / "ann", seed_ids=[], model_path="",
                         encoder=encoder)
    ann.enqueue(docs)
    _wait(lambda: ann.info()["docs"] == len(docs), timeout=60)
    assert ann.info()["delta_engine"] == "usearch"

    for a, q in enumerate(anchors):
        hit_ann, hit_brute = _search_ids(ann, q, 20), _search_ids(brute, q, 20)
        assert hit_ann[:10] == hit_brute[:10]
        assert hit_brute[0] == f"P{a}_0"
        assert set(hit_brute[:10]) <= {f"P{a}_{r}" for r in range(12)}
    brute.close()
    ann.close()


def test_usearch_delta_restores_from_sqlite(tmp_path, stub_encoder,
                                            monkeypatch):
    monkeypatch.setenv("SFU_DENSE_DELTA_USEARCH_MIN", "50")
    c = _fill_delta(tmp_path, stub_encoder, 120)
    c.close()
    c2 = DenseWarmCache(tmp_path, seed_ids=[], model_path="",
                        encoder=stub_encoder)
    assert c2.info()["docs"] == 120
    assert c2.info()["delta_engine"] == "usearch"
    q = stub_encoder(["delta doc 99 body 99"])[0]
    assert _search_ids(c2, q, 10)[0] == "D99"
    c2.close()


def test_usearch_gate_default_and_bad_value(tmp_path, stub_encoder,
                                            monkeypatch):
    monkeypatch.delenv("SFU_DENSE_DELTA_USEARCH_MIN", raising=False)
    c = _fill_delta(tmp_path / "off", stub_encoder, 60)
    assert c.info()["delta_engine"] == "brute" and c.info()["delta_ann_min"] == 0
    c.close()
    monkeypatch.setenv("SFU_DENSE_DELTA_USEARCH_MIN", "not-a-number")
    c2 = DenseWarmCache(tmp_path / "bad", seed_ids=[], model_path="",
                        encoder=stub_encoder)
    assert c2.info()["delta_ann_min"] == 0
    c2.close()


def test_onnx_encoder_gate_defaults_off_and_falls_back(tmp_path, monkeypatch):
    from lib.thinclient import dense_cache as dc

    monkeypatch.delenv("SFU_DENSE_ENCODER_ONNX", raising=False)
    assert dc.make_onnx_encoder("models/sfu-academic-embed-v5") is None
    monkeypatch.setenv("SFU_DENSE_ENCODER_ONNX", "1")
    monkeypatch.setenv("SFU_DENSE_ENCODER_ONNX_PATH", str(tmp_path / "nope"))
    assert dc.make_onnx_encoder("models/sfu-academic-embed-v5") is None
