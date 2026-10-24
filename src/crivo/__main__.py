"""Entry point: wires the hand-written core (loop.Session) to the REPL driver."""

import argparse
import os
import sys

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    # import-light and keyless: crivo.policy pulls in the standard library
    # only, so --diagnose still costs no model and no key
    from crivo.policy import AUTONOMY_LEVELS

    parser = argparse.ArgumentParser(prog="crivo")
    parser.add_argument(
        "--auto-run",
        action="store_true",
        help="run the analyst's own query cells without asking (dev only); fix "
        "gates, plans and skill admissions still wait for a person",
    )
    parser.add_argument(
        "--workspace", default="workspace", help="session workspace directory"
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="read-only data mount for the --docker kernel (ignored otherwise)",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="run the kernel in the net-none container (default: subprocess)",
    )
    parser.add_argument(
        "--resume",
        metavar="SESSION",
        help="resume an earlier session by id (e.g. s16): datasets reloaded, "
        "fixes restored from the snapshot, /why chain intact",
    )
    # `diagnose` deliberately sits before the API-key check: it runs the
    # detection engine in-process with no model and no kernel, so needing a
    # paid credential to be told a CSV holds "N/A" would be the barrier it
    # exists to remove.
    parser.add_argument(
        "--diagnose",
        metavar="FILE",
        help="report what is wrong with a file and exit; no model, no API key",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--fail-on",
        choices=["AUTO", "GATE", "HUMAN", "never"],
        default="GATE",
        help="diagnose as a linter: exit 1 when any finding carries this grade "
        "or one needing MORE human judgment (ordered AUTO < GATE < HUMAN by "
        "judgment required — the default GATE means 'fail me when something "
        "needs a person'); 'never' always exits 0 after reporting. Unreadable "
        "files exit 2, like bad arguments.",
    )
    parser.add_argument(
        "--clean",
        metavar="FILE",
        help="headless one-shot clean: AUTO fixes run, judgement calls are deferred",
    )
    parser.add_argument("--name", help="variable name for the loaded file (clean mode)")
    parser.add_argument(
        "--autonomy",
        choices=list(AUTONOMY_LEVELS),
        default="autonomous",
        help="how much crivo decides on its own while cleaning. 'autonomous' "
        "(the default) applies AUTO-grade findings that have a registered "
        "deterministic fixer without asking, re-checking each one and "
        "reverting it if the check fails; 'careful' asks before those and "
        "before every model-authored fix; 'report-only' diagnoses and applies "
        "nothing. One exception at the first two levels: a proven library "
        "skill fixes an AUTO finding with no gate shown, and only report-only "
        "stops it. A judgement call waits for a person at every level, and no "
        "level admits a skill. The level governs the clean flows, /clean and "
        "the family harmonize; a QUERY turn still runs the cell you approve "
        "at its gate, whatever that cell does.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        metavar="FILE",
        help="the file for `crivo diagnose FILE` and `crivo clean FILE`",
    )
    # the subcommand names the mode and FILE is a positional, so options may
    # sit before or after it and `crivo diagnose --help` prints the help
    mode = sys.argv[1] if sys.argv[1:2] in (["diagnose"], ["clean"]) else None
    if mode:
        parser.prog = f"crivo {mode}"
    args = parser.parse_args(sys.argv[2:] if mode else sys.argv[1:])
    if mode == "diagnose":
        args.diagnose = args.diagnose or args.file
    elif mode == "clean":
        args.clean = args.clean or args.file
    # the mode's own FILE only, so the other mode's flag is refused: the
    # diagnose branch runs first, and `crivo clean F --diagnose G` diagnosed
    # G and never cleaned F (#46); `crivo clean --diagnose F` is refused too
    other = {"diagnose": "clean", "clean": "diagnose"}.get(mode)
    if other and getattr(args, other):
        parser.error(f"crivo {mode} does not take --{other}; run `crivo {other} FILE`")
    if mode and not getattr(args, mode):
        parser.error(f"crivo {mode} needs a FILE")
    if not mode and args.file:
        parser.error("unexpected FILE; did you mean `crivo diagnose FILE`?")

    if args.diagnose:
        import json as _json

        from crivo import checkup

        try:
            if args.json:
                payload = checkup.report(args.diagnose, as_json=True)
                print(payload)
                findings = _json.loads(payload)["findings"]
            else:
                # styled for a terminal; rich degrades to plain text off a TTY
                frame = checkup.load(args.diagnose)
                result = checkup.detect_all(frame, os.path.basename(args.diagnose))
                checkup.render_console(args.diagnose, frame, result)
                findings = result["findings"]
        except (OSError, ValueError) as exc:
            print(f"could not read {args.diagnose}: {exc}")
            return 2  # could-not-run, like argparse's own bad-argument exit
        # linter semantics: exit 1 when a finding sits at/above the threshold
        # on the judgment ladder; an unknown grade counts as maximally human
        if args.fail_on == "never":
            return 0
        judgment = {"AUTO": 0, "GATE": 1, "HUMAN": 2}
        threshold = judgment[args.fail_on]
        return (
            1 if any(judgment.get(f["grade"], 2) >= threshold for f in findings) else 0
        )

    # import-light: crivo.query imports only os at module level
    from crivo.query import provider_problem

    problem = provider_problem()
    if problem:
        print(f"{problem}. Put it in .env or export it.")
        return 1

    from crivo.loop import Session

    if args.clean:
        # the orchestration surface: chatter to stderr, one JSON object (or a
        # short text summary) to stdout, no prompts anywhere
        import contextlib
        import json as _json

        from crivo.repl import run_clean_once

        with contextlib.redirect_stdout(sys.stderr):
            session = Session(
                workspace=args.workspace,
                data_dir=args.data_dir,
                docker=args.docker,
                preview=False,  # headless: nobody reads a preview
                autonomy=args.autonomy,
            )
            try:
                summary = run_clean_once(session, args.clean, name=args.name)
            finally:
                session.close()
        if args.json:
            print(_json.dumps(summary))
        else:
            for text in summary.get("notices", []):
                print(text)
            fixes = summary.get("fixes", [])
            done = sum(1 for f in fixes if f["status"] == "fixed")
            print(f"{args.clean}: {done}/{len(fixes)} findings fixed")
            for title in summary.get("needs_human", []):
                print(f"  needs a human: {title}")
            if summary.get("report"):
                print(f"  report: {summary['report']}")
        return 0 if not summary.get("error") else 1

    from crivo.repl import run_repl

    session = Session(
        workspace=args.workspace,
        data_dir=args.data_dir,
        docker=args.docker,
        # the clean gates a person still answers under --auto-run need their
        # preview
        preview=True,
        resume=args.resume,
        autonomy=args.autonomy,
    )
    run_repl(session, auto_run=args.auto_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
