"""Deterministic cleaning — the wedge against pandas-ai (Phase 1).

`aa.clean(df)` fixes the safe diseases with no LLM and no kernel, verifies each
fix the way the agent does (the detector re-runs clean or the fix reverts), and
returns a cleaned frame plus a summary of what it did and what it left for a
human. pandas-ai has no answer to this: it cannot clean your data
trustworthily, only chat with it.
"""

import pandas as pd
import pytest
from test_autoclean_regressions import _excel_damaged_ids
from test_detect import _PRICES, _plant

import crivo as aa
from crivo.autoclean import CleanSummary, changed_cells

# The two public ways to call the deterministic cleaner, each taking the frame
# first and passing any further arguments straight through.
_CLEAN_ENTRY_POINTS = {
    "crivo.clean": lambda df, *args, **kwargs: aa.clean(df, *args, **kwargs),
    "df.crivo.clean": lambda df, *args, **kwargs: df.crivo.clean(*args, **kwargs),
}


@pytest.mark.parametrize("entry", list(_CLEAN_ENTRY_POINTS))
def test_clean_takes_no_policy(entry: str) -> None:
    """#29: `policy` was accepted and never read, so `policy="all"` read as if
    it widened what runs. Both entry points refuse it with a TypeError, by
    keyword or by position, and the bare call still cleans the frame."""
    call = _CLEAN_ENTRY_POINTS[entry]
    df = pd.DataFrame(
        {
            "invoice_id": [f"{n:06d}" for n in range(1, 21)],  # leading zeros
            "amount": ["$1,200", "$3,400.50", "$15", "$980"] * 5,  # d01 AUTO
            "status": (["paid", "late", "N/A"] * 6) + ["paid", "N/A"],  # d04 AUTO
        }
    )
    original = df.copy()

    cleaned, summary = call(df)

    # the legitimate call: same fixes, same frame, input untouched
    assert isinstance(summary, CleanSummary)
    assert df.equals(original), "clean must not touch the input frame"
    assert {a["disease"] for a in summary.applied} == {1, 4}
    assert summary.needs_review == []
    assert cleaned["amount"].tolist()[:4] == [1200.0, 3400.5, 15.0, 980.0]
    assert cleaned["status"].isna().sum() == 7, "the seven N/A sentinels -> NaN"
    assert cleaned["invoice_id"].tolist()[:2] == ["000001", "000002"]

    # the dead argument: refused, not silently ignored
    with pytest.raises(TypeError, match="policy"):
        call(df, policy="all")
    with pytest.raises(TypeError):
        call(df, "all")


def test_changed_cells_reports_the_before_and_after_of_a_value_fix() -> None:
    before = pd.DataFrame({"amount": ["$1,200", "$15"], "note": ["a", "b"]})
    after = pd.DataFrame({"amount": [1200.0, 15.0], "note": ["a", "b"]})
    applied = [{"disease": 1, "slug": "numbers-as-strings", "columns": ["amount"]}]

    out = changed_cells(before, after, applied)

    assert len(out) == 1
    fix = out[0]
    assert fix["disease"] == 1 and fix["columns"] == ["amount"]
    pairs = {(e["old"], e["new"]) for e in fix["examples"]}
    assert ("$1,200", 1200.0) in pairs
    assert all(e["column"] == "amount" for e in fix["examples"])


def test_changed_cells_reports_a_dropped_constant_column_as_removed() -> None:
    before = pd.DataFrame({"amount": [1.0, 2.0], "constant": ["x", "x"]})
    after = pd.DataFrame({"amount": [1.0, 2.0]})
    applied = [{"disease": 19, "slug": "constant-column", "columns": ["constant"]}]

    out = changed_cells(before, after, applied)

    assert out[0]["examples"] == [{"column": "constant", "removed": True, "value": "x"}]


def test_changed_cells_is_empty_when_a_fix_changed_nothing() -> None:
    frame = pd.DataFrame({"note": ["a", "b"]})
    applied = [{"disease": 6, "slug": "whitespace", "columns": ["note"]}]

    out = changed_cells(frame, frame.copy(), applied)

    assert out[0]["examples"] == []


