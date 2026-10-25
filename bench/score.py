"""The Proving Ground's scorer (spec R3): detection quality, end-to-end repair
quality, and verification survival, all measured from outside `crivo` — this
module owns its own equivalence rule (`autoclean._same` is private, and bench
never imports core internals) so a scoring bug can never hide behind a shared
helper with the thing it is grading.
"""

from __future__ import annotations

import datetime
import math
import re
from collections import Counter

import numpy as np
import pandas as pd

# A plain number, so "12.0" and "12" can score as the same value in string
# space. Leading zeros are excluded on purpose: losing them is disease 22,
# so "02115" must never equal "2115".
_PLAIN_NUMBER = re.compile(r"^[-+]?(0|[1-9]\d*)(\.\d+)?$")

from crivo.autoclean import FIXERS, clean
from crivo.detect import detect_all


def _is_missing(x) -> bool:
    """None, float NaN, pd.NaT, pd.NA are one value: the missing family."""
    if x is None or x is pd.NA:
        return True
    try:
        return bool(pd.isna(x))
    except (TypeError, ValueError):
        return False


def _is_bool(x) -> bool:
    """Python bool or numpy bool_. np.bool_ is neither a Python bool nor an
    np.integer, so it needs naming here or it falls through to plain ==."""
    return isinstance(x, (bool, np.bool_))


def _is_number(x) -> bool:
    """int/float/np numbers — bool excluded, even though bool subclasses int."""
    return not _is_bool(x) and isinstance(x, (int, float, np.integer, np.floating))


def _is_datetime(x) -> bool:
    return isinstance(x, (datetime.date, np.datetime64, pd.Timestamp))


def equivalent(a, b) -> bool:
    """Type-aware value equivalence for scoring.

    The missing family collapses to one value; numbers cross-compare within a
    1e-9 relative tolerance; datetime-like values compare by instant;
    everything else needs exact equality in the same type family. A str is
    never equivalent to a number or a timestamp — dtype damage is damage, a
    deliberate scoring decision, not an oversight. A bool likewise compares
    only to another bool, numpy booleans counted as bools on both sides:
    True and 1 are not the same fix.

    Never raises: an incomparable pair is just not equivalent.
    """
    try:
        a_missing, b_missing = _is_missing(a), _is_missing(b)
        if a_missing or b_missing:
            return a_missing and b_missing
        if _is_bool(a) or _is_bool(b):
            return _is_bool(a) and _is_bool(b) and bool(a == b)
        if _is_number(a) and _is_number(b):
            return math.isclose(float(a), float(b), rel_tol=1e-9)
        a_dt, b_dt = _is_datetime(a), _is_datetime(b)
        if a_dt or b_dt:
            return a_dt and b_dt and bool(pd.Timestamp(a) == pd.Timestamp(b))
        return bool(a == b)
    except Exception:  # noqa: BLE001 - an incomparable pair must never crash the scorer
        # incomparable pair (mismatched exotic types, tz-naive vs tz-aware,
        # a custom __eq__ that raises) — never crash the scorer over one cell
        return False


def _stringly(x) -> str:
    """Render a value the way an all-string CSV would show it: missing is
    blank, a midnight timestamp is its date, everything else str() stripped."""
    if _is_missing(x):
        return ""
    if _is_datetime(x):
        ts = pd.Timestamp(x)
        return str(ts.date()) if ts == ts.normalize() else str(ts)
    return str(x).strip()


def equivalent_str(a, b) -> bool:
    """String-space equivalence for external (all-string) pairs.

    Raha pairs carry every value as text while crivo.clean re-types, so the
    typed `equivalent` would make external repair structurally unwinnable.
    Here both sides render to strings first; two plain numbers then compare
    numerically ("12.0" == "12") — but a leading zero fails the plain-number
    shape, so "02115" != "2115" (losing zeros is disease 22, not a formatting
    nicety). Never raises.
    """
    try:
        a_s, b_s = _stringly(a), _stringly(b)
        if a_s == b_s:
            return True
        if _PLAIN_NUMBER.match(a_s) and _PLAIN_NUMBER.match(b_s):
            return math.isclose(float(a_s), float(b_s), rel_tol=1e-9)
        return False
    except Exception:  # noqa: BLE001 - an incomparable pair must never crash the scorer
        return False


