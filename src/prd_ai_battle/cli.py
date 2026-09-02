"""CLI: launch OpenCode (default) | ingest | offline TUI | phase | write-check | demo."""

from __future__ import annotations

import argparse
import json
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
    ingest = sub.add_parser(
        "ingest",
        help="Extract brief + 对照表 seed from a 招标 PDF or markdown (local parse).",
        parents=[common],
    )
    ingest.add_argument(
        "path",
        type=Path,
        help="Path to a .pdf (parsed locally with pypdf) or .md tender.",
    )
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
    rec.add_argument("--actor", default="", help="Defaults to the configured primary id")
    rec.add_argument("--workspace", type=Path, default=None)
    rec.add_argument("--config", type=Path, default=None)
    rec.add_argument("--offline", action="store_true")

    cfgp = sub.add_parser("config", help="Show/set gitignored local Mac yaml (models, urls, keys).")
    cfg_sub = cfgp.add_subparsers(dest="config_action")
    cfg_sub.add_parser("show", help="Print last-saved local yaml (keys redacted)")
    cfg_init = cfg_sub.add_parser("init", help="Copy seed → gitignored prd-ai-battle.yaml")
    cfg_init.add_argument("--force", action="store_true", help="Overwrite existing local yaml from seed")
    setter = cfg_sub.add_parser("set", help="Change primary/advisors/base_url/keys and save locally")
    setter.add_argument("--primary-id")
    setter.add_argument("--primary-model")
    setter.add_argument("--primary-base-url")
    setter.add_argument("--primary-key-env")
    setter.add_argument("--primary-key", help="Stored in gitignored prd-ai-battle.env, not yaml")
    setter.add_argument("--advisor-id", help="Existing advisor id, or with --add-advisor a new one")
    setter.add_argument("--add-advisor", action="store_true")
    setter.add_argument("--model", help="Advisor model id (with --advisor-id)")
    setter.add_argument("--base-url", help="Advisor base_url (with --advisor-id)")
    setter.add_argument("--key-env", help="Advisor api_key_env (with --advisor-id)")
    setter.add_argument("--key", help="Advisor key → gitignored env file (with --advisor-id)")
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


def cmd_init(*, force: bool = False) -> int:
    from prd_ai_battle.config import ensure_local_config, local_yaml_path, seed_yaml_path

    dest = local_yaml_path()
    if dest.exists() and not force:
        print(f"already exists: {dest}  (gitignored local yaml — edit or `prd-ai-battle config set`)", file=sys.stderr)
        return 1
    wrote = ensure_local_config(force=force)
    print(
        f"wrote {wrote} from seed {seed_yaml_path().name}  "
        "(gitignored). Set keys with `prd-ai-battle config set --primary-key …` "
        "or export the api_key_env names."
    )
    return 0


def cmd_demo(args) -> int:
    from prd_ai_battle.session import run_offline_pipeline

    workspace = args.workspace or Path(".prd-ai-battle")
    result = __import__("asyncio").run(run_offline_pipeline(workspace))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_doctor(args) -> int:
    from prd_ai_battle.config import doctor_report, load_runtime_config

    cfg = load_runtime_config(
        explicit=getattr(args, "config", None),
        offline=True if getattr(args, "offline", False) else None,
        ensure_local=not getattr(args, "offline", False),
    )
    if args.workspace:
        cfg.workspace = str(args.workspace)
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

    return launch_opencode(repo=repo_root())


def cmd_config(args) -> int:
    from prd_ai_battle.config import (
        apply_user_set,
        doctor_report,
        ensure_local_config,
        load_runtime_config,
        local_env_path,
        local_yaml_path,
        save_local_config,
    )
    from prd_ai_battle.overlay import write_generated_opencode

    action = args.config_action or "show"
    if action == "init":
        return cmd_init(force=getattr(args, "force", False))
    cfg = load_runtime_config(ensure_local=True)
    if action == "show":
        report = doctor_report(cfg)
        report["local_yaml"] = str(local_yaml_path())
        report["local_env"] = str(local_env_path())
        print(json.dumps(report, indent=2))
        return 0
    if action == "set":
        keys = apply_user_set(
            cfg,
            primary_id=args.primary_id,
            primary_model=args.primary_model,
            primary_base_url=args.primary_base_url,
            primary_key_env=args.primary_key_env,
            primary_key=args.primary_key,
            advisor_id=args.advisor_id,
            advisor_model=args.model,
            advisor_base_url=args.base_url,
            advisor_key_env=args.key_env,
            advisor_key=args.key,
            add_advisor=args.add_advisor,
        )
        dest = save_local_config(cfg, keys=keys or None)
        overlay = write_generated_opencode(cfg)
        print(
            json.dumps(
                {
                    "saved": str(dest),
                    "env_file": str(local_env_path()) if keys else None,
                    "opencode_overlay": str(overlay),
                    "keys_written": sorted(keys),
                    "contract": doctor_report(cfg),
                },
                indent=2,
            )
        )
        return 0
    print("usage: prd-ai-battle config [show|init|set]", file=sys.stderr)
    return 2


def cmd_ingest(args) -> int:
    """PDF/markdown → text → brief → matrix seed. Raw PDF is never sent to advisors."""
    from prd_ai_battle.ingest import IngestError
    from prd_ai_battle.phase import cmd_ingest as run_ingest
    from prd_ai_battle.phase import dumps, load_session
    from prd_ai_battle.state import IllegalTransition

    session = load_session(
        workspace=args.workspace,
        config_path=args.config,
        offline=True if args.offline else None,
    )
    try:
        payload = run_ingest(session, args.path)
    except (IngestError, IllegalTransition, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    print(dumps(payload))
    return 0


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
        payload = run_record(session, args.path, actor_id=args.actor or session.state.primary)
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
    if command == "config":
        raise SystemExit(cmd_config(args))
    if command == "demo":
        raise SystemExit(cmd_demo(args))
    if command == "screenshot":
        raise SystemExit(cmd_screenshot(args))
    if command == "doctor":
        raise SystemExit(cmd_doctor(args))
    if command == "tui":
        raise SystemExit(cmd_tui(args))
    if command == "ingest":
        raise SystemExit(cmd_ingest(args))
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
