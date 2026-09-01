"""The live memory dial — WI-3 of docs/infrastructure/OCI_FREE_TIER_RESIDENT_DEMO.md §3/§8.

Sets `MemoryHigh` (reclaim throttle, never OOM) on the serve's cgroup while it
runs, so a demo can walk the measured R1/R2 ladder live: the answers stay
bit-identical, only the time-to-answer moves (doc §3.2). Per §3.1 the dial is
`MemoryHigh=<rung>` plus a `MemoryMax=<rung + guard>` backstop; `MemorySwapMax=0`
is pinned in the unit file, not here, because the whole ladder was measured
swap-forbidden.

Two backends, one contract:

  * ``SystemdBackend`` — `systemctl set-property --runtime <unit> ...`, the
    production path on the OCI box (unit file: ``systemd/sfu-serve.service``).
  * ``CgroupBackend`` — writes ``memory.high`` / ``memory.max`` in a cgroup-v2
    directory directly, for hosts where the serve is not under systemd — and it
    doubles as the test seam (a tmpdir with fake ``memory.*`` files).

Neither backend exists in this dev container (PID 1 is not systemd and
/sys/fs/cgroup is mounted read-only — probed 2026-08-18), so nothing here
self-tests against a real kernel: the R1/R2-ladder-under-MemoryHigh
verification is deferred to the OCI Phase-5 dry run.

CLI (reads the same DEMO_DIAL_* env as the broker):
    .venv/bin/python3 scripts/demo_broker/dial.py status
    .venv/bin/python3 scripts/demo_broker/dial.py set 12
    .venv/bin/python3 scripts/demo_broker/dial.py off
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GB = 1024 ** 3


class DialError(RuntimeError):
    """A dial operation failed or was refused (bounds, missing backend, ...)."""


def _fmt_bytes(n: int | None) -> str | None:
    return None if n is None else f"{n / GB:.2f}G"


@dataclass(frozen=True)
class DialStatus:
    backend: str
    high_bytes: int | None
    max_bytes: int | None
    current_bytes: int | None
    swap_max_bytes: int | None

    def to_json(self) -> dict:
        return {
            "backend": self.backend,
            "memory_high": _fmt_bytes(self.high_bytes) or "off",
            "memory_max": _fmt_bytes(self.max_bytes) or "off",
            "memory_current": _fmt_bytes(self.current_bytes),
            "memory_swap_max": _fmt_bytes(self.swap_max_bytes),
            "high_bytes": self.high_bytes, "max_bytes": self.max_bytes,
            "current_bytes": self.current_bytes,
        }


class SystemdBackend:
    """`systemctl set-property --runtime` on the serve unit (doc §3.1).

    ``--runtime`` writes /run/systemd/system.control/ — the rung does not
    survive a reboot, which is what a demo dial wants."""

    name = "systemd"
    _INF = 2 ** 63 - 1

    def __init__(self, unit: str, runner=subprocess.run):
        self.unit = unit
        self._run = runner

    def _systemctl(self, *args: str) -> str:
        p = self._run(["systemctl", *args], capture_output=True, text=True)
        if p.returncode != 0:
            raise DialError(f"systemctl {' '.join(args[:2])} failed: "
                            f"{(p.stderr or p.stdout or '').strip()}")
        return p.stdout

    def set(self, high_bytes: int | None, max_bytes: int | None) -> None:
        props = [f"MemoryHigh={'infinity' if high_bytes is None else high_bytes}",
                 f"MemoryMax={'infinity' if max_bytes is None else max_bytes}"]
        self._systemctl("set-property", "--runtime", self.unit, *props)

    def status(self) -> DialStatus:
        out = self._systemctl(
            "show", self.unit, "-p", "MemoryHigh,MemoryMax,MemoryCurrent,MemorySwapMax")
        vals: dict[str, int | None] = {}
        for line in out.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if v in ("infinity", "") or not v.lstrip("-").isdigit():
                vals[k] = None
            else:
                n = int(v)
                vals[k] = None if n >= self._INF else n
        return DialStatus(self.name, vals.get("MemoryHigh"), vals.get("MemoryMax"),
                          vals.get("MemoryCurrent"), vals.get("MemorySwapMax"))


class CgroupBackend:
    """Direct cgroup-v2 writes for a serve not managed by systemd.

    ``dir`` is the serve's cgroup directory (contains ``memory.high`` etc.).
    A tmpdir with those files is the unit-test seam."""

    name = "cgroup"

    def __init__(self, cgroup_dir: str | os.PathLike):
        self.dir = Path(cgroup_dir)

    def _read(self, fname: str) -> int | None:
        p = self.dir / fname
        try:
            raw = p.read_text().strip()
        except OSError:
            return None
        return None if raw == "max" else int(raw)

    def _write(self, fname: str, value: int | None) -> None:
        p = self.dir / fname
        try:
            p.write_text("max" if value is None else str(value))
        except OSError as e:
            raise DialError(f"cannot write {p}: {e}") from e

    def set(self, high_bytes: int | None, max_bytes: int | None) -> None:
        if not (self.dir / "memory.high").exists():
            raise DialError(f"{self.dir} is not a cgroup-v2 memory dir "
                            "(no memory.high)")
        self._write("memory.max", max_bytes)
        self._write("memory.high", high_bytes)

    def status(self) -> DialStatus:
        return DialStatus(self.name, self._read("memory.high"),
                          self._read("memory.max"), self._read("memory.current"),
                          self._read("memory.swap.max"))


class MemoryDial:
    """Bounds-checked dial over a backend. All rungs in GB (float ok)."""

    def __init__(self, backend, min_gb: float, max_gb: float, guard_mb: int):
        self.backend = backend
        self.min_gb, self.max_gb = float(min_gb), float(max_gb)
        self.guard_bytes = int(guard_mb) * 1024 ** 2

    def set_high(self, gb: float) -> DialStatus:
        gb = float(gb)
        if not (self.min_gb <= gb <= self.max_gb):
            raise DialError(f"rung {gb}G outside [{self.min_gb}, {self.max_gb}]G "
                            "(DEMO_DIAL_MIN_GB/DEMO_DIAL_MAX_GB)")
        high = int(gb * GB)
        self.backend.set(high, high + self.guard_bytes)
        return self.backend.status()

    def off(self) -> DialStatus:
        self.backend.set(None, None)
        return self.backend.status()

    def status(self) -> DialStatus:
        return self.backend.status()


def make_dial(config) -> MemoryDial | None:
    """Build the dial the broker config asks for; None when disabled."""
    kind = config.dial_backend
    if kind == "systemd":
        backend = SystemdBackend(config.dial_unit)
    elif kind == "cgroup":
        if not config.dial_cgroup_dir:
            raise DialError("DEMO_DIAL_BACKEND=cgroup needs DEMO_DIAL_CGROUP_DIR")
        backend = CgroupBackend(config.dial_cgroup_dir)
    elif kind in ("", "off"):
        return None
    else:
        raise DialError(f"unknown DEMO_DIAL_BACKEND {kind!r} (systemd|cgroup|off)")
    return MemoryDial(backend, config.dial_min_gb, config.dial_max_gb,
                      config.dial_guard_mb)


def main(argv: list[str]) -> int:
    from config import CONFIG
    dial = make_dial(CONFIG)
    if dial is None:
        print("dial disabled (DEMO_DIAL_BACKEND=off)", file=sys.stderr)
        return 2
    cmd = argv[0] if argv else "status"
    if cmd == "status":
        st = dial.status()
    elif cmd == "set" and len(argv) == 2:
        st = dial.set_high(float(argv[1]))
    elif cmd == "off":
        st = dial.off()
    else:
        print(__doc__.split("CLI")[-1], file=sys.stderr)
        return 2
    print(json.dumps(st.to_json(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
