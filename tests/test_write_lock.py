from pathlib import Path

import pytest

from prd_ai_battle.models import Phase
from prd_ai_battle.state import StateMachine
from prd_ai_battle.write_lock import ArtifactWriter, WriteDenied, WriteLock


def _ready_machine() -> StateMachine:
    sm = StateMachine(has_brief=True)
    sm.advance(Phase.DISCUSS)
    sm.lock_matrix()
    return sm


def test_advisor_never_gets_write_tools():
    sm = _ready_machine()
    lock = WriteLock("primary")
    assert lock.tools_for("advisor-a", sm) == []
    assert lock.tools_for("primary", sm) == ["write_file"]


def test_primary_has_no_write_tools_in_discuss():
    sm = StateMachine(has_brief=True)
    sm.advance(Phase.DISCUSS)
    lock = WriteLock("primary")
    assert lock.tools_for("primary", sm) == []
    with pytest.raises(WriteDenied, match="forbidden"):
        lock.assert_can_write("primary", sm)


def test_advisor_write_denied_even_after_lock(tmp_path: Path):
    sm = _ready_machine()
    writer = ArtifactWriter(tmp_path / "drafts", WriteLock("primary"), sm)
    with pytest.raises(WriteDenied, match="not the primary"):
        writer.write("advisor-a", "sneaky.md", "nope", version=1)
    assert not (tmp_path / "drafts" / "v1" / "sneaky.md").exists()


def test_primary_cannot_write_before_lock(tmp_path: Path):
    sm = StateMachine(has_brief=True)
    sm.advance(Phase.DISCUSS)
    writer = ArtifactWriter(tmp_path / "drafts", WriteLock("primary"), sm)
    with pytest.raises(WriteDenied, match="not locked"):
        writer.write("primary", "response.md", "draft", version=1)


def test_primary_write_after_lock(tmp_path: Path):
    sm = _ready_machine()
    writer = ArtifactWriter(tmp_path / "drafts", WriteLock("primary"), sm)
    path = writer.write("primary", "response.md", "# draft\n", version=1)
    assert path.read_text(encoding="utf-8") == "# draft\n"
    assert sm.draft_count == 1


def test_rejects_path_escape(tmp_path: Path):
    sm = _ready_machine()
    writer = ArtifactWriter(tmp_path / "drafts", WriteLock("primary"), sm)
    with pytest.raises(WriteDenied, match="relative"):
        writer.write("primary", "../escape.md", "x", version=1)
