"""Tests for the P0 dataset profiler: schema + stats + samples, never raw dumps."""

import io
import re

import pandas as pd
import pytest

from crivo import pii
from crivo.profile import profile_df

OMITTED_RE = re.compile(r"… (\d+) columns omitted \(char budget\)")
CELLS = ("column", "dtype", "non_null", "nunique", "samples", "stats")


def _line_for(out: str, column: str) -> str:
    """Return the profile table row for a column name."""
    return next(line for line in out.splitlines() if line.startswith(f"| {column} |"))


def _cells(out: str, column: str) -> dict[str, str]:
    """The profile row for a column, split into its named cells."""
    parts = _line_for(out, column)[2:-2].split(" | ")
    assert len(parts) == len(CELLS), "a cell grew an unescaped pipe"
    return dict(zip(CELLS, parts, strict=True))


def test_header_has_name_shape_and_memory() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    out = profile_df(df, "taxes")
    assert "taxes" in out
    assert "3 rows × 2 cols" in out
    assert re.search(r"\d+\.\d MB", out)


def test_every_column_name_appears() -> None:
    df = pd.DataFrame({"alpha": [1], "beta": [2.5], "gamma": ["g"]})
    out = profile_df(df, "small")
    for col in ("alpha", "beta", "gamma"):
        assert col in out
    for dtype in ("int64", "float64", "str"):
        assert dtype in out


def test_non_null_pct() -> None:
    df = pd.DataFrame({"v": [1.0, None, 3.0, None, 5.0]})
    assert "60.0%" in _line_for(profile_df(df, "d"), "v")


def test_sample_values_truncated_to_80_chars() -> None:
    df = pd.DataFrame({"long": ["x" * 500, "short"]})
    out = profile_df(df, "d")
    assert "x" * 500 not in out
    runs = [len(m) for m in re.findall(r"x+", out)]
    assert max(runs) <= 80  # each sample repr is hard-capped
    assert max(runs) >= 40  # but a truncated sample of the long value is present


def test_numeric_min_median_max() -> None:
    df = pd.DataFrame({"n": [10, 20, 30, 40, 50]})
    line = _line_for(profile_df(df, "d"), "n")
    assert "min=10" in line
    assert "median=30" in line
    assert "max=50" in line


def test_object_top_values_and_nunique() -> None:
    df = pd.DataFrame({"c": ["a", "a", "a", "b", "b", "c"]})
    line = _line_for(profile_df(df, "d"), "c")
    assert "'a'" in line
    assert "×3" in line  # top value_counts with counts
    assert "| 3 |" in line  # nunique cell


def test_empty_df_does_not_raise() -> None:
    assert "0 rows × 0 cols" in profile_df(pd.DataFrame(), "empty")
    assert "0 rows" in profile_df(pd.DataFrame(columns=["a", "b"]), "cols_only")
    assert "0 cols" in profile_df(pd.DataFrame(index=range(2)), "rows_only")


def test_all_nan_column() -> None:
    df = pd.DataFrame({"fnan": [float("nan")] * 4, "onan": [None] * 4})
    out = profile_df(df, "d")
    assert "0.0%" in _line_for(out, "fnan")
    assert "0.0%" in _line_for(out, "onan")


def test_duplicate_column_names() -> None:
    df = pd.DataFrame([[1, "a"], [2, "b"]], columns=["x", "x"])
    out = profile_df(df, "d")
    assert sum(line.startswith("| x |") for line in out.splitlines()) == 2


def test_wide_frame_respects_char_budget() -> None:
    df = pd.DataFrame({f"f_{i:03d}": range(5) for i in range(150)})
    for budget in (6000, 1500):
        out = profile_df(df, "wide", char_budget=budget)
        assert len(out) <= budget  # hard cap, never exceeded
        match = OMITTED_RE.search(out)
        assert match is not None  # omitted marker present
        kept = sum(line.startswith("| f_") for line in out.splitlines())
        assert kept > 0  # truncation happens at whole-row boundaries, not before
        assert kept + int(match.group(1)) == 150


