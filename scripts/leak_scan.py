"""Fail CI when the text the model reads holds material from a suite it is
graded on (spec: specs/2026-10-17-eval-tooling.md EV12, #75).

Protected text, what the model reads, each as its source reads:
- every str constant of src/crivo/prompts.py but its module docstring, an
  f-string whole, wherever it sits (a module constant, a tuple, a function);
- the docstring of each function in src/crivo/mcp_server.py decorated with
  `<any name>.tool(...)`;
- every skills/**/SKILL.md, and .claude/skills/crivo/SKILL.md.

Suite material, each item under an id that says where it lives, not what it
says:
- each SMOKE case name in bench/corpus.py (`corpus.py:<line>`);
- the str literals of bench/corrupt.py and bench/bases.py (`corrupt.py:<line>`,
  `bases.py:<line>`), less docstrings and every part of an f-string (G1), a
  literal equal to a taxonomy slug (G2) and a single lowercase identifier such
  as a column name (G3). The limit: a planted lowercase word ("unknown") goes
  unscanned;
- the name, question and expected value of each bench/traps/<suite>/*.json
  (`<suite>/case-<12 hex>:<field>`, the hex from sha256 of the file's stem, so
  no id carries a trap's words). No traps directory, nothing to scan. A trap
  file that is not UTF-8 JSON, or holds no JSON object, is a violation under
  its id, never its path.

Nothing passes vacuously: prompts.py, mcp_server.py, the crivo skill, corpus.py
and the injectors must exist and parse, prompts.py must hold a str constant,
mcp_server.py a tool docstring and corpus.py a SMOKE name literal. Each that
doesn't is one violation naming only the file.

Names, literals and trap values of 5 characters or more match as whole tokens,
case-insensitively, whitespace runs as any whitespace; a question matches on
any run of 6 of its words, consecutive runs reported once. Exact text only: a
paraphrase passes.

Output names the protected file, its line and the item id, never the matched
text: CI logs on a public repo are public, and for a sealed set the text is the
leak. Exits like a linter: 0 and one summary line when clean, 1 and one line
per violation. A line `<protected file>:<item id>:<sha256>  # reason` in the
allow file passes the match in that protected file, from that item's source
file, whose text casefolded with its whitespace collapsed has that sha256. The
item's line is not compared, so an edit to the injectors leaves it standing.
Aarmen adds the lines.

Standard library, plus the taxonomy's slugs from crivo.detect. It reads the
bench's files with ast and json and never imports them.

Usage: uv run python scripts/leak_scan.py [--root DIR] [--allow PATH]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

from crivo.detect import SLUGS

PROMPTS = "src/crivo/prompts.py"
MCP = "src/crivo/mcp_server.py"
SKILLS = "skills"
CRIVO_SKILL = ".claude/skills/crivo/SKILL.md"
CORPUS = "bench/corpus.py"
INJECTORS = ("bench/corrupt.py", "bench/bases.py")
TRAPS = "bench/traps"
ALLOW = "scripts/leak_scan_allow.txt"
FIELDS = ("name", "expected")
MIN_CHARS = 5
SHINGLE = 6
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
WORD = re.compile(r"\w+")


def _read(root: Path, rel: str, problems: list, required: bool) -> str | None:
    """`rel` under `root` as UTF-8 text, or None. A file that can't be read,
    or a required one that is missing, is a problem naming only the file."""
    path = root / rel
    if not path.exists():
        if required:
            problems.append(f"{rel}: missing, so nothing in it is scanned")
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        problems.append(f"{rel}: not readable as UTF-8 text")
        return None


def _parse(root: Path, rel: str, problems: list):
    """(source, tree) of a required Python file, or None and a problem."""
    source = _read(root, rel, problems, required=True)
    if source is None:
        return None
    try:
        return source, ast.parse(source)
    except (SyntaxError, ValueError):
        problems.append(f"{rel}: does not parse as Python")
        return None


def _str(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _docstring(node) -> ast.Constant | None:
    body = getattr(node, "body", None)
    first = body[0] if isinstance(body, list) and body else None
    if isinstance(first, ast.Expr) and _str(first.value) is not None:
        return first.value
    return None


def _prompt_nodes(tree) -> list:
    """Every str constant of prompts.py but its module docstring; an f-string
    as one node, its parts and expressions inside it."""
    doc, nodes, skip = _docstring(tree), [], set()
    for node in ast.walk(tree):  # breadth-first: an f-string before its parts
        if node is doc or id(node) in skip:
            continue
        if isinstance(node, ast.JoinedStr):
            skip.update(id(part) for part in ast.walk(node))
            nodes.append(node)
        elif _str(node) is not None:
            nodes.append(node)
    return nodes


def _tool_nodes(tree) -> list:
    """The docstring of each function decorated with <name>.tool(...)."""
    nodes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = [
                d.func if isinstance(d, ast.Call) else d for d in node.decorator_list
            ]
            tool = any(isinstance(f, ast.Attribute) and f.attr == "tool" for f in calls)
            doc = _docstring(node) if tool else None
            if doc is not None:
                nodes.append(doc)
    return nodes


def _protected(root: Path, problems: list) -> list[tuple[str, int, str]]:
    """Each text the model reads: (its file, the line it starts on, its text)."""
    texts = []
    for rel, pick, what in (
        (PROMPTS, _prompt_nodes, "str constant"),
        (MCP, _tool_nodes, "tool docstring"),
    ):
        parsed = _parse(root, rel, problems)
        source, tree = parsed if parsed else ("", None)
        found = [
            (rel, node.lineno, ast.get_source_segment(source, node))
            for node in (pick(tree) if tree else [])
        ]
        if parsed and not found:
            problems.append(f"{rel}: no {what} found, so nothing in it is scanned")
        texts += found
    folder = root / SKILLS
    skills = sorted(folder.rglob("SKILL.md")) if folder.is_dir() else []
    rels = [f"{SKILLS}/{p.relative_to(folder).as_posix()}" for p in skills]
    for rel in [*rels, CRIVO_SKILL]:
        text = _read(root, rel, problems, required=rel == CRIVO_SKILL)
        if text is not None:
            texts.append((rel, 1, text))
    return texts


def _case_names(root: Path, problems: list) -> list[tuple[str, str]]:
    """(id, name) for each SMOKE entry's name literal in bench/corpus.py."""
    parsed = _parse(root, CORPUS, problems)
    if not parsed:
        return []
    names = []
    for node in parsed[1].body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        else:
            targets = [node.target] if isinstance(node, ast.AnnAssign) else []
        smoke = any(isinstance(t, ast.Name) and t.id == "SMOKE" for t in targets)
        entries = node.value.elts if smoke and hasattr(node.value, "elts") else []
        for entry in entries:
            if isinstance(entry, ast.Dict):
                for key, value in zip(entry.keys, entry.values, strict=True):
                    if _str(key) == "name" and _str(value) is not None:
                        names.append((f"corpus.py:{value.lineno}", value.value))
    if not names:
        problems.append(f"{CORPUS}: no SMOKE case names found, so none are scanned")
    return names


