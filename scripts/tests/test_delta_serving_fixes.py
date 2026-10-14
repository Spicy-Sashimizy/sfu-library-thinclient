"""Delta-layer serving fixes 2026-10-01 (docs/delta_ingest/02_DESIGN.md §3.1):
the buffer-section-missing-at-load gap (O1 follow-up), O2 (published but not
yet reloaded generations vanish from the SPLADE buffer leg) and O16 (delta
root resolution). Synthetic roots only; no real index is loaded.
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


COMMON = ["--profile", "laptop", "--no-seismic"]


def _ingest(root, path):
    cli.main(["ingest", "--source", "jsonl", "--path", str(path), "--index-root", str(root),
              "--rate", "0", "--no-encode", "--namespace", "local", *COMMON])


def _write(tmp_path, name, prefix, n, term):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(
        {"id": f"{prefix}{i}", "title": f"{term} {prefix} {i}", "abstract": f"{term} abstract {prefix}{i}",
         "year": 2024, "type": "article", "sparse_field": {term: 1.0, f"{prefix}{i}": 1.0}})
        for i in range(n)) + "\n")
    return p


class _FakeSeismic:
    def search(self, query, fetch, **kw):
        return [("W1", 0.5), ("W2", 0.4)]


def _retriever(root, monkeypatch):
    monkeypatch.setenv("SFU_DELTA_ROOT", "1")
    monkeypatch.setenv("SFU_SPLADE_BACKEND", "seismic")
    monkeypatch.delenv("SFU_SEISMIC_SHARD_MANIFEST", raising=False)
    tc = ThinClientRetriever(index_root=str(root), remote_abstracts=False)
    tc._load()
    monkeypatch.setattr(tc, "_seismic_backend", lambda: _FakeSeismic())
    import lib.opensearch_retriever as osr
    monkeypatch.setattr(osr, "encode_splade", lambda q, m: {t: 1.0 for t in q.split()})
    return tc


def _ids(tc, q, mode):
    return {h["openalex_id"] for h in tc.search(q, top_k=20, mode=mode)}


def test_buffer_section_created_after_load_is_searched(base_root, tmp_path, monkeypatch, capsys):
    """Gap: the layer loaded before the buffer's tantivy dir existed, so
    BM25F never searched `delta_buffer` until `reload()`."""
    (base_root / "delta").mkdir()
    tc = _retriever(base_root, monkeypatch)
    assert "delta_buffer" not in tc._sections
    assert not any(i.startswith("local:") for i in _ids(tc, "widgets", "bm25f"))

    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "widgets"))
    capsys.readouterr()
    want = {f"local:A{i}" for i in range(3)}
    assert want <= _ids(tc, "widgets", "bm25f")
    assert want <= _ids(tc, "widgets", "splade")
    assert tc._sections["delta_buffer"]["delta_origin"] == "buffer"


def test_frozen_generation_stays_visible_until_reload(base_root, tmp_path, monkeypatch, capsys):
    """O2: a freeze moves records out of the buffer view at
    `finish_generation`, but serving only loads the new generation on
    `reload()`; in between the SPLADE buffer leg must still serve them."""
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "gadgets"))
    tc = _retriever(base_root, monkeypatch)
    want = {f"local:A{i}" for i in range(3)}
    assert tc._delta.buffer_size() == 3
    assert want <= _ids(tc, "gadgets", "splade")

    cli.main(["flush", "--force", "--index-root", str(base_root), *COMMON])
    capsys.readouterr()
    assert tc._delta.buffer_size() == 3
    assert want <= _ids(tc, "gadgets", "splade")
    assert tc.fetch_abstracts(["local:A1"])["local:A1"] == "gadgets abstract A1"

    tc.reload()
    assert tc._delta.buffer_size() == 0
    assert [g["gen"] for g in tc._delta.generations] == [1]
    assert want <= _ids(tc, "gadgets", "bm25f")


def test_compaction_of_loaded_generations_is_not_pulled_into_buffer(base_root, tmp_path,
                                                                   monkeypatch, capsys):
    """O2 guard: a compaction output whose sources are already served by
    loaded generations must not be parsed into the buffer view."""
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "gears"))
    cli.main(["flush", "--force", "--index-root", str(base_root), *COMMON])
    _ingest(base_root, _write(tmp_path, "b.jsonl", "B", 2, "gears"))
    cli.main(["flush", "--force", "--index-root", str(base_root), *COMMON])
    tc = _retriever(base_root, monkeypatch)
    assert [g["gen"] for g in tc._delta.generations] == [1, 2]
    assert tc._delta.buffer_size() == 0

    cli.main(["compact", "--gens", "1,2", "--index-root", str(base_root), *COMMON])
    _ingest(base_root, _write(tmp_path, "c.jsonl", "C", 2, "gears"))
    capsys.readouterr()
    assert tc._delta.buffer_size() == 2
    assert set(tc._delta._buffer_rows) == {"local:C0", "local:C1"}


def test_unloaded_compaction_of_unloaded_freezes_stays_visible(base_root, tmp_path,
                                                               monkeypatch, capsys):
    """O2: freeze g1, freeze g2, compact g1+g2 -> g3, all after the layer
    loaded: g3 holds only docs that were buffered, so it counts as buffer."""
    (base_root / "delta").mkdir()
    tc = _retriever(base_root, monkeypatch)
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "cogs"))
    cli.main(["flush", "--force", "--index-root", str(base_root), *COMMON])
    _ingest(base_root, _write(tmp_path, "b.jsonl", "B", 2, "cogs"))
    cli.main(["flush", "--force", "--index-root", str(base_root), *COMMON])
    cli.main(["compact", "--gens", "1,2", "--index-root", str(base_root), *COMMON])
    capsys.readouterr()
    assert tc._delta.generations == []
    assert tc._delta.buffer_size() == 5
    assert {f"local:A{i}" for i in range(3)} | {"local:B0", "local:B1"} <= _ids(tc, "cogs", "splade")


def test_gate_off_has_no_delta_layer(base_root, monkeypatch):
    monkeypatch.delenv("SFU_DELTA_ROOT", raising=False)
    (base_root / "delta").mkdir()
    tc = ThinClientRetriever(index_root=str(base_root), remote_abstracts=False)
    tc._load()
    assert tc._delta is None
    tc._delta_attach_buffer_section()
    assert "delta_buffer" not in tc._sections


def test_building_compaction_of_loaded_generation_not_in_buffer(base_root, tmp_path,
                                                                monkeypatch, capsys):
    """O2 guard (building phase): while a compaction of loaded generations
    builds, its docs are still served by those generations; the buffer view
    must not parse them (it did before 2026-10-01: every `building` gen)."""
    from spike.delta_ingest.ledger import IngestLedger
    _ingest(base_root, _write(tmp_path, "a.jsonl", "A", 3, "bolts"))
    cli.main(["flush", "--force", "--index-root", str(base_root), *COMMON])
    capsys.readouterr()
    tc = _retriever(base_root, monkeypatch)
    assert tc._delta.buffer_size() == 0
    led = IngestLedger(base_root / "delta" / "ledger.sqlite")
    led.open_generation(2, led.records_for([1]), from_gens=[1])
    led.close()
    assert tc._delta.buffer_size() == 0


def test_resolve_delta_root(tmp_path, monkeypatch):
    """O16: one resolver for serving and writers; writers refuse
    data/seismic_150m and an implicit default under the repo's data/."""
    from lib.thinclient.delta_layer import REPO_DATA_DIR, DeltaLayer, resolve_delta_root
    monkeypatch.delenv("SFU_DELTA_ROOT", raising=False)
    idx = tmp_path / "index"
    assert resolve_delta_root(idx) == idx / "delta"
    assert resolve_delta_root(idx, "1") == idx / "delta"
    assert resolve_delta_root(idx, str(tmp_path / "d")) == tmp_path / "d"
    assert resolve_delta_root(idx, for_write=True) == idx / "delta"
    monkeypatch.setenv("SFU_DELTA_ROOT", str(tmp_path / "env"))
    assert resolve_delta_root(idx) == tmp_path / "env"
    assert resolve_delta_root(idx, str(tmp_path / "x")) == tmp_path / "x"
    monkeypatch.setenv("SFU_DELTA_ROOT", "1")
    assert resolve_delta_root(idx) == idx / "delta"

    served = REPO_DATA_DIR / "thinclient_index"
    assert resolve_delta_root(served) == served / "delta"
    with pytest.raises(ValueError, match="implicit"):
        resolve_delta_root(served, for_write=True)
    monkeypatch.delenv("SFU_DELTA_ROOT", raising=False)
    with pytest.raises(ValueError, match="implicit"):
        resolve_delta_root(served, for_write=True)
    assert resolve_delta_root(served, str(served / "delta"), for_write=True) == served / "delta"
    with pytest.raises(ValueError, match="read-only"):
        resolve_delta_root(idx, str(REPO_DATA_DIR / "seismic_150m" / "delta"), for_write=True)
    with pytest.raises(ValueError, match="read-only"):
        resolve_delta_root(REPO_DATA_DIR / "seismic_150m", "1", for_write=True)

    assert DeltaLayer.load_if_enabled(idx) is None
    monkeypatch.setenv("SFU_DELTA_ROOT", "")
    assert DeltaLayer.load_if_enabled(idx) is None


