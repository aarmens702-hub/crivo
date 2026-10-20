"""Notebook HTML card tests: a self-contained dark diagnosis / clean card that
paints its own colours, never trusts the notebook theme, and escapes every
value that crosses into it (GitHub / nbconvert sanitize aggressively)."""

import re
from html import escape, unescape

import pandas as pd
import pytest
from test_autoclean_regressions import _excel_damaged_ids, _state_frame

from crivo import autoclean, pii
from crivo.detect import SINGLE_FRAME, SLUGS, detect_all
from crivo.notebook import clean_html, report_html


def _diagnosis():
    """A frame that reliably trips AUTO findings: money-as-strings (d01), a
    constant column (d19), and byte-identical repeats (d09)."""
    df = pd.DataFrame(
        {
            "amount": ["$1,200", "$3,400.50", "$15", "$980"] * 5,
            "status": ["OPEN"] * 20,
        }
    )
    return df, detect_all(df, "txns.csv")


def test_report_html_names_the_dataset():
    df, result = _diagnosis()
    card = report_html("txns.csv", df, result)
    assert card.startswith("<div")
    assert "txns.csv" in card


def test_report_html_lists_at_least_one_finding_slug():
    df, result = _diagnosis()
    card = report_html("txns.csv", df, result)
    slugs = {f["slug"] for f in result["findings"]}
    assert slugs, "fixture should trip at least one finding"
    assert any(slug in card for slug in slugs)


def test_report_html_carries_the_absence_footer():
    df, result = _diagnosis()
    card = report_html("txns.csv", df, result)
    assert "absence is a checked claim, not a silence" in card
    assert f"{len(SINGLE_FRAME)} signals run on every file" in card


def test_report_html_is_sanitizer_safe_and_escapes_user_data():
    """No <script>, no external URL, and user-controlled text (here the name)
    is escaped — the card must survive GitHub/nbconvert sanitizers and never
    inject markup a value carried in."""
    df, result = _diagnosis()
    card = report_html("<b>evil</b>.csv", df, result)
    assert "<script" not in card
    assert "http" not in card
    assert "&lt;b&gt;evil&lt;/b&gt;" in card
    assert "<b>evil</b>" not in card


def test_report_html_paints_its_own_background_inline():
    """The card carries its own dark ground so it reads the same on a light or
    dark notebook — the token is set inline, not left to inherit."""
    df, result = _diagnosis()
    card = report_html("txns.csv", df, result)
    assert "background:#14171a" in card


def test_report_html_single_escapes_special_char_column_names():
    """A column named with '&' must escape exactly once — '&amp;', never the
    double-escaped '&amp;amp;'. _cols_label already escapes each name, so the
    call sites must not escape the joined label again."""
    df = pd.DataFrame({"Q&A": ["$1,200", "$3,400.50", "$15", "$980"] * 5})

    card = report_html("t.csv", df, detect_all(df, "t.csv"))

    assert "Q&amp;A" in card
    assert "Q&amp;amp;A" not in card


def test_finding_escapes_an_unexpected_grade_value():
    """Defensive: grade is always AUTO/GATE/HUMAN in practice, but the renderer's
    contract is that NO interpolated value reaches the card unescaped."""
    from crivo.notebook import _finding

    f = {
        "disease": 1,
        "slug": "x",
        "columns": ["c"],
        "evidence": "e",
        "grade": "<b>x</b>",
        "confidence": 1.0,
        "indicator": False,
    }

    html = _finding(f)

    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def _contacts_diagnosis():
    """A contacts export whose findings quote PII cells: emails and phones
    padded with stray spaces (d06 on both) and a plan column with an 'N/A'
    token (d04, not PII)."""
    df = pd.DataFrame(
        {
            "email": [
                f" ana.{i}@example.com  " if i % 4 == 1 else f"ana.{i}@example.com"
                for i in range(20)
            ],
            "phone": [
                f"  555-010-{2000 + i}" if i % 5 == 0 else f"(555) 010-{2000 + i}"
                for i in range(20)
            ],
            "plan": ["basic", "N/A", "pro", "team"] * 5,
        }
    )
    return df, detect_all(df, "contacts.csv")


