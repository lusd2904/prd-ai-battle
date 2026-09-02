"""Thin subprocess adapter for Mac-local CLIs (Codex, Claude Code, Antigravity, Gemini, Grok).

Does not install binaries. Missing CLI → structured `missing` result.
Stdout is the assistant message (chat-completions-shaped for ping).
Stderr is captured and redacted. Hung processes are killed on timeout.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from prd_ai_battle.mac_speakers import CliPreset, infer_cli_command, preset_for_command
from prd_ai_battle.redact import redact

WhichFn = Callable[[str], str | None]

CLI_PROBE_TIMEOUT_S = 8.0
CLI_EXEC_TIMEOUT_S = 120.0
CLI_KILL_GRACE_S = 2.0


@dataclass
class CliProbe:
    command: str
    found: bool
    binary: str = ""
    path: str = ""
    tried: list[str] = field(default_factory=list)
    fallback_used: str = ""
    detail: str = ""
    version: str = ""
    preset: str = ""
    provider_id: str = ""

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "found": self.found,
            "binary": self.binary,
            "path": self.path,
            "tried": list(self.tried),
            "fallback_used": self.fallback_used,
            "detail": self.detail,
            "version": self.version,
            "preset": self.preset,
            "provider_id": self.provider_id,
            "cli": "present" if self.found else "missing",
        }


def _which(name: str, which: WhichFn | None = None) -> str | None:
    finder = which or shutil.which
    return finder(name)


def resolve_preset(command: str) -> CliPreset | None:
    return preset_for_command(command)


def candidate_binaries(command: str) -> list[str]:
    preset = preset_for_command(command)
    if preset:
        return list(preset.binaries)
    token = (command or "").strip()
    if not token:
        return []
    first = token.split()[0]
    return [first]


def probe_cli(
    command: str,
    *,
    which: WhichFn | None = None,
    run_version: bool = False,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> CliProbe:
    """Locate a CLI binary. Never raises if the tool is missing."""
    wanted = (command or "").strip()
    tried = candidate_binaries(wanted)
    preset = preset_for_command(wanted)
    result = CliProbe(
        command=wanted,
        found=False,
        tried=tried,
        preset=preset.name if preset else "",
        provider_id=preset.provider_id if preset else "",
        detail=preset.fallback_note if preset else "",
    )
    if not tried:
        result.detail = "no CLI command configured"
        return result

    preferred = tried[0]
    for name in tried:
        path = _which(name, which)
        if not path:
            continue
        result.found = True
        result.binary = name
        result.path = path
        if name != preferred:
            result.fallback_used = name
            result.detail = f"using fallback binary {name!r} (preferred {preferred!r} missing)"
        else:
            result.detail = f"found {name} at {path}"
        if run_version:
            result.version = _version_text(path, preset, runner=runner)
            if result.version:
                result.detail = f"{result.detail}; {result.version}"
        return result

    result.detail = f"missing CLI ({', '.join(tried)})"
    return result


def _run_captured(
    argv: list[str],
    *,
    timeout: float,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> subprocess.CompletedProcess:
    """Run argv, kill on timeout, return completed process. Never leaks hung children."""
    if runner is not None:
        return runner(argv, capture_output=True, text=True, timeout=timeout, check=False)
    proc = subprocess.Popen(  # noqa: S603 — user-configured local CLI only
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=CLI_KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            proc.terminate()
            stdout, stderr = "", ""
        raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr) from None
    return subprocess.CompletedProcess(argv, proc.returncode or 0, stdout, stderr)


def _version_text(
    path: str,
    preset: CliPreset | None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> str:
    args = list(preset.version_args) if preset else ["--version"]
    try:
        proc = _run_captured([path, *args], timeout=CLI_PROBE_TIMEOUT_S, runner=runner)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return redact(str(exc))[:200]
    blob = redact((proc.stdout or proc.stderr or "").strip())
    if blob:
        return blob.splitlines()[0][:200]
    # Cheap fallback when --version is unrecognized.
    try:
        proc = _run_captured([path, "--help"], timeout=CLI_PROBE_TIMEOUT_S, runner=runner)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    help_blob = redact((proc.stdout or proc.stderr or "").strip())
    return help_blob.splitlines()[0][:200] if help_blob else ""


def exec_argv(command: str, prompt: str, *, binary_path: str = "", binary_name: str = "") -> list[str]:
    """Build argv for a one-shot prompt. Prompt is the last argument."""
    preset = preset_for_command(command)
    tokens = (command or "").split()
    if preset and (len(tokens) <= 1):
        prefix = list(preset.exec_prefix)
        if prefix and not prefix[0].startswith("-"):
            resolved = binary_path or binary_name or prefix[0]
            prefix[0] = resolved
        else:
            resolved = binary_path or binary_name or (preset.binaries[0] if preset.binaries else "cli")
            prefix = [resolved, *prefix]
        return [*prefix, prompt]
    if not tokens:
        raise ValueError("empty CLI command")
    tokens[0] = binary_path or binary_name or tokens[0]
    return [*tokens, prompt]


def run_cli_prompt(
    command: str,
    prompt: str,
    *,
    which: WhichFn | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    timeout: float = CLI_EXEC_TIMEOUT_S,
) -> str:
    probe = probe_cli(command, which=which)
    if not probe.found:
        raise FileNotFoundError(probe.detail or f"missing CLI {command!r}")
    argv = exec_argv(command, prompt, binary_path=probe.path, binary_name=probe.binary)
    try:
        proc = _run_captured(argv, timeout=timeout, runner=runner)
    except subprocess.TimeoutExpired as exc:
        err = redact((exc.stderr or "") if isinstance(exc.stderr, str) else "")
        raise RuntimeError(
            f"{probe.binary} timed out after {timeout}s and was killed"
            + (f": {err[:200]}" if err else "")
        ) from exc
    if proc.returncode != 0:
        err = redact((proc.stderr or proc.stdout or f"exit {proc.returncode}").strip())
        raise RuntimeError(f"{probe.binary} failed: {err[:400]}")
    return redact((proc.stdout or "").strip())


def messages_to_prompt(messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role") or "user"
        content = msg.get("content") or ""
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def chat_completions_shape(text: str, model: str) -> dict[str, Any]:
    """Minimal OpenAI-compatible completion body (for ping / tests)."""
    return {
        "id": "cli-local",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }


def command_for_model(model) -> str:
    transport = getattr(model, "transport", "http") or "http"
    if str(transport).lower() != "cli":
        return ""
    return infer_cli_command(getattr(model, "model", ""), getattr(model, "command", "") or "")
