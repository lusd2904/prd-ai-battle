"""Thin subprocess adapter for Mac-local CLIs (Codex, Claude Code, Antigravity, Gemini, Grok).

Does not install binaries. Missing CLI → structured `missing` result.
Streaming CLIs yield tokens as they arrive (JSONL or raw chunks) so discuss
does not wait for process exit. Timeouts and cancel kill the process group.
Stderr is captured and redacted.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import time
from collections.abc import AsyncIterator, Callable
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


def kill_cli_process(proc: Any) -> None:
    """Kill the CLI and its process group. Safe if already exited."""
    if proc is None:
        return
    if getattr(proc, "returncode", None) is not None:
        return
    pid = getattr(proc, "pid", None)
    if pid:
        if hasattr(os, "killpg"):
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
    killer = getattr(proc, "kill", None)
    if callable(killer):
        try:
            killer()
        except (ProcessLookupError, OSError):
            pass


def _run_captured(
    argv: list[str],
    *,
    timeout: float,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> subprocess.CompletedProcess:
    """Run argv, kill the process group on timeout. Never leaks hung children."""
    if runner is not None:
        return runner(argv, capture_output=True, text=True, timeout=timeout, check=False)
    proc = subprocess.Popen(  # noqa: S603 — user-configured local CLI only
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_cli_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=CLI_KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            kill_cli_process(proc)
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
    try:
        proc = _run_captured([path, "--help"], timeout=CLI_PROBE_TIMEOUT_S, runner=runner)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    help_blob = redact((proc.stdout or proc.stderr or "").strip())
    return help_blob.splitlines()[0][:200] if help_blob else ""


def exec_argv(
    command: str,
    prompt: str,
    *,
    binary_path: str = "",
    binary_name: str = "",
    stream: bool = False,
) -> list[str]:
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
        if stream and preset.stream_args:
            prefix.extend(preset.stream_args)
        return [*prefix, prompt]
    if not tokens:
        raise ValueError("empty CLI command")
    tokens[0] = binary_path or binary_name or tokens[0]
    if stream:
        extra = preset.stream_args if preset else ()
        if extra:
            tokens.extend(extra)
    return [*tokens, prompt]


def decode_cli_jsonl(line: str) -> str:
    """Pull assistant text out of Codex / Claude / Gemini / Grok JSONL events."""
    raw = (line or "").strip()
    if not raw:
        return ""
    if raw.startswith("data:"):
        raw = raw[5:].strip()
    if raw in {"[DONE]", ""}:
        return ""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    return _extract_json_text(obj)


def _extract_json_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if not isinstance(obj, dict):
        return ""
    for key in ("delta", "text", "content", "response"):
        val = obj.get(key)
        if isinstance(val, str) and val:
            return val
    delta = obj.get("delta")
    if isinstance(delta, dict):
        for key in ("text", "content"):
            val = delta.get(key)
            if isinstance(val, str) and val:
                return val
    msg = obj.get("message") or obj.get("item") or obj.get("event") or {}
    if isinstance(msg, dict):
        for key in ("text", "content", "delta"):
            val = msg.get(key)
            if isinstance(val, str) and val:
                return val
            if isinstance(val, list):
                parts = [
                    block.get("text", "")
                    for block in val
                    if isinstance(block, dict) and isinstance(block.get("text"), str)
                ]
                if parts:
                    return "".join(parts)
    return ""


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


async def stream_cli_process(
    argv: list[str],
    *,
    timeout: float = CLI_EXEC_TIMEOUT_S,
    stream_format: str = "text",
    spawn: Callable[..., Any] | None = None,
) -> AsyncIterator[str]:
    """Yield tokens as stdout arrives. Timeout/cancel kill the process group."""
    if spawn is not None:
        proc = await spawn(argv)
    else:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    stderr_task = asyncio.create_task(_drain_stderr(proc))
    deadline = time.monotonic() + timeout
    yielded = False
    try:
        stdout = proc.stdout
        if stdout is None:
            return
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            if stream_format == "jsonl":
                chunk = await asyncio.wait_for(stdout.readline(), timeout=remaining)
                if not chunk:
                    break
                text = decode_cli_jsonl(_as_text(chunk))
            else:
                chunk = await asyncio.wait_for(stdout.read(64), timeout=remaining)
                if not chunk:
                    break
                text = _as_text(chunk)
            text = redact(text)
            if text:
                yielded = True
                yield text
        await asyncio.wait_for(proc.wait(), timeout=max(0.1, deadline - time.monotonic()))
        if proc.returncode not in (0, None) and not yielded:
            err = redact(await _stderr_result(stderr_task))
            raise RuntimeError(f"CLI exited {proc.returncode}: {err[:400]}")
    except asyncio.TimeoutError as exc:
        kill_cli_process(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=CLI_KILL_GRACE_S)
        except (asyncio.TimeoutError, ProcessLookupError):
            kill_cli_process(proc)
        raise RuntimeError(f"CLI timed out after {timeout}s and was killed") from exc
    except asyncio.CancelledError:
        kill_cli_process(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=CLI_KILL_GRACE_S)
        except (asyncio.TimeoutError, ProcessLookupError, asyncio.CancelledError):
            kill_cli_process(proc)
        raise
    finally:
        if getattr(proc, "returncode", None) is None:
            kill_cli_process(proc)
        if not stderr_task.done():
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass


async def stream_cli_prompt(
    command: str,
    prompt: str,
    *,
    which: WhichFn | None = None,
    timeout: float = CLI_EXEC_TIMEOUT_S,
    spawn: Callable[..., Any] | None = None,
) -> AsyncIterator[str]:
    probe = probe_cli(command, which=which)
    if not probe.found:
        raise FileNotFoundError(probe.detail or f"missing CLI {command!r}")
    preset = preset_for_command(command)
    argv = exec_argv(
        command,
        prompt,
        binary_path=probe.path,
        binary_name=probe.binary,
        stream=True,
    )
    async for token in stream_cli_process(
        argv,
        timeout=timeout,
        stream_format=(preset.stream_format if preset else "text"),
        spawn=spawn,
    ):
        yield token


async def _drain_stderr(proc: Any) -> str:
    stderr = getattr(proc, "stderr", None)
    if stderr is None:
        return ""
    try:
        data = await stderr.read()
    except (OSError, asyncio.CancelledError):
        return ""
    return redact(_as_text(data))


async def _stderr_result(task: asyncio.Task) -> str:
    try:
        return await task
    except (Exception, asyncio.CancelledError):
        return ""


def _as_text(chunk: bytes | str) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="replace")
    return chunk


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
