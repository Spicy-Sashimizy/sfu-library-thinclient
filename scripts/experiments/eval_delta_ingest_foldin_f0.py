#!/usr/bin/env python3
r"""Delta-ingest fold-in F0 (doc 10 §6 row F0): size dependence of ONE
consolidated generation's per-query tax. Written 2026-10-08, BEFORE any F0
number existed. Implementation readings: doc 10 addendum "2026-10-08 — F0
implementation readings" (committed before the first measured run).

---- doc 10 §6 row F0, verbatim (frozen 2e674773) ----
| **F0** | Size dependence of one consolidated generation's tax (calibrates (b)) | paired Δ(arm, n0) in-process as 09 §1.1, arms n0, n1 (160,347 docs, existing), g1M (one 1,000,000-doc generation of base docs re-ingested as updates with twin vectors, no GPU; corpus builder to write) | recorded; PASS-line for using a single consolidated generation as the long-lived sections tier: Δ(g1M) − Δ(n1) ≤ **8.0 ms** (CI upper bound). FAIL → the sections tier also needs a fold or a split, recorded | exclusive |
---- end verbatim ----

Corpus rule for g1M (fixed before the build; counts land in select.json and
build_g1M.json):
  U  every base doc of shard 0 that the closed in-place spike's Stage-0
     sample (10% of the 2026-06-17..09-15 OpenAlex `updated_date` part files,
     /home/vscode/work/inplace_update/stage0/) saw UPDATED and IN SLICE
     (partsout_f10/*.npz: rows >= 0 AND in_slice; 517,185 expected). Text =
     the snapshot record (the newest part that carries it), normalised by the
     product adapter `records.normalize_openalex_work`.
  F  fill to exactly 1,000,000: shard-0 base docs whose ordinal section is
     `social_sciences__recent` (the only section with a local abstract
     sidecar on this host) and that the sidecar holds, minus U, in a seeded
     permutation (seed 20261008). Text = base meta row + sidecar abstract via
     `seed.base_record` (the base-hash seed's record builder).
  Vectors for U and F = the doc's stored f16 vector in twin 0
  (`base_vectors.BaseVectorStore`, exact-or-refuse; a refused doc is
  dropped and counted, never re-encoded). No GPU.
  All 1,000,000 are staged with in_base=1 into a NEW ledger and frozen as ONE
  generation by the product `freeze_buffer` (layout per_base_section,
  seismic=True, base manifest = M4's, base ordinals = the C ordinal arrays so
  the superseded base copies go into a livedocs bitset).

Arms (M4F in-process design = 09 §1 / §1.1, parallel federation, separate
prime retriever, 1 warm-up + 2 measured passes, 120 topics of the M4 set):
  n0x   gate off + L4 (the stack lever that acts on the base)
  x1    m4/root_n1 (160,347 docs, 1 generation) + L3,L4,L5
  xg1M  f0/root_g1M (1,000,000 docs, 1 generation) + L3,L4,L5
Bar: the paired difference t(xg1M) - t(x1) per (pass, topic) — which equals
Δ(g1M, n0x) - Δ(n1, n0x) per unit — median with the 09 §1.1 topic-cluster
bootstrap 95% CI (2,000 resamples, seed 20261001); PASS iff the run is
complete and healthy AND the CI upper bound <= 8.0 ms. Coefficient c of
T = a + b·G + c·D = that median / 0.839653 (million docs added).

Subcommands (run with /home/vscode/work/venv_local/bin/python3, cwd = repo):
  select     U targets + F candidate order -> f0/select.json, u_targets.npz, f_order.npy
  extract    U snapshot records -> f0/upd/<part>.jsonl (8 workers, resumable)
  build      root_g1M (ledger + one generation + publish) -> f0/build_g1M.json
  inproc     the measured process (caller holds flock -x)
  summarize  -> data/eval_results/delta_ingest_foldin_f0_<date>.json key F0
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import resource
import sqlite3
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
F0 = Path("/home/vscode/work/delta_ingest/foldin/f0")
G1M_ROOT = F0 / "root_g1M"
STAGE0 = Path("/home/vscode/work/inplace_update/stage0")
TWIN0 = Path("/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap")
LOCATORS = Path("/home/vscode/work/delta_ingest/O14/locators")
ORDS = Path("/var/tmp/sfu_delta_C_20260929/ords")
INDEX_ROOT = REPO / "data/thinclient_index"
HOT = "social_sciences__recent"
SIDECAR_FLAT = INDEX_ROOT / "sections" / HOT / "abstracts.sqlite.flat"
TOTAL = 1_000_000
N1_DOCS = 160_347
SEED = 20261008
BOOT_SEED = 20261001
BAR_MS = 8.0
ARMS = ["n0x", "x1", "xg1M"]
LEVERS = ("L3", "L4", "L5")
RAW_FIELDS = ("arm", "pass", "topic", "position", "ms", "bm25f_ms", "splade_ms", "encode_ms", "traverse_ms",
              "shard_base_max_ms", "shard_delta_sum_ms", "majflt", "n")
WID_RE = re.compile(rb'"id":\s*"https://openalex\.org/W(\d+)"')


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    print(f"[{utc()}] {msg}", flush=True)


def dump_json(path: Path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str) + "\n")
    os.replace(tmp, path)


def _paths():
    for p in (str(REPO), str(REPO / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)


# ── selection ───────────────────────────────────────────────────────────────
def part_files(stage0: Path = STAGE0) -> list[Path]:
    """Stage-0 per-part outputs in name order (= updated_date order)."""
    return sorted(p for p in (stage0 / "partsout_f10").glob("*.npz") if not p.name.endswith(".route.npz"))


def u_targets(npz_paths: list[Path]) -> dict[str, np.ndarray]:
    """part stem -> W numbers routed to shard 0, in base and in slice."""
    out = {}
    for p in npz_paths:
        z = np.load(p)
        m = (z["rows"] >= 0) & z["in_slice"]
        out[p.stem] = np.asarray(z["num"][m], dtype=np.int64)
    return out


def lookup_sorted(keys: np.ndarray, table: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(positions, found) of `keys` in the sorted `table`; found is exact equality."""
    pos = np.searchsorted(table, keys)
    pos_c = np.minimum(pos, len(table) - 1)
    found = (pos < len(table)) & (np.asarray(table[pos_c]) == keys)
    return pos_c, found


