# 单词项目文档索引

> 更新时间：2026-10-29。文档只描述**当前已落地实现**和执行门禁，不把目标架构写成既成事实。

## 按任务读文档

| 你要做什么 | 先读 | 是否还要读 |
|---|---|---|
| 任意任务开工前 | 本页 + `AGENTS.md` | 按任务再读下面文件 |
| 改前端/构建/缓存/同步 | [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) 对应章节 | [PHASES.md](./PHASES.md) 的验收门禁 |
| 查已完成阶段和后续动作 | [PHASES.md](./PHASES.md) | 必要时看本页“当前快照” |
| 判断为什么不转 C++/Qt、性能目标是什么 | [AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md) | [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) |
| 派子 Agent、worktree、租约、并发合并 | [AGENT_PROTOCOL.md](./AGENT_PROTOCOL.md) + [AGENT_SKILL_MATRIX.md](./AGENT_SKILL_MATRIX.md) | 单 Agent 顺序任务不需要这两份 |

## 文档职责

| 文档 | 唯一职责 | 是否定义任务 |
|---|---|---|
| [AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md) | 方向、性能目标、不可破坏的产品语义 | 否 |
| [PHASES.md](./PHASES.md) | 阶段状态、证据、剩余发布动作、验收入口 | **是** |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | 当前架构、数据/缓存/同步协议、模块边界 | 否 |
| [AGENT_PROTOCOL.md](./AGENT_PROTOCOL.md) | 多 Agent 调度、租约、worktree、独立验收 | 否 |
| [AGENT_SKILL_MATRIX.md](./AGENT_SKILL_MATRIX.md) | Agent/skill 路由和递归预算 | 否 |
| 根目录 [README.md](../README.md) | 产品、目录、构建、发布和实测数据总览 | 否 |

发生冲突时：`AGENTS.md` 的仓库规则优先；任务顺序与验收以 `PHASES.md` 为准；安全、数据正确性和缓存/同步不变量以 `ARCHITECTURE_REFERENCE.md` 为准。不要另写一份并行计划。

## 当前快照（2026-10-29）

| 项 | 当前事实 |
|---|---|
| 技术栈 | 原生 HTML/CSS/JavaScript PWA + Cloudflare Pages/Worker + D1；不转 C++/Qt |
| 前端源 | `software/src/` 的 shell、样式和 12 个有序 JS 片段；由 `scripts/frontend_bundle.py` 装配为 `software/template.html` |
| 构建 | `make_html.py` 生成哈希主程序、词库/详情分片、单文件版和 `deploy/`；构建锁 `deploy.lock`，暂存目录原子切换 |
| 本地状态 | 主状态为 generation + 64 shard；位置为 `ky_pos_v1` 小键，不再每次翻词重写整份章节队列 |
| 同步 | `shared/merge.js` 唯一实现；Worker 使用权威 `serverFence` 处理 clear/import，D1 `updated_at` 做乐观锁 |
| 缓存 | shell 按 build 版本分命名空间，音频固定 `ky-audio-v2`；页面只认 `x-ky-cache=stored/hit` 的落盘凭据 |
| 测试 | 数据 14/14、回归 318/318、离线 20/20（2026-10-29 本地实测） |
| 性能 | 首屏 HTML gzip 11,813 B、主程序 gzip 37,131 B；首卡 p50/p95 120/154.8 ms；详见根 README |
| CI | `.github/workflows/ci.yml` 已定义 Windows 构建、数据测试、回归、离线、性能测量；仓库无远程，尚无托管 CI 运行记录 |
| 发布 | 候选 HEAD `2d2eaa5b6f9db8879a20447edee3cbe2eb655a09`，build `76060d85d857`；公共域名尚未切到该版本 |

## 开工硬门禁

单 Agent 顺序执行也必须跑：

```powershell
git status
git log --oneline -3
Get-Item software/src/app.manifest.json, software/template.html | Select-Object LastWriteTime
python scripts/frontend_bundle.py --check
python scripts/tools/run_tests.py
```

规则：

1. 不覆盖、不回滚不是本任务产生的改动；发现 `zhVoice`、卡片 padding 等在制工作时先停下确认归属。
2. `software/src/`、`software/src/shell.html`、`software/src/styles.css`、`software/template.html` 属于同一前端写域，同一时间只允许一个会话修改；不要只锁生成物而并行改源片段。
3. 修改前端源后必须重新装配并让 `frontend_bundle.py --check` 通过；不要手改生成物。
4. 一轮改动只部署一次；部署前确认最近 10 分钟无人提交或部署。
5. 线上只认 `deploy.py` 的 deployment URL + public URL + 全新 Edge profile + `/api/health` 全套验收；Service Worker 旧缓存不能作为结论依据。

## 已确认的不变量

- 网页首屏最多内联 40 词，`CHAPTER_SIZE = 200`；第一章补全只使用 `fillDeckInBackground` + `pendingSeek` + `chapterExpectedLength`。
- 上次学习位置优先按 `posWord` 恢复，词丢失时才用 `pos` 回退。
- 静态词库不经过 D1；D1 只保存账号、会话、用户进度和必要的服务端元数据。
- clear/import 的 fence 由服务端时间生成；客户端不能自行抬高或回滚。
- 页面“已缓存”标记必须与 SW 实际写入结果一致。
- `shared/merge.js` 是合并逻辑唯一来源，不得在页面和 Worker 各写一份。
