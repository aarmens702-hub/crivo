# How agents work with tables, and the AI-analyst landscape (2026-10-23)

Read-only research for crivo. Live web search and fetch on 2026-10-23, plus the GitHub
and PyPI APIs for repo and package facts (stars, licences, last push, last release,
dependencies). Nothing in the repo was edited. No paid model calls.

**Scope.** Table reasoning research, tabular foundation models, open-source dataframe and
SQL agents, semantic layers, MCP data servers, notebook agents, the commercial
AI-analyst products, and agent-friendly data formats. Out of scope, because other agents
cover them: data cleaning and repair research, agent verification and evals, sandboxing,
prompt injection, context engineering.

**Builds on** `docs/research/2026-10-14-landscape-sweep.md` section 3 (the labs' analyst
products, Hex DataBench, TabPFN-3.5's licence, DuckDB 2.0 and Polars 2.0 previews). This
report checks those items against primary sources where it could and goes deeper on
research, repos and formats.

**How to read the tags.** An untagged claim was read from a primary source during this
session: a paper, the vendor's own page or docs, the GitHub or PyPI API. **[high] / [med] /
[low]** marks a claim from a secondary source, or a primary source I cite from memory
without re-fetching it today. Star counts and push dates come from the GitHub API on
2026-10-23.

**Access limits.** openai.com and help.openai.com returned 403, so OpenAI items come from
search snippets of those pages [med]. Hex's pricing page was not reachable; the pricing
figures are from trackers [low-med]. I could not extract text from the SemEval-2025 Task 8
overview PDF, so I used its abstract page and the participants' papers.

---

## TL;DR: the ten findings that matter most

1. **The research converged on crivo's design: profile plus executed code, not serialised
   tables.** Large-table QA moved from feeding the table to the model (Binder, DATER,
   Chain-of-Table, 2022-2024) to code over a compact schema: TableRAG (NeurIPS 2024),
   TableZoomer (Sep 2025), the SemEval-2025 Task 8 systems, and DataGovBench (Jul 2026).
   Anthropic's "code execution with MCP" (Nov 4, 2025) gives the same advice for agents in
   general: keep intermediate data in the execution environment.
2. **What goes into the profile matters more than how much.** In DataGovBench's ablation
   (arXiv 2607.06482, Jul 7, 2026), schema statistics added nothing (0.310 to 0.308), and
   more rows hurt (up to 200 rows: 0.275). A *feature-type-specific* serialisation was the
   biggest gain (0.360), and reflection plus self-correction took it to 0.393. That
   serialisation lists every category when there are 20 or fewer, otherwise 20 random
   distinct ones; min and max for numbers and dates; 10 random distinct values for every
   other type; nothing for URLs. crivo's profile shows the *first 3* non-null values and
   the top 3.
3. **Which rows you show matters on messy data.** Microsoft's "cluster-then-select"
   (NAACL 2024 Findings) beats random row choice when the column's formats vary a lot.
   That is crivo's case exactly: mixed date formats, units, sentinels. First-N sampling
   is the weakest choice for messy files.
4. **Licences rule out TabPFN as a crivo default. Three permissive tabular FMs now exist.**
   TabPFN-2.5, 2.6, 3 and 3.5 weights are non-commercial, *including their outputs*, and
   need a Prior Labs login to download. Permissive options: TabICLv2 (BSD-3 code and
   weights, ICML 2026), NVIDIA Kumo Tabular (OpenMDW-1.1, Sep 2026, with community ONNX
   ports), Mitra (Apache-2.0) and TabDPT (Apache-2.0). Every one needs torch (127 MB on
   macOS arm64, 555 MB on Linux x86_64), so any of them can only be an opt-in extra.
5. **Zero-shot outlier and imputation FMs exist, but nothing can re-check what they
   output.** Examples: OUTFORMER (ICML 2026), FoMo-0D (TMLR 2025), TabImpute (2026,
   built on TabPFN), and tabpfn-extensions' `outliers()` and `impute()`. At most they are
   a source of findings for crivo, never of verified fixes.
6. **Several well-known open-source dataframe agents are dead or dormant.** Vanna (23.8k
   stars) was archived on GitHub on 2026-02-02. pandas-ai (23.9k) has had no push since
   2025-10-28, and v3.0.0 pins `pandas<3`, `numpy<2` and `scipy==1.10.1`. LIDA's last push
   was 2024-08. TaskWeaver is archived. Active: Data Formulator (17.6k, MIT, uses DuckDB),
   DB-GPT (20.2k, MIT), WrenAI (18k; relicensed from AGPL-3.0 to Apache-2.0 for its core
   in May 2026), and DeepAnalyze (4.7k, MIT).
7. **DuckDB 2.0 LTS (Oct 21, 2026) ships an "agent mode".** It prints compact Markdown
   tables, flags truncated results, reports errors as JSON and estimates the cost of a
   query before running it. It cut the output the model had to read by 59% on TPC-H.
   That is crivo's observation-design problem, solved in a database CLI. Caveat: files
   written by 2.0 can't be read by older DuckDB versions.
8. **On warehouses, "verified" now means curated reference queries.** Examples: Databricks
   Genie's *trusted assets* and benchmarks, Snowflake Cortex Analyst's *Verified Query
   Repository* and evaluations, Fabric's evaluation SDK, Hex's evals CLI, and Claude
   Dashboards' "show the SQL behind every chart". All of these need a curated semantic
   model or reference SQL, which a messy export never has. That gap is crivo's opening.
9. **The documented failure rates are high wherever someone measured them.** Hex
   DataBench (Aug 13, 2026): traps average 54%. SpreadsheetBench 2 (Jun 2026): the best
   model scores 34.89%, debugging 12%. Excel Agent Mode: 57.2% against 71.3% for humans.
   Microsoft warned users off its Excel `COPILOT()` function for numerical work, then
   retired it [med]. OpenAI's help page tells users to review the code, outputs and
   assumptions themselves [med].
10. **Agent-friendly formats crivo can adopt without dependencies.** Frictionless Data
    Package v2 / Table Schema (Unlicense spec, Jun 2024) for cleaned outputs. ODCS v3.1-3.2
    (Apache-2.0; v3.2.0 Sep 8, 2026 added an "AI context" section) for the project
    contract. PROV-O-shaped lineage, the model Croissant 1.1 uses. MCP `structuredContent`
    with an `outputSchema` (loosened to any JSON Schema 2020-12 in the 2026-07-28 spec).
    Skip CSVW: its W3C working group and community group are closed, and the `w3c/csvw`
    repo is archived.

---

## 1. Table reasoning and understanding research, 2023-2026

### 1.1 The arc: from serialising the table to running code over a schema

| Work | Date, venue | What it does | What it means for crivo |
|---|---|---|---|
| Binder ([arXiv 2210.02875](https://arxiv.org/abs/2210.02875)) [high] | Oct 2022, ICLR 2023 | Parses a question into SQL or Python extended with calls back to the LM | Early hybrid of code and model; needs table cells in the prompt |
| DATER ([arXiv 2301.13808](https://arxiv.org/abs/2301.13808)) [high] | Jan 2023, SIGIR 2023 | Breaks a big table into sub-evidence and the question into sub-questions | Decomposition for tables that *almost* fit in context |
| StructGPT ([arXiv 2305.09645](https://arxiv.org/abs/2305.09645)) [high] | May 2023, EMNLP 2023 | An iterative read-then-reason loop over table, KG and DB interfaces | An early "interfaces instead of dumps" design, like crivo's kernel |
| TableGPT ([arXiv 2307.08674](https://arxiv.org/abs/2307.08674)) [high] / TableGPT2 ([arXiv 2411.02059](https://arxiv.org/abs/2411.02059)) | Jul 2023 / Nov 2024 | Fine-tuned table LLMs (7B and 72B) with a table encoder and an agent workflow | Specialised models; crivo stays model-agnostic |
| TableLlama ([arXiv 2311.09206](https://arxiv.org/abs/2311.09206)) [high] | Nov 2023, NAACL 2024 | Llama-2-7B tuned on TableInstruct | Generalist table model, small context |
| Chain-of-Table ([arXiv 2401.04398](https://arxiv.org/abs/2401.04398)) | Jan 9, 2024, ICLR 2024 | The LLM plans atomic table operations; each step produces a new table state; SOTA on WikiTQ, FeTaQA, TabFact | A chain of intermediate *tables*, close to crivo's chain of verified cells; small tables only |
| TableRAG ([arXiv 2410.04739](https://arxiv.org/abs/2410.04739)) | Oct 7, 2024, NeurIPS 2024 | Query expansion plus schema retrieval plus cell retrieval, so a million-token table is never serialised; new million-token benchmarks built from Arcade and BIRD | Supports "profile plus targeted probes" (see 1.4) |
| Table-R1 ([arXiv 2505.23621](https://arxiv.org/abs/2505.23621)) | May 2025, EMNLP 2025 | Distillation plus RL with verifiable rewards on tables; a 7B model matches GPT-4.1 and DeepSeek-R1 | The field moved to RL on table tasks; little to borrow |
| TableZoomer ([arXiv 2509.01312](https://arxiv.org/abs/2509.01312)) | Sep 1, 2025 | Replaces the "fully verbalized table" with a structured schema, a query-aware sub-table schema, and Program-of-Thought code in a ReAct loop; +19.34% on DataBench with Qwen3-8B | The closest published twin of crivo's analyst loop |
| TableGPT-R1 ([arXiv 2512.20312](https://arxiv.org/abs/2512.20312)) | Dec 23, 2025 | Qwen3-8B tuned with RL; writes Python and reacts to code-interpreter feedback; Apache-2.0 weights; weighted toward Chinese | A possible local model for the kernel loop; would need a bench run |
| ASTRA ([ACL 2026](https://preview.aclanthology.org/ingest-acl/2026.acl-long.1090/), arXiv 2604.08999) [med] | 2026 | A semantic tree over the table plus symbolic code execution "for verification" | Serialisation is still called a bottleneck in 2026 |
| Survey: "Table QA in the era of LLMs" ([arXiv 2510.09671](https://arxiv.org/abs/2510.09671); [ACL 2026 long 557](https://aclanthology.org/2026.acl-long.557/)) | Oct 2025, revised to Apr 2026; ACL 2026 | 277 papers; organises the RL-era methods | The reference to cite in crivo's docs |

**Bottom line [synthesis].** Serialisation methods (Binder, DATER, Chain-of-Table) won on
small Wikipedia tables. For tables that don't fit in context, the field now uses schema
plus retrieval plus executed code. crivo's design (a profile of about 6,000 characters,
pandas cells, executed asserts) matches where the research went. It is not an outlier.

### 1.2 Large tables, multiple tables and joins

- **Multi-table benchmarks.** MMQA ([ICLR 2025](https://iclr.cc/virtual/2025/poster/30290))
  asks multi-hop questions over tables linked by primary and foreign keys.
  TQA-Bench ([arXiv 2411.19504](https://arxiv.org/abs/2411.19504), Nov 2024) scales
  multi-table context from 8K to 64K tokens and adds symbolic extensions; its repo is
  **GPL-3.0**, so don't vendor it. MultiTabQA ([arXiv 2305.12820](https://arxiv.org/abs/2305.12820), ACL 2023) [high].
- **Join depth.** A 2026 paper with a Join-Hop Depth benchmark reports accuracy falling
  below 40% at four foreign-key hops
  ([SurgeLLM 2026](https://aclanthology.org/2026.surgellm-1.17/)) [med, snippet].
- **Fan-out and double counting.** Snowflake documents fan traps, chasm traps and
  join-path hallucinations, and says Cortex Analyst *rejects* queries it judges likely to
  double count
  ([Snowflake engineering blog](https://www.snowflake.com/en/engineering-blog/snowflake-cortex-analyst-introducting-joins-complex-schemas)) [med, vendor].
  Research on in-context-learning text-to-SQL errors finds LLMs often join on unrelated
  columns ([arXiv 2501.09310](https://arxiv.org/abs/2501.09310), Jan 2025) [med, snippet].
  The earlier sweep found `sqlsure` (Apache-2.0), which checks declared grain, join
  cardinality and measure additivity.
- **Schema linking is optional with strong models.** Distyl's "The Death of Schema
  Linking?" ([arXiv 2408.07702](https://arxiv.org/abs/2408.07702), NeurIPS 2024 workshop)
  gives the model the whole schema whenever it fits, reaching 71.83% execution accuracy
  on BIRD. Linking can drop a column the query needs. For crivo: when the profile is over
  budget, truncating columns ("… N columns omitted") is a schema-linking failure that
  nobody sees.
- **The leaderboards themselves are unreliable.** "Pervasive Annotation Errors Break
  Text-to-SQL Benchmarks and Leaderboards"
  ([arXiv 2601.08778](https://arxiv.org/abs/2601.08778); [PVLDB 19](https://www.vldb.org/pvldb/vol19/p931-jin.pdf);
  [CIDR 2026](https://vldb.org/cidrdb/papers/2026/p5-jin.pdf)) finds annotation errors in
  52.8% of BIRD Mini-Dev and 62.8-66.1% of Spider 2.0-Snow. Corrections moved agents up
  to 9 places, and rank correlation fell from 0.85 to 0.32. Spider 2.0
  ([arXiv 2411.07763](https://arxiv.org/abs/2411.07763), ICLR 2025) [high] remains the
  enterprise reference; its repo (`xlang-ai/Spider2`, MIT, 884 stars) was last pushed
  2026-08-12.

**For crivo:** multi-file questions (crivo already has `reconcile` and `drivers`) need a
key-and-cardinality block in the profile when more than one frame is loaded. The research
says join errors are silent and get worse with every hop.

### 1.3 How models read tables: formats and structure

- **Formats vary by task, and there is no universal winner.**
  - Sui et al., "Table Meets LLM" ([arXiv 2305.13062](https://arxiv.org/abs/2305.13062),
    WSDM 2024) [high]: HTML > XML > JSON > Markdown on structural tasks. They also found
    that *self-augmented prompting*, where the model first states the table's critical
    values and ranges, helps.
  - Singha et al. ([arXiv 2310.10358](https://arxiv.org/abs/2310.10358), Oct 2023) [high]
    measured how noise and format change structure understanding.
  - Improving Agents ([blog, Sep 30, 2025](https://www.improvingagents.com/blog/best-input-data-format-for-llms))
    tested one model (GPT-4.1-nano) on 1,000 flat records with single-field lookups:
    Markdown-KV 60.7%, JSON 52.3%, Markdown table 51.9%, CSV 44.3%; CSV was the cheapest
    in tokens [med, single model].
  - crivo's profile is a Markdown table with one row per column. Column-per-row is
    already close to a key-value layout, and nothing in this evidence argues for changing
    the container. What goes in it matters more (1.4).
- **TOON** (`toon-format/toon`, MIT, 25.5k stars since Oct 2025). The maintainers report
  76.4% against JSON's 75.0% with about 40% fewer tokens [med, maintainer's own numbers].
  An independent study ([arXiv 2603.03306](https://arxiv.org/abs/2603.03306), early 2026)
  finds plain JSON generation more accurate, and TOON's advantage shrinks once you pay for
  its instructions [med]. Don't adopt it for the profile without a bench run.
- **Structure sensitivity.** Liu et al. ([arXiv 2312.16702](https://arxiv.org/abs/2312.16702),
  Dec 27, 2023): the same content in a different structure lowers accuracy, especially on
  symbolic (code) reasoning. Mixing textual and symbolic reasoning paths with
  self-consistency reached 73.6% on WikiTQ. For crivo: normalise structure (header
  repair, unpivot detection) *before* the model writes code. That is what crivo's library
  half does.
- **Spreadsheets.** SpreadsheetLLM ([arXiv 2407.09025](https://arxiv.org/abs/2407.09025),
  Jul 2024, revised Apr 2025) compresses sheets about 25x with its SheetCompressor:
  structural anchors, an inverse index, and *data-format-aware aggregation*, which groups
  cells by number format instead of listing values. Table detection improved 25.6% over
  plain serialisation with GPT-4. For crivo's `excel_structure.py`, format-aware
  aggregation is a profile idea for xlsx: "C2:C900 = currency, 3 cells = text".

### 1.4 What profile and sample design helps a model write correct pandas without all rows

This is the most actionable section for crivo.

| Evidence | Finding | Source |
|---|---|---|
| DataFrame QA (Ye, Du, Wang) | Column names only, no values: GPT-4 pass@1 is 86% on WikiSQL and 97% on UCI-DataFrameQA; under 250 tokens a task | [arXiv 2401.15463](https://arxiv.org/abs/2401.15463) (Jan 2024; ACML 2024, [PMLR 260](https://proceedings.mlr.press/v260/ye25a.html)) |
| DataGovBench ablation (Table 4) | First 10 rows: 0.310. Plus schema stats: 0.308. Plus up to 200 rows: 0.275. Plus type-specific serialisation: **0.360**. Plus reflection: 0.379. Plus self-correction: 0.393 (Gemini 2.5 Flash; GPT-4o follows the same pattern, 0.242 to 0.270) | [arXiv 2607.06482](https://arxiv.org/html/2607.06482v1) (Jul 7, 2026) |
| DataGovBench's serialisation rules | Each column gets its inferred feature type, dtype and missing %. Categorical: every category if 20 or fewer, else 20 random distinct ones. Numeric: min and max. Datetime: earliest and latest. URL: no samples. Everything else (embedded numbers, numbers with units, lists, ranges, IDs): 10 random *distinct* values | same |
| Cluster-then-select (Barke et al., Microsoft) | Accuracy depends on how many rows go in the prompt, which ones, and where. Picking representative rows from clusters of similar *formatting* beats random rows when the input varies a lot | [arXiv 2402.11734](https://arxiv.org/abs/2402.11734) (Feb 2024; NAACL 2024 Findings) |
| LIDA summariser | Rule-based atomic types, min/max/unique counts and *random* non-null samples, then optional LLM-added descriptions and semantic types | [arXiv 2303.02927](https://arxiv.org/abs/2303.02927) (Mar 2023) |
| MRT (SemEval-2025 Task 8) | Per-column type, unique count, missingness, min/max/mean and top values, turned into an LLM-written column description that is cached per table | [arXiv 2505.22264](https://arxiv.org/abs/2505.22264) [med, snippet] |
| SemEval-2025 Task 8 (DataBench) | LLM approaches dominated, and larger models clearly beat smaller ones. A Python code-generation system reached 70.49%. Column selection before prompting placed 7th on the Lite track | [overview](https://aclanthology.org/2025.semeval-1.324/) (Jul 2025); [IUST_Champs](https://preview.aclanthology.org/setup/2025.semeval-1.260) [med]; [TabaQA](https://airi.net/articles/tabaqa-at-semeval-2025-task-8-column-augmented-generation-for-question-answering-over-tabular-data) [med] |
| TableRAG | Retrieve the schema and the *cells* relevant to the question rather than reading rows | [arXiv 2410.04739](https://arxiv.org/abs/2410.04739) |
| pandas-ai v2 privacy mode | Sent a randomised, shuffled head; `enforce_privacy=True` sent column names only | [PyPI 2.0.36 README](https://pypi.org/project/pandasai/2.0.36) [med] |
| Anthropic, code execution with MCP | "Intermediate results stay in the execution environment by default"; tokenise PII before the model sees it; 150,000 to 2,000 tokens (98.7%) | [anthropic.com](https://www.anthropic.com/research/code-execution-with-mcp) (Nov 4, 2025) |

**What this means for crivo's profile** (`src/crivo/profile.py`, read 2026-10-23):

- **Samples come from the head.** `_row` shows `nonnull.iloc[:_SAMPLES]`, the first 3
  non-null values in file order. On messy exports the head is often the cleanest part:
  the preamble has been skipped and the defects sit further down. The evidence favours
  *distinct* values chosen at random or by format cluster (Barke; DataGovBench).
- **Categories are cut to 3.** Top-3 values are shown for every text column. A
  20-or-fewer category list (DataGovBench) would show the "mobile" vs "mobile_app" split
  that Hex's DataBench uses as a trap.
- **Shape is missing for object columns.** A column of numbers stored as text, with
  units, sentinels or two date formats, shows only 3 samples and the top 3. A
  "format-signature" summary would fill the gap, for example `9999-99-99 ×812 · 99/99/9999 ×40 · 'N/A' ×7`.
  This is DataGovBench's "Numbers with Unit / Embedded Number" typing plus SpreadsheetLLM's
  format aggregation. `semantic_types.py` already exists and could supply the type.
- **Over-budget truncation drops columns silently from the model's point of view.** When
  the budget is hit, the profile drops the trailing columns (`… N columns omitted`). The
  schema-linking literature says dropping columns is the riskier failure. A cheaper
  fallback: keep every column's name and dtype, and drop the samples first.
- **No relationship block.** Nothing says "candidate key: `order_id` (unique, 0 nulls)"
  or "`customer_id` repeats ×4.2 on average". DataBench-style traps (several IDs per
  customer) and join fan-out start there.
- **Gap between the rule and the kernel (checked in code, not run).** The profile masks
  PII, but cell observations are only clipped. `kernel/bootstrap.py` sets
  `display.max_rows=30`, `prompts.py` tells the model to use `.head()` and
  `.value_counts()`, and `SECURITY.md` lists "cell output … clipped today" as a path from
  data to the model. A masked peek helper (suggestion 2) would bring the observations
  under the same rule as the profile.

### 1.5 Data-agent benchmarks that test reading tables (verification evals are another agent's topic)

- **DataGovBench.** Government open data: about 210K rows on average, up to 11.9M rows ×
  213 columns; 36% of datasets have several tables; 57% need a data dictionary. The best
  whole-question QA score is 0.393; Claude Sonnet 4.6 scores 0.534 on individual
  sub-questions ([arXiv 2607.06482](https://arxiv.org/abs/2607.06482)). The repo
  (`SoHasegawa/datagovbench`) has **no licence**, so it can't be vendored.
- **AgenticDataBench** ([arXiv 2607.01647](https://arxiv.org/abs/2607.01647), Jul 2, 2026):
  344 tasks in 15 domains. Data analysis is the biggest failure category ("validation,
  summarization, and statistical calculation"). In Healthcare, ARFF and other mixed
  formats drive self-repair failures [med, snippet].
- **SpreadsheetBench 2** ([arXiv 2606.29955](https://arxiv.org/abs/2606.29955), NeurIPS 2026):
  321 tasks averaging 11.8 sheets each; the best model scores 34.89%, debugging 12%. The
  bottlenecks are "insufficient spreadsheet inspection" and picking the wrong target cell
  [med, snippet].
- **Hex DataBench** ([hex.tech, Aug 13, 2026](https://hex.tech/blog/databench-agentic-analytics-benchmark/)):
  100 tasks in a deliberately messy warehouse. Examples: five plausible revenue columns,
  "mobile" vs "mobile_app" never backfilled, every customer with 2 to 4 IDs, stale
  tables, drifting timestamps. "Mistakes are silent." Averages: Q&A 75%, open-ended 66%,
  traps 54%. Fable 5 scores 85; Opus 5 regresses at xhigh and max effort. The tasks are
  private.
- **DiscRun-Bench** ([UNLV, ICMLA 2026 PDF](https://arifuzzaman.faculty.unlv.edu/paper/icmla26-llm.pdf)) [med]:
  on messy data prep, a "hazard-asking" plan step raised Claude Haiku 4.5's rate of
  surfacing caveats from 0.74 to 0.90. The authors conclude that silent failure is
  "substantially an elicitation problem".
- **DeepAnalyze** ([arXiv 2510.16872](https://arxiv.org/abs/2510.16872), Oct 2025): an
  open 8B agentic data-science model (MIT, 4.7k stars). The authors report it beats
  workflow agents built on proprietary models on DataSciBench [med, the summaries
  disagree].

---

## 2. Tabular foundation models, and what they could do inside crivo

### 2.1 The models

| Model | Date | Code licence | Weights licence | CPU and deps | Tasks | Fit for crivo |
|---|---|---|---|---|---|---|
| **TabPFN-2** ([Nature, Jan 2025](https://www.nature.com/articles/s41586-024-08328-6)) [high] | Jan 2025 | Apache-2.0 | "Prior Labs License" = Apache-2.0 **plus an attribution requirement** ([README](https://cdn.jsdelivr.net/gh/PriorLabs/TabPFN@main/README.md)) | `tabpfn` 9.2.0 (Oct 12, 2026) needs `torch>=2.5`, `huggingface-hub`, `pydantic` and more. CPU allows 1,000 samples on older models | classification, regression; outliers and impute via extensions | The only TabPFN weights commercially usable for free; old; attribution clause |
| **TabPFN-2.5 / 2.6 / 3 / 3.5** ([3.5 report, arXiv 2609.17895](https://arxiv.org/abs/2609.17895)) | 3.5 weights dated 2026-09-09 | Apache-2.0 | **Non-commercial.** The model, its derivatives *and its outputs* may not be used commercially or in production. Gated: browser login, or `TABPFN_TOKEN`, to download ([gating docs](https://docs.priorlabs.ai/how-to-access-gated-models.md)) | CPU: up to 5,000 samples for 3 and 3.5. GPU path: up to 1M rows × 20K features | same plus "Thinking" (enterprise only) | **Incompatible with crivo's defaults.** Outputs inherit the restriction, and the gating breaks "keyless" |
| **tabpfn-extensions** (Apache-2.0, 338 stars; 0.6.3 on Sep 21, 2026) | 2026 | Apache-2.0 | uses TabPFN weights (above) | as TabPFN | `TabPFNUnsupervisedModel.outliers()` (low joint likelihood = anomaly), `.impute()`, synthetic data ([API ref](https://priorlabs.ai/reference/tabpfn_extensions/unsupervised/unsupervised)) [med] | The right *shape* of API for a crivo detector; the weights licence decides |
| **TabICLv2** ([arXiv 2602.11139](https://arxiv.org/abs/2602.11139); [PMLR 306](https://proceedings.mlr.press/v306/qu26a.html)) | Feb 2026, ICML 2026 | BSD-3 (`tabicl` 2.2.0, Sep 2, 2026) | BSD-3 on HF (`jingang/TabICL`, 2026-02-12) | Falls back to CPU automatically, with CPU and disk offload; torch required; pretrained on 300 to 48K rows and 2 to 100 columns ([README](https://cdn.jsdelivr.net/gh/soda-inria/tabicl@main/README.md)) | classification, regression, forecasting; beats RealTabPFN-2.5 on TabArena and TALENT without tuning | **Best permissive candidate.** No login; weights from HF |
| **NVIDIA Kumo Tabular** ([model card](https://build.nvidia.com/nvidia/kumo-tabular/modelcard); HF `nvidia/Kumo-Tabular`) | HF 2026-09-01, release on the card 09/23, press Sep 29, 2026 | Apache-2.0 (`NVIDIA/structured-data-models`, 394 stars, `torch>=2.7`) | **OpenMDW-1.1**, commercial use allowed, no limits on outputs [med via [beri.net](https://www.beri.net/article/nvidia-kumo-tabular-open-tabular-foundation-model-tabarena-commercial-license-vs-tabpfn-3-5)] | 28M to 215M params; pretrained up to 60K rows and 100 columns; numeric and categorical only. Community **ONNX** ports exist (`onnx-community/kumo-tabular-small-*`), and onnxruntime is a 21-24 MB wheel against torch's 127-555 MB | classification, regression | Permissive; ONNX could avoid torch. The TabArena PR was "still open" as of late Sep [med]. The ONNX ports are third-party, licence "other" |
| **Mitra** (Amazon, in AutoGluon) | Jun 2025 (HF `autogluon/mitra-classifier`) | Apache-2.0 | Apache-2.0 ([AutoGluon tutorial](https://auto.gluon.ai/1.5/tutorials/tabular/tabular-foundational-models.html)) | torch; inside AutoGluon, a heavy dependency | classification, regression | Permissive; AutoGluon is too heavy for crivo |
| **TabDPT** ([arXiv 2410.18164](https://arxiv.org/abs/2410.18164)) | Oct 2024; `tabdpt` 1.3.1 Sep 21, 2026 | Apache-2.0 | Apache-2.0 (HF `Layer6/TabDPT`) | `torch>=2.6`, `faiss-cpu` | classification, regression (retrieval ICL) | Permissive; faiss adds weight |
| **LimiX** (`limix-ldm-ai/LimiX`, 4.4k stars) | 2025-2026; licence v1.0 Sep 2026 | "Stable AI Technology License", Apache-derived **with mandatory attribution and naming rules** ("Built with StableAI LimiX") | same (HF "other") | torch | classification, regression, imputation [med] | Usable, but the attribution and naming rules are clumsy for an MIT library |
| **sap-rpt-1-oss** (ConTextTab) | 2025; repo last pushed Jun 2026 | Apache-2.0 | [med] | torch | semantics-aware ICL (uses column names and text) | Watch; SAP now owns Prior Labs too |
| **CARTE** ([arXiv 2402.16785](https://arxiv.org/abs/2402.16785)) [high] | Feb 2024, ICML 2024 | BSD-3; last push 2025-08-11 | - | `carte-ai` pulls in torch-geometric, fasttext, **tabpfn**, xgboost, catboost | graph-based, string-aware | Dormant and very heavy; skip |
| **XTab** ([arXiv 2305.06090](https://arxiv.org/abs/2305.06090)) [high] | May 2023, ICML 2023 | **no licence** (`BingzhaoZhu/XTab`, 42 stars, last push Jan 2023) | - | - | cross-table pretraining | Unusable (no licence) and dormant |
| **OUTFORMER** ([arXiv 2602.03018](https://arxiv.org/abs/2602.03018); [PMLR 306](https://proceedings.mlr.press/v306/ding26s.html)) | Feb 2026, ICML 2026 | no official repo found | - | - | **zero-shot outlier detection**; SOTA on ADBench and 1,500+ datasets | The right task; code and licence unclear |
| **FoMo-0D** ([arXiv 2409.05672](https://arxiv.org/abs/2409.05672)) | Sep 2024; TMLR Sep 2025 | MIT (`A-Chicharito-S/FoMo-0D`, 3 stars) | - | torch | zero-shot outlier detection | Research code, tiny repo |
| **TabImpute** ([arXiv 2510.02625](https://arxiv.org/abs/2510.02625)) | Oct 2025, v4 Feb 17, 2026 | repo `jacobf18/TabImpute`, no licence file found | builds on TabPFN, so it inherits that question | - | zero-shot imputation; MissBench; 100x faster than TabPFN imputation | Licence unclear |

**Standings.** TabArena ([arXiv 2506.16791](https://arxiv.org/abs/2506.16791), NeurIPS 2025
D&B) is the living benchmark. Foundation models lead on small and medium data, and
gradient-boosted trees stay strong on practical data. One aggregator reports the current
top four single models as TabPFN-3, TabPFN-2.6, RealTabPFN-2.5 and TabICLv2
([codesota](https://www.codesota.com/tasks/tabular-ml)) [low].

**Column type annotation** (for `semantic_types.py`). Two 2026 papers: frozen-LLM column
embeddings with light classifiers beat the strongest prior baseline by 3.7 points
([ICML 2026](https://icml.cc/virtual/2026/71546)) [med], and StraTyper discovers types per
collection to cut the cost of LLM calls ([emergentmind 2602.04004](https://www.emergentmind.com/papers/2602.04004))
[med]. ArcheType ([VLDB 2024](https://mail.vldb.org/pvldb/volumes/17/paper/ArcheType%3A%20A%20Novel%20Framework%20for%20Open-Source%20Column%20Type%20Annotation%20using%20Large%20Language%20Models))
[med] is the zero-shot baseline. All of these need a model (an LLM or embeddings), so
they don't fit the keyless library half.

### 2.2 What a tabular FM could do inside crivo, and what it must never do

- **A row-likelihood outlier signal (a detector input).** Fit in context on the frame and
  flag rows with a low joint likelihood (tabpfn-extensions' approach) or a high zero-shot
  outlier score (OUTFORMER, FoMo-0D). Fits a crivo finding: counts plus up to 3 masked
  samples.
- **Cross-column predictability.** Predict each column from the others and flag cells
  whose observed value is improbable. This overlaps the data-cleaning research, which
  another agent covers.
- **Imputation *suggestions* only.** A model-imputed value can't be re-checked
  deterministically: no assertion can prove a filled cell is the true value. Under
  crivo's rule (a fix is kept only if a re-check passes), FM imputation can at most be a
  HUMAN-gated suggestion labelled "model estimate", never an AUTO fix.
- **Rules it must not break.**
  - `import crivo` stays import-light: torch is 127 MB on macOS and 555 MB on Linux, and
    the weights are network downloads. Ship it only as an extra (`crivo[tabfm]`), import
    it lazily inside the detector, and never fetch weights at import. The download is an
    explicit command that records the weight file's hash in lineage.
  - Keyless: TabPFN 2.5 and later need an account token, which rules them out.
  - "Nothing verified because a model said so": an FM score can *raise* a finding but
    can't *clear* one or verify a fix.
- **Licence ranking for an MIT tool.**
  1. TabICLv2 (BSD-3 code and weights).
  2. Mitra and TabDPT (Apache-2.0).
  3. Kumo Tabular (OpenMDW-1.1; check the full text before shipping).
  4. LimiX (attribution and naming rules).
  5. TabPFN-2 (attribution).
  6. **Never** TabPFN 2.5 and later: non-commercial, outputs included.

---

## 3. Text-to-pandas, text-to-SQL and dataframe agents (open source)

### 3.1 Dataframe and SQL agents

| Repo | Licence | Stars | Last push | Latest release | Maintained? | Notes |
|---|---|---|---|---|---|---|
| [sinaptik-ai/pandas-ai](https://github.com/sinaptik-ai/pandas-ai) | MIT, except `pandasai/ee/` (separate licence) | 23,900 | 2025-10-28 | 3.0.0 (2025-10-07) | **Dormant.** Pins `pandas<3`, `numpy<2`, `scipy==1.10.1`, `duckdb<2` | v3 adds an experimental semantic layer; v2 sent a randomised head |
| [microsoft/lida](https://github.com/microsoft/lida) | MIT | 3,287 | 2024-08-08 | - | **Dormant** | The summariser design (1.4) is the lasting idea |
| [microsoft/data-formulator](https://github.com/microsoft/data-formulator) | MIT | 17,590 | 2026-10-23 | 0.8b1 (2026-08-15); 0.7.0 (2026-05-28) | **Active** | DuckDB as its compute engine; Python for messier transforms [med]; the agent architecture was rewritten between 0.5 and 0.7 [med] |
| [vanna-ai/vanna](https://github.com/vanna-ai/vanna) | MIT | 23,814 | 2026-02-02 | - | **Archived on GitHub** (no notice in the README) | Vanna 2.0 had added user-aware permissions and row-level security |
| [eosphoros-ai/DB-GPT](https://github.com/eosphoros-ai/DB-GPT) | MIT | 20,185 | 2026-10-23 | v0.8.2 (2026-08-26) | **Active** | A full platform; framework-heavy |
| [Canner/WrenAI](https://github.com/Canner/WrenAI) | **Apache-2.0 for core, sdk and skills since 2026-05-04** (was AGPL-3.0); docs CC-BY-4.0; future AGPL modules reserved | 17,958 | 2026-10-23 | - | **Active** | Semantic-layer-first text-to-SQL. Watch for AGPL modules |
| [OtterMind/Chat2DB](https://github.com/OtterMind/Chat2DB) | **Modified Apache-2.0 ("LicenseRef-Chat2DB") from 5.3.0** | 28,331 | 2026-10-20 | - | Active | Not OSI-clean; avoid |
| [ruc-datalab/DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze) | MIT | 4,746 | 2026-10-13 | - | Active | Open 8B data-science agent model |
| [tablegpt/tablegpt-agent](https://github.com/tablegpt/tablegpt-agent) | Apache-2.0 | 635 | 2026-10-06 | v0.2.27 (2025-03-05) | Low activity | TableGPT2 / R1 agent |
| [microsoft/TaskWeaver](https://github.com/microsoft/TaskWeaver) | MIT | 6,160 | 2026-03-23 | - | **Archived** | Was a code-first stateful agent |
| [openinterpreter/openinterpreter](https://github.com/openinterpreter/openinterpreter) | Apache-2.0 (today's repo; the older project was AGPL) [med] | 68,653 | 2026-10-11 | - | Active | A general agent, not table-specific |
| [briefercloud/briefer](https://github.com/briefercloud/briefer) | **AGPL-3.0** | 4,327 | 2025-08-07 | - | Dormant | Flag: AGPL |
| [xlang-ai/Spider2](https://github.com/xlang-ai/Spider2) | MIT | 884 | 2026-08-12 | - | Active | Benchmark plus baseline agents |

**Execution engines.**

| Engine | Licence | Stars | Release | Relevance |
|---|---|---|---|---|
| [duckdb/duckdb](https://github.com/duckdb/duckdb) | MIT | 42,472 | **2.0.0 LTS, Oct 21, 2026** ([announcement](https://duckdb.org/2026/10/21/announcing-duckdb-200)); LTS to Oct 2027 | **Agent mode** (CLI): compact Markdown, truncation flags, JSON errors, runaway-query stop, a cost estimate, 59% less output on TPC-H. Plus VARIANT, async CSV and Parquet I/O, the Quack client-server protocol. Breaking: files written by 2.0 can't be read by older versions, the Python package drops 3.10, macOS x86_64 is being phased out |
| DuckDB faulty-CSV handling ([docs 2.0](https://duckdb.org/docs/2.0/data/csv/reading_faulty_csv_files)) | MIT | - | - | `store_rejects=true` writes `reject_errors` with `error_type` (CAST, MISSING COLUMNS, TOO MANY COLUMNS, UNQUOTED VALUE, LINE SIZE OVER MAXIMUM, INVALID ENCODING) **and the raw `csv_line`**. Use the counts and types; never put `csv_line` in a prompt |
| [pola-rs/polars](https://github.com/pola-rs/polars) | MIT | 40,173 | **2.0.0 on PyPI 2026-10-06** | Streaming is now the default for `collect`. Row order is *not guaranteed* for joins, group-bys and unpivot unless you ask for it; coercion is stricter [med, [New Stack](https://thenewstack.io/polars-streaming-row-order/)]. LLMs still mix the pandas and Polars APIs; the Polars team's own test had 31 of 33 translations correct ([pola.rs](https://pola.rs/posts/llm-polars-patterns)) [med, vendor] |
| [ibis-project/ibis](https://github.com/ibis-project/ibis) | Apache-2.0 | 6,679 | active | One dataframe API over DuckDB, Polars and warehouses; Boring Semantic Layer builds on it |
| [duckdb/ducklake](https://github.com/duckdb/ducklake) | MIT | 3,332 | active | A lakehouse format whose catalog lives in SQL |

**What this says about crivo's engine [synthesis].** Keep pandas as the model's language:
it has the most training data, and crivo's row-alignment checks rely on a stable order.
Add DuckDB *beside* it in the kernel for files too big for memory, for reading CSVs with
reject tables, and for profiling statistics over a scan. Don't hand the model Polars
frames: streaming's unordered default breaks positional row diffs, and the API confusion
is documented. One caution: DuckDB 2.0 is two days old. Pin `duckdb>=1.5,<3`, test both,
and don't write `.duckdb` files that users' older DuckDB installs must read.

### 3.2 Semantic layers and governed metrics

| Project | Licence | Stars, activity | What it is | Relevance to crivo |
|---|---|---|---|---|
| [dbt-labs/metricflow](https://github.com/dbt-labs/metricflow) | Apache-2.0 (open-sourced [Oct 14, 2025](https://www.getdbt.com/blog/open-source-metricflow-governed-metrics)) | 1,844; v0.213.0 (2026-09-10) | Compiles YAML semantic models and metrics to SQL | Serving to BI and agents needs a paid dbt plan [low, [Querio](https://querio.ai/articles/dbt-semantic-layer)] |
| [dbt-labs/dbt-mcp](https://github.com/dbt-labs/dbt-mcp) | Apache-2.0 | 612; pushed 2026-10-23 | MCP access to the dbt Semantic Layer | A pattern to copy, not a dependency |
| [apache/ossie](https://github.com/apache/ossie) (formerly Open Semantic Interchange, OSI) | Apache-2.0 | 2,535; created 2025-11-18 | A vendor-neutral YAML/JSON spec for datasets, fields, relationships, metrics and an AI-context section; v0.1 Jan 2026 ([Snowflake](https://www.snowflake.com/en/blog/open-semantic-interchanges-specs-finalized/), [dbt](https://www.getdbt.com/blog/the-osi-spec-updates)); entered the Apache Incubator (Jul 10 per [OWOX](https://www.owox.com/blog/articles/apache-ossie.md)) [med]; 0.2.0 still a draft | The one *interchange format* for metrics. crivo could **emit** a draft Ossie model from a cleaned file plus its glossary. Wait for 0.2 |
| [cube-js/cube](https://github.com/cube-js/cube) | Apache-2.0, some MIT | 21,067; active | A semantic layer exposed over MCP, SQL, REST and GraphQL; admins "certify agent reports" ([cube.dev](https://cube.dev/product/cube)) [med, vendor] | Warehouse-side; not crivo's market |
| [boringdata/boring-semantic-layer](https://github.com/boringdata/boring-semantic-layer) | MIT | 486; pushed 2026-08-24 | Ibis-based, in-process, an optional MCP extra | The lightest example; shows a semantic layer can be a library |
| Snowflake semantic views + VQR ([docs](https://docs.snowflake.com/LIMITEDACCESS/snowflake-cortex/cortex-analyst-vqr)) | proprietary | - | Verified question-and-SQL pairs; [evaluations](https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-analyst-evaluations) use them as ground truth and track regressions | A "verified queries" model for crivo's saved answers |
| Databricks Genie trusted assets ([docs](https://docs.databricks.com/gcp/genie)) | proprietary | - | A result is "Trusted" only when built from parameterized example SQL or SQL functions; benchmarks compare results against reference SQL | Same idea |

**Takeaway [synthesis].** In 2026 "governed metrics" means a human wrote the definition,
or the SQL, ahead of time, and the agent reuses it. Messy one-off exports have no such
artefact. crivo's skills, plus a glossary of saved, verified answers (SECURITY.md already
lists "contracts, the glossary and saved answers" as future referee-trusted inputs), are
the messy-file equivalent. Ossie is the format to export them to once it stabilises.

### 3.3 MCP data servers

| Server | Licence | Stars, activity | Notes |
|---|---|---|---|
| [motherduckdb/mcp-server-motherduck](https://github.com/motherduckdb/mcp-server-motherduck) | MIT | 534; v1.1.0 (2026-10-07) | Local DuckDB works without an account. Read-only by default, but the README says read-only "is not sufficient" for third parties. Results capped at **1024 rows / 50,000 characters** (`--max-rows`, `--max-chars`). Tools: `execute_query`, `list_databases`, `list_tables`, `list_columns` |
| [teaguesterling/duckdb_mcp](https://github.com/teaguesterling/duckdb_mcp) | Apache-2.0 | 66; active | A DuckDB extension that is both an MCP client and server |
| [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp) (Postgres MCP Pro) | MIT | 3,423; last release v0.3.0 (2025-05-16), push 2026-08 | Index tuning and health checks plus SQL |
| Reference Postgres MCP server ([servers-archived](https://github.com/modelcontextprotocol/servers-archived)) | MIT | archived 2025-05 | Retired |
| Reference filesystem server ([modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)) | moving from MIT to Apache-2.0; docs CC-BY-4.0 | 91,527 | The generic file-access baseline |
| [googleapis/mcp-toolbox](https://github.com/googleapis/mcp-toolbox) (formerly genai-toolbox) | Apache-2.0 | 16,715; active | Prebuilt tools for Postgres, BigQuery, AlloyDB, Spanner, MySQL, Snowflake and others; no DuckDB or SQLite found [med] |
| [Snowflake-Labs/mcp](https://github.com/Snowflake-Labs/mcp) | Apache-2.0 | 301; push 2026-05 | Cortex Analyst, Search, SQL |
| [datalayer/jupyter-mcp-server](https://github.com/datalayer/jupyter-mcp-server) | BSD-3 | 1,311; v2.2.4 (2026-10-11) | Notebook, cell and execution tools against a Jupyter Server; sandbox backends (Colab, Modal, E2B…); `ALLOW_IMG_OUTPUT`; no documented truncation |

**What every one of these returns: raw rows, capped.** None returns a checked answer, a
receipt or lineage, and none masks PII. crivo's MCP surface (`open_data` returns a masked
profile; `ask` returns an `AnswerCard`) is a different kind of tool. Pitch it as "the MCP
server that returns verified answers, not rows". From DuckDB's agent mode and MotherDuck,
copy explicit truncation flags, JSON errors and stated caps.

### 3.4 Notebook agents

| Product | Licence | Status | How the agent drives the notebook |
|---|---|---|---|
| [Jupyter AI](https://github.com/jupyterlab/jupyter-ai) | BSD-3 | v3.2.0 (2026-09-03); 4,424 stars | v3 brings external agents in (Claude, Codex, Gemini, Goose…) over the **Agent Client Protocol**, plus a built-in Jupyter MCP server; a permission prompt gates writes and commands ([PyPI](https://pypi.org/project/jupyter_ai/)) [med] |
| [marimo](https://github.com/marimo-team/marimo) | Apache-2.0 | 0.25.2 (2026-10-19); 23,309 stars | `marimo edit nb.py --mcp` exposes *read-only* lower-level tools ([docs](https://docs.marimo.io/guides/editor_features/mcp.md)); Claude Code over ACP ([docs](https://docs.marimo.io/guides/editor_features/agents/)) [med] |
| [marimo-pair](https://github.com/marimo-team/marimo-pair) | Apache-2.0 | 429 stars; created 2026-02-24 | An **Agent Skill** plus a Claude Code plugin; bash scripts (`execute-code.sh`) drive a live notebook with curl and jq. The same "skill, not framework" shape crivo uses |
| [Deepnote (open source)](https://github.com/deepnote/deepnote) | Apache-2.0 | 3,026 stars; open-sourced Nov 4, 2025 ([New Stack](https://thenewstack.io/deepnote-a-successor-to-jupyter-notebook-goes-open-source/)) [med] | A YAML notebook format; the agent is mostly in the cloud tier |
| [Positron](https://github.com/posit-dev/positron) (Posit) | Posit's own licence agreement (not OSI) | 4,313 stars | An IDE with an assistant; licence flag |
| Hex agent (formerly Notebook Agent / Magic) | proprietary | Evals CLI ([Aug 4, 2026 changelog](https://learn.hex.tech/changelog/2026-08-04)); Context Studio (Jan 2026); resource-usage display (Jul 30, 2026) | Semantic models plus guides; LLM-judge evals in YAML suites |
| Julius | proprietary | - | Chat over uploaded files and databases; see section 4 |

---

## 4. The product and competitor landscape for AI data analysts (2025-2026)

### 4.1 Product by product

| Product | Surface and data | What it verifies, if anything | Messy files vs warehouses | Public pricing | Documented failures |
|---|---|---|---|---|---|
| **ChatGPT data analysis** ([help](https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt)) [med, 403 on fetch] | Python sandbox over uploads | Shows code; the help text tells users to "review the generated code, outputs, and assumptions before relying on the result" [med] | Uploaded files; limits "vary by upload type, model, plan" [med] | ChatGPT plans | Parsing errors (encoding, delimiters, ragged rows) can show up as "silent truncation" [low, [DataStudios](https://www.datastudios.org/post/can-chatgpt-analyze-csv-files-data-parsing-calculations-and-error-handling)] |
| **OpenAI Data agent** (ChatGPT Work and Codex; [Sep 10, 2026](https://openai.com/index/put-data-to-work/)) [med, 403] | Snowflake, BigQuery, Databricks, Redshift, ClickHouse, MongoDB, Datadog, Drive, SharePoint; builds dashboards; pushes to Tableau, Power BI, ThoughtSpot [med] | Uses semantic-layer definitions (dbt, Genie Ontology, Snowflake Horizon); respects permissions; users "refine, validate" through follow-up questions ([help 20001518](https://help.openai.com/en/articles/20001518-using-the-data-plugin-in-chatgpt-work-and-codex)) [med] | Warehouse-first; Drive and SharePoint files too | Work plans | No accuracy numbers published [med] |
| **Claude**: analysis tool → code execution; Claude for Excel; **Claude Dashboards** | Analysis tool (JS, [Oct 24, 2024](https://claude.com/resources/articles/analysis-tool)), replaced by code execution on Nov 5, 2025. Excel/Word/PowerPoint add-ins GA May 7, 2026 [med, [pillitteri.it](https://pasqualepillitteri.it/en/news/2143/claude-microsoft-365-outlook-beta)]. Dashboards beta Oct 8, 2026 over Redshift, BigQuery, ClickHouse, Databricks, Snowflake, Salesforce [med, [New Stack](https://thenewstack.io/claude-dashboards-data-motion/)] | Dashboards: every chart shows its SQL and refresh time; queries run on the *viewer's own* credentials [med] | Dashboards are warehouse-first; files go through code execution | Paid plans; admins enable Dashboards | None found for Dashboards or Excel |
| **Julius AI** | Chat over files and databases; notebooks | Shows code [low] | Files first; DB connectors on Pro | Free 15 messages/month; Plus ~$35, Pro ~$45/month; credit tiers also reported ([coefficient](https://coefficient.io/julius-ai-pricing), [usagepricing](https://usagepricing.com/blueprint/julius-ai)) [low, sources conflict] | None found that is systematic |
| **Hex** | Notebooks plus agent, threads, apps | Semantic models, Context Studio, **evals CLI** (an LLM judge reads the thread and the resources used), resource-usage display ([evals docs](https://learn.hex.tech/docs/agent-management/evals)) | Warehouse-first | Community $0, Professional $36, Team $75 per editor/month; agent credits 30-40 per seat ([frontdeskreview](https://frontdeskreview.com/software/ai-data-analytics/hex/), [Hex credits](https://hex.tech/blog/credits-and-usage-visibility-for-hex-agents/)) [med] | Its own DataBench: traps 54% on average ([Aug 13, 2026](https://hex.tech/blog/databench-agentic-analytics-benchmark/)) |
| **Databricks Genie / Genie One** | Unity Catalog spaces; Genie One launched Jun 16, 2026 [med] | **Trusted assets** (parameterized example SQL and functions) plus **benchmarks** against reference SQL ([docs](https://docs.databricks.com/gcp/genie)) | Governed warehouse only | Databricks consumption | The docs call Genie nondeterministic. A Databricks guide's baseline got **zero** answers right because of poor table names and metadata ([blog](https://www.databricks.com/blog/how-build-production-ready-genie-spaces-and-build-trust-along-way)) [med]. 84.5% on 28 internal questions, vendor-claimed [med, [Pebblous](https://blog.pebblous.ai/blog/databricks-genie-one-governed-data/en/)] |
| **Snowflake Cortex Analyst** | Semantic model YAML or semantic views | **VQR**; evaluations with verified queries as ground truth, including regressions; rejects likely double-count queries ([VQR](https://docs.snowflake.com/LIMITEDACCESS/snowflake-cortex/cortex-analyst-vqr), [evals](https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-analyst-evaluations)) | Warehouse only; semantic file ≤1 MB and about 32K tokens | Snowflake credits | Claims 90%+ and "nearly 2x" single-prompt GPT-4o, on internal data ([engineering blog](https://snowflake.com/en/engineering-blog/cortex-analyst-text-to-sql-accuracy-bi)) [med, vendor] |
| **Google Colab Data Science Agent** | Notebook generated from a prompt over an uploaded CSV, JSON or txt (under 1 GB at launch); BigQuery version | Plan → "Accept & run"; no verification step ([BigQuery docs](https://docs.cloud.google.com/bigquery/docs/colab-data-science-agent)) | Files plus BigQuery | Free in Colab | None found; default model Gemini 3.0 Flash |
| **Microsoft**: Excel Agent Mode, Copilot, Fabric data agents | Agent Mode (announced Sep 29, 2025); Fabric data agents over lakehouses and semantic models | Agent Mode reportedly "evaluates the results and corrects them" [med, [The Decoder](https://the-decoder.com/microsoft-adds-autonomous-ai-agents-to-copilot-for-office-apps/)]; Fabric **evaluation SDK**: you supply expected answers and an LLM critic judges ([Learn](https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent)) | Both | M365 Copilot; Fabric F2+ capacity | Agent Mode: **57.2% on SpreadsheetBench vs 71.3% for humans** [med, [Engadget](https://engadget.com/ai/microsoft-is-trying-to-make-vibe-working-a-thing-163334367.html)]. `COPILOT()` launched with a warning against numerical and regulatory use; ICAEW found wrong projections; later retired [med, [ICAEW](https://www.icaew.com/technical/technology/excel-community/excel-community-articles/2025/introducing-excels-new-copilot-function), [Redmond](https://redmondmag.com/blogs/generationai/2026/08/microsoft-pulls-excel-copilot.aspx)] |
| **Fabi.ai** | SQL, Python and AI "Smartbooks"; dbt semantics | Generated SQL can be viewed and edited [low] | Both | From $39/user/month ([Capterra](https://www.capterra.com/p/10023722/Fabi-ai/)) [low] | None found |
| **Powerdrill Bloom** | Excel, CSV, TSV, PDF, DB; generates slides | - | Files first | Pro ~$19.90, Plus ~$39.90, Premium ~$199/month, credits ([usagepricing](https://usagepricing.com/blueprint/powerdrill)) [low] | None found |
| **Rows** | AI spreadsheet | - | - | - | **Acquired by Superhuman (Feb 2026, [Rows blog](https://rows.com/blog/post/rows-is-joining-superhuman)); standalone product wound down May 31, 2026** [med] |
| **Akkio** | Pivoted to media agencies | - | - | Contact sales [low, [checkthat](https://checkthat.ai/brands/akkio/pricing)] | - |
| **Formula Bot** | Formulas plus a data analyzer | - | Files | Free tier with 5 MB uploads; paid tiers conflict ($9-$29+) [low, [frontdeskreview](https://frontdeskreview.com/software/ai-data-analytics/formula-bot/)] | - |
| **Open-source contenders** | Data Formulator, DB-GPT, WrenAI, DeepAnalyze; pandas-ai dormant, Vanna archived | None ships executed per-answer verification | Mostly SQL or warehouse | free | - |

### 4.2 Where crivo's verify-first, messy-file, MCP-native position is open, and where it is crowded

**Crowded:**
- **Natural language to SQL over governed warehouses.** OpenAI Data agent, Claude
  Dashboards, Genie, Cortex Analyst, Fabric, Hex, WrenAI, DB-GPT. The labs and the
  warehouse vendors own this, and their trust story is "curated definitions plus
  reference SQL plus show the query". crivo shouldn't compete here.
- **Consumer "chat with your CSV".** ChatGPT, Claude, Julius, Powerdrill, Formula Bot,
  Colab. Cheap or free, with no verification beyond "here's the code". Rows exiting shows
  the margins are thin.

**Open:**
1. **Messy one-off files with no semantic layer.** Every vendor verification mechanism
   above (trusted assets, VQR, evaluation SDKs, Hex evals) needs ground truth someone
   curated: reference SQL, expected answers, a semantic model. A messy export has none.
   crivo's checks (executed asserts, an intent check, receipts such as `reconcile`'s
   independent recount, re-checked fixes) produce their evidence *per answer, with
   nothing curated in advance*. Nobody else in this survey does that.
2. **A verifier other agents can call.** Every MCP data server found returns capped raw
   rows. None returns a checked answer with lineage and masked evidence. Since Claude
   Code, Cursor and Jupyter AI all drive notebooks and MCP now (ACP, jupyter-mcp-server,
   marimo-pair), "the agent's data tool that refuses to return an unchecked number" is an
   open slot.
3. **Data-file linting in CI.** `datacontract-cli` (MIT, 1,099 stars, v1.2.7 Oct 16,
   2026) and Frictionless validate against a declared schema. Neither diagnoses an
   undeclared messy file or proves a repair. crivo's GitHub Action sits beside them, and
   could *read* their contract formats (section 5).

**Risks to the positioning:**
- The labs now use trust words: OpenAI "validate", Genie "Trusted", Claude "shows the
  query". crivo's copy must say what it *executes*. Its claim should be about receipts,
  not adjectives.
- Hex's DataBench shows the best models reaching 85-88% on *messy warehouses* with
  context tooling. crivo's edge has to show up on messy *files*, measured on its own
  bench. Publish a trap set shaped like DataBench, aimed at exports (bench work; another
  agent covers eval methodology).

---

## 5. Agent-friendly data formats and interfaces

| Format or standard | Status (date, licence) | What crivo could use it for | Verdict |
|---|---|---|---|
| **Apache Arrow** ([apache/arrow](https://github.com/apache/arrow), Apache-2.0, 17,215 stars) | Active. The PyCapsule interface (`__arrow_c_stream__`) is still marked "experimental" ([docs](https://arrow.apache.org/docs/format/CDataInterface/PyCapsuleInterface.html)) | Zero-copy handoff between pandas, Polars and DuckDB inside the kernel; crivo already depends on `pyarrow>=25.0.1` | Keep using; accept any `__arrow_c_stream__` object in `cv.read`/`diagnose` as a cheap way to take Polars and DuckDB input |
| **Parquet** | Stable; VARIANT shredding read and write in DuckDB 2.0 | The default *cleaned output* (already in `write`); types survive, unlike CSV | Make it the recommended output for `clean` and keep CSV for humans |
| **DuckDB file** | The 2.0 storage format can't be read by older versions | Not an interchange format | Avoid as an output |
| **Frictionless Data Package v2 / Table Schema v2** ([datapackage.org](https://datapackage.org/), released Jun 26, 2024; spec Unlicense; [frictionless-py](https://github.com/frictionlessdata/frictionless-py) MIT, v5.21.0 Oct 15, 2026) | v2 adds `categories` / `categoriesOrdered`, field-level and labelled `missingValues`, a `list` type, `uniqueKeys`, `fieldsMatch`, `$schema` versioning, Table Dialect (CSV, JSON, Excel) ([changelog](https://datapackage.org/overview/changelog/)) | A `datapackage.json` **sidecar** for every cleaned file: inferred types, categories, the missing-value tokens crivo found (sentinels), the primary-key candidate, the dialect it detected. Write the JSON directly, with no runtime dependency (frictionless-py pulls in petl, jinja2, marko, pydantic and more); validate with frictionless only in tests | **Adopt** (S). The natural "schema of what crivo learned" |
| **ODCS v3.x, Open Data Contract Standard** ([bitol-io](https://github.com/bitol-io/open-data-contract-standard), Apache-2.0, 1,188 stars) | v3.1.0 (Dec 8, 2025): `relationships` (foreign keys), quality metrics `rowCount`, `nullValues`, `invalidValues`, `duplicateValues`, `missingValues`. **v3.2.0 (Sep 8, 2026): an "AI context" section ("guidance for agents on data use, verification, and prohibited actions")**, synonyms, measures and dimensions ([releases](https://github.com/bitol-io/open-data-contract-standard/releases)) | **Project config / contract input** for the GitHub Action and `diagnose`: map ODCS quality metrics to crivo detectors and run them as gates. `datacontract-cli` (MIT) reads ODCS | **Adopt the read side** (M). Flag: the ODCS 3.2 "AI context" text is model-readable data from a third party, so it is an injection surface (SECURITY.md); show it to the model as data, never as instructions |
| **CSVW** (W3C Recommendation, 2015) | WG and CG closed ([W3C](https://www.w3.org/groups/wg/csv/activity/)); `w3c/csvw` repo archived 2026 (GitHub API) | - | **Skip** |
| **Croissant 1.1** ([mlcommons/croissant](https://github.com/mlcommons/croissant), Apache-2.0; v1.1.0 Apr 16, 2026; v1.1.1 Oct 5, 2026) | Adds W3C PROV-O provenance down to field level (`prov:wasDerivedFrom`, `prov:wasGeneratedBy`) and ODRL usage rights [med, [ODI](https://theodi.org/news-and-events/blog/croissant-11/)]; NeurIPS 2026 requires the RAI metadata in Croissant ([NeurIPS blog](https://blog.neurips.cc/2026/05/04/responsible-ai-metadata-requirements-for-the-evaluations-and-datasets-track-neurips-2026/)) | Shape crivo's lineage export with **PROV-O terms** (entity = file or variable, activity = fix or cell, agent = crivo or model), so Croissant and PROV tools can read it | **Adopt the vocabulary** (S); a full Croissant export is optional |
| **OpenLineage** ([OpenLineage/OpenLineage](https://github.com/OpenLineage/OpenLineage), Apache-2.0, 2,721 stars; 1.54.0 Oct 13, 2026) | The pipeline lineage event standard (Marquez, Airflow, dbt) | Optional: emit a `RunEvent` per `clean` run so enterprise lineage tools see crivo's output | Later (M); only if users ask |
| **MCP structured output** ([2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)) | `outputSchema` / `structuredContent` (since 2025-06-18) now take any JSON Schema 2020-12 and any JSON value; protocol is stateless; `resultType` required; cross-call state through explicit server-minted handles; deterministic `tools/list` order for prompt caching | Give `ask`, `diagnose` and `clean_file` an `outputSchema`, so calling agents parse the AnswerCard and findings without scraping text; resource links to artifacts; crivo's `session_id` is already a server-minted handle | **Adopt** (S-M); coordinate with the planned port to the newer spec (earlier sweep, item 6) |
| **Apache Ossie** (metrics) | 0.1.1; 0.2.0 draft | Export verified metrics and glossary (section 3.2) | **Watch** |

---

## What crivo should do (ranked)

Each item names the crivo piece, the source, effort (S/M/L), licence compatibility with
crivo's MIT licence, the risk, and any rule it touches. Items 1, 2 and 6 change what the
model sees, so under AGENTS.md they are **`behaviour`** work: they need a pre-registered
eval, and until that tooling exists their effect is unmeasured.

1. **Profile v2: per-type serialisation plus format-diverse samples.** *Piece:* the profile
   design (`profile.py`, `semantic_types.py`).
   - *Change:*
     - Text columns with 20 or fewer distinct values: list them all, with counts.
     - Other text columns: up to about 10 *distinct* values chosen to cover different
       format signatures (digits → `9`, letters → `a`; one value per signature cluster),
       instead of the first 3.
     - Object columns: add a "shape" line with the signature counts and how many values
       fail to parse as numbers or dates.
     - Numeric and datetime columns: keep min and max.
     - URL columns: no samples.
     - Every column: carry the semantic type as a feature type.
     - Over budget: drop samples before dropping columns.
   - *Sources:* DataGovBench Table 4 and its serialisation rules (arXiv 2607.06482); Barke
     et al. cluster-then-select (arXiv 2402.11734); SpreadsheetLLM's format-aware
     aggregation; "Death of Schema Linking" (don't drop columns).
   - *Effort:* S to build, M to measure. *Licence:* n/a (ideas only).
   - *Risk:* a longer profile hurts small models. The 6,000-character budget needs a
     re-tune. Category lists widen the PII surface.
   - *Rules:* all values stay masked through `pii` and truncated. Showing distinct values
     is still "truncated samples", not rows. Measure on the bench before calling it
     better.
2. **A masked `peek` helper in the kernel instead of `.head()`.** *Piece:* the analyst
   engine (`kernel/bootstrap.py`, `prompts.py`).
   - *Change:* a bootstrap function that returns, for chosen columns or a filter, typed
     distinct values, counts and PII-masked examples. Point the prompt to it rather than
     `.head()`.
   - *Sources:* TableRAG's cell retrieval; TableZoomer's sub-table schema; Anthropic's
     code execution with MCP (filter in code, return little); DuckDB agent mode (compact
     output, flagged truncation).
   - *Effort:* S. *Licence:* n/a.
   - *Risk:* the model may still print rows. The "no raw rows" claim then depends on
     masking the observation path too: today's output is clipped but not masked
     (SECURITY.md). Masking observations is a core change (`loop.py`), so Aarmen decides.
   - *Rules:* this narrows a current gap between the rule and practice. It must not be
     sold as closing it until a test proves it.
3. **Position against "trusted queries" with receipts, and prove it on messy files.**
   *Piece:* positioning (README, PRD) plus the bench.
   - *Change:* say plainly that warehouse tools verify against curated reference SQL
     (Genie trusted assets, Cortex VQR, Fabric and Hex evals), while crivo verifies each
     answer on files with no curation. Back it with a public trap suite on messy exports,
     shaped like DataBench (split columns, stale flags, several IDs, mixed formats), and
     report both crivo and a bare model.
   - *Sources:* Hex DataBench; Databricks and Snowflake docs; the Excel Agent Mode and
     SpreadsheetBench 2 numbers.
   - *Effort:* M. *Licence:* n/a.
   - *Risk:* claiming before measuring. AGENTS.md already forbids that; the risk is copy
     drifting ahead of the bench.
4. **Cleaned outputs: Parquet plus a `datapackage.json` sidecar, and lineage in PROV-O
   terms.** *Piece:* output format (`write`, the clean report, `provenance.py`).
   - *Change:* write Table Schema v2 JSON (types, `categories`, `missingValues` = the
     sentinels crivo found, `primaryKey` candidate, dialect) next to every cleaned file.
     Export the provenance DAG with PROV-O names, which Croissant 1.1 reads.
   - *Sources:* datapackage.org v2; Croissant 1.1 and the ODI post.
   - *Effort:* S-M. *Licence:* the specs are Unlicense and Apache-2.0. Write the JSON by
     hand, with no runtime dependency; frictionless-py (MIT) only in tests.
   - *Risk:* schema drift between crivo's types and Table Schema's types; keep a mapping
     table in the contract.
   - *Rules:* the sidecar holds schema and stats, no rows. Categories from PII-flagged
     columns must be omitted or masked.
5. **Read ODCS v3.1+ or Table Schema as the project contract for `diagnose` and the
   Action.** *Piece:* project config plus the GitHub Action.
   - *Change:* `crivo diagnose FILE --contract contract.yaml` maps ODCS quality metrics
     (`nullValues`, `duplicateValues`, `invalidValues`, `rowCount`) and `relationships`
     to crivo's detectors and gates.
   - *Sources:* ODCS v3.1.0 and v3.2.0 release notes; datacontract-cli.
   - *Effort:* M. *Licence:* Apache-2.0 spec. Don't import datacontract-cli; parse the
     YAML with crivo's existing dependencies.
   - *Risk:* scope creep into a general data-contract engine; keep to the metrics crivo
     already detects. ODCS 3.2's "AI context" is third-party text, so treat it as data
     (an injection surface).
6. **DuckDB as an optional second engine inside the kernel, for big files.** *Piece:* the
   analyst engine and readers.
   - *Change:* in the kernel only, read CSVs too large for memory through DuckDB
     (`store_rejects`, then pass *counts by `error_type`*, never `csv_line`). Compute the
     profile statistics with a DuckDB scan. Keep pandas as the model's API. Accept any
     `__arrow_c_stream__` object as input.
   - *Sources:* DuckDB 2.0 announcement and faulty-CSV docs; Data Formulator's use of
     DuckDB.
   - *Effort:* M. *Licence:* MIT.
   - *Risk:* DuckDB 2.0 is two days old, with breaking changes (no Python 3.10, new
     storage format, PEG parser), so pin a range and test both 1.5 and 2.0. Two engines
     mean two sets of type semantics.
   - *Rules:* the kernel-side import keeps `import crivo` light; `reject_errors.csv_line`
     is raw data.
7. **MCP: return typed results and copy DuckDB agent mode's habits.** *Piece:* the MCP
   surface (`mcp_server.py`).
   - *Change:* add an `outputSchema` and `structuredContent` for `ask` / AnswerCard,
     `diagnose` and `clean_file`; explicit `truncated` flags with stated caps; JSON error
     objects; resource links to the card, lineage and report files; a deterministic tool
     order.
   - *Sources:* MCP 2026-07-28 changelog; DuckDB 2.0 agent mode; the MotherDuck MCP caps.
   - *Effort:* S-M. *Licence:* n/a.
   - *Risk:* clients that ignore structured content still need text. Send both.
8. **Tabular FM as an opt-in outlier signal, licence first.** *Piece:* detectors (a new
   optional extra; `detect.py` is core, so Aarmen decides).
   - *Change:* `crivo[tabfm]` with TabICLv2 (BSD-3), or Kumo Tabular through ONNX once
     its ONNX licence is confirmed. It emits a "row improbable under the model" finding
     with counts and masked samples.
   - *Sources:* TabICLv2; Kumo Tabular; tabpfn-extensions' `outliers()` design;
     OUTFORMER and FoMo-0D.
   - *Effort:* L. *Licence:* fine for TabICLv2, Mitra and TabDPT; check OpenMDW-1.1; **no
     TabPFN 2.5 and later** (non-commercial including outputs, plus login gating). LimiX
     carries attribution and naming rules.
   - *Risk:* torch weight (127-555 MB), slow on CPU (TabPFN limits CPU to 5,000 samples),
     and the score can't be verified. It needs bench corpus cases first ("the instrument
     comes before the capability").
   - *Rules:* never in `import crivo`, no download at import, never a basis for AUTO
     fixes. An FM can't verify anything.
9. **A multi-frame key and cardinality block in the profile.** *Piece:* the profile
   design.
   - *Change:* when two or more frames are loaded, add candidate keys (unique, no nulls),
     the average multiplicity of shared key columns, and the overlap between frames'
     key sets.
   - *Sources:* MMQA, TQA-Bench, the Join-Hop Depth paper, Snowflake's fan-trap post, and
     Hex DataBench's multi-ID traps.
   - *Effort:* S-M. *Licence:* n/a.
   - *Risk:* the cost of computing it on big frames (sample it, or use DuckDB); more
     profile characters.
10. **Later: export verified metrics and the glossary as Apache Ossie YAML.** *Piece:* a
    new surface.
    - *Sources:* Apache Ossie; dbt MetricFlow.
    - *Effort:* M. *Licence:* Apache-2.0.
    - *Risk:* the spec is still 0.x (0.2.0 is a draft). Wait for 0.2 before building.

**Don't do:**
- Build natural language to SQL over warehouses (crowded, and labs own it).
- Adopt CSVW (dead).
- Depend on pandas-ai, LIDA or Vanna (dormant or archived; pandas-ai pins `pandas<3` and
  `numpy<2`).
- Vendor TQA-Bench (GPL-3.0), Briefer (AGPL-3.0), Chat2DB (modified Apache) or
  DataGovBench (no licence).
- Put TOON in the profile without a bench result.
- Make Polars the model's dataframe: unordered streaming breaks row diffs, and the model
  mixes up the APIs.
- Use agent frameworks: DB-GPT and WrenAI's LangChain SDK are framework-shaped, so take
  the ideas, not the code.

### Checks against crivo's rules

- **No raw rows in prompts.**
  - Items 1, 2 and 9 change what the model sees. All values stay masked through `pii`
    and capped.
  - DuckDB's `reject_errors.csv_line` and any FM "most anomalous rows" output are raw
    rows. Counts and masked samples only.
  - Separately, cell observations today are clipped but not PII-masked. That is
    acknowledged in SECURITY.md, and is a decision for Aarmen (core: `loop.py`).
- **Nothing verified because a model said so.** FM scores, LLM column-type labels,
  vendors' "trusted" labels and LLM-judge evals (Hex, Fabric) can raise findings or inform
  a human. They never pass a check.
- **No agent frameworks.** Nothing above requires one. Take patterns from WrenAI, DB-GPT
  and Data Formulator, not their code.
- **`import crivo` stays keyless and import-light.**
  - Table Schema, PROV and ODCS are hand-written JSON and YAML with no new runtime
    dependency.
  - DuckDB and any FM load only inside the kernel or an extra.
  - TabPFN 2.5 and later fail this rule twice over (gated download, non-commercial
    outputs).

---

## Sources (by section; date of the item, then the link)

**Research**
- Binder, Oct 2022: https://arxiv.org/abs/2210.02875 [high, not re-fetched]
- DATER, Jan 2023: https://arxiv.org/abs/2301.13808 [high, not re-fetched]
- StructGPT, May 2023: https://arxiv.org/abs/2305.09645 [high, not re-fetched]
- TableGPT, Jul 2023: https://arxiv.org/abs/2307.08674 [high]
- TableGPT2, Nov 2024: https://arxiv.org/abs/2411.02059
- TableLlama, Nov 2023: https://arxiv.org/abs/2311.09206 [high]
- Chain-of-Table, Jan 9, 2024: https://arxiv.org/abs/2401.04398
- Rethinking Tabular Data Understanding, Dec 27, 2023: https://arxiv.org/abs/2312.16702
- Table Meets LLM, May 2023: https://arxiv.org/abs/2305.13062 [high]
- Singha et al., Oct 2023: https://arxiv.org/abs/2310.10358 [high]
- SpreadsheetLLM, Jul 12, 2024: https://arxiv.org/abs/2407.09025
- TableRAG, Oct 7, 2024: https://arxiv.org/abs/2410.04739
- DataFrame QA, Jan 2024: https://arxiv.org/abs/2401.15463
- Barke et al. (cluster-then-select), Feb 18, 2024: https://arxiv.org/abs/2402.11734
- LIDA, Mar 2023: https://arxiv.org/abs/2303.02927
- Table-R1, May 2025: https://arxiv.org/abs/2505.23621
- TableZoomer, Sep 1, 2025: https://arxiv.org/abs/2509.01312
- TableGPT-R1, Dec 23, 2025: https://arxiv.org/abs/2512.20312
- Table QA survey (ACL 2026): https://aclanthology.org/2026.acl-long.557/
- ASTRA (ACL 2026): https://preview.aclanthology.org/ingest-acl/2026.acl-long.1090/
- DataGovBench, Jul 7, 2026: https://arxiv.org/html/2607.06482v1
- AgenticDataBench, Jul 2, 2026: https://arxiv.org/abs/2607.01647
- SpreadsheetBench 2, Jun 2026: https://arxiv.org/abs/2606.29955
- SemEval-2025 Task 8 overview, Jul 2025: https://aclanthology.org/2025.semeval-1.324/
- MRT at SemEval-2025: https://arxiv.org/abs/2505.22264
- MMQA (ICLR 2025): https://iclr.cc/virtual/2025/poster/30290
- TQA-Bench, Nov 2024: https://arxiv.org/abs/2411.19504
- MultiTabQA, May 2023: https://arxiv.org/abs/2305.12820 [high]
- Spider 2.0, Nov 2024: https://arxiv.org/abs/2411.07763 [high]
- Death of Schema Linking, Aug 2024: https://arxiv.org/abs/2408.07702
- Pervasive annotation errors, 2026: https://arxiv.org/abs/2601.08778
- ICL text-to-SQL errors, Jan 2025: https://arxiv.org/abs/2501.09310
- Join-hop depth (SurgeLLM 2026): https://aclanthology.org/2026.surgellm-1.17/
- DiscRun-Bench (ICMLA 2026 PDF): https://arifuzzaman.faculty.unlv.edu/paper/icmla26-llm.pdf
- DeepAnalyze, Oct 19, 2025: https://arxiv.org/abs/2510.16872
- Improving Agents formats, Sep 30, 2025: https://www.improvingagents.com/blog/best-input-data-format-for-llms
- TOON vs JSON, 2026: https://arxiv.org/abs/2603.03306
- Anthropic, Code execution with MCP, Nov 4, 2025: https://www.anthropic.com/research/code-execution-with-mcp

**Tabular foundation models**
- TabPFN README (fetched 2026-10-23): https://cdn.jsdelivr.net/gh/PriorLabs/TabPFN@main/README.md
- TabPFN-3.5 report: https://arxiv.org/abs/2609.17895
- Prior Labs gated models: https://docs.priorlabs.ai/how-to-access-gated-models.md
- tabpfn-extensions unsupervised: https://priorlabs.ai/reference/tabpfn_extensions/unsupervised/unsupervised
- TabICLv2, Feb 2026: https://arxiv.org/abs/2602.11139 ; https://proceedings.mlr.press/v306/qu26a.html ; README: https://cdn.jsdelivr.net/gh/soda-inria/tabicl@main/README.md
- Kumo Tabular model card: https://build.nvidia.com/nvidia/kumo-tabular/modelcard ; licence comparison: https://www.beri.net/article/nvidia-kumo-tabular-open-tabular-foundation-model-tabarena-commercial-license-vs-tabpfn-3-5
- Mitra in AutoGluon: https://auto.gluon.ai/1.5/tutorials/tabular/tabular-foundational-models.html
- TabDPT: https://arxiv.org/abs/2410.18164
- OUTFORMER, ICML 2026: https://arxiv.org/abs/2602.03018
- FoMo-0D: https://arxiv.org/abs/2409.05672
- TabImpute: https://arxiv.org/abs/2510.02625
- TabArena: https://arxiv.org/abs/2506.16791
- Column type annotation, ICML 2026: https://icml.cc/virtual/2026/71546

**Repos, engines and standards**
- DuckDB 2.0, Oct 21, 2026: https://duckdb.org/2026/10/21/announcing-duckdb-200
- DuckDB faulty CSV: https://duckdb.org/docs/2.0/data/csv/reading_faulty_csv_files
- Polars row order: https://thenewstack.io/polars-streaming-row-order/ ; LLM patterns: https://pola.rs/posts/llm-polars-patterns
- MetricFlow open source, Oct 14, 2025: https://www.getdbt.com/blog/open-source-metricflow-governed-metrics
- OSI / Ossie: https://www.snowflake.com/en/blog/open-semantic-interchanges-specs-finalized/ ; https://ossie.apache.org/
- Cube: https://cube.dev/product/cube
- MotherDuck MCP: https://github.com/motherduckdb/mcp-server-motherduck
- jupyter-mcp-server: https://github.com/datalayer/jupyter-mcp-server
- Jupyter AI: https://pypi.org/project/jupyter_ai/
- marimo MCP: https://docs.marimo.io/guides/editor_features/mcp.md
- marimo-pair: https://github.com/marimo-team/marimo-pair
- Deepnote open source, Nov 4, 2025: https://thenewstack.io/deepnote-a-successor-to-jupyter-notebook-goes-open-source/
- MCP 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Data Package v2: https://datapackage.org/ ; changelog: https://datapackage.org/overview/changelog/
- ODCS releases: https://github.com/bitol-io/open-data-contract-standard/releases
- Croissant 1.1: https://theodi.org/news-and-events/blog/croissant-11/
- CSVW WG activity: https://www.w3.org/groups/wg/csv/activity/
- Arrow PyCapsule: https://arrow.apache.org/docs/format/CDataInterface/PyCapsuleInterface.html

**Products**
- Hex DataBench, Aug 13, 2026: https://hex.tech/blog/databench-agentic-analytics-benchmark/ ; Hex evals: https://learn.hex.tech/docs/agent-management/evals
- Databricks Genie: https://docs.databricks.com/gcp/genie ; https://www.databricks.com/blog/how-build-production-ready-genie-spaces-and-build-trust-along-way
- Snowflake VQR: https://docs.snowflake.com/LIMITEDACCESS/snowflake-cortex/cortex-analyst-vqr ; evaluations: https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-analyst-evaluations ; accuracy: https://snowflake.com/en/engineering-blog/cortex-analyst-text-to-sql-accuracy-bi ; joins: https://www.snowflake.com/en/engineering-blog/snowflake-cortex-analyst-introducting-joins-complex-schemas
- Fabric evaluation SDK: https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent
- Colab DS agent (BigQuery): https://docs.cloud.google.com/bigquery/docs/colab-data-science-agent
- Claude analysis tool: https://claude.com/resources/articles/analysis-tool
- Claude Dashboards, Oct 8, 2026: https://thenewstack.io/claude-dashboards-data-motion/ [med]
- OpenAI Data agent, Sep 10, 2026: https://openai.com/index/put-data-to-work/ ; https://help.openai.com/en/articles/20001518-using-the-data-plugin-in-chatgpt-work-and-codex [med, 403]
- ChatGPT data analysis help: https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt [med, 403]
- Excel Agent Mode: https://engadget.com/ai/microsoft-is-trying-to-make-vibe-working-a-thing-163334367.html [med]
- Excel COPILOT(): https://www.icaew.com/technical/technology/excel-community/excel-community-articles/2025/introducing-excels-new-copilot-function ; https://redmondmag.com/blogs/generationai/2026/08/microsoft-pulls-excel-copilot.aspx [med]
- Rows joins Superhuman: https://rows.com/blog/post/rows-is-joining-superhuman
- Julius pricing: https://coefficient.io/julius-ai-pricing [low]
- Powerdrill pricing: https://usagepricing.com/blueprint/powerdrill [low]
- Fabi.ai: https://www.capterra.com/p/10023722/Fabi-ai/ [low]
- Formula Bot: https://frontdeskreview.com/software/ai-data-analytics/formula-bot/ [low]
- Akkio: https://checkthat.ai/brands/akkio/pricing [low]

**Repo and package facts** (GitHub REST API and PyPI JSON, 2026-10-23): licences, stars,
`pushed_at`, `archived`, releases and `requires_dist` for every repo and package named in
sections 2 and 3. Wheel sizes: torch 2.14.1 (127 MB macOS arm64, 555 MB Linux x86_64) and
onnxruntime 1.31.0 (21-24 MB).
