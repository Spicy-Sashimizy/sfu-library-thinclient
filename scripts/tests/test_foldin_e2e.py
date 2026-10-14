"""Doc 10 G3/G4 plumbing end to end on a TOY shard in a tmp tree: real
SEISMIC build of a 300-doc "base shard", a ledger with an update (carrying a
token the base map lacks), a new doc, a delete and a doc routed elsewhere,
then `build_fold` (pinned token map) -> READY -> `publish_fold` -> the
serving layer's origins. Skips when the seismic toolchain is absent.
Nothing outside tmp_path is written.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest import foldin  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402
from spike.delta_ingest.routing import route_shard  # noqa: E402

_C1A = REPO / "spike/seismic_upstream/target/release/c1a_mmap_index"
VOCAB = ["cell", "receptor", "kinase", "membrane", "signal", "protein", "gene", "assay"]


def _ids(shard, n, start=9_000_000):
    out, i = [], start
    while len(out) < n:
        if route_shard(f"W{i}") == shard:
            out.append(f"W{i}")
        i += 1
    return out


def _mapping(mmap_dir: Path) -> list[str]:
    import numpy as np
    offs = np.fromfile(mmap_dir / "document_mapping_offsets.bin", dtype="<u8")
    blob = (mmap_dir / "document_mapping_strings.bin").read_bytes()
    return [blob[int(offs[i]):int(offs[i + 1])].decode() for i in range(len(offs) - 1)]


@pytest.mark.skipif(not _C1A.is_file(), reason="c1a_mmap_index not built")
def test_fold_build_publish_serve_toy(tmp_path, monkeypatch):
    pytest.importorskip("seismic")
    from spike.delta_ingest.generation import build_seismic_shard
    base_ids = _ids(0, 300)
    inp = tmp_path / "base"
    inp.mkdir()
    jl = inp / "base.jsonl"
    with open(jl, "w") as fh:
        for k, i in enumerate(base_ids):
            vec = {t: (3.0 if k < 5 and t == "kinase" else 0.5 + (k % 7) / 10) for t in VOCAB}
            fh.write(json.dumps({"id": i, "vector": vec}) + "\n")
    info = build_seismic_shard(jl, inp / "base", 2, want_dotvbyte=False)
    if not info.get("mmap_dir"):
        pytest.skip(f"seismic chain unavailable: {info['stages']}")
    base_mmap = Path(info["mmap_dir"])
    base_map = foldin.load_token_map(base_mmap)

    fold_root = tmp_path / "work" / "foldin"
    fold_root.mkdir(parents=True)
    fake_data = tmp_path / "repo" / "data"
    (fake_data / "seismic").mkdir(parents=True)
    (fake_data / "seismic" / "x.bin").write_bytes(b"x")
    served = tmp_path / "served.json"
    served.write_text(json.dumps({"n_shards": 2, "shards": [
        {"shard": 0, "mmap_dir": str(base_mmap), "n_docs": 300},
        {"shard": 1, "mmap_dir": str(tmp_path / "base1.mmap"), "n_docs": 1}]}))
    cfg = foldin.GuardConfig(fold_root=fold_root, repo_data=fake_data, stage_dir=tmp_path / "stage",
                             manifests=(), repo_root=tmp_path / "repo")
    roots = [fake_data]

    delta = tmp_path / "work" / "delta"
    delta.mkdir()
    led = IngestLedger(delta / "ledger.sqlite")
    upd, gone = base_ids[10], base_ids[11]
    new0 = _ids(0, 1, start=9_500_000)[0]
    new1 = _ids(1, 1, start=9_500_000)[0]
    recs = [DocRecord(id=upd, title="updated", sparse_field={"zebra": 4.0, "cell": 0.5}),
            DocRecord(id=new0, title="new", sparse_field={"kinase": 0.1, "gene": 0.2}),
            DocRecord(id=new1, title="other shard", sparse_field={"kinase": 9.0})]
    led.stage(recs, {upd: True})
    led.delete([gone], {gone: True})
    led.db.execute("UPDATE docs SET generation=1 WHERE status='live'")
    led.db.execute("UPDATE records SET generation=1")
    led.db.commit()

    out = foldin.build_fold(delta, led, 0, base_mmap, token_map_dir=base_mmap, cfg=cfg, threads=2,
                            workers=1, baseline_roots=roots)
    assert out["state"] == "built", out.get("stages")
    assert out["dump"]["dropped_base_rows"] == 2 and out["dump"]["added_delta_rows"] == 2
    assert out["token_map_appended"] == 1 and out["token_map_appended_sample"] == ["zebra"]
    fdir = Path(out["dir"])
    assert fdir.parent.parent == fold_root.resolve()
    fold_f16 = fdir / "fold.mmap"
    ids = _mapping(fold_f16)
    assert ids == [i for i in base_ids if i not in (upd, gone)] + sorted([upd, new0])
    fold_map = foldin.load_token_map(fold_f16)
    assert all(fold_map[t] == base_map[t] for t in base_map)
    assert fold_map["zebra"] == max(base_map.values()) + 1
    assert not (fdir / "fold.jsonl").exists()

    with pytest.raises(ValueError, match="READY"):
        foldin.publish_fold(delta, led, BaseIndex(tmp_path / "idx"), 0, out["fold"], confirm=True,
                            cfg=cfg, base_shard_manifest=str(served), baseline_roots=roots)
    foldin.mark_fold_ready(led, 0, out["fold"], {"toy": True})
    pub = foldin.publish_fold(delta, led, BaseIndex(tmp_path / "idx"), 0, out["fold"], confirm=True,
                              cfg=cfg, base_shard_manifest=str(served), baseline_roots=roots)
    assert pub["marked_seismic_origin"] == 2
    gj = json.loads((delta / "generations.json").read_text())
    assert gj["mask"]["newest_by_leg"]["seismic"] == {upd: "fold:0:1", new0: "fold:0:1"}

    from lib.thinclient.delta_layer import DeltaLayer
    dl = DeltaLayer(delta)
    sm = dl.shard_manifest_path()
    assert dl.shard_origins(2, sm) == ["fold:0:1", None]
    rec = json.loads(Path(sm).read_text())["shards"][0]
    assert rec["mmap_dir"] == out["mmap_dir"] and rec["fold_of"]["mmap_dir"] == str(base_mmap)
    dl.close()

    from lib.thinclient.sharded_seismic_backend import ParallelSeismicBackend
    import lib.opensearch_retriever as osr
    monkeypatch.setattr(osr, "encode_splade", lambda q, p: {"zebra": 2.0})
    m1 = tmp_path / "fold_only.json"
    m1.write_text(json.dumps({"n_shards": 1, "shards": [{"shard": 0, "mmap_dir": out["mmap_dir"]}]}))
    be = ParallelSeismicBackend.from_manifest(str(m1), load_mode="mmap")
    assert [d for d, _ in be.search("zebra", 3)][0] == upd
    led.close()
