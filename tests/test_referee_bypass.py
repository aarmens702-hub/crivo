"""T15 (Stage 0, RE1): the two ways a kernel cell makes a fix verify today.

The checks that make a fix *verified* run inside the kernel, next to the cells
whose work they judge. The baselines are kernel globals (`_clean_backup`,
`_clean_rows`, `_clean_hashes`) and the verify cell imports `detect_one` there.
So a cell that runs in the kernel can make a fix read verified when it is not:

1. a fix cell that ends by re-taking the baseline snapshot moves the baseline
   onto whatever the fix left behind, rows dropped and all;
2. an earlier cell that rebinds `crivo.detect.detect_one` (or a fixer in
   `crivo.autoclean.FIXERS`) makes every later verify cell in the session
   pass: model fixes, deterministic fixes and skills.

It bites where nobody reads the cell: autonomous mode, headless `crivo clean`,
MCP `clean_file`. Each test drives the real subprocess kernel with only the
model stubbed, and makes one claim, the same in all four so it stays true
while RE11 (#167) to RE13 (#169) move the checks to the host: every record
that reads `fixed` is true of the data. Each is a strict xfail today and loses
its marker in the issue that closes its path.

Preconditions use pytest.fail, never assert: `raises=AssertionError` must not
count a run that never reached the claim as the expected failure.
"""

import json
import sys
from collections import Counter

import pandas as pd
import pytest

from crivo import checkup, detect, library, llm, skills
from crivo.events import GateDecision, GateRequest, Notice
from crivo.loop import CLEAN_MAX_ATTEMPTS, Session

SUBPROCESS_ARGV = [sys.executable, "-m", "crivo.kernel.supervisor"]

# A building-permit inspection export. The ids keep their leading zeros as
# text, and the score column carries four spellings of "no reading" among the
# real values. Hand-checked on the host: the only fixable finding is d04
# sentinel-missing on inspection_score, AUTO, 5 of 16 values.
VAR = "permits"
ID = "permit_id"
TARGET = "inspection_score"
PERMITS_CSV = (
    "permit_id,neighbourhood,inspection_score\n"
    "BP-2023-00417,Kitsilano,87\n"
    "BP-2023-00418,Strathcona,N/A\n"
    "BP-2023-00419,Grandview-Woodland,92\n"
    "BP-2023-00420,Downtown,unknown\n"
    "BP-2023-00421,Fairview,74\n"
    "BP-2023-00422,Mount Pleasant,N/A\n"
    "BP-2023-00423,Renfrew-Collingwood,81\n"
    "BP-2023-00424,Riley Park,95\n"
    "BP-2023-00425,Hastings-Sunrise,-\n"
    "BP-2023-00426,West End,68\n"
    "BP-2023-00427,Sunset,89\n"
    "BP-2023-00428,Marpole,77\n"
    "BP-2023-01003,Killarney,n/a\n"
    "BP-2023-01004,Dunbar-Southlands,90\n"
    "BP-2023-01005,Kerrisdale,83\n"
    "BP-2023-01006,Shaughnessy,79\n"
)

# The source of verify.baseline_cell("permits") on 2026-10-19 (BASELINE_TEMPLATE
# with COLUMN_DIGEST filled in), copied as text on purpose: RE11 to RE13 delete
# the kernel baselines, and this test has to outlive them.
REBASELINE = (
    "import hashlib as _hashlib\n"
    "import json as _json\n"
    "import pandas as pd\n"
    "_clean_backup = permits.copy()\n"
    "_clean_rows = len(permits)\n"
    "_clean_hashes = {}\n"
    "for _i in range(len(permits.columns)):\n"
    "    _clean_hashes.setdefault(str(permits.columns[_i]), []).append("
    "_hashlib.blake2b(pd.util.hash_pandas_object(permits.iloc[:, _i], "
    "index=True).sort_values().to_numpy().tobytes(), "
    "digest_size=16).hexdigest())\n"
    "_json.dumps(sorted(_clean_hashes))\n"
)

