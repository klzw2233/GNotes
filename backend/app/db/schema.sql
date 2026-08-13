-- GNotes 数据库 schema —— 幂等执行（IF NOT EXISTS）

-- users 表：新增 role 列支撑管理员鉴权
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,              -- UUID4
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,                 -- bcrypt（含 salt，60 字符）
    role          TEXT NOT NULL DEFAULT 'user',  -- 'user' | 'admin'
    created_at    TEXT NOT NULL,                 -- ISO8601 UTC
    updated_at    TEXT NOT NULL
);

-- notes 表：标题与正文各用独立 nonce，每次写入/更新重新随机生成（修文档 Nonce 复用瑕疵）
CREATE TABLE IF NOT EXISTS notes (
    id                TEXT PRIMARY KEY,          -- UUID4，不可变（用作 AAD）
    user_id           TEXT NOT NULL,
    title_encrypted   TEXT NOT NULL,             -- Base64(密文‖16字节tag)
    title_nonce       TEXT NOT NULL,             -- Base64(12字节随机nonce)
    content_encrypted TEXT NOT NULL,
    content_nonce     TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 复合索引：支撑列表查询（某用户按 updated_at desc，覆盖 FR-09）
CREATE INDEX IF NOT EXISTS idx_notes_user_upd ON notes(user_id, updated_at DESC);

-- backup_runs 表：持久化备份历史（修 TODO P0-1，进程内存状态容器重启即丢）
-- status 与 verify_status 分离：备份上传成功但恢复验证失败时，status 仍为 success，
-- 既保留“已上传”事实，又能让 UI 提示“可能不可恢复”。
CREATE TABLE IF NOT EXISTS backup_runs (
    id              TEXT PRIMARY KEY,              -- UUID4
    status          TEXT NOT NULL,                 -- 'success' | 'failed'
    filename        TEXT,                           -- backup_<ts>.db.gz.enc
    size_bytes      INTEGER,
    drive_file_id   TEXT,
    error_message   TEXT,                           -- 给运维看的短错误（不回传堆栈）
    verify_status   TEXT,                           -- 'ok' | 'failed' | 'skipped'
    verify_message  TEXT,                           -- 恢复验证结果说明
    started_at      TEXT NOT NULL,                 -- ISO8601 UTC
    finished_at     TEXT NOT NULL
);

-- 按开始时间倒序：支撑“最近N条”“最近成功/失败”“连续失败计数”查询
CREATE INDEX IF NOT EXISTS idx_backup_runs_started ON backup_runs(started_at DESC);
