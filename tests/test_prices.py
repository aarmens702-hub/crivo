"""bench.prices units (spec: specs/2026-10-17-eval-tooling.md EV9, #72).

A number that was not measured is not claimed: every price names the page it
was read from and the day it was read, and `cost_usd` prices one
gen_ai.client.call span on the terms `agent_run._call_stats` sums (input
minus cache hits, cache hits, output), in dollars per million tokens. A span
it can't price is None, never 0, except under an all-zero entry (faux), where
the call costs nothing whatever it reported.

The interface these tests pin where the issue leaves it open:
- `PRICES[key]` is {"input", "cache_hit", "output", "source", "checked"}, the
  rates in USD per million tokens and `checked` an ISO date string.
- `price_key(provider, model)` is the PRICES key an arm is priced under; faux
  is priced by its provider, whatever model it names.
- `cost_usd(attrs, key)` takes a span's attrs, as llm.generate writes them.

Keyless and offline: no price is fetched, and the test prices below are
monkeypatched in, never written to PRICES.
"""

import importlib
import importlib.util
import math
from datetime import date

import pytest

# A made-up price, in USD per million tokens; not any provider's.
TEST_KEY = "test-model-v1"
TEST_PRICE = {
    "input": 0.27,
    "cache_hit": 0.07,
    "output": 1.10,
    "source": "a test price, not read from any provider's page",
    "checked": "2026-10-18",
}
# What llm.generate writes on every span besides usage.
NAMED = {
    "gen_ai.system": "deepseek",
    "gen_ai.request.model": "deepseek-v4-pro",
    "gen_ai.response.model": "deepseek-v4-pro-0925",
}


def _prices():
    """bench.prices, imported per test, so a missing module fails each test on
    this assert instead of erroring the whole file at collection."""
    assert importlib.util.find_spec("bench.prices") is not None, (
        "bench/prices.py does not exist yet (#72)"
    )
    return importlib.import_module("bench.prices")


@pytest.mark.parametrize(
    "attrs, key, want",
    [
        # A DeepSeek span with a warm cache. Hand-checked:
        # (12480 - 9216) * 0.27 + 9216 * 0.07 + 1037 * 1.10
        #   = 881.28 + 645.12 + 1140.70 = 2667.10 per million -> $0.0026671
        (
            {
                **NAMED,
                "gen_ai.usage.input_tokens": 12480,
                "gen_ai.usage.output_tokens": 1037,
                "crivo.cache.hit_tokens": 9216,
                "crivo.cache.miss_tokens": 3264,
            },
            TEST_KEY,
            0.0026671,
        ),
        # A Claude span as llm._claude_usage maps it: input counts the cache
        # write (412 fresh + 9800 written), no read.
        # 10212 * 0.27 + 655 * 1.10 = 2757.24 + 720.50 -> $0.00347774
        (
            {
                "gen_ai.system": "claude",
                "gen_ai.request.model": "claude-opus-5-5",
                "gen_ai.usage.input_tokens": 10212,
                "gen_ai.usage.output_tokens": 655,
                "crivo.cache.hit_tokens": 0,
                "crivo.cache.miss_tokens": 10212,
            },
            TEST_KEY,
            0.00347774,
        ),
        # An endpoint that reports no cache counters: no hits.
        # 2000 * 0.27 + 500 * 1.10 = 540 + 550 -> $0.00109
        (
            {
                **NAMED,
                "gen_ai.usage.input_tokens": 2000,
                "gen_ai.usage.output_tokens": 500,
            },
            TEST_KEY,
            0.00109,
        ),
        # A call that reported zero tokens cost zero, which is known.
        (
            {**NAMED, "gen_ai.usage.input_tokens": 0, "gen_ai.usage.output_tokens": 0},
            TEST_KEY,
            0.0,
        ),
    ],
    ids=["deepseek, warm cache", "claude, cache write", "no cache counters", "zero"],
)
def test_cost_usd_prices_a_span_in_dollars(monkeypatch, attrs, key, want):
    """Done when 1: a span with hand-computed tokens and a test price gives
    the hand-computed dollars; the names on the span don't change the sum."""
    prices = _prices()
    monkeypatch.setitem(prices.PRICES, TEST_KEY, dict(TEST_PRICE))
    got = prices.cost_usd(attrs, key)
    assert got == pytest.approx(want, rel=1e-9, abs=1e-12)


