"""Tests for the skill library and its governance (P2 R10-R14).

The rules under test are the ones that decide whether a skill runs unattended,
so they are asserted at their boundaries: three successes promote, three
successes on one dataset do not, two consecutive failures retire.
"""

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from crivo import library, skills


def test_register_starts_a_skill_on_probation() -> None:
    lib = library.Library(root="skills")
    entry = lib.register("fix-sentinel-missing", disease=4)

    assert entry["state"] == "probation"
    assert entry["disease"] == 4
    assert entry["successes"] == entry["failures"] == entry["uses"] == 0
    assert entry["datasets"] == []
    assert lib.entries["fix-sentinel-missing"] is entry


def test_record_counts_outcomes_and_the_sources_they_came_from() -> None:
    lib = library.Library(root="skills")
    lib.register("fix-whitespace", disease=6)

    lib.record("fix-whitespace", success=True, dataset="sha-beers", events=[7, 8])
    entry = lib.record("fix-whitespace", success=False, dataset="sha-beers", events=[9])

    assert entry["uses"] == 2
    assert entry["successes"] == 1
    assert entry["failures"] == 1
    assert entry["datasets"] == ["sha-beers"]  # the same source counts once
    assert entry["recent"] == ["success", "failure"]
    assert [e["events"] for e in entry["events"]] == [[7, 8], [9]]
    assert entry["last_used"]


def test_promotion_needs_successes_on_more_than_one_source() -> None:
    """The rule that guards the Q1 bet: a skill generalised from a single case
    proves nothing by succeeding on that same case again."""
    lib = library.Library(root="skills")
    lib.register("fix-sentinel-missing", disease=4)
    for _ in range(5):
        entry = lib.record("fix-sentinel-missing", success=True, dataset="sha-beers")
    assert entry["state"] == "probation", "five wins on one file is still one file"

    entry = lib.record("fix-sentinel-missing", success=True, dataset="sha-hospital")
    assert entry["state"] == "proven"


def test_a_recent_failure_holds_a_skill_back_until_it_ages_out() -> None:
    lib = library.Library(root="skills")
    lib.register("fix-units", disease=1)
    lib.record("fix-units", success=True, dataset="a")
    lib.record("fix-units", success=False, dataset="a")
    entry = lib.record("fix-units", success=True, dataset="b")
    lib.record("fix-units", success=True, dataset="c")
    assert entry["state"] == "probation", "a failure in the window blocks promotion"

    for _ in range(4):  # push the failure out of the last-5 window
        entry = lib.record("fix-units", success=True, dataset="d")
    assert entry["state"] == "proven"


def test_two_consecutive_failures_retire_a_skill() -> None:
    lib = library.Library(root="skills")
    lib.register("fix-dates", disease=2)
    lib.record("fix-dates", success=False, dataset="a")
    entry = lib.record("fix-dates", success=False, dataset="a")

    assert entry["state"] == "retired"
    assert "twice in a row" in entry["retired_reason"]
    assert entry["events"][-1]["outcome"] == "retired"


def test_candidates_match_on_disease_and_rank_by_record() -> None:
    lib = library.Library(root="skills")
    for name in ("fix-weak", "fix-strong", "fix-other"):
        lib.register(name, disease=6 if name != "fix-other" else 1)
    lib.record("fix-weak", success=True, dataset="a")
    for source in ("a", "b", "c"):
        lib.record("fix-strong", success=True, dataset=source)

    names = [e["name"] for e in lib.candidates(disease=6)]
    assert names == ["fix-strong", "fix-weak"], "a better record goes first"
    assert lib.candidates(disease=99) == []

    lib.retire("fix-strong", reason="superseded")
    assert [e["name"] for e in lib.candidates(disease=6)] == ["fix-weak"]


def test_only_a_proven_skill_on_an_auto_finding_runs_unattended() -> None:
    """R12. Both halves are required: the disease must be safe to fix without
    judgement, and the skill must have earned it."""
    lib = library.Library(root="skills")
    probation = lib.register("fix-new", disease=4)
    proven = lib.register("fix-old", disease=4)
    proven["state"] = "proven"

    assert library.unattended(proven, "AUTO") is True
    assert library.unattended(proven, "GATE") is False
    assert library.unattended(proven, "HUMAN") is False
    assert library.unattended(probation, "AUTO") is False


