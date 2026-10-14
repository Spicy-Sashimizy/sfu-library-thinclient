#!/bin/bash
# bench_stack_phase2.sh — cache_ext hot-set protection on the REAL serving stack.
#
# RUN THIS ON A cache_ext KERNEL. It cannot run in the dev container and has
# never been executed anywhere. Phase 1 (bench_mmap_visibility.sh) asked
# whether cache_ext sees an mmap workload at all, against a synthetic file.
# This asks whether the F1 production hot-set sidecars, pushed into the policy,
# move the real stack's fault floor and latency at the RAM tiers that matter
# (TEST_SITUATIONS.md situations S1-S4).
#
# WHAT IS REUSED, NOT REINVENTED
# ------------------------------
# The replay driver is the already-judged Tier-2/3 cell, UNCHANGED:
#
#   scripts/seismic_testbed/t23_convergence_ladder.py
#
# It is standalone (plain argparse + __main__, no ssh/systemd-run/sweep of its
# own), it builds the real backend in-process
#   HybridSeismicBackend.from_manifest(
#       "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json",
#       load_mode="mmap")                     (t23_convergence_ladder.py:201)
# it replays the 40 pre-encoded queries of
#   data/eval_results/e7b_encoded_queries.json  (:197, --queries default 40)
# up to --max-passes times with the t23 convergence rule, and it reads majflt
# from /proc/self/stat field 11 (:70-71) — the same field index t1d uses.
# Reusing it keeps every number here comparable with the t23a/t23b/sml cells
# already on record. The ONLY delta from the t23 orchestrator is the cap
# mechanism: cgcreate + memory.max instead of `systemd-run --scope -p
# MemoryMax=`, because cache_ext attaches to a cgroup PATH the loader must
# open before the workload starts (identical caveat to phase 1).
#
# DRIVER=stack_replay.py switches to the spike's own driver for S4/S6 (top-k
# hydrate through meta.sqlite, S4 query weighting, S6 drift mixture). Same
# majflt read, same convergence rule, same result-JSON shape.
#
# THE SERVING PROCESS *IS* THE MEASURED PROCESS
# ---------------------------------------------
# t23_convergence_ladder.py constructs the backend in-process and reads
# /proc/SELF/stat; there is no child server and no PID plumbing. So "the
# serving process cgroup" is just: the driver process joins $CGROUP and execs.
#
# CGROUP LAYOUT (the phase-2 design)
# ----------------------------------
#   /sys/fs/cgroup/$CGROUP   memory.max=$CAP_G G, memory.swap.max=0
#                            contains: the replay driver, and NOTHING ELSE
#                            (except deliberately, in situation S3, where
#                            antagonist_scan.sh --cgroup joins it).
# meta.sqlite is NOT separated out. In the deployed stack it is opened
# in-process by ThinClientRetriever._load() (source/lib/thinclient/retriever.py:
# 541-553) with a plain sqlite3 connection — no separate service, no separate
# cgroup — so its page cache genuinely competes with the seismic mmaps under
# one memory.max. Phase 2 MEASURES that, it does not engineer around it. Note
# the t23 driver alone never touches meta.sqlite (it calls search_encoded on
# the sharded backend directly); DRIVER=stack_replay.py --hydrate is what puts
# sqlite back into the cell, which is what situation S4 needs.
#
# WATCH_DIR SCOPE (read before interpreting any result)
# -----------------------------------------------------
# dir_watcher's inode_watchlist is seeded by a RECURSIVE stat walk of
# --watch_dir (dir_watcher.h:23-82), and folios of unwatched inodes are simply
# not managed by the policy (is_folio_relevant, hotset_protect.bpf.c:176-182)
# — they stay on the kernel's own reclaim path. With WATCH_DIR = the plan01
# index dir, that means:
#   * MANAGED, and HOT (in the table): the ~1.5 GiB of forward_data.bin pages
#     the F1 hot50 sidecars name.
#   * MANAGED, and COLD (not in the table): everything else the serving path
#     mmaps — the rest of forward_data.bin, and ALL of posting_lists.bin
#     (1.08 GiB/shard), forward_offsets.bin, document_mapping_strings.bin,
#     document_mapping_offsets.bin. These are drained first by
#     hotset_evict_folios. That is the honest reading of the arm: "protect the
#     measured hot forward pages, deprioritise everything else in the index".
#   * UNMANAGED: meta.sqlite (24.9 GiB, under data/thinclient_index/, outside
#     the watch tree). Set WATCH_DIR to a common ancestor to manage it too —
#     but note the recursive walk then stats the whole subtree, and
#     inode_watchlist caps at 200000 entries (dir_watcher.bpf.h:27).
# The guard below warns when the hot inodes or meta.sqlite fall outside
# WATCH_DIR, rather than letting a silently-unmanaged file explain the result.
#
# ARMS (all at the same cap, same driver, same query list)
#   baseline  no cache_ext policy (classic LRU, MGLRU off)
#   hotset    hotset_protect + the production sidecar chunk table
#   fifo_ctl  hotset_protect with NO table -> everything cold, two-list FIFO.
#             Isolates the framework's own cost from the hot set's value.
set -eu -o pipefail

