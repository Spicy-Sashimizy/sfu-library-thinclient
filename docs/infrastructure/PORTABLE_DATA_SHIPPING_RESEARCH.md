# Portable build — how to ship the per-shard accompanying data (RESEARCH ONLY)

**2026-07-17. Status: RESEARCH / DECISION RECORD — NOTHING BUILT.** Owner
question: for the handout/portable build, should we (a) ship all shard DBs
prebuilt ("150M cold") and unpack sections, (b) ship empty and have the end
user download + format from OpenAlex locally, or (c) something better? This
note records the analysis and a recommendation. Researched by the host
(Claude) session during the deployprep campaign; grounded in the measured
WI-8 inventory (`data/eval_results/portable_stack_manifest.json`) and online
sources (linked inline).

## 1. What "accompanying data" actually is, per shard (measured, 150M)

From WI-8 (2026-07-17, this container, as-is):

| Artifact | Role | 150M size | Subset ~10–15M *est.* (≈×0.07–0.1) |
|---|---|---|---|
| SEISMIC shard mmap dirs ×8 (dv, e5_v2) | SPLADE leg (postings+forward) | 66.24 GB | ~5–7 GB |
| `meta.sqlite` | hydration (title/DOI/year/type) | 24.91 GB | ~1.8–2.5 GB |
| packed lexical (tantivy) | BM25F leg | 44.98 GB | ~3.2–4.5 GB |
| dense (usearch) | dense leg | 0.36 GB | ~0.03 GB (persona-scale today) |
| models (SPLADE ONNX fused + dense) | query encode | ~3.9 GB | same (does not scale with corpus) |
| seismic v3 `.so` | engine | 2.7 MB | same |
| **Total** | | **185.3 GB** | **~15–20 GB** *est.* |

Two structural facts drive everything below: **shards are immutable**
(update = replace file + flip manifest — the WI-14 contract), and the
SPLADE/dense artifacts are **model-derived** (they cannot be recreated
without re-encoding the corpus with the exact served model).

## 2. Option analysis

### Option B — ship empty, user downloads + formats from OpenAlex: REJECTED as primary
- The raw source is the OpenAlex snapshot: **~330 GB gzip / ~1.6 TB
  decompressed** JSONL, monthly refresh, CC0
  ([snapshot format](https://developers.openalex.org/download/snapshot-format),
  [AWS open data registry](https://registry.opendata.aws/openalex/)) — a
  larger download than the thing it would rebuild. Filtering to a 10–15M
  subset via the paged API instead is rate-limited and takes days.
- The killer is derived artifacts: SPLADE doc encoding for 10–15M docs is
  GPU-tier work (this repo's own bulk encodes ran on the RTX 4070 Ti; the
  container memory rule "never plan CPU-only for bulk-encode" exists for
  this reason). End users have no GPU by assumption (that is the entire
  portable premise), and encoder/corpus coupling means a user-side encode
  must exactly match the served model or parity is void.
- Verdict: viable only for the *lexical* leg in principle, and even that
  costs hours of user compute for zero size advantage. **Do not ship empty.**

### Option A2 — ship the full 150M "cold" and unpack sections: REJECTED for handout
185 GB on the wire to use ~20 GB is upside-down for end users. This shape
is only right for archival/server-to-server distribution (it is
approximately what the NAS/archival-container split already does).

### Option A — ship prebuilt subset artifacts: the core of the answer
Precedent says this is the industry-normal shape for exactly our situation:
- Kiwix ships all-of-English-Wikipedia as ONE prebuilt zstd-compressed ZIM
  (~97 GB) via resumable HTTP + torrent with webseeds
  ([kiwix FAQ](https://kiwix.org/en/frequently-asked-questions/),
  [zsync discussion](https://github.com/kiwix/overview/issues/12)) — users
  never "build Wikipedia locally."
- The OpenAlex snapshot itself is redistributed via
  [Academic Torrents](https://academictorrents.com/details/c29c888839bf0512043c770e78ddbe321ea6567b)
  — CC0 makes redistribution of the underlying data unproblematic (the
  models' licenses are the separate open item in the WI-8 delta list).

### Recommendation — Option C: prebuilt subset artifacts + live tail (hybrid)
1. **Installer is small** (Tauri shell + v3 .so + models ≈ 4 GB ceiling,
   CPU-wheels pending per WI-8 delta); on first run it downloads the
   **subset bundle per-artifact, per-shard**: each shard dir, the meta
   slice, the lexical index — each entry sha256'd in the WI-14 bundle
   manifest (already built + proven on fixtures 2026-07-17). Resumable
   HTTP with byte ranges; optional torrent with webseed for cost/scale
   (Kiwix precedent). Staged-beside + verify + manifest-flip = the
   crash-safe apply flow WI-14 already proved.
2. **Wire compression**: dv forward + tantivy packed are already
   compressed formats — expect low single-digit % from zstd re-wrap
   (*est., unmeasured*; measure before deciding to bother). `meta.sqlite`
   is the exception (front-coding/zstd research in
   `LEXICAL_STORAGE_RESEARCH.md` §7 applies) — ship it zstd'd (*est.*
   2–3× on the wire).
3. **Tail + freshness via OpenAlex live API** (the existing Live-only /
   warm-cache tier design in `LOCALIZED_DEPLOYMENT_PLAN.md`): queries
   outside the subset's year×citation cut fall through to the live API;
   the dynamic warm-cache accumulates local coverage. This is what makes
   a 10–15M local cut acceptable as a product — the subset bounds disk,
   not the answerable universe.
4. **Updates**: already solved in shape — the WI-14 delta contract makes
   an index refresh a per-shard fetch (the note there records the classes:
   E8 re-conversion = all shards ~26 GB; encoder distill = models ~1 GB;
   .so fix = 2.7 MB). Add zsync-style intra-file deltas ONLY if measured
   shard-replace sizes ever hurt (*unmeasured; likely unnecessary* since
   shards are replaced whole by design).

## 3. Decision matrix (summary)

| | wire GB (user) | user compute | parity risk | infra cost | verdict |
|---|---|---|---|---|---|
| A2 full-150M cold | 185 | none | none | high egress | reject (handout) |
| B empty + rebuild | 330+ (snapshot) or days of API | GPU-tier (absent) | HIGH (encode mismatch) | low | reject |
| **C subset prebuilt + live tail** | **~15–20 *est.*** | none | none (bit-exact artifacts) | moderate (mirror/torrent offsets it) | **RECOMMENDED** |

## 4. Gated on / measure before build (pre-register in doc 11 if actioned)

1. WI-5 host-tier unblock (spool re-export + `cited_by_count`) → real
   subset artifact sizes replace every *est.* above.
2. zstd wire-gain probe on one dv shard dir + meta slice (cheap, decides §2.2).
3. Licensing: OpenAlex data CC0 ✅; SPLADE/dense **model** licenses = the
   open WI-8 delta item (owner-gated before any public handout).
4. Download-UX proof: WI-14 `updater_check/apply` against a real mirror
   URL — explicitly NOT built tonight (owner: record only).

*Sources: [OpenAlex snapshot format](https://developers.openalex.org/download/snapshot-format) · [OpenAlex on AWS Open Data](https://registry.opendata.aws/openalex/) · [Kiwix FAQ (ZIM/zstd/torrent)](https://kiwix.org/en/frequently-asked-questions/) · [Kiwix zsync issue](https://github.com/kiwix/overview/issues/12) · [OpenAlex on Academic Torrents](https://academictorrents.com/details/c29c888839bf0512043c770e78ddbe321ea6567b)*
