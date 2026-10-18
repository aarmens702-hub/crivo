"""bench.ledger units (spec: specs/2026-10-17-eval-tooling.md EV4, #67).

Offline and keyless: the ledger is stdlib over a JSONL file and git. Every test
writes a tmp ledger, through an explicit `path=` or a chdir into a tmp repo, and
never the real bench/ledger.jsonl.
"""

import importlib
import importlib.util
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# The files fingerprints() hashes, as a tmp repo holds them.
HASHED = {
    "src/crivo/prompts.py": 'SYSTEM = "You are crivo, a data analyst."\n',
    "src/crivo/verify.py": "def verify(before, after):\n    return []\n",
    "src/crivo/diff.py": "def diff(before, after):\n    return {}\n",
    "bench/score.py": "def score(truth, found):\n    return 0.0\n",
    "bench/consistency.py": "def consistency(rows):\n    return 1.0\n",
}
GENERATORS = ["bench/corpus.py", "bench/bases.py", "bench/corrupt.py", "bench/truth.py"]

# A fingerprint as a row stores it (decision 1 on #67: {"sha256", "files"}).
FP = {
    "commit": "2b326f4" + "0" * 33,
    "dirty": False,
    "prompt": {"sha256": "3f" * 32, "files": ["src/crivo/prompts.py"]},
    "referee": {
        "sha256": "a1" * 32,
        "files": ["src/crivo/verify.py", "src/crivo/diff.py"],
    },
    "scorer": {
        "sha256": "5c" * 32,
        "files": ["bench/score.py", "bench/consistency.py"],
    },
}
SUITE_HASH = {"sha256": "c4" * 32, "files": GENERATORS}
ARM = {
    "provider": "claude",
    "model": "claude-opus-5-5",
    "effort": "high",
    "docker": True,
}
CASE = "s07_mixed_date_formats"  # a per-case name `show` must not print


def _ledger():
    """bench.ledger, imported per test, so a missing module fails each test on
    this assert instead of erroring the whole file at collection."""
    assert importlib.util.find_spec("bench.ledger") is not None, (
        "bench/ledger.py does not exist yet (#67)"
    )
    return importlib.import_module("bench.ledger")


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@x"]
        + ["-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    ).stdout.strip()


def _repo(root, monkeypatch):
    """A committed tmp repo holding the hashed files, bench/ledger.py and an
    empty, tracked bench/ledger.jsonl."""
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)
    files = {**HASHED, "bench/ledger.py": "LEDGER = None\n", "bench/ledger.jsonl": ""}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--no-verify", "-m", "seed")
    return root


def _registered(ledger, fp=FP, issue=67, suite="agent-clean-smoke"):
    return ledger.new_row(
        "registered",
        issue,
        suite=suite,
        split="dev",
        arms=[{"name": "a1", **ARM}, {"name": "a2", **ARM}],
        k=3,
        hypothesis="two identical arms differ by no more than the noise floor",
        primary="pass_at_1",
        guards=["false_backed", "aborted"],
        rule="record the A/A spread as the noise floor; adopt nothing",
        budget_usd=5.0,
        per_case_usd=0.5,
        fingerprints=fp,
        suite_hash=SUITE_HASH,
    )


def _outcome(arm, case, status, solved, f1, calls, tokens, cost, wall):
    return {
        "case": case,
        "arm": arm,
        "run": 1,
        "status": status,
        "solved": solved,
        "repair_f1": f1,
        "calls": calls,
        "new_work_tokens": tokens,
        "cost_usd": cost,
        "wall_s": wall,
    }


def _arm_summary(cost, wall):
    return {
        "pass_k": 0.5,
        "pass_at_1": 0.6667,
        "flaky": ["s12_zip_leading_zeros"],
        "false_backed": None,
        "false_backed_reason": "the suite plants no false-backed cases (ED1)",
        "backed_rate": {
            "n": 5,
            "N": 6,
            "low": 0.4365,
            "high": 0.9699,
            "method": "wilson",
            "level": 0.95,
        },
        "cost_usd": cost,
        "wall_s": wall,
        "aborted": 1,
        "contained": "docker",
    }


