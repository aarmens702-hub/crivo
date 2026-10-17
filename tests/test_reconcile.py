"""Keyed row reconciliation (P7 harder-data, design spec decision 3).

The keyed twin of `compare`: `compare` diffs table shape, `reconcile` diffs the
rows themselves matched by a key, sorting them into added / removed / changed /
unchanged with a receipt. These tests pin the contract on crafted
frames: the four buckets, composite keys, duplicate-key exclusion, null-key
exclusion, key identity by value, the missing key error, disjoint columns, the
receipt (a partition guard plus an independent recount of the changed rows),
and bounded evidence (rows and columns). The keyless import of crivo.rowdiff
is pinned in test_import_isolation.py.
"""

import re

import pandas as pd
import pytest

import crivo
from crivo import pii

# the reconcile() feature lives in crivo.rowdiff (named to avoid shadowing the
# public crivo.reconcile wrapper); reach the module for its internals.
from crivo import rowdiff as reconcile
from crivo.rowdiff_report import reconcile_report


def _visible_text(html: str) -> str:
    """The report as a reader sees it: tags stripped, whitespace collapsed, so
    an assertion on a label does not depend on which element wraps it."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))


def test_basic_added_removed_changed_unchanged():
    # ids 1..4 vs 2..5: 1 removed, 5 added, id 3 changed, ids 2 and 4 unchanged
    a = pd.DataFrame({"id": [1, 2, 3, 4], "val": [10, 20, 30, 40]})
    b = pd.DataFrame({"id": [2, 3, 4, 5], "val": [20, 99, 40, 50]})

    result = reconcile.reconcile(a, b, "id")

    assert result["keys"] == ["id"]
    assert result["counts"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
        "unchanged": 2,
        "duplicate_keys": 0,
        "null_keys": 0,
    }
    assert result["added"] == [(5,)]
    assert result["removed"] == [(1,)]
    assert result["receipt"] is True

    (change,) = result["changed"]
    assert change["key"] == (3,)
    assert change["columns"] == ["val"]
    assert change["before"] == {"val": 30}
    assert change["after"] == {"val": 99}


def test_composite_multi_column_keys():
    # a two-column key: (region, sku) identifies a row
    a = pd.DataFrame(
        {
            "region": ["west", "west", "east"],
            "sku": ["A", "B", "A"],
            "qty": [1, 2, 3],
        }
    )
    b = pd.DataFrame(
        {
            "region": ["west", "west", "north"],
            "sku": ["A", "B", "C"],
            "qty": [1, 5, 9],
        }
    )

    result = reconcile.reconcile(a, b, ["region", "sku"])

    assert result["keys"] == ["region", "sku"]
    assert result["counts"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
        "unchanged": 1,
        "duplicate_keys": 0,
        "null_keys": 0,
    }
    assert result["added"] == [("north", "C")]
    assert result["removed"] == [("east", "A")]
    (change,) = result["changed"]
    assert change["key"] == ("west", "B")
    assert change["columns"] == ["qty"]
    assert change["before"] == {"qty": 2}
    assert change["after"] == {"qty": 5}
    assert result["receipt"] is True


def test_duplicate_keys_excluded_from_buckets_and_reported():
    # id 1 repeats in a, so it cannot be matched one to one: excluded from the
    # four buckets, reported in duplicate_keys, and the receipt stays exact
    a = pd.DataFrame({"id": [1, 1, 2], "val": [10, 10, 20]})
    b = pd.DataFrame({"id": [1, 2, 3], "val": [10, 20, 30]})

    result = reconcile.reconcile(a, b, "id")

    assert result["counts"] == {
        "added": 1,
        "removed": 0,
        "changed": 0,
        "unchanged": 1,
        "duplicate_keys": 1,
        "null_keys": 0,
    }
    assert result["duplicate_keys"] == [(1,)]
    # the duplicate key never leaks into any bucket
    assert (1,) not in result["added"]
    assert (1,) not in result["removed"]
    assert all(change["key"] != (1,) for change in result["changed"])
    # id 3 is the sole add, id 2 the sole unchanged row
    assert result["added"] == [(3,)]
    assert result["receipt"] is True
    assert any("duplicate" in note for note in result["notes"])


def test_missing_key_column_raises_value_error():
    a = pd.DataFrame({"id": [1, 2], "val": [1, 2]})
    b = pd.DataFrame({"identifier": [1, 2], "val": [1, 2]})

    # the key is absent from b, and the message names it
    with pytest.raises(ValueError, match="id"):
        reconcile.reconcile(a, b, "id")

    # and absent from a
    a2 = pd.DataFrame({"other": [1, 2], "val": [1, 2]})
    b2 = pd.DataFrame({"id": [1, 2], "val": [1, 2]})
    with pytest.raises(ValueError, match="id"):
        reconcile.reconcile(a2, b2, "id")


def test_disjoint_columns_compared_on_shared_only():
    # x is shared and comparable; only_a and only_b are one-sided and must be
    # reported as column_diff, never scored as cell changes
    a = pd.DataFrame({"id": [1, 2], "x": [5, 5], "only_a": ["p", "q"]})
    b = pd.DataFrame({"id": [1, 2], "x": [5, 9], "only_b": ["r", "s"]})

    result = reconcile.reconcile(a, b, "id")

    assert result["column_diff"] == {
        "only_in_a": ["only_a"],
        "only_in_b": ["only_b"],
        "compared": ["x"],
    }
    # only id 2 changed, and only on the shared column x
    assert result["counts"]["changed"] == 1
    assert result["counts"]["unchanged"] == 1
    (change,) = result["changed"]
    assert change["key"] == (2,)
    assert change["columns"] == ["x"]
    assert "only_a" not in change["before"]
    assert "only_b" not in change["after"]
    assert result["receipt"] is True


def test_partition_receipt_sums_to_distinct_non_duplicate_keys():
    # a frame with adds, removes, a change, an unchanged row, and a duplicate;
    # the four buckets must partition exactly the distinct non-duplicate keys
    a = pd.DataFrame({"id": [1, 2, 3, 3, 4], "val": [10, 20, 30, 30, 40]})
    b = pd.DataFrame({"id": [2, 4, 5, 6], "val": [99, 40, 50, 60]})

    result = reconcile.reconcile(a, b, "id")

    # id 3 is duplicated in a, so it is excluded from the key space entirely.
    # distinct non-duplicate keys across a and b: {1, 2, 4, 5, 6} => 5
    distinct_non_duplicate = 5
    counts = result["counts"]
    assert (
        counts["added"] + counts["removed"] + counts["changed"] + counts["unchanged"]
        == distinct_non_duplicate
    )
    assert result["receipt"] is True
    assert counts["duplicate_keys"] == 1


def test_example_lists_are_bounded_with_exact_counts():
    cap = reconcile._EXAMPLE_CAP

    # every b row is an add (a shares no ids), well past the cap
    n_added = cap + 5
    a = pd.DataFrame({"id": [-1], "val": [0]})
    b = pd.DataFrame({"id": list(range(n_added)), "val": list(range(n_added))})

    result = reconcile.reconcile(a, b, "id")
    assert result["counts"]["added"] == n_added
    assert len(result["added"]) == cap  # list bounded, count exact
    assert any("added" in note and "truncated" in note for note in result["notes"])

    # every shared row changed, also past the cap
    n_changed = cap + 3
    a2 = pd.DataFrame({"id": list(range(n_changed)), "val": [0] * n_changed})
    b2 = pd.DataFrame({"id": list(range(n_changed)), "val": [1] * n_changed})

    result2 = reconcile.reconcile(a2, b2, "id")
    assert result2["counts"]["changed"] == n_changed
    assert len(result2["changed"]) == cap
    assert any("changed" in note and "truncated" in note for note in result2["notes"])
    assert result2["receipt"] is True


def test_nulls_match_and_are_not_a_change():
    # a shared key whose compared cell is null on both sides is unchanged, not
    # a change; a null against a present value is a change
    a = pd.DataFrame({"id": [1, 2], "val": [None, 5]})
    b = pd.DataFrame({"id": [1, 2], "val": [None, 6]})

    result = reconcile.reconcile(a, b, "id")

    assert result["counts"]["unchanged"] == 1  # id 1: null == null
    assert result["counts"]["changed"] == 1  # id 2: 5 -> 6
    (change,) = result["changed"]
    assert change["key"] == (2,)


def test_null_key_rows_are_excluded_and_reported_not_split_across_buckets():
    # regression: a float NaN key used to slip matching (NaN != NaN), so a
    # null-keyed row could land in BOTH added and removed while the receipt
    # stayed True. A null in a key cell is not a valid one-to-one identifier,
    # so the row is now excluded from the four buckets and reported in
    # null_keys, the same discipline as a duplicate key.
    a = pd.DataFrame({"id": [1.0, float("nan"), float("nan")], "val": [10, 20, 30]})
    b = pd.DataFrame({"id": [1.0, float("nan")], "val": [10, 99]})

    result = reconcile.reconcile(a, b, "id")

    # id 1.0 is the only matchable key and is unchanged; every NaN-keyed row is
    # excluded and the repeated NaN collapses to a single reported null key
    assert result["counts"] == {
        "added": 0,
        "removed": 0,
        "changed": 0,
        "unchanged": 1,
        "duplicate_keys": 0,
        "null_keys": 1,
    }
    assert result["null_keys"] == [(None,)]  # a null key shows as None
    # the null key never leaks into any bucket (the old both-buckets bug)
    assert result["added"] == []
    assert result["removed"] == []
    assert all(change["key"] != (None,) for change in result["changed"])
    assert result["receipt"] is True
    assert any("null" in note for note in result["notes"])


def test_key_identity_is_by_value_bool_distinct_int_matches_float():
    # documented key identity: an integral float is the same key as that int,
    # so an id column that drifted from int to float across two extracts still
    # lines up; a bool is kept distinct from 0/1 so a boolean column never
    # silently merges with a numeric one.

    # (a) int keys in a match integral-float keys in b
    a = pd.DataFrame({"id": [1, 2, 3], "val": [10, 20, 30]})
    b = pd.DataFrame({"id": [1.0, 2.0, 3.0], "val": [10, 20, 30]})
    r = reconcile.reconcile(a, b, "id")
    assert r["counts"] == {
        "added": 0,
        "removed": 0,
        "changed": 0,
        "unchanged": 3,
        "duplicate_keys": 0,
        "null_keys": 0,
    }
    assert r["receipt"] is True

    # (b) a bool key does not collapse with the int 1 into a fabricated
    # duplicate: 1 and True are two distinct keys, so both rows match unchanged
    a2 = pd.DataFrame({"id": pd.Series([1, True], dtype=object), "val": [10, 20]})
    b2 = pd.DataFrame({"id": pd.Series([1, True], dtype=object), "val": [10, 20]})
    r2 = reconcile.reconcile(a2, b2, "id")
    assert r2["counts"]["duplicate_keys"] == 0
    assert r2["counts"]["unchanged"] == 2
    assert r2["receipt"] is True

    # (c) 1 and 1.0 are the SAME key by value, so a frame carrying both has a
    # genuine duplicate id, reported not silently collapsed
    a3 = pd.DataFrame({"id": pd.Series([1, 1.0], dtype=object), "val": [10, 20]})
    b3 = pd.DataFrame({"id": [2], "val": [30]})
    r3 = reconcile.reconcile(a3, b3, "id")
    assert r3["counts"]["duplicate_keys"] == 1
    assert r3["duplicate_keys"] == [(1,)]
    assert r3["receipt"] is True


def test_receipt_is_a_real_disjoint_cover_over_the_whole_key_space():
    # a rich frame exercising every group at once: an add, a remove, a change,
    # an unchanged row, a duplicate key, and a null key. Every reported key
    # lands in exactly one place. The buckets come from set algebra, so this
    # cover holds by construction; the receipt's check that can fail is the
    # recount of changed rows, pinned in the #20 tests below.
    a = pd.DataFrame(
        {"id": [1, 2, 3, 4, 4, float("nan")], "val": [10, 20, 30, 40, 40, 50]}
    )
    b = pd.DataFrame({"id": [2, 3, 5, float("nan")], "val": [20, 99, 60, 70]})

    r = reconcile.reconcile(a, b, "id")

    assert r["counts"] == {
        "added": 1,  # id 5
        "removed": 1,  # id 1
        "changed": 1,  # id 3: 30 -> 99
        "unchanged": 1,  # id 2
        "duplicate_keys": 1,  # id 4 repeats in a
        "null_keys": 1,  # NaN in both frames, one reported null key
    }
    assert r["receipt"] is True
    # every reported key falls in exactly one group, nothing double-counted
    reported = (
        r["added"]
        + r["removed"]
        + [change["key"] for change in r["changed"]]
        + r["duplicate_keys"]
        + r["null_keys"]
    )
    assert len(reported) == len(set(reported))


def test_changed_row_before_after_are_bounded_in_width():
    # regression: the changed ROW list was capped, but before/after inside a
    # changed entry listed EVERY differing column with no cap and no note, so a
    # wide row was a full-width dump. The differing columns are now capped and
    # the truncation is noted.
    cap = reconcile._COLUMN_CAP
    n_cols = cap + 20
    a = pd.DataFrame({"id": [1], **{f"c{i}": [0] for i in range(n_cols)}})
    b = pd.DataFrame({"id": [1], **{f"c{i}": [1] for i in range(n_cols)}})

    result = reconcile.reconcile(a, b, "id")

    assert result["counts"]["changed"] == 1  # still one changed row, count exact
    (change,) = result["changed"]
    assert len(change["columns"]) == cap  # column list bounded
    assert len(change["before"]) == cap  # before dict bounded
    assert len(change["after"]) == cap  # after dict bounded
    assert any("column" in note for note in result["notes"])
    assert result["receipt"] is True


def test_reconcile_surface_is_exported():
    # reconcile and its HTML twin are wired onto the top-level package and named
    # in crivo.__all__, the same public-surface contract as compare and drivers.
    # Both resolve to the callable wrappers, not the same-named submodules.
    assert {"reconcile", "reconcile_report"} <= set(crivo.__all__)
    assert callable(crivo.reconcile)
    assert callable(crivo.reconcile_report)


# --- reconcile_report: the self-contained HTML render (fast-follow) ---
# The keyed twin of the compare report. These pin the render contract: one
# self-contained document (no external asset, no script), the four bucket
# counts, a changed row with its changed columns and before-to-after, the
# duplicate-key note and column diff, and HTML escaping of hostile values.


def test_report_is_one_self_contained_document():
    a = pd.DataFrame({"id": [1, 2, 3], "val": [10, 20, 30]})
    b = pd.DataFrame({"id": [2, 3, 4], "val": [20, 99, 40]})
    html = reconcile_report(a, b, "id")
    assert html.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in html
    # self-contained: nothing to fetch, no script to run, emailable
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html.lower()


def test_report_shows_a_changed_row_and_its_changed_columns():
    # id 3 changes val 30 -> 99; the changed key, the changed column, and the
    # before-to-after values must all appear in the rendered document
    a = pd.DataFrame({"id": [1, 2, 3], "val": [10, 20, 30]})
    b = pd.DataFrame({"id": [1, 2, 3], "val": [10, 20, 99]})
    html = reconcile_report(a, b, "id")
    assert "<code>3</code>" in html  # the changed row's key
    assert "<code>val</code>" in html  # the differing column
    assert "30 &rarr; 99" in html  # before -> after


def test_report_shows_the_four_bucket_counts():
    # id 1 removed, id 5 added, id 4 changed (40 -> 99), ids 2 and 3 unchanged
    a = pd.DataFrame({"id": [1, 2, 3, 4], "val": [10, 20, 30, 40]})
    b = pd.DataFrame({"id": [2, 3, 4, 5], "val": [20, 30, 99, 50]})
    html = reconcile_report(a, b, "id")
    for label in ("added", "removed", "changed", "unchanged"):
        assert f"<th>{label}</th>" in html
    # the unchanged count (2) is rendered in the buckets row
    assert '<td class="delta flat">2</td>' in html


def test_report_surfaces_duplicate_key_note_and_column_diff():
    # id 1 repeats in a (a duplicate key: excluded and noted); only_a / only_b
    # are one-sided columns and land in the column diff, x is the compared one
    a = pd.DataFrame({"id": [1, 1, 2], "x": [5, 5, 5], "only_a": ["p", "q", "r"]})
    b = pd.DataFrame({"id": [1, 2, 3], "x": [5, 9, 1], "only_b": ["s", "t", "u"]})
    html = reconcile_report(a, b, "id")
    assert "duplicate" in html.lower()  # the exclusion is surfaced as a note
    assert "<code>x</code>" in html  # compared
    assert "<code>only_a</code>" in html  # only in before
    assert "<code>only_b</code>" in html  # only in after


def test_report_escapes_hostile_values():
    # a hostile value in a changed cell must be escaped, never injected as markup
    a = pd.DataFrame({"id": [1], "note": ["clean"]})
    b = pd.DataFrame({"id": [1], "note": ["<script>alert(1)</script>"]})
    html = reconcile_report(a, b, "id")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# --- #20: the receipt is a check that can fail, and the report masks PII ---
# The receipt used to be true by construction (set algebra plus a count of the
# same loop it checked), so a broken per-cell comparison still read "verified".
# These pin a receipt that catches a wrong changed count (a misclassification
# that keeps the count is not caught: no total can see it), the legitimate
# frames on which it must stay True, and a report that never shows a raw key or
# value from a column the PII scan flags in either frame.


def _crm_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two CRM extracts keyed on email. Hand-checked buckets: bob is removed,
    dave is added, ann changes phone, plan and backup_contact, carol's phone
    goes from the N/A sentinel to a real number, eve is unchanged. So added 1,
    removed 1, changed 2, unchanged 1. acct carries leading zeros and is not
    PII; backup_contact is only PII in the after frame (an email typed into a
    free-text column), so it is flagged by b alone."""
    a = pd.DataFrame(
        {
            "email": [
                "ann@example.com",
                "bob.smith@example.com",
                "carol_01@mail.example.org",
                "eve@example.com",
            ],
            "acct": ["00417", "00982", "01133", "00050"],
            "phone": ["555-123-4567", "(555) 234-5678", "N/A", "555-222-3333"],
            "plan": ["basic", "pro", "basic", "pro"],
            "backup_contact": ["N/A", "N/A", "N/A", "N/A"],
        }
    )
    b = pd.DataFrame(
        {
            "email": [
                "ann@example.com",
                "carol_01@mail.example.org",
                "eve@example.com",
                "dave+crm@example.net",
            ],
            "acct": ["00417", "01133", "00050", "02210"],
            "phone": ["555-987-6543", "555.345.6789", "555-222-3333", "555 456 7890"],
            "plan": ["pro", "basic", "pro", "basic"],
            "backup_contact": ["ann.w@example.org", "N/A", "N/A", "N/A"],
        }
    )
    return a, b


