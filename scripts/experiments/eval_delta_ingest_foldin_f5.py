#!/usr/bin/env python3
r"""Delta-ingest fold-in F5 crash safety (doc 10 §6 row F5). Written 2026-10-08,
BEFORE any trial. Implementation readings: doc 10 addendum "2026-10-08 — F5
implementation readings" (committed before the first trial).

Spec row (doc 10 §6, frozen 2e674773), verbatim:

| **F5** | Crash safety | 50 SIGKILL trials at uniform-random times over the fold wall on a reduced fixture (first 1,000,000 docs of twin 0 + the fold delta routed into it; fixture builder to write), plus 10 kills inside `publish-fold` on the full shard-0 fold output | **60 / 60**: (i) served state after restart is exactly the pre-fold or the post-fold state — every live delta doc routed to *s* is servable from exactly one SEISMIC origin, checked by state inspection + 200 own-id lookups per trial; (ii) the G3 baseline is unchanged; (iii) re-running the fold after a kill completes and its output passes F2 Q-a against L | none (fixture) |

Kill criterion (doc 10 §8): "F5 has any trial with a served state that is
neither pre- nor post-fold" -> track KILLED. Such a trial is recorded, never
fixed-and-rerun silently.

Subcommands (run with /home/vscode/work/venv_local/bin/python3, cwd = repo):
  build-fixture  reduced base = the first N docs of twin 0 (cmp-verified local
                 copy, never the 9p mount) dumped in twin row order and built by
                 the twin route with the twin's pinned token map (f16 c1a +
                 dv-v2); a 1-shard base manifest naming it; a fixture root =
                 a copy of fixture_n8's ledger (sqlite backup, fold tables
                 emptied) + copies of its generation dirs, published once with
                 the reduced base manifest (the pre-fold state).
  calibrate      two clean folds of the reduced fixture: the fold wall W (kill
                 times are uniform on [0, W]), m_set (build-vs-build mean
                 overlap@10 of the two F arms per set) and Q-a of each clean
                 fold against L (readability of (iii) on this fixture).
  trials         the 50 fold-build kills, then the 10 publish-fold kills;
                 resumable (rows already in the rows file are kept).
  summarize      F5 verdict -> data/eval_results/delta_ingest_foldin_f5_<date>.json key F5.
  all            build-fixture (if absent) + calibrate (if absent) + trials + summarize.

Served state = what a restarted server would load from the delta root:
generations.json -> the composed manifest it names -> masks + livedocs
(`DeltaLayer`) + the federated SEISMIC backend over that manifest with the
per-shard origin filter attached, exactly as `retriever._seismic_backend`
wires it. It is compared as a digest (paths normalised to the root; stamp,
publish time and manifest file name left out) with the pre-fold digest taken
before the trial and the post-fold digest of a clean reference publish.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import random
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))
os.environ.setdefault("SFU_SEISMIC_PREFLOOR", "2")
for _k in ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR", "SFU_SEISMIC_SHARD_MANIFEST", "SFU_DELTA_ROOT",
           "SFU_THINCLIENT_ORDINALS", "SFU_SEISMIC_DELTA_GROUP", "SFU_SEISMIC_SHARD_FAULT_BOUNDARY"):
    os.environ[_k] = ""

E = os.environ.get
FOLD_ROOT_MAIN = Path("/home/vscode/work/delta_ingest/foldin")
FIXTURE_N8 = FOLD_ROOT_MAIN / "fixture_n8"
TWIN = Path("/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap")
QUERIES = FOLD_ROOT_MAIN / "f2" / "queries.json"
BASE_MANIFEST_FULL = Path("/home/vscode/work/inplace_update/m4/base_manifest.json")
WORK = Path(E("SFU_F5_WORK", str(FOLD_ROOT_MAIN / "f5")))
PY = sys.executable
SHARD = 0
SEED = 20261008
K = 200
HEAP_FACTOR = 0.8
N_LOOKUPS = 200
LOOKUP_K = 1000
SETS = ("QT", "QD")
TRIALS_FOLD = 50
TRIALS_PUBLISH = 10
MAX_REDRAWS = 25


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    print(f"{utc()} {msg}", flush=True)


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=1, default=str) + "\n")
    os.replace(tmp, path)


def git_head() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def overlap10(a: list, b: list) -> float:
    return len(set(a[:10]) & set(b[:10])) / 10


class Layout:
    """All paths of one F5 work tree (`WORK` for the real run, a tmp dir for the smoke)."""

    def __init__(self, work: Path):
        self.work = Path(work)
        self.base = self.work / "base"
        self.base_manifest = self.base / "manifest.json"
        self.fixture = self.work / "fixture"
        self.fold_root = self.work / "foldroot"
        self.previews = self.work / "previews"
        self.pub = self.work / "pub"
        self.logs = self.work / "logs"
        self.calib = self.work / "calibrate.json"
        self.rows = self.work / "rows.json"
        self.cache = self.work / "cache"


# ── fixture builder ─────────────────────────────────────────────────────────
def dump_prefix_jsonl(twin: Path, n: int, out: Path, workers: int, step: int = 50_000) -> dict:
    """The first `n` rows of the twin, twin row order, in the fold dump's format
    (`foldin._dump_range`, exact decimal of the stored f16)."""
    from multiprocessing import Pool
    from spike.delta_ingest import foldin
    offs = np.memmap(twin / "forward_offsets.bin", dtype=np.uint64, mode="r")
    n = min(n, len(offs) - 1)
    parts = out.parent / (out.name + ".parts")
    parts.mkdir(parents=True, exist_ok=True)
    jobs = [(lo, min(lo + step, n), str(parts / f"part_{lo:09d}.jsonl")) for lo in range(0, n, step)]
    t0 = time.time()
    with Pool(max(1, workers), initializer=foldin._dump_init, initargs=(str(twin), set())) as pool:
        kept = sum(k for k, _ in pool.imap(foldin._dump_range, jobs))
    with open(out, "wb") as w:
        for _, _, p in jobs:
            with open(p, "rb") as r:
                shutil.copyfileobj(r, w, 64 << 20)
            os.unlink(p)
    parts.rmdir()
    return {"rows": kept, "bytes": out.stat().st_size, "seconds": round(time.time() - t0, 1)}


def copy_root(src: Path, dst: Path, *, gens_from: Path | None = None, link_gens: bool = False,
              clear_folds: bool = False) -> list[int]:
    """Ledger by sqlite backup (source opened read-only) + the published
    generation dirs (copied, or symlinked to `gens_from`'s copies). Never
    writes `src`."""
    from spike.delta_ingest.generation import gen_name
    from spike.delta_ingest.ledger import IngestLedger
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    s = sqlite3.connect(f"file:{src / 'ledger.sqlite'}?mode=ro", uri=True)
    d = sqlite3.connect(str(dst / "ledger.sqlite"))
    s.backup(d)
    d.close()
    s.close()
    led = IngestLedger(dst / "ledger.sqlite")
    if not led.has_routes:
        led.backfill_routes()
    if clear_folds:
        from spike.delta_ingest import foldin
        foldin.ensure_fold_schema(led)
        with led.db:
            led.db.execute("DELETE FROM folds")
            led.db.execute("DELETE FROM fold_members")
            led.db.execute("UPDATE docs SET seismic_origin=NULL")
    gens = led.published_generations()
    led.close()
    for g in gens:
        srcg = (gens_from or src) / gen_name(g)
        if link_gens:
            os.symlink(srcg.resolve(), dst / gen_name(g))
        else:
            shutil.copytree(srcg, dst / gen_name(g), symlinks=False)
    return gens


def publish_root(root: Path, base_manifest: Path) -> dict:
    from spike.delta_ingest.base import BaseIndex
    from spike.delta_ingest.generation import publish
    from spike.delta_ingest.ledger import IngestLedger
    led = IngestLedger(root / "ledger.sqlite")
    base = BaseIndex(root / "no_index_root")
    try:
        out = publish(root, led, base, str(base_manifest), None)
    finally:
        led.close()
        base.close()
    return {"stamp": out["stamp"], "shard_manifest": out.get("shard_manifest")}


def cmd_build_fixture(a, L: Layout) -> dict:
    from spike.delta_ingest import foldin
    from spike.delta_ingest.generation import build_seismic_shard
    L.base.mkdir(parents=True, exist_ok=True)
    rec = {"created_utc": utc(), "n_base": a.n_base, "twin": str(TWIN), "fixture_source": str(FIXTURE_N8),
           "git_head": git_head()}
    jl = L.base / "base.jsonl"
    rec["dump"] = dump_prefix_jsonl(TWIN, a.n_base, jl, a.workers)
    t0 = time.time()
    info = build_seismic_shard(jl, L.base / "base", a.threads,
                               build_kwargs={"input_token_to_id_map": foldin.load_token_map(TWIN)})
    rec["build"] = {k: info.get(k) for k in ("stages", "format", "mmap_dir")}
    rec["build"]["seconds"] = round(time.time() - t0, 1)
    if info.get("format") != "dotvbyte_fixedu8_v2":
        raise SystemExit(f"reduced base build failed: {info.get('stages')}")
    for p in (jl, L.base / "base.index.seismic"):
        if p.exists():
            p.unlink()
    f16 = L.base / "base.mmap"
    dump_json(L.base_manifest, {"plan": f"F5 reduced base: first {rec['dump']['rows']} docs of twin 0",
                                "n_shards": 1, "shards": [{"shard": SHARD, "mmap_dir": info["mmap_dir"],
                                                           "n_docs": rec["dump"]["rows"],
                                                           "forward_format": "dotvbyte_fixedu8_v2"}]})
    rec["base_f16"] = str(f16)
    rec["base_dv"] = info["mmap_dir"]
    rec["generations"] = copy_root(FIXTURE_N8, L.fixture, clear_folds=True)
    rec["publish"] = publish_root(L.fixture, L.base_manifest)
    L.fold_root.mkdir(parents=True, exist_ok=True)
    dump_json(L.work / "fixture.json", rec)
    log(f"fixture built: {json.dumps({k: rec[k] for k in ('dump', 'publish')})}")
    return rec


# ── served state ────────────────────────────────────────────────────────────
def _norm(v, root: str):
    if isinstance(v, str):
        return v.replace(root, "<root>")
    if isinstance(v, list):
        return [_norm(x, root) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x, root) for k, x in v.items()}
    return v


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def served_state(root: Path) -> dict:
    """Digest of what a restart would serve from `root` (see module doc)."""
    root = Path(root)
    rs = str(root)
    gj = json.loads((root / "generations.json").read_text())
    man_path = gj.get("shard_manifest")
    man = json.loads(Path(man_path).read_text()) if man_path and Path(man_path).exists() else None
    recs = []
    for r in (man or {}).get("shards") or []:
        recs.append({"mmap_dir": _norm(str(Path(r["mmap_dir"]).resolve()) if Path(r["mmap_dir"]).is_absolute()
                                       else r["mmap_dir"], str(root.resolve())),
                     "n_docs": r.get("n_docs"), "delta_generation": r.get("delta_generation"),
                     "fold_origin": r.get("fold_origin")})
    mask = gj.get("mask") or {}
    ld = gj.get("livedocs")
    parts = {
        "manifest_present": man is not None,
        "manifest_named_exists": bool(man_path) and Path(man_path).exists(),
        "shards": recs,
        "generations": _norm([{"gen": g["gen"], "dir": g["dir"], "sections": g.get("sections"),
                               "seismic": g.get("seismic")} for g in gj.get("generations") or []], rs),
        "deleted": _h(sorted(mask.get("deleted") or [])),
        "superseded": _h(mask.get("superseded") or {}),
        "newest_seismic": _h(((mask.get("newest_by_leg") or {}).get("seismic")) or {}),
        "n_newest_seismic": len(((mask.get("newest_by_leg") or {}).get("seismic")) or {}),
        "livedocs": None if not ld else {k: ld.get(k) for k in ("crc32", "popcount", "nbits", "ordinal_space_id")},
        "base_shard_manifest": _norm(gj.get("base_shard_manifest"), rs),
    }
    origins = [int(r["delta_generation"]) if r["delta_generation"] is not None
               else (r["fold_origin"] or None) for r in recs]
    return {"digest": _h(parts), "parts": parts, "origins": origins, "stamp": gj.get("stamp"),
            "manifest": man_path}


def _mapping_hits(mmap_dir: Path, want: set, cache_dir: Path | None) -> set:
    """Ids of `want` present in a served shard's document mapping (cached per
    dir + mapping size/mtime; served files are immutable)."""
    offs_p, str_p = mmap_dir / "document_mapping_offsets.bin", mmap_dir / "document_mapping_strings.bin"
    st = (offs_p.stat().st_size, offs_p.stat().st_mtime_ns, str_p.stat().st_size, str_p.stat().st_mtime_ns)
    key = _h([str(mmap_dir.resolve()), st, _h(sorted(want))])[:24]
    cf = cache_dir / f"map_{key}.json" if cache_dir else None
    if cf and cf.exists():
        return set(json.loads(cf.read_text()))
    offs = np.fromfile(offs_p, dtype="<u8")
    blob = str_p.read_bytes()
    hits = set()
    for i in range(len(offs) - 1):
        s = blob[int(offs[i]):int(offs[i + 1])].decode("utf-8")
        if s in want:
            hits.add(s)
    if cf:
        dump_json(cf, sorted(hits))
    return hits


def ledger_view(root: Path, shard: int) -> dict:
    db = sqlite3.connect(f"file:{Path(root) / 'ledger.sqlite'}?mode=ro", uri=True)
    rows = db.execute("SELECT id, generation, seismic_origin FROM docs WHERE status='live' AND generation>=1 "
                      "AND route_shard=? ORDER BY id", (shard,)).fetchall()
    db.close()
    return {"ids": [r[0] for r in rows], "gen": {r[0]: int(r[1]) for r in rows},
            "seismic_origin": {r[0]: r[2] for r in rows if r[2]}}


def origin_check(root: Path, shard: int, state: dict, cache_dir: Path | None) -> dict:
    """State inspection: for every live delta doc routed to `shard`, the served
    positions that hold it physically (document mappings of position `shard`
    and of every delta position; base positions != shard cannot hold an id
    routed to `shard`, G2) and the positions that keep it after the product
    per-shard filter. `kept_at` = the one origin serving it, or a failure."""
    from lib.thinclient.delta_layer import DeltaLayer
    lv = ledger_view(root, shard)
    want = set(lv["ids"])
    man = json.loads(Path(state["manifest"]).read_text())["shards"]
    origins = state["origins"]
    phys: dict[str, list[int]] = {i: [] for i in want}
    for pos, r in enumerate(man):
        if origins[pos] is None and r.get("shard", pos) != shard:
            continue
        md = Path(r["mmap_dir"])
        md = md if md.is_absolute() else REPO / md
        for i in _mapping_hits(md, want, cache_dir):
            phys[i].append(pos)
    dl = DeltaLayer(root)
    try:
        f = dl.shard_result_filter(dl.shard_origins(len(man), state["manifest"]))
        per = [[] for _ in man]
        for i, ps in phys.items():
            for p in ps:
                per[p].append(("q", 1.0, i))
        kept = f(per)
    finally:
        dl.close()
    where: dict[str, list] = {i: [] for i in want}
    for pos, res in enumerate(kept):
        for _q, _s, i in res:
            where[i].append(origins[pos])
    n0 = sorted(i for i, w in where.items() if len(w) == 0)
    n2 = sorted(i for i, w in where.items() if len(w) > 1)
    return {"n_ids": len(want), "kept_once": sum(1 for w in where.values() if len(w) == 1),
            "kept_none": len(n0), "kept_twice_or_more": len(n2), "examples_none": n0[:5], "examples_multi": n2[:5],
            "kept_at": {i: (w[0] if len(w) == 1 else ("NONE" if not w else "MULTI")) for i, w in where.items()}}


def expected_origins(root: Path, shard: int, kind: str, fold_origin: str | None) -> dict:
    """pre: every live delta doc routed to `shard` at its delta generation;
    post: fold members (live, last_seen == staged_at) at the fold origin, the
    rest at their generation."""
    lv = ledger_view(root, shard)
    exp = dict(lv["gen"])
    if kind == "post":
        k = int(fold_origin.split(":")[2])
        db = sqlite3.connect(f"file:{Path(root) / 'ledger.sqlite'}?mode=ro", uri=True)
        moved = {r[0] for r in db.execute(
            "SELECT d.id FROM docs d JOIN fold_members m ON m.id=d.id WHERE m.shard=? AND m.fold=? "
            "AND d.status='live' AND d.last_seen=m.staged_at", (shard, k))}
        db.close()
        exp.update({i: fold_origin for i in moved if i in exp})
    return exp


def open_served(root: Path, positions: set | None = None) -> dict:
    """The served SEISMIC leg of `root`: DeltaLayer + one MmapSeismicIndex per
    needed position (product loader) + the product per-shard filter."""
    import seismic
    from lib.thinclient.delta_layer import DeltaLayer
    from lib.thinclient.sharded_seismic_backend import _load_manifest, _load_one_shard
    dl = DeltaLayer(root)
    man = dl.shard_manifest_path()
    paths = _load_manifest(man, load_mode="mmap")
    origins = dl.shard_origins(len(paths), man)
    idx = {p: _load_one_shard(seismic, paths[p], "mmap") for p in range(len(paths))
           if positions is None or p in positions}
    return {"dl": dl, "paths": paths, "origins": origins, "idx": idx,
            "filter": dl.shard_result_filter(origins), "dtype": seismic.get_seismic_string()}


def served_search(sv: dict, terms: dict, k: int = K) -> list:
    from lib.thinclient.sharded_seismic_backend import _prepare_query
    qcomp, qvals, qc, kp = _prepare_query(terms, k, sv["dtype"], len(terms), k)
    per = [[] for _ in sv["paths"]]
    for p, ix in sv["idx"].items():
        per[p] = ix.search(query_id="q", query_components=qcomp, query_values=qvals, k=kp, query_cut=qc,
                           heap_factor=HEAP_FACTOR)
    return sv["filter"](per)


def close_served(sv: dict) -> None:
    sv["dl"].close()


def lookup_sample(root: Path, shard: int, n: int = N_LOOKUPS, seed: int = SEED) -> list:
    from spike.delta_ingest.records import DocRecord
    lv = ledger_view(root, shard)
    ids = random.Random(seed).sample(lv["ids"], min(n, len(lv["ids"])))
    db = sqlite3.connect(f"file:{Path(root) / 'ledger.sqlite'}?mode=ro", uri=True)
    out = []
    for i in ids:
        (rec,) = db.execute("SELECT record FROM records WHERE id=?", (i,)).fetchone()
        sp = DocRecord.from_json(rec).sparse_field or {}
        top = dict(sorted(((t, float(w)) for t, w in sp.items() if w > 0), key=lambda x: -x[1])[:64])
        out.append((i, top))
    db.close()
    return out


def own_lookups(root: Path, shard: int, sample: list, expected: dict) -> dict:
    """200 own-id lookups on the served leg: each sampled doc's own vector
    (top-64 terms) as the query, per-shard k = k' = LOOKUP_K (1000: at the E8
    k = 200 a quarter of the delta docs rank below heavier docs on their own
    terms — inner product, measured in the 2026-10-08 smoke); the doc must
    come back from exactly one position, the one `expected` names. A doc not
    returned at all is a `missed` lookup (compared with the reference state)."""
    st = served_state(root)
    pos_needed = {p for p, o in enumerate(st["origins"]) if o is not None}
    man = json.loads(Path(st["manifest"]).read_text())["shards"]
    pos_needed |= {p for p, r in enumerate(man) if st["origins"][p] is None and r.get("shard", p) == shard}
    sv = open_served(root, pos_needed)
    res = {"found_once_expected": 0, "missed": [], "double": [], "wrong_origin": []}
    try:
        for i, terms in sample:
            kept = served_search(sv, terms, LOOKUP_K)
            at = [sv["origins"][p] for p, r in enumerate(kept) if any(x[2] == i for x in r)]
            if not at:
                res["missed"].append(i)
            elif len(at) > 1:
                res["double"].append([i, at])
            elif at[0] != expected.get(i):
                res["wrong_origin"].append([i, at[0], expected.get(i)])
            else:
                res["found_once_expected"] += 1
    finally:
        close_served(sv)
    res["n"] = len(sample)
    return res


def inspect_state(root: Path, shard: int, pre: dict, post: dict | None, fold_origin: str | None,
                  sample: list, cache_dir: Path | None, ref_missed: dict | None = None) -> dict:
    """(i): PRE iff the digest equals the pre-fold digest, every live delta doc
    routed to `shard` is kept at exactly one origin and that origin is the pre
    expectation for all of them, and the lookups agree; POST likewise against
    the post-fold reference; else NEITHER."""
    st = served_state(root)
    oc = origin_check(root, shard, st, cache_dir)
    out = {"digest": st["digest"], "stamp": st["stamp"], "origins": st["origins"],
           "origin_check": {k: v for k, v in oc.items() if k != "kept_at"}}
    kind = "pre" if st["digest"] == pre["digest"] else ("post" if post and st["digest"] == post["digest"] else None)
    out["digest_matches"] = kind
    exp = expected_origins(root, shard, kind or "pre", fold_origin)
    mism = [i for i, o in oc["kept_at"].items() if o != exp.get(i)]
    out["origin_mismatch"] = len(mism)
    out["origin_mismatch_examples"] = [[i, oc["kept_at"][i], exp.get(i)] for i in mism[:5]]
    lk = own_lookups(root, shard, sample, exp)
    out["lookups"] = {k: (v if not isinstance(v, list) else {"n": len(v), "examples": v[:5]}) for k, v in lk.items()}
    lookups_ok = not lk["double"] and not lk["wrong_origin"]
    if ref_missed is not None and kind in ref_missed:
        lookups_ok = lookups_ok and sorted(lk["missed"]) == sorted(ref_missed[kind])
        out["lookups"]["missed_equal_to_reference"] = sorted(lk["missed"]) == sorted(ref_missed[kind])
    out["lookups_missed_ids"] = lk["missed"]
    ok = kind is not None and oc["kept_none"] == 0 and oc["kept_twice_or_more"] == 0 and not mism and lookups_ok
    out["state"] = kind.upper() if ok else "NEITHER"
    return out


# ── fold runs ───────────────────────────────────────────────────────────────
def fold_argv(L: Layout, threads: int, workers: int) -> list:
    return [PY, "-m", "spike.delta_ingest.cli", "fold-build", "--delta-root", str(L.fixture), "--shard", str(SHARD),
            "--fold-input", str(L.base / "base.mmap"), "--token-map-dir", str(TWIN), "--fold-root", str(L.fold_root),
            "--fold-workers", str(workers), "--profile", "desktop_gpu", "--seismic-threads", str(threads)]


def child_env(threads: int) -> dict:
    return dict(os.environ, OMP_NUM_THREADS=str(threads), RAYON_NUM_THREADS=str(threads), PYTHONPATH=str(REPO))


def run_child(argv: list, logf: Path, threads: int, kill_at: float | None = None) -> dict:
    """Run `argv` in its own session; with `kill_at`, SIGKILL its whole process
    group (the CLI, its dump workers and its Rust converter children at once)
    `kill_at` seconds after start."""
    logf.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(logf, "w") as fh:
        p = subprocess.Popen(argv, cwd=REPO, env=child_env(threads), stdout=fh, stderr=subprocess.STDOUT,
                             start_new_session=True)
        killed = False
        if kill_at is None:
            rc = p.wait()
        else:
            try:
                rc = p.wait(timeout=max(0.0, kill_at))
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                killed = True
                rc = p.wait()
                for _ in range(50):
                    try:
                        os.killpg(p.pid, 0)
                        time.sleep(0.1)
                    except ProcessLookupError:
                        break
    return {"rc": rc, "killed": killed, "wall_s": round(time.time() - t0, 2)}


def fold_rows(root: Path, shard: int) -> dict:
    db = sqlite3.connect(f"file:{Path(root) / 'ledger.sqlite'}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT fold, state, dir, info FROM folds WHERE shard=? ORDER BY fold", (shard,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    db.close()
    return {int(k): {"state": s, "dir": d, "info": json.loads(i or "{}")} for k, s, d, i in rows}


def fold_stage(fdir: Path, row: dict | None) -> str:
    """Which stage a killed build was in, from what it left on disk."""
    if not fdir.exists():
        return "before_mkdir"
    if row is None:
        return "after_mkdir_before_ledger_row"
    if (fdir / "fold.json").exists():
        return "after_fold_json" if row["state"] == "building" else "finished"
    if (fdir / "fold.dotvbyte.v2.mmap").exists():
        return "dotvbyte"
    if (fdir / "fold.mmap").exists():
        return "c1a_or_after"
    if (fdir / "fold.index.seismic").exists():
        return "c1a"
    if (fdir / "fold.jsonl.parts").exists():
        return "dump"
    if (fdir / "fold.jsonl").exists():
        return "build"
    return "plan_or_token_map"


def dir_sig(d: Path) -> str:
    out = []
    for dp, _dn, fns in os.walk(d):
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            st = os.stat(p)
            out.append([os.path.relpath(p, d), st.st_size, st.st_mtime_ns])
    return _h(sorted(out))


def preview(L: Layout, fold: int, tag: str) -> Path:
    spec_path = REPO / "scripts/experiments/eval_delta_ingest_foldin.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("foldin_harness", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from spike.delta_ingest import foldin
    out = L.previews / tag
    man = L.fold_root / "manifests" / f"f2_preview.fold_s{SHARD}_k{fold}.json"
    if man.exists():
        man.unlink()
    if out.exists():
        shutil.rmtree(out)
    mod.make_preview(L.fixture, SHARD, fold, L.fold_root, out, foldin.GuardConfig(fold_root=L.fold_root))
    return out


def arm_top10(root: Path, queries: dict) -> dict:
    """Federated SEISMIC leg of an arm (all positions), top-10 ids per query,
    the F2 harness's `fed` reading (per-shard filter, merge, filter_ids)."""
    from lib.thinclient.sharded_seismic_backend import _merge_topk
    sv = open_served(root, None)
    try:
        out = {}
        for s in SETS:
            rows = []
            for terms in queries[s]:
                kept = served_search(sv, {t: v for t, v in terms})
                rows.append([d for d, _ in sv["dl"].filter_ids(_merge_topk(kept, K))][:10])
            out[s] = rows
    finally:
        close_served(sv)
    return out


