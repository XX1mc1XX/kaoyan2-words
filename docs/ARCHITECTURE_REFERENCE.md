# 单词项目架构参考 v2：高性能、可扩展、分层解耦

> 审计日期：2026-10-29。  
> 定位：基于当前工作区的建议方案，不代表重构已完成。  
> 本版修订重点：架构和设计模式必须由性能、可扩展性、可维护性驱动，禁止为了“看起来商业”而堆叠模式、框架和分层。
> 任务顺序：[PHASES.md](./PHASES.md)（唯一任务源）；方向与约束：[AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md)。本文只定义架构约束和技术取舍，不另排执行任务。

## 0. 方案边界

本方案追求四个结果：

1. **高性能**：首屏、滑动、章节切换、离线读取、音频和同步不能被工程化拖慢。
2. **可扩展**：新增牌组、学习算法、音频源、存储方式时，不需要改遍全项目。
3. **分层解耦**：业务规则不依赖 DOM、浏览器存储、HTTP 或 D1。
4. **低复杂度**：当前只有约 9,400 行可维护源码，不为小项目制造微服务、全量 DDD、事件溯源或插件平台。

明确不做：

- 不为了使用而使用 23 种设计模式。
- 不为了“架构完整”拆出大量空包、空接口和转发方法。
- 不引入微服务、消息队列、CQRS、Event Sourcing、全量 DDD。
- 不只为了商业化替换现有语言、数据库和部署平台。
- 不一次性重写当前已验证的离线优先和缓存链路。

## 1. 架构由需求驱动

| 优先级 | 架构驱动 | 可验证目标 |
|---:|---|---|
| P0 | 交互性能 | 首卡片、滑动、章节切换无可见退化；ASI 稳定 |
| P0 | 离线可靠 | 页面、词库、进度、音频缓存可升级且不互相错位 |
| P0 | 数据正确性 | 本地/云端合并唯一实现；冲突可解释；迁移可回滚 |
| P1 | 可扩展性 | 新牌组、新排序策略、新音频源只改限定模块 |
| P1 | 可维护性 | 单文件职责清晰；依赖可检查；AI 可按边界修改 |
| P1 | 安全性 | 会话、限流、输入校验、错误边界可测试 |
| P2 | 交付可复现 | 锁文件、双次构建同哈希、CI 门禁 |
| P2 | 运营能力 | 日志、指标、备份、发布和回滚可执行 |

### 1.1 最小充分原则

只有在满足以下任一条件时才新增抽象：

1. 已经存在或明确即将存在第二种实现。
2. 是外部边界：浏览器存储、网络、音频、D1、文件系统。
3. 需要隔离不确定性，例如时间、随机数、外部服务。
4. 提炼后能显著减少重复，或能建立真正的测试缝。
5. 有性能测量证明抽象不会进入关键热路径。

不满足条件的抽象一律延后。**“以后可能会用”不是新增接口的理由。**

## 2. 架构选型

采用：

- **模块化单体 Modular Monolith**
- **垂直功能切片 Vertical Feature Slice**
- **轻量六边形边界 Hexagonal-lite**
- **Local-first / Offline-first**
- **静态内容与动态用户数据分离**
- **Edge-first 但保持无状态**

不采用：

- 微服务：当前规模没有独立部署、扩容和团队边界收益。
- 全量 DDD：没有复杂聚合和领域专家协作需求，成本和收益不匹配。
- Event Sourcing：用户进度需要简单、可恢复、可合并，事件溯源会增加迁移和回放风险。
- 全量响应式框架：滑动和学习卡片是性能热路径，不应被通用响应式运行时拖慢。
- 通用依赖注入容器：手工 composition root 足够，热路径不能依赖反射或容器查找。

### 2.1 总体依赖方向

```text
                         composition root / bootstrap
                          /                      \
                         v                        v
Web UI / Worker HTTP -> Application Use Cases -> Domain
        |                       |
        |                       +-> Ports（仅真实边界）
        |                                  ^
        +-> Platform Adapters -------------+
            storage / http / audio / D1

Shared Contracts: 只放跨端 DTO、错误码、schema、merge 纯函数
Content Pipeline: 源数据 -> 校验 -> 规范化 -> 发布物
```

严格规则：

- Domain 不导入 DOM、fetch、localStorage、IndexedDB、D1、Cloudflare 类型。
- Application 只依赖 Domain、Ports 和 Shared Contracts。
- Platform Adapter 实现 Port，不包含业务规则。
- UI 只调用 Application 用例，不直接拼 SQL、同步协议或 merge 规则。
- Worker 路由只做协议适配，不把业务逻辑和 SQL 写在一起。
- 只有 composition root 知道“当前使用哪个 Adapter”。

### 2.2 分层不是四个全仓库大目录

不采用：

```text
domain/   application/   infrastructure/   presentation/
```

然后在每个目录里再按功能拆一遍，最后同一功能的文件相距很远。

