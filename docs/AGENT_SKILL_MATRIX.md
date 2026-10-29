# Claude Code 技能路由与递归子 Agent 矩阵

> 日期：2026-10-29
> 文档性质：工程控制面参考，不是第二份执行计划。唯一任务顺序由 [PHASES.md](./PHASES.md) 决定。
> 目的：让父 Agent 在合适的任务上主动、递归、并行地调用 Claude Code 的 skills、agents、teams 和 CLI worker，同时避免上下文污染、文件覆盖和假验收。

## 0. 本机扫描结果

2026-10-29 对当前 Claude Code 配置做只读扫描：

- 扫描到约 147 个 `SKILL.md`（包含嵌套缓存/备份，不能当作当前生效技能数）。当前生效组件以 `claude plugin details` 为准：`superpowers` 15 skills、`oh-my-claudecode` 69 skills/19 agents、`context-mode` 8 skills。
- `C:\Users\xrk\.agents\skills`：9 个用户级 skill。
- `C:\Users\xrk\.claude\plugins`：已启用 `superpowers`、`context-mode`、`oh-my-claudecode`、`claude-coding`、`claude-thinking`、`code-review`、`code-simplifier`、`context7`、`ralph-loop`、`caveman` 等。
- Claude 设置中包含 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 和 `CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4.1-flash[1M]`，并启用了 OMC 多 Agent 编排层。当前设置还残留一个用户级 context cap 覆盖；它不是 Claude 默认值，文档不把它当项目标准。
- 因此运行时必须按“当前生效窗口”计算阈值，不能只按模型宣传窗口或固定 token 数计算。

运行时状态提醒：2026-10-29 的 claude plugin list 显示多个 marketplace 插件为 failed to load cache-miss，只能确认 superpowers@skills-dir 等 skills-directory 插件已加载。矩阵里的 OMC、claude-coding、claude-thinking、code-review、context-mode 等是候选路由，必须先运行 claude plugin list 并确认 loaded，否则不得派单。

### 0.1 每次开工的全量技能发现

父 Agent 不能凭记忆猜 skill。每个 root task 开始时执行一次只读发现，把结果写到协调目录，不让完整清单进入主上下文：

```powershell
Get-ChildItem 'C:\Users\xrk\.claude\skills' -Recurse -Filter SKILL.md |
  Select-String '^(name|description):' |
  Set-Content -LiteralPath $skillIndex -Encoding utf8

Get-Content 'C:\Users\xrk\.claude\settings.json' -Raw |
  ConvertFrom-Json |
  Select-Object -ExpandProperty enabledPlugins
```

发现规则：

1. 先运行 claude plugin list 和 claude plugin details <plugin-id>，只把 loaded 的组件放进候选；再按 name/description 筛选 1–3 个 skill，必要时读完整 SKILL.md。
2. `/skills` 或 `find-skills` 用于真实运行环境中的名称确认，不能把缓存目录里未启用的插件当成已启用能力。
3. 遵守用户级 `CLAUDE.md` 的既有技能映射；不要把缓存中的旧版本或 `_backup_*` 目录当成当前能力。
4. 运行日志只记录选中的 skill 名称、路径、版本/日期和输出摘要，不把 147 份 skill 正文拼进上下文。

## 1. 递归 Agent 树与预算

默认允许递归调用，但必须是有界的：

```text
Depth 0  Root Orchestrator
          ├─ Depth 1  Domain Lead / Planner / Implementer
          │            ├─ Depth 2  Specialist / Implementer / Reviewer
          │            │            └─ Depth 3  Read-only Verifier / Research
          │            └─ Depth 2  Read-only Verifier
          └─ Depth 1  Independent Domain Lead
```

默认预算：

| 预算项 | 默认值 | 说明 |
|---|---:|---|
| `max_depth` | 4 | 根节点深度为 0；只读探索可按任务配置到 5 |
| `write_depth_limit` | 3 | 写代码的子 Agent 最多到深度 3；更深的节点默认只读 |
| `max_children_per_agent` | 6 | 单个节点每轮最多派 6 个直接子节点 |
| `max_active_agents` | 16（硬上限 32） | 默认 16；独立只读或 OMC team 任务经 Root 批准可到 32 |
| `max_write_agents` | 8（硬上限 16） | 默认 8 个写 Agent；每个路径必须不相交，排他资源仍单写 |
| `max_read_only_agents` | 24 | 只读调查、审查、验证和文档 Agent；不占写租约 |
| `max_total_spawned` | 64 | 单个 root task 生命周期内总派生上限 |
| `max_children_per_root` | 12 | 防止根节点一次性 fan-out 爆炸 |

