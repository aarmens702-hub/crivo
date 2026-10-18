"""Tests for the SKILL.md format layer (P2 R1-R4).

Portability is the whole point of the format, so these tests are mostly about
what the validator *refuses*: a seventh frontmatter field, a name that doesn't
match its directory, metadata that isn't string->string. claude.ai and the
Skills API hard-fail on those, and a skill that can't be uploaded isn't a skill.
"""

import json
from pathlib import Path

import pytest

from crivo import skills


def make(**kw) -> "skills.Skill":
    base = {
        "name": "fix-sentinel-missing",
        "description": "Replace missing-data tokens with NaN. Use when a column "
        "holds 'N/A' or 'unknown' as if they were values.",
        "fix_source": "def fix(df, columns):\n    return df.copy()\n",
        "test_source": "def test_fix():\n    assert True\n",
        "metadata": {"disease": "4"},
    }
    base.update(kw)
    return skills.Skill(**base)


def test_render_emits_the_six_spec_fields_and_nothing_else() -> None:
    text = skills.render(make())
    keys = [
        line.split(":", 1)[0]
        for line in text.splitlines()[1:]
        if line and not line.startswith((" ", "-", "#")) and ":" in line
    ]
    assert keys[: len(skills.SPEC_FIELDS)] == list(skills.SPEC_FIELDS)
    assert "name: fix-sentinel-missing" in text


def test_parse_round_trips_frontmatter_and_body() -> None:
    original = make(
        body="## How it works\n\nNormalise, then replace.\n",
        metadata={"disease": "4", "version": "1", "spawned_by": "beers/ibu"},
    )
    front, body = skills.parse(skills.render(original))
    assert set(front) == set(skills.SPEC_FIELDS)
    assert front["name"] == original.name
    assert front["description"] == original.description  # quoting survives
    assert front["metadata"] == original.metadata
    assert front["allowed-tools"] == []
    assert body.strip() == original.body.strip()


def test_parse_refuses_what_it_cannot_represent() -> None:
    """Guessing at richer YAML would produce a skill that fails at upload time,
    far from the mistake. Refuse instead."""
    deeper = "---\nname: x\nmetadata:\n  nested:\n    deeper: 1\n---\nbody\n"
    with pytest.raises(ValueError, match="subset"):
        skills.parse(deeper)
    with pytest.raises(ValueError, match="frontmatter"):
        skills.parse("# just a heading\n")
    with pytest.raises(ValueError, match="unterminated"):
        skills.parse("---\nname: x\n")


def test_validate_passes_a_well_formed_skill() -> None:
    assert skills.validate(make(), "fix-sentinel-missing") == []


@pytest.mark.parametrize(
    "bad", ["Fix_Upper", "fix sentinel", "", "x" * 65, "fix/slash"]
)
def test_name_charset_and_directory_agreement_are_enforced(bad: str) -> None:
    assert any("name" in p for p in skills.validate(make(name=bad), bad))
    mismatch = skills.validate(make(), "some-other-directory")
    assert any("directory" in p for p in mismatch)


def test_description_metadata_and_body_limits_are_enforced() -> None:
    """The spec's own limits: description 1-1024, metadata string->string,
    body under 500 lines so progressive disclosure stays cheap."""
    here = "fix-sentinel-missing"
    for bad in ("", "x" * 1025):
        assert any(
            "description" in p for p in skills.validate(make(description=bad), here)
        )
    assert any(
        "metadata" in p for p in skills.validate(make(metadata={"disease": 4}), here)
    )
    assert any("500" in p for p in skills.validate(make(body="x\n" * 501), here))


def test_fix_source_must_honour_the_contract() -> None:
    """R3: a top-level `fix(df, columns)`. Checked by parsing, not by string
    search — a docstring mentioning fix(df, columns) is not an implementation."""
    here = "fix-sentinel-missing"
    no_fix = make(
        fix_source='"""calls fix(df, columns)"""\ndef other(df):\n    return df\n'
    )
    assert any("fix(df, columns)" in p for p in skills.validate(no_fix, here))
    wrong_arity = make(fix_source="def fix(df):\n    return df\n")
    assert any("fix(df, columns)" in p for p in skills.validate(wrong_arity, here))
    broken = make(fix_source="def fix(df, columns:\n")
    assert any("syntax" in p.lower() for p in skills.validate(broken, here))


def test_save_writes_the_layout_and_load_round_trips_it(tmp_path) -> None:
    original = make(metadata={"disease": "4", "version": "2"}, body="## Notes\n")
    path = skills.save(original, tmp_path)
    assert path == tmp_path / "fix-sentinel-missing"
    assert (path / "scripts" / "fix.py").read_text().startswith("def fix(df, columns)")
    assert (path / "scripts" / "test_fix.py").exists()

    loaded = skills.load(path)
    assert loaded.name == original.name
    assert loaded.description == original.description
    assert loaded.metadata == original.metadata
    assert loaded.fix_source == original.fix_source
    assert loaded.test_source == original.test_source


def _load_or_error(path):
    """skills.load, with a refusal returned instead of raised, so a test that
    reads back an unreadable skill fails on its assertion rather than erroring."""
    try:
        return skills.load(path)
    except ValueError as exc:
        return exc


def test_a_multiline_description_survives_save_and_load(tmp_path) -> None:
    """Regression for #27. The model's <description> reaches the skill unedited,
    so a person can admit one that spans lines. save wrote it and load could not
    read it back, so every later clean skipped the skill as unreadable and the
    person's approval was silently lost."""
    original = make(
        description="Fixes x.\nUse when y.",
        metadata={"born_from": "a\rb", "note": "p q"},
    )
    path = skills.save(original, tmp_path)

    loaded = _load_or_error(path)
    assert isinstance(loaded, skills.Skill), f"load refused what save wrote: {loaded}"
    assert loaded.description == original.description
    assert loaded.metadata == original.metadata