# --- configuration ---------------------------------------------------------
SCRIPT_PATH=$(realpath "$0")
SPIKE_DIR=$(dirname "$SCRIPT_PATH")
REPO=$(realpath "$SPIKE_DIR/../..")

UPSTREAM="${UPSTREAM:-$SPIKE_DIR/cache_ext_upstream}"
LOADER="${LOADER:-$UPSTREAM/policies/hotset_protect.out}"
DRIVER="${DRIVER:-$REPO/scripts/seismic_testbed/t23_convergence_ladder.py}"
PY="${PY:-$REPO/.venv/bin/python3}"
LOAD_HOTSET="${LOAD_HOTSET:-$SPIKE_DIR/load_hotset.py}"
ANTAGONIST="${ANTAGONIST:-$SPIKE_DIR/antagonist_scan.sh}"

INDEX_DIR="${INDEX_DIR:-$REPO/data/seismic_150m/index/plan01}"
WATCH_DIR="${WATCH_DIR:-$INDEX_DIR}"
INDEX_ROOT="${INDEX_ROOT:-$REPO/data/thinclient_index}"
BUDGET="${BUDGET:-hot50_1.6gb}"      # hot50_1.6gb | hot80_4.2gb | full_touched
OUTDIR="${OUTDIR:-$REPO/data/eval_results}"
DATE="${DATE:-$(date +%Y%m%d)}"

CGROUP="${CGROUP:-cache_ext_serve}"
CG_PATH="/sys/fs/cgroup/$CGROUP"
CAP_G="${CAP_G:-16}"                 # S1 ladder: 24 / 16 / 14
ARMS="${ARMS:-baseline hotset fifo_ctl}"
MAX_PASSES="${MAX_PASSES:-12}"
MIN_PASSES="${MIN_PASSES:-3}"
TOP_K="${TOP_K:-50}"
QUERIES="${QUERIES:-40}"
CELL_TIMEOUT="${CELL_TIMEOUT:-6000}"
DRIVER_EXTRA="${DRIVER_EXTRA:-}"     # e.g. "--hydrate --weight metadata"

# Serving env gates. Defaults chosen so the POLICY is the only thing acting on
# residency; every one of these is a documented gate read by
# source/lib/thinclient/sharded_seismic_backend.py.
#   PREFLOOR_HOTSET=1 is what every t23 orchestrator exports (t23_host_
#   orchestrator.sh:33) and phase-B/C quarantine results that lack it — but it
#   PREFAULTS the same F1 hot set the policy is being asked to protect, which
#   would confound the phase-2 question. Default 0 here, deliberately; set
#   PREFLOOR_HOTSET=1 for a run that is protocol-comparable to the t23 record
#   instead, and say which one a number came from.
PREFLOOR_HOTSET="${PREFLOOR_HOTSET:-0}"
#   PIN_BUDGET_GB and MLOCK_FLOOR MUST stay 0: mlock'd pages are unevictable,
#   never reach evict_folios, and would silently do the policy's job for it.
PIN_BUDGET_GB="${PIN_BUDGET_GB:-0}"
MLOCK_FLOOR="${MLOCK_FLOOR:-0}"
PREFLOOR_AT_LOAD="${PREFLOOR_AT_LOAD:-0}"
#   Federation: unset => FS-aware auto (sequential on 9p/NFS, parallel on a
#   local FS). Left to auto by default; pin it if arms must match exactly.
FEDERATION="${FEDERATION:-}"

# Antagonist (situations S2 / S3); off unless ANTAGONIST_MODE is set.
#   outside -> S2 noisy neighbour;  inside -> S3 rebuild interference.
ANTAGONIST_MODE="${ANTAGONIST_MODE:-}"
ANTAGONIST_RATE="${ANTAGONIST_RATE:-200}"
ANTAGONIST_TARGET="${ANTAGONIST_TARGET:-}"

