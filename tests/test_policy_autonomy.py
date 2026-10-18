"""The autonomous default's standing policy factory (P7 autonomy Packet 2).

`default_autonomous_policies` mints the one ENFORCE record that lets an
autonomous session apply AUTO findings with a registered deterministic fixer
without showing a gate. The load-bearing test in this file is
`test_the_default_policy_cannot_silence_a_person_grade`: it is the whole
safety argument for autonomous mode. Autonomy is a silence decision about
AUTO-with-fixer findings, not a widening of what may be decided, and the
reason it cannot become one is structural, not a matter of which ids the
factory happens to list.

The file also pins where the three autonomy levels live (#31): in
crivo.policy, beside the approval code they configure.
"""

import json
import os
import subprocess
import sys

import pytest

from crivo.llm import KEY_ENV_VARS
from crivo.policy import default_autonomous_policies, evaluate
from crivo.readers.remote import READER_ENV_VARS

# Stand-in taxonomy and fixer registry. They arrive as parameters precisely so
# this module (and policy.py) needs neither crivo.detect nor crivo.autoclean.
TAXONOMY = frozenset({1, 2, 4, 6, 7, 14, 18, 19, 23})
FIXER_IDS = frozenset({1, 2, 4, 6, 7, 18, 19, 23})
TODAY = "2026-09-05"


@pytest.fixture(autouse=True)
def _quarantine_telemetry(monkeypatch):
    """A CRIVO_TELEMETRY path in the shell must not leak rows into a real file."""
    monkeypatch.delenv("CRIVO_TELEMETRY", raising=False)


def _finding(disease=6, grade="AUTO"):
    """A finding shaped exactly like crivo.detect._finding builds them."""
    return {
        "disease": disease,
        "slug": "whitespace-damage",
        "columns": ["name"],
        "evidence": "3/10 values carry an NBSP",
        "stats": {"values": 10},
        "grade": grade,
        "confidence": 0.9,
        "indicator": False,
    }


def test_the_factory_mints_one_enforce_record_over_the_fixer_ids():
    (record,) = default_autonomous_policies(TAXONOMY, FIXER_IDS)
    assert record.id == "autonomy-auto"
    assert record.disease_ids == tuple(sorted(FIXER_IDS))
    assert record.approver == "autonomy-default"
    assert record.mode == "ENFORCE"
    assert record.expires == "2099-01-01"


def test_an_auto_finding_of_a_listed_disease_batches_silently():
    policies = default_autonomous_policies(TAXONOMY, FIXER_IDS)
    decision = evaluate(_finding(disease=6), policies, today=TODAY)
    assert decision["batched"] is True
    assert decision["mode"] == "ENFORCE"
    assert decision["policy_id"] == "autonomy-auto"
    assert decision["denial"] is None


@pytest.mark.parametrize("grade", ["GATE", "HUMAN"])
@pytest.mark.parametrize("disease", sorted(FIXER_IDS))
def test_the_default_policy_cannot_silence_a_person_grade(grade, disease):
    """The safety argument for autonomous mode, pinned adversarially.

    Every disease the autonomous default lists is fed back in as a GATE and as
    a HUMAN finding, so the policy is maximally permissive about exactly this
    finding's disease. It must not matter: `evaluate` reads the grade before
    it reads any policy, so the denial is on "grade", never on "disease". A
    future edit that adds GATE-graded ids to the factory therefore still
    cannot enable GATE auto-apply.
    """
    policies = default_autonomous_policies(TAXONOMY, FIXER_IDS)
    (record,) = policies
    assert disease in record.disease_ids, "the policy really does list this disease"

    decision = evaluate(_finding(disease=disease, grade=grade), policies, today=TODAY)

    assert decision["batched"] is False
    assert decision["would_batch"] is False
    assert decision["policy_id"] is None
    assert decision["denial"]["condition"] == "grade"
    assert "person-grade findings never batch" in decision["denial"]["reason"]


def test_the_real_fixer_ids_all_admit_against_the_real_taxonomy():
    from crivo.autoclean import FIXERS
    from crivo.detect import SLUGS

    (record,) = default_autonomous_policies(set(SLUGS), FIXERS)
    assert record.disease_ids == tuple(sorted(FIXERS))


