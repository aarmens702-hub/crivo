"""#85: a proposed skill's code runs only after a person says yes to its test.

After a model fix verifies, the model generalises it into a skill, and
admission ran the proposed fix and its shipped test in the live kernel (the
case is a copy; the code is not contained) before the admission gate was on
screen. So model-written code ran with nobody asked. A first gate now comes
before that: "test skill ..." shows the proposed fix and test verbatim, graded
HUMAN, with the #84 no-preview line. Run there runs the admission checks and
then the admission gate as before; reject sends a note back for one revision;
skip, or no answer, discards the skill with nothing run.

The first test drives the real subprocess kernel, because what it checks is
what the kernel ran. The rest use the recording fake kernel, which keeps every
cell it is sent.
"""

import json
import sys

import pytest
from test_a1_m1_loop import fp
from test_clean_loop import (
    AFTER_APPROVAL,
    FIX_A,
    REG,
    FakeClient,
    baseline,
    case,
    counting_generate,
    diag,
    err,
    finding,
    ok,
    report_of,
)
from test_preview_consent import SEED, RecordingClient

from crivo import llm
from crivo.events import CardReady, GateDecision, GateRequest
from crivo.kernel.client import StreamOut
from crivo.loop import SKILL_MAX_ATTEMPTS, Session

SUBPROCESS_ARGV = [sys.executable, "-m", "crivo.kernel.supervisor"]
TEST_GATE = "test skill "
ADMIT_GATE = "admit skill "
RUN = GateDecision("run")
SKIP = GateDecision("skip")
NOTE = "the test never checks that a real value survives"
REJECT = GateDecision("reject", NOTE)


def drive(turn, decisions, at_gate=lambda gate: None):
    """Answer each gate from `decisions`, skipping once they run out, and call
    at_gate(gate) first: the moment a gate is on screen, unanswered."""
    decisions = list(decisions)
    events = []
    try:
        event = next(turn)
        while True:
            events.append(event)
            answer = None
            if isinstance(event, GateRequest):
                at_gate(event)
                answer = decisions.pop(0) if decisions else SKIP
            if isinstance(event, CardReady):
                return events
            event = turn.send(answer)
    except StopIteration:
        return events


def through_the_test_gate(seen):
    """What was recorded at each gate up to and including the first test gate.
    With no test gate, every gate: then nothing asked before the proposed
    skill's code ran."""
    end = next(
        (i for i, (title, _) in enumerate(seen) if title.startswith(TEST_GATE)),
        len(seen) - 1,
    )
    return seen[: end + 1]


# -- the real kernel ----------------------------------------------------------

# SEED is the #84 order export: zero-padded ids kept as text, and 'N/A'
# standing in for a missing quantity (disease 4) in 12 of 32 rows
FIX_ORDERS = (
    "<execute>\n"
    "def fix_sentinel_missing(df):\n"
    "    out = df.copy()\n"
    "    out['qty'] = out['qty'].replace('N/A', None)\n"
    "    return out\n"
    "orders = fix_sentinel_missing(orders)\n"
    "assert (orders['qty'] == 'N/A').sum() == 0\n"
    "</execute>"
)

# a faithful generalisation that also writes a marker into the live namespace
# at module level, which validate allows beside fix(df, columns)
MARKED_PROPOSAL = (
    "<name>fix-sentinel-missing</name>\n"
    "<description>Replace missing-data tokens with NaN. Use when a column "
    "holds 'N/A' standing in for a value nobody recorded.</description>\n"
    "<fix>\n"
    "get_ipython().user_ns['_m85'] = 1\n"
    "def fix(df, columns):\n"
    "    out = df.copy()\n"
    "    for c in columns:\n"
    "        if c in out.columns:\n"
    "            out[c] = out[c].replace(['N/A', 'n/a'], None)\n"
    "    return out\n"
    "</fix>\n"
    "<test>\n"
    "import pandas as pd\n"
    "def test_fix_blanks_the_token_and_keeps_the_quantity():\n"
    "    out = fix(pd.DataFrame({'qty': ['N/A', '7', 'n/a']}), ['qty'])\n"
    "    assert out['qty'].isna().sum() == 2\n"
    "    assert out['qty'].iloc[1] == '7'\n"
    "</test>"
)


def scripted(responses):
    queue = list(responses)

    def generate(messages, model=None):
        yield queue.pop(0) if queue else "<answer>done</answer>"

    return generate


@pytest.fixture
def orders(tmp_path, monkeypatch):
    # the legacy arm sends this AUTO finding to the model, whose verified fix
    # is what a skill is proposed from; under M1 the fixer would take it
    monkeypatch.setenv("CRIVO_M1", "off")
    session = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
    )
    result = None
    for ev in session.client.execute(SEED, timeout_s=60):
        result = ev
    assert result.status == "ok", result.error
    session._stamp_registry(result.registry, 1)
    yield session
    session.close()


