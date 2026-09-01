"""OpenAI-compatible Chat Completions client with true parallel SSE streams.

Also ships an offline mock so the TUI is usable with no API keys.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from prd_ai_battle.config import ModelConfig
from prd_ai_battle.models import ChatMessage, Phase


@dataclass
class StreamDelta:
    model_id: str
    text: str
    done: bool = False


class LLMError(RuntimeError):
    pass


class ChatClient:
    """Minimal Chat Completions wrapper. One HTTP stream per model."""

    def __init__(self, timeout: float = 120.0) -> None:
        self.timeout = timeout

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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise LLMError(f"{model.id} HTTP {resp.status_code}: {body[:400]}")
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


class MockChatClient(ChatClient):
    """Deterministic streaming replies for offline / demo mode."""

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
    # discuss
    if is_primary:
        return (
            "I read the brief, not the raw tender. Highest risk is the ★ must-respond clauses "
            "(compute / storage / 等保) plus 废标项 on certificates and budget. "
            "I propose we lock a 响应对照表 covering starred items, scoring points, and "
            "disqualifiers before anyone writes files."
        )
    if "advisor-b" in model_id:
        return (
            "Disagree slightly: lock the matrix now, but mark 类似业绩 and 项目团队 as "
            "PARTIAL until we list named contracts and PMP/软考 evidence. "
            "Do not dump the whole 招标文件 into context — the brief is enough."
        )
    return (
        "Agree with a shared chat. Scoring is 30/30/40 — the technical 40 is where we lose. "
        "Call out 等保 2.0 三级, 180-day logs, and 90-day初验 as must-win rows in the matrix."
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
) -> AsyncIterator[StreamDelta]:
    """Fan out one SSE stream per model and yield labeled deltas as they arrive."""

    queue: asyncio.Queue[StreamDelta | None] = asyncio.Queue()

    async def run(model: ModelConfig) -> None:
        try:
            async for token in client.stream_chat(
                model,
                messages_for[model.id],
                tools=tools_for.get(model.id, []),
            ):
                await queue.put(StreamDelta(model.id, token, False))
            await queue.put(StreamDelta(model.id, "", True))
        except Exception as exc:  # noqa: BLE001 — surface to the TUI as a bubble
            await queue.put(StreamDelta(model.id, f"\n[error] {exc}", True))

    tasks = [asyncio.create_task(run(m)) for m in models]
    finished = 0
    while finished < len(tasks):
        event = await queue.get()
        if event is None:
            continue
        if event.done:
            finished += 1
        yield event
    await asyncio.gather(*tasks, return_exceptions=True)


def transcript_to_openai(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]
