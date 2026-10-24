# Four deep dives, 2026-10-23: what crivo uses, and where each finding landed

Four read-only research agents, run in parallel with live web search, then a planning agent that mapped every
finding onto the Stage 0 issues. The full reports sit next to this file:

| Report | File |
|---|---|
| Data cleaning: error detection and repair research, benchmarks, libraries | `2026-10-23-data-cleaning.md` |
| Trustworthy data agents: verification, anti-hallucination, skills, evals | `2026-10-23-trustworthy-agents.md` |
| Containment, prompt-injection defence and context engineering | `2026-10-23-containment-context.md` |
| Table agents, tabular models, dataframe agents and the product landscape | `2026-10-23-table-agents-landscape.md` |
| The mapping, with every comment and issue draft in full | `2026-10-23-embed-plan.md` |

**Checked against the source by the orchestrator** (the four claims the top picks rest on):
- **TabClean** (arXiv 2606.25388, 2026-06-24): LLM reasoning compiled into reusable guarded repair programs. The precision and F1 figures quoted in the report come from the paper's body; the abstract gives no numbers.
- **VeriGraph** (arXiv 2606.16603, 2026-06-15): an evidence graph that links raw data, interpreter variables, results and claims, with an 87.61% grounding rate.
- **Ni et al., "Automatic Data Repair: Are We Ready to Deploy?"** (PVLDB 17(10), 2024): "most data repair methods exhibit negative values for the EDR metric". For example, Nadeef scores −1.80 on hospital; Baran is the exception.
- **DuckDB 2.0 LTS** (2026-10-21): agent mode cut the output a model reads by 59% on TPC-H.

Everything else is as the reports state it, with dates, links and confidence tags. Not re-checked:
- the reports' own measured runs, such as the pandas `dayfirst` result;
- ZMQ over unix sockets under Seatbelt;
- whether macOS enforces memory rlimits.

## The headline

