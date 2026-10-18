"""Pre-registered evals of the agent lane (spec: specs/2026-10-17-eval-tooling.md
EV8, #71).

`register` writes the arms, k, hypothesis and rule before any case runs;
`run --registered ROW` runs the suite's cases k times per arm through
bench.agent_run and appends the result; `decide` appends the adopt, drop or
shipped-unmeasured call Aarmen made. Every row goes through bench.ledger.

    python -m bench.eval register --issue N --type behaviour \\
        --suite agent-clean-smoke --split dev --arm a1=faux:m --k 3 \\
        --budget-usd 0 --per-case-usd 0 --hypothesis T --primary pass_at_1 \\
        --guards aborted --rule T [--dry]
    python -m bench.eval run --registered ROW [--record DIR]
    python -m bench.eval decide --result ROW (--adopted | --dropped) --note T
    python -m bench.eval decide --shipped-unmeasured --issue N --note T

The caps (EV9, #72): an arm whose model has no entry in bench.prices is
refused, and its entry is copied onto the registered arm. Each case runs
under --per-case-usd (agent_run's spend guard), and before each case `run`
stops if what it spent plus that cap could cross --budget-usd. The guard
reads the spend after each call, so a case can spend its cap plus at most
one call, and a run its budget plus one call. A case whose spend can't be
read stops the run there: it may have spent its cap plus a call, and going on
would let each unread case add another call past the budget. Both stops set
budget_hit and list the cases not run. Arms run one after another, so a stop
starves
the later arms, and the arm it stops in has a partial k: its cases ran
different numbers of times. `register --dry` prints the worst case and
appends nothing. Run from the repo root: the ledger and the fingerprints
read from it.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path, PurePosixPath

from bench import agent_run, consistency, corpus, ledger, prices
from crivo import llm
from crivo.query import provider_problem

EVAL_DIR = Path("bench/results/eval")
TYPES = ("code", "behaviour", "eval", "experiment")
NO_VERDICTS = "no verdicts exist before 0b"
NOT_RUN = "no case of this arm ran"
CHECK_LOCKS = Path(__file__).resolve().parents[1] / "scripts" / "check_locks.py"

# ED1: one provisional suite until 0a's dev split replaces it.
SUITES = {
    "agent-clean-smoke": {
        "splits": {"dev": list(corpus.SMOKE)},
        "files": [
            "bench/corpus.py",
            "bench/bases.py",
            "bench/corrupt.py",
            "bench/truth.py",
        ],
        "false_backed_reason": f"{NO_VERDICTS}: agent-clean-smoke, ED1",
        "limits": [
            f"{NO_VERDICTS}, so false_backed and backed_rate are null",
            "repair F1 drops None, so real misses go uncounted and it reads high (DD2)",
            "the bench runs every GATE and PLAN gate a person would answer (T13)",
            "agent cells can read bench/, where the truth is generated (0a)",
            "the prompts were tuned while looking at SMOKE, so it is not held out",
        ],
    }
}

# The baseline agent-lane arm (step 3): careful autonomy, HUMAN gates
# skipped, the host kernel, the default caps. register writes it, run drives it.
BASELINE = {
    "docker": False,
    "autonomy": "careful",
    "human_gates": "skip",
    "policies": "none",
    "max_events": agent_run.DEFAULT_MAX_EVENTS,
    "wall_cap": agent_run.DEFAULT_WALL_CAP,
}


def _refuse(why: str):
    sys.exit(f"eval: {why}")


def _key_file() -> Path:
    """The main checkout's key file: a worktree has none, so it is the one
    beside the git common dir. Loaded, never printed; the tests' seam."""
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    ).stdout.strip()
    return Path(common).resolve().parent / ".env"


def _restore(saved: dict) -> None:
    """os.environ as `saved` had it: what an arm or the key file set goes."""
    for key in set(os.environ) - set(saved):
        del os.environ[key]
    os.environ.update(saved)