def load_queries(limit: int | None) -> dict:
    qs = json.loads(QUERIES.read_text())
    return {s: qs["encoded"][s][: limit or None] for s in SETS}


def mean_overlap(a: dict, b: dict) -> dict:
    return {s: round(float(np.mean([overlap10(x, y) for x, y in zip(a[s], b[s])])), 6) for s in SETS}


def q_a(f: dict, l: dict, m_set: dict) -> dict:
    ov = mean_overlap(f, l)
    bars = {s: round(min(0.99, m_set[s]) - 0.005, 6) for s in SETS}
    return {"overlap10_F_vs_L": ov, "bar_A": bars, "pass_A": all(ov[s] >= bars[s] for s in SETS),
            "pass_B_0p99": all(ov[s] >= 0.99 for s in SETS)}


def cmd_calibrate(a, L: Layout) -> dict:
    qs = load_queries(a.limit)
    rec = {"created_utc": utc(), "git_head": git_head(), "threads": a.threads, "workers": a.workers, "folds": []}
    l_top = arm_top10(L.fixture, qs)
    dump_json(L.cache / "L_top10.json", l_top)
    tops = []
    for j in range(2):
        before = set(fold_rows(L.fixture, SHARD))
        r = run_child(fold_argv(L, a.threads, a.workers), L.logs / f"calib_fold{j + 1}.log", a.threads)
        rows = fold_rows(L.fixture, SHARD)
        new = sorted(set(rows) - before)
        if r["rc"] != 0 or not new or rows[new[-1]]["state"] != "built":
            raise SystemExit(f"clean fold {j + 1} failed: {r} {L.logs / f'calib_fold{j + 1}.log'}")
        k = new[-1]
        pv = preview(L, k, f"calib{j + 1}")
        top = arm_top10(pv, qs)
        dump_json(L.cache / f"calib{j + 1}_top10.json", top)
        tops.append(top)
        rec["folds"].append({"fold": k, "wall_s": r["wall_s"], "stages": rows[k]["info"].get("stages"),
                             "dump": rows[k]["info"].get("dump"), "token_map_appended": rows[k]["info"].get("token_map_appended")})
    m = mean_overlap(tops[1], tops[0])
    rec["m_set"] = m
    rec["W_s"] = round(float(np.mean([f["wall_s"] for f in rec["folds"]])), 2)
    rec["clean_q_a"] = [q_a(t, l_top, m) for t in tops]
    rec["iii_readable"] = all(x["pass_A"] for x in rec["clean_q_a"])
    rec["reference_fold"] = rec["folds"][0]["fold"]
    sample = lookup_sample(L.fixture, SHARD)
    pre = served_state(L.fixture)
    rec["pre_digest"] = pre["digest"]
    lk = own_lookups(L.fixture, SHARD, sample, expected_origins(L.fixture, SHARD, "pre", None))
    rec["reference_lookups_pre"] = {k: (v if not isinstance(v, list) else len(v)) for k, v in lk.items()}
    rec["reference_missed_pre"] = lk["missed"]
    dump_json(L.calib, rec)
    log(f"calibrate: W={rec['W_s']} s m_set={m} clean Q-a={[x['pass_A'] for x in rec['clean_q_a']]}")
    return rec


