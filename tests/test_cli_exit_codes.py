"""`crivo diagnose` as a data linter (bulletproof-core arc R4): exit codes a
CI pipeline can gate on, like ruff for data. 0 = nothing at/above the
threshold, 1 = findings the threshold cares about, 2 = could not run at all.

The threshold order is about judgment required, not severity: AUTO findings
are safe-to-fix housekeeping; GATE and HUMAN need a person. `--fail-on GATE`
(the default) means "fail me when something needs a human"."""

import json

import pandas as pd
import pytest


def _exit_code(monkeypatch, argv: list) -> int:
    """main()'s exit code whether it returns it or argparse raises it, so a
    parse refusal fails a test on its assertion instead of escaping it."""
    from crivo.__main__ import main

    monkeypatch.setattr("sys.argv", argv)
    try:
        return main()
    except SystemExit as exc:
        return exc.code


def _error_line(stderr: str) -> str:
    """argparse's one-line complaint, the last thing it writes to stderr."""
    return "".join([line for line in stderr.splitlines() if "error:" in line][-1:])


def _dirty_gate_csv(tmp_path):
    """A file whose findings include at least one GATE-or-above grade:
    an age column with impossible values trips d13 (GATE)."""
    path = tmp_path / "people.csv"
    pd.DataFrame({"age": [34, 45, 29, 150, -3, 61, 22, 58, 40, 33]}).to_csv(
        path, index=False
    )
    return path


def test_dirty_file_fails_at_the_default_gate_threshold(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["crivo", "diagnose", str(_dirty_gate_csv(tmp_path))]
    )
    from crivo.__main__ import main

    assert main() == 1
    assert "out-of-domain" in capsys.readouterr().out


def test_fail_on_never_and_clean_files_exit_zero(tmp_path, monkeypatch, capsys) -> None:
    """The zero paths: --fail-on never restores today's report-only behavior
    on a dirty file, and a genuinely clean file exits 0 at the default."""
    from crivo.__main__ import main

    dirty = _dirty_gate_csv(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["crivo", "diagnose", str(dirty), "--fail-on", "never"]
    )
    assert main() == 0

    clean_path = tmp_path / "clean.csv"
    pd.DataFrame({"height_cm": [171.2, 165.8, 180.1, 156.4, 177.7, 169.3]}).to_csv(
        clean_path, index=False
    )
    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(clean_path)])
    assert main() == 0
    capsys.readouterr()  # drain


def test_unreadable_file_exits_two_like_bad_arguments(
    tmp_path, monkeypatch, capsys
) -> None:
    """2 means 'could not run', matching argparse's own bad-argument exit —
    distinct from 1 ('ran, found problems') so CI can tell a broken pipeline
    from a dirty dataset."""
    from crivo.__main__ import main

    monkeypatch.setattr(
        "sys.argv", ["crivo", "diagnose", str(tmp_path / "no-such-file.csv")]
    )
    assert main() == 2
    assert "could not read" in capsys.readouterr().out


def test_json_output_survives_and_auto_threshold_is_stricter(
    tmp_path, monkeypatch, capsys
) -> None:
    """--json still prints one parseable object whatever the exit code; and
    --fail-on AUTO fails a file whose findings are all safe-to-fix, while the
    default GATE lets the same file pass (housekeeping isn't a person's
    problem)."""
    import json

    from crivo.__main__ import main

    words = [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
        "theta",
        "iota",
        "kappa",
        "mu",
        "nu",
    ]
    padded = tmp_path / "padded.csv"
    pd.DataFrame({"note": [f"  {w}  " for w in words]}).to_csv(padded, index=False)

    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(padded), "--json"])
    code = main()
    payload = json.loads(capsys.readouterr().out)
    grades = {f["grade"] for f in payload["findings"]}
    assert grades == {"AUTO"}, f"fixture must be AUTO-only, got {grades}"
    assert code == 0, "default GATE ignores safe-to-fix housekeeping"

    monkeypatch.setattr(
        "sys.argv", ["crivo", "diagnose", str(padded), "--json", "--fail-on", "AUTO"]
    )
    assert main() == 1
    json.loads(capsys.readouterr().out)  # still one parseable object


# --- `crivo diagnose` / `crivo clean` argument order (#15) -------------------