def test_report_carries_no_raw_value_from_a_pii_flagged_column():
    """Regression for #20. Keyed on an email column, the report printed every
    added, removed and changed email raw, and every changed phone value raw.
    A key or value from a column the PII scan flags in either frame is now
    masked; the counts, the receipt and non-PII values still render."""
    a, b = _crm_frames()
    html = reconcile_report(a, b, "email")

    pii_cols = ("email", "phone", "backup_contact")
    raw = {v for df in (a, b) for c in pii_cols for v in df[c] if v != "N/A"}
    leaked = sorted(v for v in raw if v in html)
    assert leaked == []

    # the masked keys still render in each list: bob removed, dave added, and
    # carol's key in the changed table
    assert '<li class="rem"><code>***@example.com</code></li>' in html
    assert '<li class="add"><code>***@example.net</code></li>' in html
    assert "<td><code>***@mail.example.org</code></td>" in html
    # a changed phone still shows that it changed, masked on both sides
    assert f"{pii.REDACTED} &rarr; {pii.REDACTED}" in html
    # a column the scan does not flag is not masked
    assert "basic &rarr; pro" in html

    # the bucket counts and the receipt are untouched by masking
    assert '<td class="delta add">1</td>' in html
    assert '<td class="delta rem">1</td>' in html
    assert '<td class="delta ">2</td>' in html
    assert '<td class="delta flat">1</td>' in html
    text = _visible_text(html)
    assert "receipt: verified" in text
    assert "partition receipt" not in text


