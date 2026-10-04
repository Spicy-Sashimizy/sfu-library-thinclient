"""O14: base-vector reuse for text-unchanged base docs (exact-or-refuse).

docs/delta_ingest/02_DESIGN.md §3.1 O14. Synthetic f16 c1a shard twins are
written in the real on-disk layout; a seeded ledger decides eligibility
(R1/R2), the store decides exactness (R3-R5), and the CLI wires it behind
`--base-forward-dir` / `--base-locator-dir`.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest import cli  # noqa: E402
from spike.delta_ingest.base_vectors import (  # noqa: E402
    BaseVectorStore, base_reuse_candidates, build_locator, reusable_base_sparse)
from spike.delta_ingest.encode import ensure_sparse  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402

TOKENS = ["alpha", "beta", "gamma", "delta", "##ing", "épsilon"]


def _write_shard(d: Path, docs: list[tuple[str, list[int], list[float]]]) -> Path:
    d.mkdir(parents=True)
    offs, comps, vals, moffs, blob = [0], [], [], [0], b""
    for did, c, v in docs:
        comps += c
        vals += v
        offs.append(len(comps))
        blob += did.encode()
        moffs.append(len(blob))
    np.array(offs, dtype=np.uint64).tofile(d / "forward_offsets.bin")
    np.array(comps, dtype=np.uint16).tofile(d / "forward_components.bin")
    np.array(vals, dtype=np.float16).tofile(d / "forward_values.bin")
    np.array(moffs, dtype=np.uint64).tofile(d / "document_mapping_offsets.bin")
    (d / "document_mapping_strings.bin").write_bytes(blob)
    raw = struct.pack("<Q", len(TOKENS))
    for i, t in enumerate(TOKENS):
        b = t.encode()
        raw += struct.pack("<Q", len(b)) + b + struct.pack("<Q", i)
    (d / "token_to_id_map.bin").write_bytes(raw)
    return d


def _rec(i: int, title: str = "", is_oa: bool = False) -> DocRecord:
    return DocRecord(id=f"W{i}", title=title or f"title {i}", abstract=f"abstract text {i}",
                     year=2020, type="article", is_oa=is_oa, doi=f"10.1/{i}")


@pytest.fixture
def shards(tmp_path):
    s0 = _write_shard(tmp_path / "global_shard0of2.mmap", [
        ("W10", [0, 2, 5], [0.5, 1.25, 0.01000213623046875]),
        ("W11", [1], [3.3125]),
        ("X99", [0], [1.0]),
        ("W12", [3, 1], [0.5, 0.5]),
        ("W13", [0, 9], [0.5, 0.5]),
        ("W14", [], []),
    ])
    s1 = _write_shard(tmp_path / "global_shard1of2.mmap", [
        ("W20", [4], [0.75]),
        ("W21", [0, 1], [float("inf"), 0.5]),
        ("W11", [2], [0.5]),
    ])
    loc = tmp_path / "locators"
    infos = [build_locator(s0, loc / f"{s0.name}.locator", chunk=2),
             build_locator(s1, loc / f"{s1.name}.locator", chunk=2)]
    return [s0, s1], loc, infos


def test_locator_counts_and_non_w(shards):
    _, _, infos = shards
    assert infos[0]["docs"] == 6 and infos[0]["w_ids"] == 5 and infos[0]["non_w"] == 1
    assert infos[1]["docs"] == 3 and infos[1]["duplicate_ids"] == 0


def test_store_exact_vectors_and_refusals(shards):
    dirs, loc, _ = shards
    store = BaseVectorStore(dirs, loc)
    vecs, refused = store.vectors(["W10", "W20", "W11", "W12", "W13", "W14", "W21", "W77", "X99"])
    assert vecs["W10"] == {"alpha": 0.5, "gamma": 1.25, "épsilon": 0.01000213623046875}
    assert vecs["W20"] == {"##ing": 0.75}
    assert refused == {"W11": "multiple_rows", "W12": "components_not_increasing",
                       "W13": "unknown_component", "W14": "nnz_out_of_range",
                       "W21": "value_not_exact", "W77": "not_in_base_shards", "X99": "not_w_id"}


def test_reused_vector_survives_seismic_line_bit_exact(shards):
    dirs, loc, _ = shards
    vecs, _ = BaseVectorStore(dirs, loc).vectors(["W10"])
    r = _rec(10)
    r.sparse_field = vecs["W10"]
    back = json.loads(r.seismic_line())["vector"]
    stored = np.fromfile(dirs[0] / "forward_values.bin", dtype=np.float16)[:3]
    got = np.array([back[t] for t in ("alpha", "gamma", "épsilon")], dtype=np.float32).astype(np.float16)
    assert got.view(np.uint16).tolist() == stored.view(np.uint16).tolist()


def test_mapping_mismatch_refused(shards, tmp_path):
    dirs, loc, _ = shards
    p = dirs[1] / "document_mapping_strings.bin"
    p.write_bytes(p.read_bytes().replace(b"W20", b"W29"))
    vecs, refused = BaseVectorStore(dirs, loc).vectors(["W20"])
    assert vecs == {} and refused == {"W20": "mapping_mismatch"}


def test_stale_locator_rejected(shards, tmp_path):
    dirs, loc, _ = shards
    other = _write_shard(tmp_path / "x" / "global_shard0of2.mmap", [("W1", [0], [0.5])])
    with pytest.raises(ValueError):
        BaseVectorStore([other], loc)


def _seeded_ledger(tmp_path, recs_for_seed):
    led = IngestLedger(tmp_path / "ledger.sqlite")
    led.seed_base([(r.id, r.content_hash(), r.encode_hash()) for r in recs_for_seed])
    return led


def test_candidates_r1_r2(shards, tmp_path):
    base10, base20, base30 = _rec(10), _rec(20), _rec(30)
    led = _seeded_ledger(tmp_path, [base10, base20, base30])
    upd10 = _rec(10, is_oa=True)
    upd20 = _rec(20, title="retitled")
    upd30 = _rec(30, is_oa=True)
    led.stage([upd30], {"W30": True})
    upd30b = _rec(30, is_oa=False)
    unseeded = _rec(40)
    ok, why = base_reuse_candidates(led, [upd10, upd20, upd30b, unseeded])
    assert ok == ["W10"]
    assert why == {"W20": "encode_text_changed", "W30": "has_ledger_row", "W40": "not_seeded"}


def test_reuse_skips_encoder_only_for_exact_hits(shards, tmp_path):
    dirs, loc, _ = shards
    led = _seeded_ledger(tmp_path, [_rec(10), _rec(20), _rec(12)])
    todo = [_rec(10, is_oa=True), _rec(20, title="new text"), _rec(12, is_oa=True), _rec(50)]
    vecs, counts = reusable_base_sparse(led, todo, BaseVectorStore(dirs, loc))
    assert set(vecs) == {"W10"}
    assert counts == {"encode_text_changed": 1, "components_not_increasing": 1, "not_seeded": 1}
    seen = []

    def enc(texts):
        seen.extend(texts)
        return [{"zeta": 1.0} for _ in texts]

    st = ensure_sparse(todo, enc, vecs)
    assert st["reused"] == 1 and st["encoded"] == 3
    assert todo[0].sparse_field == {"alpha": 0.5, "gamma": 1.25, "épsilon": 0.01000213623046875}
    assert "title 10 abstract text 10" not in seen


def test_flag_off_returns_nothing(tmp_path):
    led = _seeded_ledger(tmp_path, [_rec(10)])
    assert reusable_base_sparse(led, [_rec(10, is_oa=True)], None) == ({}, {})


def test_cli_ingest_reuses_base_vectors(shards, tmp_path):
    dirs, loc, _ = shards
    delta = tmp_path / "delta"
    led = IngestLedger(delta / "ledger.sqlite")
    led.seed_base([(r.id, r.content_hash(), r.encode_hash()) for r in (_rec(10), _rec(20))])
    led.close()
    src = tmp_path / "in.jsonl"
    rows = [{"id": "W10", "title": "title 10", "abstract": "abstract text 10", "publication_year": 2020,
             "type": "article", "is_oa": True, "doi": "10.1/10"},
            {"id": "W20", "title": "changed", "abstract": "abstract text 20", "publication_year": 2020,
             "type": "article", "is_oa": False, "doi": "10.1/20"}]
    src.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    index_root = tmp_path / "index"
    index_root.mkdir()
    argv = ["ingest", "--index-root", str(index_root), "--delta-root", str(delta), "--source", "jsonl",
            "--path", str(src), "--namespace", "openalex", "--no-encode", "--no-seismic",
            "--base-forward-dir", str(dirs[0]), "--base-forward-dir", str(dirs[1]),
            "--base-locator-dir", str(loc)]

    class InBase:
        def __init__(self, *a, **k):
            pass

        def contains(self, ids):
            return {i: True for i in ids}

        def shard_manifest(self, explicit=None):
            return None

        def close(self):
            pass

    orig = cli.BaseIndex
    cli.BaseIndex = InBase
    try:
        out = cli.main(argv)
    finally:
        cli.BaseIndex = orig
    assert out["reused_base"] == 1
    assert out["base_refusals"] == {"encode_text_changed": 1}
    led = IngestLedger(delta / "ledger.sqlite")
    rec = json.loads(led.db.execute("SELECT record FROM records WHERE id='W10'").fetchone()[0])
    assert rec["sparse_field"] == {"alpha": 0.5, "gamma": 1.25, "épsilon": 0.01000213623046875}
    rec20 = json.loads(led.db.execute("SELECT record FROM records WHERE id='W20'").fetchone()[0])
    assert rec20["sparse_field"] is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
