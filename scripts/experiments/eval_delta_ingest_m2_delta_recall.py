#!/usr/bin/env python3
"""Delta-ingest M2: delta-shard recall on corpus (a)
(docs/delta_ingest/03_SPIKE_PLAN.md row M2), plus the shared corpus (a)
fixture that M3 reuses (subcommand `build-fixture`).

PRE-REGISTERED 2026-09-30 (written and pushed BEFORE any M2 number existed;
metric and bar copied VERBATIM from 03_SPIKE_PLAN.md row M2):

  metric : for corpus (a): fraction of updated docs returned by the SPLADE leg
           from the delta shard for their own title-as-query, vs the same docs
           served from the base shard before the update
  bar    : >= 0.95 of the base's own-recall; per-shard overlap@10 vs an exact
           dot product >= 0.99 (the E8 bar)

Corpus (a) fixture (plan "Fixed inputs": 50k docs sampled from the base meta,
titles/abstracts fetched via the sidecar, re-ingested as "updates" with one
appended sentence):
  population   : base docs whose ordinal-array section code is
                 social_sciences__recent (code 1 in
                 /var/tmp/sfu_delta_C_20260929/ords/codes.json), the ONLY hot
                 section, i.e. the only one with a local abstract sidecar
                 (data/thinclient_index/sections/social_sciences__recent/
                 abstracts.sqlite, read through lib.thinclient.abstracts.
                 AbstractStore.fetch, the store the retriever's
                 `fetch_abstracts` reads first). Consequence: corpus (a) is
                 one section of ten, not a whole-corpus sample (recorded).
  sampling     : numpy default_rng(int(sha256("sfu-delta-m2-2026-09-30")[:16], 16))
                 .permutation over the population's ordinals; walk that order
                 in blocks of 5,000 and keep a doc iff meta.sqlite `docs`
                 title.strip() != "" AND the sidecar abstract.strip() != "";
                 stop at exactly 50,000 kept (ties impossible: order is the
                 permutation). The walk count and rejections are recorded.
  update       : DocRecord fields from meta.sqlite (title, doi verbatim incl.
                 any https://doi.org/ prefix, year, type, is_oa) + abstract =
                 sidecar abstract + APPENDED_SENTENCE (one fixed sentence,
                 below). Title unchanged, so title-as-query is the same string
                 for both copies. Ids are bare W-ids: `canonical_id` keeps a
                 bare W-id from any namespace, `BaseIndex.contains` finds it in
                 meta `docs` (INTEGER PK via encode_meta_id), so the ledger
                 classifies every record `updated` (in_base=1) -> superseded
                 mask + livedocs bit on the base ordinal. O5 (doi prefix) does
                 not touch ids.
  build        : supported CLI only, from a `git archive` snapshot of src +
                 spike/delta_ingest at the fixture commit:
                 `cli ingest --source jsonl --namespace openalex` (profile
                 desktop_gpu, GPU encode) then `cli flush --force`, both with
                 --base-shard-manifest = the frozen M4 copy
                 /home/vscode/work/inplace_update/m4/base_manifest.json and
                 SFU_THINCLIENT_ORDINALS=/var/tmp/sfu_delta_C_20260929/ords
                 (O9: the CLI has no ordinal-dir flag; publish reads this env).
                 One generation g0001, empty buffer afterwards.
  verify       : generations.json lists g0001 with 50,000 docs; livedocs .liv
                 popcount 50,000; shard_manifest.json = 8 base + 1 delta shard;
                 ledger buffer 0; one gate-on `search_rrf` smoke with the health
                 assertions (below) passing. Then READY.json + READY.

M2 operational definitions (fixed before the run):
  title sample : the 50,000 fixture ids permuted with
                 default_rng(int(sha256("sfu-delta-m2-2026-09-30:queries")[:16], 16));
                 the list is written to READY.json (M3 uses the same list).
                 M2 uses its PREFIX of length N. N rule: a 50-query probe
                 (delta arm, the LAST 50 ids of the permuted list, never in the
                 prefix) gives per-query p50 t; N = min(10000, 1000*floor(A /
                 (2 * 1.3 * t) / 1000)) where A = seconds from probe end to
                 22:40Z minus 1800 s (exact-overlap runs + record); N >= 2000
                 regardless. N is recorded.
  query        : the doc's meta title, verbatim.
  SPLADE leg   : `ThinClientRetriever._splade_leg(title, 50, None)` (the
                 served SEISMIC leg: ParallelSeismicBackend, served defaults
                 k'=max(2*50,100)=100, heap_factor 0.8, query_cut=len(terms),
                 then the delta layer's `filter_ids` / buffer merge in the delta
                 arm). NOT the full `search_rrf`.
  arms         : BASE = gate off (SFU_DELTA_ROOT="", SFU_SEISMIC_SHARD_MANIFEST
                 = the frozen base manifest, 8 shards); DELTA = gate on
                 (SFU_DELTA_ROOT = the fixture root, manifest env blank so the
                 composed 8+1 manifest serves; livedocs per-shard filter
                 attached). SFU_SEISMIC_STAGE_DIR / SFU_META_STAGE_DIR /
                 SFU_THINCLIENT_ORDINALS blank in both. One process per arm,
                 BASE first then DELTA, queries in sample order, same N.
                 Code = `git archive` of src at the recorded commit.
  own-recall@k : fraction of the N sampled docs whose id is in the leg's top-k
                 for its own title; k=10 PRIMARY, k=50 supplementary. In DELTA
                 the hit must be the DELTA COPY: attribution by wrapping the
                 backend's `_shard_result_filter` (the livedocs hook; in BASE
                 an identity filter is installed, which leaves the merge
                 byte-identical) and recording, per query, which shard
                 positions held the target id before and after the filter, and
                 its score; a DELTA hit counts iff after the filter the id is
                 held by the delta shard (position 8, origin g1 via
                 `DeltaLayer.shard_origins`) and by no base shard, and the
                 final score equals that delta-shard score.
  bar 1        : PASS iff recall_delta@10 / recall_base@10 >= 0.95.
  mask leak    : count of sampled docs whose id survives the filter on a base
                 shard in DELTA, or is returned by both copies; must be 0; any
                 leak is a FAIL of the mask (reported beside bar 1).
  deadline     : if DELTA cannot finish N by 23:15Z the verdict is computed on
                 the common completed prefix of both arms and marked PARTIAL.
  exact overlap: delta shard ALONE. exact = sparse dot product of the query
                 vector with the generation's stored vectors
                 (g0001/seismic/delta_g0001.jsonl, the float SPLADE weights the
                 shard was built from; the served dotvbyte v2 layout stores them
                 per-doc u8-quantised, --value-scale perdoc), top-10 by score
                 (scores > 0 only; if fewer than 10 positive, the denominator is
                 that count). Engine = seismic.MmapSeismicIndex on the served
                 delta mmap_dir with the E8 recall-max params of the
                 twin-rebuild header: k=k'=200, query_cut=len(terms),
                 heap_factor=0.8, SFU_SEISMIC_PREFLOOR=2. Query encoding =
                 encode_splade(q, "models/splade_onnx_fp16"), top-64 terms.
                 Query sets: 120 natural topics (data/sfu_eval_queries.json
                 "query"), 100 diverse (diverse_queries.json via
                 e6_forward_codec_proto.load_queries, first 100 distinct), the
                 first 1,000 titles of the M2 title sample.
                 overlap@10 = |top10_seismic & top10_exact| / denominator.
  bar 2        : PASS iff mean overlap@10 >= 0.99 on EACH of the three sets.
                 Reported: min, count identical (set and order).
  recorded     : the same overlap with the served params (k=100, heap 0.8,
                 query_cut=len(terms), SFU_SEISMIC_PREFLOOR unset) - no bar.
  health       : per child, before any measured query: SPLADE ONNX encoder
                 non-empty; backend ParallelSeismicBackend with 8 (BASE) or 9
                 (DELTA) shards none None; DELTA: delta layer generations [1],
                 livedocs popcount 50,000 with the per-shard filter attached,
                 buffer 0; BASE: no delta layer. Logs scanned for ENOMEM /
                 fallback signatures (O12); a degraded arm is recorded as such.
  timings      : NOT deliverables (host shared with B7 / S0-2 / M3 / M8
                 agents); every wall/latency field is timings_valid=false.
  host         : nice -n 10 taskset -c 8-15, one index-loading process at a
                 time, MemAvailable >= 8 GB before a load, no latency lock.

DEVIATION 2026-09-30 19:25Z (written after the BASE arm had run ~200+ of its
2,000 queries, BEFORE any DELTA-arm query of the sample ran; bars and metric
unchanged). The probe measured p50 4.6 s/query and the probe rule gave
N=2,000; under the concurrent S0-2 process (~19.5 GB RSS, MemAvailable fell to
~9 GB) the BASE arm then slowed to > 11 s/query (~330 major faults/s on the
staged base shards). Sequential BASE-then-DELTA would leave DELTA with almost
no queries before 23:15Z, and a bar-1 ratio needs both arms on the same ids.
Change: the BASE child is stopped with SIGINT at 20:50Z (rows flushed; rows
are resumable), and the DELTA arm then runs the same permuted order until
23:15Z. The verdict is computed on the common completed prefix (as
pre-registered for a deadline stop) and is PARTIAL if that prefix < 2,000.

Run (all under nice -n 10 taskset -c 8-15):
  eval_delta_ingest_m2_delta_recall.py build-fixture
  eval_delta_ingest_m2_delta_recall.py probe
  eval_delta_ingest_m2_delta_recall.py arm --arm base --n N
  eval_delta_ingest_m2_delta_recall.py arm --arm delta --n N
  eval_delta_ingest_m2_delta_recall.py exact --params e8
  eval_delta_ingest_m2_delta_recall.py exact --params served
  eval_delta_ingest_m2_delta_recall.py record
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIX = Path("/home/vscode/work/delta_ingest/corpus_a")
ROOT = FIX / "root"
WORK = Path("/home/vscode/work/delta_ingest/m2")
ORDS = Path("/var/tmp/sfu_delta_C_20260929/ords")
BASE_MANIFEST = Path("/home/vscode/work/inplace_update/m4/base_manifest.json")
INDEX_ROOT = REPO / "data/thinclient_index"
SIDECAR = INDEX_ROOT / "sections/social_sciences__recent/abstracts.sqlite"
RESULT = REPO / "data/eval_results/delta_ingest_M2_20260930.json"
SEED = "sfu-delta-m2-2026-09-30"
N_DOCS = 50_000
SECTION = "social_sciences__recent"
APPENDED_SENTENCE = "This record was updated after publication."
TOP_K = 50
N_BASE_SHARDS = 8
QUERY_N_MAX = 10_000
SIGNATURES = ("Cannot allocate memory", "CrossEncoder unavailable", "Failed to load embedding model",
              "falling back to BM25F", "SPLADE encoder failed", "SEISMIC SPLADE leg failed",
              "delta buffer sparse encode failed", "Traceback", "delta layer off",
              "SFU_SEISMIC_SHARD_MANIFEST is set", "MemoryError", "WI-10")
BLANK_ENV = ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR", "SFU_THINCLIENT_ORDINALS", "SFU_DELTA_ROOT",
             "SFU_SEISMIC_SHARD_MANIFEST", "SFU_SEARCH_SPECULATIVE_RERANK", "SFU_SEISMIC_K_PRIME",
             "SFU_SEISMIC_QUERY_CUT", "SFU_SEISMIC_PREFLOOR")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git_commit() -> str:
    return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()


def ts(s: str) -> float:
    return float(calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")))


def seed_int(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest()[:16], 16)


def host_state() -> dict:
    out = {"utc": utc(), "loadavg": list(os.getloadavg())}
    for line in open("/proc/meminfo"):
        k, v = line.split(":", 1)
        if k in ("MemAvailable", "SwapFree"):
            out[k + "_gb"] = round(int(v.split()[0]) / 1024 ** 2, 2)
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        out["gpu"] = g.stdout.strip()
    except Exception as exc:
        out["gpu"] = f"unavailable: {exc!r}"
    try:
        ps = subprocess.run(["ps", "-eo", "pid,psr,pcpu,rss,cmd", "--sort=-pcpu"], capture_output=True,
                            text=True, timeout=10).stdout.splitlines()[1:7]
        out["top_procs"] = [p[:160] for p in ps]
    except Exception:
        pass
    return out


def mem_ok(min_gb: float = 8.0) -> float:
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable"):
            gb = int(line.split()[1]) / 1024 ** 2
            if gb < min_gb:
                sys.exit(f"MemAvailable {gb:.1f} GB < {min_gb} GB; wait and retry")
            return gb
    return 0.0


def snapshot(commit: str) -> Path:
    """git archive of src + spike/delta_ingest at `commit` (other agents edit
    the live tree concurrently); data/models/.env/seismic binaries symlinked."""
    snap = WORK / f"code_{commit[:8]}"
    if not (snap / "src").exists():
        snap.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(f"git -C {REPO} archive {commit} src spike/delta_ingest | tar -x -C {snap}",
                              shell=True)
        for name in ("models", "data", ".env", "spike/seismic_upstream"):
            if not (snap / name).exists():
                (snap / name).symlink_to(REPO / name)
    return snap


def child_env(arm: str | None) -> dict:
    env = dict(os.environ)
    env.update({k: "" for k in BLANK_ENV})
    env["SFU_SEISMIC_FEDERATION"] = "parallel"
    env["SFU_SPLADE_BACKEND"] = "seismic"
    if arm == "base":
        env["SFU_SEISMIC_SHARD_MANIFEST"] = str(BASE_MANIFEST)
    elif arm == "delta":
        env["SFU_DELTA_ROOT"] = str(ROOT)
    return env


def scan_log(path: Path) -> dict:
    text = path.read_text(errors="replace") if path.exists() else ""
    return {"path": str(path), "bytes": len(text), "signature_counts": {s: text.count(s) for s in SIGNATURES}}


# ── corpus (a) fixture ─────────────────────────────────────────────────────
def sample_corpus() -> dict:
    """Deterministic 50k sample (rule in the header) -> FIX/corpus_a.jsonl."""
    import numpy as np
    sys.path.insert(0, str(REPO / "src"))
    from lib.thinclient.abstracts import AbstractStore
    out_json = FIX / "sample.json"
    if out_json.exists():
        return json.loads(out_json.read_text())
    codes = json.loads((ORDS / "codes.json").read_text())
    code = codes["section"][SECTION]
    sec = np.load(ORDS / "section.npy", mmap_mode="r")
    wids = np.load(ORDS / "wids.npy", mmap_mode="r")
    pop = np.flatnonzero(np.asarray(sec) == code)
    rng = np.random.default_rng(seed_int(SEED))
    order = pop[rng.permutation(len(pop))]
    meta = sqlite3.connect(f"file:{INDEX_ROOT / 'meta.sqlite'}?mode=ro", uri=True)
    store = AbstractStore(SIDECAR)
    kept, walked = [], 0
    rej = {"no_meta_row": 0, "empty_title": 0, "no_abstract": 0, "section_mismatch": 0}
    t0 = time.time()
    pos = 0
    while len(kept) < N_DOCS and pos < len(order):
        block = order[pos:pos + 5000]
        pos += len(block)
        nums = [int(wids[o]) for o in block]
        rows = {}
        for i in range(0, len(nums), 500):
            ch = nums[i:i + 500]
            for r in meta.execute(f"SELECT id,title,doi,year,type,is_oa,section FROM docs WHERE id IN "
                                  f"({','.join('?' * len(ch))})", ch):
                rows[r[0]] = r
        ids = [f"W{n}" for n in nums]
        abs_ = store.fetch(ids)
        for o, n, wid in zip(block, nums, ids):
            if len(kept) >= N_DOCS:
                break
            walked += 1
            r = rows.get(n)
            if r is None:
                rej["no_meta_row"] += 1
                continue
            if r[6] != SECTION:
                rej["section_mismatch"] += 1
                continue
            if not (r[1] or "").strip():
                rej["empty_title"] += 1
                continue
            a = abs_.get(wid) or ""
            if not a.strip():
                rej["no_abstract"] += 1
                continue
            kept.append({"id": wid, "ordinal": int(o), "title": r[1], "doi": r[2] or "", "year": r[3],
                         "type": r[4] or "", "is_oa": bool(r[5]), "abstract_base": a})
        print(json.dumps({"walked": walked, "kept": len(kept), "rej": rej,
                          "s": round(time.time() - t0, 1)}), flush=True)
    meta.close()
    assert len(kept) == N_DOCS, len(kept)
    with open(FIX / "corpus_a.jsonl", "w") as fh:
        for k in kept:
            fh.write(json.dumps({"id": k["id"], "title": k["title"],
                                 "abstract": f"{k['abstract_base'].rstrip()} {APPENDED_SENTENCE}",
                                 "year": k["year"], "type": k["type"], "is_oa": k["is_oa"],
                                 "doi": k["doi"]}, ensure_ascii=False) + "\n")
    with open(FIX / "base_copies.jsonl", "w") as fh:
        for k in kept:
            fh.write(json.dumps({"id": k["id"], "ordinal": k["ordinal"], "title": k["title"],
                                 "abstract": k["abstract_base"]}, ensure_ascii=False) + "\n")
    ids = [k["id"] for k in kept]
    qrng = np.random.default_rng(seed_int(SEED + ":queries"))
    qorder = [ids[i] for i in qrng.permutation(len(ids))]
    info = {"utc": utc(), "seed": SEED, "population_section": SECTION, "population_size": int(len(pop)),
            "walked": walked, "rejections": rej, "kept": len(kept), "sample_seconds": round(time.time() - t0, 1),
            "appended_sentence": APPENDED_SENTENCE, "ids": ids,
            "ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
            "query_order": qorder, "query_order_seed": SEED + ":queries",
            "titles": {k["id"]: k["title"] for k in kept}}
    out_json.write_text(json.dumps(info))
    return info


def run_cli(snap: Path, cmd: list[str], log: Path) -> dict:
    env = child_env(None)
    env["SFU_THINCLIENT_ORDINALS"] = str(ORDS)
    full = ["nice", "-n", "10", "taskset", "-c", "8-15", str(REPO / ".venv/bin/python3"), "-m",
            "spike.delta_ingest.cli", *cmd, "--profile", "desktop_gpu", "--index-root", str(INDEX_ROOT),
            "--delta-root", str(ROOT), "--base-shard-manifest", str(BASE_MANIFEST)]
    t0 = time.time()
    with open(log, "w") as fh:
        rc = subprocess.call(full, cwd=str(snap), env=env, stdout=fh, stderr=subprocess.STDOUT)
    text = log.read_text(errors="replace")
    out = None
    i = text.rfind("\n{")
    if i >= 0:
        try:
            out = json.loads(text[i + 1:])
        except json.JSONDecodeError:
            out = None
    return {"cmd": full, "rc": rc, "wall_s": round(time.time() - t0, 1), "out": out, "log": str(log),
            "scan": scan_log(log)}


def verify_root() -> dict:
    sys.path.insert(0, str(REPO / "src"))
    from lib.thinclient.livedocs import HEADER_LEN, read_header
    gj = json.loads((ROOT / "generations.json").read_text())
    sm = json.loads((ROOT / "shard_manifest.json").read_text())
    ld = gj.get("livedocs") or {}
    hdr = read_header(open(ROOT / ld["path"], "rb").read(HEADER_LEN)) if ld else None
    led = sqlite3.connect(f"file:{ROOT / 'ledger.sqlite'}?mode=ro", uri=True)
    buf = led.execute("SELECT COUNT(*) FROM docs WHERE generation=0 AND status='live'").fetchone()[0]
    inb = led.execute("SELECT COUNT(*) FROM docs WHERE in_base=1 AND status='live'").fetchone()[0]
    led.close()
    checks = {
        "gens": [(g["gen"], g["docs"], g.get("docs_with_vectors"), g.get("seismic")) for g in gj["generations"]],
        "g0001_50000": [g["gen"] for g in gj["generations"]] == [1] and gj["generations"][0]["docs"] == N_DOCS
        and gj["generations"][0].get("docs_with_vectors") == N_DOCS,
        "livedocs": ld, "liv_header": hdr,
        "liv_popcount_50000": bool(hdr) and hdr.get("popcount") == N_DOCS and ld.get("superseded_in_base") == N_DOCS,
        "superseded_json": len(gj["mask"]["superseded"]), "deleted_json": len(gj["mask"]["deleted"]),
        "shards": [s.get("shard") or Path(s["mmap_dir"]).name for s in sm["shards"]],
        "shards_8_plus_1": len(sm["shards"]) == 9 and sum(1 for s in sm["shards"] if s.get("delta_generation")) == 1,
        "buffer_live": buf, "buffer_empty": buf == 0, "ledger_in_base_live": inb,
    }
    checks["ok"] = all(checks[k] for k in ("g0001_50000", "liv_popcount_50000", "shards_8_plus_1", "buffer_empty"))
    return checks


def build_fixture(args) -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    if (FIX / "READY").exists():
        sys.exit("READY exists; the fixture is published and must not be rebuilt")
    commit = git_commit()
    rec = {"started": utc(), "commit": commit, "host_start": host_state()}
    man = json.loads(BASE_MANIFEST.read_text())
    rec["base_manifest_shards"] = [s["mmap_dir"] for s in man["shards"]]
    assert len(man["shards"]) == N_BASE_SHARDS
    info = sample_corpus()
    rec["sample"] = {k: v for k, v in info.items() if k not in ("ids", "query_order", "titles")}
    snap = snapshot(commit)
    rec["snapshot"] = str(snap)
    if not (ROOT / "generations.json").exists() or not any(
            g["gen"] == 1 for g in json.loads((ROOT / "generations.json").read_text())["generations"]):
        if ROOT.exists() and any(ROOT.iterdir()):
            sys.exit(f"{ROOT} is non-empty but has no g0001; inspect before rebuilding")
        ROOT.mkdir(parents=True, exist_ok=True)
        rec["ingest"] = run_cli(snap, ["ingest", "--source", "jsonl", "--path", str(FIX / "corpus_a.jsonl"),
                                       "--namespace", "openalex", "--source-name", "m2_corpus_a"],
                                FIX / "ingest.log")
        print(json.dumps({"ingest": rec["ingest"]["out"], "rc": rec["ingest"]["rc"]}), flush=True)
        if rec["ingest"]["rc"] != 0:
            (FIX / "build_fixture.json").write_text(json.dumps(rec, indent=1, default=str))
            return 2
        rec["flush"] = run_cli(snap, ["flush", "--force"], FIX / "flush.log")
        print(json.dumps({"flush_rc": rec["flush"]["rc"]}), flush=True)
        if rec["flush"]["rc"] != 0:
            (FIX / "build_fixture.json").write_text(json.dumps(rec, indent=1, default=str))
            return 2
    rec["verify"] = verify_root()
    print(json.dumps(rec["verify"], default=str), flush=True)
    mem_ok()
    smoke_log = FIX / "smoke.log"
    with open(smoke_log, "w") as fh:
        rc = subprocess.call(["nice", "-n", "10", "taskset", "-c", "8-15", str(REPO / ".venv/bin/python3"),
                              __file__, "smoke", "--src", str(snap / "src")], cwd=str(REPO),
                             env=child_env("delta"), stdout=fh, stderr=subprocess.STDOUT)
    rec["smoke"] = {"rc": rc, "scan": scan_log(smoke_log)}
    sj = FIX / "smoke.json"
    if sj.exists():
        rec["smoke"]["result"] = json.loads(sj.read_text())
    rec["finished"] = utc()
    (FIX / "build_fixture.json").write_text(json.dumps(rec, indent=1, default=str))
    ok = rec["verify"]["ok"] and rc == 0 and rec["smoke"].get("result", {}).get("health", {}).get("ok")
    if not ok:
        print("fixture NOT ready", file=sys.stderr)
        return 3
    (FIX / "title_sample.json").write_text(json.dumps({
        "rule": "fixture ids permuted with numpy default_rng(int(sha256(seed)[:16],16)); M2 uses a prefix",
        "seed": SEED + ":queries", "order": info["query_order"],
        "titles": [info["titles"][i] for i in info["query_order"]]}))
    ready = {
        "root": str(ROOT), "fixture_dir": str(FIX), "published_utc": utc(),
        "fixture_commit": commit, "harness": "scripts/experiments/eval_delta_ingest_m2_delta_recall.py",
        "code_snapshot": str(snap),
        "env_gate_on": {"SFU_DELTA_ROOT": str(ROOT), "SFU_SEISMIC_SHARD_MANIFEST": "",
                        "SFU_SEISMIC_STAGE_DIR": "", "SFU_META_STAGE_DIR": "", "SFU_THINCLIENT_ORDINALS": "",
                        "SFU_SEISMIC_FEDERATION": "parallel", "SFU_SPLADE_BACKEND": "seismic"},
        "env_gate_off": {"SFU_DELTA_ROOT": "", "SFU_SEISMIC_SHARD_MANIFEST": str(BASE_MANIFEST),
                         "SFU_SEISMIC_STAGE_DIR": "", "SFU_META_STAGE_DIR": "", "SFU_THINCLIENT_ORDINALS": "",
                         "SFU_SEISMIC_FEDERATION": "parallel", "SFU_SPLADE_BACKEND": "seismic"},
        "env_note": "blank strings, not unset (lib.config re-injects unset keys from .env); livedocs reads "
                    "its ordinal_dir from generations.json, so SFU_THINCLIENT_ORDINALS stays blank when serving",
        "doc_ids_path": str(FIX / "sample.json") + " (key 'ids', 50,000 W-ids, sampling order)",
        "doc_ids_sha256": info["ids_sha256"],
        "delta_records_path": str(FIX / "corpus_a.jsonl"),
        "base_copies_path": str(FIX / "base_copies.jsonl") + " (sidecar abstract before the update + ordinal)",
        "title_sample_path": str(FIX / "title_sample.json") + " (key 'order' = permuted ids, 'titles' aligned)",
        "title_sample_rule": "prefix of the permuted list; M2 uses the first N (N recorded in the M2 results)",
        "sampling_rule": "see harness header 'Corpus (a) fixture'", "appended_sentence": APPENDED_SENTENCE,
        "sidecar_text_source": str(SIDECAR) + " via lib.thinclient.abstracts.AbstractStore.fetch (the only hot "
                               "section; corpus (a) is social_sciences__recent only)",
        "population": {"section": SECTION, "size": info["population_size"], "walked": info["walked"],
                       "rejections": info["rejections"]},
        "verify": rec["verify"], "smoke": rec["smoke"].get("result"),
        "base_manifest": str(BASE_MANIFEST), "ordinals": str(ORDS),
        "rule": "do not delete or rebuild the root; if it must change, READY is removed first and this file says so",
    }
    (FIX / "READY.json").write_text(json.dumps(ready, indent=1, default=str))
    (FIX / "READY").write_text(utc() + "\n")
    print(json.dumps({"READY": str(FIX / "READY.json")}))
    return 0


# ── children (load a retriever) ────────────────────────────────────────────
class _WarnCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record):
        try:
            self.records.append(f"{record.name}: {record.getMessage()}"[:400])
        except Exception:
            pass


def load_retriever(src: str, arm: str, want_ce: bool) -> tuple:
    """Load + health-assert a retriever in THIS process (env set by the parent)."""
    sys.path.insert(0, src)
    cap = _WarnCapture()
    logging.getLogger().addHandler(cap)
    health: dict = {"ok": True, "problems": [], "arm": arm, "env": {k: os.environ.get(k) for k in
                                                                   (*BLANK_ENV, "SFU_SEISMIC_FEDERATION",
                                                                    "SFU_SPLADE_BACKEND")}}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    if os.environ.get("SFU_SEISMIC_STAGE_DIR") or os.environ.get("SFU_META_STAGE_DIR"):
        sys.exit("a stage dir is set in the child env; refusing to load")
    import lib.tools as tools
    from lib.opensearch_retriever import encode_splade
    if logging.getLogger("sfu_library_mcp").propagate is False:
        logging.getLogger("sfu_library_mcp").addHandler(cap)
    retriever = tools._get_thinclient_retriever()
    if retriever is None:
        bad("search backend is not thinclient")
        return None, None, health, cap
    retriever._fetch_remote_abstracts = lambda ids: {}
    t0 = time.perf_counter()
    retriever._load()
    health["load_s"] = round(time.perf_counter() - t0, 1)
    try:
        qv = encode_splade("warm up query for sparse encoder", retriever.splade_model_path)
        health["splade_terms"] = len(qv or {})
        if not qv:
            bad("encode_splade returned empty")
    except Exception as exc:
        bad(f"encode_splade raised {exc!r}")
    if want_ce:
        from lib.reranker import _get_cross_encoder
        ce = _get_cross_encoder()
        health["cross_encoder"] = type(ce).__name__ if ce is not None else None
        if ce is None:
            bad("cross-encoder not loaded")
    try:
        backend = retriever._seismic_backend()
    except Exception as exc:
        backend = None
        bad(f"seismic backend load raised {exc!r}")
    want = N_BASE_SHARDS + (1 if arm == "delta" else 0)
    if backend is not None:
        health["backend_class"] = type(backend).__name__
        health["n_shards"] = len(backend.shards)
        if type(backend).__name__ != "ParallelSeismicBackend":
            bad(f"backend {type(backend).__name__} != ParallelSeismicBackend")
        if len(backend.shards) != want or any(s is None for s in backend.shards):
            bad(f"shards {len(backend.shards)} != {want} or a shard is None")
        health["manifest"] = getattr(retriever, "_seismic_manifest", None)
    d = retriever._delta
    if arm == "delta":
        if d is None:
            bad("delta layer not loaded")
        else:
            info = d.info()
            health["delta_info"] = info
            if [g["gen"] for g in d.generations] != [1]:
                bad(f"delta generations {[g['gen'] for g in d.generations]} != [1]")
            if not info.get("livedocs") or info["livedocs"]["popcount"] != N_DOCS or not info["livedocs"]["per_shard"]:
                bad(f"livedocs not as expected: {info.get('livedocs')}")
            if info.get("buffer_docs"):
                bad(f"buffer not empty: {info.get('buffer_docs')}")
            if backend is not None:
                origins = d.shard_origins(len(backend.shards), health.get("manifest"))
                health["shard_origins"] = origins
                if origins != [None] * N_BASE_SHARDS + [1]:
                    bad(f"shard origins {origins}")
    elif d is not None:
        bad("delta layer loaded in the gate-off arm")
    return retriever, backend, health, cap


def smoke(args) -> int:
    info = json.loads((FIX / "sample.json").read_text())
    retriever, backend, health, cap = load_retriever(args.src, "delta", want_ce=True)
    out = {"utc": utc(), "health": health}
    if health["ok"]:
        q = info["titles"][info["query_order"][0]]
        t0 = time.perf_counter()
        res = retriever.search_rrf(q, top_k=50)
        out["search_rrf"] = {"query": q, "target": info["query_order"][0], "n": len(res),
                             "top5": [r.get("openalex_id") for r in res[:5]],
                             "target_rank": next((i for i, r in enumerate(res) if r.get("openalex_id") ==
                                                  info["query_order"][0]), None),
                             "wall_s": round(time.perf_counter() - t0, 2), "timings_valid": False}
        if not res:
            health["ok"] = False
            health["problems"].append("search_rrf returned nothing")
    out["warnings"] = cap.records[-50:]
    sig = [w for w in cap.records if any(s in w for s in SIGNATURES)]
    if sig:
        health["ok"] = False
        health["problems"].append(f"warning signatures: {sig[:5]}")
    (FIX / "smoke.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, default=str)[:3000])
    return 0 if health["ok"] else 3


def run_queries(retriever, backend, ids: list[str], titles: dict, rows_path: Path, arm: str,
                deadline: float | None) -> dict:
    """One SPLADE-leg call per id with per-shard capture; rows appended to
    `rows_path` (resumable: ids already there are skipped)."""
    done = set()
    if rows_path.exists():
        for line in rows_path.open():
            try:
                done.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                pass
    cap: dict = {}
    orig = getattr(backend, "_shard_result_filter", None)
    if arm == "delta" and orig is None:
        raise RuntimeError("delta arm without the livedocs per-shard filter")

    def wrapped(per_shard):
        cap["pre"] = per_shard
        out = orig(per_shard) if orig is not None else per_shard
        cap["post"] = out
        return out
    backend._shard_result_filter = wrapped
    n_new = 0
    with rows_path.open("a") as fh:
        for qi, did in enumerate(ids):
            if did in done:
                continue
            if deadline and time.time() > deadline:
                return {"stopped_at_deadline": True, "new_rows": n_new}
            cap.clear()
            t0 = time.perf_counter()
            res = retriever._splade_leg(titles[did], TOP_K, None)
            wall = time.perf_counter() - t0
            ranked = [d for d, _ in res]
            rank = ranked.index(did) if did in ranked else None
            pre, post = cap.get("pre") or [], cap.get("post") or []

            def where(per):
                out = []
                for pos, r in enumerate(per):
                    for j, t in enumerate(r or []):
                        if t[2] == did:
                            out.append([pos, j, float(t[1])])
                            break
                return out
            row = {"qi": qi, "id": did, "rank": rank, "score": float(res[rank][1]) if rank is not None else None,
                   "n_res": len(res), "pre": where(pre), "post": where(post), "captured": "post" in cap,
                   "wall_ms": round(wall * 1000, 1)}
            fh.write(json.dumps(row) + "\n")
            n_new += 1
            if n_new % 200 == 0:
                fh.flush()
                print(json.dumps({"utc": utc(), "arm": arm, "done": len(done) + n_new, "last_ms": row["wall_ms"]}),
                      flush=True)
    return {"stopped_at_deadline": False, "new_rows": n_new}


def arm_child(args) -> int:
    info = json.loads((FIX / "sample.json").read_text())
    retriever, backend, health, cap = load_retriever(args.src, args.arm, want_ce=False)
    tag = args.tag or args.arm
    hp = WORK / f"health_{tag}.json"
    hp.write_text(json.dumps(health, indent=1, default=str))
    if not health["ok"]:
        print(json.dumps(health, default=str))
        return 3
    order = info["query_order"]
    ids = order[-50:] if args.probe else order[:args.n]
    deadline = ts(args.deadline) if args.deadline else None
    t0 = time.time()
    st = run_queries(retriever, backend, ids, info["titles"], WORK / f"rows_{tag}.jsonl", args.arm, deadline)
    st.update({"wall_s": round(time.time() - t0, 1), "finished": utc(), "warnings_tail": cap.records[-30:],
               "warning_signatures": [w for w in cap.records if any(s in w for s in SIGNATURES)][:20]})
    (WORK / f"status_{tag}.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps(st, default=str)[:2000])
    return 0


def drive_arm(args) -> int:
    mem_ok()
    commit = args.commit or git_commit()
    snap = snapshot(commit)
    tag = "probe" if args.probe else args.arm
    log = WORK / f"log_{tag}.txt"
    cmd = ["nice", "-n", "10", "taskset", "-c", "8-15", str(REPO / ".venv/bin/python3"), __file__,
           "arm-child", "--arm", args.arm, "--src", str(snap / "src"), "--n", str(args.n), "--tag", tag]
    if args.probe:
        cmd.append("--probe")
    if args.deadline:
        cmd += ["--deadline", args.deadline]
    meta = {"started": utc(), "commit": commit, "cmd": cmd, "host_start": host_state()}
    with open(log, "a") as fh:
        rc = subprocess.call(cmd, cwd=str(REPO), env=child_env(args.arm), stdout=fh, stderr=subprocess.STDOUT)
    meta.update({"rc": rc, "finished": utc(), "host_end": host_state(), "scan": scan_log(log)})
    (WORK / f"drive_{tag}.json").write_text(json.dumps(meta, indent=1, default=str))
    if args.probe:
        rows = [json.loads(x) for x in (WORK / "rows_probe.jsonl").open()]
        ms = sorted(r["wall_ms"] for r in rows)
        p50 = ms[len(ms) // 2] / 1000
        avail = ts("2026-09-30T22:40:00Z") - time.time() - 1800
        n = int(min(QUERY_N_MAX, 1000 * int(avail / (2 * 1.3 * p50) / 1000)))
        n = max(2000, n)
        probe = {"n_probe": len(rows), "p50_s": p50, "avail_s": round(avail), "N": n, "utc": utc(),
                 "timings_valid": False}
        (WORK / "probe.json").write_text(json.dumps(probe, indent=1))
        print(json.dumps(probe))
    return rc


# ── exact overlap on the delta shard ───────────────────────────────────────
def exact(args) -> int:
    if args.params == "e8":
        os.environ["SFU_SEISMIC_PREFLOOR"] = "2"
    else:
        os.environ.pop("SFU_SEISMIC_PREFLOOR", None)
    import numpy as np
    import scipy.sparse as sp
    sys.path.insert(0, args.src)
    sys.path.insert(0, str(REPO / "scripts/seismic_testbed"))
    from e6_forward_codec_proto import load_queries
    from lib.opensearch_retriever import encode_splade
    import seismic
    gi = json.loads((ROOT / "g0001/generation.json").read_text())
    mmap_dir = ROOT / "g0001" / gi["seismic"]["mmap_dir"]
    jsonl = ROOT / "g0001/seismic/delta_g0001.jsonl"
    info = json.loads((FIX / "sample.json").read_text())
    sets = {"topics120": [r["query"] for r in json.loads((REPO / "data/sfu_eval_queries.json").read_text())],
            "diverse100": load_queries(100, REPO / "data/eval_results/diverse_queries.json"),
            "titles1000": [info["titles"][i] for i in info["query_order"][:1000]]}
    assert len(sets["topics120"]) == 120 and len(sets["diverse100"]) == 100 and len(sets["titles1000"]) == 1000
    doc_ids, vocab, rows, cols, vals = [], {}, [], [], []
    for line in jsonl.open():
        d = json.loads(line)
        r = len(doc_ids)
        doc_ids.append(d["id"])
        for t, w in d["vector"].items():
            rows.append(r)
            cols.append(vocab.setdefault(t, len(vocab)))
            vals.append(float(w))
    M = sp.csr_matrix((np.array(vals, dtype=np.float64), (rows, cols)), shape=(len(doc_ids), len(vocab)))
    enc = {name: [dict(sorted((encode_splade(q, "models/splade_onnx_fp16") or {}).items(),
                              key=lambda x: -x[1])[:64]) for q in qs] for name, qs in sets.items()}
    k = 200 if args.params == "e8" else max(2 * TOP_K, 100)
    idx = seismic.MmapSeismicIndex(str(mmap_dir))
    sd = seismic.get_seismic_string()
    rec = {"params": args.params, "utc": utc(), "mmap_dir": str(mmap_dir), "jsonl": str(jsonl),
           "forward_format": idx.forward_format, "shard_len": int(idx.len), "jsonl_docs": len(doc_ids),
           "vocab": len(vocab), "nnz": int(M.nnz),
           "search": {"engine": "MmapSeismicIndex", "k": k, "k_prime": k, "query_cut": "len(terms)",
                      "heap_factor": 0.8, "query_terms": 64,
                      "SFU_SEISMIC_PREFLOOR": os.environ.get("SFU_SEISMIC_PREFLOOR")},
           "value_scale_note": "jsonl = float SPLADE weights (DocRecord.sparse_field); served shard = dotvbyte v2 "
                               "--value-scale perdoc (generation.build_seismic_shard)", "sets": {}}
    passed = True
    for name, qs in enc.items():
        ov, ident_o, ident_s, empty, denoms = [], 0, 0, 0, []
        for terms in qs:
            if not terms:
                empty += 1
                continue
            qv = np.zeros(len(vocab))
            for t, w in terms.items():
                j = vocab.get(t)
                if j is not None:
                    qv[j] = w
            sc = M @ qv
            pos = np.flatnonzero(sc > 0)
            top = pos[np.lexsort((np.array([doc_ids[i] for i in pos]), -sc[pos]))][:10] if len(pos) else []
            ex = [doc_ids[i] for i in top]
            r = idx.search(query_id="q", query_components=np.array(list(terms.keys()), dtype=sd),
                           query_values=np.array([float(v) for v in terms.values()], dtype=np.float32),
                           k=k, query_cut=len(terms), heap_factor=0.8)
            got = [d for (_q, _s, d) in r][:10]
            den = len(ex)
            if den == 0:
                empty += 1
                continue
            denoms.append(den)
            ov.append(len(set(got) & set(ex)) / den)
            ident_o += got[:den] == ex
            ident_s += set(got[:den]) == set(ex)
        m = float(np.mean(ov)) if ov else None
        rec["sets"][name] = {"n": len(ov), "empty_or_no_positive": empty, "overlap10_mean": m and round(m, 5),
                             "overlap10_min": min(ov) if ov else None, "identical_top10_ordered": ident_o,
                             "identical_top10_set": ident_s, "denominator_lt10": sum(1 for d in denoms if d < 10),
                             "pass": (m is not None and m >= 0.99)}
        passed &= rec["sets"][name]["pass"]
    rec["verdict"] = "PASS" if passed else "FAIL"
    rec["finished"] = utc()
    (WORK / f"exact_{args.params}.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))
    return 0


def drive_exact(args) -> int:
    commit = args.commit or git_commit()
    snap = snapshot(commit)
    log = WORK / f"log_exact_{args.params}.txt"
    env = child_env(None)
    if args.params == "e8":
        env["SFU_SEISMIC_PREFLOOR"] = "2"
    else:
        env.pop("SFU_SEISMIC_PREFLOOR", None)
    cmd = ["nice", "-n", "10", "taskset", "-c", "8-15", str(REPO / ".venv/bin/python3"), __file__,
           "exact-child", "--params", args.params, "--src", str(snap / "src")]
    with open(log, "w") as fh:
        rc = subprocess.call(cmd, cwd=str(REPO), env=env, stdout=fh, stderr=subprocess.STDOUT)
    (WORK / f"drive_exact_{args.params}.json").write_text(json.dumps(
        {"commit": commit, "rc": rc, "cmd": cmd, "scan": scan_log(log), "utc": utc()}, indent=1))
    return rc


# ── record ─────────────────────────────────────────────────────────────────
def summarise_arm(rows: list[dict], arm: str) -> dict:
    out = {"n": len(rows), "empty_results": sum(1 for r in rows if not r["n_res"]),
           "capture_missing": sum(1 for r in rows if not r["captured"])}
    for k in (10, 50):
        hit_any = [r for r in rows if r["rank"] is not None and r["rank"] < k]
        out[f"any_copy_hits@{k}"] = len(hit_any)
        if arm == "delta":
            good = [r for r in hit_any if any(p[0] == N_BASE_SHARDS for p in r["post"])
                    and not any(p[0] < N_BASE_SHARDS for p in r["post"])
                    and any(p[0] == N_BASE_SHARDS and abs(p[2] - r["score"]) < 1e-6 for p in r["post"])]
            out[f"delta_copy_hits@{k}"] = len(good)
            out[f"recall@{k}"] = round(len(good) / len(rows), 5) if rows else None
        else:
            out[f"recall@{k}"] = round(len(hit_any) / len(rows), 5) if rows else None
    if arm == "delta":
        out["mask_leak_base_shard_post_filter"] = sum(1 for r in rows if any(p[0] < N_BASE_SHARDS for p in r["post"]))
        out["base_copy_seen_pre_filter"] = sum(1 for r in rows if any(p[0] < N_BASE_SHARDS for p in r["pre"]))
        out["delta_copy_in_delta_shard_topk'"] = sum(1 for r in rows if any(p[0] == N_BASE_SHARDS for p in r["post"]))
    else:
        out["held_by_base_shard"] = sum(1 for r in rows if r["post"])
    return out


def record(args) -> int:
    fix = json.loads((FIX / "build_fixture.json").read_text())
    ready = json.loads((FIX / "READY.json").read_text()) if (FIX / "READY.json").exists() else None
    load = lambda p: [json.loads(x) for x in p.open()] if p.exists() else []  # noqa: E731
    base = {r["id"]: r for r in load(WORK / "rows_base.jsonl")}
    delta = {r["id"]: r for r in load(WORK / "rows_delta.jsonl")}
    probe = json.loads((WORK / "probe.json").read_text()) if (WORK / "probe.json").exists() else None
    info = json.loads((FIX / "sample.json").read_text())
    n_target = probe["N"] if probe else None
    common = [i for i in info["query_order"][:n_target or 0] if i in base and i in delta]
    sb = summarise_arm([base[i] for i in common], "base")
    sd = summarise_arm([delta[i] for i in common], "delta")
    ratio = (sd["recall@10"] / sb["recall@10"]) if sb.get("recall@10") else None
    ratio50 = (sd["recall@50"] / sb["recall@50"]) if sb.get("recall@50") else None
    both = sum(1 for i in common if delta[i]["rank"] is not None and delta[i]["rank"] < 10)
    trans = {"base_hit_delta_miss@10": sum(1 for i in common if base[i]["rank"] is not None and base[i]["rank"] < 10
                                           and not (delta[i]["rank"] is not None and delta[i]["rank"] < 10)),
             "base_miss_delta_hit@10": sum(1 for i in common if not (base[i]["rank"] is not None and base[i]["rank"] < 10)
                                           and delta[i]["rank"] is not None and delta[i]["rank"] < 10)}
    ex = {p: json.loads((WORK / f"exact_{p}.json").read_text()) for p in ("e8", "served")
          if (WORK / f"exact_{p}.json").exists()}
    partial = n_target is None or len(common) < n_target
    v1 = None if ratio is None else ("PASS" if ratio >= 0.95 else "FAIL")
    leak = sd.get("mask_leak_base_shard_post_filter")
    out = {
        "item": "delta-ingest M2: delta-shard recall on corpus (a)", "date": "2026-09-30",
        "harness": "scripts/experiments/eval_delta_ingest_m2_delta_recall.py",
        "plan_row": "docs/delta_ingest/03_SPIKE_PLAN.md M2",
        "metric_verbatim": "for corpus (a): fraction of updated docs returned by the SPLADE leg from the delta shard "
                           "for their own title-as-query, vs the same docs served from the base shard before the update",
        "bar_verbatim": ">= 0.95 of the base's own-recall; per-shard overlap@10 vs an exact dot product >= 0.99 "
                        "(the E8 bar)",
        "verdicts": {
            "bar1_own_recall_ratio@10": {"value": ratio and round(ratio, 5), "bar": 0.95,
                                         "verdict": (v1 + (" (PARTIAL)" if partial else "")) if v1 else "NOT RUN"},
            "bar2_exact_overlap@10_e8": {"verdict": ex["e8"]["verdict"] if "e8" in ex else "NOT RUN",
                                         "per_set": {k: v["overlap10_mean"] for k, v in ex["e8"]["sets"].items()}
                                         if "e8" in ex else None},
            "mask_leak": {"value": leak, "must_be": 0,
                          "verdict": None if leak is None else ("PASS" if leak == 0 else "FAIL")},
        },
        "own_recall": {"n_target": n_target, "n_common": len(common), "base": sb, "delta": sd,
                       "ratio@10": ratio and round(ratio, 5), "ratio@50": ratio50 and round(ratio50, 5),
                       "delta_any_copy_hits@10": both, "transitions": trans,
                       "rows_files": [str(WORK / "rows_base.jsonl"), str(WORK / "rows_delta.jsonl")]},
        "exact_overlap": ex, "probe": probe,
        "fixture": {"root": str(ROOT), "ready": ready and {k: ready[k] for k in
                                                           ("published_utc", "fixture_commit", "doc_ids_sha256",
                                                            "population", "appended_sentence", "verify")},
                    "build": {k: fix.get(k) for k in ("commit", "started", "finished", "sample", "verify")},
                    "ingest_out": (fix.get("ingest") or {}).get("out"), "flush_out_keys":
                        sorted(((fix.get("flush") or {}).get("out") or {}).keys()),
                    "ingest_scan": (fix.get("ingest") or {}).get("scan"),
                    "flush_scan": (fix.get("flush") or {}).get("scan"), "smoke": fix.get("smoke")},
        "health": {t: json.loads((WORK / f"health_{t}.json").read_text()) for t in ("base", "delta", "probe")
                   if (WORK / f"health_{t}.json").exists()},
        "drives": {t: json.loads((WORK / f"drive_{t}.json").read_text()) for t in ("base", "delta", "probe")
                   if (WORK / f"drive_{t}.json").exists()},
        "status": {t: json.loads((WORK / f"status_{t}.json").read_text()) for t in ("base", "delta", "probe")
                   if (WORK / f"status_{t}.json").exists()},
        "timings_valid": False,
        "timings_note": "host shared with the in-place spike's B7 (cores 0-7, latency lock) and S0-2 (~19 GB), and "
                        "the M3/M8 agents; every wall/latency field is not a deliverable",
        "notes": args.note or [],
        "recorded_utc": utc(), "record_commit": git_commit(),
    }
    RESULT.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out["verdicts"], indent=1))
    print(RESULT)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-fixture")
    s = sub.add_parser("smoke")
    s.add_argument("--src", default=str(REPO / "src"))
    for name in ("arm", "probe"):
        a = sub.add_parser(name)
        a.add_argument("--arm", choices=["base", "delta"], default="delta")
        a.add_argument("--n", type=int, default=QUERY_N_MAX)
        a.add_argument("--deadline", default="2026-09-30T23:15:00Z")
        a.add_argument("--commit", default=None)
    c = sub.add_parser("arm-child")
    c.add_argument("--arm", choices=["base", "delta"], required=True)
    c.add_argument("--src", required=True)
    c.add_argument("--n", type=int, default=QUERY_N_MAX)
    c.add_argument("--tag", default=None)
    c.add_argument("--probe", action="store_true")
    c.add_argument("--deadline", default=None)
    e = sub.add_parser("exact")
    e.add_argument("--params", choices=["e8", "served"], required=True)
    e.add_argument("--commit", default=None)
    ec = sub.add_parser("exact-child")
    ec.add_argument("--params", choices=["e8", "served"], required=True)
    ec.add_argument("--src", required=True)
    r = sub.add_parser("record")
    r.add_argument("--note", action="append")
    args = ap.parse_args(argv)
    if args.cmd == "build-fixture":
        return build_fixture(args)
    if args.cmd == "smoke":
        return smoke(args)
    if args.cmd == "arm":
        args.probe = False
        return drive_arm(args)
    if args.cmd == "probe":
        args.probe = True
        args.arm = "delta"
        return drive_arm(args)
    if args.cmd == "arm-child":
        return arm_child(args)
    if args.cmd == "exact":
        return drive_exact(args)
    if args.cmd == "exact-child":
        return exact(args)
    if args.cmd == "record":
        return record(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
