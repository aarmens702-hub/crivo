"""Scorer tests (bench/score.py, spec R3/R7) — dense TDD: one test function
per RED step, each table-driven so the whole scorer needs few of them."""

import numpy as np
import pandas as pd
import pytest

from bench import corpus
from bench.score import equivalent, score_detection, score_end_to_end, score_pair
from bench.truth import Cell, Corruption, GroundTruth, frame_sha256


def test_equivalent_type_aware_cases():
    # (a, b, expected) — the missing family collapses to one value; numerics
    # cross-compare within 1e-9 relative tolerance; datetime-like values
    # compare by instant; everything else needs exact equality in the same
    # type family — a str is never a stand-in for a number or a timestamp.
    cases = [
        (None, np.nan, True),
        (np.nan, pd.NaT, True),
        (pd.NA, None, True),
        (5, 5.0, True),
        (5, 5 * (1 + 1e-6), False),  # 5 vs 5.000005 — well outside 1e-9 rel tol
        (5, 5 * (1 + 1e-12), True),  # 5 vs 5.000000000005 — inside 1e-9 rel tol
        (pd.Timestamp("2024-01-01"), np.datetime64("2024-01-01"), True),
        ("12.5", 12.5, False),  # str is never a stand-in for a number
        ("a", "a", True),
        ("a", "a ", False),  # trailing space is a real difference
    ]
    for a, b, expected in cases:
        assert equivalent(a, b) is expected, f"equivalent({a!r}, {b!r})"
        assert equivalent(b, a) is expected, f"equivalent({b!r}, {a!r}) [symmetry]"


def test_score_end_to_end_hand_computed_fixture():
    # 3x2 grid. Dirty cells vs pristine: (0,b) "xx"!="x", (1,a) "two"!=2,
    # (2,b) "zz"!="z" -> D = {(0,b),(1,a),(2,b)}, |D|=3.
    # Cleaned: (0,b) left untouched (a miss); (1,a) fixed to 2 (correct);
    # (2,b) touched but fixed to "ZZ", still != pristine "z" (fixed wrong).
    # C = cells where cleaned != dirty = {(1,a),(2,b)}, |C|=2.
    # K = cells where cleaned == pristine = {(0,a),(1,a),(1,b),(2,a)}, |K|=4.
    # C∩D = {(1,a),(2,b)} -> 2. D∩K = {(1,a)} -> 1. C∩D∩K = {(1,a)} -> 1.
    # dirt_targeting: P = 2/2 = 1.0, R = 2/3, F1 = 2*1*(2/3)/(1+2/3) = 0.8
    # repair:         P = 1/2 = 0.5, R = 1/3, F1 = 2*.5*(1/3)/(.5+1/3) = 0.4
    pristine = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    dirty = pd.DataFrame({"a": [1, "two", 3], "b": ["xx", "y", "zz"]})
    cleaned = pd.DataFrame({"a": [1, 2, 3], "b": ["xx", "y", "ZZ"]})
    truth = GroundTruth(seed=0, base="fixture", n_rows=3, n_cols=2, frame_sha256="x")

    result = score_end_to_end(pristine, dirty, cleaned, truth)

    assert result["dirt_targeting"] == {"precision": 1.0, "recall": 2 / 3, "f1": 0.8}
    assert result["repair"]["precision"] == 0.5
    assert result["repair"]["recall"] == 1 / 3
    assert result["repair"]["f1"] == 2 * 0.5 * (1 / 3) / (0.5 + 1 / 3)  # == 0.4
    assert result["counts"] == {"dirty": 3, "changed": 2, "repaired": 1}


def test_score_end_to_end_oracle_and_no_op_invariants():
    pristine = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    dirty = pd.DataFrame({"a": [1, 99], "b": ["x", "y"]})  # D = {(1,a)}, |D|=1
    truth = GroundTruth(seed=0, base="fixture", n_rows=2, n_cols=2, frame_sha256="x")

    # Oracle: the cleaner produces the pristine frame exactly -> every dirty
    # cell got touched and landed correct, so repair P = R = 1.0.
    oracle = score_end_to_end(pristine, dirty, pristine.copy(), truth)
    assert oracle["repair"]["precision"] == 1.0
    assert oracle["repair"]["recall"] == 1.0
    assert oracle["repair"]["f1"] == 1.0

    # No-op: the cleaner changes nothing, so C = set() -> both precisions are
    # 0/0 (None, the zero-denominator rule), while both recalls have a real,
    # nonzero denominator (|D|=1) and come out 0.0 — never a crash either way.
    # F1 is 2*TP/(|C|+|D|) = 0/(0+1) = 0.0: a cleaner that left real dirt
    # alone scored a measured zero, not "undefined" (#86).
    noop = score_end_to_end(pristine, dirty, dirty.copy(), truth)
    assert noop["dirt_targeting"]["precision"] is None
    assert noop["dirt_targeting"]["recall"] == 0.0
    assert noop["dirt_targeting"]["f1"] == 0.0
    assert noop["repair"]["precision"] is None
    assert noop["repair"]["recall"] == 0.0
    assert noop["repair"]["f1"] == 0.0
    assert noop["counts"] == {"dirty": 1, "changed": 0, "repaired": 0}


