# GNotes 部署文档

本文说明**当前仓库的实际部署方式**：Docker Compose 两个服务（`backend` + `nginx`），SQLite 数据放在命名卷，密钥和环境变量走 `.env`。

适用场景：Ubuntu 虚拟机验证、海外 VPS 自托管。本 compose **只提供 HTTP :80**，公网请在前面加 TLS，不要把 80 直接暴露到互联网。

相关文件：

| 文件 | 作用 |
| :--- | :--- |
| `docker-compose.yml` | 编排 backend、nginx，挂载数据卷和 `secrets/` |
| `.env.example` | 环境变量模板，复制为 `.env` 后填写 |
| `backend/Dockerfile` | FastAPI 镜像；入口脚本启动时 chown 数据卷再降权 |
| `nginx/Dockerfile` | 多阶段：构建 Vue 前端，再用 nginx 提供静态文件并反代 `/api` |
| `nginx/nginx.conf` | SPA 回退、`/api` 反代、CSP、登录限流 |
| `secrets/gdrive.json` | Google Drive 服务账号（可选，不进 git） |

---

## 1. 机器要求

- 系统：Ubuntu 22.04 / 24.04（其它能跑 Docker 的 Linux 也可）
- 内存：**≥ 2GB**（首次构建前端镜像时 Node 较吃内存）
- 磁盘：镜像 + 数据卷预留数 GB 即可
- 网络：能拉取 Docker Hub 镜像；若要测 Google Drive 备份，机器必须能访问 `googleapis.com`（国内网络通常不行）
- 端口：宿主机 **80** 未被占用

安装 Docker（官方脚本）：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git python3
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# 退出并重新登录，使 docker 组生效
docker compose version
```

确认命令是 `docker compose`（中间有空格）。

检查 80 端口：

```bash
sudo ss -lntp | grep ':80 ' || true
# 若被 apache2 / 系统 nginx 占用：
sudo systemctl stop apache2 nginx
sudo systemctl disable apache2
```

虚拟机网络：

- **桥接**：宿主机浏览器直接访问虚拟机 IP，例如 `http://192.168.x.x/`
- **NAT**：在虚拟化软件里做端口转发（主机 `8080` → 虚拟机 `80`），访问 `http://127.0.0.1:8080/`

---

## 2. 获取源码

在目标机器上使用 git 克隆，或只拷源码。**不要**从 Windows 整盘共享带上 `frontend/node_modules`、`frontend/dist`、`backend/__pycache__`。

仓库根目录应能看到：

```text
.env.example  docker-compose.yml  backend/  frontend/  nginx/  README.md  部署文档.md
```

若文件从 Windows 拷来，检查入口脚本换行。CRLF 会导致容器报 `docker-entrypoint.sh: no such file or directory`：

```bash
file backend/docker-entrypoint.sh
# 若出现 "CRLF line terminators"：
sed -i 's/\r$//' backend/docker-entrypoint.sh
```

---

## 3. 配置环境变量

在仓库根目录：

```bash
cp .env.example .env
chmod 600 .env
```

生成密钥（需要本机 `python3`；没有则用下方 openssl）：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

```bash
openssl rand -base64 48    # JWT_SECRET，长度必须 ≥ 32 字符
openssl rand -base64 32    # ENCRYPTION_KEY，解码后必须正好 32 字节
openssl rand -base64 32    # BACKUP_ENCRYPTION_KEY，建议与主密钥不同
```

编辑 `.env`，**不要留空必填项**：

```bash
# 必填
JWT_SECRET=
ENCRYPTION_KEY=
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=     # 6～72 字符
INITIAL_ADMIN_EMAIL=admin@example.com

# 强烈建议填写（不填会回退到 ENCRYPTION_KEY 并打 warning）
BACKUP_ENCRYPTION_KEY=

# 第一次可以空：应用能启动，仅手动/定时备份会失败
GOOGLE_DRIVE_FOLDER_ID=

# 保持生产默认
DEBUG=false
LOG_LEVEL=INFO
BACKUP_SCHEDULE=0 2 * * *
BACKUP_RETENTION_COUNT=30
```

