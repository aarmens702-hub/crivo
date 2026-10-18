"""Wave 1.5: what the last four packets broke in the fixers.

Two kinds of regression, and they pull in opposite directions.

The silent ones first: a magnitude spelling that was left out of the refusal
set by accident, so "1.5MM" became 1.5 and was recorded verified, and a d19
target that is not in the frame at all, which returned the untouched frame and
was likewise recorded verified.

Then the over-refusals P2 bought and never paid back. Each one declines input
crivo can repair without guessing, and a refused repair is a repair lost: the
survival rate cannot tell "correctly declined" from "stopped fixing what it
used to fix well".

Where a token really is two things, the refusal stays and says so - see
`test_number_fix_still_refuses_the_millimetre_million_collision`.
"""

import pandas as pd
import pytest

from crivo import load_example
from crivo.autoclean import FIXERS, clean
from crivo.detect import detect_all, detect_one


def _reviewed(summary, disease, columns):
    return any(
        r["disease"] == disease and r["columns"] == columns
        for r in summary.needs_review
    )


# --- 15. magnitude spellings that were omitted by accident -------------------


def test_number_fix_refuses_the_finance_million_spelling():
    """'1.5MM' is 1,500,000 on every US finance desk. SCALE_SUFFIXES listed
    'mn' and 'bn' but not 'MM', so the fixer stripped it, wrote 1.5, and d01
    could no longer see the column at all: a million-fold error recorded as a
    verified fix."""
    values = ["1.5MM", "2.3MM", "0.8MM", "12.4MM", "7.1MM"] * 6

    cleaned, summary = clean(pd.DataFrame({"revenue": values}))

    assert cleaned["revenue"].tolist() == values, "the scale was stripped"
    assert not any(a["disease"] == 1 for a in summary.applied)
    assert _reviewed(summary, 1, ["revenue"]), summary.needs_review


def test_number_fix_refuses_the_single_letter_trillion():
    """Same hole, one letter wide: 'T' was missing beside 'tn'."""
    values = ["1.5T", "2.3T", "0.8T", "12.4T", "7.1T"] * 6

    cleaned, summary = clean(pd.DataFrame({"gdp": values}))

    assert cleaned["gdp"].tolist() == values, "the scale was stripped"
    assert not any(a["disease"] == 1 for a in summary.applied)


def test_number_fix_still_refuses_the_millimetre_million_collision():
    """The ambiguity kept on purpose, not closed. 'mm' is millimetres and the
    finance spelling for millions, and one column cannot tell them apart, so
    both readings refuse. A wrong magnitude is silent; a refusal is a line in
    needs_review that a person reads."""
    values = ["12 mm", "8 mm", "15 mm", "3 mm"] * 6

    cleaned, summary = clean(pd.DataFrame({"width": values}))

    assert cleaned["width"].tolist() == values
    assert not any(a["disease"] == 1 for a in summary.applied)
    assert _reviewed(summary, 1, ["width"]), summary.needs_review


# --- 9. units that merely begin with a magnitude letter ----------------------


def test_number_fix_still_refuses_a_rate_unit_that_begins_with_a_magnitude():
    """DELIBERATELY INVERTED from the wave 1.5 repair, which asserted "the
    slash proves this is a unit" and parsed '12 m/s' as 12 metres per second.
    The slash proves nothing: '4.5M/yr' is millions per year and wears exactly
    the same shape, so the rule that recovered this one stripped the scale off
    that one and recorded it verified. The two readings cannot be separated
    from the column, so this is the "mm" collision again and it takes the same
    answer - the refusal, and a line in needs_review a person reads.

    The cost is admitted rather than hidden: a genuine speed column goes to
    review. Item 9's recoverable half is the escape a magnitude can never
    wear, which `test_number_fix_repairs_a_unit_a_magnitude_can_never_wear`
    pins."""
    values = ["12 m/s", "3.5 m/s", "7 m/s", "21 m/s"] * 6

    cleaned, summary = clean(pd.DataFrame({"speed": values}))

    assert cleaned["speed"].tolist() == values
    assert not any(a["disease"] == 1 for a in summary.applied)
    assert _reviewed(summary, 1, ["speed"]), summary.needs_review


