"""Report.suggest() — keyless starter questions from schema + findings (P3
table stakes: Genie ships per-space suggested questions; ours must work with
no model key, deterministically, and never leak a cell value)."""

import pandas as pd
import pytest

import crivo


def _typed_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": [f"OR{i:04d}" for i in range(40)],
            "placed_at": pd.date_range("2024-01-01", periods=40, freq="D"),
            "region": (["east", "west", "north", "south"] * 10),
            "amount": [round(10.0 + i, 2) for i in range(40)],
        }
    )


def test_suggest_derives_questions_from_schema_deterministically():
    report = crivo.diagnose(_typed_frame(), name="orders")
    first = report.suggest()
    again = report.suggest()

    assert first == again, "same report, same questions — no set/dict order leaks"
    assert 3 <= len(first) <= 5
    assert len(first) == len(set(first)), "no duplicate questions"
    mentioned = " ".join(first)
    assert "amount" in mentioned and "region" in mentioned
    assert report.suggest(k=3) == first[:3], "k caps, preserving order"


def test_suggest_uses_findings_but_never_leaks_cell_values_and_survives_edges():
    dirty = pd.DataFrame(
        {
            "score": ["12.5", "-999", "8.1", "-999", "3.3"] * 8,
            "team": ["red", "blue"] * 20,
        }
    )
    report = crivo.diagnose(dirty, name="scores")
    assert report.findings, "fixture must actually trip the detector"
    questions = report.suggest()
    assert any("score" in q for q in questions), "the defective column is suggested"
    assert all("-999" not in q for q in questions), "cell values must never leak"
    assert all("12.5" not in q for q in questions)

    # edges: single column and empty frames answer with whatever is derivable,
    # never an exception
    single = crivo.diagnose(pd.DataFrame({"only": [1, 2, 3]}), name="single")
    assert isinstance(single.suggest(), list)
    empty = crivo.diagnose(pd.DataFrame(), name="empty")
    assert empty.suggest() == []


# Duplicate headers, as a re-exported sheet leaves them: two columns both
# named "x" with different values (so only header damage fires, not
# duplicated-columns), plus a repeating categorical "y". Eight distinct rows,
# so no column is unique by accident and no duplicate-rows finding joins in.
_DUPLICATE_HEADER_FRAMES = {
    "both-numeric": [
        [7341, 4.25, "zebrafish"],
        [8812, 6.5, "axolotl"],
        [7341, 11.75, "axolotl"],
        [9157, 4.25, "zebrafish"],
        [8812, 11.75, "zebrafish"],
        [9157, 6.5, "axolotl"],
        [7341, 6.5, "zebrafish"],
        [8812, 4.25, "axolotl"],
    ],
    "text-codes-and-numeric": [
        ["0042", 4.25, "zebrafish"],
        ["0078", 6.5, "axolotl"],
        ["0115", 11.75, "axolotl"],
        ["0042", 6.5, "zebrafish"],
        ["0078", 11.75, "zebrafish"],
        ["0115", 4.25, "axolotl"],
        ["0042", 11.75, "axolotl"],
        ["0078", 4.25, "zebrafish"],
    ],
}


@pytest.mark.parametrize(
    "rows", _DUPLICATE_HEADER_FRAMES.values(), ids=_DUPLICATE_HEADER_FRAMES.keys()
)
def test_suggest_survives_duplicate_column_names(rows):
    """Regression for #16. A frame with a repeated column name is exactly what
    crivo flags as header damage; suggest() must still answer with starter
    questions instead of raising on the ambiguous frame[c] lookup."""
    df = pd.DataFrame(rows, columns=["x", "x", "y"])
    report = crivo.diagnose(df, name="dupes")
    assert any(f["slug"] == "header-damage" for f in report.findings), (
        "fixture must actually trip the header-damage detector"
    )

    try:
        qs = report.suggest()
    except ValueError as exc:
        pytest.fail(f"suggest() raised on duplicate column names: {exc}")

    assert len(qs) >= 3
    assert all(isinstance(q, str) for q in qs)
    assert len(qs) == len(set(qs)), "a repeated column name yields no repeat question"
    cells = {str(v) for v in df.to_numpy().ravel()}
    assert not any(cell in q for q in qs for cell in cells), (
        "cell values must never leak"
    )
