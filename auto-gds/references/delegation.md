# Delegation prompts

**This file is the single source of truth for what each delegated GDS/BMGD step runs** — its exact
installed GDS skill name, prompt body, and the placeholders below. One entry per step, named by its heading (e.g.
`create-story`); `pipeline.md` references each by heading name and never repeats the command, so a
command changes here and nowhere else. Git/PR steps are not delegated and have no entry here — the
orchestrator runs them; see `git-and-pr.md`.

Auto-GDS delegates to installed GDS skill names from `_bmad/_config/skill-manifest.csv`. For
BMad 6.8.0 with GDS v0.6.0 these are `gds-*` names. If a future GDS release changes names,
resolve exact names from the installed skill manifest rather than relying on documentation aliases.

The orchestrator fills the placeholders and sends the result as the Agent prompt to the profile
that `phase_profiles` assigns to the step's phase (see `pipeline.md` for the phase→profile-key
mapping and `state-and-resume.md` for the config). Keep prompts **minimal** (command + the inputs
the skill needs) and end each with the shared autonomy directive below — the delegate profiles
already carry the full form, so the short version is enough.

**Shared autonomy directive (append to every prompt):**
> Run fully autonomously — answer any interactive BMAD menu/checkpoint with the sensible default
> and never wait for human input. The sensible default is ALWAYS the option that completes the
> step and persists its deliverable — never one that skips it, discards findings, or writes
> nothing. If something genuinely needs a human (missing secret/credential, external service, 
> manual action, or an ambiguity that changes the outcome), STOP and report it as `needs-human`. 
> Return the structured result: Outcome, Files changed, Status, Open questions, Deferred work, 
> Blockers, Retro notes (short and terse — say `none` unless something is genuinely worth the 
> epic retrospective; one line per item, no recap of routine work).

**Placeholders (canonical glossary — `pipeline.md` references this list, not its own copy).**
`<...>` = a filesystem path the orchestrator resolves; `{...}` = a non-path value it fills in
(identity/config scalar, or an injected block).
- `{e}` / `{s}` — epic / story number.
- `{key}` — full story key (e.g. `1-2-user-auth`).
- `{slug}` — the title part of the key.
- `{decisions}` — the human-chosen fix directions from Phase 7.
- `<project_root>` — absolute cwd.
- `<impl>` — the `implementation_artifacts` dir; `<planning>` — the planning dir.
- `<auto_gds_dir>` — resolved Auto-GDS runtime directory (`{output_folder}/auto-gds`, or the
  `_bmad-output/auto-gds` fallback when GDS config has no `output_folder`).
- `<story_file>` — absolute path `<impl>/{key}.md` (from `story_plan.py`).

---

### create-story
```
Run `gds-create-story {e}-{s}` in <project_root>.
Create the comprehensive story context file for story {e}-{s}.
{retro_notes_hint}
{deferred_work_hint}
```
The orchestrator fills `{retro_notes_hint}` from on-disk state:
- If `<auto_gds_dir>/retro-notes/epic-{e}.md` exists and is non-empty (earlier stories in
  this epic have landed signal): `BEFORE drafting the story context, ALSO read
  <auto_gds_dir>/retro-notes/epic-{e}.md and treat each '## Story <key>' section's bullets
  as constraints surfaced by earlier stories in the same epic — epic-wide gotchas, schema
  inheritance, conventions ratified, things later stories MUST or MUST NOT do. Reflect any that
  apply to this story directly in the Story Context (constraints, persistent_facts, or test
  notes), not as a generic "see retro-notes" reference.`
- Else, if this is the **first story of epic {e}** AND a prior epic `{e-1}` closed with a
  retrospective document — locate it with `find <impl> -name 'epic-{e-1}-retro-*.md'` (BMAD writes
  the retro there; never iterate a raw glob — see CLAUDE.md → shell-glob rule; use the newest match
  if several, omit if none): `BEFORE drafting the story context, ALSO read the prior epic's
  retrospective document and focus on its FORWARD-looking sections (e.g. "Next Epic Preparation",
  "Preparation Checklist Before Epic {e}", "Conventions Ratified for All Epic {e}+ Stories", Action
  Items). These are the epic-transition prep + conventions the just-closed epic flagged for THIS
  epic. Fold the items that apply to this story into the Story Context (constraints,
  persistent_facts, or test notes) — especially any "before the first story of epic {e}" prep, and
  any "the gate/check will fail-loud on the new table → that is expected, register/extend it"
  heads-ups — not as a generic "see the retro" reference. (Durable conventions also reach you via
  project-context.md as persistent_facts; this feed adds the transient, epic-specific prep that
  project-context.md does not carry.)`
- Otherwise omit the line entirely (first story of epic 1, or no signal yet).

Phase notes in the retro file use a `[Phase X — short-name]` prefix (e.g.
`[Phase 5 — dev-story]`, `[Phase 7 — code review]`). Preserve the prefix when appending — it
lets later stories filter by phase if they need to.

