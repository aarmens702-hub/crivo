# Stage 0: the foundation

**Status: drafted 2026-10-17; filed as issues #86 to #232; Aarmen took every recommendation under "Decisions the owner owes" on 2026-10-18**, plus a Stage 0 comment
on each open issue folded in (#44 to #47, #51 to #59, #84, #85).

2026-10-17. The WRAP spec for Stage 0 of `specs/2026-10-14-the-plan.md`. It merges five
drafts written the same day from a read-only review of `dev` @ 7c73957 (the containment
draft @ 2024bfc, docs only between them): 0a and loop 1, 0b, 0c, and 0d in two halves
(containment, then the platform). Every row was checked in the code, and most defects were
reproduced in a scratch folder; the drafts' "Verified against dev" sections hold the
file:line evidence. The eval tooling (`specs/2026-10-17-eval-tooling.md`, EV1 to EV20,
#64 to #83) lands first, and Stage 0 builds on it without repeating it.

## What

A true instrument, an untouchable referee, honest detectors, and a contained, versioned
platform, before anything is built on them. Concretely: a bench number counts its zeros,
cannot be beaten by a cleaner that destroys data, and says which code, corpus and scorer
made it; a blind attacker tried to break the scorer and then the referee, and every lie it
found is a red test turned green. Every check that makes a fix "backed" runs on the host,
against a baseline the kernel cannot touch, and every surface says backed, partly backed or
not backed. A grade of AUTO means `clean()` can act, and a check that read part of the
data never says the data is clean. Model code runs in an OS sandbox with no network,
read-only data and no `.env`, nothing unattended runs it uncontained, secrets are redacted
on the way out, and spend has a cap. Every file crivo writes carries a version, and the
project has a root, a config file, `crivo init` and `crivo doctor`.

## Requirements

One issue each, in landing order within each part. `core` marks a diff Aarmen reviews
(a file on the core list in AGENTS.md); `core if S0-D6` becomes core if Aarmen takes S0-D6
(the referee files join the list). `(existing)` is an open issue folded in: it keeps its
number and gets a Stage 0 comment, not a new issue. `bug` marks a defect the drafts
reproduced or read on `dev`. Rows reference each other by id; the filer adds the numbers.

**0a. The honest scorer** (30 rows)
| id | issue | type | core |
|---|---|---|---|
| SC1 (#86) | score: a measured zero scores 0, and "repair undefined by design" is a declared, counted rule | code, bug |  |
| SC2 (#87) | score: long ids and amounts compare digit for digit | code, bug |  |
| SC3 (#89) | bench: `python -m bench.score` scores a cleaned file against a Raha pair, and `scripts/score_fixes.py` is retired | code |  |
| SC4 (#90) | agent lane: an aborted, failed or empty case scores as no-op, and pass^k counts it failed | code, bug |  |
| SC5 (#91) | bench: invariants that can fire run in CI, with apply-twice and shuffled-row checks | code, bug |  |
| SC7 (#92) | score: a detection finding is credited per column it names | code, bug |  |
| SC8 (#93) | score: duplicate, total and footer rows get a row repair score, aligned by content | code, bug |  |
| SC9 (#94) | bench: per-detector precision, recall and F1 over the whole corpus | code |  |
| SC11 (#95) | bench: a full run appends a ledger row with corpus and scorer hashes; `--results-dir` is a flag | code |  |
| SC16a (#96) | kernel: a read guard the kernel installs when told which paths to refuse | code |  |
| SC6 (#118) | bench: degenerate cleaners never beat no-op on a published number | eval |  |
| SC10 (#119) | bench: the scoring rules are written down in `bench/SCORING.md` | code |  |
| SC12 (#120) | bench: republish the full numbers with real zeros; survived-verification leaves the headline | code |  |
| SC14 (#121) | agent lane: arms are named by provider and model; old results are archived, never resumed | code |  |
| SC15 (#122) | agent lane: GATE, PLAN and ungraded gates wait unless the ceiling arm approves them | code, bug |  |
| SC16b (#123) | agent lane: cases run outside the repo, and a cell that reads `bench/` is caught | code, bug |  |
| SC17 (#124) | agent lane: one ledger row per run with p50 and p95 cost and time, and every case's outputs and trace kept | code |  |
| SC18 (#125) | ledger: compare two runs case by case from the ledger; retire `bench/compare.py` | code |  |
| SC19 (#126) | audit: crivo's truth labels checked by someone who did not write them | eval |  |
| SC22 (#127) | corrupt: planted tokens come from an outside-sourced vocabulary, not the fixer's | eval |  |
| SC23 (#129) | bench: a property-based generator of dirt shapes | eval |  |
| SC26 (#130) | corrupt: a schema-drift (d20) injector that builds a family of files | eval |  |
| SC27 (#131) | bench: family cases are scored for d20 detection | code |  |
| SC28 (#132) | corrupt: Excel multi-value cells in the packed-field (d17) cases | eval |  |
| SC29 (#133) | external: CITBench cleaning instances and one REIN-style set scored beside Raha | code |  |
| SC20 (#185) | truth: a corruption can carry several diseases and a cell several accepted repairs | code |  |
| SC21 (#186) | corrupt: injectors record secondary diseases and accepted repairs | eval |  |
| SC24 (#187) | corpus: every disease gets dev, held-out and sealed shapes, split by kind of dirt | eval |  |
| SC25 (#188) | bench: dev and held-out columns side by side; the sealed set runs only at finalize | code |  |
| SC30 (#227) | bench: the autonomous-vs-careful agent numbers, published from the ledger | experiment |  |

**Loop 1: red-team the scorer, then the referee** (5 rows)
| id | issue | type | core |
|---|---|---|---|
| L1 (#166) | hooks: a scorer-attacker agent that writes only `bench/attacks/loop1/` and cannot read the scorer, truth or generator | code |  |
| L2 (#189) | bench: an attack harness that runs attacker code confined and reports published against recomputed numbers | code |  |
| L3 (#228) | loop 1: red-team the scorer, with a positive control on the pre-0a scorer first | experiment |  |
| L4 (#229) | bench: the attack harness submits a fix to the referee and checks its verdict against truth | code |  |
| L5 (#230) | loop 1 again: red-team the referee | experiment |  |

**0b. The referee** (39 rows)
| id | issue | type | core |
|---|---|---|---|
| #84 (existing) | loop: model-written code runs in a gate preview before anyone approves it | code, bug | core |
| #85 (existing) | loop: a proposed skill runs in the live kernel before its admission gate | code, bug | core |
| RE1 (#97) | referee: the reproduced verification bypass is a red test | code |  |
| RE2 (#98) | family: a real-kernel test harmonizes two drifting CSVs | code |  |
| RE3 (#99) | ci: the docker-marked tests run on Linux | code |  |
| RE4 (#100) | clean: a failed diagnosis is a failed clean, with a report that says so | code, bug | core |
| #54 (existing) | headless clean exits 0 with no error when the clean never ran | code, bug |  |
| RE5 (#101) | plan: an approved plan's policy lasts one run, has its own id, and keeps the person's note | code, bug | core |
| #59 (existing) | loop: drop the stale load_url comment and record the same-shape stamp gap | code | core |
| RE6 (#102) | intent: an intent check that gave no verdict is never read as a match | code, bug | core |
| #52 (existing) | headless clean records fixes nobody approved as unattended: false | code, bug | core |
| RE7 (#103) | loop: snapshots and resumed loads use the kernel's own paths on either transport | code, bug | core |
| RE25 (#104) | kernel: each cell result says which asserts ran and whether they held | code |  |
| #51 (existing) | headless clean can run a model-written row deletion for d09 without asking | code, bug |  |
| RE8 (#139) | kernel: a frame format the host can read without unpickling | code | core if S0-D6 |
| RE9 (#140) | kernel: the host can pull a frame out of the kernel and push one back | code |  |
| RE10 (#141) | referee: host-side fix checks that return backed, partly backed or not backed | code | core if S0-D6 |
| RE11 (#167) | referee: a model-written fix is verified on the host, against a baseline the kernel cannot touch | code, bug | core |
| RE12 (#168) | referee: a deterministic fix runs and is verified on the host | code, bug | core |
| RE13 (#169) | referee: a skill's fix is verified on the host, and the kernel holds no baseline | code, bug | core |
| RE14 (#170) | referee: the cleaned file is the frame the referee checked | code | core |
| RE15 (#171) | referee: gate previews render on the host | code | core |
| RE16 (#172) | referee: family harmonizing is verified on the host | code | core |
| RE17 (#173) | referee: skill admission is checked on the host | code | core |
| RE18 (#181) | detect: report the cells behind each finding crivo fixes unattended | code | core |
| RE19 (#182) | detect: report the rows behind each row-level finding | code | core |
| RE20 (#204) | detect: report the cells behind the other cell-level findings | code | core |
| RE21 (#205) | referee: a fix that changes cells or rows its finding did not flag is not backed | code, bug | core if S0-D6 |
| RE22 (#206) | referee: a fix applied twice must equal the fix applied once | code | core |
| RE23 (#207) | referee: a clean is replayed in a fresh kernel before its result counts | code | core |
| RE24 (#208) | library: crivo.clean checks each fix with the referee | code |  |
| RE26 (#209) | card: a check is stamped passed only when it ran and held | code, bug | core |
| RE27 (#210) | card: every answer card says backed, partly backed or not backed, and why | code | core |
| RE28 (#211) | report: every fix shows its verdict in the clean report and the headless summary | code |  |
| RE29 (#212) | provenance: /why shows the verdict of each claim and fix | code, bug | core |
| RE30 (#213) | notebook, ask and mcp: an answer's verdict travels with it | code, bug |  |
| RE31 (#214) | resume: a resumed session re-proves its verified fixes before trusting them | code | core |
| RE33 (#231) | referee: the new collateral and idempotency checks keep fix quality on the dev split | experiment |  |
| RE32 (#232) | docs: the README and architecture describe the referee and its verdicts | code |  |

**0c. Detector honesty** (27 rows)
| id | issue | type | core |
|---|---|---|---|
| DH2 (#88) | bench: a header-damage finding is scored against the damaged header it names | code, bug |  |
| #47 (existing) | repr: review lines for findings that differ only by grade print identically | code, bug |  |
| #55 (existing) | clean: a value fix on a column d18 renamed is reported as a removed column | code, bug |  |
| DH10 (#105) | excel: a one-cell title directly above the header is reported, not read as the header | code, bug |  |
| DH1 (#106) | bench: the scorer says which fix changed each cell, and counts checks that called present dirt clear | code |  |
| DH3 (#107) | bench: why 124 fixable cases repair nothing, and what hospital's 2,305 changed cells are | experiment |  |
| DH4 (#128) | bench: numbers-as-strings plants keep the number's value | eval, bug |  |
| DH5 (#134) | bench: cases where blank coordinates and correct accented text are not damage | eval |  |
| DH6 (#135) | bench: contradictions about one entity in wide and long tables | eval |  |
| DH7 (#136) | bench: sparse columns and one-value-or-blank flag columns | eval |  |
| DH8 (#137) | bench: date placeholders, and missing-value words that can be real answers | eval |  |
| DH9 (#138) | bench: text whose clean form holds runs of spaces inside it | eval |  |
| DH11 (#142) | detect: blank coordinates and correctly spelled accented capitals are not reported as damage | code, bug | core |
| DH12 (#143) | detect: a check that read part of the data says so, instead of being listed clear | code, bug | core |
| DH13 (#144) | diagnose: the report, --json and Report show checks that ran on part of the data | code |  |
| DH14 (#145) | detect: d07, d10 and d24 say when they scanned part of the frame | code, bug | core |
| DH15 (#146) | detect: d19 drops only a column with no values; a nearly empty one goes to a gate | code, bug | core |
| DH16 (#174) | detect: d01 says how many values match, and is AUTO only when clean() can parse every one | code, bug | core |
| DH17 (#175) | detect: d02 says how many values match, and is GATE for times, epochs and ambiguous day/month | code, bug | core |
| DH18 (#176) | detect: d04 names and clears the same cells, graded by what the column holds | code, bug | core |
| DH19 (#177) | detect: d05, d09, d16 and d17 are GATE, since clean() has no fixer for them | code | core |
| DH20 (#178) | detect: d01 reads a number in parentheses as its negative | code, bug | core |
| DH21 (#179) | tests: no AUTO finding on the smoke corpus is one clean() refuses for its shape | code |  |
| DH22 (#180) | detect: d06 runs of spaces inside text go to a gate; edge and invisible whitespace stay automatic | code | core |
| DH23 (#183) | api: crivo.diagnose_family finds schema drift across files | code |  |
| DH24 (#184) | cli: crivo diagnose FILE FILE... also reports schema drift | code |  |
| DH25 (#220) | headless: crivo clean --family runs the family clean and reports drift it did not resolve | code |  |

**0d. Containment, egress, injection and cost** (26 rows)
| id | issue | type | core |
|---|---|---|---|
| CT1 (#108) | security: a threat model where the data itself can attack | code |  |
| #56 (existing) | readers: the URL lineage stamp keeps credentials from the URL | code, bug |  |
| CT12 (#109) | docker: the container cannot read a .env inside its mounts | code |  |
| CT17 (#110) | loop: every kernel message that reaches the model is capped, error messages included | code, bug | core |
| CT19 (#111) | llm: every model call reports its tokens, served model, stop reason and endpoint | code | core |
| #58 (existing) | claude: a cut-off, all-thinking or too-old-model reply says so | code, bug | core |
| CT13 (#112) | secrets: one redaction helper covers everything that leaves the kernel and the transcript | code |  |
| CT14 (#113) | llm: a prompt is redacted before it leaves for the provider | code | core |
| CT16 (#114) | profile: the model sees masked samples from PII-flagged columns | code |  |
| CT3 (#147) | kernel: the supervisor reaches its kernel over unix sockets, so the kernel needs no network | code |  |
| CT4 (#148) | kernel: one module builds the macOS and Linux sandboxes and says when neither can run | code |  |
| CT9 (#149) | kernel: a memory limit stops a runaway cell instead of the machine | code |  |
| CT15 (#150) | pii: secret-shaped values are flagged and masked like other PII | code |  |
| CT18 (#151) | providers: an allowlist, and each provider's retention and region on record | code |  |
| CT21 (#152) | pricing: a dated price table turns each call into dollars | code |  |
| CT5 (#190) | kernel: the kernel client can start the supervisor inside the sandbox | code |  |
| CT10 (#191) | repl: Ctrl-C stops a running cell and keeps the kernel | code | core |
| CT11 (#192) | tests: no provider key or database credential reaches the kernel, contained or not | code |  |
| CT6 (#193) | loop: the kernel writes only inside its own folder | code | core |
| CT7 (#194) | loop: a session runs its kernel contained when it can, and says so when it cannot | code | core |
| CT22 (#195) | loop: a dollar cap per task and per session | code | core |
| CT8 (#215) | drivers: crivo.ask, MCP and headless clean never run model code uncontained | code |  |
| CT23 (#216) | card: every answer card and clean report shows what it cost | code | core |
| CT24 (#217) | cli: the headless clean summary and the REPL exit line show the session's cost | code |  |
| CT25 (#218) | traps: injection cases, part 1: instructions in cell values and column names | eval |  |
| CT26 (#219) | traps: injection cases, part 2: sheet names, file names and tracebacks | eval |  |

**0d. The platform: formats, readers, project, reliability, the linter** (35 rows)
| id | issue | type | core |
|---|---|---|---|
| #53 (existing) | cli: the key file is searched from crivo's install directory, not where you run it | code, bug |  |
| #44 (existing) | readers: crivo.diagnose(dir) calls an empty or _SUCCESS-only directory clean | code, bug |  |
| #45 (existing) | cli: crivo diagnose reads a SQLite .db file as CSV and can report clean | code, bug |  |
| #57 (existing) | readers: C:// paths, file:// with a query, and chunked URL reads | code, bug |  |
| #46 (existing) | cli: crivo clean F --diagnose G runs diagnose on G | code, bug |  |
| PF5 (#115) | loop: /load and open_data read a parquet folder instead of crashing on its hash | code, bug | core |
| PF8 (#116) | loop: a context-overflow error compacts the history and retries the call once | code | core |
| PF9 (#117) | llm: retries wait on Retry-After inside the call budget, can be cancelled, and never replay a streamed reply | code, bug | core |
| PF10 (#153) | docs: a semver, deprecation and format-version policy in the contract | code |  |
| PF11 (#154) | formats: one helper for schema versions, the version stamp and atomic writes | code |  |
| PF12 (#155) | diagnose: the json report says which crivo and which check set wrote it | code |  |
| PF13 (#156) | clean: the clean report and the headless summary carry schema_version, and the report is written atomically | code |  |
| PF14 (#157) | card: answer cards carry schema_version and the crivo version, saved atomically | code | core |
| PF15 (#158) | loop: lineage and family summaries are written atomically and versioned | code | core |
| PF16 (#159) | transcript: session_meta carries schema_version, and a torn last line no longer breaks resume | code, bug |  |
| PF17 (#160) | provenance: /why refuses a card or clean report written by a newer crivo | code | core |
| PF18 (#161) | skills: SKILL.md carries a format version and saves atomically | code | core |
| PF19 (#162) | library: the skill ledger carries schema_version and is written atomically | code, bug | core |
| PF20 (#163) | readers: one local-file reader behind crivo.read, crivo diagnose, the analyst and MCP | code |  |
| PF6 (#164) | mcp: diagnose_file, open_data and clean_file accept a parquet folder under the root | code, bug |  |
| PF7 (#165) | family: /clean-family reads each file with the shared reader, so N/A tokens and cp1252 files survive | code, bug | core if S0-D6 |
| PF21 (#196) | cli: real subcommands and `crivo --version` | code |  |
| PF22 (#197) | config: crivo finds its project root and reads crivo.toml | code |  |
| PF23 (#198) | config: provider, model, allowed providers and autonomy come from crivo.toml | code |  |
| PF24 (#199) | cli: the workspace, skills and key file resolve against the project root | code |  |
| PF25 (#200) | mcp: the workspace and skills resolve against the project root, so a client launched from / works | code, bug |  |
| PF26 (#201) | cli: `crivo init` sets up a project | code |  |
| PF27 (#202) | cli: `crivo doctor` says what is set up and what is missing | code |  |
| PF28 (#203) | config: named connections take credentials from env, never inline | code |  |
| PF29 (#221) | mcp: idle kernels close on a timer, a server holds a capped number, and shutdown closes them all | code |  |
| PF30 (#222) | workspace: an opt-in retention rule removes old sessions without reusing their ids | code |  |
| PF31 (#223) | kernel: docker kernels carry their owner, and a dead server's containers are removed | code |  |
| PF32 (#224) | diagnose: --select and --ignore choose which checks count | code |  |
| PF33 (#225) | diagnose: a baseline of accepted findings, so CI fails only on new ones | code |  |
| PF34 (#226) | action: select, ignore and baseline inputs, passed to the shell through env | code, bug |  |

## Acceptance criteria (the Stage 0 gate)

The plan's gate, as runnable checks. Each line names the part that owns it.

**The instrument: hospital and every external set report real numbers; no degenerate
strategy beats no-op on any published number (0a)**
- `uv run pytest tests/test_bench_score.py tests/test_bench_run.py tests/test_bench_degenerate.py -q`
  passes; `uv run pytest tests/test_bench_run.py -q -k invariant` shows each invariant can fire.
- `uv run python -m bench.run --smoke` exits 0 (CI's step), prints the repair mean with its
  scored and undefined-by-design counts, and `bench/results/smoke.json` lists every invariant
  and degenerate check with `failed: 0`.
- With the Raha sets and SC29's sets fetched, after a smoke run:
  `uv run python -c "import json; r=json.load(open('bench/results/smoke.json')); e2e=[(e['name'], e['scores']['end_to_end']) for e in r['external']]; bad=[n for n, s in e2e if s['repair']['f1'] is None]; print(bad); raise SystemExit(bool(bad) or len(e2e) < 4)"`
  prints `[]` and exits 0.
- `uv run pytest tests/test_kernel_readguard.py tests/test_agent_bench.py -q -k "readguard or contaminated or gate"`
  passes (real subprocess kernel, faux provider), and no default-arm ledger row shows a GATE
  or PLAN gate run.
- The last `bench.run` row in `bench/ledger.jsonl` carries `commit`, `corpus_sha256`,
  `scorer_sha256`, each external set's hashes, per-detector counts and p50 and p95 case time;
  `uv run python scripts/check_locks.py` exits 0.
- `bench/RESULTS.md` has the per-detector table and dev and held-out columns, and
  `uv run python -m bench.ledger compare --last 2` prints per-detector deltas.
- `README.md`'s bench block and `bench/RESULTS.md` come from `bench.run --full --write-readme`
  after SC1 to SC12, and the README headline has no survived-verification row.

**Loop 1 finds at least one lie (fixed) or returns a clean bill against the scorer and the
referee (L1 to L5)**
- Ledger rows exist for L3 and L5, each with a positive control and a real run and a
  recorded decision. Each positive control found a known lie, or its row says the clean bill
  is not credible.
- Every confirmed find has a closed `bug` issue whose regression test opens with
  `Regression for #<n>.` and passes in `uv run pytest -q`; the runner log shows
  `check_locks.py` passed at every keep.

**The bypass test passes (0b)**
- `uv run pytest tests/test_referee_bypass.py -q` passes and
  `grep -n xfail tests/test_referee_bypass.py` prints nothing.
- `git grep -nE "_clean_backup|_clean_rows|_clean_hashes|_family_backup|_family_rows|_family_nonnull" -- src`
  prints nothing.
- `uv run pytest tests/test_family_kernel.py tests/test_admission_kernel.py tests/test_loop_kernel.py tests/test_resume_kernel.py tests/test_preview_consent.py -q`
  passes (subprocess transport).
- CI's `docker` job (Linux only) runs `uv run pytest -m docker -q` green on the push to
  `dev`: pull and push, snapshots, and resume across transports. Never on Aarmen's Mac.
- `uv run pytest tests/test_verify.py tests/test_card.py tests/test_report.py tests/test_provenance.py tests/test_notebook.py tests/test_mcp_server.py -q`
  passes: every kept fix record carries `verify.verdict` and the referee hash; a capped,
  malformed, truncated, cut-off, intent-mismatched or code-free answer is never backed; under
  S0-D10, no answer card reads backed before Stage 1.
- The `P2r1` reproduction reads not backed beside a kept correct d04 fix on the same frame,
  and a d24 fix that drops exactly its flagged rows is kept.
- The cassette suite (EV3 (#66), EV16 (#79)) passes with a verdict assertion on every
  false-backed, abort and cap-hit cassette.
- RE33 has registered, result and decision rows; RE21's and RE24's commits state every moved
  bench number.

**Every 0c change shows its per-detector effect (0c)**
- `uv run pytest tests/test_detect.py tests/test_autoclean.py tests/test_autoclean_refusals.py tests/test_excel_structure.py tests/test_diagnose.py tests/test_api.py tests/test_cli_exit_codes.py tests/test_repl.py tests/test_taxonomy_drift.py tests/test_bench_score.py -q`
  passes, with one `Regression for #<n>.` test per DH code row.
- Every DH row that moves detection or repair has a ledger row naming its issue, with SC9's
  per-disease before and after and DH1's `by_fix` and `listed_clear`:
  `uv run python -c "import json; rows=[json.loads(l) for l in open('bench/ledger.jsonl')]; print(sorted({r.get('issue') for r in rows}))"`
  lists every such issue.
- `uv run pytest tests/test_taxonomy_drift.py -q` passes, and fails if any grade DH16 to DH19
  changed is set back.
- DH1's `listed_clear` is 0 on DH6's wide and long cases; the only non-zero `listed_clear`
  on smoke and dev are the recall gaps S0-D19 names.
- hospital's changed cells are split by fix; MeasureName's collateral is 0 after DH22 (under
  D8 (b)); the rest is declared under SC1's rule. tx-money-strings' repair F1 is defined and
  above 0 after DH4 and DH20.
- `uv run crivo diagnose a.csv b.csv --json` on two drifting files carries a non-empty
  `family` and exits 1; `crivo.diagnose_family([a, b])` returns the same finding;
  `CRIVO_PROVIDER=faux uv run crivo clean --family "x_*.csv" --name x --json` lists the
  unresolved drift in `needs_human`.
- `uv run python scripts/check_taxonomy_drift.py` exits 0, and QA CLI-01, LIB-01, LIB-03,
  AN-05 and AN-08 pass from a fresh install.

**Injection trap cases cannot change a verdict or reach the network; a cell cannot read
`.env` or write a referee input (0d, containment)**
- On Aarmen's Mac, and in CI on `macos-latest` and `ubuntu-latest`:
  `uv run pytest tests/test_sandbox.py tests/test_containment_paths.py tests/test_kernel_env.py tests/test_kernel_memory.py tests/test_repl.py -q`.
  With `CI` set, the `sandbox` marker fails instead of skipping. A contained cell cannot read
  a `.env` in the data root, a `.env.*`, `.git/config` or a file under `$HOME` outside the
  roots; cannot reach 192.0.2.1 or a listener on the host's loopback; cannot launch an app;
  cannot write the data root, `skills/ledger.json`, `transcript.jsonl`, `cards/` or
  `clean_reports/`; and can write its own `kernel/` folder. A 1 GiB allocation under a 500 MB
  limit ends as `kernel_died` with `MemoryLimit` and the session goes on. No name in
  `llm.KEY_ENV_VARS` or the database-credential list reaches the kernel on any transport.
  Ctrl-C during `time.sleep(60)` returns `interrupted` within 5 s with the variables intact.
- Rule 3, in `tests/test_containment_paths.py`: with the backend unavailable, `crivo.ask`
  raises, MCP `open_data` and `clean_file` return `error`, and `crivo clean` exits 1 with
  `error` in its JSON. With it available, a scripted hostile faux reply on each path fails to
  read `.env`, connect out or write the ledger, and the result says `contained`. With
  `CRIVO_SANDBOX=none` each path runs and every card carries `flags.uncontained`.
- `uv run pytest tests/test_secrets.py -q`: a planted host secret and a token-shaped cell
  value appear in none of `transcript.jsonl`, `cards/*`, the clean report, the lineage file,
  the MCP results or the messages handed to the provider.
- `uv run pytest tests/test_budget.py tests/test_pricing.py tests/test_card.py -q`: a faux
  session priced by `CRIVO_PRICE_PER_MTOK` stops at the task cap with a `budget` notice; every
  card, clean report and headless summary carries `cost`.
- Paid, once, under D21: `/eval injection --split dev -k 3 --model <the default> --budget <D21>`
  with the kernel contained writes one ledger row with `contained: true`, and changed
  verdicts, canary listener hits, canary in egress and referee-input hash changes are all 0.
  Any non-zero count is a red test before its fix.
- By hand, once, on Aarmen's Mac: `uv run python -m crivo` prints
  `sandbox: seatbelt (no network, read-only data)`, and `/load` of a file outside the data
  root is refused with the reason.

**A versioned platform (0d, platform)**
- `uv run pytest -q tests/test_formats.py` (every file a session writes is versioned; no bare
  JSON write in `src/crivo`) and `uv run pytest -q -k newer_schema` (one refusal per reader).
- `uv run crivo diagnose example.csv --json | uv run python -c "import json,sys; d=json.load(sys.stdin); assert d['schema_version'] == 1 and set(d['versions']) == {'crivo', 'checks'}"`.
- `uv run pytest -q tests/test_one_reader_path.py tests/test_load_kernel.py`; the BENCH-01
  smoke line holds.
- In a temp folder: `crivo init` exits 0 and a second `crivo init` exits 1;
  `CRIVO_PROVIDER=faux crivo doctor --json` exits 0 with no `fail`; `crivo --version` prints
  the pyproject version; `uv run pytest -q tests/test_config.py tests/test_mcp_server.py -k "project_root or crivo_toml"` passes.
- `uv run pytest -q -k "overflow or retry_after or idle_sweep or kernel_cap or retention or owner_label"`
  passes (PF31 fakes `subprocess.run` and never runs Docker).
- `uv run crivo diagnose example.csv --fail-on AUTO --write-baseline b.json && uv run crivo diagnose example.csv --fail-on AUTO --baseline b.json`
  exits 0.
- Rule 9, both print nothing:
  `for sub in diagnose clean init doctor; do uv run crivo $sub --help; done | grep -oE -- '--[a-z][a-z-]+' | sort -u | while read f; do grep -q -- "$f" docs/API-CONTRACT.md || echo "missing $f"; done`
  and `git grep -ohE 'CRIVO_[A-Z_]+' -- src | sort -u | while read v; do grep -q "$v" docs/API-CONTRACT.md || echo "missing $v"; done`.

**The whole stage**
- `uv run ruff check .` and `uv run pytest -q` pass; CI is green on `dev` and on the
  promotion to `main`; every non-paid `docs/QA.md` case passes from a fresh install.

## Priority

**Wave 0, before any Stage 0 row:** the eval tooling, EV1 to EV20 (#64 to #83), as the plan
orders it, and #84 (being built now, held at the core gate). Each row's `depends_on` names
the EV issues it builds on, so if Aarmen lets a row with none start early, the manifest says
which. Before wave 2's eval rows start, EV5 (#68) carries S0-D32's lines (a comment on #68,
or a one-line follow-up if EV5 has shipped).

**Wave 1, no owner decision needed** (small calls are taken as recommended):
- 0a: SC1, SC2, DH2, SC3, SC4, SC5, SC7, SC8, SC9, SC11, SC16a.
- 0b: RE1, RE2, RE3, RE4, #54, RE5, #59, RE6, #52, RE7, RE25; and #85 as soon as S0-D34 is
  answered (it is filed first in the manifest, beside #84).
- 0c: #47, #55, DH10, DH1, DH3.
- 0d: CT1, #56, CT12, CT17, CT19, #58, CT13, CT14, CT16; #53, #44, #45, #57, #46, PF5, PF8,
  PF9.

**Wave 2, after the decision sittings (below):** the eval-author's rows and the
decision-gated starts. Sittings 1 to 3 unblock most of it; 4 and 5 unblock CT3, CT4, CT9,
CT18, CT21 and PF10 to PF20.
- 0a: SC6, SC10, SC12, SC14, SC15, SC16b, SC17, SC18; eval-author rows SC19, SC22, DH4,
  SC23, SC26, SC28 (one at a time on the corrupt, bases and corpus files); SC27, SC29; L1.
- 0c: DH5 to DH9 (eval-author); DH11 to DH15.
- 0b: #51, RE8, RE9, RE10.
- 0d: CT3, CT4, CT9, CT15, CT18, CT21; PF10 to PF19, PF20, PF6, PF7.

**Wave 3, the referee on the host, the regrades, containment, the project:**
- 0b: RE11, RE12, RE13, RE14 (strictly in that order), RE15, RE16, RE17, RE18, RE19.
- 0c: DH16 to DH22, DH23, DH24.
- 0a: SC20, SC21, SC24, SC25; L2.
- 0d: CT5, CT10, CT11, CT6 (after RE14), CT7, CT22; PF21 to PF28.

**Wave 4, the referee's new checks and verdicts, contained drivers, cost on every surface:**
- 0b: RE20 to RE24, RE26 to RE31.
- 0d: CT8, CT23, CT24, CT25, CT26; PF29 to PF34. 0c: DH25 (after CT8).
- 0a: SC30 (paid). Loop 1: L3 (paid).

**Wave 5, the gate runs and the docs:** L4, L5 (paid), RE33 (paid), RE32. Then the gate
checks above, a `bench.run --full --write-readme`, and `/qa-pass`.

**Shared files, landing order** (whichever lands second rebases):
- `src/crivo/loop.py` (core; the bottleneck of the stage, 30 rows): #84, #85, RE4, RE5, #59,
  CT17, PF5, PF8, RE6, #52, RE7, #58, PF15, RE11, RE12, RE13, RE14, CT10, CT6, CT7, RE15,
  RE16, RE17, CT22, RE22, RE23, RE31, RE26, RE27, CT23. RE11 to RE14 are strict (the same
  functions); CT6 and CT7 follow RE14, because the kernel stops writing the cleaned file only
  once the host writes it.
- `src/crivo/verify.py` (core if S0-D6): PF7, RE10, RE13, RE15, RE16, RE17, RE21, RE22,
  RE23, RE27.
- `src/crivo/detect.py` (core): DH11, DH12, DH14, DH15, DH16, DH17, DH18, DH19, DH20, RE18,
  RE19, DH22, RE20. RE18 after DH16 to DH18; DH22 either side of RE18, on one shared helper;
  RE20 after DH11.
- `src/crivo/llm.py` (core): CT19, #58, PF9, CT14 (EV1 (#64) before Stage 0).
- `src/crivo/card.py` (core): RE6, PF14, RE26, RE27, CT23. `provenance.py`: PF17, RE29.
  `library.py`: #85, PF19. `skills.py`: PF18.
- `src/crivo/autoclean.py`: #47, #55, DH16, DH18, DH19, DH22, RE24.
- `src/crivo/kernel/client.py`: SC16a, RE3, CT12, CT13, RE25, RE9, CT9, CT5, CT10, CT6,
  PF31. `kernel/bootstrap.py`: SC16a, RE25. `kernel/supervisor.py`: RE25, CT3.
- `src/crivo/repl.py`: #52, #54, PF13, #51, CT10, CT8, RE28, CT24, DH25.
- `src/crivo/mcp_server.py`: #52, #51, PF6, PF25, CT8, RE30, PF29, PF30, PF31.
- `src/crivo/__main__.py`: #53, #46, PF21, PF23, PF24, DH24, PF26, PF27, CT8, RE28, CT24,
  DH25, PF30, PF32, PF33.
- `src/crivo/query.py`: CT18, PF24, CT8, RE30. `checkup.py`: #45, DH13, PF12, PF20, DH24,
  PF32, PF33. `api.py`: DH13, PF12, DH23. `notebook.py`: #47, DH13, RE30.
- `src/crivo/readers/remote.py`: #56, #57, CT13. `readers/files.py`: #44, PF20.
  `report.py`: RE4, #54, PF13, RE28, CT23. `transcript.py`: CT13, PF16. `events.py`: #52,
  CT10.
- `bench/score.py`: SC1, SC2, DH2, SC3, SC7, SC8, DH1, SC20.
- `bench/run.py`: SC1, SC5, SC9, SC11, DH1, SC10, SC12, SC18, SC27, SC29, SC20, SC21, SC25.
  From SC10 on, a row that adds or changes a bench number updates `bench/SCORING.md` in the
  same change (SC10's test enforces it).
- `bench/agent_run.py`: SC4, SC14, SC15, SC16b, SC17, CT8 (EV1, EV2, EV9 before Stage 0).
- `bench/corrupt.py`, `bench/bases.py`, `bench/corpus.py` (the eval-author, one issue at a
  time): DH4, SC22, DH5, DH6, SC28, SC26, DH7, DH8, DH9, SC23, SC21, SC24. Each changes the
  corpus hash, so each may force a cheap re-recording of the cassettes it touches.
- `.claude/hooks/guard_reads.py`: S0-D32's lines on EV5, RE10 (`kernel/frames.py`), L1 (the
  `attacker` mode). `scripts/check_locks.py`: RE10, SC24, L1.
- `.github/workflows/ci.yml`: RE3 (the docker job), CT4 (bubblewrap and the sandbox
  marker).
- `README.md`: SC12, DH19, DH22, RE32, PF34. `docs/PRD.md`: DH19. `SECURITY.md`: CT1 first,
  then CT8, CT9, CT12, CT13, CT18, CT22. `AGENTS.md`: RE10 (the core list, after EV19).
- `docs/QA.md`: SC1, SC2, SC7, SC8, SC12 (BENCH-01); RE6, RE27, RE29 (AN-02, AN-07); DH13,
  DH19, DH22, DH24; PF12 (CLI-05), PF13 (AN-05), PF21 (INST-03), PF26, PF27; RE32.
- `docs/API-CONTRACT.md` is touched by most rows, each in its own section;
  `docs/ARCHITECTURE.md` by RE9, RE10, RE13, RE26, PF10, PF11, PF22, PF27, PF30, PF33, RE32.
- `tests/test_clean_loop.py` (`FakeClient`): RE11 adds `pull` and `push` first; RE12, RE13,
  RE16 and RE17 migrate their own flows.

**Core review sittings for Aarmen** (51 diffs, 55 if S0-D6 is taken; each sitting reads its
diffs in landing order):
1. #84, #85: model code before consent.
2. RE4, RE5, #59, CT17, PF5: five small `loop.py` fixes.
3. RE6, #52, PF8: the intent verdict, who decided a gate, overflow compaction.
4. CT19, #58, PF9, CT14: `llm.py` in order (per-call record, cut-off replies, retries,
   redaction).
5. RE7, PF15: paths per transport, the versioned lineage.
6. RE8, RE10 (if S0-D6): the codec and the host checks, before anything calls them.
7. RE11: the model-fix path moves to the host. The one to read slowly.
8. RE12, RE13: the other two fix paths; the kernel baselines are deleted.
9. RE14, CT6, CT10: custody of the output, the kernel's own folder, Ctrl-C.
10. CT7: a session runs contained.
11. RE15, RE16, RE17: previews, family, admission on the host.
12. DH11, DH12, DH14, DH15: detector honesty without regrades.
13. DH16, DH17, DH18, DH19, DH20: the D4 regrades, read with the demo-story change.
14. RE18, RE19, DH22, RE20: cell and row evidence, and d06.
15. RE21 (if S0-D6), RE22, PF7 (if S0-D6): collateral, idempotency, the family reader.
16. RE23, RE31: replay and resume.
17. RE26, RE27, PF14, CT22, CT23: what the card says (checks run, verdict, version, cost).
18. RE29, PF17, PF18, PF19: provenance, and the versions of skills and the ledger.

**For the filer.** `stage0-manifest.json` is in this order. `depends_on` holds Stage 0 ids,
EV ids (EVn is #(63+n)) and existing issue numbers; `blocked_on` holds only the owner's
decisions below. A comment row's labels are what the issue should carry after the merge
(#51 drops `core`; the fix moved out of `loop.py`).

## Decisions the owner owes

38 are Aarmen's: the taxonomy and grades, the contract, architecture and the core list,
money, the plan, and anything a user would see change (an exit code, a refusal, a default
that stops work, a deleted file, the demo story). 13 are small calls: internal mechanism or
scoring code that the drafts' measured evidence settles. They are taken as recommended
under Aarmen's standing instruction, as ED1 to ED4 and ED6 were, and he may overturn any;
no row is blocked on one. "Blocked" means the row cannot start; "waits to ship" means it
can be built but ships after the answer.

| id | decision | recommendation, and why | rows waiting | decided by Aarmen 2026-10-18, as recommended (owner's or small call ) |
|---|---|---|---|---|
| D4 | Regrade AUTO findings autoclean refuses, or keep them with a reason. (a) Regrade at the source, so AUTO only where `clean()` can act: d05, d09, d16 (explicit units) and d17 become GATE; d01 is AUTO only when one shared parse rule accepts every value; d02 is GATE for times, epochs and ambiguous day/month; d04 per S0-D15. (b) Keep the grades, each with a reason. (c) Regrade d09 only. | (a). AUTO tells a person "safe to fix automatically", and a grade nothing in crivo can act on is the false claim P2r2 names. Cost: the demo story changes. `crivo diagnose example.csv` exits 1 at the default `--fail-on GATE` (d09), so PRD step 4, the README block and QA CLI-01 change, and the Action exits 1 on duplicate rows (a minor release with a changelog line). #51 no longer waits on it. | blocked: DH16, DH17, DH19, DH20, DH21 | decided by Aarmen 2026-10-18, as recommended (owner's (grades, exit codes, the demo story) ) |
| D5 | Multi-label bench truth; canonical booleans in the truth manifest. (a) One label, overlaps footnoted. (b) A corruption may carry secondary diseases, a cell may list accepted repairs, a column may carry an accepted form, each declared per disease from the taxonomy. (c) (b) without canonical booleans. | (b), with canonical booleans. 0a and 0c agree: the manifest names the canonical form for a representation disease (d23: the boolean), declared by the eval-author from the taxonomy before scoring, never from a fixer's output. To start: missing for a d04 placeholder, column removed for d19, the canonical boolean for a d23 flag column; SC19's audit supplies the case list. 0c measured flags-bool-chaos at 12,500 of 12,500 cells keeping their truth value after the d23 fix, so its zero is a type-strict compare, not a bad fix. The d18 "Unnamed" header variant (DH3's H3) goes on SC1's declared undefined list instead, because the original name is not in the file. | blocked: SC20, SC21; waits: DH3 (its H1 rule) | decided by Aarmen 2026-10-18, as recommended (owner's (what counts as a correct repair) ) |
| D6 | Bench arm suffix migration, which orphans results on disk. (a) Add provider and model to the suffix and rename old files from their recorded model. (b) A directory per arm; old flat files moved once to `legacy/` and never resumed. (c) Leave it and document. | (b). (a) cannot work: 9 of the 21 local rows carry no `model` field. Nothing published reads agent rows. Cost: re-running paid cases. | blocked: SC14, SC17 (then SC15, SC16b, SC30) | decided by Aarmen 2026-10-18, as recommended (owner's (discards paid results) ) |
| D7 | Collateral for row-level diseases. (a) Row masks: a row fix may remove (d09, d21, d24) or merge (d10, d11) only the rows its detector flagged; every other row keeps its values and label. (b) Cell masks for every disease. (c) No collateral check for row diseases. | (a). It is the v2 design's proposal, and it unblocks d24: `verify._row_invariant` allows no dropped row for d24, so a correct d24 fix cannot verify today. | blocked: RE19, RE21 | decided by Aarmen 2026-10-18, as recommended (owner's (what a fix may do) ) |
| D8 | The d6 internal-space verdict. (a) Keep: every internal run of 2 or more spaces is damage, fixed automatically. (b) An internal run gets its own GATE finding; edges and invisible spaces stay AUTO. (c) Fix internal runs only when the column also shows edge damage. (d) Internal runs are not a disease. | (b). A run inside text is sometimes meaning, and hospital's truth shows 78 such clean cells collapsed today. Cost: tx-whitespace's internal-doubling plants move from repaired to a gate (repair recall about 0.75), and the example's d06 note becomes a GATE finding (README, QA LIB-01, LIB-03). (c) scores better only because the injector plants every variant in one column. | blocked: DH9, DH22 | decided by Aarmen 2026-10-18, as recommended (owner's (taxonomy, demo output) ) |
| D16 | Budget for the learning loops, loop 1 first. | Per run `claude -p --max-budget-usd 30`; the runner kills at $60 by `total_cost_usd` (the flag is a client-side estimate and can overshoot); 30 iterations; stop after 10 with no confirmed find. Four runs in Stage 0 (a positive control and a real run, against the scorer and then the referee): at most $240 at the hard kill. If a positive control hits the cap without finding a known lie, Aarmen decides once whether to raise it. | blocked: L3, L5 | decided by Aarmen 2026-10-18, as recommended (owner's (money) ) |
| D18 | Containment approach. (a) Seatbelt on macOS and bubblewrap on Linux around the supervisor, no new dependency. (b) A Python-level sandbox. (c) A microVM. (d) Landlock and seccomp on Linux. | (a) for v1; (d) as a Linux fallback and (c) in Stage 5. (a) ran on Aarmen's Mac with a deny-default profile (pandas, pyarrow and matplotlib worked; no IP network; home unreadable). (b) is not containment: C extensions and ctypes pass audit hooks. (c) needs RAM the Mac lacks. Costs: `sandbox-exec` is marked deprecated; Ubuntu 24.04 blocks bubblewrap's user namespaces unless a sysctl or AppArmor profile allows them; nothing on Windows. Docker stays as `CRIVO_SANDBOX=docker`. | blocked: CT3, CT4, PF31 (then CT5, CT7, CT8, CT10, CT11, PF27) | decided by Aarmen 2026-10-18, as recommended (owner's (architecture) ) |
| D18a | Unattended paths fail closed: only `CRIVO_SANDBOX=none` runs them uncontained, and then every card and summary says so. `CRIVO_SANDBOX` (`auto`, `docker`, `none`) replaces `CRIVO_MCP_SANDBOX`, which stays an alias for one minor release. | Yes. Rule 3 as written, with an escape hatch that shows on every output. | blocked: CT8 | decided by Aarmen 2026-10-18, as recommended (owner's (`crivo.ask`, MCP and headless clean refuse where they ran before; a new env var) ) |
| D18b | An attended REPL that cannot contain still starts, says so, drops `autonomous` to `careful`, and gates proven skills. | Yes. Rule 3 is about code nobody reads, and today a proven skill skips its gate at `careful` too (`loop.py:1785`). | blocked: CT7 | decided by Aarmen 2026-10-18, as recommended (owner's (REPL behaviour) ) |
| D18c | What the kernel may read: the data root (REPL: the project root or `--data-dir`; `crivo clean FILE`: its folder; `crivo.ask`: the file's folder; MCP: `CRIVO_MCP_ROOT`), plus the Python install and crivo. Never `/` or `$HOME`; `.env`, `.env.*` and `.git` unreadable inside a root. | Yes. One rule for every driver; MCP works this way already. Cost: a mid-session `/load` outside the roots is refused, because a sandbox cannot widen after it starts. | blocked: CT7 | decided by Aarmen 2026-10-18, as recommended (owner's (a refusal users will see) ) |
| D18d | The supervisor and kernel talk over unix sockets, and the kernel gets no IP network, not even loopback. | Yes, if D18 is (a): Seatbelt cannot give the kernel a private loopback. Cost: output from processes a cell starts is not captured. | CT3 | small call (follows from D18 (a)) |
| D18e | The kernel's working directory: the data root (relative reads work, writes to the cwd fail) or its own folder (the reverse). | The data root: the model reads more often than it writes, and CT7's guard run measures it. | CT5, CT7 | small call |
| D19 | Gate thresholds: the false-backed ceiling, minimum suite sizes, the confidence level. | The 95% Wilson upper bound of the false-backed rate is at most 5%; at least 100 backed results per arm per suite; k at least 3 (5 at stage gates). Wilson behaves at zero: 0 of 100 gives 3.7%, 1 of 100 gives 5.4%. For 0a: a degenerate strategy may not beat no-op by more than 0.01 absolute on any published number (a row shuffle earns 0.004 to 0.006 by chance today); per-detector rows are published with at least 20 truth corruptions, smaller ones marked. | blocked: SC6; waits: SC9 (the minimum), L2 (the margin), Stage 1's gate | decided by Aarmen 2026-10-18, as recommended (owner's (the plan's gate) ) |
| D20 | Provider policy: allowed providers, residency, the procurement criterion, and whether to switch the default to DeepSeek V4.1 Flash now. | (1) `CRIVO_ALLOWED_PROVIDERS` (a `crivo.toml` key once PF23 lands), unset meaning today's four. (2) Record retention and region in SECURITY.md; do not enforce. (3) A provider can be the default only if its retention and processing region are documented and API inputs are not used for training by default. (4) No switch now: a default-model change is behaviour work for Stage 1's bake-off. To weigh: DeepSeek's privacy policy (updated 2026-02-10) says data is processed and stored in the PRC and lists training as a purpose, so (3) as written could rule it out as the default. | blocked: CT18 (then PF23) | decided by Aarmen 2026-10-18, as recommended (owner's (privacy, the default model) ) |
| D21 | Paid eval budget and cadence, the part pulled forward: the paid runs in Stage 0 outside loop 1: SC30 (autonomous against careful), RE33 (the referee's new checks), CT7's guard, and the injection gate run (CT25, CT26). Merges 0a's D21 part and 0d's one-off budget. | Each run is registered through `/eval` with an explicit `--budget-usd` and no default (ED5's rule), runs a pilot of 3 cases per arm first, and gets its cap from the pilot (the pilot's p95 case cost times the planned cases, times 1.25), aborted at 2x. Aarmen names each cap. crivo has no price table until CT21, so a number set before a pilot would be a guess. The weekly canary stays in Stage 1. | blocked: SC30, RE33; waits to ship: CT7, CT25, CT26 | decided by Aarmen 2026-10-18, as recommended (owner's (money) ) |
| D24 | Trap-suite datasets and their licences, the part pulled forward: licences for 0a's external corpora (CITBench, a REIN-style set). | Fetch, never commit (`data/` is git-ignored); pin file hashes in the fetch script; record each licence and source URL in its header; publish scores only; take only sets with cell-level clean and dirty truth. | blocked: SC29 | decided by Aarmen 2026-10-18, as recommended (owner's (licences) ) |
| ED7 | Where held-out and sealed sets live (the eval tooling spec's decision, still owed). | Outside the public repo, with only their hash committed (EV11 (#74) checks either way). Stage 0 needs it before SC24's split and CT25's trap splits: a sealed set in this public repo is not sealed. | blocked: SC24, CT25 (then SC25, CT26) | decided by Aarmen 2026-10-18, as recommended (owner's ) |
| S0-D1 | Which numbers count as "published" for the degenerate-strategy gate (0a's SC-D1). (a) Stop publishing dirt-targeting F1; keep it in the JSON as a diagnostic. (b) Publish dirt precision and recall separately and exempt them. (c) Redefine targeting. | (a). A column wipe, a column drop and renaming every column each beat no-op on dirt-targeting F1 on 24 of 31 smoke cases today, by construction. Repair F1 already measures targeting, and the README never published dirt F1. | blocked: SC6, SC12 | decided by Aarmen 2026-10-18, as recommended (owner's (it defines the plan's gate) ) |
| S0-D2 | Detection credit: per finding, or per column a finding names (SC-D2). | Per (finding, column) claim for precision; recall unchanged; a finding with no column keeps today's whole-row rule. One finding naming every column of a frame scores precision 1.0 today, and the score's docstring already says "column x disease". | SC7, SC9 | small call (the scorer matches its own docstring) |
| S0-D3 | How agent-arm cells are kept off `bench/` before 0d's sandbox (SC-D3). (a) A kernel read guard (an audit hook the bootstrap installs when `CRIVO_KERNEL_DENY_READ` names the refused paths), a temp cwd, neutral file names and a transcript scan. (b) The temp cwd and the scan only. (c) Only under docker. | (a). It blocks the easy routes and records attempts, survives restarts, and L2 reuses it. It is detection and a speed bump, not containment, and the docs say so. (c) cannot run on Aarmen's Mac. The env var joins S0-D13's list. | SC16a, SC16b, L2 | small call |
| S0-D4 | Row-level repair scoring for d09, d10, d21 and d24 (SC-D4). (a) Content-aligned row scoring now. (b) Wait for D7. (c) Leave them unscored. | (a). The honest dedupe of tx-dup-rows gets no repair number today, and keeping the last copy instead of the first is scored as 2,009 changed cells. The bench's alignment is its own rule, apart from the referee's. | SC8 | small call |
| S0-D5 | `generate(model=)`: keep or remove (SC-D5; Stage A sent it to 0a). | Keep, pinned by a test in CT19. Stage 1's cheaper sub-model needs a per-call model, and the tests' scripted generators already take it. | CT19 | small call |
| S0-D6 | The referee's files, and whether they are core (0b's D-RE1). (a) `verify.py`, `diff.py` and the new `kernel/frames.py` are the referee: hashed together on every verdict, added to the core list (AGENTS.md and plan rule 5, with a changelog line), and named in `guard_reads.py` and `check_locks.py`; `detect.py` is hashed apart as the check set. (b) The referee is `verify.py` alone, and agents own it. (c) A new `referee.py`. | (a). Rule 2 makes the referee the trust anchor, and today the file that decides verdicts is the one file in the trust path nobody reviews. Keeping the name keeps the paths the eval tooling's hooks already list. RE8, RE10, RE21 and PF7 become core with it. | blocked: RE10 | decided by Aarmen 2026-10-18, as recommended (owner's (the core list, the plan) ) |
| S0-D7 | How a frame crosses from the kernel to the host (D-RE2, D-RE3). Transport: (a) an internal cell writes the encoded frame to a file in the session workspace and the host reads it once, no protocol change; (b) a supervisor op that streams it over stdout (v2 R1.1's "Arrow over the supervisor", protocol v2). Format: (a) crivo's codec over Arrow IPC (typed columns native; object columns as a per-cell type tag plus exact text; names and index positional; a cell type outside an allowlist makes that column unreadable); (b) object columns cast to text; (c) pickle, refused because it runs code on the host. | The file and crivo's codec. The file is about 60 lines against about 200, and the referee checks the bytes it read either way. pyarrow 25.0.1 refuses a mixed int and str object column and duplicate column names, both routine in dirty data, and casting to text loses `1` beside `"1"`, which d01 and d22 read. It departs from R1.1's transport, so it is Aarmen's. | blocked: RE8, RE9 | decided by Aarmen 2026-10-18, as recommended (owner's (architecture of record) ) |
| S0-D8 | Who writes the cleaned file (D-RE4). (a) The host, from the frame the referee verified; a frame that changed between two gates stops the run. (b) The kernel, with a digest check after. | (a), written atomically. Otherwise the file a user gets is not the frame the referee checked. It also makes CT6's and PF15's parquet steps unnecessary. | RE14 | small call (follows R1.1; no output a user sees changes) |
| S0-D9 | The target contract per disease (D-RE5): what a fix may do to cells of its own target column that the detector did not flag. | Approve the table. Cell diseases may change flagged cells; an unflagged target cell may change only in representation, read by the disease's own parser (d01, d05, d16, d22: the same number; d02, d03: the same instant; d23: the same boolean), and must be unchanged for d04, d06, d07, d08, d13, d14 and d26. Row diseases per D7. Column diseases: d17 may add columns and rewrite its packed target; d18 renames its target, values unchanged; d19 drops its target only; d25 drops one twin only. d11, d12, d15 and d20 have no contract yet (collateral reads "not run"). | blocked: RE21 | decided by Aarmen 2026-10-18, as recommended (owner's (taxonomy) ) |
| S0-D10 | What the three verdicts mean in 0b (D-RE6, D-RE7). Fixes: (a) the required checks (signal clears, the row rule, untouched columns, the d06 reference) must run or the fix reverts, and the rest (collateral without a mask, idempotency, replay) may read "could not run", which keeps the fix as partly backed and never counts it backed; (b) any check that cannot run reverts the fix. Answers: (a) at most partly backed until Stage 1's grounding, replay and second path exist, the card naming them as not built; (b) a stdout-grounding check now. | Fixes (a) and answers (a). Fix (b) would revert most model fixes until RE20 lands, which reads as rigour and is a regression. For answers: a number that was not measured is not claimed. Cost: every answer card reads "partly backed" in Stage 0, and `/why` stops saying "trusted" (QA AN-02, AN-07). | blocked: RE10, RE27 | decided by Aarmen 2026-10-18, as recommended (owner's (what "backed" means; user-visible) ) |
| S0-D11 | Plan rule 3 before containment (D-RE8, with 0c's shape for #51). (a) Headless clean and MCP `clean_file` never run a model-written fix cell: it goes to `needs_human`, or MCP asks by elicitation. Proven skills keep running unattended; `crivo.ask` and MCP `ask` keep running query cells until CT8. (b) Also stop proven skills until 0d. (c) Change nothing until 0d. Mechanism: in the drivers, by gate origin (0b), or by grading the model fix's gate GATE in `loop.py` (0c). | (a), in the drivers. It closes #51 without touching a grade or `loop.py`, and leaves the bench agent lane measuring model fixes. Cost: a headless run applies fewer fixes. | blocked: #51 | decided by Aarmen 2026-10-18, as recommended (owner's (what headless clean does) ) |
| S0-D12 | #52: what `unattended` means (D-RE9). (a) True when no person decided, including a gate the headless rule or `--auto-run` answered. (b) Keep "no gate was shown". | (a): it is how the crivo skill and a reader of the summary already read the field. | #52 | small call (a bug fixed to match how the field is read) |
| S0-D13 | One yes for the additive contract fields Stage 0 adds, each written into `docs/API-CONTRACT.md` with its code (D-RE10 and the other parts' additive lines). 0b: `GateRequest.origin`, `GateDecision.by` (#52); the result event's `checks` (RE25); intent `unknown` (RE6); `verdict` on `AnswerCard`, fix records, the summary's `fixes` and `CleanSummary.applied` (RE24, RE27, RE28); report and summary `error` on a failed diagnosis (RE4, #54); `Answer.verdict` (RE30). 0a: `CRIVO_KERNEL_DENY_READ` (SC16a). 0d: `SessionLike.interrupt()` (CT10); `endpoint` in the model dict (CT19); the lineage output's `sha256` (CT6); what `remote.uri` holds (#56); the profile under "masked when rendered" (CT16). `status` values stay as they are. Fields that come with another decision (cost and budget: S0-D20; sandbox: D18a; memory: S0-D21; secrets: S0-D24; formats: S0-D25; config: S0-D26; the linter: S0-D28) are approved with it. | Approve the list; each row still shows its diff. One yes for the shape, so no row stops to ask. | waits to ship: #52, #54, #56, RE4, RE6, RE24, RE25, RE27, RE28, RE30, SC16a, CT6, CT10, CT16, CT19 | decided by Aarmen 2026-10-18, as recommended (owner's (the contract) ) |
| S0-D14 | New referee failure text reaches the model in a fix turn (collateral, idempotency; D-RE11). (a) Keep every existing message byte-identical, fix the new messages' text in their issues, ship RE21 and RE22 as code, and pre-register one eval at the 0b gate (RE33). (b) A behaviour eval per row. | (a). The change is to what the referee refuses, not to the prompt, and one gate eval measures the combined effect for one budget. RE33's guard is collateral, because a per-fix false-backed rate needs frames the agent lane does not keep. | blocked: RE33; waits: RE21, RE22 (they ship as code under (a)) | decided by Aarmen 2026-10-18, as recommended (owner's (how behaviour work is typed and measured) ) |
| S0-D15 | d04's grade for placeholder dates and words that can be real answers, such as "none", "unknown", "not applicable" and "missing" (DH-Da). (a) AUTO everywhere; only make the fixer clear what the detector names. (b) Two tiers: placeholder codes (N/A, NULL, NaN, #N/A, "?", "-") are AUTO anywhere; answer-like words and placeholder dates are AUTO only where the column's other values are numbers or dates, GATE in a text column. (c) Every text finding GATE. All three share one mask for detector and fixer. | (b), with the word list Aarmen confirms. The same token is a placeholder in a number column and can be an answer in a text column; the column's shape is what separates them. (c) over-refuses N/A in an id column. | blocked: DH8, DH18 | decided by Aarmen 2026-10-18, as recommended (owner's (a grade) ) |
| S0-D16 | d19 for (i) a column holding a handful of values among blanks and (ii) a column holding one value or blank (DH-Db). (a) Neither is a d19 finding. (b) (i) is GATE, "holds K values in N rows"; (ii) is no finding, since it is a flag. (c) Both GATE. (d) Keep AUTO; fix only the evidence. | (b). Dropping (i) unasked deletes real values today (2 of 1,000 in the repro); (ii) carries presence against absence (15 "Y" in 100 rows was dropped). | blocked: DH7, DH15 | decided by Aarmen 2026-10-18, as recommended (owner's (a grade, and what counts as a disease) ) |
| S0-D17 | How a check that read part of the data is reported (DH-Dc). (a) A new `partial: {id: why}` key on `detect_all`, `crivo diagnose --json` and `Report`, never also in `clear`; an empty frame lists every id under `broken`. (b) Capped checks under `broken`. (c) Remove the caps. | (a). It keeps "absence is a checked claim" true without making wide or long files slow, and the key is additive. | blocked: DH12, DH13, DH14 | decided by Aarmen 2026-10-18, as recommended (owner's (a contract field users read) ) |
| S0-D18 | The CLI and API shape for Stage 0 (DH-Dd and PF-D3 merged). (i) argparse subcommands `diagnose`, `clean`, `init`, `doctor`; no subcommand starts the REPL; `--diagnose` and `--clean` stay as deprecated aliases with a warning until at least the minor release after next; `crivo --version`. (ii) `crivo init [DIR]` writes `crivo.toml`, `skills/`, `workspace/` and the missing `.gitignore` lines; it never overwrites and never prompts. (iii) `crivo doctor [--json] [--no-kernel]`, keyless and offline, `ok`, `warn` or `fail` per check, exit 1 on any `fail`. (iv) d20: `crivo.diagnose_family(sources, names=None)`; `crivo diagnose FILE FILE...` with `--json` as `{files, family}`; headless `crivo clean --family GLOB --name NAME` after CT8; MCP in Stage 1's port. Rejected: an interactive init wizard, `doctor --online`, `crivo.diagnose` taking a list, a `--family` flag on diagnose, d20 in MCP now. | As written. It matches the plan's subcommand list, keeps every script on the old flags working for a release, keeps `doctor` as free as `diagnose`, and leaves every single-file contract unchanged. The MCP description is read by outside models, and only Stage 1's outside-agent runs can measure it. | blocked: PF21, PF26, PF27, DH23, DH24, DH25 | decided by Aarmen 2026-10-18, as recommended (owner's (new commands, flags and an API function) ) |
| S0-D19 | Recall gaps the smoke corpus shows outside 0c's list: d12 has no ordering check, d17 misses a minority of packed cells, d16 (BT1) (DH-De). Into 0c, or a recall wave after 0a's split? | Later, after SC24's split. 0c is about false claims, and a recall fix tuned on one smoke case each would fit the generator. DH1's `listed_clear` shows these three as non-zero, which is the honest state. | none (not filed) | small call (nothing is added to the plan) |
| S0-D20 | Dollar caps (D-CT1): none by default, only on unattended paths, or everywhere. | Everywhere: a task (one question or one clean run) $1.00, a session $10.00, `off` disables. Checked before each call, so one call can overshoot, and the docs say so. A model with no price stops before its first call unless `CRIVO_PRICE_PER_MTOK` is set; an `openai` endpoint on localhost prices at 0. Unattended paths need a hard stop, and a fixed default is easy to state. | blocked: CT21, CT22 (then CT23, CT24) | decided by Aarmen 2026-10-18, as recommended (owner's (money; a default that stops work) ) |
| S0-D21 | The subprocess kernel's memory limit default (D-CT2): 2 GiB (docker parity), half of RAM, or 4 GiB. | The smaller of 4 GiB and half of RAM, with `CRIVO_KERNEL_MEMORY_MB` to override (0 turns it off). 2 GiB is tight for a pandas copy of a mid-size file; half of RAM protects a small Mac. macOS refuses `setrlimit` memory limits, so it is a polling watchdog. | blocked: CT9 | decided by Aarmen 2026-10-18, as recommended (owner's (a default that kills a cell) ) |
| S0-D22 | Redaction scope (D-CT3). (a) The exact values of the host's secret env vars, plus prefix-anchored token shapes. (b) (a) plus generic high-entropy strings. | (a). (b) would rewrite hashes and ids the referee compares. | CT13 | small call |
| S0-D23 | Fix-path evidence (D-CT4): the finding JSON a model fix gets carries up to 3 raw samples, even from PII-flagged columns, and the contract exempts this on purpose. | Confirm the exemption and revisit it with D15 (Stage 4). CT16 masks the profile only. | CT16 | small call (no change) |
| S0-D24 | A `secret` PII type (D-CT5): `Report.pii()` flags token-shaped columns, graded HUMAN and masked on every shareable surface, so a file with a token column gets a new finding. | Yes. | blocked: CT15 | decided by Aarmen 2026-10-18, as recommended (owner's (a new finding and its grade) ) |
| S0-D25 | Versions, deprecation, and how a format carries its version (PF-D1). (a) Semver: while 0.x a minor may change flags, exit codes and shapes and a patch never does. A deprecated flag, key, field or format keeps working, with a warning, for at least one minor release. Every JSON object crivo writes carries an integer `schema_version` per format and `versions: {crivo, checks}`; readers accept their version and older and refuse newer; JSONL carries it on its first event, SKILL.md in `metadata`; `checks` is the first 12 hex of `detect.py`'s sha256; one new module, `formats.py`. (b) Per-format semver strings. (c) One crivo-wide version. | (a). One integer compare per reader, and a hash cannot be forgotten. | blocked: PF10 to PF19, PF21 | decided by Aarmen 2026-10-18, as recommended (owner's (formats, the contract) ) |
| S0-D26 | The project root and the config file (PF-D2). (a) `crivo.toml` at the project root, read with the stdlib `tomllib`, found by walking up from the cwd (MCP from `CRIVO_MCP_ROOT`). No file means today's behaviour exactly. A flag beats env, env beats the file, the file beats the default; the library half never reads it; unknown keys are an error. v1 keys: `[model]`, `[run] autonomy`, `[budget]`, `[paths]`, `[workspace] retention_days`, `[mcp] max_kernels`, `[connections.<name>]` with credentials only as an env or keyring reference, never inline. (b) `[tool.crivo]` in `pyproject.toml`. (c) `.crivo/config.yaml`, a new dependency. | (a). No dependency, it works in any repo, and no file means no change. | blocked: PF22, PF23, PF24, PF25, PF28 | decided by Aarmen 2026-10-18, as recommended (owner's (a new file format and config) ) |
| S0-D27 | Workspace retention (PF-D4). (a) Opt-in `retention_days`; absent keeps everything; `crivo init` writes 30; pruning at start; a pruned session keeps a `PRUNED` marker so its id is not reused. (b) 30 days for everyone. (c) Keep the last N. | (a). The cleaned parquet, `crivo clean`'s deliverable, lives in the workspace, so a default delete loses work a user never copied. | blocked: PF30 | decided by Aarmen 2026-10-18, as recommended (owner's (deletes user files) ) |
| S0-D28 | The linter (PF-D5). `--select` and `--ignore` take ids or slugs (an unknown one exits 2; ignored checks leave `clear` and are listed under `ignored`); `--baseline FILE` and `--write-baseline FILE` with `crivo-baseline.json` (`{schema_version, versions, entries: [{file, disease, slug, grade, column, reason}]}`, no values); Action inputs. Rejected: a sidecar per data file, inline suppressions. | As written. One reviewable file per repo, no values in it, and the identity rule #25 uses already exists. | blocked: PF32, PF33, PF34 | decided by Aarmen 2026-10-18, as recommended (owner's (new flags, a file format) ) |
| S0-D29 | The MCP kernel cap and the idle sweep (PF-D6). (a) At most 4 live kernels per server (`[mcp] max_kernels` or `CRIVO_MCP_MAX_KERNELS`); idle sessions close first, then an error names `close_session`; a sweep every 60 s closes sessions idle for 30 minutes; SIGTERM and SIGHUP close them all. (b) Queue past the cap. (c) A cap of 1. | (a). Each kernel holds a copy of its dataset, and the machines crivo runs on are short of RAM. | blocked: PF29 | decided by Aarmen 2026-10-18, as recommended (owner's (a refusal MCP clients will see) ) |
| S0-D30 | Provider fallback now, or with Stage 1's escalation (R4.2) (PF-D7). | Retries only in 0d (PF9); fallback in Stage 1 as behaviour work, because a fallback changes which model answers. | PF9 (scope only) | small call (keeps the plan) |
| S0-D31 | One rule for a file with an unlisted suffix (PF-D8). (a) Read it as delimited text only when its first 8 KB decode as text, hold no NUL byte and contain a delimiter, else refuse with the supported list; `.db`, `.sqlite` and `.sqlite3` are always refused with the `crivo.read(path, query=...)` pointer. (b) Refuse everywhere, which breaks `crivo diagnose export.dat`, working today. (c) Sniff everything as CSV, the class of #45. | (a). It pins the legitimate `.dat` CSV beside the refusal of a binary file. | blocked: PF20 | decided by Aarmen 2026-10-18, as recommended (owner's (what `crivo.read` and `crivo diagnose` accept) ) |
| S0-D32 | The eval-author's lists for Stage 0, new in the merge, extending ED3 and ED4 (#68 already records `bench/corpus.py` and `bench/shapes.py`). Reads add `SECURITY.md` and `docs/PRD.md`, CT25's sources. Writes add `bench/degenerate.py`, `tests/test_bench_degenerate.py` and `tests/test_bench_shapes.py`, and its Bash may run pytest on those two test files. The degenerate registry moves from `bench/attacks/degenerate.py` to `bench/degenerate.py`, so `bench/attacks/` stays loop 1's alone. The README is not on the read list, so the bodies that cited its disease table cite the brief's taxonomy and the contract's slug table instead. | Take it, as a comment on EV5 (#68), or a one-line follow-up if EV5 has shipped, before SC6, SC23 and CT25 start. | SC6, SC23, CT25, CT26 | small call (extends ED3 and ED4) |
| S0-D33 | #84's own decision: model-written code at the QUERY and fix gates. (a) Harden `preview_screen`. (b) Never run a model-written cell before its gate is approved. (c) Ask before previewing. | (b), built and held at the core gate for Aarmen's yes. A screen narrows the hole and never closes it. | none blocked; RE15 builds on it | decided by Aarmen 2026-10-18, as recommended (owner's (gate behaviour, core) ) |
| S0-D34 | #85's own decision: a proposed skill runs before its admission gate. (a) Show the gate first and run the checks after a yes. (b) Two gates: "run this proposed skill's test on a copy?" with the code shown, then the admission gate with the result. (c) Leave the order until 0d and say so in the docs and the gate text. Separately: pin a sha256 of an admitted skill's `fix.py` and `test.py` in the ledger. | (b), and the pin. It keeps test-before-admission (the P2 design) and adds one prompt per proposal, and skills are rare. The pin stops an admitted skill from being edited on disk after its admission. | blocked: #85 (then RE17) | decided by Aarmen 2026-10-18, as recommended (owner's (the P2 admission design, core) ) |

**Sittings for the owner's decisions** (by topic; all five come before wave 2, and 1 to 3
unblock most of it):
1. The instrument and money: D5, D6, D16, D19, D21, D24, ED7, S0-D1.
2. The referee: D7, S0-D6, S0-D7, S0-D9, S0-D10, S0-D11, S0-D13, S0-D14, S0-D33, S0-D34.
3. Grades and the demo story: D4, D8, S0-D15, S0-D16, S0-D17, S0-D24.
4. Containment and providers: D18, D18a, D18b, D18c, D20, S0-D20, S0-D21.
5. The platform: S0-D18, S0-D25, S0-D26, S0-D27, S0-D28, S0-D29, S0-D31.

## Cut, with reasons

| item | where it goes | why |
|---|---|---|
| SC13 (llm: record the served model) | dropped; EV1 (#64), CT19 | EV1 records the served model on the span before Stage 0; the `generate(model=)` pin (S0-D5) moved into CT19 |
| CT19's `gen_ai.response.model` span attribute; SC17's served-model collection | EV1 (#64) | the same attribute and the same `served_models` field, already filed |
| 0c's #51 (grade the model-fix gate GATE in `loop.py`) | merged into #51 on 0b's shape | one fix, one owner (S0-D11); no grade a person sees changes |
| T52 in CT6 | RE7 | RE7 lands early with no decision, and RE9 and RE31 need it; CT6 builds on its helper |
| CT6's move of the cleaned output; PF15's kernel-side temp-and-rename | RE14 | the host writes the cleaned parquet from the verified frame, atomically (S0-D8) |
| PF23's allowed-provider check | CT18 | one check in `provider_problem`; PF23 feeds it from `crivo.toml` |
| RE15's `preview_screen` hardening | #84 | model-written QUERY and fix cells never run before approval |
| RE17's gate order; the hash pin of admitted skills | #85 | the first gate and the pin are #85's |
| PF21's refusal of another mode's flag | #46 | lands now as filed; PF21 builds on it |
| `bench/attacks/degenerate.py` | `bench/degenerate.py` | `bench/attacks/` stays loop 1's alone (S0-D32) |
| L1's `tests/test_guard_reads.py` | `tests/test_hooks.py` | EV5's test file |
| PF-D9 (#48, #50) | outside Stage 0, under ED6 | ED6 already covers behaviour changes no suite measures yet: shipped-unmeasured with Aarmen's yes |
| D-CT6 (0d's one-off paid budget) | D21 (part) | one rule for every paid Stage 0 run |
| SC24's sealed shapes in `bench/traps/sealed/` | where ED7 puts them | a sealed set in a public repo is not sealed |
| R1.5, cut the reply at `</execute>` | dropped | done in Stage A (#17) |
| Grounding, replay and the second path for answers | Stage 1 | they need Stage 1's `answer()`; S0-D10 keeps answers at most partly backed until then |
| R1.3 SQL checks (fan-out, keys, grain) | Stage 3 | the plan puts them there |
| `llm.is_context_overflow`; `loop._context`; `diff.inline`; `KernelClient._send_raw` | PF8; #59; RE15; RE9 | in the rows that rebuild those modules (Stage A's cut list) |
| `bench.run.sweep` | removed in SC11 | dead (test-only caller), and its "ledger" name collides with the eval ledger |
| BT4 (`score_fixes.py` path) | dropped | fixed already; SC3 retires the script |
| d20 in MCP | Stage 1's MCP port (S0-D18) | a model-read tool description needs outside-agent runs to measure |
| Recall gaps: d12 ordering, d17 minority packing, d16 (BT1) | after SC24's split (S0-D19) | recall, not false claims; tuning on one smoke case each fits the generator |
| hospital's 227 cells on Raha's missing marker | kept as decided 2026-09-02 | teaching the scorer Raha's marker fits the metric to one dataset |
| Family loads lost after a kernel death or on resume | a follow-up, not filed yet | found by 0b; recovery, not the referee |
| Previews of model cells inside the sandbox | after CT7, not filed yet | #84 turns them off until containment exists |
| Probation-skill gates that carry AUTO (`loop.py:1794`) | Stage 1 loop rebuild | a person passed the skill's admission; separate from #51 |
| Family repair scored end to end | after SC27, with a paid family arm | family cleaning is model-driven and paid |
| Prompt-level injection defences | Stage 1 prompt rebuild (`behaviour`) | 0d builds the mechanical defences and measures injection |
| A full sandbox beyond v1; Windows | Stage 5 | the second half of D18 |
| Provider fallback | Stage 1 (S0-D30) | it changes which model answers |
| `schema_version` on contracts, the glossary and saved answers | Stages 1 and 2b | the files do not exist yet; PF10's policy covers them from their first release |
| URL and database sources for the analyst, CLI and MCP | Stages 1 and 3 | a contained kernel has no network, so URL reads belong on the host side of the bridge |
| `CRIVO_M1=off` | Stage 1 | Stage A's cut; RE11 keeps both arms working |
| #49, #60, #63 | standalone | not Stage 0 work |

## Size

162 rows: 147 new issues and 15 comments on open issues. By part: 0a 30, loop 1 5, 0b 39,
0c 27, 0d containment 26, 0d platform 35. By type: 141 code, 16 eval, 5 experiment; 53 are
bugs. 51 core diffs (55 if S0-D6 is taken) in 18 sittings. 72 rows are blocked on 38 owner's
decisions; 13 small calls are taken.

Paid runs: L3 and L5 (four runs at D16's caps, at most $240 at the hard kill), and SC30,
RE33, CT7's guard and the injection gate run (each capped from its pilot under D21). Stage A
shipped 39 issues in about three weeks. Stage 0 is about four times as many, with more core
and M-size rows, so about three months at that pace, plus the paid runs' wall time and the
decision sittings.

## Risks

- **`loop.py` is the bottleneck.** 30 rows land in one core file, in order. The referee's
  chain (RE11 to RE14) and containment's (CT6, CT7) meet there: CT6 waits for RE14, so a
  stall in the referee stalls containment. Sittings 7 to 10 should come early.
- **Decisions gate most of the work.** 72 rows cannot start until 38 decisions are answered;
  wave 2 needs sittings 1 to 3.
- **Corpus changes force re-recording.** Twelve eval-author rows change the corpus hash, and
  EV3 (#66) fails a cassette that replays on changed data with a "re-record" message.
- **Numbers fall on purpose.** SC1, SC7, SC22 and D8 lower published numbers, and RE21,
  RE24 and DH15 to DH19 add refusals. Refusing looks like rigour: each row pins the
  legitimate repair beside its refusal, and RE33 checks the referee's new refusals on the
  agent's fixes.
- **The demo story changes** under D4 (`crivo diagnose example.csv` exits 1 at the default
  threshold, the Action fails on duplicate rows) and D8 (the example's d06 note becomes a
  gate). README, PRD and QA move with them, in a minor release.
- **Containment on CI runners.** bubblewrap needs unprivileged user namespaces, which Ubuntu
  24.04 restricts; `sandbox-exec` is deprecated; and `/usr/bin/open` still exited 0 inside
  the tested profile. CT4 must settle that before the profile is trusted.
- **No per-fix false-backed rate in Stage 0.** RE33 uses collateral as its guard, because
  the agent lane keeps only each case's final frame. Stage 0's gate claims no false-backed
  rate for fixes; Stage 1 brings it for answers.
- **The eval tooling is in flight.** EV5 (#68) needs S0-D32's lines before SC6, SC23 and
  CT25 start, and ED7 must be answered before SC24 and CT25.
- **Size.** If three months is too long for one gate, the stage splits by part: 0a with
  loop 1's run against the scorer (SC1 to SC30, L1 to L3) as one sub-gate, the rest as the
  second.
