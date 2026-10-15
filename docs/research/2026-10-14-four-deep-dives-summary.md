# Four deep dives, 2026-10-14: what they mean for crivo

Four read-only research agents, run in parallel, each with live web search.
The full reports sit next to this file:

| Report | File |
|---|---|
| Recursive Language Models: origin, what changed, crivo fit | `2026-10-14-recursive-language-models.md` |
| "jev": what it is, and whether crivo should use it | `2026-10-14-jev-model.md` |
| autoresearch and the agents around it | `2026-10-14-autoresearch.md` |
| AI landscape sweep, mid-July to mid-October 2026 | `2026-10-14-landscape-sweep.md` |

Private pages (Aarmen's claude.ai account): the autoresearch report at
https://claude.ai/artifact/9ySLoGSuyp14V2CogZ2JT6, and the other three plus
this summary at https://claude.ai/artifact/VLsKmegSiNjMPQ9rcHUYqa.

Coverage limits: X was read through search snippets only. Reddit blocked
direct access, so the RLM report has no Reddit signal and the landscape sweep
used the Arctic Shift archive.

## Ranked findings

**Checked** means confirmed in crivo's code or bench data on 2026-10-14.
**Report** means it comes from an agent's research and was not re-checked.

1. **The Claude path fails on every current Claude model.** (Checked)
   `src/crivo/llm.py:86-88` sends `temperature=0.0`, and the default model
   is `claude-opus-5`. Anthropic's API docs say Opus 5 and 5.5 reject
   temperature with a 400; Sonnet 5.5 and Haiku 5.5 reject any non-default
   value. `CLAUDE_MAX_TOKENS = 8192` is too low now that thinking is on by
   default and counts toward it. Checked against the docs, not run live; the
   tests use a fake client that never inspects request arguments.
2. **The published repair F1 of 0.923 is 0.596 when real misses count.**
   (Checked) `_f1` (`bench/score.py:155`) returns None when P+R is 0, and
   `_aggregate` (`bench/run.py:50`) leaves None out of the mean. 224 of the
   450 fully-fixable datasets drop out. 100 are by design (`tx-sentinels`,
   `tx-constant-col`). The other 124 are real misses: `flags-bool-chaos`
   (50), `tx-money-strings` (50) and `tx-header-damage` (24). In
   `flags-bool-chaos` and `tx-header-damage`, verification reported every
   fix holding while no dirty cell was repaired. Verification checks that the
   detector went quiet; it is not a correctness signal.
3. **The default model is shifting, and cheaper models score as well.**
   (Report) DeepSeek's pages disagree on whether `deepseek-v4-pro` now routes
   to V4.1-Flash. On Artificial Analysis, V4 Pro scores 36 at $0.67 per task,
   below V4.1-Flash, Haiku 5.5 and MiMo-V2.6-Pro, which all cost less. A
   DeepSeek default may also block US enterprise users. Suggested test order:
   Haiku 5.5, DeepSeek Flash, GPT-6.1 Sol, Sonnet 5.5, Opus 5.5 at low
   effort, and one local open model, ranked by cost per verified fix. The
   jev report adds that bench result files don't record which model ran.
4. **Jev can't run crivo.** (Report) It's a fast decision model that returns
   typed choices, not text or code. At most it could pre-screen the intent
   check, and only if a labeled test shows it matches DeepSeek there.
5. **crivo is already a depth-0 RLM; the cheap win is a stop sequence.**
   (Checked) `llm.py` sets no stop sequence, so text the model writes after
   `</execute>` enters history next to the real output. The RLM field found
   the REPL matters more than recursion, and depth 2 or more mostly hurts. A
   gated `llm_map` for labelling text values is the bigger idea; it crosses
   the no-raw-rows rule and needs a spec and a benchmark gap first. The
   "depth 1" wording in `docs/ARCHITECTURE.md:80` reads like RLM recursion
   but means skills can't spawn skills.
6. **The frontier labs now sell AI analysts, built for warehouses, not messy
   files.** (Report) pandas-ai has had no commit since 2025-10-28. Hex's
   DataBench has models averaging 54% on silently-wrong data traps. A
   2026-09-28 survey of data agents names a verification-repair repository
   as an open problem.
7. **MCP, SKILL.md and sandboxing all moved.** (Report) The 2026-07-28 MCP
   spec is stateless and deprecates sampling; crivo pins `mcp` 2.0.0 while
   2.3.0 is out. More than 40 tools read SKILL.md, so exporting crivo's
   test-gated skills is an opening. Sandboxing is now a buying criterion,
   and the default kernel on macOS is an unsandboxed subprocess.
8. **Lock the scorer before any self-improvement loop.** (Report) Agents
   game any scorer they can see or reach. The first loop should hunt for
   scorer lies, then run locked against a held-out test set.

## Suggested order

Fix the Claude path, fix the scorer and republish the numbers, then run the
model comparison. The stop sequence, `llm.py` and `llm_map` are core, so they
go to Aarmen as proposed diffs.