def _use(arm: dict) -> None:
    os.environ["CRIVO_PROVIDER"] = arm["provider"]
    os.environ["CRIVO_MODEL"] = arm["model"]


def _price_problem(entry) -> str | None:
    """Why a bench.prices entry can't price an arm: none, a rate that is not
    a finite amount, or no page or ISO date it was read from."""
    if entry is None:
        return "has no price in bench/prices.py"
    for rate in prices.RATES:
        value = entry.get(rate)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"has a price whose {rate} rate is not an amount"
        if value < 0:
            return f"has a price whose {rate} rate is below 0"
    if not str(entry.get("source") or "").strip():
        return "has a price that names no source page"
    try:
        date.fromisoformat(entry.get("checked"))
    except (TypeError, ValueError):
        return "has a price that names no ISO date it was read"
    return None


def _resolve(arm: dict) -> dict:
    """The arm as its own env resolves it, its price entry copied on (EV9);
    refused when its provider can't run or its model has no price. Leaves the
    arm's env set."""
    _use(arm)
    problem = provider_problem()
    if problem:
        _refuse(
            f"arm {arm['name']} ({arm['provider']}:{arm['model']}): {problem} "
            "(checked env and the main checkout's key file)"
        )
    info = llm.model_info()
    control = {key: info[key] for key in ("effort", "temperature") if key in info}
    entry = prices.PRICES.get(prices.price_key(arm["provider"], info["model"]))
    why = _price_problem(entry)
    if why:
        _refuse(
            f"arm {arm['name']} ({arm['provider']}:{info['model']}) {why}: add the "
            "rates from the provider's own pricing page, with its URL and the "
            "date read"
        )
    return {**arm, "model": info["model"], **control, **BASELINE, "price": dict(entry)}


def _parse_arms(specs: list[str]) -> list[dict]:
    """NAME=PROVIDER:MODEL, split on the first ":" (a model id can hold one)."""
    arms = []
    for spec in specs:
        name, _, rest = spec.partition("=")
        provider, _, model = rest.partition(":")
        if not (name and provider and model):
            _refuse(f"--arm {spec!r} is not NAME=PROVIDER:MODEL")
        arms.append({"name": name, "provider": provider, "model": model})
    names = [arm["name"] for arm in arms]
    if len(set(names)) != len(names):
        _refuse(f"arm names must be unique, got {', '.join(names)}")
    return arms


def _faux_shell(shell: str | None, arms: list[dict]) -> None:
    real = [arm["name"] for arm in arms if arm["provider"] != "faux"]
    if shell == "faux" and real:
        _refuse(f"CRIVO_PROVIDER=faux is set, so arm {', '.join(real)} is refused")


def _find(kind: str, row_id: str) -> dict:
    for row in ledger.rows(kind=kind, path=ledger.LEDGER):
        if row["row_id"] == row_id:
            return row
    _refuse(f"no {kind} row {row_id} in {ledger.LEDGER}")


def _spent(issue: int, owner_ok: bool, hint: str = "Aarmen's yes (--owner-ok)") -> None:
    results = ledger.rows(kind="result", issue=issue, path=ledger.LEDGER)
    if len(results) >= 2 and not owner_ok:
        _refuse(f"#{issue} already has {len(results)} results: a third needs {hint}")


def _usd(value: float) -> str:
    """Dollars to the cent, or to a hundredth of a cent when smaller."""
    whole, _, cents = f"{value:.4f}".rstrip("0").partition(".")
    return f"${whole}.{cents.ljust(2, '0')}"


