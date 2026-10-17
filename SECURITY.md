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
