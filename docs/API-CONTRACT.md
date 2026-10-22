# API contract

Build against this exactly. If you need an interface that is not here, propose it on the issue; never invent it.

Every signature below is copied from the source. Shapes marked "seen" were captured from a real run on `crivo.load_example()`.

## Public Python API (`import crivo`)

| Name | Signature | Returns |
|---|---|---|
| `read` | `read(source, **kwargs)` | `DataFrame`. Local path (csv, tsv, txt, parquet file or folder, xlsx, xls, json, jsonl, ndjson, feather, orc, dta, sas7bdat, optionally .gz/.zip/.bz2/.xz), a sqlite file (`query=`), a DBAPI connection or SQLAlchemy URL, or an http(s) URL (`records_path=`). `format="fwf"` for fixed width. Missing tokens such as `"N/A"` stay strings. A skipped CSV preamble is stamped on `frame.attrs["preamble_rows"]`. A frame read from an http(s) URL carries `attrs["remote"] = {uri, fetched_at, sha256, rows, columns}`. Other URL schemes (`file://`, `ftp://`, ...) raise `ValueError`, and a redirect to one raises `RuntimeError`; cloud storage (`s3://`, `gs://`, ...) is not built yet and raises `NotImplementedError`. |
| `read_sql` | `read_sql(query: str, connection)` | `DataFrame`, via `pandas.read_sql`. |
| `write` | `write(frame, path, **kwargs)` | `Path`. Extensions: .csv .parquet/.pq .xlsx .json .jsonl/.ndjson .feather .orc; anything else raises `ValueError`. Parents are created. |
| `load_example` | `load_example()` | `DataFrame`, 60 rows x 5 columns (`customer`, `region`, `revenue`, `units`, `note`), same every call. Planted: d01, d04, d06, d07, d09. |
| `diagnose` | `diagnose(data, name=None)` | `Report`. `data` is a DataFrame or a path (read with `read`). |
| `clean` | `clean(df)` | `(DataFrame, CleanSummary)`. Input never mutated. |
| `compare` | `compare(before, after, name_before="before", name_after="after")` | `str`, one self-contained HTML document. |
| `reconcile` | `reconcile(a, b, keys)` | `dict` with keys `keys, counts, added, removed, changed, duplicate_keys, null_keys, column_diff, receipt, notes` (seen). `keys` is a column name or list. `receipt` is true when every distinct key lands in exactly one bucket or excluded set and an independent recount of changed rows, done without the per-row comparison, equals `counts["changed"]`. |
| `reconcile_report` | `reconcile_report(a, b, keys)` | `str`, HTML. A key cell or changed value from a column `flagged_columns(a, b)` flags is masked with `mask_cell`; counts, receipt and notes are unchanged. |
| `drivers` | `drivers(before, after, value_col, by_col)` | `dict` with keys `metric, by, total_before, total_after, delta, contributions, receipt` (seen). Rows with an empty `by_col` (None or NaN) form one contribution whose `category` is `None`. `receipt` is true when the contributions sum to `delta`, the change in the whole frames' totals, within rounding scaled to the size of the values (about 1e-9 of their absolute sum), so it cannot see a lost row smaller than that (e.g. under about $2.50 on a ledger with $2.5B of absolute volume). |
| `analyze_excel` | `analyze_excel(path)` | `list[dict]`, one per sheet: `sheet, header_row, preamble_rows, tables, grade, evidence, suggestion, kind` (seen). |
| `export_notebook` | `export_notebook(source, path)` | `Path` of a runnable .ipynb that re-reads and re-diagnoses `source`. Finding evidence in its markdown is masked (`pii.redact_findings`, see "PII masking"). |
| `ask` | `ask(data, question, *, name=None)` | `Answer`. Needs a model (see Environment). Raises `RuntimeError` naming the missing variable. Gates auto-run. |
| `main` | `main()` | `int`, the console-script entry. |

The accessor, registered on import: `df.crivo.diagnose(name=None) -> Report` and `df.crivo.clean() -> (DataFrame, CleanSummary)`.

