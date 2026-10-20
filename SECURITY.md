# Security

## Reporting a vulnerability

Report privately through GitHub:
https://github.com/aarmens702-hub/crivo/security/advisories/new

Please do not open a public issue for a security problem. You will get an
acknowledgement within 7 days.

## Supported versions

crivo is pre-1.0. Fixes go to `main` and the latest release tag only.

## What crivo protects today, and what it does not

The library half (`import crivo`, `crivo diagnose`, the GitHub Action) runs no
model code and makes no network calls of its own.

**The analyst is not sandboxed by default.** `crivo clean`, the REPL,
`crivo.ask` and the MCP tools `clean_file` and `ask` (in the kernel `open_data`
starts) run model-written Python in a subprocess, as the user who started
crivo, with that user's files (including `.env`) and network. `--docker`, or
`CRIVO_MCP_SANDBOX=docker` for the MCP server, runs it in a container with no
network. `crivo.ask` has no container option yet. Containment without Docker is
planned.

What limits exposure today:

- The kernel starts with an allowlisted environment, so provider keys are not
  in its `os.environ`. A cell can still read `.env` from disk in subprocess mode.
  In a container it can read `.env` too when the file sits inside the mounted
  `CRIVO_MCP_ROOT` or `--data-dir`, or inside the session's own directory under
  the workspace (`--workspace` or `CRIVO_WORKSPACE`). That directory is mounted
  read-write at `/workspace`.
- The MCP server only opens paths that resolve inside `CRIVO_MCP_ROOT`
  (default: the directory it was launched from). A process that can write
  inside the root can still swap a file between the check and the read.
- Variable names from MCP clients are checked before use.

## Threat model

The data a user loads can attack crivo. Text planted in a cell value, a column,
sheet or file name, or an error message reaches the model, which may follow it
as an instruction. What decides a verdict must sit out of the model's reach.

**Actors.** The data (any file, URL or database result a user loads); the
model (assume the data can steer it); a calling agent over MCP; the person at
a gate. Out of scope: a malicious model provider or a compromised machine.

**Paths from data to the model.**
- The dataset profile: column names, sample values and top values.
- The finding a model fix is given. Its evidence can quote raw values, from
  PII-flagged columns too.
- Cell output and error messages. The value, printed output and traceback are
  clipped today; the error message is not.
- Excel sheet names and file names, in load messages, error text and lineage.

**What an attack tries.** Reading secrets (`.env`, files under home, the
keychain); reaching the network; writing what the referee trusts; changing a
verdict; spending money; pushing a person to approve a gate.

**What the referee trusts.** Plan rule 2: nothing the model, the kernel or the
data can write may change a verdict. The referee trusts `skills/` (the SKILL.md
files and `ledger.json`), the session transcript, cards, clean reports, lineage
files, host-side baselines (after Stage 0b), `bench/` truth and
`bench/ledger.jsonl`, and later contracts, the glossary and saved answers.
Today kernel code can write them: the default kernel runs as the user, and a
Docker kernel can write the session's transcript, cards, clean reports and
lineage (the session's folder is mounted read-write). The referee's checks, and
the baselines they compare against, also live in the kernel today, so a cell
can patch them (RE1: the strict xfails in `tests/test_referee_bypass.py`).
Stage 0b moves them to the host (RE11 (#167) to RE13 (#169)).

**Defences.**
- **Today.** The kernel starts with an allowlisted environment, so provider
  keys are not in its `os.environ`. A cell can still read `.env` from disk.
- **Today.** A GATE or HUMAN gate runs only on a yes. Headless `crivo clean`
  defers both to `needs_human`; MCP `clean_file` defers HUMAN gates and asks
  GATE fixes by elicitation when the client can, trusting the client to put
  that question to a person. AUTO fixes, proven skills on AUTO findings and
  the query cells of `crivo.ask` and MCP `ask` run with no person.
- **Today, CT16 (#114).** The profile masks sample and top values from
  PII-flagged text columns. That guards privacy, not against injection: other
  text values, column names and numeric columns reach the model raw.
- **Stage 0d, CT3 (#147) to CT8 (#215).** An OS sandbox around the kernel: no
  network, read-only data, writes only to the kernel's own folder. Unattended
  paths then run model code uncontained only when the user opts out, and every
  card says so. Today only Docker contains the kernel; the default does not.
- **Stage 0d, CT9 (#149).** A memory limit on the subprocess kernel.
- **Stage 0d, CT13 (#112) to CT15 (#150).** Host secrets and token-shaped values
  are redacted from kernel output, the transcript and prompts, and secret-shaped
  columns are masked like other PII.
- **Stage 0d, CT17 (#110).** Every kernel message to the model is capped.
- **Stage 0d, CT22 (#195).** A dollar cap per task and per session.

**Known limits of the Stage 0d defences.**
- The memory watchdog polls, so a fast burst can overshoot the limit.
- Output from processes a cell starts is not captured.
- There is no OS sandbox on Windows.
- The macOS sandbox uses `sandbox-exec`, which Apple marks deprecated.
- The Linux sandbox needs unprivileged user namespaces; some systems block them.

## In scope

- Model-written code escaping a gate, or escaping the documented container.
- A secret reaching the kernel environment, a prompt, a log or an artifact.
- Raw values from a PII-flagged column in a shareable output (the HTML report,
  the notebook export, the reconcile report).
- Bypassing `CRIVO_MCP_ROOT`.
- A receipt or a verification that claims a check which did not run.

## Out of scope

- The documented unsandboxed default itself. Running the analyst means running
  model-written code as you.
- Findings that need a malicious model provider or a compromised machine.
- The check-then-read race in the MCP path check. A process that can write
  inside `CRIVO_MCP_ROOT` can swap a file after the check and before the read.
  This is a known limit.
