# Per-story pipeline

The orchestrator runs these phases **in order** for a single story. Each phase: check its
condition → delegate the named **`delegation.md` entry** (the hyphenated name in **bold backticks**
below, e.g. **`create-story`**) to the profile `phase_profiles` assigns to the phase (each phase
also names its `phase_profiles` **key** — the underscored form, e.g. `→ create_story`; resolve
key → profile → model+effort via config — the mapping lives only in config, never hardcode a
profile name here). `delegation.md` owns the exact `/bmad-*` command + prompt; spawn it for the
current host/tier per `delegation-runtime.md` → read the result → if `blocked`/`needs-human`, stop
and report → else update the state file (append retro notes, mark the phase done in
`completed_phases`, record timing — see `state-and-resume.md`) and **commit it in the same single
commit as the phase's artifacts** (see `git-and-pr.md` → "Commits"; **never** a standalone
state-only commit). Each phase below gives its `Commit:` **subject only** — every commit also
carries a **required body** (and a footer when relevant), built from that phase's own facts, per
`git-and-pr.md` → "Message body & footer". When updating state, also record timing — never with hand-rolled `date` arithmetic: bracket each
phase with `python3 {skill-root}/scripts/state_update.py timing-start --state-file <state>` just
before delegating and `… timing-pause …` when it returns (just before the state write + commit);
the script owns the clock math and folds the interval into `active_seconds` — this is what lets
the report split AI-run time from human/idle wait (`state-and-resume.md` → timing fields).
**Don't count time spent waiting on the user:** if the phase opens an `AskUserQuestion` (e.g. the
Phase 7 decision asks or the HITL halt), invert the bracket — `timing-pause` before the prompt,
`timing-start` after — so the wait lands on human/idle, not active. (A `dropped_anchor: true`
from `timing-start` means a prior session crashed mid-bracket; the dangling interval is discarded
conservatively — expected on resume, not an error.)

