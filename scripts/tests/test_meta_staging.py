"""meta.sqlite staging: the residency lever for the post-filter stage.

Measured 2026-08-03 (doc seismic_150m_testbed/18 §14): the SPLADE/dense filter
stage costs 222.2 ms with `meta.sqlite` on 9p and 4.0 ms with the same file on
local disk. `retriever._stage_meta_local` automates that copy. A staging path
that can hand the serve a TORN database is worse than no staging at all, so
what this file asserts is the refusals and the atomicity, not the speed:

  * stages only when asked (default OFF) and only off a slow FS (droplet no-op),
  * an interrupted copy is never promoted and never opened,
  * a verify mismatch fails instead of serving wrong metadata,
  * a live -wal refuses (a byte copy would drop those pages),
  * staged and unstaged connections return identical rows.

Run: .venv/bin/python3 -m pytest scripts/tests/test_meta_staging.py -q
"""
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from lib.thinclient import retriever as R  # noqa: E402

ROWS = [(i, f"title {i}", f"10.1234/{i}", 2000 + i % 25, "article", i % 2, "s")
        for i in range(500)]
STAGE_ENV = ("SFU_META_STAGE_DIR", "SFU_STAGE_META", "SFU_SEISMIC_STAGE_DIR",
             "SFU_META_STAGE_FORCE", "SFU_META_STAGE_VERIFY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in STAGE_ENV:
        monkeypatch.delenv(k, raising=False)


def make_meta(path: Path, rows=ROWS) -> Path:
    """A miniature meta.sqlite in WAL journal mode — same shape and same
    journal mode as the real 24.9 GB file (verified 2026-08-17)."""
    db = sqlite3.connect(str(path))
    db.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=OFF;")
    db.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, title TEXT, doi TEXT,"
               " year INTEGER, type TEXT, is_oa INTEGER, section TEXT)")
    db.executemany("INSERT INTO docs VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # what builder.py:299 does
    db.close()
    return path


def stage_on(monkeypatch, dst_dir: Path, **extra):
    monkeypatch.setenv("SFU_META_STAGE_DIR", str(dst_dir))
    monkeypatch.setenv("SFU_META_STAGE_FORCE", "1")   # tmp_path is a local FS
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def all_rows(conn):
    return conn.execute("SELECT id, title, doi, year, type, is_oa, section "
                        "FROM docs ORDER BY id").fetchall()


# ── gating: OFF by default, no-op on a local source ───────────────────────────

def test_no_env_is_passthrough(tmp_path):
    src = make_meta(tmp_path / "meta.sqlite")
    assert R._stage_meta_local(src) == src
    assert not (tmp_path / "meta.sqlite.staged_ok").exists()


def test_local_source_is_a_noop_without_force(tmp_path, monkeypatch):
    """Production shape: index already on local block storage. Even with the
    stage dir set, staging must not happen — copying 24.9 GB to buy nothing."""
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    monkeypatch.setenv("SFU_META_STAGE_DIR", str(stage))
    assert R._stage_meta_local(src) == src
    assert not stage.exists()


def test_slow_fs_source_stages_without_force(tmp_path, monkeypatch):
    """The auto-trigger: source on 9p/virtiofs/NFS → stage, no force needed."""
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    monkeypatch.setenv("SFU_META_STAGE_DIR", str(stage))
    monkeypatch.setattr(R, "_fstype_for_path", lambda p: "9p")
    assert R._stage_meta_local(src) == stage / "meta.sqlite"


def test_shared_stage_dir_opt_in(tmp_path, monkeypatch):
    """SFU_STAGE_META=1 reuses SFU_SEISMIC_STAGE_DIR (one dir, both artifacts)."""
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "seismic_stage"
    monkeypatch.setenv("SFU_SEISMIC_STAGE_DIR", str(stage))
    monkeypatch.setenv("SFU_META_STAGE_FORCE", "1")
    assert R._stage_meta_local(src) == src      # not opted in yet
    monkeypatch.setenv("SFU_STAGE_META", "1")
    assert R._stage_meta_local(src) == stage / "meta.sqlite"


# ── the copy: happens, verifies, is idempotent ────────────────────────────────

@pytest.mark.parametrize("verify", ["size", "fingerprint", "sha256"])
def test_stages_and_verifies(tmp_path, monkeypatch, verify):
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage, SFU_META_STAGE_VERIFY=verify)
    dst = R._stage_meta_local(src)
    assert dst == stage / "meta.sqlite"
    assert dst.read_bytes() == src.read_bytes()
    marker = json.loads((stage / "meta.sqlite.staged_ok").read_text())
    assert marker["size"] == src.stat().st_size
    assert marker["mtime_ns"] == src.stat().st_mtime_ns
    assert marker["verify"] == verify


