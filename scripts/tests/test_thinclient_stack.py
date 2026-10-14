"""Regression suite for the thin-client stack (2026-06-11 batch):
meta v1/v2 schema, era sub-sections + pruning, abstracts v3 (pre-v3 refused),
dense warm cache, MCP index-management tools.

Run: .venv/bin/python3 -m pytest scripts/tests/test_thinclient_stack.py -q
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import zstandard

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts"))

from lib.thinclient.builder import (SectionBuilder, encode_meta_id,  # noqa: E402
                                    open_meta_db)
from lib.thinclient.retriever import ThinClientRetriever, _era_skip  # noqa: E402
from lib.thinclient.sections import PERSONAS, SUBSECTION_NAMES, era_of  # noqa: E402
import lib.thinclient.abstracts as A  # noqa: E402

EN = ("This study examines the political economy of climate adaptation in "
      "coastal regions, drawing on comparative survey data and case studies. ")
RU = ("В данной работе рассматривается политическая экономия адаптации к "
      "изменению климата в прибрежных регионах. ")
ZH = "本文研究沿海地区气候适应的政治经济学，基于比较调查数据和案例研究。"


def _mkdoc(i: int, year: int = 2015, section_word: str = "politics") -> dict:
    return {"id": f"W{i}", "title": f"{section_word} paper {i}",
            "abstract": f"{section_word} text {i}", "publication_year": year,
            "type": "article", "is_oa": i % 2 == 0, "doi": f"10.1/{i}"}


def _build_index(root: Path, n: int = 600, hot: bool = True) -> None:
    meta = open_meta_db(root)
    b = SectionBuilder(root, "social_sciences__recent", hot=hot, meta_db=meta)
    for i in range(1, n + 1):
        b.add(_mkdoc(i))
    b.finish()
    meta.commit()
    meta.close()


def test_encode_meta_id():
    assert encode_meta_id("W2031234567") == 2031234567
    for bad in ("W0123", "X123", "W12a3", "W"):
        assert encode_meta_id(bad) is None


def test_meta_v2_roundtrip_and_overflow(tmp_path):
    meta = open_meta_db(tmp_path)
    b = SectionBuilder(tmp_path, "social_sciences__recent", hot=False, meta_db=meta)
    for i in range(1, 601):
        b.add(_mkdoc(i))
    odd = _mkdoc(9999)
    odd["id"] = "ODDID-42"
    b.add(odd)
    b.finish()
    meta.commit(); meta.close()

    db = sqlite3.connect(tmp_path / "meta.sqlite")
    assert db.execute("SELECT COUNT(*) FROM docs").fetchone()[0] == 600
    assert db.execute("SELECT COUNT(*) FROM docs_other").fetchone()[0] == 1
    assert db.execute("SELECT typeof(id) FROM docs LIMIT 1").fetchone()[0] == "integer"

    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
    r._load()
    rows = r._meta_rows(["ODDID-42", "W5", "Wnope"])
    assert rows["W5"][1] == "politics paper 5"
    assert rows["ODDID-42"][1] == "politics paper 9999"
    assert "Wnope" not in rows
    assert r._meta_numeric


def test_meta_v1_text_schema_still_served(tmp_path):
    db = sqlite3.connect(tmp_path / "meta.sqlite")
    db.executescript(
        "CREATE TABLE docs (id TEXT PRIMARY KEY, title TEXT, doi TEXT,"
        " year INTEGER, type TEXT, is_oa INTEGER, section TEXT);")
    db.execute("INSERT INTO docs VALUES ('W1','t','d',2020,'article',1,'s')")
    db.commit(); db.close()
    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
    r._load()
    assert not r._meta_numeric
    assert r._meta_rows(["W1"])["W1"][1] == "t"


def test_era_helpers_and_personas():
    assert era_of(2015) == "recent" and era_of(1995) == "archive"
    assert era_of(None) == "archive"
    assert "cs_math__recent" in SUBSECTION_NAMES
    assert PERSONAS["political_science"] == ["social_sciences__recent"]
    assert "social_sciences__archive" in PERSONAS["historical"]
    assert all(s.endswith("__recent") for s in PERSONAS["contemporary"])
    assert PERSONAS["all_hot"] == SUBSECTION_NAMES


def test_era_skip():
    assert _era_skip("x__archive", {"year_range": (2015, 2020)})
    assert _era_skip("x__recent", {"year_range": (1980, 1999)})
    assert not _era_skip("x__recent", {"year_range": (2000, 2020)})
    assert not _era_skip("x__recent", None)
    assert not _era_skip("legacy_name", {"year_range": (2015, 2020)})


def test_build_worker_era_routing(tmp_path):
    import build_thinclient_index as B
    spool = tmp_path / "spool" / "social_sciences"
    spool.mkdir(parents=True)
    with open(spool / "slice_000.jsonl.zst", "wb") as fh:
        zw = zstandard.ZstdCompressor(level=3).stream_writer(fh)
        for i in range(400):
            zw.write((json.dumps(_mkdoc(i + 1, year=2015 if i % 2 else 1990))
                      + "\n").encode())
        zw.close()
    infos = B.build_section_worker(str(tmp_path), "social_sciences",
                                   ["social_sciences__recent"], True)
    assert infos["social_sciences__recent"]["docs"] == 200
    assert infos["social_sciences__recent"]["hot"]
    assert not infos["social_sciences__archive"]["hot"]
    assert (tmp_path / "sections/social_sciences__recent/abstracts.sqlite").exists()
    assert not (tmp_path / "sections/social_sciences__archive/abstracts.sqlite").exists()
    B.merge_section_meta(tmp_path, ["social_sciences"])

    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
    res = r.search("politics", top_k=50, filters={"publication_year": "2012-2024"})
    assert res and all(d["year"] == 2015 for d in res)
    res_old = r.search("politics", top_k=50, filters={"publication_year": "1980-1999"})
    assert res_old and all(d["year"] == 1990 for d in res_old)
    assert r.cold_section_hint("quantum semiconductor physics") == "phys_eng__recent"
    assert r.cold_section_hint("quantum semiconductor physics",
                               filters={"publication_year": "1950-1990"}
                               ) == "phys_eng__archive"
    assert r.cold_section_hint("political governance") is None


def test_script_bucket():
    assert A.script_bucket(EN) == "latin"
    assert A.script_bucket(RU) == "cyrillic"
    assert A.script_bucket(ZH) == "han"
    assert A.script_bucket("") == "latin"


def test_abstracts_v3_roundtrip(tmp_path):
    w = A.AbstractStoreWriter(tmp_path / "a.sqlite")
    docs = {f"W{i}": EN + f"variant {i}" for i in range(2000)}
    docs.update({f"WR{i}": RU + f"вариант {i}" for i in range(400)})
    docs.update({f"WZ{i}": ZH + f"变体 {i}" for i in range(40)})
    for k, v in docs.items():
        w.add(k, v)
    w.add("Wempty", "")
    assert w.finish() == len(docs)

    r = A.AbstractStore(tmp_path / "a.sqlite")
    fetched = r.fetch(list(docs))
    assert fetched == docs
    db = sqlite3.connect(tmp_path / "a.sqlite")
    n_dicts = db.execute(
        "SELECT COUNT(*) FROM meta WHERE k LIKE 'zdict_%'").fetchone()[0]
    assert n_dicts == 2


def test_abstracts_flat_sidecar_is_byte_identical(tmp_path):
    """N5 (doc 18 §9): moving block payloads to a flat file must change
    latency and nothing else. The spike gated this on 20,000 production ids;
    this is the unit-scale regression guard for the landed reader."""
    p = tmp_path / "a.sqlite"
    w = A.AbstractStoreWriter(p)
    docs = {f"W{i}": EN + f"variant {i}" for i in range(2000)}
    docs.update({f"WR{i}": RU + f"вариант {i}" for i in range(400)})
    for k, v in docs.items():
        w.add(k, v)
    w.finish()

    plain = A.AbstractStore(p)
    assert plain._flat is None
    before = plain.fetch(list(docs))

    rep = A.build_flat_sidecar(p)
    assert rep["blocks"] > 1
    flat = A.AbstractStore(p)
    assert flat._flat is not None
    assert flat.fetch(list(docs)) == before == docs


def test_abstracts_flat_survives_dropping_the_blocks_table(tmp_path):
    """Reclaiming the payload space means dropping `blocks` from the sqlite.
    v3 detection must not key off that table, or the store silently falls
    through to the v1/v2 path and queries a non-existent `abs` table."""
    p = tmp_path / "a.sqlite"
    w = A.AbstractStoreWriter(p)
    docs = {f"W{i}": EN + f"variant {i}" for i in range(800)}
    for k, v in docs.items():
        w.add(k, v)
    w.finish()
    A.build_flat_sidecar(p)

    db = sqlite3.connect(p)
    db.execute("DROP TABLE blocks")
    db.commit()
    db.execute("VACUUM")
    db.close()

    r = A.AbstractStore(p)
    assert r._flat is not None
    assert r.fetch(list(docs)) == docs


def test_abstracts_no_payloads_left_raises_clearly(tmp_path):
    """Sidecar gone AND blocks dropped = the payloads are genuinely gone.
    That must say so, not fail three frames deeper in sqlite."""
    p = tmp_path / "a.sqlite"
    w = A.AbstractStoreWriter(p)
    for i in range(400):
        w.add(f"W{i}", EN + f"variant {i}")
    w.finish()
    A.build_flat_sidecar(p)
    db = sqlite3.connect(p)
    db.execute("DROP TABLE blocks")
    db.commit()
    db.close()
    (p.with_suffix(p.suffix + ".flat") / "blocks.bin").unlink()

    with pytest.raises(RuntimeError, match="no payloads left"):
        A.AbstractStore(p)


def test_abstracts_half_built_sidecar_falls_back(tmp_path):
    """A crashed sidecar build must not take the section down — v3 still holds
    every payload, so falling back is lossless."""
    p = tmp_path / "a.sqlite"
    w = A.AbstractStoreWriter(p)
    docs = {f"W{i}": EN + f"variant {i}" for i in range(600)}
    for k, v in docs.items():
        w.add(k, v)
    w.finish()
    A.build_flat_sidecar(p)
    (p.with_suffix(p.suffix + ".flat") / "blocks.bin").unlink()

    r = A.AbstractStore(p)
    assert r._flat is None
    assert r.fetch(list(docs)) == docs


def test_abstracts_pre_v3_store_refused(tmp_path):
    p1 = tmp_path / "v1.sqlite"
    db = sqlite3.connect(p1)
    db.executescript("CREATE TABLE abs (id TEXT PRIMARY KEY, z BLOB);"
                     "CREATE TABLE meta (k TEXT PRIMARY KEY, v BLOB);")
    db.commit(); db.close()
    with pytest.raises(RuntimeError, match="not a v3 abstracts store"):
        A.AbstractStore(p1)


@pytest.fixture
def stub_encoder():
    rng = np.random.default_rng(7)
    cache: dict[str, np.ndarray] = {}

    def enc(texts):
        out = []
        for t in texts:
            if t not in cache:
                v = rng.standard_normal(384).astype(np.float32)
                cache[t] = v / np.linalg.norm(v)
            out.append(cache[t])
        return np.array(out)
    return enc


def _wait(pred, timeout=30):
    deadline = time.time() + timeout
    while not pred() and time.time() < deadline:
        time.sleep(0.1)
    assert pred()


def test_dense_cache_lifecycle(tmp_path, stub_encoder):
    from lib.thinclient.dense_cache import DenseWarmCache
    c = DenseWarmCache(tmp_path, seed_ids=["W1"], model_path="",
                       encoder=stub_encoder)
    docs = [{"openalex_id": f"W{i}", "title": f"doc {i}",
             "abstract": f"about {i}", "doi": "", "year": 2020,
             "type": "article", "is_oa": True} for i in range(1, 101)]
    c.enqueue(docs)
    c.enqueue(docs)
    _wait(lambda: c.info()["docs"] == 99)
    q = stub_encoder(["doc 42 about 42"])[0]
    hits = c.search(np.packbits(q > 0), q, fetch=10)
    assert hits[0][0] == "W42" and hits[0][1] > 0.9
    rows = c.metadata_rows(["W42", "Wmissing"])
    assert rows["W42"][1] == "doc 42" and "Wmissing" not in rows
    c.close()
    c2 = DenseWarmCache(tmp_path, seed_ids=["W1"], model_path="",
                        encoder=stub_encoder)
    assert c2.info()["docs"] == 99
    assert c2.search(np.packbits(q > 0), q, fetch=5)[0][0] == "W42"
    c2.close()


def test_dense_cache_only_leg(tmp_path, stub_encoder, monkeypatch):
    _build_index(tmp_path)
    monkeypatch.setenv("SFU_DENSE_LEG", "1")
    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
    r._load()
    assert r._dense is None and r._dense_cache is not None
    r._dense_cache._encoder = stub_encoder
    res = r.search("politics", top_k=10)
    assert res
    _wait(lambda: r._dense_cache.info()["docs"] >= len(res))
    import lib.opensearch_retriever as osr
    monkeypatch.setattr(osr, "encode_dense",
                        lambda text, mp: stub_encoder([text])[0])
    d0 = res[0]
    out = r.dense_search(f"{d0['title']} {d0['abstract']}", top_k=5)
    assert out and out[0]["openalex_id"] == d0["openalex_id"]


def test_serves_with_no_dense_dir(tmp_path, monkeypatch, caplog):
    """No `dense/` in the payload → bm25f/SPLADE still serve, RRF fuses the
    surviving legs, the dense leg returns [] and logs nothing."""
    monkeypatch.setenv("SFU_DENSE_WARMCACHE", "0")
    _build_index(tmp_path)
    assert not (tmp_path / "dense").exists()

    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
    with caplog.at_level("WARNING", logger="sfu_library_mcp"):
        r._load()
        assert r._dense is None and r._dense_cache is None
        assert r.is_available()
        assert r.search("politics", top_k=10)
        before = r._leg_snapshot_for_log()
        caplog.clear()
        for _ in range(5):
            assert r.dense_search("politics paper", top_k=10) == []
        assert caplog.records == []
        fused = r.search_rrf("politics paper", top_k=10, include_dense=True)
    assert fused and all(d["source"] == "thinclient_rrf" for d in fused)
    assert not [rec for rec in caplog.records
                if "dense" in rec.getMessage().lower()]

    assert "dense" not in r._leg_delta_for_log(before)
    m = r.metrics()
    assert m["dense_vectors"] == 0 and m["dense_warm_cache"] is None
    assert r.reload()["dense_vectors"] == 0


def test_dense_leg_env_gate(tmp_path, monkeypatch):
    """The dense leg is DEFAULT OFF (2026-08-18 ablation verdict); only the
    literal "1" enables it. Off never touches the encoder or creates dense/."""
    _build_index(tmp_path)

    monkeypatch.delenv("SFU_DENSE_LEG", raising=False)
    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
    r._load()
    assert r._dense is None and r._dense_cache is None
    assert r.metrics()["dense_leg_enabled"] is False
    assert not (tmp_path / "dense").exists()
    import lib.opensearch_retriever as osr
    monkeypatch.setattr(osr, "encode_dense", _raise_encoder)
    assert r.dense_search("politics paper", top_k=10) == []
    assert r.search("politics", top_k=5)

    for off_value in ("0", "true", "on", "yes"):
        monkeypatch.setenv("SFU_DENSE_LEG", off_value)
        r_off = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
        r_off._load()
        assert r_off.metrics()["dense_leg_enabled"] is False, off_value

    monkeypatch.setenv("SFU_DENSE_LEG", "1")
    r2 = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
    r2._load()
    assert r2._dense_cache is not None
    assert r2.metrics()["dense_leg_enabled"] is True
    r2._dense_cache.close()


def _raise_encoder(text, model_path):
    raise AssertionError("dense encoder must not be loaded when the leg is off")


def _leg(*ids: str) -> list[dict]:
    return [{"openalex_id": i, "title": i, "score": 1.0} for i in ids]


def test_rrf_provenance_synthetic_fusion():
    """Hand-built legs → exact per-doc {leg: 1-based rank} and exact scores."""
    fuse = ThinClientRetriever._rrf_fuse
    legs = {"bm25f": _leg("A", "B", "C"),
            "splade": _leg("B", "A", "D"),
            "dense": _leg("E", "B")}
    out = fuse(legs, top_k=10, with_provenance=True)
    prov = {d["openalex_id"]: d["rrf_legs"] for d in out}
    assert prov == {"A": {"bm25f": 1, "splade": 2},
                    "B": {"bm25f": 2, "splade": 1, "dense": 2},
                    "C": {"bm25f": 3},
                    "D": {"splade": 3},
                    "E": {"dense": 1}}
    assert out[0]["openalex_id"] == "B"
    scores = {d["openalex_id"]: d["score"] for d in out}
    assert scores["B"] == 1 / 62 + 1 / 61 + 1 / 62
    assert scores["E"] == 1 / 61
    assert [d["openalex_id"] for d in out if list(d["rrf_legs"]) == ["dense"]] == ["E"]
    assert list(prov["B"]) == ["bm25f", "splade", "dense"]


def test_rrf_provenance_is_opt_in_and_ranking_neutral():
    """Default shape is byte-for-byte the pre-provenance one; turning it on
    adds `rrf_legs` and changes NOTHING else (ids, order, float scores)."""
    fuse = ThinClientRetriever._rrf_fuse
    legs = {"bm25f": _leg(*[f"W{i}" for i in range(20)]),
            "splade": _leg(*[f"W{i}" for i in range(15, 40)])}
    plain = fuse(legs, top_k=25)
    withp = fuse(legs, top_k=25, with_provenance=True)
    assert all("rrf_legs" not in d for d in plain)
    assert [d["openalex_id"] for d in plain] == [d["openalex_id"] for d in withp]
    for a, b in zip(plain, withp):
        assert a["score"] == b["score"]
        assert b.pop("rrf_legs")
        assert a == b


def test_search_rrf_ranking_unchanged_with_provenance(tmp_path, monkeypatch):
    """Same assertion through the real served path (tantivy BM25F leg; no
    SEISMIC shards here, so the SPLADE leg takes its BM25F fallback)."""
    monkeypatch.setenv("SFU_DENSE_WARMCACHE", "0")
    _build_index(tmp_path)
    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)

    plain = r.search_rrf("politics paper", top_k=20)
    withp = r.search_rrf("politics paper", top_k=20, with_provenance=True)
    assert plain and len(plain) == len(withp)
    assert all("rrf_legs" not in d for d in plain)
    for a, b in zip(plain, withp):
        assert a["openalex_id"] == b["openalex_id"]
        assert a["score"] == b["score"] and b["source"] == "thinclient_rrf"
        assert set(b) - set(a) == {"rrf_legs"}
        assert b["rrf_legs"] and set(b["rrf_legs"]) <= {"bm25f", "splade"}
        assert all(isinstance(v, int) and v >= 1 for v in b["rrf_legs"].values())


def test_search_rrf_detailed_carries_legs_and_latency(tmp_path, monkeypatch):
    """The eval surface: per-leg rankings + per-leg ms + the fused list with
    provenance, from ONE retrieval pass, identical to search_rrf's ranking."""
    monkeypatch.setenv("SFU_DENSE_WARMCACHE", "0")
    _build_index(tmp_path)
    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)

    det = r.search_rrf_detailed("politics paper", top_k=20, include_dense=True)
    assert set(det) == {"results", "legs", "leg_latency_ms"}
    assert set(det["legs"]) == {"bm25f", "splade"}
    assert set(det["leg_latency_ms"]) == {"bm25f", "splade"}
    assert all(ms >= 0 for ms in det["leg_latency_ms"].values())
    assert det["legs"]["bm25f"] and all(isinstance(i, str)
                                        for i in det["legs"]["bm25f"])
    ref = r.search_rrf("politics paper", top_k=20)
    assert [d["openalex_id"] for d in det["results"]] == \
           [d["openalex_id"] for d in ref]
    assert [d["score"] for d in det["results"]] == [d["score"] for d in ref]
    for d in det["results"]:
        for leg, rank in d["rrf_legs"].items():
            assert det["legs"][leg][rank - 1] == d["openalex_id"]


