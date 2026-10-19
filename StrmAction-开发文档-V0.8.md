# StrmAction 开发文档（v0.8 / 可交付给开发 Agent）

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
| **v0.8** | **决策：伴侣 App 内置 Media3 播放器**（替代外部 mpv 成为默认播放路径），外部 mpv 降级为兜底；进度从「退出时回传」升级为「5 秒实时心跳」，R10 风险大幅收敛；新增 `play_token` 机制避免原生层碰 Cookie；重写 §12 与附录 E；功能清单更新为 66 项，v1 工期 17.5 → **20.5 人日** |
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
6. 点播放 → 把 `.strm` 内容的 URL 交给播放器：**伴侣 App 内用内置 Media3 播放**（默认），失败或用户选择时降级到外部 mpv；桌面用进程/IPC；最终兜底为复制链接。
7. 单管理员账号登录，全站需鉴权。
8. **独立完整**：不依赖 Jellyfin / Emby / Plex 等任何媒体服务器，单容器即可提供完整媒体库体验。
9. **元数据可维护**：支持重新刮削、单条刷新、手动编辑字段、手动绑定，保证库可以长期演进。
10. **电视一等公民**：提供 Android 伴侣 App，内含 Media3 播放器，实现一键播放、**实时进度**、断点续播、无缝连播（见 §12.8）。
11. **中文优先**：界面文案仅中文，不实现多语言切换；但所有文案集中在一个常量文件，便于日后扩展。

### 2.2 非目标（MUST NOT）

- ❌ 不做视频转码
- ❌ 不做视频流中转/反代/缓存
- ❌ 不实现网盘登录、不做 Alist 的替代
- ❌ **不依赖、不读取、不迁移任何 Jellyfin / Emby / Plex 的数据**（本项目是替代品，不是外挂）
- ❌ 不做多用户/权限体系（仅单管理员）
- ❌ 不做弹幕、评论、社交
- ❌ 不做网页内嵌播放器（WebView 里的 `<video>` 不用于播视频流；播放由原生播放器承担）
- ❌ 不做多语言 UI（v1 仅中文；元数据语言可配，那是数据层不是 UI）
- ❌ 不做 iOS / tvOS 伴侣 App（iOS 端直接用浏览器方案）

