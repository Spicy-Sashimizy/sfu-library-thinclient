"""delta_ingest CLI — ingest / flush / compact / publish / status.

    .venv/bin/python3 -m spike.delta_ingest.cli ingest --source jsonl --path docs.jsonl \\
        --namespace local --profile laptop
    .venv/bin/python3 -m spike.delta_ingest.cli ingest --source openalex-snapshot --profile desktop_gpu
    .venv/bin/python3 -m spike.delta_ingest.cli flush [--force]
    .venv/bin/python3 -m spike.delta_ingest.cli compact --gens 1,2,3   |  --auto
    .venv/bin/python3 -m spike.delta_ingest.cli status
    .venv/bin/python3 -m spike.delta_ingest.cli seed-base --seed-lo 0 --seed-hi 9000000000 \
        [--seed-ids-file ids.txt] [--sidecar-root DIR ...] [--limit N]

Every subcommand that publishes (ingest, flush, compact, publish) takes
`--ordinal-dir DIR` (the base ordinal arrays for the livedocs bitset; relative
paths resolve against --index-root); without it `SFU_THINCLIENT_ORDINALS` is
the fallback, and with neither the JSON mask lists are written as before.

Serving picks the layer up with SFU_DELTA_ROOT=1 (== <index_root>/delta) and
the `reload_index` MCP tool after a flush/compact (docs/delta_ingest/02_DESIGN.md).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from spike.delta_ingest.adapters import JsonlAdapter, OpenAlexApiAdapter, OpenAlexSnapshotAdapter  # noqa: E402
from spike.delta_ingest.base import DEFAULT_INDEX_ROOT, BaseIndex  # noqa: E402
from spike.delta_ingest.buffer import BufferWriter  # noqa: E402
from spike.delta_ingest.encode import ensure_sparse, make_encoder  # noqa: E402
from spike.delta_ingest.generation import auto_compact_plan, compact, freeze_buffer, publish  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.profiles import PROFILES, apply_nice  # noqa: E402
from spike.delta_ingest.records import BASE_MIN_YEAR  # noqa: E402
from spike.delta_ingest.seed import BaseSeeder  # noqa: E402

log = logging.getLogger("delta_ingest")


def _profile(args):
    p = PROFILES[args.profile]
    return p.with_overrides(encode_backend=args.encode_backend, encode_device=args.encode_device,
                            encode_batch=args.encode_batch, ingest_batch=args.ingest_batch,
                            rate_docs_per_s=args.rate, flush_docs=args.flush_docs,
                            buffer_max_docs=args.buffer_max_docs, max_rss_gb=args.max_rss_gb,
                            seismic_threads=args.seismic_threads, parts_per_run=args.parts_per_run)


def _adapter(args, profile):
    if args.source == "jsonl":
        mapping = json.loads(args.mapping) if args.mapping else None
        return JsonlAdapter(args.path, namespace=args.namespace, mapping=mapping,
                            openalex_shape=args.openalex_shape, source=args.source_name)
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = "sfu-library-thinclient delta_ingest"
    if args.source == "openalex-snapshot":
        return OpenAlexSnapshotAdapter(session, min_year=args.min_year, max_parts=profile.parts_per_run)
    if args.source == "openalex-api":
        key = args.api_key or os.environ.get("OPENALEX_API_KEY", "")
        if not key:
            sys.exit("openalex-api needs --api-key or OPENALEX_API_KEY (keys mandatory since 2026-02-13)")
        return OpenAlexApiAdapter(session, key, filter_expr=args.filter, max_records=args.limit)
    sys.exit(f"unknown source {args.source}")


def run_ingest(args, delta_root: Path, ledger: IngestLedger, base: BaseIndex, profile) -> dict:
    """Stream adapter records through classify -> encode -> stage -> buffer,
    in `profile.ingest_batch`-sized ledger transactions, throttled by
    `profile.rate_docs_per_s`. Resumable: the adapter cursor is saved after
    every batch, so a kill costs at most one batch."""
    adapter = _adapter(args, profile)
    state = ledger.source_state(adapter.name)
    encoder = None if args.no_encode else make_encoder(profile.encode_backend, profile.encode_batch,
                                                        profile.encode_device)
    writer = BufferWriter(delta_root)
    totals = {"seen": 0, "new": 0, "updated": 0, "unchanged": 0, "deleted": 0, "encoded": 0,
              "reused": 0, "batches": 0, "started": time.time()}
    batch: list = []

    def flush_batch():
        if not batch:
            return
        if ledger.buffer_count() >= profile.buffer_max_docs:
            log.warning("buffer at cap (%d) — freezing a generation before continuing",
                        profile.buffer_max_docs)
            freeze_buffer(delta_root, ledger, base, profile, seismic=not args.no_seismic,
                          base_shard_manifest=args.base_shard_manifest, ordinal_dir=args.ordinal_dir)
        in_base = base.contains(r.id for r in batch)
        cls = ledger.classify(batch, in_base)
        todo = cls["new"] + cls["updated"]
        stats = ensure_sparse(todo, encoder, ledger.reusable_sparse(todo), profile.encode_batch)
        ledger.stage(todo, in_base)
        writer.upsert(todo)
        writer.commit()
        ledger.save_source_state(adapter.name, state)
        for k in ("new", "updated", "unchanged"):
            totals[k] += len(cls[k])
        totals["encoded"] += stats["encoded"]
        totals["reused"] += stats["reused"]
        totals["batches"] += 1
        totals["seen"] += len(batch)
        if profile.rate_docs_per_s:
            time.sleep(len(batch) / profile.rate_docs_per_s)
        batch.clear()

    try:
        for rec in adapter.iter_records(state):
            batch.append(rec)
            if len(batch) >= profile.ingest_batch:
                flush_batch()
            if args.limit and totals["seen"] + len(batch) >= args.limit:
                break
        flush_batch()
        gone = list(adapter.iter_deletions(state))
        if gone:
            in_base = base.contains(gone)
            ledger.delete(gone, in_base)
            writer.delete(gone)
            writer.commit()
            totals["deleted"] += len(gone)
        ledger.save_source_state(adapter.name, state)
    finally:
        writer.close()
    if ledger.buffer_count() >= profile.flush_docs:
        totals["auto_flush"] = freeze_buffer(delta_root, ledger, base, profile,
                                             seismic=not args.no_seismic,
                                             base_shard_manifest=args.base_shard_manifest,
                                             ordinal_dir=args.ordinal_dir)
    else:
        publish(delta_root, ledger, base, args.base_shard_manifest, args.ordinal_dir)
    totals["seconds"] = round(time.time() - totals["started"], 1)
    return totals


def run_seed(args, index_root: Path, ledger: IngestLedger) -> dict:
    """Seed base content/encode hashes into the ledger (issue O4, seed.py)."""
    seeder = BaseSeeder(index_root, ledger, sidecar_roots=args.sidecar_root or None,
                        batch=args.seed_batch)
    try:
        if args.seed_ids_file:
            ids = [ln.strip() for ln in Path(args.seed_ids_file).read_text().splitlines() if ln.strip()]
            return seeder.seed_ids(ids)
        return seeder.seed_range(args.seed_lo, args.seed_hi, limit=args.limit)
    finally:
        seeder.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ingest", "flush", "compact", "publish", "status", "seed-base"])
    ap.add_argument("--index-root", default=str(DEFAULT_INDEX_ROOT))
    ap.add_argument("--delta-root", default=None, help="default <index-root>/delta")
    ap.add_argument("--base-shard-manifest", default=None)
    ap.add_argument("--ordinal-dir", default=None,
                    help="base ordinal arrays for the livedocs bitset (default $SFU_THINCLIENT_ORDINALS)")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="desktop_gpu")
    for name in ("encode-backend", "encode-device"):
        ap.add_argument(f"--{name}", default=None)
    for name in ("encode-batch", "ingest-batch", "flush-docs", "buffer-max-docs", "seismic-threads",
                 "parts-per-run"):
        ap.add_argument(f"--{name}", type=int, default=None)
    ap.add_argument("--rate", type=float, default=None, help="docs/s throttle (0 = none)")
    ap.add_argument("--max-rss-gb", type=float, default=None)
    ap.add_argument("--source", choices=["jsonl", "openalex-snapshot", "openalex-api"], default="jsonl")
    ap.add_argument("--path"); ap.add_argument("--namespace", default="local")
    ap.add_argument("--source-name", default=None)
    ap.add_argument("--mapping", default=None, help='JSON {"src_col": "canonical_field"}')
    ap.add_argument("--openalex-shape", action="store_true", help="JSONL lines are OpenAlex work objects")
    ap.add_argument("--min-year", type=int, default=BASE_MIN_YEAR)
    ap.add_argument("--filter", default="from_created_date:2026-01-01")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-encode", action="store_true")
    ap.add_argument("--no-seismic", action="store_true", help="skip the SEISMIC shard (tantivy+meta only)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--gens", default=None); ap.add_argument("--auto", action="store_true")
    ap.add_argument("--seed-lo", type=int, default=0)
    ap.add_argument("--seed-hi", type=int, default=1 << 62)
    ap.add_argument("--seed-ids-file", default=None, help="one W-id per line (seed-base)")
    ap.add_argument("--sidecar-root", action="append", default=None,
                    help="dir holding <section>/abstracts.sqlite (seed-base; repeatable)")
    ap.add_argument("--seed-batch", type=int, default=5000)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    profile = _profile(args)
    apply_nice(profile)
    index_root = Path(args.index_root)
    delta_root = Path(args.delta_root) if args.delta_root else index_root / "delta"
    delta_root.mkdir(parents=True, exist_ok=True)
    ledger = IngestLedger(delta_root / "ledger.sqlite")
    base = BaseIndex(index_root)
    try:
        if args.cmd == "ingest":
            out = run_ingest(args, delta_root, ledger, base, profile)
        elif args.cmd == "flush":
            if not args.force and ledger.buffer_count() < profile.flush_docs:
                out = {"skipped": f"buffer {ledger.buffer_count()} < flush_docs {profile.flush_docs} (use --force)"}
            else:
                out = freeze_buffer(delta_root, ledger, base, profile, seismic=not args.no_seismic,
                                    base_shard_manifest=args.base_shard_manifest,
                                    ordinal_dir=args.ordinal_dir) or {"skipped": "empty buffer"}
                if "frozen_generation" in out:
                    w = BufferWriter(delta_root)
                    w.delete([r.id for r in ledger.records_for([out["frozen_generation"]])])
                    w.commit(); w.close()
        elif args.cmd == "compact":
            gens = auto_compact_plan(delta_root, ledger) if args.auto else [int(g) for g in (args.gens or "").split(",") if g]
            out = compact(delta_root, ledger, base, profile, gens, seismic=not args.no_seismic,
                          base_shard_manifest=args.base_shard_manifest,
                          ordinal_dir=args.ordinal_dir) if gens else {"skipped": "nothing to compact"}
        elif args.cmd == "seed-base":
            out = run_seed(args, index_root, ledger)
        elif args.cmd == "publish":
            out = publish(delta_root, ledger, base, args.base_shard_manifest, args.ordinal_dir)
        else:
            out = {"ledger": ledger.stats(), "profile": profile.as_dict(), "delta_root": str(delta_root)}
            gj = delta_root / "generations.json"
            out["published"] = json.loads(gj.read_text()) if gj.exists() else None
            if out["published"]:
                out["published"]["mask"] = {k: len(v) for k, v in out["published"]["mask"].items()}
    finally:
        ledger.close(); base.close()
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