# ── trials ──────────────────────────────────────────────────────────────────
def baseline_roots() -> list:
    from spike.delta_ingest import foldin
    return foldin.default_baseline_roots()


def g3_check(before: dict) -> dict:
    from spike.delta_ingest import foldin
    try:
        d = foldin.baseline_check(before)
        return {"unchanged": True, "n_files": d["n_files_after"], "retries": d["retries"]}
    except foldin.BaselineChanged as exc:
        return {"unchanged": False, "diff": str(exc)[:2000]}


def fold_trial(j: int, kill_at: float, L: Layout, a, calib: dict, l_top: dict, qs: dict, sample: list,
               pre: dict) -> dict:
    from spike.delta_ingest import foldin
    row = {"trial": f"fold-{j:02d}", "kind": "fold_build_kill", "kill_at_s": round(kill_at, 3), "start_utc": utc()}
    before_rows = set(fold_rows(L.fixture, SHARD))
    before_dirs = {p.name for p in (L.fold_root / f"shard{SHARD}").glob("fold*")} if (L.fold_root / f"shard{SHARD}").exists() else set()
    snap = foldin.baseline_snapshot(baseline_roots())
    r = run_child(fold_argv(L, a.threads, a.workers), L.logs / f"trial_fold{j:02d}_killed.log", a.threads, kill_at)
    row["run"] = r
    if not r["killed"]:
        row["finished_before_kill"] = True
        rows = fold_rows(L.fixture, SHARD)
        for k in sorted(set(rows) - before_rows):
            shutil.rmtree(rows[k]["dir"], ignore_errors=True)
        return row
    rows = fold_rows(L.fixture, SHARD)
    dirs = sorted(p for p in (L.fold_root / f"shard{SHARD}").glob("fold*") if p.name not in before_dirs)
    killed_dir = dirs[-1] if dirs else None
    kk = int(killed_dir.name[4:]) if killed_dir else None
    row["killed_fold"] = kk
    row["stage_hit"] = fold_stage(killed_dir, rows.get(kk)) if killed_dir else "before_mkdir"
    row["killed_row_state"] = rows.get(kk, {}).get("state") if kk else None
    row["inspect"] = inspect_state(L.fixture, SHARD, pre, None, None, sample, L.cache,
                                   {"pre": calib["reference_missed_pre"]})
    row["g3_after_kill"] = g3_check(snap)
    before_rerun = set(rows)
    rr = run_child(fold_argv(L, a.threads, a.workers), L.logs / f"trial_fold{j:02d}_rerun.log", a.threads)
    rows2 = fold_rows(L.fixture, SHARD)
    new = sorted(set(rows2) - before_rerun)
    row["rerun"] = dict(rr, fold=(new[-1] if new else None), state=(rows2[new[-1]]["state"] if new else None))
    row["rerun_completes"] = rr["rc"] == 0 and bool(new) and rows2[new[-1]]["state"] == "built"
    row["g3_after_rerun"] = g3_check(snap)
    if row["rerun_completes"]:
        k2 = new[-1]
        pv = preview(L, k2, f"trial{j:02d}")
        top = arm_top10(pv, qs)
        row["q_a"] = q_a(top, l_top, calib["m_set"])
        ref = json.loads((L.cache / "calib1_top10.json").read_text())
        row["overlap10_vs_clean_fold"] = mean_overlap(top, ref)
        row["after_rerun_state"] = served_state(L.fixture)["digest"] == pre["digest"]
        shutil.rmtree(pv, ignore_errors=True)
    for k in sorted(set(rows2) - before_rows):
        d = Path(rows2[k]["dir"])
        if d.exists():
            row.setdefault("removed_dirs", []).append([str(d), sum(f.stat().st_size for f in d.rglob("*") if f.is_file())])
            shutil.rmtree(d, ignore_errors=True)
    if killed_dir and killed_dir.exists():
        row.setdefault("removed_dirs", []).append([str(killed_dir), None])
        shutil.rmtree(killed_dir, ignore_errors=True)
    row["i_pass"] = row["inspect"]["state"] in ("PRE", "POST")
    row["ii_pass"] = row["g3_after_kill"]["unchanged"] and row["g3_after_rerun"]["unchanged"]
    row["iii_pass"] = bool(row["rerun_completes"] and row.get("q_a", {}).get("pass_A"))
    row["end_utc"] = utc()
    return row


