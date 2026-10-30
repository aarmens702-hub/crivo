"""generate() seam tests: a fake client stands in for the openai SDK so every
test runs with no network calls and no API key. Each fake stream is a plain
iterator we control -- it can yield reasoning-only chunks, content chunks, or
block -- so we can drive the same code paths a real DeepSeek stream would hit
without ever opening a socket."""

import inspect
import json
import os
import re
import threading
import time
from email.utils import formatdate
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


def chunk(content=None, reasoning=None, model=None):
    """A double for one `ChatCompletionChunk`. generate() reads the text from
    `.choices[0].delta` and the served model id from `.model`. Without a
    `model` the double has no such field at all, the shape of an endpoint
    that does not report one; `model=""` is an endpoint that sends it empty."""
    delta = SimpleNamespace(content=content, reasoning_content=reasoning)
    served = {} if model is None else {"model": model}
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], **served)


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


def install_openai_create(monkeypatch, create):
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(llm, "_get_client", lambda: client)


def install_claude_create(monkeypatch, create):
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(llm, "_get_claude_client", lambda: client)


class ProviderError(RuntimeError):
    def __init__(self, status_code, headers=None, message="provider request failed"):
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})


def test_provider_clients_disable_sdk_retries(monkeypatch):
    import anthropic

    openai_calls: list[dict] = []
    claude_calls: list[dict] = []

    def fake_openai(**kwargs):
        openai_calls.append(kwargs)
        return SimpleNamespace()

    def fake_anthropic(**kwargs):
        claude_calls.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(llm, "OpenAI", fake_openai)
    monkeypatch.setattr(anthropic, "Anthropic", fake_anthropic)
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm, "_openai_client", None)
    monkeypatch.setattr(llm, "_claude_client", None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("CRIVO_BASE_URL", "http://localhost/v1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    llm._get_client()
    llm._get_openai_client()
    llm._get_claude_client()

    assert [call["max_retries"] for call in openai_calls] == [0, 0]
    assert [call["max_retries"] for call in claude_calls] == [0]


def test_retry_after_accepts_milliseconds_seconds_and_http_dates(monkeypatch):
    monkeypatch.setattr(llm.time, "time", lambda: 1_000_000.0)

    assert (
        llm._retry_after_seconds(
            ProviderError(429, {"retry-after-ms": "500", "Retry-After": "5"})
        )
        == 0.5
    )
    assert llm._retry_after_seconds(
        ProviderError(503, {"Retry-After": formatdate(1_000_003, usegmt=True)})
    ) == pytest.approx(3.0)


def test_rate_limited_create_retries_after_the_server_delay(monkeypatch):
    monkeypatch.setenv("CRIVO_PROVIDER", "deepseek")
    calls: list[int] = []
    delays: list[float] = []

    def create(**_):
        calls.append(1)
        if len(calls) == 1:
            raise ProviderError(429, {"Retry-After": "2"})
        return iter([chunk(content="done")])

    def skip_wait(delay_s, _started_at, _call_budget, _retry_stats=None):
        delays.append(delay_s)
        return iter(())

    install_openai_create(monkeypatch, create)
    monkeypatch.setattr(llm, "_wait_before_retry", skip_wait)

    assert list(llm.generate([{"role": "user", "content": "hi"}])) == ["done"]
    assert calls == [1, 1]
    assert delays == [2.0]


@pytest.mark.parametrize("provider", ["deepseek", "claude"])
def test_connection_error_before_first_stream_chunk_retries(monkeypatch, provider):
    """Regression for #117: a stream can fail before yielding its first item."""
    monkeypatch.setenv("CRIVO_PROVIDER", provider)
    monkeypatch.setattr(llm, "_wait_before_retry", lambda *_: iter(()))
    calls: list[int] = []

    def failed_stream():
        raise ConnectionError("connection closed before the first chunk")
        yield  # keep this a generator so failure happens while consuming it

    def create(**_):
        calls.append(1)
        if len(calls) == 1:
            return failed_stream()
        event = (
            claude_event(text="recovered")
            if provider == "claude"
            else chunk(content="recovered")
        )
        return iter([event])

    if provider == "claude":
        install_claude_create(monkeypatch, create)
    else:
        install_openai_create(monkeypatch, create)

    assert list(llm.generate([{"role": "user", "content": "hi"}])) == ["recovered"]
    assert calls == [1, 1]


@pytest.mark.parametrize("provider", ["deepseek", "claude"])
@pytest.mark.parametrize("heartbeat", [False, True], ids=["text", "heartbeat"])
def test_connection_error_after_first_stream_chunk_is_not_retried(
    monkeypatch, provider, heartbeat
):
    """Regression for #117: delivered text and heartbeat chunks are not replayed."""
    monkeypatch.setenv("CRIVO_PROVIDER", provider)
    monkeypatch.setattr(llm, "_wait_before_retry", lambda *_: iter(()))
    calls: list[int] = []

    def failed_after_chunk():
        if provider == "claude":
            event = (
                claude_event(thinking="thinking")
                if heartbeat
                else claude_event(text="partial")
            )
        else:
            event = (
                chunk(reasoning="thinking") if heartbeat else chunk(content="partial")
            )
        yield event
        raise ConnectionError("connection closed after the first chunk")

    def create(**_):
        calls.append(1)
        return failed_after_chunk()

    if provider == "claude":
        install_claude_create(monkeypatch, create)
    else:
        install_openai_create(monkeypatch, create)

    reply = llm.generate([{"role": "user", "content": "hi"}])
    assert next(reply) == ("" if heartbeat else "partial")
    with pytest.raises(ConnectionError, match="after the first chunk"):
        next(reply)
    assert calls == [1]


def test_retry_discards_metadata_from_a_failed_unstarted_claude_stream(
    tmp_path, monkeypatch
):
    """Regression for #117: a retried attempt cannot overwrite final metadata."""
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    monkeypatch.setenv("CRIVO_TELEMETRY", str(path))
    monkeypatch.setattr(llm, "_wait_before_retry", lambda *_: iter(()))
    calls: list[int] = []
    discarded_usage = {
        "input_tokens": 9,
        "cache_read_input_tokens": 2,
        "cache_creation_input_tokens": 3,
        "output_tokens": 1,
    }
    final_usage = {
        "input_tokens": 1200,
        "cache_read_input_tokens": 200,
        "cache_creation_input_tokens": None,
        "output_tokens": 1,
    }

    def failed_after_metadata():
        yield _claude_stream(discarded_usage, model="claude-discarded")[0]
        raise ConnectionError("connection closed before any reply chunk")

    def create(**_):
        calls.append(1)
        if len(calls) == 1:
            return failed_after_metadata()
        return iter(_claude_stream(final_usage, model="claude-final"))

    install_claude_create(monkeypatch, create)

    assert (
        "".join(llm.generate([{"role": "user", "content": "hi"}])) == "RS-1 grew most."
    )

    attrs = _call_attrs(path)
    assert attrs["gen_ai.response.model"] == "claude-final"
    assert tuple(attrs.get(attr) for attr in _USAGE_ATTRS) == (1400, 57, 200, 1200)
    assert calls == [1, 1]


def test_retry_stats_include_attempts_and_actual_total_wait(tmp_path, monkeypatch):
    """Regression for #117. Retry telemetry records the calls and wait."""
    monkeypatch.setenv("CRIVO_PROVIDER", "deepseek")
    monkeypatch.setenv("CRIVO_TELEMETRY", str(tmp_path / "trace.jsonl"))
    calls: list[int] = []

    def create(**_):
        calls.append(1)
        if len(calls) == 1:
            raise ProviderError(429, {"Retry-After": "0.02"})
        return iter([chunk(content="done")])

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )

    chunks = list(llm.generate([{"role": "user", "content": "hi"}]))
    assert chunks[-1] == "done"
    assert chunks[:-1] and set(chunks[:-1]) == {""}
    attrs = _call_attrs(tmp_path / "trace.jsonl")
    assert attrs["crivo.retry.attempts"] == 1
    assert 0 < attrs["crivo.retry.wait_s"] < 1
    assert len(calls) == 2


def test_default_backoff_stops_after_three_provider_attempts(monkeypatch):
    monkeypatch.setenv("CRIVO_PROVIDER", "deepseek")
    calls: list[int] = []
    delays: list[float] = []

    def create(**_):
        calls.append(1)
        raise ProviderError(503)

    def skip_wait(delay_s, _started_at, _call_budget, _retry_stats=None):
        delays.append(delay_s)
        return iter(())

    install_openai_create(monkeypatch, create)
    monkeypatch.setattr(llm, "_wait_before_retry", skip_wait)

    with pytest.raises(ProviderError):
        list(llm.generate([{"role": "user", "content": "hi"}]))

    assert len(calls) == 3
    assert delays == [1, 2]


def test_connection_errors_retry_but_context_overflow_does_not(monkeypatch):
    monkeypatch.setenv("CRIVO_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "_wait_before_retry", lambda *_: iter(()))
    calls: list[int] = []

    def connection_then_success(**_):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("connection reset")
        return iter([chunk(content="ok")])

    install_openai_create(monkeypatch, connection_then_success)
    assert list(llm.generate([{"role": "user", "content": "hi"}])) == ["ok"]
    assert len(calls) == 2

    overflow_calls: list[int] = []

    def overflow(**_):
        overflow_calls.append(1)
        raise ProviderError(500, message="maximum context length exceeded")

    install_openai_create(monkeypatch, overflow)
    with pytest.raises(ProviderError, match="maximum context length"):
        list(llm.generate([{"role": "user", "content": "hi"}]))
    assert len(overflow_calls) == 1


def test_anthropic_connection_error_retries_before_stream(monkeypatch):
    import anthropic
    import httpx2

    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    monkeypatch.setattr(llm, "_wait_before_retry", lambda *_: iter(()))
    error = anthropic.APIConnectionError(
        request=httpx2.Request("GET", "https://api.anthropic.com")
    )
    calls: list[int] = []

    def create(**_):
        calls.append(1)
        if len(calls) == 1:
            raise error
        return iter(())

    install_claude_create(monkeypatch, create)

    assert list(llm.generate([{"role": "user", "content": "hi"}])) == []
    assert len(calls) == 2


def test_anthropic_overloaded_error_retries_before_stream(monkeypatch):
    import anthropic
    import httpx2

    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    monkeypatch.setattr(llm, "_wait_before_retry", lambda *_: iter(()))
    request = httpx2.Request("POST", "https://api.anthropic.com")
    error = anthropic.OverloadedError(
        message="overloaded",
        response=httpx2.Response(529, request=request),
        body={"type": "overloaded_error"},
    )
    calls: list[int] = []

    def create(**_):
        calls.append(1)
        if len(calls) == 1:
            raise error
        return iter(())

    install_claude_create(monkeypatch, create)

    assert list(llm.generate([{"role": "user", "content": "hi"}])) == []
    assert len(calls) == 2


def test_retry_after_longer_than_remaining_budget_fails_without_waiting(monkeypatch):
    monkeypatch.setenv("CRIVO_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "MAX_CALL_S", 0.05)
    calls: list[int] = []

    def create(**_):
        calls.append(1)
        raise ProviderError(429, {"Retry-After": "2"})

    install_openai_create(monkeypatch, create)
    with pytest.raises(TimeoutError, match="2s exceeds remaining call budget"):
        list(llm.generate([{"role": "user", "content": "hi"}]))
    assert len(calls) == 1


def test_cancel_interrupts_a_provider_retry_wait(monkeypatch):
    monkeypatch.setenv("CRIVO_PROVIDER", "deepseek")
    calls: list[int] = []

    def create(**_):
        calls.append(1)
        raise ProviderError(429, {"Retry-After": "2"})

    install_openai_create(monkeypatch, create)
    timer = threading.Timer(0.02, llm.request_cancel)
    started = time.monotonic()
    timer.start()
    try:
        with pytest.raises(llm.CallCancelled):
            list(llm.generate([{"role": "user", "content": "hi"}]))
    finally:
        timer.join()
    assert time.monotonic() - started < 0.5
    assert len(calls) == 1


def test_stream_failure_after_first_chunk_is_not_replayed(monkeypatch):
    monkeypatch.setenv("CRIVO_PROVIDER", "deepseek")
    calls: list[int] = []

    def broken_stream():
        yield chunk(content="first")
        raise ConnectionError("connection closed")

    def create(**_):
        calls.append(1)
        return broken_stream()

    install_openai_create(monkeypatch, create)
    reply = llm.generate([{"role": "user", "content": "hi"}])
    assert next(reply) == "first"
    with pytest.raises(ConnectionError, match="connection closed"):
        next(reply)
    assert len(calls) == 1


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


def _claude_stream(
    start_usage: dict | None, output_tokens: int = 57, model: str = "claude-opus-5-5"
) -> list:
    """The event sequence a real Messages API stream sends, built from the
    SDK's own types. Input and cache counts arrive once, on message_start,
    and so does the served model id (`message.model`); message_delta carries
    the running output count. No start_usage means no message_start at all."""
    events: list = []
    if start_usage is not None:
        events.append(
            RawMessageStartEvent(
                type="message_start",
                message=Message(
                    id="msg_01XFDUDYJgAACzvnptvVoYEL",
                    type="message",
                    role="assistant",
                    model=model,
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


def _deepseek_stream(model: str = "deepseek-v4-pro") -> list:
    """DeepSeek's final chunk: no choices, usage only. prompt_tokens already
    includes the cache hits; the hit/miss split is DeepSeek's own extension.
    The final chunk names the model that served the call, as `model`."""
    return [
        chunk(content="RS-1 grew most."),
        ChatCompletionChunk.model_validate(
            {
                "id": "a3f1c9e2-5b7d-4e8a-9c0f-1d2e3f4a5b6c",
                "object": "chat.completion.chunk",
                "created": 1760700000,
                "model": model,
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


_SERVED = "gen_ai.response.model"
# Each served id differs from the id crivo asks for (DEFAULT_MODEL,
# CLAUDE_DEFAULT_MODEL), so a span that copied the request model cannot pass
# for one that read the stream.
_DEEPSEEK_SERVED = "deepseek-v4-pro-0926"
_CLAUDE_SERVED = "claude-opus-5-5-20261001"
_START_USAGE = {"input_tokens": 1200, "output_tokens": 1}


def _call_spans(path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return [r["attrs"] for r in rows if r["name"] == "gen_ai.client.call"]


def _client_serving(*streams):
    """A client double for either SDK that answers each call with the next
    stream in line, so one test can make several calls through one seam."""
    queued = iter(streams)

    def create(**_):
        return iter(next(queued))

    return SimpleNamespace(
        messages=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )


@pytest.mark.parametrize(
    ("provider", "seam", "env", "stream", "served"),
    [
        # DeepSeek repeats the id on its chunks, the final usage-only one
        # included
        pytest.param(
            "deepseek",
            "_get_client",
            {},
            lambda: [
                chunk(reasoning="weighing the medians", model=_DEEPSEEK_SERVED),
                *_deepseek_stream(_DEEPSEEK_SERVED),
            ],
            _DEEPSEEK_SERVED,
            id="deepseek",
        ),
        # an OpenRouter arm: the endpoint resolves the name crivo asked for
        # to a dated snapshot, and only the stream says which
        pytest.param(
            "openai",
            "_get_openai_client",
            {"CRIVO_MODEL": "qwen/qwen3-32b"},
            lambda: [
                chunk(reasoning="weighing the medians", model="qwen/qwen3-32b-04-28"),
                chunk(content="RS-1 grew most.", model="qwen/qwen3-32b-04-28"),
            ],
            "qwen/qwen3-32b-04-28",
            id="openrouter",
        ),
        # an empty id names nothing, and a later chunk naming another id does
        # not replace the first one seen (decided on #64)
        pytest.param(
            "deepseek",
            "_get_client",
            {},
            lambda: [
                chunk(reasoning="weighing the medians", model=""),
                chunk(reasoning="the medians, by district", model=_DEEPSEEK_SERVED),
                *_deepseek_stream("deepseek-v4-pro-1015"),
            ],
            _DEEPSEEK_SERVED,
            id="first-non-empty-id-wins",
        ),
    ],
)
def test_an_openai_compatible_span_names_the_model_that_served_it(
    tmp_path, monkeypatch, provider, seam, env, stream, served
):
    """EV1 (#64): the span recorded only gen_ai.request.model, the id crivo
    asked for. An eval row has to record the model that answered, so it can
    notice a provider changing the model behind a name, and every
    OpenAI-compatible chunk carries that id as `model`."""
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CRIVO_TELEMETRY", str(path))
    monkeypatch.setenv("CRIVO_PROVIDER", provider)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(llm, seam, lambda: fake_client(iter(stream())))

    reply = "".join(llm.generate([{"role": "user", "content": "q"}]))
    assert reply == "RS-1 grew most."

    attrs = _call_attrs(path)
    assert attrs.get(_SERVED) == served
    assert attrs["gen_ai.request.model"] == llm.model_name(), "still what we asked"


def test_a_claude_span_names_the_model_message_start_reports(tmp_path, monkeypatch):
    """EV1 (#64): Anthropic names the served model once, as message_start's
    `message.model`, on the same event that carries the input and cache
    counts. No other event in the stream carries it."""
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CRIVO_TELEMETRY", str(path))
    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    stream = _claude_stream(_START_USAGE, model=_CLAUDE_SERVED)
    monkeypatch.setattr(
        llm, "_get_claude_client", lambda: fake_claude_client(iter(stream))
    )

    reply = "".join(llm.generate([{"role": "user", "content": "q"}]))
    assert reply == "RS-1 grew most."

    attrs = _call_attrs(path)
    assert attrs.get(_SERVED) == _CLAUDE_SERVED
    assert attrs["gen_ai.request.model"] == llm.CLAUDE_DEFAULT_MODEL


@pytest.mark.parametrize(
    ("provider", "seam", "reported", "served", "unreported"),
    [
        pytest.param(
            "deepseek",
            "_get_client",
            [chunk(content="RS-1 grew most.", model=_DEEPSEEK_SERVED)],
            _DEEPSEEK_SERVED,
            [chunk(content="RS-1 grew most.")],
            id="openai-chunk-without-a-model-field",
        ),
        pytest.param(
            "deepseek",
            "_get_client",
            [chunk(content="RS-1 grew most.", model=_DEEPSEEK_SERVED)],
            _DEEPSEEK_SERVED,
            [chunk(content="RS-1 grew most.", model="")],
            id="openai-chunk-with-an-empty-model",
        ),
        # no message_start reached us, so nothing named the model
        pytest.param(
            "claude",
            "_get_claude_client",
            _claude_stream(_START_USAGE, model=_CLAUDE_SERVED),
            _CLAUDE_SERVED,
            _claude_stream(None),
            id="claude-without-message-start",
        ),
        pytest.param(
            "claude",
            "_get_claude_client",
            _claude_stream(_START_USAGE, model=_CLAUDE_SERVED),
            _CLAUDE_SERVED,
            _claude_stream(_START_USAGE, model=""),
            id="claude-message-start-with-an-empty-model",
        ),
    ],
)
def test_a_call_whose_stream_names_no_model_leaves_the_attribute_out(
    tmp_path, monkeypatch, provider, seam, reported, served, unreported
):
    """EV1 (#64): a call whose stream names no model, or an empty one,
    records no gen_ai.response.model at all: not "", not "unknown", and not
    the id that served the call before it. An eval reads a present value as
    what the provider said, so a placeholder or a carried-over id is a false
    record. The first call, whose stream does name its model, is the control
    that the attribute is recorded at all."""
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CRIVO_TELEMETRY", str(path))
    monkeypatch.setenv("CRIVO_PROVIDER", provider)
    client = _client_serving(reported, unreported)
    monkeypatch.setattr(llm, seam, lambda: client)

    for _ in range(2):
        reply = "".join(llm.generate([{"role": "user", "content": "q"}]))
        assert reply == "RS-1 grew most."

    first, second = _call_spans(path)
    assert first.get(_SERVED) == served
    assert _SERVED not in second, (
        f"recorded {second[_SERVED]!r} for a call whose stream named no model"
    )


def _peer_drops(release):
    raise ConnectionError(
        "peer closed connection without sending complete message body"
    )


def _goes_silent(release):
    time.sleep(0.5)  # bounded, so a regression fails fast instead of hanging


def _waits_for_cancel(release):
    release.wait(5)


@pytest.mark.parametrize(
    ("provider", "seam", "head", "served"),
    [
        pytest.param(
            "deepseek",
            "_get_client",
            [chunk(reasoning="weighing the medians", model=_DEEPSEEK_SERVED)],
            _DEEPSEEK_SERVED,
            id="deepseek",
        ),
        pytest.param(
            "claude",
            "_get_claude_client",
            [
                _claude_stream(_START_USAGE, model=_CLAUDE_SERVED)[0],
                claude_event(thinking="weighing the medians"),
            ],
            _CLAUDE_SERVED,
            id="claude",
        ),
    ],
)
@pytest.mark.parametrize(
    ("then", "error"),
    [
        pytest.param(_peer_drops, ConnectionError, id="raises"),
        pytest.param(_goes_silent, TimeoutError, id="stalls"),
        pytest.param(_waits_for_cancel, llm.CallCancelled, id="cancelled"),
    ],
)
def test_a_call_that_dies_after_the_model_arrived_still_names_it(
    tmp_path, monkeypatch, provider, seam, head, served, then, error
):
    """EV1 (#64): telemetry.span emits from a `finally`, so a call that is
    cancelled, times out or fails mid-stream still leaves a span, and those
    are often the longest and costliest calls in a run. Once the stream has
    named its model, the span keeps that id whatever ends the call (decided
    on #64: the first id is recorded when it arrives, not after the stream
    completes)."""
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CRIVO_TELEMETRY", str(path))
    monkeypatch.setenv("CRIVO_PROVIDER", provider)
    if error is TimeoutError:
        monkeypatch.setattr(llm, "STALL_S", 0.05)
    release = threading.Event()

    def stream():
        yield from head
        then(release)

    client = _client_serving(stream())
    monkeypatch.setattr(llm, seam, lambda: client)

    reply = llm.generate([{"role": "user", "content": "q"}])
    try:
        assert next(reply) == "", "the model-bearing item arrives as a heartbeat"
        if error is llm.CallCancelled:
            llm.request_cancel()  # the REPL's Ctrl-C, mid-think
        with pytest.raises(error):
            next(reply)
    finally:
        release.set()

    assert _call_attrs(path).get(_SERVED) == served


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
