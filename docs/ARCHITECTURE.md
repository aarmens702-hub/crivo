# Architecture

crivo has two halves. The **library** (`crivo.read`, `diagnose`, `clean` and the report helpers) is plain pandas: no API key, no kernel, and no network, subprocess or Docker work on import. The **analyst** is an LLM client on the host driving an IPython kernel over a small NDJSON supervisor on stdio; the kernel is a host subprocess by default, or a `--network=none` Docker container with `--docker`. Datasets live in the kernel as variables, and the model sees schema, stats and truncated samples, never rows. Both halves keep one rule: **verify or revert.** A fix is kept only when the check that found the problem stops firing and the frame is otherwise intact; anything else is rolled back and reported.

## Stack
- Python 3.12, pandas, pyarrow, openpyxl: the data layer and every file format.
- jupyter_client + ipykernel: the kernel, driven only by `kernel/supervisor.py`.
- openai SDK (DeepSeek, any OpenAI-compatible endpoint) and anthropic SDK: the model, behind `llm.generate()`.
- mcp: the MCP server. rich: the `diagnose` terminal report. matplotlib: `Report.plot()`.
- uv, ruff, pytest, hypothesis: build, lint, tests. GitHub Actions CI on Linux and macOS.

## Modules
**Library half (keyless, no kernel)**
- `__init__.py` / `api.py`: the public surface (`crivo.__all__`): `read`, `write`, `read_sql`, `diagnose` (returns `Report`), `load_example`, and thin wrappers for the modules below.
- `accessor.py`: the `df.crivo` accessor, forwarding to `api.diagnose` and `autoclean.clean`.
- `detect.py`: the 26-disease taxonomy and its detectors (`detect_all`, `detect_one`, `detect_family`). pandas + stdlib only, so the same code also runs inside the kernel.
- `autoclean.py`: `clean(df)`. Deterministic fixers, each re-checked with `detect_one`; a fix that does not clear moves to `needs_review`. Returns `CleanSummary`.
- `checkup.py`: `crivo diagnose FILE`: load, run the signals, render with rich or as JSON.
- `readers/`: `crivo.read` dispatch. `files.py` (local formats, compression, parquet folders), `sql.py`, `remote.py` (http), `_sniff.py` (csv preambles).
- `crosscol.py`, `pii.py`, `semantic_types.py`: `Report.cross_column()`, `Report.pii()`, `Report.semantic_types()`.
- `charts.py`, `notebook.py`, `htmlreport.py`: `Report.plot()`, the inline-HTML notebook cards, and the PII section of `Report.to_html()`.
- `compare_report.py`, `rowdiff.py`, `rowdiff_report.py`, `decompose.py`, `excel_structure.py`, `notebook_export.py`: `compare`, `reconcile` and its HTML, `drivers`, `analyze_excel`, `export_notebook`.

**Analyst half**
- `__main__.py`: the CLI. `diagnose` (keyless), headless `clean`, and the REPL.
- `repl.py`, `mcp_server.py`, `query.py`: the three drivers (terminal, MCP over stdio, `crivo.ask`). They render events and answer gates; no model or kernel logic.
- `events.py`: the typed events and the `SessionLike` protocol between the loop and its drivers.
- `loop.py`: `Session`. QUERY turns (`run_turn`), CLEAN runs (`clean`, `clean_family`), gates, repair-by-observation.
- `prompts.py`: the system prompt and the tag contract the loop parses. `llm.py`: the `generate()` seam (deepseek, claude, openai, faux).
- `profile.py`: the kernel-side profiler that produces what the model sees instead of rows.
- `verify.py`: kernel cells for baseline, per-fix verification, revert, and skill admission. `diff.py`: renders a fix's consequence at the gate; a QUERY cell or a model-written fix gets no preview, because it never runs before approval (#84).
- `router.py`, `policy.py`, `plan.py`: grade routing, approval policies and the three autonomy levels, the plan-first artifact.
- `card.py`: the answer card; checks are lifted by AST from cells that ran ok (every assert in such a cell counts, including ones in branches that did not run: T25, Stage 0b). `report.py`: the per-run clean report.
- `skills.py`: SKILL.md packaging. `library.py`: the skill ledger, probation, promotion and retirement.
- `provenance.py`: the provenance DAG behind `/why`. `transcript.py`: the append-only JSONL transcript it reads.
- `snapshot.py`: namespace snapshots so verified fixes survive a kernel death. `fingerprint.py`: frame digests. `telemetry.py`: optional JSONL telemetry.
- `kernel/`: `client.py` (host side, protocol v1, env allowlist), `supervisor.py` (drives the IPython kernel), `bootstrap.py` (the kernel start cell).

**Repo**
- `tests/`: the keyless suite (`conftest.py` quarantines provider keys). `bench/`: the Proving Ground (injectors, truth, scorer, runner, `RESULTS.md`). `skills/`: admitted skill folders. The skill ledger (`skills/ledger.json`) is local and git-ignored until the Stage 2 rebuild commits it. The eval ledger (`bench/ledger.jsonl`) is append-only and written only by `bench/ledger.py`'s `append`; `scripts/check_locks.py` checks its git history in CI. `scripts/`: dataset fetchers and one-off tools. `specs/`: a design spec per phase. `docs/`: these docs. `docker/`: the sandbox image.

