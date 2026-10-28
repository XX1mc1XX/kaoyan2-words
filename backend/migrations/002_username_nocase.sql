-- 迁移 002：用户名不区分大小写唯一
--
-- 执行前先确认没有历史重复（有重复时建索引会失败）：
--   SELECT username, COUNT(*) FROM users GROUP BY username COLLATE NOCASE HAVING COUNT(*) > 1;
-- 有结果就先决定保留哪个账号，把另一个改名或删掉再执行本文件。
--
-- 应用命令：
--   npx wrangler d1 execute kaoyan2-users --remote --file backend/migrations/002_username_nocase.sql

CREATE UNIQUE INDEX IF NOT EXISTS users_username_nocase ON users (username COLLATE NOCASE);