def test_determinism_and_pathological_values() -> None:
    df = pd.DataFrame(
        {
            "mix": [1, "a", 3.5, None],
            "uni": ["café", "🚀🔥", "naïve", "ok"],
            "ts": pd.to_datetime(["2021-03-01", "2020-01-15", "2022-07-09", None]),
        }
    )
    first = profile_df(df, "d")
    assert profile_df(df, "d") == first  # byte-identical, no randomness
    assert "🚀" in first
    line = _line_for(first, "ts")
    assert "min=2020-01-15" in line
    assert "max=2022-07-09" in line


def test_no_raw_dump_on_large_frame() -> None:
    values = [f"common_{i % 3}" for i in range(10_000)]
    values[5_000] = "SENTINEL_ROW_5000_ONLY"
    df = pd.DataFrame({"cat": values, "num": range(10_000)})
    out = profile_df(df, "big")
    assert "SENTINEL_ROW_5000_ONLY" not in out  # only head samples + aggregates leak
    assert "10,000 rows" in out


# -- PII masking (#114): the profile is what the model sees in place of rows --

LOCAL_PARTS = ("jane.doe", "raj.patel", "m.okafor")


def _customers() -> pd.DataFrame:
    """A CRM export: ids with leading zeros, addresses with stray whitespace
    and mixed case, one missing its TLD (no detector match), a sentinel."""
    return pd.DataFrame(
        {
            "customer_id": [
                *("00412", "00077", "01999", "00412"),
                *("00981", "00063", "00500", "00777"),
            ],
            "email": [
                " Jane.Doe@acme.co.uk",
                None,
                "m.okafor@northwind",
                "raj.patel@acme.co.uk",
                "N/A",
                "jane.doe@acme.co.uk",
                "raj.patel@acme.co.uk",
                "raj.patel@acme.co.uk",
            ],
            "amount": [1200.5, 99.0, -999.0, 15.25, 0.0, 310.0, 42.0, 7.5],
        }
    )


def test_an_email_column_profiles_masked_with_its_counts_kept() -> None:
    """Regression for #114. A flagged column's samples and top values all pass
    through pii.mask_cell, the address the detector misses (no TLD) included,
    so no local part reaches the model. non-null % and nunique are counted on
    the raw values: 7 of 8 cells are non-null and 5 are distinct (masked, they
    would collapse to 3)."""
    out = profile_df(_customers(), "customers")
    for local in LOCAL_PARTS:
        assert local not in out.lower()
    assert set(re.findall(r"(.{0,3})@", out)) == {"***"}  # every @ is masked
    row = _cells(out, "email")
    assert row["samples"].count("***@acme.co.uk") == 2
    assert "***@northwind" in row["samples"]
    assert re.match(r"top: '?\*\*\*@acme\.co\.uk'?×3 · ", row["stats"])
    assert row["non_null"] == "87.5%"
    assert row["nunique"] == "5"


@pytest.mark.parametrize(
    ("column", "values"),
    [
        (
            "phone",
            ["(555) 010-4477", "555.010.9921", None]
            + ["555-010-3310", "5550107788", "555.010.9921"],
        ),
        (
            "ssn",
            ["123-45-6789", " 987-65-4320", "078-05-1120"]
            + [None, "123-45-6789", "987-65-4320"],
        ),
        # an Excel export: one card came through as a number, so the column is
        # object dtype with an int in it
        (
            "card_no",
            [4111111111111111, "5500-0000-0000-0004", "4012 8888 8888 1881"]
            + [None, "378282246310005", "5500-0000-0000-0004"],
        ),
    ],
    ids=["phone", "ssn", "credit_card"],
)
def test_phone_ssn_and_card_columns_profile_redacted(column, values) -> None:
    """Regression for #114. Every type but email masks to [REDACTED], in the
    samples and the top values, so no four digits of a number survive."""
    row = _cells(profile_df(pd.DataFrame({column: values}), "d"), column)
    assert re.search(r"\d{4}", row["samples"] + " " + row["stats"]) is None
    assert row["samples"].count(pii.REDACTED) == 3
    assert pii.REDACTED in row["stats"]


