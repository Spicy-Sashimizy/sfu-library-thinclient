#!/usr/bin/env python3
"""Userspace side of the hotset_protect cache_ext policy.

Five jobs, one per subcommand:

  chunks        Turn a Tier-1d result JSON into the chunk table that
                hotset_protect.c feeds into the `hot_chunks` BPF map.
  stack-chunks  Turn the PRODUCTION F1 hot-set sidecars (one or more
                <shard>.mmap/hotset_<budget>.json) into ONE multi-inode chunk
                table in the same format. This is the Phase-2 input.
  attach        Create/size the cgroup and start the policy loader against it,
                mirroring bench/bench_lib.py::CacheExtPolicy.start() from the
                cache_ext artifact.
  stats         Read the pinned `hotset_stats` array map (hook counters).
  refresh       Rewrite the PINNED `hot_chunks` map of an already-attached
                policy, in place, from a new chunk table (situation E8).

WHY A CHUNK TABLE AND NOT AN EXTENT LIST
----------------------------------------
BPF hash maps do exact-match lookups only, so the policy cannot ask "which
extent contains this pgoff?" without looping over every extent on every
folio_added. hotset_protect.bpf.c therefore keys on
(inode, pgoff >> 6) and stores a 64-bit membership bitmap for the 64 pages
of that chunk; this script does the extent -> chunk expansion.

WHERE THE HOT SET COMES FROM
----------------------------
t1d_cell.py records `skew.hot_extents` only for the CLUSTERED skew kind
(`hotsetc`); see spike/convergence_repro/t1d_cell.py:242 and :579. For the
scattered kinds (`hotset`, `zipf`) the field is null, and the hot set is the
prefix of a seeded ranking:

    rank_rng = np.random.default_rng(seed ^ 0x5EAB1D)   # == skew.ranking_seed
    ranking  = rank_rng.permutation(r_pages)
    hot      = ranking[:skew.hot_set_pages]

(t1d_cell.py:225-260). This script reproduces that exactly from the JSON's
`skew.ranking_seed`, `r_pages` and `skew.hot_set_pages`, so both skew kinds
are supported from a result JSON alone. Reproduction is verified against the
recorded `skew.hot_set_pages` count; it will NOT survive a change to
SkewDraw's ranking construction, and --self-check exits nonzero if the
reconstructed count disagrees with the JSON.

WHERE THE PRODUCTION HOT SET COMES FROM (`stack-chunks`)
--------------------------------------------------------
scripts/seismic_testbed/f1_hotset_generator.py writes one sidecar per shard
per budget dial at <shard>.mmap/hotset_<budget>.json, schema
"seismic.hotset.v1". The only field this script consumes is `extents`.

UNIT CONVERSION — there is NONE, and that is a load-bearing fact:

  * f1_hotset_generator.py:136
        pages = np.unique(np.asarray(visited, dtype=np.uint64) * WORD // PAGE)
    with WORD = 8 (f1:56, "dv visited starts are u64 word offsets into
    forward_data.bin") and PAGE = 4096 (f1:55). So a sidecar page id is
        (u64_word_offset * 8) // 4096
    i.e. a 4 KiB PAGE INDEX, FILE-RELATIVE to forward_data.bin. Not a byte
    offset, not a posting id, not a word offset.
  * f1_hotset_generator.py:70-87 coalesce_extents() emits
    [page_start, page_len] pairs — length in PAGES, not bytes.
  * f1_hotset_generator.py:191
        fwd_total_pages = int(shard_man["forward_data_words"]) * WORD // PAGE
    is recorded in the sidecar as `forward_data_total_pages`, again pages.
  * The sidecar also carries `page_size: 4096` explicitly; this script
    REFUSES any sidecar whose page_size is not PAGE, because the chunk
    bitmap format hard-codes a 4 KiB page.

That unit is exactly the `pgoff` the cache_ext `folio_added` hook sees for a
folio of forward_data.bin, so extents map straight onto (ino, pgoff>>6)
chunk bitmaps with no arithmetic beyond the shift.

Sidecar extents cover forward_data.bin ONLY (f1 counts `search_visited`
starts, which are forward-data word offsets). posting_lists.bin,
forward_offsets.bin and the document_mapping_*.bin files are mmap'd by the
serving path too but have no measured hot set, so they are NOT declared hot
here and land on the policy's cold list. That is deliberate, and it is the
Phase-2 result's main confound — see bench_stack_phase2.sh.

ASSUMPTIONS (all unverified — no cache_ext kernel exists here yet):
  * The target file is <data-dir>/R.bin (t1d_cell.py:360). L.bin is
    deliberately NOT declared hot.
  * inode numbers are stable for the life of the run. t1d_cell.py with
    --skip-laydown reuses the existing R.bin, so the ino resolved here is the
    ino the kernel sees. A cell that re-lays R.bin (no --skip-laydown) may
    get a different ino and the chunk table must be regenerated.
  * A chunk table is only valid on the machine and filesystem it was
    generated on: `stack-chunks` bakes in os.stat().st_ino. The dev container
    mounts the repo over 9p/v9fs, whose inode numbers are NOT the ones an
    ext4 cache_ext box will report. GENERATE THE PHASE-2 TABLE ON THE TARGET
    BOX; bench_stack_phase2.sh does exactly that, every run.
  * hotset_protect.out pins its stats map at /sys/fs/bpf/cache_ext/hotset_stats
    and (as of the E8 work) its hot_chunks map at
    /sys/fs/bpf/cache_ext/hotset_chunks; it needs that directory to exist
    (the upstream eval run.sh scripts mkdir it for cache_ext_get_scan's pin).
  * `bpftool` is the one built and installed by install_kernel.sh
    (/usr/local/sbin/bpftool, v7.3.0).
"""
import argparse
import glob as globmod
import json
import os
import subprocess
import sys
import time

