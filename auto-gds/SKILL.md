---
name: auto-gds
description: "Run the FULL GDS/BMGD story implementation workflow end-to-end for one story at a time. Use when the user says 'auto-gds', 'run auto-gds', 'implement the next game story', 'auto implement story X-Y', or wants the whole create-story -> dev-story -> code-review pipeline driven automatically on a branch with a PR at the end."
argument-hint: "[--story <id> | status | setup | reprovision | reset-defaults | <overrides…>]"
---

# auto-gds orchestrator

You drive the **entire GDS/BMGD implementation workflow for ONE story**, then stop and report so
the user manually triggers the next one.

## Output discipline
Work quietly: don't pre-announce or narrate routine reads/detections ("Let me check…", "Now I'll
read…") — just do them. Surface only what the user needs: decisions (with brief rationale), the
first-run/config summary, interactive questions, blockers, and the final report. Terse beats
play-by-play; this is an autonomous orchestrator, not a running commentary.

## On activation — register & provision first

Before the procedure, confirm cwd is a BMGD/GDS project: `_bmad/` exists and
`_bmad/gds/config.yaml` is readable. If not, hard-stop with:
"Not a BMGD/GDS project (no `_bmad/gds/config.yaml`). Run the BMAD installer with Game Dev Studio enabled first."
Then handle module registration and delegate provisioning:
- If invoked with `status` → run **Status mode** (below) and stop. It is read-only and never
  triggers setup, the first-run flow, or the pipeline.
- **Central registration check (BMad v6 — TOML, never `_bmad/config.yaml`):** the module counts
  as registered when a `[modules.agds]` table exists in `{project-root}/_bmad/config.toml`
  (team-scope central config, primary) or `{project-root}/_bmad/config.user.toml` (user-scope).
  Registration is written by the **BMad installer**, not by this skill. Do not read or require
  `_bmad/config.yaml`.
- If invoked with `setup`, `configure`, `install`, or `reprovision`, **or** if the module is not
  registered (no `[modules.agds]` in either central TOML file) → load
  `{skill-root}/assets/module-setup.md` and complete it first. It verifies installer
  registration, collects Auto-GDS settings, and renders the tool-native delegate agents
  (`.claude/agents/agds-*.md` and/or `.codex/agents/agds-*.toml`) for the selected
  `target_tools`. `reprovision` runs only the agent-render step; `setup`/`configure` always
  re-run the flow even if already registered. (When registration is absent but the Auto-GDS
  runtime config already exists, module-setup short-circuits with a one-time note instead of
  re-running setup — see its "Check Registration" section.)
- If the Auto-GDS runtime config (`<auto_gds_dir>/config.yaml`, where `<auto_gds_dir>` =
  `{resolved output_folder}/auto-gds` — see Step 0.3) is missing, the **first-run flow** in
  `references/state-and-resume.md` handles it (Step 0.3) — central registration alone does not
  create it.
- If invoked with `reset-defaults [scope]`, run the **restore-shipped-defaults** flow in
  `references/state-and-resume.md` → "reset-defaults": overwrite the asset-sourced
  `profiles`/`phase_profiles` from the shipped asset (after showing the diff and confirming), then
  re-render delegates if a profile changed. It needs a BMGD/GDS project + an existing runtime
  `config.yaml` (`<auto_gds_dir>/config.yaml`),
  is **config-only** (report what changed, then **stop** — never start a pipeline), and never
  touches the `delegation`/`testing`/`git`/`code_review` setup blocks.
- If the user's only intent was `setup`/`configure`/`reprovision`/`reset-defaults`, stop after
  reporting what was written/rendered — do **not** start a pipeline run. Otherwise continue to the
  Procedure — but
  if configuration ran **only because it was missing** (a run-intent invocation on a fresh
  project), the Procedure's first-run flow finishes the remaining config and then **stops for a
  fresh session** rather than launching the pipeline (see Step 0.3).

## Status mode (read-only)

