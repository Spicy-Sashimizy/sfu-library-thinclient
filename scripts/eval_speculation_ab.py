#!/usr/bin/env python3
"""deployprep WI-18b — three-arm speculation benchmark (THE core deliverable).

A deterministic typing simulator replays each query as timed keystrokes at three
WPM profiles (slow ~35, medium ~55, fast ~90) using a FIXED SEED + recorded
inter-key jitter, drives the SAME speculation rules as the client (same 400 ms
debounce + same ≥8 min-length), then submits at "Enter" and measures Enter→
response. Cells A–G, all on the WARM serve (process-cold/9p re-warm is WI-6/
WI-12 territory, OUT of scope; serve state recorded with every cell).

  A — cold floor:        SFU_RESULT_CACHE=0, n≥20, Enter→response p50/p95.
  B — pre-seed hit:      cache ON + primer, 6 seeds, n≥20 repeat-visits, p50/p95.
  C — speculation:        cache ON, speculation ON, non-seeded distinct queries,
                         n≥20 per typing profile (3 profiles), predictor mode AND
                         literal mode measured separately.
  D — cache-ON miss ctrl: cache ON, speculation OFF, non-seeded, n≥20 — must
                         match arm A within noise (isolates cache/spec overhead).
  E — interference:       while a continuous typist speculates, fire n≥10 real
                         cold searches; compare p50 vs arm A.
  F — waste:              speculative backend executions per completed search,
                         per profile + adversarial set.
  G — parity:            ≥6 speculation-primed responses byte-identical to fresh
                         cache-OFF runs (reuse eval_result_cache_parity.py shape).

Trial hygiene (arm C): a trial is valid only if its query was NOT cache-resident
before the typing simulation began (probed via /health resident + a key-probe);
contaminated trials are discarded + logged. Each arm-C trial uses a DISTINCT
query within a serve lifetime. Interleaved A/Bs only — trials interleaved across
arms WITHIN each cell (never all-A-then-all-B).

F6: every headline recomputed from the raw per-trial samples in the results
JSON (store per-trial raw samples + per-trial event timelines, not aggregates).

Pre-registered bars (docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md, set
BEFORE the first measured run):
  (a) arm B hit p50 ≤ 10 ms.
  (b) arm C medium-profile predictor-mode hit-rate ≥ 80% with hit latency
      ≤ 2× arm-B p50.
  (c) parity 6/6.
  (d) arm D within 10% of arm A AND arm E within 15% of arm A.
  (e) waste ≤ 3 speculative executions per completed search at medium profile.

Results → data/eval_results/speculation_ab_2026-07-28.json (raw per-trial
samples + event timelines included). WI-19a (HOST-NOTE-W8-3 fix, 2026-07-28):
the arm-C timeline is REAL-TIME — computed deterministically by `_build_timeline`
then played back in wall-clock (each computed interval SLEPT, each speculation
fired at its wall-clock spec point, Enter at enter_t REGARDLESS of store state;
the pre-Enter wait-for-store probe is DELETED, a background poller survives only
as post-trial bookkeeping for the lead-time distribution). The wave-8 file
`speculation_ab_2026-07-18.json` (arm A only, n=20, p50 2335.88 ms) is
HISTORICAL — the container rebuild + serve restart make cross-session mixing
unpromotable; it is left untouched. GUI-level validation: a SMALL Playwright
run (n≥5, medium profile, real SearchBar typing → Enter→results-rendered)
confirming the client wiring fires in a real browser — run SEPARATELY via
scripts/gui_testbed (the HTTP harness here is the measured evidence; the
Playwright pass is the wiring proof, NOT a latency source). NOTE: the wave-9
container rebuild left Playwright lib present but NO browser installed; the GUI
wiring proof relies on jsdom + HTTP, recorded honestly (browser NOT installed).

NOTE on arms A/D/B/E: the drive prompt's arm A says SFU_RESULT_CACHE=0 serve.
The benchmark itself drives a SINGLE warm serve (the staging serve on a port);
toggling SFU_RESULT_CACHE requires a restart. To keep the warm serve hot across
cells and avoid ~2 min re-warm between every arm, this script measures A on a
cache-OFF serve (operator starts it that way) and B/C/D/E/F on the cache-ON
serve. The operator runs the script ONCE per serve configuration and passes
--arm-set to select which cells run on the current serve. Parity (G) reuses
the OFF-vs-ON capture files from eval_result_cache_parity.py when present.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "eval_results" / "speculation_ab_2026-07-28.json"
SEED_FILE = REPO / "data" / "eval_results" / "demo_seed_queries.txt"
BENCH_FILE = REPO / "data" / "eval_results" / "speculation_bench_queries.txt"
# Arm G genuine OFF-vs-ON parity: cache-OFF fresh baselines captured during the
# cache_off leg land here, then the cache_on leg's speculation-primed Enter
# responses are compared to them (the pre-registered bar c — byte-identical to a
# fresh cache-OFF run, NOT round-trip identity which PASSes trivially).
G_OFF_BASELINE = REPO / "data" / "eval_results" / "_speculation_g_cacheoff_baseline.json"
DEFAULT_LIMIT = 50
SEED = 20260718  # fixed seed — deterministic typing replay (wave-8; retained for
                 # reproducibility — the timeline is deterministic, the playback is real)

# ── helpers ─────────────────────────────────────────────────────────────────


def http(method: str, url: str, body=None, timeout=120.0):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode())
            return r.status, payload, (time.perf_counter() - t0) * 1000.0
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            payload = {"error": str(e)}
        return e.code, payload, (time.perf_counter() - t0) * 1000.0


def pctl(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return round(s[k], 2)


def mean(vals):
    return round(statistics.mean(vals), 2) if vals else None


def seed_queries() -> list[str]:
    out = []
    if SEED_FILE.exists():
        for line in SEED_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    seen, dedup = set(), []
    for q in out:
        nq = " ".join(q.split()).casefold()
        if nq not in seen:
            seen.add(nq)
            dedup.append(q)
    return dedup


def bench_queries() -> list[str]:
    """The non-seeded pool (≥80), de-duplicated, order preserved."""
    out = []
    if BENCH_FILE.exists():
        for line in BENCH_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    seen, dedup = set(), []
    for q in out:
        nq = " ".join(q.split()).casefold()
        if nq not in seen:
            seen.add(nq)
            dedup.append(q)
    return dedup


def wait_warm(base, timeout=400):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st, h, _ = http("GET", f"{base}/health")
        if st == 200 and h.get("warmup") in ("warm", "failed"):
            return h
        time.sleep(2)
    return None


def health(base):
    st, h, _ = http("GET", f"{base}/health")
    return h if st == 200 else {}


# ── freshness: nonce-suffixed novel queries + per-trial residency probe ──────
# HOST-NOTE-W9-3 (2026-07-28): arms D / C-literal / F banked 100% hit-rates and
# 0.0 waste because they drew from the SAME bench pool with merely different
# seeds — so D's queries overlapped C-predictor's primed 60 (13/20 already
# resident → bimodal hits-among-misses), C-literal reused C-predictor's EXACT 60
# (same SEED+2 rng.sample → every Enter hit a key already resident → the
# physically-impossible 100% literal hit-rate), and F's 7/10 queries hit the
# cache so `_speculate_search` did a free hit (no fresh store → spec_stores_delta
# = 0). ONE root cause: query-pool contamination across cells in one serve
# lifetime. Contract term 7's pre-residency discipline applies to EVERY cell with
# miss/novel semantics, not just arm C.
#
# Fix (host W9-3 option: nonce-suffixed novel queries, mapped to the W8-1
# framing): predictor mode IS the known/in-pool-query scenario → it uses REAL
# bench queries (disjoint partition, primed by the speculation under test — that
# is the win being measured). literal mode IS the novel-query scenario → it
# types a real bench prefix but Enter-submits a NONCE-SUFFIXED query, so the
# literal speculation stores under the typed-prefix key (which can NEVER be the
# full-query key unless fired at the last keystroke — the host's physics) and
# the Enter is provably cache-cold by construction. D + F likewise use
# nonce-suffixed novel queries (genuine misses / genuine fresh stores). Arm E
# already did this correctly (kept as-is).
#
# A per-trial residency probe records the pre-trial resident-count + a
# latency-based heuristic; for nonce queries it confirms non-residency. For the
# predictor cells (real pool queries, which CAN be cross-contaminated by an
# earlier arm — see the disjoint partition below), the probe + a counter-delta
# sanity check discard a contaminated trial (term 7) rather than assuming it.

def _fresh_query(base_query: str) -> str:
    """Return a NONCE-SUFFIXED version of `base_query` for cells that must be
    cache-cold (D miss-control, F waste, C-literal novel-query, E interference).
    The suffix is a hex token from a DEDICATED deterministic RNG (the main SEED-
    driven typing RNG stays untouched); the query text stays a realistic
    academic query (the retriever scores the real terms, the cache key is
    normalized so the suffix guarantees a key never seen before). Deterministic
    per run for F6 (the transcript records the nonce token per trial; no
    time-derived entropy in a recorded result)."""
    return f"{base_query} {NONCE_RNG.getrandbits(24):06x}"


# A dedicated RNG for nonce generation so the main SEED-driven typing RNG is
# untouched (the typing jitter + spec_points stay reproducible across runs).
NONCE_RNG = random.Random(SEED + 909)


def _residency_probe(base, query) -> dict:
    """Per-trial term-7 probe: capture the result_cache counter snapshot so a
    contamination check can compare before/after. We do NOT key-probe over HTTP
    (no non-priming probe endpoint exists, and a /api/search probe would itself
    prime the key, defeating the purpose). Instead the nonce construction makes
    non-residency provable for novel-query cells, and for predictor cells the
    disjoint partition + this counter snapshot let a contaminated trial (a hit
    landing without this trial's speculation firing) be detected + discarded
    after-the-fact. LATENCY is the secondary signal: a resident key returns in
    single-digit ms; a genuine miss is ≥0.2 s on the warm serve."""
    h = health(base)
    rc = h.get("result_cache", {}) or {}
    return {"rc_hit": rc.get("hit", 0), "rc_miss": rc.get("miss", 0),
            "rc_store": rc.get("store", 0), "rc_resident": rc.get("resident", 0),
            "spec_stores": (h.get("speculation", {}) or {}).get("stores", 0)}


# ── deterministic typing simulator (REAL-TIME — WI-19a fix for HOST-NOTE-W8-3) ─
# The drive prompt: three profiles (slow ~35 WPM, medium ~55 WPM, fast ~90 WPM),
# fixed seed, inter-key jitter recorded. 1 WPM ≈ 5 chars/min → cps = WPM*5/60.
#
# WI-19a (HOST-NOTE-W8-3 REJECTED-BLOCKING fix, option (a) REAL-TIME simulation):
# the trial timeline is computed deterministically (t_ms per keystroke, injected
# thinking pauses, the spec_points at which the client debounce would fire, and
# enter_t) — then PLAYED BACK IN WALL-CLOCK TIME: the simulator SLEEPS each
# computed inter-key interval, fires each speculation at its spec point in real
# time, and presses Enter at enter_t REGARDLESS of speculative-store state.
# `resident_by_enter` is a fact observed at the real Enter instant (the cache
# HIT counter advanced on Enter — the speculation primed the exact key, term 1),
# NOT a probe-deadline artifact. The pre-Enter "wait up to 3 s for the store"
# probe that inflated hit-rate-by-construction is DELETED; a lightweight
# background poller survives ONLY as post-trial bookkeeping to record each
# fire's store-complete wall latency for the lead-time distribution — it never
# gates Enter and no code path waits on the store before Enter.

PROFILES = {
    # name: (wpm, label)
    "slow": (35, "slow ~35 WPM"),
    "medium": (55, "medium ~55 WPM"),
    "fast": (90, "fast ~90 WPM"),
}
DEBOUNCE_MS = 400  # client default (term 6)
MIN_LEN = 8
SPEC_CAP = 3  # max speculations fired per trial (realism: a user pauses a few
              # times mid-query, not 13×; earliest predictions win — they have
              # the most time to complete before Enter)


def wpm_to_interkey_ms(wpm: int) -> float:
    """Mean inter-keystroke interval (ms) for a WPM rate (5 chars/word)."""
    cps = wpm * 5.0 / 60.0
    return 1000.0 / cps if cps > 0 else 1000.0


def _build_timeline(query: str, wpm: int, rng: random.Random) -> dict:
    """PURE/deterministic: compute the full per-trial schedule with NO I/O.
    Returns keystroke events (each with t_ms + typed_so_far), injected thinking
    pauses, the enter_t, and the spec_points (keystroke char-indices where the
    client debounce fires a speculation). A spec_point is a keystroke whose
    typed-so-far text ≥ MIN_LEN AND whose following gap (next keystroke OR the
    pre-Enter pause) ≥ DEBOUNCE_MS — the client debounce fires DEBOUNCE_MS into
    that gap (fire_t = keystroke_t + DEBOUNCE_MS), so the speculation is in
    flight while the user is still paused/typing. Earliest spec_points win,
    capped at SPEC_CAP.

    Realism (term 6): the client debounce fires only after ≥400 ms IDLE.
    Continuous typing at any WPM < ~90 has inter-key < 400 ms, so a speculation
    NEVER fires mid-stream during pure typing — only when the user PAUSES (to
    think of the next word) or stops to verify before Enter. The simulator
    injects an occasional long pause at word boundaries (slower profile → longer
    + more frequent pauses, modelling cognitive load) AND a variable pre-Enter
    "verify then submit" gap (300–900 ms — sometimes ≥ DEBOUNCE, so the most
    valuable speculation — the full query right before Enter — can fire). This
    is the realistic scenario where speculation primes the cache BEFORE Enter.
    """
    inter = wpm_to_interkey_ms(wpm)
    events: list[dict] = []
    intervals: list[float] = []
    # word-boundary thinking pause: P scales with slowness; duration 500–2500 ms
    # (≥ DEBOUNCE_MS so a speculation fires there). Slow typists pause longer +
    # more often; fast typists rarely pause mid-query (but not never — floor).
    pause_prob = max(0.05, min(0.6, (90 - wpm) / 200.0))  # slow→0.275, fast→0.05
    t = 0.0
    for i, ch in enumerate(query):
        jit = inter * rng.uniform(0.6, 1.4)
        jit = max(15.0, jit)
        intervals.append(round(jit, 2))
        t += jit
        events.append({"kind": "keystroke", "i": i, "ch": ch, "t_ms": round(t, 2),
                       "typed_so_far": query[: i + 1]})
        if ch == " " and rng.random() < pause_prob:
            pause = rng.uniform(500.0, 2500.0)  # ≥ DEBOUNCE_MS → fires mid-query
            intervals.append(round(pause, 2))
            t += pause
            events.append({"kind": "pause", "t_ms": round(t, 2),
                           "pause_ms": round(pause, 2)})
    # pre-Enter "verify then submit" gap: the user finishes typing, glances at
    # the bar, then hits Enter. 300–900 ms — sometimes ≥ DEBOUNCE, so the full-
    # query speculation (literal mode's only hit opportunity, or predictor's
    # confirmation) can fire right before Enter. This is the high-value fire
    # the feature exists for; modelling a blind one-inter-key gap (always
    # < DEBOUNCE) would have hidden it.
    pre_enter_gap = rng.uniform(300.0, 900.0)
    intervals.append(round(pre_enter_gap, 2))
    enter_t = t + pre_enter_gap

    # spec_points: keystroke char-indices where the gap AFTER ≥ DEBOUNCE_MS AND
    # typed-so-far ≥ MIN_LEN. fire_t = keystroke_t + DEBOUNCE_MS (into the gap).
    spec_points: list[int] = []
    keystroke_indices = [i for i, e in enumerate(events) if e.get("kind") == "keystroke"]
    for ki, idx in enumerate(keystroke_indices):
        typed = query[: idx + 1]
        n = " ".join(typed.strip().lower().split())
        if len(n) < MIN_LEN:
            continue
        next_evt = events[ki + 1] if ki + 1 < len(events) else None
        if next_evt is None:
            gap = enter_t - events[ki]["t_ms"]
        else:
            gap = next_evt["t_ms"] - events[ki]["t_ms"]
        if gap >= DEBOUNCE_MS:
            spec_points.append(idx)
    spec_points = spec_points[:SPEC_CAP]
    # the wall-clock fire time for each spec_point (keystroke_t + DEBOUNCE_MS).
    spec_fire_t: dict[int, float] = {}
    ks_by_i = {e["i"]: e["t_ms"] for e in events if e.get("kind") == "keystroke"}
    for idx in spec_points:
        spec_fire_t[idx] = ks_by_i.get(idx, 0.0) + DEBOUNCE_MS
    return {
        "events": events, "intervals_ms": intervals, "enter_t_ms": round(enter_t, 2),
        "spec_points": spec_points, "spec_fire_t_ms": spec_fire_t,
        "profile_wpm": wpm,
    }


def _store_complete_monitor(base, stop, stores_before, rc_store_before):
    """Background thread (WI-19a): polls /health counters to record each
    speculation store's wall-complete time for the lead-time distribution. This
    is POST-TRIAL BOOKKEEPING ONLY — it NEVER gates Enter and no caller waits on
    it (the main playback presses Enter at enter_t regardless of what this
    poller sees). It survives only because the lead-time distribution (Enter −
    store-complete) needs the store-complete wall instant."""
    import threading
    spec_completes: list[float] = []  # wall (perf_counter ms) per spec store
    rc_completes: list[float] = []    # wall (perf_counter ms) per result_cache store
    last_spec = stores_before
    last_rc = rc_store_before
    while not stop.is_set():
        try:
            h = health(base)
            cur_spec = h.get("speculation", {}).get("stores", 0)
            cur_rc = h.get("result_cache", {}).get("store", 0)
            now = time.perf_counter() * 1000.0
            if cur_spec > last_spec:
                for _ in range(cur_spec - last_spec):
                    spec_completes.append(round(now, 2))
                last_spec = cur_spec
            if cur_rc > last_rc:
                for _ in range(cur_rc - last_rc):
                    rc_completes.append(round(now, 2))
                last_rc = cur_rc
        except Exception:
            pass
        time.sleep(0.02)  # 20 ms poll — finer than the ~0.2–3 s store latency
    return spec_completes, rc_completes


def simulate_and_speculate(base, query, wpm, rng, *, literal_mode=False,
                           speculation_on=True) -> dict:
    """Type `query` in REAL WALL-CLOCK TIME at the given WPM (jittered) with
    realistic inter-word thinking pauses, firing /api/speculate at every point
    the client debounce would (≥ DEBOUNCE_MS idle AND ≥ MIN_LEN typed), then
    submit Enter at enter_t REGARDLESS of speculative-store state, and measure
    Enter→response.

    WI-19a (HOST-NOTE-W8-3 fix): the schedule is computed deterministically by
    `_build_timeline`, then played back in wall-clock — each computed interval
    is SLEPT, each speculation fires at its wall-clock spec point, Enter fires
    at the wall-clock enter_t. `resident_by_enter` is the fact observed at the
    real Enter instant (the cache HIT counter advanced on Enter — the
    speculation primed the exact key, term 1), never a probe-deadline artifact.
    A background poller records each store's wall-complete latency for the
    lead-time distribution but does NOT gate Enter.

    Returns a per-trial timeline: keystroke times, speculations fired/dropped,
    each fire's store-complete wall latency (from the background poller) + the
    lead-time (Enter − store-complete), Enter time, Enter→response latency, and
    whether the query was resident-by-Enter.
    """
    import threading
    tl = _build_timeline(query, wpm, rng)
    events = tl["events"]
    spec_points = tl["spec_points"]
    spec_fire_t = tl["spec_fire_t_ms"]
    enter_t = tl["enter_t_ms"]
    intervals = tl["intervals_ms"]

    # Counter baselines before the trial (for delta attribution + the monitor).
    spec_h0 = health(base)
    stores_before = spec_h0.get("speculation", {}).get("stores", 0)
    rc_store_before = spec_h0.get("result_cache", {}).get("store", 0)

    # Start the background store-complete monitor (bookkeeping only — never
    # gates Enter). It records wall-complete times for the lead-time dist.
    stop_mon = threading.Event()
    mon_thread = threading.Thread(
        target=lambda: setattr(stop_mon, "result",
                              _store_complete_monitor(base, stop_mon, stores_before,
                                                      rc_store_before)),
        daemon=True)
    mon_thread.start()

    # A merged playback schedule: keystrokes (no-op), pauses (no-op), and spec
    # fires at their fire_t. We walk absolute t_ms in order, sleeping the real
    # interval to each action's t, then performing it. Enter is the final action.
    actions: list[dict] = []
    for e in events:
        if e["kind"] == "keystroke":
            actions.append({"t": e["t_ms"], "kind": "keystroke", "i": e["i"]})
        else:
            actions.append({"t": e["t_ms"], "kind": "pause"})
    for idx in spec_points:
        actions.append({"t": spec_fire_t[idx], "kind": "speculate", "i": idx})
    actions.append({"t": enter_t, "kind": "enter"})
    actions.sort(key=lambda a: a["t"])

    wall0 = time.perf_counter()
    fired_results: list[dict] = []
    enter_wall_t = None
    st = None
    enter_latency = None
    enter_was_hit = False
    invalid_reason = None
    for act in actions:
        target = wall0 + act["t"] / 1000.0
        sleep_for = target - time.perf_counter()
        if sleep_for > 0:
            time.sleep(sleep_for)
        wall_now = (time.perf_counter() - wall0) * 1000.0
        if act["kind"] == "speculate":
            typed = query[: act["i"] + 1]
            body = {"query": typed, "limit": DEFAULT_LIMIT}
            if literal_mode:
                body["force_literal"] = True  # WI-19b: novel-query leg, no restart
            st, resp, ms = http("POST", f"{base}/api/speculate", body=body, timeout=30.0)
            fired_results.append({
                "i": act["i"], "typed": typed,
                "schedule_t_ms": round(act["t"], 2),
                "wall_t_ms": round(wall_now, 2),
                "status": (resp or {}).get("status"), "mode": (resp or {}).get("mode"),
                "predicted": (resp or {}).get("predicted"),
                "roundtrip_ms": round(ms, 2),
            })
        elif act["kind"] == "enter":
            enter_wall_t = wall_now
            # Enter fires at enter_t REGARDLESS of store state (WI-19a core).
            # REQ-1b: the counter-delta window brackets exactly one api_search
            # on a single-threaded trial serve — acceptable here. Arm E
            # (concurrent typist) MUST NOT use this delta method (concurrent
            # hits contaminate it) — arm E measures latency only.
            rc_hit_before = health(base).get("result_cache", {}).get("hit", 0)
            st, _data, enter_ms = http("POST", f"{base}/api/search",
                                       body={"query": query, "limit": DEFAULT_LIMIT})
            enter_latency = round(enter_ms, 2)
            rc_hit_after = health(base).get("result_cache", {}).get("hit", 0)
            enter_was_hit = rc_hit_after > rc_hit_before

    # Stop the monitor + collect the store-complete wall latencies (post-trial
    # bookkeeping). This NEVER gated Enter.
    stop_mon.set()
    mon_thread.join(timeout=2.0)
    mon_spec, mon_rc = getattr(stop_mon, "result", ([], []))

    # Lead-time distribution: for each FIRED speculation, match its store-
    # complete wall latency (the Nth store after the trial's fires) and
    # compute lead_time = enter_wall − store_complete (positive ⇒ store beat
    # Enter ⇔ the user benefits). Single-slot drops make the Nth-fire↔Nth-store
    # matching approximate (a dropped fire stores nothing); unmatched ⇒ None.
    fired_count = sum(1 for f in fired_results)
    per_fire_lead: list[dict] = []
    for fi, f in enumerate(fired_results):
        store_wall = mon_spec[fi] if fi < len(mon_spec) else None
        lead = round(enter_wall_t - store_wall, 2) if (
            enter_wall_t is not None and store_wall is not None) else None
        per_fire_lead.append({
            "i": f["i"], "status": f["status"],
            "fire_wall_t_ms": f["wall_t_ms"],
            "store_complete_wall_t_ms": store_wall,
            "lead_time_enter_minus_store_ms": lead,  # +ve = beat Enter (user benefits)
        })

    stores_after = health(base).get("speculation", {}).get("stores", 0)
    rc_store_after = health(base).get("result_cache", {}).get("store", 0)
    spec_stores_this_trial = stores_after - stores_before
    rc_stores_this_trial = rc_store_after - rc_store_before

    # REQ-1b (HOST-NOTE-W9-1): resident_by_enter := the Enter request bumped the
    # cache HIT counter (the speculation primed the exact key, term 1 — observed
    # at the real Enter instant) AND the Enter returned 200. The latency<50ms OR
    # is REMOVED: a fast FAILURE (500, 429, empty short-circuit) in <50ms would
    # otherwise score as a hit — the W8-3 defect class via a different door.
    # A non-200 Enter invalidates the trial (contract term 7: contaminated
    # trials are excluded from hit-rate n + logged with the reason).
    latency_consistent_with_hit = (enter_latency is not None and enter_latency < 50.0)
    latency_hit_counter_miss = (not enter_was_hit and latency_consistent_with_hit
                                and st == 200)  # anomaly: fast + 200 + miss
    if st != 200:
        invalid_reason = f"enter_status_not_200 ({st})"
        resident = False
    else:
        resident = bool(enter_was_hit)

    return {
        "query": query, "profile_wpm": wpm,
        "intervals_ms": intervals, "enter_t_ms": round(enter_t, 2),
        "spec_points": spec_points,
        "speculation_fired": fired_results,
        "store_complete_monitor": per_fire_lead,
        # resident-by-Enter (REQ-1b): the Enter request bumped the cache HIT
        # counter AND Enter returned 200. A non-200 Enter invalidates the trial
        # (invalid_reason set; excluded from hit-rate n per term 7). Never OR'd
        # with latency — the <50ms fast-fail trap is removed.
        "resident_by_enter": resident,
        "valid_trial": invalid_reason is None,
        "invalid_reason": invalid_reason,
        # latency cross-check (REQ-1b): a hit is single-digit ms; a miss is
        # 0.2–3 s. DISAGREEMENTS (hit-counter says miss, latency<50, status 200)
        # are surfaced as anomalies in the cell summary, never promoted into the
        # headline hit-rate.
        "latency_consistent_with_hit": latency_consistent_with_hit,
        "latency_counter_disagreement": latency_hit_counter_miss,
        "enter_was_cache_hit": bool(enter_was_hit),
        "spec_stores_delta": spec_stores_this_trial,
        "rc_store_delta_enter": rc_stores_this_trial,
        "enter_status": st,
        "enter_response_ms": enter_latency,
        "trial_wall_ms": round((time.perf_counter() - wall0) * 1000.0, 2),
    }


# ── cells ───────────────────────────────────────────────────────────────────


def run_arm_A(base, n=20) -> dict:
    """Cold floor — cache OFF, n queries, Enter→response p50/p95.
    Run on a cache-OFF serve (SFU_RESULT_CACHE=0)."""
    bench = bench_queries()
    rng = random.Random(SEED)
    trials = []
    # interleave: pick n distinct queries, submit each once (cold).
    qs = rng.sample(bench, min(n, len(bench)))
    for q in qs:
        st, _, ms = http("POST", f"{base}/api/search",
                         body={"query": q, "limit": DEFAULT_LIMIT})
        trials.append({"query": q, "status": st, "enter_response_ms": round(ms, 2)})
    lats = [t["enter_response_ms"] for t in trials if t["status"] == 200]
    return {
        "cell": "A_cold_floor_cache_off", "n": len(trials),
        "p50_ms": pctl(lats, 50), "p95_ms": pctl(lats, 95),
        "mean_ms": mean(lats), "min_ms": round(min(lats), 2) if lats else None,
        "max_ms": round(max(lats), 2) if lats else None,
        "samples_ms": lats, "trials": trials,
        "serve_state": _serve_state(base),
    }


def run_arm_B(base, n=20) -> dict:
    """Pre-seed hit — cache ON + primer, 6 seeds, n repeat-visits, p50/p95."""
    seeds = seed_queries()
    rng = random.Random(SEED + 1)
    trials = []
    # Interleave the reps across seeds (never all-reps-of-one-then-next).
    for i in range(n):
        q = seeds[i % len(seeds)]
        st, _, ms = http("POST", f"{base}/api/search",
                         body={"query": q, "limit": DEFAULT_LIMIT})
        trials.append({"query": q, "rep": i, "status": st,
                       "enter_response_ms": round(ms, 2),
                       "cache_hit_expected": True})
    lats = [t["enter_response_ms"] for t in trials if t["status"] == 200]
    return {
        "cell": "B_preseed_hit_cache_on", "n": len(trials), "n_seeds": len(seeds),
        "p50_ms": pctl(lats, 50), "p95_ms": pctl(lats, 95),
        "mean_ms": mean(lats), "min_ms": round(min(lats), 2) if lats else None,
        "max_ms": round(max(lats), 2) if lats else None,
        "samples_ms": lats, "trials": trials,
        "serve_state": _serve_state(base),
    }


def run_arm_C(base, profiles, n_per_profile=20, literal_mode=False,
              speculation_on=True) -> dict:
    """Speculation — cache ON, speculation ON, distinct queries, n per profile.

    HOST-NOTE-W8-1 framing + HOST-NOTE-W9-3 freshness fix (2026-07-28):
      * PREDICTOR mode = the known-query (in-pool) scenario. Types a REAL bench
        query; the predictor matches the typed prefix → fires the FULL predicted
        query → lands it under the exact key a real Enter-submit produces (term
        1). The win being measured: does that speculation land resident before
        Enter at this typing speed? + a per-trial residency probe (term 7).
      * LITERAL mode = the novel-query scenario. Types a real bench query but
        Enter-submits a NONCE-SUFFIXED query → the Enter key is provably cache-
        cold by construction (the literal speculation stores under the typed-
        prefix key, which can only be the full-query key if it fires at/after
        the final keystroke — exactly the physics the host flagged as absent
        from the contaminated 100%-hit run). This is the genuine literal leg.

    The W9-3 contamination (C-literal reused C-predictor's exact 60 queries via
    the same SEED+2 rng.sample → every Enter hit a key already resident → a
    physically-impossible 100% hit-rate) is eliminated: literal Enter-submits a
    nonce query that no prior cell could have primed. Predictor + literal both
    draw from the full pool (the nonce is the freshness guarantee, so a disjoint
    partition would only risk an needless n-deviation).
    """
    bench = bench_queries()
    rng = random.Random(SEED + 2)
    # Distinct queries per trial within the serve lifetime (term 7): pull
    # enough to cover n_per_profile × n_profiles, none reused.
    needed = n_per_profile * len(profiles)
    available = [q for q in bench]
    qs = rng.sample(available, min(needed, len(available)))
    qi = 0
    by_profile: dict[str, dict] = {}
    mode_label = "literal" if literal_mode else "predictor"
    for pname, (wpm, label) in profiles.items():
        trials = []
        discarded = 0
        for _ in range(n_per_profile):
            if qi >= len(qs):
                break
            base_q = qs[qi]; qi += 1
            # LITERAL (novel-query): Enter-submits a nonce-suffixed query that
            # is provably cache-cold (no prior cell primed it). The typing
            # simulation samples a realistic academic prefix so the predictor's
            # prefix-match discipline is exercised; only the Enter key differs.
            enter_query = _fresh_query(base_q) if literal_mode else base_q
            # term-7 residency probe BEFORE the sim (records the pre-trial
            # counter snapshot; a post-trial delta confirms the speculation /
            # Enter actually primed / hit — a hit with no speculation fire +
            # no store = a pre-resident contaminated trial, discarded below).
            probe_before = _residency_probe(base, enter_query)
            res = simulate_and_speculate(
                base, enter_query, wpm, rng, literal_mode=literal_mode,
                speculation_on=speculation_on)
            res["enter_query"] = enter_query
            res["base_query"] = base_q
            res["residency_probe_before"] = probe_before
            # term-7 discipline: a predictor-mode trial whose Enter HIT without
            # a speculation firing in this trial AND without a fresh store is a
            # pre-resident contaminated trial (a prior arm primed it) — discard.
            # (Nonce queries make this impossible for literal mode by
            # construction; the check is a belt-and-braces guard for predictor.)
            fired_this = bool(res.get("speculation_fired"))
            stored_this = (res.get("spec_stores_delta", 0) > 0
                           or res.get("rc_store_delta_enter", 0) > 0)
            if (res.get("resident_by_enter") and not fired_this
                    and not stored_this and res.get("enter_status") == 200):
                res["contaminated"] = True
                res["invalid_reason"] = (res.get("invalid_reason")
                                         or "resident_with_no_fire_no_store")
                res["valid_trial"] = False
                discarded += 1
            trials.append(res)
        # REQ-1b: hit-rate denominator = VALID trials only (a non-200 Enter
        # invalidates the trial per contract term 7; an invalid trial is excluded
        # from n + logged). Latency is computed over the 200s. Disagreements
        # (hit-counter miss + latency<50 + 200 — a fast-fail-shaped sample) are
        # surfaced as anomaly_count, never promoted into the headline hit-rate.
        valid_trials = [t for t in trials if t.get("valid_trial", True)]
        invalid_trials = [t for t in trials if not t.get("valid_trial", True)]
        lats = [t["enter_response_ms"] for t in trials if t.get("enter_status") == 200]
        hits = [t for t in valid_trials if t.get("resident_by_enter")]
        spec_stores = [t["spec_stores_delta"] for t in trials]
        anomalies = [t for t in valid_trials if t.get("latency_counter_disagreement")]
        by_profile[pname] = {
            "profile": pname, "wpm": wpm, "mode": mode_label,
            "n": len(trials), "n_valid": len(valid_trials),
            "n_invalid": len(invalid_trials), "n_discarded_contaminated": discarded,
            "hit_rate": round(len(hits) / max(len(valid_trials), 1), 4),
            "n_hits": len(hits),
            "anomaly_count": len(anomalies),  # REQ-1b: surfaced, not in headline
            "enter_p50_ms": pctl(lats, 50), "enter_p95_ms": pctl(lats, 95),
            "enter_mean_ms": mean(lats),
            "spec_execs_per_trial": round(sum(spec_stores) / max(len(trials), 1), 3),
            "spec_execs_total": sum(spec_stores),
            "samples_ms": lats,
            "trials": trials,
        }
    return {
        "cell": "C_speculation", "mode": mode_label,
        "speculation_on": speculation_on,
        "per_profile": by_profile,
        "serve_state": _serve_state(base),
    }


def run_arm_D(base, n=20) -> dict:
    """Cache-ON control miss — cache ON, speculation OFF, n trials. Must match
    arm A within noise (isolates cache/spec overhead on the miss path).

    HOST-NOTE-W9-3 freshness fix: D previously drew from the same bench pool as
    C-predictor (different seed) → 13/20 queries were already primed by C's
    speculation stores → bimodal hits-among-misses (4-6 ms "misses" that were
    really cache HITS) → bar d (within 10% of arm A) failed as an artifact.
    Now every D trial Enter-submits a NONCE-SUFFIXED novel query: provably
    cache-cold by construction (no prior cell could have primed the nonce key),
    so a 4-6 ms sample is impossible — every D sample is a genuine warm-retrieval
    miss, directly comparable to arm A. The result_cache counter delta confirms
    each was a miss (recorded per trial)."""
    bench = bench_queries()
    rng = random.Random(SEED + 3)
    qs = rng.sample(bench, min(n, len(bench)))
    trials = []
    for q in qs:
        enter_q = _fresh_query(q)
        probe_before = _residency_probe(base, enter_q)
        st, _, ms = http("POST", f"{base}/api/search",
                         body={"query": enter_q, "limit": DEFAULT_LIMIT})
        probe_after = _residency_probe(base, enter_q)
        was_store = probe_after.get("rc_store", 0) > probe_before.get("rc_store", 0)
        trials.append({"query": enter_q, "base_query": q, "status": st,
                       "enter_response_ms": round(ms, 2),
                       "was_cache_store": was_store,  # True ⇒ genuine miss→store
                       "residency_probe_before": probe_before})
    lats = [t["enter_response_ms"] for t in trials if t["status"] == 200]
    n_stored = sum(1 for t in trials if t.get("was_cache_store"))
    return {
        "cell": "D_cache_on_miss_ctrl_spec_off", "n": len(trials),
        "n_genuine_miss_store": n_stored,  # W9-3: every D trial should store
        "p50_ms": pctl(lats, 50), "p95_ms": pctl(lats, 95),
        "mean_ms": mean(lats),
        "samples_ms": lats, "trials": trials,
        "serve_state": _serve_state(base),
    }


def run_arm_E(base, n=10) -> dict:
    """Interference — while a continuous typist speculates, fire n real cold
    searches; compare p50 vs arm A (does speculative GPU load regress a real
    search?). The 'continuous typist' is a background thread firing speculations
    on a loop while the main thread does the n cold searches.

    REQ-1b (HOST-NOTE-W9-1): arm E measures LATENCY ONLY — it does NOT use the
    result_cache hit-counter delta (the concurrent typist's speculation stores
    contaminate the delta, so a counter-delta hit-rate would be meaningless
    here). The cell spec is latency comparison vs arm A, which is intact."""
    import threading
    bench = bench_queries()
    rng = random.Random(SEED + 4)
    stop = threading.Event()

    def _typist():
        i = 0
        while not stop.is_set() and i < len(bench):
            q = bench[i % len(bench)]
            # type a partial prefix that would predict (use a long prefix)
            partial = q[: max(MIN_LEN, len(q) // 2)]
            try:
                http("POST", f"{base}/api/speculate",
                     body={"query": partial, "limit": DEFAULT_LIMIT}, timeout=10.0)
            except Exception:
                pass
            i += 1
            time.sleep(0.1)

    th = threading.Thread(target=_typist, daemon=True)
    th.start()
    # distinct non-seeded cold queries (different from the typist's, via nonce).
    # F6 reproducibility: the nonce RNG is seeded (not secrets.token_hex) so the
    # transcript is reproducible per run (no time-derived entropy in a result).
    trials = []
    for _ in range(n):
        # a fresh nonce query → genuine cold miss under speculative load
        q = f"interference probe {NONCE_RNG.getrandbits(24):06x} machine learning"
        st, _, ms = http("POST", f"{base}/api/search",
                         body={"query": q, "limit": DEFAULT_LIMIT})
        trials.append({"query": q, "status": st, "enter_response_ms": round(ms, 2)})
    stop.set(); th.join(timeout=5.0)
    lats = [t["enter_response_ms"] for t in trials if t["status"] == 200]
    return {
        "cell": "E_interference_under_speculation", "n": len(trials),
        "p50_ms": pctl(lats, 50), "p95_ms": pctl(lats, 95),
        "mean_ms": mean(lats),
        "samples_ms": lats, "trials": trials,
        # REQ-1b: latency-only measurement; no hit-counter delta (concurrent
        # typist's speculation stores would contaminate it — noted explicitly).
        "measurement": "latency_only_no_counter_delta",
        "serve_state": _serve_state(base),
    }


def run_arm_F(base, profiles, n_per_profile=10) -> dict:
    """Waste — speculative backend executions per completed search, per profile
    + adversarial set.

    HOST-NOTE-W9-3 freshness fix: F previously drew from the same bench pool as
    C (SEED+5 vs SEED+2) → 7/10 queries already primed by C's speculation stores
    → every `_speculate_search` hit the cache (no fresh store) → spec_stores_delta
    = 0.0 across all profiles, contradicting C's own 0.2–1.9 execs/trial under
    the identical typing sim. ONE root cause: contamination. Now each F trial
    types a NONCE-SUFFIXED query and runs in LITERAL mode → the speculation
    fires+stores under a provably-novel typed-prefix key (a genuine fresh backend
    execution every fire), so spec_stores_delta reflects the real GPU cost of
    the feature, not a free-hit artifact. The `fired` counter delta is also
    recorded (a fire that doesn't store = a cache hit = no GPU waste, but still
    a slot use — surfaced for transparency, NOT the bar-e metric)."""
    rng = random.Random(SEED + 5)
    bench = bench_queries()
    by_profile = {}
    for pname, (wpm, label) in profiles.items():
        n = n_per_profile
        qs = rng.sample(bench, min(n, len(bench)))
        stores = []
        fires = []
        for q in qs:
            enter_q = _fresh_query(q)
            spec_h0 = health(base).get("speculation", {})
            fired_before = spec_h0.get("fired", 0)
            stores_before = spec_h0.get("stores", 0)
            res = simulate_and_speculate(base, enter_q, wpm, rng,
                                         literal_mode=True, speculation_on=True)
            spec_h1 = health(base).get("speculation", {})
            # spec_stores_delta (from the trial's own counter bracket) is the
            # bar-e metric (fresh backend executions = real GPU cost). `fired`
            # delta is slot-usage transparency.
            stores.append(res["spec_stores_delta"])
            fires.append(spec_h1.get("fired", 0) - fired_before)
        by_profile[pname] = {
            "profile": pname, "wpm": wpm, "n": len(stores),
            "spec_execs_per_trial": round(sum(stores) / max(len(stores), 1), 3),
            "spec_execs_total": sum(stores), "samples": stores,
            "fired_per_trial": round(sum(fires) / max(len(fires), 1), 3),
            "fired_total": sum(fires),  # transparency: slot uses (hits store nothing)
        }
    # adversarial set: mid-typing edits (backspace), abandoned-then-changed,
    # sub-min-length shorts. A well-behaved client cancels pending spec on new
    # input → few/no spec execs. We simulate the CLIENT behavior (cancel on
    # edit) so this measures the steady-state waste under realistic typing.
    adversarial = [
        {"type": "mid_typing_edit", "partial": _fresh_query("machine learning for drug discovery overview edited")},
        {"type": "abandoned_then_changed", "partial": _fresh_query("climate change abandoned")},
        {"type": "sub_min_length_short", "partial": "ml"},  # < MIN_LEN → guard suppresses (0 stores is CORRECT)
        {"type": "backspace_correction", "partial": _fresh_query("crispr gene editing corrected")},
    ]
    adv_stores = []
    for a in adversarial:
        # simulate: the client cancels on every edit, so at most ONE spec fires
        # (the final settle). Measure the server-side stores from one final fire.
        stores_before = health(base).get("speculation", {}).get("stores", 0)
        http("POST", f"{base}/api/speculate",
             body={"query": a["partial"], "limit": DEFAULT_LIMIT}, timeout=30.0)
        time.sleep(1.0)  # let the speculation settle/store
        stores_after = health(base).get("speculation", {}).get("stores", 0)
        adv_stores.append({"type": a["type"], "spec_execs": stores_after - stores_before})
    return {
        "cell": "F_waste", "per_profile": by_profile,
        "adversarial": adv_stores,
        "serve_state": _serve_state(base),
    }


def run_arm_G(base, off_baseline) -> dict:
    """Parity — ≥6 speculation-primed responses byte-identical to fresh cache-OFF
    runs of the same normalized query (the pre-registered bar c, the SAME bar
    wave-7 WI-17c-fix made genuine: OFF-vs-ON, not round-trip identity which
    PASSes trivially).

    The cache-OFF baselines are captured during the cache_off leg (arm A — see
    `capture_g_off_baseline`) into `_speculation_g_cacheoff_baseline.json`. This
    cache_on leg: for each of 6 bench queries, (1) fire a speculation on the
    predictor-matched prefix, (2) wait for the store (a real-world Enter would
    land after; here we wait so the primed Enter is the thing being compared, not
    the speculation's own in-flight timing), (3) Enter-submit the PREDICTED
    query → should be a cache hit primed by the speculation (term 1 — same key
    as a real submit), (4) compare to the captured cache-OFF baseline of the
    same normalized predicted query byte-for-byte (parsed-JSON equality of the
    result set + meta)."""
    trials = []
    if off_baseline is None:
        return {
            "cell": "G_parity", "n": 0, "parity_pass": 0,
            "parity_all_pass": False,
            "trials": [], "off_baseline_file": str(G_OFF_BASELINE),
            "note": "no cache-OFF baseline captured (run the cache_off leg first; "
                    "bar c UNMEASURED without it)",
            "serve_state": _serve_state(base),
        }
    for q, predicted, off_resp, off_ms in off_baseline:
        # 1. Fire the speculation on the predictor-matched prefix (literal-close:
        #    use the prefix the predictor would resolve to for this query).
        partial = predicted[: max(MIN_LEN, len(predicted) // 2)]
        http("POST", f"{base}/api/speculate",
             body={"query": partial, "limit": DEFAULT_LIMIT}, timeout=30.0)
        # 2. Wait for the speculative store (this is the only cell that waits —
        #    deliberately, because it's measuring byte-parity of a PRIMED Enter,
        #    not arm-C's Enter-regardless timing).
        deadline = time.monotonic() + 5.0
        stores0 = health(base).get("speculation", {}).get("stores", 0)
        while time.monotonic() < deadline:
            if health(base).get("speculation", {}).get("stores", 0) > stores0:
                break
            time.sleep(0.05)
        # 3. Enter-submit the PREDICTED query → cache hit if primed (term 1).
        st, speculated_run, spec_ms = http("POST", f"{base}/api/search",
            body={"query": predicted, "limit": DEFAULT_LIMIT})
        # 4. Compare to the fresh cache-OFF baseline byte-for-byte (parsed-JSON).
        parity = (speculated_run == off_resp)
        trials.append({
            "query": q, "partial": partial, "predicted": predicted,
            "spec_enter_ms": round(spec_ms, 2),
            "spec_enter_cache_hit": spec_ms < 50.0,  # fast ⇒ cache hit (primed)
            "off_baseline_ms": round(off_ms, 2),
            "parity_off_vs_on": parity,
        })
    n_pass = sum(1 for t in trials if t["parity_off_vs_on"])
    return {
        "cell": "G_parity", "n": len(trials), "parity_pass": n_pass,
        "parity_all_pass": n_pass == len(trials),
        "trials": trials, "off_baseline_file": str(G_OFF_BASELINE),
        "serve_state": _serve_state(base),
    }


def capture_g_off_baseline(base, n=6) -> list:
    """Capture n fresh cache-OFF Enter baselines FOR arm G. Run on the cache-OFF
    serve (the cache_off leg, alongside arm A). For each of n bench queries:
    resolve the predictor's predicted query for the query's prefix (same
    prediction the cache_on leg's speculation will fire), Enter-submit it (a
    fresh miss on a cache-OFF serve = the uncached truth), record the parsed
    response + latency. The cache_on leg compares its speculation-primed Enter
    to these. Caches to `_speculation_g_cacheoff_baseline.json` for F6."""
    bench = bench_queries()
    rng = random.Random(SEED + 6)
    qs = rng.sample(bench, min(n, len(bench)))
    baseline = []
    for q in qs:
        # Resolve the prediction: speculate the prefix in predictor mode
        # (force_literal False) — but on a cache-OFF serve the speculation is
        # guard-suppressed (cache-off guard), so we read the predicted query via
        # the schedule() predictor directly over HTTP isn't available; instead we
        # use the same partial the cache_on leg will use and predict client-side.
        partial = q[: max(MIN_LEN, len(q) // 2)]
        # The predicted query = the predictor's match for this prefix. On the
        # cache-OFF serve /api/speculate returns suppressed; so we re-derive the
        # prediction here using a direct predictor call (the predictor is a pure
        # function of the pool — same on both legs).
        import importlib
        sys.path.insert(0, str(REPO / "src"))
        from lib import speculation as _spec  # noqa: E402
        _spec.reset_pool_for_test()
        pred = _spec.predict(partial, force_literal=False)
        predicted = pred.query if pred.mode == "predicted" else q
        st, off_resp, off_ms = http("POST", f"{base}/api/search",
            body={"query": predicted, "limit": DEFAULT_LIMIT})
        baseline.append([q, predicted, off_resp, off_ms])
    G_OFF_BASELINE.parent.mkdir(parents=True, exist_ok=True)
    G_OFF_BASELINE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False))
    print(f"  G cache-OFF baseline captured ({len(baseline)} queries) → {G_OFF_BASELINE}")
    return baseline




def _serve_state(base):
    h = health(base)
    return {
        "warmup": h.get("warmup"), "warm": h.get("warm"),
        "cache_preseed": h.get("cache_preseed"),
        "result_cache": h.get("result_cache"),
        "speculation": h.get("speculation"),
    }


# ── orchestration ────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--arm-set", default="cache_on",
                    choices=["cache_off", "cache_on"],
                    help="cache_off → run arm A (cache OFF serve). "
                         "cache_on → run B/C/D/E/F/G (cache ON serve).")
    ap.add_argument("--n", type=int, default=20, help="trials per arm/cell")
    ap.add_argument("--n-c", type=int, default=20, help="trials per profile, arm C")
    ap.add_argument("--n-e", type=int, default=10, help="trials, arm E")
    ap.add_argument("--n-f", type=int, default=10, help="trials per profile, arm F")
    ap.add_argument("--profiles", default="slow,medium,fast",
                    help="comma list of typing profiles to run for arm C")
    ap.add_argument("--merge", action="store_true",
                    help="re-read the existing OUT JSON + append the cells run "
                         "this invocation (so the cache_off + cache_on runs land "
                         "in ONE results file).")
    ap.add_argument("--smoke", action="store_true",
                    help="WI-19a bar: one trial per profile, smoke-verify the "
                         "real-time playback (a medium-profile trial must take "
                         "roughly its typing duration, not milliseconds).")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"
    print(f"Waiting for serve {base} to be warm ...")
    h = wait_warm(base)
    if not h:
        print("! serve did not reach warm state", file=sys.stderr); sys.exit(2)
    print(f"Warm: {h.get('warmup')} cache_preseed={h.get('cache_preseed')} "
          f"spec={h.get('speculation',{}).get('enabled')}")

    n = 1 if args.smoke else args.n
    n_c = 1 if args.smoke else args.n_c
    profs = {p: PROFILES[p] for p in args.profiles.split(",") if p in PROFILES}
    out = {
        "date": "2026-07-28", "limit": DEFAULT_LIMIT, "seed": SEED,
        "serve": base, "debounce_ms": DEBOUNCE_MS, "min_len": MIN_LEN,
        "spec_cap": SPEC_CAP,
        "protocol": "WI-19a real-time (HOST-NOTE-W8-3 fix option a): timeline "
                    "computed deterministically by _build_timeline, played back in "
                    "wall-clock; each speculation fired at its spec point, Enter "
                    "at enter_t REGARDLESS of store state.",
        "profiles": {p: w for p, (w, _) in profs.items()},
    }
    if args.smoke:
        out["smoke"] = True
    if args.merge and OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
            out.update({k: v for k, v in prev.items() if k not in out})
        except Exception:
            pass

    if args.arm_set == "cache_off":
        # arm A only (the cold floor must run on a cache-OFF serve) + capture
        # the arm-G cache-OFF baseline (same serve, same leg — no second cold leg).
        rc = health(base).get("result_cache", {})
        if rc.get("enabled"):
            print(f"! WARN: arm A targets a cache-OFF serve (SFU_RESULT_CACHE=0), "
                  f"but the serve has cache ENABLED. The cold floor will still "
                  f"measure (these are genuine fresh misses), but arm D is the "
                  f"proper cache-ON control. Recording serve state honestly.")
        out["A_cold_floor"] = run_arm_A(base, n=n)
        if not args.smoke:
            capture_g_off_baseline(base, n=6)
    else:
        # cache ON cells: B, C (predictor + literal), D, E, F, G.
        # W9-3 freshness: the literal leg Enter-submits NONCE-suffixed queries
        # (run_arm_C), D uses nonces, F uses nonces — so no Enter key the miss/
        # novel cells submit can have been primed by C-predictor's speculation
        # stores. Predictor + literal BOTH draw from the full pool (the nonce is
        # the freshness guarantee, not the partition; an n-deviation from a
        # too-short disjoint slice would be needless — see run_arm_C docstring).
        out["B_preseed_hit"] = run_arm_B(base, n=n)
        out["C_speculation_predictor"] = run_arm_C(
            base, profs, n_per_profile=n_c, literal_mode=False, speculation_on=True)
        out["C_speculation_literal"] = run_arm_C(
            base, profs, n_per_profile=n_c, literal_mode=True, speculation_on=True)
        out["D_cache_on_miss"] = run_arm_D(base, n=n)
        out["E_interference"] = run_arm_E(base, n=max(3, args.n_e) if args.smoke else args.n_e)
        out["F_waste"] = run_arm_F(base, profs, n_per_profile=(3 if args.smoke else args.n_f))
        off_baseline = None
        if G_OFF_BASELINE.exists() and not args.smoke:
            try:
                off_baseline = json.loads(G_OFF_BASELINE.read_text())
            except Exception:
                off_baseline = None
        out["G_parity"] = run_arm_G(base, off_baseline)

    # ── bars (F6: recomputed from the raw samples in `out`) ─────────────────
    bars = {}
    if "B_preseed_hit" in out:
        bars["a_arm_B_hit_p50_le_10ms"] = (out["B_preseed_hit"]["p50_ms"] is not None
                                           and out["B_preseed_hit"]["p50_ms"] <= 10.0)
    if "C_speculation_predictor" in out:
        med = out["C_speculation_predictor"]["per_profile"].get("medium", {})
        b_p50 = out.get("B_preseed_hit", {}).get("p50_ms")
        hit_rate = med.get("hit_rate", 0)
        med_p50 = med.get("enter_p50_ms")
        bars["b_arm_C_medium_predictor_hitrate_ge_80pct"] = (hit_rate >= 0.80)
        bars["b_arm_C_medium_hit_latency_le_2x_armB"] = (
            b_p50 is not None and med_p50 is not None and med_p50 <= 2.0 * b_p50)
    if "C_speculation_literal" in out:
        # W9-3 freshness cross-check (recorded, NOT pre-registered): a literal
        # speculation can only prime the Enter key if it fires at/after the final
        # keystroke AND completes before Enter — so a 100% hit-rate across ALL
        # profiles (the contaminated signature) is physically implausible. If this
        # is True post-fix, the nonce freshness is broken; investigate.
        lit = out["C_speculation_literal"]["per_profile"]
        all_100 = all(lit.get(p, {}).get("hit_rate", 0) >= 0.999
                      for p in ("slow", "medium", "fast") if p in lit)
        bars["c_literal_implausible_100pct_all_profiles_w9_3_check"] = all_100
    if "G_parity" in out:
        bars["c_parity_6_of_6_off_vs_on"] = out["G_parity"].get("parity_all_pass", False)
    if "A_cold_floor" in out and "D_cache_on_miss" in out:
        a = out["A_cold_floor"].get("p50_ms"); d = out["D_cache_on_miss"].get("p50_ms")
        bars["d_armD_within_10pct_armA"] = (a is not None and d is not None
            and d <= a * 1.10 and d >= a * 0.90)
        # W9-3 freshness cross-check (recorded, NOT a pre-registered bar): every
        # D trial must be a genuine miss→store (nonce keys → no pre-primed hits).
        # If n_genuine_miss_store < n, D is still contaminated; surface it.
        dn = out["D_cache_on_miss"].get("n", 0)
        ds = out["D_cache_on_miss"].get("n_genuine_miss_store", 0)
        bars["d_armD_all_trials_genuine_miss_w9_3_check"] = (dn > 0 and ds == dn)
    elif "A_cold_floor" in out:
        bars["d_armD_within_10pct_armA"] = None  # arm D runs on cache_on leg
    if "A_cold_floor" in out and "E_interference" in out:
        a = out["A_cold_floor"].get("p50_ms"); e = out["E_interference"].get("p50_ms")
        bars["d_armE_within_15pct_armA"] = (a is not None and e is not None
            and e <= a * 1.15)
    elif "E_interference" in out:
        bars["d_armE_within_15pct_armA"] = None
    if "F_waste" in out:
        med = out["F_waste"]["per_profile"].get("medium", {})
        bars["e_waste_le_3_per_search_medium"] = (
            med.get("spec_execs_per_trial", 999) <= 3.0)
    out["bars"] = bars

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nResults → {OUT}")
    print(f"Bars: {json.dumps(bars, indent=2)}")
    if args.smoke:
        # WI-19a bar: smoke-trial wall-clock plausibility — a medium-profile
        # trial must take roughly its typing duration (enter_t_ms), not ms.
        print("\n── WI-19a smoke: trial wall vs typing duration ──")
        for mode_key in ("C_speculation_predictor", "C_speculation_literal"):
            if mode_key not in out:
                continue
            for pname, prof in out[mode_key].get("per_profile", {}).items():
                for t in prof.get("trials", []):
                    print(f"  {mode_key} {pname}: enter_t={t.get('enter_t_ms')}ms "
                          f"trial_wall={t.get('trial_wall_ms')}ms "
                          f"ratio={round((t.get('trial_wall_ms') or 0) / max(t.get('enter_t_ms') or 1, 1), 2)}")
    print(f"Final serve state: {json.dumps(_serve_state(base), indent=2)}")


if __name__ == "__main__":
    main()
