#!/usr/bin/env python3
"""Delta-ingest item C: livedocs tombstone bitset gates (2026-09-29).

PRE-REGISTERED BARS (written 2026-09-29 before the first run; a fail is a fail):

  G1 bit-identity: with an EMPTY livedocs bitset (popcount 0, real 150,413,098-bit
     file over the served ordinal space, per-shard filter INSTALLED on the served
     federated SEISMIC backend), fused top-50 (== search_rrf) and final top-10
     (lib.tools._maybe_rerank) serialised with json.dumps(sort_keys=True) are
     byte-identical to the feature-off arm (retriever._delta = None, no hook) on
     all 120 topics: 120/120 fused AND 120/120 final.
  G2 synthetic-delete parity: per topic, bitset = a seeded 0.1% random sample of
     base ordinals (seed 20260929, 150,413 ordinals, fixed across topics) + that
     topic's top-1 fused id + top-1 BM25F id + top-1 SPLADE id (from the
     feature-off arm of the same topic). PASS iff (a) no tombstoned id appears in
     the BM25F leg, the SPLADE leg or the fused list of any topic (0 topics;
     final top-10 is a rerank of the fused list, so the fused check covers it and
     the synthetic arm skips the rerank), and (b) in each leg, the surviving ids
     keep their relative order: off-arm leg minus tombstoned ids, restricted to
     ids present in the masked leg, equals the masked leg restricted to ids
     present in the off arm (all topics, per leg). Fused relative order is
     REPORTED, not gated: RRF scores depend on leg ranks, which shift
     legitimately when a doc above is removed.
  R1 (report only) over-fetch: per-shard k' is unchanged by the post-filter.
     Per query and shard: candidates dropped; a shard is "uncertified at depth
     N" when it lost >=1 candidate and every survivor of that shard lies inside
     the merged top-N (its (k'+1)-th candidate might have entered). Reported:
     queries fully certified at N=50/N=10, max dropped per shard (= extra k'
     needed to restore the unmasked candidate depth).
  R2 (report only) latency: warm SEISMIC traverse (backend.search_encoded,
     top_k=50, pre-encoded qvec) p50/p95 with no hook vs empty-bitset hook vs
     synthetic-bitset hook, interleaved per topic, 2 reps on up to 60 topics;
     plus the filter function's own cost and the BM25F filter_hits cost.

Arms run in ONE process on the served index (in-process swap of
retriever._delta and backend._shard_result_filter), interleaved PER TOPIC in the
order off1 -> empty -> synth -> off2 after a 10-topic warm pass, so the cold
cost of a topic is paid by off1 and off2 is the within-topic determinism
control. (Revised 2026-09-29 before the first run from arm-major order, because
the shared lock was contended and a per-topic loop can stop at --stop-at and
still report every completed topic; bars unchanged except G2's seed set, which
became per-topic.)
Remote abstracts are stubbed to {} in every arm.

Ordinal arrays: a byte copy of spike/meta_consolidation/work_ordinals_full
(space 7012d0ed-...) on local disk under /var/tmp/sfu_delta_C_20260929/ords,
because the repo copy sits on 9p, where a cold W-id -> ordinal binary search
measured ~0.7 s per 100 ids (2026-09-29 probe) vs ~2-50 ms per 800 ids local.

Run (the whole run holds the shared latency lock):
  flock /tmp/sfu_latency_measure.lock env -u SFU_DELTA_ROOT -u SFU_SEISMIC_SHARD_MANIFEST \
    -u SFU_SEARCH_SPECULATIVE_RERANK .venv/bin/python3 \
    scripts/experiments/eval_delta_ingest_livedocs_bitset.py

ADDITION 2026-10-01 (flags only, bars and per-topic method unchanged; written
before the remainder run): --topic-offset N measures topics [N:] of the same
120-topic list (the 2026-09-29 run stopped after 101, so the remainder is
--topic-offset 101); the 10-topic warm pass stays on topics [:10] as before.
--out / --date write a new dated results file instead of the 2026-09-29 one
(the default path is unchanged). --health asserts, before the first measured
topic, that the SPLADE encoder returns terms, the cross-encoder and the
embedding model load and no O12/fallback signature was logged; warnings
logged during the run are scanned afterwards (result fields `health`,
`warning_signatures_during_run`). Partial rows go to <out>.rows_partial.json.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
ORDINALS_SRC = REPO / "spike/meta_consolidation/work_ordinals_full"
ORDINALS = Path("/var/tmp/sfu_delta_C_20260929/ords")
SCRATCH = Path("/var/tmp/sfu_delta_C_20260929")
OUT = Path(os.environ.get("SFU_DELTA_C_OUT") or REPO / "data/eval_results/delta_ingest_livedocs_20260929.json")
TOP_K = 50
LIMIT = 10
SEED = 20260929


def dump(o) -> str:
    return json.dumps(o, sort_keys=True, default=str)


def make_root(name: str, deleted: list[str], extra_ords: np.ndarray | None = None) -> Path:
    from lib.thinclient.livedocs import payload_len
    from spike.delta_ingest.livedocs import build_bits, open_ordinals, resolve, write_livedocs
    root = SCRATCH / name
    root.mkdir(parents=True, exist_ok=True)
    ords = open_ordinals(ORDINALS)
    got, missing = resolve(ords, deleted)
    allo = np.concatenate([got, extra_ords]) if extra_ords is not None else got
    bits = build_bits(ords.rows, allo) if len(allo) else np.zeros(payload_len(ords.rows), np.uint8)
    rel = f"livedocs/base-{name}.liv"
    facts = write_livedocs(root / rel, bits, ords.rows, ords.space_id)
    entry = {"format": 1, "path": rel, "ordinal_dir": str(ORDINALS.resolve()),
             "ordinal_space_id": ords.space_id, **facts}
    (root / "generations.json").write_text(json.dumps(
        {"format": 1, "stamp": f"itemC-{name}", "generations": [],
         "mask": {"deleted": missing, "superseded": {}}, "livedocs": entry,
         "shard_manifest": None}))
    return root


def run_arm(retriever, tools, items, rerank: bool) -> list[dict]:
    rows = []
    for key, q in items:
        legs, lat = retriever._rrf_legs(q, TOP_K, None, False)
        fused = retriever._rrf_fuse(legs, TOP_K, False)
        final = tools._maybe_rerank(copy.deepcopy(fused), q, LIMIT) if (rerank and fused) else None
        rows.append({"topic": key, "fused": dump(fused), "final": dump(final) if final is not None else None,
                     "fused_ids": [d["openalex_id"] for d in fused],
                     "final_ids": [d["openalex_id"] for d in final] if final else None,
                     "legs": {n: [d["openalex_id"] for d in v] for n, v in legs.items()},
                     "leg_ms": lat})
    return rows


def set_arm(retriever, backend, root: Path | None):
    from lib.thinclient.delta_layer import DeltaLayer
    if retriever._delta is not None:
        retriever._delta.close()
    backend._shard_result_filter = None
    retriever._delta = None
    if root is not None:
        retriever._delta = DeltaLayer(root)
        assert retriever._delta.attach_seismic(backend, None)


def order_ok(off: list[str], masked: list[str], dead: set[str]) -> bool:
    a = [d for d in off if d not in dead]
    sm, sa = set(masked), set(a)
    return [d for d in a if d in sm] == [d for d in masked if d in sa]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-topics", type=int, default=0)
    ap.add_argument("--lat-reps", type=int, default=2)
    ap.add_argument("--stop-at", default="2026-09-29T06:50:00Z",
                    help="UTC time after which no new topic starts (hard deadline of the run)")
    ap.add_argument("--topic-offset", type=int, default=0,
                    help="measure topics [offset:] of the 120 (warm pass stays on topics [:10])")
    ap.add_argument("--out", default="", help="results path (default: the 2026-09-29 file)")
    ap.add_argument("--date", default="2026-09-29")
    ap.add_argument("--health", action="store_true", help="assert models loaded before measuring")
    args = ap.parse_args()
    global OUT
    if args.out:
        OUT = Path(args.out)
    from datetime import datetime, timezone
    stop_at = datetime.fromisoformat(args.stop_at.replace("Z", "+00:00")).timestamp()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    import logging

    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.WARNING)
            self.records: list[str] = []

        def emit(self, record):
            try:
                self.records.append(f"{record.name}: {record.getMessage()}"[:400])
            except Exception:
                pass
    cap = _Cap()
    logging.getLogger().addHandler(cap)
    sigs = ("Cannot allocate memory", "CrossEncoder unavailable", "Failed to load embedding model",
            "falling back to BM25F", "SPLADE encoder failed", "SEISMIC SPLADE leg failed", "MemoryError",
            "Traceback")
    import lib.tools as tools
    from lib.thinclient.livedocs import payload_len
    from spike.delta_ingest.livedocs import build_bits, open_ordinals, write_livedocs
    if logging.getLogger("sfu_library_mcp").propagate is False:
        logging.getLogger("sfu_library_mcp").addHandler(cap)
    retriever = tools._get_thinclient_retriever()
    retriever._fetch_remote_abstracts = lambda ids: {}
    retriever._load()
    assert retriever._delta is None, "run with SFU_DELTA_ROOT unset"
    backend = retriever._seismic_backend()
    health: dict = {"checked": bool(args.health), "ok": True, "problems": [],
                    "env": {k: os.environ.get(k) for k in ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR",
                                                           "SFU_SEISMIC_SHARD_MANIFEST", "SFU_DELTA_ROOT",
                                                           "SFU_SPLADE_MODEL_PATH", "SFU_CE_MODEL_PATH",
                                                           "SFU_EMBEDDING_MODEL_PATH", "SFU_SEISMIC_FEDERATION")},
                    "python": sys.executable}
    if args.health:
        def bad(msg):
            health["ok"] = False
            health["problems"].append(msg)
        if os.environ.get("SFU_SEISMIC_STAGE_DIR") or os.environ.get("SFU_META_STAGE_DIR"):
            bad("a stage dir is set")
        try:
            import onnxruntime
            health["onnxruntime"] = onnxruntime.__version__
        except Exception as exc:
            bad(f"onnxruntime import failed: {exc!r}")
        from lib.opensearch_retriever import encode_splade
        from lib.reranker import _get_cross_encoder
        try:
            qv = encode_splade("warm up query for sparse encoder", retriever.splade_model_path)
            health["splade_terms"] = len(qv or {})
            if not qv:
                bad("encode_splade returned empty")
        except Exception as exc:
            bad(f"encode_splade raised {exc!r}")
        try:
            ce = _get_cross_encoder()
            health["cross_encoder"] = type(ce).__name__ if ce is not None else None
            if ce is None:
                bad("cross-encoder not loaded")
        except Exception as exc:
            bad(f"cross-encoder load raised {exc!r}")
        try:
            from lib.embedding import _load_model
            em = _load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
            health["embedding_model"] = type(em).__name__ if em is not None else None
            if em is None:
                bad("embedding model not loaded")
        except Exception as exc:
            bad(f"embedding model load raised {exc!r}")
        health["backend_class"] = type(backend).__name__
        health["n_shards"] = len(getattr(backend, "shards", []) or [])
        if health["n_shards"] != 8 or any(s is None for s in backend.shards):
            bad(f"backend shards {health['n_shards']} != 8 or a shard is None")
        health["warnings_at_load"] = list(cap.records)
        if any(any(s in w for s in sigs) for w in cap.records):
            bad("failure signature in warnings during load")
        print(f"HEALTH {'OK' if health['ok'] else 'FAIL'} {json.dumps(health, default=str)}", flush=True)
        if not health["ok"]:
            return 3
    n_warn0 = len(cap.records)
    topics = json.loads(TOPICS.read_text())["topics"]
    all_items = [(k, v["natural"]) for k, v in topics.items()]
    items = all_items
    if args.limit_topics:
        items = items[:args.limit_topics]
    warm_items = all_items[:min(10, len(items))]
    if args.topic_offset:
        items = items[args.topic_offset:]
    print(f"loaded {type(backend).__name__} shards={len(backend.shards)} topics={len(items)} "
          f"t={time.time()-t_start:.0f}s", flush=True)

    ords = open_ordinals(ORDINALS)
    empty_root = make_root("empty", [])
    rng = np.random.default_rng(SEED)
    sample = rng.choice(ords.rows, size=ords.rows // 1000, replace=False).astype(np.int64)
    sample_bits = build_bits(ords.rows, sample)
    synth_root = SCRATCH / "synth"
    (synth_root / "livedocs").mkdir(parents=True, exist_ok=True)

    def write_synth(seed_ids: list[str]) -> None:
        pos, found = ords.lookup(seed_ids)
        bits = sample_bits.copy()
        for o in pos[found].tolist():
            bits[o >> 3] |= np.uint8(1 << (o & 7))
        rel = "livedocs/base-synth.liv"
        facts = write_livedocs(synth_root / rel, bits, ords.rows, ords.space_id)
        missing = [d for d, f in zip(seed_ids, found) if not f]
        (synth_root / "generations.json").write_text(json.dumps(
            {"format": 1, "stamp": "itemC-synth", "generations": [],
             "mask": {"deleted": missing, "superseded": {}},
             "livedocs": {"format": 1, "path": rel, "ordinal_dir": str(ORDINALS.resolve()),
                          "ordinal_space_id": ords.space_id, **facts},
             "shard_manifest": None}))

    shard_log: list = []

    def recording(inner):
        def _f(per_shard):
            out = inner(per_shard)
            e = [(len(a), len(b), (min(x[1] for x in b) if b else None)) for a, b in zip(per_shard, out)]
            e.append(sorted((x[1] for b in out for x in b), reverse=True))
            shard_log.append(e)
            return out
        return _f

    warm_n = len(warm_items)
    run_arm(retriever, tools, warm_items, rerank=True)
    print(f"warm {warm_n} topics done t={time.time()-t_start:.0f}s", flush=True)

    rows = []
    g2_seed_total = 0
    for ti, item in enumerate(items):
        if time.time() > stop_at:
            print(f"stop-at reached after {ti} topics", flush=True)
            break
        t0 = time.time()
        set_arm(retriever, backend, None)
        off1 = run_arm(retriever, tools, [item], rerank=True)[0]
        set_arm(retriever, backend, empty_root)
        empty = run_arm(retriever, tools, [item], rerank=True)[0]
        seed = [x for x in {*(off1["fused_ids"][:1]), *(off1["legs"].get("bm25f", [])[:1]),
                            *(off1["legs"].get("splade", [])[:1])}]
        g2_seed_total += len(seed)
        write_synth(seed)
        set_arm(retriever, backend, synth_root)
        backend._shard_result_filter = recording(backend._shard_result_filter)
        synth = run_arm(retriever, tools, [item], rerank=False)[0]
        dl = retriever._delta
        out_ids = sorted(set(synth["fused_ids"]) | set(synth["legs"].get("bm25f", [])) |
                         set(synth["legs"].get("splade", [])))
        dead_out = [d for d, x in zip(out_ids, dl.base_dead(out_ids)) if x] + \
            [d for d in out_ids if d in dl.deleted]
        off_ids = sorted(set(off1["fused_ids"]) | set(off1["legs"].get("bm25f", [])) |
                         set(off1["legs"].get("splade", [])))
        dead_off = set(d for d, x in zip(off_ids, dl.base_dead(off_ids)) if x) | (set(off_ids) & set(seed))
        set_arm(retriever, backend, None)
        off2 = run_arm(retriever, tools, [item], rerank=True)[0]
        rows.append({
            "topic": item[0],
            "g1_fused": off1["fused"] == empty["fused"], "g1_final": off1["final"] == empty["final"],
            "ctl_fused": off1["fused"] == off2["fused"], "ctl_final": off1["final"] == off2["final"],
            "g1_vs_off2_fused": empty["fused"] == off2["fused"], "g1_vs_off2_final": empty["final"] == off2["final"],
            "seed": seed, "seed_in_output": sorted(set(seed) & set(out_ids)), "dead_in_output": dead_out,
            "dead_in_off_outputs": len(dead_off),
            "order_bm25f": order_ok(off1["legs"].get("bm25f", []), synth["legs"].get("bm25f", []), dead_off),
            "order_splade": order_ok(off1["legs"].get("splade", []), synth["legs"].get("splade", []), dead_off),
            "order_fused": order_ok(off1["fused_ids"], synth["fused_ids"], dead_off),
            "leg_ms_off1": off1["leg_ms"], "leg_ms_empty": empty["leg_ms"],
        })
        print(f"[{ti+1}/{len(items)}] {time.time()-t0:.1f}s g1={rows[-1]['g1_fused']}/{rows[-1]['g1_final']} "
              f"ctl={rows[-1]['ctl_fused']}/{rows[-1]['ctl_final']} dead_out={len(dead_out)} "
              f"order={rows[-1]['order_bm25f']}/{rows[-1]['order_splade']}", flush=True)
        if (ti + 1) % 10 == 0:
            (Path(str(OUT) + ".rows_partial.json") if args.out else SCRATCH / "rows_partial.json").write_text(
                json.dumps(rows))
    set_arm(retriever, backend, None)
    done = [k for k, _ in items[:len(rows)]]

    cert = {50: 0, 10: 0}
    max_drop = drops_total = queries_with_drops = 0
    for entry in shard_log:
        merged, per = entry[-1], entry[:-1]
        dq = sum(a - b for a, b, _ in per)
        drops_total += dq
        queries_with_drops += dq > 0
        max_drop = max([max_drop] + [a - b for a, b, _ in per])
        for n in cert:
            nth = merged[n - 1] if len(merged) >= n else float("-inf")
            cert[n] += not any((a - b) > 0 and (mn is None or mn >= nth) for a, b, mn in per)

    lat = {"none": [], "empty": [], "synth": []}
    filt_cost = {}
    lat_topics = 0
    if time.time() < stop_at + 240:
        enc = [backend.encode_query(q) for _k, q in items[:len(rows)]][:60]
        lat_topics = len(enc)
        f_empty, dl_e = DeltaLayer_filter(empty_root, backend)
        f_synth, dl_s = DeltaLayer_filter(synth_root, backend)
        arms = {"none": None, "empty": f_empty, "synth": f_synth}
        for qv in enc:
            backend._shard_result_filter = None
            backend.search_encoded(qv, TOP_K)
        for _ in range(args.lat_reps):
            for qv in enc:
                for a, f in arms.items():
                    backend._shard_result_filter = f
                    t0 = time.perf_counter()
                    backend.search_encoded(qv, TOP_K)
                    lat[a].append((time.perf_counter() - t0) * 1000)
        backend._shard_result_filter = None
        from lib.thinclient.sharded_seismic_backend import _prepare_query
        for name, f, dl in (("empty", f_empty, dl_e), ("synth", f_synth, dl_s)):
            samples = []
            for qv in enc[:30]:
                qcomp, qvals, qc, kp = _prepare_query(qv, TOP_K, backend._string_dtype, None, None)
                per = [s.search(query_id="q", query_components=qcomp, query_values=qvals, k=kp,
                                query_cut=qc, heap_factor=0.8) for s in backend.shards]
                t0 = time.perf_counter()
                f(per)
                samples.append((time.perf_counter() - t0) * 1000)
            hits = [(f"W{int(w)}", 1.0, None) for w in ords.wids[::3_000_000][:50]]
            t0 = time.perf_counter()
            for _ in range(50):
                dl.filter_hits(hits)
            filt_cost[name] = {"shard_filter_ms_p50": round(statistics.median(samples), 3) if samples else None,
                               "shard_filter_ms_max": round(max(samples), 3) if samples else None,
                               "shard_candidates_per_call": sum(len(r) for r in per) if samples else None,
                               "bm25f_filter_hits_ms_per_call_50_hits": round((time.perf_counter() - t0) * 1000 / 50, 3)}
            dl.close()

    def pct(v, p):
        v = sorted(v)
        return round(v[min(len(v) - 1, int(p * len(v)))], 2) if v else None

    n = len(rows)
    cnt = lambda k: sum(1 for r in rows if r[k])  # noqa: E731
    res = {
        "item": "delta-ingest C livedocs bitset", "date": args.date, "topic_offset": args.topic_offset,
        "health": health,
        "warning_signatures_during_run": [w for w in cap.records[n_warn0:] if any(s in w for s in sigs)][:20],
        "n_warnings_during_run": len(cap.records) - n_warn0,
        "commit": (os.environ.get("SFU_EVAL_COMMIT") or (subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True, capture_output=True).stdout.strip() if (REPO / ".git").exists() else REPO.name)),
        "script": "scripts/experiments/eval_delta_ingest_livedocs_bitset.py",
        "delivered_path": "python per-shard post-filter before _merge_topk (no Rust gather-time skip)",
        "backend": type(backend).__name__, "n_shards": len(backend.shards),
        "topics_planned": len(items), "topics_done": n, "topics_done_keys": done,
        "ordinal_dir": str(ORDINALS), "ordinal_dir_source": str(ORDINALS_SRC),
        "ordinal_space_id": ords.space_id, "nbits": ords.rows,
        "G1_bit_identity_empty_bitset": {
            "fused_identical_off1_vs_empty": cnt("g1_fused"), "final_identical_off1_vs_empty": cnt("g1_final"),
            "fused_identical_off1_vs_off2_control": cnt("ctl_fused"),
            "final_identical_off1_vs_off2_control": cnt("ctl_final"),
            "fused_identical_empty_vs_off2": cnt("g1_vs_off2_fused"),
            "final_identical_empty_vs_off2": cnt("g1_vs_off2_final"), "n": n},
        "G2_synthetic_delete": {
            "design": "per topic: bitset = seeded 0.1% random ordinals + that topic's top-1 fused/BM25F/SPLADE ids",
            "random_ordinals": int(len(sample)), "seed_ids_total": g2_seed_total,
            "topics_with_seed_in_output": sum(1 for r in rows if r["seed_in_output"]),
            "topics_with_tombstoned_in_output": sum(1 for r in rows if r["dead_in_output"]),
            "tombstoned_in_output_examples": [r["dead_in_output"] for r in rows if r["dead_in_output"]][:5],
            "order_preserved_bm25f": cnt("order_bm25f"), "order_preserved_splade": cnt("order_splade"),
            "order_preserved_fused_report_only": cnt("order_fused"),
            "tombstoned_ids_in_off_outputs_total": sum(r["dead_in_off_outputs"] for r in rows), "n": n},
        "R1_overfetch": {
            "seismic_calls_logged": len(shard_log), "queries_with_drops": queries_with_drops,
            "candidates_dropped_total": drops_total, "max_dropped_one_shard": max_drop,
            "certified_exact_at_50": cert[50], "certified_exact_at_10": cert[10]},
        "R2_latency_warm_traverse_ms": {a: {"p50": pct(v, 0.5), "p95": pct(v, 0.95), "n": len(v)}
                                        for a, v in lat.items()},
        "R2_topics": lat_topics, "R2_filter_cost": filt_cost,
        "rows": rows, "wall_s": round(time.time() - t_start, 1),
    }
    g1, g2 = res["G1_bit_identity_empty_bitset"], res["G2_synthetic_delete"]
    full = n == len(items)
    res["verdicts"] = {
        "G1": ("PASS" if g1["fused_identical_off1_vs_empty"] == n and g1["final_identical_off1_vs_empty"] == n
               else "FAIL") + ("" if full else f" (PARTIAL {n}/{len(items)} topics)"),
        "G2": ("PASS" if (g2["topics_with_tombstoned_in_output"] == 0 and g2["topics_with_seed_in_output"] == 0
                          and g2["order_preserved_bm25f"] == n and g2["order_preserved_splade"] == n)
               else "FAIL") + ("" if full else f" (PARTIAL {n}/{len(items)} topics)"),
    }
    OUT.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "topics_done_keys")}, indent=1))
    return 0


def DeltaLayer_filter(root: Path, backend):
    from lib.thinclient.delta_layer import DeltaLayer
    dl = DeltaLayer(root)
    return dl.shard_result_filter(dl.shard_origins(len(backend.shards), None)), dl


if __name__ == "__main__":
    sys.exit(main())
