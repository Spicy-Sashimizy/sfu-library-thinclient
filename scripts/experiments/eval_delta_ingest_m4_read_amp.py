#!/usr/bin/env python3
"""Delta-ingest M4: read amplification per live delta generation
(docs/delta_ingest/03_SPIKE_PLAN.md M4; arm A1 of the in-place spike,
docs/archive/inplace_update/05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md section 6; that spike
closed MEASURED 2026-09-30, M4 stands on its own bar in 03_SPIKE_PLAN.md).

PRE-REGISTERED (bars copied verbatim from 03_SPIKE_PLAN.md M4, written into
this header 2026-09-29 before any M4 number existed; operational definitions
below were also fixed before the run):

  metric : `search_rrf` p50/p95 with 0, 1, 4, 8 live generations of corpus (b)
           split evenly, before and after `compact`
  bar    : p50 growth <= +8 ms per generation *est.* budget, and compaction
           returns to within 5% of the 1-generation arm
  GO line of the in-place spike (05 brief section 6, Stage 0): generation tax
           >= 3 ms p50 per generation.

Operational definitions (fixed before the run):
  corpus (b)   : the OpenAlex records of snapshot partition
                 updated_date=2026-09-15/part_0001 already ingested and
                 GPU-encoded by item F (M6) into
                 /var/tmp/sfu_delta_F_20260929/root/desktop_gpu/ledger.sqlite
                 (read-only here), MINUS every id present in the served base
                 meta.sqlite (plan: "absent from meta.sqlite"). The partition
                 yields fewer than the plan's 200k; all remaining ids are used.
                 Order = ledger rowid (arrival order); "split evenly" = N
                 contiguous chunks whose sizes differ by at most one.
  build        : per arm a fresh SFU_DELTA_ROOT under
                 /home/vscode/work/inplace_update/m4/, built only through
                 supported spike calls: ledger.stage -> BufferWriter.upsert/commit
                 -> generation.freeze_buffer -> BufferWriter.delete/commit (the
                 CLI `flush` sequence), profile desktop_gpu, base shard manifest
                 = a frozen copy of the staged served manifest
                 (/var/tmp/seismic_stage/staged_manifest.json -> WORK/base_manifest.json,
                 the same dv-v2 e5 files the served process maps). The
                 empty-but-present buffer section is therefore part of every
                 delta arm (the real post-flush state).
                 Compacted arms: copytree of the 4- and 8-generation roots,
                 generation.publish (repoints paths), then generation.compact
                 over all their generations.
  arms         : n0 (gate off, SFU_SEISMIC_SHARD_MANIFEST = WORK/base_manifest.json),
                 n1, n4, n8, n4c, n8c (SFU_DELTA_ROOT set, manifest env blank so
                 the composed delta manifest serves). SFU_SEISMIC_STAGE_DIR is
                 set to "" in every child (blank, not unset: lib.config's .env
                 loader re-injects unset keys) and the child aborts if any stage
                 dir is visible: the base manifest already points at the staged
                 copies, and `_stage_shards_local` on a manifest whose shards
                 already live in the stage dir DELETES them (src == dst; found
                 2026-09-29 by this harness's first pilot, which removed the
                 staged shard 0 copy; it was re-staged from the read-only source
                 with the product's own staging call). meta.sqlite is served as
                 in the current serving env (unstaged).
  federation   : parallel AND sequential (SFU_SEISMIC_FEDERATION set explicitly).
  queries      : the 120 natural topics of
                 data/eval_results/dense_ablation_qrels_20260817.json (as M1),
                 `retriever.search_rrf(q, top_k=50)`, remote abstracts stubbed to {}.
  per process  : one warm-up pass over the 120 topics (discarded), then
                 --passes measured passes. Health asserted before the first
                 measured query (SPLADE encoder non-empty, SEISMIC backend of the
                 requested class with 8 + n_gen shards and none missing, delta
                 layer with the expected generations, cross-encoder loaded) and
                 checked after (no fallback/ENOMEM warnings, every query reached
                 the SEISMIC traverse). A failed check marks the arm DEGRADED and
                 its numbers are not used.
  rounds       : --rounds rounds; each round runs every (arm, federation) once
                 in an order shuffled with a recorded seed, so drift shows up
                 as round-to-round spread.
  p50 / p95    : over all measured queries of an arm pooled across rounds
                 (nearest-rank on sorted list); per-round p50s reported.
  slope        : PRIMARY = OLS slope of arm p50 (pooled) vs N over N in
                 {0,1,4,8}, parallel backend (the served default on this host).
                 Spread = min/max of the same slope computed per round.
                 Secondary: OLS over {1,4,8} (marginal cost of a generation
                 without the fixed cost of turning the layer on), (p50(8)-p50(1))/7,
                 and the per-query paired median of (t_N - t_0)/N.
                 Bar verdict: PASS iff primary slope <= 8.0 ms; also reported
                 against the 3.0 ms GO line (>= 3.0 ms -> GO input met).
  compaction   : PASS iff |p50(n8c)/p50(n1) - 1| <= 0.05 (parallel); n4c and
                 sequential reported with the same rule.

REVISION 2026-09-29 ~09:20Z, BEFORE any measured run (bars unchanged; only
the arm scheduling changed). Two pilots (not results; files under
WORK/pilot/) showed this host serving `search_rrf` at 8-29 s per query with
5k-87k major faults per query even on the third repetition of the same
query, and another agent at ~14 cores; the served baseline recorded by
warmcache_metric3_isolated_20260925.json is p50 3.56 s / p95 8.9 s. At that
noise, one process per arm (each with its own cold/warm history) cannot
resolve a few ms per generation. The PRIMARY run is therefore `inproc`:
  * one process per federation holds SIX ThinClientRetriever instances, one
    per arm (n0, n1, n4, n8, n4c, n8c), each loaded with its own env
    (SFU_DELTA_ROOT / SFU_SEISMIC_SHARD_MANIFEST set before its `_load` and
    SEISMIC backend open; both are read only there). Base pages are shared
    through the page cache, exactly as they would be in one serving process.
  * health checks per retriever as above; models are process singletons.
  * warm-up pass: every query through every arm in fixed order (discarded).
  * measured passes (--passes, default 2): for each query, one PRIME call on
    the n0 retriever (discarded, recorded), then all six arms in an order
    shuffled per query with a recorded seed; the position is recorded so an
    order effect can be estimated.
  * a quiet check (load1 <= 6 and no other process > 50% CPU or > 30 MB/s
    read) runs before every 10th query; if not quiet it waits up to 120 s and
    records the wait; every query row carries the last host sample.
  * primary metric and verdict rules are unchanged (arm p50 over all
    measured calls; OLS of p50 vs N over {0,1,4,8}); added: the paired
    per-query slope (OLS of that query's arm latencies vs N) with its median
    and a bootstrap 95% CI over queries (2000 resamples, seed 20260929), and
    the component attribution described in `serial_delta` / `seismic_inc`.
The per-process `drive`/`child` path stays for M5 reuse and as a fallback.

REVISION 2, 2026-09-29 ~20:55Z (after the parallel process of run
`inproc_main` had completed its warm-up and first measured pass; before the
sequential process started; bars unchanged). The first measured pass showed
that priming on the n0 retriever itself leaves THAT instance warm (its own
SQLite connection caches for meta/abstracts on 9p and its own shard
mappings): n0 median traverse 48 ms vs 193 ms, hydration 5 vs 77 ms, 5 vs 723
major faults per call, n0 p50 ~370 ms below every delta arm. That biases n0
low and inflates the {0,1,4,8} slope. From this revision the PRIME call runs
on a SEPARATE seventh retriever configured like n0 (`--prime-mode separate`,
the default) so no measured arm is instance-warm. The parallel file of run
`inproc_main` (prime-mode n0) is kept and reported with its n0 arm flagged
BIASED; its n1/n4/n8/n4c/n8c arms are mutually comparable. A parallel re-run
with the separate prime (arms n0,n1,n4,n8) supplies the primary slope.

Run:
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m4_read_amp.py prepare
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m4_read_amp.py build --n 1   (4, 8)
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m4_read_amp.py compact --n 8 (4)
  09 follow-up roots (docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md section 3, added 2026-10-01):
  ... build --n 1 --layout single --reuse-seismic-from root_n1     (-> root_s1; per_era -> root_e1)
  ... compact --n 8 --layout single --seismic-threads 4            (-> root_s8c, log compact_s8.json)
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m4_read_amp.py drive --rounds 3   (fallback)
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m4_read_amp.py inproc-drive           (primary)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import resource
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path("/home/vscode/work/inplace_update/m4")
F_LEDGER = Path("/var/tmp/sfu_delta_F_20260929/root/desktop_gpu/ledger.sqlite")
STAGED_MANIFEST = Path("/var/tmp/seismic_stage/staged_manifest.json")
BASE_MANIFEST = WORK / "base_manifest.json"
CORPUS = WORK / "corpus_b.json"
TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
LOCK = "/tmp/sfu_latency_measure.lock"
TOP_K = 50
N_BASE_SHARDS = 8
ARMS = {"n0": 0, "n1": 1, "n4": 4, "n8": 8, "n4c": 1, "n8c": 1}
ENV_DROP = ("SFU_DELTA_ROOT", "SFU_SEARCH_SPECULATIVE_RERANK", "SFU_SEISMIC_SHARD_MANIFEST",
            "SFU_SEISMIC_STAGE_DIR", "SFU_SEISMIC_FEDERATION")
SIGNATURES = ("Cannot allocate memory", "CrossEncoder unavailable", "Failed to load embedding model",
              "falling back to BM25F", "SPLADE encoder failed", "SEISMIC SPLADE leg failed",
              "delta buffer sparse encode failed", "Traceback", "delta layer off",
              "SFU_SEISMIC_SHARD_MANIFEST is set", "MemoryError", "WI-10")


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def host_state() -> dict:
    out = {"utc": utc(), "loadavg": list(os.getloadavg())}
    try:
        mem = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            if k in ("MemTotal", "MemAvailable", "Cached", "SwapFree", "SwapTotal"):
                mem[k] = round(int(v.split()[0]) / 1024 ** 2, 2)
        out["mem_gb"] = mem
    except OSError:
        pass
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        u, m = g.stdout.strip().split(",")[:2]
        out["gpu"] = {"util_pct": int(u), "mem_used_mib": int(m)}
    except Exception as exc:
        out["gpu"] = f"unavailable: {type(exc).__name__}"
    try:
        out["busy_procs_gt20pct"] = busy_procs(1.0, 20.0)
    except Exception as exc:
        out["busy_procs_gt20pct"] = [f"unavailable: {exc!r}"]
    return out


def _proc_ticks() -> dict:
    ticks = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            s = open(f"/proc/{d}/stat").read()
            rest = s[s.rfind(")") + 2:].split()
            rb = 0
            try:
                for line in open(f"/proc/{d}/io"):
                    if line.startswith("rchar:"):
                        rb = int(line.split()[1])
            except OSError:
                pass
            ticks[int(d)] = (int(rest[11]) + int(rest[12]), rb)
        except (OSError, IndexError, ValueError):
            pass
    return ticks


def busy_procs(window_s: float, min_pct: float, min_read_mbps: float = 30.0) -> list[str]:
    """Processes above min_pct CPU or min_read_mbps read (rchar, includes
    page-cache hits) over a window_s sample (instantaneous, not ps's lifetime
    average), excluding this process and its parent; 'pid cpu% cmd [read MB/s]'."""
    hz = os.sysconf("SC_CLK_TCK")
    a = _proc_ticks()
    time.sleep(window_s)
    b = _proc_ticks()
    out = []
    for pid, (t, rb) in b.items():
        t0, rb0 = a.get(pid, (t, rb))
        pct_ = (t - t0) / hz / window_s * 100.0
        mbps = (rb - rb0) / 1e6 / window_s
        if (pct_ > min_pct or mbps > min_read_mbps) and pid not in (os.getpid(), os.getppid()):
            try:
                cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                cmd = "?"
            out.append(f"{pid} {pct_:.0f} {cmd[:140]} [read {mbps:.0f} MB/s]")
    return sorted(out, key=lambda s: -float(s.split()[1]))


def quiet_gate(max_wait_s: int, load1_max: float = 4.0, poll_s: int = 15) -> dict:
    """Wait (holding the lock) until load1 <= load1_max and no other process
    uses > 50% CPU; record what was seen. Proceeds un-quiet after max_wait_s."""
    t0 = time.time()
    samples = []
    while True:
        hs = host_state()
        busy = [p for p in hs.get("busy_procs_gt20pct", [])
                if not p.startswith("unavailable") and (float(p.split()[1]) > 50.0 or
                                                        float(p.rsplit("[read ", 1)[1].split()[0]) > 30.0)]
        samples.append({"utc": hs["utc"], "load1": hs["loadavg"][0], "busy_gt50pct": busy})
        if hs["loadavg"][0] <= load1_max and not busy:
            return {"quiet": True, "waited_s": round(time.time() - t0, 1), "samples": samples[-3:]}
        if time.time() - t0 >= max_wait_s:
            return {"quiet": False, "waited_s": round(time.time() - t0, 1), "samples": samples[-5:]}
        time.sleep(poll_s)


def load_topics() -> list[tuple[str, str]]:
    topics = json.loads(TOPICS.read_text())["topics"]
    return [(k, v["natural"]) for k, v in topics.items()]


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    i = max(0, min(len(s) - 1, int(round(p / 100.0 * len(s) + 0.5)) - 1))
    return round(s[i], 2)


def ols(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den, 3) if den else None


def _spike_imports():
    sys.path.insert(0, str(REPO / "src"))
    sys.path.insert(0, str(REPO))
    from spike.delta_ingest.base import DEFAULT_INDEX_ROOT, BaseIndex
    from spike.delta_ingest.buffer import BufferWriter
    from spike.delta_ingest.generation import compact, freeze_buffer, publish
    from spike.delta_ingest.ledger import IngestLedger
    from spike.delta_ingest.profiles import PROFILES, apply_nice
    from spike.delta_ingest.records import DocRecord
    return dict(DEFAULT_INDEX_ROOT=DEFAULT_INDEX_ROOT, BaseIndex=BaseIndex, BufferWriter=BufferWriter,
                compact=compact, freeze_buffer=freeze_buffer, publish=publish,
                IngestLedger=IngestLedger, PROFILES=PROFILES, apply_nice=apply_nice,
                DocRecord=DocRecord)


def prepare(args) -> int:
    """Freeze the base manifest copy and the corpus (b) id list."""
    WORK.mkdir(parents=True, exist_ok=True)
    man = json.loads(STAGED_MANIFEST.read_text())
    served = json.loads((REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json").read_text())
    names_staged = [Path(s["mmap_dir"]).name for s in man["shards"]]
    names_served = [Path(s["mmap_dir"]).name for s in served["shards"]]
    assert names_staged == names_served, (names_staged, names_served)
    checks = []
    for s in man["shards"]:
        d = Path(s["mmap_dir"])
        size = sum(p.stat().st_size for p in d.iterdir() if p.is_file() and p.name != ".staged_ok")
        marker = int((d / ".staged_ok").read_text().strip())
        checks.append({"mmap_dir": str(d), "bytes": size, "staged_ok": marker, "match": size == marker})
    assert all(c["match"] for c in checks), checks
    man["m4_frozen_from"] = {"path": str(STAGED_MANIFEST), "utc": utc(), "shard_checks": checks,
                             "served_manifest": "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"}
    BASE_MANIFEST.write_text(json.dumps(man, indent=1))
    m = _spike_imports()
    src = sqlite3.connect(f"file:{F_LEDGER}?mode=ro", uri=True)
    rows = src.execute("SELECT r.rowid, r.id FROM records r JOIN docs d ON d.id=r.id "
                       "WHERE d.status='live' ORDER BY r.rowid").fetchall()
    ids = [r[1] for r in rows]
    t0 = time.time()
    base = m["BaseIndex"](m["DEFAULT_INDEX_ROOT"])
    in_base = base.contains(ids)
    base.close()
    keep = [i for i in ids if not in_base.get(i)]
    CORPUS.write_text(json.dumps({
        "source_ledger": str(F_LEDGER), "records_live": len(ids),
        "in_base": sum(1 for i in ids if in_base.get(i)), "kept": len(keep),
        "membership_check_s": round(time.time() - t0, 1), "order": "ledger rowid", "ids": keep,
        "ids_sha256": hashlib.sha256("\n".join(keep).encode()).hexdigest(), "utc": utc()}))
    print(json.dumps({"records_live": len(ids), "kept": len(keep), "in_base": len(ids) - len(keep)}))
    return 0


def _records(ids: list[str], DocRecord) -> list:
    src = sqlite3.connect(f"file:{F_LEDGER}?mode=ro", uri=True)
    out = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for rid, rec in src.execute(f"SELECT id, record FROM records WHERE id IN ({','.join('?' * len(chunk))})",
                                    chunk):
            out[rid] = DocRecord.from_json(rec)
    src.close()
    return [out[i] for i in ids]


def split_even(ids: list[str], n: int) -> list[list[str]]:
    q, r = divmod(len(ids), n)
    out, pos = [], 0
    for k in range(n):
        size = q + (1 if k < r else 0)
        out.append(ids[pos:pos + size])
        pos += size
    return out


LAYOUT_PREFIX = {"per_base_section": "n", "per_era": "e", "single": "s"}


def root_tag(layout: str, n: int, compacted: bool = False) -> str:
    """09 section 3 root names: n (per_base_section, M4), e (per_era), s (single)."""
    return f"{LAYOUT_PREFIX[layout]}{n}{'c' if compacted else ''}"


def _profile(m, args):
    over = {"layout": args.layout}
    if getattr(args, "seismic_threads", None):
        over["seismic_threads"] = args.seismic_threads
    return m["PROFILES"]["desktop_gpu"].with_overrides(**over)


def _source_gen_ids(src_root: Path, gen: int) -> set[str]:
    con = sqlite3.connect(f"file:{src_root / 'ledger.sqlite'}?mode=ro", uri=True)
    ids = {r[0] for r in con.execute("SELECT id FROM docs WHERE generation=? AND status='live'", (gen,))}
    con.close()
    return ids


def build(args) -> int:
    """Build root_<tag>{N}: N freezes of an evenly split corpus (b), with the
    09 L2 `--layout`; `--reuse-seismic-from root_nN` copies each generation's
    SEISMIC dir from the matching generation of that root (doc-id sets
    asserted against its ledger and its jsonl) instead of building it."""
    m = _spike_imports()
    profile = _profile(m, args)
    m["apply_nice"](profile)
    tag = root_tag(args.layout, args.n)
    root = WORK / f"root_{tag}"
    if root.exists():
        print(f"{root} exists; refusing to rebuild", file=sys.stderr)
        return 2
    src_root = None
    if args.reuse_seismic_from:
        src_root = WORK / args.reuse_seismic_from
        src_gens = json.loads((src_root / "generations.json").read_text())["generations"]
        if [g["gen"] for g in src_gens] != list(range(1, args.n + 1)):
            print(f"{src_root} does not hold generations 1..{args.n}", file=sys.stderr)
            return 2
    corpus = json.loads(CORPUS.read_text())
    chunks = split_even(corpus["ids"], args.n)
    if src_root is not None:
        for k, chunk in enumerate(chunks):
            if _source_gen_ids(src_root, k + 1) != set(chunk):
                print(f"{src_root} g{k + 1:04d} doc ids differ from chunk {k}", file=sys.stderr)
                return 2
    root.mkdir(parents=True)
    ledger = m["IngestLedger"](root / "ledger.sqlite")
    base = m["BaseIndex"](m["DEFAULT_INDEX_ROOT"])
    writer = m["BufferWriter"](root)
    log = {"root": str(root), "n": args.n, "layout": args.layout, "chunk_sizes": [len(c) for c in chunks],
           "reuse_seismic_from": str(src_root) if src_root else None, "freezes": [],
           "profile": profile.as_dict(), "commit": git_commit(), "started": utc(), "host_start": host_state()}
    t_all = time.time()
    for k, chunk in enumerate(chunks):
        t0 = time.time()
        recs = _records(chunk, m["DocRecord"])
        ledger.stage(recs, {})
        writer.upsert(recs)
        writer.commit()
        out = m["freeze_buffer"](root, ledger, base, profile, seismic=True,
                                 base_shard_manifest=str(BASE_MANIFEST), layout=args.layout,
                                 seismic_from=(src_root / f"g{k + 1:04d}") if src_root else None)
        writer.delete(chunk)
        writer.commit()
        gi = json.loads((root / f"g{out['frozen_generation']:04d}" / "generation.json").read_text())
        log["freezes"].append({"k": k, "gen": out["frozen_generation"], "docs": out["frozen_docs"],
                               "wall_s": round(time.time() - t0, 1), "seismic": gi["seismic"].get("status"),
                               "format": gi["seismic"].get("format"), "stages": gi["seismic"].get("stages"),
                               "sections": sorted(gi["sections"]), "layout": gi.get("layout"),
                               "seismic_reused_from": gi["seismic"].get("reused_from"),
                               "reuse_ids_checked": gi["seismic"].get("reuse_ids_checked")})
        print(json.dumps(log["freezes"][-1]), flush=True)
    writer.close()
    ledger.close()
    base.close()
    log["build_wall_s"] = round(time.time() - t_all, 1)
    log["finished"] = utc()
    log["host_end"] = host_state()
    (WORK / f"build_{tag}.json").write_text(json.dumps(log, indent=1, default=str))
    return 0


def compact_root(args) -> int:
    """root_n{N} -> copy root_n{N}c -> publish (repoint) -> compact all gens."""
    m = _spike_imports()
    profile = _profile(m, args)
    m["apply_nice"](profile)
    src, dst = WORK / f"root_{root_tag(args.layout, args.n)}", WORK / f"root_{root_tag(args.layout, args.n, True)}"
    if dst.exists():
        print(f"{dst} exists; refusing", file=sys.stderr)
        return 2
    t0 = time.time()
    shutil.copytree(src, dst, symlinks=True)
    copy_s = time.time() - t0
    ledger = m["IngestLedger"](dst / "ledger.sqlite")
    base = m["BaseIndex"](m["DEFAULT_INDEX_ROOT"])
    m["publish"](dst, ledger, base, str(BASE_MANIFEST))
    gens = ledger.published_generations()
    t0 = time.time()
    host_before = host_state()
    out = m["compact"](dst, ledger, base, profile, gens, seismic=True, base_shard_manifest=str(BASE_MANIFEST),
                       layout=args.layout)
    rec = {"root": str(dst), "from": str(src), "copy_s": round(copy_s, 1), "compacted": out.get("compacted"),
           "into": out.get("into"), "compact_wall_s": round(time.time() - t0, 1), "utc": utc(),
           "published_after": ledger.published_generations(), "layout": args.layout,
           "profile": profile.as_dict(), "commit": git_commit(), "host_before": host_before,
           "host_after": host_state()}
    gi = json.loads((dst / f"g{out['into']:04d}" / "generation.json").read_text())
    rec["sections"] = sorted(gi["sections"])
    rec["seismic_stages"] = gi["seismic"].get("stages")
    ledger.close()
    base.close()
    (WORK / f"compact_{root_tag(args.layout, args.n)}.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps(rec))
    return 0


class _WarnCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record):
        try:
            self.records.append(f"{record.name}: {record.getMessage()}"[:400])
        except Exception:
            pass


class _Timed:
    """Pass-through proxy that adds the wall time of selected method calls
    to `acc[key]` (ms). Used to attribute per-query time to base vs delta
    tantivy sections, each SEISMIC shard, and delta meta/abstract probes. It
    never changes arguments or results; the same proxies are installed in
    every arm."""

    def __init__(self, inner, acc: dict, key: str, methods: tuple):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_acc", acc)
        object.__setattr__(self, "_key", key)
        object.__setattr__(self, "_methods", methods)

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name not in self._methods or not callable(attr):
            return attr
        acc, key = self._acc, self._key

        def timed(*a, **kw):
            t = time.perf_counter()
            try:
                return attr(*a, **kw)
            finally:
                acc[key] = acc.get(key, 0.0) + (time.perf_counter() - t) * 1000
        return timed


class _TimedIndex(_Timed):
    def searcher(self):
        return _Timed(self._inner.searcher(), self._acc, self._key, ("search", "doc"))


def instrument(retriever, backend, acc: dict) -> dict:
    """Install the timing proxies; returns what was wrapped."""
    wrapped = {"sections_base": 0, "sections_delta": 0, "buffer": 0, "shards": 0,
               "abstract_stores_base": 0, "abstract_stores_delta": 0}
    for name, sec in retriever._sections.items():
        origin = sec.get("delta_origin")
        key = "bm25f_base" if origin is None else ("bm25f_buffer" if origin == "buffer" else "bm25f_delta")
        if origin == "buffer":
            sec["index"] = _TimedIndex(sec["index"], acc, key, ())
            wrapped["buffer"] += 1
        else:
            sec["searcher"] = _Timed(sec["searcher"], acc, key, ("search", "doc"))
            wrapped["sections_base" if origin is None else "sections_delta"] += 1
    for name in list(retriever._abstract_stores):
        key = "abs_delta" if name.startswith("delta_") else "abs_base"
        retriever._abstract_stores[name] = _Timed(retriever._abstract_stores[name], acc, key, ("fetch",))
        wrapped["abstract_stores_delta" if key == "abs_delta" else "abstract_stores_base"] += 1
    for i, sh in enumerate(backend.shards):
        backend.shards[i] = _Timed(sh, acc, f"shard{i}", ("search",))
        wrapped["shards"] += 1
    d = retriever._delta
    if d is not None:
        for meth, key in (("meta_rows", "delta_meta"), ("buffer_abstracts", "delta_buffer_abs"),
                          ("filter_hits", "delta_masks"), ("filter_ids", "delta_masks"),
                          ("buffer_size", "delta_masks"), ("refresh_buffer", "delta_buffer_poll")):
            orig = getattr(d, meth)

            def w(*a, _o=orig, _k=key, **kw):
                t = time.perf_counter()
                try:
                    return _o(*a, **kw)
                finally:
                    acc[_k] = acc.get(_k, 0.0) + (time.perf_counter() - t) * 1000
            setattr(d, meth, w)
    return wrapped


def child(args) -> int:
    """One measured process: load, assert health, warm-up pass, measured passes."""
    t_start = time.time()
    host0 = host_state()
    sys.path.insert(0, args.src)
    cap = _WarnCapture()
    logging.getLogger().addHandler(cap)
    logging.getLogger("sfu_library_mcp").addHandler(cap)
    health: dict = {"ok": True, "problems": []}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    try:
        import onnxruntime
        health["onnxruntime"] = onnxruntime.__version__
    except Exception as exc:
        bad(f"onnxruntime import failed: {exc!r}")
    import lib.tools as tools
    import lib.thinclient.retriever as rmod
    from lib.opensearch_retriever import encode_splade
    from lib.reranker import _get_cross_encoder
    if logging.getLogger("sfu_library_mcp").propagate:
        logging.getLogger("sfu_library_mcp").removeHandler(cap)
    retriever = tools._get_thinclient_retriever()
    if retriever is None:
        bad("search backend is not thinclient")
        Path(args.rows_out).write_text(json.dumps({"arm": args.arm, "health": health}) + "\n")
        return 3
    retriever._fetch_remote_abstracts = lambda ids: {}
    if os.environ.get("SFU_SEISMIC_STAGE_DIR") or os.environ.get("SFU_META_STAGE_DIR"):
        bad("a stage dir is set in the child env; refusing to load (staging a manifest that already "
            "points into the stage dir deletes the staged shard)")
        Path(args.rows_out).write_text(json.dumps({"arm": args.arm, "health": health}) + "\n")
        return 3
    t0 = time.perf_counter()
    retriever._load()
    load_s = time.perf_counter() - t0
    try:
        qv = encode_splade("warm up query for sparse encoder", retriever.splade_model_path)
        health["splade_terms"] = len(qv or {})
        if not qv:
            bad("encode_splade returned empty")
    except Exception as exc:
        bad(f"encode_splade raised {exc!r}")
    t0 = time.perf_counter()
    try:
        ce = _get_cross_encoder()
        health["cross_encoder"] = type(ce).__name__ if ce is not None else None
        if ce is None:
            bad("cross-encoder not loaded")
    except Exception as exc:
        bad(f"cross-encoder load raised {exc!r}")
    ce_s = time.perf_counter() - t0
    try:
        from lib.embedding import _load_model
        em = _load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
        health["embedding_model"] = type(em).__name__ if em is not None else None
        if em is None:
            bad("embedding model not loaded")
    except Exception as exc:
        bad(f"embedding model load raised {exc!r}")
    t0 = time.perf_counter()
    try:
        backend = retriever._seismic_backend()
    except Exception as exc:
        backend = None
        bad(f"seismic backend load raised {exc!r}")
    backend_s = time.perf_counter() - t0
    want_cls = {"parallel": "ParallelSeismicBackend", "sequential": "SequentialSeismicBackend"}[args.federation]
    n_gen = ARMS[args.arm]
    delta = retriever._delta
    if backend is not None:
        health["backend_class"] = type(backend).__name__
        health["n_shards"] = len(backend.shards)
        if type(backend).__name__ != want_cls:
            bad(f"backend {type(backend).__name__} != {want_cls}")
        if len(backend.shards) != N_BASE_SHARDS + n_gen or any(s is None for s in backend.shards):
            bad(f"shards {len(backend.shards)} != {N_BASE_SHARDS + n_gen} or a shard is None")
    if args.arm == "n0":
        if delta is not None:
            bad("delta layer loaded in the gate-off arm")
    else:
        if delta is None:
            bad("delta layer not loaded")
        else:
            health["delta_generations"] = [g["gen"] for g in delta.generations]
            health["delta_stamp"] = delta.stamp
            health["delta_manifest"] = delta.shard_manifest_path()
            health["delta_buffer_size"] = delta.buffer_size()
            health["delta_sections_loaded"] = sum(1 for n in retriever._sections if n.startswith("delta_"))
            health["livedocs"] = delta.livedocs is not None
            if len(delta.generations) != n_gen:
                bad(f"delta generations {len(delta.generations)} != {n_gen}")
            if getattr(retriever, "_seismic_manifest", None) != delta.shard_manifest_path():
                bad("served manifest is not the delta composed manifest")
    health["sections_total"] = len(retriever._sections)
    health["abstract_stores"] = len(retriever._abstract_stores)
    health["meta_path"] = str(retriever._meta_path)
    health["warnings_at_load"] = list(cap.records)
    if any(any(s in w for s in SIGNATURES) for w in cap.records):
        bad("failure signature in warnings during load")
    meta = {"arm": args.arm, "n_gen": n_gen, "federation": args.federation, "pid": os.getpid(),
            "round": args.round, "src": args.src,
            "env": {k: os.environ.get(k) for k in sorted(os.environ) if k.startswith("SFU_") and
                    not any(s in k for s in ("KEY", "TOKEN", "AUTH", "SECRET", "PASS"))},
            "load_s": round(load_s, 2), "ce_load_s": round(ce_s, 2), "backend_load_s": round(backend_s, 2),
            "health": health, "host_start": host0}
    if not health["ok"]:
        meta["host_end"] = host_state()
        Path(args.rows_out).write_text(json.dumps(meta) + "\n")
        print("HEALTH FAIL", json.dumps(health["problems"]), file=sys.stderr, flush=True)
        return 3

    timing: dict = {}
    orig_encode, orig_search = backend.encode_query, backend.search_encoded

    def enc_w(q):
        t = time.perf_counter()
        r = orig_encode(q)
        timing["encode_ms"] = (time.perf_counter() - t) * 1000
        return r

    def srch_w(q, top_k, **kw):
        t = time.perf_counter()
        r = orig_search(q, top_k, **kw)
        timing["traverse_ms"] = (time.perf_counter() - t) * 1000
        timing["traverse_n"] = len(r)
        return r

    backend.encode_query = enc_w
    backend.search_encoded = srch_w
    acc: dict = {}
    meta["instrumented"] = instrument(retriever, backend, acc)
    base_idx = [i for i, o in enumerate(delta.shard_origins(len(backend.shards), retriever._seismic_manifest))
                if o is None] if delta is not None else list(range(len(backend.shards)))
    items = load_topics()[:args.limit_topics or None]
    corpus_ids = set(json.loads(CORPUS.read_text())["ids"])
    meta["quiet_gate"] = quiet_gate(args.quiet_wait)
    passes = []
    n_warn_before = len(cap.records)
    for p in range(args.warmup + args.passes):
        rows = []
        for key, q in items:
            timing.clear()
            acc.clear()
            before = rmod.snapshot_leg_metrics()
            ru0 = resource.getrusage(resource.RUSAGE_SELF)
            t = time.perf_counter()
            fused = retriever.search_rrf(q, top_k=TOP_K)
            ms = (time.perf_counter() - t) * 1000
            ru1 = resource.getrusage(resource.RUSAGE_SELF)
            legs = rmod.leg_metrics_delta(before)
            rows.append({"topic": key, "ms": round(ms, 2), "bm25f_ms": legs.get("bm25f"),
                         "splade_ms": legs.get("splade"),
                         "encode_ms": round(timing["encode_ms"], 2) if "encode_ms" in timing else None,
                         "traverse_ms": round(timing["traverse_ms"], 2) if "traverse_ms" in timing else None,
                         "traversed": "traverse_ms" in timing, "n": len(fused),
                         "n_delta_top50": sum(1 for d in fused if d.get("openalex_id") in corpus_ids),
                         "n_delta_top10": sum(1 for d in fused[:10] if d.get("openalex_id") in corpus_ids),
                         "majflt": ru1.ru_majflt - ru0.ru_majflt,
                         "comp": {k: round(v, 2) for k, v in acc.items()},
                         "shard_base_max_ms": round(max([acc.get(f"shard{i}", 0.0) for i in base_idx] or [0.0]), 2),
                         "shard_all_max_ms": round(max([acc.get(f"shard{i}", 0.0) for i in range(len(backend.shards))] or [0.0]), 2),
                         "shard_delta_sum_ms": round(sum(acc.get(f"shard{i}", 0.0) for i in range(len(backend.shards))
                                                         if i not in base_idx), 2),
                         "top10": [d.get("openalex_id") for d in fused[:10]]})
        kind = "warmup" if p < args.warmup else "measured"
        passes.append({"pass": p + 1, "kind": kind, "rows": rows,
                       "p50": pct([r["ms"] for r in rows], 50), "p95": pct([r["ms"] for r in rows], 95)})
        print(f"[{args.arm}/{args.federation} r{args.round} pass{p+1} {kind}] p50={passes[-1]['p50']} "
              f"p95={passes[-1]['p95']}", flush=True)
    measured = [r for ps in passes if ps["kind"] == "measured" for r in ps["rows"]]
    untraversed = sum(1 for r in measured if not r["traversed"])
    warn_meas = cap.records[n_warn_before:]
    if untraversed:
        bad(f"{untraversed} measured queries never reached the SEISMIC traverse")
    if any(any(s in w for s in SIGNATURES) for w in warn_meas):
        bad("failure signature in warnings during measurement")
    health["warnings_during_passes"] = warn_meas[:50]
    health["n_warnings_during_passes"] = len(warn_meas)
    meta["host_end"] = host_state()
    meta["wall_s"] = round(time.time() - t_start, 1)
    meta["maxrss_gb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 2, 2)
    meta["passes"] = passes
    Path(args.rows_out).write_text(json.dumps(meta) + "\n")
    return 0 if health["ok"] else 3


def snapshot_src(commit: str) -> Path:
    snap = WORK / f"code_{commit[:8]}"
    if not (snap / "src").exists():
        snap.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(f"git -C {REPO} archive {commit} src | tar -x -C {snap}", shell=True)
        for name in ("models", "data", ".env"):
            if not (snap / name).exists():
                (snap / name).symlink_to(REPO / name)
    return snap


def arm_env(arm: str, federation: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ENV_DROP}
    env.update({k: "" for k in ENV_DROP})
    env["SFU_SEISMIC_FEDERATION"] = federation
    if arm == "n0":
        env["SFU_SEISMIC_SHARD_MANIFEST"] = str(BASE_MANIFEST)
    else:
        env["SFU_DELTA_ROOT"] = str(WORK / f"root_{arm}")
    return env


def scan_log(path: Path) -> dict:
    text = path.read_text(errors="replace") if path.exists() else ""
    return {"path": str(path), "bytes": len(text), "signature_counts": {s: text.count(s) for s in SIGNATURES}}


def drive(args) -> int:
    commit = args.commit or git_commit()
    snap = snapshot_src(commit)
    runs_dir = WORK / f"runs_{args.tag}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    arms = args.arms.split(",")
    feds = args.federations.split(",")
    rng = random.Random(args.seed)
    deadline = time.time() + args.max_seconds if args.max_seconds else None
    schedule = []
    for r in range(1, args.rounds + 1):
        cells = [(a, f) for f in feds for a in arms]
        rng.shuffle(cells)
        schedule += [(r, a, f) for a, f in cells]
    for r, a, f in schedule:
        rows_out = runs_dir / f"r{r}_{a}_{f}.json"
        logp = runs_dir / f"r{r}_{a}_{f}.log"
        if rows_out.exists() and json.loads(rows_out.read_text()).get("health", {}).get("ok") \
                and json.loads(rows_out.read_text()).get("passes"):
            continue
        if deadline and time.time() > deadline:
            print(f"deadline reached before r{r} {a} {f}", flush=True)
            break
        for attempt in range(1, args.retries + 2):
            cmd = ["flock", LOCK, sys.executable, str(Path(__file__).resolve()), "child", "--arm", a,
                   "--federation", f, "--round", str(r), "--passes", str(args.passes),
                   "--warmup", str(args.warmup), "--rows-out", str(rows_out),
                   "--limit-topics", str(args.limit_topics), "--src", str(snap / "src"),
                   "--quiet-wait", str(args.quiet_wait)]
            tw = time.time()
            with open(logp, "a") as fh:
                fh.write(f"=== attempt {attempt} {utc()} ===\n")
                fh.flush()
                rc = subprocess.call(cmd, env=arm_env(a, f), cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT,
                                     timeout=args.child_timeout)
            ok = rows_out.exists() and json.loads(rows_out.read_text()).get("health", {}).get("ok")
            print(f"r{r} {a} {f} attempt {attempt} rc={rc} ok={ok} wall={time.time() - tw:.0f}s", flush=True)
            if ok:
                break
            if rows_out.exists():
                rows_out.rename(runs_dir / f"r{r}_{a}_{f}.degraded{attempt}.json")
    return summarize(args, commit, snap, runs_dir)


COMP_KEYS = ("bm25f_base", "bm25f_delta", "bm25f_buffer", "abs_base", "abs_delta", "delta_meta",
             "delta_buffer_abs", "delta_masks", "delta_buffer_poll")


def serial_delta(r: dict) -> float:
    """Per-query wall time spent in delta-only serial work: delta and buffer
    tantivy sections, delta abstract stores, delta meta probes, buffer
    abstracts, masks (delta_buffer_poll is nested inside meta/abstract calls
    and is not added)."""
    c = r.get("comp", {})
    return sum(c.get(k, 0.0) for k in ("bm25f_delta", "bm25f_buffer", "abs_delta", "delta_meta",
                                        "delta_buffer_abs", "delta_masks"))


def seismic_inc(r: dict, federation: str) -> float:
    """SEISMIC time attributable to delta shards: parallel = max(all shards)
    - max(base shards) (the fan-out waits for the slowest); sequential = sum
    of the delta shards' own times."""
    if federation == "sequential":
        return r.get("shard_delta_sum_ms", 0.0)
    return max(0.0, r.get("shard_all_max_ms", 0.0) - r.get("shard_base_max_ms", 0.0))


