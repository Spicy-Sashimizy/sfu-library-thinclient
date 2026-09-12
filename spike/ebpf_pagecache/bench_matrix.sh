#!/bin/bash
# bench_matrix.sh — run a LIST of phase-1 situations, one cell per line.
#
# RUN THIS ON A cache_ext KERNEL. Never executed anywhere.
#
# bench_mmap_visibility.sh answers one question with three fixed arms. This is
# the same arm mechanics (cgcreate + memory.max, drop_caches, loader in the
# background, stats sampled before teardown, t1d_cell.py reused UNCHANGED)
# driven from a situations file, so the E1 policy ladder and the E2-E8 knob
# sweeps of TEST_SITUATIONS.md can be queued and left to run.
#
# It can drive the UPSTREAM policies as well as ours: cache_ext_fifo.out,
# cache_ext_s3fifo.out, cache_ext_sampling.out, cache_ext_lhd.out,
# cache_ext_mru.out, cache_ext_mglru.out all take the same
# `--watch_dir DIR --cgroup_path PATH` argp surface (cache_ext_fifo.c:21-24 and
# siblings); s3fifo additionally requires `--cgroup_size BYTES`
# (cache_ext_s3fifo.c:25, used as `cache_size = cgroup_size / page_size` at
# :152). Only hotset_protect pins a stats map, so stat columns are blank for
# upstream arms — that is expected, not a failure.
#
# SITUATIONS FILE FORMAT
# ----------------------
# One cell per line, `key=value` fields, whitespace separated. Blank lines and
# lines starting with '#' are ignored. Values must not contain spaces.
#
#   id=<tag>            REQUIRED. Goes in every filename for this cell.
#   policy=<name>       none | hotset | fifo | s3fifo | sampling | lhd | mru | mglru
#                       (`none` = the classic-LRU baseline, no loader at all)
#   table=<v>           hotset only. none (empty table -> the FIFO control) |
#                       auto (build from an earlier row's result for the SAME
#                       cell signature) | an explicit chunk-table path.
#   limit_mib=<N>       table knob, situation E3 (load_hotset.py --limit-mib)
#   corrupt_frac=<F>    table knob, situation E6 (load_hotset.py --corrupt-frac)
#   corrupt_seed=<S>    table knob, default 20260906
#   refresh_at=<N>      situation E8: rewrite the pinned hot map after pass N
#   refresh_table=<p>   the chunk table to install at refresh_at (REQUIRED with
#                       it). `auto-epoch1` = build it from the SAME source
#                       result `table=auto` used, with load_hotset.py
#                       --epoch 1, i.e. the table the switched WORKLOAD moves
#                       to (needs table=auto and a source row run with the
#                       same switch_at/switch_seed/switch_skew).
#   switch_at=<N>       situation E8, workload half: t1d --hotset-switch-pass,
#                       the pass from which the cell draws from a second,
#                       independently seeded hot set. Needs skew=.
#   switch_seed=<S>     t1d --hotset-switch-seed (default: seed ^ 0x5717C8)
#   switch_skew=<spec>  t1d --hotset-switch-skew (default: the same as skew=)
#   cap=<G>             memory.max in GiB (float ok), or `free` for no cap
#   skew=<spec>         t1d --skew, e.g. hotset:0.20:0.80 or hotsetc:0.20:0.80:8
#   seed=<N>            t1d --seed                    (default $SEED)
#   passes=<N>          t1d --passes                  (default $PASSES)
#   frac=<F>            t1d --resident-frac           (default $FRAC)
#   r_mib=<N> l_mib=<N> t1d sizes                     (defaults $R_MIB/$L_MIB)
#   fault_around=1      t1d --fault-around (situation E4)
#   warm_l=0            drop t1d --warm-l (on by default, as in phase 1)
#
# The E1 ladder at the divergence rung is then just:
#
#   id=E1_classic policy=none   cap=1.5 skew=hotset:0.20:0.80 seed=2027
#   id=E1_fifo    policy=fifo   cap=1.5 skew=hotset:0.20:0.80 seed=2027
#   id=E1_s3fifo  policy=s3fifo cap=1.5 skew=hotset:0.20:0.80 seed=2027
#   id=E1_lfu     policy=sampling cap=1.5 skew=hotset:0.20:0.80 seed=2027
#   id=E1_lhd     policy=lhd    cap=1.5 skew=hotset:0.20:0.80 seed=2027
#   id=E1_ctl     policy=hotset table=none cap=1.5 skew=hotset:0.20:0.80 seed=2027
#   id=E1_hotset  policy=hotset table=auto cap=1.5 skew=hotset:0.20:0.80 seed=2027
#
# `table=auto` needs a result JSON carrying the cell's `skew` block, and
# t1d_cell.py --laydown-only exits BEFORE writing one (t1d_cell.py:378-380).
# So an auto row reuses the result of an EARLIER row in this file with the
# same cell signature — which the ladder above provides for free, because the
# classic baseline runs first. Ordering is checked, and a missing baseline is
# a hard error rather than a silently empty table.
set -eu -o pipefail