def test_dense_leg_off_produces_no_dense_provenance(tmp_path, monkeypatch):
    """Arm A of the §7 ablation: SFU_DENSE_LEG=0 must leave no dense trace in
    the record — no `dense` leg, no `dense` key in any doc's provenance."""
    monkeypatch.setenv("SFU_DENSE_LEG", "0")
    _build_index(tmp_path)
    import lib.opensearch_retriever as osr
    monkeypatch.setattr(osr, "encode_dense", _raise_encoder)

    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False)
    det = r.search_rrf_detailed("politics paper", top_k=20, include_dense=True)
    assert "dense" not in det["legs"] and "dense" not in det["leg_latency_ms"]
    assert det["results"]
    assert all("dense" not in d["rrf_legs"] for d in det["results"])
    assert r.metrics()["dense_leg_enabled"] is False


def _eval_pipeline_module():
    import importlib.util
    path = REPO / "scripts/experiments/eval_pipeline.py"
    spec = importlib.util.spec_from_file_location("eval_pipeline_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eval_pipeline_query_loader_shapes(tmp_path):
    EP = _eval_pipeline_module()
    p = tmp_path / "q.json"
    p.write_text(json.dumps([
        {"paraphrase": "climate adaptation coastal", "judge_key": "jk1",
         "query_type": "natural", "stratum": "HELD-OUT"},
        {"query": "bare query form"},
        {"paraphrase": "climate adaptation coastal"},
    ]))
    rows = EP.load_query_records(p)
    assert [r["query"] for r in rows] == ["climate adaptation coastal",
                                          "bare query form"]
    assert rows[0]["judge_key"] == "jk1" and rows[0]["stratum"] == "HELD-OUT"
    assert rows[1]["judge_key"] == "bare query form"
    assert rows[1]["query_type"] == "unspecified"
    p.write_text(json.dumps({"queries": ["one", "two"]}))
    assert [r["query"] for r in EP.load_query_records(p, limit=1)] == ["one"]


def test_eval_pipeline_summary_metrics_from_recorded_lists():
    """dense-vote share / leg overlap / recall@50 must be computable from the
    recorded per-query lists alone — no retrieval re-run."""
    EP = _eval_pipeline_module()
    rows = [{
        "query": "q", "judge_key": "jk", "query_type": "natural",
        "stratum": "HELD-OUT",
        "bm25f": ["A", "B", "C"], "splade": ["B", "D"], "dense": ["E", "B"],
        "lat_bm25f_ms": 10.0, "lat_splade_ms": 20.0, "lat_dense_ms": 5.0,
        "rrf": ["B", "A", "E", "C", "D"],
        "rrf_legs": [{"bm25f": 2, "splade": 1, "dense": 2}, {"bm25f": 1},
                     {"dense": 1}, {"bm25f": 3}, {"splade": 2}],
        "lat_total_ms": 40.0,
    }]
    summ = EP.summarize_thinclient(rows, {"jk": {"B": 3, "E": 0, "Z": 2}})
    for name in ("overall", "natural", "HELD-OUT"):
        s = summ[name]
        assert s["n_queries"] == 1 and s["n_judged"] == 1
        assert s["dense_vote_share@10"] == 0.2
        assert s["dense_any_share@10"] == 0.4
        assert s["bm25f_splade_overlap@50"] == 1
        assert s["dense_bm25f_overlap@50"] == 1
        assert s["retrieval_recall@50"] == 0.5
        assert s["lat_dense_p50_ms"] == 5.0
    assert summ["overall"]["retrieval_ndcg@10"] > 0


def test_metrics_query_log_and_reload(tmp_path):
    _build_index(tmp_path)
    r = ThinClientRetriever(index_root=str(tmp_path), remote_abstracts=False,
                            query_log_path=str(tmp_path / "qlog.jsonl"))
    res = r.search("politics", top_k=5)
    assert res and res[0]["abstract"]
    m = r.metrics()
    assert m["legs"]["bm25f"]["count"] >= 1
    entry = json.loads((tmp_path / "qlog.jsonl").read_text().strip().split("\n")[-1])
    assert entry["leg"] == "bm25f" and entry["results"] == 5
    info = r.reload()
    assert "social_sciences__recent" in info["live_sections"]
    assert r.search("politics", top_k=3)


@pytest.mark.asyncio
async def test_mcp_index_tools(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    _build_index(tmp_path)
    monkeypatch.setenv("SFU_SEARCH_BACKEND", "thinclient")
    monkeypatch.setenv("SFU_THINCLIENT_INDEX_ROOT", str(tmp_path))
    monkeypatch.setenv("SFU_DENSE_WARMCACHE", "0")
    from lib import tools
    monkeypatch.setattr(tools, "_federated_router", None)
    monkeypatch.setattr(tools, "_thinclient_retriever", None)
    monkeypatch.setattr(tools, "_config", None, raising=False)

    names = {t.name for t in tools.TOOL_DEFINITIONS}
    assert {"get_index_status", "list_personas", "request_section_unpack",
            "reload_index"} <= names

    out = await tools._dispatch_tool("list_personas", {})
    data = json.loads(out[0].text)
    assert "contemporary" in data["personas"]
    assert data["live_sections"] == ["social_sciences__recent"]
    out = await tools._dispatch_tool("request_section_unpack", {"section": "bogus"})
    assert "Unknown section" in out[0].text
    out = await tools._dispatch_tool("request_section_unpack",
                                     {"section": "social_sciences__recent"})
    assert "already live" in out[0].text
    out = await tools._dispatch_tool("reload_index", {})
    assert json.loads(out[0].text)["reloaded"]["live_sections"]
