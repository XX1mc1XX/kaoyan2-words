# 单词项目执行方案（方向与约束）

> 日期：2026-10-29。本文只定义方向、性能目标和不可破坏的行为，不定义任务顺序。
>
> 任务状态与验收入口：[PHASES.md](./PHASES.md)
> 当前架构：[ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md)
> 产品/构建总览：[README.md](../README.md)

## 1. 总方向

保持现有 Web/PWA 产品形态，在不重写客户端的前提下优化启动、滑动、章节切换、离线、音频和同步。

当前已落地的主线是：

- 前端源码拆进 `software/src/`，由 `scripts/frontend_bundle.py` 装配成经典顶层脚本；
- 首屏只内联 40 词，第一章仍按 200 词补全；
- 主状态改为 generation + 64 shard，位置独立为 `ky_pos_v1`；
- Service Worker 用明确的缓存状态/修订/epoch 协议保证页面标记和实际缓存一致；
- `shared/merge.js` 统一前后端合并，Worker 生成并维护 `serverFence`；
- 构建锁、CI、离线实测、性能基线、发布锁和双域名线上验收已接入。

## 2. 不转 C++/Qt

当前瓶颈主要在浏览器数据流、状态写入、缓存和同步，不在 JavaScript 语言本身。重写为 C++/Qt 会新增：

- Windows/macOS/Android/iOS 的打包、签名、升级和审核；
- Web 与 Qt 两套 UI、缓存、离线、账号和同步实现；
- 与 Cloudflare Pages、Worker、D1 的重新接入；
- 现有 PWA 获客和免安装能力的丢失。

只有同时满足以下条件，才把 Qt/C++ 作为**独立增强客户端**评估：

1. 存在系统级划词、托盘常驻、超大本地词库或严格帧率/内存控制等桌面专属需求；
2. 真实性能数据证明 Web 端无法通过算法、存储或缓存优化解决；
3. 后端 API、D1 和同步契约稳定；
4. 有独立客户端团队和长期维护预算；
5. 接受 Web 与桌面两端并行维护。

即使满足，也不把整个 Web 项目重写成 Qt；优先复用现有 Worker API/D1，Qt 仅做独立客户端。

## 3. 性能目标

### 3.1 用户可感知预算

| 指标 | 目标 | 当前实测（2026-10-29） |
|---|---:|---:|
| 冷启动首卡 p50 | <800 ms | 128 ms |
| 冷启动首卡 p95 | <800 ms | 167.6 ms |
| 首屏 DOM | <400 | 240 |
| 首屏 HTML gzip | <20 KB | 11.8 KB |
| 关键 JS gzip | <45 KB | 36.5 KB |
| 章节切换 p95 | <300 ms | 0.46 ms |
| 搜索 p95 | 无可见卡顿 | 1.58 ms |
| 词表分页 p95 | 无可见卡顿 | 1.25 ms |
| 同步快照 gzip p95 | 不进入交互热路径 | 4.52 ms |
| 静态请求 D1 查询 | 0 | 0 |

当前数据来自生产等价临时构建、Windows Edge headless、5 个全新 profile、本地 HTTP、SW 禁用和本地 WAV。它证明桌面基线，不替代移动真机/CPU 降速验收。

### 3.2 测量要求

- 必须使用生产构建，不能拿开发模式、旧缓存页面或单次最快值下结论。
- 冷启动使用全新 `--user-data-dir`；离线用真实 SW + Cache Storage。
- 记录 p50/p95、字节数、请求数和关键行为结果。
- 性能退化超过 5% 时先回滚或解释清楚，再考虑合并。
- 算法、存储、缓存优化优先于框架替换。

## 4. 已采用的优化

1. **存储止血**：主 state 64 shard；每次翻词只更新一个分片；位置走 `ky_pos_v1`。
2. **启动控制**：网页只内联 40 词；主程序独立 defer 下载；完整词库由 SW 后台预取。
3. **首章恢复**：`fillDeckInBackground`、`pendingSeek`、`chapterExpectedLength` 共同保证 40→200 和上次词恢复。
4. **详情按需**：按首字母内容哈希分片，失败不缓存空结果。
5. **音频离线**：规范化缓存键、单飞请求、配额淘汰、页面 marker 由实际缓存确认头驱动。
6. **同步收敛**：服务端合并、稳定序列化、乐观锁、删除墓碑、持久 serverFence。
7. **交付可复现**：固定工具链、source digest、app/build 哈希、构建锁、发布锁和 fresh Edge 线上验收。

