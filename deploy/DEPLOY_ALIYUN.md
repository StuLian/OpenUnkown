# OpenUnknown 阿里云部署 SOP（方案 C：子域名）

> 实际采用方案：**主域名首页放 OSS，聊天应用放 ECS 的子域名 `chat.<域名>`**。
> 服务器系统：**Alibaba Cloud Linux 4 LTS**（RHEL/Anolis 系，用 `dnf`）。
> 代码上传方式：**本地打包 tar → scp 上传**。

---

## 0. 架构总览

```
用户浏览器
   ├─ https://j71995.cn/           → OSS（首页，静态 index.html）
   └─ https://chat.j71995.cn/      → ECS: Nginx(443) → uvicorn:8000 (FastAPI)
                                          │
                                          └─ data/（SQLite + 密钥 + RAG 索引）
```

- 前端为 React（源码 `frontend/`），`dist/` 不入库，由 `deploy/deploy_local.sh` 在**本地构建**后随部署包上传，
  由 FastAPI 直接托管（`/`、`/assets`、`/api`），**无单独前端部署**；但服务器仍要装 Node（`npx`）——
  飞书/高德等 MCP 工具走 `stdio + npx` 子进程，`deploy.sh` 会自动装 `nodejs npm`（推荐 Node ≥ 18）
- 数据库是 SQLite（`data/openunknown.db`），**不需要 MySQL/Redis**
- 模型 ApiKey 由用户在 Web「模型设置」填写，加密落库，**不进环境变量**

---

## 1. 前置条件（一次性，控制台操作）

| 项 | 说明 |
|----|------|
| ECS | Alibaba Cloud Linux 4 LTS，已绑定公网 IP `39.96.65.185` |
| 安全组 | 入方向放行 `22` / `80` / `443` |
| DNS | `j71995.cn` → OSS（首页，不动）；`chat.j71995.cn` A 记录 → `39.96.65.185` |
| ICP 备案 | 已完成（国内地域必需） |
| 证书 | `chat.j71995.cn` 的 Nginx 格式证书（`.pem` + `.key`） |
| OSS 首页 | 已开启静态页面托管，默认首页 `index.html`，入口链接指向 `https://chat.j71995.cn/` |

---

## 2. 方式一：一键部署（推荐）

### 首次准备

1. 把以下文件放进 `deploy/` 目录：
   - `j71995.pem`（SSH 登录私钥）
   - `chat.j71995.cn.pem`、`chat.j71995.cn.key`（SSL 证书）
2. 编辑 `deploy/deploy_local.sh` 顶部「配置区」：`HOST`、`SSH_KEY`、`DOMAIN`、证书文件名。

### 首次部署（带数据迁移）

```bash
cd /Users/josie/Documents/AI/AI\ Project/OpenUnknown
./deploy/deploy_local.sh --with-data
```

### 后续更新代码（不覆盖服务器数据）

```bash
./deploy/deploy_local.sh
```

脚本会自动：打包代码（+可选数据）→ scp 上传 → SSH 执行 `deploy/deploy.sh` 完成安装。

---

## 3. 方式二：手动分步（对应实际执行过的流程）

### 第 0 步 · 本地打包上传

```bash
# 本地项目根目录，先打包含代码+数据（含一致性备份的 db 与两把密钥）
# （脚本已封装此步骤，手动时用 rsync + sqlite3 .backup）
scp -i j71995.pem openunknown-deploy.tar.gz root@39.96.65.185:/tmp/
```

### 第 1 步 · 登录

```bash
ssh -i j71995.pem root@39.96.65.185
```

### 第 2 步 · 装环境 + 解压 + 装依赖 + 起服务

