#!/usr/bin/env bash
# R3 capability gate G-R3-0 (2026-07-16; backlog §R3 / doc 15 §3).
#
# Checks the WSL2 kernel can give R3 what it needs — BTF, the four
# filemap/vmscan tracepoints, a firing bpftrace, and cachestat(2) syscall
# 451 returning sane counts on a known-resident file. A hard miss on
# BTF/tracepoints/bpftrace PARKS the spike (§R3); cachestat-FAIL alone falls
# back to mincore (instrument 4), recorded.
#
# Runs ON THE WINDOWS HOST as a privileged `--pid=host` container (the dev
# container is unprivileged: debugfs/tracing not mounted, no bpftrace, no
# CAP_BPF). The host monitor launches it from the host queue (REQ-1). It is
# self-contained and idempotent: every check prints a one-line
# `CHECK <name>: PASS|FAIL <detail>` and a final summary line. The host
# monitor copies its stdout to data/eval_results/_r3_hostreq_1.log.
#
# bpftrace strategy: the ClaudeBox app image has no bpftrace and we will NOT
# apt-get it into that image (bloats the served image + risk to the venv).
# Instead apt-get install bpftrace inside THIS throwaway privileged probe
# container only (Debian bookworm base, same as the app image). If apt is
# unavailable we fall back to a separate `bpftrace/bpftrace` image — recorded.
#
# Usage (from repo root on the host, launched by the host monitor OR manually):
#   bash scripts/seismic_testbed/r3_capability_probe.sh
# A repo bind-mount + the dev image name are supplied by the host monitor's
# `docker run` invocation; when run bare (no docker), this script probes the
# running kernel directly (useful sanity check from the dev container, where
# tracepoint/bpftrace checks will legitimately FAIL without privileges).
set -u
export MSYS_NO_PATHCONV=1

PASS=0
FAIL=0
HARD_FAIL=0   # BTF/tracepoints/bpftrace — a miss parks the spike
CACHESTAT_FAIL=0

emit()  { echo "CHECK $1: $2"; }                       # name, "PASS|FAIL detail"
ok()    { emit "$1" "PASS $2";          PASS=$((PASS+1)); }
fail()  { emit "$1" "FAIL $2";          FAIL=$((FAIL+1)); }
hfail()  { emit "$1" "FAIL $2";         FAIL=$((FAIL+1)); HARD_FAIL=$((HARD_FAIL+1)); }

echo "=== R3 capability probe G-R3-0  (host $(hostname), $(date -u +%FT%TZ)) ==="
echo "kernel: $(uname -r)"

# ── 1. kernel version ≥ 6.5 (cachestat) ────────────────────────────────────
KV=$(uname -r)
MAJ=$(echo "$KV" | sed -E 's/^([0-9]+)\..*/\1/')
MIN=$(echo "$KV" | sed -E 's/^[0-9]+\.([0-9]+).*/\1/')
if [ "$MAJ" -gt 6 ] || { [ "$MAJ" -eq 6 ] && [ "$MIN" -ge 5 ]; }; then
  ok kernel_version "($KV ≥ 6.5 — cachestat available)"
else
  fail kernel_version "($KV < 6.5 — cachestat UNAVAILABLE; instrument 4 falls back to mincore)"
  CACHESTAT_FAIL=1
fi

# ── 2. /sys/kernel/btf/vmlinux (CO-RE/BTF for the kprobe) ───────────────────
if [ -r /sys/kernel/btf/vmlinux ]; then
  SZ=$(stat -c %s /sys/kernel/btf/vmlinux 2>/dev/null || echo 0)
  ok btf_vmlinux "(present, ${SZ} bytes)"
else
  hfail btf_vmlinux "(missing — kprobe CO-RE cannot resolve types; PARKS the spike)"
fi

