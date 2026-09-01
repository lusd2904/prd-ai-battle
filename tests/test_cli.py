from pathlib import Path

from prd_ai_battle.cli import build_parser, cmd_demo


def test_demo_accepts_workspace_after_subcommand(tmp_path: Path):
    args = build_parser().parse_args(["demo", "--workspace", str(tmp_path)])
    assert args.command == "demo"
    assert args.workspace == tmp_path
    assert cmd_demo(args) == 0
    assert (tmp_path / "drafts" / "v1" / "response.md").is_file()
    assert (tmp_path / "drafts" / "v2" / "response.md").is_file()
    assert (tmp_path / "matrix.json").is_file()
    assert (tmp_path / "transcript.jsonl").is_file()
