"""Agent-mode bench lane units (spec: specs/2026-09-03-agent-bench-design.md).

Everything here is keyless and offline: the lane must be import-safe and
testable on CI machines that have no model key (spec acceptance).
"""

import pytest

from bench import agent_run


def test_require_key_exits_without_key(monkeypatch):
    for var in ("CRIVO_PROVIDER", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit):
        agent_run._require_key()


def test_require_key_accepts_an_openrouter_arm(monkeypatch):
    """BP3: an OpenRouter arm runs on CRIVO_PROVIDER=openai with an endpoint,
    a model and the endpoint's own key. It holds no DeepSeek or Anthropic key
    and must not be refused for lacking one."""
    monkeypatch.setenv("CRIVO_PROVIDER", "openai")
    monkeypatch.setenv("CRIVO_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("CRIVO_MODEL", "qwen/qwen3-32b")
    monkeypatch.setenv("CRIVO_API_KEY", "sk-or-test")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    try:
        agent_run._require_key()
    except SystemExit as exc:
        pytest.fail(f"the OpenRouter arm was refused: {exc.code}")


def test_require_key_names_the_configured_providers_key(monkeypatch):
    """BP3: under claude, a DeepSeek key is not a model key. Passing the gate
    on it only defers the failure to llm.py's KeyError mid-run; the gate must
    stop and name ANTHROPIC_API_KEY. The claude arm with its own key runs."""
    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        agent_run._require_key()
    assert "ANTHROPIC_API_KEY" in str(exc.value.code)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    agent_run._require_key()  # no SystemExit: the right key is set


def test_require_key_refuses_a_provider_that_does_not_exist(monkeypatch):
    """BP3: CRIVO_PROVIDER=openrouter is a natural slip for an OpenRouter arm.
    llm routes any unknown value to DeepSeek, so with a DeepSeek key on hand
    the arm would run on DeepSeek under another arm's name. The gate refuses
    and lists the providers that exist."""
    monkeypatch.setenv("CRIVO_PROVIDER", "openrouter")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with pytest.raises(SystemExit) as exc:
        agent_run._require_key()
    assert "deepseek, claude, openai, faux" in str(exc.value.code)


def test_load_dotenv_fills_missing_but_never_overwrites(tmp_path, monkeypatch):
    import os

    env = tmp_path / ".env"
    env.write_text('A_FRESH_VAR="from-file"\nALREADY_SET=from-file\n# comment\n')
    monkeypatch.delenv("A_FRESH_VAR", raising=False)
    monkeypatch.setenv("ALREADY_SET", "from-env")
    agent_run._load_dotenv(env)
    assert os.environ["A_FRESH_VAR"] == "from-file"
    assert os.environ["ALREADY_SET"] == "from-env"
    monkeypatch.delenv("A_FRESH_VAR", raising=False)


def test_mean_ignores_none_and_empty():
    assert agent_run._mean([1.0, None, 3.0]) == 2.0
    assert agent_run._mean([]) is None
    assert agent_run._mean([None]) is None


def test_drive_auto_approves_plain_gates_and_counts_events():
    import time

    from crivo.events import GateDecision, GateRequest

    seen = []

    def gen():
        answer = yield GateRequest(code="df.head()", iteration=1)
        seen.append(answer)
        answer = yield "not-a-gate"
        seen.append(answer)

    n = agent_run._drive(gen(), max_events=10, wall_cap=60.0, t0=time.monotonic())
    assert n == 2
    assert isinstance(seen[0], GateDecision) and seen[0].action == "run"
    assert seen[1] is None


def test_drive_skips_human_gates():
    """Skill admissions and judgement calls are a person's to decide — the
    headless bench must never fake-approve them (events.GateRequest.grade)."""
    import time

    from crivo.events import GateRequest

    seen = []

    def gen():
        answer = yield GateRequest(code="admit_skill()", iteration=1, grade="HUMAN")
        seen.append(answer)

    agent_run._drive(gen(), max_events=10, wall_cap=60.0, t0=time.monotonic())
    assert seen[0].action == "skip"


def test_drive_collects_gate_actions():
    """The lane must record what it decided at each gate, so a case that
    changed nothing can say WHY (skipped judgement calls are a result)."""
    import time

    from crivo.events import GateRequest

    def gen():
        yield GateRequest(code="a", iteration=1)
        yield GateRequest(code="b", iteration=1, grade="HUMAN")

    gates: list = []
    agent_run._drive(
        gen(), max_events=10, wall_cap=60.0, t0=time.monotonic(), gates=gates
    )
    assert gates == ["run", "skip"]


def test_drive_approve_policy_runs_human_gates_but_never_admissions():
    """--human-gates approve is the owner's standing pre-authorisation for
    judgement-call fixes (the ceiling arm). Skill admission is governance and
    stays skipped in every mode."""
    import time

    from crivo.events import GateRequest

    seen = []

    def gen():
        a = yield GateRequest(
            code="fix()", iteration=1, grade="HUMAN", title="d12 · person call"
        )
        seen.append(a)
        a = yield GateRequest(
            code="admit",
            iteration=1,
            grade="HUMAN",
            title="admit skill fix-x · d3 · reproduces the case it came from",
        )
        seen.append(a)

    gates: list = []
    agent_run._drive(
        gen(),
        max_events=10,
        wall_cap=60.0,
        t0=time.monotonic(),
        gates=gates,
        human_gates="approve",
    )
    assert [d.action for d in seen] == ["run", "skip"]
    assert gates == ["run", "skip"]


def test_drive_event_cap_aborts():
    import time

    def endless():
        while True:
            yield "event"

    with pytest.raises(agent_run.CaseAborted):
        agent_run._drive(endless(), max_events=5, wall_cap=60.0, t0=time.monotonic())


def test_handoff_prefers_parquet_and_records_csv_fallback(tmp_path):
    import pandas as pd

    clean = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    assert agent_run._handoff(clean, tmp_path / "clean") == "parquet"
    assert (tmp_path / "clean.parquet").exists()

    mixed = pd.DataFrame({"c": [1, "x"]})  # arrow refuses mixed-type objects
    assert agent_run._handoff(mixed, tmp_path / "messy") == "csv"
    assert (tmp_path / "messy.csv").exists()


def test_run_case_gives_each_case_an_isolated_skills_dir(tmp_path, monkeypatch):
    """The bench must never touch the repo's live skills/ — a retirement
    during a bench run deleted a real skill (2026-09-03). Sessions get a
    per-case skills dir under the work folder."""
    import argparse

    import pandas as pd

    captured = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.session_dir = tmp_path / "sess"

        def load(self, path, name):
            pass

        def clean(self, var):
            return iter(())

        def close(self):
            pass

    monkeypatch.setattr("crivo.loop.Session", FakeSession)
    df = pd.DataFrame({"a": [1, 2]})
    monkeypatch.setattr(agent_run.corpus, "build", lambda entry: (df, df, None))
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")
    args = argparse.Namespace(
        docker=False, max_events=10, wall_cap=5.0, human_gates="skip"
    )

    row = agent_run._run_case({"name": "iso_case", "diseases": [1]}, args)
    assert row["status"] == "no_cleaned_output"
    assert row["model"]["provider"]  # provenance: every row names its model
    assert "skills_dir" in captured, "Session must get an explicit skills_dir"
    assert captured["skills_dir"].startswith(str(tmp_path / "res"))


def test_repeat_runs_each_case_k_times_with_distinct_files(tmp_path, monkeypatch):
    """--repeat k gives pass^k k rows per case under distinct .rN names, and
    tags each row with its run index (A4)."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(
        agent_run.corpus,
        "SMOKE",
        [{"name": "rep_case", "diseases": [4]}],
        raising=False,
    )
    seen: list = []

    def fake_run(entry, args):
        seen.append(entry["name"])
        return {
            "name": entry["name"],
            "status": "ok",
            "wall_secs": 0.1,
            "scores": {"repair": {"f1": 1.0}},
        }

    monkeypatch.setattr(agent_run, "_run_case", fake_run)
    agent_run.main(["--sample", "1", "--repeat", "3"])

    assert seen == ["rep_case"] * 3
    files = sorted(p.name for p in tmp_path.glob("rep_case.r*.json"))
    assert files == ["rep_case.r1.json", "rep_case.r2.json", "rep_case.r3.json"]
    import json as _json

    assert _json.loads((tmp_path / "rep_case.r2.json").read_text())["run"] == 2


def test_policies_auto_mints_one_record_and_reaches_the_session(
    tmp_path, monkeypatch, capsys
):
    """T1.4 bench arm: --policies auto builds the bench-auto ENFORCE record
    over every fixer-backed disease and passes it into the Session."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")
    entry = {"name": "pol_case", "diseases": [4]}
    monkeypatch.setattr(agent_run.corpus, "SMOKE", [entry], raising=False)
    captured = {}

    def grab(args_entry, args):
        captured["policies"] = args.policy_records
        return {"name": "pol_case", "status": "error: stub", "wall_secs": 0.1}

    monkeypatch.setattr(agent_run, "_run_case", grab)
    agent_run.main(["--sample", "1", "--policies", "auto"])

    records = captured["policies"]
    assert len(records) == 1 and records[0].id == "bench-auto"
    assert records[0].mode == "ENFORCE"
    assert set(records[0].disease_ids) == set(agent_run.FIXERS)


