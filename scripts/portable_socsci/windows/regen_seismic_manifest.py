#!/usr/bin/env python3
"""Rewrite the bundle's seismic manifest to the CURRENT bundle location.

Ships INSIDE the bundle. The v1 manifest ($BUNDLE/seismic/shards.e5.v2.json)
records absolute `mmap_dir` paths, but a thumb drive gets a different absolute
path on every host (E:\, F:\, /media/... ). START.bat runs this first so the
manifest always points at wherever the drive is mounted right now.

Standard library only (the relocatable python may not have pip packages beyond
the serving wheels). Cross-platform: uses os.path, so the same file works when
the drive is loop-mounted back into this Linux container for testing.

    python regen_seismic_manifest.py <bundle_root>
    # default bundle_root = the parent of this file's dir (…/<bundle>/…)
"""
import json
import os
import sys


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    # This file ships at <bundle>/regen_seismic_manifest.py (phase 5 copies it to
    # the bundle root), so default root = its own dir. An explicit arg wins.
    root = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else here
    manifest = os.path.join(root, "seismic", "shards.e5.v2.json")
    if not os.path.isfile(manifest):
        sys.exit(f"seismic manifest not found: {manifest}")

    with open(manifest) as fh:
        man = json.load(fh)

    seismic_root = os.path.join(root, "seismic")
    changed = 0
    for rec in man.get("shards", []):
        base = os.path.basename(rec.get("mmap_dir", "").rstrip("/\\"))
        if not base:
            continue
        new_dir = os.path.join(seismic_root, base)
        if rec.get("mmap_dir") != new_dir:
            changed += 1
        rec["mmap_dir"] = new_dir
        rec["index_path"] = new_dir
    man["seismic_root"] = seismic_root
    man["relocated_to"] = root

    with open(manifest, "w") as fh:
        json.dump(man, fh, indent=2)
    print(f"seismic manifest repointed at {seismic_root} "
          f"({changed}/{len(man.get('shards', []))} shard paths updated)")


if __name__ == "__main__":
    main()
