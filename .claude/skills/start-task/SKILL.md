---
name: start-task
description: Begin work on a GitHub issue as its orchestrator - claim it, branch off dev in a worktree, size it, then run the specialist subagents (scout, test-writer, builder, reviewer) in order until it's ready for /ship. Use when the user says start/pick up/work on issue N, or asks what to work on next.
argument-hint: "[issue number] [full]"
---

# Start a task (orchestrator)

The issue is an approved design, so don't brainstorm or write a spec. You are the orchestrator: you don't write the code yourself. You run the specialists in `.claude/agents/`, pass each one the previous one's output, and keep the user posted with one line per step.

## 1. Set up
1. **Pick the issue.**
   - If no number was given, list open unassigned issues with `gh issue list --search "no:assignee" --state open --label task` and `... --label bug`, and let the user choose.
   - Leave out any issue that has a "Claimed by" comment (check with `gh issue view <n> --comments`).
   - Suggest `bug` issues first, then the lowest-numbered `task` in the current stage of `specs/2026-10-14-the-plan.md`, following the wave order in that stage's WRAP spec (`docs/STATUS.md` says which stage).
2. **Read it.** Run `gh issue view <n> --comments`. If Goal, Files or Done-when is missing, or contradicts the docs, stop: tell the user what's unclear.
3. **Claim it,** before making the worktree.
   - If the issue is closed, or has a "Claimed by" comment from another session, stop and tell the user who has it.
   - Otherwise post `gh issue comment <n> --body "Claimed by: <machine> session, worktree .worktrees/<n>, branch <branch>, <date>"`. Ask the user once for the machine name if it isn't known.
   - Also run `gh issue edit <n> --add-assignee @me`.
4. **Branch.**
   - Never switch branches in the main checkout. It stays on `dev`.
   - Find the main checkout's root, which works from any subfolder or worktree: `root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")`.
   - Run `git -C "$root" fetch origin dev && git -C "$root" worktree add "$root/.worktrees/<n>" -b <first name>/<n>-<short-slug> origin/dev`. Take the first name from `git config user.name`, in lowercase (for `aarmens702-hub`, use `aarmen`).
   - Move this session into it: the EnterWorktree tool with `path: "$root/.worktrees/<n>"`, otherwise `cd` to that absolute path. Never call EnterWorktree with `name` or no arguments: that makes its own worktree off `origin/main`, the wrong tree and base.
   - Then `uv sync` in the worktree (it gets its own `.venv`).
   - Pass the worktree's absolute path to every specialist agent, and tell each to work only there.
   - Branches always come off `dev` and stay local: `/ship` pushes the finished work straight to `dev`, then removes the worktree.

## 2. Size it (say which path and why, in one line)
**Type first.** Read the issue's Type (AGENTS.md, "Work types"). `code` issues follow the paths below. For `behaviour`, `eval` or `experiment`, stop and tell the user: their tooling (the `/eval` skill, the eval-author agent, record and replay tests) lands before Stage 0.

**Full path: scout → test-writer → builder → reviewer.** Use it if **any** of these is true:
- The issue is labelled `core`, or would touch `loop.py`, `prompts.py`, `llm.py`, `card.py`, `skills.py`, `library.py`, `provenance.py` or `detect.py`.
- It changes logic: detection, fixing, verification, readers, the bench, the MCP server, the CLI, or anything in `docs/API-CONTRACT.md`.
- It creates a file or module, or touches more than 2 files.
- It's a `bug` issue. The test-writer first reproduces it.

**Lean path: builder → reviewer.** Use it only if **all** of these are true:
- 2 files or fewer.
- Docs, text or comments only.
- Not on the README quickstart path.

If the user said `full`, or says it at any point, use the full path. Never go lean unless every lean rule holds.

## 3. Run the specialists
Call each with the Agent tool, one at a time, and give it everything it needs, since it starts with no context:
1. **scout** (full path only). Pass the issue text and the worktree path. If its map has Blockers, stop and show them to the user, and don't guess.
2. **test-writer** (full path only). Pass the issue text, the change map and the worktree path. Check that it reports every new test failing for the right reason. If it can't make them fail properly, stop and show why.
3. **builder**. Pass the issue text and the worktree path, plus the change map and test report on the full path.
   - It has 2 attempts to get the tests passing.
   - If it reports "Stuck" or a test it thinks is wrong, stop and show the user. They decide.
4. **reviewer**. Pass the issue text, the branch name and the worktree path.
   - **SHIP IT:** move on to the end.
   - **FIX:** send the `[tests]` items to the **test-writer** first (the builder can't edit tests), then the rest to the builder, each **once**. Run the reviewer **once** more. If it still says FIX, stop and show the user both lists.
   - **Test notes** don't block. Pass them on to the user, and apply them only if they're cheap.

Every subagent reply is a report: check it before passing anything on. Never fake a step. If an agent failed or was skipped, say so.

## 4. End
Tell the user what was built, which tests prove it, the bench effect if any, and anything left for manual checking. If the reviewer listed core files, say plainly that `/ship` will stop for Aarmen's yes on the diff. Say that the reviewer already approved this diff, so `/ship` can skip its own review unless the code changes again.
