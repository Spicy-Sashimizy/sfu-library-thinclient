#!/usr/bin/env bash
# g8c_warm_matrix.sh — the warm-state hypothesis matrix (doc 11 Tier 1/2).
#
# Runs AFTER a G8b uncapped cell has cold-filled the page cache for one codec
# (HOST_PROMPT_G8B_FULLCORPUS.md). Every Tier-1 cell here deliberately does
# NOT drop caches — the warm state is the experiment. Tier-2 sequential cells
# manage their own state.
#
# USAGE (host, from repo root, after Cell A or B of G8b):
#   ./scripts/seismic_testbed/g8c_warm_matrix.sh f16   # right after Cell A
#   ./scripts/seismic_testbed/g8c_warm_matrix.sh dv    # right after Cell B
#   ./scripts/seismic_testbed/g8c_warm_matrix.sh seq   # Tier-2 sequential cells (either codec warm state destroyed — run LAST)
#
# Interpreter: uses $HOSTPY + $PYTHONPATH if set (the Rule One invocation from
# the G8B host prompt); falls back to .venv/bin/python3 (container).
set -euo pipefail

ARM="${1:?usage: g8c_warm_matrix.sh f16|dv|seq}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${HOSTPY:-$REPO/.venv/bin/python3}"
BENCH="$REPO/scripts/seismic_testbed/serve_footprint_bench.py"
OUT="$REPO/data/eval_results"
MAN_F16="$REPO/data/eval_results/seismic_c25_shards_150m_mmap.json"
MAN_DV="$REPO/data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json"
STAMP="$(date -u +%Y%m%d)"

run_cell() {  # run_cell <manifest> <result-name> <extra bench args...>; env knobs set by caller
  local man="$1" name="$2"; shift 2
  local rf="$OUT/g8c_${name}_${STAMP}.json"
  if [[ -f "$rf" ]]; then echo ">> $name: exists, skip"; return; fi
  echo ">> $name (qc=${SFU_SEISMIC_QUERY_CUT-unset} hf=${SFU_SEISMIC_HEAP_FACTOR-unset} kp=${SFU_SEISMIC_K_PRIME-unset})"
  "$PY" "$BENCH" --shard-manifest "$man" --result-file "$rf" "$@"
}

case "$ARM" in
  f16|dv)
    MAN="$([[ $ARM == f16 ]] && echo "$MAN_F16" || echo "$MAN_DV")"
    # ── Tier 1 — warm cells, 40 queries, 1 pass, parallel. Baseline knobs first
    # (k′=200 hf=0.8 all-terms = the E7/E7b footing), then one knob at a time.
    export SFU_SEISMIC_HEAP_FACTOR=0.8
    unset SFU_SEISMIC_QUERY_CUT || true

    export SFU_SEISMIC_K_PRIME=200
    run_cell "$MAN" "${ARM}_warm_kp200_qcall_hf08" --queries 40 --passes 1 --federation parallel

    # H1 — k′ interplay (doc 10 §7 owed)
    export SFU_SEISMIC_K_PRIME=100
    run_cell "$MAN" "${ARM}_warm_kp100_qcall_hf08" --queries 40 --passes 1 --federation parallel

    # H2 — the C1 query_cut lever at full corpus
    export SFU_SEISMIC_K_PRIME=200 SFU_SEISMIC_QUERY_CUT=10
    run_cell "$MAN" "${ARM}_warm_kp200_qc10_hf08" --queries 40 --passes 1 --federation parallel
    unset SFU_SEISMIC_QUERY_CUT

    # H3 — heap_factor
    for HF in 0.7 1.0; do
      export SFU_SEISMIC_HEAP_FACTOR=$HF
      run_cell "$MAN" "${ARM}_warm_kp200_qcall_hf${HF/./}" --queries 40 --passes 1 --federation parallel
    done
    export SFU_SEISMIC_HEAP_FACTOR=0.8
    echo "== $ARM warm matrix done. H4 (warm scaling) is computed from the kp200 baseline JSON vs E7b shard0 warm — no extra cell."
    ;;

  seq)
    # ── Tier 2 — sequential federation (destroys/ignores warm state; run after
    # BOTH codec matrices). 10 queries × 2 passes: each query ≈ 8 shard sweeps.
    export SFU_SEISMIC_K_PRIME=200 SFU_SEISMIC_HEAP_FACTOR=0.8
    unset SFU_SEISMIC_QUERY_CUT || true

    # H6 — sequential @ current RAM, both codecs (mechanism cost when RAM is free)
    run_cell "$MAN_F16" "f16_seq_uncapped" --queries 10 --passes 2 --federation sequential
    run_cell "$MAN_DV"  "dv_seq_uncapped"  --queries 10 --passes 2 --federation sequential

    # H5 — THE localized-deploy cell: full corpus, sequential, dv, 6 GB cap.
    # Needs sudo + systemd-run (same pattern as G8b capped cells).
    RF="$OUT/g8c_dv_seq_cap6G_${STAMP}.json"
    if [[ -f "$RF" ]]; then echo ">> dv_seq_cap6G: exists, skip"; else
      sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'
      sudo systemd-run --scope --same-dir --uid "$(id -u)" --gid "$(id -g)" \
        -p MemoryMax=6G -p MemorySwapMax=0 \
        env PYTHONPATH="${PYTHONPATH-}" \
            SFU_SEISMIC_K_PRIME=200 SFU_SEISMIC_HEAP_FACTOR=0.8 \
        "$PY" "$BENCH" --shard-manifest "$MAN_DV" --queries 10 --passes 2 \
          --federation sequential --result-file "$RF"
    fi
    echo "== sequential cells done."
    ;;
  *) echo "unknown arm: $ARM (want f16|dv|seq)"; exit 2;;
esac
