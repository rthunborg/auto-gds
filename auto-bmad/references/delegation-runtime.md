# Delegation runtime — host detection & how to spawn a profile

`delegation.md` says **what** to tell a delegate (the tool-agnostic prompt body); this file says
**how** to spawn it on the current host and degrade gracefully. Three config fields (in
`{output_folder}/auto-bmad/config.yaml`, see `state-and-resume.md`) drive everything:
- `delegation.host` — `claude-code` | `codex` | `opencode` | `other`
- `delegation.mode` — `custom-subagents` | `general-subagents` | `inline`
- `delegation.cli_phases` — opt-in per-phase override routing a phase to an external CLI instead of
  an in-tool sub-agent (absent/empty ⇒ none; see "Per-phase external-CLI routing" below).

`phase_profiles` (also in config) maps each phase to a profile name — one of the shipped four
(`ab-deep`, `ab-standard`, `ab-alt-deep`, `ab-alt-standard`) or a custom `ab-*` profile the user
added to the config's `profiles` block (see `state-and-resume.md`); `profiles` holds each
profile's per-tool model + effort.

## Resolving host & mode (every run)

Both default to `auto` and are **re-detected on every run** — one provisioned project runs under any
supported tool; an explicit non-`auto` value forces the choice. `delegation.target_tools` is
**separate**: it only controls which agent files were generated, not which tool runs now.

Detect the host in this order — **env-var signals first** (they identify the tool *currently
executing*, which coexisting on-disk dirs cannot):
1. **Claude Code** — `${CLAUDE_PLUGIN_ROOT}` is set → `custom-subagents`.
2. **opencode** — `${OPENCODE_SESSION_ID}` is set → `custom-subagents`.
3. **On-disk fallback** (no env signal): a `.claude/` dir → Claude Code; a `.opencode/` dir or the
   `opencode` CLI on PATH → opencode; a `.codex/` dir or the `codex` CLI on PATH → Codex. All three
   support `custom-subagents`.
4. **Other** — none of the above. General subagent/Task mechanism → `general-subagents`; else → `inline`.

If the detected host needs `custom-subagents`, **verify the agent files are present _and_ current**
(existence alone misses drift after a module update or a `profiles` edit) with the freshness check:

```bash
python3 ./scripts/render-agents.py --check --project-root "{project-root}" \
  --tools "<comma-joined target_tools>" --profiles "{output_folder}/auto-bmad/config.yaml"
```

