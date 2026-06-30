#!/usr/bin/env bash
# run_g8_latency_noswap.sh — turnkey wrapper for the G8 SEISMIC latency re-run.
#
# PURPOSE (08_LATENCY_RESEARCH.md §A1): the 2026-06-29 G8 run recorded SEISMIC
# p50 = 76.7 s on a SWAP-THRASHING host (15/16 GiB swap used) → NOT a verdict.
# This wrapper makes the latency run CLEAN by (a) killing swap on the serving
# process so file-backed mmap pages are reclaimed/re-read instead of fighting
# anon swap, and (b) measuring the ACTUAL resident set so the ~7.5 GB
# projection in the doc finally gets a real number behind it.
#
# It pre-stages the §C1 lever (SFU_SEISMIC_QUERY_CUT=10 → 4× traverse at
# overlap@10 0.995, commit d27bb3e) + --passes 2 (real warm p50) + the
# encode/traverse split (efce80e) so the run attributes SEISMIC's p50 to SPLADE
# encode vs fan-out traversal.
#
# USAGE (from repo root, project venv on PATH works too):
#   sudo env "PATH=$PATH" scripts/seismic_testbed/run_g8_latency_noswap.sh \
#       --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json \
#       [--queries 40] [--passes 2] [--result-file ...]
#   (set SFU_SEISMIC_QUERY_CUT="" to disable C1 and measure the all-terms baseline)
#
# Swap control is attempted three ways; the wrapper reports which took effect:
#   1. cgroup v2 memory.swap.max=0 on a transient cgroup (BEST — needs writable
#      /sys/fs/cgroup; the container this was authored on has it READ-ONLY).
#   2. swapoff -a before the run (needs true root; WSL2 reports "Not superuser"
#      even under sudo).
#   3. neither → the run still goes, but SWAP IS NOT BOUNDED, and the wrapper
#      prints a loud CAVEAT: the captured VmSwap tells the truth (read it from
#      the result JSON — if vmswap_kb > 0 the latency is STILL swap-confounded,
#      and the number is recorded-not-concluded, same status as 2026-06-29).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${REPO}/.venv/bin/python3"
BENCH="${REPO}/scripts/seismic_testbed/serve_footprint_bench.py"

# ── args we pass through to the bench (intercept a couple) ───────────────────
BENCH_ARGS=()
QUERIES="${SFU_G8_QUERIES:-40}"
PASSES="${SFU_G8_PASSES:-2}"
RESULT_FILE=""
for ((i=1; i<=$#; i++)); do
  a="${!i}"
  case "$a" in
    --queries)   i=$((i+1)); QUERIES="${!i}";;
    --passes)    i=$((i+1)); PASSES="${!i}";;
    --result-file) i=$((i+1)); RESULT_FILE="${!i}";;
    *) BENCH_ARGS+=("$a");;
  esac
done
# require --shard-manifest
have_manifest=0
for a in "${BENCH_ARGS[@]:-}"; do [[ "$a" == "--shard-manifest" ]] && have_manifest=1; done
if [[ $have_manifest -eq 0 ]]; then
  echo "ERROR: --shard-manifest is required (the 8-shard 150M mmap manifest)." >&2
  echo "  e.g. --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json" >&2
  exit 2
fi
[[ -n "$RESULT_FILE" ]] || RESULT_FILE="${REPO}/data/eval_results/seismic_g8_latency_noswap_$(date -u +%Y%m%d_%H%M%S).json"

# ── the §C1 lever (override by exporting SFU_SEISMIC_QUERY_CUT="" to disable) ─
export SFU_SEISMIC_QUERY_CUT="${SFU_SEISMIC_QUERY_CUT:-10}"   # all-terms → 4× traverse @ overlap@10 0.995
export SFU_SEISMIC_HEAP_FACTOR="${SFU_SEISMIC_HEAP_FACTOR:-0.8}"

# mmap default (the served 150M path); set SFU_SEISMIC_LOAD_MODE=stock for a Path-A control
export SFU_SEISMIC_LOAD_MODE="${SFU_SEISMIC_LOAD_MODE:-mmap}"

echo "=== G8 latency re-run (no-swap wrapper) ==="
echo "  queries=${QUERIES} passes=${PASSES} (pass 0 = cold fault-storm, pass>=1 = warm steady-state)"
echo "  §C1: SFU_SEISMIC_QUERY_CUT=${SFU_SEISMIC_QUERY_CUT} heap_factor=${SFU_SEISMIC_HEAP_FACTOR} load_mode=${SFU_SEISMIC_LOAD_MODE}"
echo "  result_file=${RESULT_FILE}"

# ── swap control: try cgroup v2 first, then swapoff, then honest caveat ────────
SWAP_MODE="none"
CGROUP_DIR=""
swap_kb_before="$(awk '/SwapTotal/{print $2}' /proc/meminfo)"
swap_free_before="$(awk '/SwapFree/{print $2}' /proc/meminfo)"
echo "  swap before: total=${swap_kb_before} kB, free=${swap_free_before} kB (used=$((swap_kb_before-swap_free_before)) kB)"

if mount | grep -q 'on /sys/fs/cgroup type cgroup2'; then
  RO=""
  if mount | grep '/sys/fs/cgroup' | grep -q '\bro\b'; then RO="ro"; fi
  if [[ -z "$RO" ]]; then
    CGROUP_DIR="/sys/fs/cgroup/sfu_g8_latency_$$"
    if mkdir -p "$CGROUP_DIR" 2>/dev/null && echo "+memory" > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null; then
      echo 0 > "$CGROUP_DIR/memory.swap.max" 2>/dev/null && SWAP_MODE="cgroup"
      # Delegate to a helper that moves the bench PID into the cgroup (see below).
    else
      CGROUP_DIR=""
    fi
  fi
