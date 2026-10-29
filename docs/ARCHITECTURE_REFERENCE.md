# 单词项目架构参考（as built）

> 核对日期：2026-10-29。本文描述当前仓库已实现的架构和不可破坏的协议，不再把“建议目标”写成本文主线。
>
> 产品与数据边界：[AI_EXECUTION_PLAN.md](./AI_EXECUTION_PLAN.md)
> 阶段状态与验收：[PHASES.md](./PHASES.md)
> 构建/发布命令：[README.md](../README.md)

## 0. 架构结论

- 保持现有 Web/PWA，不重写为 C++/Qt；当前也没有 Qt 并行客户端。
- 前端使用原生 HTML/CSS/JavaScript；没有 React、TypeScript 构建链或运行时模块框架。
- 托管和接口：Cloudflare Pages 静态资源 + Pages Functions/Worker + D1。
- 静态词库与用户数据分离：词库是内容哈希文件，D1 只保存账号、会话和用户进度。
- 优化集中在启动、存储、缓存和同步；不为了“架构完整”引入微服务、消息队列、全量 DDD 或第二套离线协议。

## 1. 运行时总览

```text
Browser
  ├─ index.html + app.<hash>.js
  ├─ localStorage: 64-shard state / positions / config / daily
  └─ Service Worker
       ├─ ky-shell-<build>  页面壳、主程序、四本词库
       └─ ky-audio-v2       中英文音频

Cloudflare Pages
  ├─ deploy/ 静态资源（immutable 哈希文件）
  ├─ _worker.js
  │    ├─ /api/auth, /api/state, /api/state/sync
  │    ├─ /api/audio（英语源站 / 中文 TTS 代理）
  │    └─ /api/health
  └─ D1: users / sessions / progress / rate / pair_codes
```

这是一个 local-first、模块化单体应用。前端离线读写不依赖网络；联网后再把快照交给服务端合并。

## 2. 前端源码与构建链

### 2.1 手写源

`software/src/` 是前端唯一手写源：

| 文件 | 责任 |
|---|---|
| `shell.html` | DOM 骨架、占位符、少量启动元数据 |
| `styles.css` | 全部样式 |
| `app.manifest.json` | 固定 12 个 JS 片段的顺序 |
| `app/00-deck-loader.js` | Web/单文件模式的词库与详情装载 |
| `app/10-storage.js` | localStorage 分片、位置、迁移和快照基础 |
| `app/20-decks.js` | 牌组元数据和章节选择 |
| `app/30-study.js` | 队列、章节补全、位置恢复、学习动作 |
| `app/40-audio.js` | 音频播放、缓存标记、离线下载 |
| `app/50-list-stats.js` | 词表、分页、统计 |
| `app/60-deck-actions.js` | 洗牌、重置、牌组操作 |
| `app/70-input.js` | 点击、长按、滑动、详情 |
| `app/80-import-export.js` | 备份导入导出 |
| `app/90-sync-auth.js` | 账号、快照、同步、合并应用 |
| `app/95-events-errors.js` | 全局事件与错误边界 |
| `app/99-offline-main.js` | SW 注册、离线下载、缓存消息 |

### 2.2 装配

`scripts/frontend_bundle.py`：

1. 读取 `shell.html`；
2. 将 `styles.css` 放入 `__KY_STYLES__`；
3. 按 `app.manifest.json` 顺序拼接 `app/*.js`，放入 `__KY_APP__`；
4. 拒绝片段中的 `import`/`export`、提前出现的 `</script>`、缺失文件和重复清单；
5. 写出 `software/template.html`，或通过 `--check` 验证生成物是否过期。

这是**源码布局拆分**，不是 ES module 运行时。所有片段仍共享同一经典脚本顶层作用域，以保持单文件离线版和首卡路径不变。不要并行手改 `software/src/` 与生成后的 `template.html`。

### 2.3 `make_html.py`

`make_html.py` 是生成的唯一入口：

- 校验必需构建输入；`data/ecdict.csv`、`lemma.en.txt` 和可选 `ref/` 原件不参与默认 build/source 指纹。文本输入按 LF 规范化后哈希，确保 Windows/Linux 干净 checkout 可复现同一 build；
- 将 `shared/merge.js` 注入 `software/template.html` 和 `backend/worker.js` 的单处 `/*__MERGE__*/` 占位符。
- 用 Terser `5.51.2` 压缩主程序；失败即中止构建。
- 输出：
  - `software/考研核心词.html`：内嵌全部词库的单文件版；
  - `deploy/index.html`：首屏仅内联 40 个核心词；
  - `deploy/app.<sha256-12>.js`：内容哈希主程序；
  - `deploy/data/*.<sha256-12>.json`：四本词库和按字母拆分的详情；
  - `deploy/sw.js`：已注入 build、app 和四本词库哈希的 SW；
  - `deploy/_worker.js`：已注入共享合并实现的 Worker；
  - `deploy/build-meta.json`：`build`、`source_digest`、`app_asset`。
