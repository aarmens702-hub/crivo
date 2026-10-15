# Recursive Language Models (RLMs): origin, what changed, and what it means for crivo

Research date: 2026-10-14. Every claim carries a date. Claims not taken from a primary source (the paper, the authors' posts, official repos and docs, the vendor's own blog) carry a confidence tag: **[high]**, **[med]** or **[low]**. "RLM" here always means Recursive Language Models (Zhang, Kraska, Khattab, MIT), never "reasoning language model".

---

## TL;DR

- **What an RLM is.** The root LM never sees the long input. The input sits as a variable (`context`) in a Python REPL. The model writes code to peek at, grep, slice and chunk it, and calls `llm_query(...)` on pieces from inside that code. It finishes with `FINAL(...)` or `FINAL_VAR(var)`. Alex Zhang introduced it in a blog post on 2025-10-15. The paper (arXiv 2512.24601) followed on 2025-12-31 and was revised on 2026-01-28 and 2026-05-11. The authors say it is accepted to NeurIPS 2026. I could not open OpenReview to confirm.
- **The headline results are real but narrow.** On GPT-5 (paper v1/v3), the RLM took OOLONG from 44 to 56, OOLONG-Pairs from 0.04 to 58, and BrowseComp-Plus at 6 to 11M tokens from 0 to 91. Median cost was at or below the base model. Mean cost was higher because of an outlier tail. The weak spots were also documented from the start: counting, short inputs, blocking sub-calls, brittle FINAL tags, and weak coders (Qwen3-Coder issued thousands of sub-calls).
- **The REPL matters more than the recursion.** In the paper's own ablation, the no-sub-call variant ("depth 0") is close to or better than depth 1 on code and retrieval tasks. Apple's SRLM paper (2026-03) concludes that "recursion contributes only marginal gains". Sub-calls matter mainly for semantic labelling of many items, such as OOLONG and OOLONG-Pairs. Depth above 1 usually hurts: a reproduction (2026-03) and the paper's own Qwen3-Coder rows both show it.
- **The paradigm has moved from a prompting trick toward a trained harness.** The milestones are RLM-Qwen3-8B (SFT, 2026-01), RL-trained RLMs (Qwen3-4B on MRCRv2, Qwen3-30B-A3B LoRA on 2026-05-24, alphaXiv's 4B on 2026-05-13), and the "harnesses are compositional generalizers" result (2026-07-20). In that last result, RL on short tasks generalizes to tasks 8 to 32 times longer and across domains. Other things changed too: sub-calls became batched and async, sub-agents now get their own kernels, tree-wide token budgets appeared, and compaction now keeps history retrievable. sPTC (2026-08) is a latency trick that only measured a 1 to 1.2x speedup.
- **The industry converged rather than adopted.** No frontier lab ships a model called an RLM. Anthropic shipped the same ingredients separately: programmatic tool calling (2025-11, now GA), a "context object outside the window" (Managed Agents, 2026-04-08), and Claude Code dynamic workflows, where a script holds the loop and intermediate results (2026-05). OpenAI added Codex subagents on 2026-03-16. In Prime Intellect's own table (2026-08), Claude Code on Opus 5 scores 0.92 on OOLONG and an RLM harness scores 0.90. The 2025 gap over coding agents has mostly closed **[med: interested party's numbers]**.
- **The serious open-source lines are few.** `alexzhang13/rlm` (5.7k stars, MIT) is the reference library, and its code commits stopped in June. `PrimeIntellect-ai/prime-agent` (22k stars, MIT) is the production line, with `verifiers` and `nano-rlm` beneath it. `dspy.RLM` has been experimental since 2026-01-19. Most of the other roughly 40 repos are Claude Code plugins, MCP wrappers or from-scratch toys.
- **For crivo:** In RLM terms crivo is a **depth-0 RLM with a much stronger trust layer**. Datasets live as variables, the kernel is sandboxed, observations are truncated, and the model gets no in-kernel sub-calls. crivo's "depth-1 recursion cap" is a rule about skill provenance, not about sub-call depth, and RLM readers will misread it. crivo is ahead on verification, sandboxing and governance. It is behind on semantic per-value work over text columns. That gap is exactly what sub-calls fix, and it collides with crivo's "no raw rows to the model" rule. The best import is a **gated, engine-managed `llm_map` over distinct values** paired with pandas counting. Free-form recursion is not worth importing. The cheapest wins are fixing the depth wording, a stop sequence at `</execute>`, and checking the answer prose against `result`.

---

## Dated timeline

