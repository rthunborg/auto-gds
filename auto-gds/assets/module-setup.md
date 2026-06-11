# Module Setup

Standalone module setup. This file is loaded when:
- The user passes `setup`, `configure`, or `install` as an argument
- The central BMad config has no `[modules.agds]` table in `{project-root}/_bmad/config.toml`
  or `{project-root}/_bmad/config.user.toml`

## Overview

Prepares this module to run inside a project. Module identity (name, code, version) comes from
`./assets/module.yaml` (sibling to this file). In BMad v6 the **installer owns central
registration**; this flow verifies it, collects Auto-GDS preferences, and provisions the
delegate agents. The config surfaces involved:

- **`{project-root}/_bmad/config.toml`** — BMad v6 team-scope central config, written by the
  **BMad installer**. Module registration and install-time answers live under `[modules.agds]`.
  This skill only **reads** it — never writes.
- **`{project-root}/_bmad/config.user.toml`** — BMad v6 user-scope central config (personal,
  typically gitignored). May also carry `[modules.agds]` values. Read-only here too.
- **`{project-root}/_bmad/agds/config.yaml`** — the installed module's carry-forward config,
  written by the BMad installer. It is **not** the orchestrator runtime config; never write it
  and never read it for runtime settings.
- **`{output_folder}/auto-gds/config.yaml`** — the Auto-GDS **runtime config**: the only config
  this module writes (seeded by the first-run flow in `references/state-and-resume.md`).
- **`{project-root}/_bmad/module-help.csv`** — registers module capabilities for the help system.

Never read, write, or require `_bmad/config.yaml` — BMad v6 central config is TOML, and central
registration belongs to the installer. The help-CSV script uses an anti-zombie pattern —
existing entries for this module are removed before writing fresh ones, so stale values never
persist.

`{project-root}` is a **literal token** in config values — never substitute it with an actual path. It signals to the consuming LLM that the value is relative to the project root, not the skill root.

Before writing anything, confirm the target project is a BMGD/GDS project: `_bmad/` exists and
`_bmad/gds/config.yaml` is readable. If not, hard-stop with:
"Not a BMGD/GDS project (no `_bmad/gds/config.yaml`). Run the BMAD installer with Game Dev Studio enabled first."

## Check Registration

1. Read `./assets/module.yaml` for module metadata and variable definitions (the `code` field is the module identifier — `agds`)
2. Check central registration: look for a `[modules.agds]` table in
   `{project-root}/_bmad/config.toml`, then `{project-root}/_bmad/config.user.toml`. Parse with
   Python stdlib `tomllib` (Python ≥ 3.11):

   ```bash
   python3 -c "import tomllib,sys; d=tomllib.load(open(sys.argv[1],'rb')); sys.exit(0 if 'agds' in d.get('modules',{}) else 1)" "{project-root}/_bmad/config.toml"
   ```

   On older Pythons, fall back to scanning the file text for a `[modules.agds]` table header.
3. Interpret the result:
   - **Registered** (table found in either file): this is an update (reconfiguration) — say so,
     and use any values recorded under `[modules.agds]` as defaults below — **except
     `target_tools`**: the installer records a static default from `module.yaml` and cannot
     detect which tool(s) the install actually targets, so for `target_tools` host detection
     takes precedence (see "Provision Delegate Agents" step 1).
   - **Not registered, but the Auto-GDS runtime config already exists**: the project was
     provisioned without installer registration (e.g. a plugin-style install). Unless the user
     explicitly asked for `setup`/`configure`/`install`/`reprovision`, inform them once —
     recommend re-running the BMad installer with this module as a custom source — and return to
     the skill without re-running setup.
   - **Not registered and no runtime config**: fresh project. Central registration is owned by
     the BMad installer (`npx bmad-method install --custom-source …`); note that it's missing,
     recommend the installer, and continue — this flow can still provision the runtime config
     and delegate agents without it.

