# Epic pipeline (`/auto-bmad epic`)

Epic mode drives a **whole epic** — every actionable story — in one run, then **one PR**. It exists
to recover wall-clock on an epic that is unsustainable story-by-story: it trims the per-story heavy
code-review loop to a **thin single review + fix** (Tier A), batches the heavy adversarial review
into **one epic integration review** (Tier B), and collapses N branches / PRs / CI-waits / merges
into **one**. The deliberate trade — **warned and confirmed up front** — is that there are **no
per-story human checkpoints**; the single human halt is the epic integration review (E_review).

This file is the epic analog of `pipeline.md`. It does **not** restate per-story phase internals —
each E-step names the per-story phase it reuses; read `pipeline.md` for that phase's mechanics. The
orchestrator obeys the same **core principle**: it delegates every BMAD step and **reads no code**;
it owns git + finalize bookkeeping directly (`git-and-pr.md` → "Ownership", now at epic scope). The
delegated prompts are the **exact** `delegation.md` entries (the per-story ones reused verbatim in
the loop, plus the epic code-review variants).

Placeholders are the `delegation.md` glossary (`{e}`/`{s}`, `{key}`, `{slug}`, `<impl>`,
`<story_file>`, `<project_root>`, …). `{state}` = `<output_folder>/auto-bmad/state`; the **epic
anchor** is `{state}/epic/epic-{e}.yaml` (`state-and-resume.md` → "state/epic/epic-{e}.yaml").
`{base}` = `git.base_branch`.

---

## E-steps at a glance

| E-step | Reuses (per-story) | Runs | Owner |
|--------|--------------------|------|-------|
| **E0** Preflight, enumerate & adopt | Phase 0 | once | orchestrator (+ delegated TEA triage is deferred into E5) |
| **E1** Epic branch + anchor | Phase 1 | once | orchestrator (git) |
| **E2** Epic-start | Phase 2 | once (conditional) | delegated |
| **E5** Story loop (sequential) + **Tier A** | Phases 3–7 per story | per story | delegated steps; orchestrator commits/state |
| **E8a** Epic-end gates | Phase 8 (gates) | once (conditional) | delegated; gate ask **suppressed** |
| **E_review** Epic integration review (**Tier B**) | Phase 7 at epic scope | once (conditional) | delegated fan-out; **the single HITL halt** |
| **E8b** Epic-end closing | Phase 8 (closing) | once (conditional) | delegated |
| **E_final** Finalize | Phase 9 | once | orchestrator (git) |

The loop is **sequential** — create-story for the next story is **not** overlapped with the current
story's dev (dev-story is the irreducible core; nothing else is safely overlappable). Each E-step
records its marker in the **epic anchor's** `completed_phases` (the E-steps as integers: E0→0, E1→1,
E2→2, E5→5, E8a→81, E_review→7, E8b→82, E_final→9) in a folded `state_update.py` write, and commits
in the same single commit as its artifacts (`git-and-pr.md` → "Commits"; never a state-only commit).
Bracket every delegated step and every `AskUserQuestion` with `state_update.py timing-start/-pause`
on the **epic anchor** (the per-story loop body also brackets the per-story state file). **Exception
— E0:** the epic anchor does not exist until E1's `init`, so E0 writes no state — every E0 decision
rides into E1's `init --json` payload.

---

## E0 — Preflight, enumerate & adopt  *(orchestrator)*
Runs during the SKILL procedure before any commit. Same probe discipline as Phase 0 (one
`preflight.py` call; never a bare glob).

1. **Preflight (reuse Phase 0 verbatim):** `preflight.py` for git state/mode, project-context,
   CI presence, required skills, and the config-drift heal (`config_plan.py`) + provisioning
   freshness. Obey its `git` block + `hard_stop`. The required-skills list is the same as a per-story
   run (core + TEA if enabled + epic-end skills — this run always reaches the epic end).
2. **Enumerate the epic:** `python3 {skill-root}/scripts/story_plan.py --epic {e}
   --sprint-status <impl>/sprint-status.yaml --impl-dir <impl>`. Parse `epic_stories` (ordered);
   `hard_stop` true (unknown/empty epic, or epic already `done`) ⇒ surface and stop. (SKILL.md owns
   how `{e}` is resolved — `--epic N`, else the epic of the next actionable story.)