The orchestrator also fills `{deferred_work_hint}` from on-disk state. The ledger
`<impl>/deferred-work.md` is the project-wide code-review defer sink (append-only,
project-wide, keyed by `## Deferred from: <source> (<date>)` headings) — no GDS/BMGD skill
reads it back, so create-story only sees it if we inject it here.
- If `<impl>/deferred-work.md` exists and is non-empty: `ALSO read <impl>/deferred-work.md before
  drafting the story context. It is a project-wide ledger of work earlier stories consciously
  deferred — most entries are out of scope for this story. Identify ONLY the deferrals whose
  subject overlaps this story's area, files, or acceptance criteria, and fold those into the Story
  Context (constraints, persistent_facts, or test notes) so the dev agent either addresses them or
  knowingly works around them. Do NOT copy the whole ledger, and do NOT reopen or re-defer items
  unrelated to this story.`
- Otherwise omit the line entirely (the ledger doesn't exist yet, or is empty).

### dev-story
```
Run `gds-dev-story <story_file>` in <project_root>.
Implement the story to completion: all tasks/subtasks done, tests written and passing, story
moved to `review`. Do not commit or branch — the orchestrator handles git.
When done, report a short summary of what you built plus any deviations, key decisions, and
deferred work — and any breaking change you introduce (a changed/removed public interface, config
key, schema, CLI flag, or required migration step). The orchestrator records these in the commit
body (and a `BREAKING CHANGE:` footer).
```

### code-review
```
Run `gds-code-review` in <project_root>, reviewing story {key}, current branch's diff against 
the base branch (excluding `_bmad`, `_bmad-output`, cache files and folders, and obvious non-code 
files), with <story_file> as the spec/story file. 

PERSIST the findings in the story file's `### Review Findings` section (add it if missing) as 
`[Review][Patch|Decision|Defer]` bullets, and copy every `[Review][Defer]` to the cross-story 
ledger `<impl>/deferred-work.md` (its own `deferred_work_file`) under a `## Deferred from: 
code review of {key} (<date>)` heading — create that file if absent.

Do not end on the skill's summary alone. Report: verdict (Approve / Changes Requested / Blocked);
Critical/High/Med/Low counts; the count of open `[Review][Decision]` items (a human call — see
`pipeline.md` Phase 7); `Findings persisted: <N>` = `[Review][*]` bullets now in <story_file>;
`Deferrals logged: <W>` = bullets you added under this story's `## Deferred from:` heading in
`<impl>/deferred-work.md`.
```

### code-review fix
```
Run `gds-dev-story <story_file>` in <project_root>, focused ONLY on the open code-review
findings under the story's `### Review Findings` section: resolve every unresolved `[Review][Patch]`
item, plus each `[Review][Decision]` item for which a human-chosen fix direction is listed below.
Implement each in the stated direction and mark it resolved in place (tick its `[ ]` checkbox if it
has one). NEVER invent a direction for a `[Review][Decision]` item with no chosen direction — leave
it unresolved. Make tests pass. Do not commit.

Resolved decisions (implement exactly these): {decisions}
```
(The orchestrator fills `{decisions}` from the Phase 7 AskUserQuestion answers, or omits the line
when there are none.)

### GDS testing workflow (disabled in V0)

There are no runnable testing delegate entries in Auto-GDS V0. Do not call the old BMM Test
Architect commands from the default pipeline. Future GDS testing integration may add dedicated entries for
`gds-test-design`, `gds-test-automate`, `gds-test-review`, `gds-performance-test`, and
`gds-playtest-plan`, plus framework/scaffold support through `gds-test-framework` and
`gds-e2e-scaffold`.

### generate-project-context
```
Run `gds-generate-project-context` in <project_root>. {bootstrap_intent}
Use sensible defaults for any prompt.
```
The orchestrator fills `{bootstrap_intent}` from the calling phase:
- Phase 2 bootstrap (no `project-context.md` exists yet): `Create project context for the first time`
- Phase 8 refresh (epic-end, file already exists): `Update project-context.md to reflect the
  current stack, patterns, and conventions after epic {e}. BEFORE rewriting, read the accumulated
  retro notes at <auto_gds_dir>/retro-notes/epic-{e}.md (and scan <impl>/deferred-work.md
  for any DURABLE constraint).`

### retrospective
```
Run `gds-retrospective` in <project_root> for epic {e}.
You are the sole facilitator AND participant — answer all party-mode questions yourself using
the accumulated notes at <auto_gds_dir>/retro-notes/epic-{e}.md plus the story files and
sprint-status. Produce the full retrospective document and mark the epic retrospective `done`.
In the structured result, add a `Planning drift` line: if the retro surfaced planning assumptions
the epic proved wrong (PRD / architecture / epic scope that no longer matches what was actually
built), list each as one line — the artifact, what drifted, and whether it is detail-level or
structural — so the orchestrator can recommend a re-sync. Say `none` when the build matched the plan.
```

