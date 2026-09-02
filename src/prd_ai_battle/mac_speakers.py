"""Optional Mac-local speakers: HTTP OpenAI-compat and/or local CLIs.

Not the seed team. User can `config set` any of these as primary or advisor.
write_lock still binds yaml `primary.id`, never a model name or CLI binary.

CLI binaries (probe only — never installed by this repo):

- Codex CLI: ``codex`` (``codex exec``; or ``opencode auth`` / ``codex login``)
- Claude Code CLI: ``claude`` (``claude -p``; not the xixi HTTP Claude path)
- Antigravity (反重力): ``agy`` then ``antigravity``; Gemini CLI ``gemini`` fallback
- Grok: ``grok`` CLI and/or local grok2api at :8000; optional HTTP ``prd-xai``
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Optional env *names* (values never live in git).
CODEX_KEY_ENV = "PRD_CODEX_KEY"
CODEX_KEY_ENV_ALT = "OPENAI_API_KEY"
CLAUDE_CODE_KEY_ENV = "PRD_CLAUDE_CODE_KEY"
CLAUDE_CODE_KEY_ENV_ALT = "ANTHROPIC_API_KEY"
GEMINI_KEY_ENV = "PRD_GEMINI_KEY"
GEMINI_KEY_ENV_ALT = "GEMINI_API_KEY"
ANTIGRAVITY_KEY_ENV = "PRD_ANTIGRAVITY_KEY"
XAI_KEY_ENV = "PRD_XAI_KEY"
XAI_KEY_ENV_ALT = "XAI_API_KEY"

CODEX_PROVIDER_ID = "prd-codex"
CLAUDE_CODE_PROVIDER_ID = "prd-claude-code"
GEMINI_PROVIDER_ID = "prd-gemini"
ANTIGRAVITY_PROVIDER_ID = "prd-antigravity"
XAI_PROVIDER_ID = "prd-xai"

# Official xAI Chat Completions root (OpenAI-compatible). Not OpenRouter.
XAI_BASE_URL = "https://api.x.ai/v1"

CODEX_MODELS = ("gpt-5-codex", "gpt-5.1-codex")
CLAUDE_CODE_MODELS = ("claude-opus-5", "claude-sonnet-5")
GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.5-pro")
XAI_MODELS = ("grok-4", "grok-4.5")

OPTIONAL_KEY_ENVS = (
    CODEX_KEY_ENV,
    CODEX_KEY_ENV_ALT,
    CLAUDE_CODE_KEY_ENV,
    CLAUDE_CODE_KEY_ENV_ALT,
    GEMINI_KEY_ENV,
    GEMINI_KEY_ENV_ALT,
    ANTIGRAVITY_KEY_ENV,
    XAI_KEY_ENV,
    XAI_KEY_ENV_ALT,
)

OPTIONAL_PROVIDER_IDS = (
    CODEX_PROVIDER_ID,
    CLAUDE_CODE_PROVIDER_ID,
    GEMINI_PROVIDER_ID,
    ANTIGRAVITY_PROVIDER_ID,
    XAI_PROVIDER_ID,
)


@dataclass(frozen=True)
class CliPreset:
    """How to find and invoke a Mac-local CLI. Prompt is appended last."""

    name: str
    provider_id: str
    binaries: tuple[str, ...]
    exec_prefix: tuple[str, ...]
    version_args: tuple[str, ...] = ("--version",)
    default_model: str = ""
    key_envs: tuple[str, ...] = ()
    fallback_note: str = ""


@dataclass
class SpeakerSpec:
    """One optional speaker that can be HTTP, CLI, or both."""

    provider_id: str
    name: str
    models: tuple[str, ...]
    key_envs: tuple[str, ...]
    npm: str
    package: str
    default_command: str
    cli: CliPreset
    http_base_url: str = ""
    notes: str = ""
    extra_env: list[str] = field(default_factory=list)

    def overlay_entry(self) -> dict:
        env = list(self.key_envs)
        for name in self.extra_env:
            if name not in env:
                env.append(name)
        options: dict = {}
        if self.http_base_url:
            options["baseURL"] = self.http_base_url
        if self.key_envs:
            options["apiKey"] = f"{{env:{self.key_envs[0]}}}"
        models = {mid: {"name": f"{self.name} ({mid})"} for mid in self.models}
        return {
            "npm": self.npm,
            "name": self.name,
            "env": env,
            "options": options,
            "package": self.package,
            "settings": dict(options),
            "models": models,
            "optional": True,
        }


CLI_PRESETS: dict[str, CliPreset] = {
    "codex": CliPreset(
        name="codex",
        provider_id=CODEX_PROVIDER_ID,
        binaries=("codex",),
        exec_prefix=("codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only"),
        default_model=CODEX_MODELS[0],
        key_envs=(CODEX_KEY_ENV, CODEX_KEY_ENV_ALT),
        fallback_note="Subscription/CLI login: `codex login` or `opencode auth` /connect OpenAI (ChatGPT).",
    ),
    "claude": CliPreset(
        name="claude",
        provider_id=CLAUDE_CODE_PROVIDER_ID,
        binaries=("claude",),
        exec_prefix=("claude", "-p"),
        default_model=CLAUDE_CODE_MODELS[0],
        key_envs=(CLAUDE_CODE_KEY_ENV, CLAUDE_CODE_KEY_ENV_ALT),
        fallback_note="Claude Code CLI on Mac (`claude -p`). Distinct from HTTP xixi Claude.",
    ),
    "claude-code": CliPreset(
        name="claude-code",
        provider_id=CLAUDE_CODE_PROVIDER_ID,
        binaries=("claude",),
        exec_prefix=("claude", "-p"),
        default_model=CLAUDE_CODE_MODELS[0],
        key_envs=(CLAUDE_CODE_KEY_ENV, CLAUDE_CODE_KEY_ENV_ALT),
        fallback_note="Alias for the Claude Code CLI binary `claude`.",
    ),
    "antigravity": CliPreset(
        name="antigravity",
        provider_id=ANTIGRAVITY_PROVIDER_ID,
        binaries=("agy", "antigravity", "gemini"),
        exec_prefix=("-p",),
        default_model=GEMINI_MODELS[0],
        key_envs=(ANTIGRAVITY_KEY_ENV, GEMINI_KEY_ENV, GEMINI_KEY_ENV_ALT),
        fallback_note="反重力: prefer `agy` (Antigravity CLI), then `antigravity`, then Gemini CLI `gemini`.",
    ),
    "agy": CliPreset(
        name="agy",
        provider_id=ANTIGRAVITY_PROVIDER_ID,
        binaries=("agy", "antigravity", "gemini"),
        exec_prefix=("-p",),
        default_model=GEMINI_MODELS[0],
        key_envs=(ANTIGRAVITY_KEY_ENV, GEMINI_KEY_ENV, GEMINI_KEY_ENV_ALT),
        fallback_note="Antigravity CLI binary is `agy`.",
    ),
    "gemini": CliPreset(
        name="gemini",
        provider_id=GEMINI_PROVIDER_ID,
        binaries=("gemini",),
        exec_prefix=("gemini", "-p"),
        default_model=GEMINI_MODELS[0],
        key_envs=(GEMINI_KEY_ENV, GEMINI_KEY_ENV_ALT),
        fallback_note="Gemini CLI fallback when Antigravity (`agy`) is not installed.",
    ),
    "grok": CliPreset(
        name="grok",
        provider_id=XAI_PROVIDER_ID,
        binaries=("grok",),
        exec_prefix=("grok", "-p"),
        default_model=XAI_MODELS[0],
        key_envs=(XAI_KEY_ENV, XAI_KEY_ENV_ALT),
        fallback_note="Grok CLI (`grok -p`). Local HTTP tool path is grok2api at :8000 (prd-gateway).",
    ),
}

# Aliases used in yaml `command:`
CLI_PRESETS["反重力"] = CLI_PRESETS["antigravity"]


SPEAKERS: dict[str, SpeakerSpec] = {
    CODEX_PROVIDER_ID: SpeakerSpec(
        provider_id=CODEX_PROVIDER_ID,
        name="Codex / ChatGPT (optional Mac)",
        models=CODEX_MODELS,
        key_envs=(CODEX_KEY_ENV, CODEX_KEY_ENV_ALT),
        npm="@ai-sdk/openai",
        package="@opencode-ai/ai/providers/openai",
        default_command="codex",
        cli=CLI_PRESETS["codex"],
        notes="HTTP: set base_url + PRD_CODEX_KEY/OPENAI_API_KEY. CLI: `codex`. Auth: `opencode auth` or `codex login`.",
    ),
    CLAUDE_CODE_PROVIDER_ID: SpeakerSpec(
        provider_id=CLAUDE_CODE_PROVIDER_ID,
        name="Claude Code CLI (optional Mac)",
        models=CLAUDE_CODE_MODELS,
        key_envs=(CLAUDE_CODE_KEY_ENV, CLAUDE_CODE_KEY_ENV_ALT),
        npm="@ai-sdk/anthropic",
        package="@opencode-ai/ai/providers/anthropic",
        default_command="claude",
        cli=CLI_PRESETS["claude"],
        notes="Local `claude` CLI, not the seed xixi HTTP Claude pair.",
    ),
    ANTIGRAVITY_PROVIDER_ID: SpeakerSpec(
        provider_id=ANTIGRAVITY_PROVIDER_ID,
        name="Antigravity / 反重力 (optional Mac)",
        models=GEMINI_MODELS,
        key_envs=(ANTIGRAVITY_KEY_ENV, GEMINI_KEY_ENV, GEMINI_KEY_ENV_ALT),
        npm="@ai-sdk/google",
        package="@opencode-ai/ai/providers/google",
        default_command="antigravity",
        cli=CLI_PRESETS["antigravity"],
        notes="Prefer `agy` (Antigravity CLI). Fall back to `antigravity`, then Gemini CLI `gemini`.",
    ),
    GEMINI_PROVIDER_ID: SpeakerSpec(
        provider_id=GEMINI_PROVIDER_ID,
        name="Gemini CLI (optional Mac fallback)",
        models=GEMINI_MODELS,
        key_envs=(GEMINI_KEY_ENV, GEMINI_KEY_ENV_ALT),
        npm="@ai-sdk/google",
        package="@opencode-ai/ai/providers/google",
        default_command="gemini",
        cli=CLI_PRESETS["gemini"],
        notes="Gemini CLI when Antigravity is not installed. HTTP: set base_url + PRD_GEMINI_KEY/GEMINI_API_KEY.",
    ),
    XAI_PROVIDER_ID: SpeakerSpec(
        provider_id=XAI_PROVIDER_ID,
        name="xAI Grok HTTP (optional)",
        models=XAI_MODELS,
        key_envs=(XAI_KEY_ENV, XAI_KEY_ENV_ALT),
        npm="@ai-sdk/openai-compatible",
        package="@opencode-ai/ai/providers/xai",
        default_command="grok",
        cli=CLI_PRESETS["grok"],
        http_base_url=XAI_BASE_URL,
        notes="Official xAI API. Do not duplicate OpenRouter. Local tool: grok2api prd-gateway :8000 or `grok` CLI.",
    ),
}


def preset_for_command(command: str) -> CliPreset | None:
    token = (command or "").strip().split()[0].lower() if command else ""
    if token in CLI_PRESETS:
        return CLI_PRESETS[token]
    # Full path: /usr/local/bin/codex
    base = token.rsplit("/", 1)[-1]
    return CLI_PRESETS.get(base)


def provider_id_for_command(command: str) -> str | None:
    preset = preset_for_command(command)
    return preset.provider_id if preset else None


def infer_cli_command(model: str, command: str = "") -> str:
    if command and command.strip():
        return command.strip()
    mid = (model or "").lower()
    if "codex" in mid:
        return "codex"
    if "antigravity" in mid or "反重力" in mid:
        return "antigravity"
    if "gemini" in mid:
        return "gemini"
    if "grok" in mid:
        return "grok"
    if "claude" in mid:
        return "claude"
    return command.strip()


def optional_overlay_providers() -> dict[str, dict]:
    """Always-present catalog so OpenCode can select these speakers."""
    return {pid: spec.overlay_entry() for pid, spec in SPEAKERS.items()}


def first_set_env(names: tuple[str, ...] | list[str]) -> tuple[str, str]:
    """Return (env_name, value) for the first name that is set and non-empty."""
    import os

    for name in names:
        found = os.environ.get(name, "")
        if found:
            return name, found
    return (names[0] if names else "", "")
