# 本仓库协作规则（多会话并发）

这个仓库同时可能有多个 AI 会话（Claude / Codex）在改。违反下面的规则会导致改动被互相覆盖。

## 谁是主线

- 动手改源码前先跑 `git status` 和 `git log --oneline -3`，确认工作区里没有别人的在制改动。
- 发现不是自己写的改动（例如 `zhVoice`、卡片 padding 这类），**不要覆盖、不要回滚**，先确认归属。
- 同一时间只让一条会话负责 `software/template.html`。改之前看文件 mtime，几分钟内被别人写过就等一等。

## 部署互斥

- 部署前先看 `git log --oneline -3`，确认最近 10 分钟没人提交或部署。
- 一轮改动只部署一次；部署后把版本号（`app.<hash>.js`）写进 commit message。
- 线上验证用全新 `--user-data-dir` 的 Edge headless，否则 Service Worker 旧缓存会让结论相反。

## 已验证的事实（不要重复实现）

- 网页版首屏只内联 40 个词（`scripts/make_html.py` 里 `slim[:40]`），而章节按 `CHAPTER_SIZE = 200` 切。
  第一章能显示 200 是靠 `software/template.html` 里的 `fillDeckInBackground` + `pendingSeek` + `chapterExpectedLength`。
  **不要再写第二套补全逻辑。**
- 2026-10-29 已上线并验证：第一章显示「第 1 / 200 个」。

## 测试与部署

- 改完先跑 `python scripts/tools/run_tests.py`，全绿再动线上。
- 一条命令走完构建 + 测试 + 部署：`python scripts/deploy.py`。
