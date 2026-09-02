"""Product-team session contract: phases, brief, matrix, review packet."""

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
    """Required product phases — no idle/confirm aliases."""

    DISCUSS = "discuss"
    LOCKED = "locked"
    EXECUTE = "execute"
    REVIEW = "review"
    REVISE = "revise"


WRITE_PHASES: frozenset[Phase] = frozenset({Phase.EXECUTE, Phase.REVISE})


class ResponseStatus(str, Enum):
    """是否响应 (responded)."""

    YES = "yes"
    PARTIAL = "partial"
    NO = "no"
    DEVIATION = "deviation"


class RowStatus(str, Enum):
    """状态 (status) — row lifecycle, distinct from 是否响应."""

    OPEN = "open"
    FILLED = "filled"
    LOCKED = "locked"


class ScoringPoint(BaseModel):
    title: str
    score: float | None = None
    detail: str = ""


class RequirementClause(BaseModel):
    """A non-tender requirement line (必须 / 可选 / 风险 / 约束 / …)."""

    kind: str
    text: str


class Brief(BaseModel):
    """Shared extract — 目录 / 评分点 / 废标项 / 需求条款. Never the raw file."""

    title: str
    toc: list[str] = Field(default_factory=list)
    scoring_points: list[ScoringPoint] = Field(default_factory=list)
    disqualifiers: list[str] = Field(default_factory=list)
    starred_requirements: list[str] = Field(default_factory=list)
    requirement_clauses: list[RequirementClause] = Field(default_factory=list)
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
        reqs = "\n".join(f"- {c.text}" for c in self.requirement_clauses) or "- (none)"
        return (
            f"# Brief: {self.title}\n\n"
            f"{self.summary}\n\n"
            f"## 目录\n{toc}\n\n"
            f"## 评分点\n{scores}\n\n"
            f"## 废标项\n{disq}\n\n"
            f"## ★ 必须响应条款\n{starred}\n\n"
            f"## 需求条款\n{reqs}\n"
        )


class MatrixRow(BaseModel):
    """条款 / 是否响应 / 证据页码 / 意见 / 状态."""

    clause_id: str
    clause: str
    responded: ResponseStatus = ResponseStatus.NO
    evidence_page: str = ""
    opinion: str = ""
    status: RowStatus = RowStatus.OPEN
    category: str = "requirement"

    def as_prompt_line(self) -> str:
        page = self.evidence_page or "-"
        return (
            f"| {self.clause_id} | {self.clause} | {self.responded.value} "
            f"| {page} | {self.opinion or '-'} | {self.status.value} |"
        )


class ComplianceMatrix(BaseModel):
    """响应对照表. User locks it to enter phase=locked."""

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
        for row in self.rows:
            row.status = RowStatus.LOCKED

    def as_prompt_table(self) -> str:
        header = (
            f"# {self.title} (v{self.version}, "
            f"{'LOCKED' if self.locked else 'draft'})\n\n"
            "| 条款ID | 条款 | 是否响应 | 证据页码 | 意见 | 状态 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
        )
        body = "\n".join(r.as_prompt_line() for r in self.rows) or "| - | - | - | - | - | - |"
        return header + body + "\n"

    def add_row(self, row: MatrixRow) -> MatrixRow:
        """Discuss-only. After /lock the clause list cannot grow."""
        if self.locked:
            raise MatrixLocked("Locked 对照表 cannot add clauses")
        self.rows.append(row)
        return row

    def remove_row(self, clause_id: str) -> MatrixRow:
        """Discuss-only. After /lock the clause list cannot shrink."""
        if self.locked:
            raise MatrixLocked("Locked 对照表 cannot remove clauses")
        for index, row in enumerate(self.rows):
            if row.clause_id == clause_id:
                return self.rows.pop(index)
        raise KeyError(clause_id)

    def cycle_status(self, clause_id: str) -> MatrixRow:
        """User click-cycle during discuss. After /lock use apply_response instead."""
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
                row.status = RowStatus.FILLED if row.responded is not ResponseStatus.NO else RowStatus.OPEN
                return row
        raise KeyError(clause_id)

    def apply_response(
        self,
        clause_id: str,
        *,
        responded: ResponseStatus,
        evidence_page: str = "",
        opinion: str = "",
    ) -> MatrixRow:
        """Update 是否响应 / 证据 / 意见 on an existing row. Never add/remove clauses."""
        for row in self.rows:
            if row.clause_id == clause_id:
                row.responded = responded
                row.evidence_page = evidence_page
                row.opinion = opinion
                if not self.locked:
                    row.status = (
                        RowStatus.FILLED if responded is not ResponseStatus.NO else RowStatus.OPEN
                    )
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
        return speaker_label(self.model_id, self.ts)

    def as_bubble(self) -> str:
        return f"[{self.label()}]\n{self.content}".rstrip()


