"""O2 BM25F residual (docs/delta_ingest/02_DESIGN.md §3.1): after a freeze,
the frozen docs must stay visible to the BM25F leg until serving `reload()`s
the new generation, without duplicates once it has, and the buffer tantivy
must not keep frozen docs forever. Synthetic tmp roots only; no real index."""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from lib.thinclient.builder import SectionBuilder, open_meta_db  # noqa: E402
from lib.thinclient.retriever import ThinClientRetriever  # noqa: E402
from spike.delta_ingest import cli  # noqa: E402


@pytest.fixture
def base_root(tmp_path):
    root = tmp_path / "index"
    root.mkdir()
    meta = open_meta_db(root)
    b = SectionBuilder(root, "social_sciences__recent", hot=True, meta_db=meta)
    for i in range(1, 301):
        b.add({"id": f"W{i}", "title": f"politics paper {i}",
               "abstract": f"policy study number {i} about elections",
               "publication_year": 2015 + i % 5, "type": "article", "is_oa": i % 2 == 0,
               "doi": f"10.1/{i}"})
    b.finish()
    meta.commit()
    meta.close()
    (root / "manifest.json").write_text(json.dumps({"sections": {}, "persona": "all_hot"}))
    return root


COMMON = ["--profile", "laptop", "--no-seismic"]


def _ingest(root, path, *extra):
    cli.main(["ingest", "--source", "jsonl", "--path", str(path), "--index-root", str(root),
              "--rate", "0", "--no-encode", "--namespace", "local", *COMMON, *extra])


def _flush(root):
    cli.main(["flush", "--force", "--index-root", str(root), *COMMON])


def _write(tmp_path, name, prefix, n, term):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(
        {"id": f"{prefix}{i}", "title": f"{term} {prefix} {i}", "abstract": f"{term} abstract {prefix}{i}",
         "year": 2024, "type": "article"}) for i in range(n)) + "\n")
    return p


def _retriever(root, monkeypatch):
    monkeypatch.setenv("SFU_DELTA_ROOT", "1")
    monkeypatch.setenv("SFU_SPLADE_BACKEND", "seismic")
    monkeypatch.delenv("SFU_SEISMIC_SHARD_MANIFEST", raising=False)
    tc = ThinClientRetriever(index_root=str(root), remote_abstracts=False)
    tc._load()
    return tc


def _bm25f(tc, q):
    return [d for d, _ in tc._bm25f_leg(q, 50, None)]


def _buffer_tantivy_ids(root):
    import tantivy
    idx = tantivy.Index.open(str(root / "delta" / "buffer" / "delta_buffer" / "tantivy"))
    idx.reload()
    s = idx.searcher()
    if not s.num_docs:
        return set()
    return {s.doc(a)["id"][0] for _, a in s.search(tantivy.Query.all_query(), s.num_docs).hits}


def test_frozen_docs_bm25f_visible_until_reload(base_root, tmp_path, monkeypatch, capsys):
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "sprockets"))
    tc = _retriever(base_root, monkeypatch)
    want = {f"local:A{i}" for i in range(3)}
    assert want <= set(_bm25f(tc, "sprockets"))

    _flush(base_root)
    capsys.readouterr()
    assert want <= set(_bm25f(tc, "sprockets"))

    tc.reload()
    hits = _bm25f(tc, "sprockets")
    assert want <= set(hits)
    assert max(Counter(hits).values()) == 1


def test_no_duplicate_bm25f_hits_after_ingest_auto_freeze(base_root, tmp_path, monkeypatch, capsys):
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 4, "flanges"), "--flush-docs", "2")
    capsys.readouterr()
    tc = _retriever(base_root, monkeypatch)
    assert [g["gen"] for g in tc._delta.generations] == [1]
    hits = _bm25f(tc, "flanges")
    assert {f"local:A{i}" for i in range(4)} <= set(hits)
    assert max(Counter(hits).values()) == 1, Counter(hits).most_common(3)


def test_buffer_tantivy_keeps_only_buffer_and_last_frozen(base_root, tmp_path, monkeypatch, capsys):
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "valves"))
    _flush(base_root)
    assert _buffer_tantivy_ids(base_root) == {f"local:A{i}" for i in range(3)}
    _ingest(base_root, _write(tmp_path, "b.jsonl", "B", 2, "valves"))
    _flush(base_root)
    _ingest(base_root, _write(tmp_path, "c.jsonl", "C", 1, "valves"))
    capsys.readouterr()
    assert _buffer_tantivy_ids(base_root) == {"local:B0", "local:B1", "local:C0"}


def test_ingest_auto_freeze_garbage_collects_older_generations(base_root, tmp_path, monkeypatch,
                                                               capsys):
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "pistons"), "--flush-docs", "2")
    _ingest(base_root, _write(tmp_path, "b.jsonl", "B", 3, "pistons"), "--flush-docs", "2")
    capsys.readouterr()
    assert _buffer_tantivy_ids(base_root) == {f"local:B{i}" for i in range(3)}


def test_deleted_buffer_doc_not_served_by_bm25f(base_root, tmp_path, monkeypatch, capsys):
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "rivets"))
    tc = _retriever(base_root, monkeypatch)
    _flush(base_root)
    tc.reload()
    _ingest(base_root, _write(tmp_path, "b.jsonl", "B", 1, "rivets"))
    capsys.readouterr()
    hits = _bm25f(tc, "rivets")
    assert {"local:A0", "local:A1", "local:A2", "local:B0"} <= set(hits)
    assert max(Counter(hits).values()) == 1
