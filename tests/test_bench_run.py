"""The corpus and runner are the instrument's chassis: if the corpus quietly
stops covering a disease, or two builds of the same entry diverge, every
published number downstream is fiction — so coverage and determinism are the
first invariants, tested before any scoring runs."""

import pytest


def test_smoke_corpus_is_deterministic_and_covers_every_injector():
    from bench.corpus import SMOKE, build
    from bench.corrupt import INJECTORS

    covered: set[int] = set()
    names = [entry["name"] for entry in SMOKE]
    assert len(names) == len(set(names)), "corpus names must be unique"
    assert 12 <= len(SMOKE) <= 40, "smoke-sized by design (about 30 datasets)"
    for entry in SMOKE:
        pristine, dirty, truth = build(entry)
        _, _, again = build(entry)
        assert truth.frame_sha256 == again.frame_sha256, entry["name"]
        assert truth.to_json() == again.to_json(), entry["name"]
        assert len(dirty) >= len(pristine), entry["name"]
        assert truth.corruptions, entry["name"]
        covered |= set(entry["diseases"])
    assert covered == set(INJECTORS), sorted(set(INJECTORS) ^ covered)


def test_run_smoke_scores_corpus_and_writes_artifacts(tmp_path):
    from bench.run import run

    report = run(
        mode="smoke",
        results_dir=tmp_path / "results",
        results_md=tmp_path / "RESULTS.md",
        external_root=tmp_path / "no-such-data",  # absent => skipped, never fatal
        limit=4,  # machinery check on a slice; CI runs the unrestricted smoke
    )
    assert report["invariants"] == "ok"
    assert report["external"] == []
    assert (tmp_path / "results" / "smoke.json").exists()
    md = (tmp_path / "RESULTS.md").read_text()
    assert "deterministic mode baseline" in md
    rows = report["synthetic"]
    assert len(rows) == 4
    for row in rows:
        scores = row["scores"]
        assert {"detection", "end_to_end", "verification"} <= scores.keys()
        assert "attempted_diseases" in scores and "not_attempted_diseases" in scores
    agg = report["aggregates"]
    assert set(agg) >= {
        "detection_micro_f1_mean",
        "repair_f1_fixable_mean",
        "survived_rate_mean",
    }


def test_smoke_with_default_paths_leaves_published_results_md_untouched(
    tmp_path, monkeypatch
):
    """Regression for #3. CI, /ship and /promote all run `bench.run --smoke`,
    and it used to rewrite the tracked `bench/RESULTS.md` (the published full
    tables) with smoke numbers, one careless `git add` from being committed
    over them. Smoke's markdown belongs beside smoke.json in the git-ignored
    `bench/results/`; only --full writes `bench/RESULTS.md`. Run with the
    DEFAULT paths, since the defaults are what the CLI uses."""
    from bench.run import run

    monkeypatch.chdir(tmp_path)
    published = tmp_path / "bench" / "RESULTS.md"
    published.parent.mkdir(parents=True)
    sentinel = b"# bench results (full, 2026-09-07)\n\npublished tables, hands off\n"
    published.write_bytes(sentinel)

    run(mode="smoke", limit=2, external_root=tmp_path / "none")

    assert published.read_bytes() == sentinel, "smoke overwrote bench/RESULTS.md"
    smoke_md = tmp_path / "bench" / "results" / "smoke.md"
    assert smoke_md.exists(), "smoke markdown should land in bench/results/"
    assert "deterministic mode baseline" in smoke_md.read_text()


def test_full_with_default_paths_writes_published_results_md(tmp_path, monkeypatch):
    """Regression for #3. The other half of the new default: moving smoke's
    markdown out of `bench/RESULTS.md` must not also stop --full from writing
    the published tables there, or the refresh path silently goes dead. A full
    run with the DEFAULT paths writes `bench/RESULTS.md` and nothing to
    `bench/results/smoke.md`."""
    from bench.run import run

    monkeypatch.chdir(tmp_path)

    run(mode="full", limit=2, external_root=tmp_path / "none")

    published = tmp_path / "bench" / "RESULTS.md"
    assert published.exists(), "a full run should write bench/RESULTS.md"
    assert published.read_text().startswith("# Proving Ground results (full,")
    assert not (tmp_path / "bench" / "results" / "smoke.md").exists(), (
        "a full run wrote the smoke markdown"
    )


