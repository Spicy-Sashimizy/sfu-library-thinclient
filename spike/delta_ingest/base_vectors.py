"""Base-vector reuse (issue O14): copy a base doc's stored SPLADE vector into
its delta copy instead of re-encoding, when the encoder text is unchanged.

Why: after the base-hash seed (O4, `seed.py`) the ledger knows each base
doc's encode hash, so a content-only update (is_oa / type / year / DOI flips,
5,530 of 9,965 seeded docs on the M7 primary hot section) needs no encoder
pass — its SPLADE vector is already in the base forward index.

Source of vectors: the f16 c1a mmap twins of the base shards
(`data/seismic_150m/index/plan01/global_shard{k}of8.mmap`, or a local copy),
NOT the served dotvbyte fixed-u8 shards (lossy, per-doc scale). Layout read
(read-only, by small ranges; nothing is ever written next to the shard):
  forward_offsets.bin            u64 x (n_docs + 1)
  forward_components.bin         u16 x nnz   (token ids, strictly increasing per doc)
  forward_values.bin             f16 x nnz
  document_mapping_offsets.bin   u64 x (n_docs + 1)
  document_mapping_strings.bin   utf-8 doc ids, concatenated
  token_to_id_map.bin            u64 count, then (u64 len, bytes, u64 id) * count

id -> row: a per-shard "locator" (`<locator_dir>/<shard dir name>.locator/`:
`wnum.npy` sorted numeric W-ids, `row.npy` rows, `meta.json`), built once by
`build_locator` in bounded chunks, kept on local disk and memory-mapped.
Vectors and mapping strings are read with `os.pread` (no mapping of the
3.3 GB forward files: mmap fault-around inflated RSS to 2.6 GB on 20k random
rows, measured 2026-10-01).

Exact-or-refuse. A base vector is reused for record r only if ALL hold;
otherwise r is left for the encoder (never guessed):
  R1 the ledger has no `docs` row for r.id (a delta copy exists -> the ledger
     path `reusable_sparse` decides, the base copy may be stale);
  R2 `base_hashes` holds a seed for r.id and its encode hash64 equals
     hash64(r.encode_hash()) (encoder text unchanged vs the seeded base text);
  R3 exactly one shard row is found for r.id and the stored mapping string at
     that row equals r.id (guards a stale/corrupt locator);
  R4 the row's vector is non-empty, nnz <= MAX_NNZ, components strictly
     increasing and inside the token map, values finite and > 0;
  R5 every value survives the trip the delta build takes (python float ->
     JSON text -> float -> f16) with identical f16 bits.
R1-R5 make the delta copy's stored vector bit-identical to the base copy's
f16 forward vector. They do NOT prove that the base vector equals what the
current encoder would produce for the same text (base build encoder/runtime
vs today's): that is measured separately (INGEST_FIXES_20261001.md, O14).
"""
from __future__ import annotations

import json
import math
import os
import struct
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from .ledger import IngestLedger, hash64
from .records import DocRecord

MAX_NNZ = 256
LOCATOR_CHUNK = 1 << 20


def load_token_map(shard_dir: Path) -> list[str | None]:
    raw = (Path(shard_dir) / "token_to_id_map.bin").read_bytes()
    off = 0
    (count,) = struct.unpack_from("<Q", raw, off)
    off += 8
    pairs = []
    for _ in range(count):
        (slen,) = struct.unpack_from("<Q", raw, off)
        off += 8
        s = raw[off:off + slen].decode("utf-8")
        off += slen
        (v,) = struct.unpack_from("<Q", raw, off)
        off += 8
        pairs.append((s, v))
    if off != len(raw):
        raise ValueError(f"token_to_id_map.bin trailing bytes in {shard_dir}")
    id2tok: list[str | None] = [None] * (max((v for _, v in pairs), default=-1) + 1)
    for s, v in pairs:
        id2tok[v] = s
    return id2tok


