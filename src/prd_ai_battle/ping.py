"""HTTP + local-CLI ping of configured speakers.

POSTs a tiny (max_tokens=8) non-streaming chat/completions request for HTTP.
CLI speakers are probed with `shutil.which` (no LLM call). Keys are never
printed. Optional providers with an empty env are skipped. The optional
grok2api backup treats 429 quota as reachable (credits empty), not a hard fail.

Tests must inject an httpx transport and may stub CLI `which` — this module
does not require live network or installed Mac CLIs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from prd_ai_battle.cli_transport import WhichFn, probe_cli
from prd_ai_battle.config import (
    GATEWAY_BACKUP_PING_MODEL,
    GATEWAY_KEY_ENV,
    GATEWAY_PROVIDER_ID,
    AppConfig,
    is_backup_gateway_url,
)
from prd_ai_battle.http_retry import backoff_seconds, should_retry_status
from prd_ai_battle.mac_speakers import (
    OPTIONAL_PROVIDER_IDS,
    SPEAKERS,
    infer_cli_command,
)
from prd_ai_battle.overlay import provider_id_for
from prd_ai_battle.redact import redact as redact_secrets

PING_MAX_TOKENS = 8
PING_TIMEOUT_S = 20.0
PING_USER_MESSAGE = "ping"
PING_RETRY_ATTEMPTS = 3
PING_BACKOFF_S = (0.05, 0.1)


@dataclass
class PingTarget:
    id: str
    model: str
    base_url: str
    api_key: str
    api_key_env: str
    backup: bool = False
    kind: str = "http"
    optional: bool = False
    command: str = ""
    provider_id: str = ""

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
    kind: str = "http"
    command: str = ""
    cli: str = ""
    binary: str = ""
    version: str = ""

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
            "kind": self.kind,
            "command": self.command,
            "cli": self.cli,
            "binary": self.binary,
            "version": self.version,
        }


def redact(text: str, secrets: list[str] | None = None) -> str:
    return redact_secrets(text, extra=secrets)


def _optional_http(model_id: str, url: str, gateway_url: str, provider_id: str) -> bool:
    if is_backup_gateway_url(url, gateway_url):
        return True
    return provider_id in OPTIONAL_PROVIDER_IDS


def ping_targets(cfg: AppConfig) -> list[PingTarget]:
    """Yaml speakers + optional backup + catalog CLI probes not already on the team."""
    gateway_url = cfg.gateway.resolved_base_url()
    seen_http: set[str] = set()
    seen_cli: set[str] = set()
    targets: list[PingTarget] = []
    for model in cfg.all_models():
        pid = provider_id_for(model, gateway_url)
        if model.is_cli():
            command = infer_cli_command(model.model, model.command)
            if command in seen_cli:
                continue
            seen_cli.add(command)
            targets.append(
                PingTarget(
                    id=model.id,
                    model=model.model,
                    base_url="",
                    api_key=model.resolved_key(cfg.gateway),
                    api_key_env=model.api_key_env or "",
                    backup=False,
                    kind="cli",
                    optional=True,
                    command=command,
                    provider_id=pid,
                )
            )
            continue
        url = model.resolved_base_url(cfg.gateway)
        key = url.rstrip("/")
        if not key or key in seen_http:
            continue
        seen_http.add(key)
        optional = _optional_http(model.id, url, gateway_url, pid)
        targets.append(
            PingTarget(
                id=model.id,
                model=model.model,
                base_url=url,
                api_key=model.resolved_key(cfg.gateway),
                api_key_env=model.api_key_env or "",
                backup=is_backup_gateway_url(url, gateway_url),
                kind="http",
                optional=optional,
                provider_id=pid,
            )
        )
    if gateway_url.rstrip("/") not in seen_http:
        targets.append(
            PingTarget(
                id=GATEWAY_PROVIDER_ID,
                model=GATEWAY_BACKUP_PING_MODEL,
                base_url=gateway_url,
                api_key=cfg.gateway.resolved_key(),
                api_key_env=GATEWAY_KEY_ENV,
                backup=True,
                kind="http",
                optional=True,
                provider_id=GATEWAY_PROVIDER_ID,
            )
        )
    for spec in SPEAKERS.values():
        if spec.default_command in seen_cli:
            continue
        seen_cli.add(spec.default_command)
        targets.append(
            PingTarget(
                id=spec.provider_id,
                model=spec.models[0],
                base_url=spec.http_base_url,
                api_key="",
                api_key_env=spec.key_envs[0] if spec.key_envs else "",
                backup=False,
                kind="cli",
                optional=True,
                command=spec.default_command,
                provider_id=spec.provider_id,
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


def _base_result(target: PingTarget) -> PingResult:
    return PingResult(
        id=target.id,
        model=target.model,
        base_url=target.base_url,
        backup=target.backup,
        api_key="set" if target.api_key else "missing",
        api_key_env=target.api_key_env,
        kind=target.kind,
        command=target.command,
    )


def ping_one(
    target: PingTarget,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = PING_TIMEOUT_S,
    which: WhichFn | None = None,
) -> PingResult:
    if target.kind == "cli":
        return _ping_cli(target, which=which)
    secrets = [target.api_key] if target.api_key else []
    result = _base_result(target)
    if not target.api_key:
        if target.optional and not target.backup:
            result.outcome = "skipped_optional"
            result.detail = f"optional env empty ({target.api_key_env or 'api_key'})"
            result.hard_fail = False
            return result
        result.outcome = "missing_key"
        result.detail = f"unset {target.api_key_env or 'api_key'}"
        result.hard_fail = not target.backup
        return result

    headers = {
        "Authorization": f"Bearer {target.api_key}",
        "Content-Type": "application/json",
    }
    last_status: int | None = None
    last_detail = ""
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            for attempt in range(PING_RETRY_ATTEMPTS):
                try:
                    resp = client.post(
                        target.chat_url(), headers=headers, json=_payload(target.model)
                    )
                except httpx.TimeoutException as exc:
                    last_detail = redact(str(exc), secrets)
                    if attempt >= PING_RETRY_ATTEMPTS - 1:
                        result.outcome = "unreachable"
                        result.detail = last_detail
                        result.hard_fail = not target.backup and not target.optional
                        return result
                    time.sleep(backoff_seconds(attempt, PING_BACKOFF_S))
                    continue
                last_status = resp.status_code
                last_detail = redact(resp.text[:400], secrets)
                # 429 = quota empty for ping (especially grok2api). Retry 5xx only.
                if (
                    resp.status_code != 429
                    and should_retry_status(resp.status_code)
                    and attempt < PING_RETRY_ATTEMPTS - 1
                ):
                    time.sleep(backoff_seconds(attempt, PING_BACKOFF_S))
                    continue
                break
        result.http_status = last_status
        result.detail = last_detail
        if last_status == 429:
            result.outcome = "reachable_quota_empty"
            result.hard_fail = False
        elif last_status is not None and 200 <= last_status < 300:
            result.outcome = "ok"
            result.hard_fail = False
        else:
            result.outcome = "http_error"
            result.hard_fail = not target.backup and not target.optional
    except httpx.HTTPError as exc:
        result.outcome = "unreachable"
        result.detail = redact(str(exc), secrets)
        result.hard_fail = not target.backup and not target.optional
    return result


def _ping_cli(target: PingTarget, *, which: WhichFn | None = None) -> PingResult:
    result = _base_result(target)
    probe = probe_cli(target.command, which=which, run_version=True)
    result.cli = "present" if probe.found else "missing"
    result.binary = probe.binary
    result.detail = probe.detail
    result.version = probe.version
    if probe.found:
        result.outcome = "cli_present"
        result.hard_fail = False
        if probe.fallback_used:
            result.detail = probe.detail
    else:
        result.outcome = "missing_cli"
        result.hard_fail = False
    return result


def ping_config(
    cfg: AppConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = PING_TIMEOUT_S,
    skip_http: bool = False,
    which: WhichFn | None = None,
) -> dict[str, Any]:
    """Probe every configured provider. Returns a redacted report."""
    results: list[PingResult] = []
    for target in ping_targets(cfg):
        if skip_http:
            result = _base_result(target)
            result.outcome = "skipped_offline"
            result.detail = "no HTTP (--offline)"
            result.hard_fail = False
            if target.kind == "cli":
                probe = probe_cli(target.command, which=which)
                result.cli = "present" if probe.found else "missing"
                result.binary = probe.binary
                result.detail = f"{probe.detail} (offline; no CLI exec)"
                result.outcome = "missing_cli" if not probe.found else "cli_present"
            results.append(result)
            continue
        results.append(ping_one(target, transport=transport, timeout=timeout, which=which))
    public = [r.as_public_dict() for r in results]
    hard_fails = [r.id for r in results if r.hard_fail]
    return {
        "targets": public,
        "ok": not hard_fails,
        "hard_fails": hard_fails,
        "max_tokens": PING_MAX_TOKENS,
        "note": (
            "429 on the optional grok2api backup is reachable, quota empty — not a hard fail. "
            "Optional HTTP with empty env is skipped. Missing Mac CLI is reported, not a crash. "
            "Keys are redacted."
        ),
    }
