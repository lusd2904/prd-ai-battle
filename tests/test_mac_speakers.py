"""Optional Mac speakers: HTTP + CLI catalog, seed team unchanged, no secrets."""

from pathlib import Path

from prd_ai_battle.config import (
    doctor_report,
    load_config,
    SEED_KEY_ENVS,
)
from prd_ai_battle.mac_speakers import (
    ANTIGRAVITY_PROVIDER_ID,
    CLAUDE_CODE_PROVIDER_ID,
    CODEX_PROVIDER_ID,
    GEMINI_PROVIDER_ID,
    OPTIONAL_KEY_ENVS,
    OPTIONAL_PROVIDER_IDS,
    XAI_PROVIDER_ID,
    infer_cli_command,
    optional_overlay_providers,
    preset_for_command,
)
from prd_ai_battle.overlay import generate_opencode_config
from prd_ai_battle.write_lock import WriteLock
from prd_ai_battle.models import Phase, SessionState
from prd_ai_battle.state import StateMachine


def test_seed_yaml_still_loads_xixi_openrouter_team(monkeypatch):
    monkeypatch.delenv("PRD_SFP_XIXI_KEY", raising=False)
    cfg = load_config(Path("config.example.yaml"), offline=True)
    assert cfg.primary.model == "claude-opus-5"
    assert cfg.primary.transport == "http"
    assert cfg.advisors[0].id == "advisor-lightning"
    assert cfg.advisors[0].model == "nvidia/nemotron-3.5-lightning:free"
    assert cfg.advisors[1].id == "advisor-ling"
    assert cfg.advisors[1].model == "inclusionai/ling-3.0-flash-fin:free"
    assert cfg.advisors[1].resolved_base_url(cfg.gateway) == "https://openrouter.ai/api/v1"


def test_optional_overlay_catalog_has_all_mac_speakers():
    catalog = optional_overlay_providers()
    for pid in OPTIONAL_PROVIDER_IDS:
        assert pid in catalog
        assert catalog[pid]["optional"] is True
        assert catalog[pid]["env"]
        assert catalog[pid]["models"]
    assert "gpt-5-codex" in catalog[CODEX_PROVIDER_ID]["models"]
    assert "gemini-2.5-flash" in catalog[ANTIGRAVITY_PROVIDER_ID]["models"]
    assert "gemini-2.5-flash" in catalog[GEMINI_PROVIDER_ID]["models"]
    assert catalog[XAI_PROVIDER_ID]["options"]["baseURL"] == "https://api.x.ai/v1"


def test_infer_cli_command_and_antigravity_fallback_chain():
    assert infer_cli_command("gpt-5-codex") == "codex"
    assert infer_cli_command("claude-opus-5") == "claude"
    assert infer_cli_command("gemini-2.5-flash") == "gemini"
    assert infer_cli_command("grok-4") == "grok"
    assert infer_cli_command("x", "反重力") == "反重力"
    agy = preset_for_command("antigravity")
    assert agy is not None
    assert agy.binaries == ("agy", "antigravity", "gemini")
    assert preset_for_command("claude-code").binaries == ("claude",)


def test_doctor_reports_optional_cli_missing_without_crash(monkeypatch):
    monkeypatch.delenv("PRD_SFP_XIXI_KEY", raising=False)
    cfg = load_config(Path("config.example.yaml"), offline=True)
    report = doctor_report(cfg)
    blob = str(report)
    assert "sk-" not in blob
    assert report["primary_id"] == "primary"
    assert "yaml primary.id" in report["write_lock_binds"]
    ids = {row["provider_id"] for row in report["optional_mac_speakers"]}
    assert ids >= {
        CODEX_PROVIDER_ID,
        CLAUDE_CODE_PROVIDER_ID,
        ANTIGRAVITY_PROVIDER_ID,
        GEMINI_PROVIDER_ID,
        XAI_PROVIDER_ID,
    }
    for row in report["optional_mac_speakers"]:
        assert row["cli"]["cli"] in {"missing", "present"}
        assert row["api_key"] in {"set", "missing"}


def test_env_example_optional_keys_are_names_only():
    text = Path("prd-ai-battle.env.example").read_text(encoding="utf-8")
    for name in (*SEED_KEY_ENVS, *OPTIONAL_KEY_ENVS):
        assert f"{name}=" in text
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        _name, value = line.split("=", 1)
        assert value.strip() == ""
    assert "sk-" not in text


def test_schema_allows_transport_and_command():
    import json

    schema = json.loads(Path("schemas/config.schema.json").read_text(encoding="utf-8"))
    props = schema["$defs"]["model"]["properties"]
    assert props["transport"]["enum"] == ["http", "cli"]
    assert "command" in props


def test_write_lock_uses_yaml_primary_id_not_cli_or_model_name():
    state = SessionState(primary="lead", advisors=["advisor-claude"], phase=Phase.EXECUTE)
    state.artifact_version = "v1"
    lock = WriteLock(state)
    machine = StateMachine(state)
    assert machine.tools_for("lead")
    assert machine.tools_for("advisor-claude") == []
    assert machine.tools_for("claude") == []
    assert machine.tools_for("claude-opus-5") == []
    lock.assert_can_write("lead", machine)
    try:
        lock.assert_can_write("claude", machine)
        raise AssertionError("CLI binary name must not unlock writes")
    except Exception as exc:
        assert "primary" in str(exc).lower() or "lead" in str(exc)


def test_generated_overlay_from_seed_keeps_optional_catalog():
    cfg = load_config(Path("config.example.yaml"), offline=True)
    overlay = generate_opencode_config(cfg)
    assert set(OPTIONAL_PROVIDER_IDS) <= set(overlay["provider"])
    assert "opencode" in overlay["provider"]
    assert overlay["agent"]["primary"]["model"].endswith("claude-opus-5")
