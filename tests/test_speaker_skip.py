"""Discuss/review skip a 402/quota speaker; remaining mouths continue."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from prd_ai_battle.config import AppConfig, GatewayConfig, LOCAL_GATEWAY_URL, ModelConfig
from prd_ai_battle.llm import MockChatClient
from prd_ai_battle.models import Phase
from prd_ai_battle.ping import filter_ready_speakers, ping_one, skip_reason, speaker_ping_target
from prd_ai_battle.session import Session


def _live_team(workspace: str) -> AppConfig:
    cfg = AppConfig(
        workspace=workspace,
        offline=False,
        gateway=GatewayConfig(base_url=LOCAL_GATEWAY_URL, api_key="gw"),
        primary=ModelConfig(
            id="primary",
            model="mock-primary",
            base_url="http://xixi.test/v1",
            api_key="xixi-key",
            temperature=0.2,
        ),
        advisors=[
            ModelConfig(
                id="advisor-sonnet",
                model="mock-sonnet",
                base_url="http://xixi.test/v1",
                api_key="xixi-key",
                temperature=0.4,
            ),
            ModelConfig(
                id="advisor-glm",
                model="z-ai/glm-5.2:free",
                base_url="http://openrouter.test/v1",
                api_key="or-key",
                temperature=0.4,
            ),
        ],
    )
    return cfg.resolve()


def _handler_402_on_openrouter(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    host = request.url.host
    if host == "openrouter.test":
        return httpx.Response(402, text="Payment required: no credits")
    if host == "xixi.test":
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    return httpx.Response(500, text=f"unexpected {host} {body}")


@pytest.mark.asyncio
async def test_discuss_skips_402_speaker_others_continue(tmp_path: Path):
    ws = tmp_path / "ws"
    session = Session(_live_team(str(ws)), root=ws)
    session.client = MockChatClient(delay_s=0.0)
    session._ping_transport = httpx.MockTransport(_handler_402_on_openrouter)
    session.load_sample()

    spoke: set[str] = set()
    skipped_text: dict[str, str] = {}
    async for event in session.discuss("cover 等保"):
        if event.done:
            spoke.add(event.model_id)
        if "[skipped]" in event.text:
            skipped_text[event.model_id] = event.text

    assert "advisor-glm" in skipped_text
    assert "402" in skipped_text["advisor-glm"]
    assert ("advisor-glm",) == tuple(mid for mid, _ in session.last_skipped)
    assert "primary" in spoke
    assert "advisor-sonnet" in spoke
    # 402 speaker must not be asked to stream a real reply
    timeline = session.load_timeline()
    glm_msgs = [m for m in timeline if m.model_id == "advisor-glm"]
    assert glm_msgs
    assert all("[skipped]" in m.content for m in glm_msgs if m.role == "assistant")
    sonnet = [m for m in timeline if m.model_id == "advisor-sonnet" and m.role == "assistant"]
    assert sonnet
    assert "[skipped]" not in sonnet[0].content
    assert session.state.phase is Phase.DISCUSS
    assert session.state.write_lock is True
    assert not session.state.allows_write("advisor-glm")
    assert not session.state.allows_write("advisor-sonnet")
    assert session.store.latest_version() == 0


@pytest.mark.asyncio
async def test_review_skips_402_advisor_others_continue(tmp_path: Path):
    ws = tmp_path / "ws"
    session = Session(_live_team(str(ws)), root=ws)
    session.client = MockChatClient(delay_s=0.0)
    session.load_sample()
    session.seed_matrix_offline()
    session.enter_discuss()
    session.lock_matrix()
    await session.execute_primary()
    session._ping_transport = httpx.MockTransport(_handler_402_on_openrouter)

    skipped: set[str] = set()
    reviewed: set[str] = set()
    async for event in session.review():
        if "[skipped]" in event.text:
            skipped.add(event.model_id)
        elif event.text.strip() and event.model_id != "user":
            reviewed.add(event.model_id)

    assert "advisor-glm" in skipped
    assert "advisor-sonnet" in reviewed
    assert "advisor-glm" not in reviewed
    assert session.state.tools_for("advisor-sonnet") == []
    assert session.state.tools_for("advisor-glm") == []


def test_filter_ready_speakers_skips_402_keeps_ok(tmp_path: Path):
    cfg = _live_team(str(tmp_path))
    transport = httpx.MockTransport(_handler_402_on_openrouter)
    ready, skipped = filter_ready_speakers(cfg.all_models(), cfg, transport=transport)
    ready_ids = [m.id for m in ready]
    skipped_ids = [m.id for m, _reason in skipped]
    assert "primary" in ready_ids
    assert "advisor-sonnet" in ready_ids
    assert "advisor-glm" in skipped_ids
    assert "advisor-glm" not in ready_ids
    assert "402" in skipped[0][1]


def test_ping_402_is_payment_required_not_hard_fail(tmp_path: Path):
    cfg = _live_team(str(tmp_path))
    glm = next(m for m in cfg.advisors if m.id == "advisor-glm")
    target = speaker_ping_target(glm, cfg)
    result = ping_one(target, transport=httpx.MockTransport(_handler_402_on_openrouter))
    assert result.http_status == 402
    assert result.outcome == "payment_required"
    assert result.hard_fail is False
    reason = skip_reason(result)
    assert reason is not None
    assert "402" in reason
