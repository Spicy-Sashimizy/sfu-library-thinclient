"""O17 option (a): base-side is_oa bitmap — builder, reader, seeder, retriever.

Tmp trees only (never a path under data/). docs/delta_ingest/02_DESIGN.md §3.1
O17; spike/delta_ingest/OA_BITMAP_FINDINGS.md.
"""
import gzip
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

from lib.thinclient import oa_overlay as ov  # noqa: E402
from spike.delta_ingest import oa_bitmap as ob  # noqa: E402

WIDS = [10, 20, 30, 40, 50, 60, 70, 80, 90]


def _ordinals(root: Path, space: str = "space-1") -> Path:
    d = root / "ords"
    d.mkdir(parents=True)
    np.save(d / "wids.npy", np.asarray(WIDS, dtype=np.int64))
    (d / "ordinal_space.json").write_text(json.dumps(
        {"ordinal_space_id": space, "rows": len(WIDS)}))
    return d


def _index_root(root: Path) -> Path:
    r = root / "index"
    r.mkdir()
    (r / "meta.sqlite").write_bytes(b"x" * 64)
    return r


def _build(tmp_path: Path) -> tuple[Path, Path, Path]:
    ords = _ordinals(tmp_path)
    idx = _index_root(tmp_path)
    b = ob.OABitmapBuilder(tmp_path / "work", ords)
    b.ingest_unit("updated_date=2026-01-01/part_0000.gz",
                  [("W10", True), ("https://openalex.org/W20", False), ("W99", True),
                   (30, False), ("bogus", True)])
    b.ingest_unit("updated_date=2026-02-01/part_0000.gz", [("W20", True), ("W40", False)])
    out = tmp_path / "bitmap"
    stamp = b.finalize(out, idx / "meta.sqlite", {"note": "test"})
    assert stamp["coverage"] == {"known": 4, "oa": 2, "not_oa": 2, "unknown": 5,
                                 "units": 2, "repeat_hits": 1}
    return ords, idx, out


def test_builder_later_unit_wins_and_three_states(tmp_path):
    _, idx, out = _build(tmp_path)
    o = ov.OAOverlay(out, meta_path=idx / "meta.sqlite")
    assert o.states(["W10", "W20", "W30", "W40", "W50", "W99", "X1", "W010"]) == [
        True, True, False, False, None, None, None, None]


def test_unit_files_make_the_pass_resumable(tmp_path):
    ords = _ordinals(tmp_path)
    b = ob.OABitmapBuilder(tmp_path / "work", ords)
    assert not b.done("updated_date=2026-01-01/part_0000.gz")
    b.ingest_unit("updated_date=2026-01-01/part_0000.gz", [("W10", True)])
    b2 = ob.OABitmapBuilder(tmp_path / "work", ords)
    assert b2.done("updated_date=2026-01-01/part_0000.gz")
    assert not list((tmp_path / "work" / "units").glob("*.tmp.npz"))


def test_apply_rows_and_keep_oa(tmp_path):
    _, idx, out = _build(tmp_path)
    o = ov.OAOverlay(out, meta_path=idx / "meta.sqlite")
    rows = {"W10": ("W10", "t", "d", 2020, "article", 0, "s"),
            "W30": ("W30", "t", "d", 2020, "article", 0, "s"),
            "W50": ("W50", "t", "d", 2020, "article", 0, "s")}
    o.apply_rows(rows, ["W10", "W30", "W50", "W77"])
    assert [rows[k][5] for k in ("W10", "W30", "W50")] == [True, False, None]
    assert rows["W10"][:5] == ("W10", "t", "d", 2020, "article")
    hits = [("W50", 3.0, None), ("W10", 2.0, None), ("W30", 1.0, None), ("W20", 0.5, None)]
    assert o.keep_oa(hits) == [("W10", 2.0, None), ("W20", 0.5, None)]


