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
from prd_ai_battle.session import Session

BOARD_DIR_NAME = ".prd-ai-battle-board"
CATALOG_NAME = "catalog.json"
DEFAULT_PROJECT_NAME = "默认项目"
NEW_PROJECT_PREFIX = "项目"

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


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
    def open(cls, home: Path, *, seed_config: AppConfig, offline: bool | None = None) -> ProjectHub:
        """Load a catalog or register the current workspace as the first project."""
        off = seed_config.offline if offline is None else offline
        hub = cls(home, offline=off)
        hub._load()
        if hub.projects:
            if hub.active_id not in hub.projects:
                hub.active_id = hub.order[0]
            hub.mount(hub.active_id)
            return hub
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
    "NEW_PROJECT_PREFIX",
    "ProjectError",
    "ProjectHub",
    "ProjectRecord",
    "unique_project_id",
]
