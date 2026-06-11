# Delegation runtime — host detection & how to spawn a profile

`delegation.md` says **what** to tell a delegate (the tool-agnostic prompt body); this file says
**how** to spawn it on the current host and degrade gracefully when the host can't do isolated,
effort-tuned subagents.

Two config fields (in `<auto_gds_dir>/config.yaml`, see `state-and-resume.md`) drive
everything:
- `delegation.host` — `claude-code` | `codex` | `other`
- `delegation.mode` — `custom-subagents` | `general-subagents` | `inline`

`phase_profiles` (also in config) maps each phase to a profile name (`agds-xhigh`, `agds-high`,
`agds-alt-xhigh`, `agds-alt-high`); `profiles` holds each profile's per-tool model + effort.

## Resolving host & mode (every run)

`delegation.host` and `delegation.mode` default to `auto` and are **re-detected on every run** —
so one project, with agents provisioned for both tools, runs in Claude Code *or* Codex with no
reconfiguration. `delegation.target_tools` is **separate**: it only decides which agent files were
generated, not which tool runs now. An explicit non-`auto` value in config forces the choice.

Detect the host in this order, then pick the best tier it supports:
1. **Claude Code** — `${CLAUDE_PLUGIN_ROOT}` is set, or a `.claude/` dir exists → `custom-subagents`.
2. **Codex** — a `.codex/` dir exists or the `codex` CLI is on PATH → `custom-subagents`.
3. **Other** — neither. General subagent/Task mechanism → `general-subagents`; else → `inline`.

If the detected host needs `custom-subagents`, **verify the agent files are present _and_ current**
before relying on them — checking existence alone lets the generated agents drift silently after a
module update (new templates) or a `profiles` edit. Run the freshness check, which re-renders every
agent in memory and diffs it against the on-disk files:

```bash
python3 ./scripts/render-agents.py --check --project-root "{project-root}" \
  --tools "<comma-joined target_tools>" --profiles "<auto_gds_dir>/config.yaml"
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
once, at process launch** — and Codex loads `.codex/agents/*.toml` the same way. Agents rendered
*during* a session (first-run setup, an explicit `reprovision`, or an auto-reprovision) are written
to disk but are **not invokable until the tool is fully quit and relaunched**. A `/clear` or "new
chat" starts a fresh *context* in the **same process** and does **not** re-scan the agents dir.

So `render-agents.py --check` reporting `fresh` proves the files are correct on disk — not that the
current process can invoke them. The canonical symptom is the Agent/Task tool returning
**`Agent type 'agds-…' not found`** though the file exists and is fresh. On a custom-subagents host,
read that as **"restart needed," not "host lacks custom subagents":** stop and tell the user to quit
& relaunch, then re-run — do **not** degrade to Tier 2, which would run the pipeline untuned when a
restart restores full fidelity. (Only a host with no custom-subagent mechanism at all degrades — see
the tiers below.) This is also why the first-run stop (`state-and-resume.md`) sends the user to
relaunch the tool, not merely open a fresh context.

## Tier 1 — `custom-subagents` (Claude Code & Codex)

Full fidelity: the delegate runs in an isolated context at the profile's tuned model + effort.
Look up the profile for the phase via `phase_profiles`, then:

- **Claude Code:** delegate with the Agent/Task tool, `subagent_type` = the profile name
  (`agds-xhigh` / `agds-high` / `agds-alt-xhigh` / `agds-alt-high`). These resolve to the project-level
  `.claude/agents/<name>.md` rendered at setup. (No plugin namespace prefix — they are project
  agents now.) The agent body already carries the autonomy directive; the prompt is the
  `delegation.md` body with placeholders filled.
- **Codex:** Codex spawns a subagent only when explicitly asked, and identifies it by its
  `name`. Phrase the delegation unambiguously, e.g.:

  > Use the **agds-xhigh** agent to do the following, then report back its full structured result
  > block (Outcome / Files changed / Status / Open questions / Deferred work / Blockers / Retro
  > notes):
  > <the delegation.md prompt body>

  Delegate **one** profile at a time and wait for its consolidated result before the next phase
  (the pipeline is sequential — do not fan out). Parse the returned structured block exactly as
  on Claude Code.

In both cases, after the delegate returns: read the structured result, append Retro notes,
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

The pipeline, phase conditions, testing policy, git/PR conventions, resume logic, and the structured
result contract are **identical across tiers**. Only the spawn mechanism changes. Never invent a
delegation path not listed here; if the host fits none, use `inline`.