If the user provides arguments (e.g. `accept all defaults`, `--headless`, or inline values like `user name is BMAD, I speak Swahili`), map any provided values to config keys, use defaults for the rest, and skip interactive prompting. Still display the full confirmation summary at the end.

## Collect Configuration

Ask the user for values. Show defaults in brackets. Present all values together so the user can respond once with only the values they want to change (e.g. "change language to Swahili, rest are fine"). Never tell the user to "press enter" or "leave blank" — in a chat interface they must type something to respond.

**Default priority** (highest wins): existing config values > `./assets/module.yaml` defaults.

### Core Config

Core values (`user_name`, `communication_language`, `document_output_language`,
`output_folder`) are owned by the BMad installer's central TOML config and by
`_bmad/gds/config.yaml` — do **not** collect or write them here. Auto-GDS resolves
`output_folder` from `_bmad/gds/config.yaml` at runtime, with the
`{project-root}/_bmad-output` fallback.

### Module Config

Read each variable in `./assets/module.yaml` that has a `prompt` field. The module.yaml supports several question types:

- **Text input**: Has `prompt`, `default`, and optionally `result` (template), `required`, `regex`, `example` fields
- **Single-select**: Has a `single-select` array of `value`/`label` options — present as a choice list
- **Multi-select**: Has a `multi-select` array — present as checkboxes, default is an array
- **Confirm**: `default` is a boolean — present as Yes/No

Ask using the prompt with its default value. Apply `result` templates when storing (e.g. `{project-root}/{value}`). Fields with `user_setting: true` are personal preferences — they still land in the Auto-GDS runtime config like any other module answer; never write them to the installer-owned central TOML files.

## Write Files

Central registration is **not** written here — `[modules.agds]` in `_bmad/config.toml` /
`_bmad/config.user.toml` belongs to the BMad installer. This flow persists only:

1. **Auto-GDS runtime config** — the collected module answers (e.g. `target_tools`) land in
   `{output_folder}/auto-gds/config.yaml` under `delegation`:
   - if the runtime config already exists, update the affected keys in place
     (e.g. `delegation.target_tools`);
   - if it doesn't exist yet, hand the answers to the first-run flow in
     `references/state-and-resume.md`, which seeds the full file.
2. **Help registration:**

   ```bash
   python3 ./scripts/merge-help-csv.py --target "{project-root}/_bmad/module-help.csv" --source ./assets/module-help.csv --module-code {module-code}
   ```

   The script outputs JSON to stdout with results. If it exits non-zero, surface the error and
   stop. Run `./scripts/merge-help-csv.py --help` for full usage.

## Create Output Directories

After writing config, create any configured output directories that don't exist yet. For filesystem operations only (such as creating directories), resolve the `{project-root}` token to the actual project root — paths stored in config files must continue to use the literal `{project-root}` token. Create the resolved `output_folder` (from `_bmad/gds/config.yaml`, fallback `{project-root}/_bmad-output`) and the `auto-gds` directory beneath it, plus any module variable whose value starts with `{project-root}/`. Use `mkdir -p` or equivalent to create the full path.

If `./assets/module.yaml` contains a `directories` array, also create each listed directory (resolving any `{field_name}` variables from the collected config values).

## Provision Delegate Agents (Auto-GDS)

Auto-GDS delegates each production pipeline step to a model/effort-tuned subagent. Those subagents are
tool-native files that must be generated into the host's agent directory. Do this here so the
module is ready to run immediately after setup.

