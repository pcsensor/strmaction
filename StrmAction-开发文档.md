# StrmAction 开发文档（v0.7 / 可交付给开发 Agent）

> **文档状态**：设计已定稿，可直接进入实现
> **读者**：负责实现本项目的 AI Agent / 开发者
> **实现语言**：后端 Python 3.11+，前端 TypeScript
> **交付形态**：单容器自托管 Web 应用 + Android 伴侣 App（**v1 必做**）

### 变更记录

| 版本 | 变更 |
|---|---|
| v0.1 | 初版设计 |
| **v0.2** | **决策：彻底舍弃 Jellyfin**。StrmAction 成为唯一的媒体库与元数据来源，刮削完全自建；移除「从 Jellyfin 导入元数据」的所有设计；新增元数据刷新、字段手动编辑、观看状态管理 |
| **v0.3** | **决策：新增 TVDB（v4 API）作为第二元数据源**。补齐动漫、日剧、欧美剧的覆盖；TMDB 仍为默认主源，双源可配优先级与降级链；新增跨源 ID 映射与去重规则；伴侣 App 说明补全 |
| **v0.4** | **修正进度回传设计**：进度不再依赖 10 分钟过期的 `play_session.token`（长片必然失败），改为登录会话鉴权的 `POST /api/items/{id}/progress`；补充进度粒度矩阵、`resume_ms` 续播、自动连播 |
| **v0.5** | 新增**附录 C：功能总览**（61 项功能，按模块列出优先级与章节号）+ 工作量汇总表，可直接作为验收清单 |
| **v0.6** | **D1 决策：伴侣 App 纳入 v1**（电视端一等公民）；**D3 决策：不做多语言 UI**，界面仅中文（文案集中管理，预留 i18n 可能性）；里程碑与工作量据此更新 |
| **v0.7** | 新增**附录 D：M2 刮削实现细则**（Provider 接口、双源映射、打分、季集对齐、图片队列、错误分类）与**附录 E：M6 伴侣 App 实现细则**（WebView、JS 桥、拉起 mpv 的 6 个坑、结果幂等、TV 适配）。至此文档可支撑「不看代码即可开工」 |

---

## 0. 一句话定义

**StrmAction 是一个面向 `.strm` 媒体库的「刮削 + 展示 + 播放分发」Web 应用**：它扫描 SmartStrm 生成的 `.strm` 目录，用 TMDB + TVDB 刮削元数据，提供一个 VidHub/SenPlayer 级别的浏览界面，并在用户点播放时，把该集对应的 `.strm` 里的 URL **交给外部播放器（mpv）直接播放**。

它**不转码、不代理视频流、不碰网盘鉴权**——这三件事分别由播放器、SmartStrm、Alist 负责。

---

## 1. 背景：为什么需要它

现有链路（Jellyfin + SmartStrm + Alist + 百度网盘 + 302）存在一个死结：

| 环节 | 问题 |
|---|---|
| Jellyfin 客户端直接播 | 请求走 Jellyfin 的 `/Videos/{id}/stream`，由**服务器**去拉百度，UA 是 Jellyfin 的 → 403；即便成功也吃服务器带宽 |
| Caddy 改 UA | 302 之后 Caddy 已不在链路上，物理无效 |
| Jellyfin 外部播放器 | ATV 实现会**跳过 PlaybackInfo**，自己拼 `/Videos/{id}/stream?static=true` 交给 mpv；而 mpv 的 UA 是全局的，无法既满足 SmartStrm 又满足百度 |
| Alist 中转 | 吃服务器带宽（明确排除） |

**StrmAction 的价值主张**：把「播放」从 Jellyfin 里彻底剥离。

```
SmartStrm 生成 .strm（内容 = 网盘解析地址）
        │
        ▼
StrmAction 扫描目录 → 解析命名 → TMDB 刮削 → 入库
        │
        ▼
用户在 Web 界面浏览（手机/平板/电脑/TV 浏览器）
        │  点击播放
        ▼
StrmAction 把 .strm 里的 URL 交给 mpv
        │
        ▼
mpv ──(302)──► Alist ──(302)──► 百度 CDN     ← 全程不经过 StrmAction
```

这样：
- **UA 由 mpv 负责**（`mpv.conf` 里全局设 `User-Agent: pan.baidu.com` 即可，因为 mpv 只会访问 strm 主机和网盘，不再需要区分域名）
- **零中转**、**零服务器带宽**、**零转码**
- 元数据、封面、剧集组织全部由 StrmAction 自己掌握

> **v0.2 决策（重要）**：本项目**彻底舍弃 Jellyfin**。
> StrmAction 是媒体库的**唯一**数据源与展示层——元数据刮削、图片缓存、剧集组织、播放进度、观看状态全部由它自己负责。
> 实现时**不得**引入任何 Jellyfin / Emby 的 API 依赖、配置项或迁移逻辑；旧版本的「从 Jellyfin 导入元数据」设计已删除。

**舍弃 Jellyfin 后需要自己补齐的能力**（这些原本由 Jellyfin 提供，现在都是 StrmAction 的必修项）：

| 能力 | 归属 | 说明 |
|---|---|---|
| 元数据刮削 | §10 | TMDB 为唯一主源 |
| 图片下载/缓存/取色 | §11 | 海报、背景、剧照、头像 |
| 手动修正与字段编辑 | §10.7 | 自动匹配必然有错，没有修正入口就不可用 |
| 元数据刷新 | §10.6 | TMDB 数据更新后能重新拉取 |
| 播放进度 / 已看状态 | §7、§13 | `play_progress` |
| 缺失元数据的降级展示 | §14.2 | 用文件名优雅兜底，不出现「无标题」空白卡 |

---

## 2. 产品目标 / 非目标

### 2.1 目标（MUST）

1. 管理多个「识别目录」，每个目录对应一个媒体库，可选择类型：**电影 / 电视剧 / 家庭视频 / 课程**。
2. 扫描目录，识别 `.strm` 文件，按文件夹名、文件名、年份、季集号解析出结构。
3. 调用 TMDB 刮削元数据（标题、简介、年份、评分、类型、演职员、海报、背景图、预告片）。
4. 提供**手动匹配修正**：自动匹配失败或匹配错误时，管理员可搜索并重新绑定。
5. 提供优雅的浏览界面：轮播首页、详情页、选集、搜索、继续观看。
6. 点播放 → 把 `.strm` 内容的 URL 交给外部播放器（Android 用 `intent://` 拉起 mpv，桌面用进程/IPC，兜底为复制链接）。
7. 单管理员账号登录，全站需鉴权。
8. **独立完整**：不依赖 Jellyfin / Emby / Plex 等任何媒体服务器，单容器即可提供完整媒体库体验。
9. **元数据可维护**：支持重新刮削、单条刷新、手动编辑字段、手动绑定，保证库可以长期演进。
10. **电视一等公民**：提供 Android 伴侣 App，使 Android TV 上可一键拉起 mpv、断点续播、自动连播（见 §12.6）。
11. **中文优先**：界面文案仅中文，不实现多语言切换；但所有文案集中在一个常量文件，便于日后扩展。

### 2.2 非目标（MUST NOT）

- ❌ 不做视频转码
- ❌ 不做视频流中转/反代/缓存
- ❌ 不实现网盘登录、不做 Alist 的替代
- ❌ **不依赖、不读取、不迁移任何 Jellyfin / Emby / Plex 的数据**（本项目是替代品，不是外挂）
- ❌ 不做多用户/权限体系（仅单管理员）
- ❌ 不做弹幕、评论、社交
- ❌ 不内置播放器（不内嵌 video 标签播视频流）
- ❌ 不做多语言 UI（v1 仅中文；元数据语言可配，那是数据层不是 UI）
- ❌ 不做 iOS / tvOS 伴侣 App（iOS 端直接用浏览器方案）

> 若后续需要「内嵌播放」，属于独立版本，需重新评估（会引入中转）。

---

## 3. 术语

| 术语 | 含义 |
|---|---|
| 识别目录（Library） | 一个被扫描的根目录，对应一个媒体库 |
| 条目（Item） | 一部电影 / 一部剧 / 一季 / 一集 / 一个家庭视频，统一建模 |
| 媒体文件（MediaFile） | 一个 `.strm` 文件，含路径与其内容 URL |
| 播放会话（PlaySession） | 一次播放请求，生成一次性 token，供播放器回传进度 |
| 播放适配器（PlayerAdapter） | 把 URL 交给播放器的实现，可插拔 |

---

## 4. 总体架构

```
┌────────────────────────────────────────────────────────────┐
│                     浏览器（手机 / 桌面 / TV）                │
│   React SPA（静态资源由后端托管）                              │
└───────────────┬────────────────────────────┬───────────────┘
                │ REST /api/*                │ intent:// 或 HTTP
                ▼                            ▼
┌──────────────────────────────┐    ┌──────────────────────┐
│  StrmAction 后端（FastAPI）   │    │  mpv-android (is.xyz.mpv) │
│  ├─ API 层                   │    └──────────────────────┘
│  ├─ 扫描器 Scanner           │              ▲
│  ├─ 解析器 Parser            │              │ 或
│  ├─ 刮削器 Scraper (TMDB)    │    ┌──────────────────────┐
│  ├─ 播放分发 PlayerDispatcher│───►│  桌面 mpv（spawn/IPC） │
│  └─ 任务调度 Scheduler       │    └──────────────────────┘
└──────────┬───────────────────┘
           │
     ┌─────▼──────┐        ┌──────────────┐
     │  SQLite    │        │  本地图片缓存 │
     └────────────┘        └──────────────┘
           ▲
           │ 只读扫描（挂载为卷）
     ┌─────┴───────────────────────────────┐
     │  /media/strm  ← SmartStrm 生成目录     │
     └─────────────────────────────────────┘
```

**关键约束**：后端对视频数据**永不发起请求**。它只读取 `.strm` 的文本内容，以及下载海报/背景图。

---

## 5. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI | `guessit` 是现有最好的文件名解析库（Python 生态）；异步 IO 适合大量刮削请求 |
| ORM | SQLModel（SQLAlchemy 2.x） | 类型友好，迁移轻量 |
| DB | SQLite（WAL） | 单用户场景足够，零运维；十万级条目无压力 |
| 爬取 | httpx + tenacity | 异步 + 重试 |
| 文件名解析 | 自定义规则链 + `guessit` 兜底 | 中文目录名 guessit 有时不准，需要模板优先 |
| 图片 | Pillow | 生成多尺寸缩略图、提取主题色 |
| 调度 | APScheduler | 定时增量扫描 |
| 前端 | React 18 + TypeScript + Vite | 生态成熟 |
| 样式 | Tailwind CSS + CSS Variables | 主题色动态注入 |
| 动画 | Framer Motion | 轮播、转场、手势 |
| 数据层 | TanStack Query | 缓存、预取、失效 |
| 状态 | Zustand | 轻量全局状态（播放器设置、主题） |
| 部署 | Docker 单容器（后端托管前端静态产物） | 一条 `docker run` 起服务 |

> 若开发 Agent 更熟悉 Node.js，允许替换为 NestJS/Fastify，但**必须自行实现中文文件名解析规则**，并保证 `guessit` 那部分行为等价。

---

## 6. 目录结构

