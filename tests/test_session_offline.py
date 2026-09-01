from pathlib import Path

import pytest

from prd_ai_battle.config import default_offline_config, expand_env, load_config
from prd_ai_battle.models import Phase
from prd_ai_battle.session import Session, run_offline_pipeline
from prd_ai_battle.write_lock import WriteDenied


@pytest.mark.asyncio
async def test_offline_pipeline(tmp_path: Path):
    result = await run_offline_pipeline(tmp_path / "ws")
    assert result["phase"] == Phase.REVIEW.value
    assert result["matrix_locked"] is True
    assert "primary" in result["discuss_models"]
    assert "advisor-a" in result["discuss_models"]
    assert "primary" not in result["review_models"]
    assert Path(result["v1"]).is_file()
    assert Path(result["v2"]).is_file()
    assert Path(result["v1"]).read_text(encoding="utf-8")
    transcript = Path(result["transcript"]).read_text(encoding="utf-8")
    assert "primary" in transcript
    assert "advisor-a" in transcript


@pytest.mark.asyncio
async def test_review_packet_has_no_repo_dump(tmp_path: Path):
    session = Session(default_offline_config(str(tmp_path)), root=tmp_path)
    session.client.delay_s = 0.0  # type: ignore[attr-defined]
    session.load_sample()
    session.seed_matrix_offline()
    async for _ in session.discuss():
        pass
    session.lock_matrix()
    await session.execute_primary()
    packet = session.build_review_packet()
    prompt = packet.as_prompt()
    assert "You do not have repository access" in prompt
    assert "Chapter diffs" in prompt
    assert "drafts/" not in prompt
    assert "__pycache__" not in prompt
    assert "投标截止时间" not in prompt  # raw tender body stays out; only the brief is shared


@pytest.mark.asyncio
async def test_advisor_cannot_write_via_session(tmp_path: Path):
    session = Session(default_offline_config(str(tmp_path)), root=tmp_path)
    session.load_sample()
    session.seed_matrix_offline()
    session.enter_discuss()
    session.lock_matrix()
    with pytest.raises(WriteDenied):
        session.advisor_try_write("advisor-a", "pwned")


def test_expand_env(monkeypatch):
    monkeypatch.setenv("FOO_URL", "https://example.test/v1")
    assert expand_env("${FOO_URL}") == "https://example.test/v1"
    assert expand_env("${MISSING:-http://fallback}") == "http://fallback"


def test_load_example_config(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    src = Path("config.example.yaml")
    cfg = load_config(src, offline=True)
    assert cfg.primary.id == "primary"
    assert cfg.advisors
    assert cfg.primary.base_url.endswith("/v1")
