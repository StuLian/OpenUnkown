#!/usr/bin/env bash
#
# OpenUnknown 开发环境一键启动：uvicorn(--reload) + Vite(热更新)
#
# 用法：
#   ./dev.sh                # 同时启动前后端，支持热更新
#   OPEN_BROWSER=0 ./dev.sh # 不自动打开浏览器
#
# - 后端：http://127.0.0.1:8000（Python 文件改动自动重载）
# - 前端：http://localhost:5173 （React 源码改动即时热更新，/api 自动代理到后端）
# - 首次运行会自动创建 .venv 并安装前后端依赖
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
FRONTEND="$ROOT/frontend"
OPEN_BROWSER="${OPEN_BROWSER:-1}"

log() { printf '\033[1;36m[dev]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 环境检查 ----
command -v python3 >/dev/null 2>&1 || die "未找到 python3，请先安装 Python 3.10+"
command -v npm     >/dev/null 2>&1 || die "未找到 npm，请先安装 Node.js（https://nodejs.org）"

# ---- 后端虚拟环境 ----
if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  log "创建虚拟环境并安装后端依赖（首次）..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip -q
  "$VENV/bin/pip" install -r "$ROOT/requirements.txt" -q
fi

# ---- 前端依赖 ----
if [[ ! -d "$FRONTEND/node_modules" ]]; then
  log "安装前端依赖（首次）..."
  ( cd "$FRONTEND" && npm install --no-audit --no-fund )
fi

# ---- 启动后端（后台 + 热重载；端口被占用则跳过，前端代理到现有服务）----
port_in_use() {
  command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

BACKEND_PID=""
if port_in_use 8000; then
  log "检测到 8000 端口已有后端服务，跳过启动（前端将代理到该服务）"
else
  log "启动后端 uvicorn（--reload）：http://127.0.0.1:8000"
  "$VENV/bin/uvicorn" backend.main:app --reload --host 127.0.0.1 --port 8000 &
  BACKEND_PID=$!
fi

cleanup() {
  if [[ -n "$BACKEND_PID" ]]; then
    printf '\n'
    log "正在停止后端服务..."
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

# ---- 启动前端（前台 + HMR）----
if [[ "$OPEN_BROWSER" == "1" ]] && command -v open >/dev/null 2>&1; then
  ( sleep 1; open "http://localhost:5173" ) >/dev/null 2>&1 &
fi

log "启动前端 Vite（热更新）：     http://localhost:5173"
log "按 Ctrl+C 同时停止前后端"

( cd "$FRONTEND" && npm run dev -- --port 5173 --strictPort )