def test_o13_nonlatin_plain_fallback_decodes_with_latin_dict(tmp_path, monkeypatch):
    """O13 (code reading): a non-latin bucket that reaches the training bar
    before latin and fails training is compressed PLAIN, while the reader
    later decodes it with the latin dict. Pinned here as benign: a frame
    written without a dict (dictID 0) decodes identically under any dict."""
    import zstandard

    import lib.thinclient.abstracts as ab
    monkeypatch.setattr(ab, "TRAIN_TARGET_DOCS", 400)
    real = zstandard.train_dictionary
    calls = []

    def flaky(size, samples, *a, **kw):
        calls.append(len(samples))
        if len(calls) == 1:
            raise zstandard.ZstdError("forced failure for the first (cyrillic) bucket")
        return real(size, samples, *a, **kw)

    monkeypatch.setattr(zstandard, "train_dictionary", flaky)
    path = tmp_path / "abstracts.sqlite"
    w = ab.AbstractStoreWriter(path)
    ru = {f"R{i}": f"Аннотация номер {i} о выборах и политике региона {i % 17}" for i in range(400)}
    for k, v in ru.items():
        w.add(k, v)
    assert ab.script_bucket(ru["R1"]) != "latin" and len(calls) == 1
    words = ["policy", "election", "study", "vote", "party", "reform", "market", "labour"]
    la = {f"L{i}": " ".join(words[(i + j) % 8] for j in range(40)) + f" case {i}" for i in range(400)}
    for k, v in la.items():
        w.add(k, v)
    w.finish()
    assert len(calls) == 2
    import sqlite3
    keys = {r[0] for r in sqlite3.connect(path).execute("SELECT k FROM meta WHERE k LIKE 'zdict_%'")}
    assert keys == {"zdict_latin"}
    store = ab.AbstractStore(path)
    got = store.fetch(list(ru) + list(la))
    assert got == {**ru, **la}
