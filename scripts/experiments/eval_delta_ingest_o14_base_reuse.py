"""O14 — base-vector reuse: reader exactness on a real shard twin + (after the
latency lock) a small GPU check of base vector vs re-encode for text-unchanged
base docs.

docs/delta_ingest/02_DESIGN.md §3.1 O14; code `spike/delta_ingest/base_vectors.py`.
Doc 08 §0.3 flags 87.6 (base shard) vs 122.5 (S0-1 re-encodes) nnz/doc "to
verify first": `gpu-check` re-encodes the SAME text the seed hashes (meta title
+ sidecar abstract) and compares with the stored f16 forward vector.

Subcommands (all read-only on the shard twin and on data/; writes only under
WORK and the results file):
  locator       build the id->row locator for the local twin copy of shard 0
  verify-reader sha256 of the twin's small files vs the 2026-09-29 listing;
                N random rows: BaseVectorStore.vectors(id) vs a direct read of
                the same row (bit-equal f16), refusal counts, nnz stats
  gpu-check     <= 2,000 docs of shard 0 whose section sidecar is local:
                base text -> encoder (GPU) -> compare with the stored vector.
                ONLY after 06:10Z 2026-10-01 (latency lock); timings invalid.

Usage
  nice -n 19 taskset -c 12-15 env OMP_NUM_THREADS=2 .venv/bin/python3 \
      scripts/experiments/eval_delta_ingest_o14_base_reuse.py locator|verify-reader|gpu-check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest.base_vectors import BaseVectorStore, build_locator  # noqa: E402

TWIN = Path("/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap")
WORK = Path("/home/vscode/work/delta_ingest/O14")
LOCATORS = WORK / "locators"
SHA_LIST = REPO / "docs/infrastructure/seismic_150m_sha256_2026-09-29.txt"
INDEX_ROOT = REPO / "data/thinclient_index"
RESULTS = REPO / "data/eval_results/delta_ingest_O14_base_reuse_20261001.json"
LOCK_END_UTC = "2026-10-01T06:10:00Z"


def _load() -> dict:
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else {
        "measurement": "O14 base-vector reuse (docs/delta_ingest/02_DESIGN.md §3.1 O14)",
        "bar": "none pre-registered; exact-or-refuse is a correctness property, recorded",
        "script": "scripts/experiments/eval_delta_ingest_o14_base_reuse.py",
        "code": "spike/delta_ingest/base_vectors.py", "twin": str(TWIN)}


def _save(d: dict) -> None:
    RESULTS.write_text(json.dumps(d, indent=1))


def _head() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _hwm_gb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return round(int(line.split()[1]) / 1024 ** 2, 3)
    return float("nan")


def cmd_locator(a) -> None:
    t0 = time.perf_counter()
    info = build_locator(TWIN, LOCATORS / f"{TWIN.name}.locator")
    d = _load()
    d["locator"] = {**info, "seconds": round(time.perf_counter() - t0, 1), "peak_rss_gb": _hwm_gb(),
                    "date": _now(), "git_head": _head(), "timings_valid": False}
    _save(d)
    print(json.dumps(d["locator"], indent=1))


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while b := fh.read(1 << 22):
            h.update(b)
    return h.hexdigest()


def cmd_verify(a) -> None:
    want = {}
    for line in SHA_LIST.read_text().splitlines():
        if "/global_shard0of8.mmap/" in line:
            h, name = line.split(" *", 1)
            want[Path(name).name] = h
    sha = {}
    for name in ("token_to_id_map.bin", "document_mapping_offsets.bin", "document_mapping_strings.bin",
                 "forward_offsets.bin", "config.json"):
        sha[name] = {"got": _sha(TWIN / name), "want": want.get(name)}
        sha[name]["match"] = sha[name]["got"] == sha[name]["want"]
    store = BaseVectorStore([TWIN], LOCATORS)
    sh = store.shards[0]
    n = sh.n_docs
    rng = random.Random(a.seed)
    rows = sorted(rng.sample(range(n), a.n))
    ids = [sh.doc_id(r) for r in rows]
    t0 = time.perf_counter()
    vecs, refused = store.vectors(ids)
    dt = time.perf_counter() - t0
    bit_equal = mismatch = 0
    nnz = []
    for r, i in zip(rows, ids):
        if i not in vecs:
            continue
        lo, hi = np.fromfile(TWIN / "forward_offsets.bin", dtype="<u8", count=2, offset=8 * r).tolist()
        comps = np.fromfile(TWIN / "forward_components.bin", dtype="<u2", count=hi - lo, offset=2 * lo)
        vals = np.fromfile(TWIN / "forward_values.bin", dtype="<f2", count=hi - lo, offset=2 * lo)
        v = vecs[i]
        got = np.array(list(v.values()), dtype=np.float32).astype(np.float16).view(np.uint16)
        toks = [sh.id2tok[c] for c in comps.tolist()]
        if list(v.keys()) == toks and got.tolist() == vals.view(np.uint16).tolist():
            bit_equal += 1
        else:
            mismatch += 1
        nnz.append(len(comps))
    reasons: dict[str, int] = {}
    for x in refused.values():
        reasons[x] = reasons.get(x, 0) + 1
    d = _load()
    d["verify_reader"] = {
        "date": _now(), "git_head": _head(), "sample_rows": a.n, "seed": a.seed, "shard_docs": n,
        "sha256_vs_2026_09_29_listing": sha,
        "reused_exact": len(vecs), "refused": reasons, "bit_equal_to_direct_read": bit_equal, "direct_read": "np.fromfile at the row offsets (independent of the store pread path)",
        "mismatch": mismatch, "nnz_mean": round(float(np.mean(nnz)), 2) if nnz else None,
        "nnz_max": int(max(nnz)) if nnz else None, "lookup_seconds": round(dt, 2),
        "per_doc_ms": round(1000 * dt / a.n, 3), "peak_rss_gb": _hwm_gb(), "timings_valid": False}
    _save(d)
    print(json.dumps(d["verify_reader"], indent=1))


def cmd_gpu(a) -> None:
    if _now() < LOCK_END_UTC and not (a.force or a.dry):
        sys.exit(f"gpu-check is allowed only after {LOCK_END_UTC} (latency lock)")
    from lib.thinclient.abstracts import AbstractStore
    from spike.delta_ingest.encode import make_encoder
    from spike.delta_ingest.seed import base_record, resolve_meta
    store = BaseVectorStore([TWIN], LOCATORS)
    sh = store.shards[0]
    meta = sqlite3.connect(f"file:{resolve_meta(INDEX_ROOT)}?mode=ro", uri=True, timeout=60)
    mrows = meta.execute("SELECT id, title, doi, year, type, is_oa, section FROM docs WHERE id > ? "
                         "ORDER BY id LIMIT ?", (a.start_id, a.scan)).fetchall()
    meta.close()
    wn = np.array([r[0] for r in mrows], dtype=np.int64)
    pos = np.searchsorted(sh.wnum, wn)
    in_shard = (pos < len(sh.wnum)) & (sh.wnum[np.minimum(pos, len(sh.wnum) - 1)] == wn)
    mrows = [r for r, ok in zip(mrows, in_shard.tolist()) if ok]
    side = INDEX_ROOT / "sections" / a.section / "abstracts.sqlite"
    sel = [r for r in mrows if r[6] == a.section]
    ab = AbstractStore(side).fetch([f"W{r[0]}" for r in sel])
    recs = [base_record(f"W{r[0]}", r[1], r[2], r[3], r[4], r[5], ab[f"W{r[0]}"])
            for r in sel if f"W{r[0]}" in ab][: min(a.n, 2000)]
    base_vecs, refused = store.vectors([r.id for r in recs])
    recs = [r for r in recs if r.id in base_vecs]
    if a.dry:
        print(json.dumps({"dry": True, "meta_rows_in_shard0": len(mrows), "in_section": len(sel),
                          "with_abstract": len(ab), "docs_to_compare": len(recs),
                          "store_refusals": len(refused), "peak_rss_gb": _hwm_gb()}))
        return
    enc = make_encoder(a.backend, 64, "cuda")
    owner = getattr(enc, "__self__", None)
    backend_cls = type(owner).__name__ if owner is not None else None
    t0 = time.perf_counter()
    new = []
    for k in range(0, len(recs), 64):
        new += enc([r.encoder_text() for r in recs[k:k + 64]])
    enc_s = time.perf_counter() - t0
    if len(new) != len(recs) or not any(new):
        sys.exit("encoder returned nothing — model not loaded")
    nb, nn, jac, cos, exact_doc, val_eq, val_tot, maxdiff = [], [], [], [], 0, 0, 0, 0.0
    for r, v in zip(recs, new):
        b = base_vecs[r.id]
        nb.append(len(b))
        nn.append(len(v))
        kb, kn = set(b), set(v)
        jac.append(len(kb & kn) / max(1, len(kb | kn)))
        dot = sum(b[t] * v[t] for t in kb & kn)
        cos.append(dot / (np.sqrt(sum(x * x for x in b.values())) * np.sqrt(sum(x * x for x in v.values())) or 1))
        same = kb == kn
        for t in kb & kn:
            e = np.float16(v[t]).view(np.uint16) == np.float16(b[t]).view(np.uint16)
            val_eq += int(e)
            val_tot += 1
            same &= bool(e)
            maxdiff = max(maxdiff, abs(float(np.float16(v[t])) - b[t]))
        exact_doc += int(same)
    d = _load()
    d["gpu_check"] = {
        "date": _now(), "git_head": _head(), "section": a.section, "rows_scanned": a.scan,
        "selection": f"meta rows id > {a.start_id} in id order (LIMIT scan), kept if in shard 0 and in section",
        "meta_rows_in_shard0": len(mrows), "in_section": len(sel), "docs_compared": len(recs),
        "store_refusals": refused and {k: list(refused.values()).count(k) for k in set(refused.values())},
        "encoder_backend_requested": a.backend, "encoder_class": backend_cls,
        "text": "DocRecord.encoder_text() of the seed's base record (meta title + sidecar abstract)",
        "nnz_base_mean": round(float(np.mean(nb)), 2), "nnz_reencode_mean": round(float(np.mean(nn)), 2),
        "nnz_ratio_reencode_over_base": round(float(np.mean(nn)) / float(np.mean(nb)), 4),
        "term_jaccard_mean": round(float(np.mean(jac)), 4), "term_jaccard_p5": round(float(np.percentile(jac, 5)), 4),
        "cosine_mean": round(float(np.mean(cos)), 5), "cosine_p1": round(float(np.percentile(cos, 1)), 5),
        "docs_bit_identical": exact_doc, "shared_term_values_f16_equal": val_eq,
        "shared_terms": val_tot, "max_abs_diff_shared_terms": round(maxdiff, 5),
        "encode_seconds": round(enc_s, 2), "timings_valid": False, "peak_rss_gb": _hwm_gb()}
    _save(d)
    print(json.dumps(d["gpu_check"], indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["locator", "verify-reader", "gpu-check"])
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--scan", type=int, default=60000)
    ap.add_argument("--start-id", type=int, default=4000000000)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--section", default="social_sciences__recent")
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry", action="store_true", help="gpu-check selection only, no encoder")
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    {"locator": cmd_locator, "verify-reader": cmd_verify, "gpu-check": cmd_gpu}[a.cmd](a)


if __name__ == "__main__":
    main()
