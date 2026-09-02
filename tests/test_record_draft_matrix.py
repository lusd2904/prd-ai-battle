"""execute/revise record-draft fills 是否响应 from the draft; lock only freezes clauses."""

from pathlib import Path

import pytest

from prd_ai_battle.cli import build_parser, cmd_record_draft as cli_record_draft
from prd_ai_battle.models import ResponseStatus
from prd_ai_battle.phase import (
    cmd_execute,
    cmd_lock,
    cmd_record_draft,
    cmd_review,
    load_session,
)
from prd_ai_battle.write_lock import WriteDenied

FIVE_ROW = Path(__file__).resolve().parent / "fixtures" / "vpn_latency_brief.md"

COVERING_DRAFT = """# 投标响应稿 v1

## 延迟优化
给出不改现网前提下可落地的延迟优化方案，并量化预期 RTT 改善。

## 多路径评估
评估多路径或智能选路的收益与改造成本，不作为验收项。

## 风险说明
方案若被误当成实施清单，可能中断现网隧道。

## 现网边界
不得直接改现网设备或路由。

## 供应商
不引入新的供应商锁定。
"""

OMITTING_DRAFT = """# 投标响应稿 v1

## 延迟优化
给出不改现网前提下可落地的延迟优化方案，并量化预期 RTT 改善。

## 多路径评估
评估多路径或智能选路的收益与改造成本，不作为验收项。

## 风险说明
方案若被误当成实施清单，可能中断现网隧道。

## 现网边界
不得直接改现网设备或路由。
"""


def _ingest_lock_execute(workspace: Path):
    session = load_session(workspace=workspace, offline=True)
    session.load_requirement(FIVE_ROW)
    assert len(session.state.matrix.rows) == 5
    assert [row.clause_id for row in session.state.matrix.rows] == [
        "S01",
        "R02",
        "R03",
        "R04",
        "R05",
    ]
    assert all(row.responded is ResponseStatus.NO for row in session.state.matrix.rows)
    assert all(row.evidence_page == "" for row in session.state.matrix.rows)
    cmd_lock(session)
    cmd_execute(session)
    return session


def _write_draft(workspace: Path, body: str, version: str = "v1") -> Path:
    dest = workspace / "drafts" / version / "response.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    return dest


def test_record_draft_covering_five_rows_not_all_no(tmp_path: Path):
    session = _ingest_lock_execute(tmp_path)
    locked_ids = [row.clause_id for row in session.state.matrix.rows]
    draft = _write_draft(tmp_path, COVERING_DRAFT)
    payload = cmd_record_draft(session, str(draft), actor_id="primary")
    rows = session.state.matrix.rows
    assert [row.clause_id for row in rows] == locked_ids
    assert not all(row.responded is ResponseStatus.NO for row in rows)
    assert any(row.responded in {ResponseStatus.YES, ResponseStatus.PARTIAL} for row in rows)
    covered = [row for row in rows if row.responded is not ResponseStatus.NO]
    assert covered
    assert all(row.evidence_page for row in covered)
    assert all("L" in row.evidence_page or "·" in row.evidence_page for row in covered)
    matrix_rows = payload["matrix"]["rows"]
    assert not all(item["responded"] == "no" for item in matrix_rows)


def test_record_draft_omitting_one_clause_leaves_that_row_no(tmp_path: Path):
    session = _ingest_lock_execute(tmp_path)
    _write_draft(tmp_path, OMITTING_DRAFT)
    cmd_record_draft(session, "drafts/v1/response.md", actor_id="primary")
    by_id = {row.clause_id: row for row in session.state.matrix.rows}
    assert by_id["R05"].responded is ResponseStatus.NO
    assert by_id["R05"].evidence_page == ""
    assert by_id["S01"].responded is not ResponseStatus.NO
    assert by_id["R02"].responded is not ResponseStatus.NO
    assert by_id["R03"].responded is not ResponseStatus.NO
    assert by_id["R04"].responded is not ResponseStatus.NO


