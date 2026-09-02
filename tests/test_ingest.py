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