```
strmaction/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                 # FastAPI 入口 + 静态托管
│  │  ├─ config.py               # 配置加载（DB > yaml > 默认）
│  │  ├─ db.py                   # engine / session
│  │  ├─ models.py               # SQLModel 表定义
│  │  ├─ schemas.py              # Pydantic 出入参
│  │  ├─ deps.py                 # 鉴权依赖
│  │  ├─ api/
│  │  │  ├─ auth.py
│  │  │  ├─ libraries.py
│  │  │  ├─ items.py
│  │  │  ├─ search.py
│  │  │  ├─ play.py
│  │  │  └─ admin.py             # 任务、日志、匹配修正
│  │  ├─ scanner/
│  │  │  ├─ walker.py            # 目录遍历 + 增量
│  │  │  └─ sync.py              # 入库 / 软删除 / 移动归并
│  │  ├─ parser/
│  │  │  ├─ rules.py             # 目录模板 + 正则规则
│  │  │  ├─ guess.py             # guessit 兜底
│  │  │  └─ types.py             # Parsed 数据类
│  │  ├─ scraper/
│  │  │  ├─ base.py              # MetadataProvider 接口 + CanonicalMeta
│  │  │  ├─ tmdb.py              # 附录 D.2
│  │  │  ├─ tvdb.py              # 附录 D.3
│  │  │  ├─ nfo.py               # 本地 .nfo（可选）
│  │  │  ├─ matcher.py           # 归一化 + 打分（D.4）
│  │  │  └─ merge.py             # 跨源补空（D.5.1）
│  │  ├─ images.py               # 下载队列、转码、取色（D.7）
│  │  ├─ players/
│  │  │  ├─ base.py
│  │  │  ├─ web_intent.py
│  │  │  ├─ mpv_ipc.py
│  │  │  └─ clipboard.py
│  │  └─ jobs.py                 # APScheduler 任务
│  └─ pyproject.toml
├─ frontend/
│  ├─ src/
│  │  ├─ pages/                  # Home / Detail / Search / Settings / Tasks
│  │  ├─ components/             # HeroCarousel / PosterCard / EpisodeList ...
│  │  ├─ i18n/zh-CN.ts           # 全部界面文案（唯一来源，不许散落组件）
│  │  ├─ api/                    # client.ts / hooks.ts
│  │  ├─ store/
│  │  └─ styles/
│  └─ vite.config.ts
├─ companion/                    # Android 伴侣 App（M6，见附录 E）
│  └─ app/src/main/java/top/strmaction/companion/
│     ├─ MainActivity.kt
│     ├─ JsBridge.kt
│     └─ MpvLauncher.kt
├─ Dockerfile
└─ config.example.yaml
```

---

## 7. 数据模型

SQLite DDL（实现可用 SQLModel 生成，字段等价即可）：

```sql
CREATE TABLE library (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  root_path     TEXT NOT NULL UNIQUE,      -- 容器内绝对路径
  type          TEXT NOT NULL,             -- movie | tv | home | course
  provider      TEXT NOT NULL DEFAULT 'tmdb',
  language      TEXT NOT NULL DEFAULT 'zh-CN',
  scan_cron     TEXT,                      -- 空 = 仅手动
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  last_scan_at  TEXT
);

CREATE TABLE item (
  id            INTEGER PRIMARY KEY,
  library_id    INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
  parent_id     INTEGER REFERENCES item(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL,             -- movie | series | season | episode | video
  title         TEXT NOT NULL,
  original_title TEXT,
  sort_title    TEXT,
  year          INTEGER,
  season_no     INTEGER,
  episode_no    INTEGER,
  overview      TEXT,
  tagline       TEXT,
  runtime_min   INTEGER,
  rating        REAL,
  provider      TEXT,                      -- 最终采用的源：tmdb | tvdb | nfo | none
  provider_id   TEXT,                      -- 该源的 id
  external_ids  TEXT,                      -- JSON: {"tmdb":603,"tvdb":12345,"imdb":"tt0133093"}
  genres        TEXT,                      -- JSON array
  cast          TEXT,                      -- JSON array (name, role, avatar)
  certification TEXT,                      -- PG-13 / TV-MA
  alt_titles    TEXT,                      -- JSON array，别名（搜索用）
  trailer_key   TEXT,                      -- YouTube key
  collection    TEXT,                      -- JSON {id,name}，所属合集
  poster_path   TEXT,
  backdrop_path TEXT,
  logo_path     TEXT,
  still_path    TEXT,                      -- 剧集单集剧照
  color_primary TEXT,                      -- #RRGGBB，取自 backdrop
  locked_fields TEXT,                      -- JSON array，手动锁定的字段名
  meta_hash     TEXT,                      -- payload sha1，用于跳过无变更刷新
  match_state   TEXT NOT NULL DEFAULT 'pending', -- pending|auto|manual|failed|skipped
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE INDEX idx_item_parent ON item(parent_id);
CREATE INDEX idx_item_lib_kind ON item(library_id, kind);
CREATE INDEX idx_item_title ON item(sort_title);

CREATE TABLE media_file (
  id            INTEGER PRIMARY KEY,
  item_id       INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  library_id    INTEGER NOT NULL,
  rel_path      TEXT NOT NULL,
  abs_path      TEXT NOT NULL,
  url           TEXT NOT NULL,             -- .strm 文件内容（首行）
  size_bytes    INTEGER,
  mtime         INTEGER,
  missing       INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX uq_media_abs ON media_file(abs_path);
CREATE INDEX idx_media_item ON media_file(item_id);

CREATE TABLE play_progress (
  id            INTEGER PRIMARY KEY,
  item_id       INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  position_ms   INTEGER NOT NULL,
  duration_ms   INTEGER,
  finished      INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX uq_progress_item ON play_progress(item_id);

CREATE TABLE play_session (
  token         TEXT PRIMARY KEY,
  item_id       INTEGER NOT NULL,
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,             -- 24h；仅用于播放 URL 下发，与进度无关
  consumed      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE task_log (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL,             -- scan | scrape | image
  library_id    INTEGER,
  status        TEXT NOT NULL,             -- running | success | failed
  message       TEXT,
  stats         TEXT,                       -- JSON
  started_at    TEXT NOT NULL,
  finished_at   TEXT
);

CREATE TABLE scrape_cache (
  id            INTEGER PRIMARY KEY,
  provider      TEXT NOT NULL,             -- tmdb | tvdb
  query_hash    TEXT NOT NULL,             -- sha1(provider+kind+query+year+lang)
  payload       TEXT NOT NULL,             -- 原始 JSON（压缩可选）
  expires_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX uq_scrape_cache ON scrape_cache(provider, query_hash);

CREATE TABLE provider_token (
  provider      TEXT PRIMARY KEY,          -- tvdb（TMDB 无状态，不需要）
  token         TEXT NOT NULL,
  expires_at    TEXT,
  updated_at    TEXT NOT NULL
);
```

**设计说明**

- 用单表 `item` + 自引用 `parent_id` 表达 剧→季→集，避免三套表。
- `media_file.url` 存 `.strm` 的**原始内容**；不缓存网盘直链（会过期），播放时直接用这个解析地址。
- `match_state` 是 UI 的核心状态：`failed` 的条目必须在首页有入口提示管理员修正。
- `item.external_ids` 让两个源可以互相定位；**季集结构一旦选定 winning provider 就不得混用**。

---

## 8. 识别目录与扫描

### 8.1 目录类型行为

| 类型 | 结构假设 | 刮削 |
|---|---|---|
| `movie` | 每个子目录 = 一部电影（或根下每个 `.strm` = 一部） | 按 `provider_priority.movie` 链（默认 TMDB → TVDB） |
| `tv` | `剧名/Season XX/剧名 - SxxExx.strm` 或 `剧名/Sxx/...` | 按 `provider_priority.tv` 链；动漫库建议 `[tvdb, tmdb]` |
| `home` | 按目录树分组，不刮削 | 仅本地：目录名 = 分组名，文件名 = 标题 |
| `course` | 同 `home`，但按「课程 → 章节」展示 | 仅本地，可手工填封面/简介 |

### 8.2 扫描策略（MUST）

1. **增量**：遍历时记录 `(abs_path, mtime, size)`；三者均未变则跳过解析与刮削。
2. **删除**：已入库但本次未遍历到的文件，标记 `missing=1`，不物理删除；连续 3 次缺失才软删除条目（保留 7 天）。
3. **移动/改名**：若内容 URL 相同（同一条目），更新路径而不是新建条目。
4. **忽略规则**：跳过 `@eaDir`、`.DS_Store`、`#recycle`、`*.tmp` 等；可通过配置追加。
5. **并发**：遍历单线程（IO 密集，但目录可能很大）；刮削并发 4。
6. **安全**：解析符号链接时限制在 `root_path` 内，防止越权读取。

### 8.3 `.strm` 读取规则（MUST）

- 读取文件**首行**，`strip()` 后作为 URL。
- 必须以 `http://` 或 `https://` 开头；否则标记 `invalid`，不参与播放。
- 内容以 `#` 开头的行视为注释跳过。
- 文件编码按 UTF-8 with BOM 兼容处理。
- **禁止**在后端对 URL 发起任何请求（不探测、不校验可达性）。

---

## 9. 命名解析（重点）

### 9.1 两级策略

1. **模板优先**：管理员可在库设置里填写目录模板（默认给 SmartStrm 的常见输出）。例如电影库：
   ```
   {title} ({year})/{title} ({year}).strm
   ```
   电视剧库：
   ```
   {title} ({year})/Season {season:02d}/{title} - S{season:02d}E{episode:02d}.strm
   ```
   模板用命名捕获组编译成正则，命中即用，置信度最高。

2. **guessit 兜底**：模板不命中时，对**文件名**和**父目录名**分别跑 `guessit`，取 `title/year/season/episode`。

### 9.2 必须支持的写法（测试用例见 §18）

- `流浪地球2 (2023)` / `流浪地球2.2023.2160p.WEB-DL`
- `三体 (2023)/Season 01/三体 - S01E01.strm`
- `三体/第一季/第01集.strm`、`三体/01.strm`、`三体/EP01.strm`
- `Some.Show.S01E01.1080p.WEB-DL.strm`
- 多版本：`电影 (2023) - 2160p.strm` 与 `电影 (2023) - 1080p.strm` → **同一条目下的两个 media_file**，UI 上做「版本」下拉
- 分段：`CD1/CD2` 或 `-part1/part2` → 合并为一个 media_file 序列
- 中文全角括号 `（）`、书名号、空格与下划线混排

### 9.3 输出结构

```python
@dataclass
class Parsed:
    kind: Literal["movie", "series", "episode", "video"]
    title: str
    year: int | None
    season: int | None
    episode: int | None
    confidence: float          # 0..1
    raw_name: str
```

`confidence < 0.5` 的条目直接进 `match_state='failed'`。

---

## 10. 刮削子系统

### 10.1 刮削来源（v0.3 已定）

**Jellyfin 已舍弃，StrmAction 自己做刮削。** 因此刮削子系统是本项目的核心模块，不是附属功能。

Jellyfin / Emby 的刮削器是内嵌的 C# 实现，**不是可独立调用的库**，所以「调用 Jellyfin 的刮削工具」在工程上不成立。业界通用做法是直接对接元数据源官方 API，本项目采用**双源**：

| 优先级 | 来源 | 用途 | 是否必须 |
|---|---|---|---|
| 1 | **本地 `.nfo`**（若同目录存在） | 完全接管元数据（兼容 tinyMediaManager / Kodi 标准 NFO），命中则不再请求任何在线源 | 可选 |
| 2 | **TMDB API v3**（默认主源） | 电影/剧集主力：中文标题、简介、演职员、图片、预告片、合集 | **必须** |
| 3 | **TVDB v4 API**（第二源） | 补齐 TMDB 覆盖弱的场景：**动漫、日剧、欧美剧的季集结构与集标题**；也可作为独立主源 | **必须** |
| 4 | **文件名兜底解析** | 所有在线源不可达或匹配失败时，用 §9 的解析结果做最小展示 | **必须** |

**为什么要双源**（写进 README，避免用户困惑）：

- TMDB 的**中文标题与电影资料**更强，但**日剧/动漫的季集划分**经常与发布组不一致（例如把 24 集拆成 2 季）。
- TVDB 的**季集结构**（aired order / absolute order）更贴近发布组，动漫尤其明显；但中文标题与简介较弱。
- 因此默认策略：**电影用 TMDB，剧集先 TMDB、季集结构可回退 TVDB**；每部作品记录最终采用的 provider，UI 上可显示来源。

> 实现要求：抽象 `MetadataProvider` 接口，`NfoProvider` / `TmdbProvider` / `TvdbProvider` 均实现它。
> **不要**为 Jellyfin/Emby 写任何 provider。

**Provider 选择优先级**（每库可配，见 §15）：

```yaml
scraper:
  provider_priority:        # 默认
    movie:  [tmdb, tvdb]
    tv:     [tmdb, tvdb]    # 动漫库改成 [tvdb, tmdb]
    home:   []
    course: []
```

实现规则：按优先级**依次尝试**，第一个得分达标的源即为 `winning_provider`；后续只在字段缺失时做“补全合并”（见 §10.2.3）。

### 10.2 匹配流程（MUST）

#### 10.2.1 主流程（按 provider 优先级链）

