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
| 2 启动与恢复 | 40 词内联 + 200 词首章补全；`pendingSeek` 按词恢复；第一章显示 `第 1 / 200 个` | 完成 | 回归测试 321/321；离线检查第 1 章 200/200；partial resume 测试通过 |
| 3 详情、音频与离线 | 详情按字母分片；音频规范化、去重、确认落盘、淘汰通知；fresh-profile 断网验收 | 完成 | `offline_check.py` 20/20，覆盖四本词库、切章、词表、详情、中英音频、断网重启 |
| 4 同步与 serverFence | `shared/merge.js` 唯一实现；服务端权威 fence；clear/import 分流；D1 乐观锁 | 完成 | 回归覆盖 reset/import fence、旧设备防复活、每日合并、gzip 解压上限、Worker 合并；导入使用稳定 operationId 和点击时刻 fence，重试幂等，游客破坏字段不进入账号 |
| 5 前端拆分与交付 | 12 个有序源码片段；bundle 装配；CI；构建锁；发布锁；双域名验收 | 完成（本地） | `frontend_bundle.py --check` 通过；数据测试 14/14、回归 321/321；CI workflow 已定义；无远程，尚无托管 CI 运行记录 |

Phase 0–5 的功能工程已经闭合，但生产化验证和运维闭环尚未全部完成；后续任务顺序以本文件的“发布后生产化剩余任务”为准。

## 当前发布状态

截至 **2026-10-29 21:11 +08:00**：

| 项 | 事实 |
|---|---|
| 发布源码 | `4368766` |
| 线上构建 | build `c18904c08771`，app `./app.4defd52cb022.js` |
| 公共域名 | app `./app.4defd52cb022.js`，SW build `c18904c08771` |
| `/build-meta.json` | 200 JSON，与本地 build/source/app 完全一致 |
| `/api/health` | 200，`{"ok":true,"database":true}` |
| 结论 | 已上线；public URL + deployment URL 双域名 fresh Edge 验收通过 |

本地构建已前进到 build `0e51ab571177`（含 Worker 侧指标与 `/api/metrics`），**尚未部署**：线上仍是 `c18904c08771`。本地与线上的 build 不同是预期状态，不是漂移。

本轮发布闭环已完成；下次发布仍必须重跑 10 分钟互斥、构建、回归、离线与双域名 fresh Edge 验收。
## 两个发布地址的区别

| 名称 | 当前地址 | 用途 | 是否给普通用户 |
|---|---|---|---|
| public URL | `https://kaoyan2-words.pages.dev/` | Cloudflare Pages 项目的稳定生产入口；以后发布新版本时通常继续使用这个地址 | 是，唯一正式入口 |
| deployment URL | `https://138572ea.kaoyan2-words.pages.dev/` | 某一次具体 deployment 的技术地址；用于确认本次上传的精确产物，并排除“上传成功但生产别名还没切过去” | 否，仅验收、排障和追溯 |

两个地址现在打开一样是正常现象：production 已经指向本次 deployment，所以稳定入口和本次 deployment 地址返回同一套 HTML、app、SW 和数据。必须同时验收两者，是为了证明：

1. 本次精确 deployment 本身可运行；
2. 稳定 public URL 确实已经切换到该 deployment。

注意：不同域名属于不同的浏览器 origin，`localStorage`、IndexedDB、Cache Storage 和 Service Worker 都相互隔离。不要用 deployment URL 判断某个真实用户在 public URL 下的登录、进度或离线缓存；它只用于发布验收和故障定位。两处访问的是同一个 Pages 项目及同一套生产 Worker/D1 绑定，不是两个数据库。

## 发布后生产化剩余任务

状态只使用 `未开始`、`进行中`、`已完成`。以下事项不阻塞当前已经上线的核心版本，但在完成前，不能宣称“长期生产稳定性全部闭环”。

