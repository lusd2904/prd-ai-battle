"""OpenAI-compatible Chat Completions client with true parallel SSE streams.

Also ships an offline mock so the board is usable with no network.
HTTP: timeouts + retry/backoff on 429/5xx. One speaker failure is isolated
by stream_parallel. Errors are redacted (no Authorization / env values).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from prd_ai_battle.config import ModelConfig
from prd_ai_battle.http_retry import DEFAULT_ATTEMPTS, backoff_seconds, should_retry_status
from prd_ai_battle.models import ChatMessage, Phase
from prd_ai_battle.redact import redact

# Opening-round marker: unique per yaml speaker id so a later crossing
# reply can prove it read someone else's bubble. Not a seed model name.
ROUND0_MARKER = re.compile(r"\[round0-only:([^\]]+)\]")


@dataclass
class StreamDelta:
    model_id: str
    text: str
    done: bool = False


class LLMError(RuntimeError):
    pass


class _RetryableHTTP(LLMError):
    """429 / 5xx before any tokens — ChatClient retries with backoff."""


class ChatClient:
    """Minimal Chat Completions wrapper. One HTTP stream per model."""

    def __init__(self, timeout: float = 120.0, client: httpx.AsyncClient | None = None) -> None:
        self.timeout = timeout
        self._shared_client = client
        self._own_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._shared_client is None or self._shared_client.is_closed:
            self._shared_client = httpx.AsyncClient(timeout=self.timeout)
            self._own_client = True
        return self._shared_client

    async def aclose(self) -> None:
        if self._own_client and self._shared_client is not None and not self._shared_client.is_closed:
            await self._shared_client.aclose()
            self._shared_client = None

    async def __aenter__(self) -> ChatClient:
        await self._get_client()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.aclose()

    async def stream_chat(
        self,
        model: ModelConfig,
        messages: list[dict[str, str]],
        *,
        tools: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """Yield content tokens from an OpenAI-compatible SSE stream.

        Advisors must be called with tools=[] — that empty list is sent on the wire.
        """
        if model.is_cli():
            async for token in _stream_cli(model, messages, timeout=self.timeout):
                yield token
            return
        key = model.resolved_key()
        if not key:
            hint = model.api_key_env or "gateway.api_key / PRD_AI_GATEWAY_KEY"
            raise LLMError(f"Missing API key for model {model.id} ({hint})")

        payload = {
            "model": model.model,
            "messages": messages,
            "temperature": model.temperature,
            "stream": True,
            "tools": [_tool_spec(name) for name in (tools or [])],
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        url = model.chat_completions_url()
        last_error = ""
        for attempt in range(DEFAULT_ATTEMPTS):
            try:
                async for token in self._stream_once(model.id, url, headers, payload, extra_secrets=[key]):
                    yield token
                return
            except _RetryableHTTP as exc:
                last_error = str(exc)
                if attempt >= DEFAULT_ATTEMPTS - 1:
                    raise LLMError(redact(last_error, [key])) from exc
                await asyncio.sleep(backoff_seconds(attempt))
            except httpx.TimeoutException as exc:
                last_error = f"{model.id} timed out"
                if attempt >= DEFAULT_ATTEMPTS - 1:
                    raise LLMError(redact(last_error, [key])) from exc
                await asyncio.sleep(backoff_seconds(attempt))
        raise LLMError(redact(last_error or f"{model.id} HTTP failed", [key]))

    async def _stream_once(
        self,
        model_id: str,
        url: str,
        headers: dict[str, str],
        payload: dict,
        *,
        extra_secrets: list[str],
    ) -> AsyncIterator[str]:
        client = await self._get_client()
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if should_retry_status(resp.status_code):
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise _RetryableHTTP(
                        redact(f"{model_id} HTTP {resp.status_code}: {body[:400]}", extra_secrets)
                    )
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise LLMError(
                        redact(f"{model_id} HTTP {resp.status_code}: {body[:400]}", extra_secrets)
                    )
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content


async def _stream_cli(
    model: ModelConfig,
    messages: list[dict[str, str]],
    *,
    timeout: float = 120.0,
) -> AsyncIterator[str]:
    """Yield CLI tokens as they arrive so discuss does not wait for process exit."""
    from prd_ai_battle.cli_transport import command_for_model, messages_to_prompt, stream_cli_prompt

    command = command_for_model(model)
    if not command:
        raise LLMError(f"Model {model.id} has transport=cli but no command")
    try:
        async for token in stream_cli_prompt(
            command, messages_to_prompt(messages), timeout=timeout
        ):
            if token:
                yield token
    except FileNotFoundError as exc:
        raise LLMError(f"Missing CLI for {model.id}: {exc}") from exc
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as stream error, don't crash siblings
        raise LLMError(redact(f"CLI {command!r} failed for {model.id}: {exc}")) from exc


class MockChatClient(ChatClient):
    """Deterministic streaming replies for offline / --offline board mode."""

    def __init__(self, delay_s: float = 0.012) -> None:
        super().__init__()
        self.delay_s = delay_s

    async def stream_chat(
        self,
        model: ModelConfig,
        messages: list[dict[str, str]],
        *,
        tools: list[str] | None = None,
    ) -> AsyncIterator[str]:
        _ = tools
        phase = _infer_phase(messages)
        text = mock_reply(model.id, phase, messages)
        # Stream in small slices so the TUI can paint parallel bubbles.
        step = 12
        for i in range(0, len(text), step):
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield text[i : i + step]


def _tool_spec(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Write a draft artifact. Primary only; execute/revise phases.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    }


def _infer_phase(messages: list[dict[str, str]]) -> Phase:
    blob = " ".join(m.get("content", "") for m in messages).lower()
    if "chapter_diff" in blob or "you are reviewing" in blob or "review-phase input" in blob:
        return Phase.REVIEW
    if "revise the draft" in blob:
        return Phase.REVISE
    if "write the first draft" in blob:
        return Phase.EXECUTE
    return Phase.DISCUSS


def opening_marker(model_id: str) -> str:
    """Content that exists only in this speaker's round-0 bubble."""
    return f"[round0-only:{model_id}]"


