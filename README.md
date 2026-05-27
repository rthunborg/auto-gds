# auto-bmad

A Claude Code orchestrator that runs the **full [BMAD](https://github.com/bmad-code-org/BMAD-METHOD) story implementation workflow end-to-end — one story at a time.**

`auto-bmad` chains the core BMM skills (`create-story` → `dev-story` → `code-review`) and the
optional TEA (Test Architect) skills into a single resumable pipeline. It detects the next
story from `sprint-status.yaml` (or takes one as an argument), runs every step in an isolated
git branch with conventional-commit checkpoints, opens a PR, and finishes with a report of the
PR link, open questions, deferred work, and anything that needs your attention — then stops so
**you** decide when to start the next story.

The orchestrator **only delegates and reports.** Every BMAD step runs inside a sub-agent, with
the model and thinking effort matched to the stakes of the step (Opus for high-stakes
implementation/review, Sonnet for low-stakes mechanics).

> Requires an existing BMAD installation in your project (the `/bmad-*` skills + `_bmad/`
> config). auto-bmad orchestrates those skills; it does not replace them.

## Install

```text
/plugin marketplace add stefanoginella/auto-bmad
/plugin install auto-bmad@auto-bmad
```

## Usage

Run from the root of a BMAD-enabled project:

```text
/auto-bmad              # implement the next story from sprint-status.yaml
/auto-bmad 1-3          # implement a specific story (epic 1, story 3)
/auto-bmad 1-3-user-auth
```

- **First run in a project** asks a couple of one-time setup questions (TEA on/off, test
  framework/CI scaffolding) and writes `_bmad-output/auto-bmad/config.yaml`.
- The pipeline is **resumable** — re-run `/auto-bmad` (same story) to continue from the last
  completed phase after an interruption.
- It **stops and tells you** whenever something genuinely needs a human (missing planning
  docs, merge conflicts, unresolved review findings, missing credentials, etc.).

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
| 7 | Code review (≤3 iterations, alternating models) | `bmad-code-review` | always |
| 8 | Gates, project context, retrospective | `bmad-testarch-trace`/`nfr`/`test-review`, `bmad-generate-project-context`, `bmad-retrospective` | last story of epic |
| 9 | Push + open PR + final report | — | always |

Each phase ends with a conventional commit, so progress survives interruptions and is easy to
review.

## Configuration

`_bmad-output/auto-bmad/config.yaml` (created on first run) controls TEA on/off, git mode
(PR vs local-only), branch prefix, code-review iteration cap + model alternation, and the
per-phase agent profile mapping. See the skill's `references/state-and-resume.md` for the
full schema.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) and our [Code of Conduct](./CODE_OF_CONDUCT.md).

## License

[MIT](./LICENSE) © 2026 Stefano Ginella