import numpy as np

PAGE = 4096
CHUNK_SHIFT = 6                       # must match HOTSET_CHUNK_SHIFT
CHUNK_PAGES = 1 << CHUNK_SHIFT
CHUNK_MASK = CHUNK_PAGES - 1
MAX_CHUNK_ENTRIES = 1 << 18           # must match hot_chunks max_entries

STATS_PIN = "/sys/fs/bpf/cache_ext/hotset_stats"
CHUNKS_PIN = "/sys/fs/bpf/cache_ext/hotset_chunks"
BPFTOOL = os.environ.get("BPFTOOL", "/usr/local/sbin/bpftool")

# --- production sidecar constants (schema seismic.hotset.v1) ---------------
SIDECAR_SCHEMA = "seismic.hotset.v1"
# The one file the F1 sidecars describe; see the module docstring.
STACK_TARGET_FILE = "forward_data.bin"
# The v2 (E8 / dotvbyte forward_format_version 2) shard dirs the serving
# manifest data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json lists.
STACK_SHARD_GLOB = "*.e5.v2.mmap"
STACK_DEFAULT_BUDGET = "hot50_1.6gb"

# Index -> name, must match enum hotset_stat in hotset_protect.bpf.c.
STAT_NAMES = [
    "added_calls",
    "added_relevant",
    "added_hot",
    "added_cold",
    "accessed_calls",
    "accessed_relevant",
    "accessed_hot",
    "evicted_calls",
    "evicted_relevant",
    "evicted_hot",
    "evict_folios_calls",
    "evict_from_cold",
    "evict_from_hot",
    "evict_hot_fallback",
    "scan_cold",
    "scan_hot",
]


# ---------------------------------------------------------------------------
# (a) path -> inode
# ---------------------------------------------------------------------------

def resolve_ino(path):
    """Inode number the kernel will put in folio->mapping->host->i_ino."""
    st = os.stat(path)
    return int(st.st_ino), int(st.st_size)


# ---------------------------------------------------------------------------
# (b) t1d result JSON -> hot page ids -> chunk bitmaps
# ---------------------------------------------------------------------------