Read the JSON `needs_reprovision` (exit 1 ⇒ stale). When true, **auto-reprovision** — rerun without
`--check` (the `reprovision` action; see `module-setup.md`) — and **report it prominently** in the
Phase 0 preflight echo and the final report ("⚠ Delegate agents were stale — regenerated N
file(s)"). Cases: `missing` ⇒ never rendered for this tool; `stale` ⇒ out of date; `extra` ⇒ left
over from a tool dropped from `target_tools` (reported, not auto-removed). Reprovisioning is
deterministic and safe (generated, gitignored files) and needs no human stop, but only fully applies
next launch (see below): for `stale`, continue on the launch-time definitions (they still resolve)
and report that a restart is needed; for `missing` (not in the launch-time roster), the run
**cannot invoke it this session** — stop and have the user restart, don't silently degrade. A host
that genuinely lacks custom-subagent support instead falls back to `general-subagents`/`inline` for
this run, noted in the report.

### Newly-rendered agents need a process restart (custom-subagents only)

Claude Code loads project delegate agents (`.claude/agents/*.md`) into the **invokable-agent roster
once, at process launch**; Codex (`.codex/agents/*.toml`) likewise; treat an opencode **host
session** (`.opencode/agent/*.md`) the same conservatively (a headless `opencode run` on the
cli-route path is a fresh process and always re-scans — this caveat is about the running host
only). Agents rendered *during* a session (first-run setup, `reprovision`, auto-reprovision) are on
disk but **not invokable until the tool is fully quit and relaunched**; a `/clear` or "new chat"
reuses the **same process** and does **not** re-scan the agents dir.

So `--check` reporting `fresh` proves the files are correct on disk, not that the current process
can invoke them — the canonical symptom is the Agent/Task tool returning **`Agent type 'ab-…' not
found`** though the file exists and is fresh. On a custom-subagents host that means **"restart
needed," not "host lacks custom subagents"**: stop, tell the user to quit & relaunch, then re-run —
do **not** degrade to Tier 2 when a restart restores full fidelity. Only a host with no
custom-subagent mechanism at all degrades (see the tiers below).

## Per-phase external-CLI routing (opt-in — sits *above* the tiers)

A phase can be delegated to an **external CLI** — `claude -p`, `codex exec` or `opencode run` — via
the `delegation.cli_phases` map (keys = `phase_profiles` keys, value = a tool name; absent/empty ⇒
**every phase uses its normal tier**; schema: `state-and-resume.md`, examples:
`assets/config-defaults.yaml`). **Opt-in and
orthogonal** — an unrouted phase falls straight through to the tiers below.

**Before spawning any phase, check `cli_phases` first**; if the phase key is present, take the CLI
path. It is **still delegation** — you build the command, deliver the prompt, capture the child's
structured-result block, then do your own git/finalize bookkeeping; you never read or write story
code yourself.

**Resolve the invocation with the helper — do not hand-build the command** (the per-tool flag
matrix lives in the script, tested):

```bash
python3 {skill-root}/scripts/cli_delegate.py --phase <phase> \
  --config "{output_folder}/auto-bmad/config.yaml" --project-root "{project-root}" \
  --story-key <story_key> --host <resolved-host: claude-code|codex|opencode> --mkdir
```

(Pass the **resolved** host detected this run, not the literal config `auto`.)

It prints JSON. `routed:false` ⇒ use the normal tier. Otherwise it gives `tool`, `model`, `effort`
(from the phase's profile's matching tool block; **for opencode both `model` and the variant are
optional — `null` ⇒ inherit the user's opencode defaults**, never a hard-stop), the `argv`
(prompt-less), `prompt_via`, `cwd`, the OS-temp `capture_log`, and `result_source`. It also runs
the **preflight `validation`**: binary on PATH; that tool's BMAD skills present — looked up in the
tool's own skills dirs (claude: `.claude/skills`; codex: `.agents/skills`, `.codex/skills`,
`~/.codex/skills`; opencode: `.opencode/skills`, `~/.config/opencode/skills`, plus the
`command`/`commands` siblings of both — some BMAD opencode installs expose the skills as
slash-command files `bmad-*.md` there, which works at runtime — project paths
relative to the project root), **not** `target_tools` (the CLI path consumes no rendered agent files;
don't "fix" that); and `auth` for the **non-host** tool only (lenient for opencode — see notes
below). **`ok:false` ⇒ hard-stop** with its `errors`; never silently degrade to an agent. Echo the
routed phases + resolved tool/model/effort in the Phase 0 preflight and final report, next to
`delegation.mode`.

**Build the prompt exactly as Tier 2 does** (a CLI invocation has no pre-rendered agent persona):
the shared autonomy directive from `delegation.md` **plus** the "How you operate / What you return"
body from `assets/agents/claude/agent.md.tmpl`, with the mapped profile's `role_blurb` /
`status_example` substituted **from the runtime config's `profiles` block** (the live source —
it carries persona retunes and custom profiles the shipped asset doesn't; fall back to
`assets/agents/profiles.yaml` only if the config lacks the strings), **plus** the `delegation.md`
step body with placeholders filled (story id, absolute paths).

**Spawn it in-place and capture:** deliver the prompt per `prompt_via` — pipe to **stdin** for
claude/codex; for **opencode** append it as the **final positional `argv` element** (`opencode run`
does NOT read stdin). Run in the **same repo dir** (`cwd`) — no HOME/Docker isolation; the child
edits the real working tree you then commit. codex (`-C <cwd>`) and opencode (`--dir <cwd>`) pin
their working root in the argv; the **claude** argv has no equivalent, so a `claude` route MUST
`cd "$cwd"` before the call. **Every routed invocation runs in the background — never foreground:**
host shell tools cap foreground commands far below real delegate runtimes (Claude Code: 2-min
default, 10-min max; a routed step — `dev_story`, a review lens — routinely needs 20+ min). Launch
it detached, stdout redirected to `capture_log`, and monitor to process exit; if the background
mechanism still takes a timeout knob, set it to **at least 30 minutes**. Long runtimes are normal —
declare a delegate wedged (a failed delegation: hard-stop) only after `capture_log` has been silent
for that same allowance with the process still alive.
Then read `result_source`: claude → parse `result_field` (`.result`) from the JSON envelope,
`error_field` (`.is_error`) true = failed delegation; codex → read the `-o` last-message file
verbatim; opencode → pass `capture_log` (the `--format json` event stream) through
`cli_delegate.py`'s `extract_opencode_result()`.

**Failure detection is uniform — never proceed on an empty result.** A missing/blank required field
is a **failed delegation: hard-stop.** claude → `.result` absent/blank OR `.is_error` true; codex →
empty/absent `-o` file; opencode → `extract_opencode_result` returns no message. (Verified against
real output: claude `2.1.169`, codex `0.138.0`, opencode `1.16.2`.) `capture_log` is **debug-grade,
outside the repo** — surface its path **only when a delegation fails**.