def test_admission_still_rejects_an_id_outside_the_taxonomy():
    with pytest.raises(ValueError, match="99"):
        default_autonomous_policies(TAXONOMY, {6, 99})


def test_the_factory_is_pure_and_hands_back_a_fresh_list_each_call():
    first = default_autonomous_policies(TAXONOMY, FIXER_IDS)
    second = default_autonomous_policies(TAXONOMY, FIXER_IDS)
    assert first == second
    assert first is not second
    first.clear()  # a caller mutating its own list must not poison the next
    assert len(default_autonomous_policies(TAXONOMY, FIXER_IDS)) == 1


# --- where the three levels live (#31) ----------------------------------------
#
# The levels moved out of crivo.governance, which no runtime code reads, into
# crivo.policy beside the approval code they configure, so #32 can delete the
# governance module without touching anything live.


def _policy_levels():
    """crivo.policy.AUTONOMY_LEVELS, or None while policy does not define it.

    Imported in the body, inside try, so a missing name fails a test on its
    assertion instead of erroring the whole file at collection."""
    try:
        from crivo.policy import AUTONOMY_LEVELS
    except ImportError:
        return None
    return AUTONOMY_LEVELS


def test_autonomy_levels_are_the_three_named_postures():
    """The setting spans the spectrum: decide everything verifiable, gate
    everything, decide nothing. It is named in crivo.policy, beside the
    approval code it configures (#31)."""
    assert _policy_levels() == ("autonomous", "careful", "report-only")


def test_governance_reexports_the_policy_tuple_until_it_is_deleted():
    """governance.py imports the levels back from crivo.policy, so the two
    names are one object, not two copies that can drift apart. #32 deletes
    this test together with the governance module."""
    from crivo import governance, policy

    assert governance.AUTONOMY_LEVELS is getattr(policy, "AUTONOMY_LEVELS", None)


