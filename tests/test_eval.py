"""bench.eval units (spec: specs/2026-10-17-eval-tooling.md EV8, #71; the caps,
EV9, #72).

`register` writes a registered row, `run` runs the suite's cases k times per
arm through the agent lane and writes the result row, and `decide` writes the
decision row, all through bench.ledger.

Keyless and offline. Every test runs from inside a committed tmp git repo that
holds copies of the files the fingerprints and the suite hash read, so the
ledger it writes is the tmp repo's, never bench/ledger.jsonl. The key file is
found through the runner's `_key_file()` seam, which every test points at a
tmp file holding fake keys at most. Every env var the runner or a key file can
set is pre-armed (setenv, then delenv), so the monkeypatch undo removes it
whatever the code under test leaves behind; agent_run.RESULTS_DIR likewise.
`agent_run._run_case` is replaced through the module with canned rows shaped
as it returns them, except in the one end-to-end test, which boots a real
kernel under the faux provider.

The interface these tests pin where the issue leaves it open:
- `SUITES[name]["splits"][split]` is the list of corpus entries a run uses,
  and `SUITES[name]["limits"]` the known-limits text every row carries.
- A refusal is a non-zero exit (or return) of `main(argv)`; it says why.
- A null metric carries `<key>_reason` beside it, as ledger.py's
  `false_backed_reason` does: `model_cases`, `cost_usd`, `noise_floor`.
- `noise_floor` is {"arms", "pass_at_1_diff", "flaky"}.

EV9 (#72), where the issue leaves it open:
- A registered arm carries its price entry, copied from bench.prices, as
  `arm["price"]`.
- `run` hands each case the registration's cap as `args.per_case_usd`, and
  `agent_run._run_case` returns what the case cost as `row["cost_usd"]`
  (None when it can't be read). The canned rows below carry it: 0.0 under
  faux's zero price, None when the telemetry was unread.
- A result whose budget stopped the run lists every case it never started in
  `cases_not_run`, each {"arm", "case", "run"}.
- `register --dry` prints the worst case and appends nothing.
- When a case raises, the rows already run and the spend so far are kept as
  JSON (.json or .jsonl) under bench/results/eval/<row id>/.
- The review's decisions on #72: a run stops at the first case whose spend is
  unread (budget_hit, every later case not run); run re-checks the
  registered caps; decide --adopted hashes the files committed at HEAD and
  refuses when the working tree drifts from them; an A/A pair whose arms ran
  unequal numbers of runs gets no noise floor.

#73, the scout's calls taken on the issue:
- Each run's Session output (its data profile among it) goes to
  bench/results/eval/<row id>/<arm>/logs/<case>.r<run>.log, never to the
  terminal; stdout keeps the per-case lines, the per-arm screens and the
  summary. The closing lines, and the refusal when a case raises, name a logs
  dir by a path that holds the row id.
"""

import copy
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench import agent_run, consistency, corpus, ledger
from crivo import llm

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SUITE = "agent-clean-smoke"
CASES = ("tx-whitespace", "tx-dates-mixed", "tx-near-dups")
ONE = ("tx-whitespace",)
HYPOTHESIS = "two arms on one config differ by no more than the noise floor"
RULE = "record the A/A spread as the noise floor; adopt nothing"
NOTE = "Aarmen said yes on #71, 2026-10-18"
# Every env var the runner sets per arm, or a key file can fill in.
ARMED = (
    "CRIVO_PROVIDER",
    "CRIVO_MODEL",
    "CRIVO_BASE_URL",
    "CRIVO_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "CRIVO_TELEMETRY",
)
OPUS = "claude-opus-5-5"
# A made-up price, in USD per million tokens; not any provider's.
TEST_PRICE = {
    "input": 5.0,
    "cache_hit": 0.5,
    "output": 25.0,
    "source": "a test price, not read from any provider's page",
    "checked": "2026-10-18",
}
# Exception text quoting a value from the data (an account id with a leading
# zero). The ledger is committed, so this must never reach it.
LEAKED_VALUE = "00417-ACME"


# --- helpers -----------------------------------------------------------------


def _eval():
    """bench.eval, imported per test, so a missing module fails each test on
    this assert instead of erroring the whole file at collection."""
    assert importlib.util.find_spec("bench.eval") is not None, (
        "bench/eval.py does not exist yet (#71)"
    )
    return importlib.import_module("bench.eval")


def _prices():
    """bench.prices, imported per test, so a missing module fails each test on
    this assert instead of erroring the whole file at collection."""
    assert importlib.util.find_spec("bench.prices") is not None, (
        "bench/prices.py does not exist yet (#72)"
    )
    return importlib.import_module("bench.prices")


def _price(monkeypatch, provider, model, entry=None):
    """A test price for the model, monkeypatched into bench.prices.PRICES."""
    prices = _prices()
    entry = dict(TEST_PRICE if entry is None else entry)
    monkeypatch.setitem(prices.PRICES, prices.price_key(provider, model), entry)
    return entry


def _check_locks():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
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


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--no-verify", "--allow-empty", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _repo(tmp_path, monkeypatch):
    """A committed tmp repo holding a copy of every bench/*.py and
    src/crivo/*.py (the prompt, referee, scorer and suite generator files are
    among them), an empty tracked ledger, and bench/results/ ignored, as the
    real repo ignores it. The test then runs from inside it."""
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "repo"
    sources = [*(ROOT / "bench").glob("*.py"), *(ROOT / "src" / "crivo").glob("*.py")]
    for src in sources:
        if src.name == "__init__.py":
            continue
        target = root / src.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    (root / ".gitignore").write_text("bench/results/\n")
    (root / ledger.LEDGER).write_text("")
    _git(root, "init", "-q")
    for key, value in (("user.name", "t"), ("user.email", "t@x")):
        _git(root, "config", key, value)
    _git(root, "config", "commit.gpgsign", "false")
    _commit(root, "seed")
    monkeypatch.chdir(root)
    return root


def _arm_env(monkeypatch):
    """Pre-arm every var the runner may set, so the undo removes it again even
    when the code under test sets it and never restores it."""
    for var in ARMED:
        monkeypatch.setenv(var, "pre-armed")
        monkeypatch.delenv(var)
    monkeypatch.setattr(agent_run, "RESULTS_DIR", agent_run.RESULTS_DIR)


def _keys(tmp_path, monkeypatch, ev, text=""):
    """A tmp key file standing in for the main checkout's, found through the
    runner's `_key_file()` seam."""
    path = tmp_path / "keys"
    path.write_text(text)
    monkeypatch.setattr(ev, "_key_file", lambda: path)
    return path


def _suite(ev, monkeypatch, *names):
    """agent-clean-smoke cut to the named SMOKE cases on its dev split, its
    limits kept."""
    entries = [next(e for e in corpus.SMOKE if e["name"] == n) for n in names]
    real = ev.SUITES[SUITE]
    monkeypatch.setattr(ev, "SUITES", {SUITE: {**real, "splits": {"dev": entries}}})
    return entries


def _setup(tmp_path, monkeypatch, keys="", cases=None):
    """bench.eval, a tmp repo to run in, the env pre-armed, the key file
    pointed at a tmp one, and (for a run) the suite cut to `cases`."""
    ev = _eval()
    root = _repo(tmp_path, monkeypatch)
    _arm_env(monkeypatch)
    _keys(tmp_path, monkeypatch, ev, keys)
    if cases is not None:
        _suite(ev, monkeypatch, *cases)
    return ev, root


def _call(ev, argv, capsys):
    """Run the CLI: (exit code, everything it said). sys.exit("why") is a
    refusal whose text counts as said."""
    try:
        code = ev.main(argv)
    except SystemExit as exc:
        code = exc.code
    said = capsys.readouterr()
    return code, "\n".join([code if isinstance(code, str) else "", said.out, said.err])


def _ok(code) -> bool:
    return code in (0, None)


def _register_argv(
    *arms,
    issue=71,
    k=3,
    type_="code",
    split="dev",
    budget=1.0,
    per_case=0.25,
    extra=(),
):
    argv = ["register", "--issue", str(issue)]
    if type_ is not None:
        argv += ["--type", type_]
    argv += ["--suite", SUITE, "--split", split]
    for arm in arms:
        argv += ["--arm", arm]
    argv += ["--k", str(k), "--budget-usd", str(budget)]
    argv += ["--per-case-usd", str(per_case)]
    argv += ["--hypothesis", HYPOTHESIS, "--primary", "pass_at_1"]
    argv += ["--guards", "aborted", "--rule", RULE]
    return argv + list(extra)


def _register(ev, capsys, *arms, **kw):
    code, text = _call(ev, _register_argv(*arms, **kw), capsys)
    assert _ok(code), f"register was refused: {text}"
    return ledger.rows(kind="registered")[-1]


def _arm(name, provider, model, price=None):
    """A registered arm as register writes it: the baseline agent-lane arm,
    with the sampling control llm.model_info() reports for its provider, and
    (EV9) the price entry register copied onto it. `price` None leaves it off:
    a registration register never wrote."""
    control = (
        {"effort": llm.CLAUDE_EFFORT}
        if provider == "claude"
        else {"temperature": llm.TEMPERATURE}
    )
    arm = {
        "name": name,
        "provider": provider,
        "model": model,
        **control,
        "docker": False,
        "autonomy": "careful",
        "human_gates": "skip",
        "policies": "none",
        "max_events": agent_run.DEFAULT_MAX_EVENTS,
        "wall_cap": agent_run.DEFAULT_WALL_CAP,
    }
    if price is not None:
        arm["price"] = dict(price)
    return arm


def _row(name, status, f1, count, wall, served=(), cost=0.0):
    """A row shaped as agent_run._run_case returns it. `count` None is
    unreadable telemetry: calls, tokens and served models are all unknown.
    `cost` is what the case cost (EV9): 0.0 by default, since faux's zero
    price bills nothing even when its telemetry is unread (agent_run's
    _case_cost); None is a priced case's spend that couldn't be read, so its
    tokens are unknown too."""
    if count is None:
        calls = {
            "count": None,
            "model_wait_s": None,
            "new_work_tokens": None,
            "served_models": None,
        }
    else:
        calls = {
            "count": count,
            "model_wait_s": round(count * 1.7, 2),
            "input_tokens": count * 1400,
            "output_tokens": count * 100,
            "new_work_tokens": count * 1500,
            "served_models": sorted(served),
        }
    if cost is None and count is not None:
        calls["new_work_tokens"] = None  # a span reported no usage
    row = {
        "name": name,
        "diseases": next(e["diseases"] for e in corpus.SMOKE if e["name"] == name),
        "date": "2026-10-18T09:14:03+00:00",
        "handoff": "parquet",
        "human_gates": "skip",
        "policies": "none",
        "autonomy": "careful",
        "model": {"provider": "faux", "model": "m", "temperature": 0.0},
        "status": status,
        "calls": calls,
        "gates": {"run": 1, "skip": 0},
        "wall_secs": wall,
        "cost_usd": cost,
    }
    if status in ("ok", "ok_unchanged"):
        row["events"] = 40
        row["scores"] = {"repair": {"precision": f1, "recall": f1, "f1": f1}}
    return row


