"""Verify-cell builder tests (spec R9-R10): baseline/revert cells exec'd
against a real frame; verify_cell checked as a string contract only, because
the code it generates imports crivo.detect at kernel runtime —
compiling it is fine, executing it here is not."""

import json

import pandas as pd
import pytest

from crivo import verify
from crivo.detect import detect_one
from crivo.verify import (
    ROW_DELTA_BOUNDED,
    ROW_DELTA_EXACT,
    baseline_cell,
    revert_cell,
    verify_cell,
)

BASELINE_COLS = ["a", "b", "c"]


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"], "c": [0.5, 1.5, 2.5]})


def _exec_baseline(frame: pd.DataFrame) -> tuple[dict, str]:
    """Run the baseline cell the way the kernel would: exec every statement,
    eval the trailing expression (exec alone would discard its value)."""
    ns = {"df": frame}
    lines = baseline_cell("df").rstrip("\n").splitlines()
    exec(compile("\n".join(lines[:-1]), "<baseline>", "exec"), ns)  # noqa: S102
    value = eval(compile(lines[-1], "<baseline-last>", "eval"), ns)
    return ns, value


# --- baseline / revert: executable without crivo.detect ---


def test_baseline_cell_snapshots_backup_rows_and_hashes():
    frame = _frame()
    ns, value = _exec_baseline(frame)
    assert ns["_clean_backup"] is not frame
    pd.testing.assert_frame_equal(ns["_clean_backup"], frame)
    assert ns["_clean_rows"] == len(frame)
    assert set(ns["_clean_hashes"]) == set(BASELINE_COLS)
    # one list of hex digests per NAME, one entry per COLUMN carrying it, so
    # a name two columns share records two digests instead of one overwriting
    # the other. Not the old commutative sum of row hashes either.
    assert all(
        isinstance(digests, list)
        and digests
        and all(isinstance(h, str) and h for h in digests)
        for digests in ns["_clean_hashes"].values()
    )
    # the cell's value is the JSON list of baseline columns the host reads
    assert json.loads(value) == sorted(frame.columns)


def test_revert_cell_restores_the_mutated_frame():
    frame = _frame()
    original = frame.copy()
    ns, _ = _exec_baseline(frame)
    ns["df"]["a"] = [7, 8, 9]
    assert not ns["df"]["a"].equals(original["a"])  # mutation really landed
    exec(compile(revert_cell("df"), "<revert>", "exec"), ns)  # noqa: S102
    pd.testing.assert_frame_equal(ns["df"], original)


def test_baseline_cell_survives_duplicate_column_names():
    frame = pd.concat(
        [pd.DataFrame({"x": [1, 2]}), pd.DataFrame({"x": [3, 4]})], axis=1
    )
    assert list(frame.columns) == ["x", "x"]
    ns = {"df": frame}
    # positional hashing must not raise on duplicate names
    exec(compile(baseline_cell("df"), "<baseline-dup>", "exec"), ns)  # noqa: S102
    assert "x" in ns["_clean_hashes"]


# --- verify_cell: string contract + compile, never exec ---


def _finding(disease=4, slug="sentinel-missing", columns=("a",), stats=None):
    return {
        "disease": disease,
        "slug": slug,
        "columns": list(columns),
        "stats": stats or {},
    }


def _untouched_line(code: str) -> str:
    return next(ln for ln in code.splitlines() if ln.startswith("_untouched = "))


def test_preview_cell_shows_consequence_without_touching_the_frame():
    """R3: the gate shows the code and asks whether to run it, which makes the
    operator execute pandas in their head. The preview applies the fix to a
    sampled scratch copy and renders what would move — and the live frame is
    untouched by construction, not by revert (AC3). A fix that errors on the
    sample degrades to a one-line reason instead of blocking the gate."""
    import contextlib
    import io

    fix_source = (
        "def fix_amount(df):\n"
        "    out = df.copy()\n"
        "    out['amount'] = out['amount'].str.replace(',', '', regex=False)\n"
        "    return out\n"
        "df = fix_amount(df)\n"
    )
    frame = pd.DataFrame({"amount": ["1,200", "3,400"], "note": ["a", "b"]})
    namespace = {"df": frame}

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(  # noqa: S102
            compile(verify.preview_cell("df", fix_source), "<pv>", "exec"), namespace
        )
    rendered = out.getvalue()

    assert namespace["df"] is frame, "the live variable must not be rebound"
    assert list(frame["amount"]) == ["1,200", "3,400"], "or mutated"
    assert "preview on 2 of 2 rows" in rendered
    assert "amount: 2 of 2 cells change" in rendered
    assert "untouched" in rendered

    broken = "raise RuntimeError('no such column')\n"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(  # noqa: S102
            compile(verify.preview_cell("df", broken), "<pv2>", "exec"), namespace
        )
    assert "preview unavailable: RuntimeError" in out.getvalue()


def test_the_preview_screen_refuses_anything_beyond_dataframes():
    """A preview executes model code BEFORE the human approves it. The
    scratch copy protects the data; it cannot protect the process — a cell
    that SIGKILLs the kernel, opens files, or reaches for dunders would do so
    unapproved. Discovered live: the sigkill recovery test died inside its
    own preview. Anything beyond pure dataframe work degrades the gate to
    code-only, with the reason named."""
    pure = (
        "import pandas as pd\n"
        "def fix(df):\n    return df.copy()\n"
        "df = fix(df)\n"
        "assert len(df) > 0\n"
    )
    assert verify.preview_screen(pure) == ""

    assert "os" in verify.preview_screen("import os\nos.kill(1, 9)\n")
    assert "open" in verify.preview_screen("open('/etc/passwd')\n")
    assert "dunder" in verify.preview_screen("df.__class__.__init__\n")
    assert "parse" in verify.preview_screen("def broken(:\n")


def test_the_preview_screen_catches_the_bypasses_it_can_see():
    """The screen used to read dunders only when they were spelled as
    attributes, and it never looked at pandas, which carries its own doors to
    the filesystem. So a cell reached __builtins__ through a subscript, named
    it through getattr, or called pd.read_pickle (which runs whatever the file
    unpickles) and still previewed, unapproved. These are the cheap spellings,
    and they are now named. The expensive ones stay open by construction,
    which is what the docstring says out loud."""
    # a dunder reached by string subscript is the same reach as an attribute
    assert verify.preview_screen("globals()['__builtins__']['eval']('1+1')\n") != ""
    assert "dunder" in verify.preview_screen("d['__class__']\n")
    # ... and so is one named as a string to a lookup builtin
    assert "getattr" in verify.preview_screen("getattr(df, '__class__')\n")
    assert verify.preview_screen("vars(df)['__dict__']\n") != ""

    # pandas reads and writes files without importing anything the import
    # check would see; read_pickle executes what it loads
    assert "read_pickle" in verify.preview_screen("df = pd.read_pickle('x.pkl')\n")
    assert "read_csv" in verify.preview_screen("df = pd.read_csv('/etc/passwd')\n")
    assert "to_csv" in verify.preview_screen("df.to_csv('/tmp/out.csv')\n")
    assert "to_pickle" in verify.preview_screen("df.to_pickle(path='p')\n")

    # but a writer handed no destination returns a string and touches nothing
    assert verify.preview_screen("s = df.to_csv()\n") == ""
    assert verify.preview_screen("s = df.to_json(index=False)\n") == ""
    # and ordinary dataframe work still previews
    assert verify.preview_screen("df['amount'] = df['amount'].abs()\n") == ""


def test_the_preview_screen_still_previews_ordinary_cleaning_code():
    """The screen matched builtin names against any attribute call, so
    re.compile() (an allowlisted module's main API, and all over crivo's own
    fixers) and df.eval()/pd.eval() (restricted pandas expression ops, not
    Python eval) lost their preview to a reason that misdescribed them. Real
    dunder-shaped names are collateral of the same kind: '__index_level_0__'
    is pandas' own index column, written by pandas."""
    assert verify.preview_screen("import re\npat = re.compile(r'^\\d+$')\n") == ""
    assert verify.preview_screen("df = df[df.eval('amount > 0')]\n") == ""
    assert verify.preview_screen("mask = pd.eval('df.amount > 0')\n") == ""
    assert verify.preview_screen("df = df.drop(columns=['__index_level_0__'])\n") == ""
    assert verify.preview_screen("src = meta['__source__']\n") == ""