def test_number_fix_still_refuses_a_bitrate_that_begins_with_a_magnitude():
    """The same inversion one letter over. '40 b/s' is bits per second and
    '12B/day' is billions per day, and nothing in the column says which."""
    values = ["40 b/s", "1200 b/s", "9 b/s", "512 b/s"] * 6

    cleaned, summary = clean(pd.DataFrame({"rate": values}))

    assert cleaned["rate"].tolist() == values
    assert not any(a["disease"] == 1 for a in summary.applied)


# --- 10. one slot order, several values, and the 20% floor -------------------


def test_date_fix_refuses_the_order_a_fifth_of_the_column_does_not_support():
    """DELIBERATELY INVERTED from the wave 1.5 repair, which dropped the
    proportional floor to a flat count of two so this 27-value column would
    parse day-first. A count with no relation to column size says the same
    thing about two values in twenty as about two in two hundred: the same
    rule transposed 132 of 198 rows in a month-first column carrying two
    typos, silently, with zero NaT and recorded verified.

    Three in twenty-seven is a typo rate, not a convention, and "one order
    alone parses" does not separate them - a transposed typo makes the other
    order fail to parse too. So the floor stays and the ambiguity is named.
    This is the unclosed half of triage item 10; its other half, the report
    calling a refusal "fix did not clear verification", is a wording defect
    and is pinned below."""
    values = [f"{d:02d}/{m:02d}/2020" for d in (5, 7, 9, 11) for m in (1, 2, 3)]
    values += ["25/06/2020", "19/03/2020", "28/11/2020"]
    values += [f"{d:02d}/{m:02d}/2021" for d in (2, 4, 6) for m in (5, 6, 7, 8)]

    cleaned, summary = clean(pd.DataFrame({"d": values}))

    assert not any(a["disease"] == 2 for a in summary.applied)
    assert cleaned["d"].tolist() == values, "the column was parsed anyway"
    assert _reviewed(summary, 2, ["d"]), summary.needs_review


# --- 22 (sibling). iso-zoned columns with mixed offsets ----------------------


def test_date_fix_parses_an_iso_zoned_column_whose_offsets_differ():
    """_UNSWAPPABLE_FAMILIES sent iso-zoned to a bare pd.to_datetime, which
    RAISES on mixed UTC offsets instead of returning, so the null gate the
    comment promises never ran and the fixer died where it meant to refuse.
    datetime64 carries one offset per column, so the instants are kept in UTC
    and the per-row offset is not."""
    values = [
        "2020-01-01T08:00:00+01:00",
        "2020-01-02T09:00:00+02:00",
        "2020-01-03T10:00:00Z",
    ] * 8

    cleaned, summary = clean(pd.DataFrame({"ts": values}))

    assert 2 in {a["disease"] for a in summary.applied}, summary.needs_review
    assert pd.api.types.is_datetime64_any_dtype(cleaned["ts"])
    assert int(cleaned["ts"].isna().sum()) == 0, "instants were deleted"
    assert cleaned["ts"].iloc[0] == pd.Timestamp("2020-01-01T07:00:00Z")
    assert cleaned["ts"].iloc[1] == pd.Timestamp("2020-01-02T07:00:00Z")


# --- 14. a d19 target that is not in the frame -------------------------------


def test_constant_drop_raises_when_its_target_is_not_in_the_frame():
    """The refusal arm fired on count != 1, so an ABSENT name returned the
    frame untouched and looked exactly like a considered refusal. A refusal
    that cannot be told from a no-op is not a refusal."""
    frame = pd.DataFrame({"amount": [float(i) for i in range(20)], "k": ["x"] * 20})

    with pytest.raises(KeyError) as err:
        FIXERS[19](frame, ["ghost"])

    assert "ghost" in str(err.value)


def test_an_absent_d19_target_is_never_recorded_as_a_verified_fix():
    """Why the raise, end to end. d19 is COLUMN_CHANGING, so detect_one does
    not treat a vanished target as a failure, and an untouched frame carrying
    no other constant column clears the re-check: clean() would record the
    informationless column as fixed. Raising routes it to the fixer-error path
    instead, which is what the loop's revert also keys on."""
    frame = pd.DataFrame({"amount": [float(i) for i in range(20)], "k": ["x"] * 20})

    try:
        candidate = FIXERS[19](frame, ["ghost"])
    except KeyError:
        return  # the fixer-error path: reported, never recorded verified

    assert detect_one(candidate, 19, ["ghost"]) is not None, (
        "an untouched frame cleared the d19 re-check: a verified no-op"
    )


# --- 11. a row _d18 never counted as a header row ----------------------------


