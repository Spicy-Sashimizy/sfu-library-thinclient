#!/usr/bin/env bash
# =====================================================================
# convergence_repro — ONE CELL (runs INSIDE the memory-capped container)
#
# Protocol (PREREGISTRATION.md "Protocol per cell"), imitating the proven
# R1 cell protocol in scripts/seismic_testbed/r1_ram_ladder.py:
#
#   0. preflight   — R and L present at the expected sizes, else abort
#   1. record      — kernel, lru_gen state, cgroup version, the cap actually
#                    in force (memory.max), swap policy
#   2. evict       — vmtouch -e on R and L, then VERIFY ~0% residency.
#                    Per-file eviction only; never global drop_caches.
#                    Eviction that did not take => abort the cell.
#   3. load        — ONE buffered sweep over both files (dd -> /dev/null).
#                    TIER-1b (PREREGISTRATION_TIER1B.md, Change 1): the default
#                    LOAD_ORDER is `interleaved` — R and L are both cut into
#                    64-MiB chunks and merged into ONE deterministic
#                    proportional round-robin (Bresenham) schedule, so L's
#                    chunks are spread evenly among R's. Under any cap < D the
#                    load-time evictions therefore fall on the sweep head — a
#                    proportional MIX of L and R — and pass 1 starts with R only
#                    partially resident (the convergence transient Tier-1
#                    structurally could not produce; RESULTS.md §2).
#                    64 MiB is a DECLARED CONSTANT, not a tuning knob: it is
#                    hard-coded below and deliberately has no env override.
#                    LOAD_ORDER=r_then_l is the pre-registered EXPLORATORY order
#                    arm (recorded, never judged); LOAD_ORDER=l_then_r reproduces
#                    the Tier-1 protocol for reference. Both are stamped
#                    load_phase.order_arm=true so analyze.py keeps them out of
#                    the Tier-1b bars by construction.
#   3b. early sort — OPTIONAL (EARLY_SORT, default none == the Tier-1 protocol,
#                    which is byte-for-byte unchanged). See PREREGISTRATION_
#                    EARLYSORT.md. Applied strictly between the load and pass 1:
#                      guided — vmtouch -e L.bin ONLY (the map-guided F5
#                               analogue: the application names the residue),
#                               then verify L residency <= EVICT_MAX_PCT.
#                       blind — write L's byte count to this cgroup's
#                               memory.reclaim (cgroup v2 proactive reclaim, the
#                               map-blind / TMO analogue: the kernel picks the
#                               victims). Unwritable/absent => recorded BLOCKED
#                               (not failed) and the cell continues as a `none`
#                               cell in behaviour.
#   4. passes      — N fio invocations, one invocation == one full pass over R
#                    (jobs/repeat.fio). Per pass: clat p50/p95, wall, majflt,
#                    ms/fault, R+L residency, cgroup memory.stat deltas.
#
#   Modes:  fixed3   — exactly PASSES (default 3) passes, the headline window
#           converge — up to MAX_PASSES (default 12). TIER-1b convergence rule
#                      (defect D3, RESULTS.md §6): a cell is `converged` only
#                      when the per-pass majflt PLATEAUS within +/-10% across 2
#                      consecutive passes **AND** the final pass's majflt is
#                      < 1% of pass 1's (or exactly 0). The Tier-1 rule accepted
#                      either condition alone, so a *thrashing* plateau
#                      (deep: ~1.31M majflt/pass, flat) was scored "converged".
#                      Minimum MIN_PASSES (default 3) so the fixed-window bars
#                      always have pass-3 data.
#
#   Swap: memory.swap.current > 0 in ANY pass marks the cell
#         swap_confounded=true (the R1 / G8 §A1 "recorded-not-concluded" rule).
#
# Output: ONE JSON object on stdout, fenced by CONVREPRO_JSON_BEGIN/END.
#         All human-readable logging goes to stderr. (stdout capture avoids
#         needing any writable bind mount into the cell.)
#
# Exit codes: 0 ok | 2 preflight failed | 3 eviction failed | 4 fio failed
# =====================================================================
set -uo pipefail

log() { printf '[cell %s] %s\n' "${RUNG:-?}" "$*" >&2; }
die() { log "FATAL: $2"; exit "$1"; }

# ---------------------------------------------------------------- inputs
RUNG="${RUNG:-unknown}"
CAP_LABEL="${CAP_LABEL:-uncapped}"
SCALE="${SCALE:-1.0}"
MODE="${MODE:-fixed3}"
PASSES="${PASSES:-3}"
MAX_PASSES="${MAX_PASSES:-12}"
MIN_PASSES="${MIN_PASSES:-3}"
DATA_DIR="${DATA_DIR:-/data}"
JOBS_DIR="${JOBS_DIR:-/bench/jobs}"
FIO_RANDSEED="${FIO_RANDSEED:-20260831}"
R_SIZE_MIB="${R_SIZE_MIB:-5120}"
L_SIZE_MIB="${L_SIZE_MIB:-1792}"
EVICT_MAX_PCT="${EVICT_MAX_PCT:-1}"     # residency % above which eviction failed
CAP_ENFORCED="${CAP_ENFORCED:-1}"       # 0 for the no-docker mechanics run
CAP_BYTES_NOMINAL="${CAP_BYTES_NOMINAL:-}"   # what the orchestrator asked for
RUN_LABEL="${RUN_LABEL:-}"
# VALIDATION ONLY. SKIP_LOAD=1 omits the sequential load of L and R, so pass 1
# starts on a fully evicted R and every 4 KiB block majors. It exists solely to
# exercise the majflt/clat capture path where no memory cap can be enforced.
# It is NOT the pre-registered protocol: any cell produced with it is stamped
# load_phase.skipped=true and must never be used for a bar verdict.
SKIP_LOAD="${SKIP_LOAD:-0}"
# LOAD_ORDER (PREREGISTRATION_TIER1B.md Change 1 + the exploratory order arm):
#   interleaved — THE TIER-1b PROTOCOL. One sweep, 64-MiB chunks of R and L
#                 merged by a deterministic proportional round-robin.
#   r_then_l    — exploratory order arm: whole R, then whole L (residue is the
#                 most-recently-loaded population). RECORDED, NOT JUDGED.
#   l_then_r    — the Tier-1 protocol, kept for reference. RECORDED, NOT JUDGED.
LOAD_ORDER="${LOAD_ORDER:-interleaved}"
# The chunk size of the interleaved sweep. DECLARED CONSTANT (see the banner):
# deliberately NOT an environment knob, so it can never be quietly tuned.
readonly LOAD_CHUNK_MIB=64
# EARLY_SORT: none (default, = the unchanged Tier-1 protocol) | guided | blind.
EARLY_SORT="${EARLY_SORT:-none}"
# Where the blind arm writes. cgroup v2 only; overridable for hosts that expose
# the cell's cgroup somewhere else (e.g. a writable bind mount).
ES_RECLAIM_FILE="${ES_RECLAIM_FILE:-}"
# Free-text note from the orchestrator about HOW write access was granted
# (e.g. "docker --privileged"); recorded verbatim in the JSON.
ES_CGROUP_WRITE_GRANT="${ES_CGROUP_WRITE_GRANT:-}"

