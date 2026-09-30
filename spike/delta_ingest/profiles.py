"""Resource profiles — the same pipeline from a laptop trickle to a server bulk.

Every dial the pipeline honours lives here so "how slow / how fast" is one
switch (`--profile`) plus overrides, not a different code path:
  encode_*        GPU TRT vs CPU PyTorch, batch size
  ingest_batch    records classified/staged per ledger transaction
  rate_docs_per_s throttle (sleep between batches) so ingest never starves a
                  co-located serving process; 0 = unthrottled
  flush_docs/_bytes  when the L0 buffer freezes into an immutable generation
  buffer_max_docs hard cap on the mutable tier (RAM: exact sparse scorer holds
                  ~nnz*12 B per doc, ~2.5 KB/doc at SPLADE's ~200 nnz)
  max_rss_gb      abort a generation build if the process RSS crosses it
                  (mirrors build_plan01_150m_shards --abort-rss-gb)
  seismic_threads SEISMIC build threads; the c1a/dotvbyte converters are serial
  parts_per_run   snapshot parts (≤400k records each) per invocation
  nice            os.nice() increment for the ingest process
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class IngestProfile:
    name: str
    encode_backend: str = "auto"
    encode_device: str = "auto"
    encode_batch: int = 64
    ingest_batch: int = 2000
    rate_docs_per_s: float = 0.0
    flush_docs: int = 500_000
    flush_bytes: int = 2 * 1024 ** 3
    buffer_max_docs: int = 100_000
    max_rss_gb: float = 20.0
    seismic_threads: int = 8
    parts_per_run: int | None = None
    nice: int = 0

    def with_overrides(self, **kw) -> "IngestProfile":
        return replace(self, **{k: v for k, v in kw.items() if v is not None})

    def as_dict(self) -> dict:
        return asdict(self)


PROFILES: dict[str, IngestProfile] = {
    # CPU-only, 8 GB class machine, serving co-located: trickle a few k docs/h.
    "laptop": IngestProfile(
        name="laptop", encode_backend="pytorch", encode_device="cpu", encode_batch=8,
        ingest_batch=200, rate_docs_per_s=20.0, flush_docs=20_000, flush_bytes=256 * 1024 ** 2,
        buffer_max_docs=20_000, max_rss_gb=3.0, seismic_threads=2, parts_per_run=1, nice=10),
    # This dev box: one consumer GPU, 31 GB RAM, serving co-located.
    "desktop_gpu": IngestProfile(
        name="desktop_gpu", encode_backend="auto", encode_device="auto", encode_batch=64,
        ingest_batch=2000, rate_docs_per_s=0.0, flush_docs=500_000, flush_bytes=2 * 1024 ** 3,
        buffer_max_docs=100_000, max_rss_gb=12.0, seismic_threads=8, parts_per_run=4, nice=5),
    # Dedicated ingest host: freeze multi-million-doc generations.
    "server": IngestProfile(
        name="server", encode_backend="trt", encode_device="cuda", encode_batch=128,
        ingest_batch=10_000, rate_docs_per_s=0.0, flush_docs=5_000_000, flush_bytes=16 * 1024 ** 3,
        buffer_max_docs=500_000, max_rss_gb=48.0, seismic_threads=16, parts_per_run=None, nice=0),
}


def rss_gb() -> float:
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024 ** 2
    except OSError:
        pass
    return 0.0


def apply_nice(profile: IngestProfile) -> None:
    if profile.nice:
        try:
            os.nice(profile.nice)
        except OSError:
            pass