def _positions(
    columns,
    n_rows: int,
    left: pd.DataFrame,
    right: pd.DataFrame,
    want_equivalent: bool,
    values_equal=equivalent,
) -> set[tuple[int, str]]:
    """Row/column positions (row < n_rows) where `left` and `right` do (or, if
    `want_equivalent` is False, do not) agree, restricted to `columns`. A
    column absent from either frame counts as disagreeing everywhere — a
    renamed or dropped column is column-granular damage, not a per-cell
    question, so it can never contribute to the "agree" side."""
    out = set()
    for column in columns:
        name = str(column)
        if column not in left.columns or column not in right.columns:
            if not want_equivalent:
                out.update((row, name) for row in range(n_rows))
            continue
        l_col, r_col = left[column], right[column]
        l_len, r_len = len(l_col), len(r_col)
        for row in range(n_rows):
            l_val = l_col.iat[row] if row < l_len else None
            r_val = r_col.iat[row] if row < r_len else None
            if values_equal(l_val, r_val) == want_equivalent:
                out.add((row, name))
    return out


def _value_key(x) -> tuple:
    """A hashable stand-in for one value, finer than `equivalent`, in a form
    a Counter can hold: the missing family is one key, numbers are floats
    rounded to 12 significant digits, a bool stays a bool, datetime-likes
    compare by instant (tz-aware and naive apart, as `equivalent` keeps them),
    strings compare exactly. On those families an equal key implies
    `equivalent`, but not the other way round: two numbers within its 1e-9
    tolerance can round apart at 12 digits. Never raises: an exotic value
    keys by its type and repr, and only that fallback can give one key to
    values `equivalent` keeps apart."""
    try:
        if _is_missing(x):
            return ("missing",)
        if _is_bool(x):
            return ("bool", bool(x))
        if _is_number(x):
            return ("number", float(f"{float(x):.12g}"))
        if _is_datetime(x):
            ts = pd.Timestamp(x)
            if ts.tzinfo is None:
                return ("datetime", "naive", ts)
            return ("datetime", "aware", ts.tz_convert(None))
        if isinstance(x, str):
            return ("str", str(x))
        return ("other", type(x).__name__, repr(x))
    except Exception:  # noqa: BLE001 - one odd value must never crash the scorer
        return ("other", type(x).__name__)


def _first_column(frame: pd.DataFrame, label):
    """The first column of `frame` named `label`, or None. A cleaned frame
    can carry one name twice, and `frame[label]` would then be a frame."""
    if label not in frame.columns:
        return None
    return frame.iloc[:, frame.columns.get_indexer_for([label])[0]]


def _row_keys(frame: pd.DataFrame, columns) -> list[tuple]:
    """One value key per row of `frame` over `columns`, in row order."""
    if not columns:
        return [()] * len(frame)
    values = [_first_column(frame, c).tolist() for c in columns]
    return [tuple(_value_key(x) for x in row) for row in zip(*values)]


def _row_removal(
    pristine: pd.DataFrame, dirty: pd.DataFrame, cleaned: pd.DataFrame, truth
) -> dict:
    """Row-removal precision and recall for the truth's row corruptions.

    The planted rows are the union of every row corruption's `rows`
    (positions in `dirty`). Rows match by value, never by position or index
    label, over pristine's columns present in both `dirty` and `cleaned`,
    and copy by copy, since a planted exact duplicate has its source's
    values. For each value key v, kept(v) counts v among the unplanted dirty
    rows, and still_there(v) = min(planted(v), max(0, cleaned(v) - kept(v))).
    Then planted_removed = min(removed, Σ(planted(v) - still_there(v))),
    where removed = max(0, len(dirty) - len(cleaned)).

    The cap holds credit to the drop in row count, so a rewrite alone earns
    nothing. It stops no more than that: value matching can't tell a
    rewritten planted row from a removed one, so a cleaner that rewrites and
    also removes is credited for planted rows first. In the limit the score
    is counts alone, planted_removed = min(removed, planted): with no
    compared column (all renamed or dropped) every row has the same empty
    key, and once no planted row's dirty key is left in `cleaned`, none is
    still there. A compared column rewritten on every row (wiped to NaN,
    cast to str, nudged inside `equivalent`'s tolerance but past the key's
    12 digits) gets there wherever it changes the planted rows' values.

    Credit for a planted row still in place is paid for by an unplanted row
    removed, and the unplanted rows are the cell grid's rows (injectors
    append the rows they plant), where a removal shifts every row after it.
    The cell score is what sees that, which is why `consistency.solved`
    reads both."""
    planted_at = sorted(
        {r for c in truth.corruptions if c.granularity == "row" for r in c.rows}
    )
    columns = [
        c
        for c in pristine.columns
        if _first_column(dirty, c) is not None and _first_column(cleaned, c) is not None
    ]
    dirty_keys = _row_keys(dirty, columns)
    planted_set = set(planted_at)
    planted = Counter(dirty_keys[r] for r in planted_at)
    kept = Counter(k for i, k in enumerate(dirty_keys) if i not in planted_set)
    in_cleaned = Counter(_row_keys(cleaned, columns))
    gone = sum(n - min(n, max(0, in_cleaned[v] - kept[v])) for v, n in planted.items())
    removed = max(0, len(dirty) - len(cleaned))
    planted_removed = min(removed, gone)
    precision = planted_removed / removed if removed else None
    recall = planted_removed / len(planted_at) if planted_at else None
    return {
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "planted": len(planted_at),
        "removed": removed,
        "planted_removed": planted_removed,
    }


