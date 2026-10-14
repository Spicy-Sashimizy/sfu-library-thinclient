#!/usr/bin/env python3
"""Delta-ingest M7-seed: base-hash seed for the ingest ledger (issue O4 of
docs/delta_ingest/02_DESIGN.md §3.1, the UNBUILT item of §4 item 1) and a
re-classification of the M7 partitions against the seeded ledger; adapter
fixes O5 (DOI prefix) and O6 (min_year) quantified on the same files.

PRE-REGISTERED 2026-09-30 (~18:05Z), written and committed before the first
measured run.

Context (M7 row of 03_SPIKE_PLAN.md, bar verbatim: "recorded; expectation from
research >= 10:1 touched:changed -- if it is < 3:1 the design's
write-amplification argument is wrong"; M7 verdict FAIL). M7's ledger held no
base hashes, so every in-base id classified "updated" (1.00:1). M7's exact
proxy on the one section with a local abstract sidecar
(social_sciences__recent, 9,965 in-base in-slice docs of the primary file):
encoder text changed for 2,517 (25.3%) -> 3.959:1 among in-base docs;
content_hash changed for 8,047 (80.8%, DOI prefix-stripped) -> 1.238:1.
Supplementary file: 10,843 compared, 3,182 encode changed -> 3.408:1.

EXPECTATION (pre-registered, from the dispatch): the seeded-ledger ratio for
in-base docs agrees with M7's exact proxy.
  primary     : on the primary file, seeded subset (min_year=2015 arm, the
                M7-identical in-slice set), ratio R_enc = touched_seeded /
                encode_hash_changed_vs_seed. PASS iff |R_enc / 3.959 - 1| <= 0.02.
                A FAIL is recorded as a FAIL.
  secondary   : the same on the supplementary file vs 3.408 (same +-2% rule).
  consistency : encode_hash_changed count == M7's 2,517 (resp. 3,182) exactly
                (same meta, same sidecar, same partition, same normalisation of
                the encoder text; any difference is a bug to explain).
  recorded    : content_hash-changed (what `classify` calls "updated") vs
                encode_hash-changed separately, per-field attribution of
                content-only changes (is_oa, type, year, doi, title/abstract),
                and the touched:must-encode ratio both as coded (classify: new
                + updated are re-encoded, because `reusable_sparse` finds no
                stored vector for a base doc) and encode-aware (new + updated
                whose encode hash differs from the seed).

Operational definitions (fixed before the run):
  files       : /var/tmp/sfu_delta_B_20260929/works_updated_date=2026-09-15_part_0001.gz
                (primary), ..._2026-09-22_part_0054.gz (supplementary). Read
                locally, streamed line by line (NOT through
                OpenAlexSnapshotAdapter, which decompresses the whole partition
                into memory, O7); the adapter's slice rule is reproduced
                exactly: year gate `min_year is not None and isinstance(year,
                int) and year < min_year`, then `normalize_openalex_work(work,
                source="openalex_snapshot")` (is_xpac, abstract >= 50 chars,
                W-id; DOI through `records.normalize_doi`, i.e. O5 applied).
  arms        : slice at min_year=2015 (M7-identical set; primary verdict) and
                at min_year=2010 (the new default, O6).
  base        : data/thinclient_index/meta.sqlite over the 9p mount, read-only
                (SFU_META_STAGE_DIR forced blank; no local meta copy exists);
                abstracts from sections/social_sciences__recent/abstracts.sqlite
                (+ .flat, ordinal locator), read-only. No other section keeps a
                local sidecar (they are packed tar.zst archives).
  seed set    : in-slice (min_year=2010, superset of 2015) ids of the file that
                BaseIndex.contains() and whose meta section is
                social_sciences__recent. Seeded with `BaseSeeder.seed_ids` into
                a fresh ledger /home/vscode/work/delta_ingest/seed/ledger_<file>.sqlite.
  classify    : `IngestLedger.classify` in 5,000-record batches over the whole
                in-slice stream of each arm, in_base from BaseIndex.contains.
                "seeded subset" = in-slice records whose id was seeded.
  throughput  : T1 = the primary seed_ids call above (random ids, cold-ish);
                T2 = seed_range over a contiguous meta id range starting at
                W2000000000, first 300,000 meta rows, all sections scanned,
                only the hot section seeded (others skipped + counted), into a
                fresh ledger; T2w = the same range repeated into another fresh
                ledger (page cache warm). docs/s, meta rows/s, /proc/self/io
                rchar, majflt, maxrss, ledger bytes per seeded row.
                Extrapolation to 150,413,098 docs is *est.* with the
                assumption stated in the results file (per-doc cost of T2 on
                the hot section applies to every section once its sidecar is
                local). Local-copy arm: NOT RUN if no local copy of meta /
                sidecar exists at run time (checked and recorded).
  REVISION 2026-09-30 ~18:08Z, before the first measured run (bars
  unchanged): the extrapolation uses per-stage timers added to BaseSeeder
  (meta_s per meta row + abstract_fetch_s/hash_s/ledger_write_s per seeded
  doc), because wall/seeded over-charges the ~80% of scanned rows that are
  skipped (no local sidecar); the naive wall/seeded figure is kept too.
  host        : nice -n 10 taskset -c 8-15, shared host (B7 on 0-7, S0-2 on
                8-15). Every wall/throughput field carries timings_valid=false.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "source"))
sys.path.insert(0, str(REPO_ROOT))

os.environ["SFU_META_STAGE_DIR"] = ""
os.environ["SFU_SEISMIC_STAGE_DIR"] = ""
os.environ["SFU_DELTA_ROOT"] = ""

from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger, hash64  # noqa: E402
from spike.delta_ingest.records import (  # noqa: E402
    DocRecord, canonical_id, normalize_doi, normalize_openalex_work)
from spike.delta_ingest.seed import BaseSeeder, resolve_meta  # noqa: E402

HOT = "social_sciences__recent"
WORK = Path("/home/vscode/work/delta_ingest/seed")
PARTS = {
    "primary": ("/var/tmp/sfu_delta_B_20260929/works_updated_date=2026-09-15_part_0001.gz",
                {"hot_compared": 9965, "encode_changed": 2517, "content_changed": 8047, "ratio": 3.959}),
    "supplementary": ("/var/tmp/sfu_delta_B_20260929/works_updated_date=2026-09-22_part_0054.gz",
                      {"hot_compared": 10843, "encode_changed": 3182, "content_changed": 8809, "ratio": 3.408}),
}
TIMING_NOTE = ("shared host: B7 latency run on cores 0-7, S0-2 (~19 GB) on cores 8-15, this run "
               "nice 10 on 8-15; 9p reads; timings are indicative only")


def stream(path: str, min_year: int | None):
    """Yield (DocRecord|None, raw_id, year) per line with the adapter's slice rule."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                w = json.loads(line)
            except json.JSONDecodeError:
                continue
            year = w.get("publication_year")
            wid = canonical_id("openalex", w.get("id") or "")
            if min_year is not None and isinstance(year, int) and year < min_year:
                yield None, wid, year
                continue
            yield normalize_openalex_work(w, source="openalex_snapshot"), wid, year


