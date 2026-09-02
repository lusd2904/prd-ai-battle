"""Local gitignored yaml is the live config; seed is only a copy source."""

from pathlib import Path

from prd_ai_battle.config import (
    GATEWAY_BACKUP_MODELS,
    GATEWAY_PROVIDER_ID,
    apply_user_set,
    ensure_local_config,
    load_config,
    load_env_file,
    local_env_path,
    local_yaml_path,
    save_local_config,
)
from prd_ai_battle.overlay import generate_opencode_config


def _seed_repo(tmp_path: Path) -> Path:
    (tmp_path / "config.example.yaml").write_text(
        Path("config.example.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_init_copies_seed_and_save_does_not_store_keys(tmp_path: Path, monkeypatch):
    repo = _seed_repo(tmp_path)
    dest = ensure_local_config(repo)
    assert dest == local_yaml_path(repo)
    cfg = load_config(dest)
    cfg.primary.model = "my-custom-opus"
    cfg.primary.base_url = "http://127.0.0.1:9000/v1"
    save_local_config(cfg, repo=repo, keys={"PRD_SFP_XIXI_KEY": "super-secret-key"})
    yaml_text = local_yaml_path(repo).read_text(encoding="utf-8")
    env_text = local_env_path(repo).read_text(encoding="utf-8")
    assert "my-custom-opus" in yaml_text
    assert "http://127.0.0.1:9000/v1" in yaml_text
    assert "super-secret-key" not in yaml_text
    assert "super-secret-key" in env_text
    monkeypatch.delenv("PRD_SFP_XIXI_KEY", raising=False)
    load_env_file(local_env_path(repo))
    again = load_config(local_yaml_path(repo))
    assert again.primary.model == "my-custom-opus"
    assert again.primary.resolved_base_url(again.gateway) == "http://127.0.0.1:9000/v1"
    assert again.primary.resolved_key(again.gateway) == "super-secret-key"


def test_generated_opencode_overlay_follows_yaml_not_seed_opus(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    cfg = load_config(ensure_local_config(repo))
    keys = apply_user_set(
        cfg,
        primary_id="lead",
        primary_model="not-opus",
        primary_base_url="http://127.0.0.1:7777/v1",
        advisor_id="advisor-grok",
        advisor_model="not-grok",
        advisor_base_url="http://127.0.0.1:7778/v1",
    )
    assert keys == {}
    overlay = generate_opencode_config(cfg)
    assert overlay["default_agent"] == "lead"
    assert overlay["agent"]["lead"]["model"].endswith("not-opus")
    assert "claude-opus-5" not in overlay["agent"]["lead"]["model"]
    assert overlay["agent"]["advisor-grok"]["model"].endswith("not-grok")
    assert overlay["agent"]["lead"]["permission"]["task"] == "deny"
    assert overlay["agents"]["lead"]["permissions"] == [
        {"action": "subagent", "resource": "*", "effect": "deny"}
    ]
    assert overlay["agent"]["primary"]["disable"] is True
    gw = overlay["provider"][GATEWAY_PROVIDER_ID]
    assert set(gw["models"]) >= set(GATEWAY_BACKUP_MODELS)
    assert "claude-opus-5" not in gw["models"]
    assert "claude-sonnet-5" not in gw["models"]


def test_generated_overlay_from_seed_keeps_backup_as_grok(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    cfg = load_config(ensure_local_config(repo))
    overlay = generate_opencode_config(cfg)
    gw = overlay["provider"][GATEWAY_PROVIDER_ID]
    assert gw["options"]["baseURL"].endswith(":8000/v1") or "127.0.0.1:8000" in gw["options"]["baseURL"]
    assert "grok-4.5" in gw["models"]
    assert "grok-composer-2.5-fast" in gw["models"]
    assert not any(name.startswith("claude") for name in gw["models"])
    # Live seed agents stay on xixi / OpenRouter, not fake Claude-on-gateway aliases.
    assert overlay["agent"]["primary"]["model"].endswith("claude-opus-5")
    assert "prd-gateway" not in overlay["agent"]["primary"]["model"]
    assert overlay["agent"]["advisor-grok"]["model"].endswith("x-ai/grok-4.6")


def test_generated_overlay_lists_optional_mac_providers(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    cfg = load_config(ensure_local_config(repo))
    overlay = generate_opencode_config(cfg)
    for pid in ("prd-codex", "prd-claude-code", "prd-antigravity", "prd-gemini", "prd-xai", "prd-gateway"):
        assert pid in overlay["provider"]
        assert pid in overlay["providers"]
    # Seed team unchanged.
    assert overlay["agent"]["primary"]["model"].endswith("claude-opus-5")
    assert overlay["agent"]["advisor-sonnet"]["model"].endswith("claude-sonnet-5")
    assert overlay["agent"]["advisor-grok"]["model"].endswith("x-ai/grok-4.6")
    assert overlay["default_agent"] == "primary"


def test_config_set_cli_speaker_as_primary_or_advisor(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    cfg = load_config(ensure_local_config(repo))
    apply_user_set(
        cfg,
        primary_transport="cli",
        primary_command="claude",
        primary_model="claude-opus-5",
        advisor_id="advisor-codex",
        add_advisor=True,
        advisor_transport="cli",
        advisor_command="codex",
        advisor_model="gpt-5-codex",
    )
    assert cfg.primary.transport == "cli"
    assert cfg.primary.command == "claude"
    assert cfg.primary.id == "primary"
    overlay = generate_opencode_config(cfg)
    assert overlay["agent"]["primary"]["model"].startswith("prd-claude-code/")
    assert overlay["agent"]["advisor-codex"]["model"].startswith("prd-codex/")
    # write_lock binds yaml primary.id, not the CLI binary or model name.
    assert overlay["default_agent"] == "primary"
    dest = save_local_config(cfg, repo=repo)
    text = dest.read_text(encoding="utf-8")
    assert "transport: cli" in text
    assert "command: claude" in text
    assert "command: codex" in text


def test_gitignore_covers_local_yaml_and_env():
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert "prd-ai-battle.yaml" in text
    assert "prd-ai-battle.env" in text
    assert "prd-ai-battle.opencode.json" in text
    assert ".prd-ai-battle-board/" in text
    assert "prd-ai-battle.env.example" not in text
    assert Path("prd-ai-battle.env.example").is_file()
