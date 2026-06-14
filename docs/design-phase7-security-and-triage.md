# Design — Phase 7 security review + triage selectivity

Status: **proposal** (not yet implemented). Two deliberate, *fenced* deviations from the upstream
`bmad-code-review` replica. Author-facing design note; the normative behaviour, once built, lives in
the reference docs.

## 1. The two changes (and why they're coupled)

- **B — Triage selectivity (the "Low explosion").** With a 3-reviewer roster, 20+ Low findings can
  survive triage. They never *block* the pipeline (the gate converges on a Low-only pass with no
  count cap — `review_loop.py _is_converged`), but every surviving Low persists as `[Review][Patch]`
  and is handed to the fix delegate → fix-churn on trivia + story/PR clutter. Fix: a **severity-aware
  keep/drop test** that retains genuine Lows and discards noise (cosmetic, hypothetical,
  defense-in-depth-without-a-problem).
- **A — Security review.** Add a security reviewer to Phase 7, modelled on Anthropic's open-source
  `claude-code-security-review` methodology (ported inline — the `/security-review` command is
  Claude-only; auto-bmad must run on Codex/opencode too).

**Coupling (do B with or before A):** a security reviewer *increases* finding volume, so the keep/drop
test (B) is a prerequisite for adding A without making the Low explosion worse. The same discipline
powers both — Anthropic's exclusion list + confidence floor *is* the keep/drop test specialised to
vulns.

## 2. Guiding constraint — lockstep, and how we fence the deviation

CLAUDE.md: auto-bmad's Phase 7 *replicates the internal structure* of upstream `bmad-code-review`
(lens roster, the verbatim Acceptance Auditor prompt, the triage rubric) because a delegate can't
spawn that skill's three internal subagents. Both changes touch replicated surface (A = the lens
roster, B = the triage rubric). They are **intentional local additions with no upstream counterpart.**

