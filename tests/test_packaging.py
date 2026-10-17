"""Packaging tests: what a fresh `pip install` of crivo actually gets.

The lock pulls in packages crivo never declares, so an import of one passes in
CI and breaks on a fresh, unlocked install the day an SDK swaps its own
dependency (openai 3.x and anthropic 1.x moved from `httpx` to `httpx2`).
These tests read `pyproject.toml` and the shipped source as text and parse
both, so they import nothing from crivo and need no key or network.
"""

import ast
import re
import sys
import tomllib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# import name -> distribution name, where the two differ
_IMPORT_TO_DIST = {
    "dotenv": "python-dotenv",
    "jupyter_client": "jupyter-client",
}

# Undeclared on purpose: arrives through a declared package. One per line, so
# a change that declares one deletes only its own line.
_TRANSITIVE_ALLOWED = {
    "numpy",  # via pandas; #8 declares it
    "anyio",  # via the model SDKs and mcp
    "pydantic",  # via the model SDKs and mcp
    "mcp_types",  # ships with mcp>=2
}


def _normalise(name):
    """PEP 503 name: lower case, runs of `-`, `_` and `.` become one `-`."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(spec):
    try:
        from packaging.requirements import Requirement
    except ImportError:
        return re.split(r"[<>=!~\[ ;]", spec.strip(), maxsplit=1)[0]
    return Requirement(spec).name


def _declared_distributions():
    """Runtime and extras requirements; [dependency-groups] never ships."""
    project = tomllib.loads((_REPO / "pyproject.toml").read_text())["project"]
    specs = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        specs.extend(extra)
    return {_normalise(_requirement_name(spec)) for spec in specs}


def _third_party_imports():
    """Top-level module -> sorted relative paths of the src/crivo files importing it.

    Only real, absolute import statements count: a relative import is crivo's
    own, and an import written inside a string template is code for the kernel
    or the reader, which the AST rightly sees as a string.
    """
    src = _REPO / "src" / "crivo"
    found = {}
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top == "crivo":
                    continue
                found.setdefault(top, set()).add(str(path.relative_to(_REPO)))
    return {top: sorted(files) for top, files in found.items()}


def test_shipped_code_imports_only_declared_packages():
    declared = _declared_distributions()
    imports = _third_party_imports()

    offenders = sorted(
        top
        for top in imports
        if top not in _TRANSITIVE_ALLOWED
        and _normalise(_IMPORT_TO_DIST.get(top, top)) not in declared
    )

    detail = "; ".join(f"{top} ({', '.join(imports[top])})" for top in offenders)
    assert offenders == [], (
        f"src/crivo imports packages pyproject.toml does not declare: {detail}"
    )
