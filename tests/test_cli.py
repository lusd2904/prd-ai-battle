from pathlib import Path

from prd_ai_battle.cli import build_parser, cmd_demo, cmd_doctor, cmd_ingest
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


def test_launch_without_opencode_prints_mac_install_hint(monkeypatch, capsys):
    from prd_ai_battle.launch import launch_opencode

    monkeypatch.setattr("prd_ai_battle.launch.find_opencode", lambda: None)
    assert launch_opencode() == 1
    err = capsys.readouterr().err
    assert "brew install anomalyco/tap/opencode" in err
    assert "prd-ai-battle --offline" in err
