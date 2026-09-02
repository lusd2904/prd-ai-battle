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
    ROOT / ".opencode" / "agents" / "advisor-glm.md",
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
    ROOT / "prd-ai-battle.env.example",
]


def test_overlay_files_exist():
    missing = [str(p) for p in OVERLAY_FILES if not p.is_file()]
    assert missing == []


def test_opencode_json_seed_has_primary_and_two_advisors():
    cfg = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    agents = cfg.get("agent") or cfg.get("agents")
    assert "primary" in agents
    assert "advisor-sonnet" in agents
    assert "advisor-glm" in agents
    assert "advisor-grok" not in agents
    # Seed snapshot only — runtime overlay is generated from local yaml.
    assert agents["primary"]["model"].endswith("claude-opus-5")
    sonnet_perm = agents["advisor-sonnet"].get("permission") or {}
    assert sonnet_perm.get("edit") == "deny"
    glm_perm = agents["advisor-glm"].get("permission") or {}
    assert glm_perm.get("edit") == "deny"


def test_providers_use_env_interpolation_not_secrets():
    raw = (ROOT / "opencode.json").read_text(encoding="utf-8")
    assert "https://xixiapi.io/v1" in raw
    assert "https://openrouter.ai/api/v1" in raw
    assert "https://opencode.ai/zen/v1" in raw
    assert "http://127.0.0.1:8000/v1" in raw
    assert "{env:PRD_SFP_XIXI_KEY}" in raw
    assert "{env:PRD_SFP_OPENROUTER_KEY}" in raw
    assert "{env:PRD_OPENCODE_ZEN_KEY}" in raw
    assert "PRD_AI_GATEWAY_KEY" in raw
    assert "prd-codex" in raw
    assert "prd-claude-code" in raw
    assert "prd-antigravity" in raw
    assert "prd-gemini" in raw
    assert "prd-xai" in raw
    assert "opencode" in raw
    assert "{env:PRD_CODEX_KEY}" in raw
    assert "{env:PRD_XAI_KEY}" in raw
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(raw), f"secret-like value in opencode.json: {pattern.pattern}"


def test_seed_prd_gateway_models_are_grok_not_claude():
    for path in (ROOT / "opencode.json", ROOT / ".opencode" / "opencode.json"):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        for block in (cfg["provider"]["prd-gateway"], cfg["providers"]["prd-gateway"]):
            models = set(block["models"])
            assert "grok-4.5" in models
            assert "grok-composer-2.5-fast" in models
            assert "claude-opus-5" not in models
            assert "claude-sonnet-5" not in models
            assert not any(m.startswith("claude") for m in models)
        xixi = set(cfg["provider"]["prd-xixi"]["models"])
        assert "claude-opus-5" in xixi
        assert "claude-sonnet-5" in xixi
        openrouter = set(cfg["provider"]["prd-openrouter"]["models"])
        assert "z-ai/glm-5.2:free" in openrouter
        assert "meta/muse-spark-1.2" in openrouter
        zen = set(cfg["provider"]["opencode"]["models"])
        assert "mimo-v2.5-free" in zen
        assert "big-pickle" in zen


def test_write_lock_plugin_is_in_repo_hook_not_npm_package():
    plugin = (ROOT / ".opencode" / "plugins" / "write-lock.js").read_text(encoding="utf-8")
    assert "tool.execute.before" in plugin
    assert "permission.ask" in plugin
    assert "write-check" in plugin
    assert "runWriteCheck" in plugin
    assert "evaluateWriteCheck" in plugin
    assert "NOT an npm plugin" in plugin or "not an npm plugin" in plugin.lower()
    assert "WriteLockHook" in plugin
    # Both OpenCode gates must call write-check — not actor !== primary alone.
    ask = plugin.split('"permission.ask"')[1].split('"tool.execute.before"')[0]
    before = plugin.split('"tool.execute.before"')[1].split('"tool.execute.after"')[0]
    assert "decide(" in ask and "decide(" in before
    assert "phase\", \"status\"" not in ask
    assert "actor !== primary" not in ask


def test_advisor_markdown_denies_edit_and_does_not_pin_a_model():
    for name in ("advisor-sonnet.md", "advisor-glm.md", "advisor-grok.md", "primary.md"):
        text = (ROOT / ".opencode" / "agents" / name).read_text(encoding="utf-8")
        front, _, _ = text.partition("---\n")
        body_front = text.split("---", 2)[1]
        assert "edit: deny" in body_front or name == "primary.md"
        assert "model:" not in body_front
        if name != "primary.md":
            assert "bash: deny" in body_front
            assert "tools=[]" in text or "tools: []" in text.replace(" ", "")


def test_commands_drive_python_state_machine():
    for name in ("lock", "execute", "review", "revise"):
        text = (ROOT / ".opencode" / "commands" / f"{name}.md").read_text(encoding="utf-8")
        assert f"phase {name}" in text or f"prd_ai_battle phase {name}" in text
    discuss = (ROOT / ".opencode" / "commands" / "discuss.md").read_text(encoding="utf-8")
    assert "prd_ai_battle discuss" in discuss
    assert "do not abort discuss" in discuss.lower()
    assert "shared" in discuss.lower() and "timeline" in discuss.lower()
    for banned in ("advisor-sonnet", "advisor-grok", "advisor-glm", "subagents/teammates", "Agent Teams shape"):
        assert banned not in discuss
    review = (ROOT / ".opencode" / "commands" / "review.md").read_text(encoding="utf-8")
    assert "advisor-sonnet" not in review
    assert "advisor-grok" not in review
    assert "advisor-glm" not in review
    assert "sidecar" in discuss.lower() or "teammate" in discuss.lower()


def test_readme_leads_with_product_board_not_demo():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "optional Textual demo" not in readme
    assert "optional textual demo" not in readme.lower()
    board_at = readme.find("Textual board")
    assert board_at != -1
    assert board_at < readme.find("prd-ai-battle launch")
    assert "--offline" in readme
    assert "不是演示" in readme or "not a demo" in readme.lower() or "不是演示模式" in readme
    assert "Do not deploy" in readme or "cloud VM" in readme
    assert "gitignored" in readme.lower() or "prd-ai-battle.yaml" in readme
    assert "config set" in readme
    assert "prd-ai-battle.env" in readme
    assert "prd-ai-battle.env.example" in readme
    assert "prd-ai-battle ping" in readme
    assert "prd-ai-battle discuss" in readme
    assert "prd-ai-battle export" in readme
    assert "group chat" in readme.lower() or "交叉讨论" in readme or "group-chat" in readme.lower()
    assert "grok-4.5" in readme
    assert "do not ship a plugin" in readme.lower() or "not an npm" in readme.lower()
    assert "brew install anomalyco/tap/opencode" in readme
    assert "transport: cli" in readme or "--primary-transport cli" in readme
    assert "claude" in readme.lower()
    assert "antigravity" in readme.lower() or "反重力" in readme
    assert "codex" in readme.lower()
    assert "write_lock" in readme
