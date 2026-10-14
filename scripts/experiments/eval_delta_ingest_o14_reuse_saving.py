"""O14 measurements, 2026-10-01 (third wave, agent FIX):
docs/delta_ingest/02_DESIGN.md §3.1 O14; code spike/delta_ingest/base_vectors.py.

(a) encode time saved by base-vector reuse, reuse OFF vs ON, on the M7 primary
    hot subset (partition 2026-09-15/part_0001, min_year 2015 slice, in-base
    docs seeded in the M7 seed ledger copy = 9,965 docs; the M7/seed numbers:
    8,047 content-updated, 2,517 encode-text changed, 5,530 content-only).
    Each arm runs the ingest-path functions the CLI's `flush_batch` calls
    (`IngestLedger.classify` -> `reusable_sparse` -> [ON: `reusable_base_sparse`]
    -> `ensure_sparse`), on a fresh copy of the seeded ledger, in ONE process
    with ONE encoder (warm-up first), order OFF, ON, OFF (drift check).
    Reported: docs sent to the encoder, encoder wall seconds, base lookup
    seconds, end-to-end seconds (lookup + encode), saving.
(b) do reused vectors give the SAME served dotvbyte codes as the base copy?
    >= 20,000 shard-0 rows (seeded random sample) are read with
    `BaseVectorStore.vectors` (the reuse reader), written as the delta build's
    SEISMIC jsonl (`DocRecord.seismic_line`), built with the delta chain
    (`generation.build_seismic_shard`: stock -> c1a f16 -> dotvbyte v2
    per-doc), and each doc's dotvbyte v2 record is DECODED from both the
    delta shard and the served base shard (`global_shard0of8.dotvbyte.e5.v2.mmap`)
    to {token: u8 code} + the f16 vmax header (component ids mapped back
    through each shard's `forward_encoder.bin` inverse mapping and
    `token_to_id_map.bin`). A doc counts as equal iff nnz, vmax bits and every
    (token, u8) pair are equal.
(c) locators for shards 1-7 (only if (a) shows a saving worth it):
    `base_vectors.build_locator` per shard, outputs under
    /home/vscode/work/delta_ingest/fix/locators, size + seconds per shard.

Subcommands: prepare | encode-saving | codes | locators | record
Results: data/eval_results/delta_ingest_O14_reuse_saving_20261001.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))
os.environ["SFU_DELTA_ROOT"] = ""

from spike.delta_ingest.base_vectors import (BaseVectorStore, build_locator,  # noqa: E402
                                             load_token_map, reusable_base_sparse)
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import DocRecord, canonical_id, normalize_openalex_work  # noqa: E402

PART = "/var/tmp/sfu_delta_B_20260929/works_updated_date=2026-09-15_part_0001.gz"
SEED_LEDGER = Path("/home/vscode/work/delta_ingest/seed/ledger_primary.sqlite")
WORK = Path("/home/vscode/work/delta_ingest/fix/o14")
TWIN0 = Path("/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap")
LOC0 = Path("/home/vscode/work/delta_ingest/O14/locators")
LOCS = Path("/home/vscode/work/delta_ingest/fix/locators")
PLAN01 = REPO / "data/seismic_150m/index/plan01"
SERVED0 = PLAN01 / "global_shard0of8.dotvbyte.e5.v2.mmap"
STAGED0 = Path("/var/tmp/seismic_stage/global_shard0of8.dotvbyte.e5.v2.mmap")
RESULTS = REPO / "data/eval_results/delta_ingest_O14_reuse_saving_20261001.json"
MIN_YEAR = 2015


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def head() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def hwm_gb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return round(int(line.split()[1]) / 1024 ** 2, 3)
    return float("nan")


def load_res() -> dict:
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else {
        "measurement": "O14 base-vector reuse: encode time saved, served dotvbyte code equality, "
                       "locators for shards 1-7",
        "script": str(Path(__file__).relative_to(REPO)), "bar": "none pre-registered"}


def save_res(key: str, val: dict) -> None:
    d = load_res()
    d[key] = val
    RESULTS.write_text(json.dumps(d, indent=1))
    print(json.dumps(val, indent=1))


def gpu_apps() -> list[str]:
    r = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                        "--format=csv,noheader"], capture_output=True, text=True)
    return [x for x in r.stdout.strip().splitlines() if x]


def gpu_util() -> str:
    r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                        "--format=csv,noheader"], capture_output=True, text=True)
    return r.stdout.strip()


def cmd_prepare(a) -> None:
    """Records of the M7 primary hot subset: in-slice at min_year 2015 and
    seeded in the M7 seed ledger (seeded => in base, hot section)."""
    led = IngestLedger(SEED_LEDGER)
    seeded = {f"W{r[0]}" for r in led.db.execute("SELECT id FROM base_hashes")}
    led.close() if hasattr(led, "close") else None
    t0 = time.time()
    out = []
    with gzip.open(PART, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                w = json.loads(line)
            except json.JSONDecodeError:
                continue
            year = w.get("publication_year")
            wid = canonical_id("openalex", w.get("id") or "")
            if wid not in seeded:
                continue
            if isinstance(year, int) and year < MIN_YEAR:
                continue
            rec = normalize_openalex_work(w, source="openalex_snapshot")
            if rec is not None:
                out.append(rec)
    WORK.mkdir(parents=True, exist_ok=True)
    p = WORK / "primary_seeded_2015.jsonl"
    p.write_text("".join(r.to_json() + "\n" for r in out))
    save_res("prepare", {"date": now(), "head": head(), "partition": PART, "min_year": MIN_YEAR,
                         "seed_ledger": str(SEED_LEDGER), "seeded_ids": len(seeded),
                         "records": len(out), "records_file": str(p),
                         "seconds": round(time.time() - t0, 1)})


def _records() -> list[DocRecord]:
    return [DocRecord.from_json(x) for x in (WORK / "primary_seeded_2015.jsonl").read_text().splitlines() if x]


def _arm(name: str, records: list[DocRecord], encoder, store) -> dict:
    d = WORK / f"arm_{name}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    shutil.copy2(SEED_LEDGER, d / "ledger.sqlite")
    led = IngestLedger(d / "ledger.sqlite")
    recs = [DocRecord.from_json(r.to_json()) for r in records]
    from spike.delta_ingest.encode import ensure_sparse
    t_all = time.perf_counter()
    in_base = {r.id: True for r in recs}
    cls = led.classify(recs, in_base)
    todo = cls["new"] + cls["updated"]
    reusable = led.reusable_sparse(todo)
    t0 = time.perf_counter()
    refusals: dict = {}
    n_base = 0
    if store is not None:
        from_base, refusals = reusable_base_sparse(
            led, [r for r in todo if r.id not in reusable and not r.sparse_field], store)
        reusable.update(from_base)
        n_base = len(from_base)
    lookup_s = time.perf_counter() - t0
    gpu_mid = gpu_apps()
    stats = ensure_sparse(todo, encoder, reusable, a_batch)
    total_s = time.perf_counter() - t_all
    return {"arm": name, "records": len(recs), "unchanged": len(cls["unchanged"]),
            "updated": len(cls["updated"]), "new": len(cls["new"]), "todo": len(todo),
            "reused_ledger": len(reusable) - n_base, "reused_base": n_base, "base_refusals": refusals,
            "encoded": stats["encoded"], "missing": stats["missing"],
            "encode_seconds": stats["encode_seconds"], "base_lookup_seconds": round(lookup_s, 3),
            "classify_to_vectors_seconds": round(total_s, 3),
            "encode_docs_per_s": round(stats["encoded"] / stats["encode_seconds"], 1)
            if stats["encode_seconds"] else None,
            "gpu_apps_during": gpu_mid}


a_batch = 64


def cmd_encode_saving(a) -> None:
    global a_batch
    a_batch = a.batch
    from spike.delta_ingest.encode import make_encoder
    records = _records()
    if a.limit:
        records = records[: a.limit]
    gpu_before = gpu_apps()
    t0 = time.perf_counter()
    enc = make_encoder(a.backend, a.batch, a.device)
    init_s = time.perf_counter() - t0
    owner = getattr(enc, "__self__", None)
    warm = [r.encoder_text() for r in records[: a.batch * a.warmup_batches]]
    t0 = time.perf_counter()
    for i in range(0, len(warm), a.batch):
        v = enc(warm[i:i + a.batch])
    warm_s = time.perf_counter() - t0
    if not v or not any(v):
        sys.exit("encoder returned nothing — model not loaded")
    shard_dirs = [TWIN0] + [PLAN01 / f"global_shard{k}of8.mmap" for k in a.extra_shards]
    loc_dir = LOC0 if not a.extra_shards else LOCS
    if a.extra_shards:
        for p in (LOC0 / f"{TWIN0.name}.locator").iterdir():
            (LOCS / f"{TWIN0.name}.locator").mkdir(parents=True, exist_ok=True)
            dst = LOCS / f"{TWIN0.name}.locator" / p.name
            if not dst.exists():
                shutil.copy2(p, dst)
    store = BaseVectorStore(shard_dirs, loc_dir)
    arms = []
    for name in a.order.split(","):
        arms.append(_arm(name + f"_{len(arms)}", records, enc, store if name == "on" else None))
        print(json.dumps({k: v for k, v in arms[-1].items() if k != "gpu_apps_during"}), flush=True)
    off = [x for x in arms if x["arm"].startswith("off")]
    on = [x for x in arms if x["arm"].startswith("on")]
    off_enc = float(np.mean([x["encode_seconds"] for x in off]))
    off_tot = float(np.mean([x["classify_to_vectors_seconds"] for x in off]))
    on_tot = float(np.mean([x["classify_to_vectors_seconds"] for x in on]))
    res = {"date_start": now(), "head": head(), "encoder_class": type(owner).__name__ if owner else None,
           "encoder_backend_label": getattr(owner, "backend", None),
           "encoder_runtime_backend": getattr(owner, "runtime_backend", None),
           "batch": a.batch, "encoder_init_seconds": round(init_s, 2), "warmup_docs": len(warm),
           "warmup_seconds": round(warm_s, 2), "base_shards": [str(s) for s in shard_dirs],
           "gpu_apps_before": gpu_before, "gpu_util_after": gpu_util(), "arms": arms,
           "off_mean_encode_seconds": round(off_enc, 3),
           "on_mean_encode_seconds": round(float(np.mean([x["encode_seconds"] for x in on])), 3),
           "off_mean_end_to_end_seconds": round(off_tot, 3), "on_mean_end_to_end_seconds": round(on_tot, 3),
           "end_to_end_saving_fraction": round(1 - on_tot / off_tot, 4) if off_tot else None,
           "encoded_off": off[0]["encoded"], "encoded_on": on[0]["encoded"],
           "peak_rss_gb": hwm_gb()}
    res["device"] = a.device
    res["records_limit"] = a.limit or None
    key = ("encode_saving" if not a.extra_shards else "encode_saving_8shards") + (
        "" if a.device == "cuda" else f"_{a.device}")
    if a.lock_note:
        res["lock"] = a.lock_note
    save_res(key, res)


def _read_u64s(path: Path, i: int, n: int) -> np.ndarray:
    with open(path, "rb") as fh:
        fh.seek(8 * i)
        return np.frombuffer(fh.read(8 * n), dtype="<u8")


def _encoder_maps(dirp: Path) -> tuple[int, np.ndarray | None, np.ndarray | None]:
    b = (dirp / "forward_encoder.bin").read_bytes()
    dim = struct.unpack_from("<Q", b, 0)[0]
    off = 8
    out = []
    for _ in range(2):
        tag = b[off]
        off += 1
        if tag == 0:
            out.append(None)
            continue
        n = struct.unpack_from("<Q", b, off)[0]
        off += 8
        out.append(np.frombuffer(b, dtype="<u2", count=n, offset=off).copy())
        off += 2 * n
    if off != len(b):
        raise ValueError(f"{dirp}/forward_encoder.bin: parsed {off} of {len(b)} bytes")
    return dim, out[0], out[1]


def decode_v2(rec: bytes) -> tuple[int, list[int], list[int]]:
    """One dotvbyte v2 record -> (vmax f16 bits, permuted components, u8 codes),
    components in record order (sorted permuted ids). Layout:
    vectorium_fork/src/encoders/dotvbyte_fixedu8.rs push_vector_inner, N = 8."""
    n8 = 8
    length, vmax = struct.unpack_from("<HH", rec, 0)
    pos = 4
    r = length % n8
    nch = length - r
    rem_c = list(struct.unpack_from(f"<{r}H", rec, pos))
    pos += 2 * r
    rem_v = list(rec[pos:pos + r])
    pos += r
    bits = rec[pos:pos + nch // n8]
    pos += nch // n8
    gaps = []
    for k in range(nch):
        big = (bits[k // n8] >> (n8 - (k % n8) - 1)) & 1
        if big:
            gaps.append(struct.unpack_from("<H", rec, pos)[0])
            pos += 2
        else:
            gaps.append(rec[pos])
            pos += 1
    pos = (pos + 7) // 8 * 8
    vals = list(rec[pos:pos + nch])
    gaps += rem_c
    comps = []
    acc = 0
    for g in gaps:
        acc += g
        comps.append(acc)
    return vmax, comps, vals + rem_v


class DvShard:
    def __init__(self, d: Path, locator: Path | None):
        self.d = d
        _, self.mapping, self.inverse = _encoder_maps(d)
        self.id2tok = load_token_map(d)
        self.fd = os.open(d / "forward_data.bin", os.O_RDONLY)
        self.offs_path = d / "forward_offsets.bin"
        if locator is not None:
            self.wnum = np.load(locator / "wnum.npy", mmap_mode="r")
            self.row = np.load(locator / "row.npy", mmap_mode="r")

    def row_of(self, wid: str) -> int | None:
        w = int(wid[1:])
        i = int(np.searchsorted(self.wnum, w))
        return int(self.row[i]) if i < len(self.wnum) and int(self.wnum[i]) == w else None

    def raw(self, row: int) -> bytes:
        a, b = _read_u64s(self.offs_path, row, 2).tolist()
        return os.pread(self.fd, 8 * (b - a), 8 * a)

    def codes(self, row: int) -> tuple[int, dict[str, int]]:
        vmax, comps, vals = decode_v2(self.raw(row))
        if self.inverse is not None:
            comps = [int(self.inverse[c]) for c in comps]
        return vmax, {self.id2tok[c]: v for c, v in zip(comps, vals)}


def py_codes(vec: dict[str, float]) -> tuple[int, dict[str, int]]:
    """The converter's per-doc quantiser in f32 (mmap_io push_encoded_per_doc)."""
    v = np.array([np.float16(x) for x in vec.values()], dtype=np.float16).astype(np.float32)
    vmax16 = np.float16(min(float(v.max()), 65504.0)) if v.max() > 0 else np.float16(1.0)
    vm = np.float32(vmax16)
    x = (v / vm * np.float32(255.0)).astype(np.float32)
    fl = np.floor(x)
    r = np.where(x - fl >= np.float32(0.5), fl + 1, fl)
    q = np.clip(r, 0, 255).astype(np.uint8)
    return int(vmax16.view(np.uint16)), dict(zip(vec.keys(), q.tolist()))


