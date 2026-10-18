"""PII detection and masking (capability roadmap B0.1, the ship-safety
prerequisite that gates the shareable HTML report). Keyless and pure-stdlib:
conservative regex detectors plus a Luhn check for cards, so a receipts tool
does not cry wolf. Each hit carries evidence; masking is offered as a safe
fix. Names/addresses need NER and are deliberately out of the keyless path."""

import copy

import pandas as pd
import pytest

import crivo  # noqa: F401  (registers the df.crivo accessor)
from crivo import pii


def test_detects_emails_with_a_count_and_masked_sample():
    df = pd.DataFrame({"contact": ["a@x.com", "b@y.org", "not-an-email", None]})
    (hit,) = pii.scan(df)
    assert hit["column"] == "contact"
    assert hit["pii_type"] == "email"
    assert hit["count"] == 2
    assert "@" in hit["sample"] and "a@x.com" not in hit["sample"]  # sample masked


def test_credit_cards_require_a_luhn_pass():
    # 4111111111111111 passes Luhn; 4111111111111112 does not
    df = pd.DataFrame({"card": ["4111111111111111", "4111111111111112"]})
    (hit,) = pii.scan(df)
    assert hit["pii_type"] == "credit_card"
    assert hit["count"] == 1  # only the Luhn-valid one counts


def test_ssn_and_phone_are_separate_types():
    df = pd.DataFrame({"ssn": ["123-45-6789", "x"], "phone": ["(415) 555-0132", "y"]})
    types = {h["column"]: h["pii_type"] for h in pii.scan(df)}
    assert types == {"ssn": "ssn", "phone": "phone"}


def test_clean_frame_yields_no_findings():
    df = pd.DataFrame({"amount": [1.0, 2.5], "city": ["burnaby", "vancouver"]})
    assert pii.scan(df) == []


def test_numeric_columns_are_never_scanned_as_text():
    # a numeric column of 16-digit-ish ints must not be read as cards
    df = pd.DataFrame({"n": [4111111111111111, 2]})
    assert pii.scan(df) == []


def test_mask_column_redacts_the_detected_type_only():
    df = pd.DataFrame({"contact": ["a@x.com", "plain"]})
    masked = pii.mask_column(df["contact"], "email")
    assert masked.iloc[0] != "a@x.com"
    assert masked.iloc[0].endswith("@x.com") or masked.iloc[0] == pii.REDACTED
    assert masked.iloc[1] == "plain"  # non-matching cells untouched


def test_scan_findings_are_gradeable_and_carry_evidence():
    df = pd.DataFrame({"email": ["a@x.com", "b@y.com"]})
    (hit,) = pii.scan(df)
    assert hit["grade"] in {"GATE", "HUMAN"}  # exposure is never a silent auto-fix
    assert str(hit["count"]) in hit["evidence"]


# --- #9: one shared masker for every shareable surface ---------------------
# The helpers below do not exist before #9, so each test reaches them through
# `_helper` and fails on an assertion, not an AttributeError at import.


def _helper(name):
    fn = getattr(pii, name, None)
    assert callable(fn), f"pii.{name} is not defined"
    return fn


def test_scan_reads_duplicate_named_columns():
    # a CRM export with two "c" columns (primary and billing contact); each
    # copy is its own column, read by position
    df = pd.DataFrame(
        [
            ["a.lee@example.com", "billing@acme.co"],
            [" b.ng@mail.example.org ", "ops@acme.co"],
            ["n/a", "ops@acme.co"],
            [None, ""],
        ],
        columns=["c", "c"],
    )
    hits = pii.scan(df)
    assert [h["pii_type"] for h in hits] == ["email", "email"]
    assert [h["column"] for h in hits] == ["c", "c"]
    assert [h["count"] for h in hits] == [2, 3]


def test_scan_by_position_still_skips_a_numeric_twin():
    # same name twice: SSN text in one copy, card-length ints in the other;
    # only the text copy is PII
    df = pd.DataFrame(
        [["123-45-6789", 4111111111111111], ["987-65-4321", 2]],
        columns=["id", "id"],
    )
    hits = pii.scan(df)
    assert [(h["column"], h["pii_type"], h["count"]) for h in hits] == [
        ("id", "ssn", 2)
    ]