SCRIPT_PATH=$(realpath "$0")
SPIKE_DIR=$(dirname "$SCRIPT_PATH")
REPO=$(realpath "$SPIKE_DIR/../..")

UPSTREAM="${UPSTREAM:-$SPIKE_DIR/cache_ext_upstream}"
POLICY_DIR="${POLICY_DIR:-$UPSTREAM/policies}"
DRIVER="${DRIVER:-$REPO/spike/convergence_repro/t1d_cell.py}"
PY="${PY:-$REPO/.venv/bin/python3}"
LOAD_HOTSET="${LOAD_HOTSET:-$SPIKE_DIR/load_hotset.py}"

DATADIR="${DATADIR:-/var/tmp/t1d_scratch}"
OUTDIR="${OUTDIR:-$REPO/data/eval_results}"
DATE="${DATE:-$(date +%Y%m%d)}"
CGROUP="${CGROUP:-cache_ext_test}"
CG_PATH="/sys/fs/cgroup/$CGROUP"
CELL_TIMEOUT="${CELL_TIMEOUT:-1800}"

# Row defaults.
R_MIB="${R_MIB:-5120}"
L_MIB="${L_MIB:-1792}"
FRAC="${FRAC:-0.92}"
PASSES="${PASSES:-12}"
SEED="${SEED:-1729}"

STATS_PIN=/sys/fs/bpf/cache_ext/hotset_stats
CHUNKS_PIN=/sys/fs/bpf/cache_ext/hotset_chunks
BPFTOOL="${BPFTOOL:-/usr/local/sbin/bpftool}"

SITUATIONS="${1:-}"
[ -n "$SITUATIONS" ] && [ -f "$SITUATIONS" ] || {
	echo "Usage: bench_matrix.sh <situations-file>" >&2
	echo "See the header of this script for the line format." >&2
	exit 2
}

TAG="matrix_$(basename "$SITUATIONS" | tr -c 'A-Za-z0-9_.-' '_')_${DATE}"
LOG="$OUTDIR/_${TAG}.log"
mkdir -p "$OUTDIR" "$DATADIR"
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }

# --- guards (identical to bench_mmap_visibility.sh) -------------------------
if ! uname -r | grep -q "cache-ext"; then
	echo "This script is intended to be run on a cache_ext kernel." >&2
	echo "Current kernel: $(uname -r)" >&2
	exit 1
