"""MCP wrapper tests (specs/2026-08-14-mcp-wrapper-design.md).

The server is a driver, like repl.py: logic lives in plain module functions
tested here against SessionLike doubles, with the FastMCP registration a thin
layer over them. One real-kernel test (AC2) proves the session tools against
the actual subprocess kernel; everything else uses doubles, in the style of
tests/test_repl.py.
"""

import json
import pathlib

import pandas as pd

from crivo import mcp_server


def test_diagnose_file_is_keyless_and_returns_json(tmp_path, monkeypatch) -> None:
    """The try-before-trust property must survive the wrapper: a stranger's
    agent can diagnose with no API key configured at all."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(tmp_path))  # the fixture file is served
    path = tmp_path / "beers.csv"
    pd.DataFrame({"ibu": ["N/A"] * 8 + [str(v) for v in range(20)]}).to_csv(
        path, index=False
    )

    report = json.loads(mcp_server._diagnose_file(str(path)))

    assert any(f["slug"] == "sentinel-missing" for f in report["findings"])
    assert "clear" in report


def test_key_needing_tools_name_the_missing_key(monkeypatch) -> None:
    """R5: the error must name the key the configured provider actually uses,
    so the person fixing their MCP client config knows which env var to add."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    assert "DEEPSEEK_API_KEY" in mcp_server._clean_file("x.csv")["error"]

    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    assert "ANTHROPIC_API_KEY" in mcp_server._clean_file("x.csv")["error"]


def test_required_key_is_per_provider(monkeypatch) -> None:
    """BP3: the model tools ask each provider for what it needs and nothing
    else. faux needs nothing; openai (Ollama, vLLM, OpenRouter) needs an
    endpoint and a model, not a DeepSeek key; claude needs its own key; a
    misspelled provider is refused instead of routed to DeepSeek; an empty
    CRIVO_PROVIDER, as .env.example ships it, is deepseek."""
    cases = [
        ({"CRIVO_PROVIDER": "faux"}, None),
        (
            {
                "CRIVO_PROVIDER": "openai",
                "CRIVO_BASE_URL": "http://localhost:11434/v1",
                "CRIVO_MODEL": "qwen3:32b",
            },
            None,
        ),
        (
            {"CRIVO_PROVIDER": "openai", "CRIVO_BASE_URL": "http://localhost:11434/v1"},
            "CRIVO_MODEL",
        ),
        (
            {"CRIVO_PROVIDER": "claude", "DEEPSEEK_API_KEY": "sk-test"},
            "ANTHROPIC_API_KEY",
        ),
        (
            {
                "CRIVO_PROVIDER": "Claude",
                "DEEPSEEK_API_KEY": "sk-test",
                "ANTHROPIC_API_KEY": "sk-ant-test",
            },
            "deepseek, claude, openai, faux",
        ),
        ({"CRIVO_PROVIDER": "", "DEEPSEEK_API_KEY": "sk-test"}, None),
    ]
    wrong = []
    for env, expected in cases:
        with monkeypatch.context() as m:
            for var, value in env.items():
                m.setenv(var, value)
            message = mcp_server._required_key()
        if expected is None:
            ok = message is None
        else:
            ok = message is not None and expected in message
        if not ok:
            wrong.append({"env": env, "want": expected, "got": message})
    assert not wrong, wrong


class FakeSession:
    """SessionLike double in the tests/test_repl.py style: scripted event
    generators, recorded decisions, and just enough surface for the server."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.sent = []
        self.datasets = []
        self.history = []
        self.closed = False
        self.session_dir = None

    def load(self, path, name=None):
        variable = name or "df"
        self.datasets.append({"path": path, "variable": variable})
        self.history.append(
            {
                "role": "user",
                "content": f"<dataset variable={variable!r}>\nrows\n</dataset>",
            }
        )

    def run_turn(self, question):
        for event in self.script:
            self.sent.append((yield event))

    def clean(self, var):
        for event in self.script:
            self.sent.append((yield event))

    def close(self):
        self.closed = True


def test_clean_file_relays_needs_human_and_closes_the_session(monkeypatch) -> None:
    """AC1: the wrapper must not swallow the one thing the grade rule exists
    to surface — the judgement calls it refused to make — and must never leak
    a kernel, success or not. Since #30 the summary echoes no policy."""
    from crivo.events import GateRequest

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    fake = FakeSession(
        script=[
            GateRequest("fix_a", 1, title="fix 1/2 · strip spaces", grade="AUTO"),
            GateRequest("fix_b", 1, title="fix 2/2 · merge variants", grade="GATE"),
        ]
    )
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)

    summary = mcp_server._clean_file("data/x.csv")

    assert [d.action for d in fake.sent if d is not None] == ["run", "skip"]
    assert summary["needs_human"] == ["fix 2/2 · merge variants"]
    assert "policy" not in summary, sorted(summary)
    assert fake.closed, "the kernel must be closed, success or not"


