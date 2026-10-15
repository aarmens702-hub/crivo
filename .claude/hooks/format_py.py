"""PostToolUse hook: ruff-format the Python file Claude just edited.

Format only, never `ruff check --fix`: the fixer strips an import added in
one edit before the next edit adds its first use. /ship runs the lint.
A formatter failure must never block Claude, so every error exits 0.
Standard library only.
"""

import json
import os
import shutil
import subprocess
import sys

try:
    path = json.load(sys.stdin).get("tool_input", {}).get("file_path") or ""
except (ValueError, AttributeError):
    sys.exit(0)
if not path.endswith(".py") or not os.path.isfile(path):
    sys.exit(0)

uv = os.path.expanduser("~/.local/bin/uv")
if not os.access(uv, os.X_OK):
    uv = shutil.which("uv")
if not uv:
    sys.exit(0)

root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
try:
    subprocess.run(
        [uv, "run", "--quiet", "ruff", "format", path],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
except (OSError, subprocess.SubprocessError):
    pass
sys.exit(0)