def test_review_packet_shows_updated_flags_brief_and_chapter_diff(tmp_path: Path):
    session = _ingest_lock_execute(tmp_path)
    cmd_record_draft(session, str(_write_draft(tmp_path, COVERING_DRAFT)), actor_id="primary")
    review = cmd_review(session)
    packet = review["review_packet"]
    assert "brief + matrix + chapter_diff" in packet or "chapter_diff" in packet
    assert session.state.brief is not None
    assert session.state.brief.title in packet
    for row in session.state.matrix.rows:
        assert row.clause_id in packet
        assert row.responded.value in packet
        if row.responded is not ResponseStatus.NO:
            assert row.evidence_page
            assert row.evidence_page in packet
    assert not all(row.responded is ResponseStatus.NO for row in session.state.matrix.rows)
    assert "chapter_diff" in packet


def test_record_draft_does_not_duplicate_workspace_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path
    workspace = home / ".prd-ai-battle" / "round-matrix"
    monkeypatch.chdir(home)
    session = _ingest_lock_execute(workspace)
    draft = _write_draft(workspace, COVERING_DRAFT)
    incoming = ".prd-ai-battle/round-matrix/drafts/v1/response.md"
    payload = cmd_record_draft(session, incoming, actor_id="primary")
    wrote = payload["wrote"]
    assert ".prd-ai-battle/round-matrix/.prd-ai-battle/round-matrix" not in wrote
    assert Path(wrote).resolve() == draft.resolve()
    doubled = ".prd-ai-battle/round-matrix/.prd-ai-battle/round-matrix/drafts/v1/response.md"
    again = load_session(workspace=workspace, offline=True)
    # already recorded v1; writing the same file again would bump version — just resolve
    from prd_ai_battle.matrix import resolve_recorded_write_path

    resolved = resolve_recorded_write_path(again.store.root, doubled)
    assert ".prd-ai-battle/round-matrix/.prd-ai-battle/round-matrix" not in str(resolved)
    assert resolved.resolve() == draft.resolve() or resolved == workspace / "drafts" / "v1" / "response.md"


def test_advisor_record_draft_still_denied(tmp_path: Path):
    session = _ingest_lock_execute(tmp_path)
    draft = _write_draft(tmp_path, COVERING_DRAFT)
    with pytest.raises(WriteDenied):
        cmd_record_draft(session, str(draft), actor_id="advisor-a")
    assert all(row.responded is ResponseStatus.NO for row in session.state.matrix.rows)


def test_locked_clause_list_frozen_after_record_draft(tmp_path: Path):
    session = _ingest_lock_execute(tmp_path)
    ids = [row.clause_id for row in session.state.matrix.rows]
    cmd_record_draft(session, str(_write_draft(tmp_path, COVERING_DRAFT)), actor_id="primary")
    from prd_ai_battle.models import MatrixLocked, MatrixRow

    with pytest.raises(MatrixLocked):
        session.state.matrix.add_row(MatrixRow(clause_id="X99", clause="new"))
    with pytest.raises(MatrixLocked):
        session.state.matrix.remove_row("S01")
    assert [row.clause_id for row in session.state.matrix.rows] == ids


def test_cli_record_draft_prints_wrote_without_doubled_prefix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path
    workspace = home / ".prd-ai-battle" / "round-matrix"
    monkeypatch.chdir(home)
    session = _ingest_lock_execute(workspace)
    session.persist()
    _write_draft(workspace, COVERING_DRAFT)
    args = build_parser().parse_args(
        [
            "record-draft",
            "--path",
            ".prd-ai-battle/round-matrix/drafts/v1/response.md",
            "--actor",
            "primary",
            "--workspace",
            str(workspace),
            "--offline",
        ]
    )
    assert cli_record_draft(args) == 0
    out = capsys.readouterr().out
    assert ".prd-ai-battle/round-matrix/.prd-ai-battle/round-matrix" not in out
    assert "drafts/v1/response.md" in out
