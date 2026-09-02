"""Launch OpenCode as the prd-ai-battle product shell (Mac)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

INSTALL_HINT = """prd-ai-battle uses OpenCode as its TUI shell.

This product runs on Mac only. Install OpenCode, then relaunch from this repo:

  brew install anomalyco/tap/opencode

  cd /path/to/prd-ai-battle
  python3 -m venv .venv && source .venv/bin/activate
  pip install -e ".[dev]"
  prd-ai-battle init
  prd-ai-battle config set --primary-key ... --advisor-id advisor-grok --key ...
  prd-ai-battle

Do not deploy this to a cloud VM. The Textual demo is still available with:

  prd-ai-battle --offline
"""


def repo_root() -> Path:
    """Walk up from CWD (and this file) looking for the product overlay."""

    from prd_ai_battle.config import repo_paths

    return repo_paths()


def find_opencode() -> str | None:
    return shutil.which("opencode") or shutil.which("opencode2")


def prepare_launch(repo: Path | None = None):
    """Load last-saved yaml, keys env, and generate the OpenCode overlay."""
    from prd_ai_battle.config import load_runtime_config, local_env_path, local_yaml_path
    from prd_ai_battle.overlay import write_generated_opencode

    root = repo or repo_root()
    cfg = load_runtime_config(repo=root, ensure_local=True)
    overlay = write_generated_opencode(cfg, root)
    return cfg, overlay, local_yaml_path(root), local_env_path(root)


def launch_env(repo: Path, overlay: Path) -> dict[str, str]:
    env = os.environ.copy()
    src = repo / "src"
    pythonpath = str(src)
    existing = env.get("PYTHONPATH", "")
    if existing:
        pythonpath = pythonpath + os.pathsep + existing
    env["PYTHONPATH"] = pythonpath
    env["PRD_AI_ROOT"] = str(repo)
    env["PRD_AI_PYTHON"] = sys.executable
    env.setdefault("OPENCODE_EXPERIMENTAL_AGENT_TEAMS", "1")
    # Generated overlay from local yaml wins over committed seed opencode.json.
    env["OPENCODE_CONFIG"] = str(overlay)
    try:
        env["OPENCODE_CONFIG_CONTENT"] = overlay.read_text(encoding="utf-8")
    except OSError:
        pass
    return env


def launch_command(repo: Path | None = None, extra_args: list[str] | None = None) -> list[str]:
    binary = find_opencode()
    if not binary:
        raise FileNotFoundError("opencode is not installed")
    args = [binary]
    if extra_args:
        args.extend(extra_args)
    return args


def launch_opencode(
    *,
    repo: Path | None = None,
    extra_args: list[str] | None = None,
    dry_run: bool = False,
) -> int:
    root = repo or repo_root()
    binary = find_opencode()
    if not binary:
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    _cfg, overlay, yaml_path, env_path = prepare_launch(root)
    argv = launch_command(root, extra_args)
    env = launch_env(root, overlay)
    if dry_run:
        print(" ".join(argv))
        print(f"cwd={root}")
        print(f"config={yaml_path}")
        print(f"envfile={env_path}")
        print(f"opencode_overlay={overlay}")
        return 0
    os.chdir(root)
    os.execvpe(argv[0], argv, env)
    return 0  # pragma: no cover — exec never returns