def test_summary_samples_are_the_changed_cells_of_the_applied_fixes() -> None:
    df = pd.DataFrame({"amount": ["$1,200", "$3,400.50", "$15", "$980"] * 5})
    _cleaned, summary = aa.clean(df)

    samples = summary.samples()

    assert any(
        s["disease"] == 1 and any(e.get("new") == 1200.0 for e in s["examples"])
        for s in samples
    )


def test_clean_summary_repr_html_renders_the_notebook_card() -> None:
    """In a notebook, a clean summary renders as the HTML card — an applied fix
    marked done and at least one before/after example."""
    df = pd.DataFrame(
        {"amount": ["$1,200", "$3,400.50", "$15", "$980"] * 5, "const": ["x"] * 20}
    )
    _cleaned, summary = aa.clean(df)

    html = summary._repr_html_()

    assert html.startswith("<div")
    assert "✓" in html
    assert "→" in html


def test_clean_summary_diff_is_a_styler_of_the_changed_frame() -> None:
    """`summary.diff()` is the opt-in full-frame highlighted view."""
    import pytest

    pytest.importorskip("jinja2")
    from pandas.io.formats.style import Styler

    df = pd.DataFrame({"amount": ["$1,200", "$3,400.50", "$15", "$980"] * 5})
    _cleaned, summary = aa.clean(df)

    assert isinstance(summary.diff(), Styler)


def test_styler_diff_returns_a_styler_highlighting_the_changed_cells() -> None:
    import pytest

    pytest.importorskip("jinja2")  # pandas Styler needs it; diff() is opt-in extra
    from pandas.io.formats.style import Styler

    from crivo.autoclean import styler_diff

    before = pd.DataFrame({"amount": ["$1,200", "$15"]})
    after = pd.DataFrame({"amount": [1200.0, 15.0]})

    styled = styler_diff(before, after)

    assert isinstance(styled, Styler)
    html = styled.to_html()
    assert "background-color: #1e3a32" in html


def test_clean_fixes_the_safe_diseases_and_defers_the_judgement_calls() -> None:
    df = pd.DataFrame(
        {
            "amount": ["$1,200", "$3,400.50", "$15", "$980"] * 5,  # d01 AUTO
            "status": (["ok", "late", "N/A"] * 6) + ["ok", "N/A"],  # d04 AUTO
            "note": ["  spaced  ", "clean", "two  spaces", "x"] * 5,  # d06 AUTO
            "constant": ["same"] * 20,  # d19 AUTO
            # decimal-comma and symbol coexisting => the same digits read two
            # ways => d01 grades GATE, so clean must defer, not guess
            "amount_eu": ["27,29", "$1,200", "3,50", "$980"] * 5,
        }
    )
    original = df.copy()

    cleaned, summary = aa.clean(df)

    # the input is never mutated — the cleaned frame is a new object
    assert df.equals(original), "clean must not touch the input frame"
    # safe fixes applied and verified
    assert pd.api.types.is_numeric_dtype(cleaned["amount"]), "d01 coerced"
    assert cleaned["status"].isna().sum() == 7, "d04 sentinels -> NaN"
    assert cleaned["note"].tolist()[:3] == ["spaced", "clean", "two spaces"], "d06"
    assert "constant" not in cleaned.columns, "d19 constant column dropped"
    applied = {a["disease"] for a in summary.applied}
    assert {1, 4, 6, 19} <= applied
    # the ambiguous mixed-money column is deferred, not guessed
    assert any(
        r["disease"] == 1 and r["columns"] == ["amount_eu"]
        for r in summary.needs_review
    )
    assert not pd.api.types.is_numeric_dtype(cleaned["amount_eu"]), (
        "GATE not auto-fixed"
    )


def test_a_fix_that_would_not_verify_is_reverted_not_applied(monkeypatch) -> None:
    """The whole promise: a deterministic fix is trusted only because the
    detector re-runs clean. If a fixer produced garbage that still tripped the
    signal, the frame must come back untouched for that column and the finding
    must land in review — never silently 'fixed'."""
    from crivo import autoclean

    def broken_whitespace(frame, cols):
        out = frame.copy()
        for c in cols:
            out[c] = out[c]  # a no-op 'fix' — the signal will still fire
        return out

    monkeypatch.setitem(autoclean.FIXERS, 6, broken_whitespace)
    df = pd.DataFrame({"note": ["  spaced  ", "clean", "two  spaces", "x"] * 5})

    cleaned, summary = aa.clean(df)

    assert cleaned["note"].equals(df["note"]), "an unverified fix must not stick"
    assert not any(a["disease"] == 6 for a in summary.applied)
    assert any(
        r["disease"] == 6 and "did not clear" in r.get("reason", "")
        for r in summary.needs_review
    )