def test_a_headerless_export_masks_its_int_named_email_column() -> None:
    """Regression for #114. read_csv(header=None) names columns 0, 1, 2. The
    email column at 0 is masked like a named one (a flag kept under str(name)
    must still find it), and the id column beside it is not."""
    raw = (
        "jane.doe@acme.co.uk,00412,1200.50\n"
        "raj.patel@acme.co.uk,00077,N/A\n"
        "m.okafor@northwind-traders.com,01999,-999\n"
        "jane.doe@acme.co.uk,00500,42.00\n"
    )
    df = pd.read_csv(io.StringIO(raw), header=None, dtype=str, keep_default_na=False)
    assert list(df.columns) == [0, 1, 2]
    out = profile_df(df, "headerless")
    for local in LOCAL_PARTS:
        assert local not in out.lower()
    assert _cells(out, "0")["samples"].count("***@") == 3
    assert _cells(out, "1")["samples"] == "'00412' · '00077' · '01999'"


def test_unflagged_text_columns_keep_their_raw_samples_and_top_values() -> None:
    """Regression for #114 (the pin). Masking is for flagged columns and for
    values that are PII on their own: ids with leading zeros, a supplier
    with an `@` in free text and invoice refs full of digits sit beside a
    flagged email column and render exactly as they do without it."""
    df = pd.DataFrame(
        {
            "customer_id": ["00412", "00077", "01999", "00412", "00981", "00063"],
            "supplier": [
                *("Acme Ltd", "Acme Ltd @ Leeds", "Globex"),
                *("N/A", "Acme Ltd", "Initech"),
            ],
            "invoice_ref": [
                *("INV-2026-000417", "CN-000099", "INV-2026-000418"),
                *(None, "INV-2026-000417", "INV-2026-000420"),
            ],
            "email": [
                *("jane.doe@acme.co.uk", "raj.patel@acme.co.uk", None),
                *("m.okafor@northwind", "jane.doe@acme.co.uk", "N/A"),
            ],
        }
    )
    out = profile_df(df, "invoices")
    expected = {
        "customer_id": (
            "'00412' · '00077' · '01999'",
            "top: '00412'×2 · '00077'×1 · '01999'×1",
        ),
        "supplier": (
            "'Acme Ltd' · 'Acme Ltd @ Leeds' · 'Globex'",
            "top: 'Acme Ltd'×2 · 'Acme Ltd @ Leeds'×1 · 'Globex'×1",
        ),
        "invoice_ref": (
            "'INV-2026-000417' · 'CN-000099' · 'INV-2026-000418'",
            "top: 'INV-2026-000417'×2 · 'CN-000099'×1 · 'INV-2026-000418'×1",
        ),
    }
    alone = profile_df(df.drop(columns="email"), "invoices")
    for column, (samples, stats) in expected.items():
        row = _cells(out, column)
        assert (row["samples"], row["stats"]) == (samples, stats)
        assert _line_for(out, column) == _line_for(alone, column)


def test_numbers_are_never_read_as_pii_on_their_own() -> None:
    """Regression for #114 (the pin). Only str values in object or string
    columns are checked for PII on their own. Every number here reads as a
    phone once it is a string, but 10-digit account ids in an int64 column,
    and ints in an object column of an Excel sheet, render raw beside a
    flagged email column, exactly as they do without it."""
    df = pd.DataFrame(
        {
            "account_no": [5550104477, 4012888888, 2125550199, 5550104477],
            "legacy_ref": [5550109921, "N/A", 2125550147, None],
            "email": [
                *("jane.doe@acme.co.uk", "raj.patel@acme.co.uk"),
                *(None, "m.okafor@northwind"),
            ],
        }
    )
    assert str(df["account_no"].dtype) == "int64"
    assert str(df["legacy_ref"].dtype) == "object"
    out = profile_df(df, "ledger")
    account = _cells(out, "account_no")
    assert account["samples"] == "5550104477 · 4012888888 · 2125550199"
    assert account["stats"] == "min=2.12555e+09 · median=4.7815e+09 · max=5.5501e+09"
    legacy = _cells(out, "legacy_ref")
    assert legacy["samples"] == "5550109921 · 'N/A' · 2125550147"
    assert legacy["stats"] == "top: 5550109921×1 · 'N/A'×1 · 2125550147×1"
    alone = profile_df(df.drop(columns="email"), "ledger")
    for column in ("account_no", "legacy_ref"):
        assert _line_for(out, column) == _line_for(alone, column)


