#!/usr/bin/env python3
# CLOSED MEASURED 2026-09-30 — in-place bit-update spike harness (docs/archive/inplace_update/); evidence kept, pre-registered bars live in source
"""In-place bit updater, Stage 0 bar S0-1: dead-slot supply vs insert demand.

BAR (verbatim from docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md, commit 8c239e99):

  ### S0-1 — dead-slot supply vs insert demand

  - **Unit:** each posting list L (term t) of the served shard-0 dv-v2 index;
    `slots(L)` = its posting count at build.
  - **Supply** `dead(L)` = postings in L whose doc is deleted, merged away, or
    updated in Q1 (an updated doc's old posting is dead; its new vector is
    demand). Also recorded: supply from deletions/merges only.
  - **Demand** `new(L)` = number of Q1 new-or-updated docs routed to shard 0
    whose encoded vector has a non-zero weight on t (every new posting, not
    only those that would pass the list's current minimum — the brief's
    literal, stricter reading). Also recorded, not gated: admissible demand
    (weight > the list's current minimum weight, or `slots(L)` below the
    per-list cap).
  - **Coverage without eviction** of a set S of lists =
    Σ_{L∈S} min(dead(L), new(L)) / Σ_{L∈S} new(L) (posting-weighted, pooled).
  - **Long lists** = lists with `slots(L)` ≥ ⌈cap/2⌉, where cap =
    `n_postings × max_fraction` read from shard 0's build config (3,500 ×
    1.5 = 5,250 at the G2 params per `seismic_150m_testbed/06_FINDINGS.md`;
    the script records the value it read, and the count and total postings
    of the long-list set).
  - **Deciles:** lists ranked by `slots(L)`, split into 10 equal-count
    deciles; pooled coverage per decile. **Hybrid cut-off** = scanning from
    the longest decile down, the first decile whose coverage < 0.50;
    recorded with its `slots` range.
  - **Thresholds.** PASS: long-list coverage ≥ 0.80 on the full Q1 window.
    If the full window could not be downloaded, a part-file sample (fraction
    f ≥ 0.10, recorded, deletions for the full window) may be used: PASS then
    needs the 95 % bootstrap lower bound (resampling part files, 10,000,
    seed 0) ≥ 0.80; PARTIAL if the point estimate ≥ 0.80 but the lower bound
    < 0.80 (PARTIAL does NOT satisfy the GO rule). FAIL: point estimate
    < 0.80.

Fixed inputs used (plan §"Fixed inputs", deviations recorded in the results):
  Q1 = snapshot works partitions with updated_date in [2026-06-17, 2026-09-15]
  (manifest 2026-09-23: 1,098 part files, 297,498,722 records, 359 GB). The
  full window is not downloaded; a part-file sample with f >= 0.10 is used
  (rule fixed 2026-09-29 before any S0-1 number): the window's files sorted
  by url, shuffled by random.Random("inplace-s0-1-f10"), taken in order until
  their records reach 10 % of the window's (110 files, 29,899,040 records,
  f = 0.1005). An earlier 6-file draw (seed "inplace-s0-1", f = 0.005) was
  prepared but never scored and is superseded.
  Deletions: every deleted_ids.csv.gz row with deleted_date in the window
  (full window, exact; the file starts at 2026-08-14). Slice:
  normalize_openalex_work + year >= 2010.
  Routing: in served shard 0 (by id) => updated; else blake2b rule == 0 and
  not in shard 0 => new. Demand vectors: a hash subsample (rate 1/4, seed
  "inplace-s0-enc") of each file's routed in-slice records, encoded with
  lib.thinclient.doc_encoder (PyTorch fp16 on CUDA, the base model), scaled
  per class (updated / new) to the file's exact routed counts. Scaling to the
  quarter: ratio estimator on manifest record counts (*est.*). Bootstrap:
  10,000 resamples of part files, seed 0.

Subcommands: prep-shard, prep-route, prep-encode, run (see --help). Work dir (default
/home/vscode/work/inplace_update/stage0) holds every intermediate;
data/seismic_150m/ is opened read-only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "source"))

from spike.inplace_update import prep  # noqa: E402
from spike.inplace_update.shard import ShardView, load_token_to_id  # noqa: E402

TWIN = Path(os.environ["INPLACE_TWIN_DIR"]) if os.environ.get("INPLACE_TWIN_DIR") else REPO / "data/seismic_150m/index/plan01/global_shard0of8.mmap"
SERVED = REPO / "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap"
WORK = Path("/home/vscode/work/inplace_update/stage0")
WINDOW = ("2026-06-17", "2026-09-15")
MIN_YEAR = 2010
ENC_RATE = 1 / 4
ENC_SEED = "inplace-s0-enc"
SAMPLE_SEED = "inplace-s0-1-f10"
MIN_F = 0.10
PARTS_OUT = WORK / "partsout_f10"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def window_files(manifest: dict) -> list[dict]:
    fs = [e for e in manifest["files"]
          if WINDOW[0] <= e["url"].split("updated_date=")[1][:10] <= WINDOW[1]]
    return sorted(fs, key=lambda e: e["url"])


def sample_files(manifest: dict) -> list[dict]:
    """f >= 0.10 sample (rule fixed 2026-09-29 before any S0-1 number): the
    window's files sorted by url, shuffled by random.Random(SAMPLE_SEED),
    taken in that order until their record count reaches 10 % of the
    window's."""
    fs = window_files(manifest)
    N = sum(e["meta"]["record_count"] for e in fs)
    idx = list(range(len(fs)))
    random.Random(SAMPLE_SEED).shuffle(idx)
    out, cum = [], 0
    for i in idx:
        out.append(fs[i])
        cum += fs[i]["meta"]["record_count"]
        if cum >= MIN_F * N:
            break
    return out


