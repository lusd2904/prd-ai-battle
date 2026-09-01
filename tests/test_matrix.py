import pytest

from prd_ai_battle.ingest import extract_brief, bundled_sample_path
from prd_ai_battle.matrix import apply_offline_seed, matrix_from_brief
from prd_ai_battle.models import MatrixLocked, ResponseStatus


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
