# N2 — MPHF viability for ordinal addressing

**Status:** CLOSED MEASURED 2026-09-27 — **FAIL** against the pre-registered bar; the 1.2 GB sorted array stays.

Spike for `docs/seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` §7 N2
(the verdict, table and corrections live there). Results:
`data/eval_results/n2_mphf_viability_2026-09-27.json`.

Pre-registered bar (doc 18 §7, 2026-08-02): ≤ 100 MB and ≤ 100 ns/key end to
end including the verification read, else keep the sorted array.

## Library

- **PtrHash** — crate `ptr_hash` **2.1.1**, license **MIT**
  (R. Groot Koerkamp, "PtrHash: Minimal Perfect Hashing at RAM Throughput",
  SEA 2025, github.com/RagnarGrootKoerkamp/ptrhash). Pinned `=2.1.1`.
- Variant: `PtrHash<u64, Linear, Vec<u32>, Xxh3Int, Vec<u8>>` with
  `PtrHashParams::default()` (the crate's `DefaultPtrHash` layout, but with the
  `Xxh3Int` hasher because W-ids are structured sorted integers and the default
  FxHash does not implement epserde).
- Serialization / mmap: `epserde` 0.13.1 (MIT OR Apache-2.0), `Deserialize::mmap`
  = file-backed mmap, zero-copy.
- Built with rustc 1.98.1 (user-local rustup in `~/.cargo`), `-C
  target-cpu=x86-64-v3` (the repo's portable target; this is a benchmark
  binary, never shipped).

## Files

- `src/main.rs` — the harness. Subcommands: `build` (construct + store the
  MPHF), `payload` (slot of every key → `keys_by_slot.u64`, `perm.u32`,
  `fp8.u8`, `fp16.u16`; asserts minimal-perfect), `genq` (1M random members +
  1M random non-members in [min, max]), `bench <arm>` (cold + warm, hits +
  misses, one JSON object).
- `run_n2.py` — orchestrator: runs every step under
  `flock /tmp/sfu_latency_measure.lock`, adds the numpy `searchsorted`
  baseline (what `src/lib/thinclient/ordinals.py` ships), writes the results
  JSON with the verdict and the information-theoretic floor.
- `Cargo.toml`, `Cargo.lock` — pinned dependencies.

## Reproduce

```bash
curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path
mkdir -p /tmp/claude-1000/n2_mphf
flock /tmp/sfu_latency_measure.lock cp spike/meta_consolidation/work_ordinals_full/wids.npy /tmp/claude-1000/n2_mphf/
(cd spike/archive/n2_mphf && CARGO_TARGET_DIR=/tmp/claude-1000/n2_mphf/target \
   RUSTFLAGS="-C target-cpu=x86-64-v3" ~/.cargo/bin/cargo build --release)
.venv/bin/python3 spike/archive/n2_mphf/run_n2.py --wids /tmp/claude-1000/n2_mphf/wids.npy \
   --work /tmp/claude-1000/n2_mphf/full --out data/eval_results/n2_mphf_viability_2026-09-27.json
```

Built artifacts (≈ 3.4 GB) live in `/tmp/claude-1000/n2_mphf/full/`, never in
the repo. `N2_NO_LOCK=1` skips the lock for tiny subset smoke tests only.

## Result (2026-09-27, Ryzen 7 5700X3D, 150,413,098 keys, 1M queries per pass)

| arm | on disk | warm p50 ns (hit) | warm throughput ns/key | exact? |
|---|---|---|---|---|
| sorted array + binary search (today) | 1,203 MB | 1100 | 685 | yes |
| MPHF only (no verification) | 56 MB | 40 | 16 | no — accepts 100% of non-members |
| MPHF + key at slot (ordinals renumbered) | 1,260 MB | 190 | 75 | yes |
| MPHF + slot→ordinal + today's `wids` | 1,861 MB | 360 | 104 | yes |
| MPHF + 8-bit fingerprint | 207 MB | 160 | 60 | no — 0.39% false accepts |
| MPHF + 16-bit fingerprint | 357 MB | 170 | 79 | no — 0.0014% false accepts |

Construction 45.4 s, peak RSS 3.30 GiB; MPHF 56,215,380 B (2.99 bits/key),
mmaps fully resident at 56.2 MB warm. Every exact variant is larger than the
array it would replace, and the information-theoretic floor for any exact
structure over this key set is 131.6 MB, so the ≤ 100 MB bar was unreachable.
Full table (cold passes, p99, numpy baseline, caveats) in doc 18 §7 N2.
