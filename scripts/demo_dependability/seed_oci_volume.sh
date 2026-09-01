#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"

MANIFEST="${MANIFEST:-$REPO_ROOT/scripts/data/demo_payload_manifest.json}"
DEST="${DEST:-}"
SSH_OPTS="${SSH_OPTS:--o ServerAliveInterval=30 -o ServerAliveCountMax=4}"
MAX_RETRIES="${MAX_RETRIES:-0}"        # 0 = retry forever (until rsync exits 0)
BACKOFF="${BACKOFF:-15}"               # seconds, capped at 300
BWLIMIT="${BWLIMIT:-0}"                # KB/s, 0 = unlimited
REFRESH="${REFRESH:-0}"
MODE="transfer"
MANIFEST_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2;;
    --manifest) MANIFEST="$2"; shift 2;;
    --refresh-manifest) REFRESH=1; shift;;
    --verify) MODE="verify"; shift;;
    --dry-run) MODE="dryrun"; shift;;
    --bwlimit) BWLIMIT="$2"; shift 2;;
    --include-dense) MANIFEST_ARGS+=(--include-dense); REFRESH=1; shift;;
    --sqlite-free-abstracts) MANIFEST_ARGS+=(--sqlite-free-abstracts); REFRESH=1; shift;;
    -h|--help) sed -n '2,55p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[[ -n "$DEST" ]] || { echo "ERROR: --dest (or DEST=) required" >&2; exit 2; }

BUILDER="$REPO_ROOT/scripts/demo_dependability/build_demo_payload_manifest.py"
if [[ "$REFRESH" == "1" ]]; then
  echo ">> refreshing manifest: $MANIFEST"
  "$PY" "$BUILDER" --out "$MANIFEST" "${MANIFEST_ARGS[@]+"${MANIFEST_ARGS[@]}"}"
fi
[[ -f "$MANIFEST" ]] || {
  echo "ERROR: manifest '$MANIFEST' not found — run:" >&2
  echo "  $PY $BUILDER" >&2
  exit 2
}

FILES_FROM="$(mktemp -t oci_payload_files.XXXXXX)"
cleanup() { rm -f "$FILES_FROM"; }
trap cleanup EXIT

"$PY" - "$MANIFEST" "$FILES_FROM" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))
files = m.get("files", [])
if not files:
    sys.exit("ERROR: manifest lists no files")
if m.get("partial"):
    sys.exit("ERROR: manifest is PARTIAL (an interrupted --hash run) — re-run "
             "the builder to completion before seeding")
with open(sys.argv[2], "w") as fh:
    fh.writelines(p["path"] + "\n" for p in files)
t = m["totals"]
print(f">> manifest {m['generated_utc']}: {t['files']} files, {t['gb']} GB "
      f"({t['gib']} GiB)", file=sys.stderr)
PYEOF

RSYNC_RSH=()
if [[ "$DEST" == *:* && "$DEST" != /* ]]; then
  RSYNC_RSH=(-e "ssh ${SSH_OPTS}")
fi

BASE_FLAGS=(-a --files-from="$FILES_FROM" --partial --append-verify --inplace
            --human-readable --info=progress2,stats2)
[[ "$BWLIMIT" != "0" ]] && BASE_FLAGS+=(--bwlimit="$BWLIMIT")

verify() {
  echo ">> VERIFY: checksum dry-run $REPO_ROOT/ -> $DEST"
  local diffs
  diffs=$(rsync -a --files-from="$FILES_FROM" --checksum --dry-run \
          --itemize-changes "${RSYNC_RSH[@]}" \
          "$REPO_ROOT/" "$DEST" 2>/dev/null | grep -E '^[^.]f' || true)
  if [[ -n "$diffs" ]]; then
    echo "$diffs"
    echo ">> VERIFY: content differences remain (re-run transfer)"
    return 1
  fi
  echo ">> VERIFY OK: dest is byte-identical to the manifest's payload"
}

dryrun() {
  echo ">> DRY-RUN: $REPO_ROOT/ -> $DEST"
  rsync "${BASE_FLAGS[@]}" --dry-run --itemize-changes "${RSYNC_RSH[@]}" \
        "$REPO_ROOT/" "$DEST"
}

transfer() {
  local attempt=0 rc wait
  while true; do
    attempt=$((attempt+1))
    if [[ "$MAX_RETRIES" != "0" && "$attempt" -gt "$MAX_RETRIES" ]]; then
      echo ">> hit MAX_RETRIES=$MAX_RETRIES without a verified-complete transfer" >&2
      return 1
    fi
    echo ">> [$(date -u +%H:%M:%S)] rsync attempt #$attempt : $REPO_ROOT/ -> $DEST"
    rc=0
    rsync "${BASE_FLAGS[@]}" "${RSYNC_RSH[@]}" "$REPO_ROOT/" "$DEST" || rc=$?
    if [[ "$rc" -eq 0 ]]; then
      echo ">> transfer pass complete on attempt #$attempt"
      if verify; then return 0; fi
      echo ">> verify found residual diffs; re-running rsync"
      continue
    fi
    wait=$(( BACKOFF * attempt )); [[ $wait -gt 300 ]] && wait=300
    echo ">> rsync interrupted (rc=$rc); resuming in ${wait}s (re-entrant: --partial keeps progress)"
    sleep "$wait"
  done
}

case "$MODE" in
  verify) verify;;
  dryrun) dryrun;;
  transfer) transfer;;
esac