def test_sweep_hunts_exceptions_and_reports_a_ledger(monkeypatch):
    """Arc W3/H2: the corpus doubles as a fuzzer — sweep() runs detect+clean
    over expanded entries hunting EXCEPTIONS (not scores) and returns the
    ledger. A healthy slice yields an empty ledger; a booby-trapped detector
    lands in it with the dataset name and error, never a crash."""
    from bench import run as bench_run
    from bench.corpus import SMOKE

    ledger = bench_run.sweep(entries=SMOKE[:2])
    assert ledger == []

    def boom(df, name="df"):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(bench_run, "detect_all", boom)
    ledger = bench_run.sweep(entries=SMOKE[:2])
    assert len(ledger) == 2
    assert all("kaboom" in entry["error"] for entry in ledger)
    assert ledger[0]["name"] == SMOKE[0]["name"]


def _synthetic_row(
    name: str, survived, repair_f1, not_attempted=(), attempted=(1,)
) -> dict:
    """One `score_pair` row, cut down to the fields `_aggregate` reads."""
    return {
        "name": name,
        "diseases": sorted({*attempted, *not_attempted}),
        "scores": {
            "detection": {"micro": {"f1": 1.0}},
            "end_to_end": {
                "dirt_targeting": {"f1": 1.0},
                "repair": {"f1": repair_f1},
            },
            "verification": {"survived_rate": survived},
            "attempted_diseases": sorted(attempted),
            "not_attempted_diseases": list(not_attempted),
        },
    }


def test_survival_mean_publishes_the_denominator_it_averaged_over():
    """A dataset where crivo attempted nothing has an UNDEFINED survival rate,
    not a good one, so it stays out of the mean by design. The danger is the
    silence: without a published count the headline can rest on a handful of
    datasets while reading as if it covered the whole corpus. So the count of
    contributing datasets ships in the aggregates next to the rate."""
    from bench.run import _aggregate

    synthetic = [
        _synthetic_row("attempted-all-survived", 1.0, 1.0),
        _synthetic_row("attempted-half-survived", 0.5, 1.0),
        # attempted nothing on real dirt: repair is a measured zero (#86)
        _synthetic_row("attempted-nothing", None, 0.0),
        _synthetic_row("attempted-nothing-either", None, 0.0),
    ]
    agg = _aggregate(synthetic)

    assert agg["datasets"] == 4
    assert agg["survived_rate_mean"] == 0.75  # the two defined rates only
    assert agg["survival_defined_datasets"] == 2  # not 4: the denominator used


def test_survival_and_repair_denominators_reach_every_published_surface(
    monkeypatch, capsys
):
    """The aggregates dict is the least-read surface. RESULTS.md and the
    one-line smoke summary are what humans quote, so the denominator has to
    appear there too. A bare "survived 1.000" is the failure being fixed.

    A published count also has to name the universe it counts and the
    statistic it belongs to, or it just moves the hiding place. Repair's count
    is over the datasets it scored, which is a subset of the FULLY FIXABLE
    datasets, itself a subset of the corpus: phrased like survival's "over 2
    of 4" on the same line, "over 2 of 3" reads as 67% coverage when the truth
    is 2 of 4. So both counts denominate against the corpus and keep the
    fixable split as a parenthetical, and since #86 that parenthetical also
    counts the fully fixable datasets the declared rule left out ("undefined
    by design"). And both numbers are means of per-dataset ratios rather than
    pooled rates, so the word `mean` has to survive everywhere they are
    printed."""
    from bench import run as bench_run

    synthetic = [
        _synthetic_row("a", 1.0, 1.0),
        _synthetic_row("b", 0.5, 1.0),
        # d04 only: declared undefined by design, so out of the mean, counted
        _synthetic_row("c", None, 0.0, attempted=[4]),
        _synthetic_row("d", None, None, not_attempted=[3]),
    ]
    report = {
        "mode": "smoke",
        "date": "2026-09-06",
        "synthetic": synthetic,
        "external": [],
        "aggregates": bench_run._aggregate(synthetic),
    }

    md = bench_run._markdown(report)
    assert "survived-verification rate, mean over the 2/4 datasets" in md
    assert "repair F1, mean over the 2/4 datasets" in md
    assert "2 of the 3 fully fixable" in md  # the subset, still disclosed
    assert "1 undefined by design" in md  # and what the rule left out of it
    assert "rate, mean:" not in md  # the bare, un-denominated old label

    monkeypatch.setattr(bench_run, "run", lambda **kwargs: report)
    assert bench_run.main(["--smoke"]) == 0
    out = capsys.readouterr().out
    assert "survived mean 0.750 over 2 of 4" in out
    assert (
        "repair F1 mean 1.000 over 2 of 4 (2 of 3 fixable; 1 undefined by design)"
        in out
    )


