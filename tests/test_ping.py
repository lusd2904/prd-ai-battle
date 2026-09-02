"""Provider ping: mocked HTTP only. No live network in CI."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from prd_ai_battle.cli import build_parser, cmd_ping
from prd_ai_battle.config import (
    GATEWAY_BACKUP_PING_MODEL,
    GATEWAY_KEY_ENV,
    GATEWAY_PROVIDER_ID,
    OPENROUTER_KEY_ENV,
    XIXI_KEY_ENV,
    load_config,
)
from prd_ai_battle.ping import PING_MAX_TOKENS, ping_config, ping_targets, redact


def _seed_cfg(monkeypatch):
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    monkeypatch.setenv(XIXI_KEY_ENV, "xixi-super-secret")
    monkeypatch.setenv(OPENROUTER_KEY_ENV, "or-super-secret")
    monkeypatch.setenv(GATEWAY_KEY_ENV, "gw-super-secret")
    return load_config(Path("config.example.yaml"), offline=False)


def test_seed_ping_targets_cover_xixi_openrouter_and_backup_grok(monkeypatch):
    cfg = _seed_cfg(monkeypatch)
    targets = ping_targets(cfg)
    ids = [t.id for t in targets]
    models = {t.id: t.model for t in targets}
    urls = {t.base_url for t in targets}
    assert "primary" in ids
    assert "advisor-grok" in ids
    assert GATEWAY_PROVIDER_ID in ids
    assert models["primary"] == "claude-opus-5"
    assert models["advisor-grok"] == "x-ai/grok-4.6"
    assert models[GATEWAY_PROVIDER_ID] == GATEWAY_BACKUP_PING_MODEL == "grok-4.5"
    assert "https://xixiapi.io/v1" in urls
    assert "https://openrouter.ai/api/v1" in urls
    assert "http://127.0.0.1:8000/v1" in urls
    backup = next(t for t in targets if t.backup)
    assert backup.model == "grok-4.5"
    assert backup.model.startswith("claude") is False


def test_ping_mocked_http_statuses_and_redacts_keys(monkeypatch):
    cfg = _seed_cfg(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["max_tokens"] == PING_MAX_TOKENS
        assert body["stream"] is False
        assert "Authorization" in request.headers
        host = request.url.host
        if host == "xixiapi.io":
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        if host == "openrouter.ai":
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        if host == "127.0.0.1":
            return httpx.Response(429, text="quota empty gw-super-secret")
        return httpx.Response(500, text="unexpected")

    report = ping_config(cfg, transport=httpx.MockTransport(handler))
    blob = json.dumps(report)
    assert "xixi-super-secret" not in blob
    assert "or-super-secret" not in blob
    assert "gw-super-secret" not in blob
    assert "***" in blob  # backup 429 body redacted the key
    by_id = {t["id"]: t for t in report["targets"]}
    assert by_id["primary"]["http_status"] == 200
    assert by_id["primary"]["outcome"] == "ok"
    assert by_id["advisor-grok"]["http_status"] == 200
    assert by_id[GATEWAY_PROVIDER_ID]["http_status"] == 429
    assert by_id[GATEWAY_PROVIDER_ID]["outcome"] == "reachable_quota_empty"
    assert by_id[GATEWAY_PROVIDER_ID]["model"] == "grok-4.5"
    assert report["ok"] is True
    assert report["hard_fails"] == []


def test_backup_429_is_not_hard_fail_required_500_is(monkeypatch):
    cfg = _seed_cfg(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "127.0.0.1":
            return httpx.Response(429, text="quota")
        return httpx.Response(500, text="boom")

    report = ping_config(cfg, transport=httpx.MockTransport(handler))
    assert report["ok"] is False
    assert "primary" in report["hard_fails"]
    backup = next(t for t in report["targets"] if t["backup"])
    assert backup["outcome"] == "reachable_quota_empty"
    assert backup["id"] not in report["hard_fails"]


def test_backup_unreachable_is_not_hard_fail(monkeypatch):
    cfg = _seed_cfg(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "127.0.0.1":
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"ok": True})

    report = ping_config(cfg, transport=httpx.MockTransport(handler))
    backup = next(t for t in report["targets"] if t["backup"])
    assert backup["outcome"] == "unreachable"
    assert report["ok"] is True


def test_missing_key_fails_required_not_backup(monkeypatch):
    monkeypatch.delenv(XIXI_KEY_ENV, raising=False)
    monkeypatch.delenv(OPENROUTER_KEY_ENV, raising=False)
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    cfg = load_config(Path("config.example.yaml"), offline=False)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not run when the key is missing")

    report = ping_config(cfg, transport=httpx.MockTransport(handler))
    assert report["ok"] is False
    outcomes = {t["id"]: t["outcome"] for t in report["targets"]}
    assert outcomes["primary"] == "missing_key"
    assert outcomes[GATEWAY_PROVIDER_ID] == "missing_key"
    assert GATEWAY_PROVIDER_ID not in report["hard_fails"]
    assert "primary" in report["hard_fails"]


def test_redact_helper():
    assert redact("token=abc123 leftover", ["abc123"]) == "token=*** leftover"


def test_cli_ping_offline_skips_http(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv(XIXI_KEY_ENV, "xixi-super-secret")
    cfg = tmp_path / "prd.yaml"
    cfg.write_text(Path("config.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    args = build_parser().parse_args(
        ["ping", "--offline", "--config", str(cfg), "--workspace", str(tmp_path)]
    )
    assert cmd_ping(args) == 0
    out = capsys.readouterr().out
    assert "xixi-super-secret" not in out
    assert "skipped_offline" in out
    assert "grok-4.5" in out
    assert '"ok": true' in out
