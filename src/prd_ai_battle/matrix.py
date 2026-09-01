"""Build a 响应对照表 from an extracted brief."""

from __future__ import annotations

from prd_ai_battle.models import Brief, ComplianceMatrix, MatrixRow, ResponseStatus


def matrix_from_brief(brief: Brief) -> ComplianceMatrix:
    rows: list[MatrixRow] = []
    n = 1
    for item in brief.starred_requirements:
        rows.append(
            MatrixRow(
                clause_id=f"S{n:02d}",
                clause=item,
                responded=ResponseStatus.NO,
                category="starred",
            )
        )
        n += 1
    for point in brief.scoring_points:
        label = point.title if point.score is None else f"{point.title}（{point.score:g}分）"
        rows.append(
            MatrixRow(
                clause_id=f"P{n:02d}",
                clause=label,
                responded=ResponseStatus.NO,
                category="scoring",
            )
        )
        n += 1
    for item in brief.disqualifiers:
        rows.append(
            MatrixRow(
                clause_id=f"D{n:02d}",
                clause=item,
                responded=ResponseStatus.NO,
                category="disqualifier",
                comment="Must not trigger 废标",
            )
        )
        n += 1
    return ComplianceMatrix(title=f"响应对照表 · {brief.title}", rows=rows)


def apply_offline_seed(matrix: ComplianceMatrix) -> None:
    """Fill a plausible first-pass response so the demo can lock immediately."""
    if matrix.locked:
        return
    for row in matrix.rows:
        if row.category == "disqualifier":
            row.responded = ResponseStatus.YES
            row.evidence_page = "封皮 / 投标函"
            row.comment = "密封、报价、认证、有效期均按须知执行"
        elif row.category == "starred":
            row.responded = ResponseStatus.YES
            row.evidence_page = "技术方案 ch.5"
            row.comment = "★ 条款在实施方案中逐条响应"
        else:
            row.responded = ResponseStatus.PARTIAL
            row.evidence_page = "商务 / 技术分册"
            row.comment = "评分点已列提纲，待一次稿补证据"
