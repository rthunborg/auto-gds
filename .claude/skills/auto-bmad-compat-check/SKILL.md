---
name: auto-bmad-compat-check
# Maintainer/utility skill: user-invocable only (run /auto-bmad-compat-check);
# never auto-triggered by the model, so it can't fire mid-pipeline.
disable-model-invocation: true
description: >
  Maintainer tool for the auto-bmad repo itself (run it with
  /auto-bmad-compat-check) — not for end-user BMAD projects. Checks whether new
  BMAD-METHOD releases (the npm `latest` stable and `next` prerelease) are
  compatible with auto-bmad: reports what changed since the last verified
  version, whether it impacts auto-bmad's delegated-skill pipeline, and which new
  skills/features are worth adopting — then offers to update the README/CHANGELOG
  compatibility markers.
---

# BMAD compatibility check

auto-bmad is an orchestrator layered on top of BMAD-METHOD's skills. When BMAD
ships a new version, the only questions that matter are: **did anything we
delegate to or parse change, and is there a new capability we should wire in?**
This skill answers both, grounded in the *published* npm package (what users
actually install) rather than guesswork.

Run it from the **root of the auto-bmad repo** (it reads the repo to find both
the baseline version and the set of skills auto-bmad depends on).

## How it works

A dependency-free helper does the mechanical, error-prone part — resolving
versions, downloading and diffing the published tarballs, and classifying every
changed file against auto-bmad's surface. Your job is the judgement it can't do:
reading the flagged diffs and deciding whether a change *actually* affects us.

### Step 1 — run the helper

```bash
python3 .claude/skills/auto-bmad-compat-check/scripts/bmad_compat.py \
  --report --readme README.md --refs auto-bmad/references/*.md \
  > /tmp/bmad-compat.json
```

- **Baseline** = the last-verified versions, parsed from the README compat
  blockquote (the exact stable + prerelease we last signed off on).
- **Surface** = the BMAD skills auto-bmad delegates to, derived live from
  `auto-bmad/references/*.md` so it never goes stale as the pipeline evolves.
- The script fetches the npm `latest` (stable) and `next` (prerelease) versions,
  diffs `baseline → stable` and `stable → prerelease`, and emits JSON with a
  `summary` plus per-file `impact` entries (each carrying a bounded unified
  `diff` for the changes that matter).

If it can't determine the baseline, pass `--baseline X.Y.Z` explicitly. If the
network is unavailable it exits with a clear error — say so and stop.

### Step 2 — read the classification

Each changed file is tagged by how much it can affect auto-bmad:

| Relevance | Meaning | What you do |
|-----------|---------|-------------|
| **critical** | A delegated skill that *owns a contract auto-bmad parses* changed (e.g. `bmad-create-story` → story `Status:` field; `bmad-sprint-*` → `sprint-status.yaml`; `bmad-generate-project-context` → `project-context.md`; `bmad-code-review` → `### Review Findings`). | **Read the diff.** Decide if the file *format/structure* auto-bmad reads actually changed. Cross-check the parser it would break: `scripts/story_plan.py`, `review_findings.py`, `state_plan.py`. |
| **high** | A delegated skill changed, but not one that owns a parsed contract (e.g. `bmad-dev-story`, the `bmad-testarch-*` family). | Skim the diff for changed invocation flags/modes or removed capabilities auto-bmad's delegation prompts assume (`references/delegation.md`). |
| **low** | A BMAD skill auto-bmad does **not** use changed, or a brand-new skill appeared. | Not a compatibility risk. Assess only as a *new-capability* opportunity (Step 3). |
| **info** | Non-skill file (e.g. `package.json`). | Version noise — ignore. |

Remember the package excludes `docs/` and tests, so a docs-only BMAD release
correctly shows as "nothing shipped" — that's a real *no runtime impact*, not a
gap in the check.

### Step 3 — assess new skills/features

For every entry in each comparison's `new_skills` (and any `low`/off-pipeline
change that looks like a genuinely new capability), ask concretely: **which
auto-bmad phase could use this?** Map it to the pipeline (README "What it does
per story" table) — e.g. a new test-architecture skill might slot into the
TEA-gated phases; a new review layer might strengthen Phase 7. Recommend only
where there's a real fit; say "nothing actionable" when there isn't. Don't
invent uses.

## Report structure

Produce this exact template in chat:

```
# BMAD compatibility check — <YYYY-MM-DD>

## Versions
- Last verified (auto-bmad): <baseline>
- Current stable (npm `latest`): <stable>
- Current prerelease (npm `next`): <prerelease, or "none ahead of stable">

## What changed
<grouped by comparison; bold the delegated/contract changes; one line each.
For docs-only or off-pipeline churn, say so plainly.>

## Impact on auto-bmad
- **Verdict:** none / low / needs-attention / breaking
- <specifics, citing the file + what you concluded from its diff. If a
  contract-owner changed, state explicitly whether the parsed format moved.>

## New skills/features worth considering
- <skill → concrete auto-bmad phase it could improve, or "nothing actionable">

## Recommendation
- <e.g. "Safe to bump the compat marker to <stable>", or "Hold — inspect X first">
```

Lead with the verdict; a maintainer should grasp it in seconds.

## Step 4 — offer to update the markers (only if compatible)

If the verdict is clean (no `critical`/`high` change that actually breaks a
contract), **offer** to update the compatibility markers — never write silently:

1. **README badge** — the shields badge `tested with BMAD-<minor>.x`. Bump only
   on a new minor line (e.g. `6.8.x` → `6.9.x`); a new patch/prerelease alone
   doesn't change it.
2. **README compat blockquote** — rewrite the exact versions to the new stable
   (and prerelease, if any). Keep the contract-based "tested against … couples
   to those skills' contracts rather than a pinned version" framing — that
   wording is *why* a BMAD bump is low-risk; don't reduce it to a bare version.
3. **CHANGELOG `[Unreleased]`** — add a short note only if this is a meaningful
   compatibility statement (a verified new BMAD line). A routine "still
   compatible, nothing changed" check needs no changelog entry.

Note for the user: `scripts/bump-version.py` rewrites auto-bmad's *own* version
badge but **not** these BMAD-compat markers, so they're hand-maintained — which
is exactly what this skill automates.

## Notes

- The `next` tag can lag a fresh stable release; the script only treats it as a
  prerelease when it actually sorts above `latest` (and reports the raw tag).
- Tarball diffing is authoritative for "what shipped" but won't catch a BMAD
  *installer* behavior change (those live in `tools/`, not the skill payload). If
  the user is asking about install/update flow specifically, fall back to
  `gh`-comparing the BMAD repo and the installer notes in `CLAUDE.md`.
- `python3 .claude/skills/auto-bmad-compat-check/scripts/bmad_compat.py --self-test`
  validates the classification logic offline — run it if you change the script.
```
