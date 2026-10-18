"""The PreToolUse hooks in .claude/hooks/, run the way Claude Code runs them.

Each case starts the hook as a subprocess with the hook's JSON on stdin and the
mode in argv, from a throwaway checkout in tmp_path, and reads the exit code: 2
blocks the tool call, 0 lets it through. A block writes one line to stderr, in
the guard_tests.py style ("Blocked: ..."). Every block sits beside the nearby
call the same mode must still allow, so a hook that refuses everything fails
as loudly as one that refuses nothing.

guard_reads.py (#68) keeps the eval-author to its allowlist (ED3, ED4) and
keeps the builder off the held-out and sealed sets, off writes to the ledger
and off paid commands. The eval-author agent (#69) is wired to it in its
frontmatter, read here as text. Its git runs on its own worktree with -C, its
pytest runs only a worktree's tests, and it reads neither the plan inventory
nor the stage specs (#235).

The agent files (#70) wire it: the builder and the test-writer run it in
builder mode beside their guard_tests.py entry, and the scout, builder and
test-writer prompts carry the issue's type, its eval and their eval limits.
"""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"
GUARD_READS = HOOKS / "guard_reads.py"
EVAL_AUTHOR = REPO / ".claude" / "agents" / "eval-author.md"
HOME = os.path.expanduser("~")

# The checkout each case runs in. It is named like a fresh clone of the repo,
# so a "crivo" path component is the normal case, not a paid command. There is
# no bench/traps/heldout or bench/traps/sealed until a test makes one. It holds
# two worktrees, .worktrees/9 and .worktrees/10, where /start-task puts them.
CHECKOUT = (
    ".worktrees/9/bench/corrupt.py",
    ".worktrees/9/src/crivo/detect.py",
    ".worktrees/9/tests/test_bench_bases.py",
    ".worktrees/9/tests/test_bench_corrupt.py",
    ".worktrees/9/tests/test_bench_degenerate.py",
    ".worktrees/9/tests/test_bench_shapes.py",
    ".worktrees/9/tests/test_bench_truth.py",
    ".worktrees/9/tests/test_detect.py",
    ".worktrees/10/tests/test_bench_corrupt.py",
    "AGENTS.md",
    "CLAUDE.md",
    "pyproject.toml",
    "README.md",
    "SECURITY.md",
    "docs/PRD.md",
    "bench/__init__.py",
    "bench/agent_run.py",
    "bench/bases.py",
    "bench/corpus.py",
    "bench/corrupt.py",
    "bench/ledger.jsonl",
    "bench/RESULTS.md",
    "bench/score.py",
    "bench/results/run-2026-10-16.json",
    "bench/traps/dev/case-001.json",
    "data/example.csv",
    "docs/API-CONTRACT.md",
    "docs/ARCHITECTURE.md",
    "docs/p3-core-diffs-2026-09-02.md",
    "specs/2026-09-02-phase6-instrument-core-design.md",
    "specs/2026-10-14-plan-inventory.md",
    "specs/2026-10-14-the-plan.md",
    "specs/2026-10-17-eval-tooling.md",
    "specs/2026-10-17-stage-0-foundation.md",
    "specs/2026-10-17-stage-a-stabilize.md",
    "src/crivo/__init__.py",
    "src/crivo/__pycache__/detect.cpython-312.pyc",
    "src/crivo/autoclean.py",
    "src/crivo/detect.py",
    "src/crivo/loop.py",
    "src/crivo/prompts.py",
    "src/crivo/verify.py",
    "tests/test_bench_bases.py",
    "tests/test_bench_corrupt.py",
    "tests/test_bench_truth.py",
    "tests/test_detect.py",
)


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "crivo"
    for rel in CHECKOUT:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    return root


# Each tool's path field, and the other fields its real calls carry.
TOOL_FIELDS = {
    "Read": ("file_path", {}),
    "Write": ("file_path", {"content": "x = 1\n"}),
    "Edit": ("file_path", {"old_string": "a", "new_string": "b"}),
    "MultiEdit": ("file_path", {"edits": [{"old_string": "a", "new_string": "b"}]}),
    "NotebookEdit": ("notebook_path", {"new_source": "x = 1"}),
    "Grep": ("path", {"pattern": "def "}),
    "Glob": ("path", {"pattern": "**/*.py"}),
    "Bash": ("command", {}),
}


