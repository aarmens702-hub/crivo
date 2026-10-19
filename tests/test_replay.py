"""Self-tests for the cassette replay and the raw-row scan (EV3, #66).

Each test plants one change and checks the replay or the scan catches it, so
a replay that passes everything, or a scan that refuses everything, fails
here. The committed fixture is replayed once for the module; the mutations of
its cassette are checked against that one real run with the pure compare.
Only the tests that need the loop to act on a changed reply run a kernel of
their own."""

import copy
import hashlib
import math
import os

import pandas as pd
import pytest

from bench import agent_run, corpus
from crivo import detect, llm, pii
from crivo.loop import HEARTBEAT_EVERY
from crivo.policy import PolicyRecord
from tests import replay

CASE = "tx-money-strings"
FIXTURE = replay.CASSETTES / f"{CASE}.json"


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory):
    """(the committed fixture, one real replay of it)."""
    cassette = replay.load(FIXTURE)
    with pytest.MonkeyPatch.context() as mp:
        result = replay.run(cassette, tmp_path_factory.mktemp("fixture"), mp)
    return cassette, result


def _changed(cassette, change):
    out = copy.deepcopy(cassette)
    change(out)
    return out


# --- the fixture and a green replay ----------------------------------------


def test_the_fixture_is_a_verified_model_fix_from_the_scripted_replies():
    """The fixture is worth replaying only while the model's fix carries the
    case: model calls made, the case ok, and a fix with a model attempt behind
    it that verification kept. Its replies are the scripted ones, so
    re-recording reproduces it."""
    cassette = replay.load(FIXTURE)
    assert cassette["source"]["kind"] == "fixture"
    assert [c["reply"] for c in cassette["calls"]] == list(replay.FIXTURES[CASE])
    assert all(c["complete"] and c["error"] is None for c in cassette["calls"])
    assert cassette["outcome"]["status"] == "ok"
    fixed_by_model = [
        r for r in cassette["outcome"]["records"] if r[3] == "fixed" and r[4] >= 1
    ]
    assert fixed_by_model, "no fix with a model attempt behind it"


def test_the_fixture_replays_green(fixture_run):
    cassette, result = fixture_run
    replay.check(cassette, result)
    assert result["asked"] == len(cassette["calls"])
    assert result["left"] == 0, "a recorded reply was never asked for"
    assert not [n for n in result["notices"] if n[0] == "llm_error"]


# --- what a replay fails on ---------------------------------------------------


def _drop_reply(c):
    del c["calls"][-1]


def _add_reply(c):
    extra = copy.deepcopy(c["calls"][-1])
    extra["i"] = len(c["calls"])
    c["calls"].append(extra)


def _set(*path_and_value):
    *path, value = path_and_value

    def change(c):
        node = c
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return change


HARD_FAILURES = {
    "a dropped reply": (_drop_reply, "calls: the cassette has 1 model calls"),
    "an added reply": (_add_reply, "1 recorded replies were never asked for"),
    "other data": (_set("source", "dirty_sha256", "0" * 64), "re-record:"),
    "a call that did not complete": (
        _set("calls", 0, "complete", False),
        "calls[0].complete",
    ),
    "a call that failed": (
        _set("calls", 0, "error", {"type": "TimeoutError", "message": "gave up"}),
        "calls[0].error.type",
    ),
    "another status": (
        _set("outcome", "status", "no_cleaned_output"),
        "outcome.status",
    ),
    "other gates": (_set("outcome", "gates", ["run", "skip"]), "outcome.gates"),
    "other records": (
        _set("outcome", "records", [[1, ["amount"], "AUTO", "failed", 3]]),
        "outcome.records",
    ),
    "another cleaned frame": (
        _set("outcome", "cleaned_sha256", "0" * 64),
        "outcome.cleaned_sha256",
    ),
    "other scores": (_set("outcome", "scores", None), "outcome.scores"),
}


@pytest.mark.parametrize("case", HARD_FAILURES)
def test_a_cassette_the_replay_does_not_match_fails(fixture_run, case):
    cassette, result = fixture_run
    change, expected = HARD_FAILURES[case]
    changed = _changed(cassette, change)

    failures, _ = replay.compare(changed, result)
    assert any(expected in f for f in failures), failures
    with pytest.raises(AssertionError, match="differs from the cassette"):
        replay.check(changed, result)


STALE = {
    "crivo.prompts_sha256": _set("crivo", "prompts_sha256", "0" * 64),
    "calls[0].system_sha256": _set("calls", 0, "system_sha256", "0" * 64),
    "calls[1].messages_sha256": _set("calls", 1, "messages_sha256", "0" * 64),
    "execs[1].stream_sha256": _set("execs", 1, "stream_sha256", "0" * 64),
    "outcome.events": _set("outcome", "events", 12),
}


@pytest.mark.parametrize("field", STALE)
def test_a_stale_cassette_warns_and_still_passes(fixture_run, field):
    """A prompt or a cell that drifted while the harness still reaches the same
    outcome is stale, not broken: it warns and stays green."""
    cassette, result = fixture_run
    changed = _changed(cassette, STALE[field])

    failures, stale = replay.compare(changed, result)
    assert failures == []
    assert any(s.startswith(field) for s in stale), stale
    with pytest.warns(replay.StaleCassette, match=field.replace("[", r"\[")):
        replay.check(changed, result)


