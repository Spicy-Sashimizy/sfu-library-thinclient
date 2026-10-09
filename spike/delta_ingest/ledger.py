"""Ingest ledger — the durable spool + bookkeeping for every delta document.

One SQLite file (`<delta_root>/ledger.sqlite`, WAL). It is the only mutable
store the ingest side writes continuously; everything published to serving is
an immutable generation directory derived from it.

Tables
  sources     adapter resume cursors
  docs        id -> content_hash, encode_hash, status, generation, in_base
  records     full DocRecord JSON (with sparse_field) per id — the spool that
              makes compaction and the eventual base rebuild replays, not
              re-downloads / re-encodes
  generations gen -> state (building|published|compacted), counts, info
  tombstones  ids deleted (hard deletes from the source, or superseded by a
              non-OpenAlex namespace re-key)
  base_hashes numeric W-id -> 64-bit prefixes of the content/encode hash the
              BASE copy would have (written by `seed.py`, issue O4). Kept out
              of `docs` so seeded base ids never enter masks, the buffer or
              `docs_live`; a `docs` row, once staged, always wins.

Fold-in columns (doc 10 §3 G2/G4; `routing.py`, `foldin.py`): `docs.route_shard`
= the base shard an id routes to (plan01 blake2b rule), written at `stage()`;
`docs.seismic_origin` = `fold:s:k` when the doc's newest SEISMIC copy lives in
a published fold of shard s (NULL otherwise; every re-stage resets it). New
ledgers get both columns; an EXISTING ledger is never altered on open — only
`backfill_routes()` (CLI `backfill-routes`) adds them, so opening a ledger
written by older code leaves its file untouched and `stage()`/`mask()` behave
exactly as before for it.

generation 0 == the L0 warm buffer (searchable now, not yet frozen).
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

from .records import DocRecord
from .routing import ROUTE_SEED, ROUTE_SHARDS, route_shard

SCHEMA = """
PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS sources (name TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at REAL);
CREATE TABLE IF NOT EXISTS docs (
  id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, encode_hash TEXT NOT NULL,
  status TEXT NOT NULL, generation INTEGER NOT NULL, in_base INTEGER NOT NULL,
  section TEXT, source TEXT, first_seen REAL, last_seen REAL,
  route_shard INTEGER, seismic_origin TEXT);
CREATE INDEX IF NOT EXISTS docs_gen ON docs(generation, status);
CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, generation INTEGER NOT NULL, record TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS records_gen ON records(generation);
CREATE TABLE IF NOT EXISTS generations (gen INTEGER PRIMARY KEY, state TEXT NOT NULL,
  created REAL, published REAL, docs INTEGER, info TEXT);
