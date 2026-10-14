"""Doc 10 F2 harness (`scripts/experiments/eval_delta_ingest_foldin.py`): the
statistics, the leak finder, the bar logic and the F-arm preview root, on
synthetic rows and TMP TREES ONLY. Nothing here loads an index or names a
real served path.
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest.foldin import GuardConfig  # noqa: E402

_spec = importlib.util.spec_from_file_location("foldin_h", REPO / "scripts/experiments/eval_delta_ingest_foldin.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

IDS = [f"W{i}" for i in range(40)]


def test_header_carries_doc10_section6_verbatim():
    doc = (REPO / "docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md").read_text().splitlines()
    a = next(i for i, x in enumerate(doc) if x.startswith("## 6. Measurements"))
    b = next(i for i, x in enumerate(doc) if x.startswith("## 7."))
    assert "\n".join(doc[a:b]).rstrip() in H.__doc__


def test_overlap_and_ndcg():
    assert H.overlap10(IDS[:10], IDS[:10]) == 1.0
    assert H.overlap10(IDS[:10], IDS[1:11]) == 0.9
    assert H.overlap10(IDS[:10], IDS[20:30]) == 0.0
    gains = {"W0": 2.0, "W1": 1.0}
    assert H.ndcg10(["W0", "W1"], gains) == pytest.approx(1.0)
    assert 0 < H.ndcg10(["W1", "W0"], gains) < 1.0
    assert H.ndcg10(["W5"], gains) == 0.0
    assert H.ndcg10(["W0"], {}) == 0.0


def test_bootstrap_is_seeded_and_brackets_the_mean():
    d = [0.01, -0.02, 0.0, 0.03, -0.01] * 24
    a, b = H.paired_bootstrap(d), H.paired_bootstrap(d)
    assert a == b and a["n"] == 120 and a["resamples"] == 10_000
    assert a["ci95"][0] <= a["mean"] <= a["ci95"][1]
    assert H.paired_bootstrap([])["ci95"] is None


def test_find_leaks_kinds():
    origins = ["fold:0:1", None, 1]
    truth = {"N1": "fold:0:1", "N2": 1}
    clean = [[(3.0, "W1"), (2.0, "N1")], [(1.0, "W2")], [(0.5, "N2")]]
    assert H.find_leaks(clean, origins, set(), truth) == []
    kinds = lambda per, tomb=frozenset(): sorted(x["kind"] for x in H.find_leaks(per, origins, set(tomb), truth))  # noqa: E731
    assert kinds([[(1.0, "W1")], [], []], {"W1"}) == ["deleted"]
    assert kinds([[], [], [(1.0, "N1")]]) == ["stale_copy"]
    assert kinds([[(1.0, "N1")], [], [(1.0, "N1")]]) == ["double_served", "stale_copy"]
    assert kinds([[(1.0, "W9")], [(1.0, "W9")], []]) == ["double_served"]


def _rows(shift_f: int = 0, leak: bool = False, n=(120, 100, 240)):
    leg = []
    for s, cnt in zip(("QT", "QD", "QA"), n):
        for i in range(cnt):
            base = [[d, 1.0] for d in IDS[:10]]
            f = [[d, 1.0] for d in IDS[shift_f:shift_f + 10]] if i == 0 else base
            leg.append({"set": s, "i": i,
                        "L": {"fed10": base, "own10": base, "leaks": []},
                        "F": {"fed10": f, "own10": f,
                              "leaks": [{"id": "N1", "pos": 9, "kind": "stale_copy"}] if leak and i == 0 else []}})
    qa = [{"i": i, "key": f"t{i % 120}", "L": {"fused_ids": IDS[:10], "final_ids": IDS[:10]},
           "F": {"fused_ids": IDS[:10], "final_ids": IDS[:10]}} for i in range(n[2])]
    return {"leg": leg, "qa": qa, "health": {"ok": True}, "stop": None, "ledger": {"tombstones": 0, "superseded": 0}}


QRELS = {f"t{i}": {"docs": [{"openalex_id": "W0", "gain": 1}, {"openalex_id": "W30", "gain": 2}]} for i in range(120)}
PLANNED = {"QT": 120, "QD": 100, "QA": 240, "QA_pipeline": 240}
M_SET = {"QT": 0.9908, "QD": 0.985}
REF = {"QT": {"overlap10_mean": 0.9858, "n": 120, "source": "t"}, "QD": {"overlap10_mean": 0.987, "n": 100, "source": "t"}}


def test_bar_readings():
    b = H.q_a_bars(M_SET)
    assert b["QT"]["A"] == pytest.approx(0.985) and b["QD"]["A"] == pytest.approx(0.980)
    assert b["QT"]["B"] == b["QD"]["B"] == 0.99
    assert H.q_a_bars({})["QT"]["A"] is None


def test_verdict_needs_the_owner_reading_and_a_complete_run():
    r = H.compute_f2(_rows(), QRELS, M_SET, REF, PLANNED, None)
    assert r["verdict"].startswith("NOT READ: the owner") and r["verdict_by_reading"] == {"A": "PASS", "B": "PASS"}
    assert H.compute_f2(_rows(), QRELS, M_SET, REF, PLANNED, "A")["verdict"] == "PASS (Q-a reading A)"
    short = H.compute_f2(_rows(n=(5, 5, 5)), QRELS, M_SET, REF, PLANNED, "A")
    assert short["verdict"].startswith("NOT READ: run not complete") and not short["complete"]
    sick = _rows()
    sick["health"] = {"ok": False}
    assert H.compute_f2(sick, QRELS, M_SET, REF, PLANNED, "B")["verdict"].startswith("NOT READ: run not complete")


def test_leak_and_missing_reference_fail():
    r = H.compute_f2(_rows(leak=True), QRELS, M_SET, REF, PLANNED, "A")
    assert r["Q_d"]["leaks_F"] == 3 and not r["Q_d"]["pass"] and r["verdict"].startswith("FAIL")
    none = {s: {"overlap10_mean": None, "n": 0, "source": "MISSING"} for s in ("QT", "QD")}
    r = H.compute_f2(_rows(), QRELS, M_SET, none, PLANNED, "A")
    assert not r["Q_b"]["QT"]["pass"] and r["verdict"].startswith("FAIL")


def test_q_c_reads_the_final_ndcg_ci():
    rows = _rows()
    for r in rows["qa"]:
        r["F"]["final_ids"] = IDS[10:20]
    r = H.compute_f2(rows, QRELS, M_SET, REF, PLANNED, "A")
    assert r["Q_c"]["final"]["delta_F_minus_L"]["mean"] < 0 and not r["Q_c"]["pass"]
    assert r["Q_c"]["identical_final_top10"] == 0 and r["verdict"].startswith("FAIL")


@pytest.fixture
def fixture_root(tmp_path):
    fold_root = tmp_path / "foldin"
    root = fold_root / "fixture"
    gen = root / "g0001"
    gen.mkdir(parents=True)
    fdir = fold_root / "shard0" / "fold1"
    mmap = fdir / "fold.dotvbyte.v2.mmap"
    mmap.mkdir(parents=True)
    base = [{"shard": s, "mmap_dir": str(tmp_path / f"served{s}.mmap"), "n_docs": 10} for s in range(2)]
    lman = root / "shard_manifest.json"
    lman.write_text(json.dumps({"n_shards": 3, "shards": base + [
        {"mmap_dir": str(gen / "seismic.mmap"), "n_docs": 3, "delta_generation": 1}]}))
    (root / "generations.json").write_text(json.dumps({
        "format": 1, "stamp": "g0001-1", "generations": [{"gen": 1, "dir": str(gen)}],
        "mask": {"deleted": [], "superseded": {}}, "livedocs": None, "shard_manifest": str(lman)}))
    db = sqlite3.connect(root / "ledger.sqlite")
    db.executescript(
        "CREATE TABLE docs (id TEXT PRIMARY KEY, status TEXT, generation INT, in_base INT, last_seen REAL, route_shard INT);"
        "CREATE TABLE tombstones (id TEXT); CREATE TABLE history (id TEXT);"
        "CREATE TABLE folds (shard INT, fold INT, state TEXT, created REAL, snapshot REAL, published REAL, dir TEXT, "
        "manifest TEXT, info TEXT); CREATE TABLE fold_members (shard INT, fold INT, id TEXT, staged_at REAL);")
    db.executemany("INSERT INTO docs VALUES (?,?,?,?,?,?)",
                   [("N1", "live", 1, 0, 5.0, 0), ("N2", "live", 1, 0, 9.0, 0), ("N3", "live", 1, 0, 5.0, 1)])
    db.executemany("INSERT INTO fold_members VALUES (0,1,?,?)", [("N1", 5.0), ("N2", 5.0)])
    db.execute("INSERT INTO folds VALUES (0,1,'built',1,1,NULL,?,NULL,?)",
               (str(fdir), json.dumps({"mmap_dir": str(mmap), "dump": {"docs": 12}, "format": "dotvbyte_fixedu8_v2"})))
    db.commit()
    db.close()
    cfg = GuardConfig(fold_root=fold_root, repo_data=tmp_path / "repo" / "data", stage_dir=tmp_path / "stage",
                      manifests=(), repo_root=tmp_path / "repo", mounts_text="dev / ext4 rw 0 0\n")
    return root, fold_root, mmap, lman, cfg


def test_preview_root_moves_only_snapshot_members(fixture_root, tmp_path):
    root, fold_root, mmap, lman, cfg = fixture_root
    before = {p: p.read_bytes() for p in (root / "generations.json", lman, root / "ledger.sqlite")}
    out = fold_root / "f2" / "preview_root"
    rec = H.make_preview(root, 0, None, fold_root, out, cfg)
    assert rec["moved_ids"] == ["N1"] and rec["members"] == 2 and rec["origin"] == "fold:0:1"
    pg = json.loads((out / "generations.json").read_text())
    assert pg["mask"]["newest_by_leg"]["seismic"] == {"N1": "fold:0:1"}
    assert pg["stamp"] != "g0001-1" and pg["generations"] == [{"gen": 1, "dir": str(root / "g0001")}]
    man = json.loads(Path(pg["shard_manifest"]).read_text())
    assert man["shards"][0]["mmap_dir"] == str(mmap) and man["shards"][0]["fold_origin"] == "fold:0:1"
    assert man["shards"][1:] == json.loads(lman.read_text())["shards"][1:]
    assert all(p.read_bytes() == b for p, b in before.items())
    again = H.make_preview(root, 0, 1, fold_root, out, cfg)
    assert again["manifest"] == rec["manifest"]


def test_preview_refuses_a_published_or_missing_fold(fixture_root):
    root, fold_root, _mmap, _lman, cfg = fixture_root
    with pytest.raises(SystemExit):
        H.make_preview(root, 1, None, fold_root, fold_root / "f2" / "p", cfg)
    db = sqlite3.connect(root / "ledger.sqlite")
    db.execute("UPDATE folds SET state='published'")
    db.commit()
    db.close()
    with pytest.raises(SystemExit):
        H.make_preview(root, 0, None, fold_root, fold_root / "f2" / "p", cfg)


def test_q_b_level_federated_ignores_the_shard_own_overlap():
    rows = _rows()
    for r in rows["leg"]:
        if r["set"] == "QD" and r["i"] < 30:
            r["F"]["own10"] = [[d, 1.0] for d in IDS[1:11]]
    both = H.compute_f2(rows, QRELS, M_SET, REF, PLANNED, "A")
    assert not both["Q_b"]["QD"]["pass"] and not both["Q_b"]["QD"]["pass_shard_own"] and both["Q_b"]["QD"]["pass_federated"]
    assert both["verdict"].startswith("FAIL")
    fed = H.compute_f2(rows, QRELS, M_SET, REF, PLANNED, "A", "federated")
    assert fed["Q_b"]["QD"]["pass"] and not fed["Q_b"]["QD"]["pass_shard_own"] and fed["Q_b"]["QD"]["level"] == "federated"
    assert fed["verdict"] == "PASS (Q-a reading A)"