def test_score_detection_counts_and_disease_zero_exclusion():
    # disease 1: finding matches truth on "amount" -> TP. disease 2: truth
    # has a corruption but no finding claims it -> FN. disease 3: a finding
    # claims it but truth has no such corruption -> FP (wrong disease).
    # disease 0 (external/unknown) appears on both sides and must vanish.
    detect_result = {
        "findings": [
            {"disease": 1, "columns": ["amount"]},
            {"disease": 3, "columns": ["amount"]},
            {"disease": 0, "columns": ["x"]},
        ]
    }
    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=1,
        n_cols=1,
        frame_sha256="x",
        corruptions=[
            Corruption(disease=1, columns=("amount",), granularity="cell"),
            Corruption(disease=2, columns=("date",), granularity="cell"),
            Corruption(disease=0, columns=("x",), granularity="cell"),
        ],
    )

    result = score_detection(detect_result, truth)

    # Matching here is one-to-one, so both numerators agree and every metric
    # value is the same as before the numerators were split; what changed is
    # the schema, which now names each numerator and its own denominator and
    # carries no count that would fit either ratio. Misses are a subtraction:
    # findings missed = n_truth - matched_truth, spurious = n_findings -
    # matched_findings.
    # disease 1: 1 of 1 finding matched, 1 of 1 corruption matched
    #            -> P=1/1=1.0, R=1/1=1.0, F1=1.0
    assert result["per_disease"]["1"] == {
        "matched_findings": 1,
        "n_findings": 1,
        "matched_truth": 1,
        "n_truth": 1,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }
    # disease 2: no findings at all, 0 of 1 corruption matched
    #            -> P: 0/0 -> None, R=0/1=0.0, F1 = 2*0/(0+1) = 0.0
    #            (a silent detector on real dirt is a measured zero, #86)
    assert result["per_disease"]["2"] == {
        "matched_findings": 0,
        "n_findings": 0,
        "matched_truth": 0,
        "n_truth": 1,
        "precision": None,
        "recall": 0.0,
        "f1": 0.0,
    }
    # disease 3: 0 of 1 finding matched, no corruptions at all
    #            -> P=0/1=0.0, R: 0/0 -> None, F1 = 2*0/(1+0) = 0.0
    assert result["per_disease"]["3"] == {
        "matched_findings": 0,
        "n_findings": 1,
        "matched_truth": 0,
        "n_truth": 0,
        "precision": 0.0,
        "recall": None,
        "f1": 0.0,
    }
    assert "0" not in result["per_disease"]
    # macro_f1: diseases present in truth (excluding 0) are {1, 2}; disease
    # 2's None f1 counts as 0.0 in the average -> (1.0 + 0.0) / 2 = 0.5
    assert result["macro_f1"] == 0.5
    # micro: matched_findings=1 over 2 findings -> P=0.5; matched_truth=1 over
    # 2 truth corruptions -> R=0.5; F1=0.5
    assert result["micro"] == {"precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_score_detection_recall_counts_truth_not_findings():
    # Matching is not one-to-one: three findings all match the SAME corruption,
    # and a second corruption is matched by nothing. Only 1 of 2 corruptions was
    # recalled, so recall is 0.5. Counting the recall numerator over findings
    # gives 3/(3+1) = 0.75, the inflation this test exists to forbid.
    detect_result = {
        "findings": [
            {"disease": 1, "columns": ["amount"]},
            {"disease": 1, "columns": ["amount"]},
            {"disease": 1, "columns": ["amount"]},
        ]
    }
    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=1,
        n_cols=1,
        frame_sha256="x",
        corruptions=[
            Corruption(disease=1, columns=("amount",), granularity="cell"),
            Corruption(disease=1, columns=("date",), granularity="cell"),
        ],
    )

    result = score_detection(detect_result, truth)
    d1 = result["per_disease"]["1"]

    # precision numerator is over findings, recall numerator is over truth
    assert (d1["matched_findings"], d1["n_findings"]) == (3, 3)
    assert (d1["matched_truth"], d1["n_truth"]) == (1, 2)

    assert d1["precision"] == 1.0
    assert d1["recall"] == 0.5
    assert d1["f1"] == 2 * 1.0 * 0.5 / 1.5

    # the micro aggregate must use the same per-ratio numerators
    assert result["micro"]["precision"] == 1.0
    assert result["micro"]["recall"] == 0.5

    # The metric fields are only half the artifact: bench/results/*.json
    # publishes these counts too, and a reader recomputing from them has to
    # land on the published ratio. A count of matched FINDINGS paired with a
    # truth-side miss count rebuilds 3/(3+1) = 0.75, the recall this scorer
    # retracted, from a file whose metric fields are correct. So every count
    # names the universe it was counted over, and no field IS that number.
    # The comment here used to go one further and say no such pair could be
    # drawn at all; the test below that one shows it can be, exactly.
    assert set(d1) == {
        "matched_findings",
        "n_findings",
        "matched_truth",
        "n_truth",
        "precision",
        "recall",
        "f1",
    }
    assert d1["matched_findings"] / d1["n_findings"] == d1["precision"]
    assert d1["matched_truth"] / d1["n_truth"] == d1["recall"]


def test_the_retracted_recall_is_constructible_from_the_published_counts():
    """The wave 1 docstring and commit message claimed a reader "cannot land
    on the retracted number by reaching for a plausible-looking pair". That
    claim is false, and it is the kind of false claim that stops the next
    reader checking: matched_findings over matched_findings plus the truth
    side's misses rebuilds the retracted 0.75 exactly, from the four counts
    this scorer publishes. The counts stay published, because hiding the
    inputs of a wrong ratio would hide the inputs of the right one too. What
    has to go is the guarantee."""
    detect_result = {
        "findings": [
            {"disease": 1, "columns": ["amount"]},
            {"disease": 1, "columns": ["amount"]},
            {"disease": 1, "columns": ["amount"]},
        ]
    }
    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=1,
        n_cols=1,
        frame_sha256="x",
        corruptions=[
            Corruption(disease=1, columns=("amount",), granularity="cell"),
            Corruption(disease=1, columns=("date",), granularity="cell"),
        ],
    )

    d1 = score_detection(detect_result, truth)["per_disease"]["1"]
    misses = d1["n_truth"] - d1["matched_truth"]
    retracted = d1["matched_findings"] / (d1["matched_findings"] + misses)

    assert retracted == 0.75
    assert d1["recall"] == 0.5, "the published recall is still the honest one"

    doc = score_detection.__doc__ or ""
    assert "cannot land on" not in doc, "the retracted number is constructible"
    assert "matched_findings + (n_truth - matched_truth)" in doc, (
        "the docstring has to name the wrong pairing it cannot prevent"
    )


def test_a_finding_that_names_no_column_cannot_recall_a_column_scoped_disease():
    """The empty-columns wildcard was written for the whole-row diseases and
    then applied to every disease in both directions, so ONE finding naming no
    column recalled every cell-scoped corruption of its disease and published
    recall 1.0 off a finding that located nothing."""
    detect_result = {"findings": [{"disease": 1, "columns": []}]}
    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=1,
        n_cols=3,
        frame_sha256="x",
        corruptions=[
            Corruption(disease=1, columns=("amount",), granularity="cell"),
            Corruption(disease=1, columns=("date",), granularity="cell"),
            Corruption(disease=1, columns=("qty",), granularity="cell"),
        ],
    )

    d1 = score_detection(detect_result, truth)["per_disease"]["1"]

    assert (d1["matched_truth"], d1["n_truth"]) == (0, 3)
    assert d1["recall"] == 0.0
    assert (d1["matched_findings"], d1["n_findings"]) == (0, 1)
    assert d1["precision"] == 0.0


