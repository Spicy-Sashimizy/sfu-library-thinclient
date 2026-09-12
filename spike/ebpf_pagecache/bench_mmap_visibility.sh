#!/bin/bash
# bench_mmap_visibility.sh — does cache_ext see an mmap'd workload at all?
#
# RUN THIS ON A cache_ext KERNEL. It cannot run in the dev container and it
# has never been executed anywhere: it is the empirical check of a claim made
# by reading the kernel diff.
#
# THE QUESTION
# ------------
# In linux-cache-ext @ 7442a927 (base v6.6.8) the `folio_accessed` struct_ops
# hook is called from exactly one site, mm/swap.c:459-464 inside
# folio_mark_accessed(). Reading mm/filemap.c, filemap_fault() (:3383) and
# filemap_map_pages() (:3686) never call folio_mark_accessed, and mm/rmap.c
# carries no cache_ext hook at all. The prediction is therefore:
#
#   folio_accessed NEVER fires during an mmap touch pass;
#   folio_added / folio_evicted DO fire (insertion/removal go through
#   __filemap_add_folio / __filemap_remove_folio regardless of access method).
#
# Falsifiable readout: STAT_ACCESSED_CALLS is bumped at the top of
# hotset_folio_accessed BEFORE any inode filtering, so
#   delta(accessed_calls) == 0 over a pass  => hook truly never fires
#   delta(accessed_calls) > 0 but accessed_relevant == 0
#                                            => hook fires, our filter rejects
#   delta(accessed_relevant) > 0             => PREDICTION WRONG, cache_ext
#                                               does see mmap PTE accesses
# A nonzero accessed_calls at munmap time is expected and NOT a refutation:
# zap_pte_range() (mm/memory.c:1452) calls mark_page_accessed() for
# pte_young() file pages during teardown. That is why stats are sampled
# per-pass-window around the cell and also once after it exits.
#
# THE ARMS (all at the same cap, same seed, same skew)
#   baseline  no cache_ext policy attached (kernel LRU, MGLRU off)
#   fifo_ctl  hotset_protect attached with NO hot table -> everything cold,
#             two-list FIFO. This is the "trivial counting policy" upstream
#             does not ship; it isolates the cost of the framework itself.
#   hotset    hotset_protect attached with the real t1d hot-extent table.
#
# t1d_cell.py is reused UNCHANGED. The only difference from the WSL2
# orchestrator is that the memory cap comes from a named cgroup created with
# cgcreate instead of a transient `systemd-run --scope -p MemoryMax=` scope:
# cache_ext attaches to a cgroup path opened by the loader, so the path has to
# be known before the workload starts.
set -eu -o pipefail

# --- configuration ---------------------------------------------------------
SCRIPT_PATH=$(realpath "$0")
SPIKE_DIR=$(dirname "$SCRIPT_PATH")
REPO=$(realpath "$SPIKE_DIR/../..")

UPSTREAM="${UPSTREAM:-$SPIKE_DIR/cache_ext_upstream}"
LOADER="${LOADER:-$UPSTREAM/policies/hotset_protect.out}"
DRIVER="${DRIVER:-$REPO/spike/convergence_repro/t1d_cell.py}"
PY="${PY:-$REPO/.venv/bin/python3}"
LOAD_HOTSET="${LOAD_HOTSET:-$SPIKE_DIR/load_hotset.py}"

DATADIR="${DATADIR:-/var/tmp/t1d_scratch}"
OUTDIR="${OUTDIR:-$REPO/data/eval_results}"
DATE="${DATE:-$(date +%Y%m%d)}"

CGROUP="${CGROUP:-cache_ext_test}"
CG_PATH="/sys/fs/cgroup/$CGROUP"
CAP_G="${CAP_G:-2.5}"
R_MIB="${R_MIB:-5120}"
L_MIB="${L_MIB:-1792}"
FRAC="${FRAC:-0.92}"
PASSES="${PASSES:-12}"
SEED="${SEED:-1729}"
SKEW="${SKEW:-hotsetc:0.20:0.80:8}"
CELL_TIMEOUT="${CELL_TIMEOUT:-1800}"

STATS_PIN=/sys/fs/bpf/cache_ext/hotset_stats
BPFTOOL="${BPFTOOL:-/usr/local/sbin/bpftool}"
TAG="mmapvis_$(printf '%s' "$SKEW" | tr ':' '-')_cap${CAP_G}g_seed${SEED}_${DATE}"
LOG="$OUTDIR/_${TAG}.log"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }

# --- guards ----------------------------------------------------------------
if ! uname -r | grep -q "cache-ext"; then
	echo "This script is intended to be run on a cache_ext kernel." >&2
	echo "Current kernel: $(uname -r)" >&2
	exit 1