def _column_removal(
    pristine: pd.DataFrame, dirty: pd.DataFrame, cleaned: pd.DataFrame
) -> dict:
    """Column-removal recall for the extra columns planted in `dirty`.

    The planted columns are the labels `dirty` holds that pristine lacks,
    counted copy by copy: E = Counter(dirty.columns) - Counter(pristine
    .columns), planted = ΣE. Labels compare exactly as pandas holds them (no
    str(), strip or case-fold), so an int label stays an int and a NaN label
    is one more label, and nothing here raises on either. `cleaned`'s labels
    are its columns plus its named index levels, so a planted column moved
    into the index under its own name (set_index, a parquet round trip of
    it) is still there. The labels left over are left = Counter(those) -
    Counter(pristine.columns); still_there = min(planted, Σleft), removed =
    planted - still_there, recall = removed / planted (None when nothing is
    planted).

    A left-over label counts whatever it is called now, so renaming the
    planted column is not removing it, while renaming a damaged header back
    to its pristine name is. There is no precision: a pristine column the
    cleaner drops, or never restores, is charged in the cell grid already
    (every cell of it changed, none correct), and charging it here would
    count it twice. On d18 one miss is counted in both, by design: a
    damaged header never renamed back is a pristine column missing from the
    grid and a planted label left here.

    Known gaps. Two under-credit: a column the cleaner adds (a review flag)
    reads as the planted column left in place, and so do int labels the
    cleaner turned into text (a CSV round trip reads 0..2 back as "0".."2").
    One over-credits: an unnamed index level carries no label, so a planted
    column moved into one (`cleaned.index = values`) reads as removed while
    its values stay in the frame. Unnamed levels stay uncounted: every
    frame has an index, and an unnamed one (a plain range, or the gapped
    one a row drop leaves) can't be told from one that holds a column."""
    pristine_labels = Counter(pristine.columns)
    planted = sum((Counter(dirty.columns) - pristine_labels).values())
    named_levels = [n for n in cleaned.index.names if n is not None]
    left = sum((Counter([*cleaned.columns, *named_levels]) - pristine_labels).values())
    removed = planted - min(planted, left)
    return {
        "planted": planted,
        "removed": removed,
        "recall": removed / planted if planted else None,
    }


def _f1(precision: float | None, recall: float | None) -> float | None:
    """Harmonic mean of precision and recall. In `score_end_to_end` (dirt
    targeting, repair) that is 2·TP / (|C| + |D|), since a dirty cell that
    ends correct has changed; `score_detection` counts precision and recall
    over different numerators, so there it is only the harmonic mean.
    None only when both precision and recall are undefined: nothing
    to find and nothing done. One undefined side reads as 0.0 (changing
    nothing on real dirt is a measured miss), and P+R of 0 is F1 0.0, never
    None or NaN (#86)."""
    if precision is None and recall is None:
        return None
    precision, recall = precision or 0.0, recall or 0.0
    denom = precision + recall
    return 2 * precision * recall / denom if denom else 0.0


