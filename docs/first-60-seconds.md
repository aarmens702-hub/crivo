# First 60 seconds

The shortest path to a cleaned file and an honest report of what did not get
fixed. Four steps, all copy-pasteable. Nothing before step 4 needs a model
key, a kernel, or Docker.

## 1. Install

```bash
# from source until crivo is on PyPI
uv add git+https://github.com/aarmens702-hub/crivo
```

## 2. Diagnose: the 26-check report, as a card

```python
import crivo

df = crivo.read("your_data.csv")   # csv, tsv, parquet, xlsx, json, jsonl, ...
df.crivo.diagnose()
```

In a notebook, that line is the output: a severity-coloured card, not a wall
of text. Importing crivo registers the `df.crivo` accessor on every
DataFrame, so `df.crivo.diagnose()` reads like `df.describe()`. Detection is
pure Python: no key, no kernel, no Docker.

In a script, `crivo.diagnose(df)` (or `crivo.diagnose("your_data.csv")`
straight from a path) returns the same `Report`; `print()` it for the text
version. From the command line, `crivo diagnose your_data.csv` prints the same
report in colour.

## 3. Clean: safe fixes applied, the rest reported

```python
cleaned, summary = df.crivo.clean()    # or crivo.clean(df)
summary                                # renders as a card: before/after per fix
crivo.write(cleaned, "cleaned.xlsx")   # format from the extension
```

`clean` only applies a fix it can verify by re-running the detector that found
the problem: numbers stored as text, mixed date formats, sentinel "missing"
values, stray whitespace, case variants, constant columns. Still no model.
Anything that deletes rows (duplicates, near-duplicates) or needs a judgement
call (ambiguous money conventions, contradictions, outliers) is reported, not
decided. It shows up in `summary.needs_review` instead of being silently
resolved for you.

## 4. The hard fixes: run the analyst

The findings `clean` deferred are the ones worth a second pair of eyes, human
or model. Point the analyst at the same file:

```bash
uv sync
echo 'DEEPSEEK_API_KEY=sk-...' > .env   # or CRIVO_PROVIDER=claude + ANTHROPIC_API_KEY
uv run python -m crivo
```

```
/load your_data.csv df
/clean df
```

Every fix the model writes stops at a gate: `[r]un` executes it, `re[j]ect`
sends a steering note back, `[s]kip` leaves it unfixed. Nothing
judgement-shaped gets decided without you watching. See
[the analyst](../README.md#the-analyst-with-a-model-key) for the rest of the
REPL, or the [MCP server](../README.md#mcp-server) to drive the same loop from
Claude Desktop, Claude Code, or Cursor instead of the terminal.

---

That is the whole path: a report you can trust from the first cell, a clean
pass that only claims what it verified, and an analyst for the part that needs
judgement. No API key until step 4.
