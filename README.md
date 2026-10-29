# 考研英语二核心词

一个面向考研英语二的离线优先背单词 PWA。词频来自 2010–2024 年英语二 17 套真题；不是通用词表。

线上地址：<https://kaoyan2-words.pages.dev/>

## 当前形态

- 前端是原生 HTML/CSS/JavaScript，不引入 React，也没有 C++/Qt 客户端；当前没有重写 UI 的计划。
- 托管在 Cloudflare Pages，动态接口由 Pages Functions/Worker + D1 提供，静态词库与用户进度分离。
- 四本牌组：核心词 1342、核心派生 120、基础词 349、保险库 1545，共 3356 词。
- 章节大小为 200。网页首屏只内联前 40 词，再用既有的 `fillDeckInBackground`、`pendingSeek`、`chapterExpectedLength` 补齐第一章，不为启动补全另写第二套逻辑。

## 目录结构

```text
单词/
├── software/
│   ├── src/                   前端唯一手写源
│   │   ├── shell.html         页面壳
│   │   ├── styles.css         样式
│   │   ├── app.manifest.json  有序 JS 片段清单
│   │   └── app/*.js           12 个有序源码片段
│   ├── template.html          scripts/frontend_bundle.py 生成，勿手改
│   ├── sw.template.js         Service Worker 源模板
│   ├── sw.js                  make_html.py 注入版本后的生成物
│   └── 考研核心词.html         单文件版生成物
├── backend/
│   ├── worker.js              Pages Functions / API / D1
│   ├── schema.sql             D1 基线结构
│   └── migrations/            手工执行的数据库迁移
├── shared/merge.js            前后端共享的进度合并与 serverFence
├── scripts/
│   ├── frontend_bundle.py     装配 software/src
│   ├── make_html.py           构建单文件版与 deploy/
│   ├── deploy.py              构建、测试、发布、线上验收
│   └── tools/                 回归、离线与性能测量
├── data/                      词库、词频、审查结果、ECDICT 子集
├── ref/                       真题原件与原词表
└── .github/workflows/ci.yml   Windows CI 门禁
```

`software/template.html` 是装配产物，不是手写入口。`software/sw.js`、`deploy/` 和单文件 HTML 也都是生成物；不要直接编辑或在部署后手工复制覆盖。

## 前端装配

`software/src/app.manifest.json` 固定 12 个 JS 片段的顺序。`scripts/frontend_bundle.py` 把以下内容装入 `software/template.html`：

1. `shell.html` 的 `__KY_STYLES__`、`__KY_APP__` 占位符；
2. `styles.css`；
3. `app/*.js`，按清单顺序在同一经典脚本作用域内拼接。

这是源码布局拆分，不是运行时模块系统；片段中禁止 `import`/`export`，以免改变单文件离线版和首卡行为。修改源后执行：

```powershell
python scripts/frontend_bundle.py --write
python scripts/make_html.py
```

`make_html.py` 还会：

- 把 `shared/merge.js` 注入模板和 Worker 的 `/*__MERGE__*/` 占位符；
- 生成带内容哈希的 `deploy/app.<hash>.js`；
- 生成带内容哈希的四本词库、按字母拆分的详情分片和 `build-meta.json`；
- 生成 `deploy/index.html`、`deploy/sw.js`、`deploy/_worker.js` 与缓存头；
- 通过 `deploy.lock` 互斥、独立暂存目录和目录切换完成原子构建。

## 本地状态

主状态使用 `generation + 64 shard`：

- `ky_words_v1#meta[@account]` 保存当前 generation；
- `ky_words_v1#<generation>-<0..63>[@account]` 保存按词名稳定 hash 分片的记录；
- 单次翻词只重写一个分片；一次完整迁移/导入/清空先写新 generation，最后原子切换 meta，再清理旧 generation；
- 旧 `ky_words_v1` 会迁移到新格式，读取时保留兼容回退。

`ky_pos_v1[@account]` 单独保存每章的小型 `{pos, posWord, t}` 位置记录。翻词不再反复写整份章节队列，刷新后仍优先按 `posWord` 恢复。

