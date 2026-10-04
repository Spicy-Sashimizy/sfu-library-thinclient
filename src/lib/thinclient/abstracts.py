"""Hot-section abstract sidecar — clustered zstd blocks with per-script dicts.

Policy (docs/THIN_CLIENT_STACK_RESEARCH.md, decided 2026-06-11):
  - HOT sections store abstracts locally so the reranker's top ~50-100
    candidates are fetchable offline at full quality.
  - COLD sections store nothing; the retriever fetches missing abstracts from
    the OpenAlex API before rerank (one mget of ~100 docs ≈ 150 KB).
  - Never rerank on titles alone — that's the one variant that measurably
    loses quality (~+0.12 NDCG@10 comes from title+abstract rerank).

Format v3 (the measured 64.7 -> 52.9 GB config at 150M):
  - abstracts are grouped by Unicode-script bucket and packed into ~32 KB
    uncompressed blocks, each compressed whole with the bucket's trained
    zstd-19 dictionary. Script bucketing captures the big per-language wins
    for free (held-out eval per_language_dicts_20260611: ru −40% / fa −38% /
    ko −37% / zh −32% vs the English dict — all non-Latin scripts; full
    langid measured too slow for the build path at ~95 docs/s).
  - a doc fetch decompresses one 32 KB block (sub-ms) and slices.
Readers transparently handle v1 (per-doc, single dict), v2 (per-doc, +ru
dict column) and v3 stores.

Format v3-flat (N5, measured 2026-08-02 — `docs/seismic_150m_testbed/
18_ORDINAL_ADDRESSING_DESIGN.md` §9): identical blocks, identical dictionaries,
identical locator table — only the compressed block *payloads* move out of the
`blocks` table into a flat `blocks.bin` read by `pread`, indexed by three
ordinal-style arrays. **2.82-2.89x faster `fetch()`** end-to-end at k=10-100
with a 20,000-id byte-parity gate, and ~2.2 GB smaller. The codec is untouched
deliberately: doc 17 §11 measured payload as 83% of the store, so changing it
would cost more than the envelope saves. The locator deliberately stays in
SQLite — §11 measured moving it to tantivy as a 27-54x regression on that stage.

A store is served flat only when its `<name>.flat/` sidecar directory exists,
so v3 stores keep working untouched and the two can coexist per section.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import zstandard

logger = logging.getLogger("sfu_library_mcp")

DICT_SIZE = 112 * 1024
COMPRESSION_LEVEL = 19
BLOCK_TARGET = 32 * 1024
TRAIN_TARGET_DOCS = 20_000
DICT_MIN_DOCS = 300
FLUSH_BYTES = 4 << 20
BLOCK_CACHE = 64

RU_DICT_ID = 1

FLAT_STAMP = "flat_store.json"
LOCATOR_STAMP = "locator.json"
DICTS_STAMP = "dicts.json"
FLAT_ID_KEY = "flat_store_id"

PREFAULT_ENV = "SFU_ABSTRACTS_PREFAULT"
_PAGE_BYTES = 4096

_SCRIPT_RANGES = (
    ("cyrillic", ((0x0400, 0x0500),)),
    ("han", ((0x4E00, 0xA000), (0x3400, 0x4DC0))),
    ("hangul", ((0xAC00, 0xD7B0), (0x1100, 0x1200))),
    ("arabic", ((0x0600, 0x0700), (0x0750, 0x0780), (0xFB50, 0xFE00))),
    ("kana", ((0x3040, 0x3100),)),
    ("greek", ((0x0370, 0x0400),)),
)


def script_bucket(text: str) -> str:
    """Dominant non-Latin script of the head of `text`, else 'latin'.
    ~µs per doc — the build-path-affordable stand-in for langid."""
    head = text[:300]
    if not head:
        return "latin"
    counts = dict.fromkeys((n for n, _ in _SCRIPT_RANGES), 0)
    for c in head:
        o = ord(c)
        for name, ranges in _SCRIPT_RANGES:
            if any(lo <= o < hi for lo, hi in ranges):
                counts[name] += 1
                break
    name, n = max(counts.items(), key=lambda kv: kv[1])
    return name if n > len(head) * 0.15 else "latin"


def _is_cyrillic(text: str) -> bool:
    return script_bucket(text) == "cyrillic"


class AbstractStoreWriter:
    """Build-time writer (v3). Buffers per script bucket, trains each bucket's
    dict at TRAIN_TARGET_DOCS (or finish), then packs ~32 KB blocks."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.executescript(
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=OFF;"
            "CREATE TABLE IF NOT EXISTS blocks (b INTEGER PRIMARY KEY, d INTEGER, z BLOB);"
            "CREATE TABLE IF NOT EXISTS docs (id TEXT PRIMARY KEY, b INTEGER,"
            "  off INTEGER, n INTEGER);"
            "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v BLOB);"
        )
        self._buffers: dict[str, list[tuple[str, bytes]]] = {}
        self._buffer_bytes: dict[str, int] = {}
        self._cctx: dict[str, zstandard.ZstdCompressor] = {}
        self._dict_names: list[str] = []
        self._next_block = 0
        self._n = 0
        self._restore()

    def _restore(self) -> None:
        """Resume from a checkpoint()ed store: dict ids are positional, so the
        bucket order, the trained dicts, and the not-yet-flushed pending
        buffers must all come back exactly as persisted."""
        row = self._db.execute("SELECT v FROM meta WHERE k='dicts'").fetchone()
        if row is None:
            return
        self._dict_names = json.loads(row[0])
        latin_row = self._db.execute(
            "SELECT v FROM meta WHERE k='zdict_latin'").fetchone()
        latin = (zstandard.ZstdCompressionDict(latin_row[0])
                 if latin_row else None)
        for name in self._dict_names:
            r = self._db.execute("SELECT v FROM meta WHERE k=?",
                                 (f"zdict_{name}",)).fetchone()
            zd = zstandard.ZstdCompressionDict(r[0]) if r else latin
            self._cctx[name] = (zstandard.ZstdCompressor(
                level=COMPRESSION_LEVEL, dict_data=zd) if zd
                else zstandard.ZstdCompressor(level=COMPRESSION_LEVEL))
        for (k, v) in self._db.execute(
                "SELECT k, v FROM meta WHERE k LIKE 'pending_%'").fetchall():
            bucket = k[len("pending_"):]
            docs = json.loads(zstandard.ZstdDecompressor().decompress(v))
            self._buffers[bucket] = [(i, a.encode("utf-8")) for i, a in docs]
            self._buffer_bytes[bucket] = sum(len(d) for _, d in
                                             self._buffers[bucket])
        self._next_block = self._db.execute(
            "SELECT COALESCE(MAX(b)+1, 0) FROM blocks").fetchone()[0]
        self._n = self._db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        logger.info("abstract store %s: resumed at block %d, %d docs, "
                    "%d pending buffers", self.path.name, self._next_block,
                    self._n, len(self._buffers))

    def add(self, doc_id: str, abstract: str) -> None:
        if not abstract:
            return
        bucket = script_bucket(abstract)
        buf = self._buffers.setdefault(bucket, [])
        data = abstract.encode("utf-8")
        buf.append((doc_id, data))
        self._buffer_bytes[bucket] = self._buffer_bytes.get(bucket, 0) + len(data)
        if bucket in self._cctx:
            if self._buffer_bytes[bucket] >= FLUSH_BYTES:
                self._flush(bucket)
        elif len(buf) >= TRAIN_TARGET_DOCS:
            self._train(bucket)
            self._flush(bucket)

    def _train(self, bucket: str) -> None:
        samples = [d for _, d in self._buffers.get(bucket, [])]
        cctx = None
        if len(samples) >= DICT_MIN_DOCS:
            try:
                zdict = zstandard.train_dictionary(DICT_SIZE, samples)
                self._db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                                 (f"zdict_{bucket}", zdict.as_bytes()))
                cctx = zstandard.ZstdCompressor(level=COMPRESSION_LEVEL,
                                                dict_data=zdict)
                logger.info("abstract store %s: trained %s dict on %d samples",
                            self.path.name, bucket, len(samples))
            except zstandard.ZstdError as exc:
                logger.warning("%s dict training failed (%s)", bucket, exc)
        if cctx is None:
            cctx = self._cctx.get("latin") or zstandard.ZstdCompressor(
                level=COMPRESSION_LEVEL)
        self._cctx[bucket] = cctx
        if bucket not in self._dict_names:
            self._dict_names.append(bucket)

    def _dict_id(self, bucket: str) -> int:
        return self._dict_names.index(bucket)

    def _flush(self, bucket: str) -> None:
        """Pack the bucket's buffer into ~BLOCK_TARGET uncompressed blocks."""
        buf = self._buffers.get(bucket, [])
        if not buf:
            return
        dedup = dict(buf)
        if len(dedup) < len(buf):
            buf[:] = list(dedup.items())
        cctx, did = self._cctx[bucket], self._dict_id(bucket)
        i = 0
        while i < len(buf):
            payload = bytearray()
            rows = []
            while i < len(buf) and len(payload) < BLOCK_TARGET:
                doc_id, data = buf[i]
                rows.append((doc_id, self._next_block, len(payload), len(data)))
                payload += data
                i += 1
            self._db.execute("INSERT INTO blocks VALUES (?,?,?)",
                             (self._next_block, did, cctx.compress(bytes(payload))))
            self._db.executemany("INSERT OR REPLACE INTO docs VALUES (?,?,?,?)",
                                 rows)
            self._next_block += 1
            self._n += len(rows)
        buf.clear()
        self._buffer_bytes[bucket] = 0
        if self._n % 200_000 < TRAIN_TARGET_DOCS:
            self._db.commit()

    def checkpoint(self) -> None:
        """Durability point for the per-slice build resume: flush trained
        buckets, persist untrained buckets' raw buffers (training quality
        needs the full TRAIN_TARGET_DOCS sample, so don't train early), and
        commit. _restore() is the inverse."""
        for bucket in list(self._buffers):
            if bucket in self._cctx:
                self._flush(bucket)
        self._db.execute("DELETE FROM meta WHERE k LIKE 'pending_%'")
        for bucket, buf in self._buffers.items():
            if not buf:
                continue
            payload = json.dumps([(i, d.decode("utf-8"))
                                  for i, d in dict(buf).items()])
            self._db.execute(
                "INSERT OR REPLACE INTO meta VALUES (?, ?)",
                (f"pending_{bucket}",
                 zstandard.ZstdCompressor(level=3).compress(payload.encode())))
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('dicts', ?)",
                         (json.dumps(self._dict_names),))
        self._db.commit()
        self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def finish(self) -> int:
        order = sorted(self._buffers, key=lambda b: b != "latin")
        for bucket in order:
            if bucket not in self._cctx:
                self._train(bucket)
            self._flush(bucket)
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('format', 'v3')")
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('dicts', ?)",
                         (json.dumps(self._dict_names),))
        self._db.execute("DELETE FROM meta WHERE k LIKE 'pending_%'")
        self._db.execute("DELETE FROM blocks WHERE b NOT IN "
                         "(SELECT DISTINCT b FROM docs)")
        self._db.commit()
        self._db.execute("PRAGMA journal_mode=DELETE")
        self._db.execute("VACUUM")
        self._db.close()
        return self._n


