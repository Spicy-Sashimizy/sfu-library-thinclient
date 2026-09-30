"""Delta-ingest spike (docs/delta_ingest/): synthetic end-to-end.

Base index (immutable) + JSONL adapter -> ledger/buffer -> retriever with
SFU_DELTA_ROOT=1 sees new docs, newest-wins on updates, hides deletes; then
freeze -> generation, reload, second generation, compaction. The SPLADE leg
is exercised with a fake SEISMIC backend + fake query encoder (no model).
The real SEISMIC chain test at the end skips when the toolchain is absent.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from lib.thinclient.builder import SectionBuilder, open_meta_db  # noqa: E402
from lib.thinclient.retriever import ThinClientRetriever  # noqa: E402
from spike.delta_ingest import cli  # noqa: E402
from spike.delta_ingest.adapters import JsonlAdapter, select_new_parts  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.generation import build_generation, gen_name  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.profiles import PROFILES  # noqa: E402
from spike.delta_ingest.records import DocRecord, normalize_openalex_work  # noqa: E402

N_BASE = 300


def _base_doc(i: int) -> dict:
    title = {5: "quantum widgets alpha", 7: "delete me gamma"}.get(i, f"politics paper {i}")
    return {"id": f"W{i}", "title": title, "abstract": f"policy study number {i} about elections",
            "publication_year": 2015 + i % 5, "type": "article", "is_oa": i % 2 == 0,
            "doi": f"10.1/{i}"}


@pytest.fixture
def base_root(tmp_path):
    root = tmp_path / "index"
    root.mkdir()
    meta = open_meta_db(root)
    b = SectionBuilder(root, "social_sciences__recent", hot=True, meta_db=meta)
    for i in range(1, N_BASE + 1):
        b.add(_base_doc(i))
    b.finish()
    meta.commit()
    meta.close()
    (root / "manifest.json").write_text(json.dumps({"sections": {}, "persona": "all_hot"}))
    return root


def _sparse(*terms):
    return {t: 1.0 for t in terms}


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _ingest(root, path, *extra):
    cli.main(["ingest", "--source", "jsonl", "--path", str(path), "--index-root", str(root),
              "--profile", "laptop", "--rate", "0", "--no-encode", "--no-seismic",
              "--namespace", "local", *extra])


def _retriever(root, monkeypatch):
    monkeypatch.setenv("SFU_DELTA_ROOT", "1")
    monkeypatch.setenv("SFU_SPLADE_BACKEND", "seismic")
    monkeypatch.delenv("SFU_SEISMIC_SHARD_MANIFEST", raising=False)
    tc = ThinClientRetriever(index_root=str(root), remote_abstracts=False)
    tc._load()
    return tc


class _FakeSeismic:
    """Base SPLADE leg: still returns the stale base copies of W5 and W7."""

    def search(self, query, fetch, **kw):
        return [("W5", 0.9), ("W7", 0.8), ("W1", 0.5), ("W2", 0.4)]


def _fake_encode(query, model_path):
    return {t: 1.0 for t in query.split()}


def _ids(rows):
    return [r["openalex_id"] for r in rows]


def test_buffer_then_generations_then_compaction(base_root, tmp_path, monkeypatch, capsys):
    rows = [{"id": f"L{i}", "title": f"widgets local {i}", "abstract": f"local abstract {i} widgets",
             "year": 2024, "type": "article", "sparse_field": _sparse("widgets", f"t{i}")}
            for i in range(40)]
    rows.append({"id": "W5", "title": "quantum widgets beta", "abstract": "updated abstract widgets",
                 "year": 2016, "type": "article", "doi": "10.1/5", "sparse_field": _sparse("widgets", "beta")})
    rows.append({"_delete": "W7"})
    src = _write_jsonl(tmp_path / "batch1.jsonl", rows)
    _ingest(base_root, src)
    out = json.loads(capsys.readouterr().out)
    assert out["new"] == 40 and out["updated"] == 1 and out["deleted"] == 1

    tc = _retriever(base_root, monkeypatch)
    assert tc.metrics()["delta"]["buffer_docs"] == 41
    hits = tc.search("widgets", top_k=50, mode="bm25f")
    ids = _ids(hits)
    assert ids.count("W5") == 1 and "W7" not in ids
    assert any(i.startswith("local:L") for i in ids)
    w5 = next(h for h in hits if h["openalex_id"] == "W5")
    assert w5["title"] == "quantum widgets beta"
    assert "W7" not in _ids(tc.search("gamma", top_k=10, mode="bm25f"))
    assert tc.fetch_abstracts(["local:L3"])["local:L3"] == "local abstract 3 widgets"

    monkeypatch.setattr(tc, "_seismic_backend", lambda: _FakeSeismic())
    import lib.opensearch_retriever as osr
    monkeypatch.setattr(osr, "encode_splade", _fake_encode)
    sp = _ids(tc.search("widgets beta", top_k=50, mode="splade"))
    assert sp.count("W5") == 1 and "W7" not in sp and "W1" in sp
    assert any(i.startswith("local:L") for i in sp)
    assert sp[0] == "W5"

    # re-ingesting the same file: everything unchanged, nothing re-staged
    _ingest(base_root, _write_jsonl(tmp_path / "batch1b.jsonl", rows[:-1]))
    out = json.loads(capsys.readouterr().out)
    assert out["unchanged"] == 41 and out["new"] == 0 and out["updated"] == 0

    # freeze -> generation 1
    cli.main(["flush", "--force", "--index-root", str(base_root), "--profile", "laptop", "--no-seismic"])
    out = json.loads(capsys.readouterr().out)
    assert out["frozen_generation"] == 1 and out["frozen_docs"] == 41
    assert (base_root / "delta" / "g0001" / "generation.json").exists()
    info = tc.reload()
    assert tc.metrics()["delta"]["buffer_docs"] == 0
    assert [g["gen"] for g in tc.metrics()["delta"]["generations"]] == [1]
    hits = tc.search("widgets", top_k=50, mode="bm25f")
    ids = _ids(hits)
    assert ids.count("W5") == 1 and "W7" not in ids and len([i for i in ids if i.startswith("local:")]) == 40
    assert next(h for h in hits if h["openalex_id"] == "W5")["title"] == "quantum widgets beta"
    assert tc.fetch_abstracts(["local:L3"])["local:L3"] == "local abstract 3 widgets"
    assert any(n.startswith("delta_g0001:") for n in info["live_sections"])

    # second generation updates W5 again + adds 5 docs
    rows2 = [{"id": f"M{i}", "title": f"widgets more {i}", "abstract": "more widgets", "year": 2025,
              "sparse_field": _sparse("widgets")} for i in range(5)]
    rows2.append({"id": "W5", "title": "quantum widgets delta", "abstract": "third abstract widgets",
                  "year": 2016, "type": "article", "doi": "10.1/5", "sparse_field": _sparse("widgets", "delta")})
    _ingest(base_root, _write_jsonl(tmp_path / "batch2.jsonl", rows2))
    capsys.readouterr()
    cli.main(["flush", "--force", "--index-root", str(base_root), "--profile", "laptop", "--no-seismic"])
    capsys.readouterr()
    tc.reload()
    hits = tc.search("widgets", top_k=60, mode="bm25f")
    ids = _ids(hits)
    assert ids.count("W5") == 1
    assert next(h for h in hits if h["openalex_id"] == "W5")["title"] == "quantum widgets delta"
    assert len([i for i in ids if i.startswith("local:")]) == 45

    # compaction: gens 1+2 -> 3
    cli.main(["compact", "--gens", "1,2", "--index-root", str(base_root), "--profile", "laptop", "--no-seismic"])
    out = json.loads(capsys.readouterr().out)
    assert out["compacted"] == [1, 2] and out["into"] == 3
    assert (base_root / "delta" / "g0001.compacted").exists() and (base_root / "delta" / "g0003").exists()
    tc.reload()
    assert [g["gen"] for g in tc.metrics()["delta"]["generations"]] == [3]
    hits = tc.search("widgets", top_k=60, mode="bm25f")
    ids = _ids(hits)
    assert ids.count("W5") == 1 and "W7" not in ids
    assert next(h for h in hits if h["openalex_id"] == "W5")["title"] == "quantum widgets delta"
    assert len([i for i in ids if i.startswith("local:")]) == 45

    # gate off: the base index is untouched and serves the stale copies
    monkeypatch.delenv("SFU_DELTA_ROOT")
    tc2 = ThinClientRetriever(index_root=str(base_root), remote_abstracts=False)
    ids = _ids(tc2.search("widgets", top_k=50, mode="bm25f"))
    assert "W5" in ids and not any(i.startswith("local:") for i in ids)
    assert tc2.metrics()["delta"] is None


def test_openalex_normalizer_and_snapshot_planning():
    work = {"id": "https://openalex.org/W123", "title": "T", "publication_year": 2020,
            "doi": "https://doi.org/10.1/x", "open_access": {"is_oa": True}, "type": "article",
            "abstract_inverted_index": {"hello": [0], "world": [1, 3], "again": [2]},
            "updated_date": "2026-09-01", "cited_by_count": 3}
    rec = normalize_openalex_work(work, min_abstract_chars=5)
    assert rec.id == "W123" and rec.doi == "10.1/x" and rec.abstract == "hello world again world"
    assert rec.is_oa and rec.year == 2020 and rec.is_openalex()
    assert normalize_openalex_work({**work, "is_xpac": True}, min_abstract_chars=5) is None
    assert normalize_openalex_work({**work, "abstract_inverted_index": {}}) is None
    a, b = DocRecord(id="W1", title="t", abstract="a"), DocRecord(id="W1", title="t", abstract="a", extra={"cited_by_count": 9})
    assert a.content_hash() == b.content_hash()
    assert a.encode_hash() != DocRecord(id="W1", title="t2", abstract="a").encode_hash()
    assert DocRecord(id="W1", title="t", abstract="a", year=1999).content_hash() != a.content_hash()

    manifest = {"entries": [
        {"url": "s3://x/works/updated_date=2026-06-01/part_000.gz"},
        {"url": "s3://x/works/updated_date=2026-07-15/part_000.gz"},
        {"url": "s3://x/works/updated_date=2026-07-15/part_001.gz"},
        {"url": "s3://x/works/updated_date=2026-09-20/part_000.gz"}]}
    parts = select_new_parts(manifest, "2026-07-15", {"updated_date=2026-09-20/part_000.gz"})
    assert parts == []
    parts = select_new_parts(manifest, "2026-07-01", set())
    assert [p["url"].rsplit("/", 2)[-2:] for p in parts] == [
        ["updated_date=2026-07-15", "part_000.gz"], ["updated_date=2026-07-15", "part_001.gz"],
        ["updated_date=2026-09-20", "part_000.gz"]]


def test_jsonl_adapter_mapping_and_resume(tmp_path):
    p = _write_jsonl(tmp_path / "a.jsonl", [
        {"arxiv_id": "2401.00001", "summary": "an abstract", "title": "t1", "published": "2024-01-02"},
        {"arxiv_id": "2401.00002", "summary": "another", "title": "t2", "published": "2024-02-02"},
        {"_delete": "2312.99999"}])
    ad = JsonlAdapter(p, namespace="arxiv", mapping={"arxiv_id": "id", "summary": "abstract", "published": "year"})
    state = {}
    recs = list(ad.iter_records(state))
    assert [r.id for r in recs] == ["arxiv:2401.00001", "arxiv:2401.00002"]
    assert recs[0].year == 2024 and recs[0].section().endswith("__recent")
    assert list(ad.iter_deletions(state)) == ["arxiv:2312.99999"]
    assert state["offset"] == p.stat().st_size
    assert list(ad.iter_records(state)) == []


def test_ledger_masks_and_history(tmp_path, base_root):
    led = IngestLedger(tmp_path / "ledger.sqlite")
    base = BaseIndex(base_root)
    r = DocRecord(id="W5", title="x", abstract="y", sparse_field={"a": 1.0})
    n = DocRecord(id="local:1", title="x", abstract="y", sparse_field={"a": 1.0})
    inb = base.contains(["W5", "local:1"])
    assert inb == {"W5": True, "local:1": False}
    led.stage([r, n], inb)
    assert led.mask() == {"deleted": [], "superseded": {"W5": 0}}
    g = led.next_generation()
    led.open_generation(g, [r, n])
    led.finish_generation(g, {})
    assert led.mask()["superseded"] == {"W5": 1}
    led.stage([DocRecord(id="local:1", title="x2", abstract="y", sparse_field={"a": 1.0})], inb)
    assert led.mask()["superseded"] == {"W5": 1, "local:1": 0}
    assert led.reusable_sparse([DocRecord(id="local:1", title="x2", abstract="y")]) == {"local:1": {"a": 1.0}}
    assert led.reusable_sparse([DocRecord(id="local:1", title="x3", abstract="y")]) == {}
    led.delete(["W5"], inb)
    assert led.mask()["deleted"] == ["W5"]
    led.close()
    base.close()


_C1A = REPO / "spike/seismic_upstream/target/release/c1a_mmap_index"


@pytest.mark.skipif(not _C1A.is_file(), reason="c1a_mmap_index not built")
def test_seismic_delta_shard_chain(tmp_path, monkeypatch):
    pytest.importorskip("seismic")
    vocab = ["cell", "receptor", "kinase", "membrane", "signal", "protein", "gene", "assay"]
    recs = [DocRecord(id=f"W{9000000 + i}", title=f"bio {i}", abstract="cell receptor study",
                      year=2024, sparse_field={t: (3.0 if i < 5 and t == "kinase" else 0.5) for t in vocab})
            for i in range(200)]
    delta_root = tmp_path / "delta"
    delta_root.mkdir()
    d = build_generation(delta_root, 1, recs, PROFILES["laptop"].with_overrides(max_rss_gb=0), seismic=True)
    gi = json.loads((d / "generation.json").read_text())
    if gi["seismic"]["status"] != "served":
        pytest.skip(f"seismic chain unavailable here: {gi['seismic']['stages']}")
    from lib.thinclient.sharded_seismic_backend import ParallelSeismicBackend
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"n_shards": 1, "shards": [{"shard": "delta", "mmap_dir": str(d / gi["seismic"]["mmap_dir"])}]}))
    import lib.opensearch_retriever as osr
    monkeypatch.setattr(osr, "encode_splade", lambda q, p: {"kinase": 2.0})
    be = ParallelSeismicBackend.from_manifest(str(manifest), load_mode="mmap")
    res = be.search("kinase", 5)
    assert {d for d, _ in res} == {f"W{9000000 + i}" for i in range(5)}
