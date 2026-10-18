"""The PII section of the shareable HTML report (B0.1).

`Report.to_html` puts this block above the notebook card. It lists each column
the keyless PII scan flagged (email, phone, SSN, card) with its type, count
and a masked sample; values from those columns are masked everywhere in the
report. Names and street addresses are not detected. Every style is inline and
every dynamic value is HTML-escaped. Pure, no new dependency.
"""

from __future__ import annotations

from html import escape

import pandas as pd

from crivo import pii

_FONT = "font:14px system-ui,sans-serif"
_BANNER = (
    f"{_FONT};color:#1d3a3e;background:#fbece9;border:1px solid #a84b3a;"
    "border-radius:8px;padding:12px 16px;margin:12px 0"
)
_TABLE = f"{_FONT};color:#1d3a3e;border-collapse:collapse;width:100%;font-size:13px"
_CELL = "text-align:left;padding:7px 10px;border-bottom:1px solid #e2edeb"
_HEAD = f"{_CELL};font-size:11px;letter-spacing:.06em;color:#7b9296"


def pii_section_html(df: pd.DataFrame, hits: list[dict] | None = None) -> str:
    """The PII block as standalone HTML: masked samples only. `hits` is a
    precomputed `pii.scan(df)` so a caller scans once; it is scanned here only
    when `None`."""
    if hits is None:
        hits = pii.scan(df)
    if not hits:
        return f'<p style="{_FONT};color:#48666a">PII scan: none detected.</p>'
    head = "".join(
        f'<th style="{_HEAD}">{label}</th>'
        for label in ("column", "type", "count", "masked sample")
    )
    rows = "".join(
        "<tr>"
        f'<td style="{_CELL}">{escape(str(h["column"]))}</td>'
        f'<td style="{_CELL}">{escape(h["pii_type"])}</td>'
        f'<td style="{_CELL}">{h["count"]}</td>'
        f'<td style="{_CELL}">{escape(h["sample"])}</td>'
        "</tr>"
        for h in hits
    )
    return (
        f'<div style="{_BANNER}"><b>PII detected, review before sharing.</b>'
        " Values from these columns are masked everywhere in this report."
        " Names and street addresses are not detected.</div>"
        f'<table style="{_TABLE}"><tr>{head}</tr>{rows}</table>'
    )
