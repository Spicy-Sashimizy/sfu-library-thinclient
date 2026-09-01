#!/usr/bin/env python3
"""Stage the setup-wizard / installer layer into the portable bundle.

Idempotent. Copies the Windows launcher + installer files to the bundle ROOT
(CRLF for .bat/.ps1 so they behave on Windows) and refreshes the serving files
touched by the search-queue work (web/ + the /health sequential flag in src/).
Run this after 05/06 whenever the installer or those serving files change, then
sync the changed files onto the USB.

    BUNDLE=/var/tmp/portable_socsci_bundle .venv/bin/python3 \\
        scripts/portable_socsci/07_windows_installer.py
"""
import os
import shutil
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUNDLE = os.environ.get("BUNDLE", "/var/tmp/portable_socsci_bundle")

ROOT_FILES = [
    ("scripts/portable_socsci/windows/SETUP.bat",           "SETUP.bat",           True),
    ("scripts/portable_socsci/windows/install_wizard.ps1",  "install_wizard.ps1",  True),
    ("scripts/portable_socsci/windows/space_assistant.ps1", "space_assistant.ps1", True),
    ("scripts/portable_socsci/windows/MOVE-BACK.bat",       "MOVE-BACK.bat",       True),
    ("scripts/portable_socsci/windows/START.bat",           "START.bat",           True),
]
RUNTIME_FILES = [
    ("web/search.js",                  "web/search.js",                  False),
    ("web/src/search.jsx",             "web/src/search.jsx",             False),
    ("web/lib/api.js",                 "web/lib/api.js",                 False),
    ("web/lib/interface_prefs.js",     "web/lib/interface_prefs.js",     False),
    ("src/sfu_library_mcp_http.py",    "src/sfu_library_mcp_http.py",    False),
]


def copy_one(src_rel: str, dst_rel: str, crlf: bool) -> int:
    src = os.path.join(REPO, src_rel)
    dst = os.path.join(BUNDLE, dst_rel)
    if not os.path.isfile(src):
        print(f"  SKIP (missing in repo): {src_rel}")
        return 0
    os.makedirs(os.path.dirname(dst) or BUNDLE, exist_ok=True)
    if crlf:
        with open(src, "rb") as fh:
            data = fh.read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        with open(dst, "wb") as fh:
            fh.write(data)
    else:
        shutil.copy2(src, dst)
    print(f"  staged: {dst_rel}")
    return 1


def main() -> None:
    if not os.path.isdir(BUNDLE):
        sys.exit(f"bundle not found: {BUNDLE} (set BUNDLE=...)")
    print(f"[07] staging installer + search-queue layer -> {BUNDLE}")
    n = sum(copy_one(a, b, c) for a, b, c in ROOT_FILES + RUNTIME_FILES)
    print(f"[07] {n} files staged. Sync these paths onto the USB next.")


if __name__ == "__main__":
    main()