def fill_order(twin_wnums: np.ndarray, ord_wids: np.ndarray, ord_section: np.ndarray, hot_code: int,
               sidecar_wids: np.ndarray, exclude: np.ndarray, seed: int = SEED) -> tuple[np.ndarray, dict]:
    """Candidates for F in seeded order: twin docs whose ordinal section is the
    hot code, held by the sidecar, not in `exclude`."""
    pos, in_ord = lookup_sorted(twin_wnums, ord_wids)
    sec = np.where(in_ord, np.asarray(ord_section[pos]), -1)
    _, in_side = lookup_sorted(twin_wnums, sidecar_wids)
    excl = np.isin(twin_wnums, exclude)
    keep = (sec == hot_code) & in_side & ~excl
    cand = np.sort(twin_wnums[keep])
    rng = np.random.default_rng(seed)
    order = cand[rng.permutation(len(cand))]
    stats = {"twin_w_docs": int(len(twin_wnums)), "not_in_ordinals": int((~in_ord).sum()),
             "hot_section": int((sec == hot_code).sum()), "hot_and_sidecar": int(((sec == hot_code) & in_side).sum()),
             "excluded_as_U": int(((sec == hot_code) & in_side & excl).sum()), "candidates": int(len(cand))}
    return order, stats


def cmd_select(a) -> int:
    F0.mkdir(parents=True, exist_ok=True)
    parts = part_files()
    if a.limit_parts:
        parts = parts[:a.limit_parts]
    tg = u_targets(parts)
    allu = np.unique(np.concatenate(list(tg.values()))) if tg else np.zeros(0, dtype=np.int64)
    np.savez(a.out_dir / "u_targets.npz", **tg)
    loc = np.load(LOCATORS / f"{TWIN0.name}.locator" / "wnum.npy", mmap_mode="r")
    twin = np.asarray(loc[:a.limit_twin] if a.limit_twin else loc)
    ord_wids = np.load(ORDS / "wids.npy", mmap_mode="r")
    ord_sec = np.load(ORDS / "section.npy", mmap_mode="r")
    codes = json.loads((ORDS / "ordinal_space.json").read_text())["codes"]["section"]
    side = np.load(SIDECAR_FLAT / "loc_wids.npy", mmap_mode="r")
    order, st = fill_order(twin, ord_wids, ord_sec, int(codes[HOT]), side, allu)
    np.save(a.out_dir / "f_order.npy", order)
    _, u_in_twin = lookup_sorted(allu, np.asarray(loc))
    rec = {"utc": utc(), "parts": len(parts), "u_rows_with_repeats": int(sum(len(v) for v in tg.values())),
           "u_unique": int(len(allu)), "u_in_twin0_locator": int(u_in_twin.sum()), "fill": st,
           "hot_section": HOT, "hot_code": int(codes[HOT]), "seed": SEED, "limit_twin": a.limit_twin,
           "limit_parts": a.limit_parts, "u_sha256": hashlib.sha256(allu.tobytes()).hexdigest()}
    dump_json(a.out_dir / "select.json", rec)
    log(json.dumps(rec))
    return 0