def _fake_run_case(monkeypatch, table):
    """agent_run._run_case, replaced through the module. `table(model, case,
    i)` gives the i-th canned row for that case under that CRIVO_MODEL
    (0-based; arms run one after another, step 3). Every call is logged with
    the env and RESULTS_DIR it saw and a copy of its args."""
    log, seen = [], {}

    def fake(entry, args):
        model = os.environ.get("CRIVO_MODEL")
        i = seen.get((model, entry["name"]), 0)
        seen[(model, entry["name"])] = i + 1
        log.append(
            {
                "case": entry["name"],
                "provider": os.environ.get("CRIVO_PROVIDER"),
                "model": model,
                "results_dir": Path(agent_run.RESULTS_DIR),
                "args": copy.copy(args),
            }
        )
        return copy.deepcopy(table(model, entry["name"], i))

    monkeypatch.setattr(agent_run, "_run_case", fake)
    return log


def _solved_row(model, name, i):
    return _row(name, "ok", 1.0, 0, 5.0)


def _results_of(reg):
    return [r for r in ledger.rows(kind="result") if r["registered"] == reg["row_id"]]


def _run(ev, capsys, reg):
    code, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    assert _ok(code), f"run was refused: {text}"
    (result,) = _results_of(reg)
    return result, text


def _eval_dir(root, reg) -> Path:
    return (root / "bench" / "results" / "eval" / reg["row_id"]).resolve()


def _within(path, top) -> bool:
    path = (Path.cwd() / path).resolve()
    return path == top or top in path.parents


# Two arms on different models, three cases, k=3. Hand-checked:
# a1, all cases: per-case pass@1 1, 2/3, 0 -> mean pass@1 5/9, pass^k 1/3,
#   flaky [tx-dates-mixed]. Model cases are tx-dates-mixed (calls) and
#   tx-near-dups (one run's count is unknown, which counts, B4): pass@1 1/3,
#   pass^k 0, flaky [tx-dates-mixed]. One run aborted. Wall times sorted
#   4.0 5.5 6.0 12.5 20.0 28.0 33.5 41.0 300.2: p50 20.0, p95 (inclusive)
#   41.0 + 0.6 * (300.2 - 41.0) = 196.52.
# a2: every case solved with no model call: no model cases.
SPLIT_TABLE = {
    "m1": {
        "tx-whitespace": [
            ("ok", 1.0, 0, 4.0, ()),
            ("ok", 1.0, 0, 5.5, ()),
            ("ok", 1.0, 0, 6.0, ()),
        ],
        "tx-dates-mixed": [
            ("ok", 1.0, 4, 20.0, ("m1",)),
            ("no_cleaned_output", None, 2, 28.0, ("m1",)),
            ("ok", 1.0, 3, 33.5, ("m1-0925",)),
        ],
        "tx-near-dups": [
            ("ok", 0.5, 0, 41.0, ()),
            (
                f"error: ValueError: could not convert string to float: '{LEAKED_VALUE}'",
                None,
                None,
                12.5,
                (),
            ),
            ("aborted: wall cap 300s hit", None, 0, 300.2, ()),
        ],
    },
    "m2": {
        name: [("ok", 1.0, 0, w, ()) for w in walls]
        for name, walls in (
            ("tx-whitespace", (3.0, 3.5, 4.0)),
            ("tx-dates-mixed", (9.0, 9.5, 10.0)),
            ("tx-near-dups", (7.0, 7.5, 8.0)),
        )
    },
}
SPLIT_ARMS = ("a1=faux:m1", "a2=faux:m2")


def _split_row(model, name, i):
    return _row(name, *SPLIT_TABLE[model][name][i])


def _canned_rows(model):
    """The rows the fake hands one arm, in the order it hands them."""
    return [
        _row(name, *spec)
        for name, specs in SPLIT_TABLE[model].items()
        for spec in specs
    ]


def _run_split(tmp_path, monkeypatch, capsys, type_="code"):
    """Register SPLIT_ARMS and run them on SPLIT_TABLE's canned rows."""
    ev, root = _setup(tmp_path, monkeypatch, cases=CASES)
    log = _fake_run_case(monkeypatch, _split_row)
    reg = _register(ev, capsys, *SPLIT_ARMS, type_=type_)
    result, text = _run(ev, capsys, reg)
    return SimpleNamespace(ev=ev, root=root, reg=reg, result=result, log=log, text=text)


# Two arms on one config (A/A). Arms run one after another, so for each case
# calls 0-2 are a1's runs and 3-5 a2's. S solves, U does not.
# Model cases (both arms): tx-dates-mixed and tx-near-dups.
# a1 model-case pass@1: (2/3 + 1) / 2 = 5/6; a2: (1 + 1/3) / 2 = 2/3, so the
# noise floor's pass@1 difference is 1/6 (over all cases it would be 1/9).
# Flaky: a1 [tx-dates-mixed], a2 [tx-near-dups]; the union is both.
_DS = ("ok", 1.0, 3, 25.0, ("m",))
_DU = ("no_cleaned_output", None, 5, 61.0, ("m",))
_NS = ("ok", 1.0, 2, 18.0, ("m-2026-10",))
_NU = ("ok", 0.5, 4, 22.0, ("m-2026-10",))
AA_TABLE = {
    "tx-whitespace": [("ok", 1.0, 0, 4.0 + i / 2, ()) for i in range(6)],
    "tx-dates-mixed": [_DS, _DS, _DU, _DS, _DS, _DS],
    "tx-near-dups": [_NS, _NS, _NS, _NU, _NS, _NU],
}


def _aa_row(model, name, i):
    return _row(name, *AA_TABLE[name][i])


def _ledger_registered(
    issue, type_="code", arms=None, suite=SUITE, suite_hash=None, **fields
):
    """A registration appended straight through ledger.append, never through
    register, so nothing refused it. `type_` None writes an untyped one."""
    typed = {} if type_ is None else {"type": type_}
    row = ledger.new_row(
        "registered",
        issue,
        **typed,
        suite=suite,
        split="dev",
        arms=arms or [_arm("a1", "faux", "m")],
        k=3,
        hypothesis=HYPOTHESIS,
        primary="pass_at_1",
        guards=["aborted"],
        rule=RULE,
        **{"budget_usd": 0.0, "per_case_usd": 0.0, **fields},
        fingerprints=ledger.fingerprints(),
        suite_hash=suite_hash or {"sha256": "c4" * 32, "files": ["bench/corpus.py"]},
    )
    ledger.append(row)
    return row


def _ledger_result(reg, cost=None):
    """A result naming `reg`, appended straight through ledger.append. `cost`
    set: its one arm ran every case 3 times at `cost` dollars a run (EV9)."""
    reason = "no verdicts exist before 0b; agent-clean-smoke, ED1"
    row = ledger.new_row(
        "result",
        reg["issue"],
        registered=reg["row_id"],
        fingerprints=reg["fingerprints"],
        suite_hash=reg["suite_hash"],
        k=3,
        served_models={"a1": []},
        cases=[
            {
                "case": name,
                "arm": "a1",
                "run": run,
                "status": "ok",
                "solved": True,
                "repair_f1": 1.0,
                "calls": 4,
                "new_work_tokens": 61_200,
                "cost_usd": cost,
                "wall_s": 41.0,
            }
            for name in (CASES if cost is not None else ())
            for run in (1, 2, 3)
        ],
        arms={
            "a1": {
                "pass_k": 1.0,
                "pass_at_1": 1.0,
                "flaky": [],
                "false_backed": None,
                "false_backed_reason": reason,
                "backed_rate": None,
                "backed_rate_reason": reason,
                "cost_usd": None if cost is None else {"p50": cost, "p95": cost},
                "wall_s": {"p50": 5.0, "p95": 5.0},
                "aborted": 0,
                "contained": "host",
            }
        },
        spent_usd=0.0 if cost is None else round(9 * cost, 4),
        budget_hit=False,
    )
    ledger.append(row)
    return row


# --- the suite ---------------------------------------------------------------


def test_agent_clean_smoke_is_smoke_on_the_dev_split_with_its_known_limits():
    """ED1: one provisional suite, the agent lane over SMOKE, dev split only,
    carrying the five known limits the issue lists."""
    ev = _eval()
    suite = ev.SUITES[SUITE]
    assert suite["splits"] == {"dev": list(corpus.SMOKE)}
    limits = suite["limits"]
    assert len(limits) == 5 and all(isinstance(t, str) and t for t in limits)
    text = " ".join(limits)
    for marker in ("0b", "DD2", "T13", "0a", "held out"):
        assert marker in text, f"the known limits never mention {marker!r}"


# --- register ----------------------------------------------------------------


def test_register_appends_one_registered_row(tmp_path, monkeypatch, capsys):
    """Done when 1: register in a tmp git repo appends exactly one row, with
    the arm resolved under its own env and the code it was registered on. The
    faux arm carries faux's own (zero) price entry (EV9)."""
    ev, _ = _setup(tmp_path, monkeypatch)
    code, text = _call(ev, _register_argv("a1=faux:m"), capsys)
    assert _ok(code), f"register was refused: {text}"

    rows = ledger.read()
    assert len(rows) == 1
    (row,) = rows
    assert row["kind"] == "registered"
    assert row["issue"] == 71
    assert row["type"] == "code"
    assert row["suite"] == SUITE
    assert row["split"] == "dev"
    assert row["arms"] == [_arm("a1", "faux", "m", price=_prices().PRICES["faux"])]
    assert row["k"] == 3
    assert row["hypothesis"] == HYPOTHESIS
    assert row["primary"] == "pass_at_1"
    assert row["guards"] == ["aborted"]
    assert row["rule"] == RULE
    assert row["budget_usd"] == 1.0
    assert row["per_case_usd"] == 0.25
    assert row["fingerprints"] == ledger.fingerprints()
    files = row["suite_hash"]["files"]
    assert "bench/corpus.py" in files
    assert row["suite_hash"] == ledger.suite_hash(list(corpus.SMOKE), files)
    assert row["limits"] == ev.SUITES[SUITE]["limits"]
    assert row["owner_ok"] is False
    # the arm's env was set to resolve it, and put back
    assert "CRIVO_PROVIDER" not in os.environ
    assert "CRIVO_MODEL" not in os.environ


@pytest.mark.parametrize(
    "type_, accepted",
    [
        ("code", True),
        ("behaviour", True),
        ("eval", True),
        ("experiment", True),
        (None, False),
        ("feature", False),
    ],
)
def test_register_needs_the_issues_work_type(
    tmp_path, monkeypatch, capsys, type_, accepted
):
    """B3: --type is required and is one of the four work types; check_locks
    reads it off the registered row."""
    ev, _ = _setup(tmp_path, monkeypatch)
    code, text = _call(ev, _register_argv("a1=faux:m", type_=type_), capsys)
    rows = ledger.read()
    if accepted:
        assert _ok(code), f"register was refused: {text}"
        assert [r["type"] for r in rows] == [type_]
    else:
        assert not _ok(code), "register accepted an issue with no work type"
        assert rows == []


