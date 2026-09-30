"""Live-index guard for the format-v3 encoder/decoder harnesses (2026-09-29).

Owner requirement relayed by the coordinator: nothing in this work may alter
the live index. Every harness process:
  * clears the serving gates that could make a process stage, compact or
    serve from a live location (SFU_SEISMIC_STAGE_DIR, SFU_META_STAGE_DIR,
    SFU_DELTA_ROOT set to the empty string);
  * compares a size + mtime listing of data/seismic_150m and
    /var/tmp/seismic_stage against the coordinator's baseline
    /home/vscode/work/inplace_update/baseline_20260929T2015Z/*.tsv at start and
    end, and aborts on any difference (the stage dir's staged_manifest.json and
    .staged_ok excepted).
Listing format = `find <root> -type f -printf '%s\\t%T@\\t%p\\n'` (data paths
relative to the repo root, stage paths absolute).
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = Path("/home/vscode/work/inplace_update/baseline_20260929T2015Z")
GATES = ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR", "SFU_DELTA_ROOT")
STAGE_EXCEPT = {"staged_manifest.json", ".staged_ok"}
ROOTS = (("data_seismic_150m.tsv", "data/seismic_150m", True),
         ("_var_tmp_seismic_stage.tsv", "/var/tmp/seismic_stage", False))


def clean_env(env: dict | None = None) -> dict:
    """Set the serving gates to the empty string in `env` (default os.environ)."""
    e = os.environ if env is None else env
    for g in GATES:
        e[g] = ""
    return e


def _fmt_mtime(ns: int) -> str:
    return f"{ns // 1_000_000_000}.{ns % 1_000_000_000:09d}0"


def listing(root: str, relative: bool) -> set[tuple[str, str, str]]:
    base = REPO / root if relative else Path(root)
    out = set()
    for dp, dns, fns in os.walk(base, followlinks=False):
        for fn in fns:
            p = Path(dp) / fn
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode):
                continue
            shown = str(p.relative_to(REPO)) if relative else str(p)
            out.add((str(st.st_size), _fmt_mtime(st.st_mtime_ns), shown))
    return out


def _read_tsv(p: Path) -> set[tuple[str, str, str]]:
    rows = set()
    for line in p.read_text().splitlines():
        if line.strip():
            a, b, c = line.split("\t", 2)
            rows.add((a, b, c))
    return rows


def check_live_unchanged(tag: str, retries: int = 5, wait_s: float = 15.0) -> dict:
    """Abort (SystemExit) if data/seismic_150m or the stage dir differs from the baseline.

    A CHANGED file (present with a different size or mtime) or a NEW file aborts
    at once. A MISSING file (or a walk/stat error, which is never treated as
    data) is re-checked up to `retries` times, `wait_s` apart, because the 9p
    mount has shown transient misses (coordinator note 2026-09-30); it aborts
    only if still missing after the last retry.
    """
    import time
    report = {"tag": tag, "baseline": str(BASELINE)}
    for tsv, root, rel in ROOTS:
        want = _read_tsv(BASELINE / tsv)
        if not rel:
            want = {r for r in want if Path(r[2]).name not in STAGE_EXCEPT}
        want_by_path = {r[2]: r for r in want}
        attempt = 0
        while True:
            try:
                got = listing(root, rel)
                err = None
            except OSError as e:
                got, err = set(), repr(e)
            if not rel:
                got = {r for r in got if Path(r[2]).name not in STAGE_EXCEPT}
            got_by_path = {r[2]: r for r in got}
            changed = sorted(p for p in want_by_path if p in got_by_path and got_by_path[p] != want_by_path[p])
            new = sorted(p for p in got_by_path if p not in want_by_path)
            missing = sorted(p for p in want_by_path if p not in got_by_path)
            if changed or new:
                raise SystemExit(f"LIVE-INDEX GUARD ({tag}): {root} CHANGED {changed[:5]} NEW {new[:5]}")
            if not missing and err is None:
                break
            attempt += 1
            if attempt > retries:
                raise SystemExit(f"LIVE-INDEX GUARD ({tag}): {root} MISSING after {retries} re-checks: "
                                 f"{missing[:5]} (walk error {err})")
            time.sleep(wait_s)
        report[root] = {"files": len(got), "missing_or_changed": 0, "new_or_changed": 0,
                        "transient_rechecks": attempt}
    return report
