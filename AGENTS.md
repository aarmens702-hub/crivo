# crivo

We win on **trust**: every fix and every answer crivo keeps has been re-checked, and every number we publish was measured. A fix that cannot prove itself is reverted, a number that was not measured is not claimed. Everything below serves that.

## Team
- **Aarmen** (`@aarmens702-hub`): owner.
  - Decides the plan, the architecture, the contracts, the disease taxonomy and its grades.
  - Reviews every change to the core (below) before it lands.
  - Runs `/promote` and `/qa-pass`.
- **Agents** work one GitHub issue at a time through `/start-task` and `/ship`.

If you are an agent: your job is the issue in front of you, nothing more. When the issue is unclear or seems wrong, stop and tell Aarmen. Don't guess at architecture.

## Deciding: Aarmen decides
- **Aarmen decides** code direction, architecture, `docs/API-CONTRACT.md`, dependencies, config, the plan, which findings get which grade, and what counts as a disease. Say what changed in the commit.
- **The core is reviewed, not delegated:** `src/crivo/loop.py`, `prompts.py`, `llm.py`, `card.py`, `skills.py`, `library.py`, `provenance.py` and `detect.py`. An agent may draft a change to one of them on its branch, as a small diff with the tradeoffs stated, but `/ship` stops and shows Aarmen the diff. Nothing in the core reaches `dev` without his explicit yes. Issues that touch the core carry the `core` label.
- Write big calls under "Key decisions" in `docs/ARCHITECTURE.md` so they aren't re-argued. A multi-day feature gets a short WRAP spec in `specs/` first (What, Requirements, Acceptance criteria, Priority).

## Work types: behaviour is measured, not tested
crivo is an agent, so a green test suite proves the code, not what the model does: a prompt rewrite passes CI unchanged. Every issue has a type, and the type sets what "done" means.

| Type | Covers | Done when |
|---|---|---|
| `code` | The library, detectors, fixers, the referee, harness plumbing, the CLI and MCP | A failing test goes green, plus a bench line if detection or repair moved. |
| `behaviour` | What the model does: prompts, turn structure, tool descriptions the model reads, model and effort defaults | The harness change is tested on recorded model replies, and a pre-registered eval on the dev split (3 runs or more) meets its rule; the false-backed rate never rises. Aarmen sees the diff and the result. |
| `eval` | Trap cases, graders, injectors, attacks | The oracle passes, no-op and cheating strategies fail, and the author never read the prompts, the loop or the referee. |
| `experiment` | Bake-offs, loop runs, spikes | The hypothesis and decision rule are on the issue before the first paid call. The result is recorded, then adopted (as a new `code` or `behaviour` issue) or dropped. |

- Until the eval tooling lands (before Stage 0), say plainly when a behaviour change is unmeasured. Never call it verified.
- Never quote eval or trap cases in an issue, a prompt or a skill. Name the suite.

## Branches: dev is the workspace, main is tested
- **`dev`** is the workspace.
  - Work on a local branch off `dev`, in its own worktree at `.worktrees/<n>` (`/start-task` makes both). The main checkout stays on `dev`.
  - `/ship` runs the checks, rebases onto the latest `dev`, and pushes straight to `dev`. No PR.
  - CI (`.github/workflows/ci.yml`: ruff, pytest and the bench smoke on Linux and macOS) runs on every push to `dev`. `/ship`'s local checks are still the gate, so never push without them. If `dev` breaks, whoever broke it fixes it first.
- **`main`** is tested and is what the public sees: the README, the GitHub Action (`uses: aarmens702-hub/crivo@vX.Y.Z`, a release tag on `main`) and `pip install git+...` all read it.
  - `/promote`: the local checks on `dev`, a walk of the demo story, then a `dev → main` PR merged once CI is green on it.
  - Nothing reaches `main` any other way.
- **`/qa-pass`** runs all of `docs/QA.md` black-box. It's for checkpoints (before a release, after a big wave), not every promotion. It files `bug` issues.

## Commands
Run from the repo root (or the worktree root).

| Do | Command |
|---|---|
| Install | `uv sync` |
| One test | `uv run pytest tests/test_x.py::test_name -q` |
| Unit and integration tests | `uv run pytest -q` (about 1,050 tests, about 70 s; keyless and offline) |
| Lint and format | `uv run ruff check --fix . && uv run ruff format .` |
| Bench smoke | `uv run python -m bench.run --smoke` (what CI runs) |
| Full bench | `uv run python -m bench.run --full` (the published numbers; `--write-readme` refreshes the README block) |
| Diagnose a file | `uv run crivo diagnose <file>` (keyless) |
| Run the analyst | `uv run python -m crivo` (needs a model key in `.env`) |
| MCP server | `uv run crivo-mcp` |
| Container tests | `uv run pytest -m docker`: opt in, and **never on Aarmen's Mac** (not enough RAM) |

