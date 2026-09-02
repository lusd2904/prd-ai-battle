"""Headless phase driver used by OpenCode slash commands and the overlay hook."""

from __future__ import annotations

import asyncio
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
    view["speakers"] = session.speakers()
    view["ux"] = "shared_timeline"
    view["teammate_sessions"] = []
    return view


def _timeline_payload(session: Session) -> list[dict[str, Any]]:
    return [
        {
            "model_id": m.model_id,
            "role": m.role,
            "phase": m.phase.value,
            "ts": m.ts,
            "label": m.label(),
            "content": m.content,
        }
        for m in session.load_timeline()
    ]


def _run_stream(agen) -> None:
    async def _consume() -> None:
        async for _event in agen:
            pass

    asyncio.run(_consume())


def cmd_status(session: Session) -> dict[str, Any]:
    return contract_payload(session)


def cmd_ingest(session: Session, requirement: Path | None = None) -> dict[str, Any]:
    path = Path(requirement) if requirement is not None else bundled_sample_path()
    session.load_requirement(path)
    if session.config.offline:
        session.seed_matrix_offline()
    session.enter_discuss()
    payload = contract_payload(session)
    suffix = path.suffix.lower()
    payload["source_path"] = str(path)
    payload["parser"] = "pypdf" if suffix == ".pdf" else "markdown"
    payload["advisor_input"] = "brief"
    payload["brief_markdown"] = session.state.brief.as_prompt_block() if session.state.brief else ""
    payload["matrix_markdown"] = session.state.matrix.as_prompt_table()
    return payload


def cmd_discuss(
    session: Session,
    requirement: Path | None = None,
    *,
    prompt: str | None = None,
    run: bool = True,
) -> dict[str, Any]:
    if session.state.brief is None:
        cmd_ingest(session, requirement)
    else:
        session.enter_discuss()
        session.persist()
    if run:
        if hasattr(session.client, "delay_s"):
            session.client.delay_s = 0.0  # type: ignore[attr-defined]
        _run_stream(session.discuss_group(prompt))
    payload = contract_payload(session)
    payload["brief_markdown"] = session.state.brief.as_prompt_block() if session.state.brief else ""
    payload["matrix_markdown"] = session.state.matrix.as_prompt_table()
    payload["timeline"] = _timeline_payload(session)
    payload["transcript"] = session.render_timeline()
    payload["instruction"] = (
        "Phase=discuss. This is a GROUP CHAT, not a one-shot fan-out. "
        "Round 0: yaml primary + advisors[] opened in parallel on the brief. "
        "Later rounds: every speaker was given the FULL current timeline[] "
        "(labeled [agent-id · timestamp]) plus the brief, then replied — "
        "they may agree, disagree, or ask each other. "
        "The `transcript` / `timeline` fields are ONE ordered chat. "
        "Do NOT spawn OpenCode teammates, subagents, or sidecar panes. "
        "Do not assume seed names — speakers are whatever the current yaml lists. "
        "Advisors have tools=[]. write_lock stays closed (no filesystem writes). "
        "If one speaker times out or errors, the others continue (do not abort discuss). "
        "Discuss the brief only — never dump the raw tender or the repo. "
        "Repeat discuss until the user /lock."
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
    if hasattr(session.client, "delay_s"):
        session.client.delay_s = 0.0  # type: ignore[attr-defined]
    _run_stream(session.review())
    payload = contract_payload(session)
    payload["review_packet_path"] = str(packet_path)
    payload["review_packet"] = packet.as_prompt()
    payload["timeline"] = _timeline_payload(session)
    payload["transcript"] = session.render_timeline()
    payload["instruction"] = (
        "Phase=review. Advisors already ran in parallel; their findings are on the "
        "same shared timeline (`transcript`). Do NOT spawn OpenCode teammates. "
        "Their ONLY input was the review packet (brief + matrix + chapter_diff). "
        "Do not attach the repo, the raw tender, or any other files. "
        "Speakers are the current yaml advisors[] — do not hardcode seed names. "
        "Advisors must not edit files or run shell. If one times out, continue."
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
    "discuss": lambda session, requirement=None, prompt=None, **_: cmd_discuss(
        session, requirement, prompt=prompt
    ),
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
