#!/usr/bin/env bash
# TIER-1d convergence-repro orchestrator — LOCAL WSL2 FLAVOR. Runs as root in
# the Windows host's Ubuntu WSL2 distro (NOT in a devcontainer, NOT on the OCI
# box). PREREGISTRATION_TIER1D.md §4/§6-gap-4; a t1c_host_orchestrator.sh clone
# with the OCI-only window discipline dropped and WSL2 validity guards added.
#
# Differences from t1c_host_orchestrator.sh (each is deliberate):
#   * NO sfu-serve stop/restore — the service does not exist on this host.
#     INSTEAD: the lru_gen toggle and drop_caches here are GLOBAL to the whole
#     WSL2 VM, docker-desktop containers included. Run windows at a quiet time;
#     recommended first: Stop-NonAlwaysOnContainers.ps1 on the Windows side.
#   * apt-guard KEPT (Ubuntu distro has the timers; freeze+restore verbatim).
#   * MGLRU preflight failure here usually means the CUSTOM KERNEL is not
#     booted — check `kernel=` in C:\Users\<user>\.wslconfig + `wsl --shutdown`.
#     Stock Microsoft WSL2 kernels have # CONFIG_LRU_GEN is not set.
#   * .wslconfig HYGIENE GATE (validity, pre-reg §"what it would take" item 4):
#     Hyper-V ballooning/page-reporting reclaims guest pages behind the kernel's
#     back — a direct confound for a paging experiment. Refuses to run unless
#     [wsl2] has fixed memory=, autoMemoryReclaim absent-or-disabled, and
#     pageReporting=false. Override (recorded in the runlog) with
#     ALLOW_UNCLEAN_WSLCONFIG=1 for smoke tests only — never for graded cells.
#   * DATADIR must be on the distro ext4 rootfs (default /var/tmp/t1d_scratch).
#     /mnt/* (drvfs/9p) is REFUSED: mmap/mincore/majflt semantics there do not
#     model a local filesystem, which is the entire object of study.
#   * BASELINE_LRU defaults to the BOOT value read live from $LRU at start, so
#     the fleet's everyday reclaim behavior is restored on exit whatever it is.
#     MEASURED 2026-09-05 on the active kernel 6.18.33.2-microsoft-standard-WSL2+
#     (CONFIG_LRU_GEN=y, CONFIG_LRU_GEN_ENABLED=y, CONFIG_LRU_GEN_WALKS_MMU=y):
#     $LRU reads 0x0007 at boot -- MGLRU is compiled in AND default-ON. So the
#     fleet's everyday reclaim on this box IS MGLRU, and the CLASSIC arm is the
#     one that deviates from production (the reverse of earlier drafts, which
#     assumed a default-off 0x0000 boot). Consequences, all handled below:
#       - a start value of 0x0000 is no longer "normal": it is RESIDUE from an
#         aborted classic cell, so EXPECTED_LRU (default 0x0007) is checked and
#         an unexplained start value is NOT silently adopted as the restore
#         target (a crashed run would otherwise pin the box to classic forever);
#       - the restore fallback is direction-aware: `echo n` only for a zero
#         baseline, else `echo 7`. (`echo y` sets ALL caps and reads back
#         0x0007, so it is only ever right for a full-caps baseline; the numeric
#         write is primary and this is the last-resort path.)
#       - the per-arm toggle is now ASSERTED after the write: with a 0x0007
#         boot, a failed `echo n` leaves a "classic" cell running under MGLRU,
#         which silently destroys the arm comparison. Previously (0x0000 boot)
#         the same failure mode was masked for the classic arm.
#   * CELL_TIMEOUT default raised to 1800 s (§4: Tier-1c's 900 s truncated
#     converging capped cells before a steady floor was written).
#   * Cell spec gains an optional skew tail (§2/§6 gap 1):
#         arm:fracPct:capGiB:seed[:skew-spec]
#     where skew-spec is passed verbatim to the driver as --skew (e.g.
#     mglru:92:4:1729:hotset:0.20:0.80 → --skew hotset:0.20:0.80). Skew cells
#     require the t1d driver.
#   * The tail may carry flag prefixes `fa:` (S-faultaround, §3.4 / §6 gap 2)
#     and/or `wl:` (warm-L residue, T1d-15):
#         arm:fracPct:capGiB:seed[:fa][:wl][:skew-spec]
#     e.g. classic:92:1.5:2027:fa:hotset:0.20:0.80 → --fault-around
#     --skew hotset:0.20:0.80; classic:92:6:2027:wl:hotset:0.20:0.80 →
#     --warm-l --skew hotset:0.20:0.80 (L touched as a load-time residue
#     before R is seeded — the inversion mechanism's precondition, per the
#     T1d-13 no-residue finding). Fault-around cells have no seeded deficit
#     (MADV_NORMAL readahead makes the residency seed inoperative — pre-reg
#     §6 gap 2), so their identity is not applicable and they CANNOT run
#     under STRICT_SOUNDNESS=1 (config error, caught before any cell runs);
#     they are judged on the steady floor under the cap.
#   * Soundness identity (pass-1 majflt == seed deficit) is a WARN, not an
#     abort, unless STRICT_SOUNDNESS=1 — per bar T1d-5 the identity gates only
#     UNCAPPED validation cells; capped cells are judged on the floor
#     trajectory. Protocol-tag mismatch still quarantines and aborts.
#
# DRIVER selection: defaults to t1d_cell.py; if absent (harness gap §6-1 not
# yet closed) falls back to t1c_cell.py with a loud notice so the WSL2 window
# machinery can be smoke-tested with uniform-access cells today.
#
# Usage (from the Ubuntu WSL2 distro):
#   sudo systemd-run --unit=t1d-orch --collect -p TimeoutStopSec=300 \
#       bash /mnt/c/Users/<user>/claudebox-projects/sfu-library-thinclient/spike/convergence_repro/t1d_wsl2_orchestrator.sh
#   (plain `sudo bash .../t1d_wsl2_orchestrator.sh` also works for attended runs)
set -u

