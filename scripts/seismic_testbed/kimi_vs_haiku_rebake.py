#!/usr/bin/env python3
"""Small re-bake: Kimi-flex (NeuralWatt) vs Haiku judge agreement.

Does NOT touch data/eval_results/llm_judge_cache.json (the Haiku regime G6
commits against). Re-judges a stratified ~10-query sample's Haiku-graded
(query,doc) pairs with the committed `--judge neuralwatt` backend, writes a
separate comparison file, and reports agreement.

Apples-to-apples: same (judge_key, openalex_id) pairs, same title+abstract text,
so the only variable is the judge model.

Usage:
    .venv/bin/python3 scripts/seismic_testbed/kimi_vs_haiku_rebake.py [--queries 10]
"""
import argparse
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("rebake")

import benchmark_llm_judge as J   # the committed backend

HAIKU_CACHE = REPO / "data" / "eval_results" / "llm_judge_cache.json"
OUT_FILE = REPO / "data" / "eval_results" / "kimi_vs_haiku_rebake_20260629.json"
OPENALEX_BASE = "https://api.openalex.org"


def load_haiku() -> dict:
    raw = json.loads(HAIKU_CACHE.read_text())
    # {f"{qk}||{did}": grade} -> {(qk, did): grade}
    out = {}
    for k, g in raw.items():
        qk, _, did = k.rpartition("||")
        out[(qk, did)] = g
    return out


def reconstruct_abstract(inv_index: dict) -> str:
    if not inv_index:
        return ""
    positions = []
    for word, ps in inv_index.items():
        for p in ps:
            positions.append((p, word))
    return " ".join(w for _, w in sorted(positions))


def fetch_abstracts(session: requests.Session, openalex_ids: list[str]) -> dict[str, dict]:
    """OpenAlex batch fetch by openalex id. Returns {oaid: {title, abstract}}."""
    ids = [i for i in openalex_ids if i]
    out = {}
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        params = {"filter": "openalex:" + "|".join(batch), "per_page": "50",
                  "select": "id,display_name,abstract_inverted_index"}
        if J.OPENALEX_API_KEY:
            params["api_key"] = J.OPENALEX_API_KEY
        elif J.OPENALEX_MAILTO:
            params["mailto"] = J.OPENALEX_MAILTO
        try:
            r = session.get(f"{OPENALEX_BASE}/works", params=params, timeout=30,
                            headers={"User-Agent": "SFULibraryMCP-Eval/1.0"})
            r.raise_for_status()
            for w in r.json().get("results", []):
                oid = str(w.get("id", "")).split("/")[-1]
                out[oid] = {"title": w.get("display_name", "")[:200],
                            "abstract": reconstruct_abstract(w.get("abstract_inverted_index") or {})[:400]}
        except Exception as e:
            log.warning("OpenAlex fetch batch %d failed: %s", i, e)
    return out


