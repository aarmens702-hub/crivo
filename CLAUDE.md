@AGENTS.md

## Claude Code specifics
- **A GitHub issue is an approved design.** Working an issue counts as bounded work: skip brainstorming and spec writing, restate the plan in 3 to 5 bullets, then implement. Use brainstorming only for architecture and planning work, and skip the rest of the superpowers chain (Aarmen's call: it costs tokens he doesn't value).
- **Project skills:**
  - `/start-task`: begin an issue.
  - `/ship`: finish it. Runs the checks, stops at the core gate when it applies, then pushes straight to `dev`.
  - `/promote`: test `dev` (the local checks plus a walk of the demo story), then move it to `main` once CI is green.
  - `/new-task`: write an issue.
  - `/demo-check`: walk the demo story on `main` the way a new user would.
  - `/crivo`: drive the crivo CLI on a data file (the product skill, not a workflow one).
- **QA:** `/qa-pass` is the full `docs/QA.md` run against `dev`, black-box, at checkpoints. It files failures as `bug` issues.
- **Route by work type first** (AGENTS.md, "Work types"). `code` issues take the paths below. `behaviour`, `eval` and `experiment` issues need tooling that lands before Stage 0 (the `/eval` skill, an eval-author agent that cannot read the prompts, record and replay tests); until it exists, `/start-task` stops and asks Aarmen.
- **`/start-task` is an orchestrator.** It sizes the issue, then runs the specialists in `.claude/agents/`:
  - **Full path** (logic, the contract, the core, bugs, more than 2 files): scout → test-writer → builder → reviewer.
  - **Lean path** (at most 2 files of docs or text): builder → reviewer.
- **Write limits are enforced, not trusted. Read limits are not enforced yet:** the bench rule (injector authors don't read `detect.py` or `autoclean.py`) lives in the agents' prompts only, so the reviewer checks it.
  - scout and reviewer can't edit files; qa-tester can't edit files either.
  - A hook keeps the test-writer inside test files (`tests/`, `test_*.py`, `conftest.py`), and keeps the builder out of them.
- **Other hooks:**
  - `.env` files are blocked for every agent.
  - Every edited `.py` file is formatted with ruff.
  - Claude can't finish while the test suite fails on uncommitted Python changes.
- **Subagents run on the strongest model.** Never downgrade an agent's model to save tokens (Aarmen's call).
- Look up library APIs with context7 instead of relying on memory.
- Every task gets its own git worktree, **inside the repo** at `.worktrees/<issue#>`; `/start-task` makes it (e.g. `git worktree add .worktrees/14 -b aarmen/14-slug origin/dev`). The main checkout stays on `dev`, and nobody edits in it. `.worktrees/` is git-ignored. Never create worktrees, copies or scratch files next to the repo or on the Desktop; temporary files go in your scratchpad or `/tmp`.
