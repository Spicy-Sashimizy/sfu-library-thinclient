"""Ties every SFU_* env gate in product code to its row in docs/ENV_GATES.md.

Lifecycle: harness
Doc: docs/ENV_GATES.md

The codebase triage of 2026-10-11 found ~20 gates read by `source/` that the
"grep-able" index did not list, and rows for gates nothing read any more; no
check tied the two together, so the index drifted in both directions. These
checks make that drift fail the suite (added 2026-10-12):

  (a) every SFU_* name in a string literal (or f-string) of product code
      (`source/**/*.py` outside `source/tests/`, docstrings excluded) has a live row:
      it appears in backticks in the doc and not inside `~~...~~`. The dynamic
      `f"SFU_FEATURE_{key.upper()}"` read is expanded from the feature keys
      `load_config` iterates; any other dynamic prefix fails as unresolvable;
  (b) no name struck through in the doc (a retired gate) is read by product
      code, so a retired gate cannot come back silently, and no name is both
      struck and live, or struck twice;
  (c) every live documented name has a reader: a tracked non-Markdown file
      under `source/`, `scripts/`, `spike/` or `web/`, outside `archive/` and the
      test and vendor dirs, contains it (Markdown and JSON results records
      are not readers), or product code reads it, so a row cannot outlive
      its reader;
  (d) planted changes in a temporary tree trip (a) and (c).

Failures name every offender, so one run gives the whole list.
"""

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "ENV_GATES.md"
SRC = REPO / "source"

TOKEN_RE = re.compile(r"SFU_[A-Z0-9_]+")
STRIKE_RE = re.compile(r"~~(.+?)~~")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")

PRODUCT_EXCLUDED = ("tests",)
READER_ROOTS = ("source", "scripts", "spike", "web")
READER_EXCLUDED_PREFIXES = ("source/tests/", "scripts/tests/", "scripts/archive/",
                            "spike/archive/")
READER_EXCLUDED_SUFFIXES = (".md", ".json", ".jsonl")
READER_EXCLUDED_PARTS = ("vendor",)

FEATURE_PREFIX = "SFU_FEATURE_"


def _tokens(text):
    return {t for t in TOKEN_RE.findall(text) if not t.endswith("_")}


