"""Delta-ingest 09 levers L1 (compaction cadence) and L2 (generation layout).

All on synthetic tmp roots: no served index, no GPU, no SEISMIC toolchain
(the SEISMIC reuse path is exercised with a fake shard dir)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

from lib.thinclient.builder import SectionBuilder, open_meta_db  # noqa: E402
from lib.thinclient.retriever import ThinClientRetriever, _era_skip  # noqa: E402
from spike.delta_ingest import cli  # noqa: E402
from spike.delta_ingest.generation import auto_compact_plan, build_generation  # noqa: E402
from spike.delta_ingest.profiles import PROFILES  # noqa: E402
from spike.delta_ingest.records import LAYOUTS, DocRecord  # noqa: E402


def _rec(i: int, year: int, title: str, sparse: bool = True) -> DocRecord:
    return DocRecord(id=f"local:D{i}", title=title, abstract=f"{title} abstract number {i}", year=year,
                     type="article", source="t", sparse_field={"widgets": 1.0, f"t{i}": 0.5} if sparse else None)


RECS = [
    _rec(1, 2024, "quantum widgets physics"),
    _rec(2, 2004, "quantum widgets physics"),
    _rec(3, 2023, "election politics widgets"),
    _rec(4, 2001, "protein cell biology widgets"),
    _rec(5, 2025, "neural network algorithm widgets"),
]


@pytest.fixture
def base_root(tmp_path):
    root = tmp_path / "index"
    root.mkdir()
    meta = open_meta_db(root)
    b = SectionBuilder(root, "social_sciences__recent", hot=True, meta_db=meta)
    for i in range(1, 30):
        b.add({"id": f"W{i}", "title": f"politics paper {i}", "abstract": f"policy study {i}",
               "publication_year": 2015 + i % 5, "type": "article", "is_oa": False, "doi": ""})
    b.finish()
    meta.commit()
    meta.close()
    (root / "manifest.json").write_text(json.dumps({"sections": {}, "persona": "all_hot"}))
    return root


def test_section_names_per_layout():
    r_new, r_old = RECS[0], RECS[1]
    assert r_new.section() == r_new.section("per_base_section")
    assert r_new.section().endswith("__recent") and r_old.section().endswith("__archive")
    assert r_new.section("per_era") == "delta__recent"
    assert r_old.section("per_era") == "delta__archive"
    assert r_new.section("single") == r_old.section("single") == "delta"
    assert DocRecord(id="local:x", year=None).section("per_era") == "delta__archive"
    with pytest.raises(ValueError):
        r_new.section("bogus")
    assert set(LAYOUTS) == {"per_base_section", "per_era", "single"}


@pytest.mark.parametrize("layout,expected", [
    (None, None),
    ("per_base_section", None),
    ("per_era", ["delta__archive", "delta__recent"]),
    ("single", ["delta"]),
])
def test_build_generation_layout(tmp_path, layout, expected):
    prof = PROFILES["laptop"]
    g = build_generation(tmp_path, 1, RECS, prof, seismic=False, layout=layout)
    gi = json.loads((g / "generation.json").read_text())
    sections = sorted(gi["sections"])
    if expected is None:
        expected = sorted({r.section() for r in RECS})
        assert len(expected) >= 4
    assert sections == expected
    assert sorted(p.name for p in (g / "sections").iterdir()) == expected
    assert gi["layout"] == (layout or "per_base_section")
    con = sqlite3.connect(g / "meta.sqlite")
    tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    meta_sections = set()
    for t in tables:
        cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
        if "section" in cols:
            meta_sections |= {s for (s,) in con.execute(f"SELECT section FROM {t}")}
    con.close()
    assert meta_sections == set(expected)


def test_profile_layout_is_the_default_and_param_overrides(tmp_path):
    prof = PROFILES["laptop"].with_overrides(layout="single")
    g1 = build_generation(tmp_path, 1, RECS, prof, seismic=False)
    assert sorted(json.loads((g1 / "generation.json").read_text())["sections"]) == ["delta"]
    g2 = build_generation(tmp_path, 2, RECS, prof, seismic=False, layout="per_era")
    assert sorted(json.loads((g2 / "generation.json").read_text())["sections"]) == ["delta__archive",
                                                                                    "delta__recent"]
    assert PROFILES["desktop_gpu"].layout == "per_base_section"
    assert PROFILES["desktop_gpu"].max_live_gens == 8
    assert PROFILES["desktop_gpu"].compact_policy == "tiered"


def test_era_skip_on_new_section_names():
    recent_only = {"year_range": (2021, 2026)}
    archive_only = {"year_range": (1990, 2005)}
    both = {"year_range": (2005, 2026)}
    assert _era_skip("delta_g0001:delta__archive", recent_only)
    assert not _era_skip("delta_g0001:delta__recent", recent_only)
    assert _era_skip("delta_g0001:delta__recent", archive_only)
    assert not _era_skip("delta_g0001:delta__archive", archive_only)
    assert not _era_skip("delta_g0001:delta__archive", both)
    for f in (recent_only, archive_only, both, None):
        assert not _era_skip("delta_g0001:delta", f)


class _StubLedger:
    def __init__(self, gens):
        self.gens = gens

    def published_generations(self):
        return list(self.gens)


def _gen_json(root: Path, gens_docs: dict):
    for g, docs in gens_docs.items():
        d = root / f"g{g:04d}"
        d.mkdir()
        (d / "generation.json").write_text(json.dumps({"docs": docs}))


def test_auto_compact_plan_compact_all(tmp_path):
    _gen_json(tmp_path, {1: 1000, 2: 10, 3: 10, 4: 10, 5: 10})
    led = _StubLedger([1, 2, 3, 4, 5])
    assert auto_compact_plan(tmp_path, led, max_gens=5, policy="compact_all") == []
    assert auto_compact_plan(tmp_path, led, max_gens=4, policy="compact_all") == [1, 2, 3, 4, 5]
    assert auto_compact_plan(tmp_path, led, max_gens=1, policy="compact_all") == [1, 2, 3, 4, 5]
    assert auto_compact_plan(tmp_path, led, max_gens=4) == [2, 3, 4, 5]
    assert auto_compact_plan(tmp_path, _StubLedger([1]), max_gens=1, policy="compact_all") == []
    assert auto_compact_plan(tmp_path, _StubLedger([1, 2]), max_gens=1, policy="compact_all") == [1, 2]
    with pytest.raises(ValueError):
        auto_compact_plan(tmp_path, led, policy="nope")
    with pytest.raises(ValueError):
        auto_compact_plan(tmp_path, led, max_gens=0, policy="compact_all")


def _jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _flush(root, *extra):
    cli.main(["flush", "--force", "--index-root", str(root), "--profile", "laptop", "--no-seismic", *extra])


def test_cli_cadence_compact_all_gmax1_single_layout(base_root, tmp_path, monkeypatch, capsys):
    dials = ["--layout", "single", "--compact-policy", "compact_all", "--max-live-gens", "1"]
    for k, year in ((0, 2024), (1, 2005), (2, 2025)):
        rows = [{"id": f"K{k}_{i}", "title": f"widgets batch{k} {i}", "abstract": f"gizmo text {k} {i}",
                 "year": year, "type": "article"} for i in range(6)]
        cli.main(["ingest", "--source", "jsonl", "--path", str(_jsonl(tmp_path / f"b{k}.jsonl", rows)),
                  "--index-root", str(base_root), "--profile", "laptop", "--rate", "0", "--no-encode",
                  "--no-seismic", "--namespace", "local", "--min-year", "1900", *dials])
        capsys.readouterr()
        _flush(base_root, *dials)
        out = json.loads(capsys.readouterr().out)
        gens = json.loads((base_root / "delta" / "generations.json").read_text())["generations"]
        assert len(gens) == 1
        assert gens[0]["sections"] == ["delta"]
        if k == 0:
            assert out["auto_compact"] is None
        else:
            assert out["auto_compact"]["compacted"] == sorted(out["auto_compact"]["compacted"])
            assert len(out["auto_compact"]["compacted"]) == 2
        assert gens[0]["docs"] == 6 * (k + 1)

    monkeypatch.setenv("SFU_DELTA_ROOT", "1")
    monkeypatch.delenv("SFU_SEISMIC_SHARD_MANIFEST", raising=False)
    tc = ThinClientRetriever(index_root=str(base_root), remote_abstracts=False)
    tc._load()
    ids = [h["openalex_id"] for h in tc.search("widgets", top_k=50, mode="bm25f")]
    assert len([i for i in ids if i.startswith("local:K")]) == 18
    ids_recent = [h["openalex_id"] for h in tc.search("widgets", top_k=50, mode="bm25f",
                                                      filters={"from_publication_date": "2020-01-01"})]
    assert {i.split("_")[0] for i in ids_recent if i.startswith("local:K")} == {"local:K0", "local:K2"}
    assert tc.fetch_abstracts(["local:K1_3"])["local:K1_3"] == "gizmo text 1 3"


def test_cli_default_policy_never_compacts_on_flush(base_root, tmp_path, capsys):
    for k in range(3):
        rows = [{"id": f"P{k}_{i}", "title": f"widgets {k} {i}", "abstract": "x y z", "year": 2024}
                for i in range(3)]
        cli.main(["ingest", "--source", "jsonl", "--path", str(_jsonl(tmp_path / f"p{k}.jsonl", rows)),
                  "--index-root", str(base_root), "--profile", "laptop", "--rate", "0", "--no-encode",
                  "--no-seismic", "--namespace", "local"])
        capsys.readouterr()
        _flush(base_root, "--max-live-gens", "1")
        out = json.loads(capsys.readouterr().out)
        assert out["auto_compact"] is None
    gens = json.loads((base_root / "delta" / "generations.json").read_text())["generations"]
    assert len(gens) == 3
    assert all(not s.startswith("delta") for g in gens for s in g["sections"])


def _fake_seismic_gen(root: Path, records: list[DocRecord]) -> Path:
    d = root / "src_g0001"
    sdir = d / "seismic"
    (sdir / "delta_g0001.dotvbyte.v2.mmap").mkdir(parents=True)
    (sdir / "delta_g0001.dotvbyte.v2.mmap" / "forward.bin").write_bytes(b"\x01\x02\x03")
    (sdir / "delta_g0001.index.seismic").write_bytes(b"stock")
    with open(sdir / "delta_g0001.jsonl", "w") as fh:
        for r in reversed(records):
            if r.seismic_line():
                fh.write(r.seismic_line() + "\n")
    (d / "generation.json").write_text(json.dumps({"seismic": {
        "jsonl": "/abs/g0001.building/seismic/delta_g0001.jsonl",
        "stock": "/abs/g0001.building/seismic/delta_g0001.index.seismic",
        "mmap_dir": "seismic/delta_g0001.dotvbyte.v2.mmap", "format": "dotvbyte_fixedu8_v2",
        "stages": {"build": {"docs": 4}}, "status": "served"}}))
    return d


def test_seismic_reuse_copies_identical_shard(tmp_path):
    recs = RECS[:4] + [_rec(9, 2020, "no vector widgets", sparse=False)]
    src = _fake_seismic_gen(tmp_path, recs)
    out = tmp_path / "root"
    out.mkdir()
    g = build_generation(out, 1, recs, PROFILES["laptop"], layout="single", seismic_from=src)
    gi = json.loads((g / "generation.json").read_text())
    assert gi["docs"] == 5 and gi["docs_with_vectors"] == 4
    assert gi["seismic"]["status"] == "served"
    assert gi["seismic"]["mmap_dir"] == "seismic/delta_g0001.dotvbyte.v2.mmap"
    assert gi["seismic"]["format"] == "dotvbyte_fixedu8_v2"
    assert gi["seismic"]["reused_from"] == str(src)
    assert gi["seismic"]["jsonl"] == "seismic/delta_g0001.jsonl"
    assert (g / gi["seismic"]["mmap_dir"] / "forward.bin").read_bytes() == b"\x01\x02\x03"
    assert sorted(gi["sections"]) == ["delta"]


def test_seismic_reuse_refuses_different_doc_set(tmp_path):
    src = _fake_seismic_gen(tmp_path, RECS[:4])
    out = tmp_path / "root"
    out.mkdir()
    with pytest.raises(ValueError, match="doc-id set differs"):
        build_generation(out, 1, RECS, PROFILES["laptop"], layout="single", seismic_from=src)
    assert not (out / "g0001").exists()