`/auto-gds status` reports the project's Auto-GDS health, then exits. It writes **nothing** (no
config, no state), creates no branches/commits/PRs, spawns no delegates, and runs no GDS
production skills — safe for smoke tests. Report one line each, with concrete paths:
- **Project detection:** `_bmad/` present; `_bmad/gds/config.yaml` readable.
- **Central registration:** `[modules.agds]` found in `_bmad/config.toml` /
  `_bmad/config.user.toml` (or missing — recommend the BMad installer).
- **Runtime config:** the resolved `<auto_gds_dir>/config.yaml` path (note whether it came from
  `output_folder` or the `_bmad-output` fallback) and whether it exists.
- **Delegate agents:** rendered `.claude/agents/agds-*.md` / `.codex/agents/agds-*.toml` present.
- **GDS skills:** which of the delegated skills are installed — `gds-create-story`,
  `gds-dev-story`, `gds-code-review`, plus `gds-generate-project-context` / `gds-retrospective`
  when found. Look in the host's skills dir — `.claude/skills/`, `.agents/skills/`, or
  `.codex/skills/`, wherever this skill itself is installed.
- **Sprint status:** `<impl>/sprint-status.yaml` present (if not, point at `gds-sprint-planning`).
- **Next story:** any resumable in-flight state from `state_plan.py` (check regardless of sprint
  status), plus — when sprint status exists — the next eligible story from
  `python3 {skill-root}/scripts/story_plan.py --sprint-status <impl>/sprint-status.yaml --impl-dir <impl>`
  — **preview only, never start it**.
Missing pieces are reported with the suggested fix, never auto-fixed. For a deeper preview that
also resolves the phase plan, use `/auto-gds dry run` (an override — see
`references/overrides.md`; equally side-effect-free).

## The one rule

**You never do story work yourself.** Every GDS/BMGD production step — create-story, dev-story,
code-review, project-context generation, retrospective — runs inside a delegated sub-agent (the
`agds-*` profiles).
**Git plus the orchestrator-owned finalize actions are yours: you run them directly, never via
a delegate** — see `references/git-and-pr.md` → "Ownership" for the exact list (git preflight,
branching, per-phase commits, push, PR, the Phase 9 BMAD-status flip on a clean completion, and
the opt-in merge prompt + `gh pr merge` execution). You hold the full pipeline context, so you
write commit/PR messages yourself; delegating any of that would only add a slow round-trip. Your
own actions are: reading config/state, running `scripts/story_plan.py`, deciding what to delegate,
the ownership list above, writing the state file, and producing the final report. If you ever
feel tempted to edit code, write a test, or run an installed GDS skill such as `gds-dev-story`
directly — don't; delegate it.
(One carve-out: `inline` delegation mode on a host with no subagent support — see
`references/delegation-runtime.md`, where you run every step yourself but still follow the exact same
phase contract and structured-result discipline. At the Phase 7 HITL halt you do **not** read code:
on **Continue** you detect any external-review changes with a git-only check and **delegate** their
re-review to the alternate reviewer — never an inline read.)

`{skill-root}` is this skill's own folder — resolve it to wherever this skill is installed
(e.g. `.claude/skills/auto-gds/` for Claude Code, `.agents/skills/auto-gds/` for Codex — BMAD
installs Codex skills under `.agents/` — or `.codex/skills/auto-gds/`). Reference files live under
`{skill-root}/references/` and the helper scripts under `{skill-root}/scripts/`. Read a
reference file at the moment its step calls for it. Script invocations are written as `python3`;
on hosts without a `python3` alias (common on Windows), use `python`.

## Delegation mechanics

- **Pick the spawn method by host/tier — read `references/delegation-runtime.md`.** It uses
  `delegation.host` + `delegation.mode` from config: `custom-subagents` (Claude Code or Codex)
  runs each step in an isolated delegate at the profile's tuned model + thinking/reasoning
  effort; `general-subagents` uses the host's generic subagent without effort tuning; `inline`
  runs the step in this context as a last resort. `phase_profiles` maps each phase to a profile
  (`agds-xhigh`/`agds-high`/`agds-alt-xhigh`/`agds-alt-high`); `profiles` holds each profile's per-tool model +
  effort. The tool-native delegate files (`.claude/agents/agds-*.md`, `.codex/agents/agds-*.toml`)
  are rendered at setup by `scripts/render-agents.py` from those profiles.
