---
name: qa-pass
description: Full black-box QA pass on dev - run every case in docs/QA.md through the qa-tester subagent against a fresh install, report pass/fail and file failures as bug issues. For checkpoints (before a release, after a wave), not every promotion. Use when the user says QA dev, run QA, or full test pass. For a quick check before moving dev to main, use /promote instead.
---

# QA pass on dev

This is black-box testing: use crivo the way a person would, and judge it only against `docs/QA.md`. Don't read or edit crivo's code, and don't fix anything you find. File it instead.

1. **Get a dev install.**
   - `git switch dev && git pull` in the main checkout (stash nothing of anyone else's).
   - Make a fresh venv in the scratchpad and install the checkout into it, as `docs/QA.md`'s Setup section says. Never the repo's own `.venv`.
   - Ask whether a model key may be used for the `costs money` cases. If not, those cases are skipped, not failed.
2. **Check `docs/QA.md`.** If it's empty or has no case for the demo story, stop and offer to draft cases from `docs/PRD.md`.
3. **Run the cases** through the `qa-tester` subagent.
   - Give it the venv path, a scratch directory, and which cases to run (default: all).
   - It can't edit files, so the pass stays black-box.
   - Check its report: every case in `docs/QA.md` has a result, and every failure has evidence (the exact output or exit code, and a saved output file).
   - Re-run any case it missed, once.
4. **Report.**
   - A table of ID, result, and actual-when-failed.
   - Then the failures, ranked by how badly they'd hurt a new user following the README.
   - Say plainly which cases were skipped and why.
5. **File the bugs.** Offer to turn each failure into a GitHub issue:
   - `gh issue create --label bug`, plus `--label core` if the fix is plainly in a core file.
   - Body: case ID, steps, expected (from QA.md), actual, and the evidence path.
   - Leave it unassigned. Show the drafts before creating anything.
6. **Verdict.** Say whether `dev` is ready for `main`. If it is, suggest `/promote`. If not, list the blocking case IDs.
7. Remove the scratch venv and anything else this skill made.
