"""Advisor catalogs: OpenRouter (incl. :free) and OpenCode Zen Free.

Ids are taken from live catalogs (OpenRouter ``/api/v1/models`` and
OpenCode Zen docs + ``https://opencode.ai/zen/v1/models``). Do not invent
slugs. Zen models are **not** OpenRouter slugs.

Muse Spark 1.2 on OpenRouter is ``meta/muse-spark-1.2`` (paid). The free
Muse path on the Mac OpenCode picker is Zen ``muse-spark-1.2-contributor-free``.
"""

from __future__ import annotations

from typing import Any

# --- OpenRouter -------------------------------------------------------------

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEY_ENV = "PRD_SFP_OPENROUTER_KEY"
OPENROUTER_PROVIDER_ID = "prd-openrouter"

# Official OpenRouter id (https://openrouter.ai/meta/muse-spark-1.2).
# Pricing is not $0 — do not list this as a :free model.
OPENROUTER_MUSE_SPARK_12 = "meta/muse-spark-1.2"
OPENROUTER_MUSE_SPARK_12_CONTRIBUTOR = "meta/muse-spark-1.2-contributor"

# Verified $0 prompt+completion on OpenRouter /api/v1/models (2026-09-02).
# Excludes audio-only / safety-only ids that are a poor discuss advisor.
OPENROUTER_FREE_MODELS: tuple[str, ...] = (
    "z-ai/glm-5.2:free",
    "minimax/minimax-m3:free",
    "minimax/minimax-m2.7:free",
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "inclusionai/ling-3.0-flash-fin:free",
    "cohere/north-mini-code:free",
    "poolside/laguna-s-2.1:free",
    "poolside/laguna-xs-2.1:free",
    "liquid/lfm-2.5-2.6b:free",
    "dots-studio/dots-3-note-preview:free",
    "openrouter/free",
)

