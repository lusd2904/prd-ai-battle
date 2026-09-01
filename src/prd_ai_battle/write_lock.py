"""Write-lock: only the primary may touch the filesystem, and only after lock."""

from __future__ import annotations

from pathlib import Path

from prd_ai_battle.models import Phase
from prd_ai_battle.state import StateMachine


class WriteDenied(PermissionError):
    """Raised when an advisor — or an unlocked session — tries to write."""


class WriteLock:
    def __init__(self, primary_id: str) -> None:
        self.primary_id = primary_id

    def assert_can_write(self, actor_id: str, machine: StateMachine) -> None:
        if actor_id != self.primary_id:
            raise WriteDenied(f"{actor_id!r} is not the primary ({self.primary_id!r}); advisors have no write tools")
        if not machine.matrix_locked:
            raise WriteDenied("Compliance matrix is not locked; filesystem writes are forbidden")
        if machine.phase is Phase.DISCUSS or machine.phase is Phase.IDLE:
            raise WriteDenied(f"Filesystem writes are forbidden in phase {machine.phase.value}")
        if machine.phase not in {Phase.CONFIRM, Phase.REVIEW}:
            raise WriteDenied(f"Filesystem writes are forbidden in phase {machine.phase.value}")

    def tools_for(self, actor_id: str, machine: StateMachine) -> list[str]:
        """Advisors never see write tools, even after the matrix is locked."""
        if actor_id != self.primary_id:
            return []
        if machine.writes_allowed():
            return ["write_file"]
        return []


class ArtifactWriter:
    """The only object allowed to persist draft files."""

    def __init__(self, drafts_root: Path, lock: WriteLock, machine: StateMachine) -> None:
        self.drafts_root = drafts_root
        self.lock = lock
        self.machine = machine

    def write(self, actor_id: str, relative_path: str, content: str, *, version: int) -> Path:
        self.lock.assert_can_write(actor_id, self.machine)
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise WriteDenied("Draft path must be a relative file inside the version directory")
        dest = self.drafts_root / f"v{version}" / relative_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        self.machine.record_draft()
        return dest
