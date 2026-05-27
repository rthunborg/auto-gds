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

[Unreleased]: https://github.com/stefanoginella/auto-bmad/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/stefanoginella/auto-bmad/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/stefanoginella/auto-bmad/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/stefanoginella/auto-bmad/releases/tag/v0.1.1
