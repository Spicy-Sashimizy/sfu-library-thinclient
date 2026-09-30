#!/usr/bin/env python3
"""Delta-ingest M3: BM25F score drift (T1) on corpus (a)
(docs/delta_ingest/03_SPIKE_PLAN.md M3; issue T1 of 02_DESIGN.md section 3).

PRE-REGISTERED (row copied verbatim from 03_SPIKE_PLAN.md M3; written into
this header 2026-09-30 before any M3 number existed; the operational
definitions below were fixed at the same time, before the fixture existed):

  metric : for corpus (a): rank of each updated doc for its title-as-query
           with the update served from a delta section vs from the base; and
           the number of NON-updated base docs displaced out of the fused
           top-10 across the 120 topics
  bar    : median rank change 0; displaced base docs <= 5% of top-10 slots

Fixture (NOT built here): corpus (a) as published by the M2 agent at
/home/vscode/work/delta_ingest/corpus_a/ -- one generation g0001 of 50,000
base docs re-ingested as updates with one appended sentence, livedocs bitset
masking their base ordinals. READY.json gives the delta root, the env of the
gate-on / gate-off arms, the 50,000 updated ids, the title-query sample and
the fixture commit. This harness never writes under corpus_a/.

Arms (each its own process, run one after the other, never concurrently):
  BASE  : gate off. SFU_DELTA_ROOT="" (blank, not unset: lib.config's .env
          loader re-injects unset keys), SFU_SEISMIC_SHARD_MANIFEST =
          /home/vscode/work/inplace_update/m4/base_manifest.json (frozen copy
          of the dv-v2 e5 manifest the served process maps), plus whatever
          READY.json lists for its gate-off arm.
  DELTA : gate on. SFU_DELTA_ROOT=<fixture root>, SFU_SEISMIC_SHARD_MANIFEST=""
          (the delta composed manifest serves), SFU_THINCLIENT_ORDINALS =
          /var/tmp/sfu_delta_C_20260929/ords (local copy), plus READY.json's
          gate-on env.
  Both  : SFU_SEISMIC_STAGE_DIR="" SFU_META_STAGE_DIR="" (the child aborts if
          either is non-blank), SFU_SEARCH_SPECULATIVE_RERANK="",
          SFU_SEISMIC_FEDERATION=parallel, remote abstracts stubbed to {}.
          Code under test = `git archive <HEAD at drive time> src` under
          /home/vscode/work/delta_ingest/m3/code_<c8>/. Run as
          `nice -n 10 taskset -c 8-15`, no latency lock (timings are NOT
          deliverables: every timing field is recorded with
          timings_valid=false).

Part A -- rank drift, BM25F leg ONLY:
  entry point : ThinClientRetriever._bm25f_leg(title, 100, None), the
                tantivy leg `search(mode="bm25f")` wraps (all live sections,
                raw-score merge, then the delta masks via
                DeltaLayer.filter_hits when the layer is loaded). No SPLADE,
                no fusion, no rerank.
  sample      : the title-query sample of READY.json, same ids, same order.
                N_A = 600: the deterministic prefix of the first 600 entries
                (or all of them if the sample is smaller). Reason: a pilot
                on 2026-09-30 17:58Z (40 seed titles of
                data/sfu_eval_queries.json, gate off, NOT the sample, not a
                result) measured the leg at p50 4.2 s per title query on this
                loaded host, so 2 arms x 600 = ~85 min, which with Part B
                fits before the 2026-09-30 23:30Z hard deadline. Queries run
                in sample order; if an arm hits its deadline the comparison
                uses the common prefix and the result is PARTIAL.
  rank        : 1-based position of the doc id in the leg's returned top-100
                (after masks); > 100 = "absent".
  statistic   : median over docs present in BOTH arms of
                (rank_DELTA - rank_BASE). Bar: == 0 (PASS iff the median is
                exactly 0). Reported: quantiles (min, p5, p25, p50, p75, p95,
                max), share improved (<0) / same (0) / worse (>0), counts
                absent in BASE only / DELTA only / both, base own-recall@100.
  scores      : in the DELTA process the pre-mask hit list is captured
                (wrapper around DeltaLayer.filter_hits, which receives
                (id, score, origin)): raw score of the delta copy (origin =
                generation) and of the masked base copy (origin None) of the
                same doc for the same query in the same process; ratio
                delta/base quantiles. The BASE arm's score of the same doc is
                recorded as a cross-process check (it should equal the
                pre-mask base-copy score).
  mask leak   : count of sample queries whose post-mask list contains the
                updated doc's BASE copy (origin None). Must be 0. Also counted
                over every updated id in any Part A list and over both copies
                of one id appearing together.

Part B -- displacement, full fused list:
  queries     : the 120 natural topics, data/sfu_eval_queries.json field
                "query" (file order), 1 pass per arm.
  call        : retriever.search_rrf_detailed(q, top_k=50) -- the same legs in
                the same order and the same RRF fusion as search_rrf(q,
                top_k=50) (its docstring; ranking bit-identical), used so the
                per-leg lists come from the same retrieval pass. `rrf_legs`
                is stripped before the rerank.
  final       : lib.tools._maybe_rerank(deepcopy(fused), q, 10) (as M1).
  displaced   : a doc in the BASE-arm fused top-10 that is NOT one of the
                50,000 updated ids and is absent from the DELTA-arm fused
                top-10. Summed over 120 topics. Bar: <= 5% of the 1,200
                top-10 slots, i.e. <= 60 -> PASS.
  reported    : updated ids entering a gate-on fused top-10 (in DELTA top-10,
                not in BASE top-10), updated ids in each arm's top-10; the
                same displacement count computed on the BM25F leg's own
                top-10 and on the SPLADE leg's own top-10 (attribution);
                final (reranked) top-10 id-list change count and the
                displacement count on the final top-10 (supplementary, no
                bar).

Health (per process, before any measured query; a failure marks the arm
DEGRADED and its numbers are not used): SPLADE ONNX encoder returns a
non-empty vector; SEISMIC backend is ParallelSeismicBackend with 8 shards
(BASE) or 9 (DELTA, 8 + g0001), none missing; DELTA: delta layer loaded with
exactly the READY.json generations, livedocs loaded, delta sections loaded,
served manifest == delta composed manifest; BASE: no delta layer;
cross-encoder loaded; embedding model loaded. After the run: every Part B
query reached the SEISMIC traverse; log scan for the O12 / fallback
signatures (SIGNATURES below) over the child log.

REVISION 1, 2026-09-30 19:25Z, BEFORE any measured run (bars, sample,
statistics unchanged): READY.json landed with its own schema (ids in
sample.json "ids", title sample in title_sample.json "order"/"titles"
aligned, generations in verify.gens); load_ready() now reads exactly that.
SFU_THINCLIENT_ORDINALS follows READY.json's env (blank in both arms): the
livedocs bitset takes its ordinal_dir (/var/tmp/sfu_delta_C_20260929/ords,
the same local copy) from generations.json, and the retriever's own
ordinals object is used only by filtered post-filters, which no M3 call
uses (filters=None).

REVISION 2, 2026-09-30 ~19:35Z, BEFORE any measured run (coordinator
decision; bars, samples and statistics unchanged): the M2 agent's delta arm
occupies the index slot until ~23:15Z, so M3 runs ALONGSIDE it (two
index-loading processes, started only on the coordinator's GO and only if
MemAvailable >= 18 GB). Order changed so the promotion-relevant number
exists first: four processes in sequence -- base:B, delta:B, base:A,
delta:A (each asserts the same health before its first query). Cores:
taskset -c 0-7 if the latency lock is free at each process start (probed
with flock -n, lock NOT held), else 8-15 (--cpus auto). Memory gate: the
first process needs MemAvailable >= 18 GB (checked by hand at GO), every
process start >= 10 GB (--min-mem-gb 10), else it waits.
REVISION 3, 2026-09-30 20:20Z (the first launch at 20:16:57Z crashed in
every child at `import lib.tools` with OSError [Errno 12] on a .venv
directory read over 9p -- O12 -- before any retriever was built or query
ran; 2 of 4 bare `import idna` probes failed the same way with 26 GB
available and CommitLimit 33.2 GB vs Committed_AS 30.3 GB): a child that
exits non-zero with ENOMEM in its log before printing any progress line is
re-started (up to --retries, 20 s apart); each failed attempt's log is kept
and listed under o12_failed_start_attempts. A process that got past start-up
is never re-run; health assertions are unchanged.
REVISION 4, 2026-09-30 ~21:25Z (coordinator; serving-config detail, metric
unchanged): once /home/vscode/work/models_local/READY exists, children may
be launched with SFU_SPLADE_MODEL_PATH / SFU_CE_MODEL_PATH pointing at local
byte-identical copies of models/splade_onnx_fused and
models/sfu-cross-encoder-v1 (sha256 of every .onnx/.safetensors recorded per
launch in model_files), and with the local venv mirror
/home/vscode/work/venv_local/bin/python3 once it exists. A relaunch may
resume the schedule at the first step not yet completed (--schedule);
every launch writes its own runs/drive_<HHMMSS>.json and summarize merges
them. If Part A cannot finish by the deadline it is recorded
PARTIAL with the count reached. [That last sentence belongs to REVISION 2.]
REVISION 5, 2026-09-30 21:55Z (base:A running at ~7 s per title, 38/600
done; statistic, sample order and bar unchanged): Part A is compared on the
common prefix of the two arms (as pre-registered for a deadline cut). To
maximise that prefix, base:A is stopped by an external watcher
(m3/stop_base_A.sh) right after its first 25-row flush at or after 22:36Z
(SIGTERM to the child; rows up to that flush are kept, the process is
marked partial) so delta:A gets the remaining time to the 23:25Z deadline
instead of ~25 min. Part A will be PARTIAL. Also recorded from 21:52Z: the
SPLADE tokenizer dir each process resolved (splade_tokenizer_resolution).
REVISION 6, 2026-09-30 21:56Z: the first base:A process crashed at sample row
57 (0-based 56) because `_bm25f_leg` raised `ValueError: Syntax Error` from
tantivy's query parser on the title "INNOVATION IN THE EV INDUSTRY: CASE
STUDY OF TESLA 2019-2025" (the leg only strips non-alphanumerics; upper-case
IN/AND/OR/NOT survive as parser operators). A title whose leg call raises is
now recorded as an error row in that arm, excluded from the rank statistic
(it cannot rank in either arm since the query text is identical) and listed
under query_errors. base:A is re-run from row 0 (its 56 rows from the
crashed process are discarded, kept on disk as base_A.crashed.log); the
revision-5 stop time is unchanged. The code under test is unchanged:
snapshot code_611ee06b has `git diff dfc06e6e 611ee06b -- src` empty, so
base:B (code_dfc06e6e) and every later process run the same src.
REVISION 7, 2026-09-30 22:22Z (coordinator; statistic and bar unchanged):
the revision-5 22:36Z stop is CANCELLED. Another session is running
swapoff/swapon to bring its ~15 GB swapped S0-2 process back into RAM and
asked that no new index-loading process start until S0-2 has exited.
base:A keeps running; on the coordinator's GO it is stopped at its next
25-row flush (m3/stop_at_flush.sh) and delta:A starts immediately with the
time left before 23:25Z; delta:A's row count bounds the common prefix and
Part A is PARTIAL. If no GO by 23:05Z, the drive is killed first (so
delta:A never starts) and base:A is stopped at its next flush
(m3/fallback_2305.sh): Part A = base-only, delta NOT RUN, and the median
bar is NOT RUN.

Run:
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m3_bm25f_drift.py drive --deadline 2026-09-30T23:25:00Z
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m3_bm25f_drift.py summarize
"""
from __future__ import annotations