@pytest.mark.parametrize(
    "text",
    [
        r"Splits cells on a literal \n, as in C:\new\notes.",
        "Splits cells on a literal \\n.\nUse when a column holds 'a\\nb'.",
    ],
    ids=["literal-only", "literal-beside-a-real-break"],
)
def test_a_literal_backslash_n_is_not_read_as_a_newline(tmp_path, text) -> None:
    """Regression for #27. Escaping line breaks means decoding \\n again, and a
    decoder built from chained str.replace calls turns the two characters
    backslash-n into a newline. The literal must come back as written, alone and
    beside a real line break."""
    original = make(description=text, metadata={"born_from": text})
    loaded = _load_or_error(skills.save(original, tmp_path))
    assert isinstance(loaded, skills.Skill), f"load refused what save wrote: {loaded}"
    assert loaded.description == text
    assert loaded.metadata == {"born_from": text}


# Every boundary str.splitlines() breaks a line on (the Python docs' table, plus
# the \r\n pair). parse() splits the frontmatter with splitlines, so each one
# inside a quoted value used to cut the value in two.
LINE_SEPARATORS = {
    "lf": "\n",
    "cr": "\r",
    "crlf": "\r\n",
    "vt": "\x0b",
    "ff": "\x0c",
    "fs": "\x1c",
    "gs": "\x1d",
    "rs": "\x1e",
    "nel": "\x85",
    "u2028": "\N{LINE SEPARATOR}",
    "u2029": "\N{PARAGRAPH SEPARATOR}",
}


@pytest.mark.parametrize(
    "sep", list(LINE_SEPARATORS.values()), ids=list(LINE_SEPARATORS)
)
def test_every_line_separator_round_trips(tmp_path, sep) -> None:
    """Regression for #27. Not only \\n: every character splitlines breaks on
    survives save and load, in the description and in a metadata value. Each is
    written as a standard escape, so a reader other than ours (JSON here, whose
    string escapes YAML's double-quoted style shares) decodes it the same way."""
    description = f"Fixes x.{sep}Use when y."
    original = make(description=description, metadata={"born_from": f"a{sep}b"})
    loaded = _load_or_error(skills.save(original, tmp_path))
    assert isinstance(loaded, skills.Skill), f"load refused what save wrote: {loaded}"
    assert loaded.description == description
    assert loaded.metadata == original.metadata

    line = next(
        row
        for row in skills.render(original).split("\n")
        if row.startswith("description: ")
    )
    assert json.loads(line.removeprefix("description: ")) == description


_ROOT = Path(__file__).resolve().parents[1]


def test_the_committed_skills_still_load() -> None:
    """Regression for #27. The new escapes must not change how the skills
    already in the repo read back: each loads, and its description is what an
    independent reader of the quoted line (JSON) makes of it."""
    folders = sorted(p.parent for p in (_ROOT / "skills").glob("*/SKILL.md"))
    assert folders, "no committed skills found under skills/"
    for folder in folders:
        loaded = _load_or_error(folder)
        assert isinstance(loaded, skills.Skill), f"{folder.name}: {loaded}"
        assert loaded.name == folder.name
        line = next(
            row
            for row in (folder / "SKILL.md").read_text(encoding="utf-8").split("\n")
            if row.startswith("description: ")
        )
        assert loaded.description == json.loads(line.removeprefix("description: "))


def test_a_skill_md_from_the_old_renderer_decodes_the_same() -> None:
    """Regression for #27. Files written before the fix escape only the
    backslash and the quote, and must decode exactly as they did: an escaped
    backslash before n or u0041 stays a literal backslash. A lone backslash
    before a letter the format does not escape (a hand-edited Windows path)
    stays as written."""
    text = (
        "---\n"
        "name: fix-sentinel-missing\n"
        r'description: "Treats \"N/A\" as missing. Reads C:\\new\\data and \\u0041 as text."'
        "\n"
        'license: "MIT"\n'
        'compatibility: ">=0.1.0"\n'
        "metadata:\n"
        r'  born_from: "C:\\exports\\q3.csv"'
        "\n"
        r'  note: "hand-edited C:\temp\users"'
        "\n"
        "allowed-tools: []\n"
        "---\n"
        "## Notes\n"
    )
    front, body = skills.parse(text)
    assert front["description"] == (
        r'Treats "N/A" as missing. Reads C:\new\data and \u0041 as text.'
    )
    assert front["metadata"] == {
        "born_from": r"C:\exports\q3.csv",
        "note": r"hand-edited C:\temp\users",
    }
    assert body == "## Notes\n"


def test_save_refuses_an_invalid_skill_without_writing_anything(tmp_path) -> None:
    """A half-written folder would be found by retrieval later and treated as
    a real skill, so refusal has to happen before anything is created."""
    with pytest.raises(ValueError, match="name"):
        skills.save(make(name="NOT VALID"), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_load_refuses_a_seventh_frontmatter_field(tmp_path) -> None:
    """The field a human helpfully adds by hand is the one that breaks upload."""
    path = skills.save(make(), tmp_path)
    md = (
        (path / "SKILL.md")
        .read_text()
        .replace("license:", "author: someone\nlicense:", 1)
    )
    (path / "SKILL.md").write_text(md)
    with pytest.raises(ValueError, match="author"):
        skills.load(path)