def hot_pages_from_result(result, self_check=True, epoch=0):
    """Return (hot_page_ids, r_pages, provenance_str) for a t1d result dict.

    The page ids come back in RANKING ORDER (rank 0 = hottest) rather than
    sorted, because --limit-mib truncates a prefix of that order. Callers that
    only want membership can np.unique() it; pages_to_chunks() does not care
    about order.

    epoch=1 reads the cell's POST-SWITCH hot set instead (t1d_cell.py
    --hotset-switch-pass, situation E8): the `hotset_switch` block carries the
    same kind / hot_set_pages / ranking_seed / hot_extents fields as `skew`, so
    the reconstruction below is the identical code path. That is what makes an
    E8 refresh table match the workload the cell switches to.
    """
    skew = result.get("skew")
    if not skew:
        raise SystemExit("result JSON has skew=null (uniform cell) — there is "
                         "no hot set to protect")
    if epoch:
        skew = result.get("hotset_switch")
        if not skew:
            raise SystemExit(
                "--epoch %d asked for the post-switch hot set, but this result "
                "JSON has no `hotset_switch` block — the cell was not run with "
                "t1d_cell.py --hotset-switch-pass" % epoch)

    npages = int(result["r_pages"])
    n_hot = int(skew["hot_set_pages"])
    extents = skew.get("hot_extents")

    if extents:
        # Clustered skew (hotsetc): the table is authoritative. SkewDraw builds
        # `hot` as the extents concatenated in table order (t1d_cell.py:243-247)
        # and ranking = [hot, permuted cold], so extent order IS ranking order.
        pages = np.concatenate([
            np.arange(int(s), int(s) + int(ln), dtype=np.int64)
            for s, ln in extents
        ])
        prov = "hot_extents table (%d extents, kind=%s)" % (len(extents),
                                                            skew["kind"])
    else:
        # Scattered skew (hotset / zipf): rebuild the seeded ranking prefix.
        ranking_seed = int(skew["ranking_seed"])
        rank_rng = np.random.default_rng(ranking_seed)
        ranking = rank_rng.permutation(npages).astype(np.int64)
        pages = ranking[:n_hot]
        prov = ("reconstructed ranking prefix (seed=%d, kind=%s)"
                % (ranking_seed, skew["kind"]))

    uniq = np.unique(pages)
    if self_check and uniq.size != n_hot:
        raise SystemExit(
            "self-check FAILED: derived %d hot pages but JSON says "
            "skew.hot_set_pages=%d (%s). SkewDraw's ranking construction "
            "probably changed; refusing to load a wrong hot set."
            % (uniq.size, n_hot, prov))
    if uniq.size and (uniq.min() < 0 or uniq.max() >= npages):
        raise SystemExit("derived hot page ids fall outside [0, r_pages)")

    return pages, npages, prov


# ---------------------------------------------------------------------------
# (b2) table knobs: --limit-mib (situation E3) and --corrupt-frac (E6)
# ---------------------------------------------------------------------------

def apply_limit_mib(pages, limit_mib):
    """Truncate to the hottest `limit_mib` MiB, i.e. a RANKING PREFIX.

    Situation E3 protects "exactly what fits" instead of the whole hot set, so
    the truncation must be by hotness order, never by page id. `pages` arrives
    from hot_pages_from_result() in ranking order, so this is a head slice.

    CAVEAT worth knowing when reading E3 numbers: within the hot set the t1d
    draw is UNIFORM (SkewDraw.draw() picks `self.hot[rng.integers(...)]`,
    t1d_cell.py:275-278) — every hot page carries the same expected touch rate.
    So a prefix of the ranking is an unbiased, seeded, reproducible cap-sized
    SUBSET of the hot set, not a "hotter half". That is the honest reading of
    E3: right-SIZED protection, not better-RANKED protection.
    """
    if limit_mib is None or limit_mib <= 0:
        return pages, None
    keep = int(limit_mib) * (1024 * 1024) // PAGE
    if keep >= pages.size:
        return pages, ("limit-mib %d MiB >= whole hot set (%.1f MiB), no "
                       "truncation" % (limit_mib, pages.size * PAGE / 1048576.0))
    out = pages[:keep]
    return out, ("truncated to hottest %d MiB (%d of %d pages, ranking prefix)"
                 % (limit_mib, out.size, pages.size))


