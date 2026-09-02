"""CLI: launch OpenCode (default) | offline TUI | phase | write-check | demo."""

from __future__ import annotations

import argparse
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
        help="Force mock models / Textual demo (no network).",
    )
    common.add_argument(
        "--requirement",
        type=Path,
        default=None,
        help="Requirement / 招标文件 to load on start.",
    )
    parser = argparse.ArgumentParser(
        prog="prd-ai-battle",
        description=(
            "prd-ai-battle — multi-model PRD / bid drafting. "
            "Default: launch OpenCode in this repo (Mac). "
            "Use --offline for the optional Textual demo."
        ),
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("launch", help="Launch OpenCode as this product's TUI (default).", parents=[common])
    sub.add_parser("tui", help="Optional Textual demo (not the product shell).", parents=[common])
    sub.add_parser("demo", help="Run the offline discuss → lock → write → review pipeline.", parents=[common])
    sub.add_parser("init", help="Write config.example.yaml → ./prd-ai-battle.yaml")
    sub.add_parser("doctor", help="Print resolved provider base_url (keys redacted).", parents=[common])
    shot = sub.add_parser("screenshot", help="Headless Textual snapshot (SVG).", parents=[common])
    shot.add_argument("-o", "--output", type=Path, default=Path("prd-ai-battle.screenshot.svg"))

    phase = sub.add_parser("phase", help="Drive discuss → locked → execute → review → revise.")
    phase.add_argument(
        "action",
        choices=["status", "ingest", "discuss", "lock", "execute", "review", "revise"],
    )
    phase.add_argument("--workspace", type=Path, default=None)
    phase.add_argument("--config", type=Path, default=None)
    phase.add_argument("--offline", action="store_true")
    phase.add_argument("--requirement", type=Path, default=None)
    phase.add_argument(
        "--packet",
        action="store_true",
        help="With review: print only the review packet (brief+matrix+chapter_diff).",
    )

    check = sub.add_parser("write-check", help="Ask the write_lock whether a tool call is allowed.")
    check.add_argument("--actor", required=True, help="OpenCode agent id (primary, advisor-sonnet, …)")
    check.add_argument("--tool", required=True, help="Tool name (write, edit, bash, read, …)")
    check.add_argument("--path", default="", help="Filesystem path the tool wants to touch")
    check.add_argument("--workspace", type=Path, default=None)
    check.add_argument("--config", type=Path, default=None)
    check.add_argument("--offline", action="store_true")

    rec = sub.add_parser("record-draft", help="Record an OpenCode write as the next artifact_version.")
    rec.add_argument("--path", required=True)
    rec.add_argument("--actor", default="primary")
    rec.add_argument("--workspace", type=Path, default=None)
    rec.add_argument("--config", type=Path, default=None)
    rec.add_argument("--offline", action="store_true")
    return parser


def _config(args):
    from prd_ai_battle.config import find_config, load_config

    path = find_config(getattr(args, "config", None))
    offline = True if getattr(args, "offline", False) else None
    if path is None and not getattr(args, "offline", False) and getattr(args, "command", None) in {
        "tui",
        "screenshot",
        None,
    }:
        # Zero-config Textual first run: mock models so the demo always boots.
        if getattr(args, "command", None) == "tui":
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
    print(
        f"wrote {dest}  — export PRD_SFP_XIXI_KEY / PRD_SFP_OPENROUTER_KEY "
        "(or PRD_AI_GATEWAY_KEY for the local backup)"
    )
    return 0


def cmd_demo(args) -> int:
    from prd_ai_battle.session import run_offline_pipeline

    workspace = args.workspace or Path(".prd-ai-battle")
    result = __import__("asyncio").run(run_offline_pipeline(workspace))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_doctor(args) -> int:
    from prd_ai_battle.config import doctor_report, load_config, find_config, default_live_config

    path = find_config(args.config)
    if path is None:
        cfg = default_live_config()
        if args.offline:
            cfg.offline = True
        if args.workspace:
            cfg.workspace = str(args.workspace)
    else:
        cfg = _config(args)
    print(json.dumps(doctor_report(cfg), indent=2))
    return 0


def cmd_tui(args) -> int:
    from prd_ai_battle.tui.app import BattleApp

    cfg = _config(args)
    if args.offline:
        cfg.offline = True
    app = BattleApp(cfg, requirement=args.requirement)
    app.run()
    return 0


def cmd_screenshot(args) -> int:
    from prd_ai_battle.config import default_offline_config
    from prd_ai_battle.tui.app import BattleApp
    import asyncio

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


def cmd_launch(args) -> int:
    from prd_ai_battle.launch import launch_opencode, repo_root

    extra: list[str] = []
    return launch_opencode(repo=repo_root(), extra_args=extra or None)


def cmd_phase(args) -> int:
    from prd_ai_battle.phase import dumps, load_session
    from prd_ai_battle.phase import (
        cmd_discuss,
        cmd_execute,
        cmd_ingest,
        cmd_lock,
        cmd_review,
        cmd_revise,
        cmd_status,
    )
    from prd_ai_battle.state import IllegalTransition

    session = load_session(
        workspace=args.workspace,
        config_path=args.config,
        offline=True if args.offline else None,
    )
    try:
        if args.action == "status":
            payload = cmd_status(session)
        elif args.action == "ingest":
            payload = cmd_ingest(session, args.requirement)
        elif args.action == "discuss":
            payload = cmd_discuss(session, args.requirement)
        elif args.action == "lock":
            payload = cmd_lock(session)
        elif args.action == "execute":
            payload = cmd_execute(session)
        elif args.action == "review":
            payload = cmd_review(session)
            if args.packet:
                print(payload["review_packet"])
                return 0
        elif args.action == "revise":
            payload = cmd_revise(session)
        else:
            print(f"unknown phase action {args.action}", file=sys.stderr)
            return 2
    except (IllegalTransition, Exception) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    print(dumps(payload))
    return 0


def cmd_write_check(args) -> int:
    from prd_ai_battle.phase import cmd_write_check as run_check
    from prd_ai_battle.phase import dumps, load_session

    session = load_session(
        workspace=args.workspace,
        config_path=args.config,
        offline=True if args.offline else None,
    )
    payload = run_check(session, actor=args.actor, tool=args.tool, path=args.path or None)
    print(dumps(payload))
    return 0 if payload.get("ok") else 2


def cmd_record_draft(args) -> int:
    from prd_ai_battle.phase import cmd_record_draft as run_record
    from prd_ai_battle.phase import dumps, load_session
    from prd_ai_battle.write_lock import WriteDenied

    session = load_session(
        workspace=args.workspace,
        config_path=args.config,
        offline=True if args.offline else None,
    )
    try:
        payload = run_record(session, args.path, actor_id=args.actor)
    except (WriteDenied, Exception) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    print(dumps(payload))
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    if command == "init":
        raise SystemExit(cmd_init())
    if command == "demo":
        raise SystemExit(cmd_demo(args))
    if command == "screenshot":
        raise SystemExit(cmd_screenshot(args))
    if command == "doctor":
        raise SystemExit(cmd_doctor(args))
    if command == "tui":
        raise SystemExit(cmd_tui(args))
    if command == "phase":
        raise SystemExit(cmd_phase(args))
    if command == "write-check":
        raise SystemExit(cmd_write_check(args))
    if command == "record-draft":
        raise SystemExit(cmd_record_draft(args))
    if command == "launch" or command is None:
        if getattr(args, "offline", False):
            raise SystemExit(cmd_tui(args))
        raise SystemExit(cmd_launch(args))
    raise SystemExit(cmd_tui(args))
