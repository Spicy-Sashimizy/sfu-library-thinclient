# 01 · Chronicle — the session, question by question

Operator questions are quoted as typed (typos preserved, marked ⟨Q⟩). Answers
are recorded with their substance and every number quoted. Times UTC.

---

## Part I — E8 status and latency literacy (2026-07-13 ~21:30–22:30)

⟨Q⟩ *"taking into consdieration the current recent benchmarks of the new
addition of E8 function in simple terms where does the MMap shard db latency
and quality stand"*

Answer given: E8 (dv-v2 per-doc value scale) fixed the compressed forward's
quality dip — overlap@10 0.993–0.997 on all 8 rebuilt shards (bar ≥0.99;
previously shards 1–2 marginal at 0.985), T1 0/0 per shard, federated T1
20/20 bit-identical, size cost +0.67%. Latency: warm statistically flat
(0.97–1.03× vs dv1), cold better (0.73× shard-1 traverse; majflt 71k→38k).
Federated (`_e8s2_q7_federated_v2_20260713.json`): warm p50 113–118 ms,
cold p50 770–900 ms, anon floor ~1.1 GB, VmSwap 0. Serve flip parked
awaiting operator sign-off.

⟨Q⟩ *"for the latency could you give me a table that has user attentionspan
vs what we have currently"* — table given mapping Nielsen/Doherty thresholds
(<100 ms instantaneous / <400 ms flow / <1 s uninterrupted thought / <10 s
abandonment) to warm 113–118 ms (flow), sequential warm ~330 ms (flow), cold
p50 770–900 ms (just under 1 s). Caveat recorded: p50s only, p95 unknown at
that point.

⟨Q⟩ *"can you get the cold p95 numbers and can you explain the p number what
that means?"* — percentile explainer given (p50 = median experience, p95 =
the 1-in-20 worst that a 10–20-query session will almost surely hit, p100 =
max). Cold p95 extracted from the cell files: hybrid **4.6–4.9 s** (max ~8.1 s),
parallel 4.4–4.5 s, sequential 4.6–6.0 s (max 12.7 s); warm p95 177–182 ms.
Verdict revision: warm solidly in-flow even at p95; cold tail firmly in
"needs a spinner" territory; warmup replay recommended; n=100 precision
caveat stated.

⟨Q⟩ *"would there be levers still that we could do to fix the cold latency
issue? how about the latest research path disk-streaming (q12 skew) 'GRAY
zone', 'design only' ... research from the recent exploration of colibri"*

Answer: ~25× cold/warm gap is I/O-bound; levers = shrink faulting (E5 reorder
0.53× majflt, E8 0.73× — banked) or hide it. Ranked: (1) warmup replay,
(2) hot-set prefault-at-load (F1+F2, est. 1.3–2×), (3) floor pin (F4),
(4) hot-extent pin (F3). Measured-out: PILOT prefetch (seq cold 2.2 s beats
par cold 2.7 s — no spare I/O channel), pread+buffers (unreclaimable anon).
GRAY explained: Q12 bars repeat ≥25% (measured 0.852, pass) and hot-set-80
≤4 GB (measured 4.20 GB, 5% miss). Gates G-a (production-shaped rerun) and
G-b (E8 Stage-2 lands) explained; G-b essentially cleared.

⟨Q⟩ *"doesnt that research spike also explistily interact with LRU caching
also which could be more effective then the current MMAP page evictions?"*

Answer: yes, colibrì's core is a userspace LRU (ESlot/eclock, source-confirmed);
doc 01 called it "the biggest untried lever." Verification (doc 02) kept the
diagnosis (kernel eviction blindness = the 15.8 s warm≈cold host regime) but
replaced the dynamic LRU with a precomputed pin (stable hot set ⇒ decision
can be made offline once); F7 omitted (rung 3, only if F3 plateaus); F9
pread+buffer-pool deferred (unreclaimable anon). Granularity correction
recorded: no shard-level skew exists (every query fans out to all 8 shards);
page/extent level only. Key distinction for the cold question: LRU is an
eviction policy; eviction policy is irrelevant on an empty cache — cold-start
needs prefault, not policy.

