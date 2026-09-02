"""Offline export of the bid deliverable. No network."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from prd_ai_battle.models import utc_now
from prd_ai_battle.session import Session

BODY_NAME = "标书正文.md"
MATRIX_NAME = "响应对照表.md"
TRANSCRIPT_NAME = "transcript.jsonl"
SESSION_NAME = "session.json"

MISSING_BODY = "（尚无标书正文 — 执行阶段尚未写出稿。）\n"


def dated_folder_name(when: datetime | None = None) -> str:
    stamp = when or utc_now()
    return stamp.strftime("%Y%m%d-%H%M%S")


def export_deliverable(
    session: Session,
    *,
    dest_parent: Path | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Write a dated folder: 标书正文, 响应对照表, transcript, session snapshot.

    Missing draft still produces the folder (正文 notes 尚无). Never hits the network.
    """
    stamp = when or utc_now()
    parent = Path(dest_parent) if dest_parent is not None else session.store.root / "exports"
    folder = parent / dated_folder_name(stamp)
    folder.mkdir(parents=True, exist_ok=True)

    version = session.store.latest_version()
    draft = session.store.read_draft(version) if version >= 1 else ""
    draft_present = bool(draft.strip())
    body_path = folder / BODY_NAME
    body_path.write_text(draft if draft_present else MISSING_BODY, encoding="utf-8")

    matrix_path = folder / MATRIX_NAME
    matrix_path.write_text(session.matrix.as_prompt_table(), encoding="utf-8")

    transcript_src = session.store.transcript_path
    transcript_dest = folder / TRANSCRIPT_NAME
    if transcript_src.is_file():
        shutil.copyfile(transcript_src, transcript_dest)
    else:
        transcript_dest.write_text("", encoding="utf-8")

    session.persist()
    session_src = session.store.meta_path
    session_dest = folder / SESSION_NAME
    if session_src.is_file():
        shutil.copyfile(session_src, session_dest)
    else:
        session_dest.write_text(session.state.model_dump_json(indent=2), encoding="utf-8")

    return {
        "ok": True,
        "path": str(folder),
        "draft_present": draft_present,
        "artifact_version": session.state.artifact_version or "",
        "phase": session.state.phase.value,
        "files": {
            "标书正文": str(body_path),
            "响应对照表": str(matrix_path),
            "transcript": str(transcript_dest),
            "session": str(session_dest),
        },
    }


__all__ = [
    "BODY_NAME",
    "MATRIX_NAME",
    "MISSING_BODY",
    "SESSION_NAME",
    "TRANSCRIPT_NAME",
    "dated_folder_name",
    "export_deliverable",
]