def test_email_mask_keeps_only_the_domain():
    assert pii.mask_value("x0@example.com|555-123-4000", "email") == "***@example.com"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("first.last@mail.example.co.uk", "***@mail.example.co.uk"),
        ("o'brien@sub-domain.example.com", "***@sub-domain.example.com"),
        ("x_y@example_corp.com", "***@example_corp.com"),
    ],
)
def test_email_mask_keeps_a_plain_domain_whole(value, expected):
    # pin beside the cut above: a real domain survives intact
    assert pii.mask_value(value, "email") == expected


@pytest.mark.parametrize("value", ["a@|b", "a@", "a@ example.com"])
def test_email_mask_is_redacted_when_no_domain_follows_the_at(value):
    assert pii.mask_value(value, "email") == pii.REDACTED


@pytest.mark.parametrize(
    "value, pii_type, expected",
    [
        ("  a.lee@example.com  ", "email", "***@example.com"),
        (-999, "email", pii.REDACTED),  # numeric sentinel in an email column
        (4111111111111111, "credit_card", pii.REDACTED),
        ("(415) 555-0132", "phone", pii.REDACTED),
    ],
)
def test_mask_cell_masks_any_cell_value(value, pii_type, expected):
    mask_cell = _helper("mask_cell")
    assert mask_cell(value, pii_type) == expected


def test_flagged_columns_keys_are_str_and_the_earlier_frame_wins():
    flagged_columns = _helper("flagged_columns")
    # before and after a clean: column 0 held emails, then SSN-shaped text
    before = pd.DataFrame(
        {0: ["a.lee@example.com", "ops@acme.co"], "amount": ["$1,234.50", "-999"]}
    )
    after = pd.DataFrame(
        {0: ["123-45-6789", "987-65-4321"], "phone": ["(415) 555-0132", "604.555.0199"]}
    )
    assert flagged_columns(before, after) == {"0": "email", "phone": "phone"}
    assert flagged_columns(pd.DataFrame({"city": ["Burnaby", "VANCOUVER"]})) == {}


@pytest.mark.parametrize(
    "rows, expected",
    [
        pytest.param(
            [["a.lee@example.com", "(415) 555-0132"], ["ops@acme.co", "604.555.0199"]],
            {"contact": "email"},
            id="email-first",
        ),
        pytest.param(
            [["(415) 555-0132", "a.lee@example.com"], ["604.555.0199", "ops@acme.co"]],
            {"contact": "phone"},
            id="phone-first",
        ),
    ],
)
def test_flagged_columns_first_duplicate_by_position_wins(rows, expected):
    """Two same-named columns in ONE frame with different PII types map to a
    single key, so one type has to win: the leftmost copy's, whatever its
    type. Pins the current rule so a change to it is a decision, not drift."""
    flagged_columns = _helper("flagged_columns")
    df = pd.DataFrame(rows, columns=["contact", "contact"])
    assert flagged_columns(df) == expected


def test_redact_text_masks_quoted_values_of_a_flagged_column():
    redact_text = _helper("redact_text")
    evidence = "samples: '  user2@example.com  ', 'averyverylongname@exa'"
    out = redact_text(evidence, ["email"], {"email": "email"})
    assert out.startswith("samples: ")
    assert "user2@" not in out
    assert "averyverylongname" not in out
    assert out == "samples: '***@example.com', '***@exa'"


@pytest.mark.parametrize(
    "column, pii_type, evidence, expected",
    [
        pytest.param(
            "phone",
            "phone",
            (
                "2/40 values carry stray whitespace; samples: '(604) 555-0199 x12', "
                "' 604.555.0199'"
            ),
            "2/40 values carry stray whitespace; samples: '[REDACTED]', '[REDACTED]'",
            id="phone-with-extension",
        ),
        pytest.param(
            "tax_id",
            "ssn",
            "1/12 values carry stray whitespace; samples: 'SSN 123-45-6789'",
            "1/12 values carry stray whitespace; samples: '[REDACTED]'",
            id="ssn-with-prefix",
        ),
    ],
)
def test_redact_text_masks_by_the_flagged_column_type(
    column, pii_type, evidence, expected
):
    # these cells no longer match a detector on their own; the column's flag
    # is what masks them
    redact_text = _helper("redact_text")
    assert redact_text(evidence, [column], {column: pii_type}) == expected


