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

Record the chosen set as `tea_selected` in state, with a one-line rationale (which signal drove
it) so the decision is visible in the report and resumable.

### Notes
- Low risk ⇒ `tea_selected = []` and Phases 4 & 6 are skipped — the story still gets full code review.
- `framework` / `ci` are one-time project setup, handled (or skipped) by the first-run flow in
  `state-and-resume.md`, never per story.
- When in doubt between two tiers, pick the higher one — under-testing high-stakes code is worse
  than a little extra coverage.
