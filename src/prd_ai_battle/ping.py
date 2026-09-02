"""HTTP ping of each configured Chat Completions provider.

POSTs a tiny (max_tokens=8) non-streaming chat/completions request.
Keys are never printed. The optional grok2api backup treats 429 quota as
reachable (credits empty), not as a hard fail.

Tests must inject an httpx transport — this module does not require live
network when a transport is provided.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from prd_ai_battle.config import (
    GATEWAY_BACKUP_PING_MODEL,
    GATEWAY_KEY_ENV,
    GATEWAY_PROVIDER_ID,
    AppConfig,
    is_backup_gateway_url,
)

PING_MAX_TOKENS = 8
PING_TIMEOUT_S = 20.0
PING_USER_MESSAGE = "ping"


@dataclass
class PingTarget:
    id: str
    model: str
    base_url: str
    api_key: str
    api_key_env: str
    backup: bool = False

    def chat_url(self) -> str:
        root = self.base_url.rstrip("/")
        if root.endswith("/chat/completions"):
            return root
        return f"{root}/chat/completions"


@dataclass
class PingResult:
    id: str
    model: str
    base_url: str
    backup: bool
    api_key: str
    api_key_env: str
    http_status: int | None = None
    outcome: str = "pending"
    detail: str = ""
    hard_fail: bool = False

    def as_public_dict(self) -> dict[str, Any]:
        """JSON-safe view: never includes the key value."""
        return {
            "id": self.id,
            "model": self.model,
            "base_url": self.base_url,
            "backup": self.backup,
            "api_key": self.api_key,
            "api_key_env": self.api_key_env,
            "http_status": self.http_status,
            "outcome": self.outcome,
            "detail": self.detail,
        }


def redact(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
    return out


def ping_targets(cfg: AppConfig) -> list[PingTarget]:
    """One target per unique provider URL from yaml, plus optional backup."""
    gateway_url = cfg.gateway.resolved_base_url()
    seen: set[str] = set()
    targets: list[PingTarget] = []
    for model in cfg.all_models():
        url = model.resolved_base_url(cfg.gateway)
        key = url.rstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        targets.append(
            PingTarget(
                id=model.id,
                model=model.model,
                base_url=url,
                api_key=model.resolved_key(cfg.gateway),
                api_key_env=model.api_key_env or "",
                backup=is_backup_gateway_url(url, gateway_url),
            )
        )
    if gateway_url.rstrip("/") not in seen:
        targets.append(
            PingTarget(
                id=GATEWAY_PROVIDER_ID,
                model=GATEWAY_BACKUP_PING_MODEL,
                base_url=gateway_url,
                api_key=cfg.gateway.resolved_key(),
                api_key_env=GATEWAY_KEY_ENV,
                backup=True,
            )
        )
    return targets


def _payload(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": PING_USER_MESSAGE}],
        "max_tokens": PING_MAX_TOKENS,
        "stream": False,
    }


def ping_one(
    target: PingTarget,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = PING_TIMEOUT_S,
) -> PingResult:
    secrets = [target.api_key] if target.api_key else []
    result = PingResult(
        id=target.id,
        model=target.model,
        base_url=target.base_url,
        backup=target.backup,
        api_key="set" if target.api_key else "missing",
        api_key_env=target.api_key_env,
    )
    if not target.api_key:
        result.outcome = "missing_key"
        result.detail = f"unset {target.api_key_env or 'api_key'}"
        result.hard_fail = not target.backup
        return result

    headers = {
        "Authorization": f"Bearer {target.api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            resp = client.post(target.chat_url(), headers=headers, json=_payload(target.model))
        result.http_status = resp.status_code
        result.detail = redact(resp.text[:400], secrets)
        if resp.status_code == 429:
            result.outcome = "reachable_quota_empty"
            result.hard_fail = False
        elif 200 <= resp.status_code < 300:
            result.outcome = "ok"
            result.hard_fail = False
        else:
            result.outcome = "http_error"
            result.hard_fail = not target.backup
    except httpx.HTTPError as exc:
        result.outcome = "unreachable"
        result.detail = redact(str(exc), secrets)
        result.hard_fail = not target.backup
    return result


def ping_config(
    cfg: AppConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = PING_TIMEOUT_S,
    skip_http: bool = False,
) -> dict[str, Any]:
    """Probe every configured provider. Returns a redacted report."""
    results: list[PingResult] = []
    for target in ping_targets(cfg):
        if skip_http:
            results.append(
                PingResult(
                    id=target.id,
                    model=target.model,
                    base_url=target.base_url,
                    backup=target.backup,
                    api_key="set" if target.api_key else "missing",
                    api_key_env=target.api_key_env,
                    outcome="skipped_offline",
                    detail="no HTTP (--offline)",
                    hard_fail=False,
                )
            )
            continue
        results.append(ping_one(target, transport=transport, timeout=timeout))
    public = [r.as_public_dict() for r in results]
    hard_fails = [r.id for r in results if r.hard_fail]
    return {
        "targets": public,
        "ok": not hard_fails,
        "hard_fails": hard_fails,
        "max_tokens": PING_MAX_TOKENS,
        "note": (
            "429 on the optional grok2api backup is reachable, quota empty — not a hard fail. "
            "Keys are redacted."
        ),
    }
