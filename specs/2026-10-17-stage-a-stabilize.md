# Stage A: stabilize what ships

**Status: filed 2026-10-17** as issues #6 to #43 (plus #3). Aarmen accepted every
recommendation under "Decisions the owner owes" the same day.

2026-10-17. The WRAP spec for Stage A of `specs/2026-10-14-the-plan.md`. It is
built from a read-only code review of `dev` @ 2bfe8a8 the same day: five
reviewers covering broken paths, PII and receipts, docs and honesty,
correctness and retirements, and a whole-repo dead-code sweep. Every item below
was reproduced or quoted from the code, not taken from the inventory alone.

## What

Every path a visitor can reach today works and tells the truth: a fresh install
starts, each provider asks for the right key, shareable outputs carry no raw
value from a PII-flagged column, receipts can fail, and the docs say what the
code does (the analyst is not sandboxed by default). Dead code the review found
is removed so later stages build on less.

## Requirements

One issue each, ids as drafted. `core` marks an owner-reviewed diff.

**Broken paths**
| id | issue | core |
|---|---|---|
| BP1 (#6) | llm: a fresh install starts the analyst (`httpx` is gone under the current SDK majors) | core |
| BP2 (#8) | deps: pin what we use (`mcp>=2,<3`, numpy), drop the disabled tdd-guard plugin, and test what users install in CI | |
| BP3 (#7) | keys: check the right key for the chosen provider everywhere (CLI, MCP, bench); refuse unknown providers | |
| BP4 (#13) | claude: the Claude path works on current models and is counted (DD1, W23r, T51) | core |
| BP5 (#14) | cli: `crivo diagnose` reads json, jsonl and xlsx like the library (T56; today a JSON file reads as clean) | |
| BP6 (#15) | cli: `crivo diagnose --help` and `crivo clean --help` work | |
| BP7 (#16) | suggest: survive duplicate column names (T54) | |
| BP8 (#17) | loop: session ids stay unique past s99, and text after `</execute>` never reaches history (DD5) | core |

**PII and false receipts**
| id | issue | core |
|---|---|---|
| PI1 (#9) | pii: one shared masker for every shareable surface; scan duplicate-named columns (T34) | |
| PI2 (#18) | html report: one renderer, with PII-flagged evidence masked (T31, T32; title injection; int labels) | |
| PI3 (#19) | notebook: the clean card and notebook export mask and clip values; no crash on a header rename (T35) | |
| PI4 (#20) | reconcile: mask PII in the report; the receipt becomes a recount that can fail (T33, T27) | |
| PI5 (#21) | cross_column: mask examples from PII-flagged columns (`f`) | |
| PI6 (#22) | cli: `crivo diagnose` text output masks PII-flagged evidence (the Action prints it to CI logs) | |
| PI7 (#23) | drivers: count null categories; check the receipt against whole-frame totals (T26) | |
| PI8 (#24) | autoclean: keep a HUMAN finding beside an AUTO one; say why an AUTO finding was left (T14, `k`) | |
| PI9 (#25) | detect: stop refusing a correct d07 case fix because a HUMAN sibling is open | core |

**Correctness and retirements**
| id | issue | core |
|---|---|---|
| #3 | bench: `--smoke` stops overwriting `bench/RESULTS.md` (`h`, already filed) | |
| CR1 (#10) | bench: a smoke case for numeric placeholders like `-999` (instrument first; author has not read the detector) | |
| CR2 (#26) | detect: d04 catches `-999`-style placeholders and clean clears them (`j`), plus detect.py hygiene | core |
| CR3 (#27) | skills: a multi-line description survives save and load (T53) | core |
| CR4 (#28) | cli: `crivo clean --json` always includes `notices` (D2) | |
| CR5 (#29) | library: remove the unused `policy` argument (`d`) | |
| CR6 (#30) | headless: remove `--policy` from the CLI and MCP; always elicit when the client can | |
| CR7 (#31) | policy: move the autonomy levels out of the governance module (D3) | core (1 line) |
| CR8 (#32) | governance: delete the inert governance file and module (D3; makes T55 moot) | |
| CR9 (#33) | readers: retire `ingest.py`; URL reads record their source and refuse non-web schemes (T50) | |
| CR10 (#34) | cli: drop the misleading "core not implemented" fallback; say what `--data-dir` does | |
| CR11 (#35) | repl: `--auto-run` runs only query cells; fixes, plans and skill admissions wait for a person | |

**Honesty, docs and security**
| id | issue | core |
|---|---|---|
| HD1 (#36) | docs: say plainly that the analyst is not sandboxed by default | |
| HD2 (#37) | mcp and action: code-running tool descriptions lead with the unsandboxed default | |
| HD3 (#38) | skill: rewrite the `crivo` agent skill against the real CLI | |
| HD4 (#11) | security: SECURITY.md with private reporting and the unsandboxed default | |
| HD5 (#12) | releases: tag v0.1.0, pin the Action example, keep a changelog from fragments | |
| HD6 (#39) | docs: stale check counts, the depth-1 wording, other stale lines | |
| HD7 (#40) | repo: drop the retired committed skill; rename the take-home fetcher | |
| HD8 (#41) | docs: mark closed working notes historical; drop the duplicate quickstart | |

**Cleanup**
| id | issue | core |
|---|---|---|
| CL1 (#42) | tests: drop the placeholder and duplicate tests; fold six import checks into one | |
| CL2 (#43) | cleanup: remove dead helpers in the library, bench and scripts | |

## Acceptance criteria (the Stage A gate)

- A fresh install from `pyproject.toml` without the lock imports `crivo.loop`
  and passes the keyless suite (BP2's CI step), on Linux and macOS.
- Every non-paid case in `docs/QA.md` passes from a fresh install; no case is
  marked "Fails today".
- CI is green on `dev` and on the `dev` to `main` promotion.
- One test per shareable surface (HTML report, clean card, notebook export,
  reconcile report, `cross_column`, `crivo diagnose` text) shows no raw value
  from a PII-flagged column. The exempt surfaces are listed in
  `docs/API-CONTRACT.md` ("PII masking").
- No shipped doc, docstring, tool description or skill calls the default
  kernel sandboxed or points at the superseded master plan.
- `v0.1.0` is tagged and the README's Action example pins a tag.

## Priority

**Wave 1, unblock first:** BP1, BP3, BP2, PI1, #3, CR1, HD4, HD5 (tag v0.1.0
before any breaking change is promoted).

**Wave 2, the fixes** (parallel across areas; same-line order in brackets):
BP4, BP5, BP6, BP7, BP8; PI2 to PI8, then PI9 [after PI8]; CR2 [after CR1];
CR3; CR4, CR5, CR6 [in that order]; CR7, CR8 [in that order]; CR9;
CR10 [after BP3]; CR11.

**Wave 3, docs that describe the fixed behaviour:** HD1, HD2, HD3 [after CR4,
CR6, BP3], HD6, HD7, HD8, CL1, CL2.

**Shared files, landing order** (whichever lands second rebases):
- `__main__.py`: BP3, BP6, CR10, CR11, CR6, CR7.
- `mcp_server.py`: BP3, HD2, HD6, CR6.
- `repl.py`: CR4, CR11, CR6.
- `autoclean.py`: PI8, PI9, CR5, CR2.
- `llm.py`: BP1, BP4. `checkup.py`: BP5, PI6, HD6, CR9.
- `docs/API-CONTRACT.md` is touched by most issues, each in its own section.
- HD5 edits the ship and promote skills and AGENTS.md, so it lands after the
  workflow change.

Core reviews for Aarmen: BP1, BP4, BP8, PI9, CR2, CR3, CR7 (seven diffs, each
small enough for one sitting).

## Decisions the owner owes

| issue | decision | recommendation |
|---|---|---|
| CR4 | D2: `notices` always present or only when fired | always present, `[]` when none |
| CR7, CR8 | D3: wire the governance file or remove it | remove |
| CR2 | grade of the new numeric placeholder tokens | AUTO, only for strong tokens in otherwise numeric text columns, outside their range |
| BP2 | dependency changes; cap SDK majors or move the lock forward | move the lock to the current majors |
| BP4 | effort level on the Claude path | `high`, as a constant |
| CR11 | restrict `--auto-run` or retire it | restrict now; revisit with containment in 0d |
| PI5 | is `cross_column` a shareable surface | yes, mask it |
| PI9 | a residual finding of another grade does not fail verification | confirm |
| HD5 | immutable tags only; v0.1.0 on current `main`; 0.2.0 for the `--policy` removal | confirm |
| HD4 | enable private vulnerability reporting (owner action) | enable |
| HD8, CL2 | delete `docs/first-60-seconds.md` and `scripts/preview_notebook_html.py` | delete |

## Cut from Stage A, with reasons

| item | where it goes | why |
|---|---|---|
| T52 snapshot paths under docker | 0b | belongs with "resume across transports"; Docker is opt-in |
| Retire `CRIVO_M1=off` | Stage 1 | rewrites tests in `loop.py` just before the loop rebuild |
| T55 governance validation | dropped | moot once CR8 removes the module |
| T50 `load_url` schemes | dropped | `ingest.py` is retired (CR9) |
| Retire `--data-dir` | kept | it is wired under `--docker`; CR10 fixes its help |
| `llm.is_context_overflow`, `generate(model=)`, `loop._context`, `diff.inline`, `KernelClient._send_raw`, `bench.run.sweep` | 0a, 0b, 1 | in modules those stages rebuild |
| `pii.mask_column` | after PI6 | delete if nothing adopts it |
| `skills._unflow` splits `allowed-tools` on commas | Stage 2 | latent; nothing sets `allowed_tools` |
| d04 sentinel-date fixer mismatch | 0c (T44) | a taxonomy call |
| Record and replay tests, `agent_run --record` | before Stage 0 | part of the workflow change for agentic work |

## Size

38 issues plus #3. About three weeks at the current pace, up from the plan's
two: the review found more than the inventory listed (a broken fresh install,
an MCP server that cannot start on mcp 1.x, a false clean on JSON files, script
injection in the HTML report).
