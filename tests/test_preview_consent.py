"""#84: a model-written cell in a QUERY or fix gate never runs before approval.

A gate preview ran the model's cell, on scratch copies of the frames, before
the [r]un / re[j]ect prompt. The copies protect only the data: the cell itself
ran in the live kernel, so it could write the namespace or reach the shell
before anyone said yes. The QUERY gate and the fix gate carry model-written
cells, so they now wait for the answer. crivo's own code, a deterministic
fixer or an admitted skill, keeps the preview it had. A proposed skill is
model-written too: it waits for its own gate, before its test runs, and
tests/test_admission_consent.py checks that (#85).

The first test drives the real subprocess kernel, because what it checks is
what the kernel ran. The rest use the scripted fake kernel, which records
every cell it is sent. Previews stay on (the Session default) throughout.
"""

import sys

import pytest
from test_a1_m1_loop import fp
from test_clean_loop import (
    AFTER_APPROVAL,
    REG,
    FakeClient,
    baseline,
    case,
    diag,
    finding,
    gen,
    ok,
    saved,
)

from crivo import library, llm, skills, verify
from crivo.events import CardReady, GateDecision, GateRequest
from crivo.kernel.client import StreamOut
from crivo.loop import Session

SUBPROCESS_ARGV = [sys.executable, "-m", "crivo.kernel.supervisor"]
RUN = GateDecision("run")
REJECT = GateDecision("reject", "not like that")
SKIP = GateDecision("skip")


def drive(turn, decisions, at_gate):
    """Answer each gate from `decisions`, calling at_gate(gate) first: the
    moment a gate is on screen and nobody has answered it yet."""
    decisions = list(decisions)
    events = []
    try:
        event = next(turn)
        while True:
            events.append(event)
            answer = None
            if isinstance(event, GateRequest):
                at_gate(event)
                answer = decisions.pop(0)
            if isinstance(event, CardReady):
                return events
            event = turn.send(answer)
    except StopIteration:
        return events


# -- the real kernel ----------------------------------------------------------

# an order export: zero-padded ids kept as text, and a quantity column where
# 'N/A' stands in for a missing value (disease 4) in 12 of 32 rows
SEED = (
    "import pandas as pd\n"
    "orders = pd.DataFrame({\n"
    "    'order_id': [f'{i:05d}' for i in range(1, 33)],\n"
    "    'qty': ['N/A'] * 12 + [str(v) for v in range(3, 23)],\n"
    "})\n"
    "orders.shape"
)

# each cell first writes a marker into the live namespace, the way the probe
# that found #84 changed a live variable from inside a preview
FIX_WITH_MARKER = (
    "<execute>\n"
    "get_ipython().user_ns['_m84'] = 1\n"
    "def fix_sentinel_missing(df):\n"
    "    out = df.copy()\n"
    "    out['qty'] = out['qty'].replace('N/A', None)\n"
    "    return out\n"
    "orders = fix_sentinel_missing(orders)\n"
    "assert (orders['qty'] == 'N/A').sum() == 0\n"
    "</execute>"
)
QUERY_WITH_MARKER = (
    "<execute>\n"
    "get_ipython().user_ns['_m84'] = 1\n"
    "missing = int((orders['qty'] == 'N/A').sum())\n"
    "assert missing == 12\n"
    "missing\n"
    "</execute>"
)
ANSWER = "<answer>12 of the 32 orders have no quantity.</answer>"


def scripted(responses):
    queue = list(responses)

    def generate(messages, model=None):
        yield queue.pop(0) if queue else "<answer>done</answer>"

    return generate


@pytest.fixture
def orders(tmp_path, monkeypatch):
    # the legacy arm sends this AUTO finding to the model, which is the gate
    # under test; under M1 the deterministic fixer would take it first
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
    for ev in session.client.execute("'_m84' in get_ipython().user_ns", timeout_s=30):
        result = ev
    assert result.status == "ok", result.error
    return result.value == "True"


@pytest.mark.parametrize(
    "flow, replies, decisions, ran",
    [
        ("fix", [FIX_WITH_MARKER], [RUN], True),
        ("fix", [FIX_WITH_MARKER, FIX_WITH_MARKER], [REJECT, SKIP], False),
        ("query", [QUERY_WITH_MARKER, ANSWER], [RUN], True),
        ("query", [QUERY_WITH_MARKER, QUERY_WITH_MARKER], [REJECT, SKIP], False),
    ],
    ids=["fix-approved", "fix-rejected", "query-approved", "query-rejected"],
)
def test_a_model_cell_never_runs_before_its_gate_is_approved(
    orders, monkeypatch, flow, replies, decisions, ran
):
    """Regression for #84. A model cell that writes a marker into the live
    kernel namespace had written it by the time its gate was on screen,
    because the preview ran the cell first. The marker is absent at every
    gate, present once the gate is approved, and still absent after a
    rejection."""
    monkeypatch.setattr(llm, "generate", scripted(replies))
    turn = (
        orders.clean("orders")
        if flow == "fix"
        else orders.run_turn("how many orders have no quantity?")
    )
    at_gates: list[bool] = []
    drive(turn, decisions, at_gate=lambda gate: at_gates.append(marker_set(orders)))

    assert at_gates == [False] * len(decisions), (
        "the model's cell ran before its gate was answered"
    )
    assert marker_set(orders) is ran


# -- the recording fake kernel ------------------------------------------------

MARK = "echo m84"
SHELL_FIX = (
    "<execute>def fix_sentinel_missing(df):\n"
    "    out = df.copy()\n"
    "    out['a'] = out['a'].replace(-999, None)\n"
    "    return out\n"
    f"get_ipython().system('{MARK}')\n"
    "df = fix_sentinel_missing(df)\n"
    "assert df['a'].min() != -999</execute>"
)
SHELL_QUERY = (
    f"<execute>get_ipython().system('{MARK}')\n"
    "sentinels = int((df['a'] == -999).sum())\n"
    "assert sentinels == 2\n"
    "sentinels</execute>"
)