def publish_argv(root: Path, fold: int, fold_root: Path, base_manifest: Path) -> list:
    return [PY, "-m", "spike.delta_ingest.cli", "publish-fold", "--delta-root", str(root), "--shard", str(SHARD),
            "--fold", str(fold), "--confirm", "--fold-root", str(fold_root),
            "--base-shard-manifest", str(base_manifest)]


def prep_publish_copy(master: Path, dst: Path, fold: int, base_manifest: Path, own_manifest: Path | None = None) -> dict:
    """A trial copy of the publish master: own ledger (backup), generation dirs
    symlinked to the master's copies, published once (pre-fold, own paths),
    fold `fold` marked READY (F2 evidence on record for that fold)."""
    from spike.delta_ingest import foldin
    from spike.delta_ingest.ledger import IngestLedger
    copy_root(master, dst, gens_from=master, link_gens=True)
    led = IngestLedger(dst / "ledger.sqlite")
    with led.db:
        led.db.execute("UPDATE folds SET state='built', published=NULL, manifest=NULL WHERE shard=? AND fold=?",
                       (SHARD, fold))
    foldin.mark_fold_ready(led, SHARD, fold, {"f5": "marked READY on a trial copy by the F5 harness",
                                              "f2": "fold 1 F2 PASS (federated, Reading A) 2026-10-04"})
    if own_manifest is not None:
        with led.db:
            led.db.execute("UPDATE folds SET manifest=? WHERE shard=? AND fold=?", (str(own_manifest), SHARD, fold))
    led.close()
    return publish_root(dst, base_manifest)


