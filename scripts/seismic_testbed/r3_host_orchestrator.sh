#!/usr/bin/env bash
# R3 host orchestrator (2026-07-16; doc 15 §5) — memory-capped sibling cells
# for the kernel-ledger spike, with per-instrumented-cell privileged tracing.
# EXTENDS r2_host_orchestrator.sh: same drop_caches-then-capped-cell flow,
# same status-file protocol, same MSYS_NO_PATHCONV=1 style — ADDS a privileged
# --pid=host tracer container running instruments 1+3 (the ledger + refault
# probe) beside the instrumented cells, and uses the R3 driver
# (r3_kernel_ledger_driver.py) which writes pass-boundary CLOCK_MONOTONIC ns
# so the ledger can be sliced by pass.
#
# Runs on the WINDOWS HOST (Git Bash), NOT in the dev container: the dev
# container has no docker daemon and read-only cgroups (E7b). The in-container
# drive session (_r3_kernel_ledger_drive_prompt.md) verifies/commits cells here.
#
# Cell order (doc 15 §5): 16g-ctrl, 12g-ctrl (NO tracer), then 16g-instr,
# 12g-instr (WITH tracer). Controls establish the uninstrumented baseline +
# latency (latency is ONLY quoted from controls, §4); instrumented cells
# contribute residency/attribution state. Output naming:
#   results  r3_cap<N>g_<ctrl|instr>_<DATE>.json
#   logs     _r3_cap<N>g_<ctrl|instr>_drive.log
#   ledger   _r3_cap<N>g_instr_ledger.log      (bpftrace stdout, instr only)
#   refault  _r3_cap<N>g_instr_refault.log     (refault probe stdout)
#   status   _r3_cap<N>g_<ctrl|instr>.status   RUNNING/DONE/FAIL
#   all-done _r3_cells.ALLDONE
#
# Usage (from repo root on the host):
#   bash scripts/seismic_testbed/r3_host_orchestrator.sh
set -u
export MSYS_NO_PATHCONV=1

HOSTREPO="C:/Users/<user>/claudebox-projects/sfu-library-thinclient"
CREPO="/workspaces/sfu-library-thinclient"
IMG="claudebox-sfu-library-thinclient-app"
# tracer image: a bpftrace-capable bookworm. Built/installed once; bpftrace
# apt'd inside the throwaway probe container in r3_capability_probe.sh — here
# we reuse debian:bookworm-slim and apt bpftrace in the tracer (same pattern).
TRACER_IMG="debian:bookworm-slim"
# host-side eval dir (used for OUTER redirects + status files — host paths)
EV="$HOSTREPO/data/eval_results"
# container-side eval dir (the path the SAME files have INSIDE a bind-mounted
# container). bpftrace redirects + the cell's --result-file use CEV because
# they execute INSIDE the container; the outer `> "$CLOG"` uses EV (host). The
# two paths point at the same bytes via the bind mount — mixing them up (the
# REQ-1 host-vs-container path class) writes logs to nonexistent in-container
# paths. This split makes the scope explicit.
CEV="${CREPO}/data/eval_results"
DATE=$(date +%Y%m%d)
# optional suffix on result/log/status filenames (env override) — used by REQ-3
# to re-run the instr cells with the corrected probes WITHOUT clobbering the
# REQ-2 PARTIAL cells' valid cachestat maps (which differ only by filename
# suffix). Empty = the default r3_<label>_<DATE>.* naming (REQ-2).
DATE_SUFFIX="${_R3_DATE_SUFFIX:-}"
CELL_TIMEOUT=6000          # 100 min in-container hard stop per cell
# PRE-SPLICED probe files (generated + verified in-container by
# scripts/seismic_testbed/r3_splice_probes.py: the inode body from
# _r3_inode_body.bt is substituted into each probe's single BEGIN at the
# /*INODE_BODY*/ placeholder). The tracer `bpftrace <file>`s these directly —
# no sed-under-nested-quotes at run time (the 4th-attempt fix; see
# start_tracer's LOAD PATH note). Regenerate after touching any probe or the
# inode map. (LEDGER_BT/REFAULT_BT/INODE_BODY kept for the generator.)
LEDGER_BT="${CREPO}/scripts/seismic_testbed/r3_ledger.bt"
REFAULT_BT="${CREPO}/scripts/seismic_testbed/r3_refault_probe.bt"
INODE_BODY="${CEV}/_r3_inode_body.bt"
LEDGER_SPLICED="${CREPO}/scripts/seismic_testbed/r3_ledger_spliced.bt"
REFAULT_SPLICED="${CREPO}/scripts/seismic_testbed/r3_refault_probe_spliced.bt"

