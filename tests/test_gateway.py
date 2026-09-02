import re
from pathlib import Path

import pytest

from prd_ai_battle.config import (
    GATEWAY_KEY_ENV,
    GATEWAY_URL_ENV,
    LOCAL_GATEWAY_URL,
    ConfigError,
    doctor_report,
    expand_env,
    load_config,
)
from prd_ai_battle.llm import ChatClient

BANNED_HOST_FRAGMENTS = (
    "api.openai.com",
    "api.anthropic.com",
    "api.deepseek.com",
    "googleapis.com",
    "luapi.top",
)

# SFP vendor roots belong only in config.sfp.example.yaml, not the loopback default.
SFP_HOST_FRAGMENTS = (
    "xixiapi.io",
    "openrouter.ai",
    "integrate.api.nvidia.com",
    "build.nvidia.com",
)

SCAN_PATHS = [
    Path("config.example.yaml"),
    Path("schemas/config.schema.json"),
    Path("src/prd_ai_battle/config.py"),
    Path("src/prd_ai_battle/llm.py"),
    Path("README.md"),
]

SFP_EXAMPLE = Path("config.sfp.example.yaml")

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-or-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_\-]{16,}"),
)

SKIPPED_SFP_MODELS = (
    "claude-fable-5",
    "z-ai/glm-5.2",
    "deepseek-ai/deepseek-v4-flash-0731",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "gpt-5.6-sol",
)


def test_example_and_client_have_no_vendor_or_tunnel_hosts():
    for path in SCAN_PATHS:
        text = path.read_text(encoding="utf-8")
        for fragment in (*BANNED_HOST_FRAGMENTS, *SFP_HOST_FRAGMENTS):
            assert fragment not in text, f"{fragment} hardcoded in {path}"


def test_example_defaults_to_local_gateway(monkeypatch):
    monkeypatch.delenv(GATEWAY_URL_ENV, raising=False)
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    cfg = load_config(Path("config.example.yaml"), offline=True)
    assert cfg.gateway.resolved_base_url() == LOCAL_GATEWAY_URL
    assert cfg.primary.resolved_base_url(cfg.gateway) == LOCAL_GATEWAY_URL
    assert cfg.advisors[0].resolved_base_url(cfg.gateway) == LOCAL_GATEWAY_URL
    assert cfg.primary.resolved_key(cfg.gateway) == ""
    assert cfg.primary.chat_completions_url(cfg.gateway).endswith("/chat/completions")


def test_env_overrides_gateway(monkeypatch):
    monkeypatch.setenv(GATEWAY_URL_ENV, "http://127.0.0.1:9999/v1")
    monkeypatch.setenv(GATEWAY_KEY_ENV, "local-secret")
    cfg = load_config(Path("config.example.yaml"), offline=False)
    assert cfg.primary.resolved_base_url(cfg.gateway) == "http://127.0.0.1:9999/v1"
    assert cfg.primary.resolved_key(cfg.gateway) == "local-secret"
    report = doctor_report(cfg)
    assert report["gateway"]["api_key"] == "set"
    assert "local-secret" not in str(report)