```
解析结果 (title, year, kind)
   │
   ├─ ① 有显式 ID 提示（NFO，或文件夹名带 {tmdb-12345} / {tvdb-67890} / {imdb-tt1234567}）
   │     → 直接用对应 provider 拉详情，跳过搜索
   │
   └─ ② 无 → 按 provider_priority 依次搜索
        for provider in priority[kind]:
            candidates = provider.search(title, year, kind)
            best = max(candidates, key=score)
            if best.score >= threshold:        # 默认 0.75
                winning_provider = provider
                break
        else:
            match_state = 'failed'             # 等人工
   │
   ├─ ③ 拉详情 + 图片（winning_provider）
   ├─ ④ 尝试用跨源 ID 补齐另一源的数据（仅补空字段，见 10.2.3）
   └─ ⑤ 写库，记录 provider / provider_id / external_ids
```

#### 10.2.2 打分公式（两个 provider 统一）

```
score = 0.55 * title_sim
      + 0.25 * year_score          # 完全一致 1.0；±1 年 0.7；缺失 0.5；其他 0
      + 0.10 * popularity_norm     # 归一化到 0..1
      + 0.10 * alias_hit           # 命中别名/原名 = 1.0
```

**标题相似度**：先归一化（去标点、全角转半角、繁简统一、去 `第X季`/`Season X`/`篇`/`剧场版`），再用 `rapidfuzz.WRatio`（区间 0..1）。

**剧集额外规则**：

- 若库内已存在同名 `series`（归一化后相同）→ **优先复用已有 series**，只新建 season/episode，避免同一部剧被拆成两条。
- 若解析出的集数与 provider 的季集总数明显不符（差 > 20%），降权 0.2 并记录 `warning`。

#### 10.2.3 跨源合并与 ID 映射（MUST）

两个源各有 ID 空间，必须能互相定位：

| 方向 | 方式 |
|---|---|
| TMDB → TVDB | `/movie/{id}/external_ids`、`/tv/{id}/external_ids` 取 `tvdb_id` |
| TVDB → TMDB | `/tv/{id}/extended?meta=translations&short=false` 的 `remoteIds` 中 `TheMovieDB.com` |
| 任一 → IMDb | 同上，取 `imdb_id` |

落库：`item.provider`（winning）、`item.provider_id`、`item.external_ids`（JSON：`{"tmdb":603,"tvdb":12345,"imdb":"tt0133093"}`）。

**合并规则（只补空，不覆盖）**：

1. 以 `winning_provider` 的数据为准，写入所有非空字段。
2. 对 `overview / tagline / poster / backdrop / logo / certification` 等**空字段**，用另一源补全。
3. **季集结构永远只取 `winning_provider`**，绝不混用（混用会导致集数错位）。
4. 记录 `sources` 到 `item.meta_hash` 的输入里，便于刷新时判断是否需要重算。

#### 10.2.4 人工修正 UI

条目详情页提供「重新匹配」：

- 输入关键词（默认带原文件名），**可切换数据源**（TMDB / TVDB 两个 Tab）。
- 展示候选卡片：海报 + 标题（含原名）+ 年份 + 简介首行 + 类型，标注来源徽标。
- 选中即绑定 → `match_state='manual'`，写入 `provider`/`provider_id`，立即拉详情与图片。
- 支持直接粘贴 ID（`tmdb:603` / `tvdb:12345` / `imdb:tt0133093`），适合冷门资源。

### 10.3 数据抓取清单

因为不再有 Jellyfin 兜底，**下面每一项目标字段都必须落库**：

| 目标字段 | TMDB 接口 / 字段 | 备注 |
|---|---|---|
| 标题（中文） | `title` / `name`（`language=zh-CN`） | 缺失时回落 `original_title` |
| 原名 | `original_title` / `original_name` | 详情页副标题展示 |
| 别名 | `alternative_titles` | 搜索时可命中 |
| 年份 / 首播 | `release_date` / `first_air_date` | 解析年份对不上时用于纠错 |
| 简介 | `overview` | 中文为空则回落英文 |
| 标语 | `tagline` | Hero 轮播用 |
| 评分 | `vote_average` / `vote_count` | 展示为 `8.3` |
| 时长 | `runtime`（电影）/`episode_run_time` | 剧集显示单集时长 |
| 类型 | `genres` | 存 JSON |
| 分级 | `release_dates` / `content_ratings` | 如 `PG-13`、`TV-MA` |
| 状态 | `status`（Returning/Ended） | 剧集卡片角标 |
| 演职员 | `credits.cast`（前 20）、`credits.crew`（导演/编剧） | 头像走 §11 |
| 预告片 | `videos.results`（`type=Trailer`, `site=YouTube`） | 点击跳 YouTube 或复制 key |
| 海报 | `images.posters` | 按 `vote_average` 取最优 |
| 背景 | `images.backdrops` | 同上 |
| Logo | `images.logos` | 有则详情页用 logo 取代文字标题 |
| 剧照（集） | `/tv/{id}/season/{n}` 的 `episodes[].still_path` | 选集列表缩略图 |
| 集标题/简介 | `episodes[].name` / `overview` | 选集列表 |
| 合集 | `belongs_to_collection` | 可选：详情页「同系列」 |

参数：`language=zh-CN`（配置可改）、`include_adult=false`、`region=CN`、`append_to_response=credits,videos,images,external_ids,alternative_titles,release_dates,content_ratings`。

**TVDB v4 字段映射（第二源必须落库同样的字段）**

| 目标字段 | TVDB v4 接口 | 备注 |
|---|---|---|
| 搜索 | `/search?query={q}&type=series`、`type=movie` | 返回 `objectID` = series/movie id |
| 剧集详情 | `/series/{id}/extended?meta=translations,episodes` | `meta=episodes` 会带季集摘要 |
| 电影详情 | `/movies/{id}/extended` | v4 电影支持较新，字段少于 TMDB |
| 季列表 | `/series/{id}/extended` 的 `seasons` | 注意 `type`：`official` / `absolute` / `dvd` |
| 集列表 | `/series/{id}/episodes/default?page={n}&season={s}&seasonType=default` | 分页，需翻页取全 |
| 中文标题/简介 | `/series/{id}/translations/zho` | TVDB 语言码是 **ISO 639-2**（`zho`/`jpn`/`eng`），不是 `zh-CN` |
| 图片 | `/series/{id}/artworks?lang=zho`（或 `/artworks/{id}`） | 取 `poster` / `background` / `clearlogo` 类型 |
| 别名 | `aliases`（详情里） | |
| 内容分级 | `/series/{id}/extended` 的 `contentRatings` | |
| 跨源 ID | `/series/{id}/extended` 的 `remoteIds` | 含 `TheMovieDB.com`、`IMDB` |

> **实现注意**：TVDB 的季集有三种顺序（`default`/`official`、`absolute`、`dvd`）。默认用 `default`；动漫库允许在库设置里选 `absolute`（`scraper.tvdb_season_type`）。**一旦选定，全库统一，不可逐条混用**。

**降级规则（MUST）**：任何字段缺失都不得导致条目不可用；缺图用主色渐变占位，缺简介显示「暂无简介」，缺标题回落到文件名解析结果。

### 10.4 限流与容错（MUST）

- **按 provider 独立令牌桶**，互不干扰：

| provider | 限速 | 并发 | 说明 |
|---|---|---|---|
| TMDB | 8 req/s | 4 | 官方上限远高于此，保守取值 |
| TVDB | 4 req/s | 2 | v4 有配额，需保守 |

- 429 / 5xx → 指数退避重试 3 次（1s/4s/16s）；429 时读取 `Retry-After`。
- 单条目失败不阻塞整体任务；任务结束输出失败清单，含「失败源 + 原因」。
- 响应缓存：`scrape_cache(provider, query_hash, payload, expires_at)`，搜索缓存 7 天，详情缓存 30 天。
- **网络可达性**：两个源在国内都可能不稳定，`config.yaml` 必须为每个 provider 提供 `base_url` 与 `proxy`（见 §15），默认 `https://api.themoviedb.org/3`、`https://api4.thetvdb.com/v4`。

### 10.5 凭证管理

- 存于配置文件 / 环境变量 / 设置页，**绝不下发到前端**（接口返回时打码为 `sk-****`）。
- 所有在线请求由后端代理执行。

**TMDB**：v3 API Key（或 v4 Bearer Token），随请求带上，无状态。

**TVDB v4**：需要 **API Key + 可选 PIN**，且**必须先登录换 JWT**：

```
POST /v4/login   { "apikey": "<key>", "pin": "<pin?>" }  →  { "data": { "token": "<jwt>" } }
后续请求：Authorization: Bearer <jwt>
```

实现要求：

1. JWT 缓存在内存 + DB（`provider_token` 表），**过期前 24h 自动续期**。
2. 收到 `401` 时自动重新登录并重试一次；仍失败则标记该 provider 不可用，任务降级到另一源。
3. 设置页提供「测试连接」按钮 → `POST /api/settings/provider-test`，返回 `ok / 错误原因（401/网络/配额）`。

**均未配置时**：进入首次向导的「稍后配置」分支，全站走文件名兜底，**不报错、不白屏**。

### 10.6 元数据刷新（MUST）

没有 Jellyfin 之后，「元数据过时/错误」必须能在本应用内修复，这是长期可用的前提。

| 场景 | 触发 | 行为 |
|---|---|---|
| 新增条目 | 扫描完成后自动 | 进入刮削队列 |
| 单条更新 | 详情页「刷新元数据」 | 重新拉 TMDB 详情 + 图片 |
| 全库更新 | 设置页「刷新整个库」 | 只刷新 `match_state != manual` 且未锁定的条目 |
| 定期更新 | 配置 `scraper.auto_refresh_days`（默认 30） | 后台任务，限速执行 |
| 图片失效 | 图片 404 | 自动重下；连续失败 3 次标记 `image_broken` |

**规则**

1. 刷新只写**未锁定**字段（见 `locked_fields`）。
2. 入库前计算 payload 的 `sha1`，与 `item.meta_hash` 相同则跳过写库，避免无谓的图片重下与主题色重算。
3. backdrop 变化时必须重算 `color_primary`。
4. 刷新不得改变用户已看的播放进度与观看状态。

### 10.7 手动修正与字段编辑（MUST）

自动匹配不可能 100% 正确，**这是本项目最容易低估的模块**。

**A. 重新匹配**

- 详情页 → 「重新匹配」→ 输入关键词（默认带原文件名）→ 展示 TMDB 候选（海报 + 标题 + 年份 + 简介首行）→ 选中即绑定。
- 绑定后 `match_state='manual'`，`provider_id` 更新，立即拉取详情与图片。
- 「解除匹配」→ `match_state='failed'`，回到文件名兜底展示。

**B. 字段编辑**

- 可编辑：标题、原名、年份、简介、海报（上传/选 TMDB 候选）、背景图、合集归属。
- 保存后写入 `locked_fields`（JSON 数组，如 `["title","overview","poster"]`），后续刷新与自动刮削不再覆盖。
- 提供「恢复自动刮削」按钮，清空 `locked_fields` 并立即刷新。

**C. 合并重复条目（SHOULD）**

同一部影片因目录结构被识别成两条时，允许「合并到…」，规则：保留目标条目，迁移它的 `media_file`，源条目软删除。

---

## 11. 图片与主题色

### 11.1 图片处理（MUST）

1. 下载原图 → 生成三档：
   - `poster`: w342（列表）、w500（详情）
   - `backdrop`: w780（卡片）、w1280（hero 轮播）
   - `thumb`: w185（演职员头像）
2. 统一转 **WebP**（质量 82），存 `data/images/{sha1}.webp`。
3. 图片 URL 对外只暴露 `/img/{sha1}_{size}.webp`，**不暴露 TMDB 原链**（避免防盗链与网络问题）。
4. 下载失败 → 保留占位图，后台重试。

### 11.2 主题色提取（MUST）

- 对 `backdrop` 取色：缩放至 64px → 取主色簇（可用简单 k-means 或 `Pillow` 的 `colorgram` 思路）。
- 过滤过暗/过亮/低饱和颜色，保证与深色底对比度 ≥ 4.5:1。
- 结果存 `item.color_primary`，前端作为 CSS 变量注入详情页（见 §14.3）。

---

## 12. 播放桥接（核心）

### 12.1 抽象接口