# keeps the first row only (a real score, so one row trips no signal), then
# moves the baseline onto what it left
KEEP_FIRST_ROW = (
    "<execute>\n"
    "def fix_sentinel_missing(df):\n"
    "    return df.head(1).copy()\n"
    "permits = fix_sentinel_missing(permits)\n" + REBASELINE + "</execute>"
)

# edits one unflagged cell of the target (87 -> 88) and leaves every sentinel
EDIT_ONE_REAL_SCORE = (
    "<execute>\n"
    "def fix_sentinel_missing(df):\n"
    "    out = df.copy()\n"
    "    out.loc[out.index[0], 'inspection_score'] = '88'\n"
    "    return out\n"
    "permits = fix_sentinel_missing(permits)\n"
    "</execute>"
)

# the earlier, approved cells that rebind the checker and the fixer
PATCH_DETECTOR = "import crivo.detect as _d; _d.detect_one = lambda *a, **k: None"
PATCH_FIXER = "import crivo.autoclean as _a; _a.FIXERS[4] = lambda df, cols: df"

SKILL = "fix-sentinel-missing"
NO_OP_SKILL = "def fix(df, columns):\n    return df\n"

# the honest repairs the pins below keep: every spelling of "no reading" in
# the export becomes a real gap, and nothing else moves
TOKENS = "['N/A', 'n/a', 'unknown', '-']"
HONEST_FIX = (
    "<execute>\n"
    "def fix_sentinel_missing(df):\n"
    "    out = df.copy()\n"
    f"    out['inspection_score'] = out['inspection_score'].replace({TOKENS}, None)\n"
    "    return out\n"
    "permits = fix_sentinel_missing(permits)\n"
    "</execute>"
)
HONEST_SKILL = (
    "def fix(df, columns):\n"
    "    out = df.copy()\n"
    "    for c in columns:\n"
    f"        out[c] = out[c].replace({TOKENS}, None)\n"
    "    return out\n"
)


def scripted(responses):
    queue = list(responses)

    def generate(messages, model=None):
        yield queue.pop(0) if queue else "<answer>done</answer>"

    return generate


def drive(turn, reject=()):
    """Answer every gate: reject the ones whose title starts with a prefix in
    `reject`, run the rest. Returns (events, gate titles in order)."""
    events, titles = [], []
    try:
        event = next(turn)
        while True:
            events.append(event)
            answer = None
            if isinstance(event, GateRequest):
                titles.append(event.title)
                if reject and event.title.startswith(reject):
                    answer = GateDecision("reject", note="not this one")
                else:
                    answer = GateDecision("run")
            event = turn.send(answer)
    except StopIteration:
        return events, titles


def open_session(tmp_path, **kwargs):
    """Built in each test body, never in a fixture: a fixture error reads as
    ERROR, which a strict xfail would not flag as the wrong failure."""
    source = tmp_path / f"{VAR}.csv"
    source.write_text(PERMITS_CSV, encoding="utf-8")
    session = Session(
        workspace=tmp_path / "ws",
        data_dir=tmp_path,
        transport_argv=SUBPROCESS_ARGV,
        skills_dir=tmp_path / "skills",
        **kwargs,
    )
    return session, source


def load(session, source):
    session.load(str(source))
    if not any(d["variable"] == VAR for d in session.datasets):
        pytest.fail(f"precondition: {source.name} did not load as {VAR!r}")


def run_in_kernel(session, code):
    result = None
    for ev in session.client.execute(code, timeout_s=60):
        result = ev
    if result is None or result.status != "ok":
        pytest.fail(f"precondition: the patch cell did not run: {result}")


def target_record(session):
    """The run's record for the d04 finding: the diagnosis found it and the
    run got as far as writing the report."""
    reports = sorted((session.session_dir / "clean_reports").glob("*.json"))
    if not reports:
        pytest.fail("precondition: the run wrote no clean report")
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    recs = [
        r
        for r in report["fixes"]
        if r["finding"]["disease"] == 4 and r["finding"]["columns"] == [TARGET]
    ]
    if len(recs) != 1:
        pytest.fail(f"precondition: no single d04 record on {TARGET} in the report")
    return report, recs[0]


