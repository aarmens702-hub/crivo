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

import pandas as pd
import pytest

from bench import agent_run, corpus
from crivo import llm, pii
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
    does not have still reaches the provider and is counted."""
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

    def provider(messages, model=None):
        yield "from the provider"

    asked: list = []
    generate = replay._replaying_generate(provider, recorded, asked)

    assert list(generate([])) == ["from the provider"]
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


@pytest.mark.parametrize("arm", [{"docker": True}, {"policies": "auto"}])
def test_a_cassette_from_an_arm_replay_cannot_run_is_refused(tmp_path, arm):
    cassette = _changed(replay.load(FIXTURE), lambda c: c["arm"].update(arm))
    with pytest.raises(AssertionError, match=CASE):
        replay.arm_args(cassette, tmp_path)


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
