"""Keep bench/ledger.jsonl append-only and its rows true to the code they ran
(spec: specs/2026-10-17-eval-tooling.md EV11, #74).

The locks, checked over git history:

1. Append-only: every commit that touched the ledger keeps the file at its
   first parent as a prefix. An edited or removed line, or a deleted file,
   names that commit.
2. Registration first: every result names a registration earlier in the file
   with the same suite hash, scorer and referee hashes, arm names and k.
3. True to the code: every adopted decision on a behaviour (or untyped)
   registration matches the prompt, referee and scorer files of the commit
   that landed the decision line, hashed by ledger._hash. Not the row's own
   `commit`, which /ship's rebase replaces. Experiment, code and eval
   registrations, and dropped decisions, are exempt.
4. Sealed: no sealed set exists until ED7 names where one lives, so a
   registration on the sealed split fails.

A shallow clone fails, so history it lacks can't pass vacuously (CI checks out
with fetch-depth: 0). Exits like a linter: 0 and one summary line when clean,
1 and one line per violation. Standard library and git only.

It checks committed history only: steps 2 to 4 read the ledger at HEAD, so a
staged or uncommitted row is not checked, and neither is a rebase conflict
resolved before `git rebase --continue`. Run it after committing and before
pushing: a violation that reaches dev can't be undone without rewriting its
history.

Usage: uv run python scripts/check_locks.py [--root DIR]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

# `python scripts/check_locks.py` puts only scripts/ on sys.path, and
# bench.ledger lives at the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench import ledger

LEDGER = ledger.LEDGER.as_posix()
PARTS = ("prompt", "referee", "scorer")
# Registration types whose adoption ships no prompt change (scout call 1 on
# #74). Any other type, or none, is checked as behaviour.
EXEMPT = ("code", "eval", "experiment")
BLAME_HEADER = re.compile(r"([0-9a-f]{40,64}) \d+ (\d+)")


class GitError(RuntimeError):
    """A git call failed for a reason other than a missing parent or file."""


def _run(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", root, *args], capture_output=True, timeout=60, check=False
    )


def _git(root: str, *args: str) -> bytes:
    run = _run(root, *args)
    if run.returncode != 0:
        detail = run.stderr.decode(errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {detail}")
    return run.stdout


def _blob(root: str, commit: str, path: str) -> bytes | None:
    """`path` at `commit`, or None when that commit has no such file. A bad
    commit, or any other git failure, raises GitError."""
    if _run(root, "cat-file", "-e", f"{commit}:{path}").returncode == 0:
        return _git(root, "cat-file", "blob", f"{commit}:{path}")
    _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
    return None


def _append_only(root: str) -> tuple[list[str], int]:
    """Step 1: each commit that touched the ledger against its first parent."""
    log = _git(root, "log", "--reverse", "--format=%H", "--", LEDGER)
    commits = log.decode().split()
    found = []
    for commit in commits:
        parents = _git(root, "rev-list", "--parents", "-n", "1", commit)
        first = parents.decode().split()[1:2]
        before = _blob(root, first[0], LEDGER) if first else None
        after = _blob(root, commit, LEDGER)
        if before is None:
            continue
        if after is None:
            found.append(f"commit {commit[:12]} deletes {LEDGER} (append-only)")
        elif not after.startswith(before):
            old = before.splitlines(keepends=True)
            new = after.splitlines(keepends=True)
            pairs = enumerate(zip(old, new, strict=False), 1)
            line = next((n for n, (a, b) in pairs if a != b), len(new) + 1)
            found.append(
                f"commit {commit[:12]} edits or removes line {line} of {LEDGER} "
                "(append-only)"
            )
    return found, len(commits)


def _landed(root: str) -> dict[int, str]:
    """Each line of the ledger at HEAD (1-based) to the commit that added it."""
    out = _git(root, "blame", "--porcelain", "HEAD", "--", LEDGER)
    landed = {}
    for text in out.decode(errors="replace").split("\n"):
        header = BLAME_HEADER.match(text)
        if header:
            landed[int(header.group(2))] = header.group(1)
    return landed


def _fp(row: dict, part: str):
    prints = row.get("fingerprints")
    return prints.get(part) if isinstance(prints, dict) else None


def _digest(node) -> str | None:
    return node.get("sha256") if isinstance(node, dict) else None


def _arm_names(arms) -> list[str] | None:
    """A registration's arms[].name, or a result's arms keys, sorted."""
    if isinstance(arms, dict):
        return sorted(str(name) for name in arms)
    if isinstance(arms, list):
        return sorted(str(a.get("name") if isinstance(a, dict) else a) for a in arms)
    return None


def _show(value) -> str:
    if isinstance(value, list):
        return ",".join(value)
    return value[:12] if isinstance(value, str) else str(value)


def _linked(res: dict, at: int, rows: list, where: dict) -> list[str]:
    """Step 2: a result against the registration it names."""
    rid, link = res.get("row_id"), res.get("registered")
    j = where.get(link)
    if j is None or rows[j].get("kind") != "registered" or j > at:
        why = (
            "is not in the ledger"
            if j is None
            else "is not a registration"
            if rows[j].get("kind") != "registered"
            else "comes after it"
        )
        return [f"{rid} names registration {link}, which {why}"]
    reg = rows[j]
    pairs = [
        ("suite_hash", _digest(res.get("suite_hash")), _digest(reg.get("suite_hash"))),
        ("scorer hash", _digest(_fp(res, "scorer")), _digest(_fp(reg, "scorer"))),
        ("referee hash", _digest(_fp(res, "referee")), _digest(_fp(reg, "referee"))),
        ("arms", _arm_names(res.get("arms")), _arm_names(reg.get("arms"))),
        ("k", res.get("k"), reg.get("k")),
    ]
    found = []
    for name, got, want in pairs:
        if got is None:
            found.append(f"{rid} has no {name}")
        elif got != want:
            found.append(
                f"{rid}: {name} {_show(got)} differs from {link}'s {_show(want)}"
            )
    return found


def _write(root: str, commit: str, files: list, tmp: str) -> str | None:
    """Write each file at `commit` under `tmp`; the reason one can't be."""
    for rel in files:
        pure = PurePosixPath(rel)
        if not pure.parts or pure.is_absolute() or ".." in pure.parts:
            return f"{rel} is outside the repo"
        data = _blob(root, commit, pure.as_posix())
        if data is None:
            return f"{rel} is not in commit {commit[:12]}, which landed it"
        target = Path(tmp, *pure.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return None


def _true_to_code(
    root: str, dec: dict, commit: str | None, rows: list, where: dict
) -> list[str]:
    """Step 3: an adopted decision against the code its line landed with."""
    did, link = dec.get("row_id"), dec.get("result")
    j = where.get(link)
    res = rows[j] if j is not None else {}
    if res.get("kind") != "result":
        return [f"{did} (adopted) names result {link}, which is not a result"]
    k = where.get(res.get("registered"))
    reg = rows[k] if k is not None and rows[k].get("kind") == "registered" else {}
    if reg.get("type") in EXEMPT:
        return []
    if commit is None:
        return [f"{did} (adopted): git blame names no commit for its line"]
    found = []
    with tempfile.TemporaryDirectory() as tmp:
        for part in PARTS:
            node = _fp(res, part)
            want = _digest(node)
            files = node.get("files") if isinstance(node, dict) else None
            usable = isinstance(want, str) and isinstance(files, list) and files
            if not usable or not all(isinstance(f, str) for f in files):
                found.append(f"{did} (adopted): {link} has no {part} hash")
                continue
            reason = _write(root, commit, files, tmp)
            if reason:
                found.append(f"{did} (adopted): {part} file {reason}")
                continue
            got = ledger._hash(tmp, files)["sha256"]
            if got != want:
                found.append(
                    f"{did} (adopted): the {part} files at {commit[:12]}, "
                    f"which landed it, hash to {got[:12]}, not {link}'s "
                    f"{want[:12]}"
                )
    return found


def _check_rows(root: str, rows: list, landed: dict[int, str]) -> list[str]:
    """Steps 2 to 4 over the ledger's rows at HEAD, in file order."""
    found, where = [], {}
    for i, row in enumerate(rows):
        if isinstance(row, dict):
            where.setdefault(row.get("row_id"), i)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            found.append(f"{LEDGER} line {i + 1} is not a JSON object")
            continue
        kind = row.get("kind")
        if kind == "registered" and row.get("split") == "sealed":
            found.append(
                f"{row.get('row_id')} is registered on the sealed split, but no "
                "sealed set exists yet (ED7)"
            )
        elif kind == "result":
            found += _linked(row, i, rows, where)
        elif kind == "decision" and row.get("decision") == "adopted":
            found += _true_to_code(root, row, landed.get(i + 1), rows, where)
    return found


def _scan(root: str) -> tuple[list[str], int, int]:
    """The violations, the commits that touched the ledger, and its rows."""
    try:
        top = _git(root, "rev-parse", "--show-toplevel").decode().strip()
        shallow = _git(top, "rev-parse", "--is-shallow-repository").decode()
        if shallow.strip() == "true":
            why = "this clone is shallow: check_locks needs the full history"
            return [f"{why} (fetch-depth: 0)"], 0, 0
        found, commits = _append_only(top)
        data = _blob(top, "HEAD", LEDGER) or b""
        try:
            rows = ledger._parse(data, ledger.LEDGER)
        except ValueError as exc:
            return [*found, str(exc)], commits, 0
        landed = _landed(top) if rows else {}
        found += _check_rows(top, rows, landed)
    except (GitError, OSError, subprocess.SubprocessError) as exc:
        return [f"check_locks could not read the git history: {exc}"], 0, 0
    return found, commits, len(rows)


def check(root: str) -> list[str]:
    """One line per violation of the ledger's locks in the git repo at `root`;
    [] when it keeps them all (a missing or empty ledger keeps them)."""
    return _scan(root)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The eval ledger's locks (EV11)")
    parser.add_argument("--root", default=".", help="the git repo (default: cwd)")
    args = parser.parse_args(argv)
    found, commits, rows = _scan(args.root)
    for line in found:
        print(line)
    if found:
        return 1
    print(
        f"check_locks: clean at HEAD, {rows} row{'s' * (rows != 1)} in {LEDGER} over "
        f"{commits} commit{'s' * (commits != 1)}; no sealed set (ED7)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
