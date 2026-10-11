#!/usr/bin/env python3
# CLOSED MEASURED 2026-09-30 — in-place bit-update spike harness (docs/archive/inplace_update/); evidence kept, pre-registered bars live in source
"""In-place bit updater, Stage 0 bar S0-3: block visits vs bound inflation.

BAR (verbatim from docs/delta_ingest/06_INPLACE_SPIKE_PLAN.md, commit 8c239e99):

  ### S0-3 — block visits vs bound inflation (Mechanism C, §2.4 of the brief)

  - **Placement:** every insert posting lands in the block that holds the
    slot S0-2 assigned it (dead slot or evicted slot).
  - **Inflation rule (per-block inflation byte):** for block b, on each
    insert, recompute b's summary as the build would (α = `summary_energy`
    0.4 over the component-wise max of the block incl. the new doc);
    m_b := max(m_b, max over components c present in the OLD summary of
    new_c / old_c); m_b is quantised UP to 1 + code/32, code ∈ 0..255. A
    block needing code > 255 is "saturated" and counted as visited for every
    query. Components absent from the old summary are not covered by a
    scalar multiplier; their count and summed weight per block are recorded
    as `blind_mass` (not gated).
  - **Visit count (static proxy, not the engine's dynamic count):** for
    query q, θ_q = the k′ = 200-th score of q's A0 run (S0-2 procedure);
    block b of a list of one of q's terms is visited iff
    m_b · dot(q, summary_b) ≥ heap_factor · θ_q with heap_factor = 0.8 (the
    E8 recall-max params). V(k) = total visits over the set after k quarters;
    V(0) = the same with m_b = 1 on the unchurned shard.
  - **Output:** T* = the largest k in {1, 2, 3, 4, 5, 6} with
    V(k)/V(0) − 1 ≤ 0.10 on each of QA, QT, QD — the proposed compaction
    threshold, also expressed as dead-slot fraction and mean m_b at T*.
  - **Thresholds.** PASS: T* ≥ 1 (visits grow ≤ +10 % after one quarter, so
    the compactor runs no more than quarterly). FAIL: > +10 % at k = 1 on any
    set.

Implementation notes (recorded in the results file):
  * The simulation is the S0-2 run (scripts/experiments/eval_inplace_s0_2.py
    runs Mechanism B and this bar's inflation bookkeeping in one pass over
    quarters 1..6 and writes both keys); this module holds the S0-3 visit
    counter and verdict so the bar lives in its own script as the plan asks.
  * new_c for a component c of the OLD summary = max(old_c, w_c of the new
    doc): the component-wise block max incl. the new doc, with the old
    summary value standing in for the old block max (quantised to within
    ~0.5 %, synthetic check). Whether c would survive the α re-truncation
    does not change the ratio for a component already in the old summary.
  * blind_mass proxy: new-doc components absent from the old summary whose
    weight is >= the smallest value retained in that block's old summary.
  * T* when no k qualifies: 0 (FAIL).
"""
from __future__ import annotations

import numpy as np

HEAP_FACTOR = 0.8
K_PRIME = 200


def visits_for_query(dots_by_term: list[np.ndarray], codes_by_term: list[np.ndarray | None], theta: float) -> int:
    """codes: None = unchurned (m_b = 1); -1 = saturated."""
    v = 0
    thr = HEAP_FACTOR * theta
    for d, c in zip(dots_by_term, codes_by_term):
        if len(d) == 0:
            continue
        if c is None:
            v += int((d >= thr).sum())
        else:
            m = 1.0 + np.maximum(c, 0) / 32.0
            v += int(((c < 0) | (m * d >= thr)).sum())
    return v


def verdict(ratios: dict[str, dict[int, float]]) -> tuple[str, int]:
    """ratios[set][k] = V(k)/V(0) - 1. Returns (verdict, T*)."""
    tstar = 0
    for k in range(1, 7):
        if all(ratios[s].get(k, np.inf) <= 0.10 for s in ratios):
            tstar = k
    ok1 = all(ratios[s].get(1, np.inf) <= 0.10 for s in ratios)
    return ("PASS" if ok1 and tstar >= 1 else "FAIL"), tstar


if __name__ == "__main__":
    print(__doc__)
    print("Run via scripts/experiments/eval_inplace_s0_2.py run (writes keys s0_2 and s0_3).")