REPO="${REPO:-/mnt/c/Users/<user>/claudebox-projects/sfu-library-thinclient}"
PY="${PY:-python3}"
SPIKE=$REPO/spike/convergence_repro
if [ -n "${DRIVER:-}" ]; then :;
elif [ -f "$SPIKE/t1d_cell.py" ]; then DRIVER=$SPIKE/t1d_cell.py
else DRIVER=$SPIKE/t1c_cell.py; fi
case "$DRIVER" in *t1d_cell.py) PROTOCOL=tier1d ;; *) PROTOCOL=tier1c ;; esac
EV=$REPO/data/eval_results
DATADIR="${DATADIR:-/var/tmp/t1d_scratch}"
DATE=$(date +%Y%m%d)
LRU=/sys/kernel/mm/lru_gen/enabled
WSLCONFIG="${WSLCONFIG:-/mnt/c/Users/<user>/.wslconfig}"
R_MIB="${R_MIB:-5120}"
L_MIB="${L_MIB:-1792}"
PASSES="${PASSES:-12}"
CELL_TIMEOUT="${CELL_TIMEOUT:-1800}"           # §4: converging capped cells must finish (t1c's 900s truncated them)
WINDOW_DEADLINE_S="${WINDOW_DEADLINE_S:-5400}" # no new cell after 90 min
# Default matrix = §4 calibration seed points only; the real calibration CELLS
# are supplied by the window runner once t1d_cell.py lands (skew tails per §2).
CELLS="${CELLS:-classic:92:4:1729 mglru:92:4:1729}"
RUNLOG=$EV/_t1d_runWSL2_${DATE}.log
T0=$(date +%s)

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$RUNLOG"; }