def _fake_session(tmp_path, monkeypatch, on_init=None):
    """The FakeSession pattern from the isolated-skills-dir test, shared by
    the telemetry tests (T1.5): no model, no kernel, no cleaned output."""
    import pandas as pd

    class FakeSession:
        def __init__(self, **kwargs):
            if on_init is not None:
                on_init()
            self.session_dir = tmp_path / "sess"

        def load(self, path, name):
            pass

        def clean(self, var):
            return iter(())

        def close(self):
            pass

    monkeypatch.setattr("crivo.loop.Session", FakeSession)
    df = pd.DataFrame({"a": [1, 2]})
    monkeypatch.setattr(agent_run.corpus, "build", lambda entry: (df, df, None))
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")


def test_run_case_points_telemetry_at_a_fresh_per_case_file_and_restores_env(
    tmp_path, monkeypatch
):
    """T1.5: CRIVO_TELEMETRY names a per-case JSONL under RESULTS_DIR before
    the Session exists, stale spans from an earlier run are removed first,
    and the previous env value is restored so nothing leaks between cases."""
    import argparse
    import json
    import os

    expected = tmp_path / "res" / "telemetry" / "tele_case.jsonl"
    expected.parent.mkdir(parents=True)
    expected.write_text(json.dumps({"name": "gen_ai.client.call", "dur_s": 9.9}) + "\n")
    seen = {}
    _fake_session(
        tmp_path,
        monkeypatch,
        on_init=lambda: seen.update(env=os.environ.get("CRIVO_TELEMETRY")),
    )
    monkeypatch.setenv("CRIVO_TELEMETRY", "sentinel-before")
    # the caps sit at their defaults so the filename under test carries only
    # the arm; a non-default cap is its own arm and names itself
    args = argparse.Namespace(
        docker=False,
        max_events=agent_run.DEFAULT_MAX_EVENTS,
        wall_cap=agent_run.DEFAULT_WALL_CAP,
        human_gates="skip",
    )

    row = agent_run._run_case({"name": "tele_case", "diseases": [1]}, args)
    assert seen["env"] == str(expected)
    assert os.environ["CRIVO_TELEMETRY"] == "sentinel-before"
    assert not expected.exists(), "stale telemetry must be removed before the run"
    # new_work_tokens was pinned at 0 here, which is the bug: a case whose
    # telemetry reported nothing does not know what it cost, and the count and
    # the wait do not know either
    assert row["calls"] == {
        "count": None,
        "model_wait_s": None,
        "new_work_tokens": None,
    }


def test_run_case_ceiling_arm_gets_its_own_telemetry_file_and_unsets_cleanly(
    tmp_path, monkeypatch
):
    """T1.5: the approve arm writes name.ceiling.jsonl so the two arms never
    share spans, and a previously unset env var ends the case unset."""
    import argparse
    import os

    seen = {}
    _fake_session(
        tmp_path,
        monkeypatch,
        on_init=lambda: seen.update(env=os.environ.get("CRIVO_TELEMETRY")),
    )
    monkeypatch.delenv("CRIVO_TELEMETRY", raising=False)
    args = argparse.Namespace(
        docker=False,
        max_events=agent_run.DEFAULT_MAX_EVENTS,
        wall_cap=agent_run.DEFAULT_WALL_CAP,
        human_gates="approve",
    )

    agent_run._run_case({"name": "tele_case", "diseases": [1]}, args)
    assert seen["env"] == str(
        tmp_path / "res" / "telemetry" / "tele_case.ceiling.jsonl"
    )
    assert "CRIVO_TELEMETRY" not in os.environ


def test_call_stats_sums_client_call_spans_and_tolerates_gaps(tmp_path):
    """T1.5: calls per case, model wait, and token sums come only from the
    gen_ai.client.call spans; missing rows, fields, or junk lines degrade to
    zeros/absent keys, never an exception."""
    import json

    tele = tmp_path / "case.jsonl"
    spans = [
        {
            "name": "gen_ai.client.call",
            "dur_s": 1.5,
            "attrs": {
                "gen_ai.usage.input_tokens": 100,
                "gen_ai.usage.output_tokens": 10,
                "crivo.cache.hit_tokens": 60,
                "crivo.cache.miss_tokens": 40,
            },
        },
        {"name": "kernel.exec", "dur_s": 9.0, "attrs": {}},
        {
            "name": "gen_ai.client.call",
            "dur_s": 0.25,
            "attrs": {"gen_ai.usage.input_tokens": 50},
        },
        {"name": "gen_ai.client.call"},
    ]
    tele.write_text("\n".join(json.dumps(s) for s in spans) + "\nnot json\n")

    stats = agent_run._call_stats(tele)
    # every sum still tolerates the junk line and the absent fields. The total
    # does not: the third call reported no usage, so 150 - 60 + 10 would be a
    # knowably short sum published as this case's whole cost.
    assert stats == {
        "count": 3,
        "model_wait_s": 1.75,
        "input_tokens": 150,
        "output_tokens": 10,
        "cache_hit_tokens": 60,
        "cache_miss_tokens": 40,
        "new_work_tokens": None,
    }
    # no file, so nothing is known about this case: not the cost, and not the
    # calls or the wait either. Those two read 0 until the row said "unknown
    # cost, 0 calls" in one breath.
    assert agent_run._call_stats(tmp_path / "absent.jsonl") == {
        "count": None,
        "model_wait_s": None,
        "new_work_tokens": None,
    }


def test_call_stats_reports_unknown_tokens_rather_than_zero(tmp_path):
    """A paid run whose spans carried no token attribute must not be
    indistinguishable from a free one. When nothing reported usage the cost
    basis is unknown, so new_work_tokens is None, not 0. This is the shape a
    real run writes whenever the provider reports no usage."""
    import json

    tele = tmp_path / "silent.jsonl"
    spans = [
        {
            "name": "gen_ai.client.call",
            "dur_s": 2.0,
            "attrs": {"gen_ai.system": "claude", "gen_ai.request.model": "m"},
        },
        {"name": "gen_ai.client.call", "dur_s": 1.0},
    ]
    tele.write_text("\n".join(json.dumps(s) for s in spans) + "\n")

    stats = agent_run._call_stats(tele)
    assert stats["count"] == 2, "the calls were made, and billed"
    assert stats["model_wait_s"] == 3.0
    assert stats["new_work_tokens"] is None, "unknown cost, not free"
    # no file at all is the same kind of ignorance
    assert agent_run._call_stats(tmp_path / "absent.jsonl")["new_work_tokens"] is None


