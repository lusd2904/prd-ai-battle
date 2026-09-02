"""Local gitignored yaml is the live config; seed is only a copy source."""

from pathlib import Path

from prd_ai_battle.config import (
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
    assert overlay["agent"]["lead"]["permission"]["task"]["advisor-grok"] == "allow"
    assert overlay["agent"]["primary"]["disable"] is True


def test_gitignore_covers_local_yaml_and_env():
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert "prd-ai-battle.yaml" in text
    assert "prd-ai-battle.env" in text
    assert "prd-ai-battle.opencode.json" in text
