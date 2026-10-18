"""generate() seam tests: a fake client stands in for the openai SDK so every
test runs with no network calls and no API key. Each fake stream is a plain
iterator we control -- it can yield reasoning-only chunks, content chunks, or
block -- so we can drive the same code paths a real DeepSeek stream would hit
without ever opening a socket."""

import inspect
import json
import os
import re
import time
from types import SimpleNamespace

import pytest
from anthropic.types import (
    Message,
    MessageDeltaUsage,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
    RawMessageDeltaEvent,
    RawMessageStartEvent,
    RawMessageStopEvent,
    TextBlock,
    TextDelta,
    Usage,
)
from anthropic.types.message_create_params import MessageCreateParamsStreaming
from anthropic.types.raw_message_delta_event import Delta
from openai.types.chat import ChatCompletionChunk

from bench import agent_run
from crivo import llm


@pytest.fixture(scope="module")
def ambient_key():
    """Plants a fake shell credential the way a developer's rc file would.

    Module scope matters: higher-scoped fixtures set up before the
    function-scoped autouse quarantine in conftest, so the plant is in
    os.environ when the quarantine runs — exactly the ambient-leak scenario."""
    os.environ["DEEPSEEK_API_KEY"] = "sk-ambient-shell-leak"
    yield
    os.environ.pop("DEEPSEEK_API_KEY", None)


def test_ambient_credentials_never_reach_a_test(ambient_key):
    """F2: a real key in the developer's shell must not make a test pass that
    would fail keyless in CI. The conftest quarantine deletes every var in
    KEY_ENV_VARS before each test; tests that need one set it explicitly."""
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_deepseek_context_overflow_is_recognized():
    """F3: the shape DeepSeek's OpenAI-compatible endpoint actually returns
    when the prompt outgrows the window."""
    msg = (
        "Error code: 400 - {'error': {'message': 'This model's maximum "
        "context length is 65536 tokens. However, you requested 78123 tokens "
        "(70000 in the messages, 8123 in the completion).', "
        "'code': 'invalid_request_error'}}"
    )
    assert llm.is_context_overflow(msg) is True


def test_anthropic_context_overflow_is_recognized():
    """F3: both real Anthropic overflow shapes — the plain prompt overflow and
    the prompt+max_tokens budget overflow."""
    assert (
        llm.is_context_overflow("prompt is too long: 213462 tokens > 200000 maximum")
        is True
    )
    assert (
        llm.is_context_overflow(
            "input length and `max_tokens` exceed context limit: 195018 + 8192 > 200000"
        )
        is True
    )


def test_rate_limit_errors_are_not_context_overflow():
    """F3: throttling mentions tokens too, but means retry-later, not
    shrink-the-prompt. It must never be classified as overflow."""
    assert (
        llm.is_context_overflow(
            "Error code: 429 - rate limit reached: too many tokens per minute, "
            "please wait before trying again"
        )
        is False
    )


def test_unrelated_errors_are_not_context_overflow():
    """F3: an ordinary failure shares no overflow vocabulary and stays False."""
    assert llm.is_context_overflow("Connection reset by peer") is False


def test_faux_provider_returns_queued_responses_in_order(monkeypatch):
    """F4: CRIVO_PROVIDER=faux rides the same generate() seam callers use —
    no network, no SDK — handing back queued canned replies in order."""
    monkeypatch.setenv("CRIVO_PROVIDER", "faux")
    monkeypatch.setattr(llm, "_faux_responses", [])  # isolate queue state
    llm.faux_enqueue("first reply", "second reply")

    assert "".join(llm.generate([{"role": "user", "content": "a"}])) == "first reply"
    assert "".join(llm.generate([{"role": "user", "content": "b"}])) == "second reply"


def test_faux_provider_exhausted_queue_raises_a_clear_error(monkeypatch):
    """F4: running past the queue must name the faux provider and say how to
    feed it, not surface a bare IndexError from deep in the seam."""
    monkeypatch.setenv("CRIVO_PROVIDER", "faux")
    monkeypatch.setattr(llm, "_faux_responses", [])
    llm.faux_enqueue("only reply")
    assert "".join(llm.generate([{"role": "user", "content": "a"}])) == "only reply"

    with pytest.raises(RuntimeError, match="faux"):
        list(llm.generate([{"role": "user", "content": "b"}]))


