"""O16 CLI wiring (delta root via resolve_delta_root) and from_gens kept in a
published generation's ledger info (reader `_buffer_generations`).

docs/delta_ingest/02_DESIGN.md §3.1 O16 and O2.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest import cli  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402


def test_cli_honours_sfu_delta_root_env(tmp_path, monkeypatch):
    index_root = tmp_path / "index"
    index_root.mkdir()
    target = tmp_path / "envroot"
    monkeypatch.setenv("SFU_DELTA_ROOT", str(target))
    out = cli.main(["status", "--index-root", str(index_root)])
    assert Path(out["delta_root"]) == target
    assert (target / "ledger.sqlite").exists()
    assert not (index_root / "delta").exists()


def test_cli_explicit_delta_root_wins_over_env(tmp_path, monkeypatch):
    index_root = tmp_path / "index"
    index_root.mkdir()
    monkeypatch.setenv("SFU_DELTA_ROOT", str(tmp_path / "envroot"))
    out = cli.main(["status", "--index-root", str(index_root), "--delta-root", str(tmp_path / "cli")])
    assert Path(out["delta_root"]) == tmp_path / "cli"
    assert not (tmp_path / "envroot").exists()


@pytest.fixture
def fake_data(tmp_path, monkeypatch):
    import lib.thinclient.delta_layer as dl
    data = tmp_path / "repo" / "data"
    (data / "seismic_150m").mkdir(parents=True)
    (data / "thinclient_index").mkdir()
    monkeypatch.setattr(dl, "REPO_DATA_DIR", data)
    monkeypatch.delenv("SFU_DELTA_ROOT", raising=False)
    return data


def test_cli_refuses_implicit_root_under_data(fake_data):
    with pytest.raises(SystemExit) as exc:
        cli.main(["status", "--index-root", str(fake_data / "thinclient_index")])
    assert "implicit delta root" in str(exc.value)
    assert not (fake_data / "thinclient_index" / "delta").exists()


def test_cli_refuses_root_inside_seismic_150m(fake_data, tmp_path):
    index_root = tmp_path / "index"
    index_root.mkdir()
    with pytest.raises(SystemExit) as exc:
        cli.main(["status", "--index-root", str(index_root),
                  "--delta-root", str(fake_data / "seismic_150m" / "delta")])
    assert "read-only" in str(exc.value)
    assert not (fake_data / "seismic_150m" / "delta").exists()


def test_cli_explicit_root_under_data_allowed(fake_data):
    out = cli.main(["status", "--index-root", str(fake_data / "thinclient_index"),
                    "--delta-root", str(fake_data / "thinclient_index" / "delta")])
    assert Path(out["delta_root"]) == fake_data / "thinclient_index" / "delta"


def test_finish_generation_keeps_from_gens(tmp_path):
    led = IngestLedger(tmp_path / "ledger.sqlite")
    recs = [DocRecord(id="W1", title="t", abstract="a" * 60)]
    led.stage(recs, {})
    led.open_generation(3, recs, from_gens=[1, 2])
    led.finish_generation(3, {"docs": 1, "seismic": "served"}, retire=[1, 2])
    info = json.loads(led.db.execute("SELECT info FROM generations WHERE gen=3").fetchone()[0])
    assert info["from_gens"] == [1, 2]
    assert info["docs"] == 1 and info["seismic"] == "served"
    led.open_generation(4, [], None)
    led.finish_generation(4, {"docs": 0})
    info4 = json.loads(led.db.execute("SELECT info FROM generations WHERE gen=4").fetchone()[0])
    assert info4["from_gens"] == [0]


def test_finish_generation_explicit_from_gens_not_overwritten(tmp_path):
    led = IngestLedger(tmp_path / "ledger.sqlite")
    led.open_generation(5, [], from_gens=[0])
    led.finish_generation(5, {"from_gens": [0], "docs": 0})
    info = json.loads(led.db.execute("SELECT info FROM generations WHERE gen=5").fetchone()[0])
    assert info["from_gens"] == [0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
