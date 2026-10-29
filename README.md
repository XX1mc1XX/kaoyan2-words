# 考研英语二核心词

一个给考研英语二用的背单词应用。数据来自 2010-2024 年英语二真题（17 套）的真实词频统计，不是通用词表。

线上地址：https://kaoyan2-words.pages.dev/

## 目录结构

```
单词/
├── software/           应用源码与产物
│   ├── template.html   单文件前端（数据通过占位符注入）
│   └── 考研核心词.html  打包产物（可直接双击打开，离线可用）
├── scripts/            构建脚本（共 11 个，按执行顺序）
├── data/               数据
│   ├── words.json          阶段一 · 核心词 1342
│   ├── derivatives.json    阶段二 · 核心派生 120（S/A/B/C 四档）
│   ├── basic.json          基础词自测 349
│   ├── insurance.json      保险库 1545
│   ├── ky2_freq.json       英语二真题词频
│   ├── ky1_freq.json       英语一词频（低权重参考）
│   ├── ecdict.csv          词典源数据（77 万条，需单独下载）
│   ├── lemma.en.txt        词形还原表（需单独下载）
│   ├── archive/            历史中间产物（不参与构建）
│   └── reviews/            审查结果
├── ref/                真题原件与红宝书词表
├── output/             调试截图
└── scripts/archive/    已完成使命的一次性脚本（路径已失效，仅留档）
```

## 数据来源

| 数据 | 来源 | 说明 |
|---|---|---|
| 词频 | 2010-2024 英语二真题 17 套 | 提取全文后统计 lemma 级出现次数 |
| 释义 | 红宝书 2027 版（不背单词 App） | 已按「只留核心义」二次加工 |
| 词形变化 | ECDICT + lemma.en.txt | 屈折变化与派生词 |
| 派生关系 | WordNet derivationally_related_forms | 用于校验词族归属 |

### 选词规则

1. 必须在真题里真实出现过
2. 必须在考研大纲词表 / 红宝书 / 柯林斯 3 星以上
3. 排除纯功能词（the/and/that）、数词、中学基础词
4. 排除专有名词（>70% 出现为大写开头）
5. 排除词根碎片（如 `tract`、`voc` 这类不是英文单词的构词成分）

### 释义规则

- 真题出现 ≥ 20 次：最多 2 个义项，且优先不同词性（`approach → 接近、方法`）
- 真题出现 < 20 次：只留 1 个核心义

## 构建流程

完整顺序（从零复现）：

```bash
# 1. 下载真题 PDF 到 ref/ky2/、ref/ky1/
python scripts/fetch_corpus.py

# 2. 统计词频
python scripts/build_freq.py        # -> data/ky2_freq.json
python scripts/build_freq_ky1.py    # -> data/ky1_freq.json

# 3. 构建词库（依赖 data/ 下的校订释义文件，缺失会报错）
python scripts/build_words.py       # -> words.json（需 meanings_*.json）
python scripts/build_derivatives.py # -> derivatives.json（需 derivatives_curated.tsv）
python scripts/build_basic_words.py # -> basic.json
python scripts/build_optional_decks.py  # -> insurance.json

# 4. 打包
python scripts/make_html.py         # -> software/考研核心词.html
python scripts/make_pdf.py          # -> 打印版 PDF（可选）

# 5. 构建、测试、部署、健康检查（推荐，一条命令）
python scripts/deploy.py

# 部署脚本会检查构建/测试返回码、发布锁、迁移门禁、deployment URL 和 /api/health。
# 确认远端迁移已执行后，才能追加 --allow-pending-migrations。
# 不要再把 software\考研核心词.html 复制进 deploy/，那会覆盖按需加载版。```

**只改前端**（不动数据）的话，只需跑第 4、5 步。

构建失败会直接报错退出（包括 terser 压缩失败），不会静默产出未压缩或半成品的产物。
确实要跳过压缩时显式设置 `$env:KY_NO_MINIFY="1"`。

