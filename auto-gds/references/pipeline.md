# Per-story Pipeline

The orchestrator runs these phases **in order** for one GDS/BMGD story, then stops and reports.
Each delegated phase names a `delegation.md` entry and a `phase_profiles` key. The exact
installed GDS skill name lives only in `delegation.md`; this file owns phase order, gates, state
updates, and commit subjects.

Git/PR work is orchestrator-owned, not delegated. The orchestrator also owns state files, report
files, project-context probes, branch/commit/push/PR/final status handling, and final reporting.
Story implementation, story creation, code review, project context generation, and retrospective
work are delegated.

GDS testing workflow integration is **disabled by default in V0**. The old BMM/Test Architect
phases are not part of the default path and must not call the old testing commands. Future GDS mappings
may add dedicated entries such as `gds-test-design`, `gds-test-automate`, `gds-test-review`,
`gds-performance-test`, `gds-playtest-plan`, `gds-test-framework`, and `gds-e2e-scaffold`.

## Phase 0 — Preflight *(orchestrator)*

Runs during Step 1 of `SKILL.md`, before any commit.

- Verify this is a git repo, the starting tree is clean unless resuming on the correct story
  branch, git mode is known (`remote` when `gh` + GitHub remote are available, otherwise `local`),
  and the base branch is known.
- Verify required GDS/BMGD skills for the selected path exist:
  `gds-create-story`, `gds-dev-story`, `gds-code-review`; plus
  `gds-generate-project-context` when project context is missing or this is the last story of an
  epic; plus `gds-retrospective` when this is the last story of an epic.
- If `sprint-status.yaml` is missing under `<impl>`, hard-stop and tell the user to run
  `gds-sprint-planning` in the target game project.
- Reconcile runtime config drift:
  ```bash
  python3 {skill-root}/scripts/config_plan.py --check --config <auto_gds_dir>/config.yaml
  ```
  On additive drift, rerun with `--apply`. This may append missing shipped `profiles` or
  `phase_profiles` keys and restamp `profiles_source_version`; it must never overwrite user
  retunes. Surface `manual_review` items in the report.
- On custom-subagent hosts, check delegate freshness and reprovision if needed:
  ```bash
  python3 {skill-root}/scripts/render-agents.py --check --project-root "{project-root}" \
    --tools "<comma-joined target_tools>" --profiles "<auto_gds_dir>/config.yaml"
  ```
- Probe for `project-context.md`. Primary path is `<output_folder>/project-context.md` when the
  GDS config has `output_folder`; otherwise use the fallback output folder resolved in `SKILL.md`.
  If absent there, search under `<project_root>` while excluding VCS/build/cache directories:
  ```bash
  test -f <resolved_output_folder>/project-context.md || \
    find <project_root> -name 'project-context.md' \
      -not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/.venv/*' \
      -not -path '*/dist/*' -not -path '*/build/*' -not -path '*/.next/*' \
      -type f -print -quit | grep -q .
  ```
  Empty result sets `needs_project_context_bootstrap: true` in state.
- Record GDS config context in state/report when present: `project_name`, `primary_platform`,
  `game_dev_experience`, `communication_language`, and `document_output_language`.
- No commit.

## Phase 1 — Branch *(orchestrator)*

- Create or switch to `{git.branch_prefix}{e}-{s}-{slug}` (default `story/`).
- Initialize the state file at `<auto_gds_dir>/state/{key}.yaml`.
- Commit:
  `chore(story-{e}-{s}): start auto-gds pipeline`.

## Phase 2 — Project Context Bootstrap *(conditional) → `project_context`*

Runs only when Phase 0 set `needs_project_context_bootstrap: true`.

- Delegate `generate-project-context` with bootstrap intent.
- Commit:
  `docs(project-context): bootstrap`.
- Flip `needs_project_context_bootstrap` to `false` in state.

## Phase 3 — Create Story → `create_story`

- Delegate `create-story` for story `{e}-{s}`.
- Feed the delegate relevant retro notes and deferred work as described in `delegation.md`.
- Commit:
  `docs(story-{e}-{s}): create story context file`.

## Phase 4 — GDS Testing Placeholder *(disabled in V0)*

