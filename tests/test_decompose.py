"""Driver decomposition (capability roadmap B1.2): 'why did this metric
change' as ranked per-dimension contributions whose receipt is that they sum
to the whole-frame change, within float rounding scaled to the absolute
volume of the values.
Additive (sum) metrics only in v1, because there each contribution is an
identity (after minus before) rather than a modelling choice; mix-vs-rate for
ratios is a follow-up. Pure pandas, no model, no new dependency."""

import numpy as np
import pandas as pd
import pytest

from crivo import decompose
from crivo.decompose import decompose_sum


def _frame(rows):
    return pd.DataFrame(rows, columns=["region", "amount"])


def test_contributions_sum_exactly_to_the_delta():
    before = _frame([("west", 100), ("east", 50)])
    after = _frame([("west", 120), ("east", 40)])
    out = decompose_sum(before, after, "amount", "region")
    assert out["total_before"] == 150
    assert out["total_after"] == 160
    assert out["delta"] == 10
    assert sum(c["contribution"] for c in out["contributions"]) == out["delta"]
    assert out["receipt"] is True


def test_a_category_only_in_after_contributes_its_full_value():
    before = _frame([("west", 100)])
    after = _frame([("west", 100), ("new", 30)])
    out = decompose_sum(before, after, "amount", "region")
    new = next(c for c in out["contributions"] if c["category"] == "new")
    assert new["before"] == 0 and new["after"] == 30 and new["contribution"] == 30
    assert sum(c["contribution"] for c in out["contributions"]) == out["delta"] == 30


def test_a_category_only_in_before_contributes_negative():
    before = _frame([("west", 100), ("gone", 40)])
    after = _frame([("west", 100)])
    out = decompose_sum(before, after, "amount", "region")
    gone = next(c for c in out["contributions"] if c["category"] == "gone")
    assert gone["contribution"] == -40
    assert out["delta"] == -40


def test_contributions_ranked_by_absolute_impact():
    before = _frame([("a", 100), ("b", 100), ("c", 100)])
    after = _frame([("a", 90), ("b", 130), ("c", 105)])
    out = decompose_sum(before, after, "amount", "region")
    order = [c["category"] for c in out["contributions"]]
    assert order == ["b", "a", "c"]  # +30, -10, +5 by absolute impact


def test_zero_delta_is_reported_without_dividing_by_zero():
    before = _frame([("a", 100), ("b", 50)])
    after = _frame([("a", 90), ("b", 60)])
    out = decompose_sum(before, after, "amount", "region")
    assert out["delta"] == 0
    assert out["receipt"] is True  # -10 and +10 still sum to the (zero) delta
    assert all(c["share"] is None for c in out["contributions"])  # share undefined


def _decompose_or_fail(before, after, value_col, by_col):
    """Call decompose_sum, turning a crash into a test failure (not an ERROR).

    Only the exception type is reported, never the frame's values."""
    try:
        return decompose_sum(before, after, value_col, by_col)
    except TypeError as exc:
        pytest.fail(f"decompose_sum raised {type(exc).__name__} on these categories")


def _null_category_frames():
    """Two frames whose empty-category rows carry almost all of the change."""
    before = _frame(
        [("west", 100), ("east", 50), (None, 600), (float("nan"), 400)]
    )  # whole frame: 1,150
    after = _frame([("west", 120), ("east", 40), (None, 5000)])  # whole: 5,160
    return before, after


def test_rows_with_a_null_category_are_counted():
    """Regression for #23. Rows whose `by_col` is empty (None from a JSON
    export, NaN from a CSV read) were dropped by the groupby, so a frame whose
    real change is 4,010 reported a delta of 10 with a True receipt. The null
    rows form one `None` category and the totals are the whole frames'."""
    before, after = _null_category_frames()
    out = _decompose_or_fail(before, after, "amount", "region")
    assert out["delta"] == 4010  # 5,160 - 1,150
    assert out["total_before"] == 1150
    assert out["total_after"] == 5160
    nulls = [c for c in out["contributions"] if c["category"] is None]
    assert len(nulls) == 1  # None and NaN are the same empty category
    assert nulls[0]["before"] == 1000
    assert nulls[0]["after"] == 5000
    assert nulls[0]["contribution"] == 4000
    assert sum(c["contribution"] for c in out["contributions"]) == out["delta"]
    assert out["receipt"] is True