# ── extract (snapshot records for U) ────────────────────────────────────────
def scan_lines(lines, targets: set[int]):
    """Yield (wnum, line) for lines whose work id is in `targets`; the id is
    the first `"id": "https://openalex.org/W<n>"` on the line."""
    for line in lines:
        m = WID_RE.search(line)
        if m is None:
            continue
        w = int(m.group(1))
        if w in targets:
            yield w, line


def _extract_one(args) -> dict:
    gz_path, out_path, targets = args
    _paths()
    from spike.delta_ingest.records import normalize_openalex_work
    c = {"part": Path(gz_path).name, "matched": 0, "written": 0, "id_mismatch": 0, "not_in_slice": 0}
    if Path(str(out_path) + ".done").exists():
        c["skipped_done"] = True
        return c
    tset = set(int(x) for x in targets)
    tmp = Path(str(out_path) + ".tmp")
    t0 = time.time()
    with gzip.open(gz_path, "rb") as fh, open(tmp, "w") as out:
        for w, line in scan_lines(fh, tset):
            c["matched"] += 1
            r = normalize_openalex_work(json.loads(line), source="openalex_q1_stage0")
            if r is None:
                c["not_in_slice"] += 1
                continue
            if r.id != f"W{w}":
                c["id_mismatch"] += 1
                continue
            out.write(r.to_json() + "\n")
            c["written"] += 1
    os.replace(tmp, out_path)
    Path(str(out_path) + ".done").write_text(json.dumps(c))
    c["seconds"] = round(time.time() - t0, 1)
    return c


def cmd_extract(a) -> int:
    import multiprocessing as mp
    out = a.out_dir / "upd"
    out.mkdir(parents=True, exist_ok=True)
    z = np.load(a.out_dir / "u_targets.npz")
    jobs = []
    for stem in sorted(z.files):
        gz = STAGE0 / "parts" / f"works_{stem}.gz"
        if not gz.exists():
            log(f"MISSING part {gz}")
            return 2
        if len(z[stem]):
            jobs.append((str(gz), str(out / f"{stem}.jsonl"), z[stem]))
    t0 = time.time()
    with mp.get_context("fork").Pool(a.workers) as pool:
        res = list(pool.imap_unordered(_extract_one, jobs))
    tot = {k: sum(r.get(k, 0) for r in res) for k in ("matched", "written", "id_mismatch", "not_in_slice")}
    rec = {"utc": utc(), "parts": len(jobs), "workers": a.workers, "wall_s": round(time.time() - t0, 1), **tot}
    dump_json(a.out_dir / "extract.json", rec)
    log(json.dumps(rec))
    return 0


# ── build ───────────────────────────────────────────────────────────────────
class TreeMem(threading.Thread):
    """Peak VmRSS + VmSwap of this process and its children, every 2 s."""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak_gb = 0.0
        self.stop = False

    @staticmethod
    def _kb(pid: int) -> int:
        tot = 0
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith(("VmRSS:", "VmSwap:")):
                    tot += int(line.split()[1])
        except OSError:
            pass
        return tot

    def sample(self) -> float:
        me = os.getpid()
        pids = [me]
        try:
            pids += [int(x) for x in Path(f"/proc/{me}/task/{me}/children").read_text().split()]
        except OSError:
            pass
        return sum(self._kb(p) for p in pids) / 1024 ** 2

    def run(self):
        while not self.stop:
            self.peak_gb = max(self.peak_gb, self.sample())
            time.sleep(2)