# the fix with parentheses read as negatives: verification accepts it (the
# money strings are gone and nothing else moved), so the call count holds,
# but the corpus put the parentheses around positive amounts
_STRIP = "text = text.str.replace(r'[$,()]', '', regex=True)"
_NEGATE = (
    "text = text.str.replace(r'^\\((.*)\\)$', r'-\\1', regex=True)\n"
    "    text = text.str.replace(r'[$,]', '', regex=True)"
)


def test_editing_the_fix_cell_in_a_reply_fails_on_the_outcome(tmp_path, monkeypatch):
    cassette = replay.load(FIXTURE)
    reply = cassette["calls"][0]["reply"]
    assert _STRIP in reply, "the fixture's fix no longer has the line to edit"
    edited = _changed(
        cassette, _set("calls", 0, "reply", reply.replace(_STRIP, _NEGATE))
    )

    with (
        pytest.warns(replay.StaleCassette, match="code_sha256"),
        pytest.raises(AssertionError) as caught,
    ):
        replay.replay(edited, tmp_path, monkeypatch)

    message = str(caught.value)
    assert "outcome.cleaned_sha256" in message
    assert "outcome.scores" in message
    assert "calls:" not in message, "the edit moved the outcome, not the call count"


def test_a_recorded_timeout_replays_as_the_same_notice(tmp_path, monkeypatch):
    """Recorded live: the provider times out on the case's only model call.
    The replay raises the recorded error at that call, so the loop shows the
    notice it showed live and the case ends the same way."""
    entry = next(e for e in corpus.SMOKE if e["name"] == CASE)
    said = "gave up after 90s of silence"

    def timed_out(messages, model=None):
        yield ""  # a heartbeat, then the stall budget runs out
        raise TimeoutError(said)

    rec_dir = tmp_path / "rec"
    rec_dir.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        replay.offline_env(mp)
        mp.setattr(agent_run, "RESULTS_DIR", tmp_path / "live")
        mp.setattr(llm, "generate", timed_out)
        agent_run._run_case(entry, replay.bench_args(rec_dir))
    cassette = replay.load(rec_dir / f"{CASE}.json")
    assert [c["error"] for c in cassette["calls"]] == [
        {"type": "TimeoutError", "message": said}
    ]

    result = replay.replay(cassette, tmp_path / "replay", monkeypatch)

    assert ("llm_error", f"TimeoutError: {said}") in result["notices"]
    assert result["cassette"]["calls"][0]["error"] == cassette["calls"][0]["error"]


def test_a_recorded_event_cap_abort_replays_at_the_same_event(tmp_path, monkeypatch):
    """Recorded live on faux with an event cap of 3: the cap fires on the
    model's first reply, so that call is closed mid-stream (incomplete, not an
    error) and its scripted successor is never asked for. The replay stops on
    the same event, with the same call left incomplete."""
    entry = next(e for e in corpus.SMOKE if e["name"] == CASE)
    rec_dir = tmp_path / "rec"
    rec_dir.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        replay.offline_env(mp)
        mp.setattr(llm, "_faux_responses", [])
        mp.setattr(agent_run, "RESULTS_DIR", tmp_path / "live")
        llm.faux_enqueue(*replay.FIXTURES[CASE])
        agent_run._run_case(entry, replay.bench_args(rec_dir, max_events=3))
    (path,) = rec_dir.glob("*.json")
    cassette = replay.load(path)
    assert cassette["outcome"]["status"] == "aborted: event cap 3 hit"
    assert [(c["complete"], c["error"]) for c in cassette["calls"]] == [(False, None)]

    result = replay.replay(cassette, tmp_path / "replay", monkeypatch)

    replayed = result["cassette"]
    assert replayed["outcome"]["events"] == cassette["outcome"]["events"]
    assert [c["complete"] for c in replayed["calls"]] == [False]
    assert result["left"] == 0


def test_the_replay_raises_a_recorded_error_at_its_index_and_counts_every_call():
    """The seam on its own: a recorded error is raised at its index after what
    arrived before it, under its recorded class name, and a call the cassette
    does not have still reaches the provider and is counted. A recorded call
    that did not fail uses up the provider's reply and sends the recorded one
    (#233); a recorded error never reaches the provider."""
    recorded = [
        {"reply": "<execute>\nprint(df.shape)\n</execute>", "error": None},
        {
            "reply": "<execute>\ndf['acct'] = ",
            "error": {"type": "TimeoutError", "message": "gave up after 90s"},
        },
        {
            "reply": "",
            "error": {"type": "APIConnectionError", "message": "Connection error."},
        },
    ]
    reached: list = []

    def provider(messages, model=None):
        reached.append(len(reached))
        yield "from the provider"

    asked: list = []
    generate = replay._replaying_generate(provider, recorded, asked)

    assert list(generate([])) == [recorded[0]["reply"]]
    assert reached == [0], "the recorded call did not use up the provider's reply"
    seen = []
    with pytest.raises(TimeoutError, match="gave up after 90s"):
        for chunk in generate([]):
            seen.append(chunk)  # noqa: PERF402 — keeps the chunks before the raise
    assert seen == ["<execute>\ndf['acct'] = "]
    with pytest.raises(Exception, match="Connection error") as caught:
        list(generate([]))
    assert type(caught.value).__name__ == "APIConnectionError"
    assert list(generate([])) == ["from the provider"], "an unrecorded call"
    assert len(asked) == 4
    assert reached == [0, 1], "a recorded error reached the provider"


