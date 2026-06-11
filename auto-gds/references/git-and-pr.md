# Git & PR conventions

All git work is performed by the **orchestrator directly** — never delegated (see "Ownership"
below). Nothing ever lands on the base branch; every phase is its own commit so the pipeline is
resumable and reviewable.

## Ownership

This file is the single source for everything the orchestrator owns directly (does not delegate
to an `agds-*` profile). The list — other docs link here by name instead of restating it:

- git preflight, branching, every per-phase commit, push, PR open;
- the Phase 9 **pre-push report write + commit** (`docs(story-{e}-{s}): pipeline report`) — the
  story-level report file is written and committed *before* push so it ships in the PR diff;
- the **CI wait** + draft conversion (when `git.offer_merge` is on);
- the Phase 9 **GDS/BMGD status flip** on a clean completion (story file `Status:` +
  `sprint-status.yaml` → `done`);
- the Phase 9 **merge prompt + `gh pr merge` execution** (opt-in via `git.offer_merge`,
  default on, only on a clean completion);
- the Phase 7 **HITL-halt handling** — detecting external-review changes (a git-only check, never a
  code read), committing them (`fix(story-{e}-{s}): external review changes`), and re-opening the halt
  after the re-review. The **re-review of those changes is delegated**, not orchestrator-owned — it's a
  normal `code-review` pass on the alternate reviewer; the orchestrator no longer inspects code on
  **Continue** (see `pipeline.md` Phase 7 step 4).

Each lives here because the orchestrator holds the full pipeline context — commit/PR messages,
state, the clean-vs-caveated decision; a round-trip to a delegate would only be slower. The
**only** exception is the `inline` delegation tier (host with no subagent mechanism — see
`delegation-runtime.md`), where the orchestrator runs *every* step itself.

## Mode detection (Phase 0)
- It's a git repo? `git rev-parse --is-inside-work-tree`. If not → hard-stop (suggest
  `git init`, since the local-branch flow needs a repo).
- Base branch: the remote HEAD if present (`git symbolic-ref refs/remotes/origin/HEAD`),
  else the current branch at start (commonly `main`/`master`). Store as `git.base_branch`.
- Git mode:
  - **`remote`** if `gh` is installed (`gh --version`), authenticated (`gh auth status`), AND a
    GitHub remote exists (`git remote -v` shows a github.com origin).
  - **`local`** otherwise.
- Working tree must be clean at start (`git status --porcelain` empty). If dirty AND on the base
  branch or an unrelated branch → hard-stop ("commit or stash first"). If dirty on the correct
  story branch during a resume, that's fine — the in-flight phase will commit it.

## Branching (Phase 1)
- Branch name: `{git.branch_prefix}{e}-{s}-{slug}` (default prefix `story/`), e.g.
  `story/1-2-user-auth`. Slug = the story-key title part (already kebab-case).
- `git switch -c <branch>` from the base branch (or `git switch <branch>` if it already exists).
- Never `commit`/`push` to the base branch.

## Commits (between phases)
- Conventional Commits, **in full**: a `type(scope): subject` line **plus a body** (required on
  every commit) and a **footer when relevant** — never subject-only. See "Message body & footer".
- Scope is the story or epic: `story-{e}-{s}` or `epic-{e}`.
- Type per phase (see `pipeline.md` for the exact strings):
  - `chore` — pipeline start, review-passed checkpoint, Phase 9 finalize (mark done + GDS status)
  - `test` — reserved for future GDS testing integrations
  - `docs` — story creation, epic-end docs (context/retro), Phase 9 pipeline report
  - `feat` — story implementation
  - `fix` — addressing code-review findings
- **One commit per phase — the state update folds in.** A phase mutates the project artifacts
  *and* the auto-gds state file (`<auto_gds_dir>/state/{key}.yaml`); stage **both
  together** and make a **single** commit. **Never** emit a standalone bookkeeping commit whose
  only change is the state file — no `chore(story-{e}-{s}): record Phase N in pipeline state`, no
  `chore(...): update state/timestamps`.
- **Recording each commit's own sha** can't happen inside that same commit (the sha doesn't exist
  yet), so do **not** chase it with a second commit: append the just-made phase commit's short sha
  to `commits[]` on the **next** phase's folded-in state write (Phase 9's finalize write closes out
  the last one). `commits[]` feeds the report only — resume keys off `completed_phases`, which the
  folded write keeps current — so a one-phase lag in `commits[]` is harmless.