def test_the_preview_screen_reads_every_name_in_an_import():
    """'import pandas, os' is one Import node with two names and only the
    first was read, so a forbidden module in second position previewed
    unapproved while the docstring listed imports as a caught pattern."""
    assert "os" in verify.preview_screen("import pandas, os\n")
    assert "subprocess" in verify.preview_screen("import numpy as np, subprocess\n")


def test_the_preview_screen_sees_numpys_doors_as_well_as_pandas():
    """numpy is allowlisted and carries the same two doors the fix closed for
    pandas: np.load runs what it unpickles when allow_pickle is set, and the
    save/loadtxt family reads and writes files. Closing one and not the other
    is an asymmetry the docstring does not lead a reader to expect."""
    assert "np.load" in verify.preview_screen("a = np.load('x.npy', allow_pickle=True)")
    assert "np.savetxt" in verify.preview_screen("np.savetxt('/tmp/out.csv', a)\n")
    assert "np.fromfile" in verify.preview_screen("a = numpy.fromfile('/etc/passwd')\n")
    # a receiver that is not numpy keeps its ordinary meaning
    assert verify.preview_screen("frame = store.load()\n") == ""


def test_the_preview_screen_sees_pandas_constructors_and_to_string_buf():
    """pd.ExcelFile and pd.HDFStore open files without being spelled read_*,
    and to_string touches the filesystem only when it is handed buf=."""
    assert "ExcelFile" in verify.preview_screen("book = pd.ExcelFile('/tmp/x.xlsx')\n")
    assert "HDFStore" in verify.preview_screen("st = pd.HDFStore('/tmp/x.h5')\n")
    assert "to_string" in verify.preview_screen("df.to_string(buf='/tmp/out.txt')\n")
    assert verify.preview_screen("text = df.to_string()\n") == ""


def test_the_preview_screen_docstring_refuses_to_claim_containment():
    """The screen is the last thing standing between model code and the
    kernel at preview time, which makes it tempting to read as a boundary. It
    is not one: a name assembled at runtime walks past every check in it. The
    docstring has to say so, because the next person to lean on this function
    will read that and nothing else."""
    doc = verify.preview_screen.__doc__ or ""
    assert "not a security boundary" in doc
    assert "best-effort" in doc
    assert "sandbox" in doc


def test_a_detector_crash_reads_as_uncheckable_not_as_a_failed_fix():
    """Inside verify, a detector crash was indistinguishable from a fix that
    did not work: the cell just errored, the revert ran, and the skill ledger
    took the hit — two crashes in one run retired a working skill on someone
    else's bug. The cell must name the difference so the loop can decline to
    score it. Could-not-check still fails the cell: unverified is unverified.

    This one executes (unlike the string-contract tests below): the crash
    fires on the detect_one line, before the cell touches any kernel-only
    names, and the invariant is behavioral. The frame has to carry every
    baseline column, or the untouched-column guard refuses it first and the
    detector is never reached."""
    import pytest

    code = verify_cell("df", _finding(disease=99), BASELINE_COLS)
    namespace = {"df": pd.DataFrame({"a": ["x", "y"], "b": [1, 2], "c": [3, 4]})}

    with pytest.raises(RuntimeError, match="^uncheckable: ValueError"):
        exec(compile(code, "<v-crash>", "exec"), namespace)  # noqa: S102


def test_a_word_splitting_whitespace_repair_fails_verification():
    """detect.py documents zero-width as delete-not-space, so Bud<ZWSP>weiser
    becomes Budweiser and never 'Bud weiser' — but layer 1 only asserted the
    signal stopped firing, which the word-splitting repair also satisfies. The
    corrupted fix was marked fixed, frozen as its own case, and eligible to
    become a skill that runs unattended on AUTO findings. d06 verification is
    now anchored to the reference repair (_ws_tidy of the original), which the
    split disagrees with and the honest repair matches."""
    import pytest

    original = pd.Series(["Bud\u200bweiser"] * 8 + ["Coors Light"] * 12, name="beer")
    finding = _finding(disease=6, slug="whitespace-damage", columns=("beer",))
    code = verify_cell("df", finding, ["beer"])
    namespace = {
        "df": pd.DataFrame({"beer": original.str.replace("\u200b", " ")}),
        "_clean_backup": pd.DataFrame({"beer": original}),
        "_clean_rows": 20,
        "_clean_hashes": {},
    }

    with pytest.raises(AssertionError, match="reference"):
        exec(compile(code, "<v-zw>", "exec"), namespace)  # noqa: S102

    namespace["df"] = pd.DataFrame({"beer": original.str.replace("\u200b", "")})
    exec(compile(code, "<v-zw-ok>", "exec"), namespace)  # noqa: S102


def test_verify_cell_reruns_detector_and_holds_rows_constant():
    code = verify_cell("df", _finding(), BASELINE_COLS)
    assert "detect_one" in code
    # non-delta disease: rows must be exactly unchanged
    assert "assert len(df) == _clean_rows," in code
    compile(code, "<v>", "exec")


def test_verify_cell_untouched_loop_excludes_only_the_fix_targets():
    code = verify_cell("df", _finding(columns=["a"]), BASELINE_COLS)
    listed = _untouched_line(code)
    assert '"b"' in listed and '"c"' in listed  # every other baseline column
    assert '"a"' not in listed  # the target is allowed to change
    # the finding's own columns ride into detect_one json-encoded
    assert json.dumps(["a"]) in code


# --- the untouched-column guard, executed against real frames ---


def _guard_frame() -> pd.DataFrame:
    """One repairable target column ('flow', d04 sentinels) and two columns a
    fix aimed at 'flow' has no business touching."""
    return pd.DataFrame(
        {
            "flow": ["N/A", "N/A"] + [str(v) for v in range(8)],
            "site": [f"site-{v}" for v in range(10)],
            "note": [f"note {v}" for v in range(10)],
        }
    )


def _repair(frame: pd.DataFrame) -> pd.DataFrame:
    """The honest fix for the target column: the sentinels become missing."""
    out = frame.copy()
    out["flow"] = out["flow"].replace("N/A", pd.NA)
    return out


def _verify_after(fix) -> None:
    """The kernel's round trip: baseline snapshot, the fix cell's effect on the
    live variable, then the verify cell. Returns when the fix verifies, raises
    whatever the verify cell raises when it does not."""
    namespace = {"df": _guard_frame()}
    exec(compile(baseline_cell("df"), "<g-baseline>", "exec"), namespace)  # noqa: S102
    namespace["df"] = fix(namespace["df"])
    code = verify_cell("df", _finding(columns=("flow",)), ["flow", "note", "site"])
    exec(compile(code, "<g-verify>", "exec"), namespace)  # noqa: S102


def test_the_untouched_guard_passes_a_fix_that_only_repairs_its_target():
    """The control for the three refusals below: an honest repair of the target
    column, and nothing else moved, still verifies."""
    _verify_after(_repair)


def test_a_fix_that_drops_an_unrelated_column_fails_verification():
    """The guard walked the baseline columns and skipped any that were no
    longer in the frame, so deleting a whole column it was not aiming at was
    invisible to it: the detector cleared, the row count held, and the loop
    recorded the fix as verified while a column of data was gone."""
    import pytest

    with pytest.raises(AssertionError, match="were not fix targets"):
        _verify_after(lambda f: _repair(f).drop(columns=["note"]))


def test_a_fix_that_renames_an_unrelated_column_fails_verification():
    """A rename is a drop plus an arrival under the old guard: the baseline name
    was skipped as absent and the new name was never in the baseline list, so
    nothing checked it. Downstream code keyed on the old name silently reads
    nothing."""
    import pytest

    with pytest.raises(AssertionError, match="were not fix targets"):
        _verify_after(lambda f: _repair(f).rename(columns={"note": "notes"}))


