#!/usr/bin/env bash
# =====================================================================
# convergence_repro — HOST-SIDE ORCHESTRATOR
#
# Runs the 5-rung ladder of memory-capped sibling containers, one cell at a
# time, collecting one JSON per cell into data/eval_results/.
#
#   docker run --rm --memory=X --memory-swap=X -v convrepro_data:/data \
#              convrepro:latest
#
# --memory-swap == --memory forbids swap (the R1 method; a cell that swaps
# anyway is marked swap_confounded by cell.sh and must be recorded-not-
# concluded).
#
# THE DATA LIVES IN A DOCKER NAMED VOLUME. Never bind-mount a path from a dev
# container: `-v /path:/data` resolves on the DOCKER HOST, not in the client's
# namespace, and this repo's workspace is v9fs (9p) which must never carry
# benchmark data anyway.
#
# Between cells the volume is re-evicted by a FRESH UNCAPPED container running
# `vmtouch -e` on R and L — per-file eviction, never global drop_caches.
#
# Usage:
#   ./run_ladder.sh                          # full fixed-3 ladder at SCALE=1
#   ./run_ladder.sh --mode converge          # convergence-terminated ladder
#   ./run_ladder.sh --smoke                  # SCALE=0.2, fixed3, all rungs
#   ./run_ladder.sh --rungs marginal,boundary
#   ./run_ladder.sh --local                  # NO-DOCKER mechanics run (see below)
#   ./run_ladder.sh --early-sort guided      # one early-sort ladder (see below)
#   ./run_ladder.sh --es-matrix              # the whole pre-registered ES matrix
#   ./run_ladder.sh --order-arm              # the ONE exploratory order-arm cell
#
# TIER-1b (PREREGISTRATION_TIER1B.md). Three things changed here:
#   * RUNG_GIB is the Tier-1b ladder (marginal 6.25g, all rungs sized so the
#     deficit D-cap is real). Tier-1's tuned 6.64g is RETIRED — it was
#     calibrated against the broken L-then-R load order.
#   * Result files are named convrepro_t1b_*; smoke/local mechanics cells are
#     named convrepro_mech_* instead, so the documented analyze glob
#     'convrepro_t1b_*_<date>.json' excludes them BY CONSTRUCTION (defect D1).
#   * --build-only now does image AND volume laydown, as its label claims (D2).
#   * The image is rebuilt whenever Dockerfile/cell.sh/jobs change (D4): the
#     old 'tag exists -> skip build' test would have run Tier-1's cell.sh
#     for the Tier-1b ladder. See RESULTS.md Tier-1b section 15.
#
# EXPLORATORY ORDER ARM (recorded, NEVER judged)
#   --load-order interleaved|r_then_l|l_then_r
#     interleaved is the Tier-1b protocol (default). The other two are stamped
#     load_phase.order_arm=true in the cell JSON and analyze.py keeps them out
#     of the bars by construction. --order-arm is the pre-registered shortcut:
#     exactly one cell, marginal rung, fixed3, load order r_then_l.
#
# EARLY-SORT ARM (PREREGISTRATION_EARLYSORT.md)
#   --early-sort none|guided|blind   threads EARLY_SORT into every cell.
#     guided : vmtouch -e L.bin between load and pass 1 (map-guided F5 analogue)
#     blind  : write L's byte count to the cell cgroup's memory.reclaim
#              (map-blind / TMO analogue). NOTE: docker mounts /sys/fs/cgroup
#              READ-ONLY, so an ordinary cell cannot write memory.reclaim and the
#              arm records BLOCKED. --es-privileged (ON by default for blind
#              cells only) adds --privileged to those cells, which is what makes
#              the cgroup mount writable; --memory is still enforced. Use
#              --no-es-privileged to measure the blocked path deliberately.
#   --es-matrix  runs the pre-registered matrix in one go:
#       fixed3 x {guided,blind} x {fits,marginal,boundary,thrash}
#     + converge x {guided}      x {marginal,boundary}
#     Baselines are NOT re-run: the `none` cells must come from the Tier-1
#     ladder run on the SAME DAY at the same scale/mode (analyze.py pairs on
#     run_label + date and refuses to pair across runs).
#   Early-sort results are written as
#       convrepro_t1b_es_<esmode>_<rung>_<cellmode>[_orderXX]_<date>.json
#   Baseline (`none`) cells are convrepro_t1b_<rung>_<cellmode>_<date>.json.
#   Smoke/local cells swap the t1b_ prefix for mech_ (defect D1).
#
# --local runs cell.sh directly on this host with NO memory cap. It exists only
# to validate the harness mechanics (eviction, fio parsing, majflt, cgroup
# fields, JSON shape) where docker cannot run. Cells are stamped
# cap_enforced=false and analyze.py will REFUSE to issue a bar verdict.
# =====================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