扩容梯子：

| 级别 | 活跃 Agent | 写 Agent | 使用条件 |
|---|---:|---:|---|
| T0 单任务 | 1 | 1 | 强依赖、共享契约、热路径排他文件 |
| T1 小并行（默认上限） | 4–6 | 2–4 | worktree 和路径已验证隔离 |
| T2 大并行 | 8–12 | 4–8 | 每个路径独立、Root 有完整任务账本，且用户明确批准 |
| T3 大并行 | 16–24 | 8–16 | 多模块、多测试域，允许更长合并窗口 |
| T4 极限并行 | 25–32 | 最多 16 | 只读为主或用户明确批准；必须拆成多个独立 team |

单个 oh-my-claudecode:team 约支持 1–20 个 teammate；超过 20 必须拆成多个独立 team/CLI 进程，并由 Root 维护唯一的全局任务账本和串行 integration 队列。32 是 wrapper 全局上限，不是单个 team 的上限。

全局预算口径：activeAgents = Root + 所有后代 + 所有 OMC team lead/teammate + 所有 CLI worker + 正在等待验收的进程；32 包含 Root。平台原生并发/嵌套限制未确认时，canSpawn=true 按 false 处理，达到平台上限时必须降级或拆成独立 CLI/team，不能绕过全局 slot。
写入者动态授权（数字是上限，不是目标）：

| 门禁 | 写 Agent 上限 | 必须满足 |
|---|---:|---|
| G0 基线 | 1 | docs 和当前源码冻结为干净 commit |
| G1 控制面 | 2 | wrapper、schema、租约、全局 slot 可运行 |
| G2 dry run | 4 | 1 写 + 1 读 + 独立 Verifier 验收通过 |
| G3 模块化 | 8 | template/worker/shared 契约至少完成边界拆分 |
| G4 极限 | 16 | 用户明确批准，且 16 条路径完全不相交、合并队列为空 |

未达到对应门禁时，即使配置写了 16，也必须在 wrapper 启动前拒绝预占写 slot。


每个子 Agent 必须继承并记录：

```text
rootRunId
parentRunId
taskId
depth
spawnBudgetRemaining
canSpawn
allowedSkills
allowedPaths
worktree / branch
lease
contextWindow / checkpointThreshold
```

递归规则：

1. 父 Agent 必须根据任务独立性主动分解。默认串行；只有存在 2 个以上真正互不依赖的域时才并行，从 2–4 个起步，确认路径不相交后再按扩容梯子升。
2. 子 Agent 可以在 `canSpawn=true` 且预算未耗尽时继续递归；每派一层 `depth + 1`，`spawnBudgetRemaining - 1`。
3. 子 Agent 不得绕开 wrapper 直接运行 `claude`/`codex` 子进程；所有派生都必须登记到同一任务账本。
4. 写 Agent 只能拿到自己的 worktree 和文件租约；`depth <= write_depth_limit` 才可写，超过后只读。只读 Verifier 使用固定 SHA 的只读 checkout，不占写租约。
5. 依赖关系强、共享契约、同一前端写域（`software/src/` + 生成 `software/template.html`）、数据库迁移和生产部署禁止并行写。
6. 递归收益不足、路径开始冲突、上下文接近硬阈值或预算耗尽时，父 Agent 必须收拢分支，不继续多开。

## 2. 首选技能路由

> 本表区分两类，不能混用：**agent** 用 `Agent` 工具的 `subagent_type` 派发（OMC agent 全名带 `oh-my-claudecode:` 前缀，完整目录见 `omc-reference`）；**skill** 用 `Skill` 工具调用。用 `Skill` 去调一个 agent 名会直接报找不到。
>
> 两者都已于 2026-10-29 对照 `omc-reference` 的 Agent Catalog 和当前会话可用 skill 列表核对过。插件升级后名字若有变化，先用 `find-skills` 重新确认，不要凭记忆写。