采用 **feature-first，层在 feature 内可见**：

```text
features/study/
  study.domain.ts
  study.usecases.ts
  study.ports.ts
  study.view.ts
  study.test.ts
```

- 小功能不需要 `ports.ts`；只有一个 Adapter 时不建 Port。
- 有明确边界或测试替身需求时才建 Port。
- 每个 feature 暴露一个窄 public API，不暴露内部文件。
- 禁止跨 feature 深层导入；跨 feature 由 composition root 或 typed application event 编排。

## 3. 目标目录

```text
单词/
├─ apps/
│  ├─ web/
│  │  ├─ index.html                 # 页面壳，目标 <= 250 行
│  │  ├─ src/
│  │  │  ├─ main.ts
│  │  │  ├─ app/
│  │  │  │  ├─ bootstrap.ts         # 唯一组装点
│  │  │  │  ├─ app-shell.ts
│  │  │  │  └─ app-events.ts        # 少量 typed event
│  │  │  ├─ features/
│  │  │  │  ├─ deck/
│  │  │  │  ├─ study/
│  │  │  │  ├─ sync/
│  │  │  │  ├─ auth/
│  │  │  │  ├─ audio/
│  │  │  │  ├─ offline/
│  │  │  │  ├─ stats/
│  │  │  │  └─ settings/
│  │  │  ├─ platform/
│  │  │  │  ├─ http.ts
│  │  │  │  ├─ storage.ts
│  │  │  │  ├─ media.ts
│  │  │  │  └─ cache.ts
│  │  │  ├─ ui/
│  │  │  │  ├─ dom.ts
│  │  │  │  └─ components/
│  │  │  └─ styles/
│  │  └─ public/
│  └─ worker/
│     └─ src/
│        ├─ index.ts
│        ├─ app.ts
│        ├─ http/
│        │  ├─ router.ts
│        │  └─ middleware.ts
│        ├─ features/
│        │  ├─ auth/
│        │  ├─ progress/
│        │  ├─ pair/
│        │  └─ audio/
│        └─ platform/
│           └─ d1.ts
├─ packages/
│  └─ shared/
│     └─ src/
│        ├─ contracts.ts
│        ├─ merge.ts                # 唯一合并实现
│        └─ schema.ts
├─ pipeline/
│  ├─ sources/
│  ├─ transforms/
│  ├─ validators/
│  ├─ publishers/
│  └─ cli.py
├─ content/
│  ├─ sources/                     # 人工源 CSV/TSV/JSONL
│  ├─ fixtures/
│  └─ generated/                   # 默认不提交
├─ tests/
│  ├─ integration/
│  ├─ e2e/
│  └─ perf/
├─ infra/
│  ├─ cloudflare/
│  └─ migrations/
├─ docs/
│  └─ adr/                         # 关键决策记录
├─ tools/
│  └─ experiments/                 # 有复用价值的实验脚本
├─ artifacts/                      # PDF、截图、构建输出，不进源码
├─ package.json
├─ pnpm-lock.yaml
├─ pyproject.toml
├─ uv.lock
├─ tsconfig.json
└─ AGENTS.md
```

### 3.1 为什么只有 `packages/shared`

当前真正跨 Web、Worker、Build 的只有：

- API/storage contracts。
- merge 纯函数。
- 必要的 schema。

不需要再把 `contracts`、`merge`、`deck-model` 各做成一个 package。**包是发布和依赖边界，不是目录装饰。**

### 3.2 文件限制

- 页面壳：不超过 250 行。
- 单个源码文件：目标不超过 300 行，硬上限 400 行。
- 单个函数：目标不超过 50 行。
- Worker route：不超过 150 行；handler 不超过 80 行。
- 单测试文件：不超过 300 行。
- 单个 CSS 文件：不超过 300 行。
- 超过硬上限必须有 ADR 或明确豁免，不允许“先塞进去再说”。

## 4. 当前审计证据

| 指标 | 当前值 | 影响 |
|---|---:|---|
| Git 跟踪文件 | 170 | 源、产物、历史文件混放 |
| archive 路径文件 | 113（约 66%） | 搜索与 AI 上下文噪音 |
| 可维护源码 | 约 9,400 行 | 规模适合渐进重构，不适合重写 |
| `software/template.html` | 4,007 行 | HTML、CSS、JS、状态、DOM、同步混合 |
| 其中脚本 | 约 3,483 行、174 个函数 | 单文件不可独立测试 |
| 其中 CSS | 277 行 | 样式与业务耦合 |
| `backend/worker.js` | 650 行 | 鉴权、限流、音频、同步、静态回退混用 |
| `handleApi` | 约 339 行 | 单函数承担整个 API 路由 |
| `scripts/make_html.py` | 483 行 | 数据、HTML、压缩、部署、Headers 混合 |
| `scripts/tools/run_tests.py` | 1,120 行 | 多类测试混在一个入口 |
| `index.html` gzip | 约 12.7 KB | 性能基线 |
| `app.*.js` gzip | 约 29 KB | 性能基线 |

