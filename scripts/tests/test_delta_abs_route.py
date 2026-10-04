"""L3 routed abstract probes (`SFU_DELTA_ABS_ROUTE`, 09 §2): synthetic base +
two delta generations in a tmp tree. Routed `fetch_abstracts` returns the
same dict as the unrouted path for every id with one copy, the newest copy's
abstract for an id held by two generations, and probes no delta store for an
id the delta layer does not own."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from lib.thinclient.builder import SectionBuilder, open_meta_db  # noqa: E402
from lib.thinclient.retriever import ThinClientRetriever  # noqa: E402
from spike.delta_ingest import cli  # noqa: E402

SUBJECTS = ("quantum physics particle", "protein cell biology", "election policy voters")


@pytest.fixture
def root(tmp_path, capsys):
    root = tmp_path / "index"
    root.mkdir()
    meta = open_meta_db(root)
    b = SectionBuilder(root, "social_sciences__recent", hot=True, meta_db=meta)
    for i in range(1, 101):
        b.add({"id": f"W{i}", "title": f"policy paper {i}", "abstract": f"base abstract {i}",
               "publication_year": 2015, "type": "article", "is_oa": False, "doi": f"10.1/{i}"})
    b.finish()
    meta.commit()
    meta.close()
    (root / "manifest.json").write_text(json.dumps({"sections": {}, "persona": "all_hot"}))

    def batch(name, rows):
        p = tmp_path / name
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        cli.main(["ingest", "--source", "jsonl", "--path", str(p), "--index-root", str(root),
                  "--profile", "laptop", "--rate", "0", "--no-encode", "--no-seismic",
                  "--namespace", "local"])
        cli.main(["flush", "--force", "--index-root", str(root), "--profile", "laptop",
                  "--no-seismic"])

    batch("b1.jsonl", [{"id": f"L{i}", "title": f"{SUBJECTS[i % 3]} {i}",
                        "abstract": f"gen1 abstract {i} {SUBJECTS[i % 3]}",
                        "year": 2000 + i % 25, "type": "article"} for i in range(30)]
          + [{"id": "W5", "title": "policy paper 5 revised", "abstract": "updated W5",
              "year": 2015, "type": "article", "doi": "10.1/5"}])
    batch("b2.jsonl", [{"id": "L0", "title": f"{SUBJECTS[0]} 0", "abstract": "gen2 abstract 0",
                        "year": 2000, "type": "article"}]
          + [{"id": f"L{i}", "title": f"{SUBJECTS[i % 3]} {i}",
              "abstract": f"gen2 abstract {i} {SUBJECTS[i % 3]}",
              "year": 2001 + i % 25, "type": "article"} for i in range(30, 45)])
    capsys.readouterr()
    return root


def _retriever(root, monkeypatch, gate):
    monkeypatch.setenv("SFU_DELTA_ROOT", "1")
    if gate is None:
        monkeypatch.delenv("SFU_DELTA_ABS_ROUTE", raising=False)
    else:
        monkeypatch.setenv("SFU_DELTA_ABS_ROUTE", gate)
    tc = ThinClientRetriever(index_root=str(root), remote_abstracts=False)
    tc._load()
    return tc


def _count_probes(tc):
    calls = {}
    for name, store in tc._abstract_stores.items():
        orig = store.fetch

        def wrapped(ids, _orig=orig, _name=name):
            calls[_name] = calls.get(_name, 0) + 1
            return _orig(ids)
        store.fetch = wrapped
    return calls


def test_routed_matches_unrouted_and_skips_unowned(root, monkeypatch):
    off = _retriever(root, monkeypatch, None)
    on = _retriever(root, monkeypatch, "1")
    assert off._delta_abs_route is False and on._delta_abs_route is True
    delta_stores = [n for n in on._abstract_stores if "delta_origin" in on._sections.get(n, ())]
    assert len({n.split(":")[0] for n in delta_stores}) == 2 and len(delta_stores) >= 4
    ids = [f"W{i}" for i in range(1, 11)] + [f"local:L{i}" for i in range(45)] + ["W999999"]
    a, b = off.fetch_abstracts(ids), on.fetch_abstracts(ids)
    assert set(a) == set(b)
    diff = {k for k in a if a[k] != b[k]}
    assert diff == {"local:L0"}
    assert a["local:L0"].startswith("gen1") and b["local:L0"] == "gen2 abstract 0"
    assert b["W5"] == a["W5"]
    for i in range(1, 45):
        assert b[f"local:L{i}"].startswith("gen1" if i < 30 else "gen2")

    owners = on._delta.abstract_owner(["local:L0", "local:L1", "local:L40", "W1", "W999999"])
    assert set(owners) == {"local:L0", "local:L1", "local:L40"}
    assert owners["local:L0"][0] == 2 and owners["local:L1"][0] == 1
    for gen, section in owners.values():
        assert on._delta.section_key(gen, section) in on._abstract_stores

    calls_off, calls_on = _count_probes(off), _count_probes(on)
    off.fetch_abstracts(["W999999"])
    on.fetch_abstracts(["W999999"])
    assert sum(v for k, v in calls_off.items() if k in delta_stores) == len(delta_stores)
    assert sum(v for k, v in calls_on.items() if k in delta_stores) == 0
    calls_on.clear()
    on.fetch_abstracts(["local:L1"])
    assert sum(v for k, v in calls_on.items() if k in delta_stores) == 1


def test_gate_only_literal_one_and_no_delta(root, monkeypatch):
    for v in ("", "0", "true"):
        assert _retriever(root, monkeypatch, v)._delta_abs_route is False
    monkeypatch.delenv("SFU_DELTA_ROOT", raising=False)
    monkeypatch.setenv("SFU_DELTA_ABS_ROUTE", "1")
    tc = ThinClientRetriever(index_root=str(root), remote_abstracts=False)
    tc._load()
    assert tc._delta is None
    assert tc.fetch_abstracts(["W1", "local:L1"]) == {"W1": "base abstract 1"}
