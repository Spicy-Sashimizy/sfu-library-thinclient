"""Fold-in plumbing (doc 10 `docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md`
§3 G3/G4): the write guard, the side root, the fold build (twin route with a
PINNED token-id map), the composed-manifest repoint and the operator publish.

Nothing here writes the served index. A fold of base shard s writes only to

    <fold_root>/shard{s}/fold{k}/          (sentinel `.fold_work_dir`)
        fold.jsonl                         scratch input (deleted after build unless kept)
        fold.index.seismic                 stock build (deleted after c1a unless kept)
        fold.mmap/                         c1a f16 layout (the NEXT fold's input)
        fold.dotvbyte.v2.mmap/             served forward format
        fold.json                          state + build info + evidence
    <fold_root>/manifests/shard_manifest.fold_s{s}_k{k}.json

and "swap-in" is a MANIFEST repoint: the composed manifest names s' at the
side path in s's position; the base shard files stay where they are, untouched,
as the rollback. `publish_fold` (CLI `publish-fold --shard s --fold k
--confirm`) is the only step that makes a fold visible to serving, and it is an
operator step, never automatic.

Guard (`check_target` / `check_writable`, the rule list of
`docs/infrastructure/INDEX_WRITE_PROTECTION.md` §3 item 1): refuse any
canonical path inside `<repo>/data/`, `/var/tmp/seismic_stage`, or any
`mmap_dir` named by the served or staged shard manifests; anything not
strictly under the fold root; any path whose components are symlinks; a
non-local filesystem; a directory holding a symlink or a hard-linked file;
a directory without its own `.fold_work_dir` sentinel naming its canonical
path. Every rule has a unit test on a tmp tree
(`scripts/tests/test_foldin_guard.py`).

Baseline (`baseline_snapshot` / `baseline_diff`): size + mtime of every file
under `data/seismic_150m`, `data/thinclient_index`, `/var/tmp/seismic_stage`
before and after every fold build and every publish; any CHANGED or new file
aborts at once, a MISSING file (9p stat transient) is re-checked 5 times over
~2 min first (the rule of the closed in-place bench).

Pinned token map (G1 consequence, `spike/delta_ingest/TWIN_DRIFT_BASELINE_FINDINGS.md`):
`build_fold` refuses to run without `token_map_dir`; the build gets
`input_token_to_id_map` = that dir's `token_to_id_map.bin`, extended (ids
appended in sorted token order) by any token of the folded delta docs that the
map lacks (the fork indexes `token_to_id_mapping[&t]` and would panic). The
number of appended tokens is recorded; its effect on parity is UNMEASURED.

Dials only, same code on every profile (doc 10 §7): fold threads =
`profile.seismic_threads`, dump workers, `os.nice` via the profile, scratch
kept or deleted.
"""
from __future__ import annotations

import json
import os
import stat
import struct
import time
from dataclasses import dataclass, field
from multiprocessing import Pool
from pathlib import Path

from .base import REPO_ROOT, BaseIndex
from .ledger import IngestLedger
from .routing import route_shard

FOLD_ROOT_DEFAULT = Path("/home/vscode/work/delta_ingest/foldin")
SENTINEL = ".fold_work_dir"
STAGE_DIR = Path("/var/tmp/seismic_stage")
STAGED_MANIFEST = STAGE_DIR / "staged_manifest.json"
LOCAL_FS = ("ext4", "ext3", "xfs", "btrfs", "overlay", "tmpfs", "f2fs", "zfs")
BASELINE_IGNORE = {"meta.sqlite-wal", "meta.sqlite-shm", "staged_manifest.json", ".staged_ok"}

FOLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS folds (shard INTEGER NOT NULL, fold INTEGER NOT NULL, state TEXT NOT NULL,
  created REAL, snapshot REAL, published REAL, dir TEXT, manifest TEXT, info TEXT,
  PRIMARY KEY (shard, fold));
CREATE TABLE IF NOT EXISTS fold_members (shard INTEGER NOT NULL, fold INTEGER NOT NULL, id TEXT NOT NULL,
  staged_at REAL, PRIMARY KEY (shard, fold, id));
