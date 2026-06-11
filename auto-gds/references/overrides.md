# Invocation overrides

The user can steer a single run by adding instructions to the invocation — natural language
(primary) or flags. Examples:
`/auto-gds stop before code-review`, `/auto-gds --story 1-3 skip git commits`,
`/auto-gds start at phase 5`, `/auto-gds skip testing, max 5 review iterations`,
`/auto-gds dry run`.

Parse the invocation text into the **normalized override set** below, **echo the interpretation
back to the user before running**, and record it in state (`overrides:`) and the report
(`dry_run` excepted — a dry run writes no state).
Overrides apply to **this run only** — never write them to `config.yaml`. `--story` is not an
override; it is the existing target selector.

## Phase map (names ↔ numbers)

| # | Phase | Common aliases |
|---|-------|----------------|
| 0 | Preflight & triage | preflight, triage |
| 1 | Branch | branch |
| 2 | Project context bootstrap | project-context, context |
| 3 | Create story | create-story, story |
| 4 | GDS testing placeholder (disabled in V0) | testing, test-design |
| 5 | Dev story | dev, dev-story, implement |
| 6 | GDS testing placeholder (disabled in V0) | testing, automate |
| 7 | Code-review loop | code-review, review |
| 8 | Epic end (context / retro) | epic-end, context, retro, retrospective |
| 9 | Finalize (push / PR / hand off) | finalize, pr |

## Normalized override set

- `start_phase: <0–9>` — begin here; treat earlier phases as skipped. **Validate prerequisites**
  (below) and hard-stop if they're missing.
- `stop_before: <phase>` / `stop_after: <phase>` — end the run at that boundary, then go straight
  to the report (Step 3).
- `skip: [...]` — any of: a phase number/name, or the features `git-commits`, `pr`, `testing`,
  `code-review`, `retrospective`, `branch`, `merge-prompt`, `project-context-bootstrap`,
  `testing-advisory`.
- `max_review_iterations: <int>` — override `code_review.max_iterations` for this run.
- `git_mode: local` — force local mode (no push/PR), regardless of detection.
- `no_pr_draft: true` — open a normal (non-draft) PR even if blockers were recorded.
- `dry_run: true` — resolve everything **read-only** and print the plan (target story, phase
  window, per-phase profiles); execute nothing — no branch, no commits, no PR, no delegate
  spawns, no GDS skill runs, no state/config writes. If the runtime config is missing, plan
  from the shipped defaults in memory instead of triggering the first-run flow.

## How each maps to the pipeline

- **start_phase / stop_*:** define the active window. Run a phase only if it's within
  `[start_phase, stop_after]` (inclusive) and before any `stop_before`. Phases outside the window
  are recorded as skipped in state with the reason `override`.
- **skip git-commits:** run phases but perform **no** per-phase checkpoint commits and **no** PR
  (a PR needs commits). Leave all changes in the working tree for the user to commit. ⚠️ This
  removes the commit-based resume safety net — say so in the echo and report; the state file is
  then the only resume record.
- **skip pr** / **git_mode local:** Phase 9 pushes/opens nothing; the branch is left in place and
  noted in the report.
- **skip testing:** no-op in V0 because GDS testing integration is already disabled by default.
  Keep it for forward compatibility with future `gds-test-*` mappings.
- **skip project-context-bootstrap:** suppress only Phase 2's project-context bootstrap sub-step,
  even when `needs_project_context_bootstrap` is true. Use sparingly — every create-story in the
  epic will then run without persistent_facts injection (see Phase 0 → "Project-context probe").
- **skip code-review:** skip Phase 7 entirely. ⚠️ Quality gate removed — flag prominently.
- **skip retrospective:** skip only the retrospective sub-step of Phase 8.
- **skip testing-advisory:** no-op in V0. Future versions may use it to suppress non-blocking
  story-scope GDS test review, performance, or playtest advisories.
- **skip branch:** stay on the current branch (do not create `story/...`). Only sensible with a
  clean intent like a dry run or when the user is already on the right branch; warn otherwise.
- **skip merge-prompt:** Phase 9 still pushes and opens the PR, but does **not** wait for CI and
  does **not** ask whether to merge — same shape as `git.offer_merge: false`, just for this run.
  `ci_status` is recorded as `unknown` and the existing draft-predicate clauses 1–3 (no CI gate)
  decide draft vs non-draft. PR stays open for the human to merge on their own time.
- **max_review_iterations / no_pr_draft:** adjust Phase 7 cap / Phase 9 draft decision.

## Prerequisite validation for `start_phase`

Starting mid-pipeline requires the earlier outputs to already exist. Before skipping ahead,
check and **hard-stop with a precise message** if a prerequisite is missing:
- start at **5 (dev-story)** or later → the story context file (`<impl>/{key}.md`) must exist
  (Phase 3 output).
- start at **7 (code-review)** or later → the story must be implemented (code present; story at
  `review`).
- start at **9 (finalize)** → there must be commits on the story branch to push.
Prefer the normal resume path (`state-and-resume.md`) over `start_phase` when a state file
exists — resume already knows what's done. Use `start_phase` for deliberate manual control.

## Echo format (always show before executing)

> **Overrides for this run:** start=Phase 5 (dev-story); stop after Phase 7; skipping
> git-commits (⚠️ no checkpoint commits — resume relies on the state file only); max review
> iterations = 5.
> **Phases that will run:** 5 → 6 → 7. **Will not run:** 0–4, 8, 9.

If `dry_run`, print this plan (plus the resolved target story and per-phase profiles) and stop
without executing.
