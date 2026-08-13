# GNotes TODO Features

本文记录 GNotes 与 Joplin、TriliumNext、Standard Notes、Memos、Outline 等同类开源项目对比后，值得继续改进的功能和工程事项。

## 项目定位

GNotes 当前定位是：

> 小型、简单、可自托管、服务端加密、支持多用户和加密备份的笔记系统。

当前 MVP 已实现：

- 管理员创建普通用户
- 用户登录、登出
- 笔记列表、创建、查看、编辑、删除
- 服务端 AES-256-GCM 加密
- 标题和正文使用独立 nonce
- AAD 绑定 `note_id:user_id`
- SQLite 数据库存储
- 定时和手动 Google Drive 备份
- 备份压缩包整体 AES-GCM 加密
- Vue 3 Web 前端
- Docker Compose 部署
- 未配置 Google Drive 时记录错误并在管理员页面提示，容器继续运行

## 优先级说明

- **P0**：涉及数据安全、备份可靠性或会阻塞生产使用，应优先处理
- **P1**：显著提升可用性、运维能力或项目成熟度
- **P2**：改善用户体验和功能完整性
- **P3**：高级能力或规模化能力，按实际需求实现

---

## P0：备份与数据可靠性

### 1. 持久化备份历史

当前备份状态保存在 FastAPI 进程内存中。容器重启后，管理员页面会丢失之前的备份结果和失败记录。

建议增加 `backup_runs` 表：

```sql
CREATE TABLE backup_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,          -- success / failed
    filename TEXT,
    size_bytes INTEGER,
    drive_file_id TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
```

管理员页面应显示：

- 最近一次成功备份时间
- 最近一次失败时间
- 连续失败次数
- 最近若干次备份记录
- Drive 配置状态
- 下一次定时备份时间

### 2. 修正 Google Drive 保留策略

当前保留策略查询目标文件夹中的所有文件，存在误删用户其他文件的风险。

应只处理 GNotes 自己生成的备份文件：

```python
q = (
    f"'{folder_id}' in parents "
    "and trashed = false "
    "and name contains 'backup_'"
)
```

代码层还应再次检查：

```python
file_name.startswith("backup_") and file_name.endswith(".db.gz.enc")
```

### 3. Google Drive 上传重试和超时

网络请求失败是正常情况。建议增加：

- 连接超时
- 上传超时
- 指数退避重试
- 最大重试次数
- 网络错误、认证错误、权限错误分类
- 上传成功后的文件大小或 checksum 校验

推荐重试间隔：

```text
第 1 次失败：等待 2 秒
第 2 次失败：等待 5 秒
第 3 次失败：等待 15 秒
最终失败：写入失败记录并在管理员页面提示
```

### 4. 备份恢复完整性验证

当前可以手动解密和解压备份，但还缺自动恢复验证。

建议增加恢复检查流程：

1. 下载 `.db.gz.enc`
2. 使用 `BACKUP_ENCRYPTION_KEY` 解密
3. gzip 解压
4. 执行 SQLite `PRAGMA integrity_check`
5. 检查 `users` 和 `notes` 表
6. 使用 `ENCRYPTION_KEY` 解密一条笔记
7. 记录恢复验证结果

目标是确认备份不仅“上传成功”，而且确实可以恢复使用。

### 5. 备份文件大小和内存优化

当前 gzip 和 AES-GCM 会把整个中间文件读入内存。个人使用通常足够，但数据库较大时会增加内存压力。

后续可以考虑：

- 分块压缩
- 分块上传
- 限制单次备份大小
- 临时目录空间检查
- 备份前后磁盘空间检查

---

## P1：用户管理与认证

### 6. 管理员用户管理页面

当前创建用户需要调用 API，没有独立管理员页面。

建议增加 `/admin` 页面，支持：

- 用户列表
- 创建用户
- 禁用用户
- 删除用户
- 重置密码
- 修改角色
- 查看创建时间
- 查看最后登录时间

### 7. 修改密码和重置密码

建议增加：

- 普通用户修改自己的密码
- 管理员重置普通用户密码
- 修改密码后使旧 JWT 失效
- 密码修改审计日志

### 8. 更完善的会话管理

当前使用 7 天 JWT 和客户端软登出，MVP 可接受，但 JWT 在过期前仍然有效。

后续可以使用：

```text
短期 access token：保存在内存
长期 refresh token：HttpOnly + Secure + SameSite Cookie
```

可以进一步增加：