import argparse
import calendar
import copy
import hashlib
import json
import logging
import os
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path("/home/vscode/work/delta_ingest/m3")
FIXTURE = Path("/home/vscode/work/delta_ingest/corpus_a")
READY = FIXTURE / "READY.json"
BASE_MANIFEST = Path("/home/vscode/work/inplace_update/m4/base_manifest.json")
ORDS = "/var/tmp/sfu_delta_C_20260929/ords"
TOPICS = REPO / "data/sfu_eval_queries.json"
OUT = REPO / "data/eval_results/delta_ingest_M3_20260930.json"
N_A = 600
A_TOPK = 100
TOP_K = 50
LIMIT = 10
BAR_DISPLACED = 60
N_BASE_SHARDS = 8
O12_EVENTS = [
    {"utc": "2026-09-30T19:20Z", "what": "a short python3 start-up (inspection one-liner run by this agent, cwd "
     "/workspaces, no index loaded) failed with OSError [Errno 12] Cannot allocate memory: "
     "'/workspaces/sfu-library-thinclient' in init_fs_encoding while S0-2 held ~21 GB and MemAvailable was "
     "~9 GB; re-run from cwd /tmp it succeeded. Not a measured process."},
    {"utc": "2026-09-30T20:16:57Z..20:20:31Z", "what": "M3 launches 1 and 2: every child (base:B x7, delta:B, "
     "base:A) died before any query -- ENOMEM on .venv imports, or health FAIL (encode_splade OSError 12, "
     "cross-encoder and embedding model not loaded). Logs under /home/vscode/work/delta_ingest/m3/"
     "failed_launch_2016Z/ and runs/*.attemptN.log. Bare import probe from /tmp: 2/10 at 20:21Z, 1/5 at "
     "20:22Z (MemFree 897 MB) and 20:27Z (MemFree 2316 MB)."},
    {"utc": "2026-09-30T20:58Z", "what": "coordinator's root cause (verified by strace of a failing import): "
     "`read(3, ..., 48565) = -1 ENOMEM` and `getdents64(3, ..., 32768) = -1 ENOMEM` on the /workspaces 9p "
     "mount; the kernel 9p client request buffers need order-3/4 contiguous pages and /proc/buddyinfo showed "
     "1 free order-4 block and none above in zone Normal (MemFree 160-900 MB, 25 GB page cache); forced "
     "compaction did not fix it (probe 8/8 failed); /proc/sys read-only so vm.min_free_kbytes cannot be raised."},
    {"utc": "2026-09-30", "what": "WORKAROUND used by the measured run: interpreter = local venv mirror "
     "/home/vscode/work/venv_local (retrying rsync of the .venv, same site-packages, pyvenv home /usr/bin); "
     "code = git-archive snapshot + a copy of this harness on local disk; model files, the topics file and "
     ".env pre-read into the page cache with a retrying cat (m3/prewarm.sh) before launch. Index files "
     "(tantivy sections, meta.sqlite, abstracts) are still read from 9p."},
    {"utc": "2026-09-30T20:50Z..21:26Z", "what": "INTERPRETER / MODEL COPY PER PROCESS: base:B (20:50-21:19Z, "
     "healthy, 120/120) ran on the repo /workspaces/.../.venv with repo models (launch 3, drive.json). delta:B "
     "then failed health 7 times on the repo .venv (launch 3) and 3 times on the repo .venv with local model "
     "copies (launch 4, drive2.log, 21:22-21:25Z): `Error importing huggingface_hub.hf_api: [Errno 12] ... "
     "site-packages/huggingface_hub/utils` -> encode_splade OSError 12, CE and embedding model not loaded. "
     "From launch 5 (drive3.log, 21:26Z) delta:B, base:A and delta:A run on the local venv mirror "
     "/home/vscode/work/venv_local (rsync of the same .venv, identical package versions; only "
     "onnx/backend/test/data, torch/testing/_internal and sympy/*/tests excluded), PYTHONPATH blank, with "
     "SFU_SPLADE_MODEL_PATH / SFU_CE_MODEL_PATH on byte-identical local copies (sha256 in model_files). "
     "The CE ONNX int8 dir and the embedding model stay on 9p (hardcoded paths)."},
    {"utc": "2026-09-30T22:25Z", "what": "HOST CONDITION: another session ran swapoff/swapon to pull its ~15 GB "
     "swapped S0-2 process back into RAM (swap 16 GB, 15 GB used at 22:20Z); base:A was running at the time "
     "(its file reads re-fault; timings invalid anyway). Per that session, the 19:20Z ENOMEM coincided with a "
     "full 16 GB swap partition."}]
