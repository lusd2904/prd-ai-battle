"""YAML config + env-var interpolation for OpenAI-compatible models."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def expand_env(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        found = os.environ.get(name)
        if found is not None:
            return found
        return default if default is not None else match.group(0)

    return ENV_PATTERN.sub(repl, value)


class ModelConfig(BaseModel):
    id: str
    base_url: str
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.4

    @field_validator("base_url")
    @classmethod
    def _expand_url(cls, value: str) -> str:
        return expand_env(value).rstrip("/")

    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


class AppConfig(BaseModel):
    workspace: str = ".prd-ai-battle"
    offline: bool = False
    primary: ModelConfig
    advisors: list[ModelConfig] = Field(min_length=1)

    @field_validator("advisors")
    @classmethod
    def _unique_ids(cls, advisors: list[ModelConfig], info):
        return advisors

    def all_models(self) -> list[ModelConfig]:
        return [self.primary, *self.advisors]

    def model_ids(self) -> list[str]:
        return [m.id for m in self.all_models()]

    def validate_ids(self) -> None:
        ids = self.model_ids()
        if len(ids) != len(set(ids)):
            raise ValueError("Model ids must be unique across primary + advisors")
        if any(a.id == self.primary.id for a in self.advisors):
            raise ValueError("Advisor id cannot reuse the primary id")


def default_offline_config(workspace: str = ".prd-ai-battle") -> AppConfig:
    cfg = AppConfig(
        workspace=workspace,
        offline=True,
        primary=ModelConfig(
            id="primary",
            base_url="http://127.0.0.1:0/v1",
            model="mock-primary",
            api_key_env="NONE",
            temperature=0.2,
        ),
        advisors=[
            ModelConfig(
                id="advisor-a",
                base_url="http://127.0.0.1:0/v1",
                model="mock-advisor-a",
                api_key_env="NONE",
                temperature=0.5,
            ),
            ModelConfig(
                id="advisor-b",
                base_url="http://127.0.0.1:0/v1",
                model="mock-advisor-b",
                api_key_env="NONE",
                temperature=0.5,
            ),
        ],
    )
    cfg.validate_ids()
    return cfg


def load_config(path: Path | None, *, offline: bool | None = None) -> AppConfig:
    if path is None:
        cfg = default_offline_config()
    else:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cfg = AppConfig.model_validate(raw)
        cfg.validate_ids()
    if offline is not None:
        cfg.offline = offline
    return cfg


def find_config(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit
    for candidate in (Path("prd-ai-battle.yaml"), Path("config.yaml")):
        if candidate.is_file():
            return candidate
    return None