def _parse_wnums(blob: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Vectorised 'W<digits>' -> int; -1 where the id is not a W-id or has
    more than 18 digits."""
    n = len(starts)
    lens = ends - starts
    out = np.zeros(n, dtype=np.int64)
    ok = (lens >= 2) & (lens <= 19)
    first = np.where(ok, blob[np.minimum(starts, len(blob) - 1)], 0)
    ok &= first == ord("W")
    maxlen = int(lens[ok].max()) if ok.any() else 0
    for j in range(1, maxlen):
        has = ok & (lens > j)
        if not has.any():
            break
        ch = blob[np.minimum(starts + j, len(blob) - 1)].astype(np.int64) - ord("0")
        bad = has & ((ch < 0) | (ch > 9))
        ok &= ~bad
        out = np.where(has & ok, out * 10 + ch, out)
    out[~ok] = -1
    return out


def build_locator(shard_dir: str | Path, out_path: str | Path, chunk: int = LOCATOR_CHUNK) -> dict:
    """Write the locator dir `<out_path>` (wnum.npy int64 sorted, row.npy
    uint32, meta.json) for one shard; replaced atomically by rename.
    Reads the mapping in `chunk`-doc ranges; peak memory ~ 2 x 12 B per doc
    plus one chunk of strings."""
    shard_dir = Path(shard_dir)
    moffs = np.memmap(shard_dir / "document_mapping_offsets.bin", dtype=np.uint64, mode="r")
    n = len(moffs) - 1
    wn = np.empty(n, dtype=np.int64)
    with open(shard_dir / "document_mapping_strings.bin", "rb") as fh:
        for lo in range(0, n, chunk):
            hi = min(n, lo + chunk)
            m = np.asarray(moffs[lo:hi + 1], dtype=np.int64)
            fh.seek(int(m[0]))
            blob = np.frombuffer(fh.read(int(m[-1] - m[0])), dtype=np.uint8)
            if len(blob) == 0:
                wn[lo:hi] = -1
                continue
            rel = m - m[0]
            wn[lo:hi] = _parse_wnums(blob, rel[:-1], rel[1:])
    rows = np.arange(n, dtype=np.uint32)
    keep = wn >= 0
    wn, rows = wn[keep], rows[keep]
    order = np.argsort(wn, kind="stable")
    wn, rows = wn[order], rows[order]
    dup = int(np.count_nonzero(wn[1:] == wn[:-1])) if len(wn) > 1 else 0
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    if tmp.exists():
        for f in tmp.iterdir():
            f.unlink()
    tmp.mkdir(exist_ok=True)
    np.save(tmp / "wnum.npy", wn)
    np.save(tmp / "row.npy", rows)
    (tmp / "meta.json").write_text(json.dumps({"n_docs": n, "shard": str(shard_dir)}))
    if out_path.exists():
        for f in out_path.iterdir():
            f.unlink()
        out_path.rmdir()
    tmp.rename(out_path)
    return {"shard": str(shard_dir), "docs": n, "w_ids": int(len(wn)), "non_w": int(n - len(wn)),
            "duplicate_ids": dup, "locator": str(out_path)}


class _Shard:
    def __init__(self, shard_dir: Path, locator: Path):
        self.dir = shard_dir
        self._fd = {name: os.open(shard_dir / name, os.O_RDONLY) for name in (
            "forward_offsets.bin", "forward_components.bin", "forward_values.bin",
            "document_mapping_offsets.bin", "document_mapping_strings.bin")}
        size = {k: os.fstat(fd).st_size for k, fd in self._fd.items()}
        self.n_docs = size["forward_offsets.bin"] // 8 - 1
        nnz = size["forward_components.bin"] // 2
        if size["forward_values.bin"] != 2 * nnz or self._u64("forward_offsets.bin", self.n_docs) != nnz:
            self.close()
            raise ValueError(f"{shard_dir}: forward arrays disagree (not an f16 c1a twin?)")
        if size["document_mapping_offsets.bin"] // 8 - 1 != self.n_docs:
            self.close()
            raise ValueError(f"{shard_dir}: forward/doc-mapping lengths disagree")
        meta = json.loads((locator / "meta.json").read_text())
        if int(meta["n_docs"]) != self.n_docs:
            self.close()
            raise ValueError(f"{locator} was built for a different shard ({meta['n_docs']} docs)")
        self.wnum = np.load(locator / "wnum.npy", mmap_mode="r")
        self.row = np.load(locator / "row.npy", mmap_mode="r")
        self.id2tok = load_token_map(shard_dir)

    def close(self) -> None:
        for fd in self._fd.values():
            os.close(fd)
        self._fd = {}

    def _pread(self, name: str, n: int, off: int) -> bytes:
        b = os.pread(self._fd[name], n, off)
        if len(b) != n:
            raise OSError(f"short read {name} @{off}: {len(b)} of {n}")
        return b

    def _u64(self, name: str, i: int) -> int:
        return struct.unpack("<Q", self._pread(name, 8, 8 * i))[0]

    def _pair(self, name: str, row: int) -> tuple[int, int]:
        return struct.unpack("<QQ", self._pread(name, 16, 8 * row))

    def rows_for(self, wnums: np.ndarray) -> list[list[int]]:
        lo = np.searchsorted(self.wnum, wnums, side="left")
        hi = np.searchsorted(self.wnum, wnums, side="right")
        return [self.row[a:b].tolist() for a, b in zip(lo, hi)]

    def doc_id(self, row: int) -> str:
        a, b = self._pair("document_mapping_offsets.bin", row)
        return self._pread("document_mapping_strings.bin", b - a, a).decode("utf-8", errors="replace")

    def vector(self, row: int) -> tuple[np.ndarray, np.ndarray]:
        a, b = self._pair("forward_offsets.bin", row)
        if b < a or b - a > 1 << 16:
            return np.zeros(0, dtype=np.uint16), np.zeros(0, dtype=np.float16)
        n = b - a
        comps = np.frombuffer(self._pread("forward_components.bin", 2 * n, 2 * a), dtype="<u2")
        vals = np.frombuffer(self._pread("forward_values.bin", 2 * n, 2 * a), dtype="<f2")
        return comps, vals


def _f16_roundtrip_exact(vals: np.ndarray) -> list[float] | None:
    out = []
    for v in vals.tolist():
        if not math.isfinite(v) or v <= 0:
            return None
        back = json.loads(json.dumps(v))
        if np.float16(back).view(np.uint16) != np.float16(v).view(np.uint16):
            return None
        out.append(back)
    return out


class BaseVectorStore:
    """Read-only access to base f16 forward vectors by W-id (see module doc)."""

    def __init__(self, shard_dirs: Iterable[str | Path], locator_dir: str | Path):
        self.shards: list[_Shard] = []
        for d in shard_dirs:
            d = Path(d)
            loc = Path(locator_dir) / f"{d.name}.locator"
            if not loc.exists():
                raise FileNotFoundError(f"no locator for {d} at {loc} — run build_locator first")
            self.shards.append(_Shard(d, loc))

    def close(self) -> None:
        for sh in self.shards:
            sh.close()

    def vectors(self, ids: Iterable[str]) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
        """(id -> exact vector, id -> refusal reason) for R3-R5."""
        ids = list(dict.fromkeys(ids))
        nums = {}
        refused: dict[str, str] = {}
        for i in ids:
            if len(i) > 1 and i[0] == "W" and i[1:].isdigit() and len(i) <= 19:
                nums[i] = int(i[1:])
            else:
                refused[i] = "not_w_id"
        hits: dict[str, list[tuple[int, int]]] = {i: [] for i in nums}
        if nums:
            keys = list(nums)
            arr = np.array([nums[k] for k in keys], dtype=np.int64)
            for si, sh in enumerate(self.shards):
                for k, rows in zip(keys, sh.rows_for(arr)):
                    hits[k].extend((si, r) for r in rows)
        out: dict[str, dict[str, float]] = {}
        for i, h in hits.items():
            if len(h) != 1:
                refused[i] = "not_in_base_shards" if not h else "multiple_rows"
                continue
            si, row = h[0]
            sh = self.shards[si]
            if sh.doc_id(row) != i:
                refused[i] = "mapping_mismatch"
                continue
            comps, vals = sh.vector(row)
            if len(comps) == 0 or len(comps) > MAX_NNZ:
                refused[i] = "nnz_out_of_range"
                continue
            if len(comps) > 1 and not bool(np.all(np.diff(comps.astype(np.int64)) > 0)):
                refused[i] = "components_not_increasing"
                continue
            toks = [sh.id2tok[c] if c < len(sh.id2tok) else None for c in comps.tolist()]
            if any(t is None for t in toks):
                refused[i] = "unknown_component"
                continue
            fl = _f16_roundtrip_exact(vals)
            if fl is None:
                refused[i] = "value_not_exact"
                continue
            out[i] = dict(zip(toks, fl))
        return out, refused


def base_reuse_candidates(ledger: IngestLedger, records: list[DocRecord]) -> tuple[list[str], dict[str, str]]:
    """R1 + R2: ids eligible for base-vector reuse, and why the rest are not."""
    known = ledger.known(r.id for r in records)
    rest = [r for r in records if r.id not in known]
    seeded = ledger.base_known(r.id for r in rest)
    ok: list[str] = []
    why: dict[str, str] = {r.id: "has_ledger_row" for r in records if r.id in known}
    for r in rest:
        s = seeded.get(r.id)
        if s is None:
            why[r.id] = "not_seeded"
        elif s[1] != hash64(r.encode_hash()):
            why[r.id] = "encode_text_changed"
        else:
            ok.append(r.id)
    return ok, why


def reusable_base_sparse(ledger: IngestLedger, records: list[DocRecord],
                         store: BaseVectorStore | None) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    """id -> exact base vector for records passing R1-R5, plus refusal
    counts by reason. `store` None (flag off) returns nothing."""
    if store is None or not records:
        return {}, {}
    ok, why = base_reuse_candidates(ledger, records)
    vecs, refused = store.vectors(ok)
    why.update(refused)
    counts: dict[str, int] = {}
    for reason in why.values():
        counts[reason] = counts.get(reason, 0) + 1
    return vecs, counts