CREATE TABLE IF NOT EXISTS tombstones (id TEXT PRIMARY KEY, gen INTEGER, reason TEXT, ts REAL, in_base INTEGER);
CREATE TABLE IF NOT EXISTS history (id TEXT NOT NULL, gen INTEGER NOT NULL, PRIMARY KEY (id, gen));
CREATE TABLE IF NOT EXISTS base_hashes (id INTEGER PRIMARY KEY, ch INTEGER NOT NULL, eh INTEGER NOT NULL);
"""

BUFFER_GEN = 0


def hash64(hexdigest: str) -> int:
    """Signed 64-bit prefix of a hex digest (SQLite INTEGER). Only ever
    compared against the hash of the SAME id, so a false 'unchanged' has
    probability 2**-64 per comparison."""
    return int.from_bytes(bytes.fromhex(hexdigest[:16]), "big", signed=True)


def _wnum(doc_id: str) -> int | None:
    if len(doc_id) > 1 and doc_id[0] == "W" and doc_id[1:].isdigit():
        return int(doc_id[1:])
    return None


ROUTE_COLUMNS = (("route_shard", "INTEGER"), ("seismic_origin", "TEXT"))


def backfill_routes(db: sqlite3.Connection, seed: str = ROUTE_SEED,
                    n_shards: int = ROUTE_SHARDS) -> dict:
    """Add the G2/G4 columns to an existing ledger's `docs` table if missing
    and fill `route_shard` for every row where it is NULL. Idempotent. Run
    it on the ledger you mean to change: it ALTERs and UPDATEs in place."""
    have = {r[1] for r in db.execute("PRAGMA table_info(docs)")}
    added = [c for c, _ in ROUTE_COLUMNS if c not in have]
    db.create_function("sfu_route_shard", 1, lambda i: route_shard(i, seed, n_shards),
                       deterministic=True)
    with db:
        for c, t in ROUTE_COLUMNS:
            if c not in have:
                db.execute(f"ALTER TABLE docs ADD COLUMN {c} {t}")
        n = db.execute("UPDATE docs SET route_shard=sfu_route_shard(id) WHERE route_shard IS NULL").rowcount
        db.execute("CREATE INDEX IF NOT EXISTS docs_route ON docs(route_shard, status)")
    return {"columns_added": added, "rows_routed": n, "seed": seed, "n_shards": n_shards,
            "rows": db.execute("SELECT COUNT(*) FROM docs").fetchone()[0],
            "rows_unrouted": db.execute("SELECT COUNT(*) FROM docs WHERE route_shard IS NULL").fetchone()[0]}


class IngestLedger:
    def __init__(self, path: str | Path, *, route_seed: str = ROUTE_SEED,
                 route_shards: int = ROUTE_SHARDS):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=60)
        self.db.executescript(SCHEMA)
        self.route_seed = route_seed
        self.route_shards = route_shards
        self.has_routes = self._has_route_columns()

    def _has_route_columns(self) -> bool:
        have = {r[1] for r in self.db.execute("PRAGMA table_info(docs)")}
        return all(c in have for c, _ in ROUTE_COLUMNS)

    def backfill_routes(self) -> dict:
        out = backfill_routes(self.db, self.route_seed, self.route_shards)
        self.has_routes = self._has_route_columns()
        return out

    def close(self) -> None:
        self.db.close()

    # ── source cursors ──────────────────────────────────────────────────
    def source_state(self, name: str) -> dict:
        row = self.db.execute("SELECT state FROM sources WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_source_state(self, name: str, state: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?)",
                        (name, json.dumps(state), time.time()))
        self.db.commit()

    # ── classification ──────────────────────────────────────────────────
    def known(self, ids: Iterable[str]) -> dict[str, tuple[str, str, str, int, int]]:
        """id -> (content_hash, encode_hash, status, generation, in_base)."""
        ids = list(ids)
        out = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self.db.execute(
                    f"SELECT id, content_hash, encode_hash, status, generation, in_base "
                    f"FROM docs WHERE id IN ({marks})", chunk):
                out[r[0]] = tuple(r[1:])
        return out

    def base_known(self, ids: Iterable[str]) -> dict[str, tuple[int, int]]:
        """id -> (content hash64, encode hash64) seeded for the base copy."""
        num = {n: i for i in ids if (n := _wnum(i)) is not None}
        keys = list(num)
        out = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for n, ch, eh in self.db.execute(
                    f"SELECT id, ch, eh FROM base_hashes WHERE id IN ({marks})", chunk):
                out[num[n]] = (ch, eh)
        return out

    def seed_base(self, rows: list[tuple[str, str, str]], source_state: tuple[str, dict] | None = None) -> int:
        """Upsert (W-id, content_hash hex, encode_hash hex) for base docs, and
        the seed cursor in the same transaction (resume = no double work, no
        gap). Non-W ids are skipped (the base holds none: docs_other empty)."""
        vals = [(n, hash64(ch), hash64(eh)) for i, ch, eh in rows if (n := _wnum(i)) is not None]
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO base_hashes VALUES (?,?,?)", vals)
            if source_state is not None:
                self.db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?)",
                                (source_state[0], json.dumps(source_state[1]), time.time()))
        return len(vals)

    def classify(self, records: list[DocRecord], in_base: dict[str, bool]) -> dict[str, list[DocRecord]]:
        """Split into new / updated / unchanged. `in_base[id]` says whether the
        immutable base already holds the id (caller resolves via meta.sqlite).
        An unchanged content hash is skipped entirely — this is the guard
        against OpenAlex's citation-count churn re-encoding the world. An
        in-base id with no `docs` row is compared against its seeded base hash
        (`base_hashes`); unseeded in-base ids stay 'updated'."""
        known = self.known(r.id for r in records)
        base = self.base_known(r.id for r in records if r.id not in known and in_base.get(r.id))
        out: dict[str, list[DocRecord]] = {"new": [], "updated": [], "unchanged": []}
        for r in records:
            k = known.get(r.id)
            if k is not None:
                if k[0] == r.content_hash() and k[2] == "live":
                    out["unchanged"].append(r)
                else:
                    out["updated"].append(r)
            elif in_base.get(r.id):
                b = base.get(r.id)
                if b is not None and b[0] == hash64(r.content_hash()):
                    out["unchanged"].append(r)
                else:
                    out["updated"].append(r)
            else:
                out["new"].append(r)
        return out

    def reusable_sparse(self, records: list[DocRecord]) -> dict[str, dict[str, float]]:
        """Stored sparse vectors for records whose encoder text is unchanged
        (year/doi/is_oa-only updates re-index without touching the GPU)."""
        known = self.known(r.id for r in records)
        out = {}
        for r in records:
            k = known.get(r.id)
            if k is None or k[1] != r.encode_hash():
                continue
            row = self.db.execute("SELECT record FROM records WHERE id=?", (r.id,)).fetchone()
            if row:
                sp = json.loads(row[0]).get("sparse_field")
                if sp:
                    out[r.id] = sp
        return out

    # ── staging into the buffer (generation 0) ───────────────────────────
    def stage(self, records: list[DocRecord], in_base: dict[str, bool]) -> int:
        """Upsert into the buffer. A doc that was already published in some
        generation keeps a stale copy THERE (immutable), so its old generation
        goes to `history` and the mask hides that copy (newest-wins)."""
        now = time.time()
        known = self.known(r.id for r in records)
        rows_docs, rows_rec, rows_hist = [], [], []
        for r in records:
            k = known.get(r.id)
            if k is not None and k[3] >= 1:
                rows_hist.append((r.id, k[3]))
            row = (r.id, r.content_hash(), r.encode_hash(), "live", BUFFER_GEN,
                   1 if in_base.get(r.id) else 0, r.section(), r.source, now, now)
            if self.has_routes:
                row += (route_shard(r.id, self.route_seed, self.route_shards),)
            rows_docs.append(row)
            rows_rec.append((r.id, BUFFER_GEN, r.to_json()))
        upsert = ("content_hash=excluded.content_hash, encode_hash=excluded.encode_hash, "
                  "status='live', generation=excluded.generation, "
                  "in_base=MAX(in_base, excluded.in_base), section=excluded.section, "
                  "source=excluded.source, last_seen=excluded.last_seen")
        if self.has_routes:
            sql = ("INSERT INTO docs (id, content_hash, encode_hash, status, generation, in_base, "
                   "section, source, first_seen, last_seen, route_shard) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                   "ON CONFLICT(id) DO UPDATE SET " + upsert +
                   ", route_shard=excluded.route_shard, seismic_origin=NULL")
        else:
            sql = "INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET " + upsert
        with self.db:
            self.db.executemany(sql, rows_docs)
            self.db.executemany("INSERT OR REPLACE INTO records VALUES (?,?,?)", rows_rec)
            self.db.executemany("INSERT OR IGNORE INTO history VALUES (?,?)", rows_hist)
            ids = [r.id for r in records]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                self.db.execute(f"DELETE FROM tombstones WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        return len(records)

    def delete(self, ids: Iterable[str], in_base: dict[str, bool], reason: str = "source") -> int:
        now = time.time()
        ids = list(dict.fromkeys(ids))
        with self.db:
            for wid in ids:
                self.db.execute("INSERT OR REPLACE INTO tombstones VALUES (?,?,?,?,?)",
                                (wid, BUFFER_GEN, reason, now, 1 if in_base.get(wid) else 0))
                self.db.execute("UPDATE docs SET status='deleted', last_seen=? WHERE id=?", (now, wid))
        return len(ids)

    # ── buffer / generations ─────────────────────────────────────────────
    def buffer_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM docs WHERE generation=0 AND status='live'").fetchone()[0]

    def buffer_records(self, after_rowid: int = 0) -> list[tuple[int, DocRecord]]:
        """Buffer = generation 0 PLUS generations still `building`, so a doc
        stays visible in the mutable tier until its frozen generation is
        published (no visibility gap during a long SEISMIC build)."""
        rows = self.db.execute(
            "SELECT r.rowid, r.record FROM records r JOIN docs d ON d.id=r.id "
            "WHERE (r.generation=0 OR r.generation IN (SELECT gen FROM generations WHERE state='building')) "
            "AND d.status='live' AND r.rowid>? ORDER BY r.rowid", (after_rowid,)).fetchall()
        return [(rid, DocRecord.from_json(rec)) for rid, rec in rows]

    def buffer_signature(self) -> tuple[int, int]:
        """(count, max rowid) of the mutable tier — a reader polls this to know
        whether to append new rows or rebuild (rows left the buffer)."""
        row = self.db.execute(
            "SELECT COUNT(*), COALESCE(MAX(r.rowid),0) FROM records r JOIN docs d ON d.id=r.id "
            "WHERE (r.generation=0 OR r.generation IN (SELECT gen FROM generations WHERE state='building')) "
            "AND d.status='live'").fetchone()
        return int(row[0]), int(row[1])

    def records_for(self, gens: Iterable[int]) -> list[DocRecord]:
        gens = list(gens)
        marks = ",".join("?" * len(gens))
        rows = self.db.execute(
            f"SELECT r.record FROM records r JOIN docs d ON d.id=r.id "
            f"WHERE r.generation IN ({marks}) AND d.status='live' ORDER BY r.id", gens).fetchall()
        return [DocRecord.from_json(r[0]) for r in rows]

    def next_generation(self) -> int:
        row = self.db.execute("SELECT MAX(gen) FROM generations").fetchone()
        return (row[0] or 0) + 1

    def open_generation(self, gen: int, records: list[DocRecord], from_gens: list[int] | None = None) -> None:
        with self.db:
            self.db.execute("INSERT INTO generations VALUES (?,?,?,?,?,?)",
                            (gen, "building", time.time(), None, len(records),
                             json.dumps({"from_gens": from_gens or [BUFFER_GEN]})))
            ids = [r.id for r in records]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                self.db.execute(f"UPDATE docs SET generation=? WHERE id IN ({marks})", [gen, *chunk])
                self.db.execute(f"UPDATE records SET generation=? WHERE id IN ({marks})", [gen, *chunk])
                self.db.execute(f"UPDATE tombstones SET gen=? WHERE gen=0 AND id IN ({marks})", [gen, *chunk])

    def finish_generation(self, gen: int, info: dict, retire: list[int] | None = None) -> None:
        """Mark `gen` published. `from_gens` written by `open_generation` is
        kept in the published `info` (the serving reader's
        `_buffer_generations` classifies generations by it)."""
        with self.db:
            row = self.db.execute("SELECT info FROM generations WHERE gen=?", (gen,)).fetchone()
            prev = json.loads(row[0]) if row and row[0] else {}
            merged = dict(info)
            if "from_gens" not in merged and "from_gens" in prev:
                merged["from_gens"] = prev["from_gens"]
            self.db.execute("UPDATE generations SET state='published', published=?, info=? WHERE gen=?",
                            (time.time(), json.dumps(merged), gen))
            for g in retire or []:
                self.db.execute("UPDATE generations SET state='compacted' WHERE gen=?", (g,))
            self.db.execute("UPDATE tombstones SET gen=? WHERE gen=0", (gen,))

    def abort_generation(self, gen: int) -> None:
        with self.db:
            self.db.execute("UPDATE docs SET generation=0 WHERE generation=?", (gen,))
            self.db.execute("UPDATE records SET generation=0 WHERE generation=?", (gen,))
            self.db.execute("DELETE FROM generations WHERE gen=?", (gen,))

    def published_generations(self) -> list[int]:
        return [r[0] for r in self.db.execute(
            "SELECT gen FROM generations WHERE state='published' ORDER BY gen")]

    # ── masks for serving ───────────────────────────────────────────────
    def mask(self) -> dict:
        """{"deleted": [ids], "superseded": {id: newest_gen}} — `deleted` hides a
        doc everywhere; `superseded` hides the BASE copy and any delta copy
        older than newest_gen (newest-wins across immutable segments).
        `newest_by_leg` (G4, present only when some live doc's newest SEISMIC
        copy is a published fold): {"seismic": {id: "fold:s:k"}} — the SEISMIC
        leg's newest origin where it differs from `superseded` (which stays
        the sections/meta/abstract leg's newest generation)."""
        deleted = [r[0] for r in self.db.execute("SELECT id FROM tombstones")]
        superseded = {r[0]: r[1] for r in self.db.execute(
            "SELECT id, generation FROM docs WHERE status='live' "
            "AND (in_base=1 OR id IN (SELECT id FROM history))")}
        out = {"deleted": deleted, "superseded": superseded}
        if self.has_routes:
            seismic = {r[0]: r[1] for r in self.db.execute(
                "SELECT id, seismic_origin FROM docs WHERE status='live' AND seismic_origin IS NOT NULL")}
            if seismic:
                out["newest_by_leg"] = {"seismic": seismic}
        return out

    def active_fold_manifest(self) -> str | None:
        """The composed shard manifest of the newest published fold (it carries
        every earlier published fold), or None. Read-only: never creates the
        fold tables."""
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='folds'").fetchone():
            return None
        row = self.db.execute("SELECT manifest FROM folds WHERE state='published' "
                              "ORDER BY published DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def routed_live_counts(self, exclude_folded: bool = False) -> dict[int, int]:
        """Live delta docs per routed base shard (doc 10 §1 (a) numerator).
        `exclude_folded` leaves out docs whose newest SEISMIC copy is inside
        a published fold (`seismic_origin` set) — the trigger's reading."""
        if not self.has_routes:
            return {}
        extra = " AND seismic_origin IS NULL" if exclude_folded else ""
        return {int(s): int(n) for s, n in self.db.execute(
            "SELECT route_shard, COUNT(*) FROM docs WHERE status='live'" + extra + " GROUP BY route_shard")}

    def stats(self) -> dict:
        q = lambda s, *a: self.db.execute(s, a).fetchone()[0]  # noqa: E731
        return {"docs_live": q("SELECT COUNT(*) FROM docs WHERE status='live'"),
                "buffer": self.buffer_count(),
                "tombstones": q("SELECT COUNT(*) FROM tombstones"),
                "generations": {r[0]: r[1] for r in self.db.execute("SELECT gen, state FROM generations")},
                "base_seeded": q("SELECT COUNT(*) FROM base_hashes"),
                "records_bytes": q("SELECT COALESCE(SUM(LENGTH(record)),0) FROM records")}
