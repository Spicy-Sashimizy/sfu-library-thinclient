"""Run the Vale prose linter (if installed) on a paragraph and return its JSON
alerts. Vale supplies terminology, unit and numeral-style rules; see
docs/02_ARCHITECTURE.md. Absence of the binary is not an error: the stage is
skipped and reported as such.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def vale_available() -> bool:
    return shutil.which("vale") is not None


def run_vale(text: str, config_path: str | Path | None = None, timeout: int = 30) -> list[dict]:
    if not vale_available():
        return [{"skipped": "vale binary not found"}]
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        tmp = fh.name
    cmd = ["vale", "--output=JSON", "--no-exit"]
    if config_path:
        cmd += ["--config", str(config_path)]
    cmd.append(tmp)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        data = json.loads(proc.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return [{"error": f"vale failed: {e}"}]
    finally:
        Path(tmp).unlink(missing_ok=True)
    alerts: list[dict] = []
    for _file, items in data.items():
        for a in items:
            alerts.append({
                "check": a.get("Check"), "severity": a.get("Severity"),
                "message": a.get("Message"), "match": a.get("Match"),
                "line": a.get("Line"), "span": a.get("Span"),
            })
    return alerts
