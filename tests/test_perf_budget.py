"""Arc W3/H3: the perf budget — a regression net, not a benchmark. Measured
2026-09-03 on the dev machine: detect_all over 300k transaction rows in 2.6s
with all 25 single-file signals. The bar is 5x that, so a future detector that silently
turns diagnose() quadratic fails here before it ships, while CI machine
noise never does."""

import time

from crivo.detect import detect_all


def test_detect_all_stays_inside_the_300k_row_budget():
    from bench.bases import transactions

    frame = transactions(7, 300_000)
    started = time.monotonic()
    result = detect_all(frame)
    elapsed = time.monotonic() - started
    assert result["broken"] == {}, "a crashed signal is not a fast signal"
    assert elapsed < 15.0, f"detect_all took {elapsed:.1f}s on 300k rows"


def test_profile_df_stays_inside_the_300k_row_budget():
    """Regression for #114. profile_df now scans each text column for PII
    before it renders samples, bounded to the first 10,000 non-null values.
    Measured 2026-10-19 on the dev machine, over the same 300k transaction
    rows:
    - profile_df before the scan, idle: 0.10s (0.09s to 0.13s, three cold runs)
    - profile_df before the scan, under load (load average 9): up to 0.31s
    - a bounded-scan profile_df (a test-writer's scratch version), idle: 0.16s
    - pii.scan, which reads every row uncached, idle: 2.2s
    - an unbounded scan with a per-distinct-value cache, under load: 1.57s
    The bar is 1.0s, not 5x (0.5s), because the load figures show 0.5s would
    flake. It catches a gross regression, a profile many times slower than
    the bounded one; it does not pin the window, since the cached unbounded
    scan could pass it on an idle machine. The 10,000-value window is pinned
    by test_profile.py's
    test_the_pii_scan_reads_the_first_10000_non_null_values[past-the-window]."""
    from bench.bases import transactions
    from crivo.profile import profile_df

    frame = transactions(7, 300_000)
    started = time.monotonic()
    out = profile_df(frame, "transactions")
    elapsed = time.monotonic() - started
    assert "300,000 rows" in out, "an empty profile is not a fast profile"
    assert elapsed < 1.0, f"profile_df took {elapsed:.2f}s on 300k rows"
