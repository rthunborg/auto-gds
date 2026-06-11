# CLAUDE.md — working in the auto-gds repo

This repository is the **Auto-GDS module source**, not a target game project. Do not create or
commit target-project runtime folders such as `_bmad-output/`, `_bmad/gds/`, `.claude/agents/`,
`.codex/agents/`, generated runtime config, state, reports, or story artifacts here.

Auto-GDS is a fork/adaptation of the upstream story orchestrator for **BMad Game Dev Studio / BMGD** projects. Preserve
the orchestration boundary:

- the orchestrator owns git, state, reports, PRs, final status updates, and final chat output;
- delegated `agds-*` subagents run story creation, story implementation, code review, project
  context generation, and retrospective work;
- the orchestrator must not implement story code itself.

## Source Layout

- `.claude-plugin/marketplace.json` — Claude distribution metadata.
- `auto-gds/SKILL.md` — orchestrator entry point.
- `auto-gds/assets/module.yaml`, `module-help.csv`, `module-setup.md` — module identity and setup.
- `auto-gds/assets/agents/profiles.yaml` — shipped `agds-*` profile defaults.
- `auto-gds/assets/agents/*/agent.*.tmpl` — generated delegate templates.
- `auto-gds/references/` — pipeline, delegation, state/resume, overrides, and git/PR contracts.
- `auto-gds/scripts/` — dependency-free helper scripts.

## Required Defaults

- Target projects are detected by `_bmad/gds/config.yaml`.
- Central BMad registration is read from `_bmad/config.toml` / `_bmad/config.user.toml` under
  `[modules.agds]` (BMad v6 TOML, installer-owned). `_bmad/config.yaml` is never used.
  `_bmad/agds/config.yaml` is the installer's carry-forward config, not the runtime config.
- Runtime files live under `{output_folder}/auto-gds`, with fallback
  `{project-root}/_bmad-output/auto-gds`.
- Module code is `agds`.
- User command is `/auto-gds`.
- Delegate agents are `agds-xhigh`, `agds-high`, `agds-alt-xhigh`, and `agds-alt-high`.
- Core delegated production skills are the installed GDS names `gds-create-story`,
  `gds-dev-story`, `gds-code-review`, `gds-generate-project-context`, and `gds-retrospective`.
- GDS testing integration is disabled by default in V0.

## Validation

Run from the repository root:

```bash
python auto-gds/scripts/story_plan.py --self-test
python auto-gds/scripts/state_plan.py --self-test
python auto-gds/scripts/render-agents.py --self-test
python auto-gds/scripts/config_plan.py --self-test
python auto-gds/scripts/review_findings.py --self-test
python .claude/skills/auto-gds-compat-check/scripts/bmad_compat.py --self-test
```

Before finishing source changes, run stale-assumption searches for old BMM paths, old module
identity, old delegate profile prefixes, and old delegated production commands.

Historical changelog/report entries may still reference the upstream project; active
source, setup, runtime defaults, and generated artifacts should not.

## Releasing

The version lives in **four** tracked files that must stay in lockstep —
`.claude-plugin/marketplace.json` (`version`), `auto-gds/assets/module.yaml` (`module_version`),
the README shields badge, and `auto-gds/references/state-and-resume.md`
(`profiles_source_version`, the config.yaml schema example). "Publishing" is just **pushing a
`vX.Y.Z` git tag** (the BMAD installer keys upgrade detection off stable tags; the Claude plugin
marketplace reads the manifest `version`).

Cut a release from a clean `main`:
1. Ensure this release's notes are under `## [Unreleased]` in `CHANGELOG.md`, grouped under
   Keep-a-Changelog headings. Write them by hand as changes land — never auto-generate from commits.
2. `python3 scripts/bump-version.py <patch|minor|major>` (or an explicit `X.Y.Z`; `--dry-run` to
   preview). It refuses an empty `[Unreleased]`, guards against version drift across the four
   files, promotes the changelog (date + compare links), rewrites all four versions, then commits
   `chore(release): vX.Y.Z` and tags it.
3. `git push --follow-tags`.

`.github/workflows/release.yml` then fires on the `v*` tag and creates the GitHub Release from
that tag's CHANGELOG section (idempotent; it verifies the tag agrees with all four version files
and the changelog first). That's the only CI — no build/publish step, and nothing re-renders
agents on bump (`/auto-gds reprovision` is a runtime concern, not a release artifact).

## Known platform facts (verified)

- **Claude Code:** sub-agents take `model:` + `effort:` frontmatter (effort is settable ONLY
  there, not via the Agent tool — hence the templates); they CAN invoke skills but CANNOT spawn
  sub-agents. `.claude/agents/` is scanned into the invokable roster **only at process launch** —
  agents rendered mid-session (first-run setup, reprovision) aren't invokable until a full quit &
  relaunch (`/clear` reuses the same process and does not re-scan).
- **Codex:** subagents are TOML files in `.codex/agents/` (project) or `~/.codex/agents/`, with
  `model` + `model_reasoning_effort` (gpt-5.x effort: low|medium|high|xhigh — xhigh is the
  ceiling); invoked by naming the agent in natural language — Codex spawns/collects them. Model
  names are environment-specific (retunable per install), so they're config, not hardcoded.
- **BMAD** has no portable abstraction for delegation or model/effort; modules are skills copied
  into a tool's skills dir (`.claude/skills/`, `.agents/skills/`, `.codex/skills/`). Hence the
  tiered design.
- **BMAD update of a custom-source module (`agds`):** `--action quick-update` only re-pulls
  modules cached under `~/.bmad/cache/` and **skips custom-source re-cloning entirely**. And the
  installer never searches the project tree for a custom module's `module.yaml`, so installs can
  emit benign `could not locate module.yaml for 'agds'` warnings. Fix: re-supply the source —
  `npx bmad-method install --action update --custom-source <repo-url> --yes` (re-clones, rewrites
  the manifest source). The README "Updating" section must recommend `--action update
  --custom-source …`, **never** bare `quick-update`. The installer also silently ignores an
  **absolute** `--custom-source` path — use a relative path or URL.
- **Shell globs:** the orchestrator's probe commands run under whatever shell the host uses (zsh,
  fish, bash). An unmatched glob is fatal in zsh/fish (`nomatch` ⇒ exit 1), and `for f in *.glob`
  isn't portable to fish — probes must not iterate raw globs. Use `find … -name '<pat>'`
  (external binary, empty output + exit 0 everywhere) or Python.