def summarize(args, commit: str, snap: Path, runs_dir: Path) -> int:
    arms = args.arms.split(",")
    feds = args.federations.split(",")
    per: dict = {}
    degraded = []
    for p in sorted(runs_dir.glob("r*_*.json")):
        rec = json.loads(p.read_text())
        name = p.stem
        if ".degraded" in p.name or not rec.get("health", {}).get("ok") or not rec.get("passes"):
            degraded.append({"file": str(p), "arm": rec.get("arm"), "federation": rec.get("federation"),
                             "round": rec.get("round"), "problems": rec.get("health", {}).get("problems")})
            continue
        per.setdefault((rec["federation"], rec["arm"]), []).append(rec)
    out_fed: dict = {}
    for f in feds:
        fed = {"arms": {}}
        for a in arms:
            recs = sorted(per.get((f, a), []), key=lambda r: r["round"])
            if not recs:
                fed["arms"][a] = {"status": "NOT MEASURED"}
                continue
            rows = [r for rec in recs for ps in rec["passes"] if ps["kind"] == "measured" for r in ps["rows"]]

            def col(k):
                return [r[k] for r in rows if r.get(k) is not None]

            hydr = [r["ms"] - (r["bm25f_ms"] or 0) - (r["splade_ms"] or 0) for r in rows]
            fed["arms"][a] = {
                "n_gen": ARMS[a], "n_queries_measured": len(rows), "rounds": [rec["round"] for rec in recs],
                "p50_ms": pct(col("ms"), 50), "p95_ms": pct(col("ms"), 95), "mean_ms": round(statistics.fmean(col("ms")), 2),
                "legs_p50_ms": {"bm25f": pct(col("bm25f_ms"), 50), "splade": pct(col("splade_ms"), 50),
                                "splade_encode": pct(col("encode_ms"), 50),
                                "seismic_traverse": pct(col("traverse_ms"), 50),
                                "hydrate_fuse_remainder": pct(hydr, 50)},
                "legs_p95_ms": {"bm25f": pct(col("bm25f_ms"), 95), "splade": pct(col("splade_ms"), 95),
                                "seismic_traverse": pct(col("traverse_ms"), 95)},
                "majflt_per_query_mean": round(statistics.fmean(col("majflt")), 2),
                "components_mean_ms": {k: round(statistics.fmean([r.get("comp", {}).get(k, 0.0) for r in rows]), 3)
                                       for k in COMP_KEYS},
                "components_p50_ms": {k: pct([r.get("comp", {}).get(k, 0.0) for r in rows], 50) for k in COMP_KEYS},
                "serial_delta_ms_mean": round(statistics.fmean([serial_delta(r) for r in rows]), 3),
                "serial_delta_ms_p50": pct([serial_delta(r) for r in rows], 50),
                "seismic_delta_increment_ms_mean": round(statistics.fmean(
                    [seismic_inc(r, f) for r in rows]), 3),
                "seismic_delta_increment_ms_p50": pct([seismic_inc(r, f) for r in rows], 50),
                "shard_base_max_ms_p50": pct(col("shard_base_max_ms"), 50),
                "delta_docs_in_top10_mean": round(statistics.fmean(col("n_delta_top10")), 3),
                "delta_docs_in_top50_mean": round(statistics.fmean(col("n_delta_top50")), 3),
                "per_round": [{"round": rec["round"],
                               "p50_ms": pct([r["ms"] for ps in rec["passes"] if ps["kind"] == "measured"
                                              for r in ps["rows"]], 50),
                               "p95_ms": pct([r["ms"] for ps in rec["passes"] if ps["kind"] == "measured"
                                              for r in ps["rows"]], 95),
                               "per_pass_p50": [ps["p50"] for ps in rec["passes"]],
                               "load_s": rec["load_s"], "backend_load_s": rec["backend_load_s"],
                               "maxrss_gb": rec.get("maxrss_gb"),
                               "quiet_gate": rec.get("quiet_gate"),
                               "host_start": {k: rec["host_start"].get(k) for k in ("utc", "loadavg", "mem_gb", "gpu", "busy_procs_gt20pct")},
                               "host_end": {k: rec["host_end"].get(k) for k in ("utc", "loadavg", "mem_gb", "gpu", "busy_procs_gt20pct")},
                               "health": {k: v for k, v in rec["health"].items() if k not in ("warnings_at_load",)}}
                              for rec in recs],
                "_rows_by_topic": {},
            }
            byt: dict = {}
            for r in rows:
                byt.setdefault(r["topic"], []).append(r["ms"])
            fed["arms"][a]["_rows_by_topic"] = {k: statistics.median(v) for k, v in byt.items()}
        pts = [(ARMS[a], fed["arms"][a]["p50_ms"]) for a in ("n0", "n1", "n4", "n8")
               if fed["arms"].get(a, {}).get("p50_ms") is not None]
        fed["slope_primary_ms_per_gen_ols_0_1_4_8"] = ols([x for x, _ in pts], [y for _, y in pts]) if len(pts) == 4 else None
        pts148 = [p for p in pts if p[0] > 0]
        fed["slope_secondary_ols_1_4_8"] = ols([x for x, _ in pts148], [y for _, y in pts148]) if len(pts148) == 3 else None
        a1, a8 = fed["arms"].get("n1", {}).get("p50_ms"), fed["arms"].get("n8", {}).get("p50_ms")
        fed["slope_secondary_n1_to_n8"] = round((a8 - a1) / 7, 3) if a1 is not None and a8 is not None else None
        a0 = fed["arms"].get("n0", {}).get("p50_ms")
        fed["fixed_cost_n1_minus_n0_ms"] = round(a1 - a0, 2) if a0 is not None and a1 is not None else None
        rounds = sorted({r for (ff, a), recs in per.items() if ff == f for r in [x["round"] for x in recs]})
        per_round_slopes = []
        for rr in rounds:
            pr = []
            for a in ("n0", "n1", "n4", "n8"):
                rec = [x for x in per.get((f, a), []) if x["round"] == rr]
                if rec:
                    pr.append((ARMS[a], pct([r["ms"] for ps in rec[0]["passes"] if ps["kind"] == "measured"
                                             for r in ps["rows"]], 50)))
            if len(pr) == 4:
                per_round_slopes.append({"round": rr, "slope": ols([x for x, _ in pr], [y for _, y in pr]),
                                         "p50s": dict((str(x), y) for x, y in pr)})
        fed["slope_per_round"] = per_round_slopes
        ss = [s["slope"] for s in per_round_slopes if s["slope"] is not None]
        fed["slope_spread_min_max"] = [min(ss), max(ss)] if ss else None
        paired = {}
        t0 = fed["arms"].get("n0", {}).get("_rows_by_topic") or {}
        for a in ("n1", "n4", "n8"):
            ta = fed["arms"].get(a, {}).get("_rows_by_topic") or {}
            common = [k for k in ta if k in t0]
            if common:
                paired[a] = round(statistics.median([(ta[k] - t0[k]) / ARMS[a] for k in common]), 3)
        fed["paired_median_per_query_ms_per_gen_vs_n0"] = paired
        cpts = [(ARMS[a], fed["arms"][a]["serial_delta_ms_mean"] + fed["arms"][a]["seismic_delta_increment_ms_mean"])
                for a in ("n0", "n1", "n4", "n8") if fed["arms"].get(a, {}).get("serial_delta_ms_mean") is not None]
        fed["component_tax_ms_per_gen_ols_0_1_4_8"] = (ols([x for x, _ in cpts], [y for _, y in cpts])
                                                       if len(cpts) == 4 else None)
        fed["component_tax_points_mean_ms"] = dict((str(x), round(y, 3)) for x, y in cpts)
        fed["component_tax_note"] = ("supplementary (not the pre-registered metric): mean per-query ms of "
                                     "delta-only serial work + SEISMIC delta-shard increment, OLS over N")
        s = fed["slope_primary_ms_per_gen_ols_0_1_4_8"]
        fed["verdict_growth_bar_le_8ms"] = ("PASS" if s is not None and s <= 8.0 else
                                            "FAIL" if s is not None else "NOT DECIDED")
        fed["go_line_ge_3ms"] = (None if s is None else ("MET (tax >= 3 ms/gen)" if s >= 3.0 else
                                                         "NOT MET (tax < 3 ms/gen)"))
        comp = {}
        for c in ("n8c", "n4c"):
            pc = fed["arms"].get(c, {}).get("p50_ms")
            if pc is not None and a1 is not None:
                ratio = round(pc / a1, 4)
                comp[c] = {"p50_ms": pc, "n1_p50_ms": a1, "ratio_vs_n1": ratio,
                           "verdict_within_5pct": "PASS" if abs(ratio - 1) <= 0.05 else "FAIL"}
            else:
                comp[c] = {"verdict_within_5pct": "NOT MEASURED"}
        fed["compaction"] = comp
        for a in fed["arms"].values():
            a.pop("_rows_by_topic", None)
        out_fed[f] = fed
    log_scan = {p.name: scan_log(p) for p in sorted(runs_dir.glob("*.log"))}
    enomem = {k: v["signature_counts"]["Cannot allocate memory"] for k, v in log_scan.items()
              if v["signature_counts"]["Cannot allocate memory"]}
    builds = {p.name: json.loads(p.read_text()) for p in sorted(WORK.glob("build_n*.json"))}
    comps = {p.name: json.loads(p.read_text()) for p in sorted(WORK.glob("compact_n*.json"))}
    corpus = json.loads(CORPUS.read_text())
    corpus.pop("ids", None)
    res = {
        "measurement": "M4 read amplification per live delta generation (docs/delta_ingest/03_SPIKE_PLAN.md)",
        "bar_preregistered": ("03_SPIKE_PLAN.md M4: search_rrf p50/p95 with 0, 1, 4, 8 live generations of "
                              "corpus (b) split evenly, before and after compact -> p50 growth <= +8 ms per "
                              "generation *est.* budget, and compaction returns to within 5% of the "
                              "1-generation arm"),
        "go_line": "05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md section 6: GO needs a generation tax >= 3 ms p50/gen",
        "operational_definitions": "see the script header (fixed before the run)",
        "script": "scripts/experiments/eval_delta_ingest_m4_read_amp.py",
        "git_commit_measured_code": commit, "code_snapshot": str(snap),
        "date_utc": time.strftime("%Y-%m-%d", time.gmtime()),
        "seed_arm_order": args.seed, "rounds": args.rounds, "warmup_passes": args.warmup,
        "measured_passes_per_process": args.passes, "top_k": TOP_K,
        "topics_file": str(TOPICS.relative_to(REPO)), "query_field": "natural",
        "corpus_b": corpus, "base_manifest": str(BASE_MANIFEST), "builds": builds, "compactions": comps,
        "federations": out_fed, "degraded_or_retried_processes": degraded,
        "log_scan": log_scan, "log_scan_enomem_hits": enomem, "runs_dir": str(runs_dir),
    }
    out = Path(args.out) if args.out else REPO / f"data/eval_results/delta_ingest_M4_{time.strftime('%Y%m%d', time.gmtime())}.json"
    out.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({f: {k: v for k, v in fd.items() if k != "arms"} for f, fd in out_fed.items()}, indent=1))
    return 0