def test_readme_rewrite_is_marker_scoped_and_full_only(tmp_path):
    import pytest

    from bench.run import _write_readme, run

    readme = tmp_path / "README.md"
    readme.write_text(
        "# x\n\nkeep-above\n\n<!-- bench:start -->\nold\n<!-- bench:end -->\n\nkeep-below\n"
    )
    report = {
        "date": "2026-09-02",
        "external": [],
        "aggregates": {
            "datasets": 4,
            "fully_fixable_datasets": 3,
            "repair_scored_datasets": 2,
            "repair_undefined_by_design_datasets": 1,
            "survival_defined_datasets": 2,
            "detection_micro_f1_mean": 0.5,
            "repair_f1_fixable_mean": None,
            "survived_rate_mean": 1.0,
        },
    }
    _write_readme(readme, report)
    text = readme.read_text()
    assert "keep-above" in text and "keep-below" in text and "old" not in text
    assert "0.500" in text and "—" in text  # None renders as a dash, not "None"
    # the storefront copy carries the denominators too: a rate published
    # without the count it averaged over is the bug this pins shut, and a
    # count published against a subset nothing on the page names is the same
    # bug one level up. So both rates denominate against the 4 datasets the
    # header advertises, and repair keeps its fixable split as well, with the
    # datasets the declared rule left out of it (#86).
    assert "(2/4; 2 of the 3 fully fixable; 1 undefined by design)" in text
    assert "attempted a fix (2/4)" in text
    assert "mean over" in text  # both are means of per-dataset ratios

    bare = tmp_path / "bare.md"
    bare.write_text("no markers here")
    with pytest.raises(ValueError, match="markers"):
        _write_readme(bare, report)

    with pytest.raises(ValueError, match="smoke never writes"):
        run(
            mode="smoke",
            write_readme=True,
            results_dir=tmp_path,
            results_md=tmp_path / "r.md",
        )


def test_only_d04_and_d19_are_declared_undefined_by_design():
    """Regression for #86. Which datasets leave the repair mean is a scoring
    decision, so the declared list is pinned: d04 (a cleared placeholder lands
    on missing, while the truth holds the value it replaced) and d19 (a
    dropped constant column cannot equal the truth column). Adding a disease
    moves datasets out of the published mean, so it lands with its own
    decision (DH3, #107, may add the d18 "Unnamed" header variant) and updates
    this pin in the same commit."""
    from bench import run as bench_run

    assert hasattr(bench_run, "REPAIR_UNDEFINED_BY_DESIGN"), (
        "the undefined-by-design rule is declared in bench.run"
    )
    declared = bench_run.REPAIR_UNDEFINED_BY_DESIGN
    assert set(declared) == {4, 19}
    assert all(isinstance(why, str) and why.strip() for why in declared.values())


