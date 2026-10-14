"""Fold the dense warm-cache delta into the static seed artifacts (v2 item).

`merge_dense_delta(index_root)` is the FreshDiskANN-style background merge the
v1 warm cache deferred (docs/DENSE_WARMCACHE_RESEARCH.md "Deferred to v2"): a
BULK REBUILD of `dense/b1.usearch` + `dense/ids.json` + `dense/rescore_int8.npy`
from seed ∪ delta, then the delta is truncated. A bulk rebuild — rather than
incremental `add()` into the served graph — is what erases HNSW insert-order
debt (query-correlated insert order is the documented bad case, arXiv 2405.17813).

Fails closed: every disagreement between the three seed artifacts (or between
them and `manifest.json`'s dense block, when present) aborts before anything is
written. Writes go to sibling temp files that are fsynced and `os.replace`d, so
a reader always sees a whole artifact; the delta is truncated only after all
three renames succeed, so a crash mid-merge costs a re-merge, never a document.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

import numpy as np

logger = logging.getLogger("sfu_library_mcp")

SEED_FILES = ("b1.usearch", "ids.json", "rescore_int8.npy")
COPY_CHUNK = 8192
LOCK_NAME = ".merge.lock"


class DenseDeltaMergeError(RuntimeError):
    """Seed/delta disagreement — the merge aborted without writing."""


def _seed_bits(index, start: int, stop: int, code_bytes: int) -> np.ndarray:
    try:
        got = index.get(np.arange(start, stop, dtype=np.uint64))
    except Exception as exc:
        raise DenseDeltaMergeError(
            f"seed b1 index will not yield rows {start}:{stop} ({exc}); "
            "refusing to rebuild from a partially readable seed") from exc
    bits = np.asarray(got, dtype=np.uint8).reshape(stop - start, -1)
    if bits.shape[1] != code_bytes:
        raise DenseDeltaMergeError(
            f"seed b1 row width {bits.shape[1]} B != {code_bytes} B implied by "
            "rescore_int8.npy")
    return bits


def _manifest_dense(index_root: Path) -> dict:
    p = index_root / "manifest.json"
    if not p.exists():
        return {}
    try:
        block = json.loads(p.read_text()).get("dense") or {}
    except Exception as exc:
        raise DenseDeltaMergeError(f"manifest.json unreadable: {exc}") from exc
    return block if isinstance(block, dict) else {}


def _read_delta(db: sqlite3.Connection, dim: int,
                seed_ids: set[str]) -> tuple[list[str], np.ndarray, dict]:
    ids: list[str] = []
    vecs: list[np.ndarray] = []
    seen: set[str] = set()
    skipped = {"duplicate_of_seed": 0, "duplicate_in_delta": 0, "bad_dim": 0}
    for doc_id, blob in db.execute("SELECT id, vec FROM delta ORDER BY key"):
        if doc_id in seed_ids:
            skipped["duplicate_of_seed"] += 1
            continue
        if doc_id in seen:
            skipped["duplicate_in_delta"] += 1
            continue
        vec = np.frombuffer(blob, dtype=np.int8)
        if vec.shape[0] != dim:
            skipped["bad_dim"] += 1
            continue
        seen.add(doc_id)
        ids.append(doc_id)
        vecs.append(vec)
    stacked = (np.stack(vecs) if vecs
               else np.zeros((0, dim), dtype=np.int8))
    return ids, stacked, skipped


def _write_atomic(path: Path, write_fn) -> Path:
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    write_fn(tmp)
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return tmp


def merge_dense_delta(index_root, *, truncate: bool = True) -> dict:
    """Rebuild the seed artifacts from seed ∪ delta, then truncate the delta.

    Returns a summary dict (`status` ∈ {"merged", "noop"}). Raises
    `DenseDeltaMergeError` — before writing anything — when the seed artifacts
    disagree with each other or with `manifest.json`.
    """
    from usearch.index import Index

    root = Path(index_root)
    dense_dir = root / "dense"
    missing = [f for f in SEED_FILES if not (dense_dir / f).exists()]
    if missing:
        raise DenseDeltaMergeError(
            f"seed incomplete in {dense_dir}: missing {', '.join(missing)}")
    delta_path = dense_dir / "delta.sqlite"

    lock = dense_dir / LOCK_NAME
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise DenseDeltaMergeError(
            f"another merge holds {lock}; remove it if no merge is running"
        ) from exc
    os.write(lock_fd, str(os.getpid()).encode())
    os.close(lock_fd)

    try:
        ids = json.loads((dense_dir / "ids.json").read_text())
        rescore = np.load(dense_dir / "rescore_int8.npy", mmap_mode="r")
        if rescore.ndim != 2:
            raise DenseDeltaMergeError(
                f"rescore_int8.npy is {rescore.ndim}-D, expected 2-D")
        n_seed, dim = int(rescore.shape[0]), int(rescore.shape[1])
        if len(ids) != n_seed:
            raise DenseDeltaMergeError(
                f"ids.json has {len(ids)} ids but rescore_int8.npy has "
                f"{n_seed} rows")
        index = Index.restore(str(dense_dir / "b1.usearch"), view=True)
        if len(index) != n_seed:
            raise DenseDeltaMergeError(
                f"b1.usearch holds {len(index)} vectors but ids.json/"
                f"rescore_int8.npy hold {n_seed}")
        if int(index.ndim) != dim:
            raise DenseDeltaMergeError(
                f"b1.usearch ndim {index.ndim} != rescore dim {dim}")
        mf = _manifest_dense(root)
        for key, actual in (("vectors", n_seed), ("dim", dim)):
            if key in mf and int(mf[key]) != actual:
                raise DenseDeltaMergeError(
                    f"manifest.json dense.{key}={mf[key]} disagrees with the "
                    f"seed artifacts ({actual})")

        if not delta_path.exists():
            return {"status": "noop", "reason": "no delta.sqlite",
                    "seed": n_seed, "merged": 0, "total": n_seed, "dim": dim}
        db = sqlite3.connect(str(delta_path))
        try:
            tables = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "delta" not in tables:
                return {"status": "noop", "reason": "no delta table",
                        "seed": n_seed, "merged": 0, "total": n_seed,
                        "dim": dim}
            new_ids, new_vecs, skipped = _read_delta(db, dim, set(ids))
            n_new = len(new_ids)
            if n_new == 0:
                if truncate and any(skipped.values()):
                    db.execute("DELETE FROM delta")
                    db.commit()
                    db.execute("VACUUM")
                return {"status": "noop", "reason": "delta has no new docs",
                        "seed": n_seed, "merged": 0, "total": n_seed,
                        "dim": dim, "skipped": skipped}

            total = n_seed + n_new
            code_bytes = int(np.packbits(np.zeros(dim, dtype=bool)).shape[0])

            def _write_rescore(tmp: Path) -> None:
                out = np.lib.format.open_memmap(
                    tmp, mode="w+", dtype=np.int8, shape=(total, dim))
                for start in range(0, n_seed, COPY_CHUNK):
                    stop = min(start + COPY_CHUNK, n_seed)
                    out[start:stop] = rescore[start:stop]
                out[n_seed:] = new_vecs
                out.flush()
                del out

            def _write_b1(tmp: Path) -> None:
                fresh = Index(ndim=dim, dtype="b1", metric="hamming")
                for start in range(0, n_seed, COPY_CHUNK):
                    stop = min(start + COPY_CHUNK, n_seed)
                    fresh.add(np.arange(start, stop, dtype=np.uint64),
                              _seed_bits(index, start, stop, code_bytes))
                fresh.add(np.arange(n_seed, total, dtype=np.uint64),
                          np.packbits(new_vecs > 0, axis=1))
                if len(fresh) != total:
                    raise DenseDeltaMergeError(
                        f"rebuilt b1 holds {len(fresh)} vectors, expected "
                        f"{total}")
                fresh.save(str(tmp))

            def _write_ids(tmp: Path) -> None:
                tmp.write_text(json.dumps(list(ids) + new_ids))

            tmp_rescore = _write_atomic(dense_dir / "rescore_int8.npy",
                                        _write_rescore)
            tmp_b1 = _write_atomic(dense_dir / "b1.usearch", _write_b1)
            tmp_ids = _write_atomic(dense_dir / "ids.json", _write_ids)

            del rescore
            try:
                index.reset()
            except Exception:
                logger.debug("seed b1 view not resettable; relying on "
                             "rename-over-mmap semantics")
            for tmp, name in ((tmp_rescore, "rescore_int8.npy"),
                              (tmp_b1, "b1.usearch"), (tmp_ids, "ids.json")):
                os.replace(tmp, dense_dir / name)
            dfd = os.open(dense_dir, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)

            if truncate:
                db.execute("DELETE FROM delta")
                db.commit()
                db.execute("VACUUM")
            info = {"status": "merged", "seed": n_seed, "merged": n_new,
                    "total": total, "dim": dim, "skipped": skipped,
                    "truncated": bool(truncate)}
            logger.info("dense delta merged: %s", info)
            return info
        finally:
            db.close()
    finally:
        for leftover in dense_dir.glob("*.tmp-%d" % os.getpid()):
            leftover.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=merge_dense_delta.__doc__)
    ap.add_argument("index_root")
    ap.add_argument("--keep-delta", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(merge_dense_delta(args.index_root,
                                       truncate=not args.keep_delta),
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