def test_a_whole_row_disease_still_matches_the_finding_that_names_no_column():
    """The guard against over-correcting the test above. crivo's own d09
    finding carries `columns: []` because duplicate rows are not about any one
    column, while the injector records every column of the frame. That pair is
    a real match and closing the wildcard entirely would score crivo's most
    reliable detector at zero."""
    detect_result = {"findings": [{"disease": 9, "columns": []}]}
    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=2,
        n_cols=2,
        frame_sha256="x",
        corruptions=[
            Corruption(disease=9, columns=("a", "b"), granularity="row", rows=(2,)),
        ],
    )

    d9 = score_detection(detect_result, truth)["per_disease"]["9"]

    assert d9["recall"] == 1.0
    assert d9["precision"] == 1.0


def test_equivalent_numpy_bool_is_a_bool_not_a_number():
    # np.bool_ is not a Python bool and (in numpy 2) not an np.integer either,
    # so an unguarded numpy True falls to plain == and compares equal to 1.
    # A bool compares only to another bool: True and 1 are not the same fix.
    assert equivalent(np.bool_(True), 1) is False
    assert equivalent(1, np.bool_(True)) is False
    assert equivalent(np.bool_(False), 0) is False
    assert equivalent(0, np.bool_(False)) is False
    # ...and a numpy bool IS a bool, so it matches its Python twin.
    assert equivalent(np.bool_(True), True) is True
    assert equivalent(True, np.bool_(True)) is True
    assert equivalent(np.bool_(True), np.bool_(True)) is True
    assert equivalent(np.bool_(True), np.bool_(False)) is False
    assert equivalent(np.bool_(True), False) is False


def test_score_pair_keyless_integration_smoke():
    # Real detect_all + clean, no LLM key needed — just structural correctness
    # of the composition and sane metric ranges, not exact detector recall.
    pristine = pd.DataFrame(
        {
            "amount": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0],
            "name": [
                "alice",
                "bob",
                "carol",
                "dave",
                "erin",
                "frank",
                "grace",
                "heidi",
                "ivan",
                "judy",
            ],
        }
    )
    dirty = pristine.copy()
    dirty.loc[0, "name"] = "  alice  "  # whitespace damage (d06)
    dirty.loc[1, "amount"] = -999  # sentinel missing (d04)

    truth = GroundTruth(
        seed=1,
        base="fixture",
        n_rows=len(pristine),
        n_cols=len(pristine.columns),
        frame_sha256=frame_sha256(dirty),
        corruptions=[
            Corruption(
                disease=6,
                columns=("name",),
                granularity="cell",
                cells=(
                    Cell(row=0, column="name", original="alice", corrupted="  alice  "),
                ),
            ),
            Corruption(
                disease=4,
                columns=("amount",),
                granularity="cell",
                cells=(Cell(row=1, column="amount", original=20.0, corrupted=-999),),
            ),
        ],
    )

    result = score_pair(pristine, dirty, truth)

    assert set(result) == {
        "detection",
        "end_to_end",
        "verification",
        "attempted_diseases",
        "not_attempted_diseases",
    }
    assert set(result["detection"]) == {"per_disease", "macro_f1", "micro"}
    assert set(result["end_to_end"]) == {"dirt_targeting", "repair", "counts"}
    assert set(result["verification"]) == {
        "attempted",
        "applied",
        "survived_rate",
        "needs_review",
    }

    def _bounded(node):  # every float in this schema is a ratio metric
        if isinstance(node, dict):
            for v in node.values():
                _bounded(v)
        elif isinstance(node, list):
            for v in node:
                _bounded(v)
        elif isinstance(node, float):
            assert 0.0 <= node <= 1.0, node

    _bounded(result)


def test_string_space_equivalence_scores_external_pairs():
    # Raha pairs are all-string; crivo.clean re-types. Typed equivalence makes
    # external repair structurally unwinnable (str is never a number), so
    # external scoring needs string-space equality: blank == missing,
    # "12.0" == "12", but "02115" != "2115" (leading zeros are disease 22).
    import numpy as np
    import pandas as pd

    from bench.score import equivalent_str, score_end_to_end
    from bench.truth import GroundTruth, frame_sha256

    cases = [
        ("12.0", "12", True),
        ("12.0", 12.0, True),  # typed cleaned value vs string pristine
        ("02115", "2115", False),
        ("  x ", "x", True),
        ("", np.nan, True),
        (pd.Timestamp("2004-01-01"), "2004-01-01", True),
        ("a", "b", False),
    ]
    for a, b, want in cases:
        assert equivalent_str(a, b) is want, (a, b)
        assert equivalent_str(b, a) is want, (b, a)

    # 2x2 string pair: cell (0,'n') dirty "12,0"->cleaned typed 12.0 == "12" ✓
    # cell (1,'d') dirty "bad"->cleaned NaT vs pristine "2004-01-01" ✗ (missed)
    pristine = pd.DataFrame({"n": ["12", "3"], "d": ["2004-01-01", "2004-01-02"]})
    dirty = pd.DataFrame({"n": ["12,0", "3"], "d": ["2004-01-01", "bad"]})
    cleaned = pd.DataFrame(
        {"n": [12.0, 3.0], "d": [pd.Timestamp("2004-01-01"), pd.NaT]}
    )
    truth = GroundTruth(
        seed=0, base="external", n_rows=2, n_cols=2, frame_sha256=frame_sha256(dirty)
    )
    result = score_end_to_end(
        pristine, dirty, cleaned, truth, values_equal=equivalent_str
    )
    # D = {(0,n),(1,d)}; C = {(0,n),(1,d)}; repaired = {(0,n)} only
    assert result["counts"] == {"dirty": 2, "changed": 2, "repaired": 1}
    assert result["repair"]["precision"] == 0.5
    assert result["repair"]["recall"] == 0.5


