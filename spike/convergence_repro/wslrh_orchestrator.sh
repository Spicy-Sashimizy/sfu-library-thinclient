#!/usr/bin/env bash
# WSL2 RE-HOST orchestrator — PREREGISTRATION_WSL2_REHOST.md §6 gap 3
# (2026-09-29). A t1d_wsl2_orchestrator.sh / t23b / sml clone that drives
# scripts/seismic_testbed/wslrh_convergence_ladder.py through the §3 lever
# arms on the §4 frozen rung list, under the §8 hard bars.
#
# WHERE IT RUNS (two cap mechanisms; CAP_MECH=auto picks the first that works):
#   docker   — the R2 mechanism (r2_host_orchestrator.sh): Git Bash on the
#              WINDOWS HOST with Docker Desktop; each cell is a memory-capped
#              SIBLING container (--memory=G --memory-swap=G forbids swap)
#              bind-mounting the repo; lru_gen / drop_caches go through a
#              privileged throwaway alpine (sysfs is VM-global on WSL2).
#   systemd  — root in the Ubuntu WSL2 distro (the t1d_wsl2 mechanism):
#              systemd-run --scope -p MemoryMax=G -p MemorySwapMax=0 around the
#              venv driver; REPO must be on a local ext4 path (NOT /mnt/*:
#              drvfs/9p mmap/majflt semantics are not the object of study).
#   The dev container itself has NO cgroup write access, no docker and no
#   systemd-run: the startup gate below detects that and ABORTS before any
#   cell — an uncapped cell must never run silently (a cell whose
#   memory.max readback is not the requested cap is also quarantined by the
#   per-cell protocol check, as a second line of defence).
#
# FROZEN INPUTS (do not edit between freeze and verdict):
#   §4 rung list        9 10 11 12 13 14 16 18 22 GB (N1: anything else is a
#                       CONFIG ERROR; hard ceiling 24 GB never reached)
#   §3 arms             L0 (baseline, PREFLOOR_HOTSET=1), F5 (--f5-release-except
#                       <sidecar>), L3 (--postload-reclaim-bytes N, bytes carried
#                       in the cell spec so W7 can set them to what F5 released)
#   N5 CELL_TIMEOUT     2400 s, fixed here, NO env override; a shed cell keeps
#                       its .log/.status as the readout and is never retried
#   N4 restore target   lru_gen=0x0007 on every exit path (trap), asserted
#
# CELL SPEC   lever:arm:capGB:rep[:bytes]      e.g. L0:classic:12:1
#                                                   F5:classic:16:1
#                                                   L3:classic:12:1:9300000000
#   CELLS is taken IN THE ORDER GIVEN (the freeze commit writes the seed-20260925
#   permutation into it; this script never reorders). Default = the §5
#   calibration window (single cells: anchors 10/13, control 22, F5 mechanism
#   check 16, wall budgeting 11/12).
#
# PER CELL: deadline shed -> any-date SKIP resume -> arm toggle (asserted) ->
#   drop_caches (cold-start purity) -> capped driver -> protocol verification
#   (N8: probe, lever, prefault_gate, arm + lru_gen readback, memory.max
#   readback, F5 write_status/scope, L3 requested_bytes) with
#   quarantine-and-abort on mismatch -> §8 N6 swap check (VmSwap>0 at any pass
#   boundary => .SWAPQUARANTINE.json, excluded from every bar; second
#   occurrence aborts the window).
#
# Usage:
#   Windows host (Git Bash):  bash spike/convergence_repro/wslrh_orchestrator.sh
#   WSL2 distro:  sudo systemd-run --unit=wslrh-orch --collect -p TimeoutStopSec=300 \
#                     bash /path/to/repo/spike/convergence_repro/wslrh_orchestrator.sh
#   DRY_RUN=1 bash spike/convergence_repro/wslrh_orchestrator.sh   # parse + plan only,
#                     no gate, no writes, no cell (safe anywhere, incl. the dev container)
#   Env: CELLS, CAP_MECH=auto|docker|systemd, WINDOW_DEADLINE_S, F5_SIDECAR,
#        HOSTREPO/CREPO/IMG (docker), REPO/PY (systemd), FORCE_LOCK=1
set -u