- refresh token 轮换
- 服务端会话撤销
- 登录设备列表
- 主动退出其他设备
- MFA / 2FA

### 9. 明确加密模型说明

当前 GNotes 使用的是**服务端加密**，不是端到端加密：

```text
浏览器明文
    ↓
FastAPI 接收明文
    ↓
服务端 AES-GCM 加密
    ↓
SQLite 存储密文
```

README 和部署文档应明确说明：

> GNotes 使用 server-side encryption。服务器进程理论上可以解密笔记内容，不等同于 end-to-end encryption。

未来可选增加用户端加密模式，但会带来密码恢复、搜索、同步和多设备密钥管理等复杂问题。

---

## P1：部署和运维

### 10. Docker healthcheck

当前 `depends_on` 只保证 backend 容器启动，不保证 FastAPI 已经可以响应。

建议增加：

```yaml
backend:
  healthcheck:
    test:
      ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
    interval: 30s
    timeout: 5s
    retries: 5
```

nginx 可以依赖 backend 的健康状态。

### 11. 提供标准 HTTPS 方案

当前 compose 只监听 HTTP :80，公网需要额外的 TLS 终结层。

建议提供一种官方推荐部署方式：

- Caddy + Let's Encrypt
- Cloudflare Tunnel
- 宿主机 nginx + Certbot

对个人部署来说，Caddy 配置最简单：

```text
Internet
   ↓ HTTPS
Caddy
   ↓ HTTP localhost
GNotes nginx
```

### 12. GitHub Actions CI

建议至少自动执行：

```text
pytest
npm run build
docker compose config
docker build backend
docker build nginx
```

可以继续增加：

- Ruff
- mypy
- ESLint
- npm audit
- pip-audit
- Trivy 镜像扫描
- Gitleaks 密钥扫描

### 13. 增加 LICENSE

如果项目公开到 GitHub，应增加许可证。

可选方案：

- MIT：最宽松，适合个人项目
- Apache-2.0：包含专利授权条款
- AGPL-3.0：网络服务修改后也需要公开源码

如果希望限制别人闭源修改后直接提供 SaaS，AGPL-3.0 更合适；如果希望简单使用，MIT 最直接。

### 14. 日志和告警

当前备份错误会写日志并在管理员页面提示。

后续可增加：

- JSON 结构化日志
- 日志轮转
- 备份失败邮件通知
- Webhook 通知
- 健康检查接口
- Prometheus 指标
- 连续失败告警

---

## P1：测试与质量

### 15. Docker 集成测试

增加真实容器测试：

```text
docker compose up -d --build
请求 /health
请求登录接口
创建用户
创建笔记
检查 SQLite 中保存的是密文
停止服务并重新启动
确认数据仍然存在
```

### 16. 浏览器端到端测试

建议使用 Playwright 验证：

- 登录
- 管理员创建用户
- 普通用户创建笔记
- 编辑笔记
- 删除笔记
- 管理员查看备份状态
- 未配置 Drive 时显示提示
- 移动端布局
- 登录过期后回到登录页

### 17. 增加安全测试

建议覆盖：

- JWT 过期
- JWT 篡改
- 无效签名
- 跨用户 IDOR
- 非管理员访问管理接口
- 登录限流
- 备份包篡改
- 错误密钥启动
- 错误配置启动
- SQLite 外键约束
- Google Drive 上传失败

### 18. 并发测试

需要测试：

- 并发创建笔记
- 并发更新同一篇笔记
- 定时备份和写入同时发生
- 两个手动备份同时触发
- 备份锁是否正常工作

---

## P2：笔记组织和搜索

### 19. 标签、文件夹和归档

当前笔记是平面列表。建议增加：

1. 标签
2. 文件夹 / 笔记本
3. 收藏
4. 归档
5. 回收站
6. 最近删除恢复

可以增加以下字段：

```sql
folder_id TEXT,
is_archived INTEGER NOT NULL DEFAULT 0,
is_favorite INTEGER NOT NULL DEFAULT 0,
deleted_at TEXT
```

标签建议单独建表：

```sql
CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL
);

CREATE TABLE note_tags (
    note_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (note_id, tag_id)
);
```

### 20. 搜索

由于正文是加密的，不能直接对数据库中的密文做普通全文搜索。

可选方案：

#### 客户端搜索

- 浏览器下载用户自己的笔记
- 在客户端解密和搜索
- 不保存明文搜索索引
- 安全性最好，但大量笔记时性能有限

#### 服务端明文搜索索引