def stratified_sample(haiku: dict, n: int) -> list[str]:
    """Pick n queries stratified to span the grade distribution + SFU-niche +
    mainstream. Goes by # judged docs (high coverage = more pairs per query)."""
    byq = defaultdict(list)
    for (qk, did), g in haiku.items():
        byq[qk].append((did, g))
    # sort by coverage descending (more judged docs = denser comparison)
    ordered = sorted(byq.items(), key=lambda kv: -len(kv[1]))
    # spread the pick across the list, not just the top, to avoid all-mainstream
    step = max(1, len(ordered) // n)
    picked = [ordered[i * step][0] for i in range(n) if i * step < len(ordered)]
    return picked[:n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", type=int, default=10, help="how many queries to re-judge")
    args = ap.parse_args()

    haiku = load_haiku()
    log.info("Haiku cache: %d (query,doc) grades across %d queries",
             len(haiku), len(set(q for q, _ in haiku)))

    # activate the neuralwatt backend (reads .env at import)
    J._JUDGE_BACKEND = "neuralwatt"
    log.info("Kimi-flex backend: model=%s base=%s max_tokens=%d",
             J._NEURALWATT_MODEL, J._NEURALWATT_BASE_URL, J._NEURALWATT_MAX_TOKENS)
    if not J._NEURALWATT_API_KEY:
        raise SystemExit("NEURALWATT_API_KEY empty — set in .env")

    sample_qks = stratified_sample(haiku, args.queries)
    log.info("stratified sample: %d queries", len(sample_qks))

    session = requests.Session()
    total_pairs = 0
    kimi_scores = {}   # {(qk, did): kimi_grade}
    per_query = []

    for qi, qk in enumerate(sample_qks):
        pairs = [(did, g) for (k, did), g in haiku.items() if k == qk]
        docs = [{"openalex_id": did, "title": "", "abstract": ""} for did, _ in pairs]
        # fetch real titles+abstracts
        abst = fetch_abstracts(session, [d["openalex_id"] for d in docs])
        for d in docs:
            a = abst.get(d["openalex_id"], {})
            d["title"] = a.get("title", "")
            d["abstract"] = a.get("abstract", "")

        # JUDGE DIRECTLY via _call_neuralwatt — do NOT use judge_query(), whose
        # cache-hit short-circuit would serve the Haiku grades back (these pairs
        # are in the Haiku cache by construction → 100% agreement artifact).
        # Build the batched judge prompt the same way _batch_judge_subprocess does,
        # but call the neuralwatt backend per batch so the only variable is the
        # judge MODEL (Kimi-flex), not the cache.
        from benchmark_llm_judge import _parse_json_scores
        haiku_grades = {did: g for did, g in pairs}
        query_kimi = {}
        t_q0 = time.time()
        BATCH = 12
        for bi in range(0, len(docs), BATCH):
            batch = docs[bi:bi + BATCH]
            # mirror _batch_judge_subprocess prompt construction exactly
            lines = [f'Score each paper 0-3 for relevance to: "{qk}"\n',
                     "3=perfectly relevant  2=highly relevant  1=marginal  0=unrelated\n"]
            for p in batch:
                title = (p.get("title") or "")[:200]
                abstract = (p.get("abstract") or "")[:400]
                oid = p.get("openalex_id") or p.get("id", "")
                lines.append(f'[{oid}]\nTitle: {title}')
                if abstract:
                    lines.append(f'Abstract: {abstract}')
                lines.append("")
            lines.append('Reply ONLY with JSON: {"<id>": score, ...}')
            prompt = "\n".join(lines)
            # retry like the script does
            scores = {}
            for attempt in range(3):
                try:
                    raw = J._call_neuralwatt(prompt, timeout=120)
                    scores = _parse_json_scores(raw)
                    if scores:
                        break
                except Exception as e:
                    log.warning("Kimi batch %d failed (attempt %d): %s", bi, attempt + 1, e)
                    time.sleep(1)
            for p in batch:
                oid = p.get("openalex_id") or p.get("id", "")
                if oid in scores:
                    query_kimi[oid] = scores[oid]
                    kimi_scores[(qk, oid)] = scores[oid]
                total_pairs += 1
        dt = time.time() - t_q0

        # agreement for this query
        both = [(haiku_grades[d], query_kimi[d]) for d in query_kimi if d in haiku_grades]
        exact = sum(1 for h, k in both if h == k)
        per_query.append({
            "judge_key": qk, "n_pairs": len(pairs),
            "n_judged_kimi": len(query_kimi),
            "exact_agree": exact, "exact_rate": round(exact / max(len(both), 1), 3),
            "haiku_grades": dict(Counter(h for h, _ in both)),
            "kimi_grades": dict(Counter(k for _, k in both)),
        })
        log.info("[%d/%d] q=%s pairs=%d judged_kimi=%d exact_agree=%d/%d (%.0f%%) [%.1fs]",
                 qi + 1, len(sample_qks), qk[:50], len(pairs), len(query_kimi),
                 exact, len(both), 100 * exact / max(len(both), 1), dt)
        # NOTE: results come from _call_neuralwatt above; judge_query's cache is
        # never touched, so the Haiku cache file is never written or polluted.
        time.sleep(0.2)  # be nice to OpenAlex

    # ── overall agreement ─────────────────────────────────────────────────────
    both = [(haiku[k], kimi_scores[k]) for k in kimi_scores if k in haiku]
    n = len(both)
    exact = sum(1 for h, k in both if h == k)
    within1 = sum(1 for h, k in both if abs(h - k) <= 1)
    haiku_mean = sum(h for h, _ in both) / n if n else 0
    kimi_mean = sum(k for _, k in both) / n if n else 0
    # confusion: haiku_grade row -> kimi_grade col counts
    confusion = defaultdict(lambda: defaultdict(int))
    for h, k in both:
        confusion[h][k] += 1

    summary = {
        "meta": {"description": "Kimi-flex (NeuralWatt) vs Haiku judge agreement, same (query,doc) pairs",
                 "kimi_model": J._NEURALWATT_MODEL, "kimi_base": J._NEURALWATT_BASE_URL,
                 "haiku_model": "claude-haiku-4-5-20251001", "n_queries": len(sample_qks),
                 "date": "2026-06-29",
                 "note": "does NOT modify llm_judge_cache.json; reads it read-only"},
        "overall": {"n_pairs": n, "exact_agree": exact, "exact_rate": round(exact / max(n, 1), 4),
                    "within_1": within1, "within_1_rate": round(within1 / max(n, 1), 4),
                    "haiku_mean_grade": round(haiku_mean, 4),
                    "kimi_mean_grade": round(kimi_mean, 4),
                    "kimi_minus_haiku_mean": round(kimi_mean - haiku_mean, 4)},
        "confusion_haiku_row_kimi_col": {str(h): dict(Counter({k: c for k, c in row.items()}))
                                         for h, row in sorted(confusion.items())},
        "haiku_grade_dist": dict(Counter(h for h, _ in both)),
        "kimi_grade_dist": dict(Counter(k for _, k in both)),
        "per_query": per_query,
        " disagreements_sample": [  # spot-check the worst disagreements
            {"query": qk, "doc": did, "haiku": haiku[(qk, did)], "kimi": kimi_scores[(qk, did)]}
            for (qk, did) in list(kimi_scores)[:0]  # filled below if wanted; keep empty for now
        ],
    }
    # score the worst disagreements (|diff|==3)
    worst = sorted([(qk, did, haiku[(qk, did)], kimi_scores[(qk, did)])
                    for (qk, did) in kimi_scores if (qk, did) in haiku],
                   key=lambda x: -abs(x[2] - x[3]))[:15]
    summary["worst_disagreements"] = [
        {"query": qk[:80], "doc": did, "haiku": h, "kimi": k, "delta": k - h}
        for qk, did, h, k in worst]

    OUT_FILE.write_text(json.dumps(summary, indent=2))
    log.info("wrote %s", OUT_FILE)

    print("\n" + "=" * 64)
    print(f"  Kimi-flex vs Haiku — {n} (query,doc) pairs, {len(sample_qks)} queries")
    print("=" * 64)
    print(f"  exact agreement      : {exact}/{n}  ({100*exact/max(n,1):.1f}%)")
    print(f"  within 1 grade       : {within1}/{n}  ({100*within1/max(n,1):.1f}%)")
    print(f"  Haiku mean grade     : {haiku_mean:.3f}")
    print(f"  Kimi mean grade      : {kimi_mean:.3f}")
    print(f"  Kimi − Haiku (mean)  : {kimi_mean - haiku_mean:+.3f}  "
          f"({'Kimi stricter' if kimi_mean < haiku_mean else 'Kimi more lenient'})")
    print("\n  Confusion (rows=Haiku, cols=Kimi grades):")
    print(f"  {'Haiku':>6} | " + " ".join(f"{k:>6}" for k in range(4)))
    print("  " + "-" * 40)
    for h in range(4):
        row = confusion[h]
        print(f"  {h:>6} | " + " ".join(f"{row.get(k,0):>6}" for k in range(4)))
    print(f"\n  {len(worst)} max-disagreement pairs (|Δ|=3) — see worst_disagreements in file")
    print("  result:", OUT_FILE)


if __name__ == "__main__":
    main()
