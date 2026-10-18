---
name: new-task
description: Turn a rough description, or an item from the plan, into one or more well-formed GitHub issues that an agent can finish without asking questions. Use when anyone wants to create, split or re-scope tasks, or to file a bug.
argument-hint: "[what needs doing]"
---

# Write a task issue

A good issue lets an agent finish the work alone, without needing to understand the whole system.

1. **Ground it.** Read the relevant parts of `docs/PRD.md`, `docs/ARCHITECTURE.md` and `docs/API-CONTRACT.md`, the plan stage or spec it comes from (`specs/2026-10-14-the-plan.md`, whose ids `specs/2026-10-14-plan-inventory.md` defines, and the stage's WRAP spec), and the actual files involved.
2. **Size it.** One issue is about 1 to 2 hours of work, about 300 changed lines or fewer, and touches one module. Split anything bigger into separate issues and note their order. A plan stage is many issues, never one.
3. **Pick the type** (AGENTS.md, "Work types"): `code`, `behaviour`, `eval` or `experiment`. Fill the Type field and add the matching label. For `behaviour` and `experiment`, fill Measurement in full before filing: the hypothesis, suite and split, metrics, arms, runs, decision rule and budget. Never quote eval cases.
4. **Check the contract.** If the task needs an interface that isn't in `docs/API-CONTRACT.md`, stop and propose the contract addition to Aarmen first. Tasks build against contracts, never invent them.
5. **Check the core.** If the task would change `loop.py`, `prompts.py`, `llm.py`, `card.py`, `skills.py`, `library.py`, `provenance.py` or `detect.py`, it gets the `core` label, and its Steps say what the diff should be, small enough for Aarmen to review in one sitting.
6. **Fill in the template** from `.github/ISSUE_TEMPLATE/task.md`:
   - **Files** are exact paths.
   - **Steps** are concrete and name the functions and contract interfaces to use.
   - **Done when** lists runnable checks: a pytest command that passes, a CLI output, a bench line that moves or holds.
   - **Measurement** says whether the bench should move and which corpus case shows it, or, for `behaviour` and `experiment`, the pre-registered eval.
   - **Out of scope** names the tempting extras.
7. **Show the draft** to the user. On approval, run `gh issue create --title "..." --body-file <tmp> --label task --label <type>` (use `--label bug` instead of `task` for a defect found in testing, and add `--label core` when step 5 applies). Assign it only if the user names someone.
8. Report the issue URL(s).