def build_flat_sidecar(src: Path, out: Path | None = None,
                       log_every: int = 50_000) -> dict:
    """Derive the N5 flat block store from a built v3 `abstracts.sqlite`.

    Purely additive: the source is opened READ-ONLY and nothing about it
    changes, so a section can be reverted by deleting the sidecar directory.
    Blocks stream in `b` order, so this is sequential on both sides and never
    holds the corpus in RAM (11.13 GB / 1,062,917 blocks in 878 s for
    `social_sciences__recent`, measured 2026-08-02).
    """
    import numpy as np

    src = Path(src)
    out = Path(out) if out else src.with_suffix(src.suffix + ".flat")
    out.mkdir(parents=True, exist_ok=True)
    src_st = src.stat()
    flat_id = str(uuid.uuid4())
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        max_b = db.execute("SELECT max(b) FROM blocks").fetchone()[0]
        if max_b is None:
            raise ValueError(f"{src} has no blocks — not a v3 store")
        n_slots = max_b + 1
        offsets = np.full(n_slots, -1, dtype=np.int64)
        lengths = np.zeros(n_slots, dtype=np.int32)
        dict_ids = np.zeros(n_slots, dtype=np.int8)

        pos = n = 0
        tmp = out / "blocks.bin.partial"
        with open(tmp, "wb", buffering=1 << 22) as fout:
            for b, d, z in db.execute("SELECT b, d, z FROM blocks ORDER BY b"):
                fout.write(z)
                offsets[b], lengths[b], dict_ids[b] = pos, len(z), d
                pos += len(z)
                n += 1
                if log_every and n % log_every == 0:
                    logger.info("flat sidecar %s: %d blocks, %.2f GB",
                                src.name, n, pos / 1e9)
        np.save(out / "block_offsets.npy", offsets)
        np.save(out / "block_lengths.npy", lengths)
        np.save(out / "block_dictids.npy", dict_ids)
        tmp.rename(out / "blocks.bin")
    finally:
        db.close()
    stamp = {FLAT_ID_KEY: flat_id,
             "built_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "blocks": n, "slots": n_slots, "bytes": pos,
             "source": {"path": str(src), "bytes": src_st.st_size,
                        "mtime_ns": src_st.st_mtime_ns}}
    (out / FLAT_STAMP).write_text(json.dumps(stamp, indent=2))
    dump_dict_sidecar(src, out)
    return {"blocks": n, "slots": n_slots, "bytes": pos, "path": str(out),
            FLAT_ID_KEY: flat_id}


