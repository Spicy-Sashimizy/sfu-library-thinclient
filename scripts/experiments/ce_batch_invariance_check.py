#!/usr/bin/env python3
"""Does the serving cross-encoder / stage-1 embedder give bit-identical scores
for the same (query, text) pair regardless of batch composition?

Decides §5 risk 1 of docs/SPECULATIVE_RETRIEVAL_UPGRADES.md: if scores are
batch-invariant, per-candidate reuse of drafted scores is byte-safe as-is; if
not, per-candidate reuse needs fixed-shape batching on BOTH paths (a one-time
float-level change to gate-off scores) or reuse stays whole-batch only.

Modes:
  --mode legacy   the pre-2026-09-25 calls (``CrossEncoder.predict`` and
                  ``SentenceTransformer.encode`` padding to the batch's longest).
  --mode fixed    the serve path's fixed-shape scoring
                  (``reranker._ce_score_pairs``, ``embedding.compute_similarity``).

Arms per model: (A) each pair scored alone; (B) all 20 in one call; (C) a call
of 20 where 10 texts are replaced by others (the 10 shared pairs are
compared); (D) as B, reversed; (E) the last 7 pairs alone as a "remainder"
call (per-candidate reuse shape); (F) the 20 pairs shuffled. Reports
bit-equality, max |Δ|, and whether the ranking of the shared pairs changes.

--threads N pins torch intra-op threads; --dump writes every raw score as a
float hex so runs at different thread counts / devices can be compared with
--compare A.json B.json. --bench adds a latency table at the serve shape (20
pairs CE, 1 query + 20 docs embedder) for legacy vs fixed at several
(seq_len, batch) settings; --pairs-file uses real (query, text) pairs captured
from the serve path (JSONL {"q":..., "t":...}) instead of synthetic text.
Touches no index. Device: whatever torch picks (set CUDA_VISIBLE_DEVICES= for
CPU); recorded in the output.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))

QUERY = "lifestyle interventions delivered in primary care that prevent type 2 diabetes"
WORDS = ("diabetes prevention primary care lifestyle intervention randomized trial cohort "
         "metformin glucose insulin obesity exercise diet weight loss adherence nurse "
         "screening risk score community pharmacist telehealth outcomes follow-up").split()


def make_texts(rng, n, lo, hi):
    return [" ".join(rng.choice(WORDS) for _ in range(rng.randint(lo, hi))) for _ in range(n)]


def compare(name, ref, got, shared_idx):
    a = np.asarray([ref[i] for i in shared_idx], dtype=np.float64)
    b = np.asarray([got[i] for i in shared_idx], dtype=np.float64)
    return {"arm": name, "bit_identical": bool(np.array_equal(a, b)),
            "max_abs_diff": float(np.max(np.abs(a - b))),
            "ranking_changed": bool((np.argsort(-a, kind="stable") != np.argsort(-b, kind="stable")).any())}


def scorers(mode):
    from lib import reranker, embedding
    ce = reranker._get_cross_encoder()
    if mode == "legacy":
        def ce_fn(q, texts):
            return [float(x) for x in ce.predict([(q, t) for t in texts], show_progress_bar=False).tolist()]

        def emb_fn(q, texts):
            m = embedding._load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
            e = np.asarray(m.encode([q] + texts, normalize_embeddings=True, show_progress_bar=False))
            return [max(0.0, float(s)) for s in (e[1:] @ e[0]).tolist()]
    else:
        def ce_fn(q, texts):
            return reranker._ce_score_pairs(ce, [(q, t) for t in texts])

        def emb_fn(q, texts):
            return embedding.compute_similarity(q, texts, os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
    return ce, ce_fn, emb_fn


def arms(fn, texts, others, rng):
    alone = [fn(QUERY, [t])[0] for t in texts]
    full = fn(QUERY, texts)
    mixed = fn(QUERY, texts[:10] + others)
    rev = fn(QUERY, list(reversed(texts)))[::-1]
    rem = fn(QUERY, texts[13:])
    perm = list(range(len(texts)))
    rng.shuffle(perm)
    shuf_scores = fn(QUERY, [texts[i] for i in perm])
    shuf = [0.0] * len(texts)
    for pos, i in enumerate(perm):
        shuf[i] = shuf_scores[pos]
    rem_full = [None] * 13 + rem
    raw = {"alone": alone, "full": full, "mixed": mixed, "reversed": rev, "remainder": rem,
           "shuffled": shuf}
    res = [
        compare("B_full_batch_vs_alone", alone, full, range(20)),
        compare("C_mixed_batch_vs_alone", alone, mixed, range(10)),
        compare("D_reversed_batch_vs_alone", alone, rev, range(20)),
        compare("C_mixed_vs_B_full", full, mixed, range(10)),
        compare("E_remainder7_vs_B_full", full, rem_full, range(13, 20)),
        compare("F_shuffled_vs_B_full", full, shuf, range(20)),
    ]
    return res, raw


def timeit(fn, reps):
    for _ in range(3):
        fn()
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": round(statistics.median(ts), 2), "p95_ms": round(sorted(ts)[int(0.95 * (len(ts) - 1))], 2),
            "n": reps}


def bench(pairs_sets, reps):
    """Latency at the serve shape for legacy vs fixed-shape settings."""
    import torch
    from lib import reranker, embedding
    ce = reranker._get_cross_encoder()
    emb_model = embedding._load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
    sync = (lambda: torch.cuda.synchronize()) if torch.cuda.is_available() and str(emb_model.device).startswith("cuda") else (lambda: None)
    out = {"ce": {}, "embed": {}}
    orig = (reranker._CE_SEQ_LEN, reranker._CE_BATCH, embedding._FIXED_SEQ_LEN, embedding._EMBED_BATCH)

    def run_sets(f):
        def g():
            for q, texts in pairs_sets:
                f(q, texts)
            sync()
        return g

    def per_call(res):
        return {k: (round(v / len(pairs_sets), 2) if k.endswith("_ms") else v) for k, v in res.items()}

    try:
        for label, n_take in (("serve20", 20), ("remainder10", 10)):
            sets = [(q, t[:n_take]) for q, t in pairs_sets]

            def run(f, sets=sets):
                def g():
                    for q, texts in sets:
                        f(q, texts)
                    sync()
                return g
            out["ce"][f"{label}/legacy_longest"] = per_call(timeit(run(
                lambda q, ts: ce.predict([(q, t) for t in ts], show_progress_bar=False)), reps))
            out["embed"][f"{label}/legacy_longest"] = per_call(timeit(run(
                lambda q, ts: emb_model.encode([q] + ts, normalize_embeddings=True, show_progress_bar=False)), reps))
            for L in (256, 128):
                for B in (20, 10, 5, 4):
                    reranker._CE_SEQ_LEN, reranker._CE_BATCH = L, B
                    out["ce"][f"{label}/fixed_L{L}_B{B}"] = per_call(timeit(run(
                        lambda q, ts: reranker._ce_score_pairs(ce, [(q, t) for t in ts])), reps))
                for B in (32, 16, 11, 8, 7):
                    embedding._FIXED_SEQ_LEN, embedding._EMBED_BATCH = L, B
                    out["embed"][f"{label}/fixed_L{L}_B{B}"] = per_call(timeit(run(
                        lambda q, ts: embedding.compute_similarity(q, ts)), reps))
                reranker._CE_SEQ_LEN, reranker._CE_BATCH, embedding._FIXED_SEQ_LEN, embedding._EMBED_BATCH = orig
    finally:
        reranker._CE_SEQ_LEN, reranker._CE_BATCH, embedding._FIXED_SEQ_LEN, embedding._EMBED_BATCH = orig
    return out


def truncation_stats(pairs_sets):
    from lib import reranker, embedding
    ce = reranker._get_cross_encoder()
    m = embedding._load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
    ce_lens, emb_lens = [], []
    for q, texts in pairs_sets:
        for t in texts:
            ce_lens.append(len(ce.tokenizer(q, t, truncation=False)["input_ids"]))
            emb_lens.append(len(m.tokenizer(t, truncation=False)["input_ids"]))
    def frac(xs, L):
        return round(sum(1 for x in xs if x > L) / len(xs), 4)
    return {"n_pairs": len(ce_lens),
            "ce_tokens_p50": int(np.median(ce_lens)), "ce_tokens_p95": int(np.percentile(ce_lens, 95)),
            "ce_frac_over_256": frac(ce_lens, 256), "ce_frac_over_128": frac(ce_lens, 128),
            "embed_tokens_p50": int(np.median(emb_lens)), "embed_frac_over_256": frac(emb_lens, 256),
            "embed_frac_over_128": frac(emb_lens, 128),
            "ce_model_max_length": getattr(ce, "max_length", None),
            "embed_model_max_seq_length": getattr(m, "max_seq_length", None)}


def tokenization_parity(pairs_sets):
    """Fixed-shape tokenization must equal the library's own tokenization once pads are stripped."""
    from lib import reranker, embedding
    ce = reranker._get_cross_encoder()
    m = embedding._load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
    ce_bad = emb_bad = n = 0
    for q, texts in pairs_sets:
        pairs = [(q, t) for t in texts]
        if hasattr(ce, "preprocess"):
            lib_ids = ce.preprocess(pairs)["input_ids"].tolist()
            fixed = ce.tokenizer([p[0] for p in pairs], [p[1] for p in pairs], padding="max_length",
                                 truncation="longest_first", max_length=reranker._ce_seq_len(ce))["input_ids"]
            for a, b in zip(lib_ids, fixed):
                n += 1
                ce_bad += [x for x in a if x != 0] != [x for x in b if x != 0]
        if hasattr(m, "preprocess"):
            lib_ids = m.preprocess([q] + texts)["input_ids"].tolist()
            fixed = m.tokenizer([q] + texts, padding="max_length", truncation="longest_first",
                                max_length=embedding._seq_len(m))["input_ids"]
            for a, b in zip(lib_ids, fixed):
                emb_bad += [x for x in a if x != 0] != [x for x in b if x != 0]
    return {"pairs_checked": n, "ce_token_mismatch": ce_bad, "embed_token_mismatch": emb_bad}