case "${1:-}" in
    -h|--help) sed -n '2,52p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

# ------------------------------------------------------------- frozen inputs
RUNGS_ALLOWED=" 9 10 11 12 13 14 16 18 22 "
CAP_CEILING_GB=24
CELL_TIMEOUT=2400
EXPECTED_LRU=0x0007
F5_SIDECAR="${F5_SIDECAR:-hotset_hot50_1.6gb.json}"
CELLS="${CELLS:-L0:classic:10:1 L0:classic:13:1 L0:classic:22:1 F5:classic:16:1 L0:classic:11:1 L0:classic:12:1}"
WINDOW_DEADLINE_S="${WINDOW_DEADLINE_S:-14400}"
DRY_RUN="${DRY_RUN:-0}"
CAP_MECH="${CAP_MECH:-auto}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$(cd "$HERE/../.." && pwd)}"
CREPO="${CREPO:-/workspaces/sfu-library-thinclient}"
HOSTREPO="${HOSTREPO:-C:/Users/<user>/claudebox-projects/sfu-library-thinclient}"
IMG="${IMG:-claudebox-sfu-library-thinclient-app}"
PY="${PY:-$REPO/.venv/bin/python3}"
DRIVER_REL=scripts/seismic_testbed/wslrh_convergence_ladder.py
EV="$REPO/data/eval_results"
DATE=$(date +%Y%m%d)
LRU=/sys/kernel/mm/lru_gen/enabled
RUNLOG="$EV/_wslrh_run_${DATE}.log"
LOCK="$EV/_wslrh_orch.lock"
T0=$(date +%s)
SWAP_EVENTS=0
CELL_BG=""
CELL_NAME=""

log() {
    if [ "$DRY_RUN" = 1 ]; then echo "[$(date '+%H:%M:%S')] $*"
    else echo "[$(date '+%H:%M:%S')] $*" | tee -a "$RUNLOG"; fi
}
die() { echo "REFUSING: $1" >&2; exit "${2:-1}"; }

# ------------------------------------------------------------- spec validation
# Done for EVERY cell before anything runs: a bad spec in position 7 must not
# be discovered after six cells (each up to 40 min) have already run.
validate_spec() {
    local spec=$1 lever arm g rep bytes rest
    lever=${spec%%:*}; rest=${spec#*:}
    arm=${rest%%:*}; rest=${rest#*:}
    g=${rest%%:*}; rest=${rest#*:}
    rep=${rest%%:*}
    bytes=""
    [ "$rep" != "$rest" ] && bytes=${rest#*:}
    case "$lever" in L0|F5|L3) ;; *) echo "unknown lever '$lever' in '$spec' (L0|F5|L3)"; return 1 ;; esac
    case "$arm" in classic|mglru) ;; *) echo "unknown arm '$arm' in '$spec' (classic|mglru)"; return 1 ;; esac
    case "$g" in ''|*[!0-9]*) echo "cap '$g' in '$spec' is not an integer GB"; return 1 ;; esac
    case "$RUNGS_ALLOWED" in *" $g "*) ;; *) echo "cap ${g} GB in '$spec' is not on the §4 frozen rung list [$(echo $RUNGS_ALLOWED)] (N1)"; return 1 ;; esac
    [ "$g" -le "$CAP_CEILING_GB" ] || { echo "cap ${g} GB in '$spec' exceeds the ${CAP_CEILING_GB} GB hard ceiling (N1)"; return 1; }
    case "$rep" in ''|*[!0-9]*) echo "replicate '$rep' in '$spec' is not an integer"; return 1 ;; esac
    if [ "$lever" = L3 ]; then
        case "$bytes" in ''|*[!0-9]*|0) echo "L3 cell '$spec' needs a positive byte count as its 5th field (lever:arm:cap:rep:bytes)"; return 1 ;; esac
    elif [ -n "$bytes" ]; then
        echo "cell '$spec' carries a byte field but is not L3"; return 1
    fi
    return 0
}

