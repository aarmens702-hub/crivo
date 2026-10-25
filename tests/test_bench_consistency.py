"""pass^k consistency scoring (A4, docs/research/2026-09-04-agent-system-gaps.md
gap 6): the model-path bench cases vary run to run (the M1 exit report's
tx-dates-mixed / tx-out-of-domain case), so a single run cannot tell a real
regression from luck. This scores repeated runs of the same case: pass^k
(solved on every run) and pass@1 (solved on average), and names the flaky
cases. Pure analysis over result JSONs; it runs no model."""

import pandas as pd
import pytest

from bench import consistency, corpus
from bench.score import score_end_to_end


def _run(status="ok", f1=1.0, rows=None, columns=None):
    """One run's result row. `rows` is the row score's F1 on a dataset that
    plants rows, and `columns` the column score's recall on one that plants
    an extra column; None leaves the block out, as on a cell-only dataset."""
    scores = {"repair": {"f1": f1}}
    if rows is not None:
        scores["rows"] = {"f1": rows}
    if columns is not None:
        scores["columns"] = {"recall": columns}
    return {"status": status, "scores": scores}


def test_solved_predicate_default():
    assert consistency.solved(_run("ok", 1.0))
    assert consistency.solved(_run("ok_unchanged", None))  # held, changed nothing
    assert not consistency.solved(_run("ok", 0.6))  # scored but below threshold
    assert not consistency.solved(_run("no_cleaned_output", None))
    assert not consistency.solved({"status": "aborted: wall cap", "scores": {}})


def test_pass_k_all_runs_solved_is_one():
    runs = [_run("ok", 1.0), _run("ok", 1.0), _run("ok", 1.0)]
    out = consistency.score_pass_k(runs)
    assert out["k"] == 3
    assert out["pass_k"] == 1.0
    assert out["pass_at_1"] == 1.0
    assert out["solved"] == 3


def test_pass_k_one_miss_drops_pass_k_to_zero_but_not_pass_at_1():
    runs = [_run("ok", 1.0), _run("no_cleaned_output", None), _run("ok", 1.0)]
    out = consistency.score_pass_k(runs)
    assert out["pass_k"] == 0.0  # not solved on every run
    assert round(out["pass_at_1"], 3) == 0.667  # solved 2 of 3
    assert out["solved"] == 2


def test_aggregate_flags_flaky_cases_only():
    by_case = {
        "tx-dates-frozen": [_run("ok", 1.0), _run("ok", 1.0)],  # always solved
        "tx-dates-mixed": [_run("ok", 1.0), _run("no_cleaned_output", None)],  # flaky
        "pairs-contradictions": [
            _run("no_cleaned_output", None),
            _run("no_cleaned_output", None),
        ],  # never solved (not flaky, just unsolved)
    }
    agg = consistency.aggregate_consistency(by_case)
    assert agg["cases"] == 3
    assert agg["flaky"] == ["tx-dates-mixed"]  # 0 < pass_at_1 < 1 only
    assert agg["stable_solved"] == ["tx-dates-frozen"]
    assert round(agg["mean_pass_k"], 3) == round(1 / 3, 3)  # only frozen is pass^k
    assert round(agg["mean_pass_at_1"], 3) == 0.5  # (1 + 0.5 + 0) / 3


def test_custom_threshold_and_predicate():
    runs = [_run("ok", 0.8), _run("ok", 0.9)]
    assert consistency.score_pass_k(runs, threshold=0.75)["pass_k"] == 1.0
    assert consistency.score_pass_k(runs, threshold=0.95)["pass_k"] == 0.0


def test_group_runs_by_case_name():
    rows = [
        {"name": "a", "run": 1, "status": "ok", "scores": {"repair": {"f1": 1.0}}},
        {"name": "a", "run": 2, "status": "ok", "scores": {"repair": {"f1": 1.0}}},
        {"name": "b", "run": 1, "status": "ok", "scores": {"repair": {"f1": 1.0}}},
    ]
    grouped = consistency.group_by_case(rows)
    assert set(grouped) == {"a", "b"}
    assert len(grouped["a"]) == 2 and len(grouped["b"]) == 1


