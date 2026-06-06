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
  version (diffing the published packages and cross-referencing the BMAD repo's
  release notes and post-stable commits), whether it impacts auto-bmad's
  delegated-skill pipeline, and which new skills/features are worth adopting —
  then offers to update the README/CHANGELOG compatibility markers.
---

# BMAD compatibility check

auto-bmad is an orchestrator layered on top of BMAD-METHOD's skills. When BMAD
ships a new version, the only questions that matter are: **did anything we
delegate to or parse change, and is there a new capability we should wire in?**
This skill answers both, grounded in the *published* npm package (what users
actually install) rather than guesswork.

Run it from the **root of the auto-bmad repo** (it reads the repo to find both
the baseline versions and the set of skills auto-bmad depends on).

It checks **incrementally**: each line is diffed only from where you last left
off — last-checked stable → current stable, and last-checked prerelease →
current prerelease — so a run only ever surfaces what is *genuinely new since the
last check*, never re-litigating churn you already signed off on. The store for
"where you last left off" is the **README compat blockquote itself** (it records
both versions); Step 5's marker update is what advances that baseline for next
time. There is no separate state file to drift.

## How it works

A dependency-free helper does the mechanical, error-prone part — resolving
versions, downloading and diffing the published tarballs, and classifying every
changed file against auto-bmad's surface. Your job is the judgement it can't do:
reading the flagged diffs, cross-checking the repo's release notes and
post-stable commits (Step 3), and deciding whether a change *actually* affects us.

### Step 1 — run the helper

```bash
python3 .claude/skills/auto-bmad-compat-check/scripts/bmad_compat.py \
  --report --readme README.md --refs auto-bmad/references/*.md \
  > /tmp/bmad-compat.json
```

- **Baseline** = the last-checked versions (stable *and* prerelease), parsed from
  the README compat blockquote — the exact pair we last signed off on.
- **Surface** = the BMAD skills auto-bmad delegates to, derived live from
  `auto-bmad/references/*.md` so it never goes stale as the pipeline evolves.
