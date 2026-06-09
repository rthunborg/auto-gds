# Delegation runtime — host detection & how to spawn a profile

`delegation.md` says **what** to tell a delegate (the tool-agnostic prompt body); this file says
**how** to spawn it on the current host and degrade gracefully when the host can't do isolated,
effort-tuned subagents.

Three config fields (in `{output_folder}/auto-bmad/config.yaml`, see `state-and-resume.md`) drive
everything:
- `delegation.host` — `claude-code` | `codex` | `opencode` | `other`
- `delegation.mode` — `custom-subagents` | `general-subagents` | `inline`
- `delegation.cli_phases` — opt-in per-phase override that delegates a phase to an external CLI
  instead of an in-tool sub-agent (absent/empty ⇒ none; see "Per-phase external-CLI routing" below).

`phase_profiles` (also in config) maps each phase to a profile name (`ab-deep`, `ab-standard`,
`ab-alt-deep`, `ab-alt-standard`); `profiles` holds each profile's per-tool model + effort.

## Resolving host & mode (every run)

`delegation.host` and `delegation.mode` default to `auto` and are **re-detected on every run** —
so one project, with agents provisioned for both tools, runs in Claude Code *or* Codex with no
reconfiguration. `delegation.target_tools` is **separate**: it only decides which agent files were
generated, not which tool runs now. An explicit non-`auto` value in config forces the choice.

Detect the host in this order — **env-var signals first**, because they identify the tool
*currently executing*, which a multi-provisioned project's coexisting `.claude/` + `.codex/` +
`.opencode/` dirs cannot:
1. **Claude Code** — `${CLAUDE_PLUGIN_ROOT}` is set → `custom-subagents`.
2. **opencode** — `${OPENCODE_SESSION_ID}` is set (opencode injects it into the shell env of every
   command it runs — the analog of `CLAUDE_PLUGIN_ROOT`) → `custom-subagents`.
3. **On-disk fallback** (no env signal): a `.claude/` dir → Claude Code; a `.opencode/` dir or the
   `opencode` CLI on PATH → opencode; a `.codex/` dir or the `codex` CLI on PATH → Codex. All three
   support `custom-subagents`.
4. **Other** — none of the above. General subagent/Task mechanism → `general-subagents`; else → `inline`.

If the detected host needs `custom-subagents`, **verify the agent files are present _and_ current**
before relying on them — checking existence alone lets the generated agents drift silently after a
module update (new templates) or a `profiles` edit. Run the freshness check, which re-renders every
agent in memory and diffs it against the on-disk files:

```bash
python3 ./scripts/render-agents.py --check --project-root "{project-root}" \
  --tools "<comma-joined target_tools>" --profiles "{output_folder}/auto-bmad/config.yaml"
```

Read the JSON `needs_reprovision` (exit 1 ⇒ stale). When true, **auto-reprovision** — rerun the same
command without `--check` (the `reprovision` action; see `module-setup.md`) — then **report it
prominently** in the Phase 0 preflight echo and the final report, e.g. *"⚠ Delegate agents were stale
(module updated and/or profiles changed since last provisioned) — regenerated N file(s) before this
run."* The check distinguishes the cases: `missing` ⇒ never rendered for this tool (e.g. provisioned
only for the other one); `stale` ⇒ out of date; `extra` ⇒ left over from a tool dropped from
`target_tools` (reported, not auto-removed). Reprovisioning is deterministic and safe (the agent
files are generated and gitignored), so the **files** self-heal without a human stop — but on Claude
Code/Codex the **running process loaded its agent roster at launch and won't reload it mid-run** (see
"Newly-rendered agents need a process restart" below). So a mid-run regeneration only fully applies
next launch: for `stale`, continue this run with the launch-time definitions (they still resolve) and
report that a restart is needed for the new model/effort/body to take effect; for `missing` (the
agent wasn't on disk at launch, so it isn't in the roster at all) the run **cannot invoke it this
session** — stop and have the user restart, don't silently degrade. A host that genuinely lacks
custom-subagent support is different: there, fall back to `general-subagents`/`inline` for this run
and note it in the report.

