"""Shared domain types: phases, brief, matrix, transcript, drafts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


class Phase(str, Enum):
    """Official three-phase machine plus a pre-discuss idle state."""

    IDLE = "idle"
    DISCUSS = "discuss"
    CONFIRM = "confirm"
    REVIEW = "review"


class ResponseStatus(str, Enum):
    """是否响应."""

    YES = "yes"
    PARTIAL = "partial"
    NO = "no"
    DEVIATION = "deviation"


class ScoringPoint(BaseModel):
    title: str
    score: float | None = None
    detail: str = ""


class Brief(BaseModel):
    """Shared extract — 目录 / 评分点 / 废标项. Never the full tender."""

    title: str
    toc: list[str] = Field(default_factory=list)
    scoring_points: list[ScoringPoint] = Field(default_factory=list)
    disqualifiers: list[str] = Field(default_factory=list)
    starred_requirements: list[str] = Field(default_factory=list)
    summary: str = ""
    source_path: str = ""
    extracted_at: str = Field(default_factory=iso_now)

    def as_prompt_block(self) -> str:
        toc = "\n".join(f"- {item}" for item in self.toc) or "- (none)"
        scores = "\n".join(
            f"- {p.title}" + (f" ({p.score}分)" if p.score is not None else "") + (f": {p.detail}" if p.detail else "")
            for p in self.scoring_points
        ) or "- (none)"
        disq = "\n".join(f"- {d}" for d in self.disqualifiers) or "- (none)"
        starred = "\n".join(f"- {s}" for s in self.starred_requirements) or "- (none)"
        return (
            f"# Brief: {self.title}\n\n"
            f"{self.summary}\n\n"
            f"## 目录\n{toc}\n\n"
            f"## 评分点\n{scores}\n\n"
            f"## 废标项\n{disq}\n\n"
            f"## ★ 必须响应条款\n{starred}\n"
        )


class MatrixRow(BaseModel):
    """条款 → 是否响应 → 证据页码 → 意见."""

    clause_id: str
    clause: str
    responded: ResponseStatus = ResponseStatus.NO
    evidence_page: str = ""
    comment: str = ""
    category: str = "requirement"

    def as_prompt_line(self) -> str:
        page = self.evidence_page or "-"
        return (
            f"| {self.clause_id} | {self.clause} | {self.responded.value} "
            f"| {page} | {self.comment or '-'} |"
        )


class ComplianceMatrix(BaseModel):
    """响应对照表. Locked by the user in the confirm phase."""

    title: str = "响应对照表"
    rows: list[MatrixRow] = Field(default_factory=list)
    locked: bool = False
    locked_at: str | None = None
    version: int = 1

    def lock(self) -> None:
        if self.locked:
            return
        self.locked = True
        self.locked_at = iso_now()

    def as_prompt_table(self) -> str:
        header = (
            f"# {self.title} (v{self.version}, "
            f"{'LOCKED' if self.locked else 'draft'})\n\n"
            "| 条款ID | 条款 | 是否响应 | 证据页码 | 意见 |\n"
            "| --- | --- | --- | --- | --- |\n"
        )
        body = "\n".join(r.as_prompt_line() for r in self.rows) or "| - | - | - | - | - |"
        return header + body + "\n"

    def cycle_status(self, clause_id: str) -> MatrixRow:
        if self.locked:
            raise MatrixLocked("Matrix is locked; status cannot change")
        order = [
            ResponseStatus.NO,
            ResponseStatus.PARTIAL,
            ResponseStatus.YES,
            ResponseStatus.DEVIATION,
        ]
        for row in self.rows:
            if row.clause_id == clause_id:
                row.responded = order[(order.index(row.responded) + 1) % len(order)]
                return row
        raise KeyError(clause_id)


class MatrixLocked(RuntimeError):
    pass


class ChatMessage(BaseModel):
    ts: str = Field(default_factory=iso_now)
    model_id: str
    role: str = "assistant"
    phase: Phase
    content: str
    done: bool = True

    def label(self) -> str:
        clock = self.ts[11:19] if len(self.ts) >= 19 else self.ts
        return f"{self.model_id} · {clock}"


class DraftVersion(BaseModel):
    version: int
    path: str
    created_at: str = Field(default_factory=iso_now)
    written_by: str
    note: str = ""


class SessionMeta(BaseModel):
    phase: Phase = Phase.IDLE
    requirement_path: str = ""
    created_at: str = Field(default_factory=iso_now)
    updated_at: str = Field(default_factory=iso_now)
    draft_versions: list[DraftVersion] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    def bump(self) -> None:
        self.updated_at = iso_now()


class SectionDiff(BaseModel):
    heading: str
    diff: str


class ReviewPacket(BaseModel):
    """The only context advisors receive in the review phase."""

    brief: Brief
    matrix: ComplianceMatrix
    diffs: list[SectionDiff] = Field(default_factory=list)
    version: int

    def as_prompt(self) -> str:
        diff_blocks = []
        for item in self.diffs:
            diff_blocks.append(f"### {item.heading}\n```diff\n{item.diff}\n```")
        diffs = "\n\n".join(diff_blocks) or "(no textual diff — empty previous version)"
        return (
            "You are reviewing a draft. You are given ONLY the original brief, "
            "the locked compliance matrix, and chapter/section diffs. "
            "You do not have repository access.\n\n"
            f"{self.brief.as_prompt_block()}\n"
            f"{self.matrix.as_prompt_table()}\n"
            f"## Chapter diffs (v{self.version})\n{diffs}\n"
        )
