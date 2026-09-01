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

SCAN_PATHS = [
    Path("config.example.yaml"),
    Path("schemas/config.schema.json"),
    Path("src/prd_ai_battle/config.py"),
    Path("src/prd_ai_battle/llm.py"),
    Path("README.md"),
]


def test_example_and_client_have_no_vendor_or_tunnel_hosts():
    for path in SCAN_PATHS:
        text = path.read_text(encoding="utf-8")
        for fragment in BANNED_HOST_FRAGMENTS:
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
    for fragment in BANNED_HOST_FRAGMENTS:
        assert fragment not in source
    assert ChatClient is not None
