# crivo v2: the analyst with backed numbers (design)

2026-10-14. **Status: design approved section by section in conversation
(direction A, kernel-centric). This document is for owner review before any
slice spec or issue is written.**

Inputs: `docs/research/2026-10-14-repl-rlm-deep-dive.md`,
`docs/research/2026-10-14-owner-research-synthesis.md` (Aarmen's four reports:
RLMs, autoresearch, Jev, the Jul to Oct 2026 landscape), and the existing
plans. **This replaces the build order of `specs/2026-09-06-master-plan.md`
and keeps its rule: no capability ships ahead of the instrument that measures
it.** Remaining master-plan waves fold into the slices below (section 6).

## What

**The pitch.** crivo: numbers you can bet on. Point your agent at a CSV, a
parquet folder or a database. crivo works the data in a live Python kernel,
never by pasting it into a model's context. Every number comes back
**backed**: the code that produced it, the checks an independent referee ran,
and the rows it came from. When crivo cannot prove something it says so, or
asks. When it gets something right it remembers, as a tested skill any agent
can reuse and as a saved answer it re-checks when the data changes.

**Who it is for.** Developers and analysts who work through an agent (Claude
Code, Cursor, Codex) and need a number that holds: an analytics engineer
asked for net revenue retention from a Postgres database and a messy Stripe
export, who today gets a figure with no way to tell whether a join
double-counted, whether gross or net revenue was used, or whether "N/A" rows
vanished.

**Why it is different.** The labs now ship warehouse-first analysts (OpenAI
Data agent, Claude Dashboards); pandas-ai is dormant; nobody owns verified
repair, and a 2026-09 survey names "a missing verification-repair repository"
and "missing experience transfer" as open problems. crivo's claim is not that
it answers more questions. It is that the answers it calls backed are right,
and it publishes the rate at which that claim fails.

**What changed from v1.** v1 trusted a fix when the check that found the
problem went quiet. On the external `hospital` set that rule changed 2,305
cells, repaired 0 of 509 dirty cells, and reported 100% verified
(`bench/results/full.json`). v2 makes "backed" mean checked by a referee the
work cannot touch, on correctness signals, not only on the original alarm.

## The structure

| Layer | Job |
|---|---|
| **Kernel** (the workspace) | Data lives as variables. pandas, DuckDB SQL over files, database results, and crivo's own tools, all callable from code. Untrusted and expressive; holds no keys. |
| **Referee** (on the host) | Decides whether a fix or an answer is backed. Holds the baselines, the credentials and the ledger. Locked against the model and against any learning loop. |
| **System 2** | The reasoning model that drives the kernel: crivo's own, or the calling agent's over MCP. |
| **System 1** | Fast typed decisions behind one seam: labelling, routing, ambiguity spotting. Never grades, never admits, never counts. |
| **Memory** | Per-dataset contracts (meaning), skills (procedures), saved answers (results). Model-proposed entries are pending until a person confirms. |
| **Learning loop** | Offline autoresearch on the benchmark, aimed first at the referee itself. |

