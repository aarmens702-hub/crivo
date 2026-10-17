"""Report.to_html — the shareable single-file report (arc spec R3): the
notebook card as one standalone, self-contained HTML document an analyst can
send to someone who will never install anything."""

import re
from html import escape

import pandas as pd

import crivo
from crivo.detect import SLUGS


def test_to_html_writes_one_self_contained_document(tmp_path):
    report = crivo.diagnose(crivo.load_example(), name="example")
    assert report.findings, "the example frame must trip the detector"

    out = report.to_html(tmp_path / "nested" / "quality.html")
    assert out == tmp_path / "nested" / "quality.html"
    text = out.read_text()

    assert text.lower().startswith("<!doctype html")
    assert "example" in text
    assert "sentinel" in text  # a planted finding made it into the document
    assert "<script" not in text.lower()
    assert "http://" not in text and "https://" not in text  # no external assets


def _contacts(n=24):
    """A CRM contacts export: zero-padded ids, emails padded with stray
    spaces, phones in three formats with some padded, a shared main line that
    is the same number in every row, and a plan column with an 'N/A' token.
    It fires whitespace-damage (d06) on email and phone, empty-constant-columns
    (d19) on main_line and sentinel-missing (d04) on plan; every evidence line
    quotes cells."""
    formats = ["({a}) {b}-{c}", "{a}-{b}-{c}", "{a}.{b}.{c}"]

    def phone(i):
        cell = formats[i % 3].format(a="555", b="123", c=1000 + i)
        return f" {cell}  " if i % 4 == 1 else cell

    return pd.DataFrame(
        {
            "customer_id": [f"{i:05d}" for i in range(1, n + 1)],
            "email": [
                f"  user{i}@example.com  " if i % 3 == 2 else f"user{i}@example.com"
                for i in range(n)
            ],
            "phone": [phone(i) for i in range(n)],
            "main_line": ["(555) 123-1003"] * n,
            "plan": ["basic", "pro", "N/A", "team"] * (n // 4),
        }
    )


def test_to_html_carries_no_raw_value_from_a_pii_flagged_column(tmp_path):
    """Regression for #18. Finding evidence quoted padded emails and phones
    into the card, so the shareable report carried them raw even though the
    PII section above it was masked. Every evidence line must be masked for a
    PII-flagged column, and the findings and the non-PII evidence must stay."""
    df = _contacts()
    report = crivo.diagnose(df, name="contacts.csv")
    fired = {(f["slug"], tuple(f["columns"])) for f in report.findings}
    assert (SLUGS[6], ("email",)) in fired
    assert (SLUGS[6], ("phone",)) in fired
    assert (SLUGS[19], ("main_line",)) in fired
    assert {h["column"] for h in report.pii()} == {"email", "phone", "main_line"}

    text = report.to_html(tmp_path / "r.html").read_text()

    raw = {
        cell.strip()
        for column in ("email", "phone", "main_line")
        for cell in df[column]
    }
    leaked = sum(1 for cell in raw if cell in text)
    assert leaked == 0  # a count, so the failure message carries no cell
    assert SLUGS[6] in text and SLUGS[19] in text  # the findings still show
    assert escape("'***@example.com'") in text  # email evidence keeps its shape
    assert escape("'[REDACTED]'") in text  # phone evidence is masked, not dropped
    assert escape("('N/A')") in text  # non-PII evidence is not over-masked


def test_to_html_escapes_the_report_name_in_the_title(tmp_path):
    """Regression for #18. The <title> took the report name unescaped, so a
    hostile name closed the title and landed a live script in a document that
    promises no scripts."""
    name = "q</title><script>alert(1)</script>"
    report = crivo.diagnose(crivo.load_example(), name=name)

    text = report.to_html(tmp_path / "r.html").read_text()

    assert "<script" not in text.lower()
    assert text.count("</title>") == 1
    title = re.search(r"<title>(.*?)</title>", text, re.DOTALL).group(1)
    assert escape(name) in title  # the name is still shown, escaped
