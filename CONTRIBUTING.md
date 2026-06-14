# Contributing to auto-bmad

Thanks for helping improve `auto-bmad`! This guide covers local development, testing, and the
conventions we follow. By participating you agree to our [Code of Conduct](./CODE_OF_CONDUCT.md).

## Repository layout

```
.claude-plugin/marketplace.json        # Claude distribution; lists the single ./auto-bmad skill
auto-bmad/                             # the BMAD standalone module (one skill)
  SKILL.md                             # orchestrator entry point
  references/                          # phase + epic playbooks, delegation, TEA policy, git, state
  assets/                              # module identity, setup, and delegate templates
    agents/profiles.yaml               # source of truth: per-profile persona (description /
                                       # role_blurb / status_example) + per-tool model + effort
    agents/{claude,codex,opencode}/agent.*.tmpl  # one shared body template per tool;
                                       # render-agents.py fills it in for each profile
    config-defaults.yaml               # constant-default setup-block keys the Phase 0 drift
                                       # heal appends to an existing config.yaml
  scripts/                             # dependency-free helpers, each with --self-test
    story_plan.py                      # sprint-status reader; --mark-done flips a story to done
    state_plan.py                      # auto-bmad state-file reader (resume detection);
                                       # --finalize evaluates the Phase 9 draft predicate
    state_update.py                    # deterministic state/report/retro writer
    render-agents.py                   # generates tool-native delegate agents from profiles
    config_plan.py                     # detects/heals profiles<->config drift (Phase 0 self-heal)
    preflight.py                       # one-call Phase 0 preflight (git, skills, CI, hard-stops)
    review_findings.py                 # reconciles code-review findings + the deferral ledger
    review_loop.py                     # Phase 7 loop driver (prep-diff / gate / post-fix)
    ci_wait.py                         # Phase 9 CI wait; classifies the ci_status verdict
    deferred_ledger.py                 # Phase 8 deferred-work archive (plan / sha-guarded move)
    cli_delegate.py                    # resolves opt-in per-phase external-CLI delegation
                                       # (claude -p / codex exec / opencode run) + preflight validation
    merge-config.py, merge-help-csv.py # BMAD-template config/CSV merge (installer environment)
CHANGELOG.md                           # hand-maintained; source for release notes
scripts/bump-version.py                # release helper (repo tooling; does NOT ship in the skill)
skills/reports/                        # tracked module-validation snapshots (repo tooling)
.claude/skills/auto-bmad-compat-check/ # tracked maintainer skill: checks new BMAD releases for
                                       # impact on auto-bmad (repo tooling; does NOT ship)
```

The published repo contains the module + marketplace + docs, plus the repo tooling above
(`scripts/bump-version.py`, `skills/reports/`, and the one tracked maintainer skill under
`.claude/skills/` — a deliberate `.gitignore` exception). A full BMAD install plus generated
delegate agents (`_bmad/`, `_bmad-output/`, `.agents/`, `.claude/`, `.codex/`, `.opencode/`) may
exist locally as a test sandbox; it is gitignored — never commit it.

## Local development & testing

1. **Run the deterministic self-tests** (no Claude Code needed):
   ```bash
   python3 auto-bmad/scripts/story_plan.py --self-test
   python3 auto-bmad/scripts/state_plan.py --self-test
   python3 auto-bmad/scripts/state_update.py --self-test
   python3 auto-bmad/scripts/preflight.py --self-test
   python3 auto-bmad/scripts/render-agents.py --self-test
   python3 auto-bmad/scripts/config_plan.py --self-test
   python3 auto-bmad/scripts/review_findings.py --self-test
   python3 auto-bmad/scripts/review_loop.py --self-test
   python3 auto-bmad/scripts/cli_delegate.py --self-test
   python3 auto-bmad/scripts/ci_wait.py --self-test
   python3 auto-bmad/scripts/deferred_ledger.py --self-test
   python3 scripts/bump-version.py --self-test
   # maintainer-only compat-check skill (repo tooling, not shipped in the module):
   python3 .claude/skills/auto-bmad-compat-check/scripts/bmad_compat.py --self-test
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
  delegator — it must never implement story work itself. A small set of git / finalize / bookkeeping
  actions are the documented exceptions it owns directly (including the Phase 7 code-review **fan-out**,
  which the orchestrator drives because the review skill can't spawn its own sub-agents from inside a
  delegate) — see `CLAUDE.md` → "Core principle" for the canonical list.
- **Epic-mode behavior** (`/auto-bmad epic`) lives in `auto-bmad/references/epic-pipeline.md`. It
  reuses the per-story phases as the epic's inner loop, so a per-story phase change usually flows into
  epic mode for free; the same delegate-only rule (and the epic code-review variants in
  `delegation.md`, kept in lockstep with their base entries) applies.
- **Per-skill delegation prompts** live in `auto-bmad/references/delegation.md`. New BMAD skills
  get a prompt template here, never inline ad-hoc text.
- **Agent profiles** live in `auto-bmad/assets/agents/profiles.yaml` — the single source of truth
  for each profile's persona strings (`description` / `role_blurb` / `status_example`) **and** its
  per-tool model + effort. The tool-native `ab-*` agent files are *generated* from it by
  `scripts/render-agents.py` (filling one shared body template per tool —
  `agents/{claude,codex}/agent.{md,toml}.tmpl`) and are gitignored — never hand-edit them. Add a
  profile only when an existing one doesn't fit, then re-render (`/auto-bmad reprovision`).
- **TEA selection rules** live in `auto-bmad/references/tea-policy.md`.
- **External-CLI routing** (the opt-in `delegation.cli_phases` path) is documented in
  `references/delegation-runtime.md`; its per-tool flag matrix + preflight validation live in the
  tested `scripts/cli_delegate.py`, never in orchestrator prose — keep them there.
- **Every user-facing change needs a `CHANGELOG.md` note** under `## [Unreleased]` (correct
  Keep-a-Changelog heading) in the same PR. Never bump the version files by hand — `scripts/bump-version.py`
  keeps the four version strings in sync at release time.

## Commit & PR conventions

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
  `test:`, `chore:`, `refactor:` (this is also what the orchestrator generates).
- Keep PRs focused; describe the change and how you tested it.
- Run the self-tests, manifest validation, and the module validator before opening a PR.

## Reporting bugs & ideas

Open a GitHub issue with steps to reproduce (and a minimal `sprint-status.yaml` excerpt where
relevant). Security or conduct concerns: stefano@stefanoginella.com.