- `build` 哈希覆盖页面、SW、Worker、合并源码、输入清单、manifest 和图标；`app` 哈希只覆盖主程序内容；可选上游原件缺失或存在都不能改变版本。
- 缓存头：HTML `max-age=0, must-revalidate`，`sw.js`/`build-meta.json` `no-cache`，`/data/*` 和 `/app.*.js` 长期 immutable。

### 2.4 构建互斥与原子切换

- `deploy.lock` 以 `O_EXCL` 创建并写入随机 ownership token；不自动抢占既有锁。释放时只删除 token 匹配的锁。
- 每次构建进入独立 `deploy.tmp/build-*` 暂存目录。
- 完整生成后先原子写单文件版和 `software/sw.js`，再替换 `deploy/`；第二次 rename 失败会恢复旧目录。
- 不允许多人同时运行 `make_html.py`，也不要手工删除仍在使用的 `deploy.lock`。

## 3. 启动与学习路径

固定语义：

1. 网页版 `deploy/index.html` 只内联 40 个词，`CHAPTER_SIZE = 200`。
2. 第一章通过 `fillDeckInBackground` 拉取哈希词库；`pendingSeek` 记录待恢复的目标，`chapterExpectedLength` 让进度在数据未齐时仍显示 `第 1 / 200 个`。
3. 数据到达后按 `posWord` 查找上次词；找不到才用 `pos` 夹取；最后才回章节起点。
4. 补全前不先渲染并保存错误的第一词。
5. 词表首屏只渲染 100 条，后续增量加载。
6. 详情按首字母分片；同字母请求去重，失败不缓存空分片。

禁止：

- 另写第二套章节补全或位置恢复。
- 为“简化”而把完整词库重新内联到网页首屏。
- 在 pointermove 或滑动帧里同步序列化完整 state。

## 4. 本地持久化

### 4.1 主状态：generation + 64 shard

`ky_words_v1` 是逻辑名，实际存储为：

```text
ky_words_v1#meta[@account]                        -> "2:<generation>"
ky_words_v1#<generation>-<0..63>[@account]        -> { word: record, ... }
```

- `stateShardIndex(word)` 用稳定 hash 选择 0–63。
- 单次 `saveStateRecord(word)` 只写对应分片，不再重写全部词。
- 旧 `ky_words_v1` 是迁移回退源；首次读取会建立 generation shard，成功后删除旧键。
- 导入/清空先写完整新 generation，最后写 meta 完成原子切换；失败时旧 generation 仍是权威数据。
- 账号作用域通过 `@account` 后缀隔离；游客使用无后缀键。

### 4.2 位置与其他键

| 键 | 内容 | 关键约束 |
|---|---|---|
| `ky_pos_v1[@account]` | `deck:chapter -> {pos, posWord, t}` | 翻词只写这个小记录；不重复写整份章节 order |
| `ky_chapter_v1[@account]` | 每章队列 `order`、位置与时间戳 | 支持墓碑和账号隔离 |
| `ky_conf_v1[@account]` | 当前牌组/章节、显示/朗读设置、图标、fence 回传字段 | 不应保存大词表 |
| `ky_daily_v1[@account]` | 每日 `{s,m,t}` 或墓碑 | 保留 120 天，撤销写较新的 `t` |
| `ky_stamp_v1[@account]` | 同步水位/快照元数据 | 与进度分开 |

`ky_pos_v1` 每次只从最新表读取并更新当前 `deck:chapter`，不会用本标签页内存重建整表覆盖其他标签页的位置；章节 `order` 仍只在切章/导入时写。

当前实现**没有 IndexedDB**。是否迁移必须以现有 64 shard 实测无法满足内存/写入预算为前提，不能只因为 IndexedDB 名字更现代就增加双存储复杂度。

## 5. Service Worker 缓存协议

源码模板是 `software/sw.template.js`，生成的 `software/sw.js` 才带实际 build/hash。

### 5.1 命名空间和生命周期

