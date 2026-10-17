# QA script

<!-- Aarmen owns the cases and their expected results.
     /qa-pass runs every case here against `dev` through the qa-tester agent, black-box: install crivo the way a
     user would, use the library, the CLI and the MCP server, and judge only what comes out. Never read the code
     to explain a failure; report it.
     Each case: what to do, and what must be true. Expected results are exact (numbers, messages, exit codes)
     so a pass or fail is never a judgment call. Every expected value below was observed on 2026-10-14, except
     where a case says it fails today or costs money. When a result changes on purpose, update the case in the
     same commit. -->

## Setup

- **Work in a scratch folder,** never in the repo checkout. Every command below runs from `$Q/work`.
  ```bash
  Q=$(mktemp -d)/qa && mkdir -p "$Q/work/data" && cd "$Q/work"
  uv venv -q --python 3.12 ../venv
  uv pip install -q --python ../venv/bin/python "git+https://github.com/aarmens702-hub/crivo@dev"
  # or, for an unpushed tree: uv pip install -q --python ../venv/bin/python /path/to/crivo
  PY=../venv/bin/python; CRIVO=../venv/bin/crivo
  ```
- **Make the test files** once:
  ```bash
  $PY -c "
  import crivo as cv, pandas as pd
  cv.load_example().to_csv('example.csv', index=False)
  cv.load_example().to_csv('data/example.csv', index=False)
  pd.DataFrame({'id': range(1, 31), 'score': [float(i % 7) + 0.5 for i in range(30)],
                'city': ['Vancouver', 'Toronto', 'Montreal'] * 10}).to_csv('clean.csv', index=False)
  "
  printf 'not,a\n"broken' > bad.csv; : > empty.csv
  ```
- **The LIB prelude.** LIB cases run in `$PY` after:
  ```python
  import matplotlib; matplotlib.use("Agg")
  import crivo as cv, pandas as pd
  df = cv.load_example(); r = cv.diagnose(df); cleaned, s = cv.clean(df)
  ```
- **No key needed for INST, LIB, CLI, MCP and BENCH.** The analyst cases (AN) run free on the faux provider (`CRIVO_PROVIDER=faux`), which replays canned replies queued with `crivo.llm.faux_enqueue()` in the same process. Cases marked **costs money** call a real model and need a real `DEEPSEEK_API_KEY`; run them only when Aarmen asks.
- **The faux runs set `DEEPSEEK_API_KEY=unused`.** The CLI still demands that variable under faux (AN-03). The value is never sent anywhere: faux makes no network calls.
- **Known blocker on a fresh install:** until INST-04 passes, run `uv pip install -q --python ../venv/bin/python httpx` before the AN cases, and say in the report that you did.
- **Never** run `--docker` or `pytest -m docker`. Docker is not allowed on Aarmen's Mac.

## Install (INST)

| ID | Do | Pass when |
|---|---|---|
| INST-01 | The Setup install, then `ls ../venv/bin \| grep crivo` | It installs with no error, and both `crivo` and `crivo-mcp` are listed. |
| INST-02 | Save as `audit.py` and run `$PY audit.py`: `import sys; seen=[]; sys.addaudithook(lambda e, a: seen.append(e) if e.startswith(("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork")) else None); import crivo; print("events:", sorted(set(seen)) or "none")` | Prints `events: none`. Importing crivo opens no socket and starts no process. |
| INST-03 | `$CRIVO --help; echo $?` | The first line starts `usage: crivo [-h] [--auto-run]`, the flags include `--autonomy {autonomous,careful,report-only}`, and the exit code is `0`. |
| INST-04 | `$PY -c "import crivo.loop"; echo $?` on a fresh install, before any workaround | Exit code `0`, no output. **Fails today:** `ModuleNotFoundError: No module named 'httpx'`. `crivo/llm.py` imports `httpx` but crivo does not declare it, and a fresh install resolves `anthropic` 1.14, `openai` 3.31 and `mcp` 2.3, which pull `httpx2` instead. This breaks `cv.ask`, the REPL and the MCP analyst tools. |

## Library (LIB)