def pass1(path: str, base: BaseIndex, meta_db) -> dict:
    """Slice sets at 2010 and 2015, base membership, meta rows for in-base ids."""
    s2010, s2015, allids = set(), set(), []
    years = {}
    for rec, wid, year in stream(path, 2010):
        allids.append(wid)
        years[wid] = year
        if rec is not None:
            s2010.add(rec.id)
            if not (isinstance(year, int) and year < 2015):
                s2015.add(rec.id)
    in_base = {}
    for i in range(0, len(allids), 5000):
        in_base.update(base.contains(allids[i:i + 5000]))
    ib = [w for w in s2010 if in_base.get(w)]
    rows = {}
    nums = sorted(int(w[1:]) for w in ib)
    for i in range(0, len(nums), 500):
        sub = nums[i:i + 500]
        for r in meta_db.execute(f"SELECT id,title,doi,year,type,is_oa,section FROM docs WHERE id IN "
                                 f"({','.join('?' * len(sub))})", sub):
            rows[f"W{r[0]}"] = r
    return {"s2010": s2010, "s2015": s2015, "in_base": in_base, "years": years, "rows": rows,
            "lines": len(allids)}


def o6_report(p1: dict) -> dict:
    """In-base ids dropped by each year gate (all lines, before other slice rules)."""
    c = collections.Counter()
    ydist = collections.Counter()
    for wid, y in p1["years"].items():
        if not p1["in_base"].get(wid) or not isinstance(y, int):
            continue
        if y < 2015:
            c["in_base_year_lt_2015"] += 1
            ydist[y] += 1
        if y < 2010:
            c["in_base_year_lt_2010"] += 1
    c["in_slice_2015"] = len(p1["s2015"])
    c["in_slice_2010"] = len(p1["s2010"])
    c["in_slice_in_base_2015"] = sum(1 for w in p1["s2015"] if p1["in_base"].get(w))
    c["in_slice_in_base_2010"] = sum(1 for w in p1["s2010"] if p1["in_base"].get(w))
    return {**dict(c), "in_base_year_lt_2015_by_year": {str(k): v for k, v in sorted(ydist.items())}}


