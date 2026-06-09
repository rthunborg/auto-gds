#!/usr/bin/env python3
"""Resolve an external-CLI delegation for one auto-bmad pipeline phase.

Most auto-bmad steps run in an *in-tool* sub-agent (the three tiers in
``delegation-runtime.md``). As an **opt-in, per-phase** alternative, a phase can
instead be delegated to an **external CLI** — ``claude -p`` or ``codex exec`` —
chosen by the ``delegation.cli_phases`` map in the runtime config::

    delegation:
      cli_phases:
        code_review_review_secondary: codex   # run this phase on `codex exec`
        retrospective: codex

The value names the *tool* (``claude`` | ``codex``); model + effort come from
that tool's block of the phase's profile (``phase_profiles[phase]`` ->
``profiles[<profile>][<tool>]``), exactly the same numbers ``render-agents.py``
bakes into the in-tool delegate files. Nothing here changes the profiles or the
three existing tiers — a phase absent from ``cli_phases`` is reported
``routed: false`` and the orchestrator uses its normal tier.

This script does two things and prints ONE JSON object on stdout:

  * ``resolve()`` — PURE (no subprocess, no filesystem): from the config text it
    builds the tool, model, effort, the **argv** (without the prompt — the
    orchestrator pipes the assembled delegate prompt to the child's stdin), the
    ``cwd``, an OS-temp **capture-log** path (NEVER inside the repo, so transient
    stdout can't be swept into a commit/PR), and how to read the structured
    result back (claude: parse ``.result`` from the JSON envelope; codex: read
    the ``-o`` last-message file). The per-tool flag divergence lives here, in
    tested code, not in orchestrator prose.
  * ``validate()`` — LIVE checks the orchestrator must pass before relying on a
    routed phase (it hard-stops up front, never mid-pipeline): the CLI binary is
    on PATH, that tool's BMAD skills are installed, and — for the *non-host* tool
    (the host the orchestrator runs in is authed by definition) — the CLI is
    actually logged in (``claude auth status`` / ``codex login status``).

Command shapes are spike-confirmed (see the plan / delegation-runtime.md):
  claude:  claude -p --model M --effort E --output-format json --dangerously-skip-permissions
  codex:   codex exec -m M -c model_reasoning_effort=E -s workspace-write -C ROOT -o LASTMSG --ephemeral

Usage:
    cli_delegate.py --phase PHASE --config FILE --project-root DIR \\
        [--story-key KEY] [--host claude-code|codex] [--no-auth-probe]
    cli_delegate.py --self-test

Exit codes: 0 = routed and all validations passed (or routed:false, a clean
"use the normal tier" answer); 1 = routed but a validation failed (hard-stop);
2 = usage / resolution error (bad config, unknown phase, missing profile block).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

# Phases that may be routed: the same keys as phase_profiles. (Git/finalize work
# is orchestrator-owned and never delegated, so it is not routable.)
TOOL_BINARY = {"claude": "claude", "codex": "codex"}
# host (delegation.host) <-> the tool name it IS, so we can skip the auth probe
# for the host the orchestrator already runs inside.
_HOST_TOOL = {"claude-code": "claude", "codex": "codex"}
_AUTH_PROBE_TIMEOUT = 20  # seconds — keep short so a wedged probe can't hang preflight


# --- dependency-free YAML-ish parsing (same style as config_plan.py / render-agents.py) ---

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
    """Locate a top-level ``name:`` block -> ``(header_idx, body_end)`` or None."""
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


def _parse_inline_map(body: str) -> dict:
    """Parse ``k: v, k2: v2`` (inside of a flow map) into a dict."""
    out: dict = {}
    for part in body.split(","):
        if ":" in part:
            k, _, v = part.partition(":")
            if k.strip():
                out[k.strip()] = _strip_value(v)
    return out


def parse_phase_profiles(lines: Sequence[str]) -> dict:
    """Parse the top-level ``phase_profiles:`` ``key: value`` map (indent 2)."""
    span = find_block(lines, "phase_profiles")
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


def parse_profiles(text: str) -> dict:
    """Extract the ``profiles:`` block (block or inline tool maps), dependency-free.

    Returns ``{profile: {scalar_key: value | tool: {key: value}}}``. Other
    top-level keys are ignored. Mirrors ``render-agents.py``'s parser so the two
    read the shipped/config profiles identically.
    """
    profiles: dict = {}
    in_block = False
    cur_profile: str | None = None
    cur_tool: str | None = None
    inline_re = re.compile(r"^([\w-]+):\s*\{(.*)\}\s*$")

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = _indent(raw)
        stripped = _strip_comment(raw.strip())
        if not in_block:
            if indent == 0 and stripped == "profiles:":
                in_block = True
            continue
        if indent == 0:
            break
        if indent == 2 and stripped.endswith(":"):
            cur_profile = stripped[:-1].strip()
            profiles[cur_profile] = {}
            cur_tool = None
        elif indent == 4 and cur_profile is not None:
            m = inline_re.match(stripped)
            if m:
                profiles[cur_profile][m.group(1).strip()] = _parse_inline_map(m.group(2))
                cur_tool = None
            elif stripped.endswith(":"):
                cur_tool = stripped[:-1].strip()
                profiles[cur_profile][cur_tool] = {}
            elif ":" in stripped:
                key, _, val = stripped.partition(":")
                profiles[cur_profile][key.strip()] = _strip_value(val)
                cur_tool = None
        elif indent >= 6 and ":" in stripped and cur_profile is not None and cur_tool is not None:
            key, _, val = stripped.partition(":")
            profiles[cur_profile][cur_tool][key.strip()] = _strip_value(val)
    return profiles


def parse_cli_phases(lines: Sequence[str]) -> dict:
    """Parse ``delegation.cli_phases`` -> ``{phase: tool}`` (absent/empty => {}).

    Supports the block form::

        delegation:
          cli_phases:
            dev_story: codex

    and the inline form ``cli_phases: { dev_story: codex }`` / ``cli_phases: {}``.
    """
    span = find_block(lines, "delegation")
    if span is None:
        return {}
    header, end = span
    for i in range(header + 1, end):
        line = lines[i]
        if _is_blank_or_comment(line) or _indent(line) != 2:
            continue
        stripped = _strip_comment(line.strip())
        if not (stripped == "cli_phases:" or stripped.startswith("cli_phases:")):
            continue
        # Found the cli_phases key at indent 2.
        _, _, rest = stripped.partition(":")
        rest = rest.strip()
        if rest.startswith("{"):  # inline flow map (possibly empty `{}`)
            inner = rest.strip()[1:-1] if rest.endswith("}") else rest.strip()[1:]
            return _parse_inline_map(inner)
        # Block form: collect indent-4 `phase: tool` lines until the next
        # indent<=2 key (still inside the delegation block).
        out: dict = {}
        for j in range(i + 1, end):
            sub = lines[j]
            if _is_blank_or_comment(sub):
                continue
            if _indent(sub) <= 2:
                break
            if _indent(sub) == 4 and ":" in sub:
                k, _, v = _strip_comment(sub.strip()).partition(":")
                if k.strip():
                    out[k.strip()] = _strip_value(v)
        return out
    return {}


# --- resolution (PURE: no subprocess, no filesystem) ---

def _safe_name(s: str) -> str:
    """Filesystem-safe token for a capture filename."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", s) or "x"


