# Per-story pipeline

The orchestrator runs these phases **in order** for a single story. Each phase: check its
condition → delegate to the named `ab-*` profile with the prompt from `delegation.md` (spawn it
for the current host/tier per `delegation-runtime.md`) → read the result → if
`blocked`/`needs-human`, stop and report → else append retro notes, **commit** (see
`git-and-pr.md`), and update the state file (see `state-and-resume.md`).

Placeholders: `{e}`/`{s}` = epic/story number, `{key}` = full story key (e.g.
`1-2-user-auth`), `{slug}` = the title part, `<impl>` = `implementation_artifacts` dir,
`<story_file>` = `<impl>/{key}.md` (from `story_plan.py`).

---

## Phase 0 — Preflight & triage  → `ab-fast`
Runs during Step 1 of the SKILL procedure (before any commit).
- Verify required skills exist for the selected path. Missing → hard-stop.
- Git preflight (delegate): is this a git repo? is the working tree clean? detect git mode
  (gh installed AND a GitHub remote → `remote`; else `local`); detect the base branch.
  Dirty tree on a non-story branch → hard-stop.
- **Triage (only if `tea.enabled`)**: classify the story `low | med | high` and choose the
  per-story TEA set using `tea-policy.md`. Record `tea_selected` (e.g. `[atdd, automate]`,
  or `[]` for trivial) in state.
- No commit (nothing changed yet). Persist decisions to state.

## Phase 1 — Branch  → `ab-fast`
- Ensure we are NOT on the base branch. Create/checkout `{branch_prefix}{e}-{s}-{slug}`
  (default `story/{e}-{s}-{slug}`). If the branch already exists (resume), check it out.
- Write the initial state file and commit it:
  `chore(story-{e}-{s}): start auto-bmad pipeline`.

## Phase 2 — Epic start  *(only if `is_first_in_epic` AND `tea.enabled`)*  → `ab-high`
- Delegate `/bmad-testarch-test-design` at **epic level** for epic `{e}`.
- Commit: `test(epic-{e}): epic-level test design`.
- (If `tea.enabled` is false, skip. Non-TEA epic-start work is already handled by
  sprint-planning having been run; nothing else is needed here.)

## Phase 3 — Create story  → `ab-xhigh`
- Delegate `/bmad-create-story {e}-{s}`. The skill self-validates against its checklist and
  auto-fixes; do NOT add a separate validate pass.
- Capture any open questions the skill saved → retro notes + report.
- Commit: `docs(story-{e}-{s}): create story context file`.

## Phase 4 — Pre-dev TEA  *(only if `tea.enabled` AND `atdd ∈ tea_selected`)*  → `ab-fast`
- Delegate `/bmad-testarch-atdd` with `<story_file>`.
- Commit: `test(story-{e}-{s}): ATDD acceptance scaffolds (red)`.

## Phase 5 — Dev story  → `ab-max`
- Delegate `/bmad-dev-story <story_file>`. Fully autonomous; it runs tests and moves the story
  to `review`.
- Capture deviations / deferred work / decisions → retro notes.
- Commit: `feat(story-{e}-{s}): <one-line summary from the agent>`.
  (If the dev agent reports it cannot complete — missing secret, external service, manual
  step — that is `needs-human`: stop and report.)

## Phase 6 — Post-dev TEA  *(only if `tea.enabled` AND `automate ∈ tea_selected`)*  → `ab-fast`
- Delegate `/bmad-testarch-automate` with `<story_file>`.
- Commit: `test(story-{e}-{s}): expand automated coverage`.

## Phase 7 — Code-review loop  (≤ `code_review.max_iterations`, default 3)
Iterate until the review **Approves** / has no remaining Critical or High findings, or the cap
is hit. Track `code_review_iterations` in state (so resume continues mid-loop).

For iteration `i` (1-based):
1. **Reviewer profile** — **always start with opus.** When `code_review.alternate_models` is
   true: odd `i` → `ab-xhigh` (opus), even `i` → `ab-fast` (sonnet) — so iter 1 = opus, iter 2
   = sonnet, iter 3 = opus. When alternation is off, every iteration is `ab-xhigh` (opus).
   Delegate `/bmad-code-review` targeting the branch diff for `<story_file>`. The skill writes a
   review section + `[AI-Review]` follow-up tasks into the story file.