@pytest.mark.parametrize(
    "attrs, key",
    [
        # telemetry.span emits from a finally, so a call that died mid-stream
        # leaves a span with no usage at all
        (dict(NAMED), TEST_KEY),
        # input and a cache hit, no output: not half a reading
        (
            {
                **NAMED,
                "gen_ai.usage.input_tokens": 12480,
                "crivo.cache.hit_tokens": 9216,
            },
            TEST_KEY,
        ),
        # output alone would price the call cheap
        ({**NAMED, "gen_ai.usage.output_tokens": 1037}, TEST_KEY),
        # a model with no price entry
        (
            {
                **NAMED,
                "gen_ai.usage.input_tokens": 2000,
                "gen_ai.usage.output_tokens": 500,
            },
            "deepseek-v9-unpriced",
        ),
    ],
    ids=["no usage", "no output", "no input", "unknown key"],
)
def test_cost_usd_is_none_when_the_span_or_the_model_cant_be_priced(
    monkeypatch, attrs, key
):
    """A span missing input or output, or a model with no price, is unknown:
    None, never 0, which would read as a free call."""
    prices = _prices()
    monkeypatch.setitem(prices.PRICES, TEST_KEY, dict(TEST_PRICE))
    assert prices.cost_usd(attrs, key) is None


@pytest.mark.parametrize(
    "rate, value",
    [
        ("input", math.nan),
        ("cache_hit", math.inf),
        ("output", -math.inf),
    ],
    ids=["a NaN input rate", "an infinite cache-hit rate", "a -inf output rate"],
)
def test_a_rate_that_is_not_a_finite_amount_prices_nothing(monkeypatch, rate, value):
    """Decision on #72: a price whose rate is NaN or infinite can't price a
    call, so the span's cost is None, never NaN or infinity, which no cap
    compares against. The same span at the finite test price is priced
    (test_cost_usd_prices_a_span_in_dollars)."""
    prices = _prices()
    monkeypatch.setitem(prices.PRICES, TEST_KEY, {**TEST_PRICE, rate: value})
    attrs = {
        **NAMED,
        "gen_ai.usage.input_tokens": 12480,
        "gen_ai.usage.output_tokens": 1037,
        "crivo.cache.hit_tokens": 9216,
        "crivo.cache.miss_tokens": 3264,
    }
    assert prices.cost_usd(attrs, TEST_KEY) is None


@pytest.mark.parametrize(
    "attrs",
    [
        {"gen_ai.system": "faux", "gen_ai.request.model": "m"},
        {
            "gen_ai.system": "faux",
            "gen_ai.request.model": "m",
            "gen_ai.usage.input_tokens": 12480,
            "gen_ai.usage.output_tokens": 1037,
        },
    ],
    ids=["a faux span, no usage", "usage reported"],
)
def test_an_all_zero_price_costs_nothing_whatever_the_span_reported(attrs):
    """faux is priced at zero, so its calls cost 0.0, also when its span
    reports no usage (the faux provider reports none)."""
    prices = _prices()
    assert prices.cost_usd(attrs, prices.price_key("faux", "m")) == 0.0


def test_faux_is_priced_by_its_provider_whatever_model_it_names():
    prices = _prices()
    assert prices.price_key("faux", "m") == "faux"
    assert prices.price_key("faux", "deepseek-v4-pro") == "faux"


def test_every_price_names_its_source_and_the_day_it_was_read():
    """Each entry's rates are finite and not negative, its source names where
    it was read, and `checked` is the ISO date it was read. faux is priced at
    zero."""
    prices = _prices()
    assert "faux" in prices.PRICES
    for key, entry in prices.PRICES.items():
        for rate in ("input", "cache_hit", "output"):
            value = entry.get(rate)
            assert isinstance(value, (int, float)), f"{key}.{rate} is not a rate"
            assert math.isfinite(value) and value >= 0, f"{key}.{rate} is {value}"
        source = entry.get("source")
        assert isinstance(source, str) and source.strip(), f"{key} names no source"
        checked = entry.get("checked")
        assert isinstance(checked, str), f"{key}.checked is not an ISO date string"
        date.fromisoformat(checked)
    faux = prices.PRICES["faux"]
    assert (faux["input"], faux["cache_hit"], faux["output"]) == (0.0, 0.0, 0.0)


# --- #239: refused counts, and the bound on a call whose spend is unread -----


@pytest.mark.parametrize(
    "usage",
    [
        {"gen_ai.usage.input_tokens": -12480, "gen_ai.usage.output_tokens": 1037},
        {"gen_ai.usage.input_tokens": 12480, "gen_ai.usage.output_tokens": -1037},
        {
            "gen_ai.usage.input_tokens": 12480,
            "gen_ai.usage.output_tokens": 1037,
            "crivo.cache.hit_tokens": -9216,
        },
        # more cache hits than input: input minus hits would bill a negative
        {
            "gen_ai.usage.input_tokens": 12480,
            "gen_ai.usage.output_tokens": 1037,
            "crivo.cache.hit_tokens": 12481,
        },
    ],
    ids=["negative input", "negative output", "negative hits", "hits above input"],
)
def test_cost_usd_refuses_a_negative_count_and_hits_above_input(monkeypatch, usage):
    """#239 (from #72's review): a span reporting a negative count, or more
    cache hits than input, is no reading: None, so it reads as unread, never a
    cost below what was spent."""
    prices = _prices()
    monkeypatch.setitem(prices.PRICES, TEST_KEY, dict(TEST_PRICE))
    assert prices.cost_usd({**NAMED, **usage}, TEST_KEY) is None