def test_ask_runs_query_cells_and_returns_the_card(monkeypatch) -> None:
    """AC1: the session tools. open_data registers a persistent session and
    hands back its profile; ask drives run_turn with the calling agent as the
    operator for the analyst's own query cells (grade "", the --auto-run trust
    position) and returns the card as a dict with its executed checks. Gates
    carrying a person's grade are a different matter, tested below."""
    from crivo.card import AnswerCard
    from crivo.events import CardReady, GateRequest

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    card = AnswerCard(
        card_id="c001",
        session="s01",
        question="how many rows?",
        answer="two rows",
        checks=[{"expr": "result == 2", "passed": True}],
    )
    fake = FakeSession(script=[GateRequest("result = 2", 1), CardReady(card)])
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)

    opened = mcp_server._open_data("data/tiny.csv")
    assert opened["variable"] == "df"
    assert "<dataset" in opened["profile"]

    result = mcp_server._ask(opened["session_id"], "how many rows?")

    assert result["answer"] == "two rows"
    assert result["checks"] == [{"expr": "result == 2", "passed": True}]
    assert [d.action for d in fake.sent if d is not None] == ["run"]
    assert not fake.closed, "the session stays open for the next question"
    mcp_server.close_all()


def test_ask_on_an_unknown_session_says_what_to_do(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)

    result = mcp_server._ask("nope1234", "anything")

    assert "unknown session" in result["error"]
    assert "open_data" in result["error"], "the fix must be named, not implied"


def test_idle_sessions_are_evicted_and_their_kernels_closed(monkeypatch) -> None:
    """R4: an abandoned kernel is a leaked process. Eviction happens on the
    next lookup, and the evicted session's kernel is actually closed."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    fake = FakeSession()
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)
    opened = mcp_server._open_data("data/tiny.csv")

    import time as real_time

    later = real_time.monotonic() + mcp_server.IDLE_S + 1
    monkeypatch.setattr("time.monotonic", lambda: later)

    result = mcp_server._ask(opened["session_id"], "still there?")

    assert "unknown session" in result["error"]
    assert fake.closed, "eviction must close the kernel, not just forget it"


def test_why_and_close_session_round_trip(monkeypatch, tmp_path) -> None:
    """R3: why renders the provenance chain from the session's dir on disk;
    close_session is idempotent-honest — True once, False after."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    fake = FakeSession()
    fake.session_dir = tmp_path
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)
    opened = mcp_server._open_data("data/tiny.csv")

    rendered = mcp_server._why(opened["session_id"])
    assert isinstance(rendered, str) and not rendered.startswith("error")

    assert mcp_server._close_session(opened["session_id"]) is True
    assert fake.closed
    assert mcp_server._close_session(opened["session_id"]) is False