说明：

- `JWT_SECRET` 短于 32 字符、或 `ENCRYPTION_KEY` 解码不是 32 字节：**容器启动即退出**。
- `INITIAL_ADMIN_*` **只在 users 表为空时**创建管理员。之后改 `.env` 再重启**不会**改库里已有账号。
- `ENCRYPTION_KEY` / `BACKUP_ENCRYPTION_KEY` 丢失后，旧库和旧备份都解不开。请把 `.env` 单独备份到安全位置。
- `VITE_API_BASE_URL` 在 Docker 构建前端时默认 `/api/v1`，一般不用改。

准备 secrets 目录（compose 会只读挂载）：

```bash
mkdir -p secrets
# 暂不测 Drive 时可为空目录
```

---

## 4. 启动

在仓库根目录：

```bash
docker compose up -d --build
```

首次构建会拉取 `python:3.12-slim`、`node:20-alpine`、`nginx:alpine`，并执行前端 `npm ci`，耗时较长。

查看状态与日志：

```bash
docker compose ps
docker compose logs -f backend
```

后端正常日志应包含：

```text
加密切件已初始化
数据库已初始化: /app/data/notes.db
已创建初始管理员: username=admin email=...
定时备份已启用: 0 2 * * *
```

之后可用 `Ctrl+C` 退出日志跟随，容器继续运行。

| 现象 | 处理 |
| :--- | :--- |
| `JWT_SECRET 至少 32 字符` | `.env` 未填或太短 |
| `ENCRYPTION_KEY 必须解码为 32 字节` | 不是用上文命令生成的 Base64 32 字节密钥 |
| `docker-entrypoint.sh: no such file` | CRLF，见第 2 节 |
| `port is already allocated` | 宿主机 80 被占用 |
| 构建前端被 OOM Kill | 加大虚拟机内存到 2GB 以上 |
| `BACKUP_ENCRYPTION_KEY 未设置` 的 warning | 可补上独立备份密钥后 `docker compose up -d backend` |

停止（**保留数据卷**）：

```bash
docker compose stop          # 仅停容器
docker compose down          # 删容器，保留 db-data 卷
```

**不要**使用 `docker compose down -v`，`-v` 会删除 `db-data`，笔记全部丢失。

---

## 5. 验证部署

在虚拟机本机：

```bash
curl -s http://127.0.0.1/health
# 期望：{"status":"ok"}

curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/docs
# 期望：404（生产关闭 OpenAPI）
```

浏览器打开 `http://<虚拟机IP>/`（或 NAT 转发后的地址），用 `.env` 里的管理员账号登录。

用 API 走通主路径：

```bash
# 管理员登录
curl -s -X POST http://127.0.0.1/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<初始密码>"}'

# 创建普通用户（把 <TOKEN> 换成上一步返回的 JWT）
curl -s -X POST http://127.0.0.1/api/v1/admin/users \
  -H 'Authorization: Bearer <TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"alice-pass"}'

# alice 登录后创建笔记
curl -s -X POST http://127.0.0.1/api/v1/notes \
  -H 'Authorization: Bearer <ALICE_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"title":"测试","content":"hello"}'
```

确认数据库存的是密文：

```bash
docker compose exec backend sqlite3 /app/data/notes.db \
  "SELECT title_encrypted, content_encrypted FROM notes;"
```

输出中不应出现明文 `测试` 或 `hello`。

登录失败有限流：同一 IP 默认 5 分钟内 10 次失败后返回 429；nginx 另有每分钟约 10 次的限制。验证时不要连续打错密码过多。

---

## 6. Google Drive 备份（可选）

不配 Drive 时，应用其余功能可用；`POST /api/v1/admin/backup` 与每日定时任务会失败并记日志。

