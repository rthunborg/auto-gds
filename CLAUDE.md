# CLAUDE.md — working in the auto-bmad repo

This repo is a **BMAD standalone module** (distributed as a single skill + a Claude
`marketplace.json`). The skill (`auto-bmad`) is an orchestrator that runs the full BMAD story
workflow one story at a time, on **Claude Code or Codex**. This file is guidance for working
**on the module**, not for using it.

## Core principle (do not violate)
The orchestrator **delegates BMAD work and reports** — it must never implement story work or run
`/bmad-*` skills directly. Every BMAD step (create-story, dev-story, code-review, TEA, retro,
project-context bootstrap/refresh) runs in a delegated `ab-*` sub-agent. **Git/PR work is the
deliberate exception that the orchestrator owns directly** (never delegated): preflight
detection, branching, per-phase commits, push, and PR — it holds the full pipeline context to
write commit/PR messages, and a round-trip to a delegate would only be slower. The Phase 0
**project-context probe** is the same kind of orchestrator-owned detection: a fast existence
check at `<output_folder>/project-context.md` (the BMAD-canonical write path) plus a `find`
fallback under `<project_root>` for any custom location, mirroring the skill's own discovery —
it decides whether Phase 2's bootstrap sub-step needs to run; the bootstrap itself
(`generate-project-context`) is delegated like every other BMAD skill call. The Phase 9 **clean-completion BMAD-status flip**
(story file `Status:` + `sprint-status.yaml` → `done`) is the same kind of orchestrator-owned
finalize bookkeeping — a one-field status write, not story work, coupled to the git finalize the
orchestrator already owns. The Phase 9 **pre-push report write + commit** (`docs(story-{e}-{s}):
pipeline report` — story-level fields only, no PR/CI/merge data) is the same kind: it lands the
report in the PR diff before push and never needs touching again, because the chat output owns
PR/CI/merge details. The Phase 9 **merge prompt** (opt-in via `git.offer_merge`, default on)
is another orchestrator-owned action of the same kind: auto-bmad never merges silently, but on a
clean completion it **asks** the user to pick a merge style (merge commit (default) / rebase / squash /
don't merge) plus delete-branch, then runs the chosen `gh pr merge` call itself. The merge is the
user's call; the orchestrator just executes it because it already owns git. Apart from those, the
**only** time the orchestrator does step work itself is the `inline` delegation tier (hosts with
no subagent support — see `delegation-runtime.md`), and even then it follows the same phase
contract and structured-result discipline. When editing, preserve this separation.

## Delegation is tiered (the heart of the module)
BMAD abstracts neither sub-agent delegation nor per-agent model/effort, so we supply those with
tool-native files and degrade gracefully:
- **Tier 1 `custom-subagents`** (Claude Code, Codex) — each step runs in an isolated delegate at
  the profile's tuned model + effort. Claude: `.claude/agents/ab-*.md` (`model:`/`effort:`).
  Codex: `.codex/agents/ab-*.toml` (`model`/`model_reasoning_effort`), invoked by naming the agent.
- **Tier 2 `general-subagents`** — host has generic subagents but no effort knob; effort not honored.
- **Tier 3 `inline`** — no subagents; run the step in-context (documented last resort).

`profiles` (per-profile, per-tool model+effort) is the single source of truth; `phase_profiles`
maps each phase to a profile. `scripts/render-agents.py` generates the tool-native files from
`profiles`. **Host/mode are `auto` and re-detected every run**, so one project (with both tools
provisioned) runs in Claude Code or Codex with no reconfiguration; `target_tools` only controls
which agent files get generated — it defaults at setup to the AIs the BMAD install targets
(`.claude/skills` ⇒ claude-code, `.agents/skills` ⇒ codex) and is still confirmed by the user.

## Layout
- `.claude-plugin/marketplace.json` — Claude distribution (lists the single `./auto-bmad` skill).
- `auto-bmad/SKILL.md` — orchestrator entry point (On-activation gate + the procedure).
- `auto-bmad/references/` — where the real detail lives: `pipeline.md` (per-phase playbook),
  `delegation.md` (exact per-skill prompts, tool-agnostic), `delegation-runtime.md` (host
  detection + the three spawn tiers), `overrides.md` (invocation-override vocabulary),
  `tea-policy.md` (risk rubric), `git-and-pr.md`, `state-and-resume.md` (config/state/first-run).
- `auto-bmad/assets/agents/profiles.yaml` — the single per-profile source: tool-neutral persona
  strings (`description`/`role_blurb`/`status_example`) **plus** per-tool model+effort. `claude/
  agent.md.tmpl` and `codex/agent.toml.tmpl` — ONE shared body template per tool (renderer fills
  in `@@NAME@@`/`@@DESCRIPTION@@`/`@@ROLE_BLURB@@`/`@@STATUS_EXAMPLE@@`/`@@MODEL@@`/`@@EFFORT@@`/
  `@@REASONING_EFFORT@@`), so the same wording lands in both Claude and Codex output and the four
  ab-* personas can't drift between tools.
- `auto-bmad/assets/module.yaml` + `module-help.csv` + `module-setup.md` — BMAD module
  identity, capability registry, and self-registration/provisioning flow.
- `auto-bmad/scripts/story_plan.py` — dependency-free sprint-status reader (`--self-test`).
- `auto-bmad/scripts/state_plan.py` — dependency-free reader for auto-bmad's own `state/{key}.yaml`
  files; the orchestrator calls it for resume detection instead of hand-rolling shell. Scans
  `--state-dir` for in-flight pipelines (`status != done`) and returns the resume `target`
  (most-recently-updated, by `updated_at`); `--story-key` does an exact-path single-story check.
  Exit 0 even on an absent/empty dir — no zsh `nomatch` footgun, no phantom `story-*` glob
  (`--self-test`).
- `auto-bmad/scripts/render-agents.py` — dependency-free agent generator (`--self-test`).
- `auto-bmad/scripts/config_plan.py` — dependency-free detector/healer for drift between the shipped
  `assets/agents/profiles.yaml` and a project's runtime `config.yaml`. The Phase 0 config-drift step
  runs `--check`; on drift (asset `profiles`/`phase_profiles` keys the config lacks, or
  `profiles_source_version` older than the installed `module_version`) it `--apply`s an **additive**
  re-seed — appends only the MISSING keys (never overwriting a user retune) and restamps the version.
  Closes the gap `render-agents.py --check` can't see: that check only diffs the four rendered agent
  files and never reads `phase_profiles`, so a newer module's new phase mapping (e.g. `tea_triage`)
  reached neither the config nor any freshness signal. A sub-key missing from an already-present
  profile is reported as `manual_review`, not auto-written (`--self-test`).
- `auto-bmad/scripts/review_findings.py` — dependency-free reader for a story's `### Review
  Findings` section; the Phase 7 reconciliation gate runs it to confirm the review skill actually
  persisted findings (`--expect-min N` ⇒ exit 1 on shortfall) and that every `[Review][Defer]`
  finding reached the durable `deferred-work.md` ledger (`--deferred-work-file` + `--story-key` ⇒
  exit 1 on shortfall; `--self-test`).
- `auto-bmad/scripts/merge-config.py` + `merge-help-csv.py` — config/CSV merge (from the BMAD
  standalone-module template; use PyYAML via the BMAD installer's environment).
- `CHANGELOG.md` — hand-maintained ([Keep a Changelog](https://keepachangelog.com/)); version
  history + source for release notes. `scripts/bump-version.py` — repo-maintenance release helper.
  Both are **repo-root** tooling that does **not** ship inside the skill (unlike `auto-bmad/scripts/`,
  which is copied to users). See "Releasing".

## Where behavior lives
- **Pipeline** → `references/pipeline.md`. **What a step tells an agent** → `references/delegation.md`.
- **How a step is spawned (host/tier)** → `references/delegation-runtime.md`. **TEA selection** →
  `references/tea-policy.md`. **Config/state schema, first-run, profiles** →
  `references/state-and-resume.md`. **Invocation overrides** → `references/overrides.md`.
- **Model/effort per profile** → `assets/agents/profiles.yaml` (+ the runtime config copy).
  **Setup/registration/provisioning** → `assets/module-setup.md`. Keep `SKILL.md` thin.

## Testing
```bash
# Deterministic cores:
python3 auto-bmad/scripts/story_plan.py --self-test
python3 auto-bmad/scripts/state_plan.py --self-test
python3 auto-bmad/scripts/render-agents.py --self-test
python3 auto-bmad/scripts/config_plan.py --self-test
python3 auto-bmad/scripts/review_findings.py --self-test
# Marketplace manifest is valid JSON:
python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
# Module structure passes the BMAD validator (run from the repo root, which holds the one skill):
python3 .claude/skills/bmad-module-builder/scripts/validate-module.py .
# Live: add this repo as a local marketplace (Claude) or BMAD module source, install, run
# /auto-bmad in a BMAD project. `/auto-bmad reprovision` re-renders agents after editing profiles.
# Release helper:
python3 scripts/bump-version.py --self-test
```

## Releasing
The version lives in **three** tracked files that must stay in lockstep —
`.claude-plugin/marketplace.json` (`version`), `auto-bmad/assets/module.yaml` (`module_version`),
and the README shields badge — and "publishing" is just **pushing a `vX.Y.Z` git tag** (the BMAD
installer keys its upgrade detection off stable tags; the Claude plugin marketplace reads the
manifest `version`). There is no npm/build/publish step.

Cut a release from a clean `main`:
1. Ensure this release's notes are under `## [Unreleased]` in `CHANGELOG.md`, grouped under
   Keep-a-Changelog headings (Added/Changed/Fixed/Security/…). Write them by hand as changes land —
   never auto-generate from commits. Keeping `[Unreleased]` current makes release time just a relabel.
2. `python3 scripts/bump-version.py <patch|minor|major>` (or an explicit `X.Y.Z`; `--dry-run` to
   preview). It refuses an empty `[Unreleased]`, guards against version drift across the three files,
   promotes the changelog (date + compare links), rewrites all three version strings, then commits
   `chore(release): vX.Y.Z` and tags it.
3. `git push --follow-tags`.

Pushing the tag is the release. `.github/workflows/release.yml` then fires on the `v*` tag and
creates the GitHub Release from the tag's `## [X.Y.Z]` CHANGELOG section (idempotent; it first
verifies the tag matches all three version files and that the changelog has a matching section).
That's the only CI — there is no build/publish step (no npm/GHCR artifact). Delegate agents are a
runtime concern (`/auto-bmad reprovision`), not a release artifact, so nothing re-renders on bump.