def test_a_crashing_tool_returns_an_error_result_not_a_protocol_crash(
    monkeypatch,
) -> None:
    """R6: one bad file, one broken kernel start — the server answers with an
    error result; it never dies mid-protocol."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)

    def explode():
        raise RuntimeError("kernel refused to start")

    monkeypatch.setattr(mcp_server, "_make_session", explode)

    assert mcp_server._clean_file("x.csv")["error"].startswith("RuntimeError")
    assert mcp_server._open_data("x.csv")["error"].startswith("RuntimeError")


def test_the_server_exposes_exactly_the_six_tools_with_docstrings() -> None:
    """AC3: the six-tool inventory is the contract, and each docstring is
    what a calling model acts on — clean_file's must say there is no way to
    relay a person's consent through it, because that sentence is what stands
    between an eager agent and unattended judgement calls."""
    import asyncio

    app = mcp_server.build_server()
    tools = {t.name: t for t in asyncio.run(app.list_tools())}

    assert set(tools) == {
        "diagnose_file",
        "clean_file",
        "open_data",
        "ask",
        "why",
        "close_session",
    }
    for tool in tools.values():
        assert tool.description and len(tool.description) > 40
    assert "consent" in tools["clean_file"].description.lower()


def test_the_elicit_decider_asks_only_for_gate_grade() -> None:
    """v1.5: GATE fixes are the client's human's call, per fix. HUMAN
    findings and admissions are never a yes/no popup — they stay deferred —
    and AUTO never bothers anyone. Decline and elicitation failure both skip
    with the reason in the note, because a popup that errored is not consent."""
    from types import SimpleNamespace

    from crivo.events import GateRequest

    asked: list[str] = []

    def accept(message: str):
        asked.append(message)
        return SimpleNamespace(action="accept", data=SimpleNamespace(approve=True))

    decide = mcp_server._make_decider(accept)
    auto = GateRequest("c", 1, title="fix 1/3 · auto", grade="AUTO")
    human = GateRequest("c", 1, title="fix 2/3 · human", grade="HUMAN")
    gate = GateRequest(
        "c", 1, title="fix 3/3 · gate", preview="a: 2 cells", grade="GATE"
    )

    assert decide(auto).action == "run"
    assert decide(human).action == "skip"
    assert asked == [], "AUTO and HUMAN must never reach the client"
    assert decide(gate).action == "run"
    assert asked and "fix 3/3 · gate" in asked[0] and "a: 2 cells" in asked[0]

    def decline(message: str):
        return SimpleNamespace(action="decline", data=None)

    decision = mcp_server._make_decider(decline)(gate)
    assert decision.action == "skip" and "declined" in decision.note

    def boom(message: str):
        raise RuntimeError("client hung up")

    decision = mcp_server._make_decider(boom)(gate)
    assert decision.action == "skip" and "unavailable" in decision.note


def test_clean_file_threads_the_decide_callback_through(monkeypatch) -> None:
    """The tool layer hands its elicitation decider to the driver; without
    this seam the decider exists but every clean still runs the blanket grade
    rule. The fake takes exactly run_clean_once's signature since #30, so a
    `policy` still passed down comes back as an error result."""
    from types import SimpleNamespace

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    received: dict = {}

    def fake_run(session, path, name=None, decide=None):
        received.update(path=path, decide=decide)
        return {"file": path, "needs_human": []}

    monkeypatch.setattr("crivo.repl.run_clean_once", fake_run)
    monkeypatch.setattr(
        mcp_server, "_make_session", lambda: SimpleNamespace(close=lambda: None)
    )
    sentinel = object()

    summary = mcp_server._clean_file("x.csv", decide=sentinel)

    assert "error" not in summary, summary["error"]
    # the RESOLVED path is what goes downstream, not the client's string: the
    # check and the read must not resolve it twice (see the TOCTOU test below)
    assert summary["file"] == str(pathlib.Path("x.csv").resolve())
    assert received["decide"] is sentinel


def test_client_capability_detection_fails_closed(monkeypatch) -> None:
    """No elicitation capability, no popup — exactly v1 behavior. The check
    itself failing must read as 'cannot ask', never as a crash."""
    from types import SimpleNamespace

    def ctx_with(answer):
        session = SimpleNamespace(check_client_capability=lambda cap: answer)
        return SimpleNamespace(request_context=SimpleNamespace(session=session))

    assert mcp_server._client_can_elicit(ctx_with(True)) is True
    assert mcp_server._client_can_elicit(ctx_with(False)) is False

    class Exploding:
        @property
        def request_context(self):
            raise RuntimeError("no request context outside a call")

    assert mcp_server._client_can_elicit(Exploding()) is False
    assert mcp_server._client_can_elicit(None) is False


def test_session_chatter_never_reaches_stdout(monkeypatch) -> None:
    """In stdio MCP mode, stdout IS the protocol channel — Session prints
    'starting kernel', 'loaded ...', and the profile, which a strict client
    parses as corrupt JSON-RPC. Found live: a real client warned 'Invalid
    JSON: starting kernel' mid-handshake. The tool paths must route every byte
    of that chatter to stderr, the way the CLI already does."""
    import contextlib
    import io

    class ChattySession:
        def __init__(self):
            print("starting kernel (subprocess) …")  # to stdout, like the real one
            self.datasets = []
            self.history = []
            self.closed = False
            self.session_dir = None

        def load(self, path, name=None):
            print(f"loaded {path} → df")
            self.datasets.append({"path": path, "variable": "df"})
            self.history.append(
                {"role": "user", "content": "<dataset variable='df'>\nrows\n</dataset>"}
            )

        def close(self):
            self.closed = True

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    monkeypatch.setattr(mcp_server, "_make_session", ChattySession)

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        opened = mcp_server._open_data("data/tiny.csv")

    assert "session_id" in opened, opened
    assert captured.getvalue() == "", (
        f"session chatter leaked to the protocol channel: {captured.getvalue()!r}"
    )


def test_clean_file_refuses_a_name_that_is_not_a_variable_name(monkeypatch) -> None:
    """The client's `name` is interpolated into loop.LOAD_TEMPLATE unescaped,
    so a client that can name a frame can run any code it likes in the
    server's kernel. Refuse it here, before a kernel exists."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    fake = FakeSession()
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)

    injected = "df\nimport os; os.system('id > /tmp/crivo_pwned')\ndf2"
    refused = mcp_server._clean_file("data/x.csv", name=injected)

    assert "not a variable name" in refused["error"]
    assert fake.datasets == [], "the injected name must never reach a kernel"
    assert (
        "Python keyword" in mcp_server._clean_file("data/x.csv", name="class")["error"]
    )

    ok = mcp_server._clean_file("data/x.csv", name="beers")
    assert "error" not in ok and ok["variable"] == "beers"


def test_ask_declines_person_grade_gates_and_reports_them(monkeypatch) -> None:
    """A GATE or HUMAN grade is a person's decision, and skill admission is
    hard-coded HUMAN. The calling MCP client is not that person, so those
    gates must be skipped and named back to the caller, never answered on the
    person's behalf; the analyst's own query cell still runs."""
    from crivo.card import AnswerCard
    from crivo.events import CardReady, GateRequest

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    card = AnswerCard(card_id="c1", session="s1", question="q", answer="a")
    fake = FakeSession(
        script=[
            GateRequest("rows = len(df)", 1),  # QUERY: grade is empty
            GateRequest("admit", 1, title="admit skill money_to_float", grade="HUMAN"),
            GateRequest("fix", 1, title="merge variants", grade="GATE"),
            CardReady(card),
        ]
    )
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)
    opened = mcp_server._open_data("data/tiny.csv")

    result = mcp_server._ask(opened["session_id"], "how many rows?")

    assert [d.action for d in fake.sent if d is not None] == ["run", "skip", "skip"]
    assert result["answer"] == "a"
    assert result["unresolved_gates"] == [
        "HUMAN: admit skill money_to_float",
        "GATE: merge variants",
    ], "the caller must learn a person-grade decision was needed and skipped"
    mcp_server.close_all()