3. **Adopt — reconcile each story** (`state-and-resume.md` → "Adopting a partially-started epic"; the
   plan's full rules). **First, on a resume, skip every story already in the epic anchor's
   `stories_landed`** — it was completed by THIS run, so it must NOT be re-entered even though it sits
   at `review` with a complete per-story state file. `stories_landed` (not the `review` status) is the
   authority for "done this run"; the status-based rules below are for stories finished *outside* this
   run. Then, for each remaining enumerated story, decide using its `status` + whether a per-story
   `{state}/{key}.yaml` exists:
   - **`done`** → **skip** (no re-dev, no re-review); assumed already in `{base}`; NOT in the
     batch-flip set.
   - **`review`/`in-progress` WITH a state file** (and NOT in `stories_landed`) → resume that story
     per-story in E5 (the existing `state_plan.py --story-key {key}` path; continue from its first
     incomplete phase).
   - **`review`/`in-progress` WITHOUT a state file** (bare BMAD / external) → apply the existing
     **status-mismatch guard** (`state-and-resume.md`): **ASK** — adopt as-is (leave at `review`,
     surface in the rollup) / run the thin Tier-A review on it in E5 / skip. Never blind-re-dev a
     human's work.
   - **`ready-for-dev`/`backlog`** → run the E5 loop body fresh.
4. **Base-readiness guard (git only — never a code read):** epic mode branches off `{base}` and
   assumes `done` stories are in `{base}`. If any `done` story has a `{branch_prefix}{e}-{s}-*` branch
   that is **not merged into `{base}`** (`git branch --list "{branch_prefix}{e}-{s}-*"` then
   `git merge-base --is-ancestor <branch> {base}`), **ASK**: proceed off base (that story's work won't
   be in this epic's PR — only the remaining stories will) / stop and merge it first, then re-run.
5. **Resolve the epic slug** (git only, deterministic — no LLM read): search the planning epics doc
   for epic `{e}`'s title (e.g. `find <planning_artifacts> -name 'epics*.md'` /
   `-name 'epic-{e}*.md'`, then read the `Epic {e}` heading); kebab-case it. Fallback when absent:
   the first story-key's slug stem, else bare `epic-{e}`. Carry it into E1 as `epic_slug` (stored so
   resume reuses it, never re-derives a different one).
