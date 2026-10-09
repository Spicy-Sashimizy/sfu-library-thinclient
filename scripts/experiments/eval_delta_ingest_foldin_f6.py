#!/usr/bin/env python3
r"""Delta-ingest fold-in F6: repeated folds do not compound drift (doc 10 §6 F6).

Readings: doc 10 addendum "2026-10-09 — F6 implementation reading" (written
before any F6 build). The fold build, preview and F2 measurement reuse
`scripts/experiments/eval_delta_ingest_foldin.py`; this script does what that
harness does not:

  setup   fixture_n8 copy -> publish over the staged base manifest -> fold 1
          READY + publish-fold -> the Stage-0 Q1 batch through
          delta_ingest_foldin_del_fixture.py --keep-folds. Writes
          <work>/setup.json.
  post    the recorded (no-bar) overlaps: F's shard-own top-10 vs A0 on
          base-only docs, the same for the deletions fold, and fold-2-of-s'
          vs the deletions fold (same doc set) on shard-own and federated
          lists. Merges key `F6_overlaps` into the results file.

---- doc 10 §6 row F6, verbatim (frozen 2e674773) ----
| **F6** | Repeated folds do not compound drift | a second fold of *s′* from its own c1a output + a second delta batch (corpus (b) half not used in fold 1, or Stage-0 Q2 synthetic) | F2's Q-a and Q-b hold for fold 2 vs its live reference; overlap@10(fold 2, A0) on base-only docs recorded | shared OK |
---- end verbatim ----
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

FOLDIN = Path("/home/vscode/work/delta_ingest/foldin")
WORK = Path("/home/vscode/work/delta_ingest/foldin_f6")
SRC_FIXTURE = FOLDIN / "fixture_n8"
ROOT_PUB = WORK / "root_pub"
FIXTURE = WORK / "fixture"
M4BASE = Path("/home/vscode/work/inplace_update/m4/base_manifest.json")
FOLD1 = 1
SHARD = 0
DRIFT_WORK = Path("/home/vscode/work/delta_ingest/twin_drift")
DEL_ROWS = Path("/home/vscode/work/delta_ingest/foldin_del/f2/rows.json")
DEL_LEDGER = FOLDIN / "fixture_n8_del" / "ledger.sqlite"
SETS = {"QT": "topics120", "QD": "diverse100"}
F2_EVIDENCE = ("data/eval_results/delta_ingest_foldin_20261003.json#F2 + #F2_qb_federated (fold 1, F2 PASS at the "
               "owner's federated Q-b level, doc 10 addendum 2026-10-04)")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    print(f"[{utc()}] {msg}", flush=True)


def cli(args: list[str], timeout: int = 7200) -> dict:
    t = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "spike.delta_ingest.cli", *args], cwd=str(REPO),
                       capture_output=True, text=True, timeout=timeout)
    return {"argv": args, "rc": p.returncode, "s": round(time.perf_counter() - t, 2),
            "stdout_tail": p.stdout[-1500:], "stderr_tail": p.stderr[-1500:] if p.returncode else ""}


def published(root: Path) -> dict:
    gj = json.loads((root / "generations.json").read_text())
    sm = json.loads(Path(gj["shard_manifest"]).read_text()) if gj.get("shard_manifest") else {}
    return {"stamp": gj.get("stamp"), "generations": [(g["gen"], g["docs"], g["seismic"]) for g in gj["generations"]],
            "shard_manifest": gj.get("shard_manifest"), "base_shard_manifest": gj.get("base_shard_manifest"),
            "livedocs": bool(gj.get("livedocs")),
            "origins": [r.get("delta_generation") if r.get("delta_generation") is not None else r.get("fold_origin")
                        for r in sm.get("shards") or []],
            "newest_by_leg_seismic": len(((gj.get("mask") or {}).get("newest_by_leg") or {}).get("seismic") or {})}


def preset_fold_manifest(root: Path) -> dict | None:
    """Reuse fold 1's composed manifest (composed by F3 from the same staged base) instead of composing a new one."""
    out = FOLDIN / "manifests" / f"shard_manifest.fold_s{SHARD}_k{FOLD1}.json"
    db = sqlite3.connect(str(root / "ledger.sqlite"))
    try:
        state, info, prev = db.execute("SELECT state, info, manifest FROM folds WHERE shard=? AND fold=?",
                                       (SHARD, FOLD1)).fetchone()
        if not out.exists() or prev:
            return None
        m = json.loads(out.read_text())
        recs = [r for r in m.get("shards") or [] if r.get("fold_origin") == f"fold:{SHARD}:{FOLD1}"]
        mmap = json.loads(info or "{}").get("mmap_dir")
        if m.get("composed_from") != str(M4BASE) or len(recs) != 1 or recs[0].get("mmap_dir") != mmap:
            raise SystemExit(f"{out} was composed from other inputs; inspect by hand")
        with db:
            db.execute("UPDATE folds SET manifest=? WHERE shard=? AND fold=?", (str(out), SHARD, FOLD1))
        return {"reused_manifest": str(out)}
    finally:
        db.close()


