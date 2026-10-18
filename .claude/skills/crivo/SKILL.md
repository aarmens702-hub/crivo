---
name: crivo
description: Use when the user provides a messy CSV/TSV/parquet file, asks what is wrong with a dataset, wants a data file cleaned with an audit trail, or wants questions answered over tabular data with verifiable receipts. Drives the crivo CLI (diagnose, headless clean, the interactive REPL) and interprets its artifacts.
---

# Driving crivo

crivo diagnoses messy tables, cleans what it can prove, and ships every change
with executed checks and lineage. You are the orchestrator; it is the tool. Its
trust model is the point: follow it, do not work around it.

**The analyst is not sandboxed by default.** `crivo clean`, the REPL and the
MCP tools `clean_file`, `open_data` and `ask` run model-written Python in a
subprocess on this machine, as this user, with their files (including `.env`)
and network. Tell the user before the first run.
`--docker` runs it in a container with no network; the file must sit under
`--data-dir` (default `./data`), which is mounted read-only, and the image must
be built first, from a crivo checkout: `docker build -t analyst-kernel -f docker/Dockerfile .`.
`crivo diagnose` runs no model code.

## Running it

- Installed (`pip install git+https://github.com/aarmens702-hub/crivo`):
  `crivo diagnose ...`, `crivo clean ...`, and `crivo` for the REPL.
- Not installed: `uvx --from git+https://github.com/aarmens702-hub/crivo crivo diagnose <file>`.
- Inside the crivo repo: `uv run crivo ...`.

## Step 1: diagnose (always first; free, no API key, read-only)

    crivo diagnose <file> --json --fail-on never

Returns `{file, rows, columns, findings, clear, broken}`. Each finding has
`disease`, `slug`, `columns`, `evidence`, `stats`, `grade`, `confidence` and
`indicator`. A finding with `indicator: true` is flagged for a person and never
fixed. `clear` lists checks that ran and found nothing (absence is a claim, not
a silence); `broken` lists checks that could not run. Summarize the findings
worst first. If the file is fine, say what was checked, not just "looks good".

Exit codes: `0` when nothing is at or above `--fail-on`, `1` when at least one
finding is (the default `GATE` means "something needs a person"), `2` when the
file could not be read (stdout is then one `could not read ...` line, not JSON)
or an argument was wrong. Exit 1 is a result, not a failure. Pass
`--fail-on never` when you only want the report.

## Step 2: headless clean (needs a model key; writes artifacts)

Keys: `DEEPSEEK_API_KEY` for the default provider; `CRIVO_PROVIDER=claude` with
`ANTHROPIC_API_KEY`; or `CRIVO_PROVIDER=openai` with `CRIVO_BASE_URL` and
`CRIVO_MODEL` (and `CRIVO_API_KEY` if the endpoint needs one). Exporting the
variable always works. A `.env` is read only from a directory above where crivo
is installed (for example the project that holds its `.venv`); it is not looked
up from the current directory. Never read or print `.env`.

Agree the autonomy level with the user before running:

- `--autonomy autonomous` (the default) applies AUTO-grade findings that have a
  deterministic fixer without asking, re-checking each and reverting it if the
  check fails.
- `--autonomy careful` puts a gate before those too.
- `--autonomy report-only` diagnoses and changes nothing.

Every model-written fix passes a gate at every level. At `autonomous` and
`careful` alike, a proven library skill fixes an AUTO finding with no gate; only
`report-only` stops it. No level decides a judgement call or admits a skill. In
headless mode nobody answers a gate, so crivo's headless rule does: every
AUTO-grade gate runs, model-written fixes included, and everything else lands
in `needs_human`. So headless, `careful` still applies AUTO-grade fixes; only
`report-only` changes nothing.

    crivo clean <file> --json --autonomy careful

Chatter goes to stderr; stdout is one JSON object:

- `file` and `variable`: what was loaded, and under which name.
- `fixes`: one entry per fixable finding, with `disease`, `slug`, `grade`,
  `status` and `unattended`. `status` is `fixed`, `skipped`, `failed` or
  `aborted` (not attempted). `unattended: true` means no gate was shown for it.
  In `crivo clean` the headless rule answers every gate that is shown, so no
  fix was approved by a person, whatever `unattended` says; tell the user what
  was fixed, and which fixes ran with no gate at all. Indicator findings are in
  neither `fixes` nor `needs_human`; the report JSON lists them under
  `indicators`. Relay them as flagged, not fixed.
- `needs_human`: judgement calls. Relay them verbatim. An agent must not
  decide them.
- `notices`: messages crivo must show the user, such as "crivo just changed
  your data without asking". Always relay them. An empty list means none fired;
  that notice fires once per workspace, so later runs that change data unasked
  carry none.
- `autonomy`: the level that ran.
- `report`: the clean report JSON; a sibling `.md` is human-readable.
- `outputs`: the cleaned parquet and its lineage JSON, or `{}` when no fix
  landed, in which case no cleaned file exists.
- `skills_admitted`: skills a person admitted during the run.
- `fixes`, `autonomy`, `report`, `outputs` and `skills_admitted` come with the
  report. A summary with only `file`, `variable`, `needs_human` and `notices`
  means the clean did not run: the diagnosis inside the kernel failed, or
  `--name` was given and the load failed. It exits `0` with no `error`. Report
  it as a failure whatever the exit code, and show the user stderr, which may
  say why.
- Without `--name`, a failed load gives `{file, error}`. The exit code is `0`
  unless the summary carries `error` (then `1`). A missing model key exits `1`
  before any of this, with one plain line on stdout instead of JSON; a wrong
  argument exits `2`.

## Step 3: what needs a person

If `needs_human` is non-empty, offer the interactive REPL. The person runs it in
their own terminal, with the same model key `crivo clean` needs, and answers its
gates; each gated fix shows a preview of its consequence first. Never run it
yourself with piped input, and never answer a gate for them.

    crivo        # then: /load <file> <name>, /clean <name>, /why, /skills

## If the MCP server is configured

Prefer the crivo MCP tools (`diagnose_file`, `clean_file`, `open_data`, `ask`,
`why`, `close_session`) over the shell. Three differences from the CLI:
`clean_file` always runs at `careful`; with a client that supports elicitation
it asks the person about GATE-grade fixes one by one; and every path must sit
inside `CRIVO_MCP_ROOT` (default: the server's launch directory). `clean_file`,
and `open_data` with `ask`, run model-written Python as the server user with no
sandbox, unless the server was started with `CRIVO_MCP_SANDBOX=docker`; tell
the user before the first call. `ask` runs the analyst's query cells without a
gate. When it skips a decision a person owes, it lists it in
`unresolved_gates`: relay those the way you relay `needs_human`.

## Rules

- Never claim the data is clean beyond what the report says. Quote counts from
  the report, not from your own reading of the file.
- The cleaned parquet in `outputs` is the deliverable when there is one; when
  `outputs` is `{}`, nothing was cleaned and there is no file to hand over.
  crivo does not write to the original (under `--docker` it cannot: `/data` is
  mounted read-only), and the report records its sha256. The lineage JSON links
  the two; mention it when the user cares about auditability.
- If a fix `failed`, the summary carries `error`, or it has no `report`, say so
  plainly and show the report path or stderr. Do not rerun at a looser autonomy
  level to get a green result.
