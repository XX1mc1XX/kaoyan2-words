# 多 Agent 执行协议

> **什么时候读这份**：只有当你要派子 Agent、跑多个 Agent 并发、建 worktree、做独立验收时才读。
> 单个 Agent 顺序干活**不需要**本文件——直接看 [PHASES.md](./PHASES.md) 和 [AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md) 即可。
>
> 职责边界：本文件只管"怎么协作"，不定义任务顺序（那是 PHASES.md），也不定义架构取舍（那是 ARCHITECTURE_REFERENCE.md）。

## 0. 总则

文档分工、读法、硬规则统一见 [README.md](./README.md)。本文件只补充多 Agent 场景下的调度协议。

执行时必须遵守：

1. 阶段顺序以 [PHASES.md](./PHASES.md) 为准。
2. 架构边界以 [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) 的构建链、缓存、同步和“明确不做的事”章节为准。
3. 文档冲突时，任务顺序和验收门槛以 PHASES.md 为准；但不得突破架构参考中的安全、数据正确性和解耦红线。
4. 一项任务完成后更新 PHASES.md 的复选框、证据和日期；不另写第二份任务计划。

### 0.1 给 AI 的执行摘要

按以下顺序执行，禁止跳步：

1. 用 `measure_perf.py` 和 fresh profile 复跑性能基线；已有基线不能替代本次前后数据。
2. 先优化主线程和存储，不先改 UI 框架。
3. 保留现有 40 条启动内联数据、200 词章节补全、Service Worker 和离线能力。
4. 性能、缓存、同步改动必须提供前后测量。
5. 超过性能预算立即回滚，不允许"以后优化"。

### 0.2 直接复制给 AI 的启动提示词

单 Agent 版：

```text
你负责实施 C:\my_project\单词 的下一项性能任务。

先读：
1. docs/README.md（索引和读法；先看这一页）
2. docs/PHASES.md（唯一任务源；从执行状态表里挑 Phase）
3. docs/AI_EXECUTION_PLAN.md 的 §2 性能目标 和 §7 不变量
4. 当前 Phase 需要时，再查 docs/ARCHITECTURE_REFERENCE.md 对应章节
不要读 docs/AGENT_PROTOCOL.md —— 单 Agent 顺序执行用不上。

执行规则：
- 从 PHASES.md 选择当前待办或用户指定的单一任务；阶段表没有“未开始”项时不要自造 Phase。
- 开工前先跑门禁（git status / git log / software/src 与 template.html mtime / frontend_bundle.py --check / run_tests.py），填写任务卡。
- 一次只做一个可独立验收的子任务。
- 只修改任务卡"允许修改的文件"，保留 40 条启动内联数据、200 词章节补全和上次学习位置恢复语义。
- 不覆盖其他会话的改动，不改题外功能，不部署，除非我明确要求部署。
- 完成后给出：改动文件、功能测试结果、性能前后数据、回滚方法、未解决风险。
- 发现文档、工作区或文件所有权冲突时，停止实施并报告冲突，不要自创第五份计划。
```

多 Agent 版（Root Orchestrator）：

```text
你负责实施 C:\my_project\单词 的下一个 Phase，可以派子 Agent。

先读：
1. docs/README.md（索引和读法）
2. docs/PHASES.md（唯一任务源）
3. docs/AI_EXECUTION_PLAN.md 的 §2 和 §7
4. docs/AGENT_PROTOCOL.md（本文件的完整内容）
5. docs/AGENT_SKILL_MATRIX.md（agent / skill 路由）

你是 Root Orchestrator。默认串行；只有存在 2 个以上真正互不依赖的域时才并行，从 2–4 个起步，确认无路径冲突后再按扩容梯子升。
通过 CLI/wrapper 递归派发子 Agent；写子 Agent 必须登记 rootRunId、parentRunId、depth、spawn budget、allowedSkills 和租约；只读子 Agent 使用固定 SHA，不占写租约。
默认预算 max_depth=4、max_active_agents=16、max_write_agents=8（写硬上限 16、总硬上限 32）；这些是配置上限，实际并发从扩容梯子 T0/T1 起步，不是一上来就开满。
实现者、验收者、合并者、部署者权限分离；实现者不能自己标记 accepted。

执行规则：
- 从 PHASES.md 选择当前待办或用户指定的单一任务；阶段表没有“未开始”项时不要自造 Phase。
- 开工前先跑执行门禁，填完整任务卡（本文件 0.3 节）。
- 只修改任务卡"允许修改的文件"，保留 40 条启动内联数据、200 词章节补全和上次学习位置恢复语义。
- 不覆盖其他会话的改动，不改题外功能，不部署，除非我明确要求部署。
- 上下文达到实际有效窗口的约 1/3 时生成 checkpoint；达到约 45% 时停止会话并从 checkpoint 重启。
- 完成后给出：改动文件、功能测试结果、性能前后数据、回滚方法、未解决风险。
- 如果你发现文档、工作区或文件所有权冲突，停止实施并报告冲突，不要自创第五份计划。
```

