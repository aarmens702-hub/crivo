"""Notebook HTML card tests: a self-contained dark diagnosis / clean card that
paints its own colours, never trusts the notebook theme, and escapes every
value that crosses into it (GitHub / nbconvert sanitize aggressively)."""

from html import escape

import pandas as pd

from crivo.detect import SINGLE_FRAME, SLUGS, detect_all
from crivo.notebook import report_html


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