def test_gate_unset_is_none_and_relative_path(tmp_path, monkeypatch):
    _, idx, out = _build(tmp_path)
    monkeypatch.delenv(ov.ENV, raising=False)
    assert ov.load_if_enabled(idx, {}) is None
    monkeypatch.setenv(ov.ENV, "  ")
    assert ov.load_if_enabled(idx, {}) is None
    monkeypatch.setenv(ov.ENV, os.path.relpath(out, idx))
    assert ov.load_if_enabled(idx, {}).bitmap_id


def test_fails_closed_on_meta_change(tmp_path, monkeypatch):
    _, idx, out = _build(tmp_path)
    monkeypatch.setenv(ov.ENV, str(out))
    t = time.time() + 100
    os.utime(idx / "meta.sqlite", (t, t))
    with pytest.raises(ov.OABitmapMismatch):
        ov.load_if_enabled(idx, {})


def test_fails_closed_on_ordinal_space_and_manifest(tmp_path, monkeypatch):
    ords, idx, out = _build(tmp_path)
    monkeypatch.setenv(ov.ENV, str(out))
    with pytest.raises(ov.OABitmapMismatch):
        ov.load_if_enabled(idx, {"ordinal_space_id": "other"})
    (ords / "ordinal_space.json").write_text(json.dumps({"ordinal_space_id": "x", "rows": 9}))
    with pytest.raises(ov.OABitmapMismatch):
        ov.load_if_enabled(idx, {})


def test_fails_closed_without_meta(tmp_path, monkeypatch):
    _, idx, out = _build(tmp_path)
    (idx / "meta.sqlite").unlink()
    monkeypatch.setenv(ov.ENV, str(out))
    with pytest.raises(ov.OABitmapMismatch):
        ov.load_if_enabled(idx, {})


def test_bitmap_id_tracks_content(tmp_path):
    ords, idx, out = _build(tmp_path)
    id1 = json.loads((out / ov.STAMP_FILE).read_text())["bitmap_id"]
    b = ob.OABitmapBuilder(tmp_path / "work", ords)
    b.ingest_unit("updated_date=2026-03-01/part_0000.gz", [("W30", True)])
    st = b.finalize(tmp_path / "bitmap2", idx / "meta.sqlite", {})
    assert st["bitmap_id"] != id1


def test_openalex_line_scanner(tmp_path):
    compact = (b'{"id":"https://openalex.org/W10","title":"x","open_access":{"is_oa":true,'
               b'"oa_status":"gold"},"locations":[{"is_oa":false}]}\n')
    spaced = json.dumps({"id": "https://openalex.org/W20",
                         "open_access": {"is_oa": False}}).encode() + b"\n"
    missing = json.dumps({"id": "https://openalex.org/W30"}).encode() + b"\n"
    p = tmp_path / "part.gz"
    with gzip.open(p, "wb") as fh:
        fh.write(compact + spaced + missing + b"\nnot json\n")
    st: dict = {}
    with ob.open_partition(str(p)) as fh:
        got = list(ob.iter_openalex_lines(fh, st))
    assert got == [(10, True), (20, False)]
    assert st["records"] == 4 and st["json_fallback"] == 3
    assert st["no_oa_field"] == 1 and st["bad_json"] == 1


def test_pairs_from_any_adapter(tmp_path):
    from spike.delta_ingest.adapters import JsonlAdapter
    src = tmp_path / "custom.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in [
        {"id": "https://openalex.org/W10", "title": "a", "open_access": {"is_oa": True}, "abstract": "a" * 60,
         "publication_year": 2020},
        {"id": "https://openalex.org/W20", "title": "b", "open_access": {"is_oa": False}, "abstract": "b" * 60,
         "publication_year": 2020}]) + "\n")
    pairs = list(ob.pairs_from_adapter(JsonlAdapter(src, openalex_shape=True)))
    assert pairs == [("W10", True), ("W20", False)]