### 0.3 Claude + Codex 联合控制面（强制）

Claude Code 与 Codex **可以联合，并允许有界递归并行**。采用"父 Agent 单点调度 + 递归 domain tree + 独立 worktree + 文件化任务账本 + 独立验收"：

```text
Depth 0  Root Orchestrator（唯一合并、部署）
  ├─ Depth 1  Domain Lead A（规划/实现/调查）
  │    ├─ Depth 2  Specialist / Implementer（独立 worktree）
  │    │    └─ Depth 3  Read-only Verifier / Researcher
  │    └─ Depth 2  Read-only Reviewer
  ├─ Depth 1  Domain Lead B（与 A 路径不相交）
  │    └─ Depth 2  Specialist
  └─ Deploy Gate（Root 授权的独立门禁会话）
```

默认预算（可通过任务卡调整，但不得无界）：

- `max_depth=4`；只读探索最多 5 层。
- `write_depth_limit=3`；深度 4+ 默认只读。
- 单节点每轮最多 6 个直接子 Agent；同一 root task 最多派生 64 个。
- 默认同时最多 16 个子 Agent；硬上限 32（只读或 OMC team 且 Root 批准）。默认最多 8 个写 Agent、硬上限 16 个，且每个写 Agent 的路径必须完全不相交；排他资源仍是单写。
- 有 2 个以上真正互不依赖的调查域时才可以 fan-out，从 2–4 个起步，确认无路径冲突后再按扩容梯子升；协调成本高于合并收益时退回串行（见本节第 10 条）。不要为了"显得并行"而多开。
- 扩容梯子：T0=1（默认）；T1=4–6（默认上限）；T2=8–12（需 Root 明确批准）；T3=16–24；T4=25–32（只读为主或 Root 明确批准）。单个 OMC team 约 1–20，超过 20 必须拆成多个独立 team，由 Root 维护唯一账本和串行集成。

写入门禁（上限不是目标）：

| 门禁 | 写 Agent 上限 | 必须满足 |
|---|---:|---|
| G0 基线 | 1 | docs 与当前源码冻结为干净 commit |
| G1 控制面 | 2 | wrapper、schema、租约、全局 slot 可运行 |
| G2 dry run | 4 | 1 写 + 1 读 + 独立 Verifier 通过 |
| G3 模块化 | 8 | template/worker/shared 契约完成边界拆分 |
| G4 极限 | 16 | 用户明确批准，16 条路径完全不相交且合并队列为空 |

未达到门禁时，wrapper 必须拒绝预占写 slot。

活动 Agent 计数口径：activeAgents = Root + 所有后代 + 所有 OMC team lead/teammate + 所有 CLI worker + 仍在等待验收的进程。max_active_agents=32 包含 Root；max_write_agents=16 是硬上限，不是默认目标；max_total_spawned=64 包含重试、替换和失败节点。

平台限制未确认时，canSpawn=true 按 false 处理。Claude 原生并发/嵌套 subagent 限制以当前版本和运行时配置为准；达到平台上限时必须收拢或拆成独立 CLI/team，不能绕过全局 slot。

强制规则：

