from pathlib import Path

import pytest

from prd_ai_battle.ingest import (
    IngestError,
    bundled_sample_path,
    extract_brief,
    load_requirement,
    pdf_to_text,
    read_requirement_text,
)
from prd_ai_battle.matrix import matrix_from_brief

from pdf_fixture import MINI_TENDER, write_text_pdf

VPN_BRIEF_PATH = Path(__file__).resolve().parent / "fixtures" / "vpn_latency_brief.md"


def test_extracts_toc_scores_and_disqualifiers():
    brief = extract_brief(bundled_sample_path().read_text(encoding="utf-8"), source_path="tender.md")
    assert "政务云" in brief.title
    assert brief.toc
    assert brief.scoring_points
    assert any(p.score == 12 for p in brief.scoring_points)
    assert brief.disqualifiers
    assert any("860" in d or "预算" in d for d in brief.disqualifiers)
    assert brief.starred_requirements
    assert all(s.startswith("5.") for s in brief.starred_requirements)
    assert not any("条款作出响应" in s for s in brief.starred_requirements)
    prompt = brief.as_prompt_block()
    assert "评分点" in prompt
    assert "废标项" in prompt


def test_pdf_to_text_roundtrip(tmp_path: Path):
    pdf = write_text_pdf(tmp_path / "mini.pdf", MINI_TENDER)
    assert pdf.stat().st_size < 8_000
    text = pdf_to_text(pdf)
    assert "政务云" in text
    assert "目录" in text
    assert "类似业绩" in text
    assert "★ 5.1" in text
    assert "%PDF" not in text


def test_ingest_pdf_reuses_brief_and_matrix(tmp_path: Path):
    pdf = write_text_pdf(tmp_path / "tender.pdf", MINI_TENDER)
    text, brief = load_requirement(pdf)
    assert "废标" in text
    assert "政务云" in brief.title
    assert brief.source_path.endswith("tender.pdf")
    assert any(p.score == 12 for p in brief.scoring_points)
    assert any("860" in d for d in brief.disqualifiers)
    assert any(s.startswith("5.1") for s in brief.starred_requirements)
    matrix = matrix_from_brief(brief)
    cats = {row.category for row in matrix.rows}
    assert {"starred", "scoring", "disqualifier"} <= cats


def test_ingest_still_accepts_markdown(tmp_path: Path):
    md = tmp_path / "tender.md"
    md.write_text(MINI_TENDER, encoding="utf-8")
    text, brief = load_requirement(md)
    assert text.startswith("#")
    assert "政务云" in brief.title
    assert brief.scoring_points


def test_vpn_brief_seeds_matrix_with_real_clauses():
    text = VPN_BRIEF_PATH.read_text(encoding="utf-8")
    brief = extract_brief(text, source_path=str(VPN_BRIEF_PATH))
    assert "VPN" in brief.title or "隧道" in brief.title
    matrix = matrix_from_brief(brief)
    rows = [row for row in matrix.rows if row.clause.strip() and row.clause.strip() != "(none)"]
    assert len(rows) >= 3
    joined = "\n".join(row.clause for row in rows)
    assert "必须" in joined
    assert "可选" in joined
    assert "风险" in joined
    assert all(row.clause.strip() not in {"(none)", "（无）", "无"} for row in matrix.rows)
    assert not any(row.clause.strip() == "(none)" for row in matrix.rows)
    prompt = brief.as_prompt_block()
    assert "需求条款" in prompt
    assert "(none)" not in "\n".join(row.clause for row in matrix.rows)


def test_vpn_heading_style_must_optional_risk():
    text = """# 需求：降低现网 VPN / 隧道延迟（只出方案，不改现网）

## 必须做
- 给出不改现网的延迟优化方案并量化 RTT。

## 可选
- 评估多路径选路，不作为验收项。

## 风险
- 误实施可能中断现网隧道。

## 约束
- 只出方案，不改现网。
"""
    matrix = matrix_from_brief(extract_brief(text))
    assert len(matrix.rows) >= 3
    joined = "\n".join(row.clause for row in matrix.rows)
    assert "必须" in joined
    assert "可选" in joined
    assert "风险" in joined
    assert all("(none)" not in row.clause for row in matrix.rows)


def test_placeholder_disqualifier_is_not_a_matrix_row():
    text = """# Brief: empty-ish

## 废标项
- (none)

## ★ 必须响应条款
- (none)

## 需求条款
- (none)
"""
    brief = extract_brief(text)
    assert brief.disqualifiers == []
    assert brief.starred_requirements == []
    matrix = matrix_from_brief(brief)
    assert not any(row.clause.strip() == "(none)" for row in matrix.rows)


def test_empty_pdf_raises(tmp_path: Path):
    pdf = write_text_pdf(tmp_path / "blank.pdf", "")
    with pytest.raises(IngestError, match="No extractable text"):
        pdf_to_text(pdf)


def test_unsupported_suffix(tmp_path: Path):
    docx = tmp_path / "tender.docx"
    docx.write_bytes(b"not a tender")
    with pytest.raises(IngestError, match="Unsupported"):
        read_requirement_text(docx)


def test_missing_file(tmp_path: Path):
    with pytest.raises(IngestError, match="not found"):
        read_requirement_text(tmp_path / "missing.pdf")