def test_call_stats_keeps_a_genuinely_zero_count_as_zero(tmp_path):
    """The other side of the same distinction: a span that did report usage
    and reported nothing chargeable is a real 0, not unknown."""
    import json

    tele = tmp_path / "zero.jsonl"
    tele.write_text(
        json.dumps(
            {
                "name": "gen_ai.client.call",
                "attrs": {
                    "gen_ai.usage.input_tokens": 0,
                    "gen_ai.usage.output_tokens": 0,
                },
            }
        )
        + "\n"
    )

    assert agent_run._call_stats(tele)["new_work_tokens"] == 0


def test_call_stats_zero_calls_is_free_not_unknown(tmp_path):
    """`unknown` is for ignorance, and a readable telemetry file that records
    no model call at all is not ignorance: the deterministic policy path
    solved the case and nothing was billed. Three of the real on-disk
    telemetry files have exactly this shape, so calling them unknown drops
    them out of the token mean and leaves it several times too high."""
    import json

    tele = tmp_path / "deterministic.jsonl"
    spans = [
        {"name": "crivo.policy.decision", "dur_s": 0.01, "attrs": {"grade": "AUTO"}},
        {"name": "crivo.trajectory", "dur_s": 4.0, "attrs": {}},
    ]
    tele.write_text("\n".join(json.dumps(s) for s in spans) + "\n")

    stats = agent_run._call_stats(tele)
    assert stats["count"] == 0
    assert stats["new_work_tokens"] == 0, "no call was made, so nothing was spent"
    # the distinction that makes it meaningful: no readable telemetry at all
    # stays unknown, because then we do not know whether a call was made
    assert agent_run._call_stats(tmp_path / "absent.jsonl")["new_work_tokens"] is None


def test_call_stats_needs_the_terms_the_arithmetic_actually_adds(tmp_path):
    """new_work_tokens is input - cache hits + output. The cache counters
    alone say nothing about new work: a miss-only span would certify 0 for a
    paid call, and a hit-only span would publish a negative token count as
    fact. Only the additive terms can decide the cost basis is known."""
    import json

    def _stats(name: str, attrs: dict) -> dict:
        tele = tmp_path / f"{name}.jsonl"
        tele.write_text(
            json.dumps({"name": "gen_ai.client.call", "attrs": attrs}) + "\n"
        )
        return agent_run._call_stats(tele)

    assert _stats("miss", {"crivo.cache.miss_tokens": 117})["new_work_tokens"] is None
    assert _stats("hit", {"crivo.cache.hit_tokens": 5120})["new_work_tokens"] is None
    # BOTH additive terms present is a real reading, cache hits subtracted
    both = _stats(
        "both",
        {
            "gen_ai.usage.input_tokens": 900,
            "gen_ai.usage.output_tokens": 200,
            "crivo.cache.hit_tokens": 512,
        },
    )
    assert both["new_work_tokens"] == 588


def test_one_additive_term_alone_is_not_a_cost_basis(tmp_path):
    """The priced check was an `any` over the two terms the sum adds, so a
    span reporting input and no output was declared priced and its output
    contributed 0. That is the same knowably-short total the whole-case rule
    below refuses, one level down, and it reads as a cheap call rather than
    as an unknown one."""
    import json

    def _stats(name: str, attrs: dict) -> dict:
        tele = tmp_path / f"{name}.jsonl"
        tele.write_text(
            json.dumps({"name": "gen_ai.client.call", "attrs": attrs}) + "\n"
        )
        return agent_run._call_stats(tele)

    assert _stats("in", {"gen_ai.usage.input_tokens": 900})["new_work_tokens"] is None
    assert _stats("out", {"gen_ai.usage.output_tokens": 200})["new_work_tokens"] is None
    # the readings themselves are still kept, they just do not make a total
    assert _stats("in2", {"gen_ai.usage.input_tokens": 900})["input_tokens"] == 900


def test_absent_telemetry_publishes_an_unknown_count_not_a_zero_one(tmp_path):
    """The same return said two things: new_work_tokens None ("we do not know
    whether a call was made") beside count 0 ("no call was made"). The count
    is the more legible of the two and it is the one that was wrong, so a
    reader of the row concluded the case ran free."""
    stats = agent_run._call_stats(tmp_path / "never-written.jsonl")

    assert stats["new_work_tokens"] is None
    assert stats["count"] is None, "an unreadable file cannot certify zero calls"
    assert stats["model_wait_s"] is None, "nor zero seconds of model wait"


def test_call_stats_will_not_publish_a_partial_sum_as_the_whole_case(tmp_path):
    """telemetry.span emits from a `finally` and llm.generate maps usage only
    after the stream completes, so a cancelled or failed call leaves a call
    span carrying no usage. Summing the calls that did report and printing it
    as the case total states a number that is knowably short. This is the
    shape of the real bench/results/agent/telemetry/tx-excel-ids.jsonl, whose
    sixth and longest call reported nothing."""
    import json

    tele = tmp_path / "partial.jsonl"
    spans = [
        {
            "name": "gen_ai.client.call",
            "dur_s": 7.4,
            "attrs": {
                "gen_ai.usage.input_tokens": 1141,
                "gen_ai.usage.output_tokens": 439,
                "crivo.cache.hit_tokens": 1024,
            },
        },
        {
            "name": "gen_ai.client.call",
            "dur_s": 203.8,
            "attrs": {"gen_ai.request.model": "deepseek-v4-pro"},
        },
    ]
    tele.write_text("\n".join(json.dumps(s) for s in spans) + "\n")

    stats = agent_run._call_stats(tele)
    assert stats["count"] == 2, "both calls happened, and both were billed"
    assert stats["input_tokens"] == 1141, "the readings we do have are still kept"
    assert stats["new_work_tokens"] is None, "556 would be knowably short"


def test_main_prints_unknown_tokens_as_unknown_never_as_zero(
    tmp_path, monkeypatch, capsys
):
    """The cost column is the only place a reader sees what a run spent.
    A case with no token data prints `unknown`; printing 0 would report a
    paid run as a free one. The aggregate mean skips the unknowns, and says
    how many cases it actually covered."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path)
    entry = {"name": "silent_case", "diseases": [1]}
    monkeypatch.setattr(agent_run.corpus, "SMOKE", [entry], raising=False)
    row = {
        "name": "silent_case",
        "status": "ok",
        "wall_secs": 3.2,
        "events": 7,
        "scores": {"repair": {"f1": 0.5, "recall": 0.5}},
        "calls": {"count": 4, "model_wait_s": 2.1, "new_work_tokens": None},
    }
    monkeypatch.setattr(agent_run, "_run_case", lambda entry, args: row)

    assert agent_run.main(["--sample", "1"]) == 0
    out = capsys.readouterr().out
    assert "4 calls" in out, "the calls themselves are still known"
    assert "unknown new-work tok" in out
    assert "0 new-work tok" not in out
    assert "new-work tokens mean unknown" in out
    assert "0/1 scored cases with token data" in out


def test_token_mean_covers_only_the_cases_that_reported_tokens(tmp_path, monkeypatch):
    """An unknown case must not be averaged in as a zero, which would drag
    the mean down and hide that the run does not know what it spent. The mean
    is over the cases with token data and publishes that denominator."""
    assert agent_run._mean([200, None]) == 200.0
    assert agent_run._tokens_text(None) == "unknown"
    assert agent_run._tokens_text(0) == "0"
    assert agent_run._tokens_text(150) == "150"


def test_main_prints_calls_per_case_and_in_the_aggregate(tmp_path, monkeypatch, capsys):
    """T1.5: the per-case line and the final aggregate carry the calls
    summary (count, new-work tokens) alongside the scores."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path)
    entry = {"name": "fresh_case", "diseases": [1]}
    monkeypatch.setattr(agent_run.corpus, "SMOKE", [entry], raising=False)
    row = {
        "name": "fresh_case",
        "status": "ok",
        "wall_secs": 3.2,
        "events": 7,
        "scores": {"repair": {"f1": 0.5, "recall": 0.5}},
        "calls": {"count": 4, "model_wait_s": 2.1, "new_work_tokens": 200},
    }
    monkeypatch.setattr(agent_run, "_run_case", lambda entry, args: row)

    assert agent_run.main(["--sample", "1"]) == 0
    out = capsys.readouterr().out
    assert "4 calls" in out
    assert "200 new-work tok" in out
    assert "calls mean 4.0" in out
    assert "new-work tokens mean 200.0" in out


