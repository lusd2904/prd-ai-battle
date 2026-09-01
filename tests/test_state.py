from prd_ai_battle.models import Brief, ComplianceMatrix, MatrixRow, Phase, SessionState
from prd_ai_battle.state import IllegalTransition, StateMachine

import pytest


def _machine(*, brief: bool = True) -> StateMachine:
    state = SessionState(
        primary="primary",
        advisors=["advisor-a", "advisor-b"],
        brief=Brief(title="demo", summary="demo brief") if brief else None,
        matrix=ComplianceMatrix(rows=[MatrixRow(clause_id="S01", clause="★ compute")]),
    )
    return StateMachine(state)


def test_happy_path_discuss_locked_execute_review_revise():
    sm = _machine()
    assert sm.phase is Phase.DISCUSS
    sm.lock_matrix()
    assert sm.phase is Phase.LOCKED
    assert sm.matrix_locked
    assert not sm.writes_allowed()
    sm.enter_execute()
    assert sm.phase is Phase.EXECUTE
    assert sm.writes_allowed("primary")
    assert not sm.writes_allowed("advisor-a")
    sm.record_draft("v1")
    sm.enter_review()
    assert sm.phase is Phase.REVIEW
    assert not sm.writes_allowed()
    sm.enter_revise()
    assert sm.phase is Phase.REVISE
    sm.record_draft("v2")
    assert sm.artifact_version == "v2"


def test_cannot_discuss_without_brief():
    sm = _machine(brief=False)
    with pytest.raises(IllegalTransition, match="brief"):
        sm.enter_discuss()


def test_cannot_skip_to_review():
    sm = _machine()
    with pytest.raises(IllegalTransition):
        sm.enter_review()


def test_cannot_lock_without_brief():
    sm = _machine(brief=False)
    with pytest.raises(IllegalTransition, match="brief"):
        sm.lock_matrix()


def test_cannot_review_without_draft():
    sm = _machine()
    sm.lock_matrix()
    sm.enter_execute()
    with pytest.raises(IllegalTransition, match="draft"):
        sm.enter_review()


def test_illegal_back_to_discuss():
    sm = _machine()
    sm.lock_matrix()
    sm.enter_execute()
    sm.record_draft("v1")
    sm.enter_review()
    with pytest.raises(IllegalTransition):
        sm.advance(Phase.DISCUSS)


def test_phase_enum_is_the_product_set():
    assert {p.value for p in Phase} == {"discuss", "locked", "execute", "review", "revise"}