def test_report_masks_only_the_flagged_cell_of_a_composite_key():
    """Regression for #20. A key cell is masked by its column's position in
    the key, so in a (region, email) key the email is masked and the region
    still reads plainly, in the changed table and in the removed list."""
    a = pd.DataFrame(
        {
            "region": ["west", "east", "north"],
            "email": [
                "ann@example.com",
                "ann@example.com",
                "carol_01@mail.example.org",
            ],
            "plan": ["basic", "basic", "pro"],
        }
    )
    b = pd.DataFrame(
        {
            "region": ["west", "east"],
            "email": ["ann@example.com", "ann@example.com"],
            "plan": ["pro", "basic"],
        }
    )
    html = reconcile_report(a, b, ["region", "email"])

    assert "ann@example.com" not in html
    assert "carol_01@mail.example.org" not in html
    assert "<td><code>west, ***@example.com</code></td>" in html
    assert '<li class="rem"><code>north, ***@mail.example.org</code></li>' in html


@pytest.mark.parametrize(
    "broken_equal, reported_changed",
    [
        pytest.param(lambda *_: True, 0, id="says-every-cell-equal"),
        pytest.param(lambda *_: False, 3, id="says-every-cell-differs"),
    ],
)
def test_receipt_fails_when_cell_comparison_is_broken(
    monkeypatch, broken_equal, reported_changed
):
    """Regression for #20. The receipt was true by construction: with the
    per-cell comparison broken, reconcile still said "verified". It now
    recounts changed rows without that comparison, so a wrong changed COUNT
    fails. It checks the total only: a comparison that wrongly marks one row
    changed and another unchanged keeps the count, and the receipt stays True."""
    # invoice 0107's amount is corrected from 5.0 to 50.0: one real change
    a = pd.DataFrame(
        {
            "invoice": ["0042", "0107", "0311"],
            "amount": [19.99, 5.0, 120.5],
            "status": ["paid", "paid", "refunded"],
        }
    )
    b = pd.DataFrame(
        {
            "invoice": ["0042", "0107", "0311"],
            "amount": [19.99, 50.0, 120.5],
            "status": ["paid", "paid", "refunded"],
        }
    )
    monkeypatch.setattr(reconcile, "_cell_equal", broken_equal)

    result = reconcile.reconcile(a, b, "invoice")

    # the broken comparison is in effect: the changed count is wrong
    assert result["counts"]["changed"] == reported_changed
    assert result["receipt"] is False
    assert "NOT verified" in reconcile_report(a, b, "invoice")