# --- replaying what the recorder keeps since #233 -----------------------------
# A real model streams a reply in many chunks, with empty heartbeat chunks
# while it thinks. The loop shows each chunk as an event and a dot every
# HEARTBEAT_EVERY heartbeats, so a replay sends each reply in its recorded
# chunks. It also sets the loop flags from arm.env and rebuilds the arm's
# policy records. A cassette without those fields replays as it did before.

_PIECES = (9, 1, 40, 3, 17)  # chunk sizes, cycled: uneven, as a stream's are
_THINK = HEARTBEAT_EVERY + 3  # heartbeats before the reply: one dot's worth
_PAUSE = 3  # heartbeats after the second piece


def _streamed(reply: str) -> list[str]:
    """`reply` as a real model streams it: a think, then uneven pieces, with a
    pause after the second."""
    chunks, start, k = [""] * _THINK, 0, 0
    while start < len(reply):
        size = _PIECES[k % len(_PIECES)]
        chunks.append(reply[start : start + size])
        start, k = start + size, k + 1
        if k == 2:
            chunks.extend([""] * _PAUSE)
    return chunks


def _record(tmp_path, *, streamed=False, env=None, **arm):
    """CASE recorded live with its scripted replies, keyless and offline, and
    the cassette it wrote. `streamed` sends each reply in `_streamed` chunks
    instead of faux's one; `env` sets loop flags for the recording only."""
    entry = next(e for e in corpus.SMOKE if e["name"] == CASE)
    streams = [_streamed(reply) for reply in replay.FIXTURES[CASE]]

    def generate(messages, model=None):
        yield from streams.pop(0)

    rec_dir = tmp_path / "rec"
    rec_dir.mkdir(parents=True)
    with pytest.MonkeyPatch.context() as mp:
        replay.offline_env(mp)
        for flag, value in (env or {}).items():
            mp.setenv(flag, value)
        mp.setattr(llm, "_faux_responses", [])
        mp.setattr(agent_run, "RESULTS_DIR", tmp_path / "live")
        if streamed:
            mp.setattr(llm, "generate", generate)
        else:
            llm.faux_enqueue(*replay.FIXTURES[CASE])
        agent_run._run_case(entry, replay.bench_args(rec_dir, **arm))
    (path,) = rec_dir.glob("*.json")
    return replay.load(path)


def _replayed(cassette, tmp_path):
    """One replay in its own patch context, so a test can run two."""
    with pytest.MonkeyPatch.context() as mp:
        return replay.run(cassette, tmp_path, mp)


@pytest.fixture(scope="module")
def streamed_recording(tmp_path_factory):
    """CASE recorded once on the default arm, each reply streamed in chunks."""
    return _record(tmp_path_factory.mktemp("streamed"), streamed=True)


def test_a_reply_streamed_in_chunks_replays_with_the_events_it_recorded(
    streamed_recording, tmp_path
):
    """#233, Done when 1: each reply streamed in uneven chunks after a think
    long enough for the loop to show a dot. The replay sends the same chunks,
    so it reaches the same outcome.events, and nothing is stale."""
    replies = len(replay.FIXTURES[CASE])
    assert [(c["complete"], c["error"]) for c in streamed_recording["calls"]] == [
        (True, None)
    ] * replies

    result = _replayed(copy.deepcopy(streamed_recording), tmp_path)

    failures, stale = replay.compare(streamed_recording, result)
    assert failures == []
    replayed = result["cassette"]
    assert replayed["outcome"]["events"] == streamed_recording["outcome"]["events"]
    assert stale == []
    assert [c.get("chunks") for c in replayed["calls"]] == [
        c.get("chunks") for c in streamed_recording["calls"]
    ]


def _as_before_233(cassette):
    """The cassette as the recorder wrote it before #233: no call's chunks, no
    arm.env, no arm.policy_records."""
    old = copy.deepcopy(cassette)
    for call in old["calls"]:
        call.pop("chunks", None)
    old["arm"].pop("env", None)
    old["arm"].pop("policy_records", None)
    return old


def test_a_cassette_without_the_fields_added_in_233_still_replays(
    streamed_recording, tmp_path
):
    """Scout call 3: the fields are optional and schema_version stays 1, so a
    cassette recorded before them replays as it did (the committed fixture is
    one): each reply in one chunk, the loop flags unset, no policy records.
    Only the event count moves, which is stale, not a failure."""
    assert all("chunks" in c for c in streamed_recording["calls"]), (
        "no call kept its chunks"
    )
    assert {"env", "policy_records"} <= set(streamed_recording["arm"]), (
        "the arm kept no env or policy records"
    )
    old = _as_before_233(streamed_recording)
    assert old["schema_version"] == 1

    result = _replayed(old, tmp_path)

    failures, stale = replay.compare(old, result)
    assert failures == []
    assert all(s.startswith("outcome.events") for s in stale), stale