| ID | Do | Pass when |
|---|---|---|
| LIB-01 | `print(r)`, then `[f["disease"] for f in r.findings]` | The header is `dataframe — 60 rows × 5 columns`, then `5 fixable · 0 flagged · 20 signals clear`. Five findings in this order: `d01 numbers-as-strings [revenue]`, `d04 sentinel-missing [units]`, `d06 whitespace-damage [note]`, `d07 case-spelling-variants [region]`, `d09 duplicate-rows [whole table]`. The last lines read `checked and clean: 2-3, 5, 8, 10-19, 21-26`. The list is `[1, 4, 6, 7, 9]`. |
| LIB-02 | `[f["evidence"] for f in r.findings if "units" in f["columns"]]` | The units finding names both planted placeholders, `'N/A'` and `'-999'` (the `load_example` docstring plants both). **Fails today:** only `'N/A'` is named (`3/60 values are missing-data tokens ('N/A')`), and the three `-999` values stay in `cleaned.units`. |
| LIB-03 | `print(s)`, `len(df), len(cleaned)`, `cleaned.revenue.dtype` | `cleaned: 4 fix(es) applied, 1 left for review`, then `✓ d04 sentinel-missing [units]`, `✓ d06 whitespace-damage [note]`, `✓ d07 case-spelling-variants [region]`, `✓ d01 numbers-as-strings [revenue]`, `· d09 duplicate-rows [whole table]`. Rows stay `60, 60`. Revenue is `float64`. |
| LIB-04 | Compare `print(r)` with `s.needs_review` | A finding `clean` leaves for review is not labelled `safe to fix automatically` in the report, or its review entry carries a `reason`. **Fails today:** d09 is graded `AUTO` and printed as `safe to fix automatically`, yet `s.needs_review` is `[{'disease': 9, 'slug': 'duplicate-rows', 'columns': [], 'grade': 'AUTO'}]` with no reason (plan item `k`, Stage A). |
| LIB-05 | `x = s.samples(); len(x), [len(e["examples"]) for e in x], x[0]["examples"][0]` | `4`, `[3, 3, 3, 3]`, and `{'column': 'units', 'row': 9, 'old': 'N/A', 'new': nan}`. Each entry has the keys `disease`, `slug`, `columns`, `examples`. |
| LIB-06 | `[f["disease"] for f in df.crivo.diagnose().findings]`, then `c, s2 = df.crivo.clean(); c.shape, [a["disease"] for a in s2.applied]` | `[1, 4, 6, 7, 9]`, then `(60, 5), [4, 6, 7, 1]`. The accessor gives the same answers as the functions. |
| LIB-07 | `r.suggest()`, then `len(r.suggest(3))` | Five questions, the first `How many rows of "revenue" are affected by numbers-as-strings?` and the last `Which columns have missing values?`. Then `3`. |
| LIB-08 | For each of `csv parquet xlsx json jsonl feather`: `cv.write(df, f"example.{ext}")`, then `b = cv.read(f"example.{ext}"); b.shape, [f["disease"] for f in cv.diagnose(b).findings]` | Every format gives `(60, 5)` and `[1, 4, 6, 7, 9]`. `cv.write` returns the path. |
| LIB-09 | `df.to_csv("example.tsv", sep="\t", index=False); df.to_csv("example.csv.gz", index=False); df.to_csv("example.csv.zip", index=False); df.to_csv("semi.csv", sep=";", index=False)`, then `cv.read` each | All four read back as `(60, 5)`. The first three diagnose as `[1, 4, 6, 7, 9]`. |
| LIB-10 | `p = pd.DataFrame({"name": [f"person {i}" for i in range(30)], "email": [f"jane.doe{i}@example.com" for i in range(30)], "amount": [str(10 + i) for i in range(30)]}); rp = cv.diagnose(p); rp.pii()` | One entry: column `email`, `pii_type` `email`, `count` `30`, `sample` `'***@example.com'`, `grade` `HUMAN`. |
| LIB-11 | After LIB-10: `h = open(rp.to_html("report.html")).read(); "jane.doe" in h, [t for t in ("<script src", "<link ", "http://", "https://") if t in h]` | `False, []`. The shareable report holds no raw email and loads nothing from outside the file. |
| LIB-12 | `h = cv.compare(df, cleaned); h.lstrip()[:15], "revenue" in h` | `'<!doctype html>', True`. |
| LIB-13 | `a = pd.DataFrame({"id": [1, 2, 3, 4], "v": [10, 20, 30, 40]}); b = pd.DataFrame({"id": [2, 3, 4, 5], "v": [20, 31, 40, 50]}); x = cv.reconcile(a, b, "id"); x["counts"], x["receipt"]`, then `cv.reconcile_report(a, b, "id").lstrip()[:15]` | `{'added': 1, 'removed': 1, 'changed': 1, 'unchanged': 2, 'duplicate_keys': 0, 'null_keys': 0}, True`, then `'<!doctype html>'`. |
| LIB-14 | `d = cv.drivers(pd.DataFrame({"region": ["n", "s", "e"], "rev": [100] * 3}), pd.DataFrame({"region": ["n", "s", "e"], "rev": [150, 90, 100]}), "rev", "region"); d["delta"], [(c["category"], c["contribution"], c["share"]) for c in d["contributions"]], d["receipt"]` | `40, [('n', 50, 1.25), ('s', -10, -0.25), ('e', 0, 0.0)], True`. The contributions sum to the delta. |
| LIB-15 | `import json; nb = json.load(open(cv.export_notebook("example.csv", "analysis.ipynb"))); nb["nbformat"], len(nb["cells"])` | `4, 7`. |
| LIB-16 | `ax = r.plot(); type(ax).__name__, [t.get_text() for t in ax.get_yticklabels()]`, then `r._repr_html_()[:4], s._repr_html_()[:4]` | `'Axes', ['revenue', 'units', 'note', 'region', 'whole table']`, then `'<div', '<div'` (the notebook cards). |