def test_register_refuses_a_dirty_tree(tmp_path, monkeypatch, capsys):
    """Done when 1: a tracked change outside the ledger is refused; the same
    tree put back registers."""
    ev, root = _setup(tmp_path, monkeypatch)
    loop = root / "src" / "crivo" / "loop.py"
    original = loop.read_bytes()
    loop.write_bytes(original + b"\n# an uncommitted edit\n")

    code, text = _call(ev, _register_argv("a1=faux:m"), capsys)
    assert not _ok(code), "register accepted a dirty tree"
    assert "dirty" in text.lower()
    assert ledger.read() == []

    loop.write_bytes(original)
    code, text = _call(ev, _register_argv("a1=faux:m"), capsys)
    assert _ok(code), f"register was refused on a clean tree: {text}"
    assert len(ledger.read()) == 1


@pytest.mark.parametrize("split", ["heldout", "sealed"])
def test_register_refuses_a_split_until_stage_0a(tmp_path, monkeypatch, capsys, split):
    """Done when 1: agent-clean-smoke has a dev split only."""
    ev, _ = _setup(tmp_path, monkeypatch)
    code, text = _call(ev, _register_argv("a1=faux:m", split=split), capsys)
    assert not _ok(code), f"register accepted the {split} split"
    assert "no such split until Stage 0a" in text
    assert ledger.read() == []


@pytest.mark.parametrize("k, accepted", [(1, False), (2, False), (3, True)])
def test_register_needs_three_runs_or_more(tmp_path, monkeypatch, capsys, k, accepted):
    ev, _ = _setup(tmp_path, monkeypatch)
    code, text = _call(ev, _register_argv("a1=faux:m", k=k), capsys)
    if accepted:
        assert _ok(code), f"register was refused: {text}"
        assert [r["k"] for r in ledger.read()] == [k]
    else:
        assert not _ok(code), f"register accepted k={k}"
        assert ledger.read() == []


@pytest.mark.parametrize(
    "provider, model, key",
    [
        ("claude", "claude-opus-5-5", "ANTHROPIC_API_KEY"),
        ("deepseek", "deepseek-v4-pro", "DEEPSEEK_API_KEY"),
    ],
)
def test_register_refuses_an_arm_whose_key_is_missing(
    tmp_path, monkeypatch, capsys, provider, model, key
):
    """Step 2: an arm whose provider fails query.provider_problem once the key
    file is loaded is refused, naming the key; with the key in the key file
    the arm registers. The key itself is never printed. The model is priced
    (EV9), so the key is the only reason."""
    secret = f"sk-test-{provider}-9f3a71c2"
    ev, _ = _setup(tmp_path, monkeypatch)
    price = _price(monkeypatch, provider, model)
    arm = f"a1={provider}:{model}"

    code, refused = _call(ev, _register_argv(arm), capsys)
    assert not _ok(code), f"register accepted a {provider} arm with no key"
    assert key in refused
    assert ledger.read() == []

    _keys(tmp_path, monkeypatch, ev, f"{key}={secret}\n")
    code, text = _call(ev, _register_argv(arm), capsys)
    assert _ok(code), f"register was refused with the key loaded: {text}"
    registered = ledger.rows(kind="registered")[-1]["arms"]
    assert registered == [_arm("a1", provider, model, price=price)]
    assert secret not in refused + text, "the key was printed"


def test_register_refuses_a_real_arm_while_the_shell_says_faux(
    tmp_path, monkeypatch, capsys
):
    """With CRIVO_PROVIDER=faux set when register starts, every non-faux arm
    is refused; a faux arm still registers, and the shell's value is kept."""
    ev, _ = _setup(tmp_path, monkeypatch, keys="ANTHROPIC_API_KEY=sk-ant-test\n")
    monkeypatch.setenv("CRIVO_PROVIDER", "faux")

    code, text = _call(ev, _register_argv("a1=claude:claude-opus-5-5"), capsys)
    assert not _ok(code), "register accepted a claude arm under CRIVO_PROVIDER=faux"
    assert "faux" in text
    assert ledger.read() == []

    code, text = _call(ev, _register_argv("a1=faux:m"), capsys)
    assert _ok(code), f"register was refused a faux arm: {text}"
    assert len(ledger.read()) == 1
    assert os.environ["CRIVO_PROVIDER"] == "faux"


def test_an_arm_splits_on_its_first_colon(tmp_path, monkeypatch, capsys):
    """`--arm a1=openai:qwen3:32b` is provider openai, model qwen3:32b: a
    model id can hold a colon, a provider can't."""
    keys = "CRIVO_BASE_URL=http://localhost:11434/v1\n"
    ev, _ = _setup(tmp_path, monkeypatch, keys=keys)
    price = _price(monkeypatch, "openai", "qwen3:32b")
    reg = _register(ev, capsys, "a1=openai:qwen3:32b")
    assert reg["arms"] == [_arm("a1", "openai", "qwen3:32b", price=price)]


@pytest.mark.parametrize(
    "provider, model, keys",
    [
        ("claude", OPUS, "ANTHROPIC_API_KEY=sk-ant-test\n"),
        ("deepseek", "deepseek-v4-pro", "DEEPSEEK_API_KEY=sk-test\n"),
        ("openai", "qwen3:32b", "CRIVO_BASE_URL=http://localhost:11434/v1\n"),
    ],
    ids=["claude", "deepseek", "openai"],
)
def test_register_refuses_an_arm_whose_model_has_no_price(
    tmp_path, monkeypatch, capsys, provider, model, keys
):
    """Done when 2 (EV9): an arm whose model has no entry in bench.prices is
    refused, with its key on hand so the price is the only reason. Once the
    model has an entry the arm registers, the entry copied onto it."""
    ev, _ = _setup(tmp_path, monkeypatch, keys=keys)
    prices = _prices()
    monkeypatch.delitem(prices.PRICES, prices.price_key(provider, model), raising=False)
    arm = f"a1={provider}:{model}"

    code, text = _call(ev, _register_argv(arm), capsys)
    assert not _ok(code), f"register accepted a {provider} arm with no price"
    assert "price" in text.lower()
    assert ledger.read() == []

    price = _price(monkeypatch, provider, model)
    reg = _register(ev, capsys, arm)
    assert reg["arms"] == [_arm("a1", provider, model, price=price)]


@pytest.mark.parametrize(
    "change",
    [
        {"source": None},
        {"source": "  "},
        {"checked": None},
        {"checked": ""},
    ],
    ids=["no source", "a blank source", "no date", "a blank date"],
)
def test_register_refuses_a_price_that_names_no_source_or_date(
    tmp_path, monkeypatch, capsys, change
):
    """A number that was not measured is not claimed: a price entry that
    doesn't say which page it was read from, or on which day, is refused. The
    same entry with both registers."""
    ev, _ = _setup(tmp_path, monkeypatch, keys="ANTHROPIC_API_KEY=sk-ant-test\n")
    entry = {k: v for k, v in {**TEST_PRICE, **change}.items() if v is not None}
    _price(monkeypatch, "claude", OPUS, entry)
    arm = f"a1=claude:{OPUS}"

    code, _ = _call(ev, _register_argv(arm), capsys)
    assert not _ok(code), f"register accepted a price with {change}"
    assert ledger.read() == []

    price = _price(monkeypatch, "claude", OPUS)
    reg = _register(ev, capsys, arm)
    assert reg["arms"][0]["price"] == price


@pytest.mark.parametrize(
    "bad, good",
    [
        (("-0.01", "0"), ("0", "0")),
        (("nan", "0.25"), ("1.0", "0.25")),
        (("inf", "0.25"), ("1.0", "0.25")),
        (("1.0", "-0.01"), ("1.0", "0")),
        (("1.0", "nan"), ("1.0", "0.25")),
        (("1.0", "inf"), ("1.0", "1.0")),
        (("0.5", "0.75"), ("0.5", "0.5")),
    ],
    ids=[
        "a negative budget",
        "a NaN budget",
        "an infinite budget",
        "a negative cap",
        "a NaN cap",
        "an infinite cap",
        "a cap above the budget",
    ],
)
def test_register_refuses_a_budget_or_cap_that_is_not_a_finite_amount(
    tmp_path, monkeypatch, capsys, bad, good
):
    """No cost is greater than NaN or infinity, so a NaN or infinite cap never
    trips; a negative one is not an amount; a per-case cap above the budget
    can't hold. Each is refused, and the nearby amount registers: $0 for
    both on faux, and a cap equal to the budget."""
    ev, _ = _setup(tmp_path, monkeypatch)
    budget, per_case = bad
    argv = _register_argv("a1=faux:m", budget=budget, per_case=per_case)
    try:
        code, _ = _call(ev, argv, capsys)
    except ValueError as exc:
        pytest.fail(f"register raised {type(exc).__name__} rather than refusing")
    assert not _ok(code), (
        f"register accepted --budget-usd {budget} --per-case-usd {per_case}"
    )
    assert ledger.read() == []

    budget, per_case = good
    reg = _register(ev, capsys, "a1=faux:m", budget=budget, per_case=per_case)
    assert (reg["budget_usd"], reg["per_case_usd"]) == (float(budget), float(per_case))


def test_register_dry_prints_the_worst_case_and_appends_nothing(
    tmp_path, monkeypatch, capsys
):
    """Done when 5, scout call 3 (ED5): `register --dry` prints the worst case,
    cases x k x arms x the per-case cap, says a case can overshoot its cap by
    one call, and quotes the cost per case an earlier priced result measured
    on the same suite and model. It appends nothing.

    3 cases x k=3 x 2 arms x $0.40 = $7.20. The ledger holds an earlier result
    on the suite and model at $0.25 a case, one on another model at $0.75 and
    one on another suite at $0.61; only $0.25 is quoted."""
    keys = "ANTHROPIC_API_KEY=sk-ant-test\nDEEPSEEK_API_KEY=sk-test\n"
    ev, _ = _setup(tmp_path, monkeypatch, keys=keys, cases=CASES)
    for provider, model, suite, cost in (
        ("claude", OPUS, SUITE, 0.25),
        ("deepseek", "deepseek-v4-pro", SUITE, 0.75),
        ("claude", OPUS, "agent-other-suite", 0.61),
    ):
        price = _price(monkeypatch, provider, model)
        arm = _arm("a1", provider, model, price=price)
        reg = _ledger_registered(48, type_="experiment", arms=[arm], suite=suite)
        _ledger_result(reg, cost=cost)
    before = ledger.read()

    arms = (f"a1=claude:{OPUS}", f"a2=claude:{OPUS}")
    argv = _register_argv(*arms, budget=9.0, per_case=0.4, extra=["--dry"])
    code, text = _call(ev, argv, capsys)
    assert _ok(code), f"register --dry was refused: {text}"
    assert ledger.read() == before, "a dry run appended a row"
    assert "7.2" in text, "the worst case, 3 x 3 x 2 x $0.40, is not printed"
    assert "one call" in text.lower(), "the one-call overshoot is not stated"
    assert "0.25" in text, "the cost measured earlier on this suite and model"
    assert "0.75" not in text, "a cost measured on another model was quoted"
    assert "0.61" not in text, "a cost measured on another suite was quoted"


