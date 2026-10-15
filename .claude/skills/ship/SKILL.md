---
name: ship
description: Finish the current task - run checks, review, stop for Aarmen on core changes, commit, rebase onto the latest dev and push straight to dev, then close the issue. Use when the user says ship it, push this, or is done with a task.
---

# Ship the current task

`dev` is the workspace: shipping means pushing to it once the checks pass. No PR. Only `/promote` touches `main`.

1. **Branch check.**
   - On a local task branch (`<first name>/<issue#>-<slug>`): take the issue number from its name. It normally lives in its own worktree at `.worktrees/<n>`, made by `/start-task`, and this session is working there.
   - On `dev` itself: fine, but ask which issue this closes, if any.
   - On `main`: stop. Move the work onto `dev` first.
2. **Check.** This is the gate. From the worktree root:
   - `uv run ruff check --fix . && uv run ruff format .`, then `uv run ruff check .` must be clean.
   - `uv run pytest -q`. Check its exit status itself; never through `tail` or a `;` chain.
   - If anything under `src/crivo/` that detects, fixes or verifies changed (`detect.py`, `autoclean.py`, `verify.py`, `crosscol.py`, `checkup.py`), or anything under `bench/`: run `uv run python -m bench.run --smoke` and compare its summary line with the same command on `origin/dev`. A drop in any number needs a reason in the commit message, or it doesn't ship.
   - If the change is user-visible (README snippet, CLI output, a notebook card, an HTML report), run it once and look at the output.
   - Fix any failures this change caused. Never push red.
3. **Review.**
   - If `/start-task`'s reviewer already said SHIP IT for this exact diff, skip this step.
   - Otherwise, run the **reviewer** subagent with the issue text, the branch and the worktree path.
   - On FIX, fix the listed items, run the checks again, and run the reviewer once more. If it still says FIX, stop and show the user.
   - Remove debug prints, commented-out code and anything out of scope.
4. **The core gate.** Run `git diff --name-only origin/dev...HEAD` plus `git diff --name-only`. If any of `src/crivo/loop.py`, `prompts.py`, `llm.py`, `card.py`, `skills.py`, `library.py`, `provenance.py` or `detect.py` is in it:
   - Show Aarmen the diff of those files and the tradeoffs in two or three lines.
   - Wait for his explicit yes in this conversation. A yes for an earlier diff doesn't count for this one.
   - On no, stop. Leave the branch and worktree as they are.
5. **Commit.** Stage only this task's files by name, never `.env*` and never `git add -A`. Use a short imperative message in the repo's style (`fix: ...`, `feat: ...`, `docs: ...`), with a body that says why, ending with `Closes #<n>` when there's an issue. No Co-Authored-By trailer.
6. **Rebase and push to `dev`.**
   - Run `git fetch origin dev && git rebase origin/dev`.
   - On conflicts, keep both sides' intent, show the user what you chose, and re-run step 2's checks.
   - If a conflict is in a core file or is unclear, stop and ask.
   - Just before the push, re-read the issue: `gh issue view <n> --comments --json state,comments`. If it's already closed, or has a "Claimed by" or "Shipped to dev" comment from another session newer than ours, stop and show the user instead of pushing.
   - Then push: `git push origin HEAD:dev`. Never force-push.
   - If the push is rejected because `dev` moved, fetch, rebase, run step 2's checks and the issue re-check again, then retry once.
7. **Tidy up.**
   - On a task branch in a worktree (`.worktrees/<n>`, the normal case):
     - Find the main root first: `root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")`.
     - Leave the worktree: the ExitWorktree tool if the session entered it with EnterWorktree, otherwise `cd "$root"`.
     - Run `git -C "$root" worktree remove .worktrees/<n>`, then `git -C "$root" branch -d <task branch>`. Never leave a finished worktree behind.
     - Never switch branches in the main checkout. It stays on `dev`.
   - Worked directly on `dev` in the main checkout (the fallback): run `git pull`.
   - Always run `gh issue close <n> --comment "Shipped to dev in <sha>"`. `Closes #<n>` only closes it when the commit reaches `main`, and other sessions' claim checks look for this comment.
8. **Report.** Give the commit on `dev` and the bench line if it ran. CI runs on the push (`gh run list --branch dev -L 1`); say so, and if it goes red, fixing it comes first. It reaches `main` at the next `/promote`.