def test_main_skips_cases_already_on_disk(tmp_path, monkeypatch):
    """R5: a finished case is never rerun without --force, never re-billed."""
    import json

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path)
    entry = {"name": "done_case", "diseases": [1]}
    monkeypatch.setattr(agent_run.corpus, "SMOKE", [entry], raising=False)
    (tmp_path / "done_case.json").write_text(
        json.dumps(
            {"name": "done_case", "status": "ok", "scores": {"repair": {"f1": 1.0}}}
        )
    )

    def boom(*a, **k):
        raise AssertionError("_run_case called for a finished case")

    monkeypatch.setattr(agent_run, "_run_case", boom)
    assert agent_run.main(["--sample", "1"]) == 0


# --- arm naming and the autonomy arms (autonomy-default packet 5) -----------


def test_arm_suffix_names_every_knob_that_changes_the_arm():
    """The result and telemetry names are also the resume key, so every knob
    that changes what an arm measures has to appear in them. The default arm
    keeps the empty suffix and the ceiling arm keeps `.ceiling`, so the
    results already on disk stay addressable."""
    import argparse

    def suffix(**kwargs):
        base = {"human_gates": "skip", "policies": "none", "autonomy": None}
        return agent_run._arm_suffix(argparse.Namespace(**{**base, **kwargs}))

    assert suffix() == ""
    assert suffix(human_gates="approve") == ".ceiling"
    assert suffix(policies="auto") == ".policies-auto"
    assert suffix(autonomy="autonomous") == ".autonomous"
    assert suffix(autonomy="careful") == ".careful"
    assert suffix(policies="auto", autonomy="autonomous") == (
        ".policies-auto.autonomous"
    )
    # a namespace that predates a knob (the older test fixtures) still names
    # the default arm rather than raising
    assert agent_run._arm_suffix(argparse.Namespace(human_gates="skip")) == ""


def test_the_sandbox_and_the_caps_are_knobs_that_change_the_arm():
    """`--docker` moves the run off the host kernel and `--wall-cap` /
    `--max-events` decide how much of a case gets to finish, so all three
    change what an arm measures. None of them reached the filename, so a
    sandboxed run resumed the host-kernel run's result file and republished
    its row as its own - the exact failure the docstring above says the
    suffix prevents."""
    import argparse

    def suffix(**kwargs):
        base = {
            "human_gates": "skip",
            "policies": "none",
            "autonomy": None,
            "docker": False,
            "wall_cap": agent_run.DEFAULT_WALL_CAP,
            "max_events": agent_run.DEFAULT_MAX_EVENTS,
        }
        return agent_run._arm_suffix(argparse.Namespace(**{**base, **kwargs}))

    assert suffix() == "", "the default arm keeps the empty suffix"
    assert suffix(docker=True) == ".docker"
    assert suffix(wall_cap=60.0) == ".wall-cap-60"
    assert suffix(max_events=500) == ".max-events-500"
    assert suffix(docker=True, wall_cap=60.0, max_events=500) == (
        ".docker.wall-cap-60.max-events-500"
    )
    # the resume key is the whole point: these arms must not collide
    assert suffix(docker=True) != suffix(docker=False)
    assert suffix(wall_cap=60.0) != suffix(wall_cap=120.0)


@pytest.mark.parametrize(
    "first,second",
    [
        ([], ["--policies", "auto"]),
        ([], ["--autonomy", "autonomous"]),
        (["--autonomy", "careful"], ["--autonomy", "autonomous"]),
        (["--policies", "auto"], ["--policies", "auto", "--autonomy", "autonomous"]),
    ],
)
def test_two_arms_cannot_read_each_others_result_files(
    tmp_path, monkeypatch, first, second
):
    """R5 skips a case whose result file exists. If two arms share a filename
    the second arm resumes the first arm's row and prints the first arm's
    numbers as its own, which is how the batched arm silently reported the
    baseline's score. Each arm writes and reads its own file."""
    import json

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path)
    entry = {"name": "arm_case", "diseases": [4]}
    monkeypatch.setattr(agent_run.corpus, "SMOKE", [entry], raising=False)
    ran: list = []

    def fake_run(entry, args):
        ran.append(len(ran))
        return {
            "name": entry["name"],
            "status": "ok",
            "wall_secs": 0.1,
            "arm": len(ran),
            "scores": {"repair": {"f1": float(len(ran))}},
        }

    monkeypatch.setattr(agent_run, "_run_case", fake_run)
    agent_run.main(["--sample", "1", *first])
    agent_run.main(["--sample", "1", *second])

    assert ran == [0, 1], "the second arm resumed the first arm's result file"
    written = sorted(p.name for p in tmp_path.glob("arm_case*.json"))
    assert len(written) == 2, f"arms shared a filename: {written}"
    arms = {json.loads((tmp_path / n).read_text())["arm"] for n in written}
    assert arms == {1, 2}


def test_run_case_records_the_policy_arm_in_the_row(tmp_path, monkeypatch):
    """The saved row named its gate arm but not its policy arm, so a batched
    result was indistinguishable from a baseline one after the fact."""
    import argparse

    _fake_session(tmp_path, monkeypatch)
    args = argparse.Namespace(
        docker=False,
        max_events=10,
        wall_cap=5.0,
        human_gates="skip",
        policies="auto",
        autonomy=None,
        policy_records=[],
    )

    row = agent_run._run_case({"name": "arm_case", "diseases": [1]}, args)
    assert row["policies"] == "auto"
    assert row["human_gates"] == "skip"


def test_run_case_passes_the_autonomy_arm_into_the_session(tmp_path, monkeypatch):
    """The autonomous arm's extra reach comes from the Session seeding its own
    default AUTO policy, not from approving anything a person owns: the arm
    still drives with human_gates skip."""
    import argparse

    seen = {}

    class FakeSession:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.session_dir = tmp_path / "sess"

        def load(self, path, name):
            pass

        def clean(self, var):
            return iter(())

        def close(self):
            pass

    import pandas as pd

    monkeypatch.setattr("crivo.loop.Session", FakeSession)
    df = pd.DataFrame({"a": [1, 2]})
    monkeypatch.setattr(agent_run.corpus, "build", lambda entry: (df, df, None))
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")
    args = argparse.Namespace(
        docker=False,
        max_events=10,
        wall_cap=5.0,
        human_gates="skip",
        policies="none",
        autonomy="autonomous",
        policy_records=[],
    )

    row = agent_run._run_case({"name": "auto_case", "diseases": [1]}, args)
    assert seen["autonomy"] == "autonomous"
    assert seen["policies"] == [], "the arm leaves the Session to seed its own"
    assert row["autonomy"] == "autonomous"
    assert row["human_gates"] == "skip"


