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
state-only commit). When updating state, also record timing: read the host's `date +%s`
just before delegating the phase and again when it returns (just before the state write + commit),
and add the delta to `active_seconds`
(alongside the `updated_at` stamp) — this is what lets the report split AI-run time from
human/idle wait (`state-and-resume.md` → timing fields). **Don't count time spent waiting on the
user:** if the phase opens an `AskUserQuestion` (e.g. the Phase 7 decision asks or the cap prompt),
bracket the prompt with `date +%s` and exclude that interval from the phase's delta, so the wait
lands on human/idle, not active.

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
  first run and is never re-touched by a module update, so a newer asset's `profiles`/`phase_profiles`
  keys (e.g. a `tea_triage` phase mapping added in a later version) silently never reach the project —
  and `render-agents.py --check` below can't see this, because it only diffs the four rendered agent
  files and never reads `phase_profiles`. Reconcile deterministically:
  ```
  python3 {skill-root}/scripts/config_plan.py --check --config <output_folder>/auto-bmad/config.yaml
  ```
  (the shipped `assets/agents/profiles.yaml` + `assets/module.yaml` resolve relative to the script).
  On `status: drift` (exit 1 — asset `profiles`/`phase_profiles` keys the config lacks, and/or
  `profiles_source_version` older than the installed `module_version`), **auto-apply** the additive
  heal — re-run with `--apply` — which appends only the MISSING keys (never overwriting a user
  retune) and restamps `profiles_source_version`. Note it in the preflight echo + final report. Not
  a human stop. Run this **before** the provisioning-freshness check below, so a re-seeded profile
  *value* is then caught there as a stale agent file (a re-seeded `phase_profiles` key needs no
  re-render — it maps to an existing profile). `manual_review` items (a sub-key missing from a
  profile that already exists — rare, value-bearing) are **surfaced in the report**, not auto-written.
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
  (e.g. `[atdd, automate]`, or `[]` for trivial) in state. Also record `epic_story_count` (stories
  under epic `{e}`, from the sprint-status read that set `is_first/last_in_epic`) and, when
  `tea-policy.md` §3's conditions all hold (high risk, not last-in-epic, long-enough epic), add
  `trace-advisory` to `tea_selected` — Phase 7's tail runs it.
- No commit (nothing changed yet). Persist decisions to state.

## Phase 1 — Branch  *(orchestrator)*
- Ensure we are NOT on the base branch. Create/checkout `{branch_prefix}{e}-{s}-{slug}`
  (default `story/{e}-{s}-{slug}`). If the branch already exists (resume), check it out.
- Write the initial state file and commit it:
  `chore(story-{e}-{s}): start auto-bmad pipeline`. Stamp `started_at` (`date -u +%Y-%m-%dT%H:%M:%SZ`)
  and initialize `completed_at: null`, `active_seconds: 0` on this first write. On a **resume** (the
  state file already exists), leave `started_at` and the accumulated `active_seconds` untouched —
  they span all sessions.

## Phase 2 — Epic-start setup  *(conditional; two independently-gated sub-steps)*
Two sub-steps that each carry their own gate; either, both, or neither may run. Mark Phase 2 as
done in `completed_phases` if any sub-step ran (or if both gates were false — Phase 2 is then a
no-op, recorded as skipped). Sub-steps execute in this order:

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
- Capture deviations / deferred work / decisions → retro notes.
- Commit: `feat(story-{e}-{s}): <one-line summary from the agent>`.
  (If the dev agent reports it cannot complete — missing secret, external service, manual
  step — that is `needs-human`: stop and report.)

## Phase 6 — Post-dev TEA  *(only if `tea.enabled` AND `automate ∈ tea_selected`)*  → `tea_per_story`
- Delegate the **`testarch-automate`** entry with `<story_file>`.
- Commit: `test(story-{e}-{s}): expand automated coverage`.

## Phase 7 — Code-review loop  (≤ `code_review.max_iterations`, default 3)
Iterate until the review **Approves** / has no remaining Critical or High findings (and at most
one Medium), or the cap is hit. Track `code_review_iterations` in state (so resume continues mid-loop).