# ------------------------------------------------------------- defaults
IMAGE="convrepro:latest"
VOLUME="convrepro_data"
MODE="fixed3"
SCALE="1.0"
PASSES=3
MAX_PASSES=12
MIN_PASSES=3
SEED=20260831
HEADROOM_MIB=""            # auto: 0 at SCALE>=1, 256 below (see below)
OUT_DIR="$REPO/data/eval_results"
RUNGS="fits,marginal,boundary,thrash,deep"
SMOKE=0
LOCAL=0
LOCAL_DATA_DIR="/var/tmp/convrepro_data"     # overlay/ext4 — NEVER the 9p workspace
FORCE_LAYDOWN=0
BUILD_ONLY=0
EARLY_SORT="none"          # none | guided | blind  (PREREGISTRATION_EARLYSORT.md)
ES_MATRIX=0
ES_PRIVILEGED=1            # blind cells only: grant a writable cgroup mount
LOAD_ORDER="interleaved"   # interleaved | r_then_l | l_then_r  (Tier-1b)
ORDER_ARM_ONLY=0
PASSTHRU=()                # args forwarded verbatim by --es-matrix

# Rung table (PREREGISTRATION_TIER1B.md Change 2): base cap in GiB at SCALE=1.
# R = 5 GiB, L = 1.75 GiB, D = 6.75 GiB.  Every rung below `fits` now sits
# BELOW D, so the interleaved load actually evicts and pass 1 starts with R
# only partially resident.
#   fits     10    g = 1.48 x D   (no deficit; control, bar 5)
#   marginal  6.25 g = 0.93 x D   deficit 0.50 GiB  <- the lazy-sort cell
#   boundary  5.75 g = 1.15 x R   deficit 1.00 GiB  <- the fast-sort winner
#   thrash    3.75 g = 0.75 x R   deficit 3.00 GiB  (below-R cliff)
#   deep      2.75 g = 0.55 x R   deficit 4.00 GiB  (deep cliff)
# Tier-1's tuned marginal 6.64g is RETIRED (RESULTS.md §3): it was calibrated
# against the L-then-R load order that Change 1 replaces.
# Calibration gate (PREREGISTRATION_TIER1B.md, EXHAUSTIVE): marginal may move
# inside [6.0, 6.5] for at most 3 steps; nothing else here may be tuned.
declare -A RUNG_GIB=( [fits]=10 [marginal]=6.25 [boundary]=5.75 [thrash]=3.75 [deep]=2.75 )
RUNG_ORDER=(fits marginal boundary thrash deep)

R_BASE_MIB=5120      # 5    GiB
L_BASE_MIB=1792      # 1.75 GiB