def _result(ledger, registered_id, fp=FP, issue=67):
    return ledger.new_row(
        "result",
        issue,
        registered=registered_id,
        fingerprints=fp,
        served_models={"a1": ["claude-opus-5-5"], "a2": ["claude-opus-5-5"]},
        cases=[
            _outcome("a1", CASE, "ok", True, 0.875, 6, 4210, 0.0412, 38.2),
            _outcome("a2", CASE, "ok", True, 0.875, 7, 4630, 0.0455, 41.9),
            _outcome(
                "a1",
                "s12_zip_leading_zeros",
                "aborted: wall cap 300s hit",
                False,
                None,
                19,
                20117,
                0.2093,
                300.0,
            ),
            _outcome(
                "a2", "s12_zip_leading_zeros", "ok", False, 0.5, 9, 6120, 0.0611, 77.4
            ),
        ],
        arms={
            "a1": _arm_summary(
                {"p50": 0.1253, "p95": 0.2009}, {"p50": 169.1, "p95": 286.9}
            ),
            "a2": _arm_summary(
                {"p50": 0.0533, "p95": 0.0603}, {"p50": 59.65, "p95": 75.63}
            ),
        },
        spent_usd=0.3571,
        budget_hit=False,
        noise_floor={"pass_at_1": 0.1667},
    )


def _decision(ledger, result_id, decision="adopted", issue=67):
    return ledger.new_row(
        "decision",
        issue,
        result=result_id,
        decision=decision,
        note="A/A floor recorded at k=3",
    )


