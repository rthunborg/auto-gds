#!/usr/bin/env python3
"""Deterministic auto-bmad state-file reader for the orchestrator.

Replaces the resume-detection shell the orchestrator used to improvise (raw
``for f in story-*.yaml`` glob loops, which both misname the files — state files
are ``{key}.yaml`` with no ``story-`` prefix — and abort under zsh/fish on an
unmatched glob). This script enumerates ``{state-dir}/*.yaml`` and reports which
auto-bmad pipelines are still in flight (``status != done``), so the orchestrator
calls a tool instead of writing shell.

Three modes, all emitting a single JSON object on stdout:

* **scan** (default): list every state file with its status, the in-flight ones
  (most-recently-updated first), and the resume ``target`` (the first in-flight
  story — finish in-flight work before starting anything new).
* **story** (``--story-key KEY``): check one exact ``{KEY}.yaml`` by path — never
  a glob — and report whether it exists and should be resumed (``status != done``).
* **finalize** (``--story-key KEY --finalize``): evaluate the Phase 9 draft
  predicate (``git-and-pr.md`` → "PR") from the story's state file. The four
  clauses: ``blockers`` non-empty; ``convergence_unverified`` true;
  ``gate_decision`` is ``WAIVED``; ``ci_status`` in {failed, timeout}
  (case-insensitive, like the sibling clauses).
  ``ci_status`` comes from ``--ci-status`` when given (the live post-CI-wait
  value), else from the state file, else ``unknown`` — ``passed``/``none``/
  ``unknown`` do NOT fire clause 4 (``unknown`` means the wait never ran).
  Verdict: ``draft`` = any clause fired (then forced false by ``--no-pr-draft``,
  which changes ONLY ``draft``); ``clean_completion`` = no clause fired (never
  affected by ``--no-pr-draft``); ``flip_bmad_status`` = ``clean_completion``;
  ``reasons`` names each firing clause. Exit 0 = verdict delivered (draft or
  not), 1 = state file missing, 2 = usage errors.

Dependency-free: state files are flat ``key: value`` YAML, so the few top-level
scalars we need (``status``, ``updated_at``) are read line by line — the
finalize mode additionally reads the ``blockers`` list (inline ``[]`` or block
items) and the ``convergence_unverified`` / ``gate_decision`` / ``ci_status``
scalars. In-flight ordering uses ``updated_at`` (ISO-8601, sorts
chronologically) with filesystem mtime as a tiebreaker.

Usage:
    state_plan.py --state-dir DIR
    state_plan.py --state-dir DIR --story-key 1-3-user-auth
    state_plan.py --state-dir DIR --story-key 1-3-user-auth --finalize \\
        [--ci-status passed|failed|timeout|none|unknown] [--no-pr-draft]
    state_plan.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Top-level scalar fields (no leading indentation), value optionally quoted and
# optionally trailed by a comment.
_SCALAR_RE = {
    "status": re.compile(r"^status:\s*(.*?)\s*(?:#.*)?$"),
    "updated_at": re.compile(r"^updated_at:\s*(.*?)\s*(?:#.*)?$"),
}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_state_file(path: str):
    """Return {status, updated_at} read from a flat state YAML (values may be None)."""
    fields: "dict[str, str | None]" = {"status": None, "updated_at": None}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                for name, pat in _SCALAR_RE.items():
                    if fields[name] is None:
                        m = pat.match(line)
                        if m:
                            val = _unquote(m.group(1))
                            fields[name] = val or None
                if all(v is not None for v in fields.values()):
                    break
    except OSError:
        pass
    return fields


def _story_record(state_dir: str, filename: str):
    path = os.path.join(state_dir, filename)
    fields = read_state_file(path)
    status = fields["status"]
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    return {
        "story_key": filename[: -len(".yaml")],
        "status": status,
        "done": status == "done",
        "updated_at": fields["updated_at"],
        "file": path,
        "_mtime": mtime,  # internal sort tiebreaker; stripped before output
    }


def _scan(state_dir: str):
    result = {
        "mode": "scan",
        "state_dir": state_dir,
        "state_dir_exists": os.path.isdir(state_dir),
        "stories": [],
        "in_flight": [],
        "in_flight_count": 0,
        "target": None,
        "target_status": None,
        "extra_in_flight": [],
        "resume": False,
    }
    if not result["state_dir_exists"]:
        return result

    records = []
    for name in os.listdir(state_dir):
        if name.endswith(".yaml") and os.path.isfile(os.path.join(state_dir, name)):
            records.append(_story_record(state_dir, name))

    # Most-recently-updated first: ISO updated_at (missing sorts last), mtime tiebreak.
    records.sort(key=lambda r: (r["updated_at"] or "", r["_mtime"]), reverse=True)

    in_flight = [r for r in records if not r["done"]]
    result["stories"] = [_public(r) for r in records]
    result["in_flight"] = [_public(r) for r in in_flight]
    result["in_flight_count"] = len(in_flight)
    if in_flight:
        result["target"] = in_flight[0]["story_key"]
        result["target_status"] = in_flight[0]["status"]
        result["extra_in_flight"] = [r["story_key"] for r in in_flight[1:]]
        result["resume"] = True
    return result


def _story(state_dir: str, story_key: str):
    path = os.path.join(state_dir, story_key + ".yaml")
    exists = os.path.isfile(path)
    status = read_state_file(path)["status"] if exists else None
    return {
        "mode": "story",
        "state_dir": state_dir,
        "story_key": story_key,
        "file": path,
        "exists": exists,
        "status": status,
        "resume": exists and status != "done",
    }


def _public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def build_result(state_dir: str, story_key=None):
    return _story(state_dir, story_key) if story_key else _scan(state_dir)


# --------------------------------------------------------------------------- #
# --finalize: the Phase 9 draft-predicate / clean-completion evaluator
# (git-and-pr.md -> "PR"; the four clauses are the normative definition).
# --------------------------------------------------------------------------- #
_FINALIZE_SCALAR_RE = {
    "convergence_unverified": re.compile(r"^convergence_unverified:\s*(.*?)\s*(?:#.*)?$"),
    "gate_decision": re.compile(r"^gate_decision:\s*(.*?)\s*(?:#.*)?$"),
    "ci_status": re.compile(r"^ci_status:\s*(.*?)\s*(?:#.*)?$"),
}
_BLOCKERS_RE = re.compile(r"^blockers:\s*(.*?)\s*(?:#.*)?$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.*?)\s*(?:#.*)?$")

# ci_status values that fire clause 4 (matched case-insensitively, like the
# sibling clauses). passed/none/unknown do NOT — `unknown` means the CI wait
# never ran (offer_merge off / skip merge-prompt override).
_CI_FIRES = ("failed", "timeout")


def _scalar_or_none(value: str):
    value = _unquote(value)
    return None if value.lower() in ("", "null", "~") else value


def read_finalize_fields(path: str):
    """Read the draft-predicate inputs from a flat state YAML: the ``blockers``
    list (inline ``[...]`` or block ``- item`` form) plus the
    ``convergence_unverified`` / ``gate_decision`` / ``ci_status`` scalars."""
    fields = {"convergence_unverified": None, "gate_decision": None, "ci_status": None}
    blockers: "list[str]" = []
    in_blockers = False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        if in_blockers:
            m = _LIST_ITEM_RE.match(line)
            if m:
                item = _unquote(m.group(1))
                if item:
                    blockers.append(item)
                continue
            if not line.strip() or line.strip().startswith("#"):
                continue
            in_blockers = False  # block ended; fall through to this line
        bm = _BLOCKERS_RE.match(line)
        if bm:
            val = bm.group(1).strip()
            if val.startswith("["):
                inner = val.strip("[]").strip()
                if inner:
                    blockers.extend(p for p in (_unquote(x.strip()) for x in inner.split(",")) if p)
            elif not val:
                in_blockers = True  # block-list form: items follow
            else:
                scalar = _scalar_or_none(val)
                if scalar is not None:
                    blockers.append(scalar)  # unexpected scalar; count it
            continue
        for name, pat in _FINALIZE_SCALAR_RE.items():
            if fields[name] is None:
                m = pat.match(line)
                if m:
                    fields[name] = _scalar_or_none(m.group(1))
    fields["blockers"] = blockers
    return fields


def build_finalize_result(state_dir: str, story_key: str, ci_status=None, no_pr_draft=False):
    """Evaluate the draft predicate for one story. Returns (result, exit_code):
    0 = verdict delivered (draft or not), 1 = state file missing."""
    path = os.path.join(state_dir, story_key + ".yaml")
    result = {
        "mode": "finalize",
        "state_dir": state_dir,
        "story_key": story_key,
        "file": path,
        "blockers": [],
        "blocker_count": 0,
        "gate_decision": None,
        "ci_status": None,
        "ci_status_source": None,
        "no_pr_draft": bool(no_pr_draft),
        "clauses": {
            "blocker": False,
            "convergence_unverified": False,
            "gate_waived": False,
            "ci_failed_or_timeout": False,
        },
        "draft": False,
        "clean_completion": False,
        "flip_bmad_status": False,
        "reasons": [],
        "error": None,
    }
    if not os.path.isfile(path):
        result["error"] = f"state file not found: {path}"
        return result, 1

    fields = read_finalize_fields(path)
    blockers = fields["blockers"]
    gate = fields["gate_decision"]

    # Live --ci-status (post-CI-wait) wins; else the state file; else unknown.
    if ci_status:
        ci, ci_source = ci_status, "arg"
    elif fields["ci_status"]:
        ci, ci_source = fields["ci_status"], "state"
    else:
        ci, ci_source = "unknown", "default"

    clauses = {
        "blocker": len(blockers) > 0,
        "convergence_unverified": (fields["convergence_unverified"] or "").lower() == "true",
        "gate_waived": (gate or "").upper() == "WAIVED",
        "ci_failed_or_timeout": ci.lower() in _CI_FIRES,
    }
    any_clause = any(clauses.values())

    reasons = []
    if clauses["blocker"]:
        reasons.append(f"{len(blockers)} blocker(s) recorded")
    if clauses["convergence_unverified"]:
        reasons.append("convergence_unverified is true (review loop never verifiably converged, or review was skipped)")
    if clauses["gate_waived"]:
        reasons.append("gate_decision is WAIVED (epic trace gate shipped despite coverage gaps)")
    if clauses["ci_failed_or_timeout"]:
        reasons.append(f"ci_status is '{ci}' (CI failed or timed out)")

    result.update(
        {
            "blockers": blockers,
            "blocker_count": len(blockers),
            "gate_decision": gate,
            "ci_status": ci,
            "ci_status_source": ci_source,
            "clauses": clauses,
            # --no-pr-draft forces ONLY draft to false (overrides.md): the PR
            # ships non-draft, but the completion is still caveated.
            "draft": any_clause and not no_pr_draft,
            "clean_completion": not any_clause,
            "flip_bmad_status": not any_clause,
            "reasons": reasons,
        }
    )
    return result, 0


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
def _run_self_test():
    import tempfile

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    tmp = tempfile.mkdtemp(prefix="state_plan_")
    state_dir = os.path.join(tmp, "state")
    os.makedirs(state_dir)

    def write(name, body):
        with open(os.path.join(state_dir, name), "w", encoding="utf-8") as fh:
            fh.write(body)

    write("1-1-user-auth.yaml", 'story_key: 1-1-user-auth\nstatus: done\nupdated_at: "2026-05-20T08:00:00Z"\n')
    write("1-2-account-mgmt.yaml", 'story_key: 1-2-account-mgmt\nstatus: in-progress  # mid-review\nupdated_at: "2026-05-22T10:00:00Z"\n')
    write("1-3-plant-model.yaml", "story_key: 1-3-plant-model\nstatus: in-progress\nupdated_at: '2026-05-23T09:00:00Z'\n")
    write("malformed.yaml", "story_key: malformed\n# no status line at all\n")
    write("notes.txt", "not a state file\n")

    scan = build_result(state_dir)
    check("scan: state_dir_exists", scan["state_dir_exists"] is True)
    check("scan: counts yaml only (4)", len(scan["stories"]) == 4)
    check("scan: in_flight excludes done", scan["in_flight_count"] == 3)
    check("scan: resume true", scan["resume"] is True)
    check("scan: target most-recent updated_at (1-3)", scan["target"] == "1-3-plant-model")
    check("scan: target_status carried", scan["target_status"] == "in-progress")
    check("scan: extras are the other in-flight", set(scan["extra_in_flight"]) == {"1-2-account-mgmt", "malformed"})
    check("scan: in_flight order most-recent-first", [s["story_key"] for s in scan["in_flight"]][:2] == ["1-3-plant-model", "1-2-account-mgmt"])
    check("scan: done story flagged done", any(s["done"] and s["story_key"] == "1-1-user-auth" for s in scan["stories"]))
    check("scan: inline comment stripped from status", any(s["story_key"] == "1-2-account-mgmt" and s["status"] == "in-progress" for s in scan["stories"]))
    check("scan: malformed has null status", any(s["story_key"] == "malformed" and s["status"] is None for s in scan["stories"]))
    check("scan: no internal mtime leaks to output", all(not any(k.startswith("_") for k in s) for s in scan["stories"]))

    # Story mode: exact-path lookup, no glob.
    done = build_result(state_dir, "1-1-user-auth")
    check("story: done exists", done["exists"] is True)
    check("story: done status", done["status"] == "done")
    check("story: done not resumed", done["resume"] is False)

    live = build_result(state_dir, "1-2-account-mgmt")
    check("story: in-progress resumed", live["resume"] is True)
    check("story: in-progress status", live["status"] == "in-progress")

    missing = build_result(state_dir, "9-9-nope")
    check("story: missing not exists", missing["exists"] is False)
    check("story: missing status null", missing["status"] is None)
    check("story: missing not resumed", missing["resume"] is False)

    # Absent state dir (first run): empty, no resume, exit 0.
    empty = build_result(os.path.join(tmp, "does-not-exist"))
    check("scan: absent dir not exists", empty["state_dir_exists"] is False)
    check("scan: absent dir no resume", empty["resume"] is False)
    check("scan: absent dir zero in-flight", empty["in_flight_count"] == 0)

    # ---- finalize mode ---------------------------------------------------- #
    fin_dir = os.path.join(tmp, "fin")
    os.makedirs(fin_dir)

    def write_fin(key, **over):
        body = {
            "convergence_unverified": "false",
            "gate_decision": "null",
            "ci_status": "passed",
            "blockers": "[]",
        }
        body.update(over)
        lines = [f"story_key: {key}", "status: done", 'updated_at: "2026-06-01T10:00:00Z"']
        for k in ("convergence_unverified", "gate_decision", "ci_status"):
            lines.append(f"{k}: {body[k]}")
        if body["blockers"] is None:  # block-list form
            lines.append("blockers:")
            lines.append('  - "rotate the API key manually"')
            lines.append("  - second item  # urgent")
        else:
            lines.append(f"blockers: {body['blockers']}")
        lines.append("open_questions: []")
        with open(os.path.join(fin_dir, key + ".yaml"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    # No clauses: clean completion, flip, no draft, no reasons.
    write_fin("2-1-clean")
    res, code = build_finalize_result(fin_dir, "2-1-clean")
    check("finalize clean: exit 0", code == 0)
    check("finalize clean: no clause fires", not any(res["clauses"].values()))
    check("finalize clean: not draft", res["draft"] is False)
    check("finalize clean: clean_completion", res["clean_completion"] is True)
    check("finalize clean: flip_bmad_status", res["flip_bmad_status"] is True)
    check("finalize clean: no reasons", res["reasons"] == [])
    check("finalize clean: ci from state", res["ci_status"] == "passed" and res["ci_status_source"] == "state")

    # Clause 1 — blockers (block-list form, comment stripped, items counted).
    write_fin("2-2-blocked", blockers=None)
    res, code = build_finalize_result(fin_dir, "2-2-blocked")
    check("finalize blocker: exit 0 (verdict delivered)", code == 0)
    check("finalize blocker: clause fires alone", res["clauses"] == {"blocker": True, "convergence_unverified": False, "gate_waived": False, "ci_failed_or_timeout": False})
    check("finalize blocker: count 2", res["blocker_count"] == 2 and res["blockers"][0] == "rotate the API key manually")
    check("finalize blocker: draft", res["draft"] is True)
    check("finalize blocker: not clean", res["clean_completion"] is False and res["flip_bmad_status"] is False)
    check("finalize blocker: one reason", len(res["reasons"]) == 1 and "blocker" in res["reasons"][0])

    # Clause 1 — inline flow list also counts.
    write_fin("2-2b-inline", blockers='["needs db migration", manual deploy]')
    res, _ = build_finalize_result(fin_dir, "2-2b-inline")
    check("finalize inline blockers: count 2", res["blocker_count"] == 2)
    check("finalize inline blockers: draft", res["draft"] is True)

    # Clause 2 — convergence_unverified.
    write_fin("2-3-unverified", convergence_unverified="true")
    res, _ = build_finalize_result(fin_dir, "2-3-unverified")
    check("finalize unverified: clause fires alone", res["clauses"] == {"blocker": False, "convergence_unverified": True, "gate_waived": False, "ci_failed_or_timeout": False})
    check("finalize unverified: draft, not clean", res["draft"] is True and res["clean_completion"] is False)

    # Clause 3 — gate WAIVED.
    write_fin("2-4-waived", gate_decision="WAIVED")
    res, _ = build_finalize_result(fin_dir, "2-4-waived")
    check("finalize waived: clause fires alone", res["clauses"] == {"blocker": False, "convergence_unverified": False, "gate_waived": True, "ci_failed_or_timeout": False})
    check("finalize waived: gate_decision carried", res["gate_decision"] == "WAIVED")
    check("finalize waived: draft, no flip", res["draft"] is True and res["flip_bmad_status"] is False)

    # Clause 3 negative — PASS does not fire.
    write_fin("2-4b-pass", gate_decision="PASS")
    res, _ = build_finalize_result(fin_dir, "2-4b-pass")
    check("finalize gate PASS: clean", res["clean_completion"] is True)

    # Clause 4 — a hand-edited uppercase state value still fires (normalized
    # like the sibling clauses).
    write_fin("2-5a-upper", ci_status="FAILED")
    res, _ = build_finalize_result(fin_dir, "2-5a-upper")
    check("finalize ci FAILED uppercase: fires", res["clauses"]["ci_failed_or_timeout"] is True)
    check("finalize ci FAILED uppercase: draft, not clean", res["draft"] is True and res["clean_completion"] is False)

    # Clause 4 — ci_status from the state file (timeout).
    write_fin("2-5-timeout", ci_status="timeout")
    res, _ = build_finalize_result(fin_dir, "2-5-timeout")
    check("finalize ci timeout: clause fires alone", res["clauses"] == {"blocker": False, "convergence_unverified": False, "gate_waived": False, "ci_failed_or_timeout": True})
    check("finalize ci timeout: draft", res["draft"] is True)

    # Clause 4 — live --ci-status wins over the state file (both directions).
    res, _ = build_finalize_result(fin_dir, "2-1-clean", ci_status="failed")
    check("finalize ci arg failed: fires over passed state", res["clauses"]["ci_failed_or_timeout"] is True and res["ci_status_source"] == "arg")
    write_fin("2-6-stale-failed", ci_status="failed")
    res, _ = build_finalize_result(fin_dir, "2-6-stale-failed", ci_status="passed")
    check("finalize ci arg passed: clears stale failed state", res["clauses"]["ci_failed_or_timeout"] is False and res["clean_completion"] is True)

    # Clause 4 negatives — unknown (wait never ran) and none do NOT fire.
    write_fin("2-7-unknown", ci_status="unknown")
    res, _ = build_finalize_result(fin_dir, "2-7-unknown")
    check("finalize ci unknown: does not fire", res["clauses"]["ci_failed_or_timeout"] is False and res["clean_completion"] is True)
    with open(os.path.join(fin_dir, "2-8-no-ci.yaml"), "w", encoding="utf-8") as fh:
        fh.write("story_key: 2-8-no-ci\nstatus: done\nblockers: []\nconvergence_unverified: false\ngate_decision: null\n")
    res, _ = build_finalize_result(fin_dir, "2-8-no-ci")
    check("finalize ci absent: defaults unknown, no fire", res["ci_status"] == "unknown" and res["ci_status_source"] == "default" and res["clean_completion"] is True)
    res, _ = build_finalize_result(fin_dir, "2-1-clean", ci_status="none")
    check("finalize ci none: does not fire", res["clauses"]["ci_failed_or_timeout"] is False)

    # --no-pr-draft: forces draft false ONLY; clean_completion/flip unaffected.
    res, code = build_finalize_result(fin_dir, "2-2-blocked", no_pr_draft=True)
    check("finalize no-pr-draft: exit 0", code == 0)
    check("finalize no-pr-draft: draft forced false", res["draft"] is False)
    check("finalize no-pr-draft: still not clean", res["clean_completion"] is False and res["flip_bmad_status"] is False)
    check("finalize no-pr-draft: clause + reason still reported", res["clauses"]["blocker"] is True and len(res["reasons"]) == 1)
    res, _ = build_finalize_result(fin_dir, "2-1-clean", no_pr_draft=True)
    check("finalize no-pr-draft on clean: unchanged", res["draft"] is False and res["clean_completion"] is True)

    # Missing state file => exit 1.
    res, code = build_finalize_result(fin_dir, "9-9-nope")
    check("finalize missing: exit 1", code == 1)
    check("finalize missing: error set", bool(res["error"]))

    for name in os.listdir(fin_dir):
        os.unlink(os.path.join(fin_dir, name))
    os.rmdir(fin_dir)
    for name in os.listdir(state_dir):
        os.unlink(os.path.join(state_dir, name))
    os.rmdir(state_dir)
    os.rmdir(tmp)

    if failures:
        print("SELF-TEST FAILED:", ", ".join(failures), file=sys.stderr)
        return 1
    print("SELF-TEST PASSED (all assertions)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="auto-bmad state-file reader")
    parser.add_argument("--state-dir", help="the {output_folder}/auto-bmad/state directory")
    parser.add_argument("--story-key", help="check one exact {key}.yaml instead of scanning all")
    parser.add_argument("--finalize", action="store_true", help="evaluate the Phase 9 draft predicate / clean-completion verdict for --story-key")
    parser.add_argument("--ci-status", choices=["passed", "failed", "timeout", "none", "unknown"], help="with --finalize: the live post-CI-wait value (overrides the state file)")
    parser.add_argument("--no-pr-draft", action="store_true", help="with --finalize: the no_pr_draft override — forces draft=false, never touches clean_completion")
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()

    if not args.state_dir:
        parser.error("--state-dir is required (or use --self-test)")

    if args.finalize:
        if not args.story_key:
            parser.error("--finalize requires --story-key")
        result, code = build_finalize_result(args.state_dir, args.story_key, args.ci_status, args.no_pr_draft)
        print(json.dumps(result, indent=2))
        return code
    if args.ci_status or args.no_pr_draft:
        parser.error("--ci-status/--no-pr-draft are only valid with --finalize")

    result = build_result(args.state_dir, args.story_key)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