## Command line (CLI)

| ID | Do | Pass when |
|---|---|---|
| CLI-01 | `$CRIVO diagnose example.csv; echo $?` | The report starts `example.csv   60 rows × 5 columns` and lists d01, d04, d06, d07 and d09. Exit `0`: the default `--fail-on GATE` ignores AUTO findings. |
| CLI-02 | `$CRIVO diagnose example.csv --fail-on AUTO >/dev/null; echo $?`, then the same with `HUMAN`, then `never` | `1`, `0`, `0`. |
| CLI-03 | `$CRIVO diagnose nope.csv; echo $?` | `could not read nope.csv: [Errno 2] No such file or directory: 'nope.csv'`, exit `2`. |
| CLI-04 | `$CRIVO diagnose bad.csv; echo $?`, then `$CRIVO diagnose empty.csv; echo $?` | `could not read bad.csv: Error tokenizing data. C error: EOF inside string starting at row 1`, exit `2`. Then `could not read empty.csv: No columns to parse from file`, exit `2`. |
| CLI-05 | `$CRIVO diagnose example.csv --json > j.json; echo $?`, then `$PY -c "import json; d=json.load(open('j.json')); print(sorted(d), [f['disease'] for f in d['findings']], {f['grade'] for f in d['findings']})"` | Exit `0`. Prints `['broken', 'clear', 'columns', 'file', 'findings', 'rows'] [1, 4, 6, 7, 9] {'AUTO'}`. |
| CLI-06 | `$CRIVO diagnose clean.csv --fail-on AUTO; echo $?` | `0 fixable  ·  0 flagged  ·  25 signals clear`, `nothing found — the file is clean.`, `checked and clean: 1-19, 21-26`, exit `0`. |

## MCP server (MCP)

Save this as `mcp_check.py` in `$Q`. It starts `crivo-mcp` over stdio the way Claude Desktop would.

