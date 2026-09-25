# 06 · Kernel page-reclaim internals — what actually decided tonight's numbers

**Status:** ACTIVE

Written 2026-07-14, answering the operator questions: *"what is the
documentation around the kernel level page interactions? how is it 'learning'
— isn't it either a binary choice on which pages are evicted and or governed
by LRU?"* This file is the precise, source-anchored version, correcting the
"learning" shorthand used in earlier explanations.

## §0 The exact machine this applies to (verified)

Topology (operator-confirmed 2026-07-14): Claude Code on the Windows 11 host;
the search engine and every benchmark inside Docker containers on the WSL2
Linux VM; storage via the drvfs/9p translation layer; one shared WSL2 RAM
pool (~56 GB) and one page cache for host-side and container-side alike.

Kernel verified in-container: **`6.18.33.1-microsoft-standard-WSL2`**, and
`/sys/kernel/mm/lru_gen/enabled` is **absent → the classic two-list
active/inactive reclaim is what runs here**, NOT the multi-generational LRU.
Every R1/F6/F3 number in this session was produced by the machinery in §1–§3.

## §1 It is not LRU — the actual mechanism stack

True LRU needs a total recency order updated on every access — unaffordable
for raw memory loads. Linux ships an approximation assembled from a few bits
of per-page state (family: CLOCK/2Q, not LRU):

1. **Hardware accessed bit** — the CPU sets a PTE bit on touch, for free; the
   kernel *samples and clears* it during reclaim scans. The only observation
   primitive that exists.
2. **Two FIFO lists forming a "double clock"** (the design comment at the top
   of `mm/workingset.c` is the canonical documentation:
   https://github.com/torvalds/linux/blob/master/mm/workingset.c ):
   faulted-in pages start on the **inactive** list (probation); a page
   referenced *again* while on inactive is **promoted to active**
   (protected); eviction takes from the inactive tail only. The
   "seen-twice" promotion filter is the 2Q algorithm (Johnson & Shasha,
   VLDB 1994).
3. **Shadow entries / refault distance** — the genuinely feedback-like part
   (`mm/workingset.c`; original patch series "refault distance-based file
   cache sizing": https://lkml.iu.edu/hypermail/linux/kernel/1205.0/00053.html ):
   an evicted page leaves a *ghost entry* stamping the eviction clock; if it
   faults back, the kernel computes the **refault distance** (evictions in
   between) and, if the page would have survived under a different
   active/inactive balance, activates it immediately and rebalances the
   lists. Post-eviction mistake-detection at ghost-entry cost.
   Third-party walkthrough: https://biriukov.dev/docs/page-cache/4-page-cache-eviction-and-page-reclaim/
4. **Pressure-proportional aging** — all of the above only *runs* during
   reclaim scans, whose rate scales with memory pressure
   (https://kernel-internals.org/mm/reclaim/). No pressure ⇒ no aging work ⇒
   stale list state persists. This is the second clock behind the
   convergence artifact (doc `04_` §2).

## §2 "Binary choice" — the operator's framing, corrected precisely

The eviction *decision* is binary at the moment it happens. But it is
conditioned on **accumulated, historical state**: which list the page is on,
its referenced bit, `PG_workingset`, and — uniquely — ghost entries for pages
no longer resident. "Learning," as used in this session's explanations, means
exactly this and nothing more: *reference bits accumulating into list
membership, plus refault feedback rebalancing the lists.* Learning in the
control-systems sense (a feedback loop); no statistics, no model. The
operator's instinct that no cleverness beyond bookkeeping is involved is
correct — the remarkable part is how much regime-discrimination (R1's flat /
marginal / hysteresis / thrash bands) emerges from ~2 bits per page plus
ghosts.

## §3 The successor design makes the feedback loop explicit

Multi-Gen LRU (merged 6.1; official docs
https://docs.kernel.org/mm/multigen_lru.html , source doc
https://www.kernel.org/doc/Documentation/mm/multigen_lru.rst ): N generations
instead of two lists; **tiers by access count** (`order_base_2(N)` refs); and
— the kernel documentation's own words — "a feedback loop modeled after the
**PID controller**" that monitors per-tier *refaults* and chooses which tiers
to evict vs protect. The mainline literally adopted control-theory
terminology for what §1.3 does crudely. Not active on this box (§0), but it
validates reading the classic machinery as a proto-controller.

## §4 Academic lineage

| work | contribution inherited by Linux |
|---|---|
| CLOCK (Corbató, 1968–69) | reference-bit circular scan — the ancestor |
| 2Q (Johnson & Shasha, VLDB '94) | probation + protected queues → active/inactive |
| LIRS (Jiang & Zhang, SIGMETRICS '02) | reuse-distance ranking, ghost entries |
| CLOCK-Pro (Jiang, Chen, Zhang, USENIX ATC '05 — https://www.usenix.org/legacy/event/usenix05/tech/general/full_papers/jiang/jiang.pdf ) | LIRS at CLOCK cost; per its authors "directly influenced the upgrades of replacement algorithms in Linux, BSD"; the shadow-entry/refault machinery is its descendant |
| ARC (Megiddo & Modha, FAST '03) | adaptive ghost-list dual queue (patented; never merged, intellectually adjacent) |
| Denning working set (1968) | the capacity framing the R1 ladder measures against |

## §5 Mapping to this session's measurements (one line each)

- **2Q promotion ("seen twice")** ⇒ hot pages re-earn protection every pass ⇒
  the F3 mlock pin was redundant insurance ⇒ pin refutation
  (`r1_cap{8,6}g_pin16_20260714.json`).
- **Shadow-entry refault feedback** ⇒ what completed the residue-vs-repeat-set
  "sorting" at 12 GB by pass 3 (`r1_cap12g_20260714.json`).
- **Pressure-proportional scan rate** ⇒ why 16 GB sorted lazily (104k→56k→15k
  majflt, unconverged at pass 3) ⇒ the convergence artifact (doc `04_`).
- **Below-capacity cyclic pattern** ⇒ no policy can win (8/6 GB thrash) —
  sequential-flooding territory, policy-independent.
- **Ghost/refault machinery is per-page, not per-map** ⇒ it can never learn
  our hot-set sidecar's contents ⇒ prefault (F6) works only until pressure,
  and durability would need pinning — which §5.1 shows buys nothing against
  *self*-thrash (external-competitor regime still open).

## §6 Source list

- `mm/workingset.c` (design comment + refault implementation):
  https://github.com/torvalds/linux/blob/master/mm/workingset.c
- Refault-distance patch series (Weiner, LKML 2012):
  https://lkml.iu.edu/hypermail/linux/kernel/1205.0/00053.html
- Multi-Gen LRU official docs: https://docs.kernel.org/mm/multigen_lru.html
  and https://www.kernel.org/doc/Documentation/mm/multigen_lru.rst
- Page reclaim internals: https://kernel-internals.org/mm/reclaim/
- CLOCK-Pro (USENIX ATC '05):
  https://www.usenix.org/legacy/event/usenix05/tech/general/full_papers/jiang/jiang.pdf
- Biriukov, *Page Cache eviction and page reclaim*:
  https://biriukov.dev/docs/page-cache/4-page-cache-eviction-and-page-reclaim/
- WSL2 kernel source (the actual kernel here):
  https://github.com/microsoft/WSL2-Linux-Kernel/blob/master/mm/workingset.c
