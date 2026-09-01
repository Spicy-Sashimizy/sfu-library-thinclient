"""Tests for the production serve query-log (lib.serve_query_log).

Guards the WI-2 (deployprep 2026-07-16) deliverable:
  - normalization + stable hash (the skew/repeat key)
  - result-fingerprint (same results ⟹ same fingerprint)
  - async buffered write + size-capped rotation (bounded disk)
  - env gating: one env ON, one env OFF; staging-default semantics
  - backpressure drop (queue full ⟹ drop+count, NEVER stall a query)
  - the leg-metrics delta surface the retriever exposes (snapshot + delta)

Run: .venv/bin/python3 -m pytest scripts/tests/test_serve_query_log.py -q
     (or: .venv/bin/python3 scripts/tests/test_serve_query_log.py)
"""
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

from lib.serve_query_log import (  # noqa: E402
    QueryLogger, _normalize_query, _sha1, _staging_default,
)


def _fresh_logger(tmp_path: Path, **env_overrides) -> QueryLogger:
    """Build a logger pointed at a tmp path with explicit env, clearing the
    process singleton between tests (so a stale enabled/disabled state from a
    prior case can't leak in)."""
    QueryLogger.reset_for_test()
    env = {
        "SFU_SERVE_QUERY_LOG": "1",
        "SFU_SERVE_QUERY_LOG_PATH": str(tmp_path / "qlog.jsonl"),
        "SFU_SERVE_QUERY_LOG_MAX_BYTES": "4096",
        "SFU_SERVE_QUERY_LOG_BUFFER": "64",
        "SFU_SERVE_QUERY_LOG_RAW": "0",
        "SFU_SERVE_QUERY_LOG_STAGING": "0",
    }
    env.update({k: str(v) for k, v in env_overrides.items()})
    old = {}
    for k, v in env.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        return QueryLogger.get()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _drain_and_read(logger: QueryLogger) -> list[dict]:
    """Flush the queue + read every committed line. Closes the writer so the
    file is flushed/rotated; reconstructs a fresh logger to read from (the file
    is the source of truth)."""
    logger.close()
    QueryLogger.reset_for_test()
    p = logger.path
    if not p.exists():
        return []
    lines = p.read_text().splitlines()
    out = []
    for ln in lines:
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def test_normalize_collapses_whitespace_and_casing():
    assert _normalize_query("  Machine  Learning ") == "machine learning"
    assert _normalize_query("MACHINE learning") == "machine learning"
    assert _normalize_query('"machine learning"') == "machine learning"
    assert _normalize_query("...machine learning...") == "machine learning"


def test_hash_is_stable_and_distinct():
    a = _sha1("machine learning")
    b = _sha1("machine learning")
    assert a == b, "identical input must hash identically"
    assert a != _sha1("deep learning"), "distinct input must hash distinctly"
    assert len(a) == 16, "hash truncated to 16 chars (the join key)"


def test_emits_correct_fields(tmp_path):
    lg = _fresh_logger(tmp_path)
    lg.log(query="Machine Learning", k=50, mode="federated",
           backend="seismic", federation="parallel",
           leg_ms={"bm25f": 10.5, "splade": 30.2, "deep": None, "total": 45.0},
           n_results=50,
           result_oaids=["W1", "W2", "W3"],
           filtered=True)
    entries = _drain_and_read(lg)
    assert len(entries) == 1
    e = entries[0]
    assert e["query_hash"] == _sha1(_normalize_query("Machine Learning"))
    assert e["query_norm"] == "", "raw text NOT stored by default (PII-safe)"
    assert e["k"] == 50 and e["mode"] == "federated"
    assert e["backend"] == "seismic" and e["federation"] == "parallel"
    assert e["n_results"] == 50 and e["filtered"] is True
    assert e["leg_ms"] == {"bm25f": 10.5, "splade": 30.2, "total": 45.0}
    assert e["result_fp"] == _sha1("\x1f".join(["W1", "W2", "W3"]))
    assert e["ts"].endswith("Z"), "UTC ISO timestamp"
    assert len(e["session"]) == 8, "per-process session id"


def test_raw_opt_in_stores_norm_text(tmp_path):
    lg = _fresh_logger(tmp_path, SFU_SERVE_QUERY_LOG_RAW="1")
    lg.log(query="deep learning", k=10, mode="thinclient",
           n_results=3, result_oaids=["A", "B", "C"])
    entries = _drain_and_read(lg)
    assert entries[0]["query_norm"] == "deep learning", "raw opted in"


def _read_all_rotated(lg: QueryLogger) -> list[dict]:
    """Read BOTH the live file and the rotated .1 (the retention model keeps
    only live + .1; older rotations are dropped). The live file is flushed via
    close(); the .1 is read as-is."""
    lg.close()
    QueryLogger.reset_for_test()
    out = []
    for p in (lg.path, lg.path.with_suffix(lg.path.suffix + ".1")):
        if p.exists():
            for ln in p.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
    return out


def test_rotation_caps_file_size(tmp_path):
    lg = _fresh_logger(tmp_path, SFU_SERVE_QUERY_LOG_MAX_BYTES="400",
                       SFU_SERVE_QUERY_LOG_BUFFER="4096")
    for i in range(40):
        lg.log(query=f"query number {i}", k=50, mode="federated",
               n_results=10, result_oaids=[f"W{i}"])
    entries = _read_all_rotated(lg)
    assert len(entries) >= 1, "entries committed"
    live = lg.path
    assert live.exists(), "live file recreated after rotation"
    assert live.stat().st_size <= 800, "live file stays near the cap after rotation"
    rot = live.with_suffix(live.suffix + ".1")
    assert rot.exists(), "a rotation produced a .1 (the bounded-retention model)"
    hashes = {e["query_hash"] for e in entries}
    assert len(hashes) == len(entries), "rotation must not duplicate entries"


