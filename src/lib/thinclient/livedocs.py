"""Tombstone bitset over the base ordinal space (delta-ingest item C, 2026-09-29).

One bit per base ordinal (`ordinals.py`: W-id -> dense `0..N-1` address over
the base `meta.sqlite`); bit set = the base copy of that document must never
reach fusion, because it was deleted or a delta generation / the buffer holds
a newer version (design issue S5). 150,413,098 ordinals = 18.8 MB. The Lucene
`.liv` model, inverted: a set bit means DEAD.

File layout (`*.liv`, little-endian, written by
`spike/delta_ingest/livedocs.py`, published by path + checksum from
`generations.json["livedocs"]`):

    offset size field
    0      8    magic b"SFULIV01"
    8      4    u32 version (= 1)
    12     4    u32 header_len (= 80)
    16     8    u64 nbits (= ordinal space rows)
    24     8    u64 popcount (set bits)
    32     4    u32 crc32 of the payload (zlib.crc32)
    36     4    reserved, zero
    40     40   ordinal_space_id, ASCII, NUL-padded
    80     ceil(nbits/8) payload; bit i = byte i>>3, bit (i & 7) (LSB first,
                numpy `packbits(bitorder="little")`)

The reader fails closed (raises `LivedocsError`) on a bad magic, unknown
version, short payload, checksum mismatch, or an ordinal space id that does not
match the ordinal arrays used to resolve ids: a bitset read against a different
ordinal space masks the WRONG documents with no error (ordinals.py hazard 1).
Invariants: docs/CODE_INVARIANTS.md §"livedocs".
"""
from __future__ import annotations

import mmap
import struct
import zlib
from pathlib import Path

MAGIC = b"SFULIV01"
VERSION = 1
HEADER = struct.Struct("<8sIIQQI4x40s")
HEADER_LEN = HEADER.size


class LivedocsError(RuntimeError):
    """The bitset file is unusable or belongs to another ordinal space."""


def payload_len(nbits: int) -> int:
    return (int(nbits) + 7) // 8


def pack_header(nbits: int, popcount: int, crc: int, space_id: str) -> bytes:
    sid = space_id.encode("ascii")
    if len(sid) > 40:
        raise LivedocsError(f"ordinal_space_id longer than 40 bytes: {space_id!r}")
    return HEADER.pack(MAGIC, VERSION, HEADER_LEN, int(nbits), int(popcount),
                       int(crc) & 0xFFFFFFFF, sid)


def read_header(buf: bytes) -> dict:
    if len(buf) < HEADER_LEN:
        raise LivedocsError("livedocs file shorter than its header")
    magic, version, hlen, nbits, pop, crc, sid = HEADER.unpack_from(buf, 0)
    if magic != MAGIC:
        raise LivedocsError(f"bad livedocs magic {magic!r}")
    if version != VERSION or hlen != HEADER_LEN:
        raise LivedocsError(f"unsupported livedocs version {version} / header_len {hlen}")
    return {"version": version, "nbits": int(nbits), "popcount": int(pop), "crc32": int(crc),
            "ordinal_space_id": sid.rstrip(b"\0").decode("ascii")}


class Livedocs:
    """Read-only mmap of a `.liv` tombstone bitset.

    `dead(ordinals)` answers for a numpy int array of base ordinals; the caller
    resolves ids to ordinals (with the `found` mask from `OrdinalSpace.lookup`)
    and must treat ids with no ordinal as NOT covered by the bitset."""

    def __init__(self, path: str | Path, expect_space_id: str | None = None,
                 expect_crc32: int | None = None, verify: bool = True):
        import numpy as np

        self.path = Path(path)
        with open(self.path, "rb") as fh:
            self._mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            self.header = read_header(self._mm[:HEADER_LEN])
            self.nbits = self.header["nbits"]
            self.popcount = self.header["popcount"]
            self.space_id = self.header["ordinal_space_id"]
            need = HEADER_LEN + payload_len(self.nbits)
            if len(self._mm) != need:
                raise LivedocsError(f"{self.path}: {len(self._mm)} bytes, header implies {need}")
            if expect_space_id is not None and expect_space_id != self.space_id:
                raise LivedocsError(f"{self.path}: ordinal space {self.space_id!r} != "
                                    f"expected {expect_space_id!r}")
            if expect_crc32 is not None and int(expect_crc32) != self.header["crc32"]:
                raise LivedocsError(f"{self.path}: header crc32 does not match the published one")
            if verify and zlib.crc32(memoryview(self._mm)[HEADER_LEN:]) != self.header["crc32"]:
                raise LivedocsError(f"{self.path}: payload crc32 mismatch")
        except Exception:
            self._mm.close()
            raise
        self.bits = np.frombuffer(self._mm, dtype=np.uint8, offset=HEADER_LEN,
                                  count=payload_len(self.nbits))

    def dead(self, ordinals):
        """Boolean array: True where the ordinal's bit is set. Ordinals outside
        `0..nbits-1` are reported alive."""
        import numpy as np

        o = np.asarray(ordinals, dtype=np.int64)
        inside = (o >= 0) & (o < self.nbits)
        oc = np.where(inside, o, 0)
        return inside & ((self.bits[oc >> 3] >> (oc & 7).astype(np.uint8)) & 1).astype(bool)

    def close(self) -> None:
        self.bits = None
        try:
            self._mm.close()
        except (BufferError, ValueError):
            pass
