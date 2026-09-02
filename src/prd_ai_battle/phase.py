"""Headless phase driver used by OpenCode slash commands and the overlay hook."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prd_ai_battle.bridge import write_check
from prd_ai_battle.config import AppConfig, default_offline_config, find_config, load_config
from prd_ai_battle.ingest import bundled_sample_path
from prd_ai_battle.models import Phase
from prd_ai_battle.session import Session
from prd_ai_battle.state import IllegalTransition
from prd_ai_battle.write_lock import WriteDenied


def load_session(
    *,
    workspace: Path | None = None,
    config_path: Path | None = None,
    offline: bool | None = None,
) -> Session:
    if offline is True and config_path is None:
        cfg = default_offline_config(str(workspace or ".prd-ai-battle"))
    else:
        path = find_config(config_path)
        if path is None:
            cfg = default_offline_config(str(workspace or ".prd-ai-battle")) if offline is not False else load_config(None, offline=False)
        else:
            cfg = load_config(path, offline=offline)
    if workspace is not None:
        cfg.workspace = str(workspace)
    return Session(cfg, root=Path(cfg.workspace))


def contract_payload(session: Session) -> dict[str, Any]:
    view = session.state.contract_view()
    view["workspace"] = str(session.store.root)
    view["matrix_locked"] = session.state.matrix.locked
    view["writes_allowed_primary"] = session.state.allows_write(session.state.primary)
    view["advisor_tools"] = {aid: [] for aid in session.state.advisors}
    view["primary_tools"] = session.state.tools_for(session.state.primary)
    return view


def cmd_status(session: Session) -> dict[str, Any]:
    return contract_payload(session)


def cmd_ingest(session: Session, requirement: Path | None = None) -> dict[str, Any]:
    path = requirement or bundled_sample_path()
    session.load_requirement(path)
    if session.config.offline:
        session.seed_matrix_offline()
    session.enter_discuss()
    return contract_payload(session)


def cmd_discuss(session: Session, requirement: Path | None = None) -> dict[str, Any]:
    if session.state.brief is None:
        cmd_ingest(session, requirement)
    else:
        session.enter_discuss()
        session.persist()
    payload = contract_payload(session)
    payload["brief_markdown"] = session.state.brief.as_prompt_block() if session.state.brief else ""
    payload["matrix_markdown"] = session.state.matrix.as_prompt_table()
    payload["instruction"] = (
        "Phase=discuss. Fan out to every configured advisor IN PARALLEL. "
        "Nobody writes files. Advisors have tools=[]. Discuss the brief only — "
        "never dump the raw tender or the repo."
    )
    return payload


def cmd_lock(session: Session) -> dict[str, Any]:
    if session.state.brief is None:
        raise IllegalTransition("Cannot lock without an extracted brief — run /discuss first")
    if not session.state.matrix.rows:
        raise IllegalTransition("Cannot lock an empty 对照表")
    if not session.state.matrix.locked:
        # Live sessions may still have empty 是否响应; locking is the user's call.
        session.lock_matrix()
    payload = contract_payload(session)
    payload["matrix_markdown"] = session.state.matrix.as_prompt_table()
    payload["instruction"] = (
        "Phase=locked. 对照表 cannot be edited. write_lock still ON. "
        "Run /execute when you want the primary to write v1."
    )
    return payload


def cmd_execute(session: Session) -> dict[str, Any]:
    if session.state.phase is Phase.LOCKED:
        session.begin_execute()
    elif session.state.phase is not Phase.EXECUTE:
        session.machine.enter_execute()
        session.persist()
    payload = contract_payload(session)
    payload["brief_markdown"] = session.state.brief.as_prompt_block() if session.state.brief else ""
    payload["matrix_markdown"] = session.state.matrix.as_prompt_table()
    payload["instruction"] = (
        "Phase=execute. ONLY the primary may write files (write_lock). "
        "Advisors stay tools=[] / edit+shell denied. Write drafts under "
        ".prd-ai-battle/drafts/v1/response.md."
    )
    return payload


def cmd_review(session: Session) -> dict[str, Any]:
    if session.state.phase in {Phase.EXECUTE, Phase.REVISE}:
        session.begin_review()
    elif session.state.phase is not Phase.REVIEW:
        session.machine.enter_review()
        session.persist()
    packet_path = session.write_review_packet()
    packet = session.build_review_packet()
    payload = contract_payload(session)
    payload["review_packet_path"] = str(packet_path)
    payload["review_packet"] = packet.as_prompt()
    payload["instruction"] = (
        "Phase=review. Launch every configured advisor IN PARALLEL. "
        "Their ONLY input is the review packet below (brief + matrix + chapter_diff). "
        "Do not attach the repo, the raw tender, or any other files. "
        "Advisors must not edit files or run shell."
    )
    return payload


def cmd_revise(session: Session) -> dict[str, Any]:
    if session.state.phase is Phase.REVIEW:
        session.begin_revise()
    elif session.state.phase is not Phase.REVISE:
        session.machine.enter_revise()
        session.persist()
    payload = contract_payload(session)
    payload["brief_markdown"] = session.state.brief.as_prompt_block() if session.state.brief else ""
    payload["matrix_markdown"] = session.state.matrix.as_prompt_table()
    payload["instruction"] = (
        "Phase=revise. ONLY the primary may write the next artifact_version. "
        "Advisors remain tools=[]. Write .prd-ai-battle/drafts/v2/response.md."
    )
    return payload


def cmd_record_draft(session: Session, path: str, *, actor_id: str | None = None) -> dict[str, Any]:
    dest = session.notice_external_write(path, actor_id=actor_id)
    payload = contract_payload(session)
    payload["wrote"] = str(dest)
    return payload


def cmd_write_check(
    session: Session,
    *,
    actor: str,
    tool: str,
    path: str | None = None,
) -> dict[str, Any]:
    return write_check(session.state, actor_id=actor, tool=tool, path=path)


PHASE_COMMANDS = {
    "status": lambda session, **_: cmd_status(session),
    "ingest": lambda session, requirement=None, **_: cmd_ingest(session, requirement),
    "discuss": lambda session, requirement=None, **_: cmd_discuss(session, requirement),
    "lock": lambda session, **_: cmd_lock(session),
    "execute": lambda session, **_: cmd_execute(session),
    "review": lambda session, **_: cmd_review(session),
    "revise": lambda session, **_: cmd_revise(session),
}


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


__all__ = [
    "AppConfig",
    "IllegalTransition",
    "WriteDenied",
    "PHASE_COMMANDS",
    "cmd_discuss",
    "cmd_execute",
    "cmd_ingest",
    "cmd_lock",
    "cmd_record_draft",
    "cmd_review",
    "cmd_revise",
    "cmd_status",
    "cmd_write_check",
    "dumps",
    "load_session",
]