## Data flow
```
library:  crivo.read(path) -> readers -> DataFrame (missing tokens kept as strings)
          crivo.diagnose(df) -> detect_all -> Report {findings, clear, broken}
          crivo.clean(df) -> AUTO finding with a fixer -> FIXERS[d] -> detect_one
                          -> clear: keep | still firing or fixer error: needs_review

QUERY:    question -> Session.run_turn -> generate(prompt + profile) -> code cell
          -> GateRequest -> run / reject / skip -> kernel client -> supervisor -> kernel
          -> output or traceback is the next observation ... -> card.py lifts checks -> CardReady

CLEAN:    Session.clean(var) -> detect_all in kernel -> router.route per finding
          -> AUTO with a fixer: autoclean | else: model writes a fix -> GateRequest
          -> verify.py: detector re-run + row invariant + untouched-column hashes
          -> pass: keep, provenance node | fail: revert from baseline, back to the model
          -> verified model fix -> skill proposal -> admission gate -> library ledger
          -> report.py clean report
```

## Who works where
- **Core, Aarmen reviews.** Agents draft changes as small reviewed diffs, never landed unattended: `loop.py`, `prompts.py`, `llm.py`, `card.py` (ownership line in `specs/2026-08-09-p0-core-design.md`), `skills.py` and `library.py` (the skill lifecycle and governance, CLAUDE.md), `provenance.py` (CLAUDE.md), `detect.py` (rule 5 of `specs/2026-10-14-the-plan.md`).
- **Agent-owned:** everything else. Tests, bench, scripts, docs, Docker, kernel plumbing, readers, the drivers (`repl.py`, `mcp_server.py`, `__main__.py`, `query.py`) and the keyless capability modules.
- **The eval-author** (`.claude/agents/eval-author.md`) writes traps, injectors and corpus cases, and its read allowlist keeps it off what they test: the prompts, the loop, the referee (`verify.py`, `diff.py`), `detect.py` and `autoclean.py`.
- **Bench rule:** whoever writes corruption injectors (`bench/corrupt.py`, `bench/bases.py`) must not read `detect.py` or `autoclean.py`. The bench grades that code; an injector written from its internals grades its own exam. `.claude/hooks/guard_reads.py` (eval-author mode) enforces it on the eval-author's tools, and the reviewer still checks it, since code an agent runs can open any file.

## Shared files (change with care: other modules depend on them)
- `docs/API-CONTRACT.md` and `events.py` (the loop to driver seam).
- `detect.py`'s `SLUGS` (the taxonomy ids that bench truth, tests and skills key on) and `bench/truth.py` (the frozen truth manifest).
- `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`.

## Key decisions
- **No agent frameworks.** Raw API calls and jupyter_client; if glue is missing, write the 20 lines (CLAUDE.md, `specs/2026-08-09-p0-core-design.md`).
- **The library half is keyless** and does no network, subprocess or Docker work on import (`specs/2026-08-15-master-roadmap.md`).
- **The model never sees raw rows.** Schema, stats and truncated samples only; findings carry counts and at most 3 samples (`detect.py`, p0 spec).
- **The kernel is sandboxable, and its environment is an allowlist**, so host keys are not inherited by model-written code (`specs/2026-08-12-p4-distribution-design.md`, `kernel/client.py`).
- **`data/` originals are immutable.** Transforms write copies with lineage (CLAUDE.md, p0 spec).
- **Verify or revert.** Detector re-run, row invariant and untouched-column hashes, or the frame is restored (`specs/2026-08-11-p1-clean-mode-design.md`).
- **The detector is the verifier** (`detect_one`), so the two cannot drift (`detect.py`).
- **Skill admission is test-gated and human-gated**, with probation, promotion and retirement (`specs/2026-08-12-p2-skill-harness-design.md`).
- **Skills never breed skills.** Only a fix the model wrote can be offered as a skill; a fix a skill produced never is (`loop._skill_pass`). crivo makes no recursive model calls (p0 spec).
- **Provenance is a DAG:** a claim is trusted when it is reachable from raw bytes with passing checks on every step (`specs/2026-08-12-p3-trust-layer-design.md`).
- **Autonomy levels:** `autonomous` (default) applies AUTO findings with a deterministic fixer unattended, `careful` gates them, `report-only` changes nothing; no level decides a HUMAN finding or admits a skill. The MCP server runs `careful` explicitly (`specs/2026-09-05-autonomy-default-design.md`).
- **No capability ships ahead of the instrument that measures it.** PyPI publish is Stage 5 (decision D22), after correctness and capability (rule 1 of `specs/2026-10-14-the-plan.md`).
- **Behaviour is judged by the ledger, not by pytest.** A green suite proves the code, not what the model does, so a behaviour change is judged by a pre-registered eval whose result is an append-only row in `bench/ledger.jsonl` (AGENTS.md "Work types", `specs/2026-10-17-eval-tooling.md`).