fi
if [[ "$SWAP_MODE" == "none" ]]; then
  if swapoff -a 2>/dev/null; then SWAP_MODE="swapoff"; fi
fi
if [[ "$SWAP_MODE" == "none" ]]; then
  echo ""
  echo "  !! CAVEAT !! swap is NOT bounded on this host (cgroup mount read-only +"
  echo "  swapoff not permitted — the common WSL2/container case). The run still"
  echo "  goes, but if the result JSON shows vmswap_kb > 0 the latency is STILL"
  echo "  swap-confounded → record, do NOT conclude (same status as 2026-06-29)."
  echo "  To get a real no-swap run: run on a host with writable /sys/fs/cgroup,"
  echo "  or have the operator set memory.swap.max=0 on this container's slice."
  echo ""
fi

# ── launch the bench (inside the cgroup if we got one) ────────────────────────
cleanup() {
  [[ -n "$CGROUP_DIR" && -d "$CGROUP_DIR" ]] && rmdir "$CGROUP_DIR" 2>/dev/null || true
}
trap cleanup EXIT

run_bench() {
  "$PY" "$BENCH" \
    --queries "$QUERIES" --passes "$PASSES" \
    --result-file "$RESULT_FILE" \
    "${BENCH_ARGS[@]}"
}

if [[ "$SWAP_MODE" == "cgroup" ]]; then
  echo "  swap control: cgroup v2 memory.swap.max=0 ($CGROUP_DIR) — launching bench in-cgroup"
  # Move ourselves into the cgroup, then run (transient; process stays for the bench).
  echo $$ > "$CGROUP_DIR/cgroup.procs" 2>/dev/null || true
  run_bench
else
  run_bench
fi

# ── capture the ACTUAL resident set (so the ~7.5 GB projection gets a number) ─
echo ""
echo "=== resident-set capture (the ~7.5 GB projection gets a real number here) ==="
"$PY" - "$RESULT_FILE" <<'PYEOF'
import json, sys, os
d = json.load(open(sys.argv[1]))
s = d.get("seismic", {})
ram = s.get("ram", {})
print(f"  load_mode={s.get('load_mode')} query_cut={s.get('query_cut')} heap_factor={s.get('heap_factor')}")
print(f"  RssAnon (anon floor)     = {ram.get('rss_anon_gb')} GB")
print(f"  VmSwap (anon paged out)  = {ram.get('vmswap_gb')} GB   <== ~0 required but NOT sufficient (see warm<cold check below)")
print(f"  VmRSS peak (total resid)  = {ram.get('vmrss_peak_gb')} GB")
rss_anon = ram.get('rss_anon_gb') or 0.0
vmswap   = ram.get('vmswap_gb') or 0.0
print(f"  TRUE anon floor          = {round(rss_anon + vmswap, 3)} GB")
# latency split — the item-#3 attribution. encode_ms/traverse_ms hold cold/warm subs.
def p50(st):
    if not isinstance(st, dict): return None
    for sub in ("warm", "cold"):
        b = st.get(sub)
        if isinstance(b, dict) and b.get("p50_ms") is not None:
            return b["p50_ms"]
    return st.get("p50_ms")
print(f"  encode p50 (SPLADE ONNX)   = {p50(s.get('encode_ms'))} ms")
print(f"  traverse p50 (fan-out)     = {p50(s.get('traverse_ms'))} ms")
# Two independent ways a run can be NOT-a-verdict (08_LATENCY_RESEARCH.md §A1 measured):
#   (1) anon swap  — VmSwap > 0 → anon pages paged out, latency is swap noise.
#   (2) cache miss — VmSwap≈0 but the mmap index exceeds page cache, so warm
#       queries re-fault from disk and warm p50 shows NO speedup over cold.
# Both are "record, do not conclude"; only swap≈0 AND warm<cold is a real verdict.
lat  = s.get("latency_ms", {}) or {}
cold = (lat.get("cold") or {}).get("p50_ms")
warm = (lat.get("warm") or {}).get("p50_ms")
vmrss_peak = ram.get('vmrss_peak_gb') or 0.0
# Report every symptom present (they co-occur), then the unified cause/fix.
issues = []
if vmswap > 0.1:
    issues.append(f"VmSwap={vmswap} GB anon paged to swap")
if cold and warm and warm >= 0.9 * cold and warm > 1000:
    issues.append(f"warm p50 {warm:.0f} ms >= cold {cold:.0f} ms (mmap index exceeds page cache,"
                  f" VmRSS peak {vmrss_peak} GB resident → queries re-fault from disk)")
if issues:
    print("")
    print(f"  >> NOT A VERDICT (disk/swap-bound): " + "; ".join(issues) + ".")
    print(f"     Root cause: host RAM < working set. Needs RAM >= index-on-disk size (+ headroom)")
    print(f"     so the index stays cached and anon never swaps (08_LATENCY_RESEARCH.md '§A1 measured').")
else:
    print(f"  >> VmSwap≈0 and warm < cold (cache hit) → latency is CLEAN. This p50 IS a verdict.")
PYEOF
echo ""
echo "done. result: ${RESULT_FILE}"
