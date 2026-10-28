-- 用户与同步进度表
CREATE TABLE IF NOT EXISTS users (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  username   TEXT    NOT NULL UNIQUE,
  pass_hash  TEXT    NOT NULL,
  pass_salt  TEXT    NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT    PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS progress (
  user_id    INTEGER PRIMARY KEY,
  payload    TEXT    NOT NULL,
  updated_at INTEGER NOT NULL
);

-- 设备配对码：电脑生成 6 位码，手机输入即登录同一账号（10 分钟有效）
CREATE TABLE IF NOT EXISTS pair_codes (
  code       TEXT    PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
