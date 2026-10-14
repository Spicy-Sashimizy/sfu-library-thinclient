"""Delta-layer buffer staleness (docs/delta_ingest/02_DESIGN.md §3.1 O1) and
the `--ordinal-dir` CLI flag (O9).

O1: a `DeltaLayer` loaded while the L0 buffer was empty must still serve docs
buffered later through the SPLADE buffer leg (`_delta_merge_sparse` gates on
`buffer_size()`), not only through BM25F / meta / abstract lookups.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
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


def _ingest(root, path):
    cli.main(["ingest", "--source", "jsonl", "--path", str(path), "--index-root", str(root),
              "--profile", "laptop", "--rate", "0", "--no-encode", "--no-seismic",
              "--namespace", "local"])


def _rows(prefix, n, term):
    return [{"id": f"{prefix}{i}", "title": f"{term} {prefix} {i}", "abstract": f"{term} abstract {prefix}{i}",
             "year": 2024, "type": "article", "sparse_field": {term: 1.0, f"{prefix}{i}": 1.0}}
            for i in range(n)]


class _FakeSeismic:
    def search(self, query, fetch, **kw):
        return [("W1", 0.5), ("W2", 0.4)]


def _fake_encode(query, model_path):
    return {t: 1.0 for t in query.split()}


def test_buffer_leg_sees_docs_buffered_after_empty_load(base_root, tmp_path, monkeypatch, capsys):
    src = tmp_path / "b1.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in _rows("A", 3, "gizmos")) + "\n")
    _ingest(base_root, src)
    cli.main(["flush", "--force", "--index-root", str(base_root), "--profile", "laptop", "--no-seismic"])
    capsys.readouterr()

    monkeypatch.setenv("SFU_DELTA_ROOT", "1")
    monkeypatch.setenv("SFU_SPLADE_BACKEND", "seismic")
    monkeypatch.delenv("SFU_SEISMIC_SHARD_MANIFEST", raising=False)
    tc = ThinClientRetriever(index_root=str(base_root), remote_abstracts=False)
    tc._load()
    monkeypatch.setattr(tc, "_seismic_backend", lambda: _FakeSeismic())
    import lib.opensearch_retriever as osr
    monkeypatch.setattr(osr, "encode_splade", _fake_encode)
    assert tc._delta.buffer_size() == 0
    before = [h["openalex_id"] for h in tc.search("sprockets", top_k=20, mode="splade")]
    assert not any(i.startswith("local:B") for i in before)

    src2 = tmp_path / "b2.jsonl"
    src2.write_text("\n".join(json.dumps(r) for r in _rows("B", 4, "sprockets")) + "\n")
    _ingest(base_root, src2)
    capsys.readouterr()

    assert tc._delta.buffer_size() == 4
    sp = [h["openalex_id"] for h in tc.search("sprockets", top_k=20, mode="splade")]
    assert {f"local:B{i}" for i in range(4)} <= set(sp)
    bm = [h["openalex_id"] for h in tc.search("sprockets", top_k=20, mode="bm25f")]
    assert {f"local:B{i}" for i in range(4)} <= set(bm)
    assert tc.fetch_abstracts(["local:B2"])["local:B2"] == "sprockets abstract B2"
    assert tc._meta_rows(["local:B1"])["local:B1"][1] == "sprockets B 1"

    sig = tc._delta._buffer_sig
    calls = []
    real = tc._delta._ledger

    class _Spy:
        def execute(self, *a, **kw):
            calls.append(a[0])
            return real.execute(*a, **kw)

        def close(self):
            real.close()

    tc._delta._ledger = _Spy()
    for _ in range(5):
        tc._delta.buffer_size()
    assert calls == [] and tc._delta._buffer_sig == sig
    tc._delta._ledger = real


def test_ordinal_dir_flag_reaches_publish(base_root, tmp_path, monkeypatch, capsys):
    """O9: --ordinal-dir is threaded to generation.publish from every
    publishing subcommand; SFU_THINCLIENT_ORDINALS stays the fallback."""
    import spike.delta_ingest.livedocs as ld
    seen = []

    def fake_publish_livedocs(delta_root, stamp, od, deleted, base_sup):
        seen.append(Path(od))
        return None, deleted

    monkeypatch.setattr(ld, "publish_livedocs", fake_publish_livedocs)
    monkeypatch.delenv("SFU_THINCLIENT_ORDINALS", raising=False)
    ords = tmp_path / "ords"
    common = ["--index-root", str(base_root), "--profile", "laptop", "--no-seismic"]

    src = tmp_path / "o1.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in _rows("C", 2, "cogs")) + "\n")
    cli.main(["ingest", "--source", "jsonl", "--path", str(src), "--rate", "0", "--no-encode",
              "--namespace", "local", *common])
    assert seen == []
    cli.main(["ingest", "--source", "jsonl", "--path", str(src), "--rate", "0", "--no-encode",
              "--namespace", "local", "--ordinal-dir", str(ords), *common])
    assert seen == [ords]
    cli.main(["flush", "--force", "--ordinal-dir", str(ords), *common])
    src2 = tmp_path / "o2.jsonl"
    src2.write_text("\n".join(json.dumps(r) for r in _rows("D", 2, "cogs")) + "\n")
    cli.main(["ingest", "--source", "jsonl", "--path", str(src2), "--rate", "0", "--no-encode",
              "--namespace", "local", *common])
    cli.main(["flush", "--force", "--ordinal-dir", "ords_rel", *common])
    cli.main(["compact", "--gens", "1,2", "--ordinal-dir", str(ords), *common])
    cli.main(["publish", "--ordinal-dir", str(ords), *common])
    assert seen == [ords, ords, base_root / "ords_rel", ords, ords]
    monkeypatch.setenv("SFU_THINCLIENT_ORDINALS", str(tmp_path / "env_ords"))
    cli.main(["publish", *common])
    assert seen[-1] == tmp_path / "env_ords"
    cli.main(["publish", "--ordinal-dir", str(ords), *common])
    assert seen[-1] == ords
    capsys.readouterr()
