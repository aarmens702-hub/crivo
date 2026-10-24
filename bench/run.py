"""Headless Proving Ground runner (spec R5/R6).

`python -m bench.run --smoke` is the CI form: build every corpus entry twice
(determinism is invariant #1), check the oracle/no-op/round-trip invariants,
score everything, write results JSON + `bench/results/smoke.md`, exit nonzero
on any violation. `--full` runs the seeds-expanded corpus; only a full run
writes `bench/RESULTS.md` or may rewrite the README's marked bench section —
smoke numbers are for the terminal, not the storefront.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path

from bench import corpus
from bench.external import load_scored_pair
from bench.score import score_end_to_end, score_pair
from bench.truth import GroundTruth
from crivo.detect import detect_all

EXTERNAL = ["hospital", "flights", "beers", "rayyan"]
_MARK_START, _MARK_END = "<!-- bench:start -->", "<!-- bench:end -->"

# Diseases whose correct fix can never equal the truth value, so repair F1 on
# them is undefined by design. A fully fixable dataset whose every attempted
# disease is listed here leaves the repair mean by this rule, and is counted
# beside it; adding a disease moves datasets out of the published mean (#86).
REPAIR_UNDEFINED_BY_DESIGN: dict[int, str] = {
    4: "a cleared placeholder lands on missing; the truth holds the value it replaced",
    19: "a dropped constant column cannot equal the truth column",
}


class InvariantViolation(AssertionError):
    """The instrument itself is broken — no number it prints can be trusted."""


def _check_invariants(pristine, dirty, truth) -> None:
    if GroundTruth.from_json(truth.to_json()) != truth:
        raise InvariantViolation(f"{truth.base}: manifest does not round-trip")
    oracle = score_end_to_end(pristine, dirty, pristine, truth)
    if oracle["counts"]["dirty"] and oracle["repair"]["recall"] != 1.0:
        raise InvariantViolation(f"{truth.base}: oracle repair recall != 1.0")
    noop = score_end_to_end(pristine, dirty, dirty, truth)
    if noop["counts"]["repaired"] != 0:
        raise InvariantViolation(f"{truth.base}: no-op cleaner scored repairs")
    # planted rows sit past the cell grid, so the cell checks above pass
    # vacuously on them: hold the row score to the same oracle/no-op rule
    if any(c.granularity == "row" for c in truth.corruptions):
        if (oracle.get("rows") or {}).get("recall") != 1.0:
            raise InvariantViolation(f"{truth.base}: oracle row recall != 1.0")
        if (noop.get("rows") or {}).get("recall") != 0.0:
            raise InvariantViolation(f"{truth.base}: no-op row recall != 0.0")


def _mean(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def _repair_undefined_by_design(row: dict) -> bool:
    """True when every disease the row attempted is declared undefined."""
    attempted = set(row["scores"]["attempted_diseases"])
    return bool(attempted) and attempted <= set(REPAIR_UNDEFINED_BY_DESIGN)


def _aggregate(synthetic: list[dict]) -> dict:
    """The honest split: overall means, plus repair over only the datasets
    whose every disease has a deterministic fixer — never one blended number."""
    fixable = [row for row in synthetic if not row["scores"]["not_attempted_diseases"]]
    # a dataset can be "fully fixable" yet score zero repairs by design:
    # sentinel-clearing and constant-drops are correct fixes whose destination
    # (NaN, a removed column) can never equal the truth value. Which datasets
    # leave the repair mean is decided by their diseases against the declared
    # rule, never by their score: a measured zero stays in, and the count the
    # rule left out is published beside the mean.
    undefined_by_design = [r for r in fixable if _repair_undefined_by_design(r)]
    fixable_scored = [r for r in fixable if not _repair_undefined_by_design(r)]
    for r in fixable_scored:
        if r["scores"]["end_to_end"]["repair"]["f1"] is None:
            raise InvariantViolation(
                f"{r['name']}: repair F1 undefined on a fully fixable dataset"
                " the declared rule does not name"
            )
    # same rule for survival: a dataset where crivo attempted no fix has an
    # undefined survival rate, not a good one, so it stays out of the mean.
    # Excluding it is only honest if the count that WAS averaged travels with
    # the rate to every surface that prints it.
    survival_defined = [
        r for r in synthetic if r["scores"]["verification"]["survived_rate"] is not None
    ]
    # the row score exists only on datasets that plant rows; its precision is
    # undefined where nothing was removed, so that mean carries its own count
    row_scores = [
        r["scores"]["end_to_end"]["rows"]
        for r in synthetic
        if r["scores"]["end_to_end"].get("rows") is not None
    ]
    row_precisions = [s["precision"] for s in row_scores if s["precision"] is not None]
    return {
        "datasets": len(synthetic),
        "fully_fixable_datasets": len(fixable),
        "repair_scored_datasets": len(fixable_scored),
        "repair_undefined_by_design_datasets": len(undefined_by_design),
        "survival_defined_datasets": len(survival_defined),
        # a silent detector is a recall-0 detector: None counts as 0.0 here,
        # so the mean can never look better because a signal said nothing
        "detection_micro_f1_mean": _mean(
            [r["scores"]["detection"]["micro"]["f1"] or 0.0 for r in synthetic]
        ),
        "detection_silent_datasets": sum(
            1
            for r in synthetic
            if r["scores"]["detection"]["micro"]["f1"] in (None, 0.0)
        ),
        "repair_f1_fixable_mean": _mean(
            [r["scores"]["end_to_end"]["repair"]["f1"] for r in fixable_scored]
        ),
        "survived_rate_mean": _mean(
            [r["scores"]["verification"]["survived_rate"] for r in survival_defined]
        ),
        "row_scored_datasets": len(row_scores),
        "row_precision_defined_datasets": len(row_precisions),
        "row_recall_mean": _mean([s["recall"] for s in row_scores]),
        "row_precision_mean": _mean(row_precisions),
        "row_f1_mean": _mean([s["f1"] for s in row_scores]),
    }


def _fmt(value) -> str:
    return "—" if value is None else f"{value:.3f}"


def _markdown(report: dict) -> str:
    agg = report["aggregates"]
    lines = [
        f"# Proving Ground results ({report['mode']}, {report['date']})",
        "",
        "All numbers are the **deterministic mode baseline** — keyless",
        "`crivo.clean()`, no LLM. Diseases without a deterministic fixer are",
        'scored "not attempted", never blended into the fixable aggregate.',
        "",
        (
            f"- datasets: {agg['datasets']} synthetic"
            f" ({agg['fully_fixable_datasets']} fully fixable,"
            f" {agg['repair_scored_datasets']} with repair scored,"
            f" {agg['repair_undefined_by_design_datasets']} undefined by design)"
            f" + {len(report['external'])} external"
        ),
        (
            f"- detection micro-F1, mean incl. silence-as-zero:"
            f" {_fmt(agg['detection_micro_f1_mean'])}"
            f" — silent on {agg['detection_silent_datasets']}"
            f"/{agg['datasets']} datasets"
        ),
        (
            f"- repair F1, mean over the"
            f" {agg['repair_scored_datasets']}/{agg['datasets']} datasets with"
            f" repair scored ({agg['repair_scored_datasets']} of the"
            f" {agg['fully_fixable_datasets']} fully fixable;"
            f" {agg['repair_undefined_by_design_datasets']} undefined by design):"
            f" {_fmt(agg['repair_f1_fixable_mean'])}"
        ),
        (
            f"- survived-verification rate, mean over the"
            f" {agg['survival_defined_datasets']}/{agg['datasets']} datasets that"
            f" attempted a fix: {_fmt(agg['survived_rate_mean'])}"
        ),
        "",
        (
            "— means nothing to score: for dirt and repair F1, no scored cell"
            " was dirty and none changed (dirt in appended rows or an added"
            " column, which the cell grid doesn't see, lands here too); for"
            " detection, no finding and no planted disease; for survival, no"
            " fix was attempted. On a fully fixable dataset a miss is a"
            " measured 0.000 and stays in the repair mean. The repair mean"
            " leaves out datasets with a disease crivo has no fixer for, and,"
            " by declared rule, fully fixable datasets whose every disease is"
            " undefined by design: "
            + "; ".join(
                f"d{d:02d} ({why})" for d, why in REPAIR_UNDEFINED_BY_DESIGN.items()
            )
            + "."
        ),
        "",
        "## Synthetic corpus",
        "",
        "| dataset | diseases | detect µF1 | dirt F1 | repair F1 | survived |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["synthetic"]:
        s = row["scores"]
        lines.append(
            f"| {row['name']} | {','.join(str(d) for d in row['diseases'])}"
            f" | {_fmt(s['detection']['micro']['f1'])}"
            f" | {_fmt(s['end_to_end']['dirt_targeting']['f1'])}"
            f" | {_fmt(s['end_to_end']['repair']['f1'])}"
            f" | {_fmt(s['verification']['survived_rate'])} |"
        )
    lines += [
        "",
        "## External (Raha) datasets",
        "",
        "External dirt we did not design — scored in string space, disease",
        "taxonomy unknown, so detection columns don't apply.",
        "",
    ]
    if report["external"]:
        lines += [
            "| dataset | dirt F1 | repair F1 | survived |",
            "|---|---|---|---|",
        ]
        for row in report["external"]:
            s = row["scores"]
            lines.append(
                f"| {row['name']}"
                f" | {_fmt(s['end_to_end']['dirt_targeting']['f1'])}"
                f" | {_fmt(s['end_to_end']['repair']['f1'])}"
                f" | {_fmt(s['verification']['survived_rate'])} |"
            )
    else:
        lines.append("Not fetched — run `uv run python scripts/fetch_raha.py`.")
    return "\n".join(lines) + "\n"


def _write_readme(readme: Path, report: dict) -> None:
    text = readme.read_text()
    if _MARK_START not in text or _MARK_END not in text:
        raise ValueError(f"{readme}: bench markers missing")
    agg = report["aggregates"]
    block = "\n".join(
        [
            _MARK_START,
            (
                f"**Deterministic mode baseline** ({report['date']},"
                f" {agg['datasets']} synthetic + {len(report['external'])} external"
                " datasets, cell-level scoring, 0 labels):"
            ),
            "",
            "| metric | value |",
            "|---|---|",
            f"| detection micro-F1 (mean, silence = 0) | {_fmt(agg['detection_micro_f1_mean'])} |",
            (
                f"| repair F1, mean over datasets with repair scored"
                f" ({agg['repair_scored_datasets']}/{agg['datasets']};"
                f" {agg['repair_scored_datasets']} of the"
                f" {agg['fully_fixable_datasets']} fully fixable;"
                f" {agg['repair_undefined_by_design_datasets']} undefined by design)"
                f" | {_fmt(agg['repair_f1_fixable_mean'])} |"
            ),
            (
                f"| survived-verification rate, mean over datasets that"
                f" attempted a fix"
                f" ({agg['survival_defined_datasets']}/{agg['datasets']})"
                f" | {_fmt(agg['survived_rate_mean'])} |"
            ),
            "",
            "Full tables: `bench/RESULTS.md`.",
            _MARK_END,
        ]
    )
    head, rest = text.split(_MARK_START, 1)
    _, tail = rest.split(_MARK_END, 1)
    readme.write_text(head + block + tail)


def run(
    mode: str = "smoke",
    results_dir: Path = Path("bench/results"),
    results_md: Path | None = None,
    external_root: Path = Path("data/external/raha"),
    write_readme: bool = False,
    readme: Path = Path("README.md"),
    limit: int | None = None,
) -> dict:
    if write_readme and mode != "full":
        raise ValueError("smoke never writes the README (spec R5)")
    entries = corpus.SMOKE if mode == "smoke" else corpus.full_corpus()
    if limit is not None:
        entries = entries[:limit]  # tests exercise the machinery on a slice

    synthetic = []
    for entry in entries:
        pristine, dirty, truth = corpus.build(entry)
        _, _, again = corpus.build(entry)
        if (
            truth.frame_sha256 != again.frame_sha256
            or truth.to_json() != again.to_json()
        ):
            raise InvariantViolation(f"{entry['name']}: corpus build not deterministic")
        _check_invariants(pristine, dirty, truth)
        synthetic.append(
            {
                "name": entry["name"],
                "diseases": entry["diseases"],
                "scores": score_pair(pristine, dirty, truth, name=entry["name"]),
            }
        )

    external = []
    for name in EXTERNAL:
        try:
            clean_frame, dirty_frame, truth = load_scored_pair(name, root=external_root)
        except FileNotFoundError:
            continue  # not fetched — skipped, reported in the results markdown, never fatal
        external.append(
            {"name": name, "scores": score_pair(clean_frame, dirty_frame, truth, name)}
        )

    report = {
        "mode": mode,
        "date": str(datetime.now(tz=UTC).date()),
        "invariants": "ok",
        "synthetic": synthetic,
        "external": external,
        "aggregates": _aggregate(synthetic),
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{mode}.json").write_text(json.dumps(report, indent=1))
    if results_md is None:  # only a full run may rewrite the published tables
        results_md = (
            Path("bench/RESULTS.md") if mode == "full" else results_dir / "smoke.md"
        )
    results_md.parent.mkdir(parents=True, exist_ok=True)
    results_md.write_text(_markdown(report))
    if write_readme:
        _write_readme(readme, report)
    return report


def sweep(entries: list[dict] | None = None, seeds: int = 10) -> list[dict]:
    """The corpus as a fuzzer (arc W3/H2): run detect+clean over expanded
    entries hunting EXCEPTIONS, not scores. Returns the ledger — one entry
    per crash with the dataset name and error — and an empty ledger is the
    acceptance bar. Never raises for a single dataset's failure."""
    from crivo.autoclean import clean as _clean

    if entries is None:
        entries = corpus.full_corpus(seeds=seeds)
    ledger = []
    for entry in entries:
        try:
            _, dirty, _ = corpus.build(entry)
            detect_all(dirty, name=entry["name"])
            _clean(dirty)
        except Exception as exc:  # noqa: BLE001 - the whole point is catching them
            ledger.append(
                {"name": entry["name"], "error": f"{type(exc).__name__}: {exc}"}
            )
    return ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Proving Ground bench")
    parser.add_argument("--full", action="store_true", help="seeds-expanded corpus")
    parser.add_argument(
        "--smoke", action="store_true", help="CI-sized corpus (default)"
    )
    parser.add_argument("--write-readme", action="store_true")
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore", category=UserWarning)  # pandas parse chatter
    mode = "full" if args.full else "smoke"
    report = run(mode=mode, write_readme=args.write_readme)
    agg = report["aggregates"]
    print(
        f"{mode}: {agg['datasets']} synthetic + {len(report['external'])} external"
        f" | detect µF1 {_fmt(agg['detection_micro_f1_mean'])}"
        f" | repair F1 mean {_fmt(agg['repair_f1_fixable_mean'])}"
        f" over {agg['repair_scored_datasets']} of {agg['datasets']}"
        f" ({agg['repair_scored_datasets']} of {agg['fully_fixable_datasets']}"
        f" fixable; {agg['repair_undefined_by_design_datasets']} undefined by design)"
        f" | survived mean {_fmt(agg['survived_rate_mean'])}"
        f" over {agg['survival_defined_datasets']} of {agg['datasets']}"
    )
    print(
        f"rows removed: recall mean {_fmt(agg['row_recall_mean'])}"
        f" | F1 mean {_fmt(agg['row_f1_mean'])}"
        f" over {agg['row_scored_datasets']} of {agg['datasets']} that plant rows"
        f" | precision mean {_fmt(agg['row_precision_mean'])}"
        f" over {agg['row_precision_defined_datasets']}"
        f" of {agg['row_scored_datasets']} that removed a row"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
