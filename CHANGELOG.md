# Changelog

All notable changes to **auto-bmad** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Maintainers: add notes under **[Unreleased]** as you go (under the right
> heading — Added/Changed/Deprecated/Removed/Fixed/Security). At release time
> `scripts/bump-version.py <patch|minor|major>` promotes that section to the new
> version, bumps both version files, commits, and tags. A release is **blocked**
> if `[Unreleased]` is empty. See CLAUDE.md → "Releasing".

## [Unreleased]

## [0.10.0] - 2026-05-29

### Added

- **Phase 0 now detects and heals runtime-config drift** — the gap that let a module update's new
  config keys silently never reach a project. The runtime `config.yaml` is seeded once at first run
  and never re-touched by an update, so a newer asset's `profiles`/`phase_profiles` keys (e.g. the
  `tea_triage` phase mapping added in 0.9.0) never arrived, and nothing flagged it: the only
  freshness check (`render-agents.py --check`) diffs the four rendered agent files and **never reads
  `phase_profiles`**, while the `profiles_source_version` stamp meant to catch this was written but
  never read. New **`scripts/config_plan.py`** (dependency-free, `--self-test`) closes the gap on a
  separate axis from agent-file freshness: `--check` diffs the shipped asset's
  `profiles`/`phase_profiles` keys against the runtime config's and compares
  `profiles_source_version` to the installed `module_version`; `--apply` performs an **additive**
  heal — appends only the keys the config is MISSING (never overwriting a user retune) and restamps
  the version. Phase 0 runs `--check` and auto-`--apply`s on drift (no human stop), reporting it in
  the preflight echo + final report; a sub-key missing from an already-present profile is surfaced
  as `manual_review` rather than auto-rewritten. Wired into `references/pipeline.md` (Phase 0),
  `references/state-and-resume.md` (the now-functional `profiles_source_version`), and `CLAUDE.md`.
- **Per-story trace coverage advisory for long epics** (`tea.story_trace_advisory`, on by default,
  `min_epic_stories: 6`). A story-scope, **non-blocking** `bmad-testarch-trace` pass at the tail of
  Phase 7 that surfaces this story's uncovered acceptance criteria while the dev context is fresh
  and the PR is still open — instead of waiting for the epic-end trace gate, which on a long epic can
  be many stories away. It self-activates **only** on a high-risk, not-last-in-epic story in an epic
  of `>= min_epic_stories` stories, so it stays dormant on normal short epics (which rely on the
  epic-end gate alone). It records gaps in state (`story_trace`), the report's **TEA** line, the
  PR-body checklist, and the epic retro notes, but **never** halts, remediates, asks, or forces a
  draft PR — the blocking quality gate stays at epic end. New `tea_risk` / `epic_story_count` state
  fields back the gating, and a `skip trace-advisory` invocation override opts a single run out.
  (`references/tea-policy.md` §3, `references/pipeline.md` Phase 0 + Phase 7 tail,
  `references/delegation.md` `testarch-trace (story advisory)` entry, `references/overrides.md`,
  `references/state-and-resume.md` config + state + report template.)

### Fixed

- **`/auto-bmad` no longer fails to detect that a reprovision/re-seed is required after a module
  update.** Previously the only provisioning check (`render-agents.py --check`) reported `fresh`
  whenever the four agent files matched the current config — even when the config itself had drifted
  behind the shipped asset (missing `phase_profiles` keys) — and the `profiles_source_version`
  version-drift signal was never actually compared against `module_version`. The new Phase 0
  config-drift step (above) makes both detections real.

## [0.9.0] - 2026-05-29

### Added

- **Phase 8 now surfaces retrospective-detected *planning drift*.** When the epic retrospective
  flags a planning assumption the build proved wrong (PRD / architecture / epic scope that no longer
  matches the code), the orchestrator lifts it into a new **Planning drift** report field and
  recommends the upstream re-sync path — refresh `document-project` (if `docs/` is stale) and
  `generate-project-context`, then `/bmad-prd` (update intent) to reconcile the PRD in place;
  `/bmad-correct-course` for structural drift. It is non-blocking and **never auto-run**: the
  orchestrator names the step, the human decides (same posture as the existing correct-course
  pointers). (`references/delegation.md` retrospective entry, `references/pipeline.md` Phase 8,
  `SKILL.md` Step 3, `references/state-and-resume.md` section template.)
- **`scripts/state_plan.py` — a deterministic reader for auto-bmad's own `state/{key}.yaml`
  files**, so resume detection calls a tool instead of improvising shell. A default scan of
  `--state-dir` reports the in-flight pipelines (`status != done`), the resume `target`
  (most-recently-updated by `updated_at`, with mtime as a tiebreaker), and any `extra_in_flight`
  to mention; `--story-key` does an exact-path single-story check. It's dependency-free (flat-YAML
  line reader), exits 0 even on a first-run absent/empty dir, and has a `--self-test`. This removes
  the shell improvisation entirely (see the probe-hardening under Fixed): no raw glob loop to abort
  under zsh/fish, no phantom `story-*` filename to miss. Wired into `SKILL.md` Step 1 (target
  selection + resume check) and `references/state-and-resume.md`/`pipeline.md`.