def test_header_fix_repairs_padding_over_a_row_d18_never_reported():
    """_repeats_header matches case-folded and whitespace-collapsed while _d18
    counts header rows verbatim. Here no row ever equalled the names, so the
    finding is padding and nothing else, and no earlier fixer touched row 0:
    'AMOUNT' is the only cell of its key in its column, so d07 had nothing to
    fold it onto. Refusing the rename declines a repair over a row the finding
    never reported."""
    frame = pd.DataFrame(
        {
            "amount ": ["AMOUNT"] + [str(v) for v in range(16)],
            "region": ["REGION"] + ["east", "west"] * 8,
        }
    )

    cleaned, summary = clean(frame)

    assert 18 in {a["disease"] for a in summary.applied}, summary.needs_review
    assert list(cleaned.columns) == ["amount", "region"], "the padding survived"
    assert cleaned.iloc[0].tolist() == ["AMOUNT", "REGION"], "a row was deleted"


def test_header_fix_still_refuses_a_row_an_earlier_fixer_folded_onto_the_name():
    """The line the recovery must not cross, kept from the P2 packet's own
    case: d07 folded the echo cell onto the column's most frequent spelling of
    the same key, so the cell no longer matches the name verbatim but the row
    IS the header row d18 reported. The give-away is that the spelling occurs
    elsewhere in the column, which is the only way d07 could have written it."""
    frame = pd.DataFrame(
        {
            "  Region ": ["  Region "] + ["REGION"] * 8 + ["east", "west"] * 4,
            "amount": ["amount"] + [str(v) for v in range(16)],
        }
    )

    cleaned, summary = clean(frame)

    assert list(cleaned.columns) == ["  Region ", "amount"], "renamed anyway"
    assert not any(a["disease"] == 18 for a in summary.applied)
    assert cleaned.iloc[0].tolist() == ["REGION", "amount"], "the junk row is here"


# --- 9 (over-correction). a magnitude wearing a rate slash -------------------


def test_number_fix_refuses_a_magnitude_that_wears_a_rate_slash():
    """The item 9 repair let any residue carrying a slash skip the magnitude
    gate entirely, on the reasoning that a rate slash "spells a unit and cannot
    be a magnitude". "4.5M/yr" refutes that in one line: millions per year is
    the ordinary way a finance column writes a run rate, and stripping it
    states 4.5 where the value was 4,500,000 - item 15's exact corruption,
    reopened one character to the right and recorded verified."""
    values = ["4.5M/yr", "3.2M/yr", "1.1M/yr", "8.7M/yr"] * 6

    cleaned, summary = clean(pd.DataFrame({"run_rate": values}))

    assert cleaned["run_rate"].tolist() == values, "the scale was stripped"
    assert not any(a["disease"] == 1 for a in summary.applied)


def test_number_fix_refuses_the_millimetre_million_collision_under_a_slash_too():
    """The "mm" ambiguity does not stop being ambiguous because a slash
    follows it. "1.5 mm/yr" is a millimetres-per-year erosion rate and
    "1.5 MM/yr" is millions per year, and they are the same shape, so the
    refusal has to cover both rather than quietly resolve them to the unit
    reading."""
    values = ["1.5 mm/yr", "2.5 mm/yr", "0.8 mm/yr", "3.1 mm/yr"] * 6

    cleaned, summary = clean(pd.DataFrame({"erosion": values}))

    assert cleaned["erosion"].tolist() == values, "the scale was stripped"
    assert not any(a["disease"] == 1 for a in summary.applied)


def test_number_fix_repairs_a_unit_a_magnitude_can_never_wear():
    """The half of item 9 that IS recoverable, and the reason the gate reads
    more than the first letter run. No magnitude is ever written "1.5M²", so a
    residue carrying a superscript, a degree sign or a per-cent sign is a unit
    however it begins."""
    values = ["12 m²", "3.5 m²", "7 m²", "21 m²"] * 6

    cleaned, summary = clean(pd.DataFrame({"area": values}))

    assert 1 in {a["disease"] for a in summary.applied}, summary.needs_review
    assert cleaned["area"].iloc[0] == 12.0


# --- 10 (over-correction). two outliers against a month-first column ---------


