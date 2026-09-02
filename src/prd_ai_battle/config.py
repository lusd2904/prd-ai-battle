"""YAML + env config. Finance-platform models in config.example.yaml are seed only.

Runtime always prefers the gitignored local Mac yaml (`prd-ai-battle.yaml`).
API key *values* are stored in gitignored `prd-ai-battle.env` and loaded into
the process environment on launch — never committed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, PrivateAttr, field_validator

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")

LOCAL_YAML_NAME = "prd-ai-battle.yaml"
LOCAL_ENV_NAME = "prd-ai-battle.env"
GENERATED_OPENCODE_NAME = "prd-ai-battle.opencode.json"
SEED_YAML_NAME = "config.example.yaml"

# Backup gateway default used only when yaml omits gateway.base_url.
# grok2api on loopback — speaks these model ids, NOT Claude.
LOCAL_GATEWAY_URL = "http://127.0.0.1:8000/v1"
GATEWAY_URL_ENV = "PRD_AI_GATEWAY_URL"
GATEWAY_KEY_ENV = "PRD_AI_GATEWAY_KEY"
GATEWAY_PROVIDER_ID = "prd-gateway"
GATEWAY_BACKUP_MODELS = ("grok-4.5", "grok-composer-2.5-fast")
GATEWAY_BACKUP_PING_MODEL = "grok-4.5"

# Seed env *names* (values never live in git). Mirrored in config.example.yaml
# and committed prd-ai-battle.env.example (copy to gitignored prd-ai-battle.env).
XIXI_KEY_ENV = "PRD_SFP_XIXI_KEY"
OPENROUTER_KEY_ENV = "PRD_SFP_OPENROUTER_KEY"
SEED_KEY_ENVS = (XIXI_KEY_ENV, OPENROUTER_KEY_ENV, GATEWAY_KEY_ENV)


class ConfigError(ValueError):
    pass


def expand_env(
    value: str,
    overlay: dict[str, str] | None = None,
    *,
    process_env: bool = True,
) -> str:
    """Expand ${VAR} and ${VAR:-default}. Unset vars without a default become ''."""

    extra = overlay or {}

    def repl(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in extra:
            return extra[name]
        if process_env:
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
    # Project-scoped bake: HTTP/CLI still call resolved_key(); process env must not leak.
    _baked: bool = PrivateAttr(default=False)
    _baked_key: str = PrivateAttr(default="")

    def resolved_base_url(self) -> str:
        return expand_env(self.base_url).rstrip("/")

    def resolved_key(self) -> str:
        if self._baked:
            return self._baked_key
        return expand_env(self.api_key)


class ModelConfig(BaseModel):
    id: str
    model: str
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    temperature: float = 0.4
    transport: str = "http"
    command: str = ""
    # Set only by bake_project_secrets — never written to yaml.
    _baked: bool = PrivateAttr(default=False)
    _baked_key: str = PrivateAttr(default="")

    @field_validator("base_url", "api_key", "command")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip() if value else ""

    @field_validator("transport")
    @classmethod
    def _transport(cls, value: str) -> str:
        text = (value or "http").strip().lower() or "http"
        if text not in {"http", "cli"}:
            raise ValueError("transport must be 'http' or 'cli'")
        return text

    def is_cli(self) -> bool:
        return self.transport == "cli"

    def resolved_base_url(self, gateway: GatewayConfig | None = None) -> str:
        if self.is_cli() and not self.base_url:
            return ""
        raw = self.base_url or (gateway.base_url if gateway is not None else "")
        url = expand_env(raw).rstrip("/")
        if not url and gateway is not None and not self.is_cli():
            url = gateway.resolved_base_url()
        return url

    def resolved_key(self, gateway: GatewayConfig | None = None) -> str:
        if self._baked:
            return self._baked_key
        if self.api_key_env:
            found = os.environ.get(self.api_key_env, "")
            if found:
                return found
        if self.api_key:
            expanded = expand_env(self.api_key)
            if expanded:
                return expanded
        if self.is_cli():
            return ""
        if gateway is not None:
            return gateway.resolved_key()
        return ""

    def chat_completions_url(self, gateway: GatewayConfig | None = None) -> str:
        if self.is_cli():
            raise ConfigError(
                f"Model {self.id!r} uses transport=cli ({self.command or 'no command'}). "
                "HTTP chat/completions is not used for CLI speakers."
            )
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

    def advisor_by_id(self, advisor_id: str) -> ModelConfig:
        for advisor in self.advisors:
            if advisor.id == advisor_id:
                return advisor
        raise ConfigError(f"No advisor with id {advisor_id!r}")

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
            if model.is_cli():
                if model.base_url:
                    model.base_url = expand_env(model.base_url).rstrip("/")
                if not model.command:
                    from prd_ai_battle.mac_speakers import infer_cli_command

                    model.command = infer_cli_command(model.model, model.command)
                continue
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


def repo_paths(start: Path | None = None) -> Path:
    here = start or Path.cwd()
    candidates = [here, *here.parents]
    for path in candidates:
        if (path / SEED_YAML_NAME).is_file() or (path / "opencode.json").is_file():
            return path
    return here


def seed_yaml_path(repo: Path | None = None) -> Path:
    root = repo or repo_paths()
    direct = root / SEED_YAML_NAME
    if direct.is_file():
        return direct
    pkg = Path(__file__).resolve().parents[2] / SEED_YAML_NAME
    if pkg.is_file():
        return pkg
    cwd = Path.cwd() / SEED_YAML_NAME
    if cwd.is_file():
        return cwd
    raise ConfigError(f"Seed file {SEED_YAML_NAME} not found")


def local_yaml_path(repo: Path | None = None) -> Path:
    return (repo or repo_paths()) / LOCAL_YAML_NAME


def local_env_path(repo: Path | None = None) -> Path:
    return (repo or repo_paths()) / LOCAL_ENV_NAME


def generated_opencode_path(repo: Path | None = None) -> Path:
    return (repo or repo_paths()) / GENERATED_OPENCODE_NAME


def read_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=value pairs. Does not mutate os.environ (project isolation)."""
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip("'").strip('"')
        if not name:
            continue
        loaded[name] = value
    return loaded


