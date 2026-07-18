# Headless GLM 5.2 drive sessions — operating runbook

**Created 2026-07-16** from the R2 fine-ladder (2026-07-14) and R3
kernel-ledger (2026-07-16) campaigns. This is the working recipe for
delegating build/measure/document work to an autonomous GLM 5.2 (NeuralWatt
flex) session running headless inside the app container via
claude-code-router (CCR), with a host-side Claude session acting as
designer + monitor. Everything below was hit for real; nothing is
speculative.

## 1. The architecture (three parties)

| Party | Where | Does | Must never |
|---|---|---|---|
| **Host session** (Claude, this side) | Windows host | Designs/pre-registers the experiment, writes the drive prompt, reviews + executes privileged host actions, F6-verifies results, relaunches the GLM session | Write the scripts or analysis it delegated |
| **GLM drive session** | `claudebox-sfu-library-thinclient-app`, as `vscode` | Writes ALL scripts/instruments/analysis, verifies cells, updates docs, commits + pushes | Run docker, privileged probes, or capped cells (no docker daemon, read-only cgroups in-container) |
| **Host-action queue** | `data/eval_results/_<campaign>_host_queue.md` (shared bind mount) | The only channel between them: GLM appends `## REQ-<n>` blocks; the host monitor flips `status:` to DONE / REJECTED / RUNNING with evidence | — |

The repo dir is bind-mounted into the container (`/workspaces/sfu-library-thinclient`),
so files and git state are shared instantly — git push is for durability,
not signaling.

## 2. Prerequisites (survive across sessions; verify, don't rebuild)

- CCR config at `/root/.claude-code-router/config.json` in the container
  (provider `neuralwatt`, model `glm-5.2-flex`,
  api_base `https://api.neuralwatt.com/v1/chat/completions`).
- `ccr start` running → listens on `127.0.0.1:3456`. Check:
  `docker exec <app> sh -c 'ss -tln | grep 3456'`. It survived 2+ days
  across R2→R3; only restart if not listening.
- `claude` + `ccr` on PATH at `/usr/local/share/nvm/current/bin` (npm-global).
- A drive prompt committed at `data/eval_results/_<campaign>_drive_prompt.md`.

## 3. Launching

The launcher must run as **vscode** (`--dangerously-skip-permissions` refuses
root) and take the prompt via **stdin** (argument-passing breaks on backticks).
The host Claude session is blocked by the permission classifier from creating
or exec'ing anything containing that flag, so **the user runs ONE combined
command** (`!` prefix in the Claude session). Template (PowerShell- and
Git-Bash-safe):

```
docker exec -u vscode <app-container> sh -c 'printf "%s\n" "#!/bin/sh" "cd /workspaces/sfu-library-thinclient || exit 1" "export PATH=/usr/local/share/nvm/current/bin:\$PATH" "export ANTHROPIC_BASE_URL=http://127.0.0.1:3456" "export ANTHROPIC_AUTH_TOKEN=test" "unset ANTHROPIC_API_KEY" "exec claude -p --dangerously-skip-permissions --verbose < data/eval_results/_<campaign>_drive_prompt.md > data/eval_results/_<campaign>_drive.log 2>&1" > /home/vscode/launch_<campaign>.sh && chmod +x /home/vscode/launch_<campaign>.sh' ; docker exec -d -u vscode <app-container> sh -c 'sh /home/vscode/launch_<campaign>.sh'
```

**MSYS path-mangling trap (bit us once):** from Git Bash, a bare
`/home/vscode/...` argument to `docker exec` is rewritten to
`C:/Program Files/Git/home/...` and silently does nothing. ALWAYS wrap the
in-container command in `sh -c '<cmd>'`. Once the launcher exists,
**relaunches are host-session-safe** (no flag in the command):
`docker exec -d -u vscode <app> sh -c 'sh /home/vscode/launch_<campaign>.sh'`.

Verify startup: `ps -eo args | grep '^claude -p '` in the container + the drive
log file exists **owned by vscode** (a root-owned log blocks the next relaunch).
**Do NOT use `pgrep -f 'claude -p'`** (it self-matches monitor scripts that
quote that string) **or `pgrep -x claude`** (it matches the host Claude session
itself); the anchored `ps -eo args | grep '^claude -p '` is the working check
(correction from the deployprep 2026-07-17 three-party run).

## 4. GLM behavioral facts (design the campaign around these)

1. **It cannot hold a turn open.** It will write "parked, watchers armed,
   not stopping" and then end its turn anyway — under plain `-p` the process
   dies and no Monitor/wakeup survives. A STAY-ALIVE prompt rule helped only
   intermittently. **Working pattern: relaunch-as-scheduler** — the host
   monitor relaunches the session at every gate; each fresh run must be told
   (in the drive prompt) to resume from committed state + queue verdicts,
   never redo work. R3 took 5 launches; resume worked every time.
