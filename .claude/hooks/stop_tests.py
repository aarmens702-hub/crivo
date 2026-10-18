"""Stop hook: when Claude is about to finish with uncommitted Python changes
in src/, tests/ or bench/, run the test suite first. If it fails, block the
stop (exit 2) and hand Claude the failures, so "done" always means "tests
pass".

It tests the tree the session is working in (stdin's cwd, resolved to its
git top level), so parallel worktrees don't block each other. Skips quietly
when nothing relevant changed, when uv or the venv is missing, or when this
stop was itself caused by this hook (stop_hook_active), so it can't loop.

When the tests pass but a file that shapes what the model does changed
(BEHAVIOUR_FILES), it blocks once more to ask for the eval result, or a plain
"unmeasured": tests prove the code, not the behaviour (AGENTS.md, "Work
types"). Standard library only.
"""

BEHAVIOUR_FILES = ("src/crivo/prompts.py", "src/crivo/llm.py")

import json
import os
import shutil
import subprocess
import sys

try:
    data = json.load(sys.stdin)
except ValueError:
    data = {}
if data.get("stop_hook_active"):
    sys.exit(0)


def git(*args, cwd):
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
if data.get("cwd"):
    try:
        top = git("rev-parse", "--show-toplevel", cwd=data["cwd"]).stdout.strip()
        if top and os.path.isfile(os.path.join(top, "pyproject.toml")):
            root = top
    except (OSError, subprocess.SubprocessError):
        pass

try:
    changed = git("status", "--porcelain", "--", "src", "tests", "bench", cwd=root)
except (OSError, subprocess.SubprocessError):
    sys.exit(0)
if not any(line.endswith(".py") for line in changed.stdout.splitlines()):
    sys.exit(0)

uv = os.path.expanduser("~/.local/bin/uv")
if not os.access(uv, os.X_OK):
    uv = shutil.which("uv")
if not uv or not os.path.isdir(os.path.join(root, ".venv")):
    sys.exit(0)

try:
    run = subprocess.run(
        [uv, "run", "--quiet", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=280,
        check=False,
    )
except subprocess.TimeoutExpired:
    sys.stderr.write(
        "The test suite did not finish in 280 s. Run `uv run pytest -q` "
        "yourself and tell the user the result before finishing.\n"
    )
    sys.exit(2)
except OSError:
    sys.exit(0)
if run.returncode == 0:
    touched = [
        f
        for f in BEHAVIOUR_FILES
        if any(line.endswith(f) for line in changed.stdout.splitlines())
    ]
    if touched:
        sys.stderr.write(
            f"Tests pass, but {', '.join(touched)} shapes what the model does, and tests "
            "prove the code, not the behaviour. Before finishing, cite the eval result "
            "for this change, or tell the user plainly that the behaviour change is "
            "unmeasured.\n"
        )
        sys.exit(2)
    sys.exit(0)

tail = "\n".join((run.stdout + run.stderr).splitlines()[-40:])
sys.stderr.write(
    "The test suite is failing (uv run pytest -q). Fix it before finishing, "
    f"or tell the user plainly which tests fail and why.\n\n{tail}\n"
)
sys.exit(2)
