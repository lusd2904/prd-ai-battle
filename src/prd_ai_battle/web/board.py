"""Read-only snapshots of `.prd-ai-battle` workspace files. Never writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prd_ai_battle.models import ChatMessage, SessionState, speaker_label
from prd_ai_battle.projects import (
    CATALOG_NAME,
    DEFAULT_PROJECT_NAME,
    ProjectRecord,
    discover_named_workspaces,
    peek_workspace_dir,
    peek_workspace_state,
)
from prd_ai_battle.store import WorkspaceStore
from prd_ai_battle.tui.skin import PHASE_LABELS_ZH, matrix_lock_label, speaker_color, speaker_display_name

MATRIX_COLUMNS = ["条款", "是否响应", "证据页码", "意见", "状态"]
PHASE_ORDER = tuple(PHASE_LABELS_ZH.keys())


def _read_state(workspace: Path) -> SessionState | None:
    store = WorkspaceStore(Path(workspace))
    if not store.meta_path.is_file():
        return None
    try:
        return SessionState.model_validate_json(store.meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _messages(workspace: Path, state: SessionState | None) -> list[ChatMessage]:
    store = WorkspaceStore(Path(workspace))
    try:
        messages = store.load_transcript()
    except (OSError, ValueError):
        messages = []
    if messages:
        return messages
    if state is not None and state.timeline:
        return list(state.timeline)
    return []


def _matrix_from(workspace: Path, state: SessionState | None):
    if state is not None:
        return state.matrix
    store = WorkspaceStore(Path(workspace))
    try:
        loaded = store.load_matrix()
    except (OSError, ValueError):
        return None
    return loaded


def _latest_draft(workspace: Path, state: SessionState | None) -> tuple[str, str]:
    store = WorkspaceStore(Path(workspace))
    label = ""
    if state is not None and state.artifact_version:
        label = state.artifact_version
        text = store.read_draft(label)
        if text:
            return label, text
    if store.drafts_dir.is_dir():
        versions: list[int] = []
        for child in store.drafts_dir.iterdir():
            if child.is_dir() and child.name.startswith("v"):
                try:
                    versions.append(int(child.name[1:]))
                except ValueError:
                    continue
        if versions:
            n = max(versions)
            return f"v{n}", store.read_draft(n)
    n = store.latest_version()
    if n:
        return f"v{n}", store.read_draft(n)
    return "", ""


def matrix_payload(workspace: Path) -> dict[str, Any]:
    """对照表 JSON. Columns frozen: 条款 / 是否响应 / 证据页码 / 意见 / 状态."""
    root = Path(workspace)
    state = _read_state(root)
    matrix = _matrix_from(root, state)
    locked = bool(matrix.locked) if matrix is not None else False
    phase = state.phase.value if state is not None else "discuss"
    rows: list[dict[str, Any]] = []
    title = "响应对照表"
    if matrix is not None:
        title = matrix.title
        for row in matrix.rows:
            rows.append(
                {
                    "clause_id": row.clause_id,
                    "clause": row.clause,
                    "responded": row.responded.value,
                    "evidence_page": row.evidence_page,
                    "opinion": row.opinion,
                    "status": row.status.value,
                }
            )
    return {
        "title": title,
        "columns": list(MATRIX_COLUMNS),
        "rows": rows,
        "locked": locked,
        "lock_label": matrix_lock_label(locked),
        "editable": False if locked else phase == "discuss",
        "phase": phase,
    }


def timeline_payload(workspace: Path) -> dict[str, Any]:
    """Labeled timeline JSON: `[agent-id · timestamp]` plus body."""
    root = Path(workspace)
    state = _read_state(root)
    primary = state.primary if state is not None else "primary"
    advisors = list(state.advisors) if state is not None else []
    messages = []
    for msg in _messages(root, state):
        messages.append(
            {
                "model_id": msg.model_id,
                "role": msg.role,
                "phase": msg.phase.value,
                "ts": msg.ts,
                "label": msg.label() if hasattr(msg, "label") else speaker_label(msg.model_id, msg.ts),
                "display_name": speaker_display_name(msg.model_id, primary_id=primary),
                "color": speaker_color(msg.model_id, primary_id=primary, advisor_ids=advisors),
                "content": msg.content,
                "done": msg.done,
            }
        )
    return {"messages": messages}


def draft_payload(workspace: Path) -> dict[str, Any]:
    root = Path(workspace)
    state = _read_state(root)
    version, text = _latest_draft(root, state)
    return {"version": version, "content": text, "present": bool(text)}


def phase_rail_payload(workspace: Path) -> dict[str, Any]:
    root = Path(workspace)
    state = _read_state(root)
    current = state.phase.value if state is not None else "discuss"
    steps = []
    for phase in PHASE_ORDER:
        steps.append(
            {
                "id": phase.value,
                "label": PHASE_LABELS_ZH[phase],
                "current": phase.value == current,
            }
        )
    write_lock = True if state is None else bool(state.write_lock)
    primary = state.primary if state is not None else ""
    return {
        "phase": current,
        "label": PHASE_LABELS_ZH.get(state.phase, current) if state is not None else "讨论",
        "steps": steps,
        "write_lock": write_lock,
        "primary": primary,
        "matrix_locked": bool(state.matrix.locked) if state is not None else False,
    }


def _catalog_projects(search_root: Path) -> list[ProjectRecord]:
    found: list[ProjectRecord] = []
    candidates = [
        Path(search_root) / ".prd-ai-battle-board" / CATALOG_NAME,
        Path(search_root) / CATALOG_NAME,
    ]
    ws = Path(search_root)
    if ws.name != ".prd-ai-battle-board":
        candidates.append(ws / ".prd-ai-battle-board" / CATALOG_NAME)
    seen: set[str] = set()
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in raw.get("projects") or []:
            try:
                rec = ProjectRecord.from_dict(item)
            except (KeyError, TypeError):
                continue
            key = str(Path(rec.workspace).resolve()) if Path(rec.workspace).exists() else rec.id
            if key in seen:
                continue
            seen.add(key)
            found.append(rec)
    return found


def list_projects(workspace: Path, search_root: Path | None = None) -> list[dict[str, Any]]:
    """Read-only project list. Does not create a catalog or Session."""
    default_ws = Path(workspace)
    search = Path(search_root) if search_root is not None else default_ws.parent
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(pid: str, name: str, ws: Path) -> None:
        resolved = str(ws.resolve()) if ws.exists() else str(ws)
        if resolved in seen:
            return
        seen.add(resolved)
        state = peek_workspace_state(ws)
        items.append(
            {
                "id": pid,
                "name": name,
                "workspace": resolved,
                "phase": state.phase.value if state is not None else "discuss",
            }
        )

    ws_dir = peek_workspace_dir(default_ws) or default_ws
    parent_name = default_ws.parent.name
    label = DEFAULT_PROJECT_NAME if parent_name in {"", ".", "app"} else parent_name
    if default_ws.name == ".prd-ai-battle" and parent_name not in {"", ".", "app"}:
        label = parent_name
    elif default_ws.name != ".prd-ai-battle":
        label = default_ws.name if default_ws.name != "app" else DEFAULT_PROJECT_NAME
    _add("default", label, ws_dir)

    for rec in _catalog_projects(search):
        _add(rec.id, rec.name, rec.workspace_path)

    for name, ws in discover_named_workspaces(search):
        _add(name, name, ws)

    return items


def resolve_workspace(
    workspace: Path,
    project_id: str | None = None,
    search_root: Path | None = None,
) -> Path:
    default_ws = peek_workspace_dir(Path(workspace)) or Path(workspace)
    if not project_id or project_id == "default":
        return default_ws
    for item in list_projects(default_ws, search_root=search_root):
        if item["id"] == project_id:
            return Path(item["workspace"])
    return default_ws


def board_payload(
    workspace: Path,
    *,
    project_id: str | None = None,
    search_root: Path | None = None,
) -> dict[str, Any]:
    root = resolve_workspace(workspace, project_id, search_root)
    projects = list_projects(workspace, search_root=search_root)
    active = project_id or "default"
    if not any(p["id"] == active for p in projects) and projects:
        active = projects[0]["id"]
    matrix = matrix_payload(root)
    return {
        "projects": projects,
        "active_id": active,
        "workspace": str(root),
        "phase": phase_rail_payload(root),
        "matrix": matrix,
        "timeline": timeline_payload(root),
        "draft": draft_payload(root),
        "read_only": True,
        "clause_editable": bool(matrix.get("editable")),
    }