### 4.1 必须保护的行为

- 网页壳最多内联 40 条词数据，来源是 `scripts/make_html.py` 的 `slim[:40]`；这不是首屏显示 40 个词。学习页一次只显示一张卡、一个当前词。
- 章节大小为 `CHAPTER_SIZE = 200`。
- 第一章补全依赖现有 `fillDeckInBackground`、`pendingSeek`、`chapterExpectedLength`。
- 禁止新增第二套章节补全逻辑。
- merge 只允许一个实现，前端和 Worker 构建时复用。
- 部署后必须用全新 Edge `--user-data-dir` 验证，不能受 Service Worker 旧缓存影响。

### 4.2 学习进度恢复是不变量

应用启动时不得无条件从第一个词开始。有有效进度时必须恢复到用户上次停下的位置：

1. 先确定账号作用域（游客或当前登录用户），防止串用其他账号进度。
2. 恢复上次使用的牌组。
3. 恢复该牌组的章节；当前实现使用 `conf.deckChapter[activeDeck]`，不能只依赖全局 `conf.chapter`。
4. 恢复该章节的顺序快照和当前位置；当前实现使用 `chapterData[deck:chapter]`、`pos` 和 `posWord`。
5. 优先用稳定的单词 key（`posWord`）定位，而不是只用会因筛选、掌握状态、洗牌而变化的数组下标。
6. 如果 `posWord` 已不在当前队列，按已保存的 `pos` 做边界夹取；仍不可用时才回落到章节起点。
7. 只有在全新用户、新牌组从未学习、或保存的所有位置都失效时，才允许显示第一个词。

必须覆盖的恢复场景：

- 刷新页面后回到同一个词。
- 关闭浏览器再打开后回到同一个词。
- 离线启动后回到同一个词。
- Service Worker 更新后进度不被重置。
- 切换牌组再切回来，各牌组分别恢复自己的章节和词。
- 登录、退出、切换账号时，只恢复各自作用域的进度，不能串号。
- 云端同步完成后，合并结果中的当前位置优先恢复，不能先闪回第一个词再跳。
- 章节通过后台分片补全时，保留 `pendingSeek` 原目标，不能因为启动时只有 40 条内联数据就改写为 0。
- 打乱顺序后重启，顺序和当前位置都要恢复；不能因为重新计算 shuffle 而改变恢复目标。

禁止：

- 启动代码直接调用 `loadChapter(0)` 覆盖已保存进度。
- 加载分片期间短暂渲染第一词后，再把用户位置“纠正”过去。
- 在重新排序、掌握词过滤或详情加载后无条件把 `idx` 设为 0。
- 用账号、游客和不同牌组共用一个未分作用域的进度 key。

当前已有的 `savePos()`、`resumePosition()`、`deckChapter`、`posWord` 是该行为的实现基础。重构只能抽取和强化这些语义，不能另写一套互相竞争的恢复逻辑。

## 5. 性能优先设计

性能不是重构后的“测试项”，而是架构约束。

### 5.1 必须保留的现状

- 静态 HTML 壳优先显示。
- 启动 HTML 只内联最多 40 条词数据（用于快速装填第一张卡），其余按内容哈希分片加载；实际学习界面始终一张卡。
- 当前牌组和章节按需加载，详情按字母分片。
- Service Worker 缓存 shell、数据和音频。
- 列表只渲染当前页，控制 DOM 节点数。
- Worker 静态资源不经过 D1。
- 音频优先缓存，失败再回退。
- 内容文件使用 immutable 缓存，HTML/SW 不缓存旧版本。

### 5.2 热路径规则

以下链路属于热路径：

```text
滑动输入 -> 手势判定 -> 学习状态变更 -> 渲染下一张卡 -> 批量持久化
章节切换 -> 读取当前章节分片 -> 建立当前索引 -> 渲染当前位置
音频播放 -> 命中缓存 -> 立即播放 -> 后台补齐
```

热路径必须：

- 使用原生 DOM、数组、Set/Map 和纯函数。
- 不通过反射、DI 容器、装饰器元数据或动态代理。
- 不每次滑动都 `JSON.stringify` 全量进度并同步写 localStorage。
- 不每次渲染都重建所有 DOM 或重复加载整本词库。
- 日志、同步、统计不能阻塞滑动和下一张卡片。
- 持久化采用批量/空闲/flush-on-hide，并保证崩溃窗口可接受。
- 大型不可变对象复制必须有基准；优先局部更新和索引。

允许在热路径中“直接”处理，不等于允许全局变量和跨模块乱改。仍然必须通过 `study.domain.ts` 的状态转换入口。

### 5.3 冷路径

以下模块可按需加载，并允许更完整的抽象：

- 账号与配对。
- 设置、图标、统计详情。
- 离线全量下载。
- 错误上报。
- PDF 和内容工具。

