"""Fold-in F0 harness (doc 10 §6 F0): corpus selection, snapshot-line
prefilter, vector attachment, arm resolution and the F0 bar — on tmp trees
and synthetic arrays only (no index, no lock)."""
import gzip
import importlib.util
import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("f0h", REPO / "scripts/experiments/eval_delta_ingest_foldin_f0.py")
f0h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f0h)

from spike.delta_ingest.base_vectors import BaseVectorStore, build_locator  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402

TOKENS = ["alpha", "beta", "gamma"]


def _write_shard(d: Path, docs):
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


def test_scan_lines_takes_the_work_id_not_nested_refs():
    lines = [
        b'{"id": "https://openalex.org/W5", "referenced_works": ["https://openalex.org/W7"]}\n',
        b'{"id":"https://openalex.org/W7","title":"x"}\n',
        b'{"id": "https://openalex.org/W9"}\n',
        b'{"title": "no id"}\n',
    ]
    got = list(f0h.scan_lines(lines, {5, 7}))
    assert [w for w, _ in got] == [5, 7]


def test_u_targets_keeps_in_base_and_in_slice(tmp_path):
    p = tmp_path / "updated_date=2026-07-01_part_0001.npz"
    np.savez(p, num=np.array([1, 2, 3, 4]), rows=np.array([-1, 10, 11, 12]),
             in_slice=np.array([True, True, False, True]))
    tg = f0h.u_targets([p])
    assert tg[p.stem].tolist() == [2, 4]


def test_part_files_skip_route_npz(tmp_path):
    d = tmp_path / "partsout_f10"
    d.mkdir()
    for n in ("b.npz", "a.npz", "a.route.npz"):
        np.savez(d / n, x=np.array([0]))
    assert [p.name for p in f0h.part_files(tmp_path)] == ["a.npz", "b.npz"]


def test_fill_order_filters_and_is_seeded():
    twin = np.array([3, 5, 8, 13, 21, 34, 55], dtype=np.int64)
    ord_wids = np.array([1, 3, 5, 8, 13, 21, 34], dtype=np.int64)
    ord_sec = np.array([0, 1, 1, 0, 1, 1, 1], dtype=np.int8)
    side = np.array([3, 5, 13, 21, 55], dtype=np.int64)
    exclude = np.array([13], dtype=np.int64)
    o1, st = f0h.fill_order(twin, ord_wids, ord_sec, 1, side, exclude, seed=7)
    o2, _ = f0h.fill_order(twin, ord_wids, ord_sec, 1, side, exclude, seed=7)
    assert sorted(o1.tolist()) == [3, 5, 21]
    assert o1.tolist() == o2.tolist()
    assert st["not_in_ordinals"] == 1 and st["excluded_as_U"] == 1 and st["candidates"] == 3


def test_lookup_sorted_exact_only():
    pos, found = f0h.lookup_sorted(np.array([2, 4, 9]), np.array([1, 2, 3, 9]))
    assert found.tolist() == [True, False, True]


def test_attach_vectors_exact_or_refuse(tmp_path):
    s = _write_shard(tmp_path / "global_shard0of8.mmap", [
        ("W10", [0, 2], [0.5, 1.25]), ("W11", [], []), ("W12", [1], [0.75])])
    build_locator(s, tmp_path / "loc" / f"{s.name}.locator", chunk=2)
    store = BaseVectorStore([s], tmp_path / "loc")
    recs = [DocRecord(id=f"W{i}", title="t", abstract="a") for i in (10, 11, 12, 99)]
    refused = {}
    kept = f0h.attach_vectors(store, recs, refused)
    store.close()
    assert [r.id for r in kept] == ["W10", "W12"]
    assert kept[0].sparse_field == {"alpha": 0.5, "gamma": 1.25}
    assert refused == {"nnz_out_of_range": 1, "not_in_base_shards": 1}


def test_load_u_records_newest_part_wins(tmp_path):
    d = tmp_path / "upd"
    d.mkdir()
    (d / "updated_date=2026-07-01_part_0001.jsonl").write_text(DocRecord(id="W1", title="old").to_json() + "\n")
    (d / "updated_date=2026-08-01_part_0001.jsonl").write_text(DocRecord(id="W1", title="new").to_json() + "\n")
    assert f0h.load_u_records(d)["W1"].title == "new"


def test_extract_one_writes_normalised_records(tmp_path):
    work = {"id": "https://openalex.org/W5", "title": "T", "publication_year": 2020, "type": "article",
            "abstract_inverted_index": {f"word{i}": [i] for i in range(20)},
            "doi": "https://doi.org/10.1/X"}
    short = {"id": "https://openalex.org/W6", "title": "T", "abstract_inverted_index": {"a": [0]}}
    gz = tmp_path / "p.gz"
    with gzip.open(gz, "wt") as fh:
        for w in (work, short, {"id": "https://openalex.org/W7"}):
            fh.write(json.dumps(w) + "\n")
    out = tmp_path / "p.jsonl"
    c = f0h._extract_one((str(gz), str(out), np.array([5, 6])))
    assert c["matched"] == 2 and c["written"] == 1 and c["not_in_slice"] == 1
    r = DocRecord.from_json(out.read_text().strip())
    assert r.id == "W5" and r.doi == "10.1/x" and r.year == 2020
    assert f0h._extract_one((str(gz), str(out), np.array([5]))).get("skipped_done")


def test_resolver_maps_g1m_and_delegates(tmp_path):
    calls = []

    def orig(name, layout="per_base_section", x_levers=()):
        calls.append(name)
        return {"name": name}
    res = f0h.make_resolver(orig, tmp_path / "root_g1M")
    a = res("xg1M", "per_base_section", ("L3", "L4", "L5"))
    assert a == {"name": "xg1M", "tag": "g1M", "root": str(tmp_path / "root_g1M"), "n_gen": 1,
                 "levers": ["L3", "L4", "L5"]}
    assert res("g1M+L4")["levers"] == ["L4"]
    assert res("x1")["name"] == "x1" and calls == ["x1"]


def _units(diff_ms: float, n_topics: int = 30):
    u = {}
    for p in (1, 2):
        for t in range(n_topics):
            base = 2000.0 + t
            u[(p, f"t{t}")] = {"n0x": base, "x1": base + 1.0, "xg1M": base + 1.0 + diff_ms + (t % 3) * 0.1}
    return u


@pytest.fixture(scope="module")
def m4f():
    return f0h._m4f()


def test_f0_bar_pass_fail_and_coefficient(m4f):
    ok = f0h.f0_bar(_units(3.0), m4f.paired_diff, True, True)
    assert ok["verdict"] == "PASS"
    assert ok["coefficient_c"]["median_ms_per_M_docs"] == pytest.approx(3.1 / 0.839653, rel=1e-3)
    bad = f0h.f0_bar(_units(9.0), m4f.paired_diff, True, True)
    assert bad["verdict"] == "FAIL"
    nr = f0h.f0_bar(_units(3.0), m4f.paired_diff, True, False)
    assert nr["verdict"].startswith("NOT READ")