## Part II — Launching the autonomous drive (2026-07-13 ~23:00 → 2026-07-14 01:35)

⟨Q⟩ *"could you create a promt that will start working on all of the proposed
research within that spike and can you launch a neuralwatt CCR instance within
the dev container project of sfulibrary thin client please launch it with GLM
5.2 flex billing"*

Actions: drive prompt written (`data/eval_results/_disk_streaming_drive_prompt.md`)
— Phase 0 gates → F1–F5 build order → Phase 6 cold-p95 lever, binding rules
(worst-case shard, n≥100 p50+p95, pre-registered bars, kill-switch env,
same-commit docs), F7/F8/F9 fenced off. CCR: host config found
(`~/.claude-code-router/config.json`, provider neuralwatt, model glm-5.2-flex),
copied into `claudebox-sfu-library-thinclient-app`, `ccr start` on :3456,
smoke test returned model `zai-org/GLM-5.2-FP8`.

Launch failures (all diagnosed, all fixed):
1. `ccr code` rebuilds a shell string from argv — the prompt's backticks broke
   it (`/bin/sh: 1: Syntax error: end of file unexpected`). Fix: bypass ccr
   code; run `claude` directly with `ANTHROPIC_BASE_URL=http://127.0.0.1:3456`,
   prompt via **stdin**.
2. No Claude Code CLI in the container — installed `@anthropic-ai/claude-code`.
3. `--dangerously-skip-permissions cannot be used with root/sudo` — run as
   the `vscode` user (uid 1000).
4. Root-owned log file blocked the vscode rerun silently — recreated
   vscode-owned.
5. The permission classifier twice refused to let the assistant launch the
   skip-permissions agent; the operator ran the launch line personally
   (`docker exec -d -u vscode ... sh /home/vscode/launch_drive.sh`) —
   correct outcome: that consent belongs to the operator.

Session live at 2026-07-14 01:30 (PID 529532); monitored via the transcript
`/home/vscode/.claude/projects/-workspaces-sfu-library-thinclient/3572f0d2-*.jsonl`.

## Part III — The GLM drive session (01:35–04:30) and progress checks

⟨Q⟩ *"has there been any remote commits to github recently? if so whats the
repo and or branch"* — repo `github.com/Spicy-Sashimizy/sfu-library-thinclient`,
branch `spike/mmap-bmp`, tip then 7cb8ca6 (E8 Stage 2 complete, 21:44 UTC);
drive session had not pushed yet; `retriever.py` modification spotted in
progress (the serve flip being written).

⟨Q⟩ *"whats the progress currently?"* (asked twice) — progress reports given.
Drive session output, in commit order: fcfcfb2 (serve flip, operator-signed),
0d3497f (federated gate results committed), e793f2b/7702009 (pre-registrations),
5ebae0f (6-rep hybrid re-bench: v2/v1 cold 0.9923, warm 0.9557 — resolved the
2-rep cold miss), 600ca20 (**Q12b production-shaped probe: GO** — hot-set-80
3.07 GB vs 4 GB bar, repeat 0.9875; the Q12 GRAY inverted), 4e0a888/d6546f6
(doc sync), 56dde5a (F2/F3/F4 wiring), f21a56e (F1 sidecars, all 8 shards:
1.6 GB→60.7% touches, 4.2 GB→88.6%), 77636b7 (eager-load SPLADE before mlock
— ORT dlopen "failed to map segment" + tokenizer rayon ThreadPoolBuildError
under mlock; F3 A/B harness), cd115a3 (Phase 5 T1: 20/20 bit-identical, pin
ON vs OFF, 2-shard ParallelSeismicBackend), 67b1f0b (F6 prefault_ranges hook
+ prefault_hotset), 0b4e9c3 (**the invalid F6 measurement**), 4f954e0/da6fa42
(doc sync carrying the invalid claim). Session exited ~04:30 with an
articulate final report still asserting "cold p95 4.6 s → 30 ms (~150×)".

