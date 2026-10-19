"""scripts/leak_scan.py (spec: specs/2026-10-17-eval-tooling.md EV12, #75).

leak_scan fails CI when text the model reads (every str constant of
src/crivo/prompts.py but its module docstring, f-string parts and tuples
included; the docstrings of @app.tool() functions in src/crivo/mcp_server.py;
skills/**/SKILL.md and .claude/skills/crivo/SKILL.md) holds material from a
suite it is graded on: SMOKE case names, the injectors' literals, and trap
fields under bench/traps/<suite>/. It names where (protected path, line, item
id), never the matched text, since CI logs on a public repo are public. A trap's
id is a digest of its file's stem, so no id carries a trap's words. Neither side
passes vacuously: a missing or unparseable source, or one that yields nothing
to scan, is a violation naming only the file (review decisions on #75).

Offline and keyless: every test builds a tmp tree holding copies of the real
bench/corpus.py, bench/corrupt.py and bench/bases.py, plus tmp protected texts
and tmp traps (under traps/dev/ only). Case names and taxonomy slugs are read
at runtime from bench.corpus.SMOKE and crivo.detect.SLUGS, never written here.
"""

import hashlib
import importlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bench.corpus import SMOKE
from crivo.detect import SLUGS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "leak_scan.py"
sys.path.insert(0, str(ROOT / "scripts"))

SUITE = ("bench/corpus.py", "bench/corrupt.py", "bench/bases.py")
PROMPTS = "src/crivo/prompts.py"
MCP = "src/crivo/mcp_server.py"
SKILL = "skills/fix-empty-columns/SKILL.md"
CRIVO_SKILL = ".claude/skills/crivo/SKILL.md"
SHIP_SKILL = ".claude/skills/ship/SKILL.md"  # a workflow skill: not protected
ALLOW = "scripts/leak_scan_allow.txt"
TRAPS = "bench/traps/dev"

NAME = SMOKE[0]["name"]
OTHER_NAME = SMOKE[1]["name"]

# A dev trap as B4 reads one: an object with name, question and expected.
TRAP = {
    "name": "refunds-after-reprice",
    "question": (
        "How many refunds were issued in the week after the March price change?"
    ),
    "expected": 12408,
}
SIX = "refunds were issued in the week"  # a 6-word run of TRAP's question
FIVE = "refunds were issued in the"  # a 5-word run of it


def _leak_scan():
    """scripts/leak_scan.py, imported per test, so a missing script fails
    each test on this assert instead of erroring the whole file."""
    assert importlib.util.find_spec("leak_scan") is not None, (
        "scripts/leak_scan.py does not exist yet (#75)"
    )
    return importlib.import_module("leak_scan")


def _case(stem):
    """Review decision 2 on #75: a trap's case id, from its file's stem."""
    return "case-" + hashlib.sha256(stem.encode("utf-8")).hexdigest()[:12]


def _prompts(*extra, comment=None, source=""):
    """A prompts.py: three str constants and an int, then one constant per
    extra text, then any raw `source`. A text holding a newline is written
    triple-quoted, so the break is a real one in the source."""
    lines = [
        'SYSTEM_PROMPT = """You are a careful data analyst operating a kernel.',
        "Re-check every fix before you keep it, and cite the cell that proves it.",
        '"""',
        'NUDGE_PROMPT = "Reply with exactly one tag."',
        "MAX_TURNS = 12",
        'CHECKS_PROMPT = "List the checks you ran and what each one showed."',
    ]
    if comment is not None:
        lines.append(f"# {comment}")
    for i, text in enumerate(extra):
        value = f'"""{text}"""' if "\n" in text else repr(text)
        lines.append(f"EXTRA_{i}_PROMPT = {value}")
    return "\n".join(lines) + "\n" + source


