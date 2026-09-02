"""The repo is the product overlay, not an npm plugin."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"sk-or-[A-Za-z0-9]{8,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_\-]{12,}['\"]", re.I),
)

OVERLAY_FILES = [
    ROOT / "opencode.json",
    ROOT / ".opencode" / "opencode.json",
    ROOT / ".opencode" / "agents" / "primary.md",
    ROOT / ".opencode" / "agents" / "advisor-sonnet.md",
    ROOT / ".opencode" / "agents" / "advisor-grok.md",
    ROOT / ".opencode" / "commands" / "discuss.md",
    ROOT / ".opencode" / "commands" / "lock.md",
    ROOT / ".opencode" / "commands" / "execute.md",
    ROOT / ".opencode" / "commands" / "review.md",
    ROOT / ".opencode" / "commands" / "revise.md",
    ROOT / ".opencode" / "plugins" / "write-lock.js",
    ROOT / ".opencode" / "skills" / "prd-battle" / "SKILL.md",
    ROOT / "scripts" / "prd-ai-battle",
    ROOT / "AGENTS.md",
]


def test_overlay_files_exist():
    missing = [str(p) for p in OVERLAY_FILES if not p.is_file()]
    assert missing == []


def test_opencode_json_seed_has_primary_and_two_advisors():
    cfg = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    agents = cfg.get("agent") or cfg.get("agents")
    assert "primary" in agents
    assert "advisor-sonnet" in agents
    assert "advisor-grok" in agents
    # Seed snapshot only — runtime overlay is generated from local yaml.
    assert agents["primary"]["model"].endswith("claude-opus-5")
    sonnet_perm = agents["advisor-sonnet"].get("permission") or {}
    assert sonnet_perm.get("edit") == "deny"
    grok_perm = agents["advisor-grok"].get("permission") or {}
    assert grok_perm.get("edit") == "deny"


def test_providers_use_env_interpolation_not_secrets():
    raw = (ROOT / "opencode.json").read_text(encoding="utf-8")
    assert "https://xixiapi.io/v1" in raw
    assert "https://openrouter.ai/api/v1" in raw
    assert "http://127.0.0.1:8000/v1" in raw
    assert "{env:PRD_SFP_XIXI_KEY}" in raw
    assert "{env:PRD_SFP_OPENROUTER_KEY}" in raw
    assert "PRD_AI_GATEWAY_KEY" in raw
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(raw), f"secret-like value in opencode.json: {pattern.pattern}"


def test_write_lock_plugin_is_in_repo_hook_not_npm_package():
    plugin = (ROOT / ".opencode" / "plugins" / "write-lock.js").read_text(encoding="utf-8")
    assert "tool.execute.before" in plugin
    assert "write-check" in plugin
    assert "NOT an npm plugin" in plugin or "not an npm plugin" in plugin.lower()
    assert "WriteLockHook" in plugin


def test_advisor_markdown_denies_edit_and_does_not_pin_a_model():
    for name in ("advisor-sonnet.md", "advisor-grok.md", "primary.md"):
        text = (ROOT / ".opencode" / "agents" / name).read_text(encoding="utf-8")
        front, _, _ = text.partition("---\n")
        body_front = text.split("---", 2)[1]
        assert "edit: deny" in body_front or name == "primary.md"
        assert "model:" not in body_front
        if name != "primary.md":
            assert "bash: deny" in body_front
            assert "tools=[]" in text or "tools: []" in text.replace(" ", "")


def test_commands_drive_python_state_machine():
    for name in ("discuss", "lock", "execute", "review", "revise"):
        text = (ROOT / ".opencode" / "commands" / f"{name}.md").read_text(encoding="utf-8")
        assert f"phase {name}" in text or f"prd_ai_battle phase {name}" in text


def test_readme_leads_with_opencode_mac_not_textual():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "brew install anomalyco/tap/opencode" in readme
    assert readme.find("brew install") < readme.find("prd-ai-battle --offline")
    assert "Mac only" in readme or "Mac only" in readme.replace("\n", " ")
    assert "Do not deploy" in readme or "cloud VM" in readme
    assert "gitignored" in readme.lower() or "prd-ai-battle.yaml" in readme
    assert "config set" in readme
    assert "prd-ai-battle.env" in readme
    assert "do not ship a plugin" in readme.lower() or "not an npm" in readme.lower()
