"""Replay a recorded agent run through the real loop, the real subprocess
kernel and the real in-kernel verification (EV3, #66; replay mode ED2).

What a green replay means: given these model outputs, the harness and the
referee behave as they did when the cassette was recorded. The same number of
model calls, the same gates, the same fixes, the same cleaned frame and the
same scores. It says nothing about model behaviour; that is measured on the
ledger, not here.

A cassette (`bench.agent_run --record`, EV2) keeps each model reply and only
digests of the rest, so a replay rebuilds the data from the corpus seed. The
live corpus entry is the one that runs, never the JSON copy in the cassette (a
JSON round trip turns int keys into strings). The recorded replies are queued
on the faux provider, a recorded provider error is raised again at its call's
index, and the case runs through `bench.agent_run._run_case`, exactly as the
bench runs it.

- Hard failures: a different number of model calls, a call that completes or
  fails differently, a different outcome (status, gates, records, cleaned
  frame, scores), or different data under the cassette (re-record it).
- A `StaleCassette` warning, not a failure: the prompts, a call's system
  prompt or messages, the event count, or a kernel cell drifted. A stale
  cassette that still reaches the same outcome stays green. A cell whose code
  embeds the run's own tmp path differs on every run, so its code digest is
  not compared at all.

`scan` is the gate that keeps rows out of committed cassettes (its docstring
says what it refuses); tests/test_cassettes.py runs it in CI.

Re-record a scripted fixture, keyless and offline:
`uv run python -m tests.replay record <case>`.
"""

from __future__ import annotations

import argparse
import builtins
import copy
import hashlib
import json
import math
import re
import sys
import tempfile
import warnings
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from bench import agent_run, corpus
from bench.truth import frame_sha256
from crivo import llm, pii
from crivo.events import Notice
from crivo.kernel.client import KernelClient
from crivo.readers.remote import READER_ENV_VARS

CASSETTES = Path(__file__).resolve().parent / "cassettes"
# what a cassette's data may come from: a corpus entry recorded on a real
# model, or one with scripted faux replies. Nothing else until a licence list
# exists (D24)
KINDS = ("corpus", "fixture")
# The arm does not record these yet, so every cassette is recorded and
# replayed with both unset (the loop's defaults).
PINNED_UNSET = ("CRIVO_M1", "CRIVO_PLAN_FIRST")
MAX_BYTES = 200_000
_EXEC_KEYS = (
    "code_sha256",
    "status",
    "ename",
    "exec_count",
    "value_sha256",
    "stream_sha256",
)


class StaleCassette(UserWarning):
    """Recorded against other prompts or other cells; it still replays."""


# --- the scripted fixtures ---------------------------------------------------
# tx-money-strings plants d01 (money held as text) in `amount`. The registered
# fixer's attempt fails verification there, so the finding falls through to
# the model. Reply 1 is the fix, verified in the kernel. The corpus wraps
# positive amounts in parentheses, so the fix strips them rather than reading
# them as negatives. Reply 2 generalises the fix into a skill, which passes
# admission and then stops at the admit-skill gate the bench always skips.

_MONEY_FIX = (
    "The amount column holds numbers written as text, with currency symbols, "
    "thousands separators and parentheses. Strip them and parse.\n"
    "<execute>\n"
    "import pandas as pd\n"
    "\n"
    "def fix_money_strings(df):\n"
    "    out = df.copy()\n"
    "    text = out['amount'].astype(str).str.strip()\n"
    "    text = text.str.replace(r'[$,()]', '', regex=True)\n"
    "    out['amount'] = pd.to_numeric(text, errors='raise')\n"
    "    return out\n"
    "\n"
    "df = fix_money_strings(df)\n"
    "assert df['amount'].dtype.kind == 'f'\n"
    "</execute>"
)

