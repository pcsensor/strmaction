"""为演示环境生成封面/背景图与示例元数据（仅用于本地演示与截图）。

前置条件：服务已启动，且 sample-media 已扫描入库。
    python scripts/seed_demo.py --base-url http://127.0.0.1:8080

脚本会：
1. 首次运行时设置管理员密码（默认 demo-password-123）；
2. 若媒体库不存在则创建并扫描 sample-media 下的四个目录；
3. 用 Pillow 生成抽象海报/背景图，通过 API 上传；
4. 直接写库补全简介、评分、类型、演职员与剧集剧照；
5. 写入两条「继续观看」进度。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import random
import time
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from sqlmodel import Session, select

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import ConfigManager  # noqa: E402
from app.db import Database  # noqa: E402
from app.models import Item, Library, PlayProgress, utcnow  # noqa: E402

PALETTES = [
    ((22, 34, 74), (6, 8, 14), (232, 176, 106)),
    ((60, 24, 40), (8, 6, 12), (246, 164, 132)),
    ((14, 54, 56), (5, 10, 12), (128, 224, 200)),
    ((52, 40, 16), (8, 7, 6), (244, 206, 128)),
    ((30, 26, 66), (7, 6, 14), (170, 150, 250)),
    ((58, 30, 18), (9, 6, 5), (250, 170, 120)),
    ((18, 42, 30), (5, 9, 7), (150, 226, 168)),
]

# 为演示数据挑选的 Picsum 图片 id（风景 / 城市 / 夜景，避免随机出现无关物品）
PHOTO_IDS: dict[str, tuple[int, int]] = {
    "流浪地球2": (84, 61),
    "沙丘2": (46, 85),
    "奥本海默": (58, 67),
    "无名": (57, 91),
    "黑客帝国": (88, 52),
    "三体": (84, 94),
    "漫长的季节": (73, 94),
    "Some Show": (52, 60),
    "狂飙": (91, 88),
    "进击的巨人": (83, 66),
}
DEFAULT_PHOTO_IDS = (43, 62)
STILL_PHOTO_IDS = [43, 46, 52, 57, 62, 66, 73, 84, 88, 91, 94, 96]

CAST_POOL = [    ("吴京", "刘培强"),
    ("刘德华", "图恒宇"),
    ("李雪健", "周喆直"),
    ("沙溢", "张鹏"),
    ("王智", "韩朵朵"),
    ("宁理", "马兆"),
    ("陈瑾", "叶文洁"),
    ("王子文", "青年叶文洁"),
    ("于和伟", "史强"),
    ("张鲁一", "汪淼"),
    ("郭帆", "导演"),
    ("龚格尔", "制片人"),
]

OVERVIEWS = [
    "在人类文明面临存亡的关头，一群普通人被推到历史的十字路口。他们必须在有限的时间里做出选择，而每一个选择都会改变未来的形状。",
    "一次意外的相遇，让原本平行的命运开始交错。旧日的秘密被重新翻开，所有人都不得不面对自己曾经逃避的答案。",
    "当熟悉的世界开始崩塌，唯一能依靠的是彼此之间尚未断裂的信任。这是一段关于勇气、牺牲与重逢的故事。",
    "故事发生在一座被时间遗忘的城市。雾气散去之后，人们发现真相远比传闻更复杂，也更温柔。",
]


def load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    base = Image.new("RGB", (1, height))
    for y in range(height):
        ratio = y / max(1, height - 1)
        base.putpixel(
            (0, y),
            tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)),
        )
    return base.resize((width, height), Image.Resampling.BILINEAR)


def add_glow(image: Image.Image, palette: tuple[int, int, int], seed: int) -> Image.Image:
    rng = random.Random(seed)
    width, height = image.size
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for _ in range(3):
        x = rng.randint(int(width * 0.1), int(width * 0.9))
        y = rng.randint(int(height * 0.05), int(height * 0.6))
        radius = rng.randint(int(width * 0.25), int(width * 0.55))
        color = tuple(min(255, int(c * rng.uniform(0.55, 0.95))) for c in palette)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=width // 8))
    return Image.blend(image, glow, 0.42)


def add_grain(image: Image.Image, strength: float = 0.06) -> Image.Image:
    noise = Image.effect_noise(image.size, 42).convert("L").convert("RGB")
    return Image.blend(image, noise, strength)


def wrap_title(title: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if not title:
        return [""]
    if any("\u4e00" <= ch <= "\u9fff" for ch in title):
        chars = list(title)
        lines: list[str] = []
        current = ""
        for char in chars:
            candidate = current + char
            if font.getlength(candidate) > max_width and current:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines[:3]
    words = title.split(" ")
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) > max_width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:3]


def make_poster(
    title: str, year: int | None, palette_index: int, photo: bytes | None = None
) -> bytes:
    width, height = 600, 900
    top, bottom, accent = PALETTES[palette_index % len(PALETTES)]
    if photo:
        image = cover_photo(photo, (width, height))
        image = grade(image, top, accent)
    else:
        image = gradient((width, height), top, bottom)
        image = add_glow(image, accent, palette_index * 17 + len(title))
    image = add_grain(image, 0.05)
    draw = ImageDraw.Draw(image, "RGBA")
    # 底部渐暗，卡片叠加文字时更易读
    for y in range(int(height * 0.55), height):
        ratio = (y - height * 0.55) / (height * 0.45)
        draw.rectangle((0, y, width, y + 1), fill=(6, 7, 10, int(220 * ratio)))

    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def make_backdrop(title: str, palette_index: int, photo: bytes | None = None) -> bytes:
    width, height = 1600, 900
    top, bottom, accent = PALETTES[palette_index % len(PALETTES)]
    if photo:
        image = cover_photo(photo, (width, height))
        image = grade(image, top, accent)
    else:
        image = gradient((width, height), top, bottom)
        image = add_glow(image, accent, palette_index * 31 + 7)
    image = add_grain(image, 0.055)
    draw = ImageDraw.Draw(image, "RGBA")
    # 左侧压暗，便于叠标题
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for x in range(width):
        ratio = max(0.0, 1 - x / (width * 0.72))
        odraw.line((x, 0, x, height), fill=(5, 6, 9, int(160 * ratio)))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=88)
    return buffer.getvalue()


def make_still(
    title: str, index: int, palette_index: int, photo: bytes | None = None
) -> bytes:
    width, height = 960, 540
    top, bottom, accent = PALETTES[(palette_index + index) % len(PALETTES)]
    if photo:
        image = cover_photo(photo, (width, height))
        image = grade(image, top, accent)
    else:
        image = gradient((width, height), top, bottom)
        image = add_glow(image, accent, palette_index * 13 + index)
    image = add_grain(image, 0.05)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, height - 160, width, height), fill=(4, 5, 8, 150))
    font = load_font(30, bold=True)
    draw.text((40, height - 96), title, font=font, fill=(255, 255, 255, 230))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=86)
    return buffer.getvalue()


def cover_photo(data: bytes, size: tuple[int, int]) -> Image.Image:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    width, height = size
    source_ratio = image.width / image.height
    target_ratio = width / height
    if source_ratio > target_ratio:
        new_width = int(image.height * target_ratio)
        left = (image.width - new_width) // 2
        image = image.crop((left, 0, left + new_width, image.height))
    else:
        new_height = int(image.width / target_ratio)
        top = (image.height - new_height) // 2
        image = image.crop((0, top, image.width, top + new_height))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def grade(image: Image.Image, tint: tuple[int, int, int], accent: tuple[int, int, int]) -> Image.Image:
    from PIL import ImageEnhance

    tint_layer = Image.new("RGB", image.size, tint)
    image = Image.blend(image, tint_layer, 0.18)
    image = ImageEnhance.Color(image).enhance(0.92)
    image = ImageEnhance.Contrast(image).enhance(1.06)
    # 暗角
    width, height = image.size
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(
        (-int(width * 0.18), -int(height * 0.18), int(width * 1.18), int(height * 1.18)),
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius=min(width, height) // 6))
    black = Image.new("RGB", image.size, (3, 4, 7))
    return Image.composite(image, black, mask)


def fetch_photo(seed: str, width: int, height: int, enabled: bool = True) -> bytes | None:
    if not enabled:
        return None
    cache_dir = ROOT / "scripts" / ".demo-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{seed}:{width}x{height}".encode()).hexdigest()
    cached = cache_dir / f"{key}.jpg"
    if cached.is_file():
        return cached.read_bytes()
    if seed.startswith("id:"):
        url = f"https://picsum.photos/id/{seed[3:]}/{width}/{height}"
    else:
        url = f"https://picsum.photos/seed/{seed}/{width}/{height}"
    try:
        response = httpx.get(
            url,
            timeout=25,
            follow_redirects=True,
            headers={"User-Agent": "StrmAction-demo/1.0"},
        )
        response.raise_for_status()
        cached.write_bytes(response.content)
        return response.content
    except Exception:
        return None


def make_avatar(name: str, index: int) -> bytes:
    size = 240
    top, bottom, accent = PALETTES[index % len(PALETTES)]
    image = gradient((size, size), top, bottom)
    image = add_glow(image, accent, index * 7 + len(name))
    draw = ImageDraw.Draw(image, "RGBA")
    font = load_font(96, bold=True)
    initial = name[0] if name else "?"
    bbox = draw.textbbox((0, 0), initial, font=font)
    draw.text(
        ((size - (bbox[2] - bbox[0])) / 2, (size - (bbox[3] - bbox[1])) / 2 - bbox[1]),
        initial,
        font=font,
        fill=(255, 255, 255, 235),
    )
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=88)
    return buffer.getvalue()


def image_dir() -> Path:
    config = ConfigManager(ROOT / "config.yaml")
    return config.image_dir


def write_variant(data: bytes, sizes: tuple[int, ...]) -> str:
    """按 ImageService 的命名规则直接写 WebP 变体，返回 sha。"""
    sha = hashlib.sha1(data).hexdigest()
    folder = image_dir()
    folder.mkdir(parents=True, exist_ok=True)
    image = Image.open(io.BytesIO(data)).convert("RGB")
    for size in sizes:
        variant = image.copy()
        width, height = variant.size
        if width > size:
            height = max(1, round(height * size / width))
            variant = variant.resize((size, height), Image.Resampling.LANCZOS)
        variant.save(folder / f"{sha}_{size}.webp", "WEBP", quality=82, method=4)
    return sha


def api_client(base_url: str, password: str, username: str = "admin") -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=60, follow_redirects=True)
    state = client.get("/api/auth/state").json()
    if state.get("needs_setup"):
        response = client.post("/api/auth/setup", json={"password": password, "username": username})
        response.raise_for_status()
    elif not state.get("authenticated"):
        response = client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        response.raise_for_status()
    return client


def ensure_library(client: httpx.Client, name: str, root: Path, type_: str) -> int:
    libraries = client.get("/api/libraries").json()["libraries"]
    for library in libraries:
        if library["root_path"] == str(root.resolve()):
            return library["id"]
    response = client.post(
        "/api/libraries",
        json={"name": name, "root_path": str(root.resolve()), "type": type_},
    )
    response.raise_for_status()
    return response.json()["id"]


def wait_task(client: httpx.Client, task_id: int, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] != "running":
            return task
        time.sleep(0.4)
    raise TimeoutError(f"task {task_id}")


def upload(client: httpx.Client, item_id: int, data: bytes, kind: str) -> dict:
    files = {"file": (f"{kind}.jpg", data, "image/jpeg")}
    response = client.post(f"/api/items/{item_id}/poster", files=files, data={"kind": kind})
    response.raise_for_status()
    return response.json()


def seed_metadata(item: Item, index: int) -> None:
    item.overview = OVERVIEWS[index % len(OVERVIEWS)]
    item.tagline = ["命运之战", "时间之外", "向死而生", "雾中来信"][index % 4]
    item.rating = round(7.2 + (index % 9) * 0.24, 1)
    item.runtime_min = 96 + (index * 7) % 78
    item.genres = __import__("json").dumps(
        [["科幻", "冒险"], ["剧情", "悬疑"], ["犯罪", "剧情"], ["动画", "奇幻"]][index % 4],
        ensure_ascii=False,
    )
    item.certification = ["PG-13", "TV-14", "TV-MA", "PG"][index % 4]
    item.status = "Released" if item.kind == "movie" else "Ended"
    item.provider = "tmdb"
    item.provider_id = str(100000 + index)
    item.match_state = "auto"
    item.external_ids = __import__("json").dumps({"tmdb": 100000 + index}, ensure_ascii=False)
    cast = []
    for offset in range(6):
        name, role = CAST_POOL[(index * 3 + offset) % len(CAST_POOL)]
        avatar = write_variant(make_avatar(name, index + offset), (185,))
        cast.append({"name": name, "role": role, "avatar": avatar, "kind": "cast"})
    item.cast = __import__("json").dumps(cast, ensure_ascii=False)
    item.sort_title = item.title
    item.updated_at = utcnow()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--password", default="demo-password-123")
    parser.add_argument("--media-root", default=str(ROOT / "sample-media"))
    parser.add_argument("--no-remote", action="store_true", help="不下载示例照片，只用渐变占位")
    args = parser.parse_args()
    use_remote = not args.no_remote

    client = api_client(args.base_url, args.password)
    media_root = Path(args.media_root)
    libraries = {
        "movie": ensure_library(client, "电影", media_root / "movies", "movie"),
        "tv": ensure_library(client, "剧集", media_root / "tv", "tv"),
        "home": ensure_library(client, "家庭视频", media_root / "home", "home"),
        "course": ensure_library(client, "课程", media_root / "course", "course"),
    }
    for library_id in libraries.values():
        task = client.post(f"/api/libraries/{library_id}/scan").json()
        result = wait_task(client, task["task_id"])
        print(f"扫描任务 {task['task_id']}: {result['status']} {result.get('stats', {}).get('parsed', '')}")

    items: list[dict] = []
    for library_id in libraries.values():
        payload = client.get("/api/items", params={"library_id": library_id, "page_size": 100}).json()
        items.extend(payload["items"])

    config = ConfigManager(ROOT / "config.yaml")
    database = Database(config)
    detail_cache: list[dict] = []
    for index, summary in enumerate(items):
        detail = client.get(f"/api/items/{summary['id']}").json()
        detail_cache.append(detail)
        title = detail["item"]["title"]
        year = detail["item"]["year"]
        poster_photo = fetch_photo(
            f"id:{PHOTO_IDS.get(title, DEFAULT_PHOTO_IDS)[0]}", 600, 900, use_remote
        )
        backdrop_photo = fetch_photo(
            f"id:{PHOTO_IDS.get(title, DEFAULT_PHOTO_IDS)[1]}", 1600, 900, use_remote
        )
        poster = upload(client, summary["id"], make_poster(title, year, index, poster_photo), "poster")
        upload(client, summary["id"], make_backdrop(title, index, backdrop_photo), "backdrop")
        print(f"已生成图片：#{summary['id']} {title} ({poster['sha'][:8]})")

        # 剧集：为每集生成剧照
        if detail["seasons"]:
            for season_index, season in enumerate(detail["seasons"]):
                for episode in season["episodes"]:
                    still = make_still(
                        f"{title} · {episode.get('episode_code') or episode['title']}",
                        episode["episode_no"] or 1,
                        index + season_index,
                        fetch_photo(
                            f"id:{STILL_PHOTO_IDS[(index + (episode['episode_no'] or 0)) % len(STILL_PHOTO_IDS)]}",
                            960,
                            540,
                            use_remote,
                        ),
                    )
                    sha = write_variant(still, (300, 780))
                    with Session(database.engine) as session:
                        row = session.get(Item, episode["id"])
                        if row:
                            row.still_path = sha
                            row.overview = OVERVIEWS[(index + (episode["episode_no"] or 0)) % len(OVERVIEWS)]
                            row.runtime_min = 42 + (episode["episode_no"] or 0) % 12
                            row.title = f"第 {episode['episode_no']} 集"
                            row.match_state = "auto"
                            row.provider = "tmdb"
                            row.provider_id = f"{100000 + index}{episode['episode_no'] or 0}"
                            row.updated_at = utcnow()
                            session.add(row)
                            session.commit()

    with Session(database.engine) as session:
        for index, summary in enumerate(items):
            row = session.get(Item, summary["id"])
            if row is None:
                continue
            seed_metadata(row, index)
            session.add(row)
        session.commit()

    # 继续观看：取剧集前两集
    continue_items: list[int] = []
    for detail in detail_cache:
        for season in detail["seasons"]:
            for episode in season["episodes"]:
                continue_items.append(episode["id"])
    if len(continue_items) >= 2:
        client.post(
            f"/api/items/{continue_items[0]}/progress",
            json={"position_ms": 720000, "duration_ms": 2700000},
        )
        client.post(
            f"/api/items/{continue_items[1]}/progress",
            json={"position_ms": 1450000, "duration_ms": 2820000},
        )
    print("演示数据已就绪。")
    client.close()


if __name__ == "__main__":
    main()
