"""Read-only view of the immutable base index (membership + shard manifest)."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from lib.thinclient.builder import encode_meta_id

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX_ROOT = REPO_ROOT / "data" / "thinclient_index"
SHARD_MANIFEST_LADDER = [
    REPO_ROOT / "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json",
    REPO_ROOT / "data/eval_results/seismic_c25_shards_150m_mmap_e5.json",
    REPO_ROOT / "data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json",
]


class BaseIndex:
    def __init__(self, index_root: str | Path):
        self.root = Path(index_root)
        meta = self.root / "meta.sqlite"
        self._db = (sqlite3.connect(f"file:{meta}?mode=ro", uri=True, timeout=30)
                    if meta.exists() else None)
        self._numeric = False
        if self._db is not None:
            cols = {r[1]: (r[2] or "").upper() for r in self._db.execute("PRAGMA table_info(docs)")}
            self._numeric = cols.get("id", "").startswith("INT")

    def contains(self, ids: Iterable[str]) -> dict[str, bool]:
        ids = list(dict.fromkeys(ids))
        out = {i: False for i in ids}
        if self._db is None:
            return out
        enc: dict[int, str] = {}
        other: list[str] = []
        for s in ids:
            n = encode_meta_id(s) if self._numeric else None
            (other.append(s) if n is None else enc.__setitem__(n, s))
        for table, keys, back in (("docs", list(enc), enc), ("docs_other", other, None)):
            if self._numeric is False and table == "docs":
                keys, back = other, None
                other = []
            for i in range(0, len(keys), 500):
                chunk = keys[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for (k,) in self._db.execute(f"SELECT id FROM {table} WHERE id IN ({marks})", chunk):
                    out[back[k] if back is not None else k] = True
        return out

    def shard_manifest(self, explicit: str | None = None) -> Path | None:
        if explicit:
            p = Path(explicit)
            return p if p.is_absolute() else REPO_ROOT / p
        if self.root.resolve() != DEFAULT_INDEX_ROOT.resolve():
            return None
        for p in SHARD_MANIFEST_LADDER:
            if p.exists():
                return p
        return None

    @staticmethod
    def shard_records(manifest_path: Path | None) -> list[dict]:
        if manifest_path is None or not manifest_path.exists():
            return []
        data = json.loads(manifest_path.read_text())
        if isinstance(data, dict) and isinstance(data.get("shards"), list):
            return [dict(s) for s in data["shards"]]
        if isinstance(data, list):
            return [{"mmap_dir": p} for p in data]
        return []

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
