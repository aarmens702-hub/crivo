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
3. **By type.** Read the issue's Type (`gh issue view <n>`, under "## Type"; with no issue, ask the user).
   - **code:** nothing more.
   - **behaviour:** `uv run python -m bench.ledger check --issue <n>` must exit 0, or stop. It passes on an adopted decision measured on today's `prompts.py`, which `/eval` makes, or on a `shipped-unmeasured` one.
     - That check hashes `prompts.py` alone, so it misses any other change since the run, a reviewer's FIX among them. With an adopted row, `git diff --name-only <commit> -- . ':!bench/ledger.jsonl' ':!tests' ':!docs' ':!changes'` must print nothing, where `<commit>` is what the run measured: `uv run python -c "from bench import ledger; res = {r['row_id']: r for r in ledger.rows(kind='result')}; ad = [d for d in ledger.rows(kind='decision', issue=<n>) if d['decision'] == 'adopted']; print(res[ad[-1]['result']]['fingerprints']['commit'] if ad else 'no adopted decision')"`. If it lists a file, the row no longer measures what ships: run `/eval` again first. It flags README, `specs/` and `.claude/` edits too, forcing a re-run: conservative by design. Step 6 runs it again once committed.
     - A change no suite can measure yet ships only on Aarmen's yes in this conversation, as `uv run python -m bench.eval decide --shipped-unmeasured --issue <n> --note "<his call>, <date>"`, committed as `/eval` step 7 says (ED6). The commit message then says the change is unmeasured.
     - Step 5 stops for Aarmen on every behaviour issue, core file or not.
   - **experiment:** only `bench/ledger.jsonl` ships, with the rows `/eval` committed on the task branch. The branch's other changes are dropped, never committed to `dev`; once adopted, they come back as a new `code` or `behaviour` issue.
     - If `git log --oneline origin/dev..HEAD -- . ':!bench/ledger.jsonl'` lists a commit, ship from a fresh branch: `git switch -c <task branch>-rows origin/dev`, then `git cherry-pick` each commit `git log --reverse --format=%h origin/dev..<task branch> -- bench/ledger.jsonl` lists. Stop on one that touches another file. A pick that conflicts in the ledger takes step 7's rule (both sides' lines, `dev`'s first), then `git cherry-pick --continue`; when `dev` gained rows, the first pick does.
     - Steps 7 and 8 then push and delete that branch. Keep the task branch for Aarmen.
   - **eval:** as `code`, plus two things shown to the user. First, the `Check:` command from the eval-author's report, run again here, with its output and the report's Oracle, No-op and Cheats lines: the oracle passes, no-op and every cheat fail. Second, that the eval-author wrote the suite: each suite file in the diff is one its report lists under Written. If either fails, stop. If the report isn't in this session (after a restart), stop and ask; never guess its Written list.
4. **Review.**
   - If `/start-task`'s reviewer already said SHIP IT for this exact diff, skip this step.
   - Otherwise, run the **reviewer** subagent with the issue text, the branch and the worktree path.
   - On FIX, fix the listed items, run steps 2 and 3 again, and run the reviewer once more. If it still says FIX, stop and show the user.
   - Remove debug prints, commented-out code and anything out of scope.
5. **The core gate.** Run `git diff --name-only origin/dev...HEAD` plus `git diff --name-only`. If any of `src/crivo/loop.py`, `prompts.py`, `llm.py`, `card.py`, `skills.py`, `library.py`, `provenance.py` or `detect.py` is in it, or the issue is `behaviour`:
   - Show Aarmen the diff of those files and the tradeoffs in two or three lines. On a behaviour issue, show the whole diff and its ledger rows (`uv run python -m bench.ledger show --issue <n>`: the result and decision row ids).
   - Wait for his explicit yes in this conversation. A yes for an earlier diff doesn't count for this one.
   - On no, stop. Leave the branch and worktree as they are.
6. **Commit.** If the change is user-visible (a CLI flag, an exit code, an output shape, a report, the README), write `changes/<n>.<kind>.md` with one line and stage it with the task's files. Stage only this task's files by name, never `.env*` and never `git add -A`. Use a short imperative message in the repo's style (`fix: ...`, `feat: ...`, `docs: ...`), with a body that says why, ending with `Closes #<n>` when there's an issue. No Co-Authored-By trailer.
   - On a behaviour issue with an adopted row, run step 3's post-run diff again as `git diff --name-only <commit> HEAD -- …`, with the same exclusions. It checks what ships, new files included, and must print nothing.
7. **Rebase and push to `dev`.**
   - Run `git fetch origin dev`.
   - **Fingerprint check,** on a behaviour issue with an adopted row, before rebasing: `git diff --name-only HEAD...origin/dev -- $(uv run python -c "from bench import ledger; print(*ledger.PROMPT_FILES, *ledger.REFEREE_FILES, *ledger.SCORER_FILES)")`, the prompt, referee and scorer files the ledger hashes. If it lists one, the row no longer matches the code that would land, and `check_locks` fails its decision line once rebased. Stop and show Aarmen: re-measuring means taking the unpushed decision commit off the branch and running `/eval` again on the rebased code.
   - Run `git rebase origin/dev`.
   - On conflicts, keep both sides' intent, show the user what you chose, and re-run step 2's checks.
   - A conflict in `bench/ledger.jsonl` keeps both sides' new lines, `dev`'s first (the side a rebase marks HEAD), then this branch's. Never edit or drop a line.
   - If a conflict is in a core file or is unclear, stop and ask.
   - Just before the push, re-read the issue: `gh issue view <n> --comments --json state,comments`. If it's already closed, or has a "Claimed by" or "Shipped to dev" comment from another session newer than ours, stop and show the user instead of pushing.
   - Then, on every type, run `uv run python scripts/check_locks.py` and stop unless it exits 0. It reads committed history, so it runs after the commit and the rebase, and a violation that reaches `dev` can't be undone.
   - Then push: `git push origin HEAD:dev`. Never force-push.
   - If the push is rejected because `dev` moved, fetch, then run the fingerprint check, the rebase, step 2's checks, the issue re-check and `check_locks` again, then retry once.
8. **Tidy up.**
   - On a task branch in a worktree (`.worktrees/<n>`, the normal case):
     - Find the main root first: `root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")`.
     - Leave the worktree: the ExitWorktree tool if the session entered it with EnterWorktree, otherwise `cd "$root"`.
     - Run `git -C "$root" worktree remove .worktrees/<n>`, then `git -C "$root" branch -d <task branch>`. Never leave a finished worktree behind.
     - Never switch branches in the main checkout. It stays on `dev`.
   - Worked directly on `dev` in the main checkout (the fallback): run `git pull`.
   - Always run `gh issue close <n> --comment "Shipped to dev in <sha>"`. `Closes #<n>` only closes it when the commit reaches `main`, and other sessions' claim checks look for this comment.
9. **Report.** Give the commit on `dev` and the bench line if it ran. On a behaviour issue, give the ledger row it shipped on, or say it shipped unmeasured. CI runs on the push (`gh run list --branch dev -L 1`); say so, and if it goes red, fixing it comes first. It reaches `main` at the next `/promote`.
