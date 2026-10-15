# Plan inventory: the ids behind `the-plan.md`

2026-10-14. Two read-only inventories run against `dev` @ 84b1e7a, each item
checked against code and git history. This file defines every id the plan
uses, so `/new-task` can turn an id into an issue without asking.

**Id prefixes:** `T#` = finding # in `2026-09-06-review-triage-and-fix-plan.md`;
`W15` = `2026-09-07-wave1.5-regression-triage.md`; lowercase letters = defects
found in the 2026-10-14 session; `DD#` = item # in
`docs/research/2026-10-14-four-deep-dives-summary.md`; `BT#` =
`docs/bench-triage-2026-09-02.md`; `RF*` = `docs/research-followups-2026-08-17.md`;
`P0r`/`P2r*` = residuals of the P0 and P2 fix commits (e59fc95, 848f050).

## Open defects (54) and hardening items (7)

| id | defect | sev | core file | plan stage |
|---|---|---|---|---|
| T12r | Plan policies persist all session; every plan id is `plan-v1`; the reject note is dropped (loop.py:1556, :1583) | P1 | loop.py | 0b |
| T13 | Bench `_drive` auto-runs GATE and PLAN gates (agent_run.py:100) | P1 | | 0a |
| T14 | autoclean `needs_review` dedupe drops a HUMAN finding beside an AUTO one (autoclean.py:794) | P1 | | A |
| T15 / a | Verify baseline lives in kernel globals; a cell that re-runs `baseline_cell` verifies after deleting rows (verify.py:55, :595). Reproduced 2026-10-14 | P1 | loop.py | 0b |
| T25 | `lift_checks` stamps every AST assert passed, including ones that never ran (card.py:115) | P3 | card.py | 0b |
| T26 | decompose drops null categories; receipt stays true (decompose.py:29, :56) | P3 | | A |
| T27 | rowdiff partition receipt is tautological (rowdiff.py:295) | P3 | | A |
| T28 | Bench oracle and no-op invariants cannot fire, yet `"invariants": "ok"` (bench/run.py:34) | P3 | | 0a |
| T29 | Intent check records any non-"mismatch" reply as a match (loop.py:1480) | P3 | loop.py | 0b |
| T30 | `clean()` returns True after a failed diagnosis, no report (loop.py:567) | P3 | loop.py | 0b |
| T31 / T32 | Shareable HTML carries raw PII through finding evidence; `to_html` claims it never does (htmlreport.py, api.py:166) | P4 | detect.py (`_samples`) | A |
| T33 | `reconcile_report` writes raw keys and values, no PII gate (rowdiff_report.py) | P4 | | A |
| T34 | PII scan skips duplicate-named columns (pii.py:94) | P4 | | A |
| T35 | Notebook before/after cells render raw and uncapped (notebook.py:214) | P4 | | A |
| f | `Report.cross_column()` examples hold raw cells | P4 | | A |
| T42 | d12 scan silently capped yet listed clear (detect.py:1345) | P6 | detect.py | 0c |
| T43 | d19 calls `null_frac >= 0.995` empty at AUTO 1.0 (detect.py:1880) | P6 | detect.py | 0c |
| T44 | d04 grades `1900-01-01` and `none` AUTO | P6 | detect.py | 0c |
| T45 | d01 evidence overstates ("30/30 carry residue" when 2 match nothing) | P6 | detect.py | 0c |
| T46 | d14 counts NaN coordinates as out of range (detect.py:1535) | P6 | detect.py | 0c |
| T47 | d08 single-character markers fire on Spanish names ("Ñuñoa") (detect.py:123) | P6 | detect.py | 0c |
| T48 | A one-cell title above the header is absorbed and reported clean (excel_structure.py:69) | P6 | | 0c |
| T50 | `load_url` accepts `file://`, `ftp://`; truncates silently (ingest.py:42) | P7 | | A |
| T51 | `_watched` clears a cancel that lands mid-call (llm.py:327) | P7 | llm.py | A |
| T52 | Snapshot and restore use host paths under docker (loop.py:671, :2355) | P7 | loop.py | A |
| T53 | `_scalar` does not escape newlines; admitted SKILL.md cannot be parsed back (skills.py:65) | P7 | skills.py | A |
| T54 | `Report.suggest()` raises on duplicate column names | P7 | | A |
| T55 | Governance contract is not a uniform ValueError; unknown keys accepted | P7 | | A |
| T56 | CLI parses every non-parquet file as CSV (checkup.py:89) | P7 | | A |
| P2r1 | A model fix can corrupt its own target column and verify (no target contract) | P2 | detect.py, loop.py | 0b |
| P2r2 | detect grades AUTO on findings autoclean always refuses | P6 | detect.py | 0c |
| P0r | Sandbox optional: host kernel by default, a cell can read `.env` from disk, MCP `ask` runs model code as the server user | P0 | | see the plan's sandbox stage |
| W23r | Claude runs unpriced (llm.py maps only OpenAI/DeepSeek usage names) | P5 | llm.py | A |
| b | `httpx` imported (llm.py:16) but undeclared; a fresh install cannot start the analyst | P0 | | A |
| c | `__main__.py:122` and `mcp_server._required_key` demand `DEEPSEEK_API_KEY` under `faux` and `openai` | P7 | | A |
| d | `clean(df, policy=...)` never reads `policy` (autoclean.py:755) | P7 | | A |
| e | `load_governance()` has no runtime caller; the governance file is inert | P7 | loop.py | A (D3) |
| g | Stale check counts: mcp_server.py:496, detect.py:1, checkup.py:5, CLAUDE.md | P7 | detect.py (docstring) | A |
| h | `bench.run --smoke` overwrites `bench/RESULTS.md` (run.py:272) | P5 | | A |
| i | `clean --json` omits `notices` when none fired (repl.py:444) | P7 | | A (D2) |
| j | `load_example` plants `-999`; d04 misses it | P6 | detect.py | A |
| k | d09 graded AUTO but FIXERS has no 9; deferred with no reason | P6 | detect.py | A (reason), 0c (grade) |
| DD1 | Claude path: `temperature=0.0`, `max_tokens` 8192, default `claude-opus-5` (llm.py:84, :285) | P7 | llm.py | A |
| DD2 | Repair F1 drops `None`, so 0.923 is 0.596 with real misses (run.py:59) | P5 | | 0a |
| DD3 | Bench rows do not record the model; provider not in the arm suffix | P5 | llm.py | 0a |
| DD5 | No stop sequence at `</execute>`; invented output enters history | P3 | llm.py, loop.py | A |
| DD5b | "depth 1" wording reads like RLM recursion (ARCHITECTURE.md:80) | P7 | | A |
| DD7 | `mcp` pinned 2.0.0 while the spec moved | P7 | | MCP stage |
| BT1 | d16 blind to mixed magnitudes; needs ratio-residue design | P6 | detect.py | Later 7 |
| BT2 | Bench truth single-label; overlaps charged as false positives | P5 | | 0a (D5) |
| BT3 | d6 `_ws_tidy` collapses legitimate internal double spaces | P6 | detect.py | 0c (D8) |
| BT4 | score_fixes.py still says `data/raha/` | P7 | | A |
| BT5 | Phase-6 spec smoke budget text stale | P7 | | A |
| RFa | MCP errors not structured `{code, message, retryable}`; no spill-to-file caps | backlog | | MCP stage |
| RFb | No `schema_version` or atomic writes on provenance, skill, session records | backlog | provenance.py, skills.py | formats (stage 1) |
| RFc | No single secret-redaction helper on every egress | backlog | | sandbox stage |
| RFd | No wheel case-collision test | backlog | | 5 |
| RFe | Provider path: `{env:VAR}`, empty `/models`, Retry-After, never replay a mutating call | backlog | llm.py | 1 |
| RFf | Content-digest skill admission; register-time capability scan | backlog | skills.py, library.py | 2 |
| RFg | README lacks "why not" prose and provider/MCP tables | backlog | | 5 |

