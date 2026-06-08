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
- `<review_tmp>` — a throwaway dir the orchestrator makes **outside the work tree** (`mktemp -d`) for
  the code-review fan-out, holding `<diff_file>` (the branch diff it writes) and the three lens
  outputs `<blind_out>` / `<edge_out>` / `<auditor_out>`. Never under `<impl>` or the repo — it must
  not be committable.

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

### code-review  (fan-out — four delegates, not one skill call)
Code-review is **not** delegated as a single `/bmad-code-review` call. That skill internally fans out
to three review subagents, which a delegate cannot do (a sub-agent can't spawn sub-agents — see
`CLAUDE.md` → "Known platform facts"). So the **orchestrator hoists the fan-out** (it is the only level
where fan-out is legal — `CLAUDE.md` → orchestrator-owned actions; `pipeline.md` Phase 7 step 1): it
builds the diff, runs the four entries below — three review lenses, then one triage — and gates
persistence. The orchestrator passes the diff and each lens's findings **by path, never by content** —
it never reads either, so "no code inspection at any tier" holds. All four entries in iteration `i` run
at that iteration's reviewer profile (`code_review_review` on odd `i`, `code_review_review_secondary` on
even — see `pipeline.md`).

**Keep that invariant real for the three lenses:** when you append the shared autonomy directive to a
lens prompt, bind its structured result so finding content stays out of chat — the lens's `Outcome` is
just its output-file path + finding count, and its `Deferred work` / `Retro notes` are `none`. Only
`code-review-triage` reads the findings. (Triage's own report carries counts + verdict — metadata, not
code — which the orchestrator needs for the loop.)

**Diff construction (orchestrator, git — by path, no ingestion).** Make `<review_tmp>` with `mktemp -d`
(outside the work tree), then write the branch diff to `<diff_file>`:
```
git diff <base>...HEAD -- ':(exclude)_bmad' ':(exclude)_bmad-output' \
  ':(exclude)**/__pycache__' ':(exclude)**/*.pyc' ':(exclude)**/.DS_Store' > <diff_file>
```
`<base>` = `git.base_branch` (Phase 0). **Three-dot** = exactly what this branch changed since it
diverged from base. The single-quoted `:(exclude)` pathspecs are read by git, not the shell — safe under
zsh/fish (`CLAUDE.md` → "Shell globs"). "Obvious non-code files" beyond these excludes is **not** a path
rule (it was reviewer judgment) — it is handled in `code-review-triage` (dismiss findings whose only
locus is a lockfile / generated / vendored file). If `<diff_file>` is empty, there is nothing to review.

#### code-review-blind  (Blind Hunter — diff only, unanchored)
```
Run `/bmad-review-adversarial-general` in <project_root> with the diff at <diff_file> as the content to
review. Review ONLY that diff — do NOT open the spec, the story file, or any other project file; your
value is being unanchored by the spec. Write the skill's findings (its markdown list) to <blind_out>.
Report ONLY the path you wrote and your finding count — NOT the findings text.
```

#### code-review-edge  (Edge Case Hunter — diff + project read)
```
Run `/bmad-review-edge-case-hunter` in <project_root> with the diff at <diff_file> as the content to
review (you may read project files the diff references). Write the skill's JSON-array output to
<edge_out>. Report ONLY the path you wrote and your finding count — NOT the findings text.
```

#### code-review-auditor  (Acceptance Auditor — diff + spec)
```
You are an Acceptance Auditor. Review this diff against the spec and context docs. Check for: violations
of acceptance criteria, deviations from spec intent, missing implementation of specified behavior,
contradictions between spec constraints and actual code. Output findings as a Markdown list. Each
finding: one-line title, which AC/constraint it violates, and evidence from the diff.

The diff is at <diff_file>; the spec/story file is <story_file> (load it, plus any docs its `context`
frontmatter lists). Write your findings to <auditor_out>. Report ONLY the path you wrote and your
finding count — NOT the findings text.
```
(The first paragraph is the Acceptance Auditor prompt **verbatim** from the `bmad-code-review` skill's
`step-02-review.md`; keep it in lockstep with upstream — a divergence is the documented cost of
"replicate exactly," see `CLAUDE.md` → orchestrator-owned actions, code-review fan-out.)

#### code-review-triage  (triage + persist — the only code-review delegate that writes findings)
```
Triage a code review of story {key}. Three independent review lenses already ran; their raw findings
are in these files (any may be empty or absent — note each such case as a failed/empty layer):
- Blind Hunter (adversarial markdown list): <blind_out>
- Edge Case Hunter (JSON array — location / trigger_condition / guard_snippet / potential_consequence): <edge_out>
- Acceptance Auditor (markdown list — title / AC-or-constraint / evidence): <auditor_out>
The diff under review is at <diff_file>; the spec/story file is <story_file>. Do NOT re-review — work
from the three files.

TRIAGE:
1. Normalize all findings to a common shape (title, detail, file:line if present, source lens).
2. Deduplicate: merge findings describing the same issue — prefer the one with a concrete file:line,
   fold in the others' detail, mark the merged source (e.g. blind+edge).
3. Classify each into exactly one bucket:
   - Decision — an ambiguous choice that needs a human call; the code can't be correctly patched
     without knowing intent.
   - Patch — a code issue whose correct fix is unambiguous.
   - Defer — real but pre-existing, not caused by this change; not actionable now.
   - Dismiss — noise / false positive / handled elsewhere. ALSO dismiss any finding whose only locus
     is an obvious non-code file (lockfile, generated, vendored, build artifact).
   Drop every Dismiss finding (keep the dismissed count for the report).

PERSIST (this is the deliverable the orchestrator gates on):
- In <story_file>, add/append a `### Review Findings` section with one bullet per surviving finding,
  Decision first, then Patch, then Defer:
    - [ ] [Review][Decision] <title> — <detail>
    - [ ] [Review][Patch] <title> [<file>:<line>]
    - [x] [Review][Defer] <title> [<file>:<line>] — deferred, pre-existing
- Copy every `[Review][Defer]` finding to <impl>/deferred-work.md (create it if absent) under a
  `## Deferred from: code review of {key} (<date>)` heading — one bullet each.

REPORT (chat — the orchestrator reads this, then independently gates the file): verdict (Approve /
Changes Requested / Blocked); Critical/High/Med/Low counts; the count of open `[Review][Decision]`
items (a human call — `pipeline.md` Phase 7); `Findings persisted: <N>` = total `[Review][*]` bullets
you wrote to <story_file>; `Deferrals logged: <W>` = bullets you added under this story's
`## Deferred from:` heading in <impl>/deferred-work.md; `Failed layers: <list or none>`. Do NOT change
the story's Status field, sync sprint-status.yaml, or halt for input — the orchestrator owns those.
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

