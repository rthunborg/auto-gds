# auto-gds — Auto-GDS Orchestrator for BMGD/GDS

[![license: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-0.13.4-blue.svg)](./CHANGELOG.md)
[![BMAD-METHOD](https://img.shields.io/badge/BMAD--METHOD-module-8A2BE2.svg)](https://github.com/bmad-code-org/BMAD-METHOD)
[![Tested with BMAD 6.8.x](https://img.shields.io/badge/tested%20with%20BMAD-6.8.x-8A2BE2.svg)](https://github.com/bmad-code-org/BMAD-METHOD)

Auto-GDS is a fork/adaptation of `auto-bmad` for **BMad Game Dev Studio / BMGD** projects. It keeps
the original orchestration model: one story at a time, an orchestrator that owns git/state/reports,
and delegated subagents for story creation, implementation, and code review.

> **Compatibility:** tested against the **[BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)
> v6 skill line**, currently up to **6.8.0** (and the **6.8.1-next.4** prerelease) with GDS v0.6.0 —
> the check couples to those skills' contracts rather than a pinned version.

Auto-GDS must be run inside a target game project that has:

```text
_bmad/gds/config.yaml
```

If that file is missing, run the BMAD installer with Game Dev Studio enabled first.

## What It Does

`/auto-gds` drives the next story from GDS `sprint-status.yaml`:

- resolves `_bmad/gds/config.yaml`;
- reads `planning_artifacts`, `implementation_artifacts`, `project_name`, `output_folder`, and
  optional GDS keys such as `project_knowledge`, `primary_platform`, `game_dev_experience`,
  `communication_language`, and `document_output_language`;
- resumes any incomplete Auto-GDS state before starting new backlog work;
- delegates the installed GDS skills `gds-create-story`, `gds-dev-story`, and `gds-code-review`;
- refreshes `gds-generate-project-context` and runs `gds-retrospective` where applicable;
- owns branch creation, commits, PR creation, state, reports, and final status updates.

The orchestrator must not implement story code itself.

## Runtime Files

Runtime config/state/reports live in the **target game project**, not this module source repo:

```text
{output_folder}/auto-gds/
```

If `_bmad/gds/config.yaml` has no `output_folder`, Auto-GDS falls back to:

```text
{project-root}/_bmad-output/auto-gds/
```

Do not commit generated target-project runtime folders from this module repository.

## Commands

```text
/auto-gds
/auto-gds 1-3
/auto-gds 1-3-user-auth
/auto-gds status
/auto-gds dry run
/auto-gds stop before code-review
/auto-gds --story 1-3 skip git commits
/auto-gds reprovision
/auto-gds reset-defaults
```

`/auto-gds status` prints a read-only health report (project detection, registration, config
paths, installed GDS skills, sprint status, next eligible story). `/auto-gds dry run` resolves
the full phase plan and stops. Neither creates branches, commits, PRs, or runs GDS production
skills — both are safe for smoke testing.

`/auto-gds reprovision` re-renders local delegate agents:

```text
.claude/agents/agds-*.md
.codex/agents/agds-*.toml
```

Those files are local target-project artifacts and may be gitignored.

## Install

Install as a custom-source BMAD module using this repository URL:

```bash
npx bmad-method install --custom-source <your-auto-gds-repo-url>
```

Select the GDS/BMGD production skills in the same install when needed. The installer records the
module under `[modules.agds]` in `_bmad/config.toml` (team scope) and/or `_bmad/config.user.toml`
(user scope), and writes the module's carry-forward config at `_bmad/agds/config.yaml`. Auto-GDS
reads registration from those TOML files — it never uses `_bmad/config.yaml` — and keeps its own
runtime config at `{output_folder}/auto-gds/config.yaml`. Then run:

```text
/auto-gds setup
```

## Updating

Auto-GDS installs as a **custom-source** BMAD module, so an update has to re-supply its source.
Re-run the installer in `update` mode pointing at this repo:

```bash
npx bmad-method install --action update --custom-source <your-auto-gds-repo-url> --yes
```

> ⚠️ **Don't update Auto-GDS with `--action quick-update`** (also the interactive default for an
> existing install). quick-update only re-pulls modules whose source is already cached under
> `~/.bmad/cache/` and skips custom-source re-cloning entirely — Auto-GDS is then **silently
> skipped** and `bmad update` keeps warning `could not locate module.yaml for 'agds'`. Always
> re-supply `--custom-source` as above.

Delegate agents re-render themselves after an update: the next `/auto-gds` run detects stale
generated agents at preflight and reprovisions automatically. To refresh them yourself (e.g.
right after editing `profiles`), run `/auto-gds reprovision`.

## Testing Workflow Status

GDS testing workflow integration is future work in V0. Auto-GDS does **not** require or call the old
BMM Test Architect workflow by default.

Future mappings may include:

- `gds-test-design`
- `gds-test-automate`
- `gds-test-review`
- `gds-performance-test`
- `gds-playtest-plan`
- `gds-test-framework`
- `gds-e2e-scaffold`

## Development

Run helper self-tests from the repository root:

```bash
python auto-gds/scripts/story_plan.py --self-test
python auto-gds/scripts/state_plan.py --self-test
python auto-gds/scripts/render-agents.py --self-test
python auto-gds/scripts/config_plan.py --self-test
python auto-gds/scripts/review_findings.py --self-test
```