def _manifest():
    return json.loads((WORK / "manifest_works_2026-09-23.json").read_text())


def sample_keys() -> list[str]:
    return [part_key(e["url"]) for e in sample_files(_manifest())]


def part_key(url: str) -> str:
    return url.split("works/")[1].replace(".gz", "")


def part_path(key: str) -> Path:
    return WORK / "parts" / ("works_" + key.replace("/", "_") + ".gz")


def cmd_prep_shard(a):
    sh = ShardView(TWIN)
    ids = prep.shard_ids(sh, WORK)
    log("ids", len(ids))
    d = prep.deleted_rows(ids, WORK / "deleted_ids.csv.gz", WINDOW[0], WINDOW[1], WORK)
    log("deleted", d["meta"])
    ptr, row, w = prep.postings_table(sh, WORK, log=log)
    log("postings", len(row))


def _route_one(key: str) -> str:
    """Parse + route one part file (no encoding). Saves routed records and the
    encode subsample's texts to PARTS_OUT/<key>.route.npz."""
    out = PARTS_OUT / (key.replace("/", "_") + ".route.npz")
    if out.exists():
        try:
            with np.load(out, allow_pickle=True) as z:
                json.loads(str(z["counters"]))
            return f"skip {key}"
        except Exception:
            out.unlink()
    ids = np.load(WORK / "shard_ids.npy")
    order = np.argsort(ids)
    sid = ids[order]
    t0 = time.time()
    counters, recs = prep.parse_part(part_path(key), MIN_YEAR)
    num = np.array([r["id"] for r in recs], dtype=np.int64)
    pos = np.searchsorted(sid, num)
    pos[pos >= len(sid)] = 0
    inbase = (sid[pos] == num) if len(num) else np.zeros(0, bool)
    rows = np.where(inbase, order[pos], -1) if len(num) else np.zeros(0, np.int64)
    in_slice = np.array([r["out"] is None for r in recs], dtype=bool)
    counters["routed_in_base_out_of_slice"] = int((inbase & ~in_slice).sum())
    counters["routed_new_out_of_slice"] = int((~inbase & ~in_slice).sum())
    upd = in_slice & inbase
    counters["updated"] = int(upd.sum())
    counters["new"] = int((in_slice & ~inbase).sum())
    sel = np.array([i for i in np.flatnonzero(in_slice)
                    if prep.hash_unit(f"W{int(num[i])}", ENC_SEED) < ENC_RATE], dtype=np.int64)
    texts = np.array([recs[i]["text"] for i in sel], dtype=object)
    counters["route_seconds"] = round(time.time() - t0, 1)
    tmp = out.with_name(out.name + f".tmp{os.getpid()}.npz")
    np.savez(tmp, num=num, rows=rows, in_slice=in_slice, sel=sel, prob=np.full(len(sel), ENC_RATE),
             cls_upd=upd[sel] if len(sel) else np.zeros(0, bool), texts=texts, counters=json.dumps(counters))
    os.replace(tmp, out)
    return f"{key} {counters}"


