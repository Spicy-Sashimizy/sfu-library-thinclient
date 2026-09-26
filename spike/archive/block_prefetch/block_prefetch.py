"""Term-prefix block prefetch while typing (speculative-retrieval lever #4).

CLOSED MEASURED 2026-09-25 (archived from src/lib/thinclient/; nothing live
imports it): cold traverse -4.4% paired median vs a >= 20% bar, warm arm
slower. `docs/SPECULATIVE_RETRIEVAL_UPGRADES.md` §4 row 4.

Draft = the SPLADE terms of the text typed so far; speculated work = a kernel
read-ahead hint (`madvise(MADV_WILLNEED)` on an already-mapped range, else
`posix_fadvise(POSIX_FADV_WILLNEED)` on the file) over those terms' posting
lists inside each SEISMIC shard's `posting_lists.bin`; verify = the submitted
query reuses the terms, and its traverse finds the pages resident. Nothing is
computed or ranked here, so search output cannot change.

Granularity reachable from Python (see `docs/CODE_INVARIANTS.md`
§block_prefetch): pyseismic exposes no term -> block API, but each converted
`.mmap/` shard carries `token_to_id_map.bin` (token -> posting-list id) and a
`manifest.json` whose per-list component lengths, walked with the same
`_PL_LAYOUT` the F4 floor pin uses, give every list's exact byte range in
`posting_lists.bin`. So the unit is one WHOLE posting list per (term, shard),
split into its summary+navigation run (read unconditionally by the per-term
summary pass) and its packed-postings run (read only for surviving blocks).
Which blocks survive, and the forward-index pages they lead to (`forward_*`,
~85% of index bytes), depend on the traversal itself and are not plannable.

Public surface (the future `/api/speculate` handler calls `speculate`):

- `plan_prefetch(prefix_text) -> list[(path, offset, length)]`
- `issue_prefetch(plan) -> dict`
- `speculate(prefix_text) -> bool` (fire-and-forget; False when dropped/off)
- `configure(...)` binds the module to a live backend's shard dirs.

Gate `SFU_BLOCK_PREFETCH` (literal `1`, default OFF); byte cap per call
`SFU_BLOCK_PREFETCH_MAX_MB` (default 32). At most one prefetch in flight; a
call arriving while one runs is dropped, never queued. Every error is
swallowed (logged at debug)."""
from __future__ import annotations

import json
import logging
import os
import struct
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

GATE_ENV = "SFU_BLOCK_PREFETCH"
MAX_MB_ENV = "SFU_BLOCK_PREFETCH_MAX_MB"
DEFAULT_MAX_MB = 32.0
PREFETCH_TERMS = 64
PAGE = 4096
POSTINGS_FILE = "posting_lists.bin"
_NEG_MAP_RECHECK_S = 30.0


def enabled() -> bool:
    """True only when `SFU_BLOCK_PREFETCH` is the literal string `1`."""
    return os.environ.get(GATE_ENV, "") == "1"


def max_bytes_from_env() -> int:
    """Per-call byte cap from `SFU_BLOCK_PREFETCH_MAX_MB` (MB = 2**20). A
    missing, non-numeric or non-positive value falls back to the default."""
    raw = os.environ.get(MAX_MB_ENV, "")
    try:
        mb = float(raw) if raw.strip() else DEFAULT_MAX_MB
    except ValueError:
        mb = DEFAULT_MAX_MB
    if not mb > 0:
        mb = DEFAULT_MAX_MB
    return int(mb * (1 << 20))


def completed_words(prefix_text: str) -> str:
    """The part of a typed prefix whose words are finished: a trailing word
    with no whitespace after it is still being typed and is dropped. A prefix
    that is one unfinished word yields ''."""
    if not prefix_text:
        return ""
    if prefix_text[-1].isspace():
        return prefix_text.strip()
    head, sep, _ = prefix_text.rstrip().rpartition(" ")
    return head.strip() if sep else ""


