"""Doc 10 §1 — fold-in trigger bookkeeping (`spike/delta_ingest/trigger.py`).

(a), (d), (c) per base shard at `publish()`, the threshold dials (unset = OFF),
the 24 h hysteresis after a fold publish, the post-fold readings, and the
livedocs (d) against a direct decode of the published bitset. Tmp trees only;
no index, no model.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "tests"))

from lib.thinclient.livedocs import HEADER_LEN  # noqa: E402
from spike.delta_ingest import trigger  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.foldin import FOLD_SCHEMA  # noqa: E402
from spike.delta_ingest.generation import publish  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger, backfill_routes  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402
from spike.delta_ingest.routing import route_shard  # noqa: E402
from test_delta_livedocs import make_ordinals  # noqa: E402

N_BASE_IDS = 2000
SHARD_DOCS = [1000 + 10 * s for s in range(8)]
OFF = {}


@pytest.fixture
def env_off(monkeypatch):
    for k in (trigger.ENV_FRAC, trigger.ENV_DEAD_FRAC, trigger.ENV_MAX_AGE, "SFU_THINCLIENT_ORDINALS"):
        monkeypatch.delenv(k, raising=False)


def _manifest(tmp_path) -> Path:
    p = tmp_path / "base_manifest.json"
    p.write_text(json.dumps({"shards": [{"shard": s, "mmap_dir": f"m{s}", "n_docs": n}
                                        for s, n in enumerate(SHARD_DOCS)]}))
    return p


def _root(tmp_path):
    d = tmp_path / "delta"
    d.mkdir()
    led = IngestLedger(d / "ledger.sqlite")
    base = BaseIndex(tmp_path / "noindex")
    return d, led, base


def _stage(led, ids, in_base, t=None):
    recs = [DocRecord(id=i, title=f"t {i}", abstract="a") for i in ids]
    led.stage(recs, {i: in_base for i in ids})
    if t is not None:
        marks = ",".join("?" * len(ids))
        led.db.execute(f"UPDATE docs SET last_seen=?, first_seen=MIN(first_seen, ?) WHERE id IN ({marks})", [t, t, *ids])
        led.db.commit()


def _by_shard(ids):
    out = {}
    for i in ids:
        out.setdefault(route_shard(i), set()).add(i)
    return out


def _scenario(led):
    base_upd = [f"W{i}" for i in range(1, 61)]
    base_del = [f"W{i}" for i in range(100, 131)]
    new = [f"W{i}" for i in range(5001, 5081)]
    delta_del = new[:10]
    _stage(led, base_upd, True, t=1_000.0)
    _stage(led, new, False, t=2_000.0)
    led.delete(base_del, {i: True for i in base_del})
    led.delete(delta_del, {i: False for i in delta_del})
    return base_upd, base_del, new, delta_del


def test_counts_without_ordinals(tmp_path, env_off):
    d, led, base = _root(tmp_path)
    base_upd, base_del, new, delta_del = _scenario(led)
    out = publish(d, led, base, str(_manifest(tmp_path)))
    rec = json.loads((d / trigger.TRIGGER_FILE).read_text())
    assert out["trigger"]["shards"] == rec["shards"]
    assert rec["d_source"] == "ledger" and rec["enabled"] is False and rec["fire"] == []
    live = _by_shard(base_upd + new[10:])
    dead = _by_shard(base_upd + base_del)
    for row in rec["shards"]:
        s = row["shard"]
        assert row["base_docs"] == SHARD_DOCS[s]
        assert row["live_routed"] == len(live.get(s, ()))
        assert row["masked_routed"] == len(dead.get(s, ()))
        assert row["frac"] == pytest.approx(len(live.get(s, ())) / SHARD_DOCS[s])
        assert row["dead_frac"] == pytest.approx(len(dead.get(s, ())) / SHARD_DOCS[s])
        want_t = 1_000.0 if any(i in live.get(s, ()) for i in base_upd) else (2_000.0 if live.get(s) else None)
        assert row["oldest_staged_at"] == want_t
        assert row["tax_ms"] is None and row["fires"] == []
    assert "NOT IMPLEMENTED" in rec["tax_hook"]
    assert "trigger" not in json.loads((d / "generations.json").read_text())
    assert len((d / trigger.TRIGGER_LOG).read_text().splitlines()) == 1


def test_livedocs_reading_matches_bitset_decode(tmp_path, env_off):
    d, led, base = _root(tmp_path)
    ordd = make_ordinals(tmp_path / "ords", list(range(1, N_BASE_IDS + 1)))
    base_upd, base_del, new, _ = _scenario(led)
    led.delete(["W7777777"], {"W7777777": True})
    publish(d, led, base, str(_manifest(tmp_path)), str(ordd))
    gj = json.loads((d / "generations.json").read_text())
    rec = json.loads((d / trigger.TRIGGER_FILE).read_text())
    assert rec["d_source"] == "livedocs"
    raw = (d / gj["livedocs"]["path"]).read_bytes()[HEADER_LEN:]
    nbits = gj["livedocs"]["nbits"]
    set_ords = np.flatnonzero(np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder="little")[:nbits])
    wids = np.load(ordd / "wids.npy")
    brute = {}
    for o in set_ords:
        s = route_shard(f"W{int(wids[o])}")
        brute[s] = brute.get(s, 0) + 1
    assert sum(brute.values()) == len(base_upd) + len(base_del)
    for row in rec["shards"]:
        assert row["masked_routed"] == brute.get(row["shard"], 0)


def test_thresholds_fire_and_unset_is_off(tmp_path, env_off, monkeypatch):
    d, led, base = _root(tmp_path)
    _scenario(led)
    recs = publish(d, led, base, str(_manifest(tmp_path)))["trigger"]["shards"]
    assert all(r["fires"] == [] for r in recs)
    top = max(recs, key=lambda r: r["frac"])
    monkeypatch.setenv(trigger.ENV_FRAC, str(top["frac"]))
    monkeypatch.setenv(trigger.ENV_DEAD_FRAC, "")
    monkeypatch.setenv(trigger.ENV_MAX_AGE, "1")
    rec = publish(d, led, base, str(_manifest(tmp_path)))["trigger"]
    assert rec["enabled"] and rec["thresholds"]["dead_frac"] is None
    for r in rec["shards"]:
        want = (["frac"] if r["frac"] >= top["frac"] else []) + (["max_age"] if r["live_routed"] else [])
        assert r["fires"] == want
    assert top["shard"] in rec["fire"]


def _publish_fold_row(led, shard, fold, snapshot, published, members=()):
    led.db.executescript(FOLD_SCHEMA)
    with led.db:
        led.db.execute("INSERT INTO folds VALUES (?,?,?,?,?,?,?,?,?)",
                       (shard, fold, "published", snapshot, snapshot, published, "/x", None, "{}"))
        led.db.executemany("INSERT INTO fold_members VALUES (?,?,?,?)",
                           [(shard, fold, i, t) for i, t in members])


def test_hysteresis_24h(tmp_path, env_off, monkeypatch):
    d, led, base = _root(tmp_path)
    _scenario(led)
    monkeypatch.setenv(trigger.ENV_FRAC, "0.0")
    now = time.time()
    _publish_fold_row(led, 0, 1, now - 7200, now - 3600)
    _publish_fold_row(led, 1, 1, now - 26 * 3600, now - 25 * 3600)
    rec = trigger.compute(led, BaseIndex.shard_records(_manifest(tmp_path)), now=now)
    by = {r["shard"]: r for r in rec["shards"]}
    assert by[0]["in_hysteresis"] and by[0]["fires"] == []
    assert by[0]["hysteresis_until"] == pytest.approx(now - 3600 + 86400)
    assert not by[1]["in_hysteresis"] and by[1]["fires"] == ["frac"]
    assert by[2]["last_fold"] is None and by[2]["fires"] == ["frac"]
    rec2 = trigger.compute(led, BaseIndex.shard_records(_manifest(tmp_path)), now=now - 3600 + 86400 + 1)
    assert {r["shard"]: r for r in rec2["shards"]}[0]["fires"] == ["frac"]


def test_post_fold_readings(tmp_path, env_off):
    d, led, base = _root(tmp_path)
    s = 3
    pick = [i for i in (f"W{n}" for n in range(1, 4000)) if route_shard(i) == s]
    folded, before_unchanged, after_restaged, after_new, tomb_member, tomb_unknown, tomb_old = (
        pick[0:5], pick[5:9], pick[9:12], pick[12:14], pick[14:16], pick[16:18], pick[18:20])
    T = 10_000.0
    _stage(led, folded + after_restaged, True, t=5_000.0)
    _stage(led, before_unchanged, True, t=6_000.0)
    _stage(led, tomb_member, True, t=5_000.0)
    led.delete(tomb_old, {i: True for i in tomb_old})
    led.db.execute(f"UPDATE tombstones SET ts=? WHERE id IN ({','.join('?' * len(tomb_old))})",
                   [4_000.0, *tomb_old])
    members = [(i, 5_000.0) for i in folded + after_restaged + tomb_member]
    _publish_fold_row(led, s, 1, T, T + 1, members)
    with led.db:
        led.db.execute(f"UPDATE docs SET seismic_origin='fold:3:1' WHERE id IN ({','.join('?' * 5)})", folded)
    _stage(led, after_restaged, True, t=T + 50)
    _stage(led, after_new, True, t=T + 60)
    led.delete(tomb_member + tomb_unknown, {i: True for i in tomb_member + tomb_unknown})
    rec = trigger.compute(led, BaseIndex.shard_records(_manifest(tmp_path)), now=T + 100)
    row = rec["shards"][s]
    assert row["live_routed"] == len(before_unchanged + after_restaged + after_new)
    assert row["oldest_staged_at"] == 6_000.0
    assert row["masked_routed"] == len(after_restaged + after_new + tomb_member + tomb_unknown)
    assert row["last_fold"]["fold"] == 1


def test_old_ledger_without_routes_is_skipped(tmp_path, env_off):
    p = tmp_path / "old.sqlite"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE docs (id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, encode_hash TEXT NOT NULL, "
               "status TEXT NOT NULL, generation INTEGER NOT NULL, in_base INTEGER NOT NULL, section TEXT, "
               "source TEXT, first_seen REAL, last_seen REAL)")
    db.commit()
    db.close()
    led = IngestLedger(p)
    assert not led.has_routes
    rec = trigger.compute(led, [], env=OFF)
    assert rec["shards"] == [] and "backfill-routes" in rec["skipped"]
    backfill_routes(led.db)
    led.has_routes = led._has_route_columns()
    assert len(trigger.compute(led, [], env=OFF)["shards"]) == 8


def test_trigger_error_is_recorded_not_raised(tmp_path, env_off, monkeypatch):
    d, led, base = _root(tmp_path)
    _scenario(led)
    monkeypatch.setattr(trigger, "compute", lambda *a, **k: 1 / 0)
    out = publish(d, led, base, str(_manifest(tmp_path)))
    assert "ZeroDivisionError" in out["trigger"]["error"]
    assert (d / "generations.json").is_file()