export R_FILE="${DATA_DIR}/R.bin"
export L_FILE="${DATA_DIR}/L.bin"
export R_SIZE="${R_SIZE_MIB}M"
export L_SIZE="${L_SIZE_MIB}M"
export FIO_RANDSEED

WORK="$(mktemp -d /tmp/convrepro_cell.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# ------------------------------------------------------------- helpers
# vmtouch residency of one file -> "<resident_pages> <total_pages> <pct>"
residency() {
  local f="$1" out
  out="$(vmtouch "$f" 2>/dev/null)" || { echo "-1 -1 -1"; return; }
  echo "$out" | awk '
    /Resident Pages:/ {
      split($3, a, "/");
      r=a[1]+0; t=a[2]+0;
      p = (t>0) ? (100.0*r/t) : 0.0;
      printf "%d %d %.4f\n", r, t, p;
      found=1
    }
    END { if (!found) print "-1 -1 -1" }'
}

# --------------------------------------------- cgroup probing (v1 vs v2)
CGROUP_VERSION="unknown"
CG_ROOT=""
CG_STAT=""
CG_MAX=""
CG_CUR=""
CG_SWAP=""
CGROUP_READABLE="false"

probe_cgroup() {
  if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
    CGROUP_VERSION="v2"; CG_ROOT="/sys/fs/cgroup"
    CG_STAT="$CG_ROOT/memory.stat"
    CG_MAX="$CG_ROOT/memory.max"
    CG_CUR="$CG_ROOT/memory.current"
    CG_SWAP="$CG_ROOT/memory.swap.current"
  elif [ -d /sys/fs/cgroup/memory ]; then
    CGROUP_VERSION="v1"; CG_ROOT="/sys/fs/cgroup/memory"
    CG_STAT="$CG_ROOT/memory.stat"
    CG_MAX="$CG_ROOT/memory.limit_in_bytes"
    CG_CUR="$CG_ROOT/memory.usage_in_bytes"
    CG_SWAP="$CG_ROOT/memory.memsw.usage_in_bytes"
  else
    CGROUP_VERSION="none"
  fi
  if [ -n "$CG_STAT" ] && [ -r "$CG_STAT" ]; then CGROUP_READABLE="true"; fi
}

cg_field() {   # cg_field <name> -> value, or "" when unavailable
  [ "$CGROUP_READABLE" = "true" ] || { echo ""; return; }
  awk -v k="$1" '$1==k {print $2; f=1} END{if(!f) print ""}' "$CG_STAT" 2>/dev/null
}
cg_file() {    # cg_file <path> -> contents (single token) or ""
  [ -n "${1:-}" ] && [ -r "$1" ] && head -n1 "$1" 2>/dev/null || echo ""
}

# Snapshot the cgroup counters we care about into a key=value file.
cg_snapshot() {
  local dest="$1"
  {
    echo "pgscan=$(cg_field pgscan)"
    echo "pgsteal=$(cg_field pgsteal)"
    echo "workingset_refault_file=$(cg_field workingset_refault_file)"
    echo "active_file=$(cg_field active_file)"
    echo "inactive_file=$(cg_field inactive_file)"
    echo "workingset_activate_file=$(cg_field workingset_activate_file)"
    echo "memory_current=$(cg_file "$CG_CUR")"
    echo "memory_swap_current=$(cg_file "$CG_SWAP")"
  } > "$dest"
}

probe_cgroup

# ==================================================== 0. PREFLIGHT
case "$EARLY_SORT" in
  none|guided|blind) ;;
  *) die 2 "unknown EARLY_SORT=$EARLY_SORT (want none|guided|blind)" ;;
esac
case "$LOAD_ORDER" in
  interleaved|r_then_l|l_then_r) ;;
  *) die 2 "unknown LOAD_ORDER=$LOAD_ORDER (want interleaved|r_then_l|l_then_r)" ;;
esac
# Anything other than the pre-registered interleaved sweep is exploratory.
ORDER_ARM="false"; [ "$LOAD_ORDER" = "interleaved" ] || ORDER_ARM="true"
log "preflight: mode=$MODE scale=$SCALE cap=$CAP_LABEL R=${R_SIZE} L=${L_SIZE} early_sort=$EARLY_SORT load_order=$LOAD_ORDER"
for f in "$R_FILE" "$L_FILE"; do
  [ -f "$f" ] || die 2 "missing data file $f (populate the volume first)"