def test_key_env_vars_registry_covers_every_env_var_the_module_reads():
    """F1: one source of truth for provider credentials and selection. The
    membership is pinned exactly, and every os.environ read in llm.py must be
    registered so a new read can't silently dodge the test-suite quarantine."""
    assert set(llm.KEY_ENV_VARS) == {
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "CRIVO_PROVIDER",
        "CRIVO_MODEL",
        "CRIVO_BASE_URL",
        "CRIVO_API_KEY",
        "CRIVO_STALL_S",
        "CRIVO_MAX_CALL_S",
    }
    source = inspect.getsource(llm)
    reads = set(re.findall(r'environ(?:\.get\(|\[)\s*"([A-Z_]+)"', source))
    assert reads <= set(llm.KEY_ENV_VARS), f"unregistered env reads: {reads}"


def chunk(content=None, reasoning=None):
    """A double for one `ChatCompletionChunk`: only `.choices[0].delta` is
    ever read by generate(), so that's all this needs to have."""
    delta = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def fake_client(stream):
    """A client double whose chat.completions.create(**_) hands back a
    pre-built stream, ignoring every call kwarg (model, timeout, ...)."""

    def create(**_):
        return stream

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


def claude_event(text=None, thinking=None, kind="content_block_delta"):
    """A double for one anthropic stream event: only `.type` and
    `.delta.{type,text}` are ever read by the claude path."""
    if text is not None:
        delta = SimpleNamespace(type="text_delta", text=text)
    else:
        delta = SimpleNamespace(type="thinking_delta", thinking=thinking or "")
    return SimpleNamespace(type=kind, delta=delta)


def fake_claude_client(stream, calls=None):
    """A client double for anthropic's messages.create(**kw)."""

    def create(**kw):
        if calls is not None:
            calls.append(kw)
        return stream

    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_the_provider_switch_selects_claude_behind_the_same_seam(monkeypatch):
    """R10: generate(messages) -> Iterator[str] is the whole contract, and a
    provider env switch must be the only difference a caller can observe.
    model_info() hard-coded "deepseek", so every answer card produced through
    the Claude half would have carried a false provenance stamp."""
    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    monkeypatch.delenv("CRIVO_MODEL", raising=False)
    calls: list = []
    stream = iter([claude_event(text="hel"), claude_event(text="lo")])
    monkeypatch.setattr(
        llm, "_get_claude_client", lambda: fake_claude_client(stream, calls)
    )

    result = list(
        llm.generate(
            [
                {"role": "system", "content": "be terse"},
                {"role": "user", "content": "hi"},
            ]
        )
    )

    assert result == ["hel", "lo"]
    info = llm.model_info()
    assert info["provider"] == "claude"
    assert info["model"].startswith("claude-")
    # anthropic takes system as a top-level param, not a message role
    assert calls[0]["system"] == "be terse"
    assert all(m["role"] != "system" for m in calls[0]["messages"])


def test_claude_thinking_deltas_are_heartbeats_not_text(monkeypatch):
    """Same contract as DeepSeek's reasoning_content: thinking never reaches
    the tag parser, but an empty chunk says the stream is alive."""
    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    stream = iter(
        [
            claude_event(thinking="pondering..."),
            claude_event(text="done"),
            SimpleNamespace(type="message_stop"),
        ]
    )
    monkeypatch.setattr(llm, "_get_claude_client", lambda: fake_claude_client(stream))

    assert list(llm.generate([{"role": "user", "content": "hi"}])) == ["", "done"]


