"""Unit tests for the live SPLADE query-encoder loading helpers in lib.opensearch_retriever."""

from pathlib import Path

import pytest

from lib.opensearch_retriever import (
    _resolve_onnx_path,
    _resolve_tokenizer_dir,
)


class TestSpladeOnnxLoading:
    """Item #5: SPLADE serving model must load from the local ONNX export, and
    raise a clear error for a bare HF hub id (which can't be fetched offline)."""

    def test_bare_hub_id_raises_clear_error(self):
        with pytest.raises(FileNotFoundError) as exc:
            _resolve_onnx_path("naver/splade-cocondenser-distil")
        assert "ONNX" in str(exc.value)

    def test_missing_path_raises(self):
        with pytest.raises(FileNotFoundError):
            _resolve_onnx_path("/nonexistent/path/to/model")

    def test_resolves_onnx_dir_to_model_file(self, tmp_path):
        (tmp_path / "model.onnx").write_bytes(b"\x00")
        resolved = _resolve_onnx_path(str(tmp_path))
        assert resolved.name == "model.onnx"

    def test_resolves_direct_onnx_file(self, tmp_path):
        f = tmp_path / "model.onnx"
        f.write_bytes(b"\x00")
        assert _resolve_onnx_path(str(f)) == f

    def test_onnx_dir_without_model_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError) as exc:
            _resolve_onnx_path(str(tmp_path))
        assert "model.onnx" in str(exc.value)

    def test_tokenizer_resolves_from_model_dir(self, tmp_path):
        (tmp_path / "tokenizer.json").write_text("{}")
        assert _resolve_tokenizer_dir(str(tmp_path)) == tmp_path

    def test_real_onnx_export_dir_resolves(self):
        """The shipped models/splade_onnx export is discoverable + has a tokenizer."""
        repo_root = Path(__file__).resolve().parents[2]
        onnx_dir = repo_root / "models" / "splade_onnx"
        if not (onnx_dir / "model.onnx").is_file():
            pytest.skip("local SPLADE ONNX export not present")
        assert _resolve_onnx_path(str(onnx_dir)).name == "model.onnx"
        tok = _resolve_tokenizer_dir(str(onnx_dir))
        assert (tok / "tokenizer.json").is_file() or (tok / "tokenizer_config.json").is_file()