## Conventions
- Conventional Commits (`feat:`/`fix:`/`docs:`/`test:`/`chore:`/`refactor:`).
- Never commit the local BMAD test install or generated agents — `_bmad/`, `_bmad-output/`,
  `.agents/`, `.claude/`, `.codex/` are gitignored. The published repo is module + marketplace +
  docs only.
- Markdown reference files are read by the orchestrator at runtime; keep them concise and
  unambiguous (they are instructions, not prose). Helper scripts stay dependency-free with a
  `--self-test`.
- Don't land a user-facing change without a `CHANGELOG.md` note under `## [Unreleased]` (right
  Keep-a-Changelog heading) in the same commit/PR. Never bump the version files by hand — use
  `scripts/bump-version.py` so all three stay in sync (see "Releasing").

## Known platform facts (verified)
- **Claude Code:** sub-agents take `model:` + `effort:` frontmatter (effort is settable ONLY
  there, not via the Agent tool — that's why the templates exist); they CAN invoke skills but
  CANNOT spawn sub-agents. Project sub-agents in `.claude/agents/` are scanned into the
  invokable-agent roster **only at process launch** — agents rendered mid-session (first-run setup,
  reprovision) aren't invokable until a full quit & relaunch; `/clear` starts a fresh context in the
  same process and does not re-scan. (Verified: a freshly-rendered `ab-high` returned *"Agent type
  'ab-high' not found"* until the tool was restarted.)
- **Codex:** subagents are TOML files in `.codex/agents/` (project) or `~/.codex/agents/`, with
  `model` + `model_reasoning_effort` (gpt-5.x effort: low|medium|high|xhigh — xhigh is the
  ceiling); invoked by naming the
  agent in natural language — Codex spawns/collects them. Model names are environment-specific
  (retunable per install), so they're config, not hardcoded — the shipped defaults are real.
- **BMAD** has no portable abstraction for delegation or model/effort; modules are skills copied
  into a tool's skills dir (`.claude/skills/`, `.codex/skills/`). Hence the tiered design.
- **BMAD update of a custom-source module (auto-bmad/`abm`):** `--action quick-update` only re-pulls
  modules whose source is cached under `~/.bmad/cache/` and **skips custom-source re-cloning
  entirely** (`installer.js quickUpdate` adds a custom module only if `findModuleSourceByCode` hits a
  cached repo; otherwise it's in `skippedModules`). The installer's `resolveInstalledModuleYaml`
  never searches the project tree, so a self-registered/marketplace-installed `abm` has
  `source: unknown` in `_bmad/_config/manifest.yaml` and emits benign `could not locate module.yaml
  for 'abm'` warnings on every update. The fix is to update with the full path re-supplying the
  source: `npx bmad-method install --action update --custom-source <repo-url> --yes` (re-clones to
  cache, rewrites the manifest source). So the README "Updating" section must recommend
  `--action update --custom-source …`, **never** bare `quick-update`.
- `/bmad-create-story` has no `validate` mode; it self-validates against its checklist.
- **Shell globs:** the orchestrator's probe commands run under whatever shell the host uses (zsh,
  fish, bash). An unmatched glob is fatal in zsh/fish (`nomatch` ⇒ exit 1), and the `for f in
  *.glob; do …` loop syntax isn't even portable to fish — so probes must not iterate raw globs.
  Use `find … -name '<pat>'` (external binary, empty output + exit 0 everywhere) or Python.
