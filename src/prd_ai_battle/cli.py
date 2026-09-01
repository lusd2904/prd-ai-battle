"""CLI: tui | demo | init | screenshot."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        type=Path,
        default=None,
        help="YAML config (default: ./prd-ai-battle.yaml, else offline mocks).",
    )
    common.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Override workspace directory.",
    )
    common.add_argument(
        "--offline",
        action="store_true",
        help="Force mock models (no network).",
    )
    common.add_argument(
        "--requirement",
        type=Path,
        default=None,
        help="Requirement / 招标文件 to load on start.",
    )
    parser = argparse.ArgumentParser(
        prog="prd-ai-battle",
        description="Local TUI for multi-model PRD / bid collaborative drafting.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("tui", help="Launch the TUI (default).", parents=[common])
    sub.add_parser("demo", help="Run the offline discuss → lock → write → review pipeline.", parents=[common])
    sub.add_parser("init", help="Write config.example.yaml → ./prd-ai-battle.yaml")
    shot = sub.add_parser("screenshot", help="Headless TUI snapshot (SVG).", parents=[common])
    shot.add_argument("-o", "--output", type=Path, default=Path("prd-ai-battle.screenshot.svg"))
    return parser


def _config(args):
    from prd_ai_battle.config import find_config, load_config

    path = find_config(args.config)
    offline = True if args.offline else None
    if path is None and not args.offline:
        # Zero-config first run: mock models so the TUI always boots.
        offline = True
    cfg = load_config(path, offline=offline)
    if getattr(args, "workspace", None):
        cfg.workspace = str(args.workspace)
    return cfg


def cmd_init() -> int:
    dest = Path("prd-ai-battle.yaml")
    src = Path(__file__).resolve().parents[2] / "config.example.yaml"
    if not src.exists():
        src = Path("config.example.yaml")
    if dest.exists():
        print(f"already exists: {dest}", file=sys.stderr)
        return 1
    shutil.copy(src, dest)
    print(f"wrote {dest}  (set API keys via env vars, or pass --offline)")
    return 0


def cmd_demo(args) -> int:
    from prd_ai_battle.session import run_offline_pipeline

    workspace = args.workspace or Path(".prd-ai-battle")
    result = asyncio.run(run_offline_pipeline(workspace))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_tui(args) -> int:
    from prd_ai_battle.tui.app import BattleApp

    cfg = _config(args)
    app = BattleApp(cfg, requirement=args.requirement)
    app.run()
    return 0


def cmd_screenshot(args) -> int:
    from prd_ai_battle.config import default_offline_config
    from prd_ai_battle.tui.app import BattleApp

    async def _run() -> None:
        cfg = default_offline_config()
        if args.workspace:
            cfg.workspace = str(args.workspace)
        app = BattleApp(cfg, requirement=None, screenshot_ready=True)
        async with app.run_test(size=(140, 42)) as pilot:
            app.action_load_sample()
            await pilot.pause(0.05)
            app.action_discuss()
            for _ in range(40):
                await pilot.pause(0.05)
                if not app._busy:
                    break
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=out.name, path=str(out.parent.resolve()))

    asyncio.run(_run())
    print(f"wrote {args.output}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "tui"
    if command == "init":
        raise SystemExit(cmd_init())
    if command == "demo":
        raise SystemExit(cmd_demo(args))
    if command == "screenshot":
        raise SystemExit(cmd_screenshot(args))
    raise SystemExit(cmd_tui(args))
