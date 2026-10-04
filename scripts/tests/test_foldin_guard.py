"""Doc 10 §3 G3 — fold-in write protection, manifest repoint and the operator
publish, on TMP TREES ONLY. No test here names, stats or creates anything
under the real repo `data/`, `/var/tmp/seismic_stage` or the served shards:
every protected root is a tmp stand-in passed through `GuardConfig`.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest import foldin  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.foldin import (SENTINEL, BaselineChanged, FoldGuardError, GuardConfig,  # noqa: E402
                                       baseline_check, baseline_snapshot, check_target,
                                       check_writable, compose_fold_manifest, make_fold_dir)
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402
from spike.delta_ingest.routing import route_shard  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    repo = tmp_path / "repo"
    data = repo / "data"
    served = data / "seismic" / "plan01"
    for s in range(2):
        d = served / f"shard{s}.mmap"
        d.mkdir(parents=True)
        (d / "forward_data.bin").write_bytes(b"x" * (10 + s))
    staged = tmp_path / "stage"
    (staged / "shard0.mmap").mkdir(parents=True)
    (staged / "shard0.mmap" / "forward_data.bin").write_bytes(b"y")
    outside = tmp_path / "elsewhere" / "served_copy.mmap"
    outside.mkdir(parents=True)
    served_manifest = tmp_path / "served_manifest.json"
    served_manifest.write_text(json.dumps({"n_shards": 2, "shards": [
        {"shard": 0, "mmap_dir": "data/seismic/plan01/shard0.mmap", "n_docs": 10},
        {"shard": 1, "mmap_dir": str(outside), "n_docs": 11}]}))
    staged_manifest = staged / "staged_manifest.json"
    staged_manifest.write_text(json.dumps({"shards": [{"mmap_dir": str(staged / "shard0.mmap")}]}))
    fold_root = tmp_path / "work" / "foldin"
    fold_root.mkdir(parents=True)
    cfg = GuardConfig(fold_root=fold_root, repo_data=data, stage_dir=staged,
                      manifests=(served_manifest, staged_manifest), repo_root=repo)
    return {"cfg": cfg, "repo": repo, "data": data, "staged": staged, "outside": outside,
            "served_manifest": served_manifest, "fold_root": fold_root, "tmp": tmp_path}


def test_accepts_a_fresh_fold_dir(tree):
    d = make_fold_dir(tree["cfg"], 0, 1)
    assert d == (tree["fold_root"] / "shard0" / "fold1").resolve()
    assert json.loads((d / SENTINEL).read_text())["path"] == str(d)
    assert check_writable(d, tree["cfg"]) == d


def test_refuses_inside_repo_data(tree):
    with pytest.raises(FoldGuardError, match="protected root"):
        check_target(tree["data"] / "seismic" / "new_fold", tree["cfg"])


def test_refuses_inside_stage_dir(tree):
    with pytest.raises(FoldGuardError, match="protected root"):
        check_target(tree["staged"] / "fold", tree["cfg"])


def test_refuses_served_manifest_mmap_dir_outside_data(tree):
    with pytest.raises(FoldGuardError, match="protected root"):
        check_target(tree["outside"] / "sub", tree["cfg"])


def test_refuses_staged_manifest_mmap_dir(tree):
    cfg = tree["cfg"]
    other_stage = tree["tmp"] / "stage2" / "s.mmap"
    other_stage.mkdir(parents=True)
    m = tree["tmp"] / "staged2.json"
    m.write_text(json.dumps({"shards": [{"mmap_dir": str(other_stage)}]}))
    cfg2 = GuardConfig(fold_root=cfg.fold_root, repo_data=cfg.repo_data, stage_dir=cfg.stage_dir,
                       manifests=cfg.manifests + (m,), repo_root=cfg.repo_root)
    with pytest.raises(FoldGuardError, match="protected root"):
        check_target(other_stage, cfg2)


def test_refuses_fold_root_inside_protected_tree(tree):
    cfg = tree["cfg"]
    bad = GuardConfig(fold_root=tree["data"] / "foldin", repo_data=cfg.repo_data,
                      stage_dir=cfg.stage_dir, manifests=cfg.manifests, repo_root=cfg.repo_root)
    with pytest.raises(FoldGuardError, match="protected root"):
        check_target(tree["data"] / "foldin" / "shard0" / "fold1", bad)


def test_refuses_outside_fold_root_and_the_root_itself(tree):
    with pytest.raises(FoldGuardError, match="not strictly under"):
        check_target(tree["tmp"] / "work" / "other", tree["cfg"])
    with pytest.raises(FoldGuardError, match="not strictly under"):
        check_target(tree["fold_root"], tree["cfg"])


def test_refuses_symlinked_path_component(tree):
    link = tree["fold_root"] / "shard0"
    link.symlink_to(tree["data"])
    with pytest.raises(FoldGuardError):
        check_target(link / "fold1", tree["cfg"])
    elsewhere = tree["tmp"] / "work" / "foldin_alias_target"
    elsewhere.mkdir()
    link2 = tree["fold_root"] / "shard1"
    link2.symlink_to(elsewhere)
    with pytest.raises(FoldGuardError):
        check_target(link2 / "fold1", tree["cfg"])


def test_refuses_non_local_filesystem(tree):
    cfg = tree["cfg"]
    fake = f"overlay / overlay rw 0 0\nhost {tree['fold_root']} 9p rw 0 0\n"
    cfg9p = GuardConfig(fold_root=cfg.fold_root, repo_data=cfg.repo_data, stage_dir=cfg.stage_dir,
                        manifests=cfg.manifests, repo_root=cfg.repo_root, mounts_text=fake)
    with pytest.raises(FoldGuardError, match="not local"):
        check_target(tree["fold_root"] / "shard0" / "fold1", cfg9p)


def test_refuses_symlink_entry_inside_fold_dir(tree):
    d = make_fold_dir(tree["cfg"], 0, 1)
    (d / "fold.mmap").symlink_to(tree["data"] / "seismic" / "plan01" / "shard0.mmap")
    with pytest.raises(FoldGuardError, match="symlink"):
        check_writable(d, tree["cfg"])


def test_refuses_hard_linked_file(tree):
    d = make_fold_dir(tree["cfg"], 0, 1)
    victim = tree["tmp"] / "work" / "victim.bin"
    victim.write_bytes(b"z")
    os.link(victim, d / "forward_data.bin")
    with pytest.raises(FoldGuardError, match="hard links"):
        check_writable(d, tree["cfg"])


def test_refuses_missing_sentinel(tree):
    d = tree["fold_root"] / "shard0" / "fold1"
    d.mkdir(parents=True)
    with pytest.raises(FoldGuardError, match="sentinel"):
        check_writable(d, tree["cfg"])


def test_refuses_copied_sentinel(tree):
    d = make_fold_dir(tree["cfg"], 0, 1)
    copy = tree["fold_root"] / "shard0" / "fold2"
    copy.mkdir()
    (copy / SENTINEL).write_text((d / SENTINEL).read_text())
    with pytest.raises(FoldGuardError, match="sentinel names"):
        check_writable(copy, tree["cfg"])


def test_refuses_reusing_a_fold_number(tree):
    make_fold_dir(tree["cfg"], 0, 1)
    with pytest.raises(FoldGuardError, match="never reused"):
        make_fold_dir(tree["cfg"], 0, 1)


def test_default_config_protects_the_real_paths_without_touching_them():
    cfg = GuardConfig()
    roots = [str(r) for r in cfg.protected_roots()]
    assert str((REPO / "data").resolve()) in roots
    assert any(r.endswith("seismic_stage") for r in roots)
    assert cfg.fold_root == Path("/home/vscode/work/delta_ingest/foldin")


def _base_files(tree):
    return {p: p.read_bytes() for p in tree["data"].rglob("*") if p.is_file()}


def test_compose_manifest_repoints_one_record_and_never_overwrites(tree):
    cfg = tree["cfg"]
    d = make_fold_dir(cfg, 1, 1)
    mm = d / "fold.dotvbyte.v2.mmap"
    mm.mkdir()
    before_manifest = tree["served_manifest"].read_bytes()
    before = _base_files(tree)
    out = tree["fold_root"] / "manifests" / "m.json"
    compose_fold_manifest(tree["served_manifest"], 1, 1, mm, 12, out, cfg)
    got = json.loads(out.read_text())
    assert got["shards"][0] == {"shard": 0, "mmap_dir": "data/seismic/plan01/shard0.mmap", "n_docs": 10}
    assert got["shards"][1]["mmap_dir"] == str(mm) and got["shards"][1]["fold_origin"] == "fold:1:1"
    assert got["shards"][1]["fold_of"]["mmap_dir"] == str(tree["outside"])
    assert tree["served_manifest"].read_bytes() == before_manifest
    assert _base_files(tree) == before
    with pytest.raises(FoldGuardError, match="never overwritten"):
        compose_fold_manifest(tree["served_manifest"], 1, 1, mm, 12, out, cfg)
    with pytest.raises(FoldGuardError):
        compose_fold_manifest(tree["served_manifest"], 1, 1, mm, 12, tree["data"] / "m.json", cfg)


def test_baseline_detects_changed_new_and_missing(tree):
    roots = [tree["data"], tree["staged"]]
    snap = baseline_snapshot(roots)
    assert baseline_check(snap, roots, retries=0)["changed"] == []
    f = tree["data"] / "seismic" / "plan01" / "shard0.mmap" / "forward_data.bin"
    f.write_bytes(b"changed!!!!")
    with pytest.raises(BaselineChanged):
        baseline_check(snap, roots, retries=0)
    snap = baseline_snapshot(roots)
    (tree["staged"] / "new.bin").write_bytes(b"n")
    with pytest.raises(BaselineChanged):
        baseline_check(snap, roots, retries=0)
    snap = baseline_snapshot(roots)
    f.unlink()
    with pytest.raises(BaselineChanged):
        baseline_check(snap, roots, retries=1, sleep_s=0.01)


def _ready_fold(tree, ledger, shard, fold, ids):
    cfg = tree["cfg"]
    d = make_fold_dir(cfg, shard, fold)
    mm = d / "fold.dotvbyte.v2.mmap"
    mm.mkdir()
    (mm / "forward_data.bin").write_bytes(b"f")
    foldin.ensure_fold_schema(ledger)
    staged = dict(ledger.db.execute("SELECT id, last_seen FROM docs"))
    info = {"mmap_dir": str(mm), "format": "dotvbyte_fixedu8_v2", "dump": {"docs": 5}}
    with ledger.db:
        ledger.db.execute("INSERT INTO folds VALUES (?,?,?,?,?,?,?,?,?)",
                          (shard, fold, "built", 0.0, 0.0, None, str(d), None, json.dumps(info)))
        ledger.db.executemany("INSERT INTO fold_members VALUES (?,?,?,?)",
                              [(shard, fold, i, staged[i]) for i in ids])
    return d


def _ids_routed_to(shard, n):
    out, i = [], 1
    while len(out) < n:
        if route_shard(f"W{i}") == shard:
            out.append(f"W{i}")
        i += 1
    return out


def test_publish_fold_is_operator_only_and_repoints_via_manifest(tree, monkeypatch):
    cfg = tree["cfg"]
    delta = tree["tmp"] / "work" / "delta"
    delta.mkdir()
    idx = tree["tmp"] / "index"
    idx.mkdir()
    led = IngestLedger(delta / "ledger.sqlite")
    ids = _ids_routed_to(1, 3)
    recs = [DocRecord(id=i, title=f"t {i}", sparse_field={"a": 1.0}) for i in ids]
    led.stage(recs, {ids[0]: True})
    led.db.execute("UPDATE docs SET generation=1")
    led.db.commit()
    base = BaseIndex(idx)
    _ready_fold(tree, led, 1, 1, ids[:2])
    roots = [tree["data"], tree["staged"]]
    with pytest.raises(ValueError, match="READY"):
        foldin.publish_fold(delta, led, base, 1, 1, confirm=True, cfg=cfg,
                            base_shard_manifest=str(tree["served_manifest"]), baseline_roots=roots)
    foldin.mark_fold_ready(led, 1, 1, {"F2": "synthetic"})
    dry = foldin.publish_fold(delta, led, base, 1, 1, confirm=False, cfg=cfg,
                              base_shard_manifest=str(tree["served_manifest"]), baseline_roots=roots)
    assert dry["dry_run"] and not (delta / "generations.json").exists()
    assert led.db.execute("SELECT COUNT(*) FROM docs WHERE seismic_origin IS NOT NULL").fetchone()[0] == 0
    before = _base_files(tree)
    out = foldin.publish_fold(delta, led, base, 1, 1, confirm=True, cfg=cfg,
                              base_shard_manifest=str(tree["served_manifest"]), baseline_roots=roots)
    assert out["marked_seismic_origin"] == 2
    assert _base_files(tree) == before
    gj = json.loads((delta / "generations.json").read_text())
    assert gj["mask"]["newest_by_leg"] == {"seismic": {ids[0]: "fold:1:1", ids[1]: "fold:1:1"}}
    sm = json.loads(Path(gj["shard_manifest"]).read_text())
    assert [r.get("fold_origin") for r in sm["shards"]] == [None, "fold:1:1"]
    assert led.active_fold_manifest() == out["manifest"]
    led.stage([DocRecord(id=ids[1], title="t again", sparse_field={"a": 2.0})], {})
    assert led.mask()["newest_by_leg"] == {"seismic": {ids[0]: "fold:1:1"}}
    from spike.delta_ingest.generation import publish
    again = publish(delta, led, base)
    assert again["shard_manifest"] and json.loads(Path(again["shard_manifest"]).read_text())["shards"][1][
        "fold_origin"] == "fold:1:1"
    led.close()
    base.close()


def test_publish_fold_aborts_on_baseline_change(tree, monkeypatch):
    cfg = tree["cfg"]
    delta = tree["tmp"] / "work" / "delta"
    delta.mkdir()
    idx = tree["tmp"] / "index"
    idx.mkdir()
    led = IngestLedger(delta / "ledger.sqlite")
    ids = _ids_routed_to(1, 1)
    led.stage([DocRecord(id=ids[0], title="x", sparse_field={"a": 1.0})], {})
    base = BaseIndex(idx)
    _ready_fold(tree, led, 1, 1, ids)
    foldin.mark_fold_ready(led, 1, 1, {})
    roots = [tree["data"], tree["staged"]]
    from spike.delta_ingest import generation
    real = generation.publish

    def tamper(*a, **k):
        (tree["data"] / "tampered.bin").write_bytes(b"t")
        return real(*a, **k)
    monkeypatch.setattr(generation, "publish", tamper)
    with pytest.raises(BaselineChanged):
        foldin.publish_fold(delta, led, base, 1, 1, confirm=True, cfg=cfg,
                            base_shard_manifest=str(tree["served_manifest"]), baseline_roots=roots)
    led.close()
    base.close()


def test_build_fold_refuses_without_pinned_token_map(tree):
    led = IngestLedger(tree["tmp"] / "work" / "l.sqlite")
    with pytest.raises(ValueError, match="pins input_token_to_id_map"):
        foldin.build_fold(tree["tmp"], led, 0, tree["tmp"], token_map_dir=None, cfg=tree["cfg"])
    led.close()


def test_extend_token_map_keeps_ids():
    pinned = {"a": 0, "b": 1, "c": 2}
    out, extra = foldin.extend_token_map(pinned, ["b", "z", "y"])
    assert extra == ["y", "z"] and out == {"a": 0, "b": 1, "c": 2, "y": 3, "z": 4}