### Newly-rendered agents need a process restart (custom-subagents only)

Claude Code loads project delegate agents (`.claude/agents/*.md`) into the **invokable-agent roster
once, at process launch** — Codex loads `.codex/agents/*.toml` the same way, and treat an opencode
**host session** (`.opencode/agent/*.md`) the same conservatively (a headless `opencode run` in the
cli-route path is a fresh process and always re-scans, so this caveat is about the running host
only). Agents rendered *during* a session (first-run setup, an explicit `reprovision`, or an
auto-reprovision) are written to disk but are **not invokable until the tool is fully quit and
relaunched**. A `/clear` or "new chat" starts a fresh *context* in the **same process** and does
**not** re-scan the agents dir.

So `render-agents.py --check` reporting `fresh` proves the files are correct on disk — not that the
current process can invoke them. The canonical symptom is the Agent/Task tool returning
**`Agent type 'ab-…' not found`** though the file exists and is fresh. On a custom-subagents host,
read that as **"restart needed," not "host lacks custom subagents":** stop and tell the user to quit
& relaunch, then re-run — do **not** degrade to Tier 2, which would run the pipeline untuned when a
restart restores full fidelity. (Only a host with no custom-subagent mechanism at all degrades — see
the tiers below.) This is also why the first-run stop (`state-and-resume.md`) sends the user to
relaunch the tool, not merely open a fresh context.

## Per-phase external-CLI routing (opt-in — sits *above* the tiers)

A phase can be delegated to an **external CLI** — `claude -p`, `codex exec` or `opencode run` —
instead of an in-tool sub-agent. This is **opt-in and orthogonal**: it changes nothing about the
three tiers below, and a phase that isn't routed falls straight through to them. The opt-in is the
`delegation.cli_phases` map in config (keys = `phase_profiles` keys, value = a tool name;
absent/empty ⇒ **every phase uses its normal tier**):

```yaml
delegation:
  cli_phases:
    code_review_review_secondary: opencode   # second-opinion review on a DIFFERENT vendor's model
    retrospective: codex                      # ...or any phase on `codex exec`
```

**Before spawning any phase, check `cli_phases` first.** If the phase key is present, take the CLI
path below; otherwise drop to the tiers. The CLI path is **still delegation** — you build a command,
pipe a prompt, capture the child's structured-result block, then do your own git/finalize bookkeeping;
you never read or write story code yourself. Same structured-result contract, state, resume, retro
notes, and checkpoints as every other delegation.

**Resolve the invocation with the helper — do not hand-build the command** (the per-tool flag matrix
is exactly what it pins down):

```bash
python3 {skill-root}/scripts/cli_delegate.py --phase <phase> \
  --config "{output_folder}/auto-bmad/config.yaml" --project-root "{project-root}" \
  --story-key <story_key> --host <resolved-host: claude-code|codex|opencode> --mkdir
```

(Pass the **resolved** host you detected this run, not the literal config `auto`; the helper skips the
auth probe for the host tool and probes the other. Omitting `--host` just always probes — safe.)