def test_clean_makes_a_real_file_pass_its_own_detectors() -> None:
    """The end-to-end promise on real data: read a government spending file,
    clean it, and the columns the safe fixes touched no longer trip their
    detectors — proven by re-diagnosing the cleaned frame."""
    from pathlib import Path

    src = Path("data/external/public-spend/hmt-spend-2026-03.csv")
    if not src.exists():
        import pytest

        pytest.skip("run scripts/fetch_public_spend.py for the real file")

    df = aa.read(src)
    cleaned, summary = aa.clean(df)
    after = {f["disease"] for f in aa.diagnose(cleaned).findings}

    assert summary.applied, "a real messy file should get at least one safe fix"
    # every disease clean claims it applied is gone from the re-diagnosis
    for a in summary.applied:
        assert a["disease"] not in after or a["disease"] in {
            r["disease"] for r in summary.needs_review
        }, f"claimed d{a['disease']} fixed but it still fires"
    assert df.equals(aa.read(src)), "the input frame was mutated"


def test_clean_on_the_example_applies_the_safe_fixes_and_lists_what_is_left() -> None:
    """Pins beside #24 and #25: a finding an applied fix cleared never comes
    back as a review entry, and one the cleaned frame still carries is listed
    (Aarmen, 2026-10-17). On the example, d01 makes revenue numeric, which
    bares d15 outliers the string column hid; it is listed beside d09. diagnose
    reports d15 checked and clean on the original, so the entry says the fixes
    found it, not that it is still there (decided on #25, 2026-10-17)."""
    _cleaned, summary = aa.clean(aa.load_example())

    assert [a["disease"] for a in summary.applied] == [4, 6, 7, 1]
    assert [r["disease"] for r in summary.needs_review] == [9, 15]
    d15 = next(r for r in summary.needs_review if r["disease"] == 15)
    assert d15.get("reason") == "found once the fixes ran", d15


def test_an_auto_finding_without_a_fixer_says_why() -> None:
    """Regression for #24. d09 grades AUTO but has no fixer on purpose, so
    clean() left it in review with no reason, and the summary read "safe to fix
    automatically" with nothing to say why it was not. The reason travels in
    the entry and on the line a person reads."""
    from crivo.autoclean import FIXERS

    assert 9 not in FIXERS, "the premise of this test"
    _cleaned, summary = aa.clean(aa.load_example())

    entry = next(r for r in summary.needs_review if r["disease"] == 9)
    assert entry["grade"] == "AUTO"
    assert "duplicate rows" in entry.get("reason", ""), entry
    assert any(
        line.lstrip().startswith("· d09") and "duplicate rows" in line
        for line in repr(summary).splitlines()
    ), repr(summary)


def test_an_auto_finding_with_no_fixer_yet_gets_the_generic_reason() -> None:
    """Regression for #24. The same silent path as d09, for a disease that is
    missing a fixer rather than denied one: a census count column with "<5"
    suppression flags fires d05 AUTO, and its review entry says there is no
    fixer yet rather than nothing."""
    from crivo.autoclean import FIXERS

    counts = ["124", "87", "342", "15", "219", "603", "48", "911", "137", "260"] * 2
    counts[3] = counts[14] = "<5"
    df = pd.DataFrame(
        {"area_code": [f"{n:05d}" for n in range(20)], "residents": counts}
    )

    assert 5 not in FIXERS, "the premise of this test"
    _cleaned, summary = aa.clean(df)

    entry = next(r for r in summary.needs_review if r["disease"] == 5)
    assert entry["grade"] == "AUTO"
    assert "no deterministic fixer" in entry.get("reason", ""), entry