- The script fetches the npm `latest` (stable) and `next` (prerelease) versions
  and diffs **incrementally**, each line anchored at the highest version you've
  already checked below it:
  - *prerelease line* → from the higher of `{current stable, last-checked
    prerelease}`. So `next.1 → next.2` shows *only* `next.1 → next.2`, not the
    whole `stable → next.2`.
  - *stable line* → from the higher of `{last-checked stable, a last-checked
    prerelease that has since graduated into this stable}`. So when `6.8.1` ships
    after you reviewed `6.8.1-next.2`, you see *only* the `next.2 → 6.8.1` sliver,
    not the whole `prev_stable → 6.8.1` (which would re-show everything you already
    reviewed as prereleases).
  A comparison is **omitted entirely** when nothing is new on that line (stable
  unchanged, or the prerelease hasn't moved / has graduated) — an empty
  `comparisons` list means `up-to-date`. Output is JSON with a `summary` plus per-file `impact` entries
  (each carrying a bounded unified `diff` for the changes that matter). Each
  comparison also carries `from_git_head` / `to_git_head` — the exact source
  commits npm built its endpoints from — for the precise repo cross-check in
  Step 3.

If it can't determine a baseline from the README, pass `--baseline X.Y.Z` and/or
`--prev-prerelease X.Y.Z-next.N` explicitly. If a recorded prerelease has since
been unpublished from npm, the script degrades gracefully — it re-anchors that
line at the current stable and records why in `prerelease_anchor_note`. If the
network is unavailable it exits with a clear error — say so and stop.

### Step 2 — read the classification

Each changed file is tagged by how much it can affect auto-bmad:

| Relevance | Meaning | What you do |
|-----------|---------|-------------|
| **critical** | A delegated skill that *owns a contract auto-bmad parses* changed (e.g. `bmad-create-story` → story `Status:` field; `bmad-sprint-*` → `sprint-status.yaml`; `bmad-generate-project-context` → `project-context.md`; `bmad-code-review` → `### Review Findings`). | **Read the diff.** Decide if the file *format/structure* auto-bmad reads actually changed. Cross-check the parser it would break: `scripts/story_plan.py`, `review_findings.py`, `state_plan.py`. |
| **high** | A delegated skill changed, but not one that owns a parsed contract (e.g. `bmad-dev-story`, the `bmad-testarch-*` family). | Skim the diff for changed invocation flags/modes or removed capabilities auto-bmad's delegation prompts assume (`references/delegation.md`). |
| **low** | A BMAD skill auto-bmad does **not** use changed, or a brand-new skill appeared. | Not a compatibility risk. Assess only as a *new-capability* opportunity (Step 4). |
| **info** | Non-skill file (e.g. `package.json`). | Version noise — ignore. |

Remember the package excludes `docs/` and tests, so a docs-only BMAD release
correctly shows as "nothing shipped" — that's a real *no runtime impact*, not a
gap in the check.

### Step 3 — cross-check the BMAD repo history

The tarball diff is authoritative for **what file formats shipped**, but blind to
two things that decide compatibility just as much: changes the maintainers *flag*
as breaking, and anything under `tools/` (the installer) — which the published
package excludes. Read the repo to close both gaps. This **complements** the
diff; don't re-narrate it.

Repo `bmad-code-org/BMAD-METHOD` — tags are `vX.Y.Z`, default branch `main`.

- **baseline → stable — release notes.** Enumerate every release newer than the
  baseline up to and including the stable (`gh release list`, then
  `gh release view v<X.Y.Z> --repo bmad-code-org/BMAD-METHOD --json body`) — not
  just `v<stable>`, since the baseline can lag a minor or more. Look for the
  **💥 Breaking Changes / deprecations** callout and for installer/`tools/`
  **🐛 Fixes** the payload diff can't surface. Cross-check any installer note
  against `CLAUDE.md` "Known platform facts" — the README "Updating" guidance
  keys off exactly these.
- **prerelease line — exact commit window via `gitHead`.** The `next` prerelease
  carries no git tag, but npm stamps the **exact source commit** it was built from
  into each version's metadata — the script surfaces it as `from_git_head` /
  `to_git_head` on the prerelease comparison. Use those to read the *precise*
  commit window that produced the incremental diff:
  `gh api repos/bmad-code-org/BMAD-METHOD/compare/<from_git_head>...<to_git_head>
  --jq '.commits[].commit.message'`. This is tight — it spans only the
  last-checked prerelease → current prerelease, not the whole `v<stable>...main`
  (which can be **ahead of** the published `next`, and re-includes commits you
  reviewed on a prior run). A `src/`-touching commit is already in the diff; its
  value here is the **intent** behind it. The payoff is the **`tools/`-only**
  commits the package never carries.
  - *Fallback:* if `from_git_head`/`to_git_head` are null (an older publish that
    predates npm `gitHead`) **or the `compare` 404s** (commit squash-rewritten or
    force-pushed off `main`), fall back to `compare/v<stable>...main` and manually
    ignore commits at or before the last-checked prerelease.

If `gh` is unauthenticated or offline, say so and **fall through to the
tarball-only verdict** — this step sharpens judgement, it isn't a gate.

### Step 4 — assess new skills/features

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
- Last checked (auto-bmad): <baseline stable> + <prev_prerelease, or "no prerelease recorded">
- Current stable (npm `latest`): <stable, or "unchanged since last check">
- Current prerelease (npm `next`): <prerelease, "unchanged since last check", or "none ahead of stable">

## What changed
<grouped by comparison — and note which line each is (stable vs prerelease) and
its actual `from → to`, since the prerelease diff is incremental. Bold the
delegated/contract changes; one line each. Draw on the Step 3 release notes
(stable) and post-stable commits (prerelease) for the *why*. For docs-only or
off-pipeline churn, say so plainly. If `comparisons` is empty (verdict
`up-to-date`), say plainly that nothing is new on either line since the last
check — that is the whole point of the incremental check.>

## Impact on auto-bmad
- **Verdict:** none / low / needs-attention / breaking
- <specifics, citing the file + what you concluded from its diff. If a
  contract-owner changed, state explicitly whether the parsed format moved.>
- <repo cross-check (Step 3): any maintainer-flagged breaking change or
  deprecation, and any `tools/` installer change — note whether it touches
  auto-bmad's delegation or the README "Updating" guidance.>

## New skills/features worth considering
- <skill → concrete auto-bmad phase it could improve, or "nothing actionable">

## Recommendation
- <e.g. "Safe to advance the markers to <stable> + <prerelease>", "Already
  up-to-date — nothing new since last check", or "Hold — inspect X first">
```

Lead with the verdict; a maintainer should grasp it in seconds.

## Step 5 — offer to update the markers (only if compatible)

If the verdict is clean (no `critical`/`high` change that actually breaks a
contract), **offer** to update the compatibility markers — never write silently:

1. **README badge** — the shields badge `tested with BMAD-<minor>.x`. Bump only
   on a new minor line (e.g. `6.8.x` → `6.9.x`); a new patch/prerelease alone
   doesn't change it.
2. **README compat blockquote** — rewrite the exact versions to the new stable
   **and** the new prerelease. This blockquote **is the store** the next run
   reads as its baseline, so always advance *both* versions you just checked —
   even a prerelease-only bump (`next.1 → next.2`) must be recorded, or the next
   run re-diffs ground you already covered. Keep the contract-based "tested
   against … couples to those skills' contracts rather than a pinned version"
   framing — that wording is *why* a BMAD bump is low-risk; don't reduce it to a
   bare version.
3. **CHANGELOG `[Unreleased]`** — add a short note only if this is a meaningful
   compatibility statement (a verified new BMAD line). A routine "still
   compatible, nothing changed" check — including a benign prerelease-marker
   advance — needs no changelog entry.

Note for the user: `scripts/bump-version.py` rewrites auto-bmad's *own* version
badge but **not** these BMAD-compat markers, so they're hand-maintained — which
is exactly what this skill automates.

## Notes

- The `next` tag can lag a fresh stable release; the script only treats it as a
  prerelease when it actually sorts above `latest` (and reports the raw tag).
- The check is **incremental and stateful via the README** (Step 1): each line is
  diffed only from the highest version you've already checked below it, so nothing
  is ever reviewed twice. The prerelease line anchors at the higher of `{current
  stable, last-checked prerelease}`; the stable line, symmetrically, anchors at a
  last-checked prerelease once it has *graduated* into the stable (diffing just the
  prerelease→final sliver). A recorded prerelease that npm has since unpublished
  degrades to a durable stable anchor (`stable_anchor_note` /
  `prerelease_anchor_note`) rather than crashing.
- Tarball diffing is authoritative for "what shipped" but won't catch a BMAD
  *installer* behavior change (those live in `tools/`, not the skill payload) —
  which is exactly why Step 3 reads the release notes and post-stable commits.
  Weigh any installer finding against the install/update notes in `CLAUDE.md`.
- `python3 .claude/skills/auto-bmad-compat-check/scripts/bmad_compat.py --self-test`
  validates the classification logic offline — run it if you change the script.
```