STATS_PIN=/sys/fs/bpf/cache_ext/hotset_stats
CHUNKS_PIN=/sys/fs/bpf/cache_ext/hotset_chunks
BPFTOOL="${BPFTOOL:-/usr/local/sbin/bpftool}"
TAG="s2stack_${BUDGET}_cap${CAP_G}g${ANTAGONIST_MODE:+_ant-$ANTAGONIST_MODE}_${DATE}"
LOG="$OUTDIR/_${TAG}.log"

mkdir -p "$OUTDIR"
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }

# --- guards ----------------------------------------------------------------
if ! uname -r | grep -q "cache-ext"; then
	echo "This script is intended to be run on a cache_ext kernel." >&2
	echo "Current kernel: $(uname -r)" >&2
	exit 1
fi
[ -x "$LOADER" ]  || { echo "missing policy loader: $LOADER (see cache_ext_hotset.patch)" >&2; exit 1; }
[ -f "$DRIVER" ]  || { echo "missing replay driver: $DRIVER" >&2; exit 1; }
[ -x "$PY" ]      || { echo "missing venv python: $PY" >&2; exit 1; }
[ -x "$BPFTOOL" ] || { echo "missing bpftool: $BPFTOOL (install_kernel.sh builds it)" >&2; exit 1; }
[ -d "$INDEX_DIR" ] || { echo "missing index dir: $INDEX_DIR" >&2; exit 1; }

# dir_watcher's BPF-side path compare is capped at BPF_PATH_MAX=128
# (dir_watcher.bpf.h:17) and hotset_protect.c::validate_watch_dir refuses
# longer; catch it here rather than after a 10-minute laydown.
WATCH_REAL=$(realpath "$WATCH_DIR")
if [ "${#WATCH_REAL}" -gt 128 ]; then
	echo "WATCH_DIR realpath is ${#WATCH_REAL} chars, > BPF_PATH_MAX(128): $WATCH_REAL" >&2
	echo "bind-mount the index somewhere shorter, or the policy will refuse." >&2
	exit 1
fi
case "$INDEX_DIR" in
	"$WATCH_REAL"*) ;;
	*) log "WARNING: INDEX_DIR ($INDEX_DIR) is not under WATCH_DIR ($WATCH_REAL) — the hot inodes would be UNMANAGED" ;;
esac
case "$INDEX_ROOT/meta.sqlite" in
	"$WATCH_REAL"*) log "note: meta.sqlite IS inside the watch tree — its pages are policy-managed and land on the cold list" ;;
	*) log "note: meta.sqlite is OUTSIDE the watch tree — its pages are NOT policy-managed (kernel reclaim handles them). Relevant only when the driver hydrates." ;;
esac

# MANDATORY. shrink_lruvec() returns into lru_gen_shrink_lruvec() at
# mm/vmscan.c:6439-6442, BEFORE the cache_ext block at :6465-6469 — with MGLRU
# on, an attached policy is never consulted. Also: t23_convergence_ladder.py
# gates on --arm matching lru_gen/enabled, so "classic" is the only arm name
# that will run here at all.
if ! "$UPSTREAM/utils/disable-mglru.sh"; then
	echo "Failed to disable MGLRU — cache_ext hooks would be dead code." >&2
	exit 1
fi
log "MGLRU disabled (lru_gen/enabled = $(cat /sys/kernel/mm/lru_gen/enabled 2>/dev/null || echo absent))"

sudo mkdir -p "$(dirname "$STATS_PIN")"

# The deployed server would fight us for the page cache.
if systemctl is-active --quiet sfu-serve 2>/dev/null; then
	log "stopping sfu-serve for the duration (t23 orchestrator does the same)"
	sudo systemctl stop sfu-serve
	RESTART_SERVE=1
else
	RESTART_SERVE=0
fi

# --- helpers ---------------------------------------------------------------
POLICY_PID=""
ANT_PID=""

cleanup() {
	local rc=$?
	if [ -n "$ANT_PID" ]; then sudo kill "$ANT_PID" 2>/dev/null || true; ANT_PID=""; fi
	if [ -n "$POLICY_PID" ]; then
		sudo kill -2 "$POLICY_PID" 2>/dev/null || true
		wait "$POLICY_PID" 2>/dev/null || true
		POLICY_PID=""
	fi
	sudo rm -f "$STATS_PIN" "$CHUNKS_PIN" 2>/dev/null || true
	sudo cgdelete -g "memory:$CGROUP" 2>/dev/null || true
	[ "$RESTART_SERVE" = 1 ] && sudo systemctl start sfu-serve 2>/dev/null || true
	log "cleanup done (rc=$rc)"
}
trap cleanup EXIT INT TERM

