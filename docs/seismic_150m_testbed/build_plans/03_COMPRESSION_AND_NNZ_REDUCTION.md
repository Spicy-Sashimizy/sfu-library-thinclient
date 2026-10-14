# Build Plan 03 — Forward-index compression (DotVByte) + source nnz reduction

**Status:** DEFERRED 2026-09-25 (DESIGN, unbuilt since 2026-06-28) — DESIGN (created 2026-06-28, unbuilt). **Solves:** serving RAM/disk
reliably; build RAM only *lossily*. **Adjunct, not a primary RAM escape** — read the
honest framing before investing here.

## Why this is an adjunct, not the answer

Compression splits into two kinds with very different payoffs:

- **Lossless / structural (DotVByte, varint, mmap):** safe, but compresses the
  *stored/served* forward index — stock build still materializes the uncompressed
  forward in RAM first. → **~0 % off the build wall.** And serving RAM is *already*
  cured by mmap (Path C). So this only shrinks disk + page-cache pressure.
- **Lossy (scalar quantization, nnz pruning, binary SPLADE):** these DO cut build
  RAM (less data in RAM) — but every one pushes on the **same 0.479 overlap axis
  that already fails the 0.95 bar** (`02_GO_NO_GO_GATES.md`). You'd be compressing
  under the RAM wall by worsening the quality problem that is SEISMIC's actual
  liability. Use only with a mandatory G2 re-eval.

## The levers (grounded)

| Lever | Type | Build-RAM win | Serve/disk win | Quality cost | In Rust core? |
|-------|------|---------------|----------------|--------------|---------------|
| **DotVByte** (`SeismicIndexDotVByte`) | lossless | ~0 % (stock) | ~12–22 % | none | ✅ shipped |
| **Scalar quant** f16→int8 values | lossy | ~25 % (if ingested int8) | ~25 % | measure (G2) | needs verify |
| **nnz reduction** (SPLADE top-k / DF-FLOPS) | lossy-at-source | **linear** (½ nnz ⇒ ½ forward) | linear | measure (G2) | model-side |
| **int4 / binary SPLADE** | lossy | up to ~½ again | large | likely severe | custom |

Measured/known numbers:
- **DotVByte:** SPLADE f16 5.8→5.1 GB (~12 %), LiLsr 17.5→14.9 GB (~15 %)
  (Forward Index Compression paper). Served-side only.
- **Forward floor is linear in nnz:** 4.10 bytes/nnz, 76.7 nnz/doc (measured). So
  nnz reduction is the *only* compression lever that meaningfully moves the **build**
  floor: 76.7 → 38 nnz/doc halves the forward index (~47 → ~24 GB) → build peak
  ~30–35 GB, **borderline-fits 32 GB**.

## The one build-RAM-relevant path: source nnz reduction

This is the only compression worth doing for the build wall, and it's done at the
**SPLADE model / ingestion** side, not in SEISMIC:

1. Apply top-k masking (keep the k highest-weight terms/doc) or a higher DF-FLOPS
   regularization to drop avg_nnz/doc from 76.7 toward a target (for example, 40).
2. **Prune the Qdrant reference leg identically** — otherwise the G2 comparison is
   apples-to-oranges. This turns the exercise into a legitimate "do we ship a leaner
   SPLADE?" experiment, not a hack.
3. Re-run G2 overlap@10 at the new nnz. Pre-registered: nnz reduction is only
   acceptable if overlap@10 does **not** fall materially below the current 0.479
   (that is, it must not make the already-failing quality worse). Record before→after.

## Build steps (if pursued)

1. Choose target nnz/doc; regenerate the sparse field with top-k masking.
2. Rebuild a 2M persona index at the new nnz; measure peak RSS (confirm the linear
   forward shrink) AND G2 overlap@10 versus an identically-pruned Qdrant.
3. If quality holds: build at scale (combine with Plan 01 sharding or Plan 02).
4. For serving: enable `SeismicIndexDotVByte` for the ~12–22 % disk/page-cache win.

## Risks / honest caveats

- **Lossy levers attack the wrong problem.** Serving RAM is already solved (mmap);
  the build help comes *only* from degrading the vectors. Expect this to lower, not
  raise, 0.479.
- **int8/binary quantization for sparse is under-characterized** for this corpus
  (the literature on int8/binary is mostly *dense* embeddings). Treat any int4/binary
  result as research-grade until measured here.
- **DotVByte alone does nothing for the build.** Do not cite it as a build-RAM fix.
- **Query-time pruning (Block-Max Pruning, Dynamic Superblock Pruning) is a latency
  lever, not storage/build-RAM** — out of scope for this wall; noted to avoid
  confusion.

## Success criteria

- If pursued for build RAM: a documented before→after for **both** peak RSS **and**
  G2 overlap@10 at the reduced nnz, with the Qdrant reference pruned identically.
  No silent quality regression.
- If pursued for serving only: DotVByte enabled, disk/page-cache reduction recorded;
  no latency regression.

## Provenance

Forward Index Compression (arXiv 2602.05445, DotVByte numbers); learned-sparse
pruning literature (DF-FLOPS, top-k masking, SPLADE-doc); forward-floor measurement
(2026-06-28 session, `06_FINDINGS.md`). Marked adjunct because the lossless half is
redundant with mmap and the lossy half worsens the failing G2 axis.