```python
class PlayerAdapter(Protocol):
    name: str
    def available(self, request: Request) -> bool: ...
    def build(self, session: PlaySession, file: MediaFile) -> dict:
        """返回给前端的数据，前端据此执行（跳转 intent / 调后端 / 复制）"""
```

`build()` 返回形如：

```json
{
  "mode": "intent",           // intent | backend | copy
  "action": "intent://...",   // 前端直接 window.location = action
  "fallback_url": "https://...",
  "tip": "即将用 mpv 打开"
}
```

### 12.2 Android：`intent://` 拉起 mpv-android（MUST）

mpv-android 官方 intent 规范（`is.xyz.mpv`，`ACTION_VIEW`）支持 http/https + `video/*`，并支持 extras：`title`、`position`(ms)、`subs`、`subs.enable`、`decode_mode`。

构造：

```ts
function buildMpvIntent(url: string, title: string, positionMs = 0) {
  const payload = url.replace(/^https?:\/\//, ""); // intent:// 后的部分是 host+path
  const q = new URLSearchParams();
  q.set("title", title);   // 注意：请按 Chrome intent 语法使用 S.title
  return `intent://${payload}#Intent;scheme=https;package=is.xyz.mpv;type=video/any;` +
         `S.title=${encodeURIComponent(title)};i.position=${positionMs};` +
         `end`;
}
```

**规范细节**

- `type=video/any` 可强制 mpv 打开**无扩展名**的 strm 链接（重要，SmartStrm 的解析地址通常没有 `.mp4` 后缀）。
- `S.` 前缀 = String extra，`i.` 前缀 = Int extra。
- 必须对 URL 的 query 做完整编码，`#` 要编码成 `%23`，否则会被当成 fragment 截断。

**限制（必须在 UI 与文档中说明）**：

1. 只有 **Chromium 内核浏览器**支持 `intent://`。Android TV 自带浏览器多数不支持 → 见 §19 风险 R1。
2. 网页**收不到** mpv 的回传 result intent（`is.xyz.mpv.MPVActivity.result`），所以**网页模式无法记录播放进度**。
3. `intent://` 无法传 `subs`（ParcelableArray）→ 外挂字幕需依赖 mpv 自动加载同名 `.srt`，或走伴侣 App。

### 12.3 桌面：直接 spawn mpv（SHOULD，M1 后实现）

仅当 StrmAction 与播放器同机时启用。

```bash
mpv --no-terminal --force-window \
    --start=<秒> \
    --http-header-fields="User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/" \
    --input-ipc-server=/tmp/strmaction-mpv.sock \
    "<strm url>"
```

- 通过 **JSON IPC**（unix socket）订阅 `time-pos` / `duration` / `eof-reached`，每 5s 回写 `play_progress`。
- 这里的 `--http-header-fields` 是**单次播放生效**的，比改全局 `mpv.conf` 更干净。

### 12.4 兜底：复制链接

任何环境都提供「复制播放地址」按钮，并提示：`已在 mpv.conf 配置 User-Agent: pan.baidu.com`。

### 12.5 播放会话与进度回传

```
POST /api/play/{item_id}
  → { play_url, resume_ms, mode, action, headers_hint }
```

- `play_url` = 该集 `media_file.url` 原文（**不要改写、不要加参数**）。
- `resume_ms` = 上次观看位置（无记录则为 0），用于填充 `intent` 的 `i.position` 或 mpv 的 `--start`。

**进度回传接口（注意：用登录会话鉴权，不要用一次性 token）**

```
POST /api/items/{id}/progress
  body: { position_ms, duration_ms, finished }
  auth: 登录 Cookie（st_sess）
```

> ⚠️ **设计修正（v0.3）**：早期版本用 `play_session.token`（10 分钟过期）回传进度，这在「一部电影看 2 小时」的场景下**必然失败**。
> 现规则：**进度回传只依赖登录会话**，`play_session` 仅用于播放 URL 的短时下发与防滥用，有效期 24h，与进度无关。

**写入规则**

1. `position_ms / duration_ms > 0.9` 或 `finished=true` → 标记已看，`position_ms` 归零（下次从头播）。
2. 否则写入 `play_progress`，并刷新 `updated_at`。
3. 同一 `item_id` 只保留一条记录（UPSERT）。
4. 若 `duration_ms` 缺失/为 0（直播流、时长未知），只存绝对位置，不计算百分比。

### 12.6 伴侣 App（M6，v1 必做）

#### 它是什么

`StrmAction Companion` 不是第二个产品，而是**一个约 300 行的 Android WebView 壳**：里面加载的就是同一个 StrmAction 网页，唯一职责是在「网页」和「mpv」之间当一次桥。

```
WebView（你的网页）  ──JS bridge──►  原生 (Kotlin)  ──Intent──►  mpv-android
        ▲                                   │                      │
        └──── onActivityResult(position) ◄───┴──────────────────────┘
                                            │
                                     POST /api/items/{id}/progress
```

#### 为什么需要它

纯网页在 Android 上有两个绕不过去的硬限制：

| 限制 | 纯网页 | 有伴侣 App |
|---|---|---|
| 拉起 mpv | 只能 `intent://`，**仅 Chromium 内核浏览器支持**；Android TV 自带浏览器基本不支持 | 原生 `startActivityForResult`，任何 Android 设备都行 |
| 拿播放进度 | **拿不到**：网页无法接收 mpv 的 result intent，所以「继续观看」永远是 0 | 能收到 `position` / `duration`，回传后端 |
| 外挂字幕 | 传不了（`subs` 是 ParcelableArray，`intent://` 无法表达） | 可以 |

#### 什么时候需要

| 设备 | 需要吗 |
|---|---|
| Android 手机 / 平板（Chrome） | 不需要，`intent://` 够用 |
| 桌面浏览器（Windows/macOS） | 不需要，后端直接 spawn mpv + IPC 回传进度 |
| **Android TV / 电视盒子** | **需要**，否则只能「复制链接」到 mpv 里粘贴（遥控器体验极差） |

#### 它不做什么

- 不含任何业务逻辑（不刮削、不扫描、不存数据）
- 不做播放（播放永远是 mpv 的活）
- 不做视频代理

#### 桥接契约

```ts
interface StrmActionNative {
  play(url: string, title: string, positionMs: number, subs: string[]): void;
}
// 页面检测：if (window.StrmActionNative) { 走原生 } else { 降级到 intent:// 或 copy }
```

可见性判断：`window.StrmActionNative` 存在即视为在伴侣 App 内。网页端**不得**依赖它存在。

#### 进度回传的粒度与限制（必须写进 README）

| 端 | 进度来源 | 粒度 | 断点续播 |
|---|---|---|---|
| 伴侣 App（Android TV） | mpv 退出时的 result intent（`position`/`duration`） | **每次退出播放器时一次** | ✅ |
| 桌面（mpv IPC） | 订阅 `time-pos`，每 5s 上报 | **准实时** | ✅ |
| 纯网页（Chrome `intent://`） | 无 | **完全拿不到** | ❌（只能手动标记） |

**Android 端的真实行为**（务必按此实现，不要期待实时）：

1. 用户在 mpv 里按返回键 / 播完 → mpv `setResult` 回传 → 伴侣 App 收到 → 上报 → 写入。
2. 用户按 Home 键把 mpv 切到后台 → **不触发回传**；此时视频仍在播，但进度不会更新，直到用户真正退出 mpv。
3. 设备断电 / 强杀应用 → **本次进度丢失**。这是 Android 外部播放器方案的固有缺陷，Jellyfin 也一样。
4. `position` 缺失 = 正常播放结束 → 标记 `finished=true`，并自动播放下一集（见下方「自动连播」）。

**缓解措施（MUST 实现）**

- 播放页提供「标记为已看 / 未看」手动按钮。
- 播放页显示上次记录的进度与时间戳，让用户知道数据来自哪次播放。
- 伴侣 App 在 `onActivityResult` 里**先写库再刷新 UI**，避免用户返回后看到旧进度。

**可选增强（SHOULD，需验证再启用）**

- 若 mpv-android 支持加载外部脚本（`mpv.conf` 的 `script=`），可写一个 mpv 的 JS/Lua 脚本，每 30s 通过 `http-post` 上报一次进度，实现准实时。
- 验证失败则不做，不影响主流程。

#### 自动连播（MUST，伴侣 App 内）

mpv 返回结果后，若同一 `series` 下存在下一集且未看：
1. 自动调用 `play(next_episode_id)`；
2. 顶部 toast「即将播放 S01E06」，给 5 秒取消窗口；
3. 用户取消则停在本集详情页。

---

## 13. API 规格

统一前缀 `/api`，除 `/auth/login` 外全部需要会话 Cookie（`st_sess`，HttpOnly、SameSite=Lax）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | `{username, password}` → 设置 Cookie |
| POST | `/auth/logout` | 清除会话 |
| GET | `/libraries` | 库列表（含条目数、最近扫描时间） |
| POST | `/libraries` | 新建库 `{name, root_path, type, scan_cron}` |
| PATCH | `/libraries/{id}` | 修改（含启用/禁用） |
| DELETE | `/libraries/{id}` | 删除库（含级联） |
| POST | `/libraries/{id}/scan` | 触发扫描（异步，返回 task_id） |
| POST | `/libraries/{id}/scrape` | 触发刮削（仅处理 `pending/failed`） |
| POST | `/libraries/{id}/refresh` | 全库刷新元数据（跳过 `manual` 与锁定字段） |
| GET | `/items` | 查询：`library_id, kind, q, genre, year, sort, page, page_size` |
| GET | `/items/{id}` | 详情（含子项、media_files、进度） |
| POST | `/items/{id}/match` | 手动绑定 `{provider, provider_id}` → `manual` |
| POST | `/items/{id}/unmatch` | 解除绑定 → `failed` |
| GET | `/items/{id}/match-candidates` | `?q=` → TMDB 候选列表 |
| PATCH | `/items/{id}` | 手动编辑字段（标题/简介/年份/合集…），写入 `locked_fields` |
| POST | `/items/{id}/poster` | multipart 上传自定义海报/背景 |
| POST | `/items/{id}/refresh` | 单条重刮 |
| POST | `/items/{id}/watched` | `{finished: bool}` 手动标记已看/未看 |
| GET | `/search` | 全库搜索（标题/别名/演职员） |
| GET | `/home` | 首页聚合：`hero[]`, `continue[]`, `recent[]`, `rows[]` |
| POST | `/play/{item_id}` | 创建播放会话，返回 `play_url` + `resume_ms` + adapter 结果 |
| POST | `/items/{id}/progress` | `{position_ms, duration_ms, finished}`（**登录会话鉴权**，见 §12.5） |
| GET | `/tasks` | 任务列表与日志 |
| GET | `/settings` | 读取配置（脱敏：`api_key` 返回 `sk-****`） |
| PATCH | `/settings` | 修改（TMDB/TVDB Key、源优先级、语言、季集类型、默认播放器、模板） |
| POST | `/settings/provider-test` | `{provider}` → 测试连通性与凭证，返回 `ok` / `401` / `network` |
| GET | `/img/{name}` | 静态图片（带 `Cache-Control: max-age=31536000, immutable`） |

**响应示例（`GET /home`）**

```json
{
  "hero": [
    { "id": 12, "title": "沙丘2", "year": 2024, "backdrop": "/img/a1_1280.webp",
      "color": "#3b2a1e", "tagline": "命运之战", "badges": ["4K", "HDR"] }
  ],
  "continue": [
    { "id": 33, "title": "三体", "subtitle": "S01E05 · 剩余 27 分钟",
      "poster": "/img/b2_342.webp", "progress": 0.42 }
  ],
  "rows": [
    { "title": "最近添加", "items": [ /* Summary[] */ ] },
    { "title": "评分最高", "items": [ /* ... */ ] }
  ]
}
```

**错误格式**：`{ "error": { "code": "MATCH_FAILED", "message": "…" } }`，HTTP 状态码语义正确。

---

## 14. 前端规格

### 14.1 页面

| 页面 | 内容 |
|---|---|
| 首页 `/` | Hero 轮播 + 继续观看 + 最近添加 + 分类横滑（按类型/年份/评分） |
| 详情 `/item/:id` | 全屏背景（模糊 + 渐隐）、标题 logo、评分/年份/时长、简介、演职员、**选集**、播放按钮、版本切换、重新匹配入口 |
| 搜索 `/search` | 即时搜索、热门标签、结果网格 |
| 设置 `/settings` | 库管理、TMDB/TVDB Key、源优先级、语言、季集类型、默认播放器、目录模板、扫描计划 |
| 任务 `/tasks` | 扫描/刮削进度、失败清单、日志 |

