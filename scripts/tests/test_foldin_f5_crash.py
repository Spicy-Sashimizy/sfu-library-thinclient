"""Doc 10 F5 (crash safety) on TMP TREES ONLY: the publish commit point, the
re-runnable fold steps, and the F5 harness's served-state checker
(`scripts/experiments/eval_delta_ingest_foldin_f5.py`), including a negative
control: the torn state the pre-2026-10-08 publish order could leave (new
composed manifest + old masks) must read NEITHER. No index is built; served
shards are stand-in dirs holding only a document mapping.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest import foldin, generation  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402
from spike.delta_ingest.routing import route_shard  # noqa: E402

_spec = importlib.util.spec_from_file_location("f5", REPO / "scripts/experiments/eval_delta_ingest_foldin_f5.py")
f5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f5)


def _ids(shard, n, start=9_000_000):
    out, i = [], start
    while len(out) < n:
        if route_shard(f"W{i}") == shard:
            out.append(f"W{i}")
        i += 1
    return out


def _fake_shard(d: Path, ids: list[str]) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    blob = b"".join(i.encode() for i in ids)
    offs = np.cumsum([0] + [len(i.encode()) for i in ids]).astype("<u8")
    offs.tofile(d / "document_mapping_offsets.bin")
    (d / "document_mapping_strings.bin").write_bytes(blob)
    return d


@pytest.fixture
def root(tmp_path):
    """A delta root with one published generation (gen 1, a SEISMIC shard)
    holding 6 new docs routed to shard 0 and 2 routed to shard 1, over a
    2-shard base; published once (the pre-fold state)."""
    base0 = _fake_shard(tmp_path / "served0.mmap", _ids(0, 20, start=1_000))
    base1 = _fake_shard(tmp_path / "served1.mmap", _ids(1, 20, start=1_000))
    served = tmp_path / "served.json"
    served.write_text(json.dumps({"n_shards": 2, "shards": [
        {"shard": 0, "mmap_dir": str(base0), "n_docs": 20}, {"shard": 1, "mmap_dir": str(base1), "n_docs": 20}]}))
    r = tmp_path / "delta"
    new0, new1 = _ids(0, 6), _ids(1, 2)
    g = r / "g0001"
    _fake_shard(g / "seismic" / "delta_g0001.dotvbyte.v2.mmap", new0 + new1)
    (g / "generation.json").write_text(json.dumps({
        "generation": 1, "docs": 8, "docs_with_vectors": 8, "sections": {},
        "seismic": {"status": "served", "mmap_dir": "seismic/delta_g0001.dotvbyte.v2.mmap",
                    "format": "dotvbyte_fixedu8_v2"}}))
    led = IngestLedger(r / "ledger.sqlite")
    led.stage([DocRecord(id=i, title=i, sparse_field={"kinase": 1.0}) for i in new0 + new1], {})
    led.db.execute("UPDATE docs SET generation=1 WHERE status='live'")
    led.db.execute("UPDATE records SET generation=1")
    led.db.execute("INSERT INTO generations (gen, state) VALUES (1, 'published')")
    led.db.commit()
    base = BaseIndex(tmp_path / "idx")
    pub = generation.publish(r, led, base, str(served))
    return {"root": r, "led": led, "base": base, "served": served, "new0": new0, "new1": new1, "pub": pub,
            "tmp": tmp_path}


def _fold(root, fold_ids, k=1):
    """A built fold k of shard 0 holding the base ids + `fold_ids`, recorded
    in the ledger exactly as build_fold records it."""
    t = root["tmp"]
    cfg = foldin.GuardConfig(fold_root=t / "foldroot", repo_data=t / "repo" / "data", stage_dir=t / "stage",
                             manifests=(), repo_root=t / "repo")
    (t / "foldroot").mkdir(exist_ok=True)
    d = foldin.make_fold_dir(cfg, 0, k)
    mm = _fake_shard(d / "fold.dotvbyte.v2.mmap", _ids(0, 20, start=1_000) + fold_ids)
    led = root["led"]
    foldin.ensure_fold_schema(led)
    plan = foldin.fold_plan(led, 0)
    info = {"mmap_dir": str(mm), "format": "dotvbyte_fixedu8_v2", "dump": {"docs": 20 + len(fold_ids)}}
    with led.db:
        led.db.execute("INSERT INTO folds VALUES (?,?,?,?,?,?,?,?,?)",
                       (0, k, "built", 0.0, 0.0, None, str(d), None, json.dumps(info)))
        led.db.executemany("INSERT INTO fold_members VALUES (?,?,?,?)", [(0, k, i, ts) for i, ts in plan["add"]])
    return cfg, d, mm


def test_publish_writes_a_new_manifest_and_never_rewrites_one(root):
    r = root["root"]
    first = Path(root["pub"]["shard_manifest"])
    assert first.parent == r / "shard_manifests" and not (r / "shard_manifest.json").exists()
    body = first.read_bytes()
    second = Path(generation.publish(r, root["led"], root["base"], str(root["served"]))["shard_manifest"])
    assert second != first and first.read_bytes() == body
    assert json.loads((r / "generations.json").read_text())["shard_manifest"] == str(second)


def test_kill_between_manifest_and_generations_json_serves_the_previous_publish(root, monkeypatch):
    r = root["root"]
    pre = f5.served_state(r)
    real = generation.atomic_write_json

    def die_on_generations(path, data):
        if Path(path).name == "generations.json":
            raise KeyboardInterrupt("simulated SIGKILL")
        real(path, data)
    monkeypatch.setattr(generation, "atomic_write_json", die_on_generations)
    with pytest.raises(KeyboardInterrupt):
        generation.publish(r, root["led"], root["base"], str(root["served"]))
    assert len(list((r / "shard_manifests").glob("*.json"))) == 2
    assert f5.served_state(r)["digest"] == pre["digest"]


def test_checker_reads_pre_post_and_the_torn_state(root, monkeypatch):
    r, led = root["root"], root["led"]
    pre = f5.served_state(r)
    oc = f5.origin_check(r, 0, pre, None)
    assert oc["kept_once"] == 6 and oc["kept_none"] == 0 and oc["kept_twice_or_more"] == 0
    assert set(oc["kept_at"].values()) == {1}
    old_manifest = Path(pre["manifest"])
    old_body = old_manifest.read_text()
    pre_gj = (r / "generations.json").read_bytes()

    cfg, d, mm = _fold(root, root["new0"])
    foldin.mark_fold_ready(led, 0, 1, {"test": True})
    foldin.publish_fold(r, led, root["base"], 0, 1, confirm=True, cfg=cfg, base_shard_manifest=str(root["served"]),
                        baseline_roots=[], prefault=False)
    post = f5.served_state(r)
    assert post["digest"] != pre["digest"] and post["origins"] == ["fold:0:1", None, 1]
    oc = f5.origin_check(r, 0, post, None)
    assert oc["kept_once"] == 6 and set(oc["kept_at"].values()) == {"fold:0:1"}
    exp = f5.expected_origins(r, 0, "post", "fold:0:1")
    assert all(oc["kept_at"][i] == exp[i] for i in root["new0"])

    gj = json.loads((r / "generations.json").read_text())
    gj_old = dict(gj, mask={"deleted": [], "superseded": {}}, shard_manifest=str(old_manifest))
    old_manifest.write_text(Path(post["manifest"]).read_text())
    (r / "generations.json").write_text(json.dumps(gj_old))
    torn = f5.served_state(r)
    assert torn["digest"] not in (pre["digest"], post["digest"])
    oc = f5.origin_check(r, 0, torn, None)
    assert oc["kept_twice_or_more"] == 6
    monkeypatch.setattr(f5, "own_lookups", lambda *a, **k: {"found_once_expected": 0, "missed": [], "double": [],
                                                             "wrong_origin": [], "n": 0})
    assert f5.inspect_state(r, 0, pre, post, "fold:0:1", [], None)["state"] == "NEITHER"
    old_manifest.write_text(old_body)
    (r / "generations.json").write_bytes(pre_gj)
    assert f5.inspect_state(r, 0, pre, post, "fold:0:1", [], None)["state"] == "PRE"


def test_publish_fold_is_rerunnable_after_a_kill_at_each_step(root, monkeypatch):
    r, led = root["root"], root["led"]
    cfg, d, mm = _fold(root, root["new0"])
    foldin.mark_fold_ready(led, 0, 1, {"test": True})
    real = generation.publish

    def die(*a, **k):
        raise KeyboardInterrupt("simulated SIGKILL after the ledger commit")
    monkeypatch.setattr(generation, "publish", die)
    with pytest.raises(KeyboardInterrupt):
        foldin.publish_fold(r, led, root["base"], 0, 1, confirm=True, cfg=cfg,
                            base_shard_manifest=str(root["served"]), baseline_roots=[], prefault=False)
    monkeypatch.setattr(generation, "publish", real)
    pre_like = f5.served_state(r)
    assert pre_like["origins"] == [None, None, 1]
    foldin.publish_fold(r, led, root["base"], 0, 1, confirm=True, cfg=cfg,
                        base_shard_manifest=str(root["served"]), baseline_roots=[], prefault=False)
    assert f5.served_state(r)["origins"] == ["fold:0:1", None, 1]


def test_publish_fold_rerun_after_kill_between_compose_and_ledger(root, monkeypatch):
    r, led = root["root"], root["led"]
    cfg, d, mm = _fold(root, root["new0"])
    foldin.mark_fold_ready(led, 0, 1, {"test": True})
    real_compose = foldin.compose_fold_manifest

    def compose_then_die(*a, **k):
        real_compose(*a, **k)
        raise KeyboardInterrupt("simulated SIGKILL after compose")
    monkeypatch.setattr(foldin, "compose_fold_manifest", compose_then_die)
    with pytest.raises(KeyboardInterrupt):
        foldin.publish_fold(r, led, root["base"], 0, 1, confirm=True, cfg=cfg,
                            base_shard_manifest=str(root["served"]), baseline_roots=[], prefault=False)
    monkeypatch.setattr(foldin, "compose_fold_manifest", real_compose)
    assert led.db.execute("SELECT state FROM folds WHERE fold=1").fetchone()[0] == "ready"
    foldin.publish_fold(r, led, root["base"], 0, 1, confirm=True, cfg=cfg,
                        base_shard_manifest=str(root["served"]), baseline_roots=[], prefault=False)
    assert f5.served_state(r)["origins"] == ["fold:0:1", None, 1]


def test_next_fold_skips_a_dir_left_without_a_ledger_row(root):
    t = root["tmp"]
    cfg = foldin.GuardConfig(fold_root=t / "foldroot", repo_data=t / "repo" / "data", stage_dir=t / "stage",
                             manifests=(), repo_root=t / "repo")
    (t / "foldroot").mkdir(exist_ok=True)
    foldin.make_fold_dir(cfg, 0, 1)
    assert foldin.next_fold(root["led"], 0) == 1
    assert foldin.next_fold(root["led"], 0, cfg.fold_root) == 2


def test_fold_stage_names_what_a_kill_left(tmp_path):
    d = tmp_path / "fold3"
    assert f5.fold_stage(d, None) == "before_mkdir"
    d.mkdir()
    assert f5.fold_stage(d, None) == "after_mkdir_before_ledger_row"
    (d / "fold.jsonl.parts").mkdir()
    assert f5.fold_stage(d, {"state": "building"}) == "dump"
    (d / "fold.jsonl.parts").rmdir()
    (d / "fold.jsonl").write_text("")
    assert f5.fold_stage(d, {"state": "building"}) == "build"
    (d / "fold.index.seismic").write_text("")
    assert f5.fold_stage(d, {"state": "building"}) == "c1a"
    (d / "fold.json").write_text("{}")
    assert f5.fold_stage(d, {"state": "building"}) == "after_fold_json"
    assert f5.fold_stage(d, {"state": "built"}) == "finished"
