"""Persist transcript, brief, matrix, and the SessionState contract."""

from __future__ import annotations

import os
from pathlib import Path

from prd_ai_battle.models import (
    Brief,
    ChatMessage,
    ComplianceMatrix,
    DraftVersion,
    SessionState,
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

    def init(self, state: SessionState | None = None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        if not self.transcript_path.exists():
            self.transcript_path.write_text("", encoding="utf-8")
        if not self.meta_path.exists() and state is not None:
            self.save_state(state)

    def save_requirement(self, text: str, source: str | None = None) -> Path:
        _ = source
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

    def append_message(self, message: ChatMessage, state: SessionState | None = None) -> None:
        """Append one jsonl line and fsync so a crash mid-discuss keeps the timeline."""
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with self.transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(message.model_dump_json() + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if state is not None:
            state.timeline.append(message)
            self.save_state(state)

    def sync_timeline(self, state: SessionState) -> list[ChatMessage]:
        """One ordered transcript. Prefer jsonl; keep session.json in lockstep."""
        messages = self.load_transcript()
        if messages:
            state.timeline = list(messages)
        elif state.timeline:
            self.transcript_path.write_text(
                "".join(m.model_dump_json() + "\n" for m in state.timeline),
                encoding="utf-8",
            )
            messages = list(state.timeline)
        return messages

    def load_transcript(self) -> list[ChatMessage]:
        if not self.transcript_path.exists():
            return []
        messages: list[ChatMessage] = []
        for line in self.transcript_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                messages.append(ChatMessage.model_validate_json(line))
        return messages

    def clear_timeline(self, state: SessionState | None = None) -> None:
        """Drop leftover discuss bubbles. New brief / --requirement starts clean."""
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        self.transcript_path.write_text("", encoding="utf-8")
        if state is not None:
            state.timeline = []
            self.save_state(state)

    def save_state(self, state: SessionState) -> None:
        state.bump()
        payload = state.model_dump_json(indent=2)
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        with self.meta_path.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())

    save_meta = save_state

    def load_state(self, fallback: SessionState) -> SessionState:
        if not self.meta_path.exists():
            return fallback
        return SessionState.model_validate_json(self.meta_path.read_text(encoding="utf-8"))

    def load_meta(self) -> SessionState:
        raise RuntimeError("load_meta requires a SessionState fallback — use load_state")

    def register_draft(self, state: SessionState, version: DraftVersion) -> None:
        state.draft_versions = [v for v in state.draft_versions if v.version != version.version]
        state.draft_versions.append(version)
        state.draft_versions.sort(key=lambda v: v.version)
        self.save_state(state)

    def draft_path(self, version: int | str, name: str = "response.md") -> Path:
        label = version if isinstance(version, str) and str(version).startswith("v") else f"v{version}"
        return self.drafts_dir / label / name

    def read_draft(self, version: int | str, name: str = "response.md") -> str:
        path = self.draft_path(version, name)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def latest_version(self) -> int:
        if not self.meta_path.exists():
            return 0
        state = SessionState.model_validate_json(self.meta_path.read_text(encoding="utf-8"))
        if state.artifact_version:
            return int(state.artifact_version.lstrip("v"))
        if not state.draft_versions:
            return 0
        return max(v.version for v in state.draft_versions)

    def dump_summary(self) -> dict:
        if not self.meta_path.exists():
            return {"root": str(self.root)}
        state = SessionState.model_validate_json(self.meta_path.read_text(encoding="utf-8"))
        return {
            "root": str(self.root),
            "phase": state.phase.value,
            "primary": state.primary,
            "advisors": state.advisors,
            "artifact_version": state.artifact_version,
            "write_lock": state.write_lock,
            "drafts": [v.model_dump() for v in state.draft_versions],
            "transcript_lines": sum(1 for _ in self.transcript_path.open(encoding="utf-8"))
            if self.transcript_path.exists()
            else 0,
            "updated_at": state.updated_at or iso_now(),
        }