不得为了拆分冷路径制造过多网络请求。按实际网络瀑布决定静态 import 或动态 import。

### 5.4 硬预算

| 预算 | 目标 |
|---|---|
| 首屏 HTML gzip | <= 20 KB |
| 首屏关键 JS gzip | <= 45 KB |
| 首卡片 | 现有门槛不退化，目标 < 800 ms |
| 首屏 DOM | < 400 节点 |
| 首屏网络瀑布 | 不加载完整词库和详情 |
| 滑动输入 | 不触发网络和同步全量序列化 |
| 架构迁移 | 性能退化超过 5% 即停止并回退 |
| Worker 静态请求 | 0 次 D1 查询 |
| 重复代码/数据加载 | 同一 deck 分片不得重复请求两次 |

这些是当前项目的工程预算，不是抽象口号。修改预算必须写 ADR 并附测量。

## 6. 可扩展性设计

可扩展性来自稳定边界，不来自堆接口。

### 6.1 真正的扩展点

| 扩展需求 | 固定边界 | 扩展方式 |
|---|---|---|
| 新牌组 | Deck Manifest + Deck schema | 新增内容源和目录项，不改学习循环 |
| 新排序/权重算法 | Study Strategy | 新增纯函数策略并测试 |
| 新音频源 | AudioTransport | 新增 adapter，不改 UI |
| 新本地存储 | ProgressStore Port | 新增 adapter，双读迁移 |
| 新后端存储 | Repository Port | 仅在必须换 D1 时新增 adapter |
| 新详情展示 | Deck/Word schema + Detail view | 新增字段和渲染器 |
| 新统计维度 | Stats projector | 订阅领域事件，不侵入滑动逻辑 |
| 新部署目标 | Build publisher | 新增 publisher，不改数据转换 |

### 6.2 不是扩展点的内容

- 每个 UI 组件都建接口。
- 每个 service 都建 factory。
- 每个纯函数都包 class。
- 为未来第三方插件做插件系统。
- 为未来微服务提前拆数据库。

只有业务真的出现第三方插件、独立团队、独立扩容时，才重新评估。

## 7. 扩展和解耦的架构检查

项目应加入自动架构测试，不能只靠口头约定。

### 7.1 依赖规则

```text
features/*/*.domain.ts       -> shared 纯类型；禁止其他层
features/*/*.usecases.ts     -> domain + ports + shared
features/*/*.ports.ts        -> 纯接口
platform/*                   -> 外部 API；实现 ports
features/*/*.view.ts         -> usecases + ui；禁止外部 API
app/bootstrap.ts             -> 全部模块；唯一组装点
worker/http/*.ts             -> app/domain；禁止直接写 D1 SQL
worker/features/*/repo.ts    -> platform/d1.ts
```

### 7.2 CI 自动规则

- 禁止循环依赖。
- 禁止 Domain 导入 Browser/Cloudflare/D1 类型。
- 禁止 View 深层导入其他 feature 的内部文件。
- 禁止 Worker route 直接执行 SQL。
- 禁止两个 `mergeSnapshots`、`fillDeckInBackground` 或章节补全实现。
- 禁止提交 `content/generated`、`deploy`、`output`。
- 文件超过硬上限时构建失败。
- bundle gzip、首卡片和 DOM 预算超限时构建失败。

这些规则可用 dependency-cruiser、ESLint、自定义 Node 脚本实现。优先简单可靠，不引入庞大治理平台。

## 8. 语言、数据库和 JSON/CSV

### 8.1 语言职责

| 技术 | 负责 | 不负责 |
|---|---|---|
| TypeScript | Web、Worker、共享契约、状态与算法 | 离线数据清洗 |
| Python | 词频、内容清洗、校验、发布、PDF | 在线请求 |
| SQL | D1 schema、索引、迁移、数据修复 | 业务编排 |
| HTML/CSS | 页面结构、样式、可访问性 | 大段业务脚本 |
| JSON | 运行时只读数据、manifest、API | 人工审校主源 |
| CSV/TSV | 人工编辑和审校 | 浏览器运行时读取 |
| JSONL | 事件、审计、大记录测试数据 | 小型配置 |

不引入 Go、Rust、WASM：当前没有测量证据表明它们能抵消构建、运维和团队成本。

### 8.2 数据库

继续使用 D1。当前用户、会话、进度、配对码和限流的数据模型适合 SQLite 风格；换 Postgres 不会自动带来商业级质量，反而增加连接、迁移和运维复杂度。

必要改造而不是“大数据库重写”：

- Session token 改为哈希存储、可撤销、可轮换。
- `progress` 增加 `schema_version`、`payload_hash`、`revision`。
- 保留原子快照更新；需要审计时再加 append-only `progress_events`。
- 增加 `schema_migrations` 和可回滚迁移流程。
- 增加过期索引和备份策略。
- 参数绑定、body 上限、限流和统一错误码。