def test_an_event_cap_abort_mid_reply_replays_at_the_same_chunk(tmp_path):
    """#233: recorded live with the replies streamed and an event cap of 6.
    The think's dot and the first two pieces are events 4 to 6, so the cap
    fires on the third piece and closes the call mid-reply. The replay sends
    the same chunks, so it stops on that same piece: the call incomplete with
    the same text, and no reply asked for past it."""
    cassette = _record(tmp_path / "live", streamed=True, max_events=6)
    (call,) = cassette["calls"]
    assert cassette["outcome"]["status"] == "aborted: event cap 6 hit"
    assert (call["complete"], call["error"]) == (False, None)
    assert 0 < len(call["reply"]) < len(replay.FIXTURES[CASE][0]), (
        "the cap no longer fires mid-reply: move it"
    )

    result = _replayed(cassette, tmp_path / "replay")

    failures, _ = replay.compare(cassette, result)
    assert failures == []
    (again,) = result["cassette"]["calls"]
    assert again["complete"] is False
    assert again["reply"] == call["reply"]
    assert again.get("chunks") == call.get("chunks")


def test_a_cassette_recorded_on_the_pre_m1_flow_replays_on_it(
    streamed_recording, tmp_path
):
    """#233, Done when 1: CRIVO_M1=off is the pre-M1 flow, with no registered
    fixer's attempt before the model's, so the case shows a gate fewer.
    Recorded with it off and the replies streamed in chunks, the replay sets
    it off from arm.env and matches, outcome.events included. The default
    flow on the same streamed replies shows other gates, so a replay that
    dropped arm.env would fail on them."""
    cassette = _record(tmp_path / "live", streamed=True, env={"CRIVO_M1": "off"})
    assert cassette["outcome"]["status"] == "ok"
    assert cassette["outcome"]["gates"] != streamed_recording["outcome"]["gates"], (
        "CRIVO_M1=off no longer changes the gates: this test proves nothing"
    )

    result = _replayed(cassette, tmp_path / "replay")

    failures, stale = replay.compare(cassette, result)
    assert failures == []
    assert result["cassette"]["outcome"]["events"] == cassette["outcome"]["events"]
    assert stale == []


def _bench_auto():
    """The record `bench.agent_run.main` mints for --policies auto."""
    return PolicyRecord(
        id="bench-auto",
        disease_ids=tuple(sorted(agent_run.FIXERS)),
        approver="bench",
        expires="2099-01-01",
        mode="ENFORCE",
        valid_disease_ids=set(agent_run.FIXERS),
    )


def test_a_cassette_recorded_on_the_policies_arm_replays(tmp_path):
    """#233: --policies auto hands the Session a standing ENFORCE policy, which
    changes the gates the case shows. The arm keeps the record, so the replay
    rebuilds it and reaches the same outcome; before #233 it refused the
    cassette."""
    cassette = _record(
        tmp_path / "live", policies="auto", policy_records=[_bench_auto()]
    )
    assert cassette["arm"]["suffix"] == ".policies-auto"

    try:
        result = _replayed(cassette, tmp_path / "replay")
    except AssertionError as exc:
        pytest.fail(f"the replay refused a policies-auto cassette: {exc}")

    failures, _ = replay.compare(cassette, result)
    assert failures == []
    assert result["cassette"]["arm"]["suffix"] == ".policies-auto"
    default = replay.load(FIXTURE)["outcome"]["gates"]  # same replies, no policy
    assert result["cassette"]["outcome"]["gates"] != default, "the policy moved no gate"


# --- the chunk seam (#233) ------------------------------------------------------


def _chunker():
    """The seam under test, looked up so that a missing one fails on this
    assertion rather than on an AttributeError."""
    chunker = getattr(replay, "_recorded_chunks", None)
    assert callable(chunker), "tests.replay._recorded_chunks does not exist yet"
    return chunker


_OPEN = "<execute>\nmask = df['branch'].str.strip() == 'São Paulo'"  # 56
_BODY = "\ndf.loc[mask, 'amount'] = df.loc[mask, 'amount'].str.replace(',', '')"  # 69
_CLOSE = "\n</execute>"  # 11
_ACCT = "<execute>\ndf['acct'] = df['acct'].str.strip().str.zfill(5)\n</execute>"
_TIMEOUT = {"type": "TimeoutError", "message": "gave up after 90s of silence"}

# a call as a cassette keeps it, and the chunks a replay sends for it; the
# lengths are counted by hand, in characters ('São' is 3, in 4 bytes)
SLICED = {
    "a think, then the reply in pieces": (
        {"reply": _OPEN + _BODY + _CLOSE, "chunks": [-23, 56, -3, 69, 11]},
        [""] * 23 + [_OPEN] + [""] * 3 + [_BODY, _CLOSE],
    ),
    "a call that failed mid-cell": (
        {
            "reply": "<execute>\ndf['acct'] = ",
            "chunks": [-1, 10, -2, 13],
            "complete": False,
            "error": _TIMEOUT,
        },
        ["", "<execute>\n", "", "", "df['acct'] = "],
    ),
    # a cap closes a think on the loop's dot, every HEARTBEAT_EVERY heartbeats
    "a call a cap closed during its think": (
        {
            "reply": "",
            "chunks": [-2 * HEARTBEAT_EVERY],
            "complete": False,
            "error": None,
        },
        [""] * (2 * HEARTBEAT_EVERY),
    ),
    "a call recorded before #233": ({"reply": _ACCT}, [_ACCT]),
}


@pytest.mark.parametrize("case", SLICED)
def test_a_recorded_reply_is_cut_into_its_recorded_chunks(case):
    """The seam on its own: each positive int is the next that many
    characters of the reply, each -k is k heartbeats. A call with no
    `chunks` is sent whole, as faux sends a reply."""
    call, expected = SLICED[case]
    chunker = _chunker()

    assert chunker(call, 0) == expected