### 14.2 交互要求（对齐 VidHub / SenPlayer 的质感）

- **Hero 轮播**：8s 自动切换，交叉淡入 + 极缓慢 Ken Burns 缩放（1.0 → 1.05）；鼠标悬停或遥控聚焦即暂停；指示点细小、半透明。
- **卡片**：2:3 海报，圆角 12px，悬停上浮 4px + 阴影加深 + 300ms 缓动；缺图时显示主色渐变占位。
- **转场**：`framer-motion` 的 `layoutId` 做「海报 → 详情页背景」的共享元素过渡。
- **骨架屏**：所有异步区域必须有 skeleton，禁止白屏。
- **播放反馈**：点击播放后按钮进入 loading，成功则 toast「已交给 mpv」，失败给出原因与「复制链接」。
- **滚动**：横向行使用 `scroll-snap` + 隐藏滚动条；支持触控板横向手势。
- **无障碍**：所有可交互元素可聚焦，`:focus-visible` 有 2px 高对比描边。

### 14.3 主题色

详情页根节点注入：

```css
:root {
  --accent: #e8b06a;
  --accent-soft: color-mix(in oklab, var(--accent) 18%, transparent);
  --bg-deep: color-mix(in oklab, var(--accent) 8%, #07080a);
}
```

背景 = backdrop 图 + `backdrop-filter: blur(60px) saturate(120%)` + 自底部向上的黑色渐变遮罩，保证文字对比度。

### 14.4 TV 模式（MUST）

> 电视端的正式交付形态是**伴侣 App**（§12.6）内的 WebView；浏览器 + `?tv=1` 仅作为调试与降级入口。

- 通过 UA/查询参数 `?tv=1` 或屏幕宽度 ≥ 1920 且无触摸 → 进入 TV 布局。
- 方向键导航：自定义焦点管理（`focusKey` 数组 + 上下左右映射），避免浏览器默认 Tab 顺序错乱。
- 焦点态：放大 1.06 + 白色描边 + 光晕，200ms。
- 安全区：四周留 48px overscan 边距。
- 不依赖 hover 的交互；所有次要信息（简介、演职员）放在聚焦后才展开。

### 14.5 性能

- 图片 `loading="lazy"` + `decoding="async"`，仅预取视口下一屏。
- 长列表虚拟化（`@tanstack/react-virtual`）。
- 首屏 JS < 200KB gzip；路由级 code splitting。
- 首页 `/api/home` 一次请求拿全，避免瀑布。

### 14.6 首次启动向导（MUST）

首次访问检测到「无管理员密码」时，进入三步向导，全程不超过 60 秒：

1. **设置管理员密码**（强度校验；写入 argon2 哈希）。
2. **元数据源 Key**（TMDB / TVDB，附申请链接与图文说明；至少填一个，也可「稍后配置」跳过，跳过则走文件名兜底）。
3. **添加第一个识别目录**：填容器内路径 + 选库类型 + （可选）扫描计划 → 点「开始扫描」进入进度页。

向导完成后落到首页；若扫描中，首页顶部显示细进度条，不阻塞浏览。

---

## 15. 配置

**优先级**：数据库中的设置（设置页写入） > `config.yaml` > 内置默认值。
布尔/字符串类设置建议全部可在设置页修改，`config.yaml` 只做初始值与密钥兜底。

`config.example.yaml`：

```yaml
server:
  host: 0.0.0.0
  port: 8080
  base_url: "http://192.168.1.10:8080"   # 用于生成播放链接
  data_dir: "./data"

auth:
  username: admin
  password_hash: "$argon2id$..."          # 首次启动可用明文密码初始化后立即哈希

scraper:
  language: zh-CN
  proxy: ""                               # 两个源共用；可在各 provider 下单独覆盖
  auto_refresh_days: 30                   # 0 = 关闭定期刷新
  match_threshold: 0.75                   # 自动绑定阈值

  # 各类型的源优先级链（空数组 = 不刮削）
  provider_priority:
    movie:  [tmdb, tvdb]
    tv:     [tmdb, tvdb]                  # 动漫库建议改成 [tvdb, tmdb]
    home:   []
    course: []

  tmdb:
    api_key: ""
    base_url: https://api.themoviedb.org/3
    proxy: ""
    rate_limit: 8                         # req/s
    concurrency: 4
    language: zh-CN

  tvdb:
    api_key: ""
    pin: ""                               # 部分账号需要
    base_url: https://api4.thetvdb.com/v4
    proxy: ""
    rate_limit: 4
    concurrency: 2
    language: zho                         # ISO 639-2：zho / jpn / eng
    season_type: default                  # default | absolute | dvd

scanner:
  ignore: ["@eaDir", ".DS_Store", "#recycle", "*.tmp"]
  follow_symlinks: false
  max_depth: 6

player:
  default: auto                           # auto | intent | mpv_ipc | copy
  mpv_path: /usr/bin/mpv
  mpv_extra_args:
    - "--http-header-fields=User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/"
  enable_progress: true

ui:
  default_language: zh-CN
  hero_rotate_ms: 8000
```

---

## 16. 安全与合规

1. **播放 URL 即凭证**：`.strm` 内容是网盘解析地址，视同密码。
   - 所有返回 URL 的接口必须鉴权。
   - 日志中 URL 打码（保留 host + 前 12 字符）。
   - 不要把 URL 写进 `task_log.message`。
2. **默认仅内网**：文档与启动日志提示不要直接暴露公网；如需外网，要求前置 HTTPS 反代 + 强密码。
3. **路径穿越防护**：所有文件访问基于 `library.root_path` 做 `realpath` 校验。
4. **TMDB 合规**：页面底部必须展示
   > This product uses the TMDB API but is not endorsed or certified by TMDB.
   并附 TMDB logo。图片仅在本地缓存用于展示。
5. **无账号体系**：单管理员；密码使用 argon2 哈希；登录失败 5 次锁定 5 分钟。

---

## 17. 里程碑与验收

### M0 骨架（0.5d）
- [ ] Docker 一键启动，`/api/health` 返回 ok
- [ ] 登录/登出可用，未登录访问任意 `/api/*` 返回 401
- [ ] 前端空壳可加载

### M1 扫描 + 解析（2d）
- [ ] 添加 `movie` / `tv` 两个库，扫描 1000 个 `.strm` < 30s（不含刮削）
- [ ] 生成的条目结构正确：`series → season → episode` 层级、季集号正确
- [ ] 二次扫描为增量：无变更时 0 次解析
- [ ] 删除一个文件后，对应 `media_file.missing=1`

**验收样本**：见 §18 的目录树，必须全部解析正确。

### M2 刮削（5d）
- [ ] 100 条混合样本，自动匹配成功率 ≥ 85%（人工判定）
- [ ] 剧集能拿到季信息、集标题、集简介、集剧照
- [ ] **TVDB 通路可用**：动漫库设为 `[tvdb, tmdb]` 后，季集数量与发布组一致（用《进击的巨人》或同类做样本）
- [ ] **双源降级**：TMDB 不可用时自动落到 TVDB，任务不中断；两源都失败才标 `failed`
- [ ] **跨源 ID 映射**：同一部剧在 TMDB/TVDB 间能互相定位，不产生重复条目
- [ ] 失败条目出现在「待修正」列表，可搜索并手动绑定；候选列表可切换 TMDB/TVDB 两个 Tab
- [ ] 手动编辑标题/简介/海报后，`locked_fields` 生效——再刷新不被覆盖
- [ ] 单条刷新、全库刷新均可用；无变更时不重下图片
- [ ] 海报/背景/主题色全部落地本地，断网后详情页仍可展示
- [ ] 未配置任何 Key 时，全站仍可用（文件名兜底），不报错白屏
- [ ] 任一源 429 / 401 时不崩，记录重试；TVDB token 过期能自动续期

### M3 前端浏览（3d）
- [ ] 首页轮播、继续观看、最近添加、分类行全部可用
- [ ] 详情页有背景模糊、主题色、选集、演职员
- [ ] 骨架屏、空态、错误态齐全
- [ ] Lighthouse Performance ≥ 85（桌面）

### M4 播放（1d）
- [ ] Android Chrome 点播放能拉起 mpv 并开始播放（`type=video/any` 生效）
- [ ] 桌面模式能 spawn mpv 并回写进度
- [ ] 兜底「复制链接」可用
- [ ] 播放 URL 不出现在任何日志明文里

### M5 打磨（2d）
- [ ] TV 模式方向键导航顺畅，无焦点丢失
- [ ] 转场与轮播动效达到「可截图发朋友圈」的程度
- [ ] 任务页能看到扫描/刮削进度与失败原因

### M6 伴侣 App（4d）
- [ ] WebView 壳 + `play()` 桥接，TV 遥控器可完整操作
- [ ] 播放时把 `resume_ms` 作为 `i.position` 传给 mpv，**能续播**
- [ ] mpv 退出后收到 result intent，`position`/`duration` 正确写入（用 2 次中断播放验证）
- [ ] 首页「继续观看」显示真实进度条与剩余时长
- [ ] 播完自动连播下一集，含 5 秒取消窗口
- [ ] 断电/强杀场景：进度允许丢失，但不得写坏数据（`position_ms` 不得为负/大于时长）
- [ ] 产出签名 APK + 电视 sideload 安装说明（README 一节）

---

## 18. 测试矩阵

### 18.1 目录样本（必须全部通过）

```
/media/strm/
├─ 电影/
│  ├─ 流浪地球2 (2023)/流浪地球2 (2023).strm
│  ├─ 沙丘2 (2024)/沙丘2 (2024) - 2160p.strm
│  ├─ 沙丘2 (2024)/沙丘2 (2024) - 1080p.strm        → 同条目，两版本
│  ├─ 奥本海默 （2023）/奥本海默 （2023）.strm       → 全角括号
│  └─ 无名/无名.strm                                  → 无年份
├─ 剧集/
│  ├─ 三体 (2023)/Season 01/三体 - S01E01.strm
│  ├─ 漫长的季节 (2023)/S01/漫长的季节.01.strm
│  ├─ Some.Show.2020/Season 02/Some.Show.S02E03.1080p.strm
│  └─ 狂飙/第一季/第12集.strm
├─ 动漫/                                    → 该库 provider_priority 设为 [tvdb, tmdb]
│  └─ 进击的巨人 (2013)/Season 01/进击的巨人 - S01E01.strm
├─ 家庭视频/
│  └─ 2024-06-01 生日/VID_20240601.mp4.strm
└─ 课程/
    └─ Rust 实战/01 所有权/01 所有权.strm
```

### 18.2 边界用例

| 场景 | 期望 |
|---|---|
| `.strm` 内容为空 / 非 URL | `invalid`，不进列表，任务日志可见 |
| 文件名含 `#`、`&`、emoji | 解析正确，播放 URL 编码正确 |
| 同一目录重复扫描 10 次 | 无重复条目，无重复 media_file |
| 目录含 20000 个文件 | 扫描内存 < 300MB，UI 不卡 |
| TMDB 不可达 | 任务标记失败，已有元数据不丢 |
| 手动绑定后再扫描 | 不被覆盖（`manual` 锁定） |
| 超长标题（>100 字） | UI 截断 + tooltip，不撑破布局 |
| 动漫库用 TVDB 优先 | 季集数量与发布组一致；切回 TMDB 后不产生重复条目 |
| 双源都有该片 | 记录 `winning_provider`，季集只来自胜出源，不混用 |

### 18.3 安全用例

- 未登录访问 `/api/play/1` → 401
- `root_path` 之外的符号链接 → 拒绝
- 逾期 `session_token` → 403

---

## 19. 风险与待决