def marker_set(session) -> bool:
    result = None
    for ev in session.client.execute("'_m85' in get_ipython().user_ns", timeout_s=30):
        result = ev
    assert result.status == "ok", result.error
    return result.value == "True"


@pytest.mark.parametrize(
    "replies, decisions, ran",
    [
        ([FIX_ORDERS, MARKED_PROPOSAL], [RUN, RUN, RUN], True),
        ([FIX_ORDERS, MARKED_PROPOSAL], [RUN, SKIP], False),
        ([FIX_ORDERS, MARKED_PROPOSAL, MARKED_PROPOSAL], [RUN, REJECT, SKIP], False),
    ],
    ids=["tested", "skipped", "rejected"],
)
def test_a_proposed_skills_code_never_runs_before_its_test_gate(
    orders, monkeypatch, replies, decisions, ran
):
    """Regression for #85. A proposed skill whose fix writes a marker into the
    live kernel namespace had written it by the time any gate about the skill
    was on screen, because admission ran the fix first. The marker is absent
    at the test gate, still absent after a skip or a rejection, and present
    only once the test gate is answered run."""
    monkeypatch.setattr(llm, "generate", scripted(replies))
    seen: list[tuple[str, bool]] = []
    drive(
        orders.clean("orders"),
        decisions,
        at_gate=lambda gate: seen.append((gate.title, marker_set(orders))),
    )

    assert not any(marked for _, marked in through_the_test_gate(seen)), (
        "the proposed skill's code ran before its test gate was answered"
    )
    titles = [title for title, _ in seen]
    assert any(t.startswith(TEST_GATE) for t in titles), titles
    assert marker_set(orders) is ran


# -- the recording fake kernel ------------------------------------------------

NAME = "fix-sentinel-missing"
DESCRIPTION = (
    "Replace sentinel codes with NaN. Use when a column holds -999 or 'N/A' "
    "standing in for a missing value."
)
# what a cell carries when it carries the proposed fix, or the proposed test
# (skill_test_cell JSON-quotes the test, so its function name is the mark)
FIX_LINE = "out[c] = out[c].replace([-999, 'N/A'], None)"
TEST_FN = "test_fix_blanks_every_sentinel"
FIX_SRC = (
    "def fix(df, columns):\n"
    "    out = df.copy()\n"
    "    for c in columns:\n"
    "        if c in out.columns:\n"
    f"            {FIX_LINE}\n"
    "    return out"
)
TEST_SRC = (
    "import pandas as pd\n"
    f"def {TEST_FN}():\n"
    "    out = fix(pd.DataFrame({'a': [-999, 'N/A', 12]}), ['a'])\n"
    "    assert out['a'].isna().sum() == 2"
)
REVISED_LINE = "    assert out['a'].iloc[2] == 12"


def proposal(test_src=TEST_SRC, fix_src=FIX_SRC):
    return (
        f"<name>{NAME}</name>\n<description>{DESCRIPTION}</description>\n"
        f"<fix>\n{fix_src}\n</fix>\n<test>\n{test_src}\n</test>"
    )


PROPOSAL = proposal()
# the model's revision after the note: the same fix, a test that checks more
REVISED = proposal(TEST_SRC + "\n" + REVISED_LINE)
# the model's revision after its checks failed: a fix of its own, which also
# blanks the -998 code beside -999
REVISED_FIX_LINE = "out[c] = out[c].replace([-999, -998, 'N/A'], None)"
REVISED_FIX = proposal(fix_src=FIX_SRC.replace(FIX_LINE, REVISED_FIX_LINE))

# a GATE finding, so under M1 the model fixes it rather than the fixer, then
# the case its verified fix came from is frozen for the skill to reproduce
FIX_SCRIPT = [
    diag([finding(grade="GATE")]),
    baseline(),
    fp("AAA"),  # pre-fix fingerprint
    [ok()],  # the model's fix, once approved
    fp("BBB"),  # it changed the frame
    [ok()],  # verify
    case(),
    baseline(),  # refresh after fixed; the recording kernel answers ok() after
]


