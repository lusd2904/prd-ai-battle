# Local delivery surface: the Chinese Textual board.
# Not a cloud-host / PaaS deploy. Never bake API keys into the image.
#
# Default CMD opens the product board (`prd-ai-battle` / tui).
# Offline discuss is an explicit command, not the default:
#   docker compose run --rm prd-ai-battle discuss --offline

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TERM=xterm-256color \
    PRD_HOST_CONFIG=/host

WORKDIR /app

# Product only. .dockerignore keeps gitignored yaml/env and workspaces out.
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY schemas ./schemas
COPY samples ./samples
COPY config.example.yaml prd-ai-battle.env.example ./
COPY opencode.json ./
COPY .opencode ./.opencode
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN pip install --no-cache-dir . \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
# Product board — not `discuss --offline`.
CMD ["prd-ai-battle"]
