"""O7 — peak RSS of OpenAlexSnapshotAdapter before -> after the streaming fix.

docs/delta_ingest/02_DESIGN.md §3.1 O7: the adapter gzip.decompress()ed a whole
partition in memory (M6: 6.74 GB ingest peak on both profiles). This harness
iterates the adapter only (records counted, then dropped: no ledger, no
tantivy, no encoder), each arm in its own child process, and reads VmHWM.

Arms
  old_spooled   adapters.py as of 105261c8 (pre-fix), partition served through
                a session whose response holds the compressed bytes
                (`.content`), exactly the M6 LocalSession path
  new_spooled   fixed adapter, same partition through a streamed response
                (`iter_content`) spooled to local disk
  new_local     fixed adapter, partition named by a local path in the manifest
                (read in place)

Corpus: a real OpenAlex snapshot partition already on disk (downloaded by
item B 2026-09-29), cut to its first N raw lines and re-gzipped so the OLD
arm stays inside the 4 GB memory bound of this dispatch. The new arms are
also run on the whole partition (bounded by construction).

Timings are recorded but INVALID as throughput numbers: shared host, nice 19,
4 cores (taskset 12-15), concurrent latency run by another agent.

Usage
  nice -n 19 taskset -c 12-15 .venv/bin/python3 scripts/experiments/eval_delta_ingest_o7_streaming.py \
      run --out data/eval_results/delta_ingest_O7_streaming_20261001.json
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

PARTITION = Path("/var/tmp/sfu_delta_B_20260929/works_updated_date=2026-09-15_part_0001.gz")
WORK = Path("/home/vscode/work/delta_ingest/O7")
PRE_FIX_COMMIT = "105261c8"
PART_URL = "s3://openalex/data/jsonl/works/updated_date=2026-09-15/part_0001.gz"
MANIFEST = "local://manifest.json"


def vm_hwm_gb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) / 1024 ** 2
    return float("nan")


def vm_rss_gb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024 ** 2
    return float("nan")


class _Resp:
    def __init__(self, body: bytes | None = None, path: Path | None = None):
        self._body, self._path, self.status_code = body, path, 200

    def raise_for_status(self):
        return None

    @property
    def content(self):
        return self._body if self._body is not None else self._path.read_bytes()

    def close(self):
        return None


class _StreamResp(_Resp):
    def iter_content(self, chunk_size=1 << 20):
        with open(self._path, "rb") as fh:
            while chunk := fh.read(chunk_size):
                yield chunk


class LocalSession:
    """Serves the manifest and one partition from local disk. `stream`
    selects a response with iter_content (new arm) or `.content` only (the
    M6 LocalSession shape, old arm)."""

    def __init__(self, part_url: str, part_path: Path, stream: bool):
        self.part_url, self.part_path, self.stream = part_url, part_path, stream

    def get(self, url, stream=False, **kw):
        if url == MANIFEST:
            return _Resp(body=json.dumps({"entries": [{"url": self.part_url}]}).encode())
        if url.endswith(self.part_url.split("works/", 1)[1]):
            return (_StreamResp if self.stream else _Resp)(path=self.part_path)
        raise FileNotFoundError(url)


def load_old_adapters():
    import spike.delta_ingest  # noqa: F401
    src = subprocess.run(["git", "-C", str(REPO), "show", f"{PRE_FIX_COMMIT}:spike/delta_ingest/adapters.py"],
                         capture_output=True, text=True, check=True).stdout
    path = WORK / "adapters_pre_o7.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("spike.delta_ingest._adapters_pre_o7", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def cmd_child(a) -> None:
    part = Path(a.part)
    base_rss = vm_rss_gb()
    if a.arm == "old_spooled":
        mod = load_old_adapters()
        ad = mod.OpenAlexSnapshotAdapter(LocalSession(PART_URL, part, stream=False),
                                         manifest_url=MANIFEST, min_year=a.min_year)
    else:
        from spike.delta_ingest.adapters import OpenAlexSnapshotAdapter
        if a.arm == "new_spooled":
            ad = OpenAlexSnapshotAdapter(LocalSession(PART_URL, part, stream=True), manifest_url=MANIFEST,
                                         min_year=a.min_year, spool_dir=WORK / "spool")
        else:
            ad = OpenAlexSnapshotAdapter(LocalSession(str(part), part, stream=True), manifest_url=MANIFEST,
                                         min_year=a.min_year)
            ad.session.part_url = str(part)
    t0 = time.perf_counter()
    n = 0
    first_s = None
    for _rec in ad.iter_records({}):
        if first_s is None:
            first_s = time.perf_counter() - t0
        n += 1
    wall = time.perf_counter() - t0
    print(json.dumps({"arm": a.arm, "part": str(part), "records_in_slice": n,
                      "baseline_rss_gb": round(base_rss, 3), "peak_rss_gb": round(vm_hwm_gb(), 3),
                      "wall_s": round(wall, 2), "first_record_s": round(first_s or 0, 2),
                      "timings_valid": False}))


def make_subset(n_lines: int) -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / f"part_0001_first{n_lines}.gz"
    raw = 0
    lines = 0
    if not out.exists():
        tmp = out.with_suffix(".tmp")
        with gzip.open(PARTITION, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
            for line in src:
                dst.write(line)
                raw += len(line)
                lines += 1
                if lines >= n_lines:
                    break
        os.replace(tmp, out)
    else:
        with gzip.open(out, "rb") as src:
            for line in src:
                raw += len(line)
                lines += 1
    return {"path": str(out), "raw_lines": lines, "raw_bytes": raw, "gz_bytes": out.stat().st_size}


def full_stats() -> dict:
    raw = lines = 0
    with gzip.open(PARTITION, "rb") as src:
        for line in src:
            raw += len(line)
            lines += 1
    return {"path": str(PARTITION), "raw_lines": lines, "raw_bytes": raw, "gz_bytes": PARTITION.stat().st_size}


def run_child(arm: str, part: str, min_year: int, mem_cap_gb: float) -> dict:
    cmd = [sys.executable, __file__, "child", "--arm", arm, "--part", part, "--min-year", str(min_year)]
    env = {**os.environ, "OMP_NUM_THREADS": "2"}
    p = subprocess.run(["prlimit", f"--as={int(mem_cap_gb * 1024 ** 3)}", "--", *cmd],
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        return {"arm": arm, "part": part, "error": f"rc={p.returncode}", "stderr_tail": p.stderr[-600:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


def cmd_run(a) -> None:
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    subset = make_subset(a.subset_lines)
    full = full_stats()
    runs = []
    for arm in ("old_spooled", "new_spooled", "new_local"):
        runs.append({"corpus": "subset", **run_child(arm, subset["path"], a.min_year, a.mem_cap_gb)})
    for arm in ("new_spooled", "new_local"):
        runs.append({"corpus": "full", **run_child(arm, str(PARTITION), a.min_year, a.mem_cap_gb)})
    out = {
        "measurement": "O7 OpenAlexSnapshotAdapter peak RSS before -> after streaming (docs/delta_ingest/02_DESIGN.md §3.1 O7)",
        "bar": "none pre-registered; recorded. Laptop profile max_rss_gb 3.0 is the reference cap",
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head_at_run": head,
        "pre_fix_adapter": f"{PRE_FIX_COMMIT}:spike/delta_ingest/adapters.py",
        "script": "scripts/experiments/eval_delta_ingest_o7_streaming.py",
        "corpus_note": ("REAL OpenAlex snapshot partition (item B download 2026-09-29); the subset is its first "
                        f"{a.subset_lines} raw lines re-gzipped so the pre-fix arm stays under the {a.mem_cap_gb} GB "
                        "address-space cap of this dispatch"),
        "subset": subset, "full_partition": full, "min_year": a.min_year,
        "method": ("each arm a separate child process under prlimit --as; adapter iteration only (records counted "
                   "and dropped); peak = VmHWM of the child; nice 19, taskset 12-15, OMP_NUM_THREADS=2"),
        "timings_valid": False,
        "timings_note": "shared host with a concurrent exclusive latency run; wall times are not throughput numbers",
        "runs": runs,
    }
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "child"])
    ap.add_argument("--arm", default="new_local")
    ap.add_argument("--part", default=str(PARTITION))
    ap.add_argument("--min-year", type=int, default=2010)
    ap.add_argument("--subset-lines", type=int, default=60000)
    ap.add_argument("--mem-cap-gb", type=float, default=4.0)
    ap.add_argument("--out", default=str(REPO / "data/eval_results/delta_ingest_O7_streaming_20261001.json"))
    a = ap.parse_args()
    (cmd_run if a.cmd == "run" else cmd_child)(a)


if __name__ == "__main__":
    main()