def _literals(root: Path, rel: str, problems: list) -> list[tuple[str, str]]:
    """(id, text) for each str literal of an injector that G1-G3 keep."""
    parsed = _parse(root, rel, problems)
    if not parsed:
        return []
    tree, skip = parsed[1], set()
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        doc = _docstring(node) if isinstance(node, owners) else None
        if doc is not None:
            skip.add(id(doc))
        if isinstance(node, ast.JoinedStr):
            skip.update(id(part) for part in ast.walk(node))
    slugs, name, found = set(SLUGS.values()), Path(rel).name, []
    for node in ast.walk(tree):
        if _str(node) is None or id(node) in skip:
            continue
        text = " ".join(node.value.split())
        kept = text not in slugs and not IDENTIFIER.fullmatch(text)
        if len(text) >= MIN_CHARS and kept:
            found.append((f"{name}:{node.lineno}", text))
    return found


def _traps(root: Path, problems: list):
    """(id, text) items and the question shingles, from bench/traps/<suite>/.
    A trap's id is a digest of its file's stem, so none carries its words."""
    items, shingles = [], {}
    folder = root / TRAPS
    for path in sorted(folder.glob("*/*.json")) if folder.is_dir() else []:
        stem = path.stem.encode("utf-8", "surrogateescape")
        case = f"{path.parent.name}/case-{hashlib.sha256(stem).hexdigest()[:12]}"
        try:
            trap = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            problems.append(f"{case}: a trap file in {TRAPS} that is not UTF-8 JSON")
            continue
        if not isinstance(trap, dict):
            problems.append(f"{case}: a trap file in {TRAPS} with no JSON object")
            continue
        for field in FIELDS:
            text = " ".join(str(trap.get(field, "")).split())
            if len(text) >= MIN_CHARS:
                items.append((f"{case}:{field}", text))
        question = trap.get("question")
        question = question if isinstance(question, str) else ""
        words = [w.casefold() for w in WORD.findall(question)]
        for i in range(len(words) - SHINGLE + 1):
            ids = shingles.setdefault(tuple(words[i : i + SHINGLE]), {})
            ids[f"{case}:question"] = None
    return items, shingles


