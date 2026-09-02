#!/bin/sh
# Docker entry: open the Chinese board by default. Link host yaml/env if present.
# Secrets stay on the host bind / env_file — never in the image.
set -eu

host="${PRD_HOST_CONFIG:-/host}"

if [ -f "$host/prd-ai-battle.yaml" ]; then
  ln -sfn "$host/prd-ai-battle.yaml" /app/prd-ai-battle.yaml
fi
if [ -f "$host/prd-ai-battle.env" ]; then
  ln -sfn "$host/prd-ai-battle.env" /app/prd-ai-battle.env
fi

if [ "$#" -eq 0 ]; then
  set -- prd-ai-battle
fi

# Detect default board invocation (prd-ai-battle / tui / --offline flags only).
board=0
if [ "$1" = "prd-ai-battle" ] || [ "$1" = "tui" ]; then
  board=1
  if [ "$1" = "prd-ai-battle" ] && [ "$#" -gt 1 ]; then
    case "$2" in
      tui|--offline|-*) board=1 ;;
      *) board=0 ;;
    esac
  fi
fi

if [ "$board" -eq 1 ] && [ ! -t 0 ]; then
  echo "看板需要交互式 TTY。Docker Desktop 请运行：" >&2
  echo "  docker compose build && docker compose run --rm prd-ai-battle" >&2
  echo "不要使用 docker compose up -d（看板不是后台服务；--rm 退出后没有常驻容器是正常的）。" >&2
  echo "离线交叉讨论（显式命令，不是默认）：" >&2
  echo "  docker compose run --rm prd-ai-battle discuss --offline" >&2
  exit 2
fi

if [ "$1" = "prd-ai-battle" ]; then
  shift
  exec prd-ai-battle "$@"
fi

case "$1" in
  tui|web|demo|init|doctor|ping|discuss|ingest|export|screenshot|phase|write-check|record-draft|launch|config|-*)
    exec prd-ai-battle "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
