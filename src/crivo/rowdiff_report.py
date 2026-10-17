"""Keyed row reconciliation report (P7 harder-data, design spec decision 3,
the fast-follow render).

The HTML twin of `reconcile`, the way `compare_report` is the HTML twin of the
shape diff. `reconcile` sorts two frames' rows onto a key into added, removed,
changed, and unchanged and rides a receipt; this renders that result
as one self-contained HTML file a person can open with no server: inline styles,
no external resource, no script. It reuses `compare_report`'s stylesheet and its
before-to-after and column-list helpers, so the two reports read as one family
rather than inventing a second look.

Evidence stays bounded. The added, removed, and changed tables render only the
capped example lists `reconcile` already carries, never a full row dump, and the
exact bucket counts, the receipt, and every truncation or exclusion
note sit beside them. Every dynamic value (a key cell, a column name, a changed
value) is HTML-escaped so a hostile label cannot inject markup. A key cell or a
changed value from a column the PII scan flags in either frame is masked before
it is rendered; the counts, the receipt and the notes are unchanged. Keyless and
pure: pandas plus the standard library, no new dependency, no network, no key.
"""

from __future__ import annotations

from html import escape

import pandas as pd

from crivo import pii
from crivo.compare_report import _STYLE, _cols_html, _pair
from crivo.rowdiff import reconcile

# the four buckets that partition the matchable key space, with the color class
# reused from compare_report so added reads green and removed reads red here too
_BUCKETS = (
    ("added", "add"),
    ("removed", "rem"),
    ("changed", ""),
    ("unchanged", "flat"),
)


def _fmt_key(key: tuple, key_types: list) -> str:
    """A key tuple as one escaped, human-readable cell: the values joined in
    `keys` order, so a single-column key reads as its bare value and a composite
    key as "west, B". A null cell already shows as None from reconcile. A cell
    whose key column is PII-flagged (key_types[i] set) is masked as that type."""
    cells = [
        pii.mask_cell(cell, kind) if kind else str(cell)
        for cell, kind in zip(key, key_types)
    ]
    return escape(", ".join(cells))


def _counts_table(counts: dict) -> str:
    head = "".join(f"<th>{name}</th>" for name, _ in _BUCKETS)
    body = "".join(
        f'<td class="delta {cls}">{counts[name]:,}</td>' for name, cls in _BUCKETS
    )
    return f"<table><tr>{head}</tr><tr>{body}</tr></table>"


def _notes_list(notes: list[str]) -> str:
    if not notes:
        return '<p class="none">No notes.</p>'
    items = "".join(f"<li>{escape(note)}</li>" for note in notes)
    return f"<ul>{items}</ul>"


def _keys_list(keys: list[tuple], key_types: list, cls: str, empty_msg: str) -> str:
    """A bounded list of key tuples (added or removed), mirroring the column
    list in compare_report but formatting each key as a tuple."""
    if not keys:
        return f'<p class="none">{empty_msg}</p>'
    items = "".join(
        f'<li class="{cls}"><code>{_fmt_key(k, key_types)}</code></li>' for k in keys
    )
    return f"<ul>{items}</ul>"


def _changed_table(changed: list[dict], key_types: list, flagged: dict) -> str:
    """One row per differing column within each changed entry: the row key, the
    column, and its before-to-after. Both the changed entries and the columns
    inside them are already capped by reconcile, so this is evidence, not a
    dump. A value in a PII-flagged column is masked on both sides."""
    if not changed:
        return '<p class="none">No changed rows.</p>'
    rows = []
    for entry in changed:
        key_html = _fmt_key(entry["key"], key_types)
        before = entry["before"]
        after = entry["after"]
        for col in entry["columns"]:
            old, new = before[col], after[col]
            kind = flagged.get(str(col))
            if kind:
                old, new = pii.mask_cell(old, kind), pii.mask_cell(new, kind)
            rows.append(
                "<tr>"
                f"<td><code>{key_html}</code></td>"
                f"<td><code>{escape(str(col))}</code></td>"
                f"<td>{_pair(old, new)}</td>"
                "</tr>"
            )
    header = "<tr><th>key</th><th>column</th><th>before &rarr; after</th></tr>"
    return f"<table>{header}{''.join(rows)}</table>"


def reconcile_report(a: pd.DataFrame, b: pd.DataFrame, keys: str | list[str]) -> str:
    """Reconcile two frames on a key and render the result as one self-contained
    HTML document (P7 design spec decision 3, fast-follow).

    `a` is the before frame, `b` the after frame, and `keys` the key column(s).
    Computes reconcile(a, b, keys) then renders the four bucket counts, the
    receipt, the exclusion and truncation notes, the column diff, and
    bounded added / removed / changed tables. Inline styles only, no external
    resource, no script; every dynamic value is HTML-escaped, and a key cell or
    value from a column the PII scan flags in either frame is masked.
    """
    result = reconcile(a, b, keys)
    counts = result["counts"]
    column_diff = result["column_diff"]
    flagged = pii.flagged_columns(a, b)
    key_types = [flagged.get(str(k)) for k in result["keys"]]

    key_label = ", ".join(f"<code>{escape(str(k))}</code>" for k in result["keys"])
    receipt_badge = (
        '<span class="add">verified</span>'
        if result["receipt"]
        else '<span class="rem">NOT verified</span>'
    )

    return (
        "<!doctype html>\n<html><head><meta charset='utf-8'>"
        f"<style>{_STYLE}</style></head><body><div class='wrap'>"
        "<h1>Row reconciliation</h1>"
        f"<p class='sub'>keyed on {key_label}</p>"
        "<h2>Buckets</h2>"
        + _counts_table(counts)
        + f"<p class='sub'>receipt: {receipt_badge}</p>"
        + "<h2>Notes</h2>"
        + _notes_list(result["notes"])
        + "<h2>Columns compared</h2>"
        + _cols_html(column_diff["compared"], "", "No shared non-key columns.")
        + "<h2>Columns only in before</h2>"
        + _cols_html(column_diff["only_in_a"], "rem", "None.")
        + "<h2>Columns only in after</h2>"
        + _cols_html(column_diff["only_in_b"], "add", "None.")
        + "<h2>Added (keys only in after)</h2>"
        + _keys_list(result["added"], key_types, "add", "No added rows.")
        + "<h2>Removed (keys only in before)</h2>"
        + _keys_list(result["removed"], key_types, "rem", "No removed rows.")
        + "<h2>Changed</h2>"
        + _changed_table(result["changed"], key_types, flagged)
        + "</div></body></html>\n"
    )
