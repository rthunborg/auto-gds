#!/usr/bin/env python3
"""Detect (and additively heal) drift between auto-bmad's shipped config defaults
and a project's runtime ``config.yaml``.

The runtime config (``{output_folder}/auto-bmad/config.yaml``) is seeded **once**
at first run by copying the ``profiles:`` and ``phase_profiles:`` blocks from
``assets/agents/profiles.yaml`` verbatim, and stamping ``profiles_source_version``
with the module version. A later module update ships NEW keys (e.g. a new
``phase_profiles`` mapping like ``tea_triage``) into the asset — but nothing ever
re-touches the runtime copy, so the project silently runs on a stale snapshot.

``render-agents.py --check`` cannot catch this: it only re-renders the four
``ab-*`` *agent files* and never reads ``phase_profiles`` at all (its parser stops
at the next top-level key). So a phase whose ``phase_profiles`` mapping is missing
from the runtime config has no profile to resolve, and no existing check flags it.

This script closes that gap on a **different axis** from the agent-file freshness
check: it diffs the asset's ``profiles`` / ``phase_profiles`` *keys* against the
runtime config's, and compares ``profiles_source_version`` against the installed
``module_version``.

Two modes:
  --check   read-only; report what drifted. Exit 0 fresh, 1 drift, 2 usage error.
  --apply   additively heal: append asset keys the config is MISSING (never touch
            or overwrite a key the user already has — retunes are preserved), then
            restamp ``profiles_source_version``. Writes the config in place.

What ``--apply`` heals automatically (the realistic, safe-to-append cases):
  * ``phase_profiles`` keys present in the asset but absent from the config
    (appended as ``  key: value`` lines at the end of that block);
  * whole ``profiles`` entries present in the asset but absent from the config
    (the asset's raw block is copied verbatim to the end of the ``profiles:`` block).
What it reports but does NOT rewrite (``manual_review`` — rare, value-bearing, and
a mid-block insert would risk mangling a user-edited profile): sub-keys missing
from a profile that already exists in the config (e.g. the asset added a new tool
block or metadata field to an existing profile). The orchestrator surfaces these.

Parsing is dependency-free (same block-structured spirit as ``render-agents.py`` /
``story_plan.py``) so no PyYAML is needed. Output: a single JSON object on stdout.

Usage:
    config_plan.py --check --config FILE [--asset-profiles FILE] [--module-yaml FILE | --module-version X.Y.Z]
    config_plan.py --apply --config FILE [--asset-profiles FILE] [--module-yaml FILE | --module-version X.Y.Z]
    config_plan.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path


def _strip_comment(s: str) -> str:
    """Drop a trailing ` # comment` (must be preceded by whitespace)."""
    m = re.search(r"\s+#", s)
    if m:
        s = s[: m.start()]
    return s.rstrip()


def _strip_value(val: str) -> str:
    """Strip an inline trailing comment and surrounding quotes from a scalar."""
    val = _strip_comment(val).strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1]
    return val.strip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank_or_comment(line: str) -> bool:
    s = line.strip()
    return (not s) or s.startswith("#")


def find_block(lines: Sequence[str], name: str) -> tuple[int, int] | None:
    """Locate a top-level ``name:`` block.

    Returns ``(header_idx, body_end)`` where the body is ``lines[header_idx+1:body_end]``
    and ``body_end`` is the first non-blank, non-comment, indent-0 line after the
    header (or ``len(lines)``). Blank lines and full-line comments are transparent —
    they never terminate a block. Returns ``None`` if the block is absent.
    """
    header: int | None = None
    for i, line in enumerate(lines):
        if _is_blank_or_comment(line):
            continue
        ind = _indent(line)
        stripped = _strip_comment(line.strip())
        if header is None:
            if ind == 0 and stripped == f"{name}:":
                header = i
            continue
        if ind == 0:
            return (header, i)
    return (header, len(lines)) if header is not None else None


def _last_content_idx(lines: Sequence[str], start: int, end: int) -> int | None:
    """Index of the last non-blank, indent>0 line in ``lines[start:end]``."""
    last = None
    for i in range(start, end):
        if not _is_blank_or_comment(lines[i]) and _indent(lines[i]) > 0:
            last = i
    return last


def parse_phase_profiles(lines: Sequence[str], span: tuple[int, int] | None) -> dict:
    """Parse ``key: value`` mappings (indent 2) inside the phase_profiles block."""
    out: dict = {}
    if span is None:
        return out
    header, end = span
    for i in range(header + 1, end):
        line = lines[i]
        if _is_blank_or_comment(line) or _indent(line) != 2:
            continue
        stripped = _strip_comment(line.strip())
        if ":" in stripped:
            k, _, v = stripped.partition(":")
            out[k.strip()] = _strip_value(v)
    return out


def parse_profiles_blocks(lines: Sequence[str], span: tuple[int, int] | None) -> dict:
    """Parse the profiles block into ``name -> {start, end, keys}``.

    ``start``/``end`` bound the profile's raw lines (``end`` exclusive, trailing
    blank/comment lines trimmed) so a whole missing profile can be copied verbatim.
    ``keys`` is the set of structural sub-keys present (``meta:<k>`` for a per-profile
    scalar like ``description``; ``<tool>:<k>`` for a tool sub-key like ``claude:model``)
    — used to spot sub-keys an existing profile is missing.
    """
    profiles: dict = {}
    if span is None:
        return profiles
    header, end = span

    order: list[str] = []
    starts: dict[str, int] = {}
    cur: str | None = None
    cur_tool: str | None = None
    for i in range(header + 1, end):
        line = lines[i]
        if _is_blank_or_comment(line):
            continue
        ind = _indent(line)
        stripped = _strip_comment(line.strip())
        if ind == 2 and stripped.endswith(":"):
            cur = stripped[:-1].strip()
            cur_tool = None
            order.append(cur)
            starts[cur] = i
            profiles[cur] = {"start": i, "end": end, "keys": set()}
        elif ind == 4 and cur is not None:
            if stripped.endswith(":") and not stripped.lstrip().startswith("{"):
                cur_tool = stripped[:-1].strip()
                profiles[cur]["keys"].add(f"{cur_tool}:")
            elif ":" in stripped:
                key, _, val = stripped.partition(":")
                val = val.strip()
                if val.startswith("{"):  # inline tool map: tool: {model: .., effort: ..}
                    tool = key.strip()
                    profiles[cur]["keys"].add(f"{tool}:")
                    for part in val.strip("{} ").split(","):
                        if ":" in part:
                            sk = part.partition(":")[0]
                            profiles[cur]["keys"].add(f"{tool}:{sk.strip()}")
                    cur_tool = None
                else:  # per-profile scalar metadata
                    profiles[cur]["keys"].add(f"meta:{key.strip()}")
                    cur_tool = None
        elif ind >= 6 and cur is not None and cur_tool is not None and ":" in stripped:
            key = stripped.partition(":")[0]
            profiles[cur]["keys"].add(f"{cur_tool}:{key.strip()}")

    # Trim each profile's end to the line after its last content line.
    for idx, name in enumerate(order):
        block_end = starts[order[idx + 1]] if idx + 1 < len(order) else end
        last = _last_content_idx(lines, starts[name], block_end)
        profiles[name]["end"] = (last + 1) if last is not None else starts[name] + 1
    return profiles


def _read_version(text: str, key: str) -> str | None:
    for line in text.splitlines():
        if _indent(line) == 0:
            stripped = _strip_comment(line.strip())
            if stripped.startswith(f"{key}:"):
                return _strip_value(stripped.partition(":")[2])
    return None


def _ver_tuple(v: str | None) -> tuple:
    if not v:
        return ()
    out: list[int] = []
    for part in str(v).split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def analyze(config_text: str, asset_text: str, config_version: str | None, module_version: str | None) -> dict:
    """Diff the asset's profiles/phase_profiles keys against the config's."""
    cfg_lines = config_text.splitlines(keepends=True)
    asset_lines = asset_text.splitlines(keepends=True)

    cfg_pp = parse_phase_profiles(cfg_lines, find_block(cfg_lines, "phase_profiles"))
    asset_pp = parse_phase_profiles(asset_lines, find_block(asset_lines, "phase_profiles"))
    missing_pp = {k: v for k, v in asset_pp.items() if k not in cfg_pp}

    cfg_prof = parse_profiles_blocks(cfg_lines, find_block(cfg_lines, "profiles"))
    asset_prof = parse_profiles_blocks(asset_lines, find_block(asset_lines, "profiles"))
    missing_profiles = [name for name in asset_prof if name not in cfg_prof]
    manual_review: list[dict] = []
    for name, ainfo in asset_prof.items():
        if name in cfg_prof:
            for key in sorted(ainfo["keys"] - cfg_prof[name]["keys"]):
                if key.endswith(":"):  # a tool *block* header alone — its sub-keys cover it
                    continue
                manual_review.append({"profile": name, "missing_key": key})

    cver = _ver_tuple(config_version)
    mver = _ver_tuple(module_version)
    version_drift = bool(module_version) and config_version != module_version
    config_older = bool(module_version) and (not config_version or cver < mver)

    needs_reseed = bool(missing_pp or missing_profiles)
    return {
        "missing_phase_profiles": missing_pp,
        "missing_profiles": missing_profiles,
        "manual_review": manual_review,
        "version": {
            "config": config_version,
            "module": module_version,
            "drift": version_drift,
            "config_older": config_older,
        },
        "needs_reseed": needs_reseed,
        "_asset_profiles": asset_prof,  # internal, for apply()
        "_asset_lines": asset_lines,    # internal, for apply()
    }


def _ensure_newline(lines: list[str], idx: int) -> None:
    if lines and not lines[idx].endswith("\n"):
        lines[idx] = lines[idx] + "\n"


def apply(config_text: str, asset_text: str, config_version: str | None, module_version: str | None) -> dict:
    """Additively heal the config: append missing keys, restamp the version."""
    info = analyze(config_text, asset_text, config_version, module_version)
    lines = config_text.splitlines(keepends=True)
    asset_lines = info["_asset_lines"]
    asset_prof = info["_asset_profiles"]

    inserts: list[tuple[int, list[str]]] = []  # (insert-after index, new lines)

    # Missing whole profiles -> copy the asset's raw block to the profiles block end.
    if info["missing_profiles"]:
        span = find_block(lines, "profiles")
        if span is not None:
            header, end = span
            anchor = _last_content_idx(lines, header + 1, end)
            anchor = anchor if anchor is not None else header
            block: list[str] = []
            for name in info["missing_profiles"]:
                p = asset_prof[name]
                block.append("\n")
                block.extend(asset_lines[p["start"]: p["end"]])
            inserts.append((anchor, block))

    # Missing phase_profiles keys -> append `  key: value` lines to that block end.
    if info["missing_phase_profiles"]:
        span = find_block(lines, "phase_profiles")
        if span is not None:
            header, end = span
            anchor = _last_content_idx(lines, header + 1, end)
            anchor = anchor if anchor is not None else header
            block = [f"  {k}: {v}\n" for k, v in info["missing_phase_profiles"].items()]
            inserts.append((anchor, block))

    # Apply inserts bottom-up so earlier indices stay valid.
    for anchor, block in sorted(inserts, key=lambda t: t[0], reverse=True):
        _ensure_newline(lines, anchor)
        lines[anchor + 1: anchor + 1] = block

    # Restamp profiles_source_version (content-based, robust to the splices above).
    restamped = None
    if module_version and config_version != module_version:
        restamped = _restamp_version(lines, module_version)

    return {
        "new_text": "".join(lines),
        "reseeded_phase_profiles": info["missing_phase_profiles"],
        "reseeded_profiles": info["missing_profiles"],
        "manual_review": info["manual_review"],
        "version_restamped": restamped,
    }


def _restamp_version(lines: list[str], new_version: str) -> dict:
    """Set/insert top-level ``profiles_source_version``, preserving a trailing comment."""
    for i, line in enumerate(lines):
        if _indent(line) != 0:
            continue
        stripped = _strip_comment(line.strip())
        if stripped.startswith("profiles_source_version:"):
            old = _strip_value(stripped.partition(":")[2])
            comment = ""
            m = re.search(r"\s+#", line.rstrip("\n"))
            if m:
                comment = "  " + line.rstrip("\n")[m.start():].strip()
            lines[i] = f'profiles_source_version: "{new_version}"{comment}\n'
            return {"from": old, "to": new_version}
    # Absent: insert after the top-level `version:` line, else at the very top.
    for i, line in enumerate(lines):
        if _indent(line) == 0 and _strip_comment(line.strip()).startswith("version:"):
            _ensure_newline(lines, i)
            lines.insert(i + 1, f'profiles_source_version: "{new_version}"\n')
            return {"from": None, "to": new_version}
    lines.insert(0, f'profiles_source_version: "{new_version}"\n')
    return {"from": None, "to": new_version}


def _default_asset_profiles() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "agents" / "profiles.yaml"


def _default_module_yaml() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "module.yaml"


def _public(info: dict) -> dict:
    """Strip the internal underscore-prefixed keys from an analyze() result."""
    return {k: v for k, v in info.items() if not k.startswith("_")}


def _run_self_test() -> int:
    asset = _default_asset_profiles()
    assert asset.is_file(), f"shipped profiles.yaml missing at {asset}"
    asset_text = asset.read_text(encoding="utf-8")

    # The shipped asset must define the canonical phase_profiles keys + 4 profiles.
    a_pp = parse_phase_profiles(asset_text.splitlines(keepends=True), find_block(asset_text.splitlines(keepends=True), "phase_profiles"))
    for k in ("create_story", "dev_story", "tea_triage", "tea_per_story", "tea_epic", "project_context", "retrospective"):
        assert k in a_pp, f"asset phase_profiles missing {k}: {sorted(a_pp)}"
    a_prof = parse_profiles_blocks(asset_text.splitlines(keepends=True), find_block(asset_text.splitlines(keepends=True), "profiles"))
    for name in ("ab-xhigh", "ab-high", "ab-alt-xhigh", "ab-alt-high"):
        assert name in a_prof, f"asset profiles missing {name}"
        assert "claude:model" in a_prof[name]["keys"], a_prof[name]["keys"]
        assert "codex:reasoning_effort" in a_prof[name]["keys"], a_prof[name]["keys"]

    # find_block: blank lines / comments are transparent; next top-level key ends it.
    sample = "version: 1\nphase_profiles:\n  a: x\n\n  # note\n  b: y\ngit:\n  mode: auto\n".splitlines(keepends=True)
    sp = find_block(sample, "phase_profiles")
    assert sp is not None and parse_phase_profiles(sample, sp) == {"a": "x", "b": "y"}, sp

    # --- A config seeded from an OLDER snapshot: missing tea_triage, older version. ---
    stale_cfg = (
        'version: 1\n'
        'profiles_source_version: "0.8.0"  # seeded snapshot\n'
        'delegation:\n'
        '  host: auto\n'
        'profiles:\n'
        '  ab-xhigh:\n'
        '    description: "deep"\n'
        '    role_blurb: "deep work"\n'
        '    status_example: "ok"\n'
        '    claude:\n'
        '      model: haiku\n'        # user RETUNE — must be preserved
        '      effort: low\n'
        '    codex:\n'
        '      model: gpt-x\n'
        '      reasoning_effort: medium\n'
        '  ab-high:\n'
        '    description: "infra"\n'
        '    role_blurb: "infra work"\n'
        '    status_example: "ok"\n'
        '    claude:\n'
        '      model: opus\n'
        '      effort: high\n'
        '    codex:\n'
        '      model: gpt-x\n'
        '      reasoning_effort: high\n'
        'phase_profiles:\n'
        '  create_story: ab-xhigh\n'
        '  dev_story: ab-xhigh\n'
        'git:\n'
        '  mode: auto\n'
    )

    info = analyze(stale_cfg, asset_text, "0.8.0", "0.9.0")
    pub = _public(info)
    assert "tea_triage" in pub["missing_phase_profiles"], pub["missing_phase_profiles"]
    assert pub["missing_phase_profiles"]["tea_triage"] == "ab-alt-high", pub
    # ab-alt-xhigh / ab-alt-high absent from the stale config => flagged as whole missing profiles.
    assert set(pub["missing_profiles"]) == {"ab-alt-xhigh", "ab-alt-high"}, pub["missing_profiles"]
    assert pub["needs_reseed"] is True, pub
    assert pub["version"]["drift"] is True and pub["version"]["config_older"] is True, pub

    # --- apply(): additive heal. ---
    res = apply(stale_cfg, asset_text, "0.8.0", "0.9.0")
    healed = res["new_text"]
    assert res["version_restamped"] == {"from": "0.8.0", "to": "0.9.0"}, res["version_restamped"]
    assert 'profiles_source_version: "0.9.0"  # seeded snapshot' in healed, "comment not preserved"

    h_lines = healed.splitlines(keepends=True)
    h_pp = parse_phase_profiles(h_lines, find_block(h_lines, "phase_profiles"))
    for k, v in a_pp.items():
        assert h_pp.get(k) == v, f"phase_profiles not healed for {k}: got {h_pp.get(k)}"
    # User retune preserved: ab-xhigh.claude.model stays haiku, NOT reset to the asset's opus.
    h_prof = parse_profiles_blocks(h_lines, find_block(h_lines, "profiles"))
    assert set(("ab-xhigh", "ab-high", "ab-alt-xhigh", "ab-alt-high")).issubset(set(h_prof)), sorted(h_prof)
    assert "model: haiku" in healed and "effort: low" in healed, "user retune clobbered"
    # The healed asset profiles carry their real descriptions (verbatim copy).
    assert "lighter-weight" in healed, "ab-alt-high block not copied verbatim"
    # Other config blocks survive intact.
    assert "delegation:" in healed and "git:" in healed and "mode: auto" in healed, healed

    # Re-analyzing the healed config against the same asset => fully fresh.
    info2 = analyze(healed, asset_text, "0.9.0", "0.9.0")
    assert not info2["needs_reseed"], _public(info2)
    assert not info2["missing_phase_profiles"] and not info2["missing_profiles"], _public(info2)
    assert info2["version"]["drift"] is False, info2["version"]
    assert not info2["manual_review"], info2["manual_review"]

    # A config built straight from the asset (just stamped) is fully fresh.
    fresh_from_asset = 'profiles_source_version: "0.9.0"\n' + asset_text
    info_fresh = analyze(fresh_from_asset, asset_text, "0.9.0", "0.9.0")
    assert not info_fresh["needs_reseed"], _public(info_fresh)
    assert not info_fresh["manual_review"], info_fresh["manual_review"]
    assert info_fresh["version"]["drift"] is False, info_fresh["version"]

    # --- manual_review: an existing profile missing a sub-key the asset has. ---
    # Drop ONLY ab-xhigh's claude.effort from an otherwise-complete config.
    cfg_subkey = fresh_from_asset.replace(
        "      model: opus\n      effort: xhigh\n", "      model: opus\n", 1
    )
    assert cfg_subkey != fresh_from_asset, "fixture: ab-xhigh claude.effort line not found to drop"
    info3 = analyze(cfg_subkey, asset_text, "0.9.0", "0.9.0")
    assert not info3["needs_reseed"], _public(info3)  # all profiles + phase_profiles still present
    assert not info3["missing_profiles"], info3["missing_profiles"]
    assert any(m["profile"] == "ab-xhigh" and m["missing_key"] == "claude:effort" for m in info3["manual_review"]), info3["manual_review"]
    # manual_review alone is not auto-reseeded, and apply() leaves the profile untouched.
    res3 = apply(cfg_subkey, asset_text, "0.9.0", "0.9.0")
    assert not res3["reseeded_profiles"], res3
    assert "claude:effort" in {m["missing_key"] for m in res3["manual_review"]}, res3

    # --- version stamp absent entirely (very old config) => inserted after `version:`. ---
    no_stamp = "version: 1\nprofiles:\n  ab-xhigh:\n    claude:\n      model: opus\n      effort: xhigh\n"
    res4 = apply(no_stamp, asset_text, None, "0.9.0")
    assert res4["version_restamped"] == {"from": None, "to": "0.9.0"}, res4["version_restamped"]
    assert re.search(r'version: 1\nprofiles_source_version: "0\.9\.0"', res4["new_text"]), res4["new_text"][:120]

    # --- no module version supplied => no version drift signalled, no restamp. ---
    info5 = analyze(healed, asset_text, "0.9.0", None)
    assert info5["version"]["drift"] is False and info5["version"]["config_older"] is False, info5["version"]
    res5 = apply(healed, asset_text, "0.9.0", None)
    assert res5["version_restamped"] is None, res5["version_restamped"]

    # --- end-to-end via the file-driven check()/apply_to_file() on a temp dir. ---
    with tempfile.TemporaryDirectory() as td:
        cfgp = Path(td) / "config.yaml"
        cfgp.write_text(stale_cfg, encoding="utf-8")
        chk = check_file(cfgp, asset, "0.9.0")
        assert chk["status"] == "drift" and chk["needs_reseed"], chk
        app = apply_to_file(cfgp, asset, "0.9.0")
        assert app["status"] == "applied", app
        chk2 = check_file(cfgp, asset, "0.9.0")
        assert chk2["status"] == "fresh", chk2

    print("SELF-TEST PASSED (all assertions)")
    return 0


def check_file(config_path: Path, asset_path: Path, module_version: str | None) -> dict:
    config_text = config_path.read_text(encoding="utf-8")
    asset_text = asset_path.read_text(encoding="utf-8")
    config_version = _read_version(config_text, "profiles_source_version")
    info = _public(analyze(config_text, asset_text, config_version, module_version))
    non_fresh = info["needs_reseed"] or info["version"]["drift"] or bool(info["manual_review"])
    info["status"] = "drift" if non_fresh else "fresh"
    info["config_path"] = str(config_path)
    info["asset_path"] = str(asset_path)
    return info


def apply_to_file(config_path: Path, asset_path: Path, module_version: str | None) -> dict:
    config_text = config_path.read_text(encoding="utf-8")
    asset_text = asset_path.read_text(encoding="utf-8")
    config_version = _read_version(config_text, "profiles_source_version")
    res = apply(config_text, asset_text, config_version, module_version)
    changed = bool(res["reseeded_phase_profiles"] or res["reseeded_profiles"] or res["version_restamped"])
    if changed:
        config_path.write_text(res["new_text"], encoding="utf-8")
    return {
        "status": "applied" if changed else "noop",
        "reseeded_phase_profiles": res["reseeded_phase_profiles"],
        "reseeded_profiles": res["reseeded_profiles"],
        "version_restamped": res["version_restamped"],
        "manual_review": res["manual_review"],
        "config_path": str(config_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect/heal auto-bmad runtime config drift vs the shipped asset.")
    parser.add_argument("--self-test", action="store_true", help="Run internal tests and exit.")
    parser.add_argument("--check", action="store_true", help="Report drift (read-only). Exit 1 if drift.")
    parser.add_argument("--apply", action="store_true", help="Additively heal the config in place.")
    parser.add_argument("--config", help="Runtime config.yaml to inspect/heal.")
    parser.add_argument("--asset-profiles", help="Shipped profiles.yaml. Default: assets/agents/profiles.yaml next to this script.")
    parser.add_argument("--module-yaml", help="module.yaml to read module_version from. Default: assets/module.yaml next to this script.")
    parser.add_argument("--module-version", help="Override the module version (else read from --module-yaml).")
    args = parser.parse_args()

    if args.self_test:
        return _run_self_test()

    if not (args.check or args.apply):
        print(json.dumps({"status": "error", "message": "one of --check / --apply / --self-test is required"}))
        return 2
    if not args.config:
        print(json.dumps({"status": "error", "message": "--config is required"}))
        return 2

    config_path = Path(args.config)
    if not config_path.is_file():
        print(json.dumps({"status": "error", "message": f"config not found: {config_path}"}))
        return 2
    asset_path = Path(args.asset_profiles) if args.asset_profiles else _default_asset_profiles()
    if not asset_path.is_file():
        print(json.dumps({"status": "error", "message": f"asset profiles not found: {asset_path}"}))
        return 2

    module_version = args.module_version
    if not module_version:
        myaml = Path(args.module_yaml) if args.module_yaml else _default_module_yaml()
        if myaml.is_file():
            module_version = _read_version(myaml.read_text(encoding="utf-8"), "module_version")

    if args.apply:
        result = apply_to_file(config_path, asset_path, module_version)
        print(json.dumps(result, indent=2))
        return 0

    result = check_file(config_path, asset_path, module_version)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "drift" else 0


if __name__ == "__main__":
    sys.exit(main())
