#!/bin/bash
# antagonist_scan.sh — the page-cache polluter for phase-2 situations S2 and S3.
#
# S2 (noisy neighbour): run this OUTSIDE the serving cgroup. It competes for
#     the machine's free memory, so reclaim pressure arrives at the serving
#     cgroup from the global side.
# S3 (rebuild interference): run this INSIDE the serving cgroup (--cgroup
#     NAME). Then it competes for the SAME memory.max the replay is using, and
#     — this is the question S3 asks — hotset_protect will hand its pages to
#     the cold list and evict them first, because they are not in the hot
#     table. That is the exposure case the spike README flags: hot-set
#     protection deprioritises streaming work sharing the cgroup.
#
# Shape: a sequential read of a large file at a configurable byte rate, with
# POSIX_FADV_DONTNEED deliberately NOT issued — we WANT the pages to land in
# the page cache, because polluting it is the point. This is the "export /
# pack-shaped scan" of S3 and the "neighbour streaming a big file" of S2.
#
# Rate limiting is by sleeping between fixed-size reads rather than by pv or
# ionice, so the pollution rate is deterministic and recorded, and so the
# script has no dependency outside coreutils + the venv python.
#
# NEVER WRITES. The default target is a served shard file, and
# data/seismic_150m/ is READ-ONLY by repo rule.
set -eu -o pipefail

SCRIPT_PATH=$(realpath "$0")
SPIKE_DIR=$(dirname "$SCRIPT_PATH")
REPO=$(realpath "$SPIKE_DIR/../..")

PY="${PY:-$REPO/.venv/bin/python3}"
# Default target: a shard file that is NOT forward_data.bin, so the antagonist
# is not accidentally reading the very pages the hot table protects. Override
# with TARGET= for a scan that does collide with the hot set.
TARGET="${TARGET:-$REPO/data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap/posting_lists.bin}"
RATE_MBPS="${RATE_MBPS:-200}"     # sustained read rate
CHUNK_MIB="${CHUNK_MIB:-8}"       # read granularity
DURATION_S="${DURATION_S:-0}"     # 0 = until killed
CGROUP="${CGROUP:-}"              # empty = run outside any named cgroup (S2)

usage() {
	cat >&2 <<'EOF'
Usage: antagonist_scan.sh [--target FILE] [--rate-mbps N] [--chunk-mib N]
                          [--duration-s N] [--cgroup NAME]

  --cgroup NAME   join /sys/fs/cgroup/NAME before scanning (situation S3:
                  the antagonist shares memory.max AND the cache_ext policy
                  with the serving process). Omit for S2.
  --duration-s 0  run until SIGTERM/SIGINT (the bench kills it).
EOF
	exit 2
}

while [ $# -gt 0 ]; do
	case "$1" in
	--target) TARGET="$2"; shift 2 ;;
	--rate-mbps) RATE_MBPS="$2"; shift 2 ;;
	--chunk-mib) CHUNK_MIB="$2"; shift 2 ;;
	--duration-s) DURATION_S="$2"; shift 2 ;;
	--cgroup) CGROUP="$2"; shift 2 ;;
	-h|--help) usage ;;
	*) echo "unknown arg: $1" >&2; usage ;;
	esac
done

[ -r "$TARGET" ] || { echo "antagonist: target not readable: $TARGET" >&2; exit 1; }
[ -x "$PY" ] || { echo "antagonist: missing venv python: $PY" >&2; exit 1; }

SCAN=$(cat <<'PYEOF'
import os, sys, time

target, rate_mbps, chunk_mib, duration_s = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
chunk = chunk_mib * 1024 * 1024
# Seconds of sleep owed per chunk to hold the requested rate.
per_chunk_s = (chunk / (1024.0 * 1024.0)) / rate_mbps
size = os.path.getsize(target)
t0 = time.time()
total = 0
laps = 0
fd = os.open(target, os.O_RDONLY)
# MADV/FADV are deliberately NOT set: default readahead + cache retention is
# exactly the "streaming job that pollutes the cache" behaviour under test.
try:
    while True:
        off = 0
        while off < size:
            if duration_s and (time.time() - t0) >= duration_s:
                raise KeyboardInterrupt
            t_c = time.time()
            n = len(os.pread(fd, chunk, off))
            if n == 0:
                break
            off += n
            total += n
            slack = per_chunk_s - (time.time() - t_c)
            if slack > 0:
                time.sleep(slack)
        laps += 1
except (KeyboardInterrupt, SystemExit):
    pass
finally:
    os.close(fd)
    el = time.time() - t0
    print("antagonist: read %.2f GiB in %.1fs (%.1f MiB/s, %d full passes) over %s"
          % (total / float(1 << 30), el, total / 1048576.0 / max(el, 1e-9), laps, target),
          flush=True)
PYEOF
)

RUN=("$PY" -c "$SCAN" "$TARGET" "$RATE_MBPS" "$CHUNK_MIB" "$DURATION_S")

if [ -n "$CGROUP" ]; then
	CG_PATH="/sys/fs/cgroup/$CGROUP"
	[ -d "$CG_PATH" ] || { echo "antagonist: no such cgroup: $CG_PATH" >&2; exit 1; }
	echo "antagonist: joining $CG_PATH (S3 shape: shares memory.max AND the policy)" >&2
	exec sudo sh -c 'echo $$ > '"$CG_PATH"'/cgroup.procs; exec "$@"' _ "${RUN[@]}"
else
	echo "antagonist: running outside any named cgroup (S2 shape)" >&2
	exec "${RUN[@]}"
fi
