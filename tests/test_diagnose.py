"""Tests for `crivo diagnose` — the report you can get for free.

Everything else in this project needs an API key, a kernel, and trust. This
needs a file. It is the only surface where the strongest part of the codebase,
the detection engine, is reachable without a model being involved at all.
"""

import importlib.util
import json

import pandas as pd
import pytest

import crivo
from crivo import checkup


def write_csv(tmp_path):
    path = tmp_path / "beers.csv"
    pd.DataFrame(
        {
            "beer_name": [f"beer {i}" for i in range(40)],
            "ounces": ["12.0 oz", "16.0 oz.", "12.0 ounce", "16.0 OZ."] * 10,
            "ibu": ["N/A"] * 15 + [str(v) for v in range(25)],
        }
    ).to_csv(path, index=False)
    return path


def test_a_report_needs_no_model_no_kernel_and_no_key(tmp_path, monkeypatch) -> None:
    """The whole point: a stranger can run this on their own file before
    deciding whether to trust an agent with it."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    report = checkup.report(write_csv(tmp_path))

    assert "40 rows" in report and "3 columns" in report
    assert "numbers-as-strings" in report
    assert "ounces" in report


def test_the_cli_runs_without_an_api_key(tmp_path, monkeypatch, capsys) -> None:
    """__main__ exits 1 with no key, which is right for the agent and wrong
    for a report — needing a paid credential to be told your CSV has 'N/A' in
    it is the barrier this subcommand exists to remove."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(write_csv(tmp_path))])

    from crivo.__main__ import main

    assert main() == 0
    assert "numbers-as-strings" in capsys.readouterr().out