class RecordingClient(FakeClient):
    """The scripted fake kernel, answering ok() once its script runs out, so a
    cell the flow should never have sent is recorded instead of crashing the
    script before the gate can be checked."""

    def execute(self, code, timeout_s=120):
        FakeClient.executed.append(code)
        yield from (FakeClient.script.pop(0) if FakeClient.script else [ok()])


@pytest.fixture
def make_session(tmp_path, monkeypatch):
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


def sent_from_the_cell():
    return [c for c in FakeClient.executed if MARK in c]


GATE_FINDING = finding(grade="GATE")


@pytest.mark.parametrize(
    "flow, replies, script, decisions, ran",
    [
        (
            "fix",
            [SHELL_FIX],
            [
                diag([GATE_FINDING]),
                baseline(),
                fp("AAA"),  # pre-fix fingerprint
                [ok()],  # the fix, once approved
                fp("BBB"),  # it changed the frame
                [ok()],  # verify
                case(),
                baseline(),
                saved(),
            ],
            [RUN],
            True,
        ),
        (
            "fix",
            [SHELL_FIX, SHELL_FIX],
            [diag([GATE_FINDING]), baseline(), fp("AAA")],
            [REJECT, SKIP],
            False,
        ),
        ("query", [SHELL_QUERY, "<answer>2</answer>"], [[ok(value="2")]], [RUN], True),
        ("query", [SHELL_QUERY, SHELL_QUERY], [], [REJECT, SKIP], False),
    ],
    ids=["fix-approved", "fix-rejected", "query-approved", "query-rejected"],
)
def test_nothing_from_a_model_cell_reaches_the_kernel_before_approval(
    make_session, monkeypatch, flow, replies, script, decisions, ran
):
    """Regression for #84. A cell calling get_ipython().system(...) passes
    preview_screen, so the preview sent it to the kernel, shell call and all,
    before the gate was answered. At every gate nothing carrying the cell has
    been sent; once approved, the cell is sent once, as the gate showed it;
    after a rejection it is never sent. The gate says why there is no
    preview."""
    monkeypatch.delenv("CRIVO_M1", raising=False)
    session = make_session()
    monkeypatch.setattr(llm, "generate", gen(replies))
    FakeClient.script = list(script)
    turn = (
        session.clean("df")
        if flow == "fix"
        else session.run_turn("how many sentinels are in a?")
    )

    def nothing_sent_yet(gate):
        sent = sent_from_the_cell()
        assert not sent, (
            f"{len(sent)} kernel cell(s) carried the model's code before "
            "its gate was answered"
        )

    events = drive(turn, decisions, at_gate=nothing_sent_yet)

    gates = [e for e in events if isinstance(e, GateRequest)]
    assert [g.preview for g in gates] == [AFTER_APPROVAL] * len(decisions)
    assert sent_from_the_cell() == ([gates[0].code] if ran else [])


# -- crivo's own code keeps its preview --------------------------------------


def test_a_deterministic_fixers_gate_keeps_the_preview_it_had(
    make_session, monkeypatch
):
    """Regression for #84. The legitimate case beside the refusal: the
    autoclean gate runs crivo's own fixer, so it keeps the
    screen-then-scratch-copy path rather than the no-preview line. Today that
    path stops at the screen, because the apply cell imports crivo, so the
    screen's line is the preview this gate gets, and it must stay that."""
    monkeypatch.delenv("CRIVO_M1", raising=False)
    monkeypatch.setattr(llm, "generate", gen([]))
    session = make_session(autonomy="careful")
    FakeClient.script = [
        diag([finding()]),  # d4, AUTO, a registered fixer
        baseline(),
        [ok()],  # the apply cell, once approved
        [ok()],  # verify
        baseline(),
        saved(),
    ]
    gates: list[GateRequest] = []
    drive(session.clean("df"), [RUN], at_gate=gates.append)

    (gate,) = gates
    assert gate.title.startswith("autoclean")
    assert gate.preview == f"(preview skipped: {verify.preview_screen(gate.code)})"


def test_an_admitted_skills_gate_still_previews_on_a_scratch_copy(
    make_session, tmp_path, monkeypatch
):
    """Regression for #84. The other half of crivo's own code: a skill
    admitted to the library, gated while on probation, still shows the
    consequence computed on a scratch copy before it is answered."""
    monkeypatch.setenv("CRIVO_M1", "off")  # the library comes first here
    monkeypatch.setattr(llm, "generate", gen([]))
    root = tmp_path / "skills"
    skills.save(
        skills.Skill(
            name="fix-sentinel-missing",
            description="Replace sentinel tokens with NaN when a column holds -999.",
            fix_source="def fix(df, columns):\n    return df.copy()\n",
            test_source="def test_fix():\n    assert True\n",
            metadata={"disease": "4"},
        ),
        root,
    )
    session = make_session()
    session.library = library.Library(root=root)
    session.library.register("fix-sentinel-missing", disease=4)
    FakeClient.script = [
        diag([finding()]),
        baseline(),
        [StreamOut("stdout", "a: 2 of 4 cells change\n"), ok()],  # the preview
        [ok()],  # the skill's fix, once approved
        [ok()],  # verify
        baseline(),
        saved(),
    ]
    gates: list[GateRequest] = []
    drive(session.clean("df"), [RUN], at_gate=gates.append)

    (gate,) = gates
    assert "probation" in gate.title
    assert "2 of 4 cells change" in gate.preview