@pytest.fixture
def make_session(tmp_path, monkeypatch):
    monkeypatch.delenv("CRIVO_M1", raising=False)
    monkeypatch.delenv("CRIVO_PLAN_FIRST", raising=False)
    monkeypatch.setattr("crivo.loop.KernelClient", RecordingClient)
    FakeClient.script, FakeClient.executed = [], []

    def make(**kw):
        s = Session(
            workspace=tmp_path / "ws",
            data_dir=tmp_path,
            skills_dir=tmp_path / "skills",
            snapshots=False,
            **kw,
        )
        s._registry_prev = {"df": ("DataFrame", "[4, 2]")}
        s._registry = list(REG)
        s.datasets.append(
            {
                "path": "data/x.csv",
                "sha256": "abc123",
                "variable": "df",
                "loaded_event": 2,
            }
        )
        return s

    return make


def carrying_the_skill():
    """Every cell sent to the kernel that carries the proposed fix or test."""
    return [c for c in FakeClient.executed if FIX_LINE in c or TEST_FN in c]


def proposing(make_session, monkeypatch, replies):
    """A session whose model fixes the finding, then proposes from `replies`."""
    stub = counting_generate([FIX_A, *replies])
    monkeypatch.setattr(llm, "generate", stub)
    session = make_session()
    FakeClient.script = list(FIX_SCRIPT)
    return session, stub


def gates_of(events):
    return [e for e in events if isinstance(e, GateRequest)]


@pytest.mark.parametrize(
    "decisions, ran",
    [([RUN, RUN, RUN], True), ([RUN, SKIP], False), ([RUN, None], False)],
    ids=["run", "skip", "no-answer"],
)
def test_no_cell_carrying_a_proposed_skill_is_sent_before_its_test_gate(
    make_session, monkeypatch, decisions, ran
):
    """Regression for #85. The admission cell and the skill-test cell carry the
    proposed fix, and the second the proposed test, and both were sent before
    any gate about the skill. Nothing carrying either is sent until the test
    gate is answered; after run it is, after skip or no answer it never is."""
    session, _ = proposing(make_session, monkeypatch, [PROPOSAL])
    seen: list[tuple[str, int]] = []
    drive(
        session.clean("df"),
        decisions,
        at_gate=lambda gate: seen.append((gate.title, len(carrying_the_skill()))),
    )

    sent = [n for _, n in through_the_test_gate(seen)]
    assert sent == [0] * len(sent), (
        "a cell carrying the proposed skill reached the kernel before its "
        "test gate was answered"
    )
    titles = [title for title, _ in seen]
    assert any(t.startswith(TEST_GATE) for t in titles), titles
    assert bool(carrying_the_skill()) is ran


@pytest.mark.parametrize("answer", [SKIP, None], ids=["skip", "no-answer"])
def test_a_skill_not_run_at_its_test_gate_is_discarded(
    make_session, monkeypatch, answer
):
    """Regression for #85. A skip at the test gate, or anything that is not a
    GateDecision, discards the skill: no admission gate follows, and nothing
    reaches the library."""
    session, _ = proposing(make_session, monkeypatch, [PROPOSAL])
    events = drive(session.clean("df"), [RUN, answer])

    titles = [g.title for g in gates_of(events)]
    assert not [t for t in titles if t.startswith(ADMIT_GATE)], titles
    assert report_of(session)["skills_admitted"] == []
    assert not (session.skills_dir / NAME).exists()
    assert session.library.entries == {}


def test_the_test_gate_shows_the_proposed_skill_verbatim(make_session, monkeypatch):
    """Regression for #85. The person deciding whether the code runs sees all
    of it: the proposed fix and test as written, under the skill's name and
    description as comments. It is HUMAN-graded, carries the #84 line in place
    of a preview, and is titled as a test, not as an admission or a fix. It
    never claims the code is contained: only the case is a copy."""
    session, _ = proposing(make_session, monkeypatch, [PROPOSAL])
    events = drive(session.clean("df"), [RUN, SKIP])

    gates = gates_of(events)
    tested = [g for g in gates if g.title.startswith(TEST_GATE)]
    assert len(tested) == 1, [g.title for g in gates]
    (gate,) = tested
    assert FIX_SRC in gate.code
    assert TEST_SRC in gate.code
    lines = gate.code.splitlines()
    assert f"# {NAME}" in lines
    assert f"# {DESCRIPTION}" in lines
    assert gate.grade == "HUMAN"
    assert gate.preview == AFTER_APPROVAL
    for claim in ("isolat", "sandbox"):
        assert claim not in gate.title.lower()