6. **TEA triage is per story** — it is NOT run here (the epic spans many risk levels); E5a delegates
   the `tea_triage` per story. Record E0's decisions (`needs_project_context_bootstrap`,
   `epic_story_count`, the adopt verdicts, `epic_slug`, any `overrides`) for E1's `init --json`.
   No commit, no state write (the anchor doesn't exist yet).

## E1 — Epic branch + anchor  *(orchestrator, git)*
- Ensure we are NOT on `{base}`. Create/checkout the **one** epic branch
  `{git.epic_branch_prefix}{e}-{slug}` (default `epic/{e}-{slug}`) off `{base}`. If it already exists
  (resume), check it out.
- Write the epic anchor: `python3 {skill-root}/scripts/state_update.py init --state-file
  {state}/epic/epic-{e}.yaml --json -` (refuses if it exists, so resume never re-inits — `started_at`
  + timing span all sessions). The payload carries E0's decisions plus `story_key: epic-{e}`,
  `epic_num: {e}`, `branch`, `epic_slug`, `active_story: null`, `stories_landed: []`. Commit:
  `chore(epic-{e}): start auto-bmad epic pipeline`.

## E2 — Epic-start setup  *(conditional; reuses Phase 2)*
Runs **once** at the start of the epic (the epic's first story IS the epic start). Two
independently-gated sub-steps, exactly as Phase 2 — record each, mark E2 done once both resolve:
1. **Project-context bootstrap** *(only if `needs_project_context_bootstrap`)* → delegate
   **`generate-project-context`** (bootstrap fill). Commit `docs(project-context): bootstrap`.
2. **Epic test design** *(only if `tea.enabled`)* → delegate **`testarch-test-design`** (epic level)
   for epic `{e}`. Commit `test(epic-{e}): epic-level test design`.

> **Resume note:** if the epic was partially completed **outside** epic mode (no anchor existed before
> this run), E2 still records its `completed_phases` marker once run, so a later resume cannot re-run
> epic test design.

## E5 — Story loop (sequential) + Tier A  *(per story)*
For each story `{key}` in `epic_stories` order that is **not in the anchor's `stories_landed`** (already
done by THIS run — see E0) and not E0-skipped, set `active_story: {key}` on the epic anchor and
**capture `tier_a_base_sha = git rev-parse HEAD`** (the epic-branch tip *before* this story's first
commit), then run the per-story phases (delegated exactly as `pipeline.md`), with these epic deltas:

a. **Per-story state + triage.** Delegate `tea_triage` (only if `tea.enabled`) to pick this story's
   TEA set, then `state_update.py init` the **per-story** `{state}/{key}.yaml` carrying the triage +
   `is_first/last_in_epic` + `tier_a_base_sha` (recorded here so a resume reuses it, never re-derives
   it from a moved HEAD). Commit `chore(story-{e}-{s}): start auto-bmad pipeline`.
   *(Resume of an adopted in-flight story reuses its existing per-story state instead of init.)*
b. **Create-story** (Phase 3) → **`create-story`**. Commit `docs(story-{e}-{s}): create story context file`.
c. **Pre-dev TEA** (Phase 4, only if `atdd ∈ tea_selected`) → **`testarch-atdd`**. Commit `test(story-{e}-{s}): ATDD acceptance scaffolds (red)`.
d. **Dev-story** (Phase 5) → **`dev-story`** — the hard gate (runs tests, moves the story to
   `review`). A `needs-human` (missing secret/service/manual step) **stops the whole epic** → report.
   Commit `feat(story-{e}-{s}): <summary>` (+ `BREAKING CHANGE:` footer if reported).
e. **Post-dev TEA** (Phase 6, only if `automate ∈ tea_selected`) → **`testarch-automate`**. Commit `test(story-{e}-{s}): expand automated coverage`.
f. **Tier A — thin single review + fix (NO loop, NO convergence gate, NO halt).** This REPLACES the
   per-story Phase 7 loop:
   - Build the **story-scoped** diff: `review_loop.py prep-diff --project-root <project_root>
     --base <tier_a_base_sha>` — the epic-branch tip captured at this story's entry, so the diff is
     **only this story's commits**. (NOT `{base}`: in epic mode every story commits onto the one epic
     branch, so `--base {base}` would make story N's review the cumulative 1..N diff — fattening every
     story and breaking "thin". The whole-epic diff is Tier B's job.)
   - Fan out **only the `tier_a_lenses`** at the **primary** profile (`code_review_review`): the
     **`code-review-auditor`** (the per-story AC check) **+ `code-review-security`** (if
     `code_review.security_review`). NOT blind/edge — their payoff is the whole-epic diff in Tier B.
   - Delegate **`code-review-triage`** (primary profile; `{R}=1`, only the auditor file in the lens
     list, `{security_file_hint}` if security ran) — it persists the `### Review Findings` section to
     **`<story_file>`** verbatim, as in a per-story run. Apply the **same reconciliation gate**
     (`review_findings.py … --story-file <story_file>`; one triage re-run on non-persist, else
     `needs-human`).
   - **Resolve `[Review][Decision]` items autonomously** (no halt to ask): the orchestrator
     **auto-defers** each — re-tag `[Review][Decision]` → `[Review][Defer]` (a git-only direct write,
     never a code read), log it to `<impl>/deferred-work.md` under `## Deferred from: code review of
     {key}`. It then surfaces at the E_review halt.
   - Delegate **one** `code-review fix` pass (`code_review_fix`) on the `[Review][Patch]` items, then
     **post-fix verify** (`review_loop.py post-fix`; one `retry-fix` allowed; `needs-human` stops the
     epic). Commit `fix(story-{e}-{s}): address code review (thin)` (or `chore(story-{e}-{s}): code
     review passed (thin)` if nothing fixable).
   - **Aggregate up to the epic anchor:** if this story's post-fix non-deferred findings include any
     Critical/High (`open_crit_high > 0` or `open_severity.untagged > 0` from the gate-time capture),
     set epic `convergence_unverified: true`; record any blocker on the epic `blockers`. No per-story
     draft decision (stories get no PR). Record a thin marker `tier_a_review` in the per-story state
     (NOT `code_review_iterations` — that is Tier-B-only).
g. **Leave the story at `review`** (not `done`). Optionally run the per-story trace advisory
   (Phase 7 tail) if `trace-advisory ∈ tea_selected` — non-blocking, reuses as-is.
h. **Append `stories_landed += [{key}]`** on the epic anchor and advance `active_story`. Hand any
   retro notes to `state_update.py retro-append` (`retro-notes/epic-{e}.md`).

## E8a — Epic-end gates  *(conditional; reuses Phase 8 gates; runs BEFORE E_review)*
Only the **gates** run here (so their verdicts feed the single E_review halt); the closing steps are
E8b. **Only if `tea.enabled`** (epic-level skills always on at the epic end):
- Delegate **`testarch-trace`** via `tea_epic` (the blocking gate, full depth), then **`testarch-nfr`**
  and **`testarch-test-review`** via `tea_epic_audit` (advisory). Capture each verdict; record
  `gate_decision`.
- **The trace `FAIL` interactive ask is SUPPRESSED in epic mode** (the only halt is E_review). Run
  the gate to a verdict: remediation may still run mechanically up to `tea.gate_max_iterations`
  (delegate **`testarch-automate`** at epic scope, commit `test(epic-{e}): close trace coverage gaps
  (gate iter {i})`, re-trace). Whatever the terminal verdict, record it: `PASS`/`CONCERNS` continue;
  `FAIL`/`WAIVED` become a **finding fed into the E_review halt** (and drive the draft predicate at
  E_final). Do **not** open `AskUserQuestion` here.

## E_review — Epic integration review (Tier B) + the single HITL halt  *(conditional)*
The heavy adversarial pass over the **whole epic diff**, run **once** after all stories land and the
gates resolve. Gated by `code_review.epic_review` (default true; false ⇒ skip Tier B, rely on Tier A
+ E8a). This **relocates Phase 7 steps 1–4 to epic scope** — reuse them, do not fork. Track
`code_review_iterations` + `code_review_loop_done` on the epic anchor (resume continues mid-loop or
re-opens the halt).

1. **Roster — the per-story Phase 7 shape, at epic scope.** Build the epic diff with `review_loop.py
   prep-diff --project-root <project_root> --base {base}` (everything the epic branch changed). Fan
   out, per roster profile (`code_review_review` + the optional secondary/tertiary), the
   **`code-review-blind`**, **`code-review-edge`**, and **`code-review-auditor (epic)`** lenses
   (`3×R` total — identical roster shape to per-story Phase 7). **`code-review-security` stays
   single-instance, off the `3×R` total, severity-gated** (exactly as per story). All in parallel.
2. **Persist to the epic findings file.** Delegate **`code-review-triage (epic)`** (primary profile),
   handed all the lens files + (if security ran) `<security_path>` + the epic diff + the story-file
   list. It writes the `### Review Findings` section to **`<impl>/epic-{e}-review-findings.md`** and
   copies `[Review][Defer]` items to `<impl>/deferred-work.md` under `## Deferred from: epic review of
   epic-{e}`. Apply the **same reconciliation gate** as Phase 7 step 1 against that file
   (`review_findings.py --story-file <impl>/epic-{e}-review-findings.md … --story-key epic-{e}`; one
   triage re-run on non-persist, else `needs-human`).
3. **Loop + classify** exactly as Phase 7 steps 2–3, against the epic findings file: resolve open
   `[Review][Decision]` items via `AskUserQuestion` (**this IS the single review halt** — the only
   place epic mode asks the user about review); delegate **`code-review fix (epic)`**
   (`code_review_fix`) on the `[Review][Patch]` items, commit `fix(epic-{e}): address code review
   (iter {i})`; drive the loop with `review_loop.py gate --findings-json - --iteration {i}
   --max-iterations {code_review.max_iterations} --lenses-failed {failed} --lenses-total {3×R}`
   (`--convergence-unverified true` when a security pass failed on the exit iteration). Obey its
   `action`.
4. **HITL halt** = Phase 7 step 4 verbatim at epic scope: the skip gate auto-continues on a clean
   convergence (`convergence_unverified=false`); otherwise summarize + offer **Run another iteration**
   / **Continue** (with the git-only external-change check + single-shot re-review via the epic
   fan-out) / **Stop**. `convergence_unverified` persisted here drives the epic PR draft predicate.

**Large-diff strategy.** Default: one high-context pass (`prep-diff` writes the full epic diff). When
`diff_file` exceeds `code_review.epic_diff_chunk_threshold_lines` (a deterministic `wc -l` check on
the path — not a code read; 0 ⇒ never), chunk: run `prep-diff --base <story-base>` per landed story
(each its own temp dir), fan the roster per chunk in parallel, then **one JOINT
`code-review-triage (epic)`** over ALL chunk outputs → the single epic findings file (dedup across
chunk boundaries). Gate `--lenses-total = 3×R` over the logical roster (a lens "failed" only if it
failed for every chunk), so chunk count never violates the `{3,6,9}` validator. The residual
purely-cross-chunk discovery gap is accepted (backstopped by the E8a trace gate + the human halt).

## E8b — Epic-end closing  *(conditional; reuses Phase 8 closing; runs AFTER E_review)*
So they capture the integration review's findings + fix commits (mirrors per-story Phase 7 → Phase 8
ordering). In order:
1. **Project context** → delegate **`generate-project-context`** (refresh) via `project_context`, fed
   the epic's accumulated `retro-notes/epic-{e}.md` + the deferred-work ledger.