@pytest.mark.parametrize(
    "arms, accepted",
    [
        (("a1=faux:m", "a1=faux:n"), False),
        (("a1=faux:m", "a2=faux:m"), True),
    ],
    ids=["a name twice", "two names, one config"],
)
def test_arm_names_are_unique(tmp_path, monkeypatch, capsys, arms, accepted):
    ev, _ = _setup(tmp_path, monkeypatch)
    code, text = _call(ev, _register_argv(*arms), capsys)
    if accepted:
        assert _ok(code), f"register was refused: {text}"
        assert [a["name"] for a in ledger.read()[0]["arms"]] == ["a1", "a2"]
    else:
        assert not _ok(code), "register accepted two arms named a1"
        assert ledger.read() == []


@pytest.mark.parametrize(
    "results, on_issue, owner_ok, accepted",
    [
        (1, 71, False, True),
        (2, 48, False, True),
        (2, 71, False, False),
        (2, 71, True, True),
    ],
    ids=["one result", "results on another issue", "two results", "--owner-ok"],
)
def test_a_third_result_for_one_issue_needs_owner_ok(
    tmp_path, monkeypatch, capsys, results, on_issue, owner_ok, accepted
):
    """Done when 1: an issue that already has 2 result rows is refused another
    registration unless --owner-ok, which the row records."""
    ev, _ = _setup(tmp_path, monkeypatch)
    for _ in range(results):
        _ledger_result(_ledger_registered(on_issue))
    before = ledger.read()

    extra = ["--owner-ok"] if owner_ok else []
    code, text = _call(ev, _register_argv("a1=faux:m", extra=extra), capsys)
    if accepted:
        assert _ok(code), f"register was refused: {text}"
        row = ledger.read()[-1]
        assert row["kind"] == "registered" and row["issue"] == 71
        assert row["owner_ok"] is owner_ok
    else:
        assert not _ok(code), "a third result for #71 was registered without --owner-ok"
        assert ledger.read() == before


@pytest.mark.parametrize(
    "registrations, owner_ok, accepted",
    [
        (1, False, True),
        (2, False, False),
        (2, True, True),
    ],
    ids=["one prior result", "the second of two registrations", "--owner-ok"],
)
def test_run_checks_the_two_result_limit_again(
    tmp_path, monkeypatch, capsys, registrations, owner_ok, accepted
):
    """The limit is checked again at run: two registrations made while #71 had
    one result can't both run, since the second would write a third result.
    The refusal says to register again with --owner-ok (run takes no such
    flag); a registration made with --owner-ok runs, and so does one run on
    top of a single earlier result."""
    ev, _ = _setup(tmp_path, monkeypatch, cases=ONE)
    log = _fake_run_case(monkeypatch, _solved_row)
    _ledger_result(_ledger_registered(71))
    first = [_register(ev, capsys, "a1=faux:m") for _ in range(registrations - 1)]
    extra = ["--owner-ok"] if owner_ok else []
    last = _register(ev, capsys, "a1=faux:m", extra=extra)
    for reg in first:
        _run(ev, capsys, reg)
    calls_before = len(log)

    code, text = _call(ev, ["run", "--registered", last["row_id"]], capsys)
    if accepted:
        assert _ok(code), f"run was refused: {text}"
        assert len(_results_of(last)) == 1
    else:
        assert not _ok(code), "a third result for #71 was run without --owner-ok"
        assert "register again" in text and "--owner-ok" in text
        assert len(log) == calls_before, "a case ran before the refusal"
        assert _results_of(last) == []


# --- run: what it writes ------------------------------------------------------


def test_run_appends_a_result_row_naming_its_registration(
    tmp_path, monkeypatch, capsys
):
    """Done when 2: one result row, on the registration's suite hash and k,
    every case run k times per arm, nothing spent under faux: each case's
    cost is faux's known 0.0 (EV9), not unknown."""
    run = _run_split(tmp_path, monkeypatch, capsys)
    ev, reg, result, log = run.ev, run.reg, run.result, run.log

    assert [r["kind"] for r in ledger.read()] == ["registered", "result"]
    assert result["issue"] == reg["issue"]
    assert result["registered"] == reg["row_id"]
    assert result["k"] == reg["k"] == 3
    assert result["suite_hash"] == reg["suite_hash"]
    assert result["fingerprints"] == reg["fingerprints"]
    assert result["limits"] == ev.SUITES[SUITE]["limits"]
    assert result["spent_usd"] == 0.0
    assert result["budget_hit"] is False
    assert sorted(result["arms"]) == ["a1", "a2"]

    # each arm under its own env: k runs of every case
    seen = sorted((c["provider"], c["model"], c["case"]) for c in log)
    want = sorted(("faux", m, n) for m in ("m1", "m2") for n in CASES for _ in range(3))
    assert seen == want
    assert len(result["cases"]) == 2 * len(CASES) * 3
    by_key = {(c["arm"], c["case"], c["run"]): c for c in result["cases"]}
    assert sorted(by_key) == sorted(
        (a, n, r) for a in ("a1", "a2") for n in CASES for r in (1, 2, 3)
    )
    case = by_key[("a1", "tx-dates-mixed", 2)]
    assert {key: case[key] for key in ledger.CASE_OUTCOME} == {
        "case": "tx-dates-mixed",
        "arm": "a1",
        "run": 2,
        "status": "no_cleaned_output",
        "solved": False,
        "repair_f1": None,
        "calls": 2,
        "new_work_tokens": 3000,
        "cost_usd": 0.0,
        "wall_s": 28.0,
    }


def test_arm_metrics_equal_consistency_on_the_same_rows(tmp_path, monkeypatch, capsys):
    """Done when 2: pass^k, pass@1 and flaky are what
    consistency.aggregate_consistency gives on the same canned rows, stored as
    raw floats, plus the aborted count."""
    result = _run_split(tmp_path, monkeypatch, capsys).result
    for name, model in (("a1", "m1"), ("a2", "m2")):
        agg = consistency.aggregate_consistency(
            consistency.group_by_case(_canned_rows(model))
        )
        arm = result["arms"][name]
        assert arm["pass_k"] == agg["mean_pass_k"]
        assert arm["pass_at_1"] == agg["mean_pass_at_1"]
        assert arm["flaky"] == agg["flaky"]
        assert arm["contained"] == "host", "these arms run on the host kernel"

    a1 = result["arms"]["a1"]
    assert a1["pass_at_1"] == pytest.approx(5 / 9)
    assert a1["pass_k"] == pytest.approx(1 / 3)
    assert a1["flaky"] == ["tx-dates-mixed"]
    assert a1["aborted"] == 1
    assert result["arms"]["a2"]["aborted"] == 0


def test_wall_time_quantiles_are_right_on_a_hand_checked_list(
    tmp_path, monkeypatch, capsys
):
    """Done when 2: p50 and p95 by ledger.quantiles over every run of the arm.
    Cost too (EV9): faux bills nothing, so 0.0 on all nine a1 runs, the one
    whose telemetry was unread included."""
    result = _run_split(tmp_path, monkeypatch, capsys).result
    a1 = result["arms"]["a1"]
    assert a1["wall_s"] == pytest.approx({"p50": 20.0, "p95": 196.52})
    assert a1["cost_usd"] == {"p50": 0.0, "p95": 0.0}


def test_false_backed_is_null_with_the_suites_reason(tmp_path, monkeypatch, capsys):
    """Done when 2: no verdicts exist before 0b, so false_backed and
    backed_rate are null on every arm, with the suite's reason."""
    result = _run_split(tmp_path, monkeypatch, capsys).result
    for name, arm in result["arms"].items():
        for key in ("false_backed", "backed_rate"):
            assert arm[key] is None, f"{name}.{key} claims a measurement"
            assert "no verdicts exist before 0b" in arm[f"{key}_reason"]


def test_metrics_are_reported_again_over_the_model_cases(tmp_path, monkeypatch, capsys):
    """Step 4: a case solved with no model call says nothing about the model,
    so each arm reports its metrics again over the cases where some run called
    it. A case whose call count is unknown is a model case (B4). An arm with no
    model case gets null with a reason, not a vacuous 1.0."""
    result = _run_split(tmp_path, monkeypatch, capsys).result
    model_rows = [
        r for r in _canned_rows("m1") if r["name"] in ("tx-dates-mixed", "tx-near-dups")
    ]
    agg = consistency.aggregate_consistency(consistency.group_by_case(model_rows))
    got = result["arms"]["a1"]["model_cases"]
    assert got is not None, "a1 called the model, so it has model cases"
    assert got["pass_k"] == agg["mean_pass_k"] == 0.0
    assert got["pass_at_1"] == agg["mean_pass_at_1"]
    assert got["pass_at_1"] == pytest.approx(1 / 3)
    assert got["flaky"] == agg["flaky"] == ["tx-dates-mixed"]

    a2 = result["arms"]["a2"]
    assert a2["model_cases"] is None
    assert a2["model_cases_reason"]
    # the two arms differ in model, so there is no A/A pair
    assert result["noise_floor"] is None
    assert result["noise_floor_reason"]


def test_two_arms_with_one_config_get_a_noise_floor(tmp_path, monkeypatch, capsys):
    """Done when 2: an A/A pair gets noise_floor, the difference in mean
    pass@1 over model cases and the union of the two flaky sets; served models
    are listed per arm, sorted."""
    ev, _ = _setup(tmp_path, monkeypatch, cases=CASES)
    _fake_run_case(monkeypatch, _aa_row)
    reg = _register(ev, capsys, "a1=faux:m", "a2=faux:m")
    result, _ = _run(ev, capsys, reg)

    floor = result["noise_floor"]
    assert floor is not None, "two arms on one config got no noise floor"
    assert sorted(floor["arms"]) == ["a1", "a2"]
    assert floor["pass_at_1_diff"] == pytest.approx(1 / 6)
    assert floor["flaky"] == ["tx-dates-mixed", "tx-near-dups"]
    assert result["served_models"] == {
        "a1": ["m", "m-2026-10"],
        "a2": ["m", "m-2026-10"],
    }


def test_a_status_built_from_an_exception_keeps_only_its_type(
    tmp_path, monkeypatch, capsys
):
    """Exception text can quote the data, and the ledger is committed, so a
    case's status stores only "error: <ExcType>". The statuses crivo writes
    itself are kept."""
    run = _run_split(tmp_path, monkeypatch, capsys)
    root, result, text = run.root, run.result, run.text
    by_key = {(c["arm"], c["case"], c["run"]): c for c in result["cases"]}
    assert by_key[("a1", "tx-near-dups", 2)]["status"] == "error: ValueError"
    assert by_key[("a1", "tx-near-dups", 3)]["status"].startswith("aborted")
    assert by_key[("a1", "tx-dates-mixed", 2)]["status"] == "no_cleaned_output"
    assert by_key[("a1", "tx-dates-mixed", 1)]["status"] == "ok"
    leaked = LEAKED_VALUE in (root / ledger.LEDGER).read_text()
    assert not leaked, "exception text reached the ledger"
    assert LEAKED_VALUE not in text, "exception text was printed"