_MONEY_SKILL = (
    "<name>fix-money-strings</name>\n"
    "<description>Parse money written as text into numbers. Use when an amount "
    "column holds currency symbols, thousands separators or parentheses around "
    "the number.</description>\n"
    "<fix>\n"
    "def fix(df, columns):\n"
    "    import pandas as pd\n"
    "    out = df.copy()\n"
    "    for c in columns:\n"
    "        if c in out.columns:\n"
    "            text = out[c].astype(str).str.strip()\n"
    "            text = text.str.replace(r'[$,()]', '', regex=True)\n"
    "            out[c] = pd.to_numeric(text, errors='raise')\n"
    "    return out\n"
    "</fix>\n"
    "<test>\n"
    "import pandas as pd\n"
    "def test_fix_parses_money_text():\n"
    "    out = fix(pd.DataFrame({'x': ['$12.00', '3,000.50', '(7.25)']}), ['x'])\n"
    "    assert out['x'].tolist() == [12.0, 3000.5, 7.25]\n"
    "</test>"
)

FIXTURES: dict[str, tuple[str, ...]] = {
    "tx-money-strings": (_MONEY_FIX, _MONEY_SKILL),
}


# --- loading and rebuilding --------------------------------------------------


def load(path) -> dict:
    return json.loads(Path(path).read_text())


