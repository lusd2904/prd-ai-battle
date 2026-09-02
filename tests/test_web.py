"""Read-only 对照表 handlers. No browser. Bind 127.0.0.1:1780 only."""

from __future__ import annotations

import json
import shutil
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest

from prd_ai_battle.models import Phase, SessionState
from prd_ai_battle.web.board import (
    MATRIX_COLUMNS,
    board_payload,
    draft_payload,
    matrix_payload,
    timeline_payload,
)
from prd_ai_battle.web.server import (
    MATRIX_HOST,
    MATRIX_PORT,
    BindError,
    make_handler,
    validate_bind,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "web_board"


def test_matrix_json_columns_and_locked_rows():
    data = matrix_payload(FIXTURE)
    assert data["columns"] == ["条款", "是否响应", "证据页码", "意见", "状态"]
    assert data["columns"] == MATRIX_COLUMNS
    assert data["locked"] is True
    assert data["editable"] is False
    assert data["lock_label"] == "已锁定"
    assert [r["clause"] for r in data["rows"]] == ["时延≤20ms", "等保三级"]
    assert data["rows"][0]["responded"] == "yes"
    assert data["rows"][0]["evidence_page"] == "12"
    assert data["rows"][0]["opinion"] == "承诺专线 SLA"
    assert data["rows"][0]["status"] == "locked"


def test_timeline_json_is_labeled_shared_chat():
    data = timeline_payload(FIXTURE)
    labels = [m["label"] for m in data["messages"]]
    assert labels[0].startswith("primary · ")
    assert "advisor-sonnet" in labels[1]
    assert data["messages"][0]["content"] == "先锁时延与等保。"
    assert data["messages"][1]["content"].startswith("同意")
    assert " · " in data["messages"][0]["label"]


def test_latest_draft_from_fixture():
    data = draft_payload(FIXTURE)
    assert data["present"] is True
    assert data["version"] == "v1"
    assert "20ms" in data["content"]


def test_board_payload_phase_rail_and_projects():
    data = board_payload(FIXTURE)
    assert data["read_only"] is True
    assert data["clause_editable"] is False
    steps = [s["label"] for s in data["phase"]["steps"]]
    assert steps == ["讨论", "锁定", "执行", "审核", "修订"]
    assert data["phase"]["phase"] == "review"
    assert any(s["current"] for s in data["phase"]["steps"] if s["id"] == "review")
    assert data["projects"]
    assert data["write_lock"] if False else data["phase"]["write_lock"] is True


def test_handlers_are_read_only(tmp_path: Path):
    dest = tmp_path / "ws"
    shutil.copytree(FIXTURE, dest)
    before = {
        p.relative_to(dest): p.read_bytes()
        for p in dest.rglob("*")
        if p.is_file()
    }
    matrix_payload(dest)
    timeline_payload(dest)
    board_payload(dest)
    after = {
        p.relative_to(dest): p.read_bytes()
        for p in dest.rglob("*")
        if p.is_file()
    }
    assert before == after
    state = SessionState.model_validate_json((dest / "session.json").read_text(encoding="utf-8"))
    assert state.write_lock is True
    assert state.phase is Phase.REVIEW
    assert state.matrix.locked is True


def test_empty_workspace_has_frozen_columns():
    data = matrix_payload(Path("/no/such/workspace-prd"))
    assert data["columns"] == MATRIX_COLUMNS
    assert data["rows"] == []
    assert data["locked"] is False
    assert timeline_payload(Path("/no/such/workspace-prd"))["messages"] == []


def test_validate_bind_localhost_1780_only():
    assert validate_bind("127.0.0.1", 1780) == ("127.0.0.1", 1780)
    with pytest.raises(BindError, match="0.0.0.0"):
        validate_bind("0.0.0.0", 1780)
    with pytest.raises(BindError, match="8080"):
        validate_bind("127.0.0.1", 8080)
    with pytest.raises(BindError, match="1780"):
        validate_bind("127.0.0.1", 8000)
    with pytest.raises(BindError, match="1780"):
        validate_bind("127.0.0.1", 3000)
    assert MATRIX_HOST == "127.0.0.1"
    assert MATRIX_PORT == 1780


def test_http_matrix_and_timeline_json_no_browser():
    from http.server import ThreadingHTTPServer

    handler = make_handler(FIXTURE, search_root=FIXTURE.parent)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address[:2]
        assert host == "127.0.0.1"
        assert port != 8080
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/matrix")
        matrix = json.loads(conn.getresponse().read().decode("utf-8"))
        assert matrix["columns"] == MATRIX_COLUMNS
        assert matrix["rows"][0]["clause"] == "时延≤20ms"
        conn.request("GET", "/api/timeline")
        timeline = json.loads(conn.getresponse().read().decode("utf-8"))
        assert timeline["messages"][0]["label"].startswith("primary · ")
        conn.request("POST", "/api/matrix")
        denied = json.loads(conn.getresponse().read().decode("utf-8"))
        assert denied["ok"] is False
        conn.close()
    finally:
        httpd.shutdown()
