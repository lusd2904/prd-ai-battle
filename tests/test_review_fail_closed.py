""" /review with no artifact or chapter_diff fails closed — Chinese error, no empty packet."""

from pathlib import Path

import pytest

from prd_ai_battle.cli import build_parser, cmd_phase
from prd_ai_battle.models import Phase
from prd_ai_battle.phase import cmd_discuss, cmd_execute, cmd_lock, cmd_review, load_session
from prd_ai_battle.session import (
    REVIEW_NO_ARTIFACT,
    REVIEW_NO_CHAPTER_DIFF,
    Session,
)
from prd_ai_battle.config import default_offline_config
from prd_ai_battle.state import IllegalTransition
from prd_ai_battle.bridge import review_packet_path


def _ready_for_execute(tmp_path: Path):
    session = load_session(workspace=tmp_path, offline=True)
    cmd_discuss(session)
    cmd_lock(session)
    cmd_execute(session)
    return session


def test_review_without_artifact_fails_closed_chinese(tmp_path: Path):
    session = _ready_for_execute(tmp_path)
    assert session.state.phase is Phase.EXECUTE
    with pytest.raises(IllegalTransition, match="空包|稿件|artifact"):
        cmd_review(session)
    assert session.state.phase is Phase.EXECUTE
    assert not review_packet_path(session.store.root).exists()
    with pytest.raises(IllegalTransition) as exc:
        session.build_review_packet()
    assert "审核失败" in str(exc.value)
    assert "空包" in str(exc.value)
    assert str(exc.value) == REVIEW_NO_ARTIFACT


def test_review_without_chapter_diff_fails_closed_chinese(tmp_path: Path):
    session = _ready_for_execute(tmp_path)
    v1 = tmp_path / "drafts" / "v1" / "response.md"
    v1.parent.mkdir(parents=True)
    body = "# v1\n## 响应\n同一正文\n"
    v1.write_text(body, encoding="utf-8")
    session.notice_external_write(v1, actor_id="primary")
    first = cmd_review(session)
    assert first["phase"] == Phase.REVIEW.value
    assert first["review_packet"]
    assert "chapter_diff" in first["review_packet"]
    from prd_ai_battle.phase import cmd_revise

    cmd_revise(session)
    v2 = tmp_path / "drafts" / "v2" / "response.md"
    v2.parent.mkdir(parents=True, exist_ok=True)
    v2.write_text(body, encoding="utf-8")
    session.notice_external_write(v2, actor_id="primary")
    prior_phase = session.state.phase
    with pytest.raises(IllegalTransition, match="chapter_diff|空包"):
        cmd_review(session)
    assert session.state.phase is prior_phase
    with pytest.raises(IllegalTransition) as exc:
        session.build_review_packet()
    assert str(exc.value) == REVIEW_NO_CHAPTER_DIFF


def test_cli_review_no_artifact_prints_chinese(tmp_path: Path, capsys):
    session = _ready_for_execute(tmp_path)
    session.persist()
    args = build_parser().parse_args(
        ["phase", "review", "--workspace", str(tmp_path), "--offline"]
    )
    assert cmd_phase(args) == 2
    err = capsys.readouterr().err
    assert "审核失败" in err
    assert "空包" in err
    assert "artifact" in err
    assert not review_packet_path(tmp_path).exists()


@pytest.mark.asyncio
async def test_session_review_without_draft_does_not_enter_review(tmp_path: Path):
    session = Session(default_offline_config(str(tmp_path)), root=tmp_path)
    session.load_sample()
    session.seed_matrix_offline()
    session.lock_matrix()
    session.begin_execute()
    with pytest.raises(IllegalTransition, match="审核失败"):
        async for _ in session.review():
            pass
    assert session.state.phase is Phase.EXECUTE
    assert not review_packet_path(session.store.root).exists()