def _sums_dropping_nulls(frame, value_col, by_col):
    """The pre-#23 grouping: groupby's default dropna=True loses null rows."""
    sums = frame.groupby(by_col, dropna=True)[value_col].sum()
    return {k: float(v) for k, v in sums.items()}


def test_receipt_fails_when_the_grouping_drops_rows(monkeypatch):
    """Regression for #23. The old receipt compared the contributions with a
    delta built from the same grouped sums, so it was True by construction.
    Put the old null-dropping grouping back: the delta is still the
    whole-frame change, the contributions no longer reach it, and the
    receipt must say so."""
    monkeypatch.setattr(decompose, "_sums_by", _sums_dropping_nulls)
    before, after = _null_category_frames()
    out = decompose_sum(before, after, "amount", "region")
    assert sum(c["contribution"] for c in out["contributions"]) == 10  # nulls lost
    assert out["delta"] == 4010  # 5,160 - 1,150, taken from the whole frames
    assert out["receipt"] is False


def test_receipt_holds_at_large_magnitudes():
    """Regression for #23. The receipt used an absolute tolerance of 1e-9, so
    on legitimate float sums in the 1e6 to 1e9 range rounding alone made it
    False almost every time. Each draw is its own pair of frames, so the delta
    is far from zero; the receipt must hold on every one."""
    rng = np.random.default_rng(23)
    categories = ["0042", "0107", "north", "south"]  # ids keep leading zeros
    failed = []
    for draw in range(200):
        before = _frame(
            zip(rng.choice(categories, 8), rng.uniform(1e6, 1e9, 8), strict=True)
        )
        after = _frame(
            zip(rng.choice(categories, 8), rng.uniform(1e6, 1e9, 8), strict=True)
        )
        out = _decompose_or_fail(before, after, "amount", "region")
        if out["receipt"] is not True:
            failed.append(draw)
    assert failed == [], f"receipt was not True on {len(failed)} of 200 draws"


