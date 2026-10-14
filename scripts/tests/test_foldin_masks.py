"""Doc 10 §3 G4 — per-leg newest-origin masks in the serving delta layer.

(1) No fold: `shard_result_filter`, `shard_origins` and `attach_seismic`
equal the pre-G4 code (the reference below is the pre-G4 filter verbatim) on
2,000 random cases. (2) With a fold: every (leg x origin) case for every doc
state. Tmp trees only; no index, no model.
"""
import json
import random
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

from lib.thinclient.delta_layer import BUFFER_ORIGIN, DeltaLayer  # noqa: E402


def _reference_filter(deleted, superseded, dead_fn, origins):
    """Pre-G4 `DeltaLayer.shard_result_filter` body (commit 2fc2cb5c)."""
    def _filter(per_shard):
        out = []
        for pos, res in enumerate(per_shard):
            if not res:
                out.append(res)
                continue
            origin = origins[pos] if pos < len(origins) else None
            dead = dead_fn([r[2] for r in res])
            if origin is None:
                out.append([r for r, x in zip(res, dead) if not x and r[2] not in deleted])
            else:
                out.append([r for r, x in zip(res, dead) if r[2] not in deleted
                            and not (x and r[2] not in superseded)
                            and superseded.get(r[2], origin) == origin])
        return out
    return _filter


