"""crivo.load_example() — the README's first block must run offline (arc spec
R1): a deterministic in-code messy frame whose docstring-listed diseases the
engine actually finds, and whose AUTO subset clean() actually fixes."""

import crivo


def test_load_example_is_deterministic_and_its_planted_diseases_are_found():
    frame = crivo.load_example()
    again = crivo.load_example()
    assert frame.equals(again), "same frame every call, forever"
    assert len(frame) == 60

    found = {f["disease"] for f in crivo.diagnose(frame, name="example").findings}
    planted = {1, 4, 6, 7, 9}  # the docstring's promised list
    assert planted <= found, f"missing: {sorted(planted - found)}"

    cleaned, summary = crivo.clean(frame)
    assert len(summary.applied) >= 3, "the AUTO subset must actually fix"
    assert not cleaned.equals(frame)
    assert frame.equals(again), "clean never mutates its input"
    assert "load_example" in crivo.api.__all__


def test_example_clean_clears_both_planted_placeholders():
    """Regression for #26. The docstring plants "-999" and "N/A" in `units`;
    diagnose named only the N/A, and clean left all three -999 cells standing
    as data in the README's first block."""
    frame = crivo.load_example()
    placeholders = [6, 19, 40, 9, 28, 51]  # three "-999", then three "N/A"
    findings = crivo.diagnose(frame, name="example").findings
    (d04,) = [f for f in findings if f["disease"] == 4 and f["columns"] == ["units"]]
    assert "-999" in d04["evidence"]
    assert "N/A" in d04["evidence"]

    cleaned, summary = crivo.clean(frame)

    assert "-999" not in set(cleaned.units.astype(str))
    assert cleaned.units.loc[[6, 19, 40]].isna().tolist() == [True] * 3
    assert cleaned.units.loc[[9, 28, 51]].isna().tolist() == [True] * 3
    # every real count is left exactly as it was
    kept = frame.index.difference(placeholders)
    assert cleaned.units.loc[kept].tolist() == frame.units.loc[kept].tolist()
    assert any(a["disease"] == 4 for a in summary.applied)
