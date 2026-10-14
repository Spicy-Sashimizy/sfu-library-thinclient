"""L5 grouped delta shards (`SFU_SEISMIC_DELTA_GROUP`, 09 §2): fake shards, no
SEISMIC `.so` needed. Grouping is keyed on the manifest records'
`delta_generation`; the merged result equals the ungrouped one; all delta
shards run inside one pool task; under `SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1` a
raising delta shard inside the group is isolated (its siblings still serve,
it alone is marked down); without the boundary the raise propagates as today."""
import concurrent.futures as cf
import json
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

pytest.importorskip("numpy")

from lib.thinclient import sharded_seismic_backend as ssb  # noqa: E402


class FakeShard:
    def __init__(self, name, n=30, boom=False):
        self.name, self.n, self.boom = name, n, boom
        self.threads = []

    def search(self, query_id, query_components, query_values, k, query_cut, heap_factor):
        self.threads.append(threading.get_ident())
        if self.boom:
            raise RuntimeError(f"{self.name} exploded")
        h = sum(ord(c) for c in self.name)
        return [(query_id, float((h * 7919 + j * 104729) % 10007) / 10.0, f"{self.name}-{j}")
                for j in range(min(k, self.n))]


def _backend(shards, group, boundary):
    b = ssb.ParallelSeismicBackend.__new__(ssb.ParallelSeismicBackend)
    b.shards = shards
    b._shard_result_filter = None
    b._string_dtype = str
    b._fault_boundary = boundary
    b._shard_faults = [ssb._ShardFaultTracker() for _ in shards] if boundary else []
    b._shard_names = [s.name for s in shards] if boundary else []
    b._executor = cf.ThreadPoolExecutor(max_workers=len(shards))
    b._delta_group = group
    return b


def _shards(boom_at=None):
    base = [FakeShard(f"base{i}") for i in range(8)]
    delta = [FakeShard(f"g{g}", n=12, boom=(g == boom_at)) for g in range(1, 6)]
    return base + delta


def _manifest(tmp_path, n_base=8, gens=(1, 2, 3, 4, 5)):
    recs = [{"shard": i, "mmap_dir": f"/x/{i}"} for i in range(n_base)]
    recs += [{"shard": f"delta_g{g:04d}", "delta_generation": g, "mmap_dir": f"/d/{g}"} for g in gens]
    p = tmp_path / "shard_manifest.json"
    p.write_text(json.dumps({"n_shards": len(recs), "shards": recs}))
    return p


Q = {"alpha": 1.0, "beta": 0.5}


def test_group_positions_from_manifest(tmp_path, monkeypatch):
    m = str(_manifest(tmp_path))
    monkeypatch.delenv("SFU_SEISMIC_DELTA_GROUP", raising=False)
    assert ssb._delta_group_positions(m, 13) is None
    for v in ("0", "true", ""):
        monkeypatch.setenv("SFU_SEISMIC_DELTA_GROUP", v)
        assert ssb._delta_group_positions(m, 13) is None
    monkeypatch.setenv("SFU_SEISMIC_DELTA_GROUP", "1")
    assert ssb._delta_group_positions(m, 13) == [8, 9, 10, 11, 12]
    assert ssb._delta_group_positions(m, 12) is None
    assert ssb._delta_group_positions(str(_manifest(tmp_path, gens=())), 8) is None
    assert ssb._delta_group_positions("/nonexistent/m.json", 13) is None
    lst = tmp_path / "list.json"
    lst.write_text(json.dumps(["/a", "/b"]))
    assert ssb._delta_group_positions(str(lst), 2) is None


@pytest.mark.parametrize("boundary", [False, True])
def test_grouped_equals_ungrouped_and_one_task(boundary):
    plain = _backend(_shards(), None, boundary)
    grouped_shards = _shards()
    grouped = _backend(grouped_shards, [8, 9, 10, 11, 12], boundary)
    for top_k in (10, 50, 200):
        assert grouped.search_encoded(Q, top_k) == plain.search_encoded(Q, top_k)
    delta_threads = {t for s in grouped_shards[8:] for t in s.threads}
    if not boundary:
        for call in range(3):
            assert len({s.threads[call] for s in grouped_shards[8:]}) == 1
    assert delta_threads


def test_raising_delta_shard_isolated_under_fault_boundary():
    shards = _shards(boom_at=3)
    b = _backend(shards, [8, 9, 10, 11, 12], True)
    ref = _backend([s for s in _shards() if s.name != "g3"], None, False)
    assert b.search_encoded(Q, 200) == ref.search_encoded(Q, 200)
    assert b.degraded_shards() == ["g3"]
    assert all(s.threads for s in shards)


def test_raising_delta_shard_propagates_without_boundary():
    b = _backend(_shards(boom_at=2), [8, 9, 10, 11, 12], False)
    with pytest.raises(RuntimeError, match="g2 exploded"):
        b.search_encoded(Q, 50)