recreate_cgroup() {
	sudo cgdelete -g "memory:$CGROUP" 2>/dev/null || true
	sudo cgcreate -g "memory:$CGROUP"
	sudo sh -c "echo $(awk -v g="$CAP_G" 'BEGIN{printf "%d", g*1024*1024*1024}') > $CG_PATH/memory.max"
	sudo sh -c "echo 0 > $CG_PATH/memory.swap.max"
	log "cgroup $CGROUP recreated with memory.max=${CAP_G}G, swap.max=0"
}

start_policy() {
	# $1 = chunk table path, or "" for the all-cold FIFO control.
	local chunks="$1"
	local cmd=(sudo "$LOADER" --watch_dir "$WATCH_REAL" --cgroup_path "$CG_PATH")
	[ -n "$chunks" ] && cmd+=(--hot_chunks "$chunks")
	log "starting policy: ${cmd[*]}"
	"${cmd[@]}" >>"$LOG" 2>&1 &
	POLICY_PID=$!
	sleep 10   # bench_lib.CacheExtPolicy.start() settle time
	if ! kill -0 "$POLICY_PID" 2>/dev/null; then
		log "policy loader exited early — see $LOG"; exit 2
	fi
	[ -e "$STATS_PIN" ]  || { log "stats map was not pinned at $STATS_PIN"; exit 2; }
	[ -e "$CHUNKS_PIN" ] || { log "hot_chunks map was not pinned at $CHUNKS_PIN"; exit 2; }
}

stop_policy() {
	[ -n "$POLICY_PID" ] || return 0
	sudo kill -2 "$POLICY_PID" 2>/dev/null || true
	wait "$POLICY_PID" 2>/dev/null || true
	POLICY_PID=""
	sudo rm -f "$STATS_PIN" "$CHUNKS_PIN" 2>/dev/null || true
}

snap_stats() {
	[ -e "$STATS_PIN" ] || { echo '{}' > "$1"; return 0; }
	sudo "$PY" "$LOAD_HOTSET" stats --pin "$STATS_PIN" --json > "$1"
}

stat_delta() {
	"$PY" - "$1" "$2" "$3" <<'EOF'
import json, sys
b = json.load(open(sys.argv[1])); a = json.load(open(sys.argv[2]))
print(a.get(sys.argv[3], 0) - b.get(sys.argv[3], 0))
EOF
}

start_antagonist() {
	[ -n "$ANTAGONIST_MODE" ] || return 0
	local args=(--rate-mbps "$ANTAGONIST_RATE")
	[ -n "$ANTAGONIST_TARGET" ] && args+=(--target "$ANTAGONIST_TARGET")
	[ "$ANTAGONIST_MODE" = inside ] && args+=(--cgroup "$CGROUP")
	log "starting antagonist ($ANTAGONIST_MODE, ${ANTAGONIST_RATE} MiB/s)"
	"$ANTAGONIST" "${args[@]}" >>"$LOG" 2>&1 &
	ANT_PID=$!
	sleep 5
}

stop_antagonist() {
	[ -n "$ANT_PID" ] || return 0
	sudo kill "$ANT_PID" 2>/dev/null || true
	wait "$ANT_PID" 2>/dev/null || true
	ANT_PID=""
}

run_replay_in_cgroup() {
	# $1 = arm label, $2 = result json path
	local arm="$1" result="$2"
	# t23_convergence_ladder.py:173-182 hard-gates --arm against
	# lru_gen/enabled and only accepts mglru|classic; with MGLRU off (which
	# cache_ext requires) "classic" is the only value it will run under, and
	# the POLICY arm is carried by the result filename instead. The spike's
	# own driver has no such gate, so it gets the real arm name.
	local driver_arm="classic"
	[ "$(basename "$DRIVER")" = "stack_replay.py" ] && driver_arm="$arm"
	sync; sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
	start_antagonist
	log "replay $arm starting (cap=${CAP_G}G budget=$BUDGET driver=$(basename "$DRIVER"))"
	# Join the policy's cgroup, then exec the driver. The driver IS the
	# serving process (it builds the backend in-process), so this is the
	# whole of "put the serving process in the policy cgroup, and nothing
	# else in it".
	# shellcheck disable=SC2086  # DRIVER_EXTRA is intentionally word-split
	sudo -E env \
		SFU_SEISMIC_LOAD_MODE=mmap \
		SFU_SEISMIC_PREFLOOR_HOTSET="$PREFLOOR_HOTSET" \
		SFU_SEISMIC_PREFLOOR_AT_LOAD="$PREFLOOR_AT_LOAD" \
		SFU_SEISMIC_PIN_BUDGET_GB="$PIN_BUDGET_GB" \
		SFU_SEISMIC_MLOCK_FLOOR="$MLOCK_FLOOR" \
		${FEDERATION:+SFU_SEISMIC_FEDERATION=$FEDERATION} \
		sh -c 'echo $$ > '"$CG_PATH"'/cgroup.procs; exec "$@"' _ \
			timeout "$CELL_TIMEOUT" "$PY" "$DRIVER" \
				--arm "$driver_arm" --cap-label "cap${CAP_G}g" \
				--min-passes "$MIN_PASSES" --max-passes "$MAX_PASSES" \
				--top-k "$TOP_K" --queries "$QUERIES" \
				--result-file "$result" $DRIVER_EXTRA >>"$LOG" 2>&1
	stop_antagonist
}