No default work runs here. Keep this phase as a stable future insertion point for GDS testing
design or playtest planning. Record it as skipped with reason `gds-testing-disabled` when it would
otherwise be in the active phase window.

## Phase 5 — Dev Story → `dev_story`

- Delegate `dev-story` with `<story_file>`.
- The delegate implements the story, writes/runs relevant tests, and moves the story to `review`.
- Commit:
  `feat(story-{e}-{s}): <one-line summary from the delegate>`.

## Phase 6 — GDS Testing Placeholder *(disabled in V0)*

No default work runs here. Keep this phase as a stable future insertion point for GDS automation,
performance checks, or playtest evidence. Record it as skipped with reason
`gds-testing-disabled`.

## Phase 7 — Code-Review Loop → `code_review_review`, `code_review_review_secondary`, `code_review_fix`

The loop uses `gds-code-review` for review passes and `gds-dev-story` for fixes to already
identified findings. It always ends at a human-in-the-loop checkpoint.

For each review iteration:

- Start with `code_review_review`. When `code_review.alternate_models` is true, alternate
  subsequent review passes with `code_review_review_secondary`.
- Delegate `code-review`; then verify persistence with:
  ```bash
  python3 {skill-root}/scripts/review_findings.py --story-file <story_file> --expect-min {N} \
    --deferred-work-file <impl>/deferred-work.md --story-key {key}
  ```
- If review findings did not persist, re-delegate once with the spec binding reinforced. If they
  still do not persist, stop with `needs-human`.
- Ask the user only for `[Review][Decision]` items that truly require a human product/design/
  security/asset call. Do not guess those decisions.
- Delegate `code-review fix` for fixable `[Review][Patch]` items and human-resolved decisions.
- Continue until the loop converges or reaches `code_review.max_iterations`.

At the checkpoint, ask whether to continue or stop. On Continue, detect external-review changes
with git only; if changes exist, commit them and delegate a fresh whole-story `code-review` to the
secondary reviewer. If a finding requires a real human design/product/security/asset decision,
return `needs-human` rather than guessing.

TODO: a future version may add a dedicated headless GDS review companion if the repository gains a
clear local pattern for companion skills. For V0, use `gds-code-review` with the autonomy
directive in `delegation.md`.

## Phase 7 Tail — GDS Testing Advisory *(disabled in V0)*

No default work runs here. Future versions may add story-scope GDS test review, performance, or
playtest advisory steps. Record it as skipped with reason `gds-testing-disabled`.

## Phase 8 — Epic End *(only if `is_last_in_epic`)*

Run these in order and commit the epic-end docs once at the end:
`docs(epic-{e}): project context, deferred-work archive, retrospective`.

1. **Project context refresh** → `project_context`
   - Delegate `generate-project-context`.
   - Feed accumulated Auto-GDS retro notes plus durable deferred-work constraints.
2. **Archive resolved deferred work** *(orchestrator-direct)*
   - Move only clearly resolved entries from `<impl>/deferred-work.md` into
     `<impl>/deferred-work-resolved.md`.
   - Keep uncertain or partially resolved items in the active ledger.
3. **Retrospective** → `retrospective`
   - Delegate `retrospective`, handing it `<auto_gds_dir>/retro-notes/epic-{e}.md` when present.
   - Capture any `Planning drift` line for the report. Planning re-sync is advisory; do not run
     corrective planning automatically.

## Phase 9 — Finalize *(orchestrator)*

- Ensure all phase artifacts are committed.
- Append the report section to `<auto_gds_dir>/reports/{key}.md`, commit it, and push/open a PR
  when `git.mode` is `remote`.
- Mark Auto-GDS state `done`.
- On a clean completion, advance the GDS/BMGD status to `done` in both:
  - `<story_file>` `Status:`;
  - `<impl>/sprint-status.yaml` entry for `{key}`.
- On a caveated completion, leave GDS/BMGD status at `review`.
- Commit the state finalization and any clean-completion status flips together:
  `chore(story-{e}-{s}): finalize (mark done + GDS status)`.
- If `git.offer_merge` is true, mode is `remote`, and the completion is clean, ask whether to
  merge the PR and execute the selected `gh pr merge` command.
- Return to `SKILL.md` Step 3 for the final report.
