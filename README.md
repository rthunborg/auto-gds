# auto-bmad

A **BMad module** that runs the **full [BMAD](https://github.com/bmad-code-org/BMAD-METHOD) story implementation workflow end-to-end — one story at a time**, on **Claude Code or Codex**.

`auto-bmad` chains the core BMM skills (`create-story` → `dev-story` → `code-review`) and the
optional TEA (Test Architect) skills into a single resumable pipeline. It detects the next
story from `sprint-status.yaml` (or takes one as an argument), runs every step in an isolated
git branch with conventional-commit checkpoints, opens a PR, and finishes with a report of the
PR link, open questions, deferred work, and anything that needs your attention — then stops so
**you** decide when to start the next story.

The orchestrator **only delegates and reports.** Every BMAD step runs inside a sub-agent, with
the model and thinking effort matched to the stakes of the step (e.g. Opus/max for high-stakes
implementation, a faster model for low-stakes mechanics). On **Claude Code and Codex** those
delegates are real, tuned subagents (`.claude/agents` / `.codex/agents`, generated from a
configurable profiles block); on a tool with generic subagents it falls back to those (untuned),
and on one with none it runs steps inline — same pipeline either way.

> Requires an existing BMAD installation in your project (the `/bmad-*` skills + `_bmad/`
> config). auto-bmad orchestrates those skills; it does not replace them.

## Install

**Claude Code** (marketplace):

```text
/plugin marketplace add stefanoginella/auto-bmad
/plugin install auto-bmad@auto-bmad
```

**Codex / other BMad tools:** install the module from this repo with the BMad installer (it
copies the `auto-bmad` skill into your tool's skills dir). Then run `/auto-bmad setup` once to
register the module and provision the tool-native delegate agents.

## Usage

Run from the root of a BMAD-enabled project:

```text
/auto-bmad              # implement the next story from sprint-status.yaml
/auto-bmad 1-3          # implement a specific story (epic 1, story 3)
/auto-bmad 1-3-user-auth
/auto-bmad stop before code-review        # steer a single run (see Overrides)
/auto-bmad --story 1-3 skip git commits
/auto-bmad reprovision                    # re-render delegate agents after editing profiles
```

- **First run in a project** asks a couple of one-time setup questions (TEA on/off, test
  framework/CI scaffolding) and writes `_bmad-output/auto-bmad/config.yaml`.
- **No-argument `/auto-bmad` resumes unfinished work first.** It picks up an interrupted
  auto-bmad pipeline if one exists, otherwise the next actionable story by status
  (`in-progress → review → ready-for-dev → backlog`) — it doesn't jump straight to a fresh
  backlog item. Pass a story id to target one explicitly.
- The pipeline is **resumable** — re-run `/auto-bmad` to continue from the last completed phase
  after an interruption.
- **Code review starts on Opus** and alternates Opus/Sonnet across iterations. If Critical/High
  findings remain after the iteration cap (default 3), it **asks you** whether to run another
  pass, accept the findings and continue (the eventual PR is opened as a draft), or stop.
- A per-story **report log** is saved to `_bmad-output/auto-bmad/reports/<story>.md` — each run
  appends a timestamped section (never overwritten on resume) and the report is also printed.
- It **stops and tells you** whenever something genuinely needs a human (missing planning
  docs, merge conflicts, missing credentials, etc.).

## What it does per story

| Phase | Step | Skill | When |
|-------|------|-------|------|
| 0 | Preflight, triage, first-run config | — | always |
| 1 | Create `story/X-Y-slug` branch | — | always |
| 2 | Epic-level test design | `bmad-testarch-test-design` | first story of epic, TEA on |
| 3 | Create + self-validate story | `bmad-create-story` | always |
| 4 | ATDD acceptance scaffolds | `bmad-testarch-atdd` | TEA on + risk-warranted |
| 5 | Implement story | `bmad-dev-story` | always |
| 6 | Expand automated coverage | `bmad-testarch-automate` | TEA on + risk-warranted |
| 7 | Code review (Opus-first, alternating models, ≤3 iters; asks if unresolved) | `bmad-code-review` | always |
| 8 | Gates, project context, retrospective | `bmad-testarch-trace`/`nfr`/`test-review`, `bmad-generate-project-context`, `bmad-retrospective` | last story of epic |
| 9 | Push + open PR + final report | — | always |

Each phase ends with a conventional commit, so progress survives interruptions and is easy to
review.

## Overrides

Steer a single run by adding instructions to the invocation (natural language or flags) — e.g.
`stop before code-review`, `start at phase 5`, `skip git commits`, `skip TEA`,
`max 5 review iterations`, `git mode local`, `dry run`. The orchestrator echoes how it
interpreted them and which phases will run before executing. See `references/overrides.md`.

## Configuration

`_bmad-output/auto-bmad/config.yaml` (created on first run) controls TEA on/off, git mode
(PR vs local-only), branch prefix, code-review iteration cap + model alternation, the
per-phase profile mapping (`phase_profiles`), and the per-tool model + effort for each delegate
(`profiles`). It also records `delegation.target_tools` — the tools agents are provisioned for.
**Provision both Claude Code and Codex and the same project works in either** — the running tool
is auto-detected each run, so you never reconfigure when you switch. After editing `profiles`
(e.g. to set your Codex model names), run `/auto-bmad reprovision`. See
`references/state-and-resume.md` for the full schema.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) and our [Code of Conduct](./CODE_OF_CONDUCT.md).

## License

[MIT](./LICENSE) © 2026 Stefano Ginella
