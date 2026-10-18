"""Arc W3/H1: property invariants — the contracts that hold on ANY frame,
asserted across the input space instead of on hand-picked examples. These are
the promises the README makes implicitly; hypothesis's job is to find the
frame that breaks them before a user does."""

import io

import hypothesis.strategies as st
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings

from crivo.detect import detect_all

_CELLS = st.one_of(
    st.none(),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.floats(allow_nan=True, allow_infinity=True, width=32),
    st.text(max_size=12),
    st.sampled_from(["N/A", "-999", "", "  padded ", "café", "1,234.50", "Y", "no"]),
    st.datetimes(
        min_value=pd.Timestamp("1970-01-01").to_pydatetime(),
        max_value=pd.Timestamp("2120-01-01").to_pydatetime(),
    ),
)


@st.composite
def frames(draw):
    n_cols = draw(st.integers(min_value=0, max_value=6))
    n_rows = draw(st.integers(min_value=0, max_value=25))
    names = draw(
        st.lists(
            st.text(min_size=0, max_size=10),
            min_size=n_cols,
            max_size=n_cols,
            unique=True,
        )
    )
    data = {
        name: draw(st.lists(_CELLS, min_size=n_rows, max_size=n_rows)) for name in names
    }
    return pd.DataFrame(data)


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(frames())
def test_detect_all_never_raises_and_never_mutates(frame):
    before = frame.copy(deep=True)
    result = detect_all(frame)
    assert set(result) == {"findings", "clear", "broken"}
    assert result["broken"] == {}, "a signal crashed on a generated frame"
    pd.testing.assert_frame_equal(frame, before)


def _unreviewed(frame, cleaned, summary) -> list:
    """Every finding detect_all still raises on the cleaned frame that has no
    needs_review entry of the same disease, grade and leading column: the
    findings clean() left over silently. The leading column is what
    detect_one counts as the same finding (d11's key, however many
    attributes it has since gained or lost; #25), and a whole-table finding
    with no columns matches on disease and grade alone. A d18 repair renames
    columns after every other fix ran (and after d19's drops), so a leftover
    counts as listed under its final name or under the one it had before the
    rename."""
    dropped = {
        str(c) for a in summary.applied if a["disease"] == 19 for c in a["columns"]
    }
    kept = [str(c) for c in frame.columns if str(c) not in dropped]
    final = [str(c) for c in cleaned.columns]
    back = dict(zip(final, kept)) if len(kept) == len(final) else {}

    def lead(columns):
        return str(columns[0]) if columns else None

    listed = {
        (r["disease"], r["grade"], lead(r["columns"])) for r in summary.needs_review
    }
    missing = []
    for f in detect_all(cleaned)["findings"]:
        names = [str(c) for c in f["columns"]]
        first = lead(names)
        under = {first, back.get(first, first)}
        if not any((f["disease"], f["grade"], k) in listed for k in under):
            missing.append((f["disease"], names, f["grade"]))
    return missing


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(frames())
def test_clean_is_pure_idempotent_and_keeps_the_verify_promise(frame):
    import inspect

    from crivo.autoclean import clean
    from crivo.detect import detect_one

    assert "grade" in inspect.signature(detect_one).parameters, (
        "detect_one(df, disease, columns, grade=None) is the contract"
    )
    before = frame.copy(deep=True)
    cleaned, summary = clean(frame)
    pd.testing.assert_frame_equal(frame, before)  # never mutates its input

    # verify-or-revert, restated post-hoc: every applied fix's signal is
    # still gone on the FINAL frame — later fixes never resurrect a disease.
    # The signal is the fix's own grade: a HUMAN finding of the same disease
    # on the same column is a different finding, and stays open (#25)
    for fix in summary.applied:
        cols = [c for c in fix["columns"] if c in cleaned.columns]
        if fix["disease"] != 19 and cols:
            residual = detect_one(cleaned, fix["disease"], cols, grade=fix["grade"])
            assert residual is None, fix

    # and the visibility half (#25): whatever is left on the cleaned frame is
    # in needs_review, so a summary never reads cleaner than the frame it
    # returned. The message names diseases and columns, never cell values.
    silent = _unreviewed(frame, cleaned, summary)
    assert not silent, f"left over, not in needs_review: {silent}"

    again, second = clean(cleaned)
    assert not second.applied, f"second pass re-applied: {second.applied}"
    pd.testing.assert_frame_equal(again, cleaned)