BLANK = ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR", "SFU_DELTA_ROOT", "SFU_SEISMIC_SHARD_MANIFEST",
         "SFU_SEARCH_SPECULATIVE_RERANK", "SFU_THINCLIENT_ORDINALS")
SIGNATURES = ("Cannot allocate memory", "CrossEncoder unavailable", "Failed to load embedding model",
              "falling back to BM25F", "SPLADE encoder failed", "SEISMIC SPLADE leg failed",
              "Reranker failed", "Traceback", "delta layer off", "SFU_SEISMIC_SHARD_MANIFEST is set",
              "MemoryError", "WI-10")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_utc(s: str) -> float:
    return float(calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")))


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def mem_available_gb() -> float:
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 ** 2
    return 0.0


def host_state() -> dict:
    out = {"utc": utc(), "loadavg": list(os.getloadavg())}
    mem = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":", 1)
        if k in ("MemTotal", "MemAvailable", "Cached", "SwapFree", "SwapTotal"):
            mem[k] = round(int(v.split()[0]) / 1024 ** 2, 2)
    out["mem_gb"] = mem
    try:
        ps = subprocess.run(["ps", "-eo", "pid,pcpu,rss,args", "--sort=-pcpu"], capture_output=True,
                            text=True, timeout=10).stdout.splitlines()[1:9]
        out["top_procs"] = [p[:160] for p in ps]
    except Exception as exc:
        out["top_procs"] = [f"unavailable: {exc!r}"]
    return out


def qtiles(xs: list[float]) -> dict | None:
    if not xs:
        return None
    s = sorted(xs)

    def q(p):
        i = max(0, min(len(s) - 1, int(round(p / 100.0 * len(s) + 0.5)) - 1))
        return s[i]
    return {"n": len(s), "min": s[0], "p5": q(5), "p25": q(25), "p50": statistics.median(s),
            "p75": q(75), "p95": q(95), "max": s[-1], "mean": round(statistics.fmean(s), 4)}


def load_ready() -> dict:
    """Normalise READY.json (schema of the M2 fixture, commit 885c29e7) into
    {root, env_on, env_off, updated_ids, sample, generations, commit}."""
    raw = json.loads(READY.read_text())
    ids = json.loads(Path(raw["doc_ids_path"].split(" ")[0]).read_text())["ids"]
    ts = json.loads(Path(raw["title_sample_path"].split(" ")[0]).read_text())
    sample = list(zip(ts["order"], ts["titles"]))
    gens = [g[0] for g in (raw.get("verify") or {}).get("gens") or []]
    return {"root": raw["root"], "env_on": {k: str(v) for k, v in raw["env_gate_on"].items()},
            "env_off": {k: str(v) for k, v in raw["env_gate_off"].items()}, "updated_ids": ids,
            "sample": sample, "commit": raw.get("fixture_commit"), "generations": gens,
            "raw_keys": sorted(raw)}