2. **Reconcile missed completions** *(delegated — `deferred_reconcile`; runs BEFORE the archive)*:
   delegate the **`deferred-reconcile`** entry to mark any `open`/`partial` ledger item whose deferred
   work actually landed during the epic but went unmarked, so step 3 can archive it (same mechanics +
   skip condition as Phase 8 step 3). Record the marked count + evidence in the report.
3. **Archive resolved deferred work** *(orchestrator-direct — connective bookkeeping)*: trim
   `<impl>/deferred-work.md` via `deferred_ledger.py plan` → judge keep-vs-move → `deferred_ledger.py
   archive` into `<impl>/deferred-work-resolved.md` (same mechanics as Phase 8 step 4). Record
   `deferred_work_archived`.
4. **Retrospective** → delegate **`retrospective`** via `retrospective` for epic `{e}`, fed
   `retro-notes/epic-{e}.md`. Record any `planning_drift` (non-blocking; surface in the report).
Commit once: `docs(epic-{e}): gate, project context, deferred-work reconcile + archive, retrospective`.
(Trace-gate remediation, if any in E8a, already committed separately.)

## E_final — Finalize  *(orchestrator, git)*
- Ensure everything is committed (no dirty tree).
- **Write the epic report (before push):** `state_update.py report-section --epic --report-file
  <output_folder>/auto-bmad/reports/epic-{e}.md --state-file {state}/epic/epic-{e}.yaml --json -`
  (the epic-rollup template; `EPIC_REPORT_PAYLOAD_KEYS`). Commit `docs(epic-{e}): pipeline report`.