### Message body & footer
- Keep the **subject** imperative and ≤ ~72 chars. The `feat` subject for dev-story comes from the
  agent's one-line summary of what it built.
- **Body — required on every commit.** One blank line after the subject, then 1–4 wrapped lines
  saying *what this phase changed and why*, drawn from the context the orchestrator **already holds**
  for the phase (the delegate's report, finding/severity counts, resolved decisions, deviations,
  deferred work) — never invent. **The body must add information the subject doesn't carry; if it
  would only restate the subject, the commit is too thin — put the real facts the phase produced.**
  By type:
  - `feat` (dev-story): what was built + notable decisions/deviations + any deferred work.
  - `fix` (code review): the findings addressed this iteration, by severity, and the reviewer/iter;
    note anything deferred or dismissed.
  - `test`: future GDS testing artifacts, when an explicit future testing integration exists.
  - `docs`: which artifact and its scope (story context, project-context, epic context/retro,
    pipeline report).
  - `chore` start: story title, epic, branch, and the delegation tier/profiles in use.
  - `chore` checkpoint (`code review passed`): reviewer/model, iteration, verdict, and that the pass
    had 0 non-deferred findings.
  - `chore` finalize: clean-vs-caveated outcome, the GDS/BMGD status flip, and PR URL / CI status.
- **Footer — optional, only when relevant.** One blank line after the body, Conventional Commits
  `token: value` form. auto-gds emits one only when it holds the data — chiefly
  `BREAKING CHANGE: <what broke + how to migrate>` when a delegate reports an incompatible change
  (equivalently mark the type, e.g. `feat(story-1-2)!: …`). Don't invent footers the phase didn't
  produce.
- **Emit the parts as separate `-m` args** so the blank-line separators are guaranteed:
  `git commit -m "<subject>" -m "<body>" [-m "<footer>"]` — each `-m` becomes its own
  blank-line-separated paragraph, i.e. exactly the subject / body / footer shape. (Stage the phase
  artifacts **and** the state file first — the single-commit rule above.)

## PR (Phase 9, mode `remote` only)
- Push: `git push -u origin <branch>`.
- Open PR: `gh pr create --base <base_branch> --head <branch> --title "<title>" --body "<body>"`.
  Add `--draft` if **any** of these hold (the **draft predicate**):
  1. a blocker was recorded;
  2. `convergence_unverified` is `true` (Phase 7: the review loop hit `max_iterations` while the
     last pass still had not converged — > 3 non-deferred findings or ≥ 1 non-deferred Critical/High;
     **or** a post-halt re-review of external changes surfaced meaningful findings the user chose to
     **Ignore & continue**, or its Fix & re-review rounds hit the cap — see `pipeline.md` Phase 7 step 4);
  3. **CI is red or unknown** when the CI wait below resolves (a required check failed, or the wait
     cap was hit with checks still running) — see "CI wait" below. This condition can only be
     evaluated *after* the push, so if it fires the PR is **converted to draft after the fact**
     with `gh pr ready --undo <pr-number>` (the initial `gh pr create` is issued without
     `--draft` for clauses 1–2 only).
  **The negation of this same draft predicate is the "clean completion" test** that decides
  whether Phase 9 also flips the GDS/BMGD story status (story file `Status:` + `sprint-status.yaml`)
  to `done` — non-draft ⇒ flip, draft ⇒ leave at `review` (see `pipeline.md` Phase 9). Keep the two
  coupled if you edit it.
- Title: a conventional summary of the story, e.g. `feat(story-1-2): user authentication`.
- Body must include:
  - one-paragraph summary of what the story delivered;
  - a link to the story file (`<impl>/{key}.md`);
  - GDS testing outcomes (if a future explicit testing integration ran);
  - a `## Needs attention` checklist of open questions, deferred work, and human-action items
    (empty section omitted);
  - a footer line: `Generated by auto-gds`.
