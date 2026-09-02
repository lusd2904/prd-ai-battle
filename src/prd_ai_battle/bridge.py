"""OpenCode overlay bridge: write-check + actor mapping.

This is the product enforcement layer. OpenCode's own permissions are not
phase-aware, so the branded workspace calls this module (from the in-repo
hook and from slash commands) before any filesystem mutation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prd_ai_battle.models import Phase, SessionState
from prd_ai_battle.write_lock import WriteDenied, WriteLock

WRITE_TOOLS = frozenset(
    {
        "write",
        "edit",
        "apply_patch",
        "applypatch",
        "write_file",
        "patch",
        "strreplace",
        "str_replace",
    }
)
SHELL_TOOLS = frozenset({"bash", "shell"})
READ_TOOLS = frozenset({"read", "glob", "grep", "list"})

# Paths advisors may read during review. Everything else is out of band.
REVIEW_ALLOWLIST_SUFFIXES = (
    "/brief.md",
    "/brief.json",
    "/matrix.json",
    "/review-packet.md",
    "/session.json",
)

TENDER_NAME_HINTS = (
    "tender.md",
    "tender.pdf",
    "requirement.md",
    "requirement.pdf",
    ".pdf",
    "招标",
)


def is_primary_actor(actor_id: str, state: SessionState) -> bool:
    """write_lock binds the current primary id from config/session — never a model name."""
    actor = (actor_id or "").strip()
    return bool(actor) and actor == state.primary


def is_unknown_actor(actor_id: str) -> bool:
    """Session not remembered (or empty) — never treat as the primary writer."""
    return not (actor_id or "").strip() or (actor_id or "").strip() == "unknown"


def is_advisor_actor(actor_id: str, state: SessionState) -> bool:
    actor = (actor_id or "").strip()
    if is_unknown_actor(actor):
        # Fail closed for writes: unknown caller is not the current primary.
        return True
    return actor != state.primary


def is_write_tool(tool: str) -> bool:
    return (tool or "").lower() in WRITE_TOOLS


def is_shell_tool(tool: str) -> bool:
    return (tool or "").lower() in SHELL_TOOLS


def is_read_tool(tool: str) -> bool:
    return (tool or "").lower() in READ_TOOLS


def _posix(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/")


def is_tender_path(path: str | None) -> bool:
    text = _posix(path).lower()
    if not text:
        return False
    return any(hint in text for hint in TENDER_NAME_HINTS)


def is_review_allowlisted(path: str | None) -> bool:
    text = _posix(path)
    if not text:
        return False
    lowered = text.lower()
    return any(lowered.endswith(suffix) for suffix in REVIEW_ALLOWLIST_SUFFIXES)


def write_check(
    state: SessionState,
    *,
    actor_id: str,
    tool: str,
    path: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable decision. `ok` is True only when allowed."""

    advisor = is_advisor_actor(actor_id, state)
    tool_name = (tool or "").lower()
    payload = {
        "ok": True,
        "reason": "allowed",
        "actor": actor_id,
        "tool": tool_name,
        "path": path or "",
        "phase": state.phase.value,
        "primary": state.primary,
        "advisors": list(state.advisors),
        "write_lock": state.write_lock,
        "advisor": advisor,
        "tools_for_actor": state.tools_for(state.primary if not advisor else actor_id),
    }

    if advisor:
        payload["tools_for_actor"] = []

    if is_unknown_actor(actor_id) and (is_write_tool(tool_name) or is_shell_tool(tool_name)):
        payload["ok"] = False
        payload["reason"] = "write_lock denied for unknown actor"
        return payload

    if advisor and (is_write_tool(tool_name) or is_shell_tool(tool_name)):
        payload["ok"] = False
        payload["reason"] = (
            f"write_lock: advisor {actor_id!r} is denied {tool_name or 'mutation'} "
            "(advisors always have tools=[]; edit/shell denied)"
        )
        return payload

    if advisor and is_tender_path(path):
        payload["ok"] = False
        payload["reason"] = (
            "Advisors never receive the raw tender / requirement file. "
            "Use the extracted brief only."
        )
        return payload

    if advisor and state.phase is Phase.REVIEW and is_read_tool(tool_name):
        if not is_review_allowlisted(path):
            payload["ok"] = False
            payload["reason"] = (
                "Review-phase advisor input is ONLY brief + matrix + chapter_diff. "
                "Refusing repo/tender reads."
            )
            return payload

    if is_write_tool(tool_name):
        # Same fail-closed decision as WriteLock.assert_can_write (source of truth).
        try:
            WriteLock(state).assert_can_write(actor_id)
        except WriteDenied as exc:
            payload["ok"] = False
            payload["reason"] = str(exc)
            return payload

    return payload


def review_packet_path(workspace: Path) -> Path:
    return workspace / "review-packet.md"