def _score_export(start: str, edits: dict) -> dict:
    """Score a cleaner on a small messy export. `start` picks the frame the
    cleaner is handed ("dirty": four planted cells; "pristine": no dirt at
    all) and `edits` are the cells the cleaner rewrites, {(row, column):
    value}. The export is typed the way a CSV reader leaves it: zero-padded
    customer ids and ISO dates held as text, money as floats, a town. Every
    value is invented; none is from the Raha data."""
    pristine = pd.DataFrame(
        {
            "cust_id": ["00412", "00977", "01530", "03218"],
            "signup": ["2024-01-05", "2024-02-11", "2024-03-02", "2024-03-30"],
            "amount": [1200.0, 85.5, 40.0, 310.25],
            "town": ["Quarnby", "Velloch", "Tarrisford", "Quarnby"],
        }
    )
    dirty = pristine.copy()
    if start == "dirty":
        dirty.loc[3, "cust_id"] = "3218"  # leading zero lost (d22)
        dirty.loc[1, "signup"] = "11/02/2024"  # a second date format (d03)
        dirty.loc[2, "amount"] = -999.0  # a placeholder for missing (d04)
        dirty.loc[0, "town"] = "  Quarnby "  # stray whitespace (d06)
        # D = {(3,cust_id), (1,signup), (2,amount), (0,town)}, |D| = 4
    cleaned = dirty.copy()
    for (row, column), value in edits.items():
        cleaned.loc[row, column] = value
    truth = GroundTruth(seed=0, base="fixture", n_rows=4, n_cols=4, frame_sha256="x")
    return score_end_to_end(pristine, dirty, cleaned, truth)


# (frame the cleaner gets, the cells it rewrites, dirt-targeting F1, repair F1,
#  counts). F1 = 2*TP/(|C|+|D|): TP is C∩D for dirt targeting, C∩D∩K for repair.
_MEASURED_ZEROS = [
    # changes nothing: C = {}, |D| = 4
    #   dirt:   P = 0/0 None, R = 0/4 = 0.0, F1 = 2*0/(0+4) = 0.0
    #   repair: P = 0/0 None, R = 0/4 = 0.0, F1 = 2*0/(0+4) = 0.0
    pytest.param(
        "dirty",
        {},
        0.0,
        0.0,
        {"dirty": 4, "changed": 0, "repaired": 0},
        id="changes-nothing-on-real-dirt",
    ),
    # re-cases a clean town and nudges a clean amount: C = {(1,town),
    # (0,amount)}, C∩D = {}
    #   dirt:   P = 0/2, R = 0/4, P + R = 0, F1 = 2*0/(2+4) = 0.0
    #   repair: P = 0/2, R = 0/4, P + R = 0, F1 = 2*0/(2+4) = 0.0
    pytest.param(
        "dirty",
        {(1, "town"): "VELLOCH", (0, "amount"): 1200.5},
        0.0,
        0.0,
        {"dirty": 4, "changed": 2, "repaired": 0},
        id="changes-only-clean-cells",
    ),
    # clears the -999 to NaN (truth held 40.0) and pads "3218" to the wrong
    # width (truth "03218"): C = {(2,amount), (3,cust_id)} ⊆ D, K∩D = {}
    #   dirt:   P = 2/2 = 1.0, R = 2/4 = 0.5, F1 = 2*2/(2+4) = 2/3
    #   repair: P = 0/2, R = 0/4, P + R = 0, F1 = 2*0/(2+4) = 0.0
    pytest.param(
        "dirty",
        {(2, "amount"): np.nan, (3, "cust_id"): "003218"},
        2 / 3,
        0.0,
        {"dirty": 4, "changed": 2, "repaired": 0},
        id="changes-dirty-cells-repairs-none",
    ),
    # no dirt at all, and the cleaner re-cases a clean town: D = {},
    # C = {(1,town)}
    #   dirt:   P = 0/1 = 0.0, R = 0/0 None, F1 = 2*0/(1+0) = 0.0
    #   repair: P = 0/1 = 0.0, R = 0/0 None, F1 = 2*0/(1+0) = 0.0
    pytest.param(
        "pristine",
        {(1, "town"): "VELLOCH"},
        0.0,
        0.0,
        {"dirty": 0, "changed": 1, "repaired": 0},
        id="damages-a-frame-with-no-dirt",
    ),
]


@pytest.mark.parametrize("start, edits, dirt_f1, repair_f1, counts", _MEASURED_ZEROS)
def test_a_cleaner_that_repairs_nothing_scores_a_measured_zero(
    start, edits, dirt_f1, repair_f1, counts
):
    """Regression for #86. A cleaner that changed nothing on real dirt, or
    changed cells and repaired none, scored F1 None: precision was 0/0, or
    P + R was 0, and `_f1` called both undefined. The bench's repair mean
    drops a None, so a total miss left the mean instead of pulling it down.
    F1 is 2*TP/(|C|+|D|), and that is 0.0 whenever anything was dirty or
    anything changed."""
    result = _score_export(start, edits)

    assert result["counts"] == counts
    assert result["dirt_targeting"]["f1"] == pytest.approx(dirt_f1)
    assert result["repair"]["f1"] == pytest.approx(repair_f1)


def test_nothing_dirty_and_nothing_changed_is_the_one_undefined_f1():
    """Regression for #86, the pin beside the zeros above. With nothing to
    repair and nothing done, every ratio is 0/0 and F1 stays None. A scorer
    that answered 0.0 here would mark a cleaner down for leaving a clean frame
    alone."""
    result = _score_export("pristine", {})

    assert result["counts"] == {"dirty": 0, "changed": 0, "repaired": 0}
    for family in ("dirt_targeting", "repair"):
        assert result[family] == {"precision": None, "recall": None, "f1": None}


