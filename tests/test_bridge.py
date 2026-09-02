"""write-check: advisors tools=[], primary writes only in execute/revise."""

import pytest

from prd_ai_battle.bridge import WRITE_TOOLS, write_check
from prd_ai_battle.models import Brief, ComplianceMatrix, MatrixRow, Phase, SessionState
from prd_ai_battle.write_lock import WriteDenied, WriteLock


def _state(phase: Phase = Phase.DISCUSS, *, advisors=None) -> SessionState:
    state = SessionState(
        primary="primary",
        advisors=advisors or ["advisor-sonnet", "advisor-grok"],
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
    if phase in {Phase.REVIEW, Phase.REVISE}:
        state.artifact_version = "v1"
    return state


def test_advisor_product_ids_always_empty_tools():
    for phase in Phase:
        state = _state(phase)
        for advisor in ("advisor-sonnet", "advisor-grok", "advisor-a"):
            assert state.tools_for(advisor) == []
            denied = write_check(state, actor_id=advisor, tool="write", path="drafts/v1/sneaky.md")
            assert denied["ok"] is False
            assert denied["tools_for_actor"] == []
            shell = write_check(state, actor_id=advisor, tool="bash", path="")
            assert shell["ok"] is False


def test_primary_write_denied_outside_execute_revise():
    for phase in (Phase.DISCUSS, Phase.LOCKED, Phase.REVIEW):
        state = _state(phase)
        result = write_check(state, actor_id="primary", tool="write", path="drafts/v1/response.md")
        assert result["ok"] is False
        assert "execute" in result["reason"]


def test_primary_write_allowed_in_execute_and_revise():
    for phase in (Phase.EXECUTE, Phase.REVISE):
        state = _state(phase)
        result = write_check(state, actor_id="primary", tool="edit", path="drafts/v1/response.md")
        assert result["ok"] is True
        assert state.tools_for("primary") == ["write_file"]


def test_write_lock_binds_configured_primary_id_not_opus_or_seed_name():
    state = _state(Phase.EXECUTE)
    state.primary = "lead"
    state.advisors = ["advisor-sonnet", "advisor-grok"]
    assert write_check(state, actor_id="lead", tool="write", path="draft.md")["ok"] is True
    assert write_check(state, actor_id="primary", tool="write", path="draft.md")["ok"] is False
    assert write_check(state, actor_id="claude-opus-5", tool="write", path="draft.md")["ok"] is False
    assert write_check(state, actor_id="build", tool="write", path="draft.md")["ok"] is False
    assert write_check(state, actor_id="advisor-sonnet", tool="write", path="draft.md")["ok"] is False


def test_review_advisor_cannot_read_tender_or_repo():
    state = _state(Phase.REVIEW)
    tender = write_check(state, actor_id="advisor-grok", tool="read", path="samples/tender.md")
    assert tender["ok"] is False
    repo = write_check(state, actor_id="advisor-sonnet", tool="read", path="src/prd_ai_battle/session.py")
    assert repo["ok"] is False
    packet = write_check(
        state, actor_id="advisor-sonnet", tool="read", path=".prd-ai-battle/review-packet.md"
    )
    assert packet["ok"] is True


def test_advisor_never_reads_raw_tender_even_in_discuss():
    state = _state(Phase.DISCUSS)
    result = write_check(state, actor_id="advisor-sonnet", tool="read", path="src/prd_ai_battle/data/tender.md")
    assert result["ok"] is False


def test_advisor_never_reads_raw_pdf():
    state = _state(Phase.DISCUSS)
    pdf = write_check(state, actor_id="advisor-grok", tool="read", path="~/Downloads/招标文件.pdf")
    assert pdf["ok"] is False
    named = write_check(state, actor_id="advisor-sonnet", tool="read", path="samples/tender.pdf")
    assert named["ok"] is False


@pytest.mark.parametrize("phase", list(Phase))
@pytest.mark.parametrize("advisor", ["advisor-sonnet", "advisor-grok", "advisor-a"])
@pytest.mark.parametrize("tool", ["write", "edit", "apply_patch", "bash", "shell"])
def test_advisor_denied_write_and_shell_in_every_phase(phase, advisor, tool):
    state = _state(phase)
    result = write_check(state, actor_id=advisor, tool=tool, path="drafts/v1/sneaky.md")
    assert result["ok"] is False
    if tool in WRITE_TOOLS:
        with pytest.raises(WriteDenied):
            WriteLock(state).assert_can_write(advisor)


@pytest.mark.parametrize("phase", [Phase.DISCUSS, Phase.LOCKED, Phase.REVIEW])
@pytest.mark.parametrize("tool", ["write", "edit", "apply_patch", "write_file"])
def test_primary_write_denied_in_discuss_locked_review(phase, tool):
    state = _state(phase)
    result = write_check(state, actor_id="primary", tool=tool, path="drafts/v1/response.md")
    assert result["ok"] is False
    assert "execute" in result["reason"] or "revise" in result["reason"] or "forbidden" in result["reason"]
    with pytest.raises(WriteDenied):
        WriteLock(state).assert_can_write("primary")


@pytest.mark.parametrize("phase", [Phase.EXECUTE, Phase.REVISE])
@pytest.mark.parametrize("tool", ["write", "edit", "apply_patch"])
def test_primary_write_allowed_in_execute_revise_matrix(phase, tool):
    state = _state(phase)
    result = write_check(state, actor_id="primary", tool=tool, path="drafts/v1/response.md")
    assert result["ok"] is True
    WriteLock(state).assert_can_write("primary")


@pytest.mark.parametrize("phase", list(Phase))
@pytest.mark.parametrize("actor", ["unknown", "", "  "])
@pytest.mark.parametrize("tool", ["write", "edit", "apply_patch", "bash", "shell"])
def test_unknown_actor_denied_writes_and_shell(phase, actor, tool):
    state = _state(phase)
    result = write_check(state, actor_id=actor, tool=tool, path="drafts/v1/response.md")
    assert result["ok"] is False
    assert "unknown" in result["reason"]
    if tool in WRITE_TOOLS:
        with pytest.raises(WriteDenied, match="unknown"):
            WriteLock(state).assert_can_write(actor)
