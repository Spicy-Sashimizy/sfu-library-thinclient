#!/usr/bin/env python3
"""Back-compat shim: re-exports `SeismicBackend` and `SPLADE_QUERY_TERMS` from
the canonical location `lib.thinclient.seismic_backend`.

The class was relocated under `source/lib/thinclient/` so the served retriever
(`ThinClientRetriever`, the `SFU_SPLADE_BACKEND=seismic` branch) can import it
without depending on `scripts/`. The standalone parity/sweep harnesses
(`eval_seismic_parity.py`, `g2_param_sweep.py`) add this directory to
`sys.path` and `import seismic_backend` — this shim keeps that working, so
those scripts need no change.

Canonical implementation: `source/lib/thinclient/seismic_backend.py`.
"""
import sys
import os

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "source"))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from lib.thinclient.seismic_backend import SeismicBackend, SPLADE_QUERY_TERMS  # noqa: E402,F401

__all__ = ["SeismicBackend", "SPLADE_QUERY_TERMS"]
