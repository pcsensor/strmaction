# 云服务器部署指南（Ubuntu + Docker + HTTPS）

> 一句话：把仓库放到云主机，`docker compose -f docker-compose.cloud.yml up -d --build`，
> 再用 Caddy 或 Nginx 套一层 HTTPS，手机/电视 App 里填域名即可。
>
> **视频字节不经过服务器**：云主机只读 `.strm` 文本、提供 API、缓存海报。
> 因此 1 核 1G 也能跑，带宽 1Mbps 足够。

---

## 0. 先确认三件事

1. **服务器只需要 `.strm` 文件，不需要视频文件、不需要挂载网盘。**
   把 SmartStrm 生成的目录同步到云主机即可（见第 4 节）。
2. **`.strm` 里的 URL 必须能被手机/电视直接访问。**
   如果里面是 `http://192.168.1.10:5244/...` 这类内网地址，云端部署后客户端在 4G/外网下无法播放。
   请在 SmartStrm/Alist 侧换成公网可达的域名或地址，或让客户端处于同一内网/VPN。
3. **HTTPS 域名**。手机 App 用 `https://` 地址；HTTP 也可以，但不建议公网明文。
   中国大陆服务器绑定域名走 80/443 需要备案；没有备案时可用香港/海外服务器，或临时用 `IP:端口`
   （不推荐，Cookie/安全性都会打折）。

> **没有域名时**可临时用 `http://公网IP:8080`：把 compose 里的
> `127.0.0.1:8080:8080` 改成 `8080:8080`，安全组放行 8080，App 填 `http://IP:8080`。
> 仅建议临时测试；正式使用请上 HTTPS。

---

## 1. 服务器规格

| 项 | 建议 |
|---|---|
| 系统 | Ubuntu 22.04 / 24.04 LTS（Debian 12 同样适用） |
| CPU / 内存 | 1C1G 可运行；**2C2G 推荐**（Docker 构建前端时更稳） |
| 磁盘 | 20GB 起（SQLite + 海报缓存；每千条约几百 MB 图片） |
| 带宽 | 1–5Mbps 足够（只走 API 与图片，不走视频） |
| 区域 | 尽量靠近客户端；大陆机器访问 TMDB/TVDB 可能需代理（见第 5 节） |

> 内存只有 1G 时，建议先加 2G swap，否则 `npm run build` 可能 OOM（见第 9 节）。

---

## 2. 初始化系统

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl ca-certificates rsync ufw
sudo timedatectl set-timezone Asia/Shanghai
```

### 2.1 安装 Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

退出 SSH 重新登录（或执行 `newgrp docker`），确认：

```bash
docker version
docker compose version
```

### 2.2 防火墙

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

> 云厂商的**安全组**也要只放行 22 / 80 / 443。
> **不要**把 8080 暴露到公网；本指南的 compose 只把它绑在 `127.0.0.1`。

---

## 3. 上传代码

任选一种。

**A. 有 Git 仓库：**

```bash
sudo mkdir -p /opt/strmaction && sudo chown "$USER":"$USER" /opt/strmaction
git clone <你的仓库地址> /opt/strmaction
cd /opt/strmaction
```

**B. 从本地上传（当前工作区没有 Git）：**

```bash
# 在本地项目目录执行；不要上传 data/.env/config.yaml/.venv/node_modules
# 注意：--delete 会删除服务器上多出的文件，所以必须排除 .env 与 data
rsync -av --delete \
  --exclude '.env' --exclude 'data' --exclude 'config.yaml' \
  --exclude '.venv' --exclude 'node_modules' \
  --exclude 'frontend/node_modules' --exclude 'frontend/dist' \
  --exclude 'companion' --exclude 'sample-media' \
  ./ user@你的服务器:/opt/strmaction/
```

> 需要 APK 时单独上传即可：`scp companion/app/build/outputs/apk/release/app-release.apk user@服务器:/opt/strmaction/`。
> 它只影响下载安装，不影响服务端运行。

---

## 4. 准备 `.strm` 目录

云主机上的目录只放 `.strm` 与可选字幕，例如：

```bash
sudo mkdir -p /srv/strm
sudo chown -R "$USER":"$USER" /srv/strm
```

### 4.1 从 NAS / 本地同步（推荐）

```bash
rsync -av --delete \
  --include='*/' \
  --include='*.strm' --include='*.srt' --include='*.ass' --include='*.vtt' \
  --exclude='*' \
  nas-user@192.168.1.10:/volume1/strm/ /srv/strm/
