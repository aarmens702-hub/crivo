---
name: eval
description: Measure a behaviour or experiment issue with a pre-registered eval - refuse an incomplete Measurement, dry-run the caps, register, run with recordings, judge the result against the A/A noise floor, hand transcripts to the reviewer and cassettes to the test-writer, and record Aarmen's decision in the ledger. Use when a behaviour or experiment issue needs its measurement, or the user says run the eval, measure this, or record the result.
argument-hint: "<issue> [suite] [split]"
---

# Run a pre-registered eval

Only the orchestrating session runs this, never a specialist (the builder's hook runs `bench.eval` only under faux), and always from the root of the task's worktree, `.worktrees/<n>`: the runner reads the ledger and the fingerprints from where it runs.

1. **Refuse.** Stop and say why if any of these holds:
   - The tree is dirty (`git status --porcelain`). Commit the change on the task branch first; the orchestrator owns git, and `bench.eval` refuses a dirty tree anyway.
   - The issue's Type (`gh issue view <n>`) is not `behaviour` or `experiment`.
   - Its Measurement block lacks any of: the hypothesis, the suite and split, the primary and guard metrics, the arms with exact model ids, k, the decision rule, the budget. Ask for what's missing on the issue; never fill it in yourself. A `[suite]` or `[split]` argument must match the Measurement's.
   - The split is `heldout` without Aarmen's yes in this conversation, or `sealed` outside a stage gate. Until 0a, `bench.eval` has neither split and refuses both anyway.
2. **Dry run.** Any arm that isn't `faux` costs money, so `register` runs with `--dry` first, its flags one for one with the Measurement (repeat `--arm` per arm and `--guards` per guard metric):
   ```
   uv run python -m bench.eval register --issue <n> --type <behaviour|experiment> \
       --suite <suite> --split <split> --arm <NAME>=<PROVIDER>:<MODEL> --k <k> \
       --budget-usd <B> --per-case-usd <C> --wall-cap <seconds> \
       --hypothesis "<hypothesis>" --primary <metric> --guards <metric> \
       --rule "<rule>" --dry
   ```
   - Both caps come from the Measurement or from Aarmen. Neither has a default (ED5), so ask him for any the Measurement leaves out; never pick one. The wall cap comes from the same place, or `--wall-cap` is left off for the 300 s default; never pick one yourself.
   - Show Aarmen the worst case it prints, its worst-case wall time line (a lower bound, not a ceiling), and what each arm's model cost a case before. Stop and wait for his answer. Register only once he has confirmed both caps or named new ones (new caps get a fresh `--dry`).
   - A non-faux arm needs an entry in `bench/prices.py`, its rates read from the provider's own pricing page, with that page's URL and the date read. Without one, `register` refuses the arm. A new entry is a change: commit it on the task branch before registering.
3. **Register.** The same line without `--dry`. It prints the registered row id.
   - An issue gets 2 results. `register` refuses a third without `--owner-ok`, and that flag goes on only with Aarmen's yes in this conversation. The builder stops after 2 runs and reports.
   - Commit `bench/ledger.jsonl` by name (`git add bench/ledger.jsonl`, then a message like `eval: register <row> for #<n>`), then run `uv run python scripts/check_locks.py`. It must exit 0: the ledger is append-only, so a violation that reaches `dev` can't be undone.
4. **Run.** `uv run python -m bench.eval run --registered <row> --record <scratchpad>/eval/<row>`.
   - It refuses on a dirty tree, and when code outside the ledger was committed since registering: a run is measured on the code it was registered on, so register again.
   - It prints one line per case and run, then one screen per arm (pass^k, pass@1, flaky, aborted, cost, wall time, served models, false-backed), the noise-floor line, what was spent of the budget, where each run's Session output went, and the result row id.
   - Show Aarmen each arm's screen and the noise-floor, spent and result lines as printed. The noise-floor line names the flaky cases: anywhere outside the terminal (the issue, a report), give them as a count.
   - Each run's Session output, its data profile among it, is in the logs dir the run names, `bench/results/eval/<row>/<arm>/logs/`. Read a log there when a case needs a look; never paste one anywhere, since it holds samples of the data.
   - If a case raises, the run stops without a result: the refusal names that case's log, and the cases that ran are kept in `bench/results/eval/<row>/cases.jsonl`. No result row means its spend is in no ledger row, and the 2-results count never sees it. Stop and give Aarmen the spend the refusal names (plus up to the raising case's cap and one call, unread). Register again only on his yes.
   - A budget hit lists the cases not run, and the arm it stopped in has a partial k.
   - A call whose spend can't be read (a stream cut off before its usage arrived) is charged its bound, at most one call's cost: the bytes sent plus the output limit its model's `bench/prices.py` entry names. The bound counts toward the budget and the run goes on; the case line, the arm's screen and the spent line say "bounded, not measured". `spent_usd` is the measured calls of the runs read, priced at the entry's rates (peak, so it reads high off-peak); `spent_bound_usd` adds the bounds, the most the runs read could cost at those rates; a run left unread is in neither. On a model whose entry names no output limit, an unread case still stops the run.
   - Commit `bench/ledger.jsonl` by name again, then run `uv run python scripts/check_locks.py`.
