# TEA selection policy

Applies only when `tea.enabled` is true in config. Two layers:

## 1. Epic-level skills — ALWAYS ON (when TEA enabled)
- **Epic start** (`is_first_in_epic`): `bmad-testarch-test-design` (epic level).
- **Epic end** (`is_last_in_epic`): `bmad-testarch-trace` (gate) → `bmad-testarch-nfr` →
  `bmad-testarch-test-review`.

## 2. Per-story skills — RISK-BASED (triage in Phase 0)
`bmad-testarch-atdd` (before dev) and `bmad-testarch-automate` (after dev) are selected per
story based on a quick risk classification.

### Risk classification
Look at the story's epic entry / acceptance criteria / described scope and score the signals:

**High** — any of:
- authentication, authorization, sessions, secrets, crypto, or permissions
- money/payments/billing, or other irreversible side effects
- data integrity: schema/DB migrations, deletes, bulk mutations
- public/external API surface or contract changes
- security-sensitive input handling (uploads, parsing, deserialization, SSRF/XSS/SQLi surface)
- concurrency, scheduling, or other hard-to-reproduce behavior

**Medium** — none of the above, but the story:
- adds/changes business logic or non-trivial branching
- adds an internal endpoint/service method or stateful UI flow
- touches multiple modules

**Low (trivial)** — copy/docs, config/constants, styling-only, comments, dependency bumps with
no behavior change, or pure scaffolding with no logic.

### Selection matrix
| Risk | atdd (pre-dev) | automate (post-dev) |
|------|----------------|---------------------|
| High | yes | yes |
| Medium | no | yes |
| Low | no | no |

Record the classified level as `tea_risk` (`low|med|high`) **and** the chosen set as `tea_selected`
in state, with a one-line rationale (which signal drove it) so the decision is visible in the report
and resumable. (`tea_risk` is what the long-epic trace advisory below gates on — keep it explicit
rather than re-deriving the level from `tea_selected`.)

## 3. Long-epic trace advisory — per-story, NON-BLOCKING (opt-out)
A story-scope `bmad-testarch-trace` pass that runs at the **tail of Phase 7** (after the code-review
loop converges) to surface this story's uncovered acceptance criteria *while the dev context is
still fresh and the PR is still open* — instead of waiting for the epic-end trace gate, which on a
long epic can be many stories away. It is **advisory only**: it records gaps, never halts,
remediates, asks, or forces a draft PR. The blocking gate stays at epic end (§1).

Select `trace-advisory` (add it to `tea_selected`) at Phase-0 triage **iff all** of:
- `tea.enabled` **and** `tea.story_trace_advisory.enabled` (default true), **and**
- `tea_risk == high` — only stories where an uncovered AC is genuinely costly justify the extra pass, **and**
- `stories_after_in_epic >= tea.story_trace_advisory.skip_last_stories` (default 3) — **skip the
  last few stories of the epic.** Their distance to the epic-end trace gate is already tiny, so an
  advisory there is near-duplication of the gate that is about to run (and the last story would
  double the gate outright). Gating on *distance to the epic's end* — rather than the old
  `is_last_in_epic` flag — keeps the advisory exactly where it pays off (the early-to-middle stories,
  whose gaps would otherwise stay hidden longest) and drops only the redundant tail.
  `stories_after_in_epic` is how many stories in this epic come after this one (0 for the last, 1 for
  second-to-last, …), so `>= 3` skips the last three and subsumes the old is-last clause, **and**
- `epic_story_count >= tea.story_trace_advisory.min_epic_stories` (default 6) — **this is the
  long-epic gate.** The advisory's only value is shrinking the distance from "gap introduced" to
  "gap noticed"; on a short epic that distance is already tiny (the epic-end gate is right there), so
  it would be pure overhead. On a long epic a high-risk gap in story 2 would otherwise stay hidden
  until the story-12 gate — context gone, PRs merged. The threshold is what makes this feature
  **dormant on normal short epics and self-activating only on the long ones that need it.**

`epic_story_count` and `stories_after_in_epic` both come from the same `story_plan.py` read that
sets `is_first_in_epic`/`is_last_in_epic` (`stories_after_in_epic` = epic stories ordered after this
one); record both in state alongside `tea_risk`.

### Notes
- Low risk ⇒ `tea_selected = []` and Phases 4 & 6 are skipped — the story still gets full code review.
- `framework` / `ci` are one-time project setup, handled (or skipped) by the first-run flow in
  `state-and-resume.md`, never per story.
- When in doubt between two tiers, pick the higher one — under-testing high-stakes code is worse
  than a little extra coverage.
