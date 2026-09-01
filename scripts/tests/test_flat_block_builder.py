"""The production flat-block build path (`scripts/build_flat_blocks.py`).

Doc 18 §17 #2 listed "no build-time path" as the last blocker to serving the
flat abstract store: the three builders in `lib/thinclient/abstracts.py` ship,
but nothing drove them for a served section. `build_flat_blocks.py` is that
driver, and what has to be true of it is *operational*, not algorithmic — the
underlying builders are already covered by `test_abstract_locator.py`. So this
file asserts the properties a production build path has to have:

  * it publishes only after a byte-parity gate passes, on all four serving arms
  * the served name (`abstracts.sqlite.flat`) never exists half-populated
  * it refuses to overwrite a published sidecar
  * it resumes: a completed stage is detected and skipped, an interrupted one
    is detected and redone (including the `blocks.bin.partial` left behind)
  * it is additive: the source sqlite is byte-identical afterwards
  * a torn artifact is caught by the stage-state checks, not served

The last block covers the INLINE path added 2026-08-17 (doc 18 §22 "still not
settled" #2): `build_thinclient_index.py --flat-sidecar` drives that same
`build_section` at the end of a build. What has to be true there is that the
flag is genuinely opt-in, that the gate's verdict propagates out of the build
(a failed gate must abort, not warn), and that a rerun does not touch a
published sidecar. Synthetic scale only — this path has NOT been run at 150M.

Everything runs on a tiny store built through the shipped writer, so no fixture
encodes an assumption about the on-disk format.

Run: .venv/bin/python3 -m pytest scripts/tests/test_flat_block_builder.py -q
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from lib.thinclient.abstracts import (  # noqa: E402
    DICTS_STAMP, FLAT_STAMP, LOCATOR_STAMP, AbstractStore, AbstractStoreWriter,
    build_flat_sidecar)
import build_flat_blocks as B  # noqa: E402

LATIN = ("A study of citation half-lives across the social sciences, with "
         "attention to archival provenance and network effects. Document %d.")
CYR = ("Исследование сетевых эффектов и архивной атрибуции в социальных "
       "науках. Документ %d.")


def make_store(path: Path, n: int = 1200, odd_ids: bool = True) -> dict:
    w = AbstractStoreWriter(path)
    docs = {}
    for i in range(n):
        did = f"W{100000 + i}"
        text = (CYR if i % 7 == 0 else LATIN) % i
        docs[did] = text
        w.add(did, text)
    if odd_ids:
        docs["W0999"] = "leading-zero id — a docs_other-class record"
        docs["Wxyz"] = "non-numeric id — unaddressable by the ordinal locator"
        w.add("W0999", docs["W0999"])
        w.add("Wxyz", docs["Wxyz"])
    w.finish()
    return docs


@pytest.fixture
def section(tmp_path):
    """A section directory holding only a built v3 abstract store."""
    sdir = tmp_path / "sections" / "synthetic__recent"
    sdir.mkdir(parents=True)
    src = sdir / "abstracts.sqlite"
    docs = make_store(src)
    return src, docs


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_build_publishes_only_after_parity_passes(section):
    src, docs = section
    before = _digest(src)

    rep = B.build_section(src, verify_ids=2000, verify_blocks_n=50)

    assert rep["pass"] is True
    assert rep["published"] is True
    flat = src.with_suffix(src.suffix + ".flat")
    assert flat.is_dir()
    assert not src.with_suffix(src.suffix + ".flat.building").exists()
    for f in ("blocks.bin", "block_offsets.npy", "block_lengths.npy",
              "block_dictids.npy", FLAT_STAMP, LOCATOR_STAMP, DICTS_STAMP,
              "loc_wids.npy", "loc_b.npy", "loc_off.npy", "loc_n.npy"):
        assert (flat / f).exists(), f

    for arm, st in rep["verify_reads"]["arms"].items():
        assert st["pass"], (arm, st)
    assert rep["verify_reads"]["locator_attached"] is True
    assert rep["verify_reads"]["sqlite_free_has_no_db"] is True
    assert rep["verify_blocks"]["pass"] and rep["verify_blocks"]["blocks_checked"] > 1

    assert _digest(src) == before

    s = AbstractStore(src)
    assert s._flat is not None and s._locator is not None
    assert s.fetch(list(docs)) == docs


def test_unaddressable_ids_block_deletion_but_still_serve(section):
    """Hazard 2: ids the ordinal locator cannot address keep the SQLite path,
    so the store still returns them — but `abstracts.sqlite` is NOT deletable."""
    src, docs = section
    rep = B.build_section(src, verify_ids=2000, verify_blocks_n=20)
    assert rep["skipped_non_wid"] == 2
    assert rep["sqlite_deletable"] is False
    assert AbstractStore(src).fetch(["W0999", "Wxyz"]) == {
        "W0999": docs["W0999"], "Wxyz": docs["Wxyz"]}


def test_all_wid_store_is_reported_deletable(tmp_path):
    sdir = tmp_path / "sections" / "clean__recent"
    sdir.mkdir(parents=True)
    src = sdir / "abstracts.sqlite"
    docs = make_store(src, n=400, odd_ids=False)
    rep = B.build_section(src, verify_ids=400, verify_blocks_n=20)
    assert rep["skipped_non_wid"] == 0
    assert rep["sqlite_deletable"] is True
    free = tmp_path / "free"
    free.mkdir()
    (free / "abstracts.sqlite.flat").symlink_to(
        src.with_suffix(src.suffix + ".flat"))
    s = AbstractStore(free / "abstracts.sqlite")
    assert s._db is None
    assert s.fetch(list(docs)) == docs


def test_a_failed_verify_does_not_publish(section, monkeypatch):
    src, _ = section
    monkeypatch.setattr(B, "verify_reads", lambda *a, **k: {
        "ids_checked": 10, "arms": {"flat_ordinal": {"pass": False}},
        "pass": False})
    rep = B.build_section(src, verify_ids=10, verify_blocks_n=5)
    assert rep["pass"] is False and rep["published"] is False
    assert not src.with_suffix(src.suffix + ".flat").exists()
    assert src.with_suffix(src.suffix + ".flat.building").is_dir()


def test_build_refuses_to_overwrite_a_published_sidecar(section):
    src, _ = section
    B.build_section(src, verify_ids=200, verify_blocks_n=10)
    with pytest.raises(SystemExit, match="already exists"):
        B.build_section(src, verify_ids=200, verify_blocks_n=10)


def test_completed_flat_stage_is_detected_and_skipped(section):
    """The expensive stage is a single sequential pass; a rerun must not repeat
    it. Completion is proved from the stamp the builder writes last."""
    src, _ = section
    stage = src.with_suffix(src.suffix + ".flat.building")
    build_flat_sidecar(src, stage)
    flat_id = json.loads((stage / FLAT_STAMP).read_text())["flat_store_id"]

    rep = B.build_section(src, verify_ids=500, verify_blocks_n=10)
    assert rep["stages"]["flat"]["skipped"] is True
    assert rep["stages"]["locator"]["skipped"] is False
    assert rep["pass"] is True
    flat = src.with_suffix(src.suffix + ".flat")
    assert json.loads((flat / FLAT_STAMP).read_text())["flat_store_id"] == flat_id


def test_interrupted_flat_stage_is_redone_and_the_partial_removed(section):
    src, _ = section
    stage = src.with_suffix(src.suffix + ".flat.building")
    stage.mkdir()
    (stage / "blocks.bin.partial").write_bytes(b"\x00" * 4096)
    rep = B.build_section(src, verify_ids=500, verify_blocks_n=10)
    assert rep["stages"]["flat"]["skipped"] is False
    assert rep["pass"] is True
    assert not (src.with_suffix(src.suffix + ".flat")
                / "blocks.bin.partial").exists()


def test_truncated_index_array_is_caught_not_served(section):
    """doc 18 §12's failure: one column short, and the tail addresses whatever
    the shorter array holds. The stage state must call that incomplete."""
    src, _ = section
    stage = src.with_suffix(src.suffix + ".flat.building")
    build_flat_sidecar(src, stage)
    ok, _ = B.flat_stage_state(stage, src)
    assert ok
    arr = np.load(stage / "block_lengths.npy")
    np.save(stage / "block_lengths.npy", arr[:-1])
    ok, why = B.flat_stage_state(stage, src)
    assert not ok and "block_lengths" in why


@pytest.mark.parametrize("shape", ["truncated", "empty", "garbage"])
def test_a_torn_published_index_falls_back_losslessly_to_v3(section, shape):
    """The other half of the torn-artifact story: a stage that never published
    is caught by `flat_stage_state`, but an index torn *after* publication is
    only seen by the reader. `np.load` does not confine that to `OSError`
    (measured 2026-08-17: truncated -> ValueError, zero-byte -> EOFError,
    header-corrupt -> ValueError), so the documented lossless fallback to the
    v3 `blocks` table has to catch those too — otherwise a half-written
    sidecar takes the section down instead of degrading."""
    src, docs = section
    assert B.build_section(src, verify_ids=500, verify_blocks_n=10)["published"]
    p = src.with_suffix(src.suffix + ".flat") / "block_lengths.npy"
    raw = p.read_bytes()
    p.write_bytes({"truncated": raw[:len(raw) // 2],
                   "empty": b"",
                   "garbage": b"not an npy file at all"}[shape])

    s = AbstractStore(src)
    assert s._flat is None
    assert s._locator is None
    assert s.fetch(list(docs)) == docs


@pytest.mark.parametrize("shape", ["truncated", "empty", "garbage"])
def test_a_torn_index_in_sqlite_free_mode_raises_a_clear_error(tmp_path, shape):
    """Same tear, no fallback to fall back to: §18's SQLite-free store has no
    `blocks` table, so the reader must say so plainly instead of leaking a
    numpy `ValueError` three frames deeper."""
    sdir = tmp_path / "sections" / "clean__recent"
    sdir.mkdir(parents=True)
    src = sdir / "abstracts.sqlite"
    make_store(src, n=400, odd_ids=False)
    assert B.build_section(src, verify_ids=400, verify_blocks_n=10)["published"]
    free = tmp_path / "free"
    free.mkdir()
    (free / "abstracts.sqlite.flat").symlink_to(
        src.with_suffix(src.suffix + ".flat"))
    p = free / "abstracts.sqlite.flat" / "block_offsets.npy"
    raw = p.read_bytes()
    p.write_bytes({"truncated": raw[:len(raw) // 2],
                   "empty": b"",
                   "garbage": b"not an npy file at all"}[shape])

    with pytest.raises(RuntimeError, match="no payloads left"):
        AbstractStore(free / "abstracts.sqlite")


def test_staging_with_foreign_files_is_refused(section):
    src, _ = section
    stage = src.with_suffix(src.suffix + ".flat.building")
    stage.mkdir()
    (stage / "operator_notes.txt").write_text("do not delete me")
    with pytest.raises(SystemExit, match="refusing to touch"):
        B.build_section(src, verify_ids=100, verify_blocks_n=5)
    assert (stage / "operator_notes.txt").exists()


def test_block_byte_check_catches_a_corrupted_payload(section):
    src, _ = section
    rep = B.build_section(src, verify_ids=200, verify_blocks_n=10)
    flat = src.with_suffix(src.suffix + ".flat")
    with open(flat / "blocks.bin", "r+b") as f:
        f.seek(3)
        b = f.read(1)
        f.seek(3)
        f.write(bytes([b[0] ^ 0xFF]))
    out = B.verify_blocks(src, flat, 10_000)
    assert not out["pass"] and out["mismatched"] >= 1
    assert rep["pass"] is True


def test_read_parity_catches_a_shifted_block_index(section, tmp_path):
    """A wrong offset returns a real, plausible, WRONG abstract — the whole
    reason the gate is byte-level and not 'it returned something'."""
    src, _ = section
    B.build_section(src, verify_ids=200, verify_blocks_n=10)
    flat = src.with_suffix(src.suffix + ".flat")
    off = np.load(flat / "block_offsets.npy")
    assert len(off) > 1
    off[1] = off[0]
    np.save(flat / "block_offsets.npy", off)
    out = B.verify_reads(src, flat, tmp_path / "views", 2000)
    assert not out["pass"]


def test_survey_orders_sections_smallest_first(tmp_path):
    root = tmp_path / "idx"
    for name, n in (("big__recent", 900), ("small__recent", 120)):
        d = root / "sections" / name
        d.mkdir(parents=True)
        make_store(d / "abstracts.sqlite", n=n, odd_ids=False)
    (root / "sections" / "cold__archive").mkdir(parents=True)
    rows = B.survey(root)
    assert [r["section"] for r in rows] == ["small__recent", "big__recent"]
    assert all(r["published"] is False for r in rows)
    assert rows[0]["est_sidecar_bytes"] > 0


import build_thinclient_index as M  # noqa: E402  (after the sys.path setup)


@pytest.fixture
def index_root(tmp_path):
    """An index root holding one built section with a v3 abstract store."""
    root = tmp_path / "idx"
    sdir = root / "sections" / "synthetic__recent"
    sdir.mkdir(parents=True)
    docs = make_store(sdir / "abstracts.sqlite", n=400, odd_ids=False)
    return root, sdir / "abstracts.sqlite", docs


def _stub_other_phases(monkeypatch, tmp_path):
    """Run `main()` for real except for the phases that need a live source
    index — the point is the wiring of the flag, not re-testing export/build."""
    for name in ("phase_export", "phase_build", "phase_pack", "phase_dense",
                 "write_manifest"):
        monkeypatch.setattr(M, name, lambda *a, **k: None)
    monkeypatch.setattr(M, "_flat_report_path",
                        lambda section, rd: tmp_path / f"report_{section}.json")


def test_inline_sidecar_is_off_by_default(index_root, monkeypatch, tmp_path):
    """Default behaviour of the build script is unchanged: no sidecar, no
    staging directory, nothing recorded in build_status.json."""
    root, src, _ = index_root
    _stub_other_phases(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["build_thinclient_index.py", "--index-root", str(root)])
    M.main()

    assert not src.with_suffix(src.suffix + ".flat").exists()
    assert not src.with_suffix(src.suffix + ".flat.building").exists()
    sp = root / "build_status.json"
    status = json.loads(sp.read_text()) if sp.exists() else {}
    assert "flat_sections" not in status and "flat_info" not in status
    assert not list(tmp_path.glob("report_*.json"))


def test_flat_sidecar_flag_emits_a_verified_sidecar_inline(index_root,
                                                           monkeypatch, tmp_path):
    root, src, docs = index_root
    _stub_other_phases(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "build_thinclient_index.py", "--index-root", str(root),
        "--flat-sidecar", "--flat-verify-ids", "400",
        "--flat-verify-blocks", "20"])
    M.main()

    flat = src.with_suffix(src.suffix + ".flat")
    assert flat.is_dir()
    assert not src.with_suffix(src.suffix + ".flat.building").exists()
    for f in ("blocks.bin", FLAT_STAMP, LOCATOR_STAMP, DICTS_STAMP,
              "loc_wids.npy"):
        assert (flat / f).exists(), f

    status = json.loads((root / "build_status.json").read_text())
    assert status["flat_sections"] == ["synthetic__recent"]
    info = status["flat_info"]["synthetic__recent"]
    assert info["pass"] is True and info["published"] is True
    assert info["sqlite_deletable"] is True
    rep = json.loads((tmp_path / "report_synthetic__recent.json").read_text())
    assert rep["pass"] is True
    for arm, st in rep["verify_reads"]["arms"].items():
        assert st["pass"], (arm, st)

    s = AbstractStore(src)
    assert s._flat is not None and s._locator is not None
    assert s.fetch(list(docs)) == docs


def test_a_failed_gate_aborts_the_inline_phase_and_publishes_nothing(
        index_root, monkeypatch, tmp_path):
    """Fail-closed: the sub-script's verdict has to come OUT of the build. A
    gate failure must raise, keep the staging directory, and leave the section
    serving from its v3 abstracts.sqlite."""
    root, src, docs = index_root
    monkeypatch.setattr(B, "verify_reads", lambda *a, **k: {
        "ids_checked": 10, "arms": {"flat_ordinal": {"pass": False}},
        "pass": False})
    status: dict = {}
    with pytest.raises(RuntimeError, match="synthetic__recent"):
        M.phase_flat_sidecar(root, status, 100, 5, report_dir=tmp_path)

    assert not src.with_suffix(src.suffix + ".flat").exists()
    assert src.with_suffix(src.suffix + ".flat.building").is_dir()
    assert status["flat_sections"] == []
    assert status["flat_info"]["synthetic__recent"]["published"] is False
    assert AbstractStore(src).fetch(list(docs)) == docs


def test_a_published_sidecar_is_left_alone_on_a_rerun(index_root, tmp_path):
    """The sub-script REFUSES to overwrite a published sidecar (SystemExit), so
    a resumed build must filter those out rather than trip over them."""
    root, src, _ = index_root
    M.phase_flat_sidecar(root, {}, 200, 10, report_dir=tmp_path)
    flat = src.with_suffix(src.suffix + ".flat")
    flat_id = json.loads((flat / FLAT_STAMP).read_text())["flat_store_id"]
    mtime = (flat / "blocks.bin").stat().st_mtime_ns

    status: dict = {}
    M.phase_flat_sidecar(root, status, 200, 10, report_dir=tmp_path)

    assert status.get("flat_sections") == []
    assert (flat / "blocks.bin").stat().st_mtime_ns == mtime
    assert json.loads((flat / FLAT_STAMP).read_text())["flat_store_id"] == flat_id