def test_a_refused_fix_is_listed_once_and_keeps_its_reason(monkeypatch) -> None:
    """Pin beside #24: a finding clean() attempted and refused is in review
    once, with the refusal's reason, not again as a bare copy or with the
    no-fixer wording."""
    from crivo import autoclean

    monkeypatch.setitem(autoclean.FIXERS, 6, lambda frame, cols: frame.copy())
    df = pd.DataFrame({"note": ["  spaced  ", "clean", "two  spaces", "x"] * 5})

    _cleaned, summary = aa.clean(df)

    entries = [r for r in summary.needs_review if r["disease"] == 6]
    assert len(entries) == 1, entries
    assert entries[0]["grade"] == "AUTO"
    assert entries[0]["reason"] == "fix did not clear verification"


@pytest.mark.parametrize(
    ("gaps", "via_csv", "stacked"),
    [
        (("", ""), True, False),
        ((None, None), False, False),
        (("", None), False, False),
        (("", None), False, True),
    ],
    ids=["csv-blanks", "nan", "blank-and-nan", "stacked-exports"],
)
def test_clean_clears_a_typed_in_minus_999_beside_blank_and_nan_cells(
    tmp_path, gaps, via_csv, stacked
) -> None:
    """Regression for #26. The d04 fixer re-derives which cells to clear on
    its own (the loop calls FIXERS[4](df, cols) with nothing else), and it
    sees the gaps the detector skips: crivo's readers keep a blank cell as ""
    (keep_default_na=False), and a frame built in code holds NaN. A gap is not
    a number, so a fixer that judged -999 against it would leave the -999,
    fail verification and revert, taking the N/A clearing with it.

    stacked-exports pins sentinel_mask's "positional, so a non-unique index is
    safe": two 18-reading gauge exports stacked with pd.concat carry every row
    label twice, and a mask written by label would also clear the real reading
    that shares a placeholder's label."""
    rain = [f"{0.4 + i * 1.3:.1f}" for i in range(36)]  # 0.4 .. 45.9 mm
    planted = {3: "-999", 12: "N/A", 17: "-999", 26: "N/A", 33: "-999"}
    for row, cell in {**planted, 8: gaps[0], 21: gaps[1]}.items():
        rain[row] = cell
    ids = [f"R{i:04d}" for i in range(36)]
    if via_csv:
        path = tmp_path / "gauge.csv"
        rows = "".join(f"{i},{v}\n" for i, v in zip(ids, rain, strict=True))
        path.write_text("reading_id,rain_mm\n" + rows)
        frame = aa.read(path)
        assert frame.loc[8, "rain_mm"] == "", "the premise: the blank arrives as text"
    else:
        frame = pd.DataFrame({"reading_id": ids, "rain_mm": rain})
    if stacked:
        frame.index = list(range(18)) * 2
        assert not frame.index.is_unique, "the premise: each label twice"

    cleaned, summary = aa.clean(frame)

    # by position throughout: under stacked-exports a label names two rows
    col = cleaned["rain_mm"]
    assert col.iloc[[3, 17, 33]].isna().tolist() == [True] * 3
    assert col.iloc[[12, 26]].isna().tolist() == [True] * 2
    # every real reading is left exactly as it was
    real = [p for p in range(36) if p not in {*planted, 8, 21}]
    assert col.iloc[real].tolist() == frame["rain_mm"].iloc[real].tolist()
    # the fix verified: applied, not reverted into review
    assert [a["columns"] for a in summary.applied if a["disease"] == 4] == [["rain_mm"]]
    assert not any(r["disease"] == 4 for r in summary.needs_review)


# ledger adjustments run -5000..5000, so -999 is a real adjustment here
_LEDGER = [
    "-5000",
    "-2500.00",
    "-999",
    "-120.50",
    "0",
    "45.10",
    "999",
    "2500",
    "5000",
    "-999",
    "310.25",
    "-999",
] * 3