@pytest.mark.parametrize(
    "start, edits, precision, recall",
    [
        # C = {}: both precisions are 0/0; |D| = 4, so both recalls are 0/4
        pytest.param("dirty", {}, None, 0.0, id="nothing-changed"),
        # D = {}: both recalls are 0/0; |C| = 1, so both precisions are 0/1
        pytest.param(
            "pristine", {(1, "town"): "VELLOCH"}, 0.0, None, id="nothing-dirty"
        ),
    ],
)
def test_an_empty_denominator_still_leaves_its_ratio_undefined(
    start, edits, precision, recall
):
    """Regression for #86. Only F1 reads a missing side as 0.0. Precision with
    nothing changed and recall with nothing dirty are still 0/0, and the JSON
    keeps saying so with None, so a reader can tell "changed nothing" from
    "changed the wrong cells"."""
    result = _score_export(start, edits)

    for family in ("dirt_targeting", "repair"):
        assert (result[family]["precision"], result[family]["recall"]) == (
            precision,
            recall,
        ), family


def test_a_detector_that_flags_the_wrong_column_scores_f1_zero():
    """Regression for #86. P = R = 0 is a measured miss: the detector flagged
    mixed dates on `amount` while truth planted them on `signup`. Per-disease
    and micro F1 read 0.0, not None."""
    detect_result = {"findings": [{"disease": 3, "columns": ["amount"]}]}
    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=4,
        n_cols=4,
        frame_sha256="x",
        corruptions=[Corruption(disease=3, columns=("signup",), granularity="cell")],
    )

    result = score_detection(detect_result, truth)
    d3 = result["per_disease"]["3"]

    # 0 of 1 finding matched, 0 of 1 corruption matched:
    # P = 0/1, R = 0/1, F1 = 2*0/(1+1) = 0.0
    assert (d3["precision"], d3["recall"]) == (0.0, 0.0)
    assert d3["f1"] == 0.0
    assert result["micro"] == {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    assert result["macro_f1"] == 0.0


# Row-level scoring (#256). A row corruption's `rows` are positions in the
# DIRTY frame, and every row injector appends at the end, so the cell grid
# (rows < n_rows) never sees them. The row score counts the planted rows that
# are gone from `cleaned`, by value and copy by copy:
#   removed = max(0, len(dirty) - len(cleaned))
#   still_there(v) = min(planted(v), max(0, cleaned(v) - kept(v))), where
#     kept(v) counts value v among the unplanted dirty rows
#   planted_removed = min(removed, sum(planted(v) - still_there(v)))
#   R = planted_removed / planted, P = planted_removed / removed (None when
#   nothing was removed), F1 by `_f1`

# (SMOKE entry, planted rows k, dirty rows) for every SMOKE entry that plants
# a row corruption; the planted rows are the last k dirty positions
_ROW_ENTRIES = [
    pytest.param("tx-dup-rows", 25, 275, id="d09-exact-duplicates"),
    pytest.param("tx-near-dups", 25, 275, id="d10-near-duplicates"),
    pytest.param("tx-aggregate-row", 1, 251, id="d21-total-row"),
    pytest.param("tx-header-echo", 2, 252, id="d24-header-echo-and-footer"),
    # 35 d09 duplicates + 1 d21 total row, behind cell damage (d07, d15) and
    # a renamed first column (d18), so matching runs without that column
    pytest.param("tx-compound-hard", 36, 386, id="compound-hard"),
]


def _row_case(name: str, k: int, n_dirty: int):
    """(pristine, dirty, truth, planted positions) for one SMOKE row entry,
    checked against the shape the expected values were worked out on."""
    entry = next(e for e in corpus.SMOKE if e["name"] == name)
    pristine, dirty, truth = corpus.build(entry)
    planted = sorted(
        {r for c in truth.corruptions if c.granularity == "row" for r in c.rows}
    )
    assert (len(planted), len(dirty)) == (k, n_dirty), f"{name}: the corpus moved"
    return pristine, dirty, truth, planted


def _rows_of(pristine, dirty, cleaned, truth) -> dict:
    result = score_end_to_end(pristine, dirty, cleaned, truth)
    assert "rows" in result, "no row score on a dataset that plants rows"
    return result["rows"]


def _hand_back(frame: pd.DataFrame, how: str, tmp_path=None) -> pd.DataFrame:
    """The frame a cleaner returns, rebuilt the ways real cleaners rebuild it."""
    if how == "as-is":
        return frame
    if how == "shuffled-reset":
        # new order and a fresh RangeIndex: neither a position nor an index
        # label still names the dirty row it came from
        return frame.sample(frac=1, random_state=7).reset_index(drop=True)
    if how == "retyped":
        # every column as object and every missing value as None: the same
        # values in other types (NaN, NaT and None are one missing value)
        return frame.astype(object).where(frame.notna(), None)
    if how == "parquet":
        path = tmp_path / "cleaned.parquet"
        frame.to_parquet(path)
        return pd.read_parquet(path)
    raise ValueError(how)


def _swap_a_planted_row_for_a_good_one(pristine, dirty, truth, planted):
    """Remove every planted row but the last, plus the first good row whose
    values are unique in dirty, so no planted row shares its value."""
    shared = [c for c in pristine.columns if c in dirty.columns]
    unique = ~dirty[shared].duplicated(keep=False)
    good = next(row for row in range(truth.n_rows) if unique.iat[row])
    return dirty.drop(index=dirty.index[[*planted[:-1], good]])


@pytest.mark.parametrize("name, k, n_dirty", _ROW_ENTRIES)
def test_the_oracle_removes_every_planted_row_and_the_no_op_none(name, k, n_dirty):
    """Regression for #256. The cell grid stops at n_rows, so on a row
    dataset the oracle and the no-op scored the same: every repair number
    None, and both counted as solved. The row score tells them apart."""
    pristine, dirty, truth, _ = _row_case(name, k, n_dirty)

    # oracle: cleaned = pristine, n_rows rows, so removed = n_dirty - n_rows
    # = k, and no planted value is in pristine: planted_removed = min(k, k)
    #   P = k/k = 1.0, R = k/k = 1.0, F1 = 1.0
    assert _rows_of(pristine, dirty, pristine, truth) == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "planted": k,
        "removed": k,
        "planted_removed": k,
    }
    # no-op: removed = 0, so planted_removed = min(0, ...) = 0
    #   P = 0/0 None, R = 0/k = 0.0, F1 = 0.0 (a miss on real dirt, #86)
    assert _rows_of(pristine, dirty, dirty.copy(), truth) == {
        "precision": None,
        "recall": 0.0,
        "f1": 0.0,
        "planted": k,
        "removed": 0,
        "planted_removed": 0,
    }


