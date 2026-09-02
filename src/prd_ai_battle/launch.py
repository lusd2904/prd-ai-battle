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
  export PRD_SFP_XIXI_KEY=...          # xixiapi.io
  export PRD_SFP_OPENROUTER_KEY=...    # openrouter.ai
  prd-ai-battle

Do not deploy this to a cloud VM. The Textual demo is still available with:

  prd-ai-battle --offline
"""


def repo_root() -> Path:
    """Walk up from CWD (and this file) looking for the product overlay."""

    candidates = [Path.cwd(), *Path.cwd().parents]
    here = Path(__file__).resolve()
    candidates.extend([here.parents[2], here.parents[1]])
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        if (path / "opencode.json").is_file() or (path / ".opencode" / "opencode.json").is_file():
            return path
    return Path.cwd()


def find_opencode() -> str | None:
    return shutil.which("opencode") or shutil.which("opencode2")


def launch_env(repo: Path) -> dict[str, str]:
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
    argv = launch_command(root, extra_args)
    env = launch_env(root)
    if dry_run:
        print(" ".join(argv))
        print(f"cwd={root}")
        return 0
    os.chdir(root)
    os.execvpe(argv[0], argv, env)
    return 0  # pragma: no cover — exec never returns
