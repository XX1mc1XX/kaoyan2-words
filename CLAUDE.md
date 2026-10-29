# 项目指令

本仓库可能有多条 AI 会话并发改动。动手前必读 @AGENTS.md。

三条硬规则：

1. **改源码前先 `git status`** —— 工作区里不是自己写的改动，不要覆盖、不要回滚。
2. **部署互斥** —— 一轮改动只部署一次，部署前确认最近 10 分钟没人动过线上。
3. **别重复造轮子** —— 第一章 200 词的补全逻辑已存在于 `fillDeckInBackground` + `pendingSeek` + `chapterExpectedLength`，不要再写第二套。

测试：`python scripts/tools/run_tests.py`。
部署：`python scripts/deploy.py`（构建 + 测试 + 部署一条龙）。