def load_u_records(upd_dir: Path) -> dict:
    """W-id -> DocRecord, the newest part wins (files in name = date order)."""
    _paths()
    from spike.delta_ingest.records import DocRecord
    out = {}
    for p in sorted(upd_dir.glob("*.jsonl")):
        with open(p) as fh:
            for line in fh:
                r = DocRecord.from_json(line)
                out[r.id] = r
    return out


def attach_vectors(store, recs: list, refused: dict) -> list:
    vecs, why = store.vectors([r.id for r in recs])
    kept = []
    for r in recs:
        v = vecs.get(r.id)
        if v is None:
            refused[why.get(r.id, "unknown")] = refused.get(why.get(r.id, "unknown"), 0) + 1
            continue
        r.sparse_field = v
        kept.append(r)
    return kept


def fill_records(meta: sqlite3.Connection, store_abs, wnums: list[int], base_record) -> tuple[list, int]:
    """Base DocRecords for `wnums` (meta row + hot-sidecar abstract); returns (records, missing)."""
    rows = []
    for i in range(0, len(wnums), 500):
        ch = wnums[i:i + 500]
        rows += meta.execute(f"SELECT id, title, doi, year, type, is_oa, section FROM docs WHERE id IN "
                             f"({','.join('?' * len(ch))})", ch).fetchall()
    by = {r[0]: r for r in rows}
    ids = [f"W{w}" for w in wnums if w in by]
    abstracts = store_abs.fetch(ids)
    out = []
    for w in wnums:
        r = by.get(w)
        ab = abstracts.get(f"W{w}") if r else None
        if r is None or not ab:
            continue
        out.append(base_record(f"W{w}", r[1], r[2], r[3], r[4], r[5], ab))
    return out, len(wnums) - len(out)


def dir_bytes(d: Path) -> int:
    return sum(p.stat().st_size for p in d.rglob("*") if p.is_file())