def _capture_dir() -> Path:
    """OS temp dir for capture logs — NEVER inside the repo."""
    return Path(tempfile.gettempdir()) / "auto-bmad-cli"


def resolve(
    phase: str,
    config_text: str,
    project_root: str,
    story_key: str = "story",
    label: str | None = None,
) -> dict:
    """Build the external-CLI plan for ``phase`` from the config text. Pure.

    Returns ``{"routed": False, ...}`` when the phase is not in
    ``delegation.cli_phases`` (the orchestrator then uses the normal tier), or a
    full plan dict (tool/model/effort/argv/cwd/capture/result-source) when it is.
    On a resolution error (unknown phase, bad tool, missing profile block) the
    dict carries a non-empty ``errors`` list and ``routed`` reflects the intent.
    """
    lines = config_text.splitlines()
    cli_phases = parse_cli_phases(lines)
    if phase not in cli_phases:
        return {"routed": False, "phase": phase}

    errors: list[str] = []
    tool_raw = cli_phases[phase].strip()
    tool = "claude" if tool_raw == "claude-code" else tool_raw
    if tool not in TOOL_BINARY:
        errors.append(f"cli_phases[{phase}] = {tool_raw!r}; expected 'claude' or 'codex'")

    phase_profiles = parse_phase_profiles(lines)
    profile = phase_profiles.get(phase)
    if not profile:
        errors.append(f"no phase_profiles mapping for '{phase}'")

    profiles = parse_profiles(config_text)
    model = effort = None
    if profile and tool in TOOL_BINARY:
        prof = profiles.get(profile)
        if not prof:
            errors.append(f"profile '{profile}' not found in profiles block")
        else:
            tool_block = prof.get(tool)
            if not tool_block:
                errors.append(f"profile '{profile}' has no '{tool}' block")
            else:
                model = tool_block.get("model")
                # claude uses `effort`; codex uses `reasoning_effort`.
                effort_key = "effort" if tool == "claude" else "reasoning_effort"
                effort = tool_block.get(effort_key)
                if not model:
                    errors.append(f"profile '{profile}.{tool}.model' missing")
                if not effort:
                    errors.append(f"profile '{profile}.{tool}.{effort_key}' missing")

    root = str(Path(project_root))
    cap_dir = _capture_dir()
    # `label` keeps capture paths distinct when one phase spawns several delegates
    # (the code-review fan-out: 3 lenses + triage all share phase + story_key).
    base = f"{_safe_name(story_key)}-{_safe_name(phase)}"
    if label:
        base += f"-{_safe_name(label)}"
    capture_log = str(cap_dir / f"{base}.log")

    plan: dict = {
        "routed": True,
        "phase": phase,
        "tool": tool,
        "profile": profile,
        "model": model,
        "effort": effort,
        "cwd": root,
        "prompt_via": "stdin",
        "capture_log": capture_log,
        "errors": errors,
    }

    if errors:
        plan["ok"] = False
        return plan

    if tool == "claude":
        plan["argv"] = [
            "claude", "-p",
            "--model", model,
            "--effort", effort,
            "--output-format", "json",
            "--dangerously-skip-permissions",
        ]
        # The JSON envelope lands in capture_log; the structured block is `.result`.
        plan["result_source"] = capture_log
        plan["result_format"] = "json"
        plan["result_field"] = "result"
        plan["error_field"] = "is_error"
    else:  # codex
        last_msg = str(cap_dir / f"{base}.lastmsg")
        plan["argv"] = [
            "codex", "exec",
            "-m", model,
            "-c", f"model_reasoning_effort={effort}",
            "-s", "workspace-write",
            "-C", root,
            "-o", last_msg,
            "--ephemeral",
        ]
        # `-o` writes ONLY the agent's final message — the clean structured block.
        plan["result_source"] = last_msg
        plan["result_format"] = "text"
        plan["result_field"] = None
        plan["error_field"] = None

    return plan