@pytest.mark.parametrize(
    "chunks",
    [[-23, 56, -3, 69], [-23, 56, -3, 69, 11, 4]],
    ids=["short of the reply", "past the reply"],
)
def test_chunks_that_do_not_sum_to_the_reply_fail_naming_the_call_not_its_text(
    chunks,
):
    """Scout call 4: a cassette whose chunks do not add up to its reply cannot
    be replayed as recorded. It fails naming calls[i], never the text: a
    reply can quote what the model saw."""
    reply = _OPEN + _BODY + _CLOSE
    chunker = _chunker()

    with pytest.raises(AssertionError) as caught:
        chunker({"reply": reply, "chunks": chunks}, 3)

    message = str(caught.value)
    assert "calls[3]" in message
    leaked = any(line in message for line in reply.splitlines() if line)
    assert not leaked, "the failure quotes the reply"


def test_a_recorded_error_sends_its_recorded_chunks_before_it_raises():
    """The replaying generate on a recorded error: what arrived before it, in
    its recorded chunks with the heartbeats, then the error again."""
    recorded = [
        {
            "reply": "<execute>\ndf['acct'] = ",
            "chunks": [-2, 10, -1, 13],
            "complete": False,
            "error": _TIMEOUT,
        }
    ]

    def provider(messages, model=None):
        yield "from the provider"

    generate = replay._replaying_generate(provider, recorded, [])
    seen = []
    with pytest.raises(TimeoutError, match="gave up after 90s"):
        for chunk in generate([]):
            seen.append(chunk)  # noqa: PERF402 — keeps the chunks before the raise

    assert seen == ["", "", "<execute>\n", "", "df['acct'] = "]


def test_a_cassette_whose_chunks_miss_a_reply_is_refused_before_it_runs(
    tmp_path, monkeypatch
):
    """Scout call 4, at the run: a mismatch found mid-replay would be raised
    inside generate, where the loop reads it as a provider error and goes on,
    so the replay checks every call before the case starts and refuses the
    cassette, naming the call and never its text."""
    cassette = replay.load(FIXTURE)
    reply = cassette["calls"][1]["reply"]
    bad = _changed(cassette, _set("calls", 1, "chunks", [-20, len(reply) - 1]))

    with pytest.raises(AssertionError) as caught:
        replay.run(bad, tmp_path, monkeypatch)

    message = str(caught.value)
    assert CASE in message and "calls[1]" in message
    leaked = any(line in message for line in reply.splitlines() if line.strip())
    assert not leaked, "the refusal quotes the reply"


class _Started(Exception):
    """Where a replay rebuilds the case: past every check it makes first."""


def _stop_at_rebuild(monkeypatch, *, refused: bool) -> None:
    """Stop `replay.run` where the case would start, so no kernel runs. With
    `refused`, reaching it fails the test: the cassette got past the checks."""

    def rebuild(cassette, label=None):
        if refused:
            pytest.fail("the case started: the cassette was not refused")
        raise _Started

    monkeypatch.setattr(replay, "rebuild", rebuild)