For iteration `i` (1-based):
1. **Reviewer profile** — **always start with the primary reviewer.** When
   `code_review.alternate_models` is true: odd `i` → `code_review_review` (primary), even `i` →
   `code_review_review_secondary` — so iter 1 = primary, iter 2 = secondary, iter 3 = primary.
   When alternation is off, every iteration is `code_review_review`. Delegate the **`code-review`**
   entry to that reviewer profile. The skill writes findings into the story file's
   `### Review Findings` section as `[Review][Patch]` / `[Review][Decision]` / `[Review][Defer]` items.

   **Verify persistence (reconciliation gate) — before trusting the result.** The review skill
   silently runs in `no-spec` mode and persists *nothing* if the story file isn't bound as its
   spec, so never take the reviewer's chat counts on faith. After the delegate returns, run
   `python3 {skill-root}/scripts/review_findings.py --story-file <story_file> --expect-min {N}
   --deferred-work-file <impl>/deferred-work.md --story-key {key}` where `{N}` is the reviewer's
   reported `Findings persisted:` count (fall back to its total raised-findings count if that line
   is missing). The same gate confirms the `### Review Findings` section persisted AND that every
   `[Review][Defer]` finding reached the durable ledger (`deferred_work_logged >=` the story's
   defer count). `reconciled: true` (exit 0) → proceed, and use **the file's** counts (`open_patch`
   / `open_decision`), not the chat report, to drive steps 2–3.
   `reconciled: false` (exit 1 — section absent, fewer bullets than claimed, or defer findings not
   logged to the ledger) → the findings did NOT persist: **re-delegate the `code-review` entry once
   more this iteration** with the spec binding and deferral-ledger reinforced (this retry does not
   consume a loop iteration). If it still won't persist, **stop and report `needs-human`**
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
   (<date>)` heading — the same file the `code-review` delegate logs its own `[Review][Defer]`
   findings to. This is a direct orchestrator write, like the report and retro-notes: it owns the
   user-deferred decisions because it (not the delegate) resolved them.
3. Read the verdict (Approve / Changes Requested / Blocked) and the Critical/High/Med/Low counts.
   When there is fixable work — `[Review][Patch]` items, or `[Review][Decision]` items the user just
   resolved — delegate the fix via the **`code-review fix`** entry (profile `code_review_fix`),
   focused on those items, implementing each resolved decision in its chosen direction and checking
   it off, then commit `fix(story-{e}-{s}): address code review (iter {i})`. What happens next depends on the **severity
   this pass found** (the findings it just fixed, decision items included):
   - **No findings** → commit `chore(story-{e}-{s}): code review passed (iter {i})` and exit.
   - **At most one Med, plus any number of Low (and no Critical or High)** → the fixes are in and
     nothing high-risk surfaced; exit the loop and continue the pipeline (no need to ask).
   - **Any Critical or High, OR two or more Med** → they were fixed, but the fix is unverified and
     such findings can recur (and a cluster of Mediums means the change still isn't settling), so
     re-review: if `i < cap`, continue to iteration `i+1`; if `i == cap`, go to step 4.
4. **Cap reached while the last pass was still tripping the re-review threshold (Critical/High, or
   ≥2 Med) → ASK the user** (AskUserQuestion); do not silently proceed. Each pass fixed its
   findings, but the final pass still tripped the threshold, so convergence is unverified.
   Summarize the findings the last pass fixed, then offer:
   - **Run another review+fix iteration** *(recommended)* — continue beyond the cap with the
     primary reviewer (`code_review_review`) + `code_review_fix`, to verify the fixes and drive the
     findings below the re-review threshold. Repeat this ask after each extra iteration until a pass
     comes back clean or below threshold (no Critical/High and ≤1 Med), or the user stops.
   - **Accept the fixes and continue the pipeline** — trust the fixes already applied; set
     `convergence_unverified: true` in state, then proceed normally to Phase 8 (if last story) and
     Phase 9. Because that flag is set, Phase 9 opens the PR as a **draft** (or, in local mode,
     just notes it).
   - **Stop the pipeline now** — skip the remaining phases, go straight to the report (Step 3);
     commits stay on the branch, nothing is pushed and no PR is opened. The last pass's findings
     are reported as `needs-human`.
   Record the user's choice and any extra iterations in state (`code_review_iterations`).

### Phase 7 tail — per-story trace advisory  *(conditional; non-blocking)*  → `tea_per_story`
Runs **once, after the review loop exits**, only if `trace-advisory ∈ tea_selected` (set in Phase 0
— high risk, not last-in-epic, and the epic is long enough; see `tea-policy.md` → §3). Resume-safe:
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
Run these in order. Commit the epic-end docs once at the end: `docs(epic-{e}): gate, project
context, retrospective`. (Trace-gate remediation, if any, commits separately as it runs — step 1.)
1. **TEA gates (only if `tea.enabled`; epic-level skills are always on here):** delegate via
   `tea_epic`, in order, the **`testarch-trace`**, then **`testarch-nfr`**, then
   **`testarch-test-review`** entries. Capture each verdict; record the gate decision in state
   (`gate_decision`) + report. Handle the **trace** verdict before running nfr/test-review:
   - `PASS` → continue.
   - `WAIVED` (emitted by the skill itself) → continue; it ships as a **draft** PR in Phase 9
     (already a documented human waiver — see `git-and-pr.md`).
   - `CONCERNS` → advisory; continue silently, but record it and surface it in the report + PR body.
     It does **not** halt or force a draft.
   - `FAIL` → **ASK the user** (AskUserQuestion; mirrors the Phase 7 cap prompt — this is not a
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
   retro doc does not yet — step 3 — so notes, not the doc, are the source here.)
3. **Retrospective:** delegate the **`retrospective`** entry via the `retrospective` profile, handing
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
- **Write the report file (before push, so it ships in the PR).** Append a new
  `## Report — <ISO timestamp>` section to `_bmad-output/auto-bmad/reports/{key}.md`,
  preserving any earlier sections. The file holds only the **story-level** outputs that aren't
  recorded elsewhere — overrides, TEA outcomes, open questions, deferred work, blockers,
  next-story preview (see `SKILL.md` Step 3 for the exact fields). PR URL, CI link/status,
  draft reason, merge method, and the BMAD-status-flip outcome are deliberately **chat-only**
  (Step 3 prints them; rationale in `state-and-resume.md` → "reports/{key}.md"). Commit it:
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