@pytest.mark.parametrize(
    ("column", "cells", "token"),
    [
        # used-car prices up to 20000, two listings not yet priced
        ("list_price", _PRICES + ["N/A", "N/A"], "9999"),
        # a ledger export with two adjustments marked N/A and one left blank
        ("balance_change", _plant(_LEDGER, {4: "N/A", 16: "", 28: "N/A"}), "-999"),
    ],
    ids=["prices-reach-9999", "ledger-spans-minus-999"],
)
def test_clean_keeps_a_strong_token_the_real_values_reach(column, cells, token) -> None:
    """Pin beside #26, in the fixer. test_detect pins that d04 does not name a
    9999 or -999 the real values reach, but _fix_sentinels re-derives which
    cells to clear from the whole column, and it is the step that deletes
    data. The N/A cells beside the real token are still cleared."""
    frame = pd.DataFrame(
        {"row_id": [f"{i:06d}" for i in range(len(cells))], column: cells}
    )
    na = [p for p, v in enumerate(cells) if v == "N/A"]
    real = [p for p, v in enumerate(cells) if v not in {"N/A", ""}]
    assert cells.count(token) >= 3, "the premise: the token is a real value here"

    cleaned, summary = aa.clean(frame)

    assert [a["columns"] for a in summary.applied if a["disease"] == 4] == [[column]]
    assert cleaned[column].iloc[na].isna().all()
    kept = cleaned[column].iloc[real].tolist()
    assert [v for v in kept if v == token] == [token] * cells.count(token)
    assert kept == [cells[p] for p in real]


def _excel_damaged_ids_with_states() -> pd.DataFrame:
    """The Excel-damaged transactions export (two d22 GATE findings on
    txn_id: three ids with the apostrophe guard, three a numeric cast ate)
    with a state column beside it: three casings of California (d07 AUTO,
    which clean() folds) and two misspellings a person maps (d07 HUMAN)."""
    frame = _excel_damaged_ids()
    frame["state"] = (
        ["California"] * 9
        + ["california", "CALIFORNIA"]
        + ["Pennsylvania"] * 6
        + ["Pensylvania"]
        + ["Washington"] * 6
        + ["Massachusetts"] * 5
        + ["Massachusets"]
    )
    return frame


def test_a_d22_review_entry_says_which_damage_and_quotes_no_id() -> None:
    """Regression for #47. The two d22 GATE findings on one id column, the
    apostrophe guard and the ids a numeric cast ate, made review entries that
    were identical dicts, so nothing a person or a machine read could tell
    them apart. Each now carries `kind`, "guarded" or "eaten", read from which
    count its finding holds, never an id. Entries of any other disease, the
    d07 fold applied beside them and the d07 spelling left in review, carry
    no `kind`."""
    frame = _excel_damaged_ids_with_states()

    _cleaned, summary = aa.clean(frame)

    # a count first, so no later failure message can carry an id
    leaked = sum(1 for cell in set(frame["txn_id"]) if cell in summary.to_json())
    assert leaked == 0
    kinds = [r.get("kind") for r in summary.needs_review if r["disease"] == 22]
    assert kinds == ["guarded", "eaten"], summary.needs_review
    others = [r for r in summary.applied + summary.needs_review if r["disease"] != 22]
    assert [(r["disease"], r["grade"]) for r in others] == [(7, "AUTO"), (7, "HUMAN")]
    assert not any("kind" in r for r in others), others


def test_a_numeric_id_column_with_eaten_zeros_reviews_as_eaten() -> None:
    """Regression for #47. d22's numeric path, a zip column read as integers
    that lost its leading zeros, counts the short ids as `shorter`, not
    `eaten`. It is the same damage the text path calls eaten, so its review
    entry says "eaten" too, on the entry and on the line, and quotes no zip."""
    zips = [35233, 90210, 60614, 98101, 87501, 55401, 73301, 33101, 44101]
    zips += [66101, 77001, 15201, 2115, 2138, 1002]  # 02115, 02138, 01002 lost a 0
    cities = ["Birmingham", "Beverly Hills", "Chicago", "Seattle", "Santa Fe"]
    cities += ["Minneapolis", "Austin", "Miami", "Cleveland", "Kansas City"]
    cities += ["Houston", "Pittsburgh", "Boston", "Cambridge", "Amherst"]
    frame = pd.DataFrame({"zip_code": zips, "city": cities})

    _cleaned, summary = aa.clean(frame)

    # a count first, so no later failure message can carry a zip
    shown = summary.to_json() + repr(summary)
    leaked = sum(1 for z in zips if str(z) in shown or f"{z:05d}" in shown)
    assert leaked == 0
    d22 = [r for r in summary.needs_review if r["disease"] == 22]
    assert [(r["columns"], r.get("kind")) for r in d22] == [(["zip_code"], "eaten")]
    lines = [line for line in repr(summary).splitlines() if " d22 " in line]
    assert len(lines) == 1, lines
    assert lines[0].rstrip().endswith("GATE eaten"), lines