def cmd_prep_route(a):
    from multiprocessing import Pool
    PARTS_OUT.mkdir(exist_ok=True)
    keys = sample_keys()
    sizes = {part_key(e["url"]): e["meta"]["content_length"] for e in _manifest()["files"]}
    todo = [k for k in keys if part_path(k).exists()
            and part_path(k).stat().st_size == sizes[k]]
    log(f"routing {len(todo)}/{len(keys)} downloaded files with {a.workers} workers")
    with Pool(a.workers) as pool:
        for msg in pool.imap_unordered(_route_one, todo):
            log(msg[:400])


def cmd_prep_encode(a):
    import torch
    torch.set_num_threads(4)
    from lib.thinclient.doc_encoder import make_doc_encoder
    enc = make_doc_encoder(backend="pytorch", device=a.device, batch_size=64)
    assert enc.model is not None and enc.tokenizer is not None, "encoder did not load"
    assert str(enc.device) == a.device, enc.device
    tok = load_token_to_id(TWIN)
    for key in sample_keys():
        rp = PARTS_OUT / (key.replace("/", "_") + ".route.npz")
        out = PARTS_OUT / (key.replace("/", "_") + ".npz")
        if out.exists() or not rp.exists():
            continue
        z = np.load(rp, allow_pickle=True)
        d = {k: z[k] for k in z.files}
        counters = json.loads(str(d.pop("counters")))
        texts = list(d.pop("texts"))
        te = time.time()
        vecs = []
        for b in range(0, len(texts), 64):
            vecs.extend(enc.encode_batch(texts[b:b + 64]))
        cptr, cc, cv = [0], [], []
        unk_tokens = unk_mass = 0
        for v in vecs:
            items = sorted((tok[t], w) for t, w in (v or {}).items() if t in tok)
            unk = [w for t, w in (v or {}).items() if t not in tok]
            unk_tokens += len(unk)
            unk_mass += sum(unk)
            cc.extend(c for c, _ in items)
            cv.extend(w for _, w in items)
            cptr.append(len(cc))
        counters.update({"encoded": len(texts), "encode_seconds": round(time.time() - te, 1),
                         "encoder": f"pytorch {a.device} (fp16 on cuda)", "unknown_token_entries": unk_tokens,
                         "unknown_token_mass": round(unk_mass, 3)})
        np.savez(out, **d, cptr=np.array(cptr, dtype=np.int64), comp=np.array(cc, dtype=np.uint16),
                 val=np.array(cv, dtype=np.float32).astype(np.float16), counters=json.dumps(counters))
        log(key, len(texts), counters["encode_seconds"])


def load_part(key: str) -> dict:
    z = np.load(PARTS_OUT / (key.replace("/", "_") + ".npz"), allow_pickle=True)
    d = {k: z[k] for k in z.files if k != "counters"}
    d["counters"] = json.loads(str(z["counters"]))
    return d


def per_file_vectors(d: dict, ptr, prow, pw, n_lists: int, list_min: np.ndarray, below_cap: np.ndarray):
    """Per-list (supply_upd, demand, demand_admissible) for one part file, in
    file units (not yet scaled)."""
    rows_upd = d["rows"][d["in_slice"] & (d["rows"] >= 0)]
    supply = np.zeros(n_lists)
    if len(rows_upd):
        supply = dead_counts(rows_upd, ptr, prow, n_lists).astype(np.float64)
    n_upd = int(d["counters"]["updated"])
    n_new = int(d["counters"]["new"])
    cls = d["cls_upd"]
    prob = d["prob"]
    cptr = d["cptr"]
    comp = d["comp"].astype(np.int64)
    val = d["val"].astype(np.float32)
    nd = len(cls)
    w_upd = np.where(cls, 1 / prob, 0.0)
    w_new = np.where(~cls, 1 / prob, 0.0)
    ht_upd, ht_new = w_upd.sum(), w_new.sum()
    s_upd = n_upd / ht_upd if ht_upd else 0.0
    s_new = n_new / ht_new if ht_new else 0.0
    wdoc = w_upd * s_upd + w_new * s_new
    lens = np.diff(cptr)
    wpost = np.repeat(wdoc, lens)
    demand = np.bincount(comp, weights=wpost, minlength=n_lists)[:n_lists]
    adm = (val > list_min[comp].astype(np.float32)) | below_cap[comp]
    demand_adm = np.bincount(comp[adm], weights=wpost[adm], minlength=n_lists)[:n_lists]
    info = {"n_upd": n_upd, "n_new": n_new, "vectors": nd, "ht_upd": float(ht_upd), "ht_new": float(ht_new),
            "vectors_upd": int(cls.sum()), "vectors_new": int((~cls).sum()),
            "mean_nnz_vectors": float(lens.mean()) if nd else None}
    return supply, demand, demand_adm, info