def apply_corruption(pages, npages, frac, seed, all_hot=None):
    """Replace `frac` of the table with seeded WRONG pages, count preserved.

    Situation E6 asks how fast the win decays as the table drifts from real
    traffic. The substitution pool is the COLD remainder of R (every page not
    in the true hot set), so a corrupted entry is genuinely never-hot rather
    than merely mis-ranked, and frac=1.0 gives a table with ~zero touch mass —
    the "hotset degenerates to fifo" end of the ladder.

    Corruption is applied at PAGE granularity, not chunk granularity, because
    per-page membership is what hotset_protect.bpf.c::folio_is_hot() actually
    tests; the emitted CHUNK count therefore moves a little (scattered wrong
    pages touch more chunks than a clustered hot set did). The PAGE count is
    preserved exactly, which is the quantity that has to be held fixed for the
    ladder to isolate correctness from size.

    `all_hot` is the untruncated hot set (so that --limit-mib + --corrupt-frac
    compose: pages dropped by the limit are still not valid substitutes).
    """
    if not frac:
        return pages, None
    if not (0.0 < frac <= 1.0):
        raise SystemExit("--corrupt-frac must be in (0, 1], got %r" % frac)

    hot_all = np.unique(pages if all_hot is None else all_hot)
    mask = np.ones(npages, dtype=bool)
    mask[hot_all] = False
    cold_pool = np.flatnonzero(mask).astype(np.int64)

    n_bad = int(round(frac * pages.size))
    if n_bad > cold_pool.size:
        raise SystemExit(
            "--corrupt-frac %.3f needs %d wrong pages but only %d pages of R "
            "are outside the hot set — pick a smaller fraction or a smaller h"
            % (frac, n_bad, cold_pool.size))
    if n_bad == 0:
        return pages, "corrupt-frac %.3f rounds to 0 pages, table unchanged" % frac

    rng = np.random.default_rng([int(seed), 0xC0FFEE])
    victim_idx = rng.choice(pages.size, size=n_bad, replace=False)
    replacement = rng.choice(cold_pool, size=n_bad, replace=False)

    out = pages.copy()
    out[victim_idx] = replacement
    return out, ("corrupted %d of %d pages (frac=%.3f, seed=%d) with pages "
                 "drawn from the %d-page cold remainder"
                 % (n_bad, pages.size, frac, seed, cold_pool.size))


def pages_to_chunks(pages):
    """Collapse page ids into {chunk: uint64 bitmap}."""
    if pages.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.uint64)

    chunk_ids = (pages >> CHUNK_SHIFT).astype(np.int64)
    bits = (np.uint64(1) << (pages & CHUNK_MASK).astype(np.uint64))

    dense = np.zeros(int(chunk_ids.max()) + 1, dtype=np.uint64)
    np.bitwise_or.at(dense, chunk_ids, bits)

    nz = np.flatnonzero(dense)
    return nz.astype(np.int64), dense[nz]


def write_chunk_table(path, entries, header_lines):
    """entries: iterable of (ino, chunk_ids, bitmaps).

    One inode per element; the on-disk format has always carried the ino per
    line (hotset_protect.c::load_hot_chunks reads "%llu %llu %llx"), so a
    multi-inode table needs no format change and no loader change.
    """
    total = 0
    with open(path, "w") as fh:
        for line in header_lines:
            fh.write("# %s\n" % line)
        fh.write("# format: <ino> <chunk> <bitmap_hex>\n")
        for ino, chunk_ids, bitmaps in entries:
            for c, b in zip(chunk_ids.tolist(), bitmaps.tolist()):
                fh.write("%d %d %x\n" % (ino, c, b))
                total += 1
    return total


def check_chunk_budget(n_chunks, what):
    if n_chunks > MAX_CHUNK_ENTRIES:
        raise SystemExit(
            "%s needs %d chunks but hot_chunks max_entries is %d — raise "
            "HOTSET_CHUNK_SHIFT or max_entries in hotset_protect.bpf.c"
            % (what, n_chunks, MAX_CHUNK_ENTRIES))


def cmd_chunks(args):
    with open(args.result_json) as fh:
        result = json.load(fh)

    target = args.file or os.path.join(args.data_dir, "R.bin")
    ino, size = resolve_ino(target)
    file_pages = (size + PAGE - 1) // PAGE

    pages, npages, prov = hot_pages_from_result(
        result, self_check=not args.no_self_check, epoch=args.epoch)
    full_hot = pages
    src_block = result["hotset_switch"] if args.epoch else result["skew"]

    if file_pages < int(result["r_pages"]):
        print("WARNING: %s holds %d pages but the result JSON was produced "
              "against r_pages=%d — the hot set may not fit the file on disk"
              % (target, file_pages, result["r_pages"]), file=sys.stderr)

    knob_notes = []
    pages, note = apply_limit_mib(pages, args.limit_mib)
    if note:
        knob_notes.append(note)
    pages, note = apply_corruption(pages, npages, args.corrupt_frac,
                                   args.corrupt_seed, all_hot=full_hot)
    if note:
        knob_notes.append(note)

    chunk_ids, bitmaps = pages_to_chunks(np.unique(pages))
    check_chunk_budget(chunk_ids.size, "hot set")

    header = [
        "hotset_protect chunk table",
        "source result: %s" % os.path.abspath(args.result_json),
        "target file:   %s (ino=%d, %d pages)" % (target, ino, file_pages),
        "skew:          %s%s" % (src_block["spec"],
                                 "" if not args.epoch
                                 else "  [epoch 1: the post-switch hot set, "
                                      "switch_pass=%s switch_seed=%s]"
                                      % (src_block["switch_pass"],
                                         src_block["switch_seed"])),
        "hot set:       %d pages (%.3f MiB), %s"
        % (pages.size, pages.size * PAGE / (1024.0 * 1024.0), prov),
        "chunks:        %d (chunk = %d pages)" % (chunk_ids.size, CHUNK_PAGES),
    ] + ["knob:          %s" % n for n in knob_notes]
    write_chunk_table(args.out, [(ino, chunk_ids, bitmaps)], header)

    for line in header:
        print(line)
    print("wrote %s" % args.out)


