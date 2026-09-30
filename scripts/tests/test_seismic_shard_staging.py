"""SEISMIC shard staging must never delete a staged shard it cannot replace.

Incident 2026-09-29: a process given `staged_manifest.json` while
`SFU_SEISMIC_STAGE_DIR` pointed at the same directory removed staged shard 0
(source and destination were the same path). What this file asserts:

  * a fresh stage copies the shards and rewrites the manifest,
  * a second call re-copies nothing,
  * staging the staged manifest into its own stage dir leaves every file,
  * a changed source is re-copied,
  * a failing copy leaves the previous staged shard in place.

Run: .venv/bin/python3 -m pytest scripts/tests/test_seismic_shard_staging.py -q
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from lib.thinclient import retriever as R  # noqa: E402


def _make_source(root: Path, n: int = 2) -> Path:
    shards = []
    for i in range(n):
        d = root / "src" / f"shard{i}.mmap"
        d.mkdir(parents=True)
        (d / "forward.bin").write_bytes(bytes([i]) * (1000 + i))
        (d / "postings.bin").write_bytes(bytes([i + 7]) * 300)
        shards.append({"shard": i, "mmap_dir": str(d)})
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"shards": shards}))
    return manifest


def _snapshot(stage: Path) -> dict:
    return {str(p.relative_to(stage)): p.read_bytes()
            for p in sorted(stage.rglob("*")) if p.is_file()}


def test_fresh_stage_copies_and_rewrites_manifest(tmp_path):
    manifest = _make_source(tmp_path)
    stage = tmp_path / "stage"
    out = R._stage_shards_local(str(manifest), str(stage))
    data = json.loads(Path(out).read_text())
    for i, s in enumerate(data["shards"]):
        d = Path(s["mmap_dir"])
        assert d.parent == stage
        assert (d / "forward.bin").read_bytes() == bytes([i]) * (1000 + i)
        assert (d / ".staged_ok").is_file()


def test_second_call_does_not_recopy(tmp_path, monkeypatch):
    manifest = _make_source(tmp_path)
    stage = tmp_path / "stage"
    R._stage_shards_local(str(manifest), str(stage))

    def boom(*a, **k):
        raise AssertionError("re-copied an already staged shard")
    monkeypatch.setattr(shutil, "copytree", boom)
    monkeypatch.setattr(shutil, "rmtree", boom)
    R._stage_shards_local(str(manifest), str(stage))


def test_staged_manifest_into_its_own_stage_dir_keeps_every_file(tmp_path):
    manifest = _make_source(tmp_path)
    stage = tmp_path / "stage"
    staged = R._stage_shards_local(str(manifest), str(stage))
    before = _snapshot(stage)
    again = R._stage_shards_local(staged, str(stage))
    assert _snapshot(stage) == before
    data = json.loads(Path(again).read_text())
    assert [Path(s["mmap_dir"]).parent for s in data["shards"]] == [stage, stage]


def test_changed_source_is_recopied(tmp_path):
    manifest = _make_source(tmp_path)
    stage = tmp_path / "stage"
    R._stage_shards_local(str(manifest), str(stage))
    src0 = tmp_path / "src" / "shard0.mmap" / "forward.bin"
    src0.write_bytes(b"\x55" * 4321)
    R._stage_shards_local(str(manifest), str(stage))
    assert (stage / "shard0.mmap" / "forward.bin").read_bytes() == b"\x55" * 4321
    assert not list(stage.glob("*.tmp-*"))


def test_failed_copy_leaves_the_old_staged_shard(tmp_path, monkeypatch):
    manifest = _make_source(tmp_path)
    stage = tmp_path / "stage"
    R._stage_shards_local(str(manifest), str(stage))
    before = _snapshot(stage)
    (tmp_path / "src" / "shard0.mmap" / "forward.bin").write_bytes(b"\x01" * 9)

    def fail(*a, **k):
        raise OSError("copy failed")
    monkeypatch.setattr(shutil, "copytree", fail)
    with pytest.raises(OSError):
        R._stage_shards_local(str(manifest), str(stage))
    assert _snapshot(stage) == before