def _run_fresh(code: str, cwd) -> subprocess.CompletedProcess:
    """`code` in a fresh interpreter with no provider key, reader override or
    telemetry path. A module-scoped caller runs before conftest's autouse
    quarantine, so the env is scrubbed here rather than trusted."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in KEY_ENV_VARS + READER_ENV_VARS + ("CRIVO_TELEMETRY",)
    }
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=120,
        check=False,
    )


def test_importing_the_levels_pulls_in_neither_governance_nor_a_core_module(
    tmp_path,
):
    """The CLI reads the levels before its keyless --diagnose path, so the
    import must stay light: no governance module (which #32 deletes) and none
    of the reserved core modules tests/test_import_isolation.py names."""
    from tests.test_import_isolation import RESERVED

    code = (
        "import json, sys\n"
        "from crivo.policy import AUTONOMY_LEVELS\n"
        f"watched = {('crivo.governance', *RESERVED)!r}\n"
        "print(json.dumps([m for m in watched if m in sys.modules]))\n"
    )
    proc = _run_fresh(code, tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout.splitlines()[-1]) == []


# The CLI and the loop must keep working once #32 deletes crivo.governance, so
# the tests below run them with that module blocked from import. The names are
# spelled out because parametrize needs them at collection, before any import
# can be tried; test_autonomy_levels_are_the_three_named_postures pins them to
# crivo.policy.
NAMED_LEVELS = ("autonomous", "careful", "report-only")


@pytest.fixture
def no_governance(monkeypatch):
    """crivo.governance as if #32 had deleted it: any import of it raises."""
    monkeypatch.setitem(sys.modules, "crivo.governance", None)


def _cli(monkeypatch, tmp_path, argv: list) -> int:
    """`crivo <argv>` in-process with no .env read, as an exit code whether
    main() returns it or argparse raises it."""
    import crivo.__main__ as entry

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(entry, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["crivo", *argv])
    try:
        return entry.main()
    except SystemExit as exc:
        return exc.code


def _orders_csv(tmp_path):
    """A small messy export: zero-padded ids, mixed date formats, an N/A and a
    -999 sentinel."""
    path = tmp_path / "orders.csv"
    path.write_text(
        "order_id,placed,amount\n"
        "007,2024-01-05,12.50\n"
        "012,05/02/2024,N/A\n"
        "031,2024-03-11,7.25\n"
        "044,,-999\n"
        "058,2024-03-19,18.00\n"
    )
    return path


@pytest.mark.parametrize("level", NAMED_LEVELS)
def test_each_level_parses_on_the_cli_with_governance_blocked(
    level, no_governance, tmp_path, monkeypatch
):
    argv = ["diagnose", str(_orders_csv(tmp_path)), "--autonomy", level]
    assert _cli(monkeypatch, tmp_path, [*argv, "--fail-on", "never"]) == 0


def test_a_mistyped_level_is_refused_on_the_cli_with_governance_blocked(
    no_governance, tmp_path, monkeypatch, capsys
):
    """The choices are closed: a typo exits 2 at the parser, not a fallback."""
    argv = ["diagnose", str(_orders_csv(tmp_path)), "--autonomy", "report-onlyy"]
    assert _cli(monkeypatch, tmp_path, argv) == 2
    assert "argument --autonomy: invalid choice" in capsys.readouterr().err


def test_the_help_lists_the_levels_with_governance_blocked(
    no_governance, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("COLUMNS", "200")  # one line per option, no wrap
    assert _cli(monkeypatch, tmp_path, ["--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "--autonomy {" + ",".join(NAMED_LEVELS) + "}" in out


# One child interpreter, shared by the loop tests below: governance blocked
# before crivo.loop is first imported, a kernel stand-in in place of the real
# client, and one Session per level plus one with a mistyped level. Its report
# is the last line it prints (Session prints its own startup lines first).
_LOOP_CHILD = """
import json, sys
sys.modules["crivo.governance"] = None
from crivo import loop, policy
from crivo.kernel.client import HelloInfo

class StandIn:
    def __init__(self, workspace_dir, transport_argv=None, data_dir=None):
        pass

    def start(self):
        return HelloInfo(1, "3.12.0", "7.3.0")

loop.KernelClient = StandIn

def build(level):
    return loop.Session(
        workspace="ws-" + level, data_dir=".", skills_dir="skills",
        preview=False, snapshots=False, autonomy=level,
    )

report = {"same_tuple": loop.AUTONOMY_LEVELS is policy.AUTONOMY_LEVELS}
report["levels"] = {}
for level in policy.AUTONOMY_LEVELS:
    s = build(level)
    report["levels"][level] = {
        "autonomy": s.autonomy, "policy_ids": [p.id for p in s.policies],
    }
try:
    build("report-onlyy")
    report["typo"] = None
except ValueError as exc:
    report["typo"] = str(exc)
print(json.dumps(report))
"""


@pytest.fixture(scope="module")
def loop_child(tmp_path_factory):
    return _run_fresh(_LOOP_CHILD, tmp_path_factory.mktemp("loop-child"))


def _loop_report(proc) -> dict:
    """The child's report; a child that died fails the test that reads it."""
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.splitlines()[-1])


def test_the_loop_reads_the_policy_tuple_with_governance_blocked(loop_child):
    assert _loop_report(loop_child)["same_tuple"] is True


@pytest.mark.parametrize("level", NAMED_LEVELS)
def test_each_level_builds_a_session_with_governance_blocked(level, loop_child):
    built = _loop_report(loop_child)["levels"]
    assert built.get(level, {}).get("autonomy") == level


@pytest.mark.parametrize("level", NAMED_LEVELS)
def test_only_autonomous_seeds_the_default_policy_with_governance_blocked(
    level, loop_child
):
    """A session given no policies of its own arms the autonomy-auto record at
    autonomous and nothing at careful or report-only."""
    built = _loop_report(loop_child)["levels"]
    expected = ["autonomy-auto"] if level == "autonomous" else []
    assert built.get(level, {}).get("policy_ids") == expected


def test_a_mistyped_level_is_refused_by_the_session_with_governance_blocked(
    loop_child,
):
    """Refused, not defaulted: a typo must not fall through to a posture."""
    refusal = _loop_report(loop_child)["typo"]
    assert refusal is not None, "Session built with autonomy='report-onlyy'"
    assert "report-onlyy" in refusal
