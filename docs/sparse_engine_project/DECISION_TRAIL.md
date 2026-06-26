# Decision Trail — how we got to "build mmap-BMP (+ optional Lance unification)"

> **CLOSED — line MEASURED & STOPPED 2026-06-26.** This trail converged on *building*
> the engine; the later P3a/P3b measurements reversed that — at 150M the bespoke engine
> loses to FOSS (pruning linear in corpus; inverted-side RAM ~7.6× the Qdrant floor).
> Historical reasoning only — current verdict in `README.md` + `07_INTEGRATION_PLAN.md` §8.

The chain of questions and findings (2026-06-25 session) that converged on the
build. Each step: **Q** asked → **finding** → **what it forced**.

| # | Question asked | Finding (measured / source) | What it forced |
|---|---|---|---|
| 1 | Should we swap **off Qdrant** given the sparse RAM/calling pain at 150M? | Qdrant 150M is **RAM-bound**: p50 545–861 ms on the 24 GB host; 30M fits (66 ms). | The pain is real and scale-dependent — keep asking *why*. |
| 2 | Were the **Qdrant OOMs** ever fixed? | Optimizer-OOM **fixed** (PATCH, verified live: `optimizer_status ok`, swap 0). Server-OOM **mitigated** (autorestart) but **structural**. | "Fixed operationally, not structurally" → there's a root cause underneath. |
| 3 | Direct **Qdrant vs Lucene RAM**? | Lucene = bounded JVM heap (2 GB, corpus-independent) + reclaimable page cache. Qdrant = **6.55 GB anon floor, rising ~43 B/point**, non-reclaimable. | The floor *grows with the corpus* — that's the smell. |
| 4 | Is OpenSearch even available to compare? | OpenSearch 3.7 is **online/green but empty** — the 150M corpus is **archived**. | Live OpenSearch numbers unavailable; rely on recorded baseline. |
| 5 | Full **specs comparison** at 150M? | Thin-client **wins quality +0.111 NDCG@10** (29/34) but is ~2.3× the disk and carries the rising floor. | Don't throw away the quality win; fix the RAM/disk instead. |
| 6 | Aren't the vectors **compressed** (zstd/dict)? | zstd/dict is a *text* lever; the sparse leg is **raw f32, `quantization_config: null`** (live). `uint8` is an unused lever (B1 proved 8-bit == f32). | A cheap interim exists — but it *mitigates*, doesn't cure. |
| 7 | **Best of both worlds**, least overhead? + web survey | SEISMIC (in OpenSearch 3.3+), Infinity (C++), LanceDB, etc. | Options exist, but each trades JVM, migration, or maturity. |
| 8 | How does the **JVM bounded heap** work, and why can't tantivy + a sparse engine share one bounded area? | Heap bounded because **index is mmap'd off-heap** (immutable). tantivy gets the same via mmap **without** a heap. The sparse engine is the odd one out. | The good property is **mmap + immutability**, not the heap. |
| 9 | **Wouldn't keeping Qdrant perpetuate the issue?** | **Yes — at 150M.** Root cause named: Qdrant's **mutable/MVCC store** keeps per-point trackers resident; immutable segments (Lucene/tantivy) bake them on disk → ~0 floor. | **Mutable-vs-immutable is THE fault line.** The cure must be immutable. |
| 10 | Split scale: **server full-150M vs local persona** hot/cold? | Persona hot section ≈ 5–26M docs → Qdrant floor ~1 GB (the 30M GREEN zone). Disease is strictly a *full-150M-single-collection* phenomenon. | Qdrant is right *locally*, wrong *at 150M*. Server needs an immutable cure. |
| 11 | Is **LanceDB** the no-JVM immutable cure? | LanceDB **stores** sparse vectors but has **no sparse index** (IVF-PQ/HNSW are dense-only); storage unoptimized for sparse. | The gap is precisely a **sparse index**, not the data type or the substrate. |
| 12 | Could a **LanceDB + BMP connector** fill that gap? | Naive wire-up = **pointless** (BMP is load-into-RAM → re-imports the disease, ~211 GB @150M). The useful version = make **BMP's Block-Max search read mmap'd immutable postings**. | The cure = **fix BMP with mmap**; Lance is the (optional) unifying substrate. |
| 13 | Does **BMP's block-filtering tolerate a paged mmap** access pattern? | Source-checked: block-max is **TERM-MAJOR + contiguous** → block-filtering streams *q* contiguous runs = **mmap-friendly** (same shape as WAND over mmap'd postings). Load-into-RAM is an **engineering choice, not an algorithmic need**. | **No structural blocker.** The build is feasible. |
| 14 | What would **mmap-BMP** buy vs current Qdrant / past OpenSearch? | vs Qdrant: cures floor, ~3× less disk, faster warm, same quality, fewer engines, still no-JVM. vs OpenSearch: keeps +0.111 quality, drops the JVM. (all est.) | Strong enough upside to **justify a spike**. |
| 15 | Prototype **here or spin off**? | All comparison infra is **here** (cargo, test `.bmp`, `spool_backup` 123 GB, live Qdrant, harness). | **Spike here (isolated branch); spin off only after the gate.** |

## The conclusion the trail forces

1. **The 150M pain = Qdrant's mutable per-point anon floor** (steps 1–3, 9). Not a
   bug — a structural property of a mutable store.
2. **The cure must be immutable + mmap'd** (steps 8–9). No-JVM is still wanted
   (recurring overhead), which rules "just use OpenSearch" to a fallback, not the goal.
3. **The only no-JVM immutable substrate that's close is LanceDB — but it lacks a
   sparse index** (step 11). BMP *is* a (measured-good) sparse index — but
   load-into-RAM (step 12).
4. **So: fix BMP with mmap** (immutable postings, ~0 anon floor) — which the source
   check says the algorithm permits (step 13) — and **optionally host it in Lance**
   to unify lexical+sparse+dense and contribute the very sparse index LanceDB #1930
   wants (step 12, Option B).
5. **De-risk with a 2-phase spike here** (steps 14–15): G2 (RAM drops to ~0) and G3b
   (cold-p95 stays bounded) decide build-vs-kill in ~half a week.

**One line:** the corpus quality is worth keeping (+0.111), the RAM wall is Qdrant's
*mutability*, the cure is *immutable mmap*, the no-JVM immutable substrate (Lance)
is missing a *sparse index*, BMP is that index but lives in RAM, BMP's layout is
*already mmap-shaped* — therefore **build "mmap-BMP," optionally on Lance**, and
prove or kill it with two measured gates before committing.
</content>
