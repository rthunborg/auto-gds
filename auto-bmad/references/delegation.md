# Delegation prompts

One template per BMAD step. The orchestrator fills the placeholders and sends the result as the
Agent prompt to the profile named in `pipeline.md`. Keep prompts **minimal** — the exact
`/bmad-*` command + the inputs the skill needs. Every prompt ends with the shared autonomy
directive (the `ab-*` profiles already carry it, so the short form below is enough).

**Shared autonomy directive (append to every prompt):**
> Run fully autonomously — answer any interactive BMAD menu/checkpoint with the sensible default
> and never wait for human input. If something genuinely needs a human (missing secret/credential,
> external service, manual action, or an ambiguity that changes the outcome), STOP and report it
> as `needs-human`. Return the structured result: Outcome, Files changed, Status, Open questions,
> Deferred work, Blockers, Retro notes.

Placeholders: `{e}`,`{s}`,`{key}`,`{slug}`,`<story_file>` (absolute), `<impl>`/`<planning>` dirs,
`{project_root}` (absolute cwd).

---

### create-story  → `ab-xhigh`
```
Run `/bmad-create-story {e}-{s}` in {project_root}.
Create the comprehensive story context file for story {e}-{s}. The skill self-validates
against its checklist and auto-fixes — let it; do not add a separate validation pass.
```

### dev-story  → `ab-max`
```
Run `/bmad-dev-story <story_file>` in {project_root}.
Implement the story to completion: all tasks/subtasks done, tests written and passing, story
moved to `review`. Do not commit or branch — the orchestrator handles git.
```

### code-review  → `ab-xhigh` (odd iters) / `ab-fast` (even iters)
```
Run `/bmad-code-review` in {project_root}, reviewing the changes on the current branch for
story <story_file> (review the branch diff against the base branch).
Write the review section and `[AI-Review]` follow-up tasks into the story file. Report the
verdict (Approve / Changes Requested / Blocked) and the High/Med/Low finding counts explicitly.
```

### code-review fix  → `ab-max`
```
Run `/bmad-dev-story <story_file>` in {project_root}, focused ONLY on resolving the open
`[AI-Review]` follow-up tasks added by the latest code review. Make tests pass. Do not commit.
```

### testarch-test-design (epic level)  → `ab-high`
```
Run `/bmad-testarch-test-design` in {project_root}. Choose EPIC-LEVEL mode for epic {e}
(epic + its stories). Produce the epic test plan / risk matrix.
```

### testarch-atdd  → `ab-fast`
```
Run `/bmad-testarch-atdd` in {project_root} for story file <story_file>.
Generate the red-phase acceptance test scaffolds + checklist for this story.
```

### testarch-automate  → `ab-fast`
```
Run `/bmad-testarch-automate` in {project_root} for story file <story_file>.
Expand automated test coverage for the code implemented in this story.
```

### testarch-trace (epic gate)  → `ab-high`
```
Run `/bmad-testarch-trace` in {project_root} for epic {e}. Build the traceability matrix and
produce the quality-gate decision. Report the gate verdict (PASS/CONCERNS/FAIL/WAIVED) + rationale.
```

### testarch-nfr (epic gate)  → `ab-high`
```
Run `/bmad-testarch-nfr` in {project_root} for epic {e}. Audit NFR evidence
(performance/security/reliability/maintainability) for the work completed in this epic.
```

### testarch-test-review (epic gate)  → `ab-high`
```
Run `/bmad-testarch-test-review` in {project_root} with suite scope (the tests added across
epic {e}). Report quality findings + score.
```

### generate-project-context  → `ab-fast`
```
Run `/bmad-generate-project-context` in {project_root}. Update project-context.md to reflect the
current stack, patterns, and conventions after epic {e}. Use sensible defaults for any prompt.
```

### retrospective  → `ab-high`
```
Run `/bmad-retrospective` in {project_root} for epic {e}.
You are the sole facilitator AND participant — answer all party-mode questions yourself using
the accumulated notes at _bmad-output/auto-bmad/retro-notes/epic-{e}.md plus the story files and
sprint-status. Produce the full retrospective document and mark the epic retrospective `done`.
```

### git ops (preflight / branch / commits / finalize / PR) — **not delegated**
Git/PR work is run by the **orchestrator itself**, never by an `ab-*` delegate — so there is no
delegation prompt for it. See `git-and-pr.md` for the exact commands.