def test_no_rotation_when_under_cap(tmp_path):
    lg = _fresh_logger(tmp_path, SFU_SERVE_QUERY_LOG_MAX_BYTES="1048576",
                       SFU_SERVE_QUERY_LOG_BUFFER="4096")
    for i in range(25):
        lg.log(query=f"q{i}", k=50, mode="federated", n_results=1,
               result_oaids=[f"X{i}"])
    entries = _read_all_rotated(lg)
    assert len(entries) == 25, f"all 25 committed under cap, got {len(entries)}"
    rot = lg.path.with_suffix(lg.path.suffix + ".1")
    assert not rot.exists(), "no rotation when under cap"


def test_rotation_drops_old_rotated_file(tmp_path):
    lg = _fresh_logger(tmp_path, SFU_SERVE_QUERY_LOG_MAX_BYTES="300",
                       SFU_SERVE_QUERY_LOG_BUFFER="4096")
    rot = lg.path.with_suffix(lg.path.suffix + ".1")
    rot.write_text("pre-existing old log\n")
    for i in range(40):
        lg.log(query=f"q{i}", k=50, mode="federated",
               n_results=1, result_oaids=[f"X{i}"])
    entries = _read_all_rotated(lg)
    assert len(entries) >= 1
    if rot.exists():
        for ln in rot.read_text().splitlines():
            if ln.strip():
                json.loads(ln)


def test_disabled_is_hard_noop(tmp_path):
    lg = _fresh_logger(tmp_path, SFU_SERVE_QUERY_LOG="0")
    assert lg.enabled is False
    lg.log(query="anything", k=50, mode="federated", n_results=1,
           result_oaids=["W1"])
    lg.close()
    QueryLogger.reset_for_test()
    assert not lg.path.exists() or lg.path.stat().st_size == 0, \
        "disabled logger writes nothing"


def test_staging_default_on(tmp_path):
    """default profile / unset SFU_ENV == staging → log ON by default (the drive
    prompt's requirement); an explicit production env defaults OFF."""
    QueryLogger.reset_for_test()
    old = {k: os.environ.get(k) for k in
           ("SFU_SERVE_QUERY_LOG", "SFU_SERVE_QUERY_LOG_STAGING",
            "SFU_ACTIVE_PROFILE", "SFU_ENV")}
    try:
        os.environ.pop("SFU_SERVE_QUERY_LOG", None)
        os.environ.pop("SFU_SERVE_QUERY_LOG_STAGING", None)
        os.environ["SFU_ACTIVE_PROFILE"] = "default"
        os.environ.pop("SFU_ENV", None)
        assert _staging_default() is True, "default profile = staging = ON"
        os.environ["SFU_ENV"] = "production"
        assert _staging_default() is False, "production default OFF unless opted in"
        os.environ["SFU_SERVE_QUERY_LOG"] = "1"
        assert _staging_default() is True, "explicit enable trumps production default"
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    QueryLogger.reset_for_test()


def test_backpressure_drops_not_stalls(tmp_path):
    lg = _fresh_logger(tmp_path, SFU_SERVE_QUERY_LOG_BUFFER="4")
    n = 5000
    t0 = time.perf_counter()
    for i in range(n):
        lg.log(query=f"flood {i}", k=50, mode="federated", n_results=1,
               result_oaids=[f"W{i}"])
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"non-blocking puts took {elapsed:.2f}s — log() blocked!"
    assert lg._dropped > 0, "a flood past a tiny buffer must drop+count (backpressure)"
    lg.close()
    QueryLogger.reset_for_test()


def test_same_results_same_fingerprint():
    oaids = ["W1", "W2", "W3"]
    fp = _sha1("\x1f".join(oaids))
    assert fp == _sha1("\x1f".join(oaids)), "same oaid list ⟹ same fingerprint"


def test_different_results_different_fingerprint():
    a = _sha1("\x1f".join(["W1", "W2", "W3"]))
    b = _sha1("\x1f".join(["W1", "W2", "W4"]))
    assert a != b, "differing result sets must fingerprint distinctly"


def test_leg_metrics_delta():
    from lib.thinclient.retriever import (snapshot_leg_metrics,
                                          leg_metrics_delta, _record_leg)
    before = snapshot_leg_metrics()
    _record_leg("splade", 25.0)
    _record_leg("bm25f", 10.0)
    delta = leg_metrics_delta(before)
    assert delta.get("splade") == 25.0
    assert delta.get("bm25f") == 10.0
    assert "dense" not in delta


if __name__ == "__main__":
    import tempfile
    failures = 0
    g = globals()
    for name in sorted(g):
        if name.startswith("test_") and callable(g[name]):
            try:
                with tempfile.TemporaryDirectory() as td:
                    g[name](Path(td))
                print(f"PASS {name}")
            except TypeError:
                try:
                    g[name]()
                    print(f"PASS {name}")
                except Exception as e:
                    print(f"FAIL {name}: {e}"); failures += 1
            except Exception as e:
                print(f"FAIL {name}: {e}"); failures += 1
    QueryLogger.reset_for_test()
    sys.exit(1 if failures else 0)