[ "$(id -u)" = 0 ] || { echo "must run as root (wsl -u root, or sudo from the distro)"; exit 1; }
mkdir -p "$EV"
command -v "$PY" >/dev/null || { echo "python3 missing"; exit 1; }
"$PY" -c 'import numpy' 2>/dev/null || { echo "numpy missing for $PY (apt-get install python3-numpy)"; exit 1; }
[ -f "$DRIVER" ] || { echo "driver missing: $DRIVER"; exit 1; }
[ "$PROTOCOL" = tier1d ] || echo "NOTICE: t1d_cell.py absent — smoke-test mode with t1c_cell.py (protocol tier1c, no skew cells)"
[ -e "$LRU" ] || { echo "no $LRU — MGLRU absent. On WSL2 this means the custom kernel is not booted: check kernel= in C:\\Users\\<user>\\.wslconfig, then wsl --shutdown and relaunch."; exit 1; }
case "$DATADIR" in /mnt/*) echo "DATADIR=$DATADIR is on drvfs/9p — invalid for the experiment; use the ext4 rootfs (default /var/tmp/t1d_scratch)"; exit 1 ;; esac

# --- .wslconfig hygiene gate (validity) ---
WSLCFG_BAD=""
if [ -f "$WSLCONFIG" ]; then
    CFG=$(sed 's/\r$//; s/[[:space:]]//g' "$WSLCONFIG" | grep -v '^#')
    echo "$CFG" | grep -qi '^memory=' || WSLCFG_BAD="$WSLCFG_BAD no-fixed-memory="
    if echo "$CFG" | grep -qi '^autoMemoryReclaim=' && ! echo "$CFG" | grep -qi '^autoMemoryReclaim=disabled'; then
        WSLCFG_BAD="$WSLCFG_BAD autoMemoryReclaim-active"
    fi
    echo "$CFG" | grep -qi '^pageReporting=false' || WSLCFG_BAD="$WSLCFG_BAD pageReporting-not-false"
else
    WSLCFG_BAD="wslconfig-not-found-at-$WSLCONFIG"
fi
if [ -n "$WSLCFG_BAD" ]; then
    if [ "${ALLOW_UNCLEAN_WSLCONFIG:-0}" = 1 ]; then
        log "WARNING: unclean .wslconfig [$WSLCFG_BAD] — ALLOW_UNCLEAN_WSLCONFIG=1 override; cells from this window are SMOKE-TEST ONLY, not gradable"
    else
        echo "REFUSING: .wslconfig fails experiment hygiene [$WSLCFG_BAD]."
        echo "Required in [wsl2]: fixed memory=, autoMemoryReclaim=disabled (or absent), pageReporting=false; then wsl --shutdown."
        echo "Smoke-test override: ALLOW_UNCLEAN_WSLCONFIG=1"
        exit 1
    fi
fi

LOCK=/run/t1d-orch.lock
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
    echo "[$(date '+%H:%M:%S')] REFUSING: live t1d-orch PID $(cat "$LOCK") holds $LOCK" | tee -a "$RUNLOG"
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

# Clean-boot value of $LRU on the active custom kernel (LRU_GEN_ENABLED=y ->
# 0x0007). Anything else at start is residue from an aborted run, NOT the
# fleet's everyday setting, and must not become the restore target by default.
EXPECTED_LRU="${EXPECTED_LRU:-0x0007}"
BASELINE_EXPLICIT=${BASELINE_LRU+set}
BOOT_LRU=$(cat "$LRU")
BASELINE_LRU="${BASELINE_LRU:-$BOOT_LRU}"
if [ "$BOOT_LRU" != "$EXPECTED_LRU" ]; then
    if [ -n "${BASELINE_EXPLICIT:-}" ]; then
        log "WARNING: lru_gen at start is $BOOT_LRU, not the clean-boot value $EXPECTED_LRU — likely residue from an aborted run; restoring to the EXPLICIT BASELINE_LRU=$BASELINE_LRU"
    else
        log "WARNING: lru_gen at start is $BOOT_LRU, not the clean-boot value $EXPECTED_LRU — treating as RESIDUE from an aborted run; restore target forced to $EXPECTED_LRU (override: BASELINE_LRU=$BOOT_LRU)"
        BASELINE_LRU=$EXPECTED_LRU
    fi
fi
# MGLRU min_ttl_ms (T1d-16): a WINDOW-level knob (sysfs is VM-global, so it
# cannot vary per cell inside one window). When MIN_TTL_MS is set, every cell
# in this window runs under it, cell labels gain a _ttl<ms> suffix so results
# never collide with min_ttl=0 cells, and the boot value is restored in the
# trap. Only meaningful for mglru-arm cells (classic ignores lru_gen aging).
MINTTL_PATH=/sys/kernel/mm/lru_gen/min_ttl_ms
BOOT_MINTTL=$(cat "$MINTTL_PATH" 2>/dev/null || echo "")
if [ -n "${MIN_TTL_MS:-}" ]; then
    if [ -z "$BOOT_MINTTL" ]; then
        log "CONFIG ERROR: MIN_TTL_MS=$MIN_TTL_MS requested but $MINTTL_PATH is absent on this kernel"
        exit 2
    fi
    echo "$MIN_TTL_MS" > "$MINTTL_PATH"
    NOW_MINTTL=$(cat "$MINTTL_PATH")
    if [ "$NOW_MINTTL" != "$MIN_TTL_MS" ]; then
        log "CONFIG ERROR: min_ttl_ms write did not take ($NOW_MINTTL != $MIN_TTL_MS)"
        exit 2
    fi
    log "min_ttl_ms=$MIN_TTL_MS for this window (boot value $BOOT_MINTTL, restored on exit)"
fi

log "tier1d(WSL2) start: deadline ${WINDOW_DEADLINE_S}s, cell timeout ${CELL_TIMEOUT}s, R=${R_MIB}MiB L=${L_MIB}MiB passes=${PASSES}, driver=$(basename "$DRIVER") protocol=$PROTOCOL, boot lru_gen=$BOOT_LRU (restore target $BASELINE_LRU)${MIN_TTL_MS:+, min_ttl_ms=$MIN_TTL_MS}, cells=[$CELLS]"
log "NOTE: lru_gen + drop_caches are VM-GLOBAL (docker-desktop shares this kernel); run windows at a quiet time"

CELL_BG=""
restore() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$CELL_BG" ]; then kill "$CELL_BG" 2>/dev/null || true; wait "$CELL_BG" 2>/dev/null || true; fi
    printf '%s\n' "$BASELINE_LRU" > "$LRU" 2>/dev/null || {
        case "$BASELINE_LRU" in 0x0000|0|n) echo n > "$LRU" ;; *) echo 7 > "$LRU" ;; esac
    } 2>/dev/null || true
    for t in $APT_WAS_ACTIVE; do systemctl start "$t" 2>/dev/null || true; done
    if [ -n "${MIN_TTL_MS:-}" ] && [ -n "$BOOT_MINTTL" ]; then
        echo "$BOOT_MINTTL" > "$MINTTL_PATH" 2>/dev/null || true
    fi
    rm -rf "$DATADIR" 2>/dev/null || true
    [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ] && rm -f "$LOCK"
    log "RESTORED: lru_gen=$(cat "$LRU")${MIN_TTL_MS:+ min_ttl_ms=$(cat "$MINTTL_PATH" 2>/dev/null)} apt-timers=[${APT_WAS_ACTIVE:- none}] scratch-removed (exit rc=$rc)"
    touch "$EV/_t1d_ALLDONE_${DATE}"
    exit "$rc"
}
trap restore EXIT INT TERM

mkdir -p "$DATADIR"
cd "$REPO"

# Lay down R/L ONCE on ext4; every cell reuses via --skip-laydown.
log "laydown: R=${R_MIB}MiB L=${L_MIB}MiB in $DATADIR (ext4 rootfs)"
"$PY" "$DRIVER" --data-dir "$DATADIR" --r-size-mib "$R_MIB" --l-size-mib "$L_MIB" \
    --resident-frac 1.0 --seed 1729 --result-file /dev/null --laydown-only \
    >>"$RUNLOG" 2>&1 || { log "laydown FAILED — aborting"; exit 4; }

for SPEC in $CELLS; do
    ARM=${SPEC%%:*}; REST=${SPEC#*:}
    FRACPCT=${REST%%:*}; REST=${REST#*:}
    G=${REST%%:*}; REST=${REST#*:}
    SEED=${REST%%:*}
    TAIL=""
    [ "$SEED" != "$REST" ] && TAIL=${REST#*:}
    FA=""
    WL=""
    SKEW="$TAIL"
    while true; do
        case "$SKEW" in
            fa)   FA=1; SKEW="" ;;
            wl)   WL=1; SKEW="" ;;
            fa:*) FA=1; SKEW=${SKEW#fa:} ;;
            wl:*) WL=1; SKEW=${SKEW#wl:} ;;
            *) break ;;
        esac
    done
    if [ -n "$FA" ] && [ "${STRICT_SOUNDNESS:-0}" = 1 ]; then
        log "CONFIG ERROR: fault-around cell '$SPEC' under STRICT_SOUNDNESS=1 — its identity is not applicable by design and strict mode would quarantine it; run it in a non-strict window"
        exit 2
    fi
    ELAPSED=$(( $(date +%s) - T0 ))
    if [ "$ELAPSED" -ge "$WINDOW_DEADLINE_S" ]; then
        log "DEADLINE: ${ELAPSED}s elapsed — not starting $SPEC (or anything after); resume later"
        break
    fi
    case "$ARM" in classic|mglru) ;; *) log "CONFIG ERROR: unknown arm '$ARM' in '$SPEC'"; exit 2 ;; esac
    if [ -n "$SKEW" ] && [ "$PROTOCOL" != tier1d ]; then
        log "CONFIG ERROR: skew cell '$SPEC' but driver is $(basename "$DRIVER") (no --skew support)"; exit 2
    fi
    FRAC=$(awk -v p="$FRACPCT" 'BEGIN{printf "%.4f", p/100.0}')
    SKEWTAG=""
    [ -n "$TAIL" ] && SKEWTAG="$(printf '%s' "$TAIL" | tr ':' '-')_"
    LABEL="${SKEWTAG}frac${FRACPCT}_cap${G}g_seed${SEED}${MIN_TTL_MS:+_ttl${MIN_TTL_MS}}"
    RESULT="data/eval_results/t1d_${ARM}_${LABEL}_${DATE}.json"
    CLOG="$EV/_t1d_${ARM}_${LABEL}_${DATE}.log"
    STATUS="$EV/_t1d_${ARM}_${LABEL}_${DATE}.status"
    EXISTING=$(ls "$EV"/t1d_"${ARM}"_"${LABEL}"_*.json 2>/dev/null | head -1)
    if [ -n "$EXISTING" ] && [ -s "$EXISTING" ]; then
        log "SKIP $ARM/$LABEL — result exists ($(basename "$EXISTING"))"; echo DONE > "$STATUS"; continue
    fi
    if [ "$ARM" = classic ]; then echo n > "$LRU"; else printf '%s\n' 0x0007 > "$LRU" 2>/dev/null || echo y > "$LRU"; fi
    # Assert the toggle TOOK. With a 0x0007 boot a silently-failed `echo n`
    # would run the classic arm under MGLRU and void the whole comparison.
    NOW_LRU=$(cat "$LRU")
    case "$NOW_LRU" in 0x0000|0|n) NOW_ARM=classic ;; *) NOW_ARM=mglru ;; esac
    if [ "$NOW_ARM" != "$ARM" ]; then
        log "ARM TOGGLE FAILED: $ARM cell but lru_gen reads $NOW_LRU (boot was $BOOT_LRU) — aborting window rather than mislabelling a cell"
        exit 3
    fi
    sync; echo 3 > /proc/sys/vm/drop_caches
    log "cell $ARM/$LABEL starting (elapsed ${ELAPSED}s, lru_gen $(cat "$LRU"), frac=$FRAC cap=${G}G${SKEW:+ skew=$SKEW}${FA:+ fault-around=ON}${WL:+ warm-l=ON})"
    # shellcheck disable=SC2086
    systemd-run --scope --collect --quiet -p MemorySwapMax=0 -p "MemoryMax=${G}G" -- \
        timeout "$CELL_TIMEOUT" "$PY" "$DRIVER" \
            --data-dir "$DATADIR" --r-size-mib "$R_MIB" --l-size-mib "$L_MIB" \
            --resident-frac "$FRAC" --passes "$PASSES" --seed "$SEED" \
            --arm "$ARM" --cap-label "cap${G}g" --skip-laydown \
            ${SKEW:+--skew "$SKEW"} ${FA:+--fault-around} ${WL:+--warm-l} \
            --result-file "$REPO/$RESULT" >"$CLOG" 2>&1 &
    CELL_BG=$!
    wait "$CELL_BG"
    rc=$?
    CELL_BG=""
    if [ $rc -eq 0 ] && [ -s "$REPO/$RESULT" ]; then
        if ! grep -q "\"protocol\": \"$PROTOCOL\"" "$REPO/$RESULT"; then
            mv "$REPO/$RESULT" "$REPO/${RESULT%.json}.PROTOVIOLATION.json"
            echo "PROTOVIOLATION" > "$STATUS"
            log "cell $ARM/$LABEL PROTOCOL VIOLATION: protocol!=$PROTOCOL — quarantined, aborting window"
            exit 5
        fi
        if ! grep -q '"soundness_pass1_majflt_eq_deficit": true' "$REPO/$RESULT"; then
            # T1d-5: identity gates UNCAPPED validation cells only; capped cells
            # are judged on the floor trajectory.
            if [ "${STRICT_SOUNDNESS:-0}" = 1 ]; then
                mv "$REPO/$RESULT" "$REPO/${RESULT%.json}.PROTOVIOLATION.json"
                echo "PROTOVIOLATION" > "$STATUS"
                log "cell $ARM/$LABEL SOUNDNESS FAILURE under STRICT_SOUNDNESS=1 — quarantined, aborting window"
                exit 5
            fi
            if [ -n "$FA" ]; then
                log "cell $ARM/$LABEL identity not applicable (fault-around) — kept, judged on floor per §6 gap 2"
            else
                log "cell $ARM/$LABEL soundness identity false (expected when the cap binds during seeding) — kept, judged on floor per T1d-5"
            fi
        fi
        echo DONE > "$STATUS"; log "cell $ARM/$LABEL DONE"
    else
        echo "FAIL($rc)" > "$STATUS"; log "cell $ARM/$LABEL FAIL rc=$rc (see $CLOG)"
    fi
done

log "tier1d(WSL2) window complete"
