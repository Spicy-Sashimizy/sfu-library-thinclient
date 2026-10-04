"""O15: AbstractStore opens its SQLite read-only by construction.

docs/delta_ingest/02_DESIGN.md §3.1 O15: the store connected read-write, so a
bug or a stray statement on a reader could modify a served sidecar, and the
open itself may create journal files next to it.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from lib.thinclient.abstracts import AbstractStore  # noqa: E402
from lib.thinclient.builder import SectionBuilder, open_meta_db  # noqa: E402

SECTION = "social_sciences__recent"


@pytest.fixture
def store_path(tmp_path):
    root = tmp_path / "index"
    root.mkdir()
    meta = open_meta_db(root)
    b = SectionBuilder(root, SECTION, hot=True, meta_db=meta)
    for i in range(1, 41):
        b.add({"id": f"W{i}", "title": f"title {i}", "abstract": f"abstract number {i} " * 6,
               "publication_year": 2020, "type": "article", "is_oa": False, "doi": f"10.1/{i}"})
    b.finish()
    meta.commit()
    meta.close()
    p = root / "sections" / SECTION / "abstracts.sqlite"
    assert p.exists()
    return p


def test_store_connection_rejects_writes(store_path):
    s = AbstractStore(store_path)
    assert s.fetch(["W3"])["W3"].startswith("abstract number 3")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        s._db.execute("CREATE TABLE stray (a)")


def test_open_and_fetch_leave_file_and_dir_untouched(store_path):
    before = {p.name: p.stat().st_mtime_ns for p in store_path.parent.iterdir()}
    raw = store_path.read_bytes()
    s = AbstractStore(store_path)
    s.fetch([f"W{i}" for i in range(1, 41)])
    after = {p.name: p.stat().st_mtime_ns for p in store_path.parent.iterdir()}
    assert after == before
    assert store_path.read_bytes() == raw


def test_path_with_uri_special_characters(tmp_path, store_path):
    odd = tmp_path / "we?ird #dir%20" / "abstracts.sqlite"
    odd.parent.mkdir()
    odd.write_bytes(store_path.read_bytes())
    flat = store_path.with_suffix(".sqlite.flat")
    if flat.exists():
        pytest.skip("flat sidecar present; covered by the plain-path tests")
    s = AbstractStore(odd)
    assert s.fetch(["W7"])["W7"].startswith("abstract number 7")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