def _label(cassette: dict) -> str:
    return str(((cassette.get("source") or {}).get("entry") or {}).get("name"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _roundtrip(value):
    """What a value reads back as from a cassette (the writer's own dump)."""
    return json.loads(json.dumps(value, default=str))


def rerecord_hint(cassette: dict) -> str:
    name = _label(cassette)
    if (cassette.get("source") or {}).get("kind") == "fixture":
        return f"re-record: uv run python -m tests.replay record {name}"
    return f"re-record {name} with bench.agent_run --record (a paid run)"


def _outside_kind(label: str) -> str:
    return (
        f"{label}: source.kind must be corpus or fixture "
        "(no outside data until a licence list exists, D24)"
    )


def rebuild(cassette: dict, label: str | None = None) -> tuple:
    """(live entry, pristine, dirty) for the corpus entry a cassette names.

    Raises AssertionError, naming no value, when the data is not a corpus
    entry's or is no longer the data the cassette was recorded on."""
    label = label or _label(cassette)
    source = cassette.get("source") or {}
    if source.get("kind") not in KINDS:
        raise AssertionError(_outside_kind(label))
    want = source.get("entry") or {}
    entry = next(
        (
            e
            for e in (*corpus.SMOKE, *corpus.full_corpus())
            if e["name"] == want.get("name")
        ),
        None,
    )
    if entry is None:
        raise AssertionError(
            f"{label}: source.entry names no corpus entry, so its data is from "
            "outside the corpus (refused until a licence list exists, D24)"
        )
    if _roundtrip(entry) != want:
        raise AssertionError(
            f"{label}: source.entry differs from the live corpus entry; "
            + rerecord_hint(cassette)
        )
    pristine, dirty, _ = corpus.build(entry)
    if frame_sha256(dirty) != source.get("dirty_sha256"):
        raise AssertionError(
            f"{label}: source.dirty_sha256: the corpus generator changed under "
            "the cassette; " + rerecord_hint(cassette)
        )
    return entry, pristine, dirty


def bench_args(record_dir, **arm) -> argparse.Namespace:
    """The namespace `bench.agent_run.main` hands `_run_case`: the default
    arm, recording into `record_dir`."""
    base = {
        "docker": False,
        "max_events": agent_run.DEFAULT_MAX_EVENTS,
        "wall_cap": agent_run.DEFAULT_WALL_CAP,
        "human_gates": "skip",
        "policies": "none",
        "autonomy": None,
        "policy_records": [],
        "record": str(record_dir),
        "run_tag": "",
    }
    return argparse.Namespace(**{**base, **arm})


def arm_args(cassette: dict, record_dir) -> argparse.Namespace:
    """The arm the cassette recorded, rebuilt.

    A recorded abort replays with the event cap one below the recorded event
    count and no wall cap: the cap fires on the event after max_events. For a
    faux-recorded cassette, which streams one chunk per reply live and on
    replay alike, the replay stops where the live run did, whichever cap fired
    then. A real-model reply arrives in many chunks, each one an event, and
    replays as one, so placing a real-model abort waits for #233 (the recorder
    keeping chunk counts) and EV16 (#79)."""
    label = _label(cassette)
    arm = cassette.get("arm") or {}
    if arm.get("docker"):
        raise AssertionError(
            f"{label}: recorded with --docker; replay runs the host kernel only"
        )
    if (arm.get("policies") or "none") != "none":
        raise AssertionError(
            f"{label}: recorded with a policies arm; replay has no policy records"
        )
    max_events, wall_cap = arm["max_events"], arm["wall_cap"]
    outcome = cassette.get("outcome") or {}
    if str(outcome.get("status", "")).startswith("aborted"):
        events = outcome.get("events")
        if not isinstance(events, int) or events < 2:
            raise AssertionError(
                f"{label}: an abort recorded with no event count cannot replay"
            )
        max_events, wall_cap = events - 1, math.inf
    # the baseline arm records the autonomy it pinned ("careful") but has no
    # suffix part for it; None is how that arm is asked for
    autonomy = arm.get("autonomy")
    if autonomy not in (arm.get("suffix") or "").split("."):
        autonomy = None
    return bench_args(
        record_dir,
        max_events=max_events,
        wall_cap=wall_cap,
        human_gates=arm.get("human_gates", "skip"),
        autonomy=autonomy,
    )


def offline_env(monkeypatch) -> None:
    """Keyless and offline, whatever the shell holds: the faux provider, no
    credential or tuning variable, and the loop flags at their defaults."""
    for var in (*llm.KEY_ENV_VARS, *READER_ENV_VARS, *PINNED_UNSET):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CRIVO_PROVIDER", "faux")


# --- the seams ---------------------------------------------------------------


def _exception(error: dict) -> Exception:
    """The recorded provider error, raised again: the builtin or crivo class
    when one has the recorded name, else a stand-in class of that name (the
    loop reads only the name and the message)."""
    name = error.get("type") or "Exception"
    for space in (builtins, llm):
        cls = getattr(space, name, None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            return cls(error.get("message", ""))
    return type(name, (Exception,), {})(error.get("message", ""))


def _replaying_generate(orig, recorded: list, asked: list):
    """`orig` (llm.generate on the faux provider) behind a call counter. A
    recorded call with an error sends what arrived before it, then raises it
    again; every other call, an unrecorded one included, goes to `orig`, so
    one the cassette does not have meets the empty faux queue."""

    def generate(messages, model=None):
        i = len(asked)
        asked.append(i)
        call = recorded[i] if i < len(recorded) else {}
        if call.get("error"):
            if call.get("reply"):
                yield call["reply"]
            raise _exception(call["error"])
        yield from (orig(messages) if model is None else orig(messages, model))

    return generate


def _observed_execute(orig, cells: list):
    """KernelClient.execute, unchanged, keeping each cell's code in memory so
    the replay can tell which cells embed its own tmp path."""

    def execute(self, code, *args, **kwargs):
        cells.append(code)
        yield from orig(self, code, *args, **kwargs)

    return execute


class _Tee:
    """The CLEAN flow, passed through, keeping each event it yields."""

    def __init__(self, gen, sink: list):
        self._gen, self._sink = gen, sink

    def __iter__(self):
        return self

    def __next__(self):
        return self.send(None)

    def send(self, value):
        event = self._gen.send(value)
        self._sink.append(event)
        return event

    def close(self):
        self._gen.close()


def _teed_drive(orig, events: list):
    def drive(gen, *args, **kwargs):
        return orig(_Tee(gen, events), *args, **kwargs)

    return drive


# --- replaying ---------------------------------------------------------------


def run(cassette: dict, tmp_path, monkeypatch) -> dict:
    """Replay `cassette` once and return what happened, compared with nothing:
    the cassette the replay recorded, how many model calls it made, how many
    recorded replies were never asked for, the notices the flow showed, and
    the code digests of cells that embed the run's own tmp path."""
    tmp_path = Path(tmp_path)
    entry, _, _ = rebuild(cassette)
    record_dir = tmp_path / "replayed"
    record_dir.mkdir(parents=True, exist_ok=True)
    args = arm_args(cassette, record_dir)

    offline_env(monkeypatch)
    monkeypatch.setattr(llm, "_faux_responses", [])  # isolate the queue
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")
    recorded = cassette.get("calls") or []
    llm.faux_enqueue(*(c.get("reply") or "" for c in recorded if not c.get("error")))
    asked: list = []
    monkeypatch.setattr(
        llm, "generate", _replaying_generate(llm.generate, recorded, asked)
    )
    cells: list = []
    monkeypatch.setattr(
        KernelClient, "execute", _observed_execute(KernelClient.execute, cells)
    )
    events: list = []
    monkeypatch.setattr(agent_run, "_drive", _teed_drive(agent_run._drive, events))

    agent_run._run_case(entry, args)

    written = sorted(record_dir.glob("*.json"))
    if len(written) != 1:
        raise AssertionError(
            f"{_label(cassette)}: the replay wrote {len(written)} cassettes, not 1"
        )
    roots = {str(tmp_path), str(tmp_path.resolve())}
    return {
        "cassette": load(written[0]),
        "asked": len(asked),
        "left": len(llm._faux_responses),
        "notices": [(e.kind, e.text) for e in events if isinstance(e, Notice)],
        "path_cells": {_sha256(c) for c in cells if any(r in c for r in roots)},
    }


def _error_type(call: dict):
    return (call.get("error") or {}).get("type")


def _status(outcome: dict) -> str:
    """A recorded abort replays as an event-cap abort at the same event, so
    any abort matches any abort; outcome.events says where."""
    status = str(outcome.get("status"))
    return "aborted" if status.startswith("aborted") else status


def _shown(key: str, value) -> str:
    if key == "cleaned_sha256":
        return "none" if value is None else f"{value[:12]}…"
    return json.dumps(value)


def compare(recorded: dict, result: dict) -> tuple[list[str], list[str]]:
    """(failures, stale) between a cassette and a `run` of it. Pure: the
    self-tests check their mutated copies against one real run. Failures
    quote structure (gates, records, scores, digests), never a status or an
    error message, which can quote the data."""
    replayed = result["cassette"]
    fail: list[str] = []
    stale: list[str] = []

    if (recorded.get("source") or {}).get("dirty_sha256") != (
        replayed.get("source") or {}
    ).get("dirty_sha256"):
        fail.append(
            "source.dirty_sha256: the replay ran on other data; "
            + rerecord_hint(recorded)
        )

    rec_calls = recorded.get("calls") or []
    rep_calls = replayed.get("calls") or []
    made = result["asked"]
    if made != len(rec_calls):
        why = (
            "the harness asked for a reply the cassette does not have"
            if made > len(rec_calls)
            else f"{len(rec_calls) - made} recorded replies were never asked for"
        )
        fail.append(
            f"calls: the cassette has {len(rec_calls)} model calls, the replay "
            f"made {made} ({why})"
        )
    elif result.get("left"):
        fail.append(f"calls: {result['left']} queued replies were never asked for")
    for i, (a, b) in enumerate(zip(rec_calls, rep_calls)):
        if bool(a.get("complete")) != bool(b.get("complete")):
            fail.append(
                f"calls[{i}].complete: recorded {bool(a.get('complete'))}, "
                f"replayed {bool(b.get('complete'))}"
            )
        if _error_type(a) != _error_type(b):
            fail.append(
                f"calls[{i}].error.type: recorded {_error_type(a)}, "
                f"replayed {_error_type(b)}"
            )
        stale.extend(
            f"calls[{i}].{key}"
            for key in ("system_sha256", "messages_sha256", "n_messages")
            if a.get(key) != b.get(key)
        )

    ro = recorded.get("outcome") or {}
    po = replayed.get("outcome") or {}
    if _status(ro) != _status(po):
        fail.append("outcome.status differs")
    for key in ("gates", "records", "cleaned_sha256", "scores"):
        if _roundtrip(ro.get(key)) != _roundtrip(po.get(key)):
            fail.append(
                f"outcome.{key}: recorded {_shown(key, ro.get(key))}, "
                f"replayed {_shown(key, po.get(key))}"
            )
    if ro.get("events") != po.get("events"):
        stale.append(f"outcome.events ({ro.get('events')} -> {po.get('events')})")

    if (recorded.get("crivo") or {}).get("prompts_sha256") != (
        replayed.get("crivo") or {}
    ).get("prompts_sha256"):
        stale.append("crivo.prompts_sha256 (prompts.py changed since recording)")

    rx, px = recorded.get("execs") or [], replayed.get("execs") or []
    if len(rx) != len(px):
        stale.append(f"execs: {len(rx)} cells recorded, {len(px)} replayed")
    path_cells = result.get("path_cells") or set()
    for i, (a, b) in enumerate(zip(rx, px)):
        for key in _EXEC_KEYS:
            if key == "code_sha256" and b.get(key) in path_cells:
                continue  # embeds this run's tmp path, so it differs every run
            if a.get(key) != b.get(key):
                stale.append(f"execs[{i}].{key}")
    return fail, stale


def check(recorded: dict, result: dict, label: str | None = None) -> None:
    """Warn when the cassette is stale, fail when the replay differs."""
    label = label or _label(recorded)
    fail, stale = compare(recorded, result)
    if stale:
        warnings.warn(
            StaleCassette(f"{label}: stale, still replays: " + "; ".join(stale)),
            stacklevel=2,
        )
    if fail:
        raise AssertionError(
            f"{label}: the replay differs from the cassette:\n  " + "\n  ".join(fail)
        )


def replay(cassette: dict, tmp_path, monkeypatch) -> dict:
    """Replay `cassette` through the real loop and kernel; fail when it
    differs, warn when it is stale. Returns the `run` result."""
    result = run(cassette, tmp_path, monkeypatch)
    check(cassette, result)
    return result


# --- the raw-row scan ----------------------------------------------------------

# never scanned: the corpus entry, which rebuild checks against the live one
_SKIP_PATHS = ("source.entry",)
# a field that holds a digest is skipped only while it holds one: a sha256 or
# a git commit, lowercase hex, or nothing
_DIGEST = re.compile(r"[0-9a-f]{64}|[0-9a-f]{40}")


def _is_digest_field(path: str, key) -> bool:
    return str(key).endswith("_sha256") or path == "crivo.commit"


def _leaves(node, path: str = ""):
    """(field path, text) for every string in the cassette that is scanned:
    every value but the corpus entry and a digest field's digest. A digest
    field holding anything else is scanned like any other."""
    if isinstance(node, dict):
        for key, value in node.items():
            sub = f"{path}.{key}" if path else str(key)
            if sub in _SKIP_PATHS:
                continue
            if _is_digest_field(sub, key) and (
                value is None or (isinstance(value, str) and _DIGEST.fullmatch(value))
            ):
                continue
            yield from _leaves(value, sub)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _leaves(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def _cell_text(value) -> str:
    """A cell as a reply would quote it: stripped, a midnight timestamp as its
    date, a whole float without its `.0`. Empty for a missing cell."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass  # a list-like cell: not a scalar, so not missing
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value == value.normalize() else str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def scan(
    cassette: dict,
    label: str,
    frames: tuple | None = None,
    nbytes: int | None = None,
) -> list[str]:
    """What keeps a cassette from carrying rows. Empty when it may be committed.

    - `source.kind` must be corpus or fixture, and the entry a live corpus
      entry. Nothing from outside data (D24).
    - The pristine and dirty frames are rebuilt from the corpus (or passed in
      as `frames`). A cell counts when it is distinctive: text of 4
      characters or more whose value occurs in at most max(2, 1% of rows)
      rows of its column, and is not a column name. Three distinctive cells
      of one row anywhere in the cassette, matched at word boundaries, are
      refused. A common category, region and status of one row are not.
    - A value of a column `crivo.pii.flagged_columns` flags is refused on its
      own when it is PII by itself (an address repeated across rows still is)
      or distinctive under the filter above (an address cut short still is).
      A sentinel such as "N/A" in that column is neither, and passes, as does
      the masked form of an address.
    - Over MAX_BYTES is refused.

    `source.entry` is not scanned (rebuild checks it against the live corpus
    entry), nor is a `*_sha256` or `crivo.commit` field while it holds a
    digest or nothing. A problem names the cassette, the frame, the row, the
    columns and the field paths. Never a value."""
    problems: list[str] = []
    if nbytes is None:
        nbytes = len(json.dumps(cassette, indent=2, default=str).encode())
    if nbytes > MAX_BYTES:
        problems.append(f"{label}: {nbytes} bytes, over the {MAX_BYTES}-byte limit")
    if frames is None:
        try:
            _, pristine, dirty = rebuild(cassette, label)
        except AssertionError as exc:
            return [*problems, str(exc)]
    else:
        if (cassette.get("source") or {}).get("kind") not in KINDS:
            return [*problems, _outside_kind(label)]
        pristine, dirty = frames

    leaves = list(_leaves(cassette))
    joined = "\n".join(text for _, text in leaves)
    found: dict[str, list[str]] = {}

    def where(text: str) -> list[str]:
        if text not in found:
            if text not in joined:
                found[text] = []
            else:
                pattern = re.compile(rf"(?<!\w){re.escape(text)}(?!\w)")
                found[text] = [p for p, t in leaves if pattern.search(t)]
        return found[text]

    flagged = pii.flagged_columns(pristine, dirty)
    for which, frame in (("pristine", pristine), ("dirty", dirty)):
        names = {str(c) for c in frame.columns}
        limit = max(2, 0.01 * len(frame))
        rows: dict[int, dict[int, list[str]]] = {}
        for j in range(frame.shape[1]):
            column = str(frame.columns[j])
            cells = [_cell_text(v) for v in frame.iloc[:, j]]
            counts = Counter(c for c in cells if c)
            for i, text in enumerate(cells):
                if not text:
                    continue
                distinctive = (
                    len(text) >= 4 and counts[text] <= limit and text not in names
                )
                personal = column in flagged and (
                    distinctive or pii._cell_type(text) is not None
                )
                if personal and (paths := where(text)):
                    problems.append(
                        f"{label}: a value of {flagged[column]}-flagged "
                        f"column {column} ({which} row {i}) is in " + ", ".join(paths)
                    )
                if distinctive and (paths := where(text)):
                    rows.setdefault(i, {})[j] = paths
        for i, hits in sorted(rows.items()):
            if len(hits) < 3:
                continue
            columns = ", ".join(str(frame.columns[j]) for j in sorted(hits))
            paths = sorted({p for ps in hits.values() for p in ps})
            problems.append(
                f"{label}: {len(hits)} cells of {which} row {i} ({columns}) "
                f"are in {', '.join(paths)}"
            )
    return problems


# --- recording a fixture -------------------------------------------------------


def record(name: str, out_dir: Path = CASSETTES) -> Path:
    """Record FIXTURES[name] on its SMOKE case with EV2's recorder, under the
    faux provider, and write it as `<out_dir>/<name>.json` with
    `source.kind: fixture`. Keyless and offline."""
    replies = FIXTURES[name]
    entry = next(e for e in corpus.SMOKE if e["name"] == name)
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        offline_env(mp)
        mp.setattr(llm, "_faux_responses", [])
        mp.setattr(agent_run, "RESULTS_DIR", Path(tmp) / "res")
        llm.faux_enqueue(*replies)
        rec_dir = Path(tmp) / "rec"
        rec_dir.mkdir()
        agent_run._run_case(entry, bench_args(rec_dir))
        left = len(llm._faux_responses)
        cassette = load(rec_dir / f"{name}.json")
    if left:
        raise SystemExit(f"{name}: {left} scripted replies were never asked for")
    cassette = copy.deepcopy(cassette)
    cassette["source"]["kind"] = "fixture"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.json"
    out.write_text(json.dumps(cassette, indent=2, default=str) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.replay")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser(
        "record", help="re-record a scripted fixture (faux replies, keyless)"
    )
    rec.add_argument("case", choices=sorted(FIXTURES))
    args = parser.parse_args(argv)
    path = record(args.case)
    cassette = load(path)
    outcome = cassette["outcome"]
    print(
        f"wrote {path}: {len(cassette['calls'])} model calls, "
        f"{len(cassette['execs'])} cells, gates {outcome['gates']}, "
        f"records {outcome['records']}"
    )
    problems = scan(cassette, path.stem, nbytes=path.stat().st_size)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
