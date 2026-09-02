from pathlib import Path

from prd_ai_battle.models import ChatMessage, Phase, SessionState
from prd_ai_battle.store import WorkspaceStore


def test_transcript_and_state_roundtrip(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "ws")
    state = SessionState(primary="primary", advisors=["advisor-a"])
    store.init(state)
    store.append_message(ChatMessage(model_id="primary", phase=Phase.DISCUSS, content="hello"), state)
    store.append_message(ChatMessage(model_id="advisor-a", phase=Phase.DISCUSS, content="hi"), state)
    messages = store.load_transcript()
    assert [m.model_id for m in messages] == ["primary", "advisor-a"]
    assert [m.model_id for m in state.timeline] == ["primary", "advisor-a"]
    assert " · " in messages[0].label()
    loaded = store.load_state(state)
    assert loaded.phase is Phase.DISCUSS
    assert loaded.primary == "primary"
    assert loaded.advisors == ["advisor-a"]
    assert loaded.write_lock is True


def test_transcript_append_fsyncs(tmp_path: Path, monkeypatch):
    """A crash mid-discuss must not lose the last jsonl line (fsync after write)."""
    fsync_fds: list[int] = []
    real_fsync = __import__("os").fsync

    def spy(fd: int) -> None:
        fsync_fds.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr("prd_ai_battle.store.os.fsync", spy)
    store = WorkspaceStore(tmp_path / "ws")
    store.init(SessionState(primary="primary", advisors=["advisor-a"]))
    store.append_message(ChatMessage(model_id="primary", phase=Phase.DISCUSS, content="hello"))
    assert fsync_fds, "append_message must fsync the transcript"
    lines = (tmp_path / "ws" / "transcript.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "hello" in lines[0]


def test_clear_timeline_drops_leftover_utterances(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "ws")
    state = SessionState(primary="primary", advisors=["advisor-a"])
    store.init(state)
    store.append_message(
        ChatMessage(model_id="advisor-a", phase=Phase.DISCUSS, content="old 招标 bubble"),
        state,
    )
    assert store.load_transcript()
    store.clear_timeline(state)
    assert store.load_transcript() == []
    assert state.timeline == []
    assert store.transcript_path.read_text(encoding="utf-8") == ""
