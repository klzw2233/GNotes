# GNotes

自托管、多用户笔记系统。笔记在服务端用 AES-256-GCM 加密后写入 SQLite；可选地将加密备份上传到 Google Drive。

> License: MIT（见 [LICENSE](./LICENSE)）。

无公开注册：首次启动用 `.env` 创建管理员，由管理员再创建普通用户。

## 能做什么

- 管理员创建用户；用户登录后管理自己的笔记（列表 / 新建 / 编辑 / 删除）
- 标题与正文分别加密存储，各用独立 nonce，并用 `note_id:user_id` 作 AAD
- Docker Compose 两个容器：`backend`（FastAPI）+ `nginx`（前端静态 + `/api` 反代）
- Google Drive 备份是**可选**的：不配也能用笔记功能。定时/手动备份失败只记日志并在管理员页面提示，**不会让容器退出**
- 管理员登录后，笔记列表顶部可看到备份状态，并可点「立即备份」

不做（MVP 后置）：公开注册、全文搜索、Markdown 渲染、独立管理后台。

## 技术栈

| 层 | 技术 |
| :--- | :--- |
| 前端 | Vue 3 + Vite + TypeScript + Pinia + Vue Router |
| 后端 | Python FastAPI + aiosqlite + APScheduler |
| 加密 | AES-256-GCM（cryptography）+ bcrypt + JWT（HS256，7 天） |
| 备份 | `VACUUM INTO` → gzip → AES-GCM 整包加密 → Drive（可选） |
| 部署 | Docker Compose；nginx 只监听 HTTP :80 |

## 仓库结构

```text
GNotes/
├── backend/                 # FastAPI
│   ├── app/                 # 路由 / 加密 / 认证 / 备份
│   ├── tests/
│   ├── requirements.txt     # 生产依赖
│   └── requirements-dev.txt # 含 pytest
├── frontend/                # Vue 3（构建进 nginx 镜像）
├── nginx/
├── docker-compose.yml
├── .env.example
├── Deployment.md              # Ubuntu / 虚拟机逐步部署
└── README.md
```

---

## 部署（精简）

完整步骤、虚拟机注意点和排错见 **[Deployment.md](./Deployment.md)**。

```bash
cp .env.example .env
# 填写 JWT_SECRET（≥32 字符）、ENCRYPTION_KEY、BACKUP_ENCRYPTION_KEY、
# INITIAL_ADMIN_USERNAME / PASSWORD / EMAIL
# Google Drive 相关可先空着

mkdir -p secrets
docker compose up -d --build
```

密钥生成：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

要点：

- compose **只暴露 HTTP :80**。公网请在前面加 TLS，不要把 80 直接对互联网。
- backend 的 8000 **不映射**到宿主机。
- **不要**给 uvicorn 开 `--workers N`（定时备份在进程内，多 worker 会跑多份）。
- **不要** `docker compose down -v`（会删掉 SQLite 数据卷）。
- `INITIAL_ADMIN_*` 只在 users 表为空时生效。
- 生产默认 `DEBUG=false`，`/docs` `/redoc` `/openapi.json` 关闭。

未配置 Drive 时：应用可正常登录写笔记；管理员页面会提示未配置；`POST /admin/backup` 返回 500 且记下失败原因，容器继续运行。

---

## 使用

浏览器打开 `http://<主机>/`，用初始管理员登录。

- 普通用户：列表、新建、编辑、删除、登出
- 管理员额外：顶部备份横幅（配置是否齐全、最近一次成功/失败）、立即备份

创建其他用户目前用 API（无管理后台 UI）：

```bash
curl -s -X POST http://localhost/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<初始密码>"}'
# data.token、data.role

curl -s -X POST http://localhost/api/v1/admin/users \
  -H 'Authorization: Bearer <admin_token>' \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"alice-pass"}'
```

---

## API

统一成功包装：`{"code":0,"message":"...","data":...}`。业务错误多为 HTTP 4xx/5xx（登录失败为 **401**，不是 200 + code）。