@pytest.mark.parametrize("raises", [False, True], ids=["cases finish", "a case raises"])
def test_run_restores_the_env_and_results_dir(tmp_path, monkeypatch, capsys, raises):
    """Each arm runs under its own CRIVO_PROVIDER and CRIVO_MODEL with
    agent_run.RESULTS_DIR in a fresh bench/results/eval/<row id>/; all three
    are put back afterwards, also when a case raises. A raising case stops the
    run with a non-zero exit that names the exception's type, never its text
    (it can quote data), and writes no result."""
    ev, root = _setup(tmp_path, monkeypatch, cases=("tx-whitespace",))
    reg = _register(ev, capsys, "a1=faux:m")
    monkeypatch.setenv("CRIVO_MODEL", "the-shells-model")
    results_dir = agent_run.RESULTS_DIR
    seen = []

    def case(entry, args):
        seen.append(
            (
                os.environ.get("CRIVO_PROVIDER"),
                os.environ.get("CRIVO_MODEL"),
                Path(agent_run.RESULTS_DIR),
            )
        )
        if raises:
            raise KeyError(f"acct {LEAKED_VALUE}")
        return _row(entry["name"], "ok", 1.0, 0, 5.0)

    monkeypatch.setattr(agent_run, "_run_case", case)
    code, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    if raises:
        assert not _ok(code), "a run whose case raised exited 0"
        assert "raised KeyError" in text
        assert LEAKED_VALUE not in text, "the exception's text was printed"
        assert ledger.rows(kind="result") == []
    else:
        assert _ok(code), f"run was refused: {text}"

    assert seen, "no case ran"
    provider, model, during = seen[0]
    assert (provider, model) == ("faux", "m")
    assert _within(during, _eval_dir(root, reg))
    assert os.environ.get("CRIVO_MODEL") == "the-shells-model"
    assert "CRIVO_PROVIDER" not in os.environ
    assert agent_run.RESULTS_DIR == results_dir
    assert LEAKED_VALUE not in (root / ledger.LEDGER).read_text()


def test_run_hands_each_case_the_baseline_arm_and_the_record_dir(
    tmp_path, monkeypatch, capsys
):
    """Step 3: the baseline arm (careful autonomy, HUMAN gates skipped, host
    kernel, default caps), and --record DIR passed through (EV2) so that no
    two runs share a cassette."""
    ev, _ = _setup(tmp_path, monkeypatch, cases=("tx-whitespace",))
    log = _fake_run_case(monkeypatch, _solved_row)
    reg = _register(ev, capsys, "a1=faux:m", "a2=faux:m")
    record = (tmp_path / "cassettes").resolve()
    argv = ["run", "--registered", reg["row_id"], "--record", str(record)]
    code, text = _call(ev, argv, capsys)
    assert _ok(code), f"run was refused: {text}"

    assert len(log) == 2 * 3
    cassettes = set()
    for call in log:
        args = call["args"]
        assert args.docker is False
        assert args.max_events == agent_run.DEFAULT_MAX_EVENTS
        assert args.wall_cap == agent_run.DEFAULT_WALL_CAP
        assert getattr(args, "autonomy", None) in (None, "careful")
        assert agent_run._arm_gates(args) == "skip"
        assert getattr(args, "policies", "none") == "none"
        assert args.record is not None, "--record did not reach the case"
        tag = getattr(args, "run_tag", "") or ""
        name = f"{call['case']}{agent_run._arm_suffix(args)}{tag}.json"
        cassette = (Path(args.record) / name).resolve()
        assert record == cassette.parent or record in cassette.parents
        cassettes.add(cassette)
    assert len(cassettes) == len(log), "two runs would write one cassette"


def test_run_prints_one_screen_per_arm(tmp_path, monkeypatch, capsys):
    """Step 6: a screen per arm, with false-backed's reason since it is null;
    the key file is loaded but never printed."""
    secret = "sk-test-deepseek-4be1d07a"
    ev, _ = _setup(
        tmp_path, monkeypatch, keys=f"DEEPSEEK_API_KEY={secret}\n", cases=CASES
    )
    _fake_run_case(monkeypatch, _split_row)
    reg = _register(ev, capsys, *SPLIT_ARMS)
    _, text = _run(ev, capsys, reg)
    for name in ("a1", "a2"):
        assert name in text, f"no screen for arm {name}"
    assert "no verdicts exist before 0b" in text
    assert secret not in text, "the key was printed"


# --- run: where each case's Session output goes (#73) -------------------------


def _said(ev, argv, capsys):
    """Run the CLI: (exit code, its stdout, its stderr), kept apart, since
    _call merges them. A refusal's text is the exit code."""
    try:
        code = ev.main(argv)
    except SystemExit as exc:
        code = exc.code
    said = capsys.readouterr()
    return code, said.out, said.err


def _profile_text(marker: str) -> str:
    """A stand-in for what a Session prints while it boots, loads and profiles
    a case: schema, stats and truncated samples (ids with leading zeros, a
    sentinel, mixed date and decimal formats), marked with `marker`."""
    return "\n".join(
        [
            "starting kernel (subprocess) …",
            f"profile of df [{marker}]: 1,204 rows x 4 columns",
            "  account_id  object  1,204 non-null  e.g. 00417, 00981, 01133",
            "  posted_on   object  1,198 non-null  e.g. 2026-03-04, 04/03/2026",
            "  amount      object  1,204 non-null  e.g. 1.204,50, -99999, N/A",
            "  memo        object    611 non-null  e.g. ' ACH  REF', 'wire'",
            f"loaded df.parquet → df (ev 1) [{marker}]",
        ]
    )


def _chatty(monkeypatch, arms: dict) -> dict:
    """agent_run._run_case as it is set now (_fake_run_case's fake), made to
    print a stand-in data profile first, as a Session does. `arms` maps each
    arm's CRIVO_MODEL to its name; each (arm, case) counts its runs from 1.
    Returns each run's marker, keyed by (arm, case, run)."""
    inner = agent_run._run_case
    markers, seen = {}, {}

    def case(entry, args):
        arm, name = arms[os.environ.get("CRIVO_MODEL")], entry["name"]
        run = seen[(arm, name)] = seen.get((arm, name), 0) + 1
        marker = markers[(arm, name, run)] = f"session-output-{arm}-{name}-r{run}"
        print(_profile_text(marker))
        return inner(entry, args)

    monkeypatch.setattr(agent_run, "_run_case", case)
    return markers


def _logs_holding(top: Path, marker: str) -> list[Path]:
    """Every .log file under `top` whose text holds `marker`."""
    return [p for p in sorted(top.rglob("*.log")) if marker in p.read_text()]


def _per_case(lines) -> list[str]:
    """The `<arm> <case> r<run>` heading each per-case line among `lines`."""
    heads = []
    for line in lines:
        head, sep, _ = line.partition(": ")
        parts = head.split(" ")
        run = parts[-1] if len(parts) == 3 else ""
        if sep and run.startswith("r") and run[1:].isdigit():
            heads.append(head)
    return heads


def _names_the_logs(text: str, reg: dict) -> bool:
    """Whether `text` names a logs dir by a path that holds the run's row id."""
    return any(reg["row_id"] in word and "logs" in word for word in text.split())


def test_each_cases_session_output_goes_to_its_log_not_the_terminal(
    tmp_path, monkeypatch, capsys
):
    """#73: each case's Session prints its data profile, about 2,800 lines
    for the full suite at k=3 with 2 arms, and the /eval skill reads what a
    run prints. So each run's Session output goes to its own log,
    <row id>/<arm>/logs/<case>.r<run>.log, and the terminal keeps every
    per-case line, every arm's screen and the summary, whose closing lines
    say where the logs are."""
    ev, root = _setup(tmp_path, monkeypatch, cases=CASES)
    reg = _register(ev, capsys, *SPLIT_ARMS)
    _fake_run_case(monkeypatch, _split_row)
    markers = _chatty(monkeypatch, {"m1": "a1", "m2": "a2"})
    code, out, err = _said(ev, ["run", "--registered", reg["row_id"]], capsys)
    assert _ok(code), "run was refused"
    assert len(markers) == 2 * len(CASES) * 3, "not every run printed"

    loud = [m for m in markers.values() if m in out or m in err]
    assert len(loud) == 0, f"{len(loud)} runs' Session output reached the terminal"
    assert "account_id" not in out + err, "a data profile reached the terminal"

    lines = out.splitlines()
    want = sorted(f"{a} {c} r{r}" for a, c, r in markers)
    assert sorted(_per_case(lines)) == want, "a per-case line went missing"
    for arm in ("a1 (faux:m1)", "a2 (faux:m2)"):
        assert arm in lines, f"no screen for {arm}"
    assert any(line.startswith("result ") for line in lines), "no summary"

    top = _eval_dir(root, reg)
    for (arm, case, run), marker in markers.items():
        log = top / arm / "logs" / f"{case}.r{run}.log"
        assert _logs_holding(top, marker) == [log], f"{arm} {case} r{run}'s log"
    tail = "\n".join(lines[lines.index("a1 (faux:m1)") :])
    assert _names_the_logs(tail, reg), "the closing lines never say where the logs are"


def test_a_case_that_prints_then_raises_leaves_its_output_in_its_log(
    tmp_path, monkeypatch, capsys
):
    """#73: a case whose Session printed, then raised, still keeps that output
    in its log and off the terminal; the refusal still says what raised and
    names the logs dir, and stdout is the terminal's again afterwards."""
    ev, root = _setup(tmp_path, monkeypatch, cases=CASES)
    reg = _register(ev, capsys, "a1=faux:m")

    def raising(model, name, i):
        if name == "tx-dates-mixed":
            raise KeyError(f"acct {LEAKED_VALUE}")
        return _row(name, "ok", 1.0, 0, 5.0)

    _fake_run_case(monkeypatch, raising)
    markers = _chatty(monkeypatch, {"m": "a1"})
    code, out, err = _said(ev, ["run", "--registered", reg["row_id"]], capsys)
    assert not _ok(code), "a run whose case raised exited 0"
    refusal = code if isinstance(code, str) else ""
    assert "raised KeyError" in refusal

    marker = markers[("a1", "tx-dates-mixed", 1)]
    leaked = marker in out + err + refusal
    assert not leaked, "the raising case's Session output reached the terminal"
    top = _eval_dir(root, reg)
    assert _logs_holding(top, marker) == [top / "a1" / "logs" / "tx-dates-mixed.r1.log"]
    assert _per_case(out.splitlines()) == ["a1 tx-whitespace r1"]
    assert _names_the_logs(refusal, reg), "the refusal never says where the logs are"
    assert LEAKED_VALUE not in out + err + refusal, "the exception's text was printed"

    assert not getattr(sys.stdout, "closed", False), "stdout was left closed"
    print("after the refusal")
    assert "after the refusal" in capsys.readouterr().out, "stdout was not put back"