1. 每次递归必须继承并登记 `rootRunId`、`parentRunId`、`taskId`、`depth`、`spawnBudgetRemaining`、`canSpawn`、`allowedSkills`、`allowedPaths`。写节点还要登记 worktree、branch 和租约；只读节点固定 SHA，不占写租约。
2. 子 Agent 只能通过统一 wrapper/CLI adapter 递归；不得绕开账本直接运行 `claude`、`codex`、`team` 或后台 Agent。
3. 子 Agent 可以在预算内继续派生子 Agent；超过 `max_depth`、预算耗尽、路径冲突或上下文达到硬阈值时必须收拢。
4. 实现者只能修改任务卡列出的 `allowed_paths`；越界即失败，不接受"顺手优化"。
5. 验收者不得改代码；实现者不得自己标 `accepted`；最终合并和部署只能由 Root 完成。
6. 所有写任务必须使用独立 `git worktree`；主工作区只用于 Root 集成，禁止并发写。每个写 Agent 的 worktree 由父层绑定，不能和兄弟节点共享。
7. `software/src/`、`software/template.html`、`shared/merge.js`、D1 迁移、生产部署是排他资源；前端源片段与生成模板视为同一写域，名称相同但路径不同的租约也不能重叠。
8. mtime 只是警告，不是锁。租约必须使用 Windows 可用的原子创建（`New-Item`/`CreateNew`/Python `O_CREAT|O_EXCL`）。
9. 当前工作区有未知归属改动时，先冻结基线；不得把别人的改动当成自己的提交。
10. 递归不是目标本身：当任务强依赖、共享契约或合并收益低于协调成本时，必须退回单 Agent 顺序执行。

### 0.4 任务状态机与角色

任务状态只能按以下顺序流转，跳级无效：

```text
queued -> claimed -> running
running -> handoff
running -> waiting_children -> running
handoff -> verifying
verifying -> accepted | changes_requested
changes_requested -> claimed | running
accepted -> integrated
verifying -> blocked
waiting_children -> blocked
blocked -> claimed
```

异常状态：`blocked`、`cancelled`、`rejected`、`rolled_back`。

| 角色 | 权限 | 禁止 |
|---|---|---|
| Root / Integrator | 派工、递归预算、加锁、审 diff、合并、部署 | 不绕过独立验收；不突破全局并发上限 |
| Domain Lead | 拆分子域，按需递归派生专业 Agent | 不跨文件写、不越过父层租约 |
| Implementer | 只改白名单文件，跑定向测试，交 handoff | 不自验收、不合并、不部署；不得在无租约的 worktree 写 |
| Verifier | 只读，在固定 SHA 重跑验收，可递归派生只读检查 | 不改代码、不接受会变化的 working tree |
| Architect Reviewer | 只读，检查边界、重复实现、热路径和架构异味 | 不修代码、不只凭实现者自述 |
| Deploy Gate | Root 授权的独立部署会话 | 不在实现/验收会话内执行；部署前重新验证 |

推荐交叉审查：**Codex 写 → Claude 只读审；Claude 写 → Codex 只读审**。联合发生在父 Agent 的 CLI 调度和文件化交接中，不是两个模型私下直接对话。

### 0.5 上下文 1/3 阈值与防降智协议

目标：在上下文达到实际窗口约 **1/3** 时主动收口，不能让模型"聊到很晚才压缩"。

阈值：

| 级别 | 触发 | 动作 |
|---|---|---|
| 软阈值 | 约 33% 实际上下文窗口 | 停止新探索，生成 checkpoint，完成当前最小闭环 |
| 硬阈值 | 约 45% 实际窗口 | 当前会话不得继续写代码；父 Agent 终止并从 checkpoint 新开会话 |
| 任务完成 | 每个可验收子任务完成 | 无论是否到阈值，都生成 handoff 并清理不必要上下文 |

可执行方式：

1. **Claude 使用自己的默认上下文策略。** 不在项目文档或 wrapper 中强制注入 `CLAUDE_CODE_MAX_CONTEXT_TOKENS`；按 Claude Code 运行时报告的 actual/effective window 计算 1/3。若运行环境存在用户级 context cap 覆盖，把它当作"用户自定义配置"，记录并审计，不能冒充默认值，也不能自动写回。
2. Claude 默认不传 `--autocompact`，完全使用自身默认行为；只有用户明确要求并确认有效窗口时才设置固定值。窗口未知时不要硬编码固定 token 数，由 wrapper 在软阈值时先生成 checkpoint，并读取实际 usage 后决定硬停止。
3. Codex 先读取运行时实际配置；只有确认 `model_context_window=1000000` 且用户明确选择时，才覆盖 `model_auto_compact_token_limit=333000`。否则按实际窗口计算，不能把 1M 配置复制给所有子 Agent。
4. 到达软阈值时，必须生成 checkpoint；到达硬阈值时，硬停止并开新会话，不继续"赌模型还能记住"。
5. 压缩/重启后必须重新注入：任务 ID、允许文件、基线 SHA、不可变量、失败日志路径、下一步唯一动作。
6. 不承诺"压缩后绝不降智"。验收看固定 SHA、命令退出码、原始日志和独立复跑，不看模型主观保证。

