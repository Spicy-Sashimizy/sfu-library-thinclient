"""Writer for the base livedocs tombstone bitset (item C, 2026-09-29).

Format and reader: `source/lib/thinclient/livedocs.py`. One bitset per publish,
rebuilt from the ledger (tombstones + base docs superseded by a delta copy),
written to `<delta_root>/livedocs/base-<stamp>.liv` via tmp + fsync +
`os.replace`, and named (path, crc32, ordinal space) in `generations.json`,
which `publish` writes last. Older bitsets are left for the operator (a reader
that loaded the previous `generations.json` may still have them mmap'd).
"""
from __future__ import annotations

import os
import zlib
from pathlib import Path

import numpy as np

from lib.thinclient.livedocs import HEADER_LEN, pack_header, payload_len
from lib.thinclient.ordinals import OrdinalSpace

LIVEDOCS_DIR = "livedocs"
LOOKUP_CHUNK = 200_000


def open_ordinals(ordinal_dir: str | Path) -> OrdinalSpace:
    """Open the base ordinal arrays, trusting their own stamp (the bitset
    records the space id, and the reader re-checks it against these arrays)."""
    import json
    stamp = json.loads((Path(ordinal_dir) / "ordinal_space.json").read_text())
    return OrdinalSpace(ordinal_dir, {"ordinal_space_id": stamp["ordinal_space_id"]})


def resolve(ords: OrdinalSpace, ids) -> tuple[np.ndarray, list[str]]:
    """ids -> (ordinals found in the base space, ids with no base ordinal)."""
    ids = list(ids)
    found_ords: list[np.ndarray] = []
    missing: list[str] = []
    for i in range(0, len(ids), LOOKUP_CHUNK):
        chunk = ids[i:i + LOOKUP_CHUNK]
        pos, found = ords.lookup(chunk)
        found_ords.append(pos[found])
        missing.extend(c for c, f in zip(chunk, found) if not f)
    arr = np.concatenate(found_ords) if found_ords else np.empty(0, dtype=np.int64)
    return arr.astype(np.int64), missing


def build_bits(nbits: int, ordinals: np.ndarray) -> np.ndarray:
    dense = np.zeros(nbits, dtype=bool)
    if len(ordinals):
        dense[ordinals] = True
    return np.packbits(dense, bitorder="little")


def write_livedocs(path: Path, bits: np.ndarray, nbits: int, space_id: str) -> dict:
    """Write one `.liv` file atomically; returns its header facts."""
    if len(bits) != payload_len(nbits):
        raise ValueError(f"payload {len(bits)} bytes != {payload_len(nbits)} for {nbits} bits")
    pop = int(np.unpackbits(bits, bitorder="little")[:nbits].sum()) if nbits else 0
    crc = zlib.crc32(bits.tobytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(pack_header(nbits, pop, crc, space_id))
        fh.write(bits.tobytes())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return {"nbits": int(nbits), "popcount": pop, "crc32": int(crc),
            "bytes": HEADER_LEN + len(bits)}


def publish_livedocs(delta_root: Path, stamp: str, ordinal_dir: str | Path,
                     deleted_ids, superseded_base_ids) -> tuple[dict, list[str]]:
    """Build + write the bitset for one publish. Returns (the
    `generations.json["livedocs"]` entry, deleted ids with no base ordinal —
    those stay in the JSON `mask.deleted` list)."""
    ords = open_ordinals(ordinal_dir)
    del_ords, del_missing = resolve(ords, deleted_ids)
    sup_ords, _ = resolve(ords, superseded_base_ids)
    bits = build_bits(ords.rows, np.concatenate([del_ords, sup_ords]))
    rel = Path(LIVEDOCS_DIR) / f"base-{stamp}.liv"
    facts = write_livedocs(Path(delta_root) / rel, bits, ords.rows, ords.space_id)
    entry = {"format": 1, "path": str(rel), "ordinal_dir": str(Path(ordinal_dir).resolve()),
             "ordinal_space_id": ords.space_id, "deleted_in_base": int(len(del_ords)),
             "superseded_in_base": int(len(sup_ords)), "deleted_without_ordinal": len(del_missing),
             **facts}
    return entry, del_missing
