#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# build_offline.sh -- compile hotset_protect on a STOCK kernel.
#
# This is NOT the production build path. The real one is upstream's
# build_policies.sh on a -cache-ext kernel (see ../cache_ext_hotset.patch);
# it refuses to run anywhere else, which is why this spike sat at "NEVER
# COMPILED" from 2026-09-06 to 2026-09-25.
#
# What this script proves, and all it proves:
#   1. hotset_protect.bpf.c compiles clean to BPF bytecode.
#   2. bpftool can generate a skeleton for it, including the
#      `.struct_ops.link` section (needs libbpf >= 1.2).
#   3. hotset_protect.c compiles and links against that skeleton.
#   4. with --load, exactly where and how the kernel refuses it.
# It proves NOTHING about eviction behaviour or performance. Every
# performance statement in this spike stays *est.*
#
# It works by supplying the cache_ext kernel ABI from
# cache_ext_abi.bpf.h (definitions transcribed from the pinned kernel
# commit) and stubbing the patched-libbpf attach entry point
# (cache_ext_attach_shim.c). No file in cache_ext_upstream/ is modified.
#
# Deps (Debian 12): clang llvm libelf-dev zlib1g-dev pkg-config git curl.
# libbpf and bpftool are built from source into $CACHE_DIR because Debian
# bookworm ships libbpf 1.1.2 / bpftool 7.1.0, which SKIP `.struct_ops.link`
# ("libbpf: elf: skipping unrecognized data section(18) .struct_ops.link")
# and therefore emit a skeleton with no struct_ops member at all.
#
# Usage:
#   ./build_offline.sh            # build only
#   ./build_offline.sh --load     # build, then attempt a load and log it
set -eu -o pipefail

LIBBPF_TAG="${LIBBPF_TAG:-v1.6.2}"
BPFTOOL_TAG="${BPFTOOL_TAG:-v7.6.0}"
CLANG="${CLANG:-clang}"

HERE="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
SPIKE="$(dirname "$HERE")"
POLICIES="$SPIKE/cache_ext_upstream/policies"
BUILD="${BUILD_DIR:-$HERE/build}"
CACHE_DIR="${CACHE_DIR:-$BUILD/toolchain}"

DO_LOAD=0
[ "${1:-}" = "--load" ] && DO_LOAD=1

mkdir -p "$BUILD" "$CACHE_DIR"

echo "== host =="
uname -r
$CLANG --version | head -1

# ---------------------------------------------------------------- toolchain
LIBBPF_INST="$CACHE_DIR/libbpf-inst"
if [ ! -f "$LIBBPF_INST/usr/lib64/libbpf.a" ]; then
	echo "== building libbpf $LIBBPF_TAG =="
	[ -d "$CACHE_DIR/libbpf" ] || \
		git clone -q --depth 1 --branch "$LIBBPF_TAG" \
			https://github.com/libbpf/libbpf.git "$CACHE_DIR/libbpf"
	make -C "$CACHE_DIR/libbpf/src" -j"$(nproc)" BUILD_STATIC_ONLY=1 \
		OBJDIR="$CACHE_DIR/libbpf-build" DESTDIR="$LIBBPF_INST" \
		PREFIX=/usr install install_uapi_headers >/dev/null
fi

BPFTOOL="$CACHE_DIR/bpftool/src/bpftool"
if [ ! -x "$BPFTOOL" ]; then
	echo "== building bpftool $BPFTOOL_TAG =="
	[ -d "$CACHE_DIR/bpftool" ] || \
		git clone -q --depth 1 --recurse-submodules --shallow-submodules \
			--branch "$BPFTOOL_TAG" \
			https://github.com/libbpf/bpftool.git "$CACHE_DIR/bpftool"
	make -C "$CACHE_DIR/bpftool/src" -j"$(nproc)" >/dev/null
fi
"$BPFTOOL" version