def publish_stage(root: Path, pre_stamp: str, fold: int) -> str:
    db = sqlite3.connect(f"file:{root / 'ledger.sqlite'}?mode=ro", uri=True)
    st = db.execute("SELECT state FROM folds WHERE shard=? AND fold=?", (SHARD, fold)).fetchone()[0]
    db.close()
    gj = json.loads((root / "generations.json").read_text())
    mans = sorted((root / "shard_manifests").glob("*.json")) if (root / "shard_manifests").exists() else []
    if gj.get("stamp") != pre_stamp:
        return "after_generations_json" + ("+trigger" if (root / "trigger.json").exists()
                                           and json.loads((root / "trigger.json").read_text()).get("stamp") == gj["stamp"] else "")
    if st == "published":
        return "after_ledger_commit" + ("+new_manifest" if len(mans) > 1 else "")
    return "before_ledger_commit (prefault / compose / baseline)"


def publish_trial(j: int, kill_at: float | None, P: dict, a, L: Layout, sample: list | None,
                  ref: dict | None) -> dict:
    from spike.delta_ingest import foldin
    tag = f"pub-{j:02d}" if kill_at is not None else "pub-ref"
    dst = L.pub / tag
    row = {"trial": tag, "kind": "publish_fold_kill" if kill_at is not None else "publish_reference",
           "kill_at_s": None if kill_at is None else round(kill_at, 3), "start_utc": utc()}
    prep = prep_publish_copy(P["master"], dst, P["fold"], P["base_manifest"], P.get("own_manifest"))
    row["compose"] = "pre-composed own manifest (shared one composed from other inputs)" if P.get("own_manifest") else "shared path"
    pre = served_state(dst)
    row["pre_stamp"], row["pre_digest"] = prep["stamp"], pre["digest"]
    if kill_at is None:
        row["missed_pre"] = own_lookups(dst, SHARD, sample, expected_origins(dst, SHARD, "pre", None))["missed"]
    fsig = dir_sig(P["fold_dir"])
    snap = foldin.baseline_snapshot(baseline_roots())
    r = run_child(publish_argv(dst, P["fold"], P["fold_root"], P["base_manifest"]),
                  L.logs / f"{tag}.log", a.threads, kill_at)
    row["run"] = r
    if kill_at is None:
        row["post"] = served_state(dst)
        row["post_digest"] = row["post"]["digest"]
        row["wall_s"] = r["wall_s"]
        row["ok"] = r["rc"] == 0
        row["missed_post"] = own_lookups(dst, SHARD, sample, expected_origins(dst, SHARD, "post", P["origin"]))["missed"]
        return row
    if not r["killed"]:
        row["finished_before_kill"] = True
        return row
    row["stage_hit"] = publish_stage(dst, prep["stamp"], P["fold"])
    row["inspect"] = inspect_state(dst, SHARD, pre, {"digest": ref["post_digest"]}, P["origin"], sample, L.cache,
                                   ref.get("missed"))
    row["g3_after_kill"] = g3_check(snap)
    rr = run_child(publish_argv(dst, P["fold"], P["fold_root"], P["base_manifest"]), L.logs / f"{tag}_rerun.log",
                   a.threads)
    after = served_state(dst)
    row["rerun"] = rr
    row["rerun_completes"] = rr["rc"] == 0
    row["after_rerun_is_post"] = after["digest"] == ref["post_digest"]
    row["fold_dir_unchanged"] = dir_sig(P["fold_dir"]) == fsig
    row["g3_after_rerun"] = g3_check(snap)
    row["i_pass"] = row["inspect"]["state"] in ("PRE", "POST")
    row["ii_pass"] = row["g3_after_kill"]["unchanged"] and row["g3_after_rerun"]["unchanged"]
    row["iii_pass"] = bool(row["rerun_completes"] and row["after_rerun_is_post"] and row["fold_dir_unchanged"])
    row["iii_q_a"] = "inherited: the published output is fold 1 itself (bytes unchanged), F2 Q-a PASS 2026-10-04"
    shutil.rmtree(dst, ignore_errors=True)
    row["end_utc"] = utc()
    return row


