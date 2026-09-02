"""Offline fixture: N advisors, one shared labeled timeline, no teammate sessions."""

from __future__ import annotations

from pathlib import Path

import pytest

from prd_ai_battle.cli import build_parser, cmd_discuss_stream
from prd_ai_battle.config import AppConfig, GatewayConfig, LOCAL_GATEWAY_URL, ModelConfig
from prd_ai_battle.llm import MockChatClient
from prd_ai_battle.models import Phase, render_timeline
from prd_ai_battle.session import Session


def n_advisor_config(workspace: str, n: int = 3, *, primary_id: str = "lead") -> AppConfig:
    advisors = [
        ModelConfig(id=f"adv-{i}", model=f"mock-adv-{i}", temperature=0.4) for i in range(1, n + 1)
    ]
    cfg = AppConfig(
        workspace=workspace,
        offline=True,
        gateway=GatewayConfig(base_url=LOCAL_GATEWAY_URL, api_key=""),
        primary=ModelConfig(id=primary_id, model="mock-lead", temperature=0.2),
        advisors=advisors,
    )
    return cfg.resolve()


def _session(tmp_path: Path, n: int = 3) -> Session:
    ws = tmp_path / "ws"
    session = Session(n_advisor_config(str(ws), n=n), root=ws)
    session.client = MockChatClient(delay_s=0.0)
    session.load_sample()
    return session


@pytest.mark.asyncio
async def test_discuss_n_advisors_single_ordered_timeline(tmp_path: Path):
    session = _session(tmp_path, n=3)
    expected = ["lead", "adv-1", "adv-2", "adv-3"]
    assert session.speakers() == expected

    async for _ in session.discuss("first turn — score 等保"):
        pass

    timeline = session.load_timeline()
    assert timeline, "shared timeline must not be empty"
    assert all(m.model_id and m.ts for m in timeline)
    assert [m.model_id for m in timeline if m.role == "user"][0] == "user"
    assistant_ids = [m.model_id for m in timeline if m.role == "assistant"]
    assert set(assistant_ids) == set(expected)
    assert assistant_ids == list(dict.fromkeys(assistant_ids))  # each speaker once this round

    rendered = render_timeline(timeline)
    for speaker in expected:
        assert f"[{speaker} · " in rendered
    assert " · " in timeline[0].label()

    # session.json holds the same ordered list — no per-advisor session files.
    raw = session.store.meta_path.read_text(encoding="utf-8")
    assert '"timeline"' in raw
    assert session.state.timeline
    assert [m.model_id for m in session.state.timeline] == [m.model_id for m in timeline]
    assert session.store.transcript_path.is_file()
    assert not (session.store.root / "teammates").exists()
    assert list(session.store.root.glob("session-*.json")) == []
    assert list(session.store.root.glob("**/teammate*")) == []


@pytest.mark.asyncio
async def test_second_round_sees_prior_labeled_utterances(tmp_path: Path):
    session = _session(tmp_path, n=2)
    async for _ in session.discuss("opening: lock ★ storage"):
        pass
    captured: dict[str, list[dict[str, str]]] = {}
    original = session.client.stream_chat

    async def wrap(model, messages, *, tools=None):
        captured[model.id] = messages
        async for token in original(model, messages, tools=tools):
            yield token

    session.client.stream_chat = wrap  # type: ignore[method-assign]
    async for _ in session.discuss("follow-up: also mark 废标证书"):
        pass

    assert "adv-1" in captured
    blob = "\n".join(m["content"] for m in captured["adv-1"])
    assert "Shared discuss timeline" in blob
    assert "[lead · " in blob or "lead · " in blob
    assert "opening: lock ★ storage" in blob
    assert session.speakers() == ["lead", "adv-1", "adv-2"]
    assistant = [m for m in session.load_timeline() if m.role == "assistant"]
    assert len(assistant) == 6  # 3 speakers × 2 rounds


def test_discuss_cli_prints_one_labeled_stream(tmp_path: Path, capsys):
    args = build_parser().parse_args(
        [
            "discuss",
            "--offline",
            "--workspace",
            str(tmp_path / "cli"),
            "--prompt",
            "cover 废标风险",
        ]
    )
    assert cmd_discuss_stream(args) == 0
    out = capsys.readouterr().out
    assert "Shared discuss" in out
    assert "not OpenCode teammate panes" in out
    assert "[primary · " in out
    assert "[advisor-a · " in out
    assert "[advisor-b · " in out
    assert "teammate_sessions" not in out  # human stream, not JSON sidecar list
    ws = tmp_path / "cli"
    assert (ws / "transcript.jsonl").is_file()
    assert (ws / "session.json").is_file()
    assert not (ws / "teammates").exists()


def test_discuss_cli_json_has_speakers_from_yaml(tmp_path: Path, capsys):
    args = build_parser().parse_args(
        ["discuss", "--offline", "--json", "--workspace", str(tmp_path / "json")]
    )
    assert cmd_discuss_stream(args) == 0
    out = capsys.readouterr().out
    assert '"ux": "shared_timeline"' in out
    assert '"teammate_sessions": []' in out
    assert '"speakers"' in out
    assert "primary" in out
    assert "advisor-a" in out
    assert '"label"' in out


@pytest.mark.asyncio
async def test_advisors_still_tools_empty_on_shared_timeline(tmp_path: Path):
    session = _session(tmp_path, n=4)
    seen_tools: dict[str, list[str]] = {}
    original = session.client.stream_chat

    async def wrap(model, messages, *, tools=None):
        seen_tools[model.id] = list(tools or [])
        async for token in original(model, messages, tools=tools):
            yield token

    session.client.stream_chat = wrap  # type: ignore[method-assign]
    async for _ in session.discuss():
        pass
    assert seen_tools["lead"] == []  # discuss is not a write phase
    for i in range(1, 5):
        assert seen_tools[f"adv-{i}"] == []
    assert session.state.phase is Phase.DISCUSS
    assert not session.state.allows_write("lead")
    assert not session.state.allows_write("adv-1")