def test_the_clean_subcommand_is_headless_and_machine_readable(
    monkeypatch, capsys
) -> None:
    """`crivo clean <file> --json` is the orchestration surface: no
    prompts, chatter on stderr, one JSON object on stdout. The session runs
    with previews off (nobody reads them); AUTO fixes run and judgement calls
    are deferred, never decided. Since #30 there is no policy to hand the
    clean or to echo in the summary: the fake takes only what the CLI may
    pass, and the summary carries no "policy" key."""
    import json

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setattr("crivo.__main__.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["crivo", "clean", "data/messy.csv", "--json"])
    session_kw: dict = {}

    class FakeSession:
        def __init__(self, **kw):
            session_kw.update(kw)

        def close(self):
            pass

    monkeypatch.setattr("crivo.loop.Session", FakeSession)
    monkeypatch.setattr(
        "crivo.repl.run_clean_once",
        lambda session, path, name=None: {
            "file": path,
            "needs_human": ["fix 2/3 · merge variants"],
        },
    )
    from crivo.__main__ import main

    assert main() == 0
    out = capsys.readouterr().out
    payload = json.loads(out.strip().splitlines()[-1])
    assert payload["file"] == "data/messy.csv"
    assert "policy" not in payload, sorted(payload)
    assert session_kw.get("preview") is False


def test_resume_flag_reaches_the_session(monkeypatch) -> None:
    """P5 R9's last mile: --resume s16 must construct the Session with
    resume='s16'. Everything past the constructor is covered by the real
    kernel resume test; this pins the plumbing between argv and Session."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.delenv("CRIVO_PROVIDER", raising=False)
    monkeypatch.setattr("sys.argv", ["crivo", "--resume", "s16"])
    seen: dict = {}

    class Captures:
        def __init__(self, **kw):
            seen.update(kw)
            raise SystemExit  # constructor reached; nothing else should run

    monkeypatch.setattr("crivo.loop.Session", Captures)
    import pytest as _pytest

    from crivo.__main__ import main

    with _pytest.raises(SystemExit):
        main()
    assert seen.get("resume") == "s16"


def test_the_key_gate_matches_the_provider(monkeypatch, capsys) -> None:
    """R10 follow-through: with CRIVO_PROVIDER=claude, holding a DeepSeek
    key must not satisfy the gate, and the message must name the key the
    session would actually use."""
    monkeypatch.setenv("CRIVO_PROVIDER", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-the-right-provider")
    monkeypatch.setattr("sys.argv", ["crivo"])

    from crivo.__main__ import main

    assert main() == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out


def test_a_windows_encoded_export_still_gets_a_report(tmp_path) -> None:
    """HM Treasury's real March 2026 spend CSV carries a literal £ sign in
    Windows-1252; utf-8 dies at byte 0xa3 before a single detector runs — an
    encoding disease the loader itself was manufacturing into a crash. The
    fallback must be *loud*: a silently switched encoding is the exact
    found-nothing/didn't-check conflation this project exists to kill."""
    path = tmp_path / "spend.csv"
    rows = "Supplier,Amount\n" + "\n".join(f"Vendor {i},£{i}25.00" for i in range(30))
    path.write_bytes(rows.encode("cp1252"))

    report = checkup.report(path)

    assert "30 rows" in report
    assert "cp1252" in report, "the fallback must be reported, not silent"


def test_the_transaction_fixture_scores_against_its_own_ground_truth(tmp_path) -> None:
    """scripts/make_transactions.py plants four diseases on purpose so this
    report can be scored, not admired. The columns that matter most — amount
    in five money formats, posted_at in four timestamp formats — were the
    exact two the pre-A1 gate filed under "checked and clean"."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import make_transactions

    path = make_transactions.write(tmp_path)[0]  # q1, the un-drifted schema
    report = checkup.report(path)

    assert "amount" in report, "five money formats must not read as clean"
    assert "posted_at" in report, "four timestamp formats must not read as clean"
    assert "merchant" in report
    assert "N/A" in report or "sentinel" in report


def test_render_console_styles_findings_without_corrupting_the_facts(
    tmp_path, monkeypatch
) -> None:
    """The terminal report is styled for a person, but the facts must survive:
    the slug, the columns, and the counts are all still there in the captured
    output. rich degrades to plain text off a TTY, so a pipe or a test sees no
    escape codes — which is what keeps --json and piped output clean."""
    from io import StringIO

    from rich.console import Console

    from crivo import checkup

    # a developer shell exporting FORCE_COLOR/COLORTERM makes rich colour even
    # a StringIO console — correct rich behaviour, but this test asserts the
    # UNFORCED default, so neutralise the forcing the way CI's env has it
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("COLORTERM", raising=False)

    path = write_csv(tmp_path)
    frame = checkup.load(path)
    result = checkup.detect_all(frame, "beers.csv")
    buffer = StringIO()
    checkup.render_console(path, frame, result, console=Console(file=buffer, width=90))

    out = buffer.getvalue()
    assert "beers.csv" in out
    assert "numbers-as-strings" in out
    assert "ounces" in out
    assert "fixable" in out and "signals clear" in out
    assert "\x1b[" not in out, "no ANSI escapes when the console is not a TTY"


def spend_frame() -> pd.DataFrame:
    """40 rows of a vendor-spend export: zero-padded vendor ids, money as
    strings with a currency sign and thousands separators, and 8 "N/A" cells
    in the money column. No date-like column names, because pd.read_json
    converts those."""
    return pd.DataFrame(
        {
            "vendor_id": [f"{i:05d}" for i in range(7, 47)],
            "vendor": [f"Vendor {i}" for i in range(40)],
            "amount": ["$1,300.50", "$85.00", "$12,004.10", "$7.25"] * 8 + ["N/A"] * 8,
            "region": ["North", "South", "East", "West"] * 10,
        }
    )


# how each format is written; pandas infers gzip from the .gz suffix
WRITERS = {
    "spend.json": lambda df, p: df.to_json(p, orient="records"),
    "spend.jsonl": lambda df, p: df.to_json(p, orient="records", lines=True),
    "spend.xlsx": lambda df, p: df.to_excel(p, index=False),
    "spend.json.gz": lambda df, p: df.to_json(p, orient="records"),
}


@pytest.mark.parametrize("name", list(WRITERS))
def test_cli_diagnose_reads_json_jsonl_and_xlsx_like_the_library(
    tmp_path, name
) -> None:
    """Regression for #14. The CLI read every non-parquet file as CSV while
    `crivo.diagnose` read it by its format. A JSON records file is one line,
    so it came back as a bare header: 0 rows, every check clear, exit 0, a
    false clean the GitHub Action would pass. JSON lines came back one row
    short with a finding the data does not have, and xlsx died on an encoding
    error. One file must get one diagnosis, whichever door it came in by. The
    .json.gz case pins the compressed form of the same rule."""
    df = spend_frame()
    path = tmp_path / name
    WRITERS[name](df, path)

    try:
        payload = json.loads(checkup.report(path, as_json=True))
    except ValueError as exc:  # UnicodeDecodeError and ParserError included
        pytest.fail(f"checkup could not read {name}: {type(exc).__name__}: {exc}")
    library = {f["slug"] for f in crivo.diagnose(path).findings}

    assert payload["rows"] == 40  # spend_frame's rows, counted by hand
    assert {f["slug"] for f in payload["findings"]} == library
    assert "sentinel-missing" in library, "parity must not pass with both sides empty"


def test_cli_diagnose_json_with_planted_na_is_not_a_false_clean(
    tmp_path, monkeypatch, capsys
) -> None:
    """Regression for #14. `crivo diagnose x.json --fail-on never` exits 0
    either way, so the exit code cannot catch the false clean; the report
    itself must carry the rows and the planted "N/A"."""
    df = spend_frame()
    path = tmp_path / "spend.json"
    WRITERS["spend.json"](df, path)
    monkeypatch.setattr(
        "sys.argv",
        ["crivo", "diagnose", str(path), "--json", "--fail-on", "never"],
    )

    from crivo.__main__ import main

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 40  # spend_frame's rows, counted by hand
    assert "sentinel-missing" in {f["slug"] for f in payload["findings"]}


@pytest.mark.skipif(
    importlib.util.find_spec("xlrd") is not None,
    reason="xlrd is installed, so .xls has its reader",
)
def test_cli_diagnose_exits_2_on_xls_without_its_reader(
    tmp_path, monkeypatch, capsys
) -> None:
    """Regression for #14. crivo advertises .xls but does not ship xlrd, its
    reader. Once the CLI reads .xls the way the library does, a missing xlrd
    is a could-not-run: exit 2 with the file and the package named, never a
    traceback. Today the CLI sniffs the bytes as CSV and calls the file clean
    (0 rows, exit 0). The .xlsx case above is the legitimate twin it must
    still read."""
    path = tmp_path / "x.xls"
    # the OLE2 signature every .xls opens with, then an empty header block
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504)
    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(path)])

    from crivo.__main__ import main

    try:
        code = main()
    except ImportError as exc:
        pytest.fail(f"a missing optional reader escaped as a traceback: {exc}")
    out = capsys.readouterr().out
    assert code == 2
    assert "x.xls" in out and "xlrd" in out


@pytest.mark.parametrize("dirname", ["spend", "spend.parquet"])
def test_cli_diagnose_reads_a_parquet_directory_like_the_library(
    tmp_path, dirname
) -> None:
    """Regression for #14. A partitioned parquet export is a directory of
    part files; Spark names it like a file (spend.parquet/) and drops a
    _SUCCESS marker beside the parts. The CLI must read every part, the same
    rows and the same findings `crivo.diagnose` gets. This is the legitimate
    twin of the directory refusal below."""
    df = spend_frame()
    directory = tmp_path / dirname
    directory.mkdir()
    parts = [df.iloc[:24], df.iloc[24:]]  # the 8 "N/A" cells all land in part-1
    for i, part in enumerate(parts):
        part.to_parquet(directory / f"part-{i}.parquet", index=False)
    (directory / "_SUCCESS").touch()

    payload = json.loads(checkup.report(directory, as_json=True))
    library = {f["slug"] for f in crivo.diagnose(directory).findings}

    assert payload["rows"] == sum(len(p) for p in parts) == 40  # 24 + 16
    assert {f["slug"] for f in payload["findings"]} == library
    assert "sentinel-missing" in library, "parity must not pass with both sides empty"


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
@pytest.mark.parametrize(
    "dirname, files",
    [
        ("exports", []),
        ("spend.parquet", ["_SUCCESS"]),
        ("spend.parquet", ["_SUCCESS", ".DS_Store"]),
    ],
    ids=["empty", "success-marker-only", "success-and-ds-store"],
)
def test_cli_diagnose_exits_2_on_a_directory_with_no_table(
    tmp_path, monkeypatch, capsys, dirname, files, flags
) -> None:
    """Regression for #14. A directory with no data files (empty, or a Spark
    output whose job wrote only the _SUCCESS marker, with a Finder .DS_Store
    beside it) reads as a 0 x 0 frame, and 0 x 0 passes every check: exit 0,
    "the file is clean", a false clean the GitHub Action would pass. There is
    nothing to check, so it is a could-not-run: exit 2, never clean. The
    parquet directory above is the twin it must still read."""
    directory = tmp_path / dirname
    directory.mkdir()
    for name in files:
        (directory / name).touch()
    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(directory), *flags])

    from crivo.__main__ import main

    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    # the path is echoed back; drop it so a tmp dir name cannot match "clean"
    out = capsys.readouterr().out.replace(str(directory), "<dir>")
    assert code == 2
    assert "clean" not in out


def _short_schema_spend(conn):
    # 40 rows under a CREATE TABLE short enough that its bytes decode as
    # cp1252: zero-padded ids, money as strings, the last 8 amounts "N/A"
    conn.execute("create table spend (id text, amount text)")
    amounts = ["1300.50", "85.00", "12004.10", "7.25"] * 8 + ["N/A"] * 8
    conn.executemany(
        "insert into spend values (?, ?)",
        [(f"{i:05d}", amount) for i, amount in enumerate(amounts)],
    )


# what a SQLite file holds; each one is a database, never a csv
SQLITE_TABLES = {
    "spend-frame": lambda conn: spend_frame().to_sql("spend", conn, index=False),
    "short-schema-40-rows": _short_schema_spend,
    "empty-table": lambda conn: conn.execute(
        "create table spend (vendor_id text, amount text)"
    ),
}


def write_sqlite(path, table="spend-frame"):
    """A real SQLite file holding one of SQLITE_TABLES, closed after."""
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        SQLITE_TABLES[table](conn)
        conn.commit()
    finally:
        conn.close()
    return path


SQLITE_NAMES = ["spend.db", "spend.sqlite", "spend.sqlite3", "SPEND.DB"]


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
@pytest.mark.parametrize("table", ["short-schema-40-rows", "empty-table"])
def test_cli_diagnose_never_calls_a_sqlite_file_clean(
    tmp_path, monkeypatch, capsys, table, flags
) -> None:
    """Regression for #45. Sniffed as CSV, a SQLite file whose header bytes
    happen to decode reads as garbage: 40 rows under a short schema come back
    as 20 rows of one column with a duplicate-rows finding, and an empty
    table as 2 rows and "nothing found — the file is clean". Both exit 0, a
    false clean the GitHub Action would pass. A database is a could-not-run
    for `crivo diagnose`: exit 2, never clean."""
    path = write_sqlite(tmp_path / "spend.db", table)
    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(path), *flags])

    from crivo.__main__ import main

    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    # the path is echoed back; drop it so a tmp dir name cannot match "clean"
    out = capsys.readouterr().out.replace(str(path), "<file>")
    assert code == 2
    assert "clean" not in out


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
@pytest.mark.parametrize("name", SQLITE_NAMES)
def test_cli_diagnose_exits_2_on_a_sqlite_file_and_points_to_crivo_read(
    tmp_path, monkeypatch, capsys, name, flags
) -> None:
    """Regression for #45. `checkup.load` sniffs an unknown suffix as CSV, so
    a SQLite database came back as garbage rows and could exit 0, "clean". A
    database file has no one table to check: it is a could-not-run, exit 2,
    and the message names the file and the way to read it (`crivo.read(path,
    query="select ...")`). The message is asserted as well as the code,
    because the bytes may already exit 2 by luck through a parse error that
    says nothing useful."""
    path = write_sqlite(tmp_path / name)
    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(path), *flags])

    from crivo.__main__ import main

    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    # the path is echoed back; drop it so the message itself must name the
    # file, and a tmp dir name cannot match "clean"
    out = capsys.readouterr().out.replace(str(path), "<file>")
    assert code == 2
    assert name in out, "the refusal must name the file"
    assert "crivo.read" in out and "query=" in out
    assert "clean" not in out


@pytest.mark.parametrize("name", SQLITE_NAMES)
def test_checkup_load_refuses_a_sqlite_file_like_the_library(tmp_path, name) -> None:
    """Regression for #45. The library refuses a SQLite file without a query;
    `checkup.load`, the door `crivo diagnose` and the analyst's /load share,
    must refuse it too, by name and with the `crivo.read(path, query=...)`
    pointer, and in words that fit either surface."""
    path = write_sqlite(tmp_path / name)

    with pytest.raises(ValueError):
        crivo.diagnose(path)
    with pytest.raises(ValueError, match=r"crivo\.read\(.*query=") as excinfo:
        checkup.load(path)
    assert name in str(excinfo.value)
    assert "crivo diagnose" not in str(excinfo.value)


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
def test_a_db_file_is_refused_by_its_suffix_not_its_bytes(
    tmp_path, monkeypatch, capsys, flags
) -> None:
    """Regression for #45. The refusal goes by the suffix alone and never
    opens the file, so a notes.db that holds csv text, not SQLite pages, is
    refused the same way. The message must not then claim the file is a
    SQLite database: crivo never looked."""
    path = tmp_path / "notes.db"
    spend_frame().to_csv(path, index=False)

    with pytest.raises(ValueError, match=r"crivo\.read\(.*query=") as excinfo:
        checkup.load(path)
    assert "is a SQLite database" not in str(excinfo.value)

    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(path), *flags])

    from crivo.__main__ import main

    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    # the path is echoed back; drop it so a tmp dir name cannot match "clean"
    out = capsys.readouterr().out.replace(str(path), "<file>")
    assert code == 2
    assert "notes.db" in out and "crivo.read" in out and "query=" in out
    assert "is a SQLite database" not in out
    assert "clean" not in out


def _write_sqlite_header_csv(df, path):
    # a text first line that opens with the SQLite magic words, but no NUL:
    # a csv by its suffix, whatever its first bytes say
    df.rename(columns={"vendor_id": "SQLite format 3"}).to_csv(path, index=False)


# files that sit next to the refusal and must still be read: the suffix
# decides, and only the final one
STILL_READ = {
    "spend.csv": lambda df, p: df.to_csv(p, index=False),
    "sqlite-header.csv": _write_sqlite_header_csv,
    "export.db.csv": lambda df, p: df.to_csv(p, index=False),
    "spend.parquet": lambda df, p: df.to_parquet(p, index=False),
    "spend.feather": lambda df, p: df.to_feather(p),
}


@pytest.mark.parametrize("name", list(STILL_READ))
def test_cli_diagnose_still_reads_the_files_beside_the_sqlite_refusal(
    tmp_path, monkeypatch, capsys, name
) -> None:
    """Regression for #45. The legitimate twins of the SQLite refusal: a
    plain csv, a csv whose first line starts "SQLite format 3,", a csv whose
    name carries ".db" before its real suffix, and a single parquet or
    feather file. Each is read whole (spend_frame's 40 rows), never refused."""
    path = tmp_path / name
    STILL_READ[name](spend_frame(), path)
    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(path), "--json"])

    from crivo.__main__ import main

    code = main()
    out = capsys.readouterr().out
    assert code != 2, "a readable file must not be a could-not-run"
    assert json.loads(out)["rows"] == 40  # spend_frame's rows, counted by hand


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
def test_cli_diagnose_a_missing_db_file_is_still_no_such_file(
    tmp_path, monkeypatch, capsys, flags
) -> None:
    """Regression for #45. The SQLite refusal is for a file that exists; a
    missing nope.db keeps the plain could-not-read of QA CLI-03 (exit 2, "No
    such file"), not a pointer to a query it has nothing to run on."""
    path = tmp_path / "nope.db"
    monkeypatch.setattr("sys.argv", ["crivo", "diagnose", str(path), *flags])

    from crivo.__main__ import main

    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr().out
    assert code == 2
    assert "No such file" in out