done
R_BYTES_ACTUAL=$(stat -c %s "$R_FILE")
L_BYTES_ACTUAL=$(stat -c %s "$L_FILE")
R_BYTES_EXPECT=$(( R_SIZE_MIB * 1048576 ))
L_BYTES_EXPECT=$(( L_SIZE_MIB * 1048576 ))
[ "$R_BYTES_ACTUAL" -eq "$R_BYTES_EXPECT" ] \
  || die 2 "R.bin is $R_BYTES_ACTUAL B, expected $R_BYTES_EXPECT B (SCALE mismatch — repopulate the volume)"
[ "$L_BYTES_ACTUAL" -eq "$L_BYTES_EXPECT" ] \
  || die 2 "L.bin is $L_BYTES_ACTUAL B, expected $L_BYTES_EXPECT B (SCALE mismatch — repopulate the volume)"

# Non-sparse check: a sparse file would fault from the zero page and never
# touch the disk, making the whole experiment vacuous.
R_ALLOC_KB=$(stat -c %b "$R_FILE"); R_BLKSZ=$(stat -c %B "$R_FILE")
R_ALLOC_BYTES=$(( R_ALLOC_KB * R_BLKSZ ))
if [ "$R_ALLOC_BYTES" -lt $(( R_BYTES_EXPECT / 2 )) ]; then
  die 2 "R.bin looks SPARSE (${R_ALLOC_BYTES} B allocated of ${R_BYTES_EXPECT} B) — relay it down with fallocate=none"
fi

# ==================================================== 1. RECORD ENV
KERNEL="$(uname -r)"
if [ -r /sys/kernel/mm/lru_gen/enabled ]; then
  LRU_GEN="enabled:$(cat /sys/kernel/mm/lru_gen/enabled)"
else
  LRU_GEN="absent"          # classic two-list LRU (the regime the spec targets)
fi
CAP_BYTES_ACTUAL="$(cg_file "$CG_MAX")"
SWAP_MAX_ACTUAL="$(cg_file "$CG_ROOT/memory.swap.max")"
log "kernel=$KERNEL lru_gen=$LRU_GEN cgroup=$CGROUP_VERSION readable=$CGROUP_READABLE memory.max=${CAP_BYTES_ACTUAL:-n/a}"
if [ "$CGROUP_READABLE" != "true" ]; then
  log "WARNING: cgroup memory.stat NOT readable in-container — emitting cgroup_needs_host_read marker"
fi

# ==================================================== 2. EVICT + VERIFY
log "evicting R and L from the page cache (vmtouch -e; no global drop_caches)"
vmtouch -e "$R_FILE" "$L_FILE" >/dev/null 2>&1
sync
vmtouch -e "$R_FILE" "$L_FILE" >/dev/null 2>&1   # second sweep: dirty pages
read -r EV_R_RES EV_R_TOT EV_R_PCT <<<"$(residency "$R_FILE")"
read -r EV_L_RES EV_L_TOT EV_L_PCT <<<"$(residency "$L_FILE")"
log "post-evict residency: R=${EV_R_PCT}% L=${EV_L_PCT}%"
EVICT_OK=true
awk -v r="$EV_R_PCT" -v l="$EV_L_PCT" -v m="$EVICT_MAX_PCT" \
    'BEGIN{ exit !(r<=m && l<=m && r>=0 && l>=0) }' || EVICT_OK=false
if [ "$EVICT_OK" != "true" ]; then
  die 3 "eviction did NOT take (R=${EV_R_PCT}% L=${EV_L_PCT}%, limit ${EVICT_MAX_PCT}%) — cell aborted"
fi

# ==================================================== 3. LOAD PHASE
# ONE buffered sweep over both populations. This is the "load" whose residue the
# kernel must later sort out from the repeat set. TIER-1b default: interleaved
# (see the banner). The two whole-file orders are the exploratory arms.
#
# Schedule construction (interleaved), deterministic and integer-only —
# Bresenham: with n_r chunks of R and n_l chunks of L, step k in [1, n_r+n_l]
# emits an L chunk iff floor(k*n_l/(n_r+n_l)) > floor((k-1)*n_l/(n_r+n_l)).
# That emits exactly n_l L chunks, spread as evenly as integers allow among the
# n_r R chunks (at SCALE=1: 28 L among 80 R).
N_CHUNKS_R=0; N_CHUNKS_L=0; SCHEDULE=""
LOAD_L_S="0.000"; LOAD_R_S="0.000"

read_chunk() {   # read_chunk <file> <chunk-index-0-based>
  dd if="$1" of=/dev/null bs=1M skip=$(( $2 * LOAD_CHUNK_MIB )) \
     count="$LOAD_CHUNK_MIB" status=none 2>/dev/null
}

LOAD_T0=$(date +%s.%N)
if [ "$SKIP_LOAD" = "1" ]; then
  log "load phase SKIPPED (SKIP_LOAD=1, validation-only — NOT the protocol)"
