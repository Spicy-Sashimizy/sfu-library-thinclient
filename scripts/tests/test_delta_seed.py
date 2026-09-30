"""Base-hash seed for the ingest ledger (issue O4) + DOI normalisation (O5) +
snapshot min_year default (O6). Synthetic base built with SectionBuilder."""
import gzip
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from lib.thinclient.builder import SectionBuilder, open_meta_db  # noqa: E402
from spike.delta_ingest import cli  # noqa: E402
from spike.delta_ingest.adapters import OpenAlexSnapshotAdapter  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger, hash64  # noqa: E402
from spike.delta_ingest.records import (  # noqa: E402
    BASE_MIN_YEAR, normalize_doi, normalize_generic, normalize_openalex_work)
from spike.delta_ingest.seed import BaseSeeder, base_record  # noqa: E402

N = 40


def _doc(i):
    return {"id": f"W{i}", "title": f"politics paper {i}",
            "abstract": f"policy study number {i} about elections and parliaments",
            "publication_year": 2012 + i % 5, "type": "article", "is_oa": i % 2 == 0,
            "doi": f"https://doi.org/10.1/ABC{i}"}


def _work(i, **over):
    d = _doc(i)
    w = {"id": f"https://openalex.org/W{i}", "title": d["title"], "abstract": d["abstract"],
         "publication_year": d["publication_year"], "type": d["type"],
         "open_access": {"is_oa": d["is_oa"]}, "doi": f"https://doi.org/10.1/abc{i}",
         "updated_date": "2026-09-15", "cited_by_count": 99}
    w.update(over)
    return w


@pytest.fixture
def base_root(tmp_path):
    root = tmp_path / "index"
    root.mkdir()
    meta = open_meta_db(root)
    b = SectionBuilder(root, "social_sciences__recent", hot=True, meta_db=meta)
    for i in range(1, N + 1):
        b.add(_doc(i))
    b.finish()
    meta.commit()
    meta.close()
    return root


def test_seeded_base_doc_unchanged_or_updated(base_root, tmp_path):
    led = IngestLedger(tmp_path / "d" / "ledger.sqlite")
    s = BaseSeeder(base_root, led)
    rep = s.seed_ids([f"W{i}" for i in range(1, N + 1)])
    assert rep["stats"]["seeded"] == N
    recs = [normalize_openalex_work(_work(1)),
            normalize_openalex_work(_work(2, title="politics paper 2 revised")),
            normalize_openalex_work(_work(3, open_access={"is_oa": True})),
            normalize_openalex_work(_work(4, doi="doi.org/10.1/ABC4"))]
    in_base = BaseIndex(base_root).contains(r.id for r in recs)
    assert all(in_base.values())
    cls = led.classify(recs, in_base)
    assert sorted(r.id for r in cls["unchanged"]) == ["W1", "W4"]
    assert sorted(r.id for r in cls["updated"]) == ["W2", "W3"]
    bk = led.base_known(["W2", "W3"])
    w2, w3 = recs[1], recs[2]
    assert bk["W2"][1] != hash64(w2.encode_hash())
    assert bk["W3"][1] == hash64(w3.encode_hash()) and bk["W3"][0] != hash64(w3.content_hash())
    assert led.mask() == {"deleted": [], "superseded": {}}
    assert led.buffer_count() == 0 and led.stats()["docs_live"] == 0


def test_unseeded_in_base_stays_updated_and_docs_row_wins(base_root, tmp_path):
    led = IngestLedger(tmp_path / "d" / "ledger.sqlite")
    r1 = normalize_openalex_work(_work(1))
    assert led.classify([r1], {"W1": True})["updated"] == [r1]
    BaseSeeder(base_root, led).seed_ids(["W1"])
    assert led.classify([r1], {"W1": True})["unchanged"] == [r1]
    r1b = normalize_openalex_work(_work(1, title="changed"))
    led.stage([r1b], {"W1": True})
    assert led.classify([r1], {"W1": True})["updated"] == [r1]
    assert led.classify([r1b], {"W1": True})["unchanged"] == [r1b]