# (status, repair F1, row F1, solved). On a row dataset the dirt sits in
# appended rows the cell grid never sees, so repair F1 is usually None there
# and only the row score can say the run left the rows in.
_ROW_RUNS = [
    pytest.param("ok", None, 0.0, False, id="cells-unmeasurable-rows-left"),
    pytest.param("ok_unchanged", None, 0.0, False, id="held-run-left-the-rows"),
    pytest.param("ok", 1.0, 0.5, False, id="cells-repaired-half-the-rows"),
    # the pins beside: a row score that meets the threshold leaves the run
    # to the rules it had, status and cell F1 alike
    pytest.param("ok", None, 1.0, True, id="cells-unmeasurable-rows-removed"),
    pytest.param("ok", 1.0, 1.0, True, id="cells-and-rows-repaired"),
    pytest.param("ok", 0.6, 1.0, False, id="rows-removed-cells-short"),
    pytest.param("no_cleaned_output", None, 1.0, False, id="no-output-still-fails"),
]


@pytest.mark.parametrize("status, repair_f1, rows_f1, want", _ROW_RUNS)
def test_a_row_dataset_is_solved_only_when_its_rows_are(
    status, repair_f1, rows_f1, want
):
    """Regression for #256. `solved` read only the cell repair F1, so a run
    that left every planted row in place counted as solved whenever the
    cells were unmeasurable, and a held ok_unchanged run on a row dataset
    counted as deferring correctly. A defined row score below the threshold
    now fails the run, whatever the cells say."""
    assert consistency.solved(_run(status, repair_f1, rows=rows_f1)) is want


def test_the_threshold_applies_to_the_row_score():
    """Regression for #256. The caller's threshold is the bar for the row
    score as well as for cells."""
    runs = [_run("ok", 1.0, rows=0.8), _run("ok", 1.0, rows=0.9)]

    assert consistency.score_pass_k(runs, threshold=0.75)["pass_k"] == 1.0
    assert consistency.score_pass_k(runs, threshold=0.95)["pass_k"] == 0.0
    assert consistency.solved(runs[1], threshold=0.85)
    assert not consistency.solved(runs[0], threshold=0.85)


def _dup_rows_cleaned(cleaner: str):
    """The real end_to_end scores of the d09 SMOKE dataset as `cleaner` left
    it. The 25 planted exact duplicates are appended after row 250, so the
    cell grid sees nothing a row-only cleaner does."""
    entry = next(e for e in corpus.SMOKE if e["name"] == "tx-dup-rows")
    pristine, dirty, truth = corpus.build(entry)
    planted = sorted(
        {r for c in truth.corruptions if c.granularity == "row" for r in c.rows}
    )
    cleaned = {
        "oracle": lambda: pristine,
        "no-op": lambda: dirty.copy(),
        "drop-everything": lambda: dirty.iloc[:0],
        "leaves-one-planted-row": lambda: dirty.drop(index=planted[:-1]),
        "drop-duplicates": lambda: dirty.drop_duplicates(),
    }[cleaner]()
    return score_end_to_end(pristine, dirty, cleaned, truth)


@pytest.mark.parametrize(
    "status, cleaner, want",
    [
        pytest.param("ok", "no-op", False, id="no-op"),
        pytest.param("ok_unchanged", "no-op", False, id="held-no-op"),
        # 24 of 25 removed: row P = 24/24, R = 24/25, F1 = 48/49 < 1.0
        pytest.param("ok", "leaves-one-planted-row", False, id="leaves-one-row"),
        # the cells already fail this one (every scored cell went missing);
        # it stays failed with rows scored: row P = 25/275, F1 = 1/6
        pytest.param("ok", "drop-everything", False, id="drop-everything"),
        # the pins beside: removing exactly the planted rows is solved
        pytest.param("ok", "oracle", True, id="oracle"),
        pytest.param("ok", "drop-duplicates", True, id="drop-duplicates"),
    ],
)
def test_solved_on_real_scores_of_the_duplicate_rows_dataset(status, cleaner, want):
    """Regression for #256. With the real scorer on the d09 SMOKE dataset,
    the oracle and the no-op both scored every repair number None, and both
    counted as solved. Now only the cleaners that remove the planted rows
    are."""
    run = {"status": status, "scores": _dup_rows_cleaned(cleaner)}

    assert consistency.solved(run) is want


