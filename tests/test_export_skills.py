"""Tests for scripts/export_skills.py — the skill export/scrub/bundle path (P4).

No network, no Docker. Fixture skill folders are built with
crivo.skills.save() and a hand-written ledger dict, matching a real
skills/ directory: skills/<name>/{SKILL.md,scripts/} plus skills/ledger.json,
or skills/retired/<name>/ for the ones the library has already retired.
"""

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

from crivo import library, skills

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from export_skills import run_export


def make_skill(name="fix-sentinel-missing", **kw) -> skills.Skill:
    base = {
        "name": name,
        "description": "Replace missing-data tokens with NaN. Use when a column "
        "holds 'N/A' or 'unknown' as if they were values.",
        "fix_source": "def fix(df, columns):\n    return df.copy()\n",
        "test_source": "def test_fix():\n    assert True\n",
        "metadata": {"disease": "4"},
    }
    base.update(kw)
    return skills.Skill(**base)


def ledger_entry(*, state, disease=4, successes=0, failures=0) -> dict:
    return {
        "state": state,
        "disease": disease,
        "successes": successes,
        "failures": failures,
        "uses": successes + failures,
        "datasets": [],
        "recent": [],
        "created": "",
        "last_used": "",
        "events": [],
    }


def write_ledger(root: Path, entries: dict) -> None:
    library.Library(root=root, entries=entries).save()


def test_default_selection_exports_only_proven(tmp_path) -> None:
    root = tmp_path / "skills"
    skills.save(make_skill("fix-proven"), root)
    skills.save(make_skill("fix-probation"), root)
    write_ledger(
        root,
        {
            "fix-proven": ledger_entry(state="proven"),
            "fix-probation": ledger_entry(state="probation"),
        },
    )

    report = run_export(root, tmp_path / "out")

    assert report.exported == ["fix-proven"]
    assert (tmp_path / "out" / "fix-proven" / "SKILL.md").exists()
    assert not (tmp_path / "out" / "fix-probation").exists()


def test_selection_flags_widen_by_state(tmp_path) -> None:
    """--include-probation adds known-probation skills; unknown-state skills
    (no ledger entry at all) need the broader --all, not just --include-probation."""
    root = tmp_path / "skills"
    skills.save(make_skill("fix-proven"), root)
    skills.save(make_skill("fix-probation"), root)
    skills.save(make_skill("fix-mystery"), root)
    write_ledger(
        root,
        {
            "fix-proven": ledger_entry(state="proven"),
            "fix-probation": ledger_entry(state="probation"),
            # fix-mystery is deliberately absent from the ledger.
        },
    )

    default = run_export(root, tmp_path / "out-default")
    assert default.exported == ["fix-proven"]

    probation = run_export(root, tmp_path / "out-probation", include_probation=True)
    assert sorted(probation.exported) == ["fix-probation", "fix-proven"]

    everything = run_export(root, tmp_path / "out-all", include_all=True)
    assert sorted(everything.exported) == ["fix-mystery", "fix-probation", "fix-proven"]


def test_retired_needs_its_own_flag_even_under_all(tmp_path) -> None:
    root = tmp_path / "skills"
    skills.save(make_skill("fix-dead"), root / library.RETIRED_DIR)
    write_ledger(root, {"fix-dead": ledger_entry(state="retired")})

    broad = run_export(root, tmp_path / "out-all", include_all=True)
    assert broad.exported == []

    explicit = run_export(root, tmp_path / "out-retired", include_retired=True)
    assert explicit.exported == ["fix-dead"]


def test_born_from_is_generalized_to_a_basename(tmp_path) -> None:
    """metadata.born_from names a real path on the author's machine (P4 why).
    from_proposal() also echoes that same path into the body as quoted
    provenance, so the body needs the same generalisation, not just metadata."""
    root = tmp_path / "skills"
    born_from = "/Users/aarmensidhu/Desktop/crivo/data/raha/beers/dirty.csv"
    skill = make_skill(
        "fix-ibu-units",
        metadata={"disease": "4", "born_from": born_from},
        body=f"## Where it came from\n\nDisease 4 on `{born_from}`: 340 rows.\n",
    )
    skills.save(skill, root)
    write_ledger(root, {"fix-ibu-units": ledger_entry(state="proven")})

    report = run_export(root, tmp_path / "out")

    assert report.exported == ["fix-ibu-units"]
    result = next(r for r in report.results if r.name == "fix-ibu-units")
    assert any("born_from" in note for note in result.scrubbed)

    exported = skills.load(tmp_path / "out" / "fix-ibu-units")
    assert exported.metadata["born_from"] == "dirty.csv"
    assert born_from not in exported.body
    assert "dirty.csv" in exported.body


