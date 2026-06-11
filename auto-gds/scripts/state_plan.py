#!/usr/bin/env python3
"""Deterministic auto-gds state-file reader for the orchestrator.

Replaces the resume-detection shell the orchestrator used to improvise (raw
``for f in story-*.yaml`` glob loops, which both misname the files — state files
are ``{key}.yaml`` with no ``story-`` prefix — and abort under zsh/fish on an
unmatched glob). This script enumerates ``{state-dir}/*.yaml`` and reports which
auto-gds pipelines are still in flight (``status != done``), so the orchestrator
calls a tool instead of writing shell.

Two modes, both emitting a single JSON object on stdout:

* **scan** (default): list every state file with its status, the in-flight ones
  (most-recently-updated first), and the resume ``target`` (the first in-flight
  story — finish in-flight work before starting anything new).
* **story** (``--story-key KEY``): check one exact ``{KEY}.yaml`` by path — never
  a glob — and report whether it exists and should be resumed (``status != done``).

Dependency-free: state files are flat ``key: value`` YAML, so the few top-level
scalars we need (``status``, ``updated_at``) are read line by line. In-flight
ordering uses ``updated_at`` (ISO-8601, sorts chronologically) with filesystem
mtime as a tiebreaker.

Usage:
    state_plan.py --state-dir DIR
    state_plan.py --state-dir DIR --story-key 1-3-user-auth
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
    parser = argparse.ArgumentParser(description="auto-gds state-file reader")
    parser.add_argument("--state-dir", help="the {output_folder}/auto-gds/state directory")
    parser.add_argument("--story-key", help="check one exact {key}.yaml instead of scanning all")
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()

    if not args.state_dir:
        parser.error("--state-dir is required (or use --self-test)")

    result = build_result(args.state_dir, args.story_key)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