@pytest.mark.parametrize("sub", ["diagnose", "clean"])
def test_subcommand_help_prints_help_and_exits_zero(monkeypatch, capsys, sub) -> None:
    """Regression for #15. `crivo diagnose --help` used to be rewritten into
    `crivo --diagnose --help`, so argparse read --help as a missing FILE and
    exited 2 with `argument --diagnose: expected one argument`."""
    from crivo.__main__ import main

    monkeypatch.setattr("sys.argv", ["crivo", sub, "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "usage:" in out
    assert "--fail-on" in out


@pytest.mark.parametrize(
    "options_first",
    [
        ["--json", "--fail-on", "never", "{file}"],
        ["--fail-on", "never", "--json", "{file}"],
        ["--json", "{file}", "--fail-on", "never"],
    ],
)
def test_options_may_come_before_the_file(
    tmp_path, monkeypatch, capsys, options_first
) -> None:
    """Regression for #15. `crivo diagnose --json FILE` works the same as
    `crivo diagnose FILE --json`: same exit code, same JSON object."""
    csv_path = str(_dirty_gate_csv(tmp_path))

    argv = [csv_path if a == "{file}" else a for a in options_first]
    code = _exit_code(monkeypatch, ["crivo", "diagnose", *argv])
    captured = capsys.readouterr()
    assert code == 0, _error_line(captured.err)
    payload = json.loads(captured.out)
    assert "findings" in payload
    assert (payload["file"], payload["rows"], payload["columns"]) == (csv_path, 10, 1)

    reference = ["crivo", "diagnose", csv_path, "--json", "--fail-on", "never"]
    assert _exit_code(monkeypatch, reference) == 0
    assert payload == json.loads(capsys.readouterr().out)


def _no_model_clean(monkeypatch) -> dict:
    """The clean path with no model and no kernel: a fake key passes the
    provider gate, and the session and the one-shot clean only record what
    the CLI handed them."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    seen: dict = {"sessions": [], "cleaned": []}

    class FakeSession:
        def __init__(self, **kw):
            seen["sessions"].append(kw)

        def close(self):
            pass

    def fake_clean_once(session, path, name=None, policy="auto"):
        seen["cleaned"].append((path, name))
        return {"file": path, "variable": name, "needs_human": []}

    monkeypatch.setattr("crivo.loop.Session", FakeSession)
    monkeypatch.setattr("crivo.repl.run_clean_once", fake_clean_once)
    return seen


@pytest.mark.parametrize(
    ("options_first", "name", "autonomy"),
    [
        (["--json", "{file}"], None, "autonomous"),
        (
            ["--name", "people", "--autonomy", "careful", "--json", "{file}"],
            "people",
            "careful",
        ),
    ],
)
def test_clean_cleans_the_file_after_its_options(
    tmp_path, monkeypatch, capsys, options_first, name, autonomy
) -> None:
    """Regression for #15. Under `crivo clean` the positional FILE is the
    file cleaned, wherever the options sit."""
    seen = _no_model_clean(monkeypatch)
    csv_path = str(_dirty_gate_csv(tmp_path))

    argv = [csv_path if a == "{file}" else a for a in options_first]
    code = _exit_code(monkeypatch, ["crivo", "clean", *argv])
    captured = capsys.readouterr()
    assert code == 0, _error_line(captured.err)
    assert seen["cleaned"] == [(csv_path, name)]
    assert [kw["autonomy"] for kw in seen["sessions"]] == [autonomy]
    assert json.loads(captured.out.strip().splitlines()[-1])["file"] == csv_path


@pytest.mark.parametrize("sub", ["diagnose", "clean"])
def test_a_subcommand_without_a_file_is_refused_in_its_own_words(
    monkeypatch, capsys, sub
) -> None:
    """Regression for #15. A bare `crivo diagnose` is refused with exit 2,
    and the complaint names the subcommand the user typed and the FILE it
    needs, not the `--diagnose` flag the old argv rewrite invented."""
    code = _exit_code(monkeypatch, ["crivo", sub])
    line = _error_line(capsys.readouterr().err)
    assert code == 2
    assert f"--{sub}" not in line
    assert f"crivo {sub}" in line and "FILE" in line


@pytest.mark.parametrize(
    ("sub", "other_flag"), [("clean", "--diagnose"), ("diagnose", "--clean")]
)
def test_a_subcommand_does_not_run_the_other_mode(
    tmp_path, monkeypatch, capsys, sub, other_flag
) -> None:
    """Regression for #15. `crivo clean --diagnose FILE` gives clean no FILE,
    so it is refused; it must not quietly diagnose instead (and
    `crivo diagnose --clean FILE` must not start a clean). The legitimate
    forms beside it, `crivo clean --json FILE` and `crivo --diagnose FILE`,
    are pinned in the tests around this one."""
    seen = _no_model_clean(monkeypatch)
    csv_path = str(_dirty_gate_csv(tmp_path))

    code = _exit_code(monkeypatch, ["crivo", sub, other_flag, csv_path])
    out = capsys.readouterr().out
    assert code == 2
    assert out == "", "the other mode printed a report or a summary"
    assert seen == {"sessions": [], "cleaned": []}


@pytest.mark.parametrize(
    "argv",
    [
        ["--diagnose", "{file}", "--fail-on", "never"],
        ["--fail-on", "never", "--json", "--diagnose", "{file}"],
    ],
)
def test_the_legacy_diagnose_flag_still_works(
    tmp_path, monkeypatch, capsys, argv
) -> None:
    """Pin for #15: `--diagnose FILE` predates the subcommand and scripts use
    it (`--clean FILE` is pinned in test_loop_autonomy)."""
    csv_path = str(_dirty_gate_csv(tmp_path))

    argv = [csv_path if a == "{file}" else a for a in argv]
    assert _exit_code(monkeypatch, ["crivo", *argv]) == 0
    assert "out-of-domain" in capsys.readouterr().out


def test_a_bare_file_without_a_subcommand_is_refused(tmp_path, monkeypatch) -> None:
    """Pin for #15: `crivo FILE` names no mode, so argparse refuses it
    (exit 2) rather than guessing diagnose or starting the REPL."""
    from crivo.__main__ import main

    monkeypatch.setattr("sys.argv", ["crivo", str(_dirty_gate_csv(tmp_path))])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