def publish_setup(a, L: Layout) -> dict:
    """The publish master: a copy of fixture_n8 (ledger + generation dirs) whose
    fold `a.publish_fold` is the full shard-0 fold output, published once."""
    master = L.pub / "master"
    if not (master / "generations.json").exists():
        L.pub.mkdir(parents=True, exist_ok=True)
        copy_root(Path(a.publish_source), master)
        publish_root(master, Path(a.publish_base_manifest))
    rows = fold_rows(master, SHARD)
    fr = rows.get(a.publish_fold)
    if not fr or fr["state"] not in ("built", "ready", "published"):
        raise SystemExit(f"publish master has no built fold {a.publish_fold}: {fr}")
    P = {"master": master, "fold": a.publish_fold, "fold_dir": Path(fr["dir"]),
         "fold_root": Path(a.publish_fold_root), "base_manifest": Path(a.publish_base_manifest),
         "origin": f"fold:{SHARD}:{a.publish_fold}", "own_manifest": None}
    from spike.delta_ingest import foldin
    shared = P["fold_root"] / "manifests" / f"shard_manifest.fold_s{SHARD}_k{a.publish_fold}.json"
    if shared.exists():
        info = fr["info"]
        n_docs = int((info.get("dump") or {}).get("docs") or info.get("stages", {}).get("build", {}).get("docs") or 0)
        cfg = foldin.GuardConfig(fold_root=P["fold_root"])
        try:
            foldin.compose_fold_manifest(P["base_manifest"], SHARD, a.publish_fold, Path(info["mmap_dir"]), n_docs,
                                         shared, cfg, info.get("format") or "dotvbyte_fixedu8_v2")
        except foldin.FoldGuardError:
            own = L.pub / "manifests" / f"shard_manifest.fold_s{SHARD}_k{a.publish_fold}.json"
            if not own.exists():
                foldin.compose_fold_manifest(P["base_manifest"], SHARD, a.publish_fold, Path(info["mmap_dir"]),
                                             n_docs, own, cfg, info.get("format") or "dotvbyte_fixedu8_v2")
            P["own_manifest"] = own
    return P


