from pathlib import Path

import pytest

from prd_ai_battle.config import (
    GATEWAY_BACKUP_MODELS,
    GATEWAY_KEY_ENV,
    GATEWAY_PROVIDER_ID,
    GATEWAY_URL_ENV,
    LOCAL_GATEWAY_URL,
    SEED_KEY_ENVS,
    ConfigError,
    doctor_report,
    expand_env,
    load_config,
    XIXI_KEY_ENV,
    OPENROUTER_KEY_ENV,
)
from prd_ai_battle.mac_speakers import OPTIONAL_KEY_ENVS
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
    Path("prd-ai-battle.env.example"),
    Path("schemas/config.schema.json"),
    Path("src/prd_ai_battle/config.py"),
    Path("src/prd_ai_battle/llm.py"),
    Path("src/prd_ai_battle/bridge.py"),
    Path("src/prd_ai_battle/ping.py"),
    Path("README.md"),
    Path("opencode.json"),
    Path(".opencode/opencode.json"),
    Path(".opencode/plugins/write-lock.js"),
]


def test_example_and_client_have_no_leaked_tunnel_or_vendor_sdk_hosts():
    for path in SCAN_PATHS:
        text = path.read_text(encoding="utf-8")
        for fragment in BANNED_HOST_FRAGMENTS:
            assert fragment not in text, f"{fragment} hardcoded in {path}"
        assert "sk-" not in text


def test_example_uses_product_endpoints_and_env_keys(monkeypatch):
    monkeypatch.delenv(GATEWAY_URL_ENV, raising=False)
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    monkeypatch.delenv(XIXI_KEY_ENV, raising=False)
    monkeypatch.delenv(OPENROUTER_KEY_ENV, raising=False)
    cfg = load_config(Path("config.example.yaml"), offline=True)
    assert cfg.gateway.resolved_base_url() == LOCAL_GATEWAY_URL
    assert LOCAL_GATEWAY_URL == "http://127.0.0.1:8000/v1"
    assert cfg.primary.model == "claude-opus-5"
    assert cfg.primary.resolved_base_url(cfg.gateway) == "https://xixiapi.io/v1"
    assert cfg.primary.api_key_env == XIXI_KEY_ENV
    assert cfg.advisors[0].id == "advisor-lightning"
    assert cfg.advisors[0].model == "nvidia/nemotron-3.5-lightning:free"
    assert cfg.advisors[0].resolved_base_url(cfg.gateway) == "https://openrouter.ai/api/v1"
    assert cfg.advisors[0].api_key_env == OPENROUTER_KEY_ENV
    assert cfg.advisors[1].id == "advisor-ling"
    assert cfg.advisors[1].model == "inclusionai/ling-3.0-flash-fin:free"
    assert cfg.advisors[1].resolved_base_url(cfg.gateway) == "https://openrouter.ai/api/v1"
    assert cfg.advisors[1].api_key_env == OPENROUTER_KEY_ENV
    assert cfg.primary.resolved_key(cfg.gateway) == ""
    assert cfg.primary.chat_completions_url(cfg.gateway).endswith("/chat/completions")


def test_env_keys_redacted_in_doctor(monkeypatch):
    monkeypatch.setenv(XIXI_KEY_ENV, "xixi-super-secret")
    monkeypatch.setenv(OPENROUTER_KEY_ENV, "or-super-secret")
    monkeypatch.setenv(GATEWAY_KEY_ENV, "gw-super-secret")
    cfg = load_config(Path("config.example.yaml"), offline=False)
    assert cfg.primary.resolved_key(cfg.gateway) == "xixi-super-secret"
    assert cfg.advisors[1].resolved_key(cfg.gateway) == "or-super-secret"
    report = doctor_report(cfg)
    blob = str(report)
    assert "xixi-super-secret" not in blob
    assert "or-super-secret" not in blob
    assert "gw-super-secret" not in blob
    assert report["models"][0]["api_key"] == "set"
    assert report["models"][2]["api_key"] == "set"
    assert report["gateway"]["provider_id"] == GATEWAY_PROVIDER_ID
    assert report["gateway"]["models"] == list(GATEWAY_BACKUP_MODELS)
    assert "not Claude" in report["gateway"]["speaks"]
    assert "ping" in report["hint"]


def test_backup_gateway_env_override(monkeypatch):
    monkeypatch.setenv(GATEWAY_URL_ENV, "http://127.0.0.1:9999/v1")
    cfg = load_config(Path("config.example.yaml"), offline=True)
    assert cfg.gateway.resolved_base_url() == "http://127.0.0.1:9999/v1"
    # Per-model URLs stay on the product endpoints.
    assert cfg.primary.resolved_base_url(cfg.gateway) == "https://xixiapi.io/v1"


def test_per_model_override(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    yaml_text = """
gateway:
  base_url: http://127.0.0.1:8000/v1
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


def test_env_example_has_key_names_only():
    path = Path("prd-ai-battle.env.example")
    text = path.read_text(encoding="utf-8")
    assert "prd-ai-battle.env" in text
    assert "copy" in text.lower() or "Copy" in text
    for name in (*SEED_KEY_ENVS, *OPTIONAL_KEY_ENVS):
        assert f"{name}=" in text
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        _name, value = line.split("=", 1)
        assert value.strip() == "", f"{_name} must be empty in env.example"
    assert "sk-" not in text
    assert "grok-4.5" in text
    assert "NOT Claude" in text or "not Claude" in text


def test_expand_env_unset_is_empty():
    assert expand_env("${TOTALLY_UNSET_VAR_XYZ}") == ""


def test_chat_client_uses_model_url_not_a_builtin_host():
    source = Path("src/prd_ai_battle/llm.py").read_text(encoding="utf-8")
    assert "chat_completions_url" in source
    assert "Authorization" in source
    for fragment in BANNED_HOST_FRAGMENTS:
        assert fragment not in source
    assert ChatClient is not None