# print the whole leading comment banner
usage() { awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "$0"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --smoke)        SMOKE=1; SCALE="0.2"; MODE="fixed3"; PASSTHRU+=("$1"); shift ;;
    --mode)         MODE="$2"; shift 2 ;;
    --rungs)        RUNGS="$2"; shift 2 ;;
    --early-sort)   EARLY_SORT="$2"; shift 2 ;;
    --load-order)   LOAD_ORDER="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --order-arm)    ORDER_ARM_ONLY=1; shift ;;
    --es-matrix)    ES_MATRIX=1; shift ;;
    --es-privileged)    ES_PRIVILEGED=1; PASSTHRU+=("$1"); shift ;;
    --no-es-privileged) ES_PRIVILEGED=0; PASSTHRU+=("$1"); shift ;;
    --scale)        SCALE="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --passes)       PASSES="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --max-passes)   MAX_PASSES="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --min-passes)   MIN_PASSES="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --headroom-mib) HEADROOM_MIB="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --seed)         SEED="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --out-dir)      OUT_DIR="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --image)        IMAGE="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --volume)       VOLUME="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --local)        LOCAL=1; PASSTHRU+=("$1"); shift ;;
    --local-data-dir) LOCAL_DATA_DIR="$2"; PASSTHRU+=("$1" "$2"); shift 2 ;;
    --force-laydown) FORCE_LAYDOWN=1; PASSTHRU+=("$1"); shift ;;
    --build-only)   BUILD_ONLY=1; shift ;;
    -h|--help)      usage ;;
    *) echo "unknown flag: $1" >&2; exit 64 ;;
  esac
done

case "$MODE" in fixed3|converge) ;; *) echo "--mode must be fixed3|converge" >&2; exit 64 ;; esac
case "$EARLY_SORT" in none|guided|blind) ;;
  *) echo "--early-sort must be none|guided|blind" >&2; exit 64 ;; esac
case "$LOAD_ORDER" in interleaved|r_then_l|l_then_r) ;;
  *) echo "--load-order must be interleaved|r_then_l|l_then_r" >&2; exit 64 ;; esac

# ---- --order-arm: the ONE pre-registered exploratory order-arm cell --------
# PREREGISTRATION_TIER1B.md "Exploratory order arm": marginal rung, fixed3,
# load order R then L. Informational only — analyze.py never scores it.
if [ "$ORDER_ARM_ONLY" -eq 1 ]; then
  MODE="fixed3"; RUNGS="marginal"; LOAD_ORDER="r_then_l"; EARLY_SORT="none"
fi

# ---- --es-matrix: the pre-registered early-sort cell matrix ----------
# (PREREGISTRATION_EARLYSORT.md "Cells"): rungs {fits,marginal,boundary,thrash}
# x {guided,blind} in fixed3, plus converge at marginal+boundary for guided.
# Implemented by re-invoking this script once per (early-sort mode, cell mode)
# leg so every leg gets the normal image/volume/laydown handling.
if [ "$ES_MATRIX" -eq 1 ]; then
  ES_RC=0
  run_leg() {   # run_leg <early-sort> <mode> <rungs>
    printf '\n########## ES MATRIX LEG: early-sort=%s mode=%s rungs=%s\n' "$1" "$2" "$3" >&2
    bash "${BASH_SOURCE[0]}" "${PASSTHRU[@]+"${PASSTHRU[@]}"}" \
         --early-sort "$1" --mode "$2" --rungs "$3" || ES_RC=$?
  }
  run_leg guided fixed3   "fits,marginal,boundary,thrash"
  run_leg blind  fixed3   "fits,marginal,boundary,thrash"
  run_leg guided converge "marginal,boundary"
  printf '\n########## ES MATRIX DONE (rc=%s). Baseline `none` cells must come from\n' "$ES_RC" >&2
  printf '########## the Tier-1 ladder run TODAY at the same scale — analyze.py\n' >&2
  printf '########## pairs on run_label + date and never pairs across runs.\n' >&2
  exit "$ES_RC"
fi

# ---- headroom policy -------------------------------------------------
# The caps in the pre-registration are sized against FILE demand only (fio's
# anon footprint is ~50 MB, negligible against a 2.75 GiB cap). At reduced
# SCALE the caps shrink proportionally and that anon footprint stops being
# negligible, so we add a FIXED headroom ON TOP of the scaled cap. Adding it on
# top (rather than inside) keeps the quantity that actually matters — the file
# budget cap_file = cap - headroom — scaling exactly with R and L, so the
# regime ratios cap_file/R and cap_file/D are preserved across scales.
if [ -z "$HEADROOM_MIB" ]; then
  if awk -v s="$SCALE" 'BEGIN{exit !(s>=1.0)}'; then HEADROOM_MIB=0; else HEADROOM_MIB=256; fi
