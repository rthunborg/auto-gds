# Delegation prompts

**This file is the single source of truth for what each BMAD step runs** — its exact `/bmad-*`
command, prompt body, and the placeholders below. One entry per step, named by its heading (e.g.
`create-story`); `pipeline.md` references each by heading name and never repeats the command, so a
command changes here and nowhere else. Git/PR steps are not delegated and have no entry here — the
orchestrator runs them; see `git-and-pr.md`.

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
- `<story_file>` — absolute path `<impl>/{key}.md` (from `story_plan.py`).

---

### create-story
```
Run `/bmad-create-story {e}-{s}` in <project_root>.
Create the comprehensive story context file for story {e}-{s}.
{retro_notes_hint}
{deferred_work_hint}
```
The orchestrator fills `{retro_notes_hint}` from on-disk state:
- If `_bmad-output/auto-bmad/retro-notes/epic-{e}.md` exists and is non-empty (earlier stories in
  this epic have landed signal): `BEFORE drafting the story context, ALSO read
  _bmad-output/auto-bmad/retro-notes/epic-{e}.md and treat each '## Story <key>' section's bullets
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
`<impl>/deferred-work.md` is BMAD's own code-review/quick-dev defer sink (append-only,
project-wide, keyed by `## Deferred from: <source> (<date>)` headings) — no BMAD or TEA skill
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
Run `/bmad-dev-story <story_file>` in <project_root>.
Implement the story to completion: all tasks/subtasks done, tests written and passing, story
moved to `review`. Do not commit or branch — the orchestrator handles git.
When done, report a short summary of what you built plus any deviations, key decisions, and
deferred work — and any breaking change you introduce (a changed/removed public interface, config
key, schema, CLI flag, or required migration step). The orchestrator records these in the commit
body (and a `BREAKING CHANGE:` footer).
```

### code-review
```
Run `/bmad-code-review` in <project_root>, reviewing the current branch's diff against the base
branch, with <story_file> as the spec/story file. 

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
Run `/bmad-dev-story <story_file>` in <project_root>, focused ONLY on the open code-review
findings under the story's `### Review Findings` section: resolve every unresolved `[Review][Patch]`
item, plus each `[Review][Decision]` item for which a human-chosen fix direction is listed below.
Implement each in the stated direction and mark it resolved in place (tick its `[ ]` checkbox if it
has one). NEVER invent a direction for a `[Review][Decision]` item with no chosen direction — leave
it unresolved. Make tests pass. Do not commit.

Resolved decisions (implement exactly these): {decisions}
```
(The orchestrator fills `{decisions}` from the Phase 7 AskUserQuestion answers, or omits the line
when there are none.)

### testarch-test-design (epic level)
```
Run `/bmad-testarch-test-design` in <project_root>. Choose EPIC-LEVEL mode for epic {e}
(epic + its stories). Produce the epic test plan / risk matrix.
```

### testarch-atdd
```
Run `/bmad-testarch-atdd` in <project_root> for story file <story_file>.
Generate the red-phase acceptance test scaffolds + checklist for this story.
```

### testarch-automate
```
Run `/bmad-testarch-automate` in <project_root> for story file <story_file>.
Expand automated test coverage for the code implemented in this story.
```
(Phase 8 trace-gate remediation reuses this skill at **epic scope**: pass epic {e} instead of a
single story file and target the specific coverage gaps the trace gate reported.)

### testarch-trace (epic gate)
```
Run `/bmad-testarch-trace` in <project_root> for epic {e}. Build the traceability matrix and
produce the quality-gate decision. Report the gate verdict (PASS/CONCERNS/FAIL/WAIVED) + rationale.
If the verdict is not PASS, also list the specific requirements / acceptance criteria left
uncovered, so the orchestrator can summarize them for the human and target remediation.
```

### testarch-trace (story advisory)
```
Run `/bmad-testarch-trace` in <project_root> for story file <story_file> — STORY SCOPE: trace
ONLY this story's acceptance criteria, not the whole epic. Build the story-level traceability
matrix (each AC -> its covering test(s)) and report the verdict (PASS/CONCERNS/FAIL) plus the
specific ACs left uncovered. This is an ADVISORY pass: its job is to surface coverage gaps early
so they are visible at review time — do NOT block, remediate, or open a gate; just report.
```
(Same skill as the epic gate, narrowed to one story and stripped of gate semantics. The blocking
quality gate stays at epic end — see `tea-policy.md` → "Long-epic trace advisory".)

### testarch-nfr (epic gate)
```
Run `/bmad-testarch-nfr` in <project_root> for epic {e}. Audit NFR evidence
(performance/security/reliability/maintainability) for the work completed in this epic.
```

### testarch-test-review (epic gate)
```
Run `/bmad-testarch-test-review` in <project_root> with suite scope (the tests added across
epic {e}). Report quality findings + score.
```

### generate-project-context
```
Run `/bmad-generate-project-context` in <project_root>. {bootstrap_intent}
Use sensible defaults for any prompt.
```
The orchestrator fills `{bootstrap_intent}` from the calling phase:
- Phase 2 bootstrap (no `project-context.md` exists yet): `Create project context for the first time`
- Phase 8 refresh (epic-end, file already exists): `Update project-context.md to reflect the
  current stack, patterns, and conventions after epic {e}. BEFORE rewriting, read the accumulated
  retro notes at _bmad-output/auto-bmad/retro-notes/epic-{e}.md (and scan <impl>/deferred-work.md
  for any DURABLE constraint).`

### retrospective
```
Run `/bmad-retrospective` in <project_root> for epic {e}.
You are the sole facilitator AND participant — answer all party-mode questions yourself using
the accumulated notes at _bmad-output/auto-bmad/retro-notes/epic-{e}.md plus the story files and
sprint-status. Produce the full retrospective document and mark the epic retrospective `done`.
In the structured result, add a `Planning drift` line: if the retro surfaced planning assumptions
the epic proved wrong (PRD / architecture / epic scope that no longer matches what was actually
built), list each as one line — the artifact, what drifted, and whether it is detail-level or
structural — so the orchestrator can recommend a re-sync. Say `none` when the build matched the plan.
```