```python
import asyncio, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main(tool, args, drop_keys=False):
    env = {k: v for k, v in os.environ.items()
           if not (drop_keys and k in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"))}
    env["CRIVO_MCP_ROOT"] = os.path.abspath(".")
    server = StdioServerParameters(
        command=os.path.join(os.path.dirname(sys.executable), "crivo-mcp"), env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("tools:", sorted(t.name for t in (await session.list_tools()).tools))
            res = await session.call_tool(tool, args)
            text = res.content[0].text
            try:
                body = json.loads(text)
            except ValueError:
                body = {}
            if isinstance(body, dict) and "findings" in body:
                print(tool + ": findings", [f["disease"] for f in body["findings"]])
            else:
                print(tool + ":", " ".join(text.split())[:240])

asyncio.run(main(sys.argv[1], json.loads(sys.argv[2]), drop_keys="--no-keys" in sys.argv))
```

| ID | Do | Pass when |
|---|---|---|
| MCP-01 | `$PY ../mcp_check.py diagnose_file '{"path": "example.csv"}'` | `tools: ['ask', 'clean_file', 'close_session', 'diagnose_file', 'open_data', 'why']`, exactly six. Nothing but JSON-RPC reaches stdout (the handshake would fail otherwise). |
| MCP-02 | Same output as MCP-01 | `diagnose_file: findings [1, 4, 6, 7, 9]`, with no key set. |
| MCP-03 | `$PY ../mcp_check.py diagnose_file '{"path": "/etc/hosts"}'` | `{"error": "path '/etc/hosts' is outside the directory this server may read. Move the file under it, or set CRIVO_MCP_ROOT to a root that holds it."}` |
| MCP-04 | `$PY ../mcp_check.py open_data '{"path": "example.csv"}' --no-keys` | `{ "error": "DEEPSEEK_API_KEY is not set — add it to the MCP client config env" }` |
| MCP-05 | `CRIVO_PROVIDER=openai CRIVO_BASE_URL=http://127.0.0.1:9/v1 CRIVO_MODEL=qwen3:32b $PY ../mcp_check.py open_data '{"path": "example.csv"}' --no-keys` | The error, if any, does not ask for `DEEPSEEK_API_KEY`: a local OpenAI-compatible endpoint needs only `CRIVO_BASE_URL` and `CRIVO_MODEL`, as `cv.ask` already accepts. **Fails today:** the same `DEEPSEEK_API_KEY is not set` error as MCP-04 (`mcp_server.py` `_required_key`). |

## The analyst (AN)

Save this as `faux.py` in `$Q`. It queues two canned model replies, then runs either `cv.ask` or the REPL.

```python
import os, sys
os.environ["CRIVO_PROVIDER"] = "faux"
import crivo as cv
from crivo import llm

llm.faux_enqueue(
    "<execute>\nresult = int(len(sales))\nassert result == 60\nresult\n</execute>",
    "<answer>\nThe table has 60 rows.\n\nHow this was computed: counted the rows and checked the count.\n</answer>",
)
if sys.argv[1:] == ["ask"]:
    a = cv.ask(cv.load_example(), "how many rows are there?", name="sales")
    print("TEXT:", a.text.splitlines()[0]); print("CHECKS:", a.checks)
    print("LINEAGE:", [(d["variable"], len(d["sha256"])) for d in a.lineage["datasets"]])
else:
    from crivo.__main__ import main
    sys.argv = ["crivo"]; sys.exit(main())
```