def load_env_file(path: Path) -> dict[str, str]:
    """Load KEY=value pairs into os.environ if the key is not already set.

    Existing process env wins (the user may have exported a newer key).
    Board projects must use read_env_file + bake_project_secrets instead.
    """
    loaded = read_env_file(path)
    for name, value in loaded.items():
        if name not in os.environ:
            os.environ[name] = value
    return loaded


def bake_project_secrets(cfg: AppConfig, overlay: dict[str, str]) -> AppConfig:
    """Seal this project's env-file keys onto in-memory models.

    HTTP/CLI still call resolved_key(); they must not see another project's
    process env. Overlay only — process env is ignored so keys cannot leak.
    Never write baked values back to yaml.
    """
    def only(value: str) -> str:
        return expand_env(value, overlay=overlay, process_env=False)

    gw_key = overlay.get(GATEWAY_KEY_ENV, "") or only(cfg.gateway.api_key)
    cfg.gateway._baked = True
    cfg.gateway._baked_key = gw_key
    baked_gw_url = only(cfg.gateway.base_url).rstrip("/")
    if baked_gw_url:
        cfg.gateway.base_url = baked_gw_url

    for model in cfg.all_models():
        key = ""
        if model.api_key_env and model.api_key_env in overlay:
            key = overlay[model.api_key_env]
        if not key and model.api_key:
            key = only(model.api_key)
        if not key and not model.is_cli():
            key = gw_key
        model._baked = True
        model._baked_key = key
        if model.base_url:
            model.base_url = only(model.base_url).rstrip("/")
    return cfg


def infer_project_root(workspace: Path) -> Path:
    """Directory that holds this project's yaml + env (workspace or its parent)."""
    ws = Path(workspace)
    if (ws / LOCAL_YAML_NAME).is_file() or (ws / LOCAL_ENV_NAME).is_file():
        return ws
    parent = ws.parent
    if (parent / LOCAL_YAML_NAME).is_file() or (parent / LOCAL_ENV_NAME).is_file():
        return parent
    return ws


def load_project_config(
    root: Path,
    *,
    offline: bool | None = None,
    workspace: Path | None = None,
) -> AppConfig:
    """Load yaml + this project's env file. Secrets stay on the in-memory config."""
    root = Path(root)
    overlay = read_env_file(root / LOCAL_ENV_NAME)
    yaml_path = root / LOCAL_YAML_NAME
    ws = Path(workspace) if workspace is not None else root / ".prd-ai-battle"
    if yaml_path.is_file():
        cfg = load_config(yaml_path, offline=offline)
    elif offline is False:
        dest = ensure_local_config(root)
        cfg = load_config(dest, offline=offline)
    else:
        cfg = default_offline_config(str(ws))
    if not Path(cfg.workspace).is_absolute():
        cfg.workspace = str((root / cfg.workspace).resolve() if workspace is None else Path(workspace).resolve())
    else:
        cfg.workspace = str(Path(cfg.workspace).resolve())
    if workspace is not None:
        cfg.workspace = str(Path(workspace).resolve())
    return bake_project_secrets(cfg, overlay)


