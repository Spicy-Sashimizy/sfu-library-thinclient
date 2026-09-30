"""Contract pins for scripts/seismic_testbed/wslrh_convergence_ladder.py
(PREREGISTRATION_WSL2_REHOST.md §6 gap 2), with the backend MOCKED: no index
is loaded, no cell runs, no cgroup is needed. What is pinned:

  * F5 (`--f5-release-except`) calls the fork hook with exactly the extents
    `prefault_hotset()` would prefault from the sidecar (budget clamp +
    `_coalesce_extents`), records `requested_bytes` / `released_bytes` /
    `write_status` / `elapsed_s` and RssFile + hot_resident_pct pre/post in
    the SAME shape as the L3 `postload_reclaim` block, and names the hook
    scope (pre-fix `.so` => `forward_slab_only_prefix_hook`);
  * L3 (`--postload-reclaim-bytes`) block is the t23 block plus the shared
    residency keys; F5 and L3 are one lever each (both => exit 2);
  * L0 output is a superset of the judged R2 driver's keys (comparability);
  * the arm/lru_gen mismatch exits 4 before the index is touched; a missing
    F5 sidecar exits 5.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DRIVER = REPO / "scripts" / "seismic_testbed" / "wslrh_convergence_ladder.py"
sys.path.insert(0, str(REPO / "src"))

R2_KEYS = {"probe", "date", "cap", "cgroup_memory_max", "manifest", "queries",
           "top_k", "load_s", "prefault_gate", "convergence",
           "converged_state", "cg_load_delta", "cg_postload_gauges",
           "per_pass", "swap_confounded", "vmswap_kb_max"}
LEVER_BLOCK_KEYS = {"requested_bytes", "freed_bytes", "write_status",
                    "pre_gauges", "post_gauges", "elapsed_s", "rssfile_pre",
                    "rssfile_post", "hot_resident_pct_pre",
                    "hot_resident_pct_post", "hot_pages_total",
                    "hot_pages_resident_pre", "hot_pages_resident_post"}
SIDECAR_EXTENTS = [[0, 3], [4, 1], [6, 1], [40, 2], [100, 4]]
N_PAGES = 128


@pytest.fixture(scope="module")
def wslrh():
    spec = importlib.util.spec_from_file_location("wslrh_driver", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeIndexPrefix:
    """Pre-scope-fix hook surface: release_pages_except only (the served .so
    as of 2026-09-29)."""

    def __init__(self):
        self.calls = []

    def release_pages_except(self, extents, keep_structural=False):
        self.calls.append((list(extents), keep_structural))
        return 12345


class FakeIndexFixed(FakeIndexPrefix):
    def release_pages_except_by_slab(self, extents, keep_structural=False):
        self.calls.append((list(extents), keep_structural))
        return [("forward_values", 1000), ("postings", 2000),
                ("doc_strings", 300)]


class FakeBackend:
    def __init__(self, shards, dirs):
        self.shards = shards
        self._shard_mmap_dirs = dirs

    def search_encoded(self, q, k):
        return [("W1", 1.0), ("W2", 0.5)]


def make_shard(tmp_path: Path, name: str) -> Path:
    d = tmp_path / f"{name}.dotvbyte.e5.v2.mmap"
    d.mkdir()
    (d / "forward_data.bin").write_bytes(b"\x01" * (N_PAGES * 4096))
    (d / "forward_offsets.bin").write_bytes(b"\x02" * 8192)
    (d / "posting_lists.bin").write_bytes(b"\x03" * 16384)
    vk = {"forward_format": "dotvbyte_fixedu8", "forward_format_version": 2,
          "forward_reordered": "block_walk_canonical",
          "forward_data_words": N_PAGES * 512}
    (d / "manifest.json").write_text(json.dumps(vk))
    (d / "hotset_hot50_1.6gb.json").write_text(json.dumps(
        {"schema": "seismic.hotset.v1", "budget_bytes_per_shard": 10 ** 9,
         "page_size": 4096, "version_keys": vk, "extents": SIDECAR_EXTENTS}))
    return d


@pytest.fixture
def cell_env(tmp_path, monkeypatch, wslrh):
    """A fake cgroup dir, a fake lru_gen file reading 0x0007, and a backend
    factory patched into the module the driver imports from."""
    cg = tmp_path / "cg"
    cg.mkdir()
    (cg / "memory.stat").write_text(
        "anon 1000\nfile 5000\nfile_mapped 4000\nactive_file 2000\n"
        "inactive_file 3000\nunevictable 0\npgfault 10\npgmajfault 5\n"
        "pgscan 0\npgsteal 0\nworkingset_refault_file 0\n")
    (cg / "memory.current").write_text("6000\n")
    (cg / "memory.max").write_text("12884901888\n")
    (cg / "memory.reclaim").write_text("")
    lru = tmp_path / "lru_gen_enabled"
    lru.write_text("0x0007\n")
    monkeypatch.setattr(wslrh, "CG", cg)
    monkeypatch.setattr(wslrh, "LRU_GEN", lru)
    shard_dirs = [make_shard(tmp_path, "s0"), make_shard(tmp_path, "s1")]

    def install(index_cls):
        idxs = [index_cls() for _ in shard_dirs]
        fb = FakeBackend(idxs, [str(d) for d in shard_dirs])
        import lib.thinclient.sharded_seismic_backend as backend
        monkeypatch.setattr(backend.HybridSeismicBackend, "from_manifest",
                            classmethod(lambda cls, *a, **k: fb))
        return fb

    return {"cg": cg, "lru": lru, "shards": shard_dirs, "install": install,
            "tmp": tmp_path}


def run_cell(wslrh, tmp_path, extra, arm="mglru"):
    out = tmp_path / "cell.json"
    argv = ["--arm", arm, "--cap-label", "12g", "--replicate", "1",
            "--min-passes", "1", "--max-passes", "2", "--queries", "2",
            "--result-file", str(out)] + extra
    wslrh.main(argv)
    return json.loads(out.read_text())


def expected_extents(wslrh):
    from lib.thinclient.sharded_seismic_backend import _coalesce_extents
    return [tuple(e) for e in _coalesce_extents(
        [tuple(e) for e in SIDECAR_EXTENTS])]


def test_l0_is_a_superset_of_r2_and_carries_rehost(wslrh, cell_env):
    cell_env["install"](FakeIndexPrefix)
    d = run_cell(wslrh, cell_env["tmp"], [])
    assert R2_KEYS <= set(d)
    assert d["probe"] == "wslrh_convergence_ladder"
    assert d["lever"] == "L0" and d["rehost"]["lever"] == "L0"
    assert "f5_release" not in d and "postload_reclaim" not in d
    assert d["rehost"]["f5_release"]["write_status"] == "off"
    assert d["rehost"]["cap_gb"] == 12.0 and d["rehost"]["arm"] == "mglru"
    assert d["rehost"]["classification"] in ("near-zero", "transient", "plateau")
    assert d["cgroup_memory_max"] == "12884901888"
    assert d["rehost"]["constants"]["lower_boundary_gb"] == 11.3


def test_f5_prefix_hook_block_shape_and_extents(wslrh, cell_env):
    fb = cell_env["install"](FakeIndexPrefix)
    d = run_cell(wslrh, cell_env["tmp"],
                 ["--f5-release-except", "hotset_hot50_1.6gb.json"])
    f5 = d["f5_release"]
    assert d["lever"] == "F5" and d["rehost"]["f5_release"] == f5
    assert LEVER_BLOCK_KEYS <= set(f5)
    assert f5["write_status"] == "ok"
    assert f5["released_bytes"] == 12345 * len(fb.shards)
    assert f5["scope"] == "forward_slab_only_prefix_hook"
    assert f5["scope_fix_present"] is False and f5["by_slab"] is None
    ext = expected_extents(wslrh)
    for idx in fb.shards:
        assert idx.calls == [(ext, False)]
    kept_pages = sum(ln for _, ln in ext)
    assert f5["kept_bytes"] == kept_pages * 4096 * len(fb.shards)
    assert f5["kept_extents"] == len(ext) * len(fb.shards)
    assert f5["requested_bytes"] == (N_PAGES * 4096 - kept_pages * 4096) * len(fb.shards)
    assert f5["hot_pages_total"] == kept_pages * len(fb.shards)
    for k in ("hot_resident_pct_pre", "hot_resident_pct_post"):
        assert f5[k] is not None and 0.0 <= f5[k] <= 100.0
    assert f5["rssfile_pre"] is not None and f5["rssfile_post"] is not None
    assert f5["elapsed_s"] >= 0.0
    assert f5["freed_bytes"] == 0
    assert f5["sidecar"] == "hotset_hot50_1.6gb.json"


def test_f5_fixed_hook_records_by_slab_and_all_slab_scope(wslrh, cell_env):
    fb = cell_env["install"](FakeIndexFixed)
    sidecar_path = cell_env["shards"][0] / "hotset_hot50_1.6gb.json"
    d = run_cell(wslrh, cell_env["tmp"], ["--f5-release-except", str(sidecar_path)])
    f5 = d["f5_release"]
    assert f5["scope"] == "all_slabs" and f5["scope_fix_present"] is True
    assert f5["by_slab"] == {"forward_values": 2000, "postings": 4000,
                             "doc_strings": 600}
    assert f5["released_bytes"] == 3300 * len(fb.shards)
    kept = sum(ln for _, ln in expected_extents(wslrh)) * 4096
    per_shard_slabs = N_PAGES * 4096 + 8192 + 16384
    assert f5["requested_bytes"] == (per_shard_slabs - kept) * len(fb.shards)


def test_l3_block_matches_f5_shape(wslrh, cell_env):
    cell_env["install"](FakeIndexPrefix)
    d = run_cell(wslrh, cell_env["tmp"], ["--postload-reclaim-bytes", "9300000000"])
    r = d["postload_reclaim"]
    assert d["lever"] == "L3" and d["rehost"]["lever"] == "L3"
    assert LEVER_BLOCK_KEYS <= set(r)
    assert r["requested_bytes"] == 9300000000
    assert r["write_status"] == "ok"
    assert (cell_env["cg"] / "memory.reclaim").read_text() == "9300000000"
    assert r["hot_pages_total"] > 0 and r["hot_resident_pct_pre"] is not None
    assert d["rehost"]["f5_release"]["write_status"] == "off"


def test_two_levers_in_one_cell_exit_2(wslrh, cell_env):
    cell_env["install"](FakeIndexPrefix)
    with pytest.raises(SystemExit) as e:
        run_cell(wslrh, cell_env["tmp"],
                 ["--postload-reclaim-bytes", "1", "--f5-release-except", "x.json"])
    assert e.value.code == 2


def test_arm_mismatch_exits_4_before_load(wslrh, cell_env):
    fb = cell_env["install"](FakeIndexPrefix)
    with pytest.raises(SystemExit) as e:
        run_cell(wslrh, cell_env["tmp"], [], arm="classic")
    assert e.value.code == 4
    assert all(idx.calls == [] for idx in fb.shards)


def test_f5_missing_sidecar_exits_5(wslrh, cell_env):
    cell_env["install"](FakeIndexPrefix)
    with pytest.raises(SystemExit) as e:
        run_cell(wslrh, cell_env["tmp"], ["--f5-release-except", "hotset_nope.json"])
    assert e.value.code == 5


def test_classifier_constants(wslrh):
    near = [{"p50_ms": 500.0}, {"p50_ms": 30.0}, {"p50_ms": 20.0}]
    assert wslrh.classify(near, "near_zero", 2500) == "near-zero"
    trans = [{"p50_ms": 500.0}, {"p50_ms": 300.0}, {"p50_ms": 20.0}]
    assert wslrh.classify(trans, "near_zero", 2500) == "transient"
    assert wslrh.classify(trans, "plateau", 2500) == "plateau"
    assert wslrh.classify(trans, "maxpass", 2500) == "plateau"
    assert wslrh.cap_gb_from_label("12g") == 12.0
    assert wslrh.cap_gb_from_label("cap22g") == 22.0