- Capture the returned PR URL into state (`pr_url`) for the **chat** report (chat-only artifact).
- **CI link & wait:** if the repo has CI workflows (test existence with `find .github/workflows
  -name '*.yml' -o -name '*.yaml'` or `test -d`, never a bare `ls .github/workflows/*` glob —
  unmatched it aborts under zsh/fish), the push/PR will have triggered a run. Capture its URL — query the run for the pushed head SHA:
  `gh run list --branch <branch> --limit 1 --json url,workflowName,status,headSha`
  (match `headSha` to the pushed commit), falling back to `gh pr checks <pr-number>` or the
  branch's Actions tab (`<repo_url>/actions?query=branch:<branch>`) if no run has registered yet.
  Store it in state (`ci_run_url`).

  Then evaluate `ci_status` and, when warranted, **wait for in-progress checks to finish**:
  - **When to wait:** only if the merge prompt is effectively enabled this run —
    `git.offer_merge: true` AND no `skip merge-prompt` override. When the prompt is off, do not
    wait — just link the run and leave `ci_status: unknown`.
  - **How to wait:** poll `gh pr checks <pr-number> --json bucket,state,name` every ~20s until no
    check is `pending`/`in_progress`, capped at `git.ci_wait_minutes` (default 30). `gh pr checks
    --watch` is acceptable as long as the call honors the cap. Don't echo per-poll noise — print
    one "waiting on CI (cap N min)" line, then the resolution.
  - **Outcomes** (record in state as `ci_status`):
    - `passed` — every required check is `success` (or `neutral`/`skipped`).
    - `failed` — any required check is `failure`/`cancelled`/`timed_out`/`action_required`.
    - `timeout` — cap reached with checks still running.
    - `none` — no CI workflows or no checks reported.
  - `failed` or `timeout` ⇒ draft-predicate clause 3 fires ⇒ convert PR to draft via
    `gh pr ready --undo <pr-number>` and leave story at `review`.
  - `passed` or `none` ⇒ clause 3 does not fire; the existing clauses 1–2 still decide draft vs
    non-draft.

## Merging the PR (Phase 9, only when clean) — orchestrator
auto-gds never merges automatically. When the run is a **clean completion** (full draft
predicate is false — clauses 1–3 above) AND `git.offer_merge` is `true` AND the run has no
`skip merge-prompt` override, the orchestrator **asks** the user whether to merge before
reporting. The merge is the user's call; the orchestrator just runs the chosen `gh` command on
their behalf, then switches the working tree back to the base branch so the next run starts
clean.

- **Prompt** (`AskUserQuestion`, 4 options, in this order — first is the default): **Merge commit
  (recommended)** / Rebase and merge / Squash and merge / Don't merge. Merge commit is the default
  because it preserves every per-phase auto-gds commit — the richest signal for an AI later
  running `git log`/`blame`/`bisect` on the story. If a merge style is chosen, **ask a second
  question** — Delete branch? Yes / No.
- **Execute** (only if the user picked a merge style):
  - `gh pr merge <pr-number> --merge` *(or `--rebase` / `--squash`)* `[--delete-branch]`.
  - On success: `git switch <base_branch>` then `git pull --ff-only` so the local tree matches
    `origin/<base_branch>` post-merge.
  - On failure (branch protection, required reviews, conflict, CI required check missing, etc.):
    don't retry, don't error out — capture the `gh` stderr verbatim into the report under "Needs
    attention" ("PR merge failed: …; merge manually at `<pr_url>`") and leave the PR open. The
    pipeline still ends `done` (the GDS/BMGD status flip already happened); merging is a separate,
    user-elected action and a failed attempt doesn't invalidate the completion.
- **Record** in state: `pr_merged: true|false`, `merge_method: squash|merge|rebase|null`,
  `branch_deleted: true|false`. Surface the outcome in the **chat** report (it's a chat-only
  finalization artifact — one line: "Merged via merge commit; branch deleted." / "PR left open at
  user's request." / "Merge attempted but failed (`<reason>`); merge manually."). A *failed* merge
  also lands in the file's "⚠️ Needs human" — it's a genuine follow-up, not just an artifact echo.

When the prompt is **off** for this run (`git.offer_merge: false` or `skip merge-prompt`
override), Phase 9 ends after the finalize bookkeeping — PR stays open for the human.

## Mode `local`
- No push, no PR, no merge prompt (there's nothing to merge). Leave the branch checked out. The
  final report tells the user the branch name and that no GitHub remote/`gh` was found, so they
  can push/PR manually if they wish.