def test_claude_request_matches_the_current_messages_api(monkeypatch):
    """Regression for #13. DD1: models after Claude Opus 4.6 answer any
    temperature, top_p or top_k with HTTP 400, so every call on
    CRIVO_PROVIDER=claude failed. Thinking is always on and spends from
    max_tokens, so 8192 can cut a reply short; effort is the control now.
    Summarized thinking streams deltas, which the stall timer reads as a live
    stream instead of a dead one."""
    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    calls: list = []
    stream = iter(
        [claude_event(thinking="weighing the medians"), claude_event(text="ok")]
    )
    monkeypatch.setattr(
        llm, "_get_claude_client", lambda: fake_claude_client(stream, calls)
    )

    reply = llm.generate(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "which district grew most?"},
        ]
    )
    assert list(reply) == ["", "ok"]

    sent = calls[0]
    assert not {"temperature", "top_p", "top_k"} & set(sent), (
        f"current Claude models reject these with HTTP 400: {sorted(sent)}"
    )
    assert sent.get("model") == "claude-opus-5-5"
    assert sent.get("max_tokens", 0) >= 32000, "thinking spends from max_tokens"
    effort = getattr(llm, "CLAUDE_EFFORT", None)
    assert effort == "high"  # Aarmen's call: a constant, not an env var
    assert sent.get("output_config") == {"effort": effort}
    thinking = sent.get("thinking") or {}
    assert thinking.get("type") == "adaptive"
    assert "budget_tokens" not in thinking
    assert thinking.get("display") == "summarized", "keeps the stall timer honest"
    assert sent.get("stream") is True
    fields = (
        MessageCreateParamsStreaming.__required_keys__
        | MessageCreateParamsStreaming.__optional_keys__
    )
    assert set(sent) <= fields, f"not Messages API fields: {set(sent) - fields}"

    assert llm.model_info() == {
        "provider": "claude",
        "model": "claude-opus-5-5",
        "effort": "high",
    }


@pytest.mark.parametrize(
    ("provider", "seam", "env"),
    [
        pytest.param("deepseek", "_get_client", {}, id="deepseek"),
        pytest.param(
            "openai", "_get_openai_client", {"CRIVO_MODEL": "llama3.3"}, id="openai"
        ),
    ],
)
def test_openai_compatible_requests_keep_their_temperature(
    monkeypatch, provider, seam, env
):
    """Pin beside DD1: dropping temperature is a Claude fact. DeepSeek and
    the generic OpenAI endpoint still accept it, and still get 0.0."""
    monkeypatch.setenv("CRIVO_PROVIDER", provider)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sent: dict = {}

    def create(**kw):
        sent.update(kw)
        return iter([chunk(content="pong")])

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(llm, seam, lambda: client)

    assert list(llm.generate([{"role": "user", "content": "hi"}])) == ["pong"]
    assert sent.get("temperature") == llm.TEMPERATURE == 0.0
    assert llm.model_info()["temperature"] == 0.0


_USAGE_ATTRS = (
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "crivo.cache.hit_tokens",
    "crivo.cache.miss_tokens",
)


def _claude_stream(start_usage: dict | None, output_tokens: int = 57) -> list:
    """The event sequence a real Messages API stream sends, built from the
    SDK's own types. Input and cache counts arrive once, on message_start;
    message_delta carries the running output count."""
    events: list = []
    if start_usage is not None:
        events.append(
            RawMessageStartEvent(
                type="message_start",
                message=Message(
                    id="msg_01XFDUDYJgAACzvnptvVoYEL",
                    type="message",
                    role="assistant",
                    model="claude-opus-5-5",
                    content=[],
                    stop_reason=None,
                    stop_sequence=None,
                    usage=Usage(**start_usage),
                ),
            )
        )
    events += [
        RawContentBlockStartEvent(
            type="content_block_start",
            index=0,
            content_block=TextBlock(type="text", text="", citations=None),
        ),
        RawContentBlockDeltaEvent(
            type="content_block_delta",
            index=0,
            delta=TextDelta(type="text_delta", text="RS-1 grew most."),
        ),
        RawContentBlockStopEvent(type="content_block_stop", index=0),
        RawMessageDeltaEvent(
            type="message_delta",
            delta=Delta(stop_reason="end_turn", stop_sequence=None),
            usage=MessageDeltaUsage(output_tokens=output_tokens),
        ),
        RawMessageStopEvent(type="message_stop"),
    ]
    return events