It prints JSON. `routed:false` ⇒ use the normal tier. Otherwise it gives `tool`, `model`, `effort`
(claude `effort` / codex `reasoning_effort` / opencode `--variant`, from the phase's profile's
matching tool block — the same values `render-agents.py` bakes into the in-tool delegates; **for
opencode both `model` and the variant are optional — `null` ⇒ inherit the user's opencode defaults**,
so a routed opencode phase never hard-stops on a "missing" model/effort), the `argv` (prompt-less),
`prompt_via` (`stdin` for claude/codex; `arg` for opencode — see below), `cwd`, the OS-temp
`capture_log`, and how to read the result back. It also runs the **preflight `validation`** (binary on
PATH, that tool's BMAD skills present, and — for the **non-host** tool only, since the host is authed
by definition — `auth`; opencode's auth check is **lenient** — it supports keyless/local/config
providers, so it never hard-stops on "0 credentials"). **`ok:false` ⇒ hard-stop** with its `errors`;
never silently degrade to an agent (the user opted in deliberately, and falling back would hide the
cross-tool intent). Skills are looked up in the tool's **skills dir** — claude `.claude/skills/`;
codex `.agents/skills/` *or* `.codex/skills/` *or* `~/.codex/skills/`; opencode `.opencode/skills/`
*or* `~/.config/opencode/skills/` — **not** `target_tools` (the CLI path consumes no rendered agent
files, so `target_tools` is irrelevant here; don't "fix" that). Echo the routed phases + resolved
tool/model/effort in the Phase 0 preflight and the final report, next to `delegation.mode`.

**Build the prompt exactly as Tier 2 does** (a CLI invocation has no pre-rendered agent persona):
the shared autonomy directive from `delegation.md` **plus** the "How you operate / What you return"
body from `assets/agents/claude/agent.md.tmpl`, with the mapped profile's `role_blurb` /
`status_example` substituted, **plus** the `delegation.md` step body with placeholders filled (story
id, absolute paths).

**Spawn it in-place and capture:** deliver the prompt per `prompt_via` — for claude/codex pipe it to
**stdin**; for **opencode** append the assembled prompt as the **final positional `argv` element**
(`opencode run` does NOT read stdin). Run in the **same repo dir** (`cwd`) — no HOME/Docker isolation;
the child edits the real working tree you then commit. **codex** pins its working root with `-C <cwd>`
and **opencode** with `--dir <cwd>` in the argv, but the **claude** argv has no equivalent — so for a
`claude` route you MUST `cd "$cwd"` before the call (a headless `claude -p` edits whatever the shell
cwd is). A routed step can outlive the 10-min foreground cap (`dev_story`), so run it in the
**background** with stdout redirected to `capture_log` and monitor to process exit. Then read the
result from `result_source`: claude → parse `result_field` (`.result`) out of the JSON envelope and
treat `error_field` (`.is_error`) true as a failed delegation; codex → read the file verbatim (the
`-o` last-message — the clean, complete block); **opencode** → pass `capture_log` (the `--format json`
event stream) through `cli_delegate.py`'s `extract_opencode_result()`.

**Failure detection is uniform across all three — never proceed on an empty result.** If the field we
need is missing or blank, treat it as a **failed delegation and hard-stop** (do not continue the
pipeline on an empty delegate result): claude → `.result` absent/blank, OR `.is_error` true; codex →
an empty or absent `-o` file; opencode → `extract_opencode_result` returns no message. So if a tool's
JSON output ever **diverges in what we read**, you get an explicit hard-stop, not a silent empty step.
(The three were verified against real output — claude `2.1.169`, codex `0.138.0`, opencode `1.16.2`.
claude's `.result` and codex's `-o` file are single well-defined values, so divergence tends to make
them *missing* → caught here; opencode's multi-event stream has more surface, so its parser adds
defensive fallbacks before that same hard-stop — a wrong-but-nonempty extraction is the one residual
risk, only there.) `capture_log` is **debug-grade and lives outside the repo** — surface its path in
the report **only when a delegation fails**.

Notes: codex runs under its `-s workspace-write` sandbox (network-restricted) — a phase needing
network/installs may not suit codex; route those to `claude`/`opencode` or leave them in-tool.
**opencode** runs with `--dangerously-skip-permissions` (headless auto-approve) and resolves its model
through whatever provider the user configured (`-m provider/model`, optional `--variant` for
reasoning) — a blank model just uses their opencode default.

The opencode cli-route **result parsing is verified** against a real opencode 1.16.2
`run --format json` capture: the assistant's reply is the concatenated `part.text` of the top-level
`type:"text"` events (`extract_opencode_result`), with defensive fallbacks and a hard-stop if
nothing parses. **Practical preflight note:** a cloud/Zen model needs `opencode auth login` first —
an unauthenticated `opencode run` blocks indefinitely — so make sure opencode is logged in before
routing a phase to it. (The `cli_delegate.py` auth probe stays **lenient** and won't hard-stop on "0
credentials", because local/config providers — e.g. an LM Studio `baseURL` — need no credential.) Routing `code_review_review` /
`code_review_review_secondary` sends **all four** code-review fan-out delegates (three lenses + triage)
through the CLI — one invocation each, still sequential, but pass a distinct `--label` per delegate
(e.g. `blind-hunter`, `edge-case`, `acceptance-auditor`, `triage`) so their `capture_log` / `-o`
paths don't collide.

## Tier 1 — `custom-subagents` (Claude Code, Codex & opencode)

Full fidelity: the delegate runs in an isolated context at the profile's tuned model + effort
(**opencode is model-only** — see its caveat below). Look up the profile for the phase via
`phase_profiles`, then:

- **Claude Code:** delegate with the Agent/Task tool, `subagent_type` = the profile name
  (`ab-deep` / `ab-standard` / `ab-alt-deep` / `ab-alt-standard`). These resolve to the project-level
  `.claude/agents/<name>.md` rendered at setup. (No plugin namespace prefix — they are project
  agents now.) The agent body already carries the autonomy directive; the prompt is the
  `delegation.md` body with placeholders filled.
- **Codex:** Codex spawns a subagent only when explicitly asked, and identifies it by its
  `name`. Phrase the delegation unambiguously, e.g.:

  > Use the **ab-deep** agent to do the following, then report back its full structured result
  > block (Outcome / Files changed / Status / Open questions / Deferred work / Blockers / Retro
  > notes):
  > <the delegation.md prompt body>

  Delegate **one** profile at a time and wait for its consolidated result before the next phase
  (the pipeline is sequential — do not fan out). Parse the returned structured block exactly as
  on Claude Code.
- **opencode:** opencode spawns a subagent on request and identifies it by name — delegate via its
  Task tool or an `@ab-deep` mention (phrase it as unambiguously as the Codex example above).
  These resolve to the project-level `.opencode/agent/<name>.md` rendered at setup. **Fidelity
  caveat:** the delegate runs at the profile's `opencode.model` (or **inherits your opencode default
  model** when that is blank — the shipped default) but with **no effort tuning** — opencode agent
  files have no portable effort knob (its reasoning setting is provider-specific; set it
  per-agent-name in `opencode.json` if wanted). So opencode is Tier-1 for *isolation* but, by
  default, *untuned* — record that in the run report like the Tier-2 effort caveat, and note that
  pointing `ab-alt-*` at a different vendor than `ab-deep` buys genuine cross-model review diversity.

In all cases, after the delegate returns: read the structured result, append Retro notes,
checkpoint, update state.

## Tier 2 — `general-subagents`

The host has isolated subagents/Task delegation but **no per-agent model/effort knob**. Spawn
the host's generic subagent with the prompt body. Because there's no baked-in agent persona,
**prepend the operating guidance inline**: the shared autonomy directive from `delegation.md`
**plus** the "How you operate / What you return" guidance from the shared body template
`assets/agents/claude/agent.md.tmpl`, with the mapped profile's `role_blurb` and
`status_example` substituted from `assets/agents/profiles.yaml`. Effort is not honored —
record `delegation.mode: general-subagents` in the run report so the user knows steps ran
untuned. Everything else (sequential, structured result, retro notes, checkpoints) is unchanged.

## Tier 3 — `inline`

The host has no subagents at all. Run the step **yourself, in this context**, following the
`delegation.md` prompt body and the mapped profile's operating guidance. This is the only mode
where the orchestrator does the step's work directly — used solely because the host offers no
alternative.

To keep the rest of the machinery intact:
- Do each phase strictly in order; finish and **emit the same structured result block** (Outcome
  / Files changed / Status / Open questions / Deferred work / Blockers / Retro notes) before
  moving on, exactly as a delegate would — state, retro notes, and the report all depend on it.
- Honor every hard-stop / `needs-human` condition.
- You lose context isolation (no fresh reasoning budget per step) and per-step model/effort
  tuning; note `delegation.mode: inline` prominently in the report.

## One rule that survives every tier

The pipeline, phase conditions, TEA policy, git/PR conventions, resume logic, and the structured
result contract are **identical across tiers** — and across the opt-in external-CLI path above. Only
the spawn mechanism changes. Never invent a delegation path not listed here (the tiers + the
`cli_phases` route are the complete set); if a phase isn't CLI-routed and the host fits no tier, use
`inline`.
