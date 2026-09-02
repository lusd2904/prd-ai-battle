"""YAML + env config. No vendor or tunnel hostnames are hardcoded.

Default traffic goes to the user's local multi-key gateway. Any other
endpoint (including an optional external tunnel) is supplied only via
`gateway.base_url` / `PRD_AI_GATEWAY_URL` in the operator's own config.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, field_validator

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")

# Optional local backup gateway. Primary traffic uses per-model base_url in
# config.example.yaml / opencode.json (keys only via env).
LOCAL_GATEWAY_URL = "http://127.0.0.1:8000/v1"
GATEWAY_URL_ENV = "PRD_AI_GATEWAY_URL"
GATEWAY_KEY_ENV = "PRD_AI_GATEWAY_KEY"

# Product endpoints — keys never stored in git, only env var *names*.
XIXI_BASE_URL = "https://xixiapi.io/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
XIXI_KEY_ENV = "PRD_SFP_XIXI_KEY"
OPENROUTER_KEY_ENV = "PRD_SFP_OPENROUTER_KEY"
PRIMARY_MODEL = "claude-opus-5"
ADVISOR_SONNET_MODEL = "claude-sonnet-5"
ADVISOR_GROK_MODEL = "x-ai/grok-4.6"


class ConfigError(ValueError):
    pass


def expand_env(value: str) -> str:
    """Expand ${VAR} and ${VAR:-default}. Unset vars without a default become ''."""

    def repl(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        found = os.environ.get(name)
        if found is not None:
            return found
        return default if default is not None else ""

    return ENV_PATTERN.sub(repl, value)


def display_gateway_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.netloc:
        return parsed.netloc
    return base_url or "(unset)"


class GatewayConfig(BaseModel):
    """Shared OpenAI-compatible gateway. All models inherit unless overridden."""

    base_url: str = f"${{{GATEWAY_URL_ENV}:-{LOCAL_GATEWAY_URL}}}"
    api_key: str = f"${{{GATEWAY_KEY_ENV}:-}}"

    def resolved_base_url(self) -> str:
        return expand_env(self.base_url).rstrip("/")

    def resolved_key(self) -> str:
        return expand_env(self.api_key)


class ModelConfig(BaseModel):
    id: str
    model: str
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    temperature: float = 0.4

    @field_validator("base_url", "api_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip() if value else ""

    def resolved_base_url(self, gateway: GatewayConfig | None = None) -> str:
        raw = self.base_url or (gateway.base_url if gateway is not None else "")
        url = expand_env(raw).rstrip("/")
        if not url and gateway is not None:
            url = gateway.resolved_base_url()
        return url

    def resolved_key(self, gateway: GatewayConfig | None = None) -> str:
        if self.api_key_env:
            found = os.environ.get(self.api_key_env, "")
            if found:
                return found
        if self.api_key:
            expanded = expand_env(self.api_key)
            if expanded:
                return expanded
        if gateway is not None:
            return gateway.resolved_key()
        return ""

    def chat_completions_url(self, gateway: GatewayConfig | None = None) -> str:
        root = self.resolved_base_url(gateway)
        if not root:
            raise ConfigError(
                f"Model {self.id!r} has an empty base_url. "
                f"Set gateway.base_url or {GATEWAY_URL_ENV} to your local multi-key gateway."
            )
        if root.endswith("/chat/completions"):
            return root
        return f"{root}/chat/completions"


class AppConfig(BaseModel):
    workspace: str = ".prd-ai-battle"
    offline: bool = False
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    primary: ModelConfig
    advisors: list[ModelConfig] = Field(min_length=1)

    def all_models(self) -> list[ModelConfig]:
        return [self.primary, *self.advisors]

    def model_ids(self) -> list[str]:
        return [m.id for m in self.all_models()]

    def validate_ids(self) -> None:
        ids = self.model_ids()
        if len(ids) != len(set(ids)):
            raise ConfigError("Model ids must be unique across primary + advisors")
        if any(a.id == self.primary.id for a in self.advisors):
            raise ConfigError("Advisor id cannot reuse the primary id")

    def resolve(self) -> AppConfig:
        """Bake gateway defaults into each model. Does not persist secrets to disk."""
        self.validate_ids()
        g_url = self.gateway.resolved_base_url()
        if not g_url:
            raise ConfigError(
                f"gateway.base_url is empty. Set {GATEWAY_URL_ENV} or gateway.base_url "
                "to your local multi-key gateway (loopback)."
            )
        for model in self.all_models():
            if not model.base_url:
                model.base_url = g_url
            else:
                model.base_url = expand_env(model.base_url).rstrip("/")
            if not model.base_url:
                raise ConfigError(f"Model {model.id!r} base_url is empty after env expansion")
            if not model.api_key and not model.api_key_env:
                model.api_key = self.gateway.api_key
        return self

    def gateway_host(self) -> str:
        return display_gateway_host(self.primary.resolved_base_url(self.gateway))


def default_offline_config(workspace: str = ".prd-ai-battle") -> AppConfig:
    cfg = AppConfig(
        workspace=workspace,
        offline=True,
        gateway=GatewayConfig(base_url=LOCAL_GATEWAY_URL, api_key=""),
        primary=ModelConfig(id="primary", model="mock-primary", temperature=0.2),
        advisors=[
            ModelConfig(id="advisor-a", model="mock-advisor-a", temperature=0.5),
            ModelConfig(id="advisor-b", model="mock-advisor-b", temperature=0.5),
        ],
    )
    return cfg.resolve()


def default_live_config(workspace: str = ".prd-ai-battle") -> AppConfig:
    """Live product models. Keys come from env; never from this file's values."""
    cfg = AppConfig(
        workspace=workspace,
        offline=False,
        gateway=GatewayConfig(),
        primary=ModelConfig(
            id="primary",
            model=PRIMARY_MODEL,
            base_url=XIXI_BASE_URL,
            api_key_env=XIXI_KEY_ENV,
            temperature=0.3,
        ),
        advisors=[
            ModelConfig(
                id="advisor-sonnet",
                model=ADVISOR_SONNET_MODEL,
                base_url=XIXI_BASE_URL,
                api_key_env=XIXI_KEY_ENV,
                temperature=0.5,
            ),
            ModelConfig(
                id="advisor-grok",
                model=ADVISOR_GROK_MODEL,
                base_url=OPENROUTER_BASE_URL,
                api_key_env=OPENROUTER_KEY_ENV,
                temperature=0.5,
            ),
        ],
    )
    return cfg.resolve()


