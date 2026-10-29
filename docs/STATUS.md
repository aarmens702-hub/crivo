# Status and handoff

**Read this first when you pick the project up on any machine.** It's the shared memory: where things stand, what's next, what we learned, and how Aarmen likes to work. Claude Code's own memory lives on one laptop only, so anything worth keeping goes here. Update it at the end of each session (Claude: do it as part of wrapping up).

*Last updated: 2026-10-29, Mac session. crivo is paused at Aarmen's request: no agents or paid runs are going.*

## Where things are
- **The repo is `github.com/aarmens702-hub/crivo`** (renamed from `analyst-agent` on 2026-10-14; the old URLs redirect). MIT. Not on PyPI yet.
- **Branches:** `dev` is the workspace and `main` is what the public sees (`/start-task`, `/ship`, `/promote`).
- **`main` is v0.2.0** (Stage A, promoted 2026-10-17). `dev` is 52 commits ahead of it: the eval tooling, the first Stage 0 rows and the fixes listed below. There has been no promotion since.
- **Tests:** 2,665 on `dev`, keyless and offline. CI is green on `dev` at `d90949e`.
- **Bench smoke on `dev`** (measured 2026-10-29 at `d90949e`, 31 cases): detect micro-F1 0.769; repair F1 0.562 over 8 of 31 (3 more are undefined by design); survived 0.717 over 15 of 31. Repair F1 reads lower than the 0.899 of 2026-10-17 because #86 scores a measured zero as 0 instead of leaving the case out. Since #256 and #263 the smoke also scores removals: rows removed recall 0.000 over the 5 cases that plant rows, columns removed recall 0.333 over the 3 that plant columns.
- **The published numbers** (README, `bench/RESULTS.md`) are still the 2026-09-07 full run: detection micro-F1 0.731, repair F1 0.923, survived 0.673. They predate the honest scorer.

## To do, in order
**The plan is `specs/2026-10-14-the-plan.md`**, the only sequencing authority. `specs/2026-10-14-plan-inventory.md` defines its ids, and each stage has a WRAP spec. The design of record for what gets built is `specs/2026-10-14-crivo-v2-design.md`.

