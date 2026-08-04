"""Ordinal addressing: dense `0..N-1` addresses for the filter stage.

Design + measurements: `docs/seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md`.

A W-id (`W2803642969`) is an **identity**. It is sparse — 150,413,098 documents
spread over a key range up to 7.14e9, density ~1 in 47 — so resolving one is a
*search*. An **ordinal** is an *address*: looking one up is an array index.
Lucene has always kept this split (internal docid vs external UID); this index
collapsed the two, and doc 18 §1-§3 is why.

**This module is a SPACE lever, not a latency lever** (doc 18 §14, measured
2026-08-03). The `meta.sqlite` post-filter mask's ~400 ms per 1000 candidates
(doc 18 §4.1) is dominated by the filesystem under the file, not by the sparse
key: staging that same `meta.sqlite` to local disk with no code change takes the
filter stage from 222.2 ms to **4.0 ms**, and ordinals then reach 1.5 ms — a
further 2.7x on the stage, but only 2.0% of the whole query and inside the
measured noise floor. What ordinals actually buy is that latency for **1.96 GB**
of resident local disk instead of **24.9 GB**. Adopt them when local disk is the
binding constraint; otherwise stage the file, which carries none of the two
hazards below.

This module is the read side. The arrays are built by
`spike/meta_consolidation/09_n3_build_ordinals.py`.

**Nothing here is enabled by default.** `retriever` consults it only when
`SFU_THINCLIENT_ORDINALS` points at an ordinal directory.

## The two hazards this module exists to contain

**1. Stale ordinals fail SILENTLY** (doc 18 §6 risk 1 — the single most
dangerous property of the design). Ordinals renumber on every rebuild. A set of
arrays paired with a *different* build of `meta.sqlite` does not error: it
returns the wrong document's year and type, and the query returns plausible
wrong results forever. This is precisely why Lucene forbids persisting docids.

So `OrdinalSpace` refuses to load unless the arrays' `ordinal_space_id` matches
the one stamped in the index `manifest.json`. **It fails closed**: a manifest
with no stamp at all disables the ordinal path rather than trusting it. There is
no "best effort" mode and no override flag, deliberately — an override would be
used exactly once, in a hurry, and would then be the bug.

**2. Not every id has an ordinal.** `_meta_rows` falls back to
`DenseWarmCache.metadata_rows` for docs added at query time, which by
construction have no build-time ordinal (doc 18 §6 risk 3). A pure ordinal mask
drops them silently — the same class of invisible-wrong-answer as hazard 1. So
`post_filter` never decides a miss by itself: it returns the misses to the
caller, which resolves them the way it always did.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Written next to the arrays by the build; binds them to one meta.sqlite.
STAMP_FILE = "ordinal_space.json"
MANIFEST_KEY = "ordinal_space_id"

_ARRAYS = ("wids", "year", "dtype", "is_oa", "section")


class OrdinalSpaceMismatch(RuntimeError):
    """The arrays were built against a different index than the one loaded.

    Raised instead of returning wrong documents. See hazard 1 above.
    """


class OrdinalSpace:
    """mmap'd ordinal-indexed columns + the `W-id -> ordinal` binary search.

    `wids` is monotonically increasing because the build scans `docs` by
    `INTEGER PRIMARY KEY` (measured `monotonic=True` over 150,413,098 rows,
    doc 18 §11), so `searchsorted` is valid without a separate sort or index.
    """

    def __init__(self, path: str | Path, manifest: dict[str, Any] | None = None):
        import numpy as np

        self.path = Path(path)
        stamp_path = self.path / STAMP_FILE
        if not stamp_path.exists():
            raise OrdinalSpaceMismatch(
                f"{stamp_path} is missing — the arrays carry no identity, so "
                f"they cannot be proven to match this index. Rebuild them with "
                f"09_n3_build_ordinals.py, which writes the stamp.")
        self.stamp = json.loads(stamp_path.read_text())
        self.space_id = self.stamp.get(MANIFEST_KEY)

        # ── hazard 1: fail closed ────────────────────────────────────────────
        want = (manifest or {}).get(MANIFEST_KEY)
        if not self.space_id:
            raise OrdinalSpaceMismatch(
                f"{stamp_path} has no {MANIFEST_KEY!r}")
        if not want:
            raise OrdinalSpaceMismatch(
                f"the index manifest carries no {MANIFEST_KEY!r}, so it cannot "
                f"be shown to share an ordinal space with {self.path}. "
                f"Refusing to serve ordinals: a mismatched pair returns the "
                f"WRONG document with no error (doc 18 §6 risk 1).")
        if want != self.space_id:
            raise OrdinalSpaceMismatch(
                f"ordinal space mismatch: manifest {want!r} != arrays "
                f"{self.space_id!r} ({self.path}). The arrays were built "
                f"against a different index; ordinals from one do not address "
                f"the other. Rebuild the arrays against this index.")

        self.rows = int(self.stamp["rows"])
        for name in _ARRAYS:
            arr = np.load(self.path / f"{name}.npy", mmap_mode="r")
            # EVERY array must be full length, not just wids. A short column
            # is not a loud failure: `wids` can be complete while `year` is
            # truncated (e.g. an interrupted copy), and then every ordinal past
            # the truncation either raises deep in a query or, worse, filters
            # against whatever the shorter array holds. Checking only wids
            # missed exactly this case in practice on 2026-08-02.
            if len(arr) != self.rows:
                raise OrdinalSpaceMismatch(
                    f"{name}.npy holds {len(arr)} entries but the stamp "
                    f"declares {self.rows} — the arrays are truncated, "
                    f"partially copied, or the stamp is stale; either way "
                    f"the tail addresses nothing.")
            setattr(self, name, arr)
        self.type_codes: dict[str, int] = self.stamp["codes"]["type"]
        logger.info("ordinal space %s loaded: %d docs from %s",
                    self.space_id, self.rows, self.path)

    # ── lookup ───────────────────────────────────────────────────────────────

    def lookup(self, ids: list[str]):
        """`W-id -> (ordinals, found)`. `found` is the verification read that
        makes a miss visible; `ordinals` is meaningless where `found` is False."""
        import numpy as np

        nums = np.empty(len(ids), dtype=np.int64)
        valid = np.zeros(len(ids), dtype=bool)
        for i, s in enumerate(ids):
            # Must mirror builder.encode_meta_id EXACTLY, including its
            # leading-zero rejection. Those ids live in docs_other and have no
            # ordinal; accepting one would map "W0123" onto the ordinal of the
            # DIFFERENT document "W123", pass the `found` check (the stored
            # W-id really is 123), and filter on the wrong document's metadata.
            # That is the silent-wrong-answer class this module exists to
            # prevent, so the two encoders must not be allowed to drift.
            if len(s) > 1 and s[0] == "W":
                digits = s[1:]
                if digits.isdigit() and digits[0] != "0":
                    nums[i] = int(digits)
                    valid[i] = True
        pos = np.clip(np.searchsorted(self.wids, nums), 0, self.rows - 1)
        found = valid & (self.wids[pos] == nums)
        return pos, found

    def post_filter(self, ranked: list[tuple[str, float]], f: dict):
        """Vectorised equivalent of `retriever._post_filter`, rank order
        preserved.

        Returns `(kept, unresolved)`. **`unresolved` is not a detail.** Those
        ids have no ordinal — warm-cache docs, or anything else outside the
        build — and this function refuses to guess at them (hazard 2). The
        caller must resolve them the old way and merge, or the docs vanish
        silently. Returning them separately makes ignoring them a visible
        choice in the caller rather than an invisible default here.
        """
        import numpy as np

        if not ranked:
            return [], []
        ids = [d for d, _ in ranked]
        pos, found = self.lookup(ids)

        ok = found.copy()
        if f.get("year_range"):
            lo, hi = f["year_range"]
            y = self.year[pos]
            # `y != 0` reproduces the production `if not (year and ...)`:
            # a NULL year is stored as the 0 sentinel and must not pass.
            ok &= (y >= lo) & (y <= hi) & (y != 0)
        if f.get("type"):
            # An unknown type code can never equal a stored code, so an
            # unseen filter value correctly keeps nothing.
            ok &= self.dtype[pos] == self.type_codes.get(f["type"], -999)
        if f.get("is_oa"):
            ok &= self.is_oa[pos] != 0

        kept = [ranked[i] for i in np.flatnonzero(ok)]
        unresolved = [ranked[i] for i in np.flatnonzero(~found)]
        return kept, unresolved


def write_stamp(work: Path, rows: int, codes: dict, source: Path,
                space_id: str | None = None) -> dict:
    """Mint an ordinal space identity and bind it to the `meta.sqlite` it came
    from. Called by the build; `OrdinalSpace` refuses to load without it.

    The id is a fresh uuid4 per build rather than a hash of the source, because
    two builds of the same corpus still produce *different* ordinal spaces the
    moment a row is added or removed, and a content hash would tempt someone to
    treat "same corpus" as "same addresses". They are not the same thing.
    """
    import uuid

    st = source.stat()
    stamp = {
        MANIFEST_KEY: space_id or str(uuid.uuid4()),
        "built_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "rows": int(rows),
        "codes": codes,
        "source": {"path": str(source), "bytes": st.st_size,
                   "mtime_ns": st.st_mtime_ns},
        "note": ("copy ordinal_space_id into the index manifest.json under "
                 f"{MANIFEST_KEY!r} to authorise this pairing; the retriever "
                 "hard-refuses a mismatch (doc 18 §6 risk 1)"),
    }
    (work / STAMP_FILE).write_text(json.dumps(stamp, indent=2))
    return stamp


def load_if_enabled(index_root: Path, manifest: dict[str, Any]) -> OrdinalSpace | None:
    """Load the ordinal space iff `SFU_THINCLIENT_ORDINALS` names a directory.

    A configured-but-broken ordinal space raises: silently serving the SQLite
    path after being told to serve ordinals would make a misconfiguration look
    like a performance regression, which is the hardest kind to find.
    """
    path = os.environ.get("SFU_THINCLIENT_ORDINALS")
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = index_root / p
    return OrdinalSpace(p, manifest)
