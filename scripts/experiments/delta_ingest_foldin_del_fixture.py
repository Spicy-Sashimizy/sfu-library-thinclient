#!/usr/bin/env python3
r"""Deletions fixture for fold-in F2 Q-d (doc 10 §5 (ii); doc 12 §4 item 1).
Written 2026-10-08, BEFORE the fold of this fixture was built.

Builds a NEW delta root = a copy of the fold-in fixture `fixture_n8` (M4
corpus (b): 8 generations, 160,347 new docs, 20,112 routed to shard 0) plus the
Stage-0 encoded subsample of the closed in-place spike, through the product
ledger path:

  1. `cp -a fixture_n8 <dest>`; the copy's fold tables are emptied (folds 1-3
     of fixture_n8 belong to that root; this fixture's folds go to their own
     fold root, so its first fold is fold 1).
  2. deletions: every row of `deleted_rows_2026-06-17_2026-09-15.npz`
     (1,131,292 shard-0 twin rows) -> W-id via `shard_ids.npy` ->
     `IngestLedger.delete(ids, in_base=BaseIndex.contains)` + buffer delete.
  3. upserts: the 32,155 encoded docs of stage2/docs (the Stage-0 `partsout`
     part files copied by the in-place bench's prep-docs, with their texts):
     DocRecord(id="W<n>", title=<encoder text>, year, sparse_field = the cached
     vector with token ids inverted through the twin's token map), exactly the
     records the in-place bench's A1 arm built. `IngestLedger.stage` +
     buffer upsert, in deletion-then-upsert order (an upsert of a deleted id
     re-stages it, the source order of the bench's q1 batch).
  4. `freeze_buffer` (one new generation, SEISMIC + sections, profile
     desktop_gpu) and `publish` with the base ordinal arrays, so deletes and
     superseded base copies go into the livedocs bitset — the serving masks.

Nothing under <repo>/data/ is written. Records `<dest>/build_fixture.json`.

Run (lock-free; ~2-5 min):
  /home/vscode/work/venv_local/bin/python3 scripts/experiments/delta_ingest_foldin_del_fixture.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "source"))

SRC = Path("/home/vscode/work/delta_ingest/foldin/fixture_n8")
DEST = Path("/home/vscode/work/delta_ingest/foldin/fixture_n8_del")
DOCS = Path("/home/vscode/work/inplace_update/stage2/docs")
TWIN = Path("/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap")
ORDS = Path("/var/tmp/sfu_delta_C_20260929/ords")
EXPECT = {"deletes": 1131292, "upserts": 32155, "upserts_in_base": 8465}


def log(msg) -> None:
    print(time.strftime("%H:%M:%S", time.gmtime()), msg, flush=True)


def stage0_records():
    from spike.delta_ingest.foldin import load_token_map
    from spike.delta_ingest.records import DocRecord
    tok = load_token_map(TWIN)
    inv = {v: k for k, v in tok.items()}
    recs, part_counts = [], {}
    for p in sorted(x for x in DOCS.glob("updated_date=*.npz") if not x.name.endswith(".texts.npz")):
        date = p.name.split("=")[1][:10]
        z = np.load(p, allow_pickle=True)
        num, sel, cptr, comp, val = z["num"], z["sel"], z["cptr"], z["comp"], z["val"]
        tz = np.load(p.with_name(p.name[:-4] + ".texts.npz"), allow_pickle=True)
        tmap = {int(i): (str(t), int(y) or None) for i, t, y in zip(tz["ids"], tz["texts"], tz["years"])}
        for i in range(len(sel)):
            a, b = int(cptr[i]), int(cptr[i + 1])
            sf = {inv[int(c)]: float(v) for c, v in zip(comp[a:b], val[a:b].astype(np.float32)) if float(v) > 0}
            wid = int(num[sel[i]])
            text, year = tmap.get(wid, ("", None))
            recs.append((date, wid, DocRecord(id=f"W{wid}", title=text, year=year, sparse_field=sf,
                                              source="stage0_q1")))
        part_counts[p.name] = len(sel)
    recs.sort(key=lambda x: (x[0], x[1]))
    return [r for _, _, r in recs], part_counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--dest", default=str(DEST))
    ap.add_argument("--ordinal-dir", default=str(ORDS))
    ap.add_argument("--profile", default="desktop_gpu")
    ap.add_argument("--keep-folds", action="store_true",
                    help="keep the source's fold tables (F6: the batch lands on a root with a published fold)")
    a = ap.parse_args()
    src, dest = Path(a.src), Path(a.dest)
    if dest.exists():
        raise SystemExit(f"{dest} exists; this builder never overwrites a fixture")
    if str(dest.resolve()).startswith(str((REPO / "data").resolve())):
        raise SystemExit("refusing a destination under <repo>/data")
    from spike.delta_ingest.base import BaseIndex
    from spike.delta_ingest.buffer import BufferWriter
    from spike.delta_ingest.generation import freeze_buffer
    from spike.delta_ingest.ledger import IngestLedger
    from spike.delta_ingest.profiles import PROFILES
    from spike.delta_ingest.routing import route_shard

    t0 = time.time()
    rec = {"item": "doc 12 §4 item 1 / doc 10 §5 (ii): deletions fixture for F2 Q-d", "date_utc":
           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "script": str(Path(__file__).relative_to(REPO)),
           "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                                      text=True).stdout.strip(),
           "src": str(src), "dest": str(dest), "stage0_docs": str(DOCS), "twin": str(TWIN),
           "ordinal_dir": a.ordinal_dir, "docset": json.loads((DOCS / "docset.json").read_text())["q1"]}
    subprocess.run(["cp", "-a", str(src), str(dest)], check=True)
    log(f"copied {src} -> {dest}")

    ledger = IngestLedger(dest / "ledger.sqlite")
    base = BaseIndex(REPO / "data" / "thinclient_index")
    profile = PROFILES[a.profile]
    try:
        assert ledger.has_routes, "fixture_n8 copy has no route_shard column"
        rec["keep_folds"] = a.keep_folds
        with ledger.db:
            for t in (() if a.keep_folds else ("fold_members", "folds")):
                if ledger.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                    rec[f"cleared_{t}"] = ledger.db.execute(f"DELETE FROM {t}").rowcount
        before = ledger.stats()
        rec["before"] = {k: before[k] for k in ("docs_live", "buffer", "tombstones")}
        rec["before"]["routed_live_shard0"] = ledger.routed_live_counts().get(0, 0)
        assert before["buffer"] == 0 and before["tombstones"] == 0

        ids = np.load(DOCS / "shard_ids.npy")
        rows = np.load(DOCS / "deleted_rows_2026-06-17_2026-09-15.npz", allow_pickle=True)["rows"]
        del_ids = [f"W{int(ids[r])}" for r in np.sort(rows)]
        assert len(del_ids) == EXPECT["deletes"] == len(set(del_ids))
        known_fixture = {r[0] for r in ledger.db.execute("SELECT id FROM docs")}
        rec["deletes_hitting_fixture_docs"] = len(known_fixture.intersection(del_ids))
        routed = sum(1 for i in del_ids if route_shard(i, ledger.route_seed, ledger.route_shards) == 0)
        rec["deletes_routed_shard0"] = routed
        in_base_del = base.contains(del_ids)
        rec["deletes_in_base_meta"] = sum(in_base_del.values())
        log(f"deleting {len(del_ids)} ids (routed to shard 0: {routed}, in base meta: {rec['deletes_in_base_meta']})")
        ledger.delete(del_ids, in_base_del, reason="stage0_q1")
        w = BufferWriter(dest)
        try:
            w.delete(del_ids)
            w.commit()
        finally:
            w.close()

        recs, part_counts = stage0_records()
        rec["upsert_parts"] = part_counts
        assert len(recs) == EXPECT["upserts"] == len({r.id for r in recs})
        shard_set = {f"W{int(x)}" for x in ids}
        rec["upserts_in_shard0_rows"] = sum(1 for r in recs if r.id in shard_set)
        assert rec["upserts_in_shard0_rows"] == EXPECT["upserts_in_base"], rec["upserts_in_shard0_rows"]
        rec["upserts_routed_shard0"] = sum(1 for r in recs
                                           if route_shard(r.id, ledger.route_seed, ledger.route_shards) == 0)
        rec["upserts_of_deleted_ids"] = len(set(del_ids).intersection(r.id for r in recs))
        rec["upserts_hitting_fixture_docs"] = len(known_fixture.intersection(r.id for r in recs))
        rec["upserts_empty_vector"] = sum(1 for r in recs if not r.sparse_field)
        rec["upserts_empty_text"] = sum(1 for r in recs if not r.title)
        in_base_up = base.contains(r.id for r in recs)
        rec["upserts_in_base_meta"] = sum(in_base_up.values())
        cls = ledger.classify(recs, in_base_up)
        rec["classify"] = {k: len(v) for k, v in cls.items()}
        log(f"staging {len(recs)} upserts ({rec['upserts_in_base_meta']} in base meta, "
            f"{rec['upserts_routed_shard0']} routed to shard 0)")
        ledger.stage(recs, in_base_up)
        w = BufferWriter(dest)
        try:
            w.upsert(recs)
            w.commit()
        finally:
            w.close()

        t1 = time.time()
        out = freeze_buffer(dest, ledger, base, profile, seismic=True, ordinal_dir=a.ordinal_dir)
        rec["freeze_s"] = round(time.time() - t1, 1)
        rec["frozen_generation"] = out["frozen_generation"]
        rec["frozen_docs"] = out["frozen_docs"]
        keep = {r.id for _, r in ledger.buffer_records()}
        w = BufferWriter(dest)
        try:
            rec["buffer_removed_after_freeze"] = w.retain_only(keep)
            w.commit()
        finally:
            w.close()
        after = ledger.stats()
        rec["after"] = {k: after[k] for k in ("docs_live", "buffer", "tombstones")}
        rec["after"]["routed_live_shard0"] = ledger.routed_live_counts().get(0, 0)
        m = ledger.mask()
        rec["after"]["mask_superseded"] = len(m["superseded"])
        gj = json.loads((dest / "generations.json").read_text())
        rec["published"] = {"stamp": gj["stamp"], "generations": len(gj["generations"]),
                            "mask_deleted_json": len(gj["mask"]["deleted"]),
                            "mask_superseded_json": len(gj["mask"]["superseded"]),
                            "livedocs": gj.get("livedocs"), "shard_manifest": gj.get("shard_manifest"),
                            "base_shard_manifest": gj.get("base_shard_manifest")}
        assert gj.get("livedocs"), "publish wrote no livedocs entry"
        assert all(Path(g["dir"]).parent == dest for g in gj["generations"]), "generation dirs not the copy's"
        assert after["buffer"] == 0
    finally:
        ledger.close()
        base.close()
    rec["wall_s"] = round(time.time() - t0, 1)
    (dest / "build_fixture.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    print(json.dumps(rec, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
