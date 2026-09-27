#!/usr/bin/env bash
# Build the portable, relocatable Linux python runtime bundle for the serve path.
#
#   scripts/portable_linux/build_linux_runtime.sh <out_dir>
#
# Produces, in a FRESH <out_dir> (refuses a non-empty one):
#   python/                 python-build-standalone CPython 3.11 (pinned + sha256)
#                           + the CPU-only serving wheels from the hash lock
#   python/lib/python3.11/site-packages/sfu_bundle.pth
#                           relative import path -> ../../../../ext and ../../../../app/src
#   ext/seismic/            the WI-4 portable x86-64-v3 seismic .so (+ __init__.py)
#   app/src/                src/lib/ (incl. lib/thinclient/) + the two server entry points
#   bin/sfu-python          isolated launcher (drops PYTHONPATH/PYTHONHOME/user site)
#   bin/bundle_check.py     imports / smoke self-check
#   BUNDLE_MANIFEST.json    every file: path, sha256, bytes, category
#   BUILD_REPORT.json       wall-clock + sizes of this build (not in the manifest)
#
# NO index data and NO model weights are bundled; the serve path finds them via
# SFU_THINCLIENT_INDEX_ROOT / SFU_SEISMIC_SHARD_MANIFEST / SFU_SPLADE_MODEL_PATH /
# SFU_EMBEDDING_MODEL_PATH / SFU_CE_MODEL_PATH (docs/infrastructure/PORTABLE_LINUX_BUNDLE.md).
#
# Env:
#   PORTABLE_LINUX_CACHE   download cache (CPython tarball + wheelhouse);
#                          default /tmp/claude-1000/portable_linux/cache
#   SFU_BUNDLE_OFFLINE=1   never touch the network; the cache must already hold
#                          the tarball and every locked wheel
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/../.." && pwd -P)"
# shellcheck source=pins.conf
source "$HERE/pins.conf"
LOCK="$HERE/serving_requirements_linux.lock.txt"

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <out_dir>" >&2
  exit 2
fi
mkdir -p "$1"
OUT="$(cd "$1" && pwd -P)"
case "$OUT/" in
  "$REPO/data/"*|"$REPO/"*) echo "refusing to build inside the repo tree: $OUT" >&2; exit 2 ;;
esac
if [[ -n "$(ls -A "$OUT")" ]]; then
  echo "refusing non-empty out_dir (builds must start fresh): $OUT" >&2
  exit 2
fi
[[ -f "$LOCK" ]] || { echo "missing $LOCK (run bundle_tool.py lock)" >&2; exit 2; }

CACHE="${PORTABLE_LINUX_CACHE:-/tmp/claude-1000/portable_linux/cache}"
WHEELHOUSE="$CACHE/wheelhouse"
mkdir -p "$CACHE" "$WHEELHOUSE"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
HOST_PY="$(command -v python3)"
TOOL="$HOST_PY $HERE/bundle_tool.py"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH PYTHONHOME || true

now() { date +%s.%N; }
dt() { awk -v a="$1" -v b="$2" 'BEGIN{printf "%.1f", b-a}'; }
T0=$(now)

# 1. relocatable CPython -------------------------------------------------------
TARBALL="$CACHE/$PBS_ASSET"
if [[ ! -f "$TARBALL" ]]; then
  [[ "${SFU_BUNDLE_OFFLINE:-0}" == "1" ]] && { echo "offline and $TARBALL missing" >&2; exit 3; }
  echo "[build] fetching $PBS_ASSET"
  curl -fsSL -o "$TARBALL.part" "$PBS_URL_BASE/$PBS_TAG/${PBS_ASSET//+/%2B}"
  mv "$TARBALL.part" "$TARBALL"
fi
echo "$PBS_SHA256  $TARBALL" | sha256sum -c --quiet - \
  || { echo "CPython tarball sha256 mismatch" >&2; exit 4; }
tar -xzf "$TARBALL" -C "$OUT"
PY="$OUT/python/bin/python3.11"
[[ -x "$PY" ]] || { echo "no $PY after extract" >&2; exit 4; }
$TOOL snapshot --root "$OUT/python" --out "$WORK/runtime_files.txt" >/dev/null
T_PY=$(now)

# 2. CPU-only serving wheels, hash-locked ---------------------------------------
if [[ "${SFU_BUNDLE_OFFLINE:-0}" != "1" ]]; then
  echo "[build] downloading locked wheels into $WHEELHOUSE"
  "$PY" -m pip download --disable-pip-version-check --quiet \
    --no-deps --only-binary=:all: --require-hashes \
    --index-url "$PYPI_INDEX" --extra-index-url "$TORCH_CPU_INDEX" \
    -r "$LOCK" -d "$WHEELHOUSE"
