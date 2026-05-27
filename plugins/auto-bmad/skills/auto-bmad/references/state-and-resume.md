# Config, state, resume & first-run

Everything auto-bmad persists lives under `{project-root}/_bmad-output/auto-bmad/`:

```
_bmad-output/auto-bmad/
  config.yaml                 # project config (created on first run)
  state/{key}.yaml            # one resumable state file per story
  retro-notes/epic-{e}.md     # accumulated notes feeding the epic retrospective
  reports/{key}.md            # the final per-story report (written in Phase 9 / SKILL Step 3)
```

## config.yaml
```yaml
version: 1
tea:
  enabled: true            # set at first run after checking TEA skills exist
  framework_ci: prompt     # prompt | done | skip  (resolved at first run)
git:
  mode: auto               # auto -> detect; or force "remote" / "local"
  branch_prefix: "story/"
  base_branch: main        # auto-detected; written after first detection
code_review:
  max_iterations: 3
  alternate_models: true   # odd iters ab-xhigh (opus), even iters ab-sonnet (sonnet)
profiles:                  # phase -> agent profile (defaults; user may retune)
  create_story: ab-xhigh
  dev_story: ab-max
  code_review_review: ab-xhigh
  code_review_fix: ab-max
  tea_per_story: ab-sonnet
  tea_epic: ab-high
  retrospective: ab-high
  project_context: ab-sonnet
  ops: ab-sonnet
```

## First-run flow (only when config.yaml is absent)
This is the single interactive moment in normal operation. Use AskUserQuestion:
1. **Detect TEA availability:** check that the TEA skills (`bmad-testarch-*`) are installed.
2. **Ask `tea.enabled`** — default to "yes" if TEA skills are present, "no" if absent (and if
   absent, don't offer yes).
3. **If TEA enabled, resolve `framework_ci`:** detect whether a test framework config exists
   (e.g. `playwright.config.*`, `cypress.config.*`, `pytest`/`jest`/`vitest` config) and a CI
   workflow (`.github/workflows/*`, `.gitlab-ci.yml`, etc.).
   - If both look present → set `framework_ci: done` silently.
   - If missing → **ask**: run one-time `/bmad-testarch-framework` + `/bmad-testarch-ci` now
     (delegate to `ab-high`), or skip and let the user handle it (`skip`). Heavy, infra-choosing
     setup — never auto-run without asking.
4. Write `config.yaml` with the answers and detected `git`/`base_branch` values. Proceed.

## state/{key}.yaml
```yaml
story_key: 1-2-user-auth
epic_num: 1
story_num: 2
branch: story/1-2-user-auth
status: in-progress         # in-progress | done
is_first_in_epic: false
is_last_in_epic: false
git_mode: remote
tea_selected: [atdd, automate]   # from triage; [] if trivial or TEA off
tea_rationale: "touches auth -> High risk"
completed_phases: [0, 1, 3, 5]   # phase numbers from pipeline.md
code_review_iterations: 1
commits: [a1b2c3d, e4f5g6h]
gate_decision: null          # PASS|CONCERNS|FAIL|WAIVED (last story only)
pr_url: null
open_questions: []
deferred_work: []
blockers: []                 # each: short human-action description
```
Update it after every phase. Treat it as the source of truth for resume.

## Target selection & resume logic
No-arg `/auto-bmad` chooses the target story with this precedence:
1. **Incomplete auto-bmad pipeline first.** If any `state/*.yaml` has `status != done`, that
   story is the target — finish in-flight work before starting anything new. (At most one should
   exist; if several, take the most-recently-modified and mention the others in the report.)
2. **Else `story_plan.py`** picks the next actionable story. Its own precedence is
   `in-progress → review → ready-for-dev → backlog → retrospective`, so it resumes BMAD-level
   unfinished work before pulling a fresh `backlog` item — it does NOT jump straight to backlog.

An explicit `--story <arg>` overrides both and targets that story directly.

Once the target `story_key` is known:
- If `state/{key}.yaml` exists and `status != done` → **resume**: skip phases already in
  `completed_phases`, and if Phase 7 is in progress, continue the review loop from
  `code_review_iterations`. Re-detect git mode/branch (cheap) rather than trusting stale values
  if the branch is missing.
- Else → start fresh (initialize the state file in Phase 1).
- A `done` state file for the requested story → tell the user it's already complete and show the
  recorded `pr_url`; do not redo it (unless they explicitly force a re-run).

Git commits are the secondary safety net: even if the state file is lost, the per-phase commits
on the story branch show how far the pipeline got.

## retro-notes/epic-{e}.md
After each phase, append the agent's **Retro notes** under a per-story heading:
```
## Story {key}
- <decision / surprise / deviation / deferred item / risk worth remembering>
```
This file is created lazily on the first note for an epic and handed to `/bmad-retrospective`
at epic end as primary input — it carries the cross-step context (autonomy choices, why things
were done a certain way) that the story file alone doesn't capture.