- The delegate prompt is always the **exact** content from `references/delegation.md` for that
  step, with placeholders filled (story id, absolute file paths). Pass absolute paths — the
  delegate resolves BMAD's `{project-root}` from its cwd, but explicit paths remove ambiguity.
- After each delegated step, read the structured result. Append any **retro notes** to the epic
  retro-notes file — but skip `none`/empty/routine notes, so clean phases add nothing and the file
  stays usable across a long epic (see `references/state-and-resume.md`). Then checkpoint (commit)
  and update state. This is identical across tiers.

## Procedure

### Step 0 — Resolve paths & config
1. Confirm cwd is a BMGD/GDS project: `_bmad/` exists and `_bmad/gds/config.yaml` is readable.
   If not → **hard-stop**: "Not a BMGD/GDS project (no `_bmad/gds/config.yaml`). Run the BMAD installer with Game Dev Studio enabled first."
2. Read `_bmad/gds/config.yaml` for `implementation_artifacts`, `planning_artifacts`,
   `project_name`, `output_folder`, `project_knowledge`, `primary_platform`,
   `game_dev_experience`, `communication_language`, and `document_output_language`
   where present. Resolve `{project-root}` to the absolute cwd.
3. Resolve `output_folder` if present; otherwise use `{project-root}/_bmad-output`. Load
   Auto-GDS config from `{resolved output_folder}/auto-gds/config.yaml`.
   If missing — and the invocation did **not** ask for a `dry run` — run the **first-run flow**
   in `references/state-and-resume.md`, write the config, then **stop for a fresh session** per
   the same file's First-run stop (don't start the pipeline on the context that just did setup).
   A `dry run` invocation must stay side-effect-free: skip the first-run flow, plan from the
   shipped defaults in memory, and note the missing config in the printed plan. On later runs the config already exists, so this stop does not
   apply — continue to Step 1. First-run is the main interactive moment; auto-gds also halts at the
   end of the code-review loop on every run (Phase 7 — continue, optionally after an external review
   whose changes then get re-reviewed, or stop), and at the very end on a clean-completion PR —
   whether to merge (Phase 9, opt-in via `git.offer_merge`).

### Step 1 — Preflight
Read `references/state-and-resume.md`, `references/pipeline.md` (Phase 0), and — if the
invocation carried any instructions — `references/overrides.md`, then:
0. **Parse invocation overrides** (if any): normalize them per `references/overrides.md`,
   **echo the interpretation plus the resolved phase window/skips to the user**, and record them
   in state under `overrides` (on a `dry_run`, skip the state write — dry runs write nothing).
   If `dry_run`, print the plan and stop here.
1. **Skill availability:** verify the GDS/BMGD skills required for the selected path exist
   (core always; project-context/retrospective only when their phase can run). Missing
   → **hard-stop** listing exactly which skills are absent and how to install them.
2. **Target story** (precedence when NO `--story` argument is given):
   a. **Resume an interrupted pipeline first:** run
      `python3 {skill-root}/scripts/state_plan.py --state-dir <auto_gds_dir>/state`.
      If it reports `resume: true`, its `target` (the most-recently-updated in-flight story) wins —
      auto-gds finishes in-flight work before starting anything new (note any `extra_in_flight`
      in the report; there should be at most one given "one story at a time"). Don't hand-roll a
      glob loop for this — see `state-and-resume.md` → "Target selection & resume logic".
   b. Otherwise run
      `python3 {skill-root}/scripts/story_plan.py --sprint-status <impl>/sprint-status.yaml --impl-dir <impl>`
      to pick the next actionable story. Its precedence is `in-progress → review →
      ready-for-dev → backlog → retrospective`, so it **resumes GDS/BMGD-level unfinished work
      before pulling a fresh backlog item** — it does not jump straight to backlog.
   With a `--story <arg>`: pass `--story <arg>` to the script (overrides the above). Either way,
   parse the JSON; if `hard_stop` is true → surface `hard_stop_reason` and stop.
