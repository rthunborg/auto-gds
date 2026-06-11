---
name: auto-bmad
description: "Run the FULL BMAD story implementation workflow end-to-end for one story at a time. Use when the user says 'auto-bmad', 'run auto-bmad', 'implement the next story', 'auto implement story X-Y', or wants the whole create-story -> dev-story -> code-review (+ TEA + epic-boundary) pipeline driven automatically on a branch with a PR at the end."
argument-hint: "[--story <id> | setup | reprovision | reset-defaults | <overrides…>]"
---

# auto-bmad orchestrator

You drive the **entire BMAD implementation workflow for ONE story**, then stop and report so
the user manually triggers the next one.

## Output discipline
Work quietly: don't pre-announce or narrate routine reads/detections — just do them. Surface
only what the user needs: decisions (with brief rationale), the first-run/config summary,
interactive questions, blockers, and the final report.

## On activation — register & provision first

Before the procedure, handle module registration and delegate provisioning:
- If invoked with `setup`, `configure`, `install`, or `reprovision`, **or** if
  `{project-root}/_bmad/config.yaml` has no `abm` section → load
  `{skill-root}/assets/module-setup.md` and complete it first (registration, config write,
  delegate-agent rendering for the selected `target_tools`). `reprovision` runs only the
  agent-render step; `setup`/`configure` always re-run registration even if already registered.
- If invoked with `reset-defaults [scope]`, run the **restore-shipped-defaults** flow in
  `references/state-and-resume.md` → "reset-defaults". It is **config-only**: report what
  changed, then **stop** — never start a pipeline.
- This requires a BMAD project; if `_bmad/` is absent, the Step 0.1 hard-stop applies.
- If the user's only intent was `setup`/`configure`/`reprovision`/`reset-defaults`, stop after
  reporting what was written/rendered — do **not** start a pipeline run. Otherwise continue to
  the Procedure; if configuration ran **only because it was missing** (a run-intent invocation
  on a fresh project), Step 0.3's first-run stop applies — finish config, then **stop for a
  fresh session** rather than launch the pipeline.

## The one rule

**You never do story work yourself.** Every BMAD step — create-story, dev-story, code-review,
every TEA skill, retrospective — runs inside a delegated `ab-*` sub-agent. **Git plus the
orchestrator-owned finalize actions are yours: you run them directly, never via a delegate** —
exact list in `references/git-and-pr.md` → "Ownership"; you write commit/PR messages yourself.
Your own actions: reading config/state, running `scripts/story_plan.py`, deciding what to
delegate, the ownership list, writing the state file, and producing the final report. Tempted
to edit code, write a test, or run a `/bmad-*` skill directly? Don't — delegate it. (One
carve-out: `inline` delegation mode — see `references/delegation-runtime.md` — where you run
every step yourself under the same phase contract and structured-result discipline. Even
inline, the Phase 7 HITL halt reads no code: on **Continue** you detect external-review changes
with a git-only check and **delegate** their re-review via the code-review fan-out — never an
inline read.)

`{skill-root}` is this skill's own folder — resolve it to wherever this skill is installed
(e.g. `.claude/skills/auto-bmad/`, `.codex/skills/auto-bmad/` or `.opencode/skills/auto-bmad/`). Reference files live under
`{skill-root}/references/` and the helper scripts under `{skill-root}/scripts/`. Read a
reference file at the moment its step calls for it.

## Delegation mechanics

- **Pick the spawn method by host/tier — read `references/delegation-runtime.md`.** It resolves
  `delegation.host` + `delegation.mode` from config into a tier (`custom-subagents` — isolated
  delegate at the profile's tuned model + effort; `general-subagents` — no effort tuning;
  `inline` — this context, last resort), maps each phase to a profile via `phase_profiles`, and
  takes each profile's per-tool model + effort from `profiles` (rendered into the tool-native
  delegate files at setup by `scripts/render-agents.py`).
- **Opt-in external-CLI routing:** before picking a tier, check `delegation.cli_phases` — a phase
  listed there is delegated to an external CLI (`claude -p` / `codex exec` / `opencode run`) instead of an in-tool
  sub-agent (resolve it with `scripts/cli_delegate.py`; see `references/delegation-runtime.md` →
  "Per-phase external-CLI routing"). Still delegation — you build the command and parse the result,
  never read code. Default is empty (all in-tool).
- The delegate prompt is always the **exact** content from `references/delegation.md` for that
  step, with placeholders filled (story id, file paths — always pass absolute paths).