def test_date_fix_refuses_two_day_first_outliers_in_a_month_first_column():
    """_ORDER_SUPPORT went from a fifth of the column to a flat count of two,
    with no relation to column size, so a month-first column whose day slot
    never exceeds 12 plus two stray day-first rows derived %d/%m/%Y and
    transposed every other row silently, with zero NaT to show for it. Two
    typos are not a convention. The column below is the same shape at 200 rows
    that the packet's own test used at 27."""
    values = [f"{m:02d}/{d:02d}/2020" for m in range(1, 13) for d in range(1, 12)]
    values = values[:198] + ["06/25/2020", "07/26/2020"]

    cleaned, summary = clean(pd.DataFrame({"d": values}))

    assert not any(a["disease"] == 2 for a in summary.applied), (
        "a month-first column was transposed on two outliers"
    )
    assert cleaned["d"].tolist() == values


# --- 11 (over-refusal survived). a banner row that merely repeats ------------


def test_header_fix_repairs_padding_over_a_repeated_banner_row():
    """The item 11 repair still refuses when the row's spelling merely occurs
    more than once in its own column, on the theory that only d07 could have
    written it there. A repeated all-caps banner is exactly the spelling d07
    leaves alone, and the d18 finding on this frame reports header_rows 0: no
    row ever equalled the names, so there is no header row for the rename to
    hide from the re-check."""
    frame = pd.DataFrame(
        {
            "amount ": ["AMOUNT"] * 6 + [str(v) for v in range(12)],
            "region": ["REGION"] * 6 + ["east", "west"] * 6,
        }
    )
    finding = next(f for f in detect_all(frame)["findings"] if f["disease"] == 18)
    assert finding["stats"]["header_rows"] == 0, "the premise of this test"

    cleaned, summary = clean(frame)

    assert 18 in {a["disease"] for a in summary.applied}, summary.needs_review
    assert list(cleaned.columns) == ["amount", "region"], "the padding survived"


def test_number_fix_refuses_the_magnitudes_spelled_as_words():
    """The item 15 comment says every spelling is listed on purpose "because
    omitting one by accident is exactly how 1.5MM became 1.5". The word
    spellings were never listed, so "1.5 million" still became 1.5 by exactly
    that accident, under a comment asserting the hole was closed. These carry
    no unit collision at all - nothing is measured in millions - so the
    refusal costs nothing that "mm" costs."""
    for spelling in ("million", "mil", "billion", "thousand", "trillion"):
        values = [f"{n}.5 {spelling}" for n in range(1, 5)] * 6

        cleaned, summary = clean(pd.DataFrame({"revenue": values}))

        assert cleaned["revenue"].tolist() == values, f"{spelling} was stripped"
        assert not any(a["disease"] == 1 for a in summary.applied), spelling


# --- #24. a HUMAN finding that shares a column with an AUTO one --------------


def _state_frame() -> pd.DataFrame:
    """A CRM export's state column: three casings of one state (d07 AUTO) and
    two misspellings a person must map (d07 HUMAN), both on ['state']. The
    zero-padded ids keep every row distinct, so no row disease rides along."""
    states = (
        ["California"] * 5
        + ["california", "CALIFORNIA"]
        + ["Pennsylvania"] * 4
        + ["Pensylvania"]
        + ["Washington"] * 4
        + ["Massachusetts"] * 3
        + ["Massachusets"]
    )
    ids = [f"{n:06d}" for n in range(1041, 1041 + 7 * len(states), 7)]
    return pd.DataFrame({"account_id": ids, "state": states})


def test_a_human_finding_beside_an_auto_one_stays_in_review():
    """Regression for #24. The second loop of clean() deduped review entries
    on (disease, columns) alone, so once the d07 AUTO case finding landed in
    review, the d07 HUMAN spelling finding on the same column matched it and
    was dropped. The spelling variants are still in the cleaned frame; the
    one finding a person had to decide vanished from the summary."""
    frame = _state_frame()
    found = {
        (f["disease"], f["grade"])
        for f in detect_all(frame)["findings"]
        if f["columns"] == ["state"]
    }
    assert {(7, "AUTO"), (7, "HUMAN")} <= found, "the premise of this test"

    _cleaned, summary = clean(frame)

    assert any(
        r["disease"] == 7 and r["grade"] == "HUMAN" for r in summary.needs_review
    ), summary.needs_review