def _open_arm(arm: str, federation: str, cfg, ThinClientRetriever, health: dict) -> tuple:
    """Construct and load one arm's retriever with its env; return
    (retriever, backend, problems)."""
    probs = []
    os.environ["SFU_SEISMIC_FEDERATION"] = federation
    os.environ["SFU_DELTA_ROOT"] = "" if arm == "n0" else str(WORK / f"root_{arm}")
    os.environ["SFU_SEISMIC_SHARD_MANIFEST"] = str(BASE_MANIFEST) if arm == "n0" else ""
    r = ThinClientRetriever(index_root=cfg.thinclient_index_root, splade_model_path=cfg.splade_model_path,
                            openalex_mailto=cfg.openalex_mailto, query_log_path="",
                            openalex_api_key=cfg.openalex_api_key, remote_abstract_fetcher=None)
    r._fetch_remote_abstracts = lambda ids: {}
    t0 = time.perf_counter()
    r._load()
    load_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    try:
        b = r._seismic_backend()
    except Exception as exc:
        return r, None, [f"{arm}: backend load raised {exc!r}"], {}
    n_gen = ARMS[arm]
    want = {"parallel": "ParallelSeismicBackend", "sequential": "SequentialSeismicBackend"}[federation]
    if type(b).__name__ != want:
        probs.append(f"{arm}: backend {type(b).__name__} != {want}")
    if len(b.shards) != N_BASE_SHARDS + n_gen or any(x is None for x in b.shards):
        probs.append(f"{arm}: shards {len(b.shards)} != {N_BASE_SHARDS + n_gen}")
    d = r._delta
    info = {"load_s": round(load_s, 2), "backend_load_s": round(time.perf_counter() - t0, 2),
            "backend_class": type(b).__name__, "n_shards": len(b.shards), "sections": len(r._sections),
            "abstract_stores": len(r._abstract_stores), "meta_path": str(r._meta_path)}
    if arm == "n0":
        if d is not None:
            probs.append("n0: delta layer loaded")
    elif d is None:
        probs.append(f"{arm}: delta layer not loaded")
    else:
        info.update({"delta_generations": [g["gen"] for g in d.generations], "delta_stamp": d.stamp,
                     "delta_manifest": d.shard_manifest_path(), "buffer_size": d.buffer_size(),
                     "delta_sections": sum(1 for n in r._sections if n.startswith("delta_")),
                     "livedocs": d.livedocs is not None, "deleted": len(d.deleted),
                     "superseded": len(d.superseded)})
        if len(d.generations) != n_gen:
            probs.append(f"{arm}: generations {len(d.generations)} != {n_gen}")
        if getattr(r, "_seismic_manifest", None) != d.shard_manifest_path():
            probs.append(f"{arm}: served manifest is not the delta composed manifest")
    return r, b, probs, info


