#!/usr/bin/env bash
# Tier-2/3 phase-A orchestrator — runs ON THE OCI SERVE BOX as root
# (PREREGISTRATION_TIER23.md §3 N1-N5, §4 phase A). NOT the dev container,
# NOT the WSL2 host.
#
# One maintenance window: stops sfu-serve, runs the MGLRU arm (box baseline,
# no toggle) then the classic arm (lru_gen off), then the EXIT trap
# unconditionally restarts sfu-serve and restores lru_gen — a wedged cell
# may cost the window, never the demo (N2).
#
# Per cell: sync + drop_caches (first-toucher poisoning, R2 lesson), then a
# systemd-run scope with MemoryMax as the cap. Results + logs land in
# data/eval_results/ (additive only, N3).
#
# Usage (on the box):  sudo bash /mnt/idxvol/scripts/seismic_testbed/t23_host_orchestrator.sh
#   env overrides: ARMS="mglru classic"  RUNGS="free 24 16 12 10 8"
set -u

REPO=/mnt/idxvol
PY=$REPO/.venv/bin/python3
DRIVER=$REPO/scripts/seismic_testbed/t23_convergence_ladder.py
EV=$REPO/data/eval_results
DATE=$(date +%Y%m%d)
LRU=/sys/kernel/mm/lru_gen/enabled
CELL_TIMEOUT=6000              # 100 min hard stop per cell (Tier-1 precedent)
ARMS="${ARMS:-mglru classic}"
RUNGS="${RUNGS:-free 48 36 32 30 28 26}"
# R1/R2 protocol pin (phase-A finding 2026-09-01): the WSL2 cells ran with the
# prefault hotset floor ON (r2 cells record prefault_gate=1, load 177s leaving
# 13.76 GB resident — the artifact's L population). Without it the load is a
# bare mmap-open (1.5s, 0.2 GB) and the two-population initial condition never
# exists. systemd-run --scope children inherit this env; the driver records it.
export SFU_SEISMIC_PREFLOOR_HOTSET=1
RUNLOG=$EV/_t23a_run_${DATE}.log

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$RUNLOG"; }

[ "$(id -u)" = 0 ] || { echo "must run as root"; exit 1; }
[ -x "$PY" ] && [ -f "$DRIVER" ] || { echo "driver/venv missing"; exit 1; }

# Pinned, not read from boot state: a prior interrupted run can leave the
# toggle polluted (observed 2026-09-01: killed mid-classic-arm -> 0x0000 read
# back as "baseline", every mglru cell then correctly refused). The box's true
# baseline is pre-registered (PREREGISTRATION_TIER23.md section 1).
BASELINE_LRU="${BASELINE_LRU:-0x0007}"
BOOT_LRU=$(cat "$LRU")
[ "$BOOT_LRU" = "$BASELINE_LRU" ] || echo "WARNING: lru_gen at start is $BOOT_LRU, not pinned baseline $BASELINE_LRU (prior run residue?)"
SERVE_WAS=$(systemctl is-active sfu-serve || true)
log "phase A start: arms=[$ARMS] rungs=[$RUNGS] lru_gen baseline=$BASELINE_LRU sfu-serve=$SERVE_WAS"

restore() {
    rc=$?
    trap - EXIT INT TERM
    # N2: unconditional restore, regardless of how we got here
    if ! printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null; then
        echo y > "$LRU" 2>/dev/null || true
    fi
    systemctl start sfu-serve || systemctl restart sfu-serve || true
    log "RESTORED: lru_gen=$(cat "$LRU") sfu-serve=$(systemctl is-active sfu-serve || true) (exit rc=$rc)"
    touch "$EV/_t23a_ALLDONE_${DATE}"
    exit "$rc"
}
trap restore EXIT INT TERM

systemctl stop sfu-serve
log "sfu-serve stopped for the window"

# The backend resolves relative asset paths (models/splade_onnx_fused, needed
# by the PREFLOOR encoder init) against cwd; a transient unit starts at /.
cd "$REPO"

for ARM in $ARMS; do
    if [ "$ARM" = classic ]; then
        echo n > "$LRU"
    else
        printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null || echo y > "$LRU"
    fi
    log "arm=$ARM lru_gen now $(cat "$LRU")"

    for G in $RUNGS; do
        LABEL="cap${G}g"; [ "$G" = free ] && LABEL="free"
        RESULT="data/eval_results/t23a_${ARM}_${LABEL}_${DATE}.json"
        CLOG="$EV/_t23a_${ARM}_${LABEL}_${DATE}.log"
        STATUS="$EV/_t23a_${ARM}_${LABEL}_${DATE}.status"
        if [ -s "$REPO/$RESULT" ]; then
            log "SKIP $ARM/$LABEL — result exists"; echo DONE > "$STATUS"; continue
        fi
        sync
        echo 3 > /proc/sys/vm/drop_caches
        CAP_OPT=""; [ "$G" != free ] && CAP_OPT="-p MemoryMax=${G}G"
        log "cell $ARM/$LABEL starting (timeout ${CELL_TIMEOUT}s)"
        # shellcheck disable=SC2086  # CAP_OPT intentionally word-split
        systemd-run --scope --collect --quiet -p MemorySwapMax=0 $CAP_OPT -- \
            timeout $CELL_TIMEOUT "$PY" "$DRIVER" \
                --arm "$ARM" --cap-label "$LABEL" \
                --result-file "$REPO/$RESULT" >"$CLOG" 2>&1
        rc=$?
        if [ $rc -eq 0 ] && [ -s "$REPO/$RESULT" ]; then
            echo DONE > "$STATUS"; log "cell $ARM/$LABEL DONE"
        else
            echo "FAIL($rc)" > "$STATUS"; log "cell $ARM/$LABEL FAIL rc=$rc (see $CLOG)"
        fi
    done
done

log "phase A cells complete"