def cmd_trials(a, L: Layout) -> dict:
    calib = json.loads(L.calib.read_text())
    data = json.loads(L.rows.read_text()) if L.rows.exists() else {"rows": [], "started_utc": utc(), "seed": SEED}
    # resume: a previous invocation's stop is history, not a stop for this one (2026-10-09 fix)
    if data.get("stopped"):
        data.setdefault("resumes", []).append({"utc": utc(), "previous_stop": data.pop("stopped"),
                                               "previous_ended_utc": data.pop("ended_utc", None)})
    done = {r["trial"] for r in data["rows"] if not r.get("finished_before_kill")}
    # draws consumed per tag, incl. finished-before-kill redraws, so a resume reuses no kill time
    draws_by_tag = {}
    for r in data["rows"]:
        draws_by_tag[r["trial"]] = draws_by_tag.get(r["trial"], 0) + 1
    qs = load_queries(a.limit)
    l_top = json.loads((L.cache / "L_top10.json").read_text())
    sample = lookup_sample(L.fixture, SHARD)
    pre = served_state(L.fixture)
    if pre["digest"] != calib["pre_digest"]:
        raise SystemExit("fixture served state differs from the calibrated pre-fold state")
    rng = random.Random(SEED)
    deadline = calendar.timegm(time.strptime(a.deadline, "%Y-%m-%dT%H:%M:%SZ")) if a.deadline else None
    W = calib["W_s"]
    n_fold = a.n_fold if a.n_fold is not None else TRIALS_FOLD
    draws = [rng.uniform(0, W) for _ in range(n_fold + MAX_REDRAWS)]
    used, j = 0, 0
    while j < n_fold:
        if deadline and time.time() > deadline:
            data["stopped"] = "deadline"
            break
        tag = f"fold-{j:02d}"
        if tag in done:
            j += 1
            used += draws_by_tag[tag]
            continue
        if used >= len(draws):
            data["stopped"] = "out of redraws"
            break
        t = draws[used]
        used += 1
        row = fold_trial(j, t, L, a, calib, l_top, qs, sample, pre)
        data["rows"].append(row)
        dump_json(L.rows, data)
        log(f"{tag}: kill@{t:.1f}s stage={row.get('stage_hit')} i={row.get('i_pass')} ii={row.get('ii_pass')} "
            f"iii={row.get('iii_pass')} fbk={row.get('finished_before_kill', False)}")
        if row.get("finished_before_kill"):
            continue
        if row["inspect"]["state"] == "NEITHER":
            log(f"{tag}: SERVED STATE NEITHER PRE NOR POST (doc 10 §8 kill criterion) — recorded")
        j += 1
    n_pub = a.n_publish if a.n_publish is not None else TRIALS_PUBLISH
    if n_pub and not data.get("stopped"):
        P = publish_setup(a, L)
        ref = data.get("publish_reference")
        psample = lookup_sample(P["master"], SHARD)
        if not ref:
            rr = publish_trial(0, None, P, a, L, psample, None)
            if not rr["ok"]:
                raise SystemExit(f"reference publish failed: {rr['run']}")
            ref = {"post_digest": rr["post_digest"], "wall_s": rr["wall_s"],
                   "missed": {"pre": rr["missed_pre"], "post": rr["missed_post"]},
                   "post_parts": rr["post"]["parts"], "pre_digest_ref_copy": rr["pre_digest"]}
            data["publish_reference"] = ref
            shutil.rmtree(L.pub / "pub-ref", ignore_errors=True)
            dump_json(L.rows, data)
        prng = random.Random(SEED + 1)
        pdraws = [prng.uniform(0, ref["wall_s"]) for _ in range(n_pub + MAX_REDRAWS)]
        used, j = 0, 0
        while j < n_pub:
            if deadline and time.time() > deadline:
                data["stopped"] = "deadline"
                break
            tag = f"pub-{j:02d}"
            if tag in done:
                j += 1
                used += draws_by_tag[tag]
                continue
            if used >= len(pdraws):
                data["stopped"] = "out of redraws (publish)"
                break
            t = pdraws[used]
            used += 1
            row = publish_trial(j, t, P, a, L, psample, ref)
            data["rows"].append(row)
            dump_json(L.rows, data)
            log(f"{tag}: kill@{t:.2f}s stage={row.get('stage_hit')} i={row.get('i_pass')} ii={row.get('ii_pass')} "
                f"iii={row.get('iii_pass')} fbk={row.get('finished_before_kill', False)}")
            if row.get("finished_before_kill"):
                continue
            j += 1
    data["ended_utc"] = utc()
    dump_json(L.rows, data)
    return data