fi

R_MIB=$(awk -v b="$R_BASE_MIB" -v s="$SCALE" 'BEGIN{printf "%d", int(b*s+0.5)}')
L_MIB=$(awk -v b="$L_BASE_MIB" -v s="$SCALE" 'BEGIN{printf "%d", int(b*s+0.5)}')
DATE_TAG="$(date +%Y%m%d)"
SMOKE_TAG=""; [ "$SMOKE" -eq 1 ] && SMOKE_TAG="_smoke"
[ "$LOCAL" -eq 1 ] && SMOKE_TAG="${SMOKE_TAG}_nocap"
ORDER_TAG=""; [ "$LOAD_ORDER" = "interleaved" ] || ORDER_TAG="_order${LOAD_ORDER}"
# DEFECT D1 FIX (RESULTS.md §6). A cell that can NEVER be bar evidence — a
# reduced-SCALE smoke cell or an uncapped --local mechanics cell — is written
# under the prefix `convrepro_mech_` instead of `convrepro_t1b_`. The
# documented analyze glob is 'convrepro_t1b_*_<date>.json', which cannot match
# a mech_ file no matter what date it carries: the exclusion is structural, not
# a filter someone has to remember (Tier-1's bug was exactly that).
FILE_PREFIX="convrepro_t1b"
if [ "$SMOKE" -eq 1 ] || [ "$LOCAL" -eq 1 ]; then FILE_PREFIX="convrepro_mech"; fi
# RUN_LABEL deliberately does NOT encode EARLY_SORT: analyze.py pairs an
# early-sort cell with its `none` baseline by (run_label, date, rung, mode), so
# the label must be identical across the two arms of the same run.
RUN_LABEL="scale${SCALE}_${MODE}${SMOKE_TAG}"

# Result filename.
out_path_for() {   # out_path_for <rung>
  if [ "$EARLY_SORT" = "none" ]; then
    echo "$OUT_DIR/${FILE_PREFIX}_${1}_${MODE}${ORDER_TAG}${SMOKE_TAG}_${DATE_TAG}.json"
  else
    echo "$OUT_DIR/${FILE_PREFIX}_es_${EARLY_SORT}_${1}_${MODE}${ORDER_TAG}${SMOKE_TAG}_${DATE_TAG}.json"
  fi
}

say() { printf '\n=== %s\n' "$*" >&2; }

es_summary() {   # es_summary <cell.json>  -> one stderr line, only for ES cells
  [ "$EARLY_SORT" = "none" ] && return 0
  python3 - "$1" <<'PY' >&2
import json, sys
try:
    e = json.load(open(sys.argv[1])).get("early_sort") or {}
except Exception as exc:
    print(f"  early_sort: could not read ({exc})"); raise SystemExit(0)
flags = [k for k in ("applied", "blocked", "early_sort_failed") if e.get(k)]
print("  early_sort: mode={} {} wall={}s R={}% L={}% freed={} req={}{}".format(
    e.get("mode"), "/".join(flags) or "no-action", e.get("action_wall_s"),
    e.get("post_action_resident_pct_R"), e.get("post_action_resident_pct_L"),
    e.get("bytes_freed_observed"), e.get("bytes_requested"),
    ("  reason=" + str(e.get("blocked_reason") or e.get("failed_reason")))
    if (e.get("blocked") or e.get("early_sort_failed")) else ""))
PY
}

say "convergence_repro TIER-1b ladder | mode=$MODE scale=$SCALE R=${R_MIB}MiB L=${L_MIB}MiB headroom=${HEADROOM_MIB}MiB early_sort=$EARLY_SORT load_order=$LOAD_ORDER"
[ "$LOAD_ORDER" = "interleaved" ] || say "!! EXPLORATORY ORDER ARM (load_order=$LOAD_ORDER) — recorded, NEVER judged"
[ "$FILE_PREFIX" = "convrepro_mech" ] && say "!! MECHANICS cells (prefix convrepro_mech_) — excluded from the bar glob by construction"
say "rungs: $RUNGS | out: $OUT_DIR | seed=$SEED | backend=$([ "$LOCAL" -eq 1 ] && echo LOCAL-UNCAPPED || echo docker)"
mkdir -p "$OUT_DIR"