def test_a_human_finding_the_applied_fix_also_cleared_is_not_left_in_review(
    monkeypatch,
):
    """Pin beside #24, the other side of the line. When the fix applied on
    a column also clears a HUMAN finding of the same disease there, the
    re-check finds nothing and review must not carry a finding that is no
    longer true. The stand-in fixer maps every variant onto its canonical
    spelling, which is what a person would have decided."""
    canonical = {
        "california": "California",
        "pennsylvania": "Pennsylvania",
        "pensylvania": "Pennsylvania",
        "washington": "Washington",
        "massachusetts": "Massachusetts",
        "massachusets": "Massachusetts",
    }

    def fold_and_respell(frame, cols):
        out = frame.copy()
        for c in cols:
            out[c] = out[c].str.lower().map(canonical)
        return out

    monkeypatch.setitem(FIXERS, 7, fold_and_respell)

    cleaned, summary = clean(_state_frame())

    assert 7 in {a["disease"] for a in summary.applied}, summary.needs_review
    assert detect_one(cleaned, 7, ["state"]) is None, "the premise of this test"
    assert not _reviewed(summary, 7, ["state"]), summary.needs_review


# --- #25. a residual of a different grade is a different finding ------------


def test_a_case_fix_is_kept_beside_an_open_spelling_variant():
    """Regression for #25. FIXERS[7] folds the three casings of California
    onto one, which is the whole of the d07 AUTO finding. The re-check then
    found the d07 HUMAN spelling finding on the same column, counted it as the
    case finding still firing, and reverted the fold. No fixer may clear a
    spelling judgement, so that refusal could never be satisfied: every case
    fix on a column with a misspelling was lost."""
    frame = _state_frame()

    cleaned, summary = clean(frame)

    applied = {(a["disease"], tuple(a["columns"]), a["grade"]) for a in summary.applied}
    assert (7, ("state",), "AUTO") in applied, summary.needs_review
    # hand-checked: the casings fold onto the majority spelling, and the two
    # misspellings are left exactly as they were for a person to map
    expected = (
        ["California"] * 7
        + ["Pennsylvania"] * 4
        + ["Pensylvania"]
        + ["Washington"] * 4
        + ["Massachusetts"] * 3
        + ["Massachusets"]
    )
    assert cleaned["state"].tolist() == expected, "the fold was not kept as is"
    assert cleaned["account_id"].tolist() == frame["account_id"].tolist()
    assert any(
        r["disease"] == 7 and r["grade"] == "HUMAN" for r in summary.needs_review
    ), summary.needs_review
    assert not any(
        r["disease"] == 7 and r["grade"] == "AUTO" for r in summary.needs_review
    ), summary.needs_review


def test_a_case_fix_that_leaves_a_casing_behind_is_still_refused(monkeypatch):
    """Pin beside #25, the refusal that must survive it. A fold that misses
    one casing leaves the d07 AUTO finding itself still firing, so the residual
    is the same grade as the fix and the fix is reverted, spelling finding or
    not. Only a residual of a different grade stops counting."""

    def fold_only_upper(frame, cols):
        out = frame.copy()
        for c in cols:
            out[c] = out[c].replace({"CALIFORNIA": "California"})
        return out

    monkeypatch.setitem(FIXERS, 7, fold_only_upper)
    frame = _state_frame()

    cleaned, summary = clean(frame)

    assert not any(a["disease"] == 7 for a in summary.applied), summary.applied
    assert cleaned["state"].tolist() == frame["state"].tolist(), "not reverted"
    assert any(
        r["disease"] == 7
        and r["grade"] == "AUTO"
        and r.get("reason") == "fix did not clear verification"
        for r in summary.needs_review
    ), summary.needs_review
    assert any(
        r["disease"] == 7 and r["grade"] == "HUMAN" for r in summary.needs_review
    ), summary.needs_review


def _cased_state_frame() -> pd.DataFrame:
    """The CRM state column with three casings of Pennsylvania (d07 AUTO) and
    every other state spelled right, so before any fix the column carries no
    d07 HUMAN spelling finding at all."""
    states = (
        ["Pennsylvania"] * 5
        + ["pennsylvania", "PENNSYLVANIA"]
        + ["California"] * 4
        + ["Washington"] * 4
        + ["Massachusetts"] * 4
    )
    ids = [f"{n:06d}" for n in range(1041, 1041 + 7 * len(states), 7)]
    return pd.DataFrame({"account_id": ids, "state": states})


