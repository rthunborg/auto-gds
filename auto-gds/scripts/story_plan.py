#!/usr/bin/env python3
"""Deterministic GDS sprint-status reader for the auto-gds orchestrator.

Parses a GDS/BMGD ``sprint-status.yaml`` and decides which story the pipeline should
work next (or inspects a story passed explicitly), including the epic-boundary
facts the orchestrator needs (first/last story of an epic, retrospective state).

Output is a single JSON object on stdout so the orchestrator never has to parse
YAML with an LLM. Dependency-free: the ``development_status`` block is a flat
``key: value`` map, so we read it line by line and preserve file order.

Usage:
    story_plan.py --sprint-status PATH [--story 1-3|1-3-slug] [--impl-dir DIR]
    story_plan.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

EPIC_RE = re.compile(r"^epic-(\d+)$")
RETRO_RE = re.compile(r"^epic-(\d+)-retrospective$")
STORY_RE = re.compile(r"^(\d+)-(\d+)-(.+)$")

# Legacy status aliases the BMAD framework still honours.
STATUS_ALIASES = {"drafted": "ready-for-dev", "contexted": "in-progress"}

# Story status -> the GDS/BMGD action that advances it.
ACTION_FOR_STATUS = {
    "backlog": "create-story",
    "ready-for-dev": "dev-story",
    "in-progress": "dev-story",
    "review": "code-review",
    "done": "done",
}


def parse_development_status(text: str):
    """Return an ordered list of (key, status) from the development_status block."""
    entries = []
    in_block = False
    block_indent = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not in_block:
            if stripped == "development_status:" or re.match(r"^development_status:\s*$", raw):
                in_block = True
            continue
        # Inside the block.
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if block_indent is None:
            block_indent = indent
        # A line dedented back to column 0 (or below block indent) ends the block.
        if indent < block_indent or indent == 0:
            break
        m = re.match(r"^\s*([^:#]+?):\s*([^#]*?)\s*(?:#.*)?$", raw)
        if not m:
            continue
        key, value = m.group(1).strip(), m.group(2).strip()
        if not value:
            continue
        entries.append((key, STATUS_ALIASES.get(value, value)))
    return entries


def classify(entries):
    epics, stories, retros = {}, [], {}
    for key, status in entries:
        em = EPIC_RE.match(key)
        rm = RETRO_RE.match(key)
        sm = STORY_RE.match(key)
        if rm:
            retros[int(rm.group(1))] = status
        elif em:
            epics[int(em.group(1))] = status
        elif sm:
            stories.append(
                {
                    "key": key,
                    "epic_num": int(sm.group(1)),
                    "story_num": int(sm.group(2)),
                    "slug": sm.group(3),
                    "status": status,
                }
            )
    return epics, stories, retros


def pick_next(stories, retros):
    """Mirror GDS sprint-status next-action precedence. Stories are in file order."""
    for want in ("in-progress", "review", "ready-for-dev", "backlog"):
        for s in stories:
            if s["status"] == want:
                return s, ACTION_FOR_STATUS[want]
    # All stories done -> first optional retrospective.
    for epic_num in sorted(retros):
        if retros[epic_num] == "optional":
            return None, "retrospective"
    return None, "done"


def match_explicit(stories, story_arg):
    m = re.match(r"^(\d+)-(\d+)(?:-(.+))?$", story_arg.strip())
    if not m:
        return None, f"could not parse --story '{story_arg}' (expected N-N or N-N-slug)"
    epic_num, story_num = int(m.group(1)), int(m.group(2))
    for s in stories:
        if s["epic_num"] == epic_num and s["story_num"] == story_num:
            return s, None
    return None, f"story {epic_num}-{story_num} not found in sprint-status"


def build_result(sprint_status_path, story_arg, impl_dir):
    result = {
        "story_key": None,
        "epic_num": None,
        "story_num": None,
        "story_file": None,
        "current_status": None,
        "epic_status": None,
        "epic_story_count": None,
        "is_first_in_epic": None,
        "is_last_in_epic": None,
        "retrospective_status": None,
        "next_action": None,
        "hard_stop": False,
        "hard_stop_reason": None,
        "error": None,
    }

    if not os.path.isfile(sprint_status_path):
        result["error"] = f"sprint-status file not found: {sprint_status_path}"
        result["hard_stop"] = True
        result["hard_stop_reason"] = "no sprint-status.yaml; run gds-sprint-planning first"
        return result

    with open(sprint_status_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    entries = parse_development_status(text)
    if not entries:
        result["error"] = "no development_status entries found"
        result["hard_stop"] = True
        result["hard_stop_reason"] = "empty/invalid sprint-status; run gds-sprint-planning"
        return result

    epics, stories, retros = classify(entries)

    if story_arg:
        target, err = match_explicit(stories, story_arg)
        if target is None:
            result["error"] = err
            result["hard_stop"] = True
            result["hard_stop_reason"] = err
            return result
        next_action = ACTION_FOR_STATUS.get(target["status"], "dev-story")
    else:
        target, next_action = pick_next(stories, retros)
        if target is None:
            result["next_action"] = next_action  # retrospective or done
            if next_action == "done":
                result["hard_stop"] = True
                result["hard_stop_reason"] = "all stories and retrospectives complete"
            return result

    epic_num = target["epic_num"]
    same_epic = [s for s in stories if s["epic_num"] == epic_num]
    min_story = min(s["story_num"] for s in same_epic)
    max_story = max(s["story_num"] for s in same_epic)

    result.update(
        {
            "story_key": target["key"],
            "epic_num": epic_num,
            "story_num": target["story_num"],
            "story_file": os.path.join(impl_dir, target["key"] + ".md") if impl_dir else target["key"] + ".md",
            "current_status": target["status"],
            "epic_status": epics.get(epic_num),
            "epic_story_count": len(same_epic),
            "is_first_in_epic": target["story_num"] == min_story,
            "is_last_in_epic": target["story_num"] == max_story,
            "retrospective_status": retros.get(epic_num),
            "next_action": next_action,
        }
    )

    if result["epic_status"] == "done" and next_action == "create-story":
        result["hard_stop"] = True
        result["hard_stop_reason"] = f"epic {epic_num} is marked done; cannot create new story"

    return result


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
_FIXTURE = """\
generated: 05-06-2025 21:30
last_updated: 05-06-2025 21:30
project: Demo
tracking_system: file-system

