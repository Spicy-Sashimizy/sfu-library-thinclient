#!/usr/bin/env bash
# Small-machine levers PHASE-A' orchestrator — runs ON THE OCI SERVE BOX as root
# (spike/archive/smallmachine_levers/PREREGISTRATION.md sections 2-5: lever arms
# L0/L1/L3, calibration cells, bar N8 protocol pin).
#
# Differences from the Tier-2/3 phase-B orchestrator (t23b_host_orchestrator.sh):
#   * CELLS entries carry a lever prefix — lever:arm:rungGiB:rep — and the
#     lever, not a global export, decides the cell's environment: L0/L3 load
#     the residue (SFU_SEISMIC_PREFLOOR_HOTSET=1), L1 does not (=0), L3 adds
#     the one-shot post-load reclaim nudge (--postload-reclaim-bytes). The
#     gate variable is set explicitly for EVERY cell, so no iteration ever
#     inherits the previous cell's lever;
#   * per-cell protocol verification (pre-reg N8) checks prefault_gate against
#     the cell's OWN lever and, for L3, that the reclaim actually freed pages;
#   * calibration timings: deep small-cap cells run long, so the per-cell
#     timeout and the window deadline are wider than phase B's.
#
# Unchanged from t23b (deliberately): priority-ordered flat CELLS list so a
# time cutoff sheds the least important tail; WINDOW_DEADLINE_S — no new cell
# starts after the deadline, so restore is guaranteed inside the user's window;
# stop-anytime — every finished cell's JSON is already on disk,
# `systemctl stop sml-orch` fires the trap (serve restarted, lru_gen restored
# to the pinned baseline), and a later window resumes via the any-date
# existing-result SKIP.
#
# Usage (on the box):
#   sudo systemd-run --unit=sml-orch --collect \
#       bash /mnt/idxvol/scripts/seismic_testbed/sml_host_orchestrator.sh
set -u

REPO=/mnt/idxvol
PY=$REPO/.venv/bin/python3
DRIVER=$REPO/scripts/seismic_testbed/t23_convergence_ladder.py
EV=$REPO/data/eval_results
DATE=$(date +%Y%m%d)
LRU=/sys/kernel/mm/lru_gen/enabled
CELL_TIMEOUT="${CELL_TIMEOUT:-3600}"           # 60 min/cell (small-cap plateau/thrash cells run long)
WINDOW_DEADLINE_S="${WINDOW_DEADLINE_S:-7200}" # no new cell after 120 min
SML_RECLAIM_BYTES="${SML_RECLAIM_BYTES:-15032385536}"  # 14 GiB = footprint - hot set (pre-reg section 2, L3)
# Phase A' priority order (pre-reg section 4): cheap/informative first —
# L1 rescue pair at 16G, L3 mechanism check at 20G, then the L0 small-cap
# baseline ladder alternating arms. lever:arm:rungGiB:rep
CELLS="${CELLS:-L1:mglru:16:1 L1:classic:16:1 L3:classic:20:1 L0:mglru:20:1 L0:classic:18:1 L0:mglru:16:1 L0:classic:14:1}"
RUNLOG=$EV/_sml_runA_${DATE}.log
T0=$(date +%s)

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$RUNLOG"; }

[ "$(id -u)" = 0 ] || { echo "must run as root"; exit 1; }
[ -x "$PY" ] && [ -f "$DRIVER" ] || { echo "driver/venv missing"; exit 1; }

# D-sml-3 guard (a): single-live-instance lock. A re-spawn (e.g. systemd
# re-registering the transient unit during an unattended-upgrades daemon
# reload) exits WITHOUT touching sfu-serve, so it cannot re-stop the demo
# behind a running window. Runs before any serve/timer/lru mutation.
LOCK=/run/sml-orch.lock
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
    echo "[$(date '+%H:%M:%S')] REFUSING to start: live sml-orch instance PID $(cat "$LOCK") holds $LOCK — leaving sfu-serve untouched" | tee -a "$RUNLOG"
    exit 0
fi
echo $$ > "$LOCK"

# D-sml-3 guard (b): disable the apt maintenance timers for the window so an
# unattended upgrade cannot daemon-reload mid-run; restored in the trap.
APT_TIMERS="apt-daily.timer apt-daily-upgrade.timer"
APT_WAS_ACTIVE=""
for t in $APT_TIMERS; do
    if systemctl is-active "$t" >/dev/null 2>&1; then
        APT_WAS_ACTIVE="$APT_WAS_ACTIVE $t"
        systemctl stop "$t" 2>/dev/null || true
    fi
