import json
import subprocess
import sys
from pathlib import Path

from truth_drift_auditor.cli import build_auditor
from truth_drift_auditor.config import load_config
from truth_drift_auditor.pipeline import split_paragraphs
from truth_drift_auditor.tier1_haiku import build_user_message, parse_verdicts
from truth_drift_auditor.models import Evidence

ROOT = Path(__file__).resolve().parent.parent


def test_split_paragraphs_skips_headings_and_tracks_offsets():
    text = "# Title\n\nFirst paragraph here.\n\nSecond one.\n"
    ps = split_paragraphs(text)
    assert [p.text for p in ps] == ["First paragraph here.", "Second one."]
    assert text[ps[0].start:ps[0].end].strip() == "First paragraph here."


def test_offline_batch_flags_the_drifted_paragraphs_only():
    cfg = load_config(ROOT / "config.example.toml")
    aud = build_auditor(cfg, offline=True)
    reports = aud.audit_document(ROOT / "fixtures/drafts/sample_draft.md")
    flags = [r.drifted for r in reports]
    # p0 correct, p1 wrong projection number, p2 meaning drift (fake client cannot see it),
    # p3 correct ratio, p4 plan/opinion
    assert flags[0] is False
    assert flags[1] is True
    assert flags[3] is False
    assert flags[4] is False
    assert reports[0].evidence, "local retriever must find the lit-review passage"
    assert reports[0].claims[0].verdict == "SUPPORTED"
    assert reports[1].numeric and not reports[1].numeric[0].ok
    assert reports[1].claims[0].verdict == "CONTRADICTED"


def test_parse_verdicts_locates_quotes_and_normalises_bad_labels():
    para = "Alpha is 3. Beta is 4."
    data = {"claims": [
        {"quote": "Beta is 4.", "claim": "beta=4", "verdict": "supported", "evidence_ids": ["x"], "confidence": 0.9, "note": ""},
        {"quote": "missing", "claim": "", "verdict": "WEIRD", "evidence_ids": [], "confidence": 0.1, "note": ""},
    ]}
    cs = parse_verdicts(para, data)
    assert cs[0].verdict == "SUPPORTED" and cs[0].span == (12, 22)
    assert cs[1].verdict == "NO_EVIDENCE" and cs[1].span is None


def test_user_message_contains_evidence_ids_and_paragraph():
    msg = build_user_message("P", [Evidence(id="doc#1", text="E", source="local", score=1.0)], ["OK: x"])
    assert "[doc#1]" in msg and "PARAGRAPH" in msg and "OK: x" in msg


def test_cli_batch_offline_writes_jsonl(tmp_path):
    out = tmp_path / "r.jsonl"
    cmd = [sys.executable, "-m", "truth_drift_auditor.cli", "--config", str(ROOT / "config.example.toml"),
           "batch", "--draft", str(ROOT / "fixtures/drafts/sample_draft.md"), "--offline", "--out", str(out)]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(rows) == 5 and rows[1]["drifted"] is True


def test_eval_offline_scores_judged_set(tmp_path):
    cfg = load_config(ROOT / "config.example.toml")
    aud = build_auditor(cfg, offline=True)
    sys.path.insert(0, str(ROOT))
    from eval.score import score_judged
    res = score_judged(aud, ROOT / "eval/judged_set.example.jsonl", tmp_path / "res.json")
    assert res["n"] == 8 and 0.0 <= res["f1"] <= 1.0
    assert (tmp_path / "res.json").exists()
