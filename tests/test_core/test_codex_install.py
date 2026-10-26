"""Codex install plumbing: agent TOML translation, install tree, Stop hook, stop gate."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta

import pytest

from hyperresearch.core import codex
from hyperresearch.core.hooks import install_global_hooks, install_hooks

EXPECTED_CODEX_AGENTS = {
    "hyperresearch-fetcher.toml",
    "hyperresearch-loci-analyst.toml",
    "hyperresearch-depth-investigator.toml",
    "hyperresearch-source-analyst.toml",
    "hyperresearch-corpus-critic.toml",
    "hyperresearch-dialectic-critic.toml",
    "hyperresearch-depth-critic.toml",
    "hyperresearch-width-critic.toml",
    "hyperresearch-instruction-critic.toml",
    "hyperresearch-patcher.toml",
    "hyperresearch-polish-auditor.toml",
    "hyperresearch-readability-recommender.toml",
    "hyperresearch-draft-orchestrator.toml",
    "hyperresearch-synthesizer.toml",
    "hyperresearch-cite-checker.toml",
}


def _load_agents(root) -> dict[str, dict]:
    agents_dir = root / ".codex" / "agents"
    return {
        p.name: tomllib.loads(p.read_text(encoding="utf-8"))
        for p in agents_dir.glob("*.toml")
    }


# ---------------------------------------------------------------------------
# TOML encoding helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "plain text",
        'quotes " and \\ backslashes',
        "tab\tnewline\nform\fcarriage\rbell\x07del\x7f",
        "unicode — ✓ 字",
        "",
    ],
)
def test_toml_basic_string_round_trips(value):
    doc = f"x = {codex.toml_basic_string(value)}\n"
    assert tomllib.loads(doc)["x"] == value


@pytest.mark.parametrize(
    "value",
    [
        "multi\nline\nbody with 'single' and '' quotes and \\ backslash\n",
        "no trailing newline",
        "contains ''' a triple quote\n",
        "ends in a quote'",
        "ends in two quotes''",
        "has a\x00control char\n",
        "windows\r\nline endings\r\n",
        "\nleading newline\n",
    ],
)
def test_toml_text_block_round_trips(value):
    doc = f"x = {codex.toml_text_block(value)}\n"
    assert tomllib.loads(doc)["x"] == value


def test_toml_text_block_prefers_literal_when_safe():
    assert codex.toml_text_block("a\nb\n").startswith("'''\n")
    assert codex.toml_text_block("a ''' b").startswith('"')


# ---------------------------------------------------------------------------
# Markdown agent -> TOML translation
# ---------------------------------------------------------------------------

_SAMPLE_AGENT = """\
---
name: hyperresearch-sample
description: >
  First line of a folded
  description.
model: opus
tools: Read, Edit
color: red
---

