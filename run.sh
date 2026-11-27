#!/usr/bin/env bash
# 智学 — 一键启动
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[1/2] 创建虚拟环境并安装依赖…"
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv --python 3.12
    uv pip install -r requirements.txt
  else
    python3 -m venv .venv
    ./.venv/bin/pip install -r requirements.txt
  fi
fi

[ -f .env ] || cp .env.example .env

PORT="${PORT:-8000}"
echo "[2/2] 启动服务: http://0.0.0.0:${PORT}"
exec ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
