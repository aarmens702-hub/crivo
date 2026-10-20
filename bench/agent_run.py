"""Agent-mode bench lane (spec: specs/2026-09-03-agent-bench-design.md).

Drives the real `Session.clean` loop headlessly over the same corpus as the
deterministic bench, then scores the cleaned frame with the same
`score_end_to_end`. Plain gates are auto-approved; HUMAN gates (a proposed
skill's test and its admission, judgement calls) are skipped, never
fake-approved. Sampled runs print to the terminal only; storefront numbers
come from a full, blessed run (R6).

`uv run python -m bench.agent_run --sample 2`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bench import corpus, prices
from bench.score import score_end_to_end
from bench.truth import frame_sha256
from crivo import llm
from crivo.autoclean import FIXERS
from crivo.policy import PolicyRecord
from crivo.query import provider_problem

RESULTS_DIR = Path("bench/results/agent")

# The cap defaults, named once: `main` gives them to the parser and
# `_arm_suffix` compares against them to decide whether an arm is the default
# one. Two copies of a default is how an arm silently stops being named.
DEFAULT_MAX_EVENTS = 8000
DEFAULT_WALL_CAP = 300.0

# The env flags that change the clean flow (crivo/loop.py). A cassette's arm
# keeps each as set when the case started (None when unset), so a replay can
# set them back.
LOOP_FLAGS = ("CRIVO_M1", "CRIVO_PLAN_FIRST")


class CaseAborted(Exception):
    """A cap fired; the case is recorded and the run moves on (R4).

    `events` is the count `_drive` had reached when the cap fired: every
    event the flow yielded, the one that tripped the cap included (it was
    counted, never answered). None when the raiser gave no count: 0 would
    claim no event ran. A cassette records it; the row does not."""

    def __init__(self, message: str, events: int | None = None):
        super().__init__(message)
        self.events = events


def _load_dotenv(path: Path = Path(".env")) -> None:
    """The project's own .env, no dependency: KEY=VALUE lines, no expansion."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def _require_key() -> None:
    """R7: the configured provider's own needs, the check the CLI shares."""
    problem = provider_problem()
    if problem:
        sys.exit(f"agent bench: {problem} (checked env and .env)")


def _drive(
    gen,
    max_events: int,
    wall_cap: float,
    t0: float,
    gates: list | None = None,
    human_gates: str = "skip",
    over_cap=None,
) -> int:
    """repl._drive, headless: run plain gates, swallow the rendering.

    HUMAN gates default to skip — a person's authorisation is not the bench's
    to give. `human_gates="approve"` applies the owner's standing
    pre-authorisation to judgement-call fixes (the ceiling arm), but the
    skill gates are governance and stay skipped in every mode: a proposed
    skill's test (title "test skill …", #85), so its code never runs, and its
    admission (title "admit skill …").

    `over_cap()`, when given, is asked on each event after the event and wall
    caps: a reason (the per-case dollar cap's, EV9) aborts the case with it."""
    from crivo.events import GateDecision, GateRequest

    events = 0
    try:
        event = next(gen)
        while True:
            events += 1
            if events > max_events:
                gen.close()
                raise CaseAborted(f"event cap {max_events} hit", events)
            if time.monotonic() - t0 > wall_cap:
                gen.close()
                raise CaseAborted(f"wall cap {wall_cap:.0f}s hit", events)
            over = over_cap() if over_cap is not None else None
            if over:
                gen.close()
                raise CaseAborted(over, events)
            answer = None
            if isinstance(event, GateRequest):
                approved = human_gates == "approve" and not event.title.startswith(
                    ("test skill ", "admit skill ")
                )
                action = "run" if event.grade != "HUMAN" or approved else "skip"
                answer = GateDecision(action)
                if gates is not None:
                    gates.append(action)
            event = gen.send(answer)
    except StopIteration:
        return events


def _handoff(dirty: pd.DataFrame, target: Path) -> str:
    """Dtype-exact parquet (R2); CSV only when arrow refuses, and recorded."""
    try:
        dirty.to_parquet(target.with_suffix(".parquet"))
        return "parquet"
    except Exception:  # noqa: BLE001 — whatever arrow refuses, CSV must carry
        dirty.to_csv(target.with_suffix(".csv"), index=False)
        return "csv"