def classify_arm(path: str, min_year: int, p1: dict, led: IngestLedger, seeded: set,
                 base_recs: dict) -> dict:
    tot = collections.Counter()
    sub = collections.Counter()
    o5 = collections.Counter()
    fields = collections.Counter()
    batch: list[DocRecord] = []

    def flush():
        if not batch:
            return
        ib = {r.id: bool(p1["in_base"].get(r.id)) for r in batch}
        for r in batch:
            row = p1["rows"].get(r.id)
            if row is not None:
                o5["in_base_compared"] += 1
                o5["doi_diff_raw_base_vs_normalized_record"] += (row[2] or "") != r.doi
                o5["doi_diff_both_normalize_doi"] += normalize_doi(row[2]) != r.doi
        cls = led.classify(batch, ib)
        bk = led.base_known([r.id for r in batch if r.id in seeded])
        for k, v in cls.items():
            tot[k] += len(v)
            for r in v:
                if r.id not in seeded:
                    continue
                sub[k] += 1
                enc_changed = bk[r.id][1] != hash64(r.encode_hash())
                sub["encode_changed"] += enc_changed
                if k == "updated" and not enc_changed:
                    sub["updated_content_only"] += 1
                    b = base_recs.get(r.id)
                    if b is not None:
                        for f in ("year", "type", "is_oa", "doi"):
                            fields[f"content_only_{f}_differs"] += getattr(r, f) != getattr(b, f)
                        diffs = tuple(f for f in ("year", "type", "is_oa", "doi") if getattr(r, f) != getattr(b, f))
                        fields["content_only_combo:" + ("+".join(diffs) or "none")] += 1
                if k == "unchanged" and enc_changed:
                    sub["unchanged_but_encode_changed_BUG"] += 1
        batch.clear()

    for rec, _wid, _y in stream(path, min_year):
        if rec is None:
            continue
        batch.append(rec)
        if len(batch) >= 5000:
            flush()
    flush()

    def ratio(a, b):
        return round(a / b, 4) if b else None

    touched_seeded = sub["new"] + sub["updated"] + sub["unchanged"]
    in_slice = tot["new"] + tot["updated"] + tot["unchanged"]
    must_coded = tot["new"] + tot["updated"]
    must_enc_aware = tot["new"] + (tot["updated"] - sub["updated_content_only"])
    return {
        "min_year": min_year,
        "classify_all_in_slice": dict(tot),
        "seeded_subset": dict(sub),
        "seeded_subset_touched": touched_seeded,
        "content_only_field_attribution": dict(fields),
        "o5_doi_all_in_base": dict(o5),
        "ratio_seeded_touched_to_encode_changed": ratio(touched_seeded, sub["encode_changed"]),
        "ratio_seeded_touched_to_content_changed_as_coded": ratio(touched_seeded, sub["updated"]),
        "in_slice_touched": in_slice,
        "must_encode_as_coded": must_coded,
        "must_encode_encode_aware": must_enc_aware,
        "ratio_in_slice_touched_to_must_encode_as_coded": ratio(in_slice, must_coded),
        "ratio_in_slice_touched_to_must_encode_encode_aware": ratio(in_slice, must_enc_aware),
        "note": ("only the hot section is seeded: in-base ids outside it have no base hash and "
                 "stay 'updated' (as coded); whole-partition ratios are therefore partial-seed numbers"),
    }


def fresh(path: Path) -> IngestLedger:
    for suf in ("", "-wal", "-shm"):
        p = Path(str(path) + suf)
        if p.exists():
            p.unlink()
    return IngestLedger(path)


def ledger_bytes_per_row(path: Path, rows: int) -> dict:
    led = IngestLedger(path)
    led.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    pages = led.db.execute("SELECT COUNT(*) FROM dbstat WHERE name='base_hashes'").fetchone()[0] \
        if _has_dbstat(led) else None
    psize = led.db.execute("PRAGMA page_size").fetchone()[0]
    led.close()
    size = path.stat().st_size
    out = {"ledger_file_bytes": size, "rows": rows,
           "file_bytes_per_row": round(size / rows, 2) if rows else None}
    if pages is not None:
        out["base_hashes_table_bytes"] = pages * psize
        out["table_bytes_per_row"] = round(pages * psize / rows, 2) if rows else None
    return out