def test_report_html_masks_evidence_from_pii_flagged_columns():
    """Regression for #18. The notebook card rendered finding evidence raw, so
    padded emails and phones quoted by whitespace-damage reached the card.
    Evidence from a PII-flagged column is masked; the finding and non-PII
    evidence stay as they were."""
    df, result = _contacts_diagnosis()
    fired = {(f["slug"], tuple(f["columns"])) for f in result["findings"]}
    assert (SLUGS[6], ("email",)) in fired
    assert (SLUGS[6], ("phone",)) in fired

    card = report_html("contacts.csv", df, result)

    raw = {cell.strip() for column in ("email", "phone") for cell in df[column]}
    leaked = sum(1 for cell in raw if cell in card)
    assert leaked == 0  # a count, so the failure message carries no cell
    assert SLUGS[6] in card
    assert escape("'***@example.com'") in card  # masked, not dropped
    assert escape("('N/A')") in card  # non-PII evidence is untouched


def _clean_summary():
    """A summary with at least one applied fix that changed cells (d01 money)."""
    from crivo.autoclean import clean

    df = pd.DataFrame(
        {
            "amount": ["$1,200", "$3,400.50", "$15", "$980"] * 5,
            "const": ["x"] * 20,
        }
    )
    _cleaned, summary = clean(df)
    return summary


def test_clean_html_shows_an_applied_fix_and_a_before_after_example():
    from crivo.notebook import clean_html

    card = clean_html(_clean_summary())
    assert card.startswith("<div")
    assert "✓" in card, "an applied fix should be marked done"
    assert "→" in card, "a before/after example should render"


# --- #19: the clean card masks PII-flagged values and clips every value -----

MONEY = ["$1,200", "$3,400.50", "$15", "$980"] * 5  # d01, not PII


def _padded_emails(n=20):
    """A CRM export's email column, every fourth address padded (d06)."""
    return [
        f" jane.doe{i}@example.com  " if i % 4 == 1 else f"jane.doe{i}@example.com"
        for i in range(n)
    ]


def _mixed_phones(n=20):
    """Phones in two formats, every fifth one padded (d06)."""
    return [
        f"  555-010-{2000 + i}" if i % 5 == 0 else f"(555) 010-{2000 + i}"
        for i in range(n)
    ]


def _leaked(rendered, cells) -> int:
    """How many distinct raw cells appear in `rendered`, raw or escaped. A
    count, so a failing assertion message carries no cell."""
    raw = {str(cell).strip() for cell in cells}
    return sum(1 for cell in raw if cell in rendered or escape(cell) in rendered)


def _card_or_error(summary) -> str:
    """The clean card, or the exception it raised as text, so a crash fails on
    the test's assertion instead of erroring out of the test."""
    try:
        return clean_html(summary)
    except Exception as exc:  # noqa: BLE001 - the crash is what is under test
        return f"clean_html raised {type(exc).__name__}: {exc}"


@pytest.mark.parametrize(
    "column, cells, disease, masked",
    [
        pytest.param("email", _padded_emails(), 6, "***@example.com", id="d06-email"),
        pytest.param("phone", _mixed_phones(), 6, pii.REDACTED, id="d06-phone"),
        pytest.param(
            "owner_email",
            ["acct.owner@example.com"] * 20,
            19,
            "***@example.com",
            id="d19-constant-email",
        ),
    ],
)
def test_clean_html_masks_values_from_pii_flagged_columns(
    column, cells, disease, masked
):
    """Regression for #19. The clean card printed each applied fix's examples
    raw, so a padded email trimmed by d06, or the constant a d19 drop removed,
    reached a card a person forwards. Values from a PII-flagged column show
    masked; the money column beside it keeps its real values."""
    df = pd.DataFrame({column: cells, "amount": MONEY})
    _cleaned, summary = autoclean.clean(df)
    fixed = {(a["disease"], tuple(a["columns"])) for a in summary.applied}
    assert (disease, (column,)) in fixed  # the premise: the fix ran
    assert column in pii.flagged_columns(df)  # and the column is flagged

    card = summary._repr_html_()

    leaked = _leaked(card, cells)  # a count, never the cells, in a failure
    assert leaked == 0
    assert masked in card  # masked, not dropped
    assert "✓" in card
    assert escape("'$1,200'") in card  # a non-PII example keeps its value