# ---------------------------------------------------------------------------
# (b3) PRODUCTION sidecars -> one multi-inode chunk table  (`stack-chunks`)
# ---------------------------------------------------------------------------

def discover_shard_dirs(args):
    dirs = []
    for d in args.shard_dir or []:
        dirs.append(os.path.abspath(d))
    for parent in args.index_dir or []:
        hits = sorted(globmod.glob(os.path.join(os.path.abspath(parent),
                                                args.shard_glob)))
        if not hits:
            raise SystemExit("no shard dirs matching %r under %s"
                             % (args.shard_glob, parent))
        dirs.extend(hits)
    if not dirs:
        raise SystemExit("give at least one --shard-dir or --index-dir")
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def sidecar_extents_to_pages(sidecar, path):
    """[page_start, page_len] pairs -> a sorted int64 array of page ids.

    No unit conversion: f1_hotset_generator.py already emits 4 KiB
    file-relative page indices into forward_data.bin (f1:55-56, :136, :70-87).
    The page_size assertion below is the guard that keeps that true.
    """
    if sidecar.get("schema") != SIDECAR_SCHEMA:
        raise SystemExit("%s: schema is %r, expected %r — refusing"
                         % (path, sidecar.get("schema"), SIDECAR_SCHEMA))
    ps = int(sidecar.get("page_size", 0))
    if ps != PAGE:
        raise SystemExit(
            "%s: page_size=%d but the chunk-bitmap format assumes %d-byte "
            "pages (HOTSET_CHUNK_SHIFT counts 4 KiB pages) — refusing"
            % (path, ps, PAGE))
    extents = sidecar.get("extents")
    if not extents:
        raise SystemExit("%s: no extents — refusing to emit an empty table "
                         "silently (use the fifo_ctl arm for an empty table)"
                         % path)
    bad = [e for e in extents if len(e) != 2 or int(e[1]) <= 0 or int(e[0]) < 0]
    if bad:
        raise SystemExit("%s: %d malformed extents, first=%r"
                         % (path, len(bad), bad[0]))
    return np.concatenate([
        np.arange(int(s), int(s) + int(ln), dtype=np.int64)
        for s, ln in extents
    ])


def check_version_keys(shard_dir, sidecar):
    """The F1 discipline (f1_hotset_generator.py:184-188): a sidecar built
    against a different forward encoding must fail loud, never pin garbage.
    manifest.json is ~22 MB per shard on the served corpus, so this is opt-out.
    """
    want = sidecar.get("version_keys") or {}
    man_path = os.path.join(shard_dir, "manifest.json")
    if not os.path.exists(man_path):
        raise SystemExit("%s: manifest.json missing — cannot verify the "
                         "sidecar's version_keys" % shard_dir)
    with open(man_path) as fh:
        man = json.load(fh)
    for k, v in want.items():
        if man.get(k) != v:
            raise SystemExit(
                "%s: sidecar version_keys mismatch on %r (sidecar=%r, "
                "manifest=%r) — the shard was rebuilt since the sidecar was "
                "generated; regenerate with f1_hotset_generator.py"
                % (shard_dir, k, v, man.get(k)))


