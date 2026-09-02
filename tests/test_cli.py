from pathlib import Path

from prd_ai_battle.cli import build_parser, cmd_demo, cmd_doctor


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


def test_launch_without_opencode_prints_mac_install_hint(monkeypatch, capsys):
    from prd_ai_battle.launch import launch_opencode

    monkeypatch.setattr("prd_ai_battle.launch.find_opencode", lambda: None)
    assert launch_opencode() == 1
    err = capsys.readouterr().err
    assert "brew install anomalyco/tap/opencode" in err
    assert "prd-ai-battle --offline" in err