### `Report`
- `findings: list[dict]`, `clear: list[int]` (disease ids that ran and found nothing), `broken: dict` (ids that could not run, with why).
- `to_dict()` keys: `name, rows, columns, findings, clear, broken`. `to_json(indent=2)`.
- `repr()` is the text report and `_repr_html_()` the notebook card, both with finding evidence from PII-flagged columns masked (see "PII masking").
- `plot(ax=None)` returns a matplotlib `Axes` and never calls `show`.
- `pii() -> list[dict]`, `semantic_types() -> list[dict]`, `cross_column(threshold=0.9) -> list[dict]` (each `columns, violations, strength, grade, confidence, evidence, examples`, graded HUMAN).
- `pii()` reads columns by position, so a frame with a duplicated column name can return two findings that share a `column`.
- `cross_column()` masks each `examples` element taken from a PII-flagged column (`pii.flagged_columns`, `pii.mask_cell`); elements from unflagged columns, `violations` and the `pairs-capped` note are unchanged.
- `to_html(path) -> Path`: one standalone HTML file, PII section first; finding evidence from PII-flagged columns is masked (see "PII masking").
- `suggest(k=5) -> list[str]`: starter questions; column names may appear, cell values never do.

### `CleanSummary`
- `applied`, `needs_review`: lists of `{disease, slug, columns, grade}`; a review entry may add `reason` (`"fix did not clear verification"`, `"fixer error: ..."`, `"found once the fixes ran"`, `"still present after the fixes ran"`, and for an `AUTO` finding with no fixer `"removing duplicate rows deletes data, so a person decides"` (d09) or `"no deterministic fixer for this disease yet"`). Every finding the cleaned frame still carries has a review entry of the same identity, the one `detect_one` reads: `disease`, `grade` and leading column (the column the finding is about, such as d11's key or d25's first twin; a whole-table finding matches on `disease` and `grade`). A leftover no entry names gets `"found once the fixes ran"` when no pre-fix finding had its identity (a correct fix uncovered it), and `"still present after the fixes ran"` when one did. There is one review entry per finding, and entries can share `disease`, `columns` and even `grade` (for example a d07 `AUTO` beside a d07 `HUMAN` on one column, or two d22 `GATE` findings on one id column).
- `to_dict()` keys: `applied, needs_review, rows_before, rows_after, columns_before, columns_after`. `to_json(indent=2)`.
- `samples(per_fix=3) -> list[dict]`: `{disease, slug, columns, examples}`. An example is `{column, row, old, new}` for a changed cell, `{column, renamed: True, new}` for a d18 header repair (`column` the old name, `new` the new one), or `{column, removed: True, value}` for a d19 constant-column drop (`value` the constant). Values are raw (exempt, see "PII masking").
- `repr()` is the text summary and `_repr_html_()` the clean card. Both mask a review `reason` with `pii.redact_text`; the card also masks example values from PII-flagged columns (never a header name) and clips each example value to 40 characters. A reason is masked, not clipped.
- `diff(max_rows=200)`: a pandas Styler of changed cells (needs jinja2, not a runtime dependency).

### `Answer`
- `card` (an `AnswerCard`), `notices: list`.
- Properties: `text` (the answer), `code` (the last cell that ran ok), `checks`, `lineage`, `images` (chart paths saved on the way).
- `AnswerCard` fields (`card.py`): `card_id, session, question, answer, cells, checks, lineage, model, flags, intent, created`.

## Findings
A finding is a plain JSON-safe dict (`detect._finding`):

| Key | Type | Meaning |
|---|---|---|
| `disease` | int | taxonomy id, 1 to 26 |
| `slug` | str | the id's name, from `SLUGS` |
| `columns` | list[str] | affected columns; `[]` means the whole table |
| `evidence` | str | one line, no row dumps |
| `stats` | dict | JSON-safe numbers (floats rounded to 6 places, NaN becomes null) |
| `grade` | str | `AUTO`, `GATE` or `HUMAN` |
| `confidence` | float | 3 decimal places |
| `indicator` | bool | true for 12 and 15: evidenced, never auto-fixed |

Seen: `{"disease": 1, "slug": "numbers-as-strings", "columns": ["revenue"], "evidence": "2 number formats in one column (bare 90%, symbol 7%)", "stats": {...}, "grade": "AUTO", "confidence": 0.95, "indicator": false}`.

**Grade ladder** (judgement required): `AUTO` < `GATE` < `HUMAN`. AUTO is mechanical; GATE is one plausible fix worth confirming; HUMAN is a judgement call, reported and never decided for you.