def other_round0_markers(blob: str, model_id: str) -> list[str]:
    """Speaker ids whose round-0 markers appear in the shared timeline."""
    return [mid for mid in ROUND0_MARKER.findall(blob) if mid != model_id]


def mock_reply(model_id: str, phase: Phase, messages: list[dict[str, str]]) -> str:
    is_primary = model_id == "primary" or model_id.endswith("primary")
    if phase is Phase.REVIEW:
        if is_primary:
            return (
                "Review absorbed. I will bump the draft to v2: tighten 等保三级 evidence, "
                "add a 90-day milestone table, and map each ★ clause to a page in the 响应对照表."
            )
        if "advisor-b" in model_id:
            return (
                "Diff review: 废标项 on budget/cert/validity are asserted but not evidenced. "
                "Need explicit ISO 27001 / 20000 certificate pages and a sealed-bid checklist."
            )
        return (
            "Section diff vs brief: ★ 5.2 storage (500TB / 3 replicas / 8000 IOPS) is only "
            "partially answered. Recommend a capacity table and an IOPS test method."
        )
    if phase in {Phase.EXECUTE, Phase.REVISE}:
        return _primary_draft_markdown()
    blob = "\n".join(m.get("content", "") for m in messages)
    others = other_round0_markers(blob, model_id)
    has_thread = "Shared discuss timeline" in blob or "交叉讨论" in blob
    if has_thread and others:
        seen = others[0]
        return (
            f"Crossing as {model_id}. I read {seen}'s opening and quote "
            f"{opening_marker(seen)} — agree on locking the 对照表, "
            f"push back if anyone dumps the 招标文件."
        )
    # Round 0: parallel opening. Marker is unique to this yaml speaker id.
    marker = opening_marker(model_id)
    if is_primary:
        return (
            f"{marker} I read the brief, not the raw tender. Highest risk is the ★ "
            "must-respond clauses (compute / storage / 等保) plus 废标项 on certificates "
            "and budget. I propose we lock a 响应对照表 covering starred items, scoring "
            "points, and disqualifiers before anyone writes files."
        )
    if "advisor-b" in model_id:
        return (
            f"{marker} Disagree slightly: lock the matrix now, but mark 类似业绩 and "
            "项目团队 as PARTIAL until we list named contracts and PMP/软考 evidence. "
            "Do not dump the whole 招标文件 into context — the brief is enough."
        )
    return (
        f"{marker} Agree with a shared chat. Scoring is 30/30/40 — the technical 40 "
        "is where we lose. Call out 等保 2.0 三级, 180-day logs, and 90-day初验 as "
        "must-win rows in the matrix."
    )