3. **Resume check:** for the chosen `story_key`, run the same reader with
   `--story-key {story_key}` (exact-path lookup, no glob). `resume: true` ⇒ resume from the first
   phase not in `completed_phases` (and continue the review loop from `code_review_iterations`);
   otherwise initialize a fresh state file in Phase 1.
4. **Git preflight & project-context probe** (per Phase 0 of the pipeline): **you run the
   git preflight and the project-context probe directly** — detect repo, clean tree, git mode,
   base branch; then probe for an existing `project-context.md` at the BMAD-canonical write path
   (`<output_folder>/project-context.md`) with a `find` fallback anywhere under `<project_root>`
   except `node_modules/`/`.venv/`/`.git/` (see Phase 0 for the exact invocation — it mirrors the
   `gds-generate-project-context` skill's own discovery) and record
   `needs_project_context_bootstrap` in state. Record GDS config context in state/report when
   present.

### Step 2 — Run the pipeline
Execute Phases 1–9 exactly as specified in `references/pipeline.md`, in order, skipping phases
whose conditions don't apply (project-context bootstrap only if needed; epic-end only if
`is_last_in_epic`; GDS testing placeholders disabled in V0). **Also honor this run's overrides
(`references/overrides.md`):** run a phase only if it's inside the start/stop window and not in
`skip`; phases outside it are recorded as skipped with reason `override`. For each phase that runs:
- delegate to the profile named in the pipeline using the prompt from `references/delegation.md`
  (spawn it per `references/delegation-runtime.md`);
- on a `blocked` / `needs-human` outcome, **stop the pipeline** and jump to the report;
- otherwise checkpoint (commit per `references/git-and-pr.md` — **unless `skip git-commits` is in
  effect**), append retro notes, update state.

### Step 3 — Final report
Always produce a report (even on hard-stop). The report is **split**: a story-level **file
portion** that lands in the PR diff, and a **chat-only** wrapper for the PR/CI/merge **artifacts**
(links, merge method, status-flip) that exist elsewhere already (git, GitHub, sprint-status). The
one-line *disposition* is **not** in that wrapper — it lives in the file's `Pipeline status` line.
Both are always printed to the user.

- **File portion** (the persistent log under `<auto_gds_dir>/reports/{key}.md`):
  on a clean path this file was already written + committed in Phase 9 **before push**
  (`docs(story-{e}-{s}): pipeline report`) so it ships in the PR — Step 3 does not re-write it
  in that case. On any path that didn't reach the Phase 9 pre-push write (a hard-stop in
  Phases 0–8, `needs-human`, or an override that ended the run early), Step 3 writes it now as
  a fallback (append a new `## Report — <ISO timestamp>` section — tagged `(halted — <reason>)`
  on this pre-finalize path — preserving any earlier sections; **no commit** — the tree is already
  in needs-human state and the human will commit alongside their fix). Never overwrite on resume —
  earlier runs' sections carry context we must not lose. The ONLY time you overwrite is a
  deliberate full re-run of an already-`done` story, after explicit user confirmation; if
  declined, append.
- **Chat-only** (printed at the end of every run; not written to the file): the full file
  portion below, **plus** the PR / CI / merge / final-status **artifact** lines listed underneath
  — these add the links/merge-method/status-flip specifics to the disposition the file's
  `Pipeline status` line already records; they do not replace it.

**File portion — fields** (story-level outputs preserved across runs; use the exact heading
order and field labels from `references/state-and-resume.md` → "Section template" — no
restructuring per run, so PR reviewers always find each field in the same place):
- **Story:** key, branch (HEAD short sha).
- **Pipeline status:** one-line summary (clean completion / halted at Phase N / draft (reason) / …).
  Also tag the `## Report` heading itself with the section's disposition — `(final)` /
  `(final — caveated)` / `(halted — <reason>)` — so the log is skim-readable from its outline.
