# Research: is the REPL the right core, and what makes Prime Agent shine

2026-10-14. Three read-only agents, run in parallel for the "agent skill and
tool" brainstorm: a Prime Agent teardown (upstream `main` at 5f218f7, now a
Rust port, plus arXiv 2608.23552 and the RLM paper 2512.24601), a 2026
landscape survey, and an audit of how crivo uses its own kernel. Paper
numbers were read from the arXiv HTML pages, not the PDFs.

## Verdict

**A persistent Python kernel is a strong substrate, and the mainstream one in
2026.** Anthropic (code execution with persistent state since
`code_execution_20260120`), Prime Intellect, DSPy (`dspy.RLM`) and marimo all
converged on a kernel that holds the data as a variable. What is weak is a
*bare* REPL: hidden state, no checkpoint, no budget, no replay. The REPL is
the wrong tool only for clean warehouse data (push down to SQL) and for data
larger than RAM (lazy DuckDB or Polars plans inside the kernel fix that).

**"REPL + RLM" alone is no longer unique.** Prime Agent ships exactly that,
plus skills and memory. What no one else ships is crivo's deterministic
verify-and-revert loop with receipts. DS-STAR checks itself with an LLM
judge; Databricks Genie "Inspect" writes SQL sub-checks; neither re-runs a
deterministic detector and reverts.

## Measured evidence

RLM paper, Table 1, GPT-5 root (CodeQA / BrowseComp+ 1K / OOLONG / OOLONG-Pairs):

| Setup | Scores |
|---|---|
| Base model | 24.0 / 0.0 / 44.0 / 0.1 |
| RLM, depth 0 (REPL, no sub-calls) | 58.0 / 88.0 / 36.0 / 43.9 |
| RLM, depth 1 | 62.0 / 91.3 / 56.0 / 58.0 |
| Claude Code (Opus 4.1) | 12.0 / 0.0 / 40.2 / 0.1 |

- Putting the data in the REPL carries most of the gain. Sub-calls pay off
  mostly on per-entry semantic labelling then aggregation (OOLONG).
- Weaker coders get worse with recursion: Qwen3-Coder-480B depth 0 to 1,
  CodeQA 66 to 56; depth 2 dropped OOLONG 48 to 26. A reproduction (arXiv
  2603.02615) found depth 2 "overthinks", latency 3.6 s to 344.5 s.
- Costs: median run cheaper than the base model, mean higher on outliers.
- Prime Agent vs each model's own harness: large wins for GLM-5.2 over
  Pi-mono, roughly a tie for Opus 5 vs Claude Code and GPT-5.6 vs Codex. No
  ablation separates REPL, subagents and refinement. ARC-AGI-3 30% to 95.5%
  is vendor-reported with an unstated baseline.
- DataSpace (KDD Cup 2026): with the model fixed, the harness alone moved
  scores 15 points (Claude Code 44.6 vs smolagents 31.0); 52% of audited
  failures were "answer materialization" after the right result was in memory.
- Code-calling-tools beat JSON tool calls in 11 of 14 models (arXiv
  2608.06370); Anthropic's programmatic tool calling cut input tokens 37 to 38%.
- MCP 2026-07-28 deprecates Sampling and protocol sessions: a server cannot
  borrow the caller's model, so an inner-model tool always costs two models.

## Why Prime Agent shines (principles, with crivo's status)

1. Data in the environment, model sees metadata. **crivo: present**, stricter
   than Prime Agent (2,000-char clips vs 65,536).
2. Code is the only action space; every capability is a function in the
   kernel. **crivo: partial.** The kernel has pandas; detectors, profiler,
   skills and verifier run host-side and are invisible to the model.
3. A typed, validated kernel-to-host bridge; host owns state, policy, budgets.
   **crivo: partial.** Host owns policy, but there is no kernel-to-host channel.
4. Recursion returns handles and bounded results, never the child's context;
   depth cap 2. **crivo: absent.**
