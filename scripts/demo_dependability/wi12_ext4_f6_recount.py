#!/usr/bin/env python3
"""WI-12 route B (2026-07-28) F6 discipline: recompute the headline soak
availability directly from the raw per-request JSONL, independent of the
summary JSON reliability_soak.sh itself writes. Usage:

    .venv/bin/python3 scripts/demo_dependability/wi12_ext4_f6_recount.py \
        data/eval_results/_wi12_soak_requests_<TS>.jsonl \
        data/eval_results/wi12_soak_<TS>.json
"""
import json
import sys


def main():
    jsonl_path = sys.argv[1]
    summary_path = sys.argv[2] if len(sys.argv) > 2 else None
    reqs = [json.loads(l) for l in open(jsonl_path) if l.strip()]
    total = len(reqs)
    sheds = [r for r in reqs if r.get("shed")]
    accepted = [r for r in reqs if not r.get("shed")]
    acc_ok = [r for r in accepted if r.get("ok")]
    acc_fail = [r for r in accepted if not r.get("ok")]
    avail = len(acc_ok) / max(len(accepted), 1)
    print(f"raw jsonl: {jsonl_path}")
    print(f"total requests: {total}")
    print(f"sheds (429, clean): {len(sheds)}")
    print(f"accepted: {len(accepted)}  accepted_ok: {len(acc_ok)}  accepted_fail: {len(acc_fail)}")
    print(f"F6 RECOMPUTED availability = accepted_ok/accepted = {avail:.4f} ({avail*100:.2f}%)")
    from collections import Counter
    status_hist = Counter(r.get("status") for r in reqs)
    err_hist = Counter(r.get("error", "").split(":")[0] for r in acc_fail if r.get("error"))
    print(f"status histogram: {dict(status_hist)}")
    print(f"fail error-type histogram: {dict(err_hist)}")
    if summary_path:
        summ = json.load(open(summary_path))
        summ_avail = summ.get("availability")
        print(f"\nsummary JSON availability: {summ_avail}")
        agree = abs(summ_avail - avail) < 1e-6 if summ_avail is not None else False
        print(f"F6 AGREEMENT (raw recount == summary JSON): {agree}")


if __name__ == "__main__":
    main()
