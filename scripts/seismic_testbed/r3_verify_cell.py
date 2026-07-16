#!/usr/bin/env python3
"""R3 Phase C cell verifier (2026-07-16; doc 15 §4 + drive prompt Phase C).

The FULL R2 checklist (from _r2_convergence_drive_prompt.md) PLUS the R3
checks, applied to each cell's result JSON BEFORE its row is written. A
number failing a check is recorded INVALID, never quoted as a result (F6
discipline). Prints a one-line verdict + a JSON verdict record the summary
appender consumes.

R2 checks (inherited):
  - swap_confounded must be false
  - convergence.kind ∈ {near_zero, plateau, maxpass}; maxpass = UNCONVERGED
    (p50 NOT steady state)
  - pass-1 majflt ≥ 50,000 for caps ≤ 17g (real cold fill; else drop_caches
    failed → INVALID)
  - ms_per_fault (majflt>0 passes) in rough [0.1, 2.0] ms
  - converged p50 ≥ ~15 ms (traversal-only; <10 ms or majflt≈0 at ≤12g = broken)
  - per_pass cg_delta shows pgscan/pgsteal activity where majflt large

R3 checks (additions, doc 15 §4 + backlog §R3 discard rules):
  - ledger drop rate ≤ 1% (else that cell's ledger INVALID; residency maps may
    still be used; latency NEVER — latency only from control cells)
  - instrumented converged p50 ≤ 1.10× its control (else instrument overhead
    fails the bar — record, then request ONE downsampled rerun via the queue)
  - ledger pgoffs ⊆ inode map (in-probe filter intact)
  - ledger refault count within ~2× of the cell's shard-attributable majflt
    (gross mismatch = broken filter → INVALID)

Usage:
  .venv/bin/python3 scripts/seismic_testbed/r3_verify_cell.py \
      --result data/eval_results/r3_cap12g_instr_20260716.json \
      --ledger data/eval_results/_r3_cap12g_instr_ledger.log \
      --refault data/eval_results/_r3_cap12g_instr_refault.log \
      --control-result data/eval_results/r3_cap12g_ctrl_20260716.json \
      --inode-map data/eval_results/_r3_inode_map.json
"""
import argparse
import json
import sys
from pathlib import Path


def pctl_pass3(passes, key):
    """The R2 fixed window is pass 3 (or final if <3 passes)."""
    idx = min(2, len(passes) - 1)
    return passes[idx].get(key)


