"""Offline export: missing draft vs present draft. No network."""

from pathlib import Path

from prd_ai_battle.config import default_offline_config
from prd_ai_battle.export import (
    BODY_NAME,
    MATRIX_NAME,
    MISSING_BODY,
    SESSION_NAME,
    TRANSCRIPT_NAME,
    export_deliverable,
)
from prd_ai_battle.llm import MockChatClient
from prd_ai_battle.session import Session, run_offline_pipeline


def test_export_missing_draft(tmp_path: Path):
    ws = tmp_path / "ws"
    session = Session(default_offline_config(str(ws)), root=ws)
    session.client = MockChatClient(delay_s=0.0)
    session.load_sample()
    dest_parent = tmp_path / "exports"
    payload = export_deliverable(session, dest_parent=dest_parent)
    folder = Path(payload["path"])
    assert payload["draft_present"] is False
    assert folder.is_dir()
    assert folder.parent == dest_parent
    body = (folder / BODY_NAME).read_text(encoding="utf-8")
    assert body == MISSING_BODY
    assert "尚无" in body
    matrix = (folder / MATRIX_NAME).read_text(encoding="utf-8")
    assert "响应对照表" in matrix
    assert (folder / TRANSCRIPT_NAME).is_file()
    assert (folder / SESSION_NAME).is_file()
    session_json = (folder / SESSION_NAME).read_text(encoding="utf-8")
    assert "write_lock" in session_json
    assert not (folder / "teammates").exists()


def test_export_present_draft(tmp_path: Path):
    ws = tmp_path / "pipe"
    import asyncio

    asyncio.run(run_offline_pipeline(ws))
    session = Session(default_offline_config(str(ws)), root=ws)
    payload = export_deliverable(session, dest_parent=tmp_path / "out")
    assert payload["draft_present"] is True
    folder = Path(payload["path"])
    body = (folder / BODY_NAME).read_text(encoding="utf-8")
    assert body.strip()
    assert "尚无" not in body
    assert "投标" in body or "响应" in body
    assert (folder / MATRIX_NAME).read_text(encoding="utf-8")
    assert (folder / TRANSCRIPT_NAME).read_text(encoding="utf-8")
    assert (folder / SESSION_NAME).is_file()