# --- live validation (subprocess + filesystem) ---

def _skills_dirs(tool: str, project_root: Path) -> list[Path]:
    if tool == "claude":
        return [project_root / ".claude" / "skills"]
    # codex skills can live in either project layout, or the user-global dir.
    return [
        project_root / ".agents" / "skills",
        project_root / ".codex" / "skills",
        Path.home() / ".codex" / "skills",
    ]


def _has_bmad_skills(d: Path) -> bool:
    try:
        return d.is_dir() and any(d.glob("bmad-*"))
    except OSError:
        return False


def _probe_auth(tool: str) -> tuple[str, str | None]:
    """Return (status, error). status in ok|failed|unknown."""
    try:
        if tool == "claude":
            p = subprocess.run(
                ["claude", "auth", "status"],
                capture_output=True, text=True, timeout=_AUTH_PROBE_TIMEOUT,
            )
            if p.returncode != 0:
                return "failed", (p.stderr or p.stdout or "").strip()[:200]
            try:
                logged = bool(json.loads(p.stdout).get("loggedIn"))
            except (ValueError, AttributeError):
                logged = '"loggedIn": true' in p.stdout or '"loggedIn":true' in p.stdout
            return ("ok", None) if logged else ("failed", "not logged in")
        else:  # codex
            p = subprocess.run(
                ["codex", "login", "status"],
                capture_output=True, text=True, timeout=_AUTH_PROBE_TIMEOUT,
            )
            out = (p.stdout or "") + (p.stderr or "")
            if p.returncode == 0 and "logged in" in out.lower():
                return "ok", None
            return "failed", out.strip()[:200] or "not logged in"
    except FileNotFoundError:
        return "unknown", "binary not found"
    except subprocess.TimeoutExpired:
        return "unknown", f"auth probe timed out after {_AUTH_PROBE_TIMEOUT}s"
    except OSError as e:  # pragma: no cover - environment dependent
        return "unknown", str(e)[:200]


