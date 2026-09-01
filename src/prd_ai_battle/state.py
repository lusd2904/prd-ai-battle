"""discuss → locked → execute → review → revise.

Artifact filesystem writes are allowed only in execute|revise by primary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prd_ai_battle.models import WRITE_PHASES, Phase, SessionState


class IllegalTransition(RuntimeError):
    pass


TRANSITIONS: dict[Phase, frozenset[Phase]] = {
    Phase.DISCUSS: frozenset({Phase.LOCKED}),
    Phase.LOCKED: frozenset({Phase.EXECUTE}),
    Phase.EXECUTE: frozenset({Phase.REVIEW}),
    Phase.REVIEW: frozenset({Phase.REVISE}),
    Phase.REVISE: frozenset({Phase.REVIEW}),
}


@dataclass
class StateMachine:
    state: SessionState
    history: list[tuple[Phase, Phase]] = field(default_factory=list)

    @property
    def phase(self) -> Phase:
        return self.state.phase

    @property
    def primary(self) -> str:
        return self.state.primary

    @property
    def advisors(self) -> list[str]:
        return list(self.state.advisors)

    @property
    def has_brief(self) -> bool:
        return self.state.brief is not None

    @property
    def matrix_locked(self) -> bool:
        return self.state.matrix.locked

    @property
    def artifact_version(self) -> str:
        return self.state.artifact_version

    def can_advance(self, dest: Phase) -> bool:
        return dest in TRANSITIONS[self.phase]

    def advance(self, dest: Phase) -> Phase:
        if not self.can_advance(dest):
            raise IllegalTransition(f"Cannot go {self.phase.value} → {dest.value}")
        if dest is Phase.LOCKED and not self.has_brief:
            raise IllegalTransition("Cannot lock without an extracted brief")
        if dest is Phase.EXECUTE and not self.state.matrix.locked:
            raise IllegalTransition("Cannot execute until the matrix is locked")
        if dest is Phase.REVIEW and not self.state.artifact_version:
            raise IllegalTransition("Cannot review until the primary has written a draft")
        previous = self.phase
        self.state.phase = dest
        self.history.append((previous, dest))
        return self.phase

    def enter_discuss(self) -> Phase:
        if not self.has_brief:
            raise IllegalTransition("Cannot discuss without an extracted brief")
        if self.phase is not Phase.DISCUSS:
            raise IllegalTransition(f"Discuss is only valid at the start (in {self.phase.value})")
        return self.phase

    def lock_matrix(self) -> Phase:
        if self.phase is not Phase.DISCUSS:
            raise IllegalTransition(f"Matrix can only be locked from discuss (in {self.phase.value})")
        if not self.has_brief:
            raise IllegalTransition("Cannot lock an empty session — ingest a requirement first")
        if not self.state.matrix.rows:
            raise IllegalTransition("Cannot lock an empty 对照表")
        self.state.matrix.lock()
        return self.advance(Phase.LOCKED)

    def enter_execute(self) -> Phase:
        if self.phase is Phase.EXECUTE:
            return self.phase
        return self.advance(Phase.EXECUTE)

    def enter_review(self) -> Phase:
        return self.advance(Phase.REVIEW)

    def enter_revise(self) -> Phase:
        if self.phase is Phase.REVISE:
            return self.phase
        return self.advance(Phase.REVISE)

    def record_draft(self, version: str) -> None:
        if not self.state.allows_write(self.state.primary):
            raise IllegalTransition(f"Writes are not allowed in phase {self.phase.value}")
        self.state.artifact_version = version

    def writes_allowed(self, actor_id: str | None = None) -> bool:
        actor = actor_id if actor_id is not None else self.state.primary
        return self.state.allows_write(actor)

    def tools_for(self, actor_id: str) -> list[str]:
        return self.state.tools_for(actor_id)