只有实测出现跨区域写入、复杂事务、分析查询或 D1 容量瓶颈时，才评估 Postgres。

### 8.3 JSON/CSV

- 人工源：`content/sources/` 中 CSV/TSV/JSONL。
- 运行时：`content/generated/` 中版本化 JSON 分片。
- 生成物：带 `schemaVersion` 和内容哈希，不提交 Git。
- 构建：确定性排序、无运行时间戳、manifest 哈希。
- 浏览器：只读取 JSON；不直接解析 CSV。
- 不把所有数据塞成一行巨型 JSON，也不把所有审校文件改成数据库。

## 9. 当前大文件和文件乱放问题

结论：

- `template.html` 已经过大，必须拆。
- `worker.js` 的 `handleApi` 已经过大，必须拆。
- `make_html.py` 和 `run_tests.py` 职责混杂，必须拆。
- 仓库确实有过多历史文件，但不是“见到 archive 就删”。先确认唯一数据、引用和归属，再迁移或删除。

### 9.1 文件归属

- 活跃业务源：`apps/`、`packages/`、`pipeline/`、`content/sources/`。
- 测试：`tests/` 和 feature 内小测试。
- 生成物：`artifacts/`、`content/generated/`、CI artifact。
- 历史：独立 `archive/` 或 Git tag。
- 实验：`tools/experiments/`，命名必须表达用途。
- 根目录实验文件：`.cmp.py`、`.edge*.py`、`.probe.py`、`.runt*.py`、`.t*.py`、`swspec.tmp` 先确认归属后处理。

### 9.2 清理原则

- `scripts/archive/`、`scripts/tools/archive/`：约 86 个文件，迁出活跃构建树。
- `data/archive/`：约 27 个文件，校验引用后归档。
- `software/考研核心词.html`、`software/sw.js`：生成物，停止 Git 跟踪。
- `deploy/`、`output/`：构建/调试产物，仅保留本地或 CI artifact。
- `.omc/`、`.wrangler/`：本地工具状态，加入 `.gitignore`。

归档不是删除。保留可追溯历史，但不要让归档参与构建、搜索和 AI 默认上下文。
## 10. 设计模式使用规则

设计模式是局部实现工具，不是架构目标。选择顺序：

1. 先判断是否真的存在变化点。
2. 先用函数、组合、参数和普通对象解决。
3. 只有在职责、替换或扩展需要时才引入模式。
4. 每次引入都写一个小 ADR：问题、候选、选择、性能影响、退出条件。

### 10.1 第一优先级：现在值得使用

| 模式 | 限定用途 | 为什么值得 | 性能/复杂度约束 |
|---|---|---|---|
| Adapter 适配器 | 存储、HTTP、音频、D1 这些真实外部边界 | 防止平台 API 渗透业务，替换和测试有真实收益 | Adapter 只在边界，不在热路径每帧反复查找 |
| Strategy 策略 | 排序/权重、音频回退、同步冲突选择 | 新增算法不改调用方，可纯函数单测 | 策略在初始化时确定，不为每个单词动态分配 |
| Command 命令 | 用户滑动、撤销、批量状态变更 | 可记录、可撤销、可重放，明确一次学习动作 | 只保存必要字段，不存整份状态快照 |
| Memento 备忘录 | 撤销上一次滑动/操作 | 替代散落 undo 变量，控制状态恢复 | 只保留有限窗口，禁止无限历史内存增长 |
| State 状态机 | 学习页网络/音频/提交等显式状态 | 消除布尔变量互相打架 | 状态转换是纯函数，渲染订阅变化 |
| Observer 观察者 | UI 订阅学习状态、统计、同步状态 | 解耦状态与视图，避免瀑布式直接调用 | 事件必须有类型；禁止热路径事件风暴和同步全量重渲染 |
| Composite 组合 | Deck、Chapter、Word 的统一遍历/分页 | 章节和牌组操作一致 | 不复制大对象；使用索引和只读视图 |
| Iterator 迭代器 | 分片加载、章节分页 | 隐藏异步分片细节，边界清晰 | 不额外复制整本词库；按需加载 |

#### 采用顺序

1. State、Command、Memento、Observer 解决学习页状态一致性。
2. Adapter 隔离 storage、HTTP、audio、D1。
3. Strategy 只用于已有多个算法或明确需求。
4. Composite/Iterator 只用于分页和分片，不重造数据层。

### 10.2 第二优先级：有明确条件再用

| 模式 | 触发条件 | 默认决策 |
|---|---|---|
| Decorator | 已有横切中间件，需要组合 auth/rate/logging/error | Worker 可用；前端不要用装饰器包裹热路径 |
| Chain of Responsibility | API 中间件链或内容校验链 | Worker 用；不要在 UI 事件中建立长链 |
| Facade | 同步、音频、离线等多个底层协作复杂 | 用薄 Facade，禁止变成上帝对象 |
| Builder | 内容发布物、manifest、复杂测试 fixture | Pipeline 用；普通对象不用 builder |
| Factory Method | Adapter 创建需要环境差异 | 只用于 composition root |
| Proxy | Service Worker 缓存代理是实际代理语义 | 不新增业务代理层 |
| Bridge | 已有多种内容源格式和多发布器 | 数据流水线需要时才用 |
| Template Method | 数据发布流程固定但某些步骤可替换 | 优先函数组合，确有多实现再用 |

