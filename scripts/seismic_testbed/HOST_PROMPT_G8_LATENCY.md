# HOST PROMPT — G8 SEISMIC latency re-run (clean, no-swap)

Paste the block below into a Claude Code instance running **directly on the host**
(i.e. NOT inside the container where `/sys/fs/cgroup` is read-only and `swapoff`
fails with "Not super user"). The host instance has the cgroup + RAM access this
container lacks, which is exactly the unblock the 2026-06-29 G8 run needs.

---

## CONTEXT (what you're running and why; do not skip)

You are picking up item #3 of the SEISMIC testbed work: the **G8 150M serving
latency measurement**, which was *recorded-not-concluded* on 2026-06-29 because
the host was swap-thrashing (15/16 GiB swap used → SEISMIC p50 measured 76.7 s,
Qdrant 7.9 s — both swap-page-fault artifacts, NOT representative). The RAM axis
of G8 is already **decisive** (SEISMIC TRUE anon floor 1.10 GB vs Qdrant
16.99 GB incl. 10.23 GB paged to swap — ~15× lower, file-backed mmap never
swaps). **Latency is the open half.**

Everything to run cleanly is already staged on this host:
- The repo: `/workspaces/sfu-library-thinclient` (branch `spike/mmap-bmp`).
  → `git pull` first (CLAUDE.md mandates pull-before-work; the project workflow is
  pull → edit → explicit-add → commit → push, NEVER `git add .`).
- The converted 8-shard 150M SEISMIC corpus: **8 shards × 7.8 GB ≈ 62 GB total**
  at `/tmp/seismic_testbed/index/plan01/global_shard{0..7}of8.mmap/` (C2 flat
  layout — `document_mapping_strings.bin` + `_offsets.bin` present, the only
  layout the mmap reader loads with non-None doc_mapping).
- The manifest (tracked in git): `data/eval_results/seismic_c25_shards_150m_mmap.json`
  — its `index_path`/`mmap_dir` already point at the real
  `/tmp/seismic_testbed/index/plan01/global_shard{N}of8` locations.
- The SPLADE fp16 query encoder: `models/splade_onnx_fp16/model.onnx`.
- The turnkey wrapper: `scripts/seismic_testbed/run_g8_latency_noswap.sh`
  (shipped `f27b879` on the branch).
- The `c1a_mmap_index` bin + Rust source: `spike/seismic_upstream/` (gitignored —
  NOT in git; this host already has it, do not expect `git` to provide it).

