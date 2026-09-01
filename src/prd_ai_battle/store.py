"""Persist transcript, brief, matrix, and draft versions under a workspace dir."""

from __future__ import annotations

import json
from pathlib import Path

from prd_ai_battle.models import (
    Brief,
    ChatMessage,
    ComplianceMatrix,
    DraftVersion,
    SessionMeta,
    iso_now,
)


class WorkspaceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.transcript_path = root / "transcript.jsonl"
        self.brief_path = root / "brief.json"
        self.brief_md_path = root / "brief.md"
        self.matrix_path = root / "matrix.json"
        self.requirement_path = root / "requirement.md"
        self.meta_path = root / "session.json"
        self.drafts_dir = root / "drafts"

    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        if not self.transcript_path.exists():
            self.transcript_path.write_text("", encoding="utf-8")
        if not self.meta_path.exists():
            self.save_meta(SessionMeta())

    def save_requirement(self, text: str, source: str | None = None) -> Path:
        self.requirement_path.write_text(text, encoding="utf-8")
        return self.requirement_path

    def save_brief(self, brief: Brief) -> None:
        self.brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
        self.brief_md_path.write_text(brief.as_prompt_block(), encoding="utf-8")

    def load_brief(self) -> Brief | None:
        if not self.brief_path.exists():
            return None
        return Brief.model_validate_json(self.brief_path.read_text(encoding="utf-8"))

    def save_matrix(self, matrix: ComplianceMatrix) -> None:
        self.matrix_path.write_text(matrix.model_dump_json(indent=2), encoding="utf-8")

    def load_matrix(self) -> ComplianceMatrix | None:
        if not self.matrix_path.exists():
            return None
        return ComplianceMatrix.model_validate_json(self.matrix_path.read_text(encoding="utf-8"))

    def append_message(self, message: ChatMessage) -> None:
        with self.transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(message.model_dump_json() + "\n")

    def load_transcript(self) -> list[ChatMessage]:
        if not self.transcript_path.exists():
            return []
        messages: list[ChatMessage] = []
        for line in self.transcript_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                messages.append(ChatMessage.model_validate_json(line))
        return messages

    def save_meta(self, meta: SessionMeta) -> None:
        meta.bump()
        self.meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    def load_meta(self) -> SessionMeta:
        if not self.meta_path.exists():
            return SessionMeta()
        return SessionMeta.model_validate_json(self.meta_path.read_text(encoding="utf-8"))

    def register_draft(self, meta: SessionMeta, version: DraftVersion) -> None:
        meta.draft_versions = [v for v in meta.draft_versions if v.version != version.version]
        meta.draft_versions.append(version)
        meta.draft_versions.sort(key=lambda v: v.version)
        self.save_meta(meta)

    def draft_path(self, version: int, name: str = "response.md") -> Path:
        return self.drafts_dir / f"v{version}" / name

    def read_draft(self, version: int, name: str = "response.md") -> str:
        path = self.draft_path(version, name)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def latest_version(self) -> int:
        meta = self.load_meta()
        if not meta.draft_versions:
            return 0
        return max(v.version for v in meta.draft_versions)

    def dump_summary(self) -> dict:
        meta = self.load_meta()
        return {
            "root": str(self.root),
            "phase": meta.phase.value,
            "drafts": [v.model_dump() for v in meta.draft_versions],
            "transcript_lines": sum(1 for _ in self.transcript_path.open(encoding="utf-8"))
            if self.transcript_path.exists()
            else 0,
            "updated_at": meta.updated_at or iso_now(),
        }
