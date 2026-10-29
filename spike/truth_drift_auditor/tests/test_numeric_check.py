from pathlib import Path

from truth_drift_auditor.config import load_config
from truth_drift_auditor.metrics_store import MetricsStore
from truth_drift_auditor.numeric_check import check_paragraph, extract_numbers

ROOT = Path(__file__).resolve().parent.parent


def _setup():
    cfg = load_config(ROOT / "config.example.toml")
    return MetricsStore(cfg.path("metrics.directory")), cfg.aliases


def test_extract_numbers_units_and_unicode_minus():
    ms = extract_numbers("saves 2.37 GB, −17.6 % smaller, 1,021.76 s, 1.72x slower, 146 µs")
    got = [(m.value, m.unit) for m in ms]
    assert (2.37, "GB") in got
    assert (-17.6, "%") in got
    assert (1021.76, "s") in got
    assert (1.72, "x") in got
    assert (146.0, "us") in got


def test_correct_number_passes():
    store, aliases = _setup()
    f = check_paragraph("The dictionaries on the served section are 17.6 % smaller than no dictionary.", store, aliases)
    assert f and all(x.ok for x in f)


def test_wrong_number_is_flagged_with_expected_value():
    store, aliases = _setup()
    f = check_paragraph("The dictionaries on the served section are 25 % smaller than no dictionary.", store, aliases)
    bad = [x for x in f if not x.ok]
    assert bad and bad[0].expected == -17.58 and bad[0].written == 25.0


def test_projection_alias():
    store, aliases = _setup()
    f = check_paragraph("At 150M the abstract sidecar is estimated at about 60 GB with dictionaries.", store, aliases)
    assert any((not x.ok) and x.expected == 71.56 for x in f)
    f2 = check_paragraph("At 150M the abstract sidecar is estimated at 71.6 GB with dictionaries.", store, aliases)
    assert f2 and all(x.ok for x in f2)


def test_sentence_without_alias_phrase_is_ignored():
    store, aliases = _setup()
    assert check_paragraph("We expect 25 % more users next year.", store, aliases) == []


def test_number_attached_to_phrase_wins_over_other_numbers_in_sentence():
    store, aliases = _setup()
    s = ("Projected over the full 150M-work corpus the abstract sidecar is estimated at about 60 GB "
         "with dictionaries, which comfortably beats the earlier 64.7 GB figure.")
    f = [x for x in check_paragraph(s, store, aliases) if x.path.endswith("a_shipped")]
    assert f and f[0].written == 60.0 and not f[0].ok