def test_strict_drops_born_from_entirely(tmp_path) -> None:
    root = tmp_path / "skills"
    skill = make_skill(
        "fix-ibu-units",
        metadata={"disease": "4", "born_from": "/Users/aarmensidhu/data/dirty.csv"},
        body="## Notes\n\nGeneralised at proposal time.\n",
    )
    skills.save(skill, root)
    write_ledger(root, {"fix-ibu-units": ledger_entry(state="proven")})

    report = run_export(root, tmp_path / "out", strict=True)

    assert report.exported == ["fix-ibu-units"]
    result = next(r for r in report.results if r.name == "fix-ibu-units")
    assert any("dropped" in note for note in result.scrubbed)

    exported = skills.load(tmp_path / "out" / "fix-ibu-units")
    assert "born_from" not in exported.metadata


def test_seventh_frontmatter_field_is_refused(tmp_path) -> None:
    """claude.ai and the Skills API hard-fail on a seventh top-level field, so a
    skill carrying one must be refused with a reason, not silently skipped."""
    root = tmp_path / "skills"
    path = skills.save(make_skill("fix-bad"), root)
    md = (
        (path / "SKILL.md")
        .read_text()
        .replace("license:", "author: someone\nlicense:", 1)
    )
    (path / "SKILL.md").write_text(md)
    write_ledger(root, {"fix-bad": ledger_entry(state="proven")})

    report = run_export(root, tmp_path / "out")

    assert report.exported == []
    result = next(r for r in report.results if r.name == "fix-bad")
    assert result.selected is True
    assert result.ok is False
    assert any("author" in p for p in result.problems)
    assert not (tmp_path / "out" / "fix-bad").exists()


def test_absolute_path_outside_born_from_is_refused(tmp_path) -> None:
    """The body can quote real values from the case that spawned the skill (P4
    why #3) — e.g. from_proposal()'s evidence text. born_from generalisation
    alone doesn't catch this, so any leftover absolute path anywhere in the
    rendered SKILL.md is a hard refusal, not a best-effort scrub."""
    root = tmp_path / "skills"
    skill = make_skill(
        "fix-leaky",
        body="## Evidence\n\nSee /Users/aarmensidhu/Desktop/crivo/"
        "workspace/s07/skill_cases/fix-leaky.parquet for the frozen slice.\n",
    )
    skills.save(skill, root)
    write_ledger(root, {"fix-leaky": ledger_entry(state="proven")})

    report = run_export(root, tmp_path / "out")

    assert report.exported == []
    result = next(r for r in report.results if r.name == "fix-leaky")
    assert result.ok is False
    assert any("absolute path" in p for p in result.problems)
    assert not (tmp_path / "out" / "fix-leaky").exists()


def test_folder_conformance_refuses_extra_and_oversized_files(
    tmp_path, monkeypatch
) -> None:
    """The export gate is stricter than skills.validate(): no stray files in
    the folder, and nothing over the size cap — checked on the source folder,
    not just the rendered SKILL.md."""
    import export_skills

    monkeypatch.setattr(export_skills, "MAX_FILE_BYTES", 10)

    root = tmp_path / "skills"
    cluttered = skills.save(make_skill("fix-cluttered"), root)
    (cluttered / "notes.txt").write_text("do not ship this\n")
    skills.save(make_skill("fix-huge"), root)  # fix.py is well over 10 bytes
    write_ledger(
        root,
        {
            "fix-cluttered": ledger_entry(state="proven"),
            "fix-huge": ledger_entry(state="proven"),
        },
    )

    report = run_export(root, tmp_path / "out")

    assert report.exported == []
    problems = {r.name: r.problems for r in report.results}
    assert any("notes.txt" in p for p in problems["fix-cluttered"])
    assert any("bytes" in p for p in problems["fix-huge"])