cap_mib_for() {   # cap_mib_for <rung> -> integer MiB (scaled + headroom)
  awk -v g="${RUNG_GIB[$1]}" -v s="$SCALE" -v h="$HEADROOM_MIB" \
      'BEGIN{ printf "%d", int(g*1024*s + 0.5) + h }'
}

# =====================================================================
#                           LOCAL (no-docker) BACKEND
# =====================================================================
if [ "$LOCAL" -eq 1 ]; then
  for b in fio vmtouch /usr/bin/time python3; do
    command -v "$b" >/dev/null 2>&1 || [ -x "$b" ] || { echo "missing $b" >&2; exit 70; }
  done
  case "$(stat -fc %T "$(dirname "$LOCAL_DATA_DIR")" 2>/dev/null)" in
    9p|v9fs) echo "REFUSING: $LOCAL_DATA_DIR is on 9p — benchmark data must not live there" >&2; exit 71 ;;
  esac
  mkdir -p "$LOCAL_DATA_DIR" || { echo "cannot create $LOCAL_DATA_DIR" >&2; exit 71; }

  R_FILE="$LOCAL_DATA_DIR/R.bin"; L_FILE="$LOCAL_DATA_DIR/L.bin"
  want_r=$(( R_MIB * 1048576 )); want_l=$(( L_MIB * 1048576 ))
  have_r=$(stat -c %s "$R_FILE" 2>/dev/null || echo 0)
  have_l=$(stat -c %s "$L_FILE" 2>/dev/null || echo 0)
  if [ "$FORCE_LAYDOWN" -eq 1 ] || [ "$have_r" != "$want_r" ] || [ "$have_l" != "$want_l" ]; then
    say "laying down R=${R_MIB}MiB L=${L_MIB}MiB in $LOCAL_DATA_DIR (deterministic, seed=$SEED)"
    rm -f "$R_FILE" "$L_FILE"
    R_FILE="$R_FILE" L_FILE="$L_FILE" R_SIZE="${R_MIB}M" L_SIZE="${L_MIB}M" \
      FIO_RANDSEED="$SEED" fio "$HERE/jobs/laydown.fio" --output-format=json \
      --output=/dev/null >/dev/null || { echo "laydown failed" >&2; exit 72; }
  else
    say "data already present at the requested scale — skipping laydown"
  fi
  if [ "$BUILD_ONLY" -eq 1 ]; then
    say "--build-only (--local): data laid down in $LOCAL_DATA_DIR. Done."
    exit 0
  fi

  for rung in "${RUNG_ORDER[@]}"; do
    case ",$RUNGS," in *",$rung,"*) ;; *) continue ;; esac
    cap_mib="$(cap_mib_for "$rung")"
    out="$(out_path_for "$rung")"
    say "cell $rung (cap ${RUNG_GIB[$rung]}g nominal -> ${cap_mib}MiB, NOT ENFORCED in --local) early_sort=$EARLY_SORT"
    RUNG="$rung" CAP_LABEL="${RUNG_GIB[$rung]}g" SCALE="$SCALE" MODE="$MODE" \
    PASSES="$PASSES" MAX_PASSES="$MAX_PASSES" MIN_PASSES="$MIN_PASSES" \
    DATA_DIR="$LOCAL_DATA_DIR" JOBS_DIR="$HERE/jobs" FIO_RANDSEED="$SEED" \
    R_SIZE_MIB="$R_MIB" L_SIZE_MIB="$L_MIB" CAP_ENFORCED=0 RUN_LABEL="$RUN_LABEL" \
    CAP_BYTES_NOMINAL="$(( cap_mib * 1048576 ))" SKIP_LOAD="${SKIP_LOAD:-0}" \
    EARLY_SORT="$EARLY_SORT" ES_CGROUP_WRITE_GRANT="none (--local backend)" \
    LOAD_ORDER="$LOAD_ORDER" \
      bash "$HERE/cell.sh" > "$out.raw" 2>"$out.log"
    rc=$?
    if [ $rc -ne 0 ]; then
      echo "cell $rung FAILED rc=$rc — see $out.log" >&2; tail -n 5 "$out.log" >&2; continue
    fi
    sed -n '/===CONVREPRO_JSON_BEGIN===/,/===CONVREPRO_JSON_END===/p' "$out.raw" \
      | sed '1d;$d' > "$out"
    rm -f "$out.raw"
    python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$out" \
      || { echo "cell $rung produced malformed JSON" >&2; continue; }
    es_summary "$out"
    say "wrote $out"
    vmtouch -e "$R_FILE" "$L_FILE" >/dev/null 2>&1
  done
  say "LOCAL ladder done. NOTE: caps were NOT enforced — mechanics only, not a bar verdict."
  exit 0