def test_ledger_round_trips_through_disk(tmp_path) -> None:
    lib = library.Library(root=tmp_path)
    lib.register("fix-sentinel-missing", disease=4)
    lib.record("fix-sentinel-missing", success=True, dataset="sha-beers", events=[3])
    lib.save()

    assert (tmp_path / library.LEDGER_NAME).exists()
    reopened = library.Library.load(tmp_path)
    assert reopened.entries == lib.entries
    assert library.Library.load(tmp_path / "nowhere").entries == {}


def test_retiring_moves_the_folder_aside_rather_than_deleting_it(tmp_path) -> None:
    """The graveyard is evidence for the day-1-vs-day-N story, not garbage."""
    folder = tmp_path / "fix-dates" / "scripts"
    folder.mkdir(parents=True)
    (folder / "fix.py").write_text("def fix(df, columns):\n    return df\n")

    lib = library.Library(root=tmp_path)
    lib.register("fix-dates", disease=2)
    lib.retire("fix-dates", reason="superseded")

    assert not (tmp_path / "fix-dates").exists()
    moved = tmp_path / library.RETIRED_DIR / "fix-dates"
    assert (moved / "scripts" / "fix.py").exists()
    assert lib.entries["fix-dates"]["state"] == "retired"


def test_the_active_cap_evicts_the_worst_performer(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(library, "ACTIVE_CAP", 3)
    lib = library.Library(root=tmp_path)
    for name in ("fix-a", "fix-b", "fix-c"):
        lib.register(name, disease=4)
    lib.record("fix-a", success=True, dataset="x")
    lib.record("fix-b", success=True, dataset="x")
    lib.record("fix-b", success=True, dataset="y")
    # fix-c has done nothing at all, so it is the one to lose

    lib.register("fix-d", disease=4)
    states = {name: entry["state"] for name, entry in lib.entries.items()}
    assert states["fix-c"] == "retired"
    assert "cap" in lib.entries["fix-c"]["retired_reason"]
    assert [s for s in states.values() if s != "retired"] == ["probation"] * 3


# --- #237: an admitted skill's scripts are pinned at admission ---------------

NAME = "fix-sentinel-missing"
FIX_SOURCE = (
    "def fix(df, columns):\n"
    "    out = df.copy()\n"
    "    for c in columns:\n"
    "        if c in out.columns:\n"
    "            out[c] = out[c].replace(['-999', 'N/A', 'n/a'], None)\n"
    "    return out\n"
)
TEST_SOURCE = (
    "import pandas as pd\n"
    "\n"
    "\n"
    "def test_fix_clears_the_sentinels_and_keeps_leading_zeros():\n"
    "    df = pd.DataFrame({'zip': ['02134', '-999', 'N/A', '00501']})\n"
    "    out = fix(df, ['zip'])\n"
    "    assert out['zip'].isna().sum() == 2\n"
    "    assert out['zip'].dropna().tolist() == ['02134', '00501']\n"
)


def _skill(name=NAME) -> skills.Skill:
    return skills.Skill(
        name=name,
        description="Replace sentinel tokens with NaN. Use when a column holds -999 or 'N/A'.",
        fix_source=FIX_SOURCE,
        test_source=TEST_SOURCE,
        metadata={"disease": "4", "slug": "sentinel-missing", "version": "1"},
    )


def _admitted(root, name=NAME):
    """A skill as admission leaves it: the folder written, then the row
    registered (the order _propose_skill uses)."""
    skills.save(_skill(name), root)
    lib = library.Library(root=root)
    lib.register(name, disease=4)
    return lib, Path(root) / name


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _crlf(folder) -> None:
    """What a Windows checkout with core.autocrlf does to the scripts."""
    for script in ("fix.py", "test_fix.py"):
        path = Path(folder) / "scripts" / script
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))


