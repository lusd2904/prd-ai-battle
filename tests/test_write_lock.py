from pathlib import Path

import pytest

from prd_ai_battle.models import Brief, ComplianceMatrix, MatrixRow, Phase, SessionState
from prd_ai_battle.state import StateMachine
from prd_ai_battle.write_lock import ArtifactWriter, WriteDenied, WriteLock


def _machine(phase: Phase = Phase.DISCUSS) -> StateMachine:
    state = SessionState(
        primary="primary",
        advisors=["advisor-a"],
        phase=phase,
        brief=Brief(title="demo", summary="demo"),
        matrix=ComplianceMatrix(
            rows=[MatrixRow(clause_id="S01", clause="★ compute")],
            locked=phase is not Phase.DISCUSS,
        ),
        write_lock=True,
    )
    if phase is not Phase.DISCUSS:
        state.matrix.locked = True
    return StateMachine(state)


def test_advisor_always_gets_empty_tools_in_every_phase():
    lock = WriteLock(_machine().state)
    for phase in Phase:
        sm = _machine(phase)
        sm.state.artifact_version = "v1"
        assert sm.tools_for("advisor-a") == []
        assert lock.tools_for("advisor-a", sm) == []


def test_primary_tools_only_in_execute_and_revise():
    for phase in Phase:
        sm = _machine(phase)
        sm.state.artifact_version = "v1"
        tools = sm.tools_for("primary")
        if phase in {Phase.EXECUTE, Phase.REVISE}:
            assert tools == ["write_file"]
        else:
            assert tools == []


def test_primary_cannot_write_in_discuss_or_locked(tmp_path: Path):
    for phase in (Phase.DISCUSS, Phase.LOCKED, Phase.REVIEW):
        sm = _machine(phase)
        writer = ArtifactWriter(tmp_path / "drafts", WriteLock(sm.state), sm)
        with pytest.raises(WriteDenied):
            writer.write("primary", "response.md", "draft")


def test_advisor_write_denied_in_execute(tmp_path: Path):
    sm = _machine(Phase.EXECUTE)
    writer = ArtifactWriter(tmp_path / "drafts", WriteLock(sm.state), sm)
    with pytest.raises(WriteDenied, match="not the primary"):
        writer.write("advisor-a", "sneaky.md", "nope")
    assert not (tmp_path / "drafts").exists() or not any((tmp_path / "drafts").rglob("sneaky.md"))


def test_primary_write_in_execute_and_revise(tmp_path: Path):
    sm = _machine(Phase.EXECUTE)
    writer = ArtifactWriter(tmp_path / "drafts", WriteLock(sm.state), sm)
    path = writer.write("primary", "response.md", "# draft\n")
    assert path.read_text(encoding="utf-8") == "# draft\n"
    assert sm.artifact_version == "v1"
    sm.enter_review()
    sm.enter_revise()
    path2 = writer.write("primary", "response.md", "# draft v2\n")
    assert "v2" in str(path2)
    assert sm.artifact_version == "v2"


def test_rejects_path_escape(tmp_path: Path):
    sm = _machine(Phase.EXECUTE)
    writer = ArtifactWriter(tmp_path / "drafts", WriteLock(sm.state), sm)
    with pytest.raises(WriteDenied, match="relative"):
        writer.write("primary", "../escape.md", "x")


def test_unknown_actor_cannot_write_even_in_execute(tmp_path: Path):
    sm = _machine(Phase.EXECUTE)
    lock = WriteLock(sm.state)
    for actor in ("unknown", ""):
        with pytest.raises(WriteDenied, match="unknown"):
            lock.assert_can_write(actor, sm)
    writer = ArtifactWriter(tmp_path / "drafts", lock, sm)
    with pytest.raises(WriteDenied, match="unknown"):
        writer.write("unknown", "response.md", "nope")
    assert not (tmp_path / "drafts").exists() or not any((tmp_path / "drafts").rglob("response.md"))


def test_assert_can_write_matches_phase_rules():
    lock = WriteLock(_machine().state)
    for phase in Phase:
        sm = _machine(phase)
        if phase in {Phase.EXECUTE, Phase.REVISE}:
            lock.assert_can_write("primary", sm)
        else:
            with pytest.raises(WriteDenied):
                lock.assert_can_write("primary", sm)
        with pytest.raises(WriteDenied):
            lock.assert_can_write("advisor-a", sm)
        with pytest.raises(WriteDenied, match="unknown"):
            lock.assert_can_write("unknown", sm)