_TOKEN_ATTRS = (
    ("input_tokens", "gen_ai.usage.input_tokens"),
    ("output_tokens", "gen_ai.usage.output_tokens"),
    ("cache_hit_tokens", "crivo.cache.hit_tokens"),
    ("cache_miss_tokens", "crivo.cache.miss_tokens"),
)
# the terms new_work_tokens ADDS, and a call has to report ALL of them to be
# priced. One of them is not half a reading: the missing term contributes a
# silent 0. Cache counters alone say nothing either, since they cannot report
# what new work a call did and subtracting a hit count from nothing would
# publish a negative token count.
_NEW_WORK_ATTRS = ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens")


def _call_stats(path: Path) -> dict:
    """Sum a case's gen_ai.client.call spans into the T1.5 columns: calls,
    model wait, token usage, and new_work_tokens (input minus cache hits
    plus output, the cost basis that excludes cache reads). A missing file,
    junk line, or absent field degrades to None/absent keys, never raises:
    telemetry must not be able to fail a case.

    new_work_tokens separates three states rather than two, because 0 and
    None each mean something and the wrong one flatters a cost column:
      - no readable telemetry -> None. We do not know whether a call was made.
        `count` and `model_wait_s` are None for that same case and for that
        same reason: they used to read 0 here, which is not ignorance but the
        positive claim that no call was made and no time was spent, published
        beside an unknown cost that said the opposite.
      - readable, no call span -> 0. The deterministic path solved the case;
        no call was made, so nothing was spent. Calling this unknown drops
        real, free cases out of the mean and leaves it several times high.
      - a call span that did not report BOTH terms the sum adds -> None for
        the whole case. Reporting one of them is not half a reading: the sum
        would silently contribute 0 for the other and publish a total that is
        knowably short as if it were complete. The span is emitted from
        telemetry.span's `finally` while llm.generate maps usage only after
        the stream finishes, so a cancelled or failed call leaves one behind.

    served_models is the sorted, distinct gen_ai.response.model ids the
    provider said answered the case's calls (EV1), with the same honesty:
    None when no telemetry was readable, [] when spans were read and none
    named a model.
    """
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return {
            "count": None,
            "model_wait_s": None,
            "new_work_tokens": None,
            "served_models": None,
        }
    count = 0
    unpriced = 0
    wait = 0.0
    sums: dict = {}
    served: set = set()
    for line in lines:
        try:
            span = json.loads(line)
        except ValueError:
            continue
        if not isinstance(span, dict) or span.get("name") != "gen_ai.client.call":
            continue
        count += 1
        dur = span.get("dur_s")
        if isinstance(dur, (int, float)):
            wait += dur
        attrs = span.get("attrs") or {}
        model = attrs.get("gen_ai.response.model")
        if isinstance(model, str) and model:
            served.add(model)
        if not all(isinstance(attrs.get(a), (int, float)) for a in _NEW_WORK_ATTRS):
            unpriced += 1
        for key, attr in _TOKEN_ATTRS:
            value = attrs.get(attr)
            if isinstance(value, (int, float)):
                sums[key] = sums.get(key, 0) + value
    stats = {"count": count, "model_wait_s": round(wait, 2), **sums}
    stats["served_models"] = sorted(served)
    if unpriced:
        stats["new_work_tokens"] = None  # a call of unknown cost is in there
    else:
        stats["new_work_tokens"] = (
            sums.get("input_tokens", 0)
            - sums.get("cache_hit_tokens", 0)
            + sums.get("output_tokens", 0)
        )
    return stats


def _arm_gates(args: argparse.Namespace) -> str:
    """The gate policy this arm actually drives with.

    An autonomy arm is always driven with HUMAN gates skipped. `approve` runs
    every non-admission HUMAN gate, which is a person's authorisation to give,
    and an autonomy arm's reach is meant to come from the Session's seeded
    AUTO policy alone. `main` refuses the combination at the parser and says
    so; this is the same rule at the point of use, because `_arm_suffix` and
    `_run_case` are called with hand-built namespaces that never pass through
    that parser. Reads knobs defensively for the same reason.
    """
    gates = getattr(args, "human_gates", "skip")
    if gates == "approve" and getattr(args, "autonomy", None):
        return "skip"
    return gates


def _cap_text(value) -> str:
    """A cap rendered so two different caps can never render alike: every
    digit, no exponent, and a whole number written as one. "%g" was the
    collision - it switches to exponential and rounds past six significant
    figures, so 1000000 and 1000001 shared a filename."""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return format(float(value), "f").rstrip("0").rstrip(".")


