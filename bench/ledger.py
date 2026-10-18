"""The eval ledger: one append-only JSONL file of registrations, results and
decisions (spec: specs/2026-10-17-eval-tooling.md EV4, #67).

This module is the only writer of bench/ledger.jsonl. Every eval is
registered before it runs, its result names that registration, and its adopt
or drop decision names the result; each row is stamped with the code it ran
against (`fingerprints`). A `shipped-unmeasured` decision names no result
(ED6), only its issue.

`python -m bench.ledger show [--issue N] [--suite S]` prints one line per row
with no per-case detail; `python -m bench.ledger check --issue N` exits 0 when
the issue has an adopted decision on today's prompts.py or a
shipped-unmeasured one, else 1. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

LEDGER = Path("bench/ledger.jsonl")
SCHEMA_VERSION = 1

PROMPT_FILES = ["src/crivo/prompts.py"]
REFEREE_FILES = ["src/crivo/verify.py", "src/crivo/diff.py"]
SCORER_FILES = ["bench/score.py", "bench/consistency.py"]

BASE = ("schema_version", "row_id", "kind", "at", "by", "issue")
REQUIRED = {
    "registered": (
        "suite",
        "split",
        "arms",
        "k",
        "hypothesis",
        "primary",
        "guards",
        "rule",
        "budget_usd",
        "per_case_usd",
        "fingerprints",
        "suite_hash",
    ),
    "result": (
        "registered",
        "fingerprints",
        "served_models",
        "cases",
        "arms",
        "spent_usd",
        "budget_hit",
    ),
    "decision": ("result", "decision", "note"),
}
DECISIONS = ("adopted", "dropped", "shipped-unmeasured")
# The row a result or a decision names, keyed by the field that names it.
LINKS = {"result": "registered", "decision": "result"}

# Keys nested in a row: present, though a value may be null (no cases ran).
REGISTERED_ARM = ("name", "provider", "model", "docker")
ARM_SUMMARY = (
    "pass_k",
    "pass_at_1",
    "flaky",
    "false_backed",
    "backed_rate",
    "cost_usd",
    "wall_s",
    "aborted",
    "contained",
)
CASE_OUTCOME = (
    "case",
    "arm",
    "run",
    "status",
    "solved",
    "repair_f1",
    "calls",
    "new_work_tokens",
    "cost_usd",
    "wall_s",
)
WILSON = ("n", "N", "low", "high", "method", "level")


def _git(*args: str, cwd: str = ".") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _author() -> str:
    """git user.name, read per row; "unknown" where git has no identity (CI)."""
    try:
        name = _git("config", "user.name").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return name or "unknown"


def new_row(kind: str, issue: int, **fields) -> dict:
    """A row of `kind` for `issue`, stamped with schema_version, row_id, at
    and by. It only builds the row; append() validates it."""
    now = datetime.now(UTC)
    row_id = f"{kind}-{now:%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"
    return {
        **fields,
        "schema_version": SCHEMA_VERSION,
        "row_id": row_id,
        "kind": kind,
        "issue": issue,
        "at": now.isoformat(timespec="seconds"),
        "by": _author(),
    }


def _hash(root: str, files: list[str], head: bytes = b"") -> dict:
    """sha256 fed each file's path and the sha256 of its bytes, in order, so a
    byte moved between two files moves the hash. A missing file raises."""
    outer = hashlib.sha256(head)
    for rel in files:
        digest = hashlib.sha256((Path(root) / rel).read_bytes()).hexdigest()
        outer.update(f"{rel}\0{digest}\0".encode())
    return {"sha256": outer.hexdigest(), "files": list(files)}


def suite_hash(entries: list, files: list[str]) -> dict:
    """The hash of a suite: its case list, in order, plus its generator files."""
    head = json.dumps(list(entries), sort_keys=True).encode() + b"\0"
    return _hash(".", files, head)


def _dirty(root: str) -> bool:
    """Any tracked change, staged or not, except bench/ledger.jsonl itself."""
    status = _git(
        "status",
        "--porcelain",
        "-z",
        "--untracked-files=no",
        "--no-renames",
        cwd=root,
    )
    if status.returncode != 0:
        raise ValueError(f"git status failed in {root}: {status.stderr.strip()}")
    paths = [entry[3:] for entry in status.stdout.split("\0") if entry]
    return any(path != LEDGER.as_posix() for path in paths)


def fingerprints(root: str = ".") -> dict:
    """The code a run is measured against: the commit, whether the tree is
    dirty, and the prompt, referee and scorer hashes over the files on disk."""
    head = _git("rev-parse", "HEAD", cwd=root)
    if head.returncode != 0:
        raise ValueError(f"git rev-parse HEAD failed in {root}: {head.stderr.strip()}")
    return {
        "commit": head.stdout.strip(),
        "dirty": _dirty(root),
        "prompt": _hash(root, PROMPT_FILES),
        "referee": _hash(root, REFEREE_FILES),
        "scorer": _hash(root, SCORER_FILES),
    }


def wilson(n: int, N: int, level: float = 0.95) -> dict:
    """The Wilson score interval for n hits in N trials, clamped to [0, 1]."""
    if N < 1 or not 0 <= n <= N:
        raise ValueError(f"wilson needs 0 <= n <= N and N >= 1, got n={n}, N={N}")
    z = statistics.NormalDist().inv_cdf((1 + level) / 2)
    p = n / N
    scale = 1 + z * z / N
    center = (p + z * z / (2 * N)) / scale
    half = z * ((p * (1 - p) + z * z / (4 * N)) / N) ** 0.5 / scale
    low = 0.0 if n == 0 else max(0.0, center - half)
    high = 1.0 if n == N else min(1.0, center + half)
    return {
        "n": n,
        "N": N,
        "low": low,
        "high": high,
        "method": "wilson",
        "level": level,
    }


def quantiles(values: list[float]) -> dict | None:
    """p50 and p95 by the inclusive method; None for no values."""
    xs = sorted(values)
    if not xs:
        return None
    if len(xs) == 1:
        return {"p50": xs[0], "p95": xs[0]}
    cuts = statistics.quantiles(xs, n=20, method="inclusive")
    return {"p50": cuts[9], "p95": cuts[18]}


def _parse(data: bytes, path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} line {number} is not JSON: {exc.msg}") from exc
    return rows


def read(path: Path = LEDGER) -> list[dict]:
    """Every row in file order; [] when the file is missing."""
    path = Path(path)
    if not path.exists():
        return []
    return _parse(path.read_bytes(), path)


def rows(
    kind: str | None = None,
    issue: int | None = None,
    suite: str | None = None,
    path: Path = LEDGER,
) -> list[dict]:
    """The rows matching every filter given, in file order. Only a
    registration carries `suite`, so a result takes its registration's and a
    decision its result's; a decision naming no result is in no suite."""
    found, suite_of = [], {}
    for row in read(path):
        link = LINKS.get(row.get("kind"))
        row_suite = suite_of.get(row.get(link)) if link else row.get("suite")
        suite_of[row.get("row_id")] = row_suite
        if (
            (kind is None or row.get("kind") == kind)
            and (issue is None or row.get("issue") == issue)
            and (suite is None or row_suite == suite)
        ):
            found.append(row)
    return found