class AbstractLocatorMismatch(RuntimeError):
    """The locator arrays cannot be proven to address these `blocks.bin`.

    Raised instead of serving a plausible WRONG abstract. See the FLAT_ID_KEY
    comment and doc 18 §17; this is the abstract-store twin of
    `OrdinalSpaceMismatch`.
    """


def _encode_wid(doc_id: str) -> int | None:
    """`W2031234567` -> 2031234567, or None when the id wouldn't round-trip.

    Inlined mirror of `builder.encode_meta_id` (importing it would be circular:
    builder imports this module). The two MUST agree on the leading-zero
    rejection: if they drift, "W0123" resolves to the ordinal of the DIFFERENT
    document "W123", passes the verification read, and returns the wrong
    abstract silently — doc 18's first real bug, now guarded by
    test_abstract_locator.test_encoder_agrees_with_the_builder.
    """
    if len(doc_id) > 1 and doc_id[0] == "W":
        digits = doc_id[1:]
        if digits.isdigit() and digits[0] != "0":
            return int(digits)
    return None


def _touch_pages(arr) -> tuple[int, int]:
    """Fault in every page of one mmap'd locator column, sequentially.

    Returns `(bytes_touched, checksum)`. The checksum is an anti-DCE accumulator
    (the F6 `touch_bytes` pattern): reading one byte per 4 KiB page is the whole
    point, so the result has to be consumed or numpy is free not to do the read.
    `madvise(MADV_WILLNEED)` is issued first where the platform has it — it is
    advisory *readahead*, asynchronous and unguaranteed, so the strided read is
    what actually establishes residency; the advice just lets the kernel batch
    the I/O instead of servicing ~103k separate minor faults.

    Residency-only: no byte of any column changes, so a store with the gate on
    returns bit-identical abstracts to one with it off, by construction.
    """
    import mmap as _mmap

    import numpy as np

    mm = getattr(arr, "_mmap", None)
    advise = getattr(mm, "madvise", None)
    if advise is not None and hasattr(_mmap, "MADV_WILLNEED"):
        try:
            advise(_mmap.MADV_WILLNEED)
        except (OSError, ValueError):
            pass
    flat = np.asarray(arr).reshape(-1).view(np.uint8)
    if flat.size == 0:
        return 0, 0
    return int(flat.nbytes), int(flat[::_PAGE_BYTES].sum(dtype=np.int64))