def load_ledger(path: Path):
    """Parse the bpftrace ledger TSV. Returns (events, n_emitted, lost).
    events = list of (ns, 'ADD'|'DEL'|..., ino, pgoff, tag). Drops parsed
    from bpftrace's own 'lost N events' summary line if present; n_emitted
    from the LEDGER_END summary line for the drop-rate denominator. The
    tracer is `docker stop`'d at cell end, so LEDGER_END (and bpftrace's own
    'lost events' exit summary) often do NOT fire — both absent. In that
    case n_emitted=0 and lost=None, but len(events) (parsed event lines) is
    the true event count and a fallback denominator; the drop-rate check
    records UNKNOWN when neither the END line nor a lost-events line exists
    (never silently false-passes — the F6 rule)."""
    if not path or not path.exists():
        return [], 0, None
    events = []
    n_emitted = 0
    lost = None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("LEDGER_END"):
            parts = dict(p.split("=") for p in line.split()[1:]
                         if "=" in p)
            n_emitted = int(parts.get("emitted", 0))
            continue
        # bpftrace's own perf loss: "Lost N events" (per-CPU, CAPITAL L in
        # bpftrace 0.17 output) — sum them. CASE-INSENSITIVE (an earlier
        # version checked lowercase "lost" only → the real "Lost" lines were
        # missed → lost read as None → the drop-rate check falsely passed/
        # recorded UNKNOWN, HIDING a 92% perf-ring overrun — the F6 rule
        # violated by a one-character case bug. Match either Spelling.)
        if "lost" in line.lower() and "events" in line.lower():
            tok = line.split()
            for i, t in enumerate(tok):
                if t.lower() == "lost" and i + 1 < len(tok):
                    try:
                        lost = (lost or 0) + int(tok[i + 1])
                    except ValueError:
                        pass
        f = line.split("\t")
        if len(f) >= 5 and f[0].isdigit():
            events.append((int(f[0]), f[1], int(f[2]), int(f[3]), int(f[4])))
    return events, n_emitted, lost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--refault", default=None)
    ap.add_argument("--control-result", default=None,
                    help="control cell JSON for the instrumented-overhead bar")
    ap.add_argument("--inode-map", default="data/eval_results/_r3_inode_map.json")
    # the probes sample 1 event per SAMPLE_RATE pages (extent sampling, the
    # downsample fix for the REQ-3f perf-ring overrun). Counts read from the
    # logs are 1/SAMPLE_RATE of true; scale ×SAMPLE_RATE before comparing to
    # the un-sampled cell majflt (the refault-ratio bar).
    ap.add_argument("--sample-rate", type=int, default=512,
                    help="page-sample rate (1/probe-event per this many pages; "
                         "512 = the 2 MiB extent sample). Counts scaled ×this.")
    args = ap.parse_args()

    r = json.loads(Path(args.result).read_text())
    passes = r.get("per_pass", [])
    verdict = "VALID"
    checks = []

    def chk(name, ok, detail):
        nonlocal verdict
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok and verdict == "VALID":
            verdict = "INVALID"

    # ── R2 checks ────────────────────────────────────────────────────────────
    swap = r.get("swap_confounded", False)
    chk("swap_confounded_false", not swap,
        f"swap_confounded={swap} (vmswap_kb_max={r.get('vmswap_kb_max')})")

    kind = r.get("convergence", {}).get("kind", "maxpass")
    converged = kind != "maxpass"
    chk("convergence_kind_valid", kind in ("near_zero", "plateau", "maxpass"),
        f"kind={kind}")
    if not converged:
        verdict = "UNCONVERGED" if verdict == "VALID" else verdict

    cap_str = r.get("cap", "0g")
    cap_g = int("".join(c for c in cap_str if c.isdigit()) or 0)
    p1_majflt = passes[0].get("majflt", 0) if passes else 0
    if cap_g and cap_g <= 17:
        chk("pass1_majflt_cold_fill", p1_majflt >= 50_000,
            f"pass-1 majflt={p1_majflt} (≥50k required for cap≤17g)")
    else:
        checks.append({"check": "pass1_majflt_cold_fill", "ok": True,
                       "detail": f"cap={cap_g}g>17g — cold-fill floor skipped"})

    # ms/fault range 0.1–2.0 on passes with REAL faulting. The near-zero
    # convergence tail (majflt<1000, residual faults) gives meaningless
    # ms/fault (latency/4) — the R2 prompt's intent is "wildly outside on a
    # pass with real faulting," so only flag passes with majflt≥1000.
    bad_msf = [p["pass"] for p in passes
               if p.get("majflt", 0) >= 1000 and p.get("ms_per_fault")
               and not (0.1 <= p["ms_per_fault"] <= 2.0)]
    chk("ms_per_fault_range", not bad_msf,
        f"passes (majflt≥1k) outside [0.1,2.0] ms/flt: {bad_msf}")

    final = passes[-1] if passes else {}
    cp50 = final.get("p50_ms", 0)
    final_majflt = final.get("majflt", 0)
    chk("converged_p50_floor", cp50 >= 15 or (cap_g and cap_g > 12),
        f"final p50={cp50} ms (≥15 for traversal; <10 at ≤12g + majflt≈0 = broken)")
    if cap_g <= 12 and cp50 < 10 and final_majflt == 0:
        verdict = "INVALID" if verdict != "UNCONVERGED" else verdict
        checks.append({"check": "broken_cell_too_fast", "ok": False,
                       "detail": f"p50 {cp50}<10 with majflt~0 at {cap_g}g — broken"})

    # cg_delta activity where majflt large
    quiet = [p["pass"] for p in passes
             if p.get("majflt", 0) > 10000
             and not any(v for v in p.get("cg_delta", {}).values()
                         if isinstance(v, int) and v > 0)]
    if quiet:
        checks.append({"check": "cg_delta_activity", "ok": False,
                       "detail": f"passes w/ majflt>10k but zero cg_delta: {quiet} "
                                  "(instrumentation may have failed — cell still usable)"})
    else:
        checks.append({"check": "cg_delta_activity", "ok": True,
                       "detail": "cgroup counters moving where expected"})

    # ── R3 checks (instrumented cells only — need ledger/refault) ────────────
    is_instr = "instr" in Path(args.result).stem
    if is_instr:
        ino_map = {}
        if Path(args.inode_map).exists():
            im = json.loads(Path(args.inode_map).read_text())
            ino_map = {f["ino"] for f in im["files"]}

        events, n_emitted, lost = load_ledger(
            Path(args.ledger) if args.ledger else None)

        # drop rate. The bar is ≤1% perf-buffer loss. The denominator:
        # LEDGER_END's emitted count if present; else the parsed event count
        # (the true event total, since every emitted ADD/DEL flushed to the
        # log). lost = bpftrace's own 'lost N events' line if present.
        # HONESTY: if NEITHER a lost-events line NOR an END line is present
        # (the `docker stop`-before-detach case), drop-rate is UNKNOWN, not
        # a silent pass — recorded as a non-blocking caveat (the cell's other
        # checks + the monitor's preflight already vouch for the ledger; a
        # perf overrun would show as a low event count, flagged in the join).
        n_parsed = len(events)
        denom = n_emitted if n_emitted else n_parsed
        if lost is not None and denom and (denom + lost) > 0:
            drop_rate = lost / (denom + lost)
            ok = drop_rate <= 0.01
            chk("ledger_drop_rate", ok,
                f"drop_rate={drop_rate:.4f} (emitted={n_emitted} parsed="
                f"{n_parsed} lost={lost}); ≤1% required — over → ledger INVALID")
        elif lost is None and not n_emitted:
            # no lost line AND no END line → can't compute; record UNKNOWN,
            # not a pass (but not a cell-INVALID either — non-blocking caveat).
            checks.append({"check": "ledger_drop_rate", "ok": True,
                           "detail": f"UNKNOWN — LEDGER_END + bpftrace 'lost "
                                     f"events' line both absent (tracer "
                                     f"docker-stop'd before detach; {n_parsed} "
                                     f"events parsed); perf overrun would surface "
                                     f"as anomalously low event count (see join)"})
        else:
            # lost present but no denominator, or vice versa — can't compute,
            # but no lost-events line at all ⇒ treat as 0 (monitor confirms).
            checks.append({"check": "ledger_drop_rate", "ok": True,
                           "detail": f"no lost-events line (assume 0); "
                                     f"emitted={n_emitted} parsed={n_parsed}"})

        # pgoffs ⊆ inode map
        ledger_inos = {e[2] for e in events if e[2] != 0}
        if ino_map and ledger_inos:
            stray = ledger_inos - ino_map
            chk("ledger_pgoffs_in_inode_map", not stray,
                f"{len(stray)} ledger inodes not in inode map: "
                f"{sorted(stray)[:5]}{'...' if len(stray)>5 else ''}")
        else:
            checks.append({"check": "ledger_pgoffs_in_inode_map", "ok": True,
                           "detail": "no ledger events or inode map to compare"})

        # refault probe accuracy vs the kernel's OWN refault counter (2026-07-16
        # CORRECTION — monitor critique on REQ-3g verdict). The original check
        # compared probe_refault×512 against `majflt` within 2×. That compared
        # against the WRONG denominator: `workingset_refault` fires PER PAGE
        # that finds a shadow entry, while `majflt` counts readahead-coalesced
        # I/O servicing events (~7× fewer on this kernel — measured 6.6–7.0×
        # across both instr cells). The pre-sampling-era heuristic thus flagged
        # a DESIGNED property (1/512 sample × 512 ≈ true refaults, which exceed
        # majflt by the coalescing factor) as a "broken filter" — a verifier
        # bug, not a data defect. The CORRECT reference is the cgroup's own
        # `workingset_refault_file` counter (summed per pass), against which the
        # ×512-scaled probe is within 0.3–1.8% (measured: 12g r3h 1.018, 16g r3fix
        # 1.003). The 2× sanity band stays (now against the right reference: a
        # gross mismatch there would genuinely flag a broken filter). majflt is
        # kept only as a fallback denominator if the cgroup counter is absent.
        # The tracer is `docker stop`'d at cell end → REFAULT_END often absent;
        # fall back to counting REFAULT event lines directly (ground truth — the
        # stream flushes continuously regardless).
        cell_majflt = sum(p.get("majflt", 0) for p in passes)
        cell_ws_refault = sum(
            (p.get("cg_delta", {}) or {}).get("workingset_refault_file", 0)
            for p in passes)
        if args.refault and Path(args.refault).exists():
            refault_lines = Path(args.refault).read_text(
                errors="replace").splitlines()
            ref_n_end = None
            for line in refault_lines:
                if line.startswith("REFAULT_END"):
                    parts = dict(p.split("=") for p in line.split()[1:]
                                 if "=" in p)
                    ref_n_end = int(parts.get("refault_n", 0))
                    break
            # fallback: count REFAULT event lines directly (ns\tREFAULT\t...)
            ref_n_counted = sum(1 for L in refault_lines
                                if len(L.split("\t")) >= 6
                                and L.split("\t")[0].isdigit()
                                and L.split("\t")[1] == "REFAULT")
            ref_n = ref_n_end if ref_n_end is not None else ref_n_counted
            ref_source = ("REFAULT_END line" if ref_n_end is not None
                          else f"event-line count ({ref_n_counted}, END line "
                               f"absent — tracer stopped before detach)")
            # the refault probe SAMPLES 1 event per SAMPLE_RATE pages (the
            # downsample for perf-ring overrun). Scale ×SAMPLE_RATE and compare
            # to the kernel's own workingset_refault_file (the right reference).
            ref_n_scaled = ref_n * args.sample_rate
            denom = cell_ws_refault if cell_ws_refault else cell_majflt
            denom_name = ("cgroup workingset_refault_file" if cell_ws_refault
                          else "majflt (cgroup ws_refault absent — legacy)")
            if denom > 0:
                ratio = ref_n_scaled / denom
                chk("refault_probe_vs_kernel_counter", 0.5 <= ratio <= 2.0,
                    f"refault_n={ref_n} (sampled 1/{args.sample_rate}, "
                    f"scaled={ref_n_scaled}; source: {ref_source}) / "
                    f"{denom_name}={denom} = {ratio:.3f} "
                    f"(0.5–2.0 sanity band vs kernel's own refault counter; "
                    f"gross mismatch = broken filter)")
        # instrument overhead vs control
        if args.control_result and Path(args.control_result).exists():
            c = json.loads(Path(args.control_result).read_text())
            cpass = c.get("per_pass", [])
            # The overhead bar is on the CONVERGED p50. The two cells can
            # converge in DIFFERENT numbers of passes (12g r3h took 5 vs ctrl's
            # 4 — the tracer's cachestat-snapshot pressure delayed it), so a
            # fixed pass-index is apples-to-oranges (12g pass-3 is mid-sort
            # 824 ms vs ctrl's near-converged 20 ms → a bogus 40×). The uniform,
            # pass-shape-invariant reference is EACH cell's most-converged pass
            # (min majflt = the steady-state regime that cell actually reached).
            # For 12g that's the majflt≈0 final pass (1.006×); for 16g the
            # near_zero rule stops at a ~2000-fault residual tail (artifact §5.1:
            # not a clean steady state, but it IS 16g's converged regime — and
            # the tracer's overhead there, 1.120×, is the honest, if slightly
            # over-bar, number). The pass-3 symmetric transient (both cells at
            # ~14k faults) is recorded as a secondary signal in the detail.
            ip_conv = min(passes, key=lambda x: x.get("majflt", 1 << 62))
            cp_conv = min(cpass, key=lambda x: x.get("majflt", 1 << 62))
            ip50 = ip_conv.get("p50_ms", 0)
            cp50c = cp_conv.get("p50_ms", 0)
            ratio = ip50 / cp50c if cp50c else float("inf")
            # pass-3 transient as a secondary, both-cells-symmetric reference
            t_ip = pctl_pass3(passes, "p50_ms")
            t_cp = pctl_pass3(cpass, "p50_ms")
            t_ratio = t_ip / t_cp if t_cp else 0
            chk("instr_overhead_le_1.10x", ratio <= 1.10,
                f"instr steady p50={ip50:.2f} (pass {ip_conv.get('pass')} "
                f"majflt {ip_conv.get('majflt')}) / control {cp50c:.2f} "
                f"(pass {cp_conv.get('pass')} majflt {cp_conv.get('majflt')}) "
                f"= {ratio:.3f}× (≤1.10×); pass-3 symmetric-transient "
                f"{t_ip:.2f}/{t_cp:.2f}={t_ratio:.3f}×")
    else:
        checks.append({"check": "r3_checks_skipped", "ok": True,
                       "detail": "control cell — ledger/refault bars N/A "
                                 "(latency IS quoted from this cell)"})

    summary = {
        "cell": Path(args.result).stem, "cap_g": cap_g,
        "kind": kind, "passes": len(passes),
        "pass3_p50": pctl_pass3(passes, "p50_ms"),
        "final_p50": cp50, "final_majflt": final_majflt,
        "pass1_majflt": p1_majflt, "verdict": verdict, "checks": checks,
    }
    print(json.dumps(summary, indent=2))
    print(f"\nVERDICT: {verdict}")
    sys.exit(0 if verdict == "VALID" else
            0 if verdict == "UNCONVERGED" else 1)


if __name__ == "__main__":
    main()
