#!/usr/bin/env python3
"""convergence_repro — per-rung table + the 5 pre-registered TIER-1b bars.

Reads the per-cell JSON documents written by run_ladder.sh (schema
``convrepro/cell/1``) and

  1. prints a per-rung, per-pass table (clat p50/p95, wall, majflt, ms/fault,
     pgscan delta, workingset_refault_file delta, active_file, R/L residency);
  2. evaluates the five bars pre-registered in ``PREREGISTRATION_TIER1B.md``
     (1b, 2b, 3b, 4b and the unchanged bar 5) and prints PASS / FAIL / NO DATA
     for each, with the numbers behind it;
  3. if — and only if — early-sort cells (``early_sort.mode != "none"``) are in
     the glob, adds an EARLY-SORT section: the ES tables, bars ES-1..ES-4 from
     ``PREREGISTRATION_EARLYSORT.md`` (re-specified on p95 by Tier-1b), and the
     ES-5 exploratory table (recorded, NOT judged);
  4. lists any EXPLORATORY ORDER-ARM cells separately — they are recorded and
     never scored.

WHAT TIER-1b CHANGED IN THIS TOOL (PREREGISTRATION_TIER1B.md):
  * every latency comparison moved from clat **p50 to clat p95**. Tier-1's
    lesson: the synthetic's median is page-cache-hit-dominated even while
    thrashing (thrash p50 was 3.4x converged at ~600k faults/pass), so faults
    only show up in the tail.
  * bar 1b gained an explicit PRECONDITION — marginal pass-1 majflt > 0 — the
    thing Tier-1 silently lacked.
  * bar 4b clamps pass-1 pgscan values below 4096 pages (16 MiB) to a single
    "~0" tier before the monotonicity test (Tier-1 failed bar 4 on a 512-page
    wiggle between two zero-pressure rungs).
  * `converged` is RECOMPUTED here with the fixed D3 rule — plateau AND final
    majflt < 1% of pass-1 (or 0) — so a *thrashing* plateau is never scored as
    a steady state, whatever the cell JSON's own `converged` field says.
  * cells carrying ``load_phase.order_arm = true`` (the exploratory R-then-L /
    L-then-R orders) are excluded from every table and bar BY CONSTRUCTION.

Sections 1 and 2 see ONLY ``none`` cells: an early-sort cell can never displace
a baseline in the table or in the bars.

LEGACY (Tier-1) CELLS. Cells written before Tier-1b have no ``load_phase.
load_order`` field; they were loaded L-then-R by construction. They still load
and print correctly, but they were produced under a DIFFERENT protocol and the
Tier-1b bars do not apply to them — the frozen Tier-1 verdict lives in
RESULTS.md. This tool labels them loudly rather than silently re-judging them.

**The bars are only meaningful at SCALE=1 with caps actually enforced.** If any
loaded cell has ``scale != 1.0`` or ``cap_enforced == false`` (the --smoke or
--local runs), the report is labelled MECHANICS CHECK and every verdict is
stamped ``(mechanics — NOT a bar verdict)``. Judging the real bars is the
session lead's job, on a SCALE=1 docker ladder.

Usage:
    python3 analyze.py --dir data/eval_results                     # t1b glob
    python3 analyze.py --dir data/eval_results --glob 'convrepro_mech_*.json'
    python3 analyze.py file1.json file2.json
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
import sys

RUNG_ORDER = ["fits", "marginal", "boundary", "thrash", "deep"]
MIB = 1024 * 1024
# Bar 4b noise floor: a pass-1 pgscan below this many pages (16 MiB) is not
# "pressure", it is a wiggle. Everything under it collapses to one "~0" tier
# before the monotonicity test. PREREGISTRATION_TIER1B.md bar 4b.
PGSCAN_NOISE_FLOOR_PAGES = 4096


# --------------------------------------------------------------- loading
def load_cells(paths):
    cells = []
    for p in sorted(paths):
        try:
            with open(p) as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"  ! skipping {p}: {exc}", file=sys.stderr)
            continue
        if doc.get("schema") != "convrepro/cell/1":
            print(f"  ! skipping {p}: not a convrepro cell document", file=sys.stderr)
            continue
        doc["_path"] = p
        _fill_from_host_samples(doc, p)
        cells.append(doc)
    return cells


def _parse_sampler(path):
    """Parse a run_ladder.sh host-side cgroup sampler file -> [(t, {k: v}), ...]."""
    series, cur, t = [], None, None
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("t="):
                    if cur is not None and t is not None:
                        series.append((t, cur))
                    t = float(line[2:])
                    cur = {}
                elif cur is not None and " " in line:
                    k, v = line.split(None, 1)
                    try:
                        cur[k] = int(v)
                    except ValueError:
                        pass
        if cur is not None and t is not None:
            series.append((t, cur))
    except OSError:
        return []
    return series


def _at(series, when, key):
    """Value of `key` in the last sample at or before `when`."""
    best = None
    for t, d in series:
        if t <= when and key in d:
            best = d[key]
    if best is None:  # fall back to the earliest sample that has it
        for _, d in series:
            if key in d:
                return d[key]
    return best


def _fill_from_host_samples(doc, path):
    """When the cell could not read its own cgroup, reconstruct the per-pass
    cgroup numbers from the orchestrator's host-side sampler file."""
    if not doc.get("env", {}).get("cgroup_needs_host_read"):
        return
    sfile = path + ".cgsamples"
    if not os.path.exists(sfile):
        doc["_host_sample_status"] = "marker set but no .cgsamples file found"
        return
    series = _parse_sampler(sfile)
    if not series:
        doc["_host_sample_status"] = "sampler file empty/unparseable"
        return
    for ps in doc.get("passes", []):
        t0, t1 = ps.get("t_start_epoch"), ps.get("t_end_epoch")
        if t0 is None or t1 is None:
            continue
        cg = ps.setdefault("cgroup", {})
        for key, dst in (("pgscan", "pgscan_delta"),
                         ("pgsteal", "pgsteal_delta"),
                         ("workingset_refault_file", "workingset_refault_file_delta")):
            a, b = _at(series, t0, key), _at(series, t1, key)
            if a is not None and b is not None and cg.get(dst) is None:
                cg[dst] = b - a
        for key, dst in (("active_file", "active_file_end"),
                         ("inactive_file", "inactive_file_end"),
                         ("memory_swap_current", "memory_swap_current_end")):
            v = _at(series, t1, key)
            if v is not None and cg.get(dst) is None:
                cg[dst] = v
    doc["_host_sample_status"] = f"filled from {len(series)} host samples"