def test_file_tools_refuse_paths_outside_the_configured_root(
    tmp_path, monkeypatch
) -> None:
    """diagnose_file is documented read-only and always safe to call first;
    unconfined it reads any file the server process can read. A symlink inside
    the root pointing out of it is the same escape, so containment is tested
    after resolving both sides."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    root = tmp_path / "served"
    (root / "sub").mkdir(parents=True)
    inside = root / "sub" / "ok.csv"
    pd.DataFrame({"a": [1, 2]}).to_csv(inside, index=False)
    secret = tmp_path / "secret.csv"
    pd.DataFrame({"a": [1]}).to_csv(secret, index=False)
    escape = root / "escape.csv"
    escape.symlink_to(secret)
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(root))
    fake = FakeSession()
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)

    assert "findings" in json.loads(mcp_server._diagnose_file(str(inside)))

    for path in (str(secret), str(escape), str(root / ".." / "secret.csv")):
        assert "outside" in json.loads(mcp_server._diagnose_file(path))["error"], path
        assert "outside" in mcp_server._open_data(path)["error"], path
        assert "outside" in mcp_server._clean_file(path)["error"], path
    assert fake.datasets == [], "no refused path may reach a kernel"


def test_a_symlinked_home_does_not_defeat_the_home_root_refusal(
    tmp_path, monkeypatch
) -> None:
    """The guard compared a RESOLVED root against an UNRESOLVED Path.home(),
    so the two spellings of one directory never matched and the whole home
    directory was served with no warning at all. A symlinked HOME is ordinary,
    not exotic: a relocated or encrypted home, or an operator who sets
    CRIVO_MCP_ROOT to the link instead of the target. Both spellings must be
    refused, and refusing is all this closes: a root one level under home is
    still served, by design."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    real_home = tmp_path / "real_home"
    real_home.mkdir()
    linked_home = tmp_path / "linked_home"
    linked_home.symlink_to(real_home)
    monkeypatch.setenv("HOME", str(linked_home))

    for spelling in (real_home, linked_home):
        monkeypatch.setenv("CRIVO_MCP_ROOT", str(spelling))
        denied = json.loads(mcp_server._diagnose_file("notes.csv"))["error"]
        assert "no usable root" in denied, spelling
        assert "CRIVO_MCP_ROOT" in denied, spelling

    # a directory under the home is a real root and stays served
    served = real_home / "datasets"
    served.mkdir()
    pd.DataFrame({"a": [1, 2]}).to_csv(served / "ok.csv", index=False)
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(served))
    assert "findings" in json.loads(mcp_server._diagnose_file("ok.csv"))


def test_a_relative_client_path_resolves_against_the_root_not_the_cwd(
    tmp_path, monkeypatch
) -> None:
    """A client is told the root and is never told the server's cwd, so a
    relative path it sends means "under the root". Resolving it against the
    process cwd refused every relative path whenever the server was launched
    outside its own root, which is the ordinary MCP stdio deployment: the
    client picks the cwd, the operator picks CRIVO_MCP_ROOT."""
    root = tmp_path / "served"
    (root / "sub").mkdir(parents=True)
    inside = root / "sub" / "ok.csv"
    pd.DataFrame({"a": [1, 2]}).to_csv(inside, index=False)
    elsewhere = tmp_path / "launched_here"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(root))

    target, denied = mcp_server._client_path("sub/ok.csv")

    assert denied is None, denied
    assert target == str(inside.resolve())
    assert "findings" in json.loads(mcp_server._diagnose_file("sub/ok.csv"))
    # relative does not mean unchecked: the containment test still runs after
    assert "outside" in mcp_server._client_path("../secret.csv")[1]


def test_the_sandbox_choice_is_explicit_and_warns_when_it_is_off(
    monkeypatch, capsys
) -> None:
    """loop.Session defaults to docker=False, so a factory that passes no
    docker argument runs model-authored code in a host subprocess with this
    user's files and network while the tools promise a sandbox. The choice
    must be made explicitly, and the unsandboxed default must say so aloud."""
    import crivo.loop

    seen: list[dict] = []

    class Recorder:
        def __init__(self, **kwargs):
            seen.append(kwargs)

    monkeypatch.setattr(crivo.loop, "Session", Recorder)
    monkeypatch.delenv("CRIVO_MCP_SANDBOX", raising=False)

    mcp_server._make_session()
    assert seen[0]["docker"] is False
    warning = capsys.readouterr().err
    assert "CRIVO_MCP_SANDBOX" in warning and "UNSANDBOXED" in warning.upper()

    monkeypatch.setenv("CRIVO_MCP_SANDBOX", "docker")
    mcp_server._make_session()
    assert seen[1]["docker"] is True
    assert "UNSANDBOXED" not in capsys.readouterr().err.upper()


def test_the_path_check_states_the_symlink_race_it_does_not_close() -> None:
    """_client_path's docstring narrated the TOCTOU race as won: it named the
    257-wins-in-8-seconds flipper and stopped there. Passing the resolved path
    downstream closes crivo's own second resolve, not the gap between this
    check and the reader's open: the resolved path is still a name, and a
    writer inside the root can swap the final component or re-point a parent
    in that gap. A reader checking the code against the comment would have
    concluded the race was over. The residual has to be in the words."""
    doc = mcp_server._client_path.__doc__

    assert "REMAINS OPEN" in doc.upper(), "the residual has to be stated"
    assert "O_NOFOLLOW" in doc, "and what closing it would actually take"