# --- build the production chunk table, ON THIS BOX --------------------------
# Regenerated every run on purpose: the table bakes in os.stat().st_ino, and an
# inode from another machine (or another filesystem, or a rebuilt shard) would
# silently protect nothing. stack-chunks refuses on a missing file, a
# past-EOF extent, or a sidecar/manifest version mismatch.
CHUNKS="$OUTDIR/_${TAG}_hot_chunks.txt"
INODES="$OUTDIR/_${TAG}_hot_inodes.txt"
log "=== building production chunk table from $BUDGET sidecars ==="
"$PY" "$LOAD_HOTSET" stack-chunks \
	--index-dir "$INDEX_DIR" --budget "$BUDGET" \
	--out "$CHUNKS" --inodes-out "$INODES" 2>&1 | tee -a "$LOG"

log "hot inodes: $(tr '\n' ' ' < "$INODES")"

# --- arms -------------------------------------------------------------------
for ARM in $ARMS; do
	log "=== arm $ARM (cap ${CAP_G}G) ==="
	recreate_cgroup
	RESULT="$OUTDIR/${TAG}_${ARM}.json"

	if [ "$ARM" = baseline ]; then
		run_replay_in_cgroup "$ARM" "$RESULT"
		log "  $ARM: no policy attached, no stats to sample"
		continue
	fi

	if [ "$ARM" = hotset ]; then start_policy "$CHUNKS"; else start_policy ""; fi

	BEFORE="$OUTDIR/_${TAG}_${ARM}_stats_before.json"
	AFTER="$OUTDIR/_${TAG}_${ARM}_stats_after.json"
	POST="$OUTDIR/_${TAG}_${ARM}_stats_postexit.json"

	snap_stats "$BEFORE"
	run_replay_in_cgroup "$ARM" "$RESULT"
	# AFTER is taken while the driver has exited but the policy is still
	# attached, so the munmap/zap_pte_range teardown burst lands in POST
	# rather than inside the measured window (the phase-1 lesson).
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

	ADDR=$(stat_delta "$BEFORE" "$AFTER" added_relevant)
	ADDH=$(stat_delta "$BEFORE" "$AFTER" added_hot)
	EVH=$(stat_delta "$BEFORE" "$AFTER" evicted_hot)
	if [ "$ADDR" -eq 0 ]; then
		log "  VERDICT[$ARM]: no relevant folio_added — the policy is NOT seeing the index files (check WATCH_DIR and the inode list)"
	elif [ "$ARM" = hotset ] && [ "$ADDH" -eq 0 ]; then
		log "  VERDICT[$ARM]: folios seen ($ADDR) but NONE matched the hot table — inode mismatch; regenerate the chunk table on this box"
	else
		log "  VERDICT[$ARM]: policy live — added_relevant=$ADDR added_hot=$ADDH evicted_hot=$EVH"
	fi

	stop_policy
done

# --- summary ---------------------------------------------------------------
log "=== summary ==="
"$PY" - "$OUTDIR" "$TAG" $ARMS <<'EOF' 2>&1 | tee -a "$LOG"
import json, os, sys
outdir, tag, arms = sys.argv[1], sys.argv[2], sys.argv[3:]
print("%-10s %10s %10s %10s %10s %8s" %
      ("arm", "majflt", "p50_ms", "p95_ms", "wall_s", "passes"))
for arm in arms:
    p = os.path.join(outdir, "%s_%s.json" % (tag, arm))
    if not os.path.exists(p):
        print("%-10s  (no result — cell failed)" % arm); continue
    d = json.load(open(p))
    f, last = d["converged_state"], d["per_pass"][-1]
    print("%-10s %10s %10s %10s %10s %8d" %
          (arm, f["majflt"], f["p50_ms"], f["p95_ms"],
           last.get("wall_s", "?"), len(d["per_pass"])))
EOF

log "=== done. results + stats snapshots under $OUTDIR (tag $TAG) ==="