def test_served_models_count_the_runs_whose_telemetry_was_unread(
    tmp_path, monkeypatch, capsys
):
    """EV1: a run whose telemetry was unreadable named no model, and that is
    not "none named". served_models keeps the union of what was read, and
    served_models_unread counts the unread runs per arm, present only when
    some were (a1's tx-near-dups run 2 here). a1's screen says the models are
    unknown on 1 run instead of claiming none were named."""
    run = _run_split(tmp_path, monkeypatch, capsys)
    result = run.result
    assert result["served_models"] == {"a1": ["m1", "m1-0925"], "a2": []}
    assert result.get("served_models_unread") == {"a1": 1}

    served = [line for line in run.text.splitlines() if "served" in line.lower()]
    assert len(served) == 2, "one served-models line per arm's screen"
    a1 = served[0]
    assert "none named" not in a1, "a1 had a run whose models are unknown"
    assert "unknown" in a1 and "1 run" in a1


# --- run: what it spends (EV9, #72) -------------------------------------------


def test_run_hands_each_case_the_registered_per_case_cap(tmp_path, monkeypatch, capsys):
    """Step 3: every case runs under the registration's per-case cap, which
    agent_run's spend guard reads off the namespace."""
    ev, _ = _setup(tmp_path, monkeypatch, cases=ONE)
    log = _fake_run_case(monkeypatch, _solved_row)
    reg = _register(ev, capsys, "a1=faux:m", budget=2.0, per_case=0.35)
    _run(ev, capsys, reg)
    caps = [getattr(call["args"], "per_case_usd", None) for call in log]
    assert caps == [0.35] * 3


# One priced arm, three cases, k=3: (status, f1, calls, wall, served, cost).
# Every spend is read: an unread one stops the run (decision 1 on #72), which
# test_a_run_stops_at_the_first_case_whose_spend_is_unread pins. Costs,
# sorted: 0, 0, 0, 0.0123, 0.0209, 0.0297, 0.0388, 0.0412, 0.0571.
# Hand-checked, inclusive method: p50 at 4 = 0.0209; p95 at 7.6 = 0.0412 +
# 0.6 * 0.0159 = 0.05074. Model cases (tx-dates-mixed, tx-near-dups): 0.0123,
# 0.0209, 0.0297, 0.0388, 0.0412, 0.0571, so p50 at 2.5 = 0.0297 + 0.5 *
# 0.0091 = 0.03425 and p95 at 4.75 = 0.0412 + 0.75 * 0.0159 = 0.053125.
# Spent: the sum, 0.2.
COST_TABLE = {
    "tx-whitespace": [("ok", 1.0, 0, 4.0 + i, (), 0.0) for i in range(3)],
    "tx-dates-mixed": [
        ("ok", 1.0, 4, 20.0, ("m",), 0.0412),
        ("no_cleaned_output", None, 3, 28.0, ("m",), 0.0388),
        ("ok", 1.0, 5, 33.5, ("m",), 0.0571),
    ],
    "tx-near-dups": [
        ("ok", 0.5, 2, 18.0, ("m",), 0.0123),
        ("no_cleaned_output", None, 3, 22.0, ("m",), 0.0297),
        ("ok", 1.0, 2, 19.0, ("m",), 0.0209),
    ],
}


def _cost_row(model, name, i):
    return _row(name, *COST_TABLE[name][i][:5], cost=COST_TABLE[name][i][5])


def test_each_case_costs_what_it_cost_and_the_arm_gets_p50_and_p95(
    tmp_path, monkeypatch, capsys
):
    """EV9: each case outcome keeps what its run cost, the arm reports p50 and
    p95 by ledger.quantiles over its runs, again over its model cases, and
    spent_usd is the sum."""
    ev, _ = _setup(tmp_path, monkeypatch, cases=CASES)
    _fake_run_case(monkeypatch, _cost_row)
    reg = _register(ev, capsys, "a1=faux:m")
    result, _ = _run(ev, capsys, reg)

    by_key = {(c["case"], c["run"]): c["cost_usd"] for c in result["cases"]}
    assert by_key[("tx-whitespace", 1)] == 0.0
    assert by_key[("tx-dates-mixed", 3)] == 0.0571
    assert by_key[("tx-near-dups", 2)] == 0.0297
    a1 = result["arms"]["a1"]
    assert a1["cost_usd"] == pytest.approx({"p50": 0.0209, "p95": 0.05074})
    assert a1["model_cases"]["cost_usd"] == pytest.approx(
        {"p50": 0.03425, "p95": 0.053125}
    )
    assert result["spent_usd"] == pytest.approx(0.2)
    assert result["budget_hit"] is False


@pytest.mark.parametrize(
    "budget, ran", [(0.6, 2), (10.0, 18)], ids=["room for two", "room for all"]
)
def test_a_run_stops_before_a_case_that_could_cross_its_budget(
    tmp_path, monkeypatch, capsys, budget, ran
):
    """Done when 4: each case costs $0.20 under a $0.25 cap. Before each case
    the run checks spent + cap against the budget: with $0.60, two cases run
    ($0.40 spent) and 0.40 + 0.25 > 0.60 stops it before the third. The result
    says budget_hit and lists every case not run; arms run one after another,
    so a2 never starts, and it is still in the result (check_locks lock 2),
    its cost null with a reason. With $10 every case runs."""
    ev, root = _setup(tmp_path, monkeypatch, cases=CASES)

    def priced(model, name, i):
        return _row(name, "ok", 1.0, 3, 25.0, (model,), cost=0.2)

    log = _fake_run_case(monkeypatch, priced)
    reg = _register(ev, capsys, "a1=faux:m1", "a2=faux:m2", budget=budget)
    _, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    results = _results_of(reg)
    assert len(results) == 1, f"no result was written: {text}"
    (result,) = results

    assert len(log) == ran, "the run did not stop before the case that could cross"
    every = [(a, n, r) for a in ("a1", "a2") for r in (1, 2, 3) for n in CASES]
    done = sorted((c["arm"], c["case"], c["run"]) for c in result["cases"])
    assert done == sorted(every[:ran])
    not_run = result.get("cases_not_run", [])
    assert sorted((c["arm"], c["case"], c["run"]) for c in not_run) == sorted(
        every[ran:]
    )
    assert result["spent_usd"] == pytest.approx(0.2 * ran)
    assert result["budget_hit"] is (ran < len(every))
    assert sorted(result["arms"]) == ["a1", "a2"]
    if ran < len(every):
        assert "budget" in text.lower()
        a2 = result["arms"]["a2"]
        assert a2["cost_usd"] is None
        assert a2["cost_usd_reason"]

    _commit(root, "ledger: an eval")
    assert _check_locks().check(str(root)) == []


@pytest.mark.parametrize(
    "budget", [0.55, 10.0], ids=["the cap would let one more run", "room for all"]
)
def test_a_run_stops_at_the_first_case_whose_spend_is_unread(
    tmp_path, monkeypatch, capsys, budget
):
    """Decision 1 on #72: a priced case whose spend can't be read could have
    spent anything up to its cap plus a call, so the run stops there, however
    much budget is left. The first case (a1, tx-whitespace, run 1) is unread;
    a second would cost $0.10 under a $0.25 cap. Only the first ran: every
    later case is not run and budget_hit is set. Nothing known was spent, so
    spent_usd is 0.0, with spent_usd_unread 1 beside it, and the arm counts
    its unread run (cost_usd_unread 1) under a null cost with a reason. With
    $0.55, charging the unread case the full cap ($0.25) would still have run
    the second case; with $10 it would have run them all."""
    ev, root = _setup(tmp_path, monkeypatch, cases=CASES)

    def first_unread(model, name, i):
        if (model, name, i) == ("m1", "tx-whitespace", 0):
            status = "aborted: per-case budget (spend unread)"
            return _row(name, status, None, 3, 22.0, (model,), cost=None)
        return _row(name, "ok", 1.0, 3, 25.0, (model,), cost=0.1)

    log = _fake_run_case(monkeypatch, first_unread)
    reg = _register(ev, capsys, "a1=faux:m1", "a2=faux:m2", budget=budget)
    _, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    results = _results_of(reg)
    assert len(results) == 1, f"no result was written: {text}"
    (result,) = results

    assert len(log) == 1, "the run went on past a case whose spend was unread"
    assert [c["cost_usd"] for c in result["cases"]] == [None], "unread is not 0"
    every = [(a, n, r) for a in ("a1", "a2") for r in (1, 2, 3) for n in CASES]
    not_run = result.get("cases_not_run", [])
    assert sorted((c["arm"], c["case"], c["run"]) for c in not_run) == sorted(every[1:])
    assert result["budget_hit"] is True
    assert result["spent_usd"] == 0.0
    assert result.get("spent_usd_unread") == 1
    a1 = result["arms"]["a1"]
    assert a1.get("cost_usd_unread") == 1
    assert a1["cost_usd"] is None
    assert a1["cost_usd_reason"]

    _commit(root, "ledger: an eval")
    assert _check_locks().check(str(root)) == []


def test_an_aa_pair_cut_by_the_budget_gets_no_noise_floor(
    tmp_path, monkeypatch, capsys
):
    """Two arms on one config are an A/A pair, but once the budget stops the
    run in a2 the two ran unequal numbers of runs (a1 all 9, a2 3), so their
    pass@1 spread is not a noise floor: null, with a reason. Each case costs
    $0.20 under a $0.25 cap and a $2.60 budget: before the 13th case $2.40 is
    spent and 2.40 + 0.25 > 2.60. An A/A pair that ran every case still gets
    one (test_two_arms_with_one_config_get_a_noise_floor)."""
    ev, _ = _setup(tmp_path, monkeypatch, cases=CASES)

    def priced(model, name, i):
        return _row(name, "ok", 1.0, 3, 25.0, (model,), cost=0.2)

    log = _fake_run_case(monkeypatch, priced)
    reg = _register(ev, capsys, "a1=faux:m", "a2=faux:m", budget=2.6)
    _, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    results = _results_of(reg)
    assert len(results) == 1, f"no result was written: {text}"
    (result,) = results

    assert len(log) == 12, "the budget did not cut the run inside a2"
    assert result["budget_hit"] is True
    assert result["noise_floor"] is None, "unequal runs were read as a noise floor"
    assert result["noise_floor_reason"]


def _json_under(top: Path) -> tuple[list, str]:
    """Every JSON document in a .json or .jsonl file under `top`, and all
    their text."""
    docs, texts = [], []
    for path in sorted(top.rglob("*")):
        if path.suffix not in (".json", ".jsonl") or not path.is_file():
            continue
        text = path.read_text()
        texts.append(text)
        if path.suffix == ".json":
            docs.append(json.loads(text))
        else:
            docs += [json.loads(line) for line in text.splitlines() if line.strip()]
    return docs, "\n".join(texts)


