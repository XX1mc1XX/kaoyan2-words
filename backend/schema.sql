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

-- 设备配对码：电脑生成 6 位码，手机输入即登录同一账号（5 分钟有效）
CREATE TABLE IF NOT EXISTS pair_codes (
  code       TEXT    PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

-- 简单限流：key = 动作:IP，窗口期内计数
CREATE TABLE IF NOT EXISTS rate (
  key      TEXT    PRIMARY KEY,
  n        INTEGER NOT NULL,
  reset_at INTEGER NOT NULL
);

-- 运行指标：只记异常事件（5xx、D1 故障、音频上游失败、同步冲突、客户端报错）。
-- 正常请求一条不写，写入量与故障率成正比，平时几乎零 D1 写入。
-- 按 UTC 天聚合，30 天前的行在 sweepExpired 里顺手删掉。
CREATE TABLE IF NOT EXISTS metrics (
  day  TEXT    NOT NULL,
  name TEXT    NOT NULL,
  n    INTEGER NOT NULL,
  PRIMARY KEY (day, name)
);

-- 用户名不区分大小写唯一。UNIQUE(username) 是二进制比较，
-- 并发注册时 Alice / alice 能双双插入，之后登录会随机命中其中一个，
-- 两个账号就会互相看到对方进度。判重和登录都走这个索引。
CREATE UNIQUE INDEX IF NOT EXISTS users_username_nocase ON users (username COLLATE NOCASE);