| 任务 | 首选 Skill / Agent | 使用时机 | 产出 |
|---|---|---|---|
| 按计划逐任务执行 | `superpowers:subagent-driven-development` | 已有计划且任务可独立 | 每任务新 implementer + 任务审查 |
| 多个互不依赖的子问题 | `superpowers:dispatching-parallel-agents` | 独立 bug、文件、模块、调查 | 并行结果和统一整合 |
| 顺序执行计划 | `superpowers:executing-plans` | 不适合子 Agent 或强依赖任务 | 按 checkpoint 顺序执行 |
| 编写/修改计划 | `superpowers:writing-plans` | 已有 spec，需要拆任务 | 可执行计划和测试步骤 |
| 隔离工作区 | `superpowers:using-git-worktrees` | 任何写任务开工前 | worktree 和隔离分支 |
| 代码审查 | `superpowers:requesting-code-review`、`superpowers:receiving-code-review`、`github-github-code-review` | 每任务后、合并前 | 固定 SHA 审查和修复闭环 |
| 完成前证据 | agent `oh-my-claudecode:verifier` + skill `oh-my-claudecode:verify` + `superpowers:verification-before-completion` | 声称完成、提交、部署前 | 独立复跑、退出码、测试计数 |
| TDD | `superpowers:test-driven-development` | 功能、回归、修复 | 红-绿-重构证据 |
| 方案探索 | `superpowers:brainstorming` | 需求/架构歧义，先比较方案 | 方案候选和风险 |
| 根因排查 | `superpowers:systematic-debugging`、`diagnose` | 测试失败、性能异常 | 根因和最小修复 |
| 架构调查 | agent `oh-my-claudecode:architect`、agent `claude-coding:architecture-auditor` | 固定 SHA，只读扫描模块和边界 | 模块风险、错误 seam、重复实现 |
| 架构设计/监督 | agent `oh-my-claudecode:architect`、`engineering-software-architect`、`ai-agents-architect`、`docs-architect` | 目标架构、边界、ADR，且必须独立于实现 | 方案、权衡、决策记录、审查结论 |
| 架构异味/最小改动 | agent `oh-my-claudecode:critic`、`brooks-lint`、`engineering-minimal-change-engineer`、`karpathy-guidelines` | 重构前、固定 SHA 评审时 | 过度设计、耦合、范围膨胀和最小修复建议 |
| 文档可执行性 | `docs-architect` | 修改计划/ADR/交接文档后 | 新会话能否只读文档执行 |
| Git/分支协同 | `engineering-git-workflow-master`、`git-advanced-workflows` | 多 worktree、合并、冲突 | 可审计分支和合并记录 |
| Python 性能 | `python-pro`、`python-patterns`、`python-performance-optimization`、`python-testing-patterns` | Python 流水线和测试 | 优化和测试证据 |
| 上下文管理 | `context-mode`、`ctx-stats`、`ctx-doctor`、`ctx-search`、`development-context-optimization` | 长会话、上下文膨胀 | usage、索引、检索和 checkpoint；`ctx-purge` 只能在父 Agent 明确确认后用于清理 |
| 技能发现/扩展 | `find-skills`、`skill-creator`、`writing-skills` | 没有匹配 skill 或要新增能力 | 选择或创建并校验 skill |
| 原生 team / 跨 CLI | `oh-my-claudecode:team`，可用 `N:codex` 派 Codex worker | 多 Agent 共享任务清单、需要团队协作 | 任务依赖、成员、完成闭环 |
| 系统健康 | `claude-monitor`、`omc-doctor`、`claude-settings-audit` | 卡顿、权限、插件异常 | 诊断和权限建议 |
| 持续执行循环 | `oh-my-claudecode:autopilot`、`oh-my-claudecode:ralph` | 已批准的长任务且需要重试/收尾 | 持久循环，不得跳过验收 |
| 独立 QA/验收 | agent `oh-my-claudecode:qa-tester`、agent `oh-my-claudecode:code-reviewer`、skill `code-review`、`oh-my-claudecode:verify`、`oh-my-claudecode:ultraqa` | 代码审查后再做 QA | 独立 QA 证据 |
| 记忆/经验 | `hmem-subagent`、`hmem-dispatch`、`hmem-context` | hmem MCP 可用且有跨会话记忆 | 记忆上下文，不替代测试 |

### 2.1 架构监督链

架构相关任务必须至少形成“架构提案者 → 独立架构审查者 → 验证者”三节点：

