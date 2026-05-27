# CLAUDE.md — working in the auto-bmad repo

This repo is a **BMad standalone module** (distributed as a single skill + a Claude
`marketplace.json`). The skill (`auto-bmad`) is an orchestrator that runs the full BMAD story
workflow one story at a time, on **Claude Code or Codex**. This file is guidance for working
**on the module**, not for using it.

## Core principle (do not violate)
The orchestrator **delegates BMAD work and reports** — it must never implement story work or run
`/bmad-*` skills directly. Every BMAD step (create-story, dev-story, code-review, TEA, retro)
runs in a delegated `ab-*` sub-agent. **Git/PR work is the deliberate exception that the
orchestrator owns directly** (never delegated): preflight detection, branching, per-phase
commits, push, and PR — it holds the full pipeline context to write commit/PR messages, and a
round-trip to a delegate would only be slower. Apart from git, the **only** time the orchestrator
does step work itself is the `inline` delegation tier (hosts with no subagent support — see
`delegation-runtime.md`), and even then it follows the same phase contract and structured-result
discipline. When editing, preserve this separation.

## Delegation is tiered (the heart of the module)
BMad abstracts neither sub-agent delegation nor per-agent model/effort, so we supply those with
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
- `auto-bmad/assets/agents/profiles.yaml` — default per-tool model+effort. `claude/*.md.tmpl` and
  `codex/*.toml.tmpl` — delegate templates with `@@MODEL@@`/`@@EFFORT@@`/`@@REASONING_EFFORT@@`.
- `auto-bmad/assets/module.yaml` + `module-help.csv` + `module-setup.md` — BMad module
  identity, capability registry, and self-registration/provisioning flow.
- `auto-bmad/scripts/story_plan.py` — dependency-free sprint-status reader (`--self-test`).
- `auto-bmad/scripts/render-agents.py` — dependency-free agent generator (`--self-test`).
- `auto-bmad/scripts/merge-config.py` + `merge-help-csv.py` — config/CSV merge (from the BMad
  standalone-module template; use PyYAML via the BMad installer's environment).

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
python3 auto-bmad/scripts/render-agents.py --self-test
# Marketplace manifest is valid JSON:
python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
# Module structure passes the BMad validator (run from the repo root, which holds the one skill):
python3 .claude/skills/bmad-module-builder/scripts/validate-module.py .
# Live: add this repo as a local marketplace (Claude) or BMad module source, install, run
# /auto-bmad in a BMAD project. `/auto-bmad reprovision` re-renders agents after editing profiles.
```

## Conventions
- Conventional Commits (`feat:`/`fix:`/`docs:`/`test:`/`chore:`/`refactor:`).
- Never commit the local BMAD test install or generated agents — `_bmad/`, `_bmad-output/`,
  `.agents/`, `.claude/`, `.codex/` are gitignored. The published repo is module + marketplace +
  docs only.
- Markdown reference files are read by the orchestrator at runtime; keep them concise and
  unambiguous (they are instructions, not prose). Helper scripts stay dependency-free with a
  `--self-test`.

## Known platform facts (verified)
- **Claude Code:** sub-agents take `model:` + `effort:` frontmatter (effort is settable ONLY
  there, not via the Agent tool — that's why the templates exist); they CAN invoke skills but
  CANNOT spawn sub-agents.
- **Codex:** subagents are TOML files in `.codex/agents/` (project) or `~/.codex/agents/`, with
  `model` + `model_reasoning_effort` (effort: minimal|low|medium|high); invoked by naming the
  agent in natural language — Codex spawns/collects them. Model names are environment-specific
  (confirmed at setup), so they're config, not hardcoded.
- **BMad** has no portable abstraction for delegation or model/effort; modules are skills copied
  into a tool's skills dir (`.claude/skills/`, `.codex/skills/`). Hence the tiered design.
- `/bmad-create-story` has no `validate` mode; it self-validates against its checklist.
