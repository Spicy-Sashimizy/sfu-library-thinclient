#!/usr/bin/env python3
"""
> **CLOSED KILLED 2026-06-26** — SEISMIC federated mmap took the slot; evidence for docs/archive/sparse_engine_project/

mmap-BMP spike — ZERO-DECODE (R3-v2) G1 consistency diff at persona scale.

The 1M G1 (compare_flat.py, 50/50) already proved the v2 layout matches stock on
small shards. This checks the SAME invariant on a real persona shard: does the
zero-decode flat path (BMP_LOAD=flat, bytemuck cast_slice + flat_block_score)
return byte-identical top-k to the stock load-into-RAM path (BMP_LOAD=file,
b_search_verbose + block_score) on the SAME .bmp source? Both readers are built
into the ONE v2 wheel (Backend::Stock is untouched upstream; Backend::Flat is
the v2 zero-decode path), so this is a clean apples-to-apples diff with no
second venv.

Run from repo root (throwaway venv with the v2 wheel):

    BMP_LOAD=flat MMAP_BMP_SITE=<venv>/lib/python3.11/site-packages \
      <venv>/bin/python3 spike/mmap_bmp/compare_zerodecode_persona.py \
        --shards /tmp/persona_bench/sections/med_bio/splade_00[0-3].bmp \
        --baseline spike/mmap_bmp/out \
        --flat-dir spike/mmap_bmp/persona_med_bio_zd
"""
import argparse, glob, json, os, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="/tmp/persona_bench/sections/med_bio/splade_00[0-3].bmp")
    ap.add_argument("--baseline", default="spike/mmap_bmp/out")
    ap.add_argument("--flat-dir", default="spike/mmap_bmp/persona_med_bio_zd")
    args = ap.parse_args()

    # Stock reader: import under BMP_LOAD unset (-> file/load-into-RAM).
    os.environ.pop("BMP_LOAD", None)
    import bmp as bmp_stock  # noqa: F401  (module imported once; backend chosen per-Searcher)

    base = json.load(open(f"{args.baseline}/baseline.json"))
    qvecs = json.load(open(f"{args.baseline}/qvecs.json"))
    k = base["meta"]["k"]
    ALPHA, BETA = 0.8, 1.0

    shards = sorted(glob.glob(args.shards))
    assert shards, f"no shards matched {args.shards}"
    assert len(shards) == 4, f"expected 4 shards, got {len(shards)}"
    print(f"{len(shards)} persona shards; {len(qvecs)} queries; k={k}", flush=True)

    # Per-shard name -> .bmflat path (pre-transcoded v2 by transcode step).
    flat_of = {}
    for sp in shards:
        base_name = os.path.basename(sp).replace(".bmp", ".bmflat")
        fp = os.path.join(args.flat_dir, base_name)
        assert os.path.exists(fp), f"missing v2 flat {fp} — transcode first"
        flat_of[sp] = fp

    mismatches, checked = 0, 0
    for sp in shards:
        fp = flat_of[sp]
        # Stock load-into-RAM reader (ground truth) — BMP_LOAD unset -> Backend::Stock.
        os.environ.pop("BMP_LOAD", None)
        s_stock = bmp_stock.Searcher(sp)
        # Zero-decode v2 reader — BMP_LOAD=flat -> Backend::Flat (read by __new__).
        os.environ["BMP_LOAD"] = "flat"
        s_flat = bmp_stock.Searcher(fp)

        for q, qv in qvecs.items():
            qv = {t: int(w) for t, w in qv.items()}
            ids_st, sc_st = s_stock.search(qv, k=k, alpha=ALPHA, beta=BETA)
            ids_fl, sc_fl = s_flat.search(qv, k=k, alpha=ALPHA, beta=BETA)
            checked += 1
            got_st = {"ids": list(ids_st), "scores": [round(float(x), 6) for x in sc_st]}
            got_fl = {"ids": list(ids_fl), "scores": [round(float(x), 6) for x in sc_fl]}
            if got_st != got_fl:
                mismatches += 1
                if mismatches <= 5:
                    print(f"  MISMATCH {os.path.basename(sp)} | {q[:40]!r}", flush=True)
                    # show where they diverge
                    for i, (a, b) in enumerate(zip(got_st["ids"], got_fl["ids"])):
                        if a != b:
                            print(f"    pos {i}: stock={a} flat={b}", flush=True)
                            break

    g1 = mismatches == 0 and checked > 0
    print("\n──────── G1 PERSONA (zero-decode vs stock) ────────")
    print(f"G1  {'PASS' if g1 else 'FAIL'}  ({checked - mismatches}/{checked} byte-identical)")
    print(f"   shards: {[os.path.basename(s) for s in shards]}")
    print("VERDICT:", "GREEN — zero-decode path faithful at persona scale"
          if g1 else "RED — zero-decode diverges from stock; layout/scorer wrong")


if __name__ == "__main__":
    main()