def per_file_vd(d: dict, sh, ptr, prow, n_lists: int, posthoc: dict | None):
    """SUPPLEMENTARY P1 (06 plan, second addendum): per-list supply/demand
    counting only vector-changed updated docs (all new docs still demand).
    Returns {mode: (supply_vd, demand_vd)} in file units + diff counters."""
    cls = d["cls_upd"]
    prob = d["prob"]
    cptr = d["cptr"]
    comp = d["comp"].astype(np.int64)
    n_upd = int(d["counters"]["updated"])
    n_new = int(d["counters"]["new"])
    ju = np.flatnonzero(cls)
    w_upd = np.where(cls, 1 / prob, 0.0)
    w_new = np.where(~cls, 1 / prob, 0.0)
    s_upd = n_upd / w_upd.sum() if w_upd.sum() else 0.0
    s_new = n_new / w_new.sum() if w_new.sum() else 0.0
    rows_j = d["rows"][d["sel"][ju]].astype(np.int64)
    sub_ptr = np.concatenate([[0], np.cumsum(cptr[ju + 1] - cptr[ju])]).astype(np.int64)
    gi = np.concatenate([np.arange(cptr[j], cptr[j + 1]) for j in ju]) if len(ju) else np.zeros(0, np.int64)
    diff = prep.vector_diff(sh, rows_j, sub_ptr, comp[gi] if len(gi) else np.zeros(0, np.int64),
                            d["val"][gi] if len(gi) else np.zeros(0, np.float16))
    modes = {"exact": ~diff["exact"], "tol": ~(diff["same_set"] & (diff["max_ulps"] <= 1))}
    if posthoc:
        modes["post_hoc"] = ~((diff["max_ulps"] <= posthoc["max_ulps"]) & (diff["symdiff_max_weight"] <= posthoc["setdiff_max_weight"]))
    lens = np.diff(cptr)
    out = {}
    for m, ch in modes.items():
        changed = np.zeros(len(cls), bool)
        changed[ju] = ch
        keep = (~cls) | changed
        wdoc = np.where(keep, w_upd * s_upd + w_new * s_new, 0.0)
        wpost = np.repeat(wdoc, lens)
        demand = np.bincount(comp, weights=wpost, minlength=n_lists)[:n_lists]
        supply = np.zeros(n_lists)
        rc = rows_j[ch]
        if len(rc):
            supply = dead_counts(rc, ptr, prow, n_lists).astype(np.float64) * s_upd / prob[ju][0]
        out[m] = (supply, demand)
    info = {"encoded_updated": int(len(ju)), **{f"changed_{m}": int(v.sum()) for m, v in modes.items()}}
    return out, info


_ROW2LISTS = {}


def dead_counts(rows: np.ndarray, ptr, prow, n_lists: int) -> np.ndarray:
    """Number of postings per list whose row is in `rows`."""
    key = "m"
    if key not in _ROW2LISTS:
        order = np.argsort(prow, kind="stable")
        lid = np.repeat(np.arange(n_lists, dtype=np.int32), np.diff(ptr))
        _ROW2LISTS[key] = (prow[order], lid[order])
    srow, slid = _ROW2LISTS[key]
    rows = np.unique(rows)
    a = np.searchsorted(srow, rows, side="left")
    b = np.searchsorted(srow, rows, side="right")
    idx = prep_ranges(a, b)
    return np.bincount(slid[idx], minlength=n_lists)