def summarize(L: Layout, out_path: Path, key: str, expect: tuple = (TRIALS_FOLD, TRIALS_PUBLISH)) -> dict:
    calib = json.loads(L.calib.read_text())
    data = json.loads(L.rows.read_text())
    trials = [r for r in data["rows"] if not r.get("finished_before_kill")]
    redraws = [r["trial"] for r in data["rows"] if r.get("finished_before_kill")]
    fold = [r for r in trials if r["kind"] == "fold_build_kill"]
    pub = [r for r in trials if r["kind"] == "publish_fold_kill"]
    passed = [r for r in trials if r.get("i_pass") and r.get("ii_pass") and r.get("iii_pass")]
    neither = [r["trial"] for r in trials if r.get("inspect", {}).get("state") == "NEITHER"]
    complete = len(fold) == expect[0] and len(pub) == expect[1]
    rec = {"item": "doc 10 §6 F5 crash safety", "date_utc": utc(), "git_head": git_head(),
           "script": "scripts/experiments/eval_delta_ingest_foldin_f5.py", "work": str(L.work),
           "rows_file": str(L.rows), "seed": SEED,
           "calibration": {k: calib.get(k) for k in ("W_s", "m_set", "clean_q_a", "iii_readable", "folds", "threads")},
           "publish_reference": data.get("publish_reference"),
           "n_fold_trials": len(fold), "n_publish_trials": len(pub), "redrawn_finished_before_kill": redraws,
           "passed": len(passed), "of": len(trials), "complete": complete,
           "i_fail": [r["trial"] for r in trials if not r.get("i_pass")],
           "ii_fail": [r["trial"] for r in trials if not r.get("ii_pass")],
           "iii_fail": [r["trial"] for r in trials if not r.get("iii_pass")],
           "neither_pre_nor_post": neither,
           "stages_hit": sorted({(r["kind"], r.get("stage_hit")) for r in trials}),
           "stopped": data.get("stopped"),
           "verdict": ("NOT COMPLETE" if not complete else
                       ("FAIL — KILL CRITERION (doc 10 §8): a served state neither pre- nor post-fold" if neither else
                        ("PASS" if len(passed) == len(trials) else
                         ("NOT READ: (iii) unreadable on this fixture (a clean fold fails Q-a)"
                          if not calib.get("iii_readable") else "FAIL")))),
           "rows": [{k: v for k, v in r.items() if k not in ("inspect",)} | {"state": r.get("inspect", {}).get("state")}
                    for r in data["rows"]]}
    full = json.loads(out_path.read_text()) if out_path.exists() else {}
    full[key] = rec
    dump_json(out_path, full)
    log(f"F5 summary: {rec['verdict']} {rec['passed']}/{rec['of']} neither={neither}")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build-fixture", "calibrate", "trials", "summarize", "all"])
    ap.add_argument("--work", default=str(WORK))
    ap.add_argument("--n-base", type=int, default=1_000_000)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None, help="queries per set (smoke only)")
    ap.add_argument("--n-fold", type=int, default=None)
    ap.add_argument("--n-publish", type=int, default=None)
    ap.add_argument("--publish-source", default=str(FIXTURE_N8))
    ap.add_argument("--publish-fold", type=int, default=1)
    ap.add_argument("--publish-fold-root", default=str(FOLD_ROOT_MAIN))
    ap.add_argument("--publish-base-manifest", default=str(BASE_MANIFEST_FULL))
    ap.add_argument("--deadline", default=None, help="UTC %%Y-%%m-%%dT%%H:%%M:%%SZ; no new trial after it")
    ap.add_argument("--out", default=None)
    ap.add_argument("--key", default="F5")
    a = ap.parse_args()
    L = Layout(Path(a.work))
    os.chdir(REPO)
    out = Path(a.out or REPO / f"data/eval_results/delta_ingest_foldin_f5_{time.strftime('%Y%m%d', time.gmtime())}.json")
    if a.cmd in ("build-fixture", "all") and not (L.work / "fixture.json").exists():
        cmd_build_fixture(a, L)
    if a.cmd in ("calibrate", "all") and not L.calib.exists():
        cmd_calibrate(a, L)
    if a.cmd in ("trials", "all"):
        cmd_trials(a, L)
    if a.cmd in ("summarize", "all"):
        exp = (a.n_fold if a.n_fold is not None else TRIALS_FOLD, a.n_publish if a.n_publish is not None else TRIALS_PUBLISH)
        summarize(L, out, a.key, exp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