def _refunds() -> pd.DataFrame:
    """An orders export's refund column: '$0.00' on 16 of 20 rows. As text it
    is d01 (AUTO) and nothing else, and the number fix is correct. Typed, it
    is 0.0 sixteen times against one of anything else, d04's placeholder
    signature (HUMAN: a zero may be a real refund of nothing)."""
    refunds = ["$0.00"] * 16 + ["$12.50", "$7.25", "$1,204.99", "$38.00"]
    ids = [f"{n:06d}" for n in range(417, 417 + 11 * len(refunds), 11)]
    return pd.DataFrame({"order_id": ids, "refund": refunds})


def _export_with_footer() -> pd.DataFrame:
    """A CRM export read from its CSV: three legacy columns no one fills
    (d19, AUTO, dropped) and a '-- end of export --' line at the bottom. With
    the empty columns in, every row is half blank and the footer does not
    stand out; once they are dropped it is d24's mostly-empty footer (GATE)."""
    regions = ["West", "East", "North", "South", "Central", "West", "East"] * 2
    amounts = ["125.00", "89.50", "1204.99", "47.25", "310.00", "66.00", "18.75"]
    amounts += ["990.00", "402.50", "73.10", "12.00", "845.60", "59.99", "230.00"]
    lines = ["account_id,region,amount,fax,pager,notes"]
    lines += [
        f"{2203 + 9 * k:06d},{region},{amount},,,"
        for k, (region, amount) in enumerate(zip(regions, amounts))
    ]
    lines.append("-- end of export --,,,,,")
    return pd.read_csv(io.StringIO("\n".join(lines)), dtype={"account_id": str})


@pytest.mark.parametrize(
    ("build", "fixes", "uncovered"),
    [
        (_refunds, {(1, ("refund",))}, (4, ["refund"], "HUMAN")),
        (
            _export_with_footer,
            {(19, ("fax",)), (19, ("pager",)), (19, ("notes",))},
            (24, [], "GATE"),
        ),
    ],
    ids=["typed-zeros-read-as-a-placeholder", "dropped-columns-bare-a-footer"],
)
def test_a_finding_a_correct_fix_uncovers_is_listed_not_left_silent(
    build, fixes, uncovered
):
    """Regression for #25. clean() builds needs_review from the findings it
    saw BEFORE fixing, so a finding that shows only on the fixed frame was
    left over with nothing saying so. Each frame carries a correct fix that
    makes a finding of another disease readable. The repair is kept (refusing
    it would lose a correct fix: the zeros and the footer were there all
    along) and the uncovered finding is listed beside it, once, with the reason
    for a finding no pre-fix diagnosis carried (decided on #25, 2026-10-17):
    the fixes found it, it was not 'still' anywhere."""
    from crivo.autoclean import clean

    frame = build()
    disease, columns, grade = uncovered
    before = {(f["disease"], f["grade"]) for f in detect_all(frame)["findings"]}
    assert (disease, grade) not in before, "the premise of this test"

    cleaned, summary = clean(frame)

    applied = {(a["disease"], tuple(a["columns"])) for a in summary.applied}
    assert applied == fixes, summary.needs_review
    entries = [
        r
        for r in summary.needs_review
        if r["disease"] == disease and r["columns"] == columns and r["grade"] == grade
    ]
    assert [r.get("reason") for r in entries] == ["found once the fixes ran"], (
        summary.needs_review
    )
    silent = _unreviewed(frame, cleaned, summary)
    assert not silent, f"left over, not in needs_review: {silent}"