def cmd_stack_chunks(args):
    shard_dirs = discover_shard_dirs(args)
    rows, entries = [], []
    tot_pages = tot_chunks = 0

    for shard_dir in shard_dirs:
        sc_path = os.path.join(shard_dir, "hotset_%s.json" % args.budget)
        if not os.path.exists(sc_path):
            raise SystemExit(
                "%s: no sidecar for budget %r. Available: %s"
                % (shard_dir, args.budget,
                   ", ".join(sorted(os.path.basename(p) for p in globmod.glob(
                       os.path.join(shard_dir, "hotset_*.json")))) or "(none)"))
        with open(sc_path) as fh:
            sidecar = json.load(fh)

        target = os.path.join(shard_dir, args.target_file)
        # SELF-CHECK 1: a sidecar naming a file that is not there is fatal.
        if not os.path.exists(target):
            raise SystemExit("%s: sidecar %s references a file that does not "
                             "exist — refusing to emit"
                             % (target, os.path.basename(sc_path)))
        if not args.no_version_check:
            check_version_keys(shard_dir, sidecar)

        ino, size = resolve_ino(target)
        file_pages = (size + PAGE - 1) // PAGE
        pages = sidecar_extents_to_pages(sidecar, sc_path)

        # SELF-CHECK 2: extents past EOF mean the sidecar and the file have
        # drifted apart; a pgoff beyond i_size can never be a real folio, so
        # emitting it would silently shrink the protected set.
        end = int(pages.max()) + 1
        if end > file_pages:
            raise SystemExit(
                "%s: sidecar extents reach page %d but %s holds only %d pages "
                "(%d bytes) — refusing to emit"
                % (sc_path, end - 1, args.target_file, file_pages, size))
        declared = int(sidecar.get("forward_data_total_pages", 0))
        if declared and abs(declared - file_pages) > 1:
            raise SystemExit(
                "%s: sidecar says forward_data_total_pages=%d but the file on "
                "disk is %d pages — refusing to emit"
                % (sc_path, declared, file_pages))

        uniq = np.unique(pages)
        chunk_ids, bitmaps = pages_to_chunks(uniq)
        entries.append((ino, chunk_ids, bitmaps))
        tot_pages += int(uniq.size)
        tot_chunks += int(chunk_ids.size)
        rows.append({
            "shard_dir": shard_dir, "file": target, "ino": ino,
            "pages": int(uniq.size), "mib": uniq.size * PAGE / 1048576.0,
            "extents": len(sidecar["extents"]), "chunks": int(chunk_ids.size),
            "file_pages": file_pages,
        })

    check_chunk_budget(tot_chunks, "production hot set (%d shards)" % len(rows))

    header = [
        "hotset_protect chunk table (PRODUCTION, multi-inode)",
        "budget dial:   hotset_%s.json" % args.budget,
        "shards:        %d" % len(rows),
        "target file:   %s (per shard)" % args.target_file,
        "hot set:       %d pages (%.1f MiB, %.3f GiB) across %d inodes"
        % (tot_pages, tot_pages * PAGE / 1048576.0,
           tot_pages * PAGE / float(1 << 30), len(rows)),
        "chunks:        %d of %d map slots (chunk = %d pages)"
        % (tot_chunks, MAX_CHUNK_ENTRIES, CHUNK_PAGES),
        "generated on:  %s (inodes are host+filesystem specific)"
        % os.uname().nodename,
    ]
    for r in rows:
        header.append("shard ino=%d pages=%d (%.1f MiB) chunks=%d file=%s"
                      % (r["ino"], r["pages"], r["mib"], r["chunks"], r["file"]))

    n = write_chunk_table(args.out, entries, header)

    print("%-22s %-12s %10s %10s %10s  %s"
          % ("ino", "shard", "hot pages", "hot MiB", "chunks", "file"))
    for r in rows:
        print("%-22d %-12s %10d %10.1f %10d  %s"
              % (r["ino"], os.path.basename(r["shard_dir"]).split(".")[0],
                 r["pages"], r["mib"], r["chunks"], r["file"]))
    print("%-22s %-12s %10d %10.1f %10d  (%.3f GiB)"
          % ("TOTAL", "%d shards" % len(rows), tot_pages,
             tot_pages * PAGE / 1048576.0, tot_chunks,
             tot_pages * PAGE / float(1 << 30)))
    print("wrote %s (%d lines)" % (args.out, n))

    if args.inodes_out:
        with open(args.inodes_out, "w") as fh:
            for r in rows:
                fh.write("%d\n" % r["ino"])
        print("wrote %s (one hot inode per line)" % args.inodes_out)


# ---------------------------------------------------------------------------
# (c) load / attach, mirroring bench/bench_lib.py
# ---------------------------------------------------------------------------