def test_a_case_fix_that_creates_a_spelling_variant_is_reverted(monkeypatch):
    """Regression for #25. Counting only a residual of the fix's own grade
    let a fix clear its grade by making a finding of another. The stand-in
    fold maps the two odd casings of Pennsylvania onto a mistyped canonical,
    'Pensylvania': the case finding (AUTO) is gone, and in its place is a
    spelling finding (HUMAN) the column did not carry before the fix. The fix
    damaged the column, so it is reverted like any fix that did not verify.
    The legitimate side of the line, a spelling finding that was already open
    before the fold, is pinned by
    `test_a_case_fix_is_kept_beside_an_open_spelling_variant` and
    `test_a_case_fix_is_kept_when_it_rewords_the_open_spelling_finding`."""

    def fold_onto_a_typo(frame, cols):
        out = frame.copy()
        for c in cols:
            out[c] = out[c].replace(
                {"pennsylvania": "Pensylvania", "PENNSYLVANIA": "Pensylvania"}
            )
        return out

    frame = _cased_state_frame()

    def on_state(f):
        return {
            (x["disease"], x["grade"])
            for x in detect_all(f)["findings"]
            if x["columns"] == ["state"]
        }

    assert on_state(frame) == {(7, "AUTO")}, "the premise of this test"
    assert on_state(fold_onto_a_typo(frame, ["state"])) == {(7, "HUMAN")}, (
        "the premise of this test"
    )
    monkeypatch.setitem(FIXERS, 7, fold_onto_a_typo)

    cleaned, summary = clean(frame)

    assert not any(a["disease"] == 7 for a in summary.applied), (
        "a fix that created a spelling finding was kept",
        summary.applied,
    )
    assert cleaned["state"].tolist() == frame["state"].tolist(), "not reverted"
    assert any(
        r["disease"] == 7 and r["grade"] == "AUTO" and r.get("reason")
        for r in summary.needs_review
    ), summary.needs_review


def test_a_case_fix_is_kept_when_it_rewords_the_open_spelling_finding():
    """Pin beside #25. Here the spelling finding was open before the fold,
    and the fold changes how it reads: one rep typed MASSACHUSETTS in capitals
    on the first row, so before the fix the HUMAN finding quotes that casing
    as its side of the pair, and after it quotes 'Massachusetts'. Same
    disease, same grade, same column, the same finding reworded, not a new
    one, so the correct fold is kept. A refusal keyed on the wording would
    lose it."""
    states = (
        ["MASSACHUSETTS"]
        + ["California"] * 5
        + ["Pennsylvania"] * 4
        + ["Washington"] * 4
        + ["Massachusetts"] * 3
        + ["massachusetts", "Massachusets"]
    )
    ids = [f"{n:06d}" for n in range(1041, 1041 + 7 * len(states), 7)]
    frame = pd.DataFrame({"account_id": ids, "state": states})

    def spelling(f):
        return [
            x
            for x in detect_all(f)["findings"]
            if x["disease"] == 7 and x["grade"] == "HUMAN"
        ]

    before, after = spelling(frame), spelling(FIXERS[7](frame, ["state"]))
    assert len(before) == len(after) == 1, "the premise of this test"
    assert before[0]["evidence"] != after[0]["evidence"], "the premise"

    cleaned, summary = clean(frame)

    applied = {(a["disease"], tuple(a["columns"]), a["grade"]) for a in summary.applied}
    assert (7, ("state",), "AUTO") in applied, summary.needs_review
    # hand-checked: both odd casings fold onto the majority 'Massachusetts';
    # the misspelling on the last row is left for a person to map
    expected = (
        ["Massachusetts"]
        + ["California"] * 5
        + ["Pennsylvania"] * 4
        + ["Washington"] * 4
        + ["Massachusetts"] * 4
        + ["Massachusets"]
    )
    assert cleaned["state"].tolist() == expected, "the fold was not kept as is"
    assert any(
        r["disease"] == 7 and r["grade"] == "HUMAN" for r in summary.needs_review
    ), summary.needs_review


def _resent_orders() -> pd.DataFrame:
    """An orders export of 290 orders with zero-padded ids, ten of them sent
    twice. Five re-sends carry a re-keyed amount ($10 more than the first
    send), and five were keyed by a second rep who typed the region in lower
    case. order_id is 290 of 300 unique, so d11 reads it as a damaged key
    whose repeats contradict both region and amount; the lower-case regions
    are d07's case finding (AUTO) on region as well."""
    regions = ["West", "East", "North", "South", "Central"]
    orders = [
        (
            f"{50113 + 17 * k:06d}",
            regions[k % 5],
            round(40 + (k * 37) % 460 + (k % 4) * 0.25, 2),
        )
        for k in range(290)
    ]
    rekeyed = [
        (oid, region, round(amount + 10.0, 2))
        for oid, region, amount in (orders[k] for k in (12, 71, 130, 188, 247))
    ]
    lowered = [
        (oid, region.lower(), amount)
        for oid, region, amount in (orders[k] for k in (25, 90, 151, 203, 266))
    ]
    return pd.DataFrame(
        orders + rekeyed + lowered, columns=["order_id", "region", "amount"]
    )