def cmd_codes(a) -> None:
    from spike.delta_ingest.generation import build_seismic_shard
    store = BaseVectorStore([TWIN0], LOC0)
    sh = store.shards[0]
    rng = random.Random(a.seed)
    rows = sorted(rng.sample(range(sh.n_docs), a.n))
    ids = [sh.doc_id(r) for r in rows]
    t0 = time.perf_counter()
    vecs, refused = store.vectors(ids)
    read_s = time.perf_counter() - t0
    out = WORK / "codes"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    jsonl = out / "reused.jsonl"
    with open(jsonl, "w") as fh:
        for i in ids:
            if i in vecs:
                fh.write(DocRecord(id=i, sparse_field=vecs[i]).seismic_line() + "\n")
    t0 = time.perf_counter()
    info = build_seismic_shard(jsonl, out / "reused", a.threads)
    build_s = time.perf_counter() - t0
    if info.get("format") != "dotvbyte_fixedu8_v2":
        sys.exit(f"delta chain did not reach dotvbyte v2: {json.dumps(info)[:800]}")
    dv = Path(info["mmap_dir"])
    delta = DvShard(dv, None)
    dmo = np.fromfile(dv / "document_mapping_offsets.bin", dtype="<u8")
    dms = (dv / "document_mapping_strings.bin").read_bytes()
    drow = {dms[int(dmo[k]):int(dmo[k + 1])].decode(): k for k in range(len(dmo) - 1)}
    src = STAGED0 if a.staged else SERVED0
    loc = LOCS / f"{src.name}.locator"
    if not loc.exists():
        build_locator(src, loc)
    served = DvShard(src, loc)
    authority = DvShard(SERVED0, None) if a.staged else None
    n_eq = n_cmp = n_missing = n_vmax = n_nnz = n_tok = n_val = n_py = n_auth_mismatch = 0
    examples = []
    t0 = time.perf_counter()
    for i in ids:
        if i not in vecs:
            continue
        sr = served.row_of(i)
        if sr is None or i not in drow:
            n_missing += 1
            continue
        n_cmp += 1
        if authority is not None and authority.raw(sr) != served.raw(sr):
            n_auth_mismatch += 1
        bv, bc = served.codes(sr)
        dvv, dc = delta.codes(drow[i])
        pv, pc = py_codes(vecs[i])
        n_py += int((pv, pc) == (bv, bc))
        same = bv == dvv and bc == dc
        n_eq += int(same)
        if not same:
            n_vmax += int(bv != dvv)
            n_nnz += int(len(bc) != len(dc))
            n_tok += int(set(bc) != set(dc))
            n_val += int(set(bc) == set(dc) and any(bc[t] != dc[t] for t in bc))
            if len(examples) < 5:
                examples.append({"id": i, "vmax_base": bv, "vmax_delta": dvv, "nnz_base": len(bc),
                                 "nnz_delta": len(dc)})
    cmp_s = time.perf_counter() - t0
    reasons: dict = {}
    for x in refused.values():
        reasons[x] = reasons.get(x, 0) + 1
    save_res("served_codes", {
        "date": now(), "head": head(), "sample_rows": a.n, "seed": a.seed, "twin": str(TWIN0),
        "served_shard_read": str(src), "authority_shard": str(SERVED0),
        "records_checked_byte_equal_vs_authority": None if authority is None else n_cmp - n_auth_mismatch,
        "records_byte_mismatch_vs_authority": None if authority is None else n_auth_mismatch,
        "reused_exact": len(vecs), "refused": reasons, "compared": n_cmp, "missing": n_missing,
        "docs_codes_equal": n_eq, "docs_differ": n_cmp - n_eq,
        "differ_vmax": n_vmax, "differ_nnz": n_nnz, "differ_token_set": n_tok, "differ_u8_value": n_val,
        "python_quantiser_equals_served": n_py, "examples": examples,
        "delta_chain": {k: v for k, v in info.items() if k != "stages"} | {"stages": info.get("stages")},
        "read_seconds": round(read_s, 2), "build_seconds": round(build_s, 2),
        "compare_seconds": round(cmp_s, 2), "timings_valid": False, "peak_rss_gb": hwm_gb(),
        "method": "decode dotvbyte v2 records of both shards (decode_v2) -> {token: u8} + vmax bits"})


