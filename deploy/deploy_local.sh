#!/usr/bin/env bash
#
# OpenUnknown 本地一键部署（在你的 Mac 上执行）
#
# 用法：
#   ./deploy_local.sh              # 更新代码（不覆盖服务器上的数据库/密钥）
#   ./deploy_local.sh --with-data  # 首次部署：连本地数据一起迁移到服务器
#
# 它会自动：打包代码 → 上传 → 登录服务器执行 deploy.sh。
# 首次使用请先修改下方「配置区」。
#
set -euo pipefail

# ===================== 配置区（改成你的）=====================
HOST="39.96.65.185"            # 服务器公网 IP
SSH_KEY="j71995.pem"           # SSH 私钥（相对 deploy 目录，或填绝对路径）
DOMAIN="chat.j71995.cn"        # 子域名
CERT_PEM="chat.j71995.cn.pem"  # SSL 证书（相对 deploy 目录）
CERT_KEY="chat.j71995.cn.key"  # SSL 私钥（相对 deploy 目录）
# ============================================================

log() { printf '\033[1;34m[local]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"     # 项目根目录
DEPLOY_DIR="$ROOT/deploy"
WITH_DATA=0
[[ "${1:-}" == "--with-data" ]] && WITH_DATA=1

# 路径解析：私钥/证书支持「相对 deploy 目录」或「绝对路径」
resolve() { [[ "$1" = /* ]] && echo "$1" || echo "$DEPLOY_DIR/$1"; }
KEY="$(resolve "$SSH_KEY")"
CERT_PEM_PATH="$(resolve "$CERT_PEM")"
CERT_KEY_PATH="$(resolve "$CERT_KEY")"

[[ -f "$KEY" ]]          || die "找不到 SSH 私钥：$KEY"
[[ -f "$CERT_PEM_PATH" ]] || die "找不到证书：$CERT_PEM_PATH"
[[ -f "$CERT_KEY_PATH" ]] || die "找不到证书私钥：$CERT_KEY_PATH"

# 用数组存命令，避免路径里的空格（如 "AI AI Project"）把参数拆坏
SSH=(ssh -o StrictHostKeyChecking=accept-new -i "$KEY" "root@$HOST")
SCP=(scp -o StrictHostKeyChecking=accept-new -i "$KEY")

# ---- 1. 打包代码（排除 .venv/.git/.env/data）----
log "打包代码..."
STAGE="$(mktemp -d)"
rsync -a --exclude '.venv' --exclude '.git' --exclude '__pycache__' \
  --exclude '.env' --exclude 'data' \
  "$ROOT/" "$STAGE/"
tar --no-xattrs -czf /tmp/openunknown-code.tar.gz -C "$STAGE" .
rm -rf "$STAGE"

# ---- 2. 可选：打包数据（首次迁移）----
if [[ "$WITH_DATA" == "1" ]]; then
  log "打包数据（SQLite 一致性备份 + 密钥 + 索引）..."
  DSTAGE="$(mktemp -d)"
  mkdir -p "$DSTAGE/data/hotels"
  sqlite3 "$ROOT/data/openunknown.db" ".backup '$DSTAGE/data/openunknown.db'"
  cp "$ROOT/data/.app_secret" "$ROOT/data/.app_master_key" "$DSTAGE/data/"
  cp "$ROOT/data/hotels/docs.json" "$ROOT/data/hotels/hotels.index" "$DSTAGE/data/hotels/"
  tar --no-xattrs -czf /tmp/openunknown-data.tar.gz -C "$DSTAGE" data
  rm -rf "$DSTAGE"
fi

# ---- 3. 上传 ----
log "上传代码包..."
"${SCP[@]}" /tmp/openunknown-code.tar.gz "root@$HOST:/tmp/"
if [[ "$WITH_DATA" == "1" ]]; then
  log "上传数据包..."
  "${SCP[@]}" /tmp/openunknown-data.tar.gz "root@$HOST:/tmp/"
fi
log "上传证书..."
"${SCP[@]}" "$CERT_PEM_PATH" "root@$HOST:/tmp/chat_fullchain.pem"
"${SCP[@]}" "$CERT_KEY_PATH" "root@$HOST:/tmp/chat_privkey.pem"

# ---- 4. 远程执行 ----
log "远程部署中..."
"${SSH[@]}" "DOMAIN='$DOMAIN' bash -s" <<'REMOTE'
set -e
mkdir -p /opt/openunknown
tar -xzf /tmp/openunknown-code.tar.gz -C /opt/openunknown
bash /opt/openunknown/deploy/deploy.sh
REMOTE

log "完成！访问 https://$DOMAIN/"
