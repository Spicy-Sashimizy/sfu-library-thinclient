"""Fold-in prerequisite gates G2 and G6 (docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md §3).

Frozen bars (copied from doc 10 §3, not re-cut):
  G2: "10,000 / 10,000 ids sampled (seed 20261001) from each served shard's
      doc mapping route to that shard (all 8 shards; any miss fails G2 and
      stops the track until explained)."
  G6: "(not a gate on a value): mean nnz and L2 norm of re-encoded vs stored
      vectors for >= 1,000 text-unchanged docs ... recorded before F2 runs."

Subcommands
  g2-routing   read ONLY document_mapping_{offsets,strings}.bin of the 8 served
               shards (manifest = the serving default ladder, e5_v2); sample
               10,000 ordinals per shard with ONE numpy Generator seeded
               20261001, drawn shard 0..7 in order (rng.choice(n, 10000,
               replace=False), sorted); route each id with
               spike/delta_ingest/routing.route_shard and count misses.
               Bounded memory: memmap of the offsets + one pread per id.
               SHARED latency lock (index IO).
  g2-backfill  copy a fixture ledger with the sqlite backup API (source opened
               read-only) into WORK, run backfill_routes() on the COPY, and
               cross-check every row against route_shard. The source is never
               written.
  g6-calib     the O14 gpu-check selection (meta rows id > 4,000,000,000 in id
               order, LIMIT 60,000, in shard 0 and in social_sciences__recent,
               with a sidecar abstract; <= 2,000 docs), re-encode with the
               ingest encoder on the GPU, record mean nnz AND mean L2 norm of
               re-encoded vs stored (twin f16) vectors, per-doc ratios.
               SHARED latency lock (GPU). Timings invalid by declaration.

Usage (repo root)
  flock -s /tmp/sfu_latency_measure.lock nice -n 19 taskset -c 12-15 env OMP_NUM_THREADS=2 \\
      .venv/bin/python3 scripts/experiments/eval_delta_ingest_foldin_gates.py g2-routing
  nice -n 19 taskset -c 12-15 .venv/bin/python3 scripts/experiments/eval_delta_ingest_foldin_gates.py \\
      g2-backfill --ledger /home/vscode/work/delta_ingest/corpus_a/root/ledger.sqlite
  flock -s /tmp/sfu_latency_measure.lock nice -n 19 taskset -c 12-15 env OMP_NUM_THREADS=2 \\
      /home/vscode/work/venv_local/bin/python3 scripts/experiments/eval_delta_ingest_foldin_gates.py g6-calib
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest.base import SHARD_MANIFEST_LADDER  # noqa: E402
from spike.delta_ingest.routing import ROUTE_SEED, ROUTE_SHARDS, route_shard  # noqa: E402

RESULTS = REPO / "data/eval_results/delta_ingest_foldin_gates_20261001.json"
WORK = Path("/home/vscode/work/delta_ingest/foldin_gates")
SEED = 20261001
N_SAMPLE = 10_000


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _head() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()


def _hwm_gb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return round(int(line.split()[1]) / 1024 ** 2, 3)
    return 0.0


def _load() -> dict:
    if RESULTS.exists():
        return json.loads(RESULTS.read_text())
    return {"measurement": "doc 10 §3 fold-in prerequisite gates G2 (routing) and G6 (encoder calibration)",
            "script": "scripts/experiments/eval_delta_ingest_foldin_gates.py",
            "prereg": "docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md"}


def _save(d: dict) -> None:
    tmp = RESULTS.with_name(RESULTS.name + ".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    os.replace(tmp, RESULTS)


def cmd_g2_routing(a) -> None:
    manifest = next(p for p in SHARD_MANIFEST_LADDER if p.exists())
    shards = json.loads(manifest.read_text())["shards"]
    rng = np.random.default_rng(SEED)
    per = []
    t0 = time.perf_counter()
    for pos, rec in enumerate(shards):
        s = int(rec.get("shard", pos))
        d = REPO / rec["mmap_dir"]
        offs = np.memmap(d / "document_mapping_offsets.bin", dtype="<u8", mode="r")
        n = len(offs) - 1
        ords = np.sort(rng.choice(n, size=N_SAMPLE, replace=False))
        fd = os.open(d / "document_mapping_strings.bin", os.O_RDONLY)
        miss, hist, examples = 0, [0] * ROUTE_SHARDS, []
        try:
            for o in ords.tolist():
                lo, hi = int(offs[o]), int(offs[o + 1])
                did = os.pread(fd, hi - lo, lo).decode("utf-8")
                r = route_shard(did)
                hist[r] += 1
                if r != s:
                    miss += 1
                    if len(examples) < 10:
                        examples.append({"ordinal": o, "id": did, "routes_to": r})
        finally:
            os.close(fd)
        per.append({"shard": s, "mmap_dir": rec["mmap_dir"], "n_docs_mapping": n,
                    "n_docs_manifest": rec.get("n_docs"), "sampled": int(len(ords)),
                    "routed_to_own_shard": N_SAMPLE - miss, "misses": miss,
                    "route_histogram": hist, "miss_examples": examples})
        del offs
        print(f"shard {s}: {N_SAMPLE - miss}/{N_SAMPLE}", flush=True)
    total_miss = sum(p["misses"] for p in per)
    d = _load()
    d["G2_routing"] = {
        "date": _now(), "git_head": _head(), "manifest": str(manifest.relative_to(REPO)),
        "rule": f"spike/delta_ingest/routing.route_shard: blake2b-8('{ROUTE_SEED}' + id) mod {ROUTE_SHARDS} "
                "(= scripts/seismic_testbed/shard_spool.py shard_id)",
        "sampling": f"numpy default_rng({SEED}); per shard in manifest order rng.choice(n, {N_SAMPLE}, "
                    "replace=False), sorted; ids read from document_mapping_strings.bin at "
                    "document_mapping_offsets.bin[o]..[o+1]",
        "bar": "10,000 / 10,000 per shard, all 8 shards (doc 10 §3 G2, frozen)",
        "per_shard": per, "total_sampled": N_SAMPLE * len(per), "total_misses": total_miss,
        "verdict": "HOLDS" if total_miss == 0 and len(per) == 8 else "FAILS",
        "seconds": round(time.perf_counter() - t0, 1), "peak_rss_gb": _hwm_gb(),
        "lock": "shared /tmp/sfu_latency_measure.lock", "timings_valid": False}
    _save(d)
    print(json.dumps({k: v for k, v in d["G2_routing"].items() if k != "per_shard"}, indent=1))


def cmd_g2_backfill(a) -> None:
    from spike.delta_ingest.ledger import IngestLedger
    src = Path(a.ledger)
    WORK.mkdir(parents=True, exist_ok=True)
    dst = WORK / f"backfill_copy_{src.parent.parent.name}_{src.parent.name}.sqlite"
    if dst.exists():
        dst.unlink()
    st_before = src.stat()
    s = sqlite3.connect(f"file:{src}?mode=ro&immutable=1", uri=True)
    t = sqlite3.connect(str(dst))
    s.backup(t)
    s.close()
    t.close()
    st_after = src.stat()
    led = IngestLedger(dst)
    had = led.has_routes
    t0 = time.perf_counter()
    out = led.backfill_routes()
    secs = time.perf_counter() - t0
    bad = sum(1 for i, r in led.db.execute("SELECT id, route_shard FROM docs") if r != route_shard(i))
    counts = led.routed_live_counts()
    again = led.backfill_routes()
    led.close()
    d = _load()
    d.setdefault("G2_backfill", []).append({
        "date": _now(), "git_head": _head(), "source_ledger": str(src),
        "source_unchanged": (st_before.st_size, st_before.st_mtime_ns) == (st_after.st_size, st_after.st_mtime_ns),
        "copy": str(dst), "copy_had_route_columns": had, "backfill": out, "seconds": round(secs, 2),
        "rows_mismatching_route_shard": bad, "live_per_routed_shard": counts,
        "second_backfill": again})
    _save(d)
    print(json.dumps(d["G2_backfill"][-1], indent=1))


def cmd_g6(a) -> None:
    sys.path.insert(0, str(REPO / "scripts" / "experiments"))
    from lib.thinclient.abstracts import AbstractStore
    from spike.delta_ingest.base_vectors import BaseVectorStore
    from spike.delta_ingest.encode import make_encoder
    from spike.delta_ingest.seed import base_record, resolve_meta
    twin = Path("/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap")
    locators = Path("/home/vscode/work/delta_ingest/O14/locators")
    index_root = REPO / "data/thinclient_index"
    store = BaseVectorStore([twin], locators)
    sh = store.shards[0]
    meta = sqlite3.connect(f"file:{resolve_meta(index_root)}?mode=ro", uri=True, timeout=60)
    mrows = meta.execute("SELECT id, title, doi, year, type, is_oa, section FROM docs WHERE id > ? "
                         "ORDER BY id LIMIT ?", (a.start_id, a.scan)).fetchall()
    meta.close()
    wn = np.array([r[0] for r in mrows], dtype=np.int64)
    pos = np.searchsorted(sh.wnum, wn)
    ok = (pos < len(sh.wnum)) & (sh.wnum[np.minimum(pos, len(sh.wnum) - 1)] == wn)
    mrows = [r for r, k in zip(mrows, ok.tolist()) if k]
    sel = [r for r in mrows if r[6] == a.section]
    ab = AbstractStore(index_root / "sections" / a.section / "abstracts.sqlite").fetch([f"W{r[0]}" for r in sel])
    recs = [base_record(f"W{r[0]}", r[1], r[2], r[3], r[4], r[5], ab[f"W{r[0]}"])
            for r in sel if f"W{r[0]}" in ab][: min(a.n, 2000)]
    base_vecs, refused = store.vectors([r.id for r in recs])
    recs = [r for r in recs if r.id in base_vecs]
    enc = make_encoder(a.backend, 64, "cuda")
    owner = getattr(enc, "__self__", None)
    new = []
    t0 = time.perf_counter()
    for k in range(0, len(recs), 64):
        new += enc([r.encoder_text() for r in recs[k:k + 64]])
    enc_s = time.perf_counter() - t0
    if len(new) != len(recs) or not any(new):
        sys.exit("encoder returned nothing — model not loaded")
    nb = np.array([len(base_vecs[r.id]) for r in recs], dtype=np.float64)
    nn = np.array([len(v) for v in new], dtype=np.float64)
    lb = np.array([np.sqrt(sum(float(x) ** 2 for x in base_vecs[r.id].values())) for r in recs])
    ln = np.array([np.sqrt(sum(float(x) ** 2 for x in v.values())) for v in new])
    l1b = np.array([sum(float(x) for x in base_vecs[r.id].values()) for r in recs])
    l1n = np.array([sum(float(x) for x in v.values()) for v in new])
    ratio_l2 = ln / lb
    rng = np.random.default_rng(0)
    boot = [float(np.mean(ratio_l2[rng.integers(0, len(ratio_l2), len(ratio_l2))])) for _ in range(10000)]
    d = _load()
    d["G6_encoder_calibration"] = {
        "date": _now(), "git_head": _head(),
        "selection": f"O14 gpu-check selection: meta rows id > {a.start_id} in id order (LIMIT {a.scan}), "
                     f"kept if in shard 0 (twin locator) and section {a.section} with a sidecar abstract; "
                     "<= 2,000 docs",
        "text_unchanged_basis": "encoder input = DocRecord.encoder_text() of the seed's base record (meta title + "
                                "sidecar abstract), i.e. the same text the stored base vector was built from",
        "docs": len(recs), "store_refusals": len(refused),
        "encoder_backend_requested": a.backend, "encoder_class": type(owner).__name__ if owner is not None else None,
        "stored": "twin f16 forward vector of shard 0 (BaseVectorStore, exact)",
        "nnz_stored_mean": round(float(nb.mean()), 3), "nnz_reencoded_mean": round(float(nn.mean()), 3),
        "nnz_ratio_of_means": round(float(nn.mean() / nb.mean()), 5),
        "l2_stored_mean": round(float(lb.mean()), 5), "l2_reencoded_mean": round(float(ln.mean()), 5),
        "l2_ratio_of_means": round(float(ln.mean() / lb.mean()), 5),
        "l2_ratio_per_doc_mean": round(float(ratio_l2.mean()), 5),
        "l2_ratio_per_doc_p1_p50_p99": [round(float(np.percentile(ratio_l2, p)), 5) for p in (1, 50, 99)],
        "l2_ratio_per_doc_mean_ci95_bootstrap": [round(float(np.percentile(boot, 2.5)), 5),
                                                 round(float(np.percentile(boot, 97.5)), 5)],
        "l1_stored_mean": round(float(l1b.mean()), 4), "l1_reencoded_mean": round(float(l1n.mean()), 4),
        "bar": "none (doc 10 G6 is recorded, not gated on a value)",
        "encode_seconds": round(enc_s, 2), "timings_valid": False, "peak_rss_gb": _hwm_gb(),
        "lock": "shared /tmp/sfu_latency_measure.lock"}
    _save(d)
    print(json.dumps(d["G6_encoder_calibration"], indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["g2-routing", "g2-backfill", "g6-calib"])
    ap.add_argument("--ledger")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--scan", type=int, default=60000)
    ap.add_argument("--start-id", type=int, default=4000000000)
    ap.add_argument("--section", default="social_sciences__recent")
    ap.add_argument("--backend", default="auto")
    a = ap.parse_args()
    {"g2-routing": cmd_g2_routing, "g2-backfill": cmd_g2_backfill, "g6-calib": cmd_g6}[a.cmd](a)


if __name__ == "__main__":
    main()