def test_a_fix_that_shuffles_an_unrelated_column_fails_verification():
    """The per-column digest was a .sum() of the row hashes, and a sum is
    commutative: permuting a column's rows left the digest identical. So a fix
    that tore one column loose from its rows passed the untouched check while
    corrupting every record in the frame."""
    import pytest

    def shuffle_note(frame: pd.DataFrame) -> pd.DataFrame:
        out = _repair(frame)
        out["note"] = list(out["note"])[::-1]
        return out

    with pytest.raises(AssertionError, match="was not a fix target"):
        _verify_after(shuffle_note)


def test_the_baseline_digest_is_order_dependent():
    """Same values, different order, must digest differently, or the guard
    above has nothing to compare."""
    ns, _ = _exec_baseline(_frame())
    reversed_b = _frame()
    reversed_b["b"] = list(reversed_b["b"])[::-1]
    ns2, _ = _exec_baseline(reversed_b)

    assert ns2["_clean_hashes"]["a"] == ns["_clean_hashes"]["a"]
    assert ns2["_clean_hashes"]["c"] == ns["_clean_hashes"]["c"]
    assert ns2["_clean_hashes"]["b"] != ns["_clean_hashes"]["b"]


def test_verify_cell_exact_row_delta_for_duplicate_rows():
    finding = _finding(9, "duplicate-rows", stats={"dup_count": 7})
    code = verify_cell("df", finding, BASELINE_COLS)
    assert "_clean_rows - 7" in code
    assert "len(df) == _clean_rows - 7" in code
    compile(code, "<v9>", "exec")


def test_verify_cell_bounded_row_delta_for_near_duplicate_merges():
    finding = _finding(10, "near-duplicates", stats={"pair_count": 3})
    code = verify_cell("df", finding, BASELINE_COLS)
    assert "_clean_rows - 3 <= len(df) <= _clean_rows" in code
    compile(code, "<v10>", "exec")


def test_verify_cell_exact_row_delta_for_rollup_rows():
    finding = _finding(21, "rollup-rows", stats={"rollup_count": 2})
    code = verify_cell("df", finding, BASELINE_COLS)
    assert "len(df) == _clean_rows - 2" in code
    compile(code, "<v21>", "exec")


def test_row_delta_constants_match_spec_r9():
    assert ROW_DELTA_EXACT == {9: "dup_count", 21: "rollup_count"}
    assert ROW_DELTA_BOUNDED == {10: "pair_count"}


def test_a_frozen_case_still_trips_the_detector_it_was_carved_from() -> None:
    """Admission asserts the case still exhibits the disease, or passing proves
    nothing. But the case concentrates sick rows (150 sick + 50 healthy), which
    moves every fraction-based threshold — and disease 22's density guard reads
    a dense integer range as a row counter rather than a code. Concentration
    must not flip either verdict."""
    zips = pd.DataFrame(
        {"zip_code": ([35233, 90210, 60614, 98101] * 30) + ([2115, 2116] * 20)}
    )
    assert detect_one(zips, 22, ["zip_code"]) is not None, "the column itself"

    short = zips["zip_code"].astype(str).str.len() < 5
    case = pd.concat(
        [
            zips[short].head(verify.CASE_SICK_ROWS),
            zips[~short].head(verify.CASE_HEALTHY_ROWS),
        ]
    ).sort_index()
    assert detect_one(case, 22, ["zip_code"]) is not None, (
        "the frozen case must still trip it, or admission refuses good skills"
    )

    sentinel = pd.DataFrame({"flow": ["N/A"] * 3 + [str(v) for v in range(200)]})
    sick = sentinel["flow"] == "N/A"
    thin = pd.concat(
        [sentinel[sick], sentinel[~sick].head(verify.CASE_HEALTHY_ROWS)]
    ).sort_index()
    assert detect_one(thin, 4, ["flow"]) is not None, (
        "a disease with only a handful of sick rows must survive the carve too"
    )


# --- integration pass: the guard's keying, executed against real frames ------


def _verify_frame(frame: pd.DataFrame, fix, columns) -> None:
    """The kernel round trip over an arbitrary frame: baseline, fix, verify.
    `columns` is the baseline column list the host reads back from the
    baseline cell, so the two sides agree the way the loop makes them agree."""
    namespace = {"df": frame}
    exec(compile(baseline_cell("df"), "<k-baseline>", "exec"), namespace)  # noqa: S102
    namespace["df"] = fix(namespace["df"])
    code = verify_cell("df", _finding(columns=("flow",)), columns)
    exec(compile(code, "<k-verify>", "exec"), namespace)  # noqa: S102


def test_a_non_string_column_name_does_not_break_the_guard():
    """The guard recorded untouched names as str() and then subscripted the
    frame with the recorded string, so one integer-named bystander raised
    KeyError on every finding in the frame: no fix on it could ever verify,
    and the model burned its whole attempt budget on the lookup. Reachable
    through crivo's own reader on any spreadsheet with year headers."""
    frame = _guard_frame().rename(columns={"site": 2020})

    _verify_frame(frame, _repair, ["2020", "flow", "note"])


def test_a_lossless_whole_frame_reorder_still_verifies():
    """The digest read values in frame order, so sorting or sampling the whole
    frame, every column moving together and nothing lost, failed the untouched
    check. Pairing each value with its index label and folding the pairs in
    sorted order keeps the tear-loose refusal below while letting the lossless
    move through."""
    _verify_after(lambda f: _repair(f).sort_values("site", ascending=False))


def test_a_reorder_that_also_resets_the_index_still_verifies():
    """Pairing each value with its index label put the index inside the guard,
    and `sort_values(...).reset_index(drop=True)` is one idiom, not two: the
    frame moves as a unit and every label is rewritten. The pairs then all
    change and the untouched guard refused a fix that lost nothing, which is
    over-refusal - a repair the model wrote correctly, reverted and counted
    against it."""
    _verify_after(
        lambda f: _repair(f).sort_values("site", ascending=False).reset_index(drop=True)
    )


def test_an_index_reset_does_not_excuse_a_column_torn_loose():
    """The other half, and the one that must not be traded away for the test
    above: a fix that rewrites the index AND tears one untouched column loose
    from its rows has to keep failing. Corruption is silent and a refusal is
    not."""
    import pytest

    def reorder_then_tear(frame: pd.DataFrame) -> pd.DataFrame:
        out = _repair(frame).sort_values("site", ascending=False)
        out = out.reset_index(drop=True)
        out["note"] = list(out["note"])[::-1]
        return out

    with pytest.raises(AssertionError, match="was not a fix target"):
        _verify_after(reorder_then_tear)


def test_the_whole_untouched_block_sliding_together_is_refused():
    """DELIBERATELY INVERTED. This was pinned as the documented price of the
    reorder exemption, on the reading that "once the index labels are gone"
    nothing can say whether the target column rode along. The labels are not
    gone here: this fix never touches the index, and the exemption's real
    precondition was only that the live index is a positional range - which
    every default-index frame satisfies, so the residual applied to almost
    every frame crivo reads rather than to reordered ones.

    Something CAN say whether the target rode along: the target column itself.
    A genuine reorder differs from the permuted baseline only on the cells the
    repair changed; a slid block leaves the target sitting still and disagrees
    with the permutation nearly everywhere. `rode_along` asks it, so this now
    refuses, and the guard is back to what the P2 index-pairing bought.

    The test above (`..._reorder_that_also_resets_the_index_still_verifies`)
    pins the recovery this must not cost."""
    import pytest

    def slide_the_block(frame: pd.DataFrame) -> pd.DataFrame:
        out = _repair(frame)
        rotated = list(range(1, len(out))) + [0]
        out[["site", "note"]] = out[["site", "note"]].iloc[rotated].to_numpy()
        return out

    with pytest.raises(AssertionError, match="was not a fix target"):
        _verify_after(slide_the_block)


