# Synthesis: Aarmen's four research reports, and what they change

2026-10-14. Read in full: `2026-10-14-recursive-language-models.md`,
`2026-10-14-autoresearch.md`, `2026-10-14-jev-model.md` and
`2026-10-14-landscape-sweep.md` in this folder (their own ranked summary is
`2026-10-14-four-deep-dives-summary.md`).
Companion to `2026-10-14-repl-rlm-deep-dive.md`. This is the input to the
kernel-centric structure design (direction A, approved 2026-10-14).

## Verified against the repo

`bench/results/full.json`, external `hospital` (one of the four Raha sets, the
only dirt in the benchmark nobody here designed): 509 dirty cells, **2,305 cells changed, 0
repaired**, `verification.survived_rate = 1.0`. Repair and dirt F1 are `None`
because precision = recall = 0, and RESULTS prints "—" for a measured zero.

## The five findings that change the structure

1. **Verified is not the same as correct.** crivo's verifier is a
   self-defined signal (the detector went quiet, untouched columns match), the
   exact shape DGM and AlphaEvolve gamed. Nothing checks that the target column
   is right. Hospital proves the gap. ArrivalBench (2026-10-01): pipelines
   certified 86 to 100% by single-run grading were 7 to 79% silently wrong on
   replay. **A backed number needs an evaluator the work cannot touch, a
   collateral measure (cells changed outside the dirt), and replay checks.**
2. **The REPL carries the gain; recursion is for labelling.** RLM depth 0 gets
   most of the lift; sub-calls pay only on per-item semantic labelling; LMs
   cannot count (trained 30B RLM: 4.9 on numeric vs 60.5 non-numeric).
   Typed, engine-managed operators beat free-form recursion (lambda-RLM, LCM).
   **Design: `llm_map` over distinct values, LM labels and pandas/SQL counts.**
   Cheap fixes: stop at `</execute>` (hallucinated observations), and check the
   answer prose's numbers against `result`.
3. **Jev is System 1, never the driver.** A decision model: typed answers with
   probabilities, no text, no code. Weak on numbers, dates, counting,
   indirection. Fits: the labeller inside `llm_map` (choice over up to 255
   categories), the intent-check pre-filter, routing. Open Apache-2.0
   equivalents (Laya, Kev 4B, Perplexity Decider 27B) can run locally, which
   keeps values on the machine. Must be measured before trusted.
4. **autoresearch: the evaluator matters more than the search.** Reward
   hacking is the default once the agent can see the scorer (METR 30.4%,
   BaitBench 57%); only mechanical isolation works, never prompts. Order of
   loops: red-team the scorer, then generate corruption variety, then a
   constrained detector loop with shape-held-out acceptance, then skills
   (counterfactual rent, SkillOpt-style nightly improvement behind the human
   gate). The skill library has never worked in practice: 3 skills ever, 2
   retired, 0 promoted.
5. **The market moved.** OpenAI Data agent and Claude Dashboards ship
   warehouse-first analysts; pandas-ai is dormant; nobody owns verified
   cleaning. A Sep 2026 survey names "a missing verification-repair repository"
   and "missing experience transfer" as open problems: that is crivo's skill
   library. Agent Skills is read by 40+ clients including Databricks Genie Code
   and Snowflake Cortex Code. Text-to-SQL leaderboards have 52 to 66% label
   errors, so a SQL claim needs its own honest instrument.

## Practical items surfaced

- The Claude path in `llm.py` likely 400s on current models (`temperature`
  rejected; `max_tokens` 8192 too low for thinking). Unverified live.
- The default model (DeepSeek V4 Pro) is being phased out; choose by cost per
  verified fix. Log the response's `model` field.
- Bench gaming gradient: datasets with P = R = 0 drop out of the repair mean
  (174 of 450 fully fixable), so turning a partial repair into a total failure
  raises the published number.
- Injector and fixer share the same truthy set (`_BOOL_TRUTHY` vs `_TRUTHY`):
  the dirt and the cure have one designer.
- MCP 2026-07-28: pull the port forward; plan HTTP transport.
