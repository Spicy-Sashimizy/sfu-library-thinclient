"""Fold-in trigger bookkeeping (doc 10 §1; F1 in §6).

At every `generation.publish()` the trigger computes, per base shard s:

  (a) frac      live delta docs routed to s ÷ base docs of s
  (d) dead_frac masked base docs routed to s ÷ base docs of s
  (c) age       age of the oldest live delta doc routed to s (ledger stage time)

evaluates them against the dials `SFU_DELTA_FOLDIN_FRAC`,
`SFU_DELTA_FOLDIN_DEAD_FRAC` and `SFU_DELTA_FOLDIN_MAX_AGE` (days) — unset =
that threshold is OFF; all unset = nothing ever fires (doc 10: nothing ships ON
until F7) — and writes the result to `<delta_root>/trigger.json` (latest, atomic)
and one line of `<delta_root>/trigger_log.jsonl`. It only REPORTS: it never
builds or publishes a fold (that stays `cli.py fold-build` / the operator's
`publish-fold`). Serving never reads either file, and nothing under `source/`
imports this module, so the gate-off path (`SFU_DELTA_ROOT` unset) is untouched.

Definitions as coded (implementation readings, doc 10 addendum 2026-10-08):

- base docs of s = `n_docs` of the record in position s of the base shard
  manifest `publish()` used (after a published fold that is s′'s record).
- (a) numerator = ledger `docs` rows with status='live' (any generation or the
  buffer), `route_shard = s`, and `seismic_origin IS NULL`. A doc whose newest
  SEISMIC copy is already inside a published fold of s (`seismic_origin =
  fold:s:k`) no longer weighs on the delta SEISMIC leg, so it is not counted.
  `IngestLedger.routed_live_counts(exclude_folded=True)`.
- (c) = now − MIN(`last_seen`) over the same rows (`last_seen` is the stage time
  of the current copy; `stage()` sets it, `foldin` uses it as `staged_at`).
- (d) numerator, no published fold of s = the number of distinct base ordinals
  set in the livedocs bitset `publish()` writes whose id routes to s: the
  bitset holds the base ordinals of every tombstoned id and every live id with
  `in_base=1` (`generation.publish`), so the trigger resolves exactly those
  ids against the same ordinal arrays and groups the found ordinals by
  `route_shard(id)`. Without ordinal arrays (no bitset is written) the
  numerator is the ledger reading: tombstones with `in_base=1` plus live
  `in_base=1` docs, routed (`d_source = "ledger"`).
- (d) after a published fold k of s (snapshot time T = `folds.snapshot`): s′ was
  built from the ledger at T, so only copies that went dead AFTER T are dead in
  s′: a live `in_base=1` doc with `last_seen > T` that was a fold member or was
  unknown to the ledger at T (`first_seen > T`), or a tombstone with `ts > T`
  whose id was a fold member or has no `docs` row with `first_seen <= T`.
  Residual edge (documented, not handled): an id tombstoned before T and again
  after T with no `docs` row is counted though s′ does not hold it. F1's
  checkpoints publish no fold, so this branch is covered by unit tests only.
- hysteresis: for 24 h after a fold of s publishes (`folds.published`), s is
  not evaluated (`in_hysteresis = true`, `fires = []`).
- (b) tax: NOT IMPLEMENTED — needs F0's size coefficient; `tax_ms` is null and
  `SFU_DELTA_FOLDIN_TAX_MS` is ignored (`tax_hook` says so in every record).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .routing import route_shard

TRIGGER_FILE = "trigger.json"
TRIGGER_LOG = "trigger_log.jsonl"
HYSTERESIS_S = 24 * 3600
ENV_FRAC = "SFU_DELTA_FOLDIN_FRAC"
ENV_DEAD_FRAC = "SFU_DELTA_FOLDIN_DEAD_FRAC"
ENV_MAX_AGE = "SFU_DELTA_FOLDIN_MAX_AGE"
TAX_HOOK = "NOT IMPLEMENTED: (b) needs F0's size coefficient (doc 10 §6 F0); SFU_DELTA_FOLDIN_TAX_MS is ignored"
CHUNK = 500


def thresholds(env=None) -> dict:
    """The three dials from the environment; an unset or empty value is OFF."""
    env = os.environ if env is None else env

    def num(k):
        v = (env.get(k) or "").strip()
        return float(v) if v else None
    return {"frac": num(ENV_FRAC), "dead_frac": num(ENV_DEAD_FRAC), "max_age_days": num(ENV_MAX_AGE)}


def base_n_docs(base_records: list[dict], n_shards: int) -> dict[int, int | None]:
    """shard -> n_docs from the base records (position s, or the record whose
    integer `shard` is s; delta-generation records are skipped)."""
    out: dict[int, int | None] = {s: None for s in range(n_shards)}
    for j, r in enumerate(base_records):
        if r.get("delta_generation") is not None:
            continue
        s = r.get("shard", j)
        if isinstance(s, int) and 0 <= s < n_shards and r.get("n_docs") is not None:
            out[s] = int(r["n_docs"])
    return out


def published_folds(db) -> dict[int, dict]:
    """shard -> newest published fold {fold, snapshot, published}; {} when the
    fold tables do not exist (read-only: never creates them)."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='folds'").fetchone():
        return {}
    out: dict[int, dict] = {}
    for s, k, snap, pub in db.execute(
            "SELECT shard, fold, snapshot, published FROM folds WHERE state='published' ORDER BY published"):
        out[int(s)] = {"fold": int(k), "snapshot": snap, "published": pub}
    return out