# Seed default advisors: verified :free slugs on the user's OpenRouter key.
# Do not invent slugs. Muse Spark 1.2 / grok are not on this list.
SEED_OPENROUTER_FREE_ADVISORS: tuple[tuple[str, str], ...] = (
    ("advisor-lightning", "nvidia/nemotron-3.5-lightning:free"),
    ("advisor-ling", "inclusionai/ling-3.0-flash-fin:free"),
    ("advisor-ultra", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("advisor-router", "openrouter/free"),
)
SEED_OPENROUTER_FREE_ADVISOR_IDS: tuple[str, ...] = tuple(aid for aid, _mid in SEED_OPENROUTER_FREE_ADVISORS)
SEED_OPENROUTER_FREE_MODELS: tuple[str, ...] = tuple(mid for _aid, mid in SEED_OPENROUTER_FREE_ADVISORS)
# Back-compat aliases for the first seed :free advisor (ping URL de-dupe).
SEED_OPENROUTER_FREE_ADVISOR_ID = SEED_OPENROUTER_FREE_ADVISOR_IDS[0]
SEED_OPENROUTER_FREE_MODEL = SEED_OPENROUTER_FREE_MODELS[0]

# Paid / optional OpenRouter ids we document but do not put on the seed team.
OPENROUTER_OPTIONAL_PAID: tuple[str, ...] = (
    OPENROUTER_MUSE_SPARK_12,
    OPENROUTER_MUSE_SPARK_12_CONTRIBUTOR,
    "x-ai/grok-4.6",
)

# --- OpenCode Zen (sst/opencode provider id: ``opencode``) ------------------

# Official provider id in OpenCode config is ``opencode`` (model ref
# ``opencode/big-pickle``). HTTP Chat Completions root for the Free picker
# models that use @ai-sdk/openai-compatible.
ZEN_PROVIDER_ID = "opencode"
ZEN_BASE_URL = "https://opencode.ai/zen/v1"
ZEN_KEY_ENV = "PRD_OPENCODE_ZEN_KEY"
ZEN_KEY_ENV_ALT = "OPENCODE_API_KEY"
ZEN_KEY_ENVS = (ZEN_KEY_ENV, ZEN_KEY_ENV_ALT)

# Mac OpenCode picker labels → official Zen model ids (zen/v1/models + docs).
# These are NOT OpenRouter slugs (no ``org/name:free`` shape).
ZEN_FREE_MODELS: tuple[str, ...] = (
    "mimo-v2.5-free",  # MiMo V2.5 Free
    "ling-3.0-flash-fin-free",  # Ling 3.0 Flash Fin Free
    "nemotron-3.5-lightning-free",  # Nemotron 3.5 Lightning Free
    "nemotron-3-ultra-free",  # Nemotron 3 Ultra Free
    "big-pickle",  # Big Pickle
    "muse-spark-1.2-contributor-free",  # Muse Spark 1.2 Contributor Free (Zen)
    "muse-spark-1.3-contributor-free",
    "deepseek-v4-flash-free",
    "laguna-s-2.1-free",
)

ZEN_PICKER_FREE: tuple[tuple[str, str], ...] = (
    ("MiMo V2.5 Free", "mimo-v2.5-free"),
    ("Ling 3.0 Flash Fin Free", "ling-3.0-flash-fin-free"),
    ("Nemotron 3.5 Lightning Free", "nemotron-3.5-lightning-free"),
    ("Nemotron 3 Ultra Free", "nemotron-3-ultra-free"),
    ("Big Pickle", "big-pickle"),
)

# Chat Completions-compatible Zen Free ids (same endpoint as our HTTP client).
# Muse Spark Contributor Free on Zen uses /responses — keep in catalog, not seed.
ZEN_CHAT_COMPLETIONS_FREE: tuple[str, ...] = (
    "mimo-v2.5-free",
    "ling-3.0-flash-fin-free",
    "nemotron-3.5-lightning-free",
    "nemotron-3-ultra-free",
    "big-pickle",
    "deepseek-v4-flash-free",
    "laguna-s-2.1-free",
)


def is_zen_url(url: str) -> bool:
    root = (url or "").rstrip("/")
    return root.startswith("https://opencode.ai/zen") or root == ZEN_BASE_URL


def is_openrouter_url(url: str) -> bool:
    return "openrouter.ai" in (url or "")


def is_openrouter_free_model(model: str) -> bool:
    return (model or "") in OPENROUTER_FREE_MODELS or (model or "").endswith(":free")


def is_zen_free_model(model: str) -> bool:
    return (model or "") in ZEN_FREE_MODELS


def openrouter_overlay_models() -> dict[str, dict[str, str]]:
    models: dict[str, dict[str, str]] = {
        OPENROUTER_MUSE_SPARK_12: {"name": "Muse Spark 1.2 (OpenRouter, paid)"},
        OPENROUTER_MUSE_SPARK_12_CONTRIBUTOR: {
            "name": "Muse Spark 1.2 Contributor (OpenRouter, paid)"
        },
        "x-ai/grok-4.6": {"name": "Grok 4.6 (OpenRouter, optional — not seed; 402 without credits)"},
    }
    seed_models = set(SEED_OPENROUTER_FREE_MODELS)
    for mid in OPENROUTER_FREE_MODELS:
        tag = "seed advisor" if mid in seed_models else "OpenRouter :free"
        models.setdefault(mid, {"name": f"{mid} ({tag})"})
    return models


def zen_overlay_models() -> dict[str, dict[str, str]]:
    models: dict[str, dict[str, str]] = {}
    labels = {mid: label for label, mid in ZEN_PICKER_FREE}
    for mid in ZEN_FREE_MODELS:
        label = labels.get(mid, mid)
        models[mid] = {"name": f"{label} (OpenCode Zen Free)"}
    return models


def zen_overlay_provider() -> dict[str, Any]:
    """Official ``opencode`` provider — not an OpenRouter alias."""
    options = {
        "baseURL": ZEN_BASE_URL,
        "apiKey": f"{{env:{ZEN_KEY_ENV}}}",
    }
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "OpenCode Zen (official provider id: opencode)",
        "env": list(ZEN_KEY_ENVS),
        "options": options,
        "package": "@opencode-ai/ai/providers/openai-compatible",
        "settings": dict(options),
        "models": zen_overlay_models(),
        "optional": True,
        "zen": True,
    }