@pytest.mark.parametrize("disease", [4, 19])
def test_a_declared_dataset_leaves_the_repair_mean_and_is_counted(disease):
    """Regression for #86. Once a miss scores 0, a d04 or d19 dataset measures
    P = R = 0 even when its fix was right, because the right fix can never
    equal the truth value. The declared rule takes it out of the mean by its
    diseases, not by its score, and the count of what it took out is
    published beside the mean."""
    from bench.run import _aggregate

    synthetic = [
        _synthetic_row("tx-whitespace", 1.0, 1.0, attempted=[6]),
        _synthetic_row("tx-case-spelling", 1.0, 0.8, attempted=[6, 7]),
        _synthetic_row(f"declared-d{disease:02d}", 1.0, 0.0, attempted=[disease]),
        _synthetic_row("tx-dates-mixed", None, None, attempted=(), not_attempted=[3]),
    ]
    agg = _aggregate(synthetic)

    # over the two scored datasets: (1.0 + 0.8) / 2 = 0.9. Averaging the
    # declared zero in would read (1.0 + 0.8 + 0.0) / 3 = 0.6.
    assert agg["repair_f1_fixable_mean"] == 0.9
    assert agg["fully_fixable_datasets"] == 3
    assert agg["repair_scored_datasets"] == 2
    assert agg["repair_undefined_by_design_datasets"] == 1
    assert "repair_defined_datasets" not in agg  # replaced, not kept beside


def test_a_compound_dataset_with_one_declared_disease_is_still_scored():
    """Regression for #86. The rule leaves a dataset out only when EVERY
    disease it attempted is declared. A compound mix of d04 with diseases
    whose repair is defined stays in the mean; a mix of d04 and d19 alone is
    declared."""
    from bench.run import _aggregate

    synthetic = [
        _synthetic_row("tx-whitespace", 1.0, 1.0, attempted=[6]),
        _synthetic_row("tx-compound-fixable", 1.0, 0.65, attempted=[1, 2, 4, 6]),
        _synthetic_row("tx-sentinels", 1.0, 0.0, attempted=[4]),
        _synthetic_row("declared-d04-d19", 1.0, 0.0, attempted=[4, 19]),
    ]
    agg = _aggregate(synthetic)

    # scored: tx-whitespace and the compound -> (1.0 + 0.65) / 2 = 0.825.
    # declared: the [4] and [4, 19] datasets. All four averaged would read
    # (1.0 + 0.65 + 0.0 + 0.0) / 4 = 0.4125.
    assert agg["repair_f1_fixable_mean"] == 0.825
    assert agg["repair_scored_datasets"] == 2
    assert agg["repair_undefined_by_design_datasets"] == 2


def test_an_undeclared_undefined_repair_stops_the_run_and_names_the_dataset():
    """Regression for #86. After the scorer change a fully fixable dataset
    with real dirt always scores a number, so an undeclared None means the
    instrument broke. Dropping it from the mean is how 124 real misses left
    the published 0.923; now it raises and says which dataset."""
    from bench.run import InvariantViolation, _aggregate

    synthetic = [
        _synthetic_row("tx-whitespace", 1.0, 1.0, attempted=[6]),
        _synthetic_row("tx-case-variants", 1.0, None, attempted=[7]),
    ]
    with pytest.raises(InvariantViolation, match="tx-case-variants"):
        _aggregate(synthetic)


def test_a_declared_or_unattempted_undefined_repair_does_not_stop_the_run():
    """Regression for #86, the pin beside the refusal above. A None repair F1
    is legitimate on a dataset the declared rule names and on one crivo could
    not fully attempt. Neither raises, and neither enters the mean."""
    from bench.run import _aggregate

    synthetic = [
        _synthetic_row("tx-whitespace", 1.0, 1.0, attempted=[6]),
        _synthetic_row("tx-sentinels", 1.0, None, attempted=[4]),
        _synthetic_row("tx-constant-col", 1.0, None, attempted=[19]),
        _synthetic_row("tx-dates-mixed", None, None, attempted=(), not_attempted=[3]),
    ]
    agg = _aggregate(synthetic)

    assert agg["repair_f1_fixable_mean"] == 1.0


def _scored_row(name: str, attempted: list, pristine, dirty, cleaned) -> dict:
    """A fully fixable synthetic row whose end_to_end block is real
    `score_end_to_end` output for the given cleaner."""
    from bench.score import score_end_to_end
    from bench.truth import GroundTruth

    truth = GroundTruth(
        seed=0,
        base="fixture",
        n_rows=len(pristine),
        n_cols=len(pristine.columns),
        frame_sha256="x",
    )
    return {
        "name": name,
        "diseases": list(attempted),
        "scores": {
            "detection": {"micro": {"f1": 1.0}},
            "end_to_end": score_end_to_end(pristine, dirty, cleaned, truth),
            "verification": {"survived_rate": 1.0},
            "attempted_diseases": list(attempted),
            "not_attempted_diseases": [],
        },
    }


