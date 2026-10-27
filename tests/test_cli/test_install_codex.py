"""CLI: `hyperresearch install --target`, `run stop-gate`, and `run resume` Codex hint."""

from __future__ import annotations

import json
import tomllib

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def _json(result) -> dict:
    return json.loads(result.stdout)


def test_install_target_codex(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "codex", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["targets"] == ["codex"]
    # Existing keys are kept
    for key in ("vault_path", "vault", "agent_docs", "hooks_installed", "crawl4ai"):
        assert key in data
    assert "AGENTS.md (created)" in data["agent_docs"]

    root = tmp_vault.root
    assert not (root / ".claude").exists()
    assert (root / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (root / ".codex" / "hooks.json").is_file()
    for toml in (root / ".codex" / "agents").glob("*.toml"):
        parsed = tomllib.loads(toml.read_text(encoding="utf-8"))
        assert {"name", "description", "developer_instructions"} <= set(parsed)

    again = runner.invoke(app, ["install", str(root), "--target", "codex", "--json"])
    assert again.exit_code == 0
    assert _json(again)["data"]["hooks_installed"] == []


def test_codex_only_install_on_fresh_dir_writes_no_claude_files(tmp_path, monkeypatch):
    root = tmp_path / "fresh"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install", str(root), "--target", "codex", "--json"])
    assert result.exit_code == 0, result.stdout
    assert _json(result)["data"]["vault"] == "created"
    assert (root / "AGENTS.md").is_file()
    assert not (root / "CLAUDE.md").exists()
    assert not (root / ".claude").exists()


def test_fresh_all_install_writes_both_docs(tmp_path, monkeypatch):
    root = tmp_path / "fresh"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install", str(root), "--target", "all", "--json"])
    assert result.exit_code == 0, result.stdout
    assert (root / "AGENTS.md").is_file()
    assert (root / "CLAUDE.md").is_file()


def test_install_target_all(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "all", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["targets"] == ["claude", "codex"]
    root = tmp_vault.root
    assert (root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (root / ".claude" / "agents" / "hyperresearch-browser-fetcher.md").is_file()
    assert (root / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert not (root / ".codex" / "agents" / "hyperresearch-browser-fetcher.toml").exists()
    assert (root / "AGENTS.md").is_file()
    assert (root / "CLAUDE.md").is_file()


def test_install_default_target_is_claude(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--json"])
    assert result.exit_code == 0
    assert _json(result)["data"]["targets"] == ["claude"]
    assert not (tmp_vault.root / ".codex").exists()
    assert not (tmp_vault.root / ".agents").exists()
    assert not (tmp_vault.root / "AGENTS.md").exists()


def test_install_unknown_target_fails_before_writing(tmp_path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install", str(target), "--target", "gemini", "--json"])
    assert result.exit_code == 1
    assert _json(result)["error_code"] == "UNKNOWN_TARGET"
    assert not target.exists()


def test_install_steps_only_codex(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(
        app, ["install", str(tmp_vault.root), "--steps-only", "--target", "codex", "--json"]
    )
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["targets"] == ["codex"]
    assert data["steps_installed"]
    root = tmp_vault.root
    assert (root / ".hyperresearch" / "codex" / "steps" / "hyperresearch-1-decompose.md").is_file()
    assert (root / ".codex" / "hooks.json").is_file()
    assert not (root / ".claude").exists()
    assert not (root / ".codex" / "agents").exists()

    again = runner.invoke(
        app, ["install", str(root), "--steps-only", "--target", "codex", "--json"]
    )
    assert _json(again)["data"]["steps_installed"] is None


@pytest.mark.parametrize("steps_only", [False, True])
@pytest.mark.parametrize("content", ["{not json", "[]", '{"hooks": []}', '{"hooks": {"Stop": {}}}', '{"hooks": {}, "other": 1}', '{"hooks": {"PreToolUse": {}}}', '{"hooks": {}, "hooks": {}}', '{"hooks": {"FutureEvent": NaN}}'])
def test_install_rejects_unmergeable_requested_stop_hook(tmp_vault, monkeypatch, steps_only, content):
    monkeypatch.chdir(tmp_vault.root)
    hooks = tmp_vault.root / ".codex" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text(content, encoding="utf-8")
    args = ["install", str(tmp_vault.root), "--target", "codex", "--json"]
    if steps_only:
        args.append("--steps-only")
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert _json(result)["ok"] is False
    assert _json(result)["error_code"] == "CODEX_INSTALL_ERROR"
    assert hooks.read_text(encoding="utf-8") == content


def test_install_explicit_stop_hook_opt_out_is_degraded(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    hooks = tmp_vault.root / ".codex" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "codex", "--no-stop-hook", "--json"])
    assert result.exit_code == 0, result.stdout
    assert _json(result)["data"]["stop_hook"] == "skipped-by-request"
    assert hooks.read_text(encoding="utf-8") == "{not json"


@pytest.mark.parametrize("steps_only", [False, True])
def test_fresh_install_preflight_failure_preserves_entire_target(tmp_path, monkeypatch, steps_only):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "fresh"
    hooks = root / ".codex/hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text("{not json", encoding="utf-8")

    def snapshot():
        return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}

    before = snapshot()
    args = ["install", str(root), "--target", "codex", "--json"]
    if steps_only:
        args.append("--steps-only")
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert _json(result)["error_code"] == "CODEX_INSTALL_ERROR"
    assert snapshot() == before

    result = runner.invoke(app, [*args, "--no-stop-hook"])
    assert result.exit_code == 0, result.stdout
    assert _json(result)["data"]["stop_hook"] == "skipped-by-request"
    assert hooks.read_text(encoding="utf-8") == "{not json"


def test_install_global_codex(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    result = runner.invoke(app, ["install", "--global", "--target", "codex", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["global"] is True and data["targets"] == ["codex"]
    assert (home / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (home / ".codex" / "agents" / "hyperresearch-fetcher.toml").is_file()
    assert not (home / ".codex" / "config.toml").exists()
    assert not (home / ".codex" / "hooks.json").exists()
    assert not (home / ".claude").exists()


def test_install_codex_console_mentions_exec_flags(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "codex"])
    assert result.exit_code == 0
    out = " ".join(result.stdout.split())
    assert "$hyperresearch" in out
    assert "sandbox_workspace_write.network_access=true" in out
    assert "--dangerously-bypass-hook-trust" in out


def test_profile_use_rerenders_codex_install(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    runner.invoke(app, ["install", str(tmp_vault.root), "--target", "all", "--json"])
    result = runner.invoke(app, ["profile", "use", "premier", "--json"])
    assert result.exit_code == 0, result.stdout
    step = tmp_vault.root / ".hyperresearch" / "codex" / "steps" / "hyperresearch-2-width-sweep.md"
    assert 'rendered from profile "premier"' in step.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# run stop-gate
# ---------------------------------------------------------------------------


def _gate(stdin: str | None = None, env: dict | None = None):
    if stdin is None:
        from pathlib import Path

        stdin = json.dumps({"hook_event_name": "Stop", "session_id": "session-a", "stop_hook_active": False, "cwd": str(Path.cwd())})
    return runner.invoke(app, ["run", "stop-gate"], input=stdin, env=env)


def test_stop_gate_silent_without_vault(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _gate()
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_silent_without_runs(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = _gate()
    assert result.exit_code == 0
    assert result.stdout == ""


@pytest.fixture
def running_vault(tmp_vault, monkeypatch):
    from hyperresearch.core.runs import init_run

    monkeypatch.chdir(tmp_vault.root)
    monkeypatch.delenv("HYPERRESEARCH_STOP_GATE", raising=False)
    init_run(tmp_vault, "gate-run", session_id="session-a")
    return tmp_vault


def test_stop_gate_blocks_in_progress_run(running_vault):
    result = _gate()
    assert result.exit_code == 0
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert "gate-run is at step 1 (hyperresearch-1-decompose)" in decision["reason"]
    assert ".hyperresearch/codex/steps/hyperresearch-1-decompose.md" in decision["reason"]
    assert result.stdout.count("\n") == 1  # exactly one JSON object


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]"])
def test_stop_gate_tolerates_bad_stdin(running_vault, stdin):
    result = _gate(stdin)
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_silent_when_stop_hook_active(running_vault):
    result = _gate(json.dumps({"hook_event_name": "Stop", "session_id": "session-a", "stop_hook_active": True, "cwd": str(running_vault.root)}))
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_env_opt_out(running_vault):
    result = _gate("{}", env={"HYPERRESEARCH_STOP_GATE": "0"})
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_rejects_direct_done_transition(running_vault):
    from hyperresearch.core.runs import RunError, set_status

    with pytest.raises(RunError, match="only run finish"):
        set_status(running_vault, "gate-run", "done")
    result = _gate()
    assert result.exit_code == 0
    assert json.loads(result.stdout)["decision"] == "block"


def test_stop_gate_follows_cwd_from_hook_input(running_vault, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    payload = json.dumps({"hook_event_name": "Stop", "session_id": "session-a", "stop_hook_active": False, "cwd": str(running_vault.root)})
    assert json.loads(_gate(payload).stdout)["decision"] == "block"


@pytest.mark.parametrize("field,value", [("session_id", None), ("session_id", "unrelated"), ("session_id", []), ("hook_event_name", "PreToolUse"), ("stop_hook_active", "false"), ("cwd", None), ("cwd", ".")])
def test_stop_gate_silent_for_missing_unrelated_or_invalid_identity(running_vault, field, value):
    payload = {"hook_event_name": "Stop", "session_id": "session-a", "stop_hook_active": False, "cwd": str(running_vault.root)}
    payload[field] = value
    result = _gate(json.dumps(payload))
    assert result.exit_code == 0
    assert result.stdout == ""


@pytest.mark.parametrize("aliases,expected", [({"CODEX_SESSION_ID": "session-a"}, "session-a"), ({"CODEX_THREAD_ID": "session-b"}, "session-b"), ({"CODEX_SESSION_ID": "session-a", "CODEX_THREAD_ID": "session-a"}, "session-a"), ({"CODEX_SESSION_ID": "session-a", "CODEX_THREAD_ID": "session-b"}, None), ({}, None)])
def test_run_init_binds_only_unambiguous_codex_identity(tmp_vault, monkeypatch, aliases, expected):
    monkeypatch.chdir(tmp_vault.root)
    for key in ("CODEX_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(key, raising=False)
    for key, value in aliases.items():
        monkeypatch.setenv(key, value)
    result = runner.invoke(app, ["run", "init", "bound-run", "--json"])
    assert result.exit_code == 0, result.stdout
    assert _json(result)["data"]["manifest"].get("codex_session_id") == expected


def test_run_init_explicit_owner_and_conflicting_rebind(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    first = runner.invoke(app, ["run", "init", "bound-run", "--session-id", "session-a", "--json"])
    assert first.exit_code == 0
    second = runner.invoke(app, ["run", "init", "bound-run", "--session-id", "session-b", "--json"])
    assert second.exit_code == 1
    assert _json(second)["error_code"] == "RUN_ERROR"


def test_stop_gate_two_sessions_two_runs_and_unrelated_session(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    for session in ("session-a", "session-b"):
        result = runner.invoke(app, ["run", "init", session + "-run", "--session-id", session, "--json"])
        assert result.exit_code == 0
    for session in ("session-a", "session-b", "unrelated"):
        payload = {"hook_event_name": "Stop", "session_id": session, "stop_hook_active": False, "cwd": str(tmp_vault.root)}
        result = _gate(json.dumps(payload))
        assert result.exit_code == 0
        if session == "unrelated":
            assert result.stdout == ""
        else:
            assert session + "-run is at step" in json.loads(result.stdout)["reason"]


def test_stop_gate_does_not_infer_missing_payload_owner_from_environment(running_vault):
    payload = {"hook_event_name": "Stop", "stop_hook_active": False, "cwd": str(running_vault.root)}
    result = _gate(json.dumps(payload), env={"CODEX_SESSION_ID": "session-a", "CODEX_THREAD_ID": "session-a"})
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_hidden_from_help():
    result = runner.invoke(app, ["run", "--help"])
    assert "stop-gate" not in result.stdout


def test_run_resume_includes_codex_step_file(running_vault):
    result = runner.invoke(app, ["run", "resume", "--json"])
    assert result.exit_code == 0
    data = _json(result)["data"]
    assert data["skill_to_invoke"] == "hyperresearch-1-decompose"
    assert data["codex_step_file"] == ".hyperresearch/codex/steps/hyperresearch-1-decompose.md"