def prep_ranges(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ln = b - a
    tot = int(ln.sum())
    if tot == 0:
        return np.zeros(0, dtype=np.int64)
    cs = np.cumsum(ln)
    return np.repeat(a - (cs - ln), ln) + np.arange(tot, dtype=np.int64)


def coverage(dead, new, mask) -> float | None:
    d = new[mask].sum()
    return float(np.minimum(dead[mask], new[mask]).sum() / d) if d > 0 else None


def cmd_run(a):
    t0 = time.time()
    sh = ShardView(TWIN)
    cfg = json.loads((TWIN / "config.json").read_text())
    gt = cfg["pruning"]["GlobalThreshold"]
    cap = int(gt["n_postings"] * gt["max_fraction"])
    long_min = math.ceil(cap / 2)
    ptr, prow, pw = prep.postings_table(sh, WORK)
    n = sh.n_lists
    slots = np.diff(ptr)
    assert np.array_equal(slots, sh.list_len)
    served_len = np.array([p["packed_postings_words"] for p in json.loads((SERVED / "manifest.json").read_text())["posting_lists"]])
    list_min = np.full(n, np.inf, dtype=np.float32)
    nz = slots > 0
    list_min[nz] = np.minimum.reduceat(pw.astype(np.float32), ptr[:-1][nz])
    below_cap = slots < cap
    dl = prep.deleted_rows(np.load(WORK / "shard_ids.npy"), WORK / "deleted_ids.csv.gz", WINDOW[0], WINDOW[1], WORK)
    dead_del = dead_counts(dl["rows"], ptr, prow, n).astype(np.float64)

    man = json.loads((WORK / "manifest_works_2026-09-23.json").read_text())
    wf = window_files(man)
    N_window = sum(e["meta"]["record_count"] for e in wf)
    files = sample_files(man)
    keys = [part_key(e["url"]) for e in files]
    recs = {part_key(e["url"]): e["meta"]["record_count"] for e in man["files"]}
    per = {}
    missing = [k for k in keys if not (PARTS_OUT / (k.replace("/", "_") + ".npz")).exists()]
    keys = [k for k in keys if k not in missing]
    for k in keys:
        d = load_part(k)
        s, dm, dma, info = per_file_vectors(d, ptr, prow, pw, n, list_min, below_cap)
        per[k] = {"supply_upd": s, "demand": dm, "demand_adm": dma, "info": info, "counters": d["counters"],
                  "records": recs[k]}
        assert d["counters"]["lines"] == recs[k], (k, d["counters"]["lines"], recs[k])

    Rv = np.array([per[k]["records"] for k in keys], dtype=np.float64)
    SU = np.stack([per[k]["supply_upd"] for k in keys])
    DE = np.stack([per[k]["demand"] for k in keys])
    DA = np.stack([per[k]["demand_adm"] for k in keys])

    def estimate(sel_keys, counts=None):
        counts = counts if counts is not None else np.ones(len(keys))
        sc = N_window / float(counts @ Rv)
        return sc * (counts @ SU), sc * (counts @ DE), sc * (counts @ DA), sc

    longm = slots >= long_min
    rank = np.argsort(slots, kind="stable")
    dec = np.zeros(n, dtype=np.int64)
    for i, part in enumerate(np.array_split(rank, 10)):
        dec[part] = i + 1

    def summarize(sup_u, dem, dem_a):
        dead = dead_del + sup_u
        out = {"long_list_coverage": coverage(dead, dem, longm),
               "long_list_coverage_deletions_only_supply": coverage(dead_del, dem, longm),
               "long_list_coverage_admissible_demand": coverage(dead, dem_a, longm),
               "all_lists_coverage": coverage(dead, dem, np.ones(n, bool)),
               "totals": {"dead_deletions": float(dead_del.sum()), "dead_updates_est": float(sup_u.sum()),
                          "demand_est": float(dem.sum()), "demand_admissible_est": float(dem_a.sum()),
                          "long_dead": float(dead[longm].sum()), "long_demand": float(dem[longm].sum())},
               "deciles": []}
        for i in range(1, 11):
            m = dec == i
            out["deciles"].append({"decile": i, "lists": int(m.sum()), "slots_min": int(slots[m].min()),
                                   "slots_max": int(slots[m].max()), "slots_total": int(slots[m].sum()),
                                   "coverage": coverage(dead, dem, m),
                                   "coverage_deletions_only": coverage(dead_del, dem, m),
                                   "coverage_admissible": coverage(dead, dem_a, m),
                                   "dead": float(dead[m].sum()), "demand": float(dem[m].sum()),
                                   "dead_over_slots": float(dead[m].sum() / max(1, slots[m].sum()))})
        cut = None
        for row in reversed(out["deciles"]):
            if row["coverage"] is not None and row["coverage"] < 0.5:
                cut = row
                break
        out["hybrid_cutoff_decile"] = None if cut is None else {k: cut[k] for k in ("decile", "slots_min", "slots_max", "coverage")}
        return out

    sup_u, dem, dem_a, sc = estimate(keys)
    point = summarize(sup_u, dem, dem_a)
    rng = np.random.default_rng(0)
    B = 10_000
    boots = np.empty(B)
    K = len(keys)
    for bi in range(B):
        cnt = np.bincount(rng.integers(0, K, K), minlength=K).astype(float)
        su, de, _, _ = estimate(keys, cnt)
        boots[bi] = coverage(dead_del + su, de, longm)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    ctrl_p = WORK / "p1_control.json"
    ctrl = json.loads(ctrl_p.read_text()) if ctrl_p.exists() else None
    posthoc = ctrl.get("post_hoc_smallest_tolerance_under_1pct") if ctrl else None
    vd_files = {}
    vd_info = {}
    for k in keys:
        vd_files[k], vd_info[k] = per_file_vd(load_part(k), sh, ptr, prow, n, posthoc)
    p1 = {"label": "supplementary P1, not a bar (06 plan second addendum, d4ba6b87); GO reads only the frozen S0-1 above",
          "control_verdict": ctrl["verdict"] if ctrl else "control not run",
          "post_hoc_tolerance": posthoc, "modes": {}}
    for m in vd_files[keys[0]]:
        SUv = np.stack([vd_files[k][m][0] for k in keys])
        DEv = np.stack([vd_files[k][m][1] for k in keys])
        scv = N_window / float(Rv.sum())
        sv_, dv_ = scv * SUv.sum(0), scv * DEv.sum(0)
        bl = np.empty(2000)
        rng3 = np.random.default_rng(0)
        for bi in range(2000):
            cnt = np.bincount(rng3.integers(0, K, K), minlength=K).astype(float)
            sc_ = N_window / float(cnt @ Rv)
            bl[bi] = coverage(dead_del + sc_ * (cnt @ SUv), sc_ * (cnt @ DEv), longm)
        enc_u = sum(vd_info[k]["encoded_updated"] for k in keys)
        chg = sum(vd_info[k][f"changed_{m}"] for k in keys)
        p1["modes"][m] = {"long_list_coverage_vd": coverage(dead_del + sv_, dv_, longm),
                          "long_list_coverage_vd_ci95_2000_file_resamples": [float(np.percentile(bl, 2.5)), float(np.percentile(bl, 97.5))],
                          "all_lists_coverage_vd": coverage(dead_del + sv_, dv_, np.ones(n, bool)),
                          "dead_vd_total": float((dead_del + sv_).sum()), "new_vd_total": float(dv_.sum()),
                          "encoded_updated_docs": int(enc_u), "vector_changed_docs": int(chg),
                          "vector_changed_share_of_updated": chg / max(1, enc_u),
                          "deciles_vd": [{"decile": i, "coverage": coverage(dead_del + sv_, dv_, dec == i)} for i in range(1, 11)]}
    upd_f = np.array([per[k]["counters"]["updated"] for k in keys], dtype=np.float64)
    new_f = np.array([per[k]["counters"]["new"] for k in keys], dtype=np.float64)
    share_file = upd_f / Rv * N_window / sh.n_docs
    ub = np.empty(B)
    rng2 = np.random.default_rng(0)
    for bi in range(B):
        cnt = np.bincount(rng2.integers(0, K, K), minlength=K).astype(float)
        ub[bi] = (cnt @ upd_f) / (cnt @ Rv) * N_window / sh.n_docs
    update_share = {
        "definition": "Q1 updated docs routed to shard 0 (in served shard 0, in slice, touched in the window) / shard-0 docs; ratio estimator over the sampled files (*est.*)",
        "point": float(upd_f.sum() / Rv.sum() * N_window / sh.n_docs),
        "bootstrap_ci95_file_resampling": [float(np.percentile(ub, 2.5)), float(np.percentile(ub, 97.5))],
        "per_file_extrapolated_share": {"min": float(share_file.min()), "p10": float(np.percentile(share_file, 10)),
                                        "median": float(np.median(share_file)), "p90": float(np.percentile(share_file, 90)),
                                        "max": float(share_file.max())},
        "est_updated_docs_per_quarter": float(upd_f.sum() / Rv.sum() * N_window),
        "est_new_docs_per_quarter": float(new_f.sum() / Rv.sum() * N_window),
        "real_deletions_in_window_share": dl["meta"]["in_shard"] / sh.n_docs}
    f = sum(per[k]["records"] for k in keys) / N_window
    pe = point["long_list_coverage"]
    if pe < 0.80:
        verdict = "FAIL"
    elif f >= 0.10 and lo >= 0.80:
        verdict = "PASS"
    else:
        verdict = "PARTIAL"
    commit = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    res = {
        "bar": "S0-1 dead-slot supply vs insert demand (docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md @ 8c239e99)",
        "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script": "scripts/experiments/eval_inplace_s0_1.py", "git_commit_at_run": commit,
        "inputs": {"twin": str(TWIN), "served_dv_v2": str(SERVED),
                   "served_list_lengths_equal_twin": bool(np.array_equal(served_len, slots)),
                   "build_config_pruning": gt, "cap": cap, "long_min_slots": long_min,
                   "long_lists": int(longm.sum()), "long_list_postings": int(slots[longm].sum()),
                   "lists": int(n), "postings": int(slots.sum()),
                   "window": list(WINDOW), "window_files": len(wf), "window_records": int(N_window),
                   "sample_seed": SAMPLE_SEED, "sample_files": keys, "sample_records": int(sum(per[k]["records"] for k in keys)),
                   "sample_fraction_f": f, "plan_min_fraction": 0.10,
                   "quarter_scale_factor_ratio_estimator": sc,
                   "sample_files_missing": missing, "min_year": MIN_YEAR,
                   "encode_subsample": {"rate": ENC_RATE, "seed": ENC_SEED, "encoder": "lib.thinclient.doc_encoder PyTorch fp16 on CUDA, prithivida/Splade_PP_en_v1, max_length 128"},
                   "deletions": dl["meta"]},
        "per_file": {k: {"records": per[k]["records"], "counters": per[k]["counters"], "info": per[k]["info"],
                         "supply_upd_file_units": float(per[k]["supply_upd"].sum()),
                         "demand_file_units": float(per[k]["demand"].sum())} for k in per},
        "point_estimate": point,
        "bootstrap": {"resamples": B, "seed": 0, "unit": "part file", "long_list_coverage_ci95": [float(lo), float(hi)],
                      "mean": float(boots.mean())},
        "update_share_of_shard0_per_quarter": update_share,
        "threshold": "PASS long-list coverage >= 0.80 (full window, or sample f >= 0.10 with bootstrap LB >= 0.80); FAIL point < 0.80",
        "verdict": verdict,
        "verdict_note": ("sample fraction f is below the plan's 0.10 minimum, so PASS is unreachable; "
                         "FAIL is decided on the point estimate, otherwise PARTIAL") if f < 0.10 else "",
        "wall_seconds": round(time.time() - t0, 1),
    }
    out = Path(a.out)
    blob = json.loads(out.read_text()) if out.exists() else {}
    blob["s0_1"] = res
    blob.setdefault("supplementary", {}).setdefault("P1", {})["new_vd_dead_vd"] = p1
    out.write_text(json.dumps(blob, indent=1) + "\n")
    print(json.dumps({"verdict": verdict, "long": pe, "ci": [lo, hi], "cut": point["hybrid_cutoff_decile"]}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep-shard")
    p = sub.add_parser("prep-route")
    p.add_argument("--workers", type=int, default=4)
    e = sub.add_parser("prep-encode")
    e.add_argument("--device", default="cuda")
    r = sub.add_parser("run")
    r.add_argument("--out", default=str(WORK / "inplace_s0_draft.json"))
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    {"prep-shard": cmd_prep_shard, "prep-route": cmd_prep_route, "prep-encode": cmd_prep_encode, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
