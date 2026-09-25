# eBPF policy test situations — the uplift battery

**Status 2026-09-25: DESIGN. Nothing here is measured; every prediction is
*est.* until a cache_ext kernel exists to run on. EVERY policy-arm row below
is BLOCKED on the only host that exists — see "Runnable vs blocked on this
host" at the foot of this file.** (2026-09-06 status text otherwise
unchanged.) Companion to
`README.md` (findings + files). Arms marked *(upstream)* reuse policies
shipped in `cache_ext_upstream/policies/` at zero new code; arms marked
*(ours)* use `hotset_protect`. Baseline in every situation = the same cell
with **no policy** (which, MGLRU being off on a cache_ext kernel, means
classic LRU — the strong baseline Tier-1d measured). Metric throughout:
steady majflt floor (mean last 3 of 12 passes) + wall, per the t1d
convention; Phase 2 adds per-replay wall and p50/p95.

## Phase 1 — synthetic (t1d driver, frozen baselines exist)

| ID | Situation | Arms | The question | Prediction (*est.*) |
|---|---|---|---|---|
| E1 | **Policy ladder at the divergence rung** — cap 1.5G, `hotset:0.20:0.80`, seed 2027 | classic · fifo · s3fifo · lfu/sampling · lhd *(upstream)* · hotset *(ours)* | Which policies beat classic where MGLRU lost 1.443×? And do the *learned* policies (s3fifo/lfu/lhd), blinded to mmap recency, degrade to ≈fifo as the visibility finding predicts? | hotset ≤ classic floor (perfect knowledge = upper bound); learned ≈ fifo ≥ classic |
| E2 | **App knowledge across the cap band** — hotset arm at caps 0.75 / 1.5 / 2.5 / 4G | classic vs hotset | Where does being told the hot set pay? | biggest at 1.5G and 0.75G; ≈0 at 4G |
| E3 | **Right-sized protection where classic drowns** — h=0.40 (hot 2G > cap 1.5G), hot table **truncated to a cap-sized prefix** (`--limit-mib`) | classic (measured floor 678k) vs truncated-hotset | mlock pinning failed by protecting too much; does protecting exactly-what-fits win the regime nobody wins today? | the potential headline: a floor well under 678k |
| E4 | **Taming the readahead bomb** — `fa:hotsetc:0.20:0.80` at 1.5G (the ≥30×-amplification cell) | classic-fa vs hotset-fa | Does hot-extent protection make fault-around survivable at a tight cap? | from unrunnable (>1800s/pass) toward runnable |
| E5 | **Residue sorting** — `wl:` cells at 5.5/6.5G (the T1d-15 inversion rig) | classic vs hotset (table = R's hot set, residue unlisted) | Does explicit knowledge sort the residue out faster than classic's refault-activation? | policy ≥ classic; margin is the finding |
| E6 | **Stale-table robustness** — E1's hotset arm with the table deliberately wrong by 25% / 50% / 100% (`--corrupt-frac`) | hotset(correct) vs corrupted ladder | The production risk: how fast does the win decay as real traffic drifts from the table? | graceful to ~25%, ≈fifo at 100% |
| E7 | **Warm-path overhead on our shape** — cap 8G (everything fits), empty-table policy vs none, 12 passes | none vs empty-table | Is the paper's ≤1.7%/IO ≈ 0 on a 0-fault warm path, for us? | indistinguishable floors and walls |
| E8 | **Live table refresh** — E1's hotset arm; at pass 6 the pinned map is rewritten to a *different* seeded hot set (the draw switches at the same pass) | static-stale vs live-refreshed | Is runtime refresh (the production cadence question) mechanically viable and effective? | refreshed arm re-converges within ~3 passes |

Order: E7 first (it validates the rig cheaply), then E1 (the headline
ladder), then E3 (the novel regime), then E2/E4/E5, then E6/E8
(production-viability pair). One cell ≈ t1d walls (3–20 min by cap); the
full phase-1 battery ≈ 25 cells ≈ two window-evenings on the cache_ext box.

## Phase 2 — real stack (sidecar table, 40-query replay)

| ID | Situation | Arms | The question |
|---|---|---|---|
| S1 | **Replay ladder at real caps** — cgroup memory.max 24 / 16 / 14G | baseline vs sidecar-hotset vs empty-table | Does the policy move the real p50/p95/majflt at the tiers that matter — and does 14G become shippable? |
| S2 | **Noisy neighbor** — 16G serving cgroup + an antagonist streaming scan outside it | baseline vs sidecar-hotset | The demo-box co-load story: does protection hold the ~54ms profile under pollution pressure? |
| S3 | **Rebuild interference** — a sequential export/pack-shaped scan INSIDE the policy cgroup | baseline vs sidecar-hotset | The exposure case from the README: does hot-set protection starve streaming work sharing the cgroup, and by how much? |
| S4 | **Mixed access** — replay weighted toward metadata-heavy queries (sqlite) vs postings-heavy | same arms as S1 at 16G | Does a postings-tuned table mishandle the B-tree pattern sharing the process? |
| S5 | **Sidecar fidelity** — sidecar table vs a gap-3-probe-derived table (when the probe exists) | the two tables at 16G | Are the F1 sidecars already the right hot set, or does measured traffic beat them? |
| S6 | **Hotness-predictor ladder (the ML question, userspace-side)** — static sidecar table vs EMA-refreshed table (frequency decay over the query stream) vs a learned ranker's table (offline-trained on replay logs), all through the same E8 refresh path | three table sources at 16G | Does any *predictor* beat the static table enough to justify its moving parts? In-kernel ML (LearnedCache-style) is ruled out for this stack — its feature tracer feeds on `folio_mark_accessed`, which mmap never calls (their stated limitation; our §1a code-read finding independently) — so the ML seat, if any, is userspace table generation. Gate: run the offline eval (predictor AUC on held-out replay traffic) BEFORE burning kernel time; if EMA ≈ learned offline, the learned arm is dropped. |

Phase 2 runs only after Phase 1's E1/E7 justify the kernel time; S5
additionally waits on the gap-3 probe, and S6 on S5 plus its offline gate.

## S6 training-data plan (semi-synthetic queries + drift harness)

A parametric synthetic query set is DISALLOWED as training input — a model
trained on generator-chosen statistics rediscovers the generator and
validates against itself (the Tier-1→1c circularity lesson, one level up).
The synthetic machinery instead gets three bounded jobs:

1. **Pipeline validation:** any traffic may exercise the full chain
   (replay → gap-3 access recording → features/labels → model → chunk
   table → E8 refresh) as an engineering smoke test. No scientific claims.
2. **Drift harness (the load-bearing piece):** replay whose query mixture
   shifts mid-run between **two real measured distributions** (e.g. the
   40-query workload vs a persona-weighted demo mix) on a controlled
   schedule — semester-flip and persona-shift shapes. Synthetic in the
   *scheduling only*; endpoints always real. This is what actually
   separates EMA from a learner in S6.
3. **Volume expansion, semi-synthetic only:** if training needs more than
   the real seeds (40-query real workload, 120 SFU benchmark queries, demo
   mix, personas), expand by corpus-grounded LLM paraphrase/neighbor
   generation FROM those seeds, so term statistics stay anchored to actual
   usage. Parametric generators (Zipf-knob traffic) stay banned.

**Hard rules:** the S6 evaluation gate is scored on held-out REAL traffic
only — never on anything this section produces; and the static table needs
no training at all (the probe measures hotness directly), so all of this
exists solely to test drift-tracking. **Standing recommendation:** start
retaining hosted demo/GUI query logs now (anonymized per the public-demo
posture) — every week of real logs devalues the synthetic substitute.

Sequencing: after the gap-3 probe freezes (the probe records the access
data this consumes). Drift-harness code: assigned to the spike's code
agent alongside knob 5 (the S2–S4 helpers) — a mixture-schedule option on
the phase-2 replay driver. — PENDING Every situation lands its numbers in
this file with absolute dates when run; unrun rows stay *est.*

## Code knobs the battery needs (agent work; status tracked here)

1. `load_hotset.py chunks --limit-mib N` — truncate the table to the
   hottest N MiB (E3). — **DONE 2026-09-06** (ranking-prefix subset;
   under t1d's uniform-within-hot draw this is an unbiased seeded subset,
   so E3 reads as right-*sized*, not better-*ranked*).
2. `--corrupt-frac F --corrupt-seed S` — **DONE 2026-09-06**, at PAGE
   granularity (page membership is what the policy tests; page count
   preserved exactly, chunk count moves slightly — recorded in the table
   header). frac=1.0 verified to give zero overlap with the true set.
3. `refresh` (pinned-map runtime rewrite) — **DONE 2026-09-06** (required
   pinning `hot_chunks`, added alongside the stats pin). Semantics: only
   folios faulted AFTER the refresh are re-filed — a refresh is
   forward-looking, never a re-sort.
4. `bench_matrix.sh` + `situations_battery.conf` (23 rows) — **DONE
   2026-09-06**. E8 caveat: the map-rewrite half works, but switching the
   *workload's* draw at the same pass needs a `t1d_cell.py` mid-run
   hot-set switch (outside this spike) — until that lands, an E8 row
   measures "table goes wrong at pass N" (a timed E6). — workload-side
   switch **DONE 2026-09-06**: `t1d_cell.py --hotset-switch-pass N`
   [`--hotset-switch-seed S`] [`--hotset-switch-skew SPEC`] draws passes
   N..end from a SECOND independently seeded hot set (default seed
   `seed^0x5717C8`, replayable from the JSON's new `hotset_switch` block;
   passes gain `hot_set_epoch` and the residency of both hot sets), with
   `bench_matrix.sh switch_at=/switch_seed=/switch_skew=` and
   `refresh_table=auto-epoch1` (`load_hotset.py chunks --epoch 1`) pinning
   the map to exactly the set the workload moves to. Off by default and
   bit-identical when unset (verified against the pre-change driver on a
   tiny cell, 2026-09-06). Kernel efficacy of the refreshed arm remains
   *est.* — unrun, like every row above.
5. Phase-2 S2–S4 helpers — **DONE 2026-09-06** (`antagonist_scan.sh`;
   `stack_replay.py --weight` with the term-count proxy recorded in the
   result JSON, and `--hydrate` for sqlite traffic).
6. S6 drift harness — **DONE 2026-09-06** (`stack_replay.py
   --query-list-a/-b --mixture-schedule off|const|step|ramp
   --mixture-seed`; realized mixture logged per replay; convergence
   early-stop disabled under a schedule; pre-encoded lists required by
   design so the encoder never enters the capped cgroup).

## Runnable vs blocked on this host — 2026-09-25

The only machine left is the WSL2 box (kernel
`6.18.33.2-microsoft-standard-WSL2+`, Debian 12 container, 16 cores, 31 GB).
No cloud host exists any more. The spike now **compiles** there
(`README.md` §7), which changes nothing about what can be *run*.

**Two independent walls, either one sufficient:**

- **W1 — no cache_ext kernel.** Zero hits for `cache_ext_ops` /
  `cache_ext_list_node` / `cache_ext_eviction_ctx` / `cache_ext_iterate_opts`
  / `sampling_options` in this kernel's BTF; zero `bpf_cache_ext_*` symbols in
  `/proc/kallsyms`; the only struct_ops type this kernel registers is
  `tcp_congestion_ops`. Clearing W1 means booting WSL2 on a hand-built
  `-cache-ext` bzImage (README §4 — and README §4's WSL2 risk list is still
  unverified). MGLRU is also `=y` here and cache_ext needs it off (§1b).
- **W2 — no `CAP_BPF` in the container.** `CapBnd 0x00000000a80425fb` clears
  CAP_BPF, CAP_SYS_ADMIN and CAP_PERFMON; `sudo` inherits the same bounding
  set, so uid 0 buys nothing, and `kernel.unprivileged_bpf_disabled=2`.
  `bpf(2)` returns `-EPERM` for libbpf's *trivial* probe program, before our
  object is ever offered to the kernel. Clearing W2 means recreating the
  container with `--cap-add=BPF,PERFMON,SYS_ADMIN` (host-side, outside this
  spike).

| Row | Runnable here? | Why |
|---|---|---|
| **E1–E8** (phase 1, every policy arm incl. the upstream fifo/s3fifo/sampling/lhd/mru/mglru arms and the empty-table control) | **BLOCKED** | W1 + W2. `bench_mmap_visibility.sh` and `bench_matrix.sh` both guard on a `-cache-ext` kernel and exit; that guard is correct, not a bug. |
| **S1–S6** (phase 2, every policy arm) | **BLOCKED** | W1 + W2, plus the phase-2 rig needs `data/thinclient_index` at scale, which this spike must not touch (page-cache measurements there are owned elsewhere). |
| E1/E2/E3/E5/E7 **no-policy baseline arms** (`t1d_cell.py`, synthetic, no BPF) | mechanically runnable | needs no BPF at all — but these are the *already-frozen* Tier-1d baselines, so re-running buys nothing except a host-comparability check, and each cell costs 3–20 min. Not scheduled. |
| S1–S6 **baseline arms** | **do not run** | they drive the real index; benching `data/thinclient_index` is another owner's territory. |
| `load_hotset.py chunks` / `stack-chunks` / `--limit-mib` / `--corrupt-frac` / `--epoch 1` | **RUNNABLE** (and exercised 2026-09-06 against real sidecars + a real t1d result) | pure userspace table generation; no kernel involvement. |
| `load_hotset.py attach` / `stats` / `refresh` | **BLOCKED** | all three need a loaded, pinned policy. |
| `bench_matrix.sh` parser dry-run, `bash -n` on every script, `stack_replay.py` offline scheduler exercise | **RUNNABLE** (done 2026-09-06) | no kernel involvement. |
| `offline_build/build_offline.sh` (compile + link + load attempt) | **RUNNABLE** (done 2026-09-25) | the load attempt is expected to fail; that failure is the recorded result, not a measurement of the policy. |

**Consequence for the battery's ordering.** "E7 first, then E1" still stands,
but the gating item ahead of all of it is now a kernel, not code: nothing in
this file can produce a number until a `-cache-ext` boot exists. The
2026-09-25 build result removes the *code* risk from that plan (the policy
compiles as authored; the two portability `#define`s live in the harness, not
in the policy) and leaves the kernel risk untouched.
