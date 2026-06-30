#!/usr/bin/env python3
"""SEISMIC G7 — fully-confirm the 150M build-RAM requirement via a measured curve.

NOT a 150M build (RAM-impossible on this 31 GB host — the k-means clustering +
forward index are held resident by `SeismicIndex.build`; pyseismic 0.4.0 has no
on-disk/streaming build path). Instead: collect every measured peak-RSS data
point (the persona builds + the larger scale points built for this run), fit TWO
models (linear + power-law), and project to 150M with a stated conservative band.

The two models are defense-in-depth against a single-fit blind spot:
  - linear  rss = a + b·docs        (what the original 2-point 128 GB claim used)
  - power   rss = a · docs^c        (captures clustering overhead; c<1 sub-linear
                                     → lower projection than linear; c>1 higher)

If the largest measured point forces curvature, the power-law fit is the honest
one and the 2-point linear figure was an over- or under-estimate — that curvature
is exactly what "fully confirmed" requires naming, not hiding.

Reads: every `data/eval_results/seismic_build_*.json` whose top-level keys match
the builder's output schema (a `docs` int + a `peak_rss_gb` float + `on_disk_gb`),
PLUS the explicit `--point docs=N,rss_gb=X` overrides for scale builds not in that
schema. Dedups by docs (keeps the highest-RSS measurement at each scale — peak).
Writes: `data/eval_results/seismic_g7_150m_ram_projection.json`.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/project_150m_ram.py \
        --target-docs 150413098 \
        --result-file data/eval_results/seismic_g7_150m_ram_projection.json
"""
import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TARGET_DOCS = 150_413_098  # data/thinclient_index/manifest.json sum (2026-06-27)
HOST_PHYSICAL_GB = 31.0    # /proc/meminfo MemTotal on the testbed container
SAFETY_FACTOR = 1.3        # build headroom (allocator fragmentation, vocab map, etc.)