| ID | Do | Pass when |
|---|---|---|
| AN-01 | `$PY ../faux.py ask` | `TEXT: The table has 60 rows.`, `CHECKS: [{'expr': 'result == 60', 'passed': True}]`, `LINEAGE: [('sales', 64)]`. The answer carries its code, a check that ran, and the dataset's sha256. |
| AN-02 | `printf '/load data/example.csv sales\nhow many rows are there?\nr\n/why\n/skills\n/quit\n' \| DEEPSEEK_API_KEY=unused $PY ../faux.py` | The banner lists `/load <path> [name] · /clean <var>`. The cell is shown in a box before it runs, then `[r]un / re[j]ect / [s]kip:`. After `r`: `## answer card s<NN>-c001`, `The table has 60 rows.`, `- ✓ \`result == 60\``, and a lineage line for `data/example.csv`. `/why`: `✓ trusted — reachable from 1 raw file(s), checks pass throughout`. `/skills`: `the library is empty — skills are born from verified fixes`. Exit `0`. A line `· intent: intent check unavailable: RuntimeError` is expected here: faux has no reply queued for the intent check. |
| AN-03 | `printf '/quit\n' \| env -u DEEPSEEK_API_KEY $PY ../faux.py; echo $?` | The REPL starts and exits `0`: the faux provider needs no key. **Fails today:** `DEEPSEEK_API_KEY is not set — put it in .env or export it.`, exit `1` (`src/crivo/__main__.py:123` checks for a DeepSeek key unless the provider is `claude`). |
| AN-04 | `printf '/quit\n' \| env -u DEEPSEEK_API_KEY CRIVO_PROVIDER=openai CRIVO_BASE_URL=http://127.0.0.1:9/v1 CRIVO_MODEL=qwen3:32b $CRIVO; echo $?` | The REPL starts without asking for `DEEPSEEK_API_KEY` (the README's Ollama example). **Fails today:** `DEEPSEEK_API_KEY is not set — put it in .env or export it.`, exit `1`. |
| AN-05 | `W=$(mktemp -d); DEEPSEEK_API_KEY=unused CRIVO_PROVIDER=faux $CRIVO clean data/example.csv --json --workspace "$W" > clean.json 2>/dev/null; echo $?`, then `$PY -c "import json; d=json.load(open('clean.json')); print(sorted(d), [(f['disease'], f['status']) for f in d['fixes']], d['autonomy'], d['policy'], d['notices'][0].split(':')[0])"`. Then run the same clean again with the same `$W` and print `sorted(d)` | Exit `0`. Keys `['autonomy', 'file', 'fixes', 'needs_human', 'notices', 'outputs', 'policy', 'report', 'skills_admitted', 'variable']`. Fixes `[(1, 'fixed'), (4, 'fixed'), (6, 'fixed'), (7, 'fixed'), (9, 'failed')]` (d09 fails only because faux has no model reply queued), `autonomous`, `auto`, and `crivo just changed your data without asking`. stdout holds only the JSON. The notice fires once per workspace: the second run has no notice, and its keys should still include `notices` (as `[]`). **The second half fails today:** the key is left out entirely, so a script reading `d['notices']` crashes. |
| AN-06 | `DEEPSEEK_API_KEY=unused CRIVO_PROVIDER=faux $CRIVO clean data/example.csv --autonomy report-only --json 2>/dev/null`, then read `fixes` and `autonomy` | Every fix has status `aborted`, none `fixed`, and `autonomy` is `report-only`. Nothing changed. |
| AN-07 | **Costs money.** With a real `DEEPSEEK_API_KEY`: `$CRIVO`, then `/load data/example.csv sales`, ask `which region has the most revenue?`, answer `r` at each gate, then `/why` | Every cell is shown before it runs and waits at `[r]un / re[j]ect / [s]kip:`. The card has the answer, at least one `✓` check, and a lineage line for `data/example.csv`. `/why` says `✓ trusted`. The answer accounts for the re-cased region names (`north` and `NORTH` are one region). Not re-observed in this pass; shape from AN-02. |
| AN-08 | **Costs money.** Same session: `/clean sales` | The four AUTO fixes (d01, d04, d06, d07) apply without a gate, with the `crivo just changed your data without asking` notice. d09 (duplicate rows) stops at a gate or is reported; rows are never dropped unasked. The run ends with a report path. Not re-observed in this pass. |

## Benchmark (BENCH)

| ID | Do | Pass when |
|---|---|---|
| BENCH-01 | In a scratch copy of the repo, never the main checkout (the run rewrites `bench/RESULTS.md` with smoke numbers): `git clone -q --branch dev https://github.com/aarmens702-hub/crivo "$Q/clone" && cd "$Q/clone" && uv run python -m bench.run --smoke; echo $?` | Exit `0`, and the summary line reads `smoke: 29 synthetic + 0 external \| detect µF1 0.753 \| repair F1 mean 0.913 over 4 of 29 (4 of 9 fixable) \| survived mean 0.673 over 13 of 29`. A checkout with the four Raha datasets in `data/` prints `+ 4 external` with the same three numbers. A different number is a finding: say which moved and by how much. |