def write_env_file(path: Path, updates: dict[str, str]) -> None:
    """Merge key values into the gitignored env file. Never called on seed files."""
    existing: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            existing[name.strip()] = value.strip()
    existing.update({k: v for k, v in updates.items() if k and v})
    lines = [
        "# gitignored local keys — written by `prd-ai-battle config`. Do not commit.",
        "# Launch loads these into the process environment if the var is unset.",
    ]
    for name in sorted(existing):
        lines.append(f"{name}={existing[name]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _model_yaml(model: ModelConfig, gateway: GatewayConfig) -> dict:
    url = model.resolved_base_url(gateway) or model.base_url
    block: dict = {
        "id": model.id,
        "model": model.model,
        "temperature": model.temperature,
    }
    if model.is_cli():
        block["transport"] = "cli"
        if model.command:
            block["command"] = model.command
        if url:
            block["base_url"] = url
    else:
        block["base_url"] = url
    if model.api_key_env:
        block["api_key_env"] = model.api_key_env
        block["api_key"] = f"${{{model.api_key_env}:-}}"
    else:
        block["api_key"] = ""
    return block


def local_yaml_dict(cfg: AppConfig) -> dict:
    """Serialize config for the gitignored yaml. No raw key values."""
    return {
        "workspace": cfg.workspace,
        "offline": cfg.offline,
        "gateway": {
            "base_url": cfg.gateway.base_url,
            "api_key": f"${{{GATEWAY_KEY_ENV}:-}}",
        },
        "primary": _model_yaml(cfg.primary, cfg.gateway),
        "advisors": [_model_yaml(a, cfg.gateway) for a in cfg.advisors],
    }


def save_local_config(
    cfg: AppConfig,
    *,
    repo: Path | None = None,
    keys: dict[str, str] | None = None,
) -> Path:
    """Write gitignored yaml (models/urls/env names) and optional env key file."""
    root = repo or repo_paths()
    dest = local_yaml_path(root)
    dest.write_text(
        "# gitignored local Mac config. Seed is config.example.yaml.\n"
        "# Keys are NOT stored here — see prd-ai-battle.env / process env.\n\n"
        + yaml.safe_dump(local_yaml_dict(cfg), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    if keys:
        write_env_file(local_env_path(root), keys)
        load_env_file(local_env_path(root))
    return dest


def ensure_local_config(repo: Path | None = None, *, force: bool = False) -> Path:
    """Copy the committed seed yaml to the gitignored local yaml if missing."""
    root = repo or repo_paths()
    dest = local_yaml_path(root)
    if dest.is_file() and not force:
        return dest
    src = seed_yaml_path(root)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


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
    """Load the committed seed yaml (not a locked-in Python model list)."""
    cfg = load_config(seed_yaml_path(), offline=False)
    cfg.workspace = workspace
    return cfg


def load_config(path, *, offline: bool | None = None) -> AppConfig:
    if path is None:
        cfg = default_offline_config() if offline is not False else default_live_config()
    else:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        cfg = AppConfig.model_validate(raw).resolve()
    if offline is not None:
        cfg.offline = offline
    return cfg


def find_config(explicit=None, *, repo: Path | None = None):
    if explicit is not None:
        return explicit
    root = repo or repo_paths()
    for candidate in (
        root / LOCAL_YAML_NAME,
        Path.cwd() / LOCAL_YAML_NAME,
        Path.cwd() / "config.yaml",
        root / "config.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_runtime_config(
    *,
    explicit=None,
    repo: Path | None = None,
    offline: bool | None = None,
    ensure_local: bool = True,
) -> AppConfig:
    """Load last-saved local yaml (creating it from seed on first run)."""
    root = repo or repo_paths()
    load_env_file(local_env_path(root))
    path = find_config(explicit, repo=root)
    if path is None and ensure_local and offline is not True:
        path = ensure_local_config(root)
    return load_config(path, offline=offline)


def _apply_cli_defaults(model: ModelConfig) -> None:
    """Fill command / model / key-env when the user points a speaker at a Mac CLI."""
    from prd_ai_battle.mac_speakers import infer_cli_command, preset_for_command

    if not model.is_cli():
        return
    model.command = infer_cli_command(model.model, model.command)
    preset = preset_for_command(model.command)
    if not preset:
        return
    if not model.model or model.model in {"custom-advisor", "mock-primary"}:
        model.model = preset.default_model or model.model
    if not model.api_key_env and preset.key_envs:
        model.api_key_env = preset.key_envs[0]


def apply_user_set(
    cfg: AppConfig,
    *,
    primary_id: str | None = None,
    primary_model: str | None = None,
    primary_base_url: str | None = None,
    primary_key_env: str | None = None,
    primary_key: str | None = None,
    primary_transport: str | None = None,
    primary_command: str | None = None,
    advisor_id: str | None = None,
    advisor_model: str | None = None,
    advisor_base_url: str | None = None,
    advisor_key_env: str | None = None,
    advisor_key: str | None = None,
    advisor_transport: str | None = None,
    advisor_command: str | None = None,
    add_advisor: bool = False,
) -> dict[str, str]:
    """Mutate cfg from user flags. Returns key-env → secret map to persist in .env."""
    keys: dict[str, str] = {}
    if primary_id:
        cfg.primary.id = primary_id
    if primary_model:
        cfg.primary.model = primary_model
    if primary_base_url:
        cfg.primary.base_url = primary_base_url
    if primary_key_env:
        cfg.primary.api_key_env = primary_key_env
    if primary_transport:
        cfg.primary.transport = primary_transport
    if primary_command:
        cfg.primary.command = primary_command
        if not primary_transport:
            cfg.primary.transport = "cli"
    if primary_key:
        env_name = cfg.primary.api_key_env or "PRD_AI_PRIMARY_KEY"
        cfg.primary.api_key_env = env_name
        keys[env_name] = primary_key
        cfg.primary.api_key = f"${{{env_name}:-}}"
    _apply_cli_defaults(cfg.primary)
    if advisor_id:
        if add_advisor:
            cfg.advisors.append(
                ModelConfig(
                    id=advisor_id,
                    model=advisor_model or "custom-advisor",
                    base_url=advisor_base_url or "",
                    api_key_env=advisor_key_env or "",
                    transport=advisor_transport or "http",
                    command=advisor_command or "",
                )
            )
        target = cfg.advisor_by_id(advisor_id)
        if advisor_model:
            target.model = advisor_model
        if advisor_base_url:
            target.base_url = advisor_base_url
        if advisor_key_env:
            target.api_key_env = advisor_key_env
        if advisor_transport:
            target.transport = advisor_transport
        if advisor_command:
            target.command = advisor_command
            if not advisor_transport:
                target.transport = "cli"
        if advisor_key:
            env_name = target.api_key_env or f"PRD_AI_{advisor_id.upper().replace('-', '_')}_KEY"
            target.api_key_env = env_name
            keys[env_name] = advisor_key
            target.api_key = f"${{{env_name}:-}}"
        _apply_cli_defaults(target)
    cfg.resolve()
    return keys


def is_backup_gateway_url(url: str, gateway_url: str) -> bool:
    """True when url is the optional grok2api backup (not xixi / OpenRouter)."""
    return (url or "").rstrip("/") == (gateway_url or "").rstrip("/")


def doctor_report(cfg: AppConfig) -> dict:
    """Resolved gateway view with the key redacted."""
    from prd_ai_battle.cli_transport import probe_cli
    from prd_ai_battle.mac_speakers import SPEAKERS, first_set_env

    models = []
    for model in cfg.all_models():
        key = model.resolved_key(cfg.gateway)
        row = {
            "id": model.id,
            "model": model.model,
            "base_url": model.resolved_base_url(cfg.gateway),
            "api_key": "set" if key else "missing",
            "api_key_env": model.api_key_env or "",
            "transport": model.transport,
            "command": model.command,
        }
        if model.is_cli():
            row["cli"] = probe_cli(model.command or model.model).as_public_dict()
        models.append(row)
    optional = []
    for spec in SPEAKERS.values():
        env_name, env_val = first_set_env(spec.key_envs)
        cli = probe_cli(spec.default_command)
        optional.append(
            {
                "provider_id": spec.provider_id,
                "name": spec.name,
                "models": list(spec.models),
                "command": spec.default_command,
                "transport": ["http", "cli"],
                "api_key": "set" if env_val else "missing",
                "api_key_env": env_name,
                "cli": cli.as_public_dict(),
                "notes": spec.notes,
            }
        )
    return {
        "offline": cfg.offline,
        "source": "local-yaml-or-seed",
        "primary_id": cfg.primary.id,
        "write_lock_binds": "yaml primary.id (never a model name or CLI binary)",
        "gateway": {
            "base_url": cfg.gateway.resolved_base_url(),
            "host": cfg.gateway_host(),
            "api_key": "set" if cfg.gateway.resolved_key() else "missing",
            "url_env": GATEWAY_URL_ENV,
            "key_env": GATEWAY_KEY_ENV,
            "provider_id": GATEWAY_PROVIDER_ID,
            "models": list(GATEWAY_BACKUP_MODELS),
            "optional": True,
            "speaks": "grok2api (grok-4.5 / grok-composer-2.5-fast, not Claude)",
            "local_tool": "Mac grok2api at :8000 or Grok CLI (`grok`)",
        },
        "models": models,
        "optional_mac_speakers": optional,
        "hint": "prd-ai-battle ping  # HTTP + CLI probe; keys redacted; missing CLI is not a crash",
    }
