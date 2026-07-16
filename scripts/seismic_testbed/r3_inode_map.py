#!/usr/bin/env python3
"""R3 instrument 2 (2026-07-16; doc 15 §1/§2): inventory (path, dev, ino, size)
for every file of BOTH mmap shards the driver will serve, writing

  data/eval_results/_r3_inode_map.json    — per-file records (the join key)
  data/eval_results/_r3_inode_body.bt     — a bpftrace BODY fragment (the
                                            `@shard_inodes[ino]=tag` lines +
                                            `@shard_inodes_count=N`, NO BEGIN
                                            wrapper) that the orchestrator
                                            splices into each probe's single
                                            BEGIN block at the /*INODE_BODY*/
                                            placeholder. bpftrace rejects more
                                            than one BEGIN probe, so the body
                                            must live INSIDE the probe's BEGIN
                                            (not its own). For IN-PROBE filtering
                                            (the ledger never post-filters —
                                            event rate would swamp the buffer).

This runs IN-CONTAINER (the shard files are bind-mounted with real inodes,
and the WSL2 kernel is shared with the host, so the host-side --pid=host
tracer sees identical inode numbers). It is read-only over the shards.

The two shards: the R2/R3 cells run the full 8-shard E8-v2 served manifest by
default, but the ledger filter must name only the files actually mmap'd by the
process. A 150M cell mmaps ALL 8 shards' slabs (~96 files) — too many inodes
for a clean bpftrace map and most are not the eviction-inversion carriers.
Per doc 15 §5 the inversion is a 12/16 GB repeat-set phenomenon; the per-page
ledger needs the files the search path faults. We inventory the files the F1
hot-set sidecar already identified as touched (forward_data.bin across shards,
the dominant fault target) PLUS the full slab list so the join can attribute
structurally, but the ledger IN-PROBE filter defaults to the forward slabs
(the repeat-set carriers). `--scope all` inventories every slab file.

Reproducible: deterministic file ordering, absolute repo-rooted paths.
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
OUT_JSON = REPO / "data/eval_results/_r3_inode_map.json"
OUT_BT = REPO / "data/eval_results/_r3_inode_body.bt"

# The slabs whose pages the search path faults. forward_data.bin is the
# repeat-set carrier (the F1 sidecar / search_visited coord system); the
# structure slabs (posting_lists, doc-mapping, forward_offsets, token map)
# are the load-residue floor (doc 15 §2 / 04 §2.1).
FORWARD_SLAB = "forward_data.bin"
STRUCT_SLABS = ("posting_lists.bin", "document_mapping_strings.bin",
                "document_mapping_offsets.bin", "forward_offsets.bin",
                "forward_encoder.bin", "token_to_id_map.bin")


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def shard_mmap_dirs(manifest: Path) -> list[Path]:
    """Resolve the served mmap_dir for every shard record (the C2.5 mmap_dir
    field, persistent post-/tmp-wipe). Repo-rooted if relative."""
    m = json.loads(manifest.read_text())
    recs = m["shards"]
    dirs = []
    for s in recs:
        p = Path(s["mmap_dir"])
        if not p.is_absolute():
            p = REPO / p
        dirs.append(p)
    return dirs


def inventory(dirs: list[Path], scope: str) -> list[dict]:
    out = []
    for si, d in enumerate(dirs):
        if not d.is_dir():
            log(f"  WARN shard {si} dir missing: {d}")
            continue
        for f in sorted(d.glob("*")):
            if not f.is_file():
                continue
            name = f.name
            if scope == "forward" and name != FORWARD_SLAB:
                # forward scope: only each shard's forward_data.bin (the
                # repeat-set carrier — the search_visited coord system).
                # Structure slabs + manifest.json are excluded from the probe
                # filter (they are load-residue, inventoried under --scope all).
                continue
            st = f.stat()
            out.append({"shard": si, "path": str(f.relative_to(REPO)),
                        "abs_path": str(f), "name": name,
                        "dev": st.st_dev, "ino": st.st_ino,
                        "size": st.st_size,
                        "slab": "forward" if name == FORWARD_SLAB
                                else ("structure" if name in STRUCT_SLABS
                                      else "other")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-bt", default=str(OUT_BT))
    ap.add_argument("--scope", choices=("forward", "all"), default="forward",
                    help="forward: only each shard's forward_data.bin (the "
                         "repeat-set carrier, the search_visited coord) + "
                         "manifest.json for the join. all: every slab file.")
    args = ap.parse_args()

    dirs = shard_mmap_dirs(Path(args.manifest))
    log(f"inventorying {len(dirs)} shard dirs (scope={args.scope})")
    recs = inventory(dirs, args.scope)
    if not recs:
        log("FATAL: no files inventoried — shards not mounted?")
        sys.exit(2)

    # dedup inodes (hardlinks / same file) — keep first, note dups
    seen = {}
    deduped = []
    for r in recs:
        key = (r["dev"], r["ino"])
        if key in seen:
            seen[key].setdefault("also_as", []).append(r["path"])
        else:
            r["also_as"] = []
            deduped.append(r)
            seen[key] = r

    inodes = sorted({r["ino"] for r in deduped})
    by_slab = {}
    for r in deduped:
        by_slab.setdefault(r["slab"], []).append(r["ino"])

    out = {
        "probe": "r3_inode_map", "date": time.strftime("%Y-%m-%d"),
        "manifest": str(Path(args.manifest).relative_to(REPO)),
        "scope": args.scope, "n_shards": len(dirs),
        "n_files": len(deduped), "n_distinct_inodes": len(inodes),
        "forward_data_total_gb": round(
            sum(r["size"] for r in deduped if r["slab"] == "forward") / 1e9, 4),
        "inodes_by_slab": {k: sorted(v) for k, v in by_slab.items()},
        "files": deduped,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2))
    log(f"wrote {args.out_json}: {len(deduped)} files, {len(inodes)} distinct "
        f"inodes, forward total {out['forward_data_total_gb']} GB")

    # bpftrace BODY fragment (NOT a BEGIN block — just the @shard_inodes[] =
    # tag lines + the count) that the orchestrator splices into each probe's
    # single BEGIN at the /*INODE_BODY*/ placeholder. bpftrace rejects more
    # than one BEGIN probe (REQ-3 monitor found this the hard way), so the
    # body must live INSIDE the probe's BEGIN, not its own.
    lines = [
        "// AUTO-GENERATED by r3_inode_map.py — bpftrace BODY fragment",
        "// (NOT a BEGIN block). Spliced into each probe's single BEGIN at the",
        "// /*INODE_BODY*/ placeholder by the orchestrator. Populates",
        "// @shard_inodes[ino] = <tag> so the probes filter filemap/vmscan",
        "// events to ONLY shard slabs IN-PROBE.",
        f"// generated {time.strftime('%Y-%m-%d')}; scope={args.scope}; "
        f"{len(inodes)} inodes.",
    ]
    TAG = {"forward": 1, "structure": 2, "other": 3}
    for r in deduped:
        lines.append(f'  @shard_inodes[{r["ino"]}] = {TAG[r["slab"]]};')
    # breadcrumb the probes print at attach: if this is 0, the inode map did
    # not load OR the kernel inodes seen by --pid=host differ from those
    # stat() saw in the dev container (cross-container drvfs remap). Either
    # way, the cell should be killed before burning ~1h on zero events.
    lines.append(f"  @shard_inodes_count = {len(deduped)};")
    # NO closing } here — this is a BODY fragment spliced INTO the probe's
    # BEGIN block (which owns its own braces).
    Path(args.out_bt).write_text("\n".join(lines) + "\n")
    log(f"wrote {args.out_bt} ({len(deduped)} @shard_inodes entries + count)")


if __name__ == "__main__":
    main()