| ID | 风险 | 影响 | 应对 |
|---|---|---|---|
| R1 | Android TV 浏览器不支持 `intent://` | TV 上无法一键播放 | **已由 M6 伴侣 App 解决**（纳入 v1）；浏览器 + `?tv=1` 仅作调试降级 |
| R2 | 网页收不到 mpv 的 result intent | 网页模式无进度 | M6 伴侣 App 解决；网页模式以「手动标记已看」兜底 |
| R3 | TMDB / TVDB 国内访问不稳 | 刮削失败 | 每个 provider 独立配 `proxy` / 自建反代；双源互为降级；`.nfo` 兜底 |
| R4 | SmartStrm 目录命名不规范 | 解析失败 | 模板可配置 + 手动修正；建议用户在 SmartStrm 里开启 TMDB 批量重命名 |
| R5 | 网盘解析地址有时效 | 播放 403 | 本设计只存解析地址、播放时实时交给 mpv，已规避；若用户存的是直链，则需提示重新生成 strm |
| R6 | 一个目录里混多种媒体类型 | 归类错乱 | 库按类型隔离；`tv` 库里出现孤立文件时归为「其他」 |
| R7 | TMDB 对冷门/国产老片中文数据缺失 | 详情页信息稀疏 | TVDB 可补部分数据；仍缺则手动编辑 + 支持本地 `.nfo`；README 说明可配合 tinyMediaManager |
| R8 | 用户按 Jellyfin 习惯期待「转码/字幕搜索/多端同步」 | 认知落差 | README 明确非目标；字幕由 mpv 自动加载同名 `.srt`（SmartStrm 可复制） |
| R9 | **双源季集结构不一致**（TMDB 2 季 vs TVDB 1 季 24 集） | 集数与文件对不上，出现空集/错位 | §10.2.3 已规定：季集**只取 winning provider**，绝不混用；切源时触发整剧重建并保留已看进度（按 `SxxExx` 重映射） |
| R10 | **Android 进度只在退出 mpv 时回传** | 断电/强杀丢进度；看一半切后台不更新 | 见 §12.6：手动标记兜底 + 显示记录时间戳；桌面端用 IPC 做准实时；不承诺 TV 端实时同步 |

**已决策（无需再讨论）**

- D1 ✅ **伴侣 App 纳入 v1**（v0.6）。电视端是一等公民：一键拉起 mpv、断点续播、自动连播。里程碑 M6 不再是可选项。
- D2 ✅ **TVDB 纳入 v1**（v0.3）。默认 `[tmdb, tvdb]`，动漫库建议 `[tvdb, tmdb]`。
- D3 ✅ **不做多语言 UI**（v0.6）。界面文案仅中文；要求所有文案集中在一个常量文件（`src/i18n/zh-CN.ts`），不散落在组件里，便于日后扩展。元数据语言仍可通过配置切换（那是数据层）。

**待决**

- 暂无。

---

## 20. 交付物清单

- [ ] 可运行的 Docker 镜像（`docker run -p 8080:8080 -v /media/strm:/media/strm -v ./data:/data`）
- [ ] `config.example.yaml` + `docker-compose.yml` + README（部署、配置 mpv 的 UA、TV 使用方式、**TMDB 与 TVDB Key 申请图文步骤**）
- [ ] API 文档（FastAPI 自动生成 `/docs`）
- [ ] **数据导出/导入**：`GET /api/export` 导出 `library.json`（库配置 + 条目元数据 + 手动覆盖），`POST /api/import` 回灌；SQLite 文件本身可整份备份
- [ ] **伴侣 App 的签名 APK**（`strmaction-companion-v1.apk`）+ 安装说明（电视上如何 sideload）
- [ ] 一份 3 分钟的演示录屏（首页轮播 → 详情 → 选集 → 拉起 mpv 播放 → 退出后「继续观看」有进度）
- [ ] §18 的测试样本目录（可用脚本生成占位 `.strm`）

---

## 附录 A：给开发 Agent 的执行顺序

1. 先做 **M0 + M1**，用 §18.1 的样本目录跑通解析，这是全项目地基。
2. **M2 是全项目最重的模块**（不再是附属功能）：先跑通「搜索 → 打分 → 绑定 → 写库 → 下图 → 取色」主链路，再补「手动修正 / 字段锁定 / 刷新」。
   - 「手动修正」必须和自动匹配同期完成，否则失败样本无法验收。
   - 剧集的季/集详情（集标题、剧照）建议放在电影链路稳定之后再做。
3. **M3 与 M4 可以并行**；M4 先用 `copy` 兜底打通链路，再实现 `intent://`。
4. **M6（伴侣 App）在 M4 之后做、在 M5 之前做**：因为 TV 端的焦点导航与动效打磨，必须在伴侣 App 里真机验证才有意义，顺序反了要返工两次。
5. 最后做 **M5 打磨**，动效与主题色是这个产品区别于 Jellyfin 的核心，不要省。
   - **开工前先读附录 D 与附录 E**：那里面是「照着敲」级别的实现细节，能省掉大量试错。
6. 任何时候都**不要**给视频流加代理——那会让这个项目的存在意义消失；也**不要**引入 Jellyfin 依赖。
7. UI 文案从一开始就集中放 `src/i18n/zh-CN.ts`，不要在组件里写死中文字符串——虽然 v1 不做多语言，但这一步几乎零成本。

## 附录 B：mpv 端配置（写进 README）

Android（`mpv.conf`，应用内「设置 → 高级 → 编辑 mpv.conf」）：

```ini
http-header-fields=User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/
cache=yes
demuxer-max-bytes=256MiB
```

桌面：由 StrmAction 启动时传入 `--http-header-fields`，无需改全局配置。

---

## 附录 C：功能总览（最终范围）

> 本表即最终功能范围，供开发 Agent 与验收使用。优先级：`P0` 必须有 / `P1` 应该有 / `P2` 可选。

### C.1 媒体库与扫描

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 1 | 多「识别目录」管理（增删改、启用/禁用、定时扫描） | P0 | §8 |
| 2 | 四种库类型：电影 / 电视剧 / 家庭视频 / 课程 | P0 | §8.1 |
| 3 | 增量扫描（mtime + size 判断，未变更不重新解析） | P0 | §8.2 |
| 4 | 删除软标记（`missing`）、连续缺失才清理 | P0 | §8.2 |
| 5 | 改名/移动识别（按内容 URL 归并，不产生重复条目） | P0 | §8.2 |
| 6 | 忽略规则（`@eaDir`、`.DS_Store`、`#recycle` 等可配） | P0 | §8.2 |
| 7 | `.strm` 读取与校验（首行、URL 前缀、注释、BOM） | P0 | §8.3 |
| 8 | 符号链接越界防护 | P0 | §8.2 |

### C.2 命名解析

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 9 | 目录模板优先解析（可配置正则模板） | P0 | §9.1 |
| 10 | `guessit` 兜底解析 | P0 | §9.1 |
| 11 | 中文/全角括号/无年份/多季多集写法兼容 | P0 | §9.2 |
| 12 | 多版本识别（2160p / 1080p → 同条目多文件） | P0 | §9.2 |
| 13 | 分段识别（CD1/CD2、part1/part2） | P1 | §9.2 |

### C.3 刮削与元数据

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 14 | 双元数据源：TMDB（默认主源）+ TVDB（第二源） | P0 | §10.1 |
| 15 | 按库类型配置源优先级链（如动漫库 `[tvdb, tmdb]`） | P0 | §10.1 |
| 16 | 自动匹配打分（标题 55% / 年份 25% / 热度 10% / 别名 10%） | P0 | §10.2.2 |
| 17 | 显式 ID 直取（`{tmdb-…}` / `{tvdb-…}` / `{imdb-…}`） | P1 | §10.2.1 |
| 18 | 跨源 ID 映射（tmdb ↔ tvdb ↔ imdb）与去重 | P0 | §10.2.3 |
| 19 | 跨源字段补全（只补空；**季集永不混用**） | P0 | §10.2.3 |
| 20 | 完整元数据 17 项（标题/原名/别名/年份/简介/标语/评分/时长/类型/分级/状态/演职员/预告片/海报/背景/Logo/剧照） | P0 | §10.3 |
| 21 | 剧集季/集详情（集标题、集简介、集剧照） | P0 | §10.3 |
| 22 | 本地 `.nfo` 兼容（命中则完全接管） | P1 | §10.1 |
| 23 | 手动重新匹配（双源候选 Tab + 直接粘贴 ID） | P0 | §10.7 |
| 24 | 字段级手动编辑 + 锁定（`locked_fields`）+ 一键恢复自动 | P0 | §10.7 |
| 25 | 重复条目合并 | P2 | §10.7 |
| 26 | 元数据刷新：单条 / 全库 / 每 30 天自动 | P0 | §10.6 |
| 27 | `meta_hash` 变更检测，无变更不重下图片 | P1 | §10.6 |
| 28 | 无 Key / 源不可达时降级为文件名展示 | P0 | §10.3 |

### C.4 图片与视觉资产

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 29 | 三档尺寸 WebP（poster / backdrop / thumb） | P0 | §11.1 |
| 30 | 本地缓存 + 长缓存头 | P0 | §11.1 |
| 31 | 主题色提取并落库（`color_primary`） | P0 | §11.2 |
| 32 | 图片失效自动重下（3 次失败标记） | P1 | §10.6 |

### C.5 播放

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 33 | 播放适配器：Android `intent://` 拉起 mpv | P0 | §12.2 |
| 34 | 播放适配器：桌面 spawn mpv + JSON IPC | P1 | §12.3 |
| 35 | 播放适配器：复制链接兜底 | P0 | §12.4 |
| 36 | 断点续播（`resume_ms` → `i.position` / `--start`） | P0 | §12.5 |
| 37 | 进度回传（Android 退出时 / 桌面 5s 轮询） | P0 | §12.5 |
| 38 | 播完 90% 自动标记已看、位置归零 | P0 | §12.5 |
| 39 | 手动标记已看 / 未看 | P0 | §13 |
| 40 | 自动连播下一集（5 秒取消窗口） | P1 | §12.6 |
| 41 | 外挂字幕传递（伴侣 App） | P1 | §12.6 |
| 42 | 播放 URL 视为凭证：鉴权 + 日志打码 | P0 | §16 |

### C.6 界面

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 43 | 首页：Hero 轮播 + 继续观看 + 最近添加 + 分类横滑 | P0 | §14.1 |
| 44 | 详情页：背景模糊 + 主题色 + Logo + 演职员 + 选集 + 版本切换 | P0 | §14.1 |
| 45 | 搜索（标题/别名/演职员） | P0 | §14.1 |
| 46 | 设置页（库、Key、源优先级、季集类型、播放器、模板） | P0 | §14.1 |
| 47 | 任务页（扫描/刮削进度、失败清单、日志） | P0 | §14.1 |
| 48 | TV 模式（方向键焦点、安全区、10-foot UI） | P0 | §14.4 |
| 49 | 动效（共享元素转场、Ken Burns、骨架屏） | P0 | §14.2 |
| 50 | 首次启动向导（密码 → Key → 加目录 → 扫描） | P0 | §14.6 |
| 51 | 缺图/缺简介/缺标题的优雅降级 | P0 | §14.2 |
| 52 | 中文文案集中管理（`src/i18n/zh-CN.ts`，不散落组件） | P0 | §2.1 |

### C.7 运维与安全

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 53 | 单容器 Docker 部署 | P0 | §20 |
| 54 | 配置优先级（DB > yaml > 默认） | P0 | §15 |
| 55 | 数据导出/导入 + SQLite 备份 | P1 | §20 |
| 56 | 单管理员鉴权（argon2、登录限流、HttpOnly Cookie） | P0 | §16 |
| 57 | TMDB/TVDB 连通性测试 | P1 | §13 |
| 58 | 每个 provider 独立代理与限速 | P0 | §10.4 |

### C.8 伴侣 App（M6，v1 必做）

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 59 | WebView 壳 + `window.StrmActionNative` 桥 | **P0** | §12.6 |
| 60 | 拉起 mpv 并接收 result intent | **P0** | §12.6 |
| 61 | 续播 + 进度写入 + 自动连播 | **P0** | §12.6 |

### C.9 明确不做

| 不做 | 原因 |
|---|---|
| 视频转码 | 播放器负责 |
| 视频流中转 / 反代 / 缓存 | 会吃掉服务器带宽，项目失去意义 |
| 网盘登录 / Alist 替代 | 由 SmartStrm + Alist 负责 |
| 依赖 Jellyfin / Emby / Plex | 本项目是替代品 |
| 多语言 UI 切换 | D3 决策：v1 仅中文（文案已集中，未来可低成本扩展） |
| 多用户 / 权限体系 | 单管理员足够 |
| 内嵌播放器 | 播放交给 mpv |
| 弹幕 / 评论 / 社交 | 非目标 |

