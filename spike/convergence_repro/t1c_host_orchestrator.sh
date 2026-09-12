#!/usr/bin/env bash
# TIER-1c convergence-repro orchestrator — runs ON THE OCI SERVE BOX as root.
#
# Runs the native (docker-free) residency-seeded synthetic (t1c_cell.py) under a
# real memory cap on a REAL Linux host with MGLRU available — the two things the
# WSL2/classic-LRU docker synthetic never had (publication-gate items 2-3).
# See spike/convergence_repro/PREREGISTRATION_TIER1C.md and RESULTS.md sections
# 14/16 for why this experiment exists.
#
# Cell spec:  arm:fracPct:capGiB:seed   (e.g. mglru:92:6:1729)
#   arm     classic | mglru  — sets /sys/kernel/mm/lru_gen/enabled per cell
#   fracPct target R residency at pass-1 start, integer percent (the SEEDED
#           deficit — decoupled from load order, the Tier-1c move)
#   capGiB  MemoryMax for the cell's systemd scope (independent of fracPct now)
#   seed    determinism seed (resident subset + repeat permutation)
#
# Reuses the sml orchestrator's window discipline VERBATIM in intent (D-sml-1/2/3
# lessons): single-live-instance lock, apt-timer freeze + restore, sfu-serve
# stopped for a quiet page cache and restored in the trap, lru_gen pinned back to
# 0x0007 on exit, priority-ordered CELLS shed at a deadline, any-date SKIP resume.
# Unlike sml this uses NO docker (absent on the box) and does NOT load the 150M
# index — it lays down its own R/L scratch under $DATADIR and removes it on exit.
#
# Usage (on the box):
#   sudo systemd-run --unit=t1c-orch --collect -p TimeoutStopSec=300 \
#       bash /mnt/idxvol/spike/convergence_repro/t1c_host_orchestrator.sh
set -u

REPO=/mnt/idxvol
PY=$REPO/.venv/bin/python3
DRIVER=$REPO/spike/convergence_repro/t1c_cell.py
EV=$REPO/data/eval_results
DATADIR="${DATADIR:-$REPO/data/t1c_scratch}"
DATE=$(date +%Y%m%d)
LRU=/sys/kernel/mm/lru_gen/enabled
R_MIB="${R_MIB:-5120}"
L_MIB="${L_MIB:-1792}"
PASSES="${PASSES:-12}"
CELL_TIMEOUT="${CELL_TIMEOUT:-900}"            # 15 min/cell (cells are cheap: only deficit pages fault)
WINDOW_DEADLINE_S="${WINDOW_DEADLINE_S:-5400}" # no new cell after 90 min
# Calibration matrix (PREREGISTRATION_TIER1C.md, run-2 one-shot correction):
# caps BELOW |R|=5G so the cap binds on R itself (run 1 proved caps >= R give
# pure 1-pass deficit-decay with no arm difference -- nothing evicts). Here R
# cannot fully fit, so every pass re-faults the shortfall and the STEADY MAJFLT
# FLOOR is the graded metric: classic (refault-activation) is expected to reach
# a lower floor than MGLRU (never re-promotes refaulting pages) -- the Tier-2/3
# / sml arm asymmetry at synthetic scale. Both arms x {4.0, 4.5, 3.5}G.
CELLS="${CELLS:-classic:92:4:1729 mglru:92:4:1729 classic:92:4.5:1729 mglru:92:4.5:1729 classic:92:3.5:1729 mglru:92:3.5:1729}"
BASELINE_LRU="${BASELINE_LRU:-0x0007}"
RUNLOG=$EV/_t1c_runA_${DATE}.log
T0=$(date +%s)

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$RUNLOG"; }

[ "$(id -u)" = 0 ] || { echo "must run as root"; exit 1; }
[ -x "$PY" ] && [ -f "$DRIVER" ] || { echo "driver/venv missing"; exit 1; }
[ -e "$LRU" ] || { echo "no /sys/kernel/mm/lru_gen/enabled — MGLRU absent, wrong host"; exit 1; }

LOCK=/run/t1c-orch.lock
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
    echo "[$(date '+%H:%M:%S')] REFUSING: live t1c-orch PID $(cat "$LOCK") holds $LOCK" | tee -a "$RUNLOG"
    exit 0
fi
echo $$ > "$LOCK"

APT_TIMERS="apt-daily.timer apt-daily-upgrade.timer"
APT_WAS_ACTIVE=""
for t in $APT_TIMERS; do
    if systemctl is-active "$t" >/dev/null 2>&1; then
        APT_WAS_ACTIVE="$APT_WAS_ACTIVE $t"
        systemctl stop "$t" 2>/dev/null || true
    fi
done
systemctl stop apt-daily.service apt-daily-upgrade.service 2>/dev/null || true

BOOT_LRU=$(cat "$LRU")
[ "$BOOT_LRU" = "$BASELINE_LRU" ] || log "WARNING: lru_gen at start is $BOOT_LRU, not baseline $BASELINE_LRU"
log "tier1c start: deadline ${WINDOW_DEADLINE_S}s, cell timeout ${CELL_TIMEOUT}s, R=${R_MIB}MiB L=${L_MIB}MiB passes=${PASSES}, cells=[$CELLS]"

