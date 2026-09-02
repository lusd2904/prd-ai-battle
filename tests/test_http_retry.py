"""Offline HTTP retry / redact fixtures. No live network."""

from __future__ import annotations

import json

import httpx
import pytest

from prd_ai_battle.http_retry import backoff_seconds, retry_call, should_retry_status
from prd_ai_battle.redact import redact


def test_backoff_and_retryable_status():
    assert should_retry_status(429)
    assert should_retry_status(503)
    assert not should_retry_status(401)
    assert not should_retry_status(402)
    assert backoff_seconds(0) == 0.4
    assert backoff_seconds(9) == 1.6


def test_retry_call_succeeds_after_failures():
    box = {"n": 0}

    def flaky() -> str:
        box["n"] += 1
        if box["n"] < 3:
            raise RuntimeError("retry me")
        return "ok"

    assert retry_call(flaky, attempts=4, sleeper=lambda _s: None) == "ok"
    assert box["n"] == 3


def test_retry_call_stops_when_not_retryable():
    def boom() -> str:
        raise ValueError("no")

    with pytest.raises(ValueError):
        retry_call(boom, attempts=4, sleeper=lambda _s: None, retryable=lambda _e: False)


def test_redact_authorization_and_env_values(monkeypatch):
    monkeypatch.setenv("PRD_SFP_XIXI_KEY", "xixi-super-secret")
    monkeypatch.setenv("PRD_CODEX_KEY", "codex-super-secret")
    blob = redact(
        "Authorization: Bearer xixi-super-secret leftover PRD_CODEX_KEY=codex-super-secret"
    )
    assert "xixi-super-secret" not in blob
    assert "codex-super-secret" not in blob
    assert "***" in blob


@pytest.mark.asyncio
async def test_chat_client_retries_429_then_streams(monkeypatch):
    from prd_ai_battle.config import ModelConfig
    from prd_ai_battle.llm import ChatClient

    monkeypatch.setenv("PRIMARY_KEY", "primary-super-secret")
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        auth = request.headers.get("Authorization", "")
        assert "primary-super-secret" in auth
        if hits["n"] < 2:
            return httpx.Response(429, text="quota primary-super-secret")
        sse = (
            'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    model = ModelConfig(
        id="primary",
        model="mock",
        base_url="http://127.0.0.1:9/v1",
        api_key_env="PRIMARY_KEY",
    )
    client = ChatClient(timeout=5.0)

    async def _once(model_id, url, headers, payload, extra_secrets):
        # Drive the real retry loop by patching httpx.AsyncClient
        yield "hi"

    # Use httpx mock via monkeypatch of AsyncClient.stream is heavy; call retry path
    # through a tiny local transport by swapping _stream_once to use MockTransport.
    original = ChatClient._stream_once

    async def patched(self, model_id, url, headers, payload, extra_secrets):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(timeout=5.0, transport=transport) as http:
            async with http.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code == 429:
                    from prd_ai_battle.llm import _RetryableHTTP

                    raise _RetryableHTTP("429")
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        chunk = json.loads(data)
                        content = chunk["choices"][0]["delta"].get("content")
                        if content:
                            yield content

    monkeypatch.setattr(ChatClient, "_stream_once", patched)
    tokens: list[str] = []
    async for tok in client.stream_chat(model, [{"role": "user", "content": "ping"}]):
        tokens.append(tok)
    assert tokens == ["hi"]
    assert hits["n"] == 2
    _ = original
