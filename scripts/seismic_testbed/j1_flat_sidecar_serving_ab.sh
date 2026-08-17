#!/usr/bin/env bash
# J1 driver — SERVING A/B of the PUBLISHED flat abstract sidecar (doc 18 §22
# "still not settled" #1). Sequences the four phases of
# `j1_flat_sidecar_serving_ab.py`; see that file's docstring for the design and
# the in-source pre-registration.
#
#   1. collect      real bm25f top-100 result sets, frozen to JSON
#   2. cold         one arm per FRESH PROCESS, page cache evicted before each.
#                   Two reps with the arm order REVERSED, so a residual
#                   ordering effect (arm 2 reusing arm 1's metadata faults on
#                   the shared 9p mount) shows up as a rep-to-rep spread rather
#                   than as a result.
#   3. warm         all arms in one process, order randomised per trial, plus
#                   the byte-parity gate (doc 18 §14/§17 discipline)
#   4. verdict      merge + apply the pre-registered bars
#   5. stage        byte-copy the PUBLISHED bytes to LOCAL DISK (overlay)
#   6. local        phases 2-4 again on the staged copy
#
# WHY PHASES 5-6 EXIST. `data/thinclient_index` is 9p. Doc 18 §16 measured this
# exact payload move at 2.89x on 9p and 1.21x on LOCAL DISK — the filesystem is
# worth more than the change under test, and §14 is the section that exists
# because an earlier run forgot that. Phases 2-4 answer "what does THIS
# container get"; phases 5-6 answer "what does a droplet get", by re-running
# the identical arms over the identical published bytes with only the
# filesystem changed. Neither is quoted alone.
#
# Read-only w.r.t. data/thinclient_index: the arms are symlink views under
# /var/tmp and `stage` only reads. Nothing there is moved, renamed or written.
set -u
cd /workspaces/sfu-library-thinclient

PY=.venv/bin/python3
H=scripts/seismic_testbed/j1_flat_sidecar_serving_ab.py
EV=data/eval_results
IDS=$EV/j1_flat_idsets_20260817.json
WORK=/var/tmp/j1_flat_ab
WORK_LOCAL=/var/tmp/j1_flat_ab_local
STAGE=${STAGE:-/var/tmp/j1_abs_stage}
TOPK=${TOPK:-50}

# COLD MECHANISM (measured 2026-08-17). The doc-18 precedent
# (`sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'`, f4/serve_footprint_bench)
# CANNOT RUN HERE: sudo succeeds and the write still fails —
# "cannot create /proc/sys/vm/drop_caches: Read-only file system" — because
# this is WSL2. `bench --evict` therefore uses
# posix_fadvise(POSIX_FADV_DONTNEED) over every file of the section instead,
# and records the measured `Cached:` delta so the results file can be judged on
# whether eviction happened rather than on the call returning 0. It evicts BOTH
# arms' files on every run, so arm order cannot leave one arm warmer.

if [ ! -f "$IDS" ]; then
  echo "== 1. collect =="
  $PY "$H" collect --queries 120 --top-k 100 --out "$IDS" || exit 1
else
  echo "== 1. collect — reusing $IDS =="
fi

# $1 = tag ("" for the published 9p path, "local_" for the staged copy)
# $2 = --work dir   $3.. = extra args passed to bench/interleaved (--src ...)
run_ab() {
  tag=$1; work=$2; shift 2
  echo "== 2. cold ${tag:-9p} (fresh process per arm, top_k=$TOPK) =="
  for rep in 1 2; do
    if [ "$rep" = 1 ]; then order="sqlite flat"; else order="flat sqlite"; fi
    for arm in $order; do
      echo "-- rep$rep arm=$arm"
      $PY "$H" bench --arm "$arm" --ids "$IDS" --work "$work" --top-k "$TOPK" \
          --passes 3 --evict "$@" \
          --out "$EV/j1_flat_serving_cold_${tag}${arm}_rep${rep}_20260817.json" || exit 1
    done
  done

  echo "== 3. warm interleaved ${tag:-9p} =="
  $PY "$H" interleaved --ids "$IDS" --work "$work" --top-k 50 100 \
      --trials 300 --warmup 20 "$@" \
      --out "$EV/j1_flat_serving_warm_${tag}20260817.json" || exit 1

  echo "== 4. verdict ${tag:-9p} =="
  $PY "$H" verdict \
      --interleaved "$EV/j1_flat_serving_warm_${tag}20260817.json" \
      --cold $EV/j1_flat_serving_cold_${tag}sqlite_rep*_20260817.json \
             $EV/j1_flat_serving_cold_${tag}flat_rep*_20260817.json \
      --primary-top-k "$TOPK" \
      --out "$EV/j1_flat_serving_verdict_${tag}20260817.json" || exit 1
}

run_ab "" "$WORK"

echo "== 5. stage the published bytes to local disk =="
$PY "$H" stage --dest "$STAGE" || exit 1

echo "== 6. the same A/B, local disk (the droplet-transferable number) =="
rm -rf "$WORK_LOCAL"
run_ab "local_" "$WORK_LOCAL" --src "$STAGE/abstracts.sqlite"
