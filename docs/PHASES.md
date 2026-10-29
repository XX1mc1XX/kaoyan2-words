# 分阶段执行单（唯一任务源）

> 本文件是仓库里唯一的任务顺序来源。架构参考和技能矩阵都不另排 Phase。
> 从第一个「未开始」且前置依赖已满足的 Phase 开始，一次只做一个可独立验收的子任务。
>
> 方向与不变量 → [AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md)
> 架构边界 → [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md)
> 多 Agent 并发 / 租约 / worktree → [AGENT_PROTOCOL.md](./AGENT_PROTOCOL.md)

## 执行状态总表

状态只能填：`未开始`、`进行中`、`阻塞`、`完成`。完成后必须追加证据链接或摘要，不能只打勾。

| Phase | 目标 | 前置依赖 | 状态 | 验收证据 |
|---|---|---|---|---|
| 0 性能基线 | 可重复记录冷/热/离线及交互数据 | 无 | 未开始 | 待填写 |
| 1 热路径止血 | 存储和滑动不再产生同步大写入 | Phase 0 | 未开始 | 待填写 |
| 2 启动与恢复 | 40 条内联、200 词章节、上次词恢复稳定 | Phase 0；恢复回归已具备 | 未开始 | 执行时重跑并填写当前计数 |
| 3 IndexedDB | 大进度迁移且可双读、回退、回滚 | Phase 1、2 | 未开始 | 待填写 |
| 4 详情与音频 | 去重、取消、失败不缓存、预算可控 | Phase 0；相关回归测试 | 未开始 | 待填写 |
| 5 模块与 CI | 模块拆分、架构规则和性能门禁 | Phase 1–4 | 未开始 | 待填写 |

## 每次开工的门禁

单 Agent 顺序执行也必须跑；多 Agent 的写任务另加租约和固定 SHA 门禁（见 AGENT_PROTOCOL.md）。

```powershell
git status
git log --oneline -3
Get-Item software/template.html | Select-Object LastWriteTime
python scripts/tools/run_tests.py
```

- 发现不是本任务产生的改动时，记录并按路径避开，不得回滚或覆盖。
- 出现以下任一情况时**停止并确认归属，不可覆盖**：工作区有别人的在制改动；`template.html` 几分钟内被改过；改动涉及 `zhVoice`、卡片 padding 等他人功能；部署目录被占用。
- `software/template.html` 同一时间只允许一个会话修改；mtime 在几分钟内且归属不明时，任务状态写"阻塞"。
- 不修改他人正在处理的 `zhVoice`、卡片 padding、undo、音频缓存和章节位次逻辑。
- 同一轮只部署一次；部署前必须最近 10 分钟无人提交或部署，并使用全新 Edge `--user-data-dir` 验证。

> 现状（2026-10-29 实测）：工作区约 28 条未提交改动（15 修改 + 13 未跟踪），`main` 无远程、无 PR。多 Agent 要求的"干净基线"当前**不满足**——开工前必须先厘清这批改动归属并提交或清理，否则 worktree 基线不可追溯。

## 任务卡模板

每个子任务开工前复制模板并填完整；没有测量结果不得标"完成"。

单 Agent 任务只填**前 10 行 + 验收 + 结果**即可。租约、fencingToken、rootRunId/depth、teamSlot 这些字段只有多 Agent 并发写任务才需要，规则见 AGENT_PROTOCOL.md。

```text
Task ID:
Phase:
Run ID:
父 Agent:
实现 Agent / 模型:
验收 Agent:
目标（只写一个可验证结果）:
worktree（仅写任务）:
branch:
base commit:
允许修改的文件:
禁止修改的文件/行为:
租约资源（repo:<relative-path> / deploy: / d1:）:
leaseKey:
fencingToken:
heartbeatAt / expiresAt:
resourceType:
contractsTouched:
mergeGroup:
generatedFiles:
teamSlot / parentPid:
rootRunId / parentRunId:
depth / max_depth:
canSpawn:
spawnBudgetRemaining / childQuota:
allowedSkills:
contextWindow / checkpoint 阈值:
前置证据:
实施步骤:
回滚方法:
功能验收:
性能验收:
实际命令:
实际结果:
上下文 checkpoint:
遗留风险:
```

---

## Phase 0：性能基线

