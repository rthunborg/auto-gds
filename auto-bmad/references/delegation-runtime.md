# Delegation runtime — host detection & how to spawn a profile

`delegation.md` says **what** to tell a delegate (the tool-agnostic prompt body). This file says
**how** to actually spawn it on the current host, and how to degrade gracefully when the host
can't do isolated, effort-tuned subagents.

Two config fields (in `{output_folder}/auto-bmad/config.yaml`, see `state-and-resume.md`) drive
everything:
- `delegation.host` — `claude-code` | `codex` | `other`
- `delegation.mode` — `custom-subagents` | `general-subagents` | `inline`

`phase_profiles` (also in config) maps each phase to a profile name (`ab-max`, `ab-xhigh`,
`ab-high`, `ab-sonnet`); `profiles` holds each profile's per-tool model + effort. This file
turns "delegate phase X" into a concrete spawn.

## Resolving host & mode

Normally set once at setup (`module-setup.md` detects tools and writes them). If the config is
missing or you must re-derive at runtime, detect in this order and pick the **best tier the host
supports**:

1. **Claude Code** — `${CLAUDE_PLUGIN_ROOT}` is set, or a `.claude/` dir exists. Supports
   `custom-subagents`.
2. **Codex** — a `.codex/` dir exists or the `codex` CLI is on PATH. Supports
   `custom-subagents`.
3. **Other** — neither. If the host has *some* general subagent/Task mechanism →
   `general-subagents`; otherwise → `inline`.

If `mode` is `custom-subagents` but the rendered agent files are absent
(`.claude/agents/ab-*.md` / `.codex/agents/ab-*.toml`), the provisioning step was skipped —
run the renderer once (see `module-setup.md`, the `reprovision` action) before delegating, or
fall back to `general-subagents` for this run and note it in the report.

## Tier 1 — `custom-subagents` (Claude Code & Codex)

Full fidelity: the delegate runs in an isolated context at the profile's tuned model + effort.
Look up the profile for the phase via `phase_profiles`, then:

- **Claude Code:** delegate with the Agent/Task tool, `subagent_type` = the profile name
  (`ab-max` / `ab-xhigh` / `ab-high` / `ab-sonnet`). These resolve to the project-level
  `.claude/agents/<name>.md` rendered at setup. (No plugin namespace prefix — they are project
  agents now.) The agent body already carries the autonomy directive; the prompt is the
  `delegation.md` body with placeholders filled.
- **Codex:** Codex spawns a subagent only when explicitly asked, and identifies it by its
  `name`. Phrase the delegation unambiguously, e.g.:

  > Use the **ab-max** agent to do the following, then report back its full structured result
  > block (Outcome / Files changed / Status / Open questions / Deferred work / Blockers / Retro
  > notes):
  > <the delegation.md prompt body>

  Delegate **one** profile at a time and wait for its consolidated result before the next phase
  (the pipeline is sequential — do not fan out). Parse the returned structured block exactly as
  on Claude Code.

In both cases, after the delegate returns: read the structured result, append Retro notes,
checkpoint, update state — identical to today's flow.

## Tier 2 — `general-subagents`

The host has isolated subagents/Task delegation but **no per-agent model/effort knob**. Spawn
the host's generic subagent with the prompt body. Because there's no baked-in agent persona,
**prepend the operating guidance inline**: the shared autonomy directive from `delegation.md`
**plus** the one-paragraph "How you operate / What you return" guidance for the mapped profile
(copy it from the matching `assets/agents/claude/<name>.md.tmpl` body). Effort is not honored —
record `delegation.mode: general-subagents` in the run report so the user knows steps ran
untuned. Everything else (sequential, structured result, retro notes, checkpoints) is unchanged.

## Tier 3 — `inline`

The host has no subagents at all. Run the step **yourself, in this context**, following the
`delegation.md` prompt body and the mapped profile's operating guidance. This is the only mode
where the orchestrator does the step's work directly — an explicit, documented exception to the
"only orchestrate" rule, used solely because the host offers no alternative.

To keep the rest of the machinery intact:
- Do each phase strictly in order; finish and **emit the same structured result block** (Outcome
  / Files changed / Status / Open questions / Deferred work / Blockers / Retro notes) before
  moving on, exactly as a delegate would — state, retro notes, and the report all depend on it.
- Honor every hard-stop / `needs-human` condition.
- You lose context isolation (no fresh reasoning budget per step) and per-step model/effort
  tuning; note `delegation.mode: inline` prominently in the report.

## One rule that survives every tier

The pipeline, phase conditions, TEA policy, git/PR conventions, resume logic, and the structured
result contract are **identical across tiers**. Only the spawn mechanism changes. Never invent a
delegation path not listed here; if the host fits none, use `inline`.