fi
T_DL=$(now)
echo "[build] installing locked wheels (offline, no deps resolution, no bytecode)"
"$PY" -m pip install --disable-pip-version-check --quiet \
  --no-index --find-links "$WHEELHOUSE" --no-deps --only-binary=:all: \
  --require-hashes --no-compile --no-cache-dir -r "$LOCK"
$TOOL fix-scripts --bin "$OUT/python/bin" --build-root "$OUT" \
  --site "$OUT/python/lib/python3.11/site-packages" >/dev/null
T_WHL=$(now)

# 3. portable seismic extension on a deterministic import path ------------------
SO_SRC="$REPO/$SEISMIC_SO_REL"
echo "$SEISMIC_SO_SHA256  $SO_SRC" | sha256sum -c --quiet - \
  || { echo "seismic .so sha256 mismatch: $SO_SRC" >&2; exit 5; }
mkdir -p "$OUT/ext/seismic"
cp "$SO_SRC" "$OUT/ext/seismic/"
printf '%s\n' \
  'from .seismic import *' \
  '' \
  '__doc__ = seismic.__doc__' \
  'if hasattr(seismic, "__all__"):' \
  '    __all__ = seismic.__all__' > "$OUT/ext/seismic/__init__.py"

# 4. serve-path source ----------------------------------------------------------
mkdir -p "$OUT/app/src"
( cd "$REPO/src" && find lib -type f -name '*.py' -print0 | sort -z \
    | xargs -0 -I{} install -D -m 0644 {} "$OUT/app/src/{}" )
install -m 0644 "$REPO/src/sfu_library_mcp_http.py" "$REPO/src/sfu_library_mcp_server.py" "$OUT/app/src/"

SITE="$OUT/python/lib/python3.11/site-packages"
printf '%s\n' '../../../../ext' '../../../../app/src' > "$SITE/sfu_bundle.pth"

# 5. launcher + self-check ------------------------------------------------------
mkdir -p "$OUT/bin"
cat > "$OUT/bin/sfu-python" <<'SH'
#!/bin/sh
d=$(cd "$(dirname "$(realpath "$0")")/.." && pwd -P)
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
exec "$d/python/bin/python3.11" "$@"
SH
chmod 0755 "$OUT/bin/sfu-python"
install -m 0644 "$HERE/bundle_check.py" "$OUT/bin/bundle_check.py"
T_ASM=$(now)

# 6. manifest -------------------------------------------------------------------
GIT_HEAD="$(git -C "$REPO" rev-parse HEAD)"
SRC_DIRTY="$(git -C "$REPO" status --porcelain -- src/lib src/sfu_library_mcp_http.py src/sfu_library_mcp_server.py | wc -l)"
META=$(printf '{"recipe_version":%s,"pbs_tag":"%s","pbs_asset":"%s","pbs_sha256":"%s","python_version":"%s","seismic_so_source":"%s","seismic_so_sha256":"%s","lock_sha256":"%s","source_git_head":"%s","source_dirty_files":%s,"env_contract":["SFU_THINCLIENT_INDEX_ROOT","SFU_SEISMIC_SHARD_MANIFEST","SFU_SPLADE_MODEL_PATH","SFU_EMBEDDING_MODEL_PATH","SFU_CE_MODEL_PATH"]}' \
  "$BUNDLE_RECIPE_VERSION" "$PBS_TAG" "$PBS_ASSET" "$PBS_SHA256" "$PBS_PY_VERSION" \
  "$SEISMIC_SO_REL" "$SEISMIC_SO_SHA256" "$(sha256sum "$LOCK" | cut -d' ' -f1)" \
  "$GIT_HEAD" "$SRC_DIRTY")
MSUM=$($TOOL manifest --root "$OUT" --baseline "$WORK/runtime_files.txt" \
  --out "$OUT/BUNDLE_MANIFEST.json" --meta "$META")
T_END=$(now)

DU_TOTAL=$(du -sb "$OUT" | cut -f1)
cat > "$OUT/BUILD_REPORT.json" <<JSON
{
 "out_dir": "$OUT",
 "wall_s": {
  "total": $(dt "$T0" "$T_END"),
  "fetch_extract_python": $(dt "$T0" "$T_PY"),
  "download_wheels": $(dt "$T_PY" "$T_DL"),
  "install_wheels": $(dt "$T_DL" "$T_WHL"),
  "assemble_so_source_launcher": $(dt "$T_WHL" "$T_ASM"),
  "manifest": $(dt "$T_ASM" "$T_END")
 },
 "du_bytes_apparent": $DU_TOTAL,
 "manifest_summary": $MSUM
}
JSON
cat "$OUT/BUILD_REPORT.json"
echo "[build] done: $OUT"
