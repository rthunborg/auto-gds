#!/usr/bin/env python3
"""bmad_compat.py — assess BMAD version changes against auto-bmad's surface.

auto-bmad's pipeline delegates into TWO separately versioned npm packages:
`bmad-method` (the core BMM line — create-story/dev-story/code-review/…) and
`bmad-method-test-architecture-enterprise` (the TEA module — the `bmad-testarch-*`
skills run in the TEA-gated phases). They ship identically (`latest`/`next`
dist-tags, `vX.Y.Z` git tags, a `package/src/**` payload), so one diff engine
checks both; `--report` emits a combined result with a worst-of headline verdict.

The hard, error-prone part of "is the new release compatible?" is mechanical:
work out which versions exist (stable vs prerelease), download the *published*
packages, diff them, and decide which changed files actually touch the skills
auto-bmad delegates to. This script does exactly that and emits structured JSON.
The *judgement* — does a flagged change really break us, is a new skill worth
adopting — is left to the caller (the SKILL.md reading this output), because that
needs reading the real diff, not a heuristic.

Two modes, and only one of them touches the network:

  --report     fetch npm metadata + tarballs and diff each line *incrementally* —
               last-checked stable -> current stable, and last-checked prerelease
               -> current prerelease — so only what is genuinely new since the
               last check is surfaced. classify, emit JSON.  (network)
  --self-test  exercise every pure function against fixtures.  (hermetic — no
               network, so it is safe in CI and matches the repo's other scripts)

Why diff the *published tarballs* rather than git? Because that is what users
actually `npm install`. docs/ and tests aren't packaged, so a docs-only BMAD
change correctly shows up here as "nothing shipped" — which is the truth for a
runtime-compatibility question.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
import urllib.request
from difflib import unified_diff
from urllib.parse import urlparse

NPM_REGISTRY = "https://registry.npmjs.org"
# Tarball URLs are read out of the registry JSON, so pin them to https on the
# npm host before fetching — never follow a `file://` or off-host URL even if
# the metadata is tampered with.
ALLOWED_HOST_SUFFIX = ".npmjs.org"

# The BMAD npm packages auto-bmad's pipeline delegates into. They ship the SAME
# way — `latest`/`next` dist-tags, `vX.Y.Z` git tags, a `package/src/**` payload
# (docs/tests/tools excluded) — so one diff engine serves both. `bmad-method` is
# the core BMM line; `bmad-method-test-architecture-enterprise` is the separately
# versioned TEA (test-architecture) module that ships the `bmad-testarch-*` skills
# auto-bmad runs in its TEA-gated phases. Each entry pins the npm name (the dict
# key), a short report label, and the GitHub slug Step 3 cross-checks + the README
# blockquote windows baselines by. Order matters only cosmetically (report order).
PACKAGES = {
    "bmad-method": {
        "label": "BMAD-METHOD",
        "repo": "bmad-code-org/BMAD-METHOD",
    },
    "bmad-method-test-architecture-enterprise": {
        "label": "TEA (test-architecture)",
        "repo": "bmad-code-org/bmad-method-test-architecture-enterprise",
    },
}

# Skills that don't just run in the pipeline but *own a durable contract*
# auto-bmad reads or writes. A change here is the highest-signal kind: it can
# alter a file format the orchestrator parses, not just an internal step.
CONTRACT_OWNERS = {
    "bmad-sprint-planning": "sprint-status.yaml (status keys/shape)",
    "bmad-sprint-status": "sprint-status.yaml (status keys/shape)",
    "bmad-create-story": "story file (Status: field + section headings)",
    "bmad-generate-project-context": "project-context.md (path + structure)",
    "bmad-code-review": ("### Review Findings + deferred-work ledger; auto-bmad ALSO replicates this "
                         "skill's internal structure — its step-02 lens roster + the inline Acceptance "
                         "Auditor prompt + its step-03 triage rubric — in delegation.md's code-review "
                         "fan-out, so a change to those internals drifts silently"),
    # auto-bmad invokes these two review lenses DIRECTLY in the Phase 7 fan-out (they were formerly
    # reached only through bmad-code-review's own subagents), and its code-review-triage prompt parses
    # their output shapes — so a format change is a silent break, not just churn.
    "bmad-review-edge-case-hunter": ("Edge Case Hunter JSON output shape "
                                     "(location/trigger_condition/guard_snippet/potential_consequence) — "
                                     "parsed by the code-review-triage prompt"),
    "bmad-review-adversarial-general": ("Blind Hunter findings-list output — normalized by the "
                                        "code-review-triage prompt"),
    "bmad-retrospective": "retro notes consumed for project-context refresh",
}

# Fallback surface if the caller can't supply one from the repo. Kept small and
# obviously-current; the real run derives the surface from references/ so this
# never silently goes stale on its own.
FALLBACK_SURFACE = sorted(set(CONTRACT_OWNERS) | {
    "bmad-dev-story", "bmad-testarch-test-design", "bmad-testarch-atdd",
    "bmad-testarch-automate", "bmad-testarch-trace", "bmad-testarch-nfr",
    "bmad-testarch-test-review", "bmad-testarch-framework", "bmad-testarch-ci",
})

# Tokens the surface regex picks up that are not real skills.
SURFACE_NOISE = {"bmad-output", "bmad-method", "bmad-testarch"}

SKILL_SEG_RE = re.compile(r"^(?:bmad|gds)-[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"\b(\d+)\.(\d+)\.(\d+)(?:-next\.(\d+))?\b")


# --------------------------------------------------------------------------- #
# Pure helpers (all covered by --self-test)                                    #
# --------------------------------------------------------------------------- #

def semver_key(version: str):
    """Sort key honouring that a `-next` prerelease sits *below* its own final
    release but *above* the previous patch: 6.8.0 < 6.8.1-next.0 < 6.8.1."""
    m = SEMVER_RE.search(version)
    if not m:
        return (0, 0, 0, 0, 0)
    major, minor, patch, pre = m.groups()
    is_final = 0 if pre is not None else 1  # final outranks its prerelease
    return (int(major), int(minor), int(patch), is_final, int(pre or 0))


def derive_surface(refs_text: str) -> list:
    """Extract the set of BMAD skills auto-bmad delegates to by scanning its
    reference docs. Over-inclusion is safe (a flagged skill just gets read);
    omission is not, so we err toward catching everything that looks like a
    skill id and only strip known non-skill tokens."""
    found = set(re.findall(r"bmad-[a-z0-9]+(?:-[a-z0-9]+)*", refs_text))
    return sorted(t for t in found if t not in SURFACE_NOISE)


def skill_name_of(path: str):
    """Return the skill-directory segment of a package path, or None.
    e.g. src/bmm-skills/4-implementation/bmad-create-story/SKILL.md -> bmad-create-story."""
    for seg in path.split("/"):
        if SKILL_SEG_RE.match(seg):
            return seg
    return None


def classify_path(path: str, surface) -> dict:
    """Decide how much a changed file matters to auto-bmad.

    high  — a skill auto-bmad delegates to changed (it runs this every story)
    low   — some other BMAD skill changed (not in the pipeline, but maybe a new
            capability worth a look)
    info  — a non-skill file (e.g. package.json) — version noise
    """
    skill = skill_name_of(path)
    surface = set(surface)
    if skill and skill in surface:
        entry = {"path": path, "skill": skill, "relevance": "high",
                 "reason": "delegated skill — runs in the auto-bmad pipeline"}
        if skill in CONTRACT_OWNERS:
            entry["relevance"] = "critical"
            entry["owns_contract"] = CONTRACT_OWNERS[skill]
            entry["reason"] = ("delegated skill that OWNS a contract auto-bmad "
                               "parses — read the diff for format changes")
        return entry
    if skill:
        return {"path": path, "skill": skill, "relevance": "low",
                "reason": "BMAD skill not in auto-bmad's pipeline — possible new capability"}
    return {"path": path, "skill": None, "relevance": "info",
            "reason": "non-skill file"}


def diff_sets(files_a: dict, files_b: dict) -> dict:
    """Compare two {path: bytes} maps into changed / added / removed path lists."""
    a, b = set(files_a), set(files_b)
    changed = sorted(p for p in (a & b) if files_a[p] != files_b[p])
    return {"changed": changed, "added": sorted(b - a), "removed": sorted(a - b)}


def _skill_dirs(files: dict) -> dict:
    """Map skill-name -> its SKILL.md path for every skill present in a tree."""
    out = {}
    for path in files:
        if path.endswith("/SKILL.md"):
            name = skill_name_of(path)
            if name:
                out[name] = path
    return out


def parse_description(skill_md: str):
    """Pull the `description:` value out of a SKILL.md frontmatter block."""
    m = re.search(r"^description:\s*(.+?)\s*$", skill_md, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip().strip("'\"")


def find_new_skills(files_a: dict, files_b: dict, since: str) -> list:
    """Skills present in the newer tree but not the older one."""
    a, b = _skill_dirs(files_a), _skill_dirs(files_b)
    out = []
    for name in sorted(set(b) - set(a)):
        content = files_b[b[name]].decode("utf-8", "replace")
        out.append({"name": name, "path": b[name], "since": since,
                    "description": parse_description(content)})
    return out


def _compat_blockquote(text: str) -> str:
    """Isolate the `> … Compatibility: …` blockquote so version parsing can't
    collide with the BMAD-METHOD repo URL that also appears in the page's badges
    and links. Falls back to the whole text when no such blockquote is found."""
    lines = text.splitlines()
    idx = next((i for i, ln in enumerate(lines)
                if ln.lstrip().startswith(">") and "Compatibility" in ln), None)
    if idx is None:
        return text
    start = idx
    while start > 0 and lines[start - 1].lstrip().startswith(">"):
        start -= 1
    end = idx
    while end + 1 < len(lines) and lines[end + 1].lstrip().startswith(">"):
        end += 1
    return "\n".join(lines[start:end + 1])


def _highest_pair(text: str):
    """(highest plain semver, highest -next) found in a span — None where absent."""
    finals, pres = [], []
    for m in SEMVER_RE.finditer(text):
        v = m.group(0)
        (pres if "-next." in v else finals).append(v)
    stable = max(finals, key=semver_key) if finals else None
    prerelease = max(pres, key=semver_key) if pres else None
    return stable, prerelease


def parse_baseline_from_readme(text: str, package=None, packages=None):
    """Read the last-verified versions out of the README compat blockquote.

    With `package` set, scope to *that* package's clause: within the compat
    blockquote, the window runs from the package's GitHub repo slug up to the next
    package's slug (or end of blockquote). Per-package scoping is a *correctness*
    requirement, not a nicety — the two lines need not share a prerelease (TEA's
    `next` can sort below its own stable, leaving its clause with no `-next` token),
    so a global 'highest -next' would hand one package's prerelease to the other.
    Authoring rule the windowing assumes: each clause's versions sit *after* its
    repo link. Returns (stable, prerelease|None); (None, None) when the package's
    clause isn't present yet. With `package=None`, the legacy global parse over the
    blockquote (highest plain semver + highest -next)."""
    packages = packages or PACKAGES
    region = _compat_blockquote(text)
    if package is None:
        return _highest_pair(region)
    repo = packages[package]["repo"]
    start = region.find(repo)
    if start == -1:
        return None, None
    later = [p for p in (region.find(m["repo"]) for k, m in packages.items() if k != package)
             if p != -1 and p > start]
    end = min(later) if later else len(region)
    return _highest_pair(region[start:end])


def prerelease_anchor(stable, prev_prerelease, prerelease):
    """Pick the 'from' version for the prerelease diff, or None to skip it.

    We only want what's *genuinely new* in the prerelease line since the last
    check — never re-surfacing anything already covered by the stable diff or the
    prerelease we last signed off on. So anchor at the highest version we've
    already accounted for: the current stable, or the last-checked prerelease when
    it still sits above stable (semver_key ranks a final above its own -next, so a
    prerelease that has since *graduated* to stable drops below the stable floor
    and is correctly covered by the stable diff, not re-reported here). Skip
    entirely when the live prerelease isn't above that floor — it graduated, or
    hasn't moved since the last check."""
    if not prerelease:
        return None
    floor = stable
    if prev_prerelease and semver_key(prev_prerelease) > semver_key(floor):
        floor = prev_prerelease
    return floor if semver_key(prerelease) > semver_key(floor) else None