def test_a_lone_address_shown_in_an_unflagged_column_is_masked_alone() -> None:
    """Regression for #114. The flag comes from the first 10,000 non-null
    values, so a contact column whose older rows hold free text is unflagged
    even when a shared mailbox in its newer rows becomes a top value. That one
    shown value is PII on its own and is masked; the column's other values
    stay raw."""
    older = ["see CRM"] * 6 + ["no contact on file"] * 3 + ["phone only"]
    contact = [older[i % 10] for i in range(10_000)]
    contact += ["accounts.payable@northwind-traders.com"] * 1_500
    out = profile_df(pd.DataFrame({"contact": contact}), "crm")
    assert "accounts.payable" not in out
    row = _cells(out, "contact")
    assert row["samples"] == "'see CRM' · 'see CRM' · 'see CRM'"
    assert re.fullmatch(
        r"top: 'see CRM'×6000 · 'no contact on file'×3000"
        r" · '?\*\*\*@northwind-traders\.com'?×1500",
        row["stats"],
    )
    assert (row["non_null"], row["nunique"]) == ("100.0%", "4")


NOTES = ("pending review", "reversed", "ok")


def _notes_with_one_email(leading_blanks: int, email_nth: int) -> list:
    """A bank-feed notes column: `leading_blanks` empty rows (exported before
    the column existed), then notes with a blank every 50th row, one payee
    address as the `email_nth` non-null value (1-based), and 500 more notes.
    The address appears once, so it is never a top value."""
    values: list = [None] * leading_blanks
    seen = 0
    while seen < email_nth + 500:
        if len(values) % 50 == 49:
            values.append(None)
            continue
        seen += 1
        values.append("r.ito@kumo-bank.jp" if seen == email_nth else NOTES[seen % 3])
    return values


@pytest.mark.parametrize(
    ("leading_blanks", "email_nth", "flagged"),
    [
        (0, 10_001, False),  # the 10,001st non-null value: past the scan
        (2_000, 10_000, True),  # the 10,000th non-null value, past row 12,000
    ],
    ids=["past-the-window", "last-in-the-window"],
)
def test_the_pii_scan_reads_the_first_10000_non_null_values(
    leading_blanks, email_nth, flagged
) -> None:
    """Regression for #114. The flag comes from at most 10,000 non-null values
    per column, the first by position, so the profile stays fast on a large
    frame. A flagged column masks every sample, so its plain notes show as
    [REDACTED]; an unflagged one shows them raw. Blank rows don't count
    against the window."""
    values = _notes_with_one_email(leading_blanks, email_nth)
    assert values.index("r.ito@kumo-bank.jp") > 10_000
    out = profile_df(pd.DataFrame({"notes": values}), "feed")
    assert "r.ito" not in out
    samples = _cells(out, "notes")["samples"]
    if flagged:
        assert samples.count(pii.REDACTED) == 3
    else:
        assert samples == "'reversed' · 'ok' · 'pending review'"


def test_masked_rows_keep_the_char_budget_and_determinism() -> None:
    """Regression for #114. A wide contact export, every column addresses:
    rows are masked before the char budget cuts them, they are cut whole, and
    the output is byte-identical run to run."""
    df = pd.DataFrame(
        {
            f"email_{i:03d}": [f"user{i}.{j}@acme.co.uk" for j in range(5)]
            for i in range(150)
        }
    )
    for budget in (6000, 1500):
        out = profile_df(df, "wide", char_budget=budget)
        assert "user" not in out
        assert len(out) <= budget
        match = OMITTED_RE.search(out)
        assert match is not None
        kept = sum(line.startswith("| email_") for line in out.splitlines())
        assert kept > 0
        assert kept + int(match.group(1)) == 150
        assert profile_df(df, "wide", char_budget=budget) == out
