"""The PII section of the shareable report (B0.1): `pii_section_html` is the
block `Report.to_html` puts above the card. It shows masked samples only, and
every column label that reaches it is HTML-escaped, whatever its type."""

import io
import re
from html import escape

import pandas as pd
import pytest

import crivo
from crivo import htmlreport, pii


def _headerless_export(n=12):
    """A CSV export with no header row, read the way pandas reads one
    (`header=None`): the columns are labelled 0, 1, 2, and column 0 holds
    the emails."""
    lines = [
        f"user{i}@example.com,{i:05d},{'N/A' if i % 4 == 0 else 10 * i}"
        for i in range(n)
    ]
    return pd.read_csv(
        io.StringIO("\n".join(lines)),
        header=None,
        dtype={1: str},
        keep_default_na=False,
    )


def test_pii_section_handles_an_integer_column_label(tmp_path):
    """Regression for #18. A headerless file gives integer column labels, and
    the section escaped the label as if it were a string, so it crashed with
    AttributeError and took `Report.to_html` down with it."""
    df = _headerless_export()
    assert [h["column"] for h in pii.scan(df)] == [0]

    try:
        section = htmlreport.pii_section_html(df)
    except (AttributeError, TypeError) as exc:
        pytest.fail(f"pii_section_html crashed on an integer label: {exc!r}")
    try:
        out = crivo.diagnose(df, name="export.csv").to_html(tmp_path / "r.html")
    except (AttributeError, TypeError) as exc:
        pytest.fail(f"to_html crashed on an integer label: {exc!r}")

    assert re.search(r">\s*0\s*</", section)  # the label is shown as a cell
    assert "***@example.com" in section  # the masked sample still shows
    assert "user1@example.com" not in out.read_text()


@pytest.mark.parametrize(
    "column",
    [
        "<b>x</b>",
        '"><img src=x onerror=alert(1)>',
        "Q&A contact",
    ],
)
def test_pii_section_escapes_a_hostile_column_name(column):
    """Regression for #18. `Report.to_html` now scans once and hands the hits
    to `pii_section_html`; on that path every column label must still be
    escaped exactly once, so a column name can never inject markup."""
    df = pd.DataFrame({column: ["ana@example.com", "bo@example.org", "cy@x.io"]})
    hits = pii.scan(df)
    assert [h["column"] for h in hits] == [column]

    try:
        section = htmlreport.pii_section_html(df, hits=hits)
    except TypeError as exc:
        pytest.fail(f"pii_section_html does not take precomputed hits: {exc!r}")

    assert column not in section
    assert escape(column) in section
    assert escape(escape(column)) not in section  # escaped once, not twice