def test_manifest_and_readme_are_written_for_exported_skills(tmp_path) -> None:
    import hashlib
    import json

    root = tmp_path / "skills"
    skills.save(make_skill("fix-proven", metadata={"disease": "6"}), root)
    write_ledger(
        root,
        {
            "fix-proven": ledger_entry(
                state="proven", disease=6, successes=4, failures=1
            )
        },
    )

    run_export(root, tmp_path / "out")

    manifest = json.loads((tmp_path / "out" / "MANIFEST.json").read_text())
    assert len(manifest["skills"]) == 1
    entry = manifest["skills"][0]
    assert entry["name"] == "fix-proven"
    assert entry["disease"] == 6
    assert entry["state"] == "proven"
    assert entry["successes"] == 4
    assert entry["failures"] == 1

    expected_sha = hashlib.sha256(
        (tmp_path / "out" / "fix-proven" / "SKILL.md").read_bytes()
    ).hexdigest()
    assert entry["sha256"] == expected_sha

    readme = (tmp_path / "out" / "README.md").read_text()
    assert "test-gated" in readme
    assert "fix-proven" in readme


def test_dry_run_writes_nothing(tmp_path) -> None:
    root = tmp_path / "skills"
    skills.save(make_skill("fix-proven"), root)
    write_ledger(root, {"fix-proven": ledger_entry(state="proven")})
    out = tmp_path / "out"

    report = run_export(root, out, dry_run=True)

    assert report.exported == ["fix-proven"]
    assert report.dry_run is True
    assert not out.exists()


def test_zip_flag_writes_an_archive_of_the_bundle(tmp_path) -> None:
    import zipfile

    root = tmp_path / "skills"
    skills.save(make_skill("fix-proven"), root)
    write_ledger(root, {"fix-proven": ledger_entry(state="proven")})
    out = tmp_path / "out"

    report = run_export(root, out, make_zip=True)

    assert report.zip_path == out.with_suffix(".zip")
    assert report.zip_path.exists()
    with zipfile.ZipFile(report.zip_path) as zf:
        names = zf.namelist()
    assert "MANIFEST.json" in names
    assert "fix-proven/SKILL.md" in names


def test_main_runs_end_to_end_via_the_cli(tmp_path, monkeypatch, capsys) -> None:
    import export_skills

    root = tmp_path / "skills"
    skills.save(make_skill("fix-proven"), root)
    write_ledger(root, {"fix-proven": ledger_entry(state="proven")})
    out = tmp_path / "out"

    monkeypatch.setattr(
        "sys.argv",
        ["export_skills.py", "--skills-root", str(root), "--out", str(out)],
    )
    export_skills.main()

    captured = capsys.readouterr()
    assert "fix-proven" in captured.out
    assert (out / "fix-proven" / "SKILL.md").exists()
    assert (out / "MANIFEST.json").exists()


def test_manifest_disease_is_always_an_int(tmp_path) -> None:
    """The ledger stores it as int, SKILL.md metadata as str per spec. A
    manifest that reports whichever it happened to read is one a consumer
    cannot parse without guessing."""
    root = tmp_path / "skills"
    skills.save(make_skill("fix-a"), root)
    skills.save(make_skill("fix-b"), root)
    (root / "ledger.json").write_text(
        json.dumps({"fix-a": {"disease": 4, "state": "proven"}})
    )  # fix-b has no ledger row, so its disease comes from metadata as a string

    run_export(root, tmp_path / "dist", include_all=True)
    manifest = json.loads((tmp_path / "dist" / "MANIFEST.json").read_text())
    diseases = [s["disease"] for s in manifest["skills"]]
    assert diseases and all(isinstance(d, int) for d in diseases), diseases