```text
Root (depth 0)
  -> Architecture Lead (depth 1, read-only)
       -> engineering-software-architect / ai-agents-architect
       -> docs-architect（需要 ADR/文档时）
  -> Implementer (depth 1 or 2, write，独立 worktree)
  -> Architecture Reviewer (depth 2, read-only)
       -> brooks-lint / engineering-minimal-change-engineer / karpathy-guidelines
  -> Verifier (depth 2 or 3, read-only)
       -> agent oh-my-claudecode:verifier / oh-my-claudecode:code-reviewer + verification-before-completion
```

要求：

- 架构审查者不能是实现者；审查固定 SHA，不读会变化的 working tree。
- `engineering-software-architect` 负责边界、权衡和 ADR；`ai-agents-architect` 负责多 Agent 控制面、工具和失败模式；不能混成“让实现 Agent 自己设计自己”。
- 架构审查至少要给出：是否越权、是否重复实现、依赖方向是否错误、热路径是否变慢、抽象是否过度、何时撤回。
- `docs-architect` 只在需要更新 ADR/接口/架构文档时调用，不能让文档更新替代测试证据。
- 运行中的权限审计使用 `claude-settings-audit`，健康检查使用 `claude-monitor`/`omc-doctor`；它们不是业务验证。

### 2.2 OMC 与 Superpowers 的选择

- 需要“共享任务清单 + 原生 Claude teams + 任务依赖”：用 `oh-my-claudecode:team`。该 skill 支持约 1–20 个 teammate，适合较多只读并行和分阶段执行。
- 需要“跨 Codex CLI worker”：用 `oh-my-claudecode:team N:codex "..."`；需要 tmux 面板级的多进程并行时用 `oh-my-claudecode:omc-teams`（本机已安装；与 `team` 分工不同——`team` 走原生 tasks 共享清单，`omc-teams` 走 tmux 面板）。
- 需要“每任务 fresh implementer + 任务审查”：用 `superpowers:subagent-driven-development`。
- 需要“多个独立故障/文件同时调查”：用 `superpowers:dispatching-parallel-agents`。
- 需要“大输出索引、检索和会话恢复”：用 `context-mode`/`ctx-*`；它不是 compact/autocompact 本身，压缩后仍要执行 checkpoint 重新注入。

可直接使用的编排命令：

```text
/oh-my-claudecode:team 6:executor "拆分并执行本次独立任务，使用共享任务清单和固定 SHA 验收"
/oh-my-claudecode:team 4:codex "并行审查架构、测试、恢复逻辑和性能风险"
/oh-my-claudecode:team 2:codex "并行调查三个互不依赖的问题域"
```

使用前提：`team` 和 `omc-teams` 的真实可用性以 Claude Code 当前插件和能力清单为准。`omc-teams` 依赖 tmux 面板，tmux 不可用时不要路由到它；两者都不能当作普通 Windows 后台进程启动器。

### 2.3 权限与安全提醒

本机 Claude 全局配置存在 `permissions.defaultMode=bypassPermissions`。这不能成为子 Agent 的默认权限：

- 实现者使用 `--permission-mode acceptEdits`，且 `--allowedTools` 只列任务需要的读写/测试命令。
- 只读 Verifier/Architect 使用只读/plan 权限，不授予 Edit/Write。
- 任何子 Agent 都不得获得 `deploy.py`、`wrangler deploy`、远程 D1 migration 或 `git push`。
- 不把 `ANTHROPIC_AUTH_TOKEN`、session token、日志中的凭据传给子 Agent。
- 新项目第一次并行前用 `claude-settings-audit` 检查权限；发现过宽 allow 规则时先收窄，再派工。

## 2.4 OMC 专项 Agent 路由

当前 OMC 还提供 19 个专项 Agent；父 Agent 应按任务选择，不要让同一个 Agent 包办：

| Agent | 适用任务 |
|---|---|
| planner | 需求拆解、阶段计划、依赖和验收标准 |
| executor | 已隔离 worktree 内的实现 |
| architect | 只读架构调查和边界/权衡 |
| critic | 固定 SHA 的设计异味和风险审查 |
| code-reviewer | 固定 SHA 代码审查 |
| verifier | 独立复跑、证据核验、完成前门禁 |
| qa-tester | 端到端、浏览器、回归和用户路径验收 |
| test-engineer | 测试设计、红绿回归、覆盖缺口 |
| debugger | 失败复现、日志和根因定位 |
| tracer | 跨文件调用链、性能和请求追踪 |
| explore | 只读代码库探索和候选定位 |
| analyst | 数据分析、指标和证据归纳 |
| document-specialist | API、ADR 和交接文档核对 |
| security-reviewer | 权限、输入、session、限流和泄露审查 |
| git-master | 分支、冲突、rebase/cherry-pick 和提交整理 |
| code-simplifier | 在保持行为前提下的最小简化 |
| scientist | 对照实验、性能基准和可重复测量 |
| designer | UI/交互方案和视觉一致性 |
| writer | 发布说明、用户文档和最终报告 |

