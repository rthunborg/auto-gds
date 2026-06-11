# Config, State, Resume & First Run

Auto-GDS persists runtime files in the target game project, never in the module source repo.

## Config Sources

Four config surfaces exist in a BMad v6 target project — only the last is Auto-GDS-owned:

- `_bmad/config.toml` / `_bmad/config.user.toml` — central BMad config (team scope / user
  scope), written by the **BMad installer**; module registration lives under `[modules.agds]`.
  Read-only for Auto-GDS. Never read or require `_bmad/config.yaml`.
- `_bmad/agds/config.yaml` — the installed module's carry-forward config, written by the
  installer. **Not** the orchestrator runtime config; never read it for runtime settings.
- `_bmad/gds/config.yaml` — GDS project config (paths, project metadata). Read-only.
- `<auto_gds_dir>/config.yaml` — the Auto-GDS runtime config described below: the only config
  Auto-GDS writes.

Resolve the runtime directory from the GDS config:

1. Read `_bmad/gds/config.yaml`.
2. If `output_folder` is present, resolve it and use `{output_folder}/auto-gds`.
3. If `output_folder` is absent, use `{project-root}/_bmad-output/auto-gds`.

This resolved path is referred to below as `<auto_gds_dir>`.

```
<auto_gds_dir>/
  config.yaml
  state/{key}.yaml
  retro-notes/epic-{e}.md
  reports/{key}.md
```

## Runtime Config

```yaml
version: 1
profiles_source_version: "0.13.4"  # agds module version whose assets/agents/profiles.yaml seeded profiles
delegation:
  host: auto
  mode: auto
  target_tools:
    - claude-code
    - codex
testing:
  enabled: false          # V0 default; old BMM Test Architect commands do not run
  future_gds_mapping:
    - gds-test-design
    - gds-test-automate
    - gds-test-review
    - gds-performance-test
    - gds-playtest-plan
    - gds-test-framework
    - gds-e2e-scaffold
git:
  mode: auto
  branch_prefix: "story/"
  base_branch: main
  offer_merge: true
  ci_wait_minutes: 30
code_review:
  max_iterations: 3
  alternate_models: true
profiles: {…}        # agds-xhigh | agds-high | agds-alt-xhigh | agds-alt-high
phase_profiles: {…}  # create_story, dev_story, code_review_review,
                     # code_review_review_secondary, code_review_fix,
                     # retrospective, project_context
```

`assets/agents/profiles.yaml` is the single shipped source for `profiles` and `phase_profiles`.
First run copies those blocks into `<auto_gds_dir>/config.yaml`. `config_plan.py` can additively
heal missing shipped keys after a module update, and `reset-defaults` can restore shipped profile
defaults without touching user setup answers.

## First-Run Flow

The first run happens only when `<auto_gds_dir>/config.yaml` is absent.

1. Confirm `target_tools` using the same detection rules as `assets/module-setup.md` — the
   detected set unioned with any `[modules.agds].target_tools` from the central TOML. Detection
   takes precedence: the installer's recorded value is a static default that cannot know the
   host, so it must never narrow the detected set.
2. Seed `delegation`, `profiles`, and `phase_profiles` from shipped defaults.
3. Set `testing.enabled: false`. V0 does not ask to enable the old BMM Test Architect workflow,
   and it must not run those commands by default.
4. Ask Quick vs Full:
   - Quick: keep default git and code-review settings.
   - Full: allow `git.mode`, `git.branch_prefix`, `git.offer_merge`,
     `code_review.max_iterations`, and `code_review.alternate_models`.
5. Write `<auto_gds_dir>/config.yaml`, creating parent directories as needed.
6. Render the delegate agents for the confirmed `target_tools` (the BMad installer does not do
   this):
   ```bash
   python3 {skill-root}/scripts/render-agents.py --project-root "{project-root}" \
     --tools "<comma-joined target_tools>" --profiles "<auto_gds_dir>/config.yaml"
   ```
   Surface any warnings from the JSON result.
7. Stop for a fresh session. On custom-subagent hosts, tell the user to fully quit and relaunch
   before running `/auto-gds`; a clear/new chat does not reload newly rendered agents.

Also capture GDS context from `_bmad/gds/config.yaml` for state/report use when present:
`project_name`, `planning_artifacts`, `implementation_artifacts`, `output_folder`,
`project_knowledge`, `primary_platform`, `game_dev_experience`, `communication_language`, and
`document_output_language`.

## reset-defaults

`/auto-gds reset-defaults [scope]` discards retunes in `<auto_gds_dir>/config.yaml` and re-seeds
the asset-sourced blocks from `{skill-root}/assets/agents/profiles.yaml`.

Scopes:

- omitted: both `profiles` and `phase_profiles`
- `profiles`
- one shipped profile name such as `agds-high`
- `phase_profiles`

