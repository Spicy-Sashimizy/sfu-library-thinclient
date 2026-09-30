"""Stage-0 input preparation (all outputs under the work dir, never the repo).

  shard_ids        numeric OpenAlex id per forward row of the shard
  postings_table   (ptr, row, weight) of every posting of every list, slot order
  deleted_rows     rows of shard docs whose id is in deleted_ids.csv.gz with
                   deleted_date in [lo, hi]
  scan_forward     f16 value histogram of the whole forward + every
                   (row, comp, value) entry with comp in a term set and
                   value >= floor (the R_sim candidate pool)
  parse_part       one snapshot part file -> in-slice records routed to the
                   shard (adapter slice rules, min_year configurable)
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from .shard import ShardView

SEED_PLAN01 = "sfu-seismic-plan01"


def shard_of(oaid: str, n: int = 8, seed: str = SEED_PLAN01) -> int:
    h = hashlib.blake2b((seed + str(oaid)).encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big") % n


def hash_unit(key: str, seed: str) -> float:
    h = hashlib.blake2b((seed + key).encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big") / 2.0 ** 64


def shard_ids(sh: ShardView, work: Path) -> np.ndarray:
    p = work / "shard_ids.npy"
    if p.exists():
        return np.load(p)
    ids = sh.doc_ids()
    np.save(p, ids)
    return ids


def weights_pairs(sh: ShardView, rows: np.ndarray, terms: np.ndarray) -> np.ndarray:
    o = sh.offs_i64
    lo = o[rows].copy()
    hi = o[rows + 1].copy()
    tt = terms.astype(np.uint16)
    act = np.arange(len(rows))
    while len(act):
        mid = (lo[act] + hi[act]) >> 1
        cm = np.asarray(sh.comps[mid])
        less = cm < tt[act]
        lo[act] = np.where(less, mid + 1, lo[act])
        hi[act] = np.where(less, hi[act], mid)
        act = act[lo[act] < hi[act]]
    end = o[rows + 1]
    w = np.zeros(len(rows), dtype=np.float16)
    ok = lo < end
    idx = lo[ok]
    hit = np.asarray(sh.comps[idx]) == tt[ok]
    vv = np.asarray(sh.vals[idx])
    tmp = np.zeros(int(ok.sum()), dtype=np.float16)
    tmp[hit] = vv[hit]
    w[ok] = tmp
    return w


def postings_table(sh: ShardView, work: Path, log=print):
    p = work / "postings.npz"
    if p.exists():
        z = np.load(p)
        return z["ptr"], z["row"], z["w"]
    n = sh.n_lists
    ptr = np.zeros(n + 1, dtype=np.int64)
    ptr[1:] = np.cumsum(sh.list_len)
    t0 = time.time()
    row = np.concatenate([sh.list_rows_checked(t) for t in range(n)]).astype(np.int64)
    log(f"[postings] rows resolved {time.time() - t0:.0f}s")
    lid = np.repeat(np.arange(n, dtype=np.int64), np.diff(ptr))
    D1 = n + 1
    key = row * D1 + lid
    order = np.argsort(key, kind="stable")
    skey = key[order]
    del key, lid
    w_sorted = np.zeros(len(skey), dtype=np.float16)
    o = sh.offs_i64
    N = sh.n_docs
    step = 400_000
    for r0 in range(0, N, step):
        r1 = min(N, r0 + step)
        a, b = int(o[r0]), int(o[r1])
        c = np.asarray(sh.comps[a:b]).astype(np.int64)
        v = np.asarray(sh.vals[a:b])
        rr = np.repeat(np.arange(r0, r1, dtype=np.int64), np.diff(o[r0:r1 + 1]))
        fkey = rr * D1 + c
        pa = np.searchsorted(skey, r0 * D1, side="left")
        pb = np.searchsorted(skey, r1 * D1, side="left")
        pk = skey[pa:pb]
        pos = np.searchsorted(fkey, pk)
        pos[pos >= len(fkey)] = 0
        hit = fkey[pos] == pk
        assert hit.all(), f"posting without forward entry in rows {r0}..{r1}"
        w_sorted[pa:pb] = v[pos]
        if (r0 // step) % 10 == 0:
            log(f"[postings] rows {r1}/{N} {time.time() - t0:.0f}s")
    w = np.zeros(len(skey), dtype=np.float16)
    w[order] = w_sorted
    assert (w > 0).all()
    row = row.astype(np.int32)
    np.savez(p, ptr=ptr, row=row, w=w)
    return ptr, row, w


def deleted_rows(ids: np.ndarray, csv_gz: Path, lo: str, hi: str, work: Path) -> dict:
    p = work / f"deleted_rows_{lo}_{hi}.npz"
    if p.exists():
        z = np.load(p, allow_pickle=True)
        return {"rows": z["rows"], "meta": json.loads(str(z["meta"]))}
    from array import array
    lo_b, hi_b = lo.encode(), hi.encode()
    acc = array("q")
    n_all = n_win = bad = 0
    dmin, dmax = b"9999", b"0000"
    with gzip.open(csv_gz, "rb") as fh:
        fh.readline()
        for line in fh:
            n_all += 1
            k = line.rfind(b",")
            d = line[k + 1:].strip()
            if d < dmin:
                dmin = d
            if d > dmax:
                dmax = d
            if lo_b <= d <= hi_b:
                n_win += 1
                s = line[:k]
                j = s.rfind(b"/W")
                if j < 0 or not s[j + 2:].isdigit():
                    bad += 1
                    continue
                acc.append(int(s[j + 2:]))
    num = np.unique(np.frombuffer(acc, dtype=np.int64))
    del acc
    order = np.argsort(ids)
    sid = ids[order]
    pos = np.searchsorted(sid, num)
    pos[pos >= len(sid)] = 0
    hit = sid[pos] == num
    rows = np.sort(order[pos[hit]]).astype(np.int64)
    meta = {"deleted_ids_rows_total": int(n_all), "in_window": int(n_win), "unique_ids_in_window": int(len(num)),
            "bad_ids": int(bad), "in_shard": int(len(rows)), "window": [lo, hi],
            "date_min_all": dmin.decode(), "date_max_all": dmax.decode()}
    np.savez(p, rows=rows, meta=json.dumps(meta))
    return {"rows": rows, "meta": meta}


def scan_forward(sh: ShardView, term_mask: np.ndarray, floor: float, work: Path, tag: str, log=print):
    """Histogram of all f16 bit patterns + entries (row, comp, val) with
    term_mask[comp] and val >= floor."""
    p = work / f"fwdscan_{tag}.npz"
    if p.exists():
        z = np.load(p)
        return z["hist"], z["row"], z["comp"], z["val"]
    o = sh.offs_i64
    nnz = int(o[-1])
    hist = np.zeros(65536, dtype=np.int64)
    R, C, V = [], [], []
    step = 40_000_000
    t0 = time.time()
    f16floor = np.float16(floor)
    for a in range(0, nnz, step):
        b = min(nnz, a + step)
        c = np.asarray(sh.comps[a:b])
        v = np.asarray(sh.vals[a:b])
        hist += np.bincount(v.view(np.uint16), minlength=65536)
        m = term_mask[c] & (v >= f16floor)
        if m.any():
            pos = np.flatnonzero(m) + a
            r = np.searchsorted(o, pos, side="right") - 1
            R.append(r.astype(np.int32))
            C.append(c[m])
            V.append(v[m])
        log(f"[fwdscan] {b}/{nnz} {time.time() - t0:.0f}s")
    row = np.concatenate(R) if R else np.zeros(0, np.int32)
    comp = np.concatenate(C) if C else np.zeros(0, np.uint16)
    val = np.concatenate(V) if V else np.zeros(0, np.float16)
    np.savez(p, hist=hist, row=row, comp=comp, val=val)
    return hist, row, comp, val


def parse_part(path: Path, min_year: int, shard: int = 0, n_shards: int = 8):
    """Adapter slice rules (spike/delta_ingest normalize_openalex_work + the
    adapter's year gate, min_year overridable). Returns (counters, records)
    where records are in-slice works routed to `shard`: dicts id(int),
    text(str), year."""
    import sys
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    from spike.delta_ingest.records import coerce_year, normalize_openalex_work
    c = collections.Counter()
    recs = []
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            c["lines"] += 1
            try:
                w = json.loads(line)
            except json.JSONDecodeError:
                c["json_error"] += 1
                continue
            raw_id = (w.get("id") or "").rsplit("/", 1)[-1]
            routed = raw_id.startswith("W") and shard_of(raw_id, n_shards) == shard
            if routed:
                c["routed_all"] += 1
            year = coerce_year(w.get("publication_year"))
            if year is not None and year < min_year:
                c["year_lt_min"] += 1
                if routed:
                    recs.append({"id": int(raw_id[1:]), "text": None, "year": year, "out": "year"})
                continue
            r = normalize_openalex_work(w)
            if r is None:
                c["not_in_slice"] += 1
                if routed:
                    recs.append({"id": int(raw_id[1:]), "text": None, "year": year, "out": "slice"})
                continue
            c["in_slice"] += 1
            if routed:
                c["in_slice_routed"] += 1
                recs.append({"id": int(r.id[1:]), "text": r.encoder_text(), "year": year, "out": None})
    return dict(c), recs


def vector_diff(sh: ShardView, rows: np.ndarray, cptr: np.ndarray, comp: np.ndarray, val: np.ndarray) -> dict:
    """Compare encoded vectors (CSR over shard token ids; values cast to f16)
    with the stored twin forward rows. Per doc: same component set, exact
    equality after the f16 cast, max |dw| over shared components, max |dw| in
    f16 ulps of the stored value, size of the component symmetric difference
    and the largest weight among the differing components."""
    o = sh.offs_i64
    n = len(rows)
    same = np.zeros(n, bool)
    exact = np.zeros(n, bool)
    maxd = np.zeros(n)
    maxulp = np.zeros(n)
    symd = np.zeros(n, np.int64)
    symw = np.zeros(n)
    for i in range(n):
        r = int(rows[i])
        sc = np.asarray(sh.comps[o[r]:o[r + 1]]).astype(np.int64)
        sv = np.asarray(sh.vals[o[r]:o[r + 1]])
        ec = comp[cptr[i]:cptr[i + 1]].astype(np.int64)
        ev = val[cptr[i]:cptr[i + 1]].astype(np.float32).astype(np.float16)
        common, ia, ib = np.intersect1d(sc, ec, assume_unique=True, return_indices=True)
        only_s = np.setdiff1d(np.arange(len(sc)), ia)
        only_e = np.setdiff1d(np.arange(len(ec)), ib)
        symd[i] = len(only_s) + len(only_e)
        ws = np.concatenate([sv[only_s].astype(np.float32), ev[only_e].astype(np.float32)])
        symw[i] = float(ws.max()) if len(ws) else 0.0
        d = np.abs(sv[ia].astype(np.float32) - ev[ib].astype(np.float32))
        ulp = np.spacing(sv[ia]).astype(np.float32)
        maxd[i] = float(d.max()) if len(d) else 0.0
        maxulp[i] = float((d / ulp).max()) if len(d) else 0.0
        same[i] = symd[i] == 0
        exact[i] = same[i] and bool((sv[ia] == ev[ib]).all())
    return {"same_set": same, "exact": exact, "max_abs_diff": maxd, "max_ulps": maxulp,
            "symdiff": symd, "symdiff_max_weight": symw}
