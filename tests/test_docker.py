"""Docker is the local board delivery surface — not a cloud deploy, no secrets."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_defaults_to_board_not_offline_discuss():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "CMD [\"prd-ai-battle\"]" in text
    assert "discuss --offline" in text  # documented as explicit, not default
    cmd_line = [ln for ln in text.splitlines() if ln.startswith("CMD ")]
    assert cmd_line == ['CMD ["prd-ai-battle"]']
    assert "ENTRYPOINT" in text
    assert "PRD_SFP_XIXI_KEY=" not in text
    assert "sk-" not in text
    assert "Bearer" not in text


def test_dockerignore_keeps_secrets_out_of_image():
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "prd-ai-battle.yaml" in text
    assert "prd-ai-battle.env" in text
    assert ".prd-ai-battle" in text


def test_compose_tty_stdin_extra_hosts_optional_env_and_host_yaml():
    path = ROOT / "docker-compose.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    svc = data["services"]["prd-ai-battle"]
    assert svc["stdin_open"] is True
    assert svc["tty"] is True
    assert svc["image"] == "prd-ai-battle:local"
    assert svc["command"] == ["prd-ai-battle"]
    hosts = svc["extra_hosts"]
    assert "host.docker.internal:host-gateway" in hosts
    env_file = svc["env_file"]
    assert any(
        (item.get("path") == "prd-ai-battle.env" and item.get("required") is False)
        if isinstance(item, dict)
        else False
        for item in env_file
    )
    volumes = svc["volumes"]
    sources = []
    targets = []
    for item in volumes:
        if isinstance(item, dict):
            sources.append(item.get("source"))
            targets.append(item.get("target"))
        else:
            sources.append(str(item))
    assert "." in sources
    assert "/host" in targets
    assert any(t == "/app/.prd-ai-battle" for t in targets)
    raw = path.read_text(encoding="utf-8")
    assert "deploy:" not in raw
    assert "paas" not in raw.lower()
    assert "sk-" not in raw
    assert "prd-ai-battle.yaml" in raw  # documented / linked if present
    assert "host.docker.internal" in raw


def test_entrypoint_links_host_yaml_and_keeps_offline_discuss_explicit():
    text = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "prd-ai-battle.yaml" in text
    assert "prd-ai-battle.env" in text
    assert "discuss --offline" in text
    assert "docker compose run --rm prd-ai-battle" in text
    assert "exec prd-ai-battle" in text
    assert "sk-" not in text


def test_readme_documents_compose_run_env_and_http_speakers():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docker compose build" in text
    assert "docker compose run --rm prd-ai-battle" in text
    assert "discuss --offline" in text
    assert "HTTP" in text
    assert "host.docker.internal" in text
    assert "codex" in text and "agy" in text
    assert "Mac host" in text or "Mac host" in text.replace("宿主机", "host")
    assert "execute" in text.lower() and "review" in text.lower()
    assert "live execute" in text.lower() or "不声称 live execute" in text
    assert "prd-ai-battle.env" in text
    assert "cloud-host" in text.lower() or "云部署" in text