def score_end_to_end(
    pristine: pd.DataFrame,
    dirty: pd.DataFrame,
    cleaned: pd.DataFrame,
    truth,
    values_equal=equivalent,
) -> dict:
    """Cell-level dirt-targeting and repair quality (Baran-comparable),
    scored over the pristine grid only: rows < truth.n_rows, pristine's own
    columns. D = truly dirty, C = touched by the cleaner, K = ended correct.
    `values_equal` picks the equivalence space: typed for the synthetic
    corpus, `equivalent_str` for all-string external pairs.

    The cell grid never sees appended rows, so when the truth holds a "row"
    granularity corruption the result also carries "rows": how many planted
    rows are gone from `cleaned` (recall) and how many removed rows were
    planted (precision), matched by value (`_row_removal`). Without one, the
    key is absent and the result is the cell score alone. Only removal is
    scored: a d10 merge that combines values across rows is not.

    The grid never sees a column pristine lacks either, so when `dirty`
    carries one (a planted extra column, whatever the truth's granularity
    says) the result also carries "columns": how many planted columns are
    gone from `cleaned`'s columns and named index levels (`_column_removal`).
    It has no precision, since a
    pristine column the cleaner drops is charged in the grid already.
    Without a planted column the key is absent."""
    n = truth.n_rows
    columns = pristine.columns
    D = _positions(columns, n, pristine, dirty, False, values_equal)
    C = _positions(columns, n, dirty, cleaned, False, values_equal)
    K = _positions(columns, n, pristine, cleaned, True, values_equal)

    c_and_d = C & D
    d_and_k = D & K
    c_and_d_and_k = C & D & K

    dt_precision = len(c_and_d) / len(C) if C else None
    dt_recall = len(c_and_d) / len(D) if D else None
    rp_precision = len(c_and_d_and_k) / len(C) if C else None
    rp_recall = len(d_and_k) / len(D) if D else None

    result = {
        "dirt_targeting": {
            "precision": dt_precision,
            "recall": dt_recall,
            "f1": _f1(dt_precision, dt_recall),
        },
        "repair": {
            "precision": rp_precision,
            "recall": rp_recall,
            "f1": _f1(rp_precision, rp_recall),
        },
        "counts": {"dirty": len(D), "changed": len(C), "repaired": len(d_and_k)},
    }
    # _row_removal tolerates a name twice in `cleaned`, but `_positions` above
    # raises on one first, so no caller reaches that case through here yet
    if any(c.granularity == "row" for c in truth.corruptions):
        result["rows"] = _row_removal(pristine, dirty, cleaned, truth)
    column_removal = _column_removal(pristine, dirty, cleaned)
    if column_removal["planted"]:
        result["columns"] = column_removal
    return result


def _columns_match(finding_columns, corruption) -> bool:
    """Does a finding's column scope reach this truth corruption's?

    Both sides naming columns is a set intersection. The hard case is a
    finding that names none: crivo's d09 finding carries `columns: []`
    because duplicate rows are not about any one column, while the injector
    records every column of the frame, so a literal intersection would score
    the detector at zero on a match that is real.

    The wildcard that fixed it matched anything of the same disease, in both
    directions, which is not a wildcard for whole-frame scope but a wildcard
    for everything. One finding naming no column then recalled every truth
    corruption of its disease, so a cell-scoped disease planted across several
    columns published recall 1.0 off a finding that located nothing.

    So a column-less side is read as the whole-frame claim it is, and is
    credited only against a whole-row corruption ("row" granularity: d09
    duplicates, d21 rollups, d24 aggregates). Against a cell- or
    column-scoped corruption it matches nothing, because a finding that
    names no column has not found that column.
    """
    named = set(finding_columns)
    truth_columns = set(corruption.columns)
    if named and truth_columns:
        return bool(named & truth_columns)
    return corruption.granularity == "row"