def run(cmd, check=True):
    print("+ %s" % " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, check=check)


def recreate_cgroup(name, limit_bytes):
    """Mirror of bench_lib.recreate_cache_ext_cgroup().

    Deliberately uses cgcreate + memory.max rather than the repo's usual
    `systemd-run --scope -p MemoryMax=`: the policy is attached to a cgroup
    *path* opened by the loader, so the benchmark has to land in a cgroup
    whose path is known up front, which a transient systemd scope is not.
    """
    subprocess.run(["sudo", "cgdelete", "-g", "memory:%s" % name], check=False)
    run(["sudo", "cgcreate", "-g", "memory:%s" % name])
    run(["sudo", "sh", "-c",
         "echo %d > /sys/fs/cgroup/%s/memory.max" % (limit_bytes, name)])
    run(["sudo", "sh", "-c",
         "echo 0 > /sys/fs/cgroup/%s/memory.swap.max" % name])


def cmd_attach(args):
    if args.cgroup_max_bytes:
        recreate_cgroup(args.cgroup, args.cgroup_max_bytes)

    run(["sudo", "mkdir", "-p", os.path.dirname(STATS_PIN)])

    cmd = [
        "sudo",
        args.loader,
        "--watch_dir", args.watch_dir,
        "--cgroup_path", "/sys/fs/cgroup/%s" % args.cgroup,
    ]
    if args.hot_chunks:
        cmd += ["--hot_chunks", args.hot_chunks]

    print("+ %s" % " ".join(cmd), file=sys.stderr)
    proc = subprocess.Popen(cmd)

    # bench_lib.CacheExtPolicy.start() sleeps 10s then checks the child is
    # still alive; struct_ops load + verification is not instant.
    time.sleep(args.settle)
    if proc.poll() is not None:
        raise SystemExit("policy loader exited early with rc=%d" % proc.returncode)

    print("policy attached; loader pid=%d. SIGINT it to detach." % proc.pid)
    print("PID=%d" % proc.pid)
    return proc


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def _decode_value(v):
    """bpftool emits either an int (BTF-formatted) or a byte-array of hex."""
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v, 0)
    if isinstance(v, list):
        out = 0
        for i, byte in enumerate(v):
            out |= int(byte, 0) << (8 * i)   # little endian
        return out
    raise ValueError("unrecognised bpftool value: %r" % (v,))


def read_stats(pin=STATS_PIN):
    proc = subprocess.run([BPFTOOL, "map", "dump", "pinned", pin, "-j"],
                          capture_output=True, text=True, check=True)
    entries = json.loads(proc.stdout)
    out = {}
    for e in entries:
        if "formatted" in e:
            e = e["formatted"]
        key = _decode_value(e["key"])
        val = _decode_value(e["value"])
        name = STAT_NAMES[key] if key < len(STAT_NAMES) else "stat_%d" % key
        out[name] = val
    return out


def cmd_refresh(args):
    """Rewrite the pinned hot_chunks map of a LIVE policy (situation E8).

    Why this shells out to the loader instead of driving bpftool: the E8 table
    is ~20k chunk entries for a t1d cell and ~58k for the production sidecars,
    and `bpftool map update` is one process spawn per entry (minutes of stall
    mid-benchmark). hotset_protect.out --refresh_chunks opens the pin with
    bpf_obj_get() and does the whole rewrite in one process using the same
    load_hot_chunks() parser the attach path uses, so the table on the wire is
    byte-for-byte the table the attach path would have loaded.

    Default is a REPLACE (clear then load), because E8 switches to a
    *different* hot set: a merge would leave the stale set protected too.
    """
    if not os.path.exists(args.pin):
        raise SystemExit(
            "%s does not exist — no policy is attached, or the attached "
            "hotset_protect.out predates hot_chunks pinning" % args.pin)
    cmd = ["sudo", args.loader, "--refresh_chunks", args.hot_chunks,
           "--chunks_pin", args.pin]
    if args.merge:
        cmd.append("--no_clear")
    run(cmd)


