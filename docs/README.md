# 单词项目文档索引

> 2026-10-29 拆分。本目录六份文档各管一件事。**按任务类型只读需要的部分，不要每次全读。**

## 读哪份

| 你现在要做什么 | 读这个 | 体量 |
|---|---|---:|
| 任何任务开工前 | 本文 + PLAN 的 §2 性能目标、§7 不变量 | ~5 KB |
| 挑一个 Phase 开始干 | [PHASES.md](./PHASES.md) 的「执行状态总表」+ 对应 Phase 一节 | 2–3 KB |
| 想知道为什么这么改、模块边界怎么划 | [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) 的对应章节 | 按节 ~2–6 KB |
| 要派子 Agent、多 Agent 并发、建 worktree | [AGENT_PROTOCOL.md](./AGENT_PROTOCOL.md) + [AGENT_SKILL_MATRIX.md](./AGENT_SKILL_MATRIX.md) | ~49 KB |
| 单个 Agent 顺序干活 | **不要读 AGENT_PROTOCOL.md** | — |

单 Agent 干活时，AGENT_PROTOCOL.md 的 25 KB 全部与你的任务无关。省下来的是上下文预算。

## 文档分工

| 文档 | 唯一职责 | 是否定义任务 |
|---|---|---|
| [AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md) | 为什么改、改到什么程度、什么不能破 | 否，只给方向和约束 |
| [PHASES.md](./PHASES.md) | 任务顺序、文件范围、验收门槛、执行状态 | **是，唯一任务源** |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | 目标架构、边界、技术选型、设计模式取舍 | 否 |
| [AGENT_PROTOCOL.md](./AGENT_PROTOCOL.md) | 多 Agent 递归、租约、worktree、日志、验收闭环、合并互斥 | 否 |
| [AGENT_SKILL_MATRIX.md](./AGENT_SKILL_MATRIX.md) | agent / skill 路由、递归预算、上下文阈值 | 否 |

冲突时的优先级：

1. 任务顺序和验收门槛 → 以 PHASES.md 为准。
2. 安全、数据正确性、解耦红线 → 以 ARCHITECTURE_REFERENCE.md 为准。
3. 两者都写了但说法不同 → 停手记录冲突，不要自创第五份计划。

## 三条硬规则

1. 改源码前先 `git status`。工作区里不是自己写的改动，不覆盖、不回滚。
2. 一轮改动只部署一次；部署前确认最近 10 分钟没人动过线上。
3. 别重复造轮子。第一章 200 词补全逻辑已存在于 `fillDeckInBackground` + `pendingSeek` + `chapterExpectedLength`，不要再写第二套。

## 现状快照（2026-10-29）

| 项 | 状态 |
|---|---|
| git 远程 / PR | 无。部署走 `python scripts/deploy.py` |
| 工作区 | 约 28 条未提交改动，开工前先厘清归属 |
| Phase 0–5 | 全部未开始 |
| 测试 | `python scripts/tools/run_tests.py` |
| 性能脚本 | `scripts/tools/measure_perf.py` 存在，但只测首屏 5 项，见 PHASES.md Phase 0 |