### Changed

- **Retuned two delegate-profile assignments for better effort-to-leverage fit.** (1)
  `project_context` (the Phase 2 bootstrap + Phase 8 refresh of `project-context.md`) moved from
  the Sonnet-tier `ab-alt` to the Opus-tier `ab-high` — it builds the durable AI-rules doc every
  later story inherits as `persistent_facts`, so it's high-leverage, long-lived output that was
  under-provisioned next to throwaway work. (2) Phase 0 story-risk triage split out of
  `tea_per_story` into its own `tea_triage` key mapped to `ab-alt`: triage is a cheap
  `low|med|high` classification that didn't warrant the Opus `ab-high` profile, while ATDD/automate
  (which do) stay on `tea_per_story` → `ab-high`. No new agent files — both keys resolve to the
  existing four profiles. **Requires `/auto-bmad reprovision`** to re-render the affected agents.
  (`assets/agents/profiles.yaml` `phase_profiles`; `references/pipeline.md` Phase 0, `SKILL.md`
  Step 1, `references/state-and-resume.md` key list.)

### Fixed

- **Realigned the four delegate persona strings to the actual `phase_profiles` mapping.** The
  `description`/`role_blurb`/`status_example` for `ab-max`/`ab-xhigh`/`ab-high`/`ab-alt` (baked into
  each rendered agent file as its self-description) had drifted from what each profile is actually
  invoked for: `ab-high` described epic gates + the retrospective it no longer runs (those are
  `ab-xhigh`/`ab-alt`), `ab-xhigh` (the real home of `code_review_fix` and the epic gates) didn't
  mention either, `ab-max` still claimed code-review fixes, and `ab-alt` advertised triage/ATDD/
  automate that map elsewhere. The personas now honestly enumerate each profile's real duties under
  the post-retune mapping, so a delegate's framing matches its task. **Requires `/auto-bmad
  reprovision`.** (`assets/agents/profiles.yaml`; self-test assertions in `scripts/render-agents.py`
  updated to the new distinctive tokens.)

- **Resume/state probes no longer misfire on shell globs or a phantom `story-` filename prefix.**
  The orchestrator was improvising state-file checks as raw glob loops (`for f in story-1-*.yaml`),
  which fail two ways: state files are named `{key}.yaml` (e.g. `1-2-user-auth.yaml`) with no
  `story-` prefix — that form is a commit/PR-scope convention only — so the pattern matches
  nothing; and an unmatched glob aborts with exit 1 under zsh/fish (`nomatch`) instead of yielding
  an empty result. The reference docs now (a) state the real on-disk naming and ban the phantom
  prefix, (b) give a ready-to-copy `find … -exec grep -L '^status: done' {} +` enumeration plus an
  exact-path `test -f` per-story check, (c) reinforce `find`/`test` (not bare globs) for the
  first-run framework/CI detection and the Phase 9 CI-workflow check, and (d) hoist a single
  "probe discipline" rule to the top of Phase 0 so it governs every orchestrator-run probe.
  (`auto-bmad/references/state-and-resume.md`, `auto-bmad/references/pipeline.md` Phase 0,
  `auto-bmad/references/git-and-pr.md`.)

## [0.8.0] - 2026-05-29

### Added

- **Per-story run-time tracking with an AI-run vs human-wait split.** The state file gains three
  orchestrator-owned timing fields: `started_at` (stamped once at the Phase 1 write, immutable
  across resumes), `completed_at` (set when Phase 9 flips `status` to `done`; `null` while
  in-progress), and `active_seconds` (accumulated wall-clock spent executing phases — the
  orchestrator reads the host's `date +%s` before delegating each phase and after its commit, and
  sums the deltas). The per-story report's new **Timing** line then shows total elapsed
  (`completed_at − started_at`), an approximate **AI-run time** (`active_seconds`), and
  **human/idle wait** (`elapsed − active_seconds`) — the latter dominated by interactive prompts and
  cross-session resume gaps. The split is best-effort host wall-clock, not token-compute time.
  (`auto-bmad/references/state-and-resume.md` state schema + timing note + report template,
  `auto-bmad/references/pipeline.md` per-phase loop + Phase 1 + Phase 9, `auto-bmad/SKILL.md` Step 3.)

### Changed

- **Epic conventions now actually cross the epic boundary.** Two carry-forward gaps are closed so a
  retro's lessons reach the next epic's stories instead of stalling at epic close:
  - **Phase 8 `project-context.md` refresh is no longer a blind codebase scan.** It is now fed the
    epic's accumulated retro notes (and durable items from the deferred-work ledger) and instructed
    to fold every durable convention/rule/team-agreement into the AI-rule facts. A code-only scan
    reconstructs visible patterns but misses rules that aren't inferable from code (e.g. "every
    tenant table MUST GRANT DML to the app role", "every validation guard ships a rejection test") —
    exactly the facts that were silently dropped before. Since `bmad-create-story` auto-loads
    `project-context.md` as `persistent_facts`, this is the channel that carries epic-N conventions
    into epic N+1's stories. (`auto-bmad/references/delegation.md` → `generate-project-context`,
    `auto-bmad/references/pipeline.md` Phase 8.)
  - **First-in-epic create-story is fed the prior epic's retrospective forward sections.** The
    `{retro_notes_hint}` is keyed to the current epic, so the first story of a new epic previously
    got no retro signal at all (its own epic has no notes yet). It now also reads the prior epic's
    retrospective document (located via `find <impl> -name 'epic-{e-1}-retro-*.md'`) and folds its
    forward-looking prep — "before the first story of epic N" items and "the gate will fail-loud on
    the new table, that's expected" heads-ups — into the Story Context. This carries the transient,
    epic-specific prep that durable `project-context.md` does not hold.
    (`auto-bmad/references/delegation.md` → `create-story`, `auto-bmad/references/pipeline.md` Phase 3.)

## [0.7.0] - 2026-05-29

### Added

- **create-story now folds in prior deferred work.** Phase 3 gained a `{deferred_work_hint}`:
  when `<impl>/deferred-work.md` (BMAD's append-only code-review/quick-dev defer ledger) exists
  and is non-empty, the orchestrator instructs the create-story delegate to read it, fold the
  deferrals that overlap the new story's scope into the Story Context, and ignore the rest. No
  stock BMAD or TEA skill reads that ledger, so this is the only path that carries prior
  deferrals forward into new stories.

## [0.6.1] - 2026-05-29

### Fixed

- **Phase 7 reconciliation gate no longer false-fails on the reviewer's bullet format.**
  `review_findings.py` keyed on a rigid checkbox rendering (`- [ ] [Review][Patch] …`), but the
  `### Review Findings` shape is owned by the upstream `bmad-code-review` skill and produced by a
  non-deterministic LLM — which legitimately renders findings as bold prose with no checkbox
  (`- **[Review][Decision] [Med]** …`). The parser counted 0, so the gate reported
  `reconciled: false` and forced a pointless reformat re-delegation even though the findings had
  persisted correctly. The bullet matcher now keys only on the semantic `[Review][Type]` tag and
  treats the checkbox, `**bold**`/`__emphasis__` markers, and trailing severity tag as optional; a
  finding with no checkbox defaults to `open` (the safe state). The `code-review fix` delegation
  prompt is likewise reworded to be checkbox-agnostic. (`auto-bmad/scripts/review_findings.py`,
  `auto-bmad/references/delegation.md`.)