def _pattern(text: str) -> re.Pattern:
    body = r"\s+".join(re.escape(word) for word in text.split())
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def _shingle_hits(text: str, shingles: dict):
    """(start, end, item) for each run of consecutive 6-word windows of `text`
    that a trap question holds, one per run."""
    words = list(WORD.finditer(text))
    folded = [w.group(0).casefold() for w in words]
    windows = {}
    for i in range(len(words) - SHINGLE + 1):
        for item in shingles.get(tuple(folded[i : i + SHINGLE]), ()):
            windows.setdefault(item, []).append(i)
    for item, starts in windows.items():
        runs = []
        for i in starts:
            if runs and runs[-1][1] == i - 1:
                runs[-1][1] = i
            else:
                runs.append([i, i])
        for first, last in runs:
            yield words[first].start(), words[last + SHINGLE - 1].end(), item


def _sha(match: str) -> str:
    folded = " ".join(match.casefold().split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()


def _allowed(path: Path) -> set[tuple[str, str, str]]:
    """(protected file, the item's source file, sha256) per allow line."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return set()
    keys = set()
    for line in lines:
        parts = line.split("#", 1)[0].strip().split(":")
        if len(parts) >= 4:
            keys.add((parts[0], ":".join(parts[1:-2]), parts[-1].lower()))
    return keys


def scan(root: Path, allow: Path) -> tuple[list[str], dict]:
    """The violation lines, and the counts the summary reports."""
    problems = []
    texts = _protected(root, problems)
    names = _case_names(root, problems)
    literals = [i for rel in INJECTORS for i in _literals(root, rel, problems)]
    fields, shingles = _traps(root, problems)
    items = {}
    for item, text in [*names, *literals, *fields]:
        items.setdefault((item.rsplit(":", 1)[0], text.casefold()), (item, text))
    patterns = [(item, _pattern(text)) for item, text in items.values()]
    allowed, hits, passed = _allowed(allow), set(), 0
    for rel, first, text in texts:
        found = [
            (m.start(), m.end(), item)
            for item, rx in patterns
            for m in rx.finditer(text)
        ]
        for start, end, item in [*found, *_shingle_hits(text, shingles)]:
            line = first + text.count("\n", 0, start)
            if (rel, item.rsplit(":", 1)[0], _sha(text[start:end])) in allowed:
                passed += 1
            else:
                hits.add((rel, line, item))
    lines = [f"{rel}:{line}: matches {item}" for rel, line, item in sorted(hits)]
    counts = {
        "protected": len(texts),
        "names": len(names),
        "literals": len(literals),
        "traps": len(fields) + len({i for ids in shingles.values() for i in ids}),
        "allowed": passed,
    }
    return problems + lines, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Suite material in the text the model reads (EV12)"
    )
    parser.add_argument("--root", default=".", help="the repo to scan (default: cwd)")
    parser.add_argument("--allow", help=f"the allow file (default: <root>/{ALLOW})")
    args = parser.parse_args(argv)
    root = Path(args.root)
    found, n = scan(root, Path(args.allow) if args.allow else root / ALLOW)
    for line in found:
        print(line)
    if found:
        return 1
    print(
        f"leak_scan: clean, {n['protected']} protected texts against "
        f"{n['names']} case names, {n['literals']} injector literals and "
        f"{n['traps']} trap fields; {n['allowed']} allowed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
