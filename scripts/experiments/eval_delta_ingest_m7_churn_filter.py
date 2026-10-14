"""M7 churn filter (docs/delta_ingest/03_SPIKE_PLAN.md, pre-registered 2026-09-29).

Question: on one real OpenAlex snapshot partition file, how many touched
records survive the content-hash / encode-hash filter and would reach the
encoder and the SEISMIC shards?

Bar (verbatim from 03_SPIKE_PLAN.md M7): "recorded; expectation from research
>= 10:1 touched:changed -- if it is < 3:1 the design's write-amplification
argument is wrong".

Two comparison baselines are reported, because the ledger alone cannot see
the base's old hashes:

  A. LEDGER AS CODED. `IngestLedger.classify(batch, in_base)` on a fresh
     ledger. The ledger only knows hashes of docs it staged itself; a base doc
     with no ledger row is classified "updated" unconditionally (ledger.py
     classify: `elif in_base.get(r.id): out["updated"]`). So on first contact
     with the base, the filter discards nothing.

  B. BASE-FIELD PROXY. What the base still holds, compared field by field
     against the snapshot record (after the adapter's normalisation):
       - meta.sqlite docs row: title, doi, year, type, is_oa (all in-base docs)
       - abstract: only the hot section social_sciences__recent keeps a local
         sidecar (abstracts.sqlite); every other section stores none. So the
         EXACT content_hash / encode_hash comparison is only possible on that
         subset; for the rest only title (a lower bound on encode changes) and
         the non-abstract content fields are comparable.
     The base text was exported 2026-06-11..16 from the retired OpenSearch
     index, so B measures ALL drift since the base's data date, not just the
     2026-09-15 change. That makes B conservative (over-counts changes).

Nothing here loads SEISMIC or tantivy; it reads meta.sqlite and one sidecar
read-only. Run it under `flock /tmp/sfu_latency_measure.lock` anyway so its
random reads never overlap a latency measurement.
"""
from __future__ import annotations

import argparse
import collections
import difflib
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "source"))
sys.path.insert(0, str(REPO_ROOT))

from spike.delta_ingest.adapters import OpenAlexSnapshotAdapter, partition_of  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.ledger import IngestLedger  # noqa: E402
from spike.delta_ingest.records import (  # noqa: E402
    DocRecord, W_ID_RE, canonical_id, normalize_openalex_work, reconstruct_abstract)
from lib.thinclient.abstracts import AbstractStore  # noqa: E402

HOT_SECTION = "social_sciences__recent"


class _Resp:
    def __init__(self, content: bytes):
        self.content = content
        self.status_code = 200

    def raise_for_status(self):
        return None


class LocalSession:
    """Serves the adapter's two GETs from local disk: a one-entry manifest and
    the downloaded part file. Exercises OpenAlexSnapshotAdapter unchanged."""

    def __init__(self, manifest: dict, part_url: str, part_path: Path):
        self.manifest = manifest
        self.part_url = part_url
        self.part_path = part_path

    def get(self, url, timeout=None, **_kw):
        if url.endswith("manifest.json"):
            return _Resp(json.dumps(self.manifest).encode())
        if partition_of(url) == partition_of(self.part_url):
            return _Resp(self.part_path.read_bytes())
        raise FileNotFoundError(url)


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "")).strip()


def _norm_loose(s: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s or "").casefold())