def test_cost_usd_still_prices_a_span_whose_whole_input_hit_the_cache(monkeypatch):
    """The legitimate case beside the refusal: hits equal to input are a fully
    warm cache, priced. Hand-checked: 0 * 0.27 + 12480 * 0.07 + 1037 * 1.10
    = 873.6 + 1140.7 = 2014.3 per million -> $0.0020143."""
    prices = _prices()
    monkeypatch.setitem(prices.PRICES, TEST_KEY, dict(TEST_PRICE))
    attrs = {
        **NAMED,
        "gen_ai.usage.input_tokens": 12480,
        "gen_ai.usage.output_tokens": 1037,
        "crivo.cache.hit_tokens": 12480,
        "crivo.cache.miss_tokens": 0,
    }
    got = prices.cost_usd(attrs, TEST_KEY)
    assert got == pytest.approx(0.0020143, rel=1e-9, abs=1e-12)


def _bound():
    """bench.prices and its call_bound_usd, looked up so that a missing one
    fails on this assertion rather than on an AttributeError."""
    prices = _prices()
    bound = getattr(prices, "call_bound_usd", None)
    assert callable(bound), "bench.prices.call_bound_usd does not exist yet (#239)"
    return prices, bound


# TEST_PRICE with a documented output limit, as an entry names it.
BOUNDED_PRICE = {**TEST_PRICE, "max_output_tokens": 8000}


@pytest.mark.parametrize(
    "input_bytes, want",
    [
        # 2000 * 0.27 + 8000 * 1.10 = 540 + 8800 per million -> $0.00934
        (2000, 0.00934),
        # nothing sent still risks the whole output: 8800 per million
        (0, 0.0088),
    ],
    ids=["2000 bytes sent", "nothing sent"],
)
def test_call_bound_usd_is_the_input_sent_plus_the_documented_output_limit(
    monkeypatch, input_bytes, want
):
    """#239 step 1: the most one call can cost is every byte sent priced as an
    input token (a token covers at least one byte) plus the entry's
    max_output_tokens at the output rate, per million."""
    prices, bound = _bound()
    monkeypatch.setitem(prices.PRICES, TEST_KEY, dict(BOUNDED_PRICE))
    assert bound(input_bytes, TEST_KEY) == pytest.approx(want, rel=1e-9, abs=1e-12)


@pytest.mark.parametrize(
    "input_bytes, key, entry",
    [
        (2000, TEST_KEY, TEST_PRICE),
        (2000, "deepseek-v9-unpriced", BOUNDED_PRICE),
        (-1, TEST_KEY, BOUNDED_PRICE),
        (math.nan, TEST_KEY, BOUNDED_PRICE),
        (math.inf, TEST_KEY, BOUNDED_PRICE),
        (True, TEST_KEY, BOUNDED_PRICE),
        (2000, TEST_KEY, {**TEST_PRICE, "max_output_tokens": 0}),
        (2000, TEST_KEY, {**TEST_PRICE, "max_output_tokens": -1}),
        (2000, TEST_KEY, {**TEST_PRICE, "max_output_tokens": True}),
        (2000, TEST_KEY, {**BOUNDED_PRICE, "output": math.nan}),
    ],
    ids=[
        "no output limit",
        "unknown key",
        "negative bytes",
        "NaN bytes",
        "infinite bytes",
        "True as bytes",
        "a zero limit",
        "a negative limit",
        "True as a limit",
        "a NaN output rate",
    ],
)
def test_call_bound_usd_is_none_when_the_call_cant_be_bounded(
    monkeypatch, input_bytes, key, entry
):
    """An entry with no output limit can't bound a call, so the spend guard
    keeps #72's fail-closed stop: None, never 0. A count that is not a finite
    amount of 0 or more, a limit that is not a positive whole number of
    tokens, or a rate that is not finite bounds nothing either."""
    prices, bound = _bound()
    monkeypatch.setitem(prices.PRICES, TEST_KEY, dict(entry))
    assert bound(input_bytes, key) is None


def test_the_deepseek_entry_names_its_documented_output_limit():
    """#239: DeepSeek's pricing page (read 2026-10-19) gives deepseek-v4-pro a
    384K maximum output, so its calls can be bounded. Where an entry names a
    limit, it is a positive whole number of tokens."""
    prices = _prices()
    entry = prices.PRICES["deepseek:deepseek-v4-pro"]
    assert entry.get("max_output_tokens") == 384_000
    for key, entry in prices.PRICES.items():
        if "max_output_tokens" in entry:
            limit = entry["max_output_tokens"]
            assert type(limit) is int and limit > 0, f"{key}.max_output_tokens"