def _route(i: str, ledger) -> int:
    return route_shard(i, ledger.route_seed, ledger.route_shards)


def _dead_candidates(ledger, folds: dict[int, dict]) -> list[tuple[str, int]]:
    """(id, shard) of every id whose base copy is masked (the bitset's id set),
    filtered per the post-fold reading for shards with a published fold."""
    db = ledger.db
    members: dict[int, set] = {}
    for s, f in folds.items():
        members[s] = {r[0] for r in db.execute(
            "SELECT id FROM fold_members WHERE shard=? AND fold=?", (s, f["fold"]))}
    first_seen = {}
    if folds:
        first_seen = {i: fs for i, fs in db.execute("SELECT id, first_seen FROM docs")}
    out = []
    for i, ts in db.execute("SELECT id, ts FROM tombstones"):
        s = _route(i, ledger)
        f = folds.get(s)
        if f is not None:
            fs = first_seen.get(i)
            if not (ts is not None and ts > f["snapshot"]
                    and (i in members[s] or fs is None or fs > f["snapshot"])):
                continue
        out.append((i, s))
    for i, s, last, fs in db.execute(
            "SELECT id, route_shard, last_seen, first_seen FROM docs WHERE status='live' AND in_base=1"):
        s = int(s) if s is not None else _route(i, ledger)
        f = folds.get(s)
        if f is not None and not (last > f["snapshot"] and (i in members[s] or fs > f["snapshot"])):
            continue
        out.append((i, s))
    return out


def dead_counts(ledger, ordinal_dir: str | Path | None, folds: dict[int, dict]) -> tuple[dict[int, int], str]:
    """shard -> masked base docs (doc 10 §1 (d) numerator) and its source."""
    cands = _dead_candidates(ledger, folds)
    counts: dict[int, int] = {}
    if ordinal_dir:
        from .livedocs import open_ordinals
        ords = open_ordinals(ordinal_dir)
        seen: dict[int, set] = {}
        for j in range(0, len(cands), 200_000):
            chunk = cands[j:j + 200_000]
            pos, found = ords.lookup([i for i, _ in chunk])
            for (_, s), p, ok in zip(chunk, pos.tolist(), found.tolist()):
                if ok:
                    seen.setdefault(s, set()).add(p)
        counts = {s: len(v) for s, v in seen.items()}
        return counts, "livedocs"
    tomb_base = {r[0] for r in ledger.db.execute("SELECT id FROM tombstones WHERE in_base=1")}
    live_base = {r[0] for r in ledger.db.execute("SELECT id FROM docs WHERE status='live' AND in_base=1")}
    keep = tomb_base | live_base
    ids_seen: dict[int, set] = {}
    for i, s in cands:
        if i in keep:
            ids_seen.setdefault(s, set()).add(i)
    return {s: len(v) for s, v in ids_seen.items()}, "ledger"


