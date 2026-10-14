"""Doc 11 harness (`scripts/experiments/eval_delta_ingest_p2_multisection.py`):
the sample rule and the bar logic on synthetic rows. Loads no index and
names no real root.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location(
    "p2ms_h", REPO / "scripts/experiments/eval_delta_ingest_p2_multisection.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

PLANNED = {"A": 600, "B": 120, "C": 600}
IDS = [f"W{i}" for i in range(40)]


def test_header_carries_doc11_section2_verbatim():
    doc = (REPO / "docs/delta_ingest/11_P2_MULTISECTION_PREREGISTRATION.md").read_text().splitlines()
    a = next(i for i, x in enumerate(doc) if x.startswith("## 2. Measurements"))
    b = next(i for i, x in enumerate(doc) if x.startswith("## 3."))
    assert "\n".join(doc[a:b]).rstrip() in H.__doc__


def test_sample_is_seeded_stratified_and_filters_titles():
    pop = {s: [(f"{s}-{i:04d}", "one two three four" if i % 3 else "too short") for i in range(400)] for s in H.STRATA}
    a, b = H.draw_sample(pop), H.draw_sample(pop)
    assert a == b and len(a) == 600
    assert all(sum(1 for r in a if r["stratum"] == s) == 120 for s in H.STRATA)
    assert all(len(r["title"].split()) >= 4 for r in a)
    assert [r["stratum"] for r in a] == sorted(r["stratum"] for r in a)


def _rows(shift=0, drop=0, dup=0, wrong=0, n=(600, 120, 600)):
    A, C = [], []
    for i in range(n[0]):
        st = H.STRATA[i % 5]
        test_rank = None if i < drop else 3 + (shift if st == "med_bio__recent" else 0)
        A.append({"i": i, "id": f"D{i}", "stratum": st,
                  "n1": {"rank": 3, "score": 10.0, "n": 100, "dup": 0, "wrong_origin": 0},
                  "s1": {"rank": test_rank, "score": 9.5 if test_rank else None, "n": 100, "dup": dup if i == 0 else 0,
                         "wrong_origin": wrong if i == 0 else 0}})
    B = [{"i": i, "n1": {"fused_ids": IDS[:10], "bm25f10": IDS[:10], "final_ids": IDS[:10], "dup": 0, "wrong_origin": 0},
          "s1": {"fused_ids": IDS[:10], "bm25f10": IDS[:10], "final_ids": IDS[:10], "dup": 0, "wrong_origin": 0}}
         for i in range(n[1])]
    for i in range(n[2]):
        C.append({"i": i, "id": f"D{i}", "stratum": H.STRATA[i % 5],
                  "n1": {"rank": 1, "fused10": IDS[:10], "bm25f10": IDS[:10], "final_ids": IDS[:10], "dup": 0, "wrong_origin": 0},
                  "s1": {"rank": 1, "fused10": IDS[:10], "bm25f10": IDS[:10], "final_ids": IDS[:10], "dup": 0, "wrong_origin": 0}})
    return {"A": A, "B": B, "C": C, "health": {"ok": True}, "stop": None}


def test_clean_rows_pass_every_bar():
    r = H.compare(_rows(), "n1", "s1", PLANNED)
    assert r["all_bars"] and r["complete"] and r["healthy"]
    assert r["A"]["median_overall"] == 0 and r["A2"]["recall100_test"] == 1.0


def test_one_stratum_shift_fails_a_even_with_overall_median_zero():
    r = H.compare(_rows(shift=2), "n1", "s1", PLANNED)
    assert r["A"]["median_overall"] == 0 and r["A"]["median_by_stratum"]["med_bio__recent"] == 2
    assert not r["A"]["pass"] and not r["all_bars"]


def test_recall_drop_fails_a2():
    assert H.compare(_rows(drop=6), "n1", "s1", PLANNED)["A2"]["pass"]
    assert not H.compare(_rows(drop=7), "n1", "s1", PLANNED)["A2"]["pass"]


def test_displacement_bars():
    rows = _rows()
    for r in rows["B"][:7]:
        r["s1"]["fused_ids"] = IDS[10:20]
    assert not H.compare(rows, "n1", "s1", PLANNED)["B"]["pass"]
    rows = _rows()
    for r in rows["C"][:30]:
        r["s1"]["fused10"] = IDS[10:20]
    c = H.compare(rows, "n1", "s1", PLANNED)["C"]
    assert c["displaced_fused_top10"] == 300 and c["pass"]
    rows["C"][31]["s1"]["fused10"] = IDS[9:19]
    assert not H.compare(rows, "n1", "s1", PLANNED)["C"]["pass"]


def test_integrity_and_completeness():
    assert not H.compare(_rows(dup=1), "n1", "s1", PLANNED)["D"]["pass"]
    assert not H.compare(_rows(wrong=1), "n1", "s1", PLANNED)["D"]["pass"]
    assert not H.compare(_rows(n=(3, 3, 3)), "n1", "s1", PLANNED)["complete"]
    assert H.wrong_origin([("D1", 1.0, 2), ("W9", 1.0, None), ("D2", 1.0, 1)], {"D1": 1, "D2": 1}) == 1