## Docs (read the one you need, when you need it)
- `docs/STATUS.md`: **read first when you pick the project up**, on any machine. Where things stand, the to-do list in order, what we've learned, how Aarmen likes to work, and how to set up a new laptop. Update it at the end of a session.
- `docs/PRD.md`: what crivo is, who it's for, and the demo story. Read before any user-facing work.
- `docs/ARCHITECTURE.md`: modules, data flow, **who works where**, and key decisions. Read before creating a file or module.
- `docs/API-CONTRACT.md`: the public API, finding and summary shapes, CLI flags and exit codes, MCP tools, session events, env vars. **Read before writing code that calls, or is called by, another module.** Build against it exactly.
- `docs/QA.md`: the black-box cases `/qa-pass` runs, with the expected result of each.
- `docs/what-this-is.md`: the long version of why crivo is built this way.
- `specs/2026-10-14-the-plan.md`: the plan, stage by stage, and the only sequencing authority. `specs/2026-10-14-plan-inventory.md` defines its ids. Each stage has a WRAP spec (Stage A: `specs/2026-10-17-stage-a-stabilize.md`). Other `specs/` files are the design of record for their items.
- `bench/RESULTS.md`: the full benchmark tables.
- The original brief: `~/Desktop/mailo/coop-project/crivo-brief.md` and `crivo-build-research.md` (on Aarmen's Mac only): stack patterns, the disease taxonomy, datasets.

## Task loop (every task)
1. Start from an issue: `/start-task <number>`. No issue means no work, so write one with `/new-task`.
2. One issue, one local branch off `dev` in its own worktree at `.worktrees/<n>` (the main checkout stays on `dev`), one small change. Keep it under about 300 changed lines, and split the issue if it's bigger. `/start-task` runs the issue through the specialist agents (see CLAUDE.md).
3. Verify: run the tests. For anything a user sees (CLI output, a notebook card, an HTML report), run it and look at it.
4. Finish with `/ship`. It runs the checks, rebases onto `dev`, pushes to `dev`, and closes the issue.

## Code rules
- **Execution beats self-report.** Nothing works until pytest or an assertion says so. Never claim a fix is verified without running it.
- **No agent frameworks.** Raw API calls and `jupyter_client`. If glue feels missing, write the 20 lines.
- **Match the existing idiom.** Plain functions over classes unless state genuinely demands it.
- **No raw dataset rows** in any prompt, log, finding, receipt or shareable output. Schema, stats and truncated samples only.
- **`data/` originals are immutable.** Transforms write copies with lineage.
- **The library half stays keyless and import-light:** `import crivo` does no network, subprocess or Docker work.
- **Tests are keyless and offline.** `tests/conftest.py` quarantines provider credentials. Use the fake providers and tmp files; never a real key or the network.
- **The bench grades the code, so it can't be written from the code.** Authors of corruption injectors (`bench/corrupt.py`, `bench/bases.py`) must not read `src/crivo/detect.py` or `src/crivo/autoclean.py`. Plant what the taxonomy says a disease is. The scorer side may read anything.
- **The instrument comes before the capability it measures.** A change meant to move detection or repair shows its bench effect in the commit. A new detector or fixer ships with corpus cases that exercise it.
- **User-visible changes get a changelog fragment** (`changes/<issue#>.<kind>.md`). Regression tests for a bug open their docstring with `Regression for #<n>.`

## Boundaries
**Always**
- Stay within the files the issue lists.
- Build against `docs/API-CONTRACT.md`.
- Pull `dev` before starting and before shipping.

**Ask first**
- Aarmen, on anything the issue lists as out of scope, and on any change to the core files.

**Never**
- Push to `main` directly. It only changes through `/promote`.
- Push to `dev` without passing the checks. Use `/ship`.
- Force-push or rewrite history on `dev` or `main`.
- Commit, stash, reset or push from a specialist agent. The orchestrating session owns git.
- Read, print or commit secrets. Keys live in `.env`, a person edits it, and `.env.example` lists the names. A hook blocks agents from `.env` files.
- Run Docker on Aarmen's Mac.
- Leave `dev` red. Fix it, revert your push, or mark the issue `blocked` and say why.
- Silently change an interface. Propose it on the issue instead.

## Merging
- **Into `dev`:** `/ship` pushes once lint, the test suite and (when detection, fixing or the bench changed) the bench smoke pass, and the core gate is cleared.
- **Into `main`:** only `/promote`. It merges its own PR once the local checks pass, the demo story works and CI is green.

## Gotchas
<!-- Add one line each time an agent makes the same mistake twice. Say what to do instead. -->
- **`ruff check --fix` strips an unused import.** Add an import and its first use in the same edit. The edit hook only formats; `/ship` runs the lint.
- **Never mask a pytest exit code** with `;` or `| tail` in a verify chain. Check the exit status itself.
- **A pytest fixture error shows as ERROR, not FAILED.** A new failing test must fail inside its body, on its assertion.
- **Refusing looks like rigour.** Wave 1.5 found that fixers taught to refuse began declining input crivo should repair, and the lower number read as caution. Pin the legitimate repair beside every new refusal.
- **A docstring is not a fix.** Don't write that a hole is closed unless a test proves the whole of it.
- **The bench smoke only knows 30 corruption shapes.** A change can score clean there and still regress. If your change handles a new shape, add a corpus case for it.
- **tdd-guard is off for this repo** (Aarmen, 2026-10-14). Test-first is enforced by the test-writer and builder split and the Stop hook instead. Don't turn it back on.