```bash
dnf install -y git python3 python3-pip python3-devel sqlite curl nodejs npm
dnf install -y python3.12 python3.12-pip python3.12-devel 2>/dev/null || echo "python3.12 不可用，用系统自带"

useradd --system --create-home --shell /usr/sbin/nologin openunknown 2>/dev/null || true
mkdir -p /opt/openunknown
tar -xzf /tmp/openunknown-deploy.tar.gz -C /opt/openunknown

cd /opt/openunknown
if command -v python3.12 >/dev/null 2>&1; then PY=python3.12; else PY=python3; fi
$PY -m venv .venv
.venv/bin/pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/
.venv/bin/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

cp .env.example .env
chown -R openunknown:openunknown /opt/openunknown
chmod 600 data/.app_secret data/.app_master_key

cp deploy/openunknown.service /etc/systemd/system/openunknown.service
systemctl daemon-reload
systemctl enable --now openunknown
sleep 2
systemctl status openunknown --no-pager
```

### 第 3 步 · 自检

```bash
systemctl is-active openunknown          # 期望 active
curl -s http://127.0.0.1:8000/ | head -c 100; echo   # 期望返回 HTML
```

### 第 4 步 · 上传证书

```bash
scp -i j71995.pem chat.j71995.cn.pem root@39.96.65.185:/tmp/chat_fullchain.pem
scp -i j71995.pem chat.j71995.cn.key root@39.96.65.185:/tmp/chat_privkey.pem
```

### 第 5 步 · 装 Nginx + 放证书

```bash
dnf install -y nginx
mkdir -p /etc/nginx/ssl
mv /tmp/chat_fullchain.pem /etc/nginx/ssl/chat_fullchain.pem
mv /tmp/chat_privkey.pem   /etc/nginx/ssl/chat_privkey.pem
chmod 600 /etc/nginx/ssl/chat_privkey.pem
```

### 第 6 步 · 写 Nginx 站点配置

用 `deploy/nginx-openunknown.conf` 模板（占位 `chat.your-domain.com`），替换成真实子域名后写入 `/etc/nginx/conf.d/openunknown.conf`：

```bash
cd /opt/openunknown
sed "s/chat\.your-domain\.com/chat.j71995.cn/g" deploy/nginx-openunknown.conf \
  > /etc/nginx/conf.d/openunknown.conf
nginx -t && systemctl enable --now nginx && systemctl reload nginx
```

> ⚠️ 关键：`proxy_buffering off;` 缺了它，SSE 聊天流式会卡到最后才返回。
> 若访问 502：`setsebool -P httpd_can_network_connect 1 && systemctl reload nginx`（SELinux）。

### 第 7 步 · 验证

```bash
curl -I "https://chat.j71995.cn/" | head -5   # 期望 HTTP/2 200
```

浏览器打开 `https://j71995.cn/`（首页）→ 点入口 → `https://chat.j71995.cn/`（聊天登录页）。

---

## 4. 关键文件说明

| 文件 | 作用 |
|------|------|
| `data/openunknown.db` | SQLite 数据库（用户/会话/ApiKey 密文/聊天记忆） |
| `data/.app_secret` | JWT 会话签名密钥（丢了要全员重新登录） |
| `data/.app_master_key` | 信封加密主密钥（丢了 ApiKey 解不开，需重填） |
| `data/hotels/` | RAG 的 FAISS 索引 + 文档（可重建） |
| `deploy/deploy_local.sh` | 本地一键部署脚本 |
| `deploy/deploy.sh` | 服务器端幂等安装脚本 |
| `deploy/nginx-openunknown.conf` | Nginx 配置模板 |
| `deploy/openunknown.service` | systemd 服务单元 |

> 备份务必带上 `.db` + `.app_secret` + `.app_master_key` 三样；私钥（`*.key`、`j71995.pem`）绝不进 git。

---

## 5. 运维

### 日志 / 状态

```bash
journalctl -u openunknown -f               # 应用日志
systemctl status openunknown               # 服务状态
tail -f /var/log/nginx/error.log           # Nginx 日志
```

### 重启 / 升级

```bash
systemctl restart openunknown              # 重启
./deploy/deploy_local.sh                   # 更新代码（本地执行）
```

### 备份（SQLite 用一致性备份，勿直接 cp 单文件）

```bash
sqlite3 /opt/openunknown/data/openunknown.db ".backup '/opt/backup/openunknown-$(date +%F).db'"
tar -czf /opt/backup/openunknown-keys-$(date +%F).tar.gz \
  -C /opt/openunknown/data .app_secret .app_master_key hotels
```
