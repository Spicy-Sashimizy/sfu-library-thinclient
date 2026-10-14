"""Ordinal addressing: the stale-ordinal guard and the miss contract.

Doc 18 §6 risk 1 calls stale ordinals "the single most dangerous property of the
design" — after a rebuild, ordinals renumber and any surviving pairing points at
the WRONG document with no error raised. A guard that is not tested is not a
guard, so the refusals are what this file asserts, one test per way the pairing
can be wrong. Risk 3 (docs with no build-time ordinal) is the second half.

Run: .venv/bin/python3 -m pytest scripts/tests/test_ordinals_guard.py -q
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

from lib.thinclient.ordinals import (MANIFEST_KEY, STAMP_FILE,  # noqa: E402
                                     OrdinalSpace, OrdinalSpaceMismatch,
                                     write_stamp)

WIDS = np.array([100, 200, 300, 400, 500], dtype=np.int64)
YEARS = np.array([2015, 2020, 0, 2005, 2024], dtype=np.int16)
DTYPES = np.array([0, 1, 0, 0, 0], dtype=np.int8)
OAS = np.array([1, 1, 0, 1, 0], dtype=np.uint8)
SECTS = np.array([0, 0, 0, 0, 0], dtype=np.int8)
CODES = {"type": {"article": 0, "book": 1}, "section": {"s": 0},
         "sentinel_code": -1, "sentinel_year": 0, "rows": 5}


@pytest.fixture
def space(tmp_path):
    """A well-formed ordinal directory + the manifest that authorises it."""
    for name, arr in (("wids", WIDS), ("year", YEARS), ("dtype", DTYPES),
                      ("is_oa", OAS), ("section", SECTS)):
        np.save(tmp_path / f"{name}.npy", arr)
    (tmp_path / "codes.json").write_text(json.dumps(CODES))
    src = tmp_path / "meta.sqlite"
    src.write_bytes(b"not really a db, only stat()'d")
    stamp = write_stamp(tmp_path, 5, CODES, src)
    return tmp_path, {MANIFEST_KEY: stamp[MANIFEST_KEY]}


def test_matching_pair_loads(space):
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    assert s.rows == 5


def test_rebuilt_arrays_are_refused(space):
    """The actual production hazard: arrays rebuilt (new ordinal space) while
    the manifest still authorises the previous one. Silently serving these
    returns the wrong document for every query."""
    work, manifest = space
    write_stamp(work, 5, CODES, work / "meta.sqlite")
    with pytest.raises(OrdinalSpaceMismatch, match="mismatch"):
        OrdinalSpace(work, manifest)


def test_unstamped_manifest_fails_closed(space):
    """An index that never authorised any ordinal space must not get one by
    default — absence of a stamp is not permission."""
    work, _ = space
    with pytest.raises(OrdinalSpaceMismatch, match="carries no"):
        OrdinalSpace(work, {})
    with pytest.raises(OrdinalSpaceMismatch, match="carries no"):
        OrdinalSpace(work, None)


def test_missing_stamp_file_is_refused(space):
    """Arrays with no identity cannot be proven to match anything."""
    work, manifest = space
    (work / STAMP_FILE).unlink()
    with pytest.raises(OrdinalSpaceMismatch, match="missing"):
        OrdinalSpace(work, manifest)


def test_truncated_arrays_are_refused(space):
    """A short read (the `--rows` under-estimate case) leaves a tail that
    addresses nothing; the stamp's row count catches it."""
    work, manifest = space
    np.save(work / "wids.npy", WIDS[:3])
    with pytest.raises(OrdinalSpaceMismatch, match="truncated"):
        OrdinalSpace(work, manifest)


@pytest.mark.parametrize("name", ["year", "dtype", "is_oa", "section"])
def test_any_short_column_is_refused(space, name):
    """Checking only `wids` is not enough: an interrupted copy can leave wids
    complete and a value column short, and then ordinals past the truncation
    filter against whatever the shorter array holds. Hit for real on
    2026-08-02 when a staging copy was killed mid-`year.npy`."""
    work, manifest = space
    arr = np.load(work / f"{name}.npy")
    np.save(work / f"{name}.npy", arr[:2])
    with pytest.raises(OrdinalSpaceMismatch, match="truncated"):
        OrdinalSpace(work, manifest)


def _ranked(*nums):
    return [(f"W{n}", 1.0 / (i + 1)) for i, n in enumerate(nums)]


def test_post_filter_matches_the_production_predicates(space):
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    f = {"year_range": (2010, 2025), "type": "article", "is_oa": 1}
    kept, unresolved = s.post_filter(_ranked(100, 200, 300, 400, 500), f)
    assert [d for d, _ in kept] == ["W100"]
    assert unresolved == []