```

放到 crontab 每 15 分钟同步一次（需要提前配置免密 SSH）：

```bash
crontab -e
# 加入（日志写到当前用户目录，避免 /var/log 权限问题）：
*/15 * * * * rsync -a --delete --include='*/' --include='*.strm' --include='*.srt' --include='*.ass' --include='*.vtt' --exclude='*' nas-user@192.168.1.10:/volume1/strm/ /srv/strm/ >> "$HOME/strm-sync.log" 2>&1
```

用 Syncthing / rclone 也可以，原则相同：**只同步文本，不同步视频**。

### 4.2 直接在云主机跑 SmartStrm

如果 SmartStrm 能直连你的网盘，也可以让它输出到 `/srv/strm`，省掉同步。

### 4.3 路径对应关系

| 宿主机 | 容器内 | 网页里「识别目录」填 |
|---|---|---|
| `/srv/strm/movies` | `/media/strm/movies` | `/media/strm/movies` |
| `/srv/strm/tv` | `/media/strm/tv` | `/media/strm/tv` |

> 库里填的必须是**容器路径**（`/media/strm/...`），不是宿主机路径 `/srv/strm/...`。
> compose 已经把 `/srv/strm` 只读挂到 `/media/strm`。

---

## 5. 配置 `.env`

```bash
cd /opt/strmaction
cp .env.cloud.example .env
nano .env
```

| 变量 | 必填 | 说明 |
|---|---|---|
| `STRMACTION_BASE_URL` | ✅ | 对外地址，如 `https://media.example.com`；影响 Cookie 的 `Secure` |
| `STRMACTION_MEDIA_PATH` | ✅ | 宿主机 `.strm` 根目录，如 `/srv/strm` |
| `STRMACTION_TMDB_KEY` | 建议 | TMDB v3 Key 或 v4 Token |
| `STRMACTION_TVDB_KEY` / `PIN` | 可选 | TVDB v4 Key；部分账号需要 PIN |
| `STRMACTION_PROXY` | 可选 | 服务器访问 TMDB/TVDB 的 HTTP 代理 |

示例：

```dotenv
STRMACTION_BASE_URL=https://media.example.com
STRMACTION_MEDIA_PATH=/srv/strm
STRMACTION_TMDB_KEY=你的TMDBKey
STRMACTION_TVDB_KEY=
STRMACTION_TVDB_PIN=
STRMACTION_PROXY=
```

> 密钥也可以不写，先启动，之后在网页「设置 → 元数据源」里填；设置页写入的值优先于环境变量。

---

## 6. 构建并启动

```bash
cd /opt/strmaction
docker compose -f docker-compose.cloud.yml up -d --build

# 看状态与日志
docker compose -f docker-compose.cloud.yml ps
docker compose -f docker-compose.cloud.yml logs -f --tail=100

# 本机健康检查
curl -fsS http://127.0.0.1:8080/api/health
```

期望返回类似：

```json
{"ok":true,"version":"1.0.0","time":"...","db":"sqlite"}
```

> 首次构建会下载 Node/Python 镜像并编译前端，通常 3–10 分钟。
> 1G 内存机器若在 `npm run build` 阶段被杀，先加 swap 再重试。
>
> 国内网络卡在拉镜像 / npm / pip 时：
> - 在 `.env` 里取消注释 `NPM_REGISTRY` / `PIP_INDEX_URL`（已内置为 build args）；
> - 给 Docker daemon 配镜像加速器（阿里云/腾讯云容器镜像服务），或给 dockerd 配代理。

---

## 7. HTTPS 反向代理

> 先把域名的 **A 记录**指向服务器公网 IP，并确认 80/443 已在安全组与 UFW 放行。

### 7.1 Caddy（最省事，自动证书）

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo cp /opt/strmaction/deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo sed -i 's/media.example.com/你的域名/' /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddyfile 内容就是：

```caddyfile
media.example.com {
	encode zstd gzip
	header -Server
	reverse_proxy 127.0.0.1:8080
}
```

Caddy 会自动申请并续期 Let's Encrypt 证书（域名需已解析到本机，80/443 放行）。