**Engine:** `detect_all(df, name="df") -> {findings, clear, broken}` runs the 25 single-frame signals. `detect_one(df, disease, columns, grade=None) -> dict | None` re-runs one signal on one target; `None` means clean, and it is how every fix is verified. With `grade`, only a residual of that grade counts (where a vanished target column is refused, it is refused whatever the grade). `detect_family(dfs: dict) -> list` is disease 20 only. At most 3 sample values ever leave a detector.

| id | slug | id | slug |
|---|---|---|---|
| 1 | numbers-as-strings | 14 | broken-coordinates |
| 2 | dates-as-strings | 15 | statistical-outliers |
| 3 | mixed-date-formats | 16 | unit-heterogeneity |
| 4 | sentinel-missing | 17 | packed-fields |
| 5 | suppression-codes | 18 | header-damage |
| 6 | whitespace-damage | 19 | empty-constant-columns |
| 7 | case-spelling-variants | 20 | schema-drift (family only) |
| 8 | encoding-mojibake | 21 | aggregate-rows |
| 9 | duplicate-rows | 22 | id-numeric-corruption |
| 10 | near-duplicate-rows | 23 | boolean-chaos |
| 11 | key-violations | 24 | stray-structural-rows |
| 12 | field-contradictions | 25 | duplicated-columns |
| 13 | out-of-domain-values | 26 | truncated-values |

Fixed sets in `detect.py`: `INDICATORS = {12, 15}`, `FAMILY_ONLY = {20}`, `COLUMN_CHANGING = {17, 18, 19, 25}` (a fix may change the column list), `WHOLE_FRAME = {9, 10, 18, 24}` (the detector reads the whole frame).

## PII masking
One shared masker in `pii.py`, keyless. Each surface under "Masked when rendered" masks when it renders. Detection (`detect._samples`) keeps real values, because the agent loop needs them to write a fix.

**Detected types:** `email`, `phone`, `ssn`, `credit_card` (Luhn-checked). Names and street addresses are not detected (they need NER).

**Masked form:** an email becomes `***@` plus its domain, cut at the first character outside `[\w.-]` (so a tail joined by `-`, `.` or `_` stays), or `[REDACTED]` when none follow the `@`; every other type becomes `[REDACTED]`.

| Name | Signature | Returns |
|---|---|---|
| `flagged_columns` | `flagged_columns(*frames)` | `dict[str, str]`: column name (as `str`) to PII type, from `scan()` of each frame. A later frame never overwrites an earlier frame's type, and when two same-named columns in one frame hold different types, the first by position wins. |
| `mask_cell` | `mask_cell(value, pii_type)` | `str`: `mask_value(str(value).strip(), pii_type)`, so a cell of any type masks. |
| `redact_text` | `redact_text(text, columns, flagged)` | `str`. Every quoted literal (Python repr quoting, single or double) becomes its masked form, quotes kept, when a name in `columns` (as `str`) is in `flagged` (the first flagged name in `columns` order sets the type), or else when the literal is PII on its own. A quote mark right after a word character (the apostrophe in `Excel's`, or a `"` stuck to a word) does not open a literal. All other text is unchanged. |
| `redact_findings` | `redact_findings(findings, flagged)` | `list[dict]`: shallow copies with `evidence` passed through `redact_text(f["evidence"], f["columns"], flagged)`. Never mutates its input; `flagged` is precomputed so a caller scans once. |

