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

The *rendering* of those bullets (a `[ ]`/`[x]` checkbox, ``**bold**``/``__emphasis__``
around the tag, a trailing `[Med]` severity) is owned by the upstream
``gds-code-review`` skill and produced by a non-deterministic LLM, so the parser
keys only on the semantic ``[Review][Type]`` tag and treats everything around it
as optional. A finding with no checkbox counts as ``open`` (the safe default).

It also reconciles the durable, cross-story deferral ledger
(``{implementation_artifacts}/deferred-work.md``): the code-review step is
supposed to append every ``[Review][Defer]`` finding there under a
``## Deferred from: …`` heading, but auto-gds's delegation prompt historically
emphasized only the story-file section, so that side-effect got dropped. With
``--deferred-work-file`` the gate confirms each defer finding in the story
actually reached the ledger.

Dependency-free. Output is a single JSON object on stdout.

Usage:
    review_findings.py --story-file PATH [--expect-min N]
                       [--deferred-work-file PATH [--story-key KEY]]
    review_findings.py --self-test

With ``--expect-min N`` the process also exits non-zero (and sets
``reconciled: false``) when the section is absent or holds fewer than N total
items — pass the reviewer's reported finding count as N to gate the phase.

With ``--deferred-work-file PATH`` the process additionally fails reconciliation
when the ledger holds fewer ``## Deferred from:`` bullets than the story has
``[Review][Defer]`` findings. Pass ``--story-key KEY`` to scope the ledger count
to this story's heading (the ledger is append-only across stories, so an unscoped
count is trivially satisfied once history accumulates).
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
# A triage bullet. The semantic signal is the `[Review][Type]` tag; the rendering
# around it is owned by the upstream `gds-code-review` skill and produced by a
# non-deterministic LLM, so match flexibly. All of these count as one finding:
#   - [ ] [Review][Patch] ...        (checkbox form)
#   * [x] [Review][Defer] ...        (checked checkbox)
#   - **[Review][Decision] [Med]** ..(bold prose, no checkbox — real GDS/BMGD output)
#   - __[Review][Patch]__ ...        (underscore emphasis)
# The checkbox is OPTIONAL: when absent the finding defaults to `open` (the safe
# state — an unmarked finding is one still needing attention). Bold/emphasis
# markers (`**`/`__`) before the tag are tolerated and ignored.
BULLET_RE = re.compile(
    r"^\s*[-*+]\s+"                  # list bullet
    r"(?:\[(?P<mark>[ xX])\]\s+)?"   # optional checkbox (open/checked state)
    r"(?:\*\*|__)?\s*"               # optional bold/emphasis marker
    r"\[Review\]\[(?P<type>Patch|Decision|Defer)\]",
)
# A ledger section heading: `## Deferred from: code review of story-3.3 (2026-03-18)`.
DEFER_HEADING_RE = re.compile(r"^#{1,4}\s+deferred\s+from:", re.IGNORECASE)
# Any list bullet (the ledger entries are plain bullets, not triage checkboxes).
LEDGER_BULLET_RE = re.compile(r"^\s*[-*]\s+\S")


def _empty_counts():
    return {t: {"open": 0, "checked": 0} for t in ("patch", "decision", "defer")}


def parse_deferred_work(text: str, story_key=None):
    """Count deferral bullets in the ledger under ``## Deferred from:`` headings.

    Returns ``(present, count)``. ``present`` is True if any ``## Deferred from:``
    heading exists at all. When ``story_key`` is given, only bullets under a
    heading whose text contains that key (case-insensitive) are counted — the
    ledger is append-only across stories, so scoping keeps the count meaningful.
    """
    present = False
    count = 0
    counting = False
    for raw in text.splitlines():
        if DEFER_HEADING_RE.match(raw):
            present = True
            counting = story_key is None or story_key.lower() in raw.lower()
            continue
        if ANY_HEADING_RE.match(raw):
            # Any other heading closes the current deferral block.
            counting = False
            continue
        if counting and LEDGER_BULLET_RE.match(raw):
            count += 1
    return present, count


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