The kernel talks to the host through a typed bridge on the existing stdio
supervisor (Prime Agent's `host_request` pattern): kernel code asks, the host
validates, checks the budget, logs to the ledger, and replies or refuses with
a reason.

## 1. The referee

**Requirements**

- R1.1 The referee runs on the host. Baselines (row counts, per-column
  fingerprints, the revert copy) are computed and kept there. For in-memory
  frames the host pulls the data out (Arrow over the supervisor) and
  fingerprints it itself. For DuckDB and databases the host runs its own
  queries over its own read-only connection. Nothing the kernel stores can
  change a verdict.
- R1.2 The referee is one module whose content hash is recorded. When a
  learning loop runs, a hook denies the loop reads and writes to it, to the
  scorer, to the truth files and to held-out sets, and the hash is checked at
  every keep.
- R1.3 Checks by artifact:
  - **Cleaning fix:** the originating check clears; rows and untouched
    columns hold; **collateral** (cells changed that the finding did not
    flag count against the fix); **idempotency** (applying it twice equals
    once); **replay** (re-running from the raw source in a fresh kernel
    reproduces the result).
  - **Answer:** **grounding** (every number in the prose appears in the
    computed result); the model's executed assertions; replay; **contract
    conformance** (binding canonical choices were used); a **second path**
    for aggregates (the same number recomputed another way, e.g. DuckDB
    against pandas).
  - **SQL result:** **fan-out** (no join multiplied rows unexpectedly);
    **key uniqueness and null keys** on join columns; **grain** (one row per
    entity the question asks about); the second path.
- R1.4 Verdicts are **backed** (every applicable check ran and passed),
  **partly backed** (names each check that could not run, and why), or **not
  backed** (names the failing check; a fix reverts, an answer abstains). The
  card lists every check that ran.
- R1.5 The model's reply is cut at `</execute>` before it enters history, so
  invented observations never sit beside real ones.

**Cost to flag:** collateral needs detectors to report the cells (or rows,
for row-level diseases) they flagged, not only columns. That changes
`detect.py` (core).

## 2. The kernel and data access

**Requirements**

- R2.1 At startup the kernel gets a documented `crivo` toolbox that the
  prompt teaches: `read`, `profile`, `sql` (DuckDB over CSV and parquet),
  `db.query(name, sql)`, `diagnose`, `check`, `label` (section 4),
  `submit_fix`, `answer`, `save`.
- R2.2 Engines by size: pandas for frames that fit in memory; DuckDB for
  larger files and SQL-shaped work, kept lazy so the model works through
  queries; Polars frames accepted as input.
- R2.3 Databases (Postgres, Snowflake, BigQuery, S3): connections are
  configured once and their credentials live with the host, never in the
  kernel. `db.query` crosses the bridge; the host parses the SQL and refuses
  anything that writes (DDL, insert, update), with a read-only role as the
  second lock; applies a cost guard (estimated scan, row limit, timeout);
  runs it; returns the result as a kernel variable; logs the exact query to
  the ledger.
- R2.4 Pushdown by default: aggregation runs in the database and only results
  enter the kernel. Table profiles are computed with SQL, so the model sees
  schema and stats without rows moving.
- R2.5 Text-to-SQL is written from schema, stats and the contract, never from
  raw rows. `sqlglot` does the read-only check, dialect translation, and the
  query structure (joins, keys, grouping) the referee's SQL checks need.
- R2.6 Outputs go to new files, or to a scratch schema only when the user opts
  in. Sources are never overwritten.

Starting point in today's code: `readers/sql.py`. Touches the kernel
bootstrap, the supervisor protocol (a shared contract), and the prompt and
loop (core).

## 3. Dataset memory, clarify, abstain

**Requirements**

- R3.1 Each dataset gets a human-readable contract, `contracts/<dataset>.yaml`
  in the user's repo, matched by name plus a schema fingerprint
  (`fingerprint.py`). It holds column meaning, role, unit, allowed values or
  ranges; canonical choices; grain; keys, foreign keys and safe joins; known
  traps; and past clarification decisions with who and when.
- R3.2 Every entry records its source. Entries from a person or from a
  verified crivo check are **binding**. Entries the model proposes are
  **pending** until a person confirms. Only binding entries feed the referee's
  conformance check.
- R3.3 On first contact crivo drafts the contract from profiling, semantic
  types and its checks, all pending. It grows from clarifications and
  verified cleans, and a person can edit it directly.
- R3.4 **Clarify:** when a question maps to more than one plausible column or
  definition and no binding choice exists, the analyst asks one targeted
  multiple-choice question and writes the answer into the contract, so it is
  never asked twice. REPL: a prompt. MCP: the 2026-07-28 spec's request to the
  person. Headless: never asks; states the assumption and returns partly
  backed, or abstains.
- R3.5 **Abstain** is a first-class outcome with a stated reason. A correct
  abstention counts as a success in the referee and the benchmark.
- R3.6 Contracts hold meanings and rules, never rows. Allowed-value lists are
  kept only for low-sensitivity categories, never for PII-flagged columns.

Open: crivo's own YAML with an ODCS v3.1 export (master-plan B5.1), or ODCS
as the storage format. Decide in the slice 1 spec.

## 4. System 2, System 1, and `crivo.label`

**Requirements**

- R4.1 System 2 is pluggable through `llm.py`. Over MCP it is the calling
  agent, and crivo runs no second model. For crivo's own REPL the default is
  chosen by **cost per backed answer** on the benchmark. Candidates: Claude
  Haiku 5.5, DeepSeek V4.1 Flash, GPT-6.1 Sol, Sonnet 5.5; Opus 5.5 as the
  ceiling; a local Qwen3.8-27B. Prerequisites: fix the Claude path (current
  models reject `temperature`; 8,192 `max_tokens` truncates thinking), and
  record the model that actually served each call.
- R4.2 A fix that a cheap model wrote and the referee rejects escalates that
  finding to a stronger model.
- R4.3 System 1 sits behind one seam, `decide(state, questions)`, with
  providers in default order: deterministic rules; a local decision model
  (Laya or Kev 4B); Jev (opt-in); a constrained System 2 prompt. It may label,
  route a finding to a fixer or skill, pre-check whether code answers the
  question, and flag ambiguity. It may never grade, admit a skill, or decide
  anything numeric or date-ordered.
- R4.4 `crivo.label(series, labels | instruction)` is a managed operator, not
  free-form recursion. The host dedups to distinct values; screens for PII
  (refused, or local model only); gates the first use per column (column,
  distinct count, model, estimated cost); caches by value, instruction hash
  and model; validates every output; returns a column to the kernel. Only a
  summary (label counts) enters the model's context.
- R4.5 The model labels, code counts. Aggregation over labels happens in
  pandas or SQL.
- R4.6 The referee spot-checks labels (a sample re-labelled by a second model
  or a person; agreement on the card) and lineage records how many values
  which model labelled. Labels cannot call labels.

## 5. Skills, saved answers, and the learning loop

**Requirements**

- R5.1 Two skill kinds: **fix** skills (cleaning) and **recipe** skills
  (a verified analysis: parameterized code or SQL, its checks, and the
  contract entries it relies on).
- R5.2 A backed result proposes a skill with its frozen case. Admission keeps
  today's gates (trip and clear the frozen case, pass its own test, a person
  says yes) and adds a declared expected outcome.