**Git/PR work is orchestrator-owned, not delegated** — see `git-and-pr.md` → "Ownership" for the
full list. The git-only phases below (0 preflight, 1 branch, 9 finalize) carry no
`phase_profiles` key; only their non-git parts (e.g. Phase 0's TEA triage) are delegated.

Placeholders (`{e}`/`{s}`, `{key}`, `{slug}`, `<impl>`, `<story_file>`, …) are defined once in
`delegation.md` — the canonical glossary.

---

## Phase 0 — Preflight & triage  *(git preflight: orchestrator; TEA triage: `tea_triage`)*
Runs during Step 1 of the SKILL procedure (before any commit).
- **Probe discipline (applies to every orchestrator-run check here and below):** do existence /
  enumeration probes with `find`, `test`, or Python — **never a bare glob** (`ls *.x`,
  `for f in *.x`). An unmatched glob aborts with exit 1 under zsh/fish (`nomatch`), whereas
  `find`/`test` give empty output + exit 0 in every shell. And probe by real on-disk names: state
  files are `{key}.yaml`, story files `{key}.md` — neither carries the `story-{e}-{s}` prefix
  that only commit/PR scopes use. State-file enumeration is encapsulated in
  `scripts/state_plan.py` (the deterministic reader — call it, don't re-derive); this rule then
  governs the git, project-context, and framework/CI existence probes that stay hand-rolled. See
  `CLAUDE.md` → "Shell globs".
- Verify required skills exist for the selected path. Missing → hard-stop.
- Git preflight (**orchestrator runs this directly**): is this a git repo? is the working tree
  clean? detect git mode (gh installed AND a GitHub remote → `remote`; else `local`); detect the
  base branch. Dirty tree on a non-story branch → hard-stop.
- **Config drift heal (orchestrator; all hosts):** the runtime `config.yaml` is seeded **once** at
  first run and is never re-touched by a module update, so a newer asset's keys silently never reach
  the project. Two axes drift: the `profiles`/`phase_profiles` blocks (e.g. a `tea_triage` phase
  mapping added in a later version — and `render-agents.py --check` below can't see this, because it
  only diffs the four rendered agent files and never reads `phase_profiles`), AND new
  **setup-block** keys (`delegation`/`tea`/`git`/`code_review` — e.g. `git.offer_merge`,
  `tea.story_trace_advisory`), which have no profiles-style asset and so are normally invisible until
  a Full `configure` or a hand-edit. Reconcile both deterministically:
  ```
  python3 {skill-root}/scripts/config_plan.py --check --config <output_folder>/auto-bmad/config.yaml
  ```
  (the shipped `assets/agents/profiles.yaml`, `assets/config-defaults.yaml`, and `assets/module.yaml`
  resolve relative to the script). On `status: drift` (exit 1 — asset `profiles`/`phase_profiles`
  keys the config lacks, **constant-default setup keys it lacks** (`missing_setup`), and/or
  `profiles_source_version` older than the installed `module_version`), **auto-apply** the additive
  heal — re-run with `--apply` — which appends only the MISSING keys (never overwriting a user value;
  the setup-defaults asset deliberately omits environment-detected fields like `git.base_branch`, so
  the heal can't bake in a wrong guess) and restamps `profiles_source_version`. Run this **before** the provisioning-freshness
  check below, so a re-seeded profile *value* is then caught there as a stale agent file (a re-seeded
  `phase_profiles`/setup key needs no re-render — it maps to an existing profile or is delegate-free).
  `manual_review` items (a sub-key missing from a profile that already exists — rare, value-bearing)
  are **surfaced in the report**, not auto-written.
  - **Disclosure echo (only when the heal added a setup key — `--apply`'s `added_setup` is
    non-empty):** show a brief, **non-blocking** block in the preflight echo (and the final report),
    then continue — the heal is behaviour-neutral (each default equals the orchestrator's absent-key
    fallback), so there is nothing to approve; **never** open an `AskUserQuestion`/halt here. Read
    the lists straight from the `--apply` JSON — don't recompute or read code. Render, in this shape:
    - a **lead line** naming what happened — `config.yaml updated to match v<module_version>`;
    - *Added N new setting(s) (defaults; behaviour unchanged)* — one `path = value` per `added_setup`
      entry;
    - *Kept your M customisation(s)* — one `path = value  (default <default>)` per `kept_setup`
      entry (omit this list entirely when `kept_setup` is empty);
    - a **closer line** that signals it did not block — `→ continuing pipeline…`.

    If nothing was added (`added_setup` empty — the common case once a project is current), show
    nothing. `reseeded_*` profile/phase_profile reseeds and the `manual_review` note stay in the
    report as before.
- **Provisioning freshness (custom-subagents hosts):** run `render-agents.py --check`; if the
  delegate agents are missing or stale (module updated / profiles edited), auto-reprovision and
  note it in the preflight echo + final report. Not a human stop. See `delegation-runtime.md` →
  "Resolving host & mode".
- **Project-context probe (orchestrator):** match the discovery the `bmad-generate-project-context`
  skill itself does — primary location is `<output_folder>/project-context.md` (where the skill
  writes; `<output_folder>` comes from `_bmad/bmm/config.yaml`), fallback is any
  `project-context.md` anywhere under `<project_root>` except build/VCS noise. Probe:
  ```
  test -f <output_folder>/project-context.md || \
    find <project_root> -name 'project-context.md' -not -path '*/node_modules/*' \
      -not -path '*/.venv/*' -not -path '*/.git/*' -type f -print -quit | grep -q .
  ```
  (`find` is the external binary — shell-agnostic per `CLAUDE.md` → "Shell globs".) Both checks
  empty → set `needs_project_context_bootstrap: true` in state; Phase 2 will bootstrap it before
  create-story. Either non-empty → set the flag `false` (the existing file is good enough; Phase 8
  still refreshes it on the last story of the epic). This covers both greenfield first-story and
  brownfield mid-project adoption (a codebase that never ran `bmad-generate-project-context`).
- **Triage (only if `tea.enabled`; delegated to `tea_triage`)**: classify the story `low | med | high` and choose the
  per-story TEA set using `tea-policy.md`. Record `tea_risk` (`low|med|high`) and `tea_selected`
  (e.g. `[atdd, automate]`, or `[]` for trivial) in state. Also record `epic_story_count` and
  `stories_after_in_epic` (both from the sprint-status read that set `is_first/last_in_epic`) and, when
  `tea-policy.md` §3's conditions all hold (high risk, **not within the epic's last
  `skip_last_stories`** — i.e. `stories_after_in_epic >= skip_last_stories`, default 3 — and a
  long-enough epic), add `trace-advisory` to `tea_selected` — Phase 7's tail runs it.
- No commit (nothing changed yet). Persist decisions to state.

## Phase 1 — Branch  *(orchestrator)*
- Ensure we are NOT on the base branch. Create/checkout `{branch_prefix}{e}-{s}-{slug}`
  (default `story/{e}-{s}-{slug}`). If the branch already exists (resume), check it out.
- Write the initial state file with `python3 {skill-root}/scripts/state_update.py init
  --state-file <state> --json -` (it stamps `started_at` once and initializes
  `completed_at: null`, `active_seconds: 0`; it refuses — exit 1 — if the file already exists, so
  a **resume** can never re-init and `started_at`/`active_seconds` span all sessions). Commit it:
  `chore(story-{e}-{s}): start auto-bmad pipeline`.

## Phase 2 — Epic-start setup  *(conditional; two independently-gated sub-steps)*
Two sub-steps that each carry their own gate; either, both, or neither may run. **Phase 2 enters
`completed_phases` only after BOTH gates have resolved** (each sub-step ran, or its gate was
false) — never in sub-step 1's folded state write, so a crash between the sub-steps re-enters
Phase 2 on resume (sub-step 1 won't double-run: its flag already flipped `false`). If both gates
were false, Phase 2 is a no-op, recorded as skipped. Sub-steps execute in this order:

1. **Project-context bootstrap** *(only if `needs_project_context_bootstrap` from Phase 0)* →
   `project_context`
   - Delegate the **`generate-project-context`** entry. Pass `bootstrap_mode: true` so the prompt
     instructs the delegate to write `project-context.md` from scratch (architecture / patterns /
     stack scan of the existing codebase) rather than refresh an existing file.
   - Commit: `docs(project-context): bootstrap`.
   - Flip `needs_project_context_bootstrap` to `false` in state so re-invocations don't double-run.
   - Gate is independent of `is_first_in_epic` / `tea.enabled` — a repo that adopts auto-bmad
     mid-epic gets context built once, on the first story it runs.
2. **Epic test design** *(only if `is_first_in_epic` AND `tea.enabled`)* → `tea_epic`
   - Delegate the **`testarch-test-design`** entry (epic level) for epic `{e}`.
   - Commit: `test(epic-{e}): epic-level test design`.
   - (If `tea.enabled` is false, skip. Non-TEA epic-start work is already handled by
     sprint-planning having been run; nothing else is needed here.)

## Phase 3 — Create story  → `create_story`
- Delegate the **`create-story`** entry for story {e}-{s}. The skill self-validates against its
  checklist and auto-fixes; do NOT add a separate validate pass.
- The delegation is fed this epic's retro-notes + the deferred-work ledger; for the **first story
  of an epic** (no epic-{e} notes yet) it is instead fed the prior epic's retrospective forward
  sections, so epic-transition prep crosses the boundary (see `delegation.md` → `create-story`).
  Durable conventions arrive separately via `project-context.md` (persistent_facts; refreshed in
  Phase 8).
- Capture any open questions the skill saved → retro notes + report.
- Commit: `docs(story-{e}-{s}): create story context file`.

## Phase 4 — Pre-dev TEA  *(only if `tea.enabled` AND `atdd ∈ tea_selected`)*  → `tea_per_story`
- Delegate the **`testarch-atdd`** entry with `<story_file>`.
- Commit: `test(story-{e}-{s}): ATDD acceptance scaffolds (red)`.

## Phase 5 — Dev story  → `dev_story`
- Delegate the **`dev-story`** entry with `<story_file>`. Fully autonomous; it runs tests and
  moves the story to `review`.
- Capture deviations / deferred work / decisions → retro notes (these feed the commit body); if the
  agent reports a **breaking change**, capture it → the `feat` commit's `BREAKING CHANGE:` footer
  (see `git-and-pr.md` → Commits).
- Commit: `feat(story-{e}-{s}): <one-line summary from the agent>`.
  (If the dev agent reports it cannot complete — missing secret, external service, manual
  step — that is `needs-human`: stop and report.)

## Phase 6 — Post-dev TEA  *(only if `tea.enabled` AND `automate ∈ tea_selected`)*  → `tea_per_story`
- Delegate the **`testarch-automate`** entry with `<story_file>`.
- Commit: `test(story-{e}-{s}): expand automated coverage`.

## Phase 7 — Code-review loop  (1–`code_review.max_iterations` reviews, default 2; ≥ 2 unless the first pass is perfectly clean)
The loop runs **at least two review passes — unless the first pass is perfectly clean** (found **0
non-deferred findings**), in which case it exits after that single pass. (The lone exception is the
degenerate `max_iterations: 1` config, where even a non-clean first pass can't get its second
opinion — it exits as an unverified draft; see the cap edge in step 3.) Any first pass with **≥ 1**
non-deferred finding still pulls a mandatory second opinion (the alternate model, when
`code_review.alternate_models` is on) — then the loop exits as soon as a pass converges or the cap is
hit, and **ends at a human-in-the-loop halt** (step 4) — unless step 4's skip gate applies
(`code_review.skip_hitl_on_clean_convergence` on and the loop converged cleanly). A pass **converges** when it
found-and-fixed **≤ 3 non-deferred findings AND none
were Critical or High**; it does **not** converge when it found **> 3 non-deferred findings OR ≥ 1
non-deferred Critical/High**. Track `code_review_iterations` and `code_review_loop_done` in state
(resume continues mid-loop, or re-opens the halt once the loop is done).

For iteration `i` (1-based):
1. **Reviewer profile** — **always start with the primary reviewer.** When
   `code_review.alternate_models` is true: odd `i` → `code_review_review` (primary), even `i` →
   `code_review_review_secondary` — so iter 1 = primary, iter 2 = secondary (and, if the cap is
   raised, iter 3 = primary again, alternating by parity).
   When alternation is off, every iteration is `code_review_review`. **This iteration's reviewer
   profile drives all four code-review delegates below.**

   **Run the code-review fan-out (four delegates, not one skill call).** `/bmad-code-review` internally
   spawns three review subagents — impossible from inside a delegate (no nested subagents) — so the
   orchestrator hoists the fan-out (`delegation.md` → `code-review (fan-out)`; `CLAUDE.md` →
   orchestrator-owned actions). It passes the diff and findings **by path, never by content**, so it
   inspects no code:
   a. **Build the diff (orchestrator, git).** Write the branch diff (`git.base_branch...HEAD` with the
      `:(exclude)` pathspecs in `delegation.md`) to `<diff_file>` inside a throwaway `mktemp -d`
      `<review_tmp>` (outside the work tree, never committed). If `<diff_file>` is empty there is
      nothing to review — delete `<review_tmp>` and treat it as a 0-finding pass through step 3
      (the iteration-exit logic applies; with no failed lenses it is a genuine clean pass).
   b. **Fan out the three lenses** at this iteration's reviewer profile, each writing to its own temp
      file: the **`code-review-blind`**, **`code-review-edge`**, and **`code-review-auditor`** entries.
      On **Claude Code** spawn them **in parallel**; on **Codex** and **opencode** run them
      **sequentially** (Codex's no-fan-out rule — `delegation-runtime.md`; on opencode parallel
      delegate fan-out is unverified, so stay conservative). Collect each lens's reported path +
      count; note any empty/failed layer.
   c. **Triage + persist** via the **`code-review-triage`** entry (same profile), handed the three lens
      paths + `<diff_file>` + `<story_file>` + the failed-layer list. It dedupes, classifies, and writes
      the `### Review Findings` section (`[Review][Patch]` / `[Review][Decision]` / `[Review][Defer]`)
      plus the deferral ledger, then returns the verdict + counts. It is the **only** code-review
      delegate that writes findings.

   **Verify persistence (reconciliation gate) — before trusting the result.** The triage delegate is
   the one that persists; never take its chat counts on faith (a mis-bound write leaves the section
   empty while chat claims findings). After it returns, run
   `python3 {skill-root}/scripts/review_findings.py --story-file <story_file> --expect-min {N}
   --deferred-work-file <impl>/deferred-work.md --story-key {key}` where `{N}` is the reviewer's
   reported `Findings persisted:` count (fall back to its total raised-findings count if that line
   is missing). The same gate confirms the `### Review Findings` section persisted AND that every
   `[Review][Defer]` finding reached the durable ledger (`deferred_work_logged >=` the story's
   defer count). `reconciled: true` (exit 0) → proceed, and use **the file's** counts AND
   severities (`open_patch` / `open_decision` / `open_nondeferred` / `open_crit_high` /
   `open_severity`), not the chat report, to drive steps 2–3 — treat any `open_severity.untagged`
   finding as Critical/High (conservative; the triage prompt mandates a severity tag on every
   bullet). Once the gate passes, delete `<review_tmp>` (`rm -rf`) — the lens outputs are spent; on
   a `needs-human` exit keep it and surface its path for debugging.
   `reconciled: false` (exit 1 — section absent, fewer bullets than claimed, or defer findings not
   logged to the ledger) → the findings did NOT persist: **re-run the `code-review-triage` entry once
   more this iteration** — the lens findings are still on disk, so do NOT re-run the lenses — with the
   spec binding and deferral-ledger reinforced (this retry does not consume a loop iteration). If it
   still won't persist, **stop and report `needs-human`**
   ("code-review did not persist findings to `<story_file>`") rather than running the fix loop
   against an empty section.
2. **Resolve `[Review][Decision]` items first — ASK the user.** These are the calls the reviewer
   flagged as needing a human (the fix is ambiguous), so never auto-guess them. If this pass wrote
   any open `[Review][Decision]` items, batch them into `AskUserQuestion` **before** the fix: at
   most 4 findings per call (the tool's limit) — loop with more calls if there are >4. Present each
   finding's title, detail, and the reviewer's suggested options; the user picks the fix direction
   (or **defer** / **dismiss**). Record each resolution in state (`open_questions`/`deferred_work`)
   + the report. The chosen directions flow into the fix in step 3 (defer → leave it
   `[Review][Defer]` and log to `deferred_work`; dismiss → check it off as won't-fix). For each
   item the user **defers**, also append it (with their one-line reason) to the durable cross-story
   ledger `<impl>/deferred-work.md` under this story's `## Deferred from: code review of {key}
   (<date>)` heading — the same file the `code-review-triage` delegate logs its own `[Review][Defer]`
   findings to. This is a direct orchestrator write, like the report and retro-notes: it owns the
   user-deferred decisions because it (not the delegate) resolved them.
3. **Fix, then classify the pass.** Read the verdict (Approve / Changes Requested / Blocked) from
   the triage report; the Critical/High/Med/Low counts come from **the file** (step 1's
   `open_severity` / `open_crit_high`), never the chat counts. When there is fixable work — `[Review][Patch]` items, or
   `[Review][Decision]` items the user just resolved to fix — delegate the fix via the
   **`code-review fix`** entry (profile `code_review_fix`), focused on those items, implementing each
   resolved decision in its chosen direction and checking it off, then commit
   `fix(story-{e}-{s}): address code review (iter {i})`. A pass with **no fixable findings** instead
   commits the checkpoint `chore(story-{e}-{s}): code review passed (iter {i})`.

   Now classify the pass by its **non-deferred findings** — every finding it raised that was NOT
   routed to `[Review][Defer]` (the `[Review][Patch]` items plus the `[Review][Decision]` items the
   user chose to fix; use **the file's** reconciled counts and severities from step 1, not the chat
   report). The pass **converged** iff it found-and-fixed **≤ 3 non-deferred findings AND none were
   Critical or High** — file-derived: `open_crit_high == 0` AND `open_severity.untagged == 0` at
   gate time (a *deferred* Critical/High is a logged human decision and does not block convergence).

   **Incomplete-review guard (failed lenses) — apply before the loop-drive below.** Fold in the
   fan-out's failed-layer list (step 1b): if **all three lenses failed or returned empty**, the review
   did not actually happen — **stop and report `needs-human`** ("code review incomplete — 0/3 lenses
   produced findings"); never let that count as clean. If **some but not all** lenses failed, a
   0-non-deferred-finding result is **not** trustworthy as "perfectly clean": it does **not** qualify
   for the `i == 1` early-exit below — force at least a second pass (or, when `max_iterations == 1`,
   exit the single pass as a draft via the `i == 1, i == max_iterations` bullet below — a missing lens
   is "not perfectly clean"), and carry an "incomplete review (only N/3 lenses ran)" caveat into the
   report and the Phase 7 HITL-halt summary. If a pass with a
   lens still missing is the loop's final one (it converges or hits the cap), also set
   `convergence_unverified: true` so Phase 9 ships a **draft** — an incomplete review is the same
   flavor of unverified-ness as a cap-unconverged exit (`git-and-pr.md` draft predicate).

   Drive the loop:
   - **`i == 1`, all three lenses ran, and the pass found 0 non-deferred findings** → **exit the loop**
     (perfectly clean — the second opinion is skipped; this is the only first-pass early exit). The
     pass trivially converged, so `convergence_unverified` stays false.
   - **`i == 1`, not perfectly clean (≥ 1 non-deferred finding, OR a lens failed/returned empty),
     `i < max_iterations`** → **continue to iteration 2**, whatever else it found. The second review
     is mandatory the moment the first pass surfaces anything actionable (even a single ≤ 3-finding
     pass that would otherwise converge).
   - **`i == 1`, not perfectly clean, `i == max_iterations`** (only reachable when
     `max_iterations == 1`) → **exit the loop**: the mandatory second opinion can't run, so this
     single pass is unverified — set `convergence_unverified: true` (Phase 9 opens the PR as a draft,
     exactly like the cap-unconverged `i ≥ 2` exit in the next bullet). This is what the state schema
     means by `convergence_unverified` — `max_iterations` hit with the last pass not converged
     (`state-and-resume.md`) — so a findings-bearing single pass must never ship non-draft.
   - **`i ≥ 2` and the pass converged** → exit the loop.
   - **`i ≥ 2`, not converged, `i < max_iterations`** → continue to iteration `i+1`.
   - **`i ≥ 2`, not converged, `i == max_iterations`** → exit the loop **unconverged**: set
     `convergence_unverified: true` (Phase 9 then opens the PR as a draft — `git-and-pr.md` draft
     predicate clause 2).
   On any exit, set `code_review_loop_done: true`, then go to step 4.
   (Edge: if `code_review.max_iterations` is `1` the second review can't run — the loop takes its
   single pass and exits (per the `i == 1, i == max_iterations` bullet above): a **perfectly clean**
   single pass ships non-draft, while **any non-clean** single pass exits with
   `convergence_unverified: true` (a draft PR), since its mandatory second opinion never ran. Note the
   single-pass run in the report. At the default cap of 2 the loop runs 1–2 passes — 1 when the first
   pass is perfectly clean, otherwise 2.)
4. **HITL halt — ASK the user on every loop exit (unless configured to skip a clean convergence).**
   **Skip gate — evaluate first, at step entry, on the loop-exit `convergence_unverified` value**
   (the post-halt re-review below also writes this flag, so read it *before* that machinery runs): if
   `code_review.skip_hitl_on_clean_convergence` is `true` **AND** `convergence_unverified` is `false`
   (the loop converged cleanly — a perfectly-clean single pass or an `i ≥ 2` converged exit), **skip
   the halt**: do **not** open `AskUserQuestion`. `log` one line ("review converged cleanly — Phase 7
   HITL halt skipped per config"), record `hitl_halt: skipped (clean convergence)` in state + the
   report's Code-review line, and proceed as the **Continue** path **with no external-change check**
   (there was no human pause, so there are no external changes to detect) — straight to the Phase 7
   tail. This deliberately forgoes the external-review recommendation, a last sighting of any
   *deferred* Critical/High, and the Stop option — the user opted into no-pause for cleanly-converged
   stories. The gate **never** fires when `convergence_unverified` is `true` (capped-unconverged,
   incomplete-lens, or a non-clean `max_iterations: 1` single pass — those always halt). Default
   (`false`) → always halt, as below.

   Otherwise (option off, or the loop did not converge cleanly) the loop *always* ends here (converged
   or capped); this single human checkpoint replaces the old cap-only prompt. Summarize: iterations
   run, each pass's verdict + `Critical N / High N / Medium N / Low N` counts, the total non-deferred
   findings found-and-fixed, and whether the loop converged or hit the cap unconverged
   (`convergence_unverified`). **Recommend an external review while the pipeline is paused** — a
   human, another model/AI, or a separate tool, reviewing the branch's changes — because even a
   converged exit's final fix pass is itself unverified. Then ask (`AskUserQuestion`):
   - **Continue** *(recommended)* — resume the pipeline. **First check (git only — the orchestrator
     never reads the code) for new changes since the halt**: new commits and/or a dirty working tree
     from the external review. **If nothing changed, just continue.** If there are changes, commit
     them `fix(story-{e}-{s}): external review changes`, then **delegate a fresh whole-story
     re-review** — this **replaces** the old "orchestrator reads the diff itself and summarizes it"
     carve-out; the orchestrator no longer inspects code at any tier:
     - **Re-review (delegated, not an inline read).** Run the **code-review fan-out** (`delegation.md`
       → `code-review (fan-out)`) at the `code_review_review_secondary` profile — the alternate model,
       an independent second pair of eyes on the human's changes (deliberately the secondary profile
       even when `code_review.alternate_models` is off: independence is the point here, not rotation)
       — exactly like a loop pass (build the
       diff, the three lenses, then `code-review-triage`). Apply the **same reconciliation gate** as
       step 1 (`review_findings.py`; one `code-review-triage` re-run on non-persist, else
       `needs-human`). Increment `external_review_iterations`.
     - **Gate on the FILE, not the chat.** Read the `### Review Findings` counts via
       `review_findings.py` (never the reviewer's chat report). The changes are **meaningful** iff
       this review's non-deferred findings are **> 3 OR include ≥ 1 Critical/High** — file-derived:
       `open_nondeferred > 3 OR open_crit_high ≥ 1 OR open_severity.untagged ≥ 1` (the loop's
       non-convergence rule, step 3). **Not meaningful** (≤ 3 non-deferred, none Critical/High) →
       commit the checkpoint `chore(story-{e}-{s}): re-review external changes` and continue, no
       re-halt.
     - **Meaningful → re-open this same halt.** Commit the persisted findings
       `chore(story-{e}-{s}): re-review external changes`, then **ask again** (`AskUserQuestion`),
       summarizing the new findings (verdict + `Critical N / High N / Medium N / Low N` + the
       non-deferred count). For any fixing option, resolve open `[Review][Decision]` items first
       (step 2). Offer:
       - **Fix & re-review** *(recommended)* — delegate the **`code-review fix`** entry (profile
         `code_review_fix`) on the new findings, commit `fix(story-{e}-{s}): address external-change
         review`, then **loop back to Re-review** so the fix is itself verified and the user lands at
         the halt again. Cap the rounds at `code_review.max_iterations`; on the cap, drop this option
         and re-ask with the rest, setting `convergence_unverified: true`.
       - **Fix only** — delegate the same fix and commit, then continue without re-reviewing (the fix
         stays unverified, like a converged exit's final fix pass).
       - **Ignore & continue** — proceed with the findings unaddressed: they stay open in
         `<story_file>`, surface in the report + PR `Needs attention` checklist, and set
         `convergence_unverified: true` so Phase 9 ships a **draft** (a human waiver of real findings,
         mirroring the Phase 8 gate waiver).
       - **Stop now** — as the **Stop the pipeline now** option below; report the open findings as
         `needs-human`.
   - **Stop the pipeline now** — skip the remaining phases, go straight to the report (Step 3);
     commits stay on the branch, nothing is pushed and no PR is opened. If the loop exited
     unconverged, report its last pass's findings as `needs-human`.
   Record the choice, the external-change re-review outcome (if it ran — `external_review_iterations`,
   each round's verdict + counts, and the user's fix/ignore decision), and any extra commits in state +
   the report. **Bracket every prompt here with `state_update.py timing-pause`/`timing-start`** — the
   original ask and any re-opened halt
   — so the (possibly long) external-review waits land on human/idle, not `active_seconds` (see top of
   this file). Phase 7 enters `completed_phases` only after this halt resolves — or after the skip
   gate above fires (a skipped halt counts as resolved) — and the tail below, when selected.

### Phase 7 tail — per-story trace advisory  *(conditional; non-blocking)*  → `tea_per_story`
Runs **once on the Continue path, after the review loop and its HITL halt resolve** (a halt skipped
by the step-4 skip gate also reaches this path), only if
`trace-advisory ∈ tea_selected` (set in Phase 0
— high risk, not within the epic's last `skip_last_stories` stories, and the epic is long enough;
see `tea-policy.md` → §3). Resume-safe:
skip if `story_trace` is already non-null in state. Phase 7 lands in `completed_phases` only after
this step (when selected) finishes, so a resume that re-enters a converged Phase 7 with
`story_trace == null` runs just this step.
- Delegate the **`testarch-trace (story advisory)`** entry with `<story_file>` (story scope).
- It mirrors the epic-end trace's *output* but never its *control flow*: **no `AskUserQuestion`, no
  remediation loop, no draft-PR forcing, no halt.** Whatever the verdict, the pipeline continues —
  this is visibility, not a gate.
- Record `story_trace: {verdict, uncovered: [...], ran: true}` in state. Surface any uncovered ACs
  in the report's **TEA** line, the PR-body checklist (so the human sees the gap at review time),
  and the epic retro notes (so the epic-end trace gate + retrospective inherit the signal). A
  non-PASS verdict does **not** set `convergence_unverified` and does **not** add a `blockers[]`
  entry.
- Commit `test(story-{e}-{s}): trace coverage advisory` (the trace matrix artifact if the skill
  wrote one, plus the state update).

## Phase 8 — Epic end  *(only if `is_last_in_epic`)*
Run these in order. Each sub-step records its `phase8_steps.<key>` marker (`trace_gate`, `nfr`,
`test_review`, `project_context`, `archive`, `retro`) in its folded state write — `done` when it
ran (trace_gate also `waived`/`failed`), and `done` too when its gate was false (e.g. TEA off) so
a skip reads as resolved. On resume, enter Phase 8 at the **first null marker** instead of
re-running completed delegations; Phase 8 joins `completed_phases` only once all six markers are
resolved. Commit the epic-end docs once at the end: `docs(epic-{e}): gate, project context,
deferred-work archive, retrospective`. (Trace-gate remediation, if any, commits separately as it
runs — step 1.)
1. **TEA gates (only if `tea.enabled`; epic-level skills are always on here):** delegate, in order,
   the **`testarch-trace`** entry via `tea_epic` (the blocking gate — full depth), then the
   **`testarch-nfr`** and **`testarch-test-review`** entries via `tea_epic_audit` (advisory audits —
   one effort tier below the blocking gate). Capture each verdict; record the gate decision in state
   (`gate_decision`) + report. Handle the **trace** verdict before running nfr/test-review:
   - `PASS` → continue.
   - `WAIVED` (emitted by the skill itself) → continue; it ships as a **draft** PR in Phase 9
     (already a documented human waiver — see `git-and-pr.md`).
   - `CONCERNS` → advisory; continue silently, but record it and surface it in the report + PR body.
     It does **not** halt or force a draft.
   - `FAIL` → **ASK the user** (AskUserQuestion; mirrors the Phase 7 HITL halt — this is not a
     silent hard-stop). Summarize the uncovered requirements/ACs the trace flagged, then offer:
     - **Remediate & re-gate** *(recommended; offered only while `gate_iterations <
       tea.gate_max_iterations`, default 2)* — delegate the **`testarch-automate`** entry at **epic
       scope** via `tea_epic` to close the flagged coverage gaps, commit `test(epic-{e}): close trace
       coverage gaps (gate iter {i})`, increment `gate_iterations`, then re-run the
       **`testarch-trace`** entry and re-apply this same handling to the new verdict. (If the gaps are
       scope/spec drift rather than missing tests, the right heavier step is `/bmad-correct-course`
       — tell the user; do **not** auto-run it, as it changes story scope.)
     - **Waive & continue** — set `gate_decision: WAIVED`, record the user's rationale + the
       uncovered items in `deferred_work`/`open_questions`, then continue. Phase 9 opens the PR as a
       **draft** with the waiver + gaps in the body.
     - **Stop now** — skip the remaining phases, go straight to the report (Step 3); commits stay on
       the branch, nothing is pushed and no PR is opened. Keep `gate_decision: FAIL`, add a
       `blockers[]` entry (e.g. `epic {e} trace gate FAILED — {n} requirements lack test coverage`),
       and report the gaps as `needs-human`.
     Once `gate_iterations` reaches the cap and trace is still `FAIL`, drop the Remediate option and
     re-ask with only Waive / Stop. Run nfr + test-review on every path except **Stop**.
2. **Project context:** delegate the **`generate-project-context`** entry via the `project_context`
   profile. The Phase 8 refresh is fed the epic's accumulated retro notes (+ durable items from the
   deferred-work ledger) so its durable conventions/agreements distill into `project-context.md` —
   the file every later story's create-story auto-loads as `persistent_facts` (`bmad-create-story`
   `customize.toml`), and thus the channel that carries epic-N conventions into epic N+1's stories.
   See `delegation.md` → `generate-project-context`. (A blind codebase-scan refresh drops
   rules/agreements not inferable from code; the retro notes exist by this step, the synthesized
   retro doc does not yet — step 4 — so notes, not the doc, are the source here.)
3. **Archive resolved deferred work** *(orchestrator-direct — no `/bmad-*` skill prunes the ledger;
   the orchestrator already writes this file at Phase 7, so this is connective bookkeeping, not a
   delegated step. See `CLAUDE.md` → orchestrator-owned actions):* now that `project-context.md` has
   distilled the epic's durable conventions, trim the active ledger `<impl>/deferred-work.md` so
   create-story stops re-folding finished work into future stories. Read it; for every **bullet that
   clearly states ALL of its deferred work is done** — keyed on a resolution *marker's meaning*, not
   a fixed string (the phrasing varies run to run: a leading `✅`, `RESOLVED`, "resolved in
   story …", "closed", "addressed in …") — **move** that bullet out of the active ledger and append
   it, under a matching `## Deferred from: <source>` heading, to the sibling archive
   `<impl>/deferred-work-resolved.md` (create it with a one-line title if absent; reuse the heading
   there if it already exists, else add it). Then drop any active-ledger `## Deferred from:` heading
   whose last bullet was moved; preserve the ledger's title/intro. **Keep — never move:**
   - any entry with an open remainder — a *partial* resolution ("X portion done; Y owned by story Z"
     still carries open work). The entry must vouch for **itself**; do not move it just because some
     *other* entry says the remainder landed.
   - any unmarked entry (a still-open deferral).
   **When uncertain, keep it in the active ledger.** The asymmetry is the safety rule: a wrongly-kept
   resolved item is merely wasteful (create-story folds a done item once), but a wrongly-moved open
   item silently drops real follow-up work. No-op if the ledger is absent or holds no resolved entry.
   Record the count moved in state (`deferred_work_archived`) and the report's **Deferred work**
   field; the move lands in this phase's `docs(epic-{e})` commit.
4. **Retrospective:** delegate the **`retrospective`** entry via the `retrospective` profile, handing
   it the accumulated `_bmad-output/auto-bmad/retro-notes/epic-{e}.md` as primary input. It runs autonomously and
   writes the retro doc + flips the retrospective status to `done`. **Planning-drift advisory:** if the
   delegate's `Planning drift` line is non-empty — the epic proved a planning assumption wrong (PRD /
   architecture / epic scope that no longer matches what was built) — record it in state
   (`planning_drift`) and surface it in the report's **Planning drift** field. It is **non-blocking**
   and **never auto-acted**: recommend the upstream re-sync — refresh the codebase docs
   (`/bmad-document-project` only if `docs/` is stale, then `/bmad-generate-project-context`), then
   `/bmad-prd` (update intent) to reconcile the PRD in place; for **structural** drift,
   `/bmad-correct-course` instead. Like the Phase 7 / trace-gate correct-course pointer, name the step
   for the user but do **not** run it — it changes planning scope and is the user's call. `none` ⇒ omit.

## Phase 9 — Finalize  *(orchestrator)*
- Ensure everything is committed (no dirty tree).
- **Write the report file (before push, so it ships in the PR).** Emit it with
  `python3 {skill-root}/scripts/state_update.py report-section --report-file
  _bmad-output/auto-bmad/reports/{key}.md --state-file <state> --json -` — the script appends a new
  `## Report — <ISO timestamp>` section (creating the file if absent, never touching earlier
  sections) and derives the Story/Branch/Timing lines from state; you supply the prose snippets
  (`disposition_tag`, `pipeline_status`, `continues`, `phases_run`, `skipped`, `overrides`, `tea`,
  `code_review`, lists, `next`, `head_sha`) in the JSON. Tag it with this section's disposition —
  `(final)` on a clean completion, `(final — caveated)` if the run finalized but stays at `review`
  — and keep the section a session delta (on a resume, `phases_run` lists only the resumed phases
  and `continues` names the section it picks up from; full vocabulary in `state-and-resume.md` →
  "reports/{key}.md"). The file holds only the **story-level** outputs that aren't
  recorded elsewhere — overrides, TEA outcomes, open questions, deferred work, blockers,
  next-story preview (see `SKILL.md` Step 3 for the exact fields). The finalization **artifacts**
  — PR URL, CI run link, merge method + branch-deleted state, and the BMAD-status-flip outcome —
  are deliberately **chat-only** (Step 3 prints them; rationale in `state-and-resume.md` →
  "reports/{key}.md"). The one-line **disposition** DOES belong in the file's `Pipeline status`
  line — clean / caveated / halted at Phase N, and a draft's summary reason (CI red / waived gate /
  blocker); it's a summary, not a retrievable artifact, so it is **not** chat-only. Commit it:
  `docs(story-{e}-{s}): pipeline report`. (Orchestrator-owned, never delegated —
  `git-and-pr.md` → "Ownership".)
- **git mode `remote`:** push the branch, open the PR, evaluate CI, and convert to draft if
  warranted — all per `git-and-pr.md` ("PR" + "CI link & wait" + draft predicate clauses 1–4).
  Capture `pr_url`, `ci_run_url`, and `ci_status`. PR body = conventional summary + link to the
  story file + a checklist of open questions / deferred work / human-action items. (The committed
  report file is now part of the PR diff.)
- **git mode `local`** (or the user chose "stop without a PR" in Phase 7): skip the push/PR; leave
  the branch in place (with the report commit on it) and note it in the chat report. The CI wait
  and merge prompt below don't apply.
- Mark the auto-bmad state file `done` — stamp `completed_at` (`date -u +%Y-%m-%dT%H:%M:%SZ`) and
  record `pr_url`, `ci_run_url`, `ci_status`, final `branch`, any `blockers`. **Don't commit this
  on its own** — it folds into the single finalize commit below (alongside the BMAD-status flip),
  so the post-push bookkeeping is **one** commit, never a `mark done` + `record PR metadata` +
  `record CI status` chain.
- **Advance the BMAD-level status on a clean completion only.** A **clean completion** = the full
  negation of the draft predicate (see `git-and-pr.md` → "PR"); a **caveated completion** = any
  predicate clause fires (draft PR, recorded blocker, waived gate, CI failed/timed-out). On a
  clean completion, flip the story to `done` in the two BMAD-level sources so the next run
  advances past it:
  - the **story file `Status:`** field (the same one `dev-story` set to `review`) → `done`;
  - the **`<impl>/sprint-status.yaml`** entry for `{key}` → `done` (the flat `development_status:`
    map `story_plan.py` reads; change only that one line's value and preserve the rest of the file).
  On a caveated completion, **leave both BMAD-level sources at `review`** so the story keeps
  re-surfacing until a human acts (a re-run then finds the auto-bmad state already `done` and
  reports it complete rather than redoing it — see `state-and-resume.md`). This flip is
  orchestrator-owned finalize bookkeeping, **not** a delegated step (`git-and-pr.md` → "Ownership").
  **Commit the state→`done` write and these two BMAD-status flips together as the single
  `chore(story-{e}-{s}): finalize (mark done + BMAD status)` commit**, then push it so it lands on
  the branch/PR. On a **caveated** completion (no BMAD flip), the lone state→`done` write is still
  that one finalize commit. The later merge-prompt outcome (`pr_merged` / `merge_method` /
  `branch_deleted`) is written to state but gets **no commit of its own** — the run is already
  `done` (resume skips it) and the chat report owns merge details (`git-and-pr.md` → "Merging the PR").
- **Merge prompt** (only on a clean completion with `git.offer_merge: true`, mode `remote`, a PR
  was opened, no `skip merge-prompt` override): ask the user how to merge and execute their choice
  per `git-and-pr.md` → "Merging the PR". Records `pr_merged` / `merge_method` / `branch_deleted`
  in state. This is the third interactive moment in normal operation (after first-run setup and
  the Phase 7 cap; the Phase 8 trace-FAIL ask is also interactive).
- Hand control back to the SKILL's Step 3, which **prints the final chat report** (the committed
  file portion plus PR / CI / merge / final-status details).