Notes: codex runs under its `-s workspace-write` sandbox (network-restricted) — route phases needing
network/installs to `claude`/`opencode`, or leave them in-tool. opencode runs with
`--dangerously-skip-permissions` (headless auto-approve); its auth preflight is **lenient**
(keyless/local/config providers ⇒ "0 credentials" never hard-stops), so it won't catch a missing
cloud login — an unauthenticated `opencode run` on a cloud/Zen model **blocks indefinitely**: make
sure opencode is logged in before routing to it. Routing a reviewer-slot phase
(`code_review_review`, `code_review_review_secondary`, `code_review_review_tertiary`) sends **that
reviewer's three lens delegates** through the CLI — plus, for `code_review_review` only, the
**triage** (it always runs at the primary profile) — one invocation each, with a
distinct `--label` per delegate (e.g. `blind-hunter-primary`, `edge-case-secondary`, `triage`) so
`capture_log` / `-o` paths don't collide. **Launch the lens invocations in parallel** — across
CLI-routed reviewers too — as concurrent background processes (the spawn rule above), and wait for
all of them to exit before the triage, which consumes their outputs. This holds on **every** host
— CLI delegates are plain OS child processes with per-`--label` capture paths, and the lenses only
write their own reserved lens-output files, never the tree, so concurrent runs can't collide.
Routing a slot whose `phase_profiles` value is blank is a
config error (`cli_delegate.py` reports "no phase_profiles mapping").

## Tier 1 — `custom-subagents` (Claude Code, Codex & opencode)

Full fidelity: the delegate runs in an isolated context at the profile's tuned model + effort
(**opencode is model-only** — see its caveat below). Look up the phase's profile via
`phase_profiles`, then:

- **Claude Code:** delegate with the Agent/Task tool, `subagent_type` = the profile name, resolving
  to the project-level `.claude/agents/<name>.md` rendered at setup (no plugin namespace prefix).
  The agent body already carries the autonomy directive; the prompt is the `delegation.md` body
  with placeholders filled.
- **Codex:** Codex spawns a subagent only when explicitly asked, identifying it by `name` — phrase
  the delegation unambiguously, e.g.:

  > Use the **ab-deep** agent to do the following, then report back its full structured result
  > block (Outcome / Files changed / Status / Open questions / Deferred work / Blockers / Retro
  > notes):
  > <the delegation.md prompt body>

  For pipeline steps, delegate **one** profile at a time and wait for its consolidated result (the
  pipeline itself is sequential). Where the pipeline fans out (the Phase 7 lenses), name **all** the
  agents in one request — Codex spawns subagents **in parallel** and returns a consolidated
  response once every one finishes (`[agents]` `max_threads` defaults to 6; `max_depth` defaults
  to 1, so a delegate still can't spawn its own subagents — the fan-out hoist stands). Parse each
  returned structured block exactly as on Claude Code.
- **opencode:** spawns a subagent on request, identified by name — delegate via its Task tool or an
  `@ab-deep` mention (phrased as unambiguously as the Codex example), resolving to the
  project-level `.opencode/agent/<name>.md` rendered at setup. Parallel fan-out is supported —
  spawn the Phase 7 lens delegations concurrently. **Fidelity caveat:** the delegate
  runs at the profile's `opencode.model` (blank — the shipped default — ⇒ **inherits your opencode
  default model**) with **no effort tuning** (no portable effort knob; reasoning is
  provider-specific — set it per-agent-name in `opencode.json` if wanted). So opencode is Tier-1
  for *isolation* but, by default, *untuned* — record that in the run report like the Tier-2 effort
  caveat (pointing `ab-alt-*` at a different vendor buys real cross-model review diversity).

In all cases, after the delegate returns: read the structured result, append Retro notes,
checkpoint, update state.

## Tier 2 — `general-subagents`

The host has isolated subagents/Task delegation but **no per-agent model/effort knob**. Spawn the
host's generic subagent with the prompt body; because there's no baked-in agent persona, **prepend
the operating guidance inline**: the shared autonomy directive from `delegation.md` **plus** the
"How you operate / What you return" guidance from `assets/agents/claude/agent.md.tmpl`, with the
mapped profile's `role_blurb` and `status_example` substituted from the runtime config's
`profiles` block (the live source — it carries persona retunes and custom profiles; fall back to
`assets/agents/profiles.yaml` only if the config lacks the strings).
Effort is not honored — record `delegation.mode: general-subagents` in the run report (steps ran
untuned).

## Tier 3 — `inline`

The host has no subagents at all. Run the step **yourself, in this context**, following the
`delegation.md` prompt body and the mapped profile's operating guidance — the only mode where the
orchestrator does the step's work directly, used solely because the host offers no alternative.
To keep the rest of the machinery intact:
- Do each phase strictly in order; finish and **emit the same structured result block** a delegate
  would (the fields in the Codex example above) before moving on — state, retro notes, and the
  report all depend on it.
- Honor every hard-stop / `needs-human` condition.
- You lose context isolation and per-step model/effort tuning; note `delegation.mode: inline`
  prominently in the report.

## One rule that survives every tier

The pipeline, phase conditions, TEA policy, git/PR conventions, resume logic, and the structured
result contract are **identical across tiers** — and across the external-CLI path. Only the spawn
mechanism changes. Never invent a delegation path not listed here (the tiers + `cli_phases` are the
complete set); if a phase isn't CLI-routed and the host fits no tier, use `inline`.
