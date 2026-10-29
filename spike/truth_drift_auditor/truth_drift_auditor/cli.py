"""Command-line entry point.

    python -m truth_drift_auditor.cli probe-coverage --draft fixtures/drafts/sample_draft.md
    python -m truth_drift_auditor.cli batch --draft FILE [--offline] [--tier2] [--out report.jsonl]
    python -m truth_drift_auditor.cli watch --doc-id GOOGLE_DOC_ID [--post-comments]
    python -m truth_drift_auditor.cli metrics search "pct_vs_b_nodict"
    python -m truth_drift_auditor.cli metrics aliases
    python -m truth_drift_auditor.cli eval --judged eval/judged_set.example.jsonl [--offline]

``--offline`` uses the FakeVerdictClient and the local text retriever only, so
the whole pipeline runs with no API keys (that is what the tests and the demo
script do).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .evidence.base import ChainedRetriever
from .evidence.local_text import LocalTextRetriever
from .metrics_store import MetricsStore
from .pipeline import Auditor, EscalationPolicy, split_paragraphs
from .tier1_haiku import FakeVerdictClient


def build_auditor(cfg, offline: bool, tier2: bool = False) -> Auditor:
    store = MetricsStore(cfg.path("metrics.directory"))
    legs = []
    corpus_dir = cfg.path("corpus.local_text_dir")
    if corpus_dir and corpus_dir.exists():
        legs.append(LocalTextRetriever(corpus_dir))
    if not offline:
        if cfg.get("corpus.paperqa.enabled", False):
            from .evidence.paperqa import PaperQARetriever
            pq = PaperQARetriever(llm=cfg.get("corpus.paperqa.llm", "claude-haiku-5-5"),
                                  embedding=cfg.get("corpus.paperqa.embedding", "sparse"),
                                  evidence_k=cfg.get("tier1.evidence_k", 5),
                                  skip_summary=cfg.get("corpus.paperqa.skip_summary", True))
            d = cfg.path("corpus.paperqa.documents_dir")
            if d and d.exists():
                pq.add_directory(d)
            if cfg.get("corpus.paperqa.zotero", False):
                pq.add_zotero(limit=cfg.get("corpus.paperqa.zotero_limit", 200))
            legs.insert(0, pq)
        if cfg.get("thinclient.enabled", False):
            from .evidence.thinclient import ThinClientRetriever
            legs.append(ThinClientRetriever(cfg.get("thinclient.base_url", "http://localhost:8788"),
                                            year_from=cfg.get("thinclient.year_from"),
                                            year_to=cfg.get("thinclient.year_to")))
    retriever = ChainedRetriever(legs, min_hits=cfg.get("corpus.min_hits_before_fallback", 1)) if legs else None
    if offline:
        tier1 = FakeVerdictClient()
    else:
        from .tier1_haiku import HaikuVerdictClient
        tier1 = HaikuVerdictClient(model=cfg.get("tier1.model", "claude-haiku-5-5"),
                                   effort=cfg.get("tier1.effort", "low"))
    tier2_fn = None
    if tier2 and not offline:
        from .tier2_claude_code import run_escalation
        mcp = cfg.path("tier2.mcp_config")
        tier2_fn = lambda reps: run_escalation(  # noqa: E731
            reps, model=cfg.get("tier2.model", "claude-fable-5-1"),
            max_turns=cfg.get("tier2.max_turns", 12),
            mcp_config=mcp if mcp and mcp.exists() else None,
            allowed_tools=cfg.get("tier2.allowed_tools"))
    pol = EscalationPolicy(
        low_confidence=cfg.get("escalation.low_confidence", 0.7),
        min_contradicted_in_window=cfg.get("escalation.min_contradicted_in_window", 2),
        window=cfg.get("escalation.window", 5),
        numeric_mismatch_escalates=cfg.get("escalation.numeric_mismatch_escalates", False),
    )
    return Auditor(store=store, retriever=retriever, tier1=tier1, config=cfg, tier2=tier2_fn,
                   policy=pol, evidence_k=cfg.get("tier1.evidence_k", 5),
                   use_vale=cfg.get("vale.enabled", True))


def cmd_probe(args, cfg):
    """Step 1 of the pilot: retrieval only. Does the corpus cover what the draft talks about?"""
    aud = build_auditor(cfg, offline=True)
    text = Path(args.draft).read_text(encoding="utf-8")
    paras = split_paragraphs(text)
    covered = 0
    for p in paras:
        ev = aud.retriever.retrieve(p.text, aud.evidence_k) if aud.retriever else []
        hit = bool(ev) and ev[0].score >= args.min_score
        covered += hit
        print(f"\n--- paragraph {p.index} {'COVERED' if hit else 'NO EVIDENCE'}\n{p.text[:160]}")
        for e in ev[:3]:
            print(f"    [{e.id}] score={e.score} :: {e.text[:120].replace(chr(10), ' ')}")
    print(f"\ncoverage: {covered}/{len(paras)} paragraphs retrieved at least one passage with score >= {args.min_score}")


def cmd_batch(args, cfg):
    aud = build_auditor(cfg, offline=args.offline, tier2=args.tier2)
    reports = aud.audit_document(args.draft)
    out = open(args.out, "w", encoding="utf-8") if args.out else None
    for r in reports:
        flag = "DRIFT" if r.drifted else ("escalate" if r.escalate else "ok")
        print(f"[{flag:8}] p{r.paragraph.index}: {r.paragraph.text[:90]}")
        for f in r.numeric:
            if not f.ok:
                print(f"            number: wrote {f.quote}, measured {f.expected}{f.unit} ({f.path})")
        for c in r.claims:
            if c.verdict != "NOT_CHECKABLE":
                print(f"            {c.verdict:12} conf={c.confidence:.2f} {c.quote[:70]!r} {c.evidence_ids}")
        if r.tier2:
            print("            tier2:", r.tier2[:300])
        for e in r.errors:
            print("            error:", e)
        if out:
            out.write(json.dumps(r.summary(), ensure_ascii=False) + "\n")
    if out:
        out.close()
        print("wrote", args.out)


def cmd_watch(args, cfg):
    from .docs_watcher import DocsWatcher
    aud = build_auditor(cfg, offline=args.offline, tier2=args.tier2)
    w = DocsWatcher(args.doc_id, cfg.path("google.credentials_json"), cfg.path("google.token_json"),
                    interval_s=cfg.get("google.poll_interval_s", 4.0), post_comments=args.post_comments)
    print(f"watching {args.doc_id} every {w.interval_s}s (post_comments={args.post_comments}); Ctrl-C to stop")
    w.run(aud.audit_paragraph, on_report=lambda r: print(r.to_json()))


def cmd_metrics(args, cfg):
    store = MetricsStore(cfg.path("metrics.directory"))
    if args.sub == "search":
        for k, v in store.search(args.pattern, limit=args.limit):
            print(f"{v:>16g}  {k}")
    elif args.sub == "aliases":
        for a, v in store.resolve_aliases(cfg.aliases):
            print(f"{str(v):>12}  {a.unit:3}  '{a.phrase}'  <- {a.path}")
    else:
        print(f"{len(store)} numeric values from {len(store.files)} files in {store.directory}")


def cmd_eval(args, cfg):
    from eval.score import score_judged  # type: ignore
    aud = build_auditor(cfg, offline=args.offline, tier2=False)
    res = score_judged(aud, Path(args.judged), Path(args.out) if args.out else None)
    print(json.dumps(res, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="truth_drift_auditor")
    ap.add_argument("--config", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe-coverage"); p.add_argument("--draft", required=True); p.add_argument("--min-score", type=float, default=1.0); p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("batch"); p.add_argument("--draft", required=True); p.add_argument("--offline", action="store_true"); p.add_argument("--tier2", action="store_true"); p.add_argument("--out"); p.set_defaults(fn=cmd_batch)
    p = sub.add_parser("watch"); p.add_argument("--doc-id", required=True); p.add_argument("--offline", action="store_true"); p.add_argument("--tier2", action="store_true"); p.add_argument("--post-comments", action="store_true"); p.set_defaults(fn=cmd_watch)
    p = sub.add_parser("metrics"); p.add_argument("sub", choices=["search", "aliases", "stats"]); p.add_argument("pattern", nargs="?", default="."); p.add_argument("--limit", type=int, default=50); p.set_defaults(fn=cmd_metrics)
    p = sub.add_parser("eval"); p.add_argument("--judged", required=True); p.add_argument("--offline", action="store_true"); p.add_argument("--out"); p.set_defaults(fn=cmd_eval)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    args.fn(args, cfg)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