- R5.3 **Rent is counterfactual:** a skill stays only while it beats the
  no-skill alternative on held-out cases of its kind, plus a probe that it
  does not hurt other variants. This replaces successes minus failures.
- R5.4 Skills export in the Agent Skills layout (frontmatter, `scripts/`,
  tests) and carry their own assertions, since they leave the referee behind.
- R5.5 `crivo.save(answer)` (and `/save`) stores a recipe: code or SQL,
  checks, contract version, data fingerprint, value.
- R5.6 `crivo verify` re-runs saved recipes and skills on current data and
  reports each as **still backed** (with the value change), **broken** (the
  failing check: contract violated, a join now fans out, grain changed) or
  **drifted** past a threshold. It runs on demand, in CI (the GitHub Action
  gains a `verify` mode with linter exit codes and JSON) or from the user's
  own scheduler.
- R5.7 A recurring question matched to a saved recipe (System 1 ranks) is
  answered from it, and the card says "answered from saved recipe R,
  re-checked now".
- R5.8 The learning loop is offline, at development time, on the benchmark,
  never on user data. Order: (1) red-team the referee and the scorer, each
  find becoming a regression test; (2) generate new dirt and question shapes,
  each novel and labelled plausible by a person before joining the corpus;
  (3) improve detectors and fixers one function per session, delivered as a
  branch for owner review; (4) nightly skill improvement behind held-out
  acceptance and a person's yes.
- R5.9 Loop locks: R1.2 isolation; held-out data split by kind of dirt, not
  seed; an append-only experiment log keyed by git commit plus corpus and
  scorer hashes; a noise floor over paired seeds; a jump alarm; a simplicity
  prior.

Day-to-day learning (skills and contracts growing in use) is governed by the
person. The offline loop improves crivo itself.

## 6. Measurement and build order

**The headline metric is the false-backed rate:** the share of fixes and
answers the referee called backed that are wrong against known truth. It is
published with the backed rate and the cost per backed answer. A rising backed
rate never excuses a rising false-backed rate.