def _amounts(budget, per_case) -> None:
    """No cost is greater than NaN or infinity, so neither cap would trip;
    True compares as 1 but is no amount. register checks the flags, and run
    the registration again, since a row appended by hand skipped register."""
    for flag, value in (("--budget-usd", budget), ("--per-case-usd", per_case)):
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not number or not math.isfinite(value) or value < 0:
            _refuse(f"{flag} {value!r}: a cap is a finite amount of dollars, 0 or more")
    if per_case > budget:
        _refuse(
            f"--per-case-usd {_usd(per_case)} is above --budget-usd {_usd(budget)}: "
            "no case could start"
        )


def _dry(args: argparse.Namespace, arms: list[dict], cases: int) -> None:
    """ED5: the worst case before any registration exists, and what each arm's
    model cost a case in an earlier result on this suite."""
    worst = cases * args.k * len(arms) * args.per_case_usd
    print(
        f"worst case: {cases} cases x k={args.k} x {len(arms)} arms x "
        f"{_usd(args.per_case_usd)} a case = {_usd(worst)}; the run stops before "
        f"a case that could cross the {_usd(args.budget_usd)} budget",
        "the spend is read after each call, so a case can overshoot its cap by "
        "one call, and the run its budget by one call: a case whose spend can't "
        "be read stops the run, so no unread case adds another",
        sep="\n",
    )
    regs = {r["row_id"]: r for r in ledger.rows(kind="registered", path=ledger.LEDGER)}
    found = ledger.rows(kind="result", suite=args.suite, path=ledger.LEDGER)
    for arm in arms:
        measured = []
        for res in found:
            for reg_arm in regs.get(res.get("registered"), {}).get("arms", []):
                same = (reg_arm.get("provider"), reg_arm.get("model"))
                if same != (arm["provider"], arm["model"]):
                    continue
                cost = (res.get("arms", {}).get(reg_arm.get("name")) or {}).get(
                    "cost_usd"
                )
                if cost:
                    measured.append(
                        f"p50 {_usd(cost['p50'])}, p95 {_usd(cost['p95'])} a case "
                        f"in {res['row_id']}"
                    )
        print(
            f"{arm['name']} ({arm['provider']}:{arm['model']}): "
            + ("; ".join(measured) or f"no earlier priced result on {args.suite}")
        )
    print("dry run: nothing appended to the ledger")


def register(args: argparse.Namespace) -> int:
    shell = os.environ.get("CRIVO_PROVIDER")
    suite = SUITES.get(args.suite)
    if suite is None:
        _refuse(f"no suite {args.suite!r}; the suites are {', '.join(SUITES)}")
    if args.split not in suite["splits"]:
        later = args.split in ("heldout", "sealed")
        why = "no such split until Stage 0a" if later else "no such split"
        _refuse(f"{args.suite} has no {args.split} split: {why}")
    if args.k < 3:
        _refuse(f"k={args.k}: an eval runs every case 3 times or more")
    _amounts(args.budget_usd, args.per_case_usd)
    arms = _parse_arms(args.arm)
    _faux_shell(shell, arms)
    prints = ledger.fingerprints()
    if prints["dirty"]:
        _refuse("the tree is dirty: commit or put back every tracked change first")
    _spent(args.issue, args.owner_ok)
    saved = dict(os.environ)
    try:
        agent_run._load_dotenv(_key_file())
        arms = [_resolve(arm) for arm in arms]
    finally:
        _restore(saved)
    entries = suite["splits"][args.split]
    if args.dry:
        _dry(args, arms, len(entries))
        return 0
    row = ledger.new_row(
        "registered",
        args.issue,
        type=args.type,
        suite=args.suite,
        split=args.split,
        arms=arms,
        k=args.k,
        hypothesis=args.hypothesis,
        primary=args.primary,
        guards=args.guards,
        rule=args.rule,
        budget_usd=args.budget_usd,
        per_case_usd=args.per_case_usd,
        fingerprints=prints,
        suite_hash=ledger.suite_hash(entries, suite["files"]),
        limits=suite["limits"],
        owner_ok=args.owner_ok,
    )
    ledger.append(row, path=ledger.LEDGER)
    named = ", ".join(f"{a['name']}={a['provider']}:{a['model']}" for a in arms)
    print(
        f"registered {row['row_id']}: {args.suite} ({args.split}) k={args.k}, {named}"
    )
    return 0


