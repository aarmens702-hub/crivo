---
name: new-task
description: Turn a rough description, or an item from the master plan, into one or more well-formed GitHub issues that an agent can finish without asking questions. Use when anyone wants to create, split or re-scope tasks, or to file a bug.
argument-hint: "[what needs doing]"
---

# Write a task issue

A good issue lets an agent finish the work alone, without needing to understand the whole system.

1. **Ground it.** Read the relevant parts of `docs/PRD.md`, `docs/ARCHITECTURE.md` and `docs/API-CONTRACT.md`, the master plan item or spec it comes from (`specs/`), and the actual files involved.
2. **Size it.** One issue is about 1 to 2 hours of work, about 300 changed lines or fewer, and touches one module. Split anything bigger into separate issues and note their order. A master plan wave is many issues, never one.
3. **Check the contract.** If the task needs an interface that isn't in `docs/API-CONTRACT.md`, stop and propose the contract addition to Aarmen first. Tasks build against contracts, never invent them.
4. **Check the core.** If the task would change `loop.py`, `prompts.py`, `llm.py`, `card.py`, `skills.py`, `library.py`, `provenance.py` or `detect.py`, it gets the `core` label, and its Steps say what the diff should be, small enough for Aarmen to review in one sitting.
5. **Fill in the template** from `.github/ISSUE_TEMPLATE/task.md`:
   - **Files** are exact paths.
   - **Steps** are concrete and name the functions and contract interfaces to use.
   - **Done when** lists runnable checks: a pytest command that passes, a CLI output, a bench line that moves or holds.
   - **Bench effect** says whether the bench should move, and which corpus case shows it.
   - **Out of scope** names the tempting extras.
6. **Show the draft** to the user. On approval, run `gh issue create --title "..." --body-file <tmp> --label task` (use `--label bug` instead for a defect found in testing, and add `--label core` when step 4 applies). Assign it only if the user names someone.
7. Report the issue URL(s).
