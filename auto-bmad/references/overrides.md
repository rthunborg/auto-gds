# Invocation overrides

The user can steer a single run by adding instructions to the invocation — natural language
(primary) or flags. Examples: `/auto-bmad stop before code-review`,
`/auto-bmad --story 1-3 skip git commits`, `/auto-bmad start at phase 5`,
`/auto-bmad skip TEA, max 5 review iterations`, `/auto-bmad dry run`.

Parse the invocation text into the **normalized override set** below, **echo the interpretation
back to the user before running**, and record it in state (`overrides:`) and the report.
Overrides apply to **this run only** — never write them to `config.yaml`. Neither `--story` **nor
`--epic`** is an override; both are **target selectors** (mutually exclusive — `--story` picks one
story, `epic` / `--epic N` runs a whole epic; see "Epic mode" below).

## Phase map (names ↔ numbers)

| # | Phase | Common aliases |
|---|-------|----------------|
| 0 | Preflight & triage | preflight, triage |
| 1 | Branch | branch |
| 2 | Epic start (epic test design) | epic-start, test-design |
| 3 | Create story | create-story, story |
| 4 | Pre-dev TEA (ATDD) | atdd |
| 5 | Dev story | dev, dev-story, implement |
| 6 | Post-dev TEA (automate) | automate |
| 7 | Code-review loop | code-review, review |
| 8 | Epic end (gates / context / retro) | epic-end, gates, retro, retrospective |
| 9 | Finalize (push / PR / hand off) | finalize, pr |

## Normalized override set

- `start_phase: <0–9>` — begin here; treat earlier phases as skipped. **Validate prerequisites**
  (below) and hard-stop if they're missing.
- `stop_before: <phase>` / `stop_after: <phase>` — end the run at that boundary, then go straight
  to the report (Step 3).
- `skip: [...]` — any of: a phase number/name, or the features `git-commits`, `pr`, `tea`,
  `code-review`, `retrospective`, `branch`, `merge-prompt`, `project-context-bootstrap`,
  `trace-advisory`, `uat`.