The compat-check (`/auto-bmad-compat-check`) does its replica-vs-upstream comparison as **human
judgement** (SKILL.md Step 2: "diff `bmad-code-review`'s step-02/step-03 … against the replica in
`references/delegation.md`"). `bmad_compat.py` only *classifies upstream files by relevance*; it does
**not** parse our `delegation.md` for markers. So:

- Fence each addition in `delegation.md` with an explicit marker comment, e.g.
  `<!-- auto-bmad-local: NOT from upstream bmad-code-review; do not reconcile away on compat-check -->`.
  This is for the **maintainer** doing the Step-2 diff, so our additions don't read as drift.
- Add one line to `auto-bmad-compat-check/SKILL.md` Step 2 (the `critical` row) naming the two
  local additions (security reviewer, Low keep/drop test) so a future reviewer knows they have no
  upstream analogue by design.

## 3. Change B — the triage keep/drop test

The problem isn't severity; it's that triage sorts *only* on severity and has no signal-vs-noise
axis. A Low can be a genuine minor bug or pure cosmetics — and cosmetics are usually *true* (the
observation is correct) but **useless**. So filter on **impact/usefulness, not correctness of the
observation.**

### The test (Lows only; Critical/High/Med always bypass)

Keep a Low only if **both** hold:

1. **Concrete defect** — a specific wrong/worse *behaviour*, not a preference. "Could be cleaner /
   more idiomatic / more defensive" fails; "returns the wrong value on empty input" passes.
2. **Realistic trigger** — an input/path that plausibly occurs, not a chain of unlikely
   preconditions.

> **Carve-out for security-sourced findings — see §5.** The "realistic trigger" axis must NOT be
> applied to security findings: "needs attacker-controlled conditions" is the *definition of MEDIUM*
> in the security model, not a dismissal reason. Security findings are filtered by the security
> exclusion list instead.

### Three outcomes for a Low

- **Patch** — genuine defect, unambiguous fix, worth doing now → fix delegate.
- **Defer** — genuine but minor / not worth churning now → `[Review][Defer]` + the durable ledger.
  *Retained and recoverable*, surfaces in the PR checklist. (Note: deferred items are re-folded into
  future stories by create-story, so Defer is for genuinely-trackable work, not noise.)
- **Dismiss** — fails the test (cosmetic / preference / hypothetical / already-guarded
  defense-in-depth) → dropped, **counted**.

Map to the user's ask exactly: *genuine useful* → Patch/Defer; *cosmetic + remote/unlikely* →
Dismiss.

### Two supporting levers

- **Dedup harder.** A chunk of the 20+ is the same nit reported three ways by three models (and, with
  A, by the security pass too). Strengthen the existing "expect heavy overlap across reviewers — merge
  aggressively" instruction to explicitly span all lenses *and* the security pass.
- **Auditability (answers "could it hide something?").** Extend triage's chat report with
  `Dismissed (noise): <N>` plus a one-line category each (cosmetic / hypothetical / already-guarded).
  Nothing vanishes silently; the human can pull anything back. **Chat-only** — the orchestrator reads
  triage's chat report; `review_findings.py` parses only what's written to the file, so dropping a
  finding needs no parser change.

### What B does NOT touch

- `review_findings.py` — unchanged. Dismissed findings are simply never written; severity buckets
  (`critical/high/medium/low/untagged`) already exist.
- `review_loop.py` gate — unchanged. Fewer surviving Lows just means the existing convergence rule
  fires on a smaller set.

## 4. Change A — security review as an in-loop, findings-channel reviewer

### The key architectural decision: findings-channel, not lens-count-channel

`review_loop.py` validates `--lenses-total` against `VALID_LENS_TOTALS = (3, 6, 9)` (3 lenses × 1–3
reviewers), pinned by the CLI usage check and the self-test. So wiring security as a "4th lens"
(`4×R` → totals `4/8/12`, or single-instance `3R+1` → `4/7/10`) would be **rejected** and force churn
through the gate math + every self-test row.

Avoid that entirely: the security reviewer rides the **findings-severity channel**, which already
gates convergence, instead of the lens-completeness channel.

- It runs **inside the loop, every iteration**, alongside the `3×R` correctness fan-out. So it
  reviews the *cumulative* branch diff including each iteration's fixes — a fix that introduces a vuln
  is caught next pass. (This is the "review the fixes" property; it's why in-loop beats a separate
  one-shot pass.)
- Its findings flow into the **same `code-review-triage`**, are severity-tagged into the
  `### Review Findings` section, and therefore gate convergence **automatically**: a security
  Critical/High lands in `open_crit_high` → not converged → the loop continues to fix it. **No
  `review_loop.py` gate change. No `review_findings.py` change.**
- **Single-instance** (one dedicated `ab-security` delegate per iteration), not per-roster — cost is
  `+1` delegate/iteration, not `+R`. (It's off the `3×R` channel, so we're free to choose; one
  capable security model beats three generalists re-running the same hunt.)

### Completeness / failure semantics (the one subtlety)

A security pass that **runs and finds nothing is the common, clean case** — an empty findings file =
0 findings = clean, *not* a failure. Only a genuine delegate failure (errored / no parseable output)
means "security didn't actually run." Handle that via the gate's existing **sticky
`--convergence-unverified true`** input (its docstring: "a pre-existing STICKY flag … e.g. set by an
earlier event"): on a real security-pass failure, the orchestrator passes `--convergence-unverified
true` → forces an unverified exit → draft PR + HITL halt. **No `lenses_total` accounting change.**
Do **not** trip this on a successful 0-finding pass.

**Evaluate it per iteration, at exit — not as a persisted sticky.** The flag must reflect *the
exit-deciding pass's* security result, mirroring how `lenses_failed` is per-pass. The orchestrator
passes `--convergence-unverified true` only when **that** iteration's security delegate failed — so a
*transient* iteration-1 crash that recovers cleanly by the exit pass ships a normal PR, while a
genuinely-failed final security pass drafts. Do not fold a transient early failure into the persisted
state flag (the gate can never clear it, so that would draft permanently on a recovered failure).

### The delegate

- **Profile:** new `phase_profiles` key `code_review_security`, pointing to a new dedicated
  `ab-security` profile (so model/effort is independently tunable — security wants a capable model).
  If a user blanks the key, fall back to the `code_review_review` (primary) profile (the *feature* is
  gated by a config toggle, below — blanking the profile shouldn't disable it).
- **Enable toggle:** `code_review.security_review: true` (constant default; see §7 lockstep).
- **Scope:** diff + project read (like the edge lens) — reachability/authz analysis needs surrounding
  code, not just the diff.
- **Invariant preserved:** the delegate reads code and writes findings to its own temp path; the
  orchestrator routes that path to triage and never reads it. Its chat `Outcome` is path + count
  only — "no code inspection at any tier" holds.

## 5. Security severity map + exclusion carve-out (must-fix)

The triage prompt must treat security-sourced findings on the security model, or the generic Low test
(§3) will dismiss exactly the conditional-exploit vulns security review exists to catch.

**Severity map (security → triage tags):**

| Security lens | Triage tag |
|---|---|
| HIGH (directly exploitable: RCE, auth bypass, data breach) | `[Critical]` / `[High]` |
| MEDIUM (exploitable but needs conditions / attacker-controlled state) | `[Med]` |
| LOW (defense-in-depth, no concrete exploit) | `[Low]` |

**Carve-out:** a security-sourced finding is dismissable **only** via the security exclusion list —
never via the generic "unlikely trigger" rule. "Exploitable with effort/conditions" is **Medium,
keep it**, not noise.

**Routing rules (close the three ways triage can silently swallow a security finding).** The §3
carve-out closes only one (the generic trigger test). Two more, both verified against the code:

1. **No auto-Defer of security Crit/High.** Triage's `Defer` bucket ("real but pre-existing, not
   caused by this change") would naturally catch a *pre-existing* security Critical in code the diff
   touches. Traced: `[Review][Defer][Critical]` → `review_findings.py:249` excludes deferred bullets
   from `open_crit_high` → gate converges → `convergence_unverified` false → the Phase 7 step-4 skip
   gate fires → **ships as a normal PR**, visible only in the deferred-work checklist. That is too
   quiet for the one class this feature exists to catch — and unlike a correctness defer, *no human
   chose it* (the triage LLM did). **Rule: a security-sourced Critical/High may only be `Patch` or
   `Decision`, never `Defer` or `Dismiss`** — so it is either fixed in-iteration or surfaced at the
   AskUserQuestion halt. (Medium/Low security findings may still Defer/Dismiss per the normal rules.)
2. **No merge-downgrade.** Triage step 2 merges same-issue findings with no severity-precedence rule;
   if the security pass flags a line High and a generalist lens flags it Low, the LLM picks the merged
   severity — pick Low among >3 findings and §3 can dismiss a real High. **Rule: on merge, take the
   MAX severity across the merged findings; a non-security lens can never downgrade the security
   lens's severity.**

**Exclusion list** (port of Anthropic's, applied to security findings):
- Denial of Service / resource exhaustion; memory or CPU exhaustion.
- Absence of rate limiting / service-overload scenarios.
- Lack of input validation on **non-security-critical** fields with no proven problem.
- (Confidence floor: drop findings below ~0.7 confidence — speculative, no demonstrable path.)
- *Deviation from upstream Anthropic:* it excludes "secrets/credentials on disk (managed
  separately)". We do **not** blanket-exclude hardcoded secrets — they're high-signal in a code diff.
  Keep them. (Decision to confirm with the user.)

Because Medium maps below the Low filter's reach and the carve-out blocks the generic trigger test,
the design is load-bearing on this map being correct — a real vuln tagged Low would be eaten by §3.

## 6. The security prompt (draft — tool-agnostic, parallels the auditor lens)

Add to `delegation.md` as `code-review-security`, fenced as auto-bmad-local:

```
You are a Security Reviewer. Review this diff for exploitable security vulnerabilities introduced or
exposed by the change. Examine: input validation (SQL/command/template/NoSQL injection, XXE, path
traversal, SSRF); authentication & authorization (bypass, privilege escalation, session/JWT flaws);
crypto & secrets (hardcoded credentials, weak algorithms, improper key/cert handling); injection &
code execution (deserialization RCE, eval, XSS); sensitive-data exposure (logging, PII, debug leakage).

For each finding give: a one-line title; file:line; severity HIGH (directly exploitable) / MEDIUM
(exploitable under conditions) / LOW (defense-in-depth); a concrete exploit scenario; and a fix.

DO NOT REPORT (noise): denial-of-service / resource exhaustion; memory or CPU exhaustion; absence of
rate limiting; lack of input validation on non-security-critical fields with no proven problem; any
finding you are <70% confident is a real, reachable issue. "Exploitable only under conditions" is
MEDIUM — report it, do not drop it.

The diff is at <diff_file>; you may read project files the diff references for reachability. Write
findings as a Markdown list to <security_out>. Report ONLY the path you wrote and your finding count —
NOT the findings text.
```

The `code-review-triage` prompt gains: the security file as an input source; the §5 severity map +
carve-out; the §5 routing rules (security Crit/High → Patch/Decision only; max-severity on merge);
the §3 keep/drop test + three-outcome routing; the dedup reinforcement; the `Dismissed (noise): N`
report line. Concretely, append to the triage prompt's TRIAGE block:

```
- Findings from the dedicated security pass (<security_out>) use the security severity map:
  HIGH -> Critical/High, MEDIUM -> Med, LOW -> Low. A MEDIUM means "exploitable under conditions" —
  that is NOT a reason to dismiss it.
- A security-sourced Critical/High may ONLY be classified Patch or Decision — NEVER Defer or Dismiss
  (a pre-existing exploitable flaw still ships if deferred; force a human call instead).
- When merging duplicate findings, the merged severity is the MAXIMUM across them; a non-security
  lens can never lower a severity the security pass assigned.
- For Low findings only, KEEP one only if it names a concrete defect AND a realistic trigger; dismiss
  cosmetic/preference/hypothetical/already-guarded nits (count them). Do NOT apply the "realistic
  trigger" test to security findings — filter those by the security exclusion list above instead.
```

## 7. Exact file touch-list (grounded)

**Changed:**
- `assets/agents/profiles.yaml` — add `ab-security` profile (capable model/effort per tool; opencode
  blank); add `phase_profiles.code_review_security: ab-security`.
- `scripts/render-agents.py` — add `ab-security` to `PROFILE_NAMES` (line 71) + the persona
  assertions in `_run_self_test` (≈ lines 405–414). Renderer auto-emits the agent file for any
  `ab-*` profile, so no generator logic changes.
- `assets/config-defaults.yaml` — add `code_review.security_review: true`.
- `scripts/config_plan.py` — self-test: assert `code_review.security_review` present in the asset
  (≈ line 1194 neighbourhood) + add to the value-presence list (≈ line 1215). Append-only heal
  already handles a new constant-default key with no code change.
- `references/delegation.md` — new `code-review-security` entry (fenced local); triage-prompt edits
  (fenced local): security input + severity map + carve-out + keep/drop test + dedup + report line.
- `references/pipeline.md` — Phase 7 step 1: add the security delegate to the fan-out (parallel,
  every iteration, single-instance); document it's **off** the `3×R` `--lenses-total`; convergence
  rides findings severity; a security-pass *failure* (not an empty result) on the exit-deciding
  iteration sets the gate's `--convergence-unverified true` (per-iteration, not persisted-sticky).
  **All three fan-out sites must run security:** the main loop (step 1), the "Run another iteration"
  extension (re-enters the loop), AND the step-4 external-change single-shot re-review (the Continue
  path) — the last gates via `review_loop.py converged` (findings-only, no unverified input), so a
  genuine security-pass failure there is handled by treating the changes as meaningful (re-ask).
  **Also carries the orchestrator's absent-key fallback** `code_review.security_review` → `true` —
  CLAUDE.md requires this fallback to equal config-defaults.yaml's default (and state-and-resume.md),
  or `config_plan.py --self-test`'s lockstep passes while the running default silently disagrees.
- `scripts/review_loop.py` — `prep-diff`: reserve one additive `security` output path in the result
  + self-test assertions for it. **Gate / `VALID_LENS_TOTALS` deliberately unchanged.**
- `references/state-and-resume.md` — schema: document `code_review.security_review` +
  `phase_profiles.code_review_security`; bump `profiles_source_version` examples if needed at release.
  Report/state: security findings ride existing `### Review Findings` + counts (no new core field);
  consider a `code_review` report note when the security pass failed.
- `CHANGELOG.md` — `[Unreleased]`: one bullet for the security reviewer, one for the triage
  selectivity (one change = one bullet).
- `.claude/skills/auto-bmad-compat-check/SKILL.md` — one line flagging the two local additions.

**Deliberately NOT changed:** `review_findings.py` (parser); `review_loop.py` gate logic +
`VALID_LENS_TOTALS`; the upstream-mirrored parts of the lens roster + Acceptance Auditor prompt.

## 8. Test plan

- `python3 auto-bmad/scripts/review_loop.py --self-test` (new `prep-diff` security-path assertions).
- `python3 auto-bmad/scripts/render-agents.py --self-test` (new profile).
- `python3 auto-bmad/scripts/config_plan.py --self-test` (new constant-default key + lockstep).
- `python3 auto-bmad/scripts/review_findings.py --self-test` (must still pass *unchanged* — proves B
  needs no parser change).
- Live: run `/auto-bmad reprovision` to render `ab-security`; run a story whose diff has a planted
  vuln + several cosmetic Lows; confirm the vuln gates convergence and the cosmetics are dismissed
  (and counted).

## 9. Open decisions for the user

1. **Hardcoded-secrets exclusion** — keep reporting them (recommended) vs. follow Anthropic and
   exclude (they assume secret-scanning runs separately).
2. **Default on or off** — `code_review.security_review: true` by default (recommended) vs. opt-in.
3. **Single-instance vs per-roster security** — single-instance recommended (cost); per-roster only
   if cross-model vuln diversity is worth `+R` delegates/iteration.
4. **SAST pairing** — out of scope here, but the strongest security review pairs this LLM lens with a
   deterministic SAST (e.g. Semgrep) when the project ships one. Note as a future follow-up?