# cell plan: "capG:mode" pairs, mode=ctrl|instr. (doc 15 §5)
# cell plan: "capG:mode" pairs, mode=ctrl|instr. (doc 15 §5). Use "$*" (all
# args joined with spaces) NOT "$1" — a two-arg invoke like
# `... 16:instr 12:instr` passed $1=16:instr only and silently DROPPED 12:instr
# (the REQ-3f monitor found ALLDONE "cells: 16:instr" + 12g never ran). "$*"
# captures every positional arg as one space-joined list.
CELLS="${*:-16:ctrl 12:ctrl 16:instr 12:instr}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# start the privileged tracer (ledger + refault probe) beside an instrumented
# cell. $1=label (e.g. 12g_instr). Runs bpftrace --pid=host so it sees the
# capped cell's filemap/refault events, writing logs to the host eval dir.
#
# LOAD PATH (fixed 2026-07-16, twice): the inode filter is a BODY fragment
# (_r3_inode_body.bt — `@shard_inodes[ino]=tag` + count lines, NO BEGIN wrapper)
# spliced INTO each probe's SINGLE BEGIN at the /*INODE_BODY*/ placeholder via
# sed. bpftrace rejects "more than one BEGIN probe defined" (the REQ-3 monitor
# found this: concatenating two BEGIN-wrapped files fails), so the body cannot
# be its own BEGIN nor loaded via `bpftrace --include` (that is a C-preprocessor
# #include for C headers only → bpftrace syntax un-parsed → @shard_inodes empty
# → the predicate always false → ZERO events, the REQ-1 silent-failure class).
# The sed splice yields exactly ONE BEGIN per probe, map populated, breadcrumb
# prints `shard_inodes_loaded=<n>` at attach; the readiness wait below greps for
# it and records a TRACER_WARN if 0 (map did not load — likely a cross-container
# inode remap under drvfs; the cell still runs but its ledger is recorded INVALID
# by the Phase C filter checks, not silently).
start_tracer() {
  local LABEL="$1"
  local LEDLOG_HOST="$EV/_r3_${LABEL}_ledger.log"
  local REFLOG_HOST="$EV/_r3_${LABEL}_refault.log"
  # in-container log paths (the bpftrace redirects run INSIDE the tracer
  # container, which sees /workspaces, not C:/Users/<user>)
  local LEDLOG_C="$CEV/_r3_${LABEL}_ledger.log"
  local REFLOG_C="$CEV/_r3_${LABEL}_refault.log"
  log "starting tracer for $LABEL (ledger->$LEDLOG_HOST, refault->$REFLOG_HOST)"
  # apt-get bpftrace into the throwaway tracer, then run both probes against
  # the host pid namespace so they see the capped cell's filemap events.
  # --pid=host + --privileged + tracefs mount = visible tracepoints + CAP_BPF.
  #
  # LOAD PATH (fixed 2026-07-16, 4th attempt — the sed-under-nested-quotes
  # approach failed THREE times: REQ-3 `--include` ignored bpftrace syntax;
  # REQ-3b the BEGIN-merge; REQ-3c the one-char sed `r` typo; and the
  # follow-on `r: command not found` from MSYS/Git Bash backslash handling of
  # `sed -e "/.../r f" -e "/.../d"` inside `bash -c "..."` double quotes). The
  # robust, TESTABLE-IN-CONTAINER design: the inode body is PRE-SPLICED into
  # each probe at the /*INODE_BODY*/ placeholder by `r3_splice_probes.py`
  # (run here in the dev container where BEGIN-count + body-load are verified),
  # producing committed `r3_ledger_spliced.bt` / `r3_refault_probe_spliced.bt`
  # files. The tracer just `bpftrace <file>`s them — NO sed, NO nested quotes,
  # NO MSYS backslash mangling. One BEGIN per probe (bpftrace rejects more).
  docker run --rm -d --name "r3tracer_${LABEL}" \
    --privileged --pid=host \
    -v "${HOSTREPO}:${CREPO}" -w "${CREPO}" \
    -e MSYS_NO_PATHCONV=1 \
    "$TRACER_IMG" bash -c '
      apt-get update -q >/dev/null 2>&1
      apt-get install -y -q bpftrace >/dev/null 2>&1
      echo TRACER_READY $(date -u +%FT%TZ)
      # mount tracefs if not already (privileged container)
      mkdir -p /sys/kernel/tracing 2>/dev/null
      mount -t tracefs nodev /sys/kernel/tracing 2>/dev/null || true
      # PREFLIGHT (monitor recommendation, REQ-3e): dry-parse each spliced probe
      # (bpftrace -d = compile/parse only, NO kernel attach) so a probe with a
      # parse error or an unsupported attach type ("Invalid probe type ...",
      # the fentry/kfunc-on-bookworm-0.17 failure class) is caught in seconds,
      # not after a ~15 min cell. A failing probe still runs for the real run
      # (the readiness wait / TRACER_FAIL branch below records the attach
      # outcome); -d just front-loads the parse verdict into the preflight log.
      # Kept non-fatal: a probe can parse clean but fail to ATTACH (e.g. a BTF
      # field path that resolves at parse but not attach) — the real run + the
      # 150s breadcrumb / ERROR grep is the authority.
      bpftrace -d '"${LEDGER_SPLICED}"' 2>&1 | tail -1 | sed "s/^/PREFLIGHT ledger: /" >> '"${LEDLOG_C}"'.preflight
      bpftrace -d '"${REFAULT_SPLICED}"' 2>&1 | tail -1 | sed "s/^/PREFLIGHT refault: /" >> '"${REFLOG_C}"'.preflight
      # ledger (instrument 1) + refault probe (instrument 3), PRE-SPLICED files.
      # Single quotes for the bash -c body so nothing is host-shell-expanded
      # except the two file paths we inject below (the probes are committed,
      # stable paths — no env-var expansion needed inside).
      bpftrace '"${LEDGER_SPLICED}"' > '"${LEDLOG_C}"' 2>&1 &
      LPID=$!
      bpftrace '"${REFAULT_SPLICED}"' > '"${REFLOG_C}"' 2>&1 &
      RPID=$!
      wait $LPID $RPID
    ' >/dev/null 2>&1 &   # the docker run -d already detaches; this & is harmless
  # wait for apt-get (~60s observed) + bpftrace compile/attach + the breadcrumb
  # print, then read it. REQ-2 hit the 90s ceiling — apt alone consumed most of
  # it both times (monitor note) — so the budget is now 150s. The breadcrumb
  # shard_inodes_loaded=N surfaces a zero-load filter in seconds rather than
  # after a full ~1h cell; a probe compile error surfaces here too (the grep
  # finds ERROR lines in the bpftrace log if attach failed).
  local waited=0
  while [ "$waited" -lt 150 ]; do
    sleep 5; waited=$((waited+5))
    if grep -q "shard_inodes_loaded" "$LEDLOG_HOST" 2>/dev/null; then break; fi
    if grep -q "ERROR" "$LEDLOG_HOST" 2>/dev/null; then break; fi
  done
  local LOADED
  LOADED=$(grep -o "shard_inodes_loaded=[0-9]*" "$LEDLOG_HOST" 2>/dev/null | head -1 | cut -d= -f2)
  if grep -q "ERROR" "$LEDLOG_HOST" 2>/dev/null; then
    # bpftrace failed to compile/attach (probe parse error, spliced body wrong,
    # field name still bad). The cell will run but its ledger is INVALID.
    log "TRACER_FAIL: bpftrace ERROR in $LEDLOG_HOST for $LABEL — probe did not attach; ledger will be empty; first ERROR:"
    grep -m1 "ERROR" "$LEDLOG_HOST" 2>/dev/null | sed 's/^/    /'
  elif [ -z "$LOADED" ]; then
    log "WARN: tracer for $LABEL has not printed the breadcrumb in ${waited}s — bpftrace may still be installing; ledger may be empty"
  elif [ "$LOADED" = "0" ]; then
    log "TRACER_WARN: shard_inodes_loaded=0 for $LABEL — inode map did NOT load (cross-container drvfs remap or parse error); the cell will run but its ledger will be INVALID by the Phase C filter checks"
  else
    log "tracer r3tracer_${LABEL} attached OK (shard_inodes_loaded=$LOADED)"
  fi
}