checkpoint 只保存可执行事实：

```text
runId / taskId
base commit / current commit
已完成事项
改动文件
最后通过的测试命令与结果
当前失败命令与原始错误
关键决策与未验证假设
下一步唯一动作
禁止修改项
回滚命令
contextUsed / contextWindow / threshold
```

`contextUsed` 无法可靠取得时写 `unknown`，并由父 Agent 采用"每完成一个子任务就 checkpoint"的保守策略；禁止伪造 token 百分比。

### 0.6 Skill 路由与监督（强制）

完整清单、来源路径、递归树和派单提示词见 [AGENT_SKILL_MATRIX.md](./AGENT_SKILL_MATRIX.md)。父 Agent 不得只凭记忆派单，必须先做技能匹配。

本机已扫描到 `C:\Users\xrk\.claude\skills` 下大量 skill，并且启用了 `superpowers`、`oh-my-claudecode`、`context-mode` 等插件。运行时只加载当前任务需要的 1–3 个 skill，不要一次把全部 skill 塞进上下文。

运行时必须先运行 `claude plugin list`；只有状态为 loaded 的插件/skill 才能进入路由。当前扫描中多个 marketplace 插件是 cache-miss，候选列表不等于可直接派单。

最低路由要求：

> 本表区分两类：标 **agent** 的用 `Agent` 工具的 `subagent_type` 派发（完整目录见 `omc-reference`），其余用 `Skill` 工具调用。拿 `Skill` 去调一个 agent 名会直接报找不到。名字已于 2026-10-29 对照 `omc-reference` 的 Agent Catalog 与当前会话 skill 列表核对；插件升级后若有变化，先用 `find-skills` 确认再派单。

| 场景 | 必须优先考虑 |
|---|---|
| 执行多任务计划 | `superpowers:subagent-driven-development` |
| 多个独立问题 fan-out | `superpowers:dispatching-parallel-agents` |
| 创建/执行隔离 worktree | `superpowers:using-git-worktrees` |
| 每个任务后的代码审查 | `superpowers:requesting-code-review` + agent `oh-my-claudecode:code-reviewer` |
| 修复审查意见 | `superpowers:receiving-code-review` |
| 声称完成/提交/部署前 | agent `oh-my-claudecode:verifier` + skill `oh-my-claudecode:verify` + `superpowers:verification-before-completion` |
| 测试先行和回归 | `superpowers:test-driven-development` |
| 根因排查 | `superpowers:systematic-debugging`、agent `oh-my-claudecode:debugger` |
| 架构调查/监督 | agent `oh-my-claudecode:architect`、agent `claude-coding:architecture-auditor`、`ai-agents-architect`、`engineering-software-architect`、`docs-architect` |
| 架构异味/过度设计 | agent `oh-my-claudecode:critic`、`brooks-lint`、`engineering-minimal-change-engineer`、`karpathy-guidelines` |
| 计划/交接文档可执行性 | `docs-architect` |
| 多 Agent 原生团队 / 跨 Codex | `oh-my-claudecode:team`，可用 `N:codex` 派 CLI worker |
| 上下文膨胀/检索 | `context-mode`、`ctx-stats`、`ctx-doctor`、`ctx-search`；`ctx-purge` 只在 Root 明确确认后使用 |
| 不确定该用哪个 skill | `find-skills`；没有匹配才 `skill-creator` + `writing-skills` |

递归与 skill 绑定要求：

1. 每个子 Agent 的 prompt 必须写明 `allowedSkills`；不得自行加载未登记的高风险 skill。
2. 父 Agent 每次递归派单必须选择"实现 skill + 审查 skill + 验收 skill"，不能只派实现者。
3. 子 Agent 可在预算内递归派发独立调查或只读审查；写任务仍受 `write_depth_limit` 和租约限制。
4. 父 Agent 必须用 `oh-my-claudecode:team` 或 `superpowers:dispatching-parallel-agents` 维护共享任务清单；没有共享清单的"多开"无效。
5. 子 Agent 返回的是摘要和证据，不回传完整会话；由父 Agent 负责合并、冲突处理和独立复跑。
6. 任何 skill 的输出都不替代 `python scripts/tools/run_tests.py`、固定 SHA diff 和 fresh profile 验证。