Verified closed and dropped from the list: triage T1 to T11, T16 to T24,
T36 to T41, T49; wave 1.5 R0.1 to R4.32 except R3.23 (now `W23r`) and R4.31
(too vague to check); everything in `docs/open-findings.md`; the stress
finding (67b8479); the bench-triage detector silences d5, d7, d10, d11, d13,
d14, d17, d21, d22 and the d1 false positive.

## Old roadmap ids used by the plan

| id | source | item |
|---|---|---|
| P2.3, P2.5 | master roadmap 08-15 | cloud storage via fsspec; warehouses |
| P3.4 | master roadmap | several frames or a join in one question |
| P3.6 | master roadmap | speed pass |
| P4.1 to P4.4 | master roadmap | pandas-ai baseline, PyPI, demo, registries and docs site |
| P5.2, P5.3 | master roadmap | RAG grounding, agent messaging |
| LG3 to LG5 | phase6-plus 08-31 | Windows and 3.13 CI; name check; sandbox sentence in listings |
| MCP.1 to MCP.3 | phase6-plus | port to 2026-07-28; registry listing; spec position paper |
| A0.1 to A4.4 | agent-system roadmap 09-04 | steer, telemetry, planner, routing, drafts, fan-out, memory, MCP port, versioning, bench columns |
| T2.5, T2.6, T3.1 to T3.3 | a1 build plan | governance file, judge monitor, best-of-N, skill short-circuit |
| B0.1 to B5.3 | capability roadmap 09-04 | PII, statistics, drivers, Excel, DuckDB, Sheets, HTML, export, compare, semantic types, linkage, time series, free text, ODCS, OpenLineage, schedules |
| S1 to S3, R1 | p7 cross-cutting packets | severity tier; reconcile excluded keys |
| v2 toolkit R1 to R6 | 2026-08-15-v2-toolkit-design | session-handle MCP tools |