def es_mode_of(cell):
    """Early-sort mode of a cell. Cells written before the early-sort arm
    existed have no `early_sort` object at all and are `none` by definition."""
    return (cell.get("early_sort") or {}).get("mode") or "none"


def load_order_of(cell):
    """The cell's load order. Tier-1 cells have no such field: they were loaded
    L-then-R by construction, and are labelled as legacy so the difference can
    never be read as an interleaved Tier-1b cell."""
    lp = cell.get("load_phase") or {}
    lo = lp.get("load_order")
    if lo:
        return lo
    return "l_then_r(legacy-tier1)"


def is_legacy(cell):
    return (cell.get("load_phase") or {}).get("load_order") is None


def is_order_arm(cell):
    """True for the pre-registered EXPLORATORY order arm. Recorded, never
    judged — excluded from every table and bar by construction."""
    return bool((cell.get("load_phase") or {}).get("order_arm"))


def converged_fixed(cell):
    """The FIXED (defect-D3) convergence rule, recomputed from the cell's own
    per-pass majflt rather than trusted from its `converged` field:

        converged == the majflt PLATEAUED (+/-10% pass-to-pass, twice in a row,
                     ending at the final pass)
                 AND the final pass's majflt is < 1% of pass 1's, or exactly 0.

    Tier-1's rule accepted either half alone, so deep's flat ~1.31M majflt/pass
    was scored "converged" (RESULTS.md §6 D3). Recomputing here means cells
    written by the old cell.sh are re-judged under the same rule as new ones.
    Returns (bool, reason).
    """
    ps = cell.get("passes") or []
    m = [p.get("majflt") for p in ps]
    if any(v is None for v in m) or len(m) < 3:
        return False, f"needs >=3 passes with majflt (have {len(m)})"

    def step_ok(a, b):
        if a == 0 and b == 0:
            return True
        return a > 0 and abs(b - a) * 10 <= a

    plateau = step_ok(m[-3], m[-2]) and step_ok(m[-2], m[-1])
    if m[-1] == 0:
        lowfault, why = True, "majflt_zero"
    elif m[0] > 0 and m[-1] * 100 < m[0]:
        lowfault, why = True, "majflt_below_1pct_of_pass1"
    else:
        lowfault, why = False, f"final majflt {m[-1]:,} is not <1% of pass-1 {m[0]:,}"
    if plateau and lowfault:
        return True, f"plateau_within_10pct_x2_and_{why}"
    if not plateau:
        return False, f"no +/-10% plateau over the last 3 passes ({m[-3]:,} -> {m[-2]:,} -> {m[-1]:,})"
    return False, why


def conv_note(cell):
    """'converged=X (reason)' with a loud marker when the recomputed D3 verdict
    disagrees with what the cell recorded for itself."""
    ok, why = converged_fixed(cell)
    stored = bool(cell.get("converged"))
    tag = ""
    if cell.get("mode") == "fixed3":
        # A fixed-window cell never self-reports convergence (converge_reason is
        # "n/a_fixed_window"), so a disagreement here is not a defect — the rule
        # is simply being applied to the 3-pass window for the bars that need it.
        return (f"converged={ok} ({why}) [fixed-window cell: rule applied to its "
                f"{len(cell.get('passes') or [])} passes; the cell itself does not self-report]")
    if stored != ok:
        tag = (f"  [!! cell JSON says converged={stored} "
               f"({cell.get('converge_reason')}) — re-judged by the FIXED D3 rule]")
    return f"converged={ok} ({why}){tag}"


def run_key(cell):
    """(run, date) grouping key used to pair an early-sort cell with its OWN
    run's baseline. run_label is 'scale<S>_<cellmode>[_smoke][_nocap]'; the
    cell-mode token is stripped so a fixed3 cell and a converge cell from the
    same ladder group together, while different days/scales never do."""
    parts = [p for p in (cell.get("run_label") or "").split("_")
             if p not in ("fixed3", "converge")]
    return ("_".join(parts), (cell.get("generated_utc") or "")[:10])


def by_rung(cells, mode=None, es="none"):
    """Newest cell per rung. `es` filters on early-sort mode; the default keeps
    the table and bars 1b-5 seeing baseline cells ONLY. Exploratory order-arm
    cells are dropped here, so they can never displace a judged cell."""
    out = {}
    for c in cells:
        if mode and c.get("mode") != mode:
            continue
        if es is not None and es_mode_of(c) != es:
            continue
        if is_order_arm(c):
            continue
        out.setdefault(c["rung"], []).append(c)
    # newest generated_utc wins if a rung was run twice in the same mode
    return {k: sorted(v, key=lambda d: d.get("generated_utc", ""))[-1]
            for k, v in out.items()}


# ---------------------------------------------------------------- table
def fmt(v, spec="", dash="-"):
    if v is None:
        return dash
    try:
        return format(v, spec) if spec else str(v)
    except (TypeError, ValueError):
        return str(v)


def ns_to_ms(v):
    return None if v is None else v / 1e6


def ns_to_us(v):
    return None if v is None else v / 1e3


def safediv(a, b):
    """a/b, or None when it is not defined (b is 0 or either side missing)."""
    if a is None or b is None or b == 0:
        return None
    return a / b


def r(v, spec):
    """Format a possibly-None ratio."""
    return "n/a" if v is None else format(v, spec)


HEADERS = ["rung", "cap", "pass", "p50 us", "p95 us", "wall s", "majflt",
           "ms/flt", "pgscanD", "wsrfD", "actfile MiB", "R res%", "L res%"]
WIDTHS = [9, 7, 5, 9, 9, 8, 10, 8, 11, 10, 12, 8, 8]