elif [ "$LOAD_ORDER" = "interleaved" ]; then
  N_CHUNKS_R=$(( (R_SIZE_MIB + LOAD_CHUNK_MIB - 1) / LOAD_CHUNK_MIB ))
  N_CHUNKS_L=$(( (L_SIZE_MIB + LOAD_CHUNK_MIB - 1) / LOAD_CHUNK_MIB ))
  TOTAL_CHUNKS=$(( N_CHUNKS_R + N_CHUNKS_L ))
  SCHEDULE="$(awk -v nr="$N_CHUNKS_R" -v nl="$N_CHUNKS_L" 'BEGIN{
      t=nr+nl; s="";
      for (k=1; k<=t; k++) s = s ((int(k*nl/t) > int((k-1)*nl/t)) ? "L" : "R");
      print s }')"
  log "load phase: INTERLEAVED sweep, ${LOAD_CHUNK_MIB} MiB chunks, R=${N_CHUNKS_R} L=${N_CHUNKS_L} (total ${TOTAL_CHUNKS})"
  log "load schedule: $SCHEDULE"
  ri=0; li=0; acc_r=0; acc_l=0
  for (( k=0; k<TOTAL_CHUNKS; k++ )); do
    tok="${SCHEDULE:$k:1}"
    c0=$(date +%s.%N)
    if [ "$tok" = "R" ]; then read_chunk "$R_FILE" "$ri"; ri=$(( ri + 1 ));
    else                       read_chunk "$L_FILE" "$li"; li=$(( li + 1 )); fi
    c1=$(date +%s.%N)
    d=$(awk -v a="$c0" -v b="$c1" 'BEGIN{printf "%.6f", b-a}')
    if [ "$tok" = "R" ]; then acc_r=$(awk -v a="$acc_r" -v b="$d" 'BEGIN{printf "%.6f", a+b}')
    else                      acc_l=$(awk -v a="$acc_l" -v b="$d" 'BEGIN{printf "%.6f", a+b}'); fi
  done
  LOAD_R_S=$(awk -v v="$acc_r" 'BEGIN{printf "%.3f", v}')
  LOAD_L_S=$(awk -v v="$acc_l" 'BEGIN{printf "%.3f", v}')
  [ "$ri" -eq "$N_CHUNKS_R" ] && [ "$li" -eq "$N_CHUNKS_L" ] \
    || die 2 "interleave schedule emitted R=$ri L=$li, expected R=$N_CHUNKS_R L=$N_CHUNKS_L"
elif [ "$LOAD_ORDER" = "r_then_l" ]; then
  log "load phase [EXPLORATORY ORDER ARM]: sequential read of R then L (once)"
  t0=$(date +%s.%N); dd if="$R_FILE" of=/dev/null bs=1M status=none
  t1=$(date +%s.%N); dd if="$L_FILE" of=/dev/null bs=1M status=none
  t2=$(date +%s.%N)
  LOAD_R_S=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.3f", b-a}')
  LOAD_L_S=$(awk -v a="$t1" -v b="$t2" 'BEGIN{printf "%.3f", b-a}')
else   # l_then_r — the Tier-1 protocol, kept for reference only
  log "load phase [EXPLORATORY ORDER ARM]: sequential read of L then R (once) — the Tier-1 order"
  t0=$(date +%s.%N); dd if="$L_FILE" of=/dev/null bs=1M status=none
  t1=$(date +%s.%N); dd if="$R_FILE" of=/dev/null bs=1M status=none
  t2=$(date +%s.%N)
  LOAD_L_S=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.3f", b-a}')
  LOAD_R_S=$(awk -v a="$t1" -v b="$t2" 'BEGIN{printf "%.3f", b-a}')
fi
LOAD_T_END=$(date +%s.%N)
LOAD_WALL_S=$(awk -v a="$LOAD_T0" -v b="$LOAD_T_END" 'BEGIN{printf "%.3f", b-a}')
read -r LD_R_RES LD_R_TOT LD_R_PCT <<<"$(residency "$R_FILE")"
read -r LD_L_RES LD_L_TOT LD_L_PCT <<<"$(residency "$L_FILE")"
log "load done (order=$LOAD_ORDER, wall=${LOAD_WALL_S}s; read-time L=${LOAD_L_S}s R=${LOAD_R_S}s)"
log "post-load residency: R=${LD_R_PCT}% (${LD_R_RES}/${LD_R_TOT} pages)  L=${LD_L_PCT}% (${LD_L_RES}/${LD_L_TOT} pages)"
cg_snapshot "$WORK/cg_after_load"

# ============================================ 3b. EARLY SORT (optional)
# PREREGISTRATION_EARLYSORT.md. EARLY_SORT=none does NOTHING here — the Tier-1
# protocol is unchanged, and the `early_sort` JSON object simply records mode
# "none" with a null action.
ES_MODE="$EARLY_SORT"
ES_APPLIED="false"
ES_BLOCKED="false"
ES_BLOCK_REASON=""
ES_FAILED="false"
ES_FAIL_REASON=""
ES_WALL_S="0.000"
ES_BYTES_REQ=""
ES_WRITE_RC=""
ES_WRITE_ERR=""
ES_METHOD="none"
ES_PATH=""
ES_POST_R_PCT=""; ES_POST_L_PCT=""
ES_POST_R_RES=""; ES_POST_L_RES=""
ES_MEM_BEFORE=""; ES_MEM_AFTER=""

es_mem_current() { cg_file "$CG_CUR"; }

if [ "$ES_MODE" = "guided" ]; then
  # The map-guided F5 analogue: the application NAMES the residue. Only L is
  # touched; R must be left exactly as the load left it.
  ES_METHOD="vmtouch -e L.bin (per-file, by name)"
  ES_PATH="$L_FILE"
  ES_MEM_BEFORE="$(es_mem_current)"
  log "early sort [guided]: vmtouch -e on L only"
  ES_T0=$(date +%s.%N)
  vmtouch -e "$L_FILE" >/dev/null 2>&1
  ES_T1=$(date +%s.%N)
  ES_WALL_S=$(awk -v a="$ES_T0" -v b="$ES_T1" 'BEGIN{printf "%.4f", b-a}')
  ES_MEM_AFTER="$(es_mem_current)"
  ES_APPLIED="true"
  read -r ES_POST_R_RES _ES_T ES_POST_R_PCT <<<"$(residency "$R_FILE")"
  read -r ES_POST_L_RES _ES_T ES_POST_L_PCT <<<"$(residency "$L_FILE")"
  # Verification is NOT fatal: a guided cell whose eviction did not fully take
  # is still informative, so it is marked and the passes still run.
  if ! awk -v l="$ES_POST_L_PCT" -v m="$EVICT_MAX_PCT" \
        'BEGIN{ exit !(l<=m && l>=0) }'; then
    ES_FAILED="true"
    ES_FAIL_REASON="L residency ${ES_POST_L_PCT}% > ${EVICT_MAX_PCT}% after vmtouch -e"
    log "WARNING: early_sort_failed — $ES_FAIL_REASON (cell continues, marked)"
  fi
  log "early sort [guided] done in ${ES_WALL_S}s: residency now R=${ES_POST_R_PCT}% L=${ES_POST_L_PCT}%"