def _primary_draft_markdown() -> str:
    return """# 投标响应稿 v1（骨架）

## 1 投标函要点
- 报价不超过预算 860 万元；投标有效期 90 日历天。
- 不接受联合体；按须知密封正本 1 + 副本 4 + U 盘 1。

## 2 ★ 必须响应条款
- 5.1 计算：提供 ≥200 台 16C/64G 云主机规格，支持热迁移。
- 5.2 存储：分布式块存储 ≥500TB，3 副本，IOPS ≥8000。
- 5.4 安全：等保 2.0 第三级；日志留存 ≥180 天。

## 3 评分点提纲
- 报价分：基准价策略与下浮说明（待填）。
- 商务：类似业绩 3 个、ISO 27001/20000、项目经理 PMP + 5 人社保。
- 技术：总体架构、安全合规、90 天实施计划、7×24 运维、3 天培训。

## 4 废标规避
认证证书、预算、密封、有效期、★条款响应、一份投标文件 — 已在对照表勾选。
"""


async def stream_parallel(
    client: ChatClient,
    models: list[ModelConfig],
    messages_for: dict[str, list[dict[str, str]]],
    tools_for: dict[str, list[str]],
    *,
    cancel: asyncio.Event | None = None,
) -> AsyncIterator[StreamDelta]:
    """Fan out one SSE stream per model and yield labeled deltas as they arrive.

    One model timeout or HTTP failure is isolated: it becomes an ``[error]``
    delta for that id and does **not** cancel the other streams. Discuss and
    review must keep going when a single advisor dies.

    ``cancel`` stops every in-flight stream. Already-queued tokens are drained
    so partial utterances can stay on the timeline. CancelledError is not an
    isolated ``[error]`` — the user asked to stop.
    """

    queue: asyncio.Queue[StreamDelta | None] = asyncio.Queue()

    async def run(model: ModelConfig) -> None:
        try:
            async for token in client.stream_chat(
                model,
                messages_for[model.id],
                tools=tools_for.get(model.id, []),
            ):
                if cancel is not None and cancel.is_set():
                    break
                await queue.put(StreamDelta(model.id, token, False))
            await queue.put(StreamDelta(model.id, "", True))
        except asyncio.CancelledError:
            await queue.put(StreamDelta(model.id, "", True))
            raise
        except Exception as exc:  # noqa: BLE001 — isolate; do not abort siblings
            await queue.put(StreamDelta(model.id, f"\n[error] {redact(str(exc))}", True))

    tasks = [asyncio.create_task(run(m)) for m in models]
    finished = 0
    pending = len(tasks)

    async def _drain_rest() -> AsyncIterator[StreamDelta]:
        nonlocal finished
        while True:
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if event is None:
                continue
            if event.done:
                finished += 1
            yield event

    stopper: asyncio.Task[bool] | None = (
        asyncio.create_task(cancel.wait()) if cancel is not None else None
    )
    getter: asyncio.Task[StreamDelta | None] | None = None

    try:
        while finished < pending:
            if cancel is not None and cancel.is_set():
                for task in tasks:
                    if not task.done():
                        task.cancel()
                async for event in _drain_rest():
                    yield event
                break

            if stopper is None:
                event = await queue.get()
            else:
                if getter is None:
                    getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {getter, stopper}, return_when=asyncio.FIRST_COMPLETED
                )
                if stopper in done and cancel.is_set():
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    if getter.done() and not getter.cancelled():
                        event = getter.result()
                        if event is not None:
                            if event.done:
                                finished += 1
                            yield event
                    async for drained in _drain_rest():
                        yield drained
                    break
                event = getter.result()
                getter = None

            if event is None:
                continue
            if event.done:
                finished += 1
            yield event
    finally:
        if stopper is not None and not stopper.done():
            stopper.cancel()
            try:
                await stopper
            except (asyncio.CancelledError, Exception):
                pass
        if getter is not None and not getter.done():
            getter.cancel()
            try:
                await getter
            except (asyncio.CancelledError, Exception):
                pass
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def transcript_to_openai(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


__all__ = [
    "ChatClient",
    "LLMError",
    "MockChatClient",
    "StreamDelta",
    "mock_reply",
    "opening_marker",
    "other_round0_markers",
    "stream_parallel",
    "transcript_to_openai",
]