@pytest.mark.parametrize(
    "dodge",
    [
        pytest.param("leave", id="changes-nothing-on-the-hard-case"),
        pytest.param("blank", id="blanks-the-hard-case-repairs-none"),
    ],
)
def test_dodging_the_hard_case_cannot_beat_attempting_it(dodge):
    """Regression for #86. Two cleaners agree on an easy dataset and part on
    a hard one: the honest one attempts the hard case and gets half of it; the
    dodge leaves it alone, or blanks it and repairs nothing. Both dodges used
    to score F1 None there, leave the mean, and publish 1.000 over one dataset
    against the honest 0.786 over two. Built from real `score_end_to_end`
    output, so the scorer and the aggregate are checked together."""
    import pandas as pd

    from bench.run import _aggregate

    # easy (d06): two padded region names, |D| = 2. Both cleaners strip them,
    # so C = D = K∩D: P = R = 1.0, F1 = 1.0
    region = pd.DataFrame({"region": ["North", "South", "East", "West"]})
    region_dirty = pd.DataFrame({"region": [" North", "South", "East  ", "West"]})
    easy = _scored_row("tx-whitespace", [6], region, region_dirty, region.copy())

    # hard (d01): every amount arrived as a money string, |D| = 4
    money = pd.DataFrame({"amount": [1200.0, 85.5, 40.0, 310.25]})
    money_dirty = pd.DataFrame(
        {"amount": ["$1,200.00", "85.50", "$40.00", "USD 310.25"]}
    )
    # honest: parses the first two right, misreads "USD 310.25" as 31025.0
    # and leaves "$40.00": C = 3 cells, C∩D∩K = 2,
    # P = 2/3, R = 2/4, F1 = 2*2/(3+4) = 4/7
    honest_hard = pd.DataFrame({"amount": [1200.0, 85.5, "$40.00", 31025.0]})
    # dodges: leave the column as it came (C = {}, P = 0/0, R = 0/4) or blank
    # every amount (C = 4 cells, none correct, P = 0/4, R = 0/4). F1 = 0.0
    dodged_hard = {
        "leave": money_dirty.copy(),
        "blank": pd.DataFrame({"amount": [float("nan")] * 4}),
    }[dodge]

    honest = _aggregate(
        [easy, _scored_row("tx-money-strings", [1], money, money_dirty, honest_hard)]
    )
    dodged = _aggregate(
        [easy, _scored_row("tx-money-strings", [1], money, money_dirty, dodged_hard)]
    )

    # honest: (1.0 + 4/7) / 2 = 0.7857; dodge: (1.0 + 0.0) / 2 = 0.5
    assert dodged["repair_f1_fixable_mean"] < honest["repair_f1_fixable_mean"]
    assert honest["repair_f1_fixable_mean"] == round((1.0 + 4 / 7) / 2, 4)
    assert dodged["repair_f1_fixable_mean"] == 0.5
    assert dodged["repair_scored_datasets"] == honest["repair_scored_datasets"] == 2


def test_every_fully_fixable_corpus_dataset_is_scored_or_declared(tmp_path):
    """Regression for #86, on real `score_pair` rows from a smoke slice that
    holds a declared dataset. Every fully fixable dataset is either in the
    repair mean or counted as undefined by design, the two counts add up to
    the fully fixable count, and the mean is over the scored rows' numbers,
    zeros included."""
    from bench import run as bench_run

    report = bench_run.run(
        mode="smoke",
        results_dir=tmp_path / "results",
        results_md=tmp_path / "smoke.md",
        external_root=tmp_path / "no-such-data",
        limit=4,
    )
    agg = report["aggregates"]
    assert {"repair_scored_datasets", "repair_undefined_by_design_datasets"} <= set(agg)

    rule = set(bench_run.REPAIR_UNDEFINED_BY_DESIGN)
    fixable = [
        r for r in report["synthetic"] if not r["scores"]["not_attempted_diseases"]
    ]
    declared = [
        r["name"]
        for r in fixable
        if r["scores"]["attempted_diseases"]
        and set(r["scores"]["attempted_diseases"]) <= rule
    ]
    scored = [
        r["scores"]["end_to_end"]["repair"]["f1"]
        for r in fixable
        if r["name"] not in declared
    ]
    assert declared, "the slice must hold a declared dataset, or this proves nothing"
    assert agg["repair_undefined_by_design_datasets"] == len(declared)
    assert agg["repair_scored_datasets"] == len(scored)
    assert (
        agg["repair_scored_datasets"] + agg["repair_undefined_by_design_datasets"]
        == agg["fully_fixable_datasets"]
    )
    assert None not in scored  # every scored dataset carries a number
    assert agg["repair_f1_fixable_mean"] == round(sum(scored) / len(scored), 4)