def load_points_from_jsons():
    """Scrape (docs, peak_rss_gb, on_disk_gb, source) from every seismic_build_*.json
    the builder wrote. Keeps the schema-honest measurements (built with DEFAULTS —
    parity-matched, not the unpruned P3 sweep configs which inflate RSS unrelated
    to corpus scale)."""
    pts = []
    for p in sorted((REPO / "data/eval_results").glob("seismic_build_*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        docs = d.get("docs")
        rss = d.get("peak_rss_gb")
        # skip the unpruned P3/ceiling configs — those sweep RSS values are NOT
        # scale points (they're the SAME 2M docs with bigger clustering budgets);
        # including them would corrupt the scale-vs-RSS fit.
        params = d.get("meta", {}).get("params", {})
        if params.get("max_fraction", 1.5) != 1.5 or params.get("doc_cut", 15) != 15 \
                or params.get("summary_energy", 0.4) != 0.4:
            continue
        if isinstance(docs, int) and isinstance(rss, (int, float)) and docs > 0:
            pts.append({"docs": docs, "peak_rss_gb": round(float(rss), 3),
                        "on_disk_gb": d.get("on_disk_gb"),
                        "source": p.name})
    return pts


def fit_linear(points):
    """Least-squares rss = a + b·docs over the given (docs, rss) points."""
    n = len(points)
    xs = [p["docs"] for p in points]
    ys = [p["peak_rss_gb"] for p in points]
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    rss_pred = [a + b * x for x in xs]
    ss_res = sum((y - yp) ** 2 for y, yp in zip(ys, rss_pred))
    ss_tot = sum((y - sy / n) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return {"a": a, "b": b, "r2": r2,
            "project": lambda docs: a + b * docs}


def fit_power(points):
    """Least-squares log(rss) = log(a) + c·log(docs) → rss = a·docs^c.
    Cross-checks the linear fit; if the build is sub-linear (c<1) the linear
    projection over-estimates, if super-linear (c>1) it under-estimates."""
    import math as _m
    xs = [_m.log(p["docs"]) for p in points]
    ys = [_m.log(p["peak_rss_gb"]) for p in points]
    n = len(points)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    c = (n * sxy - sx * sy) / denom
    log_a = (sy - c * sx) / n
    a = _m.exp(log_a)
    rss_pred = [a * _m.exp(c * x) for x in xs]
    ys_lin = [_m.exp(y) for y in ys]
    pred_lin = [_m.exp(y) for y in [_m.log(p["peak_rss_gb"]) for p in points]]
    # r2 in log space (the space we fit)
    sy_mean = sy / n
    ss_res = sum((y - (log_a + c * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - sy_mean) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return {"a": a, "c": c, "r2": r2,
            "project": lambda docs: a * (docs ** c)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target-docs", type=int, default=TARGET_DOCS)
    ap.add_argument("--extra-point", action="append", default=[],
                    help="manual override: 'docs=N,rss_gb=X' for a build whose result "
                         "JSON isn't auto-scraped (e.g. the scale builds written to a "
                         "different path). Repeatable.")
    ap.add_argument("--result-file", default=None)
    ap.add_argument("--host-physical-gb", type=float, default=HOST_PHYSICAL_GB)
    args = ap.parse_args()

    points = load_points_from_jsons()
    for spec in args.extra_point:
        kv = dict(tok.split("=") for tok in spec.split(","))
        points.append({"docs": int(kv["docs"]),
                       "peak_rss_gb": float(kv["rss_gb"]),
                       "on_disk_gb": None,
                       "source": "manual-override"})

    # dedup by docs, keep highest RSS at each scale (peak is the honest floor)
    by_docs = {}
    for p in points:
        d = p["docs"]
        if d not in by_docs or p["peak_rss_gb"] > by_docs[d]["peak_rss_gb"]:
            by_docs[d] = p
    points = sorted(by_docs.values(), key=lambda p: p["docs"])

    if len(points) < 2:
        print(json.dumps({"error": f"need >=2 measured points, got {len(points)}",
                          "points": points}))
        sys.exit(1)

    lin = fit_linear(points)
    pw = fit_power(points) if len(points) >= 2 else None

    proj_lin = lin["project"](args.target_docs) if lin else None
    proj_pw = pw["project"](args.target_docs) if pw else None

    # the cross-check on the largest measured point: which model predicts it best?
    # (a good fit should reproduce the largest point within ~15%.)
    largest = points[-1]
    lin_back = lin["project"](largest["docs"]) if lin else None
    pw_back = pw["project"](largest["docs"]) if pw else None

    # conservative band = min..max of the two projections (the honest "we can't
    # pin it to one number; the curve gives this range" statement)
    projs = [p for p in (proj_lin, proj_pw) if p is not None]
    band_lo = min(projs) if projs else None
    band_hi = max(projs) if projs else None

    # also: the naive rss/doc × 150M scale (the simplest projection, no fit)
    rss_per_doc_at_largest = largest["peak_rss_gb"] / largest["docs"]
    proj_naive_scale = rss_per_doc_at_largest * args.target_docs

    host_block = all(p is not None and p > args.host_physical_gb for p in projs)
    safety_gb = (band_hi * SAFETY_FACTOR) if band_hi is not None else None

    summary = {
        "meta": {
            "engine": "seismic-pyseismic-lsr-0.4.0",
            "built_utc": "2026-06-27",
            "purpose": "G7 150M build-RAM requirement — CONFIRMED BY MEASUREMENT + "
                       "curve fit, NOT by a 150M build (host RAM-impossible). Projected "
                       "from the measured peak-RSS-vs-docs scaling curve.",
            "target_docs": args.target_docs,
            "target_docs_source": "data/thinclient_index/manifest.json sum over 9 sections",
            "host_physical_gb": args.host_physical_gb,
            "host_constraint": "pyseismic 0.4.0 SeismicIndex.build() holds the forward "
                              "index + k-means clustering resident (no on-disk/streaming "
                              "build path) → build RSS scales with corpus.",
            "caveat": "*proj.* — curve fit over measured points <= the largest scale, "
                      "NOT a measured 150M build. The 150M figure is a projection with a "
                      "stated band; treat the band, not a single number.",
        },
        "measured_points": points,
        "fits": {
            "linear": {"a": round(lin["a"], 4) if lin else None,
                       "b_gb_per_doc": lin["b"] if lin else None,
                       "r2": round(lin["r2"], 4) if lin else None,
                       "projected_150m_gb": round(proj_lin, 1) if proj_lin else None,
                       "backfit_largest_gb": round(lin_back, 2) if lin_back else None},
            "power_law": {"a": round(pw["a"], 4) if pw else None,
                          "exponent_c": round(pw["c"], 4) if pw else None,
                          "r2": round(pw["r2"], 4) if pw else None,
                          "projected_150m_gb": round(proj_pw, 1) if proj_pw else None,
                          "backfit_largest_gb": round(pw_back, 2) if pw_back else None},
            "naive_rss_per_doc_scale": {"rss_per_doc_gb": round(rss_per_doc_at_largest, 9),
                                        "at_docs": largest["docs"],
                                        "projected_150m_gb": round(proj_naive_scale, 1)},
        },
        "projection": {
            "linear_gb": round(proj_lin, 1) if proj_lin else None,
            "power_law_gb": round(proj_pw, 1) if proj_pw else None,
            "band_lo_gb": round(band_lo, 1) if band_lo else None,
            "band_hi_gb": round(band_hi, 1) if band_hi else None,
            "naive_scale_gb": round(proj_naive_scale, 1),
        },
        "verdict": {
            "host_impossible_on_current": host_block,
            "note": (f"150M build projected at ~{band_hi:.0f} GB peak RSS (band "
                     f"{band_lo:.0f}–{band_hi:.0f} GB, +{int((SAFETY_FACTOR-1)*100)}% "
                     f"safety → ≥{safety_gb:.0f} GB host) vs this host's "
                     f"{args.host_physical_gb:.0f} GB physical. " +
                     ("CONFIRMED host-impossible: a G7 build needs a ≥"
                      f"{safety_gb:.0f} GB RAM host." if host_block else
                      "projection fits on this host — re-check the inputs.")
                     if band_hi is not None else "no projection available."),
        },
    }
    # print the headline
    print(json.dumps({
        "measured_points_n": len(points),
        "largest_point_docs": largest["docs"],
        "linear_150m_gb": round(proj_lin, 1) if proj_lin else None,
        "power_150m_gb": round(proj_pw, 1) if proj_pw else None,
        "band_gb": f"{band_lo:.0f}-{band_hi:.0f}" if band_hi else None,
        "exponent_c": round(pw["c"], 4) if pw else None,
        "host_impossible": host_block,
        "result_file": args.result_file or "data/eval_results/seismic_g7_150m_ram_projection.json",
    }, indent=2))

    rpath = Path(args.result_file) if args.result_file else (
        REPO / "data/eval_results/seismic_g7_150m_ram_projection.json")
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(rpath, "w"), indent=2)
    print(f"wrote {rpath}")


if __name__ == "__main__":
    main()