elif [ "$ES_MODE" = "blind" ]; then
  # The map-blind analogue: ask the kernel to reclaim L-many bytes from THIS
  # cgroup and let it choose the victims. At this instant L and R have identical
  # reference bits (each touched exactly once), so any success comes from
  # inactive-list ORDER alone (L was loaded first). ES-5 datum.
  ES_METHOD="cgroup v2 memory.reclaim (proactive reclaim)"
  ES_BYTES_REQ="$L_BYTES_ACTUAL"
  RECLAIM_F="$ES_RECLAIM_FILE"
  [ -z "$RECLAIM_F" ] && [ "$CGROUP_VERSION" = "v2" ] && RECLAIM_F="$CG_ROOT/memory.reclaim"
  CG_MNT_OPTS="$(awk '$2=="/sys/fs/cgroup"{print $4}' /proc/self/mounts 2>/dev/null | head -n1)"
  if [ "$CGROUP_VERSION" != "v2" ]; then
    ES_BLOCKED="true"
    ES_BLOCK_REASON="cgroup is $CGROUP_VERSION, memory.reclaim is a cgroup-v2-only interface"
  elif [ -z "$RECLAIM_F" ] || [ ! -e "$RECLAIM_F" ]; then
    ES_BLOCKED="true"
    ES_BLOCK_REASON="memory.reclaim absent at ${RECLAIM_F:-<unset>} (kernel < 5.19?)"
  elif [ ! -w "$RECLAIM_F" ]; then
    ES_BLOCKED="true"
    ES_BLOCK_REASON="memory.reclaim not writable at $RECLAIM_F (cgroup mount opts: ${CG_MNT_OPTS:-unknown})"
  else
    ES_PATH="$RECLAIM_F"
    ES_MEM_BEFORE="$(es_mem_current)"
    log "early sort [blind]: writing $ES_BYTES_REQ to $RECLAIM_F"
    ES_T0=$(date +%s.%N)
    if printf '%s' "$ES_BYTES_REQ" > "$RECLAIM_F" 2>"$WORK/es_write.err"; then
      ES_WRITE_RC=0
    else
      ES_WRITE_RC=$?
    fi
    ES_T1=$(date +%s.%N)
    ES_WALL_S=$(awk -v a="$ES_T0" -v b="$ES_T1" 'BEGIN{printf "%.4f", b-a}')
    ES_MEM_AFTER="$(es_mem_current)"
    ES_APPLIED="true"
    ES_WRITE_ERR="$(tr '\n' ' ' < "$WORK/es_write.err" 2>/dev/null | sed 's/[[:space:]]*$//')"
    # A partial reclaim reports an errno (commonly EAGAIN) on write. That is a
    # RESULT, not a harness failure: the kernel could not free everything asked.
    if [ "${ES_WRITE_RC:-1}" -ne 0 ]; then
      ES_FAILED="true"
      ES_FAIL_REASON="memory.reclaim write rc=$ES_WRITE_RC: ${ES_WRITE_ERR:-<no stderr>} (partial/failed reclaim — a datum, not an abort)"
      log "early sort [blind]: write rc=$ES_WRITE_RC — $ES_WRITE_ERR"
    fi
    read -r ES_POST_R_RES _ES_T ES_POST_R_PCT <<<"$(residency "$R_FILE")"
    read -r ES_POST_L_RES _ES_T ES_POST_L_PCT <<<"$(residency "$L_FILE")"
    log "early sort [blind] done in ${ES_WALL_S}s: residency now R=${ES_POST_R_PCT}% L=${ES_POST_L_PCT}%"
  fi
  if [ "$ES_BLOCKED" = "true" ]; then
    log "early sort [blind] BLOCKED: $ES_BLOCK_REASON — cell continues with NO early-sort action (behaves as a 'none' cell); blocked state is recorded"
  fi
fi

cg_snapshot "$WORK/cg_after_es"

# ==================================================== 4. PASSES
case "$MODE" in
  fixed3)   PASS_BUDGET="$PASSES" ;;
  converge) PASS_BUDGET="$MAX_PASSES" ;;
  *)        die 2 "unknown MODE=$MODE (want fixed3|converge)" ;;
esac

MAJFLT_1=0
PREV_MAJFLT=""
PREV_DELTA_OK=0          # consecutive within-10% pass-to-pass steps
CONVERGED="false"
CONVERGE_REASON="not_converged"
SWAP_CONFOUNDED="false"
N_DONE=0