def print_table(cells, mode, es="none"):
    sel = by_rung(cells, mode, es)
    if not sel:
        if es == "none":
            print(f"\n(no cells in mode '{mode}')")
        return
    print(f"\n{'=' * 118}")
    print(f"MODE: {mode}" + ("" if es == "none" else f"   EARLY_SORT: {es}"))
    print("=" * 118)
    print("".join(h.rjust(w) for h, w in zip(HEADERS, WIDTHS)))
    print("-" * 118)
    for rung in RUNG_ORDER:
        c = sel.get(rung)
        if not c:
            continue
        for ps in c["passes"]:
            cg = ps.get("cgroup", {}) or {}
            af = cg.get("active_file_end")
            row = [
                rung,
                c.get("cap_label", "?"),
                str(ps["pass"]),
                fmt(ns_to_us(ps.get("clat_ns_p50")), ".2f"),
                fmt(ns_to_us(ps.get("clat_ns_p95")), ".2f"),
                fmt(ps.get("wall_s"), ".2f"),
                fmt(ps.get("majflt"), ",d"),
                fmt(ps.get("ms_per_fault"), ".4f"),
                fmt(cg.get("pgscan_delta"), ",d"),
                fmt(cg.get("workingset_refault_file_delta"), ",d"),
                fmt(None if af is None else af / MIB, ".1f"),
                fmt(ps.get("resident_pct_R"), ".1f"),
                fmt(ps.get("resident_pct_L"), ".1f"),
            ]
            print("".join(x.rjust(w) for x, w in zip(row, WIDTHS)))
        flags = []
        if c.get("swap_confounded"):
            flags.append("SWAP-CONFOUNDED (recorded-not-concluded)")
        if not c.get("cap_enforced", True):
            flags.append("CAP NOT ENFORCED")
        if c.get("_host_sample_status"):
            flags.append("cgroup host-read: " + c["_host_sample_status"])
        lp = c.get("load_phase") or {}
        note = (f"    -> passes_run={c['passes_run']} {conv_note(c)}"
                f" evictOK R={c['eviction']['post_evict_resident_pct_R']}%"
                f" L={c['eviction']['post_evict_resident_pct_L']}%")
        if flags:
            note += "  [" + "; ".join(flags) + "]"
        print(note)
        # Tier-1b: the load order and the post-load residency of BOTH files are
        # the evidence that pass 1 started from a partially non-resident R.
        print(f"    -> load_order={load_order_of(c)}"
              + (f" chunk={lp.get('chunk_mib')}MiB "
                 f"R={lp.get('n_chunks_R')}c/L={lp.get('n_chunks_L')}c"
                 if lp.get("load_order") == "interleaved" else "")
              + f"  post-load residency R={fmt(lp.get('post_load_resident_pct_R'), '.4f')}%"
                f" L={fmt(lp.get('post_load_resident_pct_L'), '.4f')}%"
              + ("   [LEGACY Tier-1 cell — Tier-1b bars do NOT apply; "
                 "see RESULTS.md for the frozen Tier-1 verdict]" if is_legacy(c) else ""))
        if es_mode_of(c) != "none":
            print("    " + es_action_line(c))
        print("-" * 118)


def es_action_line(cell):
    """One-line description of the early-sort action a cell actually took."""
    e = cell.get("early_sort") or {}
    bits = [f"early_sort={e.get('mode')}"]
    if e.get("blocked"):
        bits.append(f"BLOCKED ({e.get('blocked_reason')}) — ran as a 'none' cell")
    else:
        bits.append(f"applied={e.get('applied')} wall={fmt(e.get('action_wall_s'), '.4f')}s")
        bits.append(f"post-action residency R={fmt(e.get('post_action_resident_pct_R'), '.2f')}%"
                    f" L={fmt(e.get('post_action_resident_pct_L'), '.2f')}%")
        if e.get("bytes_requested") is not None:
            bits.append(f"requested={e['bytes_requested'] / MIB:.0f} MiB")
            fr = e.get("bytes_freed_observed")
            bits.append("freed(memory.current)=" +
                        ("n/a" if fr is None else f"{fr / MIB:.0f} MiB"))
        if e.get("early_sort_failed"):
            bits.append(f"EARLY_SORT_FAILED ({e.get('failed_reason')})")
    return "; ".join(bits)


# ----------------------------------------------------------------- bars
class Bar:
    def __init__(self, n, title):
        self.n, self.title, self.detail, self.status = n, title, [], "NO DATA"

    def say(self, s):
        self.detail.append(s)

    def verdict(self, ok):
        self.status = "PASS" if ok else "FAIL"
        return ok


def p50_ms(ps):
    """Kept for CONTEXT lines only. Tier-1b judges nothing on p50 — the
    synthetic's median is cache-hit-dominated even while thrashing."""
    return ns_to_ms(ps.get("clat_ns_p50"))


def p95_ms(ps):
    """THE Tier-1b latency metric (PREREGISTRATION_TIER1B.md Change 3)."""
    return ns_to_ms(ps.get("clat_ns_p95"))


def pass_n(cell, n):
    for ps in cell["passes"]:
        if ps["pass"] == n:
            return ps
    return None


def last_pass(cell):
    return cell["passes"][-1] if cell.get("passes") else None


def bar1(fixed):
    b = Bar("1b", "Inversion at the fixed pass-3 window, on clat p95 "
                  "(PRECONDITION: marginal pass-1 majflt > 0; then boundary p95 "
                  "< marginal p95 while marginal's majflt is still falling)")
    m, bd = fixed.get("marginal"), fixed.get("boundary")
    if not m or not bd:
        b.say("need fixed3 cells for BOTH marginal and boundary")
        return b
    m3, b3 = pass_n(m, 3), pass_n(bd, 3)
    m1, m2 = pass_n(m, 1), pass_n(m, 2)
    if not all([m1, m2, m3, b3]):
        b.say("need 3 passes in both cells")
        return b
    # PRECONDITION — the thing Tier-1 lacked. Without a pass-1 fault there is no
    # convergence transient at all and everything below is noise between two
    # zero-fault cells (RESULTS.md §4, bar 1).
    precond = m1["majflt"] > 0
    b.say(f"PRECONDITION marginal pass-1 majflt = {m1['majflt']:,} (bar > 0) -> {precond}"
          + ("" if precond else "   <-- no transient exists; the rest is meaningless"))
    lp = (m.get("load_phase") or {})
    b.say(f"  marginal load: order={load_order_of(m)} post-load residency "
          f"R={fmt(lp.get('post_load_resident_pct_R'), '.4f')}% "
          f"L={fmt(lp.get('post_load_resident_pct_L'), '.4f')}%")
    inv = p95_ms(b3) < p95_ms(m3)
    ratio = safediv(p95_ms(m3), p95_ms(b3))
    falling = m3["majflt"] < m2["majflt"] < m1["majflt"]
    not_zero = m1["majflt"] > 0 and m3["majflt"] * 100 > m1["majflt"]
    b.say(f"pass-3 p95: boundary={p95_ms(b3):.4f} ms  marginal={p95_ms(m3):.4f} ms"
          f"  -> inversion ratio {r(ratio, '.2f')}x  ({'yes' if inv else 'NO'})")
    b.say(f"  (context only, NOT judged) pass-3 p50: boundary={p50_ms(b3):.4f} ms "
          f"marginal={p50_ms(m3):.4f} ms")
    b.say(f"marginal majflt trajectory: {m1['majflt']:,} -> {m2['majflt']:,} -> {m3['majflt']:,}"
          f"  falling={falling}  still>1%-of-pass1={not_zero}")
    b.verdict(precond and inv and falling and not_zero)
    return b


