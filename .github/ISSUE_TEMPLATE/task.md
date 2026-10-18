---
name: Task
about: One self-contained piece of work an agent can finish without asking questions
labels: task
---

## Type
<!-- code, behaviour, eval or experiment (AGENTS.md, "Work types"). Add the matching label. -->
code

## Goal
<!-- One or two sentences: what a user can see or do when this is done. -->

## Context
<!-- The plan stage (specs/2026-10-14-the-plan.md) or spec this serves, its inventory ids, and the docs/API-CONTRACT.md interface(s) it uses. -->

## Files
<!-- Exact files to create or edit. Anything else: ask first. Core files (loop.py, prompts.py, llm.py, card.py, skills.py, library.py, provenance.py, detect.py) mean the `core` label. -->
-

## Steps
<!-- Concrete enough that someone new to the codebase could follow them. -->
1.

## Done when
<!-- Checks anyone can run: a pytest command that passes, a CLI output, a bench line. -->
- [ ]

## Measurement
<!-- code: should the bench move, and which corpus case shows it? Or "none".
     behaviour or experiment: the hypothesis, suite and split, primary and guard metrics, arms, runs, decision rule and budget, written before the first paid call.
     Never quote eval cases here; name the suite. -->

## Out of scope
<!-- Tempting things NOT to do in this issue. -->
-