You are a sample agent. It's got 'quotes' and \\backslashes\\.
"""


def test_agent_markdown_to_toml_fields():
    out = codex.agent_markdown_to_toml(_SAMPLE_AGENT, header_comment="<!-- prov -->")
    assert out.startswith("# <!-- prov -->\n")
    data = tomllib.loads(out)
    assert data["name"] == "hyperresearch-sample"
    assert data["description"] == "First line of a folded description."
    assert data["model_reasoning_effort"] == "high"
    assert data["sandbox_mode"] == "workspace-write"
    assert "model" not in data
    body = "You are a sample agent. It's got 'quotes' and \\backslashes\\.\n"
    assert data["developer_instructions"].endswith(body)
    assert data["developer_instructions"].startswith("## Codex runtime notes")


def test_agent_markdown_to_toml_model_override_and_effort():
    md = _SAMPLE_AGENT.replace("model: opus", "model: sonnet")
    data = tomllib.loads(
        codex.agent_markdown_to_toml(md, header_comment="x", codex_model="gpt-5.4-mini")
    )
    assert data["model"] == "gpt-5.4-mini"
    assert data["model_reasoning_effort"] == "medium"


def test_developer_instructions_round_trip_exactly():
    """The body survives TOML encoding byte for byte (preamble + body)."""
    meta, body = codex.split_frontmatter(_SAMPLE_AGENT)
    tools = codex.parse_tools(meta["tools"])
    expected = codex.codex_agent_preamble(meta["name"], tools) + body.lstrip("\n")
    data = tomllib.loads(codex.agent_markdown_to_toml(_SAMPLE_AGENT, header_comment="x"))
    assert data["developer_instructions"] == expected


def test_preamble_derives_discipline_from_tools():
    edit_only = codex.codex_agent_preamble("hyperresearch-patcher", ["Read", "Edit"])
    assert "ONLY make surgical `apply_patch`" in edit_only
    assert "no general shell access" in edit_only

    write_only = codex.codex_agent_preamble("hyperresearch-synthesizer", ["Read", "Write"])
    assert "create or overwrite only the output files" in write_only
    assert "ONLY make surgical" not in write_only

    with_task = codex.codex_agent_preamble("x", ["Bash", "Read", "Write", "Task"])
    assert "Subagent spawning is unavailable to you" in with_task
    assert "fetch-batch" in with_task
    assert "no general shell access" not in with_task


# ---------------------------------------------------------------------------
# install_hooks(platform="codex") — the installed tree
# ---------------------------------------------------------------------------


def test_codex_install_tree(tmp_vault):
    root = tmp_vault.root
    actions = install_hooks(root, "hyperresearch", platform="codex")
    assert actions and all(a.startswith("Codex: ") for a in actions)

    # Nothing for Claude Code: a codex-only install never creates .claude/
    assert not (root / ".claude").exists()

    skill = root / ".agents" / "skills" / "hyperresearch" / "SKILL.md"
    assert skill.is_file()
    meta, _ = codex.split_frontmatter(skill.read_text(encoding="utf-8"))
    assert meta["name"] == "hyperresearch"
    assert len(" ".join(str(meta["description"]).split())) <= 1024

    import yaml

    openai = yaml.safe_load(
        (skill.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    assert openai["interface"]["display_name"] == "Hyperresearch"
    assert openai["interface"]["short_description"]
    assert "$hyperresearch" in openai["interface"]["default_prompt"]
    assert openai["policy"]["allow_implicit_invocation"] is True

    from hyperresearch.core.hooks import _HYPERRESEARCH_STEP_SKILLS

    steps_dir = root / ".hyperresearch" / "codex" / "steps"
    assert {p.stem for p in steps_dir.glob("*.md")} == set(_HYPERRESEARCH_STEP_SKILLS)
    assert "rendered from profile" in (steps_dir / "hyperresearch-1-decompose.md").read_text(
        encoding="utf-8"
    )

    agents = _load_agents(root)
    assert set(agents) == EXPECTED_CODEX_AGENTS  # no browser-fetcher on Codex
    for filename, data in agents.items():
        assert data["name"] == filename.removesuffix(".toml")
        assert data["description"] and "\n" not in data["description"]
        assert data["developer_instructions"].startswith("## Codex runtime notes")
        assert data["model_reasoning_effort"] in ("high", "medium")
        assert data["sandbox_mode"] == "workspace-write"
        assert "model" not in data  # inherit the session model by default

    # opus-class Claude roles get high effort, sonnet roles medium
    assert agents["hyperresearch-synthesizer.toml"]["model_reasoning_effort"] == "high"
    assert agents["hyperresearch-fetcher.toml"]["model_reasoning_effort"] == "medium"

    hooks = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert list(hooks["hooks"]) == ["Stop"]  # no PreToolUse on Codex
    (entry,) = hooks["hooks"]["Stop"]
    assert entry["hooks"][0]["command"] == "hyperresearch run stop-gate"


def test_codex_agent_body_matches_rendered_claude_body(tmp_vault):
    """The TOML body is the Claude agent body plus the preamble — no drift."""
    from hyperresearch.core import hooks as hooks_mod

    root = tmp_vault.root
    install_hooks(root, "hyperresearch", platform="codex")
    hooks_mod._set_render_state("full", None, "codex")
    rendered = hooks_mod._render_installed(hooks_mod.PATCHER_AGENT, header=False)
    meta, body = codex.split_frontmatter(rendered)
    data = _load_agents(root)["hyperresearch-patcher.toml"]
    expected = codex.codex_agent_preamble(meta["name"], ["Read", "Edit"]) + body.lstrip("\n")
    assert data["developer_instructions"] == expected


def test_codex_reinstall_is_idempotent(tmp_vault):
    first = install_hooks(tmp_vault.root, "hyperresearch", platform="codex")
    assert first
    assert install_hooks(tmp_vault.root, "hyperresearch", platform="codex") == []


def test_codex_model_override_from_profile(tmp_vault):
    cfg = tmp_vault.root / ".hyperresearch" / "config.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8")
        + '\n[profile.full]\ncodex_models = { fetcher = "gpt-5.4-mini", critics = "gpt-5.5" }\n',
        encoding="utf-8",
    )
    install_hooks(tmp_vault.root, "hyperresearch", platform="codex")
    agents = _load_agents(tmp_vault.root)
    assert agents["hyperresearch-fetcher.toml"]["model"] == "gpt-5.4-mini"
    assert agents["hyperresearch-dialectic-critic.toml"]["model"] == "gpt-5.5"
    assert agents["hyperresearch-width-critic.toml"]["model"] == "gpt-5.5"
    assert "model" not in agents["hyperresearch-patcher.toml"]


def test_codex_models_default_to_none_and_validate():
    from hyperresearch.core.profiles import CodexModelMap, ModelMap, resolve_profile

    assert set(CodexModelMap.model_fields) == set(ModelMap.model_fields)
    p = resolve_profile("full")
    assert all(v is None for v in p.codex_models.model_dump().values())
    with pytest.raises(ValueError):
        CodexModelMap(fetcher="  ")


def test_claude_and_codex_installs_coexist(tmp_vault):
    root = tmp_vault.root
    claude_actions = install_hooks(root, "hyperresearch")
    install_hooks(root, "hyperresearch", platform="codex")
    assert (root / ".claude" / "agents" / "hyperresearch-browser-fetcher.md").is_file()
    assert (root / ".codex" / "agents" / "hyperresearch-fetcher.toml").is_file()
    # Re-running either platform is still a no-op afterwards
    assert install_hooks(root, "hyperresearch", platform="codex") == []
    again = install_hooks(root, "hyperresearch")
    assert not again or all("pruned" not in a.lower() for a in again)
    assert claude_actions


def test_codex_prunes_only_our_stale_files(tmp_vault):
    root = tmp_vault.root
    install_hooks(root, "hyperresearch", platform="codex")
    agents_dir = root / ".codex" / "agents"
    steps_dir = root / ".hyperresearch" / "codex" / "steps"

    # A retired agent we wrote (provenance comment) vs. one the user wrote
    ours = agents_dir / "hyperresearch-retired.toml"
    ours.write_text(
        (agents_dir / "hyperresearch-patcher.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    theirs = agents_dir / "hyperresearch-mine.toml"
    theirs.write_text('name = "hyperresearch-mine"\n', encoding="utf-8")
    unrelated = agents_dir / "reviewer.toml"
    unrelated.write_text('name = "reviewer"\n', encoding="utf-8")
    stale_step = steps_dir / "hyperresearch-99-retired.md"
    stale_step.write_text("<!-- rendered from profile \"full\" -->\n", encoding="utf-8")
    user_step = steps_dir / "hyperresearch-notes.md"
    user_step.write_text("my own notes\n", encoding="utf-8")

    actions = install_hooks(root, "hyperresearch", platform="codex")
    assert any("pruned" in a for a in actions)
    assert not ours.exists()
    assert not stale_step.exists()
    assert theirs.exists() and unrelated.exists() and user_step.exists()


def test_codex_global_install(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    actions = install_global_hooks(home, "hyperresearch", platform="codex")
    assert actions
    assert (home / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (home / ".agents" / "skills" / "hyperresearch" / "agents" / "openai.yaml").is_file()
    assert set(_load_agents(home)) == EXPECTED_CODEX_AGENTS
    # Global Codex install never touches user-level Codex config or hooks,
    # never installs step files globally, and never touches ~/.claude
    assert not (home / ".codex" / "config.toml").exists()
    assert not (home / ".codex" / "hooks.json").exists()
    assert not (home / ".hyperresearch").exists()
    assert not (home / ".claude").exists()
    assert install_global_hooks(home, "hyperresearch", platform="codex") == []


def test_unknown_platform_rejected(tmp_vault):
    from hyperresearch.core.platforms import PlatformError

    with pytest.raises(PlatformError):
        install_hooks(tmp_vault.root, "hyperresearch", platform="gemini")


# ---------------------------------------------------------------------------
# .codex/hooks.json merge
# ---------------------------------------------------------------------------


def test_stop_hook_merge_preserves_foreign_hooks(tmp_vault):
    from hyperresearch.core.hooks import _install_codex_stop_hook

    hooks_path = tmp_vault.root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    foreign = {
        "hooks": {
            "PreToolUse": [{"matcher": "shell", "hooks": [{"type": "command", "command": "lint"}]}],
            "Stop": [
                {"hooks": [{"type": "command", "command": "notify-done"}]},
                {"hooks": [{"type": "command", "command": "/old/hyperresearch run stop-gate"}]},
            ],
        },
        "description": "Preserve my hooks",
    }
    hooks_path.write_text(json.dumps(foreign), encoding="utf-8")

    assert _install_codex_stop_hook(tmp_vault.root, "hyperresearch")
    merged = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert merged["description"] == foreign["description"]
    assert merged["hooks"]["PreToolUse"] == foreign["hooks"]["PreToolUse"]
    commands = [e["hooks"][0]["command"] for e in merged["hooks"]["Stop"]]
    # Foreign Stop entry kept, our old entry replaced (exactly one of ours)
    assert commands == ["notify-done", "hyperresearch run stop-gate"]

    # Idempotent
    assert _install_codex_stop_hook(tmp_vault.root, "hyperresearch") is None


def test_stop_hook_leaves_unparseable_hooks_json_alone(tmp_vault):
    from hyperresearch.core.hooks import _install_codex_stop_hook

    hooks_path = tmp_vault.root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(codex.CodexInstallError, match="existing file preserved"):
        _install_codex_stop_hook(tmp_vault.root, "hyperresearch")
    assert hooks_path.read_text(encoding="utf-8") == "{ not json"


def test_stop_hook_preserves_foreign_commands_in_mixed_entries():
    foreign = {"type": "command", "command": "echo run stop-gate"}
    settings = {"hooks": {"Stop": [{"matcher": "keep", "hooks": [{"type": "command", "command": "/old/hyperresearch run stop-gate"}, foreign]}]}}
    merged = codex.merge_stop_hook(settings, "hyperresearch")
    assert merged["hooks"]["Stop"][0] == {"matcher": "keep", "hooks": [{"type": "command", "command": "hyperresearch run stop-gate"}, foreign]}
    assert len(settings["hooks"]["Stop"][0]["hooks"]) == 2


def test_stop_hook_owned_only_group_preserves_matcher_and_opaque_metadata():
    settings = {"hooks": {"Stop": [{"matcher": "custom", "opaque_group": {"value": 1}, "hooks": [{"type": "command", "command": "/old/hyperresearch run stop-gate", "opaque_handler": {"value": 2}, "timeout": 20}]}]}}
    expected = json.loads(json.dumps(settings))
    expected["hooks"]["Stop"][0]["hooks"][0]["command"] = "hyperresearch run stop-gate"
    assert codex.merge_stop_hook(settings, "hyperresearch") == expected
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "/old/hyperresearch run stop-gate"


@pytest.mark.parametrize("handlers", [[{"type": "command", "command": "/old/hyperresearch run stop-gate"}, {"type": "command", "command": "hyperresearch run stop-gate"}], [{"type": "command", "command": "hyperresearch run stop-gate", "async": True}], [{"type": "command", "command": "hyperresearch run stop-gate", "commandWindows": "other"}], [{"type": "command", "command": "hyperresearch run stop-gate", "command_windows": "other"}]])
def test_stop_hook_ambiguous_owned_configuration_fails_without_writing(tmp_vault, handlers):
    from hyperresearch.core.hooks import _install_codex_stop_hook

    path = tmp_vault.root / ".codex/hooks.json"
    path.parent.mkdir()
    original = json.dumps({"hooks": {"Stop": [{"hooks": handlers}]}})
    path.write_text(original, encoding="utf-8")
    with pytest.raises(codex.CodexInstallError, match="existing file preserved"):
        _install_codex_stop_hook(tmp_vault.root, "hyperresearch")
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("stop", [[None], [{"hooks": None}], [{"hooks": [None]}], [{"hooks": [{"type": "command", "command": []}]}]])
def test_stop_hook_rejects_malformed_stop_entries(tmp_vault, stop):
    from hyperresearch.core.hooks import _install_codex_stop_hook

    path = tmp_vault.root / ".codex/hooks.json"
    path.parent.mkdir()
    original = json.dumps({"hooks": {"Stop": stop}})
    path.write_text(original, encoding="utf-8")
    with pytest.raises(codex.CodexInstallError):
        _install_codex_stop_hook(tmp_vault.root, "hyperresearch")
    assert path.read_text(encoding="utf-8") == original


def test_stop_hook_preserves_valid_foreign_types_and_nested_extensions():
    foreign = [{"type": "mcp_tool", "server": "local", "tool": "notify", "input": {"result": "done"}, "extension": 1}, {"type": "prompt", "prompt": "opaque"}, {"type": "agent", "command": "hyperresearch run stop-gate"}]
    settings = {"hooks": {"Stop": [{"hooks": foreign, "extension": 2}, {}, {"hooks": []}], "FutureEvent": {"opaque": True}}}
    merged = codex.merge_stop_hook(settings, "hyperresearch")
    assert merged["hooks"]["Stop"][:-1] == settings["hooks"]["Stop"]
    assert merged["hooks"]["FutureEvent"] == {"opaque": True}


@pytest.mark.parametrize("settings", [{"other": 1}, {"description": []}, {"hooks": {"PreToolUse": {}}}, {"hooks": {"PreToolUse": [{"matcher": 1}]}}, {"hooks": {"Stop": [{"hooks": [{"type": "unknown"}]}]}}, {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify", "async": "false"}]}]}}, {"hooks": {"Stop": [{"hooks": [{"type": "mcp_tool", "server": "local", "tool": "notify", "input": {"value": None}}]}]}}])
def test_stop_hook_rejects_incompatible_known_settings_without_mutation(tmp_vault, settings):
    from hyperresearch.core.hooks import _install_codex_stop_hook

    path = tmp_vault.root / ".codex/hooks.json"
    path.parent.mkdir()
    original = json.dumps(settings)
    path.write_text(original, encoding="utf-8")
    with pytest.raises(codex.CodexInstallError):
        _install_codex_stop_hook(tmp_vault.root, "hyperresearch")
    assert path.read_text(encoding="utf-8") == original


def test_executable_token_uses_the_supported_runner_grammar():
    assert codex.executable_token("C:\\venv\\hpr.exe", windows=True) == "C:/venv/hpr.exe"
    assert codex.executable_token("/a b/hpr", windows=False) == "'/a b/hpr'"
    for path in ["C:/Program Files/hpr.exe", "hpr&whoami", "hpr%PATH%", "hpr!PATH!", "hpr^echo", 'hpr"quote', "hpr;other", "hpr$(other)", "hpr`other`"]:
        with pytest.raises(codex.CodexInstallError):
            codex.executable_token(path, windows=True)
    with pytest.raises(codex.CodexInstallError):
        codex.executable_token("C:\\venv\\hpr.exe", windows=False)


@pytest.mark.skipif(os.name == "nt", reason="Exercises the supported POSIX command runner")
@pytest.mark.parametrize("name", ["hpr space", "hpr'quote", 'hpr"quote', "hpr$(touch INJECTED)", "hpr`touch INJECTED`", "hpr;touch INJECTED", "hpr&touch INJECTED", "hpr|cat"])
def test_codex_executable_tokens_execute_literally(tmp_path, name):
    from hyperresearch.core import hooks

    exe = tmp_path / name
    exe.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    exe.chmod(0o700)
    hooks._set_render_state("full", None, "codex")
    commands = [codex.stop_hook_command(str(exe)), hooks._render_installed("{hpr_path} run stop-gate", str(exe), header=False)]
    for command in commands:
        result = subprocess.run(["/bin/sh", "-c", command], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "run\nstop-gate\n"
        assert not (tmp_path / "INJECTED").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable rendering")
def test_codex_all_generated_commands_quote_the_executable(tmp_vault, monkeypatch):
    from hyperresearch.core.agent_docs import inject_agent_docs

    executable = "/a b/hpr'$(echo marker);`echo marker`"
    token = shlex.quote(executable)
    install_hooks(tmp_vault.root, executable, platform="codex")
    monkeypatch.setattr("hyperresearch.core.agent_docs._resolve_executable", lambda: executable)
    inject_agent_docs(tmp_vault.root, platform="codex")
    assert token + " run resume" in (tmp_vault.root / "AGENTS.md").read_text(encoding="utf-8")
    assert token + " fetch" in _load_agents(tmp_vault.root)["hyperresearch-fetcher.toml"]["developer_instructions"]
    skill = tmp_vault.root / ".agents/skills/hyperresearch/SKILL.md"
    assert token in skill.read_text(encoding="utf-8")


def test_stop_gate_is_session_owned_and_never_uses_the_newest_run(tmp_vault):
    from hyperresearch.core.runs import init_run

    init_run(tmp_vault, "session-a-run", session_id="session-a")
    init_run(tmp_vault, "session-b-run", session_id="session-b")
    assert "session-a-run is at step" in codex.stop_gate_decision(tmp_vault, session_id="session-a")["reason"]
    assert "session-b-run is at step" in codex.stop_gate_decision(tmp_vault, session_id="session-b")["reason"]
    assert codex.stop_gate_decision(tmp_vault, session_id="unrelated") is None
    assert codex.stop_gate_decision(tmp_vault) is None
    init_run(tmp_vault, "ambiguous-a-run", session_id="session-a")
    assert codex.stop_gate_decision(tmp_vault, session_id="session-a") is None


def test_run_init_does_not_rebind_existing_or_legacy_runs(tmp_vault):
    from hyperresearch.core.runs import RunError, init_run

    owned = init_run(tmp_vault, "owned", session_id="session-a")
    assert init_run(tmp_vault, "owned", session_id="session-a") == owned
    with pytest.raises(RunError, match="session"):
        init_run(tmp_vault, "owned", session_id="session-b")
    legacy = init_run(tmp_vault, "legacy")
    assert init_run(tmp_vault, "legacy", session_id="session-a") == legacy
    assert "codex_session_id" not in legacy


# ---------------------------------------------------------------------------
# Stop gate decision
# ---------------------------------------------------------------------------


def test_stop_gate_no_runs(tmp_vault):
    assert codex.stop_gate_decision(tmp_vault) is None


def test_stop_gate_blocks_in_progress_run(tmp_vault):
    from hyperresearch.core.runs import init_run, set_step

    init_run(tmp_vault, "gate-run", session_id="session-a")
    set_step(tmp_vault, "gate-run", "1", "done")
    decision = codex.stop_gate_decision(tmp_vault, session_id="session-a")
    assert decision is not None
    assert decision["decision"] == "block"
    assert "gate-run is at step 2 (hyperresearch-2-width-sweep)" in decision["reason"]
    assert ".hyperresearch/codex/steps/hyperresearch-2-width-sweep.md" in decision["reason"]


def test_stop_gate_follows_declared_light_tier(tmp_vault):
    """Step 1 reclassified a full-gear run as light: the gate must send the
    orchestrator to step 10, never to a step the tier skips."""
    from hyperresearch.core.runs import init_run, set_step

    init_run(tmp_vault, "gate-run", profile="full", session_id="session-a")
    (tmp_vault.run_dir("gate-run") / "prompt-decomposition.json").write_text(
        json.dumps({"pipeline_tier": "light"}), encoding="utf-8"
    )
    set_step(tmp_vault, "gate-run", "1", "done")
    set_step(tmp_vault, "gate-run", "2", "done")
    decision = codex.stop_gate_decision(tmp_vault, session_id="session-a")
    assert decision is not None
    assert "gate-run is at step 10 (hyperresearch-10-triple-draft)" in decision["reason"]


@pytest.mark.parametrize("status", ["done", "aborted", "failed", "paused", "blocked"])
def test_stop_gate_silent_for_inactive_runs(tmp_vault, status):
    from hyperresearch.core.runs import init_run, set_status

    init_run(tmp_vault, "gate-run", session_id="session-a")
    set_status(tmp_vault, "gate-run", status, blocked_on="x" if status == "blocked" else None)
    assert codex.stop_gate_decision(tmp_vault, session_id="session-a") is None


def test_stop_gate_silent_when_all_steps_done(tmp_vault):
    from hyperresearch.core.runs import init_run, load_manifest, set_step

    init_run(tmp_vault, "gate-run", profile="light", session_id="session-a")
    for step in load_manifest(tmp_vault, "gate-run")["profile_steps"]:
        set_step(tmp_vault, "gate-run", step, "done")
    assert codex.stop_gate_decision(tmp_vault, session_id="session-a") is None


def test_stop_gate_silent_for_stale_run(tmp_vault):
    from hyperresearch.core.runs import init_run

    init_run(tmp_vault, "gate-run", session_id="session-a")
    later = datetime.now(UTC) + timedelta(hours=7)
    assert codex.stop_gate_decision(tmp_vault, now=later, session_id="session-a") is None
    soon = datetime.now(UTC) + timedelta(hours=5)
    assert codex.stop_gate_decision(tmp_vault, now=soon, session_id="session-a") is not None


# ---------------------------------------------------------------------------
# AGENTS.md injection
# ---------------------------------------------------------------------------


def test_codex_agent_docs(tmp_vault):
    from hyperresearch.core.agent_docs import (
        HYPERRESEARCH_SECTION_MARKER,
        inject_agent_docs,
    )

    agents_md = tmp_vault.root / "AGENTS.md"
    agents_md.write_text("# My project\n\nKeep this.\n", encoding="utf-8")
    claude_before = (tmp_vault.root / "CLAUDE.md").read_text(encoding="utf-8")

    assert inject_agent_docs(tmp_vault.root, platform="codex") == ["AGENTS.md (appended)"]
    text = agents_md.read_text(encoding="utf-8")
    assert text.startswith("# My project\n\nKeep this.\n")
    assert HYPERRESEARCH_SECTION_MARKER in text
    assert "$hyperresearch <query>" in text
    assert ".agents/skills/hyperresearch/SKILL.md" in text
    assert ".hyperresearch/codex/steps/" in text
    assert ".codex/agents/" in text
    assert "sandbox_workspace_write.network_access=true" in text
    assert "--dangerously-bypass-hook-trust" in text
    assert "`/hyperresearch" not in text  # no Claude slash command
    assert len(text.encode("utf-8")) < 16 * 1024  # well under Codex's 32 KiB cap

    # Idempotent, and CLAUDE.md is untouched
    assert inject_agent_docs(tmp_vault.root, platform="codex") == []
    assert (tmp_vault.root / "CLAUDE.md").read_text(encoding="utf-8") == claude_before


def test_vault_init_codex_only_writes_agents_md_not_claude_md(tmp_path):
    from hyperresearch.core.vault import Vault

    vault = Vault.init(tmp_path / "v", platforms=("codex",))
    assert (vault.root / "AGENTS.md").is_file()
    assert not (vault.root / "CLAUDE.md").exists()

    default = Vault.init(tmp_path / "d")
    assert (default.root / "CLAUDE.md").is_file()
    assert not (default.root / "AGENTS.md").exists()
