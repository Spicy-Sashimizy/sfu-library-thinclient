"""Tests for scripts/demo_broker/build_demo_payload_manifest.py.

Covers the two things that would silently break the OCI Phase-1 seed:
  1. the INCLUDE/EXCLUDE rules (a stale rule ships 44 GB of packed/ tarballs, or
     the ablated dense leg, or this container's dense/delta.sqlite query history);
  2. the RESUMABLE hashing (a --hash run that re-reads 108 GB every time is not
     resumable, and one that reuses a stale sha256 is worse than useless).

The module walks a REAL tree, so each test builds a miniature repo in tmp_path
and re-points the module's REPO / served-shard-manifest globals at it.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "demo_broker"))

import build_demo_payload_manifest as bpm  # noqa: E402


def _write(p: Path, content: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


@pytest.fixture()
def fake_repo(tmp_path, monkeypatch):
    """A miniature repo with one served shard, one ladder shard, the packed/
    tarballs, the dense leg + its runtime delta.sqlite, models with training
    checkpoints, and code with __pycache__."""
    root = tmp_path / "repo"
    shard_served = root / "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap"
    shard_old = root / "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.mmap"
    _write(shard_served / "forward_data.bin", "SERVED" * 10)
    _write(shard_served / "manifest.json", "{}")
    _write(shard_old / "forward_data.bin", "LADDER" * 10)

    sm = root / "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
    _write(sm, json.dumps({"shards": [{
        "shard": 0,
        "mmap_dir": "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap",
    }]}))

    ti = root / "data/thinclient_index"
    _write(ti / "meta.sqlite", "META")
    _write(ti / "meta.sqlite-wal", "WAL")
    _write(ti / "manifest.json", "{}")
    _write(ti / "build_status.json", "{}")
    _write(ti / "sections/social_sciences__recent/tantivy/meta.json", "{}")
    _write(ti / "sections/social_sciences__recent/abstracts.sqlite", "ABS")
    _write(ti / "sections/social_sciences__recent/abstracts.sqlite.flat/blocks.bin", "FLAT")
    _write(ti / "sections/cs_math__archive/tantivy/meta.json", "{}")
    _write(ti / "packed/other__recent.tar.zst", "PACKED")
    _write(ti / "dense/b1.usearch", "DENSE")
    _write(ti / "dense/ids.json", "[]")
    _write(ti / "dense/rescore_int8.npy", "R")
    _write(ti / "dense/delta.sqlite", "WARMCACHE")
    _write(ti / "dense/delta.sqlite-wal", "W")
    _write(ti / "spool/leftover.jsonl", "S")

    _write(root / "models/splade_onnx_fused/model.onnx", "SPLADE")
    _write(root / "models/sfu-academic-embed-v5/model.safetensors", "V5")
    _write(root / "models/sfu-academic-embed-v5/checkpoints/step_1000/w.bin", "CKPT")
    _write(root / "models/sfu-cross-encoder-v1/model.bin", "CE")
    _write(root / "models/sfu-cross-encoder-v1-onnx-int8/model_quantized.onnx", "CE8")
    _write(root / "models/model_registry.json", "{}")
    _write(root / "models/sfu-academic-embed-v4-bge/model.safetensors", "OLD")
    _write(root / "spike/seismic_upstream/target/portable_so/seismic_x86_64_v3.so", "SO")
    _write(root / "spike/seismic_upstream/target/portable_so/v3/seismic/__init__.py", "")

    _write(root / "source/sfu_library_mcp_http.py", "code")
    _write(root / "source/lib/embedding.py", "code")
    _write(root / "source/__pycache__/x.cpython-311.pyc", "PYC")
    _write(root / "web/search.js", "js")
    _write(root / "scripts/serve_http.sh", "sh")
    _write(root / "scripts/data/demo_payload_manifest.json", "{}")
    _write(root / "logs/serve.log", "L")

    monkeypatch.setattr(bpm, "REPO", root)
    monkeypatch.setattr(bpm, "SERVED_SHARD_MANIFEST", sm)
    return root


def _paths(rec):
    return {f["path"] for f in rec["files"]}


def test_include_rules(fake_repo, tmp_path):
    rec = bpm.build_manifest(tmp_path / "m.json")
    paths = _paths(rec)
    for wanted in [
        "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap/forward_data.bin",
        "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json",
        "data/thinclient_index/meta.sqlite",
        "data/thinclient_index/sections/social_sciences__recent/tantivy/meta.json",
        "data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite",
        "data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite.flat/blocks.bin",
        "models/splade_onnx_fused/model.onnx",
        "models/sfu-academic-embed-v5/model.safetensors",
        "models/sfu-cross-encoder-v1-onnx-int8/model_quantized.onnx",
        "spike/seismic_upstream/target/portable_so/seismic_x86_64_v3.so",
        "source/lib/embedding.py",
        "web/search.js",
        "scripts/serve_http.sh",
    ]:
        assert wanted in paths, f"missing from payload: {wanted}"
    assert rec["totals"]["files"] == len(paths)
    assert rec["totals"]["bytes"] == sum(f["bytes"] for f in rec["files"])
    assert rec["missing_paths"] == []


def test_exclude_rules(fake_repo, tmp_path):
    """Every exclusion the OCI payload decision depends on."""
    rec = bpm.build_manifest(tmp_path / "m.json")
    paths = _paths(rec)
    for banned in [
        "data/thinclient_index/dense/b1.usearch",
        "data/thinclient_index/dense/ids.json",
        "data/thinclient_index/dense/rescore_int8.npy",
        "data/thinclient_index/dense/delta.sqlite",
        "data/thinclient_index/dense/delta.sqlite-wal",
        "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.mmap/forward_data.bin",
        "data/thinclient_index/packed/other__recent.tar.zst",
        "data/thinclient_index/spool/leftover.jsonl",
        "models/sfu-academic-embed-v5/checkpoints/step_1000/w.bin",
        "models/sfu-academic-embed-v4-bge/model.safetensors",
        "data/thinclient_index/meta.sqlite-wal",
        "source/__pycache__/x.cpython-311.pyc",
        "scripts/data/demo_payload_manifest.json",
        "logs/serve.log",
    ]:
        assert banned not in paths, f"must NOT be in the payload: {banned}"


def test_include_dense_opt_in_never_ships_delta(fake_repo, tmp_path):
    rec = bpm.build_manifest(tmp_path / "m.json", include_dense=True)
    paths = _paths(rec)
    assert "data/thinclient_index/dense/b1.usearch" in paths
    assert "data/thinclient_index/dense/ids.json" in paths
    assert "data/thinclient_index/dense/rescore_int8.npy" in paths
    assert "data/thinclient_index/dense/delta.sqlite" not in paths
    assert "data/thinclient_index/dense/delta.sqlite-wal" not in paths


def test_sqlite_free_abstracts_drops_only_where_flat_exists(fake_repo, tmp_path):
    _write(fake_repo / "data/thinclient_index/sections/med_bio__recent/abstracts.sqlite", "A2")
    rec = bpm.build_manifest(tmp_path / "m.json", sqlite_free_abstracts=True)
    paths = _paths(rec)
    assert ("data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite"
            not in paths)
    assert ("data/thinclient_index/sections/social_sciences__recent/"
            "abstracts.sqlite.flat/blocks.bin") in paths
    assert "data/thinclient_index/sections/med_bio__recent/abstracts.sqlite" in paths


def test_components_and_totals_are_consistent(fake_repo, tmp_path):
    rec = bpm.build_manifest(tmp_path / "m.json")
    assert sum(c["files"] for c in rec["components"]) == rec["totals"]["files"]
    assert sum(c["bytes"] for c in rec["components"]) == rec["totals"]["bytes"]
    names = [c["name"] for c in rec["components"]]
    assert names == ["seismic_served_shards", "seismic_shard_manifest",
                     "thinclient_meta", "thinclient_sections",
                     "models_serve_path", "seismic_portable_so", "code"]


def test_missing_paths_are_reported_not_silently_skipped(fake_repo, tmp_path):
    (fake_repo / "models/splade_onnx_fused/model.onnx").unlink()
    (fake_repo / "models/splade_onnx_fused").rmdir()
    rec = bpm.build_manifest(tmp_path / "m.json")
    assert "models/splade_onnx_fused" in rec["missing_paths"]


def test_hash_populates_sha256(fake_repo, tmp_path):
    out = tmp_path / "m.json"
    rec = bpm.build_manifest(out, do_hash=True)
    assert all("sha256" in f for f in rec["files"])
    import hashlib
    e = next(f for f in rec["files"] if f["path"] == "data/thinclient_index/meta.sqlite")
    assert e["sha256"] == hashlib.sha256(b"META").hexdigest()
    assert rec["hash_stats"]["hashed_this_run"] == rec["totals"]["files"]
    assert rec["hash_stats"]["reused_from_prior"] == 0


def test_hash_is_resumable_unchanged_files_are_not_rehashed(fake_repo, tmp_path):
    out = tmp_path / "m.json"
    bpm._write(out, bpm.build_manifest(out, do_hash=True))
    n = json.loads(out.read_text())["totals"]["files"]

    rec2 = bpm.build_manifest(out, do_hash=True)
    assert rec2["hash_stats"]["reused_from_prior"] == n
    assert rec2["hash_stats"]["hashed_this_run"] == 0


def test_hash_resume_rehashes_a_changed_file(fake_repo, tmp_path):
    import hashlib
    import os
    out = tmp_path / "m.json"
    bpm._write(out, bpm.build_manifest(out, do_hash=True))

    changed = fake_repo / "data/thinclient_index/meta.sqlite"
    changed.write_text("META-V2")
    os.utime(changed, ns=(0, 0))

    rec = bpm.build_manifest(out, do_hash=True)
    assert rec["hash_stats"]["hashed_this_run"] == 1
    assert rec["hash_stats"]["reused_from_prior"] == rec["totals"]["files"] - 1
    e = next(f for f in rec["files"] if f["path"] == "data/thinclient_index/meta.sqlite")
    assert e["sha256"] == hashlib.sha256(b"META-V2").hexdigest()


def test_hash_resume_ignores_a_prior_partial_entry_without_sha(fake_repo, tmp_path):
    """An interrupted --hash run flushes a manifest whose tail entries have no
    sha256; those must be hashed on resume, not carried forward as complete."""
    out = tmp_path / "m.json"
    rec = bpm.build_manifest(out, do_hash=True)
    for f in rec["files"][-2:]:
        f.pop("sha256")
    bpm._write(out, rec)

    rec2 = bpm.build_manifest(out, do_hash=True)
    assert rec2["hash_stats"]["hashed_this_run"] == 2
    assert all("sha256" in f for f in rec2["files"])


def test_no_hash_run_records_no_sha256(fake_repo, tmp_path):
    rec = bpm.build_manifest(tmp_path / "m.json")
    assert not any("sha256" in f for f in rec["files"])
    assert rec["options"]["hash"] is False


def test_cli_writes_manifest_and_files_from_list(fake_repo, tmp_path, capsys):
    out = tmp_path / "m.json"
    ff = tmp_path / "files.txt"
    rc = bpm.main(["--out", str(out), "--files-from", str(ff), "--quiet"])
    assert rc == 0
    rec = json.loads(out.read_text())
    lines = ff.read_text().splitlines()
    assert lines == [f["path"] for f in rec["files"]]
    assert all(not p.startswith("/") for p in lines), "files-from must be relative"
    assert rec["partial"] is False


def test_manifest_is_not_written_under_seismic_150m(fake_repo, tmp_path):
    """The IRREPLACEABLE read-only dir must be untouched: no writes anywhere
    under data/seismic_150m/ and no new files in the fake repo at all."""
    before = {p for p in fake_repo.rglob("*") if p.is_file()}
    bpm.build_manifest(tmp_path / "m.json", do_hash=True)
    after = {p for p in fake_repo.rglob("*") if p.is_file()}
    assert before == after