def test_a_finding_a_kept_fix_narrows_is_listed_once():
    """Regression for #25. The leftover pass matched each finding on the
    cleaned frame to a review entry by its exact column list. Here the d07
    fold on region is correct and kept, and it settles the five re-sends
    that differed only by case, so the d11 key finding, open before the fixes
    on order_id, region and amount, is left on order_id and amount: the same
    finding about the same key, with one attribute fewer. It matched no entry
    and was listed a second time, so a person read two key findings where
    there is one."""
    frame = _resent_orders()

    def on_key(f):
        return [
            (x["grade"], x["columns"])
            for x in detect_all(f)["findings"]
            if x["disease"] == 11
        ]

    assert on_key(frame) == [("HUMAN", ["order_id", "region", "amount"])], (
        "the premise of this test"
    )

    cleaned, summary = clean(frame)

    applied = {(a["disease"], tuple(a["columns"]), a["grade"]) for a in summary.applied}
    assert (7, ("region",), "AUTO") in applied, summary.needs_review
    # hand-checked: each lower-case region folds onto its capitalised majority
    assert cleaned["region"].tolist() == [r.capitalize() for r in frame["region"]]
    assert on_key(cleaned) == [("HUMAN", ["order_id", "amount"])], (
        "the premise of this test"
    )
    key = [r for r in summary.needs_review if r["disease"] == 11]
    assert len(key) == 1, key
    assert key[0]["grade"] == "HUMAN" and key[0]["columns"][0] == "order_id", key


def _padded_state_header() -> pd.DataFrame:
    """The CRM state frame read from a CSV whose header cell was ' state',
    with a leading space: d18 (AUTO) renames it to 'state'."""
    return _state_frame().rename(columns={"state": " state"})


def _unnamed_state_beside_a_constant() -> pd.DataFrame:
    """The CRM state frame read from a CSV whose state header cell was blank,
    so pandas named the column 'Unnamed: 2', beside a country column that
    reads 'US' on every row. d19 (AUTO) drops country, then d18 renames the
    unnamed column, now at position 1."""
    frame = _state_frame()
    return pd.DataFrame(
        {
            "account_id": frame["account_id"],
            "country": ["US"] * len(frame),
            "Unnamed: 2": frame["state"],
        }
    )


@pytest.mark.parametrize(
    ("build", "fixes"),
    [
        (_padded_state_header, {(7, (" state",)), (18, (" state",))}),
        (
            _unnamed_state_beside_a_constant,
            {(7, ("Unnamed: 2",)), (19, ("country",)), (18, ("Unnamed: 2",))},
        ),
    ],
    ids=["padded-header", "unnamed-header-beside-a-dropped-constant"],
)
def test_a_finding_under_a_repaired_header_is_listed_once(build, fixes):
    """Pin beside #25. The d18 header repair runs after every other fix (and
    after d19's drops), so the d07 spelling finding the review lists under
    the column's old name turns up on the cleaned frame under its new one.
    The leftover pass maps the new name back to the old to match the two;
    without that, the one spelling finding is listed twice. The case fold,
    the drop and the rename are all correct, and all kept."""
    frame = build()

    cleaned, summary = clean(frame)

    applied = {(a["disease"], tuple(a["columns"])) for a in summary.applied}
    assert applied == fixes, summary.needs_review
    # hand-checked: the casings fold onto the majority spelling, the two
    # misspellings are left for a person, and the column ends up last
    expected = (
        ["California"] * 7
        + ["Pennsylvania"] * 4
        + ["Pensylvania"]
        + ["Washington"] * 4
        + ["Massachusetts"] * 3
        + ["Massachusets"]
    )
    assert cleaned.iloc[:, -1].tolist() == expected, "the fold was not kept as is"
    assert cleaned["account_id"].tolist() == frame["account_id"].tolist()
    spelling = [
        r for r in summary.needs_review if r["disease"] == 7 and r["grade"] == "HUMAN"
    ]
    assert len(spelling) == 1, summary.needs_review
    assert not any(
        r["disease"] == 7 and r["grade"] == "AUTO" for r in summary.needs_review
    ), summary.needs_review