| 优先级 | 任务 | 状态 | 当前事实 | 完成标准 |
|---|---|---|---|---|
| P0 | 配置远程 Git 仓库并跑通托管 CI | 已完成 | remote 指向 `XX1mc1XX/kaoyan2-words`，远程 HEAD 与本地一致；CI run `40903352211` 在干净 Windows checkout 跑通数据测试、319 项回归、离线检查与性能门禁 | 远程 HEAD 与本地一致；CI 在干净 checkout 跑通数据测试、319 项回归、离线检查和性能门禁 |
| P0 | 建立 release tag 和构建产物归档 | 已完成 | tag `v1.0.0`；GitHub Release 附 `kaoyan2-words-c18904c08771.zip`、`SHA256SUMS`、`build-meta.json`；归档由 `scripts/tools/archive_release.py` 生成 | 创建 release tag；归档 `deploy/`、`build-meta.json`、app、SW、单文件版并校验 SHA-256 |
| P0 | D1 备份、恢复和 migration 回滚演练 | 已完成（本地） | `python scripts/tools/d1_drill.py` 全绿：导出→清空→导入→进度 payload 逐字节一致→clear+reimport 回滚路径验证；远程模式需 `CLOUDFLARE_API_TOKEN`，尚未在生产库执行 | 从明确备份点恢复测试库；账号、会话、进度完整；回滚步骤有真实命令和结果 |
| P0 | 真实双设备生产同步演练 | 已完成（契约级） | `python scripts/tools/sync_two_device.py` 覆盖游客登录合并、旧设备重连、clear 不复活、重试幂等、乱序同步、过期会话 401；两个独立会话对同一 Worker，不是两台真实浏览器 | 覆盖 clear/import、响应丢失重试、游客登录、会话过期、旧设备重连和乱序请求；两端最终收敛 |
| P0 | 旧 Service Worker 升级到新 build | 已完成（本地） | `python scripts/tools/sw_upgrade_check.py`：持久 profile 先被 build A 控制，改写 sw.js 后升级到 B，旧 shell 只保留一版，页面不白屏，升级后断网仍可启动 | 旧 profile 已由旧 SW 控制后升级到新 build，页面不白屏，旧 shell 淘汰，新版本断网仍可启动 |
| P0 | 用修复后的 `deploy.py` 完整跑一次发布 | 未开始 | 本机 wrangler 认证已过期且非交互环境无法登录，也没有 `CLOUDFLARE_API_TOKEN`，无法执行部署；构建与测试在本地全绿 | 下次发布由修复后的 `deploy.py` 从构建到双域名验收一次跑完并打印 `release=ok` |
| P1 | 真机与浏览器矩阵 | 未开始 | 无真实移动设备可用；当前仍是 Windows Edge headless + 本地 HTTP | 至少覆盖 iPhone Safari、Android Chrome、低端安卓和微信内置浏览器；首卡、滑动、音频、SW、断网和锁屏恢复通过 |
| P1 | 真实音频服务 soak test | 未开始 | 代理、缓存状态和离线写入已测；真实英文源与中文 TTS 未做长时间限流测试 | 连续下载章节/词库、429/5xx、断网续传、Wi-Fi/移动网络切换均符合预期 |
| P1 | 接近 512 KiB 的数据规模压测 | 已完成（本地） | `python scripts/tools/payload_soak.py`：137/266/499 KB 同步返回 200，576 KB 正确 413，11600 个词键重复同步不膨胀、回读一致 | 接近上限的真实账号仍可同步；400 天墓碑清理、重复导入导出和长期每日记录不造成 413 或存储膨胀 |
| P2 | 线上监控和告警 | 进行中 | Worker 侧已落地 `metrics` 表（按 UTC 天聚合）与只读 `/api/metrics`（未配 `METRICS_TOKEN` 时当接口不存在，配了则 token 校验）：记 `http.5xx`、`d1.health_fail`、`audio.upstream_fail`、`sync.conflict`、`client.error:<来源>`，写入走 `waitUntil` 且失败静默，表缺失时只降级不报错。`uptime_watch.py --metrics-token` 已能按阈值告警，本地 pages dev 实测注入 `d1.health_fail=5` 后输出 `["d1.health_fail=5>1"]` 并 exit 1。剩余：生产 D1 未执行 `003_metrics.sql`（`applied.json` 标了 `remotePending`，`deploy.py` 会因此拒绝发布）、`METRICS_TOKEN` 未注入、版本分布无客户端上报来源（前端目前没有 `/api/log` 调用）、`KY_ALERT_WEBHOOK` 未配置。实测本机到生产首页偶发读超时（3 次中 2 次），已内置重试 | Worker 5xx、D1 错误、音频失败、前端未捕获错误、同步冲突和版本分布有监控与告警 |
| P2 | 正式回滚演练 | 未开始 | 有构建/发布检查，没有线上回滚演练记录；回退 deployment 需要 Cloudflare 凭据 | 能从 Cloudflare Pages 回退到上一个 deployment；旧前端与当前 Worker 兼容；D1 数据不丢失 |

## 下次执行顺序

已完成（2026-10-30）：remote + 托管 CI、release tag 与 SHA-256 归档、D1 本地备份/恢复/回滚演练、双设备语义收敛演练、旧 SW 升级演练、512 KiB 同步上限压测。

剩下的事项都卡在“本机没有 Cloudflare 凭据或没有真机”：

1. **拿到 `CLOUDFLARE_API_TOKEN` 后**：先 `npx wrangler d1 execute kaoyan2-users --remote --file backend/migrations/003_metrics.sql`（跑完删掉 `applied.json` 里 `003_metrics.sql` 的 `remotePending`，否则 `deploy.py` 会一直拒绝发布），再给 Pages 项目注入 `METRICS_TOKEN`；然后 `python scripts/tools/d1_drill.py --remote` 导出生产库；再按 `deploy.py` 完整跑一次发布，确认 `release=ok`；随后演练回退到上一个 deployment。
2. **补真机矩阵**：iPhone Safari、Android Chrome、低端安卓、微信内置浏览器；记录首卡、第一章 200 词、音频、SW、锁屏恢复和弱网表现。
3. **验证音频与数据上限的生产侧**：真实音频源 soak test；生产 D1 上构造接近 512 KiB 的测试账号。
4. **补监控闭环**：把 `uptime_watch.py` 挂到本机计划任务，设置 `KY_ALERT_WEBHOOK`；Worker 侧再补 5xx/D1/同步冲突计数与版本分布。

以上 P0 全部完成后，当前版本才算“生产化关键闭环完成”；P1/P2 完成后才算长期稳定性闭环。

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

生产化专项演练（与上面并用，互不替代）：

```powershell
python scripts/tools/d1_drill.py            # 备份→清空→恢复→回滚（本地 D1；--remote 需 token）
python scripts/tools/sw_upgrade_check.py    # 旧 SW profile 升级到新 build，含断网启动
python scripts/tools/payload_soak.py        # 512 KiB 同步上限（需先起 pages dev）
python scripts/tools/sync_two_device.py     # 两台设备语义收敛（需先起 pages dev）
python scripts/tools/uptime_watch.py --once # 线上探活：health/build-meta/首页/app
python scripts/tools/uptime_watch.py --once --metrics-token $env:KY_METRICS_TOKEN  # 加上指标阈值
python scripts/tools/archive_release.py     # 生成带 SHA-256 的 release 归档
```

`payload_soak.py` 和 `sync_two_device.py` 需要一个运行中的本地 Worker：

```powershell
npx wrangler pages dev deploy --port 8799 --ip 127.0.0.1
```

当前本地基线：

- 数据测试：14/14。
- 回归：321/321。
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
