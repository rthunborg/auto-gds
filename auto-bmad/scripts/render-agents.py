#!/usr/bin/env python3
"""Render auto-bmad's tool-native delegate agents from a profiles definition.

The auto-bmad orchestrator delegates each pipeline step to one of four profiles
(``ab-xhigh``, ``ab-high``, ``ab-alt-xhigh``, ``ab-alt-high``). Each profile carries both
tool-neutral persona strings (``description`` / ``role_blurb`` /
``status_example``) and per-tool model + thinking/reasoning effort. This script
fills ONE shared body template per tool with those values, so the four profiles
share a single body and the same persona strings appear in both Claude and Codex
output (no Claude-vs-Codex drift):

  - Claude Code -> ``{project-root}/.claude/agents/<name>.md``   (frontmatter
    ``model:`` / ``effort:``)
  - Codex       -> ``{project-root}/.codex/agents/<name>.toml``  (``model`` /
    ``model_reasoning_effort``)
  - opencode    -> ``{project-root}/.opencode/agent/<name>.md``  (frontmatter ``model:``
    only — MODEL-ONLY; opencode has no per-agent effort knob, and a blank model is
    omitted so the subagent inherits the user's opencode default model)

Templates live at ``assets/agents/claude/agent.md.tmpl``,
``assets/agents/codex/agent.toml.tmpl`` and ``assets/agents/opencode/agent.md.tmpl``
and contain the placeholders ``@@NAME@@``, ``@@DESCRIPTION@@``, ``@@ROLE_BLURB@@``,
``@@STATUS_EXAMPLE@@``, ``@@MODEL@@``, ``@@EFFORT@@`` (Claude),
``@@REASONING_EFFORT@@`` (Codex), and the whole-line ``@@MODEL_LINE@@`` (opencode).

The profiles source can be either the shipped ``assets/agents/profiles.yaml`` or
the ``profiles:`` block of the runtime config
(``{output_folder}/auto-bmad/config.yaml``). Parsing is dependency-free: a small
block-structured reader (same spirit as ``story_plan.py``), so no PyYAML needed.

Usage:
    render-agents.py --project-root DIR [--tools claude-code,codex]
                     [--profiles FILE] [--templates-dir DIR] [--dry-run]
    render-agents.py --check --project-root DIR [--tools ...] [--profiles FILE]
    render-agents.py --self-test

``--check`` renders every agent in memory and diffs it against the on-disk files
instead of writing — answering "is ``/auto-bmad reprovision`` needed?". It
reports ``needs_reprovision`` plus the ``missing`` / ``stale`` / ``extra`` files,
and exits 0 when fresh, 1 when reprovision is needed, 2 on usage error. Because
it uses the same inputs as a real render (current profiles + current templates +
``target_tools``), the check and the fix can never disagree, and it catches every
drift source: a module update that changed the templates, an edited ``profiles``
block, an added/removed ``target_tool``, or a hand-mangled generated file.

Output: a single JSON object on stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

PROFILE_NAMES = ("ab-xhigh", "ab-high", "ab-alt-xhigh", "ab-alt-high")

# tool -> (one shared body template, output dir + suffix, tool-specific placeholders)
TOOLS = {
    "claude-code": {
        "tmpl_dir": "claude",
        "tmpl_name": "agent.md.tmpl",
        "out_dir": ".claude/agents",
        "out_suffix": ".md",
        # placeholder -> per-tool profile key
        "subs": {"@@MODEL@@": "model", "@@EFFORT@@": "effort"},
        "cfg_key": "claude",
    },
    "codex": {
        "tmpl_dir": "codex",
        "tmpl_name": "agent.toml.tmpl",
        "out_dir": ".codex/agents",
        "out_suffix": ".toml",
        "subs": {"@@MODEL@@": "model", "@@REASONING_EFFORT@@": "reasoning_effort"},
        "cfg_key": "codex",
    },
    # opencode markdown agents live in `.opencode/agent/` (singular — verified against
    # opencode 1.16.2 `agent list`). They are MODEL-ONLY: no per-agent effort knob exists,
    # and the model is OPTIONAL (blank => the subagent inherits the user's opencode default
    # model). So opencode has no fixed `@@MODEL@@` placeholder; the renderer fills the
    # whole-line `@@MODEL_LINE@@` token specially (see _plan) — `model: <provider/model>` or
    # nothing. `subs` is empty because every per-tool field is handled there.
    "opencode": {
        "tmpl_dir": "opencode",
        "tmpl_name": "agent.md.tmpl",
        "out_dir": ".opencode/agent",
        "out_suffix": ".md",
        "subs": {},
        "cfg_key": "opencode",
    },
}

# Tool-neutral per-profile metadata, filled into the shared body template.
# Same values flow into BOTH the Claude and Codex output, so wording cannot drift.
SHARED_SUBS = {
    "@@DESCRIPTION@@": "description",
    "@@ROLE_BLURB@@": "role_blurb",
    "@@STATUS_EXAMPLE@@": "status_example",
}

_INLINE_MAP_RE = re.compile(r"^([\w-]+):\s*\{(.*)\}\s*$")


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


def _parse_inline_map(body: str) -> dict:
    """Parse ``k: v, k2: v2`` (the inside of a flow map) into a dict."""
    out: dict = {}
    for part in body.split(","):
        if ":" in part:
            k, _, v = part.partition(":")
            out[k.strip()] = _strip_value(v)
    return out


def parse_profiles(text: str) -> dict:
    """Extract the ``profiles:`` block from a YAML-ish file, dependency-free.

    Supports block style::

        profiles:
          ab-xhigh:
            description: "..."
            role_blurb: "..."
            status_example: "..."
            claude:
              model: opus
              effort: xhigh

    and an inline flow map at the tool level::

        profiles:
          ab-xhigh:
            claude: {model: opus, effort: xhigh}

    Per-profile scalar values (``description``, ``role_blurb``,
    ``status_example``, …) sit at indent 4 alongside the tool subsections; they
    are the tool-neutral metadata the renderer flows into BOTH tools' output.
    Other top-level keys in the file are ignored. Returns
    ``{profile: {key: value | tool: {key: value}}}``.
    """
    profiles: dict = {}
    in_block = False
    cur_profile: str | None = None
    cur_tool: str | None = None

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        # Indent comes from `raw`; strip any trailing comment so structural lines
        # like `profiles:  # ...`, `ab-xhigh:  # ...`, `claude:  # ...` (the
        # documented config carries these) parse the same as bare ones.
        stripped = _strip_comment(raw.strip())

        if not in_block:
            if indent == 0 and stripped == "profiles:":
                in_block = True
            continue

        # Inside the profiles block.
        if indent == 0:
            break  # dedented back to a new top-level key
        if indent == 2 and stripped.endswith(":"):
            cur_profile = stripped[:-1].strip()
            profiles[cur_profile] = {}
            cur_tool = None
        elif indent == 4 and cur_profile is not None:
            m = _INLINE_MAP_RE.match(stripped)
            if m:
                profiles[cur_profile][m.group(1).strip()] = _parse_inline_map(m.group(2))
                cur_tool = None
            elif stripped.endswith(":"):
                cur_tool = stripped[:-1].strip()
                profiles[cur_profile][cur_tool] = {}
            elif ":" in stripped:
                # Per-profile scalar metadata (e.g. description, role_blurb).
                key, _, val = stripped.partition(":")
                profiles[cur_profile][key.strip()] = _strip_value(val)
                cur_tool = None
        elif indent >= 6 and ":" in stripped and cur_profile is not None and cur_tool is not None:
            key, _, val = stripped.partition(":")
            profiles[cur_profile][cur_tool][key.strip()] = _strip_value(val)

    return profiles


def _plan(
    profiles: dict,
    tools: list[str],
    templates_dir: Path,
    project_root: Path,
) -> tuple[list[tuple[Path, str]], list[str]]:
    """Render every requested profile×tool in memory (no writes).

    Each tool has ONE shared body template; the four profile outputs are
    produced by substituting per-profile metadata + per-tool model/effort into
    that same template. This is the single source of truth shared by
    ``render`` (which writes) and ``check`` (which diffs), so the two can
    never disagree about what the agent files *should* contain.
    """
    outputs: list[tuple[Path, str]] = []
    warnings: list[str] = []

    for tool in tools:
        spec = TOOLS[tool]
        out_dir = project_root / spec["out_dir"]
        tmpl_path = templates_dir / spec["tmpl_dir"] / spec["tmpl_name"]
        if not tmpl_path.is_file():
            warnings.append(f"template not found: {tmpl_path} — skipped {tool}")
            continue
        tmpl_content = tmpl_path.read_text(encoding="utf-8")

        for name in PROFILE_NAMES:
            prof = profiles.get(name)
            if not prof:
                warnings.append(f"profile '{name}' missing from profiles source — skipped for {tool}")
                continue
            tool_cfg = prof.get(spec["cfg_key"])
            if not tool_cfg:
                warnings.append(f"profile '{name}' has no '{spec['cfg_key']}' config — skipped for {tool}")
                continue

            content = tmpl_content
            content = content.replace("@@NAME@@", name)
            for placeholder, key in SHARED_SUBS.items():
                if key not in prof:
                    warnings.append(f"profile '{name}' missing '{key}'")
                    continue
                content = content.replace(placeholder, str(prof[key]))
            for placeholder, key in spec["subs"].items():
                if key not in tool_cfg:
                    warnings.append(f"profile '{name}.{spec['cfg_key']}' missing '{key}'")
                    continue
                content = content.replace(placeholder, str(tool_cfg[key]))

            # opencode: the model is optional. Replace the whole-line `@@MODEL_LINE@@` token
            # (placeholder + its trailing newline) with `model: <provider/model>` when a model is
            # set, or NOTHING when blank — so a blank model omits the frontmatter line cleanly and
            # the subagent inherits the user's opencode default model.
            if tool == "opencode":
                model = str(tool_cfg.get("model", "")).strip()
                content = content.replace("@@MODEL_LINE@@\n", f"model: {model}\n" if model else "")

            leftover = re.findall(r"@@[A-Z_]+@@", content)
            if leftover:
                warnings.append(f"{name} ({tool}): unfilled placeholders {sorted(set(leftover))}")

            outputs.append((out_dir / f"{name}{spec['out_suffix']}", content))

    return outputs, warnings


def render(
    profiles: dict,
    tools: list[str],
    templates_dir: Path,
    project_root: Path,
    dry_run: bool = False,
) -> dict:
    """Render the requested tools' agent files. Returns a JSON-able summary."""
    outputs, warnings = _plan(profiles, tools, templates_dir, project_root)
    files_written: list[str] = []
    for out_path, content in outputs:
        if not dry_run:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        files_written.append(str(out_path))

    return {
        "status": "success",
        "tools": tools,
        "dry_run": dry_run,
        "files_written": files_written,
        "warnings": warnings,
    }