def bar2(conv):
    b = Bar("2b", "Same destination, not Belady (marginal & boundary both reach "
                  "steady state in <=12 passes under the FIXED convergence rule, "
                  "with steady p95 within +/-10% of each other)")
    m, bd = conv.get("marginal"), conv.get("boundary")
    if not m or not bd:
        b.say("need converge-mode cells for BOTH marginal and boundary")
        return b
    cm, whym = converged_fixed(m)
    cb, whyb = converged_fixed(bd)
    both = cm and cb
    within12 = m["passes_run"] <= 12 and bd["passes_run"] <= 12
    pm, pb = p95_ms(last_pass(m)), p95_ms(last_pass(bd))
    if pm is None or pb is None:
        b.say("clat p95 missing in one of the cells")
        return b
    mean = (pm + pb) / 2.0
    spread = safediv(abs(pm - pb), mean)
    b.say(f"marginal: {conv_note(m)} in {m['passes_run']} passes "
          f"[{whym}] steady p95={pm:.4f} ms final majflt={last_pass(m)['majflt']:,}")
    b.say(f"boundary: {conv_note(bd)} in {bd['passes_run']} passes "
          f"[{whyb}] steady p95={pb:.4f} ms final majflt={last_pass(bd)['majflt']:,}")
    b.say(f"steady-p95 spread = {r(None if spread is None else spread * 100, '.1f')}% "
          f"(bar: <=10%)   both converged={both}  within 12 passes={within12}")
    b.verdict(both and within12 and spread is not None and spread <= 0.10)
    return b


def converged_reference_p95(conv, fixed):
    """The steady p95 the cliff is measured against (bar 3b): the mean of the
    converged marginal+boundary cells."""
    vals = [p95_ms(last_pass(conv[rg])) for rg in ("marginal", "boundary")
            if conv.get(rg) and converged_fixed(conv[rg])[0]
            and p95_ms(last_pass(conv[rg])) is not None]
    if vals:
        return sum(vals) / len(vals), "mean of converged marginal+boundary (converge mode)"
    if fixed.get("boundary") and pass_n(fixed["boundary"], 3):
        return p95_ms(pass_n(fixed["boundary"], 3)), "boundary pass-3 (fixed3 fallback)"
    return None, "unavailable"


def bar3(fixed, conv):
    b = Bar("3b", "Cliff: thrash+deep stay flat-and-large (pass3 majflt >= 0.8x "
                  "pass2) with steady p95 >= 10x the converged reference p95, "
                  "neither converges; every rung >= boundary converges")
    ref, how = converged_reference_p95(conv, fixed)
    if ref is None:
        b.say("no converged reference p95 available")
        return b
    b.say(f"converged reference p95 = {ref:.4f} ms ({how})")
    ok = True
    for rung in ("thrash", "deep"):
        cell = conv.get(rung) or fixed.get(rung)
        if not cell:
            b.say(f"{rung}: NO CELL"); return b
        p2, p3 = pass_n(cell, 2), pass_n(cell, 3)
        if not p2 or not p3:
            b.say(f"{rung}: needs >=3 passes"); return b
        # A cell that never faulted at all is not "flat-and-large" — it is the
        # degenerate no-pressure case, and must not be scored as cliff behaviour.
        flat = p2["majflt"] > 0 and p3["majflt"] >= 0.8 * p2["majflt"]
        steady = p95_ms(last_pass(cell))
        slow = steady is not None and steady >= 10 * ref
        cvg, why = converged_fixed(cell)
        b.say(f"{rung}: majflt p2={p2['majflt']:,} p3={p3['majflt']:,} "
              f"(p3/p2={r(safediv(p3['majflt'], p2['majflt']), '.2f')}, "
              f"bar>=0.80 -> {flat}); "
              f"steady p95={fmt(steady, '.4f')} ms = {r(safediv(steady, ref), '.1f')}x converged "
              f"(bar>=10x -> {slow}); {conv_note(cell)}")
        ok = ok and flat and slow and not cvg
    for rung in ("fits", "marginal", "boundary"):
        cell = conv.get(rung)
        if not cell:
            b.say(f"{rung}: no converge-mode cell -> cannot confirm it converges")
            ok = False
            continue
        cvg, why = converged_fixed(cell)
        b.say(f"{rung}: {conv_note(cell)} in {cell['passes_run']} passes")
        ok = ok and cvg
    b.verdict(ok)
    return b


def bar4(fixed, conv):
    b = Bar("4b", "Pressure-scaled aging: pass-1 cgroup pgscan monotone "
                  f"non-decreasing fits -> deep, with values < "
                  f"{PGSCAN_NOISE_FLOOR_PAGES} pages "
                  f"({PGSCAN_NOISE_FLOOR_PAGES * 4096 // MIB} MiB) clamped to a "
                  "single '~0' tier")
    src = fixed if fixed else conv
    vals, missing = [], []
    for rung in RUNG_ORDER:
        cell = src.get(rung) or conv.get(rung) or fixed.get(rung)
        p1 = pass_n(cell, 1) if cell else None
        v = (p1 or {}).get("cgroup", {}).get("pgscan_delta")
        if v is None:
            missing.append(rung)
        vals.append((rung, v))
    b.say("pass-1 pgscan delta (raw): " +
          "  ".join(f"{rg}={fmt(v, ',d')}" for rg, v in vals))
    if missing:
        b.say(f"missing pgscan for: {', '.join(missing)} "
              f"(cgroup memory.stat unavailable in those cells)")
        return b

    def clamp(v):
        # Bar 4b noise floor: anything under the floor is one indistinguishable
        # "no pressure" tier, so ordering *within* it is not evidence either way.
        return 0 if v < PGSCAN_NOISE_FLOOR_PAGES else v

    seq = [clamp(v) for _, v in vals]
    b.say(f"clamped to the {PGSCAN_NOISE_FLOOR_PAGES}-page noise floor: " +
          "  ".join(f"{rg}=" + ("~0" if clamp(v) == 0 else f"{v:,}")
                    for rg, v in vals))
    mono = all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1))
    b.say(f"monotone non-decreasing (after clamping) = {mono}")
    b.verdict(mono)
    return b