2. Read the verdict (Approve / Changes Requested / Blocked) and Critical/High/Med/Low counts.
   Each pass **always fixes what it finds**: when findings are present, delegate the fix to
   `ab-max` (`/bmad-dev-story <story_file>` focused on the `[AI-Review]` follow-up tasks) and
   commit `fix(story-{e}-{s}): address code review (iter {i})`. What happens next depends on the
   **severity this pass found** (the findings it just fixed):
   - **No findings** → commit `chore(story-{e}-{s}): code review passed (iter {i})` and exit.
   - **Only Med/Low (no Critical or High)** → the fixes are in and nothing high-risk surfaced;
     exit the loop and continue the pipeline (no need to ask).
   - **Any Critical or High** → they were fixed, but the fix is unverified and such findings can
     recur, so re-review: if `i < cap`, continue to iteration `i+1`; if `i == cap`, go to step 3.
3. **Cap reached while the last pass was still finding (and fixing) Critical/High → ASK the user**
   (AskUserQuestion); do not silently proceed. Nothing is left unresolved — each pass fixed its
   findings — but because the final pass was still surfacing Critical/High, convergence is
   unverified. (This is mid-pipeline — the PR doesn't happen until Phase 9, after the epic-end
   Phase 8.) Summarize the Critical/High the last pass fixed, then offer:
   - **Run another review+fix iteration** *(recommended)* — continue beyond the cap with the
     **opus** reviewer (`ab-xhigh`) + `ab-max` fix, to verify the fixes and drive any remaining
     Critical/High to zero. Repeat this ask after each extra iteration until a pass comes back
     clean or Med/Low-only, or the user stops.
   - **Accept the fixes and continue the pipeline** — trust the fixes already applied; set
     `convergence_unverified: true` in state, then proceed normally to Phase 8 (if last story) and
     Phase 9. Because that flag is set, Phase 9 opens the PR as a **draft** (or, in local mode,
     just notes it).
   - **Stop the pipeline now** — skip the remaining phases, go straight to the report (Step 3);
     commits stay on the branch, nothing is pushed and no PR is opened. The last pass's findings
     are reported as `needs-human`.
   Record the user's choice and any extra iterations in state (`code_review_iterations`).

## Phase 8 — Epic end  *(only if `is_last_in_epic`)*
Run these in order; commit once at the end: `docs(epic-{e}): gate, project context, retrospective`.
1. **TEA gates (only if `tea.enabled`; epic-level skills are always on here):** delegate via
   `ab-high`, in order: `/bmad-testarch-trace` (capture PASS/CONCERNS/FAIL/WAIVED),
   `/bmad-testarch-nfr`, `/bmad-testarch-test-review`. Record the gate decision in state +
   report.
2. **Project context:** delegate `/bmad-generate-project-context` via `ab-fast`.
3. **Retrospective:** delegate `/bmad-retrospective` via `ab-high`, handing it the accumulated
   `_bmad-output/auto-bmad/retro-notes/epic-{e}.md` as primary input. It runs autonomously and
   writes the retro doc + flips the retrospective status to `done`.

## Phase 9 — Finalize  → `ab-fast`
- Ensure everything is committed (no dirty tree).
- **git mode `remote`:** push the branch and open a PR via `gh pr create` (see `git-and-pr.md`).
  Make it a **draft** if any blocker was recorded, or `convergence_unverified` is `true` (the
  user chose to accept the fixes and ship in Phase 7 despite the cap being hit while Critical/High
  were still surfacing). PR body = conventional summary + link to the story file +
  a checklist of open questions / deferred work / human-action items. If the repo has CI
  workflows, also capture the triggered CI run link into `ci_run_url` (see `git-and-pr.md`) — do
  not wait for it to finish.
- **git mode `local`** (or the user chose "stop without a PR" in Phase 7): skip the PR; leave the
  branch in place and note it in the report.
- Mark the state file `done` (record `pr_url`, `ci_run_url`, final `branch`, any `blockers`).
- Hand control back to the SKILL's Step 3, which **writes the report to
  `_bmad-output/auto-bmad/reports/{key}.md`** and prints it.