- **git mode `remote`:** push the epic branch, open **one** PR, wait for CI (`ci_wait.py`), convert to
  draft if warranted — all per `git-and-pr.md` → "Epic mode". Capture `pr_url`, `ci_run_url`,
  `ci_status`. **git mode `local`** (or "stop" was chosen): leave the branch, no push/PR.
- **Draft predicate + batch flip.** Evaluate the epic draft predicate deterministically:
  `state_plan.py --state-dir {state} --scope epic --story-key epic-{e} --finalize
  [--ci-status …] [--no-pr-draft]` (reads the aggregated anchor). On a **clean completion**
  (`flip_bmad_status: true`), batch-flip **every story in `stories_landed`** to `done` —
  `story_plan.py --mark-done {key} --sprint-status <impl>/sprint-status.yaml --story-file
  <impl>/{key}.md` per story (skip pre-existing `done`; never flip an un-verified adopted `review`
  story). On a **caveated** completion, flip **none** — the whole epic stays at `review` until a human
  acts (`git-and-pr.md` → the caveated-epic mirror). Mark the epic anchor `status: done`. Commit the
  anchor→done write + the flips together: `chore(epic-{e}): finalize (mark done + BMAD status)`; push.
- **Merge prompt** (clean completion, `git.offer_merge`, mode `remote`, PR opened, no `skip
  merge-prompt`): ask + execute per `git-and-pr.md` → "Merging the PR".

## Resume
Epic resume reads the epic anchor via `state_plan.py --state-dir {state} --scope epic`: an
`epic-{e}.yaml` with `status != done` is the resume target. Enter at the **first unresolved E-step**
in the anchor's `completed_phases`; for the story named by `active_story`, read its per-story
`{state}/{key}.yaml` (`--story-key {key}`) to resume intra-story granularity — the anchor owns *which
story / which E-step*, the per-story file owns *which phase within the story*. **Stories already in
`stories_landed` are skipped** (E0 adopt) — a resume never re-enters a story this run already landed,
even though it sits at `review` with a complete state file. E_review resumes mid-loop
(`code_review_iterations`) or re-opens the halt (`code_review_loop_done`), exactly as Phase 7. A bare `/auto-bmad` (no `epic`) whose resolved target story is owned by an in-flight epic
anchor **hard-stops, redirecting to `/auto-bmad epic --epic {e}`** (SKILL.md) — finishing one story
alone would split the epic's single PR.