def feature_keys(src_root):
    """The keys `load_config` iterates to build `SFU_FEATURE_<KEY>` names,
    parsed (not imported: `load_config` loads `.env` into the environment)."""
    config = src_root / "lib" / "config.py"
    if not config.is_file():
        return set()
    tree = ast.parse(config.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "load_config"):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "default_features"
                            for t in node.targets)
                    and isinstance(node.value, ast.Dict)):
                return {k.value.upper() for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return set()


def _docstring_ids(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def product_reads(src_root):
    """Map every SFU_* name in product string literals to its `file:line`s,
    plus the dynamic prefixes this test cannot resolve."""
    reads, unresolved = {}, []
    keys = feature_keys(src_root)
    for path in sorted(src_root.rglob("*.py")):
        rel = path.relative_to(src_root)
        if rel.parts[0] in PRODUCT_EXCLUDED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstring_ids(tree)
        where_base = path.relative_to(src_root.parent).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                head = node.values[0] if node.values else None
                if (isinstance(head, ast.Constant) and isinstance(head.value, str)
                        and re.search(r"SFU_[A-Z0-9_]*_$", head.value)):
                    prefix = TOKEN_RE.findall(head.value)[-1]
                    where = f"{where_base}:{node.lineno}"
                    if prefix == FEATURE_PREFIX and keys:
                        for key in keys:
                            reads.setdefault(prefix + key, []).append(where)
                    else:
                        unresolved.append(f"{where} f-string prefix {prefix}")
                continue
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in skip):
                for tok in _tokens(node.value):
                    reads.setdefault(tok, []).append(f"{where_base}:{node.lineno}")
    return reads, unresolved


def doc_names(doc_path):
    """(live, struck, struck_twice): live = SFU_* names in backticks outside
    `~~...~~`; struck = names inside `~~...~~`."""
    live, struck, twice = set(), set(), set()
    for line in doc_path.read_text(encoding="utf-8").split("\n"):
        for region in STRIKE_RE.findall(line):
            for tok in _tokens(region):
                (twice if tok in struck else struck).add(tok)
        rest = STRIKE_RE.sub("", line)
        for span in BACKTICK_RE.findall(rest):
            live |= _tokens(span)
    return live, struck, twice


def _git_files(root):
    out = subprocess.run(["git", "ls-files", "-z", "--", *READER_ROOTS], cwd=root,
                         capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def reader_tokens(root, rel_paths):
    """Map SFU_* name -> reader files among `rel_paths` (text files only)."""
    found = {}
    for rel in rel_paths:
        if (rel.startswith(READER_EXCLUDED_PREFIXES) or rel.endswith(READER_EXCLUDED_SUFFIXES)
                or set(rel.split("/")) & set(READER_EXCLUDED_PARTS)):
            continue
        path = root / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        for tok in _tokens(data.decode("utf-8", errors="ignore")):
            found.setdefault(tok, []).append(rel)
    return found


def undocumented_reads(src_root, doc_path):
    reads, unresolved = product_reads(src_root)
    live, _, _ = doc_names(doc_path)
    missing = [f"{name}  (read at {', '.join(sorted(set(reads[name]))[:3])})"
               for name in sorted(reads) if name not in live]
    return missing, unresolved


def resurrected_gates(src_root, doc_path):
    reads, _ = product_reads(src_root)
    live, struck, twice = doc_names(doc_path)
    out = [f"{name} struck as retired but read at {', '.join(sorted(set(reads[name]))[:3])}"
           for name in sorted(struck & set(reads))]
    out += [f"{name} is both struck and live in the doc" for name in sorted(struck & live)]
    out += [f"{name} is struck more than once" for name in sorted(twice)]
    return out


def orphan_rows(root, rel_paths, doc_path, src_root=None):
    """Live doc names with no reader. Product reads (`src_root`, with the
    dynamic SFU_FEATURE_ names expanded) count as readers too."""
    live, _, _ = doc_names(doc_path)
    readers = set(reader_tokens(root, rel_paths))
    if src_root is not None:
        readers |= set(product_reads(src_root)[0])
    return sorted(name for name in live if name not in readers)


def test_feature_prefix_resolves_from_config():
    """The dynamic SFU_FEATURE_ read must resolve; an empty key set would make
    check (a) silently skip every feature flag."""
    assert feature_keys(SRC), (
        "could not find the `default_features` dict in source/lib/config.py "
        "load_config; update feature_keys() to the new shape")


def test_every_product_env_read_has_a_live_doc_row():
    missing, unresolved = undocumented_reads(SRC, DOC)
    assert not unresolved, (
        "product code builds SFU_* names this test cannot resolve; teach "
        "product_reads() the key source:\n  " + "\n  ".join(unresolved))
    assert not missing, (
        f"{len(missing)} SFU_* name(s) read by product code have no live row in "
        "docs/ENV_GATES.md (full name in backticks, not struck through):\n  "
        + "\n  ".join(missing))


def test_no_retired_gate_is_read_by_product_code():
    bad = resurrected_gates(SRC, DOC)
    assert not bad, (
        "docs/ENV_GATES.md retired-gate markup disagrees with product code; "
        "un-strike and document a gate that is read again, or remove the read:\n  "
        + "\n  ".join(bad))


def test_every_live_doc_row_has_a_reader():
    orphans = orphan_rows(REPO, _git_files(REPO), DOC, SRC)
    assert not orphans, (
        f"{len(orphans)} live SFU_* row(s) in docs/ENV_GATES.md have no reader in "
        "source/ scripts/ spike/ web/ (outside archive/ and tests/); strike them into "
        "the Retired gates table:\n  " + "\n  ".join(orphans))


def _planted_tree(tmp_path):
    src = tmp_path / "source"
    (src / "lib").mkdir(parents=True)
    (src / "tests").mkdir()
    (src / "lib" / "mod.py").write_text(
        '"""Mentions SFU_DOCSTRING_ONLY, which is not a read."""\n'
        "import os\n"
        'A = os.environ.get("SFU_DOCUMENTED")\n', encoding="utf-8")
    (src / "tests" / "test_x.py").write_text(
        'import os\nos.environ.get("SFU_TEST_ONLY")\n', encoding="utf-8")
    doc = tmp_path / "ENV_GATES.md"
    doc.write_text("| `SFU_DOCUMENTED` | x |\n| ~~`SFU_GONE`~~ | removed |\n",
                   encoding="utf-8")
    return src, doc


def test_planted_undocumented_read_fails_check_a(tmp_path):
    src, doc = _planted_tree(tmp_path)
    assert undocumented_reads(src, doc) == ([], [])
    (src / "lib" / "new.py").write_text(
        'import os\nB = os.environ.get("SFU_PLANTED")\n', encoding="utf-8")
    missing, _ = undocumented_reads(src, doc)
    assert [m.split()[0] for m in missing] == ["SFU_PLANTED"]
    (src / "lib" / "dyn.py").write_text(
        'import os\nk = "x"\nos.environ.get(f"SFU_OTHER_{k}")\n', encoding="utf-8")
    _, unresolved = undocumented_reads(src, doc)
    assert unresolved and "SFU_OTHER_" in unresolved[0]


def test_planted_retired_read_fails_check_b(tmp_path):
    src, doc = _planted_tree(tmp_path)
    assert resurrected_gates(src, doc) == []
    (src / "lib" / "back.py").write_text(
        'import os\nos.environ.get("SFU_GONE")\n', encoding="utf-8")
    assert resurrected_gates(src, doc)[0].startswith("SFU_GONE")


def test_planted_unread_doc_row_fails_check_c(tmp_path):
    src, doc = _planted_tree(tmp_path)
    rels = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    assert orphan_rows(tmp_path, rels, doc) == []
    doc.write_text(doc.read_text(encoding="utf-8") + "| `SFU_NOBODY_READS` | x |\n",
                   encoding="utf-8")
    assert orphan_rows(tmp_path, rels, doc) == ["SFU_NOBODY_READS"]