def cmd_build(a) -> int:
    _paths()
    from lib.thinclient.abstracts import AbstractStore
    from spike.delta_ingest.base import BaseIndex
    from spike.delta_ingest.base_vectors import BaseVectorStore
    from spike.delta_ingest.buffer import BufferWriter
    from spike.delta_ingest.generation import freeze_buffer
    from spike.delta_ingest.ledger import IngestLedger
    from spike.delta_ingest.profiles import PROFILES, apply_nice, rss_gb
    from spike.delta_ingest.seed import base_record
    root = Path(a.root)
    if root.exists():
        log(f"{root} exists; refusing to rebuild")
        return 2
    total = a.total
    profile = PROFILES["desktop_gpu"].with_overrides(layout="per_base_section", max_rss_gb=a.max_rss_gb,
                                                     seismic_threads=a.seismic_threads, nice=a.nice)
    apply_nice(profile)
    mem = TreeMem()
    mem.start()
    t_all = time.time()
    rec = {"root": str(root), "total_target": total, "profile": profile.as_dict(), "started": utc(),
           "stages_s": {}, "refused": {"U": {}, "F": {}}}
    store = BaseVectorStore([TWIN0], LOCATORS)
    t = time.time()
    u = load_u_records(a.out_dir / "upd")
    rec["u_records_loaded"] = len(u)
    u_ids = sorted(u, key=lambda x: int(x[1:]))[:total]
    root.mkdir(parents=True)
    ledger = IngestLedger(root / "ledger.sqlite")
    staged, sha = 0, hashlib.sha256()

    def stage(batch):
        nonlocal staged
        ledger.stage(batch, {r.id: True for r in batch})
        for r in batch:
            sha.update(r.id.encode() + b"\n")
        staged += len(batch)

    n_u = 0
    for i in range(0, len(u_ids), a.batch):
        kept = attach_vectors(store, [u[x] for x in u_ids[i:i + a.batch]], rec["refused"]["U"])
        stage(kept)
        n_u += len(kept)
    del u
    rec["u_staged"] = n_u
    rec["stages_s"]["u_records"] = round(time.time() - t, 1)
    t = time.time()
    order = np.load(a.out_dir / "f_order.npy", mmap_mode="r")
    meta = sqlite3.connect(f"file:{INDEX_ROOT / 'meta.sqlite'}?mode=ro&immutable=1", uri=True)
    sidecar = AbstractStore(INDEX_ROOT / "sections" / HOT / "abstracts.sqlite")
    pos, n_f, f_missing = 0, 0, 0
    while staged < total and pos < len(order):
        need = total - staged
        take = [int(x) for x in order[pos:pos + min(a.batch, int(need * 1.05) + 16)]]
        pos += len(take)
        recs, miss = fill_records(meta, sidecar, sorted(take), base_record)
        f_missing += miss
        kept = attach_vectors(store, recs, rec["refused"]["F"])[:total - staged]
        stage(kept)
        n_f += len(kept)
    meta.close()
    store.close()
    rec.update({"f_staged": n_f, "f_candidates_consumed": pos, "f_missing_meta_or_abstract": f_missing,
                "staged_total": staged, "ids_sha256": sha.hexdigest()})
    rec["stages_s"]["f_records"] = round(time.time() - t, 1)
    if staged != total:
        log(f"only {staged} of {total} staged")
        rec["status"] = "SHORT"
        dump_json(a.out_dir / a.log_name, rec)
        return 3
    writer = BufferWriter(root)
    writer.commit()
    writer.close()
    rec["rss_before_freeze_gb"] = round(rss_gb(), 2)
    t = time.time()
    base = BaseIndex(INDEX_ROOT)
    m4_manifest = Path("/home/vscode/work/inplace_update/m4/base_manifest.json")
    out = freeze_buffer(root, ledger, base, profile, seismic=True, base_shard_manifest=str(m4_manifest),
                        ordinal_dir=str(ORDS))
    rec["stages_s"]["freeze_publish"] = round(time.time() - t, 1)
    base.close()
    gi = json.loads((root / "g0001" / "generation.json").read_text())
    stats = ledger.stats() if hasattr(ledger, "stats") else {}
    ledger.close()
    mem.stop = True
    ru_self = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 2
    ru_ch = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024 ** 2
    gdir = root / "g0001"
    rec.update({
        "status": "BUILT", "finished": utc(), "wall_s": round(time.time() - t_all, 1),
        "peak_tree_vmrss_vmswap_gb": round(mem.peak_gb, 2), "maxrss_self_gb": round(ru_self, 2),
        "maxrss_children_gb": round(ru_ch, 2), "frozen_generation": out.get("frozen_generation"),
        "frozen_docs": out.get("frozen_docs"), "generation_seconds": gi.get("seconds"),
        "docs_with_vectors": gi.get("docs_with_vectors"), "seismic": gi.get("seismic"),
        "sections": {k: v.get("docs", v) if isinstance(v, dict) else v for k, v in gi["sections"].items()},
        "bytes": {"generation": dir_bytes(gdir), "seismic": dir_bytes(gdir / "seismic") if (gdir / "seismic").exists() else 0,
                  "sections": dir_bytes(gdir / "sections") if (gdir / "sections").exists() else None,
                  "ledger": (root / "ledger.sqlite").stat().st_size, "root": dir_bytes(root)},
        "livedocs": json.loads((root / "generations.json").read_text()).get("livedocs"),
        "ledger_stats": stats})
    dump_json(a.out_dir / a.log_name, rec)
    log(json.dumps({k: rec[k] for k in ("status", "wall_s", "staged_total", "u_staged", "f_staged",
                                        "peak_tree_vmrss_vmswap_gb", "bytes")}))
    return 0


