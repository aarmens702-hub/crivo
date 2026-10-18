"""scripts/check_locks.py (spec: specs/2026-10-17-eval-tooling.md EV11, #74).

check_locks keeps bench/ledger.jsonl append-only and its rows true to the code
they ran: every commit that touched the ledger only appends to it, every result
names an earlier registration with the same suite hash, scorer and referee
hashes, arms and k, and every adopted behaviour decision's hashes match the
files of the commit that landed it.

Offline and keyless: check_locks is stdlib over git and bench.ledger. Every test
builds a tmp git repo and writes its ledger at runtime, through ledger.append
or a raw line where append would refuse the row; never the real
bench/ledger.jsonl.
"""

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bench import ledger

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_locks.py"
sys.path.insert(0, str(ROOT / "scripts"))

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
# The task-branch commit a row was measured on, which /ship's rebase replaced:
# it is in no tmp repo, so check_locks must hash the commit that landed a line.
BRANCH_COMMIT = "9e1f0c7d" * 5


def _check_locks():
    """scripts/check_locks.py, imported per test, so a missing script fails
    each test on this assert instead of erroring the whole file."""
    assert importlib.util.find_spec("check_locks") is not None, (
        "scripts/check_locks.py does not exist yet (#74)"
    )
    return importlib.import_module("check_locks")


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@x"]
        + ["-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    ).stdout.strip()


def _clean_git_env(monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)


def _repo(root, monkeypatch, seed_ledger=True):
    """A committed tmp repo holding the hashed files and, unless told not to,
    an empty, tracked bench/ledger.jsonl."""
    _clean_git_env(monkeypatch)
    root.mkdir(parents=True, exist_ok=True)
    files = {**HASHED, "README.md": "# a tmp repo\n"}
    if seed_ledger:
        files[ledger.LEDGER.as_posix()] = ""
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q")
    _commit(root, "seed")
    return root


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--no-verify", "--allow-empty", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _land(root, *rows, raw=False, message="ledger: append"):
    """Append rows to the tmp ledger and commit them; returns the commit. A
    raw line is what append would refuse (a result whose link is wrong)."""
    path = root / ledger.LEDGER
    for row in rows:
        if raw:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        else:
            ledger.append(row, path=path)
    return _commit(root, message)


def _registered(fp=FP, issue=48, split="dev", type_="behaviour"):
    """A registration as #71's register writes it: with the issue's work type,
    or with none (an untyped row is checked as behaviour)."""
    typed = {} if type_ is None else {"type": type_}
    return ledger.new_row(
        "registered",
        issue,
        **typed,
        suite="agent-clean-smoke",
        split=split,
        arms=[{"name": "a1", **ARM}, {"name": "a2", **ARM}],
        k=3,
        hypothesis="the ISO-date hint lifts pass@1 on mixed-date cases",
        primary="pass_at_1",
        guards=["false_backed", "aborted"],
        rule="adopt if pass@1 rises by more than the A/A noise floor",
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
        "backed_rate": None,
        "backed_rate_reason": "no verdicts exist before 0b",
        "cost_usd": cost,
        "wall_s": wall,
        "aborted": 1,
        "contained": "docker",
    }


def _result(registered_id, fp=FP, issue=48):
    """A result as #71's runner writes it: the suite hash and k it ran, under
    the registration's names."""
    return ledger.new_row(
        "result",
        issue,
        registered=registered_id,
        fingerprints=fp,
        suite_hash=SUITE_HASH,
        k=3,
        served_models={"a1": ["claude-opus-5-5"], "a2": ["claude-opus-5-5"]},
        cases=[
            _outcome(
                "a1", "s07_mixed_date_formats", "ok", True, 0.875, 6, 4210, 0.04, 38.2
            ),
            _outcome(
                "a2",
                "s12_zip_leading_zeros",
                "aborted: wall cap 300s hit",
                False,
                None,
                19,
                20117,
                0.2093,
                300.0,
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
    )


def _decision(result_id, decision="adopted", issue=48):
    return ledger.new_row(
        "decision",
        issue,
        result=result_id,
        decision=decision,
        note="pass@1 rose past the noise floor at k=3",
    )


def _said(capsys):
    captured = capsys.readouterr()
    return [ln for ln in (captured.out + captured.err).splitlines() if ln.strip()]


@pytest.mark.parametrize(
    "change",
    [
        "append",
        "edit-earlier-line",
        "remove-earlier-line",
        "remove-last-line",
        "delete-file",
    ],
)
def test_a_commit_may_only_append_to_the_ledger(tmp_path, monkeypatch, change):
    """#74 step 1: each commit that touched the ledger keeps the file at its
    parent as a prefix. An appended line passes; an edited or removed line,
    or a deleted file (even one recreated later), fails naming that commit and
    no other."""
    locks = _check_locks()
    root = _repo(tmp_path, monkeypatch)
    path = root / ledger.LEDGER
    first = _land(root, _registered(), message="register #48")
    second = _land(root, _decision(None, "shipped-unmeasured", issue=50))
    lines = path.read_text().splitlines(keepends=True)
    if change == "append":
        ledger.append(_decision(None, "shipped-unmeasured", issue=52), path=path)
    elif change == "edit-earlier-line":
        row = json.loads(lines[0])
        row["hypothesis"] = "the ISO-date hint lifts pass^k on every case"
        path.write_text(json.dumps(row, sort_keys=True) + "\n" + "".join(lines[1:]))
    elif change == "remove-earlier-line":
        path.write_text("".join(lines[1:]))
    elif change == "remove-last-line":
        path.write_text("".join(lines[:-1]))
    else:
        path.unlink()
    changed = _commit(root, change)
    after = _land(root, _decision(None, "shipped-unmeasured", issue=53))

    violations = locks.check(str(root))

    if change == "append":
        assert violations == []
        return
    assert any(changed[:7] in v for v in violations), (
        f"no violation names the {change} commit {changed[:7]}: {violations}"
    )
    for good in (first, second, after):
        assert not any(good[:7] in v for v in violations), (good[:7], violations)


@pytest.mark.parametrize("state", ["missing", "empty"])
def test_a_missing_or_empty_ledger_passes(tmp_path, monkeypatch, state):
    """#74: a repo where no commit touched the ledger, or one holding an empty
    tracked ledger, has nothing to violate."""
    locks = _check_locks()
    root = _repo(tmp_path, monkeypatch, seed_ledger=state == "empty")
    (root / "README.md").write_text("# a tmp repo\n\nNo evals yet.\n")
    _commit(root, "docs")

    assert locks.check(str(root)) == []


@pytest.mark.parametrize(
    "flaw",
    [
        "matching",
        "missing",
        "later",
        "not-a-registration",
        "scorer",
        "referee",
        "arms",
        "no-suite-hash",
        "suite-hash",
        "no-k",
        "k",
    ],
)
def test_a_result_names_an_earlier_registration_it_matches(tmp_path, monkeypatch, flaw):
    """#74 step 2: a result names a registered row earlier in the file with
    the same suite hash, scorer and referee hashes, arm names and k. A missing,
    later or non-registered link, a differing hash, arm set or k, and a result
    with no suite_hash or k each fail naming the result; the matching result
    passes."""
    locks = _check_locks()
    root = _repo(tmp_path, monkeypatch)
    unmeasured = _decision(None, "shipped-unmeasured", issue=50)
    reg = _registered()
    res = _result(reg["row_id"])
    order = [unmeasured, reg, res]
    if flaw == "missing":
        res["registered"] = "registered-20261016T090000-0a1b2c"  # never written
    elif flaw == "later":
        order = [unmeasured, res, reg]
    elif flaw == "not-a-registration":
        res["registered"] = unmeasured["row_id"]  # earlier, but a decision
    elif flaw in ("scorer", "referee"):
        moved = {**FP[flaw], "sha256": "6d" * 32}
        res["fingerprints"] = {**FP, flaw: moved}
    elif flaw == "arms":
        res["arms"]["b2"] = res["arms"].pop("a2")
    elif flaw == "no-suite-hash":
        del res["suite_hash"]
    elif flaw == "suite-hash":
        res["suite_hash"] = {**SUITE_HASH, "sha256": "d5" * 32}
    elif flaw == "no-k":
        del res["k"]
    elif flaw == "k":
        res["k"] = 5
    _land(root, *order, raw=True, message="eval: register and run")

    violations = locks.check(str(root))

    if flaw == "matching":
        assert violations == []
    else:
        assert any(res["row_id"] in v for v in violations), (
            f"no violation names the result with a {flaw} flaw: {violations}"
        )


@pytest.mark.parametrize(
    "type_, decision, moved, clean",
    [
        ("behaviour", "adopted", None, True),
        ("behaviour", "adopted", "src/crivo/prompts.py", False),
        (None, "adopted", "src/crivo/prompts.py", False),  # untyped is behaviour
        ("behaviour", "adopted", "src/crivo/diff.py", False),  # a referee file
        ("behaviour", "adopted", "bench/score.py", False),  # a scorer file
        ("experiment", "adopted", "src/crivo/prompts.py", True),
        ("code", "adopted", "src/crivo/prompts.py", True),
        ("eval", "adopted", "src/crivo/prompts.py", True),
        ("behavior", "adopted", "src/crivo/prompts.py", False),  # a misspelling
        ("behaviour", "dropped", "src/crivo/prompts.py", True),
    ],
    ids=[
        "matching",
        "prompt-moved",
        "untyped-prompt-moved",
        "referee-moved",
        "scorer-moved",
        "experiment-exempt",
        "code-exempt",
        "eval-exempt",
        "misspelled-behavior-checked",
        "dropped-unchecked",
    ],
)
def test_an_adopted_behaviour_row_matches_the_code_its_decision_landed_with(
    tmp_path, monkeypatch, type_, decision, moved, clean
):
    """#74 step 3: an adopted decision on a behaviour row (or an untyped one,
    or one whose type is no known work type) fails when the prompt, referee or
    scorer files in the commit that added the decision line hash differently
    from its result. An experiment, code or eval row, a dropped decision and a
    matching adoption pass."""
    locks = _check_locks()
    root = _repo(tmp_path, monkeypatch)
    fp = ledger.fingerprints(str(root))
    reg = _registered(fp=fp, type_=type_)
    res = _result(reg["row_id"], fp=fp)
    _land(root, reg, res, message="eval: register and run")
    if moved:
        with open(root / moved, "a") as fh:
            fh.write("# tuned after the eval\n")
    dec = _decision(res["row_id"], decision)
    _land(root, dec, message="the change and its decision")

    violations = locks.check(str(root))

    if clean:
        assert violations == []
    else:
        assert len(violations) == 1, violations
        assert dec["row_id"] in violations[0] or res["row_id"] in violations[0]


@pytest.mark.parametrize(
    "measured_on, clean",
    [("landing", True), ("head", False)],
    ids=["measured-on-the-landing-commit", "measured-on-head-only"],
)
def test_check_hashes_the_landing_commit_the_way_fingerprints_does(
    tmp_path, monkeypatch, measured_on, clean
):
    """#74: check_locks' hash of a row's files at the commit that landed its
    decision equals ledger.fingerprints() on that checkout, even after a later
    prompt change on dev and with the row's own commit gone (rebased away). A
    result measured on today's HEAD instead of the landing commit fails."""
    locks = _check_locks()
    root = _repo(tmp_path, monkeypatch)
    prompts = root / "src/crivo/prompts.py"
    shipped = 'SYSTEM = "You are crivo. Re-check every fix before you keep it."\n'
    later = 'SYSTEM = "You are crivo. Re-check every fix and every answer."\n'
    prompts.write_text(later)
    on_head = ledger.fingerprints(str(root))
    prompts.write_text(shipped)
    on_landing = ledger.fingerprints(str(root))
    measured = on_landing if measured_on == "landing" else on_head
    fp = {**measured, "commit": BRANCH_COMMIT, "dirty": False}
    reg = _registered(fp=fp)
    res = _result(reg["row_id"], fp=fp)
    dec = _decision(res["row_id"], "adopted")
    _land(root, reg, res, dec, message="the prompt change, its eval and adoption")
    prompts.write_text(later)
    _commit(root, "a later prompt change on dev")

    violations = locks.check(str(root))

    assert on_head["prompt"] != on_landing["prompt"]
    if clean:
        assert violations == []
    else:
        assert len(violations) == 1, violations


def test_a_shallow_clone_fails_and_a_full_clone_passes(tmp_path, monkeypatch):
    """#74: a clone without history can't pass vacuously, so a shallow clone
    is a violation that says so; a full clone of the same repo passes."""
    locks = _check_locks()
    src = _repo(tmp_path / "src", monkeypatch)
    _land(src, _registered(), message="register #48")
    _land(src, _decision(None, "shipped-unmeasured", issue=50))
    shallow, full = tmp_path / "shallow", tmp_path / "full"
    _git(tmp_path, "clone", "-q", "--depth", "1", src.as_uri(), str(shallow))
    _git(tmp_path, "clone", "-q", src.as_uri(), str(full))
    assert _git(shallow, "rev-parse", "--is-shallow-repository") == "true"

    found = locks.check(str(shallow))

    assert any("shallow" in v.lower() for v in found), found
    assert locks.check(str(full)) == []


@pytest.mark.parametrize("split", ["dev", "sealed"])
def test_a_sealed_registration_fails_until_sealed_sets_exist(
    tmp_path, monkeypatch, split
):
    """#74 step 4: no sealed set exists until ED7 names where one lives, so a
    registration on the sealed split fails, naming it; a dev one passes."""
    locks = _check_locks()
    root = _repo(tmp_path, monkeypatch)
    reg = _registered(split=split)
    _land(root, reg, message=f"register #48 on {split}")

    violations = locks.check(str(root))

    if split == "dev":
        assert violations == []
    else:
        assert len(violations) == 1, violations
        assert reg["row_id"] in violations[0]


@pytest.mark.parametrize("state", ["no-ledger", "rows"])
def test_main_prints_one_summary_line_and_exits_0_when_clean(
    tmp_path, monkeypatch, capsys, state
):
    """#74 step 5: a clean repo prints one summary line, which says there is
    no sealed set (step 4), and exits 0."""
    locks = _check_locks()
    root = _repo(tmp_path, monkeypatch, seed_ledger=state == "rows")
    if state == "rows":
        fp = ledger.fingerprints(str(root))
        reg = _registered(fp=fp)
        res = _result(reg["row_id"], fp=fp)
        unmeasured = _decision(None, "shipped-unmeasured", issue=50)
        _land(root, reg, res, _decision(res["row_id"]), unmeasured)

    code = locks.main(["--root", str(root)])
    lines = _said(capsys)

    assert code == 0
    assert len(lines) == 1, lines
    assert "no sealed set" in lines[0]


def test_main_prints_one_line_per_violation_and_exits_1(tmp_path, monkeypatch, capsys):
    """#74 step 5: an edited line and a sealed registration are two
    violations: two lines, the edit naming its commit, and exit 1."""
    locks = _check_locks()
    root = _repo(tmp_path, monkeypatch)
    path = root / ledger.LEDGER
    _land(root, _decision(None, "shipped-unmeasured", issue=50))
    row = json.loads(path.read_text())
    row["note"] = "shipped with Aarmen's yes, and measured after all"
    path.write_text(json.dumps(row, sort_keys=True) + "\n")
    edited = _commit(root, "reword an old decision")
    sealed = _registered(split="sealed")
    _land(root, sealed, message="register #48 on sealed")

    code = locks.main(["--root", str(root)])
    lines = _said(capsys)

    assert code == 1
    assert len(lines) == 2, lines
    assert any(edited[:7] in ln for ln in lines), lines
    assert any(sealed["row_id"] in ln for ln in lines), lines


@pytest.mark.parametrize("state", ["clean", "sealed"])
def test_the_script_runs_from_its_own_path_in_another_repo(
    tmp_path, monkeypatch, state
):
    """#74: `python scripts/check_locks.py` imports bench.ledger from its own
    repo root and checks the repo it runs in (--root defaults to the cwd), so
    CI's step works as written."""
    assert SCRIPT.exists(), "scripts/check_locks.py does not exist yet (#74)"
    root = _repo(tmp_path, monkeypatch)
    reg = _registered(split="dev" if state == "clean" else "sealed")
    _land(root, reg)

    run = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    lines = [ln for ln in (run.stdout + run.stderr).splitlines() if ln.strip()]

    assert "Traceback" not in run.stderr, run.stderr
    if state == "clean":
        assert (run.returncode, len(lines)) == (0, 1), lines
        assert "no sealed set" in lines[0]
    else:
        assert run.returncode == 1, lines
        assert any(reg["row_id"] in ln for ln in lines), lines


def test_check_locks_passes_on_this_repo(monkeypatch, capsys):
    """#74: the check exits 0 on this checkout's own history (CI runs it with
    fetch-depth: 0)."""
    locks = _check_locks()
    _clean_git_env(monkeypatch)

    assert locks.main(["--root", str(ROOT)]) == 0, _said(capsys)
