"""Import isolation for the keyless library modules.

Each module below must import in a fresh interpreter with no provider key and
without pulling a reserved core module into the import graph. One test, run
once per module, replaces the six copies that used to sit beside each module's
own tests.
"""

import os
import subprocess
import sys

import pytest

RESERVED = (
    "crivo.loop",
    "crivo.prompts",
    "crivo.skills",
    "crivo.provenance",
    "crivo.llm",
)

MODULES = (
    "crivo.crosscol",
    "crivo.excel_structure",
    "crivo.plan",
    "crivo.rowdiff",
    "crivo.router",
    "crivo.semantic_types",
)


@pytest.mark.parametrize("module", MODULES)
def test_import_is_keyless_and_pulls_no_core_module(module):
    # conftest's autouse quarantine has already stripped every provider key, so
    # the child interpreter imports with no key; the reserved core modules must
    # stay out of the import graph (contract: loop, prompts, skills, provenance
    # and llm are never touched)
    code = (
        "import sys\n"
        f"import {module}\n"
        f"reserved = {RESERVED!r}\n"
        "bad = [m for m in reserved if m in sys.modules]\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