- `max_review_iterations: <int>` — override `code_review.max_iterations` for this run.
- `git_mode: local` — force local mode (no push/PR), regardless of detection.
- `no_pr_draft: true` — open a normal (non-draft) PR even if blockers were recorded. (Also set
  mid-run by the Phase 7 re-ask's **Continue (ship as ready)** option — see `pipeline.md`.)
- `dry_run: true` — resolve everything and print the plan; execute nothing.

## How each maps to the pipeline

- **start_phase / stop_*:** define the active window.
  - Run a phase only if it's within `[start_phase, stop_after]` (inclusive) and before any
    `stop_before`.
  - Phases outside the window are recorded as skipped in state with the reason `override`.
- **skip git-commits:** run phases but perform **no** per-phase checkpoint commits and **no** PR — a
  PR needs commits.
  - Leave all changes in the working tree for the user to commit.
  - ⚠️ This removes the commit-based resume safety net — say so in the echo and report.
  - The state file is then the only resume record.
- **skip pr** / **git_mode local:** Phase 9 pushes/opens nothing; the branch is left in place and
  noted in the report.
- **skip tea:** treat `tea.enabled` as false for this run.
  - Skips Phases 4 and 6, Phase 2's *test-design sub-step*, and the epic-end TEA gates in Phase 8.
  - Project-context and retrospective still run.
  - Phase 2's project-context-bootstrap sub-step is TEA-independent — it runs when needed.
- **skip project-context-bootstrap:** suppress only Phase 2's project-context bootstrap sub-step,
  even when `needs_project_context_bootstrap` is true.
  - Use sparingly — every create-story in the epic will then run without persistent_facts injection
    (see Phase 0 → "Project-context probe").
- **skip code-review:** skip Phase 7 entirely AND set `convergence_unverified: true`.
  - Zero review passes is the strongest form of unverified, so the PR opens as a **draft** and the
    story stays at `review` (draft-predicate clause 2).
  - Combine with `no_pr_draft` to ship non-draft anyway — the story still stays at `review`.
  - ⚠️ Quality gate removed — flag prominently.
- **skip retrospective:** skip only the retrospective sub-step of Phase 8.
- **skip trace-advisory:** suppress only the Phase 7 tail per-story trace advisory for this run,
  even when its conditions hold (see `tea-policy.md` §3).
  - The epic-end trace gate is unaffected.
- **skip uat:** suppress the manual UAT checklist step (Phase 9 head per story; epic E5 per story +
  the E_final consolidation).
  - The report's **UAT** section then renders `(none)`.
  - Nothing else is affected — it is a read-only hand-off artifact, not a gate.
- **skip branch:** stay on the current branch (do not create `story/...`).
  - Only sensible with a clean intent like a dry run, or when the user is already on the right
    branch.
  - Warn otherwise.
- **skip merge-prompt:** same shape as `git.offer_merge: false`, just for this run.
  - Phase 9 still pushes and opens the PR.
  - It does **not** wait for CI.
  - It does **not** ask whether to merge.
  - `ci_status` is recorded as `unknown`; the existing draft-predicate clauses 1–3 (no CI gate)
    decide draft vs non-draft.
  - The PR stays open for the human to merge on their own time.
- **max_review_iterations / no_pr_draft:** adjust Phase 7 cap / Phase 9 draft decision.

## Epic mode (`/auto-bmad epic`)

`epic` / `--epic N` is a **target selector** (like `--story`), not an override: it runs a whole epic
via `epic-pipeline.md`. `--story` and `epic` are **mutually exclusive** — hard-stop if both are given
("`--story` picks one story; `epic` runs a whole epic — pick one").

Overrides that **compose** with epic mode (echo + apply the same way):
- `dry_run` — prints the epic plan + the ordered story list + per-step profiles, then stops.
- `skip tea`.
- `skip merge-prompt`.
- `git_mode local`.
- `max_review_iterations` — caps the **E_review** loop.
- `no_pr_draft` — the epic PR opens non-draft; the epic still stays caveated.
- `skip git-commits`.
- `skip uat` — suppresses the per-story UAT step AND the E_final consolidation.
- `skip code-review`:
  - Skips the **Tier-B** epic integration review (equivalent to `code_review.epic_review: false`).
  - AND sets `convergence_unverified`.
  - The per-story **Tier-A** thin review is then the only quality gate left, for **every** story.
  - Flag it even more prominently than per story — it compounds across the epic.

Overrides that **do NOT map** — reject in epic mode for v1, with a precise message:
- The per-story **phase window** (`start_phase` / `stop_before` / `stop_after`).
- Phase-number `skip`s.
- Reason: the phase map above is per-**story**-run; epic mode runs **E-steps** (`epic-pipeline.md`),
  a different axis.

Resume an interrupted epic with `/auto-bmad epic --epic N` — the epic anchor drives where it picks up.

## Prerequisite validation for `start_phase`

Starting mid-pipeline requires the earlier outputs to already exist. Before skipping ahead, check
the applicable prerequisite(s) below and **hard-stop with a precise message** if any is missing:
- start at **5 (dev-story)** or later → the story context file (`<impl>/{key}.md`) must exist
  (Phase 3 output).
- start at **7 (code-review)** or later → the story must be implemented (code present; story at
  `review`).
- start at **9 (finalize)** → there must be commits on the story branch to push.

Prefer the normal resume path (`state-and-resume.md`) over `start_phase` when a state file exists.
Use `start_phase` for deliberate manual control.

## Echo format (always show before executing)

> **Overrides for this run:** start=Phase 5 (dev-story); stop after Phase 7; skipping
> git-commits (⚠️ no checkpoint commits — resume relies on the state file only); max review
> iterations = 5.
> **Phases that will run:** 5 → 6 → 7. **Will not run:** 0–4, 8, 9.

If `dry_run`, print this plan (plus the resolved target story and per-phase profiles) and stop
without executing.