禁止：

- 一开始就转 C++/Qt、React、微服务或更换 D1。
- 为了"架构漂亮"拆出大量只有一层的接口。
- 把完整词库重新内联到首屏。
- 破坏上次学习位置恢复。
- 覆盖其他会话正在修改的 `software/src/`、`software/template.html` 或其生成链。

---

## 1. 工作目录与租约

推荐把机器级协调数据放在仓库外：

```text
C:\my_project\单词                        父 Agent / 集成分支
C:\my_project\单词-worktrees\<task-id>    每个实现者独立 worktree
C:\my_project\单词-coordination\           运行日志、租约、证据
```

仓库内提交的协调规范、schema 和 wrapper 可以放 `.ai/`；运行产物放仓库外或加入 `.gitignore`，禁止提交 PID、token、原始会话和临时产物。

原子租约示例（Windows PowerShell）：

```powershell
# 已存在就失败，避免"先检查后创建"的竞态
$stream = [IO.File]::Open(
  $lockPath,
  [IO.FileMode]::CreateNew,
  [IO.FileAccess]::ReadWrite,
  [IO.FileShare]::None
)
```

租约至少包含：`runId`、`taskId`、`agent`、`worktree`、`branch`、`paths`、`baseCommit`、`createdAt`、`expiresAt`、`pid/sessionId`。只由父 Agent 续租/释放；回收前确认进程已退出且超过 TTL。mtime 只作额外警告。

租约 key 必须使用仓库相对路径，例如 repo:software/src、repo:software/template.html、repo:shared/merge.js、contract:sync-state-schema、d1:migration、deploy:production；修改前端源时必须同时持有 repo:software/src 和 repo:software/template.html 的同一 owner 租约；不能使用 worktree 的绝对路径，否则不同 worktree 会把同一文件误判成不同资源。租约还要记录 fencingToken、heartbeatAt、parentPid、resourceType 和 generation；过期租约不能让旧进程继续提交。

每个任务实例化：

```powershell
git worktree add C:\my_project\单词-worktrees\<task-id> -b ai/<task-id> <base-commit>
```

一个 worktree 只允许一个写 Agent；每个递归写分支必须由父层分配自己的 worktree 和 branch，不能共享或自行覆盖兄弟 worktree。基线必须唯一、可追溯，不能基于来历不明的脏目录。

资源生命周期：

- 只有写 Agent 需要 worktree、branch 和文件租约；只读 Verifier 使用固定 SHA 的只读 checkout，不占写租约。
- Root 在启动子 Agent 前创建 run 目录、预占全局 active slot、创建写 worktree/租约和子节点事件文件；子 Agent 只读验证，不得自行补建。
- 子 Agent 状态写各自的 `<coordinationRoot>/runs/<run-id>/events.jsonl`；Root 汇总为任务账本，禁止多个节点同时改同一个 `task.json`。
- 任务完成或失败后由 Root 释放租约；worktree 清理必须在证据保存和合并复核之后。

进入递归 fan-out 前的硬前置：

1. 确认当前工作区所有改动的归属。
2. 把确认后的代码和 `docs/` 冻结为一个干净 baseline commit；未跟踪文档和未知改动不能作为 worktree 基线。
3. 创建 `dispatch-agent.ps1` wrapper 和结果 schema；wrapper 不存在时禁止递归写任务。
4. 先用"1 写 + 1 只读 + 独立 Verifier"做 dry run，验证无越权后先扩到 8 路，再按扩容梯子到 16/32。
5. 每个集成任务必须记录 `baseCommit`、`resultCommit`；合并时由 Root 串行 cherry-pick/rebase 到唯一 integration branch，冲突只能由 Root 或文件 owner 处理，合并后重新跑全量回归。

高并发 wave 规则：