### 10.3 默认拒绝：当前不要使用

| 模式 | 为什么不用 |
|---|---|
| Singleton | 容易隐藏全局可变状态；只允许无状态配置模块 |
| Abstract Factory | 只有一个 D1、一个 Cloudflare 运行环境，没有多产品族 |
| Prototype | 当前对象复制不需要隐藏机制，显式结构更安全 |
| Flyweight | 没有性能证据表明当前缓存需要专门享元层 |
| Interpreter | 没有查询 DSL 或规则语言 |
| Mediator | 容易把事件总线变成全应用耦合中心；只保留极少量 typed events |
| Visitor | 没有复杂树和多种独立操作 |
| 全量 DI 容器 | 手工 composition root 足够，容器 API 反而妨碍性能和追踪 |
| 全量 Repository 泛型框架 | 只在 Worker D1 边界使用简单 repository 函数 |
| 插件系统 | 没有第三方扩展和隔离执行需求 |

### 10.4 23 种模式完整对照

下表只用于防止 AI 机械照搬，不代表要全部实现。

| # | 模式 | 当前结论 | 采用条件 |
|---:|---|---|---|
| 1 | 抽象工厂 | 拒绝 | 出现多个数据库/运行时产品族 |
| 2 | 生成器 | 条件采用 | 内容发布、manifest、复杂 fixture |
| 3 | 工厂方法 | 条件采用 | 只在 composition root 创建 Adapter |
| 4 | 原型 | 拒绝 | 没有安全复制复杂对象的真实需求 |
| 5 | 单例 | 严格限制 | 只允许无状态配置/常量 |
| 6 | 适配器 | 采用 | 存储、HTTP、音频、D1 边界 |
| 7 | 桥接 | 条件采用 | 多内容格式与多发布器同时存在 |
| 8 | 组合 | 条件采用 | Deck/Chapter 有统一遍历需求 |
| 9 | 装饰器 | 条件采用 | Worker 中间件，不用于 UI 热路径 |
| 10 | 外观 | 条件采用 | 一个 Facade 封装真实复杂协作 |
| 11 | 享元 | 延后 | 有内存和对象分配测量证据 |
| 12 | 代理 | 采用现状 | Service Worker 缓存代理 |
| 13 | 责任链 | 条件采用 | API 中间件、内容校验 |
| 14 | 命令 | 采用 | 滑动、撤销、状态变更 |
| 15 | 解释器 | 拒绝 | 没有 DSL |
| 16 | 迭代器 | 条件采用 | 分片、分页、异步加载 |
| 17 | 中介者 | 严格限制 | 只做少量 typed app events |
| 18 | 备忘录 | 采用 | 撤销/恢复有限操作 |
| 19 | 观察者 | 采用 | UI 订阅状态变化 |
| 20 | 状态 | 采用 | 学习流程显式状态机 |
| 21 | 策略 | 采用 | 排序、权重、音频、同步冲突算法 |
| 22 | 模板方法 | 延后 | 优先组合；有多步骤多实现时再评估 |
| 23 | 访问者 | 拒绝 | 没有复杂树和多个外部操作 |

### 10.5 防止过度设计

以下信号出现时，停止新增抽象：

- 一个接口只有一个实现，而且近期没有第二种实现。
- 一个类只包装另一个函数，没有额外语义。
- 一个目录只有 index.ts 和 type.ts，没有独立价值。
- 抽象导致热路径多一次动态查找、额外复制或异步边界。
- 单元测试必须 mock 五层才能测一个纯规则。
- 为了复用而把两个变化原因不同的功能合在一起。

**复杂度也必须有预算。**

## 11. 解耦后的模块职责

### 11.1 Web

```text
app/bootstrap.ts       组装依赖；决定 localStorage/IndexedDB、API、音频实现
app/app-shell.ts       页面路由、聚焦管理、生命周期
features/deck/         分片加载、deck manifest、章节位置、启动恢复；保留现有补全语义
features/study/        学习状态机、排序、权重、滑动命令、撤销
features/sync/         本地/云端同步用例；依赖 merge 纯函数和 API port
features/auth/         登录、注册、配对、会话恢复
features/audio/        音频 URL、缓存标记、播放回退、离线下载
features/offline/      shell/词库/音频缓存状态与下载编排
features/stats/        统计读取和展示；不进入滑动写入路径
platform/storage.ts    localStorage/IndexedDB Adapter
platform/http.ts       fetch、超时、压缩、错误映射
platform/media.ts      Audio API
ui/components/         纯 DOM 组件，不直接访问网络和存储
```

