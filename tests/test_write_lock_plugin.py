"""Drive the OpenCode write-lock plugin with Node so both hooks stay fail-closed."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / ".opencode" / "plugins" / "write-lock.js"
HARNESS = Path(__file__).resolve().parent / "test_write_lock_plugin.mjs"


def test_plugin_harness_fail_closed():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to exercise write-lock.js")
    result = subprocess.run(
        [node, str(HARNESS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and "--experimental-default-type=module" not in result.stderr:
        # Fallback for legacy node configurations if needed
        result = subprocess.run(
            [node, "--experimental-default-type=module", str(HARNESS)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "ok" in result.stdout


def test_plugin_source_both_hooks_call_write_check():
    text = PLUGIN.read_text(encoding="utf-8")
    assert "python3" in text or "prd_ai_battle" in text
    assert '["write-check"' in text or '"write-check"' in text
    assert "--actor" in text and "--tool" in text and "--path" in text
    assert "createWriteLockHook" in text
    ask_idx = text.index('"permission.ask"')
    before_idx = text.index('"tool.execute.before"')
    decide_first = text.index("runWriteCheck")
    assert decide_first < ask_idx or "decide(" in text[ask_idx:before_idx]
    assert "decide(" in text[before_idx:]
