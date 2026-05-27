# CLAUDE.md — working in the auto-bmad repo

This repo is a **Claude Code plugin + custom marketplace**. The plugin (`auto-bmad`) is an
orchestrator skill that runs the full BMAD story workflow one story at a time. This file is
guidance for working **on the plugin**, not for using it.

## Core principle (do not violate)
The orchestrator **only delegates and reports** — it must never implement story work, run
`/bmad-*` skills directly, or do git surgery itself beyond checkpoint commits. Every BMAD step
runs in a bundled `ab-*` sub-agent. When editing the skill, preserve this separation.

## Layout
- `.claude-plugin/marketplace.json` — marketplace listing the single plugin.
- `plugins/auto-bmad/.claude-plugin/plugin.json` — plugin manifest.
- `plugins/auto-bmad/agents/ab-{max,xhigh,high,sonnet}.md` — delegate profiles. Each bakes in a
  `model` + `effort` (thinking budget). Effort can ONLY be set via this frontmatter, not via the
  Agent tool — that's why these exist.
- `plugins/auto-bmad/skills/auto-bmad/SKILL.md` — orchestrator entry point (the procedure).
- `plugins/auto-bmad/skills/auto-bmad/references/` — where the real detail lives:
  `pipeline.md` (per-phase playbook), `delegation.md` (exact per-skill prompts),
  `tea-policy.md` (risk rubric), `git-and-pr.md`, `state-and-resume.md` (config/state/first-run).
- `plugins/auto-bmad/skills/auto-bmad/scripts/story_plan.py` — dependency-free, deterministic
  sprint-status reader (next story + epic boundaries). Has a `--self-test`.

## Where behavior lives
- Change the **pipeline** → `references/pipeline.md`. Change **what a step tells an agent** →
  `references/delegation.md`. Change **TEA selection** → `references/tea-policy.md`. Change
  **config/state schema or first-run** → `references/state-and-resume.md`. Keep `SKILL.md` thin.

## Testing
```bash
# Deterministic core:
python3 plugins/auto-bmad/skills/auto-bmad/scripts/story_plan.py --self-test
# Manifests are valid JSON:
python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
python3 -m json.tool plugins/auto-bmad/.claude-plugin/plugin.json >/dev/null
# Live: add this repo as a local marketplace, then install + run /auto-bmad in a BMAD project.
```

## Conventions
- Conventional Commits (`feat:`/`fix:`/`docs:`/`test:`/`chore:`/`refactor:`).
- Never commit the local BMAD test install — `_bmad/`, `_bmad-output/`, `.agents/`, `.claude/`
  are gitignored. The published repo is plugin + marketplace + docs only.
- Markdown reference files are read by the orchestrator at runtime; keep them concise and
  unambiguous (they are instructions, not prose).

## Known platform facts (verified)
- Sub-agents CAN invoke skills and take a per-invocation `model`; they CANNOT spawn sub-agents.
- Per-agent thinking effort = `effort:` frontmatter on the sub-agent definition only.
- `/bmad-create-story` has no `validate` mode; it self-validates against its checklist.
