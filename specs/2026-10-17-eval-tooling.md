# Eval tooling: measure what the model does, before Stage 0

**Status: filed 2026-10-17** as issues #64 to #83 (EV1 to EV20). ED1 to ED4
and ED6 were taken as recommended under Aarmen's standing instruction to take
the recommended option on design calls and record it; he may overturn any of
them. ED5, ED7 and ED8 were Aarmen's; he took all three as recommended on 2026-10-18.

2026-10-17. The WRAP spec for the eval tooling that lands before Stage 0 of
`specs/2026-10-14-the-plan.md`. It turns the proposal Aarmen approved on
2026-10-17 into issues: items 1 to 7 of its "File-by-file" list shipped in
a954162 (work types, the issue template, `/new-task`, settings.json denies, the
Stop hook's behaviour prompt); this spec covers items 8 to 20, plus the routing
table in `/start-task` that a954162 left for when the tooling exists. Stage A's
spec moved "Record and replay tests, `agent_run --record`" here. Every item was
checked against `dev` @ 7c73957, read-only.

## What

A behaviour change (a prompt, a turn structure, a tool description, a model
default) is judged by a measured result, not by a green test suite. Concretely:
a run of the agent can be recorded and replayed offline through the real loop,
kernel and verification; an eval is registered before it runs and its result
lands in an append-only ledger with the code, suite, scorer, referee and served
model it ran against; whoever writes a test of crivo cannot read what it tests,
enforced by a hook; and `/ship`, `/promote` and CI refuse behaviour work that has
no row behind it. Stage 0's loop 1, truth-label audit and new injectors build on
this.

## Requirements

One issue each. `core` marks an owner-reviewed diff.

**Record and replay**
| id | issue | core |
|---|---|---|
| EV1 (#64) | llm: every model call records the model that served it (DD3, first half) | core |
| EV2 (#65) | bench: `agent_run --record` saves each model reply and kernel result with per-call fingerprints | |
| EV3 (#66) | tests: replay a recorded agent run through the real loop and kernel, and refuse cassettes that hold rows (owns the raw-row scan) | |

**Who may read what**
| id | issue | core |
|---|---|---|
| EV5 (#68) | hooks: `guard_reads` blocks the reads, writes and paid commands an agent's mode forbids | |
| EV6 (#69) | agents: an eval-author that writes injectors and corpus cases without reading what they test | |
| EV7 (#70) | agents: scout and builder carry Type and Eval lines; builder and test-writer run `guard_reads` | |

**The ledger and the runner**
| id | issue | core |
|---|---|---|
| EV4 (#67) | bench: an append-only eval ledger with one row format for registrations, results and decisions | |
| EV8 (#71) | bench: `bench.eval` runs a registered suite k times and writes the result row | |
| EV9 (#72) | bench: eval runs stop at a per-case and a per-run dollar cap | |
| EV10 (#73) | skills: `/eval` runs a pre-registered eval and records it in the ledger | |

**CI and gates**
| id | issue | core |
|---|---|---|
| EV11 (#74) | ci: `check_locks` keeps the ledger append-only and its rows true to the code they ran | |
| EV12 (#75) | ci: `leak_scan` finds suite material in prompts, tool descriptions and skills | |
| EV13 (#76) | agents: the reviewer checks behaviour diffs against their pre-registration | |
| EV14 (#77) | skills: `/ship` and `/promote` gate behaviour and experiment work on ledger rows | |

**The first measurement**
| id | issue | core |
|---|---|---|
| EV15 (#78) | bench: the A/A noise floor for `agent-clean-smoke` on the default model (experiment, paid) | |
| EV16 (#79) | tests: the first real-model cassettes, one per outcome the A/A run produced | |

**Docs and process**
| id | issue | core |
|---|---|---|
| EV17 (#80) | docs: QA says which cases test plumbing; the promotion PR lists its ledger rows | |
| EV18 (#81) | docs: architecture says behaviour is judged by the ledger, and which reads are enforced | |
| EV19 (#82) | process: `/start-task` routes behaviour, eval and experiment issues by type | |
| EV20 (#83) | plan: rule 10 names the work types | |

**Who builds what.** The hook keeps the builder out of `tests/` and the
test-writer inside it, so the test-writer builds `tests/replay.py`,
`tests/cassettes/` and the scan (EV3, EV16), on a scout → test-writer → reviewer
path with no builder step. Paid commands are the orchestrating session's alone.

## Acceptance criteria (the gate before Stage 0)

- A cassette recorded with `agent_run --record` replays offline through the real
  loop, a real subprocess kernel and the in-kernel verification, and fails on a
  changed call count or outcome; a changed prompt only warns. The cassette set
  adds under 20 s to the suite.
- No committed cassette holds three or more cells of a corpus row or any value
  from a PII-flagged column, and none comes from outside data (EV3's scan, run in
  CI).
- With `guard_reads.py eval-author`, a read of `prompts.py`, `loop.py`, the
  referee, `detect.py` or `autoclean.py` (in any worktree) exits 2, and a read of
  `bench/corrupt.py` exits 0. With `builder`, a held-out or sealed read, a Bash
  write to the ledger, and a paid command without `CRIVO_PROVIDER=faux` each
  exit 2.
- `bench/ledger.jsonl` holds the A/A run: a registered row, a result row with
  the served model, k = 3, pass^k, pass@1, the flaky set, p50 and p95 for cost
  and wall time, `false_backed: null` with its reason, and a noise floor; and
  Aarmen's decision row.
- CI runs `scripts/check_locks.py` and `scripts/leak_scan.py` on every push, and
  both pass on `dev`.
- `/start-task` routes behaviour, eval and experiment issues instead of stopping;
  `/ship` refuses a behaviour change without an adopted or `shipped-unmeasured`
  row.

## Priority

**Wave 1, independent:** EV1 (core), EV2, EV4, EV5.

**Wave 2, on wave 1:** EV3 [after EV2], EV6 and EV7 [after EV5], EV8 [after EV1,
EV2, EV4], EV11 [after EV4].

**Wave 3, on the runner:** EV9 [after EV8], EV10 [after EV9], EV12 [after EV11],
EV13 [after EV10, EV12], EV14 [after EV10].

**Wave 4, the first measurement:** EV15 [after EV10, EV11; needs ED5], EV16
[after EV3, EV15].

**Wave 5, docs and process:** EV17, EV18, EV19 [last, after EV14], EV20 [needs
ED8].

**Shared files, landing order** (whichever lands second rebases):
- `bench/agent_run.py`: EV1, EV2, EV9.
- `bench/eval.py`: EV8, EV9.
- `tests/test_hooks.py`: EV5, EV6, EV7.
- `.github/workflows/ci.yml`: EV11, EV12.
- `CLAUDE.md`: EV18 only; `AGENTS.md`: EV19 only.

Core review for Aarmen: EV1 (one diff in `llm.py`, under about 15 lines).

## Decisions the owner owes

| issue | decision | recommendation | status |
|---|---|---|---|
| EV8, EV12, EV15 | ED1: the first suite `/eval` runs before the 0a split | one provisional suite, `agent-clean-smoke` (the agent lane over SMOKE, dev only), with `false_backed: null` and its known limits on every row; replaced by 0a's dev split | taken |
| EV2, EV3 | ED2: how a cassette replays the kernel | a real subprocess kernel on data rebuilt from the corpus seed (so the real in-kernel verification runs and cassettes hold no data); recorded-kernel replay only when a kernel-death cassette needs it | taken |
| EV5, EV6 | ED3: the eval-author's read limit | an allowlist (`bench/` without `bench/results/`, the bench tests, the contract, the plan and the brief), not the approved blocklist, because docs and tests quote the code a blocklist protects | taken |
| EV5, EV6 | ED4: what the eval-author may write | `bench/traps/**`, the injectors, `bench/corpus.py` and the injector tests; not `bench/attacks/`, which loop 1's attacker owns under its own mode | taken |
| EV15 (#78) | ED5: D21 pulled forward, the paid budget before Stage 0 | an explicit `--budget-usd` on every run with no default; Aarmen names the A/A cap after its dry run; the weekly canary starts with Stage 1 | decided by Aarmen 2026-10-18, as recommended |
| EV14; #48, #50 | ED6: behaviour changes no suite measures yet | ship with Aarmen's yes as a `shipped-unmeasured` ledger row, as #30, #37 and #39 shipped, now on the record | taken |
| 0a, Stage 1 | ED7: where held-out and sealed sets live | outside the public repo, with only their hash committed (EV11 checks either way) | decided by Aarmen 2026-10-18, as recommended |
| EV20 (#83) | ED8: rule 10 names the work types (proposal item 20) | reword rule 10 as drafted in EV20, with a changelog line | decided by Aarmen 2026-10-18, as recommended |

## Cut, with reasons

| item | where it goes | why |
|---|---|---|
| "First used by DD1, DD5 and the s99 bug" | dropped | shipped in Stage A (#13, #17) with scripted tests; the first real cassettes come from EV15 |
| README numbers from ledger rows | 0a | needs the deterministic bench to write ledger rows |
| Arm suffix migration (D6), `RESULTS_DIR` flag, folding `compare.py` and `score_fixes.py`, deterministic-lane rows | 0a | EV takes only what `/eval` needs from 0a's ledger bullet |
| Loop 1's attacker mode and `bench/attacks/` | Stage 0, loop 1 | the attacker may not read the generator the eval-author writes (ED4) |
| The Stop hook naming the ledger row | dropped | item 7 already asks for the result or "unmeasured"; EV13 and EV14 check the row |
| QUERY-turn cassettes and a QUERY suite | Stage 1 | no QUERY lane exists yet; the trap runner reuses EV2's recorder |
| Effort as an arm dimension | Stage 1 (R4.1) | effort is a constant in `llm.py`; EV8 refuses another effort |
| The weekly canary | Stage 1, with D21 | written into `/eval`, not started (ED5) |
| An OS sandbox for code the eval-author runs | 0d (D18) | the hook makes a read deliberate, not impossible; the reviewer checks the diff |
| An independence lint script | folded into EV13 | a reviewer check is enough for one author |

## Size

20 issues: 8 M, 12 S; one core diff (EV1); one paid run (EV15, hours of wall
time, cost set by Aarmen). Two of the 20 (EV3, EV16) are built by the test-writer
alone. At Stage A's pace the code rows take a few sessions; EV15's wall time is
the longest single wait. The main risk: a change to the corpus generator changes
the data a cassette replays on, so an injector change in Stage 0 can force a
cheap re-recording of the cassettes it touches (EV3 fails with a "re-record"
message rather than passing on different data).