使用规则：

- OMC architect、critic、verifier、code-reviewer 默认只读，不得改代码。
- executor 只在任务 worktree 内写；写完必须交给 code-reviewer/verifier，不能自己验收。
- qa-tester 只负责独立验收；测试失败时交回实现者或 debugger。
- git-master 只能由 Root 或经 Root 授权处理集成冲突。
- 同一任务不要把 planner、executor、verifier 合并在同一会话里，避免上下文污染和自审自过。

### 2.5 claude-coding 与其他已启用插件

这些是插件组件，不等同于用户级 skill；使用前先用 claude plugin details 确认 runtime 版本和组件。

| 组件 | 用途 | 约束 |
|---|---|---|
| claude-coding:architecture-auditor | 架构边界和坏 seam 审查 | 只读，固定 SHA |
| claude-coding:code-auditor | 代码质量、重复实现和风险审查 | 只读，固定 SHA |
| claude-coding:performance-auditor | 热路径、测量和性能回归审查 | 必须有前后数据 |
| claude-coding:security-auditor | 权限、session、输入和泄露审查 | 只审计，不改权限 |
| claude-coding:test-engineer | 测试设计和回归覆盖 | 先红后绿 |
| claude-thinking:council | 多方案比较、架构权衡 | 只输出方案，不直接写 |
| code-review | 独立代码审查 | 审查固定 commit |
| code-simplifier | 行为不变的最小简化 | 不扩大范围 |
| ralph-loop | 长任务持续执行 | 必须叠加 Verifier 和预算 |
| skill-creator | 创建缺失 skill | 新 skill 不替代测试 |

用户级 skill（例如 engineering-software-architect、docs-architect、brooks-lint、python-*）与插件组件分开记录；缓存目录中的重复/旧版本不能当作 active skill。

## 3. Skill 使用规范
## 3. Skill 使用规范

1. **不一次加载 147 个 skill**。只加载当前任务需要的 1–3 个，读 `SKILL.md` 的相关段落和引用文件。
2. 技能名以 Claude Code 当前显示的 slash name / plugin namespace 为准；插件名不可猜测，先运行 `/skills` 或读取 `SKILL.md` frontmatter。
3. 没有直接匹配时先用 `find-skills`；仍没有才用 `skill-creator` 创建，并用 `writing-skills` 校验。
4. 框架/API 不确定时用 `context7-auto-research` 或 `docs-architect`，不能凭记忆补 API。
5. `caveman`/`caveman-compress` 只用于明确要求压缩表达或省 token 的场景，不能为了省 token 删除验收事实。
6. Skill 的输出是建议或流程，不是测试证据；最终以命令、退出码、日志、commit SHA 和独立复跑为准。

## 4. 递归派单的标准流程

```text
Root 读取任务 -> 建立 rootRunId -> 计算有效 context 预算
  -> 用 find-skills/已知矩阵选择 skill 和角色
  -> 拆分独立域 -> 生成 task packet
  -> 需要并行：从 2–4 个起步，确认无路径冲突后再按扩容梯子升级；不要为了“多开”而多开
  -> 写 Agent 获得独立上下文包、worktree、租约和输出 schema；只读 Verifier 使用固定 SHA
  -> 子 Agent 可在预算内继续递归派只读或独立写任务
  -> 每个叶节点输出 evidence summary，不把整段会话回传
  -> 父 Agent 汇总冲突、合并、独立复跑
```

强制边界：

- 子 Agent 的上下文只包含它需要的任务包，不复制父会话全部历史。
- 每个子 Agent 都必须回传 `runId`、`parentRunId`、`taskId`、`depth`、`resultCommit`、命令日志、风险和未完成项。
- 任何 Agent 不得修改自己的验收结论；独立验收用 agent `oh-my-claudecode:verifier` / `oh-my-claudecode:code-reviewer`（或 skill `code-review`），`verification-before-completion` 只是证据门禁，不等于验收 Agent。
- `using-git-worktrees` 只负责隔离工作区，不是文件锁；租约和固定 SHA 仍然是并发安全的前提。
- 递归派发失败时保留失败节点和日志，父 Agent 负责收拢，不允许无限重试。