Praise recorded at the time (still valid): correct gate discipline, honest
host-gating of F3/F4/F5 A/Bs, F4 flagged over-scoped (13.4 GB vs ~20 MB true
floor), resource-aware scheduling, pre-registration before measurement.

## Part IV — The corrections pass (04:30–06:00)

Trigger: reviewer skepticism at the 30 ms claim — *prefault cannot speed up
warm queries*, yet the cells showed warm 25 ms vs 117 ms baseline.

⟨Q⟩ *"yes can you please que up a corrections pass when the session finishes
out"* — monitor armed on session exit; corrections executed on fire.

Evidence chain (full detail in `02_DEFECT_LEDGER.md`): committed F6 cells had
`encode_ms`/`traverse_ms` **0.0 for all 300 samples**, RSS peak 1.78 GB vs
baseline 17.6 GB, load 88.6 s vs 2.8 s → queries were no-ops. Repro with
stderr: `SEISMIC query failed: onnxruntime and transformers are required...`
— canned ImportError masking the real error. Control (gate OFF) healthy
(encode 36.6 ms). Root causes #1–#5 fixed (defect ledger); commit 2203d9b.

Honest re-measurement (guards active, 0 failed queries):
gate ON cold p50 373–490 ms / p95 1464–1884 ms (median 1674); same-day
gate OFF cold p50 666–676 ms / p95 4656–4686 ms; warm 52–55 ms both arms →
**~2.8× cold-p95, ~1.5× cold-p50, warm unchanged**. Parity 10/10 (ids +
scores). Commit 43c090e; five doc locations corrected with dated
CORRECTION banners; parity harness promoted (5caf628,
`scripts/seismic_testbed/seismic_result_parity.py`).

⟨Q⟩ *"doesnt that... do we need the parity on arm to make a determination on
intergration to the mainline?"* — answer: merge = safe without (all levers
default-off, byte-identical); enable = parity required (doc 03 §5 step 5);
parity landed 10/10 during the answer.

## Part V — Trust audit (07:00)

⟨Q⟩ *"btw i would like a check on todays number and how trustworthy they are
the performance jump is quite increadable and also what added moduals where
responsiable for the uplift"*

Audit findings: encode (pure ONNX, no Rust) also halved 30.4→16.7 ms — the
.so rebuild cannot explain warm 117→54 ms; the 01:00 six-rep rebench on the
OLD .so under co-load measured warm 115–126 ms; the rebuild used no
target-cpu flags. Verdict: **warm delta = operating-conditions confound (CPU
contention), not a module**; quiet-host warm ≈54 ms, co-loaded ≈120 ms. Cold
p95 is disk-bound and immune (gate-OFF p95 matches the 2026-07-13 baseline
across days) → the 2.8× stands. Docs corrected (1919855). Trust table:
cold p95 2.8× HIGH, cold p50 1.5× HIGH, warm-as-module-claim LOW,
correctness HIGH. Attribution: cold gains = F6+F1/F2+coalescer; warm = no
module; quality = E8 (prior day).

## Part VI — Explanations requested and given (07:00–08:00)

⟨Q⟩ *"so in simplifed terms it was just better data mapping"* — corrected:
usage-mapping + acting on it at boot; E5 (earlier) made hot data contiguous;
F6 (today) learns where it sits and pre-warms it.

⟨Q⟩ *"wouldnt hot caching more of the db into ram before first search create
a higher ram floor during searching operations? and also how do the page
evictions work under that cheat sheet premus"* — owned-vs-borrowed memory
explained (prefault = clean reclaimable page cache; anon floor measured
unchanged ~1.13 GB); evictor is blind to the map (prefaulted-once pages look
cold to LRU until traffic re-votes them; self-heals at 99% repeat; loses
under sustained pressure → mlock escalation raises the true floor by the
dial).

⟨Q⟩ *"which computer science concepts where related to the performance
uplifts that happened today?"* — locality of reference, Zipf, Denning working
set, demand paging vs profile-guided prefetching, PGO, Amdahl (why 2.8× not
150×), LRU/clock eviction, memory pinning/tiering, tail latency, VMA
internals, amortization, experimental controls.

