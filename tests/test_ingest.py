from prd_ai_battle.ingest import bundled_sample_path, extract_brief


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