@pytest.mark.parametrize(
    "a, b, keys, changed",
    [
        pytest.param(
            pd.DataFrame(
                {
                    "id": ["0042", "0107", "0311"],
                    "discount": pd.Series([None, 0.1, pd.NA], dtype=object),
                    "shipped": pd.to_datetime(["2024-03-01", None, "2024-03-09"]),
                }
            ),
            pd.DataFrame(
                {
                    "id": ["0042", "0107", "0311"],
                    "discount": [float("nan"), 0.1, None],
                    "shipped": pd.to_datetime(["2024-03-01", None, "2024-03-09"]),
                }
            ),
            "id",
            0,
            id="nulls-on-both-sides",
        ),
        pytest.param(
            pd.DataFrame({"id": ["0042", "0107"], "score": [None, 5]}),
            pd.DataFrame({"id": ["0042", "0107"], "score": [None, 6]}),
            "id",
            1,
            id="a-real-change-beside-a-null",
        ),
        pytest.param(
            pd.DataFrame({"sku": ["A-01", "A-02", "B-07"], "qty": [10, 3, 7]}),
            pd.DataFrame({"sku": ["A-01", "A-02", "B-07"], "qty": [10.0, 3.0, 7.0]}),
            "sku",
            0,
            id="int-to-float-drift",
        ),
        pytest.param(
            pd.DataFrame({"sku": ["A-01", "A-02"], "old_price": [1.0, 2.0]}),
            pd.DataFrame({"sku": ["A-01", "A-03"], "price": [1.0, 2.0]}),
            "sku",
            0,
            id="no-shared-non-key-column",
        ),
        pytest.param(
            pd.DataFrame({"id": ["0042"], "val": [1]}),
            pd.DataFrame({"id": ["0107"], "val": [1]}),
            "id",
            0,
            id="no-matched-key",
        ),
    ],
)
def test_receipt_holds_on_frames_that_reconcile_cleanly(a, b, keys, changed):
    """Regression for #20. Pinned beside the receipt that can now fail: two
    nulls, an int that drifted to the same float, and a matched key with
    nothing to compare are not changes, and the receipt stays True on them."""
    result = reconcile.reconcile(a, b, keys)

    assert result["counts"]["changed"] == changed
    assert result["receipt"] is True


