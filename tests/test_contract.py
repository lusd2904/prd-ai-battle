"""Lock the product-team session contract in types and JSON schema."""

from prd_ai_battle.models import (
    MatrixRow,
    Phase,
    ReviewPacket,
    SessionState,
    WRITE_PHASES,
)


REQUIRED_STATE_FIELDS = {
    "phase",
    "primary",
    "advisors",
    "brief",
    "matrix",
    "artifact_version",
    "write_lock",
}

REQUIRED_MATRIX_FIELDS = {"clause", "responded", "evidence_page", "opinion", "status"}


def test_session_state_required_fields():
    schema = SessionState.model_json_schema()
    assert REQUIRED_STATE_FIELDS <= set(schema["properties"])
    state = SessionState(primary="primary", advisors=["advisor-a"])
    view = state.contract_view()
    assert set(view) == REQUIRED_STATE_FIELDS
    assert state.phase is Phase.DISCUSS
    assert state.write_lock is True
    assert state.artifact_version == ""


def test_matrix_row_has_five_product_columns():
    schema = MatrixRow.model_json_schema()
    assert REQUIRED_MATRIX_FIELDS <= set(schema["properties"])
    row = MatrixRow(clause_id="S01", clause="★ compute")
    dumped = row.model_dump()
    assert dumped["clause"] == "★ compute"
    assert dumped["responded"] == "no"
    assert dumped["evidence_page"] == ""
    assert dumped["opinion"] == ""
    assert dumped["status"] == "open"


def test_write_phases_are_execute_and_revise_only():
    assert {p.value for p in WRITE_PHASES} == {"execute", "revise"}
    state = SessionState(primary="primary", advisors=["a"])
    for phase in Phase:
        state.phase = phase
        assert state.allows_write("primary") is (phase in WRITE_PHASES)
        assert state.allows_write("a") is False
        assert state.tools_for("a") == []


def test_review_packet_only_three_inputs():
    packet_fields = set(ReviewPacket.model_fields)
    assert packet_fields == {"brief", "matrix", "chapter_diff"}
    assert ReviewPacket.model_construct(
        brief=None,  # type: ignore[arg-type]
        matrix=None,  # type: ignore[arg-type]
        chapter_diff=[],
    ).allowed_keys() == ("brief", "matrix", "chapter_diff")
