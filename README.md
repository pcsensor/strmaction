# StrmAction

<p align="center">
  <strong>面向 <code>.strm</code> 媒体库的现代「刮削 + 展示 + 播放分发」系统</strong><br>
  不转码 · 不代理视频流 · 零服务器带宽负担 · 把播放从传统媒体服务器中彻底解耦
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black" alt="React">
  <img src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Flutter-Android_iOS_Desktop-02569B?logo=flutter&logoColor=white" alt="Flutter">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
</p>

---

## 📖 这是什么

在云盘挂载和网盘播放场景中，工具（如 SmartStrm）生成的 `.strm` 文件通常仅包含一行真实播放地址。传统媒体服务器（如 Jellyfin / Emby / Plex）在处理海量 `.strm` 时容易出现转码过载、直连嗅探卡顿或请求头丢失等问题。

**StrmAction** 专为 `.strm` 媒体库设计：
1. **自动扫描与元数据刮削**：接入 **TMDB + TVDB** 双元数据源，结合自研解析链，提供海报墙、演职员、分季选集与评分等完整的媒体信息展示。
2. **播放分发与轻量架构**：点击播放时，服务端仅负责解析起播集、下发视频 URL、分发媒体库请求头（UA/Referer）与生成短效 `play_token`。
3. **直连播放与全端适配**：播放流量由播放端直连网盘/CDN，**全程不经过 StrmAction 服务端**，实现服务端零中转、零转码、零带宽消耗。

```text
SmartStrm 生成 .strm（文件内容 = 网盘解析地址）
        │
        ▼
StrmAction 服务端（扫描目录 → 智能解析 → TMDB/TVDB 刮削 → 入库展示）
        │
        ▼
用户全端浏览（Web / Android 伴侣 App / 桌面客户端）
        │  点击播放（下发播放 URL、请求头与进度 Token）
        ▼
播放器引擎（Media3 / media_kit）──(302)──► Alist ──(302)──► 网盘 CDN
        │
        └─ 视频流完全由客户端直连，服务端仅以 5s 心跳接收轻量播放进度
```

---

## ✨ 核心特性

### 🎬 媒体库与文件解析
- **四类媒体管理**：支持电影、电视剧、家庭视频与课程目录，支持多路径挂载与独立定时扫描。
- **智能增量扫描**：基于文件修改时间（`mtime`）与大小的增量检测；按 URL 识别重命名/文件移动；支持软删除防护（`missing` 机制）。
- **强大解析引擎**：目录模板优先 + 规则链 + Guessit 兜底；完美兼容中文命名、全角括号、显式 ID（如 `{tmdb-603}`）、分段视频与多版本 4K/1080P 自动归并。

### 🌐 双源智能刮削
- **TMDB + TVDB 双源**：支持配置优先级、加权匹配打分（标题/年份/热度/别名综合判定）；自动跨源补充缺失简介、剧照与演职员头像。
- **本地 NFO 接管**：支持识别 Kodi / tinyMediaManager 生成的本地 `.nfo` 文件并优先读取。
- **高性能图片服务**：海报、背景图采用 WebP 压缩，保留 8-bit Alpha 透明通道；URL 级去重与本地长效缓存。

### ⚡ 播放体系与全端支持
- **播放分发模式**：
  - **伴侣 App（`builtin`，推荐）**：专为手机与 Android TV 打造，内置 Google Media3 播放器，原生携带请求头、断点续播、无缝连播、40% 侧滑抽屉与手势控制。
  - **统一 App 内部播放（`builtin`）**：Android、iOS、Windows、macOS 共用 Flutter 界面，保留各平台原生播放内核与系统服务。
  - **复制链接（`copy`）**：复制所选媒体版本的真实直链；普通浏览器禁用内部播放并提示使用 App。
- **准实时进度系统**：
  - 播放器每 5 秒自动上报进度心跳，暂停、后台切出或播放结束时立即补写；
  - 达到 90% 自动标记完播；提供 12 小时 `play_token` 幂等鉴权，客户端无需接触会话 Cookie；
  - **海报智能续播**：海报播放优先定位到“继续播放”里的最新单集；若无在播记录（未看、全剧看完或主动移出），自动从第一集从头起播。