def test_second_call_skips_the_copy(tmp_path, monkeypatch):
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)
    first = R._stage_meta_local(src).stat()
    # A re-copy lands on a tmp file and is os.replace'd → a NEW inode. Same
    # inode == the copy genuinely did not run; the poisoned copyfileobj makes
    # any attempt to re-read the source a hard failure.
    monkeypatch.setattr(shutil, "copyfileobj",
                        lambda *a, **k: pytest.fail("re-copied an up-to-date stage"))
    second = R._stage_meta_local(src).stat()
    assert (second.st_ino, second.st_mtime_ns) == (first.st_ino, first.st_mtime_ns)


def test_rebuilt_source_forces_a_restage(tmp_path, monkeypatch):
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)
    first_ino = R._stage_meta_local(src).stat().st_ino
    src.unlink()
    make_meta(src, rows=ROWS[:100])            # a different build, same name
    dst = R._stage_meta_local(src)
    assert dst.stat().st_ino != first_ino
    assert dst.read_bytes() == src.read_bytes()
    assert len(all_rows(sqlite3.connect(str(dst)))) == 100


def test_same_size_different_content_restages(tmp_path, monkeypatch):
    """Two builds can share a byte size. The fingerprint (head+tail+size) is
    what stops the stale copy from being adopted; SFU_META_STAGE_VERIFY=size
    is the documented weaker mode."""
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)
    R._stage_meta_local(src)
    marker = stage / "meta.sqlite.staged_ok"
    ident = json.loads(marker.read_text())
    # Same field widths as ROWS → same page count → same byte size.
    rows2 = [(i, f"OTHER {i}", f"10.9999/{i}", 1990, "article", 0, "z")
             for i in range(500)]
    src.unlink()
    make_meta(src, rows=rows2)
    assert src.stat().st_size == ident["size"]         # same size, new content
    ident["mtime_ns"] = src.stat().st_mtime_ns         # forge a matching mtime
    marker.write_text(json.dumps(ident))
    dst = R._stage_meta_local(src)
    assert all_rows(sqlite3.connect(str(dst)))[0][1] == "OTHER 0"


# ── failure modes: never promote, never serve torn data ───────────────────────

def test_interrupted_copy_leaves_nothing_openable(tmp_path, monkeypatch):
    """Simulate SIGKILL mid-copy: the partial bytes must stay on the tmp name,
    the destination must not appear, and the marker must not claim success."""
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)
    real = shutil.copyfileobj

    def die(fsrc, fdst, length=0):
        fdst.write(fsrc.read(4096))            # a truncated, unopenable prefix
        raise KeyboardInterrupt("simulated kill mid-copy")

    monkeypatch.setattr(shutil, "copyfileobj", die)
    with pytest.raises(KeyboardInterrupt):
        R._stage_meta_local(src)
    assert not (stage / "meta.sqlite").exists()
    assert not (stage / "meta.sqlite.staged_ok").exists()
    assert not list(stage.glob("meta.sqlite.tmp-*"))   # cleaned on the way out

    # And the next boot recovers: a real copy completes and is promoted.
    monkeypatch.setattr(shutil, "copyfileobj", real)
    dst = R._stage_meta_local(src)
    assert dst.read_bytes() == src.read_bytes()


def test_interrupt_does_not_promote_over_a_good_copy(tmp_path, monkeypatch):
    """A staged copy already in place stays openable when a restage dies —
    os.replace is the only thing that ever touches the destination name."""
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)
    dst = R._stage_meta_local(src)
    good = dst.read_bytes()
    src.unlink()
    make_meta(src, rows=ROWS[:10])             # forces a restage
    monkeypatch.setattr(shutil, "copyfileobj",
                        lambda a, b, length=0: (_ for _ in ()).throw(OSError("ENOSPC")))
    with pytest.raises(OSError):
        R._stage_meta_local(src)
    assert dst.read_bytes() == good            # old copy intact and openable
    assert len(all_rows(sqlite3.connect(str(dst)))) == 500
    assert not (stage / "meta.sqlite.staged_ok").exists()   # not claimed current


def test_stale_tmp_from_a_killed_process_is_removed(tmp_path, monkeypatch):
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "meta.sqlite.tmp-999999").write_bytes(b"garbage" * 100)
    stage_on(monkeypatch, stage)
    R._stage_meta_local(src)
    assert not list(stage.glob("meta.sqlite.tmp-*"))


def test_verify_mismatch_refuses(tmp_path, monkeypatch):
    """Source changed under us mid-copy → the destination must not appear."""
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)
    real = shutil.copyfileobj
    monkeypatch.setattr(shutil, "copyfileobj",
                        lambda a, b, length=0: (real(a, b, length), b.write(b"X"))[0])
    with pytest.raises(RuntimeError, match="size mismatch"):
        R._stage_meta_local(src)
    assert not (stage / "meta.sqlite").exists()


def test_live_wal_refuses(tmp_path, monkeypatch):
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)
    db = sqlite3.connect(str(src))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("INSERT INTO docs VALUES (99999,'x','y',2020,'article',1,'s')")
    db.commit()                                 # commit lands in the -wal
    assert src.with_name("meta.sqlite-wal").stat().st_size > 0
    with pytest.raises(RuntimeError, match="wal"):
        R._stage_meta_local(src)
    assert not (stage / "meta.sqlite").exists()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    assert R._stage_meta_local(src) == stage / "meta.sqlite"   # clean → stages