def _call_attrs(path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return next(r for r in rows if r["name"] == "gen_ai.client.call")["attrs"]


@pytest.mark.parametrize(
    ("cache_written", "expected", "new_work"),
    [
        # 1200 fresh + 200 read + 0 written in; 57 out (the last count, not
        # 1 + 57); 1400 - 200 + 57 = 1257 new work
        pytest.param(None, (1400, 57, 200, 1200), 1257, id="cache-read"),
        # a cache write is new work: 1200 + 300 + 200 = 1700 in, 1500 missed,
        # 1700 - 200 + 57 = 1557
        pytest.param(300, (1700, 57, 200, 1500), 1557, id="cache-read-and-write"),
    ],
)
def test_claude_usage_reaches_the_telemetry_span(
    tmp_path, monkeypatch, cache_written, expected, new_work
):
    """Regression for #13. W23r: generate() mapped only the OpenAI spelling,
    and _watched never looked inside message_start, so no Claude span carried
    a token count and the bench's cost column read unknown. Anthropic's
    input_tokens excludes cache reads and writes, where DeepSeek's
    prompt_tokens includes the hits; the span carries DeepSeek's meaning, so
    the bench's input - hit + output counts the cache once, not twice."""
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CRIVO_TELEMETRY", str(path))
    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    stream = _claude_stream(
        {
            "input_tokens": 1200,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": cache_written,
            "output_tokens": 1,
        }
    )
    monkeypatch.setattr(
        llm, "_get_claude_client", lambda: fake_claude_client(iter(stream))
    )

    reply = "".join(llm.generate([{"role": "user", "content": "q"}]))
    assert reply == "RS-1 grew most."

    attrs = _call_attrs(path)
    assert tuple(attrs.get(a) for a in _USAGE_ATTRS) == expected
    assert agent_run._call_stats(path)["new_work_tokens"] == new_work


def _deepseek_stream() -> list:
    """DeepSeek's final chunk: no choices, usage only. prompt_tokens already
    includes the cache hits; the hit/miss split is DeepSeek's own extension."""
    return [
        chunk(content="RS-1 grew most."),
        ChatCompletionChunk.model_validate(
            {
                "id": "a3f1c9e2-5b7d-4e8a-9c0f-1d2e3f4a5b6c",
                "object": "chat.completion.chunk",
                "created": 1760700000,
                "model": "deepseek-v4-pro",
                "choices": [],
                "usage": {
                    "prompt_tokens": 1400,
                    "completion_tokens": 57,
                    "total_tokens": 1457,
                    "prompt_cache_hit_tokens": 200,
                    "prompt_cache_miss_tokens": 1200,
                },
            }
        ),
    ]


@pytest.mark.parametrize(
    ("provider", "seam", "stream", "expected", "new_work"),
    [
        # the same call in DeepSeek's spelling prices the same as Claude's
        pytest.param(
            "deepseek",
            "_get_client",
            _deepseek_stream,
            dict(zip(_USAGE_ATTRS, (1400, 57, 200, 1200), strict=True)),
            1257,
            id="deepseek-spelling-unchanged",
        ),
        # no message_start reached us, so input is unknown: an output count
        # alone would publish a call that knowably cost more as a cheap one
        pytest.param(
            "claude",
            "_get_claude_client",
            lambda: _claude_stream(None),
            {},
            None,
            id="claude-without-input-tokens",
        ),
    ],
)
def test_usage_mapping_the_claude_change_leaves_alone(
    tmp_path, monkeypatch, provider, seam, stream, expected, new_work
):
    """Pins beside W23r: the OpenAI-name mapping stays as it was, and a
    Claude usage with no input_tokens maps none of the four attributes
    (Aarmen's call)."""
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CRIVO_TELEMETRY", str(path))
    monkeypatch.setenv("CRIVO_PROVIDER", provider)
    events = iter(stream())
    client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **_: events),
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: events)),
    )
    monkeypatch.setattr(llm, seam, lambda: client)

    reply = "".join(llm.generate([{"role": "user", "content": "q"}]))
    assert reply == "RS-1 grew most."

    attrs = _call_attrs(path)
    assert {a: attrs[a] for a in _USAGE_ATTRS if a in attrs} == expected
    assert agent_run._call_stats(path)["new_work_tokens"] == new_work


def test_content_chunks_pass_through_unchanged(monkeypatch):
    stream = iter([chunk(content="hel"), chunk(content="lo")])
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client(stream))

    result = list(llm.generate([{"role": "user", "content": "hi"}]))

    assert result == ["hel", "lo"]


def test_reasoning_only_chunk_yields_heartbeat_not_leaked_text(monkeypatch):
    stream = iter(
        [
            chunk(reasoning="thinking step one..."),
            chunk(reasoning="thinking step two..."),
            chunk(content="done"),
        ]
    )
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client(stream))

    result = list(llm.generate([{"role": "user", "content": "hi"}]))

    assert result == ["", "", "done"], "reasoning text must never reach the caller"


