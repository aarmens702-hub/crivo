# Data cleaning, error detection and repair: research and open-source code crivo can use

Research date: 2026-10-23. Scope: 2019 to 2026 papers, benchmarks and Python libraries for detecting and repairing errors in tables, read against what crivo is (about 25 graded disease detectors, deterministic fixers kept only when a referee re-check passes, a model-driven analyst, and a bench that plants corruptions and also scores the Raha pairs).

## How to read this

- Every claim carries a date and a link. Primary sources are papers (arXiv, PVLDB, ACM, ACL Anthology), official repos, PyPI metadata and official docs.
- A claim that comes from a secondary source (news, an aggregator, a third-party summary) or from my own inference carries **[high]**, **[med]** or **[low]** confidence.
- **Repo numbers** (stars, licence, date of the last commit on the default branch) come from the GitHub API, read on 2026-10-23. **Release dates and dependencies** come from the PyPI JSON API, read the same day.
- **"Measured"** means I ran the code myself on 2026-10-23: macOS 15 (Darwin 24.5), Python 3.12, a scratch virtualenv, pandas 3.1.0. I re-checked the pandas date result on crivo's own pandas 3.0.5. Import times are warm `python -X importtime` totals, so treat them as orders of magnitude.
- **Licence shorthand:** "no licence" means the repo has no LICENSE file. Under default copyright that is all rights reserved, so crivo can learn the idea but must not copy the code.
- I didn't read `src/crivo/detect.py` or `src/crivo/autoclean.py`. Disease ids are from `docs/ARCHITECTURE.md` and the scorer is from `bench/score.py`.

---

## 1. Error detection and repair research, 2019 to 2026

### 1.1 The Raha/Baran line and its successors