def call(tool_name, target=None, cwd="{root}", **fields):
    """The PreToolUse payload Claude Code sends, with `target` in the tool's
    path field (left out when None), from the shell's `cwd`. The hook reads
    tool_name, tool_input and cwd; the rest is there because real payloads
    carry it."""
    key, tool_input = TOOL_FIELDS[tool_name]
    tool_input = {**tool_input, **fields}
    if target is not None:
        tool_input[key] = target
    return {
        "session_id": "5f0c2a9e-0b7d-4c1e-9a3f-2d6e8b1c4a70",
        "transcript_path": "{home}/.claude/projects/crivo/5f0c2a9e.jsonl",
        "cwd": cwd,
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def _fill(value, slots):
    if isinstance(value, str):
        for name, text in slots.items():
            value = value.replace("{" + name + "}", text)
        return value
    if isinstance(value, dict):
        return {k: _fill(v, slots) for k, v in value.items()}
    return value


def run_hook(hook, mode, payload, cwd, python=sys.executable, **slots):
    slots = {"root": str(cwd), "parent": str(Path(cwd).parent), "home": HOME, **slots}
    stdin = payload if isinstance(payload, str) else json.dumps(_fill(payload, slots))
    argv = [str(python), str(hook)] + ([] if mode is None else [mode])
    return subprocess.run(
        argv,
        input=stdin,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def assert_exit(proc, expected):
    assert proc.returncode == expected, proc.stderr
    if expected == 2:
        lines = proc.stderr.splitlines()
        assert len(lines) == 1, proc.stderr
        assert lines[0].startswith("Blocked"), proc.stderr


def ea(tool_name, target, expected, name, cwd="{root}", **fields):
    payload = call(tool_name, target, cwd, **fields)
    return pytest.param("eval-author", payload, expected, id="eval-author-" + name)


def bd(tool_name, target, expected, name, **fields):
    payload = call(tool_name, target, **fields)
    return pytest.param("builder", payload, expected, id="builder-" + name)


def raw(mode, stdin, name):
    return pytest.param(mode, stdin, 2, id=f"{mode}-{name}")


BRIEF = "{home}/Desktop/mailo/coop-project/crivo-brief.md"
# The eval-author's shell starts in the main checkout, so its pytest names the
# worktree's tests by their full path.
WORKTREE = "{root}/.worktrees/9"
WT_TESTS = WORKTREE + "/tests/"
PYTEST_CORRUPT = "uv run pytest " + WT_TESTS + "test_bench_corrupt.py -q"
AGENT_RUN = "uv run python -m bench.agent_run --sample 1"
CLEAN = "uv run crivo clean data/example.csv"
FAUX = "CRIVO_PROVIDER=faux "

GUARD_READS_CASES = [
    # eval-author reads: the core, and anything that quotes it, is off the
    # allowlist wherever the copy sits; bench/ and the listed docs are on it
    ea("Read", "src/crivo/prompts.py", 2, "read-prompts"),
    ea("Read", "{root}/src/crivo/prompts.py", 2, "read-prompts-abs"),
    ea("Read", ".worktrees/9/src/crivo/prompts.py", 2, "read-prompts-wt"),
    ea("Read", "src/crivo/__pycache__/detect.cpython-312.pyc", 2, "read-pyc"),
    ea("Read", ".venv/lib/python3.12/site-packages/crivo/autoclean.py", 2, "read-site"),
    ea("Read", "src/crivo/verify.py", 2, "read-referee"),
    ea("Read", "bench/../src/crivo/loop.py", 2, "read-dotdot-loop"),
    ea("Read", "docs/p3-core-diffs-2026-09-02.md", 2, "read-core-diffs"),
    ea("Read", "docs/ARCHITECTURE.md", 2, "read-architecture"),
    ea("Read", "tests/test_detect.py", 2, "read-detect-tests"),
    ea("Read", "specs/2026-09-02-phase6-instrument-core-design.md", 2, "read-spec-old"),
    ea("Read", "bench/results/run-2026-10-16.json", 2, "read-results"),
    ea("Read", "bench/RESULTS/run-2026-10-16.json", 2, "read-results-upper"),
    # U+017F, the long s, case-folds to "s"
    ea("Read", "bench/reſults/run-2026-10-16.json", 2, "read-results-long-s"),
    ea("Read", "/etc/hosts", 2, "read-outside-checkout"),
    ea("Read", "{home}/Desktop/mailo/notes.md", 2, "read-beside-brief"),
    ea("Read", None, 2, "read-no-path"),
    ea("Read", "bench/corrupt.py", 0, "read-corrupt"),
    ea("Read", "{root}/bench/corrupt.py", 0, "read-corrupt-abs"),
    ea("Read", ".worktrees/9/bench/corrupt.py", 0, "read-corrupt-wt"),
    ea("Read", "bench/RESULTS.md", 0, "read-results-md"),
    ea("Read", "bench/traps/dev/case-001.json", 0, "read-trap"),
    ea("Read", "tests/test_bench_corrupt.py", 0, "read-bench-tests"),
    ea("Read", "docs/API-CONTRACT.md", 0, "read-contract"),
    ea("Read", "AGENTS.md", 0, "read-agents-md"),
    ea("Read", "CLAUDE.md", 0, "read-claude-md"),
    ea("Read", "specs/2026-10-14-the-plan.md", 0, "read-plan"),
    # the inventory and the stage specs quote the detector and its misses; the
    # eval tooling spec is the eval-author's own design of record (#235)
    ea("Read", "specs/2026-10-14-plan-inventory.md", 2, "read-inventory"),
    ea("Read", "specs/2026-10-17-stage-0-foundation.md", 2, "read-stage-0-spec"),
    ea("Read", "specs/2026-10-17-stage-a-stabilize.md", 2, "read-stage-a-spec"),
    ea("Read", "specs/2026-10-17-eval-tooling.md", 0, "read-spec-new"),
    ea("Read", "pyproject.toml", 0, "read-pyproject"),
    ea("Read", "SECURITY.md", 0, "read-security-md"),
    ea("Read", "docs/PRD.md", 0, "read-prd"),
    ea("Read", "README.md", 2, "read-readme"),
    ea("Read", BRIEF, 0, "read-brief"),
    # eval-author searches: the root itself must sit on the allowlist (B1)
    ea("Grep", "src", 2, "grep-src"),
    ea("Grep", None, 2, "grep-no-path"),
    ea("Grep", "bench/..", 2, "grep-dotdot"),
    ea("Grep", "bench/results", 2, "grep-results"),
    ea("Grep", "tests", 2, "grep-tests"),
    ea("Grep", "bench", 0, "grep-bench"),
    ea("Grep", "tests/test_bench_corrupt.py", 0, "grep-bench-test"),
    ea("Glob", "bench", 2, "glob-up-and-out", pattern="../src/**/*.py"),
    ea("Glob", "bench", 2, "glob-abs-pattern", pattern="{root}/src/crivo/*.py"),
    # an escaped dot is still a dot to the glob matcher
    ea("Glob", "bench", 2, "glob-escaped-dotdot", pattern=".\\./src/crivo/*.py"),
    ea("Glob", None, 2, "glob-no-path", pattern="src/**/*.py"),
    ea("Glob", "bench", 0, "glob-bench"),
    # eval-author writes: the traps, the injectors, the corpus, the shape
    # generator and the injector tests (ED4); not the attacks or the scorer
    ea("Write", "src/crivo/detect.py", 2, "write-detect"),
    ea("Write", "bench/traps/../../src/crivo/prompts.py", 2, "write-dotdot"),
    ea("Write", "bench/attacks/prompt_injection.py", 2, "write-attacks"),
    ea("Write", "bench/attacks/degenerate.py", 2, "write-attacks-degenerate"),
    ea("Write", "bench/score.py", 2, "write-scorer"),
    ea("Write", "bench/results/run-2026-10-17.json", 2, "write-results"),
    ea("Edit", "tests/test_bench_truth.py", 2, "edit-truth-tests"),
    ea("MultiEdit", "src/crivo/autoclean.py", 2, "multiedit-autoclean"),
    ea("NotebookEdit", "notebooks/demo.ipynb", 2, "notebookedit"),
    ea("Write", None, 2, "write-no-path"),
    ea("Write", "bench/corrupt.py", 0, "write-corrupt"),
    ea("Write", "bench/shapes.py", 0, "write-shapes"),
    ea("Write", "bench/degenerate.py", 0, "write-degenerate"),
    ea("Write", "tests/test_bench_degenerate.py", 0, "write-degenerate-tests"),
    ea("Write", "tests/test_bench_shapes.py", 0, "write-shapes-tests"),
    ea("Write", "bench/traps/dev/case-002.json", 0, "write-trap"),
    ea("Edit", "bench/bases.py", 0, "edit-bases"),
    ea("MultiEdit", "bench/corpus.py", 0, "multiedit-corpus"),
    ea("Edit", "tests/test_bench_corrupt.py", 0, "edit-corrupt-tests"),
    ea("Edit", "tests/test_bench_bases.py", 0, "edit-bases-tests"),
    # eval-author shell: whole commands off an allowlist, no shell operators
    ea("Bash", "cat src/crivo/loop.py", 2, "bash-cat-loop"),
    ea(
        "Bash",
        "uv run pytest " + WT_TESTS + "test_detect.py -q",
        2,
        "bash-pytest-detect",
    ),
    ea("Bash", "uv run pytest -q", 2, "bash-pytest-all"),
    ea("Bash", "uv run pytest -q", 2, "bash-pytest-all-wt", cwd=WORKTREE),
    ea(
        "Bash",
        PYTEST_CORRUPT + " " + WT_TESTS + "test_detect.py",
        2,
        "bash-pytest-extra-file",
    ),
    ea("Bash", "git diff", 2, "bash-diff-everything"),
    ea("Bash", "git diff -- src/crivo/detect.py", 2, "bash-diff-detect"),
    ea("Bash", "git diff -- bench/../src/crivo/detect.py", 2, "bash-diff-dotdot"),
    ea(
        "Bash", "git diff -- bench/corrupt.py src/crivo/detect.py", 2, "bash-diff-mixed"
    ),
    ea("Bash", PYTEST_CORRUPT + " && cat x", 2, "bash-and"),
    ea("Bash", PYTEST_CORRUPT + "; cat x", 2, "bash-semicolon"),
    ea("Bash", PYTEST_CORRUPT + " & cat x", 2, "bash-background"),
    ea("Bash", PYTEST_CORRUPT + " | head", 2, "bash-pipe"),
    ea("Bash", PYTEST_CORRUPT + " > out.txt", 2, "bash-redirect-out"),
    ea("Bash", PYTEST_CORRUPT + " < in.txt", 2, "bash-redirect-in"),
    ea("Bash", PYTEST_CORRUPT + " -k `whoami`", 2, "bash-backtick"),
    ea("Bash", PYTEST_CORRUPT + " -k $(whoami)", 2, "bash-subshell"),
    ea("Bash", PYTEST_CORRUPT + "\ncat x", 2, "bash-newline"),
    ea("Bash", None, 2, "bash-no-command"),
    ea("Bash", PYTEST_CORRUPT, 0, "bash-pytest-corrupt"),
    ea(
        "Bash",
        "uv run pytest " + WT_TESTS + "test_bench_bases.py -k mixed_dates",
        0,
        "bash-k",
    ),
    ea(
        "Bash",
        "uv run pytest tests/test_bench_truth.py -q -k sentinel",
        0,
        "bash-q-k",
        cwd=WORKTREE,
    ),
    ea(
        "Bash",
        "uv run pytest " + WT_TESTS + "test_bench_degenerate.py -q",
        0,
        "bash-pytest-degenerate",
    ),
    ea(
        "Bash",
        "uv run pytest tests/test_bench_shapes.py -q",
        0,
        "bash-pytest-shapes",
        cwd=WORKTREE,
    ),
    ea("Bash", "git status", 0, "bash-git-status"),
    ea("Bash", "git diff -- bench/corrupt.py", 0, "bash-diff-corrupt"),
    # eval-author pytest: each test path resolves into a .worktrees/<n>, since a
    # relative path from the main checkout tests dev's bench, not the
    # worktree's (#235)
    ea("Bash", "uv run pytest tests/test_bench_corrupt.py -q", 2, "bash-pytest-main"),
    ea(
        "Bash",
        "uv run pytest {root}/tests/test_bench_corrupt.py -q",
        2,
        "bash-pytest-main-abs",
    ),
    ea(
        "Bash",
        "uv run pytest ../../tests/test_bench_corrupt.py -q",
        2,
        "bash-pytest-wt-up-to-main",
        cwd=WORKTREE,
    ),
    ea(
        "Bash",
        PYTEST_CORRUPT + " tests/test_bench_bases.py",
        2,
        "bash-pytest-wt-and-main",
    ),
    ea(
        "Bash",
        "uv run pytest tests/test_bench_corrupt.py -q",
        0,
        "bash-pytest-wt-relative",
        cwd=WORKTREE,
    ),
    ea(
        "Bash",
        "uv run pytest .worktrees/9/tests/test_bench_corrupt.py -q",
        0,
        "bash-pytest-main-into-wt",
    ),
    # another worktree's bench tests are bench tests too (pinned: allowed)
    ea(
        "Bash",
        "uv run pytest ../10/tests/test_bench_corrupt.py -q",
        0,
        "bash-pytest-other-wt",
        cwd=WORKTREE,
    ),
    # eval-author git -C: onto a .worktrees/<n> of this checkout only, each
    # PATH read against that worktree, the same two commands (#235)
    ea("Bash", "git -C " + WORKTREE + " status", 0, "bash-C-wt-status"),
    ea("Bash", "git -C .worktrees/9 diff -- bench/corrupt.py", 0, "bash-C-wt-diff"),
    ea(
        "Bash",
        "git -C " + WORKTREE + " diff -- bench/corrupt.py tests/test_bench_corrupt.py",
        0,
        "bash-C-wt-diff-two",
    ),
    ea("Bash", "git -C /tmp/elsewhere status", 2, "bash-C-elsewhere"),
    ea("Bash", "git -C {root} status", 2, "bash-C-main"),
    ea("Bash", "git -C .worktrees/9/bench status", 2, "bash-C-wt-subdir"),
    ea("Bash", "git -C .worktrees/9 -C ../.. status", 2, "bash-C-twice"),
    ea("Bash", "git -C .worktrees/9 log -p", 2, "bash-C-wt-log"),
    ea("Bash", "git -C .worktrees/9 diff", 2, "bash-C-wt-diff-everything"),
    ea("Bash", "git -C .worktrees/9 diff --", 2, "bash-C-wt-diff-no-path"),
    ea(
        "Bash",
        "git -C .worktrees/9 diff -- src/crivo/detect.py",
        2,
        "bash-C-wt-diff-detect",
    ),
    ea(
        "Bash",
        "git -C .worktrees/9 diff -- bench/corrupt.py src/crivo/detect.py",
        2,
        "bash-C-wt-diff-mixed",
    ),
    # git diff on two paths, one outside the work tree, runs as --no-index: a
    # diff of the two folders on disk, git-ignored files such as bench/results/
    # included (#235)
    ea("Bash", "git -C .worktrees/9 diff -- ../../bench bench", 2, "bash-C-noindex"),
    ea(
        "Bash",
        "git -C " + WORKTREE + " diff -- {root}/bench bench",
        2,
        "bash-C-noindex-abs",
    ),
    ea(
        "Bash",
        "git diff -- {root}/bench bench",
        2,
        "bash-diff-wt-noindex",
        cwd=WORKTREE,
    ),
    ea(
        "Bash",
        "git diff -- {home}/Desktop/mailo/coop-project {root}/bench",
        2,
        "bash-diff-noindex-brief",
    ),
    # git reads a PATH's ".." as text, so one that climbs out of the work tree
    # and back in by the folder's own name is outside to git (the checkout here
    # is named crivo), though its real path is inside
    ea("Bash", "git diff -- ../crivo/bench bench/traps", 2, "bash-diff-climb-back"),
    ea(
        "Bash",
        "git -C .worktrees/9 diff -- ../9/bench/corrupt.py bench/truth.py",
        2,
        "bash-C-diff-climb-back",
    ),
    ea(
        "Bash",
        "git diff -- ../9/bench bench",
        2,
        "bash-diff-wt-climb-back",
        cwd=WORKTREE,
    ),
    # every PATH is relative, since git and the hook read an absolute one
    # differently: by its text against the work tree, or folded (APFS ignores
    # case) and links followed. A worktree's own files are named from it.
    ea(
        "Bash",
        "git -C .worktrees/9 diff -- " + WORKTREE + "/bench/corrupt.py",
        2,
        "bash-C-wt-diff-full-path",
    ),
    ea(
        "Bash",
        "git -C .worktrees/9 diff -- {root}/.WORKTREES/9/bench/corrupt.py bench/truth.py",
        2,
        "bash-C-diff-abs-case",
    ),
    ea(
        "Bash",
        "git diff -- {parent}/CRIVO/bench bench/traps",
        2,
        "bash-diff-abs-case",
    ),
    ea(
        "Bash",
        "git diff -- bench/corrupt.py tests/test_bench_corrupt.py",
        0,
        "bash-diff-wt-two",
        cwd=WORKTREE,
    ),
    # builder: off the held-out and sealed sets, by any spelling of the path
    bd("Read", "bench/traps/heldout/x.json", 2, "read-heldout"),
    bd("Read", "bench/traps/HELDOUT/x.json", 2, "read-heldout-upper"),
    bd("Read", "bench/traps/ſealed/x.json", 2, "read-sealed-long-s"),
    bd("Read", "{root}/bench/traps/sealed/case-9.json", 2, "read-sealed-abs"),
    bd("Read", ".worktrees/9/bench/traps/heldout/x.json", 2, "read-heldout-wt"),
    bd("Grep", "bench/traps/heldout", 2, "grep-heldout"),
    bd("Glob", "bench/traps/sealed", 2, "glob-in-sealed", pattern="*.json"),
    bd("Glob", None, 2, "glob-heldout-pattern", pattern="bench/traps/heldout/*"),
    bd("Bash", "ls bench/traps/heldout", 2, "bash-ls-heldout"),
    bd("Bash", "cat bench/traps/sealed/case-9.json", 2, "bash-cat-sealed"),
    bd("Bash", 'cat bench/traps/"held"out/x.json', 2, "bash-cat-quoted-heldout"),
    bd("Bash", 'cat bench/traps/"dev"/case-001.json', 0, "bash-cat-quoted-dev"),
    bd("Read", "bench/traps/dev/case-001.json", 0, "read-dev-trap"),
    bd("Read", "src/crivo/loop.py", 0, "read-loop"),
    bd("Grep", "bench/traps/dev", 0, "grep-dev-traps"),
    bd("Glob", None, 0, "glob-dev-pattern", pattern="bench/traps/dev/*"),
    bd("Bash", "ls bench/traps/dev", 0, "bash-ls-dev"),
    # builder: reads the ledger, never writes it from the shell
    bd("Bash", "echo x >> bench/ledger.jsonl", 2, "ledger-append"),
    bd("Bash", "echo x > bench/ledger.jsonl", 2, "ledger-truncate"),
    bd("Bash", "echo x | tee -a bench/ledger.jsonl", 2, "ledger-tee"),
    bd("Bash", "sed -i '' 's/a/b/' bench/ledger.jsonl", 2, "ledger-sed-bsd"),
    bd("Bash", "sed -i 's/a/b/' bench/ledger.jsonl", 2, "ledger-sed-gnu"),
    bd("Bash", "cp /tmp/rows.jsonl bench/ledger.jsonl", 2, "ledger-cp-onto"),
    bd("Bash", "mv /tmp/rows.jsonl bench/ledger.jsonl", 2, "ledger-mv-onto"),
    bd("Bash", "cat bench/ledger.jsonl", 0, "ledger-cat"),
    bd("Bash", "tail -n 3 bench/ledger.jsonl", 0, "ledger-tail"),
    bd("Bash", "cp bench/ledger.jsonl /tmp/ledger-copy.jsonl", 0, "ledger-cp-from"),
    bd("Bash", "cp /tmp/x/ledger.jsonl bench/", 2, "ledger-cp-into-dir"),
    bd("Bash", "mv /tmp/x/ledger.jsonl bench", 2, "ledger-mv-into-dir"),
    bd("Bash", "dd of=bench/ledger.jsonl", 2, "ledger-dd-of"),
    bd("Bash", "truncate -s 0 bench/ledger.jsonl", 2, "ledger-truncate-cmd"),
    bd("Bash", "git checkout HEAD~3 -- bench/ledger.jsonl", 2, "ledger-git-checkout"),
    bd("Bash", "dd if=bench/ledger.jsonl of=/tmp/copy", 0, "ledger-dd-if"),
    bd("Bash", "true x#; echo y >> bench/ledger.jsonl", 2, "ledger-mid-word-hash"),
    bd("Bash", "bash -c 'echo x >> bench/ledger.jsonl'", 2, "ledger-bash-c"),
    # builder: paid commands only with the faux provider, set on that command
    bd("Bash", AGENT_RUN, 2, "paid-agent-run"),
    bd("Bash", "uv run python bench/agent_run.py --sample 1", 2, "paid-agent-script"),
    bd("Bash", "uv run python -m bench.eval", 2, "paid-eval"),
    bd("Bash", "uv run python -m crivo", 2, "paid-analyst"),
    bd("Bash", CLEAN, 2, "paid-clean"),
    bd("Bash", ".venv/bin/crivo clean data/example.csv", 2, "paid-clean-bin"),
    bd("Bash", "uv run crivo-mcp", 2, "paid-mcp"),
    bd("Bash", "CRIVO_PROVIDER=openai " + CLEAN, 2, "paid-openai"),
    bd("Bash", FAUX + "true && " + CLEAN, 2, "paid-faux-other-segment"),
    bd("Bash", "uv run pytest -q && " + CLEAN, 2, "paid-chained"),
    bd("Bash", FAUX + AGENT_RUN, 0, "faux-agent-run"),
    bd("Bash", FAUX + "uv run python -m bench.eval", 0, "faux-eval"),
    bd("Bash", FAUX + CLEAN, 0, "faux-clean"),
    bd("Bash", "uv run crivo diagnose data/example.csv", 0, "diagnose"),
    bd("Bash", "uv run pytest -q", 0, "pytest"),
    bd("Bash", "uv run pytest tests/test_agent_bench.py -q", 0, "pytest-agent-bench"),
    bd("Bash", "git diff -- src/crivo/loop.py", 0, "diff-src-crivo"),
    bd("Bash", "cat bench/agent_run.py", 0, "cat-agent-run"),
    # a "#" inside a word is not a comment, so the paid call after it runs
    bd("Bash", "true x#; uv run crivo clean data/x.csv", 2, "paid-mid-word-hash"),
    bd("Bash", "uv run pytest -q # note", 0, "pytest-comment"),
    # a command run from a string
    bd("Bash", "bash -c 'uv run crivo clean x'", 2, "paid-bash-c"),
    bd("Bash", "eval uv run crivo clean x", 2, "paid-eval-builtin"),
    bd("Bash", "bash -c 'uv run pytest -q'", 0, "pytest-bash-c"),
    # faux must be set inside the string that runs the paid call (pinned on
    # purpose: the stricter reading)
    bd(
        "Bash",
        "CRIVO_PROVIDER=faux bash -c 'uv run crivo clean x'",
        2,
        "faux-outside-c",
    ),
    bd(
        "Bash", "bash -c 'CRIVO_PROVIDER=faux uv run crivo clean x'", 0, "faux-inside-c"
    ),
    bd("Bash", "builtin eval 'uv run crivo clean x'", 2, "paid-builtin-eval"),
    # here-strings feed a shell its command on stdin
    bd("Bash", "bash <<< 'uv run crivo clean x'", 2, "paid-here-string"),
    bd(
        "Bash",
        "bash -s <<< 'echo x >> bench/ledger.jsonl'",
        2,
        "ledger-here-string",
    ),
    bd("Bash", "bash <<< 'uv run pytest -q'", 0, "pytest-here-string"),
    # uv runs a module itself, and python runs a package folder
    bd("Bash", "uv run -m bench.agent_run --sample 1", 2, "paid-uv-m"),
    bd("Bash", "uv run --module bench.agent_run --sample 1", 2, "paid-uv-module"),
    bd("Bash", "uv run --module=bench.eval", 2, "paid-uv-module-eq"),
    bd("Bash", "python bench/eval", 2, "paid-eval-folder"),
    bd("Bash", "uv run -m bench.run --smoke", 0, "uv-m-bench-smoke"),
    bd("Bash", FAUX + "uv run -m bench.agent_run --sample 1", 0, "faux-uv-m"),
    bd("Bash", "uv run --no-binary-package x crivo clean x", 2, "paid-uv-no-binary"),
    bd("Bash", "uv run --no-binary-package x pytest -q", 0, "pytest-uv-no-binary"),
    # only the keyless subcommand is keyless, however the flags are spelled
    bd("Bash", "crivo --diagnose= --clean data/example.csv", 2, "paid-diagnose-empty"),
    bd(
        "Bash", "crivo --diagnose '' --clean data/example.csv", 2, "paid-diagnose-quote"
    ),
    bd("Bash", "crivo --diagnose data/example.csv", 0, "diagnose-flag"),
    bd("Bash", "crivo --diagnose data/example.csv --json", 0, "diagnose-flag-json"),
    bd(
        "Bash",
        "crivo --diagnose data/example.csv --diagnose= --clean data/example.csv",
        2,
        "paid-diagnose-then-empty",
    ),
    bd(
        "Bash",
        "crivo --diagnose data/example.csv --di= --clean data/example.csv",
        2,
        "paid-diagnose-then-prefix",
    ),
    # tools named by absolute path, under a checkout that is itself "crivo"
    bd("Bash", "{root}/.venv/bin/pytest -q", 0, "abs-pytest"),
    bd("Bash", "{root}/.venv/bin/ruff check .", 0, "abs-ruff"),
    bd("Bash", "uv run python {root}/bench/run.py --smoke", 0, "abs-bench-smoke"),
    bd("Bash", "{root}/.venv/bin/crivo clean data/example.csv", 2, "abs-paid-clean"),
    # fail closed: an unknown or missing mode, and input the hook can't read
    pytest.param("attacker", call("Read", "bench/corrupt.py"), 2, id="unknown-mode"),
    pytest.param(None, call("Read", "bench/corrupt.py"), 2, id="no-mode"),
    raw("builder", "not json", "stdin-not-json"),
    raw("builder", "[]", "stdin-list"),
    raw("builder", "", "stdin-empty"),
    raw("eval-author", "not json", "stdin-not-json"),
    raw("eval-author", "[]", "stdin-list"),
    raw("eval-author", '{"tool_name": "Read", "tool_input": "x"}', "tool-input-str"),
]

# A launcher in front of a paid call is still a paid call; the same launcher
# in front of the test run is still the test run.
LAUNCHERS = [
    ("time", "time -p crivo clean x", "time -p uv run pytest -q"),
    ("nice", "nice -n 5 crivo clean x", "nice -n 5 uv run pytest -q"),
    ("env-u", "env -u HOME crivo clean x", "env -u HOME uv run pytest -q"),
    (
        "uv-env-file",
        "uv run --env-file F crivo clean x",
        "uv run --env-file F pytest -q",
    ),
    ("uv-extra", "uv run --extra dev crivo clean x", "uv run --extra dev pytest -q"),
    ("uv-tool-run", "uv tool run crivo clean x", "uv tool run pytest -q"),
    ("timeout", "timeout 600 uv run crivo clean x", "timeout 600 uv run pytest -q"),
    ("group", "{ crivo clean x; }", "{ uv run pytest -q; }"),
    ("if", "if true; then crivo clean x; fi", "if true; then uv run pytest -q; fi"),
]
GUARD_READS_CASES += [
    bd("Bash", command, expected, f"launcher-{name}-{kind}")
    for name, paid, free in LAUNCHERS
    for command, expected, kind in ((paid, 2, "paid"), (free, 0, "pytest"))
]


@pytest.mark.parametrize(("mode", "payload", "expected"), GUARD_READS_CASES)
def test_guard_reads_blocks_what_the_mode_forbids(checkout, mode, payload, expected):
    proc = run_hook(GUARD_READS, mode, payload, checkout)
    assert_exit(proc, expected)


# A search rooted above a held-out or sealed set reaches it, but only once the
# set is on disk; until then the builder's repo-wide search keeps working (B2).
SEARCHES_FROM_ABOVE = [
    pytest.param(call("Grep"), True, id="grep-no-path"),
    pytest.param(call("Grep", "{root}"), True, id="grep-root-abs"),
    pytest.param(call("Grep", "bench"), True, id="grep-bench"),
    pytest.param(call("Grep", "bench/traps"), True, id="grep-traps"),
    pytest.param(call("Glob", pattern="**/*.json"), True, id="glob-no-path"),
    pytest.param(call("Grep", "src"), False, id="grep-src"),
    pytest.param(call("Grep", "bench/traps/dev"), False, id="grep-dev"),
]


@pytest.mark.parametrize("held", ["heldout", "sealed"])
@pytest.mark.parametrize("on_disk", [False, True], ids=["absent", "on-disk"])
@pytest.mark.parametrize(("payload", "above"), SEARCHES_FROM_ABOVE)
def test_builder_search_above_a_held_set_is_blocked_once_the_set_exists(
    checkout, held, on_disk, payload, above
):
    if on_disk:
        held_dir = checkout / "bench" / "traps" / held
        held_dir.mkdir()
        (held_dir / "case-001.json").write_text("{}")
    proc = run_hook(GUARD_READS, "builder", payload, checkout)
    assert_exit(proc, 2 if on_disk and above else 0)


# A case-insensitive disk (APFS) opens bench/traps/sealed under a name spelled
# with U+017F, the long s, and realpath keeps that spelling.
FOLDED = [
    pytest.param(call("Read", "bench/traps/ſealed/case-001.json"), 2, id="read"),
    pytest.param(call("Grep", "bench/traps/ſealed"), 2, id="grep"),
    pytest.param(call("Read", "bench/traps/dev/case-001.json"), 0, id="read-dev"),
]


@pytest.mark.parametrize(("payload", "expected"), FOLDED)
def test_builder_is_kept_off_a_sealed_set_spelled_with_a_folded_letter(
    checkout, payload, expected
):
    sealed = checkout / "bench" / "traps" / "sealed"
    sealed.mkdir()
    (sealed / "case-001.json").write_text("{}")
    proc = run_hook(GUARD_READS, "builder", payload, checkout)
    assert_exit(proc, expected)


# Links are followed before matching: a link inside bench/ that points into
# the core is the core, and the checkout reached through a linked directory
# (macOS /tmp is /private/tmp) is still the checkout. A link in .worktrees/
# named like a worktree is the folder it points to, here another clone (#235).
LINKED = [
    pytest.param(call("Read", "bench/prompts_view.py"), 2, id="file-link"),
    pytest.param(call("Read", "bench/crivo_src/loop.py"), 2, id="dir-link"),
    pytest.param(call("Grep", "bench/crivo_src"), 2, id="grep-dir-link"),
    pytest.param(call("Write", "bench/traps/detect_view.py"), 2, id="write-link"),
    pytest.param(call("Read", "{alias}/src/crivo/prompts.py"), 2, id="alias-prompts"),
    pytest.param(call("Read", "{alias}/bench/corrupt.py"), 0, id="alias-corrupt"),
    pytest.param(call("Write", "{alias}/bench/corrupt.py"), 0, id="alias-write"),
    pytest.param(call("Bash", "git -C .worktrees/7 status"), 2, id="git-C-fake-wt"),
    pytest.param(
        call("Bash", "uv run pytest .worktrees/7/tests/test_bench_corrupt.py -q"),
        2,
        id="pytest-fake-wt",
    ),
    pytest.param(
        call("Bash", "git -C {alias}/.worktrees/9 status"), 0, id="git-C-alias"
    ),
    # a link outside the checkout into bench/ is outside the work tree to git,
    # so git diff on it and a second path runs as --no-index
    pytest.param(
        call("Bash", "git diff -- {bench_link} bench/traps"),
        2,
        id="git-diff-bench-link",
    ),
]


@pytest.mark.parametrize(("payload", "expected"), LINKED)
def test_eval_author_follows_links_before_matching(
    checkout, tmp_path, payload, expected
):
    core = checkout / "src" / "crivo"
    (checkout / "bench" / "prompts_view.py").symlink_to(core / "prompts.py")
    (checkout / "bench" / "crivo_src").symlink_to(core, target_is_directory=True)
    (checkout / "bench" / "traps" / "detect_view.py").symlink_to(core / "detect.py")
    clone = tmp_path / "other-clone"
    for rel in ("bench/corrupt.py", "tests/test_bench_corrupt.py"):
        (clone / rel).parent.mkdir(parents=True, exist_ok=True)
        (clone / rel).write_text("")
    (checkout / ".worktrees" / "7").symlink_to(clone, target_is_directory=True)
    alias = tmp_path / "checkout-link"
    alias.symlink_to(checkout, target_is_directory=True)
    bench_link = tmp_path / "bench-link"
    bench_link.symlink_to(checkout / "bench", target_is_directory=True)
    proc = run_hook(
        GUARD_READS,
        "eval-author",
        payload,
        checkout,
        alias=str(alias),
        bench_link=str(bench_link),
    )
    assert_exit(proc, expected)


def test_guard_reads_is_stdlib_only_and_parses_as_python_3_9():
    # the hook runs as the system python3, outside the project's venv
    assert GUARD_READS.is_file(), f"{GUARD_READS} is missing"
    tree = ast.parse(GUARD_READS.read_text(), feature_version=(3, 9))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported, "guard_reads.py imports nothing"
    assert sorted(imported - sys.stdlib_module_names) == []


def test_guard_reads_docstring_does_not_promise_a_wall_that_is_not_built():
    # 0d's sandbox contains the analyst's kernel, not an agent's tools; an OS
    # sandbox for code the eval-author runs is deferred to 0d (D18), not built
    # (#235)
    doc = " ".join(
        (ast.get_docstring(ast.parse(GUARD_READS.read_text())) or "").split()
    )
    assert "real wall" not in doc.lower(), "the docstring names a wall nothing builds"
    assert "D18" in doc, "the docstring doesn't say the OS sandbox is deferred (D18)"


SYSTEM_PYTHON = Path("/usr/bin/python3")


@pytest.mark.parametrize(
    ("mode", "payload", "expected"),
    [
        ea("Read", "src/crivo/prompts.py", 2, "read-prompts"),
        ea("Read", "bench/corrupt.py", 0, "read-corrupt"),
        ea("Bash", "git -C " + WORKTREE + " status", 0, "bash-C-wt-status"),
        ea("Bash", PYTEST_CORRUPT, 0, "bash-pytest-corrupt"),
        bd("Bash", CLEAN, 2, "paid-clean"),
        bd("Bash", FAUX + CLEAN, 0, "faux-clean"),
    ],
)
def test_guard_reads_runs_under_the_system_python3(checkout, mode, payload, expected):
    # the hook's real interpreter (3.9 on macOS), not the project's venv
    if not SYSTEM_PYTHON.exists():
        pytest.skip("no /usr/bin/python3")
    probe = subprocess.run(
        [str(SYSTEM_PYTHON), "-c", "pass"], capture_output=True, timeout=30, check=False
    )
    if probe.returncode != 0:
        pytest.skip("/usr/bin/python3 does not run")
    proc = run_hook(GUARD_READS, mode, payload, checkout, python=SYSTEM_PYTHON)
    assert_exit(proc, expected)


# The eval-author agent (#69). Its frontmatter is the wiring: the tools: line
# is the real allowlist (an agent with no tools: line gets every tool), so it
# names only tools guard_reads.py checks in eval-author mode; and the hook's
# matcher is "*", so any other tool still meets the hook's fail-closed refuse
# row. There is no YAML library here, so the frontmatter is read as text, in
# the subset .claude/agents/*.md use: block mappings, block sequences and
# one-line scalars.
EVAL_AUTHOR_HOOK = (
    'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_reads.py" eval-author'
)
# the tools: line the issue names; MultiEdit and NotebookEdit may join it, since
# the hook checks them too
EVAL_AUTHOR_TOOLS = {"Read", "Grep", "Glob", "Edit", "Write", "Bash"}
# Task and Agent start a subagent with no hook; WebFetch reads the public repo's
# raw files; WebSearch reaches the web; mcp__ tools are another way out
UNGUARDED = ("Task", "Agent", "WebFetch", "WebSearch")
YAML_KEY = re.compile(r"([A-Za-z_][\w-]*):(?: +(.*))?$")


def yaml_scalar(raw):
    """One YAML scalar on one line: "double-quoted", 'single-quoted' or plain."""
    if raw.startswith('"'):
        value, end = json.JSONDecoder().raw_decode(raw)
    elif raw.startswith("'"):
        quoted = re.match(r"'((?:[^']|'')*)'", raw)
        assert quoted, f"unclosed quote in {raw!r}"
        value, end = quoted.group(1).replace("''", "'"), quoted.end()
    else:
        # a plain scalar can't open with an indicator (a bare * is an alias)
        # or hold ": ", or YAML fails to load and the agent loses its hooks
        value = raw.partition(" #")[0].strip()
        assert raw[:1] not in "*&!%@`|>{[#", f"{raw!r} must be quoted in YAML"
        assert ": " not in value + " ", f"{raw!r} must be quoted in YAML"
        return value
    rest = raw[end:].strip()
    assert not rest or rest.startswith("#"), f"text after the quotes in {raw!r}"
    return value


def is_item(text):
    return text == "-" or text.startswith("- ")


def yaml_block(rows, i, indent):
    """The mapping or sequence whose rows start at rows[i], indented `indent`,
    and the index past it. Each row is (indent, text)."""
    if is_item(rows[i][1]):
        items = []
        while i < len(rows) and rows[i][0] == indent and is_item(rows[i][1]):
            text = rows[i][1][1:].strip()
            if YAML_KEY.match(text):  # "- key: value" opens a mapping 2 columns in
                rows[i] = (indent + 2, text)
                item, i = yaml_block(rows, i, indent + 2)
            else:
                item, i = yaml_scalar(text), i + 1
            items.append(item)
        return items, i
    mapping = {}
    while i < len(rows) and rows[i][0] == indent and not is_item(rows[i][1]):
        key = YAML_KEY.match(rows[i][1])
        assert key, f"frontmatter line {rows[i][1]!r} is not key: value"
        name, raw = key.groups()
        assert name not in mapping, f"{name} is set twice in the frontmatter"
        i += 1
        nested = i < len(rows) and (
            rows[i][0] > indent or (rows[i][0] == indent and is_item(rows[i][1]))
        )
        if raw and not raw.startswith("#"):
            mapping[name] = yaml_scalar(raw)
        elif nested:
            mapping[name], i = yaml_block(rows, i, rows[i][0])
        else:
            mapping[name] = None
    return mapping, i


def agent_file(path):
    """An agent file's frontmatter, as a dict, and the body below it."""
    assert path.is_file(), f"{path.relative_to(REPO)} is missing"
    lines = path.read_text().splitlines()
    assert lines[:1] == ["---"] and "---" in lines[1:], (
        f"{path.name} must open with a frontmatter block between --- lines"
    )
    end = lines.index("---", 1)
    rows = [
        (len(line) - len(line.lstrip(" ")), line.strip())
        for line in lines[1:end]
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert rows and rows[0][0] == 0, f"{path.name} has an empty frontmatter block"
    front, used = yaml_block(rows, 0, 0)
    assert used == len(rows), f"frontmatter line {rows[used][1]!r} is out of place"
    return front, "\n".join(lines[end + 1 :])


def guard_tools(mode):
    """The tools guard_reads.py has a check for in `mode` ("*" aside), from its
    MODES table. The hook runs when imported, so it is parsed instead."""
    for node in ast.parse(GUARD_READS.read_text()).body:
        targets = [getattr(t, "id", None) for t in getattr(node, "targets", [])]
        if targets == ["MODES"]:
            modes = dict(zip((k.value for k in node.value.keys), node.value.values))
            table = modes[mode]
            fields = dict(zip((k.value for k in table.keys), table.values))
            return {k.value for k in fields["tools"].keys} - {"*"}
    raise AssertionError("guard_reads.py has no MODES table")


def test_eval_author_frontmatter_names_it_and_lists_only_guarded_tools():
    front, _ = agent_file(EVAL_AUTHOR)
    assert front.get("name") == "eval-author"
    assert front.get("description"), "the description names its job and read limit"
    # with no tools: line the agent would get every tool, WebFetch and MCP too
    assert isinstance(front.get("tools"), str), "tools: is one comma-separated line"
    tools = [tool.strip() for tool in front["tools"].split(",")]
    assert len(tools) == len(set(tools)), front["tools"]
    assert [t for t in tools if t in UNGUARDED or t.startswith("mcp__")] == []
    assert sorted(EVAL_AUTHOR_TOOLS - set(tools)) == []
    assert sorted(set(tools) - guard_tools("eval-author")) == []


def test_eval_author_frontmatter_runs_guard_reads_on_every_tool_call():
    front, _ = agent_file(EVAL_AUTHOR)
    hooks = front.get("hooks")
    assert isinstance(hooks, dict), "eval-author.md has no hooks: block"
    assert hooks.get("PreToolUse") == [
        {"matcher": "*", "hooks": [{"type": "command", "command": EVAL_AUTHOR_HOOK}]}
    ]


# The bench rule, for an author of both injectors and trap suites: not the
# detector or the fixer, and not the prompts, the loop or the referee.
BENCH_RULE = ("prompts.py", "loop.py", "detect.py", "autoclean.py")
REFEREE = re.compile(r"referee|verify\.py", re.IGNORECASE)
NOT_READ = re.compile(
    r"(?:\bnot|\bnever|\bcannot|n't)\s+(?:[\w,]+\s+){0,3}?read", re.IGNORECASE
)
NO_QUOTE = re.compile(
    r"(?:\bnot|\bnever|n't)\s+quote\b[^\n]*?\bcases?\b", re.IGNORECASE
)


def test_eval_author_body_keeps_the_bench_rule_and_never_quotes_cases():
    _, body = agent_file(EVAL_AUTHOR)
    paragraphs = re.split(r"\n\s*\n", body)
    rule = [
        p
        for p in paragraphs
        if all(name in p for name in BENCH_RULE)
        and REFEREE.search(p)
        and NOT_READ.search(p)
    ]
    assert rule, (
        "no paragraph of eval-author.md says it does not read prompts.py, "
        "loop.py, the referee, detect.py or autoclean.py"
    )
    assert NO_QUOTE.search(body), "eval-author.md never says not to quote cases"


def guard_rules(name):
    """One of guard_reads.py's path lists, read from its source (the hook runs
    when imported)."""
    for node in ast.parse(GUARD_READS.read_text()).body:
        targets = [getattr(t, "id", None) for t in getattr(node, "targets", [])]
        if targets == [name]:
            return ast.literal_eval(node.value)
    raise AssertionError(f"guard_reads.py has no {name}")


def eval_author_step(phrase):
    """The numbered step of eval-author.md's body that says `phrase`, its lines
    and bullets joined into one."""
    _, body = agent_file(EVAL_AUTHOR)
    steps = [" ".join(step.split()) for step in re.split(r"\n(?=\d+\. )", body)]
    found = [step for step in steps if phrase in step.lower()]
    assert len(found) == 1, f"eval-author.md has {len(found)} steps on {phrase!r}"
    return found[0]


def rule_name(rule):
    """A path rule, or a path the prompt lists, as the file or folder it names."""
    return re.sub(r"/(\*\*)?$", "", rule.lstrip("!"))


def test_eval_author_read_list_drops_the_docs_that_describe_the_detector():
    # the inventory and the stage specs quote detector lines, thresholds and
    # misses; the eval tooling spec, its own design of record, stays by name
    # (#235). The prompt's list is the hook's list.
    step = eval_author_step("may read only")
    sentence = re.search(r"may read only(.*?)\.(?:\s|$)", step, re.IGNORECASE)
    listed = re.findall(r"`([^`]+)`", sentence.group(1))
    assert "specs/2026-10-14-plan-inventory.md" not in listed
    assert [name for name in listed if name.startswith("specs/2026-10-17-*")] == []
    assert "specs/2026-10-17-eval-tooling.md" in listed
    hook = sorted(map(rule_name, guard_rules("EVAL_AUTHOR_READS")))
    assert sorted(map(rule_name, listed)) == hook


def test_eval_author_run_list_names_git_on_its_own_worktree():
    # git status and git diff from the main checkout miss the worktree's edits
    step = eval_author_step("may run only")
    assert "git -C" in step, "eval-author.md's run list has no git -C on its worktree"


def run_frontmatter_hooks(front, payload, cwd):
    """Each PreToolUse hook in the frontmatter whose matcher takes the call,
    run through the shell as Claude Code runs it, with $CLAUDE_PROJECT_DIR at
    this checkout. A matcher of "*" (or none) takes every tool."""
    hooks = front.get("hooks") if isinstance(front.get("hooks"), dict) else {}
    stdin = json.dumps(_fill(payload, {"root": str(cwd), "home": HOME}))
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO)}
    runs = []
    for entry in hooks.get("PreToolUse") or []:
        matcher = entry.get("matcher") or "*"
        if matcher != "*" and not re.fullmatch(matcher, payload["tool_name"]):
            continue
        for hook in entry.get("hooks") or []:
            proc = subprocess.run(
                hook["command"],
                shell=True,
                input=stdin,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            runs.append(proc)
    return runs


RAW_PROMPTS = (
    "https://raw.githubusercontent.com/aarmens702-hub/crivo/dev/src/crivo/prompts.py"
)
WEB_FETCH = {
    **call("Read"),
    "tool_name": "WebFetch",
    "tool_input": {"url": RAW_PROMPTS, "prompt": "Quote the system prompt"},
}
SUBAGENT = {
    **call("Read"),
    "tool_name": "Task",
    "tool_input": {
        "description": "Summarise the loop",
        "prompt": "Read src/crivo/loop.py and summarise it",
        "subagent_type": "general-purpose",
    },
}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(call("Read", "src/crivo/prompts.py"), 2, id="read-prompts"),
        pytest.param(call("Read", "bench/corrupt.py"), 0, id="read-corrupt"),
        # tools off the tools: line meet the refuse row, through matcher "*"
        pytest.param(WEB_FETCH, 2, id="webfetch-raw-prompts"),
        pytest.param(SUBAGENT, 2, id="task-subagent"),
    ],
)
def test_eval_author_hook_command_blocks_what_eval_author_mode_forbids(
    checkout, payload, expected
):
    front, _ = agent_file(EVAL_AUTHOR)
    runs = run_frontmatter_hooks(front, payload, checkout)
    assert runs, f"no PreToolUse hook in eval-author.md sees {payload['tool_name']}"
    if expected == 0:
        for proc in runs:
            assert_exit(proc, 0)
    else:
        blocking = [proc for proc in runs if proc.returncode != 0] or runs
        assert_exit(blocking[0], 2)