⟨Q⟩ *"if you where to describe what was the mechisms for the uplift in a few
sentences that someone with termanologie knowlage would know"* — the
four-sentence terminology version (Zipf-skewed access → `search_visited`
trace → extent sidecars → WILLNEED+page-stride prefault over gap-coalesced
ranges → majflt off the critical path; Amdahl-bounded 2.8×; clean file-backed
reclaimable; kernel LRU oblivious → mlock for durability).

## Part VII — The R1 RAM-ladder (06:00–07:00, results by 06:57)

⟨Q⟩ *"previously ive run a test where you remove amounts of ram incramentally
for stress testing... could you check githistory and or documentation and
replicate it and or just create the test... please give me an eta before
starting"*

Found: E7b RAM-capped sweep (commit 9351d8c, 2026-07-03; caps 8/6/4 GB,
single shard0, f16 vs dv; `HOST_PROMPT_E7B_RAMCAP.md` with Rule Zero/Rule One;
container cannot self-cap — cgroup ro, swapoff denied). R1 design: same
method, full 8-shard E8 v2 hybrid serving, sibling containers
`docker run --memory=X --memory-swap=X`, 40 pre-encoded queries (reusing
`e7b_encoded_queries.json`) × 3 passes, 25-min DNF rule, F6 lessons baked in
(empty-results exit 3, swap-confound flag). ETA given: prep ~30–40 min,
first cells within ~1 h, full ladder 2–3 h. Actual: ~75 min.

Results (full table in `03_MEASUREMENT_TABLES.md`): 48/32/24 GB identical
(steady 18–19 ms, 0 majflt); 16 GB marginal (steady 135 ms, still converging);
12 GB hysteresis (2 thrash passes then 22 ms); 8 GB sustained thrash (steady
2.1 s, 261k majflt/pass); 6 GB sustained thrash (steady 4.9 s, 550k). Working
set measured **14.3 GB file + 1.1 GB anon ≈ 15.5 GB**. Commits 331d8da,
65f786b. Backlog R1 section written.

⟨Q⟩ *"i need a full explnation why is the steady latancy benchmarks post
12gbs is a cliff and or is faster then the higher ram caps?"* — the two-
working-sets + convergence-rate explanation (see `04_CONVERGENCE_ARTIFACT.md`);
followed by ⟨Q⟩ *"could you give me the explnation in a simplifed terms"* —
the librarian/desk analogy (junk-sorting speed scales with desk pressure;
below 11 shelves of books, arithmetic not tidiness).

## Part VIII — Pin/F5 arm, quality-under-squeeze, scope Q (07:15→)

⟨Q⟩ *"run the F3 pin ON ladder at 8 and 6 GB and i would like to understand
that quality effects of the squeeze is happening also was the ram capped test
run on the entire 150m or was it on a singlular shard?"*

Answers: R1 = full 150M, all 8 shards (E7b was the single-shard one).
Quality: pressure is residency-only — identical scoring work, slower; no
deadline-based truncation exists; to be verified empirically via per-cell
top-10 dumps vs an unpressured reference. Driver extended (`--dump-results`,
`hotset_pinned_gb` recorded).

**Defect #6 found here:** first pin-ON cells crashed — per-extent mlock
splits VMAs (33k/shard), shard4 pinned 0.00 GB, shard5 died at the manifest
read (line 566) — the same class as defect #4, missed because Phase-5 T1
pinned only 2 shards. Fix: shared `_coalesce_extents` helper (≤2048 ranges,
gap escalation), two-pass reads-before-mlock, budget re-trim after gap fill.
Cells relaunched.

⟨Q⟩ *"yes queue the F5 release test after the pin cells finish and are there
any downsides to implementing this method and also would there be any search
quality degragatation"* + mid-turn ⟨Q⟩ *"btw i also need a simplified
explanation is this just using the Mlocked map that we have sidecarted and
built to trigger page evictions using memory pressure? pleaes reframe and or
correct my question where needed"*