2. **Flex-tier hangs are real — but NOT a constant.** Twice the model call never
   returned (R3): process alive but transcript (newest
   `/home/vscode/.claude-official/projects/-workspaces-sfu-library-thinclient/*.jsonl`
   — note the `.claude-official` path, NOT `.claude/projects/...`) frozen at a
   `tool_result` for 50+ min. Detection: transcript mtime stale >30 min while
   work is pending. Remedy: `kill <pid>` + relaunch — free, because all state
   is committed or on the shared mount. **However the deployprep campaign
   (2026-07-16/17, ~7.5 h, 12 items) saw ZERO flex hangs** — GLM 5.2 flex
   averaged ~35 min/item (range 4–65 min) with no stuck calls. Design for the
   §4.2 hang rate but don't assume it: a hang-less run is normal, and the
   transcript-mtime check is a safety net, not a constant load.
   - **`find -newermt` caveat (this container):** `find` here is `bfs`, which
     REJECTS relative dates like `-newermt '-50 minutes'`. Compute the cutoff
     first: `cutoff=$(date -d '50 minutes ago' +%s); find ... -newermt
     "@$cutoff"` (or stat the transcript's mtime directly).
   - **Transcript path is `.claude-official/projects/...`** on this container
     (the `.claude` tree in §4.2's original wording is stale) — hang detection
     must watch there, or it monitors the wrong directory and never fires.
3. **Plain `-p` buffers stdout** — the drive log is empty until exit. Monitor
   via the transcript jsonl, status files, and git log instead.
4. **Its self-verification tests reconstructions, not artifacts.** See §6 —
   this is the single most important operational lesson.

### 4.1 In-container three-party variant (deployprep 2026-07-17)

The host monitor session can run INSIDE the app container (no `docker exec`
needed) when a docker-free, in-container three-party variant is set up: the
launcher is created by `sed`-copy from a prior campaign's launcher (the
`/home/vscode/launch_<campaign>.sh` of §3 with the campaign name + prompt
paths swapped). All guidance here applies the same way — only the launch
boundary changes (a local `sh` vs a `docker exec -d`). The §5 host-queue
protocol + §6 monitor duties are unchanged; the liveness check above is the
working one for both variants.

## 5. The host-queue protocol (copy the R3 format)

GLM appends; monitor answers. Fields per block: `status:` (PENDING → the
monitor flips to RUNNING/DONE/REJECTED with timestamp + evidence),
`command:` (must reference only committed scripts), `container:` (exact
docker invocation), `why:`, `expected:`. Conventions that mattered:

- Monitor output goes to `_<campaign>_hostreq_<n>.log`, committed.
- REJECT with surgical evidence (file:line, observed vs expected, suggested
  fix, "resubmit as REQ-<n><next-letter>"). GLM fixed 7/7 defects correctly
  when given the failing artifact; average round-trip ~30 min while it polls
  every ~5 min.
- Long runs: flip to RUNNING with the background-task id; per-cell status
  files (`_<campaign>_<cell>.status` RUNNING/DONE/FAIL + an `ALLDONE` flag)
  let GLM verify cells as they land.
- Non-clobbering re-runs: thread a suffix (`_R3_DATE_SUFFIX=r3h` style)
  through every output name so partial/banked artifacts survive.

## 6. Monitor duties — what actually caught the failures

R3's tracer path shipped **seven consecutive silent-empty-data defects**
(bpftrace `--include` no-op → duplicate BEGIN blocks → one-char sed typo →
`bash -c` quote nesting → splice-at-every-mention → 92% perf-ring loss →
`$1`-only arg parsing). GLM's pre-submit checks passed on five of them.
Every one was caught host-side by:

1. **Safety review before anything privileged runs**: read the committed
   script; reject writes outside `data/eval_results/`, anything touching
   `data/seismic_150m/`, `system()`/`signal()` in bpftrace programs.
2. **Live preflight of the committed artifact** in the real environment:
   e.g. `timeout 8 bpftrace <spliced-file>` in the actual privileged
   container — 8 seconds that repeatedly caught what static review missed.
   Never accept "I verified the splice" — run the committed file.
3. **Attach-time breadcrumbs** (`shard_inodes_loaded=N` printed at BEGIN)
   with an orchestrator readiness-wait that greps for them — turns a wasted
   1 h cell into a 90 s abort.
4. **Raw-count verdicts before accepting data**: Σ`Lost N events` vs
   captured (the ≤1% drop bar), event-type composition, cross-checks against
   independent kernel counters (the refault probe was validated ×512 against
   cgroup `workingset_refault_file`, ratios 1.003–1.018).
5. **F6 discipline on every headline number** ([[verify-drive-session-results]]
   memory; backlog §R2 preamble): recompute the claim from the raw file
   before it enters a doc. In R3 the monitor recomputed extent-sharing
   percentages, refault ratios, and cachestat GB — all matched, THEN the
   write-up was accepted.

## 7. Monitoring cadence

Hourly cron in the host session (`/loop 1h`-style) + event-driven
background polls (15 s loop watching the queue file / status files / git log,
25–35 min timeout) so gates clear in minutes when both sides are responsive.
Timeline reference: R3 end-to-end (design → 8 host requests → 4+2 cells →
join → docs) ran ~02:00Z–07:15Z with 2 hang-restarts, ~5 h wall.

## 8. Cost/latency observations (R3, 2026-07-16)

- GLM turnaround on a reject-with-evidence: 5–15 min (it polls every ~5 min).
- Capability probe: ~90 s (apt-get bpftrace dominates; budget 150 s in
  readiness waits, or pre-install).
- One capped cell (12/16 GB, convergence-terminated): 5–8 min + ~3 min cache
  drop/load overhead.
- Session context: ~130k tokens read per fresh launch (cached); five
  launches were unremarkable cost-wise on flex tier.

## 9. Related

- Working memory: [[ccr-neuralwatt-container-setup]] (launch pitfalls),
  [[verify-drive-session-results]] (F6 discipline + R3 extension).
- Worked example, end to end: `data/eval_results/_r3_host_queue.md` (the
  full REQ-1→3h ledger with every verdict), drive prompt
  `data/eval_results/_r3_kernel_ledger_drive_prompt.md`, design
  `docs/seismic_150m_testbed/15_R3_KERNEL_LEDGER_SPIKE.md` §6.