def test_run_case_without_an_autonomy_arm_pins_careful(tmp_path, monkeypatch):
    """An unset --autonomy is the baseline arm, and the baseline results on
    disk were recorded gating every AUTO finding. The bench pins `careful`
    rather than inheriting the Session's autonomous default, so the empty
    suffix keeps meaning what those files say."""
    import argparse

    seen = {}

    class FakeSession:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.session_dir = tmp_path / "sess"

        def load(self, path, name):
            pass

        def clean(self, var):
            return iter(())

        def close(self):
            pass

    import pandas as pd

    monkeypatch.setattr("crivo.loop.Session", FakeSession)
    df = pd.DataFrame({"a": [1, 2]})
    monkeypatch.setattr(agent_run.corpus, "build", lambda entry: (df, df, None))
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")
    args = argparse.Namespace(
        docker=False, max_events=10, wall_cap=5.0, human_gates="skip"
    )

    row = agent_run._run_case({"name": "base_case", "diseases": [1]}, args)
    assert seen["autonomy"] == "careful"
    assert row["autonomy"] == "careful"


def test_run_case_autonomy_arm_gets_its_own_telemetry_file(tmp_path, monkeypatch):
    """Telemetry is per arm for the same reason results are: spans from the
    careful arm must not be counted as the autonomous arm's calls."""
    import argparse
    import os

    seen = {}
    _fake_session(
        tmp_path,
        monkeypatch,
        on_init=lambda: seen.update(env=os.environ.get("CRIVO_TELEMETRY")),
    )
    monkeypatch.delenv("CRIVO_TELEMETRY", raising=False)
    args = argparse.Namespace(
        docker=False,
        max_events=agent_run.DEFAULT_MAX_EVENTS,
        wall_cap=agent_run.DEFAULT_WALL_CAP,
        human_gates="skip",
        policies="none",
        autonomy="careful",
        policy_records=[],
    )

    agent_run._run_case({"name": "tele_case", "diseases": [1]}, args)
    assert seen["env"] == str(
        tmp_path / "res" / "telemetry" / "tele_case.careful.jsonl"
    )


def test_autonomy_arm_never_drives_human_gates_approve(tmp_path, monkeypatch, capsys):
    """R1 at the driver: `approve` runs non-admission HUMAN gates, which is a
    person's authorisation to give. An autonomy arm is measured with them
    skipped, so the combination is refused rather than honoured."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path)
    entry = {"name": "gate_case", "diseases": [4]}
    monkeypatch.setattr(agent_run.corpus, "SMOKE", [entry], raising=False)
    seen = {}

    def grab(entry, args):
        seen["human_gates"] = args.human_gates
        return {"name": entry["name"], "status": "error: stub", "wall_secs": 0.1}

    monkeypatch.setattr(agent_run, "_run_case", grab)
    agent_run.main(
        ["--sample", "1", "--autonomy", "autonomous", "--human-gates", "approve"]
    )

    assert seen["human_gates"] == "skip"
    assert not list(tmp_path.glob("*.ceiling*.json")), "not the ceiling arm"
    assert (tmp_path / "gate_case.autonomous.json").exists()


def test_autonomy_rejects_report_only_at_the_cli():
    """The bench scores cleaned output and a report-only run cleans nothing,
    so the level is not an arm here."""
    with pytest.raises(SystemExit):
        agent_run.main(["--sample", "1", "--autonomy", "report-only"])


def test_a_hand_built_namespace_cannot_drive_an_autonomy_arm_with_approve(
    tmp_path, monkeypatch
):
    """The guard lived in `main` only, and `_arm_suffix`'s own docstring says
    callers build the namespace by hand. Such a namespace reached `_drive`
    with approve, which runs every non-admission HUMAN gate: a person's
    authorisation to give. The rule belongs at the point of use, and the
    filename has to name the arm that actually ran."""
    import argparse

    seen = {}
    _fake_session(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_run,
        "_drive",
        lambda gen, *a, human_gates="skip", **kw: seen.update(gates=human_gates) or 0,
    )
    args = argparse.Namespace(
        docker=False,
        max_events=agent_run.DEFAULT_MAX_EVENTS,
        wall_cap=agent_run.DEFAULT_WALL_CAP,
        human_gates="approve",
        policies="none",
        autonomy="autonomous",
        policy_records=[],
    )

    assert agent_run._arm_gates(args) == "skip"
    assert agent_run._arm_suffix(args) == ".autonomous", "not a ceiling arm"
    row = agent_run._run_case({"name": "hand_case", "diseases": [1]}, args)
    assert seen["gates"] == "skip"
    assert row["human_gates"] == "skip", "the row records what ran, not what was asked"


def test_the_ceiling_arm_still_drives_approve_without_an_autonomy_arm():
    """The coercion is scoped to the combination, not to `approve` itself: the
    existing ceiling arm is untouched."""
    import argparse

    args = argparse.Namespace(human_gates="approve", policies="none", autonomy=None)
    assert agent_run._arm_gates(args) == "approve"
    assert agent_run._arm_suffix(args) == ".ceiling"


def test_two_different_cap_values_do_not_share_an_arm_name() -> None:
    """The item 24 fix put the caps in the filename with "%g", which goes
    exponential past six significant figures and rounds. So --max-events
    1000000 and 1000001 both render ".max-events-1e+06", two different arms
    share one results file, and the second run resumes and republishes the
    first's row - which is the exact failure the new docstring says the
    suffix prevents."""
    from argparse import Namespace

    def arm(**knobs):
        return agent_run._arm_suffix(
            Namespace(human_gates="skip", autonomy=None, docker=False, **knobs)
        )

    assert arm(max_events=1_000_000, wall_cap=agent_run.DEFAULT_WALL_CAP) != arm(
        max_events=1_000_001, wall_cap=agent_run.DEFAULT_WALL_CAP
    )
    assert arm(max_events=123_456_789, wall_cap=agent_run.DEFAULT_WALL_CAP) != arm(
        max_events=123_456_700, wall_cap=agent_run.DEFAULT_WALL_CAP
    )
    assert arm(wall_cap=1_200_000.0, max_events=agent_run.DEFAULT_MAX_EVENTS) != arm(
        wall_cap=1_200_001.0, max_events=agent_run.DEFAULT_MAX_EVENTS
    )


# --- recording a run (EV2, #65) ---------------------------------------------


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def _recorder():
    """The recorder under test, looked up so that a missing one fails on this
    assertion rather than on an AttributeError."""
    record = getattr(agent_run, "_recording_generate", None)
    assert callable(record), "agent_run._recording_generate does not exist"
    return record


def _record_args(record_dir, **knobs):
    """The default arm recording into `record_dir`, as `main` hands it over:
    the cassette directory and the run tag ride on the namespace."""
    import argparse

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
    return argparse.Namespace(**{**base, **knobs})


def _recorded_fake_session(tmp_path, monkeypatch, clean, kernel=None):
    """The FakeSession pattern with the two things recording touches: a kernel
    client whose `execute` gets wrapped, and a session_dir. `clean(session)`
    is the body of the CLEAN flow; `kernel(code)` yields what a cell returns.
    Returns the sessions made and the client class, so a test can check that
    the client's own execute is back."""
    import pandas as pd

    from crivo.kernel.client import ExecResult

    def ok(code):
        yield ExecResult(status="ok", exec_count=1)

    made: list = []

    class FakeClient:
        def execute(self, code, timeout_s=120):
            yield from (kernel or ok)(code)

    class FakeSession:
        def __init__(self, **kwargs):
            self.session_dir = tmp_path / "sess"
            self.client = FakeClient()
            made.append(self)

        def load(self, path, name):
            pass

        def clean(self, var):
            return clean(self)

        def close(self):
            pass

    monkeypatch.setattr("crivo.loop.Session", FakeSession)
    # an export as it arrives: ids with leading zeros, a padded id, a sentinel
    df = pd.DataFrame(
        {"acct": ["00417", " 00982", "N/A"], "amount": ["1,204.50", "-999", "88.10"]}
    )
    monkeypatch.setattr(agent_run.corpus, "build", lambda entry: (df, df, None))
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")
    return made, FakeClient