def stable_anchor(baseline, prev_prerelease, stable):
    """Pick the 'from' version for the stable diff, or None to skip it.

    Symmetric to prerelease_anchor: anchor at the highest version we've already
    checked that sits *below* the current stable — the last-checked stable, or the
    last-checked prerelease once it has *graduated* into this stable (then we diff
    only the prerelease→final sliver, never re-showing changes already reviewed as
    prereleases). A prerelease aimed at a *future* line (>= this stable) is not a
    precursor to it, so it's ignored. Skip when stable hasn't moved past what we've
    seen."""
    floor = baseline
    if (prev_prerelease
            and semver_key(prev_prerelease) < semver_key(stable)
            and semver_key(prev_prerelease) > semver_key(floor)):
        floor = prev_prerelease
    return floor if semver_key(stable) > semver_key(floor) else None


def unified(path: str, a: bytes, b: bytes, max_lines: int) -> str:
    """A bounded unified diff for one file, or a binary-change note."""
    try:
        a_lines = a.decode("utf-8").splitlines(keepends=True)
        b_lines = b.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return "(binary file changed)"
    lines = list(unified_diff(a_lines, b_lines, fromfile="a/" + path, tofile="b/" + path))
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... (+{len(lines) - max_lines} more diff lines truncated)\n"]
    return "".join(lines)