fi

# =====================================================================
#                           DOCKER BACKEND
# =====================================================================
command -v docker >/dev/null 2>&1 || { echo "docker CLI not found" >&2; exit 70; }
docker info >/dev/null 2>&1 || { echo "cannot reach the docker daemon" >&2; exit 70; }

# ---- 1. image (idempotent, WITH a staleness guard) --------------------
# DEFECT D4 FIX (RESULTS.md Tier-1b §15): this block used to skip the build
# whenever the tag existed, with no staleness check. cell.sh and jobs/ are
# baked into the image by COPY, so a protocol change to cell.sh would be
# silently ignored and the OLD cell.sh would run the new ladder. That very
# nearly happened on the 2026-08-31 Tier-1b host run. The build inputs are
# now hashed into an image label and the image is rebuilt when it drifts.
BUILD_HASH="$(cat "$HERE/Dockerfile" "$HERE/cell.sh" "$HERE"/jobs/*.fio \
              | sha256sum | cut -c1-16)"
IMAGE_HASH="$(docker image inspect \
                -f '{{ index .Config.Labels "convrepro.build_hash" }}' \
                "$IMAGE" 2>/dev/null || true)"
if [ "$IMAGE_HASH" != "$BUILD_HASH" ]; then
  if [ -n "$IMAGE_HASH" ]; then
    say "image $IMAGE is STALE (label $IMAGE_HASH != inputs $BUILD_HASH) — rebuilding"
  else
    say "building $IMAGE (build_hash $BUILD_HASH)"
  fi
  docker build --label "convrepro.build_hash=$BUILD_HASH" -t "$IMAGE" "$HERE" >&2 \
    || { echo "image build failed" >&2; exit 73; }
else
  say "image $IMAGE already present and current (build_hash $BUILD_HASH)"
fi
# DEFECT D2 FIX (RESULTS.md §6): --build-only used to exit HERE, before the
# volume laydown, despite its "image + volume" label. It now falls through to
# step 2 and exits after the laydown, which is what the label always claimed.

# ---- 2. named volume + deterministic laydown (idempotent) ------------
docker volume inspect "$VOLUME" >/dev/null 2>&1 || {
  say "creating named volume $VOLUME"; docker volume create "$VOLUME" >/dev/null; }

STAMP_OK=0
if [ "$FORCE_LAYDOWN" -eq 0 ]; then
  if docker run --rm --network=none -v "$VOLUME":/data --entrypoint /bin/sh "$IMAGE" -c \
       "[ \"\$(stat -c %s /data/R.bin 2>/dev/null)\" = \"$(( R_MIB * 1048576 ))\" ] && \
        [ \"\$(stat -c %s /data/L.bin 2>/dev/null)\" = \"$(( L_MIB * 1048576 ))\" ]" >/dev/null 2>&1; then
    STAMP_OK=1
  fi
fi
if [ "$STAMP_OK" -eq 1 ]; then
  say "volume $VOLUME already holds R=${R_MIB}MiB L=${L_MIB}MiB — skipping laydown"
