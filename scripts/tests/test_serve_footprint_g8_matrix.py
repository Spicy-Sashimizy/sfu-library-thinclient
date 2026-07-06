"""Unit tests for the G8 2×2 matrix wiring in `serve_footprint_bench.py`.

These are PURE-Python tests (no pyo3 / no real shards), pinning the two
behaviours the G8 compression matrix depends on so a regression fails loudly:

1. **`detect_memcompression()` precedence** — operator assertion (via
   `SFU_MEMCOMPRESSION_REGIME`) trumps /proc introspection, and the valid set is
   enforced (a typo raises, not silently falls through to 'unknown'). The
   zram/zswap/windows_compression values resolve to compressed-in-RAM; disk_swap /
   off / unknown do not. This matters because the verdict gate treats VmSwap
   differently by regime.

2. **`_latency_caveat()` regime-aware verdict gate — the actual G8 bug fix.**
   The old gate flagged ANY `VmSwap > 0.1 GB` as a disk-swap confound
   ("latency is NOT a verdict"). Under zram/zswap/windows_compression those
   swapped pages are compressed IN RAM (the G8 mechanism being tested) and
   decompress at GB/s — NOT a disk re-fault. Without the regime awareness the
   owned-anon+zram cell would be mislabeled "not a verdict" and the compression
   idea would look dead when it worked. The 'mmap index exceeds page cache'
   (warm >= cold) symptom is also now gated on load_mode=='mmap' (owned-anon
   stock load has no file-backed page cache to exceed).

Heavy integration (real shards / parity / latency-at-150M) is covered by
`test_seismic_sequential.py` + `test_served_seismic_path.py`; this file is the
pure-logic guard for the matrix wiring added alongside those.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
BENCH = REPO / "scripts" / "seismic_testbed" / "serve_footprint_bench.py"


@pytest.fixture(scope="module")
def sfb():
    """Load serve_footprint_bench as a module (skip if it can't be imported —
    e.g. a dependency of its top-level imports is missing in a test env)."""
    spec = importlib.util.spec_from_file_location("sfb", BENCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── detect_memcompression precedence ──────────────────────────────────────────

def test_regime_env_assertion_trumps_proc(sfb, monkeypatch):
    """SFU_MEMCOMPRESSION_REGIME wins over whatever /proc says (needed for Windows
    host compression, invisible from WSL2 /proc)."""
    monkeypatch.setenv("SFU_MEMCOMPRESSION_REGIME", "windows_compression")
    r = sfb.detect_memcompression()
    assert r["regime"] == "windows_compression"
    assert "SFU_MEMCOMPRESSION_REGIME" in r["sources"][0]


def test_regime_env_invalid_rejected(sfb, monkeypatch):
    """A typo in the override must raise, not silently fall through to 'unknown'
    (an unknown regime makes the gate conservatively mislabel the zram cell)."""
    monkeypatch.setenv("SFU_MEMCOMPRESSION_REGIME", "zram2")  # typo
    with pytest.raises(ValueError, match="SFU_MEMCOMPRESSION_REGIME"):
        sfb.detect_memcompression()


@pytest.mark.parametrize("regime,compressed", [
    ("zram", True),
    ("zswap", True),
    ("windows_compression", True),
    ("disk_swap", False),
    ("off", False),
    ("unknown", False),
])
def test_compressed_in_ram_classification(sfb, regime, compressed):
    assert sfb._regime_is_compressed_in_ram(regime) is compressed


# ── _latency_caveat regime-aware gate (the G8 bug fix) ────────────────────────

def _ram(vmswap_gb):
    return {"vmswap_gb": vmswap_gb}


_WARM_LT_COLD = {"warm": {"p50_ms": 600}, "cold": {"p50_ms": 4000}}      # cache helped
_WARM_GTE_COLD = {"warm": {"p50_ms": 18000}, "cold": {"p50_ms": 15000}}  # mmap > cache, >1s
_ZRAM = {"regime": "zram", "sources": []}
_DISK = {"regime": "disk_swap", "sources": []}
_UNK = {"regime": "unknown", "sources": []}


def test_classic_clean_baseline_is_verdict(sfb):
    """mmap + disk_swap + VmSwap 0 + warm<cold → clean verdict (unchanged)."""
    out = sfb._latency_caveat(_ram(0.0), _WARM_LT_COLD, "mmap", _DISK)
    assert "VERDICT" not in out and "CAVEAT" not in out
    assert "Vmswap~0" in out.replace("VmSwap", "Vmswap") or "VmSwap~0" in out


def test_zram_cell_with_vmswap_is_verdict_not_confound(sfb):
    """THE G8 FIX: stock + zram + VmSwap 0.5 + warm<cold must be a VERDICT — the
    swapped anon is compressed in RAM, decompress at GB/s, NOT a disk re-fault.
    The old gate returned 'CAVEAT: not a verdict' here, which would have made the
    owned-anon+zram cell look dead when it worked."""
    out = sfb._latency_caveat(_ram(0.5), _WARM_LT_COLD, "stock", _ZRAM)
    assert "VERDICT" in out
    assert "compressed IN RAM" in out
    assert "zram" in out
    assert "CAVEAT" not in out


def test_disk_swap_vmswap_still_flagged(sfb):
    """mmap + plain disk_swap + VmSwap 0.5 → still a confound (regime not
    compressed). The fix is regime-scoped, not a blanket 'ignore VmSwap'."""
    out = sfb._latency_caveat(_ram(0.5), _WARM_LT_COLD, "mmap", _DISK)
    assert "CAVEAT" in out
    assert "disk swap" in out


def test_mmap_warm_gte_cold_flagged(sfb):
    """mmap + warm>=cold (both >1s) → file-backed re-fault symptom stands
    regardless of regime (compression compresses anon, it does not cache dropped
    file pages)."""
    out = sfb._latency_caveat(_ram(0.0), _WARM_GTE_COLD, "mmap", _DISK)
    assert "CAVEAT" in out
    assert "re-fault" in out


def test_stock_warm_gte_cold_no_mmap_symptom(sfb):
    """stock (owned anon) + warm>=cold → the 'mmap exceeds page cache' symptom is
    gated on load_mode=='mmap' (owned-anon has no file-backed page cache to
    exceed). Under zram with VmSwap>0 it's the compressed-verdict path; under
    unknown it's conservatively the disk.Confound via VmSwap only if VmSwap>0."""
    out_zram = sfb._latency_caveat(_ram(0.5), _WARM_GTE_COLD, "stock", _ZRAM)
    assert "page cache" not in out_zram  # mmap symptom correctly suppressed for stock
    assert "VERDICT" in out_zram  # zram + warm>=cold (no mmap symptom) + compressed → verdict
    # and with no swap at all + stock, it's the clean path
    out_clean = sfb._latency_caveat(_ram(0.0), _WARM_GTE_COLD, "stock", _UNK)
    assert "CAVEAT" not in out_clean  # no swap, no mmap symptom → not confounded


def test_unknown_regime_is_conservative(sfb):
    """Unknown regime + VmSwap>0 → conservatively a confound (can't prove it's
    compressed in RAM, so treat VmSwap as the historical disk symptom). This is
    the safe default until an operator asserts the regime."""
    out = sfb._latency_caveat(_ram(0.3), _WARM_LT_COLD, "stock", _UNK)
    assert "CAVEAT" in out