@pytest.mark.parametrize("provider", ["faux", "claude"])
def test_recording_generate_keeps_the_whole_raw_reply_the_loop_drains(
    monkeypatch, provider
):
    """EV2: a cassette holds what the model sent, not what the loop kept. The
    loop drops heartbeats, joins a cell split across chunks and cuts the reply
    at `</execute>`, but it drains the stream to its end, so the recorder sees
    every chunk and keeps the whole text, invented output included. Every
    chunk still reaches the loop unchanged, the heartbeat too. The call is
    fingerprinted, never stored: the messages carry the dataset profile."""
    import json

    from crivo import llm

    monkeypatch.setenv("CRIVO_PROVIDER", provider)
    chunks = [
        "",  # a reasoning heartbeat
        "<execute>\ntotal = df['amount'].str.replace(',', '')",
        ".astype(float).sum()\nprint(total)\n</execute>",
        "\nOutput: 48213.07\n",  # invented past the cell
    ]
    received = []

    def provider_stream(messages, model=None):
        received.append(messages)
        yield from chunks

    messages = [
        {"role": "system", "content": "You are crivo's cleaning analyst."},
        {"role": "system", "content": "Fix one finding per cell."},
        {
            "role": "user",
            "content": "<dataset variable='df'>\nbranch: São Paulo, Zürich\n</dataset>",
        },
    ]
    calls: list = []
    generate = _recorder()(provider_stream, calls)

    assert list(generate(messages)) == chunks, "the loop must get every chunk as sent"
    assert received == [messages]
    assert len(calls) == 1
    call = calls[0]
    assert call["reply"] == "".join(chunks)
    assert call["complete"] is True
    assert call.get("error") is None
    assert call["i"] == 0
    assert call["n_messages"] == 3
    assert call["messages_sha256"] == _sha(
        json.dumps(messages, sort_keys=True, ensure_ascii=False)
    )
    assert call["system_sha256"] == _sha(
        "You are crivo's cleaning analyst.\nFix one finding per cell."
    )
    assert call["model"] == llm.model_name()
    params = llm.model_info()
    if provider == "claude":
        params = {**params, "max_tokens": llm.CLAUDE_MAX_TOKENS}
    assert call["params"] == params
    assert isinstance(call["dur_s"], (int, float)) and call["dur_s"] >= 0

    # the next call through the same recorder is the case's second
    list(generate(messages[2:]))
    assert [c["i"] for c in calls] == [0, 1]


def test_recording_generate_records_a_failed_call_and_re_raises_it():
    """EV2: a call that raises is recorded with its error, and the provider's
    own exception still reaches the loop, which decides what a failed call
    means. What arrived before the failure is kept."""
    boom = TimeoutError("gave up after 240s of silence")

    def provider_stream(messages, model=None):
        yield ""
        yield "<execute>\ndf['acct'] = "
        raise boom

    calls: list = []
    generate = _recorder()(provider_stream, calls)
    seen = []
    with pytest.raises(TimeoutError) as caught:
        for chunk in generate([{"role": "user", "content": "fix d06 on acct"}]):
            seen.append(chunk)  # noqa: PERF402 — keeps the chunks before the raise

    assert caught.value is boom, "the caller must get the provider's own exception"
    assert seen == ["", "<execute>\ndf['acct'] = "]
    assert len(calls) == 1
    call = calls[0]
    assert call["error"] == {
        "type": "TimeoutError",
        "message": "gave up after 240s of silence",
    }
    assert call["complete"] is False
    assert call["reply"] == "<execute>\ndf['acct'] = "
    assert isinstance(call["dur_s"], (int, float)) and call["dur_s"] >= 0


def test_a_stream_closed_mid_reply_is_incomplete_and_not_an_error():
    """The other side of the error case. A cap ends the turn with
    `gen.close()`, which reaches the recorder as GeneratorExit mid-stream.
    That is the bench stopping the run, not the model failing: the call is
    recorded incomplete with no error, and the close goes through."""

    def provider_stream(messages, model=None):
        yield "<execute>\nprint(df.shape)"
        yield "\n</execute>"
        yield "\nOutput: (250, 9)\n"

    calls: list = []
    stream = _recorder()(provider_stream, calls)([{"role": "user", "content": "q"}])
    assert next(stream) == "<execute>\nprint(df.shape)"
    stream.close()

    assert len(calls) == 1
    assert calls[0]["complete"] is False
    assert calls[0].get("error") is None, "closing the stream is not a model error"
    assert calls[0]["reply"] == "<execute>\nprint(df.shape)"


def test_a_marker_in_the_messages_appears_nowhere_in_the_cassette(
    tmp_path, monkeypatch
):
    """EV2: the messages carry the dataset profile, so a cassette keeps only
    their fingerprints. Kernel output holds data values, so the cell, what it
    printed and what it returned are kept as digests, and an errored cell
    keeps only its exception class: its error text is not stored at all. The
    digests are of the real text, so a replay can compare against them."""
    import json

    from crivo import llm
    from crivo.events import StreamText
    from crivo.kernel.client import ExecResult, StreamOut

    marker = "MRK-5f1c9e"
    messages = [
        {"role": "system", "content": f"You are crivo's cleaning analyst. {marker}"},
        {
            "role": "user",
            "content": (
                f"<dataset variable='df'>\nacct: '00417', ' 00982', 'N/A' {marker}\n"
                "</dataset>"
            ),
        },
    ]
    reply = "<execute>\ndf['acct'] = df['acct'].str.strip()\n</execute>"
    fix_cell = f"df['acct'] = df['acct'].str.strip()  # {marker}"
    check_cell = f"df.loc[df['acct'] == '{marker}']"
    stdout = f"{marker} 00417\n"
    value = f"'{marker}'"

    def provider_stream(msgs, model=None):
        yield ""
        yield reply

    def kernel(code):
        if code == fix_cell:
            yield StreamOut("stdout", stdout)
            yield ExecResult(status="ok", value=value, exec_count=3)
        else:
            yield ExecResult(
                status="error",
                error={
                    "ename": "KeyError",
                    "evalue": f"'{marker}'",
                    "traceback": [f"KeyError: '{marker}'"],
                },
                exec_count=4,
            )

    def clean(session):
        text = "".join(llm.generate(messages))
        list(session.client.execute(fix_cell))
        list(session.client.execute(check_cell))
        yield StreamText("model", text)

    monkeypatch.setattr(llm, "generate", provider_stream)
    _recorded_fake_session(tmp_path, monkeypatch, clean, kernel=kernel)
    rec_dir = tmp_path / "cassettes"
    rec_dir.mkdir()

    agent_run._run_case(
        {"name": "acct_case", "diseases": [6]},
        _record_args(rec_dir, autonomy="careful", run_tag=".r2"),
    )

    out = rec_dir / "acct_case.careful.r2.json"
    written = sorted(p.name for p in rec_dir.iterdir())
    assert out.exists(), f"no cassette at DIR/<name><suffix><tag>.json: {written}"
    text = out.read_text()
    leaked = marker in text
    assert not leaked, "message, cell or kernel text reached the cassette"
    cassette = json.loads(text)
    assert cassette["schema_version"] == 1

    assert len(cassette["calls"]) == 1
    call = cassette["calls"][0]
    assert call["reply"] == reply, "the reply itself is the one thing kept whole"
    assert call["messages_sha256"] == _sha(
        json.dumps(messages, sort_keys=True, ensure_ascii=False)
    )
    assert call["system_sha256"] == _sha(messages[0]["content"])
    assert call["n_messages"] == 2

    assert len(cassette["execs"]) == 2
    fixed, failed = cassette["execs"]
    assert fixed["code_sha256"] == _sha(fix_cell)
    assert fixed["status"] == "ok"
    assert fixed["value_sha256"] == _sha(value)
    assert fixed["stream_sha256"] == _sha(stdout)
    assert fixed["exec_count"] == 3
    assert fixed.get("ename") is None
    assert failed["code_sha256"] == _sha(check_cell)
    assert failed["status"] == "error"
    assert failed["ename"] == "KeyError"
    assert failed["value_sha256"] is None, "no value, so nothing to digest"
    assert failed["exec_count"] == 4