def check(
    profiles: dict,
    tools: list[str],
    templates_dir: Path,
    project_root: Path,
) -> dict:
    """Diff what *would* be rendered now against the on-disk agent files.

    Answers "is ``/auto-bmad reprovision`` needed?" without writing anything.
    ``missing`` = expected but absent; ``stale`` = present but content differs
    (template or profile changed since last render); ``extra`` = ab-* agent
    files on disk that are no longer expected (e.g. a tool dropped from
    ``target_tools``) — informational, since a plain render never deletes them.
    ``needs_reprovision`` is true iff anything is missing or stale.
    """
    outputs, warnings = _plan(profiles, tools, templates_dir, project_root)
    missing: list[str] = []
    stale: list[str] = []
    ok: list[str] = []
    for out_path, content in outputs:
        if not out_path.exists():
            missing.append(str(out_path))
        elif out_path.read_text(encoding="utf-8") != content:
            stale.append(str(out_path))
        else:
            ok.append(str(out_path))

    # Scan *every* tool's output dir, not just the requested ones, so agents
    # left behind by a tool dropped from target_tools are surfaced as 'extra'.
    expected = {str(p) for p, _ in outputs}
    extra: list[str] = []
    for spec in TOOLS.values():
        out_dir = project_root / spec["out_dir"]
        if out_dir.is_dir():
            for f in sorted(out_dir.glob(f"ab-*{spec['out_suffix']}")):
                if str(f) not in expected:
                    extra.append(str(f))

    needs = bool(missing or stale)
    return {
        "status": "stale" if needs else "fresh",
        "needs_reprovision": needs,
        "tools": tools,
        "missing": missing,
        "stale": stale,
        "ok": ok,
        "extra": extra,
        "warnings": warnings,
    }


