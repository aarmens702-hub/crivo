# Embedding the 2026-10-23 research: where each finding goes

Planner's draft, 2026-10-23. Read-only: no repo file edited, no issue created or commented, no paid call, no `.env` read.

**Inputs actually used.**
- The four reports in `scratchpad/research/` (data cleaning, trustworthy agents, containment and context, table agents and the landscape).
- `specs/2026-10-17-stage-0-foundation.md` (its tables carry every row id with its issue number) and `specs/2026-10-14-the-plan.md`.
- **`plan/stage0-manifest.json` and `plan/file_log.txt` were not at the stated paths** (`scratchpad/plan/` holds only `merge/__pycache__`, and a search of the scratchpad found neither). Every mapping below was checked against the live issue body and its comments instead (`gh issue view`, read-only), dumped to `scratchpad/research/targets/<n>.md`.
- Code read where a comment cites it (`autoclean.py`, `detect.py`, `loop.py`, `kernel/bootstrap.py`, `bench/eval.py`, `bench/ledger.py`, `uv.lock`), so the comments don't ask a row to add what the code already does.

**Things found while checking that change the drafts.**
- **#242 already carries the forged-event comment** (2026-10-23: DEVNULL, per-session HMAC with a sequence number, `PR_SET_DUMPABLE`). Finding 1 needs at most a short addendum.
- **#243** ("docs: the 2026-10-23 research deep dives and their summary") is open and claimed. Its summary file must link every issue a finding lands in, so the final numbers from this plan go there. The (C) notes below are written to go into that summary.
- **The date fixer already does most of finding 3.** `autoclean._fix_dates` uses one explicit format per family, `ISO8601` for ISO, refuses day/month ambiguity, and never passes `dayfirst` or `format="mixed"`. The comment on #175 adds pins, not a redesign.
- **d21 already corroborates a single labelled total row arithmetically** (`detect.py:~1929`). The new part is block sums, averages, several columns and Excel formulas.
- **psutil is already installed** as an ipykernel dependency (`uv.lock`), so CT9's watchdog can use it without a new dependency. ftfy, validators, phonenumbers, RapidFuzz and anyascii are not in the lock.
- **The plan and the Stage 0 spec disagree on answer grounding.** The plan's 0b list says "Collateral, idempotency, replay, grounding". The spec's cut list moves answer grounding to Stage 1 because it "needs Stage 1's answer()". A deterministic number match needs only the turn's outputs. That is an owner decision (below).
- **CT4 (#148) may have a hole as written.** Its bwrap argv (`--unshare-all`) does not stop a cell from creating a nested user namespace. srt's README says that undoes deny binds such as the `/dev/null` over `.env`. Linux's mount-namespace rules lock inherited mounts, which may stop it, so the comment asks for `--disable-userns` and a test, not an assumption either way.

---

## 1. Mapping table

Routes: **A** = a comment on an open issue, **B** = a new issue (drafts in section 3, numbered B1 to B19), **C** = not filed now; a note for the #243 summary.

| # | Finding | Route | Target | Why |
|---|---|---|---|---|
| 1 | Forged protocol events: stdout to DEVNULL, HMAC, `PR_SET_DUMPABLE` | A | #242 (bug, kernel) | The fix is #242's. Its 2026-10-23 comment already has the three steps; the addendum adds key delivery on stdin, two more repro paths, and the docker path. Optional. |
| 2 | Scorer: Error Drop Rate and clean cells broken | B | B1 (new, 0a) | No row has a right-to-wrong term. DH1 (#106)'s `collateral` (C minus D) counts representation-only changes too, so it is not `broken`. |
| 2 | Scorer: recall at precision 0.95 | A | #94 (SC9) | One derived column on SC9's per-detector table. |
| 2 | Scorer: a "debatable" truth label | A | #126 (SC19) | The audit is where a label would be found debatable. Whether the scorer gets the bucket is Aarmen's: it moves published numbers, and the Raha-marker question was settled 2026-09-02. |
| 3 | Dates: per-column format, no `dayfirst` on ISO, round-trip, no `format="mixed"` | A | #175 (DH17) | The fixer already follows the research. The comment adds two pins. The round-trip check and the sibling-column tie-break go to RE21 (#205)'s contract and to the recall wave. |
| 4 | Number check on every answer card (VeriGraph) | B | B2 (matcher, not core), B3 (verdict and card, core) | No row checks numbers in prose. Whether this lands in 0b wave 4 or Stage 1 is Aarmen's (the plan and the spec disagree). |
| 5 | Impossible-question and canary traps; trust-weighted score | B | B4 (eval: impossible-repair and canary cases for the referee); the score goes in B6 | No row gives the referee cases whose right outcome is a refusal. Impossible *questions* are already in the plan's Stage 1 gate list, so B4 covers fixes only. Choosing t is Aarmen's. |
| 6 | Fixers: ftfy for d08; fingerprint key for d07's AUTO tier with RapidFuzz as GATE; AggreCol plus `=SUM(` for d21 | B (hold) | B11 (d08), B12 (d07), B13 (d21), with B14 (eval: corpus shapes) first | Capability work, not honesty. S0-D19's precedent is that recall waits for SC24 (#187)'s split. New dependencies and grades are Aarmen's. Drafted so they can be filed when he says. |
| 7 | Bench: Raha movies_1 and tax; Clean Me If You Can slice | A | #133 (SC29) | SC29 builds the external-set registry and names a sibling corpus. movies_1 and tax are the same Raha adapter. CMIYC fits D24 only as fetch-never-commit (ODbL). |
| 7 | Bench: Pollock for the readers | B | B9 (new, 0d platform) | No row measures the reader. PF20 (#163) changes the reader with no instrument for it. |
| 8 | OS sandbox after srt and Codex; macOS ZMQ over unix sockets | A | #148 (CT4) | CT4 has the design. The comment adds nested-userns blocking, `--cap-drop ALL`, `--clearenv`, Codex's sysctl list, and attribution. The macOS IPC "spike" is already done: CT3 (#147) records `KernelManager(transport="ipc")` working with all IP denied on macOS 15.5. No comment is needed on #147. |
| 9 | Mask cell observations, not just the profile; a masked `peek` | B | B7 (core) | CT16 (#114, closed) masked the profile only. Its own comment says cell output still reaches the model raw. The `peek` helper is the plan's Stage 1 `Session.peek` (a prompt change), so it is out of B7's scope. |
| 10 | Observation masking for long sessions (arXiv 2508.21433) | B | B15 (behaviour, core, Stage 1) | PF8 (#116) wires overflow to the existing compaction and says the compaction method is Stage 1's. This is a candidate for that method. It needs an eval. |
| 11 | Host replay | none | RE23 (#207) | Already covered: a clean is replayed in a fresh kernel. Replay for answers is Stage 1. |
| 11 | Invariance (metamorphic) checks | A | #206 (RE22) | The same scratch-copy machinery can run a shuffled-row check. Offered as a sibling row, since its failure text falls under S0-D14's eval. |
| 11 | Mutation-checked asserts | A | #209 (RE26) | RE26 makes "passed" mean ran-and-held. "Could have failed" is the next step. It needs host values and runs model assert code on copies, so it is recorded for Stage 1's answer checks. |
| 12 | Referee graded as a classifier; clustered SEs; paired arms; conformal bound; signal-to-noise | B | B5 (eval statistics on result rows), B6 (the referee scored on labelled fixes) | The eval tooling (EV1 to EV20) has Wilson intervals and an A/A floor, but no paired or clustered errors, no discrimination measure and no SNR flag. A conformal bound is not built: D19's Wilson bound is already finite-sample, and conformal only matters for a thresholded score. |
| 13 | Profile v2 (DataGovBench) | B | B16 (behaviour, Stage 1) | No row changes the profile's samples. It changes what the model reads, so it needs an eval. |
| 14 | Intent check v2: postconditions from the question alone, run by the host | B | B17 (code: the host evaluator), B18 (behaviour, core: the call) | RE6 (#102) only fixes "no verdict read as a match". This is Stage 1 and touches D10 (the second path). Split so the harness half is tested without a model. |
| 15 | TabClean-style guarded repair clauses | C | #243 summary, for the Stage 2b spec | The target-negative guard is already enforced outside the model by RE21 (#205)'s target contract (S0-D9). The rest is skill design (Stage 2b), is behaviour, and spans `loop.py`, `skills.py` and `prompts.py` at well over 300 lines. TabClean has no licence: ideas only. |
| 16 | Positioning: receipts on messy files compared with trusted queries; a public trap suite | C | #243 summary, then README and PRD after Stage 1's numbers | Copy follows measurement (AGENTS.md). The public trap suite is already the Stage 1 gate. |
| 17 | Outputs: a `datapackage.json` sidecar | B | B19 (Stage 1 by default) | A new file format in users' repos (rule 8), so Aarmen decides when. |
| 17 | Outputs: PROV-O lineage names | A | #158 (PF15) | PF15 gives the lineage file its first `schema_version`. Renaming keys is cheapest before readers exist. A format and contract call for Aarmen. |
| 17 | Outputs: MCP `structuredContent`; DuckDB agent-mode output | C | #243 summary, for the Stage 1 spec | Already in the plan's Stage 1: MCP on the 2026-07-28 spec with structured findings and errors, and the toolbox's bounded result payload. Filing now would front-run that spec. |
| 18 | Secrets: detect-secrets or ported gitleaks rules, not TruffleHog | A | #112 (CT13) | CT13 owns the pattern list. The comment adds encoded forms of the host's values, a licence-clean source for more shapes, and a redaction count. |
| 19 | Memory: psutil watchdog; cgroup `MemoryMax` on Linux; macOS rlimits | A | #149 (CT9) | CT9 already checked that macOS refuses rlimits. The comment adds the RSS-versus-footprint caveat, psutil being already installed, and the cgroup follow-up. |
| 20 | Injection traps: AgentDojo scoring, carriers, sandbox denials as oracles | A | #218 (CT25), covering #219 (CT26) | CT25's grader already has the canary listener, egress scan and hashes. The comment adds utility-under-attack, integrity and persistence goals, two carrier classes, adaptive variants, and denial logs. No payload text. |
| 20 | A CSP on HTML reports | B | B8 (new, 0d) | No row covers output channels. The three HTML writers escape text but set no policy. |
| 21 | "Below 3/n at 95%" wording for partial reads | A | #143 (DH12), covering #145 (DH14) | The bound is valid only for a random sample. The capped scans read a prefix or a budget, so the reason should name what was not read. |
| 21 | Validator-based d13 (Auto-Test) | B (hold) | B10 | A new detection branch with new dependencies. Recall work, so it goes after SC24 per S0-D19. |
| 22 | Licence and do-not-use list | C | #243 summary; optionally a "Key decisions" line in `docs/ARCHITECTURE.md` if Aarmen wants it binding | Docs only. |

**Counts:** 13 comments (A), 19 new issue drafts (B1 to B19), 4 notes (C).

**Where the new issues sit:**
- **Startable in Stage 0:** B1 (0a, wave 2), B5 (eval follow-up, wave 1 or 2), B7 (0d, wave 2, core), B8 (0d, wave 2), B9 (0d platform, wave 2), B4 (Loop 1 and 0b, wave 4), B6 (Loop 1, wave 5).
- **0b wave 4 or Stage 1, Aarmen's call:** B2, B3.
- **Hold until after SC24 (#187), per S0-D19:** B10 to B14.
- **Stage 1:** B15, B16, B17, B18, B19.

---

## 2. (A) Comments, in full

Each is ready for `gh issue comment <n> --body-file`. None quotes a case or payload.

### A1. #242: kernel: check whether a cell can forge a protocol event the host accepts (finding 1)

Optional: the 2026-10-23 comment on this issue already gives the fix. Post this only if the extra detail is wanted.

````markdown
Addendum to the comment above, from the same 2026-10-23 containment report (§2.2, §2.3), for the fix step:

- **Send the per-session key as the first stdin line**, not in argv or env. argv is world-readable through `/proc/<pid>/cmdline`, and the kernel inherits the env.
- **Cover two more repro paths in step 1:** a write from a background thread, and a child process (`os.system` of an `echo`). ipykernel forwards fd-level output from both.
- **Why `PR_SET_DUMPABLE` matters:** a same-uid process can open `/proc/<pid>/fd/N` of a dumpable process (ptrace(2)'s access-mode rule, which Yama's `ptrace_scope=1` does not restrict). So moving the protocol to a private fd is not enough on Linux by itself.
- **Count what the host drops** (bad MAC, out-of-order `seq`) in the session log as a number, so an attempt is visible.
- **With the kernel's stdout at DEVNULL,** fd-level output still reaches IOPub, so the model sees the same output. The docker transport gets the same change inside the container.

Unchanged: verdicts the kernel prints about itself are a second class. No transport fix closes them; that is RE11 to RE13 and the strict xfails of 4835b24.
````

### A2. #94: bench: per-detector precision, recall and F1 over the whole corpus (SC9; finding 2)

````markdown
From the 2026-10-23 data-cleaning deep dive (S1). Auto-Test (Chen, He et al., SIGMOD 2025, arXiv 2504.10762) reports F1 at a fixed precision rather than F1 alone.

Consider one more column in step 2's table: **recall at precision 0.95**. That is the pooled recall when the detector's pooled precision is at least 0.95, and "below 0.95" otherwise.

- crivo's findings are binary, so this reads the counts this row already pools. It is not a threshold sweep.
- It says how much a detector finds while it is precise enough to trust, which F1 hides.
- The 0.95 is a reporting line, not a gate. It goes in `bench/SCORING.md` with SC10 (#119)'s rule.

No change to the pooling rule or the small-row mark.
````

### A3. #126: audit: crivo's truth labels checked by someone who did not write them (SC19; finding 2)

````markdown
From the 2026-10-23 data-cleaning deep dive (S1, and the benchmark caveat in §2). Auto-Test's benchmarks (arXiv 2504.10762) carry a `ground_truth_debateable` label that counts in neither precision nor recall. Its manual check found that classic benchmark labels miss real errors: precision went from 95% strict to 97% against augmented truth.

For step 1: if the audit meets a label it cannot call right, incomplete or wrong from the taxonomy, record a fourth verdict, **debatable**, with its one-line reason.

Don't create a scoring bucket here. Two things are Aarmen's:
- whether the scorer gets a debatable class at all (it moves published numbers);
- the written rule for what may go in it, fixed before any score is seen, so it can't be used to hide misses.

It would apply to crivo's own planted labels. The Raha missing-marker question stays as decided on 2026-09-02 (the Stage 0 spec's cut list) unless he reopens it.
````

### A4. #175: detect: d02 says how many values match, and is GATE for times, epochs and ambiguous day/month (DH17; finding 3)

````markdown
From the 2026-10-23 data-cleaning deep dive (§1.9 and S2), measured on pandas 3.0.5, crivo's pin:
- `pd.to_datetime(["2025-03-04"], dayfirst=True)` returns April 3;
- dateutil 3.0.0 `parse(..., dayfirst=True)` gives two different field orders inside one ISO column;
- `format="mixed"` reads an ambiguous day-first column month-first wherever it can.

`_fix_dates` already avoids all three: one explicit format per family, `ISO8601` for ISO, and a refusal on ambiguity. So this row's direction holds. Two pins to consider for step 3. Neither adds scope:

1. **An ISO column whose days are all 12 or under stays AUTO and is fixed.** `_slot_ambiguity`'s regex needs one or two leading digits, so a four-digit year never reads as ambiguous today. Pin it, so a later change to that regex can't send every early-month ISO column to a gate.
2. **No date path passes `dayfirst=` or `format="mixed"`.** A source grep over `detect.py` and `autoclean.py` in a test is enough.

For later, outside this row:
- **A per-cell round-trip check:** `parsed.strftime(fmt) == original`, with zero-padding normalised. It could be d02's "same instant" comparison in RE21 (#205)'s target contract (S0-D9).
- **Evidence for the new GATE:** a sibling column or monotonic sort order that would settle day/month, offered to the person at the gate. That is a recall change, so it waits for SC24 (#187) (S0-D19).
````

### A5. #133: external: CITBench cleaning instances and one REIN-style set scored beside Raha (SC29; finding 7)

````markdown
From the 2026-10-23 data-cleaning deep dive (§2 and S4). Two candidates for the registry this row builds:

**Raha `movies_1` and `tax` (small effort).**
- BigDaMa/raha (Apache-2.0) ships seven sets; `scripts/fetch_raha.py` and `bench/run.py`'s `EXTERNAL` take four.
- movies_1 and tax are the same pair format, so they can be the first new `EXTERNAL_SETS` entries in step 1, with pinned hashes as the four have.
- TabClean (arXiv 2606.25388), ZeroED (2504.05345) and Ni et al. (PVLDB 17(10), 2024) all publish numbers on them, which gives crivo an outside yardstick.
- Any comparison must state the label budget: ZeroED shows Raha's own F1 changes completely with it.
- tax is about 200k rows. It belongs in `--full`, not smoke, so smoke keeps its time budget.

**"Clean Me If You Can" for step 3's sibling corpus.**
- Ahmadi et al., arXiv 2606.31983, 2026-06-30; repo D2IP-TUB/Clean-Me-If-You-Can.
- Real dirt with cell-level truth: 4.34M web postal addresses scored against geocoded OpenStreetMap truth.
- Licences: the code is MIT, the ground truth is ODbL 1.0 (share-alike), and the dirty data is under Common Crawl terms. Under D24 that means fetch, never commit, publish scores only, and never commit a derived table.
- Fix the slice before the first score: a seeded sample of N rows, with N and the seed in the fetch script. Raha ran out of memory above 100k rows on it.

The selection rule in Context stands: every instance with cell-level truth, chosen before scores are seen.
````

### A6. #148: kernel: one module builds the macOS and Linux sandboxes and says when neither can run (CT4; finding 8)

````markdown
From the 2026-10-23 containment deep dive (§1.2, §1.3, §1.4). Sources: Anthropic's sandbox-runtime README (Apache-2.0, v0.0.81) and OpenAI Codex's linux-sandbox README and `seatbelt_base_policy.sbpl` (Apache-2.0). Both converge on this row's design: Seatbelt on macOS, bubblewrap plus seccomp on Linux.

Three things to consider for steps 3, 4 and the tests:

1. **Nested user namespaces and the deny binds.**
   - srt's README: creating a user namespace "takes no capability and gives its creator a full capability set over a private copy of the mount tree, from which the binds can be removed".
   - With `--unshare-all`, a cell can create one. Linux locks mounts inherited into a less privileged namespace (mount_namespaces(7)), which may stop it unmounting step 4's `--ro-bind /dev/null <.env>`. Don't assume either way.
   - Fix: add `--unshare-user --disable-userns` (bubblewrap 0.8+; Ubuntu 24.04 ships 0.9). Or add a seccomp filter on `unshare` and `clone` with the user-namespace flag, `setns`, `mount`, `umount2` and `pivot_root`, as srt and Codex do. Nested user namespaces are also a large kernel attack surface on their own.
   - Test: a contained cell that tries `os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)` fails, and the `.env` read still fails after it.
2. **Also pass `--cap-drop ALL` and `--clearenv`.** The env comes from `kernel_env` (step 7). Codex's seccomp also blocks `io_uring` and `AF_VSOCK`.
3. **macOS `sysctl-read`.** Codex's base policy (`(deny default)`, "inspired by Chrome's sandbox policy") allows a named list of `sysctl-read` names Python needs, narrower than step 3's blanket rule. A deny-default profile that misses one fails at start (zsh 5.9 reads `hw.*`), so step 6's probe should cover it. If profile text is ported, keep the Apache-2.0 attribution and NOTICE.

Unchanged:
- No proxy: crivo needs no egress, which also removes srt's domain-fronting limit.
- Fail closed (CT7 (#194), CT8 (#215)). Claude Code's own use of srt is fail-open by default, the opposite.
````

### A7. #149: kernel: a memory limit stops a runaway cell instead of the machine (CT9; finding 19)

````markdown
From the 2026-10-23 containment deep dive (§1.7). The design matches the report: a host-side watchdog, because macOS ignores memory rlimits, which this row already checked on macOS 15.5. Three things to consider:

1. **RSS undercounts on macOS.**
   - macOS compresses memory, so RSS can read well below what the OS charges a process. `phys_footprint` (from `proc_pid_rusage`; what Activity Monitor's Memory column shows) is closer.
   - If the 1 GiB test is steady on RSS, keep RSS. If it is flaky, read the footprint.
2. **psutil is already installed** as an ipykernel dependency (see `uv.lock`; BSD-3). It could replace the `ps` call without a new dependency. It does not expose `phys_footprint` on macOS directly (that needs ctypes).
3. **Linux can have a hard cap later.**
   - `systemd-run --user --scope -p MemoryMax=<N> -p MemorySwapMax=0` gives a cgroup v2 limit with no polling race, where a user systemd exists.
   - Cgroups stay out of scope here, as written. Worth a follow-up row once CT5 (#190) settles the Linux launch.
   - Avoid `RLIMIT_AS` on Linux: numpy and pyarrow reserve large virtual ranges and trip it early.

None of srt, bubblewrap or Seatbelt limits memory, so this watchdog is needed on every backend.
````

### A8. #112: secrets: one redaction helper covers everything that leaves the kernel and the transcript (CT13; finding 18)

````markdown
From the 2026-10-23 containment deep dive (§4; ranked item 5). Three additions to consider for steps 1 and 2. All stay within S0-D22 (exact values plus prefix-anchored shapes, no entropy):

1. **Encoded forms of the host's own values.**
   - Also mask each `host_secret_values()` entry in base64 (standard and URL-safe, with and without padding) and URL-encoded form. A cell that prints `base64.b64encode(key)` gets past an exact-value match today.
   - GitHub Actions masks secrets this way and still warns "this redaction is not guaranteed". The contract line should say the same.
2. **Where more shapes come from, if wanted.**
   - Port a curated subset of gitleaks' rules (MIT; its README says the project is feature-complete with security patches only; its successor betterleaks is also MIT) into Python `re`, with attribution in the module.
   - Do not copy from TruffleHog (AGPL-3.0) or secrets-patterns-db (CC-BY-SA-4.0).
   - Yelp's detect-secrets (Apache-2.0, last release 2024-05-06) fits only as an optional extra.
   - Every added shape keeps the "a 64-character hex digest, a UUID and a column name are unchanged" test.
3. **Count the redactions** in the session log: a number, never the value. Then a run that redacted something is visible.
````

### A9. #218: traps: injection cases, part 1: instructions in cell values and column names (CT25; finding 20)

````markdown
From the 2026-10-23 containment deep dive (§3, ranked item 6). Sources:
- AgentDojo, arXiv 2406.13352;
- "The Attacker Moves Second", arXiv 2510.09023;
- Agent Data Injection, arXiv 2607.05120;
- PromptArmor's CellShock report on Claude for Excel, Nov 2025.

For the eval-author. This names classes only, with no case or payload text. Things to consider for steps 1 and 3; part 2 (#219) can use the same list for its vectors.

1. **Score it the AgentDojo way.** Report two numbers separately: utility under attack (the answer still matches the clean twin, which step 3 checks) and targeted attack success. Then a crivo that refuses everything doesn't read as safe. Step 4's no-op already fails; put both numbers in the result.
2. **Goals beyond exfiltration.**
   - Integrity: a result called checked that wasn't, a suppressed finding, a changed fix.
   - Persistence: text carried into a skill.
   - The grader reads these from what the referee and the skill ledger recorded, not from what the model says.
3. **Two carrier classes the literature says get past defences:**
   - data shaped like crivo's own trusted output (a finding, a receipt, a tool frame);
   - text a person can't see but the model reads (Unicode tag characters, zero-width and bidi controls).
4. **Static cases overstate robustness.** Adaptive attacks beat every prompt-level defence tested at over 90%. If the budget allows, add a small adaptive variant to held-out (a case rewritten after a failed attempt). Otherwise say plainly in the result that the suite is static.
5. **Score from what the sandbox denied.** Seatbelt and bubblewrap denials, the canary listener and the referee-input hashes are oracles the model cannot talk past. Where the backend logs a denial, count it beside the listener hits.

Unchanged: no prompt changes (Stage 1), and the gate rule (every count 0).
````

### A10. #143: detect: a check that read part of the data says so, instead of being listed clear (DH12; finding 21)

````markdown
From the 2026-10-23 data-cleaning deep dive (S3; the rule of three, Hanley and Lippman-Hand, JAMA 1983). For step 2's reason text, and for DH14 (#145)'s three reasons.

A check that read n rows and found nothing may say "no hits in n rows: rate below 3/n at 95%" **only when those n rows were a uniform random sample**. The exact form is 1 − 0.05^(1/n).

d12's pair budget, d07's `MAX_FUZZY_VALUES` and d24's first 50,000 rows are not random samples. For them, the honest reason names what was not read, with no rate, for example "12 of 34 candidate columns compared; the rest not checked".

If a detector ever moves to a seeded random sample, the bound becomes valid. No code change to this row beyond the wording.
````

### A11. #206: referee: a fix applied twice must equal the fix applied once (RE22; finding 11)

````markdown
From the 2026-10-23 trustworthy-agents deep dive (§2.1, ranked item 5). Sources: ArrivalBench, arXiv 2610.02363 (single-run grading certified pipelines that replay showed silently wrong); pre-action verification, arXiv 2609.11957 (anchor checks to content, not position).

Consider a **sibling check on the scratch-copy machinery this row builds**: run the fix on a seeded row permutation of `before`, undo the permutation, and compare with `after`.
- A fix that keys on row position (an `iloc` slice, a "first N rows" rule) passes idempotency and fails this.
- Exempt the row diseases whose keep rule is positional (d09's keep-first, d10, d21, d24), or compare them content-sorted, as SC5 (#91) does for `clean()`.
- SC5's probe found `clean()` order-independent on all 31 smoke cases, so crivo's own fixers should pass on landing. The check bites on model and skill fixes.

This is outside this row as written. If wanted, it is a sibling row after RE22 with its failure text fixed in the issue. That text reaches the model in a fix turn, so it falls under S0-D14's eval (RE33 (#231)).
````

### A12. #209: card: a check is stamped passed only when it ran and held (RE26; finding 11)

````markdown
From the 2026-10-23 trustworthy-agents deep dive (§2.7, ranked item 6). Sources: Meta's ACH, arXiv 2501.12862 (keep tests that kill mutants); reports of vacuous LLM-written assertions.

This row makes "passed" mean "ran and held". The next step up is "could have failed": an assert such as `assert len(df) > 0` runs, holds, and guards nothing.

A mutation check would:
- re-run each assert on 2 to 4 mutated copies of what it guards (the value just past its tolerance, one row dropped or duplicated, a sibling column);
- show "guards nothing" when no mutant fails it.

It needs the host to hold the values (RE9 (#140)) and runs model-written assert code on copies. So it belongs with Stage 1's answer checks, not here. Leave this row as written; this records the idea for the Stage 1 spec. Equivalent mutants are the known false alarm (ACH needed a pre-processing step before its detector worked).
````

### A13. #158: loop: lineage and family summaries are written atomically and versioned (PF15; finding 17)

````markdown
From the 2026-10-23 table-agents landscape deep dive (§5). Croissant 1.1 adds W3C PROV-O provenance down to field level; PROV-AGENT (arXiv 2508.02866) extends W3C PROV to agent prompts and decisions.

This row gives the lineage file its first `schema_version`. If its keys are ever renamed to PROV-O terms, that is cheapest before version 1 has readers. The terms:
- entity: a file or frame;
- activity: a fix or a cell;
- agent: crivo or the model;
- relations: `wasDerivedFrom`, `wasGeneratedBy`.

Then Croissant and PROV tools can read crivo's lineage directly.

It is a format and contract change, so it is Aarmen's call: either a separate row before this one lands, or version 2 later under PF10 (#153)'s policy. This row stays as written.
````

---

## 3. (B) New issues, in full

Every body is ready for `gh issue create --title "<title>" --body-file <file> --label task --label <type> [--label core]`. B-numbers are placeholders. Replace each "B<n>" cross-reference with the filed issue number before filing the later ones.

### B1. score: the Error Drop Rate and clean cells broken, beside repair F1

- **Labels:** task, code
- **Placement:** Stage 0, 0a, wave 2 (after SC1 and SC10)
- **depends_on:** SC1 (#86), SC10 (#119)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-data-cleaning.md`, §1.2 and S1.

## Type
code

## Goal
Every repair score the bench prints carries two more numbers: how many clean cells the cleaner made wrong (`broken`), and the Error Drop Rate. A cleaner that repairs some dirt while breaking more clean cells then reads as making the data worse.

## Context
- **The paper:** Ni, Miao et al., "Automatic Data Repair: Are We Ready to Deploy?" (PVLDB 17(10), 2024, arXiv 2310.00711) ran 12 repair algorithms on hospital, flights, beers, rayyan and tax.
  - Most had a negative Error Drop Rate: they turned more correct cells wrong than wrong cells right.
  - The paper shows a cleaner with precision 0.8 and recall 1.0 that doubles the number of errors.
- **The metric:** EDR = (#wrong to right − #right to wrong) / #initially wrong. A dirty cell changed to another wrong value counts zero.
- **What exists:** `bench/score.py::score_end_to_end` builds D (dirty), C (changed) and K (ended correct). Repair precision, recall and F1 have no right-to-wrong term.
- **Why DH1 isn't enough:** DH1 (#106) adds `collateral` (C minus D) per fix. `broken` is narrower: changed clean cells that no longer equal the truth. A representation-only change (a numeric string turned into its number) is collateral but not broken.
- **Why it matters:** the trust claim, "a fix that cannot prove itself is reverted", is best evidenced by `broken == 0`.
- Scorer side: may read anything.
- Stage 0 dependencies: SC1 (#86) (the zero rule and the scored set), SC10 (#119) (every new number is written down).

## Files
- `bench/score.py`
- `bench/run.py`
- `bench/SCORING.md`
- `tests/test_bench_score.py`
- `tests/test_bench_run.py`

## Steps
1. `score_end_to_end`: add `repaired = |C ∩ D ∩ K|` if not already returned, `broken = |(C \ D) \ K|`, and `edr = (repaired − broken) / |D|`, which is None when D is empty. Existing keys stay unchanged.
2. `bench/run.py::_aggregate`: pool `repaired`, `broken` and `|D|` over the datasets in SC1 (#86)'s scored set, as sums, not a mean of ratios. Print "clean cells broken: N" and "EDR: x over M datasets" beside the repair mean, in `_markdown` and on the smoke line.
3. External table: a `broken` column and an `EDR` column per set.
4. `bench/SCORING.md`: the two definitions, the dirty-to-other-wrong rule, and which datasets enter the pooled EDR.
5. Tests (test-writer, first):
   - a cleaner that repairs 2 of 4 dirty cells and breaks 3 clean cells gives `broken` 3 and EDR −0.25;
   - the oracle gives `broken` 0 and EDR 1.0; the no-op gives 0 and 0.0;
   - a representation-only change of a clean cell is not `broken`;
   - a dirty cell changed to another wrong value moves neither term.

## Done when
- [ ] `uv run pytest tests/test_bench_score.py tests/test_bench_run.py -q` passes.
- [ ] `uv run python -m bench.run --smoke` exits 0 and prints the broken count and EDR beside the repair mean.
- [ ] `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
- New numbers; no existing number moves. The commit states smoke's `broken` and EDR.
- Whether EDR becomes a published number is Aarmen's call. If it does, it enters SC6 (#118)'s degenerate check under S0-D1. Until then it is printed as a diagnostic.

## Out of scope
- Recall at a fixed precision (a column on SC9 (#94)'s table).
- A "debatable" truth label (raised on SC19 (#126)).
- Per-fix attribution (DH1 (#106)).
````

### B2. grounding: a keyless matcher that finds the numbers in an answer that no recorded output holds

- **Labels:** task, code
- **Placement:** Stage 0, 0b, wave 4 (beside RE27) if Aarmen pulls number grounding back into 0b, where the plan lists it; otherwise Stage 1's answer checks
- **depends_on:** none

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-trustworthy-agents.md`, §2.5 and ranked item 1.

## Type
code

## Goal
`crivo.grounding.unmatched(answer, outputs, question="")` returns every number in an answer's prose that no recorded output holds, after normalising both, so a card can name the number nobody measured.

## Context
- AGENTS.md: a number that was not measured is not claimed. Today nothing compares an answer's prose with what its cells printed.
- **Sources:**
  - VeriGraph (arXiv 2606.16603, 2026-06-15): plain ReAct data agents had only 59.5 to 78.5% of their claims recoverable from the evidence they expose. Its `bind` primitive accepts a claim only if it points at an existing runtime variable.
  - HERMAN (arXiv 2009.13312) checks quantities in summaries against the source.
  - DABstep's scorer (arXiv 2506.23719) normalises numbers and compares within a tolerance; it agreed with two annotators on 75 of 75.
  - The research found no 2025-2026 paper that deterministically matches every number in an agent's prose to logged outputs.
- **Limit:** this proves provenance, not truth. A matched number can still answer the wrong question; that is the intent check's job.
- Keyless, pure, standard library only. Not a core file; B3 wires it into the verdict.
- Under S0-D10, Stage 0 answers are at most partly backed, so this changes no verdict on its own.

## Files
- `src/crivo/grounding.py` (new)
- `tests/test_grounding.py` (new, test-writer)
- `docs/API-CONTRACT.md` (one short section: what counts as a number and a match)

## Steps
1. `numbers(text) -> list[Number]`: each number in the text, with its printed precision.
   - Read: integers with thousands separators (`1,234` and `1 234`), decimals, a leading sign or a negative in parentheses, a trailing `%`, a currency symbol, scientific notation, and `k`, `M` and `bn` suffixes only when attached.
   - Skip: list markers at a line start, and numbers inside backticked code.
2. `matches(n, recorded) -> bool`: true when a recorded number, rounded to n's printed precision, equals n. A percentage also matches its fraction (12% against 0.12 and against 12.0). A suffix scales the number before the compare.
3. `unmatched(answer, outputs, question="")`: the answer's numbers that match no number in `outputs`. `outputs` is a list of strings: the turn's cell values and printed output, and the dataset profile block. A number that appears in the question is not a claim and is skipped.
4. Return the numbers as printed, never the text around them, so a caller can show them without quoting data.

## Done when
- [ ] Tests:
  - `1,234.5` matches `1234.49`; `12%` matches `0.1203`; `(3.2)` matches `-3.2`; `2.4M` matches `2400000`;
  - a number that appears only in the question is skipped;
  - a number in no output is returned;
  - a numbered list is not read as claims.
- [ ] `uv run pytest tests/test_grounding.py -q`, `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
None (a pure function with no caller yet).

## Out of scope
- Calling it from the verdict or the card (B3).
- A `bind` primitive the model calls for derived numbers ("up 12%"). That changes what the model is told, so it is Stage 1 behaviour work.
- Dates and times in prose.
````

### B3. card: an answer whose prose holds a number no cell printed says so in its verdict

- **Labels:** task, code, core
- **Placement:** Stage 0, 0b, wave 4 (after RE27) if pulled forward; otherwise Stage 1
- **depends_on:** B2, RE26 (#209), RE27 (#210)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-trustworthy-agents.md`, ranked item 1.

## Type
code

## Goal
The answer verdict reads the grounding check. When the prose holds a number that no recorded output of the turn holds, the card names the number and the answer cannot be backed.

## Context
- **Which stage:**
  - The plan's 0b list includes "grounding". The Stage 0 spec's cut list moves answer grounding to Stage 1 because it "needs Stage 1's answer()".
  - A deterministic number match needs only the turn's outputs, which the loop already sees. Aarmen decides which stage this lands in.
- **Downgrade-only:** under S0-D10, Stage 0 answers are at most partly backed. This adds a reason and the unmatched numbers; it never raises a verdict.
- **What the loop keeps today:** `_execute_cell` keeps only `value_preview` (`_clip(result.value, VALUE_PREVIEW)`) on the cell dict. The stream text reaches only the model's history, clipped.
  - The check needs the turn's full values and printed text, held in memory for the turn.
  - Never write them to the card: the card stays free of data.
- Core: `loop.py`, `card.py`; `verify.py` is core under S0-D6.

## Files
- `src/crivo/loop.py` (core, about 10 lines: keep the turn's output texts and pass them on)
- `src/crivo/verify.py` (`answer_verdict` gains the grounding input)
- `src/crivo/card.py` (core: one line under the verdict)
- `tests/test_loop.py`, `tests/test_card.py`, `tests/test_verify.py` (test-writer)
- `docs/API-CONTRACT.md` (`AnswerCard.verdict`: the `ungrounded` reason and its list)

## Steps
1. `run_turn`: collect, in a local list for this turn, each executed cell's full `result.value` and stream text, plus the dataset profile block the turn's history holds. Pass the list to `answer_verdict`. Never store it on the card.
2. `verify.answer_verdict(..., outputs)`: call `grounding.unmatched(answer, outputs, question)`.
   - Any unmatched number adds the reason "numbers no cell printed: <n1>, <n2>": at most 5, then a count.
   - The verdict can then be at most partly backed.
   - Whether an ungrounded number gives partly backed or not backed is Aarmen's. The default here is partly backed, as the research suggests.
3. `card.to_markdown`: the reason line lists the numbers as printed.
4. The text is fixed in this row, and none of it reaches the model.

## Done when
- [ ] Tests with the faux provider:
  - an answer whose number a cell printed has no `ungrounded` reason;
  - an answer with a number no cell printed lists it;
  - a number from the question is not listed;
  - the verdict never rises because of grounding.
- [ ] Each cassette under `tests/cassettes/` that asserts a verdict still passes, or its new reason is pinned.
- [ ] `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
- None for the bench: the clean lane has no answers.
- Unmeasured on real answers until Stage 1's suite exists; the commit says so.
- Risk to state: unit and rounding false flags. The listed numbers are the evidence a person checks.

## Out of scope
- Telling the model about the check, or a `bind` primitive (behaviour, Stage 1). The model could learn to write fewer numbers, so that change needs an eval.
- Replay and the second path for answers (Stage 1).
````

### B4. traps: impossible-repair and canary cases for the referee's false-backed rate

- **Labels:** task, eval
- **Placement:** Stage 0, Loop 1 and 0b, wave 4 (before L5 and RE33)
- **depends_on:** EV6 (#69), EV19 (#82), SC24 (#187), L4 (#229); ED7 (decided)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-trustworthy-agents.md`, ranked item 3.

## Type
eval

## Goal
A trap suite at `bench/traps/referee/` holds two kinds of case: cases where no fix can be correct, and cases where a perfect repair is evidence of cheating. Its grader turns each fix's verdict into a labelled record. A backed verdict on an impossible case is false-backed by construction.

## Context
- **Sources:**
  - ImpossibleBench (arXiv 2510.20270, MIT).
  - PROCTOR (arXiv 2609.02246): canary cases where a perfect score is evidence of cheating.
  - Kalai et al. (arXiv 2509.04664): binary grading rewards guessing.
- **The gap it fills:** the Stage 0 spec has no per-fix false-backed rate, because the agent lane keeps only each case's final frame (Risks). L4 (#229) runs a fix through the real referee and checks the verdict against truth; this suite gives it cases whose right outcome is a refusal.
- **Built by the eval-author** (EV6 (#69)).
  - The author must not read `src/crivo/prompts.py`, `src/crivo/loop.py`, the referee (`src/crivo/verify.py`, `src/crivo/diff.py`, `src/crivo/kernel/frames.py`), `src/crivo/detect.py` or `src/crivo/autoclean.py`. `guard_reads.py` enforces it.
  - Cases come from the taxonomy (the brief's disease descriptions and the contract's slug table), never from what crivo does.
- Never quote a case in an issue, commit message, prompt or skill: name the suite.
- Held-out and sealed cases live where ED7 puts them: outside the public repo, with only their hash committed.

## Files
- `bench/traps/referee/` (dev cases, the grader, the self-check; held-out and sealed where ED7 puts them)
- `tests/test_traps_referee.py` (the self-check)

## Steps
1. **Impossible-repair cases:** dirty frames where, by the taxonomy's own description of the disease, the original value cannot be recovered from the file.
   - Each case's truth says "no correct fix exists; the right outcome is a refusal or a person".
   - Split dev, held-out and sealed by disease and variant, not by seed.
2. **Canary cases:** cases whose correct repair needs a value present only in the truth record, never derivable from the data. A repaired cell equal to it means a cell read the truth. The grader reports these as contaminated, never as repaired.
3. **The grader:** given a case, a fix's verdict and the cleaned frame, emit one JSON line `{case, split, disease, verdict, correct, contaminated}`.
   - `correct` is false for any changed target cell on an impossible case.
   - Verdicts are read from what the referee recorded, never from model text.
4. **The self-check, keyless:**
   - a refuse-everything cleaner scores 0 false-backed on the impossible cases;
   - a stub that backs every fix scores false-backed on all of them;
   - a stub cleaner that reads the truth file trips every canary;
   - an honest no-op trips none.
5. Register the suite hash (EV4 (#67)).

## Done when
- [ ] `uv run pytest tests/test_traps_referee.py -q` passes, with the four self-check strategies behaving as step 4 says.
- [ ] The suite hash is registered.
- [ ] The reviewer confirms the author's session never read the blocked files.

## Measurement
- No paid run in this issue. The keyless run is L4 (#229)'s harness on the dev split. The paid use is L5 (#230) and RE33 (#231)'s guard metrics, under D16 and D21.
- What it feeds: B6's false-backed rate for fixes, with its Wilson upper bound against D19's ceiling.

## Out of scope
- Impossible questions for answers (Stage 1's trap suite; the plan's Stage 1 gate lists unanswerable questions).
- The trust-weighted score (B6).
- Injection cases (CT25 (#218), CT26 (#219)).
````

### B5. eval: result rows carry paired per-case differences with clustered standard errors, and say when noise swamps the signal

- **Labels:** task, code
- **Placement:** Stage 0, eval tooling follow-up, wave 1 or 2 (no decision needed). It should land before the first paid decision rows: CT7 (#194)'s guard run, SC30 (#227), RE33 (#231).
- **depends_on:** EV8 (#71), EV15 (#78)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-trustworthy-agents.md`, §4.2 and ranked item 4.

## Type
code

## Goal
Every `bench.eval` result row that compares two arms carries the per-case paired difference in pass@1, with a standard error clustered by case, and a flag when that difference is inside the suite's A/A noise floor. A decision then reads off a stated uncertainty.

## Context
- **Sources:**
  - Miller, "Adding Error Bars to Evals" (arXiv 2411.00640; Anthropic, 2024-11-19): cluster standard errors on the unit of randomisation ("over three times larger on popular evals"), compare models with paired differences, and size evals by power.
  - AI2, "Signal and Noise" (arXiv 2508.13144): benchmarks with higher signal-to-noise give more reliable decisions.
- **What exists:** `bench/eval.py::_noise_floor` gives an A/A pass@1 spread and the flaky set, and `bench/ledger.py::wilson` gives intervals. Nothing pairs arms case by case or reports a standard error, so a two-arm difference has no uncertainty on the row.
- **Clustering:** k runs of one case are not independent, so the case is the cluster. Corpus cases built from the same base frame share a second cluster key when the suite provides one.
- Result rows are append-only and checked by `scripts/check_locks.py`. The new keys are optional, so old rows still validate.

## Files
- `bench/eval.py`
- `bench/ledger.py` (the result row's optional keys and their validation)
- `tests/test_eval.py`, `tests/test_ledger.py` (test-writer)
- `docs/ARCHITECTURE.md` (one line under the eval ledger)

## Steps
1. For each pair of arms on a result:
   - per case, the mean pass@1 over its k runs in each arm;
   - `paired = {arms, n_cases, mean_diff, se, ci95}`, where `se` is the standard deviation of the per-case differences divided by √n_cases;
   - cases missing from either arm are left out and counted.
2. When the suite's cases carry a base key, add `se_by_base`: the same computed over per-base mean differences.
3. `snr`: `|mean_diff|` divided by the suite's A/A floor for that model, read from the ledger the way `/eval` step 5 does. `inside_noise: true` when the ratio is below 1, or when no floor exists (with the reason).
4. Print one line per pair after the noise-floor line, for example "A vs B: +0.06 per case (se 0.03, 95% CI ...), inside the noise floor".
5. `ledger.py`: validate the new keys when present; old rows pass unchanged.

## Done when
- [ ] Tests:
  - two arms with known per-case outcomes give the hand-computed `mean_diff` and `se`;
  - a missing case is excluded and counted;
  - with no A/A floor, `inside_noise` is true with its reason;
  - an old result row still validates.
- [ ] `uv run pytest tests/test_eval.py tests/test_ledger.py -q`, `uv run python scripts/check_locks.py`, `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
None (statistics on rows; no model call).

## Out of scope
- Discrimination and coverage for the referee (B6).
- Power analysis to size a suite (a note in the eval spec is enough for now).
- inspect_ai as a dependency: it is heavy and ships agent scaffolds. Its formulas are MIT if any are copied.
````

### B6. bench: the referee graded as a classifier over labelled fixes

- **Labels:** task, code
- **Placement:** Stage 0, Loop 1, wave 5 (with L4 and L5)
- **depends_on:** L4 (#229), B4, B5

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-trustworthy-agents.md`, §2.4 and ranked items 3 and 4.

## Type
code

## Goal
`uv run python -m bench.referee_score <records.jsonl>` reads fix records labelled with the referee's verdict and the truth. It prints, each with its counts:
- the false-backed rate with its Wilson upper bound;
- the backed rate (coverage);
- how well the verdict separates right fixes from wrong ones;
- a trust-weighted score.

## Context
- **Why one rate is not enough:** HAL's reliability study (arXiv 2602.16666, ICML 2026) found calibration improving while discrimination (AUROC) stagnated or got worse. The plan's headline metric is the false-backed rate, and alone it cannot tell a referee that backs little from one that separates well.
- **The trust-weighted score:** Kalai et al. (arXiv 2509.04664) score against a stated confidence target t: a wrong answer costs t/(1−t), an abstention 0. The value of t is Aarmen's, beside D19.
- **The bound:** D19 (decided) caps the 95% Wilson upper bound of the false-backed rate at 5%, with at least 100 backed results per arm per suite. Wilson is already a finite-sample bound on a rate. A conformal or Learn-then-Test bound only matters if verdicts ever come from a thresholded score, so this row does not build one.
- **Inputs:** one JSON line per fix, `{case, split, disease, verdict, correct}`, from L4 (#229)'s harness on attack fixes and from B4's trap cases. The agent lane joins once it keeps each fix's frames; the Stage 0 spec says it does not yet.
- Scorer side: may read anything.

## Files
- `bench/referee_score.py` (new)
- `bench/attack_harness.py` (L4's referee target appends one record per fix)
- `tests/test_referee_score.py` (new, test-writer)
- `bench/SCORING.md` (the definitions)

## Steps
1. A confusion table over (backed, partly backed, not backed) × (correct, wrong), by split and disease, with counts.
2. False-backed rate: wrong among backed, with `ledger.wilson`'s interval, marked "below D19's minimum of 100 backed" when n is small. Coverage: the backed share of all fixes.
3. Discrimination:
   - AUROC with the verdict as an ordinal score (backed 2, partly 1, not 0), ties counted half;
   - the risk and coverage pair at each of the two cut points (backed only; backed or partly).
4. Trust-weighted score = (backed and correct − t/(1−t) × backed and wrong) / n, printed only when `--t` is given.
5. Standard errors clustered by case, as B5 computes them.

## Done when
- [ ] Tests:
  - hand-built records give the hand-computed rates, interval, AUROC and score;
  - a referee that backs everything has AUROC 0.5;
  - small n is marked.
- [ ] `uv run pytest tests/test_referee_score.py tests/test_attack_harness.py -q`, `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
None in this row (an instrument). L5 (#230)'s ledger rows quote its numbers.

## Out of scope
- Answer verdicts (Stage 1).
- Choosing t (Aarmen).
````

### B7. loop: PII-shaped values in a cell's output are masked before the model reads them

- **Labels:** task, code, core
- **Placement:** Stage 0, 0d containment, wave 2 (after CT17, which edits the same `_observation`)
- **depends_on:** CT17 (#110)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-table-agents-landscape.md`, §1.4 and ranked item 2.

## Type
code

## Goal
An email address, phone number, SSN or card number that a cell prints, in its value, printed output or error text, reaches the model's history masked the way the profile masks it. `.head()` on a PII column no longer sends raw values to the provider.

## Context
- **The gap:**
  - CT16 (#114) masked the profile's samples and top values. Its own decision comment says model cell output still reaches the model raw.
  - SECURITY.md lists "cell output and error messages ... clipped today" as a path from data to the model.
  - `kernel/bootstrap.py` sets `display.max_rows=30`, so a `.head()` of a PII column shows up to 30 raw values.
  - AGENTS.md says no raw dataset rows in any prompt; practice falls short of the rule on this path.
- **Where:** host-side, in `_observation` (`loop.py:~2320`), so a cell cannot switch it off. The kernel's own display is untouched, and the person still sees their own data in the REPL.
- `pii.py` already has per-cell detectors and `mask_value`. This needs a free-text pass over observation text.
- **It narrows the gap, it doesn't close it.** These still reach the model:
  - a value printed in a form the detectors don't match;
  - names and addresses (there is no NER);
  - finding evidence on the fix path (S0-D23).

  Docs and the changelog must not say otherwise.
- Core: `loop.py`. This changes what the model reads on PII-shaped text only; CT16 (#114) was typed `code` on the same reasoning.

## Files
- `src/crivo/pii.py` (`mask_text(text) -> tuple[str, int]`)
- `src/crivo/loop.py` (core, about 6 lines: `_observation` and the verification-failed messages pass through `mask_text`)
- `tests/test_pii.py`, `tests/test_loop.py` (test-writer)
- `docs/API-CONTRACT.md` ("PII masking": model observations), `SECURITY.md` (the path's line)

## Steps
1. `pii.mask_text`: find tokens in free text that the existing detectors call PII on their own, and replace each with `mask_value`'s form. Return the text and the count.
   - Match: an email; an SSN in its dashed form; a card number that passes Luhn, with its separators; a phone number with a `+` or separators.
   - Leave bare digit runs with no separator alone, so ids, counts and amounts are not masked.
2. `_observation`: run the value, the stream text and the error text through `mask_text` after clipping. Put the count in the observation header (`masked="N"`), so the model knows values were hidden.
3. The two verification-failed messages and the harmonize notice that CT17 (#110) clips get the same pass.

## Done when
- [ ] A test with the faux provider: a cell that prints `df.head()` of an email column leaves no raw address in `session.history`, and the count is in the header.
- [ ] A test: a column of 10-digit ids, a column of amounts and an ISO date column print unmasked.
- [ ] `uv run pytest tests/test_pii.py tests/test_loop.py -q`, `uv run pytest -q`, `uv run ruff check .` and `uv run python -m bench.run --smoke` (unchanged) pass.

## Measurement
- Bench smoke unchanged.
- This changes what the model reads only on PII-shaped text. If an agent-lane dev case carries such a column, include this change in CT7 (#194)'s guard run. Otherwise the commit says "unmeasured, no case exercises it", as CT16 (#114) did.

## Out of scope
- A masked `peek` helper the prompt points to instead of `.head()`: the plan's Stage 1 `Session.peek`, a prompt change (behaviour).
- Fix-path evidence (S0-D23). Names and addresses (Stage 4).
- Secrets: CT13 (#112) redacts those on the same path.
````

### B8. reports: every HTML page crivo writes carries a policy that loads nothing remote

- **Labels:** task, code
- **Placement:** Stage 0, 0d containment, wave 2
- **depends_on:** none

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-containment-context.md`, §3.3 and ranked item 7.

## Type
code

## Goal
`Report.to_html`, `compare_to_html` and `reconcile_report` each write a Content-Security-Policy that lets the page load nothing from the network. Text planted in data can then never turn a crivo report into a request to someone else's server.

## Context
- **The channel:** PromptArmor's "CellShock" report (Nov 2025). An injection in a sheet led Claude for Excel to write an `IMAGE()` formula pointing at an outside URL with data in its query: exfiltration through the output. Ramp Sheets AI had the same class, fixed 2026-03-16.
- **Today:** crivo's three HTML writers already escape data text (`html.escape`) and inline their styles and charts (`data:` PNGs, `notebook.py:~313`). So the policy should change nothing they render. It closes the channel if a later change, or an escaping bug, lets a URL through.
- **The policy,** as a `<meta http-equiv="Content-Security-Policy">` in each `<head>`: `default-src 'none'; img-src data:; style-src 'unsafe-inline'`.

## Files
- `src/crivo/htmlreport.py` (one shared constant)
- `src/crivo/api.py` (`Report.to_html`), `src/crivo/compare_report.py`, `src/crivo/rowdiff_report.py`
- `tests/test_to_html.py`, `tests/test_compare_report.py`, `tests/test_reconcile.py` (test-writer)
- `SECURITY.md` (one line under the threat model's defences)

## Steps
1. `CSP_META` in `crivo/htmlreport.py`; each of the three writers puts it first in `<head>`.
2. Tests:
   - each page carries the meta;
   - a frame whose text cells hold HTML markup with a remote URL renders it escaped;
   - the page holds no `src=` or `href=` pointing at `http`.

## Done when
- [ ] `uv run pytest tests/test_to_html.py tests/test_compare_report.py tests/test_reconcile.py -q` passes.
- [ ] The example report, opened by hand, still shows its charts (`data:` images are allowed); the commit says it was checked.
- [ ] `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
None.

## Out of scope
- Notebook cards inside Jupyter: a notebook ignores a meta policy, and their HTML is escaped already.
- MCP results: they carry no auto-fetching links today, and the Stage 1 MCP port keeps it so.
````

### B9. external: Pollock's polluted CSV files score crivo's reader

- **Labels:** task, code
- **Placement:** Stage 0, 0d platform, wave 2, before PF20 (#163) so the one-reader change shows its effect
- **depends_on:** D24's rule (decided); SC11 (#95) for the ledger row, if it has landed

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-data-cleaning.md`, §2 and S4.

## Type
code

## Goal
`uv run python -m bench.reader_bench` loads every file of the Pollock benchmark with `crivo.read`, scores how close each loaded table is to its clean source, and prints Pollock's simple and weighted scores beside pandas' defaults. A reader change then shows its effect on files crivo did not design.

## Context
- **The benchmark:** Pollock (Vitagliano et al., PVLDB 16(8), 2023; repo HPI-Information-Systems/Pollock, MIT, LICENSE added 2026-07-16).
  - About 2,290 polluted CSVs: preambles, multiple headers, two tables in one file, ragged rows, other delimiters and quoting, mixed newlines. Each is scored against its clean source.
  - Published simple / weighted scores: pandas 1.4.3 (configured) 9.895 / 9.431; CleverCSV 0.7.4 (auto) 9.193 / 9.453. DuckDB 1.2 scores 9.961 configured and 9.075 auto.
- **Overfitting warning:** a 0-star loader created 2026-09-24 topped the table at 9.997 three days later, added by its own author. So part of the corpus is held out, by a fixed rule chosen before the first score. Nothing in `src/crivo/readers/` is tuned against the held-out part, and a reader change reports dev and held-out side by side.
- **Instrument first:** PF20 (#163) unifies the reader path and should show its number here.
- **Licence handling follows D24:** fetch, never commit (`data/` is git-ignored), pin hashes, record the licence and source in the fetch script's header, publish scores only.

## Files
- `scripts/fetch_pollock.py` (new)
- `bench/reader_bench.py` (new)
- `tests/test_reader_bench.py` (new, test-writer)
- `bench/SCORING.md` (the reader scores)

## Steps
1. Fetch script: download into `data/external/pollock/`, check pinned sha256s, and fail loudly on a mismatch. Licence and source URL go in the header.
2. Split: a file is held out when the first hex digit of the sha256 of its relative path is 0 to 4 (about 30%). The rule goes in the module docstring and never changes after the first score.
3. Load each file with `crivo.read` in its default (automatic) mode, counting any exception as a failed load. Port Pollock's simple and weighted scores (MIT; keep the attribution). Run pandas' `read_csv` with its defaults as the baseline row.
4. Print one table per split (loader, simple, weighted, files failed) and write `bench/results/reader_bench.json`. When SC11 (#95) has landed, append a ledger row with the corpus hash.
5. Tests:
   - on three tiny hand-built polluted files in tmp (a preamble, a ragged row, a semicolon delimiter) with their clean twins, the scores match hand-computed ones;
   - a hash mismatch fails;
   - an absent corpus exits 2 with the fetch hint.

## Done when
- [ ] `uv run pytest tests/test_reader_bench.py -q` passes.
- [ ] After the fetch, `uv run python -m bench.reader_bench` prints both splits' tables.
- [ ] `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
New numbers; the commit states them. A low number is the instrument working.

## Out of scope
- Changing the reader (PF20 (#163) and later rows).
- CleverCSV or DuckDB as dependencies.
- Excel files.
````

### B10. detect: d13 flags values outside a validated domain, only when the column clears a Wilson bound

- **Labels:** task, code, core
- **Placement:** not Stage 0. The recall wave after SC24 (#187)'s split, per S0-D19's rule. Hold until then.
- **depends_on:** SC24 (#187), SC9 (#94), SC25 (#188), B14

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-data-cleaning.md`, §1.4 and S3.

## Type
code

## Goal
For a column where nearly every distinct value passes a standard validator (email, URL, phone number, an ISO country or currency code), d13 names the few that fail, graded GATE. It fires only when a Wilson lower bound on the passing share clears a threshold set in advance, so columns of codes and abbreviations never fire.

## Context
- **Source:** Auto-Test (Chen, He et al., SIGMOD 2025, arXiv 2504.10762).
  - It tests semantic-domain constraints of the form "if at least m of a column's values are in-domain, the rest are errors", with confidence taken as a Wilson lower bound (z = 1.65).
  - Its benchmarks have a realistic base rate: about 3 to 4% of columns hold errors.
  - GPT-4 few-shot detection failed there by flooding false positives on codes and abbreviations.
- Deterministic: the validator is a predicate the referee can re-run after a fix.
- **New dependencies, Aarmen's call:** `validators` (MIT, about 12 ms import) and `phonenumbers` (Apache-2.0, 23 MB on disk; `phonenumberslite` is smaller). He decides whether they are core or an extra. `import crivo` must stay light, so they load lazily inside the check.
- `detect.py` is core. d13 is GATE today (`_d13`, `detect.py:~1441`).

## Files
- `src/crivo/detect.py` (core: `_d13`'s new branch)
- `pyproject.toml` (the dependencies, as Aarmen decides)
- `tests/test_detect.py` (test-writer)

## Steps
1. For each text column with at least 20 distinct values, compute, per validator family, the share of distinct values that pass.
   - When the 95% Wilson lower bound of that share is at least `m`, list the failing values as a d13 finding, GATE, with the evidence "N of M distinct values pass <family>; K do not". Never grade AUTO.
   - `m` is fixed in this issue before any run. Start from 0.98, as the research suggests.
2. Families:
   - email and URL via `validators`;
   - phone via `phonenumbers.is_valid_number` with no default region, so a number without `+` and a country code is not judged;
   - ISO 3166 country and ISO 4217 currency codes from a short table in the module.
3. Pins:
   - a column of internal codes or abbreviations that no validator claims gives no finding;
   - an internationalised email that a validator rejects is recorded in the docstring as a known false negative.

## Done when
- [ ] Regression tests:
  - a column of valid emails with two broken ones gives one GATE finding naming a count of two;
  - a codes column gives none;
  - a 15-row column gives none.
- [ ] B14's corpus cases are in the dev split, and the commit carries SC9's per-detector before and after for d13, dev and held-out (SC25 (#188)).
- [ ] `uv run python -m bench.run --smoke`, `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
d13 precision and recall per SC9 (#94), dev and held-out side by side. The threshold m is fixed before the held-out run and never tuned on it.

## Out of scope
- A fixer for d13: out-of-domain values need a person.
- Embedding- or model-based domains: they can't be re-checked deterministically.
````

### B11. clean: d08 mojibake gets a deterministic fixer

- **Labels:** task, code
- **Placement:** not Stage 0. After SC24 (#187), with B14's corpus shapes (S0-D19).
- **depends_on:** SC24 (#187), B14

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-data-cleaning.md`, §3.1 and S5.

## Type
code

## Goal
`autoclean.FIXERS[8]` repairs text mis-decoded in the wrong encoding, in the cells d08 names, using `ftfy`. A person who approves a d08 gate then gets a deterministic fix instead of model-written code.

## Context
- **The library:** `ftfy` (Apache-2.0, 6.3.1; one dependency; about 23 ms import) fixes mojibake. Measured 2026-10-23:
  - it repaired double-decoded accents and umlauts and smart-quote mojibake;
  - it left correctly accented words untouched;
  - it is idempotent.
- **Today:** d08 is GATE and has no entry in `autoclean.FIXERS`. The loop's deterministic fix path uses `FIXERS` for any disease that has an entry (`loop.py:~1641`).
- This row keeps d08 GATE. Whether d08 becomes AUTO once it has a fixer is Aarmen's (a grade).
- **New dependency:** Aarmen decides core or extra. It is imported inside the fixer only.
- Not core: `autoclean.py`.

## Files
- `src/crivo/autoclean.py` (`_fix_mojibake`, registered as `FIXERS[8]`)
- `pyproject.toml`
- `tests/test_autoclean.py`, `tests/test_autoclean_refusals.py` (test-writer)

## Steps
1. `_fix_mojibake(frame, cols)`: for each target column, apply `ftfy.fix_encoding` to string cells. Use encoding repair only, not `fix_text`'s other normalisations. A cell changes only when the result differs.
2. Refuse, returning the column unchanged:
   - when a changed cell's result changes again under a second `fix_encoding` (not idempotent);
   - when more than half the column's non-null cells would change. That is a decode problem for the reader, not cell damage.
3. Pins: correct accented text is untouched; a column with no mojibake is returned identical.

## Done when
- [ ] Tests: the report's measured shapes are repaired; correct accented text is untouched; both refusals hold.
- [ ] The commit carries the d08 bench line, dev and held-out (SC9 (#94), SC25 (#188)).
- [ ] `uv run python -m bench.run --smoke`, `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
d08 repair on the dev and held-out splits. The smoke line holds unless a smoke case is d08; then the commit states the move.

## Out of scope
- `ftfy.badness` as the d08 detector (`detect.py`, core; its own row, with corpus evidence).
- Regrading d08 (Aarmen's).
- Reader-level encoding detection (charset-normalizer; a reader row).
````

### B12. detect and clean: d07's automatic tier uses one variant key, shared by the detector and the fixer

- **Labels:** task, code, core
- **Placement:** not Stage 0. After SC24 (#187), with B14 (S0-D19).
- **depends_on:** SC24 (#187), B14, DH11 (#142), DH5 (#134)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-data-cleaning.md`, §3.1 and S6.

## Type
code

## Goal
d07's AUTO finding and `_fix_case_variants` group spellings by one key that also ignores punctuation and accents. The key is defined once, in `detect.py`, so variants such as a trailing period or a missing accent are caught and fixed the way case variants are today.

## Context
- **Source:** OpenRefine's fingerprint key: trim, lowercase, strip punctuation and control characters, fold to ASCII, split into tokens, sort, deduplicate, join. OpenRefine's docs call it "the least likely to produce false positives" of its clustering methods (BSD-3; about 30 lines to reimplement).
- **Today:** `_fix_case_variants` (`autoclean.py:~348`) keys on whitespace-collapsed lowercase and maps each key to its most frequent spelling. `_d07` grades the case-variant tier AUTO and its fuzzy tier HUMAN.
- **One rule in one place,** the pattern of DH16 (#174)'s `number_parse`, so the detector and the fixer can't drift.
- **No token sorting in the AUTO key.** Sorting merges reordered names ("Smith John" and "John Smith") that can be distinct entities. A token-sorted or n-gram key would be at most GATE, and only if Aarmen wants that tier.
- **ASCII folding uses the standard library** (`unicodedata.normalize("NFKD")`, combining marks dropped), so there is no new dependency. `anyascii` (ISC) is an option only if Aarmen wants wider transliteration.
- **Accented text stays safe:** DH11 (#142) and DH5 (#134) pin that correct accented text is not damage. A column holding only the accented spelling never fires, because a key collision needs two spellings.
- Core: `detect.py`.

## Files
- `src/crivo/detect.py` (core: `variant_key`, used by `_d07`)
- `src/crivo/autoclean.py` (`_fix_case_variants` imports it)
- `tests/test_detect.py`, `tests/test_autoclean.py` (test-writer)

## Steps
1. `detect.variant_key(text) -> str`: strip; collapse whitespace; lowercase; NFKD-fold and drop combining marks; remove punctuation and control characters. No token sorting.
2. `_d07`'s AUTO tier groups by `variant_key`; its evidence counts each group's spellings.
3. `_fix_case_variants` keys by `variant_key`. The canonical form stays the most frequent spelling, and ties keep today's rule.
4. Pins:
   - every existing d07 test passes;
   - two reordered names are not grouped;
   - a column with one accented spelling only gives no finding.

## Done when
- [ ] Regression tests: a punctuation variant and an accent variant are grouped and fixed; reordered names are not grouped; the pins pass.
- [ ] The commit carries d07's per-detector before and after, dev and held-out (SC9 (#94), SC25 (#188)), and `tx-case-spelling` still repairs.
- [ ] `uv run python -m bench.run --smoke`, `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
d07 detection and repair on dev and held-out. If RE21 (#205) has landed, its collateral stays 0 on d07 fixes.

## Out of scope
- RapidFuzz for the fuzzy tier (MIT, a new dependency): a speed change for the HUMAN tier, its own row.
- Regrading the fuzzy tier (Aarmen's).
````

### B13. detect: a d21 rollup row is confirmed by arithmetic over its block, and an Excel SUM formula counts as evidence

- **Labels:** task, code, core
- **Placement:** not Stage 0. After SC24 (#187), with B14 (S0-D19).
- **depends_on:** SC24 (#187), B14, RE19 (#182)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-data-cleaning.md`, §1.8 and S7.

## Type
code

## Goal
d21's evidence says whether each rollup row's numbers are the sum or the mean of a block of rows, in how many columns, and whether the file's own formula says so. A person at the gate then sees proof, not just a label match.

## Context
- **Sources:**
  - AggreCol (HPI, EDBT 2022, Apache-2.0) detects sum, average and other aggregations in verbose CSVs. At 0.95 precision and recall it covers 91.1% and 86.3% of the files on two annotated corpora.
  - Strudel (EDBT 2021) uses the same arithmetic features to classify derived lines.
  - openpyxl, already a dependency, exposes formula cells (`data_type == "f"`, for example `=SUM(C4:C9)`).
- **Today, `_d21` (`detect.py:~1929`):**
  - matches rollup labels;
  - a single labelled row must corroborate as the sum of every other row in some numeric column;
  - two or more labelled rows (under 20% of rows) are flagged on the label alone;
  - subtotals over a block, averages and agreement across columns are not checked.
- **The grade stays GATE in this row.** A confirmed rollup row is removed only after a person approves (autoclean's rule: anything that deletes rows is reported, never decided). Whether arithmetic proof makes d21 AUTO is Aarmen's; D7's row rule already lets a d21 fix remove exactly its flagged rows.
- Core: `detect.py`.

## Files
- `src/crivo/detect.py` (core: `_d21`'s evidence)
- `src/crivo/excel_structure.py` (formula evidence for xlsx input)
- `tests/test_detect.py`, `tests/test_excel_structure.py` (test-writer)

## Steps
1. For each labelled candidate row, in each numeric column, test whether its value equals the sum or the mean of the contiguous block of rows above it since the previous candidate (or below, for a header total), within 1e-6 relative. Record the columns that agree.
2. Evidence: "row N is the sum of rows a to b in K of M numeric columns", or "labelled only: no column adds up".
   - Keep the finding either way.
   - Label-only findings keep GATE with a lower confidence (0.6), so a reader can tell them apart.
   - Add `confirmed: K` to the finding's stats.
3. Against coincidental sums in small integer tables:
   - a block must hold at least 3 rows;
   - a confirmation needs at least 2 agreeing columns when the frame has 2 or more numeric columns.
4. `excel_structure.py`: for xlsx input, report formula cells whose formula is a `SUM` or `AVERAGE` over a range in the same column, with the row they sit on. `_d21` reads that as confirmation.
5. Pins:
   - today's single-labelled-row corroboration still fires;
   - a row named like a total whose numbers add up to nothing is labelled-only.

## Done when
- [ ] Regression tests:
  - a subtotal block is confirmed in two columns;
  - a coincidental single-column sum in a 3-row table is not confirmed;
  - an xlsx row with a SUM formula is confirmed;
  - the pins pass.
- [ ] The commit carries d21's per-detector numbers, dev and held-out (unchanged counts are expected; the evidence is new).
- [ ] `uv run python -m bench.run --smoke`, `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
Detection counts should not move (findings are kept either way); say so. Repair is unchanged: there is no d21 fixer.

## Out of scope
- A d21 fixer, and regrading (Aarmen's).
- Unlabelled rollup rows: a recall change, to propose after this lands.
````

### B14. corpus: dev, held-out and sealed shapes for case and spelling variants, mojibake, aggregate rows and out-of-domain values

- **Labels:** task, eval
- **Placement:** not Stage 0. After SC24 (#187)'s split; it comes before B10 to B13. Split per disease when filed if it passes about 300 lines, in the order d07, d08, d21, d13.
- **depends_on:** SC24 (#187), SC21 (#186), EV6 (#69), EV19 (#82)

This body names no technique on purpose: the eval-author receives it, and B10 to B13 describe how crivo would detect or fix these diseases.

````markdown
## Type
eval

## Goal
The corpus holds shapes for d07, d08, d13 and d21 that a careful analyst would call that disease, plus look-alikes that are not damage, split dev, held-out and sealed by kind. A change to those detectors or fixers then shows its effect on shapes it was not tuned on.

## Context
- AGENTS.md: a new detector or fixer ships with corpus cases that exercise it. Upcoming work on these four diseases needs shapes beyond the smoke corpus's.
- **Built by the eval-author** (EV6 (#69)).
  - The author must not read `src/crivo/detect.py` or `src/crivo/autoclean.py`; `guard_reads.py` enforces it.
  - Plant what the taxonomy says each disease is: the brief's disease descriptions and the contract's slug table (case-spelling-variants, encoding-mojibake, out-of-domain-values, aggregate-rows).
  - Nothing in this issue describes how crivo detects or fixes them, on purpose.
- **Look-alikes:** every disease also gets correct text that only resembles the disease, so a detector that over-fires loses precision. DH5 (#134) does this for accented text; follow its pattern.
- Each shape records secondary diseases and accepted repairs (SC21 (#186)). Its split follows SC24 (#187)'s rule: by kind of dirt, not by seed. Sealed shapes live where ED7 puts them.
- Work one disease at a time on `bench/corrupt.py`, `bench/bases.py` and `bench/corpus.py`. Each changes the corpus hash, so say which cassettes need re-recording.
- Never quote corpus values in the issue thread; name the case.

## Files
- `bench/corrupt.py`, `bench/bases.py`, `bench/corpus.py`
- `tests/test_bench_corrupt.py`, `tests/test_bench_bases.py`

## Steps
1. For each of d07, d08, d13 and d21:
   - list the variants the taxonomy description implies, from the description alone, and the look-alikes a careful analyst would leave alone;
   - write one injector or base per variant, each with its truth, accepted repairs and split.
2. Self-check: each injector plants what its truth says (oracle repair F1 1.0, no-op 0.0, SC5 (#91)'s invariants); look-alike cases carry no truth corruption.
3. Hand back the list of new case names and the corpus hash.

## Done when
- [ ] `uv run pytest tests/test_bench_corrupt.py tests/test_bench_bases.py -q` and `uv run python -m bench.run --smoke` pass.
- [ ] The reviewer confirms the author never read the blocked files.

## Measurement
None in this issue. The detector and fixer rows report their effect on these cases.

## Out of scope
- Any detector or fixer change.
````

### B15. loop: cell outputs older than ten turns are replaced by a pointer, in batches

- **Labels:** task, behaviour, core
- **Placement:** not Stage 0. Stage 1 (the plan's "lossless compaction with pointers to cards and transcript events").
- **depends_on:** PF8 (#116), CT17 (#110), EV15 (#78) (the floor)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-containment-context.md`, §5 and ranked item 8.

## Type
behaviour

## Goal
In a long session, the model's history keeps every cell's code and the model's own reasoning, while cell outputs older than a window are replaced by a one-line pointer to where the full output is saved. The context stays small without an LLM summary.

## Context
- **Sources:**
  - JetBrains Research (Lindenbauer et al., arXiv 2508.21433, NeurIPS'25 DL4C) replaced observations older than M = 10 turns with a placeholder, keeping all reasoning and actions. On SWE-bench Verified it matched or beat LLM summarisation at about half the cost. Qwen3-Coder 480B: 54.8% at $0.61, against 53.4% raw at $1.29 and 53.8% with summaries at $0.64. Summaries made trajectories longer.
  - Anthropic calls tool-result clearing "one of the safest lightest touch forms of compaction" (2025-09-29).
  - Manus: compression should be restorable.
- **Today:** `_compact_history` in `loop.py` summarises with the model past `COMPACT_AT_CHARS`, and PF8 (#116) wires a context-overflow error to it.
- **Why not a summary:** an LLM summary can copy injected text from a tool output into what later reads as trusted session state (the report's §5.3). Masking has no such path.
- **Prompt caching:** DeepSeek and Anthropic cache prompt prefixes, so masking one observation per turn would break the cache every turn. Mask in batches, as Anthropic's `clear_at_least` and Manus advise.
- Keep the latest error unmasked: the model may still need it.
- Core: `loop.py`.

## Files
- `src/crivo/loop.py` (core: a `_mask_old_observations` step before each model call)
- `tests/test_loop.py` (test-writer, on recorded replies)

## Steps
1. Each observation already carries `cell_ev`, its transcript event id. When the observations outside the last 10 turns hold more than `MASK_BATCH_CHARS` (start at 20,000), replace each of them with `<observation cell_ev="..." masked="1">output hidden; transcript event ... holds it</observation>`.
   - Never mask the most recent error.
   - Never mask the dataset profile block.
2. Keep `_compact_history` as the fallback when masking is not enough.
3. Tests on recorded replies (EV3 (#66)), a 15-turn scripted session:
   - every code block is kept;
   - only observations older than 10 turns are masked, in one batch;
   - the latest error stays;
   - the profile block stays verbatim.

## Done when
- [ ] The tests pass on recorded replies; `uv run pytest -q` and `uv run ruff check .` pass.
- [ ] A pre-registered eval meets its rule (below), and Aarmen sees the diff and the result.

## Measurement
- **Hypothesis:** masking observations older than 10 turns lowers input tokens per case by at least 30% on sessions long enough to mask, with no drop in repair F1 beyond the noise floor.
- **Suite and split:** `agent-clean-smoke`, dev (SC24 (#187)'s split once it exists).
  - Precondition: at least 10 cases run past 10 turns in the A/A run's recordings (EV15 (#78)).
  - If fewer do, the run can't inform the decision, and this waits for Stage 1's answer suite with long sessions. The registration says which.
- **Primary metric:** input tokens per case, p50 and p95, on cases that masked.
- **Guard metrics:**
  - repair F1 mean (SC4 (#90));
  - aborted cases;
  - turns per case (summaries lengthened runs in the paper);
  - false-backed rate, null until verdicts exist (say so).
- **Arms:** A, `dev` at the commit before; B, this change. Both `deepseek:deepseek-v4-pro`, careful autonomy, default caps.
- **Runs:** k = 3 per arm.
- **Decision rule:** keep if all three hold: B's input tokens per masked case fall by at least 30% at p50; repair F1 is within the noise floor; turns per case do not rise beyond the noise floor. Otherwise drop, or bring the failing cases to Aarmen.
- **Budget:** set by Aarmen after the dry run (D21: a pilot of 3 cases per arm, the cap from the pilot, aborted at 2x).

## Out of scope
- Changing the compaction prompt.
- Structured compaction from crivo's records (a later Stage 1 row).
- Claude-only server-side compaction (`compact_20260112`): beta, and one provider.
````

### B16. profile: per-type samples chosen for format variety, and samples dropped before columns

- **Labels:** task, behaviour
- **Placement:** not Stage 0. Stage 1 (what QUERY and CLEAN read is Stage 1's prompt and context work).
- **depends_on:** CT16 (#114, closed), SC24 (#187), EV15 (#78)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-table-agents-landscape.md`, §1.4 and ranked item 1.

## Type
behaviour

## Goal
The dataset profile shows each column the way its type is best read, and over budget it drops samples before it drops columns:
- a small categorical column: every category, with counts;
- other text: up to 10 distinct values chosen to cover different formats;
- object columns: a format-signature line;
- numbers and dates: min and max;
- URLs: no samples.

## Context
- **Sources:**
  - DataGovBench (arXiv 2607.06482, 2026-07-07), Table 4, on Gemini 2.5 Flash (GPT-4o followed the same pattern): the first 10 rows scored 0.310; adding schema statistics, 0.308; up to 200 rows, 0.275; a type-specific serialisation, 0.360.
  - Barke et al. (arXiv 2402.11734, NAACL 2024 Findings): rows picked from clusters of similar formatting beat random rows when formats vary, which is the messy-file case.
- **Today, `profile.py`:**
  - shows the first 3 non-null values in file order and the top 3 (`_row`, `nonnull.iloc[:_SAMPLES]`); on a messy export the head is often the cleanest part;
  - over budget, drops trailing columns (`... N columns omitted`), which the schema-linking literature calls the riskier failure.
- **No raw rows:** every shown value still passes CT16 (#114)'s masking and the per-value truncation. A list of up to 20 categories is still a truncated sample, but it sends more distinct values to the provider. SECURITY.md says so, and Aarmen decides whether that needs D15's privacy rule early.
- It changes what the model reads, so it is `behaviour`. `profile.py` is not a core file, but the diff goes to Aarmen with the result.

## Files
- `src/crivo/profile.py`
- `tests/test_profile.py`, `tests/test_perf_budget.py` (test-writer)
- `SECURITY.md` (the profile line)

## Steps
1. Text columns with 20 or fewer distinct values: all of them, with counts.
2. Other text columns:
   - a format signature per value (digits to `9`, letters to `a`, other characters kept);
   - up to 10 distinct values, one per signature, most common signatures first;
   - a line "shapes: `9999-99-99` x812, `99/99/9999` x40, ..." with counts.
3. Numbers and dates: min and max, as today where present. URL-typed columns (`semantic_types.py`): no samples.
4. Over budget, drop in this order, starting from the widest column: samples, then signatures. Every column keeps its name, type and null count; columns are dropped last.
5. Tests:
   - a mixed-date column shows both shapes;
   - a 12-category column lists all 12;
   - a PII-flagged column's samples stay masked;
   - the perf budget holds.

## Done when
- [ ] The tests pass, including a replayed turn that reads the profile from recorded replies; `uv run pytest -q` and `uv run ruff check .` pass.
- [ ] A pre-registered eval meets its rule (below), and Aarmen sees the diff and the result.

## Measurement
- **Hypothesis:** the type-specific profile raises repair F1 on the agent lane's dev split by more than the noise floor, with no rise in aborted cases or cost p95 beyond it.
- **Suite and split:** `agent-clean-smoke`, dev (SC24 (#187)'s split once it exists). Then Stage 1's answer suite, once it exists, as a second registration.
- **Primary metric:** repair F1 mean over all cases (SC4 (#90)).
- **Guard metrics:**
  - aborted cases;
  - input tokens per case, p95;
  - cost p95;
  - false-backed rate, null until verdicts exist (say so);
  - the injection suite's counts (CT25 (#218)) if it has landed, since more distinct values widen what planted text can reach.
- **Arms:** A, `dev` before; B, this change. Both `deepseek:deepseek-v4-pro`, careful autonomy, default caps.
- **Runs:** k = 3 per arm.
- **Decision rule:** keep if repair F1 rises by more than the A/A noise floor and no guard worsens beyond it. A gain inside the floor is not a win: drop the change, or re-register a narrower variant.
- **Budget:** set by Aarmen after the dry run (D21).

## Out of scope
- A key and cardinality block across several frames (the report's item 9; a later row).
- TOON or other serialisation formats (no bench result).
- The masked `peek` helper (Stage 1 toolbox).
````

### B17. intent: a host-side evaluator for postconditions written from the question

- **Labels:** task, code
- **Placement:** not Stage 0. Stage 1 (the referee's answer checks; waits on D10, the second path).
- **depends_on:** RE6 (#102), RE9 (#140), RE27 (#210)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-trustworthy-agents.md`, §2.2 and ranked item 2.

## Type
code

## Goal
A keyless module evaluates a small, closed set of postconditions (unit, range, sign, grain, required filter, totals that reconcile) against an answer's result on the host, and returns held, failed or could not check for each. A model-written postcondition can then lower a verdict without the host running model code.

## Context
- **Sources:**
  - nl2postcond (FSE 2024, arXiv 2310.01831): postconditions generated from natural language caught 64 historical Defects4J bugs.
  - TiCoder (TSE 2024, arXiv 2404.10100): tests that tell interpretations apart raised pass@1 by 45.97 points within 5 interactions.
  - Q* (arXiv 2601.00224) names back-translation, crivo's current intent check, "a key bottleneck".
- **Data, not code:** the postconditions are data in a closed JSON schema. The host interprets them; nothing the model writes runs on the host.
- **Downgrade-only:** a failed postcondition can make an answer not backed; a held one never raises a verdict.
- This row is the harness half, tested without a model. The call that writes the postconditions is B18 (behaviour).

## Files
- `src/crivo/postconditions.py` (new)
- `tests/test_postconditions.py` (new, test-writer)
- `docs/API-CONTRACT.md` (the schema)

## Steps
1. Schema: a list of `{kind, ...}` with these kinds. Unknown kinds read "could not check".
   - `range` (min, max);
   - `sign`;
   - `unit` (a label the result must carry);
   - `grain` (one row per value of a named column, or per period);
   - `filter` (a named column and value the result must be restricted to, checked from the result's own columns);
   - `reconcile` (the parts sum to the stated total within a tolerance).
2. `evaluate(postconditions, result) -> list[{kind, status, why}]`; `why` holds counts and names, never values.
3. A malformed list reads "could not check" as a whole. It is never an error that drops the answer.

## Done when
- [ ] Tests per kind for held, failed and could-not-check; a malformed list; no value appears in `why`.
- [ ] `uv run pytest tests/test_postconditions.py -q`, `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
None (a pure evaluator).

## Out of scope
- Writing the postconditions, alternative readings and asking (B18).
````

### B18. intent: a separate call writes postconditions from the question alone, and the host checks them

- **Labels:** task, behaviour, core
- **Placement:** not Stage 0. Stage 1; waits on D10 (the second path) and on Stage 1's answer suite.
- **depends_on:** B17, RE6 (#102), RE27 (#210), Stage 1's answer trap suite

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-trustworthy-agents.md`, §2.2 and ranked item 2.

## Type
behaviour

## Goal
Before an answer is shown, a separate model call writes postconditions in B17's schema, plus up to 3 alternative readings when the question is ambiguous. The call sees only the question and the masked profile, never the code or its output. The host evaluates the postconditions, and a failure makes the answer not backed.

## Context
- **Sources:** as on B17, plus Ambig-DS (arXiv 2605.09698), which names "silent misframing", and HiL-Bench's Ask-F1 (arXiv 2604.09408), which penalises both over-asking and silent guessing.
- **Today:** the intent check reads the code and judges whether it answers the question, a model judging model output. It stays, as a second, downgrade-only opinion.
- **Downgrade-only:** nothing here can raise a verdict; a model is never the deciding check. A wrong postcondition costs a backed answer, which shows in the backed rate.
- **No raw rows:** the call sees the question and the masked profile only.
- **D10** (Stage 1, Aarmen's): the second path is either derived by the referee or written by a separate model call. This is a separate call, and it must not be authored by the call that wrote the answer.
- Core: `prompts.py` (the new prompt), `loop.py` (the call and the verdict).

## Files
- `src/crivo/prompts.py` (core: the postcondition prompt)
- `src/crivo/loop.py` (core: the call, after the answer and before the card)
- `src/crivo/verify.py` (`answer_verdict` reads B17's results)
- `tests/test_loop.py`, `tests/test_verify.py` (test-writer, on recorded replies)

## Steps
1. After the answer turn, make one call with the question and the masked profile. The reply is B17's JSON plus `readings` (at most 3 short statements). A reply that does not parse reads "could not check".
2. Evaluate it on the host with B17, against the answer's result variable (pulled by RE9 (#140)).
3. `answer_verdict`:
   - any failed postcondition gives not backed, with the postcondition's `why`;
   - more than one reading gives partly backed, and the card lists the readings. Asking the person is Stage 1's clarify path.
4. Tests on recorded replies:
   - a postcondition that fails on the result gives not backed;
   - a held one leaves the verdict unchanged;
   - a malformed reply gives could not check.

## Done when
- [ ] The tests pass on recorded replies; `uv run pytest -q` and `uv run ruff check .` pass.
- [ ] A pre-registered eval meets its rule (below), and Aarmen sees the diff and the result.

## Measurement
- **Hypothesis:** the postcondition check turns at least 30% of the false-backed answers on the suite's dev split into not backed, while lowering the backed rate on correct answers by no more than the noise floor.
- **Suite and split:** Stage 1's answer trap suite, dev, built by authors who did not read the prompts or the referee. This can't be registered before that suite exists.
- **Primary metric:** false-backed rate (wrong among backed), with its Wilson interval.
- **Guard metrics:**
  - backed rate on correct answers;
  - ask rate, and Ask-F1 where readings diverge;
  - cost p95 (one more call per answer).
- **Arms:** A, Stage 1 `dev` without the call; B, with it. Both use `deepseek:deepseek-v4-pro` for the answer. The postcondition call runs on the same model unless Stage 1's bake-off names a cheaper one (the plan: adopted only if verdicts still agree).
- **Runs:** k = 3 per arm (5 at the stage gate, D19).
- **Decision rule:** keep if the false-backed rate falls, its Wilson upper bound does not rise, and the backed rate on correct answers falls by no more than the noise floor. Otherwise drop.
- **Budget:** set by Aarmen from the pilot (D21).

## Out of scope
- Removing the back-translation intent check.
- Clarify and abstain flows (Stage 1 rows).
- Computing an answer per reading.
````

### B19. clean: a datapackage.json sidecar beside every cleaned file says what crivo learned about it

- **Labels:** task, code
- **Placement:** Stage 1 outputs by default ("outputs to new files, versioned per gate"). It could be 0d platform, wave 3 or later, after PF11 (#154) and RE14 (#170), if Aarmen wants it in Stage 0.
- **depends_on:** PF11 (#154), RE14 (#170)

````markdown
From the 2026-10-23 research (#243): `docs/research/2026-10-23-table-agents-landscape.md`, §5 and ranked item 4.

## Type
code

## Goal
Next to each cleaned file crivo writes, a `<name>.datapackage.json` in Frictionless Table Schema v2 form lists each column's type, the missing-value tokens crivo cleared and the file's dialect. Other tools can then read the cleaned file's schema without re-inferring it.

## Context
- **The spec:** Frictionless Data Package v2 / Table Schema v2 (datapackage.org, released 2024-06-26; the spec is under the Unlicense). Fields with types, `missingValues`, `primaryKey`, `$schema` versioning, and Table Dialect.
- **No runtime dependency:** write the JSON by hand. frictionless-py (MIT) pulls in many dependencies, so it is used in tests only, if Aarmen allows it as a dev dependency.
- **Rule 8 (formats are promises):** a new file crivo writes carries `schema_version` and `versions` (S0-D25, through PF11 (#154)'s `formats.stamp`) and is written atomically. A new format in a user's repo is Aarmen's call.
- **No rows:** types, the sentinel tokens d04 cleared (tokens, not data values), counts. No category lists in v1, since they are data values; a later version may add them for non-PII columns if Aarmen agrees.
- After RE14 (#170), the host writes the cleaned file from the verified frame; the sidecar is written beside it.

## Files
- `src/crivo/datapackage.py` (new: `sidecar(frame, path, cleared_tokens) -> dict`, `write_sidecar`)
- the one call site RE14 (#170) leaves for the cleaned-file write (a 2-line diff; core if it is in `loop.py`)
- `tests/test_datapackage.py` (new, test-writer)
- `docs/API-CONTRACT.md` (the file, its keys and the type mapping)

## Steps
1. A type-mapping table, in the module and in the contract: pandas dtypes to Table Schema types (`integer`, `number`, `boolean`, `datetime`, `date`, `string`).
2. `sidecar` returns `{"$schema": ..., "schema_version": 1, "versions": formats.stamp(), "resources": [{"name", "path", "format", "schema": {"fields": [...], "missingValues": [...]}}]}`, with `dialect` for CSV output only.
3. `write_sidecar` uses `formats.atomic_write_text`.

## Done when
- [ ] Tests:
  - a cleaned frame's sidecar validates against Table Schema v2 and carries no cell value;
  - the d04 tokens a clean cleared appear under `missingValues`;
  - the write is atomic.
- [ ] `uv run pytest -q` and `uv run ruff check .` pass.

## Measurement
None.

## Out of scope
- PROV-O lineage names (raised on PF15 (#158)).
- ODCS contracts (Stage 1, D9).
- `primaryKey` candidates (they need a key rule; later).
````

---

## 4. (C) Notes, not filed

These go into #243's summary (`docs/research/2026-10-23-four-deep-dives-summary.md`), each with its reason.

**C1. TabClean-style guarded repair clauses (finding 15).** Not filed.
- Source: TabClean (arXiv 2606.25388; no licence, so ideas only). It reaches about 1.00 precision on all six Raha sets by writing each repair as a guarded clause (a dirty-pattern guard, a target-negative guard, an evidence guard and a scope guard) and committing a program only when it is safe on a dev set.
- crivo already enforces the target-negative half outside the model: RE21 (#205)'s target contract (S0-D9) refuses a fix that changes unflagged cells of its target column. That is the stronger form, because the referee checks it rather than the fix declaring it.
- The rest (fix code shaped as clauses; a clause committed as a skill only when it breaks no clean cell on held-out data) is Stage 2b skill design: fix and recipe skills, counterfactual rent. It is `behaviour`, spans `loop.py`, `skills.py` and `prompts.py`, and is well over 300 lines.
- Record it as input for the Stage 2b WRAP spec. B1's `broken` count is the metric it would use.

**C2. Positioning (finding 16).** Not filed.
- The research says: warehouse tools verify against curated reference queries (Databricks Genie's trusted assets, Snowflake Cortex's Verified Query Repository, Fabric's and Hex's evals), which a messy export never has. crivo produces its evidence per answer with nothing curated in advance. No MCP data server found returns a checked answer.
- AGENTS.md says a number not measured is not claimed, so the README and PRD wording waits for numbers. The public trap suite shaped like Hex's DataBench is already the plan's Stage 1 gate.
- Record it in the summary as the positioning to adopt once Stage 1's trap-suite numbers exist. The labs now use trust words ("validate", "trusted", "shows the query"), so the claim should be receipts, not adjectives.

**C3. MCP `structuredContent` and DuckDB agent-mode output (part of finding 17).** Not filed.
- The plan's Stage 1 already has "MCP on the 2026-07-28 spec" with "findings as structured objects, structured errors", and the toolbox's "`Session.peek` or a bounded result payload".
- Input for that spec:
  - an `outputSchema` and `structuredContent` for `ask`, `diagnose` and `clean_file`, sending text too for older clients;
  - explicit `truncated` flags with stated caps;
  - JSON error objects;
  - resource links to the card, lineage and report files;
  - a deterministic tool order, for prompt caching.
- DuckDB 2.0 is days old and its storage format is not backward-readable, so pin a range and avoid DuckDB files as outputs.
- Filing now would front-run the Stage 1 spec, and the MCP description is read by outside models (S0-D18 keeps MCP changes for Stage 1's port).

**C4. Licence and do-not-use list (finding 22).** Not filed. Recommended as a short "Key decisions" entry in `docs/ARCHITECTURE.md` if Aarmen wants it binding; otherwise it lives in the summary.
- **Don't take as a dependency, or copy code from:**
  - TabPFN 2.5 and later: non-commercial including its outputs, and the weights are login-gated.
  - AGPL or GPL code: TruffleHog, deepchecks, Desbordante, Zingg, Briefer, firejail, Mondrian, Jenga, TQA-Bench, and Unidecode (GPL-2.0+; use anyascii, ISC, or the standard library).
  - Share-alike or non-commercial licences: secrets-patterns-db and ASI's code (CC-BY-SA-4.0), AbstentionBench (CC-BY-NC).
  - Licences that are not OSI-approved: soda-core and Arize Phoenix (Elastic-2.0).
  - Profilers pinned to old pandas: fg-data-profiling (`pandas<3.0`), dataprep (`pandas<2.0`), recordlinkage (`pandas<3`).
  - Dormant agents: pandas-ai (pins `pandas<3`), Vanna (archived), LIDA, TaskWeaver (archived).
- **Ideas only, no code (no licence file):** TabClean, ZeroED, Auto-Test, LLM4DC, CleanAgent, REIN, MatchGPT, fm_data_tasks, Automatic-Data-Repair, Pytheas, the Auto-Tables benchmark, EvoDS, DataAgentBench, KramaBench, agentic-pbt, DataGovBench.
- **Fetch, never commit:** the "Clean Me If You Can" truth (ODbL share-alike).
- **Never the boundary or the defence:**
  - as a sandbox: Pyodide, RestrictedPython, WASM, audit hooks (PEP 578 says so), Jupyter's HMAC against the kernel;
  - as the injection defence: prompt-level filters and detectors (PromptGuard and the like, over 90% bypassed by adaptive attacks).
- **Never as a grader:** an LLM judge as the deciding check (DCA-Bench style), or LLM-labelled learned detectors (ZeroED, ForestED) in the library.
- **Watch, not used:** chardet's relicensing to MIT at 7.0.0 is disputed by its original author. CleverCSV depends on chardet, so prefer charset-normalizer for encoding detection.

---

## 5. What Aarmen must decide

1. **Answer number grounding (B2, B3): 0b wave 4 or Stage 1?** The plan's 0b list includes grounding; the Stage 0 spec's cut list moved it to Stage 1. The deterministic match needs no Stage 1 machinery. Also: does an unmatched number make an answer partly backed (as drafted) or not backed?
2. **File the hold and Stage 1 drafts (B10 to B19) now, or keep them as drafts?**
   - S0-D19's precedent is that recall work waits for SC24's split, "not filed".
   - The Stage 1 behaviour items (B15, B16, B18) need suites that don't exist yet.
   - Recommendation: file B1 and B4 to B9 now, and B2 and B3 once decision 1 is made. Keep B10 to B19 as drafts for S0-D19's recall wave and the Stage 1 WRAP spec.
3. **EDR: published or diagnostic?** (B1; it extends S0-D1's list of published numbers and so SC6's degenerate check.)
4. **A "debatable" truth label:** whether the scorer gets one, and the written rule for it (the comment on #126). It would not touch the 2026-09-02 Raha-marker decision unless he reopens it.
5. **New dependencies:** ftfy (B11); validators and phonenumbers or phonenumberslite (B10); optionally RapidFuzz and anyascii (B12). psutil needs no decision: it is already installed through ipykernel.
6. **Grades, once fixers or proof exist:** d08 to AUTO with a fixer (B11)? d21 to AUTO when arithmetic confirms (B13; it deletes rows, which autoclean never does unattended today)? Is d07's token-sorted key wanted as a GATE tier (B12)?
7. **The trust-weighted score's t** (B6), next to D19's ceiling.
8. **B7 is a core `loop.py` diff with a precision trade-off:** bare digit runs are left unmasked so ids and amounts survive, which means a PII value printed as bare digits is not masked.
9. **A shuffled-row referee check** (the comment on #206) would add referee failure text the model reads, so it would fall under S0-D14's eval (RE33).
10. **Profile v2 (B16) sends more distinct values to the provider.** Should D15's privacy rule (planned for Stage 4) come early?
11. **New formats in users' repos:** the datapackage sidecar (B19) and the PROV-O lineage names (the comment on #158). Now, or later under PF10's policy?
12. **Licences under D24's rule:** Pollock (MIT, fetch only) and the CMIYC slice (ODbL truth, fetch only) are recommended as such.
13. **CT4 (#148) as written may leave the `.env` binds open to a nested user namespace.** Not a choice, but it should be settled by the test the comment asks for before CT4 ships.
14. **The #242 addendum (A1) is optional.** The existing 2026-10-23 comment already carries the fix.