def cmd_locators(a) -> None:
    LOCS.mkdir(parents=True, exist_ok=True)
    rows = []
    for k in a.shards:
        d = PLAN01 / f"global_shard{k}of8.mmap"
        out = LOCS / f"{d.name}.locator"
        t0 = time.perf_counter()
        info = build_locator(d, out)
        dt = time.perf_counter() - t0
        size = sum(p.stat().st_size for p in out.iterdir())
        rows.append({**info, "seconds": round(dt, 1), "bytes": size})
        print(json.dumps(rows[-1]), flush=True)
    d = load_res()
    prev = d.get("locators", {}).get("shards", [])
    done = {r["shard"] for r in rows}
    save_res("locators", {"date": now(), "head": head(), "source": "data/seismic_150m/index/plan01 "
                          "f16 twins over 9p (read-only)", "out_dir": str(LOCS),
                          "shards": [r for r in prev if r["shard"] not in done] + rows,
                          "peak_rss_gb": hwm_gb(), "timings_valid": False,
                          **({"lock": a.lock_note} if a.lock_note else {})})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "encode-saving", "codes", "locators"])
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--order", default="off,on,off")
    ap.add_argument("--extra-shards", type=int, nargs="*", default=[])
    ap.add_argument("--shards", type=int, nargs="*", default=[1, 2, 3, 4, 5, 6, 7])
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--lock-note", default="")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--warmup-batches", type=int, default=10)
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    {"prepare": cmd_prepare, "encode-saving": cmd_encode_saving, "codes": cmd_codes,
     "locators": cmd_locators}[a.cmd](a)


if __name__ == "__main__":
    main()