fi
[ -f "$DRIVER" ]  || { echo "missing driver: $DRIVER" >&2; exit 1; }
[ -x "$BPFTOOL" ] || { echo "missing bpftool: $BPFTOOL" >&2; exit 1; }
case "$DATADIR" in /mnt/*) echo "DATADIR=$DATADIR is on drvfs/9p — invalid; use an ext4 path" >&2; exit 1 ;; esac
if ! "$UPSTREAM/utils/disable-mglru.sh"; then
	echo "Failed to disable MGLRU — cache_ext hooks would be dead code." >&2
	exit 1
fi
log "MGLRU disabled (lru_gen/enabled = $(cat /sys/kernel/mm/lru_gen/enabled 2>/dev/null || echo absent))"
sudo mkdir -p "$(dirname "$STATS_PIN")"

# policy name -> loader binary. `mglru` here is upstream's cache_ext MGLRU
# REIMPLEMENTATION as a policy, not the kernel's MGLRU (which stays off).
policy_binary() {
	case "$1" in
	hotset)   echo "$POLICY_DIR/hotset_protect.out" ;;
	fifo)     echo "$POLICY_DIR/cache_ext_fifo.out" ;;
	s3fifo)   echo "$POLICY_DIR/cache_ext_s3fifo.out" ;;
	sampling) echo "$POLICY_DIR/cache_ext_sampling.out" ;;
	lhd)      echo "$POLICY_DIR/cache_ext_lhd.out" ;;
	mru)      echo "$POLICY_DIR/cache_ext_mru.out" ;;
	mglru)    echo "$POLICY_DIR/cache_ext_mglru.out" ;;
	*) echo "" ;;
	esac
}

POLICY_PID=""
REFRESH_PID=""

cleanup() {
	local rc=$?
	[ -n "$REFRESH_PID" ] && { kill "$REFRESH_PID" 2>/dev/null || true; REFRESH_PID=""; }
	if [ -n "$POLICY_PID" ]; then
		sudo kill -2 "$POLICY_PID" 2>/dev/null || true
		wait "$POLICY_PID" 2>/dev/null || true
		POLICY_PID=""
	fi
	sudo rm -f "$STATS_PIN" "$CHUNKS_PIN" 2>/dev/null || true
	sudo cgdelete -g "memory:$CGROUP" 2>/dev/null || true
	log "cleanup done (rc=$rc)"
}
trap cleanup EXIT INT TERM

recreate_cgroup() {
	# $1 = cap in GiB, or "free"
	sudo cgdelete -g "memory:$CGROUP" 2>/dev/null || true
	sudo cgcreate -g "memory:$CGROUP"
	if [ "$1" = free ]; then
		sudo sh -c "echo max > $CG_PATH/memory.max"
	else
		sudo sh -c "echo $(awk -v g="$1" 'BEGIN{printf "%d", g*1024*1024*1024}') > $CG_PATH/memory.max"
	fi
	sudo sh -c "echo 0 > $CG_PATH/memory.swap.max"
	log "  cgroup $CGROUP: memory.max=$1, swap.max=0"
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

# --- state carried across rows ---------------------------------------------
LAST_LAYDOWN_SIG=""
# cell signature -> result json, so `table=auto` can find a prior result.
declare -A RESULT_BY_SIG=()

ROWNO=0
while IFS= read -r LINE || [ -n "$LINE" ]; do
	ROWNO=$((ROWNO + 1))
	case "$LINE" in ''|\#*) continue ;; esac

	# --- parse key=value fields -----------------------------------------
	id=""; policy="none"; table="none"
	limit_mib=""; corrupt_frac=""; corrupt_seed="20260906"
	refresh_at=""; refresh_table=""
	switch_at=""; switch_seed=""; switch_skew=""; SRC=""
	cap="1.5"; skew=""; seed="$SEED"; passes="$PASSES"; frac="$FRAC"
	r_mib="$R_MIB"; l_mib="$L_MIB"; fault_around="0"; warm_l="1"
	for FIELD in $LINE; do
		K="${FIELD%%=*}"; V="${FIELD#*=}"
		case "$K" in
		id) id="$V" ;; policy) policy="$V" ;; table) table="$V" ;;
		limit_mib) limit_mib="$V" ;; corrupt_frac) corrupt_frac="$V" ;;
		corrupt_seed) corrupt_seed="$V" ;;
		refresh_at) refresh_at="$V" ;; refresh_table) refresh_table="$V" ;;
		switch_at) switch_at="$V" ;; switch_seed) switch_seed="$V" ;;
		switch_skew) switch_skew="$V" ;;
		cap) cap="$V" ;; skew) skew="$V" ;; seed) seed="$V" ;;
		passes) passes="$V" ;; frac) frac="$V" ;;
		r_mib) r_mib="$V" ;; l_mib) l_mib="$V" ;;
		fault_around) fault_around="$V" ;; warm_l) warm_l="$V" ;;
		*) echo "line $ROWNO: unknown field '$K'" >&2; exit 2 ;;
		esac
	done
	[ -n "$id" ] || { echo "line $ROWNO: missing id=" >&2; exit 2; }
	if [ -n "$switch_at" ] && [ -z "$skew" ]; then
		echo "line $ROWNO ($id): switch_at= needs skew= (a uniform cell has no hot set to switch)" >&2; exit 2
	fi

	CELL_TAG="${id}_${policy}_cap${cap}g_seed${seed}_${DATE}"
	RESULT="$OUTDIR/${TAG}_${CELL_TAG}.json"
	if [ -s "$RESULT" ]; then
		log "SKIP $id — result exists ($RESULT)"
		continue
	fi

	log "=== [$ROWNO] $id: policy=$policy table=$table cap=${cap}G skew=${skew:-uniform} seed=$seed${switch_at:+ hotset-switch@pass$switch_at} ==="

	# --- laydown, only when the file signature actually changes ---------
	# R.bin's inode must be stable across every row that shares a chunk
	# table, so re-laying is avoided whenever possible (t1d --skip-laydown).
	SIG="${r_mib}_${l_mib}_${seed}"
	if [ "$SIG" != "$LAST_LAYDOWN_SIG" ]; then
		log "  laydown (R=${r_mib}MiB L=${l_mib}MiB seed=$seed)"
		"$PY" "$DRIVER" --data-dir "$DATADIR" --r-size-mib "$r_mib" \
			--l-size-mib "$l_mib" --resident-frac "$frac" --seed "$seed" \
			${skew:+--skew "$skew"} --laydown-only \
			--result-file "$OUTDIR/_${TAG}_${id}_laydown.json" >>"$LOG" 2>&1
		LAST_LAYDOWN_SIG="$SIG"
		log "  R.bin ino=$(stat -c %i "$DATADIR/R.bin") L.bin ino=$(stat -c %i "$DATADIR/L.bin")"
	fi

	# --- resolve the chunk table ----------------------------------------
	CHUNKS=""
	if [ "$policy" = hotset ] && [ "$table" != none ]; then
		if [ "$table" = auto ]; then
			CELL_SIG="${skew}_${seed}_${r_mib}_${frac}"
			SRC="${RESULT_BY_SIG[$CELL_SIG]:-}"
			[ -n "$SRC" ] && [ -s "$SRC" ] || {
				echo "line $ROWNO ($id): table=auto but no earlier row in this file has produced a result for cell signature '$CELL_SIG'." >&2
				echo "Put a 'policy=none' row with the same skew/seed/r_mib/frac BEFORE this one (t1d --laydown-only writes no result JSON)." >&2
				exit 2
			}
			CHUNKS="$OUTDIR/_${TAG}_${CELL_TAG}_chunks.txt"
			log "  building chunk table from $SRC"
			"$PY" "$LOAD_HOTSET" chunks --result-json "$SRC" \
				--data-dir "$DATADIR" --out "$CHUNKS" \
				${limit_mib:+--limit-mib "$limit_mib"} \
				${corrupt_frac:+--corrupt-frac "$corrupt_frac" --corrupt-seed "$corrupt_seed"} \
				2>&1 | tee -a "$LOG"
		else
			CHUNKS="$table"
			[ -s "$CHUNKS" ] || { echo "line $ROWNO ($id): table=$CHUNKS not found" >&2; exit 2; }
			[ -n "$limit_mib$corrupt_frac" ] && log "  NOTE: limit_mib/corrupt_frac are ignored for an explicit table path"
		fi
	fi

	# --- cgroup + policy -------------------------------------------------
	recreate_cgroup "$cap"

	if [ "$policy" != none ]; then
		BIN=$(policy_binary "$policy")
		[ -n "$BIN" ] || { echo "line $ROWNO ($id): unknown policy '$policy'" >&2; exit 2; }
		[ -x "$BIN" ] || { echo "line $ROWNO ($id): missing loader $BIN (build_policies.sh / cache_ext_hotset.patch)" >&2; exit 2; }
		CMD=(sudo "$BIN" --watch_dir "$DATADIR" --cgroup_path "$CG_PATH")
		# s3fifo sizes its small/main queues from the cgroup size; every
		# other upstream loader takes only watch_dir + cgroup_path.
		if [ "$policy" = s3fifo ]; then
			if [ "$cap" = free ]; then
				echo "line $ROWNO ($id): s3fifo needs --cgroup_size, which cap=free cannot supply" >&2
				exit 2
			fi
			CMD+=(--cgroup_size "$(awk -v g="$cap" 'BEGIN{printf "%d", g*1024*1024*1024}')")
		fi
		[ -n "$CHUNKS" ] && CMD+=(--hot_chunks "$CHUNKS")
		log "  starting policy: ${CMD[*]}"
		"${CMD[@]}" >>"$LOG" 2>&1 &
		POLICY_PID=$!
		sleep 10
		kill -0 "$POLICY_PID" 2>/dev/null || { log "  policy loader exited early — see $LOG"; exit 2; }
	fi

	BEFORE="$OUTDIR/_${TAG}_${CELL_TAG}_stats_before.json"
	AFTER="$OUTDIR/_${TAG}_${CELL_TAG}_stats_after.json"
	POST="$OUTDIR/_${TAG}_${CELL_TAG}_stats_postexit.json"
	snap_stats "$BEFORE"

	CELL_LOG="$OUTDIR/_${TAG}_${CELL_TAG}_cell.log"
	: > "$CELL_LOG"

	# --- E8: refresh the pinned map mid-run ------------------------------
	# BOTH halves of E8 are available since 2026-09-06: this block rewrites
	# the POLICY's hot table after pass N, and switch_at= (t1d_cell.py
	# --hotset-switch-pass) moves the WORKLOAD's draw to a second, seeded hot
	# set at the same pass. A row with refresh_at= but no switch_at= is still
	# legal and still measures "the table changes under a steady workload" (a
	# timed variant of E6) — that is a choice now, not the only option. Set
	# refresh_at == switch_at and refresh_table=auto-epoch1 for the real
	# "refresh tracks a moved workload" arm.
	if [ -n "$refresh_at" ]; then
		[ "$policy" = hotset ] || { echo "line $ROWNO ($id): refresh_at needs policy=hotset" >&2; exit 2; }
		if [ "$refresh_table" = auto-epoch1 ]; then
			[ "$table" = auto ] || { echo "line $ROWNO ($id): refresh_table=auto-epoch1 needs table=auto (it reuses that row's source result)" >&2; exit 2; }
			REFRESH_CHUNKS="$OUTDIR/_${TAG}_${CELL_TAG}_chunks_epoch1.txt"
			log "  building epoch-1 (post-switch) refresh table from $SRC"
			"$PY" "$LOAD_HOTSET" chunks --result-json "$SRC" \
				--data-dir "$DATADIR" --epoch 1 --out "$REFRESH_CHUNKS" \
				${limit_mib:+--limit-mib "$limit_mib"} \
				${corrupt_frac:+--corrupt-frac "$corrupt_frac" --corrupt-seed "$corrupt_seed"} \
				2>&1 | tee -a "$LOG"
			refresh_table="$REFRESH_CHUNKS"
			# The source result must have been switched the SAME way, or the
			# refresh table tracks a workload move this cell never makes.
			if [ -n "$switch_at" ]; then
				SRC_SW=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("hotset_switch",{}).get("switch_pass",""))' "$SRC")
				[ "$SRC_SW" = "$switch_at" ] || { echo "line $ROWNO ($id): refresh_table=auto-epoch1 but the source result switched at pass '$SRC_SW', not '$switch_at'" >&2; exit 2; }
			fi
		fi
		[ -s "$refresh_table" ] || { echo "line $ROWNO ($id): refresh_at needs refresh_table=<existing chunk table> or auto-epoch1" >&2; exit 2; }
		log "  E8: will refresh the pinned map after t1d pass $refresh_at"
		(
			# t1d_cell.py:541 logs '[t1d] pass %d: majflt ...' per pass, so
			# the trigger is that line appearing in the cell log. Polled
			# rather than `tail -F`-piped: a pipeline leaves an orphan tail
			# behind when the reader breaks, and this subshell has to die
			# cleanly on kill when the cell finishes without reaching pass N.
			while sleep 2; do
				if grep -qF "[t1d] pass $refresh_at: " "$CELL_LOG" 2>/dev/null; then
					"$PY" "$LOAD_HOTSET" refresh \
						--loader "$(policy_binary hotset)" \
						--hot-chunks "$refresh_table" --pin "$CHUNKS_PIN" \
						>>"$LOG" 2>&1
					echo "[matrix] refreshed hot map after pass $refresh_at" >>"$LOG"
					break
				fi
			done
		) &
		REFRESH_PID=$!
	fi

	# --- the cell (t1d_cell.py reused UNCHANGED) --------------------------
	sync; sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
	set +e
	sudo sh -c 'echo $$ > '"$CG_PATH"'/cgroup.procs; exec "$@"' _ \
		timeout "$CELL_TIMEOUT" "$PY" "$DRIVER" \
			--data-dir "$DATADIR" --r-size-mib "$r_mib" --l-size-mib "$l_mib" \
			--resident-frac "$frac" --passes "$passes" --seed "$seed" \
			--arm "$id" --cap-label "cap${cap}g" --skip-laydown \
			${skew:+--skew "$skew"} \
			${switch_at:+--hotset-switch-pass "$switch_at"} \
			${switch_seed:+--hotset-switch-seed "$switch_seed"} \
			${switch_skew:+--hotset-switch-skew "$switch_skew"} \
			$([ "$warm_l" = 1 ] && echo --warm-l) \
			$([ "$fault_around" = 1 ] && echo --fault-around) \
			--result-file "$RESULT" >>"$CELL_LOG" 2>&1
	RC=$?
	set -e
	cat "$CELL_LOG" >> "$LOG"
	[ -n "$REFRESH_PID" ] && { kill "$REFRESH_PID" 2>/dev/null || true; REFRESH_PID=""; }

	snap_stats "$AFTER"
	sleep 2
	snap_stats "$POST"

	if [ "$RC" -ne 0 ] || [ ! -s "$RESULT" ]; then
		log "  CELL FAILED rc=$RC (see $CELL_LOG) — continuing to the next row"
	else
		CELL_SIG="${skew}_${seed}_${r_mib}_${frac}"
		RESULT_BY_SIG["$CELL_SIG"]="$RESULT"
		log "  cell done -> $RESULT"
	fi

	if [ -e "$BEFORE" ] && [ "$(cat "$BEFORE")" != "{}" ]; then
		for K in added_relevant added_hot added_cold accessed_calls \
		         accessed_relevant evicted_hot evict_from_cold \
		         evict_from_hot evict_hot_fallback scan_cold scan_hot; do
			log "  $id delta $K = $(stat_delta "$BEFORE" "$AFTER" "$K") (post-exit $(stat_delta "$BEFORE" "$POST" "$K"))"
		done
	elif [ "$policy" != none ]; then
		log "  (no stats: $policy is an upstream policy and pins no counter map)"
	fi

	if [ -n "$POLICY_PID" ]; then
		sudo kill -2 "$POLICY_PID" 2>/dev/null || true
		wait "$POLICY_PID" 2>/dev/null || true
		POLICY_PID=""
		sudo rm -f "$STATS_PIN" "$CHUNKS_PIN" 2>/dev/null || true
	fi
done < "$SITUATIONS"

# --- summary ---------------------------------------------------------------
log "=== summary ==="
"$PY" - "$OUTDIR" "$TAG" <<'EOF' 2>&1 | tee -a "$LOG"
import glob, json, os, sys
outdir, tag = sys.argv[1], sys.argv[2]
rows = []
for p in sorted(glob.glob(os.path.join(outdir, "%s_*.json" % tag))):
    if os.path.basename(p).startswith("_"):
        continue
    try:
        d = json.load(open(p))
    except Exception:
        continue
    pp = d.get("per_pass") or d.get("passes") or []
    if not pp:
        continue
    tail = pp[-3:]
    floor = sum(x["majflt"] for x in tail) / float(len(tail))
    rows.append((d.get("arm", "?"), d.get("cap_label", "?"), floor,
                 round(sum(x.get("wall_s", 0) for x in tail) / len(tail), 1),
                 len(pp)))
print("%-24s %-10s %14s %10s %7s" % ("arm", "cap", "majflt floor", "wall_s", "passes"))
for r in sorted(rows):
    print("%-24s %-10s %14.0f %10s %7d" % r)
print("\nfloor = mean majflt of the last 3 passes (the t1d convention)")
EOF

log "=== done. tag $TAG under $OUTDIR ==="
