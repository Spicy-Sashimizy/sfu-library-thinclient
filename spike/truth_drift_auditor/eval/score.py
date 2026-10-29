"""Score the pipeline against a judged set.

judged_set.jsonl lines: {"paragraph": str, "label": "drifted"|"ok", "note": str}
A paragraph counts as predicted-drifted when the report says so (numeric
mismatch or a CONTRADICTED claim). Precision / recall / F1 on the "drifted"
class plus the confusion counts, written with an absolute date so the result
can be cited (repo policy: no unmeasured efficacy claims).
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from truth_drift_auditor.models import Paragraph


def score_judged(auditor, judged_path: Path, out_path: Path | None = None) -> dict:
    rows = [json.loads(l) for l in judged_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    tp = fp = fn = tn = 0
    per_row = []
    for i, row in enumerate(rows):
        rep = auditor.audit_paragraph(Paragraph(index=i, text=row["paragraph"]))
        pred = rep.drifted
        gold = row["label"] == "drifted"
        tp += pred and gold; fp += pred and not gold; fn += (not pred) and gold; tn += (not pred) and not gold
        per_row.append({"i": i, "gold": row["label"], "pred": "drifted" if pred else "ok",
                        "claims": [c.verdict for c in rep.claims],
                        "numeric_mismatches": sum(1 for f in rep.numeric if not f.ok)})
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    result = {
        "date": _dt.date.today().isoformat(), "judged_set": str(judged_path), "n": len(rows),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
        "tier1": type(auditor.tier1).__name__ if auditor.tier1 else None,
        "retriever_legs": [r.name for r in getattr(auditor.retriever, "retrievers", [])] if auditor.retriever else [],
        "rows": per_row,
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result
