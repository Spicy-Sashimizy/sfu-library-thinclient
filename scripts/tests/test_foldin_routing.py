"""Doc 10 §3 G2 — per-shard routing in the ingest ledger (tmp trees only).

`route_shard` must equal the plan01 rule that built the served shards
(`scripts/seismic_testbed/shard_spool.py` `shard_id`); new ledgers write it
at `stage()`; ledgers written by older code are never altered on open and
are only migrated by `backfill_routes()`.
"""
import json
import random
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402
from spike.delta_ingest.routing import ROUTE_SEED, ROUTE_SHARDS, route_shard  # noqa: E402

OLD_SCHEMA = """
PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS sources (name TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at REAL);
CREATE TABLE IF NOT EXISTS docs (
  id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, encode_hash TEXT NOT NULL,
  status TEXT NOT NULL, generation INTEGER NOT NULL, in_base INTEGER NOT NULL,
  section TEXT, source TEXT, first_seen REAL, last_seen REAL);
CREATE INDEX IF NOT EXISTS docs_gen ON docs(generation, status);
CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, generation INTEGER NOT NULL, record TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS records_gen ON records(generation);
CREATE TABLE IF NOT EXISTS generations (gen INTEGER PRIMARY KEY, state TEXT NOT NULL,
  created REAL, published REAL, docs INTEGER, info TEXT);
CREATE TABLE IF NOT EXISTS tombstones (id TEXT PRIMARY KEY, gen INTEGER, reason TEXT, ts REAL, in_base INTEGER);
CREATE TABLE IF NOT EXISTS history (id TEXT NOT NULL, gen INTEGER NOT NULL, PRIMARY KEY (id, gen));
CREATE TABLE IF NOT EXISTS base_hashes (id INTEGER PRIMARY KEY, ch INTEGER NOT NULL, eh INTEGER NOT NULL);
"""


def _rec(i, title=None, src="t"):
    return DocRecord(id=f"W{i}", title=title or f"paper {i}", abstract="a", year=2020,
                     source=src, sparse_field={"x": 1.0})


def _cols(path):
    db = sqlite3.connect(str(path))
    try:
        return [r[1] for r in db.execute("PRAGMA table_info(docs)")]
    finally:
        db.close()


def test_route_shard_equals_plan01_rule():
    from shard_spool import shard_id
    rng = random.Random(20261001)
    ids = [f"W{rng.randrange(1, 7_500_000_000)}" for _ in range(3000)]
    ids += ["arxiv:2401.00001", "zotero:ABCD1234", "local:x", "", "W1"]
    for i in ids:
        assert route_shard(i) == shard_id(i, "sfu-seismic-plan01", 8)
    assert ROUTE_SEED == "sfu-seismic-plan01" and ROUTE_SHARDS == 8
    counts = [0] * 8
    for i in ids:
        counts[route_shard(i)] += 1
    assert min(counts) > 0


def test_new_ledger_writes_route_at_stage_and_restage_resets_origin(tmp_path):
    led = IngestLedger(tmp_path / "ledger.sqlite")
    assert led.has_routes
    recs = [_rec(i) for i in range(1, 51)]
    led.stage(recs, {r.id: True for r in recs})
    rows = dict(led.db.execute("SELECT id, route_shard FROM docs"))
    assert rows == {r.id: route_shard(r.id) for r in recs}
    led.db.execute("UPDATE docs SET seismic_origin='fold:3:1', generation=1 WHERE id='W5'")
    led.db.commit()
    m = led.mask()
    assert m["newest_by_leg"] == {"seismic": {"W5": "fold:3:1"}}
    led.stage([_rec(5, "paper 5 v2")], {"W5": True})
    assert led.db.execute("SELECT seismic_origin, route_shard FROM docs WHERE id='W5'").fetchone() == (
        None, route_shard("W5"))
    assert "newest_by_leg" not in led.mask()
    assert led.routed_live_counts() == {s: sum(1 for r in recs if route_shard(r.id) == s)
                                       for s in {route_shard(r.id) for r in recs}}
    led.close()


def test_mask_has_no_new_key_without_folds(tmp_path):
    led = IngestLedger(tmp_path / "ledger.sqlite")
    recs = [_rec(i) for i in range(1, 11)]
    led.stage(recs, {"W1": True})
    led.delete(["W2"], {"W2": True})
    assert set(led.mask()) == {"deleted", "superseded"}
    led.close()


def _old_ledger(path: Path, n: int = 40) -> None:
    db = sqlite3.connect(str(path))
    db.executescript(OLD_SCHEMA)
    for i in range(1, n + 1):
        db.execute("INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (f"W{i}", "c", "e", "live", 1, i % 2, "s", "t", 1.0, 1.0))
    db.commit()
    db.close()


def test_old_ledger_untouched_on_open_and_stage_mask_unchanged(tmp_path):
    p = tmp_path / "ledger.sqlite"
    _old_ledger(p)
    before = _cols(p)
    led = IngestLedger(p)
    assert not led.has_routes
    assert _cols(p) == before
    led.stage([_rec(100), _rec(3, "updated")], {"W3": True})
    m = led.mask()
    assert set(m) == {"deleted", "superseded"}
    assert led.routed_live_counts() == {}
    led.close()
    assert _cols(p) == before


def test_backfill_routes_on_copy_is_idempotent(tmp_path):
    p = tmp_path / "ledger.sqlite"
    _old_ledger(p, 300)
    led = IngestLedger(p)
    out = led.backfill_routes()
    assert out["columns_added"] == ["route_shard", "seismic_origin"]
    assert out["rows_routed"] == 300 and out["rows_unrouted"] == 0
    assert led.has_routes
    rows = dict(led.db.execute("SELECT id, route_shard FROM docs"))
    assert all(v == route_shard(k) for k, v in rows.items())
    again = led.backfill_routes()
    assert again["columns_added"] == [] and again["rows_routed"] == 0
    led.stage([_rec(1000)], {})
    assert led.db.execute("SELECT route_shard FROM docs WHERE id='W1000'").fetchone()[0] == route_shard("W1000")
    led.close()


def test_backfill_cli(tmp_path, capsys):
    from spike.delta_ingest import cli
    root = tmp_path / "delta"
    root.mkdir()
    _old_ledger(root / "ledger.sqlite", 20)
    idx = tmp_path / "index"
    idx.mkdir()
    out = cli.main(["backfill-routes", "--index-root", str(idx), "--delta-root", str(root)])
    assert out["rows_routed"] == 20 and out["rows_unrouted"] == 0
    json.loads(capsys.readouterr().out)