def bar5(fixed, conv):
    b = Bar(5, "The sort-not-needed datum: at the fits rung active_file stays "
               "<< R (est. < 0.25 x R) through all passes")
    cell = fixed.get("fits") or conv.get("fits")
    if not cell:
        b.say("no fits cell")
        return b
    r_bytes = cell["files"]["R_bytes"]
    limit = 0.25 * r_bytes
    vals = [(ps["pass"], (ps.get("cgroup", {}) or {}).get("active_file_end"))
            for ps in cell["passes"]]
    if any(v is None for _, v in vals):
        b.say("active_file unavailable (cgroup memory.stat not readable)")
        return b
    b.say(f"R = {r_bytes / MIB:.0f} MiB; bar = active_file < {limit / MIB:.0f} MiB")
    for p, v in vals:
        b.say(f"  pass {p}: active_file = {v / MIB:.1f} MiB "
              f"({v / r_bytes:.3f} x R) {'OK' if v < limit else 'OVER'}")
    b.verdict(all(v < limit for _, v in vals))
    return b


# ------------------------------------------------------- EARLY-SORT arm
# PREREGISTRATION_EARLYSORT.md. This whole section is inert unless the glob
# contains at least one cell with early_sort.mode != "none".
ES_HEADLINE = ("marginal", "boundary")


def es_groups(cells):
    """{run_key: [cells]}, restricted to run keys that hold >=1 ES cell."""
    groups = {}
    for c in cells:
        groups.setdefault(run_key(c), []).append(c)
    return {k: v for k, v in groups.items()
            if any(es_mode_of(c) != "none" for c in v)}


def es_pick(group, cellmode, rung, esm):
    cand = [c for c in group
            if c.get("mode") == cellmode and c.get("rung") == rung
            and es_mode_of(c) == esm and not is_order_arm(c)]
    if not cand:
        return None
    return sorted(cand, key=lambda d: d.get("generated_utc", ""))[-1]


def es_steady_ref(group, rung):
    """The rung's converged steady **p95** — the yardstick for ES-1 and ES-2
    (Tier-1b substitutes p95 for p50 throughout, and uses the fixed D3
    convergence rule). -> (value, source, trusted). Only a `none` converge cell
    from THIS run is trusted; the fallbacks are printed but never scored,
    because comparing the guided arm against itself would be circular."""
    c = es_pick(group, "converge", rung, "none")
    if c is not None:
        cvg, why = converged_fixed(c)
        tag = "" if cvg else f" (did NOT converge: {why} — read with care)"
        return (p95_ms(last_pass(c)),
                f"`none` converge cell, {c['passes_run']} passes{tag}",
                cvg)
    g = es_pick(group, "converge", rung, "guided")
    if g is not None:
        return (p95_ms(last_pass(g)),
                "FALLBACK: guided converge last pass — no `none` converge cell in this run",
                False)
    n = es_pick(group, "fixed3", rung, "none")
    if n is not None:
        return (p95_ms(last_pass(n)),
                "FALLBACK: `none` fixed3 LAST pass — no converge cell in this run "
                "(this is not a converged steady state)",
                False)
    return None, "unavailable — no baseline cell for this rung in this run", False


def transient_excess(cell, steady, upto=3):
    """Sum over passes 1..upto of max(0, p95 - steady) in ms. -> (sum, n)."""
    if cell is None or steady is None:
        return None, 0
    tot, n = 0.0, 0
    for ps in cell.get("passes", []):
        if ps["pass"] > upto:
            break
        v = p95_ms(ps)
        if v is None:
            return None, 0
        tot += max(0.0, v - steady)
        n += 1
    return (tot, n) if n else (None, 0)


def es_bar1(group):
    b = Bar("ES-1", "The claim: at marginal and boundary, guided pass-1 p95 "
                    "<= 2x that rung's converged steady p95")
    ok, complete = True, True
    for rung in ES_HEADLINE:
        g = es_pick(group, "fixed3", rung, "guided")
        steady, how, trusted = es_steady_ref(group, rung)
        base = es_pick(group, "fixed3", rung, "none")
        if not trusted:
            complete = False
        if g is None or steady is None or pass_n(g, 1) is None:
            b.say(f"{rung}: NO DATA (guided fixed3 cell={'yes' if g else 'NO'}; "
                  f"steady ref: {how})")
            complete = False
            continue
        p1 = pass_n(g, 1)
        ratio = safediv(p95_ms(p1), steady)
        hit = ratio is not None and ratio <= 2.0
        b.say(f"{rung}: guided pass-1 p95={p95_ms(p1):.4f} ms  majflt={p1['majflt']:,} "
              f"| steady={steady:.4f} ms [{how}] -> {r(ratio, '.2f')}x "
              f"(bar <=2.00x -> {hit})" +
              ("" if trusted else "   [NOT SCORED: steady reference is a fallback]"))
        if base is not None and pass_n(base, 1) is not None:
            bp1 = pass_n(base, 1)
            b.say(f"    baseline `none` pass-1 for context: p95={p95_ms(bp1):.4f} ms "
                  f"({r(safediv(p95_ms(bp1), steady), '.2f')}x steady) "
                  f"majflt={bp1['majflt']:,}")
        else:
            b.say("    (no same-run `none` fixed3 baseline for context)")
        ok = ok and hit
    if complete:
        b.verdict(ok)
    return b


def es_bar2(group):
    b = Bar("ES-2", "Transient eliminated: guided transient excess "
                    "(sum over passes 1-3 of p95-steady) reduced >=80% vs the "
                    "same rung's `none` cell [judged at marginal+boundary]")
    ok, complete = True, True
    for rung in RUNG_ORDER:
        g = es_pick(group, "fixed3", rung, "guided")
        n = es_pick(group, "fixed3", rung, "none")
        steady, how, trusted = es_steady_ref(group, rung)
        headline = rung in ES_HEADLINE
        if headline and not trusted:
            complete = False
        eg, ng_ = transient_excess(g, steady)
        en, nn_ = transient_excess(n, steady)
        if eg is None or en is None:
            msg = (f"{rung}: NO DATA (guided={'yes' if g else 'NO'} "
                   f"baseline={'yes' if n else 'NO'} steady ref: {how})")
            b.say(msg + ("" if headline else "   [informational]"))
            if headline:
                complete = False
            continue
        red = None if en == 0 else 1.0 - (eg / en)
        hit = red is not None and red >= 0.80
        b.say(f"{rung}: excess none={en:.6f} ms (n={nn_})  guided={eg:.6f} ms (n={ng_}) "
              f"-> reduction {r(None if red is None else red * 100, '.1f')}% "
              f"(bar >=80%) -> {'undefined' if red is None else hit}"
              + ("" if headline else "   [informational]"))
        if red is None:
            # Not a FAIL: with a zero baseline excess there was no transient to
            # remove, so the ratio the bar is written on does not exist.
            b.say(f"    baseline excess is 0 at {rung}: there was no transient to "
                  f"remove, so the reduction is UNDEFINED (recorded, not scored)")
            if headline:
                complete = False
            continue
        if headline:
            ok = ok and hit
    if complete:
        b.verdict(ok)
    return b