class AbstractLocator:
    """`W-id -> (block, offset, length)` for a flat abstract store, replacing
    the SQLite `docs` B-tree over 23.4M variable-length TEXT keys with a
    `searchsorted` over a sorted int64 array + three parallel columns (doc 18
    §16: p50 5.53x, mean 2.09x, parity PASS).

    The identity gate below is the whole reason this is a class and not four
    `np.load`s. A locator addresses INTO `blocks.bin`; paired with a
    `blocks.bin` from a different build its (block, offset) pairs point at the
    wrong bytes and it returns a real, plausible, WRONG abstract with no error
    — ordinals hazard 1 (doc 18 §6 risk 1) in the abstract store. So it refuses
    to load unless the `flat_store_id` it was stamped with matches the one
    `build_flat_sidecar` stamped into the blocks it is about to address. It
    fails closed: a missing stamp on either side is a refusal, never a
    best-effort pairing, and there is no override flag by design.
    """

    def __init__(self, flat_dir: str | Path):
        import numpy as np

        self.flat_dir = Path(flat_dir)
        loc_path = self.flat_dir / LOCATOR_STAMP
        if not loc_path.exists():
            raise AbstractLocatorMismatch(
                f"{loc_path} is missing — the arrays carry no identity, so they "
                f"cannot be proven to address these blocks. Rebuild them with "
                f"build_ordinal_locator, which writes the stamp last.")
        self.stamp = json.loads(loc_path.read_text())

        flat_path = self.flat_dir / FLAT_STAMP
        if not flat_path.exists():
            raise AbstractLocatorMismatch(
                f"{flat_path} is missing — the flat blocks carry no identity, "
                f"so the locator cannot be shown to address them. Refusing: a "
                f"mismatched pair returns the WRONG abstract with no error "
                f"(doc 18 §6 risk 1).")
        flat = json.loads(flat_path.read_text())
        want, got = flat.get(FLAT_ID_KEY), self.stamp.get(FLAT_ID_KEY)
        if not got:
            raise AbstractLocatorMismatch(f"{loc_path} has no {FLAT_ID_KEY!r}")
        if not want:
            raise AbstractLocatorMismatch(
                f"{flat_path} has no {FLAT_ID_KEY!r}, so the blocks cannot be "
                f"shown to share an identity with {loc_path}.")
        if want != got:
            raise AbstractLocatorMismatch(
                f"abstract locator mismatch: blocks {want!r} != locator {got!r} "
                f"({self.flat_dir}). The locator was built against a different "
                f"blocks.bin; its (block, offset) pairs address the wrong bytes. "
                f"Rebuild the locator against these blocks.")

        self.rows = int(self.stamp["rows"])
        for name in ("wids", "b", "off", "n"):
            arr = np.load(self.flat_dir / f"loc_{name}.npy", mmap_mode="r")
            if len(arr) != self.rows:
                raise AbstractLocatorMismatch(
                    f"loc_{name}.npy holds {len(arr)} entries but the stamp "
                    f"declares {self.rows} — the locator is truncated or the "
                    f"stamp is stale; the tail addresses nothing.")
            setattr(self, name, arr)
        logger.info("abstract locator %s loaded: %d rows from %s",
                    got, self.rows, self.flat_dir)

    def prefault(self) -> dict:
        """Touch all four locator columns once at load (doc 18 §23 mitigation).

        J1 (§23) measured the negative this exists for: a freshly started
        process serving flat is **0.919x** sqlite until its 421 MB of mmap'd
        `loc_*.npy` are resident — flat p95 9.597 ms vs sqlite's 3.526, gone by
        the next run. Faulting the columns in one sequential pass here moves
        that cost out of the first queries and into a bounded, measurable load
        step. IMPLEMENTED 2026-08-18, EFFICACY UNMEASURED (see the docstring
        note in `AbstractStore._open_locator`).

        FAIL-OPEN, and deliberately so: pre-faulting cannot change an answer
        (it reads read-only pages and writes nothing), so no failure of it is a
        reason to refuse to serve. Any error is logged and recorded in the
        returned dict; the store carries on with a cold locator, i.e. exactly
        the gate-off behaviour. This is the opposite of the identity gate above,
        which fails CLOSED because that one *can* return wrong bytes.

        Returns `{"bytes", "ms", "columns", "checksum", "error"}`.
        """
        t0 = time.perf_counter()
        stats: dict = {"bytes": 0, "ms": 0.0, "columns": 0,
                       "checksum": 0, "error": None}
        try:
            for name in ("wids", "b", "off", "n"):
                arr = getattr(self, name, None)
                if arr is None:
                    continue
                nbytes, chk = _touch_pages(arr)
                stats["bytes"] += nbytes
                stats["checksum"] ^= chk
                stats["columns"] += 1
        except Exception as exc:      # noqa: BLE001 — fail-open by contract
            stats["error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("abstract locator %s: pre-fault failed (%s) — serving "
                           "with a cold locator (first-touch cost unchanged)",
                           self.flat_dir, stats["error"])
        stats["ms"] = (time.perf_counter() - t0) * 1e3
        if stats["error"] is None:
            logger.info("abstract locator %s: pre-faulted %.1f MB across %d "
                        "columns in %.0f ms (%s=1)", self.flat_dir,
                        stats["bytes"] / 1e6, stats["columns"], stats["ms"],
                        PREFAULT_ENV)
        return stats

    def lookup(self, ids: list[str]):
        """`W-id -> (positions, found)`. `found` is the verification read that
        makes a miss visible; `positions` is meaningless where `found` is False.
        Mirrors `OrdinalSpace.lookup` exactly."""
        import numpy as np

        nums = np.empty(len(ids), dtype=np.int64)
        valid = np.zeros(len(ids), dtype=bool)
        for i, s in enumerate(ids):
            w = _encode_wid(s)
            if w is not None:
                nums[i], valid[i] = w, True
        if self.rows == 0:
            return np.zeros(len(ids), dtype=np.int64), valid & False
        pos = np.clip(np.searchsorted(self.wids, nums), 0, self.rows - 1)
        found = valid & (self.wids[pos] == nums)
        return pos, found