def validate(
    plan: dict,
    project_root: str,
    host: str | None = None,
    run_auth_probe: bool = True,
) -> dict:
    """Live preflight checks for a routed plan: binary on PATH, skills installed,
    and (for the non-host tool) the CLI is authed. Returns a ``validation`` dict
    and sets ``plan['ok']`` / appends to ``plan['errors']``.
    """
    tool = plan["tool"]
    root = Path(project_root)
    errors: list[str] = list(plan.get("errors") or [])

    binary = TOOL_BINARY.get(tool)
    binary_path = shutil.which(binary) if binary else None
    if not binary_path:
        errors.append(f"CLI binary '{binary}' not on PATH (route {plan['phase']} needs it)")

    dirs = _skills_dirs(tool, root)
    present_dirs = [str(d) for d in dirs if _has_bmad_skills(d)]
    if not present_dirs:
        errors.append(
            f"no BMAD skills found for '{tool}' in any of: {[str(d) for d in dirs]}"
        )

    is_host_tool = host is not None and _HOST_TOOL.get(host) == tool
    if is_host_tool:
        auth, auth_err = "skipped (host tool)", None
    elif not run_auth_probe:
        auth, auth_err = "skipped (probe disabled)", None
    elif not binary_path:
        auth, auth_err = "unknown", "binary not on PATH"
    else:
        auth, auth_err = _probe_auth(tool)
        if auth == "failed":
            errors.append(f"'{tool}' CLI is not authenticated ({auth_err}); run its login first")

    validation = {
        "binary_on_path": bool(binary_path),
        "binary_path": binary_path,
        "skills_present": bool(present_dirs),
        "skills_dirs_checked": [str(d) for d in dirs],
        "skills_dirs_found": present_dirs,
        "auth": auth,
        "auth_error": auth_err,
    }
    plan["validation"] = validation
    plan["errors"] = errors
    plan["ok"] = not errors
    return plan