不再把“拆成 ES module/TypeScript/React”作为默认目标；如果未来要做，必须先有测试缝、性能数据和明确的回滚方案。

## 5. 不可破坏的不变量

- 网页首屏最多内联 40 词，章节大小为 200。
- 第一章 200 词只使用现有 `fillDeckInBackground` + `pendingSeek` + `chapterExpectedLength`；不得写第二套补全。
- 上次学习位置优先按 `posWord`，词丢失才用 `pos`，不得先显示第一词再跳。
- `software/template.html` 是装配产物；手写源在 `software/src/`，不得成为两份独立实现。
- `shared/merge.js` 是合并唯一来源；页面和 Worker 不得各有一份漂移算法。
- SW 页面标记只接受 `x-ky-cache=stored|hit`；`store-failed` 不能当成功。
- 静态词库不经过 D1；API 404/错误不得被 SW 伪造成成功响应。
- 清空/导入必须保留 serverFence 语义和并发新学习；客户端不得用旧时钟覆盖服务端 fence。
- 旧 Service Worker 不能用于线上结论；发布验收必须使用全新 Edge profile。
- 生成物、归档、测试数据和源文件不能混写。

## 6. 执行门禁

### 6.1 开工

```powershell
git status
git log --oneline -3
Get-Item software/src/app.manifest.json, software/template.html | Select-Object LastWriteTime
python scripts/frontend_bundle.py --check
python scripts/tools/run_tests.py
```

- 发现非本任务的改动，记录并避开，不覆盖、不回滚。
- 前端源 `software/src/`、shell/styles 和生成 `template.html` 视为同一写域，同一时间只允许一个会话修改。
- 不并行修改 `shared/merge.js`、D1 迁移和生产部署。
- 文档、工作区或文件所有权冲突时停手报告，不另造第五份计划。

### 6.2 改完

```powershell
python scripts/frontend_bundle.py --check
python scripts/make_html.py
python scripts/tools/run_tests.py
python scripts/tools/offline_check.py --json
python scripts/tools/measure_perf.py
```

当前基准：数据测试 14/14、回归 318/318、离线 20/20。没有实际命令和退出码，不能写“完成”。

### 6.3 发布

```powershell
python scripts/deploy.py
```

发布前确认最近 10 分钟无人提交或部署；一轮改动只部署一次。`deploy.py` 会执行构建、测试、离线实测、发布锁、迁移门禁、deployment URL 和 public URL 验收；部署后若只看到“上传成功”而没有双域名 + fresh Edge + health 结果，不能判定上线。

## 7. 提交与验收证据

每次改动至少记录：

- 改动目标和文件；
- 功能/回归结果与命令；
- 性能前后 p50/p95、字节数或请求数；
- 对首屏、滑动、离线、同步的影响；
- 回滚方法；
- 发布版本 `app.<hash>.js` 和 build hash（如果涉及发布）。

性能模板：

```text
场景：冷启动 / 热启动 / 离线 / 滑动 / 详情 / 音频 / 同步
环境：设备、Edge 版本、CPU 降速、缓存状态
前：p50=... p95=... DOM=... 请求数=... 字节=...
后：p50=... p95=... DOM=... 请求数=... 字节=...
结论：通过 / 回滚
功能测试：<current>/<total>
```

## 8. 当前发布事实

截至 2026-10-29 20:41 +08:00：

- HEAD：`2d2eaa5b6f9db8879a20447edee3cbe2eb655a09`；
- 本地构建：build `76060d85d857`，app `./app.4defd52cb022.js`；
- 公共域名在本轮部署前仍返回旧 app `./app.9775dd28fffb.js`、SW `4e120f40cd87`；
- 公共 `/build-meta.json` 未返回有效 JSON，健康检查正常；
- 因此候选 build `76060d85d857` 尚未确认上线；发布后必须写回双域名实际结果。

下一次发布必须让 `deploy.py` 的 deployment URL + public URL 双域名验收全部通过，并在提交信息中记录对应 `app.<hash>.js`。