def _walk(node):
    yield node
    children = node.values() if isinstance(node, dict) else node
    if isinstance(node, (dict, list)):
        for child in children:
            yield from _walk(child)


def test_a_case_that_raises_keeps_the_rows_run_and_says_what_was_spent(
    tmp_path, monkeypatch, capsys
):
    """#71's note and scout call 4: a case that raises still writes no result
    row, but once runs cost money the rows already run are not thrown away.
    tx-whitespace ($0.50) and tx-dates-mixed ($0.25) finish, tx-near-dups
    raises: the rows run and the $0.75 spent are kept under the run's
    bench/results/eval/<row id>/, and the refusal says what was spent. The
    exception's text (it can quote data) reaches neither."""
    ev, root = _setup(tmp_path, monkeypatch, cases=CASES)
    reg = _register(ev, capsys, "a1=faux:m", budget=3.0, per_case=0.6)
    costs = {"tx-whitespace": 0.5, "tx-dates-mixed": 0.25}

    def case(entry, args):
        name = entry["name"]
        if name == "tx-near-dups":
            raise KeyError(f"acct {LEAKED_VALUE}")
        return _row(name, "ok", 1.0, 4, 20.0, ("m",), cost=costs[name])

    monkeypatch.setattr(agent_run, "_run_case", case)
    code, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    assert not _ok(code), "a run whose case raised exited 0"
    assert "raised KeyError" in text
    assert ledger.rows(kind="result") == []
    assert "0.75" in text, "the refusal does not say what was spent"
    assert LEAKED_VALUE not in text, "the exception's text was printed"

    docs, kept = _json_under(_eval_dir(root, reg))
    nodes = [n for doc in docs for n in _walk(doc)]
    named = {n.get("case") or n.get("name") for n in nodes if isinstance(n, dict)}
    assert {"tx-whitespace", "tx-dates-mixed"} <= named, "the rows run were not kept"
    numbers = [n for n in nodes if isinstance(n, float)]
    assert any(n == pytest.approx(0.75) for n in numbers), "the spend was not kept"
    assert LEAKED_VALUE not in kept, "the exception's text was kept"


# --- run: what it refuses -----------------------------------------------------


@pytest.mark.parametrize(
    "part, path",
    [
        ("prompt", "src/crivo/prompts.py"),
        ("referee", "src/crivo/verify.py"),
        ("scorer", "bench/score.py"),
        ("suite", "bench/corpus.py"),
    ],
)
def test_run_refuses_when_a_hashed_file_moved_since_registering(
    tmp_path, monkeypatch, capsys, part, path
):
    """Done when 1 and B2: a committed change to a file the prompt, referee,
    scorer or suite hash covers is refused before any case runs, naming what
    moved."""
    ev, root = _setup(tmp_path, monkeypatch, cases=ONE)
    log = _fake_run_case(monkeypatch, _solved_row)
    reg = _register(ev, capsys, "a1=faux:m")
    with open(root / path, "a", encoding="utf-8") as fh:
        fh.write("\n# changed after registering\n")
    _commit(root, f"change {path}")

    code, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    assert not _ok(code), f"run accepted a {part} change since registering"
    assert part in text.lower() or Path(path).name in text
    assert log == []
    assert ledger.rows(kind="result") == []


def test_run_refuses_a_dirty_tree(tmp_path, monkeypatch, capsys):
    """B2: an uncommitted tracked change is refused. The registration row the
    ledger holds uncommitted is not a change (every other run test runs so)."""
    ev, root = _setup(tmp_path, monkeypatch, cases=ONE)
    log = _fake_run_case(monkeypatch, _solved_row)
    reg = _register(ev, capsys, "a1=faux:m")
    with open(root / "src" / "crivo" / "loop.py", "a", encoding="utf-8") as fh:
        fh.write("\n# an uncommitted edit\n")

    code, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    assert not _ok(code), "run accepted a dirty tree"
    assert "dirty" in text.lower()
    assert log == []
    assert ledger.rows(kind="result") == []


@pytest.mark.parametrize(
    "path, accepted",
    [
        (None, True),
        ("src/crivo/loop.py", False),
        ("bench/agent_run.py", False),
    ],
    ids=["only the ledger committed", "loop.py", "agent_run.py"],
)
def test_run_refuses_code_committed_since_registering_outside_the_ledger(
    tmp_path, monkeypatch, capsys, path, accepted
):
    """B2: no hash covers loop.py or agent_run.py, so a commit since the
    registration's that touches anything but the ledger is refused. Committing
    the ledger row itself is not a code change."""
    ev, root = _setup(tmp_path, monkeypatch, cases=ONE)
    log = _fake_run_case(monkeypatch, _solved_row)
    reg = _register(ev, capsys, "a1=faux:m")
    if path:
        with open(root / path, "a", encoding="utf-8") as fh:
            fh.write("\n# changed after registering\n")
    _commit(root, "after registering")

    code, text = _call(ev, ["run", "--registered", reg["row_id"]], capsys)
    if accepted:
        assert _ok(code), f"run was refused after committing the ledger: {text}"
        assert len(ledger.rows(kind="result")) == 1
    else:
        assert not _ok(code), f"run accepted a commit to {path} since registering"
        assert log == []
        assert ledger.rows(kind="result") == []


def _tripwire(messages, model=None):
    """llm.generate for a test that must make no model call."""
    raise AssertionError("a model call was made")


def test_run_refuses_an_unpriced_arm_and_runs_a_priced_one(
    tmp_path, monkeypatch, capsys
):
    """EV9 lifts B1: a non-faux arm runs once its model has a price, since the
    caps now bound what it spends. An arm with no price (a registration
    appended without register, so nothing refused it) is still refused before
    any case runs. _run_case is faked and generate is a tripwire, so no call
    is made."""
    ev, _ = _setup(
        tmp_path, monkeypatch, keys="ANTHROPIC_API_KEY=sk-ant-test\n", cases=ONE
    )
    monkeypatch.setattr(llm, "generate", _tripwire)
    log = _fake_run_case(monkeypatch, _solved_row)
    entries = ev.SUITES[SUITE]["splits"]["dev"]
    unpriced = _ledger_registered(
        71,
        arms=[_arm("a1", "claude", OPUS)],
        suite_hash=ledger.suite_hash(entries, ev.SUITES[SUITE]["files"]),
        budget_usd=1.0,
        per_case_usd=0.25,
    )

    code, text = _call(ev, ["run", "--registered", unpriced["row_id"]], capsys)
    assert not _ok(code), "run accepted an arm with no price"
    assert "price" in text.lower()
    assert log == []
    assert ledger.rows(kind="result") == []

    _price(monkeypatch, "claude", OPUS)
    reg = _register(ev, capsys, "a1=faux:m", f"a2=claude:{OPUS}")
    result, _ = _run(ev, capsys, reg)
    assert sorted(result["arms"]) == ["a1", "a2"]
    assert sorted({c["provider"] for c in log}) == ["claude", "faux"]