def _strip_doi(d: str) -> str:
    d = d or ""
    return d[len("https://doi.org/"):] if d.startswith("https://doi.org/") else d


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def raw_pass(path: Path, limit: int | None, min_year: int) -> tuple[dict, dict]:
    """Every line in the file: id, exclusion reason (adapter order), created
    date, year. Returns (per_id, counters)."""
    per_id: dict[str, dict] = {}
    c = collections.Counter()
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if limit and c["lines"] >= limit:
                break
            c["lines"] += 1
            try:
                w = json.loads(line)
            except json.JSONDecodeError:
                c["json_error"] += 1
                continue
            wid = canonical_id("openalex", w.get("id") or "")
            year = w.get("publication_year")
            if year is not None and year < min_year:
                reason = f"year_lt_{min_year}"
            elif w.get("is_xpac"):
                reason = "is_xpac"
            else:
                ab = w.get("abstract") or reconstruct_abstract(w.get("abstract_inverted_index"))
                if not ab:
                    reason = "no_abstract"
                elif len(ab) < 50:
                    reason = "abstract_lt_50_chars"
                elif not W_ID_RE.match(wid):
                    reason = "bad_id"
                else:
                    reason = "in_slice"
            c[reason] += 1
            per_id[wid] = {"reason": reason, "created": (w.get("created_date") or "")[:10],
                           "year": year, "display_name": w.get("display_name") or ""}
    return per_id, c


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True)
    ap.add_argument("--manifest", required=True, help="local copy of data/jsonl/works/manifest.json")
    ap.add_argument("--part-url", required=True, help="the file's manifest url (s3://openalex/...)")
    ap.add_argument("--index-root", default=str(REPO_ROOT / "data" / "thinclient_index"))
    ap.add_argument("--workdir", default="/var/tmp/sfu_delta_B_20260929")
    ap.add_argument("--out", default=str(REPO_ROOT / "data/eval_results/delta_ingest_M7_20260929.json"))
    ap.add_argument("--limit", type=int, default=None, help="process only the first N lines (sample)")
    ap.add_argument("--min-year", type=int, default=2015)
    args = ap.parse_args(argv)

    t0 = time.time()
    path = Path(args.file)
    manifest_full = json.loads(Path(args.manifest).read_text())
    entry = next(e for e in manifest_full["files"] if partition_of(e["url"]) == partition_of(args.part_url))
    one = {k: v for k, v in manifest_full.items() if k != "files"}
    one["files"] = [entry]

    per_id, raw_c = raw_pass(path, args.limit, args.min_year)
    t_raw = time.time()

    adapter = OpenAlexSnapshotAdapter(LocalSession(one, args.part_url, path), min_year=args.min_year)
    state: dict = {}
    recs: list[DocRecord] = []
    for r in adapter.iter_records(state):
        if args.limit and len(recs) >= raw_c["in_slice"]:
            break
        recs.append(r)
    t_adapt = time.time()
    by_id = {r.id: r for r in recs}
    dup_ids = len(recs) - len(by_id)

    base = BaseIndex(args.index_root)
    all_ids = list(per_id)
    in_base_all: dict[str, bool] = {}
    for i in range(0, len(all_ids), 5000):
        in_base_all.update(base.contains(all_ids[i:i + 5000]))
    t_base = time.time()

    ledger_path = Path(args.workdir) / "m7_ledger.sqlite"
    for suf in ("", "-wal", "-shm"):
        p = Path(str(ledger_path) + suf)
        if p.exists():
            p.unlink()
    ledger = IngestLedger(ledger_path)
    led = collections.Counter()
    for i in range(0, len(recs), 5000):
        batch = recs[i:i + 5000]
        cls = ledger.classify(batch, {r.id: in_base_all.get(r.id, False) for r in batch})
        for k, v in cls.items():
            led[k] += len(v)
    ledger.close()
    t_led = time.time()

    reason_by_base = collections.Counter()
    for wid, d in per_id.items():
        reason_by_base[(d["reason"], "in_base" if in_base_all.get(wid) else "not_in_base")] += 1

    in_base_ids = [r.id for r in recs if in_base_all.get(r.id)]
    new_ids = [r.id for r in recs if not in_base_all.get(r.id)]
    created_new = collections.Counter()
    for wid in new_ids:
        cd = per_id.get(wid, {}).get("created", "")
        created_new["created_ge_2026-06-11" if cd >= "2026-06-11" else
                    ("created_2026-01-01_to_2026-06-10" if cd >= "2026-01-01" else "created_lt_2026")] += 1

    db = sqlite3.connect(f"file:{Path(args.index_root) / 'meta.sqlite'}?mode=ro", uri=True, timeout=60)
    base_rows: dict[str, tuple] = {}
    num = {int(w[1:]): w for w in in_base_ids}
    keys = list(num)
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        for row in db.execute(f"SELECT id,title,doi,year,type,is_oa,section FROM docs WHERE id IN "
                              f"({','.join('?' * len(chunk))})", chunk):
            base_rows[num[row[0]]] = row[1:]
    db.close()
    t_meta = time.time()

    f = collections.Counter()
    type_moves = collections.Counter()
    hot_ids = []
    for wid in in_base_ids:
        r = by_id[wid]
        b = base_rows.get(wid)
        if b is None:
            f["meta_row_missing"] += 1
            continue
        b_title, b_doi, b_year, b_type, b_oa, b_section = b
        t_diff = (r.title or "") != (b_title or "")
        f["title_changed_exact"] += t_diff
        f["title_changed_ws_nfc"] += _norm_ws(r.title) != _norm_ws(b_title)
        f["title_changed_loose"] += _norm_loose(r.title) != _norm_loose(b_title)
        if t_diff and (per_id[wid]["display_name"] or "") == (b_title or ""):
            f["title_differs_but_display_name_equals_base"] += 1
        f["doi_changed_raw"] += (r.doi or "") != (b_doi or "")
        f["doi_changed_normalised"] += _strip_doi(r.doi).lower() != _strip_doi(b_doi).lower()
        f["year_changed"] += int(r.year or 0) != int(b_year or 0)
        f["type_changed"] += (r.type or "") != (b_type or "")
        f["is_oa_changed"] += bool(r.is_oa) != bool(b_oa)
        if bool(r.is_oa) != bool(b_oa):
            f[f"is_oa_base{int(bool(b_oa))}_to_new{int(bool(r.is_oa))}"] += 1
        if (r.type or "") != (b_type or ""):
            type_moves[f"{b_type}->{r.type}"] += 1
        meta_changed = ((r.title or "") != (b_title or "")
                        or _strip_doi(r.doi).lower() != _strip_doi(b_doi).lower()
                        or int(r.year or 0) != int(b_year or 0)
                        or (r.type or "") != (b_type or "") or bool(r.is_oa) != bool(b_oa))
        f["nonabstract_content_changed_normalised"] += meta_changed
        f["section_changed"] += r.section() != b_section
        if b_section == HOT_SECTION:
            hot_ids.append(wid)

    hot = collections.Counter()
    hot_store = Path(args.index_root) / "sections" / HOT_SECTION / "abstracts.sqlite"
    base_abs: dict[str, str] = {}
    if hot_store.exists() or hot_store.with_suffix(".sqlite.flat").exists():
        store = AbstractStore(hot_store)
        for i in range(0, len(hot_ids), 2000):
            base_abs.update(store.fetch(hot_ids[i:i + 2000]))
    for wid in hot_ids:
        r = by_id[wid]
        hot["docs_in_hot_section"] += 1
        if wid not in base_abs:
            hot["base_abstract_missing"] += 1
            continue
        hot["compared"] += 1
        b_title, b_doi, b_year, b_type, b_oa, _ = base_rows[wid]
        b_abs = base_abs[wid]
        base_rec = DocRecord(id=wid, title=b_title or "", abstract=b_abs, year=b_year or None,
                             type=b_type or "", is_oa=bool(b_oa), doi=_strip_doi(b_doi))
        enc_changed = r.encode_hash() != base_rec.encode_hash()
        hot["encode_hash_changed"] += enc_changed
        if enc_changed:
            sim = difflib.SequenceMatcher(None, base_rec.encoder_text(), r.encoder_text()).ratio()
            hot["encode_changed_sim_ge_0.98_cosmetic"] += sim >= 0.98
            hot["encode_changed_sim_0.90_0.98_minor"] += 0.90 <= sim < 0.98
            hot["encode_changed_sim_lt_0.90_substantive"] += sim < 0.90
            b_abs_s, n_abs_s = b_abs.strip(), (r.abstract or "").strip()
            hot["encode_changed_base_abstract_has_html_tag"] += bool(re.search(r"</?[a-zA-Z][^>]{0,20}>", b_abs_s))
            hot["encode_changed_base_abstract_starts_Abstract"] += b_abs_s.lower().startswith("abstract")
        hot["content_hash_changed_doi_normalised"] += r.content_hash() != base_rec.content_hash()
        base_rec_raw = DocRecord(id=wid, title=b_title or "", abstract=b_abs, year=b_year or None,
                                 type=b_type or "", is_oa=bool(b_oa), doi=b_doi or "")
        hot["content_hash_changed_raw_base_doi"] += r.content_hash() != base_rec_raw.content_hash()
        hot["abstract_changed_exact"] += r.abstract != b_abs
        hot["abstract_changed_ws_nfc"] += _norm_ws(r.abstract) != _norm_ws(b_abs)
        hot["abstract_changed_loose"] += _norm_loose(r.abstract) != _norm_loose(b_abs)
        hot["encoder_text_changed_ws_nfc"] += (_norm_ws(r.encoder_text()) != _norm_ws(base_rec.encoder_text()))
        hot["encoder_text_changed_loose"] += (_norm_loose(r.encoder_text()) != _norm_loose(base_rec.encoder_text()))
    t_hot = time.time()

    touched_all = raw_c["lines"]
    touched_slice = len(recs)
    n_new = len(new_ids)
    n_base = len(in_base_ids)
    comp = hot["compared"] or 0
    hot_enc_rate = hot["encode_hash_changed"] / comp if comp else None
    hot_enc_rate_ws = hot["encoder_text_changed_ws_nfc"] / comp if comp else None
    est_base_enc_changed = round(hot_enc_rate * n_base) if hot_enc_rate is not None else None
    est_base_enc_changed_ws = round(hot_enc_rate_ws * n_base) if hot_enc_rate_ws is not None else None

    def ratio(a, b):
        return round(a / b, 3) if b else None

    must_encode_ledger = led["new"] + led["updated"]
    must_encode_lb = n_new + f["title_changed_exact"]
    must_encode_est = n_new + est_base_enc_changed if est_base_enc_changed is not None else None
    must_encode_est_ws = n_new + est_base_enc_changed_ws if est_base_enc_changed_ws is not None else None

    try:
        commit = subprocess.check_output(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        commit = None

    out = {
        "measurement": "M7 churn filter (docs/delta_ingest/03_SPIKE_PLAN.md)",
        "date": "2026-09-29",
        "git_commit_at_run": commit,
        "bar_verbatim": ("recorded; expectation from research >= 10:1 touched:changed -- if it is < 3:1 "
                         "the design's write-amplification argument is wrong"),
        "input": {
            "manifest": "https://openalex.s3.amazonaws.com/data/jsonl/works/manifest.json",
            "manifest_date": manifest_full.get("date"),
            "partition": "updated_date=" + partition_of(args.part_url).split("updated_date=")[1].split("/")[0],
            "file_url": args.part_url,
            "https_url": args.part_url.replace("s3://openalex/", "https://openalex.s3.amazonaws.com/"),
            "local_path": str(path),
            "content_length_bytes": path.stat().st_size,
            "manifest_content_length": entry["meta"]["content_length"],
            "manifest_record_count": entry["meta"]["record_count"],
            "partition_files_in_manifest": sum(1 for e in manifest_full["files"]
                                               if partition_of(e["url"]).split("/")[0] == partition_of(args.part_url).split("/")[0]),
            "sample": bool(args.limit),
            "limit_lines": args.limit,
            "lines_processed": touched_all,
        },
        "slice_filter": {"adapter": "OpenAlexSnapshotAdapter(min_year=%d, allow_xpac=False)" % args.min_year,
                         "reasons_all_records": dict(raw_c),
                         "reason_x_base_membership": {f"{a}|{b}": v for (a, b), v in sorted(reason_by_base.items())},
                         "adapter_yielded": touched_slice,
                         "adapter_duplicate_ids": dup_ids,
                         "raw_in_slice_equals_adapter": raw_c["in_slice"] == touched_slice},
        "counts": {
            "touched_all_records_in_file": touched_all,
            "touched_in_slice": touched_slice,
            "outside_slice": touched_all - touched_slice,
            "in_slice_in_base": n_base,
            "in_slice_new_not_in_base": n_new,
            "new_not_in_base_by_created_date": dict(created_new),
        },
        "baseline_A_ledger_as_coded": {
            "definition": ("IngestLedger.classify on a fresh ledger with in_base from BaseIndex.contains "
                           "(meta.sqlite). The ledger holds no hashes for base docs; an in-base id with no "
                           "ledger row is 'updated' unconditionally."),
            "classify": dict(led),
            "must_encode": must_encode_ledger,
            "ratio_touched_in_slice_to_must_encode": ratio(touched_slice, must_encode_ledger),
            "ratio_touched_all_to_must_encode": ratio(touched_all, must_encode_ledger),
        },
        "baseline_B_base_field_proxy": {
            "definition": ("Snapshot record (normalize_openalex_work) vs what the base holds. meta.sqlite docs "
                           "row (title, doi, year, type, is_oa) for every in-base doc; abstract only for the "
                           "hot section %s via its abstracts.sqlite sidecar (all other sections store no "
                           "abstracts locally). Base text dates from the 2026-06-11..16 build (exported from "
                           "the retired OpenSearch index), so this counts ALL drift since then, not only the "
                           "2026-09-15 change." % HOT_SECTION),
            "field_diffs_all_in_base": dict(f),
            "type_transitions_top10": dict(type_moves.most_common(10)),
            "hot_subset_exact": dict(hot),
            "hot_subset_encode_hash_change_rate": round(hot_enc_rate, 5) if hot_enc_rate is not None else None,
            "hot_subset_encoder_text_change_rate_ws_nfc": round(hot_enc_rate_ws, 5) if hot_enc_rate_ws is not None else None,
            "est_in_base_encode_changed_extrapolated_from_hot": est_base_enc_changed,
            "est_in_base_encode_changed_ws_nfc_extrapolated_from_hot": est_base_enc_changed_ws,
            "must_encode_lower_bound_new_plus_title_changed": must_encode_lb,
            "must_encode_est_new_plus_hot_rate_extrapolated": must_encode_est,
            "must_encode_est_ws_nfc": must_encode_est_ws,
            "ratio_touched_in_slice_to_must_encode_upper_bound": ratio(touched_slice, must_encode_lb),
            "ratio_touched_in_slice_to_must_encode_est": ratio(touched_slice, must_encode_est) if must_encode_est else None,
            "ratio_touched_all_to_must_encode_est": ratio(touched_all, must_encode_est) if must_encode_est else None,
            "ratio_in_base_touched_to_encode_changed_hot_exact": ratio(comp, hot["encode_hash_changed"]),
            "ratio_in_base_touched_to_encode_changed_hot_ws_nfc": ratio(comp, hot["encoder_text_changed_ws_nfc"]),
            "ratio_in_base_touched_to_content_changed_hot_exact": ratio(comp, hot["content_hash_changed_doi_normalised"]),
        },
        "wall_seconds": {"raw_pass": round(t_raw - t0, 1), "adapter": round(t_adapt - t_raw, 1),
                         "base_membership": round(t_base - t_adapt, 1), "ledger_classify": round(t_led - t_base, 1),
                         "meta_rows": round(t_meta - t_led, 1), "hot_sidecar": round(t_hot - t_meta, 1),
                         "total": round(time.time() - t0, 1)},
        "host": os.uname().nodename,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
