# Status and handoff

**Read this first when you pick the project up on any machine.** It's the shared memory: where things stand, what's next, what we learned, and how Aarmen likes to work. Claude Code's own memory lives on one laptop only, so anything worth keeping goes here. Update it at the end of each session (Claude: do it as part of wrapping up).

*Last updated: 2026-10-17, Mac session.*

## Where things are
- **The repo is `github.com/aarmens702-hub/crivo`** (renamed from `analyst-agent` on 2026-10-14; the old URLs redirect). MIT. Not on PyPI yet.
- **Branches:** `dev` is the workspace and `main` is what the public sees, as of 2026-10-14 (the EDISON workflow: `/start-task`, `/ship`, `/promote`). Before that everything went straight to `main`.
- **The last code work was 2026-09-07** (wave 1.5, commit `5adec38`). 2026-10-14 was docs and process only: the README rebuild, the repo rename, the GitHub Action fixed to install from its own checkout, and this workflow.
- **2026-10-17:** a five-reviewer code review of `dev` found Stage A larger than planned (a fresh install cannot start the analyst; the MCP server cannot start on mcp 1.x; every Claude call fails on current models; `crivo diagnose` calls a JSON file clean; PII leaks through four shareable outputs). Stage A is filed as issues #6 to #43 plus #3 (`specs/2026-10-17-stage-a-stabilize.md`). Work types for agentic work landed (AGENTS.md, "Work types").
- **Tests:** 1,045 passing, keyless and offline, about 70 s. CI runs ruff, pytest and the bench smoke on Linux and macOS for `dev`, `main` and PRs.
- **Bench, deterministic mode** (2026-09-07, 1,450 synthetic + 4 external datasets): detection micro-F1 0.731, repair F1 0.923 (where defined), survived verification 0.673. Full tables in `bench/RESULTS.md`.

## To do, in order
**The plan is `specs/2026-10-14-the-plan.md`**. Aarmen started Stage A on 2026-10-17 and accepted every Stage A decision (D2: `notices` always present; D3: remove the governance file). It supersedes every earlier roadmap and maps every old item, every open defect (54 defects, 7 hardening items, defined in `specs/2026-10-14-plan-inventory.md`) and every finding of four completeness audits to a stage. The design of record for what gets built is `specs/2026-10-14-crivo-v2-design.md`.

| Stage | What | State |
|---|---|---|
| A | Stabilize what ships: broken paths (httpx, key gating, the Claude API), PII leaks, false receipts, false docs claims, SECURITY.md, tagged Action releases. 38 issues, #6 to #43 plus #3, in three waves | **In progress** (wave 1 started 2026-10-17) |
| 0 | The foundation: 0a honest scorer (repair F1 is really 0.596), loop 1 (autoresearch red-teams the scorer), 0b the referee (closes the reproduced bypass), 0c detector honesty, 0d containment without Docker, versioned formats, config, cost caps | After A |
| 1 | A backed answer over a file, for people and agents: toolbox, DuckDB and text-to-SQL over files, charts and descriptive analysis, contracts, clarify, abstain, MCP on the new spec, design partners, model bake-off | |
| 2 | Two tracks in parallel. 2a the analyst toolkit: statistics, drivers, segments and cohorts, forecasting, anomalies, dashboards. 2b learning: System 1 as the loop's first filter, skills, the glossary, saved answers, `crivo verify`, the nightly skill loop | |
| 3 | Backed SQL and scale: databases, pushdown, SQL checks, relational and temporal checks | |
| 4 | Labelling at scale, only if stage 1 shows the gap | |
| 5 | The release: plugin, PyPI with trusted publishing, docs site, platform matrix | |

25 owner decisions are listed in the plan with the stage each is needed by.

## What we've learned
- **The bench measures variance, not coverage.** Wave 1.5's regressions scored perfectly clean because the smoke corpus contains none of the shapes involved. A change that handles a new shape needs a corpus case, or the bench can't see it.
- **Refusing looks like rigour.** Teaching fixers to refuse rather than mangle was right, then the risk inverted: crivo began declining input it should repair, and the lower survival number read as caution. Pin the legitimate repair beside every refusal.
- **A docstring is not a fix.** Several packets described a hole as closed while closing part of it. Only a test that proves the whole claim counts.
- **The verify-or-revert loop has no direct competitor.** Other "verified answer" schemes check inputs before generation, never outputs (landscape research, 2026-08-31).
- **Autonomy pays on the verifiable grades and harms on judgement calls.** The ceiling arm repaired fewer cells (250 vs 500) when allowed to decide person-grade findings (`specs/2026-09-05-autonomy-default-design.md`).

## How Aarmen likes to work
- **Aarmen decides** the plan, the architecture, the contract and the taxonomy. Core files are drafted as small reviewed diffs, never landed unattended.
- **Lean process.** Brainstorm for design approval on architectural work, then build. No separate plan documents unless he asks; the issue or WRAP spec is the design.
- **Strong models for subagents.** Never downgrade an agent's model to save tokens.
- **Honest status.** Say what ran, what passed and what was skipped. Never claim a fix verified without running it.
- **Design:** hand-made, not AI-generated. No em-dashes, no hype words, flat over gradients, and no fake terminal-window graphics; a real code block or a real screenshot does the work.
- **No Docker on his Mac** (not enough RAM). Container tests are opt-in only.

## Setting up a new laptop
1. Clone `github.com/aarmens702-hub/crivo` with the personal GitHub account `aarmens702-hub`, then `git switch dev`.
2. Install [uv](https://docs.astral.sh/uv/), then `uv sync`.
3. For the analyst half, create `.env` from `.env.example` and fill in a key by hand (`DEEPSEEK_API_KEY`, or `CRIVO_PROVIDER=claude` with `ANTHROPIC_API_KEY`). Never commit it; agents are blocked from `.env` files. The library half and the whole test suite need no key.
4. Checks: `uv run ruff check .`, `uv run pytest -q`, `uv run python -m bench.run --smoke`.
5. Claude Code: the project's skills, agents and hooks come with the repo (`.claude/`). Work happens in worktrees at `.worktrees/<issue#>`; those are local only, so push before switching machines.
