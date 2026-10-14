"""Doc 10 F3/F8 harness (`scripts/experiments/eval_delta_ingest_foldin_f3f8.py`):
the verbatim rows, the arm table, the F8 state snapshot/restore, the
manifest-reuse check and the bar logic, on TMP TREES and synthetic rows ONLY.
Nothing here loads an index or writes a real served path.
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

_spec = importlib.util.spec_from_file_location("f3f8_h", REPO / "scripts/experiments/eval_delta_ingest_foldin_f3f8.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


def test_header_carries_the_f3_and_f8_rows_verbatim():
    doc = (REPO / "docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md").read_text().splitlines()
    for tag in ("| **F3** |", "| **F8** |"):
        row = next(x for x in doc if x.startswith(tag))
        assert row in H.__doc__


def test_arms_match_the_frozen_design():
    specs = {a: H.resolve_f3(a) for a in H.F3_ARMS}
    assert specs["n0"]["root"] is None and specs["n0"]["levers"] == []
    assert specs["n0x"]["levers"] == ["L4"]
    assert specs["L"]["levers"] == specs["F"]["levers"] == ["L3", "L4", "L5"]
    assert specs["L"]["n_seismic"] == 1 and specs["F"]["n_seismic"] == 0 and specs["F"]["n_gens"] == 1
    assert specs["F"]["fold_positions"] == [0] and specs["L"]["fold_positions"] == []
    assert specs["F"]["root"] == str(H.ROOT_F3) and specs["L"]["root"].endswith("root_n8c")


def _root(tmp_path, name, stamp, manifest_body, livedocs=False):
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    man = root / "shard_manifest.json"
    man.write_text(json.dumps(manifest_body))
    gj = {"stamp": stamp, "generations": [], "shard_manifest": str(man), "livedocs": None}
    if livedocs:
        (root / "livedocs.liv").write_bytes(b"\x01\x02")
        gj["livedocs"] = {"path": "livedocs.liv"}
    (root / "generations.json").write_text(json.dumps(gj))
    return root


def test_state_snapshot_restore_round_trip(tmp_path):
    root = _root(tmp_path, "r", "pre", {"shards": [{"mmap_dir": "s"}]}, livedocs=True)
    pre = H.snapshot_state(root, tmp_path / "snap" / "pre")
    assert [Path(f["path"]).name for f in pre["files"]] == ["shard_manifest.json", "livedocs.liv", "generations.json"]
    _root(tmp_path, "r", "post", {"shards": [{"mmap_dir": "s_prime", "fold_origin": "fold:0:2"}]})
    post = H.snapshot_state(root, tmp_path / "snap" / "post")
    H.restore_state(pre)
    assert json.loads((root / "generations.json").read_text())["stamp"] == "pre"
    assert json.loads((root / "shard_manifest.json").read_text())["shards"][0]["mmap_dir"] == "s"
    H.restore_state(post)
    assert json.loads((root / "generations.json").read_text())["stamp"] == "post"
    assert json.loads((root / "shard_manifest.json").read_text())["shards"][0]["fold_origin"] == "fold:0:2"


def test_state_follows_a_per_stamp_manifest_path(tmp_path):
    root = tmp_path / "r"
    (root / "shard_manifests").mkdir(parents=True)
    m1 = root / "shard_manifests" / "shard_manifest-a.json"
    m1.write_text("{}")
    (root / "generations.json").write_text(json.dumps({"stamp": "a", "shard_manifest": str(m1)}))
    assert H.state_files(root) == [m1, root / "generations.json"]


def _ledger(root, manifest=None, mmap="/x/fold1/fold.dotvbyte.v2.mmap"):
    db = sqlite3.connect(str(root / "ledger.sqlite"))
    db.execute("CREATE TABLE folds (shard INTEGER, fold INTEGER, state TEXT, created REAL, published REAL, "
               "manifest TEXT, dir TEXT, evidence TEXT, info TEXT)")
    db.execute("INSERT INTO folds (shard, fold, state, dir, manifest, info) VALUES (0, 1, 'ready', '/x/fold1', ?, ?)",
               (manifest, json.dumps({"mmap_dir": mmap})))
    db.commit()
    db.close()


def test_manifest_reuse_only_for_the_same_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "FOLDIN", tmp_path / "foldin")
    monkeypatch.setattr(H, "M4BASE", tmp_path / "base_manifest.json")
    root = tmp_path / "copy"
    root.mkdir()
    _ledger(root)
    assert H.preset_existing_fold_manifest(root, 1) is None
    out = tmp_path / "foldin" / "manifests" / "shard_manifest.fold_s0_k1.json"
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"composed_from": str(tmp_path / "other.json"), "shards": [
        {"fold_origin": "fold:0:1", "mmap_dir": "/x/fold1/fold.dotvbyte.v2.mmap"}]}))
    with pytest.raises(SystemExit, match="other inputs"):
        H.preset_existing_fold_manifest(root, 1)
    out.write_text(json.dumps({"composed_from": str(tmp_path / "base_manifest.json"), "shards": [
        {"fold_origin": "fold:0:1", "mmap_dir": "/x/fold1/fold.dotvbyte.v2.mmap"}]}))
    assert H.preset_existing_fold_manifest(root, 1) == {"reused_manifest": str(out)}
    assert H.fold_row(root, 1)[2] == str(out)


def _f8_rec(first_ms, warm_ms, reload_s, ok=True):
    reps = [{"kind": "fold_publish_operator_step" if i == 0 else "fold_republish_from_snapshot",
             "reload_s": reload_s[i], "backend_dropped": True, "backend_reopen_s": 1.0,
             "reload_plus_reopen_s": reload_s[i] + 1.0,
             "first_query": {"topic": f"t{i}", "ms": first_ms[i], "majflt": 0, "warm_ms": warm_ms},
             "recovery": [{"topic": "x", "ms": warm_ms}]} for i in range(5)]
    reps.append({"kind": "control_no_change", "reload_s": 0.5, "backend_dropped": False,
                 "first_query": {"ms": warm_ms}})
    return {"health": {"ok": ok}, "reps": reps,
            "warm_pass": {"p50_ms": warm_ms, "p95_ms": warm_ms, "rows": [{"topic": "t0", "ms": warm_ms}]}}


def test_f8_bars():
    r = H.summarize_f8(_f8_rec([1000, 1500, 1900, 2100, 1800], 1000, [1.0, 2.0, 3.0, 4.0, 14.9]))
    assert r["first_query_p50_ms"] == 1800 and r["bars"]["first_query_p50_le_2x_warm_p50"] == "PASS"
    assert r["bars"]["reload_le_15s"] == "PASS" and r["verdict"] == "PASS"
    r = H.summarize_f8(_f8_rec([2500, 2500, 2001, 1000, 1000], 1000, [1.0] * 4 + [15.1]))
    assert r["bars"] == {"reload_le_15s": "FAIL", "first_query_p50_le_2x_warm_p50": "FAIL"}
    assert r["verdict"] == "FAIL"
    r = H.summarize_f8(_f8_rec([1000] * 5, 1000, [1.0] * 5, ok=False))
    assert r["verdict"].startswith("NOT READ")