"""


class FoldGuardError(RuntimeError):
    pass


class BaselineChanged(RuntimeError):
    pass


def fold_origin(shard: int, fold: int) -> str:
    return f"fold:{int(shard)}:{int(fold)}"


def fold_dir(fold_root: Path, shard: int, fold: int) -> Path:
    return Path(fold_root) / f"shard{int(shard)}" / f"fold{int(fold)}"


def _default_manifests() -> tuple[Path, ...]:
    out = [STAGED_MANIFEST]
    env = os.environ.get("SFU_SEISMIC_SHARD_MANIFEST", "")
    if env:
        p = Path(env)
        out.append(p if p.is_absolute() else REPO_ROOT / p)
    from .base import SHARD_MANIFEST_LADDER
    out.extend(SHARD_MANIFEST_LADDER)
    return tuple(out)


@dataclass
class GuardConfig:
    """Everything the guard compares against. Defaults are the real host
    paths; tests pass tmp trees for every field."""
    fold_root: Path = FOLD_ROOT_DEFAULT
    repo_data: Path = REPO_ROOT / "data"
    stage_dir: Path = STAGE_DIR
    manifests: tuple = field(default_factory=_default_manifests)
    repo_root: Path = REPO_ROOT
    mounts_text: str | None = None

    def protected_roots(self) -> list[Path]:
        roots = [Path(self.repo_data), Path(self.stage_dir)]
        for m in self.manifests:
            for d in _manifest_mmap_dirs(Path(m)):
                roots.append(d if d.is_absolute() else Path(self.repo_root) / d)
        return [_canon(r) for r in roots]


def _manifest_mmap_dirs(manifest: Path) -> list[Path]:
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return []
    out: list[Path] = []

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k == "mmap_dir" and isinstance(x, str):
                    out.append(Path(x))
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(data)
    return out


def _canon(p: Path) -> Path:
    """Canonical path; for a path that does not exist yet, the canonical
    nearest existing ancestor plus the remaining components."""
    p = Path(os.path.abspath(p))
    tail: list[str] = []
    cur = p
    while not cur.exists() and cur != cur.parent:
        tail.append(cur.name)
        cur = cur.parent
    base = cur.resolve()
    for t in reversed(tail):
        base = base / t
    return base


def _inside(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def fs_type_of(p: Path, mounts_text: str | None = None) -> str | None:
    if mounts_text is None:
        try:
            mounts_text = Path("/proc/mounts").read_text()
        except OSError:
            return None
    best: tuple[int, str] | None = None
    s = str(p)
    for line in mounts_text.splitlines():
        f = line.split()
        if len(f) < 3:
            continue
        mp = f[1].replace("\\040", " ")
        if (s == mp or s.startswith(mp.rstrip("/") + "/") or mp == "/") and (best is None or len(mp) > best[0]):
            best = (len(mp), f[2])
    return best[1] if best else None


def check_target(path: Path, cfg: GuardConfig) -> Path:
    """Path-level rules for a target that may not exist yet. Returns the
    canonical path or raises FoldGuardError."""
    given = Path(os.path.abspath(path))
    canon = _canon(given)
    root = _canon(Path(cfg.fold_root))
    for r in cfg.protected_roots():
        if _inside(canon, r):
            raise FoldGuardError(f"refusing {canon}: inside protected root {r}")
    if not _inside(canon, root) or canon == root:
        raise FoldGuardError(f"refusing {canon}: not strictly under the fold root {root}")
    if canon != given:
        raise FoldGuardError(f"refusing {given}: a path component is a symlink (resolves to {canon})")
    cur = given
    while cur != root and cur != cur.parent:
        if cur.is_symlink():
            raise FoldGuardError(f"refusing {given}: {cur} is a symlink")
        cur = cur.parent
    fs = fs_type_of(canon, cfg.mounts_text)
    if fs not in LOCAL_FS:
        raise FoldGuardError(f"refusing {canon}: filesystem {fs!r} is not local")
    return canon


def check_writable(d: Path, cfg: GuardConfig) -> Path:
    """The gate for every write into an existing fold directory."""
    canon = check_target(d, cfg)
    if not canon.is_dir():
        raise FoldGuardError(f"refusing {canon}: not an existing directory")
    for dp, dns, fns in os.walk(canon):
        for name in dns + fns:
            p = Path(dp) / name
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                raise FoldGuardError(f"refusing {canon}: {p} is a symlink")
            if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                raise FoldGuardError(f"refusing {canon}: {p} has {st.st_nlink} hard links")
    try:
        s = json.loads((canon / SENTINEL).read_text())
    except (OSError, ValueError):
        raise FoldGuardError(f"refusing {canon}: no readable {SENTINEL} sentinel") from None
    if not isinstance(s, dict) or s.get("path") != str(canon):
        raise FoldGuardError(f"refusing {canon}: sentinel names {s.get('path') if isinstance(s, dict) else s!r}")
    return canon


def make_fold_dir(cfg: GuardConfig, shard: int, fold: int) -> Path:
    d = fold_dir(cfg.fold_root, shard, fold)
    canon = check_target(d, cfg)
    if canon.exists():
        raise FoldGuardError(f"refusing {canon}: fold dir already exists (fold numbers are never reused)")
    canon.mkdir(parents=True)
    (canon / SENTINEL).write_text(json.dumps({"path": str(canon), "shard": shard, "fold": fold,
                                              "created": time.time()}))
    return check_writable(canon, cfg)


# ── baseline ────────────────────────────────────────────────────────────────
def default_baseline_roots() -> list[Path]:
    return [REPO_ROOT / "data" / "seismic_150m", REPO_ROOT / "data" / "thinclient_index", STAGE_DIR]


def baseline_snapshot(roots: list[Path]) -> dict:
    files: dict[str, tuple[int, int]] = {}
    missing: dict[str, str] = {}
    for root in roots:
        for dp, _, fns in os.walk(root):
            for fn in fns:
                if fn in BASELINE_IGNORE:
                    continue
                p = os.path.join(dp, fn)
                try:
                    st = os.stat(p)
                    files[p] = (st.st_size, st.st_mtime_ns)
                except OSError as ex:
                    missing[p] = ex.strerror or str(ex.errno)
    return {"roots": [str(r) for r in roots], "files": files, "missing": missing, "taken": time.time()}


def baseline_diff(before: dict, after: dict) -> dict:
    b, a = before["files"], after["files"]
    # tuple() both sides: a snapshot read back from JSON holds lists, never == a fresh tuple
    changed = sorted(p for p in a if p in b and tuple(a[p]) != tuple(b[p]))
    new = sorted(p for p in a if p not in b and p not in before["missing"])
    missing = sorted(p for p in b if p not in a)
    return {"changed": changed, "new": new, "missing": missing,
            "n_files_before": len(b), "n_files_after": len(a)}


def baseline_check(before: dict, roots: list[Path] | None = None, *, retries: int = 5,
                   sleep_s: float = 24.0) -> dict:
    """Compare a fresh snapshot with `before`; CHANGED / new aborts at once,
    MISSING is re-checked `retries` times. Raises BaselineChanged."""
    roots = [Path(r) for r in (roots or before["roots"])]
    tries = 0
    diff = baseline_diff(before, baseline_snapshot(roots))
    while diff["missing"] and not (diff["changed"] or diff["new"]) and tries < retries:
        tries += 1
        time.sleep(sleep_s)
        diff = baseline_diff(before, baseline_snapshot(roots))
    diff["retries"] = tries
    if diff["changed"] or diff["new"] or diff["missing"]:
        raise BaselineChanged(json.dumps({k: (v[:20] if isinstance(v, list) else v) for k, v in diff.items()}))
    return diff


# ── ledger bookkeeping ──────────────────────────────────────────────────────
def ensure_fold_schema(ledger: IngestLedger) -> None:
    if not ledger.has_routes:
        raise ValueError("ledger has no route_shard column; run `cli.py backfill-routes` on it first")
    ledger.db.executescript(FOLD_SCHEMA)


def next_fold(ledger: IngestLedger, shard: int, fold_root: Path | None = None) -> int:
    """1 + the highest fold number of `shard` in the ledger and, with
    `fold_root`, among the existing `shard{s}/fold{k}` dirs (a build killed
    between `make_fold_dir` and its ledger row leaves a dir the ledger does
    not know; fold numbers are never reused, F5)."""
    ensure_fold_schema(ledger)
    row = ledger.db.execute("SELECT MAX(fold) FROM folds WHERE shard=?", (shard,)).fetchone()
    k = row[0] or 0
    if fold_root is not None:
        sd = Path(fold_root) / f"shard{int(shard)}"
        if sd.is_dir():
            for p in sd.iterdir():
                if p.name.startswith("fold") and p.name[4:].isdigit():
                    k = max(k, int(p.name[4:]))
    return k + 1


def fold_plan(ledger: IngestLedger, shard: int) -> dict:
    """The doc sets of a fold of `shard` from the ledger as it is now:
    `drop` = every id the ledger knows that routes to `shard` (any copy of
    it in the input shard is stale, deleted or re-added below); `add` = live
    docs routed to `shard` in a published generation (gen >= 1), with their
    stage time (the membership snapshot)."""
    db = ledger.db
    drop = {r[0] for r in db.execute("SELECT id FROM docs WHERE route_shard=?", (shard,))}
    for (i,) in db.execute("SELECT id FROM tombstones"):
        if route_shard(i, ledger.route_seed, ledger.route_shards) == shard:
            drop.add(i)
    add = [(i, t) for i, t in db.execute(
        "SELECT id, last_seen FROM docs WHERE route_shard=? AND status='live' AND generation>=1 "
        "ORDER BY id", (shard,))]
    return {"drop": drop, "add": add}


def mark_fold_ready(ledger: IngestLedger, shard: int, fold: int, evidence: dict) -> None:
    """The fold harness attaches its F2/F3 evidence; only a READY fold can be
    published."""
    ensure_fold_schema(ledger)
    row = ledger.db.execute("SELECT state, info FROM folds WHERE shard=? AND fold=?", (shard, fold)).fetchone()
    if row is None or row[0] not in ("built", "ready"):
        raise ValueError(f"fold {shard}/{fold} is {row[0] if row else 'unknown'}, not built")
    info = json.loads(row[1] or "{}")
    info["evidence"] = evidence
    with ledger.db:
        ledger.db.execute("UPDATE folds SET state='ready', info=? WHERE shard=? AND fold=?",
                          (json.dumps(info), shard, fold))


# ── build (twin route, pinned map) ──────────────────────────────────────────
def load_token_map(mmap_dir: Path) -> dict[str, int]:
    raw = (Path(mmap_dir) / "token_to_id_map.bin").read_bytes()
    off = 0
    (count,) = struct.unpack_from("<Q", raw, off)
    off += 8
    out = {}
    for _ in range(count):
        (slen,) = struct.unpack_from("<Q", raw, off)
        off += 8
        s = raw[off:off + slen].decode("utf-8")
        off += slen
        (v,) = struct.unpack_from("<Q", raw, off)
        off += 8
        out[s] = int(v)
    if off != len(raw):
        raise ValueError(f"{mmap_dir}/token_to_id_map.bin: trailing bytes")
    return out


def extend_token_map(pinned: dict[str, int], tokens) -> tuple[dict[str, int], list[str]]:
    """Append tokens the pinned map lacks, ids len.. in sorted order; existing
    ids never move."""
    extra = sorted(set(tokens) - set(pinned))
    out = dict(pinned)
    nxt = max(pinned.values(), default=-1) + 1
    for t in extra:
        out[t] = nxt
        nxt += 1
    return out, extra


_W: dict = {}


def _dump_init(src: str, drop: set):
    import numpy as np
    d = Path(src)
    tok = load_token_map(d)
    id2tok = [None] * (max(tok.values()) + 1)
    for s, i in tok.items():
        id2tok[i] = json.dumps(s, ensure_ascii=False) + ":"
    bits = np.arange(65536, dtype=np.uint16).view(np.float16).astype(np.float64)
    _W.update(dir=d, strings=str(d / "document_mapping_strings.bin"), id2tok=id2tok,
              vstr=[repr(float(x)) if np.isfinite(x) else "null" for x in bits], drop=drop)


def _dump_read(name: str, dtype, lo: int, n: int):
    """`n` items of a raw forward file from item `lo`, by read() (no mapping:
    mapped input pages count in every dump worker's RSS, doc 10 F4)."""
    import numpy as np
    return np.fromfile(_W["dir"] / name, dtype=dtype, count=n, offset=lo * np.dtype(dtype).itemsize)


def _dump_range(args):
    import numpy as np
    lo, hi, path = args
    o = _dump_read("forward_offsets.bin", np.uint64, lo, hi - lo + 1).astype(np.int64)
    m = _dump_read("document_mapping_offsets.bin", np.uint64, lo, hi - lo + 1).astype(np.int64)
    with open(_W["strings"], "rb") as fh:
        fh.seek(int(m[0]))
        blob = fh.read(int(m[-1] - m[0]))
    c_all = _dump_read("forward_components.bin", np.uint16, int(o[0]), int(o[-1] - o[0])).tolist()
    v_all = _dump_read("forward_values.bin", np.uint16, int(o[0]), int(o[-1] - o[0])).tolist()
    id2tok, vstr, drop = _W["id2tok"], _W["vstr"], _W["drop"]
    bo, bm = int(o[0]), int(m[0])
    kept = dropped = 0
    with open(path, "w", encoding="utf-8") as w:
        lines = []
        for i in range(hi - lo):
            did = blob[int(m[i]) - bm:int(m[i + 1]) - bm].decode("utf-8")
            if did in drop:
                dropped += 1
                continue
            a0, a1 = int(o[i]) - bo, int(o[i + 1]) - bo
            body = ",".join([id2tok[c] + vstr[v] for c, v in zip(c_all[a0:a1], v_all[a0:a1])])
            lines.append('{"id":' + json.dumps(did, ensure_ascii=False) + ',"vector":{' + body + "}}\n")
            kept += 1
            if len(lines) >= 20000:
                w.write("".join(lines))
                lines = []
        w.write("".join(lines))
    return kept, dropped


def dump_fold_jsonl(input_mmap_dir: Path, drop: set, add_lines: list[str], out: Path,
                    workers: int = 4, step: int = 60_000) -> dict:
    """Input shard rows (twin row order) minus `drop`, then the folded delta
    lines, into one SEISMIC jsonl. Values are the exact decimal of the stored
    f16 (the M9 / drift dump format)."""
    import numpy as np
    offs = np.memmap(Path(input_mmap_dir) / "forward_offsets.bin", dtype=np.uint64, mode="r")
    n = len(offs) - 1
    parts = out.parent / (out.name + ".parts")
    parts.mkdir(exist_ok=True)
    jobs = [(lo, min(lo + step, n), str(parts / f"part_{lo:09d}.jsonl")) for lo in range(0, n, step)]
    kept = dropped = 0
    t0 = time.time()
    with Pool(max(1, workers), initializer=_dump_init, initargs=(str(input_mmap_dir), drop)) as pool:
        for k, d in pool.imap(_dump_range, jobs):
            kept += k
            dropped += d
    with open(out, "wb") as w:
        for _, _, p in jobs:
            with open(p, "rb") as r:
                while True:
                    b = r.read(64 << 20)
                    if not b:
                        break
                    w.write(b)
            os.unlink(p)
        for ln in add_lines:
            w.write((ln + "\n").encode("utf-8"))
    parts.rmdir()
    return {"input_rows": n, "kept_base_rows": kept, "dropped_base_rows": dropped,
            "added_delta_rows": len(add_lines), "docs": kept + len(add_lines),
            "bytes": out.stat().st_size, "seconds": round(time.time() - t0, 1)}


def build_fold(delta_root: Path, ledger: IngestLedger, shard: int, input_mmap_dir: Path, *,
               token_map_dir: Path | None, cfg: GuardConfig, threads: int = 8, workers: int = 4,
               keep_scratch: bool = False, baseline_roots: list[Path] | None = None,
               fold: int | None = None) -> dict:
    """Build fold k of `shard` into its side dir and record it `built` in the
    ledger (never served until `mark_fold_ready` + `publish_fold`).
    `input_mmap_dir` = the f16 c1a layout of the shard as it is served now
    (the base twin, or the previous fold's `fold.mmap`)."""
    if token_map_dir is None:
        raise ValueError("build_fold needs token_map_dir: every fold rebuild pins input_token_to_id_map "
                         "(G1, TWIN_DRIFT_BASELINE_FINDINGS.md)")
    from .generation import build_seismic_shard
    from .records import DocRecord
    roots = baseline_roots if baseline_roots is not None else default_baseline_roots()
    before = baseline_snapshot(roots)
    ensure_fold_schema(ledger)
    k = fold or next_fold(ledger, shard, cfg.fold_root)
    d = make_fold_dir(cfg, shard, k)
    plan = fold_plan(ledger, shard)
    snap = time.time()
    with ledger.db:
        ledger.db.execute("INSERT INTO folds VALUES (?,?,?,?,?,?,?,?,?)",
                          (shard, k, "building", time.time(), snap, None, str(d), None, "{}"))
        ledger.db.executemany("INSERT INTO fold_members VALUES (?,?,?,?)",
                              [(shard, k, i, t) for i, t in plan["add"]])
    add_lines, tokens = [], set()
    ids = [i for i, _ in plan["add"]]
    for j in range(0, len(ids), 500):
        chunk = ids[j:j + 500]
        for (rec,) in ledger.db.execute(
                f"SELECT record FROM records WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            r = DocRecord.from_json(rec)
            line = r.seismic_line()
            if line:
                add_lines.append(line)
                tokens.update(t for t, w in (r.sparse_field or {}).items() if w > 0)
    pinned, extra = extend_token_map(load_token_map(Path(token_map_dir)), tokens)
    check_writable(d, cfg)
    jsonl = d / "fold.jsonl"
    dump = dump_fold_jsonl(Path(input_mmap_dir), plan["drop"], add_lines, jsonl, workers=workers)
    check_writable(d, cfg)
    info = build_seismic_shard(jsonl, d / "fold", threads,
                               build_kwargs={"input_token_to_id_map": pinned})
    info.update(dump=dump, token_map_dir=str(token_map_dir), token_map_size=len(pinned),
                token_map_appended=len(extra), token_map_appended_sample=extra[:20],
                input_mmap_dir=str(input_mmap_dir), origin=fold_origin(shard, k),
                members=len(plan["add"]), drop_ids=len(plan["drop"]))
    if not keep_scratch:
        for p in (jsonl, Path(f"{d / 'fold'}.index.seismic")):
            if p.exists():
                p.unlink()
    info["baseline"] = baseline_check(before, roots)
    state = "built" if info.get("format") == "dotvbyte_fixedu8_v2" else "failed"
    (d / "fold.json").write_text(json.dumps({"state": state, **info}, indent=1, default=str))
    with ledger.db:
        ledger.db.execute("UPDATE folds SET state=?, info=? WHERE shard=? AND fold=?",
                          (state, json.dumps(info, default=str), shard, k))
    return {"shard": shard, "fold": k, "state": state, "dir": str(d), **info}


# ── manifest repoint + operator publish ─────────────────────────────────────
def compose_fold_manifest(base_manifest: Path | None, shard: int, fold: int, fold_mmap_dir: Path,
                          n_docs: int, out: Path, cfg: GuardConfig,
                          forward_format: str = "dotvbyte_fixedu8_v2") -> Path:
    """Write a NEW manifest naming fold k of `shard` at its side path in the
    shard's position; every other record is copied verbatim. Never overwrites
    a file, never touches `base_manifest`. If `out` already exists with the
    same source and the same shard records (a publish killed after composing
    and re-run, F5), it is reused as is; any other existing `out` is refused."""
    check_target(out, cfg)
    if base_manifest is None or not Path(base_manifest).exists():
        raise ValueError(f"base shard manifest {base_manifest} not found")
    data = json.loads(Path(base_manifest).read_text())
    recs = [dict(r) for r in data.get("shards") or []]
    pos = [j for j, r in enumerate(recs) if r.get("shard", j) == shard and r.get("delta_generation") is None]
    if len(pos) != 1:
        raise ValueError(f"{base_manifest}: expected one record for shard {shard}, found {len(pos)}")
    j = pos[0]
    old = recs[j]
    recs[j] = {"shard": shard, "mmap_dir": str(fold_mmap_dir), "n_docs": int(n_docs),
               "forward_format": forward_format, "fold_origin": fold_origin(shard, fold),
               "fold_of": {"mmap_dir": old.get("mmap_dir"), "n_docs": old.get("n_docs"),
                           "fold_origin": old.get("fold_origin")}}
    if out.exists():
        try:
            prev = json.loads(out.read_text())
        except (OSError, ValueError):
            prev = None
        if (isinstance(prev, dict) and prev.get("composed_from") == str(base_manifest)
                and prev.get("shards") == recs):
            return out
        raise FoldGuardError(f"refusing {out}: composed manifests are never overwritten")
    out.parent.mkdir(parents=True, exist_ok=True)
    body = {k: v for k, v in data.items() if k != "shards"}
    body.update(plan=f"fold-in repoint: shard {shard} -> fold {fold} (doc 10 G3)",
                composed_from=str(base_manifest), n_shards=len(recs), shards=recs,
                built_utc=time.strftime("%Y-%m-%d %H:%M", time.gmtime()))
    tmp = out.with_name(out.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(body, indent=1))
    os.replace(tmp, out)
    return out


def prefault_dir(d: Path, chunk: int = 8 << 20) -> dict:
    """Operator prefault of a fold's served dir before the manifest repoint
    (doc 10 §4, `reload()` row): read every regular file once, sequentially,
    so s' is in the page cache when serving first touches it. Read-only."""
    t0 = time.perf_counter()
    n = files = 0
    buf = memoryview(bytearray(chunk))
    for dp, dns, fns in os.walk(d):
        dns.sort()
        for name in sorted(fns):
            p = Path(dp) / name
            if p.is_symlink() or not p.is_file():
                continue
            with open(p, "rb", buffering=0) as fh:
                try:
                    os.posix_fadvise(fh.fileno(), 0, 0, os.POSIX_FADV_SEQUENTIAL)
                except (AttributeError, OSError):
                    pass
                while True:
                    k = fh.readinto(buf)
                    if not k:
                        break
                    n += k
            files += 1
    return {"dir": str(d), "files": files, "bytes": n, "s": round(time.perf_counter() - t0, 3)}


def publish_fold(delta_root: Path, ledger: IngestLedger, base: BaseIndex, shard: int, fold: int, *,
                 confirm: bool, cfg: GuardConfig, base_shard_manifest: str | None = None,
                 ordinal_dir: str | None = None, baseline_roots: list[Path] | None = None,
                 prefault: bool = True) -> dict:
    """Operator step: repoint serving at fold k of `shard`. Without `confirm`
    it only reports what it would do. With `prefault` (default) the fold's
    served dir is read into the page cache before the repoint (doc 10 §4);
    the read is recorded under `prefault`."""
    from .generation import publish
    ensure_fold_schema(ledger)
    row = ledger.db.execute("SELECT state, dir, info, manifest FROM folds WHERE shard=? AND fold=?",
                            (shard, fold)).fetchone()
    if row is None:
        raise ValueError(f"no fold {shard}/{fold} in the ledger")
    state, d, info, prev_manifest = row[0], Path(row[1]), json.loads(row[2] or "{}"), row[3]
    if state not in ("ready", "published"):
        raise ValueError(f"fold {shard}/{fold} is {state}; only a READY fold (F2/F3 evidence attached) publishes")
    base_m = base_shard_manifest or ledger.active_fold_manifest() or base.shard_manifest(None)
    out = Path(cfg.fold_root) / "manifests" / f"shard_manifest.fold_s{shard}_k{fold}.json"
    plan = {"shard": shard, "fold": fold, "origin": fold_origin(shard, fold), "fold_dir": str(d),
            "mmap_dir": info.get("mmap_dir"), "composed_from": str(base_m), "manifest": str(out),
            "members": ledger.db.execute("SELECT COUNT(*) FROM fold_members WHERE shard=? AND fold=?",
                                         (shard, fold)).fetchone()[0]}
    if not confirm:
        return {"dry_run": True, **plan}
    roots = baseline_roots if baseline_roots is not None else default_baseline_roots()
    before = baseline_snapshot(roots)
    check_writable(d, cfg)
    mmap = Path(info.get("mmap_dir") or "")
    if not mmap.is_dir() or not _inside(_canon(mmap), _canon(d)):
        raise FoldGuardError(f"fold {shard}/{fold}: served dir {mmap} missing or outside {d}")
    plan["prefault"] = prefault_dir(mmap) if prefault else None
    if prev_manifest and Path(prev_manifest).exists():
        out = Path(prev_manifest)
    else:
        compose_fold_manifest(Path(base_m) if base_m else None, shard, fold, mmap,
                              int((info.get("dump") or {}).get("docs") or info.get("stages", {}).get("build", {}).get("docs") or 0),
                              out, cfg, info.get("format") or "dotvbyte_fixedu8_v2")
    origin = fold_origin(shard, fold)
    with ledger.db:
        marked = ledger.db.execute(
            "UPDATE docs SET seismic_origin=? WHERE id IN (SELECT d.id FROM docs d JOIN fold_members m "
            "ON m.id=d.id WHERE m.shard=? AND m.fold=? AND d.status='live' AND d.last_seen=m.staged_at)",
            (origin, shard, fold)).rowcount
        ledger.db.execute("UPDATE folds SET state='published', published=?, manifest=? WHERE shard=? AND fold=?",
                          (time.time(), str(out), shard, fold))
    pub = publish(delta_root, ledger, base, str(out), ordinal_dir)
    plan.update(marked_seismic_origin=marked, stamp=pub["stamp"],
                shard_manifest=pub.get("shard_manifest"),
                baseline=baseline_check(before, roots))
    return plan