class _Store:
    def fetch(self, ids):
        return {i: f"abstract of {i}" for i in ids}


def test_seed_with_bitmap_makes_is_oa_only_flip_unchanged(tmp_path, monkeypatch):
    """O17 ingest: with the bitmap, an in-base OA work whose only difference
    from meta is is_oa classifies as unchanged (no delta copy); without it,
    the same record is an update."""
    from spike.delta_ingest import seed as seedmod
    from spike.delta_ingest.ledger import IngestLedger
    from spike.delta_ingest.records import DocRecord

    _, idx, out = _build(tmp_path)
    monkeypatch.delenv(ov.ENV, raising=False)
    rows = [(10, "T10", "10.1/a", 2020, "article", 0, "sec"),
            (30, "T30", "10.1/c", 2020, "article", 0, "sec"),
            (50, "T50", "10.1/e", 2020, "article", 0, "sec")]

    def classify(overlay, name):
        led = IngestLedger(tmp_path / f"{name}.sqlite")
        s = seedmod.BaseSeeder.__new__(seedmod.BaseSeeder)
        s.oa = overlay
        s.roots, s._stores = [], {"sec": _Store()}
        import collections
        s.stats, s.skipped_by_section = collections.Counter(), collections.Counter()
        s.timers = collections.Counter()
        recs = s.records_for_rows(rows)
        led.seed_base([(r.id, r.content_hash(), r.encode_hash()) for r in recs])
        snap = [DocRecord(id=r.id, title=r.title, abstract=r.abstract, year=r.year, type=r.type,
                          is_oa=oa, doi=r.doi, source="openalex_snapshot")
                for r, oa in zip(recs, (True, False, True))]
        res = led.classify(snap, {r.id: True for r in snap})
        led.close()
        return {k: sorted(x.id for x in v) for k, v in res.items()}, dict(s.stats)

    off, _ = classify(None, "off")
    assert off["updated"] == ["W10", "W50"] and off["unchanged"] == ["W30"]
    on, stats = classify(ov.OAOverlay(out, meta_path=idx / "meta.sqlite"), "on")
    assert on["unchanged"] == ["W10", "W30"] and on["updated"] == ["W50"]
    assert stats == {"is_oa_from_bitmap": 2, "is_oa_bitmap_unknown": 1}


def test_seeder_reads_gate_when_no_overlay_passed(tmp_path, monkeypatch):
    from spike.delta_ingest import seed as seedmod
    from spike.delta_ingest.ledger import IngestLedger
    import sqlite3

    _, idx, out = _build(tmp_path)
    meta = tmp_path / "real_meta.sqlite"
    sqlite3.connect(meta).close()
    led = IngestLedger(tmp_path / "l.sqlite")
    monkeypatch.delenv(ov.ENV, raising=False)
    assert seedmod.BaseSeeder(idx, led, meta_path=meta).oa is None
    assert seedmod.BaseSeeder(idx, led, meta_path=meta, oa_overlay=False).oa is None
    monkeypatch.setenv(ov.ENV, str(out))
    assert seedmod.BaseSeeder(idx, led, meta_path=meta).oa is not None
    assert seedmod.BaseSeeder(idx, led, meta_path=meta, oa_overlay=False).oa is None
    led.close()


def _tiny_root(tmp_path: Path, n: int = 600) -> Path:
    from lib.thinclient.builder import SectionBuilder, open_meta_db
    root = tmp_path / "root"
    root.mkdir()
    meta = open_meta_db(root)
    b = SectionBuilder(root, "social_sciences__recent", hot=True, meta_db=meta)
    for i in range(1, n + 1):
        b.add({"id": f"W{i}", "title": f"politics paper {i}", "abstract": f"politics text {i}",
               "publication_year": 2015, "type": "article", "doi": f"10.1/{i}"})
    b.finish()
    meta.commit()
    meta.close()
    return root