### C.10 工作量汇总

| 里程碑 | 内容 | 人日 |
|---|---|---|
| M0 | 骨架 + 鉴权 | 0.5 |
| M1 | 扫描 + 解析 | 2 |
| M2 | 刮削（双源 + 修正 + 刷新） | 5 |
| M3 | 前端浏览 | 3 |
| M4 | 播放桥接（web intent / 桌面 spawn / copy） | 1 |
| M6 | 伴侣 App（**v1 必做**） | 4 |
| M5 | 打磨（动效 / TV / 任务页） | 2 |
| **v1 合计** | | **17.5** |

---

## 附录 D：M2 刮削实现细则

### D.1 Provider 接口

```python
from typing import Literal, Protocol

Kind = Literal["movie", "tv"]

class MetadataProvider(Protocol):
    name: str                    # "tmdb" | "tvdb"
    supports: set[Kind]

    async def search(self, *, title: str, year: int | None, kind: Kind) -> list["Candidate"]: ...
    async def fetch(self, provider_id: str, *, kind: Kind) -> "CanonicalMeta": ...
    async def fetch_season(self, provider_id: str, season_no: int) -> "SeasonDetail": ...
    async def health(self) -> "ProviderHealth": ...
```

统一的数据类（两个 provider 都必须映射到它）：

```python
@dataclass
class Candidate:
    provider: str
    provider_id: str
    title: str
    original_title: str | None
    year: int | None
    kind: Kind
    overview: str | None
    poster_url: str | None
    popularity: float          # 原始热度；打分时用「排名」归一化，不用绝对值
    raw: dict                  # 原始 JSON，便于排错

@dataclass
class CanonicalMeta:
    provider: str
    provider_id: str
    kind: Kind
    title: str
    original_title: str | None
    aliases: list[str]
    year: int | None
    overview: str | None
    tagline: str | None
    rating: float | None
    runtime_min: int | None
    genres: list[str]
    certification: str | None
    status: str | None
    cast: list[CastMember]         # 前 20
    trailer_key: str | None        # YouTube key
    collection: dict | None        # {"id":..., "name":...}
    poster_url: str | None
    backdrop_url: str | None
    logo_url: str | None
    external_ids: dict[str, str]   # {"tmdb":"603","tvdb":"...","imdb":"tt..."}
    seasons: list[SeasonSummary]   # kind=="tv" 才有

@dataclass
class SeasonSummary:
    season_no: int
    name: str | None
    episode_count: int
    poster_url: str | None
    air_date: str | None

@dataclass
class SeasonDetail:
    season_no: int
    episodes: list[EpisodeMeta]

@dataclass
class EpisodeMeta:
    episode_no: int
    title: str | None
    overview: str | None
    runtime_min: int | None
    air_date: str | None
    still_url: str | None
```

### D.2 TmdbProvider

| 动作 | 请求 |
|---|---|
| 搜索电影 | `GET /search/movie?query=&year=&language=&include_adult=false` |
| 搜索剧集 | `GET /search/tv?query=&first_air_date_year=&language=&include_adult=false` |
| 电影详情 | `GET /movie/{id}?append_to_response=credits,videos,images,external_ids,alternative_titles,release_dates` |
| 剧集详情 | `GET /tv/{id}?append_to_response=credits,videos,images,external_ids,alternative_titles,content_ratings` |
| 季详情 | `GET /tv/{id}/season/{n}?language={lang}` |

**字段映射要点**

- 标题：`movie.title` / `tv.name`；空则回落 `original_title`。
- 年份：`release_date[:4]` / `first_air_date[:4]`，解析失败置 `None`。
- 演职员：`credits.cast[:20]`，头像用 `profile_path`；`credits.crew` 取 `job in {Director, Writer}`。
- 预告片：`videos.results` 里 `site=="YouTube"` 且 `type in {"Trailer","Teaser"}`，优先 `official==true`。
- 分级：电影从 `release_dates.results` 找 `iso_3166_1 in {"CN","US"}`；剧集从 `content_ratings.results` 同理。
- 跨源 ID：`external_ids.tvdb_id` / `external_ids.imdb_id`。

**图片选择算法（必须实现，否则海报质量随机）**

```python
def pick_image(images: list[dict], prefer_lang="zh", aspect=None) -> str | None:
    # 1) 语言优先级：zh > (None/xx) > en > 其他
    # 2) 同优先级内按 vote_average 降序，票数 < 3 的视作 0
    # 3) 背景图额外要求 1.6 <= aspect_ratio <= 1.9（避免选到奇怪裁切）
    ...
```

图片 URL 规则：`https://image.tmdb.org/t/p/{w342|w500|w780|w1280|w185}{path}`。

### D.3 TvdbProvider

**鉴权（必须先做，否则全是 401）**

```python
POST {base}/login   json={"apikey": key, "pin": pin or None}
→ {"data": {"token": "<jwt>"}}
后续所有请求：Authorization: Bearer <jwt>
```

- JWT 存 `provider_token` 表，`expires_at` 解析 JWT 的 `exp`。
- **提前 24h 续期**；收到 401 时强制重登并重试一次。
- 并发下只允许一个续期请求在飞（`asyncio.Lock`）。

**接口映射**

| 动作 | 请求 |
|---|---|
| 搜索 | `GET /search?query={q}&type=series`（电影用 `type=movie`） |
| 剧集详情 | `GET /series/{id}/extended?meta=translations,episodes` |
| 电影详情 | `GET /movies/{id}/extended` |
| 集列表 | `GET /series/{id}/episodes/default?page={n}&season={s}&seasonType={type}` |
| 翻译 | `GET /series/{id}/translations/zho` |
| 图片 | `GET /series/{id}/artworks?lang=zho` |
| 别名 | `/series/{id}/extended` 的 `aliases` |

**必须处理的三个坑**

1. **分页**：`/episodes/default` 每页上限有限，必须循环到 `links.next` 为 null，否则长剧只入前 20 集。
2. **季集类型**：`seasonType` 取 `default`（官方播出顺序）/ `absolute`（动漫绝对集号）/ `dvd`。由库配置决定，全库统一。
3. **语言码是 ISO 639-2**：`zho` / `jpn` / `eng`，不是 `zh-CN`；翻译缺失时回落英文，`overview` 为空时不要覆盖 TMDB 的值。

**图片类型映射**：`poster` → 海报，`background` → 背景，`clearlogo` → Logo。

> ⚠️ TVDB v4 的路径与字段可能随版本调整。**实现第一步先写 smoke test**：用固定 ID 拉一次 detail + 一次 episodes，打印字段，确认与本文档一致再往下写。

### D.4 归一化与打分

```python
TRAD2SIMP = ...  # opencc 或预置对照表

def normalize_title(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)          # 全角 → 半角
    s = TRAD2SIMP.translate(s)                     # 繁 → 简
    s = re.sub(r"[\[\(（【].*?[\]\)）】]", " ", s)     # 去掉括号内容
    s = re.sub(r"(?i)\b(season|s)\s*\d+\b", " ", s)
    s = re.sub(r"第[一二三四五六七八九十百\d]+[季部]", " ", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)
    return s.lower()
```

```python
def score(query: Parsed, cand: Candidate, rank: int, total: int) -> float:
    title_sim = rapidfuzz.WRatio(normalize_title(query.title),
                                 normalize_title(cand.title)) / 100.0
    if query.year and cand.year:
        d = abs(query.year - cand.year)
        year_score = 1.0 if d == 0 else (0.7 if d == 1 else 0.0)
    else:
        year_score = 0.5
    pop_score = 1.0 - (rank / max(1, total - 1))       # 用排名，不用原始热度
    alias_hit = 1.0 if any(normalize_title(a) == normalize_title(query.title)
                           for a in cand.aliases) else 0.0
    return 0.55*title_sim + 0.25*year_score + 0.10*pop_score + 0.10*alias_hit
```

**额外惩罚**：解析出的最大集号比 provider 的 `episode_count` 大 20% 以上 → `score -= 0.2`（常见于剧场版被当成剧集）。

**阈值**：`score >= 0.75` 自动绑定；`0.6 ~ 0.75` 记为 `pending` 并在 UI 提示「建议确认」；`< 0.6` 记 `failed`。

### D.5 匹配主流程（伪代码）

```python
async def scrape(item: Item) -> str:
    parsed = item.parsed
    for pname in config.priority[item.kind]:
        provider = registry[pname]
        if not provider.enabled:
            continue
        cands = await provider.search(title=parsed.title, year=parsed.year, kind=item.kind)
        ranked = [score(parsed, c, i, len(cands)) for i, c in enumerate(cands)]
        best = max(ranked, key=lambda x: x.score, default=None)
        if not best or best.score < 0.60:
            continue

        meta = await provider.fetch(best.provider_id, kind=item.kind)
        if item.kind == "tv":
            for s in meta.seasons:
                if s.season_no == 0:          # 特别篇默认跳过，可配置
                    continue
                detail = await provider.fetch_season(meta.provider_id, s.season_no)
                meta.episode_map[(s.season_no, ep.episode_no)] = ep

        async with db.transaction():
            persist_meta(item, meta, winning=pname)          # 只写未锁定字段
            await fill_missing_from_other(item, meta)        # 见 D.5.1
        enqueue_images(item)
        return "ok"
    return mark_failed(item, reason="no_match")
```

**D.5.1 跨源补空**

```python
async def fill_missing_from_other(item, meta):
    other_ids = {k: v for k, v in item.external_ids.items() if k != meta.provider}
    if not other_ids: return
    other = registry[other_ids["provider"]]
    other_meta = await other.fetch(other_ids["id"], kind=item.kind)
    for field in ("overview", "tagline", "poster_url", "backdrop_url", "logo_url", "certification"):
        if not getattr(meta, field):
            setattr(meta, field, getattr(other_meta, field))
    # 季集结构绝不从这里取
```

### D.6 结构与元数据的对齐（关键设计）

**结论：条目结构来自文件名，元数据按 `(season, episode)` 挂载。**

```
扫描/解析（文件名）          元数据（provider）
S01E01.mp4 → item(ep 1)  ←→  (1,1) → EpisodeMeta
S01E02.mp4 → item(ep 2)  ←→  (1,2) → EpisodeMeta
```

由此得到三个重要性质：

1. **切换 provider 不需要重建条目**，只更新「这集叫什么、剧情是什么、剧照是哪张」。`item.id` 不变 → **播放进度天然保留**。
2. provider 的集数比文件少 → 多出来的文件元数据为空，用文件名兜底展示。
3. provider 的集数比文件多 → 多余的 `EpisodeMeta` 直接忽略，不生成空集。

**动漫绝对集号特例**：文件名是纯数字（`01.strm`…`24.strm`）时，默认映射成 `S01E{n}`；若该库 `season_type=absolute`，则按 provider 的绝对顺序（`/series/{id}/episodes/absolute`）把 1..N 映射到实际的 `(season, episode)`。

**禁止**：不要按 provider 的季数去创建/删除条目。条目的存在性只由文件决定。

### D.7 图片下载队列

新增表（补充 §7）：

```sql
CREATE TABLE image_task (
  id          INTEGER PRIMARY KEY,
  item_id     INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,        -- poster | backdrop | logo | still | avatar
  remote_url  TEXT NOT NULL,
  status      TEXT NOT NULL,        -- pending | downloading | done | failed | broken
  retry       INTEGER NOT NULL DEFAULT 0,
  error       TEXT,
  updated_at  TEXT NOT NULL
);
CREATE INDEX idx_image_status ON image_task(status);
```

**状态机**

```
pending ──► downloading ──► done
               │
               ├─ 可重试错误 ──► pending (retry+1)
               └─ 404/410 ────► broken（不再重试）
retry > 3 ─────────────────► failed（保留占位图）
```

**规则**

1. 去重键：`sha1(remote_url)` —— 同一张图被多个条目引用时只下载一次。
2. 每种图生成固定变体：poster `w342/w500`、backdrop `w780/w1280`、thumb `w185`，统一转 WebP(q=82)。
3. 下载并发 4；单张超时 20s。
4. 主图（poster/backdrop）**同步完成**后才把条目置为可展示；头像与剧照允许异步补。
5. backdrop 变化时，**必须**触发 `color_primary` 重算。
6. 全部完成后再写 `item.meta_hash`，避免半成品被当成「已是最新」。