### 👥 多用户与权限隔离
- **完整 RBAC 权限体系**：管理员拥有全局管理权，普通用户支持细粒度按媒体库授权。
- **数据严格隔离**：首页轮播、继续观看、各库列表、搜索与详情页全局应用库级隔离；播放进度与已看记录多账号完全独立。
- **个性化播放偏好**：每个用户可自主设置个人专属的播放模式与回退策略。

---

## 🚀 快速开始

### 方式一：Docker Compose（局域网 / NAS 部署）

创建 `docker-compose.yml`（或直接使用仓库自带文件）：

```yaml
services:
  strmaction:
    image: strmaction:latest
    build: .
    container_name: strmaction
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
      - /path/to/your/strm:/media/strm:ro
    environment:
      - STRMACTION_BASE_URL=http://192.168.1.10:8080
      - STRMACTION_TMDB_KEY=your_tmdb_key
      - STRMACTION_TVDB_KEY=your_tvdb_key
```

启动容器：
```bash
docker compose up -d --build
```

访问 `http://<服务器IP>:8080`，跟随首次向导完成管理员密码设定、元数据 Key 配置与媒体库路径添加。

---

### 方式二：云服务器部署（公网 HTTPS + Caddy 反向代理）

若需在 VPS 上部署并搭配域名访问，推荐使用配套的 `docker-compose.cloud.yml`：

1. **准备环境变量**：
   ```bash
   cp .env.cloud.example .env
   # 编辑 .env，填入对外访问域名与 API Key
   # STRMACTION_BASE_URL=https://media.example.com
   # STRMACTION_MEDIA_PATH=/srv/strm
   ```

2. **配置反向代理**：
   参考 [`deploy/Caddyfile.example`](deploy/Caddyfile.example) 配置 Caddy 自动申请与续期 Let's Encrypt SSL 证书：
   ```caddy
   media.example.com {
       encode gzip zstd
       reverse_proxy 127.0.0.1:8080
   }
   ```

3. **启动云服务**：
   ```bash
   docker compose -f docker-compose.cloud.yml up -d --build
   ```

> **提示**：云主机只需同步 `.strm` 文本文件（几十 MB），无需同步体积庞大的真实视频文件，1 核 1G 规格即可流畅运行。

---

## ⚙️ 配置与环境变量

配置加载优先级：**系统设置页（SQLite 数据库） > `config.yaml` > 内置默认值**。

| 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `STRMACTION_CONFIG` | `./config.yaml` | 配置文件路径 |
| `STRMACTION_DATA_DIR` | `./data` | 数据持久化目录（存放数据库、图片缓存、会话密钥） |
| `STRMACTION_BASE_URL` | `http://localhost:8080` | 外部访问完整 URL（HTTPS 模式下 Cookie 自动启用 Secure） |
| `STRMACTION_TMDB_KEY` | - | TMDB API Key 或 v4 Token |
| `STRMACTION_TVDB_KEY` | - | TheTVDB API Key |
| `STRMACTION_TVDB_PIN` | - | TheTVDB 账号 PIN（如需要） |
| `STRMACTION_PROXY` | - | 刮削请求代理地址（如 `http://127.0.0.1:7890`） |
| `STRMACTION_SECRET` | - | 会话加密密钥（留空时首次启动自动生成并写入数据目录） |
| `STRMACTION_DISABLE_SCHEDULER` | `0` | 是否禁用后台定时任务（`1` 为禁用，用于单测） |

完整配置字段与结构参见 [`config.example.yaml`](config.example.yaml)。

---

## 📱 客户端配套

四端客户端统一维护在 [`client_flutter/`](client_flutter/README.md)，媒体库继续复用云端 Web。

| 平台 | 最低版本 | 内部播放内核 | CI 产物 |
|---|---|---|---|
| Android / Android TV | Android 7 / API 24 | Media3 | 测试 APK、Release APK |
| iPhone / iPad | iOS 16 | KSPlayer | 可重签的未签名 IPA |
| Windows | Windows 10 | media_kit / libmpv | 完整 ZIP |
| macOS | macOS 12 | media_kit / libmpv | 完整 .app ZIP |