def write_customers_csv(tmp_path):
    """40 rows of a CRM customer export: zero-padded ids, money as strings,
    and two padded text columns. 16 emails carry stray spaces (every row with
    i % 5 in {0, 1}), one is "N/A" and one is blank; 20 cities are padded.
    Only `email` holds PII, so `city` is the twin that must stay raw."""
    names = [
        "ana.souza",
        "kemi.okafor",
        "min_lee",
        "priya.nair",
        "tom-hughes",
        "wei.zhang",
        "aoife.obrien",
        "sam.reyes",
        "lars.berg",
        "dee.ndiaye",
    ]
    domains = ["example.com", "Mail.co.uk", "corp.io", "example.org"]
    emails = [f"{names[i % 10]}{i:02d}@{domains[i % 4]}" for i in range(40)]
    emails = [
        "  " + e if i % 5 == 0 else e + " " if i % 5 == 1 else e
        for i, e in enumerate(emails)
    ]
    emails[37], emails[38] = "N/A", ""
    cities = ["Lisbon", "Leeds", "Lagos", "Seoul", "Pune", "York", "Wuhan", "Cork"] * 5
    cities = [
        " " + c if i % 4 == 0 else c + "  " if i % 4 == 1 else c
        for i, c in enumerate(cities)
    ]
    frame = pd.DataFrame(
        {
            "customer_id": [f"{i:06d}" for i in range(31, 71)],
            "email": emails,
            "city": cities,
            "balance": ["$1,204.50", "$88.00", "$12,000.75", "$7.10"] * 10,
        }
    )
    path = tmp_path / "customers.csv"
    frame.to_csv(path, index=False)
    local_parts = [e.strip().split("@")[0] for e in emails if "@" in e]
    return path, local_parts


