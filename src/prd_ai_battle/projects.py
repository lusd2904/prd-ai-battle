"""Mounted projects on the board: each has its own workspace, yaml, and env.

Several sessions stay in memory. Switching does not destroy the others.
Models and keys are baked per project so they cannot leak across the list.
write_lock still binds that project's yaml primary.id only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from prd_ai_battle.config import (
    LOCAL_ENV_NAME,
    AppConfig,
    bake_project_secrets,
    default_offline_config,
    ensure_local_config,
    infer_project_root,
    load_config,
    load_project_config,
    local_yaml_path,
    read_env_file,
    save_local_config,
    write_env_file,
)
from prd_ai_battle.models import Phase, SessionState
from prd_ai_battle.session import Session

BOARD_DIR_NAME = ".prd-ai-battle-board"
CATALOG_NAME = "catalog.json"
DEFAULT_PROJECT_NAME = "默认项目"
NEW_PROJECT_PREFIX = "项目"

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")
_D01_NAME = re.compile(r"^D\d+$", re.I)
_EMPTY_CLAUSE = frozenset({"", "(none)", "（无）", "无", "-", "—"})
_SKIP_DISCOVER_DIRS = frozenset({
    ".git",
    ".venv",
    "venv",
    "src",
    "tests",
    "samples",
    "schemas",
    "scripts",
    "node_modules",
    "__pycache__",
    ".opencode",
    "dist",
    "build",
})
LOCKED_OR_LATER = frozenset({Phase.LOCKED, Phase.EXECUTE, Phase.REVIEW, Phase.REVISE})


class ProjectError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectRecord:
    id: str
    name: str
    root: str
    workspace: str

    @property
    def root_path(self) -> Path:
        return Path(self.root)

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace)

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "root": self.root, "workspace": self.workspace}

    @classmethod
    def from_dict(cls, raw: dict) -> ProjectRecord:
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            root=str(raw["root"]),
            workspace=str(raw["workspace"]),
        )


def unique_project_id(existing: set[str]) -> str:
    n = 1
    while f"p{n}" in existing:
        n += 1
    return f"p{n}"


def peek_workspace_dir(path: Path) -> Path | None:
    """Return the directory that holds session.json, if any."""
    candidate = Path(path)
    if (candidate / "session.json").is_file():
        return candidate
    nested = candidate / ".prd-ai-battle"
    if (nested / "session.json").is_file():
        return nested
    return None


def peek_workspace_state(path: Path) -> SessionState | None:
    ws = peek_workspace_dir(path)
    if ws is None:
        return None
    try:
        return SessionState.model_validate_json((ws / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_leftover_tender_fixture(state: SessionState | None, workspace: Path) -> bool:
    """True when this workspace is the bundled sample tender, not a real bid."""
    if state is None:
        return False
    source = " ".join(
        [
            state.requirement_path or "",
            state.brief.source_path if state.brief is not None else "",
        ]
    ).replace("\\", "/")
    if "data/tender.md" in source:
        return True
    req = Path(workspace) / "requirement.md"
    if not req.is_file():
        return False
    try:
        from prd_ai_battle.ingest import bundled_sample_path

        bundled = bundled_sample_path().read_text(encoding="utf-8").strip()
        return req.read_text(encoding="utf-8").strip() == bundled
    except OSError:
        return False


def is_empty_d01_stub(state: SessionState | None, name: str = "") -> bool:
    """True for an empty D01 leftover (named D01, or a stub D01 row with no clause)."""
    if name and _D01_NAME.fullmatch(name.strip()):
        if state is None:
            return True
        if state.brief is None and not state.matrix.rows:
            return True
    if state is None:
        return False
    rows = state.matrix.rows
    if not rows:
        return False

    def _empty(row) -> bool:
        return "".join((row.clause or "").split()) in _EMPTY_CLAUSE

    if all(_empty(row) for row in rows):
        return True
    if len(rows) == 1 and str(rows[0].clause_id).upper().startswith("D") and _empty(rows[0]):
        return True
    return False


def is_locked_or_later(state: SessionState | None) -> bool:
    return state is not None and state.phase in LOCKED_OR_LATER


def discover_named_workspaces(search_root: Path) -> list[tuple[str, Path]]:
    """Sibling dirs such as round-matrix that already hold a session."""
    root = Path(search_root)
    if not root.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    for child in sorted(children):
        if not child.is_dir() or child.name.startswith(".") or child.name in _SKIP_DISCOVER_DIRS:
            continue
        ws = peek_workspace_dir(child)
        if ws is not None:
            found.append((child.name, ws))
    return found


class ProjectHub:
    """Catalog + mounted Session objects. Active project owns the board chrome."""

    def __init__(self, home: Path, *, offline: bool = False) -> None:
        self.home = Path(home)
        self.offline = offline
        self.catalog_path = self.home / CATALOG_NAME
        self.projects: dict[str, ProjectRecord] = {}
        self.order: list[str] = []
        self.active_id: str = ""
        self._mounted: dict[str, Session] = {}

    @classmethod
    def open(
        cls,
        home: Path,
        *,
        seed_config: AppConfig,
        offline: bool | None = None,
        search_root: Path | None = None,
    ) -> ProjectHub:
        """Load a catalog or register the current workspace as the first project.

        Default/open prefers a last-locked workspace (e.g. round-matrix) over a
        leftover bundled tender fixture or an empty D01 stub. Fresh empty
        workspaces stay as a clean project.
        """
        off = seed_config.offline if offline is None else offline
        hub = cls(home, offline=off)
        hub._load()
        if search_root is not None:
            hub._adopt_discovered(Path(search_root))
        if not hub.projects:
            ws = Path(seed_config.workspace).resolve()
            rec = ProjectRecord(
                id=unique_project_id(set()),
                name=DEFAULT_PROJECT_NAME,
                root=str(infer_project_root(ws).resolve()),
                workspace=str(ws),
            )
            cfg = seed_config.model_copy(deep=True)
            cfg.offline = off
            cfg.workspace = str(ws)
            overlay = read_env_file(Path(rec.root) / LOCAL_ENV_NAME)
            bake_project_secrets(cfg, overlay)
            hub.projects[rec.id] = rec
            hub.order.append(rec.id)
            hub._mounted[rec.id] = Session(cfg, root=ws)
            hub.active_id = rec.id
            hub._save()
        hub._prefer_startup(seed_config)
        if hub.active_id not in hub.projects and hub.order:
            hub.active_id = hub.order[0]
            hub._save()
        hub.mount(hub.active_id)
        return hub

    @property
    def mounted_ids(self) -> tuple[str, ...]:
        return tuple(self._mounted)

    def iter_projects(self) -> list[ProjectRecord]:
        return [self.projects[pid] for pid in self.order if pid in self.projects]

    def record(self, project_id: str) -> ProjectRecord:
        try:
            return self.projects[project_id]
        except KeyError as exc:
            raise ProjectError(f"未知项目 {project_id}") from exc

    def active_record(self) -> ProjectRecord:
        return self.record(self.active_id)

    def active_session(self) -> Session:
        if not self.active_id:
            raise ProjectError("没有活动项目")
        return self.mount(self.active_id)

    def session(self, project_id: str) -> Session | None:
        return self._mounted.get(project_id)

    def is_mounted(self, project_id: str) -> bool:
        return project_id in self._mounted

    def mount(self, project_id: str) -> Session:
        """Load or return the already-mounted Session. Never drops other mounts."""
        if project_id in self._mounted:
            return self._mounted[project_id]
        rec = self.record(project_id)
        cfg = load_project_config(
            rec.root_path,
            offline=True if self.offline else None,
            workspace=rec.workspace_path,
        )
        if self.offline:
            cfg.offline = True
        session = Session(cfg, root=rec.workspace_path)
        self._mounted[project_id] = session
        return session

    def switch(self, project_id: str) -> Session:
        """Activate another mounted project. Other sessions stay alive."""
        rec = self.record(project_id)
        if self.active_id and self.active_id in self._mounted:
            self._mounted[self.active_id].persist()
        self.active_id = rec.id
        self._save()
        return self.mount(rec.id)

    def next_default_name(self) -> str:
        if not self.projects:
            return DEFAULT_PROJECT_NAME
        n = len(self.projects) + 1
        existing = {p.name for p in self.projects.values()}
        name = f"{NEW_PROJECT_PREFIX}{n}"
        while name in existing:
            n += 1
            name = f"{NEW_PROJECT_PREFIX}{n}"
        return name

    def create_project(
        self,
        name: str = "",
        *,
        config: AppConfig | None = None,
        env: dict[str, str] | None = None,
        offline: bool | None = None,
    ) -> ProjectRecord:
        """新建: own root (yaml + gitignored env) and `.prd-ai-battle/` workspace."""
        off = self.offline if offline is None else offline
        label = (name or "").strip() or self.next_default_name()
        pid = unique_project_id(set(self.projects))
        root = (self.home / "projects" / pid).resolve()
        root.mkdir(parents=True, exist_ok=True)
        ws = (root / ".prd-ai-battle").resolve()
        if config is not None:
            cfg = config.model_copy(deep=True)
            cfg.workspace = str(ws)
            cfg.offline = off if offline is None else offline
            save_local_config(cfg, repo=root)
        elif off:
            cfg = default_offline_config(str(ws))
            save_local_config(cfg, repo=root)
        else:
            ensure_local_config(root)
            cfg = load_config(local_yaml_path(root), offline=False)
            cfg.workspace = str(ws)
        overlay = dict(env or {})
        env_path = root / LOCAL_ENV_NAME
        if overlay:
            write_env_file(env_path, overlay)
        elif not env_path.exists():
            env_path.write_text(
                "# gitignored local keys — written for this project. Do not commit.\n",
                encoding="utf-8",
            )
        overlay = read_env_file(env_path)
        bake_project_secrets(cfg, overlay)
        rec = ProjectRecord(id=pid, name=label, root=str(root), workspace=str(ws))
        self.projects[pid] = rec
        self.order.append(pid)
        self._mounted[pid] = Session(cfg, root=ws)
        self.active_id = pid
        self._save()
        return rec

    def _adopt_discovered(self, search_root: Path) -> None:
        """Register sibling workspaces (round-matrix, …) that are not in the catalog."""
        existing = {Path(p.workspace).resolve() for p in self.projects.values()}
        existing_names = {p.name for p in self.projects.values()}
        added = False
        for name, ws in discover_named_workspaces(search_root):
            resolved = ws.resolve()
            if resolved in existing:
                continue
            pid = unique_project_id(set(self.projects))
            label = name
            n = 2
            while label in existing_names:
                label = f"{name}-{n}"
                n += 1
            rec = ProjectRecord(
                id=pid,
                name=label,
                root=str(infer_project_root(resolved).resolve()),
                workspace=str(resolved),
            )
            self.projects[pid] = rec
            self.order.append(pid)
            existing.add(resolved)
            existing_names.add(label)
            added = True
        if added:
            self._save()

    def _prefer_startup(self, seed_config: AppConfig) -> None:
        """Land on last locked workspace, else a clean project — not leftover/D01."""
        locked: list[tuple[str, str]] = []
        clean: list[tuple[str, str]] = []
        junk: list[str] = []
        for rec in self.iter_projects():
            state = peek_workspace_state(rec.workspace_path)
            stamp = (state.updated_at if state is not None else "") or ""
            if is_locked_or_later(state):
                locked.append((stamp, rec.id))
            elif is_leftover_tender_fixture(state, rec.workspace_path) or is_empty_d01_stub(
                state, rec.name
            ):
                junk.append(rec.id)
            else:
                clean.append((stamp, rec.id))
        if locked:
            locked.sort()
            self.active_id = locked[-1][1]
            self._save()
            return
        if clean:
            if self.active_id in {pid for _, pid in clean}:
                return
            clean.sort()
            self.active_id = clean[-1][1]
            self._save()
            return
        if junk:
            self.create_project(offline=self.offline)

    def _load(self) -> None:
        if not self.catalog_path.is_file():
            return
        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.active_id = str(raw.get("active_id") or "")
        self.projects = {}
        self.order = []
        for item in raw.get("projects") or []:
            rec = ProjectRecord.from_dict(item)
            self.projects[rec.id] = rec
            self.order.append(rec.id)

    def _save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_id": self.active_id,
            "projects": [self.projects[pid].as_dict() for pid in self.order if pid in self.projects],
        }
        self.catalog_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


__all__ = [
    "BOARD_DIR_NAME",
    "CATALOG_NAME",
    "DEFAULT_PROJECT_NAME",
    "LOCKED_OR_LATER",
    "NEW_PROJECT_PREFIX",
    "ProjectError",
    "ProjectHub",
    "ProjectRecord",
    "discover_named_workspaces",
    "is_empty_d01_stub",
    "is_leftover_tender_fixture",
    "is_locked_or_later",
    "peek_workspace_dir",
    "peek_workspace_state",
    "unique_project_id",
]
