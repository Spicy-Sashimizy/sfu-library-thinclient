"""Abstract ordinal locator: the fail-closed identity gate and the miss contract.

Doc 18 §17 ships the SQLite-free block locator for the flat abstract store. Its
danger is exactly ordinals hazard 1 (doc 18 §6 risk 1): a locator paired with a
`blocks.bin` from a different build loads fine and returns a real, plausible,
WRONG abstract with no error. `AbstractLocator.__init__` is the guard against
that, so the refusals are what this file asserts — one test per way the pairing
can be wrong — alongside the miss contract (hazard 2: ids the locator cannot
address must keep the SQLite path, never vanish).

Everything runs on a tiny real store built through the shipped writer, so the
whole pipeline (`AbstractStoreWriter` -> `build_flat_sidecar` ->
`build_ordinal_locator` -> `AbstractStore`) is exercised end to end.

Run: .venv/bin/python3 -m pytest scripts/tests/test_abstract_locator.py -q
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from lib.thinclient.abstracts import (  # noqa: E402
    DICTS_STAMP, FLAT_ID_KEY, FLAT_STAMP, LOCATOR_STAMP, AbstractLocator,
    AbstractLocatorMismatch, AbstractStore, AbstractStoreWriter,
    _encode_wid, build_flat_sidecar, build_ordinal_locator)

# W-ids deliberately out of insertion order (the locator must sort them), plus
# two ids the encoder rejects: "W0100" (leading zero -> docs_other class) and
# "Wxyz" (non-numeric). Both exercise hazard 2 — the locator skips them and the
# store must still return them via the SQLite `docs` path.
DOCS = {
    "W300": "the third social science abstract, on network effects",
    "W100": "the first abstract concerns archival methods and provenance",
    "W200": "second abstract: a study of citation half-lives across fields",
    "W0100": "leading-zero id — a docs_other-class record the ordinal misses",
    "Wxyz": "non-numeric id — also unaddressable by the ordinal locator",
}
WID_ONLY = {k: v for k, v in DOCS.items() if _encode_wid(k) is not None}
NON_WID = {k: v for k, v in DOCS.items() if _encode_wid(k) is None}


@pytest.fixture
def store(tmp_path):
    """A built v3 abstract store + flat sidecar + a matching, valid locator.

    Returns (sqlite_path, flat_dir). `AbstractStore(sqlite_path)` attaches both.
    """
    src = tmp_path / "abstracts.sqlite"
    w = AbstractStoreWriter(src)
    for doc_id, text in DOCS.items():
        w.add(doc_id, text)
    w.finish()

    build_flat_sidecar(src)                         # writes flat_store.json
    flat_dir = src.with_suffix(src.suffix + ".flat")
    build_ordinal_locator(src, flat_dir)            # writes loc_*.npy + locator.json
    return src, flat_dir


# ── it serves, and it serves the same bytes as SQLite ────────────────────────

def test_matching_pair_serves_every_document(store):
    src, flat_dir = store
    s = AbstractStore(src)
    assert s._locator is not None                   # the locator attached
    assert s.fetch(list(DOCS)) == DOCS              # byte-identical to input


def test_locator_path_equals_the_sqlite_docs_path(store):
    """The gate's whole promise: flat+locator returns exactly what flat+`docs`
    returns. Prove it by serving the same store with the locator removed."""
    src, flat_dir = store
    with_loc = AbstractStore(src).fetch(list(DOCS))

    (flat_dir / LOCATOR_STAMP).unlink()             # -> serve via SQLite docs
    s = AbstractStore(src)
    assert s._locator is None
    assert s.fetch(list(DOCS)) == with_loc == DOCS


def test_lookup_reports_hits_misses_and_non_wids(store):
    _, flat_dir = store
    loc = AbstractLocator(flat_dir)
    ids = ["W200", "W999", "Wxyz", "W100"]          # hit, absent, non-wid, hit
    _, found = loc.lookup(ids)
    assert list(found) == [True, False, False, True]


# ── the identity gate: one test per broken pairing ───────────────────────────

def test_matching_locator_loads(store):
    _, flat_dir = store
    loc = AbstractLocator(flat_dir)
    assert loc.rows == len(WID_ONLY)


def test_rebuilt_blocks_are_refused(store):
    """The production hazard: `blocks.bin` rebuilt (fresh flat_store_id) while a
    stale locator still sits beside it. Its (block, offset) pairs now address
    the wrong bytes; serving them returns the wrong abstract for every hit."""
    _, flat_dir = store
    flat = json.loads((flat_dir / FLAT_STAMP).read_text())
    flat[FLAT_ID_KEY] = "a-different-build-id"
    (flat_dir / FLAT_STAMP).write_text(json.dumps(flat))
    with pytest.raises(AbstractLocatorMismatch, match="mismatch"):
        AbstractLocator(flat_dir)


def test_missing_flat_stamp_fails_closed(store):
    """Blocks with no identity cannot be shown to match the locator."""
    _, flat_dir = store
    (flat_dir / FLAT_STAMP).unlink()
    with pytest.raises(AbstractLocatorMismatch, match="missing"):
        AbstractLocator(flat_dir)


def test_missing_locator_stamp_is_refused(store):
    """Arrays with no stamp carry no identity. (Through `AbstractStore` this is
    the benign 'not built yet' case — covered separately — but constructing the
    locator directly on stampless arrays must refuse.)"""
    _, flat_dir = store
    (flat_dir / LOCATOR_STAMP).unlink()
    with pytest.raises(AbstractLocatorMismatch, match="missing"):
        AbstractLocator(flat_dir)


def test_stamp_without_an_id_is_refused(store):
    _, flat_dir = store
    loc = json.loads((flat_dir / LOCATOR_STAMP).read_text())
    del loc[FLAT_ID_KEY]
    (flat_dir / LOCATOR_STAMP).write_text(json.dumps(loc))
    with pytest.raises(AbstractLocatorMismatch, match=FLAT_ID_KEY):
        AbstractLocator(flat_dir)


@pytest.mark.parametrize("name", ["wids", "b", "off", "n"])
def test_any_truncated_column_is_refused(store, name):
    """Checking only wids is not enough: an interrupted copy can leave wids
    complete and a value column short, and then the tail addresses whatever the
    shorter array holds (doc 18 §12)."""
    _, flat_dir = store
    arr = np.load(flat_dir / f"loc_{name}.npy")
    np.save(flat_dir / f"loc_{name}.npy", arr[:-1])
    with pytest.raises(AbstractLocatorMismatch, match="truncated"):
        AbstractLocator(flat_dir)


def test_a_mismatched_locator_takes_the_store_down(store):
    """The store must not silently serve wrong abstracts: an identity failure
    propagates out of `AbstractStore.__init__` rather than being swallowed."""
    _, flat_dir = store
    flat = json.loads((flat_dir / FLAT_STAMP).read_text())
    flat[FLAT_ID_KEY] = "some-other-build"
    (flat_dir / FLAT_STAMP).write_text(json.dumps(flat))
    src, _ = store
    with pytest.raises(AbstractLocatorMismatch):
        AbstractStore(src)


# ── the miss contract (hazard 2) ─────────────────────────────────────────────

def test_non_wid_documents_keep_the_sqlite_path(store):
    """The leading-zero and non-numeric ids are unaddressable by the ordinal
    locator, but they are real documents and must not vanish — the store falls
    back to `docs` for them."""
    src, _ = store
    s = AbstractStore(src)
    assert s._locator is not None
    got = s.fetch(list(NON_WID))
    assert got == NON_WID


def test_valid_wid_absent_from_store_returns_nothing(store):
    """A W-id that is simply not in this section resolves to found=False and is
    omitted, exactly as the SQLite path omits a missing row."""
    src, _ = store
    s = AbstractStore(src)
    assert s.fetch(["W999999"]) == {}


def test_skipped_non_wid_count_is_recorded(store):
    """The stamp records how many ids the locator could not address; deletion of
    abstracts.sqlite is only safe when this is 0 (else those docs are lost)."""
    _, flat_dir = store
    stamp = json.loads((flat_dir / LOCATOR_STAMP).read_text())
    assert stamp["skipped_non_wid"] == len(NON_WID)
    assert stamp["rows"] == len(WID_ONLY)


# ── build-time guards ────────────────────────────────────────────────────────

def test_build_requires_the_flat_sidecar_first(tmp_path):
    """The locator binds to the flat store's identity, which does not exist
    until the sidecar is built."""
    src = tmp_path / "abstracts.sqlite"
    w = AbstractStoreWriter(src)
    w.add("W1", "only doc")
    w.finish()
    with pytest.raises(FileNotFoundError, match=FLAT_STAMP):
        build_ordinal_locator(src)


def test_build_refuses_a_source_that_did_not_make_these_blocks(store):
    """If src is not the source `build_flat_sidecar` recorded, copying its id
    would certify a false pairing — the build refuses rather than certify it."""
    src, flat_dir = store
    flat = json.loads((flat_dir / FLAT_STAMP).read_text())
    flat["source"]["bytes"] += 1                    # pretend a different source
    (flat_dir / FLAT_STAMP).write_text(json.dumps(flat))
    with pytest.raises(ValueError, match="not the source"):
        build_ordinal_locator(src, flat_dir)


# ── the encoder pin (doc 18's first real bug) ────────────────────────────────

# ── dict rehoming + SQLite-free serving (doc 18 §18) ─────────────────────────

def test_dicts_are_rehomed_into_the_sidecar(store):
    """build_flat_sidecar copies the trained zstd dicts beside blocks.bin, so
    the store no longer needs the SQLite `meta` table at serve time. (This tiny
    store is below DICT_MIN_DOCS, so it trains none and uses the plain codec —
    the manifest must reflect exactly that, zero dict files.)"""
    _, flat_dir = store
    meta = json.loads((flat_dir / DICTS_STAMP).read_text())
    assert meta[FLAT_ID_KEY]                          # bound to these blocks
    assert meta["names"]                              # positional dict ids exist
    on_disk = {p.name for p in flat_dir.iterdir() if p.name.startswith("zdict")}
    assert set(meta["files"]) == on_disk             # manifest matches reality


def test_trained_dicts_rehome_and_serve_identically(tmp_path):
    """A store large enough to actually train a latin dict: the trained bytes
    must rehome verbatim and decode identically from SQLite, the sidecar, and
    with abstracts.sqlite deleted."""
    import random
    rng = random.Random(3)
    vocab = [f"term{i}" for i in range(400)]
    docs = {f"W{1000 + i}": " ".join(rng.choice(vocab) for _ in range(60))
            for i in range(600)}                     # > DICT_MIN_DOCS, real text

    src = tmp_path / "abstracts.sqlite"
    w = AbstractStoreWriter(src)
    for doc_id, text in docs.items():
        w.add(doc_id, text)
    w.finish()
    build_flat_sidecar(src)
    flat_dir = src.with_suffix(src.suffix + ".flat")
    build_ordinal_locator(src, flat_dir)
    assert (flat_dir / "zdict_latin").exists()       # a real trained dict rehomed

    ids = list(docs)
    from_sidecar = AbstractStore(src).fetch(ids)
    (flat_dir / DICTS_STAMP).unlink()
    from_sqlite = AbstractStore(src).fetch(ids)
    (flat_dir / DICTS_STAMP)  # restore below by rebuilding manifest
    from lib.thinclient.abstracts import dump_dict_sidecar
    dump_dict_sidecar(src, flat_dir)
    src.rename(src.with_suffix(".sqlite.deleted"))
    from_flatonly = AbstractStore(src).fetch(ids)

    assert from_sidecar == from_sqlite == from_flatonly == docs


def test_sqlite_dicts_and_sidecar_dicts_serve_identically(store):
    """The rehomed dicts must decode to the same bytes as the SQLite ones —
    otherwise deletion silently corrupts every abstract."""
    src, flat_dir = store
    from_sidecar = AbstractStore(src).fetch(list(DOCS))
    (flat_dir / DICTS_STAMP).unlink()                 # force the SQLite dict path
    from_sqlite = AbstractStore(src).fetch(list(DOCS))
    assert from_sidecar == from_sqlite == DOCS


def test_serves_with_abstracts_sqlite_deleted(store):
    """The end state: abstracts.sqlite gone, everything served from the flat
    sidecar (blocks + locator + dicts), no SQLite connection at all."""
    src, _ = store
    src.rename(src.with_suffix(".sqlite.deleted"))     # abstracts.sqlite is gone
    s = AbstractStore(src)
    assert s._sqlite_free is True and s._db is None
    # Every addressable (W-number) doc is served byte-identically.
    assert s.fetch(list(WID_ONLY)) == WID_ONLY


def test_sqlite_free_drops_unaddressable_ids(store):
    """Why deletion is gated on skipped_non_wid == 0: with no `docs` table left,
    a non-W-number id has no home and is simply absent. Serving it would need
    the SQLite fallback that deletion removed."""
    src, _ = store
    src.rename(src.with_suffix(".sqlite.deleted"))
    s = AbstractStore(src)
    got = s.fetch(list(DOCS))
    assert got == WID_ONLY                              # the NON_WID docs vanish
    assert set(got) & set(NON_WID) == set()


def test_sqlite_free_requires_a_locator(store):
    """Without `docs` AND without the ordinal locator there is no way to resolve
    a block address — refuse loudly rather than serve nothing."""
    src, flat_dir = store
    (flat_dir / LOCATOR_STAMP).unlink()
    src.rename(src.with_suffix(".sqlite.deleted"))
    with pytest.raises(RuntimeError, match="no ordinal locator"):
        AbstractStore(src)


def test_missing_sqlite_without_dicts_refuses_rather_than_creating_a_db(store):
    """A bare path with no SQLite file and no rehomed dicts must raise, never let
    sqlite3.connect() create an empty database that then serves nothing."""
    src, flat_dir = store
    (flat_dir / DICTS_STAMP).unlink()
    src.rename(src.with_suffix(".sqlite.deleted"))
    with pytest.raises(FileNotFoundError, match="rehomed dicts"):
        AbstractStore(src)


def test_mismatched_dict_sidecar_is_refused(store):
    """Dicts from a different build decode blocks.bin into garbage; the identity
    gate refuses them the same way it refuses a mismatched locator."""
    src, flat_dir = store
    meta = json.loads((flat_dir / DICTS_STAMP).read_text())
    meta[FLAT_ID_KEY] = "a-different-build"
    (flat_dir / DICTS_STAMP).write_text(json.dumps(meta))
    with pytest.raises(AbstractLocatorMismatch, match="identity"):
        AbstractStore(src)


def test_encoder_agrees_with_the_builder_on_a_sweep():
    """`_encode_wid` must mirror `builder.encode_meta_id` exactly. If they drift
    on leading zeros, 'W0100' aliases onto W100's row, passes the verification
    read, and returns the wrong abstract silently."""
    from lib.thinclient.builder import encode_meta_id

    probes = ["W100", "W0100", "W", "W0", "Wabc", "W12x", "W99999999", "",
              "X100", "W007", "W1", "w100", "W 1"]
    for p in probes:
        assert _encode_wid(p) == encode_meta_id(p), p
