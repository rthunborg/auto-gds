---
name: auto-bmad-compat-check
# Maintainer/utility skill: user-invocable only (run /auto-bmad-compat-check);
# never auto-triggered by the model, so it can't fire mid-pipeline.
disable-model-invocation: true
description: >
  Maintainer tool for the auto-bmad repo itself (run it with
  /auto-bmad-compat-check) — not for end-user BMAD projects. Checks whether new
  releases of the two npm packages auto-bmad delegates into — `bmad-method` (the
  core BMM line) and `bmad-method-test-architecture-enterprise` (the separately
  versioned TEA test-architecture module) — are compatible with auto-bmad, for
  each package's `latest` stable and `next` prerelease: reports what changed since
  the last verified version (diffing the published packages and cross-referencing
  each repo's release notes and post-stable commits), whether it impacts
  auto-bmad's delegated-skill pipeline, and which new skills/features are worth
  adopting — then offers to update the README/CHANGELOG compatibility markers.
---

# BMAD compatibility check

auto-bmad is an orchestrator layered on top of BMAD skills, and it delegates into
**two separately versioned npm packages**: `bmad-method` (the core BMM line —
create-story/dev-story/code-review/…) and `bmad-method-test-architecture-enterprise`
(the **TEA** module — the `bmad-testarch-*` skills that run in the TEA-gated
phases, on their own `v1.x` line). When either ships a new version, the only
questions that matter are: **did anything we delegate to or parse change, and is
there a new capability we should wire in?** This skill answers both for both
packages in one run, grounded in the *published* npm packages (what users actually
install) rather than guesswork.

Run it from the **root of the auto-bmad repo** (it reads the repo to find both
packages' baseline versions and the set of skills auto-bmad depends on).

It checks **incrementally and per-package**: for each package, each line is diffed
only from where you last left off — last-checked stable → current stable, and
last-checked prerelease → current prerelease — so a run only ever surfaces what is
*genuinely new since the last check*, never re-litigating churn you already signed
off on. The store for "where you last left off" is the **README compat blockquote
itself**, which records a clause per package (BMAD-METHOD versions + TEA versions);
Step 5's marker update advances *both* baselines for next time. There is no
separate state file to drift.

> The two packages have **independent** version lines (BMAD `v6.x`, TEA `v1.x`)
> and need not share a prerelease — TEA's `next` can sort *below* its own stable,
> leaving its clause with no `-next`. The helper windows each package's baseline to
> its own clause (by repo URL) precisely so one package's prerelease is never read
> as the other's; you never have to disentangle them by hand.

## How it works

A dependency-free helper does the mechanical, error-prone part — resolving
versions for **both packages**, downloading and diffing the published tarballs, and
classifying every changed file against auto-bmad's surface. Your job is the
judgement it can't do: reading the flagged diffs, cross-checking each repo's
release notes and post-stable commits (Step 3), and deciding whether a change
*actually* affects us.

### Step 1 — run the helper

```bash
python3 .claude/skills/auto-bmad-compat-check/scripts/bmad_compat.py \
  --report --readme README.md --refs auto-bmad/references/*.md \
  > /tmp/bmad-compat.json
```

One run covers both packages: the output is `{ "verdict": <worst-of>, "packages":
[ <bmad-method report>, <TEA report> ] }`. Each per-package report has the same
shape the rest of this doc describes (its own `baseline`/`stable`/`prerelease`,
`comparisons`, and `summary.verdict`); the top-level `verdict` is the
most-attention-needing of the two, so a TEA break can't hide behind a clean BMAD
line. A package whose baseline can't be resolved becomes an `error` entry instead
of aborting the run.

- **Baseline** = the last-checked versions (stable *and* prerelease) for each
  package, parsed from its clause in the README compat blockquote — the exact pair
  we last signed off on. (`--baseline`/`--prev-prerelease` override the
  `bmad-method` pair; `--tea-baseline`/`--tea-prev-prerelease` override TEA's.)
- **Surface** = the BMAD skills auto-bmad delegates to (`bmad-*` including the
  `bmad-testarch-*` family), derived live from `auto-bmad/references/*.md` so it
  never goes stale as the pipeline evolves. The *same* surface is applied to both
  packages — each tarball only contains its own skills, so it self-scopes.
- For **each package**, the script fetches the npm `latest` (stable) and `next`
  (prerelease) versions and diffs **incrementally**, each line anchored at the
  highest version you've already checked below it:
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

If it can't determine a package's baseline from the README, pass that package's
explicit override (`--baseline`/`--prev-prerelease` for `bmad-method`,
`--tea-baseline`/`--tea-prev-prerelease` for TEA). If a recorded prerelease has
since been unpublished from npm, the script degrades gracefully — it re-anchors
that line at the current stable and records why in `prerelease_anchor_note`. If the
network is unavailable it exits with a clear error — say so and stop.

### Step 2 — read the classification

Each changed file is tagged by how much it can affect auto-bmad:

| Relevance | Meaning | What you do |
|-----------|---------|-------------|
| **critical** | A delegated skill that *owns a contract auto-bmad parses* changed (e.g. `bmad-create-story` → story `Status:` field; `bmad-sprint-*` → `sprint-status.yaml`; `bmad-generate-project-context` → `project-context.md`; `bmad-code-review` → `### Review Findings` **plus its replicated internals** — see below; `bmad-review-adversarial-general` / `bmad-review-edge-case-hunter` → the lens output shapes the triage prompt parses). | **Read the diff.** Decide if the file *format/structure* auto-bmad reads actually changed. Cross-check the parser it would break: `scripts/story_plan.py`, `review_findings.py`, `state_plan.py`. **For the code-review fan-out** (auto-bmad replicates `bmad-code-review`'s *internal* structure, since a delegate can't spawn its three review subagents): diff `bmad-code-review`'s `steps/step-02` + `steps/step-03` and the two `bmad-review-*` skills against the replica in `references/delegation.md` (the `code-review (fan-out)` entries) — a changed lens roster, inline Acceptance Auditor prompt, edge-hunter JSON shape, or triage rubric must be mirrored there. **Two parts of the replica are auto-bmad-LOCAL additions with no upstream counterpart** (fenced with `auto-bmad-local` comments): the `code-review-security` delegate and the triage security-severity-map + Low keep/drop block. Do NOT treat their absence upstream as drift, and never remove them when reconciling — only the surrounding mirrored structure tracks upstream. |
| **high** | A delegated skill changed, but not one that owns a parsed contract (e.g. `bmad-dev-story`; the `bmad-testarch-*` family — which lives in the **TEA** package, so it surfaces in that package's report). | Skim the diff for changed invocation flags/modes or removed capabilities auto-bmad's delegation prompts assume (`references/delegation.md`). |
| **low** | A BMAD skill auto-bmad does **not** use changed, or a brand-new skill appeared. | Not a compatibility risk. Assess only as a *new-capability* opportunity (Step 4). |
| **info** | Non-skill file (e.g. `package.json`). | Version noise — ignore. |

The relevance tiers are identical for both packages — `bmad-method` and TEA share
one classifier and one surface. The `bmad-testarch-*` skills are **high**, not
contract-owners: auto-bmad's TEA gate reads the trace verdict (`PASS`/`CONCERNS`/
`FAIL`) by *delegate return*, not by parsing a file format, so there's no parser to
silently break — only invocation flags/modes to watch.

Remember the packages exclude `docs/` and tests, so a docs-only release (in either
package) correctly shows as "nothing shipped" — that's a real *no runtime impact*,
not a gap in the check.

### Step 3 — cross-check each repo's history

The tarball diff is authoritative for **what file formats shipped**, but blind to
two things that decide compatibility just as much: changes the maintainers *flag*
as breaking, and anything under `tools/` (the installer) — which the published
package excludes. Read each repo to close both gaps, **per package** — a TEA-only
release notes its breaking changes in the TEA repo, not BMAD-METHOD's. This
**complements** the diff; don't re-narrate it.

Repos (both: tags `vX.Y.Z`, default branch `main`, npm stamps `gitHead` per
version):
- `bmad-method` → `bmad-code-org/BMAD-METHOD`
- TEA → `bmad-code-org/bmad-method-test-architecture-enterprise`

Use the `repo` field on each per-package report as the `--repo` for the `gh`
commands below.

- **baseline → stable — release notes.** Enumerate every release newer than the
  baseline up to and including the stable (`gh release list --repo <repo>`, then
  `gh release view v<X.Y.Z> --repo <repo> --json body`) — not
  just `v<stable>`, since the baseline can lag a minor or more. Look for the
  **💥 Breaking Changes / deprecations** callout and for installer/`tools/`
  **🐛 Fixes** the payload diff can't surface. Cross-check any installer note
  against `CLAUDE.md` "Known platform facts" — the README "Updating" guidance
  keys off exactly these. (For a TEA-only bump, `<repo>` is the TEA repo; its
  releases describe testarch changes, not BMM ones.)
- **prerelease line — exact commit window via `gitHead`.** The `next` prerelease
  carries no git tag, but npm stamps the **exact source commit** it was built from
  into each version's metadata — the script surfaces it as `from_git_head` /
  `to_git_head` on the prerelease comparison (both packages stamp it). Use those to
  read the *precise* commit window that produced the incremental diff:
  `gh api repos/<repo>/compare/<from_git_head>...<to_git_head>
  --jq '.commits[].commit.message'`. This is tight — it spans only the
  last-checked prerelease → current prerelease, not the whole `v<stable>...main`
  (which can be **ahead of** the published `next`, and re-includes commits you
  reviewed on a prior run). A `src/`-touching commit is already in the diff; its
  value here is the **intent** behind it. The payoff is the **`tools/`-only**
  commits the package never carries.
  - *Fallback:* if `from_git_head`/`to_git_head` are null (an older publish that
    predates npm `gitHead`) **or the `compare` 404s** (commit squash-rewritten or
    force-pushed off `main`), fall back to `repos/<repo>/compare/v<stable>...main`
    and manually ignore commits at or before the last-checked prerelease.

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

Produce this exact template in chat. The body is **per package** — repeat the
`### <package>` block for `bmad-method` and TEA, then close with one combined
recommendation. Lead with the combined headline (the top-level `verdict`).

```
# BMAD compatibility check — <YYYY-MM-DD>

**Combined verdict:** <top-level `verdict`: up-to-date / compatible /
review-opportunities / needs-attention> — <one clause naming which package drove
it, if any>

### BMAD-METHOD (`bmad-method`)

#### Versions
- Last checked (auto-bmad): <baseline stable> + <prev_prerelease, or "no prerelease recorded">
- Current stable (npm `latest`): <stable, or "unchanged since last check">
- Current prerelease (npm `next`): <prerelease, "unchanged since last check", or "none ahead of stable">

#### What changed
<grouped by comparison — and note which line each is (stable vs prerelease) and
its actual `from → to`, since the prerelease diff is incremental. Bold the
delegated/contract changes; one line each. Draw on the Step 3 release notes
(stable) and post-stable commits (prerelease) for the *why*. For docs-only or
off-pipeline churn, say so plainly. If this package's `comparisons` is empty
(verdict `up-to-date`), say plainly that nothing is new on either line since the
last check — that is the whole point of the incremental check.>

#### Impact on auto-bmad
- **Verdict:** <this package's `summary.verdict`>
- <specifics, citing the file + what you concluded from its diff. If a
  contract-owner changed, state explicitly whether the parsed format moved.>
- <repo cross-check (Step 3): any maintainer-flagged breaking change or
  deprecation, and any `tools/` installer change — note whether it touches
  auto-bmad's delegation or the README "Updating" guidance.>

#### New skills/features worth considering
- <skill → concrete auto-bmad phase it could improve, or "nothing actionable">

### TEA test-architecture (`bmad-method-test-architecture-enterprise`)

<the same four #### subsections for the TEA package. If the report entry is an
`error` (baseline unresolved), say so plainly and stop the per-package detail.>

## Recommendation
- <combined — e.g. "Safe to advance both markers (BMAD <stable>+<pre>, TEA
  <stable>+<pre>)", "Already up-to-date — nothing new on either package", or
  "Hold — inspect X in <package> first". Be explicit about *which* package(s) the
  marker advance covers, since they move independently.>
```

Lead with the combined verdict; a maintainer should grasp it in seconds. When one
package is `up-to-date` and the other isn't, keep the quiet package's block to a
single "unchanged since last check" line — don't pad it.

## Step 5 — offer to update the markers (only if compatible)

If a package's verdict is clean (no `critical`/`high` change that actually breaks a
contract), **offer** to update its compatibility markers — never write silently.
The two packages advance **independently**: update only the package(s) you actually
re-verified clean. Markers, per package:

1. **README badge** — the shields badge (`tested with BMAD-<minor>.x` /
   `tested with TEA-<minor>.x`). Bump only on a new minor line (e.g. `6.8.x` →
   `6.9.x`, or `1.19.x` → `1.20.x`); a new patch/prerelease alone doesn't change it.
2. **README compat blockquote** — rewrite the exact versions in **that package's
   clause** to the new stable **and** the new prerelease. This blockquote **is the
   store** the next run reads as its baseline (windowed per package by repo URL —
   keep each clause's versions *after* its repo link, or the parser won't find
   them), so always advance *both* versions you just checked for that package —
   even a prerelease-only bump (`next.1 → next.2`) must be recorded, or the next
   run re-diffs ground you already covered. (If a package's `next` sorts below its
   own stable, it has no prerelease to record — leave its clause prerelease-less,
   as TEA's is today.) Keep the contract-based "couples to those skills' contracts
   rather than pinned versions" framing — that wording is *why* a bump is low-risk;
   don't reduce it to a bare version. Touch only the clause(s) you re-verified;
   leave the other package's clause byte-for-byte intact.
3. **CHANGELOG `[Unreleased]`** — add a short note only if this is a meaningful
   compatibility statement (a verified new BMAD or TEA line — name which). A
   routine "still compatible, nothing changed" check — including a benign
   prerelease-marker advance — needs no changelog entry.

Note for the user: `scripts/bump-version.py` rewrites auto-bmad's *own* version
badge but **not** these BMAD/TEA-compat markers, so they're hand-maintained —
which is exactly what this skill automates.

## Notes

- **Two packages, one run.** `bmad-method` and TEA
  (`bmad-method-test-architecture-enterprise`) are checked together and folded into
  a worst-of headline verdict; everything below applies to each package's own line.
  TEA is the home of the `bmad-testarch-*` skills — a TEA release with no BMM change
  still matters, which is the whole reason it's tracked here.
- The `next` tag can lag a fresh stable release; the script only treats it as a
  prerelease when it actually sorts above that package's `latest` (and reports the
  raw tag). TEA's `next` does exactly this today (`1.18.1-next.0` < `1.19.0`), so
  TEA currently has no prerelease line — that's expected, not a miss.
- The check is **incremental and stateful via the README** (Step 1), per package:
  each line is diffed only from the highest version you've already checked below it,
  so nothing is ever reviewed twice. The prerelease line anchors at the higher of
  `{current stable, last-checked prerelease}`; the stable line, symmetrically,
  anchors at a last-checked prerelease once it has *graduated* into the stable
  (diffing just the prerelease→final sliver). A recorded prerelease that npm has
  since unpublished degrades to a durable stable anchor (`stable_anchor_note` /
  `prerelease_anchor_note`) rather than crashing.
- Tarball diffing is authoritative for "what shipped" but won't catch an
  *installer* behavior change (those live in `tools/`, not the skill payload) —
  which is exactly why Step 3 reads each repo's release notes and post-stable
  commits. Weigh any installer finding against the install/update notes in
  `CLAUDE.md`.
- `python3 .claude/skills/auto-bmad-compat-check/scripts/bmad_compat.py --self-test`
  validates the classification logic offline — run it if you change the script.
```