@pytest.mark.parametrize("how", ["as-is", "shuffled-reset", "retyped"])
@pytest.mark.parametrize("name, k, n_dirty", _ROW_ENTRIES)
def test_removing_a_good_row_instead_of_a_planted_one_loses_precision(
    name, k, n_dirty, how
):
    """Regression for #256. The cleaner removes as many rows as were
    planted, but one is a good row and one planted row stays. Counted by
    length, position or a reset index label that looks perfect, so rows
    match by value, and the planted row left behind costs recall and
    precision both."""
    pristine, dirty, truth, planted = _row_case(name, k, n_dirty)
    swapped = _swap_a_planted_row_for_a_good_one(pristine, dirty, truth, planted)

    rows = _rows_of(pristine, dirty, _hand_back(swapped, how), truth)

    # removed = (k - 1) planted + 1 good = k. The planted row left, value v,
    # is in cleaned once more than among the unplanted dirty rows, so
    # still_there(v) = 1; the good row was unique, so planted(good) = 0.
    # planted_removed = min(k, k - 1) = k - 1, and R = P = F1 = (k - 1)/k:
    #   d09, d10: 24/25 = 0.96; d21: 0/1 = 0.0; d24: 1/2; compound: 35/36
    assert (rows["planted"], rows["removed"], rows["planted_removed"]) == (
        k,
        k,
        k - 1,
    )
    assert rows["recall"] == pytest.approx((k - 1) / k)
    assert rows["precision"] == pytest.approx((k - 1) / k)
    assert rows["f1"] == pytest.approx((k - 1) / k)
    assert rows["f1"] < 1.0


@pytest.mark.parametrize("name, k, n_dirty", _ROW_ENTRIES)
def test_a_cleaner_that_drops_every_row_loses_precision(name, k, n_dirty):
    """Regression for #256. Removing everything removes the planted rows
    too, so recall alone would call it perfect; precision marks it down."""
    pristine, dirty, truth, _ = _row_case(name, k, n_dirty)

    rows = _rows_of(pristine, dirty, dirty.iloc[:0], truth)

    # removed = n_dirty and nothing is left: planted_removed = min(n_dirty,
    # k) = k, so R = k/k = 1.0, P = k/n_dirty, F1 = 2k/(k + n_dirty):
    #   d09, d10: P = 25/275 = 1/11, F1 = 50/300 = 1/6
    #   d21: P = 1/251, F1 = 2/252; d24: P = 2/252, F1 = 4/254
    #   compound: P = 36/386, F1 = 72/422 = 0.171
    assert (rows["planted"], rows["removed"], rows["planted_removed"]) == (
        k,
        n_dirty,
        k,
    )
    assert rows["recall"] == 1.0
    assert rows["precision"] == pytest.approx(k / n_dirty)
    assert rows["f1"] == pytest.approx(2 * k / (k + n_dirty))
    assert rows["f1"] < 0.2


@pytest.mark.parametrize("how", ["as-is", "shuffled-reset"])
@pytest.mark.parametrize("keep", ["first", "last"])
def test_dropping_the_exact_duplicates_is_a_full_row_repair(keep, how):
    """Regression for #256, the pin beside the misses above: the repair d09
    asks for, `drop_duplicates`, scores row F1 1.0. A copy and its source
    have the same values, so keeping the later one is the same repair by
    value (what its shifted positions do to cells is the cell grid's call)."""
    pristine, dirty, truth, _ = _row_case("tx-dup-rows", 25, 275)

    rows = _rows_of(
        pristine, dirty, _hand_back(dirty.drop_duplicates(keep=keep), how), truth
    )

    # 25 copies of 22 sources (row 82 copied twice, row 135 three times) and
    # no duplicate in pristine, so drop_duplicates removes 25 rows either
    # way. Each copied value v is then in cleaned once, as often as among the
    # unplanted rows: still_there(v) = 0, planted_removed = min(25, 25) = 25
    #   P = 25/25 = 1.0, R = 25/25 = 1.0, F1 = 1.0
    assert rows == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "planted": 25,
        "removed": 25,
        "planted_removed": 25,
    }


def _blank_the_planted_rows(frame, planted):
    blanked = frame.astype(object)
    blanked.iloc[planted] = None
    return blanked


_KEEPS_EVERY_ROW = {
    "wipes-a-column": lambda f, planted: f.assign(amount=np.nan),
    "canonicalizes-a-column": lambda f, planted: f.assign(
        merchant=f["merchant"].str.upper()
    ),
    "sorts-and-resets": lambda f, planted: f.sort_values(
        "merchant", kind="stable"
    ).reset_index(drop=True),
    "renames-every-column": lambda f, planted: f.set_axis(
        [f"col_{i}" for i in range(f.shape[1])], axis=1
    ),
    "drops-a-column": lambda f, planted: f.drop(columns="merchant"),
    "makes-dates-tz-aware": lambda f, planted: f.assign(
        posted_at=pd.to_datetime(f["posted_at"], errors="coerce", utc=True)
    ),
    "blanks-the-planted-rows": _blank_the_planted_rows,
}


@pytest.mark.parametrize("rewrite", list(_KEEPS_EVERY_ROW))
@pytest.mark.parametrize("name, k, n_dirty", _ROW_ENTRIES)
def test_a_rewrite_that_removes_no_row_removes_no_planted_row(
    name, k, n_dirty, rewrite
):
    """Regression for #256. Rewriting values is not removing rows: a cleaner
    that keeps every row scores row recall 0, however much it changed. The
    planted values may be gone from cleaned (blanked, renamed away, made
    tz-aware), and the cap at `removed` is what holds recall at 0. Matching
    must also survive the rewrite without raising."""
    pristine, dirty, truth, planted = _row_case(name, k, n_dirty)
    cleaned = _KEEPS_EVERY_ROW[rewrite](dirty.copy(), planted)
    assert len(cleaned) == len(dirty)

    rows = _rows_of(pristine, dirty, cleaned, truth)

    # removed = 0, so planted_removed = min(0, ...) = 0 whatever the values:
    #   P = 0/0 None, R = 0/k = 0.0, F1 = 0.0
    assert rows == {
        "precision": None,
        "recall": 0.0,
        "f1": 0.0,
        "planted": k,
        "removed": 0,
        "planted_removed": 0,
    }