def test_an_index_rewrite_with_one_untouched_column_is_refused():
    """The documented residual, pinned so it is not loosened by accident. With
    a single untouched column there is nothing left to pair it against: once
    the index labels are gone, "the frame moved as a unit" and "this column
    was permuted against the rest of the frame" are the same picture. The
    ambiguous case takes the refusal."""
    import pytest

    frame = _guard_frame()[["flow", "note"]]

    def reorder(f: pd.DataFrame) -> pd.DataFrame:
        return _repair(f).sort_values("note", ascending=False).reset_index(drop=True)

    with pytest.raises(AssertionError, match="was not a fix target"):
        _verify_frame(frame, reorder, ["flow", "note"])


def test_a_fix_that_wipes_a_name_shadowed_column_fails_verification():
    """The baseline kept ONE digest per NAME, and it keyed by str(name), so of
    two columns whose names str() alike only the survivor of the dict write
    was addressed by anything: the integer-named one could be emptied and the
    cell still reported VERIFIED. crivo manufactures this shape itself:
    _fix_headers str()s every name during a d18 repair, and the loop then
    re-snapshots the baseline over the collided names."""
    import pytest

    frame = _guard_frame().rename(columns={"site": 1, "note": "1"})
    assert list(frame.columns) == ["flow", 1, "1"]

    def wipe_the_shadowed(f: pd.DataFrame) -> pd.DataFrame:
        out = _repair(f)
        out.iloc[:, 1] = "WIPED"  # the integer-named column
        return out

    with pytest.raises(AssertionError, match="was not a fix target"):
        _verify_frame(frame, wipe_the_shadowed, ["1", "flow"])


def test_a_frame_with_duplicate_column_names_can_still_verify_an_honest_fix():
    """The other side of it: keying by name also meant the digest was computed
    over a two-column DataFrame at verify time and a single column at baseline
    time, so a frame carrying a duplicate name could never verify anything at
    all, however honest the fix."""
    frame = _guard_frame().rename(columns={"site": "note"})

    _verify_frame(frame, _repair, ["flow", "note"])


def test_a_constant_untouched_column_does_not_excuse_a_torn_neighbour():
    """The reorder exemption fires when EVERY untouched name is torn, and the
    packet treated that as the safety property: tearing a proper subset leaves
    the others' digests intact, so not every name is torn. A CONSTANT column
    refutes it. Its (index, value) digest is torn by the index rewrite like
    every other, and it adds nothing that distinguishes one row from another,
    so the whole-row multiset is blind to a neighbour torn loose beside it.

    crivo has an entire disease for constant columns (d19), so this is not an
    exotic frame in crivo's own model of dirty data. Every record's city ends
    up attached to the wrong price."""
    import pytest

    frame = pd.DataFrame(
        {
            "flow": ["N/A", "N/A"] + [str(v) for v in range(8)],
            "city": [f"city-{v}" for v in range(10)],
            "country": ["US"] * 10,
        },
        index=[f"r{v}" for v in range(10)],
    )

    def tear_past_the_constant(f: pd.DataFrame) -> pd.DataFrame:
        out = _repair(f)
        out["city"] = list(out["city"])[::-1]
        return out.reset_index(drop=True)

    with pytest.raises(AssertionError, match="was not a fix target"):
        _verify_frame(frame, tear_past_the_constant, ["flow", "city", "country"])


def test_a_target_a_header_repair_renamed_is_not_treated_as_untouched():
    """The other half of the cross-packet item 16 fix, and without it the
    detect half is inert. detect_one now resolves a frozen target onto the
    column an already-verified d18 repair renamed it to, but verify_cell still
    built its untouched list from the FROZEN name. The loop re-snapshots the
    baseline after every verified fix, so the baseline carries the NEW name,
    the frozen name matches nothing, and the renamed column lands in
    `untouched` - the one column the fix is licensed to change. The detector
    cleared and the untouched guard then tore the honest repair up.

    Resolved the same way detect_one resolves it, so the two halves cannot
    drift apart."""
    frame = pd.DataFrame(
        {
            "active": ["Y", "N", "yes", "no", "TRUE", "FALSE", "1", "0"] * 5,
            "n": range(40),
        }
    )
    finding = _finding(23, "boolean-chaos", columns=("  active ",))

    namespace = {"df": frame.copy()}
    exec(compile(baseline_cell("df"), "<r-baseline>", "exec"), namespace)  # noqa: S102
    namespace["df"] = namespace["df"].assign(
        active=namespace["df"]["active"].str.lower().isin(["y", "yes", "true", "1"])
    )
    code = verify_cell("df", finding, ["active", "n"])

    exec(compile(code, "<r-verify>", "exec"), namespace)  # noqa: S102


# --- row-removing fixes (d09, d10, d21), executed against real findings ------


def _verify_finding(frame: pd.DataFrame, finding: dict, fix) -> None:
    """The kernel round trip for a finding the real detector raised: baseline,
    the fix's effect on the live variable, then the verify cell. The baseline
    column list is the one the baseline cell itself reports, read back the way
    the loop reads it (sorted names). Returns when the fix verifies, raises
    whatever the verify cell raises when it does not."""
    namespace = {"df": frame}
    lines = baseline_cell("df").rstrip("\n").splitlines()
    exec(compile("\n".join(lines[:-1]), "<rm-baseline>", "exec"), namespace)  # noqa: S102
    columns = json.loads(
        eval(compile(lines[-1], "<rm-baseline-last>", "eval"), namespace)
    )
    namespace["df"] = fix(namespace["df"])
    code = verify_cell("df", finding, columns)
    exec(compile(code, "<rm-verify>", "exec"), namespace)  # noqa: S102


def _verdict(frame: pd.DataFrame, finding: dict, fix) -> str:
    """`_verify_finding` read the way the loop reads a verify cell: "verified"
    when it ran to its end, otherwise the refusal the model would be shown."""
    try:
        _verify_finding(frame, finding, fix)
    except AssertionError as exc:
        return f"refused: {exc}"
    return "verified"


def _double_posted() -> pd.DataFrame:
    """A till export that posted three sales twice (one of them three times).
    Invented values in the shape real ones arrive in: order ids keep their
    leading zeros, dates come in three formats, the amount is text carrying a
    thousands separator and two sentinels, and a missing discount is NaN,
    which the repeat copies exactly. Rows 4, 9 and 11 repeat rows 1, 6, 6."""
    rows = [
        ("00417", "2026-03-01", "Maple St", "12.50", 0.0),
        ("00418", "03/01/2026", "Maple St", "N/A", None),
        ("00419", "2026-03-02", "Harbour Rd", "7.25", 0.1),
        ("00420", "2026-03-02", "Harbour Rd", "1,204.00", 0.0),
        ("00418", "03/01/2026", "Maple St", "N/A", None),
        ("00421", "3/3/26", "Old Mill", "64.10", None),
        ("00422", "2026-03-03", "Old Mill", "0.99", 0.0),
        ("00423", "2026-03-04", "Maple St", "-", 0.25),
        ("00424", "2026-03-04", "Harbour Rd", "18.00", 0.0),
        ("00422", "2026-03-03", "Old Mill", "0.99", 0.0),
        ("00425", "2026-03-05", "Old Mill", "33.33", 0.0),
        ("00422", "2026-03-03", "Old Mill", "0.99", 0.0),
    ]
    columns = ["order_id", "sold_on", "store", "amount", "discount"]
    return pd.DataFrame(rows, columns=columns)


def _keyed_twice() -> pd.DataFrame:
    """A CRM export where two customers were keyed in twice by different
    people: once in capitals, once with stray spaces and a lower-case city.
    Ids keep their leading zeros, one phone is missing. Rows 4 and 6 are the
    later copies of rows 0 and 3."""
    rows = [
        ("00031", "ACME CORP", "Toronto", "416-555-0101", 120.0),
        ("00032", "Birch & Co", "Halifax", "902-555-0144", 0.0),
        ("00033", "Cedar Lane Bakery", "Regina", None, 57.5),
        ("00034", "Delta Freight", "Moncton", "506-555-0190", 980.25),
        ("00031", "Acme Corp", "toronto", "416-555-0101", 120.0),
        ("00035", "Elm Street Dental", "Victoria", "250-555-0112", 15.0),
        ("00034", "Delta  Freight ", "Moncton", "506-555-0190", 980.25),
        ("00036", "Fir & Pine", "Kelowna", "250-555-0177", 300.0),
    ]
    columns = ["customer_id", "name", "city", "phone", "balance"]
    return pd.DataFrame(rows, columns=columns)