def inproc(args) -> int:
    """PRIMARY M4 run: all arms as retrievers in one process, interleaved per query."""
    t_start = time.time()
    host0 = host_state()
    sys.path.insert(0, args.src)
    cap = _WarnCapture()
    logging.getLogger().addHandler(cap)
    health: dict = {"ok": True, "problems": [], "arms": {}}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    try:
        import onnxruntime
        health["onnxruntime"] = onnxruntime.__version__
    except Exception as exc:
        bad(f"onnxruntime import failed: {exc!r}")
    import lib.tools as tools
    import lib.thinclient.retriever as rmod
    from lib.embedding import _load_model
    from lib.opensearch_retriever import encode_splade
    from lib.reranker import _get_cross_encoder
    from lib.thinclient.retriever import ThinClientRetriever
    cfg = tools._get_config()
    if cfg.search_backend != "thinclient":
        bad("search backend is not thinclient")
    if os.environ.get("SFU_SEISMIC_STAGE_DIR") or os.environ.get("SFU_META_STAGE_DIR"):
        bad("a stage dir is set in the process env; refusing to load")
    arms = args.arms.split(",")
    out = {"mode": "inproc", "federation": args.federation, "arms": arms, "pid": os.getpid(), "src": args.src,
           "host_start": host0, "health": health, "seed": args.seed}
    if health["ok"]:
        try:
            qv = encode_splade("warm up query for sparse encoder", cfg.splade_model_path)
            health["splade_terms"] = len(qv or {})
            if not qv:
                bad("encode_splade returned empty")
        except Exception as exc:
            bad(f"encode_splade raised {exc!r}")
        ce = _get_cross_encoder()
        health["cross_encoder"] = type(ce).__name__ if ce is not None else None
        if ce is None:
            bad("cross-encoder not loaded")
        em = _load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
        health["embedding_model"] = type(em).__name__ if em is not None else None
        if em is None:
            bad("embedding model not loaded")
    rets, accs, timings = {}, {}, {}
    out["prime_mode"] = args.prime_mode
    open_list = list(arms) + (["_prime"] if args.prime_mode == "separate" else [])
    if health["ok"]:
        for arm in open_list:
            r, b, probs, info = _open_arm("n0" if arm == "_prime" else arm, args.federation, cfg,
                                          ThinClientRetriever, health)
            health["arms"][arm] = info
            for pr in probs:
                bad(pr)
            if b is None:
                continue
            acc: dict = {}
            tm: dict = {}
            oe, osrch = b.encode_query, b.search_encoded

            def enc_w(q, _o=oe, _t=tm):
                t = time.perf_counter()
                res = _o(q)
                _t["encode_ms"] = (time.perf_counter() - t) * 1000
                return res

            def srch_w(q, top_k, _o=osrch, _t=tm, **kw):
                t = time.perf_counter()
                res = _o(q, top_k, **kw)
                _t["traverse_ms"] = (time.perf_counter() - t) * 1000
                return res
            b.encode_query, b.search_encoded = enc_w, srch_w
            info["instrumented"] = instrument(r, b, acc)
            base_idx = ([i for i, o in enumerate(r._delta.shard_origins(len(b.shards), r._seismic_manifest))
                         if o is None] if r._delta is not None else list(range(len(b.shards))))
            rets[arm], accs[arm], timings[arm] = (r, b, base_idx), acc, tm
    health["warnings_at_load"] = list(cap.records)
    if any(any(sg in w for sg in SIGNATURES) for w in cap.records):
        bad("failure signature in warnings during load")
    if not health["ok"]:
        out["host_end"] = host_state()
        Path(args.rows_out).write_text(json.dumps(out) + "\n")
        print("HEALTH FAIL", json.dumps(health["problems"]), file=sys.stderr, flush=True)
        return 3
    items = load_topics()[:args.limit_topics or None]
    corpus_ids = set(json.loads(CORPUS.read_text())["ids"])
    rng = random.Random(args.seed)

    def call(arm, q):
        r, b, base_idx = rets[arm]
        acc, tm = accs[arm], timings[arm]
        acc.clear()
        tm.clear()
        before = rmod.snapshot_leg_metrics()
        ru0 = resource.getrusage(resource.RUSAGE_SELF)
        t = time.perf_counter()
        fused = r.search_rrf(q, top_k=TOP_K)
        ms = (time.perf_counter() - t) * 1000
        ru1 = resource.getrusage(resource.RUSAGE_SELF)
        legs = rmod.leg_metrics_delta(before)
        nsh = len(b.shards)
        return {"arm": arm, "ms": round(ms, 2), "bm25f_ms": legs.get("bm25f"), "splade_ms": legs.get("splade"),
                "encode_ms": round(tm["encode_ms"], 2) if "encode_ms" in tm else None,
                "traverse_ms": round(tm["traverse_ms"], 2) if "traverse_ms" in tm else None,
                "traversed": "traverse_ms" in tm, "n": len(fused),
                "n_delta_top50": sum(1 for d in fused if d.get("openalex_id") in corpus_ids),
                "n_delta_top10": sum(1 for d in fused[:10] if d.get("openalex_id") in corpus_ids),
                "majflt": ru1.ru_majflt - ru0.ru_majflt,
                "comp": {k: round(v, 2) for k, v in acc.items()},
                "shard_base_max_ms": round(max([acc.get(f"shard{i}", 0.0) for i in base_idx] or [0.0]), 2),
                "shard_all_max_ms": round(max([acc.get(f"shard{i}", 0.0) for i in range(nsh)] or [0.0]), 2),
                "shard_delta_sum_ms": round(sum(acc.get(f"shard{i}", 0.0) for i in range(nsh)
                                                if i not in base_idx), 2),
                "top10": [d.get("openalex_id") for d in fused[:10]]}

    out["quiet_gate"] = quiet_gate(args.quiet_wait)
    passes = []
    last_host = None
    n_warn_before = len(cap.records)
    quiet_waits = []
    for p in range(args.warmup + args.passes):
        kind = "warmup" if p < args.warmup else "measured"
        rows = []
        tp = time.time()
        for qi, (key, q) in enumerate(items):
            if kind == "measured" and qi % 10 == 0:
                g = quiet_gate(args.inline_wait, load1_max=6.0, poll_s=10)
                last_host = {"utc": g["samples"][-1]["utc"], "load1": g["samples"][-1]["load1"],
                             "busy": g["samples"][-1]["busy_gt50pct"], "quiet": g["quiet"],
                             "waited_s": g["waited_s"]}
                quiet_waits.append({"pass": p + 1, "q": qi, **last_host})
            if kind == "warmup":
                for arm in arms:
                    row = call(arm, q)
                    row.update({"topic": key, "position": arms.index(arm)})
                    rows.append(row)
                continue
            prime = call("_prime" if args.prime_mode == "separate" else "n0", q)
            prime.update({"topic": key, "position": -1, "prime": True})
            rows.append(prime)
            order = list(arms)
            rng.shuffle(order)
            for pos, arm in enumerate(order):
                row = call(arm, q)
                row.update({"topic": key, "position": pos, "host": last_host})
                rows.append(row)
            if qi % 20 == 19:
                print(f"[inproc {args.federation} pass{p+1}] {qi+1}/{len(items)} "
                      f"{time.time() - tp:.0f}s", flush=True)
        passes.append({"pass": p + 1, "kind": kind, "wall_s": round(time.time() - tp, 1), "rows": rows})
        print(f"[inproc {args.federation} pass{p+1} {kind}] done in {time.time() - tp:.0f}s", flush=True)
        Path(args.rows_out).write_text(json.dumps({**out, "passes": passes, "partial": True}) + "\n")
    measured = [r for ps in passes if ps["kind"] == "measured" for r in ps["rows"] if not r.get("prime")]
    if any(not r["traversed"] for r in measured):
        bad(f"{sum(1 for r in measured if not r['traversed'])} measured calls never reached the SEISMIC traverse")
    warn_meas = cap.records[n_warn_before:]
    if any(any(sg in w for sg in SIGNATURES) for w in warn_meas):
        bad("failure signature in warnings during measurement")
    health["warnings_during_passes"] = warn_meas[:50]
    health["n_warnings_during_passes"] = len(warn_meas)
    out.update({"quiet_waits": quiet_waits, "host_end": host_state(), "wall_s": round(time.time() - t_start, 1),
                "maxrss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 2, 2),
                "passes": passes, "partial": False})
    Path(args.rows_out).write_text(json.dumps(out) + "\n")
    return 0 if health["ok"] else 3