Each slice is a full vertical slice and must pass its gate before the next
starts. Each gets its own short WRAP spec, then issues via `/new-task`, then
the `/start-task` pipeline. Core files stop for the owner.

| Slice | Builds | Acceptance gate |
|---|---|---|
| **0. Referee and honest scorer** | R1.1 to R1.5. Scorer: measured zeros score 0 (no silent `None`), degenerate-strategy invariants, the append-only experiment log, a held-out split by kind, the shared injector and fixer vocabulary removed | `hospital` reports its real zeros; no degenerate strategy (wipe a column, refuse all, drop the column) beats no-op on any published number; the reproduced baseline bypass is a red test, then green |
| **1. A backed answer over a file** | R2.1, R2.2, R2.5 for DuckDB, R2.6; R3.1 to R3.6; the referee's answer checks | A trap suite we build: competing revenue columns, stale flags, unlinked identities, unanswerable questions, on real datasets; plus a DABstep subset. False-backed rate near 0 |
| **2. Backed SQL over a database** | R2.3 to R2.5; the referee's SQL checks | Our own SQL trap suite on a seeded warehouse (fan-out, grain, wrong-key joins). Public text-to-SQL labels are 52 to 66% wrong, so no leaderboard is the gate |
| **3. Labelling at scale** | R4.3 to R4.6 | A tabular OOLONG suite (free-text column plus aggregate questions); the intent-check evaluation from the Jev report |
| **4. Learning** | R5.1 to R5.9 | Skills beat no-skill on held-out cases; `verify` catches planted breaks (duplicates, late records, retries); the red-team loop finds at least one lie or returns a clean bill |
| **5. The faces** | MCP on the 2026-07-28 spec (stateless; clarify and gates as requests to the person; tools over a session handle), a Claude Code plugin, Agent Skills export, PyPI | The `docs/QA.md` black-box suite run by an outside agent driving crivo; the demo story in `docs/PRD.md` |

R4.1 and R4.2 (model choice and escalation) run alongside slice 1, since the
benchmark that picks the default exists from slice 1 on.

**Master plan, folded in:** waves 2, 3 and 4 into slices 0 and 1; wave 9
(DuckDB) into slices 1 and 2; wave 12 into slices 1 (ODCS contracts, cost-per-task
columns), 4 (verified-answers memory, scheduled re-checks) and 5 (MCP port);
wave 13 (routing) into R4.2 and R4.3.

## Core-file impact

| Slice | Core files touched (each a reviewed diff) |
|---|---|
| 0 | `detect.py` (cell-level evidence), `loop.py` (verification via host, stop at `</execute>`) |
| 1 | `loop.py`, `prompts.py` (toolbox, clarify, abstain), `card.py` (verdicts, checks list) |
| 2 | `prompts.py` (SQL), `card.py` |
| 3 | `llm.py` (`decide` seam), `prompts.py` |
| 4 | `skills.py`, `library.py` (recipes, rent, export), `provenance.py` (saved answers) |
| 5 | none required; `mcp_server.py` and the API contract change (owner's yes on the contract) |

## Later, not dropped

A real sandbox by default (Docker is not usable on the owner's Mac; candidates
are microVM `sbx` or a Python sandbox), a per-task dollar cap, a live trace
view, and the statistics toolkit (master-plan wave 8). Each becomes its own
slice when wanted.

## Open questions, for the slice specs

1. Second path: does the model write the alternative computation, or does the
   referee derive one (e.g. translate the pandas aggregate to DuckDB)? Slice 1.
2. Replay cost on large DuckDB or database work: full replay, or replay on a
   sample with fingerprints. Slice 1.
3. Collateral for row-level diseases (duplicates, stray rows): flagged rows
   instead of cells. Slice 0.
4. Contract format: crivo YAML plus ODCS export, or ODCS native. Slice 1.
5. Which real datasets carry the trap suite: the owner's `Data sets` folder,
   AQI, the Raha sets, CITBench. Slice 1.
6. The local decision model on a RAM-constrained Mac: a 4B model is plausible,
   27B is not. Slice 3.
7. MCP HTTP transport timing relative to stdio. Slice 5.