done
systemctl stop apt-daily.service apt-daily-upgrade.service 2>/dev/null || true

BASELINE_LRU="${BASELINE_LRU:-0x0007}"   # pinned (pre-reg section 3 / N1-N6); boot state not trusted
BOOT_LRU=$(cat "$LRU")
[ "$BOOT_LRU" = "$BASELINE_LRU" ] || log "WARNING: lru_gen at start is $BOOT_LRU, not pinned baseline $BASELINE_LRU"
log "phase A' start: deadline ${WINDOW_DEADLINE_S}s, cell timeout ${CELL_TIMEOUT}s, L3 reclaim ${SML_RECLAIM_BYTES}B, cells=[$CELLS]"

CELL_BG=""
restore() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$CELL_BG" ]; then
        kill "$CELL_BG" 2>/dev/null || true
        wait "$CELL_BG" 2>/dev/null || true
    fi
    if ! printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null; then
        echo y > "$LRU" 2>/dev/null || true
    fi
    systemctl start sfu-serve || systemctl restart sfu-serve || true
    for t in $APT_WAS_ACTIVE; do systemctl start "$t" 2>/dev/null || true; done
    [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ] && rm -f "$LOCK"
    log "RESTORED: lru_gen=$(cat "$LRU") sfu-serve=$(systemctl is-active sfu-serve || true) apt-timers=[${APT_WAS_ACTIVE:- none}] (exit rc=$rc)"
    touch "$EV/_sml_ALLDONE_${DATE}"
    exit "$rc"
}
trap restore EXIT INT TERM

systemctl stop sfu-serve
log "sfu-serve stopped for the window"
cd "$REPO"