BAD=""
for SPEC in $CELLS; do
    MSG=$(validate_spec "$SPEC") || BAD="$BAD
  $MSG"
done
[ -z "$BAD" ] || die "CONFIG ERROR in CELLS:$BAD" 2

# ------------------------------------------------------------- cap mechanism gate
have_docker() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }
have_systemd() { [ "$(id -u)" = 0 ] && command -v systemd-run >/dev/null 2>&1 && [ -w "$LRU" ] && [ -w /sys/fs/cgroup ]; }

if [ "$DRY_RUN" != 1 ]; then
    if [ "$CAP_MECH" = auto ]; then
        if have_docker; then CAP_MECH=docker
        elif have_systemd; then CAP_MECH=systemd
        else
            cat >&2 <<EOF
REFUSING: no memory-cap mechanism is available here, so no capped cell can run.
  docker      : $(command -v docker >/dev/null 2>&1 && echo "CLI present but 'docker info' failed (no daemon socket)" || echo missing)
  systemd-run : $(command -v systemd-run >/dev/null 2>&1 && echo present || echo missing)
  root        : $([ "$(id -u)" = 0 ] && echo yes || echo "no (uid $(id -u))")
  $LRU writable : $([ -w "$LRU" ] && echo yes || echo no)
  /sys/fs/cgroup writable : $([ -w /sys/fs/cgroup ] && echo yes || echo no)