**Hardware check before you start (assert, don't assume):**
1. `free -h` — confirm free RAM. The working set is ~62 GB. If the host has
   **< ~12 GB free RAM you will NOT get a clean run** even with swap bound — the
   mmap pages can't stay resident and you'll page-fault to the index file
   (slow, but HONEST — that's the latency we want to measure, not swap thrash).
   A host with ≥ ~16 GB free is comfortable.
2. `mount | grep cgroup` — confirm `/sys/fs/cgroup` is writable (NOT `ro`).
   If it IS `ro`, the cgroup path is walled off; fall back to `swapoff -a`
   (needs true root; the container failed this with "Not super user" — you
   should succeed as the host process).
3. `ls -d /tmp/seismic_testbed/index/plan01/global_shard0of8.mmap` — confirm the
   shards are where the manifest says. If absent, STOP — the shards are /tmp-only
   and were not transferred to this host; do NOT attempt to rebuild them (the
   `spike/seismic_upstream` fork must be present + built first, and a re-convert
   takes ~7 min + 60 GB free, out of scope for a latency run).

## WHAT TO RUN

```bash
cd /workspaces/sfu-library-thinclient
git pull --ff-only          # mandatory before work (CLAUDE.md)

# Clean-ish quick check first (1 of the 8 real shards, mmap, ~2 min incl. the
# ~75s cold SPLADE model load) — confirms the bench + encode/traverse split +
# the wrapper's resident-set capture work on THIS host before committing to
# the full 62 GB 8-shard run. Build a 1-shard manifest from the real one:
.venv/bin/python3 -c "
import json
m=json.load(open('data/eval_results/seismic_c25_shards_150m_mmap.json'))
json.dump({'n_shards':1,'shards':[m['shards'][0]]}, open('/tmp/_1shard_manifest.json','w'))
"
sudo env "PATH=$PATH" \
    scripts/seismic_testbed/run_g8_latency_noswap.sh \
    --shard-manifest /tmp/_1shard_manifest.json \
    --queries 5 --passes 2 \
    --result-file data/eval_results/_g8_host_smoke.json
# Expected on this host: mmap load ~0.1s, RssAnon ~1 GB (≈0.028 index + 0.95
# encoder), VmSwap 0.0, encode p50 ~90ms / traverse p50 ~30ms for 1 shard.

# THE REAL G8 RUN — all 8 mmap'd shards, 150M docs, 40 queries, warm p50
# (passes=2), with the §C1 lever (query_cut=10 → 4× traverse @ overlap@10 0.995):
sudo env "PATH=$PATH" \
    scripts/seismic_testbed/run_g8_latency_noswap.sh \
    --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json \
    --queries 40 --passes 2 \
    --result-file data/eval_results/seismic_g8_150m_serve_noswap_<DATE>.json
```

(Replace `<DATE>` with the run date, e.g. `20260630`. The wrapper sets
`SFU_SEISMIC_QUERY_CUT=10`, `SFU_SEISMIC_HEAP_FACTOR=0.8`, `SFU_SEISMIC_LOAD_MODE=mmap`
by default. To ALSO measure the all-terms baseline for a paired comparison,
re-run with `SFU_SEISMIC_QUERY_CUT= ` (empty) — that disables C1 and uses the
recall-first default the served path currently ships.)

The wrapper: (1) tries cgroup v2 `memory.swap.max=0` → `swapoff` → loud CAVEAT
if neither works; (2) runs `serve_footprint_bench.py` with the encode/traverse
split (§A4); (3) prints the ACTUAL resident set (RssAnon / VmSwap / VmRSS-peak +
encode p50 / traverse p50); (4) reads `vmswap_gb` from the result and says
whether the run was CLEAN (≈0 swap → **verdict**) or still swap-confounded
(>0 swap → record, do not conclude — same status as 2026-06-29).

## WHAT TO RECORD (the whole point — this number doesn't exist yet)

After the run, capture into `docs/seismic_150m_testbed/06_FINDINGS.md` (G8 row
update) + `08_LATENCY_RESEARCH.md` (§A1) per the project's efficacy rule
(CLAUDE.md: new measurements need numbers + eval script + results path + absolute date):

1. **The actual resident set** — the ~7.5 GB projection in 08 §A1 has NEVER been
   measured. Capture: `vmswap_gb` (must be ≈0 for a clean run), `rss_anon_gb`,
   `vmrss_peak_gb`, and the encode p50 / traverse p50 split. This is the single
   most valuable datum: it converts the doc's projection into a measurement.
2. **The SEISMIC p50 warm** (passes≥1) with the encode/traverse attribution —
   is the latency the SPLADE encode (~tens of ms warm) or the SEISMIC fan-out
   traversal (page-fault-bound)? This answers whether §D (int8 encoder) or
   §B/C (index working-set) is the next lever.
3. **Whether C1 helped at 150M** — compare query_cut=10 vs all-terms: does the
   4× traverse speedup hold at scale, and does overlap@10 stay ≥0.99?
   (Re-verify overlap@10 ≥0.99 at 150M before flipping the served default —
   the 100K-testbed C1 measurement is a proxy, not a NDCG-vs-Qdrant verdict.)
4. **If `vmswap_gb > 0`**: the host STILL couldn't hold the working set → the
   number is recorded-not-concluded AGAIN; needs more RAM. Say so plainly.

Commit the results JSON (small) + the doc updates in the same push, per the
same-commit doc rule. Stage ONLY the files you touched — NEVER `git add .` (this
tree carries multi-GB runtime state under `/tmp` and `data/`; blanket staging
orphaned ~47 GB of git objects once, measured 2026-06-11).

## STOP CONDITIONS

- `/sys/fs/cgroup` is `ro` AND `swapoff -a` fails → you're in the same walled-off
  state as the container; the run will reproduce the swap-confounded 76.7 s.
  STOP and report: the latency re-run genuinely needs a host with writable
  cgroup v2 OR ≥ ~16 GB free RAM so the 62 GB working set faults to the index
  file (honest) instead of swap (noise).
- Shards absent at `/tmp/seismic_testbed/index/plan01/` → STOP; do not rebuild.
- The bench crashes on import → check the venv (`/workspaces/sfu-library-thinclient/.venv/bin/python3`)
  has `seismic` + `onnxruntime` + `qdrant_client`; the MCP-server venv rules in
  CLAUDE.md apply (install via `sudo .venv/bin/python3 -m pip install <pkg>`).

## RELEVANT DOCS (read if you need depth)

- `docs/seismic_150m_testbed/08_LATENCY_RESEARCH.md` — §A1 (working-set / no-swap
  host), §A4 (encode/traverse split), §C1 (the query_cut lever, measured), §D
  (int8 encoder). This is the roadmap you're executing.
- `docs/seismic_150m_testbed/06_FINDINGS.md` — the G8 row (the 76.7 s / RAM-decisive
  result you're re-measuring) + the §"G8 150M RAM + latency served" detail.
- `docs/seismic_150m_testbed/02_GO_NO_GO_GATES.md` — G8 gate definition.