def _root_bitmap(tmp_path: Path, root: Path) -> Path:
    import sqlite3
    db = sqlite3.connect(root / "meta.sqlite")
    ids = sorted(r[0] for r in db.execute("SELECT id FROM docs"))
    db.close()
    d = tmp_path / "ords"
    d.mkdir()
    np.save(d / "wids.npy", np.asarray(ids, dtype=np.int64))
    (d / "ordinal_space.json").write_text(json.dumps({"ordinal_space_id": "s", "rows": len(ids)}))
    b = ob.OABitmapBuilder(tmp_path / "work", d)
    b.ingest_unit("u1", [(f"W{i}", i <= 100) for i in range(1, 301)])
    b.finalize(tmp_path / "bitmap", root / "meta.sqlite", {})
    return tmp_path / "bitmap"


def _retriever(root, monkeypatch, bitmap=None):
    from lib.thinclient.retriever import ThinClientRetriever
    monkeypatch.setenv("SFU_DENSE_WARMCACHE", "0")
    monkeypatch.delenv("SFU_THINCLIENT_ORDINALS", raising=False)
    monkeypatch.delenv("SFU_DELTA_ROOT", raising=False)
    if bitmap is None:
        monkeypatch.delenv(ov.ENV, raising=False)
    else:
        monkeypatch.setenv(ov.ENV, str(bitmap))
    r = ThinClientRetriever(index_root=str(root), remote_abstracts=False)
    r._load()
    return r


OA = {"open_access.is_oa": "true"}


def test_retriever_gate_off_never_populated_base_matches_nothing(tmp_path, monkeypatch):
    root = _tiny_root(tmp_path)
    r = _retriever(root, monkeypatch)
    assert r._oa is None
    assert r.search("politics paper", top_k=20, filters=OA) == []
    allr = r.search("politics paper", top_k=20)
    assert allr and all(d["is_oa"] is False for d in allr)
    assert r._post_filter([(d["openalex_id"], 1.0) for d in allr], {"is_oa": True}) == []


def test_retriever_gate_on_filters_and_hydrates_three_states(tmp_path, monkeypatch):
    root = _tiny_root(tmp_path)
    bitmap = _root_bitmap(tmp_path, root)
    off = _retriever(root, monkeypatch).search("politics paper", top_k=600)
    r = _retriever(root, monkeypatch, bitmap)
    assert r._oa is not None
    got = r.search("politics paper", top_k=20, filters=OA)
    assert len(got) == 20
    assert all(int(d["openalex_id"][1:]) <= 100 and d["is_oa"] is True for d in got)
    on = r.search("politics paper", top_k=600)
    assert [(d["openalex_id"], d["score"]) for d in on] == [(d["openalex_id"], d["score"]) for d in off]
    by = {d["openalex_id"]: d["is_oa"] for d in on}
    assert by["W50"] is True and by["W150"] is False and by["W450"] is None
    ranked = [("W450", 3.0), ("W50", 2.0), ("W150", 1.0), ("W7", 0.5)]
    assert r._post_filter(ranked, {"is_oa": True}) == [("W50", 2.0), ("W7", 0.5)]


def test_result_cache_key_rotates_with_bitmap(tmp_path, monkeypatch):
    import lib.result_cache as rc
    import lib.tools as tools
    root = _tiny_root(tmp_path)
    bitmap = _root_bitmap(tmp_path, root)
    r_off = _retriever(root, monkeypatch)
    monkeypatch.setattr(tools, "_get_thinclient_retriever", lambda: r_off)
    s_off = rc._manifest_stamp()
    assert "@oa=" not in s_off
    r_on = _retriever(root, monkeypatch, bitmap)
    monkeypatch.setattr(tools, "_get_thinclient_retriever", lambda: r_on)
    s_on = rc._manifest_stamp()
    assert s_on == f"{s_off}@oa={r_on._oa.bitmap_id}"