for (( p=1; p<=PASS_BUDGET; p++ )); do
  cg_snapshot "$WORK/cg_pre_$p"
  T0=$(date +%s.%N)
  if ! /usr/bin/time -v -o "$WORK/time_$p.txt" \
        fio "$JOBS_DIR/repeat.fio" \
            --output-format=json --output="$WORK/fio_$p.json" >/dev/null 2>"$WORK/fio_$p.err"; then
    log "fio stderr: $(tail -n 5 "$WORK/fio_$p.err")"
    die 4 "fio failed on pass $p"
  fi
  T1=$(date +%s.%N)
  cg_snapshot "$WORK/cg_post_$p"

  WALL_S=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.4f", b-a}')
  MAJFLT=$(awk -F': ' '/Major \(requiring I\/O\) page faults/ {print $2}' "$WORK/time_$p.txt")
  MINFLT=$(awk -F': ' '/Minor \(reclaiming a frame\) page faults/ {print $2}' "$WORK/time_$p.txt")
  MAJFLT=${MAJFLT:-0}; MINFLT=${MINFLT:-0}
  read -r PR_R_RES PR_R_TOT PR_R_PCT <<<"$(residency "$R_FILE")"
  read -r PR_L_RES PR_L_TOT PR_L_PCT <<<"$(residency "$L_FILE")"

  {
    echo "pass=$p"
    echo "wall_s=$WALL_S"
    echo "t_start_epoch=$T0"
    echo "t_end_epoch=$T1"
    echo "majflt=$MAJFLT"
    echo "minflt=$MINFLT"
    echo "resident_pct_r=$PR_R_PCT"
    echo "resident_pct_l=$PR_L_PCT"
    echo "resident_pages_r=$PR_R_RES"
    echo "resident_pages_l=$PR_L_RES"
  } > "$WORK/meta_$p"

  SWAPNOW="$(cg_file "$CG_SWAP")"
  if [ -n "$SWAPNOW" ] && [ "$SWAPNOW" -gt 0 ] 2>/dev/null; then
    SWAP_CONFOUNDED="true"
    log "WARNING: memory.swap.current=$SWAPNOW > 0 on pass $p — CELL IS SWAP-CONFOUNDED"
  fi

  MSF=$(awk -v w="$WALL_S" -v f="$MAJFLT" 'BEGIN{ printf "%.6f", (f>0)? (1000.0*w/f) : 0 }')
  log "pass $p: wall=${WALL_S}s majflt=$MAJFLT ms/fault=$MSF residency R=${PR_R_PCT}%"

  N_DONE=$p
  [ "$p" -eq 1 ] && MAJFLT_1="$MAJFLT"

  # ---- convergence test (converge mode only) ----
  # TIER-1b FIXED RULE (defect D3, PREREGISTRATION_TIER1B.md bar 2b):
  #   converged  ==  plateau (+/-10% across 2 consecutive passes)
  #              AND final-pass majflt < 1% of pass-1's, or exactly 0.
  # The Tier-1 rule took EITHER condition, so deep's flat ~1.31M majflt/pass
  # was scored "converged". Both halves are now required.
  if [ "$MODE" = "converge" ]; then
    if [ -n "$PREV_MAJFLT" ]; then
      # plateau step: |m_p - m_{p-1}| <= 0.10 * m_{p-1}
      if awk -v a="$PREV_MAJFLT" -v b="$MAJFLT" \
             'BEGIN{ d=(b>a)?(b-a):(a-b); exit !(a>0 && d*10 <= a) }'; then
        PREV_DELTA_OK=$(( PREV_DELTA_OK + 1 ))
      elif awk -v a="$PREV_MAJFLT" -v b="$MAJFLT" 'BEGIN{ exit !(a==0 && b==0) }'; then
        PREV_DELTA_OK=$(( PREV_DELTA_OK + 1 ))
      else
        PREV_DELTA_OK=0
      fi
    fi
    PREV_MAJFLT="$MAJFLT"
    if [ "$p" -ge "$MIN_PASSES" ]; then
      LOWFAULT=0; LOWFAULT_WHY=""
      if [ "$MAJFLT" -eq 0 ] 2>/dev/null; then
        LOWFAULT=1; LOWFAULT_WHY="majflt_zero"
      elif awk -v m="$MAJFLT" -v m1="$MAJFLT_1" 'BEGIN{ exit !(m1>0 && m*100 < m1) }'; then
        LOWFAULT=1; LOWFAULT_WHY="majflt_below_1pct_of_pass1"
      fi
      if [ "$PREV_DELTA_OK" -ge 2 ] && [ "$LOWFAULT" -eq 1 ]; then
        CONVERGED="true"
        CONVERGE_REASON="plateau_within_10pct_x2_and_${LOWFAULT_WHY}"
        log "converged at pass $p ($CONVERGE_REASON)"
        break
      fi
    fi
  fi
done

if [ "$MODE" = "fixed3" ]; then
  CONVERGE_REASON="n/a_fixed_window"
fi

# ==================================================== 5. EMIT JSON
export CR_WORK="$WORK" CR_N_DONE="$N_DONE" CR_RUNG="$RUNG" CR_CAP_LABEL="$CAP_LABEL" \
       CR_SCALE="$SCALE" CR_MODE="$MODE" CR_KERNEL="$KERNEL" CR_LRU_GEN="$LRU_GEN" \
       CR_CGV="$CGROUP_VERSION" CR_CGR="$CGROUP_READABLE" \
       CR_CAP_BYTES="${CAP_BYTES_ACTUAL:-}" CR_SWAP_MAX="${SWAP_MAX_ACTUAL:-}" \
       CR_CAP_ENFORCED="$CAP_ENFORCED" CR_CONVERGED="$CONVERGED" \
       CR_CONVERGE_REASON="$CONVERGE_REASON" CR_SWAP_CONF="$SWAP_CONFOUNDED" \
       CR_R_BYTES="$R_BYTES_ACTUAL" CR_L_BYTES="$L_BYTES_ACTUAL" \
       CR_EV_R_PCT="$EV_R_PCT" CR_EV_L_PCT="$EV_L_PCT" \
       CR_LD_R_PCT="$LD_R_PCT" CR_LD_L_PCT="$LD_L_PCT" \
       CR_LOAD_L_S="$LOAD_L_S" CR_LOAD_R_S="$LOAD_R_S" \
       CR_LD_R_RES="$LD_R_RES" CR_LD_L_RES="$LD_L_RES" \
       CR_LD_R_TOT="$LD_R_TOT" CR_LD_L_TOT="$LD_L_TOT" \
       CR_LOAD_ORDER="$LOAD_ORDER" CR_ORDER_ARM="$ORDER_ARM" \
       CR_LOAD_CHUNK_MIB="$LOAD_CHUNK_MIB" CR_LOAD_WALL="$LOAD_WALL_S" \
       CR_N_CHUNKS_R="$N_CHUNKS_R" CR_N_CHUNKS_L="$N_CHUNKS_L" \
       CR_SCHEDULE="$SCHEDULE" \
       CR_SEED="$FIO_RANDSEED" CR_MAX_PASSES="$MAX_PASSES" CR_MIN_PASSES="$MIN_PASSES" \
       CR_RUN_LABEL="$RUN_LABEL" CR_SKIP_LOAD="$SKIP_LOAD" \
       CR_CAP_NOMINAL="${CAP_BYTES_NOMINAL:-}" \
       CR_ES_MODE="$ES_MODE" CR_ES_APPLIED="$ES_APPLIED" CR_ES_BLOCKED="$ES_BLOCKED" \
       CR_ES_BLOCK_REASON="$ES_BLOCK_REASON" CR_ES_FAILED="$ES_FAILED" \
       CR_ES_FAIL_REASON="$ES_FAIL_REASON" CR_ES_WALL="$ES_WALL_S" \
       CR_ES_BYTES_REQ="$ES_BYTES_REQ" CR_ES_WRITE_RC="$ES_WRITE_RC" \
       CR_ES_WRITE_ERR="$ES_WRITE_ERR" CR_ES_METHOD="$ES_METHOD" CR_ES_PATH="$ES_PATH" \
       CR_ES_POST_R_PCT="$ES_POST_R_PCT" CR_ES_POST_L_PCT="$ES_POST_L_PCT" \
       CR_ES_POST_R_RES="$ES_POST_R_RES" CR_ES_POST_L_RES="$ES_POST_L_RES" \
       CR_ES_MEM_BEFORE="$ES_MEM_BEFORE" CR_ES_MEM_AFTER="$ES_MEM_AFTER" \
       CR_ES_GRANT="$ES_CGROUP_WRITE_GRANT"