# --------------------------------------------------------------------------- #
# Network (NOT exercised by --self-test)                                       #
# --------------------------------------------------------------------------- #

def _get(url: str, timeout: int = 30) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(ALLOWED_HOST_SUFFIX):
        raise SystemExit(f"refusing to fetch non-npm URL: {url!r}")
    req = urllib.request.Request(url, headers={"User-Agent": "auto-bmad-compat-check"})
    # nosemgrep: dynamic-urllib-use-detected -- scheme+host pinned to https npm above
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read()


def registry_url(package: str) -> str:
    return f"{NPM_REGISTRY}/{package}"


def fetch_registry(package: str) -> dict:
    return json.loads(_get(registry_url(package)).decode("utf-8"))


def extract_package_src(tar_bytes: bytes) -> dict:
    """Return {path: bytes} for the runtime payload — package/src/** and
    package.json — with the leading `package/` stripped. docs/, tests/ etc. are
    deliberately skipped: they aren't what compatibility hinges on."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            if m.name == "package/package.json" or m.name.startswith("package/src/"):
                fh = tf.extractfile(m)
                if fh is not None:
                    out[m.name[len("package/"):]] = fh.read()
    return out


def _has_version(registry: dict, version: str) -> bool:
    """Whether npm still publishes this exact version (prereleases can be pulled)."""
    return version in registry.get("versions", {})


def _resolve_anchor(anchor, fallback, registry, kind):
    """Guard against anchoring a diff at an *ephemeral* prerelease npm has since
    unpublished. If `anchor` is such a version, degrade to `fallback` (always a
    durable stable) and return a note saying so; otherwise return it unchanged."""
    if anchor and anchor != fallback and not _has_version(registry, anchor):
        note = (f"last-checked prerelease {anchor} is no longer published on npm; "
                f"anchored the {kind} diff at {fallback} instead")
        return fallback, note
    return anchor, None


def _git_head(registry: dict, version) -> str | None:
    """The exact source commit a published version was built from, if npm recorded
    it. npm stamps `gitHead` into each published version's metadata, so this pins a
    tagless `-next` prerelease to a precise commit — letting the repo cross-check
    (Step 3) read the *exact* commit window that produced a diff, instead of the
    looser `v<stable>...main` (where `main` can sit ahead of the published build)."""
    if not version:
        return None
    return registry.get("versions", {}).get(version, {}).get("gitHead")


def _tarball_url(registry: dict, version: str) -> str:
    try:
        return registry["versions"][version]["dist"]["tarball"]
    except KeyError:
        raise SystemExit(f"version {version!r} not found on npm")


def _tree(registry: dict, version: str) -> dict:
    return extract_package_src(_get(_tarball_url(registry, version)))


def _compare(label, older_v, newer_v, older, newer, surface, max_lines) -> dict:
    sets = diff_sets(older, newer)
    impact = []
    for path in sets["changed"]:
        entry = classify_path(path, surface)
        entry["change"] = "modified"
        if entry["relevance"] in ("critical", "high", "low"):
            entry["diff"] = unified(path, older[path], newer[path], max_lines)
        impact.append(entry)
    for path in sets["added"]:
        entry = classify_path(path, surface)
        entry["change"] = "added"
        impact.append(entry)
    for path in sets["removed"]:
        entry = classify_path(path, surface)
        entry["change"] = "removed"
        impact.append(entry)
    order = {"critical": 0, "high": 1, "low": 2, "info": 3}
    impact.sort(key=lambda e: (order[e["relevance"]], e["path"]))
    return {
        "label": label,
        "from": older_v,
        "to": newer_v,
        "files_changed": len(sets["changed"]),
        "files_added": len(sets["added"]),
        "files_removed": len(sets["removed"]),
        "impact": impact,
        "new_skills": find_new_skills(older, newer, f"{label} ({newer_v})"),
    }


def build_report(package, baseline, prev_prerelease, surface, max_lines) -> dict:
    registry = fetch_registry(package)
    tags = registry.get("dist-tags", {})
    stable = tags.get("latest")
    nxt = tags.get("next")
    # A `next` tag can lag behind a fresh stable; only treat it as a real
    # prerelease if it actually sorts above the current stable.
    prerelease = nxt if (nxt and semver_key(nxt) > semver_key(stable)) else None

    trees = {baseline: _tree(registry, baseline), stable: _tree(registry, stable)}

    comparisons = []

    def add(comp):
        # Pin each comparison to the exact source commits npm built its endpoints
        # from, so Step 3's repo cross-check reads the precise commit window.
        comp["from_git_head"] = _git_head(registry, comp["from"])
        comp["to_git_head"] = _git_head(registry, comp["to"])
        comparisons.append(comp)

    # Stable line: only what's new since the highest version we've already checked
    # below the current stable — the last-checked stable, or a prerelease that has
    # since graduated into it (then just the prerelease→final sliver).
    s_anchor = stable_anchor(baseline, prev_prerelease, stable)
    s_anchor, stable_anchor_note = _resolve_anchor(s_anchor, baseline, registry, "stable")
    if s_anchor:
        if s_anchor not in trees:
            trees[s_anchor] = _tree(registry, s_anchor)
        label = "prev_stable_to_stable" if s_anchor == baseline else "prev_prerelease_to_stable"
        add(_compare(label, s_anchor, stable,
                     trees[s_anchor], trees[stable], surface, max_lines))

    # Prerelease line: only what's new since the last-checked prerelease (or the
    # current stable, whichever is higher — see prerelease_anchor).
    pre_anchor = prerelease_anchor(stable, prev_prerelease, prerelease)
    pre_anchor, pre_anchor_note = _resolve_anchor(pre_anchor, stable, registry, "prerelease")
    if pre_anchor and prerelease:  # prerelease is non-None whenever pre_anchor is set
        if pre_anchor not in trees:
            trees[pre_anchor] = _tree(registry, pre_anchor)
        if prerelease not in trees:
            trees[prerelease] = _tree(registry, prerelease)
        label = ("stable_to_prerelease" if pre_anchor == stable
                 else "prev_prerelease_to_prerelease")
        add(_compare(label, pre_anchor, prerelease,
                     trees[pre_anchor], trees[prerelease], surface, max_lines))

    return {
        "package": package,
        "label": PACKAGES.get(package, {}).get("label", package),
        "repo": PACKAGES.get(package, {}).get("repo"),
        "baseline": baseline,
        "prev_prerelease": prev_prerelease,
        "stable": stable,
        "prerelease": prerelease,
        "prerelease_tag_raw": nxt,
        "stable_anchor_note": stable_anchor_note,
        "prerelease_anchor_note": pre_anchor_note,
        "surface_skills": surface,
        "comparisons": comparisons,
        "summary": _summarize(comparisons),
    }


def _summarize(comparisons) -> dict:
    hits = {"critical": [], "high": [], "low": []}
    new_skills = []
    for c in comparisons:
        for e in c["impact"]:
            if e["relevance"] in hits:
                hits[e["relevance"]].append(e["path"])
        new_skills += [s["name"] for s in c["new_skills"]]
    if hits["critical"] or hits["high"]:
        verdict = "needs-attention"
    elif hits["low"] or new_skills:
        verdict = "review-opportunities"
    elif not comparisons:
        # Nothing new on either line since the last check.
        verdict = "up-to-date"
    else:
        verdict = "compatible"
    return {
        "verdict": verdict,
        "delegated_skill_changes": hits["critical"] + hits["high"],
        "contract_owner_changes": hits["critical"],
        "other_skill_changes": hits["low"],
        "new_skills": sorted(set(new_skills)),
    }


# Worst-of ordering, so the combined headline verdict is the most-attention-needing
# of the packages checked (a TEA break must not be masked by a clean BMAD line).
VERDICT_RANK = {"up-to-date": 0, "compatible": 1, "review-opportunities": 2,
                "needs-attention": 3}


def build_combined_report(specs, surface, max_lines) -> dict:
    """Build one per-package report for each (package, baseline, prev_prerelease)
    spec and fold them into a combined result with a worst-of headline verdict.

    A package whose baseline can't be resolved (no README clause and no override)
    becomes an `error` entry rather than aborting the whole run — one missing clause
    must never sink the other package's check."""
    reports = []
    for package, baseline, prev_prerelease in specs:
        if not baseline:
            reports.append({
                "package": package,
                "label": PACKAGES.get(package, {}).get("label", package),
                "error": "could not determine baseline (no README compat clause and no override)",
            })
            continue
        reports.append(build_report(package, baseline, prev_prerelease, surface, max_lines))
    graded = [r["summary"]["verdict"] for r in reports if "summary" in r]
    if graded:
        verdict = max(graded, key=lambda v: VERDICT_RANK.get(v, 0))
    elif reports:
        verdict = "error"
    else:
        verdict = "up-to-date"
    return {
        "verdict": verdict,
        "surface_skills": surface,
        "packages": reports,
    }


