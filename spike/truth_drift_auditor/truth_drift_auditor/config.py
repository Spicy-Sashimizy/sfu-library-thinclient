"""TOML configuration (stdlib tomllib) with environment overrides.

Everything the pilot needs lives in one file: see ../config.example.toml.
Secrets are read from the environment (ANTHROPIC_API_KEY, ZOTERO_API_KEY, ...),
never from the TOML.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Alias:
    phrase: str                 # case-insensitive substring or regex (prefix with "re:")
    path: str                   # "<metrics file stem>:<dotted.path>"
    unit: str = ""              # "%", "GB", "ms", "" ...
    tolerance_rel: float = 0.02  # relative tolerance before a mismatch is reported
    note: str = ""


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path

    # --- helpers -----------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, dotted: str, default: str | None = None) -> Path | None:
        v = self.get(dotted, default)
        if v is None:
            return None
        p = Path(os.path.expandvars(os.path.expanduser(str(v))))
        return p if p.is_absolute() else (self.root / p)

    @property
    def aliases(self) -> list[Alias]:
        out = []
        for a in self.get("metrics.aliases", []) or []:
            out.append(Alias(**{k: a[k] for k in a if k in Alias.__dataclass_fields__}))
        return out


def load_config(path: str | Path | None = None) -> Config:
    """Load config.toml (default: ./config.toml next to the package root, else
    config.example.toml). Environment variable TDA_CONFIG overrides the path."""
    env = os.environ.get("TDA_CONFIG")
    candidates = [Path(p) for p in (path, env) if p]
    here = Path(__file__).resolve().parent.parent
    candidates += [here / "config.toml", here / "config.example.toml"]
    for c in candidates:
        if c.is_file():
            with open(c, "rb") as fh:
                raw = tomllib.load(fh)
            return Config(raw=raw, root=c.parent)
    raise FileNotFoundError("no config.toml / config.example.toml found; set TDA_CONFIG")