def build_ordinal_locator(src: Path, flat_dir: Path | None = None) -> dict:
    """Build the SQLite-free block locator for a flat abstract store: a sorted
    section-local W-id array + parallel (b, off, n) columns, written INTO the
    flat sidecar beside `blocks.bin` (doc 18 §16).

    Read-only against `src`. Binds the locator to the exact blocks it will
    address by copying the `flat_store_id` `build_flat_sidecar` minted, and
    refuses to build against a source that did not produce those blocks (stat
    mismatch) — otherwise the copied id would certify a false pairing.
    """
    import numpy as np

    src = Path(src)
    flat_dir = Path(flat_dir) if flat_dir else src.with_suffix(src.suffix + ".flat")
    flat_path = flat_dir / FLAT_STAMP
    if not flat_path.exists():
        raise FileNotFoundError(
            f"{flat_path} is missing — build the flat sidecar first "
            f"(build_flat_sidecar), which mints the identity the locator binds "
            f"to.")
    flat = json.loads(flat_path.read_text())
    flat_id = flat.get(FLAT_ID_KEY)
    if not flat_id:
        raise ValueError(f"{flat_path} carries no {FLAT_ID_KEY!r}")
    recorded, st = flat.get("source", {}), src.stat()
    if (recorded.get("bytes") != st.st_size
            or recorded.get("mtime_ns") != st.st_mtime_ns):
        raise ValueError(
            f"{src} is not the source build_flat_sidecar recorded for these "
            f"blocks ({recorded}); a locator built here would certify a false "
            f"pairing. Rebuild the flat sidecar from this src, or point src at "
            f"the recorded source.")

    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        n_rows = db.execute("SELECT count(*) FROM docs").fetchone()[0]
        mx_b, mx_off, mx_n = db.execute(
            "SELECT max(b), max(off), max(n) FROM docs").fetchone()
        off_dt = np.uint16 if (mx_off or 0) < 2 ** 16 else np.uint32
        n_dt = np.uint16 if (mx_n or 0) < 2 ** 16 else np.uint32
        b_dt = np.uint32 if (mx_b or 0) < 2 ** 32 else np.uint64

        wids = np.zeros(n_rows, dtype=np.int64)
        bs = np.zeros(n_rows, dtype=b_dt)
        offs = np.zeros(n_rows, dtype=off_dt)
        ns = np.zeros(n_rows, dtype=n_dt)

        i = 0
        skipped: list[str] = []
        for did, b, off, n in db.execute("SELECT id, b, off, n FROM docs"):
            w = _encode_wid(did)
            if w is None:
                skipped.append(did)
                continue
            wids[i], bs[i], offs[i], ns[i] = w, b, off, n
            i += 1
        if skipped:
            logger.warning("abstract locator: %d ids are not plain W-numbers "
                           "(e.g. %s) — the locator cannot address them; they "
                           "keep the SQLite docs path", len(skipped), skipped[:3])
        wids, bs, offs, ns = wids[:i], bs[:i], offs[:i], ns[:i]

        order = np.argsort(wids, kind="stable")
        wids, bs, offs, ns = wids[order], bs[order], offs[order], ns[order]
        if i and not np.all(np.diff(wids) > 0):
            raise ValueError("W-ids are not strictly increasing after sort — "
                             "duplicate ids would make the lookup ambiguous")
        for name, arr in (("wids", wids), ("b", bs), ("off", offs), ("n", ns)):
            if len(arr) != i:
                raise ValueError(f"loc_{name} is {len(arr)}, expected {i}")
            np.save(flat_dir / f"loc_{name}.npy", arr)
    finally:
        db.close()

    total = sum((flat_dir / f"loc_{k}.npy").stat().st_size
                for k in ("wids", "b", "off", "n"))
    stamp = {
        FLAT_ID_KEY: flat_id,
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rows": int(i),
        "skipped_non_wid": len(skipped),
        "bytes": int(total),
        "bytes_per_doc": round(total / max(i, 1), 2),
        "dtypes": {"b": str(np.dtype(b_dt)), "off": str(np.dtype(off_dt)),
                   "n": str(np.dtype(n_dt))},
        "source": {"path": str(src), "bytes": st.st_size,
                   "mtime_ns": st.st_mtime_ns},
        "note": ("delete abstracts.sqlite only when skipped_non_wid == 0 AND "
                 "the zstd dicts (meta table) have been rehomed beside "
                 "blocks.bin — until then the SQLite file is still load-bearing"),
    }
    (flat_dir / LOCATOR_STAMP).write_text(json.dumps(stamp, indent=2))
    return stamp


