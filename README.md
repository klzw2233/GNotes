# GNotes

自托管、多用户、服务端加密的笔记系统，支持 Google Drive 自动备份加密数据库。

## 特性

- **服务端 AES-256-GCM 加密**：笔记标题与正文均加密存储，每篇笔记各字段独立 nonce + AAD 绑定（防剪贴攻击）
- **多用户隔离**：管理员创建用户，用户数据完全隔离
- **SQLite 存储**：单文件、零配置
- **Google Drive 备份**：`快照 → gzip → AES-GCM 整体加密 → 上传`，双层加密保护
- **Docker 一键部署**：backend + nginx 两容器
- **Vue 3 前端**：极简自定义 CSS，纯 textarea 编辑器

## 技术栈

| 层 | 技术 |
| :--- | :--- |
| 前端 | Vue 3 + Vite + TypeScript + Pinia + Vue Router |
| 后端 | Python FastAPI + aiosqlite + APScheduler |
| 加密 | AES-256-GCM（cryptography 库）+ bcrypt（密码哈希）+ JWT |
| 备份 | SQLite VACUUM INTO + gzip + google-api-python-client |
| 部署 | Docker + Docker Compose + nginx |

## 部署步骤

### 1. 生成密钥

```bash
# JWT 密钥（≥32 字节）
python -c "import secrets;print(secrets.token_urlsafe(48))"

# AES 主密钥 + 备份密钥（Base64 编码 32 字节，建议各自独立）
python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入上面生成的密钥、初始管理员、Drive 配置
```

### 3. 配置 Google Drive

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 创建项目，启用 Drive API
2. 创建**服务账号**，下载 JSON 密钥，保存为 `secrets/gdrive.json`
3. 在 Google Drive 创建一个文件夹，**分享**给服务账号邮箱（Editor 权限）
4. 把文件夹 ID（URL 里 `folders/` 后的部分）填入 `.env` 的 `GOOGLE_DRIVE_FOLDER_ID`

### 4. 启动

```bash
docker compose up -d --build
```

首次启动会自动用 `.env` 里的凭据创建初始管理员。

## API 示例

```bash
# 管理员登录
curl -X POST http://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<初始密码>"}'
# → {"code":0,"message":"success","data":{"token":"...","token_type":"bearer","expires_in":604800}}

# 管理员创建普通用户
curl -X POST http://localhost/api/v1/admin/users \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice@example.com","password":"alice-pass"}'

# 普通用户登录后创建笔记
curl -X POST http://localhost/api/v1/notes \
  -H "Authorization: Bearer <user_token>" \
  -H "Content-Type: application/json" \
  -d '{"title":"我的笔记","content":"内容"}'

# 手动触发备份（管理员）
curl -X POST http://localhost/api/v1/admin/backup \
  -H "Authorization: Bearer <admin_token>"
# → {"code":0,"data":{"filename":"backup_..._UTC.db.gz.enc","size_bytes":...,"drive_file_id":"..."}}
```

## API 端点

| 方法 | 路径 | 认证 | 说明 |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/auth/login` | 否 | 登录获取 JWT |
| POST | `/api/v1/auth/logout` | 是 | 软登出 |
| POST | `/api/v1/admin/users` | admin | 创建用户 |
| POST | `/api/v1/admin/backup` | admin | 手动备份 |
| GET | `/api/v1/notes` | 是 | 笔记列表（仅标题） |
| GET | `/api/v1/notes/{id}` | 是 | 笔记详情 |
| POST | `/api/v1/notes` | 是 | 创建笔记 |
| PUT | `/api/v1/notes/{id}` | 是 | 更新笔记 |
| DELETE | `/api/v1/notes/{id}` | 是 | 删除笔记 |

## 备份恢复

备份文件在 Drive 上为 `.db.gz.enc` 加密包。恢复流程：

```bash
# 1. 从 Drive 下载 backup_YYYY-MM-DD_HHMMSS_UTC.db.gz.enc

# 2. 解密 → 解压 → 得到 SQLite 快照
python -c "
import base64, gzip, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key = base64.b64decode('<BACKUP_ENCRYPTION_KEY>')
blob = open('backup_xxx.db.gz.enc','rb').read()
dec = AESGCM(key).decrypt(blob[:12], blob[12:], None)
open('restored.db','wb').write(gzip.decompress(dec))
print('已还原为 restored.db')
"

# 3. 停服后用 restored.db 替换 notes.db，重启容器
```

## 开发

```bash
# 后端
cd backend
pip install -r requirements.txt
export JWT_SECRET=... ENCRYPTION_KEY=... INITIAL_ADMIN_PASSWORD=... INITIAL_ADMIN_EMAIL=... DATABASE_PATH=./notes.db
pytest            # 运行测试
uvicorn app.main:app --reload   # 本地运行

# 前端
cd frontend
npm install
npm run dev       # 开发服务器（自动代理 /api 到 127.0.0.1:8000）
npm run build     # 生产构建
```

## 安全说明

- 笔记内容服务端 AES-256-GCM 加密，密钥走环境变量、不落盘
- 数据库仅存密文，标题/正文各有独立 nonce（绝不复用）
- 备份包双层加密（数据库内密文 + 整体再加密）
- 全站 HTTPS（nginx 终结 TLS，部署时配置证书）
- 前端全程禁用 `v-html`，nginx 配置 CSP 头
- JWT 7 天过期，密码 bcrypt 哈希
