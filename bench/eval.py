"""Pre-registered evals of the agent lane (spec: specs/2026-10-17-eval-tooling.md
EV8, #71).

`register` writes the arms, k, hypothesis and rule before any case runs;
`run --registered ROW` runs the suite's cases k times per arm through
bench.agent_run and appends the result; `decide` appends the adopt, drop or
shipped-unmeasured call Aarmen made. Every row goes through bench.ledger.

    python -m bench.eval register --issue N --type behaviour \\
        --suite agent-clean-smoke --split dev --arm a1=faux:m --k 3 \\
        --budget-usd 0 --per-case-usd 0 --hypothesis T --primary pass_at_1 \\
        --guards aborted --rule T
    python -m bench.eval run --registered ROW [--record DIR]
    python -m bench.eval decide --result ROW (--adopted | --dropped) --note T
    python -m bench.eval decide --shipped-unmeasured --issue N --note T

Until EV9 (#72) brings prices and caps, `run` refuses any arm that is not
faux. Run from the repo root: the ledger and the fingerprints read from it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from bench import agent_run, consistency, corpus, ledger
from crivo import llm
from crivo.query import provider_problem

EVAL_DIR = Path("bench/results/eval")
TYPES = ("code", "behaviour", "eval", "experiment")
NO_VERDICTS = "no verdicts exist before 0b"
NO_PRICES = "no prices until EV9 (#72)"
EV9_REFUSAL = "no prices or caps until EV9 (#72)"

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


def _resolve(arm: dict) -> dict:
    """The arm as its own env resolves it, refused when its provider can't
    run; leaves the arm's env set."""
    _use(arm)
    problem = provider_problem()
    if problem:
        _refuse(
            f"arm {arm['name']} ({arm['provider']}:{arm['model']}): {problem} "
            "(checked env and the main checkout's key file)"
        )
    info = llm.model_info()
    control = {key: info[key] for key in ("effort", "temperature") if key in info}
    return {**arm, "model": info["model"], **control, **BASELINE}


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
        "cost_usd": None,
        "wall_s": row.get("wall_secs"),
    }


def _metrics(rows: list[dict]) -> dict:
    agg = consistency.aggregate_consistency(consistency.group_by_case(rows))
    walls = [r["wall_secs"] for r in rows if r.get("wall_secs") is not None]
    return {
        "cases": agg["cases"],
        "pass_k": agg["mean_pass_k"],
        "pass_at_1": agg["mean_pass_at_1"],
        "flaky": agg["flaky"],
        "aborted": sum(str(r.get("status")).startswith("aborted") for r in rows),
        "cost_usd": None,
        "cost_usd_reason": NO_PRICES,
        "wall_s": ledger.quantiles(walls),
    }


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
            "no run called the model; a case solved without it says "
            "nothing about the model"
        )
    return summary


def _noise_floor(arms: list[dict], summaries: dict) -> tuple[dict | None, str]:
    """For arms on one config (A/A): the spread in mean pass@1 over model
    cases and the union of their flaky sets."""
    groups: dict = {}
    for arm in arms:
        config = sorted((k, str(v)) for k, v in arm.items() if k != "name")
        groups.setdefault(str(config), []).append(arm["name"])
    pair = next((names for names in groups.values() if len(names) > 1), None)
    if pair is None:
        return None, "no two arms share one config, so there is no A/A pair"
    model = [summaries[name]["model_cases"] for name in pair]
    if None in model:
        return None, f"an arm of the A/A pair {', '.join(pair)} has no model case"
    rates = [m["pass_at_1"] for m in model]
    flaky = sorted({case for m in model for case in m["flaky"]})
    return {"arms": pair, "pass_at_1_diff": max(rates) - min(rates), "flaky": flaky}, ""


def _run_arms(reg: dict, entries: list, out: Path, record) -> tuple[dict, list]:
    """Every case k times per arm, arm after arm, each under its own env and
    results dir. Never resumes: every run calls _run_case."""
    rows, cases = {}, []
    for arm in reg["arms"]:
        name = arm["name"]
        _use(arm)
        agent_run.RESULTS_DIR = out / name
        args = argparse.Namespace(**BASELINE, policy_records=[], record=record)
        rows[name] = []
        for run in range(1, reg["k"] + 1):
            for entry in entries:
                args.run_tag = f".{name}.r{run}"  # one cassette per arm and run
                try:
                    row = agent_run._run_case(entry, args)
                except Exception as exc:  # noqa: BLE001 — its text can quote data
                    _refuse(
                        f"arm {name}, {entry['name']} run {run} raised "
                        f"{type(exc).__name__}: the run stopped and wrote no result"
                    )
                rows[name].append(row)
                case = _outcome(name, run, row)
                cases.append(case)
                calls = agent_run._tokens_text(case["calls"])
                print(f"{name} {case['case']} r{run}: {case['status']} | {calls} calls")
    return rows, cases


def _p(node: dict | None, reason: str = "none", unit: str = "") -> str:
    if node is None:
        return f"unknown ({reason})"
    return f"p50 {node['p50']:.2f}{unit}, p95 {node['p95']:.2f}{unit}"


def _screen(arm: dict, s: dict, served: list, unread: int) -> None:
    named = ", ".join(served)
    if unread:  # an unread run named no model, which is not "none named"
        runs = f"{unread} run{'s' * (unread != 1)}"
        unknown = f"unknown on {runs} (telemetry unread)"
        named = f"{named}; {unknown}" if named else unknown

    def line(label: str, m: dict) -> str:
        return (
            f"  {label}: pass^k {m['pass_k']:.3f} | pass@1 {m['pass_at_1']:.3f}"
            f" | flaky {len(m['flaky'])} | aborted {m['aborted']} | {m['cases']} cases"
        )

    model = s["model_cases"]
    fb = s["false_backed"]
    print(
        f"\n{arm['name']} ({arm['provider']}:{arm['model']})",
        line("all cases", s),
        line("model cases", model)
        if model
        else f"  model cases: none ({s['model_cases_reason']})",
        f"  cost {_p(s['cost_usd'], s.get('cost_usd_reason'))}"
        f" | wall {_p(s['wall_s'], unit='s')}",
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
    real = [arm["name"] for arm in reg["arms"] if arm["provider"] != "faux"]
    if real:
        _refuse(f"arm {', '.join(real)} is not faux: {EV9_REFUSAL}")
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
        rows, cases = _run_arms(reg, entries, out, args.record)
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
    floor, why = _noise_floor(reg["arms"], summaries)
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
        spent_usd=0.0,
        budget_hit=False,
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
    print(f"result {result['row_id']} appended to {ledger.LEDGER}")
    return 0


def decide(args: argparse.Namespace) -> int:
    """B5: adopted and dropped name a result and take its issue;
    shipped-unmeasured names no result, only its issue (ED6)."""
    if args.decision == "shipped-unmeasured":
        if args.result or args.issue is None:
            _refuse("--shipped-unmeasured takes --issue N and no --result (ED6)")
        issue = args.issue
    else:
        if not args.result or args.issue is not None:
            _refuse(f"--{args.decision} takes --result ROW, and its issue from it")
        issue = _find("result", args.result)["issue"]
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