def test_the_sandbox_mount_and_the_confinement_root_are_one_directory(
    tmp_path, monkeypatch
) -> None:
    """The two P0 security fixes cancelled each other. _make_session passed
    docker=True but never data_dir, so Session kept the default ./data mount
    while the root check confined paths to CRIVO_MCP_ROOT, and every path
    that cleared the check then died in Session._kernel_path, which maps the
    file into the container by making it relative to data_dir. Sandboxing and
    path confinement could not both be on. They are the same directory now."""
    import crivo.loop

    kernel_path = crivo.loop.Session._kernel_path  # before the class is swapped
    root = tmp_path / "served"
    (root / "sub").mkdir(parents=True)
    inside = root / "sub" / "ok.csv"
    pd.DataFrame({"a": [1, 2]}).to_csv(inside, index=False)
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(root))
    monkeypatch.setenv("CRIVO_MCP_SANDBOX", "docker")
    seen: list[dict] = []

    class Recorder:
        def __init__(self, **kwargs):
            seen.append(kwargs)

    monkeypatch.setattr(crivo.loop, "Session", Recorder)

    mcp_server._make_session()

    assert seen[0]["docker"] is True
    assert seen[0]["data_dir"] == str(root.resolve())
    # the point of them being one directory: a path the root check cleared has
    # to MAP into the container, not raise on the way in
    from types import SimpleNamespace

    session = SimpleNamespace(docker=True, data_dir=pathlib.Path(seen[0]["data_dir"]))
    target, denied = mcp_server._client_path(str(inside))
    assert denied is None, denied
    assert kernel_path(session, pathlib.Path(target)) == "/data/sub/ok.csv"


def test_no_tool_docstring_promises_a_sandbox_the_server_may_not_have() -> None:
    """The docstrings are the contract a calling model acts on. While the
    host subprocess is still the default, none of them may claim the kernel is
    sandboxed, and the two that run model-authored code must name the env var
    that decides it."""
    import asyncio

    app = mcp_server.build_server()
    tools = {t.name: t for t in asyncio.run(app.list_tools())}

    for name in ("clean_file", "open_data"):
        assert "sandboxed kernel" not in tools[name].description
        assert "CRIVO_MCP_SANDBOX" in tools[name].description


def test_every_code_running_tool_opens_with_the_unsandboxed_default() -> None:
    """#37: a calling agent reads "not sandboxed by default" as the first
    sentence of every tool that runs model-written code, said once, up front,
    instead of mid-paragraph. diagnose_file runs no model code, so it must not
    carry the warning: a warning on every tool reads as boilerplate. ask keeps
    its un-gated and unresolved_gates text."""
    import asyncio

    runs = (
        "Not sandboxed by default: this runs model-written Python as the server "
        "user, with that user's files (including .env) and network. Set "
        "CRIVO_MCP_SANDBOX=docker to run it in a container with no network."
    )
    opens = (
        "Not sandboxed by default: the kernel this opens runs the model-written "
        "Python that ask sends it, as the server user, with that user's files "
        "(including .env) and network. Set CRIVO_MCP_SANDBOX=docker to run it in "
        "a container with no network."
    )
    openings = {
        "clean_file": runs,
        "open_data": opens,
        "ask": runs,
        "diagnose_file": None,
        "why": None,
        "close_session": None,
    }
    app = mcp_server.build_server()
    tools = {t.name: t for t in asyncio.run(app.list_tools())}

    wrong = []
    for name, want in openings.items():
        # the client sees the raw docstring; compare the words, not the wrap
        text = " ".join(tools[name].description.split())
        if want is None:
            ok = "sandboxed by default" not in text.lower()
        else:
            ok = text.startswith(want) and "host subprocess" not in text
        if not ok:
            wrong.append({"tool": name, "opens": text[:80]})
    assert not wrong, wrong

    ask = " ".join(tools["ask"].description.split())
    assert "un-gated" in ask
    assert "unresolved_gates" in ask


def _yaml_text(lines, at):
    """The string value of the `key:` line at index `at`, inline or folded
    (`>-`), the way a reader of action.yml sees it. The repo has no YAML
    parser dependency, and action.yml only uses these two shapes."""
    indent = len(lines[at]) - len(lines[at].lstrip())
    inline = lines[at].split(":", 1)[1].strip()
    parts = [] if inline in {">", ">-", "|", "|-"} else [inline.strip("\"'")]
    for line in lines[at + 1 :]:
        if not line.strip() or len(line) - len(line.lstrip()) <= indent:
            break
        parts.append(line.strip())
    return " ".join(parts)


