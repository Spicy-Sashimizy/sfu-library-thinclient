"""BM25-through-SEISMIC spike — shared BM25F decomposition + tokenizer.

## Why BM25 can be a sparse dot product at all

The production lexical leg (`lib/thinclient/retriever._bm25f_leg`) issues a
tantivy boolean OR of two field queries, title boosted 3.0:

    score(q,d) = 3.0 * BM25_title(q,d) + 1.0 * BM25_abstract(q,d)

and each field's BM25 is itself a sum over query terms:

    BM25_f(q,d) = SUM_t idf_f(t) * tf(t,d,f)*(k1+1)
                          / (tf(t,d,f) + k1*(1 - b + b*dl(d,f)/avgdl_f))

Every factor is either query-only (`idf_f`) or doc-only (the saturation term).
So BM25F is **exactly** an inner product between a doc-side sparse vector and a
query-side sparse vector — the same algebraic shape SEISMIC already serves for
SPLADE. No approximation is introduced by the decomposition itself; the only
approximation in the spike is SEISMIC's own index-time pruning and query-time
summary-skip traversal.

## Two decompositions (they are NOT equivalent under SEISMIC's pruning)

`VARIANT_A` — *idf-in-doc*, one component namespace:
    doc[t]   = 3*idf_title(t)*sat_title(t,d) + idf_abs(t)*sat_abs(t,d)
    query[t] = 1.0
`VARIANT_B` — *idf-in-query*, field-namespaced components (`t·term`, `a·term`):
    doc["t·"+t] = sat_title(t,d)          query["t·"+t] = 3*idf_title(t)
    doc["a·"+t] = sat_abs(t,d)            query["a·"+t] = idf_abs(t)

Both give the identical exact dot product. They differ once SEISMIC prunes,
because SEISMIC's index-time pruning keeps the highest **doc-side impact**
postings per inverted list and clusters docs by those impacts:

- Under A the impact carries idf, so a stopword's postings are near-zero and get
  pruned first — which is what you want.
- Under B the impact is saturation only, so "the" has a *large, flat* impact in
  every doc; pruning cannot tell an informative posting from a stopword one.

Within a single inverted list the two orderings coincide (idf_f(t) is a positive
constant per list), so the difference shows up in the **cross-list** machinery:
the global posting budget, the centroid clustering, and the summary-energy
threshold. Measuring that difference is the point of the spike.

## Tokenizer

Replicates tantivy's `default` tokenizer as used by `lib/thinclient/builder.py`
(`add_text_field("title"/"abstract", index_option="freq")`): SimpleTokenizer
(split on non-alphanumeric) → lowercase → drop tokens longer than 40 chars. No
stemming, no stopword list — tantivy's `default` applies neither.

One spike-imposed deviation: SEISMIC's string component dtype is `U30`
(`seismic.get_seismic_string()`), so tokens are truncated to `TOKEN_MAXLEN`=28
chars, leaving room for variant B's 2-char field prefix. The truncation is
applied identically to the exact brute-force baseline, so it cannot flatter or
penalise SEISMIC — it only shows up as a small divergence against tantivy, which
tokenizes at its own 40-char limit.
"""
from __future__ import annotations

import math
import re

# tantivy BM25 constants (tantivy 0.26 `Bm25Weight`)
K1 = 1.2
B = 0.75
TITLE_BOOST = 3.0          # matches retriever._bm25f_leg's boost_query(qt, 3.0)

TANTIVY_MAX_TOKEN = 40     # tantivy default RemoveLongFilter limit
TOKEN_MAXLEN = 28          # U30 component width minus variant-B's 2-char prefix

VARIANT_A = "idf_in_doc"
VARIANT_B = "idf_in_query"

# Field prefixes for variant B. "\x1f" (unit separator) cannot occur in a token
# produced by the alphanumeric tokenizer, so the namespaces cannot collide.
PFX_TITLE = "t\x1f"
PFX_ABS = "a\x1f"

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """tantivy `default` tokenizer + the spike's U30 truncation."""
    out = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if len(tok) > TANTIVY_MAX_TOKEN:
            continue                      # tantivy drops these outright
        out.append(tok[:TOKEN_MAXLEN])
    return out