def _arm_suffix(args: argparse.Namespace) -> str:
    """The filename tag naming this arm, for both the result and the telemetry
    file. Every knob that changes what an arm measures has to appear here: the
    result name is also the resume key (`main` reuses a case whose file exists,
    R5), so an arm missing from the name reads the other arm's row and reports
    its numbers as its own. The default arm keeps the empty suffix and the
    ceiling arm keeps `.ceiling`, so the results already on disk stay
    addressable. Reads knobs defensively, since callers build the namespace by
    hand. Names the gate policy that will actually be driven, not the one that
    was asked for, so the filename never claims a ceiling arm the run refused
    to be.

    `--docker` and the two caps are in here because they change what an arm
    measures as surely as the gate policy does: the sandbox moves the run off
    the host kernel, and a cap decides how much of a case gets to finish. They
    were left out, so a sandboxed run resumed the host-kernel run's file and
    republished its row as its own. A knob at its default adds nothing to the
    name, which is what keeps the results already on disk addressable.

    A cap is rendered digit for digit (`_cap_text`) rather than with "%g",
    which goes exponential and rounds past six significant figures: 1000000
    and 1000001 both came out ".max-events-1e+06", so two arms shared one file
    and the second resumed the first - the very collision this suffix exists
    to prevent, reintroduced by the fix for it.

    What is still NOT in here, said rather than implied: the model PROVIDER. A
    DeepSeek run and a Claude run of the same case share a name, so one can
    resume the other's row, and _call_stats' own note says the provider decides
    whether the cost column exists at all. Adding it would orphan every results
    file already on disk, so it is a migration rather than a rename and it is
    left open deliberately."""
    parts = []
    if _arm_gates(args) == "approve":
        parts.append("ceiling")
    policies = getattr(args, "policies", "none")
    if policies and policies != "none":
        parts.append(f"policies-{policies}")
    autonomy = getattr(args, "autonomy", None)
    if autonomy:
        parts.append(autonomy)
    if getattr(args, "docker", False):
        parts.append("docker")
    wall_cap = getattr(args, "wall_cap", DEFAULT_WALL_CAP)
    if wall_cap != DEFAULT_WALL_CAP:
        parts.append(f"wall-cap-{_cap_text(wall_cap)}")
    max_events = getattr(args, "max_events", DEFAULT_MAX_EVENTS)
    if max_events != DEFAULT_MAX_EVENTS:
        parts.append(f"max-events-{_cap_text(max_events)}")
    return "".join(f".{part}" for part in parts)


# --- recording a run (EV2) --------------------------------------------------
# A cassette keeps what a replay needs. The messages (they carry the dataset
# profile) and kernel output (it carries data values) are kept as digests
# only. Three things are kept as text and can quote values the model saw:
# the model's raw replies, outcome.status and calls[].error.message. So a
# cassette is not clean by construction: the scan in #66 is the gate that
# refuses one holding rows.


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _call_model(model: str | None) -> tuple:
    """The model and params a call goes out with. A misconfigured provider
    makes model_name() raise; that error is generate's to raise, from the
    same place as without a recorder, so here it reads as unknown."""
    try:
        params = llm.model_info()
        name = model or llm.model_name()
    except Exception:  # noqa: BLE001 — the recorder must not raise first
        return model, None
    if params.get("provider") == "claude":
        params = {**params, "max_tokens": llm.CLAUDE_MAX_TOKENS}
    return name, params