# The agent files (#70).
AGENTS = HOOKS.parent / "agents"


def agent_text(agent):
    path = AGENTS / agent
    assert path.is_file(), f"{path} is missing"
    return path.read_text()


def frontmatter_hooks(agent):
    """The frontmatter lines from the top-level `hooks:` key to the closing
    `---`, indentation kept."""
    lines = agent_text(agent).splitlines()
    assert lines[0] == "---", f"{agent} has no frontmatter"
    assert "---" in lines[1:], f"{agent}'s frontmatter is never closed"
    front = lines[1 : lines.index("---", 1)]
    assert "hooks:" in front, f"{agent}'s frontmatter has no top-level hooks: key"
    return front[front.index("hooks:") :]


# Pinned whole, so a mis-indented entry, a renamed key, a third entry or a
# changed guard_tests.py line fails. guard_tests.py stays first and as it was;
# guard_reads.py runs in builder mode on every tool ("*", as its docstring
# says to wire it).
FRONTMATTER_HOOKS = """\
hooks:
  PreToolUse:
    - matcher: "Edit|Write|MultiEdit"
      hooks:
        - type: command
          command: python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_tests.py" {mode}
    - matcher: "*"
      hooks:
        - type: command
          command: python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_reads.py" builder
"""


@pytest.mark.parametrize(
    ("agent", "guard_tests_mode"),
    [("builder.md", "no-tests"), ("test-writer.md", "only-tests")],
)
def test_builder_and_test_writer_run_guard_reads_beside_guard_tests(
    agent, guard_tests_mode
):
    expected = FRONTMATTER_HOOKS.format(mode=guard_tests_mode).splitlines()
    assert frontmatter_hooks(agent) == expected


