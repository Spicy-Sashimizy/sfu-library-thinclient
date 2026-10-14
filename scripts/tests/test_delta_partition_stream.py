"""O7: OpenAlexSnapshotAdapter streams a partition instead of materialising it.

docs/delta_ingest/02_DESIGN.md §3.1 O7 (M6: peak RSS 6.74 GB from
gzip.decompress of a whole partition). The adapter must read a local or
spooled gzip stream line by line, so Python heap during iteration stays far
below the decompressed partition size, and must never touch `.content` of a
partition response.
"""
import gzip
import json
import sys
import tracemalloc
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

from spike.delta_ingest.adapters import OpenAlexSnapshotAdapter  # noqa: E402

PART = "updated_date=2026-09-15/part_0001.gz"
MANIFEST = "https://example.invalid/manifest.json"
PART_URL = f"s3://openalex/data/jsonl/works/{PART}"
DELETED_URL = "https://example.invalid/deleted_ids.csv.gz"


def _work(i: int) -> dict:
    words = " ".join(f"w{i}x{j}" for j in range(60))
    return {"id": f"https://openalex.org/W{1000 + i}", "title": f"title {i}",
            "abstract_inverted_index": {w: [k] for k, w in enumerate(words.split())},
            "publication_year": 2009 if i % 7 == 0 else 2020, "type": "article",
            "open_access": {"is_oa": i % 2 == 0}, "doi": f"https://doi.org/10.1/{i}",
            "updated_date": "2026-09-15", "cited_by_count": i, "padding": "p" * 400}


def _make_partition(path: Path, n: int) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps(_work(i)) + "\n")
            if i == 3:
                fh.write("\n{not json\n")
    return path


def _make_deleted(path: Path) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("work_id,deleted_date\nW1,2026-09-01\nW2,2026-09-20\n")
    return path


class _StreamResp:
    def __init__(self, path: Path | None = None, body: bytes | None = None):
        self._path = path
        self._body = body
        self.status_code = 200

    def raise_for_status(self):
        return None

    @property
    def content(self):
        if self._path is not None:
            raise AssertionError("partition response materialised via .content")
        return self._body

    def iter_content(self, chunk_size=1 << 20):
        with open(self._path, "rb") as fh:
            while chunk := fh.read(chunk_size):
                yield chunk

    def close(self):
        return None


class _Session:
    def __init__(self, files: dict[str, Path], manifest_urls: list[str]):
        self.files = files
        self.manifest = json.dumps({"entries": [{"url": u} for u in manifest_urls]}).encode()
        self.stream_calls = 0

    def get(self, url, stream=False, **kw):
        if url == MANIFEST:
            return _StreamResp(body=self.manifest)
        if url.startswith("s3://"):
            raise AssertionError("s3 url not mapped to https")
        for key, path in self.files.items():
            if url.endswith(key):
                assert stream, "partition fetched without stream=True"
                self.stream_calls += 1
                return _StreamResp(path=path)
        raise FileNotFoundError(url)


def _ids(adapter, state):
    return [r.id for r in adapter.iter_records(state)]


def test_stream_spooled_partition_matches_and_never_materialises(tmp_path):
    part = _make_partition(tmp_path / "p.gz", 50)
    sess = _Session({PART: part}, [PART_URL])
    spool = tmp_path / "spool"
    ad = OpenAlexSnapshotAdapter(sess, manifest_url=MANIFEST, spool_dir=spool)
    state: dict = {}
    ids = _ids(ad, state)
    expected = [f"W{1000 + i}" for i in range(50) if i % 7 != 0]
    assert ids == expected
    assert sess.stream_calls == 1
    assert state["synced"] == [PART]
    assert state["watermark"] == "2026-09-15"
    assert list(spool.iterdir()) == []


def test_local_partition_path_in_manifest_is_read_in_place(tmp_path):
    part = _make_partition(tmp_path / "updated_date=2026-09-15_part_0001.gz", 20)
    sess = _Session({}, [str(part)])
    ad = OpenAlexSnapshotAdapter(sess, manifest_url=MANIFEST, min_year=None)
    assert len(_ids(ad, {})) == 20
    sess2 = _Session({}, [part.as_uri()])
    ad2 = OpenAlexSnapshotAdapter(sess2, manifest_url=MANIFEST, min_year=None)
    assert len(_ids(ad2, {})) == 20


def test_python_heap_bounded_while_streaming(tmp_path):
    n = 6000
    part = _make_partition(tmp_path / "big.gz", n)
    raw_bytes = sum(len(json.dumps(_work(i))) + 1 for i in range(n))
    assert raw_bytes > 8 * 1024 * 1024
    sess = _Session({PART: part}, [PART_URL])
    ad = OpenAlexSnapshotAdapter(sess, manifest_url=MANIFEST, spool_dir=tmp_path / "sp", min_year=None)
    tracemalloc.start()
    try:
        count = 0
        for _ in ad.iter_records({}):
            count += 1
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == n
    assert peak < raw_bytes / 4, (peak, raw_bytes)


def test_deletions_streamed(tmp_path):
    dele = _make_deleted(tmp_path / "d.gz")
    sess = _Session({"deleted_ids.csv.gz": dele}, [])
    ad = OpenAlexSnapshotAdapter(sess, manifest_url=MANIFEST, deleted_ids_url=DELETED_URL,
                                 spool_dir=tmp_path / "sp")
    state = {"deleted_since": "2026-09-10"}
    assert list(ad.iter_deletions(state)) == ["W2"]
    assert state["deleted_since"] == "2026-09-20"


def test_failed_spool_download_retries_and_cleans(tmp_path):
    part = _make_partition(tmp_path / "p.gz", 5)

    class Flaky(_Session):
        fails = 1

        def get(self, url, stream=False, **kw):
            if url.endswith(PART) and self.fails:
                self.fails -= 1
                raise ConnectionError("boom")
            return super().get(url, stream=stream, **kw)

    sess = Flaky({PART: part}, [PART_URL])
    spool = tmp_path / "spool"
    ad = OpenAlexSnapshotAdapter(sess, manifest_url=MANIFEST, spool_dir=spool, min_year=None,
                                 retry_sleep_s=0)
    assert len(_ids(ad, {})) == 5
    assert list(spool.iterdir()) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