Boundary: reset-defaults touches only `profiles`, `phase_profiles`, and
`profiles_source_version`. It never touches `delegation`, `testing`, `git`, or `code_review`.

Plan:

```bash
python3 {skill-root}/scripts/config_plan.py --reset <scope> --config <auto_gds_dir>/config.yaml
```

On confirmation, rerun with `--write`. If `render_needed` is true, reprovision agents and surface
the process-restart caveat from `delegation-runtime.md`.

## State File

State files live at `<auto_gds_dir>/state/{key}.yaml`. They are machine-readable and should always
emit explicit values for known fields.

```yaml
story_key: 1-2-user-auth
epic_num: 1
story_num: 2
branch: story/1-2-user-auth
status: in-progress
updated_at: "2026-05-28T14:04:41Z"
started_at: "2026-05-28T13:55:02Z"
completed_at: null
active_seconds: 0
is_first_in_epic: false
is_last_in_epic: false
needs_project_context_bootstrap: false
project_name: null
primary_platform: null
game_dev_experience: null
communication_language: null
document_output_language: null
git_mode: remote
base_branch: main
epic_story_count: 12
completed_phases: [0, 1, 3, 5]
code_review_iterations: 1
code_review_loop_done: false
external_review_iterations: 0
convergence_unverified: false
testing:
  enabled: false
  ran: []
commits: []
deferred_work_archived: 0
planning_drift: []
pr_url: null
ci_run_url: null
ci_status: unknown
pr_merged: false
merge_method: null
merge_commit: null
branch_deleted: false
open_questions: []
deferred_work: []
blockers: []
overrides: {}
constraints: []
```

Update state after every phase. `started_at` is stamped once. `active_seconds` accumulates
execution time across resumes; user-wait time is excluded.

## Target Selection & Resume Logic

No-arg `/auto-gds` chooses the target story with this precedence:

1. Resume an incomplete Auto-GDS pipeline first:
   ```bash
   python3 {skill-root}/scripts/state_plan.py --state-dir <auto_gds_dir>/state
   ```
   If any state file has `status != done`, resume the most recently updated one and mention any
   extras in the report.
2. Otherwise ask `story_plan.py` for the next GDS story:
   ```bash
   python3 {skill-root}/scripts/story_plan.py --sprint-status <impl>/sprint-status.yaml --impl-dir <impl>
   ```
   Precedence is `in-progress -> review -> ready-for-dev -> backlog -> retrospective`.

An explicit `--story <arg>` goes to `story_plan.py --story <arg>`.

Once the target key is known, check exact state:

```bash
python3 {skill-root}/scripts/state_plan.py --state-dir <auto_gds_dir>/state --story-key {key}
```

`resume: true` means continue from the first phase not in `completed_phases`. A `done` state means
the story is already complete unless the user explicitly forces a rerun.

## Retro Notes

`<auto_gds_dir>/retro-notes/epic-{e}.md` is a signal-only scratchpad for future stories and the
epic retrospective. Append only meaningful delegate `Retro notes`; skip `none` or routine success
recaps.

```markdown
## Story {key}
- [Phase 5 — dev-story] <one terse note>
```

## Reports

`<auto_gds_dir>/reports/{key}.md` is an append-only per-story report log. On a clean path it is
written and committed before push so it ships in the PR. On halted paths, `SKILL.md` writes it as
a fallback without committing.

Each run appends a new section. Never overwrite except for an explicit full rerun of an already
`done` story after user confirmation.

### Section Template

```markdown
## Report — <ISO timestamp UTC> (<disposition tag>)

**Story:** `{key}` (epic {e}, story {s}) — {first-in-epic? / last-in-epic? / mid-epic}.
**Branch:** `<branch>` (HEAD `<short-sha>`).
**Pipeline status:** <clean completion / halted at Phase N / draft reason / caveated reason>.
**Continues:** <prior section timestamp and tag, or `(none — first run)`>.

**Timing:** started <ISO>; completed <ISO, or "in progress"> — elapsed <Hh Mm> (≈<Hh Mm> AI-run, ≈<Hh Mm> human/idle wait)<; resumed N× if >1 session>.

**Phases run:** <comma-joined Phase N list for this session, with profile names for delegated phases>.
**Skipped:** <comma-joined Phase N list with reason>.

**Overrides:** <one line; "none" if no invocation overrides applied>.

**Testing:** disabled in V0 unless explicitly enabled by future Auto-GDS config; list any future GDS testing steps that ran.

**Code review:** <iterations run; per-iteration verdict + severity counts; HITL outcome; external-change re-review outcome if any>.

**Open questions:** <numbered list, or "(none)">.

**Deferred work:** <numbered list, or "(none)">.

**Planning drift:** <epic-end only; "(none)" if clean or not epic-end>.

**Needs human:** <numbered list of blockers/manual actions, or "(none)">.

**Next:** <next story preview only>.
```