def test_the_action_says_it_runs_no_model_code_and_lists_the_promised_formats() -> None:
    """#37: the Action runs only `crivo diagnose`, so its description says
    outright that it never runs model-written code, unlike the MCP tools. Its
    path input lists the formats the issue chose to promise: csv, tsv and
    parquet. diagnose reads more since #14; widening the promise is its own
    change, and this assert moves with it."""
    action = pathlib.Path(__file__).resolve().parents[1] / "action.yml"
    text = action.read_text(encoding="utf-8")
    lines = text.splitlines()

    top = next(i for i, line in enumerate(lines) if line.startswith("description:"))
    path_key = lines.index("  path:")
    path_desc = next(
        i
        for i in range(path_key + 1, len(lines))
        if lines[i].strip().startswith("description:")
    )

    assert (
        "Keyless: no model, no network, no configuration. "
        "It never runs model-written code." in _yaml_text(lines, top)
    )
    assert _yaml_text(lines, path_desc) == "Data file to check (csv, tsv or parquet)"
    assert "xlsx, json" not in text


def test_the_file_tools_use_the_path_they_checked(tmp_path, monkeypatch) -> None:
    """The check resolved the path and then handed the client's ORIGINAL
    string downstream, so a symlink that pointed inside the root when it was
    checked could point outside it by the time pandas opened it. That race was
    won 257 times in 8 seconds; passing the resolved path closes it."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(tmp_path))
    real = tmp_path / "real.csv"
    pd.DataFrame({"a": [1]}).to_csv(real, index=False)
    link = tmp_path / "link.csv"
    link.symlink_to(real)
    fake = FakeSession()
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)

    mcp_server._open_data(str(link))

    assert fake.datasets[-1]["path"] == str(real.resolve()), (
        "what was checked and what is opened have to be the same path"
    )


def test_a_root_that_holds_everything_is_refused_not_served(monkeypatch) -> None:
    """MCP stdio clients commonly launch a server with cwd="/", and the root
    fell back to cwd — so the deployment that most needs confining got none of
    it. A root of / or of the home directory is no root at all."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    for root in ("/", str(pathlib.Path.home())):
        monkeypatch.setenv("CRIVO_MCP_ROOT", root)
        refused = json.loads(mcp_server._diagnose_file("/etc/passwd"))["error"]
        assert "CRIVO_MCP_ROOT" in refused and "no usable root" in refused, root


def test_a_refusal_never_echoes_the_configured_root(tmp_path, monkeypatch) -> None:
    """Naming the env var helps the operator; naming its value tells an
    unauthenticated client the server's directory layout."""
    root = tmp_path / "clients" / "acme" / "private"
    root.mkdir(parents=True)
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(root))

    refused = json.loads(mcp_server._diagnose_file("/etc/passwd"))["error"]

    assert "CRIVO_MCP_ROOT" in refused
    assert str(root) not in refused and "acme" not in refused


def test_a_device_file_inside_the_root_is_refused(tmp_path, monkeypatch) -> None:
    """A FIFO or a character device inside the root is not a data file:
    reading one never returns, and this server has no other thread to notice
    that the client has hung it."""
    import os

    monkeypatch.setenv("CRIVO_MCP_ROOT", str(tmp_path))
    fifo = tmp_path / "pipe.csv"
    os.mkfifo(fifo)

    refused = json.loads(mcp_server._diagnose_file(str(fifo)))["error"]

    assert "not a regular file" in refused


def test_an_ordinary_variable_name_is_not_refused(monkeypatch) -> None:
    """The injection check was written as a regex stricter than Python, so
    _scratch, café and any name over 63 characters were refused although they
    are valid identifiers that worked before the check existed."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    fake = FakeSession()
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)

    for name in ("_scratch", "_raw", "café", "df2"):
        assert mcp_server._name_error(name) is None, name
        assert "error" not in mcp_server._clean_file("data/x.csv", name=name), name
    # and the injection it exists for is still refused
    assert "not a variable name" in mcp_server._name_error("df\nimport os")
    assert "longer than" in mcp_server._name_error("d" * 65)


def test_an_untitled_person_grade_gate_is_still_reported(monkeypatch) -> None:
    """The case that most needs surfacing: an untitled gate over an empty cell
    raised IndexError off code.splitlines()[0], so _ask returned a generic
    error, sent no decision, and reported no unresolved gate at all."""
    from crivo.events import GateRequest

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    fake = FakeSession(script=[GateRequest("", 1, grade="HUMAN")])
    monkeypatch.setattr(mcp_server, "_make_session", lambda: fake)
    opened = mcp_server._open_data("data/tiny.csv")

    result = mcp_server._ask(opened["session_id"], "how many rows?")

    assert [d.action for d in fake.sent if d is not None] == ["skip"]
    assert result["unresolved_gates"] == ["HUMAN: "]
    mcp_server.close_all()


def test_an_unknown_sandbox_value_is_an_error_not_the_weaker_default(
    monkeypatch,
) -> None:
    """CRIVO_MCP_SANDBOX=dokcer used to run unsandboxed with a stderr line the
    client may never show anyone. A sandbox the server does not recognize is
    not a sandbox, and silently downgrading is the wrong direction to fail."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("CRIVO_MCP_SANDBOX", "dokcer")

    assert "CRIVO_MCP_SANDBOX" in mcp_server._clean_file("data/x.csv")["error"]
    assert "CRIVO_MCP_SANDBOX" in mcp_server._open_data("data/x.csv")["error"]


