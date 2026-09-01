from pathlib import Path

from prd_ai_battle.models import ChatMessage, Phase, SessionState
from prd_ai_battle.store import WorkspaceStore


def test_transcript_and_state_roundtrip(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "ws")
    state = SessionState(primary="primary", advisors=["advisor-a"])
    store.init(state)
    store.append_message(ChatMessage(model_id="primary", phase=Phase.DISCUSS, content="hello"))
    store.append_message(ChatMessage(model_id="advisor-a", phase=Phase.DISCUSS, content="hi"))
    messages = store.load_transcript()
    assert [m.model_id for m in messages] == ["primary", "advisor-a"]
    loaded = store.load_state(state)
    assert loaded.phase is Phase.DISCUSS
    assert loaded.primary == "primary"
    assert loaded.advisors == ["advisor-a"]
    assert loaded.write_lock is True
