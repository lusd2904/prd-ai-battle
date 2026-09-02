"""Generate an OpenCode config overlay from the user's local yaml.

Committed opencode.json / agents/*.md are seed/templates. Launch writes
prd-ai-battle.opencode.json (gitignored) from the last-saved yaml so the
user can change primary, advisors, base_url, and models without editing
the git tree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from prd_ai_battle.config import (
    GATEWAY_BACKUP_MODELS,
    GATEWAY_KEY_ENV,
    GATEWAY_PROVIDER_ID,
    AppConfig,
    ModelConfig,
    generated_opencode_path,
    is_backup_gateway_url,
)
from prd_ai_battle.mac_speakers import (
    XAI_BASE_URL,
    XAI_PROVIDER_ID,
    infer_cli_command,
    optional_overlay_providers,
    provider_id_for_command,
)


SEED_AGENT_IDS = ("primary", "advisor-sonnet", "advisor-grok", "build")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "gateway"


def _claude_alias_on_gateway(model_id: str) -> bool:
    """grok2api does not speak Claude — never list those ids on prd-gateway."""
    return model_id.lower().startswith("claude")


def provider_id_for(model: ModelConfig, gateway_url: str) -> str:
    if model.is_cli():
        command = infer_cli_command(model.model, model.command)
        pid = provider_id_for_command(command)
        if pid:
            return pid
        return "prd-cli-" + _slug(command or model.id)
    url = model.resolved_base_url() or gateway_url
    if is_backup_gateway_url(url, gateway_url):
        return GATEWAY_PROVIDER_ID
    if (url or "").rstrip("/") == XAI_BASE_URL.rstrip("/"):
        return XAI_PROVIDER_ID
    host = urlparse(url).netloc or urlparse(url).path or "gateway"
    return "prd-" + _slug(host)


def model_ref(model: ModelConfig, gateway_url: str) -> str:
    return f"{provider_id_for(model, gateway_url)}/{model.model}"


def _provider_entry(model: ModelConfig, gateway_url: str) -> tuple[str, dict]:
    pid = provider_id_for(model, gateway_url)
    catalog = optional_overlay_providers()
    if pid in catalog:
        entry = catalog[pid]
        entry["models"] = {
            **entry.get("models", {}),
            model.model: {"name": f"{model.id} ({model.model})"},
        }
        if model.api_key_env and model.api_key_env not in entry["env"]:
            entry["env"].append(model.api_key_env)
        if model.is_cli():
            entry["cli"] = {
                "command": infer_cli_command(model.model, model.command),
                "transport": "cli",
            }
        return pid, entry
    url = (model.resolved_base_url() or gateway_url).rstrip("/")
    key_env = model.api_key_env or ""
    options = {"baseURL": url} if url else {}
    env: list[str] = []
    if key_env:
        options["apiKey"] = f"{{env:{key_env}}}"
        env.append(key_env)
    entry = {
        "npm": "@ai-sdk/openai-compatible",
        "name": urlparse(url).netloc or pid,
        "env": env,
        "options": options,
        "package": "@opencode-ai/ai/providers/openai-compatible",
        "settings": dict(options),
        "models": {
            model.model: {"name": f"{model.id} ({model.model})"},
        },
    }
    if model.is_cli():
        entry["cli"] = {
            "command": infer_cli_command(model.model, model.command),
            "transport": "cli",
        }
    return pid, entry


def _backup_gateway_entry(cfg: AppConfig) -> dict:
    """Stable prd-gateway provider: grok2api models only (not Claude aliases)."""
    url = cfg.gateway.resolved_base_url().rstrip("/")
    options = {
        "baseURL": url,
        "apiKey": f"{{env:{GATEWAY_KEY_ENV}}}",
    }
    models = {
        mid: {"name": f"Backup {mid}"}
        for mid in GATEWAY_BACKUP_MODELS
    }
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Local backup gateway (grok2api)",
        "env": [GATEWAY_KEY_ENV],
        "options": options,
        "package": "@opencode-ai/ai/providers/openai-compatible",
        "settings": dict(options),
        "models": models,
    }


def generate_opencode_config(cfg: AppConfig) -> dict:
    """OpenCode v1+v2 overlay driven entirely by AppConfig (the local yaml)."""
    gateway_url = cfg.gateway.resolved_base_url()
    providers: dict[str, dict] = {
        GATEWAY_PROVIDER_ID: _backup_gateway_entry(cfg),
        **optional_overlay_providers(),
    }
    for model in cfg.all_models():
        pid, entry = _provider_entry(model, gateway_url)
        if pid == GATEWAY_PROVIDER_ID and _claude_alias_on_gateway(model.model):
            continue
        if pid in providers:
            providers[pid]["models"][model.model] = {"name": f"{model.id} ({model.model})"}
            for env_name in entry["env"]:
                if env_name not in providers[pid]["env"]:
                    providers[pid]["env"].append(env_name)
        else:
            providers[pid] = entry

    primary_ref = model_ref(cfg.primary, gateway_url)
    agent: dict[str, dict] = {}
    agents: dict[str, dict] = {}

    # Discuss/review UX is a Python-orchestrated shared timeline. Do not allow
    # OpenCode Agent Teams / sidecar teammate panes.
    agent[cfg.primary.id] = {
        "description": "Lead drafter. Writes files only in execute/revise (write_lock).",
        "mode": "primary",
        "model": primary_ref,
        "prompt": "{file:./.opencode/prompts/primary.txt}",
        "permission": {
            "edit": "allow",
            "bash": "allow",
            "task": "deny",
        },
    }
    agents[cfg.primary.id] = {
        "description": "Lead drafter. Writes files only in execute/revise (write_lock).",
        "mode": "primary",
        "model": primary_ref,
        "system": f"You are {cfg.primary.id}, the primary / lead of prd-ai-battle. See AGENTS.md.",
        "permissions": [
            {"action": "subagent", "resource": "*", "effect": "deny"},
        ],
    }

    for advisor in cfg.advisors:
        ref = model_ref(advisor, gateway_url)
        agent[advisor.id] = {
            "description": f"Advisor ({advisor.model}). Discuss and review only. Never edits files.",
            "mode": "all",
            "model": ref,
            "prompt": "{file:./.opencode/prompts/advisor.txt}",
            "permission": {"edit": "deny", "bash": "deny"},
            "tools": {"write": False, "edit": False, "bash": False},
        }
        agents[advisor.id] = {
            "description": f"Advisor ({advisor.model}). Discuss and review only. Never edits files.",
            "mode": "all",
            "model": ref,
            "system": f"You are {advisor.id}. You never edit files or run shell. See AGENTS.md.",
            "permissions": [
                {"action": "edit", "resource": "*", "effect": "deny"},
                {"action": "shell", "resource": "*", "effect": "deny"},
            ],
        }

    live_ids = set(cfg.model_ids())
    for seed_id in SEED_AGENT_IDS:
        if seed_id not in live_ids:
            agent[seed_id] = {"disable": True}
            agents[seed_id] = {"disabled": True}

    commands = {}
    for name, description in (
        ("discuss", "Shared multi-model discuss chat (one labeled timeline, no teammate panes)"),
        ("lock", "Lock the 响应对照表 → phase=locked"),
        ("execute", "Primary writes v1 (write_lock opens for current primary id only)"),
        ("review", "Advisors review brief + matrix + chapter_diff only"),
        ("revise", "Primary writes the next artifact_version"),
    ):
        commands[name] = {
            "description": description,
            "agent": cfg.primary.id,
            "template": f"Run the {name} phase as agent {cfg.primary.id}. See AGENTS.md.",
        }

    return {
        "$schema": "https://opencode.ai/config.json",
        "model": primary_ref,
        "default_agent": cfg.primary.id,
        "autoupdate": False,
        "share": "disabled",
        "instructions": ["AGENTS.md"],
        "provider": providers,
        "providers": providers,
        "agent": agent,
        "agents": agents,
        "permission": {"edit": "ask"},
        "permissions": [
            {"action": "read", "resource": "*.env", "effect": "deny"},
            {"action": "read", "resource": "*.env.*", "effect": "deny"},
            {"action": "read", "resource": "prd-ai-battle.env", "effect": "deny"},
        ],
        "command": commands,
        "commands": commands,
    }


def write_generated_opencode(cfg: AppConfig, repo: Path | None = None) -> Path:
    dest = generated_opencode_path(repo)
    dest.write_text(json.dumps(generate_opencode_config(cfg), indent=2) + "\n", encoding="utf-8")
    return dest