else
  say "populating $VOLUME: R=${R_MIB}MiB L=${L_MIB}MiB (deterministic, seed=$SEED)"
  docker run --rm --network=none -v "$VOLUME":/data \
    -e R_FILE=/data/R.bin -e L_FILE=/data/L.bin \
    -e R_SIZE="${R_MIB}M" -e L_SIZE="${L_MIB}M" -e FIO_RANDSEED="$SEED" \
    --entrypoint /bin/sh "$IMAGE" -c \
    'rm -f /data/R.bin /data/L.bin; fio /bench/jobs/laydown.fio --output-format=json --output=/dev/null' \
    >&2 || { echo "laydown failed" >&2; exit 74; }
fi
if [ "$BUILD_ONLY" -eq 1 ]; then
  say "--build-only: image built AND volume $VOLUME laid down (R=${R_MIB}MiB L=${L_MIB}MiB). Done."
  exit 0
fi

# ---- 3. probe: is cgroup memory.stat readable inside a capped cell? ---
say "probing in-container cgroup readability"
CG_PROBE="$(docker run --rm --network=none --memory=512m --memory-swap=512m \
             --entrypoint /bin/sh "$IMAGE" -c \
             'if [ -r /sys/fs/cgroup/memory.stat ]; then echo v2-readable;
              elif [ -r /sys/fs/cgroup/memory/memory.stat ]; then echo v1-readable;
              else echo unreadable; fi' 2>/dev/null)"
say "cgroup probe: $CG_PROBE"
HOST_SAMPLE=0
if [ "$CG_PROBE" = "unreadable" ]; then
  HOST_SAMPLE=1
  say "WARNING: memory.stat is NOT readable inside the cell. Falling back to a"
  say "         HOST-SIDE sampler (cells run detached; the host polls the"
  say "         container's cgroup). analyze.py will use host_cgroup_samples."
fi

evict_volume() {   # fresh UNCAPPED container; per-file eviction only
  docker run --rm --network=none -v "$VOLUME":/data --entrypoint /bin/sh "$IMAGE" -c \
    'vmtouch -e /data/R.bin /data/L.bin >/dev/null 2>&1; vmtouch /data/R.bin /data/L.bin' >&2
}

host_cgroup_path() {   # host_cgroup_path <container-id> -> path or ""
  local cid="$1" p
  for p in \
    "/sys/fs/cgroup/system.slice/docker-${cid}.scope" \
    "/sys/fs/cgroup/docker/${cid}" \
    "/sys/fs/cgroup/kubepods/docker-${cid}.scope" \
    "/sys/fs/cgroup/memory/docker/${cid}" \
    "/sys/fs/cgroup/memory/system.slice/docker-${cid}.scope"; do
    [ -r "$p/memory.stat" ] && { echo "$p"; return; }
  done
  echo ""
}