def _mcp(
    module="The MCP layer over the plain functions.",
    helper="Resolve a client path inside the configured root.",
    server="Each docstring below is the contract a calling model acts on.",
    tool="Report what is wrong with a data file. Free, keyless, read-only.",
    obj="app",
    tool_docs=True,
):
    """An mcp_server.py shaped like the real one: two tools nested in
    build_server, a module docstring and two docstrings that are not tools'.
    `obj` renames the server object the tools are decorated through;
    tool_docs=False leaves both tools without a docstring."""
    text = "\n".join(
        [
            f'"""{module}"""',
            "",
            "",
            "def _resolve(path):",
            f'    """{helper}"""',
            "    return path",
            "",
            "",
            "def build_server():",
            f'    """{server}"""',
            "    from mcp.server.mcpserver import MCPServer",
            "",
            f'    {obj} = MCPServer("crivo")',
            "",
            f"    @{obj}.tool()",
            "    def diagnose_file(path: str) -> str:",
            f'        """{tool}"""',
            "        return _resolve(path)",
            "",
            f"    @{obj}.tool()",
            "    def why(session_id: str) -> str:",
            '        """The provenance chain for an open session."""',
            "        return session_id",
            "",
            f"    return {obj}",
            "",
        ]
    )
    if not tool_docs:
        text = "\n".join(
            ln for ln in text.splitlines() if not ln.startswith('        """')
        )
    return text


def _skill(name, description, body, extra=""):
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n{extra}"


def _clean():
    """Protected texts with nothing from any suite: 3 prompt constants, 2 tool
    docstrings and 2 skills, 7 protected texts in all."""
    return {
        PROMPTS: _prompts(),
        MCP: _mcp(),
        SKILL: _skill(
            "fix-empty-columns",
            "Drop a column that holds one value on every row.",
            "# Fix empty columns\n\nRe-run the detector after the drop and keep "
            "the fix only when it passes.",
        ),
        CRIVO_SKILL: _skill(
            "crivo",
            "Diagnose and clean a data file with crivo.",
            "# crivo\n\nRun the keyless diagnose first, then read the findings.",
        ),
        SHIP_SKILL: _skill(
            "ship", "Run the checks and push.", "# ship\n\nRun the checks, then push."
        ),
        ALLOW: "",
    }


def _tree(root, files=None):
    """A tmp tree: copies of the real corpus and injectors, the clean protected
    texts, and any overrides (str text, bytes, or a dict written as a trap)."""
    for rel in SUITE:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, root / rel)
    for rel, content in {**_clean(), **(files or {})}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, dict):
            path.write_text(json.dumps(content, indent=2))
        else:
            path.write_text(content)
    return root


def _scan(capsys, root, *args):
    code = _leak_scan().main(["--root", str(root), *args])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    return code, [ln for ln in output.splitlines() if ln.strip()], output


def _line(text, needle):
    """The one 1-based line of `text` that holds `needle`."""
    hits = [i for i, ln in enumerate(text.splitlines(), 1) if needle in ln]
    assert len(hits) == 1, f"expected one line holding the needle, found {hits}"
    return hits[0]


def _corpus_line(root, name):
    """The line of bench/corpus.py where the case's name literal sits."""
    return _line((root / "bench/corpus.py").read_text(), f'"{name}"')


def _name_hit(rel, text, needle, root, name):
    """The violation a case name planted as `needle` in protected file `rel`
    (content `text`) produces: that line, and the name's line in corpus.py."""
    cline = _corpus_line(root, name)
    return f"{rel}:{_line(text, needle)}: matches corpus.py:{cline}"