def idf(n_docs: int, df: int) -> float:
    """tantivy's BM25 idf: ln(1 + (N - df + 0.5) / (df + 0.5))."""
    return math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


def saturation(tf: int, doc_len: int, avgdl: float) -> float:
    """The doc-only half of BM25: tf*(k1+1) / (tf + k1*(1 - b + b*dl/avgdl))."""
    if tf <= 0:
        return 0.0
    norm = K1 * (1.0 - B + B * (doc_len / avgdl if avgdl > 0 else 1.0))
    return tf * (K1 + 1.0) / (tf + norm)


class BM25FStats:
    """Corpus statistics for the two fields, gathered in one pass."""

    def __init__(self) -> None:
        self.n_docs = 0
        self.df_title: dict[str, int] = {}
        self.df_abs: dict[str, int] = {}
        self.len_title = 0
        self.len_abs = 0

    def add(self, title_toks: list[str], abs_toks: list[str]) -> None:
        self.n_docs += 1
        self.len_title += len(title_toks)
        self.len_abs += len(abs_toks)
        for t in set(title_toks):
            self.df_title[t] = self.df_title.get(t, 0) + 1
        for t in set(abs_toks):
            self.df_abs[t] = self.df_abs.get(t, 0) + 1

    @property
    def avgdl_title(self) -> float:
        return self.len_title / self.n_docs if self.n_docs else 0.0

    @property
    def avgdl_abs(self) -> float:
        return self.len_abs / self.n_docs if self.n_docs else 0.0

    def to_json(self) -> dict:
        return {"n_docs": self.n_docs,
                "vocab_title": len(self.df_title), "vocab_abs": len(self.df_abs),
                "vocab_union": len(set(self.df_title) | set(self.df_abs)),
                "avgdl_title": round(self.avgdl_title, 3),
                "avgdl_abs": round(self.avgdl_abs, 3)}


def _tf(toks: list[str]) -> dict[str, int]:
    tf: dict[str, int] = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    return tf


def doc_vector(title_toks: list[str], abs_toks: list[str], stats: BM25FStats,
               variant: str) -> dict[str, float]:
    """Doc-side sparse vector whose dot with `query_vector` is exact BM25F."""
    tf_t, tf_a = _tf(title_toks), _tf(abs_toks)
    dl_t, dl_a = len(title_toks), len(abs_toks)
    vec: dict[str, float] = {}
    if variant == VARIANT_A:
        for t, f in tf_t.items():
            vec[t] = (vec.get(t, 0.0) + TITLE_BOOST
                      * idf(stats.n_docs, stats.df_title.get(t, 0))
                      * saturation(f, dl_t, stats.avgdl_title))
        for t, f in tf_a.items():
            vec[t] = (vec.get(t, 0.0)
                      + idf(stats.n_docs, stats.df_abs.get(t, 0))
                      * saturation(f, dl_a, stats.avgdl_abs))
    elif variant == VARIANT_B:
        for t, f in tf_t.items():
            vec[PFX_TITLE + t] = saturation(f, dl_t, stats.avgdl_title)
        for t, f in tf_a.items():
            vec[PFX_ABS + t] = saturation(f, dl_a, stats.avgdl_abs)
    else:
        raise ValueError(f"unknown variant {variant!r}")
    return vec


def query_vector(query: str, stats: BM25FStats, variant: str) -> dict[str, float]:
    """Query-side sparse vector. Repeated query terms are collapsed (qtf is not
    used by tantivy's BM25 either — a term appearing twice in the query scores
    once, matching `parse_query`'s boolean OR of unique term queries)."""
    toks = set(tokenize(query))
    q: dict[str, float] = {}
    if variant == VARIANT_A:
        for t in toks:
            if t in stats.df_title or t in stats.df_abs:
                q[t] = 1.0
    elif variant == VARIANT_B:
        for t in toks:
            if t in stats.df_title:
                q[PFX_TITLE + t] = TITLE_BOOST * idf(stats.n_docs, stats.df_title[t])
            if t in stats.df_abs:
                q[PFX_ABS + t] = idf(stats.n_docs, stats.df_abs[t])
    else:
        raise ValueError(f"unknown variant {variant!r}")
    return q
