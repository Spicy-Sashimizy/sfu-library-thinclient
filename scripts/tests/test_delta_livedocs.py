"""Delta-ingest item C (2026-09-29): livedocs tombstone bitset over base ordinals.

Format round-trip + fail-closed checks, the DeltaLayer masks (BM25F hits,
per-shard SEISMIC filter incl. the S5 superseded-base-copy case, post-merge
fallback), and the publish path end to end on the synthetic base of
test_delta_ingest.py with fake ordinal arrays.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "tests"))

from lib.thinclient.delta_layer import DeltaLayer  # noqa: E402
from lib.thinclient.livedocs import HEADER_LEN, Livedocs, LivedocsError  # noqa: E402
from lib.thinclient.sharded_seismic_backend import _merge_topk  # noqa: E402
from spike.delta_ingest.livedocs import build_bits, publish_livedocs, write_livedocs  # noqa: E402
from test_delta_ingest import N_BASE, _ids, _ingest, _retriever, _write_jsonl, base_root  # noqa: E402,F401

SPACE = "11111111-2222-3333-4444-555555555555"


def make_ordinals(d: Path, wnums: list[int], space: str = SPACE) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    n = len(wnums)
    np.save(d / "wids.npy", np.array(sorted(wnums), dtype=np.int64))
    for name, dt in (("year", np.int16), ("dtype", np.uint8), ("is_oa", np.uint8), ("section", np.uint8)):
        np.save(d / f"{name}.npy", np.zeros(n, dtype=dt))
    (d / "ordinal_space.json").write_text(json.dumps(
        {"ordinal_space_id": space, "rows": n, "codes": {"type": {"article": 1}}}))
    return d


def test_format_roundtrip_and_fail_closed(tmp_path):
    nbits = 1003
    ords = np.array([0, 7, 8, 500, 1002])
    bits = build_bits(nbits, ords)
    p = tmp_path / "a.liv"
    facts = write_livedocs(p, bits, nbits, SPACE)
    assert facts["popcount"] == 5 and facts["bytes"] == HEADER_LEN + 126
    liv = Livedocs(p, expect_space_id=SPACE, expect_crc32=facts["crc32"])
    got = liv.dead(np.arange(-2, nbits + 3))
    assert np.flatnonzero(got).tolist() == [o + 2 for o in ords.tolist()]
    liv.close()
    with pytest.raises(LivedocsError):
        Livedocs(p, expect_space_id="other")
    with pytest.raises(LivedocsError):
        Livedocs(p, expect_crc32=facts["crc32"] ^ 1)
    raw = bytearray(p.read_bytes())
    raw[HEADER_LEN + 3] ^= 0xFF
    (tmp_path / "b.liv").write_bytes(bytes(raw))
    with pytest.raises(LivedocsError):
        Livedocs(tmp_path / "b.liv")
    raw = bytearray(p.read_bytes())
    raw[0:8] = b"NOTLIV00"
    (tmp_path / "c.liv").write_bytes(bytes(raw))
    with pytest.raises(LivedocsError):
        Livedocs(tmp_path / "c.liv")
    (tmp_path / "d.liv").write_bytes(p.read_bytes()[:-1])
    with pytest.raises(LivedocsError):
        Livedocs(tmp_path / "d.liv")


def _delta_root(tmp_path, deleted, superseded_base, superseded, gens=(), shard_manifest=None):
    ordd = make_ordinals(tmp_path / "ords", list(range(1, 51)))
    root = tmp_path / "delta"
    root.mkdir()
    entry, missing = publish_livedocs(root, "g0001-1", ordd, deleted, superseded_base)
    data = {"format": 1, "stamp": "g0001-1", "generations": list(gens),
            "mask": {"deleted": missing, "superseded": superseded}, "livedocs": entry,
            "shard_manifest": shard_manifest}
    (root / "generations.json").write_text(json.dumps(data))
    return root, entry


def test_masks_and_s5(tmp_path):
    man = tmp_path / "shard_manifest.json"
    man.write_text(json.dumps({"n_shards": 3, "shards": [
        {"mmap_dir": "a"}, {"mmap_dir": "b"}, {"mmap_dir": "g1", "delta_generation": 1}]}))
    root, entry = _delta_root(tmp_path, ["W7", "local:x", "W999"], ["W5"], {"W5": 1},
                              shard_manifest=str(man))
    assert entry["deleted_in_base"] == 1 and entry["superseded_in_base"] == 1
    assert entry["deleted_without_ordinal"] == 2 and entry["popcount"] == 2
    dl = DeltaLayer(root)
    assert dl.deleted == {"local:x", "W999"}
    assert dl.base_dead(["W5", "W7", "W8", "local:x", "W999"]) == [True, True, False, False, False]
    hits = [("W5", 9.0, None), ("W5", 3.0, 1), ("W7", 8.0, None), ("W7", 2.0, 1),
            ("W8", 1.0, None), ("local:x", 1.0, 1)]
    assert dl.filter_hits(hits) == [("W5", 3.0), ("W8", 1.0)]
    assert dl.filter_ids([("W5", 9.0), ("W7", 8.0), ("W8", 1.0)]) == [("W5", 9.0), ("W8", 1.0)]

    class _Backend:
        shards = [object(), object(), object()]
        _shard_result_filter = None
    b = _Backend()
    assert dl.attach_seismic(b, str(man))
    per_shard = [[("q", 9.0, "W5"), ("q", 8.0, "W7"), ("q", 1.0, "W8")],
                 [("q", 5.0, "W9"), ("q", 0.5, "W999")],
                 [("q", 3.0, "W5"), ("q", 2.0, "W7")]]
    merged = _merge_topk(b._shard_result_filter(per_shard), 10)
    assert merged == [("W9", 5.0), ("W5", 3.0), ("W8", 1.0)]
    assert _merge_topk(per_shard, 10)[0] == ("W5", 9.0)
    assert dl.filter_ids(merged) == merged
    assert dl.info()["livedocs"]["popcount"] == 2
    dl.close()


def test_empty_bitset_is_identity(tmp_path):
    root, entry = _delta_root(tmp_path, [], [], {})
    assert entry["popcount"] == 0
    dl = DeltaLayer(root)

    class _Backend:
        shards = [object(), object()]
        _shard_result_filter = None
    b = _Backend()
    assert dl.attach_seismic(b, None)
    per_shard = [[("q", 9.0, "W5"), ("q", 1.0, "local:y")], [("q", 5.0, "W9")]]
    assert b._shard_result_filter(per_shard) == per_shard
    hits = [("W5", 9.0, None), ("W8", 1.0, 1)]
    assert dl.filter_hits(hits) == [("W5", 9.0), ("W8", 1.0)]
    assert dl.filter_ids([("W5", 9.0)]) == [("W5", 9.0)]
    dl.close()


def test_no_livedocs_key_keeps_json_path(tmp_path):
    root = tmp_path / "delta"
    root.mkdir()
    (root / "generations.json").write_text(json.dumps(
        {"stamp": "s", "generations": [], "mask": {"deleted": ["W7"], "superseded": {}}}))
    dl = DeltaLayer(root)
    assert dl.livedocs is None and not dl.attach_seismic(type("B", (), {"shards": [], "_shard_result_filter": None})(), None)
    assert dl.filter_ids([("W7", 1.0), ("W8", 0.5)]) == [("W8", 0.5)]
    dl.close()


def test_publish_writes_bitset_end_to_end(base_root, tmp_path, monkeypatch, capsys):
    ordd = make_ordinals(tmp_path / "ords", list(range(1, N_BASE + 1)))
    rows = [{"id": "W5", "title": "quantum widgets beta", "abstract": "updated abstract widgets",
             "year": 2016, "type": "article", "doi": "10.1/5"},
            {"_delete": "W7"}, {"_delete": "local:nope"}]
    monkeypatch.setenv("SFU_THINCLIENT_ORDINALS", str(ordd))
    _ingest(base_root, _write_jsonl(tmp_path / "b.jsonl", rows))
    capsys.readouterr()
    monkeypatch.delenv("SFU_THINCLIENT_ORDINALS")
    gj = json.loads((base_root / "delta" / "generations.json").read_text())
    ld = gj["livedocs"]
    assert ld["popcount"] == 2 and ld["ordinal_space_id"] == SPACE
    assert (base_root / "delta" / ld["path"]).is_file()
    assert "W7" not in gj["mask"]["deleted"]
    tc = _retriever(base_root, monkeypatch)
    assert tc._delta.base_dead(["W5", "W7", "W6"]) == [True, True, False]
    ids = _ids(tc.search("gamma", top_k=10, mode="bm25f"))
    assert "W7" not in ids
    hits = tc.search("quantum widgets", top_k=50, mode="bm25f")
    assert _ids(hits).count("W5") == 1
    assert next(h for h in hits if h["openalex_id"] == "W5")["title"] == "quantum widgets beta"


def test_reload_same_stamp_reattaches_filter(base_root, tmp_path, monkeypatch, capsys):
    ordd = make_ordinals(tmp_path / "ords", list(range(1, N_BASE + 1)))
    monkeypatch.setenv("SFU_THINCLIENT_ORDINALS", str(ordd))
    _ingest(base_root, _write_jsonl(tmp_path / "b.jsonl", [{"_delete": "W7"}]))
    capsys.readouterr()
    monkeypatch.delenv("SFU_THINCLIENT_ORDINALS")
    tc = _retriever(base_root, monkeypatch)

    class _Backend:
        shards = [object()]
        _shard_result_filter = None
    b = _Backend()
    tc._seismic = b
    tc._seismic_manifest = None
    assert tc._delta.attach_seismic(b, None)
    first = b._shard_result_filter
    old_delta = tc._delta
    tc.reload()
    assert tc._seismic is b and tc._delta is not old_delta
    assert b._shard_result_filter is not None and b._shard_result_filter is not first
    assert b._shard_result_filter([[("q", 1.0, "W7"), ("q", 0.5, "W8")]]) == [[("q", 0.5, "W8")]]