def load_config(path, *, offline: bool | None = None) -> AppConfig:
    from pathlib import Path

    if path is None:
        cfg = default_offline_config() if offline is not False else default_live_config()
    else:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        cfg = AppConfig.model_validate(raw).resolve()
    if offline is not None:
        cfg.offline = offline
    return cfg


def find_config(explicit=None):
    from pathlib import Path

    if explicit is not None:
        return explicit
    for candidate in (Path("prd-ai-battle.yaml"), Path("config.yaml")):
        if candidate.is_file():
            return candidate
    return None


def doctor_report(cfg: AppConfig) -> dict:
    """Resolved gateway view with the key redacted."""
    models = []
    for model in cfg.all_models():
        key = model.resolved_key(cfg.gateway)
        models.append(
            {
                "id": model.id,
                "model": model.model,
                "base_url": model.resolved_base_url(cfg.gateway),
                "api_key": "set" if key else "missing",
            }
        )
    return {
        "offline": cfg.offline,
        "gateway": {
            "base_url": cfg.gateway.resolved_base_url(),
            "host": cfg.gateway_host(),
            "api_key": "set" if cfg.gateway.resolved_key() else "missing",
            "url_env": GATEWAY_URL_ENV,
            "key_env": GATEWAY_KEY_ENV,
        },
        "models": models,
    }
