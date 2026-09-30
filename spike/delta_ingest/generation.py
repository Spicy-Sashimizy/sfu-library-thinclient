"""Immutable delta generations (L1) — build, publish, compact.

A generation directory is a self-contained mini index root:

    <delta_root>/g0007/
        generation.json           what is inside + how it was built
        meta.sqlite               meta rows for this generation's docs
        sections/<base>__<era>/   tantivy + abstracts.sqlite (always hot)
        seismic/delta_g0007.index.seismic          stock build
        seismic/delta_g0007.mmap/                  c1a f16 mmap layout
        seismic/delta_g0007.dotvbyte.v2.mmap/      served forward format

and the delta root publishes two atomic files the serving layer reads:

    <delta_root>/generations.json   stamp, published generations, masks
    <delta_root>/shard_manifest.json base shard records + one per generation

Nothing under a published gNNNN/ is ever modified; compaction builds a NEW
generation from the ledger's stored records and retires the old ones.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path

from lib.thinclient.builder import SectionBuilder, open_meta_db

from .base import REPO_ROOT, BaseIndex
from .ledger import IngestLedger
from .profiles import IngestProfile, rss_gb
from .records import DocRecord

log = logging.getLogger("delta_ingest.generation")

SEISMIC_PARAMS = dict(n_postings=3500, centroid_fraction=0.1, min_cluster_size=2,
                      summary_energy=0.4, max_fraction=1.5, doc_cut=15)
RELEASE = REPO_ROOT / "spike" / "seismic_upstream" / "target" / "release"
C1A_BIN = RELEASE / "c1a_mmap_index"
DOTVBYTE_BIN = RELEASE / "convert_f16_to_dotvbyte"
CARGO_ENV = {"PATH": "/usr/local/cargo/bin:" + os.environ.get("PATH", ""),
             "CARGO_HOME": "/usr/local/cargo", "RUSTUP_HOME": "/usr/local/rustup"}


def gen_name(gen: int) -> str:
    return f"g{gen:04d}"


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    os.replace(tmp, path)


def _guard_rss(profile: IngestProfile, stage: str) -> None:
    r = rss_gb()
    if profile.max_rss_gb and r > profile.max_rss_gb:
        raise MemoryError(f"RSS {r:.1f} GB > profile max {profile.max_rss_gb} GB during {stage}")


# ── SEISMIC chain ───────────────────────────────────────────────────────────
def build_seismic_shard(jsonl: Path, stem: Path, threads: int, *, want_dotvbyte: bool = True) -> dict:
    """jsonl -> stock index -> f16 mmap -> dotvbyte v2 (perdoc scale).
    Each stage records success or the reason it was skipped; the served
    `mmap_dir` is the most advanced layout that exists."""
    info: dict = {"jsonl": str(jsonl), "stock": None, "mmap_dir": None, "format": None, "stages": {}}
    try:
        import seismic
    except ImportError as exc:
        info["stages"]["build"] = f"skipped: seismic not importable ({exc})"
        return info
    t0 = time.perf_counter()
    idx = seismic.SeismicIndex.build(str(jsonl), num_threads=threads, **SEISMIC_PARAMS)
    idx.save(str(stem))
    stock = Path(f"{stem}.index.seismic")
    info["stock"] = str(stock)
    info["stages"]["build"] = {"seconds": round(time.perf_counter() - t0, 2), "docs": idx.len,
                               "dim": idx.dim, "nnz": idx.nnz}
    del idx
    if not C1A_BIN.is_file():
        info["stages"]["mmap"] = f"skipped: {C1A_BIN} not built"
        return info
    mmap_dir = Path(f"{stem}.mmap")
    t0 = time.perf_counter()
    proc = subprocess.run([str(C1A_BIN), "--index-book", str(stock), "--mmap-dir", str(mmap_dir),
                           "--n-queries", "5"], env={**os.environ, **CARGO_ENV},
                          capture_output=True, text=True, timeout=6 * 3600)
    if proc.returncode != 0 or not mmap_dir.is_dir():
        info["stages"]["mmap"] = f"failed rc={proc.returncode}: {proc.stderr[-400:]}"
        return info
    info["stages"]["mmap"] = {"seconds": round(time.perf_counter() - t0, 2)}
    info["mmap_dir"], info["format"] = str(mmap_dir), "f16"
    if not want_dotvbyte:
        return info
    if not DOTVBYTE_BIN.is_file():
        info["stages"]["dotvbyte"] = f"skipped: {DOTVBYTE_BIN} not built"
        return info
    dv_dir = Path(f"{stem}.dotvbyte.v2.mmap")
    t0 = time.perf_counter()
    proc = subprocess.run([str(DOTVBYTE_BIN), "--src-mmap-dir", str(mmap_dir), "--dst-mmap-dir",
                           str(dv_dir), "--value-scale", "perdoc", "--sanity-docs", "500"],
                          env={**os.environ, **CARGO_ENV}, capture_output=True, text=True,
                          timeout=6 * 3600)
    if proc.returncode != 0 or not dv_dir.is_dir():
        info["stages"]["dotvbyte"] = f"failed rc={proc.returncode}: {proc.stderr[-400:]}"
        return info
    info["stages"]["dotvbyte"] = {"seconds": round(time.perf_counter() - t0, 2)}
    info["mmap_dir"], info["format"] = str(dv_dir), "dotvbyte_fixedu8_v2"
    return info


# ── generation build ────────────────────────────────────────────────────────
def build_generation(delta_root: Path, gen: int, records: list[DocRecord],
                     profile: IngestProfile, *, seismic: bool = True) -> Path:
    """Write <delta_root>/gNNNN.building/ from `records`, then rename it to
    gNNNN/ (the rename is the only publish-visible step)."""
    staging = delta_root / f"{gen_name(gen)}.building"
    final = delta_root / gen_name(gen)
    if final.exists():
        raise FileExistsError(f"generation {gen} already published at {final}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    t_start = time.time()

    by_section: dict[str, list[DocRecord]] = defaultdict(list)
    for r in records:
        by_section[r.section()].append(r)
    meta = open_meta_db(staging)
    sections_info: dict[str, dict] = {}
    for name, recs in sorted(by_section.items()):
        b = SectionBuilder(staging, name, hot=True, meta_db=meta)
        for r in recs:
            b.add(r.builder_doc())
        sections_info[name] = b.finish()
        _guard_rss(profile, f"section {name}")
    meta.commit()
    meta.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    meta.close()

    seismic_info: dict = {"status": "disabled"}
    n_vec = 0
    if seismic:
        sdir = staging / "seismic"
        sdir.mkdir()
        jsonl = sdir / f"delta_{gen_name(gen)}.jsonl"
        with open(jsonl, "w") as fh:
            for r in records:
                line = r.seismic_line()
                if line:
                    fh.write(line + "\n")
                    n_vec += 1
        if n_vec:
            seismic_info = build_seismic_shard(jsonl, sdir / f"delta_{gen_name(gen)}",
                                               profile.seismic_threads)
            seismic_info["status"] = "served" if seismic_info.get("mmap_dir") else "unavailable"
            _guard_rss(profile, "seismic")
        else:
            seismic_info = {"status": "no_vectors"}
        if seismic_info.get("mmap_dir"):
            seismic_info["mmap_dir"] = str(Path(seismic_info["mmap_dir"]).relative_to(staging))

    info = {
        "generation": gen, "created": t_start, "seconds": round(time.time() - t_start, 2),
        "docs": len(records), "docs_with_vectors": n_vec,
        "sections": sections_info, "seismic": seismic_info, "profile": profile.as_dict(),
        "sources": sorted({r.source for r in records}),
    }
    atomic_write_json(staging / "generation.json", info)
    os.replace(staging, final)
    return final


# ── publish ─────────────────────────────────────────────────────────────────
def publish(delta_root: Path, ledger: IngestLedger, base: BaseIndex,
            base_shard_manifest: str | None = None, ordinal_dir: str | None = None) -> dict:
    """Rewrite generations.json + shard_manifest.json from the ledger's
    published generations. Both writes are atomic renames; a reader always
    sees a complete pair (generations.json is written LAST and carries the
    shard manifest path + stamp, so the reader keys everything off it).

    Item C (2026-09-29): when base ordinal arrays are available (`ordinal_dir`
    — the CLI's `--ordinal-dir`, threaded through `freeze_buffer`/`compact` —
    else `SFU_THINCLIENT_ORDINALS`, relative to the base index root), deletes
    and base copies superseded by a delta/buffer copy go into a livedocs
    bitset (`livedocs.py`) written BEFORE generations.json; `mask.deleted` then
    keeps only ids with no base ordinal. Without ordinals the JSON lists are
    written exactly as before."""
    gens = ledger.published_generations()
    entries = []
    delta_shards = []
    for g in gens:
        d = delta_root / gen_name(g)
        gi = json.loads((d / "generation.json").read_text())
        entries.append({"gen": g, "dir": str(d), "docs": gi["docs"],
                        "sections": sorted(gi["sections"]),
                        "seismic": gi["seismic"].get("status"),
                        "docs_with_vectors": gi.get("docs_with_vectors", 0)})
        if gi["seismic"].get("mmap_dir"):
            delta_shards.append({"shard": f"delta_{gen_name(g)}", "delta_generation": g,
                                 "mmap_dir": str(d / gi["seismic"]["mmap_dir"]),
                                 "n_docs": gi.get("docs_with_vectors", 0),
                                 "forward_format": gi["seismic"].get("format")})
    base_manifest = base.shard_manifest(base_shard_manifest)
    base_records = BaseIndex.shard_records(base_manifest)
    shard_manifest_path = None
    if delta_shards:
        records = base_records + delta_shards
        shard_manifest_path = delta_root / "shard_manifest.json"
        atomic_write_json(shard_manifest_path, {
            "plan": "delta layer: base shards + one shard per published delta generation",
            "base_shard_manifest": str(base_manifest) if base_manifest else None,
            "n_shards": len(records), "shards": records, "built_utc": time.strftime("%Y-%m-%d %H:%M"),
        })
    stamp = f"{gen_name(gens[-1]) if gens else 'g0000'}-{int(time.time())}"
    mask = ledger.mask()
    livedocs_entry = None
    ordinal_dir = ordinal_dir or os.environ.get("SFU_THINCLIENT_ORDINALS")
    if ordinal_dir:
        from .livedocs import publish_livedocs
        od = Path(ordinal_dir)
        if not od.is_absolute():
            od = base.root / od
        base_sup = [r[0] for r in ledger.db.execute(
            "SELECT id FROM docs WHERE status='live' AND in_base=1")]
        livedocs_entry, mask["deleted"] = publish_livedocs(
            delta_root, stamp, od, mask["deleted"], base_sup)
    data = {
        "format": 1, "stamp": stamp, "published": time.time(),
        "generations": entries, "mask": mask, "livedocs": livedocs_entry,
        "shard_manifest": str(shard_manifest_path) if shard_manifest_path else None,
        "base_shard_manifest": str(base_manifest) if base_manifest else None,
        "buffer": {"ledger": str(ledger.path), "tantivy_section": "delta_buffer"},
    }
    atomic_write_json(delta_root / "generations.json", data)
    return data


# ── freeze + compact ────────────────────────────────────────────────────────
def freeze_buffer(delta_root: Path, ledger: IngestLedger, base: BaseIndex, profile: IngestProfile,
                  *, seismic: bool = True, base_shard_manifest: str | None = None,
                  ordinal_dir: str | None = None) -> dict | None:
    records = [r for _, r in ledger.buffer_records()]
    if not records:
        return None
    gen = ledger.next_generation()
    ledger.open_generation(gen, records)
    try:
        build_generation(delta_root, gen, records, profile, seismic=seismic)
    except Exception:
        ledger.abort_generation(gen)
        shutil.rmtree(delta_root / f"{gen_name(gen)}.building", ignore_errors=True)
        raise
    gi = json.loads((delta_root / gen_name(gen) / "generation.json").read_text())
    ledger.finish_generation(gen, gi)
    out = publish(delta_root, ledger, base, base_shard_manifest, ordinal_dir)
    out["frozen_generation"] = gen
    out["frozen_docs"] = len(records)
    return out


def compact(delta_root: Path, ledger: IngestLedger, base: BaseIndex, profile: IngestProfile,
            gens: list[int], *, seismic: bool = True, base_shard_manifest: str | None = None,
            ordinal_dir: str | None = None) -> dict:
    """Merge published generations `gens` into one new generation (a rebuild
    from the ledger's stored records — SEISMIC has no merge; tantivy-py has no
    merge control). Old dirs are renamed *.compacted for the operator to
    delete after the new generation serves."""
    published = set(ledger.published_generations())
    bad = [g for g in gens if g not in published]
    if bad:
        raise ValueError(f"not published: {bad}")
    records = ledger.records_for(gens)
    gen = ledger.next_generation()
    ledger.open_generation(gen, records, from_gens=gens)
    try:
        build_generation(delta_root, gen, records, profile, seismic=seismic)
    except Exception:
        ledger.abort_generation(gen)
        for g in gens:
            ledger.db.execute("UPDATE records SET generation=? WHERE generation=? AND id IN "
                              "(SELECT id FROM docs WHERE generation=?)", (g, gen, gen))
        shutil.rmtree(delta_root / f"{gen_name(gen)}.building", ignore_errors=True)
        raise
    gi = json.loads((delta_root / gen_name(gen) / "generation.json").read_text())
    ledger.finish_generation(gen, gi, retire=gens)
    out = publish(delta_root, ledger, base, base_shard_manifest, ordinal_dir)
    for g in gens:
        d = delta_root / gen_name(g)
        if d.exists():
            os.replace(d, delta_root / f"{gen_name(g)}.compacted")
    out["compacted"] = gens
    out["into"] = gen
    return out


def auto_compact_plan(delta_root: Path, ledger: IngestLedger, *, tier_ratio: int = 10,
                      max_gens: int = 8) -> list[int]:
    """TieredMergePolicy-lite: when more than `max_gens` generations are live,
    merge the smallest run whose sizes are within `tier_ratio` of each other."""
    gens = ledger.published_generations()
    if len(gens) <= max_gens:
        return []
    sizes = []
    for g in gens:
        gi = json.loads((delta_root / gen_name(g) / "generation.json").read_text())
        sizes.append((gi["docs"], g))
    sizes.sort()
    run = [sizes[0]]
    for s in sizes[1:]:
        if s[0] <= run[0][0] * tier_ratio:
            run.append(s)
        else:
            break
    return sorted(g for _, g in run) if len(run) >= 2 else []
