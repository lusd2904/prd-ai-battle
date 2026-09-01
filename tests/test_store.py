from pathlib import Path

from prd_ai_battle.models import ChatMessage, Phase
from prd_ai_battle.store import WorkspaceStore


def test_transcript_roundtrip(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "ws")
    store.init()
    store.append_message(ChatMessage(model_id="primary", phase=Phase.DISCUSS, content="hello"))
    store.append_message(ChatMessage(model_id="advisor-a", phase=Phase.DISCUSS, content="hi"))
    messages = store.load_transcript()
    assert [m.model_id for m in messages] == ["primary", "advisor-a"]
    assert store.load_meta().phase is Phase.IDLE
