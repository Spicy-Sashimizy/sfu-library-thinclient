# research_2026-10-02_updatable_sparse_index/ — can an updater be borrowed?

**Status:** ACTIVE (research record; inputs to `../02_DESIGN.md` and `../12_NEXT_SESSION_2026-10-05.md`)

Research pass of 2026-10-02 (six documents, moved from the repository root
`reports/` and `research_notes/` on 2026-10-10). Question: does any engine have
an updater for immutable SEISMIC-style shards that this project could lift
out, or a translation layer that would make SPLADE updatable on an inverted
index? Every claim carries a provenance tag (**[read]** / [snippet] / inferred)
as written by its author.

| Doc | What |
|---|---|
| `00_REPORT_borrow_merge_rules_not_updaters.md` | The synthesis: borrow engines' merge rules, not their updaters — nothing transplantable exists; the delta tier stays |
| `01_engine_survey.md` | Updatable disk-resident learned-sparse / impact engines, with updater separability |
| `02_dynamic_lsr_literature.md` | 2024–2026 literature and code survey on dynamic LSR indexes |
| `03_impact_index_translation.md` | Impact-quantized inverted index (tantivy / Lucene / PISA) as a SPLADE translation layer |
| `04_lsm_segments_and_delta_tier.md` | LSM / segment merge machinery, per-segment query overhead, a mutable exact delta tier |
| `05_opensearch_seismic_lucene.md` | OpenSearch neural-sparse ANN (SEISMIC inside Lucene segments): update/merge design and reusability |