关键约束：

- `features/study/study.domain.ts` 是滑动状态变更的唯一入口。
- `features/study/study.persistence.ts` 只在合适时机批量保存，不在每个 pointermove 序列化全量数据。
- `features/deck/` 保留 `fillDeckInBackground`、`pendingSeek`、`chapterExpectedLength` 的语义，不允许另起补全器。
- `features/sync/` 不自己重写 merge 算法，只能调用 shared 的唯一实现。
- `stats` 通过事件或只读 selector 更新，不能拖慢滑动主循环。

### 11.2 Worker

```text
index.ts                  Cloudflare 入口
app.ts                    router 和全局错误边界
http/middleware.ts        origin、auth、rate、body、requestId
features/auth/            注册/登录/登出/会话
features/progress/        GET/PUT/sync
features/pair/            配对码
features/audio/           音频代理和缓存
platform/d1.ts            D1 prepared statements
```

关键约束：

- `app.ts` 只做路由和装配，目标不超过 40 行。
- route handler 只处理 HTTP 参数和响应，不直接写 SQL。
- `platform/d1.ts` 和 feature 的 repository 才允许 SQL。
- auth、rate、origin、body 限制是中间件，不复制到每个 handler。
- 所有错误映射统一，不返回 SQL 或内部堆栈。

### 11.3 Shared

```text
packages/shared/src/
  contracts.ts            API/存储 DTO 和错误码
  schema.ts               运行时 schema 校验
  merge.ts                唯一 merge 实现
  events.ts               极少量的跨端领域事件类型（可选）
```

不把 UI 组件、DOM helper、Worker 请求函数塞进 shared。Shared 只放稳定且真正跨端的契约。

### 11.4 Pipeline

```text
pipeline/sources/        读取 CSV/TSV/JSONL
pipeline/transforms/     规范化、去重、分词、排序
pipeline/validators/     schema、唯一性、覆盖率、引用完整性
pipeline/publishers/     JSON 分片、manifest、PDF、deploy 目录
pipeline/cli.py          validate/build/publish 入口
```

每步可单独运行、单独测试，不能要求每次修改都跑完整 PDF 或部署。

## 12. 性能关键路径的实现约束

### 12.1 滑动与学习

- pointermove 只做局部 transform，不写存储、不生成全量 snapshot。
- pointerup 通过一个 `StudyCommand` 改变状态。
- 渲染只更新变化卡片、位置、统计摘要，不重建整页。
- 撤销使用 Memento 或可逆 Command，历史长度有上限。
- 权重、到期和 mastered 只计算当前词与必要统计。
- 持久化批次合并，页面隐藏和关键动作时 flush。

### 12.2 章节和牌组

- 只加载当前 deck；只准备当前 chapter 所需索引。
- 启动数据最多内联 40 条和后台补全保留；不能把它误解为首屏并列显示 40 个词。
- 章节位置以词 key 为源，不以可变数组下标为源。
- 同一分片请求去重；失败重试有界。
- 不因一次 UI 拆分导致本可并行的数据请求串行瀑布。

### 12.3 Service Worker

- 缓存 key、版本、data hash 保持一致。
- 音频缓存预算不可回退。
- 静态资源命中不经过 Worker 业务代码。
- 升级必须先激活新 shell 再切换数据版本。
- 所有离线逻辑有 fresh profile e2e。

### 12.4 性能测量

每次影响热路径的改动必须给出：

- production build 的 gzip 体积。
- 首卡片和 DCL。
- 滑动 100/1000 次的 p50/p95。
- DOM 节点变化。
- 网络请求数和 waterfall。
- 存储序列化次数和耗时。
- Service Worker cold/warm 行为。

没有测量，不称为“性能优化”。

## 13. 架构迁移约束（执行顺序不在这里）

本节只定义“怎么改才不破坏目标架构”，不另设 Phase 或任务清单。

实际执行顺序、文件白名单、验收数据、提交和回滚必须遵循：

**[PHASES.md](./PHASES.md)**（任务顺序与验收）+ **[AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md)**（方向与不变量）

架构迁移的硬约束：

1. 先建立 characterization test，再移动代码。
2. 先拆真实边界，再拆 UI：shared contracts/merge、storage、HTTP、deck、study、audio、view。
3. 一次只移动一类职责；每步提供构建体积、首卡片、DOM、存储写入的前后对比。
4. `software/template.html` 同一时间只允许一个会话负责。
5. 第一章按 200 词补全、启动数据最多内联 40 条、上次学习位置恢复的语义不得改变。
6. Worker 拆分时 SQL 只能进入 repository/platform；路由不得直接访问 D1。
7. 内容构建必须确定、可校验、可复现；生成物不得手工修改。
8. 任何架构改动导致热路径退化超过 5% 时停止并回滚。
9. Claude/Codex 多 Agent 协作属于工程控制面，不是业务架构层；不得借机引入微服务、消息队列、第二套领域逻辑或第二套存储协议。
10. Claude Code skill 路由与递归子 Agent 预算见 [AGENT_SKILL_MATRIX.md](./AGENT_SKILL_MATRIX.md)；skill 是执行工具，不是新的业务层或扩展点。
11. 递归 Agent 必须使用明确的 skill、worktree、租约、固定 SHA 和独立验收；没有证据的子 Agent 汇报不算完成。
12. 架构审查必须由不负责实现的只读 Agent 或独立验收者完成；实现者自审只能作为预检，不能作为最终验收。

