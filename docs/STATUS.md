# Status and handoff

**Read this first when you pick the project up on any machine.** It's the shared memory: where things stand, what's next, what we learned, and how Aarmen likes to work. Claude Code's own memory lives on one laptop only, so anything worth keeping goes here. Update it at the end of each session (Claude: do it as part of wrapping up).

*Last updated: 2026-10-14, Mac session.*

## Where things are
- **The repo is `github.com/aarmens702-hub/crivo`** (renamed from `analyst-agent` on 2026-10-14; the old URLs redirect). MIT. Not on PyPI yet.
- **Branches:** `dev` is the workspace and `main` is what the public sees, as of 2026-10-14 (the EDISON workflow: `/start-task`, `/ship`, `/promote`). Before that everything went straight to `main`.
- **The last code work was 2026-09-07** (wave 1.5, commit `5adec38`). 2026-10-14 was docs and process only: the README rebuild, the repo rename, the GitHub Action fixed to install from its own checkout, and this workflow.
- **Tests:** 1,045 passing, keyless and offline, about 70 s. CI runs ruff, pytest and the bench smoke on Linux and macOS for `dev`, `main` and PRs.
- **Bench, deterministic mode** (2026-09-07, 1,450 synthetic + 4 external datasets): detection micro-F1 0.731, repair F1 0.923 (where defined), survived verification 0.673. Full tables in `bench/RESULTS.md`.

## To do, in order
The plan of record is `specs/2026-09-06-master-plan.md`. Waves 1 to 5 make crivo correct and measurable, 6 to 13 make it capable, 14 makes it available.

| Wave | What | State |
|---|---|---|
| 0 | Autonomy mode (autonomous default, careful, report-only) | Done (`4fd76c6`) |
| 1 | Make the scorer honest | Done (`9f1d996`) |
| 1.5 | Fix the 32 regressions the remediation packets introduced | Done (`5adec38`) |
| 2 | Honesty and safety: gate bugs, receipts that can't fail, PII leaking into the HTML report, notebook card and reconcile report (15 items) | **Next** |
| 3 | The Proving Ground: corpus variety, not volume (29 shapes re-rolled 50 times is why F1 sits at 0.73); per-detector P/R/F1 | The most important wave |
| 4 | Detector honesty: silent caps, AUTO on ambiguous values (17 items) | After 3 |
| 5 | Detector accuracy: move F1 by fixing misses the corpus exposes | After 3 and 4 |
| 6 to 13 | Phase 7 detectors, severity tier, the statistics toolkit (wave 8, the analyst's brain), DuckDB scale, analytics, output polish, contracts and interop, latency | Not started |
| 14 | Ship: Windows and 3.13 CI, publish 0.1.0 to PyPI | Not started, Aarmen's call |

Open review findings: 36 of 56 were open on 2026-09-06 (`specs/2026-09-06-review-triage-and-fix-plan.md`). Waves 2 and 4 carry them.

Known bug, not yet filed: `python -m crivo` with `CRIVO_PROVIDER=openai` still demands `DEEPSEEK_API_KEY` (`src/crivo/__main__.py:123`), so the README's local-model example fails from the CLI.

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
