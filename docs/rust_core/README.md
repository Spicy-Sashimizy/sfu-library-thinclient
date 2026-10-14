# Rust-core spike — one compiled core under the Python server and the handouts

**Status:** ACTIVE (opened 2026-10-11; DESIGN ONLY — nothing ported, nothing measured)

**The question.** The serve path is Python glue (~9k lines on the hot path,
~18k in `source/lib/`) over four native engines (SEISMIC fork via pyo3, tantivy via
pyo3, onnxruntime, torch). Every open row of the portable-stack backlog
(`infrastructure/PORTABLE_STACK_MANIFEST.md` §(d): Windows `.pyd`, relocatable
Python, CPU wheels, the tokenizer trap, macOS/ARM) is the cost of shipping an
interpreter plus those engines, and an Android command-line build has no torch
wheel at all. The owner asked (2026-10-11) which parts of the serve path can be
"Rust-cored" cheaply, which need substantial effort, and for a spike with
documentation, recovery and audits so the working codebase never breaks.

**The recommendation this spike tests** (first stated 2026-10-11, same session):
not a rewrite. A Rust core with a thin shell, in three measured steps:

1. make the Python serve path torch-free (all three models through onnxruntime);
2. port ONE function — encoded query → fused, filtered, hydrated candidates —
   into the existing fork crate with two faces: pyo3 (the server and every
   harness call it unchanged, parity measured in-process) and CLI (the
   Windows/Android binary);
3. decide with numbers whether Tier B modules follow. Python stays for the MCP
   surface, Zotero/OpenAlex/S2, analytics and research harnesses.

Python is not the bottleneck (cache-miss p50 ~5 s is BM25F + SEISMIC traverse +
rerank; glue is milliseconds), so the payoff is portability and longevity, not
speed. The repository's own precedent: Rust moved in where a measured Python cost or a
hard gate forced it (O10 livedocs skip, F5, bit-updater); consolidation for its
own sake measured zero (doc 17, BM25-through-SEISMIC, 2026-08-01).

| Doc | What |
|---|---|
| `01_MODULE_TRIAGE.md` | every serve-path module in a tier: **A** Rust-core now, **B** after A proves out, **C** stays Python / not ported; effort and risk per row |
| `02_SPIKE_PLAN.md` | pre-registered steps, bars, golden fixtures, environment gates, recovery, audits, kill rule |

## Recovery (how nothing breaks)

| Mechanism | Detail |
|---|---|
| Restore tag for the wave | `pre-rust-core-and-script-triage-2026-10-11`, kept by the owner. Verified 2026-10-11 by detached checkout: 2,525 files, tests pass, serve path imports, 5,332 symbols, 0 removed |
| Per-commit gate | `scripts/repo_tools/preflight.py run` before any substantial commit: fresh restore tag + fast tests (669 `source/tests` + policy tests) + function inventory against the tag (`infrastructure/SCRIPT_HYGIENE_POLICY.md` §3) |
| Everything new is gated OFF | `SFU_RERANK_ORT` (step 1) and `SFU_RUST_CORE` (step 2) default unset ⇒ the served path is byte-for-byte today's path. Gates are recorded in `ENV_GATES.md` when the code lands, not before |
| Installed `.so` untouched | Rust work builds on a fork branch into a side path (the O10 pattern); the production `seismic.cpython-311-x86_64-linux-gnu.so` is swapped only by an operator step |
| Roll back | `git checkout <tag>`, or `git revert` the step's commit (each step is its own commit), or unset the gate |

## Audits (who checks what)

- Owner instruction 2026-10-11: general audits run on **Fable** (verification of
  the triage agent's classifications, the test runs, the parity checks). The
  line-by-line script triage itself runs on an Opus agent.
- Every step's parity is measured by harness against frozen golden fixtures
  (`02_SPIKE_PLAN.md` §1), never by inspection.
- `symbol_inventory.py diff` must show zero protected removals at every commit
  of this track; a port that deletes the Python implementation is out of scope
  until Step 3's decision.