def cmd_stats(args):
    stats = read_stats(args.pin)
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        for name in STAT_NAMES:
            print("%-22s %d" % (name, stats.get(name, 0)))


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("chunks", help="t1d result JSON -> hot_chunks table")
    p.add_argument("--result-json", required=True)
    p.add_argument("--data-dir", default="/var/tmp/t1d_scratch",
                   help="directory holding R.bin (t1d_cell.py --data-dir)")
    p.add_argument("--file", default=None,
                   help="override the target file (default <data-dir>/R.bin)")
    p.add_argument("--out", required=True, help="chunk table to write")
    p.add_argument("--no-self-check", action="store_true",
                   help="do not fail when the reconstructed hot-set size "
                        "disagrees with skew.hot_set_pages")
    p.add_argument("--epoch", type=int, default=0, choices=(0, 1),
                   help="0 (default) = the cell's original hot set; 1 = the "
                        "POST-SWITCH hot set of a cell run with t1d_cell.py "
                        "--hotset-switch-pass, i.e. the table situation E8 "
                        "refreshes TO when the workload also moves")
    p.add_argument("--limit-mib", type=int, default=None,
                   help="situation E3: emit only the hottest N MiB of the hot "
                        "set (a ranking prefix), so protection is sized to "
                        "the cap instead of to the whole hot set")
    p.add_argument("--corrupt-frac", type=float, default=0.0,
                   help="situation E6: replace this fraction of the emitted "
                        "table with seeded pages from R's cold remainder; the "
                        "page count is preserved exactly (0 = off)")
    p.add_argument("--corrupt-seed", type=int, default=20260906,
                   help="seed for --corrupt-frac (the corruption draw is "
                        "reproducible from this alone)")
    p.set_defaults(func=cmd_chunks)

    p = sub.add_parser("stack-chunks",
                       help="production hot-set sidecars -> multi-inode table")
    p.add_argument("--shard-dir", action="append", default=[],
                   help="a <shard>.mmap directory (repeatable)")
    p.add_argument("--index-dir", action="append", default=[],
                   help="a parent directory to glob for shard dirs "
                        "(repeatable), e.g. data/seismic_150m/index/plan01")
    p.add_argument("--shard-glob", default=STACK_SHARD_GLOB,
                   help="glob applied under --index-dir (default %(default)s, "
                        "the E8 dv-v2 shards the serving manifest lists)")
    p.add_argument("--budget", default=STACK_DEFAULT_BUDGET,
                   help="sidecar budget dial: reads hotset_<budget>.json "
                        "(f1_hotset_generator.py emits hot50_1.6gb, "
                        "hot80_4.2gb, full_touched); default %(default)s")
    p.add_argument("--target-file", default=STACK_TARGET_FILE,
                   help="the mmap'd file the sidecar's page ids index into "
                        "(default %(default)s; nothing else has a hot set)")
    p.add_argument("--out", required=True, help="chunk table to write")
    p.add_argument("--inodes-out", default=None,
                   help="also write the hot inodes, one per line (the "
                        "phase-2 bench logs these to prove the table matches "
                        "the files the serving process actually opened)")
    p.add_argument("--no-version-check", action="store_true",
                   help="skip the sidecar-vs-manifest version_keys check "
                        "(each shard manifest.json is ~22 MB to parse)")
    p.set_defaults(func=cmd_stack_chunks)

    p = sub.add_parser("attach", help="start the policy loader on a cgroup")
    p.add_argument("--loader", required=True,
                   help="path to policies/hotset_protect.out")
    p.add_argument("--watch_dir", "--watch-dir", dest="watch_dir", required=True,
                   help="directory whose inodes the policy manages "
                        "(dir_watcher; use the t1d --data-dir)")
    p.add_argument("--cgroup", default="cache_ext_test",
                   help="cgroup NAME under /sys/fs/cgroup")
    p.add_argument("--hot-chunks", dest="hot_chunks", default=None,
                   help="chunk table from `chunks`; omit for the all-cold "
                        "FIFO control arm")
    p.add_argument("--cgroup-max-bytes", type=int, default=0,
                   help="if set, recreate the cgroup with this memory.max")
    p.add_argument("--settle", type=float, default=10.0)
    p.set_defaults(func=cmd_attach)

    p = sub.add_parser("stats", help="dump the pinned hook counters")
    p.add_argument("--pin", default=STATS_PIN)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("refresh",
                       help="rewrite the pinned hot_chunks map of a live policy")
    p.add_argument("--loader", required=True,
                   help="path to policies/hotset_protect.out")
    p.add_argument("--hot-chunks", dest="hot_chunks", required=True,
                   help="the NEW chunk table to install")
    p.add_argument("--pin", default=CHUNKS_PIN,
                   help="pinned hot_chunks map (default %(default)s)")
    p.add_argument("--merge", action="store_true",
                   help="keep the existing entries and add to them; the "
                        "default REPLACES the table (E8 switches hot sets)")
    p.set_defaults(func=cmd_refresh)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