现状（2026-10-29 核对）：`scripts/tools/measure_perf.py` 已存在，用 Edge headless 注入探针，只测 `fcp / dcl / load / firstCard / nodes` 五个值。它**不覆盖** localStorage 写入、滑动 p50/p95、章节切换、详情打开、音频延迟，也不区分冷/热/离线。所以本 Phase 是"扩展现有脚本"，不是新建第二套。

文件：

- `scripts/tools/measure_perf.py`（扩展此文件，不新建平行脚本）
- 结果目录 `artifacts/perf/`

任务（按顺序，前一项跑通再做下一项）：

1. 冷启动基线：全新 `--user-data-dir` + 生产构建 → `fcp / dcl / firstCard / nodes / 请求数`。
2. 热启动基线：同一 profile 二次加载 → 同上一组指标。
3. 离线基线：断网后加载 → 首卡片是否出现、耗时多少。
4. localStorage 写入插桩：在现有 `save` 旁加计数器（仅测试环境开启，默认关闭），记录 key、字节数、调用来源。跑 100 次滑动，统计写入次数与单次耗时峰值，并断言 pointermove 期间写入数为 0。
5. 滑动帧率：100 次与 1000 次滑动，记录帧间隔 p50 / p95 和 >50 ms 长任务数。
6. 章节切换：记录从触发到"可用卡片出现"的耗时，当前章节与跨章节各测一次。
7. 详情打开：分片已缓存 / 未缓存两种各测一次，记录耗时与网络请求数。
8. 音频：记录热缓存命中耗时、在线拉取耗时、系统语音回退占比。

退出：

- 冷 / 热 / 离线三组都有一份可复跑的 JSON。
- 第 4–8 项每项至少一组数字；确实测不到的项在基线文件里写 `not-measured` + 原因，不能留空。
- 基线文件带 `commit`（当前 HEAD SHA）与 `measuredAt` 字段。
- 不修改业务逻辑；插桩代码默认关闭。

> 为什么这步不能跳：Phase 1 / Phase 4 的验收写的是"100 次滑动通过""详情打开 < 200 ms"，没有第 4–7 项的数字就无法判定通过与否。

## Phase 1：热路径止血

文件：

- `software/template.html`
- 必要时 `shared/merge.js`

任务：

- 消除 pointermove 中存储写入。
- 合并高频状态写入。
- 减少滑动期间全量序列化。
- 减少重复 DOM 更新。
- 延迟统计和同步。

退出：

- 100 次滑动测试通过。
- 进度恢复通过。
- 首卡片不退化。

## Phase 2：启动与恢复

文件：

- `software/template.html`
- `scripts/tools/run_tests.py`

任务：

- 保留 40 条内联数据和 200 词章节语义。
- 补全前不渲染错误第一词。
- `pendingSeek` 按词恢复。
- 保存位次作为词丢失后的回退。
- 增加对应回归测试。

退出：

- 第 80 词恢复测试通过。
- 第一章 200 词测试通过。
- 离线恢复测试通过。

## Phase 3：IndexedDB 存储

文件：

- 新增 `software/storage.js` 或等效模块
- `software/template.html`
- `scripts/tools/run_tests.py`

任务：

- 建立 IndexedDB adapter。
- 双读迁移。
- 批量事务。
- 失败回退。
- 删除旧 key 前校验。

退出：

- 大状态不阻塞。
- 刷新、账号切换、导入导出全绿。
- 可人为回滚。

## Phase 4：详情与音频

文件：

- 详情加载模块
- 音频缓存模块
- `software/sw.template.js`

任务：

- 请求去重。
- 失败不缓存。
- 取消无效请求。
- 控制预取数量和缓存预算。
- 保持离线回退。

退出：

- 详情和音频基准通过。
- 无缓存标记错位。
- 不影响首屏。

## Phase 5：模块拆分和 CI 门禁

文件：

- 拆分后的 Web 模块
- `scripts/tools/run_tests.py`
- CI 配置

任务：

- 拆出 storage、api、deck、study、sync、audio、view。
- 加入循环依赖和文件大小检查。
- 加入 bundle 和性能预算。
- 建立前后截图和性能对比。

退出：

- 单文件职责达标。
- 首屏不退化。
- 全量回归通过。
