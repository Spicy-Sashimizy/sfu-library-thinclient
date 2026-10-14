#!/usr/bin/env python3
"""Phase-2 replay driver — the S4 (mixed access) variant of the T2/3 cell.

WHAT THIS IS *NOT*
------------------
It is NOT the phase-2 replay driver. `bench_stack_phase2.sh` runs the real,
already-judged one unchanged:

    scripts/seismic_testbed/t23_convergence_ladder.py

which is standalone (plain argparse, `__main__`, no orchestration, no
subprocess), builds the real backend in-process
(`HybridSeismicBackend.from_manifest(MANIFEST, load_mode="mmap")`,
t23_convergence_ladder.py:201), replays the 40 pre-encoded queries from
data/eval_results/e7b_encoded_queries.json (:197, `--queries` default 40) and
reads majflt from `/proc/self/stat` field 11 (:70-71). Re-implementing that
would break comparability with every t23a/t23b/t23c/sml cell on record.

WHAT THIS *IS*
--------------
Three things the frozen t23 driver deliberately cannot do:

  1. `--weight` (situation S4, "mixed access") — resample the 40-query log
     with replacement under a weighting, instead of walking it once in file
     order.
  2. `--hydrate` (S4) — after each search, pull the top-k rows out of
     meta.sqlite, so the SQLite B-tree's page cache shares the cgroup and the
     policy's cold list with the seismic mmaps. **The t23 driver never touches
     meta.sqlite**: it calls `sb.search_encoded()` on the sharded backend
     directly, while meta.sqlite is only read by the full retriever
     (`ThinClientRetriever._meta_rows`, source/lib/thinclient/retriever.py:1150).
     So "sqlite shares the serving cgroup" is TRUE of the deployed serving
     process and FALSE of the t23 replay — S4 needs this driver to make it
     true again.
  3. `--query-list-b` + `--mixture-schedule` (situation S6, the DRIFT
     HARNESS) — draw each query from one of TWO REAL query lists, with the
     mixture weight following a schedule across replays. See below.

THE DRIFT HARNESS (S6)
----------------------
Per TEST_SITUATIONS.md §"S6 training-data plan": the endpoints are always
REAL measured query distributions; only the SCHEDULE is synthetic. This
driver therefore GENERATES NO QUERIES AT ALL. Both lists are inputs
(`--query-list-a`, `--query-list-b`), both must already be encoded, and every
query replayed is verbatim from one of them.

Schedules (`--mixture-schedule`), all in 1-based replay/pass numbers:

    off              list A only (the default; byte-identical to t23 when
                     --weight is also uniform)
    const:W          weight of list B fixed at W for every replay
    step:N           semester-flip shape — B-weight 0 for replays < N, 1 from
                     replay N on
    step:N:W0:W1     the same flip between two arbitrary weights
    ramp:N1:N2       persona-shift shape — B-weight 0 before replay N1, linear
                     0 -> 1 across [N1, N2], 1 after N2
    ramp:N1:N2:W0:W1 the same ramp between two arbitrary weights

The draw is seeded per replay (`default_rng([--mixture-seed, pass_index])`),
so a cell is reproducible from its result JSON alone, and the REALIZED
mixture (the fraction of that replay's draws that actually came from B, which
is not exactly the scheduled weight for a finite draw) is recorded per pass in
`per_pass[i]["mixture"]`. That is what makes the schedule auditable after the
fact rather than merely asserted.

Both lists must be PRE-ENCODED (the e7b format, {"n_queries", "terms"}, or a
bare list of SPLADE term->weight dicts). Raw query text is refused on purpose:
t23 keeps the ONNX encoder outside the memory cap by pre-encoding, and a
drift cell that encoded inside the cap would put a few hundred MB of model and
arena into the same cgroup the policy is being judged on. Produce a B list the
same way A was produced —
`scripts/seismic_testbed/e7b_ramcap_bench.py --encode-only --query-workload
<real log>`.

Everything else — backend construction, the majflt read, the convergence rule,
the per-pass record shape and the result-JSON keys — is copied from
t23_convergence_ladder.py so the two drivers' outputs can sit in one table.

HOW THE WEIGHTING WORKS (and what it is NOT)
--------------------------------------------
The 40 encoded queries are SPLADE term->weight dicts. There is no measured
per-query "postings-heavy / metadata-heavy" label anywhere in the repo, so
this uses a stated PROXY, not a measurement:

  postings : p_i proportional to n_terms_i ** alpha
             More surviving query terms => more posting lists traversed =>
             more posting_lists.bin + forward_data.bin faults per query.
  metadata : p_i proportional to n_terms_i ** -alpha, and --hydrate is forced.
             Short queries spend proportionally less time in the traversal and
             proportionally more in the fixed-cost top-k hydrate, so the mix
             tilts toward the sqlite B-tree.
  uniform  : the file order, once through, exactly like t23 (--queries 40).

This proxy is an ASSUMPTION and is recorded as such in the result JSON
(`weighting.proxy`). If the gap-3 access-histogram probe ever labels queries
by measured file-level fault mix, replace the proxy with the labels.

NEVER RUN ANYWHERE YET. No cache_ext kernel exists in the dev container.
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
ENCODED = "data/eval_results/e7b_encoded_queries.json"
INDEX_ROOT = "data/thinclient_index"


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def read_majflt():
    """majflt is field 12 (1-indexed) of /proc/self/stat; comm==(python3) has
    no space, so a naive split is safe. Verbatim from
    t23_convergence_ladder.py:70-71 (and e1_kprime_df_sweep.py:158-159)."""
    return int(Path("/proc/self/stat").read_text().split()[11])


def read_vm():
    """VmRSS/VmSwap/RssFile/RssAnon in kB; same fields t23 records."""
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        k, _, v = line.partition(":")
        if k in ("VmRSS", "VmSwap", "RssFile", "RssAnon"):
            out[k.lower() + "_kb"] = int(v.split()[0])
    return out


# ---------------------------------------------------------------------------
# meta.sqlite hydrate (S4 only)
# ---------------------------------------------------------------------------

class MetaHydrator:
    """The retriever's meta.sqlite read path, reduced to what S4 needs.

    Connection factory and SELECT are lifted from
    source/lib/thinclient/retriever.py:325-358 (`_connect_meta`) and :1160-1163
    (`_meta_rows`), including the numeric-id branch, so the SQLite access
    pattern under the cap is the deployed one. Staging (SFU_META_STAGE_DIR)
    is deliberately NOT used: staging copies the DB somewhere else, which is
    the opposite of what S4 wants to measure.
    """

    SELECT = ("SELECT id, title, doi, year, type, is_oa, section "
              "FROM docs WHERE id IN (%s)")

    def __init__(self, index_root):
        import sqlite3
        path = Path(index_root) / "meta.sqlite"
        if not path.exists():
            raise SystemExit("--hydrate needs %s" % path)
        self.path = path
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        cols = {r[1]: (r[2] or "").upper()
                for r in self.db.execute("PRAGMA table_info(docs)")}
        self.numeric = cols.get("id", "").startswith("INT")
        self.rows_read = 0
        log("meta.sqlite %s (%.1f GiB, numeric_ids=%s)"
            % (path, path.stat().st_size / float(1 << 30), self.numeric))

    def hydrate(self, doc_ids):
        if not doc_ids:
            return 0
        keys = list(doc_ids)
        if self.numeric:
            from lib.thinclient.builder import encode_meta_id
            enc = [encode_meta_id(d) for d in keys]
            keys = [e for e in enc if e is not None]
            if not keys:
                return 0
        n = 0
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for _row in self.db.execute(self.SELECT % marks, chunk):
                n += 1
        self.rows_read += n
        return n


# ---------------------------------------------------------------------------

def load_query_list(path):
    """Accept the e7b envelope or a bare list; refuse raw text (see docstring)."""
    obj = json.loads(Path(path).read_text())
    terms = obj["terms"] if isinstance(obj, dict) else obj
    if not isinstance(terms, list) or not terms:
        raise SystemExit("%s: expected a non-empty query list" % path)
    bad = [i for i, t in enumerate(terms[:8]) if not isinstance(t, dict)]
    if bad:
        raise SystemExit(
            "%s: entry %d is %s, not an encoded SPLADE term->weight dict. "
            "Pre-encode the list with `e7b_ramcap_bench.py --encode-only "
            "--query-workload <log>`; this driver never encodes inside the cap."
            % (path, bad[0], type(terms[bad[0]]).__name__))
    return terms


def within_list_weights(terms, mode, alpha):
    """The S4 proxy weighting over ONE list. Returns None for uniform."""
    if mode == "uniform":
        return None
    import numpy as np
    w = np.asarray([len(t) for t in terms], dtype=np.float64)
    w = w ** (alpha if mode == "postings" else -alpha)
    return w / w.sum()


class ReplayScheduler:
    """Builds one replay's query sequence: S4 weighting x S6 drift mixture."""

    PROXY = {
        "uniform": "none (file order / uniform draw)",
        "postings": ("p ∝ n_query_terms ** alpha (more surviving SPLADE terms "
                     "=> more posting lists traversed)"),
        "metadata": ("p ∝ n_query_terms ** -alpha (short queries spend "
                     "proportionally more of the cell in the fixed-cost top-k "
                     "meta.sqlite hydrate)"),
    }

    def __init__(self, args):
        self.args = args
        self.a = load_query_list(REPO / args.query_list_a
                                if not os.path.isabs(args.query_list_a)
                                else args.query_list_a)
        self.b = None
        if args.query_list_b:
            self.b = load_query_list(REPO / args.query_list_b
                                     if not os.path.isabs(args.query_list_b)
                                     else args.query_list_b)
        self.pa = within_list_weights(self.a, args.weight, args.weight_alpha)
        self.pb = (within_list_weights(self.b, args.weight, args.weight_alpha)
                   if self.b else None)
        self.spec = self._parse_schedule(args.mixture_schedule)
        if self.spec["kind"] != "off" and self.b is None:
            raise SystemExit("--mixture-schedule %s needs --query-list-b"
                             % args.mixture_schedule)

    @staticmethod
    def _parse_schedule(spec):
        parts = (spec or "off").split(":")
        kind = parts[0]
        try:
            if kind == "off":
                return {"kind": "off", "spec": spec}
            if kind == "const":
                return {"kind": "const", "spec": spec, "w": float(parts[1])}
            if kind == "step":
                w0, w1 = (float(parts[2]), float(parts[3])) if len(parts) > 3 \
                    else (0.0, 1.0)
                return {"kind": "step", "spec": spec, "n": int(parts[1]),
                        "w0": w0, "w1": w1}
            if kind == "ramp":
                w0, w1 = (float(parts[3]), float(parts[4])) if len(parts) > 4 \
                    else (0.0, 1.0)
                n1, n2 = int(parts[1]), int(parts[2])
                if n2 <= n1:
                    raise ValueError("ramp needs N2 > N1")
                return {"kind": "ramp", "spec": spec, "n1": n1, "n2": n2,
                        "w0": w0, "w1": w1}
        except (IndexError, ValueError) as exc:
            raise SystemExit("bad --mixture-schedule %r: %s" % (spec, exc))
        raise SystemExit("unknown --mixture-schedule kind %r" % kind)

    def weight_b(self, replay_no):
        """Scheduled weight of list B at 1-based replay number."""
        s = self.spec
        if s["kind"] == "off":
            return 0.0
        if s["kind"] == "const":
            return s["w"]
        if s["kind"] == "step":
            return s["w1"] if replay_no >= s["n"] else s["w0"]
        if replay_no <= s["n1"]:
            return s["w0"]
        if replay_no >= s["n2"]:
            return s["w1"]
        frac = (replay_no - s["n1"]) / float(s["n2"] - s["n1"])
        return s["w0"] + frac * (s["w1"] - s["w0"])

    def for_pass(self, pass_idx):
        """(queries, mixture_record) for 0-based pass_idx."""
        import numpy as np
        replay_no = pass_idx + 1
        wb = self.weight_b(replay_no)
        n = self.args.queries

        # The no-mixture, no-weighting case is byte-identical to t23: the
        # whole list, in file order, the same every pass.
        if self.spec["kind"] == "off" and self.pa is None:
            return list(self.a[:n]), {
                "replay": replay_no, "scheduled_w_b": 0.0,
                "realized_w_b": 0.0, "n": min(n, len(self.a)),
                "note": "file order, list A only (t23-identical)"}

        rng = np.random.default_rng([int(self.args.mixture_seed), pass_idx])
        from_b = rng.random(n) < wb if self.b is not None \
            else np.zeros(n, dtype=bool)

        out = []
        for pick_b in from_b.tolist():
            src, p = (self.b, self.pb) if pick_b else (self.a, self.pa)
            j = int(rng.choice(len(src), p=p)) if p is not None \
                else int(rng.integers(0, len(src)))
            out.append(src[j])

        realized = float(from_b.mean()) if n else 0.0
        return out, {"replay": replay_no, "scheduled_w_b": round(wb, 6),
                     "realized_w_b": round(realized, 6), "n": n,
                     "n_from_b": int(from_b.sum())}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # --- the t23 surface, kept name-for-name so the two are interchangeable --
    ap.add_argument("--arm", required=True,
                    help="free-form arm label (baseline / hotset / fifo_ctl). "
                         "Unlike t23 this is NOT cross-checked against "
                         "lru_gen: on a cache_ext kernel MGLRU is off in every "
                         "arm and the arm names a POLICY, not a kernel mode.")
    ap.add_argument("--cap-label", required=True)
    ap.add_argument("--min-passes", type=int, default=3)
    ap.add_argument("--max-passes", type=int, default=12)
    ap.add_argument("--near-zero-majflt", type=int, default=2500)
    ap.add_argument("--plateau-rel", type=float, default=0.10)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--result-file", required=True)
    # --- the S4 additions ---------------------------------------------------
    ap.add_argument("--weight", choices=("uniform", "postings", "metadata"),
                    default="uniform")
    ap.add_argument("--weight-alpha", type=float, default=1.0)
    ap.add_argument("--weight-seed", type=int, default=20260906)
    ap.add_argument("--hydrate", action="store_true",
                    help="read the top-k rows out of meta.sqlite after each "
                         "search (forced on by --weight metadata)")
    ap.add_argument("--index-root", default=INDEX_ROOT)
    # --- the S6 drift harness ----------------------------------------------
    ap.add_argument("--query-list-a", default=ENCODED,
                    help="first REAL encoded query list (default: the 40-query "
                         "t23 workload %(default)s)")
    ap.add_argument("--query-list-b", default=None,
                    help="second REAL encoded query list — the drift endpoint. "
                         "No queries are ever generated; both endpoints are "
                         "measured traffic (TEST_SITUATIONS.md S6)")
    ap.add_argument("--mixture-schedule", default="off",
                    help="off | const:W | step:N[:W0:W1] | ramp:N1:N2[:W0:W1] "
                         "— weight of list B across 1-based replay numbers")
    ap.add_argument("--mixture-seed", type=int, default=20260906)
    args = ap.parse_args()

    if args.weight == "metadata":
        args.hydrate = True

    lru_gen = "absent"
    p = Path("/sys/kernel/mm/lru_gen/enabled")
    if p.exists():
        lru_gen = p.read_text().strip()
    if lru_gen not in ("absent", "") and int(lru_gen, 0) != 0:
        # cache_ext is never consulted with MGLRU on (mm/vmscan.c:6439 vs
        # :6465), so a phase-2 cell with lru_gen set is measuring nothing.
        raise SystemExit("lru_gen/enabled=%s — cache_ext hooks are dead code "
                         "with MGLRU on; disable it first" % lru_gen)

    sched = ReplayScheduler(args)
    weighting = {
        "mode": args.weight, "alpha": args.weight_alpha,
        "proxy": ReplayScheduler.PROXY[args.weight],
        "list_a": args.query_list_a, "n_a": len(sched.a),
        "list_b": args.query_list_b,
        "n_b": len(sched.b) if sched.b else 0,
        "mixture_schedule": sched.spec, "mixture_seed": args.mixture_seed,
    }
    log("replay: list A %s (%d) list B %s (%d) weight=%s schedule=%s"
        % (args.query_list_a, len(sched.a), args.query_list_b or "-",
           len(sched.b) if sched.b else 0, args.weight, args.mixture_schedule))

    hyd = MetaHydrator(REPO / args.index_root) if args.hydrate else None

    from lib.thinclient.sharded_seismic_backend import HybridSeismicBackend
    t0 = time.perf_counter()
    sb = HybridSeismicBackend.from_manifest(str(REPO / MANIFEST),
                                            load_mode="mmap")
    load_s = time.perf_counter() - t0
    log("backend loaded in %.1fs" % load_s)

    passes, converged_kind, empty = [], "maxpass", 0
    for pi in range(args.max_passes):
        # Rebuilt per replay: the S6 mixture weight is a function of the
        # replay number, so the query sequence is too.
        terms, mixture = sched.for_pass(pi)
        lat, mf0 = [], read_majflt()
        rows = 0
        t_pass = time.perf_counter()
        for q in terms:
            t = time.perf_counter()
            res = sb.search_encoded(q, args.top_k)
            if hyd is not None:
                rows += hyd.hydrate([r[0] for r in res])
            lat.append((time.perf_counter() - t) * 1000.0)
            if not res:
                empty += 1
        majflt = read_majflt() - mf0
        wall = time.perf_counter() - t_pass
        lat.sort()
        rec = {
            "pass": pi + 1, "majflt": majflt, "wall_s": round(wall, 3),
            "p50_ms": round(statistics.median(lat), 2),
            "p95_ms": round(lat[max(0, int(0.95 * len(lat)) - 1)], 2),
            "mean_ms": round(sum(lat) / len(lat), 2),
            "ms_per_fault": round(wall * 1000.0 / majflt, 4) if majflt else None,
            "meta_rows": rows,
            "mixture": mixture,
            "vm": read_vm(),
        }
        passes.append(rec)
        log("pass %d: majflt=%d wall=%.1fs p50=%.0fms p95=%.0fms rows=%d "
            "w_b sched=%.3f realized=%.3f"
            % (pi + 1, majflt, wall, rec["p50_ms"], rec["p95_ms"], rows,
               mixture["scheduled_w_b"], mixture["realized_w_b"]))

        # A drift cell MUST run every replay: the interesting part is what
        # happens after the schedule moves, and t23's convergence rule would
        # otherwise stop the run at pass 3 — before a `step:6` ever fires.
        if sched.spec["kind"] != "off":
            continue
        if len(passes) < args.min_passes:
            continue
        if majflt <= args.near_zero_majflt:
            converged_kind = "near_zero"
            break
        prev = passes[-2]["majflt"]
        if prev and abs(majflt - prev) / float(prev) <= args.plateau_rel:
            converged_kind = "plateau"
            break

    # Same refusal as t23_convergence_ladder.py:275-278 (F6): an empty result
    # means the traversal did not actually run, so the latency is meaningless.
    if empty:
        log("REFUSING: %d empty results — not writing a latency record" % empty)
        sys.exit(3)

    final = passes[-1]
    out = {
        "probe": "stack_replay", "date": time.strftime("%Y-%m-%d"),
        "arm": args.arm, "cap": args.cap_label,
        "lru_gen_enabled": lru_gen, "uname": " ".join(os.uname()),
        "manifest": MANIFEST, "queries": args.queries, "top_k": args.top_k,
        "load_s": round(load_s, 1),
        "prefault_gate": os.environ.get("SFU_SEISMIC_PREFLOOR_HOTSET", "0"),
        "pin_budget_gb": os.environ.get("SFU_SEISMIC_PIN_BUDGET_GB", "0"),
        "mlock_floor": os.environ.get("SFU_SEISMIC_MLOCK_FLOOR", "0"),
        "weighting": weighting,
        "hydrate": bool(hyd),
        "meta_sqlite": str(hyd.path) if hyd else None,
        "convergence": {"converged": converged_kind != "maxpass",
                        "kind": converged_kind,
                        "passes_to_converge": len(passes),
                        "rule": {"min_passes": args.min_passes,
                                 "max_passes": args.max_passes,
                                 "near_zero_majflt": args.near_zero_majflt,
                                 "plateau_rel": args.plateau_rel}},
        "converged_state": {"p50_ms": final["p50_ms"], "p95_ms": final["p95_ms"],
                            "majflt": final["majflt"],
                            "ms_per_fault": final["ms_per_fault"]},
        "per_pass": passes,
    }
    Path(args.result_file).write_text(json.dumps(out, indent=2))
    log("wrote %s (converged=%s in %d passes)"
        % (args.result_file, converged_kind, len(passes)))


if __name__ == "__main__":
    main()
