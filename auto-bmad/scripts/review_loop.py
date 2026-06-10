#!/usr/bin/env python3
"""Deterministic Phase 7 code-review loop driver for the orchestrator.

Phase 7's control flow — build the review diff, gate each pass's findings into
continue/exit/halt, and verify each fix pass actually closed its items — is a
decision table, not judgment. This script encodes it so the orchestrator calls
a tool and OBEYS the answer instead of re-deriving the rules from prose every
iteration. The table below is the normative contract; the ``--self-test`` pins
every row.

Four modes, each emitting ONE JSON object on stdout:

* ``prep-diff`` (live, git): create a throwaway temp dir OUTSIDE the work tree
  (``tempfile.mkdtemp``), write the branch diff ``git diff --no-ext-diff
  --no-color <base>...HEAD`` — run inside ``--project-root``, output pinned to
  a plain unified diff (immune to user ``diff.external``/``color.diff``
  config), with the review exclude pathspecs baked in (``_bmad``,
  ``_bmad-output`` and, in root-matching glob magic, ``**/__pycache__/**``,
  ``**/*.pyc``, ``**/.DS_Store``) — to ``<tmp>/diff.patch``, and reserve the three
  lens-output paths (``blind_out`` / ``edge_out`` / ``auditor_out`` — reserved
  PATHS only, the files are NOT created; the lens delegates write them). The
  orchestrator routes the returned paths to the fan-out delegates and never
  reads the diff itself ("no code inspection at any tier"). Output:
  ``{review_tmp, diff_file, blind_out, edge_out, auditor_out, diff_empty,
  base, head_sha}``. ``diff_empty: true`` means there is nothing to review —
  the orchestrator treats it as a perfectly clean 0-finding pass with 0 failed
  lenses (gate row 2).

* ``gate`` (pure decision, no I/O beyond reading the findings): decide what
  the loop does after a review pass. ``--findings-json`` is the VERBATIM JSON
  of ``review_findings.py`` at gate time (``-`` = stdin); the keys consumed
  are ``open_nondeferred``, ``open_crit_high`` and ``open_severity.untagged``.
  Derived: ``clean`` = ``open_nondeferred == 0``; ``converged`` =
  ``open_nondeferred <= 3 AND open_crit_high == 0 AND open_severity.untagged
  == 0`` (an untagged finding is treated as Critical/High — conservative).
  Decision table (``i`` = 1-based ``--iteration``; cap = ``i`` reaching
  ``--max-iterations``):

  | # | i   | lenses-failed | findings            | cap? | action           | convergence_unverified | hitl                       |
  |---|-----|---------------|---------------------|------|------------------|------------------------|----------------------------|
  | 1 | any | 3             | —                   | —    | needs-human      | input (unchanged)       | null                       |
  | 2 | 1   | 0             | clean               | —    | exit-clean       | false (or input true)   | skip-halt if cfg else halt |
  | 3 | 1   | 0             | not clean           | no   | continue         | false/input             | null                       |
  | 4 | 1   | 1–2           | any (untrustworthy) | no   | continue         | false/input             | null                       |
  | 5 | 1   | any ≤2        | not perfectly clean | yes  | exit-unconverged | true                    | halt                       |
  | 6 | ≥2  | 0             | converged           | —    | exit-clean       | false/input             | skip-halt if cfg else halt |
  | 7 | ≥2  | 1–2           | converged           | —    | exit-unconverged | true                    | halt                       |
  | 8 | ≥2  | ≤2            | not converged       | no   | continue         | false/input             | null                       |
  | 9 | ≥2  | ≤2            | not converged       | yes  | exit-unconverged | true                    | halt                       |

  Semantics:
  - Row 2 is the ONLY first-pass early exit: "perfectly clean" = 0 non-deferred
    findings AND all 3 lenses ran. Any other first pass pulls the mandatory
    second opinion (rows 3–4) or, when the cap blocks it (``max_iterations:
    1``), exits as an unverified draft (row 5).
  - Row 7: a converged pass with a failed/empty lens is the same flavor of
    unverified-ness as a cap exit — its ``reason`` carries the "incomplete
    review (only N/3 lenses ran)" caveat for the report and halt summary.
  - Reviewer profiles: with ``--alternate-models true``, odd iterations run
    ``code_review_review`` and even ones ``code_review_review_secondary``;
    otherwise every iteration is ``code_review_review``. Iteration 1 is
    ALWAYS the primary. ``reviewer_this_iter`` / ``reviewer_next_iter`` are
    reported on every decision.
  - ``hitl`` is non-null only on exit-* actions. ``skip-halt`` fires iff
    ``--skip-hitl-on-clean-convergence true`` AND the OUTPUT
    ``convergence_unverified`` is false; ``exit-unconverged`` always halts;
    ``needs-human`` is a hard stop (hitl null — there is no halt to skip).
  - ``--convergence-unverified true`` is a pre-existing STICKY flag (e.g. set
    by an earlier event): the output value is ``input OR what this decision
    sets`` — the gate can NEVER clear it, and a sticky true forces ``halt``
    even on rows 2/6 (the skip gate never fires while the flag is true).
  - The decision IS the result: exit 0 whatever the action (2 only on
    usage/bad JSON). Defensive: an iteration OVERSHOOTING ``--max-iterations``
    still counts as capped (the loop exits; it can never spin past the cap).

* ``converged`` (pure): the convergence rule ALONE, for the Phase 7
  external-change re-review at the HITL halt: the external changes are
  ``meaningful`` (re-open the halt) iff the re-review's findings are NOT
  converged — the same rule, same verbatim ``review_findings.py`` input as the
  gate, so the threshold lives only here, never in orchestrator prose. Output:
  ``{converged, meaningful, open_nondeferred, open_crit_high, untagged, reason}``.

* ``post-fix`` (pure): verify a fix delegate's work from a POST-FIX re-run of
  ``review_findings.py``. Expectation: ``open_patch == 0 AND open_decision ==
  0`` (the fix resolves every patch plus every human-resolved decision;
  deferred/dismissed items are checked off or re-tagged, so they no longer
  count as open). Met → ``proceed``. Unmet → ``retry-fix`` (one re-delegation
  of the `code-review fix` entry; it does not consume a loop iteration) or,
  when ``--retry-used`` is present, ``needs-human``. This guarantees the next
  gate's open counts are attributable to the next review pass, not a half-done
  fix. Output: ``{action, open_patch, open_decision, reason}``.

Usage:
    review_loop.py prep-diff --project-root DIR --base BRANCH
    review_loop.py gate --findings-json -|FILE --iteration I --max-iterations M \\
        --alternate-models true|false --lenses-failed 0..3 \\
        --skip-hitl-on-clean-convergence true|false [--convergence-unverified true|false]
    review_loop.py post-fix --findings-json -|FILE [--retry-used]
    review_loop.py converged --findings-json -|FILE
    review_loop.py --self-test

Exit codes: 0 = success (gate/post-fix: the decision is the result, whatever
it says); 2 = usage error, unreadable/invalid findings JSON, or (prep-diff) a
failed git command. Dependency-free (stdlib only).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

# The exclude pathspecs baked into the review diff. Passed as single argv
# tokens straight to git (never through a shell), so there is no glob hazard.
# The wildcard ones use ``:(exclude,glob)`` magic: under glob (wildmatch
# pathname) semantics a leading ``**/`` matches in ALL directories INCLUDING
# the repo root, whereas default fnmatch never matches root-level files
# (verified live: a committed root ``.DS_Store``/``*.pyc`` leaked without it).
# ``__pycache__`` needs the trailing ``/**`` because glob ``*`` stops at
# slashes — ``**/__pycache__`` alone matches the directory NAME, never the
# files inside it.
EXCLUDE_PATHSPECS = (
    ":(exclude)_bmad",
    ":(exclude)_bmad-output",
    ":(exclude,glob)**/__pycache__/**",
    ":(exclude,glob)**/*.pyc",
    ":(exclude,glob)**/.DS_Store",
)
DIFF_FILENAME = "diff.patch"
# Reserved lens-output filenames inside review_tmp (paths only, never created
# here — the lens delegates write them): blind/auditor emit markdown lists,
# edge emits a JSON array (delegation.md → code-review (fan-out)).
LENS_FILENAMES = (("blind_out", "blind.md"), ("edge_out", "edge.json"), ("auditor_out", "auditor.md"))

PRIMARY_REVIEWER = "code_review_review"
SECONDARY_REVIEWER = "code_review_review_secondary"
CONVERGENCE_MAX_FINDINGS = 3
TOTAL_LENSES = 3


# --------------------------------------------------------------------------- #
# prep-diff
# --------------------------------------------------------------------------- #
def build_diff_argv(base: str) -> list:
    """Pure argv builder for the review diff. Three-dot = exactly what this
    branch changed since it diverged from base. ``--no-ext-diff --no-color``
    pin the output to a plain unified diff: a user ``diff.external`` (e.g.
    difftastic) would otherwise silently replace it with external-tool output
    (exit 0!), and ``color.diff=always`` would embed ANSI escapes."""
    return ["git", "diff", "--no-ext-diff", "--no-color", f"{base}...HEAD", "--", *EXCLUDE_PATHSPECS]


def build_head_argv() -> list:
    return ["git", "rev-parse", "HEAD"]


def _default_runner(argv, cwd):
    """Run argv in cwd; return (returncode, stdout_bytes, stderr_text).

    stdout stays BYTES so a diff with non-UTF-8 hunks is written verbatim.
    """
    proc = subprocess.run(argv, cwd=cwd, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


def prep_diff(project_root: str, base: str, runner=_default_runner, mkdtemp=tempfile.mkdtemp):
    """Build the review diff in a fresh temp dir OUTSIDE the work tree.

    Returns the success dict (the prep-diff JSON contract) or
    ``{"status": "error", "message": ...}`` when git fails. The temp dir is
    only created AFTER both git commands succeed, so a failure leaks nothing.
    """
    try:
        rc, head_out, err = runner(build_head_argv(), project_root)
        if rc != 0:
            return {"status": "error",
                    "message": f"git rev-parse HEAD failed in {project_root!r} (exit {rc}): {err.strip()[:300]}"}
        rc, diff_out, err = runner(build_diff_argv(base), project_root)
        if rc != 0:
            return {"status": "error",
                    "message": f"git diff {base}...HEAD failed in {project_root!r} (exit {rc}): {err.strip()[:300]}"}
    except OSError as exc:
        return {"status": "error", "message": f"could not run git in {project_root!r}: {exc}"}

    review_tmp = mkdtemp(prefix="auto-bmad-review-")
    diff_file = os.path.join(review_tmp, DIFF_FILENAME)
    with open(diff_file, "wb") as fh:
        fh.write(diff_out)

    result = {
        "review_tmp": review_tmp,
        "diff_file": diff_file,
    }
    for key, name in LENS_FILENAMES:
        result[key] = os.path.join(review_tmp, name)
    result["diff_empty"] = not diff_out.strip()
    result["base"] = base
    result["head_sha"] = head_out.decode("utf-8", "replace").strip()
    return result


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def _reviewer_for(iteration: int, alternate_models: bool) -> str:
    """Odd iterations (and all, when not alternating) → primary; even → secondary."""
    if alternate_models and iteration % 2 == 0:
        return SECONDARY_REVIEWER
    return PRIMARY_REVIEWER


def _findings_int(findings, *path):
    node = findings
    for key in path:
        try:
            node = node[key]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"findings JSON is missing review_findings.py key {'.'.join(path)!r}"
            ) from exc
    try:
        return int(node)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"findings key {'.'.join(path)!r} is not an integer: {node!r}") from exc


def _is_converged(nondef: int, crit_high: int, untagged: int) -> bool:
    """THE convergence rule — the only place it is encoded (the gate and the
    ``converged`` mode both call this; the docs say to call, never re-derive)."""
    return nondef <= CONVERGENCE_MAX_FINDINGS and crit_high == 0 and untagged == 0


def _nonconvergence_why(nondef: int, crit_high: int, untagged: int) -> str:
    parts = []
    if nondef > CONVERGENCE_MAX_FINDINGS:
        parts.append(f"{nondef} non-deferred findings > {CONVERGENCE_MAX_FINDINGS}")
    if crit_high:
        parts.append(f"{crit_high} Critical/High")
    if untagged:
        parts.append(f"{untagged} untagged (treated as Critical/High)")
    return ", ".join(parts) or "not converged"


def decide_gate(
    findings: dict,
    iteration: int,
    max_iterations: int,
    alternate_models: bool,
    lenses_failed: int,
    skip_hitl_on_clean_convergence: bool,
    convergence_unverified: bool = False,
) -> dict:
    """Encode the Phase 7 decision table. Pure; raises ValueError on bad findings."""
    nondef = _findings_int(findings, "open_nondeferred")
    crit_high = _findings_int(findings, "open_crit_high")
    untagged = _findings_int(findings, "open_severity", "untagged")

    clean = nondef == 0
    converged = _is_converged(nondef, crit_high, untagged)
    lenses_ran = TOTAL_LENSES - lenses_failed
    cap = iteration >= max_iterations  # >= is defensive: an overshoot still caps
    unverified = bool(convergence_unverified)  # sticky: never cleared below
    lens_caveat = f"; incomplete review (only {lenses_ran}/{TOTAL_LENSES} lenses ran)" if lenses_failed else ""

    if lenses_failed >= TOTAL_LENSES:  # row 1
        action = "needs-human"
        reason = (f"code review incomplete — 0/{TOTAL_LENSES} lenses produced findings; "
                  "the review did not actually happen, never count it as clean")
    elif iteration == 1:
        if clean and lenses_failed == 0:  # row 2
            action = "exit-clean"
            reason = ("first pass perfectly clean (0 non-deferred findings, all "
                      f"{TOTAL_LENSES} lenses ran) — the only first-pass early exit; second opinion skipped")
        elif not cap:  # rows 3–4
            action = "continue"
            if lenses_failed:  # row 4 — even a 0-finding pass is untrustworthy
                reason = (f"only {lenses_ran}/{TOTAL_LENSES} lenses ran — a first pass this incomplete "
                          "is not trustworthy as clean; the second opinion is mandatory")
            else:  # row 3
                reason = f"first pass found {nondef} non-deferred finding(s) — the second opinion is mandatory"
        else:  # row 5 (max_iterations == 1)
            action = "exit-unconverged"
            unverified = True
            what = (f"{nondef} non-deferred finding(s)" if nondef
                    else f"only {lenses_ran}/{TOTAL_LENSES} lenses ran")
            reason = (f"single-pass cap (max_iterations == {max_iterations}): the pass is not perfectly "
                      f"clean ({what}) and its mandatory second opinion cannot run — unverified draft")
    else:
        if converged and lenses_failed == 0:  # row 6
            action = "exit-clean"
            reason = (f"pass converged ({nondef} non-deferred finding(s), 0 Critical/High, "
                      f"all {TOTAL_LENSES} lenses ran)")
        elif converged:  # row 7
            action = "exit-unconverged"
            unverified = True
            reason = (f"pass converged, but incomplete review (only {lenses_ran}/{TOTAL_LENSES} "
                      "lenses ran) — a converged result with a missing lens is unverified")
        elif not cap:  # row 8
            action = "continue"
            reason = (f"not converged ({_nonconvergence_why(nondef, crit_high, untagged)})"
                      f"{lens_caveat} — continue to iteration {iteration + 1}")
        else:  # row 9
            action = "exit-unconverged"
            unverified = True
            reason = (f"max_iterations ({max_iterations}) reached without convergence "
                      f"({_nonconvergence_why(nondef, crit_high, untagged)}){lens_caveat}")

    hitl = None
    if action == "exit-clean":
        hitl = "skip-halt" if (skip_hitl_on_clean_convergence and not unverified) else "halt"
    elif action == "exit-unconverged":
        hitl = "halt"

    return {
        "action": action,
        "convergence_unverified": unverified,
        "hitl": hitl,
        "reviewer_this_iter": _reviewer_for(iteration, alternate_models),
        "reviewer_next_iter": _reviewer_for(iteration + 1, alternate_models),
        "clean": clean,
        "converged": converged,
        "reason": reason,
    }


# --------------------------------------------------------------------------- #
# converged
# --------------------------------------------------------------------------- #
def decide_converged(findings: dict) -> dict:
    """The convergence rule ALONE, for the Phase 7 external-change re-review:
    the changes are 'meaningful' (re-open the halt) iff the re-review's
    findings are NOT converged. Same verbatim review_findings.py input as the
    gate; pure. Keeps CONVERGENCE_MAX_FINDINGS out of orchestrator prose."""
    nondef = _findings_int(findings, "open_nondeferred")
    crit_high = _findings_int(findings, "open_crit_high")
    untagged = _findings_int(findings, "open_severity", "untagged")
    converged = _is_converged(nondef, crit_high, untagged)
    return {
        "converged": converged,
        "meaningful": not converged,
        "open_nondeferred": nondef,
        "open_crit_high": crit_high,
        "untagged": untagged,
        "reason": (f"converged ({nondef} non-deferred ≤ {CONVERGENCE_MAX_FINDINGS}, "
                   "0 Critical/High, 0 untagged)" if converged
                   else _nonconvergence_why(nondef, crit_high, untagged)),
    }


# --------------------------------------------------------------------------- #
# post-fix
# --------------------------------------------------------------------------- #
def decide_post_fix(findings: dict, retry_used: bool) -> dict:
    """Verify a fix pass from a post-fix re-run of review_findings.py. Pure."""
    open_patch = _findings_int(findings, "open_patch")
    open_decision = _findings_int(findings, "open_decision")
    met = open_patch == 0 and open_decision == 0
    if met:
        action = "proceed"
        reason = "fix pass verified — no open [Review][Patch] or [Review][Decision] items remain"
    elif not retry_used:
        action = "retry-fix"
        reason = (f"{open_patch} open patch + {open_decision} open decision item(s) remain — "
                  "re-delegate the `code-review fix` entry once on the still-open items "
                  "(the retry does not consume a loop iteration), then re-verify with --retry-used")
    else:
        action = "needs-human"
        reason = (f"{open_patch} open patch + {open_decision} open decision item(s) still remain "
                  "after the one fix retry — the fix delegate is not closing its items")
    return {
        "action": action,
        "open_patch": open_patch,
        "open_decision": open_decision,
        "reason": reason,
    }


# --------------------------------------------------------------------------- #
# CLI plumbing
# --------------------------------------------------------------------------- #
def _parse_bool(value: str) -> bool:
    v = value.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    raise argparse.ArgumentTypeError(f"expected 'true' or 'false', got {value!r}")


def _load_findings(spec: str) -> dict:
    """Read the review_findings.py JSON from a file path or stdin ('-')."""
    if spec == "-":
        raw = sys.stdin.read()
    else:
        with open(spec, "r", encoding="utf-8") as fh:
            raw = fh.read()
    data = json.loads(raw)  # ValueError on bad JSON
    if not isinstance(data, dict):
        raise ValueError("findings JSON must be a single object (review_findings.py output)")
    return data


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
def _f(nondef=0, crit_high=0, untagged=0):
    """A minimal review_findings.py-shaped fixture (only the keys gate reads)."""
    return {
        "open_nondeferred": nondef,
        "open_crit_high": crit_high,
        "open_severity": {"critical": 0, "high": crit_high,
                          "medium": max(0, nondef - crit_high - untagged), "low": 0,
                          "untagged": untagged},
    }


_GATE_KEYS = {"action", "convergence_unverified", "hitl", "reviewer_this_iter",
              "reviewer_next_iter", "clean", "converged", "reason"}
_PREP_KEYS = {"review_tmp", "diff_file", "blind_out", "edge_out", "auditor_out",
              "diff_empty", "base", "head_sha"}
_POST_FIX_KEYS = {"action", "open_patch", "open_decision", "reason"}


def _run_self_test():
    import contextlib
    import io
    import itertools
    import shutil

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    # ---------------- prep-diff: pure argv builders ----------------
    argv = build_diff_argv("main")
    check("argv: git diff three-dot, plain-format pins",
          argv[:5] == ["git", "diff", "--no-ext-diff", "--no-color", "main...HEAD"])
    check("argv: pathspec separator", argv[5] == "--")
    check("argv: all five excludes, in order", tuple(argv[6:]) == EXCLUDE_PATHSPECS)
    check("argv: _bmad excluded", ":(exclude)_bmad" in argv)
    check("argv: _bmad-output excluded", ":(exclude)_bmad-output" in argv)
    check("argv: pycache excluded (glob, root-matching)", ":(exclude,glob)**/__pycache__/**" in argv)
    check("argv: pyc excluded (glob, root-matching)", ":(exclude,glob)**/*.pyc" in argv)
    check("argv: DS_Store excluded (glob, root-matching)", ":(exclude,glob)**/.DS_Store" in argv)
    check("argv: never two-dot", "main..HEAD" not in " ".join(argv).replace("main...HEAD", ""))
    check("argv: head rev-parse", build_head_argv() == ["git", "rev-parse", "HEAD"])

    # ---------------- prep-diff: injectable runner (no repo needed) ----------------
    calls = []

    def fake_runner(diff_bytes):
        def run(argv, cwd):
            calls.append((argv, cwd))
            if argv[:2] == ["git", "rev-parse"]:
                return 0, b"abc123def\n", ""
            return 0, diff_bytes, ""
        return run

    res = prep_diff("/proj", "develop", runner=fake_runner(b"diff --git a/x b/x\n+new\n"))
    check("prep: exact key set", set(res) == _PREP_KEYS)
    check("prep: base echoed", res["base"] == "develop")
    check("prep: head sha trimmed", res["head_sha"] == "abc123def")
    check("prep: non-empty diff flagged", res["diff_empty"] is False)
    check("prep: cwd is project root", all(cwd == "/proj" for _, cwd in calls))
    check("prep: tmp under OS tempdir, not the work tree",
          res["review_tmp"].startswith(tempfile.gettempdir()) and not res["review_tmp"].startswith("/proj"))
    check("prep: diff file inside review_tmp",
          res["diff_file"] == os.path.join(res["review_tmp"], DIFF_FILENAME))
    with open(res["diff_file"], "rb") as fh:
        check("prep: diff bytes written verbatim", fh.read() == b"diff --git a/x b/x\n+new\n")
    for key, name in LENS_FILENAMES:
        check(f"prep: {key} path reserved inside review_tmp",
              res[key] == os.path.join(res["review_tmp"], name))
        check(f"prep: {key} NOT created", not os.path.exists(res[key]))
    shutil.rmtree(res["review_tmp"])

    # Empty diff: file still written (empty), diff_empty true.
    res_e = prep_diff("/proj", "develop", runner=fake_runner(b""))
    check("prep: empty diff flagged", res_e["diff_empty"] is True)
    check("prep: empty diff file written", os.path.getsize(res_e["diff_file"]) == 0)
    shutil.rmtree(res_e["review_tmp"])

    # Git failure: error dict, and no temp dir was created (nothing to leak).
    made = []

    def spy_mkdtemp(prefix):
        made.append(prefix)
        return tempfile.mkdtemp(prefix=prefix)

    def fail_runner(argv, cwd):
        if argv[:2] == ["git", "rev-parse"]:
            return 0, b"abc\n", ""
        return 128, b"", "fatal: bad revision 'nope...HEAD'"

    bad = prep_diff("/proj", "nope", runner=fail_runner, mkdtemp=spy_mkdtemp)
    check("prep: git diff failure => error", bad.get("status") == "error" and "git diff" in bad["message"])
    check("prep: no temp dir on failure", made == [])
    bad2 = prep_diff("/proj", "main",
                     runner=lambda a, c: (128, b"", "fatal: not a git repository"), mkdtemp=spy_mkdtemp)
    check("prep: rev-parse failure => error", bad2.get("status") == "error" and "rev-parse" in bad2["message"])
    check("prep: OSError => error",
          prep_diff("/no/such/dir-xyz", "main").get("status") == "error")

    # ---------------- prep-diff: real temp git repo (git is available) ----------------
    if shutil.which("git"):
        repo = tempfile.mkdtemp(prefix="review_loop_repo_")

        def git(*args):
            subprocess.run(
                ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.com",
                 "-c", "commit.gpgsign=false", *args],
                check=True, capture_output=True)

        def put(rel, text):
            path = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

        git("init", "-q")
        put("a.txt", "base\n")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("branch", "-M", "main")
        git("checkout", "-q", "-b", "feature")
        put("src/b.txt", "needle-line\n")
        put("_bmad/inside.txt", "excluded-bmad-needle\n")
        put("pkg/__pycache__/mod.pyc", "excluded-pyc-needle\n")
        put("pkg/__pycache__/mod.cache", "excluded-pycache-other-needle\n")
        # Root-level junk: under default fnmatch a leading **/ never matched
        # the repo root — these two leaked into the diff before glob magic.
        put(".DS_Store", "excluded-root-dsstore-needle\n")
        put("root.pyc", "excluded-root-pyc-needle\n")
        git("add", "-A", "-f")
        git("commit", "-q", "-m", "feature work")
        # Hostile user diff config: an external diff tool (difftastic-style)
        # and forced color would corrupt the patch unless prep-diff pins the
        # output format with --no-ext-diff --no-color.
        git("config", "diff.external", "echo EXTERNAL-DIFF")
        git("config", "color.diff", "always")

        live = prep_diff(repo, "main")
        check("live: succeeds", live.get("status") != "error")
        if live.get("status") != "error":
            check("live: exact key set", set(live) == _PREP_KEYS)
            check("live: diff not empty", live["diff_empty"] is False)
            with open(live["diff_file"], "r", encoding="utf-8") as fh:
                patch = fh.read()
            check("live: real change in diff", "needle-line" in patch and "src/b.txt" in patch)
            check("live: plain unified diff despite diff.external", patch.startswith("diff --git"))
            check("live: no external-tool output", "EXTERNAL-DIFF" not in patch)
            check("live: no ANSI escapes despite color.diff=always", "\x1b" not in patch)
            check("live: _bmad excluded", "excluded-bmad-needle" not in patch and "_bmad" not in patch)
            check("live: pycache/pyc excluded", "excluded-pyc-needle" not in patch and ".pyc" not in patch)
            check("live: non-pyc files inside __pycache__ excluded",
                  "excluded-pycache-other-needle" not in patch and "__pycache__" not in patch)
            check("live: ROOT-level .DS_Store excluded",
                  "excluded-root-dsstore-needle" not in patch and ".DS_Store" not in patch)
            check("live: ROOT-level .pyc excluded", "excluded-root-pyc-needle" not in patch)
            head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
            check("live: head_sha matches rev-parse", live["head_sha"] == head)
            check("live: tmp outside the work tree", not live["review_tmp"].startswith(repo))
            check("live: lens paths not created",
                  not any(os.path.exists(live[k]) for k, _ in LENS_FILENAMES))
            shutil.rmtree(live["review_tmp"])

        empty = prep_diff(repo, "feature")  # feature...HEAD == nothing
        check("live: same-ref diff is empty", empty.get("status") != "error" and empty["diff_empty"] is True)
        if empty.get("status") != "error":
            shutil.rmtree(empty["review_tmp"])

        broken = prep_diff(repo, "no-such-branch")
        check("live: bad base => error", broken.get("status") == "error")
        # repo is reused by the prep-diff CLI round-trips below, then removed.

    # ---------------- gate: one case per decision-table row ----------------
    # row 1 — all lenses failed: hard stop, sticky flag passes through unchanged.
    o = decide_gate(_f(0), 1, 2, True, 3, False)
    check("row1: needs-human", o["action"] == "needs-human")
    check("row1: hitl null (hard stop)", o["hitl"] is None)
    check("row1: reason names 0/3 lenses", "0/3 lenses produced findings" in o["reason"])
    check("row1: unverified unchanged (false in)", o["convergence_unverified"] is False)
    o = decide_gate(_f(5, 2, 0), 2, 2, True, 3, True, convergence_unverified=True)
    check("row1: unverified unchanged (true in)",
          o["action"] == "needs-human" and o["convergence_unverified"] is True and o["hitl"] is None)

    # row 2 — perfectly clean first pass: the only first-pass early exit.
    o = decide_gate(_f(0), 1, 2, True, 0, True)
    check("row2: exit-clean", o["action"] == "exit-clean")
    check("row2: unverified false", o["convergence_unverified"] is False)
    check("row2: skip-halt when configured", o["hitl"] == "skip-halt")
    check("row2: clean+converged flags", o["clean"] is True and o["converged"] is True)
    o = decide_gate(_f(0), 1, 2, True, 0, False)
    check("row2: halt without skip config", o["action"] == "exit-clean" and o["hitl"] == "halt")
    o = decide_gate(_f(0), 1, 1, False, 0, False)  # max_iterations == 1, perfectly clean
    check("row2: clean single pass at max==1 still exits clean (non-draft)",
          o["action"] == "exit-clean" and o["convergence_unverified"] is False)
    # invariant: empty diff == row 2 (an all-zero findings JSON + 0 failed lenses).
    o = decide_gate(_f(0, 0, 0), 1, 2, False, 0, False)
    check("row2: empty-diff zeros land here", o["action"] == "exit-clean")
    # invariant: a sticky input true forces halt even here — skip gate never fires.
    o = decide_gate(_f(0), 1, 2, True, 0, True, convergence_unverified=True)
    check("row2: sticky true survives", o["convergence_unverified"] is True)
    check("row2: sticky true forces halt despite skip config", o["hitl"] == "halt")

    # row 3 — first pass with findings: mandatory second opinion.
    o = decide_gate(_f(2), 1, 2, True, 0, True)
    check("row3: continue", o["action"] == "continue")
    check("row3: hitl null", o["hitl"] is None)
    check("row3: unverified false", o["convergence_unverified"] is False)
    o = decide_gate(_f(1), 1, 2, False, 0, False)
    check("row3: even a would-converge first pass continues", o["action"] == "continue" and o["converged"] is True)

    # row 4 — first pass with 1–2 failed lenses: untrustworthy even at 0 findings.
    o = decide_gate(_f(0), 1, 2, True, 1, True)
    check("row4: 0-finding pass with a failed lens continues", o["action"] == "continue")
    check("row4: hitl null", o["hitl"] is None)
    check("row4: reason notes 2/3 lenses", "2/3" in o["reason"])
    o = decide_gate(_f(2), 1, 3, False, 2, False)
    check("row4: two failed lenses also continue", o["action"] == "continue")
    check("row4: unverified false", o["convergence_unverified"] is False)

    # row 5 — first pass not perfectly clean at the cap (max_iterations == 1).
    o = decide_gate(_f(1), 1, 1, True, 0, False)
    check("row5: exit-unconverged", o["action"] == "exit-unconverged")
    check("row5: unverified true", o["convergence_unverified"] is True)
    check("row5: halt", o["hitl"] == "halt")
    o = decide_gate(_f(0), 1, 1, True, 1, True)  # clean but a lens failed
    check("row5: missing lens is 'not perfectly clean' at max==1",
          o["action"] == "exit-unconverged" and o["convergence_unverified"] is True)
    check("row5: skip config cannot fire", o["hitl"] == "halt")

    # row 6 — i>=2, converged with all lenses: clean exit.
    o = decide_gate(_f(2), 2, 2, True, 0, True)
    check("row6: exit-clean", o["action"] == "exit-clean")
    check("row6: unverified false", o["convergence_unverified"] is False)
    check("row6: skip-halt when configured", o["hitl"] == "skip-halt")
    o = decide_gate(_f(3), 2, 2, True, 0, False)  # boundary: exactly 3 non-deferred converges
    check("row6: boundary 3 findings converge", o["action"] == "exit-clean" and o["hitl"] == "halt")
    o = decide_gate(_f(2), 2, 2, True, 0, True, convergence_unverified=True)
    check("row6: sticky true forces halt despite skip config",
          o["convergence_unverified"] is True and o["hitl"] == "halt")

    # row 7 — i>=2, converged but a lens missing: unverified exit.
    o = decide_gate(_f(1), 2, 3, True, 1, True)
    check("row7: exit-unconverged", o["action"] == "exit-unconverged")
    check("row7: unverified true", o["convergence_unverified"] is True)
    check("row7: halt (skip config cannot fire)", o["hitl"] == "halt")
    check("row7: reason notes incomplete review 2/3 lenses",
          "incomplete review" in o["reason"] and "2/3" in o["reason"])
    o = decide_gate(_f(0), 2, 2, False, 2, True)
    check("row7: clean-with-2-missing-lenses also unverified",
          o["action"] == "exit-unconverged" and "1/3" in o["reason"])

    # row 8 — i>=2, not converged, below the cap: continue.
    o = decide_gate(_f(5), 2, 3, True, 0, False)
    check("row8: >3 findings continue", o["action"] == "continue" and o["hitl"] is None)
    o = decide_gate(_f(2, 1, 0), 2, 3, True, 0, False)
    check("row8: Critical/High blocks convergence", o["action"] == "continue" and o["converged"] is False)
    o = decide_gate(_f(1, 0, 1), 2, 3, False, 1, False)
    check("row8: untagged blocks convergence (treated as Crit/High)",
          o["action"] == "continue" and o["converged"] is False)
    check("row8: unverified false", o["convergence_unverified"] is False)

    # row 9 — i>=2, not converged, at the cap: unconverged draft exit.
    o = decide_gate(_f(4), 2, 2, True, 0, False)
    check("row9: exit-unconverged", o["action"] == "exit-unconverged")
    check("row9: unverified true + halt", o["convergence_unverified"] is True and o["hitl"] == "halt")
    o = decide_gate(_f(1, 1, 0), 2, 2, True, 2, True)
    check("row9: crit/high at cap with missing lenses",
          o["action"] == "exit-unconverged" and o["hitl"] == "halt")
    # Defensive: an overshoot (i > max) still caps — never continues past the cap.
    o = decide_gate(_f(5), 3, 2, True, 0, False)
    check("row9: overshoot still exits", o["action"] == "exit-unconverged")

    # ---------------- gate: reviewer parity ----------------
    o = decide_gate(_f(0), 1, 2, True, 0, False)
    check("reviewer: iter 1 is always primary", o["reviewer_this_iter"] == PRIMARY_REVIEWER)
    check("reviewer: iter 2 next is secondary when alternating",
          o["reviewer_next_iter"] == SECONDARY_REVIEWER)
    o = decide_gate(_f(5), 2, 3, True, 0, False)
    check("reviewer: even iter is secondary", o["reviewer_this_iter"] == SECONDARY_REVIEWER)
    check("reviewer: iter 3 alternates back to primary", o["reviewer_next_iter"] == PRIMARY_REVIEWER)
    o = decide_gate(_f(5), 2, 3, False, 0, False)
    check("reviewer: alternation off => always primary",
          o["reviewer_this_iter"] == PRIMARY_REVIEWER and o["reviewer_next_iter"] == PRIMARY_REVIEWER)

    # ---------------- gate: invariant sweep ----------------
    findings_variants = [(0, 0, 0), (2, 0, 0), (2, 1, 0), (2, 0, 1), (5, 0, 0)]
    bools = (False, True)
    for (i, m), lf, fv, alt, skip, sticky in itertools.product(
            [(i, m) for i in (1, 2, 3) for m in (1, 2, 3) if i <= m],
            range(4), findings_variants, bools, bools, bools):
        out = decide_gate(_f(*fv), i, m, alt, lf, skip, sticky)
        tag = f"sweep i={i} m={m} lf={lf} f={fv} alt={alt} skip={skip} sticky={sticky}"
        check(f"{tag}: exact key set", set(out) == _GATE_KEYS)
        check(f"{tag}: skip-halt never with unverified true",
              not (out["hitl"] == "skip-halt" and out["convergence_unverified"]))
        check(f"{tag}: hitl null iff continue/needs-human",
              (out["hitl"] is None) == (out["action"] in ("continue", "needs-human")))
        if out["action"] == "exit-unconverged":
            check(f"{tag}: exit-unconverged => unverified + halt",
                  out["convergence_unverified"] is True and out["hitl"] == "halt")
        if sticky:
            check(f"{tag}: sticky flag never cleared", out["convergence_unverified"] is True)
            check(f"{tag}: sticky flag blocks skip-halt", out["hitl"] != "skip-halt")
        if out["action"] == "continue":
            check(f"{tag}: continue only below the cap", i < m)
        if lf >= 3:
            check(f"{tag}: 3 failed lenses is always needs-human", out["action"] == "needs-human")
        if i == 1:
            check(f"{tag}: iter-1 reviewer is primary", out["reviewer_this_iter"] == PRIMARY_REVIEWER)
        expected_this = SECONDARY_REVIEWER if (alt and i % 2 == 0) else PRIMARY_REVIEWER
        expected_next = SECONDARY_REVIEWER if (alt and (i + 1) % 2 == 0) else PRIMARY_REVIEWER
        check(f"{tag}: reviewer parity", out["reviewer_this_iter"] == expected_this
              and out["reviewer_next_iter"] == expected_next)
        json.dumps(out)  # every decision must be JSON-serializable

    # Bad findings JSON shapes raise ValueError (=> exit 2 in main).
    for bad_findings in ({}, {"open_nondeferred": 1}, {"open_nondeferred": 1, "open_crit_high": 0},
                         {"open_nondeferred": "x", "open_crit_high": 0, "open_severity": {"untagged": 0}}):
        try:
            decide_gate(bad_findings, 1, 2, False, 0, False)
            check(f"gate: bad findings {bad_findings!r} must raise", False)
        except ValueError:
            pass

    # ---------------- post-fix ----------------
    pf = decide_post_fix({"open_patch": 0, "open_decision": 0}, retry_used=False)
    check("post-fix: expectation met => proceed", pf["action"] == "proceed")
    check("post-fix: exact key set", set(pf) == _POST_FIX_KEYS)
    check("post-fix: counts echoed", pf["open_patch"] == 0 and pf["open_decision"] == 0)
    pf = decide_post_fix({"open_patch": 0, "open_decision": 0}, retry_used=True)
    check("post-fix: met after retry still proceeds", pf["action"] == "proceed")
    pf = decide_post_fix({"open_patch": 2, "open_decision": 0}, retry_used=False)
    check("post-fix: open patch => retry-fix", pf["action"] == "retry-fix" and pf["open_patch"] == 2)
    pf = decide_post_fix({"open_patch": 0, "open_decision": 1}, retry_used=False)
    check("post-fix: open decision alone => retry-fix", pf["action"] == "retry-fix")
    pf = decide_post_fix({"open_patch": 1, "open_decision": 1}, retry_used=True)
    check("post-fix: unmet after retry => needs-human", pf["action"] == "needs-human")
    try:
        decide_post_fix({"open_patch": 1}, retry_used=False)
        check("post-fix: missing key must raise", False)
    except ValueError:
        pass

    # ---------------- converged (external-change re-review) ----------------
    cv = decide_converged(_f(CONVERGENCE_MAX_FINDINGS))
    check("converged: at the cap converges, not meaningful",
          cv["converged"] is True and cv["meaningful"] is False)
    cv = decide_converged(_f(CONVERGENCE_MAX_FINDINGS + 1))
    check("converged: over the cap is meaningful",
          cv["converged"] is False and cv["meaningful"] is True)
    cv = decide_converged(_f(1, crit_high=1))
    check("converged: any Crit/High is meaningful", cv["meaningful"] is True)
    cv = decide_converged(_f(1, untagged=1))
    check("converged: untagged treated as Crit/High", cv["meaningful"] is True
          and "untagged" in cv["reason"])
    check("converged: same rule as the gate",
          decide_converged(_f(2))["converged"]
          == decide_gate(_f(2), 2, 3, False, 0, False)["converged"])
    try:
        decide_converged({"open_nondeferred": 1})
        check("converged: missing key must raise", False)
    except ValueError:
        pass

    # ---------------- main(): CLI round-trips (stdout JSON + exit codes) ----------------
    def run_main(argv, stdin_text=None):
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    rc = main(argv)
                except SystemExit as exc:  # argparse usage errors
                    rc = exc.code
        finally:
            sys.stdin = old_stdin
        return rc, out.getvalue()

    gate_args = ["gate", "--iteration", "1", "--max-iterations", "2",
                 "--alternate-models", "true", "--lenses-failed", "0",
                 "--skip-hitl-on-clean-convergence", "false"]
    rc, out = run_main(gate_args + ["--findings-json", "-"], stdin_text=json.dumps(_f(0)))
    check("cli: gate via stdin exits 0", rc == 0)
    check("cli: gate stdin decision", json.loads(out)["action"] == "exit-clean")

    ftmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    ftmp.write(json.dumps(_f(4)))
    ftmp.close()
    rc, out = run_main(["gate", "--findings-json", ftmp.name, "--iteration", "2",
                        "--max-iterations", "2", "--alternate-models", "false",
                        "--lenses-failed", "0", "--skip-hitl-on-clean-convergence", "true",
                        "--convergence-unverified", "false"])
    parsed = json.loads(out)
    check("cli: gate via file exits 0 (decision IS the result)", rc == 0)
    check("cli: gate file decision row 9", parsed["action"] == "exit-unconverged" and parsed["hitl"] == "halt")
    os.unlink(ftmp.name)

    rc, out = run_main(gate_args + ["--findings-json", "-"], stdin_text="not json{")
    check("cli: bad JSON exits 2", rc == 2)
    check("cli: bad JSON reports error", json.loads(out).get("status") == "error")
    rc, _ = run_main(["gate", "--findings-json", "/no/such/findings.json"] + gate_args[1:])
    check("cli: missing args usage exit 2 or file error 2", rc == 2)
    rc, _ = run_main(gate_args[:1] + ["--findings-json", "-", "--iteration", "0",
                                      "--max-iterations", "2", "--alternate-models", "true",
                                      "--lenses-failed", "0",
                                      "--skip-hitl-on-clean-convergence", "false"])
    check("cli: iteration < 1 is usage error", rc == 2)
    rc, _ = run_main(gate_args[:1] + ["--findings-json", "-", "--iteration", "1",
                                      "--max-iterations", "2", "--alternate-models", "true",
                                      "--lenses-failed", "4",
                                      "--skip-hitl-on-clean-convergence", "false"])
    check("cli: lenses-failed > 3 is usage error", rc == 2)
    rc, _ = run_main(gate_args[:1] + ["--findings-json", "-", "--iteration", "1",
                                      "--max-iterations", "2", "--alternate-models", "yes",
                                      "--lenses-failed", "0",
                                      "--skip-hitl-on-clean-convergence", "false"])
    check("cli: non-true/false bool is usage error", rc == 2)

    rc, out = run_main(["post-fix", "--findings-json", "-"],
                       stdin_text=json.dumps({"open_patch": 1, "open_decision": 0}))
    check("cli: post-fix exits 0", rc == 0)
    check("cli: post-fix retry-fix", json.loads(out)["action"] == "retry-fix")
    rc, out = run_main(["converged", "--findings-json", "-"],
                       stdin_text=json.dumps(_f(4)))
    check("cli: converged exits 0, meaningful", rc == 0 and json.loads(out)["meaningful"] is True)
    rc, out = run_main(["post-fix", "--findings-json", "-", "--retry-used"],
                       stdin_text=json.dumps({"open_patch": 1, "open_decision": 0}))
    check("cli: post-fix --retry-used => needs-human", json.loads(out)["action"] == "needs-human" and rc == 0)
    # prep-diff round-trips: success (live repo) exits 0 with the full
    # contract; a failed prep (error dict) maps to exit 2.
    if shutil.which("git"):
        rc, out = run_main(["prep-diff", "--project-root", repo, "--base", "main"])
        parsed = json.loads(out)
        check("cli: prep-diff exits 0", rc == 0)
        check("cli: prep-diff exact key set", set(parsed) == _PREP_KEYS)
        check("cli: prep-diff diff not empty", parsed["diff_empty"] is False)
        shutil.rmtree(parsed["review_tmp"])
        rc, out = run_main(["prep-diff", "--project-root", repo, "--base", "no-such-branch"])
        check("cli: prep-diff bad base exits 2", rc == 2)
        check("cli: prep-diff bad base reports error", json.loads(out).get("status") == "error")
        shutil.rmtree(repo)
    rc, out = run_main(["prep-diff", "--project-root", "/no/such/dir-xyz", "--base", "main"])
    check("cli: prep-diff bad project root exits 2", rc == 2)
    check("cli: prep-diff bad project root reports error", json.loads(out).get("status") == "error")
    rc, _ = run_main(["prep-diff", "--base", "main"])
    check("cli: prep-diff missing --project-root is usage error", rc == 2)

    rc, _ = run_main([])
    check("cli: no mode is usage error", rc == 2)

    if failures:
        print("SELF-TEST FAILED:", ", ".join(failures), file=sys.stderr)
        return 1
    print("SELF-TEST PASSED (all assertions)")
    return 0


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(description="auto-bmad Phase 7 code-review loop driver")
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures and exit")
    sub = parser.add_subparsers(dest="mode")

    p_diff = sub.add_parser("prep-diff", help="build the review diff in a temp dir outside the work tree")
    p_diff.add_argument("--project-root", required=True, help="the git work tree to diff")
    p_diff.add_argument("--base", required=True, help="git.base_branch — diffed as <base>...HEAD")

    p_gate = sub.add_parser("gate", help="decide continue/exit/halt from a pass's reconciled findings")
    p_gate.add_argument("--findings-json", required=True,
                        help="review_findings.py JSON: a file path, or '-' for stdin")
    p_gate.add_argument("--iteration", type=int, required=True, help="1-based review iteration i")
    p_gate.add_argument("--max-iterations", type=int, required=True, help="code_review.max_iterations")
    p_gate.add_argument("--alternate-models", type=_parse_bool, required=True,
                        metavar="true|false", help="code_review.alternate_models")
    p_gate.add_argument("--lenses-failed", type=int, required=True,
                        help="how many of the 3 review lenses failed or returned empty (0..3)")
    p_gate.add_argument("--skip-hitl-on-clean-convergence", type=_parse_bool, required=True,
                        metavar="true|false", help="code_review.skip_hitl_on_clean_convergence")
    p_gate.add_argument("--convergence-unverified", type=_parse_bool, default=False,
                        metavar="true|false",
                        help="pre-existing sticky flag from state; the gate can set but never clear it")

    p_fix = sub.add_parser("post-fix", help="verify a fix delegate's work from a post-fix findings re-run")
    p_fix.add_argument("--findings-json", required=True,
                       help="POST-FIX review_findings.py JSON: a file path, or '-' for stdin")
    p_fix.add_argument("--retry-used", action="store_true",
                       help="the one fix retry already ran — an unmet expectation is now needs-human")

    p_conv = sub.add_parser("converged", help="the convergence rule alone — external-change "
                                              "re-review ('meaningful' = NOT converged)")
    p_conv.add_argument("--findings-json", required=True,
                        help="review_findings.py JSON of the re-review: a file path, or '-' for stdin")

    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()
    if not args.mode:
        parser.error("a mode is required: prep-diff | gate | post-fix | converged (or use --self-test)")

    if args.mode == "prep-diff":
        result = prep_diff(args.project_root, args.base)
        print(json.dumps(result, indent=2))
        return 2 if result.get("status") == "error" else 0

    if args.mode == "gate":
        if args.iteration < 1:
            parser.error("--iteration must be >= 1")
        if args.max_iterations < 1:
            parser.error("--max-iterations must be >= 1")
        if not 0 <= args.lenses_failed <= TOTAL_LENSES:
            parser.error(f"--lenses-failed must be 0..{TOTAL_LENSES}")
        try:
            findings = _load_findings(args.findings_json)
            result = decide_gate(
                findings, args.iteration, args.max_iterations, args.alternate_models,
                args.lenses_failed, args.skip_hitl_on_clean_convergence,
                args.convergence_unverified,
            )
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "error", "message": str(exc)}))
            return 2
        print(json.dumps(result, indent=2))
        return 0

    # post-fix / converged (same findings-JSON plumbing)
    try:
        findings = _load_findings(args.findings_json)
        result = (decide_converged(findings) if args.mode == "converged"
                  else decide_post_fix(findings, args.retry_used))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
