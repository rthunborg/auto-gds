#!/usr/bin/env python3
"""Deterministic reader for a story file's ``### Review Findings`` section.

The code-review step is supposed to persist its triage into the story file as
``[Review][Patch]`` / ``[Review][Decision]`` / ``[Review][Defer]`` bullets. The
downstream Phase 7 loop (the human decision-ask and the fix delegate) reads
*that section*, not the reviewer's chat report — so when the skill silently runs
in its ``no-spec`` mode (story file never bound as the spec), it reports findings
to chat while the section stays empty and the loop fixes nothing.

This script lets the orchestrator reconcile what the reviewer *claimed* against
what is actually in the file, deterministically (no LLM re-read). It parses the
``### Review Findings`` section and counts each triage type by checked state.

Dependency-free. Output is a single JSON object on stdout.

Usage:
    review_findings.py --story-file PATH [--expect-min N]
    review_findings.py --self-test

With ``--expect-min N`` the process also exits non-zero (and sets
``reconciled: false``) when the section is absent or holds fewer than N total
items — pass the reviewer's reported finding count as N to gate the phase.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# `### Review Findings` (tolerant of trailing text/whitespace, case-insensitive).
HEADING_RE = re.compile(r"^#{2,4}\s+review\s+findings\b", re.IGNORECASE)
# Any ATX heading at level 1-4 — used to find where the section ends.
ANY_HEADING_RE = re.compile(r"^#{1,4}\s+\S")
# A triage bullet: `- [ ] [Review][Patch] ...` / `* [x] [Review][Defer] ...`.
BULLET_RE = re.compile(
    r"^\s*[-*]\s+\[(?P<mark>[ xX])\]\s+\[Review\]\[(?P<type>Patch|Decision|Defer)\]",
)


def _empty_counts():
    return {t: {"open": 0, "checked": 0} for t in ("patch", "decision", "defer")}


def parse_section(text: str):
    """Return (section_present, by_type-counts) for the Review Findings section."""
    lines = text.splitlines()
    by_type = _empty_counts()
    in_section = False
    section_present = False
    for raw in lines:
        if not in_section:
            if HEADING_RE.match(raw):
                in_section = True
                section_present = True
            continue
        # Inside the section: a new heading at level 1-4 ends it (the findings
        # heading itself was already consumed above).
        if ANY_HEADING_RE.match(raw):
            break
        m = BULLET_RE.match(raw)
        if not m:
            continue
        ftype = m.group("type").lower()
        checked = m.group("mark") in ("x", "X")
        by_type[ftype]["checked" if checked else "open"] += 1
    return section_present, by_type


def build_result(story_file: str, expect_min):
    result = {
        "story_file": story_file,
        "section_present": False,
        "total": 0,
        "by_type": _empty_counts(),
        "open_patch": 0,
        "open_decision": 0,
        "open_defer": 0,
        "reconciled": True,
        "expect_min": expect_min,
        "error": None,
    }

    if not os.path.isfile(story_file):
        result["error"] = f"story file not found: {story_file}"
        result["reconciled"] = expect_min in (None, 0)
        return result

    with open(story_file, "r", encoding="utf-8") as fh:
        text = fh.read()

    section_present, by_type = parse_section(text)
    total = sum(c["open"] + c["checked"] for c in by_type.values())
    result.update(
        {
            "section_present": section_present,
            "total": total,
            "by_type": by_type,
            "open_patch": by_type["patch"]["open"],
            "open_decision": by_type["decision"]["open"],
            "open_defer": by_type["defer"]["open"],
        }
    )

    if expect_min is not None:
        result["reconciled"] = section_present and total >= expect_min

    return result


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
_WITH_FINDINGS = """\
# Story 1-2

## Tasks / Subtasks

- [x] Build the thing

### Review Findings

- [ ] [Review][Decision] Token TTL — pick 15m vs 60m, affects UX
- [ ] [Review][Patch] Null deref on empty list [src/app.py:42]
- [ ] [Review][Patch] Off-by-one in pager [src/page.py:13]
- [x] [Review][Defer] Pre-existing flaky test [tests/t.py:9] — deferred

## Dev Notes

Not a finding: [Review][Patch] mentioned in prose should not count.
"""

_NO_SECTION = """\
# Story 1-3

## Tasks / Subtasks

- [x] Build the thing

## Dev Notes

Nothing was persisted here.
"""


def _run_self_test():
    import tempfile

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    def write(text):
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        f.write(text)
        f.close()
        return f.name

    p1 = write(_WITH_FINDINGS)
    r1 = build_result(p1, None)
    check("section detected", r1["section_present"] is True)
    check("total counts 4 bullets", r1["total"] == 4)
    check("two open patches", r1["open_patch"] == 2)
    check("one open decision", r1["open_decision"] == 1)
    check("defer checked not open", r1["by_type"]["defer"]["checked"] == 1 and r1["open_defer"] == 0)
    check("prose mention excluded", r1["by_type"]["patch"]["open"] == 2)
    check("no expect-min => reconciled", r1["reconciled"] is True)

    # expect-min satisfied / shortfall.
    check("expect-min 4 ok", build_result(p1, 4)["reconciled"] is True)
    check("expect-min 5 shortfall", build_result(p1, 5)["reconciled"] is False)

    p2 = write(_NO_SECTION)
    r2 = build_result(p2, None)
    check("no section flagged", r2["section_present"] is False)
    check("no section total 0", r2["total"] == 0)
    check("no section, no expectation => reconciled", r2["reconciled"] is True)
    # The failure the gate must catch: reviewer claimed findings, file has none.
    check("no section + expect 3 => NOT reconciled", build_result(p2, 3)["reconciled"] is False)

    # Missing file with an expectation is a reconciliation failure.
    check("missing file + expect 1 => NOT reconciled", build_result("/no/such.md", 1)["reconciled"] is False)
    check("missing file no expectation => reconciled", build_result("/no/such.md", None)["reconciled"] is True)

    for p in (p1, p2):
        os.unlink(p)

    if failures:
        print("SELF-TEST FAILED:", ", ".join(failures), file=sys.stderr)
        return 1
    print("SELF-TEST PASSED (all assertions)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="auto-bmad review-findings reader")
    parser.add_argument("--story-file", help="path to the story markdown file")
    parser.add_argument(
        "--expect-min",
        type=int,
        default=None,
        help="reviewer's reported finding count; exit 1 if the file holds fewer",
    )
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()

    if not args.story_file:
        parser.error("--story-file is required (or use --self-test)")

    result = build_result(args.story_file, args.expect_min)
    print(json.dumps(result, indent=2))
    return 0 if result["reconciled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