- **Raha** (configuration-free error detection) and **Baran** (error correction) are the baselines everyone still compares against.
  - Raha: SIGMOD 2019, which won the SIGMOD reproducibility award ([BIFOLD news](https://www.bifold.berlin/news-events/news/view/news-detail/researchers-in-prof-abedjans-group-win-simgod-reproducibility-award)). Baran: PVLDB 13(12), 2020 ([VLDB page](https://mail.vldb.org/pvldb/volumes/13/paper/Baran%3A%20Effective%20Error%20Correction%20via%20a%20Unified%20Context%20Representation%20and%20Transfer%20Learning)).
  - The repo [BigDaMa/raha](https://github.com/BigDaMa/raha) is Apache-2.0, has 73 stars, and was last committed on 2025-06-05. PyPI `raha` 1.26 dates from 2023-06-29.
  - The repo ships seven datasets: beers, flights, hospital, movies_1, rayyan, tax, toy. crivo uses four of them.
- **No direct "Raha 2" exists.** Abedjan's group has moved to benchmarks; see "Clean Me If You Can" in §2. That paper's repo sits under the TU Berlin `D2IP-TUB` organisation, so the group is probably now at TU Berlin **[med]**.
- **Label budget changes the ranking completely.**
  - ZeroED gave Raha only 2 labelled tuples per dataset. Raha's detection F1 then falls to 0.125 on hospital, 0.591 on flights, 0.685 on beers and 0.422 on rayyan ([ZeroED Table III, arXiv 2504.05345, Apr 2025](https://arxiv.org/html/2504.05345v1)).
  - Raha's own papers use about 20 labelled tuples, a figure confirmed only in a machine-written summary ([rmarcus.info](https://rmarcus.info/dbscholar/papers/h5c1d12c23739cbe3)) **[med]**.
  - **Lesson for crivo:** any comparison against published Raha or Baran numbers must state the label budget.

### 1.2 HoloClean and its descendants

- **HoloClean** (probabilistic repair with denial constraints) appeared at PVLDB 2017 ([paper](https://cs.uwaterloo.ca/~ilyas/papers/RekatsinasHoloClean.pdf)).
  - The repo [HoloClean/holoclean](https://github.com/HoloClean/holoclean) is Apache-2.0 with 543 stars. Its last commit was 2019-04-27, so it is unmaintained.
- **HoloDetect** (few-shot error detection with data augmentation): SIGMOD 2019 ([arXiv 1904.02285](https://arxiv.org/pdf/1904.02285)). It reports about 0.94 precision and 0.93 recall on average.
- **Bayesian successors:**
  - **PClean** (domain-specific probabilistic programs, Julia): [arXiv 2007.11838, Jul 2020](https://arxiv.org/pdf/2007.11838). The repo [probcomp/PClean](https://github.com/probcomp/PClean) is Apache-2.0, last committed 2025-09-25.
  - **BClean** (automatically built Bayesian network): [arXiv 2311.06517, Nov 2023](https://arxiv.org/pdf/2311.06517). Its venue is likely ICDE 2024 **[med]**. Repo [yyssl88/BClean](https://github.com/yyssl88/BClean) has no licence.
- **Horizon** (linear-time functional-dependency repair that keeps the most frequent patterns): PVLDB 14(11), 2021 ([VLDB page](https://www.vldb.org/pvldb/volumes/14/paper/Horizon%3A%20Scalable%20Dependency-driven%20Data%20Cleaning)).
  - It is deterministic and pattern-frequency based, the closest classic method to a verifiable fix for d12 field-contradictions.
- **The key evaluation paper is "Automatic Data Repair: Are We Ready to Deploy?"** (Ni, Miao et al., PVLDB 17(10), 2024, [arXiv 2310.00711](https://arxiv.org/html/2310.00711v2); code [WelkinNi/Automatic-Data-Repair](https://github.com/WelkinNi/Automatic-Data-Repair), no licence). It ran 12 repair algorithms on hospital, flights, beers, rayyan and tax.
  - **Most algorithms make the data worse.** Most have a *negative* Error Drop Rate (EDR): they turn more correct cells wrong than wrong cells right.
  - **The metric:** EDR = (#wrong→right − #right→wrong) / #initially wrong.
  - **Precision and F1 mislead.** The paper gives an example with precision 0.8 and recall 1.0 in which the number of errors *doubles*.
  - **What works where:** Baran is best on syntactic errors, MLNClean on semantic errors, Horizon on large data.
  - **Protecting correct cells helps.** Running Raha first to protect correct values improved most algorithms.
  - **This is the most important single finding for crivo's scorer** (see suggestion S1).

### 1.3 LLM-based cleaning, 2022 to 2026

**Foundation models and direct prompting**

- **"Can Foundation Models Wrangle Your Data?"** (Narayan et al., PVLDB 16, 2022; [arXiv 2205.09911](https://ar5iv.labs.arxiv.org/html/2205.09911); [VLDB PDF](https://www.vldb.org/pvldb/vol16/p738-narayan.pdf)). Five wrangling tasks, error detection among them, were posed as prompts.
  - With 10 demonstrations, GPT-3 matched or beat the prior state of the art on 11 of 14 datasets ([HazyResearch blog, 2023-01-13](https://hazyresearch.stanford.edu/blog/2023-01-13-datawrangling)).
  - Code [HazyResearch/fm_data_tasks](https://github.com/HazyResearch/fm_data_tasks) has no licence and was last committed 2023-01-19.
- **Jellyfish** (instruction-tuned 7B/8B/13B local models for error detection, imputation, schema matching and entity matching): EMNLP 2024 ([ACL Anthology](https://aclanthology.org/2024.emnlp-main.497)). The authors claim parity with GPT-3.5/4 on these tasks.

**Hybrid detectors: the LLM labels, a classifier detects**

- **ZeroED** (Ni et al., ICDE 2025; [arXiv 2504.05345, Apr 2025](https://arxiv.org/html/2504.05345v1)). The LLM labels about 5% of the data, chosen by clustering, then a cheap classifier is trained on those labels. No human labels are used.
  - Detection F1 by dataset: hospital 0.811, flights 0.722, beers 0.774, rayyan 0.732, billionaire 0.767, movies 0.765.
  - The plain-prompt baseline FM_ED scores 0.651, 0.660, 0.139, 0.662, 0.674 and 0.583 on the same datasets.
  - The default model is Qwen2.5-72B.
  - Code [ZJU-DataVIP-Lab/ZeroED](https://github.com/ZJU-DataVIP-Lab/ZeroED) has no licence.
- **TreeED / ForestED** ("LLM-as-inducer": the LLM writes a decision tree of rule checks and GNN nodes, and an ensemble combines the trees): [arXiv 2512.07246](https://arxiv.org/abs/2512.07246). Submitted Dec 2025, revised 2026-07-29, accepted at KDD 2026. It claims +16.1% average F1 over the best baseline and lists no code.
- **GIDCL** (graph-based, LLM creator-critic rule generation, 20 labelled tuples): PACMMOD 2(6), SIGMOD 2025 track ([DOI 10.1145/3698811](https://api.crossref.org/works/10.1145%2F3698811)). It claims +10% F1.
- **IterClean** (detector, verifier and repairer loop from 5 labelled tuples): ACM TURC 2024 ([CityU record](https://rims.cityu-dg.edu.cn/en/publications/iterclean-an-iterative-data-cleaning-framework-with-large-languag/)). It claims up to 3× the F1 of prior work.

**LLMs that write rules or programs**

- **LLMClean** (the LLM generates ontological functional dependencies, which then drive detection): [arXiv 2404.18681, Apr 2024](https://arxiv.org/abs/2404.18681v1).
- **Cocoon**, from Columbia (Huang, Wu).
  - Semantic profiling ([arXiv 2404.12552, Apr 2024](https://arxiv.org/html/2404.12552v1)) uses an LLM to decide whether a statistical anomaly is a real error.
  - Cleaning ([arXiv 2410.15547, Oct 2024](https://arxiv.org/abs/2410.15547v1)) combines LLM rules with statistical detection.
  - Code [Cocoon-Data-Transformation/cocoon](https://github.com/Cocoon-Data-Transformation/cocoon): MIT, 189 stars, last commit 2025-01-22.
- **DataVinci** (Microsoft): it learns majority regex patterns per column, flags violators, and repairs toward the majority pattern. An LLM abstracts the semantic substrings first, and execution traces of a downstream program serve as a second signal ([arXiv 2308.10922, Aug 2023](https://arxiv.org/pdf/2308.10922)).
  - It was published at SIGMOD 2025 **[med]** (secondary listing).
  - No code is public.
- **TabClean** (Wang, …, Chunwei Liu; [arXiv 2606.25388, 2026-06-24](https://arxiv.org/html/2606.25388); code [Wangyibo321/TabClean](https://github.com/Wangyibo321/TabClean), **no licence**, last commit 2026-09-17) is the newest work and the closest to crivo's design.
  - **How it works:**
    - Agents profile the table, diagnose mechanisms, and synthesize Python repair *programs* from a 110 to 369-row annotated dev set.
    - Each repair is a **guarded clause**: a dirty-pattern guard, a *target-negative* guard (skip already-clean values), an evidence guard and a scope guard, plus a deterministic transformation.
    - A deterministic decider commits only the program with the best dev-set F1 that is also "safe". Committed programs then rerun with no LLM calls.
    - Repairs that need weak or external evidence are excluded by design.
  - **Results, cell-level P/R/F1 on held-out rows:**

    | Dataset | P / R / F1 | Best baseline F1 |
    |---|---|---|
    | hospital | 1.00 / 0.77 / 0.87 | 0.95 (HoloClean) |
    | flights | 1.00 / 0.68 / 0.81 | 0.32 (Baran) |
    | beers | 1.00 / 0.89 / 0.94 | 0.88 (Baran) |
    | tax | 1.00 / 0.98 / 0.99 | 0.84 (Baran) |
    | rayyan | 1.00 / 0.85 / 0.92 | 0.36 (Baran) |
    | movies | 0.99 / 0.83 / 0.91 | 0.80 (Baran) |

  - Halving the dev set drops the average F1 from 0.91 to 0.87.
  - Its taxonomy has 10 error classes: typos, missing values, format inconsistency, attribute-dependency violation, out-of-distribution, semantic equivalence, unit/scale, truncation/extraction, schema/type mix, composite/misaligned fields. Each maps onto crivo diseases (d04, d03, d12, d13, d07, d16, d26/d08, d01/d23, d17) except plain typos.

**Agents and workflows**

- **CleanAgent** (LLM agent over `dataprep.clean` type-specific standardizers): demo, [arXiv 2403.08291, Mar 2024](https://arxiv.org/html/2403.08291v3). Code [sfu-db/CleanAgent](https://github.com/sfu-db/CleanAgent): no licence, 78 stars, last commit 2025-06-04.
- **AutoDCWorkflow** (the LLM plans OpenRefine operations for a stated analysis purpose): EMNLP Findings 2025, [arXiv 2412.06724](https://arxiv.org/html/2412.06724v3). The benchmark is in §2.
- **"Exploring LLM Agents for Cleaning Tabular ML Datasets"** (ICLR 2025 workshop; [arXiv 2503.06664, Mar 2025](https://arxiv.org/abs/2503.06664)).
  - Agents fix row-local errors: illogical values, and outliers judged from the other fields in the same row.
  - They fail on errors that need the distribution across many rows.
- **RetClean** (retrieve tuples from a data lake, then let an LLM fix the value): VLDB 2024 demo, [arXiv 2303.16909](https://arxiv.org/html/2303.16909v2).
- **ProfiliTable** (a profiler agent, an operator-retrieving generator, and an evaluator loop over 18 table task types): [arXiv 2605.12376, May 2026](https://arxiv.org/abs/2605.12376). It publishes no numbers on its abstract page and lists no code.

**Surveys and benchmark generators**

- **Survey "Can LLMs Clean Up Your Mess?"** (Zhou, …, Yeye He, Chunwei Liu, et al.; [arXiv 2601.17058, 2026-01-22](https://arxiv.org/html/2601.17058v1)). It comes with a paper list at [weAIDB/awesome-data-llm](https://github.com/weAIDB/awesome-data-llm). Its stated limits of LLM cleaning:
  - cost at scale;
  - hallucination, made worse by self-correction loops;
  - rules synthesized from dirty data that "encode errors as valid rules";
  - "the mismatch between advanced methods and weak evaluation".
- **TableEG** (an LLM fine-tuned to *generate* realistic errors for benchmarks; detectors' scores on its errors track their scores on real errors): [arXiv 2507.10934, Jul 2025, rev. Mar 2026](https://arxiv.org/abs/2507.10934). No code.
- **Glock et al., "Detecting and Cleaning Errors in Personal Contact Information with LLMs"** (VLDB DATAI workshop 2025). It reports LLMs beating Raha and Baran on contact data. Source: [HPI news](https://hpi.de/naumann/news/paper-accepted-at-dataivldb.html) **[med]**.
- **GEIL:** I found no paper, tool or acronym by that name in three searches, including an extended one. It may be a typo or a non-indexed work.

**Takeaways on LLM cleaning for crivo [high, my synthesis]**

- **Direct per-cell prompting is beaten.** Every 2025 to 2026 system that wins has the LLM produce *labels, rules or programs*, then executes something deterministic or cheap.
- **Every high-precision system has a guard.** TabClean's 1.00 precision comes from the target-negative guard and dev-set gating, not from the model.
- **None of these systems re-verifies a fix the way crivo's referee does.** They score on a held-out labelled split instead. crivo's "re-check every fix" stance is still distinctive.

### 1.4 Error detection with corpus statistics and foundation models (Microsoft/Yeye He line)

- **Auto-Detect** (SIGMOD 2018; [MSR page](https://www.microsoft.com/en-us/research/publication/auto-detect-data-driven-error-detection-tables/)). It finds incompatible formats in one column using pattern co-occurrence statistics from a corpus of clean tables, and reports precision above 0.98 on Wikipedia and Excel data.
- **Uni-Detect** (SIGMOD 2019; [MSR PDF](https://microsoft.com/en-us/research/uploads/prod/2019/04/Uni-Detect.pdf)). It uses "what-if" perturbation plus hypothesis tests against a table corpus to find FD violations, numeric outliers and spelling errors, with no per-dataset tuning.
- **Auto-Validate** (SIGMOD 2021; [arXiv 2104.04659](https://arxiv.org/pdf/2104.04659)) infers data-domain patterns for machine-generated strings that minimize false positives.
- **Auto-Test** (Chen, He et al., SIGMOD 2025; [arXiv 2504.10762, 2025-04-14](https://arxiv.org/html/2504.10762v1); code and benchmark [qixuchen/AutoTest](https://github.com/qixuchen/AutoTest), **no licence**) is the most directly usable idea in this section.
  - **Semantic-Domain Constraints (SDCs)** take the form: *if ≥ m of a column's values are in-domain, values beyond distance d_out are errors, with confidence c*. The domain families are:
    - **function-based**, e.g. "≥98% pass `validate_date()`" or "≥99% pass `validate_url()`" → flag the rest;
    - **pattern-based**, regex;
    - **embedding-based**, Sentence-BERT or GloVe;
    - **classifier-based**, the Sherlock or DoDuo column-type models.
  - Each candidate constraint is tested on a corpus with Cohen's h ≥ 0.8 and a χ² test at p < 0.05. Its confidence is the Wilson lower bound (z = 1.65).
  - **Benchmarks:** RT-bench and ST-bench, 1,200 relational plus 1,200 spreadsheet columns. They carry a `ground_truth_debateable` field that counts toward **neither** precision nor recall.
  - **Results (F1 at precision 0.8 / PR-AUC):**
    - Auto-Test Fine-Select: 0.34 / 0.45 on ST-bench and 0.21 / 0.34 on RT-bench.
    - GPT-4 few-shot with chain of thought: 0 / 0.20 and 0 / 0.16. It catches about 80% of errors but floods false positives on codes, abbreviations and proprietary vocabularies, and takes more than 20 s per column.
    - Sherlock and DoDuo used as detectors: about 0 / 0.03 to 0.06.
  - **On 9 classic cleaning datasets** (adults, beers, flights, food, hospital, movies, rayyan, soccer, tax), the new SDCs found 183 cell errors at 95% strict precision. Under *augmented* ground truth it was 97%, because **the original benchmark labels miss real errors**.
- **FAHES** (disguised missing values such as -999 or all-ones phone numbers): KDD 2018 ([PDF](https://qcai.qcri.org/ntang/pubs/kdd18.pdf)). It detects disguised missing values both as syntactic or density **outliers** and as **inliers**, meaning values repeated far more than the MCAR/MAR expectation. This is the research twin of crivo's d04/d05. Code [qcri/FAHES_Code](https://github.com/qcri/FAHES_Code): MIT, C++, last commit 2018.
- **MechDetect** (estimates whether an error mask depends on the data, as in MCAR versus MAR for errors): [arXiv 2512.04138, Dec 2025](https://arxiv.org/abs/2512.04138).

### 1.5 Entity resolution and deduplication

- **Ditto** (fine-tuned pretrained language models for entity matching): PVLDB 14(1), 2021 ([arXiv 2004.00584](https://arxiv.org/pdf/2004.00584)). It beat the prior state of the art by up to 29% F1 and reached 96.5% F1 matching 789K × 412K company records. The repo [megagonlabs/ditto](https://github.com/megagonlabs/ditto) is Apache-2.0, last committed 2021-09-24, so it is stale.
- **LLM entity matching** (Peeters, Steiner, Bizer, EDBT 2025; [arXiv 2310.11244](https://arxiv.org/abs/2310.11244v3); [PDF](https://madoc.bib.uni-mannheim.de/68185/1/paper-81.pdf)): no single prompt is best across models and datasets, and GPT-4 can explain its decisions. Code [wbsg-uni-mannheim/MatchGPT](https://github.com/wbsg-uni-mannheim/MatchGPT) has no licence.
- **AnyMatch** (a small model for zero-shot entity matching): [arXiv 2409.04073, Sep 2024](https://arxiv.org/html/2409.04073v2). It comes within 4.4% of MatchGPT/GPT-4 F1 at about 10⁴× lower cost.
- **LLM-CER** (in-context *clustering* entity resolution): [arXiv 2506.02509, Jun 2025](https://arxiv.org/abs/2506.02509). It cuts API calls by up to 5×, and a PVLDB 19 demo followed ([PDF](https://www.vldb.org/pvldb/vol19/p4746-ke.pdf)).
- **Classic toolkits:**
  - **Splink 5.0.0** (Fellegi-Sunter with EM, SQL backends) was released 2026-09-18 ([release](https://github.com/moj-analytical-services/splink/releases/tag/v5.0.0)).
    - It removes salting and the implicit cache, adds chunked `predict()`, and switches from Bayes factors to match weights.
    - pandas is no longer a core dependency; the core is duckdb, pyarrow and sqlglot. Inputs must be registered as SplinkDataFrames: per the release notes, plus an unofficial migration guide ([gist](https://gist.github.com/RobinL/c6d56a27d8f83c40b6b09643c0fa5d14)) **[med]**.
  - **dedupe** uses active learning, so it needs a human to label pairs.
  - **OpenRefine** clustering (§3) is the deterministic end of the spectrum.

### 1.6 Type and semantic-type inference

- **Sherlock** (KDD 2019, 78 types; [repo](https://github.com/mitmedialab/sherlock-project), MIT, last commit 2023-06-09), **Sato** (VLDB 2020; [repo](https://github.com/megagonlabs/sato), Apache-2.0, 2021-08-30) and **DoDuo** (SIGMOD 2022; [repo](https://github.com/megagonlabs/doduo), Apache-2.0, 2022-06-10).
  - All three are unmaintained and TensorFlow/PyTorch-heavy.
  - Auto-Test (above) found them near-useless as *error* detectors.
- **LLM column-type annotation:**
  - Korini and Bizer, "Column Type Annotation using ChatGPT": [arXiv 2306.00745, Jun 2023](https://arxiv.org/pdf/2306.00745).
  - **ArcheType** (PVLDB 17(9), 2024; [arXiv 2310.18208](https://arxiv.org/pdf/2310.18208); [repo](https://github.com/penfever/ArcheType), MIT, last commit 2025-05-21): zero-shot, with context sampling and label remapping. It scores 85.97 weighted F1 on SOTAB according to a leaderboard aggregator **[med]**.
  - Retrieve-and-Verify context selection: [arXiv 2508.17203, Aug 2025](https://arxiv.org/pdf/2508.17203).
- **ptype** (probabilistic finite-state machines that infer a column's type *and* flag which values are missing or anomalous under that type): Data Mining and Knowledge Discovery 34(3), 2020 ([arXiv 1911.10081](https://arxiv.org/pdf/1911.10081)). The repo [alan-turing-institute/ptype](https://github.com/alan-turing-institute/ptype) is MIT and archived (last commit 2021-10-27). Its model of "type plus missing plus anomaly per value" is exactly the shape of crivo's d01/d04 split.
- **SortingHat / ML Data Prep Zoo** (feature-type inference benchmark, 9,921 labelled columns in 9 classes): SIGMOD 2021 ([summary](https://rmarcus.info/dbscholar/papers/6165) **[med]**). Repo [vraj-ucsd/ML-Data-Prep-Zoo](https://github.com/vraj-ucsd/ML-Data-Prep-Zoo): Apache-2.0, last commit 2021-11-10.

### 1.7 Format and unit normalisation

- **PUC** (probabilistic unit canonicalizer, which identifies a column's dimension and maps unit symbols to a knowledge graph): Ceritli and Williams, [arXiv 2111.11959, Nov 2021](https://arxiv.org/abs/2111.11959v1). It claims the first unit-annotated messy tables and lists no code.
- **The 2024 semantic-table-interpretation survey** reports that most systems normalise units with hand-written rules (about 200 conversions) or regexes ([arXiv 2411.11891](https://arxiv.org/pdf/2411.11891)).
- **Measured hazards in common parsers** (2026-10-23, my run):
  - `price-parser` 0.5.1 parses `"12k"` as amount `12`, silently dropping the multiplier.
  - `quantulum3` 0.10.0 parses `5'11"` as `5 "unk to the 11"`.
  - Both parse clean inputs well, e.g. `"1.234,56 €"` → 1234.56 EUR and `"70 kg/m2"` → kilogram per square metre.
  - **Implication:** a fixer that trusts a parser needs a *residual check* (nothing unexplained left in the string), not just "it parsed".

### 1.8 Spreadsheet structure: tables in sheets and header detection

- **TableSense** (CNN table detection): AAAI 2019. The repo [microsoft/TableSense](https://github.com/microsoft/TableSense) holds **annotations only**: 2,615 tables in 1,645 spreadsheets from VEnron2, VEUSES and VFUSE, under the O-UDA data licence. It has no code and was last committed 2025-10-06.
- **SpreadsheetLLM / SheetCompressor** was published as "Encoding Spreadsheets for Large Language Models" at EMNLP 2024 ([ACL author page](https://aclanthology.org/people/yuzhang-tian/); [arXiv 2407.09025](https://arxiv.org/html/2407.09025v1)).
  - A fine-tuned model reaches 78.9% F1 on table detection, 12.3 points above prior work. Encoding uses 96% fewer tokens.
  - No code has been released ([computing.co.uk](https://computing.co.uk/news/4335791/microsoft-unveils-prototype-llm-designed-analyse-spreadsheets) **[med]**).
- **Auto-Tables** (synthesizes multi-step "relationalize" transforms without examples): PVLDB 16(11), 2023, Best Paper ([arXiv 2307.14565](https://arxiv.org/pdf/2307.14565)).
  - More than 30% of real spreadsheet and web tables are not relational. It solves over 70% of the 244 ATBench cases.
  - The benchmark is at [LiPengCS/Auto-Tables-benchmark](https://github.com/LiPengCS/Auto-Tables-benchmark) with no licence. The code is unreleased.
- **The HPI line (Naumann group):**
  - **Strudel** (EDBT 2021; [HPI page](https://hpi.de/projects/data-preparation/structure-detection-in-verbose-csv-files/)): a random forest classifies each line and cell as header, data, derived (aggregate), notes and so on, using content, context and *computational* features (arithmetic relations between rows). Repo Apache-2.0, 0 stars.
  - **AggreCol** (EDBT 2022; [HPI page](https://hpi.de/projects/data-preparation/aggregation-detection-in-verbose-csv-files/); repo [HPI-Information-Systems/AggreCol](https://github.com/HPI-Information-Systems/AggreCol), Apache-2.0): detects sum, difference, average, division and relative-change aggregations in verbose CSVs. At 0.95 precision and recall it covers 91.1% and 86.3% of the files on two annotated corpora.
  - **Mondrian** (multi-region layout templates): PVLDB 15(3), 2022 ([arXiv 2109.06630](https://web3.arxiv.org/pdf/2109.06630v1)). The repo is **GPL-3.0**.
- **Pytheas** (table discovery and line classification in open-data CSVs from per-column value coherence): PVLDB 13(11), 2020 ([VLDB page](https://mail.vldb.org/pvldb/volumes/13/paper/Pytheas%3A%20Pattern-based%20Table%20Discovery%20in%20CSV%20Files)).
  - It reaches 95.9% precision and 95.7% recall, against 89.6% and 81.3% for prior methods, on 4,500 annotated files.
  - The repo [cchristodoulaki/Pytheas](https://github.com/cchristodoulaki/Pytheas) has no licence.
- **openpyxl already gives deterministic evidence** (measured with openpyxl 3.1.5):
  - `ws.tables`: declared Excel Tables with their ranges, e.g. `{'T1': 'A3:C4'}`.
  - `ws.merged_cells.ranges`: e.g. a merged title `A1:C1` sitting above the header.
  - formula cells: `data_type == 'f'`, value `=SUM(C4:C4)`.
  - `python-calamine` 0.9.0 exposes `merged_cell_ranges` too, but it reads cached values only. A file saved without cached results shows `''` for a formula cell.

### 1.9 Date parsing

- **pandas PDEP-4** (implemented) makes `to_datetime` infer the format from the first non-NaN value and apply it to the whole column ([PDEP-4](https://pandas.pydata.org/pdeps/0004-consistent-to-datetime-parsing.html)). The issue "ENH: try both dayfirst and monthfirst" is still open (pandas #52508, opened 2023-04-07).
- **Measured: three popular parsers silently corrupt ISO dates under day-first settings.**

  | Parser and version | Call | Result |
  |---|---|---|
  | pandas 3.0.5 (crivo's) and 3.1.0 | `guess_datetime_format("2025-03-04", dayfirst=True)` | `"%Y-%d-%m"` |
  | pandas 3.0.5 (crivo's) and 3.1.0 | `pd.to_datetime(["2025-03-04"], dayfirst=True)` | **2025-04-03** |
  | pandas 3.0.5 (crivo's) and 3.1.0 | the same call with a day > 12 in the column | raises |
  | dateutil 3.0.0 (released 2026-10-21, [release notes](https://github.com/dateutil/dateutil/releases/tag/3.0.0)) | `parse("2025-03-04", dayfirst=True)` | 2025-04-03 |
  | dateutil 3.0.0 | `parse("2025-03-25", dayfirst=True)` | 2025-03-25 |
  | dateparser 1.4.3 | `DATE_ORDER="DMY"` on `"2025-03-04"` | 2025-04-03 |
  | dateparser 1.4.3 | `DATE_ORDER="DMY"` on `"2025-03-25"` | `None` |

  - dateutil's two results mean that **one ISO column gets two different field orders**.
  - `isoparse` is correct.
- **Measured: `format="mixed"` mixes orders within a column.** `pd.to_datetime(["03/04/2025","25/03/2025","04/05/2025"], format="mixed")` → 2025-03-04, 2025-03-25, 2025-04-05: per-element guessing reads a day-first column month-first wherever it's ambiguous.
- **Column-level disambiguation is the established practice:**
  - one unambiguous value (day > 12) fixes the whole column;
  - sibling columns and monotonic sort order break ties;
  - otherwise leave the column as text and flag it.
  - Sources: the small csvmedic library ([docs](https://csvmedic.readthedocs.io/en/latest/how-it-works/); [repo](https://github.com/Phantasm0009/CSVMedic), MIT, 1 star) and vendor write-ups ([Clarus FT](https://www.clarusft.com/auto-detecting-date-format-in-csv-files/)) **[med]**. I found no peer-reviewed paper on it.
- **DuckDB's sniffer** checks ISO first, then a preference-ordered list of 6 date and 7 timestamp formats, letting later values rule formats out. It samples 20,480 rows from several positions in the file ([DuckDB docs](https://duckdb.org/docs/2.0/data/csv/auto_detection.html)).

### 1.10 Excel-specific damage (d22 id-numeric-corruption)

- **Gene-name errors:** 30.9% (3,436 of 11,117) of PubMed Central articles with Excel gene lists had gene names turned into dates or numbers. The problem kept growing after 2016 (Abeysooriya et al., *PLOS Comp Biol*, Jul 2021, [PMC8357140](https://pmc.ncbi.nlm.nih.gov/articles/PMC8357140)).
- **Excel's documented limits:** it keeps 15 significant digits, zeroing digits 16 and beyond, and strips leading zeros ([Microsoft support](https://support.microsoft.com/en-us/office/keep-leading-zeros-and-large-numbers-1bf7b935-36e1-4985-842f-5dfa51f85fe7)).
  - The lost digits cannot be recovered, so the honest action is to *detect and refuse*, not to "repair" **[high, my inference]**.

---

## 2. Benchmarks crivo could add

| Benchmark | What it holds | Dirty/clean pairs? | Licence | Fit for crivo |
|---|---|---|---|---|
| **Raha `movies_1` and `tax`** ([BigDaMa/raha/datasets](https://github.com/BigDaMa/raha)) | The two Raha pairs crivo doesn't use yet. tax has 200k rows of BART-injected errors; movies has 7,390 real rows. | Yes | Apache-2.0 repo (the source data's provenance varies **[med]**) | **S**: same adapter as today. TabClean, ZeroED and Ni et al. all report on them, so external comparisons become possible. |
| **Clean Me If You Can** (Ahmadi, …, Abedjan; [arXiv 2606.31983, 2026-06-30](https://arxiv.org/html/2606.31983v2); [D2IP-TUB/Clean-Me-If-You-Can](https://github.com/D2IP-TUB/Clean-Me-If-You-Can)) | 4.34M real web postal addresses in 8 fields, from Common Crawl, with a geocoded OpenStreetMap truth. 48.9% of cells are dirty in 12 classes (missing 23.7%, abbreviation 9.3%, language 6.9%, typos 1.2%). | Yes, **real** | Code MIT. **Ground truth ODbL 1.0 (share-alike)**. Dirty data under Common Crawl terms. | **M**: fetch it, never vendor it. Baseline scores: correction F1 0.46 Baran, 0.42 LLM (Glock), 0.18 DataWig; Raha ran out of memory above 100k rows. It stresses d07 (abbreviation and alias variants) and d17 packed fields. |
| **Pollock** (Vitagliano et al., PVLDB 16(8), 2023; [repo](https://github.com/HPI-Information-Systems/Pollock)) | About 2,290 polluted CSVs: preambles, multiple headers, two tables in one file, ragged rows, alternative delimiters and quoting, mixed newlines. Loaders get a "simple" and a "weighted" score. | Source file vs. loaded result | MIT (LICENSE added 2026-07-16) | **M**: the reader's bench. Scores: pandas 1.4.3 (configured) 9.895 / 9.431; CleverCSV 0.7.4 (auto) 9.193 / 9.453; DuckDB 1.2 configured 9.961, auto 9.075. A 0-star pure-Python loader created 2026-09-24 ("sieve") was added by its own author on 2026-09-27 and tops the table at 9.997, which is an overfitting warning **[high, my inference]**. |
| **CleverCSV corpus** (van den Burg et al., DMKD 33(6), 2019; [arXiv 1811.11242](https://arxiv.org/abs/1811.11242); [CSV_Wrangling](https://github.com/alan-turing-institute/CSV_Wrangling), MIT) | Thousands of real GitHub and UK-data CSVs labelled with their dialect. CleverCSV scores 97% overall and +21 to 22% on messy files. | Dialect labels | MIT repo (the files themselves are third-party) | **S/M**: dialect-detection regression set for the reader. |
| **Auto-Test RT/ST-bench** ([qixuchen/AutoTest](https://github.com/qixuchen/AutoTest)) | 2,400 real columns with labelled single-value errors plus a *debatable* class. Only about 3 to 4% of columns contain errors. | Column-level error labels | **No licence**: ask the authors | **M**: the best external set for single-column detectors (d13, d07, d01). Its realistic base rate punishes false positives. |
| **AutoDCWorkflow** ([LLM4DC](https://github.com/LanLi2017/LLM4DC)) | 96 tables and 142 analysis purposes, each with a raw table, a clean table, a workflow and answers. Built from NYPL menus, Chicago food inspections, PPP loans, hospital and flights. | Yes, injected | **No licence** | Fits the analyst's end-to-end eval (purpose → answer), not the library. |
| **REIN** (Abdelaal et al., EDBT 2023, [PDF](https://openproceedings.org/2023/conf/edbt/3-paper-49.pdf); [repo](https://github.com/mohamedyd/rein-benchmark)) | 14 datasets and 38 detection and repair methods, scored by the effect on downstream ML. | Mostly injected | No licence | Low: aimed at ML impact. |
| **Ni et al. repair benchmark** ([repo](https://github.com/WelkinNi/Automatic-Data-Repair)) | 12 algorithms on 5 dirty sets plus 7 ML workloads, with EDR. | Yes | No licence | Adopt the **metric**, not the code. |
| **TableSense annotations** ([repo](https://github.com/microsoft/TableSense)) | 2,615 table ranges in 1,645 real Enron/EUSES/FUSE sheets. | Region labels | O-UDA (permissive data agreement) | **M**: Excel table detection and header damage (d18, d24). |
| **Auto-Tables ATBench** ([repo](https://github.com/LiPengCS/Auto-Tables-benchmark)) | 244 non-relational tables with their target relational form. | Yes | No licence | Analyst-level "reshape" eval. |
| **SortingHat zoo** ([repo](https://github.com/vraj-ucsd/ML-Data-Prep-Zoo)) | 9,921 columns labelled by feature type, including "embedded number" and "list". | Type labels | Apache-2.0 | **S**: a type-inference check for d01, d02, d17 and d23. |
| **Error injectors** | **BART** (PVLDB 2015; [dbunibas/BART](https://github.com/dbunibas/BART), MIT, Java): constraint-aware error generation. **Jenga** (EDBT 2021; [schelterlabs/jenga](https://github.com/schelterlabs/jenga), **GPL-3.0**). **TableEG** (LLM-generated realistic errors, no code). | n/a | see each | Ideas for the bench's injectors. Under crivo's rule, only the eval-author may apply them, without reading `detect.py`. |
| **KramaBench** (ICLR 2026; [arXiv 2506.06541](https://arxiv.org/html/2506.06541v1)) and **DCA-Bench** ([arXiv 2406.07275](https://arxiv.org/abs/2406.07275v2)) | KramaBench: 104 data-lake pipelines; the best system reaches 55% end-to-end. DCA-Bench: dataset curation agents asked to *find* real quality issues, graded by an LLM. | n/a | see papers | Analyst-level only. DCA-Bench's grading by an LLM conflicts with crivo's "measured, not self-reported" stance. |

**Benchmark caveat:** the classic Raha-family ground truth is *incomplete*. Auto-Test's manual check found that benchmark labels miss real errors, which moved its precision from 95% strict to 97% augmented ([arXiv 2504.10762](https://arxiv.org/html/2504.10762v1)). So a detector that finds a real but unlabelled error is charged a false positive. Reporting a "debatable" bucket is the honest fix.

---

## 3. Open-source libraries

Stars, licence and last commit are from the GitHub API on 2026-10-23. "pandas 3": crivo requires `pandas>=3.0.5`. "Import" is the warm import time I measured. "Light" means fewer than 5 runtime dependencies and less than 100 ms to import.

### 3.1 Libraries crivo could depend on, or copy logic from

| Library | What it does | Licence | Stars | Last commit / release | Maintained | pandas 3 | Import-light? | Use for crivo |
|---|---|---|---|---|---|---|---|---|
| [ftfy](https://github.com/rspeer/python-ftfy) | Fixes mojibake. `ftfy.badness.is_bad()` is a detector. | Apache-2.0 | 4,067 | 2024-10-30 / 6.3.1 (2024-10-26) | Stable, slow-moving (one maintainer) | n/a | **Yes**: 1 dependency, 23 ms | **d08**, detector and fixer (measured: `CafÃ©`→`Café`, idempotent, `naïve` untouched) |
| [CleverCSV](https://github.com/alan-turing-institute/CleverCSV) | CSV dialect detection from row-pattern and type consistency | MIT | 1,342 | 2026-07-02 / 0.8.5 (2026-05-11) | Yes | wrapper available | Mostly: 3 dependencies (chardet, regex, packaging), 84 ms | Reader: dialect sniffing. **chardet risk**, see 3.3. |
| [charset-normalizer](https://pypi.org/project/charset-normalizer/) | Encoding detection | MIT | n/a | 3.5.2 (2026-09-30) | Yes | n/a | **Yes**: 0 dependencies, 11 ms | Reader: encoding (instead of chardet) |
| [python-calamine](https://pypi.org/project/python-calamine/) | Fast Rust xlsx/xls/ods reader, exposes merged ranges | MIT | n/a | 0.9.0 (2026-10-16) | Yes | n/a | **Yes**: 0 dependencies, 2 ms | Reader: speed. Keep openpyxl for formulas and tables. |
| openpyxl ([PyPI](https://pypi.org/project/openpyxl/)) | xlsx reader: `ws.tables`, merged ranges, formulas | MIT | n/a (hosted on Heptapod) | 3.1.5 (2024-06-28) | Slow | crivo already depends on it | Yes | d18, d21, d24 evidence (§1.8) |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | Levenshtein, Jaro and token ratios in C++ | MIT | 4,176 | 2026-10-21 / 3.14.6 | Yes | n/a | **Yes**: 0 dependencies, 7 ms | d07 and d10 similarity, behind blocking |
| [jellyfish](https://github.com/jamesturk/jellyfish) | Phonetic codes (Soundex, Metaphone, NYSIIS) and distances | MIT | 2,232 | 2026-10-16 | Yes | n/a | **Yes**: 1 ms | d07 phonetic keys (OpenRefine-style) |
| [anyascii](https://github.com/anyascii/anyascii) | Unicode → ASCII transliteration | ISC | 424 | 2025-08-12 / 0.3.3 | Yes | n/a | **Yes**: 0 dependencies, 11 ms | Fingerprint keys (in place of GPL Unidecode) |
| [phonenumbers](https://github.com/daviddrysdale/python-phonenumbers) | Port of Google libphonenumber: parse, validate, E.164 | Apache-2.0 | 3,774 | 2026-10-08 / 9.0.41 | Yes | n/a | Yes: 0 dependencies, 10 ms, **23 MB on disk** (`phonenumberslite` is smaller) | d13/d07 phone validity and canonical form; a verifiable round-trip |
| [validators](https://github.com/python-validators/validators) | email, url, domain, iban, uuid and other validators | MIT | 1,131 | 2026-10-22 | Yes | n/a | **Yes**: 12 ms | Function-based semantic-domain constraints (S3) |
| [price-parser](https://github.com/scrapinghub/price-parser) | Amount and currency from price strings | BSD-3 | 348 | 2026-10-06 / 0.5.1 (2026-03-19) | Yes | n/a | **Yes**: 1 dependency, 15 ms | d01 money strings, **with a residual check** (`"12k"`→12) |
| babel (`babel.numbers.parse_decimal`) ([PyPI](https://pypi.org/project/babel/)) | Locale-aware number parsing | BSD-3 | n/a | 2.18.0 (2026-02-01) | Yes | n/a | 7 ms for `babel.numbers`, **33 MB on disk** | d01 locale decimals (1.234,5) |
| [Pint](https://github.com/hgrecco/pint) | Units registry and dimension-checked conversion | BSD-3 | 2,816 | 2026-10-22 / 0.26.2 (2026-10-19) | Yes | pint-pandas exists | Medium: 4 dependencies, 87 ms | d16: convert only within one dimension, a deterministic check |
| [quantulum3](https://github.com/nielstron/quantulum3) | Extracts quantities and units from text | MIT | 149 | 2026-03-09 / 0.10.0 | Thin | n/a | 21 ms but **24 MB**; misparses `5'11"` | Not recommended as a dependency; useful as a unit-alias list |
| [dateparser](https://github.com/scrapinghub/dateparser) | Many-language date parsing | BSD-3 | 2,860 | 2026-10-23 / 1.4.3 (2026-09-03) | Yes | n/a | 4 dependencies, 106 ms | Only with explicit settings, never `DATE_ORDER` on ISO (§1.9) |
| python-dateutil ([repo](https://github.com/dateutil/dateutil)) | Already a transitive dependency via pandas | Apache-2.0 / BSD dual | 2,641 | 3.0.0 (2026-10-21) | Yes | pandas dependency | Light | `isoparse` is safe; `parse(dayfirst=True)` is not (§1.9). 3.0 changes timezone gap offsets. |
| [datasketch](https://github.com/ekzhu/datasketch) | MinHash LSH for near-duplicates | MIT | 2,976 | 2026-10-10 / 2.0.0 | Yes | n/a | **No**: pulls scipy, 250 ms | d10 at scale, as an optional extra |
| [Splink](https://github.com/moj-analytical-services/splink) | Probabilistic record linkage (Fellegi-Sunter, EM) on DuckDB | MIT | 2,531 | 2026-10-21 / 5.0.0 (2026-09-18) | **Very active** | pandas-free core; DataFrames must be registered | No: duckdb, pyarrow, sqlglot | d10 at scale, as an optional extra |
| [pandera](https://github.com/unionai-oss/pandera) | DataFrame schema and contract validation | MIT | 4,493 | 2026-10-24 UTC / 0.34.1 (2026-10-06) | Very active | pandas ≥ 2.1.1 | Medium: 5 dependencies, 0.23 s | Export a verifiable schema of the cleaned frame (an artifact, not a detector) |
| [frictionless](https://github.com/frictionlessdata/frictionless-py) | Table schema inference and validation (blank-row, extra-cell, type-error…) | MIT | 848 | 2026-10-15 / 5.21.0 | Yes | partial | **No**: 21 dependencies | Learn from its error codes. Don't depend on it. |
| [skrub](https://github.com/skrub-data/skrub) | `Cleaner` (null strings, constant columns, date and number parsing), `deduplicate` (n-gram plus hierarchical clustering) | BSD-3 | 1,660 | 2026-10-22 / 0.11.0 (2026-10-01) | Very active | Yes | **No**: 1.1 s import, pulls scikit-learn and matplotlib | Copy ideas: its null-string list, and canonical = most frequent in a cluster ([Cleaner docs](https://skrub-data.org/stable/reference/generated/skrub.Cleaner.html), [deduplicate docs](https://skrub-data.org/stable/reference/generated/skrub.deduplicate.html)) |
| [pyjanitor](https://github.com/pyjanitor-devs/pyjanitor) | Method-chaining cleaning helpers (`clean_names`…) | MIT | 1,499 | 2026-10-23 / 0.32.54 | Very active | Requires pandas ≥ 3.0 | No: pulls janitor-rs, scipy | Little detector logic to borrow |
| [OpenRefine](https://github.com/OpenRefine/OpenRefine) (Java) | Clustering: fingerprint, n-gram fingerprint, phonetic, kNN with blocking | BSD-3 | 12,066 | 2026-10-23 | Very active | n/a | n/a (re-implement it, about 30 lines) | **d07**: fingerprint is "the least likely to produce false positives" ([docs](https://openrefine.org/docs/technical-reference/clustering-in-depth)) |
| [DuckDB](https://github.com/duckdb/duckdb) | `sniff_csv` (dialect, header, types, date format) | MIT | 42,472 | 2026-10-23 | Very active | Arrow interop | No (a large wheel) | Reader: a second opinion on dialect and date formats (optional) |

### 3.2 Libraries that are a poor fit, and why

| Library | Licence | Stars | Last commit / release | Problem |
|---|---|---|---|---|
| [cleanlab](https://github.com/cleanlab/cleanlab) | **Apache-2.0 only since 2025-12-16** (AGPL-3.0 before; v2.9.0 of 2026-01-13 is the first Apache release) | 11,718 | 2026-01-13 | No commits since 2026-01-13. The company was acquired by Handshake in Jan 2026 ([aiwiki](https://www.aiwiki.ai/wiki/cleanlab)) **[med]**. Datalab outlier and near-duplicate checks need feature vectors or a k-NN graph ([docs](https://docs.cleanlab.ai/stable/cleanlab/datalab/guide/issue_type_description.html)). It targets ML labels and pulls scikit-learn. |
| [great_expectations](https://github.com/fivetran/great_expectations) (the repo now lives under `fivetran/`) | Apache-2.0 | 11,897 | 2026-10-22 / 1.24.1 | 25 core dependencies. Fivetran announced stewardship of GX Core on 2026-05-13, and GX Cloud went to FICO ([Fivetran PR](https://www.fivetran.com/press/fivetran-to-become-steward-of-the-great-expectations-open-source-community-and-gx-core-project); [GX blog](https://www.greatexpectations.io/blog/an-update-from-great-expectations)). It is a validation framework, not a detector. |
| ydata-profiling, renamed **fg-data-profiling** ([repo](https://github.com/Data-Centric-AI-Community/fg-data-profiling)) | MIT | 13,736 | 2026-09-11 / 4.20.0 | **Pins `pandas<3.0`**, which crivo can't install, plus 21 dependencies. The rename to fg-data-profiling comes from the repo README ([README](https://raw.githubusercontent.com/Data-Centric-AI-Community/fg-data-profiling/develop/README.md)). |
| [dataprep](https://github.com/sfu-db/dataprep) (with `dataprep.clean`) | MIT | 2,270 | 2024-04-03; PyPI 0.4.5 dates from 2022-08-04 | **Pins `pandas<2.0`, effectively dead.** Its `clean_*` standardizer list is still a useful catalogue. |
| [recordlinkage](https://github.com/J535D165/recordlinkage) | BSD-3 | 1,063 | 2023-07-20 / 0.16 | **Pins `pandas<3`**, unmaintained. |
| [dedupe](https://github.com/dedupeio/dedupe) | MIT | 4,520 | 2025-07-29 / 3.0.3 (2024-08-15) | Active learning needs human-labelled pairs, which doesn't fit unattended AUTO. 11 dependencies. |
| [datacleaner](https://github.com/rhiever/datacleaner) | MIT | 1,078 | 2017-01-18 | Dead. |
| [Unidecode](https://github.com/avian2/unidecode) | **GPL-2.0+** | 611 | 2026-01-05 / 1.4.0 | GPL, so it can't ship in an MIT wheel. Use anyascii (ISC). `text-unidecode` is under the Artistic licence. |
| [deepchecks](https://github.com/deepchecks/deepchecks) | **AGPL-3.0** | 4,067 | 2025-11-24 | Its "data integrity" checks (mixed nulls, string mismatch, special characters…) are good inspiration. The AGPL rules out its code. |
| [Desbordante](https://github.com/Desbordante/desbordante-core) | **AGPL-3.0** | 512 | 2026-10-14 / 2.5.0 | Strong FD, AFD and UCC discovery (d11, d12), but AGPL. [Metanome](https://github.com/HPI-Information-Systems/Metanome) (Apache-2.0, Java) is the permissive reference. |
| [Zingg](https://github.com/zinggAI/zingg) | **AGPL-3.0** | 1,261 | 2026-10-19 | AGPL, and it needs Spark. |
| [soda-core](https://github.com/sodadata/soda-core) | **Elastic License 2.0** (not OSI-approved) | 2,444 | 2026-10-23 | Not open source in the OSI sense. |
| [Mondrian](https://github.com/HPI-Information-Systems/Mondrian), [Jenga](https://github.com/schelterlabs/jenga) | **GPL-3.0** | 14 / 43 | 2022 | Use the ideas only. |
| pycountry ([PyPI](https://pypi.org/project/pycountry/)), python-nameparser ([repo](https://github.com/derek73/python-nameparser)) | **LGPL-2.1** | n/a / 720 | 2026 | Usable only as an optional dependency, never vendored. |
| Sherlock, Sato, DoDuo, Ditto, HoloClean, ptype, datawig ([archived](https://github.com/awslabs/datawig)) | MIT / Apache | 35 to 543 | 2019 to 2023 | Unmaintained, ML-framework-heavy, not import-light. |
| Research code: TabClean, ZeroED, AutoTest, LLM4DC, CleanAgent, REIN, MatchGPT, fm_data_tasks, Automatic-Data-Repair, Pytheas, Auto-Tables-benchmark | **No licence** | 1 to 110 | 2021 to 2026 | All rights reserved, so ideas only. Reimplement from the paper. |
| TabPFN (tabular foundation model, *Nature* Jan 2025) | Prior Labs License (Apache-2.0 plus attribution) ([HF card](https://huggingface.co/Prior-Labs/TabPFN-v2)) **[med]** | n/a | n/a | Torch-heavy, so no place in a keyless, import-light library. Its unsupervised outlier extension exists **[med]**. |

### 3.3 Licence notes

- **chardet** went from LGPL-2.1 to MIT at 7.0.0 (March 2026), a rewrite done with AI assistance. The original author disputes it in chardet issue #327 ([LWN](https://lwn.net/Articles/1061466/); [Simon Willison](https://simonw.substack.com/p/can-coding-agents-relicense-open)) **[med]**.
  - PyPI lists chardet 7.7.0 (2026-10-18) as `0BSD`.
  - CleverCSV depends on chardet, so CleverCSV carries this provenance question. An MIT project that wants zero ambiguity should prefer charset-normalizer for encoding **[high, my inference]**.
- **Apache-2.0** dependencies (ftfy, phonenumbers, dateutil, cleanlab ≥ 2.9) are compatible with MIT, with NOTICE obligations if vendored.
- **ODbL** (the Clean Me If You Can ground truth) is share-alike for the *database*. Fetching it for a benchmark is fine; committing derived tables to the repo would trigger the share-alike terms **[med]**.

---

## 4. What crivo should do (ranked)

**Ranking basis:** expected effect on the trust story and the Stage 0 rows (detector honesty, new fixers, readers, an honest scorer), divided by effort.

- **Effort:** S is under a day, M a few days, L a week or more.
- **Det. fit:** does the fix or detection satisfy "a fix must be verifiable by a deterministic check"?
- **Process:** bench items that add injectors belong to the eval-author under crivo's rule, which forbids reading `detect.py` or `autoclean.py`.

| # | Suggestion | crivo piece | Source | Effort | Licence | Det. fit |
|---|---|---|---|---|---|---|
| S1 | Add **EDR** and a "clean cells broken" count to the repair score, plus recall-at-precision and a debatable bucket | Scorer (`bench/score.py`) | Ni et al. PVLDB 2024; Auto-Test SIGMOD 2025 | S | n/a (metric) | Yes |
| S2 | **Dates:** column-level format resolution, an explicit-format whitelist, a `strftime` round-trip verifier, never `dayfirst` on ISO | d02, d03 detector and fixer | PDEP-4, DuckDB sniffer, csvmedic heuristics, my measurements | M | own code | Yes |
| S3 | **Honest silence:** sampled checks report "< 3/n at 95%" instead of clean. **Function-based semantic-domain constraints** with Wilson bounds. | Detector honesty, d13 | Hanley and Lippman-Hand 1983; Auto-Test | S + M | validators MIT, phonenumbers Apache-2.0 | Yes |
| S4 | **Bench:** add Raha `movies_1` and `tax`; add Pollock for readers; add a Clean Me If You Can slice | Bench | BigDaMa/raha, Pollock, D2IP-TUB | S / M / M | Apache-2.0 / MIT / ODbL (fetch only) | n/a |
| S5 | **d08 mojibake** via ftfy (detect with `is_bad`, fix with `fix_text`) | d08 fixer | ftfy | S | Apache-2.0 | Yes |
| S6 | **d07 variants:** OpenRefine fingerprint and n-gram keys as the AUTO tier; RapidFuzz kNN with blocking as GATE | d07 detector and fixer | OpenRefine docs, skrub.deduplicate | S/M | BSD-3 (ideas), MIT (RapidFuzz) | Fingerprint: yes. kNN: no, judgment. |
| S7 | **d21 aggregate rows:** confirm candidates arithmetically (sum, avg of a block) plus Excel `=SUM(` formulas | d21 detector and fixer | AggreCol EDBT 2022, Strudel, openpyxl | M | Apache-2.0 (ideas) | Yes |
| S8 | **Parse with a residual check** for money, locale numbers and units; convert units only within one Pint dimension | d01, d16 fixers | price-parser, babel, Pint; my measurements | M | BSD-3 | Yes |
| S9 | **Reader structure:** dialect via CleverCSV or DuckDB `sniff_csv`, encoding via charset-normalizer, Pytheas-style header and line classification with the "header types differ from body" rule, openpyxl tables and merges | Readers, d18, d24 | CleverCSV, DuckDB docs, Pytheas, Strudel, TableSense | M/L | MIT / BSD (Pytheas ideas only) | Partly (see below) |
| S10 | **d04/d05 sentinels:** FAHES-style inlier test (a value repeated far beyond expectation) and pattern-outlier test, plus skrub's null-string list | d04, d05 detector | FAHES KDD 2018 | M | MIT (ideas) | Detection: yes. The fix to NaN is verifiable. |
| S11 | **Analyst fixes as guarded clauses:** a dirty guard, a target-negative guard, evidence and scope; commit only on dev-set gain | Analyst and skill library | TabClean (Jun 2026) | L | No licence: ideas only | The committed program is deterministic; the referee still checks it |
| S12 | **d22:** detect E-notation and 15-digit truncation and refuse to repair; recover leading zeros only when a fixed width is proven | d22 grades | Abeysooriya 2021; Microsoft docs | S | n/a | Detection: yes. Repair: only for zero-padding. |
| S13 | **d10 near-duplicates at scale:** an optional Splink or datasketch extra; keep RapidFuzz with blocking in the core | d10 | Splink 5, datasketch | M | MIT | No: always GATE or HUMAN |
| S14 | **Don't** adopt LLM-labelled learned detectors (ZeroED, ForestED) or neural column-type models in the library; at most as HUMAN-grade hints from the analyst | n/a | ZeroED, ForestED, Sherlock, DoDuo | n/a | n/a | **No** |

### S1. Scorer: add EDR, "clean cells broken", recall at fixed precision, and a debatable bucket (S)

- **What:** `bench/score.py::score_end_to_end` already computes D (dirty), C (changed) and K (ended correct). Add:
  - `broken = |(C \ D) \ K|`, clean cells the cleaner made wrong;
  - `EDR = (|D ∩ K| − broken) / |D|`, which is Ni et al.'s (#wrong→right − #right→wrong) / #initially wrong. A dirty cell changed to another wrong value counts zero, per the paper's definition.
- **Report alongside it:** per-detector **recall at precision ≥ 0.95**, in the manner of Auto-Test's F1@P=0.8.
- **Add a third truth label, `debatable`,** that counts in neither precision nor recall, as in Auto-Test's `ground_truth_debateable`. Use it for Raha cells where the label itself is doubtful.
- **Why:**
  - Repair precision and F1 can rise while the number of errors doubles (Ni et al. 2024).
  - crivo's current repair score has no right→wrong term.
  - The trust claim ("a fix that cannot prove itself is reverted") is best evidenced by `broken == 0`.
- **Risk:** low. Published numbers will move, but the change is additive. The debatable labels need a written rule so they can't be used to hide misses.
- **Det. fit:** yes. This is the scorer itself.

### S2. Dates: column-level resolution and a round-trip verifier; ban `dayfirst` on ISO columns (M)

- **What:**
  - Detect candidate explicit formats per column, following a DuckDB-style preference list.
  - Keep only the formats under which *every* non-null value parses.
  - Resolve day-first versus month-first per column: one unambiguous value (day > 12) decides; then sibling columns; then monotonic order. Otherwise GATE or HUMAN.
  - Parse ISO with `format="ISO8601"` or `isoparse`, never with `dayfirst`.
  - Never use `format="mixed"` as a fixer.
- **Verifier:** for every changed cell, `parsed.strftime(chosen_fmt) == original` (normalised for zero-padding), so the parse is invertible. A mixed-format column is fixed only when each sub-format's round-trip holds.
- **Why (measured 2026-10-23):**
  - pandas 3.0.5 and 3.1.0 turn `2025-03-04` into April 3 under `dayfirst=True`.
  - dateutil 3.0.0 gives two different field orders inside one ISO column.
  - dateparser `DATE_ORDER="DMY"` returns April 3, or `None`.
  - `format="mixed"` reads an ambiguous day-first column month-first.
- **Risk:** medium. Some columns are truly ambiguous (all days ≤ 12), and those must stay HUMAN. That's correct, not a regression ("refusing looks like rigour": pin a legitimate repair beside the refusal).
- **Det. fit:** yes.

### S3. Detector honesty: bounded silence, and statistically gated semantic-domain constraints (S + M)

- **Bounded silence (S):** when a detector reads only a sample of n rows and finds nothing, it must not report "clear". Report "no hits in n sampled rows: rate below 3/n at 95%". That is the rule of three (Hanley and Lippman-Hand, *JAMA* 1983, [record](https://wikidp.org/Q34271035)). The exact form is the Clopper-Pearson bound 1 − 0.05^(1/n).
  - DuckDB's sniffer is an example of a widely used tool that samples, 20,480 rows by default ([docs](https://duckdb.org/docs/2.0/data/csv/auto_detection.html)).
- **Function-based semantic-domain constraints (M):** for a column where at least *m* (e.g. 98%) of distinct values pass a validator (`validators.email`, `validators.url`, phonenumbers validity, ISO country or currency codes, a date format from S2), flag the remainder as d13 out-of-domain. Auto-Test's own results show the parameters matter:
  - require a Wilson lower bound above a threshold, not a raw ratio;
  - choose *m* so that columns of code-names and abbreviations don't fire (the failure that sank GPT-4 in Auto-Test).
- **Risk:** medium. Validators have false negatives (internationalized emails, for example). Fix the m-threshold from the corpus and pre-register it.
- **Det. fit:** yes. The constraint plus validator is a deterministic predicate, so the referee can re-run it after a fix.

### S4. Bench additions (S / M / M)

- **Raha `movies_1` and `tax` (S):** already in the BigDaMa repo under Apache-2.0, and crivo's adapter handles them. TabClean, ZeroED and Ni et al. all publish numbers on them, which gives crivo an external yardstick (stating the label budget).
- **Pollock (M), MIT:** score crivo's readers on the about 2,290 polluted files. Report crivo's auto-detect mode next to the paper's "configured" and "auto" rows. Keep part of it held out, because a month-old loader already sits at 9.997.
- **Clean Me If You Can (M):** fetch a 10k to 100k slice. Code MIT, truth ODbL. It is real dirt dominated by missing values, abbreviations and language variants, the regime where crivo's d07 and d17 should earn their keep. Never commit derived truth tables.
- **Process:** who writes any new *injectors* (for example BART-style constraint-aware errors) is governed by crivo's eval-author rule.
- **Risk:** low for the Raha pairs. Medium for Pollock and Clean-Me: new numbers may look worse, and that is the instrument working.

### S5. d08 mojibake via ftfy (S)

- **What:** use `ftfy.badness.is_bad(cell)` as the detector signal and `ftfy.fix_text` (or `fix_encoding` alone, for minimal change) as the fixer.
- **Verifier:** `is_bad(new)` is False, `fix_text(new) == new` (idempotent), untouched cells hash identically, and only cells with `is_bad(old)` changed.
- **Measured:** it fixed `CafÃ©`, `Ã¼ber` and smart-quote mojibake, and left `naïve` and `Café` untouched.
- **Licence:** Apache-2.0 (MIT-compatible).
- **Risk:** low. The last release is 2024-10, so it is stable but has a small maintainer base. Pin it, and keep it an optional or soft dependency if "import-light" is strict: it costs 23 ms.
- **Det. fit:** yes.

### S6. d07 case and spelling variants: deterministic key collision first (S/M)

- **What:** implement OpenRefine's fingerprint key: trim, lowercase, strip punctuation and controls, ASCII-fold with anyascii, tokenise, sort, deduplicate, join. Add the n-gram fingerprint, as in the [OpenRefine docs](https://openrefine.org/docs/technical-reference/clustering-in-depth).
- **Grades:**
  - Values that share a key form an AUTO cluster. The canonical value is the most frequent spelling, as in skrub.deduplicate.
  - Distance-based merges (RapidFuzz Levenshtein inside blocks) are GATE: a person confirms, because they are judgment calls.
  - Phonetic keys (jellyfish Metaphone) are GATE.
- **Verifier for AUTO:** every changed cell's key equals the canonical value's key, the number of distinct keys is unchanged, and the rows are unchanged.
- **Risk:** low for fingerprint. OpenRefine calls it the least false-positive-prone method. It can still wrongly merge token-reordered names such as "Smith John" and "John Smith" when they are distinct entities **[med]**. Keep it within a column, and gate on cardinality.
- **Det. fit:** fingerprint yes; kNN no.

### S7. d21 aggregate rows: arithmetic proof (M)

- **What:** a candidate total, subtotal or average row is *confirmed* only if, for at least k numeric columns, its value equals the sum or mean of a contiguous block of rows above it (or below, for header totals) within a tolerance. That is AggreCol's sum and average detection.
  - In Excel input, a formula cell (`data_type == 'f'`) whose formula is `=SUM(…)` or `=AVERAGE(…)` over the block is hard evidence.
  - Labels such as "Total" are a weak signal only.
- **Fixer:** drop the confirmed rows, or move them to a side table.
- **Verifier:** the dropped row's values are recomputable from the remaining rows, so no information is lost. The row count changes by exactly the dropped count. Per the contract that is an explicit, graded row-count change; it needs Aarmen's sign-off, because the referee currently requires the row count to hold.
- **Licence:** AggreCol and Strudel are Apache-2.0. Reimplement; the logic is about 50 lines.
- **Risk:** medium. Coincidental sums in small integer tables call for a minimum block size and agreement across several columns.
- **Det. fit:** yes. This is the strongest fit in the list.

### S8. Parse money, locale numbers and units with a residual check (M)

- **What:** for d01 numbers-as-strings, parse with price-parser (currency) and babel `parse_decimal` (locale). Accept a parse only if the *residual* is empty or whitelisted. The residual is the original minus the matched number, currency, whitespace and known thousands separators.
  - The test case: `"12k"` leaves residual `k`, so the parse is refused, or `k` is mapped explicitly ×1000 under a GATE grade.
- **d16:** use Pint to convert only between units of the same dimensionality. Refuse mixed dimensions.
  - Verifier: converting back with the inverse factor reproduces the original magnitude to 1e-9 relative.
  - Unit aliases (lbs, kgs, "in") can come from quantulum3's alias table, not its parser.
- **Risk:** medium. Locale ambiguity (`1.234` is either 1234 or 1.234) needs column-level evidence, the same approach as S2.
- **Det. fit:** yes.

### S9. Readers and structure (M/L)

- **Dialect:** CleverCSV's pattern-and-type consistency is MIT and scores 97% on its corpus. DuckDB `sniff_csv` is an optional second opinion. When they disagree, report it instead of guessing.
- **Encoding:** charset-normalizer, not chardet (licence dispute).
- **Header and preamble:**
  - DuckDB's rule: a row is a header if its types differ from the rows below.
  - Pytheas' column-coherence line classification (ideas only, no licence).
  - Strudel's line classes (Apache-2.0).
  - Excel: openpyxl `ws.tables` gives declared table ranges, and merged ranges above the first coherent row mark a title or preamble.
- **Verifier:**
  - A header choice is checked by type coherence. The column below the header has a single inferred type at ≥ 98%, and the header row fails that type.
  - Declared Excel Tables are ground truth.
  - Multi-table sheets (Mondrian or TableSense territory) stay HUMAN.
- **Risk:** medium to high. Structure inference is where silent wrong answers live, so use Pollock (S4) to measure before shipping.
- **Det. fit:** partly. Dialect and declared tables are verifiable. Heuristic header choice is GATE.

### S10. d04/d05 disguised missing values, after FAHES (M)

- **What, three tests:**
  1. A syntactic-pattern outlier: `-999`, `9999`, `N/A`, `.`, and `unknown` in a column whose pattern is otherwise numeric.
  2. A numeric density outlier at a round or extreme value.
  3. An **inlier repeated far above its expected frequency** compared with neighbouring values, as with `1900-01-01`, `0`, `99`. This is FAHES' key idea, and one most profilers miss.
- Seed the list with skrub's `CleanNullStrings` set ([docs](https://skrub-data.org/stable/reference/generated/skrub.Cleaner.html)).
- **Verifier:** the fix maps the sentinel to NA. The detector no longer fires, and no non-sentinel value changed.
- **Risk:** medium. A legitimately common value (0 sales) can look like an inlier sentinel, so grade inlier hits GATE.
- **Det. fit:** yes.

### S11. Analyst: TabClean-style guarded clauses (L)

- **What:** when the analyst writes a fix the fixers can't, require it to be a *guarded clause*:
  - a guard for which values are dirty;
  - a **target-negative** guard: which values must not be touched, enforced by checking that no value matching the column's majority pattern changes;
  - an evidence requirement and a scope;
  - a pure transformation.
- **Commit rule:** commit the clause as an admitted skill only if, on a held-out slice (or the referee's checks), it changes no clean cell. That is S1's `broken == 0`.
- **Why:** TabClean reaches about 1.00 precision on all six Raha datasets with exactly this structure, and its committed programs replay with no model.
- **Risk:** high effort. It touches the core (`loop.py`, `skills.py`, `prompts.py`), so it needs Aarmen's review, and as a `behaviour` issue it needs a pre-registered eval. TabClean has no licence: ideas only.
- **Det. fit:** the committed clause is deterministic and re-checkable. Its *authorship* is not, which is why the referee stays the gate.

### S12. d22 Excel id damage: detect and refuse (S)

- **What:**
  - **Detect:** E-notation strings or floats in an id-like column; 16-or-more-digit ids ending in zeros (Excel's 15-significant-digit truncation); mixed widths in a column that is otherwise fixed-width (eaten leading zeros); gene-like symbols turned into dates.
- **Repair:**
  - Only restore leading zeros, and only when the fixed width is proven. For example, ≥ 95% of values have width w and the short values are all exactly w − k digits.
  - Truncated digits and E-notation are **unrecoverable**, so mark them HUMAN with that reason.
- **Risk:** low.
- **Det. fit:** yes for zero-padding, since `str.zfill(w)` round-trips. Never for truncation.

### S13. d10 near-duplicates at scale (M)

- **What:** keep RapidFuzz with blocking in the core for small frames. Offer `crivo[dedup]` with Splink 5 (MIT, pandas-free core) or datasketch MinHash for large ones.
- **Grade:** always GATE or HUMAN. Deleting a near-duplicate deletes data; crivo already treats exact duplicates this way (d09).
- **Risk:** Splink pulls duckdb, pyarrow and sqlglot, so it must stay an extra.
- **Det. fit:** no. Similarity thresholds are judgment.

### S14. What not to do

- **ZeroED and ForestED:** learned detectors (LLM labels → classifier) are good research but fail crivo's rule. Their output can't be re-verified by a deterministic check, and they need a model at detection time.
- **Neural column-type models (Sherlock, Sato, DoDuo):** heavy, unmaintained, and near-zero as error detectors in Auto-Test.
- **GPL, AGPL and Elastic-licensed libraries:** Unidecode, deepchecks, Desbordante, Zingg, soda-core, Mondrian and Jenga can't be vendored. Use them only as ideas.
- **Profilers pinned to old pandas:** fg-data-profiling and dataprep can't coexist with pandas 3.
- **An LLM grader for the bench (DCA-Bench style):** it contradicts "every number we publish was measured".

---

## Sources not otherwise linked above

- Pandas 3.0 release notes: string dtype, resolution inference, NaN/NA changes ([whatsnew](https://pandas.pydata.org/docs/whatsnew/v3.0.0.html)).
- DuckDB CSV sniffer ([docs](https://duckdb.org/docs/2.0/data/csv/auto_detection.html)).
- Pollock paper: PVLDB 16(8):1870-1882, 2023 ([HPI news](https://hpi.de/naumann/news/another-paper-marked-as-reproducible-by-pvldb-reproducibility-committee.html); [DBScholar](https://rmarcus.info/dbscholar/papers/h1eaa7058596593e7)).
- CleverCSV ([PyPI](https://pypi.org/project/clevercsv)).