def load_pairs(path, n_sets):
    by_q = {}
    for line in Path(path).read_text().splitlines():
        r = json.loads(line)
        by_q.setdefault(r["q"], [])
        if r["t"] not in by_q[r["q"]]:
            by_q[r["q"]].append(r["t"])
    return [(q, ts[:20]) for q, ts in by_q.items() if len(ts) >= 20][:n_sets]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("legacy", "fixed"), default="fixed")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--texts", choices=("short", "long"), default="long",
                    help="synthetic text length: short 8-60 words (the 2026-09-25 legacy run), long 20-300")
    ap.add_argument("--pairs-file")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs="+")
    args = ap.parse_args()

    if args.compare:
        runs = [json.loads(Path(p).read_text()) for p in args.compare]
        base = runs[0]
        rep = []
        for p, r in zip(args.compare[1:], runs[1:]):
            for model in ("cross_encoder", "stage1_embedding"):
                for arm, vals in base[model]["raw"].items():
                    other = r[model]["raw"][arm]
                    a = [float.fromhex(x) for x in vals]
                    b = [float.fromhex(x) for x in other]
                    rep.append({"vs": p, "model": model, "arm": arm, "bit_identical": a == b,
                                "max_abs_diff": max(abs(x - y) for x, y in zip(a, b))})
        print(json.dumps({"base": args.compare[0], "rows": rep}, indent=1))
        return 0

    import torch
    if args.threads:
        torch.set_num_threads(args.threads)
    rng = random.Random(7)
    lo, hi = (8, 60) if args.texts == "short" else (20, 300)
    texts = make_texts(rng, 20, lo, hi)
    others = make_texts(rng, 10, lo, hi)
    ce, ce_fn, emb_fn = scorers(args.mode)
    out = {"date": date.today().isoformat(), "mode": args.mode, "texts": args.texts,
           "torch_threads": torch.get_num_threads(), "cuda_visible": torch.cuda.is_available(),
           "ce_device": str(getattr(getattr(ce, "model", None), "device", "n/a")),
           "ce_class": type(ce).__name__}
    from lib import reranker, embedding
    if args.mode == "fixed":
        out["fixed_shape"] = {"ce_seq_len": reranker._ce_seq_len(ce), "ce_batch": reranker._CE_BATCH,
                              "embed_seq_len": embedding._FIXED_SEQ_LEN, "embed_batch": embedding._EMBED_BATCH}
    for key, fn in (("cross_encoder", ce_fn), ("stage1_embedding", emb_fn)):
        res, raw = arms(fn, texts, others, random.Random(11))
        out[key] = {"arms": res, "all_bit_identical": all(a["bit_identical"] for a in res),
                    "raw": {k: [float(x).hex() for x in v] for k, v in raw.items()}}
    if args.pairs_file:
        sets = load_pairs(args.pairs_file, 40)
        out["pairs_file"] = args.pairs_file
        out["real_pairs"] = {"n_sets": len(sets), "truncation": truncation_stats(sets),
                             "tokenization_parity": tokenization_parity(sets)}
        if args.mode == "fixed":
            real = {"cross_encoder": [], "stage1_embedding": []}
            for q, ts in sets[:10]:
                full_ce = ce_fn(q, ts)
                full_em = emb_fn(q, ts)
                rem_ce = ce_fn(q, ts[11:])
                rem_em = emb_fn(q, ts[11:])
                one_ce = [ce_fn(q, [t])[0] for t in ts[:5]]
                one_em = [emb_fn(q, [t])[0] for t in ts[:5]]
                real["cross_encoder"].append(full_ce[11:] == rem_ce and full_ce[:5] == one_ce)
                real["stage1_embedding"].append(full_em[11:] == rem_em and full_em[:5] == one_em)
            out["real_pairs"]["bit_identical_sets"] = {k: f"{sum(v)}/{len(v)}" for k, v in real.items()}
    else:
        sets = [(QUERY, texts)] + [(f"query {i} " + " ".join(rng.choice(WORDS) for _ in range(6)),
                                    make_texts(rng, 20, lo, hi)) for i in range(4)]
    if args.bench:
        out["bench"] = bench(sets, args.reps)
    text = json.dumps(out, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n")
    summary = {k: v for k, v in out.items() if k not in ("cross_encoder", "stage1_embedding")}
    for key in ("cross_encoder", "stage1_embedding"):
        summary[key] = {"all_bit_identical": out[key]["all_bit_identical"],
                        "arms": [(a["arm"], a["bit_identical"], a["max_abs_diff"]) for a in out[key]["arms"]]}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