def test_redact_text_reads_an_apostrophe_in_prose_as_prose():
    """Disease 22's own wording ("Excel's text-guard") has an apostrophe
    before its samples. Read as an opening quote, it pairs with the guard
    apostrophe inside the first sample, the real double-quoted literals are
    never seen as literals, and both SSNs leak. The prose stays as written and
    each sample is masked whole."""
    redact_text = _helper("redact_text")
    evidence = (
        "2 identifiers carry a leading apostrophe — Excel's text-guard leaked "
        'into the data; samples: "\'123-45-6702", "\'123-45-6709"'
    )
    expected = (
        "2 identifiers carry a leading apostrophe — Excel's text-guard leaked "
        f'into the data; samples: "{pii.REDACTED}", "{pii.REDACTED}"'
    )
    assert redact_text(evidence, ["ssn_id"], {"ssn_id": "ssn"}) == expected


def test_redact_text_matches_column_names_as_str():
    redact_text = _helper("redact_text")
    out = redact_text("samples: 'averyverylongname@exa'", [0], {"0": "email"})
    assert out == "samples: '***@exa'"


@pytest.mark.parametrize(
    "columns, expected",
    [
        pytest.param(["email", "phone"], "pairs: '***@example.com'", id="email-first"),
        pytest.param(["phone", "email"], "pairs: '[REDACTED]'", id="phone-first"),
        pytest.param(
            ["city", "phone", "email"], "pairs: '[REDACTED]'", id="unflagged-first"
        ),
    ],
)
def test_redact_text_uses_the_first_flagged_column_in_order(columns, expected):
    redact_text = _helper("redact_text")
    flagged = {"email": "email", "phone": "phone"}
    assert redact_text("pairs: 'user2@example.com'", columns, flagged) == expected


@pytest.mark.parametrize(
    "evidence, expected",
    [
        pytest.param("'user@example.com'", "'***@example.com'", id="email"),
        pytest.param(
            'samples: "o\'brien@example.com"',
            'samples: "***@example.com"',
            id="email-double-quoted",
        ),
        pytest.param("samples: '123-45-6789'", "samples: '[REDACTED]'", id="ssn"),
        pytest.param(
            "samples: '4111 1111 1111 1111'", "samples: '[REDACTED]'", id="card"
        ),
        pytest.param("samples: '(415) 555-0132'", "samples: '[REDACTED]'", id="phone"),
        # an index label beside a plain one: only the PII literal is masked
        pytest.param(
            (
                "2 parameters are reported in more than one unit "
                "(e.g. 'ops@acme.co', 'row 7')"
            ),
            (
                "2 parameters are reported in more than one unit "
                "(e.g. '***@acme.co', 'row 7')"
            ),
            id="index-label",
        ),
    ],
)
def test_redact_text_masks_a_pii_literal_from_an_unflagged_column(evidence, expected):
    redact_text = _helper("redact_text")
    assert redact_text(evidence, ["notes"], {}) == expected