def test_clean_html_caps_each_example():
    """Regression for #19. `_applied_row` rendered `old` and `new` with no
    length cap, so a 1,400-character note printed whole, twice. Each shown
    value is clipped to the 40-character limit `detect._samples` uses."""
    notes = ["called back", "left voicemail", "no answer", "sent quote"] * 5
    notes[3] = "  " + "SECRET-" * 200 + "  "
    df = pd.DataFrame({"notes": notes, "amount": MONEY})
    _cleaned, summary = autoclean.clean(df)
    assert (6, ("notes",)) in {
        (a["disease"], tuple(a["columns"])) for a in summary.applied
    }

    card = clean_html(summary)

    shown = card.count("SECRET-")
    assert shown > 0  # clipped, not dropped
    assert shown <= 12


def test_clean_html_renders_a_header_rename():
    """Regression for #19. A d18 header repair's examples are
    `{column, renamed, new}` with no `old`, so the clean card raised
    KeyError on every header repair. It renders the rename instead."""
    df = pd.DataFrame(
        {
            "Unnamed: 0": range(20),  # a pandas index written back out to csv
            "name ": [f"Customer {i}" for i in range(20)],
            "z": [round(0.25 * i, 2) for i in range(20)],
        }
    )
    _cleaned, summary = autoclean.clean(df)
    assert 18 in {a["disease"] for a in summary.applied}

    card = _card_or_error(summary)

    assert "column_0" in card


def test_clean_html_shows_a_renamed_header_unmasked_on_a_pii_flagged_column():
    """Regression for #19. A header name is schema, not a cell value: a d18
    rename of a PII-flagged column shows its names as they are, not masked to
    REDACTED by the masking that hides the column's cells."""
    df = pd.DataFrame(
        {
            "Unnamed: 0": range(20),
            "email ": [f"jane.doe{i}@example.com" for i in range(20)],
            "plan": ["basic", "pro", "team", "free"] * 5,
        }
    )
    _cleaned, summary = autoclean.clean(df)
    assert 18 in {a["disease"] for a in summary.applied}
    assert "email " in pii.flagged_columns(df)  # the premise: the column is flagged

    card = _card_or_error(summary)

    assert "column_0" in card
    assert pii.REDACTED not in card


SURVEY_QUESTION = (
    "How satisfied were you with the onboarding process, on a scale of 1 to 10?"
)


def test_clean_html_clips_a_long_header_name_in_a_rename():
    """Regression for #19. Survey exports carry whole questions as headers,
    often with trailing spaces. The d18 rename row clips each name to the
    40-character limit rather than printing the question whole on both sides
    of the arrow."""
    df = pd.DataFrame(
        {
            SURVEY_QUESTION + "   ": [i % 10 + 1 for i in range(20)],
            "respondent_id": [f"R{i:04d}" for i in range(20)],
        }
    )
    _cleaned, summary = autoclean.clean(df)
    assert 18 in {a["disease"] for a in summary.applied}

    card = _card_or_error(summary)

    # the fix's column label, then both sides of the rename, each clipped
    assert card.count(escape(SURVEY_QUESTION[:30])) >= 3
    # only the column label may carry the whole question
    assert card.count(escape(SURVEY_QUESTION)) <= 1


def _fixer_raising(message):
    """A fixer that fails the way pandas does, quoting the cell it choked on."""

    def fixer(frame, cols, **_extra):
        raise ValueError(message)

    return fixer