### Changed

- **Trimmed duplicated rationale across the reference docs (no behavior change).** Collapsed
  repeated "why" explanations to a single canonical home with pointers — the project-context
  greenfield/brownfield gloss, the git-ownership rationale, the `profiles.yaml` single-source /
  advisory-stamp story, the report-file chat-only rationale, and several restated facts — and
  dropped a few changelog-style asides. Every pipeline contract (commit strings, gate conditions,
  the shell probe, severity thresholds, draft-predicate clauses, state schema, prompt bodies) is
  unchanged. (`auto-bmad/references/pipeline.md`, `delegation.md`, `delegation-runtime.md`,
  `git-and-pr.md`, `state-and-resume.md`, `tea-policy.md`.)
- **Dropped the hardcoded model names from the module-setup provisioning note.** The Step 4 note no
  longer lists specific defaults (`opus/sonnet`, `gpt-5.5/gpt-5.4`), so `assets/agents/profiles.yaml`
  stays the single source for model/effort and the doc can't silently drift when profiles are
  retuned. (`auto-bmad/assets/module-setup.md`.)

## [0.6.0] - 2026-05-28

### Added

- **Phase 0 project-context probe + Phase 2 project-context bootstrap sub-step.** Auto-bmad now
  detects a missing `project-context.md` at preflight — primary check at the BMAD-canonical write
  path (`<output_folder>/project-context.md`), `find` fallback under `<project_root>` excluding
  `node_modules/`/`.venv/`/`.git/`, mirroring the `bmad-generate-project-context` skill's own
  discovery — recorded as `needs_project_context_bootstrap` in state. When missing, runs `generate-project-context`
  via the `project_context` profile as a new Phase 2 sub-step (committed
  `docs(project-context): bootstrap`) *before* Phase 3's create-story. Earlier behavior only
  refreshed the file at Phase 8 (epic-end), so every create-story in epic 1 of a greenfield repo —
  and every create-story on a brownfield repo that adopted auto-bmad mid-project — silently
  skipped `persistent_facts` injection. The probe predicate ("file is missing anywhere in the
  project") naturally covers both. Phase 2 is now two independently-gated sub-steps: bootstrap
  (probe-driven, TEA-independent) and the existing epic-level test design (still gated on
  `is_first_in_epic AND tea.enabled`); either, both, or neither may run. New
  `skip project-context-bootstrap` override suppresses the bootstrap for the run if needed.
  (`auto-bmad/references/pipeline.md` Phase 0 + Phase 2, `auto-bmad/references/delegation.md`
  generate-project-context, `auto-bmad/references/overrides.md`, `auto-bmad/SKILL.md`,
  `auto-bmad/references/state-and-resume.md`, `CLAUDE.md`.)
- **`create-story` now ingests the epic's accumulated retro-notes when present.** The delegation
  prompt for Phase 3 conditionally appends a directive to read
  `_bmad-output/auto-bmad/retro-notes/epic-{e}.md` (if it exists and is non-empty) and treat each
  prior story's bullets as epic-wide constraints — schema inheritance, ratified conventions,
  things later stories MUST or MUST NOT do — reflecting them directly in the Story Context
  (constraints / persistent_facts / test notes) rather than as a generic see-retro pointer.
  Previously the retro-notes file was write-only until the Phase 8 retrospective; this turns it
  into a feedback loop within the epic. Phase-tag prefix (`[Phase X — short-name]`) is pinned in
  the delegation doc so later stories can filter by phase. (`auto-bmad/references/delegation.md`
  create-story.)
- **`profiles_source_version` field in `config.yaml`.** First-run setup now stamps the field with
  the installed module's `module_version` (read from `assets/module.yaml`), so a future update can
  detect a stale-defaults snapshot of the `profiles:` / `phase_profiles:` blocks without losing
  user retunes. Advisory only — never auto-overwrites. `scripts/bump-version.py` is now a
  four-file lockstep (added the schema example in `state-and-resume.md`) so the doc and freshly-seeded
  configs agree on the current release. (`auto-bmad/references/state-and-resume.md` config.yaml
  schema + First-run flow, `scripts/bump-version.py`.)

### Changed

- **State-file schema is now a stable contract — every field is always emitted.** Previously
  `pr_merged` / `merge_method` / `merge_commit` / `branch_deleted` / `ci_status` appeared only on
  stories that hit a clean-completion merge; parsers had to branch on field presence. Now the
  schema documented in `state-and-resume.md` requires every field on every write, using explicit
  `null` / `false` / `unknown` / `[]` / `{}` for not-yet-set or not-applicable. Added
  `updated_at` (ISO-8601 UTC) so resume can tell at a glance how stale a state file is. The doc
  also pins the rule that state is a machine-readable contract — prose narrative belongs in
  `reports/{key}.md`, not in YAML comments inside state. (`auto-bmad/references/state-and-resume.md`
  state/{key}.yaml.)
- **`reports/{key}.md` sections now follow a fixed template.** Each `## Report — <ts>` section
  uses the same headings in the same order (Story / Branch / Pipeline status / Phases run /
  Skipped / Overrides / TEA / Code review / Open questions / Deferred work / Needs human / Next),
  so PR reviewers find each field in a predictable place across runs and across stories. Empty
  sections keep their heading with "(none)" — never silently dropped. Aligns the file with the
  Step 3 chat-output expectations in `SKILL.md`. (`auto-bmad/references/state-and-resume.md`
  reports/{key}.md → "Section template", `auto-bmad/SKILL.md` Step 3.)
- **Phase 9 merge prompt now defaults to "Merge commit" instead of "Squash and merge", and the
  option order is Merge commit / Rebase and merge / Squash and merge / Don't merge.** auto-bmad
  produces meaningful per-phase commits (initial dev, `fix(story-…): apply review`, the pipeline
  report) — squashing collapses that signal, which is exactly the signal an AI later running
  `git log`/`blame`/`bisect` on the story needs to reconstruct what happened and why. Both
  history-preserving options (merge commit, rebase) sit at the top; merge commit is the default
  because it additionally marks the branch boundary as a visible "this was one auto-bmad story"
  node. Users can still pick any of the four — the change is just the default and the order.
  (`auto-bmad/references/git-and-pr.md` "Merging the PR", `auto-bmad/SKILL.md`, `CLAUDE.md`.)
- **Phase 9 now commits the per-story report file *before* push, so it ships in the PR diff.**
  Previously the report was written to `_bmad-output/auto-bmad/reports/{key}.md` at the very end
  of Step 3 — after push, the PR, and any merge — leaving the file as an uncommitted change the
  user had to either land manually or merge after the fact. The pipeline now writes + commits the
  report at the top of Phase 9 (`docs(story-{e}-{s}): pipeline report`) so the persistent log
  lands in the PR like any other artifact. To make a single pre-push write viable, the file is
  now **story-level only** — overrides, TEA outcomes, open questions, deferred work, blockers,
  next-story preview. PR URL, CI link/status, draft reason, merge method, and the BMAD-status-flip
  outcome are **chat-only** at end of run; they're already retrievable from GitHub, git, and
  `sprint-status.yaml`, so keeping them out of the file means it never needs re-touching after
  the PR/CI/merge resolve. On a hard-stop before Phase 9, Step 3 still writes the file as a
  fallback (no commit; the human commits it alongside their fix). (`SKILL.md` Step 3,
  `references/pipeline.md` Phase 9, `references/git-and-pr.md` Ownership + Commits,
  `references/state-and-resume.md` reports/{key}.md, `CLAUDE.md`, `README.md`.)

## [0.5.0] - 2026-05-28

### Changed

- **Delegate templates collapsed to one shared body per tool — no more Claude↔Codex drift.** The
  eight per-profile templates (4 Claude + 4 Codex) were ~80% identical prose and had already
  started drifting (Claude's `ab-alt` said *"Sonnet code-review iterations"* while Codex's said
  *"faster-model …"*). Now one shared body per tool (`assets/agents/{claude,codex}/agent.{md,toml}.tmpl`)
  is filled with per-profile metadata — `description`, `role_blurb`, `status_example` — living
  next to each profile's `claude:`/`codex:` blocks in `assets/agents/profiles.yaml`. The same
  strings flow into both tools' output, and `render-agents.py --self-test` asserts cross-tool
  agreement, so future Claude↔Codex drift is impossible by construction. Wording is tool-neutral
  (no more "Opus"/"Sonnet") so the bodies survive model retunings. Generated agent filenames are
  unchanged; run `/auto-bmad reprovision` to pick up the new bodies (or let preflight
  auto-reprovision do it). (`scripts/render-agents.py`, `assets/agents/profiles.yaml`, new shared
  templates, 8 old templates deleted, `CLAUDE.md`, `references/delegation-runtime.md` Tier 2 note.)

- **Reference duplication consolidated — each canonical fact has one home now.** Pointer-only
  changes: the *newly-rendered agents need a restart* warning now lives only in
  `delegation-runtime.md`; Phase 9's CI wait + draft conversion + merge prompt defer to
  `git-and-pr.md` ("PR" / "CI link & wait" / "Merging the PR"); the first-run stop is described
  once in `state-and-resume.md`; and a new `git-and-pr.md` → "Ownership" section names the
  orchestrator-owned (never-delegated) list (preflight, branching, per-phase commits, push, PR,
  Phase 9 BMAD-status flip, merge prompt) so future exceptions land in exactly one place. Pure
  docs — no behavior change. (`SKILL.md`,
  `references/{pipeline,state-and-resume,delegation,git-and-pr}.md`, `assets/module-setup.md`.)

### Added

- **End-of-pipeline merge prompt (opt-in, default on).** On a clean-completion PR, Phase 9 now
  waits for in-progress CI to finish and then **asks** the user whether to merge — **Squash and
  merge** / **Merge commit** / **Rebase and merge** / **Don't merge** — followed by a
  **delete-branch?** sub-question if a merge style is chosen. auto-bmad runs the chosen
  `gh pr merge` itself (it already owns git/PR), switches the working tree back to the base branch
  on success, and surfaces any merge failure (branch protection, required reviews, etc.) under the
  report's "Needs attention" rather than retrying. "Don't merge" preserves the old behavior:
  PR stays open for the human. Two new config knobs gate this: `git.offer_merge: true` (default;
  set `false` to never be asked) and `git.ci_wait_minutes: 30` (max wait for in-progress CI). A
  new invocation override, `skip merge-prompt`, opts out for a single run. The draft predicate
  also gains a clause — **CI red or timed-out now leaves the story at `review`** (PR converted to
  draft via `gh pr ready --undo`), keeping "clean completion" honest; failed/timed-out CI is
  treated as caveated, same as a recorded blocker or waived gate. State file gains
  `ci_status`/`pr_merged`/`merge_method`/`branch_deleted` for the report. (`pipeline.md` Phase 9,
  `git-and-pr.md`, `state-and-resume.md`, `overrides.md`, `SKILL.md`, principle update in
  `CLAUDE.md`, README user-facing notes.)

### Fixed

- **README "Updating" no longer recommends `--action quick-update`, which silently skips auto-bmad.**
  auto-bmad installs as a *custom-source* BMAD module, but `quick-update` only re-pulls modules whose
  source is already cached under `~/.bmad/cache/` and skips custom-source re-cloning entirely — so on
  a marketplace/copy install (or any install whose source resolved to `unknown` in the BMAD manifest)
  it passes auto-bmad over without updating it, and `bmad update` keeps emitting the benign `[warn] …
  could not locate module.yaml for 'abm'`. The Updating section now documents the full path that
  re-supplies the source — `npx bmad-method install --action update --custom-source <repo-url> --yes`
  — which re-clones into the cache and rewrites the manifest source so updates apply and resolve
  cleanly. (Recorded as a verified platform fact in `CLAUDE.md`.)

## [0.4.0] - 2026-05-27

### Changed

- **Retro notes are now terse, signal-only, and skipped when empty**, so the epic retro-notes file
  (`_bmad-output/auto-bmad/retro-notes/epic-{e}.md`) stays small across a long epic instead of
  accumulating a per-phase log. Delegates now default `Retro notes` to `none` and add at most a
  one-line bullet per genuinely retrospective-worthy item (deviation / non-obvious decision /
  surprise / risk not already in the story file); the orchestrator appends nothing — not even the
  `## Story {key}` heading — for `none`/empty/routine notes. (All `ab-*` delegate templates, the
  shared autonomy directive in `delegation.md`, the append step in `SKILL.md`, and the file spec in
  `state-and-resume.md`. Run `/auto-bmad reprovision` to re-render delegate agents.)

- Phase 7 code-review loop now keeps iterating on a **cluster of Medium findings**, not just on
  Critical/High. A pass exits the loop only when it found no Critical or High **and at most one
  Medium** (any number of Low is fine); two or more Mediums now re-review like a Critical/High,
  because a pile of Mediums means the change still isn't settling. (`pipeline.md`)

### Fixed

- **A finished story now advances instead of getting stuck waiting for a human merge.** `dev-story`
  leaves the BMAD-level status at `review`, and BMAD only flips `review → done` on merge — so after
  a full pipeline run, `story_plan.py` kept re-selecting the just-finished `review` story while its
  auto-bmad state file was already `done`, and the run reported "already complete" and stopped
  without ever moving on. Phase 9 now **flips the BMAD-level status (story file `Status:` + the
  `sprint-status.yaml` entry) to `done` on a clean completion** — i.e. when the PR is/would be
  non-draft (no blocker, `convergence_unverified` false, gate not `WAIVED`) — decoupling `done` from
  the human's merge (auto-bmad still never merges; the open PR is theirs to merge whenever). A
  caveated completion (draft PR / blocker / waived gate) deliberately stays at `review` so it keeps
  surfacing for the human. (`pipeline.md` Phase 9, `git-and-pr.md`, `state-and-resume.md`,
  `SKILL.md`; principle note in `CLAUDE.md`.)

- **Deferred code-review findings are persisted to the durable `deferred-work.md` ledger again.**
  `/bmad-code-review` natively appends every `[Review][Defer]` finding to the cross-story ledger
  `{implementation_artifacts}/deferred-work.md` (next to `sprint-status.yaml`), but auto-bmad's
  `code-review` delegation prompt only emphasized the story-file `### Review Findings` section and
  the orchestrator hoisted defer/decision handling into its own Phase 7 loop — recording deferrals
  to the per-story `state.deferred_work`, the report, and retro-notes, while the BMAD-native ledger
  silently never got written. The per-story state mirror is operational; the ledger is the durable,
  human-discoverable backlog the team and any later manual BMAD run rely on. Three reinforcing
  fixes: the `code-review` delegation prompt (`delegation.md`) now makes appending defers to
  `<impl>/deferred-work.md` part of the deliverable and adds a `Deferrals logged: <W>` report line;
  Phase 7 (`pipeline.md`) appends user-deferred decisions to the same ledger as a direct
  orchestrator write (like the report/retro-notes) and extends the reconciliation gate to confirm
  defers reached the ledger; and `scripts/review_findings.py` gains `--deferred-work-file` /
  `--story-key` to count scoped `## Deferred from:` bullets and fail reconciliation on a shortfall.
  (`delegation.md`, `pipeline.md`, `SKILL.md`, `scripts/review_findings.py` with new `--self-test`
  coverage.)

- **Code review now enforces that findings are persisted to the story file.** `/bmad-code-review`
  silently runs in `no-spec` mode — dropping `[Review][Decision]` items and writing nothing to the
  story's `### Review Findings` section — whenever the story file isn't bound as its spec, yet it
  still reports findings to chat. The orchestrator trusted that report, so Phase 7's decision-ask
  and fix loop ran against an empty section and lost the findings. Three reinforcing fixes: the
  `code-review` delegation prompt (`delegation.md`) now binds `<story_file>` as the spec up front,
  forbids `no-spec` fallback, and makes the delegate re-read the file and report a `Findings
  persisted: <N>` count; a new reconciliation gate in Phase 7 (`pipeline.md`) runs the new
  `scripts/review_findings.py` to confirm the section actually holds the claimed findings, and on a
  mismatch re-delegates once (free retry) before escalating to `needs-human` rather than fixing
  against an empty section. (New dependency-free `auto-bmad/scripts/review_findings.py` with
  `--self-test`.)

- First-run setup and `reprovision` now tell the user to **fully restart the tool** (quit &
  relaunch) — not just open a "new session with fresh context" — before running the pipeline on the
  `custom-subagents` tier. Claude Code/Codex scan project delegate agents (`.claude/agents/*.md`,
  `.codex/agents/*.toml`) into the invokable-agent roster only at process launch, so agents rendered
  mid-session stay unregistered after a `/clear` (same process) and the first delegation failed with
  *"Agent type 'ab-…' not found"*. (`SKILL.md`, `state-and-resume.md`, `module-setup.md`; recorded
  as a verified platform fact in `CLAUDE.md`.)
- `delegation-runtime.md`: a fresh-on-disk delegate reported as *"Agent type not found"* on a
  custom-subagents host is now read as **restart-needed** (stop, have the user relaunch) instead of a
  cue to **degrade to `general-subagents`** — degrading would run the whole pipeline untuned when a
  restart restores per-phase model/effort.
- `delegation-runtime.md`: auto-reprovision-on-stale no longer claims to "self-heal without a human
  stop" unconditionally — it heals the on-disk files, but a running process keeps the agent
  definitions it loaded at launch, so a regenerated `model`/`effort`/body applies only after a
  restart (and a `missing` agent isn't invokable at all until then).

## [0.3.1] - 2026-05-27

### Fixed

- Resume detection (`state-and-resume.md`) now steers the orchestrator to enumerate
  `state/*.yaml` with `find` (or Python) instead of a raw `for f in …/state/*.yaml`
  glob loop. On a first run the `state/` dir is empty, and an unmatched glob aborts
  with exit 1 under zsh/fish (`nomatch`) — benign noise that looked like a failure.
  `find` yields empty output + exit 0 in every shell. Recorded as a verified platform
  fact in CLAUDE.md.

## [0.3.0] - 2026-05-27

### Added

- `argument-hint` frontmatter on the `auto-bmad` skill, so Claude Code shows the
  expected arguments (`--story <id>`, `setup`/`reprovision`, overrides) in the
  slash-command autocomplete popup. No effect on Codex, which doesn't read
  `argument-hint` for skills — harmless there.
- Phase 7 now resolves `[Review][Decision]` (decision-needed) review findings via
  batched `AskUserQuestion` (≤4 per call) **before** the fix pass — it never
  auto-guesses an ambiguous fix — and feeds the human-chosen directions into the
  `code_review_fix` delegate.
- A `FAIL` epic trace gate (Phase 8 `/bmad-testarch-trace`) is no longer captured-
  and-ignored — it now halts and **asks the user** (`AskUserQuestion`): **remediate
  & re-gate** (delegate `/bmad-testarch-automate` at epic scope to close the flagged
  coverage gaps, then re-run trace; bounded by the new `tea.gate_max_iterations`
  config, default 2), **waive & continue** (records `WAIVED` + rationale; Phase 9
  ships a **draft** PR with the gaps noted), or **stop** (no push/PR; gaps reported
  as `needs-human`). `CONCERNS` stays advisory (recorded + surfaced, non-blocking);
  `PASS`/skill-emitted `WAIVED` are unchanged. New state field `gate_iterations`
  tracks the remediation loop for resume.

### Changed

- The per-step `/bmad-*` command + prompt now live **only** in `delegation.md`:
  `pipeline.md` references each step by its `delegation.md` entry name (e.g.
  `create-story`, `code-review fix`) instead of re-printing the command, and the
  placeholder glossary (`{e}`/`{s}`, `{key}`, `<story_file>`, …) is defined once in
  `delegation.md` rather than in both files. Renaming a BMAD command or editing a
  prompt is now a single-file change. (`/bmad-correct-course` stays a literal in
  `pipeline.md` — it's a *suggestion to the user*, not a delegated step.)
- Codex delegate defaults (`gpt-5.5`/`gpt-5.4`) are now treated as **real model
  names**, not placeholders. Setup no longer emits the "⚠️ Codex models are
  placeholders — confirm them" warning / "needs human" action; retuning the
  `profiles` block stays available but is no longer flagged as required.
- The phase→profile mapping now lives **only** in config `phase_profiles`: the
  pipeline/delegation playbooks reference its keys (e.g. `create_story`,
  `code_review_review`) instead of raw profile names, removing the prior
  triplication. Added the missing `code_review_review_secondary` key (the even-
  iteration reviewer used when `code_review.alternate_models` is on) and a
  `phase_profiles:` defaults block to `assets/agents/profiles.yaml` so first-run
  actually has it to copy. `render-agents.py` ignores the new block.
- `assets/agents/profiles.yaml` is now the **single source** for the default
  `profiles` + `phase_profiles` values. The `config.yaml` schema in
  `state-and-resume.md` previously re-listed every model/effort and had already
  drifted from the asset (e.g. `ab-alt` codex `gpt-5.4-mini` vs `gpt-5.4`, and
  `xhigh` vs `high` effort on `ab-max`/`ab-xhigh`). The schema now shows just the
  *shape* and points at the asset, so the two can't drift.
- Corrected the documented Codex reasoning-effort set to `low|medium|high|xhigh`
  (gpt-5.x; `xhigh` is the ceiling) in `profiles.yaml` and `CLAUDE.md` — the prior
  `minimal|low|medium|high` wrongly omitted `xhigh`.
- Standardized delegation-prompt placeholders: `<...>` for filesystem paths,
  `{...}` for non-path fill-ins — so `{project_root}` is now `<project_root>`.
- Bumped the Codex `reasoning_effort` of the top-tier profiles `ab-max` and
  `ab-xhigh` from `high` to `xhigh` (the Codex gpt-5.x ceiling), restoring the
  Claude-side tiering on Codex; `ab-high`/`ab-alt` stay `high`. Re-run
  `/auto-bmad reprovision` to regenerate the Codex delegate `.toml` files.
- Renamed the `ab-fast` delegate profile (and its `claude/`+`codex/` templates)
  to `ab-alt` — it's the *alternate*/secondary code reviewer and low-stakes
  worker, not necessarily a faster model. Upgraders from v0.2.0 should run
  `/auto-bmad reprovision` to regenerate the delegate files under the new name;
  the old `ab-fast` agent files can be deleted.

### Fixed

- Code-review references pointed at an `[AI-Review]` tag that `bmad-code-review`
  never writes — it persists findings to a `### Review Findings` section as
  `[Review][Patch]` / `[Review][Decision]` / `[Review][Defer]`. The review and fix
  prompts and Phase 7 now reference the real artifact, so the fix pass reliably
  finds its work instead of hunting for a tag that isn't there.
- `scripts/bump-version.py` now creates an **annotated** tag (was lightweight), so
  `git push --follow-tags` actually pushes it and the release workflow fires.
- `scripts/render-agents.py` now tolerates **trailing comments on structural lines**
  (`profiles:`, the profile name, the tool key) in the profiles source. The
  documented `config.yaml` schema carries inline comments on those lines, which
  previously made the parser miss the `profiles:` block entirely and fail
  reprovisioning with "no 'profiles:' block found".

## [0.2.0] - 2026-05-27

### Added

- README **"Split a story across Claude Code and Codex"** section — a manual
  workaround that uses `stop before code-review` + resume to implement a story in
  one tool and code-review it in the other (either direction), leaning on
  auto-detected host and the resumable, commit-checkpointed pipeline.
- Preflight **provisioning-drift detection**. `render-agents.py --check` re-renders
  the delegate agents in memory and diffs them against the on-disk files (exit 1
  when stale). On a `custom-subagents` host the orchestrator runs it every preflight
  and **auto-reprovisions** — reporting it — when the agents are missing or stale
  after a module update or a `profiles` edit, so generated agents no longer drift
  unnoticed.

## [0.1.1] - 2026-05-27

First tagged release. The module had been published at `0.1.1` via the
`marketplace.json` manifest; this is the matching `v0.1.1` git tag, plus the
changelog and release tooling to keep versions traceable from here on.

### Added

- The **auto-bmad** BMAD module — an orchestrator skill that runs the full BMAD
  story workflow end-to-end, one story at a time, on Claude Code or Codex. It
  chains `create-story` → `dev-story` → `code-review` with risk-gated TEA phases
  and epic-boundary steps (test-design, ATDD, automate, traceability, NFR,
  test-review, project-context, retrospective).
- Each step runs in a delegated `ab-*` sub-agent; git/PR work is owned by the
  orchestrator. Tiered delegation: tuned `custom-subagents` (Claude
  `.claude/agents`, Codex `.codex/agents`, generated from a configurable
  `profiles` block) degrading to `general-subagents` and then `inline`.
- Resumable pipeline with isolated `story/X-Y-slug` branches, per-phase
  conventional-commit checkpoints, a PR + final report, per-story report logs,
  human-in-the-loop stops, and first-run/setup config at
  `_bmad-output/auto-bmad/config.yaml`.
- Distribution via the BMAD installer (custom Git source) and a Claude plugin
  `marketplace.json`.
- README **Updating** section: re-run the BMAD installer / `--action
  quick-update` / `@next`, the `/auto-bmad reprovision` follow-up, and the
  Claude-plugin update path.
- `CHANGELOG.md` (this file) and `scripts/bump-version.py` — a dependency-free
  release helper that promotes `[Unreleased]`, syncs the version in
  `marketplace.json` + `module.yaml`, commits, and tags.

[Unreleased]: https://github.com/stefanoginella/auto-bmad/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/stefanoginella/auto-bmad/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/stefanoginella/auto-bmad/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/stefanoginella/auto-bmad/releases/tag/v0.1.1