@pytest.mark.parametrize(
    "evidence, columns, flagged",
    [
        pytest.param(
            "2 number formats in one column (bare 90%, symbol 7%)",
            ["revenue"],
            {},
            id="unquoted-prose",
        ),
        pytest.param(
            (
                "10 distinct values collapse to 7 once case and whitespace are "
                "normalised; samples: 'Burnaby', 'burnaby ', 'VANCOUVER'"
            ),
            ["city"],
            {},
            id="city-names",
        ),
        pytest.param(
            (
                "3/9 values carry currency/unit residue; samples: '$1,234.50', "
                "'00123', '-999'"
            ),
            ["amount"],
            {"email": "email"},
            id="money-ids-sentinel-beside-a-flagged-column",
        ),
        pytest.param(
            (
                "column is text, not datetime64; samples: '2024-03-01', "
                "'03/01/2024', 'N/A'"
            ),
            ["signup"],
            {},
            id="dates",
        ),
        pytest.param(
            "12 of 400 cells are blank",
            ["email"],
            {"email": "email"},
            id="flagged-column-no-literal",
        ),
        # disease 22 on a plain account column: the apostrophe fix must not
        # start masking non-PII samples that follow "Excel's"
        pytest.param(
            (
                "2 identifiers carry a leading apostrophe — Excel's text-guard "
                'leaked into the data; samples: "\'00123", "\'004417"'
            ),
            ["acct_id"],
            {"email": "email"},
            id="apostrophe-prose-non-pii-ids",
        ),
    ],
)
def test_redact_text_leaves_text_without_pii_byte_identical(evidence, columns, flagged):
    # pin beside the masking: prose and non-PII literals pass through untouched
    redact_text = _helper("redact_text")
    assert redact_text(evidence, columns, flagged) == evidence


def test_redact_findings_leaves_its_input_untouched():
    redact_findings = _helper("redact_findings")
    findings = [
        {
            "disease": 6,
            "slug": "whitespace-damage",
            "columns": ["email"],
            "evidence": "2/40 values carry stray whitespace; samples: "
            "'  user2@example.com  ', 'averyverylongname@exa'",
            "stats": {"count": 2, "exotic": 0, "values": 40},
            "grade": "AUTO",
            "confidence": 0.95,
            "indicator": False,
        },
        {
            "disease": 7,
            "slug": "case-spelling-variants",
            "columns": ["city"],
            "evidence": "3 distinct values collapse to 2 once case and whitespace "
            "are normalised; samples: 'Burnaby', 'burnaby '",
            "stats": {"distinct": 3, "normalised": 2, "shrink": 0.333333},
            "grade": "AUTO",
            "confidence": 0.9,
            "indicator": False,
        },
    ]
    before = copy.deepcopy(findings)
    out = redact_findings(findings, {"email": "email"})
    assert findings == before
    assert len(out) == 2
    assert out[0] is not findings[0] and out[1] is not findings[1]
    assert out[0]["evidence"] == (
        "2/40 values carry stray whitespace; samples: '***@example.com', '***@exa'"
    )
    assert out[1]["evidence"] == findings[1]["evidence"]
    for got, orig in zip(out, findings):
        assert {k: v for k, v in got.items() if k != "evidence"} == {
            k: v for k, v in orig.items() if k != "evidence"
        }


def test_redacted_diagnose_evidence_never_carries_a_guarded_ssn():
    """End to end on the real detector's wording, not a hand-typed copy: an
    export where Excel's text-guard put an apostrophe on 2 of 12 SSN ids.
    Disease 22 quotes both guarded ids in its evidence; after the shared
    masker runs, no digits of any SSN may survive in any finding."""
    redact_findings = _helper("redact_findings")
    flagged_columns = _helper("flagged_columns")
    ssn_ids = [f"123-45-67{n:02d}" for n in range(1, 13)]
    ssn_ids[1] = "'" + ssn_ids[1]
    ssn_ids[8] = "'" + ssn_ids[8]
    df = pd.DataFrame(
        {
            "ssn_id": ssn_ids,
            "amount": [
                "$1,234.50",
                "980.00",
                "-999",
                "12.5",
                "40",
                "$7.25",
                "3",
                "18.00",
                "99",
                "1,005.10",
                "0",
                "N/A",
            ],
        }
    )
    findings = df.crivo.diagnose().findings
    # the leak needs the disease-22 finding to be there; without it this
    # test would pass on nothing
    assert any(f["disease"] == 22 and f["columns"] == ["ssn_id"] for f in findings)
    flagged = flagged_columns(df)
    assert flagged.get("ssn_id") == "ssn"
    redacted = redact_findings(findings, flagged)
    # report which diseases leak, never the leaked values themselves
    leaking = [f["disease"] for f in redacted if "123-45-67" in f["evidence"]]
    assert leaking == []
