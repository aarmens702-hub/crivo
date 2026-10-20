"""P0 dataset profiler: schema, per-type stats, and truncated samples — never raw dumps.

Runs inside the IPython kernel (profiles kernel-resident DataFrames), so it may
import only pandas, the stdlib and crivo.pii (itself pandas and stdlib). The
rendered markdown is what the LLM sees in place of the data itself, and what
MCP open_data returns.

Sample and top values from a PII-flagged text column are masked
(pii.mask_cell), and so is any shown str value that is PII on its own. A
column is flagged by a bounded scan of its first _PII_WINDOW non-null values.
Counts, nunique, non-null % and stats are computed on the raw values. Headers,
numeric columns and anything outside the profile are not masked here.
"""

from __future__ import annotations

import pandas as pd

from crivo import pii

_SAMPLES = 3
_VALUE_CHARS = 80
_TOP_CHARS = 30
_PII_WINDOW = 10_000


def _cell(text: str, limit: int = _VALUE_CHARS) -> str:
    """Make text safe for a one-line markdown table cell, hard-capped at limit chars."""
    text = text.replace("|", "\\|").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fmt_num(value: object) -> str:
    """Compact numeric rendering: 10, 4999.5, 1e+06."""
    return f"{float(value):g}"


def _pii_kind(series: pd.Series, nonnull: pd.Series) -> str | None:
    """The PII type of a text column, read from its first _PII_WINDOW non-null
    values by position, or None. One hit flags the column and the most common
    type wins, as in pii.scan; only str values are checked."""
    if not (
        pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
    ):
        return None
    counts: dict[str, int] = {}
    kinds: dict[str, str | None] = {}  # repeated values are typed once
    for value in nonnull.iloc[:_PII_WINDOW].tolist():
        if not isinstance(value, str):
            continue
        if value not in kinds:
            kinds[value] = pii._cell_type(value)
        kind = kinds[value]
        if kind is not None:
            counts[kind] = counts.get(kind, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else None


def _shown(value: object, kind: str | None) -> str:
    """repr of one shown value: masked as `kind` when its column is flagged,
    or as its own type when it is a str that is PII on its own."""
    if kind is None and isinstance(value, str):
        kind = pii._cell_type(value)
    return repr(pii.mask_cell(value, kind)) if kind else repr(value)


def _extras(series: pd.Series, kind: str | None) -> str:
    """Per-dtype stats for one column. Top values are masked one by one (each
    keeps its raw count)."""
    if pd.api.types.is_numeric_dtype(series.dtype):
        return (
            f"min={_fmt_num(series.min())} · median={_fmt_num(series.median())}"
            f" · max={_fmt_num(series.max())}"
        )
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return f"min={series.min()} · max={series.max()}"
    top = series.value_counts().head(3)
    if top.empty:
        return "—"
    return "top: " + " · ".join(
        f"{_cell(_shown(v, kind), _TOP_CHARS)}×{int(c)}" for v, c in top.items()
    )


def _row(col_name: object, series: pd.Series, n_rows: int) -> str:
    """Render one profile table row for a column."""
    pct = 100.0 * int(series.notna().sum()) / n_rows if n_rows else 0.0
    nonnull = series.dropna()
    kind = _pii_kind(series, nonnull)
    samples = (
        " · ".join(_cell(_shown(v, kind)) for v in nonnull.iloc[:_SAMPLES].tolist())
        or "—"
    )
    return (
        f"| {_cell(str(col_name))} | {series.dtype} | {pct:.1f}% | {series.nunique()}"
        f" | {samples} | {_extras(series, kind)} |"
    )


def _omitted(n: int) -> str:
    return f"… {n} columns omitted (char budget)"


def profile_df(df: pd.DataFrame, name: str, char_budget: int = 6000) -> str:
    """Render a deterministic markdown profile of df, capped at char_budget chars."""
    n_rows, n_cols = df.shape
    mem_mb = float(df.memory_usage(deep=True).sum()) / (1024 * 1024)
    head = [
        f"## `{name}` — {n_rows:,} rows × {n_cols:,} cols · {mem_mb:.1f} MB",
        "",
        "| column | dtype | non-null % | nunique | sample values | stats |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    rows = [_row(df.columns[i], df.iloc[:, i], n_rows) for i in range(n_cols)]
    full = "\n".join(head + rows)
    if len(full) <= char_budget:
        return full
    reserve = 1 + len(_omitted(n_cols))  # worst-case marker line + its newline
    kept: list[str] = []
    size = len("\n".join(head))
    for row in rows:
        if size + 1 + len(row) + reserve > char_budget:
            break
        kept.append(row)
        size += 1 + len(row)
    return "\n".join(head + kept + [_omitted(n_cols - len(kept))])