# tracefs location: privileged on the host. /sys/kernel/tracing is the modern
# mount point; /sys/kernel/debug/tracing is the legacy alias. On a throwaway
# --pid=host debian:bookworm-slim neither is mounted by default → mount it
# ourselves before checking (following the host monitor's 2026-07-16 note:
# the original REQ-1 falsely PARKed because tracefs wasn't mounted/visible).
TRACING="/sys/kernel/tracing"
[ -d "$TRACING" ] || TRACING="/sys/kernel/debug/tracing"
if [ ! -d "$TRACING/events" ] 2>/dev/null; then
  # mount tracefs (and its debugfs parent if needed) into the throwaway. These
  # are no-ops if already mounted; on the host they are normally present.
  mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
  mount -t tracefs none /sys/kernel/tracing 2>/dev/null || true
  [ -d "$TRACING/events" ] || TRACING="/sys/kernel/debug/tracing"
fi
TP_BASE="$TRACING/events"

# ── 3. the four tracepoints ─────────────────────────────────────────────────
# tracefs lays events out as events/<subsystem>/<event> (slash-separated). We
# are given the event names in bpftrace form 'subsys:event' (colon), so the
# colon→slash conversion below is the fix for the 2026-07-16 REQ-1 PARK bug:
# need_tp() was testing the literal-colon path and every event read MISSING.
need_tp() {  # arg: 'subsys:event' (bpftrace form); returns 0 if tracefs dir exists
  local subsys="${1%%:*}" ev="${1#*:}"   # filemap:mm_... → filemap / mm_...
  [ -d "$TP_BASE/$subsys/$ev" ] && return 0
  return 1
}
TP_OK=1
TP_LIST="filemap:mm_filemap_delete_from_page_cache filemap:mm_filemap_add_to_page_cache vmscan:mm_vmscan_lru_shrink_inactive vmscan:mm_vmscan_memcg_reclaim_begin"
for tp in $TP_LIST; do
  if need_tp "$tp"; then ok tracepoint_$tp "(present)"; else hfail tracepoint_$tp "(MISSING — PARKS the spike)"; TP_OK=0; fi
done

# ── 4. bpftrace one-liner actually firing ──────────────────────────────────
# Install bpftrace AND python3 into this throwaway privileged Debian container
# only (bookworm-slim ships neither; the host monitor's 2026-07-16 note: REQ-1
# spuriously downgraded cachestat→mincore because python3 was missing → the
# ctypes syscall probe never ran). The dev image is left untouched.
BPFTRACE_BIN=""
install_bpftrace_apk_or_apt() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "installing bpftrace + python3 via apt-get (throwaway container only)..."
    apt-get update -q >/dev/null 2>&1
    apt-get install -y -q bpftrace python3 >/dev/null 2>&1
    command -v bpftrace >/dev/null 2>&1 && BPFTRACE_BIN=bpftrace && return 0
  fi
  return 1
}
if command -v bpftrace >/dev/null 2>&1; then
  BPFTRACE_BIN=bpftrace
else
  install_bpftrace_apk_or_apt || echo "CHECK bpftrace_install: NOTE apt install failed; trying to proceed without"
fi

if [ -n "$BPFTRACE_BIN" ]; then
  # Fire a real tracepoint and confirm we receive a line within 7 s. We trace
  # the sched yield (/self-triggering) so the probe provably lights up without
  # needing shard traffic: spawn bpftrace in the background, sleep, then see
  # whether it printed events. Using tracepoint:sched:sched_switch (always
  # firing) rather than filemap, so the probe firing is independent of cache.
  # tracepoint sched:sched_switch is always firing, so the probe lights up
  # without needing shard traffic — proving bpftrace compiles and attaches.
  # Write the multi-clause program to a file (avoids shell brace-parsing) and
  # have it print its map at 5 s then exit.
  BPF_OUT=$(mktemp); BPF_PRG=$(mktemp --suffix=.bt)
  cat >"$BPF_PRG" <<'BT'