def _sha(match):
    """B3: sha256 of the match, casefolded, whitespace collapsed."""
    folded = " ".join(match.casefold().split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()


def _violation(line):
    """`<protected path>:<line>: matches <item id>`, split into its parts."""
    found = re.fullmatch(r"(\S+?):(\d+): matches (\S+)", line)
    assert found, f"not a violation line: {line!r}"
    return found.group(1), int(found.group(2)), found.group(3)


def _protected_count(summary):
    found = re.search(r"(\d+)\s+protected", summary, re.IGNORECASE)
    assert found, f"the summary names no protected-text count: {summary!r}"
    return int(found.group(1))


def _stalls(name):
    return f"When a run stalls, re-open {name} and compare."


@pytest.mark.parametrize(
    "index", range(len(SMOKE)), ids=[f"smoke-{i:02d}" for i in range(len(SMOKE))]
)
def test_a_case_name_in_a_prompt_fails_without_echoing_it(tmp_path, capsys, index):
    """#75 Done when 1: a tmp prompts.py constant holding a SMOKE case name
    exits 1 with one line naming the prompt's line and the name's line in
    corpus.py, and the output never holds the name in any case."""
    name = SMOKE[index]["name"]
    prompts = _prompts(_stalls(name))
    root = _tree(tmp_path, {PROMPTS: prompts})

    code, lines, output = _scan(capsys, root)

    assert name.casefold() not in output.casefold(), "the output echoes the name"
    assert code == 1
    assert lines == [_name_hit(PROMPTS, prompts, name, root, name)], lines


@pytest.mark.parametrize(
    "form, caught",
    [
        ("upper", True),
        ("in-parens", True),
        ("word-prefix", False),
        ("underscore-suffix", False),
    ],
)
def test_a_case_name_matches_only_as_a_whole_token(tmp_path, capsys, form, caught):
    """#75 step 3: names match case-insensitively as whole tokens; the same
    characters inside a longer word are not the name."""
    text = {
        "upper": NAME.upper(),
        "in-parens": f"({NAME})",
        "word-prefix": f"re{NAME}",
        "underscore-suffix": f"{NAME}_v2",
    }[form]
    prompts = _prompts(f"When a run stalls, re-open {text} and compare.")
    root = _tree(tmp_path, {PROMPTS: prompts})

    code, lines, _ = _scan(capsys, root)

    if caught:
        assert code == 1, lines
        assert lines == [_name_hit(PROMPTS, prompts, text, root, NAME)], lines
    else:
        assert (code, len(lines)) == (0, 1), lines


@pytest.mark.parametrize(
    "allowed, passes",
    [
        ("corpus-name", True),
        ("trap-shingle", True),
        ("other-path", False),
        ("other-sha", False),
        ("other-source", False),
    ],
)
def test_an_allow_line_passes_its_match_and_no_other(tmp_path, capsys, allowed, passes):
    """#75 Done when 2, B3: `<path>:<item id>:<sha256>  # reason` in the
    default allow file passes the match it names (the sha taken over the match
    casefolded, whitespace collapsed); a line naming another protected file,
    another match or another source file passes nothing."""
    if allowed == "trap-shingle":
        wrapped = "REFUNDS WERE ISSUED\nIN THE WEEK"
        skill = _clean()[SKILL] + f"\nCount {wrapped} before answering.\n"
        root = _tree(tmp_path, {SKILL: skill, f"{TRAPS}/t017.json": TRAP})
        code, lines, _ = _scan(capsys, root)
        assert code == 1 and len(lines) == 1, lines
        path, _, item = _violation(lines[0])
        allow = f"{path}:{item}:{_sha(wrapped)}  # quotes the trap on purpose\n"
    else:
        prompts = _prompts(_stalls(NAME.upper()))
        root = _tree(tmp_path, {PROMPTS: prompts})
        cline = _corpus_line(root, NAME)
        path, item, sha = PROMPTS, f"corpus.py:{cline}", _sha(NAME.upper())
        if allowed == "other-path":
            path = SKILL
        elif allowed == "other-sha":
            sha = _sha(OTHER_NAME)
        elif allowed == "other-source":
            item = f"corrupt.py:{cline}"
        allow = f"{path}:{item}:{sha}  # names the case on purpose\n"
    (root / ALLOW).write_text(allow)

    code, lines, _ = _scan(capsys, root)

    if passes:
        assert (code, len(lines)) == (0, 1), lines
    else:
        assert code == 1, lines
        assert lines == [_name_hit(PROMPTS, prompts, NAME.upper(), root, NAME)], lines


def test_an_allow_line_still_matches_after_its_item_moves(tmp_path, capsys):
    """#75 B3: the item's line number is informational, so an allow line
    written against the old line still passes once an edit to corpus.py moves
    the name down a line (and the violation, without it, names the new line)."""
    prompts = _prompts(_stalls(NAME))
    root = _tree(tmp_path, {PROMPTS: prompts})
    before = _corpus_line(root, NAME)
    allow = root / "review" / "allow.txt"
    allow.parent.mkdir()
    allow.write_text(
        f"{PROMPTS}:corpus.py:{before}:{_sha(NAME)}  # names the case on purpose\n"
    )
    corpus = root / "bench/corpus.py"
    corpus.write_text("# Corpus specs, reordered.\n" + corpus.read_text())
    assert _corpus_line(root, NAME) == before + 1

    code, lines, _ = _scan(capsys, root)
    assert code == 1, lines
    assert lines == [
        f"{PROMPTS}:{_line(prompts, NAME)}: matches corpus.py:{before + 1}"
    ], lines

    code, lines, _ = _scan(capsys, root, "--allow", str(allow))
    assert (code, len(lines)) == (0, 1), lines


@pytest.mark.parametrize("where", ["skill", "prompt"])
@pytest.mark.parametrize("words", [6, 5])
def test_a_six_word_run_of_a_trap_question_is_caught_and_five_words_are_not(
    tmp_path, capsys, where, words
):
    """#75 Done when 3, step 3: six words of a dev trap's question, in another
    case and wrapped across a line break, fail naming the line the run starts
    on and the trap's question; five words of it pass. Neither the phrase nor
    the trap's name reaches the output."""
    # "REFUNDS WERE ISSUED" / "IN THE WEEK": no word before or after the run
    # extends it into another 6-word run of the question
    upper = (SIX if words == 6 else FIVE).upper().split()
    wrapped = " ".join(upper[:3]) + "\n" + " ".join(upper[3:])
    sentence = f"Count {wrapped} ledger first."
    if where == "skill":
        rel, text = SKILL, _clean()[SKILL] + f"\n{sentence}\n"
    else:
        rel, text = PROMPTS, _prompts(sentence)
    root = _tree(tmp_path, {rel: text, f"{TRAPS}/t017.json": TRAP})

    code, lines, output = _scan(capsys, root)

    folded = output.casefold()
    assert "refunds were issued" not in folded, "the output echoes the phrase"
    assert TRAP["name"] not in folded, "the output echoes the trap's name"
    if words == 5:
        assert (code, len(lines)) == (0, 1), lines
        return
    assert code == 1, lines
    assert len(lines) == 1, lines
    path, line, item = _violation(lines[0])
    assert (path, line) == (rel, _line(text, "REFUNDS WERE ISSUED")), lines
    assert item == f"dev/{_case('t017')}:question", item


@pytest.mark.parametrize(
    "field, expected, caught",
    [("name", 12408, True), ("expected", 12408, True), ("expected", 42, False)],
    ids=["name", "expected", "expected-under-5-chars"],
)
def test_a_trap_name_or_expected_value_is_caught_whole(
    tmp_path, capsys, field, expected, caught
):
    """#75 step 2, B4: a trap's name and the str() of its expected value are
    items when 5 or more characters long; a shorter value is not."""
    trap = {**TRAP, "expected": expected}
    value = str(trap[field])
    prompts = _prompts(f"Start from {value} and work backwards.")
    root = _tree(tmp_path, {PROMPTS: prompts, f"{TRAPS}/t017.json": trap})

    code, lines, output = _scan(capsys, root)

    if not caught:
        assert (code, len(lines)) == (0, 1), lines
        return
    assert value not in output.casefold(), "the output echoes the value"
    assert code == 1 and len(lines) == 1, lines
    path, line, item = _violation(lines[0])
    assert (path, line) == (PROMPTS, _line(prompts, value)), lines
    assert item == f"dev/{_case('t017')}:{field}", item


def test_clean_text_exits_0_with_one_summary_line_of_counts(tmp_path, capsys):
    """#75 Done when 4: a tree whose protected texts hold nothing from the
    suite, with no traps directory, exits 0 with one summary line counting the
    7 protected texts: 3 str constants (not the int), 2 tool docstrings (not
    the module's, the helper's or build_server's) and 2 skills (not the
    workflow skill)."""
    root = _tree(tmp_path)
    assert not (root / "bench/traps").exists()

    code, lines, _ = _scan(capsys, root)

    assert code == 0, lines
    assert len(lines) == 1, lines
    assert _protected_count(lines[0]) == 7, lines


def test_this_repo_has_no_leaks(capsys):
    """#75 Done when 5: this checkout's prompts, tool docstrings and skills
    hold nothing from the suite under its own allow file, and the summary
    shows the scan read protected text (not a vacuous pass)."""
    code, lines, _ = _scan(capsys, ROOT)

    assert code == 0, lines
    assert len(lines) == 1, lines
    assert _protected_count(lines[0]) > 0, lines


@pytest.mark.parametrize(
    "where, caught",
    [
        ("tool-docstring", True),
        ("helper-docstring", False),
        ("build-server-docstring", False),
        ("mcp-module-docstring", False),
        ("skill", True),
        ("crivo-skill", True),
        ("workflow-skill", False),
        ("prompts-comment", False),
    ],
)
def test_only_text_the_model_reads_is_protected(tmp_path, capsys, where, caught):
    """#75 step 1: a case name in an @app.tool() docstring, a skills/**
    SKILL.md or the crivo skill fails naming that file and line; in another
    docstring of mcp_server.py, a workflow skill or a prompts.py comment it is
    not text the model reads, and passes."""
    sentence = _stalls(NAME)
    clean = _clean()
    rel, text = {
        "tool-docstring": (MCP, _mcp(tool=sentence)),
        "helper-docstring": (MCP, _mcp(helper=sentence)),
        "build-server-docstring": (MCP, _mcp(server=sentence)),
        "mcp-module-docstring": (MCP, _mcp(module=sentence)),
        "skill": (SKILL, clean[SKILL] + f"\n{sentence}\n"),
        "crivo-skill": (CRIVO_SKILL, clean[CRIVO_SKILL] + f"\n{sentence}\n"),
        "workflow-skill": (SHIP_SKILL, clean[SHIP_SKILL] + f"\n{sentence}\n"),
        "prompts-comment": (PROMPTS, _prompts(comment=sentence)),
    }[where]
    root = _tree(tmp_path, {rel: text})

    code, lines, output = _scan(capsys, root)

    assert NAME.casefold() not in output.casefold(), "the output echoes the name"
    if caught:
        assert code == 1, lines
        assert lines == [_name_hit(rel, text, NAME, root, NAME)], lines
    else:
        assert (code, len(lines)) == (0, 1), lines


@pytest.mark.parametrize(
    "form, caught",
    [
        ("fstring", True),
        ("fstring-multiline", True),
        ("tuple", True),
        ("in-a-function", True),
        ("module-docstring", False),
    ],
)
def test_every_str_constant_of_prompts_is_protected_but_its_module_docstring(
    tmp_path, capsys, form, caught
):
    """#75 review decision 3: a prompt turned into an f-string (its parts), a
    tuple of prompt strings, or a string a function returns stays scanned, and
    a case name in one fails naming the name's own line; the module docstring
    is not text the model reads, and passes."""
    sentence = _stalls(NAME)
    if form == "module-docstring":
        prompts = f'"""{sentence}"""\n\n' + _prompts()
    else:
        source = {
            "fstring": f'TOOL = "diagnose"\nCASE_PROMPT = f"Run {{TOOL}}. {sentence}"\n',
            "fstring-multiline": (
                f'TOOL = "diagnose"\nCASE_PROMPT = f"""Run {{TOOL}} first.\n'
                f'{sentence}"""\n'
            ),
            "tuple": f'STEPS = (\n    "Reply with one tag.",\n    {sentence!r},\n)\n',
            "in-a-function": f"def nudge(turn):\n    return {sentence!r}\n",
        }[form]
        prompts = _prompts(source=source)
    root = _tree(tmp_path, {PROMPTS: prompts})

    code, lines, output = _scan(capsys, root)

    assert NAME.casefold() not in output.casefold(), "the output echoes the name"
    if caught:
        assert code == 1, lines
        assert lines == [_name_hit(PROMPTS, prompts, NAME, root, NAME)], lines
    else:
        assert (code, len(lines)) == (0, 1), lines


VIOLATION = re.compile(r"\S+:\d+: matches \S+")


@pytest.mark.parametrize("planted", [False, True], ids=["clean", "case-name"])
def test_tools_under_a_renamed_decorator_are_scanned_or_a_violation(
    tmp_path, capsys, planted
):
    """#75 review: a build_server that names its server `server` and decorates
    with @server.tool() can't drop the tools silently. Either their docstrings
    are protected (a clean tree counts all 7 texts, and a case name in one
    fails naming its line) or mcp_server.py is a violation naming the file.
    Which of the two is the builder's call; passing with 0 tools is neither."""
    tool = _stalls(NAME) if planted else "Report what is wrong with a data file."
    text = _mcp(obj="server", tool=tool)
    root = _tree(tmp_path, {MCP: text})

    code, lines, output = _scan(capsys, root)

    assert NAME.casefold() not in output.casefold(), "the output echoes the name"
    if code == 0:
        assert not planted, "a case name in a renamed tool's docstring passed"
        assert len(lines) == 1, lines
        assert _protected_count(lines[0]) == 7, "the renamed tools went unscanned"
        return
    assert code == 1 and len(lines) == 1, lines
    hit = _name_hit(MCP, text, NAME, root, NAME) if planted else None
    names_the_file = lines[0].startswith(f"{MCP}:") and not VIOLATION.fullmatch(
        lines[0]
    )
    assert lines[0] == hit or names_the_file, lines


CATCH = "Tailspin Toys Ltd"


def _guarded(guard):
    """(injector source, the guarded text a prompt quotes, the nearby literal
    in the same file that is still suite material)."""
    if guard == "module-docstring":
        doc = "Plant ledger drift across the Northwind quarter close."
        return f'"""{doc}"""\n\nCUSTOMER = {CATCH!r}\n', doc, CATCH
    if guard == "function-docstring":
        doc = "Overwrite the Contoso harbour freight codes in place."
        source = (
            f'def plant(frame):\n    """{doc}"""\n'
            f'    frame["vendor"] = {CATCH!r}\n    return frame\n'
        )
        return source, doc, CATCH
    if guard == "fstring-fragment":
        fragment = "Exported from Fabrikam Ledger"
        source = (
            f'def footer(stamp):\n    return f"{fragment}{{stamp}}"\n\n\n'
            f"VENDOR = {CATCH!r}\n"
        )
        return source, fragment, CATCH
    slugs = sorted(SLUGS.values())
    if guard == "slug":
        # equality, not containment: a message that carries a slug still counts
        message = f"disease ({slugs[0]}): no category column found"
        source = "".join(f"KIND_{i} = {s!r}\n" for i, s in enumerate(slugs))
        return source + f"MESSAGE = {message!r}\n", ", ".join(slugs), message
    # identifier: a single lowercase identifier is skipped, a lowercase phrase
    # is not
    label = "net amount due"
    source = f"MISSING = 'unknown'\nCOLUMN = 'amount_due'\nLABEL = {label!r}\n"
    return source, "unknown values and amount_due", label


@pytest.mark.parametrize("injector", ["corrupt.py", "bases.py"])
@pytest.mark.parametrize(
    "guard",
    [
        "module-docstring",
        "function-docstring",
        "fstring-fragment",
        "slug",
        "identifier",
    ],
)
def test_each_guard_skips_its_literal_and_a_nearby_literal_is_caught(
    tmp_path, capsys, injector, guard
):
    """#75 G1-G3: an injector's docstrings (G1), the parts of an f-string
    (G1), a literal equal to a taxonomy slug (G2) and a single lowercase
    identifier (G3) are not suite material, so a prompt quoting them passes;
    a plain literal in the same file, quoted by the same prompts, still fails
    naming its line."""
    source, guarded, catch = _guarded(guard)
    prompts = _prompts(guarded, f"Cite {catch} when asked.")
    root = _tree(tmp_path, {PROMPTS: prompts, f"bench/{injector}": source})

    code, lines, output = _scan(capsys, root)

    assert catch.casefold() not in output.casefold(), "the output echoes it"
    assert code == 1, lines
    pline, iline = _line(prompts, catch), _line(source, repr(catch))
    assert lines == [f"{PROMPTS}:{pline}: matches {injector}:{iline}"], lines


WHOLE = b'{"name": "late-fee-waivers", "question": "Which branch waived the most'
WHOLE += b' late fees in May?", "expected": 7}'


@pytest.mark.parametrize(
    "stem, content, readable",
    [
        ("t031", WHOLE[: WHOLE.index(b" in May")], False),
        (
            "t031",
            b'{"name": "late-fee-waivers\xff", "question": "Which branch"}',
            False,
        ),
        ("t031", b'[{"name": "late-fee-waivers", "question": "Which branch"}]', False),
        ("late-fee-waivers", WHOLE[: WHOLE.index(b" in May")], False),
        ("t031", WHOLE, True),
    ],
    ids=["truncated", "not-utf8", "not-an-object", "stem-is-its-name", "readable"],
)
def test_an_unreadable_trap_file_fails_naming_only_its_digest(
    tmp_path, capsys, stem, content, readable
):
    """#75 B4, review decision 2: a trap file that does not parse, or holds no
    JSON object, is a violation under the trap's digest id (dev/case-<12 hex>),
    with none of its text and none of its stem's words, even when the stem is
    the trap's name; the same trap, whole, passes."""
    root = _tree(tmp_path, {f"{TRAPS}/{stem}.json": content})

    code, lines, output = _scan(capsys, root)

    folded = output.casefold()
    for text in ("late-fee-waivers", "which branch", "late fees"):
        assert text not in folded, "the output echoes the trap file's text"
    if readable:
        assert (code, len(lines)) == (0, 1), lines
        return
    for word in re.findall(r"[a-z0-9]+", stem.casefold()):
        assert word not in folded, "the output carries a word of the trap's stem"
    assert code == 1, lines
    assert len(lines) == 1, lines
    assert f"dev/{_case(stem)}" in lines[0], lines


QUESTION_SLUG = "-".join(re.findall(r"[a-z0-9]+", TRAP["question"].casefold()))


@pytest.mark.parametrize(
    "stem, planted, field",
    [
        (TRAP["name"], TRAP["name"], "name"),
        (TRAP["name"].title(), TRAP["name"], "name"),
        (TRAP["name"].replace("-", "_"), TRAP["name"], "name"),
        (f"refunds-{TRAP['expected']}", str(TRAP["expected"]), "expected"),
        (QUESTION_SLUG, SIX, "question"),
    ],
    ids=[
        "stem-is-the-name",
        "stem-is-the-name-in-another-case",
        "stem-is-the-name-underscored",
        "stem-holds-the-expected-value",
        "stem-is-a-slug-of-the-question",
    ],
)
def test_a_trap_id_is_a_digest_that_carries_none_of_its_stem(
    tmp_path, capsys, stem, planted, field
):
    """#75 review decision 2: every trap's case id is case-<sha256(stem)[:12]>,
    so a file named for its trap (the name in any case or separator, its
    expected value, a slug of its question) fails under an id, and with output,
    holding none of the stem's words."""
    prompts = _prompts(f"Start from {planted} and work backwards.")
    root = _tree(tmp_path, {PROMPTS: prompts, f"{TRAPS}/{stem}.json": TRAP})

    code, lines, output = _scan(capsys, root)

    folded = output.casefold()
    for word in re.findall(r"[a-z0-9]+", stem.casefold()):
        assert word not in folded, "the output carries a word of the trap's stem"
    assert code == 1 and len(lines) == 1, lines
    path, line, item = _violation(lines[0])
    assert (path, line) == (PROMPTS, _line(prompts, planted)), lines
    assert item == f"dev/{_case(stem)}:{field}", item


# An unparseable source that holds a case name, which must not be echoed.
BROKEN = f'SMOKE = [{{"name": {NAME!r}, "seed": 101}},\n'
# SMOKE built from calls: no name literal for the scanner to read.
NO_LITERAL_NAMES = (
    "def _name(n):\n"
    '    return "-".join(("case", str(n)))\n'
    "\n\n"
    "SMOKE: list[dict] = [\n"
    '    dict(name=_name(1), base=("transactions", {}), diseases=[1], seed=101),\n'
    '    dict(name=_name(2), base=("transactions", {}), diseases=[2], seed=102),\n'
    "]\n"
)
NO_STR_CONSTANT = (
    '"""The prompts: the model\'s contract with the loop."""\n\nMAX_TURNS = 12\n'
)


@pytest.mark.parametrize(
    "rel, content",
    [
        ("bench/corpus.py", None),
        ("bench/corrupt.py", None),
        ("bench/bases.py", None),
        ("bench/corpus.py", BROKEN),
        ("bench/corrupt.py", BROKEN),
        ("bench/bases.py", BROKEN),
        ("bench/corpus.py", "SMOKE: list[dict] = []\n"),
        ("bench/corpus.py", NO_LITERAL_NAMES),
        (PROMPTS, None),
        (MCP, None),
        (CRIVO_SKILL, None),
        (PROMPTS, NO_STR_CONSTANT),
        (MCP, _mcp(tool_docs=False)),
    ],
    ids=[
        "corpus-missing",
        "corrupt-missing",
        "bases-missing",
        "corpus-unparseable",
        "corrupt-unparseable",
        "bases-unparseable",
        "smoke-empty",
        "smoke-without-literal-names",
        "prompts-missing",
        "mcp-server-missing",
        "crivo-skill-missing",
        "prompts-without-a-str-constant",
        "mcp-server-without-a-tool-docstring",
    ],
)
def test_no_source_passes_vacuously(tmp_path, capsys, rel, content):
    """#75 review decision 1: a suite source or a required protected file that
    is missing, won't parse, or yields nothing to scan (no SMOKE names, no str
    constant, no tool docstring) is one violation naming only that file, never
    a clean pass with nothing compared."""
    root = _tree(tmp_path, {} if content is None else {rel: content})
    if content is None:
        (root / rel).unlink()

    code, lines, output = _scan(capsys, root)

    assert NAME.casefold() not in output.casefold(), "the output echoes the name"
    assert code == 1, lines
    assert len(lines) == 1, lines
    assert rel in lines[0], lines
    assert not VIOLATION.fullmatch(lines[0]), lines


@pytest.mark.parametrize("state", ["clean", "leak"])
def test_the_script_scans_the_directory_it_runs_in(tmp_path, state):
    """#75 step 5: `python scripts/leak_scan.py` with no flags scans the repo
    it runs in (--root defaults to the cwd), so CI's step works as written."""
    assert SCRIPT.exists(), "scripts/leak_scan.py does not exist yet (#75)"
    prompts = _prompts(_stalls(NAME)) if state == "leak" else _prompts()
    root = _tree(tmp_path, {PROMPTS: prompts})

    run = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    lines = [ln for ln in (run.stdout + run.stderr).splitlines() if ln.strip()]

    assert "Traceback" not in run.stderr, "the script crashed"
    if state == "clean":
        assert (run.returncode, len(lines)) == (0, 1), lines
    else:
        assert run.returncode == 1, lines
        assert lines == [_name_hit(PROMPTS, prompts, NAME, root, NAME)], lines