def test_slow_but_progressing_stream_exceeds_total_budget(monkeypatch):
    """Chunks keep arriving -- just too slowly and for too long -- so the
    call-length ceiling must fire even though the stream is technically
    alive the whole time."""
    monkeypatch.setattr(llm, "MAX_CALL_S", 0.05)

    def endless():
        while True:
            time.sleep(0.02)
            yield chunk(reasoning="...")

    monkeypatch.setattr(llm, "_get_client", lambda: fake_client(endless()))

    with pytest.raises(TimeoutError, match="thinking"):
        list(llm.generate([{"role": "user", "content": "hi"}]))


def test_a_stream_that_goes_silent_is_abandoned(monkeypatch):
    """No read timeout, no chunk -- pure wire silence on an established
    connection, which is what a real 15-minute production hang traced back
    to. This is the case MAX_CALL_S cannot rescue on its own: its check only
    runs when a chunk arrives, and here none ever does. The guard must give
    up on its own wall clock rather than wait for the stream to speak again.

    The fake blocks for 0.5s (not forever) so a regression fails this test
    fast instead of hanging the suite; the assertion on `elapsed` is what
    actually proves the guard didn't just wait the block out."""
    monkeypatch.setattr(llm, "STALL_S", 0.05)

    class GoesSilent:
        def __iter__(self):
            return self

        def __next__(self):
            time.sleep(0.5)
            raise StopIteration

    monkeypatch.setattr(llm, "_get_client", lambda: fake_client(GoesSilent()))

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="silence"):
        list(llm.generate([{"role": "user", "content": "hi"}]))
    elapsed = time.monotonic() - started

    assert elapsed < 0.3, "must give up on the wall clock, not wait for the stream"


def test_openai_provider_selects_a_generic_endpoint_behind_the_same_seam(monkeypatch):
    """P3: CRIVO_PROVIDER=openai speaks to any OpenAI-compatible /v1 server
    (Ollama, OpenRouter, vLLM) — endpoint and model come from env, the key is
    optional because local servers ignore it, and misconfiguration must name
    the exact variable instead of KeyErroring deep in the SDK."""
    monkeypatch.setenv("CRIVO_PROVIDER", "openai")
    monkeypatch.setattr(llm, "_openai_client", None, raising=False)

    with pytest.raises(RuntimeError, match="CRIVO_BASE_URL"):
        list(llm.generate([{"role": "user", "content": "hi"}]))

    monkeypatch.setenv("CRIVO_BASE_URL", "http://localhost:11434/v1")
    with pytest.raises(RuntimeError, match="CRIVO_MODEL"):
        list(llm.generate([{"role": "user", "content": "hi"}]))

    monkeypatch.setenv("CRIVO_MODEL", "llama3.3")
    captured: dict = {}

    def fake_openai(**kw):
        captured.update(kw)
        return fake_client(iter([chunk(content="pong")]))

    monkeypatch.setattr(llm, "OpenAI", fake_openai)
    monkeypatch.setattr(llm, "_openai_client", None, raising=False)

    assert list(llm.generate([{"role": "user", "content": "hi"}])) == ["pong"]
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "local-no-key"  # placeholder: server ignores it
    assert llm.model_info() == {
        "provider": "openai",
        "model": "llama3.3",
        "temperature": 0.0,
    }


def test_seam_hardening_url_scheme_and_env_stream_budgets(monkeypatch):
    """Arc W3/H6: a CRIVO_BASE_URL that isn't http(s) must fail with the
    scheme named (a pasted 'localhost:11434' would otherwise die deep in the
    SDK), and the stream budgets must be env-tunable — a local model's slow
    first token would be killed as a dead stream at the hardcoded 90s."""
    monkeypatch.setenv("CRIVO_PROVIDER", "openai")
    monkeypatch.setattr(llm, "_openai_client", None, raising=False)
    monkeypatch.setenv("CRIVO_BASE_URL", "localhost:11434/v1")
    with pytest.raises(RuntimeError, match="http"):
        list(llm.generate([{"role": "user", "content": "hi"}]))

    monkeypatch.setenv("CRIVO_STALL_S", "240")
    monkeypatch.setenv("CRIVO_MAX_CALL_S", "900")
    assert llm.stall_budget_s() == 240.0
    assert llm.call_budget_s() == 900.0
    monkeypatch.delenv("CRIVO_STALL_S")
    monkeypatch.delenv("CRIVO_MAX_CALL_S")
    assert llm.stall_budget_s() == llm.STALL_S
    assert llm.call_budget_s() == llm.MAX_CALL_S