def test_per_model_override(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    yaml_text = """
gateway:
  base_url: http://127.0.0.1:4000/v1
  api_key: ${PRD_AI_GATEWAY_KEY:-gw-default}
primary:
  id: primary
  model: a
  api_key_env: PRIMARY_KEY
advisors:
  - id: advisor-a
    model: b
    base_url: http://127.0.0.1:4001/v1
"""
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setenv("PRIMARY_KEY", "from-env")
    cfg = load_config(path)
    assert cfg.primary.resolved_key(cfg.gateway) == "from-env"
    assert cfg.advisors[0].resolved_base_url(cfg.gateway) == "http://127.0.0.1:4001/v1"
    assert cfg.advisors[0].resolved_key(cfg.gateway) == "gw-default"


def test_empty_base_url_is_an_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(GATEWAY_URL_ENV, "")
    path = tmp_path / "cfg.yaml"
    path.write_text(
        """
gateway:
  base_url: ${PRD_AI_GATEWAY_URL:-}
primary:
  id: primary
  model: a
advisors:
  - id: advisor-a
    model: b
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="base_url"):
        load_config(path)


def test_expand_env_unset_is_empty():
    assert expand_env("${TOTALLY_UNSET_VAR_XYZ}") == ""


def test_chat_client_uses_model_url_not_a_builtin_host():
    source = Path("src/prd_ai_battle/llm.py").read_text(encoding="utf-8")
    assert "chat_completions_url" in source
    assert "Authorization" in source
    for fragment in (*BANNED_HOST_FRAGMENTS, *SFP_HOST_FRAGMENTS):
        assert fragment not in source
    assert ChatClient is not None


def test_sfp_example_has_no_plaintext_secrets():
    text = SFP_EXAMPLE.read_text(encoding="utf-8")
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        assert match is None, f"possible secret in {SFP_EXAMPLE}: {match.group(0)!r}"
    for match in re.finditer(r"(?m)^\s*api_key:\s*(\S+)", text):
        value = match.group(1)
        assert value.startswith("${") and value.endswith("}"), (
            f"api_key must be env interpolation, got {value!r}"
        )
    assert "PRD_SFP_XIXI_KEY" in text
    assert "PRD_SFP_OPENROUTER_KEY" in text
    assert "PRD_AI_GATEWAY_KEY" in text


def test_sfp_example_loads_and_resolves_offline(monkeypatch):
    monkeypatch.delenv(GATEWAY_URL_ENV, raising=False)
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    monkeypatch.delenv("PRD_SFP_XIXI_KEY", raising=False)
    monkeypatch.delenv("PRD_SFP_OPENROUTER_KEY", raising=False)
    cfg = load_config(SFP_EXAMPLE, offline=True)
    assert cfg.offline is True
    assert cfg.primary.id == "primary"
    assert cfg.primary.model == "claude-opus-5"
    assert cfg.primary.api_key_env == "PRD_SFP_XIXI_KEY"
    assert cfg.primary.resolved_base_url(cfg.gateway) == "https://xixiapi.io/v1"
    assert cfg.gateway.resolved_base_url() == "https://xixiapi.io/v1"
    assert cfg.primary.chat_completions_url(cfg.gateway) == (
        "https://xixiapi.io/v1/chat/completions"
    )

    by_model = {m.model: m for m in cfg.advisors}
    assert "claude-sonnet-5" in by_model
    assert "x-ai/grok-4.6" in by_model
    sonnet = by_model["claude-sonnet-5"]
    grok_or = by_model["x-ai/grok-4.6"]
    grok_45 = by_model["grok-4.5"]
    grok_composer = by_model["grok-composer-2.5-fast"]

    assert sonnet.resolved_base_url(cfg.gateway) == "https://xixiapi.io/v1"
    assert sonnet.api_key_env == "PRD_SFP_XIXI_KEY"
    assert grok_or.resolved_base_url(cfg.gateway) == "https://openrouter.ai/api/v1"
    assert grok_or.api_key_env == "PRD_SFP_OPENROUTER_KEY"
    assert grok_or.chat_completions_url(cfg.gateway) == (
        "https://openrouter.ai/api/v1/chat/completions"
    )
    assert grok_45.resolved_base_url(cfg.gateway) == "http://127.0.0.1:8000/v1"
    assert grok_45.api_key_env == GATEWAY_KEY_ENV
    assert grok_composer.resolved_base_url(cfg.gateway) == "http://127.0.0.1:8000/v1"
    assert grok_composer.api_key_env == GATEWAY_KEY_ENV

    models = {m.model for m in cfg.all_models()}
    for skipped in SKIPPED_SFP_MODELS:
        assert skipped not in models
    assert "grok-4.6" not in models  # xixi grok-4.6 skipped; OpenRouter id is x-ai/grok-4.6


def test_sfp_example_keys_resolve_from_env_and_doctor_redacts(monkeypatch):
    monkeypatch.delenv(GATEWAY_URL_ENV, raising=False)
    monkeypatch.setenv("PRD_SFP_XIXI_KEY", "xixi-test-secret")
    monkeypatch.setenv("PRD_SFP_OPENROUTER_KEY", "or-test-secret")
    monkeypatch.setenv(GATEWAY_KEY_ENV, "gw-test-secret")
    cfg = load_config(SFP_EXAMPLE, offline=True)
    assert cfg.primary.resolved_key(cfg.gateway) == "xixi-test-secret"
    by_model = {m.model: m for m in cfg.advisors}
    assert by_model["claude-sonnet-5"].resolved_key(cfg.gateway) == "xixi-test-secret"
    assert by_model["x-ai/grok-4.6"].resolved_key(cfg.gateway) == "or-test-secret"
    assert by_model["grok-4.5"].resolved_key(cfg.gateway) == "gw-test-secret"
    report = doctor_report(cfg)
    blob = str(report)
    assert "xixi-test-secret" not in blob
    assert "or-test-secret" not in blob
    assert "gw-test-secret" not in blob
    assert report["models"][0]["api_key"] == "set"