- 每个 wave 先冻结 waveId、任务集、base SHA、活跃/写 slot 和合并队列；只启动满足依赖、没有路径交集和租约冲突的任务。
- 同一时间只有一个 integration branch 和一个 merge queue 项；accepted 任务必须 rebase/cherry-pick 到当前 integration SHA。
- 任意一个租约冲突、worktree 创建失败、越权修改、无法解决的合并冲突、同类测试失败、p95 退化超过 5%、或缺少 checkpoint，立即停止当前 wave，降一级并生成新 runId。
- 只有同一层级连续两轮 clean wave，才允许升到下一层；替换或重试 Agent 也占 max_total_spawned 和活跃 slot。
- 生成文件只由 Root 在集成后构建，worker 不得手工改生成物。

---

## 2. CLI 派发模板

所有子 Agent 必须使用统一 wrapper 进行递归；递归必须受 depth、spawn budget、skill 白名单和租约限制。禁止部署和远程 D1 migration。

Codex 实现者：

```powershell
codex -a never exec `
  --cd C:\my_project\单词-worktrees\<task-id> `
  --sandbox workspace-write `
  --json `
  --output-schema C:\my_project\单词-coordination\schemas\result.schema.json `
  --output-last-message C:\my_project\单词-coordination\runs\<run-id>\result.json `
  - < C:\my_project\单词-coordination\runs\<run-id>\prompt.md
```

Claude 实现者：

> 实测（2026-10-29）：本机 `claude` 是 `C:\Users\xrk\bin\claude`，225 MB 的可执行文件但**没有 `.exe` 后缀**。PowerShell 里 `claude ...`、`& claude ...`、管道调用都会报 `CantActivateDocumentInPipeline`；bash 下正常。所以下面的模板用 bash，或先把文件复制成 `claude.exe` 再用 PowerShell。

```bash
claude -p \
  --output-format json \
  --permission-mode acceptEdits \
  --allowedTools "Read,Edit,Write,Bash(pwsh -NoProfile -File C:/my_project/单词-coordination/dispatch-agent.ps1 *),Bash(python scripts/tools/run_tests.py),Bash(git status),Bash(git diff),Bash(git add *),Bash(git commit *)" \
  --json-schema C:/my_project/单词-coordination/schemas/result.schema.json \
  --add-dir C:/my_project/单词-coordination \
  --append-system-prompt "你是实现者；canSpawn/childQuota 由任务卡决定；只通过 dispatch-agent wrapper 递归；禁止部署或远程 D1 migration；只修改任务白名单。" \
  "执行 C:/my_project/单词-coordination/runs/<run-id>/prompt.md 指定的单一任务"
```

注意：

- `codex exec --json` 是 JSONL 事件流，不能把中间事件当最终结论；最终结果看 `--output-last-message` + schema。
- `claude --output-format json` 用于最终结果；`stream-json` 只用于实时日志。
- 非交互进程必须设置外部超时；超时后终止整个进程树并保留日志。
- 子 Agent 默认不给 `bypassPermissions` / `dangerously-bypass-approvals-and-sandbox`。
- 测试、构建、部署分别授权；子 Agent 不获得 `deploy.py`、`wrangler deploy` 或远程 D1 命令。

不把固定 token 数写进标准派单模板。只有用户明确要求、运行时报告确认有效窗口，且 wrapper 已记录配置来源时，才允许显式设置压缩阈值；否则一律使用 Claude 默认配置和实际窗口 checkpoint。

后台启动必须隐藏窗口、重定向输出并记录 PID；不能把交互式终端留在后台：

```powershell
$proc = Start-Process `
  -FilePath (Get-Command codex.cmd).Source `
  -ArgumentList @('exec','--json','-C',$worktree,$prompt) `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr `
  -PassThru
$proc.Id | Set-Content -LiteralPath $pidFile
```

父 Agent 用进程 PID、心跳文件、日志尾部和 `git diff --stat` 监督；子 Agent 不通过反复"问一句"推进。交互式权限、登录提示和等待输入视为失败，不做无人值守重试。

> 核对记录（2026-10-29）：`claude agents` 子命令存在，但只支持 `-h` 和 `--setting-sources`，**没有 `--json`**。不要照这个选项写监督脚本。

---

## 3. 联调与验收闭环

```text
父 Agent 派单并加锁
  -> 子 Agent 回执（runId、worktree、base SHA、允许路径）
  -> 子 Agent 实现并记录命令/退出码/日志
  -> 子 Agent 提交固定 SHA + handoff
  -> 独立 Verifier 在该 SHA 上重跑验收
  -> Architect Reviewer 只读审查
  -> 父 Agent 检查 diff 白名单并决定 accepted
  -> 父 Agent 串行集成
  -> 合并后全量回归
  -> 只有 Parent 可进入部署闸门
```

