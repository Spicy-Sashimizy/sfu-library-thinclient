#!/usr/bin/env python3
r"""Delta-ingest fold-in trigger, doc 10 §6 F1: the trigger's bookkeeping is
exact. Written 2026-10-08, BEFORE the first F1 run.

Spec: docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md (FROZEN), §1 and
the F1 row (copied verbatim below), with the implementation readings of its
addendum 2026-10-08 (written before this harness first ran).

For each root (the F-fixture `fixture_n8` and the M4 corpus (b) root
`root_n8`), on a COPY under --work (never the original):
  1. copy the ledger with the SQLite backup API from a read-only connection
     (WAL content included) and each published generation's
     `generation.json` (all `publish()` reads); `backfill-routes` on the copy
     if its ledger has no route columns;
  2. 20 checkpoints; each = one synthetic batch (upserts of new ids, updates
     of base ids, deletions of base ids, deletions of live delta ids, and
     re-adds of deleted ids) staged into the buffer, then `publish()` with the
     full ordinal arrays so a livedocs bitset is written; the publish runs the
     trigger (`spike/delta_ingest/trigger.py`);
  3. brute-force recount, independent of the trigger's code: (a)/(c) by
     iterating every `docs` row and routing its id with
     `scripts/seismic_testbed/shard_spool.py::shard_id` (not the stored
     `route_shard`); (d) by decoding the published `.liv` (crc checked),
     mapping each set ordinal to its W-id through `wids.npy` and routing it
     the same way; base docs read from the manifest file directly;
  4. a checkpoint is identical when, for all 8 shards, base docs, live
     numerator, masked numerator and `oldest_staged_at` are equal (fractions
     follow), `trigger.json` on disk equals the record publish returned, and
     nothing fires (dials unset).
Verdict per root: PASS iff 20 / 20 checkpoints identical.

Run (cwd = repo, local venv, no lock: no index is loaded):
  OMP_NUM_THREADS=2 /home/vscode/work/venv_local/bin/python3 \
    scripts/experiments/eval_delta_ingest_trigger.py --out data/eval_results/delta_ingest_foldin_f1_<date>.json

---- doc 10 §6 row F1, verbatim (frozen 2e674773) ----
| **F1** | Trigger bookkeeping is exact | (a), (d), (c) computed by the trigger vs a brute-force recount over the ledger + livedocs on the F-fixture and on `root_n8` | identical on **100%** of 20 checkpoints (after each of 20 synthetic publishes) | none |
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import time
import zlib
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from shard_spool import shard_id  # noqa: E402

from lib.thinclient.livedocs import HEADER_LEN, read_header  # noqa: E402
from spike.delta_ingest import trigger  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.generation import gen_name, publish  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import DocRecord  # noqa: E402

ROOTS = {"fixture_n8": Path("/home/vscode/work/delta_ingest/foldin/fixture_n8"),
         "root_n8": Path("/home/vscode/work/inplace_update/m4/root_n8")}
ORDS = Path("/var/tmp/sfu_delta_C_20260929/ords")
BASE_MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
WORK = Path("/home/vscode/work/delta_ingest/foldin/f1")
SEED = 20261008
SEED_ROUTE = "sfu-seismic-plan01"
N_SHARDS = 8
BATCH = {"new": 400, "update_base": 600, "delete_base": 300, "delete_delta": 120, "readd": 40}


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    print(f"[{utc()}] {msg}", flush=True)


def stat_sig(p: Path) -> dict:
    """size + mtime of the source ledger and its WAL. The `-shm` file is
    left out: SQLite readers (even `mode=ro`) write their read marks into it,
    so its mtime moves on every open (run 1 of 2026-10-08 recorded that as a
    change; see FOLDIN_FINDINGS.md 2026-10-08)."""
    return {q.name: [q.stat().st_size, q.stat().st_mtime_ns] for q in sorted(p.glob("ledger.sqlite*"))
            if not q.name.endswith("-shm")}


def make_copy(name: str, src: Path, dst: Path) -> dict:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    s = sqlite3.connect(f"file:{src / 'ledger.sqlite'}?mode=ro", uri=True)
    d = sqlite3.connect(str(dst / "ledger.sqlite"))
    s.backup(d)
    d.close()
    s.close()
    led = IngestLedger(dst / "ledger.sqlite")
    backfill = None
    if not led.has_routes:
        backfill = led.backfill_routes()
    gens = led.published_generations()
    for g in gens:
        (dst / gen_name(g)).mkdir()
        shutil.copy2(src / gen_name(g) / "generation.json", dst / gen_name(g) / "generation.json")
    led.close()
    return {"root": name, "source": str(src), "copy": str(dst), "generations": gens, "backfill": backfill}


def synthetic_batch(led: IngestLedger, rng: random.Random, wids: np.ndarray, k: int, scale: float,
                    new_counter: list) -> dict:
    n = {key: max(1, int(v * scale)) for key, v in BATCH.items()}
    db = led.db
    now_tag = f"cp{k}"
    new_ids = []
    for _ in range(n["new"]):
        new_counter[0] += 1
        new_ids.append(f"W{new_counter[0]}")
    base_ids = [f"W{int(wids[j])}" for j in rng.sample(range(len(wids)), n["update_base"] + n["delete_base"])]
    upd_base, del_base = base_ids[:n["update_base"]], base_ids[n["update_base"]:]
    prev_upd = [r[0] for r in db.execute(
        "SELECT id FROM docs WHERE status='live' AND in_base=1 ORDER BY id")]
    if prev_upd:
        del_base += rng.sample(prev_upd, min(len(prev_upd), n["delete_base"] // 5))
    live_delta = [r[0] for r in db.execute("SELECT id FROM docs WHERE status='live' AND in_base=0")]
    del_delta = rng.sample(live_delta, min(len(live_delta), n["delete_delta"]))
    tomb = [r[0] for r in db.execute("SELECT id FROM tombstones ORDER BY id")]
    readd = rng.sample(tomb, min(len(tomb), n["readd"]))
    readd_base = {r[0]: bool(r[1]) for r in db.execute(
        f"SELECT id, in_base FROM tombstones WHERE id IN ({','.join('?' * len(readd))})", readd)} if readd else {}

    def recs(ids):
        return [DocRecord(id=i, title=f"f1 {now_tag} {i}", abstract="synthetic", year=2026, type="article",
                          source="f1_synthetic", sparse_field={"f1": 1.0}) for i in ids]
    led.stage(recs(new_ids), {i: False for i in new_ids})
    led.stage(recs(upd_base), {i: True for i in upd_base})
    led.delete(del_base, {i: True for i in del_base})
    led.delete(del_delta, {i: False for i in del_delta})
    if readd:
        led.stage(recs(readd), readd_base)
    return {"new": len(new_ids), "update_base": len(upd_base), "delete_base": len(set(del_base)),
            "delete_delta": len(del_delta), "readd": len(readd)}


def brute(copy: Path, gj: dict, wids: np.ndarray) -> dict:
    db = sqlite3.connect(f"file:{copy / 'ledger.sqlite'}?mode=ro", uri=True)
    cols = {r[1] for r in db.execute("PRAGMA table_info(docs)")}
    live = [0] * N_SHARDS
    oldest = [None] * N_SHARDS
    sel = "SELECT id, status, last_seen" + (", seismic_origin" if "seismic_origin" in cols else ", NULL") + " FROM docs"
    for i, status, last, origin in db.execute(sel):
        if status != "live" or origin is not None:
            continue
        s = shard_id(i, SEED_ROUTE, N_SHARDS)
        live[s] += 1
        if oldest[s] is None or last < oldest[s]:
            oldest[s] = last
    db.close()
    ld = gj["livedocs"]
    raw = (copy / ld["path"]).read_bytes()
    hdr = read_header(raw[:HEADER_LEN])
    payload = raw[HEADER_LEN:]
    crc_ok = zlib.crc32(payload) == hdr["crc32"] == ld["crc32"]
    bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8), bitorder="little")[:hdr["nbits"]]
    set_ords = np.flatnonzero(bits)
    masked = [0] * N_SHARDS
    for w in wids[set_ords].tolist():
        masked[shard_id(f"W{w}", SEED_ROUTE, N_SHARDS)] += 1
    man = json.loads(BASE_MANIFEST.read_text())
    base_docs = [None] * N_SHARDS
    for j, r in enumerate(man["shards"]):
        base_docs[int(r.get("shard", j))] = int(r["n_docs"])
    return {"live": live, "oldest": oldest, "masked": masked, "base_docs": base_docs,
            "popcount": int(len(set_ords)), "header_popcount": hdr["popcount"], "crc_ok": bool(crc_ok)}


def compare(rec: dict, disk: dict, b: dict) -> dict:
    mism = []
    if rec != disk:
        mism.append("trigger.json on disk != record returned by publish")
    if rec.get("error"):
        mism.append(f"trigger error: {rec['error']}")
    if rec.get("d_source") != "livedocs":
        mism.append(f"d_source {rec.get('d_source')}")
    if not b["crc_ok"] or b["popcount"] != b["header_popcount"]:
        mism.append("bitset crc/popcount check failed")
    rows = rec.get("shards") or []
    if len(rows) != N_SHARDS:
        mism.append(f"{len(rows)} shard rows")
    for r in rows:
        s = r["shard"]
        for key, want in (("base_docs", b["base_docs"][s]), ("live_routed", b["live"][s]),
                          ("masked_routed", b["masked"][s]), ("oldest_staged_at", b["oldest"][s])):
            if r[key] != want:
                mism.append(f"shard {s} {key}: trigger {r[key]} vs brute {want}")
        if r["fires"]:
            mism.append(f"shard {s} fires {r['fires']} with dials unset")
    if sum(b["masked"]) != b["popcount"]:
        mism.append("brute masked sum != popcount")
    return {"identical": not mism, "mismatches": mism}


def run_root(name: str, args, wids: np.ndarray) -> dict:
    src = ROOTS[name]
    sig0 = stat_sig(src)
    copy = Path(args.work) / name
    info = make_copy(name, src, copy)
    log(f"{name}: copied to {copy} (gens {info['generations']}, backfill {info['backfill']})")
    led = IngestLedger(copy / "ledger.sqlite")
    base = BaseIndex(copy / "no_index")
    rng = random.Random(SEED + (0 if name == "fixture_n8" else 1))
    top = int(wids[-1])
    new_counter = [top + 1_000_000 + (0 if name == "fixture_n8" else 10_000_000)]
    cps = []
    for k in range(1, args.checkpoints + 1):
        t0 = time.time()
        batch = synthetic_batch(led, rng, wids, k, args.scale, new_counter)
        out = publish(copy, led, base, str(BASE_MANIFEST), str(ORDS))
        t_pub = time.time() - t0
        rec = out["trigger"]
        disk = json.loads((copy / trigger.TRIGGER_FILE).read_text())
        b = brute(copy, out, wids)
        cmp = compare(rec, disk, b)
        s0 = rec["shards"][0] if rec.get("shards") else {}
        cps.append({"checkpoint": k, "batch": batch, "stamp": out["stamp"], "publish_s": round(t_pub, 2),
                    "brute_s": round(time.time() - t0 - t_pub, 2), **cmp,
                    "trigger_shard0": {key: s0.get(key) for key in
                                       ("base_docs", "live_routed", "masked_routed", "frac", "dead_frac",
                                        "oldest_staged_at", "age_days")},
                    "brute_totals": {"live": sum(b["live"]), "masked": sum(b["masked"]),
                                     "popcount": b["popcount"]}})
        log(f"{name} cp{k}: identical={cmp['identical']} live={sum(b['live'])} masked={sum(b['masked'])} "
            f"shard0 a={s0.get('frac')} d={s0.get('dead_frac')} ({t_pub:.1f}s publish)")
        for m in cmp["mismatches"][:5]:
            log(f"  MISMATCH {m}")
    final = led.db.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0]
    led.close()
    sig1 = stat_sig(src)
    n_ok = sum(c["identical"] for c in cps)
    return {**info, "checkpoints": cps, "identical": n_ok, "of": len(cps),
            "verdict": "PASS" if n_ok == len(cps) == 20 else ("FAIL" if n_ok < len(cps) else "SMOKE"),
            "final_tombstones": final, "source_unchanged": sig0 == sig1, "source_sig": sig0,
            "last_trigger": json.loads((copy / trigger.TRIGGER_FILE).read_text())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", default="fixture_n8,root_n8")
    ap.add_argument("--checkpoints", type=int, default=20)
    ap.add_argument("--scale", type=float, default=1.0, help="batch size multiplier (smoke: 0.05)")
    ap.add_argument("--work", default=str(WORK))
    ap.add_argument("--out", default=None)
    ap.add_argument("--key", default="F1")
    a = ap.parse_args()
    for k in (trigger.ENV_FRAC, trigger.ENV_DEAD_FRAC, trigger.ENV_MAX_AGE, trigger.ENV_FRAC.replace("FRAC", "TAX_MS"),
              "SFU_THINCLIENT_ORDINALS", "SFU_DELTA_ROOT"):
        os.environ.pop(k, None)
    t0 = time.time()
    wids = np.load(ORDS / "wids.npy", mmap_mode="r")
    res = {"key": a.key, "started_utc": utc(), "git_head": subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
        "spec": "docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md §6 F1 + addendum 2026-10-08",
        "bar": "identical on 100% of 20 checkpoints (after each of 20 synthetic publishes), per root",
        "ordinal_dir": str(ORDS), "base_manifest": str(BASE_MANIFEST.relative_to(REPO)),
        "batch_per_checkpoint": {k: max(1, int(v * a.scale)) for k, v in BATCH.items()}, "seed": SEED,
        "roots": {}}
    for name in a.roots.split(","):
        res["roots"][name] = run_root(name, a, wids)
    res["wall_s"] = round(time.time() - t0, 1)
    res["finished_utc"] = utc()
    verdicts = [r["verdict"] for r in res["roots"].values()]
    res["verdict"] = "PASS" if verdicts and all(v == "PASS" for v in verdicts) else (
        "FAIL" if "FAIL" in verdicts else "SMOKE")
    log(f"F1 verdict {res['verdict']}: " + ", ".join(f"{n} {r['identical']}/{r['of']} {r['verdict']}"
                                                    for n, r in res["roots"].items()))
    if a.out:
        p = Path(a.out)
        doc = json.loads(p.read_text()) if p.exists() else {}
        doc[a.key] = res
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1))
        os.replace(tmp, p)
    return 0 if res["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
