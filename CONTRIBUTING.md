# Contributing to auto-gds

This repository contains the Auto-GDS module source for BMGD/GDS projects. It is not a target game
project, so do not commit generated runtime folders such as `_bmad-output/`, `.claude/agents/`,
`.codex/agents/`, state files, reports, generated config, or story artifacts.

## Layout

```text
.claude-plugin/marketplace.json
auto-gds/
  SKILL.md
  assets/
  references/
  scripts/
```

## Local Checks

`sandbox/` (gitignored) holds throwaway fresh-project simulations for install smoke tests —
each subfolder is its own git-init'ed project where BMAD + this module get installed via
`npx bmad-method install --yes --directory . --modules gds --custom-source ../.. --tools <ids>`
(run from inside the subfolder; the custom source path must stay **relative**). Never commit it.

Run helper self-tests from the repository root:

```bash
python auto-gds/scripts/story_plan.py --self-test
python auto-gds/scripts/state_plan.py --self-test
python auto-gds/scripts/render-agents.py --self-test
python auto-gds/scripts/config_plan.py --self-test
python auto-gds/scripts/review_findings.py --self-test
python .claude/skills/auto-gds-compat-check/scripts/bmad_compat.py --self-test
```

## Editing Rules

- Keep `auto-gds/references/delegation.md` as the single source of exact delegated `gds-*`
  skill commands (`gds-create-story`, `gds-dev-story`, `gds-code-review`,
  `gds-generate-project-context`, `gds-retrospective`).
- Keep `auto-gds/assets/agents/profiles.yaml` as the shipped source for `agds-*` profiles.
- Preserve the orchestrator boundary: story code is delegated, while git/state/reports/PR/final
  status are orchestrator-owned.
- GDS testing workflow integration is disabled by default in V0; future mappings should use
  dedicated BMGD skills rather than old BMM testing commands.
