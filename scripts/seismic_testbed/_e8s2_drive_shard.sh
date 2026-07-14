#!/usr/bin/env bash
# Host-ops driver for E8 Stage 2 shard rebuild, phased.
#   usage: _e8s2_drive_shard.sh <K> <full|reorderonly> <build|gate|both>
# build = convert(if full)+reorder (parallel-safe, writes only new dirs)
# gate  = latency-sensitive measurement; MUST run isolated (nothing else heavy)
# Non-destructive: never deletes/commits. Operator does that after a PASS.
set -u
cd /workspaces/sfu-library-thinclient || exit 3
K="${1:?shard index required}"; MODE="${2:-full}"; PHASE="${3:-both}"
P=data/seismic_150m/index/plan01
CONV=spike/seismic_upstream/target/release/convert_f16_to_dotvbyte
REORD=spike/seismic_upstream/target/release/reorder_mmap_shard
F16=$P/global_shard${K}of8.mmap
DV1=$P/global_shard${K}of8.dotvbyte.mmap
V2=$P/global_shard${K}of8.dotvbyte.v2.mmap
E5V2=$P/global_shard${K}of8.dotvbyte.e5.v2.mmap
PERM=$P/e5_perms/global_shard${K}of8.block_walk_canonical.perm.bin
LOG=data/eval_results/_e8s2_shard${K}_drive.log
RESULT=data/eval_results/e8_stage2_shard${K}_$(date +%Y%m%d).json
STATUS=data/eval_results/_e8s2_shard${K}.status

fail(){ echo "$1"; echo "FAIL:$1" > "$STATUS"; exit 1; }

do_build(){
  for d in "$F16" "$DV1" "$PERM"; do [ -e "$d" ] || fail "MISSING_INPUT:$d"; done
  if [ "$MODE" = "full" ]; then
    echo "[convert $(date -u +%FT%TZ)] $F16 -> $V2"
    "$CONV" --src-mmap-dir "$F16" --dst-mmap-dir "$V2" \
        --value-scale perdoc --sanity-docs 2000 || fail "CONVERT_rc$?"
  else
    [ -d "$V2" ] || fail "MISSING_INTERMEDIATE:$V2"
  fi
  echo "[reorder $(date -u +%FT%TZ)] $V2 -> $E5V2"
  "$REORD" --src-mmap-dir "$V2" --dst-mmap-dir "$E5V2" \
      --perm-file "$PERM" --order-name block_walk_canonical \
      --sanity-docs 2000 || fail "REORDER_rc$?"
}
do_gate(){
  [ -d "$E5V2" ] || fail "MISSING_E5V2:$E5V2"
  echo "[gate $(date -u +%FT%TZ)] v2-dir=$E5V2"
  SFU_SEISMIC_PREFLOOR=2 .venv/bin/python3 scripts/seismic_testbed/e8_dvv2_gates.py \
      --f16-dir "$F16" --dv1-dir "$DV1" --v2-dir "$E5V2" \
      --queries 100 --result-file "$RESULT" || fail "GATE_rc$?"
}

echo "RUNNING:$PHASE" > "$STATUS"
{
  echo "==== shard $K mode=$MODE phase=$PHASE start $(date -u +%FT%TZ) ===="
  case "$PHASE" in
    build) do_build; echo "BUILT" > "$STATUS";;
    gate)  do_gate;  echo "DONE"  > "$STATUS";;
    both)  do_build; do_gate; echo "DONE" > "$STATUS";;
    *) fail "BAD_PHASE:$PHASE";;
  esac
  echo "==== shard $K phase=$PHASE COMPLETE $(date -u +%FT%TZ) ===="
} >> "$LOG" 2>&1
