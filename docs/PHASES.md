# 分阶段执行单（当前实现）

> 更新时间：2026-10-29。这里记录已验证的阶段结果、剩余发布动作和执行门禁。
>
> 方向与不变量：[AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md)
> 当前架构：[ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md)

## 执行状态总表

状态只使用：`未开始`、`进行中`、`阻塞`、`完成`。完成必须有命令或可复核证据。

| Phase | 已交付结果 | 状态 | 证据 |
|---|---|---|---|
| 0 性能基线 | Edge fresh-profile 基线覆盖冷启动、首章补全、切章、搜索、分页、64 shard 写入、音频和同步快照 | 完成 | 2026-10-29 `measure_perf.py`：首卡 p50/p95 120/154.8 ms，DOM 240，HTML gzip 11,813 B，JS gzip 37,131 B |
| 1 热路径存储 | generation + 64 shard；翻词只写一个分片；`ky_pos_v1` 单独保存位置 | 完成 | `run_tests.py` 覆盖旧键迁移、单分片写、账号隔离、失败不切换 generation；分片写 p50/p95 0.00/0.10 ms |
| 2 启动与恢复 | 40 词内联 + 200 词首章补全；`pendingSeek` 按词恢复；第一章显示 `第 1 / 200 个` | 完成 | 回归测试 318/318；离线检查第 1 章 200/200；partial resume 测试通过 |
| 3 详情、音频与离线 | 详情按字母分片；音频规范化、去重、确认落盘、淘汰通知；fresh-profile 断网验收 | 完成 | `offline_check.py` 20/20，覆盖四本词库、切章、词表、详情、中英音频、断网重启 |
| 4 同步与 serverFence | `shared/merge.js` 唯一实现；服务端权威 fence；clear/import 分流；D1 乐观锁 | 完成 | 回归覆盖 reset/import fence、旧设备防复活、每日合并、gzip 解压上限、Worker 合并；导入使用稳定 operationId 和点击时刻 fence，重试幂等，游客破坏字段不进入账号 |
| 5 前端拆分与交付 | 12 个有序源码片段；bundle 装配；CI；构建锁；发布锁；双域名验收 | 完成（本地） | `frontend_bundle.py --check` 通过；数据测试 14/14、回归 318/318；CI workflow 已定义；无远程，尚无托管 CI 运行记录 |

Phase 0–5 的工程交付已闭合。当前没有“全部未开始”或“等待建立基线”的任务。

## 当前发布状态

截至 **2026-10-29 20:41 +08:00**：

| 项 | 事实 |
|---|---|
| HEAD | `2d2eaa5b6f9db8879a20447edee3cbe2eb655a09` |
| 本地构建 | build `76060d85d857`，app `./app.4defd52cb022.js` |
| 公共域名 | app `./app.9775dd28fffb.js`，SW `4e120f40cd87` |
| `/build-meta.json` | 公共域名未返回有效构建元数据 |
| `/api/health` | 200，`{"ok":true,"database":true}` |
| 结论 | 当前 HEAD 尚未确认上线；下一次发布必须以 `deploy.py` 的双域名验收通过为准 |

这不是待开发阶段，而是唯一的发布闭环动作：确认最近 10 分钟无并发提交/部署后，执行一次 `python scripts/deploy.py`，全绿后才可更新本节和提交信息。

## 每次开工门禁

单 Agent 也必须执行：

```powershell
git status
git log --oneline -3
Get-Item software/src/app.manifest.json, software/template.html | Select-Object LastWriteTime
python scripts/frontend_bundle.py --check
python scripts/tools/run_tests.py
```

- 发现不是本任务产生的改动：记录、避开，不覆盖、不回滚。
- `software/src/`、`software/src/shell.html`、`software/src/styles.css`、`software/template.html` 属于同一前端写域；同一时间只允许一个会话修改。
- `software/template.html` 是 `frontend_bundle.py` 生成物，不手工改。
- `shared/merge.js`、D1 迁移和生产部署不能并行写。
- 涉及 `zhVoice`、卡片 padding、undo、音频缓存、章节位次等在制工作时先确认归属。
- 发布前必须确认最近 10 分钟无人提交或部署；一轮改动只部署一次。

## 修改后的验收入口

```powershell
python scripts/frontend_bundle.py --check
python scripts/make_html.py
python scripts/tools/run_tests.py
python scripts/tools/offline_check.py --json
python scripts/tools/measure_perf.py
```

当前本地基线：

- 数据测试：14/14。
- 回归：318/318。
- 离线：20/20。
- 首屏性能：首卡 p50/p95 120/154.8 ms；DOM 240；首屏 HTML gzip 11,813 B；主程序 gzip 37,131 B。

测试失败、生成物过期、离线检查失败或性能门禁失败时不得部署。

## 发布验收

一条命令：

```powershell
python scripts/deploy.py
```

`deploy.py` 会：

1. 创建 `deploy.publish.lock`；默认拒绝脏工作区和未确认的迁移；
2. 运行 `make_html.py`；
3. 校验 `build-meta.json`、`app.<hash>.js` 文件名与内容 SHA；
4. 运行回归和真实离线检查；
5. 部署到 Cloudflare Pages；
6. 同时验收 deployment URL 和 public URL 的 build-meta、SW、HTML、主程序字节、fresh Edge 运行时、SW 控制与 `/api/health`。

只有最后打印 `release=ok` 且双域名均通过，才能把版本写入提交信息并对外宣称已上线。

## 任务记录模板

只保留足够让下一会话复核的字段：

```text
Task ID:
目标（一个可验证结果）:
允许修改文件:
禁止修改:
base commit:
实施命令:
功能/离线结果:
性能前后:
回滚方法:
发布 build / app hash:
遗留风险:
```

多 Agent 并发时再使用 [AGENT_PROTOCOL.md](./AGENT_PROTOCOL.md) 的租约、worktree、fencingToken 和独立验收字段；单 Agent 不复制整套控制面。