> **注意区分**：伴侣 App 的内置 Media3 播放器是**客户端解码 + 直连网盘**，视频字节不经过服务器，因此与「不做中转」并不冲突。

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
┌───────────────────────────────────────────────────────────────┐
│          浏览器（手机 / 桌面 / TV）  React SPA（后端托管）        │
└──────────────┬──────────────────────────────┬─────────────────┘
               │ REST /api/*                  │ 降级：intent:// / HTTP
               ▼                              ▼
┌──────────────────────────────┐   ┌────────────────────────────┐
│  StrmAction 后端（FastAPI）   │   │  无伴侣 App 时的降级通道      │
│  ├─ API 层                   │   │  ├─ 浏览器 intent:// → mpv   │
│  ├─ 扫描器 Scanner           │   │  └─ 桌面 mpv（spawn + IPC）  │
│  ├─ 解析器 Parser            │   └────────────────────────────┘
│  ├─ 刮削器 Scraper (双源)     │
│  ├─ 播放分发 PlayerDispatcher│
│  └─ 任务调度 Scheduler       │
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

┌───────────────────────────────────────────────────────────────┐
│  Android 伴侣 App（电视一等公民）                                │
│  MainActivity(WebView) ──JS桥──► PlayerActivity(Media3)         │
│         ▲                              │                        │
│         │                              ├─ 5s 心跳 → /progress    │
│         └──────── 返回后刷新 ───────────┘                        │
│                 PlayerActivity ──失败/手动──► 外部 mpv（兜底）     │
└───────────────────────────────────────────────────────────────┘
```

**关键约束**：后端对视频数据**永不发起请求**。它只读取 `.strm` 的文本内容，以及下载海报/背景图。内置播放器由**客户端**解码并直连网盘，视频字节不经过服务器。

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
| 播放（伴侣 App） | **AndroidX Media3 / ExoPlayer 1.4+** | 市占最高、体积小、硬件解码与 HDR 直通最好、原生支持自定义请求头 |
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
│  │  │  ├─ registry.py          # Provider 插件注册中心（@register_provider 开放扩展）
│  │  │  ├─ service.py           # 刮削核心调度编排
│  │  │  ├─ tmdb.py              # 附录 D.2
│  │  │  ├─ tvdb.py              # 附录 D.3
│  │  │  ├─ nfo.py               # 本地 .nfo（可选）
│  │  │  ├─ matcher.py           # 归一化 + 打分（D.4）
│  │  │  └─ merge.py             # 跨源补空（D.5.1）
│  │  ├─ images.py               # 下载队列、转码（保留RGBA透明）、取色（D.7）
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
│  │  ├─ components/
│  │  │  ├─ settings/            # 设置模块化子组件（Library / Scraper / Player / System）
│  │  │  ├─ HeroCarousel.tsx
│  │  │  ├─ PosterCard.tsx
│  │  │  └─ ...
│  │  ├─ i18n/zh-CN.ts           # 全部界面文案（唯一来源，不许散落组件）
│  │  ├─ api/                    # client.ts / hooks.ts
│  │  ├─ store/
│  │  └─ styles/
│  └─ vite.config.ts
├─ companion/                    # Android 伴侣 App（M6，见附录 E）
│  └─ app/src/main/java/top/strmaction/companion/
│     ├─ MainActivity.kt         # WebView 壳 + JS 桥
│     ├─ JsBridge.kt
│     ├─ PlayerActivity.kt       # Media3 内置播放器
│     ├─ player/                 # 播放器解耦模块
│     │  ├─ PlayerDrawer.kt      # 40% 抽屉交互与集数渲染
│     │  ├─ PlayerTrackHelper.kt # 音轨 / 字幕选择
│     │  ├─ PlayerSpeedHelper.kt # 播放倍速与长按倍速菜单
│     │  └─ PlayerUiHelper.kt    # 样式与时间格式化
│     ├─ ProgressReporter.kt     # play_token 进度上报
│     └─ MpvFallback.kt          # 外部 mpv 兜底
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
  play_headers  TEXT,                      -- JSON：该库播放时需要的请求头（如百度 UA）
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

CREATE TABLE play_token (
  token         TEXT PRIMARY KEY,          -- pt_xxx
  item_id       INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,             -- 12h；只允许写该条目的进度
  revoked       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_play_token_item ON play_token(item_id);

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

## 12. 播放（核心）

> **v0.8 架构变更**：默认播放路径改为**伴侣 App 内置 Media3 播放器**；外部 mpv 降级为兜底方案。

### 12.0 为什么内置 Media3

| 收益 | 说明 |
|---|---|
| **进度实时** | 每 5 秒上报，断电/强杀最多丢 5 秒（外部播放器只能退出时回传） |
| **体验一体** | 播放器在 App 内，连播无跳转、无闪屏 |
| **请求头可控** | 每个库一套 UA/Referer，由服务端下发，不再依赖用户手改 `mpv.conf` |
| **体积/风险小** | APK +2~4MB，纯 JVM 层，不引入 native 崩溃面 |
| **硬件路径** | 走 MediaCodec 直出 Surface，HDR10 可直通电视由电视 tone mapping |

**明确代价**（必须写进 README）：

- 复杂 ASS 特效字幕（卡拉OK、动态定位、遮挡）**无法还原**——Media3 的字幕渲染只支持基础样式。
- 杜比视界 P5 在非 DV 设备上会绿屏/发紫，不会 tone map。
- 部分冷门封装/编码解不了。

→ 因此**必须保留外部 mpv 兜底**（§12.3），并在播放器错误时主动引导切换。

### 12.1 播放后端抽象

服务端不决定“用什么播”，只决定“把 URL 和参数交给谁”。客户端按能力选择：

| mode | 使用方 | 进度 | 说明 |
|---|---|---|---|
| `builtin` | 伴侣 App | **实时 5s** | 默认 |
| `external_mpv` | 伴侣 App / 浏览器 | 退出时一次 | 兜底，画质优先 |
| `browser_intent` | 浏览器（Chromium） | 无 | 无伴侣 App 时的降级 |
| `desktop_mpv` | 桌面浏览器 | 实时 5s（IPC） | 仅服务端与播放器同机时启用 |
| `copy` | 任意 | 无 | 最终兜底 |

**`POST /api/play/{item_id}` 响应**

```json
{
  "mode": "builtin",
  "item_id": 42,
  "title": "沙丘2",
  "play_url": "https://strm.example.com/xxxx",
  "resume_ms": 1830000,
  "duration_ms": 9960000,
  "headers": {
    "User-Agent": "pan.baidu.com",
    "Referer": "https://pan.baidu.com/"
  },
  "play_token": "pt_...",
  "next_item_id": 43
}
```

- `headers` 来自库配置（`library.play_headers`），不是硬编码——不同网盘/不同架子的要求不同。
- `play_token`：**item 级、12 小时有效**，只用于进度回传，避免原生层去碰 Cookie（见 §12.7）。
- `next_item_id`：供无缝连播预加载。

### 12.2 内置播放器（Media3）— 默认路径

**仅在伴侣 App 内可用**（浏览器里没有原生播放器）。

**初始化要点**

```kotlin
// 1) 带请求头的数据源（这一段是解决百度 UA 的关键）
val headers = mapOf(
    "User-Agent" to "pan.baidu.com",
    "Referer" to "https://pan.baidu.com/",
)
val dataSourceFactory = DefaultHttpDataSource.Factory()
    .setDefaultRequestProperties(headers)
    .setAllowCrossProtocolRedirects(true)      // 302 https→http 时必需
    .setConnectTimeoutMs(15_000)
    .setReadTimeoutMs(30_000)

// 2) 组播放器
val player = ExoPlayer.Builder(context)
    .setMediaSourceFactory(DefaultMediaSourceFactory(dataSourceFactory))
    .setRenderersFactory(
        DefaultRenderersFactory(context)
            .setEnableDecoderFallback(true)     // 硬解失败自动回软解
    )
    .build()

// 3) 带续播起播
val item = MediaItem.Builder().setUri(playUrl).build()
player.setMediaItem(item, resumeMs)
player.prepare()
```

**必须实现的监听**

| 事件 | 处理 |
|---|---|
| `onPlaybackStateChanged(STATE_READY)` | 开始 5 秒进度心跳 |
| `onIsPlayingChanged` | 暂停时立即上报一次（防丢） |
| `onPlayerError` | 暂停心跳 → 弹「此片源播放失败，用外部播放器打开？」→ 切 §12.3 |
| `STATE_ENDED` | 上报 `finished=true` → 自动连播 `next_item_id` |

**进度心跳（MUST）**

```
每 5s：POST /api/items/{id}/progress
       Authorization: Bearer <play_token>
       { position_ms, duration_ms, finished: false }
```

- 退到后台时**立即**上报一次并停止心跳；回到前台恢复。
- 网络失败不重试到阻塞播放，进入本地队列，下次成功时补发（最多 3 条，只保留最新）。

**音频与 HDR**

- 音频直通/offload 交给设备的 MediaCodec 能力，**不要**强行关闭隧道模式。
- 播放器 UI 上不要显示“HDR/DV”角标，除非确实读到了 `MediaFormat` 的 HDR 信息——避免虚假宣传。

**字幕**

- 内封字幕：Media3 自动识别轨道，UI 提供切换与延迟调节（±0.5s 步进）。
- 外挂字幕：读取同目录 `.srt/.ass`（若 SmartStrm 已复制），以 `SubtitleConfiguration` 附加。
- **复杂 ASS 特效不还原**：UI 上给一句提示，并提供「用 mpv 打开」。

### 12.3 外部 mpv 兜底（伴侣 App 内）

触发时机：
1. 用户在播放器菜单里主动选「用 mpv 打开」；
2. 内置播放器 `onPlayerError` 后用户确认切换。

实现沿用官方 intent 规范（细节见附录 E.5）：

```kotlin
Intent(Intent.ACTION_VIEW).apply {
    setDataAndType(Uri.parse(playUrl), "video/any")   // 无扩展名 URL 必须用 video/any
    setPackage("is.xyz.mpv")
    putExtra("title", title)
    putExtra("position", resumeMs.toInt())
}
```

- 进度只能拿到**退出时**的 result intent（`position`/`duration`）。
- 兜底路径的进度粒度在 UI 上要标注（「来自外部播放器，退出时保存」）。

### 12.4 浏览器：`intent://` 拉起 mpv（降级）

无伴侣 App 且使用 Chromium 内核浏览器时可用。约束与实现见附录 E.5 的坑位表。

- 仅 Chromium 支持 `intent://`；Android TV 自带浏览器基本不支持。
- **拿不到任何进度**，UI 必须提供「标记已看」。

### 12.5 桌面：spawn mpv + IPC

```bash
mpv --no-terminal --force-window --start=<秒> \
    --http-header-fields="User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/" \
    --input-ipc-server=/tmp/strmaction-mpv.sock "<play_url>"
```

通过 JSON IPC 订阅 `time-pos`，每 5s 回写进度。仅在服务端与播放器同机时启用。

### 12.6 兜底：复制链接

任何环境都提供，并提示需在 mpv 侧配置 UA。

### 12.7 播放会话与进度回传

**创建会话**

```
POST /api/play/{item_id}
  auth: 登录 Cookie
  → { mode, play_url, resume_ms, headers, play_token, next_item_id, ... }
```

**回传进度**

```
POST /api/items/{id}/progress
  auth: Cookie（网页） 或 Authorization: Bearer <play_token>（原生播放器）
  body: { position_ms, duration_ms, finished }
```

- `play_token`：**item 级、12h 有效、只能写该条目的进度**。设计目的：让原生播放器不必接触 Cookie（`HttpOnly` 的会话不适合在 native 层复制来复制去）。
- 同一 token 可多次使用（心跳需要）；服务端只校验 `item_id` 匹配与未过期。

**写入规则**

1. `finished=true` 或 `position/duration > 0.9` → 标记已看、`position_ms` 归零。
2. `duration_ms` 缺失/为 0 → 只存绝对位置，不算百分比。
3. 位置越界（负、大于时长）直接丢弃，不写库。
4. UPSERT，`item_id` 唯一。
5. 心跳写入要**幂等且高频友好**：单条 UPDATE，不做全表扫描。

**离线补发（SHOULD）**：原生端维护一个最多 3 条的本地队列，网络恢复后补发最新一条。

### 12.8 伴侣 App 结构

```
MainActivity（WebView）
   │  用户点播放
   ▼
JsBridge.play(itemId)
   │  GET /api/play/{itemId}（WebView 带 Cookie）
   ▼
PlayerActivity（原生）
   ├─ Media3 播放
   ├─ 每 5s → POST /progress（Bearer play_token）
   └─ 菜单：字幕 / 音轨 / 倍速 / 用 mpv 打开
   │  返回
   ▼
WebView 刷新「继续观看」
```

**JS 桥接口**

```ts
interface StrmActionNative {
  play(itemId: number): void          // 原生播放器
  playExternal(itemId: number): void  // 直接交给 mpv
  version(): string
}
```

- 原生侧收到 `play` 后自己再请求 `/api/play/{itemId}` 拿 URL 与 headers，**网页不传 URL**（避免把播放凭证暴露在 JS 层）。
- 检测 `window.StrmActionNative` 决定 UI 是否显示「内置播放」按钮。

### 12.9 进度粒度矩阵

| 端 | 来源 | 粒度 | 断点续播 |
|---|---|---|---|
| 伴侣 App · 内置 Media3 | 5s 心跳 + 事件驱动 | **准实时** | ✅ |
| 伴侣 App · 外部 mpv | 退出时 result intent | 每次退出一次 | ✅（可能丢最后一段） |
| 桌面 · mpv IPC | `time-pos` 订阅 | 准实时 | ✅ |
| 浏览器 · intent:// | 无 | — | ❌ 仅手动标记 |

### 12.10 自动连播

- **内置播放器**：`STATE_ENDED` 直接用 `next_item_id` 起下一集，播放器不销毁，**无黑屏无跳转**。
- **外部 mpv**：退出后回到 App 再起下一集，顶部 toast 给 5 秒取消窗口。
- 两种路径都要遵守：下一集若已标记已看，则继续往后找，直到找到未看的一集或到剧终。

### 12.11 从「继续观看」移除（保留进度）

- **业务需求**：用户常希望清理首页「继续观看」中不想再追或临时点开的剧集/电影，但不能清空其播放进度（后续在媒体库或剧集详情中浏览时，各集进度条与已看打勾仍需正确保留）。
- **字段支持**：`PlayProgress` 模型新增 `dismissed: bool = False` 字段（SQLite 数据库自迁移添加 `dismissed BOOLEAN DEFAULT 0`）。
- **首页聚合**：`GET /home` 查出待看进度时过滤 `PlayProgress.dismissed == False`。
- **移除接口**：`DELETE /api/items/{id}/continue` 与 `POST /api/items/{id}/dismiss-continue`：
  - 针对电影/单集：将对应条目的 `dismissed` 置为 `True`；
  - 针对电视剧（`kind == "series"`）：级联将整部剧名下所有单集的 `dismissed` 置为 `True`，确保整剧完全从首页继续观看行消失；
  - 数据只标记隐藏，`position_ms`、`duration_ms` 与 `finished` 状态原样保留。
- **重新激活**：当用户在详情页或媒体库再次播放该剧集并上报新进度（`POST /api/items/{id}/progress`）时，自动重置 `row.dismissed = False`，使重新观看的条目恢复回到首页「继续观看」。

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
| DELETE/POST | `/items/{id}/continue` | 从首页「继续观看」移除该条目（保留其播放进度与已看记录，见 §12.11） |
| GET | `/search` | 全库搜索（标题/别名/演职员） |
| GET | `/home` | 首页聚合：`hero[]`, `continue[]`, `recent[]`, `rows[]` |
| POST | `/play/{item_id}` | 返回 `mode / play_url / resume_ms / headers / play_token / next_item_id` |
| POST | `/items/{id}/progress` | `{position_ms, duration_ms, finished}`；鉴权支持 Cookie 或 `Bearer <play_token>`（见 §12.7） |
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
| 详情 `/item/:id` | 全屏背景（模糊 + 渐隐）、标题 logo、评分/年份/时长、简介、演职员、**选集**、播放按钮（伴侣 App 内走内置播放器）、版本切换、重新匹配入口 |
| 搜索 `/search` | 即时搜索、热门标签、结果网格 |
| 设置 `/settings` | 库管理（含播放请求头）、TMDB/TVDB Key、源优先级、语言、季集类型、播放方式（内置/外部）、目录模板、扫描计划 |
| 任务 `/tasks` | 扫描/刮削进度、失败清单、日志 |

### 14.2 交互要求（对齐 VidHub / SenPlayer 的质感）

- **Hero 轮播**：8s 自动切换，交叉淡入 + 极缓慢 Ken Burns 缩放（1.0 → 1.05）；鼠标悬停或遥控聚焦即暂停；指示点细小、半透明。
- **卡片**：2:3 海报，圆角 12px，悬停上浮 4px + 阴影加深 + 300ms 缓动；缺图时显示主色渐变占位。
- **转场**：`framer-motion` 的 `layoutId` 做「海报 → 详情页背景」的共享元素过渡。
- **骨架屏**：所有异步区域必须有 skeleton，禁止白屏。
- **播放反馈**：点击播放后按钮进入 loading；伴侣 App 内直接进内置播放器（无 toast）；浏览器降级时 toast「已交给 mpv」；失败给出原因与「复制链接」。
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

> 电视端的正式交付形态是**伴侣 App**（§12.8）：WebView 负责浏览，**原生 PlayerActivity 负责播放**；浏览器 + `?tv=1` 仅作为调试与降级入口。
> 因此电视端的焦点管理只需要覆盖「浏览页」，播放页的遥控逻辑由原生播放器负责（附录 E.8）。

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
  mode: builtin                           # builtin | external | auto
                                          # builtin 仅在伴侣 App 内生效；浏览器自动降级
  progress_interval_ms: 5000              # 内置播放器心跳间隔
  play_token_ttl_hours: 12
  fallback_on_error: true                 # 内置播放失败时提示切 mpv
  mpv_path: /usr/bin/mpv                  # 桌面模式
  mpv_extra_args:
    - "--http-header-fields=User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/"

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
6. **`play_token` 最小权限**：12h 有效、绑定单个 `item_id`、只能写该条目进度、不可读取任何列表或 URL；注销登录时不强制吊销（到期自然失效）。
7. **原生层不持有会话**：伴侣 App 的播放器只用 `play_token` 与后端通信，不在 native 层复制或持久化会话 Cookie。

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

### M4 服务端播放分发（1d）
- [ ] `POST /api/play/{id}` 返回 `mode / play_url / resume_ms / headers / play_token / next_item_id`
- [ ] `play_token` 签发与校验（item 级、12h、只能写该条目进度）
- [ ] 进度接口同时接受 Cookie 与 Bearer 两种鉴权
- [ ] 库级请求头（`play_headers`）可配置并正确下发
- [ ] 桌面模式能 spawn mpv 并回写进度
- [ ] 浏览器 `intent://` 降级 + 「复制链接」兜底可用
- [ ] 播放 URL 不出现在任何日志明文里

### M5 打磨（2d）
- [ ] TV 模式方向键导航顺畅，无焦点丢失
- [ ] 转场与轮播动效达到「可截图发朋友圈」的程度
- [ ] 任务页能看到扫描/刮削进度与失败原因

### M6 伴侣 App + 内置播放器（7d）
- [ ] WebView 壳 + JS 桥，TV 遥控器可完整操作
- [ ] **内置 Media3 播放器**：请求头生效（百度片源可播）、302 跨协议跳转不报错
- [ ] 起播使用 `resume_ms` 续播（误差 < 3 秒）
- [ ] **5 秒心跳**写入 `play_progress`；暂停 / 退后台各补一次；强杀最多丢 5 秒
- [ ] `play_token` 鉴权可用，且 token 过期时给出明确提示
- [ ] 播放器错误 → 弹窗 → 一键切外部 mpv 播放成功
- [ ] 内封字幕切换、外挂 `.srt` 加载
- [ ] 播完自动连播下一集，**无黑屏无跳转**
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
| 内置播放器遇到不支持的编码 | 弹「用 mpv 打开？」不崩溃；确认后 mpv 能播 |
| 直链 302 从 https 跳到 http | 内置播放器正常播放（`allowCrossProtocolRedirects`） |
| 播放中网络中断 | 播放器显示缓冲/错误，进度心跳不覆盖已有值 |
| `play_token` 过期后心跳 | 返回 401，UI 提示「请重新播放」，不静默失败 |

### 18.3 安全用例

- 未登录访问 `/api/play/1` → 401
- `root_path` 之外的符号链接 → 拒绝
- 逾期 `session_token` → 403

---

## 19. 风险与待决

| ID | 风险 | 影响 | 应对 |
|---|---|---|---|
| R1 | Android TV 浏览器不支持 `intent://` | TV 上无法一键播放 | **已由伴侣 App 内置 Media3 播放器解决**；`intent://` 仅作无伴侣 App 时的降级 |
| R2 | 浏览器模式无法回传进度 | 纯网页无「继续观看」 | 伴侣 App 内置播放器已解决；纯网页仍以「手动标记已看」兜底 |
| R3 | TMDB / TVDB 国内访问不稳 | 刮削失败 | 每个 provider 独立配 `proxy` / 自建反代；双源互为降级；`.nfo` 兜底 |
| R4 | SmartStrm 目录命名不规范 | 解析失败 | 模板可配置 + 手动修正；建议用户在 SmartStrm 里开启 TMDB 批量重命名 |
| R5 | 网盘解析地址有时效 | 播放 403 | 本设计只存解析地址、播放时实时交给 mpv，已规避；若用户存的是直链，则需提示重新生成 strm |
| R6 | 一个目录里混多种媒体类型 | 归类错乱 | 库按类型隔离；`tv` 库里出现孤立文件时归为「其他」 |
| R7 | TMDB 对冷门/国产老片中文数据缺失 | 详情页信息稀疏 | TVDB 可补部分数据；仍缺则手动编辑 + 支持本地 `.nfo`；README 说明可配合 tinyMediaManager |
| R8 | 用户按 Jellyfin 习惯期待「转码/字幕搜索/多端同步」 | 认知落差 | README 明确非目标；字幕由 mpv 自动加载同名 `.srt`（SmartStrm 可复制） |
| R9 | **双源季集结构不一致**（TMDB 2 季 vs TVDB 1 季 24 集） | 集数与文件对不上，出现空集/错位 | §10.2.3 已规定：季集**只取 winning provider**，绝不混用；切源时触发整剧重建并保留已看进度（按 `SxxExx` 重映射） |
| R10 | 外部 mpv 路径的进度只在退出时回传 | 该路径下断电/强杀会丢进度 | **默认路径已改为内置 Media3（5 秒心跳）**，风险大幅收敛；外部 mpv 作为兜底时，UI 标注「退出时保存」 |
| R11 | **Media3 的能力边界**：复杂 ASS 特效不还原、DV P5 在非 DV 设备绿屏、冷门封装解不了 | 部分片源观感差或播不了 | 播放器错误时**主动弹窗引导切外部 mpv**；README 与播放器菜单都要写明；不允许静默失败 |
| R12 | 内置播放器的 native 解码崩溃/ANR | 单个片源拖垮 App | 不用 native 渲染层（纯 Media3），`setEnableDecoderFallback(true)`；崩溃日志上报到 `/api/tasks` 附件（可选） |

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
3. **M3 与 M4 可以并行**；M4 先用 `copy` 兜底打通链路，再实现 `play_token` 与浏览器 `intent://` 降级。
4. **M6 在 M4 之后做、在 M5 之前做**。M6 内部顺序建议：
   1. WebView 壳 + JS 桥（半天，先能跑起来）
   2. **内置 Media3 播放（核心，2–3 天）**：先跑通「带 UA 头 + 302 跨协议 + 续播」，再补 UI
   3. 5 秒心跳 + 连播（1 天）
   4. 外部 mpv 兜底（半天）
   5. 原生播放器 UI 与 TV 遥控打磨（1–2 天）
   之所以 M6 必须在 M5 之前：TV 端的焦点与动效，必须在内置播放器成形后真机验证才有意义，顺序反了要返工两次。
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
| 33 | **内置 Media3 播放器**（伴侣 App 默认路径） | **P0** | §12.2 |
| 34 | 自定义请求头（每库一套 UA/Referer，服务端下发） | **P0** | §12.1 |
| 35 | 外部 mpv 兜底（intent，含 6 个坑的处理） | P0 | §12.3 |
| 36 | 浏览器 `intent://` 降级 | P1 | §12.4 |
| 37 | 桌面 spawn mpv + JSON IPC | P1 | §12.5 |
| 38 | 复制链接兜底 | P0 | §12.6 |
| 39 | 断点续播（`resume_ms`） | P0 | §12.7 |
| 40 | **5 秒进度心跳** + 暂停/退后台补写 | **P0** | §12.7 |
| 41 | `play_token`（item 级、12h、Bearer 鉴权） | **P0** | §12.7 |
| 42 | 播完 90% 自动标记已看、位置归零 | P0 | §12.7 |
| 43 | 手动标记已看 / 未看 | P0 | §13 |
| 44 | 自动连播下一集（内置无缝 / 外部 5 秒取消） | P0 | §12.10 |
| 45 | 字幕：内封切换、外挂 srt/ass 加载、延迟调节 | P1 | §12.2 |
| 46 | 播放 URL 视为凭证：鉴权 + 日志打码 | P0 | §16 |
| 47 | 播放失败自动降级（错误弹窗 → 切 mpv） | **P0** | §12.3 |

### C.6 界面

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 48 | 首页：Hero 轮播 + 继续观看 + 最近添加 + 分类横滑 | P0 | §14.1 |
| 49 | 详情页：背景模糊 + 主题色 + Logo + 演职员 + 选集 + 版本切换 | P0 | §14.1 |
| 50 | 搜索（标题/别名/演职员） | P0 | §14.1 |
| 51 | 设置页（库、Key、源优先级、季集类型、播放器、模板） | P0 | §14.1 |
| 52 | 任务页（扫描/刮削进度、失败清单、日志） | P0 | §14.1 |
| 53 | TV 模式（方向键焦点、安全区、10-foot UI） | P0 | §14.4 |
| 54 | 动效（共享元素转场、Ken Burns、骨架屏） | P0 | §14.2 |
| 55 | 首次启动向导（密码 → Key → 加目录 → 扫描） | P0 | §14.6 |
| 56 | 缺图/缺简介/缺标题的优雅降级 | P0 | §14.2 |
| 57 | 中文文案集中管理（`src/i18n/zh-CN.ts`，不散落组件） | P0 | §2.1 |

### C.7 运维与安全

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 58 | 单容器 Docker 部署 | P0 | §20 |
| 59 | 配置优先级（DB > yaml > 默认） | P0 | §15 |
| 60 | 数据导出/导入 + SQLite 备份 | P1 | §20 |
| 61 | 单管理员鉴权（argon2、登录限流、HttpOnly Cookie） | P0 | §16 |
| 62 | TMDB/TVDB 连通性测试 | P1 | §13 |
| 63 | 每个 provider 独立代理与限速 | P0 | §10.4 |

### C.8 伴侣 App（M6，v1 必做）

| # | 功能 | 优先 | 章节 |
|---|---|---|---|
| 64 | WebView 壳 + `window.StrmActionNative` 桥 | **P0** | §12.8 |
| 65 | PlayerActivity：Media3 播放 + 原生播放器 UI + TV 遥控 | **P0** | §12.2 |
| 66 | 续播 + 5 秒心跳 + 自动连播 + mpv 兜底 | **P0** | §12.7 |

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
| M4 | 服务端播放分发 + 浏览器降级 + 桌面 spawn | 1 |
| M6 | 伴侣 App + 内置 Media3 播放器（**v1 必做**） | 7 |
| M5 | 打磨（动效 / TV / 任务页） | 2 |
| **v1 合计** | | **20.5** |

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
├─ app/build.gradle.kts
└─ src/main/
   ├─ AndroidManifest.xml
   ├─ java/top/strmaction/companion/
   │  ├─ MainActivity.kt        # WebView 壳 + JS 桥
   │  ├─ JsBridge.kt
   │  ├─ PlayerActivity.kt      # Media3 播放器
   │  ├─ PlayerController.kt    # 心跳、续播、连播
   │  ├─ ProgressReporter.kt    # play_token 进度上报
   │  └─ MpvFallback.kt         # 外部 mpv 兜底
   └─ res/drawable/banner.xml   # TV banner 320x180
```

```kotlin
dependencies {
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")
    implementation("androidx.media3:media3-common:1.4.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
}
```

> 不需要 OkHttp：进度上报用 `HttpURLConnection` + `org.json`（系统自带），少一个依赖少一个坑。

```kotlin
android {
    compileSdk = 34
    defaultConfig {
        applicationId = "top.strmaction.companion"
        minSdk = 24
        targetSdk = 34
    }
}
```

### E.2 AndroidManifest

```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <uses-permission android:name="android.permission.INTERNET" />
  <uses-feature android:name="android.hardware.touchscreen" android:required="false" />
  <uses-feature android:name="android.software.leanback" android:required="false" />

  <application android:label="@string/app_name"
               android:banner="@drawable/banner"
               android:usesCleartextTraffic="true"
               android:theme="@style/Theme.AppCompat.NoActionBar">

    <activity android:name=".MainActivity" android:exported="true"
              android:screenOrientation="landscape"
              android:configChanges="orientation|screenSize|keyboardHidden">
      <intent-filter>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
        <category android:name="android.intent.category.LEANBACK_LAUNCHER" />
      </intent-filter>
    </activity>

    <activity android:name=".PlayerActivity"
              android:exported="false"
              android:launchMode="singleTask"
              android:screenOrientation="landscape"
              android:configChanges="orientation|screenSize|keyboardHidden"
              android:theme="@style/Theme.AppCompat.NoActionBar.Fullscreen" />

    <!-- Android 11+ 包可见性，否则查不到 mpv -->
    <queries><package android:name="is.xyz.mpv" /></queries>
  </application>
</manifest>
```

### E.3 MainActivity（WebView 壳）

```kotlin
webView.settings.apply {
    javaScriptEnabled = true
    domStorageEnabled = true
    mediaPlaybackRequiresUserGesture = false
    userAgentString = userAgentString + " StrmActionCompanion/1.0"
    allowFileAccess = false
    allowContentAccess = false
}
webView.addJavascriptInterface(JsBridge(this), "StrmActionNative")
webView.loadUrl("$serverUrl/?tv=1")
```

- 桥接方法运行在 **JavaBridge 线程**，所有 `startActivity` 必须 `runOnUiThread`。
- 桥接方法要校验 `webView.url` 的 host 与配置的服务器一致，防止第三方页面调用。
- 返回键：先 `webView.canGoBack()`，到底再退出。

### E.4 PlayerActivity（Media3 核心）

```kotlin
class PlayerActivity : AppCompatActivity() {
    private lateinit var player: ExoPlayer
    private lateinit var view: PlayerView

    private fun start(info: PlayInfo) {
        val headers = info.headers.orEmpty()

        val dsFactory = DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(headers)      // ← 百度 UA 在这里生效
            .setAllowCrossProtocolRedirects(true)      // ← 302 https→http 必需
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(30_000)

        player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dsFactory))
            .setRenderersFactory(
                DefaultRenderersFactory(this)
                    .setEnableDecoderFallback(true)    // 硬解失败自动回退软解
            )
            .setHandleAudioBecomingNoisy(true)
            .build()

        view.player = player
        player.setMediaItem(MediaItem.Builder().setUri(info.playUrl).build(), info.resumeMs)
        player.addListener(playbackListener)
        player.prepare()
        player.play()
    }
}
```

**事件处理（MUST）**

```kotlin
private val playbackListener = object : Player.Listener {
    override fun onPlaybackStateChanged(state: Int) {
        when (state) {
            Player.STATE_READY   -> controller.startHeartbeat()
            Player.STATE_ENDED   -> controller.onEnded()          // 上报 finished + 连播
            Player.STATE_BUFFERING -> view.showBuffering(true)
        }
    }
    override fun onIsPlayingChanged(isPlaying: Boolean) {
        if (!isPlaying) controller.flushProgressOnce()            // 暂停立即存一次
        controller.setHeartbeatActive(isPlaying)
    }
    override fun onPlayerError(error: PlaybackException) {
        controller.stopHeartbeat()
        showFallbackDialog(error)                                 // → MpvFallback
    }
}
```

**生命周期**

| 回调 | 动作 |
|---|---|
| `onStop` | 立即上报一次进度，停止心跳，`player.pause()` |
| `onDestroy` | `player.release()` |
| `onResume` | 恢复心跳（若仍在播） |

**播放控件与手势规范（v0.8 现代化升级）**

- **视觉与交互**：
  - 全面使用简洁精炼的现代矢量图标（VectorDrawable）替代旧版文字按钮；
  - 顶部栏：返回键、标题文本、画中画图标（仅支持设备）、更多菜单图标；
  - 屏幕正中：半透明悬浮播放/暂停大图标；
  - 屏幕右侧：半透明悬浮锁屏图标（锁定后收起所有控件并切换为解锁图标）；
  - 底部控制栏：渐变黑遮罩底，上方为高亮带刻度拖拽进度条（SeekBar），下方为「播放/暂停」、「上一集」、「下一集」、当前时间/总时长、弹性留白，以及右侧「选集」胶囊按钮、「倍速」胶囊按钮、「全屏/退出全屏」图标按钮。
- **手势控制**：
  - 单击屏幕：呼出 / 收起播放控件（播放状态下 4.5 秒无操作自动淡出）；
  - 双击左侧 35%：快退 10 秒，屏幕中心居中展示 `⏪ 快退 10 秒` 胶囊徽标并自动淡出；
  - 双击右侧 35%：快进 10 秒，屏幕中心居中展示 `⏩ 快进 10 秒` 胶囊徽标并自动淡出；
  - 双击中间区域：播放 / 暂停切换；
  - **长按倍速**：在屏幕任意位置长按触发触觉震动反馈（HapticFeedback），实时将播放速度提升至配置倍速，顶部浮动提示 `▶▶ 2.0x 快速播放中`；手指抬起（`ACTION_UP`/`ACTION_CANCEL`）立刻平滑恢复原先倍速并隐藏浮标；
  - **长按倍速设置**：在倍速弹出单选框底部或播放菜单中均提供「长按倍速设置」，支持快捷配置长按倍速（可选 1.5x / 2.0x（默认）/ 2.5x / 3.0x），配置值自动持久化至本地 `SharedPreferences`。

### E.5 进度心跳与 `play_token`

```kotlin
object ProgressReporter {
    fun post(baseUrl: String, token: String, itemId: Int,
             positionMs: Long, durationMs: Long, finished: Boolean) {
        val body = JSONObject(mapOf(
            "position_ms" to positionMs,
            "duration_ms" to durationMs,
            "finished" to finished,
        )).toString()

        val conn = URL("$baseUrl/api/items/$itemId/progress").openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        conn.setRequestProperty("Authorization", "Bearer $token")
        conn.connectTimeout = 5000
        conn.readTimeout = 5000
        conn.outputStream.use { it.write(body.toByteArray()) }
        conn.responseCode  // 2xx 即成功；失败入本地队列
    }
}
```

**规则**

1. 心跳间隔 5s；暂停、`STATE_ENDED`、`onStop` 各补一次。
2. 失败不重试阻塞播放：写入本地队列（最多 3 条，只留最新），下次成功时补发。
3. 位置钳制：`0 <= position <= duration`，越界直接丢弃。
4. `play_token` 12h 过期；若返回 401，提示「请回到列表重新播放」（下次点播放会换新 token）。

### E.6 错误与降级到 mpv

```kotlin
private fun showFallbackDialog(err: PlaybackException) {
    AlertDialog.Builder(this)
        .setTitle("此片源内置播放失败")
        .setMessage("可能是编码或字幕特效不支持，是否用 mpv 打开？")
        .setPositiveButton("用 mpv 打开") { _, _ -> MpvFallback.launch(this, currentInfo) }
        .setNegativeButton("返回", null)
        .show()
}
```

**外部 mpv 的 6 个坑（照抄即用）**

| # | 坑 | 后果 |
|---|---|---|
| ① | `type` 必须是 **`video/any`** | strm 链接没有扩展名，`video/*` 会被拒 |
| ② | 必须 `setPackage("is.xyz.mpv")` | 否则弹选择器，用户选别的播放器 → 没 UA → 403 |
| ③ | **不能加 `FLAG_ACTIVITY_NEW_TASK`** | 加了 `onActivityResult` 永不回调，进度全丢 |
| ④ | Android 11+ 必须声明 `<queries>` | 否则 `ActivityNotFoundException` |
| ⑤ | 分支包名不同（mpvKt 等） | 做成设置项，默认 `is.xyz.mpv` |
| ⑥ | 返回后焦点丢失 | `onResume` 里 `webView.requestFocus()` |

```kotlin
object MpvFallback {
    fun launch(activity: Activity, info: PlayInfo, launcher: ActivityResultLauncher<Intent>) {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(info.playUrl), "video/any")
            setPackage(info.mpvPackage)          // 默认 is.xyz.mpv
            putExtra("title", info.title)
            putExtra("position", info.resumeMs.toInt())
        }
        runCatching { launcher.launch(intent) }
            .onFailure { Toast.makeText(activity, "未安装 mpv", Toast.LENGTH_SHORT).show() }
    }
}
```

外部播放器返回后（`RESULT_OK`）：

- `position` 存在 → 上报该位置；
- `position` 不存在 → 播完，上报 `finished=true`；
- `RESULT_CANCELED` → 不写。

### E.7 字幕

- **内封**：`player.currentTracks` 里筛选 `TRACK_TYPE_TEXT`，UI 列轨道供切换；延迟调节用 `SubtitleView.setFractionalTextSize` 之外的 `player.setSubtitleOffset`？——以 Media3 当前版本 API 为准，若无非直接接口，用 `SubtitleConfiguration` 或自绘。
- **外挂**：同目录 `.srt/.ass` 由服务端在 `PlayInfo` 里以数组下发 URL，客户端用 `SubtitleConfiguration.Builder(uri)` 附加。
- **ASS 特效不还原**：UI 明确写一行「复杂字幕特效请用 mpv 打开」。

### E.8 TV 适配与画中画

- `LEANBACK_LAUNCHER` + banner，否则电视桌面看不到。
- 遥控器：`KEYCODE_DPAD_CENTER` 播放/暂停并唤出 OSD；左右键 ±10s；上下键唤出选集菜单；返回键先关 OSD 再退出。
- OSD 3 秒无操作自动隐藏。
- 全屏沉浸：`WindowCompat.setDecorFitsSystemWindows(window, false)` + 隐藏系统栏。
- 画中画（SHOULD，手机端）：`enterPictureInPictureMode()`，Media3 的 `PlayerView` 支持。

### E.9 明文 HTTP 与局域网

- 内网 `http://` 服务器需要 `android:usesCleartextTraffic="true"`，更严谨的做法是 `network_security_config` 只放行该网段。
- 首次启动让用户填服务器地址，校验可达后再进入 WebView。

### E.10 构建与签名

```bash
cd companion
./gradlew assembleRelease \
  -Pandroid.injected.signing.store.file=release.keystore \
  -Pandroid.injected.signing.store.password=*** \
  -Pandroid.injected.signing.alias=strmaction \
  -Pandroid.injected.signing.key.password=***
```

产物重命名为 `strmaction-companion-v1.apk`，README 给 `adb connect <TV_IP>:5555 && adb install -r ...` 的步骤。

### E.11 测试清单

- [ ] 电视桌面能看到图标（banner 正常）
- [ ] 首次启动能配置服务器地址并进入
- [ ] 内置播放器能播 1080p H.264 / 4K HEVC，声音正常
- [ ] 点播放 → 直接从上次位置起播（误差 < 3 秒）
- [ ] 播放中每 5 秒服务端 `play_progress` 有更新
- [ ] 播放中按 Home 再回来，进度不丢
- [ ] 播放中强杀 App，重启后进度最多丢 5 秒
- [ ] 播完自动连播下一集，无黑屏
- [ ] 内封字幕可切换；外挂 `.srt` 自动加载
- [ ] 遇到解不了的片源 → 弹窗 → 切 mpv 成功播放
- [ ] 未安装 mpv 时提示正确，不崩溃
- [ ] 遥控器上下左右、确定、返回、播放暂停均正常