def change_map():
    """The lines of the change-map block in scout.md."""
    blocks = re.findall(r"```\n(.*?)```", agent_text("scout.md"), re.DOTALL)
    maps = [block for block in blocks if block.startswith("CHANGE MAP:")]
    assert len(maps) == 1, f"scout.md has {len(maps)} change-map blocks"
    return maps[0].splitlines()


@pytest.mark.parametrize("label", ["Type:", "Eval:"])
def test_scout_change_map_has_a_type_and_an_eval_line(label):
    labels = [line.split(":", 1)[0] + ":" for line in change_map()]
    assert label in labels


def paragraphs(agent):
    """An agent file's body, one lower-cased string per paragraph, bullet or
    numbered step, with line wraps joined and markdown emphasis dropped."""
    body = agent_text(agent).split("\n---\n", 1)[1]
    units = []
    for line in body.splitlines():
        stripped = line.strip()
        starts = not stripped or stripped.startswith(("-", "*", "#", "```"))
        if starts or re.match(r"\d+\.", stripped) or not units:
            units.append(stripped)
        else:
            units[-1] += " " + stripped
    return [re.sub(r"[*`]", "", unit).strip().lower() for unit in units if unit]


# (agent, what the paragraph is about, what that paragraph must also say)
EVAL_LIMITS = [
    pytest.param(
        "builder.md", r"\bpaid commands?\b", [r"\bnever\b"], id="builder-never-paid"
    ),
    pytest.param(
        "builder.md",
        r"\b(2|two) eval runs\b",
        [r"\bissue\b", r"\bstops?\b"],
        id="builder-stops-after-2-eval-runs",
    ),
    pytest.param(
        "test-writer.md",
        r"\btests/replay\.py\b",
        [r"\bcassette", r"\bbehaviou?r\b"],
        id="test-writer-cassette-through-replay",
    ),
]


@pytest.mark.parametrize(("agent", "topic", "musts"), EVAL_LIMITS)
def test_agent_prompt_states_its_eval_limit(agent, topic, musts):
    about = [unit for unit in paragraphs(agent) if re.search(topic, unit)]
    saying = [unit for unit in about if all(re.search(m, unit) for m in musts)]
    assert saying != [], f"{agent}: no paragraph on {topic} says {musts}"