def _empty(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.touch()
    return path


def test_rows_round_trip_through_append_and_read(tmp_path):
    """#67: a registered, a result and a decision row land as one
    sort_keys JSON line each, starting from an empty file, and read back
    equal."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    dec = _decision(ledger, res["row_id"])

    for row in (reg, res, dec):
        ledger.append(row, path=path)

    assert ledger.read(path) == [reg, res, dec]
    text = path.read_text()
    assert text.endswith("\n")
    assert text.splitlines() == [json.dumps(r, sort_keys=True) for r in (reg, res, dec)]


@pytest.mark.parametrize(
    "gitconfig, by",
    [
        ("[user]\n\tname = Test Writer\n\temail = tw@x\n", "Test Writer"),
        ("", "unknown"),  # CI has no git identity
    ],
    ids=["git-user", "no-identity"],
)
def test_new_row_stamps_version_id_time_and_author(
    tmp_path, monkeypatch, gitconfig, by
):
    """#67: new_row stamps schema_version, a `<kind>-<UTC stamp>-<6 hex>`
    row_id, a UTC `at` and `by` from git user.name ("unknown" without one)."""
    ledger = _ledger()
    config = tmp_path / "gitconfig"
    config.write_text(gitconfig)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.chdir(tmp_path)

    row = _decision(ledger, None, "shipped-unmeasured")
    again = _decision(ledger, None, "shipped-unmeasured")

    assert ledger.LEDGER == Path("bench/ledger.jsonl")
    assert row["schema_version"] == ledger.SCHEMA_VERSION == 1
    assert (row["kind"], row["issue"], row["decision"]) == (
        "decision",
        67,
        "shipped-unmeasured",
    )
    assert re.fullmatch(r"decision-\d{8}T\d{6}-[0-9a-f]{6}", row["row_id"])
    assert row["row_id"] != again["row_id"]
    assert datetime.fromisoformat(row["at"]).utcoffset() == timedelta(0)
    assert row["by"] == by


@pytest.mark.parametrize(
    "kind, field",
    [
        ("registered", "hypothesis"),
        ("registered", "per_case_usd"),
        ("registered", "fingerprints"),
        ("registered", "suite_hash"),
        ("registered", "schema_version"),
        ("result", "registered"),
        ("result", "served_models"),
        ("result", "budget_hit"),
        ("decision", "note"),
        ("decision", "row_id"),
    ],
)
def test_append_refuses_a_row_missing_a_required_field(tmp_path, kind, field):
    """#67: append only validates, so a row missing a field its kind needs is
    refused with a ValueError naming that field, and nothing is written."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    ledger.append(reg, path=path)
    ledger.append(res, path=path)
    row = {
        "registered": _registered(ledger),
        "result": _result(ledger, reg["row_id"]),
        "decision": _decision(ledger, res["row_id"]),
    }[kind]
    del row[field]
    before = path.read_bytes()

    with pytest.raises(ValueError, match=rf"\b{field}\b"):
        ledger.append(row, path=path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "kind, field, value",
    [
        ("registered", "issue", "67"),  # check --issue and rows() key on an int
        ("result", "spent_usd", float("nan")),  # not JSON; allow_nan=False
        ("decision", "decision", "maybe"),
        ("registered", "schema_version", 2),  # no migrations (out of scope)
        ("registered", "hypothesis", None),  # present but empty is still missing
    ],
    ids=[
        "issue-as-str",
        "nan",
        "unknown-decision",
        "schema-version-2",
        "null-hypothesis",
    ],
)
def test_append_refuses_a_bad_value(tmp_path, kind, field, value):
    """#67: an issue that is not an int, a NaN, a decision outside adopted,
    dropped and shipped-unmeasured, a schema_version other than 1 and a
    required field set to null are refused unwritten."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    ledger.append(reg, path=path)
    ledger.append(res, path=path)
    row = {
        "registered": _registered(ledger),
        "result": _result(ledger, reg["row_id"]),
        "decision": _decision(ledger, res["row_id"]),
    }[kind]
    row[field] = value
    before = path.read_bytes()

    with pytest.raises(ValueError):
        ledger.append(row, path=path)
    assert path.read_bytes() == before


def _without(row, *keys):
    """Delete row[keys[0]]...[keys[-1]], a field nested in a row."""
    node = row
    for key in keys[:-1]:
        node = node[key]
    del node[keys[-1]]


@pytest.mark.parametrize(
    "kind, keys, named",
    [
        ("result", ("arms", "a2", "contained"), r"arms\.a2\.contained"),
        (
            "result",
            ("arms", "a1", "false_backed_reason"),  # false_backed is null
            r"arms\.a1\.false_backed_reason",
        ),
        ("result", ("cases", 2, "status"), r"cases\.2\.status"),
        ("registered", ("arms", 1, "model"), r"arms\.(1|a2)\.model"),
    ],
    ids=["arm-contained", "false-backed-reason", "case-status", "registered-arm-model"],
)
def test_append_refuses_a_row_missing_a_nested_field(tmp_path, kind, keys, named):
    """#67: a field a row's arms or per-case outcomes need is required too;
    the ValueError names its path, and nothing is written."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    ledger.append(reg, path=path)
    row = {
        "registered": _registered(ledger),
        "result": _result(ledger, reg["row_id"]),
    }[kind]
    _without(row, *keys)
    before = path.read_bytes()

    with pytest.raises(ValueError, match=named):
        ledger.append(row, path=path)
    assert path.read_bytes() == before


def test_append_accepts_a_result_with_no_cases_after_a_budget_hit(tmp_path):
    """#67: a run stopped by its budget before any case still writes its
    result row, with an empty cases list."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    res["cases"] = []
    res["budget_hit"] = True
    ledger.append(reg, path=path)

    ledger.append(res, path=path)

    assert ledger.read(path) == [reg, res]


def test_append_accepts_a_measured_false_backed_without_a_reason(tmp_path):
    """#67: false_backed_reason is required only beside a null false_backed."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    for summary in res["arms"].values():
        summary["false_backed"] = ledger.wilson(0, 6)
        del summary["false_backed_reason"]
    ledger.append(reg, path=path)

    ledger.append(res, path=path)

    assert ledger.read(path) == [reg, res]


def test_append_refuses_the_same_row_twice(tmp_path):
    """#67: a row id lands once; a retried append leaves the file as it was."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    ledger.append(reg, path=path)
    before = path.read_bytes()

    with pytest.raises(ValueError):
        ledger.append(reg, path=path)
    assert path.read_bytes() == before


def test_append_refuses_a_result_whose_registration_is_not_in_the_file(tmp_path):
    """#67: a result names its registration, so it can't land before it;
    once the registration is in, the same result lands."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])

    with pytest.raises(ValueError):
        ledger.append(res, path=path)
    assert path.read_bytes() == b""

    ledger.append(reg, path=path)
    ledger.append(res, path=path)
    assert [r["row_id"] for r in ledger.read(path)] == [reg["row_id"], res["row_id"]]


@pytest.mark.parametrize(
    "names, decision",
    [
        ("an-unwritten-result", "adopted"),
        ("the-registration", "adopted"),  # in the file, but not a result
        ("nothing", "adopted"),
        ("nothing", "dropped"),
    ],
)
def test_append_refuses_a_decision_whose_result_is_not_in_the_file(
    tmp_path, names, decision
):
    """#67: an adopted or dropped decision names a result row in the file;
    the same decision naming the real result lands."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    ledger.append(reg, path=path)
    ledger.append(res, path=path)
    target = {
        "an-unwritten-result": _result(ledger, reg["row_id"])["row_id"],
        "the-registration": reg["row_id"],
        "nothing": None,
    }[names]
    before = path.read_bytes()

    with pytest.raises(ValueError):
        ledger.append(_decision(ledger, target, decision), path=path)
    assert path.read_bytes() == before

    ledger.append(_decision(ledger, res["row_id"], decision), path=path)
    assert [r["kind"] for r in ledger.read(path)] == [
        "registered",
        "result",
        "decision",
    ]


def test_a_shipped_unmeasured_decision_names_no_result(tmp_path):
    """#67 (ED6): a shipped-unmeasured decision carries result: null and needs
    nothing else in the file, only its issue."""
    ledger = _ledger()
    path = _empty(tmp_path)
    dec = _decision(ledger, None, "shipped-unmeasured", issue=48)

    ledger.append(dec, path=path)

    assert ledger.read(path) == [dec]


@pytest.mark.parametrize("cut", [1, 40], ids=["lost-newline", "cut-mid-row"])
def test_append_refuses_a_file_whose_last_line_is_cut_short(tmp_path, cut):
    """#67: a torn write (the last line cut short, even by its newline alone)
    is refused, so a new row never fuses with a broken one."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    ledger.append(reg, path=path)
    ledger.append(res, path=path)
    torn = path.read_bytes()[:-cut]
    path.write_bytes(torn)

    with pytest.raises(ValueError):
        ledger.append(_decision(ledger, res["row_id"]), path=path)
    assert path.read_bytes() == torn


@pytest.mark.parametrize(
    "n, N, low, high",
    [
        (0, 30, 0.0, 0.1135),  # hand-checked: (z²/N) / (1 + z²/N), z = 1.96
        (3, 30, 0.0346, 0.2562),
        (30, 30, 0.8865, 1.0),
    ],
)
def test_wilson_matches_hand_checked_bounds(n, N, low, high):
    """#67: wilson(n, N) is the row's {n, N, low, high, method, level} at 95%."""
    ledger = _ledger()

    interval = ledger.wilson(n, N)

    assert (round(interval["low"], 4), round(interval["high"], 4)) == (low, high)
    assert {k: interval[k] for k in ("n", "N", "method", "level")} == {
        "n": n,
        "N": N,
        "method": "wilson",
        "level": 0.95,
    }


def test_wilson_stays_inside_zero_and_one():
    """#67: float error at n = 0 and n = N never leaves [0, 1]."""
    ledger = _ledger()

    for N in range(1, 61):
        for n in (0, N):
            interval = ledger.wilson(n, N)
            assert 0.0 <= interval["low"] <= interval["high"] <= 1.0, (n, N)


@pytest.mark.parametrize("n, N", [(31, 30), (-1, 30), (0, 0)])
def test_wilson_refuses_an_impossible_count(n, N):
    """#67: more hits than trials, fewer than none, or no trials at all is a
    bug upstream, not an interval."""
    ledger = _ledger()

    with pytest.raises(ValueError):
        ledger.wilson(n, N)


@pytest.mark.parametrize(
    "values, expected",
    [
        ([], None),
        ([0.0412], {"p50": 0.0412, "p95": 0.0412}),
        # run order, unsorted; the inclusive method keeps p95 under the max
        # (hand-checked: 38.2 * 0.1 + 300.0 * 0.9 = 273.82)
        ([38.2, 300.0, 12.5], {"p50": 38.2, "p95": 273.82}),
    ],
    ids=["empty", "one-run", "three-runs"],
)
def test_quantiles_give_p50_and_p95(values, expected):
    """#67: quantiles is p50 and p95, None for no values, and works on one."""
    ledger = _ledger()

    got = ledger.quantiles(values)

    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_fingerprints_change_when_prompts_changes_by_one_byte(tmp_path, monkeypatch):
    """#67: the prompt hash covers the bytes of prompts.py on disk; one byte
    moves it and nothing else, and each hash lists its files in order."""
    ledger = _ledger()
    root = _repo(tmp_path, monkeypatch)

    before = ledger.fingerprints(str(root))
    prompts = root / "src/crivo/prompts.py"
    prompts.write_bytes(prompts.read_bytes().replace(b"crivo", b"crivO"))
    after = ledger.fingerprints(str(root))

    assert before["commit"] == _git(root, "rev-parse", "HEAD")
    assert before["dirty"] is False
    assert before["prompt"]["files"] == ["src/crivo/prompts.py"]
    assert before["referee"]["files"] == ["src/crivo/verify.py", "src/crivo/diff.py"]
    assert before["scorer"]["files"] == ["bench/score.py", "bench/consistency.py"]
    assert re.fullmatch(r"[0-9a-f]{64}", before["prompt"]["sha256"])
    assert after["prompt"]["sha256"] != before["prompt"]["sha256"]
    assert (after["referee"], after["scorer"]) == (before["referee"], before["scorer"])
    assert after["dirty"] is True


@pytest.mark.parametrize(
    "edited, staged, dirty",
    [
        (["bench/ledger.jsonl"], False, False),
        (["bench/ledger.jsonl"], True, False),
        (["notes.txt"], False, False),  # untracked never counts
        (["bench/ledger.jsonl", "src/crivo/diff.py"], False, True),
        (["bench/ledger.py"], False, True),  # shares the ledger's prefix only
        (["src/crivo/verify.py"], True, True),  # staged counts
    ],
    ids=[
        "ledger",
        "ledger-staged",
        "untracked",
        "ledger-and-code",
        "ledger-py",
        "staged-code",
    ],
)
def test_dirty_ignores_a_change_to_the_ledger_file_alone(
    tmp_path, monkeypatch, edited, staged, dirty
):
    """#67: dirty is any tracked change except bench/ledger.jsonl itself."""
    ledger = _ledger()
    root = _repo(tmp_path, monkeypatch)
    for rel in edited:
        with open(root / rel, "a") as fh:
            fh.write("# edited\n")
    if staged:
        _git(root, "add", *edited)

    assert ledger.fingerprints(str(root))["dirty"] is dirty


def test_a_multi_file_hash_moves_when_a_byte_moves_between_its_files(
    tmp_path, monkeypatch
):
    """#67: the referee hash keeps each file's bytes apart, so moving a byte
    from verify.py to diff.py changes it; the same bytes hash the same."""
    ledger = _ledger()
    root = _repo(tmp_path, monkeypatch)
    verify, diff = root / "src/crivo/verify.py", root / "src/crivo/diff.py"

    verify.write_bytes(b"ab")
    diff.write_bytes(b"c")
    first = ledger.fingerprints(str(root))["referee"]["sha256"]
    again = ledger.fingerprints(str(root))["referee"]["sha256"]
    verify.write_bytes(b"a")
    diff.write_bytes(b"bc")
    moved = ledger.fingerprints(str(root))["referee"]["sha256"]

    assert first == again
    assert moved != first


def test_fingerprints_refuse_a_missing_hashed_file(tmp_path, monkeypatch):
    """#67: a hashed file that is gone is an error, not a hash of nothing."""
    ledger = _ledger()
    root = _repo(tmp_path, monkeypatch)
    (root / "bench/consistency.py").unlink()

    with pytest.raises((FileNotFoundError, ValueError), match="consistency.py"):
        ledger.fingerprints(str(root))


def test_suite_hash_covers_the_case_list_and_its_generator_files(tmp_path, monkeypatch):
    """#67: suite_hash moves with the case list and with one byte of a
    generator file, and lists the generator files."""
    ledger = _ledger()
    monkeypatch.chdir(tmp_path)
    for rel in GENERATORS:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(f"# {rel}\nSEED = 7\n")
    cases = [CASE, "s12_zip_leading_zeros", "s19_sentinel_9999"]

    full = ledger.suite_hash(cases, GENERATORS)
    fewer = ledger.suite_hash(cases[:2], GENERATORS)
    corrupt = tmp_path / "bench/corrupt.py"
    corrupt.write_text(corrupt.read_text().replace("7", "8"))
    regenerated = ledger.suite_hash(cases, GENERATORS)

    assert full["files"] == GENERATORS
    assert re.fullmatch(r"[0-9a-f]{64}", full["sha256"])
    assert fewer["sha256"] != full["sha256"]
    assert regenerated["sha256"] != full["sha256"]


def test_rows_filter_by_kind_issue_and_suite(tmp_path):
    """#67: rows(kind, issue, suite, path) keeps file order."""
    ledger = _ledger()
    path = _empty(tmp_path)
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    dec = _decision(ledger, res["row_id"])
    trap = _registered(ledger, issue=66, suite="agent-trap-smoke")
    unmeasured = _decision(ledger, None, "shipped-unmeasured", issue=66)
    for row in (reg, res, dec, trap, unmeasured):
        ledger.append(row, path=path)

    def ids(rows):
        return [r["row_id"] for r in rows]

    assert ids(ledger.rows(path=path)) == ids([reg, res, dec, trap, unmeasured])
    assert ids(ledger.rows(kind="result", path=path)) == ids([res])
    assert ids(ledger.rows(issue=66, path=path)) == ids([trap, unmeasured])
    assert ids(ledger.rows(kind="decision", issue=67, path=path)) == ids([dec])
    assert ids(
        ledger.rows(kind="registered", suite="agent-trap-smoke", path=path)
    ) == ids([trap])


def _two_suites(ledger, path):
    """Two suites' rows, interleaved as runs would land them, plus an issue-66
    shipped-unmeasured decision that names no result and so no suite."""
    smoke = _registered(ledger)
    trap = _registered(ledger, issue=66, suite="agent-trap-smoke")
    smoke_res = _result(ledger, smoke["row_id"])
    trap_res = _result(ledger, trap["row_id"], issue=66)
    unmeasured = _decision(ledger, None, "shipped-unmeasured", issue=66)
    smoke_dec = _decision(ledger, smoke_res["row_id"])
    landed = [smoke, trap, smoke_res, trap_res, unmeasured, smoke_dec]
    for row in landed:
        ledger.append(row, path=path)
    return landed


def test_rows_find_a_suites_results_and_decisions_through_their_links(tmp_path):
    """#67: only a registration carries `suite`, so rows(suite=S) follows the
    links: S's registrations, the results naming them and the decisions naming
    those, in file order. A decision that names no result is in no suite."""
    ledger = _ledger()
    path = _empty(tmp_path)
    smoke, trap, smoke_res, trap_res, unmeasured, smoke_dec = _two_suites(ledger, path)

    def ids(rows):
        return [r["row_id"] for r in rows]

    assert ids(ledger.rows(suite="agent-clean-smoke", path=path)) == ids(
        [smoke, smoke_res, smoke_dec]
    )
    assert ids(ledger.rows(kind="result", suite="agent-clean-smoke", path=path)) == ids(
        [smoke_res]
    )
    assert ids(ledger.rows(suite="agent-trap-smoke", path=path)) == ids(
        [trap, trap_res]
    )
    assert ids(ledger.rows(issue=66, suite="agent-trap-smoke", path=path)) == ids(
        [trap, trap_res]
    )
    assert ids(ledger.rows(issue=66, path=path))[-1] == unmeasured["row_id"]
    for suite in ("agent-clean-smoke", "agent-trap-smoke"):
        assert ledger.rows(kind="decision", issue=66, suite=suite, path=path) == []


def test_show_prints_one_line_per_row_without_per_case_detail(
    tmp_path, monkeypatch, capsys
):
    """#67: `show --issue N` prints one line per row of that issue, and no
    per-case outcome."""
    ledger = _ledger()
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "bench" / "ledger.jsonl"
    path.parent.mkdir()
    path.touch()
    reg = _registered(ledger)
    res = _result(ledger, reg["row_id"])
    dec = _decision(ledger, res["row_id"])
    other = _decision(ledger, None, "shipped-unmeasured", issue=66)
    for row in (reg, res, dec, other):
        ledger.append(row, path=path)

    assert ledger.main(["show", "--issue", "67"]) == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]

    assert len(lines) == 3
    for row, line in zip((reg, res, dec), lines, strict=True):
        assert row["row_id"] in line
    assert other["row_id"] not in out
    assert CASE not in out