其他键包括 `ky_chapter_v1`（队列与位置）、`ky_conf_v1`（牌组/章节/设置）、`ky_daily_v1`（每日学习节奏）和 `ky_stamp_v1`。删除使用墓碑 `{del: 1, t}`，账号数据通过 `@account` 隔离。

## 缓存协议

Service Worker 使用两套缓存：

- `ky-shell-<BUILD_VERSION>`：页面壳、哈希主程序、manifest、图标和四本词库；
- `ky-audio-v2`：中英文音频，规范化 `word/lang/v` 后缓存，最多 8000 条，并有配额保护。

关键语义：

- 导航请求 network-first，3 秒弱网超时后回退缓存；哈希静态资源 cache-first。
- 响应头 `x-ky-cache` 给出 `hit`、`stored` 或 `store-failed`；页面只有收到成功落盘确认后才写“已缓存”标记。
- `x-ky-cache-revision` 与 `x-ky-cache-epoch` 用于丢弃跨标签页乱序到达的旧缓存消息；淘汰通过 `ky:audio-evicted` 通知页面。
- 新 SW 安装时核心壳必须成功，随后 `skipWaiting`/`clients.claim`；激活时删除旧 shell 和旧音频缓存命名空间。页面以 `updateViaCache: 'none'` 注册，并在已有控制器发生替换时刷新。
- 词库和详情使用内容哈希；`/data/*` 与 `/app.*.js` 为长期 immutable，HTML、`sw.js`、`build-meta.json` 不使用旧缓存判断发布结果。

## 同步与 serverFence

合并算法只有一个源：`shared/merge.js`，由构建注入前端和 Worker。普通同步、首次登录、冲突后的 `/api/state/sync` 都走同一套逻辑。

- `clear`/`import` 不靠客户端时间戳强推；Worker 用服务端时间生成单调 `conf.serverFenceAt`，并用 `conf.serverFenceMode` 区分 `clear` 与 `import`。
- 普通 PUT 会先剥掉客户端提供的 fence，再读取云端权威 fence；旧设备不能靠旧时钟复活 fence 之前的记录。
- `clear` 以 `resetAt` 兼容旧数据；`import` 使用独立 import fence 且不留下长期 clear 栅栏。
- 合并结果按稳定键序序列化；D1 `updated_at` 兼作乐观锁版本，避免同毫秒双写和无效轮询。
- 删除墓碑、账号校验、压缩体大小检查和 512KB 上限仍由测试覆盖。

## 构建、测试与发布

```powershell
# 文档/源码一致性
python scripts/frontend_bundle.py --check

# 当前构建门禁
python scripts/make_html.py
python scripts/tools/run_tests.py
python scripts/tools/offline_check.py --json
python scripts/tools/measure_perf.py

# 一条命令完成构建、回归、离线实测、部署和双域名验收
python scripts/deploy.py
```

当前本地实测（2026-10-29）：数据测试 14/14，回归 319/319，离线端到端 20/20。

`run_tests.py` 覆盖源码片段可重建、64 shard、`ky_pos_v1`、导入/清空 generation 切换、serverFence、SW 缓存反馈、40→200 词补全和首卡性能。`offline_check.py` 使用全新临时 Edge profile，实际验证 SW 控制、四本词库、切章、词表、详情、中英文音频及断网重启。

`deploy.py` 的发布门禁：

- `deploy.publish.lock` 互斥；提交和上次成功发布都有 10 分钟冷却，可用 `--allow-recent-release` 显式覆盖；超过 30 分钟才视为残锁；
- 工作区有未提交改动默认拒绝，必须显式 `--allow-dirty-release`；
- `backend/migrations/applied.json` 记录已人工确认的迁移文件 SHA-256；新增或改动迁移而未更新账本时默认拒绝；
- 校验 `build-meta.json` 与 `app.<hash>.js` 内容哈希；
- 部署后同时检查 deployment URL 和 public URL：build-meta、SW 版本/主程序、HTML 引用、主程序字节、全新 Edge 运行时和 `/api/health` 的 D1 查询。

默认不跳过测试；`--skip-test` 只用于明确确认的紧急发布。

## 真实性能基线

2026-10-29 使用 `python scripts/tools/measure_perf.py` 实测。环境为 Windows Edge headless + Playwright，5 个全新 profile，生产等价本地 HTTP，Service Worker 阻止，外部音频替换为本地 WAV。