- **Timing:** `started_at`/`completed_at` (or "in progress"), total elapsed, and the best-effort
  AI-run vs human/idle-wait split (`active_seconds` vs `elapsed − active_seconds`); note resume count if >1.
- **Phases run / Skipped:** the Phase N list each line (THIS session only — a resume reports its
  delta, with a `Continues:` line naming the section it picks up from), profile in parens for delegated phases.
- **Overrides:** any invocation overrides applied this run (phase window, skips, caps); "none" if none.
- **Testing:** "disabled in V0" unless a future explicit GDS testing config enabled and ran steps.
- **Code review:** iterations run; per-iteration verdict + severity counts in the fixed form
  `Critical N / High N / Medium N / Low N`; the end-of-loop HITL-halt outcome (continued / stopped),
  and — if external-review changes triggered a post-halt re-review — its rounds, verdict + counts, and
  the user's fix / fix-and-re-review / ignore decision.
- **Open questions** surfaced by any step ("(none)" if empty — keep the heading).
- **Deferred work** (anything intentionally postponed; also appended to the durable cross-story
  `<impl>/deferred-work.md` ledger). "(none)" if empty — keep the heading. On the **last story of an
  epic**, also note how many resolved entries Phase 8 moved to the `deferred-work-resolved.md`
  archive (e.g. "archived 6 resolved → deferred-work-resolved.md"; omit the note if none).
- **Planning drift** (epic-end only): planning assumptions the retrospective proved wrong + the
  recommended re-sync (`gds-generate-project-context` refresh; `gds-correct-course` if
  structural). Non-blocking, never auto-run. "(none)" if clean or not epic-end.
- **⚠️ Needs human:** blockers / manual actions. On a **caveated** completion these are required
  before the story can be considered done (it was left at `review`). On a **clean** completion the
  story is already `done`; list only genuine follow-ups (e.g. merging the open PR is optional and
  on the human's own time) — do not imply the merge gates `done`. "(none)" if clean.
- **Next:** the next story `story_plan.py` would pick (preview only — do NOT start it).

**Chat-only — additional lines** (not committed; the finalization **artifacts/links**, retrievable
from git/GitHub/sprint-status later — they add the PR/CI/merge specifics on top of the disposition
the file's `Pipeline status` line already carries; the disposition itself is not chat-only):
- **Final status:** clean (GDS/BMGD status flipped to `done`) vs caveated (left at `review`: draft PR /
  recorded blocker / CI red or timed-out). On a clean completion that was **not**
  merged, frame the open PR's merge as the human's remaining (optional, non-blocking) step. On a
  successful merge, say so plainly ("Merged via merge commit; branch deleted") — no further action.
- **PR:** link (or "local branch only — no GitHub remote/`gh`"), draft? why. On a merge: merge
  method + branch-deleted state; on a failed merge attempt: the `gh` error verbatim.
- **CI:** link to the CI run the PR/push triggered + its final status (`passed`/`failed`/`timeout`
  if the merge prompt was on and Phase 9 waited; `queued/in_progress` otherwise). Omit if no
  workflows.

## Hard-stop conditions (surface clearly, then report & exit)
Not a BMGD/GDS project; missing required skill; no `sprint-status.yaml` / no epics; ambiguous or
not-found `--story`; epic already `done`; dirty working tree on the wrong branch; merge/rebase
conflict; a delegated step returns `blocked`/`needs-human` (missing secret/credential, required
external service, or manual action). Never push past a hard-stop — report and let the human act.

(Note: two pipeline situations are NOT silent hard-stops — each **asks the user** what to do:
the code-review loop's end-of-loop HITL halt, asked every run (Phase 7 — continue, optionally after
an external review, or stop; re-asked with fix / fix-and-re-review / ignore if that review's changes
re-review as meaningful); and the end-of-pipeline merge prompt on a clean-completion PR (Phase 9 — merge commit
(default) / rebase / squash / don't merge, plus a delete-branch sub-question — opt-in via
`git.offer_merge`, default on).)
