# crivo: what we're building

**One line:** an AI analyst for messy data that diagnoses, cleans and answers questions over tables, and re-checks every fix and answer before it counts.

**Who it's for:** anyone handed a messy export (analysts, data scientists, the engineer whose pipeline just choked on `N/A`), and the agents they work through: Claude Code, Claude Desktop, Cursor, or a CI job.

**Why it's different:** other tools chat with your dataframe or profile it. crivo verifies its own output. A fix is kept only if the check that found the problem stops firing and every column it didn't touch is unchanged; otherwise it's reverted and reported. Every answer ships with the code that produced it, the assertions that passed, and its lineage back to the raw file. The long version is `docs/what-this-is.md`.

## The three surfaces
1. **The library** (`import crivo`): diagnose, clean, read, write, compare, reconcile. Keyless, no kernel.
2. **The analyst** (`python -m crivo`, `crivo.ask`): a model driving an IPython kernel (a host subprocess with your files and network by default, a container with no network under `--docker`). In the REPL every model-written cell waits at a gate; `crivo.ask` and MCP `ask` run query cells without one.
3. **The agent tools**: the MCP server (`crivo-mcp`), the GitHub Action, the `/crivo` agent skill, and `crivo diagnose` as a data linter.

## Demo story
What a new visitor does in under three minutes. `/demo-check` and `/promote` walk exactly this.

1. Install from GitHub: `pip install git+https://github.com/aarmens702-hub/crivo`.
2. `import crivo as cv; cv.diagnose(cv.load_example())` shows five findings (numbers as strings, `N/A` sentinels, whitespace, case variants, duplicate rows) and names every check that came back clean.
3. `cleaned, summary = cv.clean(df)` applies four fixes, re-checks each, and leaves the duplicate rows for review because dropping rows is a judgement call. `summary.samples()` shows old and new values.
4. Save the example as a csv. `crivo diagnose example.csv --fail-on AUTO` exits 1, and `--fail-on GATE` exits 0: crivo works as a linter for data.
5. With a model key: `python -m crivo`, `/load` the file, ask "which region has the most revenue?", approve the cell at the gate, then `/why` shows where the answer came from.

## Not building
From `specs/2026-10-14-the-plan.md`, "Dropped, with reasons": slide export, dashboard servers, imputation except as a person-graded suggestion with receipts, model-written statistics, parallel read-only fan-out, speculative drafting, and sub-agents with their own kernels. crivo's own governed memory is in the plan (its Memory section), so it is no longer excluded.