`data/ecdict.csv` 和 `data/lemma.en.txt` 不在仓库里，需要从 [ECDICT](https://github.com/skywind3000/ECDICT) 下载。

`scripts/archive/` 是已完成使命的一次性脚本，内部路径已失效，仅供追溯历史改动，**不要执行**。

`shared/merge.js` 是前后端共用的进度合并实现（含删除墓碑）。`software/template.html` 和
`backend/worker.js` 里只留 `/*__MERGE__*/` 占位符，由 `make_html.py` 在构建时注入——
**改合并逻辑只改 shared/merge.js，不要在两边各写一份**。

数据库结构变更放在 `backend/migrations/`，部署前手工执行一次，例如：

```powershell
npx wrangler d1 execute kaoyan2-users --remote --file backend/migrations/002_username_nocase.sql
```

回归测试跑的是构建产物，先构建再测：

```powershell
python scripts/make_html.py
python scripts/tools/run_tests.py
```


## 应用功能

| 功能 | 说明 |
|---|---|
| 手势 | 左滑=认识（7 天后复习）、右滑=不认识（权重+1）、上下滑翻词、点卡片翻面 |
| 章节 | 每 200 词一章，进度按「词」记录而非下标，切换章节不丢 |
| 权重 | 右滑次数记在卡片左上角，洗牌时权重越高越可能排前面（概率性，不强制置顶） |
| 撤销 | 左滑后 5 秒内可撤销 |
| 已掌握 | 词表页单独分区，可恢复 |
| 备份 | 统计页支持导出/导入进度 JSON |
| 图标 | 统计页可切换 5 个内置图标或上传自定义图片，立即应用到左上角和浏览器标签页 |

状态全部存在浏览器 localStorage：
- `ky_words_v1` — 每词状态 `{w: 权重, mastered: 已掌握, due: 到期时间, seen: 次数}`；
  删除写成墓碑 `{del: 1, t: 删除时间}`，「清空 / 导入」也靠它同步，不靠时间戳压制云端
- `ky_chapter_v1` — 每章的队列顺序与位置（同样支持墓碑）
- `ky_conf_v1` — 当前词库、当前章节、显示/朗读设置与自定义图标
- `ky_daily_v1` — 每日过卡次数与新掌握数，每条带 `t`，撤销减掉的计数不会被合并「取大」复活

## 版本历史

用 git 管理，每个改动都有提交记录，效果不好可以回退：

```bash
git log --oneline        # 看历史
git checkout <commit>    # 回退到某个版本
```

## 发音、离线与性能

- 已预加载的真人发音直接秒播；新词首次先用系统语音立即发声，同时后台缓存真人音频，之后可秒播并离线重播。
- 网页首屏只内嵌几十个词，其余词库拆成带哈希的独立 JSON 并由 Service Worker 后台预缓存；首次打开不再等待 3364 个词全部下载。单文件版仍内嵌全部词库，双击即可完整离线使用。
- 听过的词以及后续 3 个词会由 Service Worker 缓存发音，之后离线也能重播。
- 首次通过 HTTPS 打开后，页面、词库与图标会进入离线缓存；之后断网仍可学习和记录进度。
- `file://` 直接打开的单文件版本原本就支持离线学习；局域网 HTTP 无法启用 Service Worker，需要 HTTPS 才有完整离线能力。
- 登录账号会缓存在本机，离线打开时仍使用该账号自己的进度；联网后再校验会话并同步。
- 账号同步采用单请求快路径：本地有改动时直接 PUT，首次登录由服务端一次完成合并，轮询用 `since` 只检查版本；较大的上传会自动 gzip 压缩。
- 词表首屏只渲染 100 条，滚动/点击“显示更多”继续加载，避免移动端一次创建上千个 DOM 节点。
- `python scripts/make_html.py` 会同时生成完整的 `software/考研核心词.html` 和按需加载的 `deploy/index.html`，并在 `deploy/data/` 生成带内容哈希的词库分片，同时复制 `sw.js`、PWA 图标和最新 Worker，部署时不需要再手工复制。