def cmd_setup(a) -> int:
    from spike.delta_ingest import foldin
    from spike.delta_ingest.ledger import IngestLedger
    WORK.mkdir(parents=True, exist_ok=True)
    rec = {"utc_start": utc(), "git_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                                                          capture_output=True, text=True).stdout.strip()}
    if not ROOT_PUB.exists():
        t = time.perf_counter()
        shutil.copytree(SRC_FIXTURE, ROOT_PUB, symlinks=True)
        db = sqlite3.connect(str(ROOT_PUB / "ledger.sqlite"))
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()
        rec["copy_s"] = round(time.perf_counter() - t, 1)
        rec["publish"] = cli(["publish", "--delta-root", str(ROOT_PUB), "--base-shard-manifest", str(M4BASE)])
        if rec["publish"]["rc"]:
            raise SystemExit(f"publish failed: {rec['publish']['stderr_tail']}")
        led = IngestLedger(ROOT_PUB / "ledger.sqlite")
        try:
            foldin.mark_fold_ready(led, SHARD, FOLD1, {"F2": F2_EVIDENCE, "by": "F6 setup, on a copy", "utc": utc()})
        finally:
            led.close()
        rec["manifest_preset"] = preset_fold_manifest(ROOT_PUB)
        rec["publish_fold"] = cli(["publish-fold", "--delta-root", str(ROOT_PUB), "--shard", str(SHARD), "--fold",
                                   str(FOLD1), "--confirm", "--base-shard-manifest", str(M4BASE)])
        if rec["publish_fold"]["rc"]:
            raise SystemExit(f"publish-fold failed: {rec['publish_fold']['stderr_tail']}")
    rec["root_pub"] = published(ROOT_PUB)
    o = rec["root_pub"]["origins"]
    if o[0] != f"fold:{SHARD}:{FOLD1}" or any(o[1:8]) or len(o) != 16:
        raise SystemExit(f"root_pub after publish-fold: unexpected served shards {o}")
    if not FIXTURE.exists():
        p = subprocess.run([sys.executable, "scripts/experiments/delta_ingest_foldin_del_fixture.py", "--src",
                            str(ROOT_PUB), "--dest", str(FIXTURE), "--keep-folds"], cwd=str(REPO),
                           capture_output=True, text=True)
        rec["batch"] = {"rc": p.returncode, "stdout_tail": p.stdout[-2500:], "stderr_tail": p.stderr[-2500:]}
        if p.returncode:
            raise SystemExit(f"batch builder failed: {p.stderr[-1500:]}")
    rec["fixture"] = published(FIXTURE)
    f = rec["fixture"]
    if f["origins"][0] != f"fold:{SHARD}:{FOLD1}" or len(f["generations"]) != 9 or not f["livedocs"]:
        raise SystemExit(f"fixture after the batch is not s' + 9 generations + livedocs: {f}")
    rec["utc_end"] = utc()
    (WORK / "setup.json").write_text(json.dumps(rec, indent=1, default=str))
    log(json.dumps({"root_pub": rec["root_pub"]["origins"][:9], "fixture_gens": f["generations"],
                    "newest_by_leg_seismic": f["newest_by_leg_seismic"]}))
    return 0


def known_ids(ledger_path: Path) -> set:
    db = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
    try:
        s = {r[0] for r in db.execute("SELECT id FROM docs")}
        s.update(r[0] for r in db.execute("SELECT id FROM tombstones"))
        return s
    finally:
        db.close()


def overlap10(a: list, b: list) -> float:
    return len(set(a[:10]) & set(b[:10])) / 10.0


def base_only_overlap(own_rows: list, a0: dict, known: set) -> dict:
    out = {}
    for k, name in SETS.items():
        vals = []
        rows = [r for r in own_rows if r["set"] == k]
        for r in rows:
            f = [d for d, _ in r["F"]["own10"] if d not in known]
            ref = [d for d, _ in a0[name][r["i"]] if d not in known][:len(f)]
            if f:
                vals.append(len(set(f) & set(ref)) / len(f))
        out[k] = {"mean": round(float(np.mean(vals)), 4) if vals else None, "n": len(vals)}
    return out


def cmd_post(a) -> int:
    rows = json.loads(Path(a.rows).read_text())
    drows = json.loads(DEL_ROWS.read_text())
    a0 = json.loads((DRIFT_WORK / "q_served_dv.json").read_text())["results"][0]
    known = known_ids(FIXTURE / "ledger.sqlite")
    known_del = known_ids(DEL_LEDGER)
    rec = {"utc": utc(), "reading": "doc 10 addendum 2026-10-09 — F6 implementation reading (recorded, no bar)",
           "known_ids_f6": len(known), "known_ids_del": len(known_del),
           "base_only_overlap_vs_A0": {"fold2_of_s_prime": base_only_overlap(rows["leg"], a0, known),
                                       "deletions_fold_from_twin": base_only_overlap(drows["leg"], a0, known_del)}}
    by = {(r["set"], r["i"]): r for r in drows["leg"]}
    fvf = {}
    for k in SETS:
        own, fed = [], []
        for r in rows["leg"]:
            if r["set"] != k or (k, r["i"]) not in by:
                continue
            d = by[(k, r["i"])]
            own.append(overlap10([x for x, _ in r["F"]["own10"]], [x for x, _ in d["F"]["own10"]]))
            fed.append(overlap10([x for x, _ in r["F"]["fed10"]], [x for x, _ in d["F"]["fed10"]]))
        fvf[k] = {"own10_mean": round(float(np.mean(own)), 4) if own else None,
                  "fed10_mean": round(float(np.mean(fed)), 4) if fed else None, "n": len(own),
                  "identical_fed10": sum(1 for x in fed if x == 1.0)}
    rec["fold2_of_s_prime_vs_deletions_fold"] = fvf
    out = Path(a.out)
    full = json.loads(out.read_text()) if out.exists() else {}
    full["F6_overlaps"] = rec
    out.write_text(json.dumps(full, indent=1) + "\n")
    print(json.dumps(rec, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    p = sub.add_parser("post")
    p.add_argument("--rows", default=str(WORK / "f2" / "rows.json"))
    p.add_argument("--out", required=True)
    a = ap.parse_args()
    return {"setup": cmd_setup, "post": cmd_post}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
