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

`{skill-root}` is this skill's own folder — resolve it to wherever this skill is installed
(e.g. `.claude/skills/auto-bmad/` or `.codex/skills/auto-bmad/`). Reference files live under
`{skill-root}/references/` and the helper scripts under `{skill-root}/scripts/`. Read a
reference file at the moment its step calls for it.

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
   run the **first-run flow** in `references/state-and-resume.md`, then write the config.
   (First-run is normally the only interactive moment; the one other place auto-bmad may ask is
   when code review fails to converge within the iteration cap — see Phase 7.)

### Step 1 — Preflight
Read `references/state-and-resume.md` and `references/pipeline.md` (Phase 0), then:
1. **Skill availability:** verify the BMAD skills required for the selected path exist
   (core always; TEA set only if `tea.enabled`; epic-end skills if this is a last story). Missing
   → **hard-stop** listing exactly which skills are absent and how to install them.
2. **Target story** (precedence when NO `--story` argument is given):
   a. **Resume an interrupted pipeline first:** if any `state/*.yaml` has `status != done`,
      that story wins — auto-bmad finishes in-flight work before starting anything new (there
      should be at most one given "one story at a time"; if several, take the most recently
      modified and note the others in the report).
   b. Otherwise run
      `python3 {skill-root}/scripts/story_plan.py --sprint-status <impl>/sprint-status.yaml --impl-dir <impl>`
      to pick the next actionable story. Its precedence is `in-progress → review →
      ready-for-dev → backlog → retrospective`, so it **resumes BMAD-level unfinished work
      before pulling a fresh backlog item** — it does not jump straight to backlog.
   With a `--story <arg>`: pass `--story <arg>` to the script (overrides the above). Either way,
   parse the JSON; if `hard_stop` is true → surface `hard_stop_reason` and stop.
3. **Resume check:** if a non-`done` state file exists for the chosen `story_key`, resume from
   the first phase not in `completed_phases` (and continue the review loop from
   `code_review_iterations`). Otherwise initialize a fresh state file in Phase 1.
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
Always produce a single report (even on hard-stop). **Append it** as a new timestamped section
(`## Report — <ISO timestamp>`) to `{project-root}/_bmad-output/auto-bmad/reports/{key}.md`,
**preserving any existing sections**, and print the same content to the user. Never overwrite on
resume — earlier runs' reports carry context we must not lose. The ONLY time you overwrite the
file is a deliberate full re-run of an already-`done` story, and only after explicit user
confirmation. The report contains:
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
conflict; a delegated step returns `blocked`/`needs-human` (missing secret/credential, required
external service, or manual action). Never push past a hard-stop — report and let the human act.

(Note: code review NOT converging within `max_iterations` is NOT a silent hard-stop — Phase 7
**asks the user** what to do.)