- `ky-shell-<BUILD_VERSION>`：安装时缓存根页面、`app.<hash>.js`、manifest 和图标；激活后后台预取四本词库。
- `ky-audio-v2`：跨 build 保留音频；音频版本与前端 `AUDIO_CACHE_VERSION = 'v2'` 对齐。
- `ky-prefetch-diagnostics-v1`：保存预取运行诊断，不承载业务数据。
- install 的核心壳必须成功，否则安装失败；成功后 `skipWaiting()`。
- activate 删除旧 shell 和旧 `ky-audio-*`，`clients.claim()`，广播优先级预取请求并补四本词库。
- 页面用 `updateViaCache: 'none'` 注册，每次启动最多检查一次更新；已有控制器发生替换时刷新，首次安装不刷新。

### 5.2 请求与反馈

- 导航：network-first，3 秒弱网超时后回退缓存；不能 cache-first 返回旧页面。
- 哈希静态资源：cache-first；未命中时同步等待 `cache.put` 结果再反馈。
- 音频：按规范化 `word/lang/v` cache-first；同 URL 网络请求去重；只缓存 `response.ok`。
- `/api/*` 不由 SW 拦截；账号、同步和音频代理直接走后端。
- 音频缓存上限 8000 条；配额吃到 80% 或剩余不足 8MB 时淘汰旧条目，并向页面发送 `ky:audio-evicted`。

响应协议：

| 头/消息 | 作用 |
|---|---|
| `x-ky-cache: hit` | 缓存命中 |
| `x-ky-cache: stored` | 本次已成功落盘 |
| `x-ky-cache: store-failed` | 未落盘，页面不得写“已缓存” |
| `x-ky-cache-revision` | SW 内单调缓存修订号 |
| `x-ky-cache-epoch` | 区分不同 SW 实例，丢弃乱序旧消息 |
| `ky:audio-evicted` | 页面同步删除对应本地 marker |
| `ky:prefetch-status/failed` | 预取完成或失败诊断 |

页面只认 `stored`/`hit` 的 revision/epoch 作为落盘凭据；播放事件不能重新写 marker，否则 SW 已淘汰的音频会被假标成可离线。

## 6. 同步合并与 serverFence

### 6.1 单一实现

`shared/merge.js` 是唯一合并源。`make_html.py` 在构建时把它分别注入前端模板和 Worker：

- 普通快照字段：`state`、`chapterData`、`daily`、`conf`；
- 墓碑规则：删除与重新学习按 `t` 和 `del` 裁定，过期墓碑可修剪；
- 位置：牌组/章节位置与 `progressAt` 合并，后端不从 DOM 取状态；
- import 是整份覆盖，clear 是按 fence 截断历史并保留 fence 后的并发新记录。

### 6.2 serverFence

破坏性操作不能靠“客户端当前时间”直接覆盖云端：

1. 客户端发送 `reset`、`mode: clear|import`；clear 发送 `resetAt`，import 发送点击时刻 `importStartedAt` 和持久化 `operationId`；
2. Worker 删除客户端可伪造的 `serverFence*`、`overwrite*`、`import*` 临时字段；
3. Worker 按点击时刻生成单调 `serverFenceAt`；import 记录 `serverFenceOperationId`，同 ID 重试直接返回当前云端结果，确保响应丢失后不二次覆盖；
4. `clear` 同步维护 legacy `resetAt`；import 写独立 import fence 且 `resetAt=0`，不伪装成长期 clear 栅栏；过期破坏操作不能越过更新 fence；
5. 普通 PUT 和 `/api/state/sync` 都先应用云端持久 fence，再合并；旧设备无法把 fence 之前的独有记录复活。

同毫秒多个操作不通过人为 `+1` 伪造 fence；fence 只前进不后退，操作类型由 mode 区分。

### 6.3 请求与并发

- `POST /api/state/sync`：首次登录、冲突后合并、reset/import；一次读取、合并、写回，最多重试两轮。
- `PUT /api/state`：本地有增量时的快路径；`baseUpdatedAt` 做乐观锁。
- `GET /api/state?since=...`：云端未变时只返回 `unchanged`。
- D1 `updated_at` 严格单调，避免同毫秒双写、轮询漏更新和客户端旧快照覆盖。
- 入库前按稳定键序序列化，避免键序变化制造无意义写入。
- 解压后 payload 上限 512 KiB；gzip 解压有累计大小保护；SQL/上游错误不回显。

## 7. Worker 与 D1 边界

