# Changelog

User-visible changes to crivo. While crivo is 0.x, a minor bump (0.2.0) may
change CLI flags, exit codes or output shapes; a patch bump (0.1.1) does not.

## Unreleased

Collected from `changes/` when the next release is cut.

## 0.2.0 (2026-10-17)

Stage A: a fresh install starts again, each provider asks for the right key,
shareable outputs mask PII, and receipts can fail. A minor bump, because
`--policy` and `policy=` are gone and `crivo clean --json` always carries
`notices`.

### Changed

- `crivo clean --json` and MCP `clean_file` now always include `notices`, as an empty list when none fired. (#28)
- `python -m crivo --auto-run` now runs only the analyst's own query cells without asking; every gate under `/clean` and `/clean-family` (fixes, plans, harmonize steps and skill admissions) waits for your answer and shows its preview, so no skill is kept without a person's yes. (#35)

### Removed

- `crivo.clean` and `df.crivo.clean` no longer accept `policy`, which was never read; drop the argument from your calls. (#29)
- `crivo clean` no longer accepts `--policy` (it exits 2), and MCP `clean_file` no longer takes `policy`; neither summary has a `policy` key. `clean_file` now asks through elicitation whenever the client supports it; otherwise only AUTO fixes run and the rest come back in `needs_human`. (#30)
- The `crivo.governance` module and `docs/governance.example.json` are gone: nothing at runtime read them. `--autonomy` is the live control. (#32)

### Fixed

- A fresh, unlocked install can start the analyst again: crivo no longer imports `httpx`, which it never declared and the current SDKs replaced. (#6)
- The CLI, the MCP server and the agent bench check the key the chosen provider needs: `faux` needs none, `openai` needs `CRIVO_BASE_URL` and `CRIVO_MODEL`, an empty `CRIVO_PROVIDER` means deepseek, and an unknown provider is refused by name. (#7)
- crivo now requires mcp 2.x. An environment that already had mcp 1.x installed used to keep it and get a `crivo-mcp` that could not start; installing crivo now upgrades it. (#8)
- The PII section of `Report.to_html()` now scans columns that share a name, and a masked email sample keeps only its domain, so a phone number packed after it no longer shows. (#9)
- `CRIVO_PROVIDER=claude` sends the request current Claude models expect (claude-opus-5-5 by default, effort high, adaptive thinking, no temperature), its token use and cache hits reach telemetry and the bench, and Ctrl-C during a call that is still opening cancels it. (#13)
- `crivo diagnose` (and the GitHub Action, `crivo clean` and MCP `diagnose_file`) now reads json, jsonl, xlsx and parquet directories instead of parsing them as CSV; a JSON file used to report 0 rows and clean. (#14)
- `crivo diagnose --help` and `crivo clean --help` now print help, and options may come before the file (`crivo diagnose --json data.csv`). (#15)
- `Report.suggest()` no longer crashes on a table whose columns share a name. (#16)
- Text the model invents after its code cell (a made-up "Output:") no longer reaches its history, the screen or the transcript, and sessions past s99 no longer share a folder. (#17)
- `crivo.drivers()` now counts rows whose category is empty (as a None category), no longer raises on mixed-type categories, and its receipt checks the contributions against the whole-frame change. (#23)
- `clean()` no longer drops a finding it left for review when another finding on the same column was fixed or listed, and an AUTO finding it could not fix (such as duplicate rows) now says why. (#24)
- `crivo.clean` no longer reverts a correct case fix over an open spelling finding: a fix is reverted when its own finding is still there or when it raises a finding of its own disease at another grade on its columns, and a fix that uncovers another disease is kept. Every finding left on the cleaned frame is listed in `needs_review`, one the fixes uncovered with the reason "found once the fixes ran". (#25)
- `crivo.diagnose` names a typed-in numeric placeholder such as `-999` in a column of numbers stored as text, and `crivo.clean` clears it, when the placeholder lies outside the real values. (#26)
- A skill whose description (or a metadata value) spans lines now saves and loads back; before, the saved SKILL.md couldn't be read again, so an admitted skill was silently dropped. (#27)
- When `python -m crivo` can't start because an import fails (a missing dependency, say), you now see the real ImportError instead of a message saying the core isn't implemented, and `--help` says `--data-dir` is the read-only data mount for `--docker` (ignored otherwise). (#34)
- The `/crivo` agent skill now matches the real CLI: it says the analyst is not sandboxed by default, drops `--policy`, explains `--autonomy`, the exit codes, the `notices`, `unattended` and `indicators` fields and the openai provider, and works outside the crivo repo. (#38)

### Security

- `SECURITY.md` says how to report a vulnerability privately and what limits exposure today, including that the analyst runs model-written code on the host by default. (#11)
- `Report.to_html()` and the notebook card now mask evidence from columns flagged as PII (email, phone, SSN, card), and a report name can no longer inject a script into the page title. (#18)
- The clean card in a notebook and `crivo.export_notebook` mask values from columns flagged as PII (email, phone, SSN, card), and the clean card clips each example value to 40 characters. (#19)
- `reconcile_report` now masks keys and changed values from PII-flagged columns (email, phone, SSN, card), and its receipt recounts the changed rows independently, so the badge reads "receipt: NOT verified" when the row comparison miscounts; the `reconcile()` dict still carries raw values. (#20)
- `Report.cross_column()` masks example values taken from PII-flagged columns. (#21)
- `crivo diagnose` text output and `print(report)` now mask evidence from columns flagged as PII, so the GitHub Action no longer prints raw emails or phone numbers into CI logs; `--json` is unchanged. (#22)
- `crivo.read` refuses URL schemes other than http(s) and database URLs, and a web read no longer follows a redirect off http(s). A frame read from a URL records its source, fetch time and sha256 on `attrs["remote"]`. (#33)
- The README and docs now say plainly that the analyst runs model-written code on your machine, as you, with your files and your network, unless you pass `--docker` (a container with no network). (#36)
- The MCP tools that run model-written code (`clean_file`, `open_data`, `ask`) now open their descriptions with "Not sandboxed by default": the code runs as the server user, with that user's files and network, unless `CRIVO_MCP_SANDBOX=docker` puts it in a container with no network. The GitHub Action's description now says it never runs model-written code. (#37)

## 0.1.0

The first tagged release. Pin it in workflows with
`uses: aarmens702-hub/crivo@v0.1.0`.
