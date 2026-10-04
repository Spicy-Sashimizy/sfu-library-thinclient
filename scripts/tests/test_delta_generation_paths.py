"""O18 (docs/delta_ingest/02_DESIGN.md §3.1): generation.json must not record
paths under the `gNNNN.building/` staging dir, which is renamed to `gNNNN/`
at publish. Every path field of the `seismic` block is relative to the
generation dir and resolves to an existing file/dir after the rename.

Synthetic tmp tree only; the SEISMIC chain is replaced by a fake that writes
the same files and returns absolute paths exactly as `build_seismic_shard`
does, so the test needs no Rust toolchain."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest import generation  # noqa: E402
from spike.delta_ingest.profiles import PROFILES  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402

PATH_KEYS = ("jsonl", "stock", "mmap_dir")


def _records(n=4):
    return [DocRecord(id=f"W{900000 + i}", title=f"paper {i} on elections",
                      abstract="policy study", year=2020, type="article",
                      source="test", sparse_field={"elect": 1.0, f"t{i}": 0.5})
            for i in range(n)]


def _fake_chain(stages_ok: int):
    def fake(jsonl: Path, stem: Path, threads: int, *, want_dotvbyte: bool = True) -> dict:
        info = {"jsonl": str(jsonl), "stock": None, "mmap_dir": None, "format": None, "stages": {}}
        if stages_ok < 1:
            info["stages"]["build"] = "skipped: seismic not importable (fake)"
            return info
        stock = Path(f"{stem}.index.seismic")
        stock.write_bytes(b"x")
        info["stock"] = str(stock)
        info["stages"]["build"] = {"seconds": 0.0}
        if stages_ok < 2:
            info["stages"]["mmap"] = "skipped: fake"
            return info
        mmap_dir = Path(f"{stem}.mmap")
        mmap_dir.mkdir()
        info["mmap_dir"], info["format"] = str(mmap_dir), "f16"
        return info
    return fake


def _build(tmp_path, monkeypatch, stages_ok):
    monkeypatch.setattr(generation, "build_seismic_shard", _fake_chain(stages_ok))
    delta = tmp_path / "delta"
    delta.mkdir()
    final = generation.build_generation(delta, 3, _records(), PROFILES["laptop"], seismic=True)
    gi = json.loads((final / "generation.json").read_text())
    return final, gi


def _check(final: Path, gi: dict):
    s = gi["seismic"]
    assert ".building" not in json.dumps(gi)
    for k in PATH_KEYS:
        v = s.get(k)
        if v is None:
            continue
        assert not Path(v).is_absolute(), (k, v)
        assert (final / v).exists(), (k, v)


def test_full_chain_paths_relative_and_resolve(tmp_path, monkeypatch):
    final, gi = _build(tmp_path, monkeypatch, 2)
    assert gi["seismic"]["status"] == "served"
    assert gi["seismic"]["stock"] and gi["seismic"]["jsonl"]
    _check(final, gi)
    assert gi["seismic"]["mmap_dir"] == "seismic/delta_g0003.mmap"


def test_stock_only_paths_relative(tmp_path, monkeypatch):
    final, gi = _build(tmp_path, monkeypatch, 1)
    assert gi["seismic"]["status"] == "unavailable"
    assert gi["seismic"]["stock"] == "seismic/delta_g0003.index.seismic"
    _check(final, gi)


def test_build_skipped_jsonl_relative(tmp_path, monkeypatch):
    final, gi = _build(tmp_path, monkeypatch, 0)
    assert gi["seismic"]["jsonl"] == "seismic/delta_g0003.jsonl"
    _check(final, gi)


def test_publish_resolves_mmap_dir_under_final(tmp_path, monkeypatch):
    final, gi = _build(tmp_path, monkeypatch, 2)
    assert (final / gi["seismic"]["mmap_dir"]).is_dir()
    assert not (tmp_path / "delta" / "g0003.building").exists()