def test_rank_order_is_preserved(space):
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    ranked = _ranked(500, 100, 400)
    kept, _ = s.post_filter(ranked, {"year_range": (2000, 2025)})
    assert [d for d, _ in kept] == ["W500", "W100", "W400"]
    assert kept == [r for r in ranked if r[0] in {"W500", "W100", "W400"}]


def test_null_year_never_passes_a_year_filter(space):
    """The 0 sentinel must not be read as year 0 sneaking under `lo`."""
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    kept, _ = s.post_filter(_ranked(300), {"year_range": (0, 3000)})
    assert kept == []


def test_ids_without_an_ordinal_are_reported_not_dropped(space):
    """Doc 18 §6 risk 3: warm-cache docs have no build-time ordinal. If
    post_filter decided these itself they would vanish silently, so it hands
    them back for the caller to resolve the old way."""
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    kept, unresolved = s.post_filter(_ranked(100, 999), {"year_range": (2010, 2025)})
    assert [d for d, _ in kept] == ["W100"]
    assert [d for d, _ in unresolved] == ["W999"]


def test_non_numeric_ids_are_unresolved_not_crashes(space):
    """docs_other ids (measured as zero rows at 150M, but handled)."""
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    kept, unresolved = s.post_filter([("Wabc", 1.0), ("W100", 0.5)],
                                     {"year_range": (2010, 2025)})
    assert [d for d, _ in kept] == ["W100"]
    assert [d for d, _ in unresolved] == ["Wabc"]


def test_leading_zero_ids_do_not_alias_onto_another_document(space):
    """`builder.encode_meta_id` rejects leading-zero digits, so "W0100" is a
    docs_other id with no ordinal. If the two encoders drift, "W0100" resolves
    to W100's ordinal, PASSES the found check (the stored W-id really is 100),
    and gets filtered on the wrong document's metadata — silently."""
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    kept, unresolved = s.post_filter([("W0100", 1.0)], {"year_range": (2010, 2025)})
    assert kept == []
    assert [d for d, _ in unresolved] == ["W0100"]


def test_encoder_agrees_with_the_builder_on_a_sweep(space):
    """Pin the two encoders together directly, so a change to either is caught
    here rather than by a wrong search result in production."""
    from lib.thinclient.builder import encode_meta_id

    work, manifest = space
    s = OrdinalSpace(work, manifest)
    probes = ["W100", "W0100", "W", "W0", "Wabc", "W12x", "W99999999", "",
              "X100", "W007", "W1"]
    _, found = s.lookup(probes)
    for probe, was_found in zip(probes, found):
        n = encode_meta_id(probe) if probe else None
        in_index = n is not None and n in set(WIDS.tolist())
        assert bool(was_found) == in_index, probe


def test_unknown_type_filter_keeps_nothing(space):
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    kept, _ = s.post_filter(_ranked(100, 200), {"type": "dataset"})
    assert kept == []


def test_empty_input(space):
    work, manifest = space
    s = OrdinalSpace(work, manifest)
    assert s.post_filter([], {"year_range": (2010, 2025)}) == ([], [])


def _retriever():
    from lib.thinclient.retriever import ThinClientRetriever
    return ThinClientRetriever(index_root="/nonexistent", remote_abstracts=False)


def test_retriever_defaults_to_sqlite(monkeypatch):
    """The gate is off unless SFU_THINCLIENT_ORDINALS is set."""
    monkeypatch.delenv("SFU_THINCLIENT_ORDINALS", raising=False)
    r = _retriever()
    assert r._ordinals is None
    r._post_filter_sqlite = lambda ranked, f: [ranked[0]]
    assert r._post_filter(_ranked(100, 200), {}) == [("W100", 1.0)]


def test_retriever_merges_unresolved_ids_in_rank_order(space):
    """The wired path must not lose docs that have no ordinal (warm cache),
    and the legs' rank order must survive the merge — a filter that reorders
    the ranking is wrong however fast it is."""
    work, manifest = space
    r = _retriever()
    r._ordinals = OrdinalSpace(work, manifest)
    seen = {}

    def fake_sqlite(ranked, f):
        seen["got"] = [d for d, _ in ranked]
        return ranked

    r._post_filter_sqlite = fake_sqlite
    ranked = _ranked(999, 500, 100)
    out = r._post_filter(ranked, {"year_range": (2010, 2025), "is_oa": 1})
    assert seen["got"] == ["W999"]
    assert [d for d, _ in out] == ["W999", "W100"]
    assert out == [ranked[0], ranked[2]]


def test_retriever_skips_sqlite_entirely_when_all_ids_resolve(space):
    """The whole point: a fully-covered candidate set must not touch SQLite."""
    work, manifest = space
    r = _retriever()
    r._ordinals = OrdinalSpace(work, manifest)

    def boom(ranked, f):
        raise AssertionError("SQLite was consulted for fully-covered ids")

    r._post_filter_sqlite = boom
    out = r._post_filter(_ranked(100, 400), {"year_range": (2010, 2025)})
    assert [d for d, _ in out] == ["W100"]