def test_a_rejected_skill_goes_back_to_the_model_unrun(make_session, monkeypatch):
    """Regression for #85. A rejection at the test gate sends its note back
    for a revision, and the revision is shown at a test gate of its own. The
    attempts stop at SKILL_MAX_ATTEMPTS, and through all of them nothing
    carrying either proposal reaches the kernel."""
    replies = [PROPOSAL] + [REVISED] * (SKILL_MAX_ATTEMPTS - 1)
    session, stub = proposing(make_session, monkeypatch, replies)
    events = drive(session.clean("df"), [RUN] + [REJECT] * SKILL_MAX_ATTEMPTS)

    gates = gates_of(events)
    tested = [g for g in gates if g.title.startswith(TEST_GATE)]
    assert len(tested) == SKILL_MAX_ATTEMPTS, [g.title for g in gates]
    assert REVISED_LINE in tested[-1].code, "the revision is what is shown"
    assert NOTE in json.dumps(stub.calls[2]), "the revision read the note"
    assert len(stub.calls) == 1 + SKILL_MAX_ATTEMPTS, "the fix, then each attempt"
    assert carrying_the_skill() == []
    assert report_of(session)["skills_admitted"] == []


def test_a_revision_after_failed_checks_waits_for_its_own_test_gate(
    make_session, monkeypatch
):
    """Regression for #85. The one path with an earlier yes: a person runs the
    first proposal's checks, they fail, and the model sends a revision with a
    fix of its own. That yes was for the code it was shown, so the revision
    gets a test gate of its own, and a skip there leaves its fix unsent and
    nothing admitted."""
    session, _ = proposing(make_session, monkeypatch, [PROPOSAL, REVISED_FIX])
    FakeClient.script.append(
        # the first proposal's admission cell: the checks fail, _admit refuses
        [err("the frozen case no longer trips the detector")]
    )
    events = drive(session.clean("df"), [RUN, RUN, SKIP])

    gates = gates_of(events)
    tested = [g for g in gates if g.title.startswith(TEST_GATE)]
    assert len(tested) == 2, [g.title for g in gates]
    assert any(FIX_LINE in c for c in FakeClient.executed), (
        "the first proposal's checks ran once a person said yes"
    )
    assert REVISED_FIX_LINE in tested[1].code, "the revision is what is shown"
    assert not [c for c in FakeClient.executed if REVISED_FIX_LINE in c], (
        "the revised fix reached the kernel without a yes of its own"
    )
    assert report_of(session)["skills_admitted"] == []


def test_a_skill_whose_test_a_person_ran_is_admitted(make_session, monkeypatch):
    """Regression for #85. The legitimate path beside the new refusal: run at
    the test gate sends the admission checks, the admission gate follows them,
    and run there admits the skill on probation."""
    session, _ = proposing(make_session, monkeypatch, [PROPOSAL])
    seen: list[tuple[str, int]] = []
    drive(
        session.clean("df"),
        [RUN, RUN, RUN],
        at_gate=lambda gate: seen.append((gate.title, len(carrying_the_skill()))),
    )

    skill_gates = [(t, n) for t, n in seen if t.startswith((TEST_GATE, ADMIT_GATE))]
    assert [t.startswith(TEST_GATE) for t, _ in skill_gates] == [True, False], (
        "the test gate, then the admission gate"
    )
    assert [n > 0 for _, n in skill_gates] == [False, True], (
        "the checks run between the two gates"
    )
    assert report_of(session)["skills_admitted"] == [NAME]
    assert (session.skills_dir / NAME).is_dir()
    assert session.library.entries[NAME]["state"] == "probation"


def test_headless_clean_discards_a_proposed_skill_unrun(
    make_session, monkeypatch, tmp_path
):
    """Regression for #85. run_clean_once answers by grade and skips every
    HUMAN gate, so headless the proposed skill is discarded before any of its
    code runs, and needs_human names the test gate for a person. The verified
    fix the skill came from stands."""
    from crivo.repl import run_clean_once

    # the legacy arm sends the AUTO finding to the model, and the fix gate
    # carries AUTO, which run_clean_once runs, so the skill pass is reached
    monkeypatch.setenv("CRIVO_M1", "off")
    stub = counting_generate([FIX_A, PROPOSAL])
    monkeypatch.setattr(llm, "generate", stub)
    csv = tmp_path / "orders.csv"
    csv.write_text("order_id,a\n00017,-999\n00018,12\n00019,-999\n00020,7\n")
    session = make_session()
    FakeClient.script = [
        [StreamOut("stdout", "profile\n"), ok()],  # the load cell
        diag([finding()]),  # d4, AUTO
        baseline(),
        [ok()],  # the model's fix
        [ok()],  # verify
        case(),
        baseline(),
    ]
    summary = run_clean_once(session, str(csv), name="df")

    asked = summary["needs_human"]
    assert [t for t in asked if t.startswith(TEST_GATE)], asked
    assert not [t for t in asked if t.startswith(ADMIT_GATE)], asked
    assert carrying_the_skill() == []
    assert summary["skills_admitted"] == []
    assert [f["status"] for f in summary["fixes"]] == ["fixed"]
