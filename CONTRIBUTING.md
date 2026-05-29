# Contributing to auto-bmad

Thanks for helping improve `auto-bmad`! This guide covers local development, testing, and the
conventions we follow. By participating you agree to our [Code of Conduct](./CODE_OF_CONDUCT.md).

## Repository layout

```
.claude-plugin/marketplace.json        # Claude distribution; lists the single ./auto-bmad skill
auto-bmad/                             # the BMAD standalone module (one skill)
  SKILL.md                             # orchestrator entry point
  references/                          # phase playbook, delegation, TEA policy, git, state
  assets/                              # module identity, setup, and delegate templates
    agents/profiles.yaml               # source of truth: per-profile persona (description /
                                       # role_blurb / status_example) + per-tool model + effort
    agents/{claude,codex}/agent.{md,toml}.tmpl  # one shared body template per tool;
                                       # render-agents.py fills it in for each profile
  scripts/                             # dependency-free helpers, each with --self-test
    story_plan.py                      # sprint-status reader (picks the next/explicit story)
    state_plan.py                      # auto-bmad state-file reader (resume detection)
    render-agents.py                   # generates tool-native delegate agents from profiles
    config_plan.py                     # detects/heals profiles<->config drift (Phase 0 self-heal)
    review_findings.py                 # reconciles code-review findings + the deferral ledger
CHANGELOG.md                           # hand-maintained; source for release notes
scripts/bump-version.py                # release helper (repo tooling; does NOT ship in the skill)
```

The published repo contains **only** the module + marketplace + docs. A full BMAD install plus
generated delegate agents (`_bmad/`, `_bmad-output/`, `.agents/`, `.claude/`, `.codex/`) may exist
locally as a test sandbox; it is gitignored — never commit it.

## Local development & testing

1. **Run the deterministic self-tests** (no Claude Code needed):
   ```bash
   python3 auto-bmad/scripts/story_plan.py --self-test
   python3 auto-bmad/scripts/state_plan.py --self-test
   python3 auto-bmad/scripts/render-agents.py --self-test
   python3 auto-bmad/scripts/config_plan.py --self-test
   python3 auto-bmad/scripts/review_findings.py --self-test
   python3 scripts/bump-version.py --self-test
   # story_plan.py also runs standalone:
   python3 auto-bmad/scripts/story_plan.py --sprint-status path/to/sprint-status.yaml
   # add --story 1-3 to target a specific story; output is JSON
   ```

2. **Install it live** to try the skill end-to-end — add this repo as a local marketplace
   (Claude Code) or as a BMAD module source, then run `/auto-bmad` in a BMAD project:
   ```text
   /plugin marketplace add /absolute/path/to/this/repo
   /plugin install auto-bmad@auto-bmad
   ```
   Re-run `/plugin marketplace update auto-bmad` after edits to pick up changes, and
   `/auto-bmad reprovision` to re-render delegate agents after editing `profiles.yaml`.

3. **Validate the module structure and manifest:**
   ```bash
   python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
   # BMAD module validator (run from the repo root, which holds the one skill):
   python3 .claude/skills/bmad-module-builder/scripts/validate-module.py .
   ```

## Making changes

- **Pipeline behavior** lives in `auto-bmad/references/pipeline.md`. Keep the orchestrator a pure
  delegator — it must never implement story work itself (git/PR work is the one exception it owns).
- **Per-skill delegation prompts** live in `auto-bmad/references/delegation.md`. New BMAD skills
  get a prompt template here, never inline ad-hoc text.
- **Agent profiles** live in `auto-bmad/assets/agents/profiles.yaml` — the single source of truth
  for each profile's persona strings (`description` / `role_blurb` / `status_example`) **and** its
  per-tool model + effort. The tool-native `ab-*` agent files are *generated* from it by
  `scripts/render-agents.py` (filling one shared body template per tool —
  `agents/{claude,codex}/agent.{md,toml}.tmpl`) and are gitignored — never hand-edit them. Add a
  profile only when an existing one doesn't fit, then re-render (`/auto-bmad reprovision`).
- **TEA selection rules** live in `auto-bmad/references/tea-policy.md`.
- **Every user-facing change needs a `CHANGELOG.md` note** under `## [Unreleased]` (correct
  Keep-a-Changelog heading) in the same PR. Never bump the version files by hand — `scripts/bump-version.py`
  keeps the three version strings in sync at release time.

## Commit & PR conventions

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
  `test:`, `chore:`, `refactor:` (this is also what the orchestrator generates).
- Keep PRs focused; describe the change and how you tested it.
- Run the self-tests, manifest validation, and the module validator before opening a PR.

## Reporting bugs & ideas

Open a GitHub issue with steps to reproduce (and a minimal `sprint-status.yaml` excerpt where
relevant). Security or conduct concerns: stefano@stefanoginella.com.
