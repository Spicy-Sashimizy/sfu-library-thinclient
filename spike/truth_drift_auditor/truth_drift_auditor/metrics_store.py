"""Flatten measured-results JSON files into a lookup of dotted numeric paths.

The metrics store is the *numerical technical base of truth*. In this spike it
is fed by copies of the thin client's ``data/eval_results/*.json`` files
(``fixtures/metrics/``), but any directory of JSON files works. A path is
``<file stem>:<dotted.path>``, e.g.
``dict_effect_at_scale_2026-10-19:hot.totals.arms.a_shipped.pct_vs_b_nodict``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from .config import Alias

_NUMERIC = (int, float)


def _walk(node, prefix: str) -> Iterator[tuple[str, float]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{prefix}[{i}]")
    elif isinstance(node, bool):
        return
    elif isinstance(node, _NUMERIC):
        yield prefix, float(node)


class MetricsStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.values: dict[str, float] = {}
        self.files: list[str] = []
        self.reload()

    def reload(self) -> None:
        self.values.clear()
        self.files.clear()
        for f in sorted(self.directory.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            self.files.append(f.stem)
            for path, val in _walk(data, ""):
                self.values[f"{f.stem}:{path}"] = val

    def get(self, path: str) -> float | None:
        return self.values.get(path)

    def search(self, pattern: str, limit: int = 50) -> list[tuple[str, float]]:
        rx = re.compile(pattern, re.I)
        out = [(k, v) for k, v in self.values.items() if rx.search(k)]
        return out[:limit]

    def resolve_aliases(self, aliases: list[Alias]) -> list[tuple[Alias, float | None]]:
        return [(a, self.get(a.path)) for a in aliases]

    def __len__(self) -> int:
        return len(self.values)