def test_show_by_suite_prints_its_results_and_decisions(tmp_path, monkeypatch, capsys):
    """#67: `show --suite S` lists S's registration, result and decision, one
    line each, and nothing of another suite or of an unlinked decision."""
    ledger = _ledger()
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "bench" / "ledger.jsonl"
    path.parent.mkdir()
    path.touch()
    smoke, trap, smoke_res, trap_res, unmeasured, smoke_dec = _two_suites(ledger, path)

    assert ledger.main(["show", "--suite", "agent-clean-smoke"]) == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]

    assert len(lines) == 3
    for row, line in zip((smoke, smoke_res, smoke_dec), lines, strict=True):
        assert row["row_id"] in line
    for row in (trap, trap_res, unmeasured):
        assert row["row_id"] not in out


@pytest.mark.parametrize(
    "decision, issue, stale, code",
    [
        ("adopted", 67, False, 0),
        ("shipped-unmeasured", 67, False, 0),
        ("adopted", 67, True, 1),  # prompts.py moved after the measurement
        ("dropped", 67, False, 1),
        (None, 67, False, 1),  # measured, never decided
        ("shipped-unmeasured", 66, False, 1),  # another issue's row
    ],
    ids=[
        "adopted-on-todays-prompt",
        "shipped-unmeasured",
        "adopted-on-a-stale-prompt",
        "dropped",
        "undecided",
        "other-issue",
    ],
)
def test_check_passes_on_a_current_adoption_or_an_unmeasured_ship(
    tmp_path, monkeypatch, capsys, decision, issue, stale, code
):
    """#67: `check --issue 67` exits 0 on an adopted decision whose result ran
    on today's prompts.py, or a shipped-unmeasured decision; otherwise 1,
    naming both."""
    ledger = _ledger()
    root = _repo(tmp_path, monkeypatch)
    monkeypatch.chdir(root)
    path = root / "bench" / "ledger.jsonl"
    if decision == "shipped-unmeasured":
        ledger.append(_decision(ledger, None, decision, issue=issue), path=path)
    else:
        fp = ledger.fingerprints(".")
        reg = _registered(ledger, fp, issue=issue)
        res = _result(ledger, reg["row_id"], fp, issue=issue)
        ledger.append(reg, path=path)
        ledger.append(res, path=path)
        if decision:
            ledger.append(_decision(ledger, res["row_id"], decision, issue), path=path)
    if stale:
        prompts = root / "src/crivo/prompts.py"
        prompts.write_bytes(prompts.read_bytes().replace(b"crivo", b"crivO"))

    assert ledger.main(["check", "--issue", "67"]) == code
    if code:
        said = "".join(capsys.readouterr())
        assert "adopted" in said
        assert "shipped-unmeasured" in said


def test_check_reads_a_missing_ledger_as_empty_and_exits_1(tmp_path, monkeypatch):
    """#67: no ledger file is no rows, not a crash."""
    ledger = _ledger()
    root = _repo(tmp_path, monkeypatch)
    (root / "bench" / "ledger.jsonl").unlink()
    monkeypatch.chdir(root)

    assert ledger.read(Path("bench/ledger.jsonl")) == []
    assert ledger.main(["check", "--issue", "67"]) == 1


def test_check_takes_the_issue_as_an_int():
    """#67: `--issue #67` is a usage error (exit 2), never a silent miss."""
    ledger = _ledger()

    with pytest.raises(SystemExit) as exit_info:
        ledger.main(["check", "--issue", "#67"])
    assert exit_info.value.code == 2