def _keep_first_spelling(frame: pd.DataFrame) -> pd.DataFrame:
    """The honest drop-only merge: fold case and whitespace to find the
    copies, keep the first one as it was written, write nothing anywhere."""
    key = frame.apply(lambda s: s.astype(str).str.split().str.join(" ").str.casefold())
    return frame[~key.duplicated()]


def _regional_sales() -> pd.DataFrame:
    """A pivot export: a Subtotal under North and a Grand Total at the foot,
    whose label carries the trailing space pivot exports pad with. The rollup
    rows have no store; one detail row has no units. Hand-checked: North sums
    to 25 units and 2928.75, the four regions to 82 units and 9210.50."""
    rows = [
        ("North", "N-001", 12.0, 1440.00),
        ("North", "N-002", 9.0, 1080.50),
        ("North", "N-003", None, 312.25),
        ("North", "N-004", 4.0, 96.00),
        ("Subtotal", None, 25.0, 2928.75),
        ("South", "S-001", 7.0, 840.00),
        ("South", "S-002", 15.0, 1795.10),
        ("South", "S-003", 3.0, 45.90),
        ("East", "E-001", 11.0, 1320.00),
        ("East", "E-002", 6.0, 702.00),
        ("East", "E-003", 2.0, 18.50),
        ("West", "W-001", 8.0, 960.00),
        ("West", "W-002", 5.0, 600.25),
        ("Grand Total ", None, 82.0, 9210.50),
    ]
    return pd.DataFrame(rows, columns=["region", "store", "units", "revenue"])


def _branch_ledger() -> pd.DataFrame:
    """Eleven detail rows and ONE trailing Total, the classic real-world
    rollup, which the detector raises only because a column corroborates it:
    the Total's qty (30) and revenue (1072.96) are the sums of the rows above.
    SKUs keep their leading zeros; the Total row has none."""
    rows = [
        ("Maple St", "00101", 3, 120.00),
        ("Maple St", "00102", 1, 45.50),
        ("Harbour Rd", "00101", 2, 80.00),
        ("Harbour Rd", "00103", 6, 210.00),
        ("Old Mill", "00102", 4, 182.00),
        ("Old Mill", "00104", 1, 9.99),
        ("Old Mill", "00101", 5, 200.00),
        ("Kingsway", "00103", 2, 70.00),
        ("Kingsway", "00104", 3, 29.97),
        ("Kingsway", "00102", 1, 45.50),
        ("Bayview", "00101", 2, 80.00),
        ("Total", None, 30, 1072.96),
    ]
    return pd.DataFrame(rows, columns=["branch", "sku", "qty", "revenue"])


def _drop_rollups(label: str):
    """The honest d21 fix a model writes: drop the rows whose label, trimmed
    and case-folded, is a rollup word."""

    def fix(frame: pd.DataFrame) -> pd.DataFrame:
        name = frame[label].str.strip().str.casefold()
        return frame[~name.isin(["total", "subtotal", "grand total"])]

    return fix


@pytest.mark.parametrize("reset", [False, True], ids=["labels-kept", "index-reset"])
def test_an_honest_dedup_verifies(reset):
    """Regression for #255. Removing any row changes every (index label, value)
    digest, so every untouched column read as torn, and the reorder exemption
    only covers a move that keeps the row count. So the untouched guard refused
    every dedup, after the row invariant had already said exactly the planted
    copies were gone: the model's correct dedup was reverted on every attempt.
    Both spellings of the idiom have to verify, with the later copies dropped
    and the labels kept, and with the index reset over the survivors."""
    frame = _double_posted()
    finding = detect_one(frame, 9, [])
    assert finding is not None and finding["stats"]["dup_count"] == 3

    def dedup(f: pd.DataFrame) -> pd.DataFrame:
        out = f.drop_duplicates()
        return out.reset_index(drop=True) if reset else out

    assert _verdict(frame, finding, dedup) == "verified"


@pytest.mark.parametrize(
    ("make", "label", "flagged"),
    [(_regional_sales, "region", 2), (_branch_ledger, "branch", 1)],
    ids=["subtotal-and-grand-total", "lone-total"],
)
def test_dropping_the_flagged_rollup_rows_verifies(make, label, flagged):
    """Regression for #255. The d21 repair is to drop the rollup rows, and the
    untouched guard refused it for the reason it refused every dedup: the row
    count moved, so every untouched column's digest moved with it. The lone
    trailing Total is the case pinned beside the refusal below, where a fix
    drops a detail row instead of it."""
    frame = make()
    finding = detect_one(frame, 21, [label])
    assert finding is not None and finding["stats"]["rollup_count"] == flagged

    assert _verdict(frame, finding, _drop_rollups(label)) == "verified"


def test_an_honest_near_duplicate_merge_that_only_drops_rows_verifies():
    """Regression for #255. A d10 merge that keeps the first copy as written
    and drops the later one changes no surviving cell, and was refused by the
    untouched guard all the same, because the row count moved. In #78 the d10
    case hit its cap on every run after rejections of this kind."""
    frame = _keyed_twice()
    finding = detect_one(frame, 10, [])
    assert finding is not None and finding["stats"]["pair_count"] == 2

    assert _verdict(frame, finding, _keep_first_spelling) == "verified"


# The refusals pinned beside the repairs above. Each passes on dev, where every
# row removal is refused, and has to keep passing once honest removals verify.


@pytest.mark.parametrize("reset", [False, True], ids=["labels-kept", "index-reset"])
def test_a_dedup_that_also_edits_a_surviving_cell_is_refused(reset):
    """A dedup that also 'tidies' one untouched cell of a row that was never a
    copy (the thousands separator stripped out of an amount) changed a record
    it had no business touching. Verifying by surviving rows must still see
    that one cell, whichever way the index comes out. The refusal is fed back
    to the model, so it names no cell values."""
    frame = _double_posted()
    finding = detect_one(frame, 9, [])
    assert finding is not None

    def dedup_and_tidy(f: pd.DataFrame) -> pd.DataFrame:
        out = f.drop_duplicates().copy()
        out.loc[3, "amount"] = "1204.00"
        return out.reset_index(drop=True) if reset else out

    with pytest.raises(AssertionError, match="not a fix target") as refused:
        _verify_finding(frame, finding, dedup_and_tidy)
    assert "1,204.00" not in str(refused.value)
    assert "1204.00" not in str(refused.value)


def test_a_dedup_that_drops_a_non_duplicate_row_is_refused():
    """The right number of rows gone, but not the right rows: two of the three
    copies and one order that was never repeated. The row invariant cannot see
    it, so the detector has to, because one copy is still in the frame."""
    frame = _double_posted()
    finding = detect_one(frame, 9, [])
    assert finding is not None

    def drop_the_wrong_rows(f: pd.DataFrame) -> pd.DataFrame:
        return f.drop(index=[4, 9, 7])

    assert len(drop_the_wrong_rows(frame)) == len(frame) - finding["stats"]["dup_count"]
    with pytest.raises(AssertionError, match="signal still fires"):
        _verify_finding(frame, finding, drop_the_wrong_rows)


def test_a_row_removal_outside_the_row_removing_diseases_is_refused():
    """Only d09, d10 and d21 may remove rows. A d04 sentinel repair that also
    drops a row is refused by the row invariant, and its verify cell carries
    none of the surviving-rows arm, so nothing about it changed."""
    frame = _guard_frame()
    finding = detect_one(frame, 4, ["flow"])
    assert finding is not None

    assert "_survived" not in verify_cell("df", finding, ["flow", "note", "site"])
    with pytest.raises(AssertionError, match="must not add or drop rows"):
        _verify_finding(frame, finding, lambda f: _repair(f).drop(index=5))