for SPEC in $CELLS; do
    LEVER=${SPEC%%:*}; REST=${SPEC#*:}
    ARM=${REST%%:*}; REST=${REST#*:}
    G=${REST%%:*}; REP=${REST#*:}
    ELAPSED=$(( $(date +%s) - T0 ))
    if [ "$ELAPSED" -ge "$WINDOW_DEADLINE_S" ]; then
        log "DEADLINE: ${ELAPSED}s elapsed — not starting $SPEC (or anything after); resume in a later window"
        break
    fi
    # Lever -> environment + driver args. Set for EVERY cell (no inheritance
    # from the previous iteration); WANT_GATE is what N8 will verify on the
    # result JSON, so the check can never drift from what was exported.
    EXTRA_ARGS=""
    # SFU_SEISMIC_FEDERATION is a retriever-layer knob; the driver builds
    # HybridSeismicBackend directly, so pure-sequential is forced via the
    # hybrid's own knobs: signal=count + FLIP_N far above any pass's query
    # count (phase A'' run 1 defect: the FEDERATION env alone flipped
    # seq->par at query 3).
    unset SFU_SEISMIC_HYBRID_SIGNAL SFU_SEISMIC_HYBRID_FLIP_N
    case "$LEVER" in
        L0)  export SFU_SEISMIC_PREFLOOR_HOTSET=1; WANT_GATE=1 ;;
        L1)  export SFU_SEISMIC_PREFLOOR_HOTSET=0; WANT_GATE=0 ;;
        L3)  export SFU_SEISMIC_PREFLOOR_HOTSET=1; WANT_GATE=1
             EXTRA_ARGS="--postload-reclaim-bytes ${SML_RECLAIM_BYTES}" ;;
        L4)  export SFU_SEISMIC_PREFLOOR_HOTSET=1; WANT_GATE=1
             export SFU_SEISMIC_HYBRID_SIGNAL=count SFU_SEISMIC_HYBRID_FLIP_N=999999 ;;
        L41) export SFU_SEISMIC_PREFLOOR_HOTSET=0; WANT_GATE=0
             export SFU_SEISMIC_HYBRID_SIGNAL=count SFU_SEISMIC_HYBRID_FLIP_N=999999 ;;
        L43) export SFU_SEISMIC_PREFLOOR_HOTSET=1; WANT_GATE=1
             export SFU_SEISMIC_HYBRID_SIGNAL=count SFU_SEISMIC_HYBRID_FLIP_N=999999
             EXTRA_ARGS="--postload-reclaim-bytes ${SML_RECLAIM_BYTES}" ;;
        *)  log "CONFIG ERROR: unknown lever '$LEVER' in cell spec '$SPEC' — aborting window"
            exit 2 ;;
    esac
    LABEL="cap${G}g_rep${REP}"
    RESULT="data/eval_results/sml_${LEVER}_${ARM}_${LABEL}_${DATE}.json"
    CLOG="$EV/_sml_${LEVER}_${ARM}_${LABEL}_${DATE}.log"
    STATUS="$EV/_sml_${LEVER}_${ARM}_${LABEL}_${DATE}.status"
    # Resume must survive a date rollover: a completed cell from ANY prior
    # window (any date) skips, else a later-day resume re-runs all cells.
    EXISTING=$(ls "$EV"/sml_"${LEVER}"_"${ARM}"_"${LABEL}"_*.json 2>/dev/null | head -1)
    if [ -n "$EXISTING" ] && [ -s "$EXISTING" ]; then
        log "SKIP $LEVER/$ARM/$LABEL — result exists ($(basename "$EXISTING"))"; echo DONE > "$STATUS"; continue
    fi
    if [ "$ARM" = classic ]; then echo n > "$LRU"; else printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null || echo y > "$LRU"; fi
    sync
    echo 3 > /proc/sys/vm/drop_caches
    log "cell $LEVER/$ARM/$LABEL starting (elapsed ${ELAPSED}s, lru_gen $(cat "$LRU"), prefloor=$SFU_SEISMIC_PREFLOOR_HOTSET${EXTRA_ARGS:+, args:$EXTRA_ARGS})"
    # Backgrounded + wait so a systemctl-stop TERM runs the trap NOW: bash
    # defers traps while a foreground command runs, which killed the
    # stop-anytime restore mid-cell (phase A'' run 1 defect).
    systemd-run --scope --collect --quiet -p MemorySwapMax=0 -p "MemoryMax=${G}G" -- \
        timeout "$CELL_TIMEOUT" "$PY" "$DRIVER" \
            --arm "$ARM" --cap-label "cap${G}g" --phase A \
            $EXTRA_ARGS \
            --result-file "$REPO/$RESULT" >"$CLOG" 2>&1 &
    CELL_BG=$!
    wait "$CELL_BG"
    rc=$?
    CELL_BG=""
    if [ $rc -eq 0 ] && [ -s "$REPO/$RESULT" ]; then
        VIOLATION=""
        if ! grep -Eq "\"prefault_gate\"[[:space:]]*:[[:space:]]*\"${WANT_GATE}\"" "$REPO/$RESULT"; then
            VIOLATION="prefault_gate!=${WANT_GATE} (lever $LEVER)"
        fi
        case "$LEVER" in L4|L41|L43)
            if [ -z "$VIOLATION" ] && grep -q "FLIP seq→par" "$CLOG"; then
                VIOLATION="sequential federation gate ignored (seq→par flip in cell log)"
            fi ;;
        esac
        if [ -z "$VIOLATION" ] && { [ "$LEVER" = L3 ] || [ "$LEVER" = L43 ]; }; then
            FREED=$("$PY" -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
    r = d.get("postload_reclaim") or {}
    print(int(r.get("freed_bytes", -1)))
except Exception:
    print(-1)' "$REPO/$RESULT" 2>/dev/null)
            case "$FREED" in
                ''|*[!0-9]*) VIOLATION="postload_reclaim.freed_bytes missing/unparseable (got '${FREED}')" ;;
                *) [ "$FREED" -gt 1073741824 ] || VIOLATION="postload_reclaim.freed_bytes=${FREED} <= 1 GiB" ;;
            esac
        fi
        if [ -z "$VIOLATION" ]; then
            echo DONE > "$STATUS"; log "cell $LEVER/$ARM/$LABEL DONE"
        else
            mv "$REPO/$RESULT" "$REPO/${RESULT%.json}.PROTOVIOLATION.json"
            echo "PROTOVIOLATION" > "$STATUS"
            log "cell $LEVER/$ARM/$LABEL PROTOCOL VIOLATION: ${VIOLATION} — result quarantined, aborting window"
            exit 5
        fi
    else
        echo "FAIL($rc)" > "$STATUS"; log "cell $LEVER/$ARM/$LABEL FAIL rc=$rc (see $CLOG)"
    fi
done

log "phase A' window complete"