fi
[ -x "$LOADER" ] || { echo "missing policy loader: $LOADER (see cache_ext_hotset.patch)" >&2; exit 1; }
[ -f "$DRIVER" ] || { echo "missing driver: $DRIVER" >&2; exit 1; }
[ -x "$BPFTOOL" ] || { echo "missing bpftool: $BPFTOOL (install_kernel.sh builds it)" >&2; exit 1; }
case "$DATADIR" in /mnt/*) echo "DATADIR=$DATADIR is on drvfs/9p — invalid; use an ext4 path" >&2; exit 1 ;; esac
mkdir -p "$OUTDIR" "$DATADIR"

# MANDATORY. shrink_lruvec() returns into lru_gen_shrink_lruvec() at
# mm/vmscan.c:6439-6442, which is BEFORE the cache_ext block at :6465-6469 —
# with MGLRU on, an attached policy is simply never consulted.
if ! "$UPSTREAM/utils/disable-mglru.sh"; then
	echo "Failed to disable MGLRU — cache_ext hooks would be dead code." >&2
	exit 1
fi
log "MGLRU disabled (lru_gen/enabled = $(cat /sys/kernel/mm/lru_gen/enabled))"

sudo mkdir -p "$(dirname "$STATS_PIN")"

# --- helpers ---------------------------------------------------------------
POLICY_PID=""

cleanup() {
	local rc=$?
	if [ -n "$POLICY_PID" ]; then
		sudo kill -2 "$POLICY_PID" 2>/dev/null || true
		wait "$POLICY_PID" 2>/dev/null || true
		POLICY_PID=""
	fi
	sudo rm -f "$STATS_PIN" 2>/dev/null || true
	sudo cgdelete -g "memory:$CGROUP" 2>/dev/null || true
	log "cleanup done (rc=$rc)"
}
trap cleanup EXIT INT TERM

recreate_cgroup() {
	# Mirror of bench/bench_lib.py::recreate_cache_ext_cgroup().
	sudo cgdelete -g "memory:$CGROUP" 2>/dev/null || true
	sudo cgcreate -g "memory:$CGROUP"
	sudo sh -c "echo $(awk -v g="$CAP_G" 'BEGIN{printf "%d", g*1024*1024*1024}') > $CG_PATH/memory.max"
	sudo sh -c "echo 0 > $CG_PATH/memory.swap.max"
	log "cgroup $CGROUP recreated with memory.max=${CAP_G}G, swap.max=0"
}

start_policy() {
	# $1 = chunk table path, or "" for the all-cold FIFO control.
	# The Python equivalent is `load_hotset.py attach`; done inline here so
	# the script owns the loader PID for a deterministic detach.
	local chunks="$1"
	local cmd=(sudo "$LOADER" --watch_dir "$DATADIR" --cgroup_path "$CG_PATH")
	[ -n "$chunks" ] && cmd+=(--hot_chunks "$chunks")
	log "starting policy: ${cmd[*]}"
	"${cmd[@]}" >>"$LOG" 2>&1 &
	POLICY_PID=$!
	sleep 10   # bench_lib.CacheExtPolicy.start() settle time
	if ! kill -0 "$POLICY_PID" 2>/dev/null; then
		log "policy loader exited early — see $LOG"
		exit 2
	fi
	[ -e "$STATS_PIN" ] || { log "stats map was not pinned at $STATS_PIN"; exit 2; }
}

stop_policy() {
	[ -n "$POLICY_PID" ] || return 0
	sudo kill -2 "$POLICY_PID" 2>/dev/null || true
	wait "$POLICY_PID" 2>/dev/null || true
	POLICY_PID=""
	sudo rm -f "$STATS_PIN" 2>/dev/null || true
}

snap_stats() {
	# $1 = destination json path; no-op when no policy is attached.
	[ -e "$STATS_PIN" ] || { echo '{}' > "$1"; return 0; }
	sudo "$PY" "$LOAD_HOTSET" stats --pin "$STATS_PIN" --json > "$1"
}

stat_delta() {
	# $1 before.json  $2 after.json  $3 key
	"$PY" - "$1" "$2" "$3" <<'EOF'
import json, sys
b = json.load(open(sys.argv[1])); a = json.load(open(sys.argv[2]))
print(a.get(sys.argv[3], 0) - b.get(sys.argv[3], 0))
EOF
}

run_cell_in_cgroup() {
	# $1 = arm label, $2 = result json path
	local arm="$1" result="$2"
	sync; sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
	log "cell $arm starting (cap=${CAP_G}G frac=$FRAC skew=$SKEW)"
	# Join the cgroup the policy is attached to, then exec the UNCHANGED
	# Tier-1d driver. --skip-laydown reuses the R.bin/L.bin laid down above,
	# which is also what keeps the inode (and therefore the chunk table)
	# valid across arms.
	sudo sh -c 'echo $$ > '"$CG_PATH"'/cgroup.procs; exec "$@"' _ \
		timeout "$CELL_TIMEOUT" "$PY" "$DRIVER" \
			--data-dir "$DATADIR" --r-size-mib "$R_MIB" --l-size-mib "$L_MIB" \
			--resident-frac "$FRAC" --passes "$PASSES" --seed "$SEED" \
			--arm "$arm" --cap-label "cap${CAP_G}g" --skip-laydown \
			--skew "$SKEW" --warm-l \
			--result-file "$result" >>"$LOG" 2>&1
}

# --- laydown (once, outside the cgroup, driver unchanged) ------------------
log "=== laydown ==="
"$PY" "$DRIVER" --data-dir "$DATADIR" --r-size-mib "$R_MIB" --l-size-mib "$L_MIB" \
	--resident-frac "$FRAC" --seed "$SEED" --skew "$SKEW" \
	--laydown-only --result-file "$OUTDIR/_${TAG}_laydown.json" >>"$LOG" 2>&1
log "R.bin ino=$(stat -c %i "$DATADIR/R.bin") L.bin ino=$(stat -c %i "$DATADIR/L.bin")"

# --- arm 1: baseline, no policy -------------------------------------------
log "=== arm baseline (no cache_ext policy) ==="
recreate_cgroup
BASE_RESULT="$OUTDIR/${TAG}_baseline.json"
run_cell_in_cgroup "baseline" "$BASE_RESULT"

# The hot-extent table needs a completed result JSON for its skew block; the
# baseline result is the cheapest source and describes the same cell.
CHUNKS="$OUTDIR/_${TAG}_hot_chunks.txt"
log "=== building hot-extent chunk table ==="
"$PY" "$LOAD_HOTSET" chunks --result-json "$BASE_RESULT" --data-dir "$DATADIR" \
	--out "$CHUNKS" 2>&1 | tee -a "$LOG"

# --- arms 2 and 3: policy attached -----------------------------------------
for ARM in fifo_ctl hotset; do
	log "=== arm $ARM ==="
	recreate_cgroup
	if [ "$ARM" = hotset ]; then
		start_policy "$CHUNKS"
	else
		start_policy ""
	fi

	BEFORE="$OUTDIR/_${TAG}_${ARM}_stats_before.json"
	AFTER="$OUTDIR/_${TAG}_${ARM}_stats_after.json"
	POST="$OUTDIR/_${TAG}_${ARM}_stats_postexit.json"

	snap_stats "$BEFORE"
	run_cell_in_cgroup "$ARM" "$OUTDIR/${TAG}_${ARM}.json"
	# Sampled while the driver's mapping is already gone (it exited), but
	# BEFORE detaching, so zap_pte_range()'s teardown burst lands in POST,
	# not in the pass window. AFTER is taken first for exactly that reason.
	snap_stats "$AFTER"
	sleep 2
	snap_stats "$POST"

	for K in added_calls added_relevant added_hot added_cold \
	         accessed_calls accessed_relevant accessed_hot \
	         evicted_calls evicted_relevant evicted_hot \
	         evict_folios_calls evict_from_cold evict_from_hot \
	         evict_hot_fallback scan_cold scan_hot; do
		log "  $ARM delta $K = $(stat_delta "$BEFORE" "$AFTER" "$K") (post-exit total $(stat_delta "$BEFORE" "$POST" "$K"))"
	done

	ACC=$(stat_delta "$BEFORE" "$AFTER" accessed_calls)
	ACCR=$(stat_delta "$BEFORE" "$AFTER" accessed_relevant)
	ADD=$(stat_delta "$BEFORE" "$AFTER" added_relevant)
	if [ "$ACCR" -gt 0 ]; then
		log "  VERDICT[$ARM]: folio_accessed FIRES for mmap ($ACCR relevant calls) — prediction REFUTED"
	elif [ "$ACC" -gt 0 ]; then
		log "  VERDICT[$ARM]: folio_accessed fires ($ACC) but never for watched inodes — check dir_watcher"
	elif [ "$ADD" -gt 0 ]; then
		log "  VERDICT[$ARM]: folio_added fires ($ADD) but folio_accessed NEVER does — prediction CONFIRMED"
	else
		log "  VERDICT[$ARM]: NO hook fired at all — policy not actually attached to the workload's cgroup"
	fi

	stop_policy
done

log "=== done. results + stats snapshots under $OUTDIR (tag $TAG) ==="