**Masked when rendered** (surfaces a person may send on, and the profile the model reads): `Report.to_html` and `_repr_html_`, the clean card, `print(summary)` and `export_notebook`, `reconcile_report`, `Report.cross_column` examples, `crivo diagnose` text output and `Report.__repr__` (`print(report)`), and the dataset profile (`profile.profile_df`, the `<dataset>` block the model reads after a load, and MCP `open_data`'s `profile`). In the profile, an object or string column is flagged when any of its first 10,000 non-null values (by position) is PII, and every sample and top value of a flagged column is masked as the most common type in that window. In an unflagged column, a shown `str` value that is PII on its own is masked; numbers are never checked. Top values are masked one by one (each keeps its raw count). `nunique`, non-null %, counts and stats are computed on the raw values, and column names are not masked.

**Exempt** (programmatic or interactive by design): `Report.findings`, `to_dict`, `to_json`, `crivo diagnose --json`, the `reconcile()` and `drivers()` dicts, `CleanSummary.diff()` and `samples()`, gate previews, MCP tool results other than `open_data`'s `profile`.

## CLI
Entry points: `crivo` and `python -m crivo` (same `main`), and `crivo-mcp`.

**`crivo diagnose FILE [--json] [--fail-on AUTO|GATE|HUMAN|never]`.** Keyless. FILE is read like `crivo.read` reads a local file (csv, tsv, parquet, json, jsonl, xlsx and the other formats in `readers.files.SUPPORTED`). `--fail-on` defaults to `GATE`. Exit `0`: no finding at or above the threshold. Exit `1`: at least one. Exit `2`: the file could not be read. `never` always exits `0`. `--json` prints `{file, rows, columns, findings, clear, broken}`. The text report masks evidence from PII-flagged columns (see "PII masking"); in a finding on no flagged column (a whole-table one, say) only a quoted literal that is PII on its own is masked. `--json` carries the raw evidence (programmatic, exempt). Options may come before or after FILE; `--help` works after the subcommand.

**`crivo clean FILE [--name NAME] [--autonomy LEVEL] [--json]`.** Needs a model and a kernel. Chatter goes to stderr; stdout is one JSON object with `--json`, else a short text summary. Exit `0` unless the summary carries `error`. Only AUTO runs unattended; judgement calls are deferred to `needs_human`. Summary (`repl.run_clean_once`): `{file, variable, needs_human: [str], notices: [str]}` (`notices` empty when none fired), and when a report was written `report, fixes: [{disease, slug, grade, status, unattended}], autonomy, outputs, skills_admitted`. On a failed load: `{file, error}`. `status` is `fixed`, `skipped`, `failed` or `aborted` (shown as "not attempted"). Options may come before or after FILE; `--help` works after the subcommand.

**`python -m crivo`** starts the REPL. Shared flags: `--workspace` (default `workspace`), `--data-dir` (default `data`; the read-only data mount under `--docker`, ignored otherwise), `--docker`, `--resume SESSION`, `--auto-run` (runs query cells without a gate, dev only; fix, plan and skill gates still wait), `--autonomy autonomous|careful|report-only` (default `autonomous`). REPL commands: `/load <path> [name]`, `/clean <var>`, `/clean-family <glob> <name>`, `/skills`, `/why [claim id]`, `/trace`, `/quit`; any other line is a question. The gate prompt is `[r]un / re[j]ect / [s]kip`.

Key check: `clean`, the REPL, `crivo.ask`, the MCP model tools and the agent bench share one per-provider check (`query.provider_problem`): `deepseek` needs `DEEPSEEK_API_KEY`, `claude` needs `ANTHROPIC_API_KEY`, `openai` needs `CRIVO_BASE_URL` and `CRIVO_MODEL`, `faux` needs nothing. Any other `CRIVO_PROVIDER` value is refused.

## MCP tools (`crivo-mcp`, stdio)
Every tool returns its errors as data (`{"error": ...}` or an error string), never a crash. Client paths must resolve inside `CRIVO_MCP_ROOT`.

| Tool | Arguments | Returns |
|---|---|---|
| `diagnose_file` | `path: str` | JSON string, the `crivo diagnose --json` shape. Keyless, read-only. |
| `clean_file` | `path: str, name: str \| None = None` | dict, the headless clean summary above. Runs at `careful`. Only AUTO runs unattended. GATE fixes are asked one by one whenever the client supports elicitation; every other judgement call comes back in `needs_human`. |
| `open_data` | `path: str` | `{session_id, variable, profile}`. `profile` is the dataset profile, with PII in its sample and top values masked (see "PII masking"). Idle sessions close after 30 minutes. |
| `ask` | `session_id: str, question: str` | the `AnswerCard` as a dict, plus `unresolved_gates` when a person's decision was skipped. On failure, `{error, notices}`. |
| `why` | `session_id: str` | str, the provenance chain as markdown. |
| `close_session` | `session_id: str` | bool, true when the session existed. |

The model-backed tools use the same check.

## Session events (`events.py`)
Drivers consume `SessionLike`: `load(path, name=None)`, `run_turn(question)`, `clean(var)`, `clean_family(pattern, name)`, `close()`. The three runners are generators of `Event`.

| Event | Fields | Driver answers with |
|---|---|---|
| `GateRequest` | `code, iteration, title="", preview="", grade=""` | `gen.send(GateDecision(action, note=""))`, action `run`, `reject` or `skip` |
| `StreamText` | `name, text` | `None` |
| `ArtifactSaved` | `path` | `None` |
| `Notice` | `kind, text` | `None` |
| `CardReady` | `card` (has `to_markdown()`) | terminal for the turn |

`grade` is empty for QUERY cells, `HUMAN` for both skill gates. With previews on, a QUERY cell or a model-written fix carries `preview="(no preview: model-written code runs only after you say yes)"` and nothing of it runs before the gate is answered. A proposed skill has two gates (#85). First its test gate: title `test skill …`, the proposed fix and test verbatim, the same no-preview line, and nothing of the skill runs until a person answers it. `run` runs its admission checks on a copy of the case it came from (the code runs in the live kernel); `reject` sends the note back for a revision; `skip`, or anything not a `GateDecision`, discards it unrun. Then, once those checks pass, its admission gate: title `admit skill …`, with its effect preview on the case. Notice kinds in use today: `autoclean, autonomy, cap, compaction, error, family, fix, intent, kernel_died, llm_error, nudge, plan, restart_offer, skill, skip`. A driver must render an unknown kind as text.

## Kernel supervisor protocol (`kernel/`, protocol v1)
One JSON object per line. The host writes requests to the supervisor's stdin; every event on stdout carries the request `id`; stderr is diagnostics only.

- Requests: `{id, op: "hello"}`, `{id, op: "execute", code, timeout_s}`, `{id, op: "interrupt"}`, `{id, op: "restart"}`, `{id, op: "shutdown"}`.
- `{id, ev: "stream", name, text}`: live output.
- `{id, ev: "display", mime: "image/png", b64}` or `{id, ev: "display", mime: "text/plain", text}`.
- `{id, ev: "result", status, value, error, exec_count, elapsed_s, registry, registry_omitted, truncated}`. `status` is `ok`, `error`, `timeout`, `interrupted` or `hung`. `error` is `{ename, evalue, traceback}`.
- The `hello` result adds `proto` (1), `python`, `ipykernel`. An unknown op or a malformed line gets a result whose error `ename` is `BadRequest`.
- Caps: a value is cut at 8 KiB, a stream at 64 KiB (head and tail kept, with a marker).
- The kernel's environment is an allowlist (`KERNEL_ENV_PASSTHROUGH`, plus `DOCKER_ENV_PASSTHROUGH` with `--docker`); provider keys are never passed in.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `CRIVO_PROVIDER` | `deepseek` | `deepseek`, `claude`, `openai` (any /v1 endpoint) or `faux` (canned replies, for tests) |
| `DEEPSEEK_API_KEY` | none | the deepseek provider's key |
| `ANTHROPIC_API_KEY` | none | the claude provider's key |
| `CRIVO_BASE_URL` | none | the openai provider's endpoint (required there) |
| `CRIVO_MODEL` | `deepseek-v4-pro`, or `claude-opus-5-5` for claude | overrides the model; required for openai |
| `CRIVO_API_KEY` | `local-no-key` | key sent to the openai provider |
| `CRIVO_STALL_S` | 90 | seconds with no stream bytes before a call is dead |
| `CRIVO_MAX_CALL_S` | 420 | cap on one model call, including provider retry waits, in seconds |
| `CRIVO_HTTP_TIMEOUT_S` | 30 | `crivo.read` http timeout |
| `CRIVO_HTTP_MAX_BYTES` | 536870912 (512 MiB) | http body cap for `crivo.read` |
| `CRIVO_WORKSPACE` | `workspace` | session workspace for `crivo.ask` and the MCP server |
| `CRIVO_MCP_ROOT` | the server's launch directory | the one directory MCP client paths may name; `/` and the home directory are refused |
| `CRIVO_MCP_SANDBOX` | unset | `docker` runs MCP cells in the container; unset runs a host subprocess and warns; any other value is an error |
| `CRIVO_TELEMETRY` | unset (off) | path of a JSONL telemetry file |
| `CRIVO_PLAN_FIRST` | `off` | `on` turns on plan-first cleaning (one plan approved as a unit) |
| `CRIVO_M1` | `on` | `off` restores the pre-M1 clean flow (the bench legacy arm) |

## Changing this file
A contract change is a `core`-labelled issue and needs Aarmen's yes before any code builds against it. Update this file in the same change as the code, never after.
