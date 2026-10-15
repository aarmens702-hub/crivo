---
name: promote
description: Promote dev to main after a quick test - run the local checks on dev, walk the demo story, then open a dev → main PR and merge it once CI is green. Use when the user says promote, push to main, release, or "is dev good to go to main".
---

# Promote dev → main

`main` is what the public sees: the README, the GitHub Action and `pip install git+...` all read it. This takes a few minutes: it's a quick "does the demo story still work", not a full QA pass. That's `/qa-pass`.

1. **Sync.** `git switch dev && git pull`. If there's nothing on `dev` that isn't on `main` (`git log --oneline origin/main..dev` is empty), say so and stop.
2. **Checks locally.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q` and `uv run python -m bench.run --smoke`. Stop on any failure.
3. **Walk the demo story** in `docs/PRD.md`, the way a new user would:
   - Install `dev` into a fresh venv in the scratchpad (`uv venv --python 3.12` then `uv pip install <repo root>`), not the repo's own `.venv`.
   - Run the README quickstart exactly as written, then `crivo diagnose` on the example with `--fail-on GATE` (exit 0) and `--fail-on AUTO` (exit 1).
   - Note anything broken, any traceback, and any output that doesn't match the README.
   - The analyst half costs money with a real key; walk it only if the user says so. Otherwise say it was skipped.
4. **Decide.**
   - **Demo story works:**
     - Open `gh pr create --base main --head dev --title "Promote dev → main (<date>)" --body "<what's new since the last promotion, from git log origin/main..dev; the checks and the demo walk results>"`.
     - Wait for CI on the PR: `gh pr checks <pr> --watch`. If it goes red, don't merge: show the failure.
     - Then merge it: `gh pr merge <pr> --merge`. This keeps `dev`'s commits as they are, and never deletes `dev`.
     - Then run `git switch dev && git pull`.
   - **Something broke:** don't promote. List what broke. Offer to file each as a `bug` issue.
5. **Report.** Say what went to `main`, with the PR link, or why not. If the README's bench block changed on `dev`, say the published numbers changed too.