- 搜索速度好
- 会产生明文或可推断内容
- 与当前安全目标冲突
- 不建议优先采用

#### 盲索引 / 可搜索加密

- 服务端保存不可直接阅读的搜索 token
- 安全性好于明文索引
- 会泄露部分搜索模式和频率
- 实现复杂

第一版建议先做：

> 标签 + 文件夹 + 客户端搜索。

### 21. 分页和性能

前端当前适合 MVP，但后续应：

- 使用服务端分页
- 增加分页控件或无限滚动
- 限制单页数据量
- 避免一次加载全部笔记
- 对列表查询增加必要索引

---

## P2：编辑体验

### 22. 自动保存草稿

建议增加：

- 定时保存草稿
- 页面关闭前保存
- 网络恢复后重试
- 保存状态提示
- 草稿恢复

### 23. 未保存提醒

用户编辑后离开页面时，应提示有未保存修改。

需要跟踪：

- 初始内容
- 当前内容
- 是否发生变化
- 是否正在保存

### 24. Markdown 编辑和预览

这是原需求中的 P1，但当前 MVP 暂后置。

后续可以增加：

- Markdown 编辑器
- Markdown 预览
- 代码块
- 表格
- 目录
- 纯文本安全渲染

渲染必须避免直接使用不安全的 `v-html`，应使用经过安全配置的 Markdown sanitizer。

### 25. 附件

成熟笔记项目通常支持图片和文件附件。

后续需要设计：

- 附件元数据表
- 文件存储目录或对象存储
- 附件加密
- 文件大小限制
- MIME 类型校验
- 下载权限校验
- 备份中包含附件

---

## P3：高级能力

### 26. 版本历史

保存笔记历史版本，支持：

- 查看历史版本
- 恢复历史版本
- 显示修改时间
- 自动清理旧版本

### 27. 多端同步和离线能力

如果未来支持桌面端或移动端，需要增加：

- 同步协议
- 冲突解决
- 增量同步
- 离线编辑
- 设备管理

### 28. 端到端加密模式

可以保留当前服务端加密模式，同时增加可选的用户端加密模式。

需要解决：

- 密钥派生
- 多设备密钥同步
- 忘记密码后的不可恢复问题
- 客户端搜索
- 备份恢复
- 共享笔记

### 29. PostgreSQL 和多实例部署

当前 SQLite 适合个人和小团队。用户量增加后，可以考虑：

- PostgreSQL
- Redis
- 外部任务队列
- 独立备份 worker
- 多个 backend 实例
- 负载均衡
- 对象存储

不要在多实例部署前继续使用单进程 APScheduler，否则会重复执行备份任务。

### 30. MFA 和更细粒度权限

可以增加：

- TOTP MFA
- 恢复码
- 团队空间
- 角色权限
- 笔记共享
- 只读权限
- 审计日志

---

## 推荐实施顺序

### 第一阶段：可靠性和部署

1. 持久化 `backup_runs`
2. 修正 Drive 保留策略
3. Drive 上传重试和超时
4. 恢复完整性验证
5. Docker healthcheck
6. GitHub Actions CI
7. 增加 LICENSE

### 第二阶段：实际使用体验

1. 标签
2. 文件夹 / 笔记本
3. 服务端分页
4. 客户端搜索
5. 自动保存草稿
6. 未保存提醒
7. 管理员用户管理页面
8. 修改密码

### 第三阶段：高级功能

1. 附件
2. Markdown 编辑器和预览
3. 版本历史
4. 回收站
5. 多端同步
6. MFA
7. 端到端加密模式
8. PostgreSQL 多实例部署

## 总结

GNotes 不需要立即复制 Joplin 或 TriliumNext 的全部功能。当前最有价值的差异化方向是：

> 简单、易部署、服务端加密、备份可靠、适合个人或小团队长期自托管。

因此，优先级应是：

1. 备份状态持久化
2. 恢复验证
3. Drive 保留策略安全性
4. Docker 健康检查
5. CI 和真实 Docker 集成测试
6. 标签、文件夹和客户端搜索

完成这些后，GNotes 会从“能运行的 MVP”提升为“可以长期自托管使用的项目”。

## 参考项目

- [Joplin](https://github.com/laurent22/joplin)
- [Joplin Server](https://github.com/laurent22/joplin/tree/dev/packages/server)
- [TriliumNext](https://github.com/TriliumNext/Trilium)
- [Standard Notes App](https://github.com/standardnotes/app)
- [Memos](https://github.com/usememos/memos)
- [Outline](https://github.com/outline/outline)