def _cents_frames(seed, n=10_000):
    """A ledger of n amounts from 0.01 to 10,000.00 (whole cents), and the
    same ledger with 1% of its rows moved by 1 to 50 cents either way, so the
    delta is a few dollars against totals near 50 million."""
    rng = np.random.default_rng(seed)
    region = rng.choice(["0042", "0107", "0300", "north", "south", "EU-west"], n)
    cents = rng.integers(1, 1_000_001, n)
    moved = rng.choice(n, n // 100, replace=False)
    step = rng.integers(1, 51, moved.size) * rng.choice([-1, 1], moved.size)
    after_cents = cents.copy()
    after_cents[moved] = np.clip(cents[moved] + step, 1, 1_000_000)
    before = pd.DataFrame({"region": region, "amount": cents / 100})
    after = pd.DataFrame({"region": region, "amount": after_cents / 100})
    return before, after


def test_receipt_holds_when_the_delta_is_tiny_next_to_the_totals():
    """Regression for #23. A tolerance relative to the delta is too tight when
    a few dollars move inside a 50-million ledger: float rounding in the
    totals alone is larger than 1e-9 of the delta. The tolerance scales to
    the absolute volume of the values, so the receipt must hold on every
    seed."""
    failed = []
    for seed in range(10):
        before, after = _cents_frames(seed)
        out = decompose_sum(before, after, "amount", "region")
        if out["receipt"] is not True:
            failed.append(seed)
    assert failed == [], f"receipt was not True on seeds {failed} of 0-9"


@pytest.mark.parametrize(
    "move, receipt",
    [(1.00, False), (0.01, True)],
    ids=["a lost dollar is seen", "a lost cent is under the tolerance"],
)
def test_receipt_sees_a_small_lost_row_at_scale(monkeypatch, move, receipt):
    """Regression for #23. The tolerance is about 1e-9 of the absolute volume
    of the values: about $0.05 on a ledger of about $50M. Put the old
    null-dropping grouping back and give one row an empty region in both
    frames, so that row falls out of the contributions. If it moved by $1.00
    (about 20 times the tolerance) the receipt must read False; if it moved
    by $0.01 the receipt reads True, the documented limit of what it sees."""
    monkeypatch.setattr(decompose, "_sums_by", _sums_dropping_nulls)
    before, after = _cents_frames(0)
    volume = before["amount"].abs().sum()
    assert 45e6 < volume < 55e6  # so the tolerance is about $0.05
    lost = 4_242
    before.loc[lost, "region"] = None
    after.loc[lost, "region"] = None
    after.loc[lost, "amount"] = before.loc[lost, "amount"] + move
    out = decompose_sum(before, after, "amount", "region")
    summed = sum(c["contribution"] for c in out["contributions"])
    assert out["delta"] - summed == pytest.approx(move, abs=1e-6)  # the row is lost
    assert out["receipt"] is receipt


def _balanced_ledger_frames(seed, n=5_000):
    """A balanced ledger of n whole-cent lines, debits and credits from
    -1,000,000.00 to 1,000,000.00 under account codes with leading zeros,
    whose last line is set so the cents sum to exactly 0. The after frame
    moves two other lines by offsetting cents (+0.05 on one, -0.05 on the
    other), so both totals and the true change are all 0."""
    rng = np.random.default_rng(seed)
    accounts = ["0100", "0110", "0200", "1200-AR", "2000-AP", "4000", "6100"]
    region = rng.choice(accounts, n)
    cents = rng.integers(-100_000_000, 100_000_001, n)
    cents[-1] = -cents[:-1].sum()  # the balancing line
    up, down = rng.choice(n - 1, 2, replace=False)
    after_cents = cents.copy()
    after_cents[up] += 5
    after_cents[down] -= 5
    before = pd.DataFrame({"region": region, "amount": cents / 100})
    after = pd.DataFrame({"region": region, "amount": after_cents / 100})
    return before, after


def test_receipt_holds_when_the_totals_net_to_zero():
    """Regression for #23. A tolerance scaled to the totals collapses to 1e-9
    on a balanced ledger, where debits and credits net to 0 but each line is
    up to a million: float rounding in sums that large is bigger than 1e-9,
    so the receipt read False on correct data. The tolerance scales to the
    volume of the values (the sum of their absolute values), so the receipt
    must hold on every seed."""
    failed = []
    for seed in range(50):
        before, after = _balanced_ledger_frames(seed)
        out = decompose_sum(before, after, "amount", "region")
        if out["receipt"] is not True:
            failed.append(seed)
    assert failed == [], f"receipt was not True on seeds {failed} of 0-49"


def test_mixed_type_categories_do_not_raise():
    """Regression for #23. A `by_col` mixing ints and strings (ids parsed as
    numbers on some rows, codes on others) raised TypeError when the
    categories were sorted. With a null row too, it must decompose, keep
    each category as it was written, and sum to the whole-frame change."""
    before = _frame([(1, 100), ("a", 200), ("007", 50), (None, 300), (2, 25)])
    after = _frame([(1, 130), ("a", 150), ("007", 50), (None, 420), ("b", 60)])
    out = _decompose_or_fail(before, after, "amount", "region")
    by_category = {c["category"]: c["contribution"] for c in out["contributions"]}
    assert by_category == {1: 30, "a": -50, "007": 0, None: 120, 2: -25, "b": 60}
    assert out["delta"] == 135  # 810 - 675
    assert sum(c["contribution"] for c in out["contributions"]) == out["delta"]
    assert out["receipt"] is True


def test_tied_int_categories_keep_numeric_order():
    """Regression for #23. Sorting categories by their string form, to keep
    mixed types from comparing, put int ids in string order (10 before 2).
    Contributions tied on impact keep the category order, so unchanged int
    categories must come back in numeric order."""
    before = _frame([(10, 400), (3, 250), (7, 90), (2, 125), (10, 35)])
    after = _frame([(2, 125), (10, 435), (7, 130), (3, 250)])
    out = decompose_sum(before, after, "amount", "region")
    assert out["contributions"][0]["category"] == 7  # the one mover leads
    tied = [c["category"] for c in out["contributions"] if c["contribution"] == 0]
    assert tied == [2, 3, 10]