def es_bar3(group):
    b = Bar("ES-3", "No free lunch at steady state: guided converged steady p95 "
                    "within +/-10% of the `none` steady p95")
    ok, complete = True, True
    for rung in ES_HEADLINE:
        g = es_pick(group, "converge", rung, "guided")
        n = es_pick(group, "converge", rung, "none")
        if g is None or n is None:
            b.say(f"{rung}: NO DATA (guided converge={'yes' if g else 'NO'}, "
                  f"`none` converge={'yes' if n else 'NO'})")
            complete = False
            continue
        pg, pn = p95_ms(last_pass(g)), p95_ms(last_pass(n))
        dev = safediv(abs(pg - pn), pn)
        hit = dev is not None and dev <= 0.10
        b.say(f"{rung}: guided steady p95={pg:.4f} ms ({conv_note(g)}, "
              f"{g['passes_run']} passes)  none steady p95={pn:.4f} ms "
              f"({conv_note(n)}, {n['passes_run']} passes) "
              f"-> deviation {r(None if dev is None else dev * 100, '.1f')}% "
              f"(bar <=10%) -> {hit}")
        ok = ok and hit
    if complete:
        b.verdict(ok)
    return b


def es_bar4(group):
    b = Bar("ES-4", "The boundaries hold: at fits guided changes nothing "
                    "(pass-1 p95 within +/-25% of `none`); at thrash guided does "
                    "NOT rescue (pass-3 majflt >= 0.8x pass-2)")
    ok, complete = True, True
    g, n = es_pick(group, "fixed3", "fits", "guided"), es_pick(group, "fixed3", "fits", "none")
    if g is None or n is None or pass_n(g, 1) is None or pass_n(n, 1) is None:
        b.say(f"fits: NO DATA (guided={'yes' if g else 'NO'}, baseline={'yes' if n else 'NO'})")
        complete = False
    else:
        pg, pn = p95_ms(pass_n(g, 1)), p95_ms(pass_n(n, 1))
        dev = safediv(abs(pg - pn), pn)
        hit = dev is not None and dev <= 0.25
        b.say(f"fits: guided pass-1 p95={pg:.4f} ms  none pass-1 p95={pn:.4f} ms "
              f"-> deviation {r(None if dev is None else dev * 100, '.1f')}% "
              f"(bar <=25%) -> {hit}")
        ok = ok and hit
    t = es_pick(group, "fixed3", "thrash", "guided") or es_pick(group, "converge", "thrash", "guided")
    p2, p3 = (pass_n(t, 2), pass_n(t, 3)) if t else (None, None)
    if not p2 or not p3:
        b.say(f"thrash: NO DATA (guided cell with >=3 passes={'yes' if t else 'NO'})")
        complete = False
    else:
        # A cell that never faulted is not "the cliff held" — it is no pressure.
        flat = p2["majflt"] > 0 and p3["majflt"] >= 0.8 * p2["majflt"]
        b.say(f"thrash: guided majflt p1={pass_n(t, 1)['majflt']:,} p2={p2['majflt']:,} "
              f"p3={p3['majflt']:,} (p3/p2={r(safediv(p3['majflt'], p2['majflt']), '.2f')}, "
              f"bar >=0.80 and p2>0) -> {flat}")
        ok = ok and flat
    if complete:
        b.verdict(ok)
    return b


ES5_HEAD = ["rung", "blind state", "excess none", "excess guid", "excess blind",
            "guid red%", "blind red%", "blind/guid", "postR%", "postL%",
            "freed MiB", "act s"]
ES5_W = [9, 13, 13, 13, 13, 11, 11, 11, 8, 8, 10, 8]


def es_bar5_table(group):
    """ES-5 is exploratory: RECORDED, NOT JUDGED. No verdict is issued."""
    print("\nES-5 (exploratory — RECORDED, NOT PASS/FAIL): blind's transient "
          "reduction as a fraction of guided's,")
    print("      and post-reclaim residency of R vs L (did inactive-list order "
          "protect the repeat set?).")
    print("      Excess columns are p95-based (Tier-1b). Under the INTERLEAVED "
          "load the inactive-list order no")
    print("      longer cleanly favours L, so blind R-survival here is the "
          "honest predictor for the map-blind lever;")
    print("      Tier-1's order-protected numbers (100 -> 39.8% descending caps) "
          "are the upper bound to compare against.")
    print("".join(h.rjust(w) for h, w in zip(ES5_HEAD, ES5_W)))
    print("-" * sum(ES5_W))
    notes = []
    for rung in RUNG_ORDER:
        bl = es_pick(group, "fixed3", rung, "blind")
        if bl is None:
            continue
        gd = es_pick(group, "fixed3", rung, "guided")
        nn = es_pick(group, "fixed3", rung, "none")
        steady, how, _trusted = es_steady_ref(group, rung)
        en, _ = transient_excess(nn, steady)
        eg, _ = transient_excess(gd, steady)
        eb, _ = transient_excess(bl, steady)
        red_g = None if (en in (None, 0) or eg is None) else 1.0 - eg / en
        red_b = None if (en in (None, 0) or eb is None) else 1.0 - eb / en
        frac = None if (red_g in (None, 0) or red_b is None) else red_b / red_g
        e = bl.get("early_sort") or {}
        state = ("BLOCKED" if e.get("blocked")
                 else ("partial/err" if e.get("early_sort_failed")
                       else ("applied" if e.get("applied") else "no-action")))
        freed = e.get("bytes_freed_observed")
        row = [rung, state,
               fmt(en, ".6f"), fmt(eg, ".6f"), fmt(eb, ".6f"),
               "n/a" if red_g is None else f"{red_g * 100:.1f}",
               "n/a" if red_b is None else f"{red_b * 100:.1f}",
               "n/a" if frac is None else f"{frac:.2f}",
               fmt(e.get("post_action_resident_pct_R"), ".1f"),
               fmt(e.get("post_action_resident_pct_L"), ".1f"),
               "n/a" if freed is None else f"{freed / MIB:.0f}",
               fmt(e.get("action_wall_s"), ".2f")]
        print("".join(str(x).rjust(w) for x, w in zip(row, ES5_W)))
        if e.get("blocked"):
            notes.append(f"  {rung}: blind BLOCKED — {e.get('blocked_reason')}")
        elif e.get("early_sort_failed"):
            notes.append(f"  {rung}: blind write reported an error (a datum, not an abort) — "
                         f"rc={e.get('write_rc')} {e.get('write_stderr')}")
        if e.get("bytes_requested") is not None and not e.get("blocked"):
            notes.append(f"  {rung}: requested {e['bytes_requested'] / MIB:.0f} MiB; "
                         f"steady ref from: {how}")
    print("-" * sum(ES5_W))
    for n in notes:
        print(n)
    print("  Reading: blind/guid = 1.00 means blind matched the map-guided arm; "
          "0.00 means it did nothing for the transient.")
    print("  postR%/postL% are residency IMMEDIATELY AFTER the action: R high + "
          "L low = inactive-list order protected the repeat set.")


