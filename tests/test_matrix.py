from pathlib import Path

import pytest

from prd_ai_battle.ingest import extract_brief, bundled_sample_path
from prd_ai_battle.matrix import apply_draft_coverage, apply_offline_seed, matrix_from_brief
from prd_ai_battle.models import MatrixLocked, MatrixRow, ResponseStatus

VPN_BRIEF_PATH = Path(__file__).resolve().parent / "fixtures" / "vpn_latency_brief.md"


def test_matrix_rows_cover_star_score_and_disqualify():
    text = bundled_sample_path().read_text(encoding="utf-8")
    brief = extract_brief(text)
    matrix = matrix_from_brief(brief)
    cats = {r.category for r in matrix.rows}
    assert {"starred", "scoring", "disqualifier"} <= cats
    starred = [r for r in matrix.rows if r.category == "starred"]
    assert starred[0].clause.startswith("5.1")
    assert any("500TB" in r.clause or "存储" in r.clause for r in matrix.rows)
    table = matrix.as_prompt_table()
    assert "是否响应" in table
    assert "证据页码" in table
    assert "意见" in table
    assert "状态" in table


def test_cycle_and_lock():
    text = bundled_sample_path().read_text(encoding="utf-8")
    matrix = matrix_from_brief(extract_brief(text))
    first = matrix.rows[0]
    matrix.cycle_status(first.clause_id)
    assert first.responded is ResponseStatus.PARTIAL
    apply_offline_seed(matrix)
    matrix.lock()
    assert matrix.locked
    with pytest.raises(MatrixLocked):
        matrix.cycle_status(first.clause_id)


def test_vpn_brief_matrix_covers_must_optional_risk():
    brief = extract_brief(VPN_BRIEF_PATH.read_text(encoding="utf-8"))
    matrix = matrix_from_brief(brief)
    assert len(matrix.rows) >= 3
    assert all(row.clause.strip() and row.clause.strip() != "(none)" for row in matrix.rows)
    joined = "\n".join(row.clause for row in matrix.rows)
    assert "必须" in joined
    assert "可选" in joined
    assert "风险" in joined
    apply_offline_seed(matrix)
    assert all(row.status.value == "filled" for row in matrix.rows)


def test_tender_sample_still_extracts_disqualify_and_star():
    brief = extract_brief(bundled_sample_path().read_text(encoding="utf-8"))
    assert brief.disqualifiers
    assert any("废标" in d or "预算" in d or "860" in d for d in brief.disqualifiers)
    assert brief.starred_requirements
    assert any(item.startswith("5.") for item in brief.starred_requirements)
    matrix = matrix_from_brief(brief)
    cats = {row.category for row in matrix.rows}
    assert "starred" in cats
    assert "disqualifier" in cats
    assert any("★" in row.clause or row.clause.startswith("5.") for row in matrix.rows if row.category == "starred")


def test_locked_matrix_cannot_add_or_remove_clauses():
    text = bundled_sample_path().read_text(encoding="utf-8")
    matrix = matrix_from_brief(extract_brief(text))
    first = matrix.rows[0].clause_id
    matrix.lock()
    with pytest.raises(MatrixLocked):
        matrix.add_row(MatrixRow(clause_id="X99", clause="extra"))
    with pytest.raises(MatrixLocked):
        matrix.remove_row(first)
    assert first in {row.clause_id for row in matrix.rows}


def test_apply_draft_coverage_yes_partial_no_and_keeps_clause_ids():
    brief = extract_brief(VPN_BRIEF_PATH.read_text(encoding="utf-8"))
    matrix = matrix_from_brief(brief)
    matrix.lock()
    ids = [row.clause_id for row in matrix.rows]
    assert len(ids) == 5
    apply_draft_coverage(
        matrix,
        "# 稿\n## 延迟\n量化预期 RTT 改善与延迟优化方案\n\n弱提一句：验收项\n",
    )
    assert [row.clause_id for row in matrix.rows] == ids
    by_id = {row.clause_id: row for row in matrix.rows}
    assert by_id["S01"].responded is ResponseStatus.YES
    assert by_id["S01"].evidence_page
    assert by_id["R05"].responded is ResponseStatus.NO
    # "验收项" is a short token on R02 — at most partial, never a new clause
    assert by_id["R02"].responded in {ResponseStatus.NO, ResponseStatus.PARTIAL}
