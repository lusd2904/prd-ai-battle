from pathlib import Path

import pytest

from prd_ai_battle.cli import build_parser, cmd_demo, cmd_doctor, cmd_export, cmd_ingest, main
from pdf_fixture import MINI_TENDER, write_text_pdf


def test_demo_accepts_workspace_after_subcommand(tmp_path: Path):
    args = build_parser().parse_args(["demo", "--workspace", str(tmp_path)])
    assert args.command == "demo"
    assert args.workspace == tmp_path
    assert cmd_demo(args) == 0
    assert (tmp_path / "drafts" / "v1" / "response.md").is_file()
    assert (tmp_path / "drafts" / "v2" / "response.md").is_file()
    assert (tmp_path / "matrix.json").is_file()
    assert (tmp_path / "transcript.jsonl").is_file()


def test_doctor_redacts_key(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("PRD_SFP_XIXI_KEY", "super-secret")
    cfg = tmp_path / "prd.yaml"
    cfg.write_text(Path("config.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    args = build_parser().parse_args(["doctor", "--config", str(cfg), "--workspace", str(tmp_path)])
    assert cmd_doctor(args) == 0
    out = capsys.readouterr().out
    assert "super-secret" not in out
    assert '"set"' in out
    assert "xixiapi.io" in out
    assert "grok-4.5" in out
    assert "prd-ai-battle ping" in out


def test_ingest_pdf_cli_seeds_brief_and_matrix(tmp_path: Path, capsys):
    pdf = write_text_pdf(tmp_path / "tender.pdf", MINI_TENDER)
    args = build_parser().parse_args(
        ["ingest", str(pdf), "--workspace", str(tmp_path / "ws"), "--offline"]
    )
    assert args.command == "ingest"
    assert cmd_ingest(args) == 0
    out = capsys.readouterr().out
    assert '"phase": "discuss"' in out
    assert '"parser": "pypdf"' in out
    assert '"advisor_input": "brief"' in out
    assert "政务云" in out
    assert "%PDF" not in out
    ws = tmp_path / "ws"
    assert (ws / "brief.json").is_file()
    assert (ws / "brief.md").is_file()
    assert (ws / "matrix.json").is_file()
    requirement = (ws / "requirement.md").read_text(encoding="utf-8")
    assert "类似业绩" in requirement
    assert requirement.lstrip().startswith("%PDF") is False


def test_ingest_markdown_cli(tmp_path: Path, capsys):
    md = tmp_path / "tender.md"
    md.write_text(MINI_TENDER, encoding="utf-8")
    args = build_parser().parse_args(
        ["ingest", str(md), "--workspace", str(tmp_path / "ws"), "--offline"]
    )
    assert cmd_ingest(args) == 0
    out = capsys.readouterr().out
    assert '"parser": "markdown"' in out
    assert '"phase": "discuss"' in out


def test_ingest_vpn_brief_cli_seeds_real_matrix_rows(tmp_path: Path, capsys):
    fixture = Path(__file__).resolve().parent / "fixtures" / "vpn_latency_brief.md"
    args = build_parser().parse_args(
        ["ingest", str(fixture), "--workspace", str(tmp_path / "ws"), "--offline"]
    )
    assert cmd_ingest(args) == 0
    out = capsys.readouterr().out
    assert '"parser": "markdown"' in out
    assert "必须" in out
    assert "可选" in out
    assert "风险" in out
    ws = tmp_path / "ws"
    matrix_text = (ws / "matrix.json").read_text(encoding="utf-8")
    assert "(none)" not in matrix_text
    assert "必须" in matrix_text
    assert "可选" in matrix_text
    assert "风险" in matrix_text


def test_launch_without_opencode_prints_engine_hint(monkeypatch, capsys):
    from prd_ai_battle.launch import launch_opencode

    monkeypatch.setattr("prd_ai_battle.launch.find_opencode", lambda: None)
    assert launch_opencode() == 1
    err = capsys.readouterr().err
    assert "brew install anomalyco/tap/opencode" in err
    assert "prd-ai-battle --offline" in err
    assert "demo" not in err.lower()
    assert "看板" in err or "board" in err.lower()


def test_default_and_tui_open_the_board_not_opencode(monkeypatch):
    called: list[str] = []

    def fake_tui(args):
        called.append("tui")
        return 0

    def fake_launch(args):
        called.append("launch")
        return 0

    monkeypatch.setattr("prd_ai_battle.cli.cmd_tui", fake_tui)
    monkeypatch.setattr("prd_ai_battle.cli.cmd_launch", fake_launch)
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 0
    assert called == ["tui"]

    called.clear()
    with pytest.raises(SystemExit):
        main(["tui"])
    assert called == ["tui"]

    called.clear()
    with pytest.raises(SystemExit):
        main(["--offline"])
    assert called == ["tui"]

    called.clear()
    with pytest.raises(SystemExit):
        main(["launch"])
    assert called == ["launch"]


def test_web_command_does_not_open_tui(monkeypatch):
    called: list[str] = []

    def fake_tui(args):
        called.append("tui")
        return 0

    def fake_web(args):
        called.append("web")
        return 0

    monkeypatch.setattr("prd_ai_battle.cli.cmd_tui", fake_tui)
    monkeypatch.setattr("prd_ai_battle.cli.cmd_web", fake_web)
    with pytest.raises(SystemExit) as exc:
        main(["web"])
    assert exc.value.code == 0
    assert called == ["web"]
    args = build_parser().parse_args(["web"])
    assert args.host == "127.0.0.1"
    assert args.port == 1780


def test_help_offline_is_not_demo():
    help_text = build_parser().format_help()
    assert "optional Textual demo" not in help_text
    assert "离线" in help_text
    assert "产品看板" in help_text
    assert "export" in help_text
    assert "web" in help_text
    assert "1780" in help_text


def test_branded_script_does_not_force_launch():
    text = Path("scripts/prd-ai-battle").read_text(encoding="utf-8")
    assert "prd_ai_battle launch" not in text
    assert 'prd_ai_battle "$@"' in text


def test_export_cli_missing_and_present_draft(tmp_path: Path, capsys):
    ws = tmp_path / "ws"
    args = build_parser().parse_args(
        ["export", "--offline", "--workspace", str(ws), "-o", str(tmp_path / "out")]
    )
    assert args.command == "export"
    assert cmd_export(args) == 0
    missing = capsys.readouterr().out
    assert '"draft_present": false' in missing
    assert "标书正文" in missing
    assert "响应对照表" in missing

    demo_args = build_parser().parse_args(["demo", "--workspace", str(ws)])
    assert cmd_demo(demo_args) == 0
    args2 = build_parser().parse_args(
        ["export", "--offline", "--workspace", str(ws), "-o", str(tmp_path / "out2")]
    )
    assert cmd_export(args2) == 0
    present = capsys.readouterr().out
    assert '"draft_present": true' in present