# ---- 4. the ladder ---------------------------------------------------
for rung in "${RUNG_ORDER[@]}"; do
  case ",$RUNGS," in *",$rung,"*) ;; *) continue ;; esac
  cap_mib="$(cap_mib_for "$rung")"
  out="$(out_path_for "$rung")"

  say "re-evicting the volume before cell $rung"
  evict_volume

  say "cell $rung: --memory=${cap_mib}m --memory-swap=${cap_mib}m (nominal ${RUNG_GIB[$rung]}g at scale $SCALE)"
  # NOTE: --rm is added only on the foreground path. The host-sampler path needs
  # the container to survive until `docker logs` has been read, so it is removed
  # there and the container is deleted explicitly.
  DOCKER_ARGS=(
      --network=none
      --memory="${cap_mib}m" --memory-swap="${cap_mib}m"
      -v "$VOLUME":/data
      -e RUNG="$rung" -e CAP_LABEL="${RUNG_GIB[$rung]}g" -e SCALE="$SCALE"
      -e MODE="$MODE" -e PASSES="$PASSES" -e MAX_PASSES="$MAX_PASSES"
      -e MIN_PASSES="$MIN_PASSES" -e FIO_RANDSEED="$SEED"
      -e R_SIZE_MIB="$R_MIB" -e L_SIZE_MIB="$L_MIB"
      -e CAP_ENFORCED=1 -e RUN_LABEL="$RUN_LABEL"
      -e CAP_BYTES_NOMINAL="$(( cap_mib * 1048576 ))"
      -e EARLY_SORT="$EARLY_SORT"
      -e LOAD_ORDER="$LOAD_ORDER"
  )
  # The blind arm must WRITE the cell's own memory.reclaim. Docker mounts
  # /sys/fs/cgroup read-only in an ordinary container, so without a grant the
  # arm records BLOCKED. --privileged makes that mount read-write while leaving
  # --memory/--memory-swap in force (the cap is still a real cgroup limit, and
  # run_ladder verifies memory.max in-cell below). Applied to blind cells ONLY,
  # so guided and `none` cells stay bit-identical to the Tier-1 protocol.
  ES_GRANT="none"
  if [ "$EARLY_SORT" = "blind" ] && [ "$ES_PRIVILEGED" -eq 1 ]; then
    DOCKER_ARGS+=( --privileged )
    ES_GRANT="docker --privileged (writable /sys/fs/cgroup; --memory still enforced)"
    say "  blind cell: adding --privileged so memory.reclaim is writable"
  elif [ "$EARLY_SORT" = "blind" ]; then
    say "  blind cell: --no-es-privileged given; expect early_sort.blocked=true"
  fi
  DOCKER_ARGS+=( -e ES_CGROUP_WRITE_GRANT="$ES_GRANT" "$IMAGE" )

  SAMPLES=""
  if [ "$HOST_SAMPLE" -eq 0 ]; then
    docker run --rm "${DOCKER_ARGS[@]}" > "$out.raw" 2>"$out.log"
    rc=$?
  else
    cid="$(docker run -d "${DOCKER_ARGS[@]}" 2>"$out.log")"
    if [ -z "$cid" ]; then rc=75; else
      SAMPLES="$out.cgsamples"; : > "$SAMPLES"
      cgp=""
      for _try in 1 2 3 4 5 6 7 8 9 10; do      # the cgroup appears a beat late
        cgp="$(host_cgroup_path "$cid")"; [ -n "$cgp" ] && break; sleep 0.2
      done
      [ -n "$cgp" ] || echo "  !! could not locate the host cgroup for $cid — no samples" >&2
      ( while docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null | grep -q true; do
          if [ -n "$cgp" ]; then
            printf 't=%s\n' "$(date +%s.%N)" >> "$SAMPLES"
            cat "$cgp/memory.stat" >> "$SAMPLES" 2>/dev/null
            printf 'memory_swap_current %s\n' "$(cat "$cgp/memory.swap.current" 2>/dev/null)" >> "$SAMPLES"
          fi
          sleep 0.5
        done ) &
      sampler=$!
      rc="$(docker wait "$cid" 2>/dev/null || echo 75)"
      wait "$sampler" 2>/dev/null
      docker logs "$cid" > "$out.raw" 2>>"$out.log"
      docker rm -f "$cid" >/dev/null 2>&1
    fi
  fi

  if [ "${rc:-1}" -ne 0 ]; then
    echo "cell $rung FAILED rc=$rc — see $out.log" >&2; tail -n 8 "$out.log" >&2; continue
  fi
  sed -n '/===CONVREPRO_JSON_BEGIN===/,/===CONVREPRO_JSON_END===/p' "$out.raw" \
    | sed '1d;$d' > "$out"
  rm -f "$out.raw"
  if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$out" 2>/dev/null; then
    echo "cell $rung produced malformed JSON — kept $out for inspection" >&2; continue
  fi
  # verify the cap really landed
  python3 - "$out" "$(( cap_mib * 1048576 ))" <<'PY' >&2
import json,sys
d=json.load(open(sys.argv[1])); want=int(sys.argv[2]); got=d.get("cap_bytes_in_force")
if got != want:
    print(f"  !! WARNING: cap_bytes_in_force={got} but --memory implied {want}")
else:
    print(f"  cap verified in-cell: memory.max={got}")
PY
  es_summary "$out"
  say "wrote $out"
done

say "ladder done. Analyze with:  python3 $HERE/analyze.py --dir $OUT_DIR --glob 'convrepro_t1b_*_${DATE_TAG}.json'"