def test_the_external_table_prints_a_measured_zero_not_a_dash():
    """Regression for #86. hospital, flights and rayyan printed a dash for
    repair F1 where the truth is 0.000: cells changed, none repaired, P = R =
    0, and the old F1 called that undefined. Raha pairs are all-string, so
    this scores a hospital-shaped pair in string space and renders the
    external table. The dash stays for a real 0/0, which `_fmt` still owns."""
    import pandas as pd

    from bench import run as bench_run
    from bench.score import equivalent_str, score_end_to_end
    from bench.truth import GroundTruth

    # invented values in the hospital pair's shape; none is from the Raha data
    pristine = pd.DataFrame(
        {
            "provider_id": ["90417", "90452", "90486"],
            "town": ["quarnby", "velloch", "tarrisford"],
            "postcode": ["58146", "58273", "58391"],
            "telephone": ["5550142837", "5550198264", "5550173510"],
        }
    )
    dirty = pristine.copy()
    dirty.loc[0, "town"] = "quarxby"  # Raha's typo shape: a letter -> "x"
    dirty.loc[2, "postcode"] = "583x1"
    dirty.loc[1, "telephone"] = "55501x8264"
    # a cleaner that touches one dirty town and fixes nothing:
    # D = 3 cells, C = {(0,town)} ⊆ D, C∩D∩K = {}
    #   dirt:   P = 1/1, R = 1/3, F1 = 2*1/(1+3) = 0.500
    #   repair: P = 0/1, R = 0/3, F1 = 2*0/(1+3) = 0.000
    cleaned = dirty.copy()
    cleaned.loc[0, "town"] = "Quarxby"
    truth = GroundTruth(seed=0, base="external", n_rows=3, n_cols=4, frame_sha256="x")
    end_to_end = score_end_to_end(
        pristine, dirty, cleaned, truth, values_equal=equivalent_str
    )

    synthetic = [_synthetic_row("tx-whitespace", 1.0, 1.0, attempted=[6])]
    report = {
        "mode": "full",
        "date": "2026-10-19",
        "synthetic": synthetic,
        "external": [
            {
                "name": "hospital",
                "scores": {
                    "end_to_end": end_to_end,
                    "verification": {"survived_rate": None},
                },
            }
        ],
        "aggregates": bench_run._aggregate(synthetic),
    }

    md = bench_run._markdown(report)

    assert "| hospital | 0.500 | 0.000 | — |" in md


def test_the_invariants_hold_on_every_smoke_dataset():
    """Regression for #256, the pin beside the violations below. The real
    oracle and no-op pass the row invariant on every SMOKE dataset that
    plants rows, and a cell-only dataset, which carries no row block, is not
    held to it."""
    from bench.corpus import SMOKE, build
    from bench.run import _check_invariants

    row_datasets = 0
    for entry in SMOKE:
        pristine, dirty, truth = build(entry)
        _check_invariants(pristine, dirty, truth)
        row_datasets += any(c.granularity == "row" for c in truth.corruptions)
    assert row_datasets, "the smoke corpus plants no rows, so this proves nothing"


def _set_rows(**fields):
    """Overwrite fields of a result's row block, making one if it has none."""
    return lambda result: result.update(rows={**result.get("rows", {}), **fields})