def inproc_drive(args) -> int:
    commit = args.commit or git_commit()
    snap = snapshot_src(commit)
    runs_dir = WORK / f"inproc_{args.tag}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for fed in args.federations.split(","):
        rows_out, logp = runs_dir / f"{fed}.json", runs_dir / f"{fed}.log"
        if rows_out.exists():
            rec = json.loads(rows_out.read_text())
            if rec.get("health", {}).get("ok") and not rec.get("partial"):
                continue
        for attempt in range(1, args.retries + 2):
            env = arm_env("n0", fed)
            cmd = ["flock", LOCK, sys.executable, str(Path(__file__).resolve()), "inproc", "--federation", fed,
                   "--arms", args.arms, "--passes", str(args.passes), "--warmup", str(args.warmup),
                   "--rows-out", str(rows_out), "--limit-topics", str(args.limit_topics),
                   "--src", str(snap / "src"), "--quiet-wait", str(args.quiet_wait),
                   "--inline-wait", str(args.inline_wait), "--seed", str(args.seed)]
            with open(logp, "a") as fh:
                fh.write(f"=== attempt {attempt} {utc()} ===\n")
                fh.flush()
                try:
                    rc = subprocess.call(cmd, env=env, cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT,
                                         timeout=args.child_timeout)
                except subprocess.TimeoutExpired:
                    rc = "timeout"
            rec = json.loads(rows_out.read_text()) if rows_out.exists() else {}
            ok = rec.get("health", {}).get("ok") and not rec.get("partial")
            print(f"inproc {fed} attempt {attempt} rc={rc} ok={bool(ok)}", flush=True)
            if ok:
                break
            if rows_out.exists():
                rows_out.rename(runs_dir / f"{fed}.degraded{attempt}.json")
    return inproc_summarize(args, commit, snap, runs_dir)