def _count_credit_cheat(name: str, cheat: str) -> dict:
    """The real end_to_end scores of a SMOKE row dataset after a cheat that
    removes as many rows as were planted (k) without removing the planted
    ones, and changes values so they no longer match their dirty copies."""
    entry = next(e for e in corpus.SMOKE if e["name"] == name)
    pristine, dirty, truth = corpus.build(entry)
    planted = sorted(
        {r for c in truth.corruptions if c.granularity == "row" for r in c.rows}
    )
    k = len(planted)

    def drop_k_grid_rows(frame):  # the first k rows: good rows, every one
        return frame.drop(index=frame.index[:k])

    def rewrite_a_planted_row():
        # every planted row but the last removed, the last rewritten in
        # place, and the last good row removed instead of it
        rewritten = dirty.astype(object)
        rewritten.iloc[planted[-1]] = "ZZ-REWRITTEN"
        return rewritten.drop(index=rewritten.index[[*planted[:-1], truth.n_rows - 1]])

    cleaned = {
        "rename-every-column": lambda: drop_k_grid_rows(
            dirty.set_axis([f"col_{i}" for i in range(dirty.shape[1])], axis=1)
        ),
        "wipe-everything": lambda: drop_k_grid_rows(
            pd.DataFrame(float("nan"), index=dirty.index, columns=dirty.columns)
        ),
        "cast-to-str": lambda: drop_k_grid_rows(dirty.astype(str)),
        "rewrite-a-planted-row": rewrite_a_planted_row,
    }[cheat]()
    return score_end_to_end(pristine, dirty, cleaned, truth)


# Where a cheat earns no row credit. tx-header-echo's planted rows (a header
# echo and a footer) are text already, so casting to str leaves both matching
# their dirty values: still there, planted_removed = 0, row F1 0.0.
_ROW_F1_OTHER_THAN_FULL = {("tx-header-echo", "cast-to-str"): 0.0}


@pytest.mark.parametrize(
    "cheat",
    ["rename-every-column", "wipe-everything", "cast-to-str", "rewrite-a-planted-row"],
)
@pytest.mark.parametrize(
    "name",
    [
        "tx-dup-rows",
        "tx-near-dups",
        "tx-aggregate-row",
        "tx-header-echo",
        "tx-compound-hard",
    ],
)
def test_a_count_credit_cheat_scores_full_rows_but_is_not_solved(name, cheat):
    """Regression for #256. KNOWN GAP, pinned: rows match by value, and value
    matching can't tell a planted row rewritten past recognition from one
    removed. A cheat that removes k good rows and rewrites the rest scores
    row F1 1.0. Today the cell rule is what stops it, since every one of
    these moves or blanks the scored grid, so `solved` stays False. This pin
    breaks if anyone relaxes the cell rule on row datasets."""
    scores = _count_credit_cheat(name, cheat)

    # KNOWN GAP. removed = k. Renamed, every row has the same (empty) value;
    # wiped, the same all-missing value; cast or rewritten, no planted row's
    # dirty value is left in cleaned. Either way still_there(v) = 0 for every
    # planted value, sum = k, planted_removed = min(k, k) = k:
    #   R = k/k = 1.0, P = k/k = 1.0, F1 = 1.0, with every planted row in
    #   place (or rewritten) and k good rows gone
    assert scores["rows"]["f1"] == _ROW_F1_OTHER_THAN_FULL.get((name, cheat), 1.0)
    # the cell rule: the scored grid is renamed away, blanked, retyped or
    # shifted, so repair F1 is a measured number below 1.0
    assert scores["repair"]["f1"] is not None
    assert scores["repair"]["f1"] < 1.0
    assert consistency.solved({"status": "ok", "scores": scores}) is False


