#!/usr/bin/env python3
"""Phase 5d — assemble the OS-neutral runtime skeleton into the bundle.

Lays down everything the drive needs that is NOT Windows-native-binary:

    $BUNDLE/
      source/                        (serving code: sfu_library_mcp_http.py + lib/)
      web/                        (the /app GUI; WEB_DIR = <root>/web at runtime)
      START.bat                   (double-click launcher, CRLF)
      regen_seismic_manifest.py   (repoints the seismic manifest to the drive)

What this does NOT place (Windows-native, produced by build_windows_runtime.ps1
on a real Windows host — see the design doc §7 phase-5b blocker):

    python/                       (relocatable CPython + CPU wheels)
    python/.../seismic.pyd        (maturin build of the cfg-gated fork)

After this + the Windows build, the drive is self-contained and START.bat is the
entry point. Idempotent; excludes tests/caches.

    .venv/bin/python3 scripts/portable_socsci/05_windows_stage.py

Env: BUNDLE (default /var/tmp/portable_socsci_bundle). REPO is this checkout.
"""
import os
import shutil
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUNDLE = os.environ.get("BUNDLE", "/var/tmp/portable_socsci_bundle")
WIN = os.path.join(REPO, "scripts", "portable_socsci", "windows")

SRC_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "tests", "test_*.py",
    ".pytest_cache")
WEB_IGNORE = shutil.ignore_patterns("__pycache__", "node_modules", "*.pyc")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def copy_tree(src, dst, ignore):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)
    return _du(dst)


def copy_crlf(src, dst):
    """Copy a text launcher converting LF -> CRLF (Windows cmd wants CRLF)."""
    with open(src, "r", newline="") as f:
        text = f.read()
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    with open(dst, "w", newline="") as f:
        f.write(text)


def _du(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def main():
    t0 = time.time()
    os.makedirs(BUNDLE, exist_ok=True)

    log("copying source/ (serving code, minus tests/caches)...")
    src_bytes = copy_tree(os.path.join(REPO, "source"),
                          os.path.join(BUNDLE, "src"), SRC_IGNORE)

    log("copying web/ (the /app GUI)...")
    web_bytes = copy_tree(os.path.join(REPO, "web"),
                          os.path.join(BUNDLE, "web"), WEB_IGNORE)

    log("placing START.bat (CRLF) + regen_seismic_manifest.py at bundle root...")
    copy_crlf(os.path.join(WIN, "START.bat"), os.path.join(BUNDLE, "START.bat"))
    shutil.copy2(os.path.join(WIN, "regen_seismic_manifest.py"),
                 os.path.join(BUNDLE, "regen_seismic_manifest.py"))

    present = {
        "thinclient_index": os.path.isdir(os.path.join(BUNDLE, "thinclient_index")),
        "seismic": os.path.isdir(os.path.join(BUNDLE, "seismic")),
        "models": os.path.isdir(os.path.join(BUNDLE, "models")),
        "src": os.path.isdir(os.path.join(BUNDLE, "src")),
        "web": os.path.isdir(os.path.join(BUNDLE, "web")),
        "START.bat": os.path.isfile(os.path.join(BUNDLE, "START.bat")),
    }
    still_needed = {
        "python/ (relocatable CPython + CPU wheels)":
            os.path.isdir(os.path.join(BUNDLE, "python")),
        "python/**/seismic.pyd (maturin build of cfg-gated fork)":
            bool(_find(os.path.join(BUNDLE, "python"), "seismic.pyd")),
    }

    report = {
        "bundle": BUNDLE,
        "src_gib": round(src_bytes / 2**30, 3),
        "web_gib": round(web_bytes / 2**30, 3),
        "present": present,
        "still_needed_on_windows": {k: ("PRESENT" if v else "MISSING")
                                    for k, v in still_needed.items()},
        "total_seconds": round(time.time() - t0, 1),
    }
    import json
    print(json.dumps(report, indent=2), flush=True)
    with open(os.path.join(BUNDLE, "_windows_stage_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    ready = all(present.values()) and all(still_needed.values())
    log("SKELETON STAGED." if not ready else "BUNDLE COMPLETE.")
    if not ready:
        log("Next: run build_windows_runtime.ps1 on a Windows host to add "
            "python/ + seismic.pyd (design §7).")


def _find(root, name):
    if not os.path.isdir(root):
        return None
    for dirpath, _dirs, files in os.walk(root):
        if name in files:
            return os.path.join(dirpath, name)
    return None


if __name__ == "__main__":
    main()