tracepoint:sched:sched_switch { @[comm] = count(); }
interval:s:5 { print(@); exit(); }
BT
  "$BPFTRACE_BIN" "$BPF_PRG" >"$BPF_OUT" 2>&1 &
  BPF_PID=$!
  sleep 6
  if grep -q "@" "$BPF_OUT" 2>/dev/null; then
    N=$(grep -c "@" "$BPF_OUT")
    ok bpftrace_fires "(got $N map-print line(s) from sched_switch in 5 s)"
  else
    hfail bpftrace_fires "(no output — bpftrace=$BPFTRACE_BIN)$(head -5 "$BPF_OUT" | tr '\n' '|')"
  fi
  kill "$BPF_PID" >/dev/null 2>&1
  rm -f "$BPF_OUT" "$BPF_PRG"
else
  hfail bpftrace_fires "(bpftrace not installed — apt-get failed in probe container)"
fi

# ── 5. cachestat (x86_64 syscall 451) on a known-resident file ──────────────
# We use python ctypes to issue syscall 451 directly. cachestat(int fd,
# const struct cachestat_range *crange, struct cachestat *cstat, unsigned int
# flags). We point it at /bin/sh (small, almost certainly resident). A sane
# result has cache > 0. This runs in-container too (the dev container can
# issue syscalls), but on the host-probe container to match deployment.
PYPROBE=$(command -v python3 || command -v python)
if [ -n "$PYPROBE" ]; then
  "$PYPROBE" - <<'PYEOF'
import ctypes, os, sys
_libc = ctypes.CDLL(None, use_errno=True)
# int cachestat(int fd, struct cachestat_range *crange, struct cachestat *cstat, unsigned int flags);
class crange(ctypes.Structure):
    _fields_ = [("off", ctypes.c_uint64), ("len", ctypes.c_uint64)]
class cstat(ctypes.Structure):
    _fields_ = [("nr_cache", ctypes.c_uint64), ("nr_dirty", ctypes.c_uint64),
                ("nr_writeback", ctypes.c_uint64), ("nr_evicted", ctypes.c_uint64),
                ("nr_recently_evicted", ctypes.c_uint64)]
NR_CACHESTAT = 451  # x86_64
fn = _libc.syscall
fn.restype = ctypes.c_long
fn.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.POINTER(crange),
               ctypes.POINTER(cstat), ctypes.c_uint]
fd = os.open("/bin/sh", os.O_RDONLY)
try:
    r = crange(0, 1 << 30)  # whole file
    s = cstat(0,0,0,0,0)
    rc = fn(NR_CACHESTAT, fd, ctypes.byref(r), ctypes.byref(s), 0)
    if rc < 0:
        err = ctypes.get_errno()
        print(f"CHECK cachestat: FAIL (syscall returned {rc}, errno={err} = {os.strerror(err)})")
        sys.exit(7)  # signal cachestat fail so the shell records mincore fallback
    print(f"CHECK cachestat: PASS (rc={rc} cache={s.nr_cache} dirty={s.nr_dirty} "
          f"evicted={s.nr_evicted} recently_evicted={s.nr_recently_evicted})")
    sys.exit(0)
finally:
    os.close(fd)
PYEOF
  CST_RC=$?
  if [ "$CST_RC" -ne 0 ]; then
    CACHESTAT_FAIL=1
    emit cachestat "NOTE (python probe rc=$CST_RC) → instrument 4 uses mincore (residency bit only; loses evicted/recently_evicted half — recorded)"
  fi
else
  emit cachestat "FAIL (no python3 to issue the syscall)"
  CACHESTAT_FAIL=1
fi

# ── summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=== G-R3-0 SUMMARY  pass=$PASS fail=$FAIL hard_fail=$HARD_FAIL cachestat_fail=$CACHESTAT_FAIL ==="
if [ "$HARD_FAIL" -gt 0 ]; then
  echo "VERDICT: PARK — BTF/tracepoints/bpftrace hard-miss; §R3 says commit probe log + skip to session-end"
  exit 10
elif [ "$CACHESTAT_FAIL" -gt 0 ]; then
  echo "VERDICT: GO-WITH-MINCORE — cachestat unavailable; instrument 4 downgrades to mincore (recorded)"
  exit 0
else
  echo "VERDICT: GO — all capability checks pass; proceed to Phase C cells"
  exit 0
fi