def test_stale_sidecars_do_not_shadow_a_restage(tmp_path, monkeypatch):
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)
    R._stage_meta_local(src)
    (stage / "meta.sqlite-wal").write_bytes(b"stale wal from a previous stage")
    (stage / "meta.sqlite-shm").write_bytes(b"stale shm")
    src.unlink()
    make_meta(src, rows=ROWS[:20])
    dst = R._stage_meta_local(src)
    assert not (stage / "meta.sqlite-wal").exists()
    assert not (stage / "meta.sqlite-shm").exists()
    assert len(all_rows(sqlite3.connect(str(dst)))) == 20


def test_no_space_refuses_before_copying(tmp_path, monkeypatch):
    src = make_meta(tmp_path / "meta.sqlite")
    stage = tmp_path / "stage"
    stage_on(monkeypatch, stage)

    class VFS:
        f_bavail, f_frsize = 1, 1
    monkeypatch.setattr(R.os, "statvfs", lambda p: VFS())
    with pytest.raises(RuntimeError, match="free"):
        R._stage_meta_local(src)
    assert not (stage / "meta.sqlite").exists()


def test_bad_verify_mode_refuses(tmp_path, monkeypatch):
    src = make_meta(tmp_path / "meta.sqlite")
    stage_on(monkeypatch, tmp_path / "stage", SFU_META_STAGE_VERIFY="md5")
    with pytest.raises(ValueError):
        R._stage_meta_local(src)


# ── the served contract: identical reads, read-only connection ────────────────

def test_staged_and_unstaged_read_identically(tmp_path, monkeypatch):
    src = make_meta(tmp_path / "meta.sqlite")
    stage_on(monkeypatch, tmp_path / "stage")
    dst = R._stage_meta_local(src)
    a, b = R._connect_meta(src), R._connect_meta(dst, staged=True)
    try:
        assert all_rows(a) == all_rows(b) == sorted(ROWS)
        assert ([r[1] for r in a.execute("PRAGMA table_info(docs)")]
                == [r[1] for r in b.execute("PRAGMA table_info(docs)")])
    finally:
        a.close(); b.close()


def test_staged_connection_is_read_only_and_sidecar_free(tmp_path, monkeypatch):
    """The staged copy is opened mode=ro&immutable=1: serving cannot write it,
    and SQLite leaves no -wal/-shm in the stage dir."""
    src = make_meta(tmp_path / "meta.sqlite")
    stage_on(monkeypatch, tmp_path / "stage")
    dst = R._stage_meta_local(src)
    conn = R._connect_meta(dst, staged=True)
    assert len(all_rows(conn)) == 500
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO docs VALUES (7,'a','b',2020,'article',1,'s')")
    conn.close()
    assert sorted(p.name for p in dst.parent.iterdir()) == \
        ["meta.sqlite", "meta.sqlite.staged_ok"]


def test_unstaged_connection_keeps_the_historical_open(tmp_path):
    """The source is opened exactly as before (plain read-write handle):
    immutable=1 on a file a rebuild may replace in place would read corrupt
    pages, so the enforcement only applies to the copy we own."""
    src = make_meta(tmp_path / "meta.sqlite")
    conn = R._connect_meta(src)
    assert len(all_rows(conn)) == 500
    conn.close()


def test_retriever_load_uses_the_staged_copy(tmp_path, monkeypatch):
    """End-to-end through _load(): the retriever opens the staged file and
    metrics() reports which copy the filter stage is reading."""
    root = tmp_path / "index"
    root.mkdir()
    make_meta(root / "meta.sqlite")
    stage_on(monkeypatch, tmp_path / "stage")
    monkeypatch.setenv("SFU_DENSE_WARMCACHE", "0")
    r = R.ThinClientRetriever(index_root=str(root))
    r._load()
    assert r._meta_path == tmp_path / "stage" / "meta.sqlite"
    assert r.metrics()["meta_staged"] is True
    assert r.metrics()["meta_path"] == str(tmp_path / "stage" / "meta.sqlite")
    assert len(all_rows(r._meta)) == 500


def test_retriever_load_falls_back_when_staging_fails(tmp_path, monkeypatch):
    """A staging failure must degrade to the slow path, never fail the load."""
    root = tmp_path / "index"
    root.mkdir()
    make_meta(root / "meta.sqlite")
    stage_on(monkeypatch, tmp_path / "stage")
    monkeypatch.setenv("SFU_DENSE_WARMCACHE", "0")
    monkeypatch.setattr(R, "_stage_meta_local",
                        lambda p: (_ for _ in ()).throw(OSError("stage FS gone")))
    r = R.ThinClientRetriever(index_root=str(root))
    r._load()
    assert r._meta_path == root / "meta.sqlite"
    assert r.metrics()["meta_staged"] is False
    assert len(all_rows(r._meta)) == 500
