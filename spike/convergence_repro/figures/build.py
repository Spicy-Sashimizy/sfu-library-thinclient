#!/usr/bin/env python3
"""Inject figures_data.json into figures_template.html -> a self-contained page.

    .venv/bin/python3 spike/convergence_repro/figures/build.py [out_path]

Default output: figures.html beside this script (gitignored build product;
the published artifact is built from it). Re-run extract.py first when a
cited result file changes.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "figures.html"
data = json.loads((HERE / "figures_data.json").read_text())
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
html = (HERE / "figures_template.html").read_text().replace("__DATA__", blob)
out.write_text(html)
print(out, len(html) // 1024, "KB")