| 指标 | p50 | p95 |
|---|---:|---:|
| 冷启动 FCP | 244.00 ms | 278.40 ms |
| 冷启动首卡 | 120.00 ms | 154.80 ms |
| DOMContentLoaded | 122.80 ms | 157.82 ms |
| 首屏 DOM | 240 | 240 |
| 40→200 词补全 | 323.60 ms | 370.20 ms |
| 章节切换 | 0.10 ms | 0.46 ms |
| 词表搜索 | 0.65 ms | 1.09 ms |
| 词表分页 | 0.50 ms | 0.70 ms |
| 64 shard 单次写 | 0.00 ms | 0.10 ms |
| 同步快照序列化 | 0.40 ms | 0.77 ms |
| 同步快照 gzip | 2.30 ms | 4.35 ms |

体积与数据：首屏 HTML gzip 11,813 B，主程序 gzip 37,131 B，启动总 gzip 48,944 B；完整 state 175,201 B，最大单分片 2,994 B；2400 条同步快照 182,332 B，gzip 后 14,961 B；本地音频窗口 11 个请求，p50/p95 为 23.15/26.45 ms。

这组数据是桌面 headless 基线，不等同于真实移动设备验收；完整冷/热/离线与 CPU 降速结论应继续用同一脚本和 fresh profile 复跑。

## 发布状态

截至 **2026-10-29 21:11 +08:00**：

- 发布源码提交：`4368766`；`deploy/build-meta.json` 为 build `c18904c08771`、app `./app.4defd52cb022.js`。
- 公共域名 `https://kaoyan2-words.pages.dev/` 与 deployment URL `https://138572ea.kaoyan2-words.pages.dev/` 均已返回 build `c18904c08771`、app `./app.4defd52cb022.js` 和对应 SW。
- 验收已通过：两个域名的 build-meta、SW、HTML、主程序 SHA-256一致，各自全新 Edge profile 运行时通过，`/api/health` 的 D1 查询为 `{"ok":true,"database":true}`。
- 仓库当前没有配置远程；`.github/workflows/ci.yml` 已定义 Windows CI，但本地没有 GitHub Actions 运行记录。不能把“workflow 已提交”说成“托管 CI 已全绿”。

## 数据规则

| 数据 | 来源 | 说明 |
|---|---|---|
| 词频 | 2010–2024 英语二真题 17 套 | 正文、题干、选项统计 lemma 词次 |
| 释义 | 红宝书 2027 版 | 已按“只留核心义”校订 |
| 词形变化 | ECDICT + lemma.en.txt | `data/ecdict_subset.json` 是可复现构建输入 |
| 派生关系 | WordNet derivationally_related_forms | 校验词族归属 |

1. 必须真实出现在真题中。
2. 必须命中考研大纲、红宝书或可靠词表门槛。
3. 排除纯功能词、数词、中学基础词、专有名词和词根碎片。
4. 真题出现 ≥20 次最多保留 2 个义项；少于 20 次只留 1 个核心义。

完整 `data/ecdict.csv` 和 `data/lemma.en.txt` 不属于常规构建必需输入；前者只在重建 ECDICT 子集时需要。

## 主要功能

| 功能 | 说明 |
|---|---|
| 手势 | 左滑认识、右滑不认识、上下滑翻词、点卡翻面 |
| 章节 | 每 200 词一章，按词和 `posWord` 恢复位置 |
| 权重 | 右滑累计权重，洗牌时概率提高 |
| 撤销 | 左滑后 5 秒可撤销，并回滚每日计数 |
| 已掌握 | 单独分区，可恢复 |
| 备份 | JSON 导入/导出，导入/清空使用 generation 原子切换 |
| 账号 | 游客与账号隔离；登录后服务端合并并同步 |
| 离线 | 支持完整词库、词表、详情和中英文音频缓存 |

## 排障与历史

```powershell
git log --oneline
git status
```

回退代码用 `git checkout <commit>`。涉及生成物时，回退后运行 `python scripts/make_html.py`，不要手工修补 `deploy/`。

`scripts/archive/` 中的一次性脚本仅用于追溯历史，路径可能已失效，不要执行。