def print_es_section(cells, mechanics_only):
    groups = es_groups(cells)
    if not groups:
        return
    print(f"\n{'=' * 118}")
    print("EARLY-SORT ARM (PREREGISTRATION_EARLYSORT.md) — the §5.3 "
          "'skip the sort' claim")
    print("=" * 118)
    # Pair strictly within one run: same run label (mode token stripped) and the
    # same date. Cross-run comparison is forbidden by the pre-registration.
    key = max(groups, key=lambda k: sum(1 for c in groups[k] if es_mode_of(c) != "none"))
    group = groups[key]
    print(f"run paired on : run='{key[0] or '(no run_label)'}'  date={key[1] or '(unknown)'}")
    if len(groups) > 1:
        others = ", ".join(f"{k[0]}@{k[1]}" for k in groups if k != key)
        print(f"!! {len(groups)} distinct runs carry early-sort cells; judging ONLY the "
              f"largest. NOT judged (never compare across runs): {others}")
    have = {}
    for c in group:
        if is_order_arm(c):     # never an ES baseline; reported in its own section
            continue
        have.setdefault((es_mode_of(c), c.get("mode")), []).append(c["rung"])
    for (m, cm), rungs in sorted(have.items()):
        print(f"  early_sort={m:7s} mode={cm:9s} rungs: {', '.join(sorted(rungs))}")
    for es in ("guided", "blind"):
        for cm in ("fixed3", "converge"):
            print_table(group, cm, es)
    print(f"\n{'=' * 118}")
    if mechanics_only:
        print("EARLY-SORT BARS — *** MECHANICS CHECK ONLY, NOT A BAR VERDICT ***")
        print("  Same refusal as the Tier-1 bars: scale != 1.0 and/or "
              "cap_enforced=false on at least one cell.")
    else:
        print("EARLY-SORT BARS (PREREGISTRATION_EARLYSORT.md) — "
              "ES-1..ES-4 all must hold for PASS; ES-5 is recorded, not judged")
    print("=" * 118)
    bars = [es_bar1(group), es_bar2(group), es_bar3(group), es_bar4(group)]
    for b in bars:
        tag = b.status + (" (mechanics — NOT a bar verdict)"
                          if mechanics_only and b.status != "NO DATA" else "")
        print(f"\nBAR {b.n}: {b.title}")
        print(f"  VERDICT: {tag}")
        for d in b.detail:
            print(f"    {d}")
    print()
    es_bar5_table(group)
    print(f"\n{'=' * 118}")
    if mechanics_only:
        print("EARLY-SORT OVERALL: MECHANICS CHECK — no bar verdict issued.")
    else:
        allpass = all(b.status == "PASS" for b in bars)
        print("EARLY-SORT OVERALL: " +
              ("PASS — ES-1..ES-4 all hold (ES-5 recorded, not judged)" if allpass
               else "FAIL — see ES bars above. ES-1/ES-2 failing with a sound "
                    "harness REFUTES §5.3 for the synthetic; record it, do not tune it away."))
    print("=" * 118)


# -------------------------------------------------- EXPLORATORY ORDER ARM
# PREREGISTRATION_TIER1B.md "Exploratory order arm": one marginal/fixed3 cell
# loaded R-then-L, completing the load-order triptych (L->R = Tier-1's
# pre-sorted load; interleaved = the Tier-1b protocol; R->L = residue is the
# most-recently-loaded population). INFORMATIONAL ONLY — it measures how much
# the artifact's visibility depends on load order, which RESULTS.md §2 already
# records as a finding. No verdict is ever issued here.
OA_HEAD = ["rung", "mode", "load order", "postload R%", "postload L%",
           "p1 majflt", "p3 majflt", "p1 p95 ms", "p3 p95 ms"]
OA_W = [10, 10, 14, 13, 13, 12, 12, 12, 12]