5. Sub-models for per-entry semantic judgment, code for everything else.
   **crivo: absent.** Free-text columns are exactly this shape.
6. State outlives the context window (snapshots, variables survive
   compaction). **crivo: partial.**
7. External verification with bounded feedback. **crivo: present and
   stronger** (detector re-run, invariants, revert).
8. Learned state is small, versioned, reversible. **crivo: present, stricter**
   (test gate plus human gate); lacks a per-skill expected outcome.

Much of Prime Agent's edge is long-running autonomy and recovery, not the REPL
itself.

## How crivo uses its kernel today (audit)

- **The verify baseline lives in kernel globals** (`_clean_backup`,
  `_clean_rows`, `_clean_hashes`, `verify.py:55-65`). A fix cell that re-runs
  the baseline passes verification after deleting 59 of 60 rows and
  overwriting an untouched column. Reproduced 2026-10-14 by exec'ing
  `baseline_cell` + fix + `verify_cell` on `load_example()`. Already listed in
  master plan wave 2 ("verification reads kernel state a model cell can
  rewrite"). Bites on unattended paths: autonomous mode, headless `clean`,
  MCP `clean_file`.
- crivo is importable inside the kernel, but the prompt never mentions it and
  the registry hides callables, so the model cannot discover its own tools.
- CLEAN fix turns are blind: one `def fix_` cell from at most 3 samples, no
  exploration first (`loop.py:1322`, `prompts.py:71-79`).
- Nothing in the kernel can call a model. "Depth 1" in the code means a skill
  fix never spawns a skill proposal; the RLM sub-call was never built.
- QUERY gets 6 cells per question; compaction is a lossy summary at turn
  start only; profiles are never refreshed after a clean.
- MCP `ask` returns the inner model's card; the calling agent never gets the
  kernel (no `run_cell`, no load into a session, no clean on an open session).
- `llm.is_context_overflow` is defined and never called.

## What a stronger REPL has (ranked by cost)

1. Tools as functions inside the kernel (cheap).
2. Recursion with budgets: depth 1, capped sub-calls, batched, a cost ceiling (cheap).
3. Output-contract checks before answering: grain, columns, types (cheap).
4. Replay the accepted cell log in a fresh kernel as an acceptance test (cheap).
5. Replayable, content-addressed execution log (cheap to medium; provenance is most of it).
6. Per-variable checkpoints, Kishu-style (medium); a real process fork (expensive).
7. A real isolation boundary by default (medium; subprocess mode is not one).
8. A reactive dependency graph, marimo-style (expensive).

## Sources

RLM: arxiv.org/abs/2512.24601 (v3 2026-05-11). Prime Agent: arxiv.org/abs/2608.23552;
github.com/PrimeIntellect-ai/prime-agent. Prime Intellect RLM blog: primeintellect.ai/blog/rlm.
Reproduction: arxiv.org/abs/2603.02615. Code execution with MCP:
anthropic.com/engineering/code-execution-with-mcp. Programmatic tool calling:
platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling.
Cloudflare Code Mode: blog.cloudflare.com/code-mode-mcp. Bitter Lesson of Tool
Calling: arxiv.org/abs/2608.06370. DataSpace: arxiv.org/abs/2608.03451. DABstep:
arxiv.org/abs/2506.23719; DS-STAR: arxiv.org/html/2509.21825v4. DAB:
arxiv.org/abs/2603.20576. FlowBook: arxiv.org/abs/2605.01560. marimo pair:
marimo.io/blog/marimo-pair. Kishu: arxiv.org/abs/2406.13856. Sandbox escape:
cyera.com/research/sandcastles-not-sandboxes-how-one-architectural-flaw-exposed-seven-products.
Braintrust SQL vs bash: braintrust.dev/blog/bash-agent-evals. MCP 2026-07-28:
modelcontextprotocol.io/specification/2026-07-28/changelog. Genie agent mode:
docs.databricks.com/aws/en/genie/agent-mode.