def _default_templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "agents"


def _run_self_test() -> int:
    templates_dir = _default_templates_dir()
    profiles_file = templates_dir / "profiles.yaml"
    assert profiles_file.is_file(), f"shipped profiles.yaml missing at {profiles_file}"

    profiles = parse_profiles(profiles_file.read_text(encoding="utf-8"))
    # Structure assertions against the shipped defaults.
    for name in PROFILE_NAMES:
        assert name in profiles, f"profile {name} not parsed"
        # Tool-neutral metadata flows into both Claude and Codex output.
        for meta in ("description", "role_blurb", "status_example"):
            assert profiles[name].get(meta), f"{name}.{meta} empty"
        # Per-tool model + effort.
        assert "claude" in profiles[name] and "codex" in profiles[name], f"{name} missing tool blocks"
        assert profiles[name]["claude"].get("model"), f"{name}.claude.model empty"
        assert profiles[name]["claude"].get("effort"), f"{name}.claude.effort empty"
        assert profiles[name]["codex"].get("model"), f"{name}.codex.model empty"
        assert profiles[name]["codex"].get("reasoning_effort"), f"{name}.codex.reasoning_effort empty"
        # opencode is MODEL-ONLY and ships the model BLANK (inherit the user's default), so assert the
        # KEYS are present — never that they're truthy (empty string is the intended shipped value).
        assert "opencode" in profiles[name], f"{name} missing opencode block"
        assert "model" in profiles[name]["opencode"], f"{name}.opencode.model key missing"
        assert "variant" in profiles[name]["opencode"], f"{name}.opencode.variant key missing"
        assert profiles[name]["opencode"]["model"] == "", f"{name}.opencode.model should ship blank"
    assert profiles["ab-xhigh"]["claude"]["model"] == "opus"
    assert profiles["ab-xhigh"]["claude"]["effort"] == "xhigh"
    assert profiles["ab-alt-xhigh"]["claude"]["model"] == "sonnet"
    assert profiles["ab-alt-xhigh"]["claude"]["effort"] == "xhigh"
    assert profiles["ab-alt-high"]["claude"]["model"] == "sonnet"
    # Descriptions carry the profile-distinctive signal — sanity-check the labels.
    assert "highest-stakes, deep-reasoning" in profiles["ab-xhigh"]["description"]
    assert "test- and context-infrastructure" in profiles["ab-high"]["description"]
    assert "alternate-model secondary code-review" in profiles["ab-alt-xhigh"]["description"]
    assert "lighter-weight" in profiles["ab-alt-high"]["description"]

    # Inline-flow-map parsing.
    inline = parse_profiles(
        "profiles:\n  ab-xhigh:\n    claude: {model: haiku, effort: low}\n    codex: {model: m, reasoning_effort: minimal}\n"
    )
    assert inline["ab-xhigh"]["claude"] == {"model": "haiku", "effort": "low"}, inline

    # Comment + quote stripping and ignoring sibling top-level keys.
    mixed = parse_profiles(
        "tea:\n  enabled: true\n"
        "profiles:\n  ab-xhigh:\n    claude:\n      model: \"opus\"  # the big one\n      effort: xhigh\n"
        "git:\n  mode: auto\n"
    )
    assert mixed["ab-xhigh"]["claude"]["model"] == "opus", mixed
    assert mixed["ab-xhigh"]["claude"]["effort"] == "xhigh", mixed
    assert "git" not in mixed and "tea" not in mixed

    # Per-profile scalar metadata at indent 4, alongside the tool subsections.
    scalar = parse_profiles(
        "profiles:\n"
        "  ab-xhigh:\n"
        "    description: \"big stakes\"\n"
        "    role_blurb: \"hard work\"\n"
        "    status_example: \"all green\"\n"
        "    claude:\n"
        "      model: opus\n"
        "      effort: xhigh\n"
    )
    assert scalar["ab-xhigh"]["description"] == "big stakes", scalar
    assert scalar["ab-xhigh"]["role_blurb"] == "hard work", scalar
    assert scalar["ab-xhigh"]["status_example"] == "all green", scalar
    assert scalar["ab-xhigh"]["claude"]["model"] == "opus", scalar

    # Trailing comments on STRUCTURAL lines (profiles:/profile/tool), as the
    # documented runtime config carries them — must parse like bare lines.
    commented = parse_profiles(
        "profiles:                  # per-profile model + effort, PER TOOL\n"
        "  ab-xhigh:                # reads to generate the agent files\n"
        "    claude:                # keep block style; run reprovision after\n"
        "      model: opus\n"
        "      effort: xhigh\n"
        "    codex:\n"
        "      model: gpt-5.5\n"
        "      reasoning_effort: high\n"
    )
    assert commented["ab-xhigh"]["claude"] == {"model": "opus", "effort": "xhigh"}, commented
    assert commented["ab-xhigh"]["codex"]["reasoning_effort"] == "high", commented

    # End-to-end render into a temp project root, all three tools.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        result = render(profiles, ["claude-code", "codex", "opencode"], templates_dir, root)
        assert result["status"] == "success", result
        assert not result["warnings"], f"unexpected warnings: {result['warnings']}"

        claude_xhigh = (root / ".claude/agents/ab-xhigh.md").read_text(encoding="utf-8")
        assert "model: opus" in claude_xhigh and "effort: xhigh" in claude_xhigh, claude_xhigh[:200]
        assert "@@" not in claude_xhigh, "unfilled placeholder in Claude output"
        assert "name: ab-xhigh" in claude_xhigh
        # Metadata flowed into the body.
        assert "highest-stakes" in claude_xhigh, "description not substituted into Claude body"
        assert "implementing story code" in claude_xhigh, "role_blurb not substituted"
        assert "story moved to `review`" in claude_xhigh, "status_example not substituted"

        codex_xhigh = (root / ".codex/agents/ab-xhigh.toml").read_text(encoding="utf-8")
        assert 'model = "gpt-5.5"' in codex_xhigh, codex_xhigh[:200]
        assert 'model_reasoning_effort = "xhigh"' in codex_xhigh, codex_xhigh[:200]
        assert "@@" not in codex_xhigh, "unfilled placeholder in Codex output"
        assert "highest-stakes" in codex_xhigh, "description not substituted into Codex body"
        assert "implementing story code" in codex_xhigh, "role_blurb not substituted (codex)"

        # opencode is MODEL-ONLY; the shipped model is blank => NO `model:` line (the subagent
        # inherits the user's opencode default), and there is no `name:`/`effort:` field.
        oc_xhigh = (root / ".opencode/agent/ab-xhigh.md").read_text(encoding="utf-8")
        assert "mode: subagent" in oc_xhigh, oc_xhigh[:200]
        assert "\nmodel:" not in oc_xhigh, "blank opencode model must omit the model: line"
        assert "\nname:" not in oc_xhigh, "opencode agents must not carry a name: field (filename is the name)"
        assert "@@" not in oc_xhigh, "unfilled placeholder in opencode output"
        assert "highest-stakes" in oc_xhigh, "description not substituted into opencode frontmatter"
        assert "implementing story code" in oc_xhigh, "role_blurb not substituted (opencode)"
        assert "story moved to `review`" in oc_xhigh, "status_example not substituted (opencode)"

        # opencode with a model SET => the `model:` frontmatter line IS emitted with that value.
        oc_set = json.loads(json.dumps(profiles))  # deep copy
        oc_set["ab-xhigh"]["opencode"]["model"] = "anthropic/claude-opus-4-5"
        with tempfile.TemporaryDirectory() as td_oc:
            render(oc_set, ["opencode"], templates_dir, Path(td_oc))
            body = (Path(td_oc) / ".opencode/agent/ab-xhigh.md").read_text(encoding="utf-8")
            assert "model: anthropic/claude-opus-4-5" in body, body[:200]
            assert "@@" not in body, "unfilled placeholder with model set"

        # Cross-tool drift guard: the persona strings are identical on both
        # sides because they came from the single profiles entry. If a future
        # edit forks the wording between tools, this fails immediately.
        for name in PROFILE_NAMES:
            c = (root / f".claude/agents/{name}.md").read_text(encoding="utf-8")
            x = (root / f".codex/agents/{name}.toml").read_text(encoding="utf-8")
            for meta in ("role_blurb", "status_example"):
                val = profiles[name][meta]
                assert val in c, f"{name}.{meta} missing from Claude output: {val!r}"
                assert val in x, f"{name}.{meta} missing from Codex output: {val!r}"

        # All four profiles produce distinct bodies (catches a regression where
        # role_blurb or status_example silently fail to substitute and every
        # agent ends up identical).
        bodies = {name: (root / f".claude/agents/{name}.md").read_text(encoding="utf-8") for name in PROFILE_NAMES}
        assert len(set(bodies.values())) == 4, "agent bodies not distinct across profiles"

        # Codex output must be valid TOML.
        try:
            import tomllib  # py3.11+

            parsed = tomllib.loads(codex_xhigh)
            assert parsed["name"] == "ab-xhigh"
            assert parsed["model"] == "gpt-5.5"
            assert parsed["model_reasoning_effort"] == "xhigh"
            assert parsed["developer_instructions"].strip()
            assert "highest-stakes" in parsed["description"]
        except ModuleNotFoundError:
            # Older Python: fall back to a structural sanity check.
            assert codex_xhigh.count('"""') == 2, "developer_instructions block malformed"

        # All four profiles rendered for all three tools => 12 files.
        assert len(result["files_written"]) == 12, result["files_written"]

        # --check: right after a render, everything is fresh.
        chk = check(profiles, ["claude-code", "codex", "opencode"], templates_dir, root)
        assert chk["status"] == "fresh" and not chk["needs_reprovision"], chk
        assert len(chk["ok"]) == 12 and not chk["stale"] and not chk["missing"], chk

        # Editing a profile makes that agent's rendered output differ -> stale.
        bumped = json.loads(json.dumps(profiles))  # deep copy
        bumped["ab-alt-high"]["claude"]["model"] = "opus"
        chk_stale = check(bumped, ["claude-code"], templates_dir, root)
        assert chk_stale["needs_reprovision"], chk_stale
        assert any(p.endswith("ab-alt-high.md") for p in chk_stale["stale"]), chk_stale
        assert not chk_stale["missing"], chk_stale

        # Editing a tool-neutral metadata key also marks both tools' outputs stale.
        bumped2 = json.loads(json.dumps(profiles))
        bumped2["ab-high"]["role_blurb"] = "totally different blurb"
        chk_meta = check(bumped2, ["claude-code", "codex"], templates_dir, root)
        assert chk_meta["needs_reprovision"], chk_meta
        assert any(p.endswith("ab-high.md") for p in chk_meta["stale"]), chk_meta
        assert any(p.endswith("ab-high.toml") for p in chk_meta["stale"]), chk_meta

        # Deleting a generated file -> missing.
        (root / ".claude/agents/ab-xhigh.md").unlink()
        chk_missing = check(profiles, ["claude-code"], templates_dir, root)
        assert chk_missing["needs_reprovision"], chk_missing
        assert any(p.endswith("ab-xhigh.md") for p in chk_missing["missing"]), chk_missing

        # A tool dropped from target_tools leaves 'extra' files (informational,
        # not on its own a reprovision trigger). Re-render to a clean state first.
        render(profiles, ["claude-code", "codex"], templates_dir, root)
        chk_extra = check(profiles, ["claude-code"], templates_dir, root)
        assert chk_extra["status"] == "fresh", chk_extra
        assert any(p.endswith("ab-xhigh.toml") for p in chk_extra["extra"]), chk_extra

        # dry-run writes nothing new.
        with tempfile.TemporaryDirectory() as td2:
            dr = render(profiles, ["claude-code"], templates_dir, Path(td2), dry_run=True)
            assert dr["files_written"] and not any(Path(p).exists() for p in dr["files_written"])

        # --check on a never-rendered root: everything missing -> needs reprovision.
        with tempfile.TemporaryDirectory() as td3:
            fresh_chk = check(profiles, ["claude-code"], templates_dir, Path(td3))
            assert fresh_chk["needs_reprovision"] and len(fresh_chk["missing"]) == 4, fresh_chk

    print("SELF-TEST PASSED (all assertions)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Render auto-bmad tool-native delegate agents.")
    parser.add_argument("--self-test", action="store_true", help="Run internal tests and exit.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Diff on-disk agents vs current profiles/templates; report if reprovision is needed. Exit 1 if stale.",
    )
    parser.add_argument("--project-root", help="Project root to write .claude/agents and/or .codex/agents into.")
    parser.add_argument("--tools", default="claude-code", help="Comma-separated: claude-code,codex,opencode")
    parser.add_argument("--profiles", help="Profiles source (YAML). Default: shipped assets/agents/profiles.yaml")
    parser.add_argument("--templates-dir", help="Templates dir. Default: assets/agents next to this script.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be written without writing.")
    args = parser.parse_args()

    if args.self_test:
        return _run_self_test()

    if not args.project_root:
        print(json.dumps({"status": "error", "message": "--project-root is required"}))
        return 2

    templates_dir = Path(args.templates_dir) if args.templates_dir else _default_templates_dir()
    profiles_file = Path(args.profiles) if args.profiles else (templates_dir / "profiles.yaml")
    if not profiles_file.is_file():
        print(json.dumps({"status": "error", "message": f"profiles source not found: {profiles_file}"}))
        return 2

    profiles = parse_profiles(profiles_file.read_text(encoding="utf-8"))
    if not profiles:
        print(json.dumps({"status": "error", "message": f"no 'profiles:' block found in {profiles_file}"}))
        return 2

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    bad = [t for t in tools if t not in TOOLS]
    if bad:
        print(json.dumps({"status": "error", "message": f"unknown tools: {bad}; valid: {list(TOOLS)}"}))
        return 2

    if args.check:
        result = check(profiles, tools, templates_dir, Path(args.project_root))
        result["profiles_source"] = str(profiles_file)
        print(json.dumps(result, indent=2))
        return 1 if result["needs_reprovision"] else 0

    result = render(profiles, tools, templates_dir, Path(args.project_root), dry_run=args.dry_run)
    result["profiles_source"] = str(profiles_file)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