def test_no_tool_docstring_still_sells_policy_all_as_human_consent() -> None:
    """A description telling the calling model to obtain and relay human
    consent through `policy` was the same class of false promise as the
    sandbox claim that was removed. Since #30 clean_file has no policy at
    all, so its description does not name one. ask must also say plainly what
    calling it executes."""
    import asyncio

    app = mcp_server.build_server()
    tools = {t.name: t for t in asyncio.run(app.list_tools())}

    clean = tools["clean_file"].description
    assert "approves judgement-grade changes unattended" not in clean
    assert "human consent relayed by you" not in clean
    assert "policy" not in clean.lower()
    assert "model-authored code" in tools["ask"].description


def test_the_docker_mount_does_not_widen_to_the_launch_directory(
    tmp_path, monkeypatch
) -> None:
    """Making the mount and the root one directory closed the mutual
    exclusion, and with no CRIVO_MCP_ROOT set _root() falls back to the launch
    directory - which three tool docstrings advertise as the default. So the
    read-only mount grew from <cwd>/data to <cwd>, and a .env sitting beside
    the project was suddenly inside the container that runs model-authored
    code un-gated. The mount widens only where an operator has named a root."""
    import crivo.loop

    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    (project / ".env").write_text("DEEPSEEK_API_KEY=sk-secret\n")
    monkeypatch.chdir(project)
    monkeypatch.delenv("CRIVO_MCP_ROOT", raising=False)
    monkeypatch.setenv("CRIVO_MCP_SANDBOX", "docker")
    seen: list[dict] = []

    class Recorder:
        def __init__(self, **kwargs):
            seen.append(kwargs)

    monkeypatch.setattr(crivo.loop, "Session", Recorder)

    mcp_server._make_session()

    mounted = pathlib.Path(seen[0].get("data_dir", "data"))
    if not mounted.is_absolute():
        mounted = project / mounted
    assert mounted.resolve() != project.resolve(), "the launch dir is mounted whole"
    assert not (mounted / ".env").exists()


def test_a_relative_path_under_a_nested_cwd_still_names_the_cwd_file(
    tmp_path, monkeypatch
) -> None:
    """Item 13's defect was a cwd OUTSIDE the root, where every relative path
    was refused. Resolving against the root unconditionally also changed the
    case where the cwd sits INSIDE the root, which already worked: with root
    /warehouse and cwd /warehouse/2024_q4, 'sales.csv' stopped naming the file
    in the cwd. The client sends one string and gets a different dataset,
    labelled with the path it sent, with no refusal in either direction."""
    root = tmp_path / "warehouse"
    nested = root / "2024_q4"
    nested.mkdir(parents=True)
    (nested / "sales.csv").write_text("b\n2\n")
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(root))
    monkeypatch.chdir(nested)

    target, denied = mcp_server._client_path("sales.csv")

    assert denied is None, denied
    assert target == str((nested / "sales.csv").resolve())


def test_a_relative_path_that_names_two_files_is_refused_by_name(
    tmp_path, monkeypatch
) -> None:
    """The other side of that preference. When a sales.csv sits in the nested
    cwd AND in the root, "relative to what" is genuinely two readings naming
    two real datasets, and there is nothing in the request that settles it.
    Picking either silently is the failure, so the string is refused and both
    readings are named. A refusal is a message; the wrong dataset is not."""
    root = tmp_path / "warehouse"
    nested = root / "2024_q4"
    nested.mkdir(parents=True)
    (root / "sales.csv").write_text("a\n1\n")
    (nested / "sales.csv").write_text("b\n2\n")
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(root))
    monkeypatch.chdir(nested)

    target, denied = mcp_server._client_path("sales.csv")

    assert target == ""
    assert "two different files" in denied, denied
    # naming it absolutely is never ambiguous, and still resolves
    assert mcp_server._client_path(str(root / "sales.csv"))[1] is None


def test_an_empty_client_path_is_refused_by_name(tmp_path, monkeypatch) -> None:
    """ "" and "." became the root DIRECTORY once relative paths resolved
    against the root, cleared containment, and reached the reader, so the tool
    answered {"error": "IsADirectoryError: ..."} where it used to give a clear
    refusal. A directory is not a dataset and the message should say so."""
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    for path in ("", ".", "  "):
        _, denied = mcp_server._client_path(path)
        assert denied, f"{path!r} was accepted"
        assert "IsADirectory" not in denied


# --- #30: clean_file takes no policy, and asks whenever the client can -------


class _ClientCtx:
    """The slice of an MCP request context clean_file reads: whether the
    client declared elicitation, and an elicit() whose person approves. Every
    question is recorded, so a test sees exactly what the person was asked."""

    def __init__(self, can_elicit: bool) -> None:
        from types import SimpleNamespace

        session = SimpleNamespace(check_client_capability=lambda cap: can_elicit)
        self.request_context = SimpleNamespace(session=session)
        self.asked: list[str] = []

    async def elicit(self, message, schema):
        from types import SimpleNamespace

        self.asked.append(message)
        return SimpleNamespace(action="accept", data=SimpleNamespace(approve=True))