development_status:
  epic-1: in-progress
  1-1-user-authentication: done
  1-2-account-management: review
  1-3-plant-data-model: backlog
  epic-1-retrospective: optional

  epic-2: backlog
  2-1-personality-system: backlog
"""


def _run_self_test():
    import tempfile

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(_FIXTURE)
        path = f.name

    # Auto: first in-progress wins? none in-progress -> first review = 1-2.
    auto = build_result(path, None, "/impl")
    check("auto picks review story 1-2", auto["story_key"] == "1-2-account-management")
    check("auto next_action code-review", auto["next_action"] == "code-review")
    check("1-2 not first in epic", auto["is_first_in_epic"] is False)
    check("1-2 not last in epic", auto["is_last_in_epic"] is False)
    check("epic-1 status in-progress", auto["epic_status"] == "in-progress")
    check("epic-1 story count is 3", auto["epic_story_count"] == 3)
    check("retro status optional", auto["retrospective_status"] == "optional")
    check("story_file joined", auto["story_file"] == os.path.join("/impl", "1-2-account-management.md"))

    # Explicit backlog story -> create-story; is_last_in_epic for 1-3.
    ex = build_result(path, "1-3", "/impl")
    check("explicit 1-3 key", ex["story_key"] == "1-3-plant-data-model")
    check("explicit 1-3 create-story", ex["next_action"] == "create-story")
    check("1-3 is last in epic", ex["is_last_in_epic"] is True)
    check("1-3 not first in epic", ex["is_first_in_epic"] is False)

    # Explicit first story of epic 2.
    ex2 = build_result(path, "2-1-personality-system", "/impl")
    check("2-1 first in epic", ex2["is_first_in_epic"] is True)
    check("2-1 last in epic", ex2["is_last_in_epic"] is True)
    check("epic-2 story count is 1", ex2["epic_story_count"] == 1)

    # Missing file hard-stops.
    miss = build_result("/no/such/file.yaml", None, "/impl")
    check("missing file hard_stop", miss["hard_stop"] is True)

    # Unknown explicit story errors.
    bad = build_result(path, "9-9", "/impl")
    check("unknown story hard_stop", bad["hard_stop"] is True)

    os.unlink(path)

    if failures:
        print("SELF-TEST FAILED:", ", ".join(failures), file=sys.stderr)
        return 1
    print("SELF-TEST PASSED (all assertions)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="auto-gds GDS sprint-status reader")
    parser.add_argument("--sprint-status", help="path to sprint-status.yaml")
    parser.add_argument("--story", help="explicit story id (N-N or N-N-slug)")
    parser.add_argument("--impl-dir", default="", help="implementation_artifacts dir (for absolute story_file)")
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()

    if not args.sprint_status:
        parser.error("--sprint-status is required (or use --self-test)")

    result = build_result(args.sprint_status, args.story, args.impl_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
