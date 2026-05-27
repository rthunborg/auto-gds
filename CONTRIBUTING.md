# Contributing to auto-bmad

Thanks for helping improve `auto-bmad`! This guide covers local development, testing, and the
conventions we follow. By participating you agree to our [Code of Conduct](./CODE_OF_CONDUCT.md).

## Repository layout

```
.claude-plugin/marketplace.json        # marketplace that lists the plugin
plugins/auto-bmad/
  .claude-plugin/plugin.json           # plugin manifest
  agents/                              # effort-tuned delegate profiles (ab-*.md)
  skills/auto-bmad/
    SKILL.md                           # orchestrator entry point
    references/                        # phase playbook, delegation, TEA policy, git, state
    scripts/story_plan.py              # deterministic sprint-status parser
```

The published repo contains **only** the plugin + marketplace + docs. A full BMAD install
(`_bmad/`, `_bmad-output/`, `.agents/`, `.claude/`) may exist locally as a test sandbox; it is
gitignored — never commit it.

## Local development & testing

1. **Unit-test the parser** (no Claude Code needed):
   ```bash
   python3 plugins/auto-bmad/skills/auto-bmad/scripts/story_plan.py \
     --sprint-status path/to/sprint-status.yaml
   # add --story 1-3 to target a specific story; output is JSON
   ```

2. **Install from a local marketplace** to try the skill live:
   ```text
   /plugin marketplace add /absolute/path/to/this/repo
   /plugin install auto-bmad@auto-bmad
   ```
   Re-run `/plugin marketplace update auto-bmad` after edits to pick up changes.

3. **Validate the manifests** are well-formed JSON:
   ```bash
   python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
   python3 -m json.tool plugins/auto-bmad/.claude-plugin/plugin.json >/dev/null
   ```

## Making changes

- **Pipeline behavior** lives in `skills/auto-bmad/references/pipeline.md`. Keep the
  orchestrator a pure delegator — it must never implement story work itself.
- **Per-skill delegation prompts** live in `references/delegation.md`. New BMAD skills get a
  prompt template here, never inline ad-hoc text.
- **Agent profiles** (`agents/ab-*.md`) bundle a model + `effort:` level. Add a profile only
  when an existing one doesn't fit; document it in `SKILL.md`'s profile table.
- **TEA selection rules** live in `references/tea-policy.md`.

## Commit & PR conventions

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
  `test:`, `chore:`, `refactor:` (this is also what the orchestrator generates).
- Keep PRs focused; describe the change and how you tested it.
- Run the manifest validation and parser tests before opening a PR.

## Reporting bugs & ideas

Open a GitHub issue with steps to reproduce (and a minimal `sprint-status.yaml` excerpt where
relevant). Security or conduct concerns: stefano@stefanoginella.com.