def dump_dict_sidecar(src: Path, flat_dir: Path | None = None) -> dict:
    """Copy the trained zstd dictionaries out of the source `meta` table into
    the flat sidecar, so a section can be served with `abstracts.sqlite`
    DELETED (the dicts are the only other thing `AbstractStore.__init__` reads
    from SQLite). Read-only against `src`.

    The dicts decode `blocks.bin`, so a wrong set produces garbage — zstd
    usually catches this itself (a dictionary-id mismatch raises), but the
    sidecar is bound to the flat store's identity anyway, defence in depth.
    Files are named exactly as the reader looks them up (`zdict_<name>`,
    `zdict_latin`), so the sidecar and SQLite dict-loading paths differ only in
    where the bytes come from.
    """
    src = Path(src)
    flat_dir = Path(flat_dir) if flat_dir else src.with_suffix(src.suffix + ".flat")
    flat_path = flat_dir / FLAT_STAMP
    if not flat_path.exists():
        raise FileNotFoundError(
            f"{flat_path} is missing — build the flat sidecar first "
            f"(build_flat_sidecar), which mints the identity the dicts bind to.")
    flat_id = json.loads(flat_path.read_text()).get(FLAT_ID_KEY)
    if not flat_id:
        raise ValueError(f"{flat_path} carries no {FLAT_ID_KEY!r}")

    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        fmt_row = db.execute("SELECT v FROM meta WHERE k='format'").fetchone()
        names_row = db.execute("SELECT v FROM meta WHERE k='dicts'").fetchone()
        fmt = fmt_row[0] if fmt_row else ("v3" if names_row else "v1")
        names = json.loads(names_row[0]) if names_row else []
        files: list[str] = []
        for (k, v) in db.execute("SELECT k, v FROM meta WHERE k LIKE 'zdict%'"):
            (flat_dir / k).write_bytes(v)
            files.append(k)
    finally:
        db.close()

    meta = {FLAT_ID_KEY: flat_id, "built_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "format": fmt, "names": names, "files": sorted(files)}
    (flat_dir / DICTS_STAMP).write_text(json.dumps(meta, indent=2))
    logger.info("abstracts: rehomed %d dicts (%s) into %s", len(files), fmt, flat_dir)
    return meta


class AbstractStore:
    """Query-time reader for v1/v2/v3 stores (thread-safe)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._block_cache: OrderedDict[int, bytes] = OrderedDict()
        self._flat = None
        self._locator = None
        self.prefault_stats: dict | None = None
        flat_dir = self.path.with_suffix(self.path.suffix + ".flat")

        self._sqlite_free = ((flat_dir / DICTS_STAMP).exists()
                             and not self.path.exists())
        if not self.path.exists() and not self._sqlite_free:
            raise FileNotFoundError(
                f"{self.path} does not exist and {flat_dir / DICTS_STAMP} is "
                f"missing — cannot open a SQLite-free store without the "
                f"rehomed dicts (doc 18 §18).")

        if self._sqlite_free:
            self._db = None
            self._v3 = True
            self._has_docs = False
            self._load_dicts_from_sidecar(flat_dir)
            self._open_flat(flat_dir)
            if self._flat is None:
                raise RuntimeError(
                    f"{self.path}: SQLite-free store but the flat sidecar "
                    f"{flat_dir} is unusable — there are no payloads to serve.")
            self._open_locator(flat_dir)
            if self._locator is None:
                raise RuntimeError(
                    f"{self.path}: SQLite-free store has no ordinal locator; "
                    f"without `docs` there is no way to resolve block addresses. "
                    f"Run build_ordinal_locator before deleting abstracts.sqlite.")
            return

        self._db = sqlite3.connect(Path(self.path).resolve().as_uri() + "?mode=ro", uri=True,
                                   check_same_thread=False)
        tables = {r[0] for r in self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self._v3 = "docs" in tables or "blocks" in tables
        self._has_docs = "docs" in tables

        if self._v3:
            if (flat_dir / DICTS_STAMP).exists():
                self._load_dicts_from_sidecar(flat_dir)
            else:
                self._load_dicts_from_sqlite()
        else:
            def _zdict(key: str):
                row = self._db.execute(
                    "SELECT v FROM meta WHERE k=?", (key,)).fetchone()
                return zstandard.ZstdCompressionDict(row[0]) if row else None
            zd = _zdict("zdict")
            main = (zstandard.ZstdDecompressor(dict_data=zd) if zd
                    else zstandard.ZstdDecompressor())
            zru = _zdict("zdict_ru")
            self._dctxs = {0: main,
                           RU_DICT_ID: (zstandard.ZstdDecompressor(dict_data=zru)
                                        if zru else main)}
            cols = [r[1] for r in self._db.execute("PRAGMA table_info(abs)")]
            self._has_dict_col = "d" in cols

        if self._v3 and flat_dir.is_dir():
            self._open_flat(flat_dir)
            if self._flat is not None:
                self._open_locator(flat_dir)


    @staticmethod
    def _build_v3_dctxs(zdict_fn, names: list[str]) -> dict:
        """Positional dict-id -> decompressor. `zdict_fn(key)` returns a
        `ZstdCompressionDict` or None; a bucket with no dict of its own shares
        latin, and a store trained below the bar shares the plain codec. Shared
        by both dict sources so they cannot drift."""
        plain = zstandard.ZstdDecompressor()
        latin = zdict_fn("zdict_latin")
        dctxs = {}
        for i, name in enumerate(names):
            zd = zdict_fn(f"zdict_{name}") or latin
            dctxs[i] = (zstandard.ZstdDecompressor(dict_data=zd) if zd else plain)
        return dctxs

    def _load_dicts_from_sqlite(self) -> None:
        def _zdict(key: str):
            row = self._db.execute(
                "SELECT v FROM meta WHERE k=?", (key,)).fetchone()
            return zstandard.ZstdCompressionDict(row[0]) if row else None
        names = json.loads(self._db.execute(
            "SELECT v FROM meta WHERE k='dicts'").fetchone()[0])
        self._dctxs = self._build_v3_dctxs(_zdict, names)

    def _load_dicts_from_sidecar(self, flat_dir: Path) -> None:
        """Load the rehomed dicts (doc 18 §18). Identity-checked against the
        blocks the same way the locator is — a dict set from a different build
        would otherwise decode `blocks.bin` into garbage."""
        meta = json.loads((flat_dir / DICTS_STAMP).read_text())
        self._require_flat_identity(flat_dir, meta.get(FLAT_ID_KEY), DICTS_STAMP)

        def _zdict(key: str):
            p = flat_dir / key
            return zstandard.ZstdCompressionDict(p.read_bytes()) if p.exists() else None
        self._dctxs = self._build_v3_dctxs(_zdict, meta["names"])

    @staticmethod
    def _require_flat_identity(flat_dir: Path, got: str | None, which: str) -> None:
        flat_path = flat_dir / FLAT_STAMP
        if not flat_path.exists():
            raise AbstractLocatorMismatch(
                f"{flat_path} is missing — the blocks carry no identity, so "
                f"{which} cannot be proven to belong to them.")
        want = json.loads(flat_path.read_text()).get(FLAT_ID_KEY)
        if not want or not got or want != got:
            raise AbstractLocatorMismatch(
                f"{which} identity {got!r} != blocks {want!r} in {flat_dir}; "
                f"the sidecar was built against different blocks.")

    def _open_flat(self, flat_dir: Path) -> None:
        """Attach the N5 flat block file. Only the payload source changes: the
        dictionaries still come from the sqlite `meta` table and the locator
        still comes from `docs`, so a flat store and its v3 parent return
        byte-identical abstracts by construction."""
        import os

        import numpy as np

        try:
            off = np.load(flat_dir / "block_offsets.npy", mmap_mode="r")
            ln = np.load(flat_dir / "block_lengths.npy", mmap_mode="r")
            did = np.load(flat_dir / "block_dictids.npy", mmap_mode="r")
            fd = os.open(str(flat_dir / "blocks.bin"), os.O_RDONLY)
        except (OSError, ValueError, EOFError) as exc:
            has_blocks = self._db and self._db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='blocks'"
            ).fetchone()
            if not has_blocks:
                raise RuntimeError(
                    f"{self.path}: flat sidecar {flat_dir} is unusable ({exc}) "
                    f"and there is no `blocks` table to fall back to — this "
                    f"store has no payloads left. Restore the sidecar or "
                    f"rebuild.") from exc
            logger.warning("abstracts: flat sidecar %s unusable (%s); "
                           "serving the v3 blocks table", flat_dir, exc)
            return
        self._flat = {"off": off, "len": ln, "did": did, "fd": fd}
        logger.info("abstracts: %s serving %d blocks from flat store",
                    self.path.name, len(off))

    def _open_locator(self, flat_dir: Path) -> None:
        """Attach the ordinal locator (doc 18 §17) when it is present AND its
        identity is proven against these blocks.

        Absent locator (no `locator.json`): serve via the SQLite `docs` table,
        no error — the pre-consolidation default. Present-but-mismatched
        locator: `AbstractLocator` RAISES, and this does not catch it. Unlike a
        half-built flat sidecar (which falls back losslessly to the v3 blocks
        table), a mismatched locator loads fine and returns wrong abstracts, so
        the only safe response is to refuse loudly — the operator built it to be
        used, and using the wrong one is the failure this gate exists for.

        `SFU_ABSTRACTS_PREFAULT=1` additionally pre-faults the locator columns
        here (doc 18 §23's mitigation for the 0.919x first-touch regression).
        Default OFF, residency-only when on, fail-open. **IMPLEMENTED
        2026-08-18, EFFICACY UNMEASURED** — the first-touch re-measurement is
        pending via `scripts/seismic_testbed/j1_flat_sidecar_serving_ab.py`
        (its first-touch phase) on an idle machine."""
        import os

        if not (flat_dir / LOCATOR_STAMP).exists():
            return
        self._locator = AbstractLocator(flat_dir)
        logger.info("abstracts: %s serving the ordinal locator (%d rows) — "
                    "block lookups no longer touch SQLite", self.path.name,
                    self._locator.rows)
        if os.environ.get(PREFAULT_ENV, "0") == "1":
            self.prefault_stats = self._locator.prefault()

    def _block_flat(self, b: int) -> bytes:
        import os

        f = self._flat
        offset = int(f["off"][b])
        if offset < 0:
            raise KeyError(f"block {b} absent from the flat store {self.path}")
        z = os.pread(f["fd"], int(f["len"][b]), offset)
        return self._dctxs.get(int(f["did"][b]), self._dctxs[0]).decompress(z)

    def _block(self, b: int) -> bytes:
        cached = self._block_cache.get(b)
        if cached is not None:
            self._block_cache.move_to_end(b)
            return cached
        if self._flat is not None:
            payload = self._block_flat(b)
        else:
            d, z = self._db.execute(
                "SELECT d, z FROM blocks WHERE b=?", (b,)).fetchone()
            payload = self._dctxs.get(d, self._dctxs[0]).decompress(z)
        self._block_cache[b] = payload
        if len(self._block_cache) > BLOCK_CACHE:
            self._block_cache.popitem(last=False)
        return payload

    def _fetch_via_docs(self, chunk: list[str], out: dict[str, str]) -> None:
        """v3 SQLite locator: resolve (block, offset, length) from the `docs`
        table, then slice the (flat or SQLite) block. Also the ordinal
        locator's miss path — ids it cannot address keep this route."""
        marks = ",".join("?" * len(chunk))
        for doc_id, b, off, n in self._db.execute(
                f"SELECT id, b, off, n FROM docs WHERE id IN ({marks})", chunk):
            out[doc_id] = self._block(b)[off:off + n].decode("utf-8")

    def _fetch_via_locator(self, ids: list[str], out: dict[str, str]) -> None:
        """flat blocks + ordinal locator — the SQLite-free block lookup
        (doc 18 §17). Byte-identical to the `docs` path by construction: same
        blocks, same (b, off, n), only the index structure changes."""
        loc = self._locator
        pos, found = loc.lookup(ids)
        miss: list[str] = []
        for i, did in enumerate(ids):
            if not found[i]:
                miss.append(did)
                continue
            p = int(pos[i])
            blk = self._block(int(loc.b[p]))
            o, n = int(loc.off[p]), int(loc.n[p])
            out[did] = blk[o:o + n].decode("utf-8")
        if miss and self._has_docs:
            for s in range(0, len(miss), 500):
                self._fetch_via_docs(miss[s:s + 500], out)

    def fetch(self, ids: list[str]) -> dict[str, str]:
        """Return {id: abstract} for ids present in this store."""
        out: dict[str, str] = {}
        with self._lock:
            if self._locator is not None:
                self._fetch_via_locator(ids, out)
            elif self._v3:
                for s in range(0, len(ids), 500):
                    self._fetch_via_docs(ids[s:s + 500], out)
            else:
                for s in range(0, len(ids), 500):
                    chunk = ids[s:s + 500]
                    marks = ",".join("?" * len(chunk))
                    sel = ("SELECT id, z, d FROM abs" if self._has_dict_col
                           else "SELECT id, z, 0 FROM abs")
                    for doc_id, z, d in self._db.execute(
                            f"{sel} WHERE id IN ({marks})", chunk):
                        dctx = self._dctxs.get(d, self._dctxs[0])
                        out[doc_id] = dctx.decompress(z).decode("utf-8")
        return out