前提：部署机器能访问 Google API。

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)，创建项目，启用 **Google Drive API**。
2. 创建**服务账号**，下载 JSON 密钥，保存为仓库根下 `secrets/gdrive.json`：

   ```bash
   chmod 600 secrets/gdrive.json
   ```

3. 用个人 Google 账号在 Drive 新建文件夹，把该文件夹**分享给服务账号邮箱**（编辑者）。
4. 文件夹 URL 中 `folders/` 后面的 ID 写入 `.env`：

   ```bash
   GOOGLE_DRIVE_FOLDER_ID=1abc...
   ```

5. 重启后端使环境变量生效：

   ```bash
   docker compose up -d backend
   ```

6. 管理员手动触发备份：

   ```bash
   curl -s -X POST http://127.0.0.1/api/v1/admin/backup \
     -H 'Authorization: Bearer <ADMIN_TOKEN>'
   ```

成功时 `data.filename` 以 `.db.gz.enc` 结尾，并带 `drive_file_id`。到 Drive 目标文件夹确认文件存在。

失败时：

```bash
docker compose logs backend | tail -50
```

常见原因：JSON 未放到 `secrets/gdrive.json`、文件夹未分享给服务账号、网络访问不了 `googleapis.com`。

定时备份默认 `BACKUP_SCHEDULE=0 2 * * *`（UTC 每天 02:00）。验证时可临时改为 `*/2 * * * *`，看到多一个文件后再改回。

从 Drive 恢复备份（停服后替换数据库）：

```bash
# 1. 下载 backup_YYYY-MM-DD_HHMMSS_UTC.db.gz.enc

# 2. 解密 + 解压（BACKUP_ENCRYPTION_KEY 与部署时一致）
python3 -c "
import base64, gzip
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key = base64.b64decode('<BACKUP_ENCRYPTION_KEY>')
blob = open('backup_xxx.db.gz.enc', 'rb').read()
dec = AESGCM(key).decrypt(blob[:12], blob[12:], None)
open('restored.db', 'wb').write(gzip.decompress(dec))
print('已还原为 restored.db')
"

# 3. 停服务，把 restored.db 拷进数据卷后再启动
docker compose stop backend
docker compose cp restored.db backend:/app/data/notes.db
docker compose start backend
```

---

## 7. 日常运维

```bash
# 看日志
docker compose logs -f backend
docker compose logs -f nginx

# 改 .env 后使后端生效（不必重建镜像）
docker compose up -d backend

# 改了代码或 Dockerfile / 前端后需要重建
docker compose up -d --build

# 数据文件位置（在容器内）
docker compose exec backend ls -l /app/data
```

数据在 Docker 命名卷（默认名类似 `<目录名>_db-data`），不在 git 工作区。备份卷或定期走 Drive 即可。

**不要**给 uvicorn 加 `--workers N`。定时备份跑在 FastAPI 进程内，多 worker 会启动多个调度器。

公网部署：在本 compose 前面加 Cloudflare / Caddy / 主机 nginx 做 HTTPS，反代到本机 80。本仓库的 nginx 容器只监听 80，backend 的 8000 **不映射到宿主机**。

---

## 8. 架构（当前实现）

```text
浏览器 ──HTTP :80──► nginx 容器
                      ├─ /          Vue 静态资源（构建进镜像）
                      └─ /api/  ──► backend 容器 :8000
                                      ├─ SQLite  → 卷 db-data
                                      └─ 定时/手动备份 →（可选）Google Drive
```

- 前端在 **构建 nginx 镜像时**编进镜像，运行期没有单独的 Node 进程。
- `nginx/Dockerfile` 的构建上下文必须是**仓库根目录**（见 `docker-compose.yml`），不要改成 `frontend/`。
- 后端以 root 进入容器，`docker-entrypoint.sh` 把 `/app/data` 属主改为 `gnotes` 后再降权启动 uvicorn。