| Stage | What | State |
|---|---|---|
| A | Stabilize what ships: broken paths, PII leaks, false receipts, false docs claims, SECURITY.md, tagged Action releases (#3, #6 to #43) | **Done:** on `main` as v0.2.0 (2026-10-17) |
| Eval tooling | Record and replay, the eval ledger, `/eval`, the eval-author and `guard_reads`, `check_locks` and `leak_scan` in CI, gates by work type (#64 to #83, `specs/2026-10-17-eval-tooling.md`) | **18 of 20 shipped.** Open: #78 (the A/A run ran but measured no floor; waits for Aarmen) and #79 (the first real-model cassettes) |
| 0 | The foundation: 0a honest scorer, loop 1 (autoresearch red-teams the scorer), 0b the referee, 0c detector honesty, 0d containment without Docker, versioned formats, config, cost caps (`specs/2026-10-17-stage-0-foundation.md`, #86 to #232) | **Started 2026-10-23.** Shipped: #86 and #96 from the stage list, plus fixes found on the way (#44 to #46, #56, #242 part 1, #253, #255 to #258, #263). 141 of #86 to #232 still open |
| 1 | A backed answer over a file, for people and agents: toolbox, DuckDB and text-to-SQL over files, charts and descriptive analysis, contracts, clarify, abstain, MCP on the new spec, design partners, model bake-off | |
| 2 | Two tracks in parallel. 2a the analyst toolkit: statistics, drivers, segments and cohorts, forecasting, anomalies, dashboards. 2b learning: System 1 as the loop's first filter, skills, the glossary, saved answers, `crivo verify`, the nightly skill loop | |
| 3 | Backed SQL and scale: databases, pushdown, SQL checks, relational and temporal checks | |
| 4 | Labelling at scale, only if stage 1 shows the gap | |
| 5 | The release: plugin, PyPI with trusted publishing, docs site, platform matrix | |

### Paused 2026-10-29: pick up here
**1. Finish what's built.** These live in local worktrees on the Mac only, so finish them or push the branches before switching machines.
- **#254**, the git-verb hook: `.worktrees/254`, branch `aarmen/254-git-verb-hook`, 2 commits. Built, its 515 hook tests pass, not reviewed. Next: the reviewer, then `/ship`.
- **#260**, emoji column names: `.worktrees/260`, branch `aarmen/260-astral-column-names`, 1 commit. Built, its 80 verify tests pass, not reviewed. Next: the reviewer, then `/ship`.
- **#78**, the A/A noise floor: `.worktrees/78`, branch `aarmen/78-ev15-aa-floor`, the register and result ledger commits (`check_locks` clean). The run stopped on its budget guard. Arm A ran 89 of 93 runs and arm B ran none, so there is no floor. Two causes: 15 cut-off calls were each charged a bound of about $1.5 to $1.7, because crivo sets no max_tokens and the bound falls back to the provider's 384k output limit; and the arms run one after the other, so a stop leaves the pair unequal. Measured spend was $6.64 at peak rates. Next: Aarmen drops it (recommended) or adopts it, then `bench.eval decide`, then `/ship`'s experiment step ships the ledger rows only.

**2. Aarmen's calls.**
- **#51** conflicts with S0-D11 (no model-written fix cell runs headless before 0d). Recommended: keep S0-D11 and add a deterministic exact-dedup fixer. Since #255, `dev` lets a headless clean apply a model-written dedup that verifies; `main` is unaffected. `.worktrees/51` exists but holds no work.
- **#268:** does an answer holding a number no cell printed read partly backed or not backed? The issue builds to partly backed. Confirm before it ships.
- **#78:** drop or adopt (above).

**3. Proposed, not filed.**
- Interleave the arms run by run in `bench/eval.py`, so a stop leaves the pair equal.
- Set max_tokens on crivo's model calls (`llm.py`, core), so an unread call's bound is small.
- Three cases in #78 end straight after the load, with no model call on any run. Find out why.
- An experiment on DeepSeek's thinking effort (see "What we've learned"). Changing it is a behaviour change in core `llm.py`.
- The PROV-O row that lands before #158.

**4. Filed, not started:** #259, #261, #262 (core), #264, #265 (core), #266, #267, #268 (core). Older and still open: #241, #251 (first find why #242's Linux `/proc` test skips on Ubuntu CI), #252.

**5. Then:** Stage 0 in the wave order of its spec. `dev` is 52 commits past `main`, so a `/qa-pass` and a `/promote` are due once #254 and #260 land.

**Decided 2026-10-24 and 2026-10-25:**
- **A verified fix runs without asking** (Aarmen, for #51's dedup). Prefer the more autonomous grade when the referee can verify the fix and the original file stays untouched.
- **Number grounding moves into Stage 0, 0b wave 4:** #267 (a keyless matcher for numbers in an answer that no recorded output holds) and #268 (the card verdict says so). The Stage 0 spec still lists answer grounding under Stage 1; update it when #267 starts.
- **PROV-O lineage names now**, before #158's version 1 has readers (comment on #158).
- **The 2026-10-23 research** is in `docs/research/2026-10-23-*`. Its open calls are in `docs/research/2026-10-23-four-deep-dives-summary.md`, whether the Error Drop Rate (#244) is published among them.

## What we've learned
- **The bench measures variance, not coverage.** Wave 1.5's regressions scored perfectly clean because the smoke corpus contains none of the shapes involved. A change that handles a new shape needs a corpus case, or the bench can't see it.
- **Refusing looks like rigour.** Teaching fixers to refuse rather than mangle was right, then the risk inverted: crivo began declining input it should repair, and the lower survival number read as caution. Pin the legitimate repair beside every refusal.
- **A held run isn't caution when the truth expects a repair.** Of #78's 18 runs that wrote no output, 9 were crivo rightly leaving a call to a person, which the bench scored as a fail (fixed by #257); 6 were detection gaps, so the model was never asked; 3 were an AUTO fix that failed its re-check every time.
- **A docstring is not a fix.** Several packets described a hole as closed while closing part of it. Only a test that proves the whole claim counts.
- **DeepSeek V4 thinks by default, at high effort.** In #78, calls averaged 8.7k output tokens, nearly all hidden thinking, and took 1 to 5 minutes each, so a case of 6 to 10 turns can't finish inside a 600 s cap. Thinking mode ignores temperature, so crivo's temperature 0 does nothing there and runs aren't deterministic. crivo sends neither an effort setting nor max_tokens. DeepSeek's peak hours are 01:00 to 04:00 and 06:00 to 10:00 UTC on weekdays.
- **Running agents in parallel:** keep about 6 to 8 going; with 8, a full suite takes about 8 minutes. Scouts have no shell, so paste the issue text into their prompt. A test-writer once put real values from an external dataset in a fixture, so reviewers check fixtures against `data/external`.
- **The verify-or-revert loop has no direct competitor.** Other "verified answer" schemes check inputs before generation, never outputs (landscape research, 2026-08-31).
- **Autonomy pays on the verifiable grades and harms on judgement calls.** The ceiling arm repaired fewer cells (250 vs 500) when allowed to decide person-grade findings (`specs/2026-09-05-autonomy-default-design.md`).

## How Aarmen likes to work
- **Aarmen decides** the plan, the architecture, the contract and the taxonomy. Core files are drafted as small reviewed diffs, never landed unattended.
- **Ask him less.** Make the small calls, record them on the issue, and tell him after. Bring the calls that are his as one short numbered list, each with a recommendation. Core diffs and paid spend still need his explicit yes, with a cap he names.
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
