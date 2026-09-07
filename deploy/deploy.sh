#!/usr/bin/env bash
#
# OpenUnknown 服务器端一键部署脚本（在服务器上以 root 执行，幂等，可重复运行用于更新）
#
# 前置：
#   - 代码已解压到 /opt/openunknown（由本地 deploy_local.sh 上传并解压）
#   - 证书可上传到 /tmp/chat_fullchain.pem、/tmp/chat_privkey.pem（由 deploy_local.sh 完成）
#
# 用法（通常由 deploy_local.sh 自动调用，也可手动）：
#   sudo DOMAIN=chat.j71995.cn bash /opt/openunknown/deploy/deploy.sh
#
set -euo pipefail

# ===================== 配置（可用环境变量覆盖）=====================
APP_DIR="${APP_DIR:-/opt/openunknown}"
APP_USER="${APP_USER:-openunknown}"
VENV_DIR="$APP_DIR/.venv"
PORT="${PORT:-8000}"
PIP_INDEX="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"
DOMAIN="${DOMAIN:-chat.j71995.cn}"
CERT_PEM="${CERT_PEM:-/tmp/chat_fullchain.pem}"
CERT_KEY="${CERT_KEY:-/tmp/chat_privkey.pem}"
# ==================================================================

log()  { printf '\033[1;32m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "请以 root 运行"

# ---- 识别系统：dnf(RHEL/Alibaba Cloud Linux) 或 apt(Debian/Ubuntu) ----
if command -v dnf >/dev/null 2>&1; then
  PM="dnf"; INSTALL="dnf install -y"
  PY_PKGS="python3 python3-pip python3-devel"
  PY312_PKGS="python3.12 python3.12-pip python3.12-devel"
  SQLITE_PKG="sqlite"
else
  PM="apt"; INSTALL="apt-get install -y"
  PY_PKGS="python3 python3-venv python3-pip"
  PY312_PKGS=""
  SQLITE_PKG="sqlite3"
  apt-get update -y
fi
log "包管理器：$PM"

# ---- 1. 系统依赖 ----
# Node.js 说明：飞书/高德等 MCP 走 stdio + npx 子进程，服务器必须装 Node（推荐 >= 18），
# 否则这些 MCP 工具会加载失败且被静默吞掉，模型拿不到工具只能凭记忆编造答案。
log "安装系统依赖..."
$INSTALL git $PY_PKGS nginx "$SQLITE_PKG" curl ca-certificates nodejs npm

# ---- 1.1 校验 npx（MCP stdio 工具依赖 Node 运行时）----
if command -v npx >/dev/null 2>&1; then
  MAJOR="$(node -e 'process.stdout.write(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)"
  log "npx 可用：v$(npx --version 2>/dev/null)（Node 主版本 $MAJOR）"
  if [[ "$MAJOR" =~ ^[0-9]+$ ]] && [[ "$MAJOR" -lt 18 ]]; then
    warn "Node 主版本 $MAJOR < 18，@amap/amap-maps-mcp-server 等现代 MCP 包可能无法运行，建议升级到 Node 18+"
  fi
else
  warn "未找到 npx：高德/飞书等 stdio 型 MCP 工具将无法加载（可用 NodeSource 安装 Node 18+）"
fi

# ---- 2. Python 3.12（dnf 系尝试，失败用系统自带）----
if [[ -n "$PY312_PKGS" ]]; then
  $INSTALL $PY312_PKGS 2>/dev/null && log "已装 Python 3.12" || warn "python3.12 不可用，用系统 python3"
fi

# ---- 3. 运行用户 ----
if ! id -u "$APP_USER" &>/dev/null; then
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
  log "已创建用户 $APP_USER"
fi
mkdir -p "$APP_DIR/data"

# ---- 4. 首次部署：迁移数据（仅当服务器还没有数据库时）----
if [[ -f /tmp/openunknown-data.tar.gz && ! -f "$APP_DIR/data/openunknown.db" ]]; then
  log "检测到数据包且服务器无数据库，执行首次数据迁移..."
  tar -xzf /tmp/openunknown-data.tar.gz -C "$APP_DIR"
fi

# ---- 5. 虚拟环境 + 依赖 ----
log "创建/更新虚拟环境与依赖..."
if command -v python3.12 >/dev/null 2>&1; then PY=python3.12; else PY=python3; fi
[[ -d "$VENV_DIR" ]] || "$PY" -m venv "$VENV_DIR"
if [[ -n "$PIP_INDEX" ]]; then
  "$VENV_DIR/bin/pip" install --upgrade pip -i "$PIP_INDEX" >/dev/null
  "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -i "$PIP_INDEX"
else
  "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
  "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

# ---- 6. .env（可选，LangSmith）----
[[ -f "$APP_DIR/.env" ]] || { cp "$APP_DIR/.env.example" "$APP_DIR/.env"; warn "已生成 .env（如需 LangSmith 追踪请编辑）"; }

# ---- 7. 目录归属与密钥权限 ----
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/data/.app_secret"     2>/dev/null || true
chmod 600 "$APP_DIR/data/.app_master_key" 2>/dev/null || true
chmod 600 "$APP_DIR/data/.app_auth_key"   2>/dev/null || true

# ---- 8. systemd 服务 ----
log "安装/更新 systemd 服务..."
if [[ -f "$APP_DIR/deploy/openunknown.service" ]]; then
  cp "$APP_DIR/deploy/openunknown.service" /etc/systemd/system/openunknown.service
else
  cat > /etc/systemd/system/openunknown.service <<EOF
[Unit]
Description=OpenUnknown FastAPI service
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_DIR/bin/uvicorn backend.main:app --host 127.0.0.1 --port $PORT --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
fi
systemctl daemon-reload
systemctl enable --now openunknown
systemctl restart openunknown
sleep 2
systemctl --no-pager --lines=8 status openunknown || true

# ---- 9. Nginx：证书 + 站点配置 ----
log "配置 Nginx..."
mkdir -p /etc/nginx/ssl
if [[ -f "$CERT_PEM" && -f "$CERT_KEY" ]]; then
  cp "$CERT_PEM" /etc/nginx/ssl/chat_fullchain.pem
  cp "$CERT_KEY" /etc/nginx/ssl/chat_privkey.pem
  chmod 600 /etc/nginx/ssl/chat_privkey.pem
  log "已放置证书"
else
  warn "未找到证书 $CERT_PEM / $CERT_KEY，沿用服务器已有证书"
fi

# 用模板生成站点配置（模板里占位为 chat.your-domain.com）
sed "s/chat\.your-domain\.com/$DOMAIN/g" "$APP_DIR/deploy/nginx-openunknown.conf" \
  > /etc/nginx/conf.d/openunknown.conf
nginx -t && systemctl enable --now nginx && systemctl reload nginx
log "Nginx 配置完成"

# ---- 10. SELinux 提示（dnf 系）----
if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce 2>/dev/null)" == "Enforcing" ]]; then
  warn "SELinux Enforcing：若访问 502，执行 setsebool -P httpd_can_network_connect 1"
fi

# ---- 11. 自检 ----
log "本机自检："
curl -sf http://127.0.0.1:$PORT/ >/dev/null \
  && log "uvicorn 响应正常 (http://127.0.0.1:$PORT/)" \
  || warn "uvicorn 未响应：journalctl -u openunknown -n 50"

log "部署完成。访问 https://$DOMAIN/"