def _unmoved(reg: dict, suite: dict, entries: list) -> tuple[dict, dict]:
    """Today's fingerprints and suite hash; refused when the code moved since
    registering (B2): a dirty tree, a hash, or any commit outside the ledger."""
    prints = ledger.fingerprints()
    if prints["dirty"]:
        _refuse("the tree is dirty: commit or put back every tracked change first")
    for part in ("prompt", "referee", "scorer"):
        if prints[part] != reg["fingerprints"][part]:
            files = ", ".join(prints[part]["files"])
            _refuse(f"the {part} hash moved since registering ({files})")
    hashed = ledger.suite_hash(entries, suite["files"])
    if hashed != reg["suite_hash"]:
        _refuse(f"the suite hash moved since registering ({', '.join(suite['files'])})")
    commit = reg["fingerprints"]["commit"]
    diff = subprocess.run(
        ["git", "diff", "--quiet", commit, "HEAD", "--", "."]
        + [f":(exclude){ledger.LEDGER.as_posix()}"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if diff.returncode == 1:
        _refuse(f"code outside the ledger was committed since {commit[:12]}")
    if diff.returncode:
        _refuse(f"git diff {commit[:12]} HEAD failed: {diff.stderr.strip()}")
    return prints, hashed


def _status(status) -> str:
    """crivo's own statuses as written; one built from an exception keeps only
    its type, since its text can quote the data and the ledger is committed."""
    status = str(status)
    if status.startswith("error"):
        return "error: " + status.removeprefix("error:").strip().split(":")[0]
    return status


def _outcome(arm: str, run: int, row: dict) -> dict:
    calls = row.get("calls") or {}
    return {
        "case": row["name"],
        "arm": arm,
        "run": run,
        "status": _status(row.get("status")),
        "solved": consistency.solved(row),
        "repair_f1": ((row.get("scores") or {}).get("repair") or {}).get("f1"),
        "calls": calls.get("count"),
        "new_work_tokens": calls.get("new_work_tokens"),
        "cost_usd": row.get("cost_usd"),
        "wall_s": row.get("wall_secs"),
    }


def _metrics(rows: list[dict]) -> dict:
    """Cost and wall time are p50 and p95 over the runs that read them; an
    arm with no runs (the budget stopped before it) gets null with a reason
    for every rate, never consistency's 0.0 over nothing."""
    agg = consistency.aggregate_consistency(consistency.group_by_case(rows))
    walls = [r["wall_secs"] for r in rows if r.get("wall_secs") is not None]
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    metrics = {
        "cases": agg["cases"],
        "pass_k": agg["mean_pass_k"] if rows else None,
        "pass_at_1": agg["mean_pass_at_1"] if rows else None,
        "flaky": agg["flaky"],
        "aborted": sum(str(r.get("status")).startswith("aborted") for r in rows),
        "cost_usd": ledger.quantiles(costs),
        "wall_s": ledger.quantiles(walls),
    }
    if not rows:
        for key in ("pass_k", "pass_at_1", "cost_usd", "wall_s"):
            metrics[f"{key}_reason"] = NOT_RUN
    elif not costs:
        metrics["cost_usd_reason"] = "no run's spend could be read"
    if len(costs) < len(rows):
        metrics["cost_usd_unread"] = len(rows) - len(costs)
    return metrics


def _summary(rows: list[dict], arm: dict, suite: dict) -> dict:
    """Each metric over every case, and again over the model cases: those
    where some run called the model, or whose call count is unknown (B4)."""
    called = {
        r["name"]
        for r in rows
        if (count := (r.get("calls") or {}).get("count")) is None or count > 0
    }
    model = [r for r in rows if r["name"] in called]
    reason = suite["false_backed_reason"]
    summary = {
        **_metrics(rows),
        "false_backed": None,
        "false_backed_reason": reason,
        "backed_rate": None,
        "backed_rate_reason": reason,
        "contained": "docker" if arm["docker"] else "host",
        "model_cases": _metrics(model) if model else None,
    }
    if not model:
        summary["model_cases_reason"] = (
            NOT_RUN
            if not rows
            else (
                "no run called the model; a case solved without it says "
                "nothing about the model"
            )
        )
    return summary


def _noise_floor(
    arms: list[dict], summaries: dict, rows: dict
) -> tuple[dict | None, str]:
    """For arms on one config (A/A): the spread in mean pass@1 over model
    cases and the union of their flaky sets. None when a stop left the pair
    with unequal runs: that spread is the cut, not the noise."""
    groups: dict = {}
    for arm in arms:
        config = sorted((k, str(v)) for k, v in arm.items() if k != "name")
        groups.setdefault(str(config), []).append(arm["name"])
    pair = next((names for names in groups.values() if len(names) > 1), None)
    if pair is None:
        return None, "no two arms share one config, so there is no A/A pair"
    runs = [len(rows[name]) for name in pair]
    if len(set(runs)) > 1:
        counts = ", ".join(f"{n} {r}" for n, r in zip(pair, runs, strict=True))
        return (
            None,
            f"the run stopped early, so the A/A pair ran unequal runs: {counts}",
        )
    model = [summaries[name]["model_cases"] for name in pair]
    if None in model:
        return None, f"an arm of the A/A pair {', '.join(pair)} has no model case"
    rates = [m["pass_at_1"] for m in model]
    flaky = sorted({case for m in model for case in m["flaky"]})
    return {"arms": pair, "pass_at_1_diff": max(rates) - min(rates), "flaky": flaky}, ""


def _spent_text(spend: dict) -> str:
    unread = spend["unread"]
    runs = f"{unread} run{'s' * (unread != 1)}"
    return _usd(spend["spent_usd"]) + (f" known ({runs} unread)" if unread else "")


def _run_arms(reg: dict, entries: list, out: Path, record) -> tuple:
    """Every case k times per arm, arm after arm, each under its own env and
    results dir and the per-case cap. Never resumes: every run calls
    _run_case. Before each case, spent plus the cap is checked against the
    budget; once it could cross, or once a case's spend went unread, that
    case and every later one is not run, so later arms starve and the arm it
    stops in has a partial k. A case can spend its cap plus one call, so the
    run can spend its budget plus one call; an unread case stops the run
    because it may have spent that much too, and going on would let each
    unread case add another call. Each finished case's outcome and the spend
    so far land in <out>/cases.jsonl as they finish, so a case that raises
    loses none of what ran. Returns the rows per arm, the outcomes, the cases
    not run and the spend."""
    rows, cases, not_run = {}, [], []
    cap, budget = reg["per_case_usd"], reg["budget_usd"]
    spend = {"spent_usd": 0.0, "unread": 0}
    for arm in reg["arms"]:
        name = arm["name"]
        _use(arm)
        agent_run.RESULTS_DIR = out / name
        args = argparse.Namespace(
            **BASELINE, policy_records=[], record=record, per_case_usd=cap
        )
        rows[name] = []
        for run in range(1, reg["k"] + 1):
            for entry in entries:
                if not_run or spend["unread"] or spend["spent_usd"] + cap > budget:
                    not_run.append({"arm": name, "case": entry["name"], "run": run})
                    continue
                args.run_tag = f".{name}.r{run}"  # one cassette per arm and run
                try:
                    row = agent_run._run_case(entry, args)
                except Exception as exc:  # noqa: BLE001 — its text can quote data
                    _refuse(
                        f"arm {name}, {entry['name']} run {run} raised "
                        f"{type(exc).__name__}: the run stopped and wrote no result. "
                        f"{_spent_text(spend)} spent before it (its own spend is "
                        f"unread); the {len(cases)} cases run are kept in "
                        f"{out / 'cases.jsonl'}"
                    )
                rows[name].append(row)
                case = _outcome(name, run, row)
                cases.append(case)
                cost = case["cost_usd"]
                if cost is None:
                    spend["unread"] += 1
                else:
                    spend["spent_usd"] += cost
                with open(out / "cases.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"outcome": case, **spend}) + "\n")
                calls = agent_run._tokens_text(case["calls"])
                paid = "cost unknown" if cost is None else _usd(cost)
                print(
                    f"{name} {case['case']} r{run}: {case['status']} | {calls} calls"
                    f" | {paid}"
                )
    return rows, cases, not_run, spend


def _p(node: dict | None, reason: str | None, show) -> str:
    if node is None:
        return f"unknown ({reason or 'none'})"
    return f"p50 {show(node['p50'])}, p95 {show(node['p95'])}"


def _screen(arm: dict, s: dict, served: list, unread: int) -> None:
    named = ", ".join(served)
    if unread:  # an unread run named no model, which is not "none named"
        runs = f"{unread} run{'s' * (unread != 1)}"
        unknown = f"unknown on {runs} (telemetry unread)"
        named = f"{named}; {unknown}" if named else unknown

    def line(label: str, m: dict) -> str:
        if m["pass_k"] is None:
            return f"  {label}: none ({m['pass_k_reason']})"
        return (
            f"  {label}: pass^k {m['pass_k']:.3f} | pass@1 {m['pass_at_1']:.3f}"
            f" | flaky {len(m['flaky'])} | aborted {m['aborted']} | {m['cases']} cases"
        )

    model = s["model_cases"]
    fb = s["false_backed"]
    cost = _p(s["cost_usd"], s.get("cost_usd_reason"), _usd)
    if s.get("cost_usd_unread") and s["cost_usd"] is not None:
        cost += f" ({s['cost_usd_unread']} unread)"
    print(
        f"\n{arm['name']} ({arm['provider']}:{arm['model']})",
        line("all cases", s),
        line("model cases", model)
        if model
        else f"  model cases: none ({s['model_cases_reason']})",
        f"  cost {cost} | wall "
        + _p(s["wall_s"], s.get("wall_s_reason"), lambda x: f"{x:.2f}s"),
        f"  served models: {named or 'none named'}",
        "  false-backed: "
        + (f"{fb['n']}/{fb['N']}" if fb else f"null ({s['false_backed_reason']})"),
        sep="\n",
    )


def run(args: argparse.Namespace) -> int:
    shell = os.environ.get("CRIVO_PROVIDER")
    reg = _find("registered", args.registered)
    suite = SUITES.get(reg["suite"])
    entries = (suite or {}).get("splits", {}).get(reg["split"])
    if entries is None:
        _refuse(f"no suite {reg['suite']} with a {reg['split']} split here")
    _faux_shell(shell, reg["arms"])
    _amounts(reg.get("budget_usd"), reg.get("per_case_usd"))
    results = ledger.rows(kind="result", path=ledger.LEDGER)
    if any(r.get("registered") == reg["row_id"] for r in results):
        _refuse(f"{reg['row_id']} already has a result: register again to rerun")
    _spent(
        reg["issue"],
        reg.get("owner_ok", False),
        "Aarmen's yes: register again with --owner-ok",
    )
    prints, hashed = _unmoved(reg, suite, entries)
    out = (EVAL_DIR / reg["row_id"]).resolve()
    if out.exists():
        _refuse(f"{out} exists: a run never resumes, so register again")

    saved, results_dir = dict(os.environ), agent_run.RESULTS_DIR
    try:
        agent_run._load_dotenv(_key_file())
        for arm in reg["arms"]:
            if _resolve(arm) != arm:
                _refuse(f"arm {arm['name']} no longer resolves as it was registered")
        out.mkdir(parents=True)
        if args.record:
            Path(args.record).mkdir(parents=True, exist_ok=True)
        rows, cases, not_run, spend = _run_arms(reg, entries, out, args.record)
    finally:
        agent_run.RESULTS_DIR = results_dir
        _restore(saved)

    summaries = {a["name"]: _summary(rows[a["name"]], a, suite) for a in reg["arms"]}
    # EV1: the union of what each run's telemetry named. A run whose telemetry
    # was unread (None) named nothing either way, so it is counted, not merged.
    named = {
        n: [(r.get("calls") or {}).get("served_models") for r in rs]
        for n, rs in rows.items()
    }
    served = {
        n: sorted({m for ms in lists if ms for m in ms}) for n, lists in named.items()
    }
    unread = {n: c for n, lists in named.items() if (c := lists.count(None))}
    floor, why = _noise_floor(reg["arms"], summaries, rows)
    result = ledger.new_row(
        "result",
        reg["issue"],
        registered=reg["row_id"],
        fingerprints=prints,
        suite_hash=hashed,
        k=reg["k"],
        served_models=served,
        **({"served_models_unread": unread} if unread else {}),
        cases=cases,
        arms=summaries,
        limits=suite["limits"],
        noise_floor=floor,
        **({} if floor else {"noise_floor_reason": why}),
        # the known spend; a run whose spend was unread is counted, not added
        spent_usd=round(spend["spent_usd"], 6),
        **({"spent_usd_unread": spend["unread"]} if spend["unread"] else {}),
        budget_hit=bool(not_run),
        cases_not_run=not_run,
    )
    ledger.append(result, path=ledger.LEDGER)
    for arm in reg["arms"]:
        name = arm["name"]
        _screen(arm, summaries[name], served[name], unread.get(name, 0))
    if floor:
        print(
            f"\nnoise floor ({', '.join(floor['arms'])}): pass@1 differs by "
            f"{floor['pass_at_1_diff']:.3f} over model cases; flaky "
            f"{', '.join(floor['flaky']) or 'none'}"
        )
    else:
        print(f"\nnoise floor: none ({why})")
    print(f"spent {_spent_text(spend)} of the {_usd(reg['budget_usd'])} budget")
    if not_run:
        cap = _usd(reg["per_case_usd"])
        since = (
            "a case's spend was unread, so it may have spent its cap plus a call"
            if spend["unread"]
            else f"spent plus the {cap} per-case cap could cross the budget"
        )
        print(f"budget hit: {len(not_run)} cases not run, since {since}")
    print(f"result {result['row_id']} appended to {ledger.LEDGER}")
    return 0


def _exempt() -> tuple:
    """check_locks.EXEMPT, the registration types lock 3 never checks, read
    from the script's own assignment (parsed, never run) so the two can't
    drift."""
    for node in ast.parse(CHECK_LOCKS.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "EXEMPT"
            for target in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    _refuse(f"{CHECK_LOCKS} assigns no EXEMPT")


def _at_head(files, tmp: str) -> str | None:
    """Each file as HEAD commits it, written under `tmp` for ledger._hash;
    why one can't be, or why its working-tree copy differs from HEAD's
    (committing the decision with it would move the hash)."""
    if not isinstance(files, list) or not files:
        return "the result names no files"
    for rel in files:
        pure = PurePosixPath(rel) if isinstance(rel, str) else None
        if pure is None or not pure.parts or pure.is_absolute() or ".." in pure.parts:
            return f"{rel!r} is outside the repo"
        blob = subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:{pure.as_posix()}"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if blob.returncode:
            return f"{rel} is not committed at HEAD"
        try:
            tree = Path(rel).read_bytes()
        except OSError:
            tree = None
        if tree != blob.stdout:
            return f"{rel} in the working tree differs from HEAD"
        target = Path(tmp, *pure.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob.stdout)
    return None


def _true_to_code(result: dict) -> None:
    """check_locks' lock 3 holds an adopted decision on a behaviour (or
    untyped) registration to the prompt, referee and scorer files committed
    with the decision line, and the ledger is append-only, so a decision that
    breaks it would leave dev red for good. So each part is hashed as HEAD
    commits it, and refused when that hash differs from the result's or the
    working tree differs from HEAD."""
    reg = next(
        (
            r
            for r in ledger.rows(kind="registered", path=ledger.LEDGER)
            if r["row_id"] == result.get("registered")
        ),
        {},
    )
    if reg.get("type") in _exempt():
        return
    for part in ("prompt", "referee", "scorer"):
        node = (result.get("fingerprints") or {}).get(part) or {}
        files = node.get("files")
        with tempfile.TemporaryDirectory() as tmp:
            why = _at_head(files, tmp)
            if why is None and ledger._hash(tmp, files)["sha256"] != node.get("sha256"):
                why = "the files committed at HEAD hash differently"
        if why:
            _refuse(
                f"the {part} hash moved since {result['row_id']}: {why}. Adopting "
                f"it on a {reg.get('type') or 'untyped'} registration would break "
                "check_locks' lock 3; drop it, or register and run again"
            )


def decide(args: argparse.Namespace) -> int:
    """B5: adopted and dropped name a result and take its issue;
    shipped-unmeasured names no result, only its issue (ED6). Adopted is
    refused when the code it was measured on moved (lock 3)."""
    if args.decision == "shipped-unmeasured":
        if args.result or args.issue is None:
            _refuse("--shipped-unmeasured takes --issue N and no --result (ED6)")
        issue = args.issue
    else:
        if not args.result or args.issue is not None:
            _refuse(f"--{args.decision} takes --result ROW, and its issue from it")
        result = _find("result", args.result)
        if args.decision == "adopted":
            _true_to_code(result)
        issue = result["issue"]
    row = ledger.new_row(
        "decision", issue, result=args.result, decision=args.decision, note=args.note
    )
    ledger.append(row, path=ledger.LEDGER)
    print(f"decision {row['row_id']}: {args.decision} on #{issue}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-registered evals (EV8)")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="write the eval down before it runs")
    reg.add_argument("--issue", type=int, required=True)
    reg.add_argument("--type", choices=TYPES, required=True, help="the work type")
    reg.add_argument("--suite", required=True)
    reg.add_argument("--split", required=True)
    reg.add_argument(
        "--arm", action="append", required=True, metavar="NAME=PROVIDER:MODEL"
    )
    reg.add_argument("--k", type=int, required=True, help="runs per case, 3 or more")
    reg.add_argument("--budget-usd", type=float, required=True)
    reg.add_argument("--per-case-usd", type=float, required=True)
    for flag in ("--hypothesis", "--primary", "--rule"):
        reg.add_argument(flag, required=True)
    reg.add_argument("--guards", action="append", required=True)
    reg.add_argument("--owner-ok", action="store_true", help="Aarmen's yes to a third")
    reg.add_argument(
        "--dry", action="store_true", help="print the worst case, append nothing"
    )
    ran = sub.add_parser("run", help="run a registration and append its result")
    ran.add_argument("--registered", required=True, metavar="ROW")
    ran.add_argument("--record", metavar="DIR", help="one cassette per run (EV2)")
    dec = sub.add_parser("decide", help="append Aarmen's call on a result")
    dec.add_argument("--result", metavar="ROW")
    which = dec.add_mutually_exclusive_group(required=True)
    for choice in ledger.DECISIONS:
        which.add_argument(
            f"--{choice}", dest="decision", action="store_const", const=choice
        )
    dec.add_argument("--issue", type=int)
    dec.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    return {"register": register, "run": run, "decide": decide}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
