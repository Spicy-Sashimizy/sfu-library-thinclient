"""delta_ingest CLI — ingest / flush / compact / publish / status.

    .venv/bin/python3 -m spike.delta_ingest.cli ingest --source jsonl --path docs.jsonl \\
        --namespace local --profile laptop
    .venv/bin/python3 -m spike.delta_ingest.cli ingest --source openalex-snapshot --profile desktop_gpu
    .venv/bin/python3 -m spike.delta_ingest.cli flush [--force]
    .venv/bin/python3 -m spike.delta_ingest.cli compact --gens 1,2,3   |  --auto
    .venv/bin/python3 -m spike.delta_ingest.cli status
    .venv/bin/python3 -m spike.delta_ingest.cli seed-base --seed-lo 0 --seed-hi 9000000000 \
        [--seed-ids-file ids.txt] [--sidecar-root DIR ...] [--limit N]
    .venv/bin/python3 -m spike.delta_ingest.cli build-base-locators --delta-root D \
        --base-forward-dir <f16 shard twin> [...] --base-locator-dir <local dir>
    .venv/bin/python3 -m spike.delta_ingest.cli backfill-routes --delta-root D
    .venv/bin/python3 -m spike.delta_ingest.cli fold-build --delta-root D --shard s \
        --fold-input <f16 c1a dir of s as served> --token-map-dir <dir with token_to_id_map.bin> \
        [--fold-root DIR] [--fold-workers N] [--keep-scratch]
    .venv/bin/python3 -m spike.delta_ingest.cli publish-fold --delta-root D --shard s --fold k [--confirm]

Fold-in (doc 10 G2-G4, foldin.py): `backfill-routes` adds `route_shard` /
`seismic_origin` to a ledger written by older code (in place: run it on the
ledger you mean to migrate). `fold-build` writes only under --fold-root
(guarded) and records the fold `built`; `publish-fold` is the operator step
(dry run without --confirm) that repoints serving at a READY fold through a
new composed manifest, with the size+mtime baseline checked before and after.

O14 base-vector reuse: `ingest ... --base-forward-dir <twin> [...] --base-locator-dir
<dir>` copies the exact base f16 vector of a seeded, text-unchanged base doc
instead of encoding it (exact-or-refuse rules R1-R5 in base_vectors.py).
O7: remote snapshot partitions are spooled compressed to `--spool-dir` and
streamed line by line.

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

from lib.thinclient.delta_layer import resolve_delta_root  # noqa: E402
from spike.delta_ingest.adapters import JsonlAdapter, OpenAlexApiAdapter, OpenAlexSnapshotAdapter  # noqa: E402
from spike.delta_ingest.base import DEFAULT_INDEX_ROOT, BaseIndex  # noqa: E402
from spike.delta_ingest.base_vectors import BaseVectorStore, build_locator, reusable_base_sparse  # noqa: E402
from spike.delta_ingest.buffer import BufferWriter  # noqa: E402
from spike.delta_ingest.encode import ensure_sparse, make_encoder  # noqa: E402
from spike.delta_ingest.generation import (COMPACT_POLICIES, auto_compact_plan, compact,  # noqa: E402
                                           freeze_buffer, publish)
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.profiles import PROFILES, apply_nice  # noqa: E402
from spike.delta_ingest.records import BASE_MIN_YEAR, LAYOUTS  # noqa: E402
from spike.delta_ingest.seed import BaseSeeder  # noqa: E402

log = logging.getLogger("delta_ingest")


def _profile(args):
    p = PROFILES[args.profile]
    return p.with_overrides(encode_backend=args.encode_backend, encode_device=args.encode_device,
                            encode_batch=args.encode_batch, ingest_batch=args.ingest_batch,
                            rate_docs_per_s=args.rate, flush_docs=args.flush_docs,
                            buffer_max_docs=args.buffer_max_docs, max_rss_gb=args.max_rss_gb,
                            seismic_threads=args.seismic_threads, parts_per_run=args.parts_per_run,
                            layout=args.layout, compact_policy=args.compact_policy,
                            max_live_gens=args.max_live_gens)


def _auto_compact(delta_root: Path, ledger: IngestLedger, base: BaseIndex, profile, args) -> dict | None:
    """09 L1: under `compact_policy=compact_all`, a flush that leaves more
    than `max_live_gens` live generations is followed by a compaction of all
    of them. The default `tiered` policy never compacts on flush."""
    if profile.compact_policy != "compact_all":
        return None
    gens = auto_compact_plan(delta_root, ledger, max_gens=profile.max_live_gens,
                             policy=profile.compact_policy)
    if not gens:
        return None
    return compact(delta_root, ledger, base, profile, gens, seismic=not args.no_seismic,
                   base_shard_manifest=args.base_shard_manifest, ordinal_dir=args.ordinal_dir)


def _adapter(args, profile):
    if args.source == "jsonl":
        mapping = json.loads(args.mapping) if args.mapping else None
        return JsonlAdapter(args.path, namespace=args.namespace, mapping=mapping,
                            openalex_shape=args.openalex_shape, source=args.source_name)
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = "sfu-library-thinclient delta_ingest"
    if args.source == "openalex-snapshot":
        return OpenAlexSnapshotAdapter(session, min_year=args.min_year, max_parts=profile.parts_per_run,
                                       spool_dir=args.spool_dir)
    if args.source == "openalex-api":
        key = args.api_key or os.environ.get("OPENALEX_API_KEY", "")
        if not key:
            sys.exit("openalex-api needs --api-key or OPENALEX_API_KEY (keys mandatory since 2026-02-13)")
        return OpenAlexApiAdapter(session, key, filter_expr=args.filter, max_records=args.limit)
    sys.exit(f"unknown source {args.source}")


def _buffer_keep_after_freeze(ledger: IngestLedger, frozen: dict | None) -> set[str] | None:
    if not frozen or "frozen_generation" not in frozen:
        return None
    keep = {r.id for _, r in ledger.buffer_records()}
    keep.update(r.id for r in ledger.records_for([frozen["frozen_generation"]]))
    return keep


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
    base_store = None
    if args.base_forward_dir:
        if not args.base_locator_dir:
            sys.exit("--base-forward-dir needs --base-locator-dir (build locators with base_vectors.build_locator)")
        base_store = BaseVectorStore(args.base_forward_dir, args.base_locator_dir)
    totals = {"seen": 0, "new": 0, "updated": 0, "unchanged": 0, "deleted": 0, "encoded": 0,
              "reused": 0, "reused_base": 0, "base_refusals": {}, "batches": 0, "started": time.time()}
    batch: list = []

    def flush_batch():
        if not batch:
            return
        if ledger.buffer_count() >= profile.buffer_max_docs:
            log.warning("buffer at cap (%d) — freezing a generation before continuing",
                        profile.buffer_max_docs)
            frozen = freeze_buffer(delta_root, ledger, base, profile, seismic=not args.no_seismic,
                                   base_shard_manifest=args.base_shard_manifest,
                                   ordinal_dir=args.ordinal_dir)
            keep = _buffer_keep_after_freeze(ledger, frozen)
            if keep is not None:
                writer.retain_only(keep)
        in_base = base.contains(r.id for r in batch)
        cls = ledger.classify(batch, in_base)
        todo = cls["new"] + cls["updated"]
        reusable = ledger.reusable_sparse(todo)
        if base_store is not None:
            from_base, refusals = reusable_base_sparse(
                ledger, [r for r in todo if in_base.get(r.id) and r.id not in reusable and not r.sparse_field],
                base_store)
            reusable.update(from_base)
            totals["reused_base"] += len(from_base)
            for k, v in refusals.items():
                totals["base_refusals"][k] = totals["base_refusals"].get(k, 0) + v
        stats = ensure_sparse(todo, encoder, reusable, profile.encode_batch)
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
        keep = _buffer_keep_after_freeze(ledger, totals["auto_flush"])
        if keep is not None:
            w = BufferWriter(delta_root)
            try:
                w.retain_only(keep)
            finally:
                w.close()
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
    ap.add_argument("cmd", choices=["ingest", "flush", "compact", "publish", "status", "seed-base",
                                    "build-base-locators", "backfill-routes", "fold-build",
                                    "publish-fold"])
    ap.add_argument("--index-root", default=str(DEFAULT_INDEX_ROOT))
    ap.add_argument("--delta-root", default=None,
                    help="explicit path, or 1 (= <index-root>/delta); else SFU_DELTA_ROOT, else "
                         "<index-root>/delta — an implicit root under the repo data/ tree and any root "
                         "inside data/seismic_150m are refused (O16, resolve_delta_root)")
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
    ap.add_argument("--layout", choices=list(LAYOUTS), default=None,
                    help="delta generation section layout (09 L2; default: the profile's, per_base_section)")
    ap.add_argument("--compact-policy", choices=list(COMPACT_POLICIES), default=None,
                    help="auto-compaction plan (09 L1; default: the profile's, tiered)")
    ap.add_argument("--max-live-gens", type=int, default=None,
                    help="G_max: live-generation cap of the auto-compaction plan (default: the profile's, 8)")
    ap.add_argument("--max-rss-gb", type=float, default=None)
    ap.add_argument("--source", choices=["jsonl", "openalex-snapshot", "openalex-api"], default="jsonl")
    ap.add_argument("--path"); ap.add_argument("--namespace", default="local")
    ap.add_argument("--source-name", default=None)
    ap.add_argument("--mapping", default=None, help='JSON {"src_col": "canonical_field"}')
    ap.add_argument("--openalex-shape", action="store_true", help="JSONL lines are OpenAlex work objects")
    ap.add_argument("--min-year", type=int, default=BASE_MIN_YEAR)
    ap.add_argument("--spool-dir", default=None,
                    help="local dir for the compressed spool of a remote partition (O7; default system temp)")
    ap.add_argument("--filter", default="from_created_date:2026-01-01")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-encode", action="store_true")
    ap.add_argument("--base-forward-dir", action="append", default=None,
                    help="O14: base f16 shard twin dir (repeat per shard); enables exact base-vector reuse")
    ap.add_argument("--base-locator-dir", default=None,
                    help="O14: dir holding <shard>.locator.npz built by base_vectors.build_locator")
    ap.add_argument("--no-seismic", action="store_true", help="skip the SEISMIC shard (tantivy+meta only)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--gens", default=None); ap.add_argument("--auto", action="store_true")
    ap.add_argument("--seed-lo", type=int, default=0)
    ap.add_argument("--seed-hi", type=int, default=1 << 62)
    ap.add_argument("--seed-ids-file", default=None, help="one W-id per line (seed-base)")
    ap.add_argument("--sidecar-root", action="append", default=None,
                    help="dir holding <section>/abstracts.sqlite (seed-base; repeatable)")
    ap.add_argument("--seed-batch", type=int, default=5000)
    ap.add_argument("--shard", type=int, default=None, help="fold-build / publish-fold: base shard")
    ap.add_argument("--fold", type=int, default=None, help="publish-fold: fold number")
    ap.add_argument("--confirm", action="store_true", help="publish-fold: actually publish (operator step)")
    ap.add_argument("--no-prefault", action="store_true",
                    help="publish-fold: skip the page-cache prefault of the fold's served dir (doc 10 §4)")
    ap.add_argument("--fold-root", default=None, help="fold side root (default foldin.FOLD_ROOT_DEFAULT)")
    ap.add_argument("--fold-input", default=None, help="fold-build: f16 c1a dir of the shard as served")
    ap.add_argument("--token-map-dir", default=None,
                    help="fold-build: dir whose token_to_id_map.bin is pinned (required)")
    ap.add_argument("--fold-workers", type=int, default=4)
    ap.add_argument("--keep-scratch", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    profile = _profile(args)
    apply_nice(profile)
    index_root = Path(args.index_root)
    try:
        delta_root = resolve_delta_root(index_root, args.delta_root, for_write=True)
    except ValueError as exc:
        sys.exit(f"delta_ingest: {exc}")
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
                    try:
                        w.retain_only(_buffer_keep_after_freeze(ledger, out))
                    finally:
                        w.close()
                    out["auto_compact"] = _auto_compact(delta_root, ledger, base, profile, args)
        elif args.cmd == "compact":
            gens = auto_compact_plan(delta_root, ledger, max_gens=profile.max_live_gens,
                                     policy=profile.compact_policy) if args.auto else [int(g) for g in (args.gens or "").split(",") if g]
            out = compact(delta_root, ledger, base, profile, gens, seismic=not args.no_seismic,
                          base_shard_manifest=args.base_shard_manifest,
                          ordinal_dir=args.ordinal_dir) if gens else {"skipped": "nothing to compact"}
        elif args.cmd == "seed-base":
            out = run_seed(args, index_root, ledger)
        elif args.cmd == "build-base-locators":
            if not (args.base_forward_dir and args.base_locator_dir):
                sys.exit("build-base-locators needs --base-forward-dir (repeat) and --base-locator-dir")
            out = [build_locator(d, Path(args.base_locator_dir) / f"{Path(d).name}.locator")
                   for d in args.base_forward_dir]
        elif args.cmd == "publish":
            out = publish(delta_root, ledger, base, args.base_shard_manifest, args.ordinal_dir)
        elif args.cmd == "backfill-routes":
            out = ledger.backfill_routes()
        elif args.cmd in ("fold-build", "publish-fold"):
            from spike.delta_ingest import foldin
            cfg = foldin.GuardConfig(fold_root=Path(args.fold_root or foldin.FOLD_ROOT_DEFAULT))
            if args.shard is None:
                sys.exit(f"{args.cmd} needs --shard")
            if args.cmd == "fold-build":
                if not (args.fold_input and args.token_map_dir):
                    sys.exit("fold-build needs --fold-input and --token-map-dir (the token-id map is always pinned)")
                out = foldin.build_fold(delta_root, ledger, args.shard, Path(args.fold_input),
                                        token_map_dir=Path(args.token_map_dir), cfg=cfg,
                                        threads=profile.seismic_threads, workers=args.fold_workers,
                                        keep_scratch=args.keep_scratch)
            else:
                if args.fold is None:
                    sys.exit("publish-fold needs --fold")
                out = foldin.publish_fold(delta_root, ledger, base, args.shard, args.fold,
                                          confirm=args.confirm, cfg=cfg,
                                          base_shard_manifest=args.base_shard_manifest,
                                          ordinal_dir=args.ordinal_dir,
                                          prefault=not args.no_prefault)
        else:
            out = {"ledger": ledger.stats(), "profile": profile.as_dict(), "delta_root": str(delta_root)}
            gj = delta_root / "generations.json"
            out["published"] = json.loads(gj.read_text()) if gj.exists() else None
            if out["published"]:
                out["published"]["mask"] = {k: len(v) for k, v in out["published"]["mask"].items()}
    finally:
        ledger.close(); base.close()
    print(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    main()
