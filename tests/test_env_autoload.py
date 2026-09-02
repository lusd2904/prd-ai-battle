"""CLI discuss/phase/ping/ingest load gitignored env files without `source`."""

from __future__ import annotations

import os
from pathlib import Path

from prd_ai_battle.cli import build_parser, cmd_discuss_stream, cmd_ingest, cmd_phase, cmd_ping
from prd_ai_battle.config import (
    OPENROUTER_KEY_ENV,
    XIXI_KEY_ENV,
    autoload_process_env,
    env_file_candidates,
)
from prd_ai_battle.phase import load_session


DUMMY_XIXI = "dummy-xixi-key-NOT-A-REAL-SECRET"
DUMMY_OR = "dummy-openrouter-key-NOT-A-REAL-SECRET"


def _write_env(path: Path) -> Path:
    path.write_text(
        f"# gitignored dummy keys for tests\n{XIXI_KEY_ENV}={DUMMY_XIXI}\n{OPENROUTER_KEY_ENV}={DUMMY_OR}\n",
        encoding="utf-8",
    )
    return path


def _clear_seed_keys(monkeypatch) -> None:
    monkeypatch.delenv(XIXI_KEY_ENV, raising=False)
    monkeypatch.delenv(OPENROUTER_KEY_ENV, raising=False)


def _assert_keys_not_printed(blob: str) -> None:
    assert DUMMY_XIXI not in blob
    assert DUMMY_OR not in blob


def test_autoload_picks_up_cwd_env_file(tmp_path: Path, monkeypatch):
    _clear_seed_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_env(tmp_path / "prd-ai-battle.env")
    applied = autoload_process_env(cwd=tmp_path)
    assert os.environ[XIXI_KEY_ENV] == DUMMY_XIXI
    assert os.environ[OPENROUTER_KEY_ENV] == DUMMY_OR
    assert applied[XIXI_KEY_ENV] == DUMMY_XIXI
    assert DUMMY_XIXI not in repr(env_file_candidates(cwd=tmp_path))


def test_autoload_picks_up_per_project_env(tmp_path: Path, monkeypatch):
    _clear_seed_keys(monkeypatch)
    project = tmp_path / "bid"
    ws = project / ".prd-ai-battle"
    project.mkdir()
    _write_env(project / "prd-ai-battle.env")
    monkeypatch.chdir(tmp_path)
    autoload_process_env(workspace=ws, cwd=tmp_path)
    assert os.environ[XIXI_KEY_ENV] == DUMMY_XIXI


def test_autoload_missing_file_is_ok(tmp_path: Path, monkeypatch):
    _clear_seed_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    applied = autoload_process_env(workspace=tmp_path / "ws", cwd=tmp_path)
    assert applied == {}
    assert XIXI_KEY_ENV not in os.environ


def test_discuss_cli_loads_env_file_and_never_prints_keys(tmp_path: Path, monkeypatch, capsys):
    _clear_seed_keys(monkeypatch)
    project = tmp_path / "proj"
    project.mkdir()
    _write_env(project / "prd-ai-battle.env")
    monkeypatch.chdir(project)
    args = build_parser().parse_args(
        ["discuss", "--offline", "--workspace", str(project / "ws"), "--prompt", "cover 废标"]
    )
    assert cmd_discuss_stream(args) == 0
    assert os.environ[XIXI_KEY_ENV] == DUMMY_XIXI
    out = capsys.readouterr()
    _assert_keys_not_printed(out.out + out.err)
    assert "Shared discuss" in out.out


def test_phase_ping_ingest_load_env_file(tmp_path: Path, monkeypatch, capsys):
    _clear_seed_keys(monkeypatch)
    project = tmp_path / "proj"
    project.mkdir()
    _write_env(project / "prd-ai-battle.env")
    (project / "config.example.yaml").write_text(
        Path("config.example.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.chdir(project)

    brief = project / "brief.md"
    brief.write_text("# 新需求\n\n## 必须做\n- 新必须条款\n", encoding="utf-8")
    ingest_args = build_parser().parse_args(
        ["ingest", str(brief), "--offline", "--workspace", str(project / "ws-in")]
    )
    assert cmd_ingest(ingest_args) == 0
    assert os.environ[XIXI_KEY_ENV] == DUMMY_XIXI

    _clear_seed_keys(monkeypatch)
    phase_args = build_parser().parse_args(
        ["phase", "status", "--offline", "--workspace", str(project / "ws-ph")]
    )
    assert cmd_phase(phase_args) == 0
    assert os.environ[XIXI_KEY_ENV] == DUMMY_XIXI

    _clear_seed_keys(monkeypatch)
    cfg = project / "prd.yaml"
    cfg.write_text(Path("config.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    ping_args = build_parser().parse_args(
        ["ping", "--offline", "--config", str(cfg), "--workspace", str(project / "ws-ping")]
    )
    assert cmd_ping(ping_args) == 0
    assert os.environ[XIXI_KEY_ENV] == DUMMY_XIXI
    blob = capsys.readouterr().out + capsys.readouterr().err
    _assert_keys_not_printed(blob)


def test_load_session_offline_works_without_env_file(tmp_path: Path, monkeypatch):
    _clear_seed_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    session = load_session(workspace=tmp_path / "ws", offline=True)
    assert session.config.offline is True
    assert session.speakers()
    assert XIXI_KEY_ENV not in os.environ