def score_detection(detect_result: dict, truth) -> dict:
    """Column x disease precision/recall/F1. A finding is a TP iff truth
    holds a same-disease corruption with intersecting columns; a truth
    corruption is recalled iff some finding matches it the same way. Disease
    0 (external/unknown) carries no taxonomy and is excluded on both sides.

    Matching is many-to-many (several findings can hit one corruption, and one
    finding can hit several), so the two ratios need different numerators and
    the JSON names both, each with its own denominator: precision is
    matched_findings/n_findings, recall is matched_truth/n_truth.

    Those four counts are the whole schema on purpose. There is no `tp`, and
    no `fp`/`fn` complements either. One numerator paired with the other
    ratio's denominator is exactly the arithmetic that inflated recall, so
    every count published here has to carry the universe it was counted over,
    and a reader who wants the misses subtracts.

    That is a labelling, not a guarantee, and the wave 1 docstring and commit
    message claimed the guarantee: they said the retracted recall was not
    constructible from these counts. It is constructible exactly, by the
    subtraction they invited: it is matched_findings over
    matched_findings + (n_truth - matched_truth), which on the three-findings
    / two-corruptions case is 3/(3+1) = 0.75, the number this scorer
    retracted. The counts stay published anyway, because withholding the
    inputs of the wrong ratio would withhold the inputs of the right one and
    leave a reader unable to check either. What the schema buys is that the
    wrong pairing is legible as a wrong pairing, and no field of this JSON is
    itself that number.
    """
    findings = [f for f in detect_result["findings"] if f["disease"] != 0]
    corruptions = [c for c in truth.corruptions if c.disease != 0]

    diseases = sorted(
        {f["disease"] for f in findings} | {c.disease for c in corruptions}
    )
    per_disease = {}
    for disease in diseases:
        d_findings = [f for f in findings if f["disease"] == disease]
        d_truth = [c for c in corruptions if c.disease == disease]
        matched_findings = sum(
            any(_columns_match(f["columns"], c) for c in d_truth) for f in d_findings
        )
        matched_truth = sum(
            any(_columns_match(f["columns"], c) for f in d_findings) for c in d_truth
        )
        precision = matched_findings / len(d_findings) if d_findings else None
        recall = matched_truth / len(d_truth) if d_truth else None
        per_disease[str(disease)] = {
            "matched_findings": matched_findings,
            "n_findings": len(d_findings),
            "matched_truth": matched_truth,
            "n_truth": len(d_truth),
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
        }

    truth_diseases = sorted({c.disease for c in corruptions})
    macro_f1 = None
    if truth_diseases:
        f1s = [per_disease[str(d)]["f1"] or 0.0 for d in truth_diseases]
        macro_f1 = sum(f1s) / len(f1s)

    # each micro ratio pools its own numerator: findings for precision, truth
    # corruptions for recall, never one shared count across two denominators
    total_matched_findings = sum(v["matched_findings"] for v in per_disease.values())
    total_findings = sum(v["n_findings"] for v in per_disease.values())
    total_matched_truth = sum(v["matched_truth"] for v in per_disease.values())
    total_truth = sum(v["n_truth"] for v in per_disease.values())
    micro_precision = (
        total_matched_findings / total_findings if total_findings else None
    )
    micro_recall = total_matched_truth / total_truth if total_truth else None

    return {
        "per_disease": per_disease,
        "macro_f1": macro_f1,
        "micro": {
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": _f1(micro_precision, micro_recall),
        },
    }


def score_verification(dirty: pd.DataFrame, summary) -> dict:
    """Verification stats from outside crivo: how many AUTO-grade, fixer-
    backed findings survived clean()'s own re-verification to become an
    applied fix, with no core changes needed to observe it."""
    findings = detect_all(dirty)["findings"]
    attempted = sum(
        1 for f in findings if f["grade"] == "AUTO" and f["disease"] in FIXERS
    )
    applied = len(summary.applied)
    return {
        "attempted": attempted,
        "applied": applied,
        "survived_rate": applied / attempted if attempted else None,
        "needs_review": len(summary.needs_review),
    }


def score_pair(
    pristine: pd.DataFrame, dirty: pd.DataFrame, truth, name: str = "df"
) -> dict:
    """The full per-dataset scoring composition: detection quality, end-to-
    end repair quality, and verification survival — plus an honest split of
    which truth diseases deterministic mode could even attempt, so aggregate
    tables never blend "not attempted" into a blended score."""
    truth.verify_frame(dirty)  # refuse a frame/manifest pair that drifted apart
    detect_result = detect_all(dirty, name=name)
    cleaned, summary = clean(dirty)
    # external pairs are all-string by Raha convention: score in string space
    values_equal = equivalent_str if truth.base == "external" else equivalent
    truth_diseases = sorted({c.disease for c in truth.corruptions if c.disease != 0})
    return {
        "detection": score_detection(detect_result, truth),
        "end_to_end": score_end_to_end(pristine, dirty, cleaned, truth, values_equal),
        "verification": score_verification(dirty, summary),
        "attempted_diseases": sorted(d for d in truth_diseases if d in FIXERS),
        "not_attempted_diseases": sorted(d for d in truth_diseases if d not in FIXERS),
    }