# --------------------------------------------------------------------------- #
# Self-test                                                                    #
# --------------------------------------------------------------------------- #

def _self_test() -> int:
    failures = []

    def check(name, cond):
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            failures.append(name)

    # semver ordering — the subtle prerelease rule
    ordered = sorted(["6.8.1", "6.8.0", "6.8.1-next.0", "6.7.1"], key=semver_key)
    check("semver: 6.7.1 < 6.8.0 < 6.8.1-next.0 < 6.8.1",
          ordered == ["6.7.1", "6.8.0", "6.8.1-next.0", "6.8.1"])
    check("semver: prerelease ranks above previous patch",
          semver_key("6.8.1-next.0") > semver_key("6.8.0"))

    # surface derivation strips noise, keeps real skills
    surf = derive_surface("run /bmad-create-story and bmad-testarch-trace; _bmad-output/")
    check("surface: keeps real skills", "bmad-create-story" in surf and "bmad-testarch-trace" in surf)
    check("surface: drops _bmad-output noise", "bmad-output" not in surf)

    # skill-name extraction from realistic package paths
    check("skill_name: bmm nested path",
          skill_name_of("src/bmm-skills/4-implementation/bmad-create-story/SKILL.md") == "bmad-create-story")
    check("skill_name: core-skills path",
          skill_name_of("src/core-skills/bmad-party-mode/SKILL.md") == "bmad-party-mode")
    check("skill_name: non-skill path", skill_name_of("package.json") is None)

    # classification tiers
    surface = ["bmad-create-story", "bmad-dev-story"]
    c1 = classify_path("src/x/bmad-create-story/SKILL.md", surface)
    check("classify: contract owner -> critical", c1["relevance"] == "critical" and "owns_contract" in c1)
    c2 = classify_path("src/x/bmad-dev-story/SKILL.md", surface)
    check("classify: delegated non-owner -> high", c2["relevance"] == "high")
    c3 = classify_path("src/core-skills/bmad-party-mode/SKILL.md", surface)
    check("classify: off-pipeline skill -> low", c3["relevance"] == "low")
    c4 = classify_path("package.json", surface)
    check("classify: non-skill -> info", c4["relevance"] == "info")
    c5 = classify_path("src/bmm-skills/4-implementation/bmad-review-edge-case-hunter/SKILL.md",
                       ["bmad-review-edge-case-hunter"])
    check("classify: code-review fan-out lens is a contract owner -> critical",
          c5["relevance"] == "critical" and "owns_contract" in c5)

    # diff sets
    a = {"p.json": b"1", "src/a/SKILL.md": b"x", "src/gone/SKILL.md": b"z"}
    b = {"p.json": b"2", "src/a/SKILL.md": b"x", "src/new/SKILL.md": b"y"}
    ds = diff_sets(a, b)
    check("diff_sets: changed", ds["changed"] == ["p.json"])
    check("diff_sets: added", ds["added"] == ["src/new/SKILL.md"])
    check("diff_sets: removed", ds["removed"] == ["src/gone/SKILL.md"])

    # new-skill detection + description parse
    old = {"src/core-skills/bmad-a/SKILL.md": b"---\nname: bmad-a\n---\n"}
    new = dict(old)
    new["src/core-skills/bmad-b/SKILL.md"] = b"---\nname: bmad-b\ndescription: Does a new thing.\n---\n"
    ns = find_new_skills(old, new, "prerelease")
    check("new_skills: detects added skill", len(ns) == 1 and ns[0]["name"] == "bmad-b")
    check("new_skills: parses description", ns[0]["description"] == "Does a new thing.")

    # README baseline parse — legacy global parse over the blockquote
    readme = "> **Compatibility:** tested ... up to **6.8.0** (and the **6.8.1-next.0** prerelease)."
    stable, pre = parse_baseline_from_readme(readme)
    check("readme: stable baseline", stable == "6.8.0")
    check("readme: prerelease baseline", pre == "6.8.1-next.0")

    # Per-package windowing — mirrors the real two-clause compat blockquote, with a
    # decoy badge line carrying the BMAD-METHOD repo URL *outside* the blockquote
    # (proves _compat_blockquote isolation dodges the badge collision).
    two_pkg = (
        "[badge](https://github.com/bmad-code-org/BMAD-METHOD) [other](https://x)\n"
        "\n"
        "> **Compatibility:** tested against the "
        "**[BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) v6 skill line** up to "
        "**6.8.0** (and the **6.8.1-next.9** prerelease), and the separately versioned "
        "**[TEA test-architecture module]"
        "(https://github.com/bmad-code-org/bmad-method-test-architecture-enterprise) v1 line** up to "
        "**1.19.0** — auto-bmad couples to those skills' contracts rather than pinned versions.\n"
    )
    bm_s, bm_p = parse_baseline_from_readme(two_pkg, "bmad-method")
    check("windowed: bmad-method stable", bm_s == "6.8.0")
    check("windowed: bmad-method prerelease", bm_p == "6.8.1-next.9")
    tea_s, tea_p = parse_baseline_from_readme(two_pkg, "bmad-method-test-architecture-enterprise")
    check("windowed: TEA stable scoped to its clause", tea_s == "1.19.0")
    check("windowed: TEA has no prerelease (next sorts below stable)", tea_p is None)
    miss_s, miss_p = parse_baseline_from_readme(
        "> **Compatibility:** only **6.8.0** here.", "bmad-method-test-architecture-enterprise")
    check("windowed: absent clause -> (None, None)", miss_s is None and miss_p is None)

    # PACKAGES integrity — distinct, non-substring repo slugs (windowing depends on it)
    slugs = [m["repo"] for m in PACKAGES.values()]
    check("packages: repo slugs distinct", len(set(slugs)) == len(slugs))
    check("packages: no slug is a substring of another",
          not any(a != b and a in b for a in slugs for b in slugs))

    # Combined verdict — worst-of, so a TEA break isn't masked by a clean BMAD line
    check("verdict: worst-of needs-attention > compatible",
          max(["compatible", "needs-attention"], key=lambda v: VERDICT_RANK[v]) == "needs-attention")
    check("verdict: worst-of review-opportunities > up-to-date",
          max(["up-to-date", "review-opportunities"], key=lambda v: VERDICT_RANK[v])
          == "review-opportunities")

    # prerelease anchoring — only diff what's genuinely new since the last check
    check("anchor: no live prerelease -> skip",
          prerelease_anchor("6.8.0", "6.8.1-next.2", None) is None)
    check("anchor: unchanged since last check -> skip",
          prerelease_anchor("6.8.0", "6.8.1-next.2", "6.8.1-next.2") is None)
    check("anchor: new prerelease on same line -> anchor at last-checked prerelease",
          prerelease_anchor("6.8.0", "6.8.1-next.2", "6.8.1-next.3") == "6.8.1-next.2")
    check("anchor: prerelease graduated + new line -> anchor at stable (no double-report)",
          prerelease_anchor("6.8.1", "6.8.1-next.2", "6.8.2-next.1") == "6.8.1")
    check("anchor: no prior prerelease recorded -> anchor at stable",
          prerelease_anchor("6.8.0", None, "6.8.1-next.1") == "6.8.0")

    # stable anchoring — symmetric: don't re-show prerelease content when it graduates
    check("stable-anchor: no new stable -> skip",
          stable_anchor("6.8.0", "6.8.1-next.2", "6.8.0") is None)
    check("stable-anchor: prerelease graduated -> anchor at it (sliver only)",
          stable_anchor("6.8.0", "6.8.1-next.2", "6.8.1") == "6.8.1-next.2")
    check("stable-anchor: no prior prerelease -> anchor at prev stable",
          stable_anchor("6.8.0", None, "6.8.1") == "6.8.0")
    check("stable-anchor: future-line prerelease ignored for this stable",
          stable_anchor("6.8.0", "6.9.0-next.1", "6.8.1") == "6.8.0")
    check("stable-anchor: prerelease already below baseline ignored",
          stable_anchor("6.8.1", "6.8.1-next.2", "6.9.0") == "6.8.1")

    # version availability — drives the graceful degrade when a recorded
    # prerelease has since been unpublished (anchor falls back to stable)
    reg = {"versions": {"6.8.0": {}, "6.8.1-next.2": {}}}
    check("has_version: present", _has_version(reg, "6.8.0"))
    check("has_version: pulled prerelease", not _has_version(reg, "6.8.1-next.1"))

    # gitHead pinning — lets Step 3 read the exact commit window for a tagless prerelease
    reg2 = {"versions": {"6.8.0": {"gitHead": "abc123"}, "6.8.1-next.2": {}}}
    check("git_head: present", _git_head(reg2, "6.8.0") == "abc123")
    check("git_head: not recorded -> None", _git_head(reg2, "6.8.1-next.2") is None)
    check("git_head: unknown version -> None", _git_head(reg2, "9.9.9") is None)
    check("git_head: None version -> None", _git_head(reg2, None) is None)

    # unified diff truncation
    big = unified("f", b"a\n" * 50, b"b\n" * 50, max_lines=10)
    check("unified: truncates", "truncated" in big)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        return 1
    print("All self-tests passed.")
    return 0


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true", help="run hermetic checks and exit")
    ap.add_argument("--report", action="store_true",
                    help="fetch + diff + classify BOTH packages (bmad-method + TEA) (network)")
    ap.add_argument("--baseline", help="bmad-method last-verified stable (e.g. 6.8.0); "
                                       "defaults to the README compat blockquote via --readme")
    ap.add_argument("--prev-prerelease", help="bmad-method last-checked prerelease (e.g. 6.8.1-next.2); "
                                              "defaults to the README compat blockquote via --readme")
    ap.add_argument("--tea-baseline", help="TEA last-verified stable (e.g. 1.19.0); "
                                           "defaults to the README compat blockquote via --readme")
    ap.add_argument("--tea-prev-prerelease", help="TEA last-checked prerelease (e.g. 1.20.0-next.1); "
                                                  "defaults to the README compat blockquote via --readme")
    ap.add_argument("--readme", help="path to README.md to read both packages' baselines from")
    ap.add_argument("--refs", nargs="*", default=[],
                    help="reference docs to derive the delegated-skill surface from")
    ap.add_argument("--max-diff-lines", type=int, default=160,
                    help="cap unified-diff length per file")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    if not args.report:
        ap.error("nothing to do: pass --report or --self-test")

    # Per-package CLI overrides; everything else comes from the README blockquote.
    overrides = {
        "bmad-method": (args.baseline, args.prev_prerelease),
        "bmad-method-test-architecture-enterprise": (args.tea_baseline, args.tea_prev_prerelease),
    }
    readme_text = None
    if args.readme:
        with open(args.readme, encoding="utf-8") as fh:
            readme_text = fh.read()

    specs = []
    for package in PACKAGES:
        baseline, prev_prerelease = overrides.get(package, (None, None))
        if readme_text is not None and (not baseline or prev_prerelease is None):
            r_stable, r_pre = parse_baseline_from_readme(readme_text, package)
            baseline = baseline or r_stable
            if prev_prerelease is None:
                prev_prerelease = r_pre
        specs.append((package, baseline, prev_prerelease))

    if not any(b for _, b, _ in specs):
        ap.error("could not determine any baseline: pass --readme, --baseline, or --tea-baseline")

    surface = []
    for path in args.refs:
        try:
            with open(path, encoding="utf-8") as fh:
                surface += derive_surface(fh.read())
        except OSError:
            pass
    surface = sorted(set(surface)) or FALLBACK_SURFACE

    report = build_combined_report(specs, surface, args.max_diff_lines)
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