def test_a_finding_a_later_fix_brings_back_is_listed_as_still_present(monkeypatch):
    """Regression for #25. The leftover pass gives a finding on the cleaned
    frame one of two reasons: "found once the fixes ran" when no diagnosis
    of the original carried it, and "still present after the fixes ran" when
    one did. Nothing told the two apart, so either reason could stand in for
    the other unseen. The stand-in d01 fixer is the real number fix that then
    re-pads `note` on every third row of the demo frame, as a fix that
    rewrites a whole frame can: d06's whitespace fix on `note` is applied and
    verified first, d01 verifies only `revenue`, and the cleaned frame carries
    the d06 finding the original did. It was open before the fixes, so it is
    left over, not uncovered."""
    number_fix = FIXERS[1]

    def fix_and_repad(frame, cols):
        out = number_fix(frame, cols)
        every_third = out.index % 3 == 0
        out.loc[every_third, "note"] = "  " + out.loc[every_third, "note"] + "  "
        return out

    frame = load_example()
    assert detect_one(frame, 6, ["note"], grade="AUTO") is not None, "the premise"
    monkeypatch.setitem(FIXERS, 1, fix_and_repad)

    cleaned, summary = clean(frame)

    applied = {(a["disease"], tuple(a["columns"]), a["grade"]) for a in summary.applied}
    assert {(6, ("note",), "AUTO"), (1, ("revenue",), "AUTO")} <= applied, (
        "the premise of this test",
        summary.needs_review,
    )
    assert detect_one(cleaned, 6, ["note"], grade="AUTO") is not None, "the premise"
    whitespace = [
        (r["disease"], r["grade"], r["columns"], r.get("reason"))
        for r in summary.needs_review
        if r["disease"] == 6
    ]
    assert whitespace == [(6, "AUTO", ["note"], "still present after the fixes ran")]
    # the padding also makes "review" and "  review  " two spellings of one
    # value, a d07 finding no diagnosis of the original carried
    case = [
        r.get("reason")
        for r in summary.needs_review
        if r["disease"] == 7 and r["columns"] == ["note"]
    ]
    assert case == ["found once the fixes ran"], summary.needs_review


def _excel_damaged_ids() -> pd.DataFrame:
    """A transactions export after a round trip through Excel, the shape of
    the bench case tx-excel-ids: 30 'TX' ids zero-padded to six digits, three
    of them still wearing Excel's leading-apostrophe text guard, and three a
    numeric cast ate (prefix and zeros gone, one rendered in scientific
    notation). Hand-checked against d22: 3 guarded of 30 sits in [2, 15], and
    3 eaten against 27 intact clears max(3, 15), so both signals fire."""
    ids = [f"TX{n:06d}" for n in range(4417, 4417 + 13 * 30, 13)]
    for row in (2, 11, 23):  # 'TX004443, 'TX004560, 'TX004716
        ids[row] = "'" + ids[row]
    ids[5] = "4482"  # was TX004482
    ids[17] = "4638"  # was TX004638
    ids[26] = "4.76E+03"  # was TX004755
    amounts = [round(12.5 + 7.25 * n, 2) for n in range(30)]
    return pd.DataFrame({"txn_id": ids, "amount": amounts})


def test_two_same_grade_findings_on_one_column_both_stay_in_review():
    """Regression for #24. The old review dedupe matched on (disease, columns)
    alone, so of two d22 GATE findings on one id column (the apostrophe guard
    and the eaten ids, two different damages a person fixes differently) the
    second was dropped from needs_review. Matching on (disease, columns,
    grade) would drop it just the same; this guards against a future dedupe
    of that kind. Every d22 finding on the column must reach review, one
    entry for one finding."""
    frame = _excel_damaged_ids()
    d22 = [
        f
        for f in detect_all(frame)["findings"]
        if f["disease"] == 22 and f["columns"] == ["txn_id"]
    ]
    assert [f["grade"] for f in d22] == ["GATE", "GATE"], "the premise of this test"

    _cleaned, summary = clean(frame)

    reviewed = [
        r
        for r in summary.needs_review
        if r["disease"] == 22 and r["columns"] == ["txn_id"]
    ]
    expected = [(22, f["slug"], ["txn_id"], "GATE") for f in d22]
    assert [
        (r["disease"], r["slug"], r["columns"], r["grade"]) for r in reviewed
    ] == expected, summary.needs_review
