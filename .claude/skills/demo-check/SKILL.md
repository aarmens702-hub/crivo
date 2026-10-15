---
name: demo-check
description: Walk the demo story from docs/PRD.md against main exactly as a new GitHub visitor would - install from GitHub, run the README - and report anything broken. Use before showing crivo to someone, or when the user asks whether the README still works. To test dev and move it to main, use /promote instead.
---

# Demo check

1. Read "Demo story" in `docs/PRD.md`. If it's missing, ask for the steps and offer to write them into the PRD.
2. Make a fresh venv in your scratchpad and install the public `main`, the way a visitor would: `uv venv --python 3.12 <dir>/venv && uv pip install --python <dir>/venv/bin/python "git+https://github.com/aarmens702-hub/crivo@main"`. Never use the repo's own `.venv`.
3. Follow every demo step exactly as written in the PRD and the README. At each step note:
   - whether it worked
   - how long it took
   - any traceback or warning
   - any output that doesn't match what the README shows
4. Open the GitHub page itself (`gh repo view aarmens702-hub/crivo --web` is not needed; read the rendered README with `gh api repos/aarmens702-hub/crivo/readme`): every link, anchor and image path resolves.
5. The analyst half needs a real key and costs money. Walk it only if the user says so; otherwise report it as skipped.
6. Report pass or fail for each step, then the top issues ranked by how bad they'd look to a visitor. Don't fix anything unless asked. Offer to turn each issue into a `bug` GitHub issue.
