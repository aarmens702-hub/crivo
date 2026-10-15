Closes #

<!-- Work reaches `dev` by `/ship` (a direct push), so PRs are normally only the `dev → main` promotion that `/promote` opens. -->

## What changed
<!-- One to three bullets, user-visible first. -->

## How to see it
<!-- The command, snippet or file that shows it working. -->

## Core and contract
<!-- None, or list core files (loop.py, prompts.py, llm.py, card.py, skills.py, library.py, provenance.py, detect.py) and contract changes, with Aarmen's yes. -->
None

## Checks
- [ ] `uv run ruff check .` and `uv run pytest -q` pass locally
- [ ] Bench smoke run if detection, fixing or the bench changed (before → after in the body)
- [ ] No secrets, no raw dataset rows in any output, no stray debug code
