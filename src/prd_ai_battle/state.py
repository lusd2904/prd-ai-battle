"""Discuss → confirm → review state machine.

Filesystem writes are forbidden until the user locks the compliance matrix
and only the designated primary may write afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prd_ai_battle.models import Phase


class IllegalTransition(RuntimeError):
    pass


# Allowed directed edges. IDLE is the pre-discuss ingest state.
TRANSITIONS: dict[Phase, frozenset[Phase]] = {
    Phase.IDLE: frozenset({Phase.DISCUSS}),
    Phase.DISCUSS: frozenset({Phase.CONFIRM}),
    Phase.CONFIRM: frozenset({Phase.REVIEW}),
    Phase.REVIEW: frozenset({Phase.CONFIRM, Phase.REVIEW}),
}


@dataclass
class StateMachine:
    phase: Phase = Phase.IDLE
    matrix_locked: bool = False
    has_brief: bool = False
    draft_count: int = 0
    history: list[tuple[Phase, Phase]] = field(default_factory=list)

    def can_advance(self, dest: Phase) -> bool:
        return dest in TRANSITIONS[self.phase]

    def advance(self, dest: Phase) -> Phase:
        if dest == self.phase and dest is Phase.REVIEW:
            self.history.append((self.phase, dest))
            return self.phase
        if not self.can_advance(dest):
            raise IllegalTransition(f"Cannot go {self.phase.value} → {dest.value}")
        if dest is Phase.DISCUSS and not self.has_brief:
            raise IllegalTransition("Cannot discuss without an extracted brief")
        if dest is Phase.CONFIRM and not self.matrix_locked:
            raise IllegalTransition("Cannot enter confirm until the matrix is locked")
        if dest is Phase.REVIEW and self.draft_count < 1:
            raise IllegalTransition("Cannot review until the primary has written a draft")
        previous = self.phase
        self.phase = dest
        self.history.append((previous, dest))
        return self.phase

    def lock_matrix(self) -> None:
        if self.phase is not Phase.DISCUSS:
            raise IllegalTransition(f"Matrix can only be locked from discuss (in {self.phase.value})")
        if not self.has_brief:
            raise IllegalTransition("Cannot lock an empty session — ingest a requirement first")
        self.matrix_locked = True
        self.advance(Phase.CONFIRM)

    def record_draft(self) -> None:
        if not self.matrix_locked:
            raise IllegalTransition("Primary cannot write until the matrix is locked")
        if self.phase not in {Phase.CONFIRM, Phase.REVIEW}:
            raise IllegalTransition(f"Writes are not allowed in phase {self.phase.value}")
        self.draft_count += 1

    def start_review(self) -> Phase:
        return self.advance(Phase.REVIEW)

    def writes_allowed(self) -> bool:
        return self.matrix_locked and self.phase in {Phase.CONFIRM, Phase.REVIEW}
