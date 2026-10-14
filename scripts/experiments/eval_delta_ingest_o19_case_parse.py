"""O19 follow-up (docs/delta_ingest/02_DESIGN.md §3.1), 2026-10-01: why does
lower-casing the BM25F query text (`bm25f_query_text`, 99e2b663) change hits
on the served index, and for how many real queries?

Cause under test: tantivy's QueryParser collapses a repeated query word only
when its SURFACE form repeats; case variants ("How" ... "how") survive as two
clauses, and after the default (lower-casing) tokenizer they are two identical
TermQuery("how") clauses, so that term's score counts twice. Upper-case AND /
OR / NOT are boolean operators and IN raises a syntax error before the fix.

Modes
  parse : lock-free. Parses every query pre-fix (sanitised, case kept) and
          post-fix (sanitised + lower) on an EMPTY tmp index with the served
          schema (parse_query only needs the schema), for title and abstract,
          and classifies: pre_raises / same / diff (+ reason).
  hits  : SHARED lock. Opens the served tantivy sections read-only
          (data/thinclient_index/sections/*/tantivy; no SEISMIC, no models),
          runs the real `ThinClientRetriever._bm25f_leg` (gate off) with the
          module's `bm25f_query_text` swapped for the pre-fix version in the
          pre arm, for every `diff` query plus a control sample of `same`
          queries, and compares the top-K lists. Known-item rank: titles ->
          their own W-id (title_sample order); topics -> `seed_doi`.

Queries: data/sfu_eval_queries.json "query" (120 topics, file order) and
/home/vscode/work/delta_ingest/corpus_a/title_sample.json "titles" (the M3
sample is its first 350; parse mode also runs all of them).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

TOPICS = REPO / "data" / "sfu_eval_queries.json"
TITLES = Path("/home/vscode/work/delta_ingest/corpus_a/title_sample.json")
SECTIONS = REPO / "data" / "thinclient_index" / "sections"
OPS = {"AND", "OR", "NOT", "IN", "TO"}


def pre_text(q: str) -> str:
    return "".join(c if c.isalnum() or c.isspace() else " " for c in q)


def lower_0930(q: str) -> str:
    return pre_text(q).lower()


def post_text(q: str) -> str:
    from lib.thinclient.retriever import bm25f_query_text
    return bm25f_query_text(q)


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_queries(n_titles: int | None):
    topics = json.loads(TOPICS.read_text())
    ts = json.loads(TITLES.read_text())
    titles = list(zip(ts["order"], ts["titles"]))
    if n_titles is not None:
        titles = titles[:n_titles]
    out = [{"set": "topic", "i": i, "q": t["query"], "known": t.get("seed_doi")}
           for i, t in enumerate(topics)]
    out += [{"set": "title", "i": i, "q": t, "known": wid} for i, (wid, t) in enumerate(titles)]
    return out


def reasons(q: str) -> list[str]:
    words = pre_text(q).split()
    r = []
    forms: dict[str, set] = {}
    for w in words:
        forms.setdefault(w.lower(), set()).add(w)
    if any(len(v) > 1 for v in forms.values()):
        r.append("case_variant_repeat")
    if any(w in OPS for w in words):
        r.append("upper_operator_word")
    return r or ["other"]


def schema_index():
    import tantivy
    sb = tantivy.SchemaBuilder()
    sb.add_text_field("id", stored=True, tokenizer_name="raw")
    sb.add_text_field("title", stored=False, index_option="freq")
    sb.add_text_field("abstract", stored=False, index_option="freq")
    sb.add_integer_field("year", stored=False, indexed=True, fast=True)
    sb.add_text_field("doctype", stored=False, tokenizer_name="raw")
    sb.add_boolean_field("is_oa", stored=False, indexed=True)
    tmp = tempfile.mkdtemp(prefix="o19_parse_")
    return tantivy.Index(sb.build(), path=tmp)


def parse_sig(idx, text: str):
    try:
        return (repr(idx.parse_query(text, ["title"])), repr(idx.parse_query(text, ["abstract"]))), None
    except ValueError as exc:
        return None, str(exc)


def classify(idx, q: str, post=post_text) -> dict:
    a, ea = parse_sig(idx, pre_text(q))
    b, eb = parse_sig(idx, post(q))
    if eb:
        return {"cls": "post_raises", "err": eb}
    if ea:
        return {"cls": "pre_raises", "err": ea}
    if a == b:
        return {"cls": "same"}
    n_pre = len(re.findall("TermQuery", a[0]))
    n_post = len(re.findall("TermQuery", b[0]))
    return {"cls": "diff", "reasons": reasons(q), "term_clauses_pre": n_pre, "term_clauses_post": n_post}


def summarize(rows: list[dict], subset) -> dict:
    sel = [r for r in rows if subset(r)]
    out = {"n": len(sel)}
    for c in ("same", "diff", "pre_raises", "post_raises"):
        out[c] = sum(r["cls"] == c for r in sel)
    rs: dict[str, int] = {}
    for r in sel:
        if r["cls"] == "diff":
            for x in r["reasons"]:
                rs[x] = rs.get(x, 0) + 1
    out["diff_reasons"] = rs
    return out


def run_parse(a) -> dict:
    idx = schema_index()
    qs = load_queries(None)
    rows = []
    c0930 = []
    for q in qs:
        rows.append({"set": q["set"], "i": q["i"], **classify(idx, q["q"])})
        c0930.append({"set": q["set"], "i": q["i"], **classify(idx, q["q"], lower_0930)})
    res = {
        "utc": utc(), "mode": "parse",
        "arms": {"pre": "sanitise, case kept (pre-99e2b663)",
                 "post": "bm25f_query_text of the working tree (current)",
                 "lower_0930": "sanitise + str.lower() (99e2b663)"},
        "lower_0930_vs_pre": {
            "topics_120": summarize(c0930, lambda r: r["set"] == "topic"),
            "titles_m3_350": summarize(c0930, lambda r: r["set"] == "title" and r["i"] < 350),
            "titles_all": summarize(c0930, lambda r: r["set"] == "title")},
        "topics_120": summarize(rows, lambda r: r["set"] == "topic"),
        "titles_m3_350": summarize(rows, lambda r: r["set"] == "title" and r["i"] < 350),
        "titles_all": summarize(rows, lambda r: r["set"] == "title"),
        "diff_topics": [{"i": r["i"], "q": qs[k]["q"], "reasons": r["reasons"]}
                        for k, r in enumerate(rows) if r["set"] == "topic" and r["cls"] == "diff"],
        "diff_titles_350": [{"i": r["i"], "q": qs[k]["q"], "reasons": r["reasons"]}
                            for k, r in enumerate(rows)
                            if r["set"] == "title" and r["i"] < 350 and r["cls"] == "diff"],
    }
    Path(a.parse_out).write_text(json.dumps({"summary": res, "rows": rows}))
    return res


def open_served():
    import tantivy
    from lib.thinclient.retriever import ThinClientRetriever
    tc = ThinClientRetriever(index_root=str(REPO / "data" / "thinclient_index"), remote_abstracts=False)
    secs = {}
    for sdir in sorted(SECTIONS.iterdir()):
        if not (sdir / "tantivy" / "meta.json").exists():
            continue
        idx = tantivy.Index.open(str(sdir / "tantivy"))
        idx.reload()
        secs[sdir.name] = {"index": idx, "searcher": idx.searcher(), "schema": idx.schema, "bmp": []}
    tc._sections = secs
    tc._delta = None
    tc._bm25f_parse_once = False
    return tc


def leg(tc, q: str, k: int, pre: bool) -> list[str]:
    import lib.thinclient.retriever as R
    saved = R.bm25f_query_text
    if pre:
        R.bm25f_query_text = pre_text
    try:
        return [d for d, _ in tc._bm25f_leg(q, k, None)]
    finally:
        R.bm25f_query_text = saved


def rank_of(ids: list[str], wid) -> int | None:
    return ids.index(wid) + 1 if wid in ids else None


def run_hits(a) -> dict:
    parsed = json.loads(Path(a.parse_out).read_text())["rows"]
    qs = load_queries(None)
    by = {(r["set"], r["i"]): r for r in parsed}
    pick = [q for q in qs if by[(q["set"], q["i"])]["cls"] == "diff"
            and (q["set"] == "topic" or q["i"] < a.max_title_index)]
    same = [q for q in qs if by[(q["set"], q["i"])]["cls"] == "same"
            and (q["set"] == "topic" or q["i"] < 350)]
    random.Random(20261001).shuffle(same)
    control = same[:a.n_control]
    tc = open_served()
    t0 = time.time()
    rows = []
    for kind, lst in (("diff", pick), ("control", control)):
        for q in lst:
            pre = leg(tc, q["q"], a.k, True)
            post = leg(tc, q["q"], a.k, False)
            rows.append({"kind": kind, "set": q["set"], "i": q["i"], "q": q["q"],
                         "reasons": by[(q["set"], q["i"])].get("reasons"),
                         "n_pre": len(pre), "n_post": len(post),
                         "identical": pre == post,
                         "same_set": set(pre) == set(post),
                         "overlap10": len(set(pre[:10]) & set(post[:10])),
                         "overlap_k": len(set(pre) & set(post)),
                         "top1_same": bool(pre and post and pre[0] == post[0]),
                         "known": q["known"], "known_rank_pre": rank_of(pre, q["known"]),
                         "known_rank_post": rank_of(post, q["known"])})
            if time.time() > a.deadline_epoch:
                break

    def agg(sel):
        n = len(sel)
        kp = [r for r in sel if r["known_rank_pre"] or r["known_rank_post"]]
        better = sum(1 for r in kp if (r["known_rank_post"] or 10**9) < (r["known_rank_pre"] or 10**9))
        worse = sum(1 for r in kp if (r["known_rank_post"] or 10**9) > (r["known_rank_pre"] or 10**9))
        return {"n": n, "identical": sum(r["identical"] for r in sel),
                "both_empty": sum(1 for r in sel if not r["n_pre"] and not r["n_post"]),
                "same_set": sum(r["same_set"] for r in sel),
                "top1_same": sum(r["top1_same"] for r in sel),
                "mean_overlap10": round(sum(r["overlap10"] for r in sel) / n, 3) if n else None,
                "known_found_either": len(kp), "known_rank_better_post": better,
                "known_rank_worse_post": worse,
                "known_rank_equal": len(kp) - better - worse}

    res = {"utc_end": utc(), "mode": "hits", "k": a.k, "seconds": round(time.time() - t0, 1),
           "sections": sorted(tc._sections),
           "diff_topics": agg([r for r in rows if r["kind"] == "diff" and r["set"] == "topic"]),
           "diff_titles": agg([r for r in rows if r["kind"] == "diff" and r["set"] == "title"]),
           "diff_titles_m3_350": agg([r for r in rows if r["kind"] == "diff" and r["set"] == "title"
                                      and r["i"] < 350]),
           "control_same_parse": agg([r for r in rows if r["kind"] == "control"]),
           "max_title_index": a.max_title_index}
    return {"summary": res, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["parse", "hits"])
    ap.add_argument("--parse-out", default="/home/vscode/work/delta_ingest/fix/o19_parse_rows.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--n-control", type=int, default=40)
    ap.add_argument("--max-title-index", type=int, default=50000)
    ap.add_argument("--deadline-epoch", type=float, default=float("inf"))
    a = ap.parse_args()
    Path(a.parse_out).parent.mkdir(parents=True, exist_ok=True)
    out_p = Path(a.out)
    doc = json.loads(out_p.read_text()) if out_p.exists() else {}
    import subprocess
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    if a.mode == "parse":
        doc["parse"] = {**run_parse(a), "head": head, "script": str(Path(__file__).relative_to(REPO)),
                        "rows_file": a.parse_out}
    else:
        r = run_hits(a)
        doc["hits"] = {**r["summary"], "head": head}
        rows_p = Path(a.parse_out).with_name("o19_hits_rows.json")
        rows_p.write_text(json.dumps(r["rows"]))
        doc["hits"]["rows_file"] = str(rows_p)
    out_p.write_text(json.dumps(doc, indent=1))
    print(json.dumps({k: v for k, v in doc.get(a.mode, {}).items() if not k.startswith("diff_t") or
                      isinstance(v, dict)}, indent=1))


if __name__ == "__main__":
    main()