# (whose result is broken, how). Each is a scorer that can no longer tell the
# oracle from the no-op on rows, which the cell-only invariant let through.
_BROKEN_ROW_SCORES = [
    pytest.param("no-op", _set_rows(recall=None), id="no-op-row-recall-undefined"),
    pytest.param(
        "no-op", lambda result: result.pop("rows", None), id="no-op-row-score-missing"
    ),
    pytest.param(
        "no-op",
        _set_rows(recall=0.04, removed=1, planted_removed=1),
        id="no-op-removed-a-planted-row",
    ),
    pytest.param(
        "oracle", lambda result: result.pop("rows", None), id="oracle-row-score-missing"
    ),
    pytest.param("oracle", _set_rows(recall=0.5), id="oracle-half-the-rows"),
]


@pytest.mark.parametrize("entry_name", ["tx-dup-rows", "tx-compound-hard"])
@pytest.mark.parametrize("side, breaks", _BROKEN_ROW_SCORES)
def test_a_broken_row_score_stops_the_run_and_names_the_dataset(
    monkeypatch, entry_name, side, breaks
):
    """Regression for #256. `_check_invariants` held the oracle to full
    repair recall and the no-op to no repairs on cells only, so on a row
    dataset it passed vacuously. On a dataset that plants rows the oracle's
    row recall must be 1.0 and the no-op's 0.0 (removed nothing, not
    undefined), and a missing row block is a violation itself."""
    import re

    from bench import run as bench_run
    from bench.corpus import SMOKE, build

    entry = next(e for e in SMOKE if e["name"] == entry_name)
    pristine, dirty, truth = build(entry)
    real = bench_run.score_end_to_end

    def scored(p, d, cleaned, t, *args, **kwargs):
        result = real(p, d, cleaned, t, *args, **kwargs)
        # the oracle hands back n_rows rows, the no-op every dirty row
        is_side = (
            len(cleaned) == t.n_rows if side == "oracle" else len(cleaned) == len(d)
        )
        if is_side:
            breaks(result)
        return result

    monkeypatch.setattr(bench_run, "score_end_to_end", scored)

    with pytest.raises(bench_run.InvariantViolation, match=re.escape(entry_name)):
        bench_run._check_invariants(pristine, dirty, truth)


def _row_dataset(name: str, disease: int, rows: dict) -> dict:
    """A row dataset's `score_pair` row: crivo has no fixer for its disease
    and its cells sit untouched, so repair F1 is None; plus its row block."""
    row = _synthetic_row(name, None, None, attempted=(), not_attempted=[disease])
    row["scores"]["end_to_end"]["rows"] = rows
    return row


# The summary line as d0180c4 prints it for the four rows below. docs/QA.md
# BENCH-01 pins this line's text on the real smoke run.
_SUMMARY_LINE = (
    "smoke: 4 synthetic + 0 external | detect µF1 1.000"
    " | repair F1 mean 0.750 over 2 of 4 (2 of 2 fixable; 0 undefined by design)"
    " | survived mean 0.750 over 2 of 4"
)