def test_an_exported_skill_runs_in_a_consumer_that_never_heard_of_us(tmp_path):
    """The README claims these are portable to any SKILL.md-speaking tool. A
    consumer does not run our test harness or import our package — it imports
    fix.py and calls it. Until this ran, 'portable' was a sentence, not a
    checked claim."""
    root = tmp_path / "skills"
    skills.save(
        make_skill(
            fix_source=(
                "import pandas as pd\n\n\n"
                "def fix(df, columns):\n"
                "    out = df.copy()\n"
                "    for c in columns:\n"
                "        if c in out.columns:\n"
                "            out[c] = pd.to_numeric(out[c], errors='coerce')\n"
                "    return out\n"
            )
        ),
        root,
    )
    (root / library.LEDGER_NAME).write_text(
        json.dumps({"fix-sentinel-missing": {"disease": 4, "state": "proven"}})
    )
    out = tmp_path / "bundle"
    run_export(root, out)

    spec = importlib.util.spec_from_file_location(
        "exported_fix", out / "fix-sentinel-missing" / "scripts" / "fix.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.fix(pd.DataFrame({"ibu": ["N/A", "60", "unknown"]}), ["ibu"])
    assert result["ibu"].isna().sum() == 2
    assert result["ibu"].tolist()[1] == 60.0


# --- #238: export holds an admitted skill to the scripts it was admitted with -

SENTINEL_FIX = (
    "def fix(df, columns):\n"
    "    out = df.copy()\n"
    "    for c in columns:\n"
    "        if c in out.columns:\n"
    "            out[c] = out[c].replace(['-999', 'N/A', 'n/a'], None)\n"
    "    return out\n"
)
SENTINEL_TEST = (
    "import pandas as pd\n"
    "\n"
    "\n"
    "def test_fix_clears_the_sentinels_and_keeps_leading_zeros():\n"
    "    df = pd.DataFrame({'zip': ['02134', '-999', 'N/A', '00501']})\n"
    "    out = fix(df, ['zip'])\n"
    "    assert out['zip'].isna().sum() == 2\n"
    "    assert out['zip'].dropna().tolist() == ['02134', '00501']\n"
)
# Edits made after admission, one per pinned script.
EDITS = [
    # one token gone: -999 now survives the fix
    ("fix.py", SENTINEL_FIX.replace("'-999', ", "")),
    # the test still runs, and no longer tests anything
    ("test_fix.py", SENTINEL_TEST.replace("== 2", ">= 0")),
]


def sentinel_skill(name) -> skills.Skill:
    return make_skill(name, fix_source=SENTINEL_FIX, test_source=SENTINEL_TEST)


def admit(root: Path, name: str, *, state: str = "proven") -> Path:
    """A skill as admission leaves it, then moved on to `state`: the folder
    written, the row registered (which pins both scripts), the ledger saved."""
    skills.save(sentinel_skill(name), root)
    lib = library.Library.load(root)
    lib.register(name, 4)
    lib.entries[name]["state"] = state
    lib.save()
    return root / name


def _result(report, name):
    return next(r for r in report.results if r.name == name)


def _notes(result) -> str:
    """Every note export carried for one skill. `notes` is the field #238
    adds; a result from before it has none to read."""
    return " ".join(getattr(result, "notes", []))


def _names_script(text: str, script: str) -> bool:
    """`script` named as a file in `text`: fix.py is not test_fix.py."""
    return re.search(rf"(?<!\w){re.escape(script)}", text) is not None


def _printed_block(stdout: str, name: str) -> list[str]:
    """A skill's own line in the printed report, then the lines indented
    under it."""
    block, inside = [], False
    for line in stdout.splitlines():
        if not line[:1].isspace():  # a skill's own line, or the blank before the tail
            inside = re.search(rf"\s{re.escape(name)}(\s|$)", line) is not None
        if inside:
            block.append(line)
    return block


@pytest.mark.parametrize("state", ["proven", "probation"])
@pytest.mark.parametrize("script, edited", EDITS, ids=[s for s, _ in EDITS])
def test_an_admitted_skill_whose_script_changed_is_not_exported(
    tmp_path, script, edited, state
) -> None:
    """Regression for #238. A pinned script edited after admission is the code
    nobody admitted, so export leaves the skill out of the bundle and the
    MANIFEST and says which skill and which file. An unchanged admitted skill
    in the same run still ships."""
    root = tmp_path / "skills"
    folder = admit(root, "fix-zip-sentinels", state=state)
    admit(root, "fix-sentinel-missing")
    (folder / "scripts" / script).write_text(edited, encoding="utf-8")
    out = tmp_path / "out"

    report = run_export(root, out, include_probation=True)

    assert "fix-zip-sentinels" not in report.exported, (
        "an admitted skill whose scripts changed exported as admitted"
    )
    assert report.refused == ["fix-zip-sentinels"]
    assert report.exported == ["fix-sentinel-missing"], "the unchanged one ships"
    assert not (out / "fix-zip-sentinels").exists()
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert [s["name"] for s in manifest["skills"]] == ["fix-sentinel-missing"]
    problems = _result(report, "fix-zip-sentinels").problems
    assert any(
        "fix-zip-sentinels" in p and _names_script(p, script) for p in problems
    ), "the refusal names the skill and the file that changed"


def test_an_unchanged_admitted_skill_exports_with_its_pinned_script_hashes(
    tmp_path,
) -> None:
    """Regression for #238. The legitimate case beside the refusal: scripts
    that still match their pin export with no refusal and no note, and the
    MANIFEST carries their sha256 beside SKILL.md's, equal to the ledger pin
    and to the bytes written into the bundle, and marks them pinned."""
    root = tmp_path / "skills"
    name = "fix-sentinel-missing"
    admit(root, name)
    pin = library.Library.load(root).entries[name].get("sha256")
    assert pin, "admission pinned nothing"
    out = tmp_path / "out"

    report = run_export(root, out)

    assert report.exported == [name]
    assert report.refused == []
    result = _result(report, name)
    assert not result.problems
    assert not _notes(result), "an unchanged pinned skill needs no notice"
    manifest = json.loads((out / "MANIFEST.json").read_text())
    entry = next(s for s in manifest["skills"] if s["name"] == name)
    assert entry.get("scripts_sha256") == pin, (
        "MANIFEST must carry the admitted scripts' sha256"
    )
    written = {
        key: hashlib.sha256((out / name / key).read_bytes()).hexdigest()
        for key in library.PINNED
    }
    assert entry["scripts_sha256"] == written
    assert entry.get("scripts_pinned") is True, (
        "scripts that passed their pin check are marked pinned in the MANIFEST"
    )


@pytest.mark.parametrize("strict", [False, True], ids=["default", "--strict"])
def test_an_unpinned_row_exports_with_a_note_that_says_so(tmp_path, strict) -> None:
    """Regression for #238. A row from before #237 has no pin, so there is
    nothing to hold its scripts to. It still exports, --strict included, and
    the export says the skill is unpinned rather than vouching for it: the
    MANIFEST still hashes its scripts, and marks them not pinned."""
    root = tmp_path / "skills"
    name = "fix-sentinel-missing"
    skills.save(sentinel_skill(name), root)
    write_ledger(root, {name: ledger_entry(state="proven", successes=4)})
    assert "sha256" not in library.Library.load(root).entries[name]
    out = tmp_path / "out"

    report = run_export(root, out, strict=strict)

    assert report.exported == [name], "an unpinned row is not refused"
    notes = _notes(_result(report, name))
    assert name in notes and "unpinned" in notes, (
        "the export must say this skill's scripts are unpinned"
    )
    manifest = json.loads((out / "MANIFEST.json").read_text())
    entry = next(s for s in manifest["skills"] if s["name"] == name)
    written = {
        key: hashlib.sha256((out / name / key).read_bytes()).hexdigest()
        for key in library.PINNED
    }
    assert entry.get("scripts_sha256") == written, (
        "an unpinned skill's scripts are still hashed in the MANIFEST"
    )
    assert entry.get("scripts_pinned") is False, (
        "a row with no pin must not read as pinned in the MANIFEST"
    )


def test_a_skill_with_no_ledger_row_exports_under_all_with_a_not_pinned_note(
    tmp_path,
) -> None:
    """Regression for #238. Under --all a skill with no ledger row is selected,
    and with no row there is no pin to check it against. It exports as before,
    with a note that its scripts are not pinned, and the MANIFEST marks them
    not pinned; the admitted skill beside it gets no such note and is marked
    pinned."""
    root = tmp_path / "skills"
    admit(root, "fix-sentinel-missing")
    skills.save(sentinel_skill("fix-zip-sentinels"), root)  # never registered
    assert "fix-zip-sentinels" not in library.Library.load(root).entries
    out = tmp_path / "out"

    report = run_export(root, out, include_all=True)

    assert report.exported == ["fix-sentinel-missing", "fix-zip-sentinels"]
    assert re.search(
        r"unpinned|not pinned|n't pinned",
        _notes(_result(report, "fix-zip-sentinels")),
        re.IGNORECASE,
    ), "the export must say a skill with no ledger row has unpinned scripts"
    assert not _notes(_result(report, "fix-sentinel-missing"))
    manifest = json.loads((out / "MANIFEST.json").read_text())
    pinned = {s["name"]: s.get("scripts_pinned") for s in manifest["skills"]}
    assert pinned == {"fix-sentinel-missing": True, "fix-zip-sentinels": False}, (
        "only the skill whose row pinned its scripts reads as pinned"
    )


def test_dry_run_still_refuses_an_admitted_skill_whose_script_changed(
    tmp_path,
) -> None:
    """Regression for #238. --dry-run reports what a real run would do, so an
    edited admitted skill shows as refused there too, and nothing is written."""
    root = tmp_path / "skills"
    folder = admit(root, "fix-zip-sentinels")
    script, edited = EDITS[0]
    (folder / "scripts" / script).write_text(edited, encoding="utf-8")
    out = tmp_path / "out"

    report = run_export(root, out, dry_run=True)

    assert report.exported == []
    assert report.refused == ["fix-zip-sentinels"]
    assert not out.exists()


@pytest.mark.parametrize("flags", [[], ["--dry-run"]], ids=["export", "--dry-run"])
def test_main_prints_the_refused_skill_with_its_file_and_the_unpinned_note(
    tmp_path, monkeypatch, capsys, flags
) -> None:
    """Regression for #238. The CLI report shows a refused admitted skill on a
    refused line with the file that changed under it, and an unpinned skill's
    note under its own exported line, in a real run and a dry run alike."""
    import export_skills

    root = tmp_path / "skills"
    folder = admit(root, "fix-zip-sentinels")
    script, edited = EDITS[0]
    (folder / "scripts" / script).write_text(edited, encoding="utf-8")
    skills.save(sentinel_skill("fix-sentinel-missing"), root)
    lib = library.Library.load(root)
    lib.entries["fix-sentinel-missing"] = ledger_entry(state="proven")  # pre-pin
    lib.save()
    out = tmp_path / "out"

    monkeypatch.setattr(
        "sys.argv",
        ["export_skills.py", "--skills-root", str(root), "--out", str(out), *flags],
    )
    export_skills.main()
    stdout = capsys.readouterr().out

    refused = _printed_block(stdout, "fix-zip-sentinels")
    assert refused and refused[0].startswith("refused"), (
        "the edited admitted skill must be printed as refused"
    )
    assert any(_names_script(line, script) for line in refused[1:]), (
        "the refusal must name the file that changed"
    )
    unpinned = _printed_block(stdout, "fix-sentinel-missing")
    assert unpinned and "refused" not in unpinned[0]
    assert any("unpinned" in line for line in unpinned[1:]), (
        "the unpinned skill's note must be printed under it"
    )
    assert not (out / "fix-zip-sentinels").exists()


def test_a_retired_skill_whose_script_changed_is_refused_under_include_retired(
    tmp_path,
) -> None:
    """Regression for #238. The pin outlives retirement, so --include-retired
    holds a retired skill to it too: the edited one is refused and named, and
    the unchanged retired one beside it exports. (Which folder the refusal's
    advice names is library.py's wording, fixed in #240, so it isn't
    asserted here.)"""
    root = tmp_path / "skills"
    admit(root, "fix-zip-sentinels")
    admit(root, "fix-sentinel-missing")
    lib = library.Library.load(root)
    for name in ("fix-zip-sentinels", "fix-sentinel-missing"):
        lib.retire(name, reason="failed verification twice in a row")
    lib.save()
    grave = root / library.RETIRED_DIR / "fix-zip-sentinels"
    script, edited = EDITS[0]
    (grave / "scripts" / script).write_text(edited, encoding="utf-8")
    out = tmp_path / "out"

    report = run_export(root, out, include_retired=True)

    assert report.refused == ["fix-zip-sentinels"], (
        "a retired skill whose scripts changed exported as admitted"
    )
    assert report.exported == ["fix-sentinel-missing"]
    assert not (out / "fix-zip-sentinels").exists()
    problems = _result(report, "fix-zip-sentinels").problems
    assert any(
        "fix-zip-sentinels" in p and _names_script(p, script) for p in problems
    ), "the refusal names the skill and the file that changed"