def print_order_arm_section(cells):
    arms = [c for c in cells if is_order_arm(c)]
    if not arms:
        return
    print(f"\n{'=' * 118}")
    print("EXPLORATORY ORDER ARM (PREREGISTRATION_TIER1B.md) — RECORDED, NOT JUDGED")
    print("=" * 118)
    print("Interleaved baselines for the same rung/mode are shown alongside for "
          "contrast. No bar is scored on any row here.")
    print("".join(h.rjust(w) for h, w in zip(OA_HEAD, OA_W)))
    print("-" * sum(OA_W))
    base = [c for c in cells if not is_order_arm(c) and es_mode_of(c) == "none"]
    rows = list(arms)
    for a in arms:
        rows += [c for c in base
                 if c.get("rung") == a.get("rung") and c.get("mode") == a.get("mode")]
    seen = set()
    for c in rows:
        if id(c) in seen:
            continue
        seen.add(id(c))
        lp = c.get("load_phase") or {}
        p1, p3 = pass_n(c, 1), pass_n(c, 3)
        row = [c.get("rung", "?"), c.get("mode", "?"), load_order_of(c),
               fmt(lp.get("post_load_resident_pct_R"), ".4f"),
               fmt(lp.get("post_load_resident_pct_L"), ".4f"),
               fmt((p1 or {}).get("majflt"), ",d"),
               fmt((p3 or {}).get("majflt"), ",d"),
               fmt(p95_ms(p1) if p1 else None, ".4f"),
               fmt(p95_ms(p3) if p3 else None, ".4f")]
        print("".join(str(x).rjust(w) for x, w in zip(row, OA_W)))
    print("-" * sum(OA_W))
    for c in arms:
        print(f"  {os.path.basename(c['_path'])}: load_order="
              f"{load_order_of(c)}  {conv_note(c)}")
    print("  Reading: a large postload R% with ~0 pass-1 majflt means the LOAD "
          "did the sorting (Tier-1's failure mode).")
    print("=" * 118)


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="explicit cell JSON paths")
    ap.add_argument("--dir", default=None, help="directory to scan")
    # DEFECT D1 FIX (RESULTS.md §6). The DOCUMENTED glob is 'convrepro_t1b_*'.
    # run_ladder.sh writes every cell that can never be bar evidence (smoke /
    # uncapped --local) under the prefix 'convrepro_mech_' instead, so this glob
    # cannot pull a mechanics cell into a bar run no matter what date it wears.
    # Tier-1's glob relied on the operator remembering to filter — it did not.
    ap.add_argument("--glob", default="convrepro_t1b_*.json",
                    help="glob within --dir (default: convrepro_t1b_*.json — "
                         "mechanics cells are convrepro_mech_* and are excluded "
                         "by construction)")
    args = ap.parse_args()

    paths = list(args.files)
    if args.dir:
        paths += globmod.glob(os.path.join(args.dir, args.glob))
    if not paths:
        ap.error("no input: give files or --dir")

    cells = load_cells(paths)
    if not cells:
        print("no valid convrepro cell documents found")
        return 1

    scales = sorted({c["scale"] for c in cells})
    enforced = all(c.get("cap_enforced", True) for c in cells)
    mechanics_only = (scales != [1.0]) or not enforced

    print("=" * 118)
    print("convergence_repro TIER-1b — synthetic repro of the fixed-window "
          "convergence inversion (PREREGISTRATION_TIER1B.md)")
    print("=" * 118)
    c0 = cells[0]
    n_es = sum(1 for c in cells if es_mode_of(c) != "none")
    print(f"cells loaded : {len(cells)}  ({', '.join(sorted({c['rung'] for c in cells}))})")
    print(f"modes        : {', '.join(sorted({c['mode'] for c in cells}))}")
    print(f"early sort   : {len(cells) - n_es} baseline (`none`) + {n_es} early-sort cells"
          f"  ({', '.join(sorted({es_mode_of(c) for c in cells}))})")
    print(f"load order(s): {', '.join(sorted({load_order_of(c) for c in cells}))}")
    legacy = [os.path.basename(c["_path"]) for c in cells if is_legacy(c)]
    if legacy:
        print(f"!! {len(legacy)} LEGACY (Tier-1) cell(s) in this glob — no "
              f"load_phase.load_order field, i.e. loaded L-then-R by the Tier-1")
        print("   protocol. The Tier-1b bars below are NOT the frozen Tier-1 "
              "verdict (that lives in RESULTS.md);")
        print("   Tier-1b judges interleaved-load cells. Legacy files: "
              + ", ".join(sorted(legacy)[:6])
              + (" ..." if len(legacy) > 6 else ""))
    arms = [c for c in cells if is_order_arm(c)]
    if arms:
        print(f"!! {len(arms)} EXPLORATORY ORDER-ARM cell(s) present — recorded, "
              f"NEVER judged; excluded from every table and bar. See the "
              f"ORDER-ARM section at the end.")
    print(f"scale(s)     : {scales}   caps enforced: {enforced}")
    print(f"kernel       : {c0['env']['kernel']}")
    print(f"lru_gen      : {c0['env']['lru_gen']}   "
          f"(absent = classic two-list LRU, the regime this spike targets)")
    print(f"cgroup       : {c0['env']['cgroup_version']}  "
          f"readable in-container: {c0['env']['cgroup_readable_in_container']}")
    print(f"fio randseed : {c0['fio_randseed']}")
    swapped = [c["rung"] for c in cells if c.get("swap_confounded")]
    if swapped:
        print(f"!! SWAP-CONFOUNDED cells (recorded-not-concluded): {', '.join(swapped)}")

    # Table and bars see BASELINE cells only (by_rung's es="none"), and never
    # the exploratory order arm (by_rung drops it).
    for mode in ("fixed3", "converge"):
        if any(c["mode"] == mode and es_mode_of(c) == "none"
               and not is_order_arm(c) for c in cells):
            print_table(cells, mode)

    fixed = by_rung(cells, "fixed3")
    conv = by_rung(cells, "converge")

    print(f"\n{'=' * 118}")
    if mechanics_only:
        print("PRE-REGISTERED BARS — *** MECHANICS CHECK ONLY, NOT A BAR VERDICT ***")
        print("  Reason: " + ("; ".join(
            ([f"scale(s) {scales} != [1.0]"] if scales != [1.0] else []) +
            (["cap_enforced=false on at least one cell"] if not enforced else []))))
        print("  The bars are judged by the session lead on a SCALE=1 docker ladder"
              " with caps enforced.")
    else:
        print("PRE-REGISTERED BARS (PREREGISTRATION_TIER1B.md) — ALL five must "
              "hold for PASS; all latency bars are on clat p95")
    print("=" * 118)

    bars = [bar1(fixed), bar2(conv), bar3(fixed, conv), bar4(fixed, conv),
            bar5(fixed, conv)]
    for b in bars:
        tag = b.status + (" (mechanics — NOT a bar verdict)"
                          if mechanics_only and b.status != "NO DATA" else "")
        print(f"\nBAR {b.n}: {b.title}")
        print(f"  VERDICT: {tag}")
        for d in b.detail:
            print(f"    {d}")

    print(f"\n{'=' * 118}")
    if mechanics_only:
        print("OVERALL: MECHANICS CHECK — no bar verdict issued.")
    else:
        allpass = all(b.status == "PASS" for b in bars)
        print(f"OVERALL: {'PASS — all 5 bars hold' if allpass else 'FAIL — see bars above'}")
        if swapped:
            print("         (swap-confounded cells present: recorded-not-concluded)")
    print("=" * 118)

    # Early-sort section: inert unless the glob holds early-sort cells.
    print_es_section(cells, mechanics_only)
    # Order-arm section: inert unless the glob holds order-arm cells.
    print_order_arm_section(cells)
    return 0


if __name__ == "__main__":
    sys.exit(main())
