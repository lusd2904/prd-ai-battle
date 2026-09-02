"""Verified OpenRouter + OpenCode Zen catalogs. No invented slugs. No secrets."""

from pathlib import Path

from prd_ai_battle.advisor_pool import (
    OPENROUTER_FREE_MODELS,
    OPENROUTER_MUSE_SPARK_12,
    OPENROUTER_MUSE_SPARK_12_CONTRIBUTOR,
    SEED_OPENROUTER_FREE_ADVISOR_IDS,
    SEED_OPENROUTER_FREE_ADVISORS,
    SEED_OPENROUTER_FREE_MODELS,
    ZEN_BASE_URL,
    ZEN_FREE_MODELS,
    ZEN_PICKER_FREE,
    ZEN_PROVIDER_ID,
    is_openrouter_free_model,
    is_zen_free_model,
    is_zen_url,
    pool_catalog,
)
from prd_ai_battle.config import load_config
from prd_ai_battle.overlay import generate_opencode_config, provider_id_for


def test_openrouter_muse_spark_id_is_official_and_not_free():
    assert OPENROUTER_MUSE_SPARK_12 == "meta/muse-spark-1.2"
    assert OPENROUTER_MUSE_SPARK_12_CONTRIBUTOR == "meta/muse-spark-1.2-contributor"
    assert not OPENROUTER_MUSE_SPARK_12.endswith(":free")
    assert OPENROUTER_MUSE_SPARK_12 not in OPENROUTER_FREE_MODELS
    assert OPENROUTER_MUSE_SPARK_12 not in SEED_OPENROUTER_FREE_MODELS
    catalog = pool_catalog()
    assert catalog["openrouter"]["muse_spark_1_2"] == "meta/muse-spark-1.2"
    assert "paid" in catalog["openrouter"]["muse_spark_1_2_note"].lower()


def test_openrouter_free_models_are_verified_slugs():
    for mid in SEED_OPENROUTER_FREE_MODELS:
        assert mid in OPENROUTER_FREE_MODELS
        assert is_openrouter_free_model(mid)
    assert "x-ai/grok-4.6" not in OPENROUTER_FREE_MODELS
    assert not is_openrouter_free_model("x-ai/grok-4.6")
    assert not is_openrouter_free_model("meta/muse-spark-1.2")


def test_zen_free_models_are_opencode_ids_not_openrouter_slugs():
    expected = {
        "mimo-v2.5-free",
        "ling-3.0-flash-fin-free",
        "nemotron-3.5-lightning-free",
        "nemotron-3-ultra-free",
        "big-pickle",
    }
    assert expected <= set(ZEN_FREE_MODELS)
    labels = {label: mid for label, mid in ZEN_PICKER_FREE}
    assert labels["MiMo V2.5 Free"] == "mimo-v2.5-free"
    assert labels["Big Pickle"] == "big-pickle"
    for mid in expected:
        assert not mid.startswith("nvidia/")
        assert not mid.startswith("inclusionai/")
        assert is_zen_free_model(mid)
        assert not is_openrouter_free_model(mid)
    assert ZEN_PROVIDER_ID == "opencode"
    assert is_zen_url(ZEN_BASE_URL)
    assert not is_zen_url("https://openrouter.ai/api/v1")


def test_seed_has_no_default_advisor_grok():
    cfg = load_config(Path("config.example.yaml"), offline=True)
    ids = [a.id for a in cfg.advisors]
    models = [a.model for a in cfg.advisors]
    assert "advisor-grok" not in ids
    assert "x-ai/grok-4.6" not in models
    assert "meta/muse-spark-1.2" not in models
    assert ids == list(SEED_OPENROUTER_FREE_ADVISOR_IDS)
    assert models == list(SEED_OPENROUTER_FREE_MODELS)
    assert SEED_OPENROUTER_FREE_ADVISORS == (
        ("advisor-lightning", "nvidia/nemotron-3.5-lightning:free"),
        ("advisor-ling", "inclusionai/ling-3.0-flash-fin:free"),
        ("advisor-ultra", "nvidia/nemotron-3-ultra-550b-a55b:free"),
        ("advisor-router", "openrouter/free"),
    )


def test_generated_overlay_includes_both_pools_and_disables_leftover_grok():
    cfg = load_config(Path("config.example.yaml"), offline=True)
    overlay = generate_opencode_config(cfg)
    assert "opencode" in overlay["provider"]
    assert overlay["provider"]["opencode"]["options"]["baseURL"] == ZEN_BASE_URL
    zen_models = overlay["provider"]["opencode"]["models"]
    for mid in ("mimo-v2.5-free", "big-pickle", "ling-3.0-flash-fin-free"):
        assert mid in zen_models
    or_models = overlay["provider"]["prd-openrouter"]["models"]
    for mid in SEED_OPENROUTER_FREE_MODELS:
        assert mid in or_models
    assert "meta/muse-spark-1.2" in or_models
    for aid, mid in SEED_OPENROUTER_FREE_ADVISORS:
        assert overlay["agent"][aid]["model"].endswith(mid)
    assert overlay["agent"]["advisor-grok"]["disable"] is True
    assert overlay["agent"]["advisor-sonnet"]["disable"] is True
    assert overlay["agent"]["advisor-glm"]["disable"] is True
    lightning = next(a for a in cfg.advisors if a.id == "advisor-lightning")
    assert provider_id_for(lightning, cfg.gateway.resolved_base_url()) == "prd-openrouter"


def test_write_lock_seed_binds_yaml_primary_id_only():
    from prd_ai_battle.models import Phase, SessionState
    from prd_ai_battle.state import StateMachine
    from prd_ai_battle.write_lock import WriteDenied, WriteLock

    cfg = load_config(Path("config.example.yaml"), offline=True)
    state = SessionState(
        primary=cfg.primary.id,
        advisors=[a.id for a in cfg.advisors],
        phase=Phase.EXECUTE,
        write_lock=True,
    )
    state.artifact_version = "v1"
    lock = WriteLock(state)
    machine = StateMachine(state)
    lock.assert_can_write(cfg.primary.id, machine)
    assert machine.tools_for(cfg.primary.id)
    for advisor in cfg.advisors:
        assert machine.tools_for(advisor.id) == []
    for banned in (
        "grok",
        "claude",
        "codex",
        "claude-opus-5",
        "nvidia/nemotron-3.5-lightning:free",
        "openrouter/free",
        "opencode",
    ):
        try:
            lock.assert_can_write(banned, machine)
            raise AssertionError(f"{banned} must not unlock writes")
        except WriteDenied:
            pass