TEXT_REPORTS = {
    "crivo-diagnose-text": lambda path: checkup.report(path),
    "print-report": lambda path: str(crivo.diagnose(path)),
}


@pytest.mark.parametrize("surface", list(TEXT_REPORTS))
def test_text_report_masks_evidence_from_pii_flagged_columns(tmp_path, surface) -> None:
    """Regression for #22. The GitHub Action prints the `crivo diagnose`
    text report into CI logs, public on a public repo, and `print(report)`
    renders the same text. A padded email column showed its raw addresses as
    whitespace-damage samples. The finding must still be there with its
    samples in the masked form (`***@` plus the domain), and no local part
    may reach the text. `city` is padded too but holds no PII, so its raw
    samples stay: masking is for flagged columns, not every quoted value."""
    path, local_parts = write_customers_csv(tmp_path)

    out = TEXT_REPORTS[surface](path).replace(str(path), "<file>")

    assert "whitespace-damage" in out
    assert sum(local in out for local in local_parts) == 0, (
        "raw email local parts reached the text report"
    )
    assert "***@" in out, "the email samples must be masked, not dropped"
    assert "' Lisbon'" in out and "'Leeds  '" in out, "non-PII samples stay raw"


@pytest.mark.parametrize("via", ["render_console", "cli"])
def test_the_styled_report_masks_evidence_too(
    tmp_path, monkeypatch, capsys, via
) -> None:
    """Regression for #22. `crivo diagnose FILE` (what action.yml runs) prints
    through `render_console`, not `render`, so the styled report must mask
    the same way. The console is wide so a long evidence line cannot wrap a
    sample apart and pass or fail on layout instead of on the masking."""
    from io import StringIO

    from rich.console import Console

    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("COLORTERM", raising=False)
    path, local_parts = write_customers_csv(tmp_path)

    if via == "render_console":
        frame = checkup.load(path)
        result = checkup.detect_all(frame, path.name)
        buffer = StringIO()
        console = Console(file=buffer, width=200)
        checkup.render_console(path, frame, result, console=console)
        out = buffer.getvalue()
    else:
        monkeypatch.setenv("COLUMNS", "200")
        monkeypatch.setattr(
            "sys.argv", ["crivo", "diagnose", str(path), "--fail-on", "never"]
        )
        from crivo.__main__ import main

        assert main() == 0
        out = capsys.readouterr().out
    out = out.replace(str(path), "<file>")

    assert "whitespace-damage" in out
    assert sum(local in out for local in local_parts) == 0, (
        "raw email local parts reached the styled report"
    )
    assert "***@" in out, "the email samples must be masked, not dropped"
    assert "' Lisbon'" in out and "'Leeds  '" in out, "non-PII samples stay raw"


def test_diagnose_json_keeps_the_raw_evidence(tmp_path) -> None:
    """#22 masks the text report only. `crivo diagnose --json` is the
    programmatic output and is exempt in the contract ("PII masking"), so its
    email evidence still carries the real samples a fix would need."""
    path, local_parts = write_customers_csv(tmp_path)

    payload = json.loads(checkup.report(path, as_json=True))
    [email] = [
        f
        for f in payload["findings"]
        if f["slug"] == "whitespace-damage" and f["columns"] == ["email"]
    ]

    assert sum(local in email["evidence"] for local in local_parts) > 0, (
        "--json must keep the raw samples"
    )