def _boot_ci(vals: list[float], seed: int, n: int = 2000) -> list[float] | None:
    if len(vals) < 5:
        return None
    rng = random.Random(seed)
    meds = sorted(statistics.median(rng.choices(vals, k=len(vals))) for _ in range(n))
    return [round(meds[int(0.025 * n)], 3), round(meds[int(0.975 * n) - 1], 3)]


def inproc_summarize(args, commit: str, snap: Path, runs_dir: Path) -> int:
    feds = {}
    degraded = [str(p) for p in sorted(runs_dir.glob("*.degraded*.json"))]
    for p in sorted(runs_dir.glob("*.json")):
        if ".degraded" in p.name:
            continue
        rec = json.loads(p.read_text())
        pm = rec.get("prime_mode", "n0")
        f = rec["federation"] + ("" if pm == "separate" else "_prime_n0")
        if not rec.get("health", {}).get("ok") or not rec.get("passes"):
            degraded.append(str(p))
            continue
        arms = rec["arms"]
        mp = [ps for ps in rec["passes"] if ps["kind"] == "measured"]
        rows = [r for ps in mp for r in ps["rows"] if not r.get("prime")]
        fd = {"status": "PARTIAL (process did not finish)" if rec.get("partial") else "COMPLETE",
              "file": str(p), "prime_mode": pm,
              "n0_bias_warning": (None if pm == "separate" else
                                  "BIASED: n0 was also the priming retriever (instance-warm); every "
                                  "statistic involving n0 in this entry is not valid (REVISION 2)"),
              "measured_passes": len(mp), "arms": {}, "wall_s": rec.get("wall_s"),
              "pass_wall_s": [ps["wall_s"] for ps in rec["passes"]], "maxrss_gb": rec.get("maxrss_gb"),
              "health_arms": rec["health"].get("arms"), "quiet_gate_start": {k: v for k, v in rec.get("quiet_gate", {}).items()},
              "quiet_waits": rec.get("quiet_waits"), "host_start": rec.get("host_start"), "host_end": rec.get("host_end"),
              "n_warnings_during_passes": rec["health"].get("n_warnings_during_passes")}
        for a in arms:
            ar = [r for r in rows if r["arm"] == a]

            def col(k, _ar=ar):
                return [r[k] for r in _ar if r.get(k) is not None]
            fd["arms"][a] = {
                "n_gen": ARMS[a], "n_calls": len(ar), "p50_ms": pct(col("ms"), 50), "p95_ms": pct(col("ms"), 95),
                "mean_ms": round(statistics.fmean(col("ms")), 2) if ar else None,
                "per_pass_p50_ms": [pct([r["ms"] for r in ps["rows"] if r["arm"] == a and not r.get("prime")], 50)
                                    for ps in mp],
                "legs_p50_ms": {"bm25f": pct(col("bm25f_ms"), 50), "splade": pct(col("splade_ms"), 50),
                                "splade_encode": pct(col("encode_ms"), 50),
                                "seismic_traverse": pct(col("traverse_ms"), 50)},
                "components_mean_ms": {k: round(statistics.fmean([r.get("comp", {}).get(k, 0.0) for r in ar]), 3)
                                       for k in COMP_KEYS},
                "serial_delta_ms_mean": round(statistics.fmean([serial_delta(r) for r in ar]), 3),
                "serial_delta_ms_p50": pct([serial_delta(r) for r in ar], 50),
                "seismic_delta_increment_ms_mean": round(statistics.fmean([seismic_inc(r, f) for r in ar]), 3),
                "seismic_delta_shard_sum_ms_mean": round(statistics.fmean([r.get("shard_delta_sum_ms", 0.0) for r in ar]), 3),
                "shard_base_max_ms_p50": pct(col("shard_base_max_ms"), 50),
                "majflt_mean": round(statistics.fmean(col("majflt")), 1),
                "delta_docs_in_top10_mean": round(statistics.fmean(col("n_delta_top10")), 3),
                "delta_docs_in_top50_mean": round(statistics.fmean(col("n_delta_top50")), 3),
                "p50_by_position": {str(pos): pct([r["ms"] for r in ar if r["position"] == pos], 50)
                                    for pos in range(len(arms))},
            }
        prime = [r["ms"] for ps in mp for r in ps["rows"] if r.get("prime")]
        fd["prime_n0_p50_ms"] = pct(prime, 50)
        fd["p50_by_position_all_arms"] = {str(pos): pct([r["ms"] for r in rows if r["position"] == pos], 50)
                                          for pos in range(len(arms))}
        pts = [(ARMS[a], fd["arms"][a]["p50_ms"]) for a in ("n0", "n1", "n4", "n8") if a in fd["arms"]]
        full = len(pts) == 4
        fd["slope_primary_ms_per_gen_ols_0_1_4_8"] = ols([x for x, _ in pts], [y for _, y in pts]) if full else None
        fd["slope_primary_per_pass"] = []
        for ps in mp:
            pp = [(ARMS[a], pct([r["ms"] for r in ps["rows"] if r["arm"] == a and not r.get("prime")], 50))
                  for a in ("n0", "n1", "n4", "n8") if a in fd["arms"]]
            fd["slope_primary_per_pass"].append({"pass": ps["pass"], "slope": ols([x for x, _ in pp], [y for _, y in pp]),
                                                 "p50s": {str(x): y for x, y in pp}})
        pts148 = [p_ for p_ in pts if p_[0] > 0]
        fd["slope_secondary_ols_1_4_8"] = ols([x for x, _ in pts148], [y for _, y in pts148]) if full else None
        byq: dict = {}
        for ps in mp:
            for r in ps["rows"]:
                if not r.get("prime") and r["arm"] in ("n0", "n1", "n4", "n8"):
                    byq.setdefault((ps["pass"], r["topic"]), {})[ARMS[r["arm"]]] = r["ms"]
        qslopes = [ols(sorted(v), [v[k] for k in sorted(v)]) for v in byq.values() if len(v) == 4]
        qslopes = [x for x in qslopes if x is not None]
        fd["paired_per_query_slope_ms_per_gen"] = {
            "n": len(qslopes), "median": round(statistics.median(qslopes), 3) if qslopes else None,
            "mean": round(statistics.fmean(qslopes), 3) if qslopes else None,
            "bootstrap95_median": _boot_ci(qslopes, 20260929)}
        cmp_ = {}
        for a, b_ in (("n1", "n0"), ("n4", "n0"), ("n8", "n0"), ("n8", "n1"), ("n8c", "n1"), ("n4c", "n1"),
                      ("n8c", "n8"), ("n4c", "n4")):
            pairs = {}
            for ps in mp:
                for r in ps["rows"]:
                    if not r.get("prime") and r["arm"] in (a, b_):
                        pairs.setdefault((ps["pass"], r["topic"]), {})[r["arm"]] = r["ms"]
            d = [v[a] - v[b_] for v in pairs.values() if a in v and b_ in v]
            if d:
                cmp_[f"{a}_minus_{b_}"] = {"n": len(d), "median_ms": round(statistics.median(d), 2),
                                           "bootstrap95_median": _boot_ci(d, 20260929)}
        fd["paired_differences"] = cmp_
        cpts = [(ARMS[a], fd["arms"][a]["serial_delta_ms_mean"] + fd["arms"][a]["seismic_delta_increment_ms_mean"])
                for a in ("n0", "n1", "n4", "n8") if a in fd["arms"]]
        fd["component_tax_ms_per_gen_ols_0_1_4_8"] = ols([x for x, _ in cpts], [y for _, y in cpts]) if len(cpts) == 4 else None
        fd["component_tax_points_mean_ms"] = {str(x): round(y, 3) for x, y in cpts}
        s = fd["slope_primary_ms_per_gen_ols_0_1_4_8"] if pm == "separate" else None
        fd["verdict_growth_bar_le_8ms"] = "PASS" if s is not None and s <= 8.0 else ("FAIL" if s is not None else "NOT DECIDED")
        fd["go_line_ge_3ms"] = None if s is None else ("MET (tax >= 3 ms/gen)" if s >= 3.0 else "NOT MET (tax < 3 ms/gen)")
        a1 = fd["arms"].get("n1", {}).get("p50_ms")
        comp = {}
        for c in ("n8c", "n4c"):
            pc = fd["arms"].get(c, {}).get("p50_ms")
            if pc is not None and a1:
                ratio = round(pc / a1, 4)
                comp[c] = {"p50_ms": pc, "n1_p50_ms": a1, "ratio_vs_n1": ratio,
                           "verdict_within_5pct": "PASS" if abs(ratio - 1) <= 0.05 else "FAIL"}
            else:
                comp[c] = {"verdict_within_5pct": "NOT MEASURED"}
        fd["compaction"] = comp
        feds[f] = fd
    log_scan = {p.name: scan_log(p) for p in sorted(runs_dir.glob("*.log"))}
    builds = {p.name: json.loads(p.read_text()) for p in sorted(WORK.glob("build_n*.json"))}
    comps = {p.name: json.loads(p.read_text()) for p in sorted(WORK.glob("compact_n*.json"))}
    corpus = json.loads(CORPUS.read_text())
    corpus.pop("ids", None)
    res = {
        "measurement": "M4 read amplification per live delta generation (docs/delta_ingest/03_SPIKE_PLAN.md)",
        "bar_preregistered": ("03_SPIKE_PLAN.md M4: search_rrf p50/p95 with 0, 1, 4, 8 live generations of "
                              "corpus (b) split evenly, before and after compact -> p50 growth <= +8 ms per "
                              "generation *est.* budget, and compaction returns to within 5% of the "
                              "1-generation arm"),
        "go_line": "05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md section 6 / 06_INPLACE_SPIKE_PLAN.md: GO input = OLS "
                   "slope of search_rrf p50 (parallel) over N in {0,1,4,8}; GO needs >= 3 ms p50/gen",
        "design": "inproc (see the script header REVISION 2026-09-29, written before any measured run)",
        "script": "scripts/experiments/eval_delta_ingest_m4_read_amp.py",
        "git_commit_measured_code": commit, "code_snapshot": str(snap),
        "date_utc": time.strftime("%Y-%m-%d", time.gmtime()), "seed_order": args.seed,
        "warmup_passes": args.warmup, "measured_passes": args.passes, "top_k": TOP_K,
        "topics_file": str(TOPICS.relative_to(REPO)), "query_field": "natural",
        "limit_topics": args.limit_topics or 120,
        "corpus_b": corpus, "base_manifest": str(BASE_MANIFEST), "builds": builds, "compactions": comps,
        "federations": feds, "degraded_or_retried": degraded, "log_scan": log_scan,
        "log_scan_enomem_hits": {k: v["signature_counts"]["Cannot allocate memory"] for k, v in log_scan.items()
                                 if v["signature_counts"]["Cannot allocate memory"]},
        "runs_dir": str(runs_dir),
    }
    out = Path(args.out) if args.out else REPO / f"data/eval_results/delta_ingest_M4_{time.strftime('%Y%m%d', time.gmtime())}.json"
    out.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({f: {k: v for k, v in fd.items() if k in (
        "status", "slope_primary_ms_per_gen_ols_0_1_4_8", "slope_primary_per_pass", "slope_secondary_ols_1_4_8",
        "paired_per_query_slope_ms_per_gen", "component_tax_ms_per_gen_ols_0_1_4_8", "verdict_growth_bar_le_8ms",
        "go_line_ge_3ms", "compaction", "paired_differences")} for f, fd in feds.items()}, indent=1))
    return 0


