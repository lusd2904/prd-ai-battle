from prd_ai_battle.models import Phase
from prd_ai_battle.state import IllegalTransition, StateMachine

import pytest


def test_happy_path_discuss_confirm_review():
    sm = StateMachine(has_brief=True)
    sm.advance(Phase.DISCUSS)
    sm.lock_matrix()
    assert sm.phase is Phase.CONFIRM
    assert sm.matrix_locked
    sm.record_draft()
    sm.start_review()
    assert sm.phase is Phase.REVIEW
    sm.record_draft()
    assert sm.draft_count == 2


def test_cannot_discuss_without_brief():
    sm = StateMachine()
    with pytest.raises(IllegalTransition, match="brief"):
        sm.advance(Phase.DISCUSS)


def test_cannot_skip_to_review():
    sm = StateMachine(has_brief=True)
    sm.advance(Phase.DISCUSS)
    with pytest.raises(IllegalTransition):
        sm.start_review()


def test_cannot_lock_from_idle():
    sm = StateMachine(has_brief=True)
    with pytest.raises(IllegalTransition, match="discuss"):
        sm.lock_matrix()


def test_cannot_review_without_draft():
    sm = StateMachine(has_brief=True)
    sm.advance(Phase.DISCUSS)
    sm.lock_matrix()
    with pytest.raises(IllegalTransition, match="draft"):
        sm.start_review()


def test_illegal_back_to_discuss():
    sm = StateMachine(has_brief=True)
    sm.advance(Phase.DISCUSS)
    sm.lock_matrix()
    sm.record_draft()
    sm.start_review()
    with pytest.raises(IllegalTransition):
        sm.advance(Phase.DISCUSS)