def test_a_near_duplicate_merge_that_writes_into_the_survivor_is_refused():
    """A survivorship merge: drop the later copy, then write its tidier
    spelling over the copy that stayed. Merges that fill or rewrite surviving
    cells are out of scope for #255, so this stays refused, and the refusal
    names no cell values."""
    frame = _keyed_twice()
    finding = detect_one(frame, 10, [])
    assert finding is not None

    def merge_into_survivor(f: pd.DataFrame) -> pd.DataFrame:
        out = _keep_first_spelling(f).copy()
        out.loc[0, "name"] = "Acme Corp"
        return out

    with pytest.raises(AssertionError, match="not a fix target") as refused:
        _verify_finding(frame, finding, merge_into_survivor)
    assert "ACME CORP" not in str(refused.value)
    assert "Acme Corp" not in str(refused.value)


def test_dropping_a_detail_row_instead_of_a_lone_total_is_refused():
    """With a single Total row, dropping a detail row instead breaks the sum
    that corroborated the Total, so the detector goes quiet; one row went, so
    the row invariant holds; and every surviving row is unchanged. Nothing but
    a check on WHICH rows went can refuse it. The message is not pinned, since
    dev refuses this in the untouched guard and the branch in a d21 label
    check, but it must name no cell values."""
    frame = _branch_ledger()
    finding = detect_one(frame, 21, ["branch"])
    assert finding is not None and finding["stats"]["rollup_count"] == 1

    def drop_a_detail_row(f: pd.DataFrame) -> pd.DataFrame:
        return f.drop(index=5)

    bad = drop_a_detail_row(frame)
    assert detect_one(bad, 21, ["branch"]) is None, "the detector cannot see it"
    assert len(bad) == len(frame) - 1, "nor can the row invariant"
    with pytest.raises(AssertionError) as refused:
        _verify_finding(frame, finding, drop_a_detail_row)
    for value in ("Old Mill", "00104", "9.99"):
        assert value not in str(refused.value)


# --- review round 1: the holes a surviving-rows reading leaves open ----------


def _pivot_with_a_one_row_group() -> pd.DataFrame:
    """A pivot export with no id column, where Eastgate has a single store, so
    its detail row (label 8) and its Subtotal (label 9) are equal everywhere
    but the label column. Hand-checked: Northfield sums to 49 units and
    5496.75, Southport to 57 and 6185.50, the Grand Total to 119.5 and
    13302.65."""
    northfield = [
        (12.0, 1440.00),
        (9.0, 1080.50),
        (4.0, 96.00),
        (6.0, 720.00),
        (3.0, 360.25),
        (10.0, 1200.00),
        (5.0, 600.00),
    ]
    southport = [
        (7.0, 840.00),
        (15.0, 1795.10),
        (3.0, 45.90),
        (8.0, 960.00),
        (2.0, 24.00),
        (11.0, 1320.00),
        (6.0, 702.00),
        (1.0, 18.50),
        (4.0, 480.00),
    ]
    rows = [("Northfield", u, r) for u, r in northfield]
    rows += [("Subtotal", 49.0, 5496.75)]
    rows += [("Eastgate", 13.5, 1620.40), ("Subtotal", 13.5, 1620.40)]
    rows += [("Southport", u, r) for u, r in southport]
    rows += [("Subtotal", 57.0, 6185.50), ("Grand Total", 119.5, 13302.65)]
    return pd.DataFrame(rows, columns=["region", "units", "revenue"])


def test_an_honest_rollup_drop_with_a_reset_verifies_on_a_one_row_group():
    """The legitimate case beside the two refusals below. Under a reset the
    surviving rows are read as a subsequence of the baseline, and here two
    baseline rows fit the Eastgate detail row equally well outside the label
    column: the detail itself and its Subtotal. Dropping every rollup and
    resetting the index has to verify all the same."""
    frame = _pivot_with_a_one_row_group()
    finding = detect_one(frame, 21, ["region"])
    assert finding is not None and finding["stats"]["rollup_count"] == 4

    def drop_and_reset(f: pd.DataFrame) -> pd.DataFrame:
        return _drop_rollups("region")(f).reset_index(drop=True)

    assert _verdict(frame, finding, drop_and_reset) == "verified"


@pytest.mark.parametrize("reset", [True, False], ids=["index-reset", "labels-kept"])
def test_keeping_a_subtotal_in_place_of_its_equal_detail_row_is_refused(reset):
    """Regression for #255. Found in review round 1: drop every rollup but
    Eastgate's Subtotal, and drop Eastgate's detail row instead of it. One
    rollup row is left, it no longer sums the rest, so the detector goes
    quiet; four rows went, so the row invariant holds. Read as surviving rows,
    the kept Subtotal passes for the detail row: under a reset it is paired
    with the earliest baseline row that fits, and with labels kept it is
    handed the detail row's label. Either way every removed row looked like a
    flagged rollup, and the frame verified with a Subtotal still in it and a
    store's sales gone. The refusal is fed back to the model, so it names no
    values."""
    frame = _pivot_with_a_one_row_group()
    finding = detect_one(frame, 21, ["region"])
    assert finding is not None
    rollup = frame["region"].str.casefold().str.contains("total")
    detail = frame.index[frame["region"] == "Eastgate"][0]
    kept = detail + 1
    assert rollup[kept] and not rollup[detail]
    assert (
        frame.loc[detail, ["units", "revenue"]].tolist()
        == frame.loc[kept, ["units", "revenue"]].tolist()
    ), "the premise: the detail row equals its Subtotal outside the label"

    def keep_the_subtotal(f: pd.DataFrame) -> pd.DataFrame:
        out = f.drop(index=[i for i in f.index[rollup] if i != kept] + [detail])
        if reset:
            return out.reset_index(drop=True)
        return out.rename(index={kept: detail})

    bad = keep_the_subtotal(frame)
    assert detect_one(bad, 21, ["region"]) is None, "the detector cannot see it"
    assert len(bad) == len(frame) - finding["stats"]["rollup_count"]
    verdict = _verdict(frame, finding, keep_the_subtotal)
    assert verdict != "verified"
    for value in ("Eastgate", "1620.4", "13.5"):
        assert value not in verdict


def _nine_branch_pivot() -> pd.DataFrame:
    """Nine regions of five stores, each closed by its own 'Subtotal - <region>'
    row, and a Grand Total: ten distinct rollup labels in one column. The
    rollup rows carry no store, and each sums the units above it."""
    regions = [
        "Aldergrove",
        "Brookfield",
        "Cedarvale",
        "Dunmore",
        "Elmwood",
        "Fairview",
        "Glenmore",
        "Harbourside",
        "Ironwood",
    ]
    rows, grand = [], 0.0
    for k, region in enumerate(regions):
        units = [float((s + 1) * (k + 2)) for s in range(5)]
        code = region[:2].upper()
        rows += [(region, f"{code}-{s + 1:03d}", u) for s, u in enumerate(units)]
        rows.append((f"Subtotal - {region}", None, sum(units)))
        grand += sum(units)
    rows.append(("Grand Total", None, grand))
    return pd.DataFrame(rows, columns=["region", "store", "units"])


def test_an_honest_rollup_drop_with_more_than_eight_labels_verifies():
    """Regression for #255. Found in review round 1: the d21 check read the
    rollup labels from the finding, and the finding records at most eight of
    them, so on a pivot with a subtotal per region every honest fix was
    refused for the labels the finding never recorded."""
    frame = _nine_branch_pivot()
    finding = detect_one(frame, 21, ["region"])
    assert finding is not None and finding["stats"]["rollup_count"] == 10
    name = frame["region"].str.casefold()
    rollup = name.str.startswith(("subtotal", "grand total"))
    assert frame["region"][rollup].nunique() == 10

    def drop_every_rollup(f: pd.DataFrame) -> pd.DataFrame:
        name = f["region"].str.strip().str.casefold()
        return f[~name.str.startswith(("subtotal", "grand total"))]

    assert _verdict(frame, finding, drop_every_rollup) == "verified"