所有客户端 SDK、原生项目生成、检查和构建仅在 [Clients CI](https://github.com/pcsensor/strmaction/actions/workflows/clients.yml) 执行。下载安装包无需在本地安装 SDK。

播放方式采用本机覆盖 → 账号默认 → 全局默认。缓存采用本机覆盖 → 云端默认 → 平台预算；只缓存当前视频，退出或切集清空。私有 HTTPS 使用导入根 CA 的方式，持续校验证书链与主机名。

Android 正式签名使用新生成的固定发布密钥，通过 GitHub Secrets 注入并校验最终 APK 证书；首次切换需卸载旧签名版 / 测试版。全部未配置时明确提供测试包与未签名 Release。原 iOS 仓库在迁移真机验收完成前保留独立历史与构建。详见[迁移与验收说明](docs/CLIENT_MIGRATION.md)。

---

## 💻 本地开发

### 后端开发
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp ../config.example.yaml config.yaml
export PYTHONPATH=.
uvicorn app.main:app --reload --port 8080
```

### 前端开发
```bash
cd frontend
npm install
npm run dev  # 启动 Vite 开发服务器，自动反向代理 /api 与 /img 到 8080
```

### 运行测试
项目内置了涵盖解析、扫描、元数据匹配、分发鉴权与全流程的自动化测试集：
```bash
cd backend
PYTHONPATH=. pytest tests/ -v
```
（当前 62 项单元测试全部通过）

---

## 📂 项目结构

```text
strmaction/
├── backend/                  # 后端源码（FastAPI + SQLModel）
│   ├── app/
│   │   ├── api/              # RESTful API 路由分发
│   │   ├── parser/           # .strm 路径与命名规则解析链
│   │   ├── scanner/          # 媒体库遍历与增量同步引擎
│   │   ├── scraper/          # TMDB / TVDB / NFO 元数据刮削与评分插件
│   │   ├── players/          # 播放协议适配与请求头清洗
│   │   ├── models.py         # 数据模型定义
│   │   └── main.py           # 应用入口与生命周期管理
│   ├── tests/                # 单元测试与端到端测试套件
│   └── requirements.txt
├── frontend/                 # Web 前端（React + Vite + TailwindCSS）
│   ├── src/
│   │   ├── api/              # API 客户端与 TanStack Query Hooks
│   │   ├── components/       # 业务 UI 组件（海报卡片、轮播、抽屉、对话框）
│   │   ├── pages/            # 路由页面（首页、详情、搜索、用户、设置）
│   │   └── store/            # 客户端状态管理
│   └── package.json
├── companion/                # Android 旧客户端与复用的 Media3 缓存核心
├── client_flutter/           # 四端 Flutter 客户端、原生桥接和公共测试
├── native/ios/               # 导入的 iOS 播放 / 缓存 / 证书核心
├── ci/                       # 四端构建准备、签名与产物追踪
├── deploy/                   # Caddy 反向代理配置示例
├── scripts/                  # 样本生成与演示数据工具
├── Dockerfile                # 多阶段生产容器构建定义
├── docker-compose.yml        # 本地与 NAS 部署配置
└── docker-compose.cloud.yml  # 云端部署配置
```

---

## 🚫 非设计目标

为了保证系统的纯粹性与极高运行效率，StrmAction 明确**不包含**以下特性：
- ❌ **服务端视频转码**：不占用宿主机 CPU/GPU 进行耗电耗资源的转码。
- ❌ **服务端流代理**：视频字节绝不经过后端中转，彻底释放服务器带宽。
- ❌ **网盘挂载与账号管理**：专注消费 `.strm`，网盘鉴权由上游工具（如 AList / SmartStrm）负责。
- ❌ **内嵌 HTML5 `<video>` 播放器**：避免原生浏览器在编码格式支持与请求头定制上的天然缺陷。

---

## 📄 开源协议

本项目基于 [MIT 许可证](LICENSE) 开源。
元数据服务由 [The Movie Database (TMDB)](https://www.themoviedb.org/) 与 [TheTVDB](https://thetvdb.com/) 提供支持。
