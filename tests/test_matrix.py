from pathlib import Path

import pytest

from prd_ai_battle.ingest import extract_brief, bundled_sample_path
from prd_ai_battle.matrix import apply_offline_seed, matrix_from_brief
from prd_ai_battle.models import MatrixLocked, ResponseStatus

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