def _leg_parts(r: dict) -> dict:
    c = r.get("comp", {})
    bm, sp = r.get("bm25f_ms") or 0.0, r.get("splade_ms") or 0.0
    tr, en = r.get("traverse_ms") or 0.0, r.get("encode_ms") or 0.0
    delta_sec = c.get("bm25f_delta", 0.0) + c.get("bm25f_buffer", 0.0)
    hyd_named = c.get("abs_base", 0.0) + c.get("abs_delta", 0.0) + c.get("delta_meta", 0.0) + c.get("delta_buffer_abs", 0.0)
    return {"total": r["ms"],
            "bm25f_base_sections": c.get("bm25f_base", 0.0),
            "bm25f_delta_sections": delta_sec,
            "bm25f_other_parse_merge_masks": bm - c.get("bm25f_base", 0.0) - delta_sec,
            "seismic_traverse": tr, "splade_encode": en, "splade_other_delta_merge": sp - tr - en,
            "hydrate_abstracts_base": c.get("abs_base", 0.0), "hydrate_abstracts_delta": c.get("abs_delta", 0.0),
            "hydrate_delta_meta": c.get("delta_meta", 0.0),
            "hydrate_other_base_meta_fuse": r["ms"] - bm - sp - hyd_named}


def annotate(args) -> int:
    """POST-HOC analysis block (not pre-registered) added to the M4 results
    file: per-leg attribution of the generation tax, bootstrap CI of the
    primary statistic, the discarded run's numbers, and the compaction run."""
    res = json.loads(Path(args.out).read_text())
    rec = json.loads(Path(args.primary_rows).read_text())
    arms4 = ("n0", "n1", "n4", "n8")
    rows = [r for ps in rec["passes"] if ps["kind"] == "measured" for r in ps["rows"] if not r.get("prime")]
    units: dict = {}
    for ps in [x for x in rec["passes"] if x["kind"] == "measured"]:
        for r in ps["rows"]:
            if not r.get("prime"):
                units.setdefault((ps["pass"], r["topic"]), {})[r["arm"]] = r
    full = [u for u in units.values() if all(a in u for a in arms4)]
    rng = random.Random(20260929)
    boot = []
    for _ in range(2000):
        smp = rng.choices(full, k=len(full))
        boot.append(ols([0, 1, 4, 8], [pct([u[a]["ms"] for u in smp], 50) for a in arms4]))
    boot.sort()
    keys = list(_leg_parts(rows[0]).keys())
    means = {a: {k: statistics.fmean([_leg_parts(r)[k] for r in rows if r["arm"] == a]) for k in keys} for a in arms4}
    legs = {}
    for k in keys:
        d8 = [_leg_parts(u["n8"])[k] - _leg_parts(u["n0"])[k] for u in full]
        qs = [ols([0, 1, 4, 8], [_leg_parts(u[a])[k] for a in arms4]) for u in full]
        legs[k] = {"arm_means_ms": {a: round(means[a][k], 2) for a in arms4},
                   "ols_slope_of_means_ms_per_gen": ols([0, 1, 4, 8], [means[a][k] for a in arms4]),
                   "paired_n8_minus_n0_median_ms": round(statistics.median(d8), 2),
                   "paired_n8_minus_n0_mean_ms": round(statistics.fmean(d8), 2),
                   "paired_per_query_slope_median_ms_per_gen": round(statistics.median(qs), 3)}
    shard = {a: {"slowest_base_shard_p50_ms": pct([r["shard_base_max_ms"] for r in rows if r["arm"] == a], 50),
                 "slowest_shard_any_p50_ms": pct([r["shard_all_max_ms"] for r in rows if r["arm"] == a], 50),
                 "delta_shards_own_time_sum_mean_ms": round(statistics.fmean([r["shard_delta_sum_ms"] for r in rows if r["arm"] == a]), 2),
                 "traverse_minus_slowest_shard_mean_ms": round(statistics.fmean(
                     [r["traverse_ms"] - r["shard_all_max_ms"] for r in rows if r["arm"] == a]), 2)}
             for a in arms4}
    ph = res.setdefault("post_hoc", {})
    ph["note"] = ("POST-HOC (not pre-registered), added after the run by `annotate`; the bar verdicts above "
                  "are computed only from the pre-registered statistics")
    ph["primary_slope_bootstrap95"] = {"what": "OLS of arm p50 over N in {0,1,4,8}, resampling (pass, topic) units "
                                       "with all four arms, 2000 resamples, seed 20260929",
                                       "n_units": len(full), "ci": [boot[50], boot[1949]],
                                       "width_ms": round(boot[1949] - boot[50], 3)}
    ph["leg_attribution_parallel"] = {"what": "per-call leg split of search_rrf; means are additive, medians are "
                                      "not; 'ols_slope_of_means' of all legs sums to the mean-total slope",
                                      "legs": legs, "seismic_shards": shard}
    if args.discarded_summary:
        ds = json.loads(Path(args.discarded_summary).read_text())
        f = ds["federations"]["parallel_prime_n0"]
        ph["discarded_run_inproc_main"] = {
            "status": "DISCARDED for the n0 arm (REVISION 2, commit 60f24f4c); not used for any verdict",
            "why": ("the PRIME call ran on the n0 retriever itself, leaving that instance warm (own SQLite "
                    "connection caches for meta/abstracts on 9p, own shard mappings): in measured pass 2 n0 had "
                    "median traverse 48 ms vs 193 ms for n1, hydration 5 vs 77 ms, 5 vs 723 major faults per "
                    "call, p50 ~370 ms below every delta arm"),
            "runs_dir": "/home/vscode/work/inplace_update/m4/inproc_main", "code_snapshot_commit": "585f3cab",
            "prime_mode": "n0", "arms": list(f["arms"]),
            "slope_primary_biased_ms_per_gen": f["slope_primary_ms_per_gen_ols_0_1_4_8"],
            "slope_primary_per_pass_biased": f["slope_primary_per_pass"],
            "slope_ols_1_4_8_unaffected_by_prime": f["slope_secondary_ols_1_4_8"],
            "paired_per_query_slope_biased": f["paired_per_query_slope_ms_per_gen"],
            "paired_differences": f["paired_differences"],
            "compaction_same_process": f["compaction"],
            "arm_p50_ms": {a: v["p50_ms"] for a, v in f["arms"].items()}}
    if args.compaction_rows:
        crec = json.loads(Path(args.compaction_rows).read_text())
        cm = [x for x in crec["passes"] if x["kind"] == "measured"]
        crow = [r for x in cm for r in x["rows"] if not r.get("prime")]
        ok = crec.get("health", {}).get("ok") and not crec.get("partial")
        cmp_ = {"status": "COMPLETE" if ok else "DEGRADED/PARTIAL", "file": args.compaction_rows,
                "prime_mode": crec.get("prime_mode"), "arms": crec["arms"], "measured_passes": len(cm),
                "host_start": crec.get("host_start"), "host_end": crec.get("host_end"),
                "quiet_gate_start": {k: v for k, v in crec.get("quiet_gate", {}).items() if k != "samples"},
                "not_quiet_inline_checks": [w for w in crec.get("quiet_waits", []) if not w["quiet"]],
                "arm_p50_ms": {a: pct([r["ms"] for r in crow if r["arm"] == a], 50) for a in crec["arms"]},
                "arm_p95_ms": {a: pct([r["ms"] for r in crow if r["arm"] == a], 95) for a in crec["arms"]}}
        a1 = cmp_["arm_p50_ms"].get("n1")
        for c in ("n8c", "n4c"):
            pc = cmp_["arm_p50_ms"].get(c)
            if ok and pc and a1:
                ratio = round(pc / a1, 4)
                pr = {}
                for x in cm:
                    for r in x["rows"]:
                        if not r.get("prime") and r["arm"] in (c, "n1"):
                            pr.setdefault((x["pass"], r["topic"]), {})[r["arm"]] = r["ms"]
                dd = [v[c] - v["n1"] for v in pr.values() if c in v and "n1" in v]
                cmp_[c] = {"ratio_vs_n1": ratio, "verdict_within_5pct": "PASS" if abs(ratio - 1) <= 0.05 else "FAIL",
                           "paired_minus_n1_median_ms": round(statistics.median(dd), 2),
                           "paired_minus_n1_bootstrap95": _boot_ci(dd, 20260929)}
        if "n8" in cmp_["arm_p50_ms"] and a1:
            cmp_["n8_ratio_vs_n1"] = round(cmp_["arm_p50_ms"]["n8"] / a1, 4)
        res["compaction_run"] = cmp_
        if ok:
            res["federations"]["parallel"]["compaction"] = {
                c: {"p50_ms": cmp_["arm_p50_ms"].get(c), "n1_p50_ms": a1, "ratio_vs_n1": cmp_[c]["ratio_vs_n1"],
                    "verdict_within_5pct": cmp_[c]["verdict_within_5pct"],
                    "source": "compaction_run (separate process, same design, arms n1,n8,n4c,n8c)"}
                for c in ("n8c", "n4c") if c in cmp_}
    for n in args.note:
        ph.setdefault("notes", []).append(n)
    Path(args.out).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({"primary_ci": ph["primary_slope_bootstrap95"], "compaction": res.get("compaction_run", {}).get("n8c")}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, required=True)
    b.add_argument("--reuse-seismic-from", default="",
                   help="root dir name under WORK (e.g. root_n4) whose generation SEISMIC dirs are copied")
    c = sub.add_parser("compact")
    c.add_argument("--n", type=int, required=True)
    for sp in (b, c):
        sp.add_argument("--layout", choices=sorted(LAYOUT_PREFIX), default="per_base_section",
                        help="09 L2 generation layout; roots are named root_{n,e,s}<N>[c]")
        sp.add_argument("--seismic-threads", type=int, default=0,
                        help="override the desktop_gpu profile's SEISMIC build threads (0 = profile)")
    d = sub.add_parser("drive")
    d.add_argument("--rounds", type=int, default=3)
    d.add_argument("--passes", type=int, default=2)
    d.add_argument("--warmup", type=int, default=1)
    d.add_argument("--arms", default="n0,n1,n4,n8,n4c,n8c")
    d.add_argument("--federations", default="parallel,sequential")
    d.add_argument("--seed", type=int, default=20260929)
    d.add_argument("--tag", default="main")
    d.add_argument("--limit-topics", type=int, default=0)
    d.add_argument("--retries", type=int, default=1)
    d.add_argument("--child-timeout", type=int, default=3600)
    d.add_argument("--max-seconds", type=int, default=0)
    d.add_argument("--commit", default="")
    d.add_argument("--out", default="")
    d.add_argument("--quiet-wait", type=int, default=600)
    s = sub.add_parser("summarize")
    for a, kw in (("--rounds", {"type": int, "default": 3}), ("--passes", {"type": int, "default": 2}),
                  ("--warmup", {"type": int, "default": 1}), ("--arms", {"default": "n0,n1,n4,n8,n4c,n8c"}),
                  ("--federations", {"default": "parallel,sequential"}), ("--seed", {"type": int, "default": 20260929}),
                  ("--tag", {"default": "main"}), ("--commit", {"default": ""}), ("--out", {"default": ""})):
        s.add_argument(a, **kw)
    ch = sub.add_parser("child")
    ch.add_argument("--arm", required=True, choices=sorted(ARMS))
    ch.add_argument("--federation", required=True, choices=["parallel", "sequential"])
    ch.add_argument("--round", type=int, default=1)
    ch.add_argument("--passes", type=int, default=2)
    ch.add_argument("--warmup", type=int, default=1)
    ch.add_argument("--rows-out", required=True)
    ch.add_argument("--limit-topics", type=int, default=0)
    ch.add_argument("--src", default=str(REPO / "src"))
    ch.add_argument("--quiet-wait", type=int, default=600)
    ip = sub.add_parser("inproc")
    ip.add_argument("--federation", required=True, choices=["parallel", "sequential"])
    ip.add_argument("--arms", default="n0,n1,n4,n8,n4c,n8c")
    ip.add_argument("--passes", type=int, default=2)
    ip.add_argument("--warmup", type=int, default=1)
    ip.add_argument("--rows-out", required=True)
    ip.add_argument("--limit-topics", type=int, default=0)
    ip.add_argument("--src", default=str(REPO / "src"))
    ip.add_argument("--quiet-wait", type=int, default=900)
    ip.add_argument("--inline-wait", type=int, default=120)
    ip.add_argument("--seed", type=int, default=20260929)
    ip.add_argument("--prime-mode", choices=["separate", "n0"], default="separate")
    idr = sub.add_parser("inproc-drive")
    idr.add_argument("--federations", default="parallel,sequential")
    idr.add_argument("--arms", default="n0,n1,n4,n8,n4c,n8c")
    idr.add_argument("--passes", type=int, default=2)
    idr.add_argument("--warmup", type=int, default=1)
    idr.add_argument("--limit-topics", type=int, default=0)
    idr.add_argument("--quiet-wait", type=int, default=900)
    idr.add_argument("--inline-wait", type=int, default=120)
    idr.add_argument("--seed", type=int, default=20260929)
    idr.add_argument("--tag", default="main")
    idr.add_argument("--retries", type=int, default=0)
    idr.add_argument("--child-timeout", type=int, default=4 * 3600)
    idr.add_argument("--commit", default="")
    idr.add_argument("--out", default="")
    isu = sub.add_parser("inproc-summarize")
    for a, kw in (("--passes", {"type": int, "default": 2}), ("--warmup", {"type": int, "default": 1}),
                  ("--limit-topics", {"type": int, "default": 0}), ("--seed", {"type": int, "default": 20260929}),
                  ("--tag", {"default": "main"}), ("--commit", {"default": ""}), ("--out", {"default": ""})):
        isu.add_argument(a, **kw)
    an = sub.add_parser("annotate")
    an.add_argument("--out", required=True)
    an.add_argument("--primary-rows", required=True)
    an.add_argument("--discarded-summary", default="")
    an.add_argument("--compaction-rows", default="")
    an.add_argument("--note", action="append", default=[])
    args = ap.parse_args()
    if args.cmd == "annotate":
        return annotate(args)
    if args.cmd == "inproc-summarize":
        commit = args.commit or git_commit()
        return inproc_summarize(args, commit, WORK / f"code_{commit[:8]}", WORK / f"inproc_{args.tag}")
    if args.cmd == "summarize":
        commit = args.commit or git_commit()
        return summarize(args, commit, WORK / f"code_{commit[:8]}", WORK / f"runs_{args.tag}")
    return {"prepare": prepare, "build": build, "compact": compact_root, "drive": drive,
            "child": child, "inproc": inproc, "inproc-drive": inproc_drive}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