def _write_root(root: Path, mask: dict, shards: list | None, generations=None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    sm = None
    if shards is not None:
        sm = root / "shard_manifest.json"
        sm.write_text(json.dumps({"n_shards": len(shards), "shards": shards}))
    (root / "generations.json").write_text(json.dumps({
        "format": 1, "stamp": "g0002-1", "generations": generations or [], "mask": mask,
        "livedocs": None, "shard_manifest": str(sm) if sm else None}))


def test_no_fold_filter_equals_pre_g4_reference(tmp_path):
    rng = random.Random(20261001)
    ids = [f"W{i}" for i in range(40)]
    for case in range(2000):
        deleted = set(rng.sample(ids, rng.randint(0, 6)))
        superseded = {i: rng.choice([0, 1, 2, 3]) for i in rng.sample(ids, rng.randint(0, 15))}
        dead_set = set(rng.sample(ids, rng.randint(0, 12)))
        origins = [rng.choice([None, None, 1, 2, 3]) for _ in range(rng.randint(1, 6))]
        per_shard = [[("q", rng.random(), rng.choice(ids)) for _ in range(rng.randint(0, 8))]
                     for _ in range(len(origins) + rng.randint(0, 1))]
        root = tmp_path / f"r{case % 3}"
        _write_root(root, {"deleted": sorted(deleted), "superseded": superseded}, None)
        dl = DeltaLayer(root)
        assert dl.seismic_newest == {}
        dl.base_dead = lambda xs, d=dead_set: [x in d for x in xs]
        got = dl.shard_result_filter(origins)(per_shard)
        want = _reference_filter(deleted, superseded, dl.base_dead, origins)(per_shard)
        assert got == want
        dl.close()


def test_no_fold_origins_and_attach_unchanged(tmp_path):
    shards = [{"mmap_dir": "a"}, {"mmap_dir": "b"}, {"mmap_dir": "g1", "delta_generation": 1}]
    root = tmp_path / "d"
    _write_root(root, {"deleted": [], "superseded": {"W1": 1}}, shards)
    dl = DeltaLayer(root)
    sm = str(root / "shard_manifest.json")
    assert dl.shard_origins(3, sm) == [None, None, 1]
    assert dl.shard_origins(3, "/elsewhere.json") == [None, None, None]
    backend = type("B", (), {"shards": [0, 1, 2], "_shard_result_filter": None})()
    assert dl.attach_seismic(backend, sm) is False and backend._shard_result_filter is None
    no_shards = type("B", (), {"_shard_result_filter": None})()
    assert dl.attach_seismic(no_shards, sm) is False
    assert dl.filter_ids([("W1", 1.0), ("W2", 0.5)]) == [("W1", 1.0), ("W2", 0.5)]
    dl.close()


def _meta(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    for t in ("docs", "docs_other"):
        db.execute(f"CREATE TABLE {t} (id TEXT PRIMARY KEY, title TEXT, doi TEXT, year INT, "
                   "type TEXT, is_oa INT, section TEXT)")
    for i in rows:
        db.execute("INSERT INTO docs_other VALUES (?,?,?,?,?,?,?)", (i, f"t {i} {path.parent.name}", "", 2020,
                                                               "article", 0, "sec"))
    db.commit()
    db.close()


U, U1, F, N, R, D, DN, O, B = "W100", "W101", "W102", "W103", "W104", "W105", "W106", "W107", "W108"
FOLD = "fold:0:1"
BIT = {F, R, D, O, B}


@pytest.fixture
def folded(tmp_path):
    """Shard positions: base shard 1 (None), s′ = fold 1 of shard 0, gen 1, gen 2.

    U  untouched base doc of shard 0 (in s′)        U1 untouched base doc of shard 1
    F  base doc updated in gen 1, then folded       N  new doc in gen 1, then folded
    R  folded, then re-updated into gen 2           D  folded base doc, then deleted
    DN folded new doc, then deleted                 O  base doc of shard 1 updated in gen 1 (not folded)
    B  base doc of shard 0 re-staged into the buffer after the fold
    """
    root = tmp_path / "delta"
    g1, g2 = root / "g0001", root / "g0002"
    _meta(g1 / "meta.sqlite", [F, N, R, O, D, DN, B])
    _meta(g2 / "meta.sqlite", [R])
    shards = [{"shard": 1, "mmap_dir": "base1"},
              {"shard": 0, "mmap_dir": "/fold/shard0/fold1/fold.dotvbyte.v2.mmap", "fold_origin": FOLD},
              {"shard": "delta_g0001", "mmap_dir": str(g1), "delta_generation": 1},
              {"shard": "delta_g0002", "mmap_dir": str(g2), "delta_generation": 2}]
    mask = {"deleted": [DN], "superseded": {F: 1, R: 2, O: 1, B: 0},
            "newest_by_leg": {"seismic": {F: FOLD, N: FOLD}}}
    gens = [{"gen": 1, "dir": str(g1), "docs": 7, "sections": []},
            {"gen": 2, "dir": str(g2), "docs": 1, "sections": []}]
    _write_root(root, mask, shards, gens)
    dl = DeltaLayer(root)
    dl.base_dead = lambda xs: [x in BIT for x in xs]
    dl.livedocs = object()
    dl._buffer_rows = {B: {"id": B}}
    dl.refresh_buffer = lambda: None
    yield dl, str(root / "shard_manifest.json")
    dl.livedocs = None
    dl.close()


def _ids(res):
    return {r[2] for r in res}


def test_fold_origins_read_from_composed_manifest(folded):
    dl, sm = folded
    assert dl.shard_origins(4, sm) == [None, FOLD, 1, 2]
    assert dl.seismic_newest == {F: FOLD, N: FOLD}


SEISMIC_PLACED = {
    None: [U1, O],
    FOLD: [U, F, N, R, D, DN, B],
    1: [F, N, R, O, D, DN],
    2: [R],
}
SEISMIC_EXPECTED = {
    None: {U1},
    FOLD: {U, F, N},
    1: {O},
    2: {R},
}


@pytest.mark.parametrize("pos,origin", [(0, None), (1, FOLD), (2, 1), (3, 2)])
def test_seismic_leg_every_origin(folded, pos, origin):
    dl, sm = folded
    origins = dl.shard_origins(4, sm)
    placed = SEISMIC_PLACED[origin]
    per_shard = [[] for _ in range(4)]
    per_shard[pos] = [("q", 1.0 - k / 100, d) for k, d in enumerate(placed)]
    got = dl.shard_result_filter(origins)(per_shard)
    assert _ids(got[pos]) == SEISMIC_EXPECTED[origin]
    assert [r[2] for r in got[pos]] == [d for d in placed if d in SEISMIC_EXPECTED[origin]]
    pre = _reference_filter(dl.deleted, dl.superseded, dl.base_dead, origins)(per_shard)
    if origin == 1:
        assert _ids(pre[pos]) == {F, N, O}


def test_each_live_doc_has_exactly_one_seismic_origin(folded):
    dl, sm = folded
    origins = dl.shard_origins(4, sm)
    where = {U: [1], U1: [0], F: [1, 2], N: [1, 2], R: [1, 2, 3], D: [1], DN: [1, 2], O: [0, 2], B: [1]}
    per_shard = [[] for _ in range(4)]
    for d, poss in where.items():
        for p in poss:
            per_shard[p].append(("q", 0.5, d))
    got = dl.shard_result_filter(origins)(per_shard)
    served = {}
    for p, res in enumerate(got):
        for r in res:
            served.setdefault(r[2], []).append(origins[p])
    assert served == {U: [FOLD], U1: [None], F: [FOLD], N: [FOLD], R: [2], O: [1]}


@pytest.mark.parametrize("origin,placed,expected", [
    (None, [U, U1, F, R, D, O, B], {U, U1}),
    (1, [F, N, R, O, D, DN], {F, N, O}),
    (2, [R], {R}),
    (BUFFER_ORIGIN, [B], {B}),
])
def test_bm25f_leg_every_origin(folded, origin, placed, expected):
    dl, _ = folded
    hits = [(d, 1.0, origin) for d in placed]
    assert {d for d, _ in dl.filter_hits(hits)} == expected


def test_bm25f_leg_without_fold_keys_is_unchanged(folded):
    dl, _ = folded
    hits = [(d, 1.0, o) for d in [U, U1, F, N, R, D, DN, O, B] for o in (None, 1, 2, BUFFER_ORIGIN)]
    with_fold = dl.filter_hits(hits)
    dl.seismic_newest = {}
    assert dl.filter_hits(hits) == with_fold


def test_splade_post_merge_leg(folded):
    dl, sm = folded
    backend = type("B", (), {"shards": [0, 1, 2, 3], "_shard_result_filter": None})()
    assert dl.attach_seismic(backend, sm) is True
    ranked = [(d, 1.0) for d in [U, F, N, R, D, DN, O, B]]
    assert [d for d, _ in dl.filter_ids(ranked)] == [U, F, N, R, D, O]


def test_attach_without_livedocs_when_a_fold_is_served(folded):
    dl, sm = folded
    dl.livedocs = None
    backend = type("B", (), {"shards": [0, 1, 2, 3], "_shard_result_filter": None})()
    assert dl.attach_seismic(backend, sm) is True
    dl.seismic_newest = {}
    backend2 = type("B", (), {"shards": [0, 1, 2, 3], "_shard_result_filter": None})()
    assert dl.attach_seismic(backend2, sm) is True
    dl.livedocs = object()


def test_meta_and_abstract_legs_follow_sections_origin(folded):
    dl, _ = folded
    rows = dl.meta_rows([F, N, R, O, U])
    assert rows[F][1] == "t W102 g0001" and rows[N][1] == "t W103 g0001"
    assert rows[R][1] == "t W104 g0002" and rows[O][1] == "t W107 g0001"
    assert U not in rows
    owner = dl.abstract_owner([F, N, R, O, U])
    assert owner == {F: (1, "sec"), N: (1, "sec"), R: (2, "sec"), O: (1, "sec")}