def _run_self_test() -> int:
    # A representative config: two profiles, a phase map, and a cli_phases route
    # in BLOCK form. claude-routed + codex-routed phases exercise both arms.
    cfg = (
        "version: 1\n"
        "delegation:\n"
        "  host: auto\n"
        "  mode: auto\n"
        "  target_tools:\n"
        "    - claude-code\n"
        "    - codex\n"
        "  cli_phases:\n"
        "    dev_story: codex\n"
        "    create_story: claude\n"
        "tea:\n"
        "  enabled: true\n"
        "profiles:\n"
        "  ab-xhigh:\n"
        "    description: \"big\"\n"
        "    claude:\n"
        "      model: opus\n"
        "      effort: xhigh\n"
        "    codex:\n"
        "      model: gpt-5.5\n"
        "      reasoning_effort: xhigh\n"
        "phase_profiles:\n"
        "  create_story: ab-xhigh\n"
        "  dev_story: ab-xhigh\n"
        "  retrospective: ab-xhigh\n"
    )

    # cli_phases / phase_profiles parsing.
    lines = cfg.splitlines()
    assert parse_cli_phases(lines) == {"dev_story": "codex", "create_story": "claude"}
    assert parse_phase_profiles(lines)["dev_story"] == "ab-xhigh"

    # --- codex arm ---
    cx = resolve("dev_story", cfg, "/proj", story_key="1-2-auth")
    assert cx["routed"] and not cx["errors"], cx
    assert cx["tool"] == "codex" and cx["model"] == "gpt-5.5" and cx["effort"] == "xhigh", cx
    a = cx["argv"]
    assert a[:2] == ["codex", "exec"], a
    assert "-m" in a and a[a.index("-m") + 1] == "gpt-5.5", a
    # codex effort is set via `-c model_reasoning_effort=`, NEVER `--effort`.
    assert "-c" in a and "model_reasoning_effort=xhigh" in a, a
    assert "--effort" not in a, a
    assert "-s" in a and a[a.index("-s") + 1] == "workspace-write", a
    assert "-C" in a and a[a.index("-C") + 1] == "/proj", a
    assert "-o" in a and "--ephemeral" in a, a
    assert cx["result_source"].endswith(".lastmsg") and cx["result_format"] == "text", cx

    # --- claude arm ---
    cl = resolve("create_story", cfg, "/proj", story_key="1-2-auth")
    assert cl["tool"] == "claude" and cl["model"] == "opus" and cl["effort"] == "xhigh", cl
    a = cl["argv"]
    assert a[:2] == ["claude", "-p"], a
    assert "--model" in a and a[a.index("--model") + 1] == "opus", a
    # claude effort is `--effort`, NEVER codex's `-c model_reasoning_effort=`.
    assert "--effort" in a and a[a.index("--effort") + 1] == "xhigh", a
    assert not any(str(x).startswith("model_reasoning_effort=") for x in a), a
    assert "--output-format" in a and "json" in a and "--dangerously-skip-permissions" in a, a
    assert cl["result_format"] == "json" and cl["result_field"] == "result", cl
    assert cl["error_field"] == "is_error", cl
    assert cl["result_source"] == cl["capture_log"], cl

    # EXPLICIT claude-vs-codex argv divergence (the helper's reason to exist).
    assert ("--effort" in cl["argv"]) and ("--effort" not in cx["argv"])
    assert any(str(x).startswith("model_reasoning_effort=") for x in cx["argv"])
    assert not any(str(x).startswith("model_reasoning_effort=") for x in cl["argv"])

    # Capture logs live OUTSIDE the repo, under the OS temp dir.
    tmp = str(_capture_dir())
    assert cx["capture_log"].startswith(tmp) and "/proj" not in cx["capture_log"], cx
    assert cl["capture_log"].startswith(tmp), cl
    # Distinct files per (story, phase).
    assert cx["capture_log"] != cl["capture_log"]
    assert cx["result_source"] != cx["capture_log"]  # codex parses the -o file, not stdout

    # `label` keeps fan-out delegates' capture paths distinct (same phase + story).
    l1 = resolve("create_story", cfg, "/proj", story_key="k", label="blind-hunter")
    l2 = resolve("create_story", cfg, "/proj", story_key="k", label="edge-case")
    assert l1["capture_log"] != l2["capture_log"], (l1["capture_log"], l2["capture_log"])
    assert "blind-hunter" in l1["capture_log"], l1["capture_log"]

    # Unrouted phase -> use the normal tier.
    assert resolve("retrospective", cfg, "/proj") == {"routed": False, "phase": "retrospective"}

    # Inline cli_phases form, including empty.
    inline = "delegation:\n  cli_phases: { dev_story: claude, retrospective: codex }\n"
    assert parse_cli_phases(inline.splitlines()) == {"dev_story": "claude", "retrospective": "codex"}
    assert parse_cli_phases("delegation:\n  cli_phases: {}\n".splitlines()) == {}
    assert parse_cli_phases("delegation:\n  host: auto\n".splitlines()) == {}  # no cli_phases key

    # Resolution errors: bad tool, missing profile block, unknown phase mapping.
    bad_tool = cfg.replace("dev_story: codex", "dev_story: gpt5")
    r = resolve("dev_story", bad_tool, "/proj")
    assert r["routed"] and r["ok"] is False and any("expected 'claude' or 'codex'" in e for e in r["errors"]), r

    no_block = (
        "delegation:\n  cli_phases:\n    dev_story: codex\n"
        "profiles:\n  ab-xhigh:\n    claude:\n      model: opus\n      effort: xhigh\n"
        "phase_profiles:\n  dev_story: ab-xhigh\n"
    )  # ab-xhigh has no codex block
    r = resolve("dev_story", no_block, "/proj")
    assert r["ok"] is False and any("no 'codex' block" in e for e in r["errors"]), r

    no_map = "delegation:\n  cli_phases:\n    dev_story: codex\nprofiles:\n  ab-xhigh:\n    codex:\n      model: m\n      reasoning_effort: high\n"
    r = resolve("dev_story", no_map, "/proj")  # no phase_profiles mapping
    assert r["ok"] is False and any("no phase_profiles mapping" in e for e in r["errors"]), r

    # --- validate(): offline-deterministic paths (no real auth probe) ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".agents" / "skills" / "bmad-create-story").mkdir(parents=True)
        # Host-tool route skips the auth probe; codex skills found in .agents/skills.
        plan = resolve("dev_story", cfg, str(root), story_key="k")
        v = validate(plan, str(root), host="codex", run_auth_probe=False)
        assert v["validation"]["skills_present"] is True, v
        assert v["validation"]["auth"] == "skipped (host tool)", v
        # binary_on_path depends on the test env; ok reflects only present errors.

        # Missing skills dir -> error.
        with tempfile.TemporaryDirectory() as td2:
            plan2 = resolve("dev_story", cfg, td2, story_key="k")
            v2 = validate(plan2, td2, host="codex", run_auth_probe=False)
            assert v2["validation"]["skills_present"] is False, v2
            assert any("no BMAD skills" in e for e in v2["errors"]), v2
            assert v2["ok"] is False

        # Non-host tool with probe disabled -> auth reported as skipped, not failed.
        plan3 = resolve("create_story", cfg, str(root), story_key="k")
        (root / ".claude" / "skills" / "bmad-create-story").mkdir(parents=True)
        v3 = validate(plan3, str(root), host="codex", run_auth_probe=False)
        assert v3["validation"]["auth"] == "skipped (probe disabled)", v3

    print("SELF-TEST PASSED (all assertions)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve an external-CLI delegation for one auto-bmad phase."
    )
    parser.add_argument("--self-test", action="store_true", help="Run internal tests and exit.")
    parser.add_argument("--phase", help="Pipeline phase key (e.g. dev_story, code_review_review).")
    parser.add_argument("--config", help="Path to the runtime config.yaml.")
    parser.add_argument("--project-root", help="Project root (cwd for the child; codex -C).")
    parser.add_argument("--story-key", default="story", help="Story key, for unique capture filenames.")
    parser.add_argument("--label", help="Extra capture-filename suffix; use a distinct one per fan-out delegate (e.g. blind-hunter) so their capture logs don't collide.")
    parser.add_argument("--host", help="Resolved host (claude-code|codex); skips the auth probe for the host tool. Any other value (e.g. 'auto') ⇒ probe always.")
    parser.add_argument("--no-auth-probe", action="store_true", help="Skip the live auth probe (resolution + binary/skills only).")
    parser.add_argument("--mkdir", action="store_true", help="Create the temp capture dir so the orchestrator's redirect succeeds.")
    args = parser.parse_args()

    if args.self_test:
        return _run_self_test()

    missing = [n for n in ("phase", "config", "project_root") if not getattr(args, n)]
    if missing:
        print(json.dumps({"status": "error", "message": f"missing required: {missing}"}))
        return 2

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(json.dumps({"status": "error", "message": f"config not found: {cfg_path}"}))
        return 2

    plan = resolve(args.phase, cfg_path.read_text(encoding="utf-8"), args.project_root, args.story_key, args.label)
    if not plan.get("routed"):
        print(json.dumps(plan, indent=2))
        return 0
    if plan.get("ok") is False:  # resolution error already recorded
        print(json.dumps(plan, indent=2))
        return 2

    validate(plan, args.project_root, host=args.host, run_auth_probe=not args.no_auth_probe)
    if args.mkdir:
        _capture_dir().mkdir(parents=True, exist_ok=True)
    print(json.dumps(plan, indent=2))
    return 0 if plan.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