### D.8 幂等、并发、事务

- **单条目的刮削用 singleflight**：`key = item.id`，同一时刻只有一个协程在处理。
- **事务边界**：一个条目的元数据 + 图片任务入队在**同一事务**内提交；图片下载本身在事务外。
- **任务检查点**：批量刮削时每完成 50 条写一次 `task_log.stats`，进程被杀后可续跑。
- **重复触发保护**：同一库的 `scrape` 任务未结束时，再次触发直接返回现有 task_id。

### D.9 错误分类

| 类型 | HTTP/现象 | 处理 |
|---|---|---|
| `auth` | 401 / 403 | 标记该 provider 本轮不可用，UI 顶部告警，任务降级到另一源 |
| `rate` | 429 | 读 `Retry-After`，退避后重排；计一次 retry |
| `network` | 超时 / 连接失败 | 重试 3 次（1s/4s/16s） |
| `notfound` | 404 | 标记 `failed`，不重试 |
| `parse` | JSON 结构异常 | 标记 `failed`，保存原始响应到日志（截断 4KB） |

### D.10 测试要点

- 为 10 部影片/剧集保存 **golden JSON**（provider 原始响应），单测只跑映射层，不联网。
- 打分单测：给同一 query 构造 5 个候选，断言排序与阈值判定。
- 季集对齐单测：构造「文件 12 集 / provider 24 集」与「文件 24 集 / provider 12 集」两种情况。
- 图片状态机单测：模拟 404、超时、重试耗尽。

---

## 附录 E：M6 伴侣 App 实现细则

### E.1 工程骨架

```
companion/
├─ app/
│  ├─ build.gradle.kts
│  └─ src/main/
│     ├─ AndroidManifest.xml
│     ├─ java/top/strmaction/companion/
│     │  ├─ MainActivity.kt
│     │  ├─ JsBridge.kt
│     │  └─ MpvLauncher.kt
│     └─ res/
│        ├─ drawable/banner.xml      # TV banner 320x180
│        └─ values/strings.xml
└─ build.gradle.kts
```

依赖：仅 `androidx.appcompat`、`androidx.activity:activity-ktx`。**不要**引入网络库——进度上报交给网页做（见 E.7）。

```kotlin
android {
    compileSdk = 34
    defaultConfig {
        applicationId = "top.strmaction.companion"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }
}
```

### E.2 AndroidManifest

```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <uses-permission android:name="android.permission.INTERNET" />

  <!-- 电视上不要求触摸屏 -->
  <uses-feature android:name="android.hardware.touchscreen" android:required="false" />
  <uses-feature android:name="android.software.leanback" android:required="false" />

  <application
      android:label="@string/app_name"
      android:banner="@drawable/banner"
      android:usesCleartextTraffic="true"     <!-- 见 E.9 -->
      android:theme="@style/Theme.AppCompat.NoActionBar">

    <activity android:name=".MainActivity"
              android:exported="true"
              android:configChanges="orientation|screenSize|keyboardHidden"
              android:screenOrientation="landscape">
      <intent-filter>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
        <category android:name="android.intent.category.LEANBACK_LAUNCHER" />
      </intent-filter>
    </activity>

    <!-- Android 11+ 包可见性：必须声明，否则查不到 mpv -->
    <queries>
      <package android:name="is.xyz.mpv" />
    </queries>
  </application>
</manifest>
```

> `<queries>` 是必踩的坑：不声明的话，`packageManager` 看不到 mpv，直接抛 `ActivityNotFoundException`。

### E.3 WebView 配置

```kotlin
webView.settings.apply {
    javaScriptEnabled = true
    domStorageEnabled = true
    mediaPlaybackRequiresUserGesture = false
    loadWithOverviewMode = true
    useWideViewPort = true
    cacheMode = WebSettings.LOAD_DEFAULT
    allowFileAccess = false
    allowContentAccess = false
    // 让服务端能识别「这是伴侣 App」
    userAgentString = userAgentString + " StrmActionCompanion/1.0"
}

webView.webViewClient = object : WebViewClient() {
    override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
        val url = req.url.toString()
        // 伴侣 App 内不需要 intent://，但要防页面降级时把 WebView 带飞
        if (url.startsWith("intent://")) {
            runCatching {
                val intent = Intent.parseUri(url, Intent.URI_INTENT_SCHEME)
                startActivity(intent)
            }
            return true
        }
        return false
    }
}

webView.loadUrl(BuildConfig.APP_URL)     // 首次向导里让用户填，存 SharedPreferences
```

`onBackPressed`：优先 `webView.canGoBack()`，到底了再退出，避免电视上误退。

### E.4 JS Bridge

```kotlin
class JsBridge(
    private val activity: MainActivity,
    private val allowedHost: String,          // 从配置的服务器地址解析，防第三方页面调用
) {
    @JavascriptInterface
    fun play(url: String, title: String, positionMs: Int, subsJson: String) {
        if (isTrustedOrigin()) activity.runOnUiThread {
            activity.launchMpv(url, title, positionMs, subsJson)
        }
    }

    @JavascriptInterface fun version(): String = BuildConfig.VERSION_NAME

    private fun isTrustedOrigin(): Boolean {
        val host = activity.currentWebHost() ?: return false
        return host.equals(allowedHost, ignoreCase = true)
    }
}
```

```kotlin
webView.addJavascriptInterface(JsBridge(this, host), "StrmActionNative")
```

**注意**：`@JavascriptInterface` 方法运行在 WebView 的 JavaBridge 线程，**不是主线程**——所有启动 Activity 的操作必须 `runOnUiThread`。

页面对应：

```ts
const native = (window as any).StrmActionNative
if (native?.play) native.play(url, title, positionMs, JSON.stringify(subs))
```

### E.5 拉起 mpv（本文最关键的 6 个坑）

```kotlin
private val playLauncher = registerForActivityResult(
    ActivityResultContracts.StartActivityForResult()
) { result -> onPlayResult(result.resultCode, result.data) }

fun launchMpv(url: String, title: String, positionMs: Int, subsJson: String) {
    val subs = parseSubs(subsJson)
    val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(Uri.parse(url), "video/any")   // ①
        setPackage(MpvLauncher.packageName)            // ②
        putExtra("title", title)
        putExtra("position", positionMs.coerceAtLeast(0))
        if (subs.isNotEmpty()) {
            putExtra("subs", subs.toTypedArray())
            putExtra("subs.enable", subs.toTypedArray())
        }
    }
    try {
        playLauncher.launch(intent)                    // ③
    } catch (e: ActivityNotFoundException) {
        toast("未安装 mpv，请先安装 mpv-android")
    }
}
```

| # | 坑 | 说明 |
|---|---|---|
| ① | **`type` 必须是 `video/any`** | SmartStrm 的解析地址通常没有 `.mp4` 后缀，用 `video/*` 或按扩展名推断会被拒；`video/any` 是 mpv 官方约定的强制打开方式 |
| ② | **必须 `setPackage`** | 否则弹系统播放器选择器，用户选了别的播放器就没有 UA 配置，必然 403 |
| ③ | **绝对不能用 `FLAG_ACTIVITY_NEW_TASK`** | 一旦加上，`onActivityResult` 永远不会回调，进度永远拿不到。用 `registerForActivityResult` + 不带该 flag 的 Intent |
| ④ | 包名可能不同 | 官方 mpv-android 是 `is.xyz.mpv`；用户若装的是 mpvKt 等分支，包名不同 → 做成设置项，默认 `is.xyz.mpv` |
| ⑤ | `<queries>` 未声明 | Android 11+ 直接 `ActivityNotFoundException` |
| ⑥ | 返回后焦点丢失 | 在 `onResume` 里 `webView.requestFocus()` |

### E.6 结果回传与幂等

mpv-android 的结果约定（官方 intent 规范）：

| 字段 | 含义 |
|---|---|
| `resultCode` | `RESULT_OK` 播放结束/用户退出；`RESULT_CANCELED` 播放失败 |
| `data.position` | 最后播放位置（毫秒）；**正常播完时该 extra 不存在** |
| `data.duration` | 总时长（毫秒）；正常播完时不存在 |

```kotlin
private fun onPlayResult(resultCode: Int, data: Intent?) {
    if (resultCode != Activity.RESULT_OK) return
    val finished = data?.hasExtra("position") == false
    val pos = data?.getIntExtra("position", -1) ?: -1
    val dur = data?.getIntExtra("duration", -1) ?: -1

    val payload = ProgressPayload(
        itemId = currentItemId,
        positionMs = if (finished) 0 else pos.coerceIn(0, maxOf(dur, 0)),
        durationMs = dur,
        finished = finished,
        clientKey = "$currentItemId-${System.currentTimeMillis()}",  // 幂等键
    )
    reportProgress(payload)      // 见 E.7
}
```

**幂等要求**：服务端对同一 `item_id` 的重复 `clientKey` 只处理一次（或允许覆盖但要保证单调：新位置不比旧位置倒退超过 5 秒，除非 `finished=true`）。

### E.7 进度上报：交给网页做，不要在原生里复制 Cookie

WebView 里的登录态在 `CookieManager` 里，原生侧再拼一次请求容易踩 Cookie 域/`HttpOnly`/`SameSite` 的坑。最省事且最不容易出错的做法是**让页面发请求**：

```kotlin
private fun reportProgress(p: ProgressPayload) {
    val js = """
        window.StrmActionReport && window.StrmActionReport(${p.itemId}, ${p.positionMs}, ${p.durationMs}, ${p.finished});
    """.trimIndent()
    webView.post {
        webView.evaluateJavascript(js, null)
        webView.reload()      // 让「继续观看」立刻反映新进度
    }
}
```

页面对应：

```ts
window.StrmActionReport = (itemId, positionMs, durationMs, finished) => {
  fetch(`/api/items/${itemId}/progress`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ position_ms: positionMs, duration_ms: durationMs, finished }),
  })
}
```

> 这样原生侧零网络代码、零鉴权逻辑；token 过期、Cookie 变更都由浏览器自己处理。

### E.8 TV 适配

- `LEANBACK_LAUNCHER` + `android:banner`（320×180），否则电视桌面看不到图标。
- 全屏沉浸：`WindowCompat.setDecorFitsSystemWindows(window, false)` + 隐藏系统栏。
- 页面需启用 §14.4 的 TV 模式（`?tv=1` 或 UA 含 `StrmActionCompanion`）；建议**伴侣 App 直接带 `?tv=1` 加载**，免检测。
- 方向键交给 WebView 的原生焦点系统，但页面必须给每个可交互元素 `tabindex` 与自定义焦点顺序。
- 遥控器返回键 = 浏览器后退；`isFinishing` 时才退出 App。

### E.9 明文 HTTP 与局域网

- 若服务器是内网 `http://192.168.x.x:8080`，必须 `android:usesCleartextTraffic="true"`（或更严谨地用 `network_security_config` 只放行该网段）。
- 不要为了省事全局允许明文却把 App 暴露在公网环境——首启动让用户填地址，并校验是内网或已配置 HTTPS。

### E.10 构建与签名

```bash
cd companion
./gradlew assembleRelease \
  -Pandroid.injected.signing.store.file=release.keystore \
  -Pandroid.injected.signing.store.password=*** \
  -Pandroid.injected.signing.key.alias=strmaction \
  -Pandroid.injected.signing.key.password=***
```

产物：`app/build/outputs/apk/release/app-release.apk`，重命名为 `strmaction-companion-v1.apk` 随 release 发布。

安装（电视）：

```bash
adb connect <TV_IP>:5555
adb install -r strmaction-companion-v1.apk
```

### E.11 测试清单

- [ ] 电视桌面能看到图标（banner 正常，不是白块）
- [ ] 首次启动能输入并保存服务器地址
- [ ] 点播放 → 直接进 mpv（**不弹选择器**）
- [ ] mpv 未安装时给出明确提示，App 不崩
- [ ] 播放 30 秒后返回 → 服务端 `play_progress` 有值
- [ ] 再次播放 → 从上次位置继续（误差 < 3 秒）
- [ ] 播完 → `finished=true`，位置归零，自动起下一集
- [ ] 遥控器：上下左右、确定、返回均正常；无焦点丢失
- [ ] 切后台 10 分钟再回来，WebView 不白屏（`onResume` 检查）