5. **Judge.** Hold the result to the rule as registered; never reword the rule after the run.
   - Compare it with the A/A noise floor for that suite and model: `noise_floor` on a result row in `bench/ledger.jsonl` whose registration ran two arms on one config. This lists every floor on a suite: its result row, the model it was measured on, the pass@1 spread and how many cases were flaky (a count, never their names), or "no floor" when there is none:
     ```
     uv run python -c "from bench import ledger; regs = {r['row_id']: r for r in ledger.rows(kind='registered')}; found = [(r['row_id'], sorted({a['provider'] + ':' + a['model'] for a in regs[r['registered']]['arms'] if a['name'] in f['arms']}), f) for r in ledger.rows(kind='result', suite='<suite>') if (f := r.get('noise_floor'))]; [print(i, *m, 'pass@1 diff', round(n['pass_at_1_diff'], 3), 'flaky', len(n['flaky'])) for i, m, n in found]; found or print('no floor on <suite>')"
     ```
   - With no floor for that suite and model, say so plainly: the result can't be told apart from noise.
   - A gain inside the floor is not a win.
   - The false-backed rate must never rise. Until 0b it is null, with its reason on the row: say so, and never count it as held.
6. **Hand off.** A run's transcript is its cassette in `<scratchpad>/eval/<row>/` (its model replies; one per case, arm and run) plus its log, `bench/results/eval/<row>/<arm>/logs/<case>.r<run>.log`. Not `work/<case>/…/transcript.jsonl`, which `_run_case` rebuilds each run.
   - The reviewer gets every false-backed transcript (from 0b, when verdicts exist), plus 2 passes and 2 failures.
   - The builder sees only the dev split's totals and transcripts, never held-out or sealed results.
   - Every abort, cap hit and (from 0b) false-backed case is offered to the test-writer as a cassette for `tests/cassettes/`, once the scan says it holds no rows. Run this from the worktree root: it prints one line per problem, never a value, and exits 1, or says the cassettes are clean:
     ```
     uv run python -c "from tests.replay import load, scan; import sys; from pathlib import Path; ps = [Path(a) for a in sys.argv[1:]]; out = [x for p in ps for x in scan(load(p), p.stem, nbytes=p.stat().st_size)]; print('\n'.join(out) or f'{len(ps)} cassettes clean'); sys.exit(1 if out else 0)" <cassette>.json ...
     ```
   - A cassette the scan refuses is never offered.
7. **Decide,** only once Aarmen says so, with a note that names his call and the date:
   - `uv run python -m bench.eval decide --result <result row> --adopted --note "<Aarmen's call>, <date>"`, or `--dropped`. On a behaviour registration, `--adopted` refuses when the prompt, referee or scorer files moved since the result: drop it, or register and run again.
   - A behaviour change no suite measures yet ships on his yes as `decide --shipped-unmeasured --issue <n> --note "..."` (ED6).
   - Commit `bench/ledger.jsonl` by name, then run `uv run python scripts/check_locks.py`.
8. **When it runs.**
   - Per behaviour issue, on the dev split, k = 3.
   - At `/promote`, only when behaviour commits landed since the last promotion.
   - Held-out at stage gates, k = 5.
   - A weekly manual canary on the default model once Stage 1 starts (ED5), comparing `served_models` with the last row's. Written down here, not started.
   - No nightly runs before Stage 2b, and no paid runs in push CI.
9. **Report.** Give the registered, result and decision row ids, each arm's screen, the noise floor and the spend, and how the result stands against the rule. Say plainly when there is no floor, when false-backed is null, and what went to the reviewer and the test-writer. Never quote cases, here or on the issue: name the suite.