def test_a_dedup_that_sorts_and_keeps_its_labels_verifies():
    """The legitimate case beside the refusal below: the survivors moved, but
    each still sits under its own baseline label, so each can be checked."""
    frame = _double_posted()
    finding = detect_one(frame, 9, [])
    assert finding is not None

    def dedup_and_sort(f: pd.DataFrame) -> pd.DataFrame:
        return f.drop_duplicates().sort_values("store")

    assert _verdict(frame, finding, dedup_and_sort) == "verified"


def test_a_dedup_that_sorts_and_resets_the_index_is_refused():
    """A known limitation, pinned so it is not loosened by accident, and not a
    goal. Once the labels are gone the survivors can only be read in order,
    and a sort breaks the order, so a dedup that also sorts and resets is
    refused although it lost nothing. The docstring of `survived` says so."""
    frame = _double_posted()
    finding = detect_one(frame, 9, [])
    assert finding is not None

    def dedup_sort_reset(f: pd.DataFrame) -> pd.DataFrame:
        return f.drop_duplicates().sort_values("store").reset_index(drop=True)

    with pytest.raises(AssertionError, match="not a fix target"):
        _verify_finding(frame, finding, dedup_sort_reset)


def test_a_near_duplicate_fix_that_removes_no_rows_meets_the_digest_guard():
    """The other branch of the row-removing diseases: a d10 fix that removes
    nothing goes to the digest guard exactly as before. This one rewrites each
    later copy into an exact copy of the first and drops neither, so the d10
    signal goes quiet and the row count holds, and the respelled cells are
    still caught."""
    frame = _keyed_twice()
    finding = detect_one(frame, 10, [])
    assert finding is not None

    def respell_the_copies(f: pd.DataFrame) -> pd.DataFrame:
        out = f.copy()
        out.loc[4, ["name", "city"]] = [out.loc[0, "name"], out.loc[0, "city"]]
        out.loc[6, "name"] = out.loc[3, "name"]
        return out

    fixed = respell_the_copies(frame)
    assert len(fixed) == len(frame)
    assert detect_one(fixed, 10, []) is None, "the detector cannot see it"
    with pytest.raises(
        AssertionError, match=r"^column '\w+' changed \(values or row identity\)"
    ):
        _verify_finding(frame, finding, respell_the_copies)


def _meter_reads() -> pd.DataFrame:
    """A utility export: nineteen accounts, ids with leading zeros, two reads
    missing, and account 0007 read twice a hundredth of a kWh apart (label
    19), the drift d10 calls the same entity recorded twice. Twenty rows with
    two gaps puts the reading column at exactly 90% coverage."""
    holders = [
        "R. Okafor",
        "L. Tremblay",
        "M. Singh",
        "A. Kowalski",
        "J. Nakamura",
        "P. Dubois",
        "S. Haddad",
        "T. MacLeod",
        "E. Rossi",
        "K. Abara",
        "N. Lindqvist",
        "D. Chen",
        "F. Moreau",
        "G. Osei",
        "H. Byrne",
        "I. Petrov",
        "O. Fontaine",
        "U. Mensah",
        "V. Larsen",
    ]
    kwh = [
        412.5,
        388.0,
        None,
        501.25,
        297.75,
        None,
        640.0,
        455.5,
        520.0,
        318.25,
        602.0,
        275.5,
        433.0,
        389.75,
        711.0,
        298.0,
        456.25,
        510.5,
        377.0,
    ]
    rows = [(f"{i + 1:04d}", h, v) for i, (h, v) in enumerate(zip(holders, kwh))]
    rows.append(("0007", "S. Haddad", 640.01))
    return pd.DataFrame(rows, columns=["account", "holder", "kwh"])


@pytest.mark.parametrize("reset", [False, True], ids=["labels-kept", "index-reset"])
def test_an_honest_drift_merge_that_drops_the_later_read_verifies(reset):
    """The legitimate case beside the refusal below: the removed read has a
    kept partner that differs from it only by the drift d10 tolerates."""
    frame = _meter_reads()
    finding = detect_one(frame, 10, [])
    assert finding is not None and finding["stats"]["pair_count"] == 1

    def drop_the_later_read(f: pd.DataFrame) -> pd.DataFrame:
        out = f.drop(index=19)
        return out.reset_index(drop=True) if reset else out

    assert _verdict(frame, finding, drop_the_later_read) == "verified"


def test_a_near_duplicate_fix_that_drops_an_unrelated_row_is_refused():
    """Regression for #255. Found in review round 1: dropping one unrelated
    account instead of the repeated read takes the reading column below the
    coverage d10's drift pass needs, so the detector stops looking and goes
    quiet; one row went, inside the merge bound; and every survivor is
    unchanged. Nothing but a check that each removed row had a kept partner
    refuses it, and the refusal names no values."""
    frame = _meter_reads()
    finding = detect_one(frame, 10, [])
    assert finding is not None

    def drop_an_unrelated_account(f: pd.DataFrame) -> pd.DataFrame:
        return f.drop(index=11)

    bad = drop_an_unrelated_account(frame)
    assert detect_one(bad, 10, []) is None, "the detector cannot see it"
    assert len(frame) - finding["stats"]["pair_count"] <= len(bad) < len(frame)
    verdict = _verdict(frame, finding, drop_an_unrelated_account)
    assert verdict != "verified"
    for value in ("0012", "D. Chen", "275.5"):
        assert value not in verdict


def _two_exports() -> pd.DataFrame:
    """March's export and April's, concatenated the way pd.concat does by
    default: each keeps its own 0-based index, so labels 0 to 4 repeat, and
    April re-posts March's last two sales."""
    columns = ["order_id", "sold_on", "amount"]
    march = [
        ("00511", "2026-03-28", "14.00"),
        ("00512", "2026-03-29", "N/A"),
        ("00513", "03/30/2026", "2,310.50"),
        ("00514", "2026-03-30", "8.75"),
        ("00515", "2026-03-31", "61.20"),
        ("00516", "2026-03-31", "0.50"),
    ]
    april = [
        ("00515", "2026-03-31", "61.20"),
        ("00516", "2026-03-31", "0.50"),
        ("00517", "2026-04-01", "19.99"),
        ("00518", "4/1/26", "-"),
        ("00519", "2026-04-02", "120.00"),
    ]
    return pd.concat(
        [pd.DataFrame(march, columns=columns), pd.DataFrame(april, columns=columns)]
    )


def test_a_dedup_that_keeps_repeated_index_labels_is_refused():
    """A known limitation, pinned so it is not loosened by accident, and not a
    goal. With labels kept, a label that repeats cannot say which baseline row
    a survivor is, so the honest dedup is refused. The docstring of `survived`
    says so. Resetting the index is the way through, and it verifies."""
    frame = _two_exports()
    assert not frame.index.is_unique
    finding = detect_one(frame, 9, [])
    assert finding is not None and finding["stats"]["dup_count"] == 2

    with pytest.raises(AssertionError, match="not a fix target"):
        _verify_finding(frame, finding, lambda f: f.drop_duplicates())

    def dedup_and_reset(f: pd.DataFrame) -> pd.DataFrame:
        return f.drop_duplicates().reset_index(drop=True)

    assert _verdict(frame, finding, dedup_and_reset) == "verified"


# --- review round 2: d21 survivors are judged on every column ---------------


def _pivot_with_an_nbsp_label() -> pd.DataFrame:
    """_regional_sales with South's Subtotal added the way an HTML export
    writes it, indented with no-break spaces (South sums to 25 units and
    2681.00). The detector matches labels through pandas' string engine, where
    \\s does not cover NBSP, so it counts two rollups here and not three."""
    frame = _regional_sales()
    south = pd.DataFrame(
        [("\u00a0\u00a0Subtotal", None, 25.0, 2681.00)],
        columns=frame.columns,
        index=[7.5],
    )
    return pd.concat([frame, south]).sort_index().reset_index(drop=True)