@pytest.mark.parametrize(
    "beats",
    [(10**9,), (replay.MAX_HEARTBEATS // 2 + 1,) * 2],
    ids=["a billion heartbeats", "runs that add up past the bound"],
)
def test_a_call_with_more_heartbeats_than_a_call_streams_is_refused_before_it_runs(
    beats, tmp_path, monkeypatch
):
    """Each -k is k empty chunks, so a hand-made -10**9 would build gigabytes.
    A call holding more heartbeats than one call can stream
    (replay.MAX_HEARTBEATS, its runs counted together) is refused before the
    case starts and before any chunk is built, naming the case and the call,
    never the text."""
    cassette = replay.load(FIXTURE)
    reply = cassette["calls"][1]["reply"]
    chunks = [-beats[0], len(reply), *(-k for k in beats[1:])]
    bad = _changed(cassette, _set("calls", 1, "chunks", chunks))
    _stop_at_rebuild(monkeypatch, refused=True)

    with pytest.raises(AssertionError) as caught:
        replay.run(bad, tmp_path, monkeypatch)

    message = str(caught.value)
    assert CASE in message and "calls[1]" in message
    leaked = any(line in message for line in reply.splitlines() if line.strip())
    assert not leaked, "the refusal quotes the reply"


def test_a_think_as_long_as_a_model_streams_is_not_refused(tmp_path, monkeypatch):
    """Beside the refusal: a think that spends Claude's whole output budget,
    one heartbeat per token (llm.CLAUDE_MAX_TOKENS), is a real model's. The
    replay starts the case and sends every heartbeat, then the reply."""
    cassette = replay.load(FIXTURE)
    reply = cassette["calls"][1]["reply"]
    think = llm.CLAUDE_MAX_TOKENS
    long = _changed(cassette, _set("calls", 1, "chunks", [-think, len(reply)]))
    _stop_at_rebuild(monkeypatch, refused=False)

    with pytest.raises(_Started):
        replay.run(long, tmp_path, monkeypatch)

    assert replay._recorded_chunks(long["calls"][1], 1) == [""] * think + [reply]


# --- the arm a replay runs ------------------------------------------------------


def test_the_replay_runs_the_arm_the_cassette_recorded(tmp_path):
    cassette = replay.load(FIXTURE)
    args = replay.arm_args(cassette, tmp_path)

    assert agent_run._arm_suffix(args) == cassette["arm"]["suffix"]
    assert args.docker is False
    assert args.max_events == cassette["arm"]["max_events"]
    assert args.wall_cap == cassette["arm"]["wall_cap"]
    assert args.human_gates == cassette["arm"]["human_gates"]
    assert args.policy_records == []


def test_a_recorded_abort_replays_with_the_event_cap_at_the_recorded_count(tmp_path):
    """A wall cap fired live at event 41. The replay cannot wait on a clock,
    so it caps events instead: `_drive` aborts on the event after max_events,
    which is event 41 again."""
    aborted = _changed(
        replay.load(FIXTURE),
        lambda c: c["outcome"].update(status="aborted: wall cap 300s hit", events=41),
    )
    args = replay.arm_args(aborted, tmp_path)

    assert args.max_events == 40
    assert math.isinf(args.wall_cap)


@pytest.mark.parametrize(
    "arm",
    [{"docker": True}, {"policies": "auto"}],
    # not "docker": conftest skips any test with that keyword when no daemon is up
    ids=["a sandboxed arm", "a policies arm that kept no policy records"],
)
def test_a_cassette_from_an_arm_replay_cannot_run_is_refused(tmp_path, arm):
    """A policies arm recorded before #233 kept no policy records, so there is
    nothing to rebuild them from (scout call 3: a missing field is the old
    behaviour). One that kept them replays, below."""
    cassette = _changed(replay.load(FIXTURE), lambda c: c["arm"].update(arm))
    with pytest.raises(AssertionError, match=CASE):
        replay.arm_args(cassette, tmp_path)


def test_a_policies_arm_replays_with_the_policy_records_it_kept(tmp_path):
    """#233: beside the refusal, the arm that kept its policy records replays,
    each rebuilt with PolicyRecord.from_dict, under the arm's own name."""
    record = _bench_auto()
    cassette = _changed(
        replay.load(FIXTURE),
        lambda c: c["arm"].update(
            policies="auto",
            suffix=".policies-auto",
            policy_records=[record.to_dict()],
        ),
    )

    try:
        args = replay.arm_args(cassette, tmp_path)
    except AssertionError as exc:
        pytest.fail(f"the replay refused a policies arm that kept its records: {exc}")

    assert args.policy_records == [record]
    assert agent_run._arm_suffix(args) == ".policies-auto"


_SECRET = "sentinel-233-quoted"  # absent from every refusal below
# a taxonomy disease with no registered fixer: a record naming it is refused
_UNFIXED = next(d for d in sorted(detect.SLUGS) if d not in agent_run.FIXERS)


def _kept(**changes) -> dict:
    """The --policies auto record as the arm keeps it, its id the sentinel."""
    return {**_bench_auto().to_dict(), "id": _SECRET, **changes}


# arm.policy_records as no recorder writes them; each is refused. The
# sentinel sits where the error from_dict raises would quote it
UNREBUILDABLE = {
    "a disease no registered fixer covers": [_kept(disease_ids=[_UNFIXED])],
    "a mode the engine does not have": [_kept(mode=_SECRET)],
    "an expiry that is not a date": [_kept(expires=_SECRET)],
    "a missing key": [{k: v for k, v in _kept().items() if k != "approver"}],
    "a record not in a list": _kept(),
    "an empty object": {},
}


@pytest.mark.parametrize("kept", UNREBUILDABLE)
def test_policy_records_that_no_longer_rebuild_are_refused_quoting_none(tmp_path, kept):
    """#233: a policies arm whose records no longer rebuild cannot run as
    recorded, so it is refused naming the case and quoting no record (a
    record that rebuilds replays, above)."""
    cassette = _changed(
        replay.load(FIXTURE),
        lambda c: c["arm"].update(
            policies="auto",
            suffix=".policies-auto",
            policy_records=copy.deepcopy(UNREBUILDABLE[kept]),
        ),
    )

    with pytest.raises(AssertionError) as caught:
        replay.arm_args(cassette, tmp_path)

    message = str(caught.value)
    assert CASE in message and "arm.policy_records" in message
    assert _SECRET not in message, "the refusal quotes a record"


def test_arm_env_sets_the_loop_flags_and_never_a_provider_or_a_key(monkeypatch):
    """#233: arm.env is read for agent_run.LOOP_FLAGS only. A cassette whose
    arm.env also holds a provider and every key variable leaves the replay on
    faux with no key set; the loop flag it holds is set as typed."""
    env = {var: _SECRET for var in llm.KEY_ENV_VARS}
    env.update(CRIVO_PROVIDER="claude", CRIVO_M1="off")
    cassette = _changed(replay.load(FIXTURE), _set("arm", "env", env))

    replay.offline_env(monkeypatch)
    replay.loop_env(cassette, monkeypatch)

    assert os.environ.get("CRIVO_PROVIDER") == "faux"
    assert [v for v in llm.KEY_ENV_VARS if v in os.environ] == ["CRIVO_PROVIDER"]
    assert _SECRET not in os.environ.values()
    assert os.environ.get("CRIVO_M1") == "off"
    assert "CRIVO_PLAN_FIRST" not in os.environ


# arm.env as no recorder writes it: a replay refuses each, naming the case.
# Only a missing arm.env or a null one is absent
BAD_ENV = {
    "a list": ["CRIVO_M1=off"],
    "a string": "CRIVO_M1=off",
    "an empty list": [],
    "an empty string": "",
    "zero": 0,
    "a flag set to false": {"CRIVO_M1": False},
    "a flag set to a number": {"CRIVO_M1": 0},
    "a flag set to a list": {"CRIVO_PLAN_FIRST": ["on"]},
}


@pytest.mark.parametrize("env", BAD_ENV)
def test_an_arm_env_no_recorder_writes_is_refused(monkeypatch, env):
    """#233: an arm.env that is there and not an object, or a flag that is
    neither a string nor null, is refused naming the case: an empty [] or ""
    is not read as a cassette that kept no flags."""
    cassette = _changed(replay.load(FIXTURE), _set("arm", "env", BAD_ENV[env]))

    with pytest.raises(AssertionError) as caught:
        replay.loop_env(cassette, monkeypatch)

    message = str(caught.value)
    assert CASE in message and "arm.env" in message


_UNSET = dict.fromkeys(agent_run.LOOP_FLAGS)
# beside the refusals: what arm.env may hold, and the flags it leaves set
GOOD_ENV = {
    "none kept (before #233)": (lambda c: c["arm"].pop("env", None), _UNSET),
    "null": (_set("arm", "env", None), _UNSET),
    "an empty object": (_set("arm", "env", {}), _UNSET),
    "one as typed, one null": (
        _set("arm", "env", {"CRIVO_M1": None, "CRIVO_PLAN_FIRST": "ON"}),
        {**_UNSET, "CRIVO_PLAN_FIRST": "ON"},
    ),
}


@pytest.mark.parametrize("env", GOOD_ENV)
def test_arm_env_sets_each_flag_as_recorded_and_unsets_the_rest(monkeypatch, env):
    """Beside the refusals: a missing, null or empty arm.env replays with
    every flag unset, whatever the shell held, and a kept flag is set as
    typed ("ON" stays "ON")."""
    change, expected = GOOD_ENV[env]
    cassette = _changed(replay.load(FIXTURE), change)
    for flag in agent_run.LOOP_FLAGS:
        monkeypatch.setenv(flag, "on")  # what the shell held

    replay.loop_env(cassette, monkeypatch)

    assert {flag: os.environ.get(flag) for flag in agent_run.LOOP_FLAGS} == expected


# --- the raw-row scan -------------------------------------------------------


@pytest.fixture(scope="module")
def dirty():
    entry = next(e for e in corpus.SMOKE if e["name"] == CASE)
    return corpus.build(entry)[1]


def _unique_rows(frame, column):
    """Rows whose `column` holds a value no other row has."""
    counts = frame[column].value_counts()
    return [i for i, v in enumerate(frame[column]) if counts[v] == 1]


def _rows_unique_in(frame, columns):
    """Rows whose value in each of `columns` no other row has."""
    rows = set(range(len(frame)))
    for column in columns:
        rows &= set(_unique_rows(frame, column))
    return sorted(rows)


def _one_row(frame):
    """A row whose id, account number and amount are each unique."""
    return _rows_unique_in(frame, ["txn_id", "account_no", "amount"])[0]


def _cells(frame, picks):
    return [str(frame.iloc[i][column]) for i, column in picks]


def _sentence(cells):
    return "Checked by hand: " + ", ".join(cells) + "."


def _in_reply(c, text):
    c["calls"][0]["reply"] += "\n" + text


def _in_status(c, text):
    c["outcome"]["status"] = f"error: ValueError: {text}"


def _in_error_message(c, text):
    c["calls"][1]["error"] = {"type": "RuntimeError", "message": text}


@pytest.mark.parametrize(
    "plant, path",
    [
        (_in_reply, "calls[0].reply"),
        (_in_status, "outcome.status"),
        (_in_error_message, "calls[1].error.message"),
    ],
)
def test_three_cells_of_a_rebuilt_row_fail_the_scan(dirty, plant, path):
    row = _one_row(dirty)
    cells = _cells(dirty, [(row, "txn_id"), (row, "account_no"), (row, "amount")])
    cassette = _changed(replay.load(FIXTURE), lambda c: plant(c, _sentence(cells)))

    problems = replay.scan(cassette, CASE)

    # the row is refused in the dirty frame, and in the pristine one too when
    # its cells came through the corruption unchanged
    dirty_hits = [p for p in problems if f"dirty row {row} " in p]
    assert len(dirty_hits) == 1, problems
    assert all(path in p for p in problems)
    assert "txn_id" in dirty_hits[0] and "account_no" in dirty_hits[0]
    leaked = any(cell in p for p in problems for cell in cells)
    assert not leaked, "the refusal quotes a cell it refused"


def _from_three_rows(frame):
    a, b, c = _rows_unique_in(frame, ["txn_id", "account_no", "amount"])[:3]
    return [(a, "txn_id"), (b, "account_no"), (c, "amount")]


def _two_of_one_row(frame):
    row = _one_row(frame)
    return [(row, "txn_id"), (row, "account_no")]


def _common_values_of_one_row(frame):
    row = next(i for i, note in enumerate(frame["notes"]) if note)
    picks = [(row, "merchant"), (row, "category"), (row, "notes")]
    for i, column in picks:
        common = (frame[column] == frame.iloc[i][column]).sum()
        assert common > 10, f"{column} at row {i} is not a common value"
    return picks


@pytest.mark.parametrize(
    "picks",
    [_from_three_rows, _two_of_one_row, _common_values_of_one_row],
    ids=["cells from three rows", "two cells of one row", "three common values"],
)
def test_what_is_not_a_row_passes_the_scan(dirty, picks):
    """Beside the refusal: a reply may name values, just not a row's worth of
    the ones that pick it out."""
    text = _sentence(_cells(dirty, picks(dirty)))
    cassette = _changed(replay.load(FIXTURE), lambda c: _in_reply(c, text))

    assert replay.scan(cassette, CASE) == []


@pytest.mark.parametrize(
    "path, field, as_digest",
    [
        (("calls", 0, "system_sha256"), "calls[0].system_sha256", True),
        (("calls", 0, "system_sha256"), "calls[0].system_sha256", False),
        (("crivo", "commit"), "crivo.commit", False),
        (("source", "note"), "source.note", False),
    ],
    ids=[
        "a real digest",
        "a row in calls[0].system_sha256",
        "a row in crivo.commit",
        "a row in source.note",
    ],
)
def test_a_digest_field_is_skipped_only_while_it_holds_a_digest(
    dirty, path, field, as_digest
):
    """A digest of a row is not the row, so a digest field is not scanned. A
    row written into one is, and so is anything in `source` but the corpus
    entry: a field's name is no promise about its value."""
    row = _one_row(dirty)
    cells = _cells(dirty, [(row, "txn_id"), (row, "account_no"), (row, "amount")])
    text = _sentence(cells)
    value = hashlib.sha256(text.encode()).hexdigest() if as_digest else text
    cassette = _changed(replay.load(FIXTURE), _set(*path, value))

    problems = replay.scan(cassette, CASE)

    if as_digest:
        assert problems == []
        return
    assert problems, "a row in a digest field passed the scan"
    assert all(field in p for p in problems)
    leaked = any(cell in p for p in problems for cell in cells)
    assert not leaked, "the refusal quotes a cell it refused"


# a members export: ids with leading zeros, a padded email, a sentinel, one
# shared billing address and an address the export cut short
MEMBERS = pd.DataFrame(
    {
        "member_id": ["00417", "00982", "01233", "02210", "03341", "03342", "04150"],
        "email": [
            "dana.okafor@northwind.example",
            " li.wei@contoso.example",
            "N/A",
            "billing@northwind.example",
            "billing@northwind.example",
            "billing@northwind.example",
            "j.moreau@fabrik",
        ],
        "plan": ["basic", "plus", "basic", "team", "team", "team", "basic"],
    }
)


@pytest.mark.parametrize(
    "quoted, refused",
    [
        ("dana.okafor@northwind.example", True),
        ("billing@northwind.example", True),
        ("j.moreau@fabrik", True),
        ("***@northwind.example", False),
        ("N/A", False),
    ],
    ids=[
        "the address",
        "an address in three rows",
        "an address cut short",
        "its masked form",
        "the column's sentinel",
    ],
)
def test_a_value_of_a_pii_flagged_column_fails_the_scan(quoted, refused):
    """No SMOKE base has a PII column, so the frames are passed in. One
    flagged value is enough to refuse when it is PII by itself (the shared
    address is, though three rows hold it) or would pick out its row (the cut
    address no longer reads as an address, but only one row has it). The
    masked form crivo shows and the column's "N/A" are neither, and pass."""
    pristine, dirty = MEMBERS, MEMBERS.copy()
    assert pii.flagged_columns(pristine, dirty) == {"email": "email"}
    assert pii.mask_value("dana.okafor@northwind.example", "email") == (
        "***@northwind.example"
    )
    cassette = _changed(
        replay.load(FIXTURE), lambda c: _in_reply(c, f"Wrote to {quoted} once.")
    )

    problems = replay.scan(cassette, CASE, frames=(pristine, dirty))

    if not refused:
        assert problems == []
        return
    assert problems, "a flagged value passed the scan"
    assert all("email-flagged column email" in p for p in problems)
    assert all("calls[0].reply" in p for p in problems)
    leaked = any(quoted in p for p in problems)
    assert not leaked, "the refusal quotes the value it refused"


@pytest.mark.parametrize(
    "change, refused",
    [
        (_set("source", "kind", "external"), True),
        (_set("source", "kind", "file"), True),
        (lambda c: c["source"]["entry"].update(name="vendor-export-2024"), True),
        (_set("source", "kind", "corpus"), False),
        (lambda c: None, False),
    ],
    ids=[
        "kind external",
        "kind file",
        "an entry not in the corpus",
        "corpus",
        "fixture",
    ],
)
def test_outside_data_fails_the_scan(change, refused):
    """D24: no outside data until a licence list exists. A corpus recording
    and a scripted fixture both rebuild from the corpus seed, and pass."""
    problems = replay.scan(_changed(replay.load(FIXTURE), change), CASE)

    if refused:
        assert len(problems) == 1, problems
        assert "source" in problems[0] and "D24" in problems[0]
    else:
        assert problems == []


def test_an_oversized_cassette_fails_the_scan():
    cassette = _changed(
        replay.load(FIXTURE), lambda c: _in_reply(c, "total = 0\n" * 25_000)
    )

    problems = replay.scan(cassette, CASE)

    assert len(problems) == 1, problems
    assert f"over the {replay.MAX_BYTES}-byte limit" in problems[0]
