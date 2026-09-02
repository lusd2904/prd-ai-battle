"""Offline fixtures for the Mac CLI adapter. No live binaries, no secrets."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from prd_ai_battle.cli_transport import (
    chat_completions_shape,
    exec_argv,
    messages_to_prompt,
    probe_cli,
    run_cli_prompt,
)
from prd_ai_battle.config import ModelConfig, load_config
from prd_ai_battle.ping import ping_config, ping_targets


def _which_map(mapping: dict[str, str]):
    def which(name: str) -> str | None:
        return mapping.get(name)

    return which


def test_probe_missing_is_structured_not_raised():
    probe = probe_cli("codex", which=lambda _n: None)
    assert probe.found is False
    assert probe.as_public_dict()["cli"] == "missing"
    assert "codex" in probe.detail


def test_antigravity_falls_back_to_gemini():
    probe = probe_cli("antigravity", which=_which_map({"gemini": "/usr/local/bin/gemini"}))
    assert probe.found is True
    assert probe.binary == "gemini"
    assert probe.fallback_used == "gemini"
    assert "agy" in probe.tried


def test_exec_argv_presets():
    assert exec_argv("codex", "ping", binary_path="/bin/codex")[0] == "/bin/codex"
    assert "exec" in exec_argv("codex", "ping")
    claude = exec_argv("claude", "hello", binary_path="/bin/claude")
    assert claude == ["/bin/claude", "-p", "hello"]
    grok = exec_argv("grok", "hello", binary_path="/bin/grok")
    assert grok[-1] == "hello"


def test_run_cli_prompt_missing_raises_filenotfound():
    with pytest.raises(FileNotFoundError):
        run_cli_prompt("codex", "hi", which=lambda _n: None)


def test_run_cli_prompt_mocked_runner_redacts_stderr(monkeypatch):
    monkeypatch.setenv("PRD_CODEX_KEY", "codex-super-secret")

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="failed Authorization: Bearer codex-super-secret"
        )

    with pytest.raises(RuntimeError) as exc:
        run_cli_prompt("codex", "hi", which=_which_map({"codex": "/bin/codex"}), runner=runner)
    assert "codex-super-secret" not in str(exc.value)
    assert "***" in str(exc.value)


def test_run_cli_prompt_timeout_is_killed():
    def runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 1), output="", stderr="hung")

    with pytest.raises(RuntimeError, match="timed out"):
        run_cli_prompt("claude", "hi", which=_which_map({"claude": "/bin/claude"}), runner=runner)


def test_chat_completions_shape_and_prompt():
    body = chat_completions_shape("ok", "gpt-5-codex")
    assert body["choices"][0]["message"]["content"] == "ok"
    assert "user:" in messages_to_prompt([{"role": "user", "content": "ping"}])


def test_ping_cli_catalog_missing_is_not_hard_fail(monkeypatch):
    monkeypatch.setenv("PRD_SFP_XIXI_KEY", "xixi-super-secret")
    monkeypatch.setenv("PRD_SFP_OPENROUTER_KEY", "or-super-secret")
    cfg = load_config(Path("config.example.yaml"), offline=False)

    def handler(_request):
        import httpx

        return httpx.Response(200, json={"ok": True})

    import httpx

    report = ping_config(
        cfg,
        transport=httpx.MockTransport(handler),
        which=lambda _n: None,
    )
    blob = str(report)
    assert "xixi-super-secret" not in blob
    cli_rows = [t for t in report["targets"] if t["kind"] == "cli"]
    assert cli_rows
    assert all(t["outcome"] == "missing_cli" for t in cli_rows)
    assert all(t["id"] not in report["hard_fails"] for t in cli_rows)


def test_ping_configured_cli_speaker_uses_version_probe(tmp_path: Path):
    yaml_text = """
gateway:
  base_url: http://127.0.0.1:8000/v1
primary:
  id: primary
  model: gpt-5-codex
  transport: cli
  command: codex
advisors:
  - id: advisor-a
    model: mock
    base_url: http://127.0.0.1:9/v1
"""
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    cfg = load_config(path)

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="codex 1.2.3\n", stderr="")

    from prd_ai_battle.ping import ping_one, ping_targets

    target = next(t for t in ping_targets(cfg) if t.kind == "cli" and t.command == "codex")
    # Inject runner via probe by patching
    import prd_ai_battle.cli_transport as ct

    orig = ct.probe_cli

    def wrapped(command, **kwargs):
        kwargs.setdefault("runner", runner)
        kwargs["which"] = _which_map({"codex": "/bin/codex"})
        return orig(command, **kwargs)

    ct.probe_cli = wrapped  # type: ignore[method-assign]
    try:
        result = ping_one(target, which=_which_map({"codex": "/bin/codex"}))
    finally:
        ct.probe_cli = orig  # type: ignore[method-assign]
    assert result.outcome == "cli_present"
    assert result.hard_fail is False


def test_cli_model_skips_http_url():
    model = ModelConfig(id="primary", model="gpt-5-codex", transport="cli", command="codex")
    assert model.is_cli()
    assert model.resolved_base_url() == ""
    with pytest.raises(Exception, match="cli"):
        model.chat_completions_url()
