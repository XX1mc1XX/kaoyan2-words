-- 迁移 003：运行指标表
--
-- 只存聚合计数（day + name + n），不存请求体、IP 或用户名。
-- 应用命令：
--   npx wrangler d1 execute kaoyan2-users --remote --file backend/migrations/003_metrics.sql

CREATE TABLE IF NOT EXISTS metrics (
  day  TEXT    NOT NULL,
  name TEXT    NOT NULL,
  n    INTEGER NOT NULL,
  PRIMARY KEY (day, name)
);
