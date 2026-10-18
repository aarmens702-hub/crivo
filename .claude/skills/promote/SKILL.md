---
name: promote
description: Promote dev to main after a quick test - run the local checks on dev, walk the demo story, cut the release notes from changes/, then open a dev → main PR, merge it once CI is green, and tag the release. Use when the user says promote, push to main, release, or "is dev good to go to main".
---

# Promote dev → main

`main` is what the public sees: the README, the GitHub Action and `pip install git+...` all read it. This takes a few minutes: it's a quick "does the demo story still work", not a full QA pass. That's `/qa-pass`.

1. **Sync.** `git switch dev && git pull`.
   - **Look for an unfinished release.** Take the newest version heading in `CHANGELOG.md` (the first `## X.Y.Z` below `## Unreleased`) and ask the remote, not local tags: `git ls-remote --tags origin vX.Y.Z` and `gh release view vX.Y.Z`. If a piece is missing, an earlier promotion stopped partway; resume at the first missing piece:
     - **The tag is missing:** step 4 reuses X.Y.Z and step 5 tags it.
     - **The tag is there but the GitHub release isn't:** create it now with step 5's `gh release create` line, then carry on.
     - **Both are there but the README's "In CI" example doesn't show `crivo@vX.Y.Z`:** step 4 pins it.
   - If there's nothing on `dev` that isn't on `main` (`git log --oneline origin/main..dev` is empty): with the tag missing, go straight to step 5's tag substeps (no PR); with nothing to resume, say so and stop.
2. **Checks locally.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q` and `uv run python -m bench.run --smoke`. Stop on any failure.
3. **Walk the demo story** in `docs/PRD.md`, the way a new user would:
   - Install `dev` into a fresh venv in the scratchpad (`uv venv --python 3.12` then `uv pip install <repo root>`), not the repo's own `.venv`.
   - Run the README quickstart exactly as written, then `crivo diagnose` on the example with `--fail-on GATE` (exit 0) and `--fail-on AUTO` (exit 1).
   - Note anything broken, any traceback, and any output that doesn't match the README.
   - The analyst half costs money with a real key; walk it only if the user says so. Otherwise say it was skipped.
4. **Cut the release notes.** If the walk broke, skip this step: step 5 doesn't promote. Fragments are the `changes/<n>.<kind>.md` files; `changes/README.md` is not one, so never fold or delete it.
   - **Resuming an untagged X.Y.Z (step 1):** reuse that version and its notes; don't cut a new one.
     - With no fragments, skip the rest of this step.
     - If `changes/` also holds fragments, stop and ask Aarmen: never tag new changes under a version whose notes leave them out. On his yes, fold them into the `## X.Y.Z` section, grouped by kind, and delete them. Propose the version again under the rule below; if it changes, rename the heading and redo the version and README-pin bullets. Then run the checks, commit and push as below. On no, stop.
   - **Resuming only the README pin (step 1):** if fragments are waiting, the new release commit below pins the README. If not, pin it as below, run the checks, commit `README.md` as `docs: pin the Action example to vX.Y.Z`, and push to `dev` before opening the PR.
   - With no fragments and nothing to resume, skip the release: go to step 5, and skip its tag substeps.
   - If `changes/` holds fragments, propose the version to Aarmen: a patch, or a minor bump when any fragment is `removed`, or is a `changed` that breaks a flag, an exit code or a shape.
   - On his yes, move the fragment lines under a new `## X.Y.Z (<date>)` heading in `CHANGELOG.md`, below `## Unreleased`, grouped by kind, and delete the fragments.
   - Set `version` in `pyproject.toml`, then run `uv lock`.
   - Pin the README: change the "In CI" example to `uses: aarmens702-hub/crivo@vX.Y.Z`, so `main`'s README is right the moment the tag lands.
   - Run `uv run ruff check .` and `uv run pytest -q` again. Stop on any failure.
   - Commit on `dev` as `release: X.Y.Z`, staging `CHANGELOG.md`, the deleted fragments, `pyproject.toml`, `uv.lock` and `README.md` by name, and push to `dev` before opening the PR.
   - If any push to `dev` in this skill is rejected because `dev` moved, stop. Drop the unpushed commit with `git fetch origin dev && git reset --keep origin/dev` (this step makes it again), and start again from step 1, so the walk matches what gets promoted.
5. **Decide.**
   - **Demo story works:**
     - Record the sha to promote: `git rev-parse HEAD`, which is step 4's push, or step 1's pull when step 4 committed nothing.
     - Open `gh pr create --base main --head dev --title "Promote dev → main (<date>)" --body "<what's new since the last promotion, from git log origin/main..dev; the checks and the demo walk results>"`. After a restart, reuse the open dev → main PR instead of running `gh pr create` again.
     - Wait for CI on the PR: `gh pr checks <pr> --watch`. If it goes red, don't merge: show the failure.
     - Then merge it: `gh pr merge <pr> --merge --match-head-commit <that sha>`. This keeps `dev`'s commits as they are, and never deletes `dev`. If gh refuses because the head moved, treat it like a rejected push (step 4's last bullet): start again from step 1.
     - If step 4 cut a release or resumed an untagged one, tag it and publish it:
       - Skip this bullet when `git ls-remote --tags origin vX.Y.Z` already shows the tag. Otherwise the remote check has decided it's missing, so delete any stale local tag first (`git tag -d vX.Y.Z 2>/dev/null || true`), then run `git fetch origin main && git tag -a vX.Y.Z origin/main -m "crivo X.Y.Z"` and `git push origin vX.Y.Z`.
       - `gh release create vX.Y.Z --title "crivo X.Y.Z" --notes-file <that CHANGELOG section saved to the scratchpad>`
     - Then run `git switch dev && git pull`.
   - **Something broke:** don't promote. List what broke. Offer to file each as a `bug` issue.
6. **Report.** Say what went to `main`, with the PR link, or why not, and the release link if one was cut or resumed. If the README's bench block changed on `dev`, say the published numbers changed too.