@pytest.mark.parametrize("how", ["shuffled-reset", "parquet"])
@pytest.mark.parametrize("name, k, n_dirty", _ROW_ENTRIES)
def test_the_oracle_scores_full_rows_however_it_is_handed_back(
    name, k, n_dirty, how, tmp_path
):
    """Regression for #256. A cleaner that rebuilt the pristine frame (new
    order, fresh index, or written out and read back) still removed exactly
    the planted rows."""
    pristine, dirty, truth, _ = _row_case(name, k, n_dirty)

    rows = _rows_of(pristine, dirty, _hand_back(pristine, how, tmp_path), truth)

    # as for the oracle: removed = k, no planted value is in pristine, so
    # planted_removed = k and P = R = F1 = 1.0
    assert rows == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "planted": k,
        "removed": k,
        "planted_removed": k,
    }


@pytest.mark.parametrize(
    "name, k, n_dirty",
    # tx-header-echo is left out: its dirty frame mixes header text into the
    # number and date columns, which parquet refuses to write
    [p for p in _ROW_ENTRIES if p.id != "d24-header-echo-and-footer"],
)
def test_a_parquet_round_trip_keeps_the_good_row_miss(name, k, n_dirty, tmp_path):
    """Regression for #256. Read back from parquet, the planted row the
    swap left behind still matches its dirty copy, so it still counts as
    there: the miss stays (k - 1)/k and doesn't round up to a full repair."""
    pristine, dirty, truth, planted = _row_case(name, k, n_dirty)
    swapped = _swap_a_planted_row_for_a_good_one(pristine, dirty, truth, planted)

    rows = _rows_of(pristine, dirty, _hand_back(swapped, "parquet", tmp_path), truth)

    # as for the swap above: removed = k, planted_removed = k - 1
    #   R = P = (k - 1)/k: d09, d10: 24/25; d21: 0/1; compound: 35/36
    assert (rows["removed"], rows["planted_removed"]) == (k, k - 1)
    assert rows["recall"] == pytest.approx((k - 1) / k)
    assert rows["precision"] == pytest.approx((k - 1) / k)


def _export_with_copies() -> tuple:
    """A small export, with rows 4 and 5 planted as exact copies of row 1
    (d09). Row 1 carries a missing town, so the copies do too. Every value
    is invented."""
    pristine = pd.DataFrame(
        {
            "cust_id": ["00412", "00977", "01530", "03218"],
            "signup": ["2024-01-05", "2024-02-11", "2024-03-02", "2024-03-30"],
            "amount": [1200.0, 85.5, 40.0, 310.25],
            "town": ["Quarnby", None, "Tarrisford", "Quarnby"],
        }
    )
    dirty = pd.concat([pristine, pristine.iloc[[1, 1]]], ignore_index=True)
    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=4,
        n_cols=4,
        frame_sha256="x",
        corruptions=[
            Corruption(
                disease=9,
                columns=tuple(pristine.columns),
                granularity="row",
                rows=(4, 5),
            )
        ],
    )
    return pristine, dirty, truth


# (dirty positions the cleaner removes, R, P). Row 1's value v: planted(v) =
# 2 (rows 4, 5), kept(v) = 1 (row 1 itself), cleaned(v) = 3 - (copies of v
# removed); still_there(v) = min(2, max(0, cleaned(v) - 1)).
_COPIES = [
    # cleaned(v) = 2: still_there = 1, sum = 1, planted_removed = min(1, 1)
    #   R = 1/2, P = 1/1, F1 = 2*0.5*1/1.5 = 2/3
    pytest.param([5], 0.5, 1.0, id="one-copy-removed"),
    # by value the source and a copy are the same row: the same count
    pytest.param([1], 0.5, 1.0, id="the-source-removed-instead"),
    # cleaned(v) = 1: still_there = 0, sum = 2, planted_removed = min(2, 2)
    #   R = 2/2, P = 2/2. v is still in cleaned, once: a match on "is v
    #   still there" would call both copies kept and score R = 0
    pytest.param([4, 5], 1.0, 1.0, id="both-copies-removed"),
    # cleaned(v) = 0: still_there = 0, sum = 2, planted_removed = min(3, 2)
    #   R = 2/2, P = 2/3, F1 = 2*(2/3)*1/(5/3) = 0.8
    pytest.param([1, 4, 5], 1.0, 2 / 3, id="source-and-both-copies-removed"),
    # cleaned(v) = 3: still_there = 2, sum = 0, planted_removed = 0
    #   R = 0/2, P = 0/1, F1 = 0.0
    pytest.param([0], 0.0, 0.0, id="a-good-row-removed"),
]


@pytest.mark.parametrize("removed_positions, recall, precision", _COPIES)
def test_row_matching_counts_copies(removed_positions, recall, precision):
    """Regression for #256. A planted exact duplicate and its source have
    equal values, so matching counts copies: of one source copied twice,
    removing one copy is half the planted rows gone, and v still being in
    cleaned does not mean both copies are. The index is reset, as a
    cleaner's often is."""
    pristine, dirty, truth = _export_with_copies()
    cleaned = dirty.drop(index=removed_positions).reset_index(drop=True)

    rows = _rows_of(pristine, dirty, cleaned, truth)

    assert (rows["planted"], rows["removed"]) == (2, len(removed_positions))
    assert rows["recall"] == pytest.approx(recall)
    assert rows["precision"] == pytest.approx(precision)


def _export_with_a_near_copy() -> tuple:
    """A small export with row 4 planted as a near copy of row 2, its amount
    nudged from 40.0 to 40.01 (d10). Every value is invented."""
    pristine = pd.DataFrame(
        {
            "cust_id": ["00412", "00977", "01530", "03218"],
            "amount": [1200.0, 85.5, 40.0, 310.25],
            "town": ["Quarnby", "Velloch", "Tarrisford", "Quarnby"],
        }
    )
    near = pristine.iloc[[2]].assign(amount=40.01)
    dirty = pd.concat([pristine, near], ignore_index=True)
    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=4,
        n_cols=3,
        frame_sha256="x",
        corruptions=[
            Corruption(disease=10, columns=("amount",), granularity="row", rows=(4,))
        ],
    )
    return pristine, dirty, truth