echo "===CONVREPRO_JSON_BEGIN==="
python3 - <<'PY'
import json, os, datetime

W  = os.environ["CR_WORK"]
N  = int(os.environ["CR_N_DONE"])

def kv(path):
    d = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    d[k] = v
    except OSError:
        pass
    return d

def num(s):
    if s is None or s == "":
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None

def delta(pre, post, key):
    a, b = num(pre.get(key)), num(post.get(key))
    return None if (a is None or b is None) else b - a

passes = []
for p in range(1, N + 1):
    with open(f"{W}/fio_{p}.json") as fh:
        fj = json.load(fh)
    job  = fj["jobs"][0]
    rd   = job["read"]
    clat = rd.get("clat_ns") or rd.get("clat") or {}
    pct  = clat.get("percentile", {}) or {}
    m    = kv(f"{W}/meta_{p}")
    pre  = kv(f"{W}/cg_pre_{p}")
    post = kv(f"{W}/cg_post_{p}")

    majflt = num(m.get("majflt")) or 0
    wall   = num(m.get("wall_s")) or 0.0

    passes.append({
        "pass": p,
        "wall_s": wall,
        "t_start_epoch": num(m.get("t_start_epoch")),
        "t_end_epoch": num(m.get("t_end_epoch")),
        "fio_runtime_ms": rd.get("runtime"),
        "io_kbytes": rd.get("io_kbytes"),
        "clat_ns_p50":  pct.get("50.000000"),
        "clat_ns_p95":  pct.get("95.000000"),
        "clat_ns_p99":  pct.get("99.000000"),
        "clat_ns_mean": clat.get("mean"),
        "iops_mean": rd.get("iops"),
        "majflt": majflt,
        "minflt": num(m.get("minflt")),
        "ms_per_fault": (1000.0 * wall / majflt) if majflt else None,
        "resident_pct_R": num(m.get("resident_pct_r")),
        "resident_pct_L": num(m.get("resident_pct_l")),
        "resident_pages_R": num(m.get("resident_pages_r")),
        "resident_pages_L": num(m.get("resident_pages_l")),
        "cgroup": {
            "pgscan_delta": delta(pre, post, "pgscan"),
            "pgsteal_delta": delta(pre, post, "pgsteal"),
            "workingset_refault_file_delta": delta(pre, post, "workingset_refault_file"),
            "workingset_activate_file_delta": delta(pre, post, "workingset_activate_file"),
            "active_file_end": num(post.get("active_file")),
            "inactive_file_end": num(post.get("inactive_file")),
            "memory_current_end": num(post.get("memory_current")),
            "memory_swap_current_end": num(post.get("memory_swap_current")),
            "pgscan_cumulative_end": num(post.get("pgscan")),
        },
    })

# early-sort bookkeeping: cgroup snapshots straddling the action itself
cg_load = kv(f"{W}/cg_after_load")
cg_es   = kv(f"{W}/cg_after_es")
_mb = num(os.environ.get("CR_ES_MEM_BEFORE"))
_ma = num(os.environ.get("CR_ES_MEM_AFTER"))
es_freed = (_mb - _ma) if (_mb is not None and _ma is not None) else None

