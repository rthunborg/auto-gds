# Upstream capability backlog

Upstream BMAD/TEA capabilities auto-bmad has **seen and deliberately deferred** —
"nice, not needed (yet)". This is a maintainer backlog, not a changelog: nothing
here has shipped. Each entry records *why* we passed and a concrete **revisit
trigger** so the decision is re-examined when the ground actually shifts.

The `/auto-bmad-compat-check` skill consults this file in **Step 4** on every run:
for each entry, if that run's diff touches the entry's *Revisit when* trigger, the
reviewer re-surfaces it in the report instead of letting it quietly age out. Add an
entry whenever a compat check concludes "real capability, but no fit today"; remove
one once it ships (with a CHANGELOG note) or is judged a permanent non-fit.

## Open

### Consume upstream `action_items` (sprint-status.yaml)

- **What it is:** `bmad-retrospective` (since `bmad-method` 6.8.1-next.x, PR #2465)
  appends a structured top-level `action_items:` section to `sprint-status.yaml` —
  a list of `epic` / `action` / `owner` / `status` (`open → in-progress → done`)
  entries it updates across epics; `bmad-sprint-status` surfaces the open ones.
- **Why nice:** it's a machine-readable mirror of the retro document's prose
  "Action Items" section that auto-bmad's create-story feed already reads at the
  first story of an epic (`auto-bmad/references/delegation.md`, the retro
  forward-feed). In **epic mode** it could deterministically seed epic N+1 prep
  from epic N's retro instead of relying on the delegate to extract it from prose.
- **Why deferred:** create-story already mines these items from the retro prose, so
  reading the structured field is only a marginal robustness gain — no new
  capability. Purely additive to a file auto-bmad parses (`story_plan.py` stops at
  the `development_status` block boundary), so it is **not** a compatibility risk.
- **Revisit when:** any further `bmad-retrospective` or `bmad-sprint-*` change to
  the `action_items` shape, **or** if we rework the epic-transition forward-feed /
  epic-mode prep (`delegation.md` retro feed, `epic-pipeline.md`) for other reasons
  — at which point consuming the structured field becomes nearly free.
- **First noted:** 2026-06-18 compat check (BMAD `6.8.1-next.14`).
- **Re-confirmed:** 2026-06-21 compat check (BMAD `6.8.1-next.17`, PR #2465) — the
  revisit trigger fired (the `action_items` write/transition rules were hardened and
  three skills now coordinate on the field: `bmad-retrospective` writes,
  `bmad-sprint-planning` carries over, `bmad-sprint-status` surfaces). The field
  *shape* (`epic`/`action`/`owner`/`status`) is unchanged, so the deferral stands.