## 14. 架构审核协议（不定义任务）

本节只用于评审一次改动是否守住架构，不规定执行顺序、文件白名单或排期；这些统一见 [PHASES.md](./PHASES.md)。

架构审核必须回答：

1. 改动对应哪个真实变化点，为什么现在需要这个边界？
2. 业务规则是否仍不依赖 DOM、浏览器存储、HTTP 或 D1？
3. 是否新增或重复了 merge、章节补全、缓存、同步实现？
4. 是否进入 pointermove、滑动渲染等热路径，多出何种分配、查找或异步边界？
5. 是否有 characterization test、性能前后数据和明确回滚方法？
6. 新增抽象何时删除；出现什么信号时应撤回？
7. 使用了哪个 skill 路由？该 skill 是否只影响执行流程，而没有偷偷引入新的业务层或第二套实现？

### 架构禁止清单

- 不得为了 23 种模式全部落地而造类。
- 不得把纯函数包成 service/factory/manager。
- 不得给单实现接口加两层工厂。
- 不得把所有状态塞入全局 event bus。
- 不得把静态词库塞进 D1。
- 不得把完整词库重新内联到首屏。
- 不得把现有第一章补全逻辑重写成“更优雅”的第二套。
- 不得仅凭旧 Service Worker 缓存判断上线结果。

## 15. 架构与验收定义

### 15.1 架构验收

- Domain/Application 无平台导入。
- 没有循环依赖。
- 每个 feature 只暴露窄 API。
- 只有 composition root 创建 Adapter。
- Worker route 无直接 SQL。
- `handleApi` 不超过 40 行。
- 没有重复 merge、补全、同步和缓存实现。
- 文件超过硬上限会被 CI 阻断。

### 15.2 性能验收

- 首屏 HTML gzip 不超过 20 KB。
- 首屏关键 JS gzip 不超过 45 KB。
- 首卡片门槛不退化，目标小于 800 ms。
- 首屏 DOM 小于 400。
- 启动时不加载完整词库，但必须尽快恢复上次牌组、章节和词。
- 滑动和撤销不触发全量序列化。
- 章节切换无重复分片请求。
- 离线 cold/warm 路径通过 fresh profile 测试。
- 相对基线退化超过 5% 时阻止合并。

### 15.3 商业级验收

- 干净环境一条命令完成构建和测试。
- 锁文件完整，双次构建哈希一致。
- CI 全绿，性能预算有实际测量。
- 内容源、生成物、归档、测试数据分离。
- D1 迁移、备份、回滚可演练。
- session、限流、输入校验、错误映射通过安全测试。
- 账号删除、导出、隐私和内容授权有实际流程。
- 新牌组、新排序策略、新音频源有独立扩展路径。
- 结构和 ADR 能让人类与 AI 判断“改哪里”和“不该改哪里”。
- 每项改动可追溯到任务 ID、run ID、worktree、固定 commit SHA、验证证据和回滚点。
- 独立架构审查能证明没有越过任务白名单，也没有新增重复的 merge、章节补全、缓存或同步实现。

## 16. 最终决策摘要

| 问题 | 决策 |
|---|---|
| 换数据库吗 | 不换，继续 D1；实测有瓶颈才评估 Postgres |
| 换 JSON/CSV 吗 | 不整体换；CSV/TSV 人工源，JSON 运行时产物，JSONL 事件/测试数据 |
| 换语言吗 | Web/Worker 用 TypeScript，Pipeline 用 Python，DB 用 SQL；不引入 Go/Rust |
| 用 React 吗 | 暂不；原生 DOM + TS 优先，只有组件复杂度证明需要时才评估 Preact |
| 是否全量 DDD | 不；采用模块化单体和 feature-first 轻量分层 |
| 是否微服务 | 不；当前没有独立部署和扩容需求 |
| 设计模式怎么用 | 只用于真实变化点；采用 Adapter/Strategy/Command/Memento/State/Observer/Composite/Iterator，其他条件采用或拒绝 |
| 单文件大吗 | 是，必须拆；页面壳 <= 250 行，源文件目标 <= 300 行 |
| 文件乱放吗 | 是，生成物、历史、实验和源混放；先确认归属后迁移 |
| 最高优先级 | 性能基线、可复现构建、真实边界解耦，不是重写 UI 或堆叠架构 |