def _raw_registered(issue, ev, budget, per_case):
    """A registration on the cut suite written straight into the ledger file,
    past ledger.append (which refuses NaN), as a hand edit or an older writer
    could leave it."""
    entries = ev.SUITES[SUITE]["splits"]["dev"]
    row = ledger.new_row(
        "registered",
        issue,
        type="code",
        suite=SUITE,
        split="dev",
        arms=[_arm("a1", "faux", "m", price=_prices().PRICES["faux"])],
        k=3,
        hypothesis=HYPOTHESIS,
        primary="pass_at_1",
        guards=["aborted"],
        rule=RULE,
        budget_usd=budget,
        per_case_usd=per_case,
        fingerprints=ledger.fingerprints(),
        suite_hash=ledger.suite_hash(entries, ev.SUITES[SUITE]["files"]),
    )
    with open(ledger.LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return row


@pytest.mark.parametrize(
    "budget, per_case",
    [
        (1.0, -1.0),
        (1.0, float("nan")),
        (1.0, True),
        (0.5, 0.75),
    ],
    ids=["a negative cap", "a NaN cap", "True as a cap", "a cap above the budget"],
)
def test_run_checks_the_registered_caps_again_before_any_case(
    tmp_path, monkeypatch, capsys, budget, per_case
):
    """A registration register never checked (appended by hand, or NaN
    written past ledger.append) is refused by run before any case runs and
    writes no result: no cost is greater than NaN, -1 is not an amount, True
    is not one either though it compares as 1, and a cap above the budget
    can't hold. The same registration with sane caps runs."""
    ev, _ = _setup(tmp_path, monkeypatch, cases=ONE)
    log = _fake_run_case(monkeypatch, _solved_row)
    bad = _raw_registered(71, ev, budget, per_case)

    code, _ = _call(ev, ["run", "--registered", bad["row_id"]], capsys)
    assert not _ok(code), f"run accepted --per-case-usd {per_case!r}"
    assert log == [], "a case ran under caps register would have refused"
    assert ledger.rows(kind="result") == []

    sane = _raw_registered(71, ev, 1.0, 0.25)
    result, _ = _run(ev, capsys, sane)
    assert len(log) == 3
    assert result["budget_hit"] is False


@pytest.mark.parametrize("how", ["made beforehand", "a second run"])
def test_run_refuses_an_existing_results_dir(tmp_path, monkeypatch, capsys, how):
    """Step 3: every run writes a fresh bench/results/eval/<row id>/. One that
    exists already, from anything or from an earlier run, is refused."""
    ev, root = _setup(tmp_path, monkeypatch, cases=ONE)
    log = _fake_run_case(monkeypatch, _solved_row)
    reg = _register(ev, capsys, "a1=faux:m")
    argv = ["run", "--registered", reg["row_id"]]
    if how == "made beforehand":
        _eval_dir(root, reg).mkdir(parents=True)
        expected_results = 0
    else:
        code, text = _call(ev, argv, capsys)
        assert _ok(code), f"the first run was refused: {text}"
        expected_results = 1
    calls_before = len(log)

    code, text = _call(ev, argv, capsys)
    assert not _ok(code), "run reused an existing results dir"
    assert len(log) == calls_before, "a case ran into an existing results dir"
    assert len(ledger.rows(kind="result")) == expected_results


def test_run_never_resumes_a_case_on_disk(tmp_path, monkeypatch, capsys):
    """agent_run.main resumes a case whose results file exists; the runner
    must not. With finished rows for the case on disk where agent_run keeps
    them, every run still calls _run_case, in the fresh results dir."""
    ev, root = _setup(tmp_path, monkeypatch, cases=("tx-whitespace",))
    on_disk = root / "bench" / "results" / "agent"
    on_disk.mkdir(parents=True)

    finished = json.dumps(_row("tx-whitespace", "ok", 1.0, 0, 3.0))
    for name in ("tx-whitespace", *(f"tx-whitespace.r{i}" for i in (1, 2, 3))):
        (on_disk / f"{name}.json").write_text(finished)

    def unsolved(model, name, i):
        return _row(name, "no_cleaned_output", None, 2, 30.0, ("m",))

    log = _fake_run_case(monkeypatch, unsolved)
    reg = _register(ev, capsys, "a1=faux:m")
    result, _ = _run(ev, capsys, reg)

    assert [c["case"] for c in log] == ["tx-whitespace"] * 3
    top = _eval_dir(root, reg)
    assert all(_within(c["results_dir"], top) for c in log)
    statuses = [c["status"] for c in result["cases"]]
    assert statuses == ["no_cleaned_output"] * 3, "a finished row was resumed"


# --- decide ------------------------------------------------------------------


@pytest.mark.parametrize(
    "flags, decision, linked",
    [
        (["--result", "{result}", "--adopted"], "adopted", True),
        (["--result", "{result}", "--dropped"], "dropped", True),
        (["--shipped-unmeasured", "--issue", "71"], "shipped-unmeasured", False),
    ],
    ids=["adopted", "dropped", "shipped-unmeasured"],
)
def test_decide_appends_one_decision_row(
    tmp_path, monkeypatch, capsys, flags, decision, linked
):
    """Step 5: adopted and dropped name a result and take its issue;
    shipped-unmeasured names no result, only its issue (ED6)."""
    ev, _ = _setup(tmp_path, monkeypatch)
    result = _ledger_result(_ledger_registered(48))
    argv = ["decide", *(f.format(result=result["row_id"]) for f in flags)]
    code, text = _call(ev, [*argv, "--note", NOTE], capsys)
    assert _ok(code), f"decide was refused: {text}"

    (row,) = ledger.rows(kind="decision")
    assert row["decision"] == decision
    assert row["note"] == NOTE
    assert row["result"] == (result["row_id"] if linked else None)
    assert row["issue"] == (48 if linked else 71)


@pytest.mark.parametrize(
    "flags",
    [
        ["--adopted"],
        ["--dropped"],
        ["--result", "{result}", "--shipped-unmeasured", "--issue", "71"],
        ["--shipped-unmeasured"],
        ["--result", "{result}", "--adopted", "--dropped"],
        ["--result", "{result}"],
    ],
    ids=[
        "adopted without --result",
        "dropped without --result",
        "shipped-unmeasured with --result",
        "shipped-unmeasured without --issue",
        "two decisions",
        "no decision",
    ],
)
def test_decide_refuses_a_malformed_decision(tmp_path, monkeypatch, capsys, flags):
    """B5: --result is required for adopted and dropped, and refused with
    --shipped-unmeasured; one decision per row."""
    ev, _ = _setup(tmp_path, monkeypatch)
    result = _ledger_result(_ledger_registered(48))
    argv = ["decide", *(f.format(result=result["row_id"]) for f in flags)]
    code, _ = _call(ev, [*argv, "--note", NOTE], capsys)
    assert not _ok(code), f"decide accepted {flags}"
    assert ledger.rows(kind="decision") == []


@pytest.mark.parametrize(
    "type_, part, path",
    [
        ("behaviour", "prompt", "src/crivo/prompts.py"),
        ("behaviour", "referee", "src/crivo/verify.py"),
        ("behaviour", "scorer", "bench/score.py"),
        (None, "prompt", "src/crivo/prompts.py"),
    ],
    ids=["behaviour, prompt", "behaviour, referee", "behaviour, scorer", "untyped"],
)
def test_decide_adopted_refuses_a_result_whose_hashes_moved(
    tmp_path, monkeypatch, capsys, type_, part, path
):
    """#71's note and scout call 5: check_locks' lock 3 holds an adopted
    decision on a behaviour (or untyped) registration to the prompt, referee
    and scorer files of the commit that lands it, and the ledger is
    append-only, so a decision row that breaks it leaves dev red for good.
    decide --adopted refuses one whose hash moved since the result, naming
    what moved. Dropping that result is still accepted, and so is adopting a
    code registration's result on the same moved file (lock 3 exempts it)."""
    ev, root = _setup(tmp_path, monkeypatch)
    result = _ledger_result(_ledger_registered(48, type_=type_))
    exempt = _ledger_result(_ledger_registered(49, type_="code"))
    with open(root / path, "a", encoding="utf-8") as fh:
        fh.write("\n# changed after the result\n")
    _commit(root, f"change {path}")

    argv = ["decide", "--result", result["row_id"], "--adopted", "--note", NOTE]
    code, text = _call(ev, argv, capsys)
    assert not _ok(code), f"decide adopted a result whose {part} hash moved"
    assert part in text.lower()
    assert ledger.rows(kind="decision") == []

    for row, flag in ((result, "--dropped"), (exempt, "--adopted")):
        argv = ["decide", "--result", row["row_id"], flag, "--note", NOTE]
        code, text = _call(ev, argv, capsys)
        assert _ok(code), f"decide {flag} was refused: {text}"
    decided = [(d["result"], d["decision"]) for d in ledger.rows(kind="decision")]
    assert decided == [(result["row_id"], "dropped"), (exempt["row_id"], "adopted")]


@pytest.mark.parametrize(
    "how, refused",
    [
        ("moved at HEAD, the tree holds the result's bytes", True),
        ("the tree drifted from HEAD", True),
        ("an unrelated tracked file is dirty", False),
    ],
    ids=["moved at HEAD", "tree drift", "unrelated file dirty"],
)
def test_decide_adopted_reads_the_files_committed_at_head(
    tmp_path, monkeypatch, capsys, how, refused
):
    """Decision 3 on #72: lock 3 hashes the files committed with the decision
    line, never the working tree. So prompts.py moved at HEAD is refused even
    when the working tree has the result's bytes back, and a working tree
    that drifts from HEAD is refused too (committing it would move the hash).
    An unmoved behaviour result is still adopted while an unrelated tracked
    file (loop.py) is dirty, and the decision passes check_locks once
    committed."""
    ev, root = _setup(tmp_path, monkeypatch)
    result = _ledger_result(_ledger_registered(48, type_="behaviour"))
    prompts = root / "src" / "crivo" / "prompts.py"
    measured = prompts.read_bytes()
    if how.startswith("moved at HEAD"):
        prompts.write_bytes(measured + b"\n# changed after the result\n")
        _commit(root, "change prompts.py")
        prompts.write_bytes(measured)
    elif how.startswith("the tree drifted"):
        prompts.write_bytes(measured + b"\n# an uncommitted edit\n")
    else:
        with open(root / "src" / "crivo" / "loop.py", "a", encoding="utf-8") as fh:
            fh.write("\n# an uncommitted edit\n")

    argv = ["decide", "--result", result["row_id"], "--adopted", "--note", NOTE]
    code, text = _call(ev, argv, capsys)
    if refused:
        assert not _ok(code), f"decide adopted a result when {how}"
        assert "prompt" in text.lower()
        assert ledger.rows(kind="decision") == []
    else:
        assert _ok(code), f"decide was refused when {how}: {text}"
        assert [d["decision"] for d in ledger.rows(kind="decision")] == ["adopted"]
        _commit(root, "ledger: adopted")
        assert _check_locks().check(str(root)) == []


# --- the ledger's locks ------------------------------------------------------


def test_every_row_the_runner_appends_passes_append_and_check_locks(
    tmp_path, monkeypatch, capsys
):
    """Every row register, run and decide append passes ledger.append, and
    scripts/check_locks passes on the tmp repo once they are committed. A
    behaviour registration, so the adopted decision is checked against the
    code that landed it."""
    run = _run_split(tmp_path, monkeypatch, capsys, type_="behaviour")
    ev, root, result = run.ev, run.root, run.result
    argv = ["decide", "--result", result["row_id"], "--adopted", "--note", NOTE]
    code, text = _call(ev, argv, capsys)
    assert _ok(code), f"decide was refused: {text}"

    rows = ledger.read()
    assert [r["kind"] for r in rows] == ["registered", "result", "decision"]
    again = tmp_path / "again.jsonl"
    for row in rows:
        ledger.append(row, path=again)
    _commit(root, "ledger: an eval")
    assert _check_locks().check(str(root)) == []


# --- the key file ------------------------------------------------------------


def test_the_key_file_is_the_main_checkouts_from_a_worktree(tmp_path, monkeypatch):
    """Step 3: a worktree has no key file, so the runner reads the main
    checkout's, at the parent of `git rev-parse --git-common-dir`. Only the
    path is checked; nothing is read."""
    ev = _eval()
    main = _repo(tmp_path, monkeypatch)
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", str(worktree), "-b", "t/wt")
    want = (main / ".env").resolve()
    for where in (main, worktree):
        monkeypatch.chdir(where)
        assert Path(ev._key_file()).resolve() == want, f"from {where.name}"


# --- end to end --------------------------------------------------------------


def test_one_faux_run_on_a_smoke_case_writes_a_registered_and_a_result_row(
    tmp_path, monkeypatch, capsys
):
    """Done when 3: the real agent_run._run_case on a real subprocess kernel,
    under faux. tx-whitespace is solved by the registered whitespace fixer
    behind one plain gate, so no model call is made (one would raise on the
    empty faux queue): the arm has no model cases. #73: the real Session's
    output goes to each run's log, so stdout before the arm's screen is the
    per-case lines alone (counted, never quoted: they are the Session's)."""
    ev, root = _setup(tmp_path, monkeypatch, cases=("tx-whitespace",))
    t0 = time.monotonic()
    reg = _register(ev, capsys, "a1=faux:m")
    code, out, _ = _said(ev, ["run", "--registered", reg["row_id"]], capsys)
    took = time.monotonic() - t0
    assert _ok(code), "run was refused"
    (result,) = _results_of(reg)

    lines = out.splitlines()
    assert "a1 (faux:m)" in lines, "no screen for a1"
    before = [line for line in lines[: lines.index("a1 (faux:m)")] if line.strip()]
    stray = len(before) - len(_per_case(before))
    assert stray == 0, f"{stray} lines of Session output reached stdout"
    runs = [f"a1 tx-whitespace r{run}" for run in (1, 2, 3)]
    assert _per_case(before) == runs
    for run in (1, 2, 3):
        log = _eval_dir(root, reg) / "a1" / "logs" / f"tx-whitespace.r{run}.log"
        assert log.is_file() and log.stat().st_size > 0, f"run {run} has no log"

    assert [r["kind"] for r in ledger.read()] == ["registered", "result"]
    cases = sorted(result["cases"], key=lambda c: c["run"])
    assert [(c["case"], c["run"]) for c in cases] == [
        ("tx-whitespace", 1),
        ("tx-whitespace", 2),
        ("tx-whitespace", 3),
    ]
    assert [c["calls"] for c in cases] == [0, 0, 0], (
        "tx-whitespace now needs the model: pick another case"
    )
    assert [c["status"] for c in cases] == ["ok", "ok", "ok"]
    arm = result["arms"]["a1"]
    assert arm["model_cases"] is None
    assert arm["model_cases_reason"]
    assert result["spent_usd"] == 0.0
    assert "CRIVO_PROVIDER" not in os.environ

    _commit(root, "ledger: an eval")
    assert _check_locks().check(str(root)) == []
    print(f"end to end: register and run in {took:.1f}s")