## 5. 上下文阈值（使用 Claude 默认）

默认策略：**不替 Claude 强制设置上下文窗口，不把任何用户级 context cap 写进项目标准。** 由 Claude Code 使用它自己解析后的默认窗口；父 Agent 只读取运行时报告并监督阈值。

```text
effectiveWindow = runtime-reported effective context window
softThreshold   = floor(effectiveWindow / 3)
hardThreshold   = floor(effectiveWindow * 0.45)
```

规则：

- Claude 默认配置下不要注入 `CLAUDE_CODE_MAX_CONTEXT_TOKENS`。如果用户级 settings 里已有覆盖，父 Agent 必须把它视为“用户自定义覆盖”，记录后按实际生效窗口计算，不能把它冒充 Claude 默认值。
- 本机若存在用户级 `CLAUDE_CODE_MAX_CONTEXT_TOKENS` 覆盖，它只是用户配置，不是本方案要求。用户要求使用 Claude 默认时，应由用户配置层清理这个覆盖，文档和 wrapper 不得偷偷写回。
- Claude 默认不传 --autocompact，完全使用自身默认行为；不要预置固定 token 数值。只有用户明确要求、运行时报告确认有效窗口并记录配置来源时，才允许显式设置阈值。
- 不要硬编码固定 token 数；以运行时报告的有效窗口为准。`--autocompact` 的可用范围由当前 CLI 决定，参数不可用时使用 `auto` 或由 wrapper 在软阈值时先 checkpoint，再按 actual usage 决定是否硬停止。
- Codex 同样先读取运行时实际配置；默认不覆盖 context/compact 配置。只有用户明确选择并确认实际窗口时才设置固定阈值。
- 拿不到 `contextUsed` 时写 `unknown`，按“每个子任务完成即 checkpoint”执行；禁止伪造百分比。

阈值行为：

| 级别 | 触发 | 动作 |
|---|---|---|
| 软阈值 | 实际有效窗口约 1/3 | 停止扩展，生成 checkpoint，收拢子 Agent |
| 硬阈值 | 实际有效窗口约 45% | 停止当前会话；从 checkpoint 新开，不在旧上下文里硬撑 |
| 任务边界 | 每个可验收子任务 | 无论 token 数都生成 handoff，避免历史污染 |
## 6. 可直接给父 Agent 的派单提示词

```text
你是 Root Orchestrator，不是单线程执行者。

先读取：
- docs/README.md（索引与读法）
- docs/PHASES.md（唯一任务源）
- docs/AI_EXECUTION_PLAN.md 的 §2 性能目标和 §7 不变量
- docs/ARCHITECTURE_REFERENCE.md（架构约束，按需查对应章节）
- docs/AGENT_PROTOCOL.md（调度协议全文）
- docs/AGENT_SKILL_MATRIX.md（skill 路由）

要求：
1. 把任务拆成独立域。默认串行执行；只有存在 2 个以上真正互不依赖的域时才并行，从 2–4 个起步，路径必须不相交。协调成本高于合并收益时退回单 Agent（对应 AGENT_PROTOCOL.md 0.3 第 10 条）。
2. 使用指定 skill/agent：计划执行用 superpowers:subagent-driven-development；独立 fan-out 用 superpowers:dispatching-parallel-agents；写任务先用 superpowers:using-git-worktrees；独立审查用 agent oh-my-claudecode:code-reviewer / oh-my-claudecode:verifier + superpowers:verification-before-completion。
3. 允许在预算内递归派生子 Agent，但必须登记 parentRunId、depth、spawn budget 和文件租约；不得绕开 wrapper。
4. 默认 max_depth=4、max_active_agents=16、max_write_agents=8（硬上限 16）；超过预算先收拢，不继续扩展。
5. 每个分支只返回结构化摘要和证据，不把全历史传回父 Agent。
6. 有效上下文达到 1/3 时 checkpoint，达到 45% 时停止当前分支；压缩后重新注入任务不变量。
7. 任何实现者不能自己标记 accepted；父 Agent 必须独立复跑测试并检查固定 SHA。
8. 没有原始命令、退出码、日志和测试证据，不得声称完成。
```