def build_result(story_file: str, expect_min, deferred_work_file=None, story_key=None):
    result = {
        "story_file": story_file,
        "section_present": False,
        "total": 0,
        "by_type": _empty_counts(),
        "open_patch": 0,
        "open_decision": 0,
        "open_defer": 0,
        "deferred_work_file": deferred_work_file,
        "deferred_work_present": False,
        "deferred_work_logged": 0,
        "deferred_work_expected": 0,
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
    story_defer = by_type["defer"]["open"] + by_type["defer"]["checked"]
    result.update(
        {
            "section_present": section_present,
            "total": total,
            "by_type": by_type,
            "open_patch": by_type["patch"]["open"],
            "open_decision": by_type["decision"]["open"],
            "open_defer": by_type["defer"]["open"],
            "deferred_work_expected": story_defer,
        }
    )

    section_ok = True
    if expect_min is not None:
        section_ok = section_present and total >= expect_min

    # Ledger reconciliation: every story defer finding must reach deferred-work.md.
    ledger_ok = True
    if deferred_work_file is not None:
        if os.path.isfile(deferred_work_file):
            with open(deferred_work_file, "r", encoding="utf-8") as fh:
                ledger_present, logged = parse_deferred_work(fh.read(), story_key)
        else:
            ledger_present, logged = False, 0
        result["deferred_work_present"] = ledger_present
        result["deferred_work_logged"] = logged
        ledger_ok = logged >= story_defer

    result["reconciled"] = section_ok and ledger_ok
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

# Real `gds-code-review` output: bold-prose bullets, no checkboxes, optional
# severity tag — plus one already-checked item and one underscore-emphasis item.
# The gate must count all of these and default the un-checkboxed ones to `open`.
_WITH_BOLD_FINDINGS = """\
# Story 1-4

### Review Findings

- **[Review][Decision] [Med]** Token TTL — pick 15m vs 60m, affects UX
- **[Review][Patch] [Low]** Null deref on empty list [src/app.py:42]
- [x] **[Review][Patch]** Off-by-one already fixed this pass [src/page.py:13]
- __[Review][Defer]__ Pre-existing flaky test [tests/t.py:9]

## Dev Notes

Not a finding: **[Review][Patch]** mentioned in prose should not count.
"""

_NO_SECTION = """\
# Story 1-3

## Tasks / Subtasks

- [x] Build the thing

## Dev Notes

Nothing was persisted here.
"""

# Ledger that logged the one defer finding from story 1-2, plus an older story's.
_LEDGER_WITH_DEFER = """\
# Deferred Work

## Deferred from: code review of story-1-1 (2026-03-10)

- Tidy the legacy import shim [src/old.py:3] — pre-existing

## Deferred from: code review of story-1-2 (2026-03-18)

- Pre-existing flaky test [tests/t.py:9] — deferred, not caused by this change
"""

# Ledger missing story 1-2's defer entirely (only the older story present).
_LEDGER_MISSING_DEFER = """\
# Deferred Work

## Deferred from: code review of story-1-1 (2026-03-10)

- Tidy the legacy import shim [src/old.py:3] — pre-existing
"""


def _run_self_test():
    import tempfile

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    def write(text):
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
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

    # Bold-prose / no-checkbox rendering (real GDS/BMGD output) must count the same.
    pb = write(_WITH_BOLD_FINDINGS)
    rb = build_result(pb, None)
    check("bold: section detected", rb["section_present"] is True)
    check("bold: total counts 4 bullets", rb["total"] == 4)
    check("bold: no-checkbox decision => open", rb["open_decision"] == 1)
    check("bold: one open + one checked patch", rb["open_patch"] == 1 and rb["by_type"]["patch"]["checked"] == 1)
    check("bold: underscore-emphasis defer => open", rb["open_defer"] == 1)
    check("bold: prose mention in other section excluded", rb["by_type"]["patch"]["open"] == 1)
    check("bold: expect-min 4 reconciled (was the false-fail)", build_result(pb, 4)["reconciled"] is True)
    os.unlink(pb)

    # Ledger reconciliation: p1 has one [Review][Defer] finding (story 1-2).
    led_ok = write(_LEDGER_WITH_DEFER)
    led_missing = write(_LEDGER_MISSING_DEFER)
    r_led = build_result(p1, None, led_ok, "story-1-2")
    check("ledger present detected", r_led["deferred_work_present"] is True)
    check("ledger expects 1 defer", r_led["deferred_work_expected"] == 1)
    check("ledger scoped count 1", r_led["deferred_work_logged"] == 1)
    check("ledger satisfied => reconciled", r_led["reconciled"] is True)
    # Same ledger, wrong story key => that story's deferral isn't logged.
    check(
        "ledger scoped to absent key => NOT reconciled",
        build_result(p1, None, led_ok, "story-9-9")["reconciled"] is False,
    )
    # Defer finding never reached the ledger.
    r_miss = build_result(p1, None, led_missing, "story-1-2")
    check("ledger missing defer logged 0", r_miss["deferred_work_logged"] == 0)
    check("ledger missing defer => NOT reconciled", r_miss["reconciled"] is False)
    # Ledger file absent but a defer exists => NOT reconciled.
    check(
        "ledger file absent + defer => NOT reconciled",
        build_result(p1, None, "/no/such-ledger.md", "story-1-2")["reconciled"] is False,
    )
    # Unscoped count tolerates history (counts all `## Deferred from:` bullets).
    check("ledger unscoped counts all", build_result(p1, None, led_ok, None)["deferred_work_logged"] == 2)
    for p in (led_ok, led_missing):
        os.unlink(p)

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
    parser = argparse.ArgumentParser(description="auto-gds review-findings reader")
    parser.add_argument("--story-file", help="path to the story markdown file")
    parser.add_argument(
        "--expect-min",
        type=int,
        default=None,
        help="reviewer's reported finding count; exit 1 if the file holds fewer",
    )
    parser.add_argument(
        "--deferred-work-file",
        default=None,
        help="path to deferred-work.md; exit 1 if it holds fewer deferrals than the story",
    )
    parser.add_argument(
        "--story-key",
        default=None,
        help="scope the ledger count to this story's `## Deferred from:` heading",
    )
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()

    if not args.story_file:
        parser.error("--story-file is required (or use --self-test)")

    result = build_result(
        args.story_file, args.expect_min, args.deferred_work_file, args.story_key
    )
    print(json.dumps(result, indent=2))
    return 0 if result["reconciled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
