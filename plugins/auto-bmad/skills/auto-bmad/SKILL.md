---
name: auto-bmad
description: "Run the FULL BMAD story implementation workflow end-to-end for one story at a time. Use when the user says 'auto-bmad', 'run auto-bmad', 'implement the next story', 'auto implement story X-Y', or wants the whole create-story -> dev-story -> code-review (+ TEA + epic-boundary) pipeline driven automatically on a branch with a PR at the end."
---

# auto-bmad orchestrator

You drive the **entire BMAD implementation workflow for ONE story**, then stop and report so
the user manually triggers the next one.

## The one rule

**You only orchestrate. You never do story work yourself.** Every BMAD step — create-story,
dev-story, code-review, every TEA skill, retrospective — runs inside a delegated sub-agent
(the bundled `ab-*` profiles). You also delegate the mechanical git/PR work. Your own actions
are limited to: reading config/state, running `scripts/story_plan.py`, deciding what to
delegate, committing checkpoints (or delegating that), writing the state file, and producing
the final report. If you ever feel tempted to edit code, write a test, or run a `/bmad-*`
skill directly — don't; delegate it.

`${CLAUDE_PLUGIN_ROOT}` is this plugin's root. Reference files live under
`${CLAUDE_PLUGIN_ROOT}/skills/auto-bmad/references/` and the helper script under
`.../scripts/story_plan.py`. Read a reference file at the moment its step calls for it.

## Delegation mechanics

- Delegate with the Agent/Task tool, setting `subagent_type` to the profile name: `ab-max`,
  `ab-xhigh`, `ab-high`, or `ab-sonnet` (each bakes in its model + thinking effort). If a bare
  name doesn't resolve, try the namespaced form `auto-bmad:ab-max`.
- The agent prompt must be the **exact** content from `references/delegation.md` for that step,
  with placeholders filled (story id, absolute file paths). Pass absolute paths — the sub-agent
  resolves BMAD's `{project-root}` from its cwd, but explicit paths remove ambiguity.
- After each delegated step, read the agent's structured result. Append its **retro notes** to
  the epic retro-notes file. Then checkpoint (commit) and update state.

## Procedure

### Step 0 — Resolve paths & config
1. Confirm cwd is a BMAD project: `_bmad/` exists and `_bmad/bmm/config.yaml` is readable.
   If not → **hard-stop**: "Not a BMAD project (no `_bmad/`). Run the BMAD installer first."
2. Read `_bmad/bmm/config.yaml` for `implementation_artifacts`, `planning_artifacts`,
   `project_name` (resolve `{project-root}` to the absolute cwd).
3. Load auto-bmad config from `{project-root}/_bmad-output/auto-bmad/config.yaml`. If missing,
   run the **first-run flow** in `references/state-and-resume.md` (this is the ONLY interactive
   moment in normal operation), then write the config.

### Step 1 — Preflight
Read `references/state-and-resume.md` and `references/pipeline.md` (Phase 0), then:
1. **Skill availability:** verify the BMAD skills required for the selected path exist
   (core always; TEA set only if `tea.enabled`; epic-end skills if this is a last story). Missing
   → **hard-stop** listing exactly which skills are absent and how to install them.
2. **Target story:** run
   `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auto-bmad/scripts/story_plan.py --sprint-status <impl>/sprint-status.yaml --impl-dir <impl> [--story <arg>]`
   where `<arg>` is the user's argument if given. Parse the JSON. If `hard_stop` is true →
   surface `hard_stop_reason` and stop.
3. **Resume check:** if a non-`done` state file exists for `story_key`, you are resuming —
   continue from the first incomplete phase. Otherwise initialize a fresh state file.
4. **Git preflight & triage:** delegate to `ab-sonnet` per Phase 0 of the pipeline (detect repo,
   clean tree, git mode, base branch; and — only if TEA enabled — classify story risk to pick
   per-story TEA skills). Record the decisions in state.

### Step 2 — Run the pipeline
Execute Phases 1–9 exactly as specified in `references/pipeline.md`, in order, skipping phases
whose conditions don't apply (epic-start only if `is_first_in_epic`; TEA phases per triage and
`tea.enabled`; epic-end only if `is_last_in_epic`). For each phase:
- delegate to the profile named in the pipeline using the prompt from `references/delegation.md`;
- on a `blocked` / `needs-human` outcome, **stop the pipeline** and jump to the report;
- otherwise checkpoint (commit per `references/git-and-pr.md`), append retro notes, update state.

### Step 3 — Final report
Always end with a single report (even on hard-stop) containing:
- **Story:** key, final status, branch.
- **PR:** link (or "local branch only — no GitHub remote/`gh`"), draft? why.
- **TEA:** which skills ran and outcomes; epic gate decision if last story.
- **Open questions** surfaced by any step.
- **Deferred work** (anything intentionally postponed).
- **⚠️ Needs human:** blockers / manual actions required before this can be considered done.
- **Next:** the next story `story_plan.py` would pick (preview only — do NOT start it).

## Hard-stop conditions (surface clearly, then report & exit)
Not a BMAD project; missing required skill; no `sprint-status.yaml` / no epics; ambiguous or
not-found `--story`; epic already `done`; dirty working tree on the wrong branch; merge/rebase
conflict; unresolved High-severity review findings after `code_review.max_iterations`;
a delegated step returns `blocked`/`needs-human` (missing secret/credential, required external
service, or manual action). Never push past a hard-stop — report and let the human act.