stop_tracer() {
  local LABEL="$1"
  log "stopping tracer for $LABEL"
  docker stop "r3tracer_${LABEL}" >/dev/null 2>&1 || true
  docker rm -f "r3tracer_${LABEL}" >/dev/null 2>&1 || true
}

for C in $CELLS; do
  G="${C%%:*}"; MODE="${C##*:}"
  LABEL="cap${G}g_${MODE}"
  # suffix (REQ-3 re-run) threads through status/log/result/ledger/refault/
  # cachestat names so the corrected-probe re-run does NOT clobber the REQ-2
  # PARTIAL cells' valid cachestat maps. Default (empty) = REQ-2 naming.
  SUF="${DATE_SUFFIX:+_${DATE_SUFFIX}}"
  STATUS="$EV/_r3_${LABEL}${SUF}.status"
  CLOG="$EV/_r3_${LABEL}${SUF}_drive.log"
  RESULT="data/eval_results/r3_${LABEL}${SUF}_${DATE}.json"
  INSTR_FLAG=""

  log "=== cell $LABEL${SUF} ==="
  echo "RUNNING $(date -u +%FT%TZ)" > "$STATUS"

  log "dropping shared WSL2 page cache (cold-start purity)"
  docker run --rm --privileged alpine \
    sh -c 'sync; echo 1 > /proc/sys/vm/drop_caches' \
    || { log "drop_caches FAILED — aborting cell (would be contaminated)";
         echo "FAIL drop_caches $(date -u +%FT%TZ)" > "$STATUS"; continue; }

  if [ "$MODE" = "instr" ]; then
    start_tracer "${LABEL}${SUF}"
    INSTR_FLAG="--cachestat-between-passes"
  fi

  # the capped cell: R3 driver, same memory-swap cap as R2 (swap forbidden),
  # prefault-ON, pass-boundary ns + between-pass cachestat (instr cells).
  # --cell-label carries the suffix so the between-pass cachestat maps
  # (_r3_cachestat_<cell-label>_pass<k>.json) are also suffixed (no clobber).
  docker run --rm --name "r3cell_${LABEL}${SUF}" \
    --memory="${G}g" --memory-swap="${G}g" \
    -v "${HOSTREPO}:${CREPO}" -w "${CREPO}" \
    -e SFU_SEISMIC_PREFLOOR_HOTSET=1 \
    -e MSYS_NO_PATHCONV=1 \
    "$IMG" timeout "$CELL_TIMEOUT" .venv/bin/python3 \
      scripts/seismic_testbed/r3_kernel_ledger_driver.py \
      --cap-label "${G}g" --cell-label "${LABEL}${SUF}" \
      --result-file "$RESULT" $INSTR_FLAG \
    > "$CLOG" 2>&1
  RC=$?

  if [ "$MODE" = "instr" ]; then
    stop_tracer "${LABEL}${SUF}"
  fi

  if [ "$RC" -eq 0 ] && [ -s "$HOSTREPO/$RESULT" ]; then
    echo "DONE $(date -u +%FT%TZ) $RESULT" > "$STATUS"
    log "cell $LABEL DONE -> $RESULT"
  else
    echo "FAIL rc=$RC $(date -u +%FT%TZ)" > "$STATUS"
    log "cell $LABEL FAIL rc=$RC (124=timeout, 3=empty-results) — continuing"
  fi
done

{
  echo "ALLDONE $(date -u +%FT%TZ)"
  echo "cells: $CELLS"
  for f in "$EV"/_r3_cap*.status; do echo "$(basename "$f"): $(cat "$f")"; done
} > "$EV/_r3_cells.ALLDONE"
log "=== R3 cells complete — wrote _r3_cells.ALLDONE ==="