def _pre_pin_ledger(root, names) -> None:
    """A ledger.json as register() wrote it before #237: no sha256 anywhere."""
    rows = {
        name: {
            "name": name,
            "disease": 4,
            "state": "proven",
            "uses": 4,
            "successes": 4,
            "failures": 0,
            "datasets": ["sha-beers", "sha-hospital"],
            "recent": ["success"] * 4,
            "created": "2026-09-30T10:12:04+01:00",
            "last_used": "2026-10-11T16:40:19+01:00",
            "events": [],
        }
        for name in names
    }
    (Path(root) / library.LEDGER_NAME).write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )


def test_register_pins_both_scripts_of_the_admitted_skill(tmp_path) -> None:
    """Regression for #237. Admission pins sha256 of scripts/fix.py and
    scripts/test_fix.py, keyed relative to the skill folder, so the code a
    person approved is the code a later load can be held to."""
    lib, _ = _admitted(tmp_path)

    assert lib.entries[NAME].get("sha256") == {
        "scripts/fix.py": _sha(FIX_SOURCE),
        "scripts/test_fix.py": _sha(TEST_SOURCE),
    }


def test_an_unchanged_admitted_skill_passes_its_check(tmp_path) -> None:
    """Regression for #237. The legitimate case beside the refusal: files that
    still match their pin load with no refusal and no note."""
    lib, folder = _admitted(tmp_path)
    assert lib.entries[NAME].get("sha256"), "admission pinned nothing"

    ok, message = lib.check(NAME, skills.load(folder))

    assert ok is True
    assert not message, "an unchanged pinned skill needs no notice"


@pytest.mark.parametrize(
    "script, edited",
    [
        # one token gone: -999 now survives the fix
        ("fix.py", FIX_SOURCE.replace("'-999', ", "")),
        # the test still runs, and no longer tests anything
        ("test_fix.py", TEST_SOURCE.replace("== 2", ">= 0")),
    ],
    ids=["fix.py", "test_fix.py"],
)
def test_an_admitted_skill_whose_script_changed_is_refused(
    tmp_path, script, edited
) -> None:
    """Regression for #237. A script edited after admission is refused at
    load. The message names the skill and the file that changed, and says how
    to re-admit it; the ledger row is left as it was, unscored."""
    lib, folder = _admitted(tmp_path)
    assert lib.entries[NAME].get("sha256"), "admission pinned nothing"
    before = copy.deepcopy(lib.entries[NAME])
    (folder / "scripts" / script).write_text(edited, encoding="utf-8")

    ok, message = lib.check(NAME, skills.load(folder))

    assert ok is False
    assert NAME in message
    assert script in message, "the message must name the file that changed"
    other = r"test_fix\.py" if script == "fix.py" else r"(?<!test_)fix\.py"
    assert not re.search(other, message), "the unchanged file is not the one named"
    assert "git checkout" in message, "say how to restore the admitted files"
    assert re.search(r"delete|remove", message, re.IGNORECASE), (
        "say the other way back: drop the folder and let a fix propose it again"
    )
    assert lib.entries[NAME] == before, "a refused skill is not scored"


def _drop_test_pin(entry: dict) -> None:
    del entry["sha256"]["scripts/test_fix.py"]


def _drop_fix_pin(entry: dict) -> None:
    del entry["sha256"]["scripts/fix.py"]


def _empty_pin(entry: dict) -> None:
    entry["sha256"] = {}


@pytest.mark.parametrize(
    "tamper",
    [_drop_test_pin, _drop_fix_pin, _empty_pin],
    ids=["no test_fix.py pin", "no fix.py pin", "empty pin"],
)
def test_an_incomplete_pin_on_unchanged_scripts_is_refused(tmp_path, tamper) -> None:
    """Regression for #237. A pin that lost a key, or was hand-edited down to
    {}, no longer vouches for both scripts, even when the files on disk are
    the ones admitted. Only a row with no pin at all is a pre-pin row; an
    empty pin is refused, not waved through as unpinned."""
    lib, folder = _admitted(tmp_path)
    assert lib.entries[NAME].get("sha256"), "admission pinned nothing"
    tamper(lib.entries[NAME])

    ok, message = lib.check(NAME, skills.load(folder))

    assert ok is False, message
    assert NAME in message