# five order ids from one CRM export, kept as text with their leading zeros,
# and a region column with an "N/A" sentinel that does not change between the
# two extracts, so every changed row below differs in its dtype column only
_ORDER_IDS = ["0042", "0107", "0311", "0420", "0533"]
_REGIONS = ["west", "N/A", "east", "west", "N/A"]


@pytest.mark.parametrize(
    "col, before, after, changed_keys",
    [
        # one extract in UTC, the other in local time: the same instant read in
        # another zone is not a change, nor is NaT on both sides. 0311 moved an
        # hour; 0533 went from NaT to a ship time.
        pytest.param(
            "shipped_at",
            pd.to_datetime(
                [
                    "2024-03-01 09:30",
                    None,
                    "2024-03-09 17:00",
                    "2024-03-12 08:00",
                    None,
                ],
                utc=True,
            ),
            pd.to_datetime(
                [
                    "2024-03-01 09:30",
                    None,
                    "2024-03-09 18:00",
                    "2024-03-12 08:00",
                    "2024-03-15 11:45",
                ],
                utc=True,
            ).tz_convert("America/Toronto"),
            [("0311",), ("0533",)],
            id="tz-aware-datetime",
        ),
        # the after extract added a category; a missing plan on both sides is
        # not a change. 0420 upgraded; 0533 lost its plan.
        pytest.param(
            "plan",
            pd.Categorical(
                ["basic", "pro", None, "pro", "basic"], categories=["basic", "pro"]
            ),
            pd.Categorical(
                ["basic", "pro", None, "enterprise", None],
                categories=["basic", "pro", "enterprise"],
            ),
            [("0420",), ("0533",)],
            id="categorical",
        ),
        # a nullable count read back as float: pd.NA against NaN and 3 against
        # 3.0 are not changes. 0420 went 7 to 8; 0533 went missing to 2.
        pytest.param(
            "qty",
            pd.array([10, pd.NA, 3, 7, pd.NA], dtype="Int64"),
            [10.0, float("nan"), 3.0, 8.0, 2.0],
            [("0420",), ("0533",)],
            id="Int64-NA-vs-float-NaN",
        ),
        # pandas string dtype against a plain object column: pd.NA against None
        # is not a change. 0311 changed tier, 0420 lost it, 0533 gained one.
        pytest.param(
            "tier",
            pd.array(["basic", pd.NA, "pro", "pro", pd.NA], dtype="string"),
            pd.Series(["basic", None, "enterprise", float("nan"), "pro"], dtype=object),
            [("0311",), ("0420",), ("0533",)],
            id="string-dtype-NA",
        ),
        # a flag exported as True/False, then as 1/0: the same truth value is
        # not a change (cell values compare by ==, as 3 and 3.0 do; only KEY
        # identity keeps a bool apart from 1/0). 0311 and 0420 flipped.
        pytest.param(
            "active",
            [True, False, True, False, True],
            [1, 0, 0, 1, 1],
            [("0311",), ("0420",)],
            id="bool-vs-1-0",
        ),
        # the same flag as nullable boolean, then as 1/0 with a blank (so the
        # column reads as float): pd.NA against NaN is not a change. 0311 and
        # 0533 flipped.
        pytest.param(
            "active",
            pd.array([True, False, True, pd.NA, False], dtype="boolean"),
            [1.0, 0.0, 0.0, float("nan"), 1.0],
            [("0311",), ("0533",)],
            id="nullable-boolean-vs-float-1-0",
        ),
    ],
)
def test_recount_agrees_with_the_row_comparison_across_dtypes(
    col, before, after, changed_keys
):
    """Regression for #20. The receipt's recount compares the aligned frames
    as object columns, apart from the per-row comparison, so it must read each
    dtype the same way: a null on both sides, or the same value in another
    dtype or zone, is not a change, and a real change (or a null against a
    value) is. On these frames exactly the hand-checked rows changed, the rest
    did not, and the receipt holds."""
    a = pd.DataFrame({"id": _ORDER_IDS, "region": _REGIONS, col: before})
    b = pd.DataFrame({"id": _ORDER_IDS, "region": _REGIONS, col: after})

    result = reconcile.reconcile(a, b, "id")

    assert [change["key"] for change in result["changed"]] == changed_keys
    assert all(change["columns"] == [col] for change in result["changed"])
    assert result["counts"]["changed"] == len(changed_keys)
    assert result["counts"]["unchanged"] == len(_ORDER_IDS) - len(changed_keys)
    assert result["receipt"] is True


def test_report_badge_reads_receipt_not_verified_when_the_recount_disagrees(
    monkeypatch,
):
    """Regression for #20. The receipt is no longer only a partition check, so
    the report labels it "receipt", not "partition receipt", and a recount that
    disagrees with the changed count reads "receipt: NOT verified"."""
    # invoice 0107's amount is corrected from 5.0 to 50.0, and the broken
    # comparison calls every cell equal, so the changed count is 0, not 1
    a = pd.DataFrame({"invoice": ["0042", "0107"], "amount": [19.99, 5.0]})
    b = pd.DataFrame({"invoice": ["0042", "0107"], "amount": [19.99, 50.0]})
    monkeypatch.setattr(reconcile, "_cell_equal", lambda *_: True)

    text = _visible_text(reconcile_report(a, b, "invoice"))

    assert "receipt: NOT verified" in text
    assert "partition receipt" not in text
