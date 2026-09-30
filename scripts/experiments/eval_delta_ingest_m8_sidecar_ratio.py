#!/usr/bin/env python3
"""Delta-ingest M8: abstract-sidecar ratio at delta size
(docs/delta_ingest/03_SPIKE_PLAN.md M8; 02_DESIGN.md section 3 row
"Abstract sidecar", issue A1).

PRE-REGISTERED (metric + bar copied verbatim from 03_SPIKE_PLAN.md M8, written
into this header 2026-09-30 before any M8 number was recorded; the operational
definitions below were fixed at the same time):

  metric : bytes/abstract in a 20k-doc and a 200k-doc generation vs the base's
           351.8 B/doc (`STORAGE_BUDGET_150M.md`)
  bar    : recorded; triggers the dict-reuse lever if > 1.3x

Disclosure: before this header was written the agent listed the file sizes,
row counts, block payload sums and meta keys of the ten stores of
root_n1/g0001 (to find where the store lives); no ratio was computed.

Operational definitions (fixed before the run):
  generations : built 2026-09-29 by the M4 item from corpus (b) (160,347
                OpenAlex works of snapshot partition updated_date=2026-09-15/
                part_0001 not present in the base, GPU-encoded by item F).
                "200k" arm = /home/vscode/work/inplace_update/m4/root_n1/g0001
                (all 160,347 docs; the partition yields fewer than 200k: a
                recorded deviation). "20k" arm = root_n8/g0001..g0008
                (20,043-20,044 docs each); all eight are measured, mean and
                min/max reported. Stores are opened read-only
                (`mode=ro&immutable=1`); the M4 roots are never modified.
  store       : every gNNNN/sections/<section>/abstracts.sqlite (format v3,
                `lib.thinclient.abstracts.AbstractStoreWriter`). Per store:
                file bytes (+ any -wal/-shm), SQLite page_count/freelist,
                block payload bytes (sum length(z)), dict bytes (sum of
                meta zdict_*), locator+envelope bytes = file - payload - dicts,
                docs (rows of `docs`), raw UTF-8 bytes and characters of every
                stored abstract (every block decompressed with the reader's own
                dict rule `_build_v3_dctxs`: zdict_<bucket>, else zdict_latin,
                else plain zstd), and per script bucket: docs, payload, raw,
                chars, dict used (trained_own | latin_fallback | plain_zstd)
                and dict size.
  headline    : H = on-disk store bytes / docs with an abstract, summed over
                all sections of the generation (what a generation costs on
                disk). Ratio R_H = H / 351.8.
  like-for-like: 351.8 B/doc (eval_storage_levers.py abstracts_full_config,
                2026-06-11) = compressed block PAYLOAD only / docs, 20,000
                sampled abstracts all with text, per-language dicts trained
                in-sample, dict bytes and any locator EXCLUDED, raw/payload
                3.42x. The like-for-like delta number is P = payload / docs
                (ratio R_P = P / 351.8). Because corpus (b) abstract lengths
                differ from that sample, the length-normalised ratio is also
                reported: R_N = 3.42 / (raw / payload of the generation).
                Context (not the bar): the served base store (one section,
                social_sciences__recent, 23,398,073 rows, flat sidecar
                blocks.bin) payload/row, and its raw/payload and bytes/char
                from a seeded sample of 1,000 blocks (seed 20260930) read
                read-only from blocks.bin.
  verdict     : RECORDED. The dict-reuse lever is TRIGGERED iff R_H > 1.3 or
                R_N > 1.3 for either arm (20k arm = mean over the eight
                generations; 200k arm = root_n1/g0001). R_N is included in
                the trigger because R_H and R_P can be pulled under 1.3 by
                shorter abstracts alone, which says nothing about the dicts.
  lever arm   : run only if TRIGGERED and it fits before 2026-09-30 23:30Z.
                Corpus = chunk 0 of corpus (b) split evenly in 8 (ids from
                /home/vscode/work/inplace_update/m4/corpus_b.json, records from
                the item-F ledger read-only; identical to root_n8/g0001's
                20,044 docs). Two fresh generations are built under
                /home/vscode/work/delta_ingest/m8/ with
                spike.delta_ingest.generation.build_generation(seismic=False)
                (the abstract stores do not depend on SEISMIC):
                  control : unmodified code. Sanity gate: per-section docs and
                            payload bytes must equal root_n8/g0001's stores
                            (determinism of the replay); a mismatch is
                            recorded and the arm still reported.
                  seeded  : every new AbstractStoreWriter is pre-seeded with
                            the base's seven dicts (meta 'dicts' = the base's
                            bucket names, meta zdict_<name> = the base files in
                            data/thinclient_index/sections/social_sciences__recent/
                            abstracts.sqlite.flat/, read-only) so `_restore`
                            installs them and no bucket is trained.
                Reported for seeded: H (dicts copied into every store, as the
                simple pre-seed ships them), H_ref (same store with the
                zdict_* rows deleted and VACUUMed on a copy = the design
                where a generation references the base dicts instead of
                copying them), P, R_N, and each vs control.
POST-HOC REVISION 2026-09-30 ~18:15Z (AFTER the pre-registered `measure` run,
which is the result of record: verdict RECORDED, lever NOT triggered; nothing
above is changed). That run showed corpus (b) is 89.8% type=dataset and 89.8%
of its abstracts are exact duplicates of an earlier abstract in the corpus
(143,999 of 160,347; mean 296 chars vs ~1,526 estimated for the served base),
so its bytes/abstract reflects repeated boilerplate inside 32 KB blocks, not
dictionary economics. A SUPPLEMENTARY, explicitly post-hoc arm (`posthoc`)
measures the A1 question on article-like content; it cannot change the
pre-registered verdict:
  sets     : S1 = corpus (b) records whose abstract text is the first
             occurrence in corpus order (unique content); S2 = corpus (b)
             records with type != "dataset". Records from the item-F ledger
             (read-only).
  stores   : per set, one store per section exactly as build_generation
             writes them (section = DocRecord.section(), AbstractStoreWriter
             add(id, abstract) in corpus order, finish()), no tantivy/meta/
             SEISMIC, under /home/vscode/work/delta_ingest/m8/posthoc/.
             Two variants each: control (unmodified writer) and seeded (base
             dicts pre-seeded as in the lever arm), with H_ref as above.
  report   : H, P, R_H, R_P, R_N, per-bucket dict use, and seeded/control.
  host        : CPU/IO only, no retriever, no index load; run under
                `nice -n 10 taskset -c 8-15`. No timing is a deliverable:
                every wall field carries timings_valid=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import zstandard

M4 = Path("/home/vscode/work/inplace_update/m4")
WORK = Path("/home/vscode/work/delta_ingest/m8")
F_LEDGER = Path("/var/tmp/sfu_delta_F_20260929/root/desktop_gpu/ledger.sqlite")
BASE_FLAT = REPO / "data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite.flat"
RESULTS = REPO / "data/eval_results/delta_ingest_M8_20260930.json"
BASE_B_PER_DOC = 351.8
BASE_RATIO = 3.42
BAR = 1.3
SAMPLE_BLOCKS = 1000
SEED = 20260930
DEADLINE_UTC = "2026-09-30T23:30:00Z"
TIMINGS_NOTE = ("host shared with a B7 run on cores 0-7 and an S0-2 process on cores 8-15; "
                "this item ran niced on cores 8-15; walls are not deliverables")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git_commit() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _dctxs(zdicts: dict[str, bytes], names: list[str]) -> tuple[dict, dict]:
    """Mirror of AbstractStoreReader._build_v3_dctxs, plus which dict each
    positional id actually decodes with."""
    plain = zstandard.ZstdDecompressor()
    latin = zdicts.get("zdict_latin")
    out, used = {}, {}
    for i, name in enumerate(names):
        own = zdicts.get(f"zdict_{name}")
        zd = own or latin
        out[i] = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(zd)) if zd else plain
        if own:
            used[i] = {"bucket": name, "dict": "trained_own", "dict_bytes": len(own)}
        elif latin:
            used[i] = {"bucket": name, "dict": "latin_fallback", "dict_bytes": 0}
        else:
            used[i] = {"bucket": name, "dict": "plain_zstd", "dict_bytes": 0}
    return out, used


def measure_store(path: Path) -> dict:
    db = _ro(path)
    file_bytes = path.stat().st_size + sum(
        p.stat().st_size for p in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm"))
        if p.exists())
    page_count = db.execute("PRAGMA page_count").fetchone()[0]
    page_size = db.execute("PRAGMA page_size").fetchone()[0]
    freelist = db.execute("PRAGMA freelist_count").fetchone()[0]
    meta = dict(db.execute("SELECT k, v FROM meta"))
    fmt = meta.get("format")
    names = json.loads(meta.get("dicts") or "[]")
    zdicts = {k: bytes(v) for k, v in meta.items() if k.startswith("zdict")}
    dctxs, used = _dctxs(zdicts, names)
    docs_by_block: dict[int, list[tuple[int, int]]] = {}
    for b, off, n in db.execute("SELECT b, off, n FROM docs"):
        docs_by_block.setdefault(b, []).append((off, n))
    buckets: dict[int, dict] = {}
    payload = raw = chars = ndocs = 0
    for b, d, z in db.execute("SELECT b, d, z FROM blocks"):
        blob = dctxs.get(d, dctxs.get(0)).decompress(z)
        rows = docs_by_block.get(b, [])
        bc = sum(len(blob[o:o + n].decode("utf-8")) for o, n in rows)
        br = sum(n for _, n in rows)
        e = buckets.setdefault(d, {**used.get(d, {"bucket": f"id{d}", "dict": "unknown", "dict_bytes": 0}),
                                   "docs": 0, "blocks": 0, "payload_bytes": 0, "raw_bytes": 0, "chars": 0})
        e["docs"] += len(rows)
        e["blocks"] += 1
        e["payload_bytes"] += len(z)
        e["raw_bytes"] += br
        e["chars"] += bc
        payload += len(z)
        raw += br
        chars += bc
        ndocs += len(rows)
    n_docs_table = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    db.close()
    dict_bytes = sum(len(v) for v in zdicts.values())
    for e in buckets.values():
        e["payload_per_doc"] = round(e["payload_bytes"] / e["docs"], 1) if e["docs"] else None
        e["raw_over_payload"] = round(e["raw_bytes"] / e["payload_bytes"], 3) if e["payload_bytes"] else None
        e["payload_per_char"] = round(e["payload_bytes"] / e["chars"], 4) if e["chars"] else None
    return {
        "path": str(path), "format": fmt, "file_bytes": file_bytes, "page_size": page_size,
        "page_count": page_count, "freelist_pages": freelist, "docs": n_docs_table,
        "docs_decoded": ndocs, "payload_bytes": payload, "dict_bytes": dict_bytes,
        "dicts_stored": sorted(k for k in zdicts),
        "locator_envelope_bytes": file_bytes - payload - dict_bytes,
        "raw_bytes": raw, "chars": chars,
        "mean_abstract_chars": round(chars / ndocs, 1) if ndocs else None,
        "bytes_per_abstract": round(file_bytes / n_docs_table, 1) if n_docs_table else None,
        "payload_per_abstract": round(payload / n_docs_table, 1) if n_docs_table else None,
        "buckets": sorted(buckets.values(), key=lambda e: -e["docs"]),
    }


def measure_generation(gdir: Path) -> dict:
    t0 = time.time()
    stores = {}
    for p in sorted(gdir.glob("sections/*/abstracts.sqlite")):
        stores[p.parent.name] = measure_store(p)
    tot = {k: sum(s[k] for s in stores.values()) for k in
           ("file_bytes", "payload_bytes", "dict_bytes", "locator_envelope_bytes", "docs", "raw_bytes", "chars")}
    gi = json.loads((gdir / "generation.json").read_text())
    return {"generation_dir": str(gdir), "generation_docs": gi.get("docs"), "stores": stores,
            "totals": tot, **headline(tot), "wall_s": round(time.time() - t0, 2), "timings_valid": False}


def headline(tot: dict) -> dict:
    n = tot["docs"]
    H = tot["file_bytes"] / n
    P = tot["payload_bytes"] / n
    comp = tot["raw_bytes"] / tot["payload_bytes"]
    comp_disk = tot["raw_bytes"] / tot["file_bytes"]
    return {"H_bytes_per_abstract": round(H, 1), "P_payload_per_abstract": round(P, 1),
            "dict_bytes_per_abstract": round(tot["dict_bytes"] / n, 1),
            "locator_envelope_per_abstract": round(tot["locator_envelope_bytes"] / n, 1),
            "mean_abstract_chars": round(tot["chars"] / n, 1),
            "mean_abstract_raw_bytes": round(tot["raw_bytes"] / n, 1),
            "raw_over_payload": round(comp, 3), "raw_over_disk": round(comp_disk, 3),
            "payload_per_char": round(tot["payload_bytes"] / tot["chars"], 4),
            "disk_per_char": round(tot["file_bytes"] / tot["chars"], 4),
            "R_H": round(H / BASE_B_PER_DOC, 3), "R_P": round(P / BASE_B_PER_DOC, 3),
            "R_N": round(BASE_RATIO / comp, 3), "R_N_disk": round(BASE_RATIO / comp_disk, 3)}


def base_context() -> dict:
    """Served base store numbers: flat stamps + a seeded block sample, read-only."""
    import numpy as np
    loc = json.loads((BASE_FLAT / "locator.json").read_text())
    flat = json.loads((BASE_FLAT / "flat_store.json").read_text())
    dmeta = json.loads((BASE_FLAT / "dicts.json").read_text())
    zd = {f"zdict_{n}": (BASE_FLAT / f"zdict_{n}").read_bytes() for n in dmeta["names"]
          if (BASE_FLAT / f"zdict_{n}").exists()}
    dctxs, used = _dctxs(zd, dmeta["names"])
    offs = np.load(BASE_FLAT / "block_offsets.npy", mmap_mode="r")
    lens = np.load(BASE_FLAT / "block_lengths.npy", mmap_mode="r")
    dids = np.load(BASE_FLAT / "block_dictids.npy", mmap_mode="r")
    valid = [i for i in range(len(lens)) if int(lens[i]) > 0]
    rng = random.Random(SEED)
    pick = sorted(rng.sample(valid, min(SAMPLE_BLOCKS, len(valid))))
    comp = raw = chars = 0
    fd = os.open(BASE_FLAT / "blocks.bin", os.O_RDONLY)
    try:
        for i in pick:
            z = os.pread(fd, int(lens[i]), int(offs[i]))
            blob = dctxs.get(int(dids[i]), dctxs[0]).decompress(z)
            comp += len(z)
            raw += len(blob)
            chars += len(blob.decode("utf-8", errors="replace"))
    finally:
        os.close(fd)
    rows = loc["rows"]
    ratio = raw / comp
    return {"flat_dir": str(BASE_FLAT), "rows": rows, "blocks_bin_bytes": flat["bytes"],
            "sqlite_bytes": flat["source"]["bytes"], "locator_bytes": loc["bytes"],
            "dict_bytes": sum(len(v) for v in zd.values()),
            "payload_per_abstract": round(flat["bytes"] / rows, 1),
            "sqlite_bytes_per_abstract": round(flat["source"]["bytes"] / rows, 1),
            "flat_plus_locator_per_abstract": round((flat["bytes"] + loc["bytes"]) / rows, 1),
            "sample": {"blocks": len(pick), "seed": SEED, "payload_bytes": comp, "raw_bytes": raw,
                       "chars": chars, "raw_over_payload": round(ratio, 3),
                       "payload_per_char": round(comp / chars, 4)},
            "est_mean_abstract_raw_bytes": round(flat["bytes"] * ratio / rows, 1),
            "est_mean_abstract_chars": round(flat["bytes"] * ratio * (chars / raw) / rows, 1),
            "dicts": {used[i]["bucket"]: used[i]["dict"] for i in used}}


def summarize_arm(gens: list[dict]) -> dict:
    keys = ("H_bytes_per_abstract", "P_payload_per_abstract", "R_H", "R_P", "R_N", "R_N_disk",
            "mean_abstract_chars", "raw_over_payload", "payload_per_char", "dict_bytes_per_abstract",
            "locator_envelope_per_abstract")
    out = {}
    for k in keys:
        v = [g[k] for g in gens]
        out[k] = {"mean": round(sum(v) / len(v), 3), "min": min(v), "max": max(v)}
    return out


def cmd_measure(args) -> int:
    started = utc()
    arm200 = measure_generation(M4 / "root_n1" / "g0001")
    arm20 = [measure_generation(M4 / "root_n8" / f"g{g:04d}") for g in range(1, 9)]
    base = base_context()
    s20 = summarize_arm(arm20)
    trig = {
        "20k_R_H_mean": s20["R_H"]["mean"], "20k_R_N_mean": s20["R_N"]["mean"],
        "200k_R_H": arm200["R_H"], "200k_R_N": arm200["R_N"],
    }
    triggered = any(v > BAR for v in trig.values())
    res = {
        "item": "M8", "title": "delta-ingest abstract-sidecar ratio at delta size",
        "plan_row": {"metric": "bytes/abstract in a 20k-doc and a 200k-doc generation vs the base's "
                               "351.8 B/doc (`STORAGE_BUDGET_150M.md`)",
                     "bar": "recorded; triggers the dict-reuse lever if > 1.3x"},
        "harness": "scripts/experiments/eval_delta_ingest_m8_sidecar_ratio.py",
        "commit": git_commit(), "started_utc": started, "finished_utc": utc(),
        "base_reference": {"b_per_doc": BASE_B_PER_DOC, "raw_over_payload": BASE_RATIO,
                           "source": "data/eval_results/storage_levers_eval.json abstracts_full_config "
                                     "(20,000 sampled abstracts, payload only, dicts + locator excluded)"},
        "served_base_context": base,
        "arm_200k": {"deviation": "partition yields 160,347 docs, not 200k", **arm200},
        "arm_20k": {"generations": arm20, "summary": s20},
        "trigger_values": trig, "bar": BAR,
        "verdict": "RECORDED", "lever_triggered": triggered,
        "timings_valid": False, "timings_note": TIMINGS_NOTE,
    }
    if RESULTS.exists():
        old = json.loads(RESULTS.read_text())
        if "lever_arm" in old:
            res["lever_arm"] = old["lever_arm"]
    RESULTS.write_text(json.dumps(res, indent=1))
    print(json.dumps({"200k": {k: arm200[k] for k in ("H_bytes_per_abstract", "P_payload_per_abstract",
                                                       "R_H", "R_P", "R_N", "mean_abstract_chars")},
                      "20k": {k: s20[k] for k in ("H_bytes_per_abstract", "P_payload_per_abstract",
                                                   "R_H", "R_P", "R_N", "mean_abstract_chars")},
                      "base": {k: base[k] for k in ("payload_per_abstract", "sqlite_bytes_per_abstract",
                                                     "est_mean_abstract_chars")},
                      "base_sample_ratio": base["sample"]["raw_over_payload"],
                      "triggered": triggered}, indent=1))
    return 0


def _chunk0_ids() -> list[str]:
    ids = json.loads((M4 / "corpus_b.json").read_text())["ids"]
    q, r = divmod(len(ids), 8)
    return ids[:q + (1 if r > 0 else 0)]


def _records(ids: list[str]):
    from spike.delta_ingest.records import DocRecord
    src = _ro(F_LEDGER)
    out = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for rid, rec in src.execute(f"SELECT id, record FROM records WHERE id IN ({','.join('?' * len(chunk))})",
                                    chunk):
            out[rid] = DocRecord.from_json(rec)
    src.close()
    return [out[i] for i in ids]


def _seed_patch():
    from lib.thinclient import abstracts as A
    dmeta = json.loads((BASE_FLAT / "dicts.json").read_text())
    names = dmeta["names"]
    blobs = {n: (BASE_FLAT / f"zdict_{n}").read_bytes() for n in names}
    orig = A.AbstractStoreWriter.__init__

    def seeded_init(self, path):
        p = Path(path)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(p))
            db.executescript(
                "CREATE TABLE IF NOT EXISTS blocks (b INTEGER PRIMARY KEY, d INTEGER, z BLOB);"
                "CREATE TABLE IF NOT EXISTS docs (id TEXT PRIMARY KEY, b INTEGER, off INTEGER, n INTEGER);"
                "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v BLOB);")
            db.execute("INSERT INTO meta VALUES ('dicts', ?)", (json.dumps(names),))
            for n, b in blobs.items():
                db.execute("INSERT INTO meta VALUES (?, ?)", (f"zdict_{n}", b))
            db.commit()
            db.close()
        orig(self, path)

    A.AbstractStoreWriter.__init__ = seeded_init
    return {"names": names, "sha256": {n: hashlib.sha256(b).hexdigest()[:16] for n, b in blobs.items()}}


def _ref_variant(gdir: Path, out: Path) -> dict:
    """Copy each store, drop its zdict_* rows, VACUUM: the store as it would be
    if the generation referenced the base dicts instead of copying them."""
    tot = {"file_bytes": 0, "docs": 0}
    for p in sorted(gdir.glob("sections/*/abstracts.sqlite")):
        dst = out / p.parent.name / "abstracts.sqlite"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        db = sqlite3.connect(str(dst))
        db.execute("DELETE FROM meta WHERE k LIKE 'zdict%'")
        db.commit()
        db.execute("VACUUM")
        db.close()
        tot["file_bytes"] += dst.stat().st_size
        tot["docs"] += _ro(p).execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    return {"file_bytes": tot["file_bytes"], "docs": tot["docs"],
            "H_ref_bytes_per_abstract": round(tot["file_bytes"] / tot["docs"], 1),
            "R_H_ref": round(tot["file_bytes"] / tot["docs"] / BASE_B_PER_DOC, 3)}


def cmd_build(args) -> int:
    from spike.delta_ingest.generation import build_generation
    from spike.delta_ingest.profiles import PROFILES
    arm = args.arm
    root = WORK / f"root_{arm}"
    if (root / "g0001").exists():
        print(f"{root}/g0001 exists; refusing to rebuild", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    seed_info = _seed_patch() if arm == "seeded" else None
    ids = _chunk0_ids()
    recs = _records(ids)
    t0 = time.time()
    build_generation(root, 1, recs, PROFILES["desktop_gpu"], seismic=False)
    log = {"arm": arm, "docs": len(recs), "ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
           "wall_s": round(time.time() - t0, 1), "timings_valid": False, "seed": seed_info, "utc": utc()}
    (WORK / f"build_{arm}.json").write_text(json.dumps(log, indent=1))
    print(json.dumps(log))
    return 0


def cmd_lever(args) -> int:
    ctrl = measure_generation(WORK / "root_control" / "g0001")
    seed = measure_generation(WORK / "root_seeded" / "g0001")
    ref = _ref_variant(WORK / "root_seeded" / "g0001", WORK / "seeded_ref")
    m4g1 = measure_generation(M4 / "root_n8" / "g0001")
    parity = {s: {"docs": (ctrl["stores"][s]["docs"], m4g1["stores"].get(s, {}).get("docs")),
                  "payload": (ctrl["stores"][s]["payload_bytes"], m4g1["stores"].get(s, {}).get("payload_bytes"))}
              for s in ctrl["stores"]}
    parity_ok = all(v["docs"][0] == v["docs"][1] and v["payload"][0] == v["payload"][1] for v in parity.values())
    lever = {
        "utc": utc(), "commit": git_commit(),
        "builds": {a: json.loads((WORK / f"build_{a}.json").read_text()) for a in ("control", "seeded")},
        "control": ctrl, "seeded": seed, "seeded_ref": ref,
        "control_vs_m4_g0001_parity": {"ok": parity_ok, "per_section": parity},
        "delta": {
            "H_seeded_over_control": round(seed["H_bytes_per_abstract"] / ctrl["H_bytes_per_abstract"], 3),
            "H_ref_over_control": round(ref["H_ref_bytes_per_abstract"] / ctrl["H_bytes_per_abstract"], 3),
            "P_seeded_over_control": round(seed["P_payload_per_abstract"] / ctrl["P_payload_per_abstract"], 3),
            "R_N_control": ctrl["R_N"], "R_N_seeded": seed["R_N"],
        },
        "timings_valid": False, "timings_note": TIMINGS_NOTE,
    }
    res = json.loads(RESULTS.read_text())
    res["lever_arm"] = lever
    RESULTS.write_text(json.dumps(res, indent=1))
    print(json.dumps({"parity_ok": parity_ok, **lever["delta"],
                      "control": {k: ctrl[k] for k in ("H_bytes_per_abstract", "P_payload_per_abstract", "R_H")},
                      "seeded": {k: seed[k] for k in ("H_bytes_per_abstract", "P_payload_per_abstract", "R_H")},
                      "seeded_ref": ref}, indent=1))
    return 0


def _write_stores(out: Path, recs) -> None:
    from lib.thinclient.abstracts import AbstractStoreWriter
    by_section: dict[str, list] = {}
    for r in recs:
        by_section.setdefault(r.section(), []).append(r)
    for name, rs in sorted(by_section.items()):
        w = AbstractStoreWriter(out / "sections" / name / "abstracts.sqlite")
        for r in rs:
            w.add(r.id, r.abstract or "")
        w.finish()
    (out / "generation.json").write_text(json.dumps({"docs": len(recs)}))


def cmd_posthoc(args) -> int:
    from spike.delta_ingest.records import DocRecord
    from lib.thinclient import abstracts as A
    ids = json.loads((M4 / "corpus_b.json").read_text())["ids"]
    recs = _records(ids)
    seen: set[str] = set()
    s1 = []
    for r in recs:
        a = r.abstract or ""
        if a not in seen:
            seen.add(a)
            s1.append(r)
    s2 = [r for r in recs if (r.type or "") != "dataset"]
    base_dir = WORK / "posthoc"
    if base_dir.exists():
        print(f"{base_dir} exists; refusing to rebuild", file=sys.stderr)
        return 2
    orig_init = A.AbstractStoreWriter.__init__
    out = {"utc": utc(), "commit": git_commit(), "label": "POST-HOC supplementary; not the verdict",
           "sets": {"S1_unique_abstract": len(s1), "S2_non_dataset": len(s2)}, "arms": {},
           "timings_valid": False, "timings_note": TIMINGS_NOTE}
    for sname, rs in (("S1_unique_abstract", s1), ("S2_non_dataset", s2)):
        for variant in ("control", "seeded"):
            A.AbstractStoreWriter.__init__ = orig_init
            seed_info = _seed_patch() if variant == "seeded" else None
            gdir = base_dir / f"{sname}_{variant}"
            t0 = time.time()
            _write_stores(gdir, rs)
            m = measure_generation(gdir)
            m["build_wall_s"] = round(time.time() - t0, 1)
            m["seed"] = seed_info
            if variant == "seeded":
                m["ref"] = _ref_variant(gdir, base_dir / f"{sname}_seeded_ref")
            out["arms"][f"{sname}_{variant}"] = m
        A.AbstractStoreWriter.__init__ = orig_init
        c, s = out["arms"][f"{sname}_control"], out["arms"][f"{sname}_seeded"]
        out["arms"][f"{sname}_delta"] = {
            "H_seeded_over_control": round(s["H_bytes_per_abstract"] / c["H_bytes_per_abstract"], 3),
            "H_ref_over_control": round(s["ref"]["H_ref_bytes_per_abstract"] / c["H_bytes_per_abstract"], 3),
            "P_seeded_over_control": round(s["P_payload_per_abstract"] / c["P_payload_per_abstract"], 3)}
    res = json.loads(RESULTS.read_text())
    res["posthoc_supplement"] = out
    RESULTS.write_text(json.dumps(res, indent=1))
    keys = ("docs", "H_bytes_per_abstract", "P_payload_per_abstract", "R_H", "R_P", "R_N",
            "mean_abstract_chars", "raw_over_payload", "dict_bytes_per_abstract")
    print(json.dumps({k: ({kk: (v["totals"]["docs"] if kk == "docs" else v.get(kk)) for kk in keys}
                          | ({"ref": v["ref"]} if "ref" in v else {}) if "totals" in v else v)
                      for k, v in out["arms"].items()}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("measure")
    b = sub.add_parser("build")
    b.add_argument("--arm", choices=("control", "seeded"), required=True)
    sub.add_parser("lever")
    sub.add_parser("posthoc")
    args = ap.parse_args()
    return {"measure": cmd_measure, "build": cmd_build, "lever": cmd_lever, "posthoc": cmd_posthoc}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
