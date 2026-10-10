# models/ — encoder and reranker models

**Status:** ACTIVE

Only `model_registry.json` (the versions table behind the Admin "Model
Versions" view, maintained by hand + `src/lib/model_registry.py`) and
`.gitkeep` are in git; the model directories are local, large, and
regenerable or downloadable.

| Directory (local) | Role |
|---|---|
| `splade_onnx_fused/` (+ `splade_onnx/`, `splade_onnx_fp16/`) | the served SPLADE query encoder (fused ONNX); the document encoder for rebuilds is `src/lib/thinclient/doc_encoder.py` |
| `sfu-cross-encoder-v1/`, `sfu-cross-encoder-v1-onnx-int8/`, `sfu-cross-encoder-baseline/` | the rerank cross-encoder (base flip pending — `docs/THIN_CLIENT_SWAP.md` §Rerank) |
| `sfu-academic-embed-v5/` (+ `v1`, `v4-*`, `v5-onnx-int8`) | dense-leg embedders (dense leg default OFF since 2026-08-18) |
| `sfu-splade-student-l4/`, `sfu-splade-teacher-torch/` | distillation-campaign checkpoints (campaign KILLED 2026-07-28) |
| `trt_engine_cache/` | TensorRT engine cache |

Licensing facts per model: `docs/infrastructure/PORTABLE_LICENSING_INVENTORY.md`.