# ------------------------------------------------------------------ sources
# Copied, never symlinked: upstream headers do #include "vmlinux.h" relative
# to themselves, and the vmlinux.h here is the STOCK one, not theirs.
cp "$POLICIES/cache_ext_lib.bpf.h" "$POLICIES/dir_watcher.bpf.h" \
   "$POLICIES/dir_watcher.h" "$BUILD/"
cp "$SPIKE/hotset_protect.bpf.c" "$SPIKE/hotset_protect.c" "$BUILD/"
cp "$HERE/cache_ext_abi.bpf.h" "$HERE/cache_ext_attach_shim.h" \
   "$HERE/cache_ext_attach_shim.c" "$BUILD/"

if [ ! -s "$BUILD/vmlinux.h" ]; then
	echo "== vmlinux.h from /sys/kernel/btf/vmlinux =="
	"$BPFTOOL" btf dump file /sys/kernel/btf/vmlinux format c > "$BUILD/vmlinux.h"
fi
wc -l < "$BUILD/vmlinux.h" | xargs echo "vmlinux.h lines:"

# Loud, because this is the whole reason the load cannot succeed.
echo "== cache_ext presence in the RUNNING kernel =="
for t in cache_ext_ops cache_ext_list_node cache_ext_eviction_ctx \
         cache_ext_iterate_opts sampling_options; do
	printf '  vmlinux.h: %-24s %s hits\n' "$t" \
		"$(grep -cw "$t" "$BUILD/vmlinux.h" || true)"
done
printf '  kallsyms:  %-24s %s hits\n' "bpf_cache_ext_*" \
	"$(grep -c 'bpf_cache_ext' /proc/kallsyms || true)"

ARCH=$(uname -m | sed 's/x86_64/x86/;s/aarch64/arm64/')
CLANG_SYS_INC=$($CLANG -v -E - </dev/null 2>&1 \
	| sed -n '/<...> search starts here:/,/End of search list./{ s| \(/.*\)|-idirafter \1|p }')

cd "$BUILD"

echo "== clang -target bpf =="
# shellcheck disable=SC2086
$CLANG -O2 -target bpf -D__TARGET_ARCH_$ARCH -c -g -Wall -I. \
	-include cache_ext_abi.bpf.h $CLANG_SYS_INC \
	hotset_protect.bpf.c -o hotset_protect.bpf.o

echo "== bpftool gen skeleton =="
"$BPFTOOL" gen skeleton hotset_protect.bpf.o > hotset_protect.skel.h
grep -q 'struct_ops' hotset_protect.skel.h || {
	echo "FATAL: skeleton has no struct_ops member (libbpf too old)"; exit 1; }

echo "== clang (userspace loader) =="
$CLANG -O2 -g -Wall -I. -I"$LIBBPF_INST/usr/include" \
	-include cache_ext_attach_shim.h \
	hotset_protect.c cache_ext_attach_shim.c -o hotset_protect.out \
	"$LIBBPF_INST/usr/lib64/libbpf.a" -lelf -lz

echo "== BUILD OK =="
ls -l hotset_protect.bpf.o hotset_protect.skel.h hotset_protect.out

if [ "$DO_LOAD" -eq 0 ]; then
	echo "(re-run with --load to attempt a kernel load)"
	exit 0
fi

# ---------------------------------------------------------------- load test
echo "== load attempt =="
mkdir -p "$BUILD/watchdir"
: > "$BUILD/watchdir/probe.bin"
echo "-- capabilities --"
grep -E 'Cap(Prm|Eff|Bnd)' /proc/self/status
echo "unprivileged_bpf_disabled=$(cat /proc/sys/kernel/unprivileged_bpf_disabled)"
echo "-- unprivileged --"
./hotset_protect.out --watch_dir "$BUILD/watchdir" \
	--cgroup_path /sys/fs/cgroup </dev/null 2>&1 | sed 's/^/   /' || true
echo "-- root --"
sudo ./hotset_protect.out --watch_dir "$BUILD/watchdir" \
	--cgroup_path /sys/fs/cgroup </dev/null 2>&1 | sed 's/^/   /' || true