1. **Determine `target_tools` — default to the AIs this BMAD install targets, then confirm.**
   Detect from where the `auto-gds` skill is installed (the tools that can actually invoke it):
   - `claude-code` if `.claude/skills/auto-gds/` exists;
   - `codex` if `.agents/skills/auto-gds/` exists (BMAD installs Codex skills under `.agents/`),
     or if `.codex/skills/auto-gds/` / `~/.codex/skills/auto-gds/` exists.

   Use the **union** of the detected set and any `target_tools` recorded under `[modules.agds]`
   as the **default** for the `target_tools` question (fall back to `[claude-code]` if both are
   empty) — detection reflects where the skill is actually installed, while the recorded value
   is only the installer's static `module.yaml` default, so it must never *narrow* the detected
   set. Then **still ask** — the user confirms, drops one, or adds a tool they plan to install
   later. On a headless/accept-all-defaults run, use that union default as-is. Provisioning is
   independent of which tool *runs* the pipeline (that's auto-detected each run).
2. **Confirm a supported host is present** (informational — `delegation.host`/`mode` stay `auto`
   and are re-detected on every run, not pinned here): Claude Code if `${CLAUDE_PLUGIN_ROOT}` is
   set or a `.claude/` dir exists; Codex if a `.codex/` dir or the `codex` CLI is present.
   Claude Code and Codex support `custom-subagents`; a host with only a generic subagent
   mechanism uses `general-subagents`, and one with none uses `inline` (see
   `references/delegation-runtime.md`).
3. **Render the delegate files** for the selected tools (resolve `{project-root}` to the real
   path; defaults come from `./assets/agents/profiles.yaml`):

   ```bash
   python3 ./scripts/render-agents.py --project-root "{project-root}" --tools "<comma-joined target_tools>"
   ```

   This writes `.claude/agents/agds-*.md` and/or `.codex/agents/agds-*.toml`. Surface the JSON
   result; if it exits non-zero or reports warnings, show them.
4. Both Claude Code and Codex profiles ship with real defaults that need no change. Model names
   are environment-specific, so if a tool's install exposes different names the user can retune the
   `profiles` block in the resolved GDS runtime config (`{output_folder}/auto-gds/config.yaml`,
   or `{project-root}/_bmad-output/auto-gds/config.yaml` when `_bmad/gds/config.yaml` has no
   `output_folder`) and run `/auto-gds reprovision` — but don't flag this as a required manual
   step.

Runtime config/state/reports are written in the target game project under
`{output_folder}/auto-gds` after `_bmad/gds/config.yaml` is read. If the GDS config has no
`output_folder`, Auto-GDS falls back to `{project-root}/_bmad-output/auto-gds`. Do not create
generated runtime config, state, reports, story artifacts, or `_bmad-output` in this module source
repository.

**Reprovision-only path:** if the user invoked with `reprovision` (or asked only to regenerate
agents after editing profiles), skip config collection entirely and run just step 3 above,
reading the live profiles from the resolved GDS runtime config (`--profiles
"{output_folder}/auto-gds/config.yaml"`, or the `_bmad-output/auto-gds` fallback when the GDS
config has no `output_folder`; fall back to the shipped defaults if that file doesn't exist yet).
The orchestrator also auto-reprovisions at
preflight when agents are stale — see `references/delegation-runtime.md` → "Resolving host &
mode", so users rarely have to run this by hand. On `custom-subagents` hosts the (re)rendered
agents become invokable only after a full tool restart; see `references/delegation-runtime.md` →
"Newly-rendered agents need a process restart" before telling the user what to do next.

## Confirm

Display what was done — central registration status (`[modules.agds]` found in `_bmad/config.toml` / `_bmad/config.user.toml`, or missing with the installer recommendation), runtime config values written to `{output_folder}/auto-gds/config.yaml`, help entries added (from the merge-help-csv JSON output), delegate agents rendered, and fresh install vs update.

If `./assets/module.yaml` contains `post-install-notes`, display them (if conditional, show only the notes matching the user's selected config values).

Then display the `module_greeting` from `./assets/module.yaml` to the user.

## Return to Skill

Setup is complete. Resume the main skill's normal activation flow — load config from the freshly written files. If this was a `setup`/`configure`/`reprovision`-only invocation, stop here (already reported). If it was a run-intent invocation that triggered setup only because the module wasn't registered, continue into the Procedure to finish the first-run flow, then **stop for a fresh session** per the first-run stop in `references/state-and-resume.md` — the pipeline must not run on the same context that just did configuration.