- Worker 入口只把 `/api/*` 交给 API，其余交给静态资源。
- 静态词库、详情和主程序不查询 D1。
- D1 保存账号、会话、进度、限流与配对码；`/api/health` 真正执行 `SELECT 1`，不是只检查绑定存在。
- 账号请求带 `expectedUsername` 校验，避免切换账号后的晚到响应写错用户。
- 会话默认 30 天；登录失败、状态读写和健康检查均有限流/失败锁。
- 中文 TTS 通过 Worker 代理并受文本白名单/大小约束；英文音频走源站代理。
- 数据库迁移放在 `backend/migrations/`，部署前手工执行；`deploy.py` 不会自动执行迁移。

## 8. 性能基线与预算

2026-10-29 的本地实测见根 [README.md](../README.md)。当前关键结果：

- 首屏 HTML gzip 11,813 B，目标 <20 KB。
- 主程序 gzip 37,131 B，目标 <45 KB。
- 首卡 p50/p95 120/154.8 ms，目标 <800 ms。
- 首屏 DOM 240，目标 <400。
- 章节切换 p50/p95 0.10/0.46 ms，目标 <300 ms。
- 64 shard 单次写 p50/p95 0.00/0.10 ms；完整 state 175,201 B，最大分片 2,994 B。
- 同步快照 182,332 B，gzip 14,961 B；序列化 gzip 均在毫秒级。

这些数字来自生产等价临时构建、5 个全新 Edge profile、本地 HTTP、SW 禁用和本地 WAV 音频。它们不是移动真机结论；移动验收仍需相同脚本和 fresh profile。禁止用旧 SW 缓存或单次最快值替代基线。

## 9. CI、构建锁与发布验收

### 9.1 CI

`.github/workflows/ci.yml` 在 Windows 2022 上固定：

- Python `3.12.9`
- Node `22.23.3`
- Terser `5.51.2`
- Wrangler `4.152.0`

步骤依次为安装锁定依赖、校验工具版本、发现 Edge、数据测试、`make_html.py`、`run_tests.py`、离线实测、性能测量；失败保留 7 天 artifacts。CI 只验证，不自动部署。

### 9.2 发布锁

`deploy.py` 使用 `deploy.publish.lock`：

- 原子创建，存在即拒绝；
- 30 分钟后才视为 stale；
- 提交时间和 `.git/ky-last-release.json` 的上次成功发布时间都必须超过 10 分钟；否则默认拒绝，显式覆盖只用 `--allow-recent-release`；
- 工作区有未提交改动默认拒绝，只有显式 `--allow-dirty-release` 才继续；
- 只允许 `backend/migrations/applied.json` 中记录且 SHA-256 未变化的迁移；新增/改动迁移需人工执行并更新账本；
- 默认执行构建、回归和离线实测；`--skip-test` 只作紧急逃生口。

### 9.3 发布验收

`deploy.py` 同时检查两个 URL，但它们不是两套产品：

- **public URL**：`https://kaoyan2-words.pages.dev/`，Cloudflare Pages 项目的稳定生产入口，普通用户只使用这个地址。
- **deployment URL**：每次部署生成的 `https://<deployment-id>.kaoyan2-words.pages.dev/`，用于访问本次精确 deployment。它是验收和排障地址，不作为长期用户入口。

生产 deployment 完成后，public URL 会指向同一份产物，所以两个网站打开看起来完全一样。同时验收的作用是分别证明“这份精确产物正常”和“生产别名确实已经切过去”。

两个 URL 是不同的浏览器 origin，localStorage、Cache Storage 和 Service Worker 作用域彼此隔离；不能用 deployment URL 推断真实用户在 public URL 下的本地进度或缓存。两者使用同一 Pages 项目和同一套生产 Worker/D1 绑定，不是两个数据库。

`deploy.py` 部署到 `kaoyan2-words` 后必须同时通过：

1. deployment URL 和 `https://kaoyan2-words.pages.dev/` 的 HTTP 检查：`build-meta` 一致、SW build/app 一致、HTML 引用一致、主程序字节/hash 一致。
2. 两个域名各自启动全新 Edge profile，确认页面实际执行对应主程序、SW 已注册/控制、health 为 `ok` 且 D1 可查询。
3. 任一域名失败即返回非 0，不能只凭 Wrangler “上传成功”判定上线成功。

## 10. 明确不做的事

- 不为小项目引入微服务、事件溯源、全量 DDD、通用 DI 容器或插件平台。
- 不把纯函数包装成 service/factory/manager。
- 不改写为 C++/Qt；只有出现明确桌面专属需求并满足独立团队、稳定 API、Web 性能无法解决等条件时才评估可选桌面客户端。
- 不把静态词库塞进 D1。
- 不重复实现 merge、章节补全、SW 缓存或同步。
- 不让生成物成为手写源；不在并发会话中同时编辑同一前端写域。