def test_recording_a_smoke_case_the_deterministic_path_solves(tmp_path, monkeypatch):
    """EV2 on a real subprocess kernel. tx-whitespace is solved by the
    registered whitespace fixer behind one plain gate, so under the faux
    provider no model call is made (one would raise on the empty faux queue,
    and be recorded). The cassette has no calls, a digest for every cell the
    kernel ran, in order, and the case's outcome; afterwards generate and the
    session's execute are the originals again."""
    import hashlib
    import json
    import subprocess
    from pathlib import Path

    import pandas as pd

    from bench import corpus, truth
    from crivo import llm, loop, prompts
    from crivo.kernel.client import KernelClient

    monkeypatch.setenv("CRIVO_PROVIDER", "faux")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")
    sessions: list = []

    class KeptSession(loop.Session):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            sessions.append(self)

    monkeypatch.setattr(loop, "Session", KeptSession)
    entry = next(e for e in corpus.SMOKE if e["name"] == "tx-whitespace")
    rec_dir = tmp_path / "cassettes"
    rec_dir.mkdir()
    real_generate = llm.generate

    row = agent_run._run_case(entry, _record_args(rec_dir))

    assert row["status"] == "ok"
    assert row["calls"]["count"] == 0, "tx-whitespace now needs the model: pick another"
    out = rec_dir / "tx-whitespace.json"
    assert out.exists(), "no cassette written for the recorded case"
    cassette = json.loads(out.read_text())
    session = sessions[0]
    session_dir = Path(session.session_dir)

    assert cassette["calls"] == []
    assert cassette["execs"], "the kernel ran cells, so the cassette has digests"
    assert cassette["outcome"]["status"] == "ok"

    # every cell in this case goes through the transcript (no restart, no
    # preview, no snapshot), so the digests line up with its exec events
    events = [json.loads(line) for line in (session_dir / "transcript.jsonl").open()]
    logged = [ev for ev in events if ev.get("kind") == "exec"]
    expected = [
        (
            _sha(ev["code"]),
            ev["status"],
            None if ev["value"] is None else _sha(ev["value"]),
            ev["exec_count"],
        )
        for ev in logged
    ]
    got = [
        (e["code_sha256"], e["status"], e["value_sha256"], e["exec_count"])
        for e in cassette["execs"]
    ]
    assert got == expected
    assert all("stream_sha256" in e for e in cassette["execs"])

    _, dirty, _ = corpus.build(entry)
    assert cassette["source"] == {
        "kind": "corpus",
        "entry": json.loads(json.dumps(entry)),
        "dirty_sha256": truth.frame_sha256(dirty),
    }
    assert cassette["arm"] == {
        "autonomy": "careful",
        "human_gates": "skip",
        "policies": "none",
        "docker": False,
        "max_events": agent_run.DEFAULT_MAX_EVENTS,
        "wall_cap": agent_run.DEFAULT_WALL_CAP,
        "suffix": "",
    }
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert set(cassette["crivo"]) == {"commit", "dirty", "prompts_sha256"}
    assert cassette["crivo"]["commit"] == head
    assert cassette["crivo"]["prompts_sha256"] == (
        hashlib.sha256(Path(prompts.__file__).read_bytes()).hexdigest()
    )

    outcome = cassette["outcome"]
    cleaned = pd.read_parquet(session_dir / "cleaned" / "df.parquet")
    assert outcome["events"] == row["events"]
    assert outcome["gates"] == ["run"], "one plain gate, run"
    # (disease, columns, grade, status, attempts): d06 on txn_id, fixed by the
    # registered fixer with no model attempt
    assert outcome["records"] == [[6, ["txn_id"], "AUTO", "fixed", 0]]
    assert outcome["cleaned_sha256"] == truth.frame_sha256(cleaned)
    assert outcome["scores"] == json.loads(json.dumps(row["scores"]))
    report = max((session_dir / "clean_reports").glob("r*.json"))
    evidence = [
        f["finding"]["evidence"] for f in json.loads(report.read_text())["fixes"]
    ]
    flat = json.dumps(cassette, ensure_ascii=False)
    leaked = any(ev in flat for ev in evidence)
    assert not leaked, "a finding's evidence (it quotes sample values) was recorded"

    assert llm.generate is real_generate, "the recorder outlived the case"
    assert session.client.execute.__func__ is KernelClient.execute, (
        "the wrapped execute outlived the case"
    )


@pytest.mark.parametrize("where", ["model_call", "after_cell"])
def test_run_case_puts_generate_and_execute_back_after_a_case_that_raises(
    tmp_path, monkeypatch, where
):
    """EV2: the recorders are swapped in for the case and taken out in a
    finally, so a case that raises (the model call itself, or the flow after
    a cell ran) leaves the next case, and the test suite, the real generate
    and the client's own execute. The case is still written down."""
    import json

    from crivo import llm
    from crivo.events import StreamText

    def provider_stream(messages, model=None):
        yield ""
        raise TimeoutError("gave up after 240s of silence")

    seen = {}

    def clean(session):
        seen["generate"] = llm.generate
        seen["execute"] = session.client.execute
        list(session.client.execute("df['acct'] = df['acct'].str.strip()"))
        if where == "model_call":
            "".join(llm.generate([{"role": "user", "content": "fix d06 on acct"}]))
        else:
            raise KeyError("acct")
        yield StreamText("stdout", "unreached")

    monkeypatch.setattr(llm, "generate", provider_stream)
    made, client_cls = _recorded_fake_session(tmp_path, monkeypatch, clean)
    rec_dir = tmp_path / "cassettes"
    rec_dir.mkdir()

    row = agent_run._run_case(
        {"name": "raise_case", "diseases": [6]}, _record_args(rec_dir)
    )

    assert row["status"].startswith("error: "), "the case was meant to raise"
    assert seen["generate"] is not provider_stream, "the case ran with no recorder"
    assert getattr(seen["execute"], "__func__", None) is not client_cls.execute, (
        "the cells ran unrecorded"
    )
    assert llm.generate is provider_stream, "the recorder outlived a case that raised"
    assert made[0].client.execute.__func__ is client_cls.execute, (
        "the wrapped execute outlived a case that raised"
    )
    out = rec_dir / "raise_case.json"
    assert out.exists(), "a case that raised is still recorded"
    cassette = json.loads(out.read_text())
    assert cassette["outcome"]["status"] == row["status"]
    assert len(cassette["execs"]) == 1
    errors = [c["error"]["type"] for c in cassette["calls"]]
    assert errors == (["TimeoutError"] if where == "model_call" else [])


def test_a_case_whose_session_never_starts_leaves_the_next_case_the_real_generate(
    tmp_path, monkeypatch
):
    """EV2: when Session() raises (a kernel that will not start) the inner
    finally never runs, so the generate swap has to be undone by the outer
    one. A recorder left behind would sit under the next case's recorder, and
    every later call would also land in a dead case's list."""
    import json

    import crivo.loop
    from crivo import llm
    from crivo.events import StreamText

    def provider_stream(messages, model=None):
        yield "<answer>acct is clean</answer>"

    def clean(session):
        "".join(llm.generate([{"role": "user", "content": "fix d06 on acct"}]))
        yield StreamText("stdout", "done")

    monkeypatch.setattr(llm, "generate", provider_stream)
    _recorded_fake_session(tmp_path, monkeypatch, clean)
    working = crivo.loop.Session

    class NoKernel:
        def __init__(self, **kwargs):
            raise RuntimeError("kernel did not answer hello within 60s")

    monkeypatch.setattr(crivo.loop, "Session", NoKernel)
    rec_dir = tmp_path / "cassettes"
    rec_dir.mkdir()
    try:
        agent_run._run_case(
            {"name": "dead_case", "diseases": [6]}, _record_args(rec_dir)
        )
    except RuntimeError:
        pass  # whether a Session that cannot start propagates is not this test's
    assert llm.generate is provider_stream, (
        "the recorder outlived a case whose Session never started"
    )

    monkeypatch.setattr(crivo.loop, "Session", working)
    agent_run._run_case({"name": "next_case", "diseases": [6]}, _record_args(rec_dir))
    out = rec_dir / "next_case.json"
    assert out.exists(), "the case after it is recorded"
    assert len(json.loads(out.read_text())["calls"]) == 1
    assert llm.generate is provider_stream


