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
| 2 启动与恢复 | 40 词内联 + 200 词首章补全；`pendingSeek` 按词恢复；第一章显示 `第 1 / 200 个` | 完成 | 回归测试 319/319；离线检查第 1 章 200/200；partial resume 测试通过 |
| 3 详情、音频与离线 | 详情按字母分片；音频规范化、去重、确认落盘、淘汰通知；fresh-profile 断网验收 | 完成 | `offline_check.py` 20/20，覆盖四本词库、切章、词表、详情、中英音频、断网重启 |
| 4 同步与 serverFence | `shared/merge.js` 唯一实现；服务端权威 fence；clear/import 分流；D1 乐观锁 | 完成 | 回归覆盖 reset/import fence、旧设备防复活、每日合并、gzip 解压上限、Worker 合并；导入使用稳定 operationId 和点击时刻 fence，重试幂等，游客破坏字段不进入账号 |
| 5 前端拆分与交付 | 12 个有序源码片段；bundle 装配；CI；构建锁；发布锁；双域名验收 | 完成（本地） | `frontend_bundle.py --check` 通过；数据测试 14/14、回归 319/319；CI workflow 已定义；无远程，尚无托管 CI 运行记录 |

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
| P0 | 配置远程 Git 仓库并跑通托管 CI | 未开始 | 仓库无 remote；`.github/workflows/ci.yml` 只是本地配置，没有 GitHub Actions 运行记录 | 远程 HEAD 与本地一致；CI 在干净 checkout 跑通数据测试、319 项回归、离线检查和性能门禁 |
| P0 | 建立 release tag 和构建产物归档 | 未开始 | 已记录 build `c18904c08771` / app `app.4defd52cb022.js`，但没有 tag、附件或不可变归档 | 创建 release tag；归档 `deploy/`、`build-meta.json`、app、SW、单文件版并校验 SHA-256 |
| P0 | D1 备份、恢复和 migration 回滚演练 | 未开始 | 迁移账本存在；没有实际恢复演练记录 | 从明确备份点恢复测试库；账号、会话、进度完整；回滚步骤有真实命令和结果 |
| P0 | 真实双设备生产同步演练 | 未开始 | 已有 Worker harness 和本地并发回归，但没有两台真实浏览器对线上 D1 演练 | 覆盖 clear/import、响应丢失重试、游客登录、会话过期、旧设备重连和乱序请求；两端最终收敛 |
| P0 | 旧 Service Worker 升级到新 build | 未开始 | 部署验收使用全新技术 Edge profile，只证明新用户正常 | 旧 profile 已由旧 SW 控制后升级到新 build，页面不白屏，旧 shell 淘汰，新版本断网仍可启动 |
| P0 | 用修复后的 `deploy.py` 完整跑一次发布 | 未开始 | 本次线上验收已人工全通过；但首次脚本因 Python TLS 假失败，修复后遵守“一轮只部署一次”没有重发 | 下次发布由修复后的 `deploy.py` 从构建到双域名验收一次跑完并打印 `release=ok` |
| P1 | 真机与浏览器矩阵 | 未开始 | 当前性能是 Windows Edge headless + 本地 HTTP + 本地 WAV | 至少覆盖 iPhone Safari、Android Chrome、低端安卓和微信内置浏览器；首卡、滑动、音频、SW、断网和锁屏恢复通过 |
| P1 | 真实音频服务 soak test | 未开始 | 代理、缓存状态和离线写入已测；真实英文源与中文 TTS 未做长时间限流测试 | 连续下载章节/词库、429/5xx、断网续传、Wi-Fi/移动网络切换均符合预期 |
| P1 | 接近 512 KiB 的数据规模压测 | 未开始 | 当前基准约 2400 条记录、同步快照 182,332 B | 接近上限的真实账号仍可同步；400 天墓碑清理、重复导入导出和长期每日记录不造成 413 或存储膨胀 |
| P2 | 线上监控和告警 | 未开始 | 目前只有 `/api/health` 人工检查 | Worker 5xx、D1 错误、音频失败、前端未捕获错误、同步冲突和版本分布有监控与告警 |
| P2 | 正式回滚演练 | 未开始 | 有构建/发布检查，没有线上回滚演练记录 | 能从 Cloudflare Pages 回退到上一个 deployment；旧前端与当前 Worker 兼容；D1 数据不丢失 |

## 下次执行顺序

1. **先做可追溯和备份**：配置 remote，跑托管 CI，创建 release tag 并归档本次构建；随后导出 D1 并完成恢复演练。
2. **再做真实同步验证**：用两个独立测试账号和两台真实浏览器，验证 clear/import、响应丢失、游客登录、会话过期、旧设备和多标签位置。
3. **验证升级路径**：准备一个被旧 Service Worker 控制的持久 profile，部署下一个候选版本，确认自动更新、旧缓存淘汰和断网启动。
4. **补真机矩阵**：iPhone Safari、Android Chrome、低端安卓、微信内置浏览器；记录首卡、第一章 200 词、音频、SW、锁屏恢复和弱网表现。
5. **验证音频与数据上限**：真实音频源 soak test；构造接近 512 KiB 的测试账号，确认不会永久 413。
6. **最后补监控和回滚**：接入错误/版本/同步指标；演练回退上一个 deployment，并记录结果。
7. **下一轮发布验收**：由修复后的 `deploy.py` 一次跑完，确认 `release=ok`，同时记录 public URL、deployment URL、build、app、tag 和归档位置。

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

当前本地基线：

- 数据测试：14/14。
- 回归：319/319。
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