def assert_fixed_records_are_true(report, source):
    """The one claim: every record that reads `fixed` is true of the data.

    Read on the host, with the host's own detector: the cleaned file keeps
    every row the input had, and the signal behind each fixed record finds
    nothing there. A run that keeps no fix claims nothing, so passes.

    Each check is reduced to a bool before it is asserted, so the assertion
    messages carry no data value or id: only row counts, the disease, the
    column name and the fix's origin."""
    fixed = [r for r in report["fixes"] if r["status"] == "fixed"]
    if not fixed:
        return
    parquet = (report["outputs"] or {}).get("parquet")
    assert parquet, "a record reads fixed, but the run wrote no cleaned file"
    original = checkup.load(source)
    cleaned = pd.read_parquet(parquet)
    every_row = ID in cleaned.columns and Counter(cleaned[ID].astype(str)) == Counter(
        original[ID].astype(str)
    )
    assert every_row, (
        "a record reads fixed, but the cleaned file does not hold the input's "
        f"rows ({len(cleaned)} where there were {len(original)})"
    )
    for rec in fixed:
        f = rec["finding"]
        still_fires = detect.detect_one(cleaned, f["disease"], f["columns"]) is not None
        assert not still_fires, (
            f"d{f['disease']:02d} {f['slug']} on {f['columns']} reads fixed "
            f"({rec['origin']}), but the host's detector still finds it in the "
            "cleaned file"
        )


def seed_proven_skill(root, fix_source):
    """A d04 skill on disk and in the ledger, promoted the way the ledger
    promotes: three clean uses on two sources. Returns its use count."""
    skills.save(
        skills.Skill(
            name=SKILL,
            description=(
                "Replace missing-data tokens with NaN. Use when a column holds "
                "'N/A' or 'unknown' as if they were real values."
            ),
            fix_source=fix_source,
            test_source="def test_fix_returns_a_frame():\n    assert fix\n",
            metadata={"disease": "4"},
        ),
        root,
    )
    ledger = library.Library.load(root)
    ledger.register(SKILL, disease=4)
    for source_sha in ("a" * 64, "b" * 64, "a" * 64):
        ledger.record(SKILL, success=True, dataset=source_sha)
    ledger.save()
    if ledger.entries[SKILL]["state"] != "proven":
        pytest.fail("precondition: the seeded skill is not proven")
    return ledger.entries[SKILL]["uses"]


def require_skill_ran(session, events, uses_before):
    """The seeded skill was applied to the finding and scored, not refused at
    load (#237) or skipped as unreadable."""
    refused = [
        e
        for e in events
        if isinstance(e, Notice)
        and e.kind == "skill"
        and SKILL in e.text
        and ("refused" in e.text or "unreadable" in e.text)
    ]
    if refused or session.library.entries[SKILL]["uses"] <= uses_before:
        pytest.fail("precondition: the seeded skill never ran on the finding")