def _has_dbstat(led: IngestLedger) -> bool:
    try:
        led.db.execute("SELECT 1 FROM dbstat LIMIT 1").fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index-root", default=str(REPO_ROOT / "data" / "thinclient_index"))
    ap.add_argument("--out", default=str(REPO_ROOT / "data/eval_results/delta_ingest_M7seed_20260930.json"))
    ap.add_argument("--t2-lo", type=int, default=2_000_000_000)
    ap.add_argument("--t2-rows", type=int, default=300_000)
    ap.add_argument("--parts", default="primary,supplementary")
    args = ap.parse_args(argv)

    assert os.environ.get("SFU_META_STAGE_DIR") == "" and os.environ.get("SFU_SEISMIC_STAGE_DIR") == ""
    WORK.mkdir(parents=True, exist_ok=True)
    index_root = Path(args.index_root)
    meta_path = resolve_meta(index_root)
    assert meta_path == index_root / "meta.sqlite", meta_path
    local_copies = subprocess.run(
        ["find", "/var/tmp", "/home/vscode/work", "-maxdepth", "4", "(", "-name", "meta.sqlite",
         "-o", "-name", "blocks.bin", ")", "-size", "+1G"],
        capture_output=True, text=True).stdout.split()
    data_before = {p.name for p in (index_root / "sections" / HOT).iterdir()} | \
        {p.name for p in index_root.iterdir()}
    import sqlite3
    meta_db = sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True, timeout=60)
    base = BaseIndex(index_root)
    t_start = time.time()
    out = {
        "measurement": "M7-seed: base-hash seed for the ingest ledger (O4) + O5/O6, M7 partitions reclassified",
        "date": "2026-09-30",
        "git_commit_at_run": subprocess.check_output(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                                                     text=True).strip(),
        "expectation_verbatim": ("the seeded-ledger ratio for in-base docs agrees with M7's exact proxy "
                                 "(encoder text changed 25.3% -> about 3.96:1 among in-base docs on that subset)"),
        "pass_rule": "|R_enc / M7 ratio - 1| <= 0.02 (primary file, min_year=2015 arm); consistency: counts equal",
        "meta_path": str(meta_path), "meta_over_9p": True,
        "local_copy_search": local_copies,
        "timings_valid": False, "timings_note": TIMING_NOTE,
        "parts": {},
    }

    for name in [p for p in args.parts.split(",") if p]:
        path, m7 = PARTS[name]
        t0 = time.time()
        p1 = pass1(path, base, meta_db)
        t1 = time.time()
        seed_ids = sorted(w for w, r in p1["rows"].items() if r[6] == HOT)
        led_path = WORK / f"ledger_{name}.sqlite"
        led = fresh(led_path)
        seeder = BaseSeeder(index_root, led, meta_path=meta_path)
        rep = seeder.seed_ids(seed_ids)
        t2 = time.time()
        seeded = set(seed_ids)
        base_recs = {r.id: r for r in seeder.records_for_rows([p1["rows"][w] for w in seed_ids])}
        seeder.close()
        seeded_hot_2015 = sum(1 for w in seed_ids if w in p1["s2015"])
        arms = {}
        for my in (2015, 2010):
            arms[str(my)] = classify_arm(path, my, p1, led, seeded, base_recs)
        t3 = time.time()
        a = arms["2015"]
        r_enc = a["ratio_seeded_touched_to_encode_changed"]
        verdict = ("PASS" if r_enc and abs(r_enc / m7["ratio"] - 1) <= 0.02 else "FAIL")
        out["parts"][name] = {
            "file": path,
            "lines": p1["lines"],
            "o6_year_gate": o6_report(p1),
            "seed_set": {"ids": len(seed_ids), "of_which_in_slice_2015": seeded_hot_2015,
                         "m7_hot_compared": m7["hot_compared"]},
            "seed_call": rep,
            "seed_docs_per_s": round(rep["stats"].get("seeded", 0) / rep["wall_s"], 1) if rep["wall_s"] else None,
            "arms": arms,
            "m7_reference": m7,
            "consistency": {
                "encode_changed_equals_m7": a["seeded_subset"].get("encode_changed") == m7["encode_changed"],
                "seeded_subset_touched_equals_m7_compared": a["seeded_subset_touched"] == m7["hot_compared"],
                "content_changed_as_coded_vs_m7": [a["seeded_subset"].get("updated"), m7["content_changed"]],
            },
            "verdict_vs_m7_ratio": verdict,
            "wall_s": {"pass1": round(t1 - t0, 1), "seed": round(t2 - t1, 1), "classify_both_arms": round(t3 - t2, 1)},
            "ledger_size": ledger_bytes_per_row(led_path, rep["stats"].get("seeded", 0)),
        }
        led.close()
        print(json.dumps({name: {"verdict": verdict, "r_enc": r_enc, "seeded": rep["stats"]}}), flush=True)

    t2s = {}
    for tag in ("T2", "T2w"):
        lp = WORK / f"ledger_{tag}.sqlite"
        led = fresh(lp)
        s = BaseSeeder(index_root, led, meta_path=meta_path)
        rep = s.seed_range(args.t2_lo, 1 << 62, limit=args.t2_rows)
        s.close()
        led.close()
        st = rep["stats"]
        rep["meta_rows_per_s"] = round(st.get("meta_rows", 0) / rep["wall_s"], 1) if rep["wall_s"] else None
        rep["seeded_docs_per_s"] = round(st.get("seeded", 0) / rep["wall_s"], 1) if rep["wall_s"] else None
        rep["ledger_size"] = ledger_bytes_per_row(lp, st.get("seeded", 0))
        t2s[tag] = rep
        print(json.dumps({tag: {k: rep[k] for k in ("wall_s", "meta_rows_per_s", "seeded_docs_per_s")}}), flush=True)
    out["throughput"] = {"range_lo": args.t2_lo, "rows_limit": args.t2_rows, **t2s,
                         "local_copy_arm": "NOT RUN: no local copy of meta.sqlite or the hot sidecar exists "
                                           "(searched /var/tmp, /home/vscode/work; SFU_META_STAGE_DIR unset in .env)"
                         if not local_copies else f"local copies found but not used: {local_copies}"}

    N = 150_413_098
    t2 = t2s["T2"]
    st = t2["stats"]
    wall = t2["wall_s"]
    seeded = st.get("seeded", 0)
    rows = st.get("meta_rows", 0)
    io_ = t2["io_delta"]
    if seeded and rows:
        tm = t2["timers_s"]
        meta_per_row = tm.get("meta_s", 0) / rows
        rest_per_doc = (tm.get("abstract_fetch_s", 0) + tm.get("hash_s", 0) + tm.get("ledger_write_s", 0)) / seeded
        per_doc_s = meta_per_row + rest_per_doc
        rchar_per_doc = io_["rchar"] / seeded
        bpr = t2["ledger_size"].get("table_bytes_per_row") or t2["ledger_size"]["file_bytes_per_row"]
        out["extrapolation_150M"] = {
            "mark": "*est.*",
            "assumption": ("every section's abstract sidecar is available locally (unpacked) with the "
                           "hot section's per-doc fetch cost in id order; per-meta-row scan cost and "
                           "per-doc fetch+hash+write cost from the T2 timers scale linearly (one-time "
                           "store opens excluded); single process; this host's shared 9p conditions"),
            "model": "N x (meta_s/meta_rows + (abstract_fetch_s + hash_s + ledger_write_s)/seeded) from T2 timers",
            "meta_ms_per_row": round(meta_per_row * 1e3, 4),
            "fetch_hash_write_ms_per_seeded_doc": round(rest_per_doc * 1e3, 4),
            "per_doc_ms": round(per_doc_s * 1e3, 4),
            "naive_wall_over_seeded_hours": round(wall / seeded * N / 3600, 1),
            "wall_hours_est": round(per_doc_s * N / 3600, 1),
            "rchar_bytes_per_seeded_doc_id_order": round(rchar_per_doc, 1),
            "read_gb_est_id_order": round(rchar_per_doc * N / 1e9, 1),
            "ledger_base_hashes_gb_est": round(bpr * N / 1e9, 2),
            "timings_valid": False,
        }
    data_after = {p.name for p in (index_root / "sections" / HOT).iterdir()} | \
        {p.name for p in index_root.iterdir()}
    out["no_writes_under_data"] = {"new_entries": sorted(data_after - data_before)}
    out["wall_seconds_total"] = round(time.time() - t_start, 1)
    out["host"] = os.uname().nodename
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