@pytest.mark.parametrize(
    "template",
    [
        pytest.param("could not convert string to float: {cell!r}", id="pandas"),
        # a quote right after a word is an apostrophe, never a literal's start
        pytest.param("Excel's text import padded {cell!r}", id="apostrophe"),
    ],
)
def test_clean_html_masks_a_deferred_reason_quoting_a_pii_value(monkeypatch, template):
    """Regression for #19. A review entry's `reason` ("fixer error: ...")
    can quote the cell the fixer failed on, and the card printed it raw. The
    reason goes through `pii.redact_text` before escaping; a reason on a
    non-PII column keeps its literal."""
    emails = _padded_emails()
    message = template.format(cell=emails[1])
    monkeypatch.setitem(autoclean.FIXERS, 6, _fixer_raising(message))
    monkeypatch.setitem(
        autoclean.FIXERS,
        1,
        _fixer_raising("could not convert string to float: '$1,200'"),
    )
    df = pd.DataFrame({"email": emails, "amount": MONEY})
    _cleaned, summary = autoclean.clean(df)
    reasons = {
        (r["disease"], tuple(r["columns"])): r.get("reason", "")
        for r in summary.needs_review
    }
    assert reasons[(6, ("email",))].startswith("fixer error:")  # the premise

    card = clean_html(summary)

    leaked = _leaked(card, emails)
    assert leaked == 0
    assert escape("'***@example.com'") in card  # masked, quotes kept
    assert escape(template.split("{cell!r}")[0]) in card  # the prose is kept
    assert escape("could not convert string to float: '$1,200'") in card


def test_clean_summary_repr_masks_a_deferred_reason_quoting_a_pii_value(monkeypatch):
    """Regression for #19. `repr(summary)` (what `print` shows) prints each
    review entry's reason too, so a fixer error quoting a PII cell is masked
    there as on the card; a non-PII literal stays."""
    emails = _padded_emails()
    message = f"could not convert string to float: {emails[1]!r}"
    monkeypatch.setitem(autoclean.FIXERS, 6, _fixer_raising(message))
    monkeypatch.setitem(
        autoclean.FIXERS,
        1,
        _fixer_raising("could not convert string to float: '$1,200'"),
    )
    df = pd.DataFrame({"email": emails, "amount": MONEY})
    _cleaned, summary = autoclean.clean(df)

    text = repr(summary)

    leaked = _leaked(text, emails)
    assert leaked == 0
    assert "'***@example.com'" in text
    assert SLUGS[6] in text
    assert "could not convert string to float: '$1,200'" in text


# --- #47: two review entries that share a disease and column read apart -----


def _card_rows(card) -> list[str]:
    """The visible text of each row of a clean card, one per <div> (the card
    nests none inside its wrapper), entities decoded and whitespace (&nbsp;
    included) collapsed, so a row reads as the line a person sees."""
    rows = (re.sub(r"<[^>]+>", "", chunk) for chunk in re.split(r"<div[^>]*>", card))
    return [text for text in (" ".join(unescape(r).split()) for r in rows) if text]


def _lines(summary, surface) -> list[str]:
    """Every row a person reads on `surface`: the lines `print(summary)`
    shows, or the clean card's rows, whitespace collapsed alike."""
    if surface == "repr":
        return [" ".join(line.split()) for line in repr(summary).splitlines()]
    return _card_rows(_card_or_error(summary))


def _review_lines(summary, surface) -> list[str]:
    return [line for line in _lines(summary, surface) if line.startswith("· ")]


def _review_entry(disease, column, grade, **extra) -> dict:
    return {
        "disease": disease,
        "slug": SLUGS[disease],
        "columns": [column],
        "grade": grade,
        **extra,
    }


