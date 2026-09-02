"""Offline fixture: N advisors, one shared labeled timeline, no teammate sessions."""

from __future__ import annotations

from pathlib import Path

import pytest

from prd_ai_battle.cli import build_parser, cmd_discuss_stream
from prd_ai_battle.config import AppConfig, GatewayConfig, LOCAL_GATEWAY_URL, ModelConfig
from prd_ai_battle.llm import MockChatClient, opening_marker
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


def test_new_requirement_discuss_does_not_leak_old_transcript(tmp_path: Path, capsys):
    """Leftover 招标 round0 bubbles must not prepend a new --requirement discuss."""
    from prd_ai_battle.models import ChatMessage
    from prd_ai_battle.phase import load_session

    ws = tmp_path / "leftover"
    session = load_session(workspace=ws, offline=True)
    session.load_sample()
    leftover = "LEFTOVER-TENDER-ROUND0-招标-UNIQUE"
    session.store.append_message(
        ChatMessage(model_id="advisor-a", role="assistant", phase=Phase.DISCUSS, content=leftover),
        session.state,
    )
    session.persist()
    assert leftover in session.render_timeline()
    assert leftover in (ws / "transcript.jsonl").read_text(encoding="utf-8")

    fresh = tmp_path / "fresh-brief.md"
    fresh.write_text("# 新需求\n\n## 必须做\n- 只讨论这条新条款\n", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "discuss",
            "--offline",
            "--workspace",
            str(ws),
            "--requirement",
            str(fresh),
            "--prompt",
            "fresh start",
        ]
    )
    assert cmd_discuss_stream(args) == 0
    out = capsys.readouterr().out
    transcript = (ws / "transcript.jsonl").read_text(encoding="utf-8")
    assert leftover not in out
    assert leftover not in transcript
    assert "招标-UNIQUE" not in out
    assert "Shared discuss" in out


def test_same_requirement_discuss_keeps_prior_utterances(tmp_path: Path, capsys):
    """Follow-up discuss on the same --requirement is still one group-chat timeline."""
    req = tmp_path / "same.md"
    req.write_text("# 同一需求\n\n## 必须做\n- 等保\n", encoding="utf-8")
    ws = tmp_path / "same-ws"
    first = build_parser().parse_args(
        ["discuss", "--offline", "--workspace", str(ws), "--requirement", str(req), "--prompt", "first D"]
    )
    assert cmd_discuss_stream(first) == 0
    capsys.readouterr()
    first_text = (ws / "transcript.jsonl").read_text(encoding="utf-8")
    assert "first D" in first_text
    second = build_parser().parse_args(
        [
            "discuss",
            "--offline",
            "--workspace",
            str(ws),
            "--requirement",
            str(req),
            "--prompt",
            "follow-up keep-me",
        ]
    )
    assert cmd_discuss_stream(second) == 0
    out = capsys.readouterr().out
    again = (ws / "transcript.jsonl").read_text(encoding="utf-8")
    assert "first D" in again
    assert "follow-up keep-me" in again
    assert "first D" in out or "keep-me" in out


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


@pytest.mark.asyncio
async def test_crossing_round_quotes_other_speakers_round0(tmp_path: Path):
    """After round 1, a speaker's second utterance must contain another mouth's round-0 marker."""
    session = _session(tmp_path, n=2)
    speakers = session.speakers()
    assert len(speakers) >= 3  # lead + 2 advisors

    async for _ in session.discuss("opening brief", crossing=False):
        pass
    round0 = [m for m in session.load_timeline() if m.role == "assistant"]
    assert {m.model_id for m in round0} == set(speakers)
    for msg in round0:
        assert opening_marker(msg.model_id) in msg.content

    async for _ in session.discuss("cross the thread", crossing=True):
        pass

    by_speaker: dict[str, list[str]] = {sid: [] for sid in speakers}
    for msg in session.load_timeline():
        if msg.role == "assistant":
            by_speaker[msg.model_id].append(msg.content)
    for sid, turns in by_speaker.items():
        assert len(turns) >= 2, sid
    # Pick any speaker's second utterance; it must quote someone else's round-0 bubble.
    other = speakers[0]
    reply = by_speaker[speakers[1]][1]
    assert opening_marker(other) in reply
    assert session.state.phase is Phase.DISCUSS
    assert session.state.write_lock is True
    assert not session.state.allows_write(session.state.primary)
    assert not (session.store.root / "teammates").exists()
    assert list(session.store.root.glob("**/teammate*")) == []
    assert session.store.latest_version() == 0


@pytest.mark.asyncio
async def test_discuss_group_does_opening_then_crossing(tmp_path: Path):
    session = _session(tmp_path, n=2)
    async for _ in session.discuss_group("first D"):
        pass
    assistants = [m for m in session.load_timeline() if m.role == "assistant"]
    by_speaker: dict[str, list[str]] = {}
    for msg in assistants:
        by_speaker.setdefault(msg.model_id, []).append(msg.content)
    assert all(len(v) == 2 for v in by_speaker.values())
    lead_second = by_speaker["lead"][1]
    assert any(opening_marker(sid) in lead_second for sid in ("adv-1", "adv-2"))


@pytest.mark.asyncio
async def test_discuss_interrupt_keeps_partials_no_writes(tmp_path: Path):
    session = _session(tmp_path, n=2)
    session.client = MockChatClient(delay_s=0.03)
    seen = 0

    async for event in session.discuss_group("please stop"):
        if event.text:
            seen += 1
        if seen >= 2:
            session.request_stop()

    assert seen >= 1
    assert session.state.phase is Phase.DISCUSS
    assert session.state.write_lock is True
    assert not session.state.allows_write(session.state.primary)
    timeline = session.load_timeline()
    assert any(m.role == "user" for m in timeline)
    assert any(m.role == "assistant" and m.content.strip() for m in timeline)
    assert session.store.latest_version() == 0
    assert list(session.store.drafts_dir.glob("**/response.md")) == []
    assert not (session.store.root / "teammates").exists()
    assert list(session.store.root.glob("session-*.json")) == []
    assert list(session.store.root.glob("**/teammate*")) == []