- After each delegated step, read the structured result. Hand any **retro notes** to
  `scripts/state_update.py retro-append` (see `references/state-and-resume.md`) — the script
  enforces the skip-empty rule. Then checkpoint (commit) and update state (via
  `state_update.py`). This is identical across tiers.

## Procedure

### Step 0 — Resolve paths & config
1. Confirm cwd is a BMAD project: `_bmad/` exists and `_bmad/bmm/config.yaml` is readable.
   If not → **hard-stop**: "Not a BMAD project (no `_bmad/`). Run the BMAD installer first."
2. Read `_bmad/bmm/config.yaml` for `implementation_artifacts`, `planning_artifacts`,
   `project_name` (resolve `{project-root}` to the absolute cwd).
3. Load auto-bmad config from `{project-root}/_bmad-output/auto-bmad/config.yaml`. If missing,
   run the **first-run flow** in `references/state-and-resume.md`, write the config, then **stop
   for a fresh session** per the same file's First-run stop; otherwise continue to Step 1.
   First-run is the main interactive moment; auto-bmad also asks at the end of the code-review
   loop (Phase 7), on a `FAIL` epic trace gate (Phase 8), and on a clean-completion PR's merge
   prompt (Phase 9) — each halt's options/conditions are in the note under Hard-stop conditions.

### Step 1 — Preflight
Read `references/state-and-resume.md`, `references/pipeline.md` (Phase 0), and — if the
invocation carried any instructions — `references/overrides.md`, then:
0. **Parse invocation overrides** (if any): normalize them per `references/overrides.md`,
   **echo the interpretation plus the resolved phase window/skips to the user**, and carry them
   into Phase 1's `init --json` under `overrides` (no state file exists yet — pipeline.md, the
   Phase 0 exception). If `dry_run`, print the plan and stop here. (`skip tea` flips
   `tea.enabled` off for this run, affecting sub-steps 1 and 4 below.)
1. **Skill availability:** the BMAD skills required for the selected path must exist — the
   `/bmad-*` skills named in `delegation.md` for the phases that will run (core always; TEA set
   only if `tea.enabled`; epic-end skills if this is a last story). Finalize the list AFTER
   sub-step 2 picks the target, and check it via sub-step 4's single `preflight.py` call:
   `--require-skills <csv> --skills-dirs <the host's per-tool skills dirs — the lookup list in
   `delegation-runtime.md` → "Per-phase external-CLI routing">`; obey `skills.missing`.
   Missing → **hard-stop** listing exactly which skills are absent and how to install them.
2. **Target story** (precedence when NO `--story` argument is given):
   a. **Resume an interrupted pipeline first:** run
      `python3 {skill-root}/scripts/state_plan.py --state-dir <output_folder>/auto-bmad/state`.
      `resume: true` ⇒ its `target` wins (note any `extra_in_flight` in the report). Don't
      hand-roll a glob loop — see `state-and-resume.md` → "Target selection & resume logic".
   b. Otherwise run
      `python3 {skill-root}/scripts/story_plan.py --sprint-status <impl>/sprint-status.yaml --impl-dir <impl>`
      to pick the next actionable story. Its precedence (`in-progress → review → ready-for-dev →
      backlog → retrospective`) resumes BMAD-level unfinished work before fresh backlog.
   With a `--story <arg>`: pass `--story <arg>` to the script (overrides the above). Either way,
   parse the JSON; if `hard_stop` is true → surface `hard_stop_reason` and stop.
3. **Resume check:** for the chosen `story_key`, run `state_plan.py` again with
   `--story-key {story_key}` (exact-path lookup, no glob). `resume: true` ⇒ resume from the first
   phase not in `completed_phases` (and continue the review loop from `code_review_iterations`);
   otherwise initialize a fresh state file in Phase 1 — but first apply the **status-mismatch
   guard** (`state-and-resume.md` → "Target selection & resume logic"): a story already at
   `review`/`in-progress` with no state file asks the user before running the full pipeline.
4. **Git preflight, project-context probe & triage** (per Phase 0 of the pipeline): run
   `python3 {skill-root}/scripts/preflight.py --project-root <project_root> --output-folder
   <output_folder>` (one call, one JSON — field semantics in Phase 0); obey its `git` block
   (honor `hard_stop`/`hard_stop_reasons`) and `project_context.found` → note
   `needs_project_context_bootstrap`. Then, **only if TEA enabled**, delegate the
   story-risk classification to the `tea_triage` profile to pick per-story TEA skills. All of
   these decisions ride in Phase 1's `init --json` payload — Phase 0 never writes state
   (pipeline.md, the Phase 0 exception). (On a resume with Phase 0 already in
   `completed_phases`, reuse the recorded `tea_risk`/`tea_selected` — don't re-delegate the
   triage.)