def test_main_hands_each_case_the_record_dir_and_its_run_tag(tmp_path, monkeypatch):
    """EV2: `--record DIR` reaches `_run_case` on the namespace, beside the run
    tag that names a repeated run's file, so each repeat writes its own
    cassette (DIR/<name><suffix><tag>.json) rather than overwriting the
    first."""
    from pathlib import Path

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(agent_run, "RESULTS_DIR", tmp_path / "res")
    entry = {"name": "rec_case", "diseases": [6]}
    monkeypatch.setattr(agent_run.corpus, "SMOKE", [entry], raising=False)
    seen: list = []

    def fake_run(entry, args):
        seen.append((getattr(args, "record", None), getattr(args, "run_tag", None)))
        return {
            "name": entry["name"],
            "status": "ok",
            "wall_secs": 0.1,
            "scores": {"repair": {"f1": 1.0}},
        }

    monkeypatch.setattr(agent_run, "_run_case", fake_run)
    rec_dir = tmp_path / "cassettes"
    try:
        agent_run.main(["--sample", "1", "--repeat", "2", "--record", str(rec_dir)])
    except SystemExit as exc:
        pytest.fail(f"main refused --record: exit {exc.code}")

    assert [Path(d) if d else d for d, _ in seen] == [rec_dir, rec_dir]
    assert [tag for _, tag in seen] == [".r1", ".r2"]


@pytest.mark.parametrize(
    "max_events,wall_cap,started_s_ago,counted",
    [
        (5, 60.0, 0.0, 6),  # the sixth event tripped the event cap
        (5, 1.0, 10.0, 1),  # the first event found the wall cap already spent
    ],
)
def test_an_aborted_case_counts_the_event_that_tripped_the_cap(
    max_events, wall_cap, started_s_ago, counted
):
    """EV2: CaseAborted carries the count `_drive` had reached when a cap
    fired, the event that tripped it included, so a cassette can say how far
    an aborted case got."""
    import time

    def endless():
        while True:
            yield "event"

    with pytest.raises(agent_run.CaseAborted) as caught:
        agent_run._drive(
            endless(),
            max_events=max_events,
            wall_cap=wall_cap,
            t0=time.monotonic() - started_s_ago,
        )
    assert caught.value.events == counted


def test_a_case_aborted_without_a_count_says_unknown_not_zero():
    """A CaseAborted raised without a count does not know how many events
    ran. 0 would claim that none did."""
    assert agent_run.CaseAborted("wall cap 300s hit").events is None


def test_a_recorded_case_cut_by_the_event_cap_records_the_count_at_the_abort(
    tmp_path, monkeypatch
):
    """EV2: an aborted case never returns from `_drive`, so the row has no
    event count and keeps none (recording changes nothing in the row). The
    cassette takes the count from the abort: max_events + 1, the event that
    tripped the cap included."""
    import json

    from crivo.events import StreamText

    def clean(session):
        while True:
            yield StreamText("stdout", ".")

    _recorded_fake_session(tmp_path, monkeypatch, clean)
    rec_dir = tmp_path / "cassettes"
    rec_dir.mkdir()

    row = agent_run._run_case(
        {"name": "cap_case", "diseases": [6]}, _record_args(rec_dir, max_events=3)
    )

    assert row["status"].startswith("aborted: event cap")
    assert "events" not in row, "the row stays as it was"
    out = rec_dir / "cap_case.max-events-3.json"
    assert out.exists(), "an aborted case is still recorded"
    outcome = json.loads(out.read_text())["outcome"]
    assert outcome["status"] == row["status"]
    assert outcome["events"] == 4


def test_a_cells_stream_digest_is_the_text_the_loop_hands_the_model(
    tmp_path, monkeypatch
):
    """EV2: the loop folds a display it does not save as an image into the
    cell's text as `[display] <payload>`, in order with the stream
    (`Session._exec_events`). A dropped image is folded in the same way. A
    saved PNG is kept out, since its payload is a tmp path that differs on
    every run. The digest is of that same text, so a replay compares what
    the model was shown. The display text itself never reaches the cassette."""
    import json

    from crivo.events import StreamText
    from crivo.kernel.client import DisplayItem, ExecResult, StreamOut

    png = str(tmp_path / "sess" / "artifacts" / "img-1.png")

    def kernel(code):
        yield StreamOut("stdout", "out\n")
        yield DisplayItem("text/html", "<b>DISPLAY-MARK</b>")
        yield DisplayItem("image/png", png)
        yield DisplayItem("image/png", "(dropped: 2048 bytes)", True)
        yield StreamOut("stdout", "more\n")
        yield ExecResult(status="ok", exec_count=2)

    def clean(session):
        list(session.client.execute("df.head()"))
        yield StreamText("stdout", "done")

    _recorded_fake_session(tmp_path, monkeypatch, clean, kernel=kernel)
    rec_dir = tmp_path / "cassettes"
    rec_dir.mkdir()

    agent_run._run_case({"name": "show_case", "diseases": [6]}, _record_args(rec_dir))

    out = rec_dir / "show_case.json"
    assert out.exists(), "no cassette written"
    text = out.read_text()
    execs = json.loads(text)["execs"]
    assert len(execs) == 1
    shown = "out\n[display] <b>DISPLAY-MARK</b>[display] (dropped: 2048 bytes)more\n"
    assert execs[0]["stream_sha256"] == _sha(shown)
    leaked = "DISPLAY-MARK" in text or png in text
    assert not leaked, "display text or an image path reached the cassette"


def test_cassettes_written_into_the_checkout_do_not_mark_it_dirty(
    tmp_path, monkeypatch
):
    """EV2: `crivo.dirty` says whether the code that recorded had changes.
    Cassettes are written into the checkout (EV16 commits them under tests/),
    so once the first is on disk, that untracked file must not mark the next
    recording dirty. A change to a tracked file still does."""
    import json
    import subprocess

    from crivo.events import StreamText

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "loop.py").write_text("STEP = 1\n")

    def git(*args):
        return subprocess.run(
            [
                "git",
                "-c",
                "user.email=bench@example.invalid",
                "-c",
                "user.name=bench",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    git("init", "-q")
    git("add", "loop.py")
    git("commit", "-qm", "base")
    head = git("rev-parse", "HEAD").strip()

    real_run = subprocess.run

    def run_in_checkout(cmd, *args, **kwargs):
        # the stamp's git calls read this tmp checkout, not crivo's own
        if list(cmd)[:1] == ["git"]:
            kwargs["cwd"] = str(checkout)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run_in_checkout)
    monkeypatch.chdir(checkout)

    def clean(session):
        yield StreamText("stdout", "done")

    _recorded_fake_session(tmp_path, monkeypatch, clean)
    rec_dir = checkout / "tests" / "cassettes"
    rec_dir.mkdir(parents=True)

    def stamp(name):
        agent_run._run_case({"name": name, "diseases": [6]}, _record_args(rec_dir))
        return json.loads((rec_dir / f"{name}.json").read_text())["crivo"]

    first = stamp("first_case")
    assert first["commit"] == head, "the stamp did not read the tmp checkout"
    assert first["dirty"] is False
    assert stamp("second_case")["dirty"] is False, (
        "an untracked cassette is not a code change"
    )

    (checkout / "loop.py").write_text("STEP = 2\n")
    assert stamp("third_case")["dirty"] is True, "a changed tracked file is one"