def read_token_map(path: Path) -> dict[str, int]:
    """Decode `token_to_id_map.bin` (bincode, fixed-int little-endian: u64
    count, then per entry u64 strlen, utf-8 bytes, u64 id)."""
    raw = Path(path).read_bytes()
    off = 0
    (count,) = struct.unpack_from("<Q", raw, off)
    off += 8
    out: dict[str, int] = {}
    for _ in range(count):
        (slen,) = struct.unpack_from("<Q", raw, off)
        off += 8
        tok = raw[off:off + slen].decode("utf-8")
        off += slen
        (tid,) = struct.unpack_from("<Q", raw, off)
        off += 8
        out[tok] = tid
    if off != len(raw):
        raise ValueError(f"token map trailing bytes ({off} != {len(raw)})")
    return out


def list_extents(manifest: dict) -> tuple[list[tuple[int, int, int, int]], int]:
    """Per posting list `(postings_off, postings_len, summary_off, summary_len)`
    in `posting_lists.bin`, plus the total bytes the walk consumed. Same walk
    as `sharded_seismic_backend._postings_nav_runs`; the summary run spans the
    first navigation component to the end of the list."""
    from lib.thinclient.sharded_seismic_backend import _PL_LAYOUT
    cursor = 0
    out: list[tuple[int, int, int, int]] = []
    for plm in manifest.get("posting_lists", []):
        p_off = p_len = 0
        s_off = None
        for key, size, align, role in _PL_LAYOUT:
            if key == "component_ids_len" and not plm.get("has_component_ids"):
                continue
            cursor += (align - (cursor % align)) % align
            n = plm[key] * size
            if key == "packed_postings_words":
                p_off, p_len = cursor, n
            elif s_off is None:
                s_off = cursor
            cursor += n
        s_off = cursor if s_off is None else s_off
        out.append((p_off, p_len, s_off, cursor - s_off))
    return out, cursor


class ShardLayout:
    """One shard's token -> posting-list byte ranges. Refuses (raises) when
    the manifest walk does not consume `posting_lists.bin` exactly or the
    token map and manifest disagree on cardinality."""

    def __init__(self, mmap_dir: str | Path):
        d = Path(mmap_dir)
        self.path = str((d / POSTINGS_FILE).resolve())
        tok2id = read_token_map(d / "token_to_id_map.bin")
        manifest = json.loads((d / "manifest.json").read_text())
        extents, walked = list_extents(manifest)
        size = os.path.getsize(self.path)
        if walked != size:
            raise ValueError(f"{d}: layout walk {walked} B != {POSTINGS_FILE} {size} B")
        if len(extents) != len(tok2id):
            raise ValueError(f"{d}: {len(tok2id)} tokens vs {len(extents)} posting lists")
        self.extents = {tok: extents[i] for tok, i in tok2id.items()
                        if 0 <= i < len(extents)}
        self.size = size