Reframe given: the map is a JSON sidecar (not mlocked); nothing triggers
eviction *via pressure* — F5 evicts **by name** (DONTNEED the map's
complement), replacing pressure; mlock is a shield, not a trigger. One map,
three uses: prefault (load listed pages), pin (forbid evicting them),
release (evict everything else). Downsides recorded: specialist-vs-generalist
cache (off-map queries pay), staleness/refresh cadence, one-shot benefit,
wrong-map self-cold-start (version keys guard), gate off on RAM-rich hosts.
Quality: no degradation by construction; being verified under squeeze by the
running cells. F5 driver flag `--release-except-hotset` implemented
(DONTNEED does not split VMAs — no flag change — but coalesced anyway for
syscall count); F5 16 GB cell queued after pin cells.

## Part IX — External research (08:00→)

⟨Q⟩ *"btw please also search online to see if there any documented version of
this interaction that we are seeing tonight"* and ⟨Q⟩ *"could you do a deeper
reserach on non monotonic convergance artifact to see if theres any research"*

Findings in `05_EXTERNAL_PRECEDENTS.md` and `04_CONVERGENCE_ARTIFACT.md`.
Headlines: our VMA bug class is kernel patch def5efe0 (2017); the container's
max_map_count=262,144 is the Elasticsearch/OpenSearch-mandated value; F6 ≈
Aquifer's profile-guided hot-set pre-install + Neo4j cache warming; F5 ≈
Meta TMO/senpai `memory.reclaim` proactive reclaim (map-guided variant);
convergence artifact = capacity-scaled convergence time (Che/Fagin, WiOpt
2022) × pressure-scaled aging (kernel) observed through a fixed window —
components documented, the composite instrumented observation apparently not.

⟨Q⟩ *"yes add the convergence-artifact note to the research docs can you
document with exteme word for word detail what we have taked about in a new
sub directory in the documents section"* — this directory is that record.

## Part X — Pin/F5 verdicts, optimal settings, kernel internals (08:00→)

⟨Q⟩ *"check the pin and f5 results"* / *"what was the hypothosis orgionally"* —
pin REFUTED (8G neutral, 6G ~35% worse; original doc-03 §3 est. "~1.5–3× p50"
traced and quoted; flaws: touch-coverage ≠ fault-mass + locked bytes starve
the streaming remainder; doc 02 §3.2's own capacity-math caveat applied).
F5 NULL as built (hook scoped to forward_data only; RssFile unchanged after
"releasing 16.45 GB"; pre-sorted-cache hypothesis UNTESTED). Quality under
squeeze: 40/40 bit-identical in all three stressed cells. Commit dd34f26.

⟨Q⟩ *"so what is the optional settings for qality latency and system
resources"* — the recommended configuration (E8 v2 + hybrid +
PREFLOOR_HOTSET=1, everything else off; RAM 24 GB comfortable / 16 GB
minimum / ≤8 GB do-not-ship) — written into THIN_CLIENT_SWAP.md (36e57eb).

⟨Q⟩ *"could you update the docs and thin_client_swap with these optimal
settings and also with the refute of the hypothsis ... what does that mean
for the non monotonic convergance artifact and the fault count mesuaements"*
— docs updated (36e57eb); answer: the refutation CORROBORATES the artifact's
mechanism (active-list self-protection proven even at 550k faults/pass), and
exposed that fault counts are a state metric not a cost metric (6G pin:
majflt +7% but latency +35% → per-fault 0.358→0.452 ms, readahead
fragmentation) — doc 04 §4b.

⟨Q⟩ *"what is the documenation around the kernal level page interactions?
also how is it 'learning' isnt it either a binary choice on which pages are
evicted and or governed by LRU. could you pull any offical doucmenation ...
academic resarch papers"* + topology dummy-check (⟨Q⟩ *"btw just as a dumby
check this is a WSL2 project dev container..."*, confirmed; kernel verified
6.18.33.1-microsoft-standard-WSL2, lru_gen absent → classic two-list) —
full answer in `06_KERNEL_PAGE_RECLAIM_INTERNALS.md`: not-LRU mechanism
stack, binary-choice-vs-accumulated-state correction, MGLRU PID controller,
CLOCK/2Q/LIRS/CLOCK-Pro lineage, per-mechanism mapping to the session's
measurements.
