"""O8 (docs/delta_ingest/02_DESIGN.md §3.1): the doc encoder's class label
`backend` is the REQUESTED backend and stays unchanged (results files key on
it); each instance also carries `runtime_backend`, derived from what actually
runs: torch device + parameter dtype, or ORT's first active provider.

No model download, no GPU: transformers loaders and the ORT session are
replaced by tiny fakes."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from lib.thinclient import doc_encoder  # noqa: E402
from lib.thinclient.doc_encoder import (SpladeDocEncoder, SpladeDocEncoderTRT,  # noqa: E402
                                        ort_runtime_label, torch_runtime_label)


class _FakeTok:
    def get_vocab(self):
        return {"[CLS]": 0, "a": 1, "b": 2}


def _fake_loaders(monkeypatch):
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained",
                        classmethod(lambda cls, *a, **k: _FakeTok()))
    monkeypatch.setattr(transformers.AutoModelForMaskedLM, "from_pretrained",
                        classmethod(lambda cls, *a, **k: torch.nn.Linear(2, 2)))


def test_class_labels_unchanged():
    assert SpladeDocEncoder.backend == "pytorch_fp16"
    assert SpladeDocEncoderTRT.backend == "onnxruntime_trt_iob_fp16"


def test_torch_label_helper():
    assert torch_runtime_label("cpu", torch.float32) == "pytorch_fp32_cpu"
    assert torch_runtime_label("cuda", torch.float16) == "pytorch_fp16_cuda"
    assert torch_runtime_label("cuda:0", torch.bfloat16) == "pytorch_bf16_cuda"


def test_ort_label_helper():
    assert ort_runtime_label(["TensorrtExecutionProvider", "CUDAExecutionProvider",
                              "CPUExecutionProvider"]) == "onnxruntime_trt_iob_fp16"
    assert ort_runtime_label(["CUDAExecutionProvider", "CPUExecutionProvider"]) == \
        "onnxruntime_cuda_iob_fp16"
    assert ort_runtime_label(["CPUExecutionProvider"]) == "onnxruntime_cpu_iob_fp16"
    assert ort_runtime_label([]) == "onnxruntime_none_iob_fp16"


def test_cpu_instance_reports_fp32(monkeypatch):
    _fake_loaders(monkeypatch)
    enc = SpladeDocEncoder("fake", device="cpu")
    assert enc.backend == "pytorch_fp16"
    assert enc.runtime_backend == "pytorch_fp32_cpu"


def test_trt_instance_reports_active_provider(monkeypatch):
    class _Sess:
        def get_providers(self):
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    enc = SpladeDocEncoderTRT.__new__(SpladeDocEncoderTRT)
    enc.session = _Sess()
    enc._set_runtime_label()
    assert enc.backend == "onnxruntime_trt_iob_fp16"
    assert enc.runtime_backend == "onnxruntime_cuda_iob_fp16"


def test_module_exports_label_helpers():
    assert callable(doc_encoder.torch_runtime_label)
    assert callable(doc_encoder.ort_runtime_label)