def _page_span(off: int, length: int, file_size: int) -> tuple[int, int]:
    start = off - (off % PAGE)
    end = min(file_size, -(-(off + length) // PAGE) * PAGE)
    return start, max(0, end - start)


def _coalesce(ranges: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    out: list[list] = []
    for path, off, ln in sorted(ranges):
        if out and out[-1][0] == path and off <= out[-1][1] + out[-1][2]:
            out[-1][2] = max(out[-1][1] + out[-1][2], off + ln) - out[-1][1]
        else:
            out.append([path, off, ln])
    return [(p, o, n) for p, o, n in out]


def cap_plan(plan: list[tuple[str, int, int]], max_bytes: int) -> list[tuple[str, int, int]]:
    """Keep plan entries in order until `max_bytes`; the entry that crosses
    the cap is clipped to a page-aligned prefix, everything after is cut."""
    out: list[tuple[str, int, int]] = []
    left = max(0, int(max_bytes))
    for path, off, ln in plan:
        if left <= 0:
            break
        if ln <= left:
            out.append((path, off, ln))
            left -= ln
            continue
        clip = left - (left % PAGE)
        if clip > 0:
            out.append((path, off, clip))
        break
    return out


class BlockPrefetcher:
    """Planner + advisor over a fixed set of shard `.mmap/` dirs.

    `encode_fn(text) -> {token: weight}` defaults to the serving SPLADE query
    encoder (`lib.opensearch_retriever.encode_splade`). Shard layouts load
    lazily on the first plan; a shard whose layout cannot be read is skipped
    for the life of the object."""

    def __init__(self, shard_dirs, *, encode_fn=None, splade_model_path: str | None = None,
                 load_mode: str = "mmap", max_bytes: int | None = None,
                 n_terms: int = PREFETCH_TERMS):
        self.shard_dirs = [str(d) for d in (shard_dirs or []) if d]
        self.load_mode = load_mode
        self.max_bytes = max_bytes
        self.n_terms = n_terms
        self._encode_fn = encode_fn
        self._splade_model_path = splade_model_path
        self._layouts: list[ShardLayout] | None = None
        self._layout_lock = threading.Lock()
        self._slot = threading.Lock()
        self._fds: dict[str, int] = {}
        self._bases: dict[str, int] = {}
        self._neg_checked: float = -1e18
        self.stats = {"issued": 0, "dropped": 0, "errors": 0, "bytes": 0}

    def _cap(self) -> int:
        return self.max_bytes if self.max_bytes is not None else max_bytes_from_env()

    def active(self) -> bool:
        """Gate on, mmap load mode, at least one shard dir."""
        return enabled() and self.load_mode == "mmap" and bool(self.shard_dirs)

    def layouts(self) -> list[ShardLayout]:
        if self._layouts is None:
            with self._layout_lock:
                if self._layouts is None:
                    loaded = []
                    for d in self.shard_dirs:
                        try:
                            loaded.append(ShardLayout(d))
                        except Exception as exc:
                            log.debug("block_prefetch: shard %s skipped (%s)", d, exc)
                    self._layouts = loaded
        return self._layouts

    def _encode(self, text: str) -> dict[str, float]:
        if self._encode_fn is not None:
            return self._encode_fn(text) or {}
        from lib.opensearch_retriever import encode_splade
        model = (self._splade_model_path or os.environ.get("SFU_SPLADE_MODEL_PATH")
                 or str(Path(__file__).resolve().parents[3] / "models" / "splade_onnx_fused"))
        return encode_splade(text, model) or {}

    def top_terms(self, text: str) -> list[str]:
        """Tokens ranked by weight desc, ties by token; top `n_terms`."""
        sparse = self._encode(text)
        ranked = sorted(sparse.items(), key=lambda kv: (-float(kv[1]), kv[0]))
        return [t for t, w in ranked[:self.n_terms] if float(w) > 0]

    def plan_for_terms(self, terms: list[str], max_bytes: int | None = None
                       ) -> list[tuple[str, int, int]]:
        """Summary+navigation runs of every (term, shard) first, in term-weight
        order, then the packed-postings runs; page-aligned, capped, then
        coalesced and sorted by (path, offset)."""
        cap = self._cap() if max_bytes is None else max_bytes
        layouts = self.layouts()
        summary: list[tuple[str, int, int]] = []
        postings: list[tuple[str, int, int]] = []
        for tok in terms:
            for lay in layouts:
                ext = lay.extents.get(tok)
                if ext is None:
                    continue
                p_off, p_len, s_off, s_len = ext
                if s_len:
                    o, n = _page_span(s_off, s_len, lay.size)
                    summary.append((lay.path, o, n))
                if p_len:
                    o, n = _page_span(p_off, p_len, lay.size)
                    postings.append((lay.path, o, n))
        seen: set = set()
        ordered = []
        for r in summary + postings:
            if r not in seen:
                seen.add(r)
                ordered.append(r)
        return _coalesce(cap_plan(ordered, cap))

    def plan_prefetch(self, prefix_text: str) -> list[tuple[str, int, int]]:
        """Plan for the finished words of a typed prefix. [] when inactive,
        when no word is finished, or on any error."""
        if not self.active():
            return []
        try:
            text = completed_words(prefix_text)
            if not text:
                return []
            return self.plan_for_terms(self.top_terms(text))
        except Exception as exc:
            self.stats["errors"] += 1
            log.debug("block_prefetch: plan failed (%s)", exc)
            return []

    def _mapped_base(self, path: str) -> int | None:
        if path in self._bases:
            return self._bases[path]
        now = time.monotonic()
        if now - self._neg_checked < _NEG_MAP_RECHECK_S:
            return None
        self._neg_checked = now
        wanted = {lay.path for lay in (self._layouts or [])} | {path}
        try:
            with open("/proc/self/maps") as fh:
                for ln in fh:
                    parts = ln.rstrip("\n").split(None, 5)
                    if len(parts) < 6:
                        continue
                    p = parts[5].strip()
                    if p in wanted and p not in self._bases:
                        self._bases[p] = int(parts[0].split("-")[0], 16) - int(parts[2], 16)
        except OSError:
            pass
        return self._bases.get(path)

    def _fd(self, path: str) -> int:
        fd = self._fds.get(path)
        if fd is None:
            fd = os.open(path, os.O_RDONLY)
            self._fds[path] = fd
        return fd

    def _advise(self, plan: list[tuple[str, int, int]]) -> dict:
        issued = 0
        n_madv = n_fadv = 0
        for path, off, ln in cap_plan(plan, self._cap()):
            try:
                base = self._mapped_base(path)
                if base is not None and _madvise_willneed(base + off, ln):
                    n_madv += 1
                else:
                    os.posix_fadvise(self._fd(path), off, ln, os.POSIX_FADV_WILLNEED)
                    n_fadv += 1
                issued += ln
            except Exception as exc:
                self.stats["errors"] += 1
                log.debug("block_prefetch: advise %s@%d+%d failed (%s)", path, off, ln, exc)
        self.stats["issued"] += 1
        self.stats["bytes"] += issued
        return {"issued": True, "bytes": issued, "madvise": n_madv, "fadvise": n_fadv}

    def issue_prefetch(self, plan: list[tuple[str, int, int]]) -> dict:
        """Advise WILLNEED over `plan` (re-capped). Returns
        `{"issued": False, "reason": ...}` when gated off, inactive or when a
        prefetch is already in flight (dropped, not queued)."""
        if not self.active():
            return {"issued": False, "reason": "inactive"}
        if not plan:
            return {"issued": False, "reason": "empty"}
        if not self._slot.acquire(blocking=False):
            self.stats["dropped"] += 1
            return {"issued": False, "reason": "busy"}
        try:
            return self._advise(plan)
        except Exception as exc:
            self.stats["errors"] += 1
            log.debug("block_prefetch: issue failed (%s)", exc)
            return {"issued": False, "reason": "error"}
        finally:
            self._slot.release()

    def speculate(self, prefix_text: str) -> bool:
        """Fire-and-forget plan + issue on a daemon thread. Returns False
        without doing anything when inactive or when one is in flight."""
        if not self.active():
            return False
        if not self._slot.acquire(blocking=False):
            self.stats["dropped"] += 1
            return False

        def _run():
            try:
                plan = self.plan_prefetch(prefix_text)
                if plan:
                    self._advise(plan)
            except Exception as exc:
                self.stats["errors"] += 1
                log.debug("block_prefetch: speculate failed (%s)", exc)
            finally:
                self._slot.release()

        try:
            threading.Thread(target=_run, name="block-prefetch", daemon=True).start()
        except Exception:
            self._slot.release()
            return False
        return True

    def close(self) -> None:
        for fd in self._fds.values():
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()


def _madvise_willneed(addr: int, length: int) -> bool:
    """`madvise(addr, length, MADV_WILLNEED)` via libc; False on any failure
    (the caller then falls back to `posix_fadvise`)."""
    try:
        import ctypes
        import mmap as _mmap
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.madvise.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        libc.madvise.restype = ctypes.c_int
        return libc.madvise(ctypes.c_void_p(addr), ctypes.c_size_t(length),
                            _mmap.MADV_WILLNEED) == 0
    except Exception:
        return False


_default: BlockPrefetcher | None = None
_default_lock = threading.Lock()


def configure(*, backend=None, shard_dirs=None, encode_fn=None,
              splade_model_path: str | None = None, load_mode: str | None = None,
              max_bytes: int | None = None) -> BlockPrefetcher:
    """Bind the module-level prefetcher. Pass the live SEISMIC backend (its
    `_shard_mmap_dirs`, `load_mode` and `splade_model_path` are read) or
    explicit `shard_dirs`."""
    global _default
    if backend is not None:
        shard_dirs = shard_dirs or list(getattr(backend, "_shard_mmap_dirs", []) or [])
        load_mode = load_mode or getattr(backend, "load_mode", "stock")
        splade_model_path = splade_model_path or getattr(backend, "splade_model_path", None)
    with _default_lock:
        if _default is not None:
            _default.close()
        _default = BlockPrefetcher(shard_dirs or [], encode_fn=encode_fn,
                                   splade_model_path=splade_model_path,
                                   load_mode=load_mode or "mmap", max_bytes=max_bytes)
    return _default


def _from_env() -> BlockPrefetcher:
    """Shard dirs from `SFU_SEISMIC_SHARD_MANIFEST` (mmap records), preferring
    a `.staged_ok` copy under `SFU_SEISMIC_STAGE_DIR`; load mode from
    `SFU_SEISMIC_LOAD_MODE` (default mmap). No manifest -> inactive."""
    load_mode = os.environ.get("SFU_SEISMIC_LOAD_MODE", "mmap")
    dirs: list[str] = []
    manifest = os.environ.get("SFU_SEISMIC_SHARD_MANIFEST")
    if manifest and load_mode == "mmap":
        try:
            from lib.thinclient.sharded_seismic_backend import (_load_manifest,
                                                                _resolve_mmap_dir)
            stage = os.environ.get("SFU_SEISMIC_STAGE_DIR")
            for p in _load_manifest(manifest, load_mode="mmap"):
                d = _resolve_mmap_dir(p, "mmap")
                if d and stage and (Path(stage) / Path(d).name / ".staged_ok").is_file():
                    d = str(Path(stage) / Path(d).name)
                if d:
                    dirs.append(d)
        except Exception as exc:
            log.debug("block_prefetch: manifest %s unreadable (%s)", manifest, exc)
            dirs = []
    return BlockPrefetcher(dirs, load_mode=load_mode)


def get_prefetcher() -> BlockPrefetcher:
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = _from_env()
    return _default


def plan_prefetch(prefix_text: str) -> list[tuple[str, int, int]]:
    """Module-level `BlockPrefetcher.plan_prefetch` on the default instance."""
    if not enabled():
        return []
    return get_prefetcher().plan_prefetch(prefix_text)


def issue_prefetch(plan: list[tuple[str, int, int]]) -> dict:
    """Module-level `BlockPrefetcher.issue_prefetch` on the default instance."""
    if not enabled():
        return {"issued": False, "reason": "inactive"}
    return get_prefetcher().issue_prefetch(plan)


def speculate(prefix_text: str) -> bool:
    """Entry point for the (not yet wired) `/api/speculate` handler."""
    if not enabled():
        return False
    try:
        return get_prefetcher().speculate(prefix_text)
    except Exception:
        return False
