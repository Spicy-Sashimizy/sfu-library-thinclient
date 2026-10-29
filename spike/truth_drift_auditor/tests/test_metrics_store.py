from pathlib import Path

from truth_drift_auditor.config import load_config
from truth_drift_auditor.metrics_store import MetricsStore

ROOT = Path(__file__).resolve().parent.parent


def test_store_flattens_fixtures():
    store = MetricsStore(ROOT / "fixtures/metrics")
    assert len(store.files) == 6
    assert store.get("dict_effect_at_scale_2026-10-19:hot.totals.arms.a_shipped.pct_vs_b_nodict") == -17.58
    assert store.get("c5_lance_vs_sqlite_20260802_0636:results.100.lance_over_sqlite") == 1.72
    assert store.get("seismic_build_scale_20m:build_seconds") == 1021.76


def test_every_alias_in_example_config_resolves():
    cfg = load_config(ROOT / "config.example.toml")
    store = MetricsStore(cfg.path("metrics.directory"))
    unresolved = [a.path for a, v in store.resolve_aliases(cfg.aliases) if v is None]
    assert unresolved == []


def test_search_is_regex():
    store = MetricsStore(ROOT / "fixtures/metrics")
    hits = store.search(r"arms_gb_at_150m_est\.a_shipped")
    assert hits and abs(hits[0][1] - 71.56) < 1e-9