The field has converged on crivo's bets.
- Data lives in the REPL, not the context (RLMs, TableRAG, Anthropic's code execution with MCP).
- A model in the loop is never the deciding judge: a pre-registered study found the strongest judge accepted 44% real regressions.
- Containment beats prompt-level filters, which an adaptive attacker beat at over 90%.

The open lane is **checked answers on messy, uncurated files**:
- warehouse tools verify against queries curated in advance;
- no MCP data server found returns a checked answer;
- no paper found checks every number in an agent's prose against executed output.

## Where each finding landed

**Comments on existing Stage 0 issues** (each sharpens a row; none rewrites it):

| Issue | Row | What the research adds |
|---|---|---|
| #242 | forged events | a stdin key, more repro paths, why `PR_SET_DUMPABLE` matters, count what the host drops |
| #94 | SC9 | recall at precision ≥ 0.95 beside F1 (Auto-Test) |
| #126 | SC19 | a "debatable" audit verdict; the scoring bucket is Aarmen's call |
| #175 | DH17 | pins: an early-month ISO column stays AUTO; no `dayfirst=` or `format="mixed"` anywhere |
| #133 | SC29 | more external sets: Raha `movies_1` and `tax`, CITBench, REIN-style |
| #148 | CT4 | sandbox-runtime and Codex as reference designs; settle nested user namespaces with a test |
| #149 | CT9 | a psutil watchdog (already installed) plus a cgroup `MemoryMax` on Linux |
| #112 | CT13 | detect-secrets and ported gitleaks rules; not TruffleHog (AGPL) |
| #218 | CT25 (and #219) | AgentDojo-style scoring, payload surfaces, scoring from what the sandbox denied |
| #143 | DH12 (and #145) | "below 3/n at 95%" wording for partial reads |
| #206 | RE22 | invariance checks (shuffled rows, apply-twice) |
| #209 | RE26 | a check mark only for a check that ran and held; mutation-checked asserts |
| #158 | PF15 | PROV-O names for lineage |

**New issues, filed 2026-10-23:**
- #244: score: the Error Drop Rate and clean cells broken, beside repair F1 (0a, wave 2)
- #245: traps: impossible-repair and canary cases for the referee's false-backed rate (eval)
- #246: eval: result rows carry paired per-case differences with clustered standard errors
- #247: bench: the referee graded as a classifier over labelled fixes
- #248: loop: PII-shaped values in a cell's output are masked before the model reads them (core)
- #249: reports: every HTML page crivo writes carries a policy that loads nothing remote
- #250: external: Pollock's polluted CSV files score crivo's reader

**Drafted, not filed yet** (full bodies in `2026-10-23-embed-plan.md`):
- **B2 and B3, number grounding** (a keyless matcher, and the card's verdict): waiting on Aarmen. Is it 0b wave 4 or Stage 1? And does an unmatched number make an answer "partly backed" or "not backed"?
- **B10 to B14, recall work:**
  - B10: d13 validated domains;
  - B11: d08 mojibake fixer;
  - B12: d07 variant key;
  - B13: d21 rollup arithmetic;
  - B14: their corpus shapes.
  Held for S0-D19's recall wave after SC24's split.
- **B15 to B19, Stage 1 inputs:**
  - B15: observation masking for long sessions;
  - B16: profile v2;
  - B17 and B18: intent check v2;
  - B19: datapackage sidecar.
  For the Stage 1 WRAP spec.

## Notes, not filed
- **TabClean-style guarded clauses.**
  - The target-negative guard is already enforced outside the model, by RE21's target contract, which is the stronger form.
  - The rest is input for the Stage 2b skill spec, with #244's `broken` count as its metric.
- **Positioning.** "Receipts on uncurated messy files" against "trusted queries on curated warehouses". Claim it in the README and PRD only once Stage 1's trap-suite numbers exist, and claim receipts rather than adjectives.
- **MCP outputs.** `structuredContent` and an `outputSchema`, truncation flags, JSON errors and resource links, in the style of DuckDB's agent mode. Input for Stage 1's MCP port. Pin DuckDB to a range, and never write DuckDB files as outputs.
- **The licence and do-not-use list.** Recommended as a "Key decisions" entry in `docs/ARCHITECTURE.md` if Aarmen wants it binding:
  - Don't depend on, or copy code from:
    - TabPFN 2.5 and later: non-commercial, including outputs;
    - AGPL or GPL code: TruffleHog, deepchecks, Desbordante, Zingg, Briefer, firejail, Unidecode;
    - CC-BY-SA, CC-BY-NC or Elastic-2.0 code: secrets-patterns-db, ASI, AbstentionBench, soda-core, Phoenix;
    - libraries pinned to old pandas: fg-data-profiling, dataprep, recordlinkage;
    - dormant dataframe agents: pandas-ai, Vanna, LIDA, TaskWeaver.
  - Ideas only, from repos with no licence file: TabClean, ZeroED, Auto-Test, CleanAgent, EvoDS and others.
  - Fetch, never commit, the "Clean Me If You Can" truth (ODbL).
  - Never the boundary: Pyodide, RestrictedPython, WASM or audit hooks as a sandbox; prompt-level filters as the injection defence; an LLM judge as the deciding check.

## Decisions Aarmen owes from this research
1. **Number grounding (B2, B3):** 0b wave 4 or Stage 1? Does an unmatched number make an answer partly backed or not backed?
2. **EDR (#244):** a published number, or a diagnostic?
3. **A "debatable" truth label (#126):** whether to have one, and its written rule.
4. **New dependencies** for the held fixers: ftfy, validators, phonenumbers, and optionally RapidFuzz and anyascii.
5. **Grades once proof exists:**
   - d08 goes to AUTO with a fixer;
   - d21 goes to AUTO when arithmetic confirms a total row (this deletes rows unattended);
   - d07 gets a token-sort GATE tier.
6. **#247:** the trust-weighted score's t.
7. **#248's trade-off:** bare digit runs stay unmasked.
8. **Profile v2:** does D15's privacy rule move earlier?
9. **New formats in users' repos:** the datapackage sidecar, and PROV-O names. Now, or under PF10's policy?
10. **Pollock and the CMIYC slice:** fetch-only, under D24.
