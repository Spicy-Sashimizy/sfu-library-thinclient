#!/usr/bin/env python3
"""R3 probe splicer (2026-07-16; doc 15 §1 + orchestrator LOAD PATH note).

Substitutes the shard-inode BODY fragment (_r3_inode_body.bt) into each
bpftrace probe's SINGLE BEGIN block at the `/*INODE_BODY*/` placeholder,
producing committed `r3_ledger_spliced.bt` / `r3_refault_probe_spliced.bt`.

This replaces the orchestrator's prior runtime `sed -e "/.../r <body>" -e
"/.../d"` splice, which failed four ways (REQ-1 `--include` ignored bpftrace
syntax; REQ-3 BEGIN-merge; REQ-3c one-char `r` typo; and the follow-on MSYS
`r: command not found` from backslash handling inside `bash -c "..."`). Doing
the splice ONCE, here, in normal Python — where its integrity is
machine-verified — means the tracer just `bpftrace <file>`s the output. No
sed, no nested quotes, no MSYS mangling, no in-container python dependency.

SUBSTITUTION ANCHOR (the REQ-3e monitor correction, 2026-07-16): the splice
substitutes at the EXACT placeholder LINE — a line whose stripped content is
`/*INODE_BODY*/` — NOT at every textual mention of that string. The probes'
header DOC COMMENTS mention `/*INODE_BODY*/` (to explain the splice); a naive
`str.replace(marker, body)` (the REQ-3d bug) injected the 8-assignment body at
EVERY mention, twice at file scope (comments became live syntax → bpftrace
compile error) and once correctly inside BEGIN. Line-anchored substitution
injects exactly ONCE, inside BEGIN.

Run after editing any probe or the inode map (r3_inode_map.py is the body's
generator). Exits non-zero if a probe lacks the placeholder, or the spliced
file does not have: exactly ONE BEGIN block, exactly ONE body copy (8 inodes +
1 count line), and ZERO non-comment statements outside probe blocks. (That
last check is the REQ-3e lesson — structural BEGIN-count alone missed the
file-scope body copies; content integrity is what bpftrace actually compiles.)

Usage:
    .venv/bin/python3 scripts/seismic_testbed/r3_splice_probes.py
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
PROBES = [
    ("scripts/seismic_testbed/r3_ledger.bt",
     "scripts/seismic_testbed/r3_ledger_spliced.bt"),
    ("scripts/seismic_testbed/r3_refault_probe.bt",
     "scripts/seismic_testbed/r3_refault_probe_spliced.bt"),
]
BODY = "data/eval_results/_r3_inode_body.bt"
MARKER = "/*INODE_BODY*/"   # the EXACT placeholder line, stripped


def main():
    body = (REPO / BODY).read_text()
    n_body_assigns = body.count("@shard_inodes[")
    n_body_count = body.count("@shard_inodes_count =")
    print(f"body {BODY}: {n_body_assigns} @shard_inodes[ assigns, "
          f"{n_body_count} count line(s)", flush=True)
    if n_body_assigns == 0:
        print("FATAL: inode body is empty — regenerate via r3_inode_map.py first",
              file=sys.stderr)
        return 2
    bad = False
    for probe_rel, out_rel in PROBES:
        src_lines = (REPO / probe_rel).read_text().splitlines()
        # line-anchored substitution: only lines whose stripped text IS the
        # marker get the body inlined; comment-mention lines are left alone.
        spliced_lines = []
        n_spliced = 0
        for L in src_lines:
            if L.strip() == MARKER:
                spliced_lines.append(body.rstrip("\n"))
                n_spliced += 1
            else:
                spliced_lines.append(L)
        spliced = "\n".join(spliced_lines) + "\n"
        out = REPO / out_rel
        out.write_text(spliced)

        # ── content-integrity checks (the REQ-3e bar, stronger than BEGIN==1) ──
        begins = [i for i, L in enumerate(spliced.splitlines())
                  if L.strip() == "BEGIN"]
        # the body's signature is `@shard_inodes_count = 8;` — it must appear
        # exactly ONCE total (one body copy).NOT the @shard_inodes[ assigns
        # count, because the probe's OWN predicates reference @shard_inodes[
        # (the filter) and so legitimately raise that count above one body copy.
        total_count = spliced.count("@shard_inodes_count = 8;")
        # zero non-comment, non-blank statements OUTSIDE a probe block.
        # probe blocks: BEGIN{...}/END{...}/tracepoint:.../fentry:.../kprobe:...
        in_block = False
        probe_headers = ("tracepoint:", "fentry:", "fexit:", "kprobe:",
                         "kretprobe:", "kfunc:", "BEGIN", "END", "interval:",
                         "profile:")
        stray = []
        for L in spliced.splitlines():
            s = L.strip()
            if not s or s.startswith("//"):
                continue
            # a probe block opens at a line starting with a probe header
            if any(s.startswith(h) for h in probe_headers):
                in_block = True
                continue
            if s == "{":
                continue
            if s.startswith("}"):
                # closing a probe block — body assigns inside BEGIN are
                # indented under { ... }, so they're covered by in_block.
                continue
            if not in_block:
                # a top-level statement outside any probe block — the REQ-3e
                # defect class: body injected at file scope (comments became
                # live syntax). bpftrace allows only probe defs at file scope.
                stray.append(L)
        ok = (len(begins) == 1 and n_spliced == 1
              and total_count == 1 and not stray)
        print(f"{out_rel}: splices={n_spliced} (want 1) BEGIN={len(begins)} "
              f"(want 1) count_lines={total_count} (want 1) "
              f"stray_toplvl={len(stray)} (want 0) -> {'OK' if ok else 'BAD'}",
              flush=True)
        if stray:
            print(f"  stray top-level lines: {stray[:3]}", flush=True)
        if not ok:
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