| 方法 | 路径 | 认证 | 说明 |
| :--- | :--- | :--- | :--- |
| GET | `/health` | 否 | 存活检查 |
| POST | `/api/v1/auth/login` | 否 | 返回 `token`、`role`、`expires_in` |
| POST | `/api/v1/auth/logout` | 是 | 软登出 |
| POST | `/api/v1/admin/users` | admin | 创建普通用户 |
| GET | `/api/v1/admin/backup` | admin | 备份配置 + 最近一次结果 |
| POST | `/api/v1/admin/backup` | admin | 立即备份 |
| GET | `/api/v1/notes` | 是 | 列表（仅标题明文） |
| GET | `/api/v1/notes/{id}` | 是 | 详情 |
| POST | `/api/v1/notes` | 是 | 创建 |
| PUT | `/api/v1/notes/{id}` | 是 | 更新 |
| DELETE | `/api/v1/notes/{id}` | 是 | 删除 |

登录失败按 IP 限流（默认 10 次 / 5 分钟，超限 429）；nginx 对登录另有 `limit_req`。

---

## Google Drive 备份（可选）

链路：`VACUUM INTO` 一致性快照 → gzip → AES-256-GCM 整包加密 → 上传。Drive 上文件名为 `backup_<UTC时间>.db.gz.enc`。

配置步骤见 [Deployment.md](./Deployment.md) 第 6 节。需要：`secrets/gdrive.json`、把 Drive 文件夹分享给服务账号、`.env` 里的 `GOOGLE_DRIVE_FOLDER_ID`。

定时默认 `BACKUP_SCHEDULE=0 2 * * *`（UTC）。保留份数 `BACKUP_RETENTION_COUNT`（默认 30）。

从 `.enc` 恢复：

```bash
python3 -c "
import base64, gzip
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key = base64.b64decode('<BACKUP_ENCRYPTION_KEY>')
blob = open('backup_xxx.db.gz.enc','rb').read()
dec = AESGCM(key).decrypt(blob[:12], blob[12:], None)
open('restored.db','wb').write(gzip.decompress(dec))
"
# 停 backend，替换数据卷中的 notes.db 后再启动
```

---

## 本地开发

```bash
# 后端
cd backend
pip install -r requirements-dev.txt
# 设置 JWT_SECRET、ENCRYPTION_KEY、INITIAL_ADMIN_*、DATABASE_PATH
pytest
uvicorn app.main:app --reload    # DEBUG=true 才开放 /docs

# 前端（Vite 把 /api 代理到 127.0.0.1:8000）
cd frontend
npm install
npm run dev
npm run build
```

---

## 安全

- 密钥只走环境变量；`.env`、`secrets/`、`*.db` 已在 `.gitignore`
- 库中无笔记明文；标题/正文 nonce 独立，禁止复用
- 备份包再加密一层；未配 Drive 时失败不拖垮进程
- 前端不用 `v-html`；nginx 带 CSP 等安全头
- 密码 bcrypt，最长 72 字符（与 bcrypt 限制一致）
- `JWT_SECRET` 启动时至少 32 字符，否则退出

---

## 加密模型（重要）

GNotes 使用 **server-side encryption**（服务端加密），**不是** end-to-end encryption：

```text
浏览器明文 → HTTPS → FastAPI 接收明文 → 服务端 AES-256-GCM 加密 → SQLite 密文
```

- 服务器进程持有主密钥（`ENCRYPTION_KEY`），理论上**可以解密笔记内容**。
- 备份包用独立的 `BACKUP_ENCRYPTION_KEY` 再加密一层，但服务器同样持有该密钥。
- 因此 GNotes 适合「信任服务器运维者」的自托管场景；若你需要的是「服务器也无法读取笔记」的端到端加密，当前实现**不满足**该威胁模型。

未来可选增加端到端加密模式，但会带来密码恢复、搜索、多设备密钥管理等复杂问题（详见 `TODO_features.md` P3-28）。