def _mixed_grade_clean() -> FakeSession:
    """One clean with a gate of each grade a headless clean meets."""
    from crivo.events import GateRequest

    return FakeSession(
        script=[
            GateRequest(
                "df['city'] = df['city'].str.strip()",
                1,
                title="fix 1/3 · strip padding in city",
                grade="AUTO",
            ),
            GateRequest(
                "df['city'] = df['city'].replace(variants)",
                1,
                title="fix 2/3 · merge spelling variants in city",
                grade="GATE",
            ),
            GateRequest(
                "df = df.drop_duplicates('invoice_id')",
                1,
                title="fix 3/3 · drop repeated invoice_id rows",
                grade="HUMAN",
            ),
        ]
    )


def _served_invoices(tmp_path, monkeypatch) -> str:
    """A key that passes the gate, and a file inside the served root. The
    session is a double, so the file is only ever path-checked, not read."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    monkeypatch.setenv("CRIVO_MCP_ROOT", str(tmp_path))
    (tmp_path / "invoices.csv").write_text(
        "invoice_id,city,issued\n"
        "00417,Vancouver,2024-03-01\n"
        "00418,vancouver ,03/02/2024\n"
        "00418,vancouver ,03/02/2024\n"
        "00419,N/A,\n"
    )
    return "invoices.csv"


def _clean_file_via_the_server(arguments: dict, ctx) -> dict:
    """Call clean_file the way a client's tools/call does: the server's own
    argument model validates `arguments`, and `ctx` reaches the tool's ctx
    parameter (None lets the server build one with no request behind it)."""
    import asyncio

    result = asyncio.run(
        mcp_server.build_server().call_tool("clean_file", arguments, context=ctx)
    )
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


def test_clean_file_elicits_whenever_the_client_can(tmp_path, monkeypatch) -> None:
    """#30: any policy but "auto" silently turned elicitation off, so a
    client that could ask its person had GATE fixes deferred instead of
    offered. A client that declared elicitation is now asked whatever it
    sends: a stale `policy` is an unknown name the argument model drops. The
    plain call is the legitimate path beside it and asks too. HUMAN stays
    deferred (test_the_elicit_decider_asks_only_for_gate_grade owns that)."""
    path = _served_invoices(tmp_path, monkeypatch)

    for arguments in (
        {"path": path, "policy": "all"},
        {"path": path, "policy": "auto"},
        {"path": path},
    ):
        fake = _mixed_grade_clean()
        monkeypatch.setattr(mcp_server, "_make_session", lambda fake=fake: fake)
        ctx = _ClientCtx(can_elicit=True)

        summary = _clean_file_via_the_server(arguments, ctx)

        actions = [d.action for d in fake.sent if d is not None]
        assert actions == ["run", "run", "skip"], arguments
        assert len(ctx.asked) == 1, (arguments, len(ctx.asked))
        assert "merge spelling variants in city" in ctx.asked[0], arguments
        assert summary["needs_human"] == ["fix 3/3 · drop repeated invoice_id rows"], (
            arguments
        )


def test_clean_file_without_elicitation_keeps_the_grade_rule(
    tmp_path, monkeypatch
) -> None:
    """The fallback beside the test above: a client that never declared
    elicitation, or a call with no request behind its context, gets the
    headless grade rule. AUTO runs, every judgement call comes back in
    needs_human, nobody is asked, and a stale `policy` changes none of it."""
    path = _served_invoices(tmp_path, monkeypatch)

    for can_elicit, arguments in (
        (False, {"path": path, "policy": "all"}),
        (False, {"path": path}),
        (None, {"path": path}),
    ):
        fake = _mixed_grade_clean()
        monkeypatch.setattr(mcp_server, "_make_session", lambda fake=fake: fake)
        ctx = None if can_elicit is None else _ClientCtx(can_elicit)

        summary = _clean_file_via_the_server(arguments, ctx)

        actions = [d.action for d in fake.sent if d is not None]
        assert actions == ["run", "skip", "skip"], (can_elicit, arguments)
        assert ctx is None or ctx.asked == [], (can_elicit, arguments)
        assert summary["needs_human"] == [
            "fix 2/3 · merge spelling variants in city",
            "fix 3/3 · drop repeated invoice_id rows",
        ], (can_elicit, arguments)


def test_clean_file_takes_no_policy_argument() -> None:
    """#30: the input schema is what a client sees, and `policy` in it
    offered a choice whose only effect was to switch elicitation off. The
    schema offers path and name, as docs/API-CONTRACT.md lists them, and the
    plain function under the tool takes no policy either. A client that
    still sends one is not refused (the two tests above send it)."""
    import asyncio
    import inspect

    tools = {t.name: t for t in asyncio.run(mcp_server.build_server().list_tools())}
    schema = tools["clean_file"].input_schema

    assert set(schema["properties"]) == {"path", "name"}, sorted(schema["properties"])
    assert schema.get("required") == ["path"]
    assert "policy" not in inspect.signature(mcp_server._clean_file).parameters


def test_the_clean_file_description_says_who_writes_each_fix() -> None:
    """#30: "Fixes are model-written" was wrong for an AUTO finding with a
    deterministic fixer, which runs that fixer; the rest are model-written.
    The description also keeps telling the calling model that GATE fixes go
    to its person when the client supports elicitation."""
    import asyncio

    tools = {t.name: t for t in asyncio.run(mcp_server.build_server().list_tools())}
    clean = tools["clean_file"].description

    assert "Fixes are model-written" not in clean
    assert "deterministic" in clean
    assert "elicitation" in clean