@pytest.mark.parametrize(
    "total_row, echo_rows, recall, precision, f1",
    [
        # d21: k = 1, 4 rows removed, the total row among them
        #   P = 1/4, R = 1/1, F1 = 2*0.25/1.25 = 0.4
        # d24: k = 2, 1 row removed, a planted one
        #   P = 1/1, R = 1/2, F1 = 2*0.5/1.5 = 2/3
        # means over the 2 row datasets: R = (1 + 0.5)/2 = 0.750,
        # P = (0.25 + 1)/2 = 0.625, F1 = (0.4 + 2/3)/2 = 0.533
        pytest.param(
            {
                "precision": 0.25,
                "recall": 1.0,
                "f1": 0.4,
                "planted": 1,
                "removed": 4,
                "planted_removed": 1,
            },
            {
                "precision": 1.0,
                "recall": 0.5,
                "f1": 2 / 3,
                "planted": 2,
                "removed": 1,
                "planted_removed": 1,
            },
            "0.750",
            "0.625",
            "0.533",
            id="rows-scored",
        ),
        # the keyless cleaner removes no row: P = 0/0 None, R = 0.0, F1 = 0.0
        # on both, so the means are R 0.000, F1 0.000 and P undefined
        pytest.param(
            {
                "precision": None,
                "recall": 0.0,
                "f1": 0.0,
                "planted": 1,
                "removed": 0,
                "planted_removed": 0,
            },
            {
                "precision": None,
                "recall": 0.0,
                "f1": 0.0,
                "planted": 2,
                "removed": 0,
                "planted_removed": 0,
            },
            "0.000",
            "—",
            "0.000",
            id="keyless-removes-no-row",
        ),
    ],
)
def test_the_smoke_summary_grows_a_row_line_and_keeps_its_line(
    monkeypatch, capsys, total_row, echo_rows, recall, precision, f1
):
    """Regression for #256. The smoke summary prints one new line: row
    recall, precision and F1, each a mean over the datasets that plant rows,
    with that count against the corpus. The existing summary line stays
    byte for byte what it was."""
    import re

    from bench import run as bench_run

    synthetic = [
        _synthetic_row("tx-whitespace", 1.0, 1.0, attempted=[6]),
        _synthetic_row("tx-case-variants", 0.5, 0.5, attempted=[7]),
        _row_dataset("tx-aggregate-row", 21, total_row),
        _row_dataset("tx-header-echo", 24, echo_rows),
    ]
    report = {
        "mode": "smoke",
        "date": "2026-10-24",
        "synthetic": synthetic,
        "external": [],
        "aggregates": bench_run._aggregate(synthetic),
    }
    monkeypatch.setattr(bench_run, "run", lambda **kwargs: report)

    assert bench_run.main(["--smoke"]) == 0
    lines = capsys.readouterr().out.splitlines()

    assert _SUMMARY_LINE in lines
    others = [line for line in lines if line != _SUMMARY_LINE]
    assert len(others) == 1, f"want one row line beside the summary, got {others}"
    row_line = others[0]
    assert "row" in row_line.lower(), row_line
    assert re.search(rf"recall\D*{re.escape(recall)}", row_line), row_line
    assert re.search(rf"precision\D*{re.escape(precision)}", row_line), row_line
    assert re.search(rf"F1\D*{re.escape(f1)}", row_line, re.IGNORECASE), row_line
    assert "over 2 of 4" in row_line, row_line


def test_the_keyless_cleaner_scores_row_recall_zero_on_the_row_datasets(
    tmp_path, monkeypatch, capsys
):
    """Regression for #256. The keyless cleaner removes no planted row (it
    defers row fixes by design), so on the SMOKE datasets that plant rows the
    new line reads recall 0.000 with precision undefined, which is a
    measurement, not a regression. Real `score_pair` rows, on those datasets
    plus one cell-only dataset."""
    from bench import corpus
    from bench import run as bench_run

    row_names = [
        "tx-dup-rows",
        "tx-near-dups",
        "tx-aggregate-row",
        "tx-header-echo",
        "tx-compound-hard",
    ]
    names = {"tx-whitespace", *row_names}
    monkeypatch.setattr(
        corpus, "SMOKE", [e for e in corpus.SMOKE if e["name"] in names]
    )
    report = bench_run.run(
        mode="smoke",
        results_dir=tmp_path / "results",
        results_md=tmp_path / "smoke.md",
        external_root=tmp_path / "no-such-data",
    )
    scored = {r["name"]: r["scores"]["end_to_end"] for r in report["synthetic"]}

    assert "rows" not in scored["tx-whitespace"]
    for name in row_names:
        rows = scored[name].get("rows")
        assert rows is not None, f"{name}: no row score"
        assert (rows["removed"], rows["recall"], rows["precision"]) == (0, 0.0, None)

    import re

    monkeypatch.setattr(bench_run, "run", lambda **kwargs: report)
    assert bench_run.main(["--smoke"]) == 0
    lines = capsys.readouterr().out.splitlines()
    row_line = next((line for line in lines if not line.startswith("smoke:")), "")
    # 5 row datasets, none with a row removed: R = 0.000, F1 = 0.000, and
    # precision 0/0 on every one, so its mean is undefined
    assert "over 5 of 6" in row_line, lines
    assert re.search(r"recall\D*0\.000", row_line), row_line
    assert re.search(r"precision\D*—", row_line), row_line
    assert re.search(r"F1\D*0\.000", row_line, re.IGNORECASE), row_line