def require_model_fix_gate(titles):
    """The scripted fix reached its gate, so the model path really ran. The
    deterministic fixer was turned down first, at a gate of its own."""
    if not any(t.startswith("autoclean") for t in titles):
        pytest.fail("precondition: no deterministic-fix gate to reject")
    if not any(t.startswith("fix ") for t in titles):
        pytest.fail("precondition: the model's fix never reached its gate")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="T15: checks run in the kernel; closed by RE11 (#167)",
)
def test_a_fix_that_reruns_the_baseline_is_not_kept(tmp_path, monkeypatch):
    """A fix cell that drops every row but one and then re-takes the baseline
    snapshot. The row invariant and the untouched-column digests then compare
    the frame against itself, and the detector has one row to read.

    M1 stays on (the default arm): careful mode gates the deterministic fixer,
    and the driver rejects that gate so the finding goes to the model. The
    fingerprint skip does not apply, because the cell drops rows."""
    monkeypatch.setattr(
        llm, "generate", scripted([KEEP_FIRST_ROW] * CLEAN_MAX_ATTEMPTS)
    )
    session, source = open_session(tmp_path, autonomy="careful")
    try:
        load(session, source)
        _, titles = drive(session.clean(VAR), reject=("autoclean",))
        require_model_fix_gate(titles)
        report, _ = target_record(session)
        assert_fixed_records_are_true(report, source)
    finally:
        session.close()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="T15: checks run in the kernel; closed by RE11 (#167)",
)
def test_a_patched_detector_does_not_verify_a_model_fix(tmp_path, monkeypatch):
    """An earlier approved cell rebinds crivo.detect.detect_one in the kernel.
    The model's fix then changes one real score and no sentinel, and the
    verify cell imports the rebound function and hears nothing.

    M1 stays on: the driver rejects the deterministic-fix gate, and the one
    edited cell moves the fingerprint, so the verify cell does run."""
    monkeypatch.setattr(
        llm, "generate", scripted([EDIT_ONE_REAL_SCORE] * CLEAN_MAX_ATTEMPTS)
    )
    session, source = open_session(tmp_path, autonomy="careful")
    try:
        load(session, source)
        run_in_kernel(session, PATCH_DETECTOR)
        _, titles = drive(session.clean(VAR), reject=("autoclean",))
        require_model_fix_gate(titles)
        report, _ = target_record(session)
        assert_fixed_records_are_true(report, source)
    finally:
        session.close()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="T15: checks run in the kernel; closed by RE12 (#168)",
)
def test_a_patched_fixer_does_not_verify_a_deterministic_fix(tmp_path, monkeypatch):
    """The same detector patch, plus the d04 fixer swapped for one that
    returns its input. At autonomous the standing policy batches the AUTO
    finding, so the no-op fix applies and verifies with no gate shown."""
    monkeypatch.setattr(llm, "generate", scripted([]))
    session, source = open_session(tmp_path, autonomy="autonomous")
    try:
        load(session, source)
        run_in_kernel(session, PATCH_DETECTOR)
        run_in_kernel(session, PATCH_FIXER)
        drive(session.clean(VAR))
        report, _ = target_record(session)
        assert_fixed_records_are_true(report, source)
    finally:
        session.close()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="T15: checks run in the kernel; closed by RE13 (#169)",
)
def test_a_patched_detector_does_not_verify_a_skill(tmp_path, monkeypatch):
    """A proven d04 skill whose fix returns its input, with the detector
    patched. A proven skill on an AUTO finding runs first and unattended, so
    the no-op lands with no gate shown and no model call."""
    uses_before = seed_proven_skill(tmp_path / "skills", NO_OP_SKILL)

    monkeypatch.setattr(llm, "generate", scripted([]))
    session, source = open_session(tmp_path)
    try:
        load(session, source)
        run_in_kernel(session, PATCH_DETECTOR)
        events, _ = drive(session.clean(VAR))
        require_skill_ran(session, events, uses_before)
        report, _ = target_record(session)
        assert_fixed_records_are_true(report, source)
    finally:
        session.close()


@pytest.mark.parametrize(
    ("path", "autonomy", "origin"),
    [
        ("model", "careful", "model"),
        ("deterministic", "autonomous", "autoclean:d04"),
        ("skill", "autonomous", f"skill:{SKILL}"),
    ],
)
def test_an_honest_fix_on_the_same_path_is_still_kept(
    tmp_path, monkeypatch, path, autonomy, origin
):
    """The legitimate repair beside the four refusals above. With nothing
    patched, an honest d04 fix on the same frame and the same path is kept,
    and is true of the data. A run that keeps nothing passes the shared
    claim, so without this pin a referee that refused every fix would turn
    all four xfails green."""
    uses_before = None
    if path == "skill":
        uses_before = seed_proven_skill(tmp_path / "skills", HONEST_SKILL)
    replies = [HONEST_FIX] if path == "model" else []
    monkeypatch.setattr(llm, "generate", scripted(replies))
    session, source = open_session(tmp_path, autonomy=autonomy)
    try:
        load(session, source)
        reject = ("autoclean",) if path == "model" else ()
        events, titles = drive(session.clean(VAR), reject=reject)
        if path == "model":
            require_model_fix_gate(titles)
        if path == "skill":
            require_skill_ran(session, events, uses_before)
        report, rec = target_record(session)
        assert (rec["status"], rec["origin"]) == ("fixed", origin)
        assert_fixed_records_are_true(report, source)
    finally:
        session.close()
