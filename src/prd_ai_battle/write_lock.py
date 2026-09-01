"""Write-lock: filesystem artifact writes only in execute|revise by primary."""

from __future__ import annotations

from pathlib import Path

from prd_ai_battle.models import WRITE_PHASES, SessionState, next_artifact_version
from prd_ai_battle.state import StateMachine


class WriteDenied(PermissionError):
    """Raised when an advisor — or a non-write phase — tries to write artifacts."""


class WriteLock:
    def __init__(self, state: SessionState) -> None:
        self.state = state

    def assert_can_write(self, actor_id: str, machine: StateMachine | None = None) -> None:
        state = machine.state if machine is not None else self.state
        if actor_id != state.primary:
            raise WriteDenied(
                f"{actor_id!r} is not the primary ({state.primary!r}); advisors always get tools: []"
            )
        if not state.write_lock:
            raise WriteDenied("write_lock is disabled in an unexpected way")
        if state.phase not in WRITE_PHASES:
            raise WriteDenied(
                f"Filesystem writes are forbidden in phase {state.phase.value} "
                f"(only {'/'.join(p.value for p in WRITE_PHASES)} + primary)"
            )
        if not state.allows_write(actor_id):
            raise WriteDenied(f"write_lock denied for {actor_id!r} in {state.phase.value}")

    def tools_for(self, actor_id: str, machine: StateMachine | None = None) -> list[str]:
        state = machine.state if machine is not None else self.state
        return state.tools_for(actor_id)


class ArtifactWriter:
    """The only object allowed to persist draft files."""

    def __init__(self, drafts_root: Path, lock: WriteLock, machine: StateMachine) -> None:
        self.drafts_root = drafts_root
        self.lock = lock
        self.machine = machine

    def write(self, actor_id: str, relative_path: str, content: str, *, version: int | None = None) -> Path:
        self.lock.assert_can_write(actor_id, self.machine)
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise WriteDenied("Draft path must be a relative file inside the version directory")
        if version is None:
            label = next_artifact_version(self.machine.state.artifact_version)
            version = int(label.lstrip("v"))
        else:
            label = f"v{version}"
        dest = self.drafts_root / label / relative_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        self.machine.record_draft(label)
        return dest
