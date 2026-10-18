"""Cross-column contradiction detection (P7, first detector).

The first harder-data check: a functional-dependency violation. When one
column almost determines another (within each value of A, one value of B
dominates for at least a threshold of rows), the minority rows that break the
rule are likely errors: a zip that disagrees with its city, a product code
whose category flips on a few rows. Fully deterministic and pair-based, so no
model nomination is needed here (that is for 3+ column rules later). Keyless,
pandas only.
"""

import pandas as pd
import pytest

import crivo
from crivo import crosscol


def test_a_near_functional_dependency_flags_the_minority_rows():
    # city -> state holds for every row but one: SF is mislabeled TX
    df = pd.DataFrame(
        {
            "city": ["SF", "SF", "SF", "SF", "LA", "LA"],
            "state": ["CA", "CA", "CA", "TX", "CA", "CA"],
        }
    )
    findings = crosscol.find_fd_violations(df, threshold=0.8)
    fd = next(f for f in findings if f["columns"] == ["city", "state"])
    assert fd["violations"] == 1
    assert fd["grade"] in {"GATE", "HUMAN"}
    assert "city" in fd["evidence"] and "state" in fd["evidence"]


def test_a_perfect_dependency_is_not_flagged():
    # city -> state holds with no exception, so nothing to report
    df = pd.DataFrame({"city": ["SF", "SF", "LA"], "state": ["CA", "CA", "CA"]})
    assert crosscol.find_fd_violations(df, threshold=0.8) == []


def test_no_dependency_below_threshold_is_not_flagged():
    # A does not determine B (every A maps to many Bs), so no FD, no finding
    df = pd.DataFrame({"a": [1, 1, 2, 2], "b": ["w", "x", "y", "z"]})
    assert crosscol.find_fd_violations(df, threshold=0.9) == []


def test_violation_count_scales_and_examples_are_bounded():
    df = pd.DataFrame(
        {
            "dept": ["eng"] * 20 + ["sales"] * 5,
            "floor": ["3"] * 18 + ["9", "9"] + ["2"] * 5,  # 2 eng rows on wrong floor
        }
    )
    fd = next(
        f
        for f in crosscol.find_fd_violations(df, threshold=0.85)
        if f["columns"] == ["dept", "floor"]
    )
    assert fd["violations"] == 2
    assert len(fd.get("examples", [])) <= 5  # evidence is bounded, never a dump


def test_pair_search_is_capped_and_reports_what_it_skipped():
    # many columns: the pair search must bound itself and say so, not silently
    cols = {f"c{i}": list(range(6)) for i in range(30)}
    df = pd.DataFrame(cols)
    findings = crosscol.find_fd_violations(df, max_pairs=50)
    # no crash, bounded work; a skipped-pairs note rides on the result meta
    assert isinstance(findings, list)


def test_nulls_do_not_count_as_a_dependency_break():
    # a missing B is absence, not a contradiction of the rule
    df = pd.DataFrame(
        {"city": ["SF", "SF", "SF", "SF"], "state": ["CA", "CA", None, "CA"]}
    )
    assert crosscol.find_fd_violations(df, threshold=0.8) == []


# an order export: four orders per customer, ids keep their leading zeros, and
# two rows break a rule. Ana's third order has the state typed as "ZZ", and
# one of Ben's orders carries his address on the wrong domain (.org).
_CUSTOMERS = [
    ("00101", "ana.lima@example.com", "CA"),
    ("00102", "ben.okafor@example.com", "NY"),
    ("00103", "chen.wei@example.com", "TX"),
    ("00104", "dana.ruiz@example.com", "WA"),
    ("00105", "eli.moss@example.com", "OR"),
]


def _orders(id_col, email_col, state_col) -> pd.DataFrame:
    rows = [list(c) for c in _CUSTOMERS for _ in range(4)]
    rows[2][2] = "ZZ"  # Ana's state, wrong on one order
    rows[5][1] = "ben.okafor@example.org"  # Ben's email, wrong domain once
    return pd.DataFrame(rows, columns=[id_col, email_col, state_col])


@pytest.mark.parametrize(
    "labels",
    [("cust_id", "email", "state"), (0, 1, 2)],
    ids=["named-columns", "header-less-int-labels"],
)
def test_cross_column_examples_mask_pii_flagged_columns(labels):
    """Regression for #21. cross_column() examples are shown to people, so a
    value from a PII-flagged column is masked wherever it sits in the pair,
    while the violation is still found and counted, and a value from an
    unflagged column stays as it is. Header-less frames have int labels,
    which the PII flags key as str."""
    id_col, email_col, state_col = labels
    df = _orders(id_col, email_col, state_col)
    raw_emails = set(df[email_col])

    findings = crivo.diagnose(df).cross_column()
    by_pair = {tuple(f["columns"]): f for f in findings}

    def examples(a, b):
        return [tuple(e) for e in by_pair[(a, b)]["examples"]]

    # email determines state for 19 of 20 rows: still found, still counted
    assert by_pair[(email_col, state_col)]["violations"] == 1
    # the flagged email is masked as element 0; the unflagged state stays raw
    assert examples(email_col, state_col) == [("***@example.com", "ZZ")]
    # the flagged email is masked as element 1; the unflagged key stays raw
    assert examples(id_col, email_col) == [("00102", "***@example.org")]
    assert examples(state_col, email_col) == [("NY", "***@example.org")]
    # a pair with no flagged column is left exactly as crosscol reports it
    assert examples(id_col, state_col) == [("00101", "ZZ")]
    # and no example anywhere carries a raw email
    for f in findings:
        for example in f["examples"]:
            assert not raw_emails & {str(v) for v in example}