SURFACES = [pytest.param("repr", id="repr"), pytest.param("card", id="card")]


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize(
    "frame, entries, marks",
    [
        pytest.param(
            _state_frame,
            [_review_entry(7, "state", "AUTO"), _review_entry(7, "state", "HUMAN")],
            [["[state] AUTO"], ["[state] HUMAN"]],
            id="d07-auto-beside-human",
        ),
        pytest.param(
            _excel_damaged_ids,
            [
                _review_entry(22, "txn_id", "GATE", kind="guarded"),
                _review_entry(22, "txn_id", "GATE", kind="eaten"),
            ],
            [["[txn_id] GATE", "guarded"], ["[txn_id] GATE", "eaten"]],
            id="d22-guarded-beside-eaten",
        ),
    ],
)
def test_review_entries_sharing_a_disease_and_column_render_apart(
    surface, frame, entries, marks
):
    """Regression for #47. After #24 there is one review entry per finding,
    so a d07 AUTO beside a d07 HUMAN, or a d22 guarded beside a d22 eaten on
    one id column, printed the same line twice on both surfaces. Each review
    line now names the bare grade after its column bracket, and a d22 line
    its kind as well."""
    df = frame()
    summary = autoclean.CleanSummary(df, df, [], entries)

    lines = _review_lines(summary, surface)

    assert len(lines) == 2, lines
    assert lines[0] != lines[1], lines
    for line, wanted in zip(lines, marks):
        assert all(mark in line for mark in wanted), (wanted, line)


def _fold_only_upper(frame, cols):
    """A case fold that misses a casing, so its d07 AUTO finding still fires
    and the fold is reverted into review beside the d07 HUMAN spelling one."""
    out = frame.copy()
    for c in cols:
        out[c] = out[c].replace({"CALIFORNIA": "California"})
    return out


@pytest.mark.parametrize("surface", SURFACES)
def test_a_refused_case_fold_and_the_spelling_finding_name_their_grades(
    monkeypatch, surface
):
    """Regression for #47, on the path clean() takes. The refused d07 case
    fold (AUTO, with the refusal's reason) and the d07 spelling finding
    (HUMAN) sit in review on one column; each line names its grade, ahead of
    the reason."""
    monkeypatch.setitem(autoclean.FIXERS, 7, _fold_only_upper)
    _cleaned, summary = autoclean.clean(_state_frame())
    case = [r for r in summary.needs_review if r["disease"] == 7]
    assert [r["grade"] for r in case] == ["AUTO", "HUMAN"], "the premise"

    lines = [line for line in _review_lines(summary, surface) if " d07 " in line]

    assert lines == [
        f"· d07 {SLUGS[7]} [state] AUTO — fix did not clear verification",
        f"· d07 {SLUGS[7]} [state] HUMAN",
    ], lines


@pytest.mark.parametrize("surface", SURFACES)
def test_an_applied_line_is_unchanged_beside_a_graded_review_line(surface):
    """Regression for #47, and its pin. The grade goes on review lines only:
    the d07 case fold clean() applies to the state column still reads as it
    did, and the spelling finding it leaves reads with its grade."""
    _cleaned, summary = autoclean.clean(_state_frame())
    assert [a["disease"] for a in summary.applied] == [7], "the premise"

    # the head of each fix, never its before/after examples, which quote cells
    heads = [line for line in _lines(summary, surface) if line[:2] in ("✓ ", "· ")]

    assert heads == [
        f"✓ d07 {SLUGS[7]} [state]",
        f"· d07 {SLUGS[7]} [state] HUMAN",
    ], heads


@pytest.mark.parametrize("surface", SURFACES)
def test_two_d22_findings_on_one_id_column_render_their_kinds(surface):
    """Regression for #47. The Excel-damaged id column carries two d22 GATE
    findings, the apostrophe guard and the ids a numeric cast ate, which a
    person fixes differently. Their review lines differ by kind; neither
    surface quotes an id."""
    frame = _excel_damaged_ids()
    _cleaned, summary = autoclean.clean(frame)

    rendered = repr(summary) if surface == "repr" else _card_or_error(summary)
    lines = [line for line in _review_lines(summary, surface) if " d22 " in line]

    # a count first, so no later failure message can carry an id
    leaked = _leaked(rendered, frame["txn_id"])
    assert leaked == 0
    assert len(lines) == 2, lines
    assert all("[txn_id] GATE" in line for line in lines), lines
    assert ["guarded" in line for line in lines] == [True, False], lines
    assert ["eaten" in line for line in lines] == [False, True], lines