class _WarnCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record):
        try:
            self.records.append(f"{record.name}: {record.getMessage()}"[:400])
        except Exception:
            pass


def child(args) -> int:
    """One arm: health, Part B (120 topics), Part A (title sample prefix)."""
    t_start = time.time()
    deadline = parse_utc(args.deadline)
    out = Path(args.out)
    sys.path.insert(0, args.src)
    ready = load_ready()
    updated = set(ready["updated_ids"])
    cap = _WarnCapture()
    logging.getLogger().addHandler(cap)
    health: dict = {"ok": True, "problems": []}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    rec = {"arm": args.arm, "pid": os.getpid(), "src": args.src, "host_start": host_state(),
           "env": {k: os.environ.get(k) for k in sorted(os.environ) if k.startswith("SFU_") and
                   not any(s in k for s in ("KEY", "TOKEN", "AUTH", "SECRET", "PASS"))},
           "health": health, "timings_valid": False,
           "timings_note": "host shared with B7 (cores 0-7) and S0-2 (~19 GB, cores 8-15); no latency lock"}

    def flush(partial=True):
        rec["partial"] = partial
        rec["wall_s"] = round(time.time() - t_start, 1)
        out.write_text(json.dumps(rec, default=str) + "\n")

    if os.environ.get("SFU_SEISMIC_STAGE_DIR") or os.environ.get("SFU_META_STAGE_DIR"):
        bad("a stage dir is set in the child env; refusing to load")
        flush(False)
        return 3
    try:
        import onnxruntime
        health["onnxruntime"] = onnxruntime.__version__
    except Exception as exc:
        bad(f"onnxruntime import failed: {exc!r}")
    import lib.tools as tools
    import lib.thinclient.retriever as rmod
    import lib.thinclient.delta_layer as dmod
    from lib.opensearch_retriever import encode_splade
    from lib.reranker import _get_cross_encoder
    rec["code_under_test"] = {m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                              for m in (tools, rmod, dmod)}
    retriever = tools._get_thinclient_retriever()
    if retriever is None:
        bad("search backend is not thinclient")
        flush(False)
        return 3
    retriever._fetch_remote_abstracts = lambda ids: {}
    t0 = time.perf_counter()
    retriever._load()
    rec["load_s"] = round(time.perf_counter() - t0, 2)
    try:
        qv = encode_splade("warm up query for sparse encoder", retriever.splade_model_path)
        health["splade_terms"] = len(qv or {})
        if not qv:
            bad("encode_splade returned empty")
    except Exception as exc:
        bad(f"encode_splade raised {exc!r}")
    try:
        ce = _get_cross_encoder()
        health["cross_encoder"] = type(ce).__name__ if ce is not None else None
        if ce is None:
            bad("cross-encoder not loaded")
    except Exception as exc:
        bad(f"cross-encoder load raised {exc!r}")
    try:
        from lib.embedding import _load_model
        em = _load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
        health["embedding_model"] = type(em).__name__ if em is not None else None
        if em is None:
            bad("embedding model not loaded")
    except Exception as exc:
        bad(f"embedding model load raised {exc!r}")
    try:
        backend = retriever._seismic_backend()
    except Exception as exc:
        backend = None
        bad(f"seismic backend load raised {exc!r}")
    delta = retriever._delta
    n_gen = 0 if args.arm == "base" else len(ready["generations"] or [1])
    if backend is not None:
        health["backend_class"] = type(backend).__name__
        health["n_shards"] = len(backend.shards)
        if type(backend).__name__ != "ParallelSeismicBackend":
            bad(f"backend {type(backend).__name__} != ParallelSeismicBackend")
        if len(backend.shards) != N_BASE_SHARDS + n_gen or any(s is None for s in backend.shards):
            bad(f"shards {len(backend.shards)} != {N_BASE_SHARDS + n_gen} or a shard is None")
    if args.arm == "base":
        if delta is not None:
            bad("delta layer loaded in the gate-off arm")
    elif delta is None:
        bad("delta layer not loaded")
    else:
        health["delta_generations"] = [g["gen"] for g in delta.generations]
        health["delta_stamp"] = delta.stamp
        health["delta_manifest"] = delta.shard_manifest_path()
        health["delta_superseded"] = len(delta.superseded)
        health["delta_deleted"] = len(delta.deleted)
        health["delta_buffer_size"] = delta.buffer_size()
        health["delta_sections_loaded"] = sorted(n for n in retriever._sections if n.startswith("delta_"))
        health["livedocs"] = delta.livedocs is not None
        health["shard_filter_attached"] = delta._shard_filter_attached
        if len(delta.generations) != n_gen:
            bad(f"delta generations {len(delta.generations)} != {n_gen}")
        if delta.livedocs is None:
            bad("livedocs not loaded")
        if not health["delta_sections_loaded"]:
            bad("no delta tantivy section loaded")
        if getattr(retriever, "_seismic_manifest", None) != delta.shard_manifest_path():
            bad("served manifest is not the delta composed manifest")
    health["sections"] = sorted(retriever._sections)
    health["warnings_at_load"] = list(cap.records)
    if any(any(s in w for s in SIGNATURES) for w in cap.records):
        bad("failure signature in warnings during load")
    if not health["ok"]:
        rec["host_end"] = host_state()
        flush(False)
        print("HEALTH FAIL", json.dumps(health["problems"]), file=sys.stderr, flush=True)
        return 3

    traverse = {"n": 0}
    orig_search = backend.search_encoded

    def srch_w(q, top_k, **kw):
        traverse["n"] += 1
        return orig_search(q, top_k, **kw)
    backend.search_encoded = srch_w

    n_warn0 = len(cap.records)
    topics = [q["query"] for q in json.loads(TOPICS.read_text())]
    rows_b = []
    rec["part_b"] = rows_b
    if "B" in args.parts:
        for i, q in enumerate(topics):
            if time.time() > deadline:
                rec["part_b_stopped_at_deadline"] = i
                break
            n0 = traverse["n"]
            t = time.perf_counter()
            det = retriever.search_rrf_detailed(q, top_k=TOP_K)
            t1 = time.perf_counter()
            fused = [{k: v for k, v in d.items() if k != "rrf_legs"} for d in det["results"]]
            final = tools._maybe_rerank(copy.deepcopy(fused), q, LIMIT) if fused else []
            t2 = time.perf_counter()
            rows_b.append({"i": i, "query": q, "fused_ids": [d.get("openalex_id") for d in fused],
                           "fused_scores": [d.get("score") for d in fused],
                           "bm25f_ids": det["legs"].get("bm25f", []), "splade_ids": det["legs"].get("splade", []),
                           "final_ids": [d.get("openalex_id") for d in final],
                           "traversed": traverse["n"] > n0,
                           "rrf_ms": round((t1 - t) * 1000, 1), "rerank_ms": round((t2 - t1) * 1000, 1)})
            print(f"[{args.arm} B {i+1}/{len(topics)}] rrf={rows_b[-1]['rrf_ms']:.0f}ms", flush=True)
            if (i + 1) % 10 == 0:
                flush()
    rec["part_b_untraversed"] = sum(1 for r in rows_b if not r["traversed"])
    if rec["part_b_untraversed"]:
        bad(f"{rec['part_b_untraversed']} Part B queries never reached the SEISMIC traverse")
    flush()

    captured: dict = {}
    if delta is not None:
        orig_filter = delta.filter_hits

        def filter_w(hits):
            res = orig_filter(hits)
            kept, j = [], 0
            for h in hits:
                if j < len(res) and h[0] == res[j][0] and h[1] == res[j][1]:
                    kept.append(h)
                    j += 1
            captured["pre"] = list(hits)
            captured["post"] = kept
            captured["aligned"] = j == len(res)
            return res
        delta.filter_hits = filter_w

    rows_a = []
    rec["part_a"] = rows_a
    sample = ready["sample"][:args.n_a]
    if "A" in args.parts:
        for i, (did, title) in enumerate(sample):
            if time.time() > deadline:
                rec["part_a_stopped_at_deadline"] = i
                break
            captured.clear()
            t = time.perf_counter()
            try:
                hits = retriever._bm25f_leg(title, A_TOPK, None)
            except Exception as exc:
                rows_a.append({"i": i, "id": did, "rank": None, "score": None, "n": 0, "ms": None,
                               "n_updated_in_list": 0, "error": f"{type(exc).__name__}: {exc}"[:300]})
                print(f"[{args.arm} A {i+1}/{len(sample)}] ERROR {type(exc).__name__}", flush=True)
                continue
            ms = (time.perf_counter() - t) * 1000
            ids = [h[0] for h in hits]
            rank = ids.index(did) + 1 if did in ids else None
            row = {"i": i, "id": did, "rank": rank, "score": hits[rank - 1][1] if rank else None,
                   "n": len(hits), "ms": round(ms, 1),
                   "n_updated_in_list": sum(1 for x in ids if x in updated)}
            if delta is not None and "pre" in captured:
                pre, post = captured["pre"], captured["post"]
                row["aligned"] = captured["aligned"]
                row["pre_base_score"] = max([s for d, s, o in pre if d == did and o is None], default=None)
                row["pre_delta_score"] = max([s for d, s, o in pre if d == did and o is not None], default=None)
                row["post_base_copy"] = any(d == did and o is None for d, s, o in post)
                row["post_delta_copy"] = any(d == did and o is not None for d, s, o in post)
                row["leak_any_updated_base_copy"] = sum(1 for d, s, o in post if o is None and d in updated)
                seen: dict = {}
                for d, s, o in post:
                    seen.setdefault(d, set()).add(o is None)
                row["both_copies_ids"] = sum(1 for v in seen.values() if len(v) == 2)
                row["origin_at_rank"] = ([o for d, s, o in post if d == did][0]
                                         if did in seen else None)
            rows_a.append(row)
            print(f"[{args.arm} A {i+1}/{len(sample)}] rank={rank} {ms:.0f}ms", flush=True)
            if (i + 1) % 25 == 0:
                flush()
    warn = cap.records[n_warn0:]
    health["n_warnings_during_run"] = len(warn)
    health["warnings_during_run"] = warn[:50]
    if any(any(s in w for s in SIGNATURES) for w in warn):
        bad("failure signature in warnings during the run")
    rec["host_end"] = host_state()
    rec["maxrss_gb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 2, 2)
    flush(False)
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


def arm_env(arm: str, ready: dict) -> dict:
    env = dict(os.environ)
    env.update(ready["env_off"] if arm == "base" else ready["env_on"])
    env.update({k: "" for k in BLANK})
    env["SFU_SEISMIC_FEDERATION"] = "parallel"
    if arm == "base":
        env["SFU_SEISMIC_SHARD_MANIFEST"] = str(BASE_MANIFEST)
        if ready["env_off"].get("SFU_THINCLIENT_ORDINALS"):
            env["SFU_THINCLIENT_ORDINALS"] = ready["env_off"]["SFU_THINCLIENT_ORDINALS"]
    else:
        env["SFU_DELTA_ROOT"] = ready["root"]
        env["SFU_THINCLIENT_ORDINALS"] = ready["env_on"].get("SFU_THINCLIENT_ORDINALS", "")
    return env


def scan_log(path: Path) -> dict:
    text = path.read_text(errors="replace") if path.exists() else ""
    return {"path": str(path), "bytes": len(text), "signature_counts": {s: text.count(s) for s in SIGNATURES}}


def drive(args) -> int:
    ready = load_ready()
    commit = git_commit()
    snap = snapshot_src(commit)
    local_harness = snap / "scripts" / "experiments" / Path(__file__).name
    local_harness.parent.mkdir(parents=True, exist_ok=True)
    local_harness.write_bytes(Path(__file__).read_bytes())
    runs = WORK / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    deadline = parse_utc(args.deadline)
    drive_rec = {"commit": commit, "snapshot": str(snap), "start": utc(), "arms": {},
                 "python": sys.executable, "sys_prefix": sys.prefix, "model_files": model_checksums()}
    drive_path = runs / f"drive_{time.strftime('%H%M%S', time.gmtime())}.json"
    drive_rec["cpus"] = args.cpus
    for step in args.schedule.split(","):
        arm, part = step.split(":")
        while mem_available_gb() < args.min_mem_gb and time.time() < deadline:
            print(f"{utc()} MemAvailable {mem_available_gb():.1f} GB < {args.min_mem_gb}; waiting", flush=True)
            time.sleep(60)
        if time.time() >= deadline:
            break
        cpus = args.cpus
        if cpus == "auto":
            free = subprocess.call(["flock", "-n", "/tmp/sfu_latency_measure.lock", "true"]) == 0
            cpus = "0-7" if free else "8-15"
        env = arm_env(arm, ready)
        log = runs / f"{arm}_{part}.log"
        arm = f"{arm}:{part}"
        cmd = ["nice", "-n", "10", "taskset", "-c", cpus, sys.executable, str(local_harness),
               "child", "--arm", arm.split(":")[0], "--src", str(snap / "src"),
               "--out", str(runs / f"{arm.replace(':', '_')}.json"),
               "--deadline", args.deadline, "--n-a", str(args.n_a), "--parts", part]
        t0 = time.time()
        attempts = []
        for attempt in range(args.retries + 1):
            print(f"{utc()} start arm {arm} attempt {attempt + 1}", flush=True)
            with open(log, "w") as fh:
                rc = subprocess.call(cmd, env=env, cwd=str(snap), stdout=fh, stderr=subprocess.STDOUT)
            text = log.read_text(errors="replace")
            early = rc != 0 and "Cannot allocate memory" in text and "[" + arm.split(":")[0] + " " not in text
            if early:
                keep = runs / f"{arm.replace(':', '_')}.attempt{attempt + 1}.log"
                keep.write_text(text)
                attempts.append({"utc": utc(), "rc": rc, "log": str(keep),
                                 "enomem_line": [ln for ln in text.splitlines() if "Cannot allocate" in ln][-1:]})
            if not early or time.time() >= deadline:
                break
            print(f"{utc()} arm {arm}: ENOMEM before any query (O12); retry in 20 s", flush=True)
            time.sleep(20)
        drive_rec["arms"][arm] = {"rc": rc, "cpus": cpus, "o12_failed_start_attempts": attempts, "host_after": host_state(), "wall_s": round(time.time() - t0, 1), "log": str(log),
                                  "env": {k: env.get(k) for k in sorted(env) if k.startswith("SFU_") and
                                          not any(s in k for s in ("KEY", "TOKEN", "AUTH", "SECRET", "PASS"))}}
        print(f"{utc()} arm {arm} rc={rc}", flush=True)
        drive_path.write_text(json.dumps(drive_rec, indent=1) + "\n")
    drive_rec["end"] = utc()
    drive_path.write_text(json.dumps(drive_rec, indent=1) + "\n")
    return 0


def model_checksums() -> dict:
    """sha256 of the model files the serving env points at (repo or local copy)."""
    out = {}
    for key, default in (("SFU_SPLADE_MODEL_PATH", REPO / "models" / "splade_onnx_fused"),
                         ("SFU_CE_MODEL_PATH", REPO / "models" / "sfu-cross-encoder-v1")):
        d = Path(os.environ.get(key) or default)
        for f in sorted(d.glob("*.onnx")) + sorted(d.glob("*.safetensors")):
            for _ in range(20):
                try:
                    out[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
                    break
                except OSError as exc:
                    out[str(f)] = f"unreadable: {exc!r}"
                    time.sleep(1)
    return out


def tokenizer_record() -> dict:
    """Which tokenizer dir each process resolved (inferred from
    opensearch_retriever._resolve_tokenizer_dir: model dir first, then
    _TOKENIZER_FALLBACK_DIRS starting with models/sfu-academic-embed-v1; the
    INFO log line naming it is not captured by the child logs) and whether
    the two candidate files are byte-identical."""
    def sha(p):
        for _ in range(20):
            try:
                return hashlib.sha256(Path(p).read_bytes()).hexdigest()
            except OSError:
                time.sleep(1)
        return "unreadable"
    repo_dir = REPO / "models" / "sfu-academic-embed-v1"
    local_dir = Path("/home/vscode/work/models_local/splade_onnx_fused")
    files = {}
    for name in ("tokenizer.json", "tokenizer_config.json"):
        files[name] = {"repo_fallback": sha(repo_dir / name), "local_model_dir": sha(local_dir / name)}
        files[name]["identical"] = files[name]["repo_fallback"] == files[name]["local_model_dir"]
    return {"per_process": {
        "base_B": f"{repo_dir} (repo models/splade_onnx_fused has no tokenizer files; 9p)",
        "delta_B": f"{repo_dir} (started 21:26Z, before the local model dir got tokenizer files at 21:51:15Z; 9p)",
        "base_A": f"{repo_dir} (healthy attempt started 21:47:34Z, before 21:51:15Z; 9p)",
        "delta_A": f"{local_dir} (started after 21:51:15Z; local copy)"},
        "basis": "inferred from the resolution order and file mtimes; the log line is not captured",
        "sha256": files}


def top10_displaced(base_lists, delta_lists, updated) -> tuple[int, list]:
    tot, per = 0, []
    for b, d in zip(base_lists, delta_lists):
        dset = set(d[:LIMIT])
        disp = [x for x in b[:LIMIT] if x not in updated and x not in dset]
        tot += len(disp)
        per.append(disp)
    return tot, per


def summarize(args) -> int:
    ready = load_ready()
    updated = set(ready["updated_ids"])
    runs = WORK / "runs"
    drvs = [json.loads(p.read_text()) for p in sorted(runs.glob("drive*.json"))]
    drv = {"commit": drvs[-1]["commit"], "snapshot": drvs[-1]["snapshot"], "arms": {}, "launches": drvs}
    for x in drvs:
        for k, v in x["arms"].items():
            if True:
                drv["arms"][k] = {**v, "launch_start": x.get("start"), "python": x.get("python"),
                                  "model_files": x.get("model_files")}
    def ld(name):
        p = runs / f"{name}.json"
        return json.loads(p.read_text()) if p.exists() else {"health": {"ok": None, "problems": ["not run"]},
                                                             "part_a": [], "part_b": []}
    procs = {n: ld(n) for n in ("base_B", "delta_B", "base_A", "delta_A")}
    degraded = {n: r["health"]["ok"] is False for n, r in procs.items()}
    bB, dB, bA, dA = procs["base_B"], procs["delta_B"], procs["base_A"], procs["delta_A"]
    res = {"item": "M3 BM25F score drift (T1)", "date": "2026-09-30",
           "plan_row": {"metric": "for corpus (a): rank of each updated doc for its title-as-query with the update "
                                  "served from a delta section vs from the base; and the number of NON-updated base "
                                  "docs displaced out of the fused top-10 across the 120 topics",
                        "bar": "median rank change 0; displaced base docs <= 5% of top-10 slots"},
           "harness": "scripts/experiments/eval_delta_ingest_m3_bm25f_drift.py",
           "code_commit": drv["commit"], "code_snapshot": drv["snapshot"],
           "fixture": {"ready_json": str(READY), "commit": ready["commit"], "root": ready["root"],
                       "n_updated_ids": len(updated), "sample_size": len(ready["sample"]),
                       "ready_keys": ready["raw_keys"]},
           "arms_env": {k: v["env"] for k, v in drv["arms"].items()},
           "health": {n: r["health"] for n, r in procs.items()}, "degraded": degraded,
           "log_scan": {n: scan_log(runs / f"{n}.log") for n in procs},
           "host": {n: {"start": r.get("host_start"), "end": r.get("host_end"), "maxrss_gb": r.get("maxrss_gb"),
                        "partial": r.get("partial"), "wall_s": r.get("wall_s")} for n, r in procs.items()},
           "o12_events_outside_measured_processes": O12_EVENTS,
           "splade_tokenizer_resolution": tokenizer_record(),
           "timings_valid": False,
           "timings_note": "host shared with the in-place B7 run (latency lock, cores 0-7) and S0-2 (~19 GB, "
                           "cores 8-15); nice 10, taskset 8-15, no lock. Every ms/wall field is NOT a deliverable."}

    ra, rd = bA.get("part_a", []), dA.get("part_a", [])
    n = min(len(ra), len(rd))
    allpairs = list(zip(ra[:n], rd[:n]))
    assert all(x["id"] == y["id"] for x, y in allpairs)
    err_pairs = [(x, y) for x, y in allpairs if x.get("error") or y.get("error")]
    pairs = [(x, y) for x, y in allpairs if not (x.get("error") or y.get("error"))]
    both = [(x, y) for x, y in pairs if x["rank"] and y["rank"]]
    diffs = [y["rank"] - x["rank"] for x, y in both]
    med = statistics.median(diffs) if diffs else None
    ratios = [y["pre_delta_score"] / y["pre_base_score"] for x, y in pairs
              if y.get("pre_delta_score") and y.get("pre_base_score")]
    xchk = [abs(y["pre_base_score"] - x["score"]) for x, y in pairs
            if y.get("pre_base_score") is not None and x.get("score") is not None]
    part_a = {
        "definition": f"BM25F leg only (_bm25f_leg(title, {A_TOPK}, None)); sample = first {N_A} of READY.json "
                      "title sample in its order; rank 1-based in top-100, >100 absent; statistic median of "
                      "(rank_delta - rank_base) over docs present in both arms",
        "n_planned": min(N_A, len(ready["sample"])), "n_common_prefix": n, "n_compared": len(pairs),
        "n_query_errors": len(err_pairs),
        "query_errors": [{"i": x["i"], "id": x["id"], "base": x.get("error"), "delta": y.get("error")}
                         for x, y in err_pairs],
        "partial": n < min(N_A, len(ready["sample"])),
        "n_present_both": len(both),
        "n_absent_base_only": sum(1 for x, y in pairs if not x["rank"] and y["rank"]),
        "n_absent_delta_only": sum(1 for x, y in pairs if x["rank"] and not y["rank"]),
        "n_absent_both": sum(1 for x, y in pairs if not x["rank"] and not y["rank"]),
        "base_own_recall_at100": round(sum(1 for x, _ in pairs if x["rank"]) / len(pairs), 4) if pairs else None,
        "delta_own_recall_at100": round(sum(1 for _, y in pairs if y["rank"]) / len(pairs), 4) if pairs else None,
        "base_rank1_share": round(sum(1 for x, _ in pairs if x["rank"] == 1) / len(pairs), 4) if pairs else None,
        "delta_rank1_share": round(sum(1 for _, y in pairs if y["rank"] == 1) / len(pairs), 4) if pairs else None,
        "rank_change_quantiles": qtiles(diffs),
        "median_rank_change": med,
        "share_improved": round(sum(1 for v in diffs if v < 0) / len(diffs), 4) if diffs else None,
        "share_same": round(sum(1 for v in diffs if v == 0) / len(diffs), 4) if diffs else None,
        "share_worse": round(sum(1 for v in diffs if v > 0) / len(diffs), 4) if diffs else None,
        "rank_base_quantiles": qtiles([x["rank"] for x, _ in both]),
        "rank_delta_quantiles": qtiles([y["rank"] for _, y in both]),
        "score_ratio_delta_over_base_copy": qtiles(ratios),
        "share_ratio_gt1": round(sum(1 for r in ratios if r > 1) / len(ratios), 4) if ratios else None,
        "n_delta_copy_scored": sum(1 for _, y in pairs if y.get("pre_delta_score") is not None),
        "n_base_copy_scored_premask": sum(1 for _, y in pairs if y.get("pre_base_score") is not None),
        "base_score_crossprocess_absdiff_max": max(xchk) if xchk else None,
        "mask_leak_own_doc_base_copy_postmask": sum(1 for _, y in pairs if y.get("post_base_copy")),
        "mask_leak_any_updated_base_copy_postmask": sum(y.get("leak_any_updated_base_copy") or 0 for _, y in pairs),
        "both_copies_same_list": sum(y.get("both_copies_ids") or 0 for _, y in pairs),
        "filter_alignment_failures": sum(1 for _, y in pairs if y.get("aligned") is False),
        "own_doc_served_origin_counts": {str(k): sum(1 for _, y in pairs if y.get("origin_at_rank") == k)
                                         for k in sorted({y.get("origin_at_rank") for _, y in pairs}, key=str)},
        "mean_updated_ids_in_list": {"base": round(statistics.fmean([x["n_updated_in_list"] for x, _ in pairs]), 3)
                                     if pairs else None,
                                     "delta": round(statistics.fmean([y["n_updated_in_list"] for _, y in pairs]), 3)
                                     if pairs else None},
        "ms_p50": {"base": qtiles([x["ms"] for x, _ in pairs if x["ms"] is not None]),
                   "delta": qtiles([y["ms"] for _, y in pairs if y["ms"] is not None]),
                   "timings_valid": False},
    }
    part_a["verdict"] = ("DEGRADED" if degraded["base_A"] or degraded["delta_A"] else
                         "NOT RUN" if not diffs else ("PASS" if med == 0 else "FAIL"))
    if part_a["partial"] and part_a["verdict"] in ("PASS", "FAIL"):
        part_a["verdict"] += " (PARTIAL)"
    part_a["worst_20"] = sorted(({"id": x["id"], "rank_base": x["rank"], "rank_delta": y["rank"],
                                  "score_base": x["score"], "score_delta": y["score"],
                                  "pre_base_score": y.get("pre_base_score")} for x, y in both),
                                key=lambda r: -(r["rank_delta"] - r["rank_base"]))[:20]
    res["part_a"] = part_a

    bb, bd = bB.get("part_b", []), dB.get("part_b", [])
    m = min(len(bb), len(bd))
    assert all(x["query"] == y["query"] for x, y in zip(bb[:m], bd[:m]))
    fb, fd = [r["fused_ids"] for r in bb[:m]], [r["fused_ids"] for r in bd[:m]]
    disp, per = top10_displaced(fb, fd, updated)
    disp_bm, _ = top10_displaced([r["bm25f_ids"] for r in bb[:m]], [r["bm25f_ids"] for r in bd[:m]], updated)
    disp_sp, _ = top10_displaced([r["splade_ids"] for r in bb[:m]], [r["splade_ids"] for r in bd[:m]], updated)
    disp_fin, _ = top10_displaced([r["final_ids"] for r in bb[:m]], [r["final_ids"] for r in bd[:m]], updated)
    entered = sum(len([x for x in y[:LIMIT] if x in updated and x not in set(xb[:LIMIT])]) for xb, y in zip(fb, fd))
    part_b = {
        "definition": "search_rrf_detailed(q, top_k=50) == search_rrf fused list; 120 topics of "
                      "data/sfu_eval_queries.json 'query'; displaced = BASE fused top-10 doc not in the 50,000 "
                      "updated ids and absent from DELTA fused top-10; bar <= 60 of 1,200 slots",
        "n_topics": m, "slots": m * LIMIT, "partial": m < 120,
        "displaced_fused_top10": disp,
        "displaced_share": round(disp / (m * LIMIT), 4) if m else None,
        "topics_with_displacement": sum(1 for p in per if p),
        "displaced_per_topic_max": max((len(p) for p in per), default=0),
        "updated_entered_fused_top10": entered,
        "updated_in_fused_top10": {"base": sum(1 for r in fb for x in r[:LIMIT] if x in updated),
                                   "delta": sum(1 for r in fd for x in r[:LIMIT] if x in updated)},
        "fused_top10_idlist_identical": sum(1 for x, y in zip(fb, fd) if x[:LIMIT] == y[:LIMIT]),
        "fused_top50_idlist_identical": sum(1 for x, y in zip(fb, fd) if x == y),
        "displaced_bm25f_leg_top10": disp_bm,
        "displaced_splade_leg_top10": disp_sp,
        "bm25f_leg_top10_identical": sum(1 for x, y in zip(bb[:m], bd[:m]) if x["bm25f_ids"][:LIMIT] == y["bm25f_ids"][:LIMIT]),
        "splade_leg_top10_identical": sum(1 for x, y in zip(bb[:m], bd[:m]) if x["splade_ids"][:LIMIT] == y["splade_ids"][:LIMIT]),
        "updated_in_bm25f_leg_top10": {"base": sum(1 for r in bb[:m] for x in r["bm25f_ids"][:LIMIT] if x in updated),
                                       "delta": sum(1 for r in bd[:m] for x in r["bm25f_ids"][:LIMIT] if x in updated)},
        "updated_in_splade_leg_top10": {"base": sum(1 for r in bb[:m] for x in r["splade_ids"][:LIMIT] if x in updated),
                                        "delta": sum(1 for r in bd[:m] for x in r["splade_ids"][:LIMIT] if x in updated)},
        "final_top10_changed_topics": sum(1 for x, y in zip(bb[:m], bd[:m]) if x["final_ids"] != y["final_ids"]),
        "displaced_final_top10": disp_fin,
        "rrf_ms_p50": {"base": qtiles([r["rrf_ms"] for r in bb[:m]]), "delta": qtiles([r["rrf_ms"] for r in bd[:m]]),
                       "timings_valid": False},
        "displaced_examples": [{"query": bb[i]["query"], "displaced": p} for i, p in enumerate(per) if p][:20],
    }
    part_b["verdict"] = ("DEGRADED" if degraded["base_B"] or degraded["delta_B"] else "NOT RUN" if not m else
                         ("PASS" if disp <= BAR_DISPLACED else "FAIL"))
    if part_b["partial"] and part_b["verdict"] in ("PASS", "FAIL"):
        part_b["verdict"] += " (PARTIAL)"
    res["part_b"] = part_b
    res["verdict"] = {"median_rank_change_0": part_a["verdict"], "displaced_le_5pct": part_b["verdict"],
                      "M3": ("PASS" if part_a["verdict"] == part_b["verdict"] == "PASS" else
                             "FAIL" if "FAIL" in (part_a["verdict"] + part_b["verdict"]) else
                             f"{part_a['verdict']} / {part_b['verdict']}")}
    res["drive"] = drv
    OUT.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("verdict",)}, indent=1))
    print(json.dumps({k: v for k, v in part_a.items() if k != "worst_20"}, indent=1, default=str))
    print(json.dumps({k: v for k, v in part_b.items() if k != "displaced_examples"}, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("child")
    c.add_argument("--arm", choices=("base", "delta"), required=True)
    c.add_argument("--src", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--deadline", required=True)
    c.add_argument("--n-a", type=int, default=N_A)
    c.add_argument("--parts", default="BA")
    dv = sub.add_parser("drive")
    dv.add_argument("--deadline", default="2026-09-30T23:25:00Z")
    dv.add_argument("--schedule", default="base:B,delta:B,base:A,delta:A")
    dv.add_argument("--cpus", default="8-15")
    dv.add_argument("--min-mem-gb", type=float, default=18.0)
    dv.add_argument("--retries", type=int, default=6)
    dv.add_argument("--n-a", type=int, default=N_A)
    sub.add_parser("summarize")
    args = ap.parse_args()
    return {"child": child, "drive": drive, "summarize": summarize}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