def speaker_label(model_id: str, ts: str | None = None) -> str:
    """Product bubble header: agent id + timestamp. Ids come from yaml, not seed names."""
    stamp = ts or iso_now()
    clock = stamp[11:19] if len(stamp) >= 19 else stamp
    return f"{model_id} · {clock}"


def render_timeline(messages: list[ChatMessage]) -> str:
    """One shared chat: an ordered list of labeled utterances. No teammate sessions."""
    if not messages:
        return ""
    return "\n\n".join(m.as_bubble() for m in messages) + "\n"


def timeline_prompt_block(messages: list[ChatMessage]) -> str:
    """Prior utterances other speakers already put on the shared timeline."""
    body = render_timeline(messages).strip()
    if not body:
        return ""
    return (
        "## Shared discuss timeline\n"
        "This is one chat. Each bubble is labeled `[agent-id · timestamp]`. "
        "Reply in this same thread. Do not open a side conversation.\n\n"
        f"{body}\n"
    )


class DraftVersion(BaseModel):
    version: int
    path: str
    created_at: str = Field(default_factory=iso_now)
    written_by: str
    note: str = ""


class SectionDiff(BaseModel):
    heading: str
    diff: str


class ReviewPacket(BaseModel):
    """Review-phase model input: ONLY brief + matrix + chapter_diff."""

    brief: Brief
    matrix: ComplianceMatrix
    chapter_diff: list[SectionDiff] = Field(default_factory=list)

    def as_prompt(self) -> str:
        diff_blocks = []
        for item in self.chapter_diff:
            diff_blocks.append(f"### {item.heading}\n```diff\n{item.diff}\n```")
        diffs = "\n\n".join(diff_blocks) or "(empty previous version)"
        return (
            "Review-phase input is strictly limited to brief + matrix + chapter_diff. "
            "You do not have repository access. You do not receive the raw tender.\n\n"
            f"{self.brief.as_prompt_block()}\n"
            f"{self.matrix.as_prompt_table()}\n"
            f"## chapter_diff\n{diffs}\n"
        )

    def allowed_keys(self) -> tuple[str, ...]:
        return ("brief", "matrix", "chapter_diff")


def format_artifact_version(n: int) -> str:
    if n < 1:
        return ""
    return f"v{n}"


def next_artifact_version(current: str) -> str:
    if not current:
        return "v1"
    return f"v{int(current.lstrip('v')) + 1}"


class SessionState(BaseModel):
    """Required product session fields — persisted as session.json."""

    phase: Phase = Phase.DISCUSS
    primary: str
    advisors: list[str]
    brief: Brief | None = None
    matrix: ComplianceMatrix = Field(default_factory=ComplianceMatrix)
    artifact_version: str = ""
    write_lock: bool = True
    requirement_path: str = ""
    created_at: str = Field(default_factory=iso_now)
    updated_at: str = Field(default_factory=iso_now)
    draft_versions: list[DraftVersion] = Field(default_factory=list)
    timeline: list[ChatMessage] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    def bump(self) -> None:
        self.updated_at = iso_now()

    def allows_write(self, actor_id: str) -> bool:
        """Filesystem artifact writes: execute|revise AND actor is primary."""
        actor = (actor_id or "").strip()
        if not actor or actor == "unknown":
            return False
        return bool(
            self.write_lock
            and self.phase in WRITE_PHASES
            and actor == self.primary
        )

    def tools_for(self, actor_id: str) -> list[str]:
        """Advisors always get tools: []. Primary gets write_file only in write phases."""
        actor = (actor_id or "").strip()
        if not actor or actor == "unknown" or actor != self.primary:
            return []
        if self.allows_write(actor):
            return ["write_file"]
        return []

    def contract_view(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "primary": self.primary,
            "advisors": list(self.advisors),
            "brief": None if self.brief is None else self.brief.summary,
            "matrix": {
                "title": self.matrix.title,
                "locked": self.matrix.locked,
                "rows": [r.model_dump() for r in self.matrix.rows],
            },
            "artifact_version": self.artifact_version,
            "write_lock": self.write_lock,
        }


# Back-compat alias used by older store helpers in this scaffold.
SessionMeta = SessionState