cap_bytes = num(os.environ.get("CR_CAP_BYTES"))
cap_nominal = num(os.environ.get("CR_CAP_NOMINAL"))
# Ratios are reported against the cap actually in force; when no cap is
# enforced (the --local mechanics run) fall back to the nominal cap so the
# rung's intended regime is still legible in the output.
cap_ref = cap_bytes if cap_bytes is not None else cap_nominal
doc = {
    # Schema string deliberately unchanged: every Tier-1b addition is an
    # OPTIONAL field, so analyze.py still loads and labels the frozen Tier-1
    # cells (which simply lack them).
    "schema": "convrepro/cell/1",
    "protocol": "tier1b",
    "generated_utc": datetime.datetime.now(datetime.timezone.utc)
                     .isoformat(timespec="seconds"),
    "run_label": os.environ.get("CR_RUN_LABEL") or None,
    "rung": os.environ["CR_RUNG"],
    "cap_label": os.environ["CR_CAP_LABEL"],
    "cap_bytes_in_force": cap_bytes,
    "cap_bytes_nominal": cap_nominal,
    "cap_enforced": os.environ["CR_CAP_ENFORCED"] == "1",
    "scale": float(os.environ["CR_SCALE"]),
    "mode": os.environ["CR_MODE"],
    "max_passes": num(os.environ["CR_MAX_PASSES"]),
    "min_passes": num(os.environ["CR_MIN_PASSES"]),
    "fio_randseed": num(os.environ["CR_SEED"]),
    "env": {
        "kernel": os.environ["CR_KERNEL"],
        "lru_gen": os.environ["CR_LRU_GEN"],
        "cgroup_version": os.environ["CR_CGV"],
        "cgroup_readable_in_container": os.environ["CR_CGR"] == "true",
        "cgroup_needs_host_read": os.environ["CR_CGR"] != "true",
        "memory_swap_max": os.environ.get("CR_SWAP_MAX") or None,
    },
    "files": {
        "R_bytes": num(os.environ["CR_R_BYTES"]),
        "L_bytes": num(os.environ["CR_L_BYTES"]),
        "R_over_cap": (num(os.environ["CR_R_BYTES"]) / cap_ref) if cap_ref else None,
        "D_over_cap": ((num(os.environ["CR_R_BYTES"]) + num(os.environ["CR_L_BYTES"])) / cap_ref)
                      if cap_ref else None,
        "cap_ref_is_nominal": cap_bytes is None and cap_nominal is not None,
    },
    "eviction": {
        "verified": True,
        "post_evict_resident_pct_R": num(os.environ["CR_EV_R_PCT"]),
        "post_evict_resident_pct_L": num(os.environ["CR_EV_L_PCT"]),
        "method": "vmtouch -e (per-file); no global drop_caches",
    },
    "load_phase": {
        # PREREGISTRATION_TIER1B.md Change 1. `load_order` is "interleaved" for
        # every judged Tier-1b cell; "r_then_l"/"l_then_r" mark the exploratory
        # order arm and set order_arm=true, which keeps them out of the bars.
        # Cells written before Tier-1b carry NO load_order field at all — those
        # are Tier-1 cells and were loaded l_then_r by construction.
        "skipped": os.environ.get("CR_SKIP_LOAD") == "1",
        "load_order": os.environ.get("CR_LOAD_ORDER") or "interleaved",
        "order_arm": os.environ.get("CR_ORDER_ARM") == "true",
        "chunk_mib": num(os.environ.get("CR_LOAD_CHUNK_MIB")),
        "n_chunks_R": num(os.environ.get("CR_N_CHUNKS_R")),
        "n_chunks_L": num(os.environ.get("CR_N_CHUNKS_L")),
        "schedule": os.environ.get("CR_SCHEDULE") or None,
        "load_wall_s": num(os.environ.get("CR_LOAD_WALL")),
        "seq_read_L_s": num(os.environ["CR_LOAD_L_S"]),
        "seq_read_R_s": num(os.environ["CR_LOAD_R_S"]),
        "post_load_resident_pct_R": num(os.environ["CR_LD_R_PCT"]),
        "post_load_resident_pct_L": num(os.environ["CR_LD_L_PCT"]),
        "post_load_resident_pages_R": num(os.environ.get("CR_LD_R_RES")),
        "post_load_resident_pages_L": num(os.environ.get("CR_LD_L_RES")),
        "total_pages_R": num(os.environ.get("CR_LD_R_TOT")),
        "total_pages_L": num(os.environ.get("CR_LD_L_TOT")),
    },
    "early_sort": {
        # PREREGISTRATION_EARLYSORT.md. mode "none" == the unchanged Tier-1
        # protocol: no action is taken and every measurement below is null.
        "mode": os.environ.get("CR_ES_MODE") or "none",
        "applied": os.environ.get("CR_ES_APPLIED") == "true",
        "blocked": os.environ.get("CR_ES_BLOCKED") == "true",
        "blocked_reason": os.environ.get("CR_ES_BLOCK_REASON") or None,
        "early_sort_failed": os.environ.get("CR_ES_FAILED") == "true",
        "failed_reason": os.environ.get("CR_ES_FAIL_REASON") or None,
        "action_wall_s": num(os.environ.get("CR_ES_WALL")),
        "method": os.environ.get("CR_ES_METHOD") or "none",
        "target_path": os.environ.get("CR_ES_PATH") or None,
        "bytes_requested": num(os.environ.get("CR_ES_BYTES_REQ")),
        "write_rc": num(os.environ.get("CR_ES_WRITE_RC")),
        "write_stderr": os.environ.get("CR_ES_WRITE_ERR") or None,
        "cgroup_write_grant": os.environ.get("CR_ES_GRANT") or None,
        "post_action_resident_pct_R": num(os.environ.get("CR_ES_POST_R_PCT")),
        "post_action_resident_pct_L": num(os.environ.get("CR_ES_POST_L_PCT")),
        "post_action_resident_pages_R": num(os.environ.get("CR_ES_POST_R_RES")),
        "post_action_resident_pages_L": num(os.environ.get("CR_ES_POST_L_RES")),
        "memory_current_before": num(os.environ.get("CR_ES_MEM_BEFORE")),
        "memory_current_after": num(os.environ.get("CR_ES_MEM_AFTER")),
        "bytes_freed_observed": es_freed,
        "cgroup_delta_over_action": {
            "pgscan_delta": delta(cg_load, cg_es, "pgscan"),
            "pgsteal_delta": delta(cg_load, cg_es, "pgsteal"),
            "active_file_before": num(cg_load.get("active_file")),
            "active_file_after": num(cg_es.get("active_file")),
            "inactive_file_before": num(cg_load.get("inactive_file")),
            "inactive_file_after": num(cg_es.get("inactive_file")),
        },
    },
    "converged": os.environ["CR_CONVERGED"] == "true",
    "converge_reason": os.environ["CR_CONVERGE_REASON"],
    "passes_run": N,
    "swap_confounded": os.environ["CR_SWAP_CONF"] == "true",
    "passes": passes,
}
print(json.dumps(doc, indent=2))
PY
echo "===CONVREPRO_JSON_END==="
log "cell complete: $N_DONE passes, converged=$CONVERGED, swap_confounded=$SWAP_CONFOUNDED"
