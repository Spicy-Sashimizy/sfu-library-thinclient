#!/usr/bin/env python3
"""Phase 1 — filter meta.sqlite to social_sciences only, into the bundle.

Read-only on the source. Writes a fresh dest db with the exact source schema,
copies docs/docs_other rows WHERE section LIKE 'social_sciences%', VACUUMs, and
prints + persists a JSON report. The dest is a rebuildable artifact, so
journal/synchronous OFF is safe.

    .venv/bin/python3 scripts/portable_socsci/01_filter_meta.py

Env: BUNDLE (default /var/tmp/portable_socsci_bundle), SRC_INDEX
(default data/thinclient_index), KEEP_PATTERN (default 'social_sciences%').

Measured 2026-08-04: 24,176,093 docs rows (== the social_sciences tantivy doc
count), 0 docs_other rows, 4.07 GiB, ~27 min on the 9p source.
"""
import sqlite3, os, time, json

BUNDLE = os.environ.get("BUNDLE", "/var/tmp/portable_socsci_bundle")
SRC_INDEX = os.environ.get("SRC_INDEX", "data/thinclient_index")
PAT = os.environ.get("KEEP_PATTERN", "social_sciences%")

SRC = os.path.join(SRC_INDEX, "meta.sqlite")
DST = os.path.join(BUNDLE, "thinclient_index", "meta.sqlite")


def main() -> dict:
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    if os.path.exists(DST):
        os.remove(DST)

    t0 = time.time()
    src = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
    ddl = {n: s for n, s in src.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table'")}
    src.close()
    print("source tables:", list(ddl), flush=True)

    dst = sqlite3.connect(DST)
    dst.execute("PRAGMA journal_mode=OFF")
    dst.execute("PRAGMA synchronous=OFF")
    for _name, sql in ddl.items():
        dst.execute(sql)
    dst.execute(f"ATTACH DATABASE 'file:{SRC}?mode=ro' AS src")
    dst.commit()

    report = {"src": SRC, "dst": DST, "pattern": PAT, "tables": {}}
    for name in ddl:
        ts = time.time()
        dst.execute(
            f"INSERT INTO main.{name} SELECT * FROM src.{name} "
            f"WHERE section LIKE ?", (PAT,))
        dst.commit()
        n = dst.execute(f"SELECT count(*) FROM main.{name}").fetchone()[0]
        report["tables"][name] = {"rows": n, "seconds": round(time.time() - ts, 1)}
        print(f"{name}: {n} rows in {report['tables'][name]['seconds']}s", flush=True)

    dst.execute("DETACH DATABASE src")
    print("VACUUM...", flush=True)
    dst.execute("VACUUM")
    dst.close()

    report["dst_bytes"] = os.path.getsize(DST)
    report["dst_gib"] = round(report["dst_bytes"] / 2**30, 2)
    report["total_seconds"] = round(time.time() - t0, 1)
    print(json.dumps(report, indent=2), flush=True)
    with open(os.path.join(BUNDLE, "_meta_filter_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    return report


if __name__ == "__main__":
    main()