def _validate(row: dict) -> None:
    kind = row.get("kind")
    if kind not in REQUIRED:
        raise ValueError(f"kind must be one of {', '.join(REQUIRED)}, not {kind!r}")
    for field in BASE + REQUIRED[kind]:
        nullable = (
            kind == "decision"
            and field == "result"
            and row.get("decision") == "shipped-unmeasured"
        )
        if field not in row or (row[field] is None and not nullable):
            raise ValueError(f"a {kind} row needs {field}")
    if row["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    if type(row["issue"]) is not int:
        raise ValueError(f"issue must be an int, not {row['issue']!r}")
    if kind == "decision" and row["decision"] not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    if kind == "registered":
        for i, arm in enumerate(_each(row["arms"], list, "arms")):
            _need(arm, REGISTERED_ARM, f"arms.{i}", kind)
            if "effort" not in arm and "temperature" not in arm:
                raise ValueError(f"a {kind} row needs arms.{i}.effort or .temperature")
    if kind == "result":
        for i, case in enumerate(_each(row["cases"], list, "cases")):
            _need(case, CASE_OUTCOME, f"cases.{i}", kind)
        for name, summary in _each(row["arms"], dict, "arms").items():
            _need(summary, ARM_SUMMARY, f"arms.{name}", kind)
            for key in ("false_backed", "backed_rate"):
                where = f"arms.{name}.{key}"
                if summary[key] is None and not summary.get(f"{key}_reason"):
                    raise ValueError(f"a {kind} row needs {where}_reason")
                if summary[key] is not None:
                    _need(summary[key], WILSON, where, kind)
                    if summary[key]["method"] != "wilson":
                        raise ValueError(f"{where}.method must be wilson")


def _each(node, of: type, where: str):
    if not isinstance(node, of):
        shape = "a list" if of is list else "an object"
        raise ValueError(f"{where} must be {shape}")  # noqa: TRY004 — append refuses with ValueError only
    return node


def _need(node, keys: tuple, where: str, kind: str) -> None:
    """Refuse a nested object missing any of `keys`, naming its dotted path."""
    _each(node, dict, where)
    for key in keys:
        if key not in node:
            raise ValueError(f"a {kind} row needs {where}.{key}")


def append(row: dict, path: Path = LEDGER) -> None:
    """Validate `row`, check its link and the file, then append it as one
    sort_keys JSON line, flushed and fsynced. Every refusal is a ValueError
    (an unencodable value included) and leaves the file as it was."""
    path = Path(path)
    _validate(row)
    try:
        line = json.dumps(row, sort_keys=True, allow_nan=False) + "\n"
    except TypeError as exc:
        raise ValueError(f"{row['row_id']} is not JSON: {exc}") from exc
    data = path.read_bytes() if path.exists() else b""
    if data and not data.endswith(b"\n"):
        raise ValueError(f"{path} does not end in a newline: a torn write")
    existing = _parse(data, path)
    if any(r.get("row_id") == row["row_id"] for r in existing):
        raise ValueError(f"{row['row_id']} is already in {path}")
    link = LINKS.get(row["kind"])
    named = link and row[link] is not None
    if named and not any(
        r.get("kind") == link and r.get("row_id") == row[link] for r in existing
    ):
        raise ValueError(
            f"{row['row_id']} names {link} {row[link]!r}, which is not a "
            f"{link} row in {path}"
        )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def _line(row: dict) -> str:
    """One line for `show`: the row's id, issue, kind and headline numbers,
    never a per-case name."""
    kind = row.get("kind")
    if kind == "registered":
        arms = ",".join(str(arm.get("name")) for arm in row["arms"])
        body = (
            f"{row['suite']} ({row['split']}) k={row['k']} arms {arms} "
            f"primary {row['primary']} budget ${row['budget_usd']}"
        )
    elif kind == "result":
        arms = "; ".join(
            f"{name} pass@1 {s.get('pass_at_1')} pass^k {s.get('pass_k')} "
            f"flaky {len(s.get('flaky') or [])} aborted {s.get('aborted')}"
            for name, s in row["arms"].items()
        )
        hit = " (budget hit)" if row["budget_hit"] else ""
        body = f"of {row['registered']}: {arms}; spent ${row['spent_usd']}{hit}"
    else:
        body = f"{row['decision']} result {row['result'] or '-'}: {row['note']}"
    return " ".join(f"{row['row_id']}  #{row['issue']}  {kind}  {body}".split())


def _check(issue: int) -> int:
    decisions = rows(kind="decision", issue=issue)
    for dec in decisions:
        if dec.get("decision") == "shipped-unmeasured":
            print(f"#{issue}: shipped-unmeasured ({dec['row_id']})")
            return 0
    adopted = [d for d in decisions if d.get("decision") == "adopted"]
    stale = []
    if adopted:
        today = _hash(".", PROMPT_FILES)["sha256"]
        results = {r.get("row_id"): r for r in rows(kind="result")}
        for dec in adopted:
            prompt = (results.get(dec.get("result")) or {}).get("fingerprints") or {}
            measured = (prompt.get("prompt") or {}).get("sha256")
            if measured == today:
                print(f"#{issue}: adopted ({dec['row_id']}) on today's prompts.py")
                return 0
            stale.append(f"{dec['row_id']} was measured on {str(measured)[:12]}")
        stale = [f"today's prompts.py is {today[:12]}", *stale]
    print(
        f"#{issue}: no adopted decision on today's prompts.py and no "
        "shipped-unmeasured decision in the ledger"
        + (f" ({'; '.join(stale)})" if stale else "")
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The eval ledger (EV4)")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show", help="one line per row, no per-case detail")
    show.add_argument("--issue", type=int)
    show.add_argument("--suite")
    check = sub.add_parser("check", help="exit 0 if the issue may ship")
    check.add_argument("--issue", type=int, required=True)
    args = parser.parse_args(argv)

    if args.command == "check":
        return _check(args.issue)
    for row in rows(issue=args.issue, suite=args.suite):
        print(_line(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