def _recording_generate(orig, calls: list):
    """`orig` (llm.generate) with a recorder in front. Every chunk reaches the
    caller unchanged, heartbeats too; the call's record is appended when it
    starts, so a call that never finishes is still in `calls`. The loop
    drains a stream to its end, so `reply` is the whole raw text, past any
    `</execute>` cut. A stream closed mid-reply (a cap's `gen.close()`) is
    incomplete, not an error: GeneratorExit is not an Exception. `chunks`
    keeps each chunk's length in characters, and each run of k empty
    heartbeat chunks as one -k, so a replay can send the chunks the model
    sent; its positive ints sum to len(reply). Lengths only, never text."""

    def generate(messages, model=None):
        messages = list(messages)  # listed once, and this same list passed on
        name, params = _call_model(model)
        system = "\n".join(
            str(m.get("content", "")) for m in messages if m.get("role") == "system"
        )
        call = {
            "i": len(calls),
            "messages_sha256": _sha256(
                json.dumps(messages, sort_keys=True, ensure_ascii=False, default=str)
            ),
            "system_sha256": _sha256(system),
            "n_messages": len(messages),
            "model": name,
            "params": params,
            "reply": "",
            "chunks": [],
            "complete": False,
            "error": None,
            "dur_s": None,
        }
        calls.append(call)
        parts: list = []
        beats = 0  # the open run of heartbeats, written out as one -k
        t0 = time.monotonic()
        try:
            stream = orig(messages) if model is None else orig(messages, model)
            for chunk in stream:
                if chunk:
                    if beats:
                        call["chunks"].append(-beats)
                        beats = 0
                    parts.append(chunk)
                    call["chunks"].append(len(chunk))
                else:
                    beats += 1
                yield chunk
            call["complete"] = True
        except Exception as exc:
            call["error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            if beats:  # a cap can close the call mid-think
                call["chunks"].append(-beats)
            call["reply"] = "".join(parts)
            call["dur_s"] = round(time.monotonic() - t0, 3)

    return generate


# --- the per-case dollar cap (EV9) -------------------------------------------
OVER_CAP = "per-case budget"
SPEND_UNREAD = "per-case budget (spend unread)"
# One fixed text for every refused call: it quotes nothing the case saw.
SPEND_REFUSED = "the case spent its per-case budget: this call was not sent"


class SpendRefused(RuntimeError):
    """A call the per-case cap refused before it reached the provider."""


def _case_cost(path: Path, key: str, sent_bytes: list) -> dict | None:
    """What the case's gen_ai.client.call spans cost at bench.prices'
    PRICES[key], in two parts: `measured`, the spans that can be priced, and
    `bounded`, what the unread calls are charged at prices.call_bound_usd
    (#239), with `bounded_calls` counting them. A call is unread when its
    span can't be priced (no usage: a call that died mid-stream) or wrote
    none (fewer spans than calls). `sent_bytes` holds one byte count per call
    the guard sent; which call left which span is unknown, so the unread
    ones are bounded by the largest. None when the spend can't be read or
    bounded: a model with no price, more unread spans than calls, or an entry
    that names no max_output_tokens. An all-zero price (faux) costs 0.0
    whatever the spans say."""
    if key not in prices.PRICES:
        return None
    if prices.cost_usd({}, key) == 0.0:  # only an all-zero price prices {}
        return {"measured": 0.0, "bounded": 0.0, "bounded_calls": 0}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = []
    costs = []
    for line in lines:
        try:
            span = json.loads(line)
        except ValueError:
            continue
        if isinstance(span, dict) and span.get("name") == "gen_ai.client.call":
            costs.append(prices.cost_usd(span.get("attrs"), key))
    priced = [cost for cost in costs if cost is not None]
    calls = len(sent_bytes)
    unread = len(costs) - len(priced) + max(0, calls - len(costs))
    if unread > calls:
        return None
    largest = sorted(sent_bytes, reverse=True)[:unread]
    bounds = [prices.call_bound_usd(sent, key) for sent in largest]
    if None in bounds:
        return None
    return {"measured": sum(priced), "bounded": sum(bounds), "bounded_calls": unread}


def _spend_guard(orig, path: Path, key: str, cap: float, spend: dict):
    """`orig` (llm.generate) behind the per-case cap. Before each call it
    keeps the UTF-8 byte count of the messages as json.dumps writes them, the
    recorder's serialization (`spend["sent_bytes"]`: the int only, never the
    text). After it, it re-reads the case's telemetry (a span is written when
    a call ends) and prices it (_case_cost): once the case's measured plus
    bounded spend is more than `cap`, or its spend can't be read or bounded,
    `spend["tripped"]` names why and every later call raises SpendRefused
    before it is sent. The loop turns a raise from generate into an
    llm_error notice and goes on, so the guard refuses each call, not just
    the next. The call that crosses the cap has already gone out, so a case
    can spend its cap plus at most one call: bounding a call before it is
    sent would need a max_tokens on every provider, and llm.py (core) sends
    none to DeepSeek. A call that raises leaves a span with no usage: it is
    charged its bound where the price names max_output_tokens, and otherwise
    reads as unread and stops the case: fail closed."""

    def generate(messages, model=None):
        if spend["tripped"]:
            raise SpendRefused(SPEND_REFUSED)
        messages = list(messages)  # listed once, and this same list passed on
        sent = json.dumps(messages, ensure_ascii=False, default=str)
        spend["sent_bytes"].append(len(sent.encode("utf-8")))
        try:
            yield from (orig(messages) if model is None else orig(messages, model))
        finally:
            cost = _case_cost(path, key, spend["sent_bytes"])
            if cost is None:
                spend["tripped"] = SPEND_UNREAD
            elif cost["measured"] + cost["bounded"] > cap:
                spend["tripped"] = OVER_CAP

    return generate


def _recording_execute(orig, execs: list):
    """`orig` (a client's bound execute) with a recorder in front: per cell,
    digests of the code, the value and the cell's text, plus the status, the
    exception class and the exec count. Never the text itself. The cell's
    text is what Session._exec_events hands the model: the StreamOut text
    with every display folded in as `[display] <payload>`, in order, except a
    saved (not dropped) image/png, whose payload is a tmp path that differs
    on every run."""
    from crivo.kernel.client import DisplayItem, ExecResult, StreamOut

    def execute(code, *args, **kwargs):
        cell = {
            "code_sha256": _sha256(code),
            "status": None,
            "ename": None,
            "value_sha256": None,
            "stream_sha256": None,
            "exec_count": None,
        }
        execs.append(cell)
        stream: list = []
        try:
            for ev in orig(code, *args, **kwargs):
                if isinstance(ev, StreamOut):
                    stream.append(ev.text)
                elif isinstance(ev, DisplayItem):
                    if ev.mime != "image/png" or ev.dropped:
                        stream.append(f"[display] {ev.payload}")
                elif isinstance(ev, ExecResult):
                    cell["status"] = ev.status
                    cell["exec_count"] = ev.exec_count
                    if ev.value is not None:
                        cell["value_sha256"] = _sha256(ev.value)
                    if ev.status == "error":
                        cell["ename"] = (ev.error or {}).get("ename")
                yield ev
        finally:
            cell["stream_sha256"] = _sha256("".join(stream))

    return execute


def _fix_records(session_dir) -> list | None:
    """(disease, columns, grade, status, attempts) per fix in the newest
    clean report, never the finding's evidence (it quotes sample values).
    None when no report was written or it cannot be read."""
    reports = list((Path(session_dir) / "clean_reports").glob("r*.json"))
    if not reports:
        return None
    try:
        report = json.loads(max(reports).read_text())
    except (OSError, ValueError):
        return None
    records = []
    for fix in report.get("fixes") or []:
        finding = fix.get("finding") or {}
        records.append(
            [
                finding.get("disease"),
                finding.get("columns"),
                finding.get("grade"),
                fix.get("status"),
                fix.get("attempts"),
            ]
        )
    return records


def _crivo_stamp(record_dir: Path) -> dict:
    """Which crivo recorded: the commit, whether the tree had changes, and a
    digest of the prompts the model was given. Without git, commit and dirty
    are None. The record dir is left out of the dirty check, so a cassette
    written earlier in the run never marks the next one dirty; a new
    untracked source file still does."""
    from crivo import prompts

    root = Path(__file__).resolve().parent.parent

    def git(*cmd: str) -> str:
        return subprocess.run(
            ["git", *cmd], cwd=root, capture_output=True, text=True, check=True
        ).stdout

    try:
        commit = git("rev-parse", "HEAD").strip()
        top = Path(git("rev-parse", "--show-toplevel").strip()).resolve()
        spec = [":/"]
        try:
            inside = Path(record_dir).resolve().relative_to(top)
        except ValueError:
            inside = None  # outside the checkout, so git status never lists it
        if inside is not None and inside.parts:
            spec.append(f":(top,exclude){inside.as_posix()}")
        dirty = bool(git("status", "--porcelain", "--", *spec).strip())
    except (OSError, subprocess.SubprocessError):
        commit = dirty = None
    prompts_sha = hashlib.sha256(Path(prompts.__file__).read_bytes()).hexdigest()
    return {"commit": commit, "dirty": dirty, "prompts_sha256": prompts_sha}


def _write_cassette(path: Path, entry: dict, dirty, arm: dict, calls, execs, outcome):
    cassette = {
        "schema_version": 1,
        "source": {
            "kind": "corpus",
            "entry": entry,
            "dirty_sha256": frame_sha256(dirty),
        },
        "arm": arm,
        "crivo": _crivo_stamp(path.parent),
        "calls": calls,
        "execs": execs,
        "outcome": outcome,
    }
    path.write_text(json.dumps(cassette, indent=2, default=str))


def _run_case(entry: dict, args: argparse.Namespace) -> dict:
    from crivo.loop import Session

    name = entry["name"]
    pristine, dirty, truth = corpus.build(entry)
    work = RESULTS_DIR / "work" / name
    if work.exists():
        shutil.rmtree(work)
    (work / "data").mkdir(parents=True)
    fmt = _handoff(dirty, work / "data" / name)
    dirty_path = next((work / "data").glob(f"{name}.*"))

    # An unset --autonomy is the baseline arm: pin "careful" rather than
    # inherit the Session's autonomous default, so the empty-suffix results
    # keep meaning what the ones already on disk say (every AUTO finding
    # gated). The arms are opted into, never fallen into.
    autonomy = getattr(args, "autonomy", None) or "careful"
    human_gates = _arm_gates(args)
    row: dict = {
        "name": name,
        "diseases": entry["diseases"],
        "date": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "handoff": fmt,
        "human_gates": human_gates,
        "policies": getattr(args, "policies", "none"),
        "autonomy": autonomy,
        "model": llm.model_info(),
        "status": "ok",
    }
    t0 = time.monotonic()
    gates: list = []
    # T1.5: per-case telemetry file, per arm; the generate() calls run in
    # this host process and read CRIVO_TELEMETRY per call (crivo/telemetry.py)
    suffix = _arm_suffix(args)
    tele_path = RESULTS_DIR / "telemetry" / f"{name}{suffix}.jsonl"
    tele_path.parent.mkdir(parents=True, exist_ok=True)
    tele_path.unlink(missing_ok=True)  # stale spans must not count in this run
    prev_tele = os.environ.get("CRIVO_TELEMETRY")
    os.environ["CRIVO_TELEMETRY"] = str(tele_path)
    # EV2: with --record, every model call and every cell of this case is
    # recorded. EV9: with a per-case cap, every call goes through the spend
    # guard, inside the recorder so a refused call is in the cassette. The
    # swaps are undone in a finally, a case that raises included
    record = getattr(args, "record", None)
    cap = getattr(args, "per_case_usd", None)
    key = prices.price_key(row["model"].get("provider"), row["model"].get("model"))
    # no price, no call: an unpriced model's spend could never be read
    spend = {
        "sent_bytes": [],
        "tripped": None if key in prices.PRICES else SPEND_UNREAD,
    }
    over_cap = (lambda: spend["tripped"]) if cap is not None else None
    calls: list = []
    execs: list = []
    # #233: what the Session starts with, taken before it is built: a flag
    # moved mid-case is not the one the case ran under
    flags = {n: os.environ.get(n) for n in LOOP_FLAGS}
    policy_records = [
        p.to_dict() for p in (getattr(args, "policy_records", None) or [])
    ]
    cleaned = None
    abort_events = None
    real_generate = llm.generate
    try:
        if cap is not None:
            llm.generate = _spend_guard(llm.generate, tele_path, key, cap, spend)
        if record:
            llm.generate = _recording_generate(llm.generate, calls)
        session = Session(
            workspace=str(work / "ws"),
            data_dir=str(work / "data"),
            docker=args.docker,
            skills_dir=str(work / "skills"),
            preview=False,
            snapshots=False,
            policies=getattr(args, "policy_records", None),
            autonomy=autonomy,
        )
        if record:
            # on the instance: restart() keeps this client, so every cell of
            # the case goes through it
            client = session.client
            real_execute = client.execute
            client.execute = _recording_execute(real_execute, execs)
        try:
            session.load(str(dirty_path), "df")
            row["events"] = _drive(
                session.clean("df"),
                args.max_events,
                args.wall_cap,
                t0,
                gates=gates,
                human_gates=human_gates,
                over_cap=over_cap,
            )
            if over_cap is not None and over_cap():  # crossed on the last call
                raise CaseAborted(over_cap(), row["events"])
            cleaned_path = Path(session.session_dir) / "cleaned" / "df.parquet"
            if cleaned_path.exists():
                cleaned = pd.read_parquet(cleaned_path)
                row["scores"] = score_end_to_end(pristine, dirty, cleaned, truth)
            else:
                row["status"] = "no_cleaned_output"
        except CaseAborted as exc:
            row["status"] = f"aborted: {exc}"
            abort_events = exc.events
        except Exception as exc:  # noqa: BLE001 — one broken case must not kill the run (R4)
            row["status"] = f"error: {type(exc).__name__}: {exc}"
        finally:
            if record:
                client.execute = real_execute
            session.close()
    finally:
        if record or cap is not None:
            llm.generate = real_generate
        # restore, never leak: the next case (and the test suite) must see
        # the environment it started with
        if prev_tele is None:
            os.environ.pop("CRIVO_TELEMETRY", None)
        else:
            os.environ["CRIVO_TELEMETRY"] = prev_tele
    row["calls"] = _call_stats(tele_path)
    if cap is not None:  # None when unread, never 0 (_case_cost)
        cost = _case_cost(tele_path, key, spend["sent_bytes"])
        bounded = cost is not None and cost["bounded_calls"] > 0
        # measured only: null once any call was charged a bound, never mixed
        row["cost_usd"] = None if cost is None or bounded else cost["measured"]
        # the calls that were measured, a bounded case's included, at the
        # entry's rates; cost_bound_usd adds the bounds on the unread ones
        row["cost_measured_usd"] = None if cost is None else cost["measured"]
        row["cost_bound_usd"] = (
            None if cost is None else cost["measured"] + cost["bounded"]
        )
        row["cost_bounded_calls"] = 0 if cost is None else cost["bounded_calls"]
    row["gates"] = {"run": gates.count("run"), "skip": gates.count("skip")}
    row["wall_secs"] = round(time.monotonic() - t0, 1)
    if record:
        arm = {
            "autonomy": autonomy,
            "human_gates": human_gates,
            "policies": row["policies"],
            "docker": args.docker,
            "max_events": args.max_events,
            "wall_cap": args.wall_cap,
            "suffix": suffix,
            "env": flags,
            "policy_records": policy_records,
        }
        outcome = {
            "status": row["status"],
            "events": row.get("events", abort_events),
            "gates": gates,
            "records": _fix_records(session.session_dir),
            "cleaned_sha256": None if cleaned is None else frame_sha256(cleaned),
            "scores": row.get("scores"),
        }
        tag = getattr(args, "run_tag", "") or ""
        _write_cassette(
            Path(record) / f"{name}{suffix}{tag}.json",
            entry,
            dirty,
            arm,
            calls,
            execs,
            outcome,
        )
    return row


def _mean(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def _tokens_text(value: float | None) -> str:
    """Render a telemetry number for the terminal. None is `unknown`, never 0:
    nothing was read, so what the case cost is not known, and a 0 in the cost
    or call column would read as a free run rather than an unmeasured one."""
    return "unknown" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent-mode Proving Ground lane")
    parser.add_argument("--sample", type=int, default=3, help="cases to run")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--full", action="store_true", help="seeds-expanded corpus")
    parser.add_argument("--force", action="store_true", help="rerun finished cases")
    parser.add_argument("--docker", action="store_true", help="sandbox kernel")
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    parser.add_argument(
        "--wall-cap", type=float, default=DEFAULT_WALL_CAP, help="secs/case"
    )
    parser.add_argument(
        "--human-gates",
        choices=("skip", "approve"),
        default="skip",
        help="approve = owner pre-authorises judgement-call fixes (ceiling arm); "
        "skill gates are skipped in every mode",
    )
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated case names; restricts the sampled set",
    )
    parser.add_argument(
        "--policies",
        choices=("none", "auto"),
        default="none",
        help="auto = one ENFORCE policy batching every AUTO disease with a "
        "registered fixer (the M1 batched arm; T1.4)",
    )
    parser.add_argument(
        "--autonomy",
        choices=("autonomous", "careful"),
        default=None,
        help="the autonomy arm to measure: autonomous applies AUTO findings "
        "with a registered fixer without showing a gate, careful gates them. "
        "Unset keeps the baseline arm (careful, empty file suffix). "
        "report-only is not an arm here: the bench scores cleaned output and "
        "a report-only run cleans nothing",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run each case N times and report pass^k consistency (A4); "
        "N model runs per case, so this is a paid choice",
    )
    parser.add_argument(
        "--record",
        metavar="DIR",
        default=None,
        help="write one cassette per case to DIR (EV2): each model reply, a "
        "fingerprint of each call, digests of each cell's result, the outcome. "
        "A case already on disk is skipped unless --force, so it is not recorded",
    )
    args = parser.parse_args(argv)
    if args.autonomy and args.human_gates == "approve":
        # An autonomy arm is measured with HUMAN gates skipped. `approve` runs
        # every non-admission HUMAN gate, which is a person's authorisation to
        # give, and the autonomous arm's reach is meant to come from the
        # Session's seeded AUTO policy alone. Coerce to the safe arm, and say
        # so: the row and the filename both record what actually ran. Saying
        # it here is for the operator who typed both flags; _arm_gates is what
        # enforces it, at every point of use.
        print("--autonomy is measured with --human-gates skip; approve ignored")
        args.human_gates = "skip"
    args.policy_records = []
    if args.policies == "auto":
        args.policy_records = [
            PolicyRecord(
                id="bench-auto",
                disease_ids=tuple(sorted(FIXERS)),
                approver="bench",
                expires="2099-01-01",
                mode="ENFORCE",
                valid_disease_ids=set(FIXERS),
            )
        ]

    _load_dotenv()
    _require_key()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.record:
        Path(args.record).mkdir(parents=True, exist_ok=True)

    entries = corpus.full_corpus() if args.full else list(corpus.SMOKE)
    picked = random.Random(args.seed).sample(entries, min(args.sample, len(entries)))
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        picked = [e for e in picked if e["name"] in wanted]

    suffix = _arm_suffix(args)
    repeat = max(1, args.repeat)
    rows = []
    for entry in picked:
        for run_i in range(repeat):
            # a repeated case needs a distinct file per run so pass^k has k
            # rows to score; a single run keeps the plain name (resume/skip)
            tag = f".r{run_i + 1}" if repeat > 1 else ""
            out = RESULTS_DIR / f"{entry['name']}{suffix}{tag}.json"
            if out.exists() and not args.force:
                rows.append(json.loads(out.read_text()))
                print(f"{entry['name']}{tag}: already on disk, skipped (R5)")
                continue
            args.run_tag = tag  # names this run's cassette, as it names `out`
            row = _run_case(entry, args)
            if repeat > 1:
                row["run"] = run_i + 1
            out.write_text(json.dumps(row, indent=2, default=str))
            repair = (row.get("scores") or {}).get("repair", {})
            calls = row.get("calls") or {}
            print(
                f"{row['name']}{tag}: {row['status']}"
                f" | repair F1 {repair.get('f1')}"
                f" | {row['wall_secs']}s | {row.get('events', 0)} events"
                f" | {_tokens_text(calls.get('count'))} calls"
                f" | {_tokens_text(calls.get('new_work_tokens'))} new-work tok"
            )
            rows.append(row)

    ok = [r for r in rows if r.get("status") == "ok" and r.get("scores")]
    ok_calls = [r.get("calls") or {} for r in ok]
    # the token mean covers only the scored cases that reported usage, so it
    # is published with the denominator it was taken over, and that
    # denominator names its own scope: an aborted case spends real tokens and
    # is in neither half of it
    tokens = [c.get("new_work_tokens") for c in ok_calls]
    known_tokens = [t for t in tokens if t is not None]
    print(
        f"\nagent lane: {len(ok)}/{len(rows)} scored"
        f" | repair F1 mean {_mean([r['scores']['repair'].get('f1') for r in ok])}"
        f" | repair recall mean "
        f"{_mean([r['scores']['repair'].get('recall') for r in ok])}"
        f" | calls mean {_mean([c.get('count') for c in ok_calls])}"
        f" | new-work tokens mean {_tokens_text(_mean(tokens))}"
        f" ({len(known_tokens)}/{len(tokens)} scored cases with token data)"
    )

    if repeat > 1:
        from bench import consistency

        agg = consistency.aggregate_consistency(consistency.group_by_case(rows))
        print(
            f"\nconsistency (k={repeat}): mean pass^k "
            f"{round(agg['mean_pass_k'], 3)} | mean pass@1 "
            f"{round(agg['mean_pass_at_1'], 3)}"
        )
        if agg["flaky"]:
            print(f"  flaky (solved some runs, not all): {', '.join(agg['flaky'])}")
        if agg["stable_solved"]:
            print(f"  stable solved every run: {', '.join(agg['stable_solved'])}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
