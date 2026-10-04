"""M6 — delta-ingest throughput per profile (docs/delta_ingest/03_SPIKE_PLAN.md).

M6 is recorded, no bar: docs/s adapter -> buffer, encode docs/s, and the
generation build wall time + peak RSS, for profiles `laptop` (CPU only,
run with CUDA_VISIBLE_DEVICES="") and `desktop_gpu`, on a real OpenAlex
snapshot partition.

Each stage runs as its own process (so profile `nice`, CUDA visibility and
peak-RSS accounting are per stage) and writes one JSON under --work:

    ingest   adapter (OpenAlexSnapshotAdapter over a local partition file,
             slice filter = min_year + normalize_openalex_work) -> classify ->
             content/encode hash -> ledger stage -> tantivy buffer upsert+commit,
             in profile.ingest_batch transactions. NO encoding. Rate throttle
             and the buffer-cap mid-ingest freeze are disabled so the number is
             the unthrottled pipeline ceiling (the throttle is a policy dial).
    encode   profile encoder (make_encoder) over the first N buffered records;
             encoder construction + first batch timed separately (warm-up);
             GPU memory polled via nvidia-smi. --write-back stores vectors in
             the ledger (untimed) so `build` can include a SEISMIC shard.
    seed     copy the first N vector-bearing records into a fresh root (the
             laptop generation is flush_docs=20k docs).
    build    freeze_buffer: meta + tantivy sections + SEISMIC stock build ->
             c1a f16 mmap -> dotvbyte v2 + publish. Must run under
             `flock /tmp/sfu_seismic_build.lock`.
    assemble merge the stage JSONs into the results file.

Usage (see the M6 record in data/eval_results/delta_ingest_M6_20260929.json):
    CUDA_VISIBLE_DEVICES="" .venv/bin/python3 scripts/experiments/eval_delta_ingest_m6_throughput.py \\
        ingest --profile laptop --corpus <part.gz> --root <root> --work <work>
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from spike.delta_ingest.profiles import PROFILES, apply_nice  # noqa: E402


def vm_hwm_gb() -> float:
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024 ** 2
    return 0.0


def children_maxrss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024 ** 2


def host_info() -> dict:
    info = {"hostname": platform.node(), "cpu_count": os.cpu_count(), "loadavg": os.getloadavg(),
            "python": sys.version.split()[0], "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES")}
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    info["cpu_model"] = line.split(":", 1)[1].strip()
                    break
        with open("/proc/meminfo") as fh:
            info["mem_total_gb"] = round(int(fh.readline().split()[1]) / 1024 ** 2, 1)
    except OSError:
        pass
    return info


def gpu_used_mib() -> list[int]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return [int(x) for x in out.split()]
    except Exception:
        return []


def gpu_compute_apps() -> list[dict]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    apps = []
    for line in out.strip().splitlines():
        pid = line.split(",")[0].strip()
        cmd = ""
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")[:200]
        except OSError:
            pass
        apps.append({"pid": int(pid), "self": int(pid) == os.getpid(), "cmdline": cmd})
    return apps


class GpuPoller:
    def __init__(self, period: float = 0.25):
        self.period = period
        self.baseline = gpu_used_mib()
        self.peak = list(self.baseline)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            cur = gpu_used_mib()
            if cur:
                self.peak = [max(a, b) for a, b in zip(self.peak or cur, cur)]
            self._stop.wait(self.period)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join()

    def as_dict(self) -> dict:
        return {"baseline_mib": self.baseline, "peak_mib": self.peak,
                "peak_minus_baseline_mib": [p - b for p, b in zip(self.peak, self.baseline)],
                "method": "nvidia-smi memory.used polled every 0.25 s (whole GPU; other processes included)"}


class LocalSession:
    """Serves the manifest and the partition from local disk so the real
    OpenAlexSnapshotAdapter code path (gzip.decompress + line parse + slice
    filter) runs unchanged, without the network."""

    def __init__(self, manifest_url: str, part_url: str, part_path: Path):
        self.manifest_url = manifest_url
        self.part_url = part_url
        self.part_path = part_path

    class _R:
        def __init__(self, content: bytes):
            self.content = content
            self.status_code = 200

        def raise_for_status(self):
            return None

    def get(self, url, **kw):
        if url == self.manifest_url:
            return self._R(json.dumps({"entries": [{"url": self.part_url}]}).encode())
        if url == self.part_url:
            return self._R(self.part_path.read_bytes())
        raise FileNotFoundError(url)


def empty_base(root: Path):
    from spike.delta_ingest.base import BaseIndex
    d = root / "empty_base"
    d.mkdir(parents=True, exist_ok=True)
    return BaseIndex(d)


def cmd_ingest(args) -> dict:
    from spike.delta_ingest.adapters import OpenAlexSnapshotAdapter
    from spike.delta_ingest.buffer import BufferWriter
    from spike.delta_ingest.ledger import IngestLedger

    profile = PROFILES[args.profile]
    apply_nice(profile)
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    corpus = Path(args.corpus)
    part_url = "local://openalex/data/jsonl/works/" + corpus.name.replace("works_", "", 1)
    session = LocalSession("local://manifest.json", part_url, corpus)
    adapter = OpenAlexSnapshotAdapter(session, min_year=args.min_year, manifest_url="local://manifest.json",
                                      max_parts=1)
    ledger = IngestLedger(root / "ledger.sqlite")
    base = empty_base(root)
    writer = BufferWriter(root)
    state = ledger.source_state(adapter.name)
    t = {"adapter": 0.0, "classify_hash": 0.0, "ledger_stage": 0.0, "tantivy_upsert": 0.0,
         "tantivy_commit": 0.0, "save_state": 0.0}
    counts = {"seen": 0, "new": 0, "updated": 0, "unchanged": 0, "batches": 0}
    batch: list = []

    def flush():
        if not batch:
            return
        t0 = time.perf_counter()
        in_base = base.contains(r.id for r in batch)
        cls = ledger.classify(batch, in_base)
        todo = cls["new"] + cls["updated"]
        for r in todo:
            r.content_hash()
            r.encode_hash()
        t1 = time.perf_counter()
        ledger.stage(todo, in_base)
        t2 = time.perf_counter()
        writer.upsert(todo)
        t3 = time.perf_counter()
        writer.commit()
        t4 = time.perf_counter()
        ledger.save_source_state(adapter.name, state)
        t5 = time.perf_counter()
        t["classify_hash"] += t1 - t0
        t["ledger_stage"] += t2 - t1
        t["tantivy_upsert"] += t3 - t2
        t["tantivy_commit"] += t4 - t3
        t["save_state"] += t5 - t4
        for k in ("new", "updated", "unchanged"):
            counts[k] += len(cls[k])
        counts["batches"] += 1
        counts["seen"] += len(batch)
        batch.clear()

    wall0 = time.perf_counter()
    first_record_s = None
    it = iter(adapter.iter_records(state))
    while counts["seen"] + len(batch) < args.limit:
        a0 = time.perf_counter()
        try:
            rec = next(it)
        except StopIteration:
            t["adapter"] += time.perf_counter() - a0
            break
        t["adapter"] += time.perf_counter() - a0
        if first_record_s is None:
            first_record_s = time.perf_counter() - wall0
        batch.append(rec)
        if len(batch) >= profile.ingest_batch:
            flush()
    flush()
    wall = time.perf_counter() - wall0
    writer.close()
    ledger.close()
    base.close()
    n = counts["seen"]
    return {
        "stage": "adapter_to_buffer", "profile": profile.as_dict(), "corpus": str(corpus),
        "corpus_bytes": corpus.stat().st_size, "limit": args.limit, "min_year": args.min_year,
        "counts": counts, "wall_s": round(wall, 2), "docs_per_s": round(n / wall, 1) if wall else None,
        "time_to_first_record_s": round(first_record_s or 0.0, 2),
        "stage_seconds": {k: round(v, 2) for k, v in t.items()},
        "adapter_docs_per_s": round(n / t["adapter"], 1) if t["adapter"] else None,
        "buffer_side_docs_per_s": round(n / (wall - t["adapter"]), 1) if wall > t["adapter"] else None,
        "peak_rss_gb": round(vm_hwm_gb(), 3),
        "throttle": f"rate_docs_per_s disabled for the measurement (profile value {profile.rate_docs_per_s})",
        "buffer_cap_freeze": f"disabled (profile buffer_max_docs {profile.buffer_max_docs}); generation build measured separately",
        "base_membership": "empty base root (served meta.sqlite not opened): every record classifies new",
        "host": host_info(),
    }


def cmd_encode(args) -> dict:
    from spike.delta_ingest.encode import make_encoder
    from spike.delta_ingest.ledger import IngestLedger
    from spike.delta_ingest.records import DocRecord

    profile = PROFILES[args.profile]
    apply_nice(profile)
    root = Path(args.root)
    ledger = IngestLedger(root / "ledger.sqlite")
    rows = ledger.db.execute("SELECT rowid, id, record FROM records WHERE generation=0 ORDER BY rowid LIMIT ?",
                             (args.sample,)).fetchall()
    recs = [DocRecord.from_json(r[2]) for r in rows]
    texts = [r.encoder_text() for r in recs]
    import torch
    torch_threads = torch.get_num_threads()
    bs = profile.encode_batch
    out: dict = {"stage": "encode", "profile": profile.as_dict(), "sample_docs": len(recs),
                 "torch_threads": torch_threads, "cuda_available": torch.cuda.is_available(),
                 "mean_encoder_text_chars": round(sum(map(len, texts)) / max(1, len(texts)), 1)}
    use_gpu = torch.cuda.is_available() and profile.encode_device != "cpu"
    poller = GpuPoller() if use_gpu else None
    if poller:
        poller.__enter__()
    try:
        t0 = time.perf_counter()
        enc_fn = make_encoder(profile.encode_backend, bs, profile.encode_device)
        out["encoder_init_s"] = round(time.perf_counter() - t0, 2)
        owner = getattr(enc_fn, "__self__", None)
        out["encoder_class"] = type(owner).__name__ if owner is not None else None
        out["encoder_backend"] = getattr(owner, "backend", None)
        out["encoder_runtime_backend"] = getattr(owner, "runtime_backend", None)
        out["encoder_device"] = getattr(owner, "device", None)
        sess = getattr(owner, "session", None)
        out["ort_providers_in_use"] = sess.get_providers() if sess is not None else None
        out["gpu_compute_apps_at_start"] = gpu_compute_apps() if use_gpu else None
        t0 = time.perf_counter()
        enc_fn(texts[:bs])
        out["warmup_first_batch_s"] = round(time.perf_counter() - t0, 2)
        vecs: list = []
        t0 = time.perf_counter()
        deadline = time.time() + args.max_seconds if args.max_seconds else None
        for i in range(0, len(texts), bs):
            vecs.extend(enc_fn(texts[i:i + bs]))
            if deadline and time.time() > deadline:
                break
        dt = time.perf_counter() - t0
        out["encoded_docs"] = len(vecs)
        out["encode_seconds"] = round(dt, 2)
        out["docs_per_s"] = round(len(vecs) / dt, 1) if dt else None
        out["mean_nnz"] = round(sum(len(v or {}) for v in vecs) / max(1, len(vecs)), 1)
        out["stopped_by_max_seconds"] = len(vecs) < len(texts)
        if use_gpu:
            out["gpu_compute_apps_at_end"] = gpu_compute_apps()
            out["gpu_contended"] = any(not a["self"] for a in
                                       (out["gpu_compute_apps_at_start"] or []) + out["gpu_compute_apps_at_end"])
            out["torch_cuda_max_memory_allocated_mib"] = round(torch.cuda.max_memory_allocated() / 1024 ** 2, 1)
    finally:
        if poller:
            poller.__exit__(None, None, None)
            out["gpu_memory"] = poller.as_dict()
    out["peak_rss_gb"] = round(vm_hwm_gb(), 3)
    if args.write_back:
        t0 = time.perf_counter()
        upd = []
        for (rowid, _id, _), r, v in zip(rows, recs, vecs):
            r.sparse_field = v or None
            upd.append((r.to_json(), rowid))
        with ledger.db:
            ledger.db.executemany("UPDATE records SET record=? WHERE rowid=?", upd)
        out["write_back"] = {"rows": len(upd), "seconds_untimed_in_docs_per_s": round(time.perf_counter() - t0, 2)}
    ledger.close()
    out["host"] = host_info()
    return out


def cmd_seed(args) -> dict:
    from spike.delta_ingest.ledger import IngestLedger
    from spike.delta_ingest.records import DocRecord

    src = IngestLedger(Path(args.src_root) / "ledger.sqlite")
    rows = src.db.execute("SELECT record FROM records WHERE generation=0 ORDER BY rowid LIMIT ?",
                          (args.n,)).fetchall()
    src.close()
    recs = [DocRecord.from_json(r[0]) for r in rows]
    recs = [r for r in recs if r.sparse_field]
    dst_root = Path(args.root)
    dst_root.mkdir(parents=True, exist_ok=True)
    dst = IngestLedger(dst_root / "ledger.sqlite")
    dst.stage(recs, {})
    dst.close()
    return {"stage": "seed", "src_root": args.src_root, "root": str(dst_root), "records_with_vectors": len(recs)}


def cmd_build(args) -> dict:
    from spike.delta_ingest.generation import freeze_buffer
    from spike.delta_ingest.ledger import IngestLedger

    profile = PROFILES[args.profile]
    apply_nice(profile)
    root = Path(args.root)
    ledger = IngestLedger(root / "ledger.sqlite")
    base = empty_base(root)
    n_buf = ledger.buffer_count()
    t0 = time.perf_counter()
    err = None
    res = None
    try:
        res = freeze_buffer(root, ledger, base, profile, seismic=True)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - t0
    out = {"stage": "generation_build", "profile": profile.as_dict(), "buffer_docs": n_buf,
           "wall_s": round(wall, 2), "error": err,
           "peak_rss_gb_python_process": round(vm_hwm_gb(), 3),
           "peak_rss_gb_largest_child": round(children_maxrss_gb(), 3),
           "rss_note": "python process VmHWM covers meta+tantivy+in-process SEISMIC build; "
                       "largest child = c1a_mmap_index / convert_f16_to_dotvbyte"}
    if res:
        gen = res.get("frozen_generation")
        gdir = root / f"g{gen:04d}"
        gi = json.loads((gdir / "generation.json").read_text())
        out["generation"] = gen
        out["generation_json"] = {k: gi[k] for k in ("seconds", "docs", "docs_with_vectors", "sections", "seismic")}
        out["generation_dir_bytes"] = sum(p.stat().st_size for p in gdir.rglob("*") if p.is_file())
        seis = gdir / "seismic"
        out["seismic_dir_bytes"] = {p.name: (sum(q.stat().st_size for q in p.rglob("*") if q.is_file())
                                             if p.is_dir() else p.stat().st_size) for p in seis.iterdir()} \
            if seis.is_dir() else None
    ledger.close()
    base.close()
    out["host"] = host_info()
    return out


def cmd_assemble(args) -> dict:
    work = Path(args.work)
    stages = {p.stem: json.loads(p.read_text()) for p in sorted(work.glob("*.json"))}
    commit = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    extra = json.loads(Path(args.extra).read_text()) if args.extra else {}
    return {"measurement": "M6 ingest throughput per profile (docs/delta_ingest/03_SPIKE_PLAN.md)",
            "bar": "recorded, no bar", "date": "2026-09-29", "git_commit_measured_at": commit,
            "script": "scripts/experiments/eval_delta_ingest_m6_throughput.py", **extra, "stages": stages}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ingest", "encode", "seed", "build", "assemble"])
    ap.add_argument("--profile", choices=sorted(PROFILES))
    ap.add_argument("--corpus")
    ap.add_argument("--root")
    ap.add_argument("--src-root")
    ap.add_argument("--work", required=True)
    ap.add_argument("--name", default=None, help="stage JSON name under --work")
    ap.add_argument("--limit", type=int, default=200_000)
    ap.add_argument("--min-year", type=int, default=2015)
    ap.add_argument("--sample", type=int, default=200_000)
    ap.add_argument("--max-seconds", type=float, default=0.0)
    ap.add_argument("--write-back", action="store_true")
    ap.add_argument("--n", type=int, default=20_000)
    ap.add_argument("--extra", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    fn = {"ingest": cmd_ingest, "encode": cmd_encode, "seed": cmd_seed, "build": cmd_build,
          "assemble": cmd_assemble}[args.cmd]
    out = fn(args)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    dest = Path(args.out) if args.out else work / f"{args.name or args.cmd + '_' + str(args.profile)}.json"
    dest.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: v for k, v in out.items() if k not in ("stages", "profile", "host")}, indent=1, default=str))


if __name__ == "__main__":
    main()
