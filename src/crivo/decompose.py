"""Driver decomposition (capability roadmap B1.2).

"Why did this metric change" as ranked per-dimension contributions. For an
additive (sum) metric each category's contribution is its after-minus-before,
and rows whose category is empty (None or NaN) form one `None` category, so
no row drops out of the explanation. The receipt is checked, not assumed: the
contributions are summed and compared with the change in the whole frames'
totals, taken independently of the grouping. It is True when they agree
within rounding scaled to the size of the values (about 1e-9 of their
absolute sum, never under 1e-9), so a balanced ledger whose totals net to 0
still passes, but it cannot see a lost row smaller than that: under about
$2.50 on a ledger with $2.5B of absolute volume. v1 covers sum metrics only;
mix-vs-rate decomposition for ratios (where the split into volume and rate
effects is a modelling choice, not an identity) is a follow-up. Pure pandas,
no model call.
"""

from __future__ import annotations

import pandas as pd

# Stands in for an empty category while grouping, so groupby keeps those rows.
_NULL = object()


def decompose_sum(
    before: pd.DataFrame, after: pd.DataFrame, value_col: str, by_col: str
) -> dict:
    """Decompose the change in sum(value_col) into per-category contributions.

    Each category's contribution is its after-total minus its before-total
    (a category on only one side counts as 0 on the other); rows with an
    empty `by_col` form one `None` category. Returns the whole frames'
    totals, their delta, the contributions ranked by absolute impact, and a
    `receipt` that is True when the contributions sum to that delta within
    rounding scaled to the size of the values (about 1e-9 of their absolute
    sum). A lost row smaller than that tolerance does not show in it.
    """
    b = _sums_by(before, value_col, by_col)
    a = _sums_by(after, value_col, by_col)
    # mixed types (1 and "a") never compare directly; None sorts last; ints
    # and floats keep numeric order inside their type group (2 before 10)
    categories = sorted(
        set(b) | set(a),
        key=lambda c: (
            c is None,
            type(c).__name__,
            c if isinstance(c, (int, float)) and not isinstance(c, bool) else str(c),
        ),
    )

    total_before = float(before[value_col].sum())
    total_after = float(after[value_col].sum())
    delta = total_after - total_before

    contributions = []
    for cat in categories:
        cb = b.get(cat, 0.0)
        ca = a.get(cat, 0.0)
        contrib = ca - cb
        contributions.append(
            {
                "category": cat,
                "before": cb,
                "after": ca,
                "contribution": contrib,
                # share of the delta a contribution explains; undefined when
                # the net delta is zero (offsetting moves), reported as None
                "share": (contrib / delta) if delta else None,
            }
        )
    contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)

    summed = sum(c["contribution"] for c in contributions)
    # the tolerance scales to the absolute volume, not the delta or the
    # totals: a few cents moving in a 50-million ledger, or a balanced ledger
    # netting to 0, still carry the rounding of summing values that large
    tolerance = 1e-9 * max(
        1.0,
        float(before[value_col].abs().sum()),
        float(after[value_col].abs().sum()),
    )
    receipt = abs(summed - delta) <= tolerance

    return {
        "metric": value_col,
        "by": by_col,
        "total_before": _clean(total_before),
        "total_after": _clean(total_after),
        "delta": _clean(delta),
        "contributions": [
            {
                **c,
                "before": _clean(c["before"]),
                "after": _clean(c["after"]),
                "contribution": _clean(c["contribution"]),
            }
            for c in contributions
        ],
        "receipt": receipt,
    }


def _sums_by(frame: pd.DataFrame, value_col: str, by_col: str) -> dict:
    """Sum value_col per by_col category, empty categories under None."""
    col = frame[by_col]
    key = col.astype(object).where(col.notna(), _NULL)
    # sort=False: the sentinel cannot be ordered against real categories
    sums = frame[value_col].groupby(key, sort=False).sum()
    return {(None if k is _NULL else k): float(v) for k, v in sums.items()}


def _clean(x: float):
    """Present a whole-number float as an int so receipts read cleanly."""
    return int(x) if float(x).is_integer() else x
