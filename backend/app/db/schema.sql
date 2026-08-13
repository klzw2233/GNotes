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