# (status, repair F1, row F1, column recall, solved). On d25 the planted
# column sits outside the cell grid, so repair F1 is None there and only the
# column score can say the run left the column in.
_COLUMN_RUNS = [
    pytest.param("ok", None, None, 0.0, False, id="cells-unmeasurable-column-left"),
    pytest.param("ok_unchanged", None, None, 0.0, False, id="held-run-left-the-column"),
    pytest.param("ok", 1.0, None, 0.0, False, id="cells-repaired-column-left"),
    pytest.param("ok", 1.0, 1.0, 0.0, False, id="cells-and-rows-repaired-column-left"),
    # one of two planted columns under one label removed
    pytest.param("ok", None, None, 0.5, False, id="half-the-columns-removed"),
    # the pins beside: a column score that meets the threshold leaves the
    # run to the rules it had, status, cells and rows alike
    pytest.param("ok", None, None, 1.0, True, id="cells-unmeasurable-column-removed"),
    pytest.param("ok", 1.0, 1.0, 1.0, True, id="cells-rows-and-column-repaired"),
    pytest.param("ok", 0.6, None, 1.0, False, id="column-removed-cells-short"),
    pytest.param("ok", 1.0, 0.0, 1.0, False, id="column-removed-rows-left"),
    pytest.param(
        "no_cleaned_output", None, None, 1.0, False, id="no-output-still-fails"
    ),
]


@pytest.mark.parametrize("status, repair_f1, rows_f1, columns, want", _COLUMN_RUNS)
def test_a_column_dataset_is_solved_only_when_its_column_is_removed(
    status, repair_f1, rows_f1, columns, want
):
    """Regression for #263. `solved` read the cell repair F1 and the row
    score, so a run that left a planted extra column in place counted as
    solved whenever the cells were unmeasurable or repaired, a held
    ok_unchanged run included. Column recall below the threshold now fails
    the run, whatever the cells and rows say."""
    run = _run(status, repair_f1, rows=rows_f1, columns=columns)

    assert consistency.solved(run) is want


def test_the_threshold_applies_to_the_column_score():
    """Regression for #263. The caller's threshold is the bar for column
    recall as well as for cells and rows."""
    runs = [_run("ok", 1.0, columns=0.5), _run("ok", 1.0, columns=1.0)]

    assert consistency.score_pass_k(runs, threshold=0.5)["pass_k"] == 1.0
    assert consistency.score_pass_k(runs, threshold=0.75)["pass_k"] == 0.0
    assert consistency.solved(runs[0], threshold=0.5)
    assert not consistency.solved(runs[0], threshold=0.75)


def _dup_column_cleaned(cleaner: str):
    """The real end_to_end scores of the d25 SMOKE dataset as `cleaner` left
    it. The planted copy, txn_id_x, is appended after pristine's columns, so
    the cell grid sees nothing a column-only cleaner does."""
    entry = next(e for e in corpus.SMOKE if e["name"] == "tx-dup-column")
    pristine, dirty, truth = corpus.build(entry)
    cleaned = {
        "oracle": lambda: pristine,
        "no-op": lambda: dirty.copy(),
        "drops-the-copy": lambda: dirty.drop(columns="txn_id_x"),
        "renames-the-copy": lambda: dirty.rename(columns={"txn_id_x": "txn_id_copy"}),
        "keeps-the-copy-drops-txn_id": lambda: dirty.drop(columns="txn_id"),
    }[cleaner]()
    return score_end_to_end(pristine, dirty, cleaned, truth)


@pytest.mark.parametrize(
    "status, cleaner, want",
    [
        # column recall 0/1 = 0.0 on each, with every repair number None
        pytest.param("ok", "no-op", False, id="no-op"),
        pytest.param("ok_unchanged", "no-op", False, id="held-no-op"),
        pytest.param("ok", "renames-the-copy", False, id="renames-the-copy"),
        # the cells already fail this one: |D| = 0 and the 250 txn_id cells
        # changed, repair P = 0/250, F1 = 0.0; column recall 0.0 as well
        pytest.param("ok", "keeps-the-copy-drops-txn_id", False, id="keeps-the-copy"),
        # the pins beside: removing the planted copy is solved
        pytest.param("ok", "oracle", True, id="oracle"),
        pytest.param("ok", "drops-the-copy", True, id="drops-the-copy"),
    ],
)
def test_solved_on_real_scores_of_the_duplicate_column_dataset(status, cleaner, want):
    """Regression for #263. With the real scorer on the d25 SMOKE dataset,
    the oracle and the no-op both scored every repair number None, and both
    counted as solved. Now only the cleaners that remove the planted column
    are; renaming it is not removing it."""
    run = {"status": status, "scores": _dup_column_cleaned(cleaner)}

    assert consistency.solved(run) is want