def compute(ledger, base_records: list[dict], ordinal_dir: str | Path | None = None,
            *, now: float | None = None, env=None, stamp: str | None = None) -> dict:
    """The trigger record for the ledger as it is now (no side effects)."""
    now = time.time() if now is None else now
    th = thresholds(env)
    rec = {"format": 1, "computed_at": now, "stamp": stamp, "thresholds": th,
           "enabled": any(v is not None for v in th.values()), "hysteresis_s": HYSTERESIS_S,
           "tax_hook": TAX_HOOK, "route_seed": ledger.route_seed, "route_shards": ledger.route_shards,
           "ordinal_dir": str(ordinal_dir) if ordinal_dir else None}
    if not ledger.has_routes:
        rec.update(skipped="ledger has no route_shard column (run `cli.py backfill-routes`)", shards=[])
        return rec
    n_base = base_n_docs(base_records, ledger.route_shards)
    live = ledger.routed_live_counts(exclude_folded=True)
    oldest = {int(s): t for s, t in ledger.db.execute(
        "SELECT route_shard, MIN(last_seen) FROM docs WHERE status='live' AND seismic_origin IS NULL "
        "GROUP BY route_shard")}
    folds = published_folds(ledger.db)
    dead, d_source = dead_counts(ledger, ordinal_dir, folds)
    rec["d_source"] = d_source
    shards = []
    for s in range(ledger.route_shards):
        n = n_base.get(s)
        a_n, d_n, t0 = live.get(s, 0), dead.get(s, 0), oldest.get(s)
        f = folds.get(s)
        until = (f["published"] + HYSTERESIS_S) if f and f.get("published") else None
        row = {"shard": s, "base_docs": n, "live_routed": a_n, "masked_routed": d_n,
               "frac": (a_n / n) if n else None, "dead_frac": (d_n / n) if n else None,
               "oldest_staged_at": t0, "age_days": ((now - t0) / 86400.0) if t0 is not None else None,
               "tax_ms": None, "last_fold": f, "hysteresis_until": until,
               "in_hysteresis": bool(until is not None and now < until), "fires": []}
        if not row["in_hysteresis"]:
            if th["frac"] is not None and row["frac"] is not None and row["frac"] >= th["frac"]:
                row["fires"].append("frac")
            if th["dead_frac"] is not None and row["dead_frac"] is not None and row["dead_frac"] >= th["dead_frac"]:
                row["fires"].append("dead_frac")
            if th["max_age_days"] is not None and row["age_days"] is not None \
                    and row["age_days"] >= th["max_age_days"]:
                row["fires"].append("max_age")
        shards.append(row)
    rec["shards"] = shards
    rec["fire"] = [r["shard"] for r in shards if r["fires"]]
    return rec


def record(delta_root: Path, ledger, base_records: list[dict], ordinal_dir: str | Path | None,
           stamp: str | None) -> dict:
    """Compute + persist (trigger.json atomically, one line appended to
    trigger_log.jsonl). A failure is recorded in the file, never raised: the
    publish it follows has already happened."""
    from .generation import atomic_write_json
    try:
        rec = compute(ledger, base_records, ordinal_dir, stamp=stamp)
    except Exception as e:
        rec = {"format": 1, "computed_at": time.time(), "stamp": stamp,
               "error": f"{type(e).__name__}: {e}", "shards": []}
    delta_root = Path(delta_root)
    atomic_write_json(delta_root / TRIGGER_FILE, rec)
    with open(delta_root / TRIGGER_LOG, "a") as fh:
        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return rec