@pytest.mark.parametrize("when", ["after admission", "at admission"])
def test_a_crlf_checkout_of_unchanged_scripts_still_passes(tmp_path, when) -> None:
    """Regression for #237. The pin is over the text skills.load returns, read
    with universal newlines, so a CRLF checkout of the same scripts is the
    same code, whether the line endings changed before or after admission."""
    if when == "at admission":
        skills.save(_skill(), tmp_path)
        _crlf(tmp_path / NAME)
        lib = library.Library(root=tmp_path)
        lib.register(NAME, disease=4)
    else:
        lib, _ = _admitted(tmp_path)
        _crlf(tmp_path / NAME)
    assert b"\r\n" in (tmp_path / NAME / "scripts" / "fix.py").read_bytes()
    assert lib.entries[NAME].get("sha256"), "admission pinned nothing"

    ok, message = lib.check(NAME, skills.load(tmp_path / NAME))

    assert ok is True, message
    assert not message


def test_a_row_from_before_the_pin_loads_with_one_note_per_session(tmp_path) -> None:
    """Regression for #237. No migration: pinning a pre-pin row at its first
    load would vouch for whatever is on disk. So the row keeps loading, unpinned,
    and each session says so once per skill, not once per load."""
    for name in ("fix-sentinel-missing", "fix-sentinel-zip"):
        skills.save(_skill(name), tmp_path)
    _pre_pin_ledger(tmp_path, ["fix-sentinel-missing", "fix-sentinel-zip"])
    a = skills.load(tmp_path / "fix-sentinel-missing")
    b = skills.load(tmp_path / "fix-sentinel-zip")

    lib = library.Library.load(tmp_path)
    ok, note = lib.check("fix-sentinel-missing", a)
    ok_again, again = lib.check("fix-sentinel-missing", a)
    ok_other, other = lib.check("fix-sentinel-zip", b)

    assert ok is ok_again is ok_other is True, "an unpinned row still loads"
    assert note and "fix-sentinel-missing" in note and "pin" in note.lower()
    assert not again, "the note is once per session, not once per load"
    assert other and "fix-sentinel-zip" in other, "each skill gets its own note"
    assert not lib.entries["fix-sentinel-missing"].get("sha256"), (
        "a load must not pin whatever happens to be on disk"
    )

    next_session = library.Library.load(tmp_path)
    assert next_session.check("fix-sentinel-missing", a)[1], (
        "a new session hears the note again"
    )


def test_the_pin_survives_a_ledger_round_trip_and_retirement(tmp_path) -> None:
    """Regression for #237. The pin lives in ledger.json, and its keys are
    relative to the skill folder, so they still resolve once retire() has
    moved the folder to retired/."""
    lib, _ = _admitted(tmp_path)
    pin = lib.entries[NAME].get("sha256")
    assert pin, "admission pinned nothing"
    lib.save()

    reopened = library.Library.load(tmp_path)
    assert reopened.entries[NAME]["sha256"] == pin

    reopened.retire(NAME, reason="superseded")
    grave = tmp_path / library.RETIRED_DIR / NAME
    assert reopened.entries[NAME]["sha256"] == pin
    assert all((grave / key).is_file() for key in pin), (
        "pin keys must be relative to the skill folder"
    )
    assert {key: _sha((grave / key).read_text(encoding="utf-8")) for key in pin} == pin


def test_register_with_no_skill_folder_pins_nothing_and_vouches_for_nothing(
    tmp_path,
) -> None:
    """Regression for #237. A row registered before its folder exists has
    nothing to pin, and register() must not raise. When a folder turns up
    later, the row is treated as unpinned, not pinned to what turned up."""
    lib = library.Library(root=tmp_path)
    entry = lib.register(NAME, disease=4)
    assert not entry.get("sha256")

    skills.save(_skill(), tmp_path)
    ok, note = lib.check(NAME, skills.load(tmp_path / NAME))

    assert ok is True
    assert note and "pin" in note.lower(), "an unpinned row says it is unpinned"
    assert not lib.entries[NAME].get("sha256"), "a load must not pin the folder"