def test_a_rollup_drop_that_leaves_a_label_the_detector_does_not_count_verifies():
    """Regression for #255. Found in review round 2: the check on the rows a
    d21 fix kept read rollup labels with Python's re, whose \\s covers NBSP,
    while the detector reads them through pandas' string engine, whose \\s
    does not. So a fix that removed exactly the rollups the finding counted
    was refused for a label the detector never counted."""
    frame = _pivot_with_an_nbsp_label()
    assert frame["region"].str.contains("\u00a0").sum() == 1
    finding = detect_one(frame, 21, ["region"])
    assert finding is not None
    assert finding["stats"]["rollup_count"] == 2, (
        "the premise: the detector does not count the NBSP-indented label"
    )

    def drop_the_counted_rollups(f: pd.DataFrame) -> pd.DataFrame:
        return f[~f["region"].isin(["Subtotal", "Grand Total "])]

    assert _verdict(frame, finding, drop_the_counted_rollups) == "verified"


def _padded_header_pivot() -> pd.DataFrame:
    """The one-row-group pivot with the label header padded the way a
    spreadsheet export pads it, 'region ', which d18 repairs by renaming."""
    return _pivot_with_a_one_row_group().rename(columns={"region": "region "})


@pytest.mark.parametrize("reset", [True, False], ids=["index-reset", "labels-kept"])
def test_keeping_a_subtotal_for_its_detail_row_under_a_header_repair_is_refused(
    reset,
):
    """Regression for #255. Found in review round 2: the attack from round 1
    (keep Eastgate's Subtotal, drop its detail row), with the padded label
    header repaired in the same fix. The check on the kept rows looked the
    label column up by the finding's frozen name, found nothing under the
    repaired one, and the frame verified with a Subtotal still in it. The
    refusal is about a kept row, so it does not say "not a fix target", and
    it names no values."""
    frame = _padded_header_pivot()
    finding = detect_one(frame, 21, ["region "])
    assert finding is not None
    rollup = frame["region "].str.casefold().str.contains("total")
    detail = frame.index[frame["region "] == "Eastgate"][0]
    kept = detail + 1
    assert rollup[kept] and not rollup[detail]

    def keep_the_subtotal_and_repair_the_header(f: pd.DataFrame) -> pd.DataFrame:
        out = f.drop(index=[i for i in f.index[rollup] if i != kept] + [detail])
        out = out.reset_index(drop=True) if reset else out.rename(index={kept: detail})
        return out.rename(columns={"region ": "region"})

    bad = keep_the_subtotal_and_repair_the_header(frame)
    assert detect_one(bad, 21, ["region "]) is None, "the detector cannot see it"
    verdict = _verdict(frame, finding, keep_the_subtotal_and_repair_the_header)
    assert verdict != "verified"
    assert "not a fix target" not in verdict
    for value in ("Eastgate", "1620.4", "13.5"):
        assert value not in verdict


def test_keeping_a_subtotal_disguised_with_a_zero_width_character_is_refused():
    """Regression for #255. Found in review round 2: the same attack under a
    reset, with a zero-width space written into the kept Subtotal's label.
    No rollup pattern matches 'Sub<ZWSP>total', so the check on the kept rows
    passed, and the label column, as a fix target, was never compared. A d21
    fix has no reason to rewrite a kept row's label, so the kept rows are
    judged on every column, and this one changed."""
    frame = _pivot_with_a_one_row_group()
    finding = detect_one(frame, 21, ["region"])
    assert finding is not None
    rollup = frame["region"].str.casefold().str.contains("total")
    detail = frame.index[frame["region"] == "Eastgate"][0]
    kept = detail + 1

    def keep_a_disguised_subtotal(f: pd.DataFrame) -> pd.DataFrame:
        out = f.drop(index=[i for i in f.index[rollup] if i != kept] + [detail])
        out = out.reset_index(drop=True)
        out.loc[out["region"] == "Subtotal", "region"] = "Sub\u200btotal"
        return out

    bad = keep_a_disguised_subtotal(frame)
    assert detect_one(bad, 21, ["region"]) is None, "the detector cannot see it"
    verdict = _verdict(frame, finding, keep_a_disguised_subtotal)
    assert verdict != "verified"
    assert "not a fix target" not in verdict
    for value in ("Eastgate", "1620.4", "13.5"):
        assert value not in verdict


def test_a_rollup_drop_that_blanks_the_surviving_labels_is_refused():
    """Regression for #255. Found in review round 2: dropping the rollups and
    blanking the label column of every row kept. With no labels left the
    detector has nothing to read, and the label column, as a fix target, was
    never compared, so the frame verified with every region gone."""
    frame = _regional_sales()
    finding = detect_one(frame, 21, ["region"])
    assert finding is not None

    def drop_and_blank(f: pd.DataFrame) -> pd.DataFrame:
        out = _drop_rollups("region")(f).copy()
        out["region"] = ""
        return out

    verdict = _verdict(frame, finding, drop_and_blank)
    assert verdict != "verified"
    assert "not a fix target" not in verdict
    for value in ("North", "N-001", "1440"):
        assert value not in verdict


def test_an_honest_rollup_drop_under_a_padded_label_header_verifies():
    """The legitimate case beside the refusals above: the rollups dropped and
    the padded header left as it is, for its own d18 fix."""
    frame = _padded_header_pivot()
    finding = detect_one(frame, 21, ["region "])
    assert finding is not None

    assert _verdict(frame, finding, _drop_rollups("region ")) == "verified"


def test_a_rollup_drop_that_also_repairs_the_label_header_is_refused():
    """The stated cost of judging a d21 fix's kept rows on every column,
    pinned so it is not loosened by accident, and not a goal. An honest
    rollup drop that also renames the padded label header in the same cell no
    longer carries the label column under the name the baseline recorded, so
    it is refused; the header repair has to come in its own d18 fix."""
    frame = _padded_header_pivot()
    finding = detect_one(frame, 21, ["region "])
    assert finding is not None

    def drop_and_repair_the_header(f: pd.DataFrame) -> pd.DataFrame:
        return _drop_rollups("region ")(f).rename(columns={"region ": "region"})

    verdict = _verdict(frame, finding, drop_and_repair_the_header)
    assert verdict != "verified"
    assert "not a fix target" not in verdict


def _price_list(drift: float, sign: int) -> pd.DataFrame:
    """Fifteen catalogue lines with SKUs that keep their leading zeros, and
    line 00004 keyed in a second time with its amount off by a relative
    `drift`. sign=-1 makes every amount a credit, so the pair sits below zero."""
    items = [
        "Hex bolt M8",
        "Hex nut M8",
        "Washer 8mm",
        "Wood screw 4x40",
        "Anchor 6mm",
        "Cable tie 200",
        "Hinge 75mm",
        "Bracket L50",
        "Wall plug 6",
        "Rivet 4.8",
        "Spring pin 3",
        "Eye bolt M10",
        "Shelf pin 5",
        "Castor 50mm",
        "Drawer slide",
    ]
    rows = [
        (f"{i + 1:05d}", item, sign * float(100 + 7 * i))
        for i, item in enumerate(items)
    ]
    sku, item, amount = rows[3]
    rows.append((sku, item, amount * (1 + drift)))
    return pd.DataFrame(rows, columns=["sku", "item", "amount"])


@pytest.mark.parametrize("sign", [1, -1], ids=["positive", "negative"])
@pytest.mark.parametrize(
    ("drift", "same_entity"),
    [(0.9e-3, True), (1.1e-3, False)],
    ids=["inside-tolerance", "outside-tolerance"],
)
def test_the_d10_partner_tolerance_is_the_detectors(drift, sign, same_entity):
    """`partnered` holds a copy of the drift tolerance _d10 keeps inline, so
    the two can drift apart unseen. Either side of the boundary, on positive
    and on negative amounts, the detector fires exactly when `partnered`
    accepts dropping the later line as a copy of the first."""
    frame = _price_list(drift, sign)
    copy = len(frame) - 1

    fires = detect_one(frame, 10, []) is not None
    assert fires == same_entity
    assert verify.partnered(frame, [copy]) == fires
