"""Headless phase driver used by OpenCode slash commands."""

from pathlib import Path

import pytest

from prd_ai_battle.cli import build_parser, cmd_phase, cmd_write_check
from prd_ai_battle.models import Phase
from prd_ai_battle.phase import cmd_discuss, cmd_execute, cmd_lock, cmd_review, cmd_revise, load_session
from prd_ai_battle.state import IllegalTransition


def test_phase_happy_path(tmp_path: Path):
    session = load_session(workspace=tmp_path, offline=True)
    discuss = cmd_discuss(session)
    assert discuss["phase"] == Phase.DISCUSS.value
    assert discuss["brief_markdown"]
    assert "目录" in discuss["brief_markdown"] or "Brief" in discuss["brief_markdown"]
    locked = cmd_lock(session)
    assert locked["phase"] == Phase.LOCKED.value
    assert locked["matrix_locked"] is True
    assert locked["writes_allowed_primary"] is False
    execute = cmd_execute(session)
    assert execute["phase"] == Phase.EXECUTE.value
    assert execute["writes_allowed_primary"] is True
    # Simulate the OpenCode primary write.
    draft = tmp_path / "drafts" / "v1" / "response.md"
    draft.parent.mkdir(parents=True)
    draft.write_text("# v1\n## 响应\nhello\n", encoding="utf-8")
    session.notice_external_write(draft, actor_id="primary")
    review = cmd_review(session)
    assert review["phase"] == Phase.REVIEW.value
    assert review["writes_allowed_primary"] is False
    assert "brief + matrix + chapter_diff" in review["review_packet"]
    assert "投标截止时间" not in review["review_packet"]
    packet_path = Path(review["review_packet_path"])
    assert packet_path.is_file()
    revise = cmd_revise(session)
    assert revise["phase"] == Phase.REVISE.value
    assert revise["writes_allowed_primary"] is True


def test_cannot_execute_before_lock(tmp_path: Path):
    session = load_session(workspace=tmp_path, offline=True)
    cmd_discuss(session)
    with pytest.raises(IllegalTransition):
        cmd_execute(session)


def test_cli_write_check_denies_advisor(tmp_path: Path, capsys):
    session = load_session(workspace=tmp_path, offline=True)
    cmd_discuss(session)
    cmd_lock(session)
    cmd_execute(session)
    args = build_parser().parse_args(
        [
            "write-check",
            "--actor",
            "advisor-sonnet",
            "--tool",
            "write",
            "--path",
            "sneaky.md",
            "--workspace",
            str(tmp_path),
            "--offline",
        ]
    )
    assert cmd_write_check(args) == 2
    out = capsys.readouterr().out
    assert '"ok": false' in out
    assert "tools: []" in out or "denied" in out.lower()


def test_cli_phase_status(tmp_path: Path, capsys):
    args = build_parser().parse_args(
        ["phase", "discuss", "--workspace", str(tmp_path), "--offline"]
    )
    assert cmd_phase(args) == 0
    out = capsys.readouterr().out
    assert '"phase": "discuss"' in out
    assert '"write_lock": true' in out
