"""Never log secrets: API keys, Bearer tokens, Authorization headers."""

from __future__ import annotations

import os
import re

from prd_ai_battle.config import GATEWAY_KEY_ENV, OPENROUTER_KEY_ENV, SEED_KEY_ENVS, XIXI_KEY_ENV
from prd_ai_battle.mac_speakers import OPTIONAL_KEY_ENVS

_BEARER = re.compile(r"(?i)(authorization:\s*bearer\s+)\S+")
_BEARER_VALUE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")
_ENV_ASSIGN = re.compile(
    r"(?i)\b("
    + "|".join(
        re.escape(name)
        for name in (*SEED_KEY_ENVS, *OPTIONAL_KEY_ENVS, "AUTHORIZATION")
    )
    + r")\s*[:=]\s*\S+"
)


def secret_values(extra: list[str] | None = None) -> list[str]:
    found: list[str] = []
    for name in (*SEED_KEY_ENVS, *OPTIONAL_KEY_ENVS):
        value = os.environ.get(name, "")
        if value:
            found.append(value)
    if extra:
        found.extend(value for value in extra if value)
    # Longest first so overlapping tokens redact fully.
    found.sort(key=len, reverse=True)
    return found


def redact(text: str, extra: list[str] | None = None) -> str:
    """Replace known key values and Authorization material with ***."""
    out = text or ""
    for secret in secret_values(extra):
        out = out.replace(secret, "***")
    out = _BEARER.sub(r"\1***", out)
    out = _BEARER_VALUE.sub(r"\1***", out)
    out = _ENV_ASSIGN.sub(lambda m: f"{m.group(1)}=***", out)
    return out


# Re-export env names so callers can mention them without importing values.
KEY_ENV_NAMES = (XIXI_KEY_ENV, OPENROUTER_KEY_ENV, GATEWAY_KEY_ENV, *OPTIONAL_KEY_ENVS)