验收必须幂等且可复核：

- 所有验收命令非交互执行，必须记录原始 stdout/stderr、退出码、cwd、耗时。
- 通过条件必须包含命令退出码、明确断言、commit SHA 和必要产物哈希。
- 不缓存测试结论；父 Agent 必须独立复跑至少一次全量验收。
- 同一 run ID 的证据不可覆盖；失败任务保留 worktree 和日志。
- 失败最多自动重试 2 次；第 3 次升级给父 Agent。
- 子 Agent 自述、聊天摘要、IDE 绿色标记都不算验收证据。

固定结果 schema 至少包含：

```json
{
  "runId": "...",
  "parentRunId": "...",
  "taskId": "...",
  "depth": 1,
  "status": "submitted",
  "baseCommit": "...",
  "resultCommit": "...",
  "changedFiles": [],
  "skills": ["superpowers:subagent-driven-development"],
  "commands": [{"cmd": "...", "exitCode": 0, "log": "..."}],
  "protectedBehaviors": [],
  "context": {"window": "...", "used": "unknown", "checkpoint": "..."},
  "risks": [],
  "rollback": "..."
}
```

### 日志目录

```text
<coordination>/runs/<run-id>/
  task.json
  prompt.md
  stdout.jsonl
  stderr.log
  result.json
  commands.csv
  artifacts/
  review.md
  verification.json
```

`commands.csv` 至少记录：`timestamp, taskId, command, cwd, exitCode, durationMs, stdoutPath, stderrPath, commitBefore, commitAfter`。

---

## 4. 合并与部署互斥

- 只允许父 Agent 进入主工作区合并，合并前检查 `git diff --name-only` 与 `git diff --check`。
- 合并后必须重新跑完整测试，不能继承子 Agent 的测试结果。
- 生产部署和 D1 migration 使用独立排他租约；同一时间只允许一个。
- 部署前由 `deploy.py` 检查最近 10 分钟提交和上次成功发布标记；默认拒绝，不能靠口头判断绕过。
- 部署失败不自动重试；先确认线上版本、回滚点和实际部署产物。

### 父 Agent 合并前验收

- 固定审查 `resultCommit`，不是会变化的 working tree。
- `git diff --name-only <base>..<result>` 必须完全落在任务白名单内。
- 实现者与验收者不能是同一个 Agent 会话；至少一方只读。
- 原始命令、退出码、日志路径、diff stat、测试计数、回滚方法齐全。
- 业务不变量测试通过：40 条启动内联、200 词第一章、上次词恢复、账号作用域隔离。
- 至少一个恢复场景覆盖"目标词不在前 40 条"：保存第 58/80 个词时先进入恢复态，补齐后落回原词，不能先保存第一词。
- 本轮涉及热路径时必须有性能前后数据；超过 5% 退化即拒绝合并。
- 合并后父 Agent 在当前主线重新跑全量回归；不能只引用子 Agent 的结果。

---

## 5. 多 Agent 协作验收

- 每个写任务都有唯一 root/parent `runId`、`taskId`、depth、worktree、branch、base SHA、允许路径和租约。
- 递归子 Agent 均登记 parentRunId、depth、spawn budget、allowedSkills 和 `canSpawn`；没有越界或无限递归。
- 并发在 max_depth=4、默认 max_active_agents=16（硬上限 32）、默认 max_write_agents=8（硬上限 16）的预算内；路径不相交且有父层批准。
- 使用了匹配的 skill：计划/并行派发/worktree/审查/完成前验证至少各到位，且 skill 输出没有被当成测试证据。
- 实现、验收、合并、部署四种权限没有混在同一个 Agent 会话中。
- 验收在固定 commit SHA 上独立复跑，原始日志和退出码可追溯。
- 每完成一个子任务或达到上下文软阈值时都有 checkpoint。
- 达到硬阈值后已重启新会话，并重新注入任务不变量。
- 所有业务不变量测试通过，尤其是上次学习位置恢复。
- 多 Agent 文档没有产生第二套 Phase、第二套 merge 或第二套章节补全实现。