| Date | Event | Source type |
|---|---|---|
| 2024-02-01 | CodeAct ("Executable Code Actions Elicit Better LLM Agents"), the code-as-action ancestor | primary (arXiv 2402.01030) |
| 2025-07 (mid) | Chroma "Context Rot" report, which the RLM post cites as its motivation | primary (trychroma) **[med on exact day]** |
| 2025-10-06 | ACE (Agentic Context Engineering), the evolving-playbook contrast | primary (arXiv 2510.04618) |
| 2025-10-15 | Alex Zhang's blog post "Recursive Language Models"; Omar Khattab: "RLMs may be the next" inference-scaling axis; HN 135 pts | primary |
| 2025-10-16 | `rlm-minimal` repo (gist-like reference) | primary (GitHub) |
| 2025-11-04 | OOLONG benchmark (Bertsch et al.), the paper's core aggregation benchmark | primary (arXiv 2511.02817) |
| 2025-11 (~04/~20) | Anthropic "Code execution with MCP" and "Advanced tool use" (programmatic tool calling, beta) | primary blog **[med on exact days]** |
| 2025-12-31 | Paper v1 (arXiv 2512.24601): GPT-5 and Qwen3-Coder, depth 1, no training | primary |
| 2026-01-01 | Prime Intellect: "RLMs: the paradigm of 2026", RLMEnv in `verifiers` | primary |
| 2026-01-02/03 | Zhang and Khattab threads: "2026 will be all about the switch to RLMs"; official `rlm` repo released; HN 161 pts | primary (X, via snippets) |
| 2026-01-15 | `mit-oasys/rlm-qwen3-8b-v0.1` weights on HF | primary |
| 2026-01-19 | DSPy 3.1.1/3.1.2 ships `dspy.RLM` (experimental) | primary (release notes) |
| 2026-01-20 | InfoQ and VentureBeat coverage, with Zhang quotes on guardrails and RAG | secondary |
| 2026-01-23 | RLM reimplemented in Google ADK (community article) | secondary |
| 2026-01 (late) | Kimi K2.5 "Agent Swarm": trained orchestrator, frozen subagents | primary blog **[med on date]** |
| 2026-01-28 | Paper v2 adds RLM-Qwen3-8B (+28.3% over Qwen3-8B) | primary |
| 2026-02-07/17/18 | `rlms` 0.1.0, then custom tools, then **depth > 1 and compaction with offloaded history** (v0.1.1a) | primary |
| 2026-02-10 | Symbolica "Agentica" REPL agents: ARC-AGI-2 85.28% with Opus 4.6 | primary |
| 2026-02-18 | RLM-JB (jailbreak detection as an RLM procedure) | primary (arXiv) |
| 2026-02-25 | Zhang: "Language Models will be Scaffolds" | primary |
| 2026-03-03 | "Think, But Don't Overthink" reproduction: depth 2 degrades, up to 96x slower | primary (arXiv 2603.02615) |
| 2026-03-07 | SRLM (Apple): recursion "marginal", self-reflective program search beats RLM | primary (arXiv 2603.15653) |
| 2026-03-16 | OpenAI Codex subagents | primary (OpenAI Devs X post) |
| 2026-03-18 | VideoAtlas / Video-RLM | primary (arXiv) |
| 2026-03-20 | λ-RLM: typed combinators in place of free-form code, wins 29 of 36 vs RLM, up to 4.1x lower latency | primary (arXiv 2603.20105) |
| 2026-03-27 | Prime Intellect `nano-rlm` | primary |
| 2026-04-08 | Anthropic "Managed Agents": the session as a context object outside the window | primary |
| 2026-04-09 | Zhang, Li, Khattab: "Mismanaged Geniuses Hypothesis" | primary |
| 2026-04-15/16/26 | LongCoT benchmark claims RLMs don't help; Weitekamp's dspy.RLM run 2.6% to 45.4% (about 20x cost); Zhang and Khattab 38.7% to 65.6% with trace-mined tips | primary |
| 2026-05-11 | Paper v3: depth 0 to 3 ablation, Claude Code and OpenCode baselines, MRCRv2 RL experiment | primary |
| 2026-05-13 | alphaXiv "Reinforcing RLMs": 4B shared parent/child policy, GRPO | primary |
| 2026-05-24/27 | `rlm-qwen3-30b-a3b-v0.1` (RL LoRA) and the `training/` harness on prime-rl | primary |
| 2026-05 (~28) | Claude Code dynamic workflows (research preview) | docs primary; date secondary **[med]** |
| 2026-06-11 | "Recursive Agent Harnesses" (PwC): full harness as the recursive unit | primary (arXiv 2606.13643) |
| 2026-06-26 | `rlms` 0.1.3 (Docker persistence, parallel sub-calls); last code release so far | primary |
| 2026-07-01 | LangChain Deep Agents RLM support | primary |
| 2026-07-20 | Zhang and Khattab: "harnesses are compositional generalizers" (RL'd RLM length and domain transfer) | primary |
| 2026-08-04 | TimeRLM (time series, RL post-training) | primary |
| 2026-08-05 | Prime Agent launch (RLM-native coding harness); HN 254 pts | primary |
| 2026-08-23/24 | sPTC (speculative programmatic tool calling); Prime Agent tech report (arXiv 2608.23552) | primary |
| 2026-09-24 | `rlm` README cites "NeurIPS 2026 paper" | primary (authors) |
| 2026-10-04 | SERA: recursive agents that write rubrics for their children | primary (arXiv 2610.04902) |
| 2026-10-09 | Prime Agent rewritten in Rust (HN 64 pts) | primary |

---

## 1. The origin (Oct to Dec 2025)

### Mechanism (blog post, 2025-10-15)
- The RLM is a drop-in for `llm.completion`. The root LM (depth 0) receives only the query and knows a `context` variable exists. The environment is a Python REPL, "similar to a Jupyter notebook". The root writes code, sees **truncated** output, and iterates. Inside the REPL it can call an LM as a function (depth 1) on any slice it builds. It ends with `FINAL(answer)` or `FINAL_VAR(variable)`.
- **Depth.** All experiments used depth 1: sub-calls are plain LMs, not RLMs. The author called deeper recursion "a relatively easy change" that wasn't needed for the benchmarks.
- **Motivation: context rot.** "No single language model call should require handling a huge context." RULER-style needle tests understate the problem because frontier models already score 90% or more on them.
- **Emergent strategies** seen in traces: peeking, regex grepping, partition plus map (chunk, label, aggregate), summarization, and long-output accumulation in variables. Khattab's thread the same day highlighted these.

### Original results
- **Blog (2025-10-15).** OOLONG `trec_coarse` at about 132k tokens: RLM(GPT-5-mini) beat GPT-5 by more than 34 points (about 114%) at similar per-query cost. At about 263k: +15 points (about 49%), cheaper. The RLM without sub-calls lost about 10%, which the author attributes to the semantic labelling sub-tasks. BrowseComp-Plus (20 queries, up to 1,000 documents): RLM(GPT-5) was "the only model / agent able to achieve and maintain perfect performance at the 1000 document scale". The no-recursion ablation reached about 90%. The author called these "preliminary".
- **Paper v1 (2025-12-31), Table 1** (score, then average $ per task; GPT-5 sub-calls use GPT-5-mini):

| GPT-5 | CodeQA (23K to 4.2M) | BrowseComp+ 1K (6 to 11M) | OOLONG (131K) | OOLONG-Pairs (32K, quadratic) |
|---|---|---|---|---|
| Base model | 24.0* ($0.13) | 0.0* | 44.0 ($0.14) | 0.04 ($0.16) |
| CodeAct + BM25 | 22.0* ($0.06) | 51.0 ($0.71) | 38.0 ($0.61) | 24.7 ($0.75) |
| Summary agent | 58.0 ($1.31) | 70.5 ($0.57) | 46.0 ($0.13) | 0.01 ($0.13) |
| **RLM** | 62.0 ($0.11) | **91.3** ($0.99) | **56.5** ($0.43) | **58.0** ($0.33) |
| RLM, no sub-calls | 58.0 ($0.18) | 88.0 ($0.44) | 36.0 ($0.37) | 43.9 ($0.69) |

(* = hit context limits.) S-NIAH (single needle, 2^13 to 2^20 tokens) is the easy control. RLMs did not need it, and on short inputs they were slightly worse than the base LM.

### Costs and failure modes the authors reported (v1, 2025-12-31)
- **Cost tail.** Median RLM runs are cheaper than the median base run, but the mean is higher because of outlier trajectories. The blog adds: "we do not currently have strong guarantees about controlling either the total API cost or the total runtime".
- **Blocking and no caching.** "Each recursive LM call is both blocking and does not take advantage of any kind of prefix caching." Latency ran from seconds to minutes.
- **Model-specific pathologies.** Qwen3-Coder issued sub-calls on nearly everything ("thousands" for simple tasks) until one warning sentence was added to the prompt. One system prompt did not transfer across models.
- **Answer brittleness.** Models put their plan inside FINAL. One Qwen3-Coder trace built the right answer in a variable, discarded it, re-verified five or more times, and returned a wrong answer it typed itself.
- **Weak coders fail.** Qwen3-8B struggled. Thinking models (Qwen3-235B) ran out of output tokens.
- **Counting** degrades with length (blog).

### How the paper grew (v2 2026-01-28, v3 2026-05-11)
- **v2** added **RLM-Qwen3-8B**. It was SFT'd on 1,072 filtered root-turn trajectories from RLM(Qwen3-Coder-480B) on 750 LongBench-Pro tasks, trained with prime-rl in about 48 H100-hours, and scored +28.3% on average over Qwen3-8B. Before patching, 16% of training turns misused FINAL and 13% misused FINAL_VAR.
- **v3** added a **depth ablation** and coding-agent baselines. Median gains for GPT-5: 26% over compaction, 130% over CodeAct with sub-calls, 13% over Claude Code.

| GPT-5 (v3) | CodeQA | BrowseComp+ | OOLONG | OOLONG-Pairs |
|---|---|---|---|---|
| RLM depth 0 | 58.0 | 88.0 | 36.0 | 43.9 |
| RLM depth 1 | 62.0 | 91.3 | 56.0 | 58.0 |
| RLM depth 2 | 66.0 | 92.0 | 56.5 | 65.5 |
| RLM depth 3 | 58.0 | 92.0 | 58.0 | 76.0 |
| Claude Code (Opus 4.1) + offloading | 62.0 | 84.0 | 48.0 | 6.5 |

For Qwen3-Coder, depths 2 and 3 were **worse** than depth 1 on CodeQA and OOLONG (CodeQA 56 → 54 → 44; OOLONG 48 → 26 → 32), partly because syntax errors propagate into sub-calls. Deep recursion only clearly pays on the quadratic task (OOLONG-Pairs) with a strong model.

---

## 2. Everything since

### 2.1 Follow-up papers (chronological)

| Paper (arXiv, date) | Who | Claim | Relevance |
|---|---|---|---|
| RLM-JB (2602.16520, 2026-02-18) | Shavit | Jailbreak detection as a bounded RLM procedure (normalize, chunk for coverage, parallel screening, aggregate). Recall 92.5 to 98% | Shows "procedure, not one-shot" for auditable decisions |
| Think, But Don't Overthink (2603.02615, 2026-03-03) | Wang (CUHK) | DeepSeek v3.2: S-NIAH 100 (base) → 85 (d1) → 70 (d2); OOLONG 0 → 42.1 → 33.7. Time 3.6s → 89s → 344.5s. Kimi K2 OOLONG 86.6 base vs 60 d1. One run, n=20 | Depth 2 hurts; RLM on easy retrieval hurts |
| SRLM (2603.15653, 2026-03-07) | Apple (Alizadeh, Shojaee, Cho, Farajtabar) | Recursion "contributes only marginal gains". GPT-5 OOLONG: RLM 53.0, no-sub-calls 50.5, SRLM 65.5. RLM often underperforms base under 131K | The REPL plus program selection matters most |
| VideoAtlas (2603.17948, 2026-03-18) | Eltahir et al. (affiliation unverified) | Video-RLM over a hierarchical grid; logarithmic compute, 30 to 60% cache hits | Structured environment to recurse into |
| λ-RLM (2603.20105, 2026-03-20) | Roy, Tutunov, …, Bou-Ammar (Huawei Noah's Ark **[med]**) | Typed λ-calculus combinators in place of free-form code; termination and cost bounds; beats RLM in 29 of 36 model-task pairs, up to +21.9 pts, up to 4.1x lower latency | Structured control beats open-ended code |
| LCM: Lossless Context Management (2605.04050, 2026) | Voltropy | Engine-managed LLM-Map plus a summary DAG with lossless pointers. Volt (Opus 4.6) beats Claude Code on OOLONG at 32K to 1M (avg 74.8 vs 70.3). Critiques RLM's variance and short-context penalty | Deterministic operators instead of model-written loops |
| Recursive Agent Harnesses (2606.13643, 2026-06-11) | PwC | The recursive unit is a full harness. Oolong-Synthetic (GPT-5): RLM 64.4, Codex 71.8, RAH 81.4; Sonnet 4.5 89.8. RLM "cannot open files, run code" in sub-calls | Sub-calls without tools are weak |
| COGNI (2606.28370, 2026-06-15) | Enterprise BI system | RLMs for multi-hop synthesis over documents (91.0%) next to NL2SQL for warehouses | Closest tabular-adjacent production report |
| RLMs Generalize Out of Domain (2609.20831, 2026) | Yang, Li, McAllester, Srebro (TTIC **[med]**) | Theory: context isolation rules out shortcut learning that CoT can fit; no IID advantage | Formal backing for "locally in-distribution" calls |
| TimeRLM (2608.03391, 2026-08-04) | Zumarraga et al., OpenTSLM group (affiliation **[low]**) | RLM for time-series anomaly localization: IoU 0.682 vs ≤0.329 baselines; RL post-training cuts turns to about a third | Domain transfer of the pattern to numeric signals |
| Chained RLM (2608.05124, 2026-08-05) | Mitra, Ulukus | Fresh roots with a blackboard and artifacts instead of history | Context-reset handoffs |
| RLMOpt (2608.10471, 2026-08-11) | Satheesha et al. | RLM-driven prompt optimizer beats GEPA in 9 of 11 seeded comparisons | RLM as a search policy |
| Prime Agent (2608.23552, 2026-08-24) | Prime Intellect and Zhang | RLM plus "Continual Harness" | Production harness (see 2.4) |
| SERA (2610.04902, 2026-10-04) | Lyu et al. | Parents write weighted rubrics for children; trained rubric generation drives the gains | Starting to fix "children's results are never checked" |
| Wikidata Search Traces (2610.06650, 2026-10-05) | Chenene et al. | RLM harness vs direct tool calling: gpt-6-luna 49 → 61, Qwen3.8-27B 60 → 74 | Persistent Python state plus batched calls wins over JSON tools |

### 2.2 RLM-trained models

| Model | Date | Method | Result | Notes |
|---|---|---|---|---|
| `mit-oasys/rlm-qwen3-8b-v0.1` (MIT) | 2026-01-15 | SFT on distilled trajectories (paper v2) | +28.3% avg over Qwen3-8B; "approaches vanilla GPT-5" on 3 tasks | Needs the RLM system prompt and scaffold |
| RLM(Qwen3-4B-Instruct) on MRCRv2 | paper v3 2026-05-11; MGH post 2026-04-09 | RL on 32k/2-needle, eval 512K to 1M/8-needle | About 0% → 100% on the hard split (MGH post) | Strongest "learned decomposition" evidence. The MGH post says 1-needle training and paper v3 says 2 needles |
| alphaXiv 4B (Qwen3.5-4B) | 2026-05-13 | Cold-start SFT then GRPO; **one shared policy for parent and child**; rubric judges | Multi-paper evidence selection 0.3 → 0.6; just short of Sonnet's 0.607; about 7s vs over 60s latency | Intro says "just as well as" Sonnet 4.6, body says short of it **[inconsistent in source]** |
| `mit-oasys/rlm-qwen3-30b-a3b-v0.1` (Apache-2.0 LoRA) | 2026-05-24 | RL (prime-rl), trained at depth 1, usable deeper | OOLONG 33.8 → 47.2; BrowseComp+ 11.6 → 29.7; CodeQA 22 → 42; **OOLONG numeric subset 4.9 (base 7.3) vs non-numeric 60.5** | Counting still fails after training |
| RL'd Qwen3-30B-A3B RLM (blog) | 2026-07-20 | 150 steps on short tasks, 6 envs | Generalizes to tasks 8 to 32x longer; about 10x the eval lift of training the plain Transformer; cross-domain (TREC→spam, essays→math) | Training runtime 1.5 to 3x a plain Transformer's |
| Community LoRAs (e.g. `lsteno/*RLM*`) | 2026-05 and 2026-06 | SFT and RL sweeps, including a depth-2 adapter | Unreported | The `lsteno` account is plausibly a TimeRLM author **[low]** |

Prime Intellect says "currently no model has been trained around Prime Agent" (2026-08-05). I found no frontier-lab model marketed as RLM-native. The closest analog is a **learned orchestration policy**: Kimi K2.5 trains the orchestrator (PARL) and keeps sub-agents frozen **[med: dates and figures secondary]**.

### 2.3 RL environments
- **Prime Intellect RLMEnv in `verifiers`** (2026-01-01). Design choices: tools usable only by sub-LLMs, `llm_batch` for parallel prompts, an `answer` dict with a `ready` flag in place of FINAL tags, sandboxes and pip installs, 8,192-character REPL output cap, depth exactly 1. Tested on DeepDive, math-python, Oolong and verbatim-copy with GPT-5-mini. The RLM **lost** on math-python and on DeepDive without tips, and increased time-to-completion in every environment.
- **By 2026-10** the verifiers v1 RLM harness runs Prime's `nano-rlm` over ACP. The kernel is the only tool. MCP tools become pre-imported IPython skills. It accepts SKILL.md paths and has a configurable `max_depth` (default 1). It adds **tree-wide budgets**: `max_total_tokens` (10M by default in the harness), `max_subagent_calls`, `max_total_turns`, and `max_concurrent_subagents` (default 4) with root-priority scheduling. Compaction keeps the kernel alive.
- **`alexzhang13/rlm/training/`** (2026-05-27): a `verifiers` env that maps 1:1 to `RLM.completion`, with no sandboxes (subprocess-isolated local REPL), plugged into prime-rl, with an OOLONG example.
- **SkyRL** (NovaSky) hosts alphaXiv's RLM scaffold and evidence-selection env.

### 2.4 Framework integrations and products
- **`rlms` (official, MIT).** PyPI 0.0.1a1 on 2026-01-18 through 0.1.3 on 2026-06-26. Environments: `local` (host `exec`, the default), `ipython` (in-process or subprocess kernel), `docker` (host proxy bridges LM calls into the container), `modal`, `prime`, `daytona`, `e2b`. Calls: `llm_query`/`llm_query_batched` and `rlm_query`/`rlm_query_batched` (depth > 1 with `max_concurrent_subcalls`). Also `custom_tools`, `persistent=True` multi-turn (`context_N`/`history_N`), `compaction=True`, a JSONL trajectory logger and a visualizer. Issue #127 (2026-02-27) shows **Claude 4.6 models hallucinate the REPL output and emit FINAL in the same turn**. The fix discards text FINALs when the response has code blocks.
- **`dspy.RLM`** (DSPy 3.1.1/3.1.2, 2026-01-19, marked experimental). Deno/Pyodide WASM sandbox, `llm_query_batched`, `SUBMIT(...)`, typed signatures, `max_iters=20`, `max_llm_calls=50`, `max_output_chars=10k`, a separate `sub_lm`, and optimizer-compatible (GEPA/MIPRO). Isaac Miller (2026-02-03) calls it "simply a new inference time strategy".
- **LangChain Deep Agents** (2026-07-01). A QuickJS interpreter dispatches subagents with `Promise.all` over `task()`. OOLONG/AgNews: 0.58 → 0.67 at 64k and 0.44 → 0.79 at 128k. Fewer tokens but higher cost and latency. "Coverage is guaranteed by code, not model judgment."
- **Google ADK** (community, 2026-01-23): lazy file references, parallel sub-agents, live event UI.
- **Prime Agent** (2026-08-05). A persistent IPython kernel is the only tool. `rlm(...)` is **async and returns a child handle** at admission, and results come back as messages. Sub-agents get their own kernel and history, persist, and can message parent, siblings and children. "Continual Harness" lets the agent CRUD its own prompts, skills, memory and subagent specs (`/refine`, rollback by ID). Self-reported results: ARC-AGI-3 95.5% RHAE with Opus 5. HN commenters note it is not on the official leaderboard, and a third party lists Opus 5's official score at 30.16% **[low/med]**. **Reward hacking** observed in Factorio, where the agent built cheating skills. Rewritten in Rust (2026-10-09).
- **Others.** Symbolica Agentica (2026-02-10): REPL agents with state-passing sub-agents; ARC-AGI-2 85.28% at $6.94/task with Opus 4.6 vs 79.03% CoT. Daytona "deep RLM" guide: unlimited depth, a sandbox per agent; one anecdotal run spawned 40 agents. Headlong (Laude Institute, 2026-04): Bash RLM `shellm`. HALO (context-labs): RLM over agent traces. Ax (TypeScript DSPy).

### 2.5 Frontier-lab adoption and analogous designs
- **Anthropic.** Programmatic tool calling (Nov 2025 beta, now GA on Opus/Sonnet 4.5+ and 5.x, requires `code_execution_20260120`+) keeps intermediate tool results out of context. "Code execution with MCP" (2025-11-04) reports 150k → 2k tokens on one example **[med: figure via secondary]**. "Managed Agents" (2026-04-08) describes the session as "a context object that lives outside Claude's context window" and cites prior work in which "context can be an object in a REPL that the LLM programmatically accesses". **Claude Code dynamic workflows** (docs current; launch about 2026-05-28 **[med]**): a JS script holds "the loop, the branching, and the intermediate results… so Claude's context holds only the final answer". It provides `agent()`, `parallel()`, `pipeline()` with JSON-schema outputs, up to 16 concurrent agents by default, 1,000 per run, prefix-cache staggering, and resumable runs. This is RLM's programmatic sub-calling, minus the context-as-variable piece, for coding work.
- **OpenAI.** Codex subagents (2026-03-16): "keep your main context window clean". A third-party guide says `agents.max_depth` defaults to 1 **[med]**.
- **Moonshot.** Kimi K2.5 Agent Swarm (Jan 2026): trainable orchestrator, critical-path reward, up to 100 subagents **[med]**.
- I found **no** OpenAI, Google or Anthropic product described as an RLM. The convergence is in mechanisms: code-held orchestration, offloaded context, and cheap parallel workers.

### 2.6 What changed in the paradigm itself

| Dimension | Oct 2025 | Oct 2026 |
|---|---|---|
| Depth | 1 (sub-calls are plain LMs) | Configurable (`rlm_query`, nano-rlm `max_depth`), but **default still 1** everywhere; evidence says depth 2+ rarely pays |
| Sub-call concurrency | Blocking, sequential | `llm_query_batched`, `rlm_query_batched`, async child handles (Prime), engine-managed LLM-Map (LCM), Claude Code `pipeline()` |
| What a sub-call is | A bare LM on a string | A full agent with its own kernel and tools (Prime, RAH, Daytona); a typed leaf in a combinator tree (λ-RLM) |
| Control | Free-form model-written code | Split: free-form (Prime, rlms) vs engine-managed operators (LCM, λ-RLM, Claude Code workflow runtime) |
| Recursion policy | Prompted | SFT (8B) → RL (4B, 30B-A3B, shared parent/child policy, rubric self-evaluation in SERA) |
| Termination | `FINAL`/`FINAL_VAR` text tags | FINAL_VAR preferred; `answer["ready"]` dict; `SUBMIT`; text FINAL ignored when code is present |
| Budgets | Iteration cap only | Tree-wide token, turn and sub-call caps with root priority (nano-rlm); `max_llm_calls` (DSPy); sandbox budgets (Daytona) |
| Latency tricks | None | Cheap sub-model; prefix caching across fan-out; sPTC speculation (measured **1 to 1.2x** on OOLONG) |
| Memory | Single query | Persistent multi-turn contexts, compaction with offloaded history, SKILL.md skills inside the REPL, self-editing harness (Prime) |
| Thesis | Long-context inference trick | "Harnesses are compositional generalizers": each call should be "locally in-distribution"; train the harness, not just the network |

---

## 3. Open-source landscape (GitHub, 2026-10-14)

| Repo | Stars | Created → last push | License | Verdict |
|---|---|---|---|---|
| PrimeIntellect-ai/prime-agent | 22,032 | 2026-05-08 → 2026-10-14 | MIT (LICENSE file; GitHub shows NOASSERTION) | **Serious, production.** Rust rewrite. HN critics call parts of the codebase bloated (10K-LOC files) |
| stanfordnlp/dspy (`dspy.RLM`) | 38,639 | → 2026-10-14 | MIT | **Serious**, but the RLM module is experimental |
| alexzhang13/rlm (`rlms`) | 5,696 (913 forks, 91 open issues) | 2025-12-20 → 2026-09-24 | MIT | **Reference.** Code releases stalled since 2026-06-26 |
| PrimeIntellect-ai/verifiers | 4,710 | → 2026-10-14 | MIT | **Serious** (RL envs; RLM harness) |
| ax-llm/ax | 2,967 | → 2026-10-13 | Apache-2.0 | Serious (TS DSPy; RLM support listed by rlm README) |
| NovaSky-AI/SkyRL | 2,420 | → 2026-10-14 | Apache-2.0 | Serious (alphaXiv RLM training) |
| laude-institute/headlong | 1,220 | 2026-04-07 → 2026-10-13 | Apache-2.0 | Research alpha (Bash RLM) |
| context-labs/HALO | 1,193 | 2026-04-21 → 2026-09-08 | MIT per README badge, no LICENSE detected | Useful niche tool (RLM over traces) |
| alexzhang13/rlm-minimal | 867 | 2025-10-16 → 2026-01-07 | MIT | Teaching gist |
| grishahq/recursive-llm | 611 | 2025-10-17 → 2026-10 | MIT | Mid, early community impl |
| avbiswas/fast-rlm | 479 | 2026-02-22 → 2026-08-24 | MIT | Mid (ACP, structured IO) |
| AsyncFuncAI/AsyncReview | 459 | 2026-01-24 → 2026-04-27 | MIT | App (code review) |
| lambda-calculus-LLM/lambda-RLM | 308 | 2026-03-19 → 2026-04-24 | MIT | Research code, dormant |
| viplismism/rlm-cli; Trampoline-AI/fractal | 210; 199 | 2026-03 and 2026-05 | MIT | CLIs, small |
| PrimeIntellect-ai/nano-rlm | 67 | 2026-03-27 → 2026-10-14 | MIT | Small but **well engineered** (versioned ACP contract, budgets, idempotency keys) |
| pydantic/monty | 8,664 | → 2026-10-14 | MIT | Rust Python sandbox Zhang asked about for RLM REPLs (2026-05-14); open PR #94 to add it |
| ~30 others (rand/rlm-claude-code, Tenobrus/claude-rlm, zircote/rlm-rs, EncrEor/rlm-claude, win10ogod/RLM-MCP, RLM-From-Scratch, rlm-go, …) | 10 to 110 | 2026 | many **no license** | **Toys or wrappers**: Claude Code plugins, MCP servers, ports |

Watch the license gaps. Several popular wrappers have no license file (rand/rlm-claude-code, Tenobrus/claude-rlm, fullstackwebdev/rlm_repl), which means all rights reserved. On HF, `mit-oasys` publishes the two official checkpoints (8B: MIT; 30B-A3B LoRA: Apache-2.0).

---

## 4. Debates and critiques

**"Isn't this just CodeAct / subagents / agent loops?"** HN 2025-10-15 and 2026-01-03 said so loudly, for example "MIT researchers found out about AI agents and rebranded it as RLM" and "a size 2 call stack… shouldn't be regarded as recursive". The authors' answer is narrow but real. CodeAct puts the prompt in context; RLM puts it in the REPL as an object and makes sub-calls functions in code, so a `for` loop can launch arbitrarily many. Their own CodeAct + sub-calls baseline scored far worse (OOLONG-Pairs 28.4 vs 58.0). Khattab (2026-01-02): "The deeper insight is LLMs *interacting with their own prompts as objects*." *Verdict:* the components are old, and the combination plus the evidence are the contribution **[high]**.

**Recursion vs programmatic access.** The paper's depth-0 rows, SRLM ("recursion contributes only marginal gains"), and the HN reading that recursion "only wins because they use a top-tier model for the root agent, and cheaper models for the sub-agents" (2026-08-06) all point the same way. Most of the gain comes from *offloading plus code*. Sub-calls help on semantic per-item labelling and quadratic pairing **[high]**.

**Depth > 1.** The reproduction shows overthinking, parametric hallucination, formatting collapse and up to 96x slowdowns. Qwen3-Coder gets worse with depth. GPT-5 gains only on OOLONG-Pairs. Every major implementation still defaults to depth 1 **[high that depth 2+ is not a general win for untrained models]**.

**Short inputs and cost tails.** RLMs are worse than the base model inside the window (paper; SRLM under 131K; LangChain at 64k "kept up reasonably well and was faster"; LCM's "short-context penalty"). Cost: median about base, mean higher. A practitioner reports p95 at 3 to 5x the median **[med]**. Weitekamp's LongCoT-mini run cost $621 vs $31 (about 20x). Prime saw longer time-to-completion in every environment **[high]**.

**Counting and numerics.** The blog flagged counting. The trained 30B RLM still scores 4.9 on OOLONG's numeric subset vs 60.5 on non-numeric. LMs should label and code should count **[high for the pattern; the numbers are single-source]**.

**Compositional / graph reasoning (LongCoT).** The LongCoT authors (2026-04) say RLMs don't beat GPT-5.2 because "context decomposition is different from task decomposition". Weitekamp (2026-04-16): dspy.RLM + Sonnet 4.5 went from 13/500 (2.6%) to 227/500 (45.4%) but scored about 0 on MaxFlow and Hindley-Milner. Zhang's post cites the baseline as 13.0%, a discrepancy I could not resolve. Zhang and Khattab (2026-04-26): RLM(GPT-5.2) went 38.7% → 50.6%, then 65.6% after Claude Code mined failure traces into tips. A tips-only ablation for the base model did worse. *Verdict:* RLM performance is **very prompt- and strategy-sensitive**, which cuts both ways **[med]**.

**Structured vs free-form control.** λ-RLM and LCM argue that model-written loops inherit stochasticity, offer no termination or cost guarantees, and should be replaced by typed combinators or engine-managed map operators. Each paper reports beating the RLM, on authors' own benchmarks **[med]**. Claude Code's workflow runtime takes the same side industrially: a deterministic script runtime with caps.

**Vs long-context models.** The 2025 gaps were measured against GPT-5 and Opus 4.1. Prime's Aug 2026 table shows Claude Code on Opus 5 at OOLONG 0.920 vs Prime Agent 0.900, and OOLONG-Pairs 0.922 vs 0.929. Codex on GPT-5.6 Sol lags at OOLONG 0.500 **[med: interested party]**. One HN builder (2026-08-05): "the foundational models have largely caught up to the point where they don't need this harness anymore… for my use cases". RLMs keep a clear edge only where input truly exceeds any window (BrowseComp+ at 6 to 11M tokens, multi-million-token corpora) **[med]**.

**Vs RAG.** Zhang to VentureBeat (2026-01-20): "I think RLMs work in tandem with standard retrieval methods like RAG". BM25 pre-retrieval baselines lost in the paper, but RAG remains far cheaper for lookups **[med]**.

**Vs ACE / agentic context engineering.** ACE evolves a persistent playbook across tasks (memory), while RLMs manage access to one input. They are orthogonal, and Prime files ACE under "context folding". The cross-task memory lesson belongs to Prime's "Continual Harness" and to crivo's skills, not to RLMs proper **[high]**.

**Vs Claude Code subagents.** The Mismanaged Geniuses post calls orchestrator-subagent scaffolds "a first step". RLMs widen the "space of decompositions" (a loop over N chunks rather than a few tool calls). Claude Code's dynamic workflows (2026-05) now provide exactly that loop in JS. Convergence is under way **[high]**.

### Hype check
| Claim | Status |
|---|---|
| "RLMs are the paradigm of 2026" (Prime, 2026-01-01; Zhang 2026-01-02) | Partly true in research, with dozens of follow-ups and two trained-RLM releases. Not true as a product category, where the ideas got absorbed into coding agents **[med]** |
| "10M+ tokens" | Substantiated for retrieval and aggregation (BrowseComp+); weak for reasoning over the whole input **[high]** |
| "Beats Claude Code by 13%" | True for paper v3's Opus 4.1 setup; not evidenced against 2026-era Claude Code **[med]** |
| "RLM-trained small models match frontier" | 8B "approaches" GPT-5 on 3 tasks (paper); alphaXiv 4B falls short of Sonnet in its own body text; 30B approaches GPT-5.5-RLM on 4 of 6 long evals (blog) **[med]** |
| "95.5% ARC-AGI-3" (Prime Agent + Opus 5) | Self-reported on the public set; not on the official leaderboard as of 2026-08-05 **[low confidence in the claim]** |

---

## 5. Social and practitioner signal

X blocked direct fetches, so the X posts below come from search snippets. I decoded dates from the post IDs. Reddit blocked both search and fetch, so **no Reddit signal could be gathered**.

- **Omar Khattab (@lateinteraction).** 2025-10-15: "I think Recursive Language Models may be the next one" (an inference-scaling axis), and the note that Alex did it "in 4 weeks". 2026-01-02: "Most people (mis)understand RLMs to be about LLMs invoking themselves. The deeper insight is LLMs *interacting with their own prompts as objects*." 2026-02-18: "folks are winning competitions and topping leaderboards left and right with RLMs" (pointing to TreeHacks winner Monolith). 2026-05-27: Alex is "open-sourcing some RL code for RLMs and a small recursive MoE model".
- **Alex Zhang (@a1zhang).** 2026-01-02: RLMs are "our bitter-lesson-pilled approach to inference-time scaling". 2026-01-03: he shipped the repo early "to get better community feedback". 2026-05-27: training harness and RLM-Qwen3-30B-A3B. 2026-08-05: Prime Agent "is really good despite not having any models" trained for it. To VentureBeat: "Today, you likely will have to implement your own guardrails and logic to control RLM behavior."
- **Prime Intellect (2026-01-01).** Calls the RLM "the simplest, most flexible method for context folding" and bets "the true potential… will be unleashed after being train[ed] via RL".
- **HN, blog thread (2025-10-15, 135 pts, 35 comments).** "This is old news! Agent-loops are not a model architecture." "I'm struggling to see what ideas it brings beyond CodeAct… or the 'task' tool in Claude code." Someone noted ViperGPT as prior art. One practitioner: "Tell it to use subagents more… it can run easily for 60-90 minutes before a compaction."
- **HN, arXiv thread (2026-01-03, 161 pts).** "How is this fundamentally different from RAG?… the LLM is responsible for implementing the retrieval mechanism." "Isn't this just subagents?" with the reply "sub-agents that access (and manipulate) the SAME context". A plea: "Anthropic / OpenAI expose 'how compaction is executed' to plugin authors."
- **HN, Prime Agent (2026-08-05, 254 pts).** "Neat, but not revolutionary. Another version of what most of these systems are already doing." "Foundational models have largely caught up." Code-quality criticism (1,000-line switch statements). "PrimeIntellect is not on official ARC-AGI-3 leaderboard." "This seems like it's going to rip through tokens like crazy."
- **Builders' blogs.** Isaac Miller (2026-02-03): needs strong reasoning-plus-coding models (GPT-5, Opus; "surprised by Kimi K2"), and budgets need tuning. Raymond Weitekamp (2026-04-16): RLMs "excel when dependencies can be expressed as code". Petros Lamb (2026-01-14): "Passing large dataframes to a containerized RLM requires serialization… that overhead accumulates." LangChain (2026-07-01): RLM agent "used fewer tokens but cost more". Google ADK forum commenters (2026-01 to 06): cost growth, nested-run observability, need for explicit depth and token limits. AI Engineer talk by Kevin Madura (AlixPartners): RLMs "outperform RAG and agent approaches" **[low: via podcast summary]**.
- **Trend reading.** Enthusiasm peaked Jan to Feb 2026 and shifted from "RLM as inference trick" to "RLM as harness to train" (May to Jul 2026). By Aug to Oct 2026, practitioner talk moved to product harnesses (Prime Agent, Claude Code workflows), with skepticism about novelty and tokens **[med]**.

---

## 6. Implications for crivo

### 6.1 Where crivo sits on the RLM map (from reading `loop.py`, `kernel/`, `prompts.py`)

| RLM element | crivo today | Read |
|---|---|---|
| Context as a variable, model sees only probes | Datasets are kernel `DataFrame`s; the model sees `profile_df` (3 samples, 80-char cells), the `<registry>` block, and clipped observations (`OBS_CLIP=2000`, supervisor `VALUE_CAP=8KiB`, traceback head and tail) | **Same idea, stricter.** RLM's default `local` env and its examples freely `print(context)` |
| Persistent REPL | IPython via jupyter_client behind an NDJSON supervisor; Docker `--network none`, `--cap-drop ALL`, read-only root, pids and memory limits | **Stronger sandbox** than `rlms` local (host `exec`), DSPy's Pyodide, or Prime's process isolation |
| Sub-LM calls from code (`llm_query`) | **None.** The kernel has no network and no LM handle. Host-side "scoped" calls exist only for the intent check (`_intent_check`) and history compaction | In paper terms crivo is a **depth-0 RLM** plus a host-side verifier call |
| Depth cap | `_skill_pass` (loop.py:1891): "a fix a skill produced never spawns another skill. That is the depth-1 recursion cap" | **Different concept**, same words. The README says "Recursion is capped at one level", which an RLM reader will take to mean sub-calls exist |
| Termination | Exactly one of `<execute>`/`<answer>` per response, otherwise malformed; final cell must set `result` and end in 1 to 3 asserts; checks lifted into the card | Equivalent to FINAL_VAR plus verification; **ahead** |
| Iteration budget | `MAX_ITERS=6` cells per question, a forced answer at the cap | Tight vs DSPy 20, Daytona 50 and Weitekamp's 50, but deliberate because every cell is human-gated |
| Verification of intermediate results | Detector re-fires after each fix, revert on failure, row and untouched-column invariants, asserts, intent check | **Ahead.** RLMs "would rarely check whether the sub-agent actually got the sub-problem correct" (Zhang, 2026-04-26). SERA (2026-10) is only now training this |
| Learned procedures | SKILL.md skills, test-gated plus human-gated, probation, retirement | **Ahead on safety** vs Prime's self-refinement, which reward-hacked |
| Compaction | Lossy summary at 60k chars; dataset blocks protected verbatim | **Behind** RLM v0.1.1a (offloaded history), LCM (lossless pointers), Prime (kernel survives) |
| Model split | One model for root and housekeeping | **Behind**: the RLM cost trick is an expensive root with cheap sub-calls |
| Parallelism | None; A3.1 read-only fan-out dropped because "the measured payoff was near zero" | **Consistent with evidence**: RLM sub-calls dominate time, and the sequential root is the bottleneck |

### 6.2 Ranked recommendations

The owner tag follows CLAUDE.md. **[core]** means the loop, skill lifecycle, provenance or prompts: propose a diff to Aarmen. **[plumbing]** means bench, docs and tests, which Claude can own.

**Adopt**

1. **Fix the vocabulary.** [plumbing for README, core for the loop.py comment wording] Replace "Recursion is capped at one level" with something like: "No skill can spawn a skill. The model has no in-kernel sub-model calls (depth 0 in RLM terms)." Cost: minutes. Why: every RLM-literate reviewer will otherwise assume sub-calls exist and that crivo chose depth 1. Confidence high.
2. **Close the hallucinated-observation hole.** [core] Add `stop=["</execute>"]` (re-append the tag), or truncate everything after `</execute>` before `self.history.append`. Today the full response goes into history (loop.py `run_turn`), and `llm.py` sets no stop sequence. A model that keeps generating fake output after the cell (rlm issue #127, Claude 4.6) leaves invented numbers in context next to the real `<observation>`. crivo's exactly-one-tag rule already blocks the worst case, a same-turn `<answer>`, which `rlms` had to patch. Write a fail-first test with a canned response. Low effort, high value.
3. **FINAL_VAR-style grounding for answer cards.** [core] Add a deterministic check that the headline numbers in the `<answer>` prose appear in the final `result` value's repr, and flag the card if not. This addresses the paper's documented failure (the root typed a wrong answer while the right one sat in a variable) and is cheaper than the intent check. Low to medium effort.
4. **Use a cheap model for housekeeping calls.** [core, small] Run `_intent_check` and `_compact_history` through `_generate_scoped` on a smaller model (`CRIVO_SUB_MODEL`). This is RLM's main cost lever, and the HN critique says the root/sub split is where the gains come from. Gate it on a bench arm showing intent-verdict agreement holds. Low effort.
5. **A governed `llm_map` primitive for semantic per-value work.** [core, needs a WRAP spec] This is the substantive import.
   - *Gap.* crivo cannot do OOLONG-shaped work: label each item, then aggregate. Examples are "how many complaints mention billing?" over a free-text column, or mapping 3,000 job-title spellings to canonical classes. The diseases with a semantic component are case-spelling-variants (7), near-duplicates (10), field-contradictions (12), out-of-domain (13), unit-heterogeneity (16), packed-fields (17), aggregate-rows (21) and stray-structural-rows (24). The paper's own ablation shows the loss without sub-calls is concentrated on exactly these semantic-labelling tasks (GPT-5 OOLONG: 36 without sub-calls vs 56 with).
   - *Design.* Make it an **engine-managed operator, not free-form recursion**, in the λ-RLM and LCM direction, the evidence-backed side of §4. A cell calls `llm_map(series.unique(), instruction, schema)`. The host intercepts it (the kernel stays network-less) and **dedups to distinct values**, a tabular advantage RLMs on text don't have. The gate shows the column, the distinct count, the model, the destination and an estimated cost. Values pass a PII screen first (`pii.py` exists). Outputs are schema-validated, then cached by (value, instruction hash, model) so replays and provenance are exact. The lineage stamps "N values labelled by model X". A random sample is spot-checked by a second model or a person, the way a fix is verified. Sub-calls get no tools and no recursion. **pandas does the counting**, which plays to the RLM numeric-subset finding (4.9 vs 60.5).
   - *Tradeoff.* This crosses crivo's "never raw rows to the model" line in bulk. crivo already shows samples and `value_counts` output, so it's a change of degree, but a real one. Make it opt-in per column, person-graded the first time, and off in headless mode. Medium to large effort, high capability gain. Don't build it before item 10 shows the gap on a bench.
6. **Tree-wide budgets and cost-tail reporting.** [core for the budget; plumbing for the bench] If item 5 lands, enforce a per-question token and cost budget on the host, nano-rlm style, regardless of what the model asks for. In the bench (A4.3 already plans cost and wall-clock columns), report **p50 and p95** cost and time, not means. The whole RLM literature shows means hide the tail. Low to medium effort.
7. **Lossless compaction pointers.** [core] Keep the summary, but have it cite card ids and transcript event ids, and give the model a host-side way to re-open a prior card. Cards are already on disk with their numbers. This follows LCM's "lossless pointers" and RLM's offloaded `history_N`. Medium effort, and it matters only for long QUERY sessions.
8. **Trace-mined tips, gated by the bench.** [core for prompts; plumbing for mining] Mine failed bench transcripts into per-disease CLEAN_PROMPT addenda and keep only the ones that raise bench scores. Evidence: LongCoT-mini went 38.7 → 65.6 with Claude-Code-written tips (2026-04-26), and Prime's "RLM + tips" arm beat plain RLM. Medium effort. The risk is overfitting to the synthetic corpus, so hold out the 4 external datasets.

**Benchmark against**

9. **An RLM arm in the agent bench.** [plumbing] Run `rlms` (`ipython` env; local subprocess, since Docker is off-limits on this Mac per the owner's note) and/or `dspy.RLM` with the **same model** (DeepSeek v4-pro) on crivo's QUERY tasks. Report accuracy, p50/p95 cost, and **bytes of raw cell values sent to the model**. That makes crivo's privacy posture a measured column, not a claim. Expect DeepSeek formatting trouble in RLM harnesses: Prime saw "wrong function-calling format", and the reproduction lost OOLONG to formatting. That is itself a crivo point, since the tag-and-nudge protocol already handles it.
10. **An OOLONG-shaped tabular suite.** [plumbing] Recast OOLONG `trec_coarse`/real items as a DataFrame with a free-text column plus aggregate questions. Current crivo should fail these honestly. This is the acceptance test for item 5. Add DABstep (Adyen/HF, arXiv 2506.23719, about 450 multi-step data-analysis tasks) for QUERY mode, a public number crivo lacks.
11. **Ship the bench as a `verifiers` environment.** [plumbing] crivo's detectors are verifiable rewards for cleaning. The RLM training community trains on OOLONG, LongBench-Pro and MRCR, and I found no data-cleaning environment on the Environments Hub **[low: did not browse the Hub directly]**. This gives crivo distribution and the referee positioning, and possibly free model improvements later. Medium effort.

**Avoid**

- **Depth > 1 or any self-spawning.** The evidence is consistently negative or mixed for untrained models (§4). crivo's flat design is right, so keep the skill-spawn cap.
- **Free-form model-written orchestration for fixes.** The deterministic router (`router.py`) and per-finding fix mini-turns already match the "locally in-distribution" ideal: one disease, its evidence, one fix. The λ-RLM, LCM and Claude-Code-runtime side of the debate favors this.
- **Speculation.** sPTC measured 1 to 1.2x on RLMs. Under human gates, speculative sub-calls would send data before approval. Deprioritize A2.3 "speculative drafting during gate waits" unless approval-rate data is extreme.
- **Parallel fan-out for speed.** Already dropped (A3.1) on crivo's own measurement, and RLM timing data agrees.
- **Sub-agents with their own kernels (Prime, RAH style).** This is overkill for single-table work and multiplies sandbox and serialization cost (Lamb's dataframe note). Revisit only for family mode if per-slice work becomes the bottleneck.
- **A large rise in `MAX_ITERS`.** Long trajectories are where RLM cost tails come from. Instead, measure how often QUERY hits the 6-cell cap (`flags.capped`) on the bench and raise it only if that rate is material.
- **RLM branding, and training a model now.** RLM-Qwen3-8B needed only about 1k trajectories and 48 H100-hours, so it's feasible. But crivo's bottleneck is correctness on variety (per the Phase 6 notes), not the policy model.

### 6.3 Honest scorecard

- **Ahead:** execution-gated verification of every step (detector re-fire, revert, asserts, intent check); the answer protocol (exactly-one-tag, `result` plus asserts) that sidesteps two documented RLM failure modes; a real network-less sandbox; governed, test-gated skills where Prime's self-editing harness reward-hacked; provenance and lineage beyond trajectory logs; a human-defined, typed decomposition space (22-plus-check taxonomy → router → fixer → verifier), which is the λ-RLM idea applied to tables.
- **Behind:** no semantic per-value capability over text columns; a single model for all calls; lossy compaction; no batched or async primitives (only matters after item 5); no public benchmark numbers on any standard data-agent or long-context suite; no evaluation against an RLM baseline, so the "verified" story isn't yet shown to cost less accuracy than an unverified RLM, or to buy more.
- **Neutral:** the 6-cell budget and per-cell human gate make crivo slow per question by design. RLM-style long exploration would cost human attention, not just tokens. That price is real and should be measured (the governed-vs-ceiling arm already does this for CLEAN).

---

## Open questions

1. Does NeurIPS 2026 list the paper? (Authors say yes; OpenReview blocked verification.)
2. Will any frontier lab train a model natively for a REPL harness (context-as-variable plus programmatic sub-calls), or will "dynamic workflows"-style runtimes make that moot?
3. Do RL-trained RLMs fix counting, or is "LM labels, code counts" a permanent split? The 30B result suggests the latter so far.
4. For crivo: how large is the semantic gap in practice? Run item 10 before building item 5.
5. Is a distinct-value `llm_map` acceptable under crivo's privacy posture with a local model (Ollama path) as the default sub-model? That would keep values on the machine.
6. Independent replication of Prime Agent's long-context table and the ARC-AGI-3 claim.
7. Reddit sentiment could not be checked (blocked).

---

## Sources

**Primary: the RLM work itself**
- Zhang, "Recursive Language Models" blog — https://alexzhang13.github.io/blog/2025/rlm/ (2025-10-15)
- Paper arXiv 2512.24601: v1 https://arxiv.org/abs/2512.24601v1 (2025-12-31), v2 https://arxiv.org/abs/2512.24601v2 (2026-01-28), v3 https://arxiv.org/html/2512.24601v3 (2026-05-11)
- Official repo — https://github.com/alexzhang13/rlm (created 2025-12-20; README cites NeurIPS 2026, 2026-09-24); issue #127 https://github.com/alexzhang13/rlm/issues/127 (2026-02-27); PyPI `rlms` https://pypi.org/project/rlms/ (0.1.3, 2026-06-26)
- rlm-minimal — https://github.com/alexzhang13/rlm-minimal (2025-10-16)
- HF weights — https://huggingface.co/mit-oasys/rlm-qwen3-8b-v0.1 (2026-01-15); https://huggingface.co/mit-oasys/rlm-qwen3-30b-a3b-v0.1 (2026-05-24)
- Zhang, "Language Models will be Scaffolds" — https://alexzhang13.github.io/blog/2026/scaffold/ (2026-02-25)
- Zhang, Li, Khattab, "The Mismanaged Geniuses Hypothesis" — https://alexzhang13.github.io/blog/2026/mgh/ (2026-04-09)
- Zhang, Khattab, "RLMs on LongCoT" — https://alexzhang13.github.io/blog/2026/longcot-rlm/ (2026-04-26)
- Zhang, Khattab, "Language model harnesses are compositional generalizers" — https://alexzhang13.github.io/blog/2026/harness/ (2026-07-20)
- Zhang, "Speculative Programmatic Tool Calling" — https://alexzhang13.github.io/blog/2026/spec-ptc/ (2026-08-23/24); repo https://github.com/alexzhang13/spec-ptc
- Zhang, "Language Model Shape" — https://alexzhang13.github.io/blog/2026/shape/ (2026-09-26)
- X posts (via search snippets; dates from post IDs): Khattab https://x.com/lateinteraction/status/1978471277149970824 (2025-10-15), https://x.com/lateinteraction/status/2007212972721275281 (2026-01-02), https://x.com/lateinteraction/status/2023926950159364379 (2026-02-18), https://x.com/lateinteraction/status/2059644669550797017 (2026-05-27); Zhang https://x.com/a1zhang/status/2007198918891974661 (2026-01-02), https://x.com/a1zhang/status/2007566581409144852 (2026-01-03), https://x.com/a1zhang/status/2059633834094678173 (2026-05-27), https://x.com/a1zhang/status/2085089855541813350 (2026-08-05)

**Primary: Prime Intellect**
- "Recursive Language Models: the paradigm of 2026" — https://www.primeintellect.ai/blog/rlm (2026-01-01)
- "Prime Agent: A self-improving RLM agent" — https://www.primeintellect.ai/blog/prime-agent (2026-08-05); tech report arXiv 2608.23552 https://arxiv.org/abs/2608.23552 (2026-08-24); repo https://github.com/PrimeIntellect-ai/prime-agent
- verifiers RLM harness — https://github.com/PrimeIntellect-ai/verifiers (verifiers/v1/harnesses/rlm/harness.py, commits to 2026-10-14)
- nano-rlm — https://github.com/PrimeIntellect-ai/nano-rlm (2026-03-27 → 2026-10-14)

**Primary: follow-up papers**
- Think, But Don't Overthink — https://arxiv.org/abs/2603.02615 (2026-03-03)
- SRLM — https://arxiv.org/abs/2603.15653 (2026-03-07)
- λ-RLM — https://arxiv.org/abs/2603.20105 (2026-03-20); https://github.com/lambda-calculus-LLM/lambda-RLM
- LCM: Lossless Context Management — https://arxiv.org/abs/2605.04050 (2026)
- RLM-JB — https://arxiv.org/abs/2602.16520 (2026-02-18)
- VideoAtlas — https://arxiv.org/abs/2603.17948 (2026-03-18)
- Recursive Agent Harnesses — https://arxiv.org/abs/2606.13643 (2026-06-11)
- COGNI — https://arxiv.org/abs/2606.28370 (2026-06-15)
- RLMs Generalize Out of Domain — https://arxiv.org/abs/2609.20831 (2026)
- TimeRLM — https://arxiv.org/abs/2608.03391 (2026-08-04)
- Chained RLMs — https://arxiv.org/abs/2608.05124 (2026-08-05)
- RLMOpt — https://arxiv.org/abs/2608.10471 (2026-08-11)
- SERA — https://arxiv.org/abs/2610.04902 (2026-10-04)
- Wikidata Search Traces — https://arxiv.org/abs/2610.06650 (2026-10-05)
- alphaXiv, "Reinforcing Recursive Language Models" — https://www.alphaxiv.org/blog/reinforcement-learning-for-rlms (2026-05-13)

**Primary: benchmarks and background**
- OOLONG — https://arxiv.org/abs/2511.02817 (2025-11-04)
- LongCoT — https://arxiv.org/abs/2604.14140 (2026-04-15)
- LongBench Pro — https://arxiv.org/abs/2601.02872 (2026-01-06)
- CodeAct — https://arxiv.org/abs/2402.01030 (2024-02-01)
- ACE — https://arxiv.org/abs/2510.04618 (2025-10-06)
- DABstep — https://arxiv.org/abs/2506.23719 (2025-06)
- Chroma, Context Rot — https://www.trychroma.com/research/context-rot (2025-07)

**Primary: frameworks and labs**
- DSPy RLM docs — https://dspy.ai/current/api/modules/RLM/ ; release 3.1.1/3.1.2 https://github.com/stanfordnlp/dspy/releases (2026-01-19)
- Isaac Miller, "DSPy is the easiest way to use RLMs" — https://blog.isaacbmiller.com/posts/rlm (2026-02-03)
- LangChain, "How to Use RLMs in Deep Agents" — https://www.langchain.com/blog/how-to-use-rlms-in-deep-agents (2026-07-01)
- Anthropic, Programmatic tool calling docs — https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling (GA, current)
- Anthropic, "Introducing advanced tool use" — https://www.anthropic.com/engineering/advanced-tool-use (2025-11)
- Anthropic, "Code execution with MCP" — https://www.anthropic.com/engineering/code-execution-with-mcp (2025-11-04)
- Anthropic, "Scaling Managed Agents" — https://www.anthropic.com/engineering/managed-agents (2026-04-08)
- Claude Code dynamic workflows docs — https://code.claude.com/docs/en/workflows (current, 2026-10)
- OpenAI Devs, Codex subagents — https://x.com/OpenAIDevs/status/2033636701848174967 (2026-03-16)
- Kimi K2.5 blog — https://www.kimi.com/blog/kimi-k2-5 (2026-01)
- Symbolica, Arcgentica — https://www.symbolica.ai/blog/arcgentica (2026-02-10)
- Daytona, deep RLM guide — https://www.daytona.io/docs/en/guides/rlm/recursive-language-models/ (2026, undated)
- Headlong — https://github.com/laude-institute/headlong (2026-04-07 →)
- HALO — https://github.com/context-labs/halo (2026-04-21 →)
- Monty — https://github.com/pydantic/monty

**Secondary and community**
- Google ADK community article — https://discuss.google.dev/t/recursive-language-models-in-adk/323523 (2026-01-23)
- InfoQ — https://www.infoq.com/news/2026/01/mit-recursive-lm/ (2026-01-20)
- VentureBeat — https://venturebeat.com/orchestration/mits-new-recursive-framework-lets-llms-process-10-million-tokens-without (2026-01-20)
- MarkTechPost — https://www.marktechpost.com/2026/01/02/recursive-language-models-rlms-from-mits-blueprint-to-prime-intellects-rlmenv-for-long-horizon-llm-agents/ (2026-01-02)
- Raymond Weitekamp, LongCoT-mini with dspy.RLM — https://raw.works/longcot-a-benchmark-worthy-of-a-rlms-attention/ (2026-04-16)
- Petros Lamb, Rooted Layers — https://lambpetros.substack.com/p/when-the-llm-programs-its-own-thinking (2026-01-14)
- HN threads — https://news.ycombinator.com/item?id=45596059 (2025-10-15, 135 pts), https://news.ycombinator.com/item?id=46475395 (2026-01-03, 161 pts), https://news.ycombinator.com/item?id=46485905 (2026-01-04), https://news.ycombinator.com/item?id=49189075 (2026-08-05, 254 pts), https://news.ycombinator.com/item?id=50027694 (2026-10-09, 64 pts), https://news.ycombinator.com/item?id=48649137 (HALO, 2026-06-23)
- Codex subagent defaults (third-party) — https://www.firecrawl.dev/blog/codex-multi-agent-orchestration (2026)
- Claude Code dynamic-workflows launch date (third-party) — https://trilogyai.substack.com/p/claude-codes-dynamic-workflows-a (2026-05)

**crivo files read:** `CLAUDE.md`, `README.md`, `src/crivo/loop.py` (run_turn, _compact_history, _intent_check, _skill_pass, _generate_scoped, _observation), `src/crivo/kernel/{bootstrap,supervisor,client}.py`, `src/crivo/prompts.py`, `src/crivo/llm.py` (model defaults, no stop sequences), `src/crivo/router.py`, `src/crivo/pii.py`, `src/crivo/profile.py`, `src/crivo/detect.py` (disease list), `specs/2026-09-04-agent-system-roadmap.md`, `specs/2026-09-06-master-plan.md`, `specs/2026-09-03-agent-bench-design.md`, `docs/research/2026-09-04-mailo-prime-agent-mining.md`.