def test_seed_range_resumes_and_counts_missing_sidecar(base_root, tmp_path):
    led = IngestLedger(tmp_path / "d" / "ledger.sqlite")
    s = BaseSeeder(base_root, led, batch=7)
    a = s.seed_range(0, 10**12, limit=14)
    assert a["stats"]["meta_rows"] == 14 and not a["done"]
    b = s.seed_range(0, 10**12)
    assert b["done"] and a["stats"]["seeded"] + b["stats"]["seeded"] == N
    assert led.db.execute("SELECT COUNT(*) FROM base_hashes").fetchone()[0] == N
    s2 = BaseSeeder(base_root, IngestLedger(tmp_path / "e" / "ledger.sqlite"),
                    sidecar_roots=[tmp_path / "nowhere"])
    c = s2.seed_range(0, 10**12)
    assert c["stats"].get("seeded", 0) == 0
    assert c["skipped_by_section"] == {"social_sciences__recent": N}


def test_cli_seed_base(base_root, tmp_path, capsys):
    ids = tmp_path / "ids.txt"
    ids.write_text("W1\nW2\n")
    droot = tmp_path / "droot"
    cli.main(["seed-base", "--index-root", str(base_root), "--delta-root", str(droot),
              "--seed-ids-file", str(ids), "--profile", "laptop"])
    out = json.loads(capsys.readouterr().out)
    assert out["stats"]["seeded"] == 2
    assert not (base_root / "delta").exists()


def test_doi_prefix_variants_hash_equal():
    variants = ["https://doi.org/10.1/AbC", "http://doi.org/10.1/abc", "doi.org/10.1/abc",
                "https://dx.doi.org/10.1/ABC", "doi:10.1/abc", "10.1/ABC", " 10.1/abc "]
    assert {normalize_doi(v) for v in variants} == {"10.1/abc"}
    hashes = {normalize_openalex_work(_work(1, doi=v)).content_hash() for v in variants}
    assert len(hashes) == 1
    g = normalize_generic({"id": "x", "title": "t", "doi": "https://doi.org/10.1/X"},
                          namespace="local", source="t")
    assert g.doi == "10.1/x"
    b = base_record("W1", "t", "https://doi.org/10.1/ABC", 2020, "article", 1, "a")
    assert b.doi == "10.1/abc" and base_record("W1", "t", "", 0, "", 0, "a").year is None


def test_min_year_default_is_base_boundary(tmp_path):
    assert BASE_MIN_YEAR == 2010
    assert OpenAlexSnapshotAdapter(None).min_year == 2010
    works = [_work(1, publication_year=2009), _work(2, publication_year=2010),
             _work(3, publication_year=2014), _work(4, publication_year=None)]
    part = tmp_path / "p.gz"
    part.write_bytes(gzip.compress("\n".join(json.dumps(w) for w in works).encode()))
    url = "s3://openalex/data/jsonl/works/updated_date=2026-09-15/part_0001.gz"

    class _R:
        def __init__(self, c):
            self.content = c

        def raise_for_status(self):
            return None

    class _S:
        def get(self, u, timeout=None, **kw):
            if u.endswith("manifest.json"):
                return _R(json.dumps({"entries": [{"url": url}]}).encode())
            return _R(part.read_bytes())

    got = [r.id for r in OpenAlexSnapshotAdapter(_S()).iter_records({})]
    assert got == ["W2", "W3", "W4"]
    got15 = [r.id for r in OpenAlexSnapshotAdapter(_S(), min_year=2015).iter_records({})]
    assert got15 == ["W4"]
    got_none = [r.id for r in OpenAlexSnapshotAdapter(_S(), min_year=None).iter_records({})]
    assert got_none == ["W1", "W2", "W3", "W4"]