# ── measure ─────────────────────────────────────────────────────────────────
def _m4f():
    spec = importlib.util.spec_from_file_location("m4f", REPO / "scripts/experiments/eval_delta_ingest_m4f.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_resolver(orig, root: Path):
    """M4F arm resolver plus the g1M arms (`g1M` bare, `xg1M` with the stack levers)."""
    def resolve(name: str, layout: str = "per_base_section", x_levers: tuple = ()) -> dict:
        base, *lev = name.split("+")
        if base in ("g1M", "xg1M"):
            levers = (list(x_levers) if base == "xg1M" else []) + list(lev)
            return {"name": name, "tag": "g1M", "root": str(root), "n_gen": 1, "levers": sorted(set(levers))}
        return orig(name, layout, x_levers)
    return resolve


def cmd_inproc(a) -> int:
    m = _m4f()
    m.resolve_arm = make_resolver(m.resolve_arm, Path(a.root))
    m.RUN_ARMS["F0"] = list(ARMS)
    ns = argparse.Namespace(run="F0", arms=",".join(ARMS), layout="per_base_section", levers=",".join(LEVERS),
                            passes=a.passes, warmup=a.warmup, rows_out=a.rows_out, limit_topics=a.limit_topics,
                            src=a.src, quiet_wait=a.quiet_wait, inline_wait=a.inline_wait, seed=BOOT_SEED,
                            deadline=a.deadline)
    return m.inproc(ns)


def f0_bar(units: dict, paired_diff, health_ok: bool, complete: bool) -> dict:
    d = paired_diff(units, "xg1M", "x1")
    hi = d["ci95"][1] if d["ci95"] else None
    if not (health_ok and complete):
        verdict = "NOT READ (run incomplete or unhealthy)"
    else:
        verdict = "PASS" if hi is not None and hi <= BAR_MS else "FAIL"
    added_m = (TOTAL - N1_DOCS) / 1e6
    c = {"median_ms_per_M_docs": round(d["median"] / added_m, 3) if d["median"] is not None else None,
         "ci95_ms_per_M_docs": [round(x / added_m, 3) for x in d["ci95"]] if d["ci95"] else None,
         "added_million_docs": added_m}
    return {"delta_g1M_minus_delta_n1": d, "threshold_ms": BAR_MS, "rule": "CI upper bound <= 8.0 ms",
            "verdict": verdict, "coefficient_c": c}


def cmd_summarize(a) -> int:
    m = _m4f()
    M4 = m.M4
    rec = json.loads(Path(a.rows).read_text())
    mp = [ps for ps in rec.get("passes", []) if ps["kind"] == "measured"]
    rows = [dict(r, **{"pass": ps["pass"]}) for ps in mp for r in ps["rows"] if not r.get("prime")]
    units = m._units(rows)
    arms = {}
    for arm in ARMS:
        ar = [r for r in rows if r["arm"] == arm]
        ms = [r["ms"] for r in ar]
        parts = [m.leg_parts(r) for r in ar]
        arms[arm] = {"spec": rec["specs"].get(arm), "n_calls": len(ar), "p50_ms": M4.pct(ms, 50),
                     "p95_ms": M4.pct(ms, 95), "mean_ms": round(statistics.fmean(ms), 2) if ms else None,
                     "legs_median_ms": {k: round(statistics.median([p[k] for p in parts]), 3) for k in parts[0]}
                     if parts else {},
                     "majflt_mean": round(statistics.fmean([r["majflt"] for r in ar]), 1) if ar else None,
                     "load": rec.get("health", {}).get("arms", {}).get(arm)}
    health_ok = bool(rec.get("health", {}).get("ok"))
    complete = (health_ok and not rec.get("partial") and len(mp) == a.passes
                and all(arms[x]["n_calls"] == 120 * a.passes for x in ARMS))
    diffs = {f"{x}_minus_{y}": m.paired_diff(units, x, y) for x, y in (("x1", "n0x"), ("xg1M", "n0x"))}
    leg_diff = {}
    for k in ("bm25f_delta_sections", "seismic_delta_shard_sum", "hydrate_abstracts_delta", "delta_masks",
              "bm25f_other_parse_merge_masks", "seismic_traverse"):
        pairs = []
        by = {}
        for r in rows:
            by.setdefault((r["pass"], r["topic"]), {})[r["arm"]] = m.leg_parts(r)[k]
        for (p, t), v in by.items():
            if "xg1M" in v and "x1" in v:
                pairs.append(v["xg1M"] - v["x1"])
        leg_diff[k] = round(statistics.median(pairs), 3) if pairs else None
    r1 = {}
    m4f_res = REPO / "data/eval_results/delta_ingest_M4F_20261001.json"
    if m4f_res.exists():
        for k, v in json.loads(m4f_res.read_text()).items():
            if isinstance(v, dict) and isinstance(v.get("bars"), dict) and "F-SLOPE" in v["bars"]:
                r1[k] = v["bars"]["F-SLOPE"]["paired_slope"]
    build = json.loads(Path(a.build).read_text()) if a.build and Path(a.build).exists() else None
    res = {"measurement": "doc 10 §6 F0", "script": "scripts/experiments/eval_delta_ingest_foldin_f0.py",
           "preregistration": "docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md (F0 row + addendum 2026-10-08 F0)",
           "rows_file": a.rows, "status": "COMPLETE" if complete else "PARTIAL/INVALID",
           "git_commit_measured_code": a.commit, "src": rec.get("src"),
           "health": {k: v for k, v in rec.get("health", {}).items() if k != "warnings_at_load"},
           "measured_passes": len(mp), "wall_s": rec.get("wall_s"), "maxrss_gb": rec.get("maxrss_gb"),
           "quiet_gate": rec.get("quiet_gate"), "host_start": rec.get("host_start"), "host_end": rec.get("host_end"),
           "mem": rec.get("mem"), "stop": rec.get("stop"), "arms": arms, "paired_differences": diffs,
           "leg_median_diff_xg1M_minus_x1_ms": leg_diff,
           "bar": f0_bar(units, m.paired_diff, health_ok, complete),
           "model_inputs": {"b_ms_per_gen_from_09_R1_F_SLOPE": r1,
                            "D_million_docs": {"x1": N1_DOCS / 1e6, "xg1M": TOTAL / 1e6}},
           "build_g1M": build,
           "raw_rows": [{k: r.get(k) for k in RAW_FIELDS} for r in rows] if a.raw else None,
           "date_utc": time.strftime("%Y-%m-%d", time.gmtime())}
    out = Path(a.out)
    full = json.loads(out.read_text()) if out.exists() else {"measurement": "doc 10 F0", "keys": "F0, F0_smoke"}
    full[a.key] = res
    out.write_text(json.dumps(full, indent=1, default=str) + "\n")
    print(json.dumps({"status": res["status"], "bar": res["bar"], "p50": {x: arms[x]["p50_ms"] for x in ARMS},
                      "diffs": diffs, "legs": leg_diff}, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--out-dir", type=Path, default=F0)
    s.add_argument("--limit-parts", type=int, default=0)
    s.add_argument("--limit-twin", type=int, default=0)
    e = sub.add_parser("extract")
    e.add_argument("--out-dir", type=Path, default=F0)
    e.add_argument("--workers", type=int, default=8)
    b = sub.add_parser("build")
    b.add_argument("--out-dir", type=Path, default=F0)
    b.add_argument("--root", default=str(G1M_ROOT))
    b.add_argument("--total", type=int, default=TOTAL)
    b.add_argument("--batch", type=int, default=20_000)
    b.add_argument("--max-rss-gb", type=float, default=40.0)
    b.add_argument("--seismic-threads", type=int, default=8)
    b.add_argument("--nice", type=int, default=5)
    b.add_argument("--log-name", default="build_g1M.json")
    i = sub.add_parser("inproc")
    i.add_argument("--root", default=str(G1M_ROOT))
    i.add_argument("--rows-out", required=True)
    i.add_argument("--src", default=str(REPO / "src"))
    i.add_argument("--passes", type=int, default=2)
    i.add_argument("--warmup", type=int, default=1)
    i.add_argument("--limit-topics", type=int, default=0)
    i.add_argument("--quiet-wait", type=int, default=900)
    i.add_argument("--inline-wait", type=int, default=120)
    i.add_argument("--deadline", default="")
    m = sub.add_parser("summarize")
    m.add_argument("--rows", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--key", default="F0")
    m.add_argument("--commit", default="")
    m.add_argument("--passes", type=int, default=2)
    m.add_argument("--build", default=str(F0 / "build_g1M.json"))
    m.add_argument("--raw", action="store_true")
    a = ap.parse_args()
    return {"select": cmd_select, "extract": cmd_extract, "build": cmd_build, "inproc": cmd_inproc,
            "summarize": cmd_summarize}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
