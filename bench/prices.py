"""What a model call costs, for the eval runner's caps (spec:
specs/2026-10-17-eval-tooling.md EV9, #72).

A number that was not measured is not claimed: every entry names the page its
rates were read from (`source`) and the ISO date they were read (`checked`),
and only the orchestrating session or Aarmen adds one, from the provider's own
pricing page on the day. Rates are USD per million tokens. Until an entry
exists for a model, `bench.eval register` refuses an arm on it.

`cost_usd` prices one gen_ai.client.call span on the terms
`agent_run._call_stats` sums: input minus cache hits at `input`, cache hits at
`cache_hit`, output at `output`. A span missing its input or output count, or
a model with no entry, is None, never 0, which would read as a free call. An
all-zero entry (faux) costs 0.0 whatever the span reported.

What the spans can't tell apart is priced as input: Claude's cache write is
counted in the span's input (llm._claude_usage) and billed above the input
rate, so a Claude cost reads low by that difference.
"""

from __future__ import annotations

import math

RATES = ("input", "cache_hit", "output")

PRICES: dict[str, dict] = {
    "faux": {
        "input": 0.0,
        "cache_hit": 0.0,
        "output": 0.0,
        "source": "crivo's offline test provider (crivo.llm, CRIVO_PROVIDER=faux): "
        "it sends nothing anywhere, so it bills nothing",
        "checked": "2026-10-18",
    },
    # Peak rates: off-peak is half, so a cost read off-peak is high, never low.
    "deepseek:deepseek-v4-pro": {
        "input": 1.32,
        "cache_hit": 0.044,
        "output": 3.96,
        "source": "https://api-docs.deepseek.com/quick_start/pricing "
        "(peak rates, model version DeepSeek-V4-Pro-0813)",
        "checked": "2026-10-19",
    },
}


def price_key(provider: str, model: str) -> str:
    """The PRICES key an arm is priced under: faux by its provider, whatever
    model it names; any other as PROVIDER:MODEL, the --arm spelling, since
    one model id can be served at another price through another provider."""
    return "faux" if provider == "faux" else f"{provider}:{model}"


def _count(value) -> bool:
    """A finite number, not a bool: NaN or infinity is no amount, and no cap
    compares against one."""
    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    return number and math.isfinite(value)


def cost_usd(attrs: dict, key: str) -> float | None:
    """One span's cost in dollars at PRICES[key], or None when it can't be
    priced (see the module docstring), a rate or a sum that is not finite
    included."""
    price = PRICES.get(key)
    if price is None or not all(_count(price.get(rate)) for rate in RATES):
        return None
    if not any(price[rate] for rate in RATES):
        return 0.0
    attrs = attrs if isinstance(attrs, dict) else {}
    fresh = attrs.get("gen_ai.usage.input_tokens")
    out = attrs.get("gen_ai.usage.output_tokens")
    if not (_count(fresh) and _count(out)):
        return None
    hit = attrs.get("crivo.cache.hit_tokens")
    hit = hit if _count(hit) else 0
    total = (
        (fresh - hit) * price["input"]
        + hit * price["cache_hit"]
        + out * price["output"]
    )
    return total / 1_000_000 if math.isfinite(total) else None
