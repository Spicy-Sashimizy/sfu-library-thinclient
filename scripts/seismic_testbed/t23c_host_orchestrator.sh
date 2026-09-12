#!/usr/bin/env bash
# Tier-2/3 AMENDMENT-1 DESCENT orchestrator (t23c) — runs ON THE OCI SERVE BOX
# as root (PREREGISTRATION_TIER23_AMEND1.md: classic ladder extension below
# 25 G to bracket the plateau floor; bars B1x/B5x freeze only after this
# descent is recorded).
#
# Same guarantees as the t23b orchestrator it clones: priority-ordered flat
# CELLS (arm:rungGiB:rep), WINDOW_DEADLINE_S (no new cell after it, restore
# guaranteed in-window), stop-anytime (`systemctl stop t23c-orch` fires the
# trap: sfu-serve restarted, lru_gen repinned), any-date existing-result
# SKIP for resume, per-cell prefault_gate=1 verification with
# quarantine-and-abort. Descent-specific: CELL_TIMEOUT default 5400 s so a
# plateau verdict can complete pass 3 (sml phase A' measured ~1500 s/pass
# at 18-20 G); default CELLS descend 24->16 with mglru:28:2 (B5x replicate)
# last.
#
# Usage (on the box):
#   sudo systemd-run --unit=t23c-orch --collect \
#       bash /mnt/idxvol/scripts/seismic_testbed/t23c_host_orchestrator.sh
set -u

REPO=/mnt/idxvol
PY=$REPO/.venv/bin/python3
DRIVER=$REPO/scripts/seismic_testbed/t23_convergence_ladder.py
EV=$REPO/data/eval_results
DATE=$(date +%Y%m%d)
LRU=/sys/kernel/mm/lru_gen/enabled
CELL_TIMEOUT="${CELL_TIMEOUT:-5400}"          # 90 min/cell: a plateau verdict needs pass 3 to COMPLETE (~1500 s/pass at 18-20 G, sml phase A' measured)
WINDOW_DEADLINE_S="${WINDOW_DEADLINE_S:-3600}" # no new cell after 60 min (worst-case end = deadline + one 90-min cell)
# Frozen priority order (pre-reg G4): B2/B3/B1 replicate pairs -> B5 bracket
# -> ladder fill. arm:rungGiB:rep
CELLS="${CELLS:-classic:24:1 classic:22:1 classic:20:1 classic:18:1 classic:16:1 mglru:28:2}"
RUNLOG=$EV/_t23c_run_${DATE}.log
T0=$(date +%s)

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$RUNLOG"; }

[ "$(id -u)" = 0 ] || { echo "must run as root"; exit 1; }
[ -x "$PY" ] && [ -f "$DRIVER" ] || { echo "driver/venv missing"; exit 1; }

# Protocol pin (pre-reg section 7, phase-A adjustment item 1). Its omission
# from this script invalidated phase-B run 1 (2026-09-01, cells renamed
# t23c0_noprefault_*): all 17 cells ran without the L population. The
# per-cell check below makes the violation loud instead of silent.
export SFU_SEISMIC_PREFLOOR_HOTSET=1

BASELINE_LRU="${BASELINE_LRU:-0x0007}"   # pinned (pre-reg section 1); boot state not trusted
BOOT_LRU=$(cat "$LRU")
[ "$BOOT_LRU" = "$BASELINE_LRU" ] || log "WARNING: lru_gen at start is $BOOT_LRU, not pinned baseline $BASELINE_LRU"
log "t23c descent start: deadline ${WINDOW_DEADLINE_S}s, cell timeout ${CELL_TIMEOUT}s, cells=[$CELLS]"

restore() {
    rc=$?
    trap - EXIT INT TERM
    if ! printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null; then
        echo y > "$LRU" 2>/dev/null || true
    fi
    systemctl start sfu-serve || systemctl restart sfu-serve || true
    log "RESTORED: lru_gen=$(cat "$LRU") sfu-serve=$(systemctl is-active sfu-serve || true) (exit rc=$rc)"
    touch "$EV/_t23c_ALLDONE_${DATE}"
    exit "$rc"
}
trap restore EXIT INT TERM

systemctl stop sfu-serve
log "sfu-serve stopped for the window"
cd "$REPO"

for SPEC in $CELLS; do
    ARM=${SPEC%%:*}; REST=${SPEC#*:}; G=${REST%%:*}; REP=${REST#*:}
    ELAPSED=$(( $(date +%s) - T0 ))
    if [ "$ELAPSED" -ge "$WINDOW_DEADLINE_S" ]; then
        log "DEADLINE: ${ELAPSED}s elapsed — not starting $SPEC (or anything after); resume in a later window"
        break
    fi
    LABEL="cap${G}g_rep${REP}"
    RESULT="data/eval_results/t23c_${ARM}_${LABEL}_${DATE}.json"
    CLOG="$EV/_t23c_${ARM}_${LABEL}_${DATE}.log"
    STATUS="$EV/_t23c_${ARM}_${LABEL}_${DATE}.status"
    # Resume must survive a date rollover: a completed cell from ANY prior
    # window (any date) skips, else a later-day resume re-runs all cells.
    EXISTING=$(ls "$EV"/t23c_"${ARM}"_"${LABEL}"_*.json 2>/dev/null | head -1)
    if [ -n "$EXISTING" ] && [ -s "$EXISTING" ]; then
        log "SKIP $ARM/$LABEL — result exists ($(basename "$EXISTING"))"; echo DONE > "$STATUS"; continue
    fi
    if [ "$ARM" = classic ]; then echo n > "$LRU"; else printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null || echo y > "$LRU"; fi
    sync
    echo 3 > /proc/sys/vm/drop_caches
    log "cell $ARM/$LABEL starting (elapsed ${ELAPSED}s, lru_gen $(cat "$LRU"))"
    systemd-run --scope --collect --quiet -p MemorySwapMax=0 -p "MemoryMax=${G}G" -- \
        timeout "$CELL_TIMEOUT" "$PY" "$DRIVER" \
            --arm "$ARM" --cap-label "cap${G}g" --t23c descent \
            --result-file "$REPO/$RESULT" >"$CLOG" 2>&1
    rc=$?
    if [ $rc -eq 0 ] && [ -s "$REPO/$RESULT" ]; then
        if grep -q '"prefault_gate": "1"' "$REPO/$RESULT"; then
            echo DONE > "$STATUS"; log "cell $ARM/$LABEL DONE"
        else
            mv "$REPO/$RESULT" "$REPO/${RESULT%.json}.PROTOVIOLATION.json"
            echo "PROTOVIOLATION" > "$STATUS"
            log "cell $ARM/$LABEL PROTOCOL VIOLATION: prefault_gate!=1 — result quarantined, aborting window"
            exit 5
        fi
    else
        echo "FAIL($rc)" > "$STATUS"; log "cell $ARM/$LABEL FAIL rc=$rc (see $CLOG)"
    fi
done

log "t23c descent window complete"