### Step 2 — Run the pipeline
Execute Phases 1–9 exactly as specified in `references/pipeline.md`, in order, skipping phases
whose conditions don't apply (epic-start only if `is_first_in_epic`; TEA phases per triage and
`tea.enabled`; epic-end only if `is_last_in_epic`). **Also honor this run's overrides
(`references/overrides.md`):** run a phase only if it's inside the start/stop window and not in
`skip`; phases outside it are recorded as skipped with reason `override`. For each phase that
runs: delegate to the profile named in the pipeline per Delegation mechanics; on a `blocked` /
`needs-human` outcome, **stop the pipeline** and jump to the report; otherwise checkpoint
(commit per `references/git-and-pr.md` — **unless `skip git-commits` is in effect**), append
retro notes, update state.

### Step 3 — Final report
Always produce a report (even on hard-stop). The report is **split**: a story-level **file
portion** that lands in the PR diff, and a **chat-only** wrapper for the PR/CI/merge **artifacts**
(the one-line *disposition* is **not** in that wrapper — it lives in the file's `Pipeline status`
line). Both are always printed to the user.

- **File portion** (the persistent log under `{project-root}/_bmad-output/auto-bmad/reports/{key}.md`):
  on a clean path Phase 9 already wrote + committed it **before push**
  (`docs(story-{e}-{s}): pipeline report`) — Step 3 does not re-write it. On any path that
  didn't reach that pre-push write (a hard-stop in Phases 0–8, `needs-human`, or an override
  that ended the run early), Step 3 writes it now as a fallback: append a new
  `## Report — <ISO timestamp>` section, tagged `(halted — <reason>)` on this pre-finalize path,
  preserving any earlier sections; **no commit** (the human commits alongside their fix). On a
  hard-stop BEFORE Phase 1's `init` (no state file yet — e.g. dirty tree, missing skill), pass
  `--allow-missing-state` to `report-section`: it renders against a default state instead of
  erroring, so the report still lands. Never
  overwrite on resume; the ONLY overwrite is a deliberate full re-run of an already-`done`
  story, after explicit user confirmation — if declined, append.
- **Chat-only** (printed at the end of every run; not written to the file): the full file
  portion, **plus** the artifact lines listed under "Chat-only — additional lines" below.

**File portion — fields:** the file portion's fields, heading order, and per-field semantics
live in `references/state-and-resume.md` → "Section template" — the **single home**, rendered
literally by `scripts/state_update.py report-section`. Don't restate or restructure them here.

**Chat-only — additional lines** (not committed; the finalization **artifacts/links**, retrievable
from git/GitHub/sprint-status later — they add the PR/CI/merge specifics on top of the disposition
the file's `Pipeline status` line already carries; the disposition itself is not chat-only):
- **Final status:** clean (BMAD-level flipped to `done`) vs caveated (left at `review`: draft PR /
  recorded blocker / waived gate / CI red or timed-out). On a clean completion that was **not**
  merged, frame the open PR's merge as the human's remaining (optional, non-blocking) step. On a
  successful merge, say so plainly ("Merged via merge commit; branch deleted") — no further action.
- **PR:** link (or "local branch only — no GitHub remote/`gh`"), draft? why. On a merge: merge
  method + branch-deleted state; on a failed merge attempt: the `gh` error verbatim.
- **CI:** link to the CI run the PR/push triggered + its final status (`passed`/`failed`/`timeout`
  if the merge prompt was on and Phase 9 waited; `queued/in_progress` otherwise). Omit if no
  workflows.

## Hard-stop conditions (surface clearly, then report & exit)
Not a BMAD project; missing required skill; no `sprint-status.yaml` / no epics; ambiguous or
not-found `--story`; epic already `done`; dirty working tree on the wrong branch; merge/rebase
conflict; a delegated step returns `blocked`/`needs-human` (missing secret/credential, required
external service, or manual action). Never push past a hard-stop — report and let the human act.

(Note: three pipeline situations are NOT silent hard-stops — each **asks the user** what to do:
the code-review loop's end-of-loop HITL halt (Phase 7 — run one more review iteration, continue
(optionally after an external review), or stop; re-asked once — another iteration, continue as
draft, or stop — if that review's changes
re-review as meaningful; always skipped when the
loop converged cleanly); a `FAIL` epic trace gate (Phase 8 — remediate & re-gate / waive /
stop); and the end-of-pipeline merge prompt on a clean-completion PR (Phase 9 — merge commit
(default) / rebase / squash / don't merge, plus a delete-branch sub-question — opt-in via
`git.offer_merge`, default on).)