CELL_BG=""
restore() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$CELL_BG" ]; then kill "$CELL_BG" 2>/dev/null || true; wait "$CELL_BG" 2>/dev/null || true; fi
    if ! printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null; then echo y > "$LRU" 2>/dev/null || true; fi
    systemctl start sfu-serve || systemctl restart sfu-serve || true
    for t in $APT_WAS_ACTIVE; do systemctl start "$t" 2>/dev/null || true; done
    rm -rf "$DATADIR" 2>/dev/null || true
    [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ] && rm -f "$LOCK"
    log "RESTORED: lru_gen=$(cat "$LRU") sfu-serve=$(systemctl is-active sfu-serve || true) apt-timers=[${APT_WAS_ACTIVE:- none}] scratch-removed (exit rc=$rc)"
    touch "$EV/_t1c_ALLDONE_${DATE}"
    exit "$rc"
}
trap restore EXIT INT TERM

systemctl stop sfu-serve
log "sfu-serve stopped for the window (quiet page cache)"
mkdir -p "$DATADIR"
cd "$REPO"

# Lay down R/L ONCE; every cell reuses via --skip-laydown (content bytes are
# irrelevant beyond being non-sparse/incompressible; the seed drives residency).
log "laydown: R=${R_MIB}MiB L=${L_MIB}MiB in $DATADIR"
"$PY" "$DRIVER" --data-dir "$DATADIR" --r-size-mib "$R_MIB" --l-size-mib "$L_MIB" \
    --resident-frac 1.0 --seed 1729 --result-file /dev/null --laydown-only \
    >>"$RUNLOG" 2>&1 || { log "laydown FAILED — aborting"; exit 4; }

for SPEC in $CELLS; do
    ARM=${SPEC%%:*}; REST=${SPEC#*:}
    FRACPCT=${REST%%:*}; REST=${REST#*:}
    G=${REST%%:*}; SEED=${REST#*:}
    ELAPSED=$(( $(date +%s) - T0 ))
    if [ "$ELAPSED" -ge "$WINDOW_DEADLINE_S" ]; then
        log "DEADLINE: ${ELAPSED}s elapsed — not starting $SPEC (or anything after); resume later"
        break
    fi
    case "$ARM" in classic|mglru) ;; *) log "CONFIG ERROR: unknown arm '$ARM' in '$SPEC'"; exit 2 ;; esac
    FRAC=$(awk -v p="$FRACPCT" 'BEGIN{printf "%.4f", p/100.0}')
    LABEL="frac${FRACPCT}_cap${G}g_seed${SEED}"
    RESULT="data/eval_results/t1c_${ARM}_${LABEL}_${DATE}.json"
    CLOG="$EV/_t1c_${ARM}_${LABEL}_${DATE}.log"
    STATUS="$EV/_t1c_${ARM}_${LABEL}_${DATE}.status"
    EXISTING=$(ls "$EV"/t1c_"${ARM}"_"${LABEL}"_*.json 2>/dev/null | head -1)
    if [ -n "$EXISTING" ] && [ -s "$EXISTING" ]; then
        log "SKIP $ARM/$LABEL — result exists ($(basename "$EXISTING"))"; echo DONE > "$STATUS"; continue
    fi
    if [ "$ARM" = classic ]; then echo n > "$LRU"; else printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null || echo y > "$LRU"; fi
    sync; echo 3 > /proc/sys/vm/drop_caches
    log "cell $ARM/$LABEL starting (elapsed ${ELAPSED}s, lru_gen $(cat "$LRU"), frac=$FRAC cap=${G}G)"
    systemd-run --scope --collect --quiet -p MemorySwapMax=0 -p "MemoryMax=${G}G" -- \
        timeout "$CELL_TIMEOUT" "$PY" "$DRIVER" \
            --data-dir "$DATADIR" --r-size-mib "$R_MIB" --l-size-mib "$L_MIB" \
            --resident-frac "$FRAC" --passes "$PASSES" --seed "$SEED" \
            --arm "$ARM" --cap-label "cap${G}g" --skip-laydown \
            --result-file "$REPO/$RESULT" >"$CLOG" 2>&1 &
    CELL_BG=$!
    wait "$CELL_BG"
    rc=$?
    CELL_BG=""
    if [ $rc -eq 0 ] && [ -s "$REPO/$RESULT" ]; then
        VIOLATION=""
        grep -q '"protocol": "tier1c"' "$REPO/$RESULT" || VIOLATION="protocol!=tier1c"
        if [ -z "$VIOLATION" ] && ! grep -q '"soundness_pass1_majflt_eq_deficit": true' "$REPO/$RESULT"; then
            VIOLATION="soundness identity failed (pass1 majflt != seed deficit)"
        fi
        if [ -z "$VIOLATION" ]; then
            echo DONE > "$STATUS"; log "cell $ARM/$LABEL DONE"
        else
            mv "$REPO/$RESULT" "$REPO/${RESULT%.json}.PROTOVIOLATION.json"
            echo "PROTOVIOLATION" > "$STATUS"
            log "cell $ARM/$LABEL PROTOCOL VIOLATION: ${VIOLATION} — quarantined, aborting window"
            exit 5
        fi
    else
        echo "FAIL($rc)" > "$STATUS"; log "cell $ARM/$LABEL FAIL rc=$rc (see $CLOG)"
    fi
done

log "tier1c window complete"