### 7.2 Nginx（已有 Nginx / 宝塔时）

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/strmaction`：

```nginx
server {
    listen 80;
    server_name media.example.com;

    # 海报/背景图上传
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/strmaction /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d media.example.com
```

> 宝塔 / 1Panel：新建站点 → 反向代理到 `http://127.0.0.1:8080` → 申请 Let's Encrypt 证书即可；
> 记得把上传大小限制调到 25MB。

### 7.3 验证

- 浏览器打开 `https://你的域名`，地址栏应为 HTTPS；
- 登录后开发者工具里 `st_sess` Cookie 应带 `Secure` + `HttpOnly`；
- `curl -fsS https://你的域名/api/health` 正常返回 JSON。

> 镜像里的 uvicorn 已带 `--proxy-headers --forwarded-allow-ips *`，
> 反代只要正确传 `X-Forwarded-Proto`，Cookie 和登录限流就会按真实协议/IP 处理。

---

## 8. 首次使用

1. 打开 `https://你的域名`，设置管理员密码（≥8 位，不能纯数字）；
2. 元数据源可填 TMDB/TVDB Key，也可「稍后配置」，先用文件名兜底；
3. 添加识别目录：填**容器路径**，例如 `/media/strm/movies`，类型选「电影」，保存并扫描；
4. 库设置 / 播放器设置里填播放请求头（百度网盘示例）：

   ```text
   User-Agent: pan.baidu.com
   Referer: https://pan.baidu.com/
   ```

5. 手机 / 电视安装伴侣 App，服务器地址填 `https://你的域名`（结尾不要加 `/`），登录一次即可；
   - 电视重设地址：长按遥控器「确定」；
   - 手机：网页「设置 → 播放器 → 伴侣 App → 打开 App 设置」。

---

## 9. 日常运维

### 9.1 查看日志 / 重启

```bash
cd /opt/strmaction
docker compose -f docker-compose.cloud.yml logs -f --tail=200
docker compose -f docker-compose.cloud.yml restart
```

### 9.2 升级

```bash
cd /opt/strmaction
git pull                     # 或重新 rsync 上传代码
docker compose -f docker-compose.cloud.yml up -d --build
docker image prune -f
```

> 用 rsync 更新时务必保留 `--exclude '.env' --exclude 'data'`，否则 `--delete` 可能删掉
> 服务器上的配置与数据库。

`./data` 不受影响，库、进度、图片都会保留。

### 9.3 备份 / 恢复

SQLite 使用 WAL，**建议先停容器再打包**：

```bash
cd /opt/strmaction
docker compose -f docker-compose.cloud.yml stop
sudo tar czf /root/strmaction-$(date +%F).tgz data .env
sudo chmod 600 /root/strmaction-$(date +%F).tgz
docker compose -f docker-compose.cloud.yml start
```

恢复：

```bash
cd /opt/strmaction
docker compose -f docker-compose.cloud.yml stop
sudo tar xzf /root/strmaction-2026-10-18.tgz -C /opt/strmaction
docker compose -f docker-compose.cloud.yml start
```

也可以只导出元数据：设置页「导出备份」（不含 `.strm` URL 与图片文件）。

### 9.4 磁盘

```bash
du -sh data
du -sh /srv/strm
```

图片缓存会随条目增长；`.strm` 本身极小。

### 9.5 1G 内存加 swap

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

---

## 10. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 打开域名 502 | 容器没起来：`docker compose ... ps` / `logs`；确认 `127.0.0.1:8080` 有监听 |
| 登录后立刻跳回登录页 | `STRMACTION_BASE_URL` 与访问协议不一致，或反代没传 `X-Forwarded-Proto`；改成 `https://域名` 并确认 uvicorn proxy headers |
| 刮削一直失败 | 服务器到 TMDB/TVDB 不通：配 `STRMACTION_PROXY`，或换海外区域、自建反代 |
| 播放 403 | 请求头没配：设置里填 `User-Agent: pan.baidu.com` / `Referer`；或 `.strm` 里的直链已过期，重新生成 |
| 手机能浏览、点播放失败 | `.strm` 里的 URL 是内网地址（如 `192.168.x.x`），外网不可达；换成公网 Alist/SmartStrm 地址 |
| 图片/海报上传 413 | 反代 body 限制：Nginx `client_max_body_size 25m;` |
| 构建时 `Killed` | 内存不足：加 swap 或换 2G 机器，重跑 `up -d --build` |
| 构建卡在 Pulling / npm install | Docker Hub 或 npm 网络问题：配镜像加速/代理，或在 `.env` 设置 `NPM_REGISTRY` / `PIP_INDEX_URL` |
| 电视/手机 App 打不开 | 地址要带 `https://`，结尾不要 `/`；证书必须被系统信任（Let's Encrypt 正常） |
| 8080 被公网扫描 | compose 已绑 `127.0.0.1`；检查安全组是否误放行 8080 |
| 大陆服务器 80/443 打不开 | 域名未备案；换海外/香港机器，或先备案 |

---

## 附录 A：全 Docker（Caddy 也放进 compose）

不想在宿主机装 Caddy 时，用下面的 compose（把 `docker-compose.cloud.yml` 里的 `ports` 换成
`expose`，并加一个 caddy 服务；这是精简版，healthcheck / 日志轮转可按主 compose 补上）：

```yaml
services:
  strmaction:
    build: .
    image: strmaction:latest
    container_name: strmaction
    restart: unless-stopped
    env_file: [.env]
    environment:
      TZ: Asia/Shanghai
      STRMACTION_DATA_DIR: /data
    expose: ["8080"]
    volumes:
      - ./data:/data
      - ${STRMACTION_MEDIA_PATH}:/media/strm:ro

  caddy:
    image: caddy:2-alpine
    container_name: caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    environment:
      STRMACTION_DOMAIN: ${STRMACTION_DOMAIN}
    volumes:
      - ./deploy/Caddyfile.docker.example:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - strmaction

volumes:
  caddy_data:
  caddy_config:
```

`.env` 里再加一行：

```dotenv
STRMACTION_DOMAIN=media.example.com
```

`deploy/Caddyfile.docker.example` 的内容是：

```caddyfile
{$STRMACTION_DOMAIN} {
	encode zstd gzip
	reverse_proxy strmaction:8080
}
```

---

## 附录 B：不用 Docker（systemd）

适合不想装 Docker 的机器。

```bash
sudo apt install -y python3 python3-venv python3-pip nginx

# 前端构建需要 Node 20（Ubuntu 自带版本偏旧）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

sudo useradd -r -s /usr/sbin/nologin strmaction
sudo mkdir -p /opt/strmaction /var/lib/strmaction
# 代码放到 /opt/strmaction 后：
cd /opt/strmaction
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

cd frontend
npm ci && npm run build
cd ..

sudo chown -R strmaction:strmaction /opt/strmaction /var/lib/strmaction
# 让服务用户能读媒体目录（只读即可）
sudo chmod -R o+rX /srv/strm
```

`/etc/strmaction.env`（权限 `chmod 600`）：

```dotenv
STRMACTION_DATA_DIR=/var/lib/strmaction
STRMACTION_BASE_URL=https://media.example.com
STRMACTION_TMDB_KEY=你的Key
```

```bash
sudo nano /etc/strmaction.env
sudo chown root:root /etc/strmaction.env
sudo chmod 600 /etc/strmaction.env
```

`/etc/systemd/system/strmaction.service`：

```ini
[Unit]
Description=StrmAction
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=strmaction
Group=strmaction
WorkingDirectory=/opt/strmaction/backend
EnvironmentFile=/etc/strmaction.env
ExecStart=/opt/strmaction/.venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port 8080 \
  --proxy-headers --forwarded-allow-ips=*
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now strmaction
sudo systemctl status strmaction
```

> systemd 模式没有容器路径映射：网页里的「识别目录」直接填宿主机路径，
> 例如 `/srv/strm/movies`，不要填 `/media/strm/...`。

反向代理与 HTTPS 同第 7 节。

---

## 附录 C：安全清单

- [ ] 公网只开 22 / 80 / 443，**8080 只绑 127.0.0.1**
- [ ] 全站 HTTPS；`st_sess` Cookie 为 `Secure` + `HttpOnly`
- [ ] 管理员密码足够强（≥12 位混合字符），不与其他站点复用
- [ ] `.env` 权限 `chmod 600`，不要提交到 Git
- [ ] 定期备份 `data/`（SQLite、图片、会话密钥）
- [ ] 保持 Docker 镜像/系统更新；`docker image prune -f`
- [ ] 不把 `/docs` 暴露给公网（可选：反代里屏蔽 `/docs`、`/openapi.json`）
- [ ] 媒体目录只读挂载（compose 已带 `:ro`）
- [ ] 公网部署前阅读 README「安全」章节
