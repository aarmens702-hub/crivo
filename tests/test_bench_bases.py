"""bench/bases.py must emit typed-canonical pristine frames: correctly dtyped,
deterministic per seed, RangeIndex, nothing corrupt.py hasn't touched yet —
everything downstream degrades FROM this state, never starts messier."""

import pandas as pd
import pytest

from bench.bases import transactions, typed_frame

_TYPED_SPEC = {
    "amount": "numeric",
    "count": "int",
    "posted_at": "datetime",
    "category": "category",
    "notes": "text",
    "key": "id",
    "lat": "lat",
    "lon": "lon",
}

_TYPED_DTYPES = {
    "amount": "numeric",
    "count": "numeric",
    "posted_at": "datetime",
    "category": "string",
    "notes": "string",
    "key": "string",
    "lat": "numeric",
    "lon": "numeric",
}

CASES = [
    pytest.param(
        lambda seed, n: transactions(seed, n=n),
        {
            "txn_id": "string",
            "posted_at": "datetime",
            "merchant": "string",
            "category": "string",
            "amount": "numeric",
            "currency": "string",
            "account_no": "string",
            "balance": "numeric",
            "notes": "string",
        },
        id="transactions",
    ),
    pytest.param(
        lambda seed, n: typed_frame(seed, n, _TYPED_SPEC),
        _TYPED_DTYPES,
        id="typed_frame",
    ),
]


def _assert_kind(series, kind):
    if kind == "numeric":
        assert pd.api.types.is_numeric_dtype(series)
    elif kind == "datetime":
        assert pd.api.types.is_datetime64_any_dtype(series)
    elif kind == "string":
        assert pd.api.types.is_string_dtype(series)


@pytest.mark.parametrize("build,dtypes", CASES)
def test_base_is_deterministic_and_typed_canonical(build, dtypes):
    n = 60
    first = build(42, n)
    second = build(42, n)
    assert first.equals(second), "same seed must give byte-identical frames"
    assert not first.equals(build(43, n)), "a different seed must differ"
    assert isinstance(first.index, pd.RangeIndex)
    assert len(first) == n
    assert set(first.columns) == set(dtypes)
    for col, kind in dtypes.items():
        _assert_kind(first[col], kind)
    if "txn_id" in first.columns:
        assert first["txn_id"].is_unique
        assert (first["amount"] > 0).all()
        assert first["merchant"].str.contains(r"[^\x00-\x7f]", regex=True).any(), (
            "merchant vocab must include an accented name for the mojibake disease"
        )
        assert (first["notes"] == "").any(), "notes must include some empty strings"
    if "key" in first.columns:
        assert first["key"].is_unique
        assert (first["amount"] > 0).all()
        assert first["lat"].between(44, 60).all()
        assert first["lon"].between(-140, -60).all()


def test_typed_frame_start_end_pairing_and_end_without_start_raises():
    spec = {"start": "start", "end": "end", "label": "id"}
    frame = typed_frame(7, 40, spec)
    assert (frame["end"] >= frame["start"]).all()
    assert pd.api.types.is_datetime64_any_dtype(frame["start"])
    assert pd.api.types.is_datetime64_any_dtype(frame["end"])
    assert frame["label"].is_unique

    with pytest.raises(ValueError, match="start"):
        typed_frame(7, 10, {"deadline": "end"})


def test_numeric_text_kind_holds_whole_numbers_as_strings():
    """A numeric_text column is whole numbers stored as text, the way a CSV
    column arrives when it is read as strings: the base a typed-in "-999"
    hides in. The id column is seed-free, so a seed change shows in units."""
    spec = {"row_id": "id", "units": "numeric_text"}
    frame = None
    reason = ""
    try:
        frame = typed_frame(42, 200, spec)
    except ValueError as exc:
        reason = str(exc)
    assert frame is not None, f"typed_frame must know the numeric_text kind: {reason}"

    units = frame["units"]
    assert pd.api.types.is_string_dtype(units)
    assert all(isinstance(v, str) and v.isdigit() for v in units)
    assert units.astype(int).between(1, 499).all()
    assert frame.equals(typed_frame(42, 200, spec)), "same seed, same frame"
    assert not frame.equals(typed_frame(43, 200, spec)), "a new seed must differ"