def test_repairing_a_near_copy_in_place_does_not_remove_it():
    """Regression for #256. A cleaner that repairs the near copy's amount
    turns it into an exact copy of row 2 but leaves the row in. Its planted
    value (40.01) is gone from cleaned, so without the cap at `removed` the
    score would credit a removal that never happened."""
    pristine, dirty, truth = _export_with_a_near_copy()
    cleaned = dirty.copy()
    cleaned.loc[4, "amount"] = 40.0

    rows = _rows_of(pristine, dirty, cleaned, truth)

    # planted(40.01 row) = 1, cleaned(40.01 row) = 0: still_there = 0, so
    # sum = 1, but removed = 0 and planted_removed = min(0, 1) = 0
    #   R = 0/1 = 0.0, P = 0/0 None, F1 = 0.0
    assert rows == {
        "precision": None,
        "recall": 0.0,
        "f1": 0.0,
        "planted": 1,
        "removed": 0,
        "planted_removed": 0,
    }


def test_dropping_the_near_copy_is_a_full_row_repair():
    """Regression for #256, the pin beside the cap above: removing the near
    copy is the repair, and scores row F1 1.0."""
    pristine, dirty, truth = _export_with_a_near_copy()

    rows = _rows_of(pristine, dirty, dirty.drop(index=[4]), truth)

    # removed = 1, the 40.01 row is gone: planted_removed = min(1, 1) = 1
    #   P = 1/1, R = 1/1, F1 = 1.0
    assert (rows["precision"], rows["recall"], rows["f1"]) == (1.0, 1.0, 1.0)


_CELL_ONLY_KEYS = {"dirt_targeting", "repair", "counts"}


def test_a_dataset_with_no_planted_rows_gets_no_row_score():
    """Regression for #256, the other side of the row score: a dataset with
    no row corruption keeps exactly today's keys, for the oracle, the no-op
    and a cleaner that drops every row, so cell-only results, the committed
    replay cassette and every reader that never heard of rows stay as they
    are."""
    checked = 0
    for entry in corpus.SMOKE:
        pristine, dirty, truth = corpus.build(entry)
        if any(c.granularity == "row" for c in truth.corruptions):
            continue
        for cleaned in (pristine, dirty.copy(), dirty.iloc[:0]):
            result = score_end_to_end(pristine, dirty, cleaned, truth)
            assert set(result) == _CELL_ONLY_KEYS, entry["name"]
        checked += 1
    assert checked, "the smoke corpus has no cell-only dataset to check"


def _half_repaired(pristine, dirty, truth) -> pd.DataFrame:
    """A partial cleaner built from the truth alone, so the pins below don't
    move when crivo's fixers do: it restores every other planted cell to its
    pristine value and damages one clean id."""
    cells = sorted({(c.row, c.column) for k in truth.corruptions for c in k.cells})
    cleaned = dirty.astype(object)
    for row, column in cells[::2]:
        cleaned.loc[row, column] = pristine.loc[row, column]
    column = pristine.columns[0]
    row = next(r for r in range(truth.n_rows) if (r, column) not in set(cells))
    cleaned.loc[row, column] = "ZZ-00000"
    return cleaned


# Full end_to_end dicts pinned from d0180c4, before row scoring existed.
# Each cleaner restores every other planted cell (|R| of them) and damages
# one clean id, so |C| = |R| + 1, C∩D = C∩D∩K = D∩K = R:
#   P = |R|/|C|, R = |R|/|D|, F1 = 2|R|/(|C| + |D|), dirt and repair alike
_CELL_PINS = [
    # 25 padded cells, |D| = 25; 13 restored, |C| = 14
    #   P = 13/14, R = 13/25, F1 = 26/39 = 2/3
    pytest.param(
        "tx-whitespace",
        {
            "dirt_targeting": {
                "precision": 0.9285714285714286,
                "recall": 0.52,
                "f1": 0.6666666666666666,
            },
            "repair": {
                "precision": 0.9285714285714286,
                "recall": 0.52,
                "f1": 0.6666666666666666,
            },
            "counts": {"dirty": 25, "changed": 14, "repaired": 13},
        },
        id="d06-whitespace",
    ),
    # the amount column arrives as text, so all 250 amount cells differ from
    # pristine's floats (truth records the 25 money strings): |D| = 250;
    # 13 of the 25 restored, |C| = 14
    #   P = 13/14, R = 13/250, F1 = 26/264
    pytest.param(
        "tx-money-strings",
        {
            "dirt_targeting": {
                "precision": 0.9285714285714286,
                "recall": 0.052,
                "f1": 0.09848484848484848,
            },
            "repair": {
                "precision": 0.9285714285714286,
                "recall": 0.052,
                "f1": 0.09848484848484848,
            },
            "counts": {"dirty": 250, "changed": 14, "repaired": 13},
        },
        id="d01-money-strings",
    ),
    # |D| = 67 ids + 350 dates + 350 amounts (every amount arrives as text)
    # = 767; truth names 452 distinct cells (35 + 35 ids, 3 shared, + 350
    # dates + 35 amounts); 226 restored, |C| = 227
    #   P = 226/227, R = 226/767, F1 = 452/994
    pytest.param(
        "tx-compound-fixable",
        {
            "dirt_targeting": {
                "precision": 0.9955947136563876,
                "recall": 0.29465449804432853,
                "f1": 0.4547283702213279,
            },
            "repair": {
                "precision": 0.9955947136563876,
                "recall": 0.29465449804432853,
                "f1": 0.4547283702213279,
            },
            "counts": {"dirty": 767, "changed": 227, "repaired": 226},
        },
        id="compound-fixable",
    ),
]


@pytest.mark.parametrize("name, expected", _CELL_PINS)
def test_cell_only_datasets_score_exactly_as_before(name, expected):
    """Regression for #256, the pin that row scoring leaves cells alone:
    on cell-only SMOKE data the whole end_to_end dict, to the last digit,
    is what the scorer published before rows were scored."""
    entry = next(e for e in corpus.SMOKE if e["name"] == name)
    pristine, dirty, truth = corpus.build(entry)

    result = score_end_to_end(
        pristine, dirty, _half_repaired(pristine, dirty, truth), truth
    )

    assert result == expected
