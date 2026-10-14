"""Base-side `is_oa` override (delta-ingest issue O17, option (a)).

The base `meta.sqlite` / tantivy `is_oa` column was never populated (0 of
150,413,098 rows set). This module serves a three-state bitmap built from one
pass over an OpenAlex snapshot (`spike/delta_ingest/oa_bitmap.py`) as an
override of that column, without reindexing the base.

Artifact (a directory, outside the read-only base; gate `SFU_OA_BITMAP`):

    oa_bitmap.json   stamp: format, rows, ordinal_space_id, ordinal_dir,
                     meta_source {bytes, mtime_ns}, bitmap_id, coverage, source
    known.npy        uint8, packbits(bitorder="little") over base ordinals:
                     1 = the snapshot pass saw this base doc
    oa.npy           same layout: 1 = open_access.is_oa was true (only
                     meaningful where `known` is 1)

Base ordinals are the `wids.npy` order of an ordinal space
(`lib.thinclient.ordinals`); the bitmap names the ordinal directory it was
built against and refuses to load unless that directory's `ordinal_space_id`
matches its own and the served `meta.sqlite` has the size and mtime the
ordinal space was built from. A mismatch raises (fails closed), as the
ordinal reader does.

States per base doc: known-OA (True), known-not-OA (False), unknown (None).
Unknown is never reported as False: hydrated rows carry `None`, and the
`open_access_only` filter keeps known-OA docs only.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV = "SFU_OA_BITMAP"
FORMAT = "oa_bitmap/1"
STAMP_FILE = "oa_bitmap.json"
KNOWN_FILE = "known.npy"
OA_FILE = "oa.npy"
ORDINAL_STAMP = "ordinal_space.json"


class OABitmapMismatch(RuntimeError):
    """The bitmap cannot be shown to address the served base."""


def meta_fingerprint(meta_path: str | Path) -> dict:
    st = Path(meta_path).stat()
    return {"bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns)}


class OAOverlay:
    """Three-state `is_oa` lookup by W-id over base ordinals."""

    def __init__(self, path: str | Path, *, meta_path: str | Path | None = None,
                 manifest: dict[str, Any] | None = None):
        import numpy as np

        self.path = Path(path)
        stamp_path = self.path / STAMP_FILE
        if not stamp_path.exists():
            raise OABitmapMismatch(f"{stamp_path} is missing")
        self.stamp = json.loads(stamp_path.read_text())
        if self.stamp.get("format") != FORMAT:
            raise OABitmapMismatch(
                f"{stamp_path}: format {self.stamp.get('format')!r} != {FORMAT!r}")
        self.rows = int(self.stamp["rows"])
        self.space_id = self.stamp.get("ordinal_space_id")
        self.bitmap_id = str(self.stamp.get("bitmap_id") or "")
        if not self.space_id or not self.bitmap_id:
            raise OABitmapMismatch(f"{stamp_path} lacks ordinal_space_id/bitmap_id")

        odir = Path(self.stamp["ordinal_dir"])
        if not odir.is_absolute():
            odir = self.path / odir
        ostamp = odir / ORDINAL_STAMP
        if not ostamp.exists():
            raise OABitmapMismatch(f"ordinal stamp {ostamp} is missing")
        ospace = json.loads(ostamp.read_text())
        if ospace.get("ordinal_space_id") != self.space_id:
            raise OABitmapMismatch(
                f"ordinal space mismatch: bitmap {self.space_id!r} != "
                f"{ospace.get('ordinal_space_id')!r} ({odir})")
        want = (manifest or {}).get("ordinal_space_id")
        if want and want != self.space_id:
            raise OABitmapMismatch(
                f"index manifest ordinal_space_id {want!r} != bitmap {self.space_id!r}")

        src = self.stamp.get("meta_source") or {}
        if meta_path is not None:
            have = meta_fingerprint(meta_path)
            if (int(src.get("bytes", -1)) != have["bytes"]
                    or int(src.get("mtime_ns", -1)) != have["mtime_ns"]):
                raise OABitmapMismatch(
                    f"served meta.sqlite {meta_path} {have} != the meta the "
                    f"ordinal space was built from {src}; the bitmap would "
                    f"address the wrong documents")

        self.wids = np.load(odir / "wids.npy", mmap_mode="r")
        if len(self.wids) != self.rows:
            raise OABitmapMismatch(
                f"wids.npy holds {len(self.wids)} ids, stamp declares {self.rows}")
        nbytes = (self.rows + 7) // 8
        self.known = np.load(self.path / KNOWN_FILE)
        self.oa = np.load(self.path / OA_FILE)
        if len(self.known) != nbytes or len(self.oa) != nbytes:
            raise OABitmapMismatch(
                f"bit arrays hold {len(self.known)}/{len(self.oa)} bytes, "
                f"{nbytes} expected for {self.rows} rows")
        logger.info("oa bitmap %s loaded: %d rows, coverage %s from %s",
                    self.bitmap_id, self.rows, self.stamp.get("coverage"), self.path)

    def lookup(self, ids: list[str]):
        """`W-id -> (ordinals, found)`; `ordinals` is meaningless where
        `found` is False."""
        import numpy as np

        nums = np.zeros(len(ids), dtype=np.int64)
        valid = np.zeros(len(ids), dtype=bool)
        for i, s in enumerate(ids):
            if isinstance(s, str) and len(s) > 1 and s[0] == "W":
                digits = s[1:]
                if digits.isdigit() and digits[0] != "0":
                    nums[i] = int(digits)
                    valid[i] = True
        if not len(ids):
            return np.zeros(0, dtype=np.int64), valid
        pos = np.clip(np.searchsorted(self.wids, nums), 0, self.rows - 1)
        found = valid & (np.asarray(self.wids[pos]) == nums)
        return pos, found

    def states(self, ids: list[str]) -> list[bool | None]:
        """Per id: True (known OA), False (known not OA), None (unknown or
        not a base doc)."""
        import numpy as np

        pos, found = self.lookup(ids)
        if not len(ids):
            return []
        byte, bit = pos >> 3, (pos & 7).astype(np.uint8)
        known = ((self.known[byte] >> bit) & 1).astype(bool) & found
        oa = ((self.oa[byte] >> bit) & 1).astype(bool)
        return [bool(oa[i]) if known[i] else None for i in range(len(ids))]

    def apply_rows(self, rows: dict[str, tuple], ids: list[str]) -> None:
        """Replace the `is_oa` column (index 5) of the base meta rows of
        `ids` present in `rows` with the bitmap state, in place."""
        have = [i for i in ids if i in rows]
        if not have:
            return
        for did, st in zip(have, self.states(have)):
            r = rows[did]
            rows[did] = r[:5] + (st,) + r[6:]

    def keep_oa(self, hits: list[tuple]) -> list[tuple]:
        """Hits (id first) whose base doc is known OA, order preserved."""
        if not hits:
            return []
        st = self.states([h[0] for h in hits])
        return [h for h, s in zip(hits, st) if s is True]


def load_if_enabled(index_root: Path, manifest: dict[str, Any] | None) -> OAOverlay | None:
    """Load the overlay iff `SFU_OA_BITMAP` names a directory (relative values
    resolve against `index_root`). Configured-but-unusable raises."""
    path = (os.environ.get(ENV) or "").strip()
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = Path(index_root) / p
    meta = Path(index_root) / "meta.sqlite"
    if not meta.exists():
        raise OABitmapMismatch(f"{ENV} is set but {meta} is missing; the bitmap "
                               f"cannot be bound to a base")
    return OAOverlay(p, meta_path=meta, manifest=manifest)