This is the dev container's normal state (read-only cgroups, no docker daemon,
no systemd). Run from the Windows host with Docker Desktop (CAP_MECH=docker) or
as root inside the WSL2 distro (CAP_MECH=systemd). An uncapped cell is not a
ladder cell and is never run silently. DRY_RUN=1 plans without running.
EOF
            exit 1
        fi
    fi
    case "$CAP_MECH" in
        docker)
            have_docker || die "CAP_MECH=docker but 'docker info' fails" 1
            export MSYS_NO_PATHCONV=1
            docker image inspect "$IMG" >/dev/null 2>&1 || die "docker image $IMG not found (the app image the cell runs in)" 1
            [ -f "$HOSTREPO/$DRIVER_REL" ] || die "driver not found at HOSTREPO=$HOSTREPO/$DRIVER_REL" 1
            ;;
        systemd)
            have_systemd || die "CAP_MECH=systemd needs root + systemd-run + writable $LRU and /sys/fs/cgroup" 1
            case "$REPO" in /mnt/*) die "REPO=$REPO is on drvfs/9p — invalid for the experiment under CAP_MECH=systemd (mmap/majflt semantics); use an ext4 path or CAP_MECH=docker" 1 ;; esac
            [ -x "$PY" ] || die "venv python missing at $PY" 1
            [ -f "$REPO/$DRIVER_REL" ] || die "driver missing at $REPO/$DRIVER_REL" 1
            ;;
        *) die "CAP_MECH=$CAP_MECH is not auto|docker|systemd" 2 ;;
    esac
fi

# sysfs access is mechanism-dependent: direct as root in the distro, via a
# privileged throwaway container from the Windows host (VM-global sysfs).
sys_read() {
    case "$CAP_MECH" in
        docker) docker run --rm --privileged alpine sh -c "cat $1" 2>/dev/null ;;
        *) cat "$1" 2>/dev/null ;;
    esac
}
sys_write() {
    case "$CAP_MECH" in
        docker) docker run --rm --privileged alpine sh -c "printf '%s\n' '$2' > $1" 2>/dev/null ;;
        *) printf '%s\n' "$2" > "$1" 2>/dev/null ;;
    esac
}
drop_caches() {
    case "$CAP_MECH" in
        docker) docker run --rm --privileged alpine sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' ;;
        *) sync; echo 3 > /proc/sys/vm/drop_caches ;;
    esac
}
lru_arm_of() { case "$1" in 0x0000|0|n) echo classic ;; ''|absent) echo absent ;; *) echo mglru ;; esac; }

# ------------------------------------------------------------- dry run: plan only
if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN (nothing is written, toggled or run): mech=$CAP_MECH cells=[$CELLS] deadline=${WINDOW_DEADLINE_S}s cell_timeout=${CELL_TIMEOUT}s f5_sidecar=$F5_SIDECAR"
fi

# ------------------------------------------------------------- N3 lock + N4 trap
if [ "$DRY_RUN" != 1 ]; then
    mkdir -p "$EV"
    if [ -e "$LOCK" ]; then
        OLDPID=$(cat "$LOCK" 2>/dev/null)
        if kill -0 "$OLDPID" 2>/dev/null; then die "live wslrh-orch PID $OLDPID holds $LOCK (N3 single-window exclusivity)" 0; fi
        [ "${FORCE_LOCK:-0}" = 1 ] || die "stale-looking $LOCK (PID $OLDPID not alive here; may be alive on the other side of the container boundary). Verify no page-cache-heavy run is in flight against data/thinclient_index, then FORCE_LOCK=1 (N3)" 1
    fi
    echo $$ > "$LOCK"

    BOOT_LRU=$(sys_read "$LRU")
    [ -n "$BOOT_LRU" ] || { rm -f "$LOCK"; die "cannot read $LRU through mech=$CAP_MECH (MGLRU absent or sysfs unreachable)" 1; }
    if [ "$BOOT_LRU" != "$EXPECTED_LRU" ]; then
        log "WARNING: lru_gen at start is $BOOT_LRU, not the clean-boot $EXPECTED_LRU — residue from an aborted run; restore target stays $EXPECTED_LRU (N4)"
    fi
    SWAP_TOTAL_KB=$(grep -E '^SwapTotal:' /proc/meminfo 2>/dev/null | awk '{print $2}')
    log "wslrh start: mech=$CAP_MECH deadline=${WINDOW_DEADLINE_S}s cell_timeout=${CELL_TIMEOUT}s (N5, fixed) boot lru_gen=$BOOT_LRU restore=$EXPECTED_LRU host SwapTotal=${SWAP_TOTAL_KB:-?}kB (N6 quarantine active) f5_sidecar=$F5_SIDECAR cells=[$CELLS]"
    log "NOTE: lru_gen + drop_caches are VM-GLOBAL on WSL2 (docker-desktop shares this kernel); run windows at a quiet time"

    restore() {
        rc=$?
        trap - EXIT INT TERM
        if [ -n "$CELL_BG" ]; then
            [ "$CAP_MECH" = docker ] && [ -n "$CELL_NAME" ] && docker kill "$CELL_NAME" >/dev/null 2>&1
            kill "$CELL_BG" 2>/dev/null || true; wait "$CELL_BG" 2>/dev/null || true
        fi
        sys_write "$LRU" "$EXPECTED_LRU" || sys_write "$LRU" 7 || true
        NOW=$(sys_read "$LRU")
        [ "$(lru_arm_of "$NOW")" = mglru ] || log "RESTORE DEFECT (N4): lru_gen reads '$NOW' after restore attempts — fix by hand: echo 7 > $LRU"
        [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ] && rm -f "$LOCK"
        log "RESTORED: lru_gen=$NOW swap_quarantines=$SWAP_EVENTS (exit rc=$rc)"
        touch "$EV/_wslrh_ALLDONE_${DATE}"
        exit "$rc"
    }
    trap restore EXIT INT TERM
fi

# ------------------------------------------------------------- the cells
for SPEC in $CELLS; do
    LEVER=${SPEC%%:*}; REST=${SPEC#*:}
    ARM=${REST%%:*}; REST=${REST#*:}
    G=${REST%%:*}; REST=${REST#*:}
    REP=${REST%%:*}
    BYTES=""; [ "$REP" != "$REST" ] && BYTES=${REST#*:}

    ELAPSED=$(( $(date +%s) - T0 ))
    if [ "$ELAPSED" -ge "$WINDOW_DEADLINE_S" ]; then
        log "DEADLINE: ${ELAPSED}s elapsed — not starting $SPEC (or anything after); resume later (any-date SKIP)"
        break
    fi

    EXTRA_ARGS=""
    case "$LEVER" in
        L0) ;;
        F5) EXTRA_ARGS="--f5-release-except $F5_SIDECAR" ;;
        L3) EXTRA_ARGS="--postload-reclaim-bytes $BYTES" ;;
    esac
    LABEL="cap${G}g_rep${REP}"
    STEM="wslrh_${LEVER}_${ARM}_${LABEL}"
    RESULT="data/eval_results/${STEM}_${DATE}.json"
    CLOG="$EV/_${STEM}_${DATE}.log"
    STATUS="$EV/_${STEM}_${DATE}.status"
    CAP_BYTES=$(( G * 1073741824 ))
    case "$ARM" in classic) WANT_LRU=0x0000 ;; *) WANT_LRU=$EXPECTED_LRU ;; esac

    # Any-date SKIP resume: a completed (non-quarantined) cell from ANY prior
    # window skips. Quarantined files end in .PROTOVIOLATION.json /
    # .SWAPQUARANTINE.json and do not match the 8-digit date glob.
    EXISTING=$(ls "$EV"/"${STEM}"_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].json 2>/dev/null | head -1)
    if [ -n "$EXISTING" ] && [ -s "$EXISTING" ]; then
        log "SKIP $STEM — result exists ($(basename "$EXISTING"))"
        [ "$DRY_RUN" = 1 ] || echo DONE > "$STATUS"
        continue
    fi

    if [ "$DRY_RUN" = 1 ]; then
        log "PLAN $STEM: arm=$ARM (lru_gen -> $WANT_LRU) cap=${G}G (memory.max must read $CAP_BYTES) SFU_SEISMIC_PREFLOOR_HOTSET=1 driver args: --arm $ARM --cap-label cap${G}g --replicate $REP $EXTRA_ARGS --result-file $RESULT"
        continue
    fi

    if [ "$ARM" = classic ]; then sys_write "$LRU" n; else sys_write "$LRU" "$EXPECTED_LRU" || sys_write "$LRU" y; fi
    NOW_LRU=$(sys_read "$LRU")
    if [ "$(lru_arm_of "$NOW_LRU")" != "$ARM" ]; then
        log "ARM TOGGLE FAILED: $ARM cell but lru_gen reads '$NOW_LRU' (boot was $BOOT_LRU) — aborting window rather than mislabelling a cell"
        exit 3
    fi
    drop_caches || { log "drop_caches FAILED — aborting window (the next cell would inherit this one's residency)"; exit 4; }
    log "cell $STEM starting (elapsed ${ELAPSED}s, lru_gen $NOW_LRU, cap ${G}G${EXTRA_ARGS:+, args: $EXTRA_ARGS})"

    # Backgrounded + wait so a TERM (systemctl stop / Ctrl-C) runs the trap NOW
    # instead of after the cell (bash defers traps during a foreground command).
    case "$CAP_MECH" in
        docker)
            CELL_NAME="${STEM}_${DATE}"
            # shellcheck disable=SC2086
            docker run --rm --name "$CELL_NAME" \
                --memory="${G}g" --memory-swap="${G}g" \
                -v "${HOSTREPO}:${CREPO}" -w "${CREPO}" \
                -e SFU_SEISMIC_PREFLOOR_HOTSET=1 \
                "$IMG" timeout "$CELL_TIMEOUT" .venv/bin/python3 "$DRIVER_REL" \
                    --arm "$ARM" --cap-label "cap${G}g" --replicate "$REP" \
                    $EXTRA_ARGS --result-file "$RESULT" >"$CLOG" 2>&1 &
            ;;
        systemd)
            # shellcheck disable=SC2086
            systemd-run --scope --collect --quiet -p MemorySwapMax=0 -p "MemoryMax=${G}G" -- \
                timeout "$CELL_TIMEOUT" env SFU_SEISMIC_PREFLOOR_HOTSET=1 "$PY" "$REPO/$DRIVER_REL" \
                    --arm "$ARM" --cap-label "cap${G}g" --replicate "$REP" \
                    $EXTRA_ARGS --result-file "$REPO/$RESULT" >"$CLOG" 2>&1 &
            ;;
    esac
    CELL_BG=$!
    wait "$CELL_BG"
    rc=$?
    CELL_BG=""; CELL_NAME=""

    if [ $rc -eq 124 ]; then
        echo "SHED(timeout ${CELL_TIMEOUT}s)" > "$STATUS"
        log "cell $STEM SHED at the ${CELL_TIMEOUT}s cell timeout — recorded as the readout (N5), never retried at a raised timeout"
        continue
    fi
    if [ $rc -ne 0 ] || [ ! -s "$REPO/$RESULT" ]; then
        echo "FAIL($rc)" > "$STATUS"; log "cell $STEM FAIL rc=$rc (3=empty results, 4=arm mismatch, 5=F5 sidecar; see $CLOG)"
        continue
    fi

    # N8 protocol pin — every field the cell must carry, verified on the file.
    VIOLATION=""
    chk() { grep -Eq "$1" "$REPO/$RESULT" || VIOLATION="${VIOLATION:+$VIOLATION; }$2"; }
    chk '"probe": "wslrh_convergence_ladder"'          "probe!=wslrh_convergence_ladder"
    chk "\"lever\": \"$LEVER\""                         "lever!=$LEVER"
    chk '"prefault_gate": "1"'                          "prefault_gate!=1"
    chk "\"arm\": \"$ARM\""                             "arm!=$ARM"
    chk "\"lru_gen_enabled\": \"$WANT_LRU\""            "lru_gen readback!=$WANT_LRU"
    chk "\"cgroup_memory_max\": \"$CAP_BYTES\""         "memory.max readback!=$CAP_BYTES (cap did not land)"
    case "$LEVER" in
        F5) chk '"write_status": "ok"'                  "f5_release.write_status!=ok"
            chk '"scope": "all_slabs"'                  "f5 scope!=all_slabs (pre-fix .so answered — the 2026-07-14 NULL scope; §6 gap 1 not closed on the served binary)"
            grep -Eq '"released_bytes": 0,' "$REPO/$RESULT" && VIOLATION="${VIOLATION:+$VIOLATION; }f5 released_bytes=0" ;;
        L3) chk "\"requested_bytes\": $BYTES"           "postload_reclaim.requested_bytes!=$BYTES"
            grep -Eq '"freed_bytes": null' "$REPO/$RESULT" && VIOLATION="${VIOLATION:+$VIOLATION; }postload_reclaim.freed_bytes null (memory.current unreadable)" ;;
    esac
    if [ -n "$VIOLATION" ]; then
        mv "$REPO/$RESULT" "$REPO/${RESULT%.json}.PROTOVIOLATION.json"
        echo "PROTOVIOLATION" > "$STATUS"
        log "cell $STEM PROTOCOL VIOLATION: $VIOLATION — quarantined as $(basename "${RESULT%.json}").PROTOVIOLATION.json, aborting window (N8)"
        exit 5
    fi

    # §8 N6 swap quarantine: VmSwap>0 at any pass boundary measures the swap
    # subsystem, not page-cache reclaim. First occurrence: quarantine and go
    # on; second: abort the window.
    if grep -Eq '"swap_confounded": true' "$REPO/$RESULT"; then
        SWAP_EVENTS=$(( SWAP_EVENTS + 1 ))
        mv "$REPO/$RESULT" "$REPO/${RESULT%.json}.SWAPQUARANTINE.json"
        echo "SWAPQUARANTINE" > "$STATUS"
        log "cell $STEM SWAP-CONFOUNDED (VmSwap>0 at a pass boundary) — quarantined as $(basename "${RESULT%.json}").SWAPQUARANTINE.json, excluded from every bar (N6; occurrence $SWAP_EVENTS)"
        if [ "$SWAP_EVENTS" -ge 2 ]; then
            log "second swap quarantine in one window — aborting (N6)"
            exit 6
        fi
        continue
    fi

    echo DONE > "$STATUS"; log "cell $STEM DONE -> $RESULT"
done

log "wslrh window complete (swap quarantines: $SWAP_EVENTS)"