def openrouter_overlay_provider() -> dict[str, Any]:
    options = {
        "baseURL": OPENROUTER_BASE_URL,
        "apiKey": f"{{env:{OPENROUTER_KEY_ENV}}}",
    }
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "OpenRouter (free :free variants + optional paid)",
        "env": [OPENROUTER_KEY_ENV],
        "options": options,
        "package": "@opencode-ai/ai/providers/openai-compatible",
        "settings": dict(options),
        "models": openrouter_overlay_models(),
        "optional": True,
    }


def pool_catalog() -> dict[str, Any]:
    """Public, key-free view of both advisor pools."""
    return {
        "openrouter": {
            "provider_id": OPENROUTER_PROVIDER_ID,
            "base_url": OPENROUTER_BASE_URL,
            "key_env": OPENROUTER_KEY_ENV,
            "muse_spark_1_2": OPENROUTER_MUSE_SPARK_12,
            "muse_spark_1_2_note": (
                "Official OpenRouter id is meta/muse-spark-1.2 (paid). "
                "There is no :free slug. Contributor is "
                f"{OPENROUTER_MUSE_SPARK_12_CONTRIBUTOR} (also paid)."
            ),
            "free_models": list(OPENROUTER_FREE_MODELS),
            "optional_paid": list(OPENROUTER_OPTIONAL_PAID),
            "seed_advisors": [
                {"id": aid, "model": mid} for aid, mid in SEED_OPENROUTER_FREE_ADVISORS
            ],
        },
        "opencode_zen": {
            "provider_id": ZEN_PROVIDER_ID,
            "base_url": ZEN_BASE_URL,
            "key_envs": list(ZEN_KEY_ENVS),
            "note": (
                "OpenCode Zen Free picker models. Provider id is `opencode` "
                "(sst/opencode), not OpenRouter. HTTP: transport=http + "
                f"base_url {ZEN_BASE_URL}. Docker stays HTTP-only."
            ),
            "picker_free": [{"label": label, "model": mid} for label, mid in ZEN_PICKER_FREE],
            "free_models": list(ZEN_FREE_MODELS),
            "chat_completions_free": list(ZEN_CHAT_COMPLETIONS_FREE),
        },
    }


__all__ = [
    "OPENROUTER_BASE_URL",
    "OPENROUTER_FREE_MODELS",
    "OPENROUTER_KEY_ENV",
    "OPENROUTER_MUSE_SPARK_12",
    "OPENROUTER_MUSE_SPARK_12_CONTRIBUTOR",
    "OPENROUTER_OPTIONAL_PAID",
    "OPENROUTER_PROVIDER_ID",
    "SEED_OPENROUTER_FREE_ADVISORS",
    "SEED_OPENROUTER_FREE_ADVISOR_ID",
    "SEED_OPENROUTER_FREE_ADVISOR_IDS",
    "SEED_OPENROUTER_FREE_MODEL",
    "SEED_OPENROUTER_FREE_MODELS",
    "ZEN_BASE_URL",
    "ZEN_CHAT_COMPLETIONS_FREE",
    "ZEN_FREE_MODELS",
    "ZEN_KEY_ENV",
    "ZEN_KEY_ENV_ALT",
    "ZEN_KEY_ENVS",
    "ZEN_PICKER_FREE",
    "ZEN_PROVIDER_ID",
    "is_openrouter_free_model",
    "is_openrouter_url",
    "is_zen_free_model",
    "is_zen_url",
    "openrouter_overlay_provider",
    "pool_catalog",
    "zen_overlay_provider",
]
