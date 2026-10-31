"""图片下载、WebP 多尺寸生成、主题色提取与异步图片队列（附录 D.7）。"""

from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import json
import socket
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image
from sqlmodel import Session, select

from .config_store import SettingsService
from .models import ImageTask, Item, Library, utcnow

Image.MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_BYTES = 25 * 1024 * 1024
ALLOWED_REMOTE_CONTENT_TYPES = ("image/", "application/octet-stream")

VARIANT_SIZES: dict[str, tuple[int, ...]] = {
    "poster": (342, 500),
    "backdrop": (780, 1280),
    "logo": (200, 400),
    "still": (300, 780),
    "thumb": (185,),
}

DEFAULT_ACCENT = "#e8b06a"
BG_DARK = (7, 8, 10)


def sha_for_source(source: str) -> str:
    """以图片源地址作为缓存键，保证同一张图只下载一次，且重启后仍可命中。"""
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def image_url(sha: str | None, size: int) -> str | None:
    if not sha:
        return None
    return f"/img/{sha}_{size}.webp"


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb: tuple[int, int, int], other: tuple[int, int, int]) -> float:
    l1 = _relative_luminance(rgb)
    l2 = _relative_luminance(other)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def extract_color(data: bytes) -> str:
    """取主色簇：饱和、亮度适中、与深色底对比度 ≥ 4.5。"""
    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image = image.resize((64, 64))
        quantized = image.quantize(colors=12, method=Image.Quantize.MEDIANCUT).convert("RGB")
        counts = Counter(quantized.getdata())
    except Exception:
        return DEFAULT_ACCENT
    best: tuple[float, tuple[int, int, int]] | None = None
    for color, count in counts.items():
        r, g, b = color
        maximum, minimum = max(color), min(color)
        saturation = 0 if maximum == 0 else (maximum - minimum) / maximum
        luminance = _relative_luminance(color)
        if not (0.12 <= luminance <= 0.9):
            continue
        if saturation < 0.18:
            continue
        score = count * (0.4 + saturation)
        if best is None or score > best[0]:
            best = (score, color)
    if best is None:
        # 退而求其次：从所有颜色里挑对比度最高的
        for color, _count in counts.items():
            if contrast_ratio(color, BG_DARK) >= 4.5:
                if best is None:
                    best = (1, color)
    color = best[1] if best else (232, 176, 106)
    # 提亮到满足对比度
    adjusted = list(color)
    for _ in range(24):
        if contrast_ratio(tuple(adjusted), BG_DARK) >= 4.5:
            break
        adjusted = [min(255, int(v * 1.08 + 4)) for v in adjusted]
    return "#{:02x}{:02x}{:02x}".format(*adjusted)


class ImageService:
    def __init__(self, settings: SettingsService):
        self.settings = settings
        self.image_dir: Path = settings.image_dir
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.engine = settings.engine
        scraper = settings.scraper()
        self.proxy = (scraper.get("proxy") or "").strip() or None
        self._client: httpx.AsyncClient | None = None
        self._stop = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()

    # -- HTTP -------------------------------------------------------------
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs: dict = {
                "timeout": httpx.Timeout(20, connect=10),
                "follow_redirects": True,
                "headers": {
                    "User-Agent": "StrmAction/1.0",
                    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                },
            }
            if self.proxy:
                kwargs["proxy"] = self.proxy
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.cancel()
        if self._client:
            await self._client.aclose()
            self._client = None

    # -- 生成变体 ---------------------------------------------------------
    def variants_exist(self, sha: str, kind: str) -> bool:
        sizes = VARIANT_SIZES.get(kind) or (342,)
        return all((self.image_dir / f"{sha}_{size}.webp").is_file() for size in sizes)

    def save_variants(self, sha: str, kind: str, data: bytes) -> bool:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                image = Image.open(io.BytesIO(data))
                image.load()
        except Exception:
            return False
        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            image = image.convert("RGBA")
        elif image.mode != "RGB":
            image = image.convert("RGB")
        sizes = VARIANT_SIZES.get(kind) or (342,)
        for size in sizes:
            variant = image.copy()
            width, height = variant.size
            if width > size:
                height = max(1, round(height * size / width))
                variant = variant.resize((size, height), Image.Resampling.LANCZOS)
            target = self.image_dir / f"{sha}_{size}.webp"
            try:
                variant.save(target, "WEBP", quality=82, method=4)
            except Exception:
                return False
        return True

    async def save_variants_async(self, sha: str, kind: str, data: bytes) -> bool:
        return await asyncio.to_thread(self.save_variants, sha, kind, data)

    def _local_source_allowed(self, path: Path) -> bool:
        """本地图片只允许来自数据目录、图片目录或已配置媒体库根目录。"""
        try:
            resolved = path.resolve()
        except OSError:
            return False
        roots = [self.settings.data_dir, self.image_dir]
        with Session(self.engine) as session:
            roots.extend(
                Path(root)
                for root in session.exec(select(Library.root_path)).all()
                if root
            )
        for root in roots:
            try:
                resolved.relative_to(root.resolve())
                return True
            except (OSError, ValueError):
                continue
        return False

    async def _remote_source_allowed(self, url: str) -> bool:
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return False
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            infos = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    parsed.hostname, port, type=socket.SOCK_STREAM
                ),
                timeout=5,
            )
        except (OSError, ValueError, asyncio.TimeoutError):
            return False
        for info in infos:
            try:
                address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
            except ValueError:
                return False
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                return False
        return True

    async def _fetch_remote(self, source: str) -> bytes | None:
        """带重定向校验、大小限制和内容类型检查的图片下载。"""
        url = source
        for _ in range(4):
            if not await self._remote_source_allowed(url):
                return None
            try:
                async with self.client().stream(
                    "GET", url, follow_redirects=False
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            return None
                        url = urljoin(url, location)
                        continue
                    if response.status_code in {404, 410}:
                        return None
                    response.raise_for_status()
                    content_type = (response.headers.get("content-type") or "").lower()
                    if content_type and not content_type.startswith(
                        ALLOWED_REMOTE_CONTENT_TYPES
                    ):
                        return None
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_IMAGE_BYTES:
                        return None
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_IMAGE_BYTES:
                            return None
                        chunks.append(chunk)
                    return b"".join(chunks)
            except (httpx.HTTPError, ValueError, OSError):
                return None
        return None

    async def read_source(self, source: str) -> bytes | None:
        if source.startswith(("http://", "https://")):
            return await self._fetch_remote(source)
        path = Path(source)
        if not path.is_absolute() or not self._local_source_allowed(path):
            return None
        try:
            if path.stat().st_size > MAX_IMAGE_BYTES:
                return None
            return path.read_bytes()
        except OSError:
            return None

    async def ensure(
        self, source: str | None, kind: str, *, force: bool = False
    ) -> str | None:
        if not source:
            return None
        if source.startswith(("http://", "https://")):
            sha = sha_for_source(source)
        else:
            path = Path(source)
            try:
                stamp = int(path.stat().st_mtime) if path.exists() else 0
            except OSError:
                stamp = 0
            sha = sha_for_source(f"file:{path.resolve()}:{stamp}")
        if not force and self.variants_exist(sha, kind):
            return sha
        data = await self.read_source(source)
        if not data:
            return None
        async with self._write_lock:
            if self.variants_exist(sha, kind) and not force:
                return sha
            if not await self.save_variants_async(sha, kind, data):
                return None
        return sha

    async def color_for(self, source: str | None, sha: str | None) -> str | None:
        data = None
        if source and not source.startswith("http"):
            data = await self.read_source(source)
        if data is None and sha:
            variant = self.image_dir / f"{sha}_780.webp"
            if variant.is_file():
                try:
                    data = variant.read_bytes()
                except OSError:
                    data = None
        if data is None and source and source.startswith("http"):
            data = await self.read_source(source)
        if not data:
            return None
        return await asyncio.to_thread(extract_color, data)

    # -- 队列 -------------------------------------------------------------
    def enqueue(
        self,
        item_id: int,
        kind: str,
        source: str,
        target_field: str | None = None,
    ) -> None:
        if not source:
            return
        with Session(self.engine) as session:
            existing = session.exec(
                select(ImageTask).where(
                    ImageTask.item_id == item_id,
                    ImageTask.kind == kind,
                    ImageTask.remote_url == source,
                    ImageTask.target_field == target_field,
                )
                .order_by(ImageTask.id.desc())
            ).first()
            latest = session.exec(
                select(ImageTask.id).where(
                    ImageTask.item_id == item_id,
                    ImageTask.kind == kind,
                    ImageTask.target_field == target_field,
                ).order_by(ImageTask.id.desc()).limit(1)
            ).first()
            # A source may return after a newer source replaced it. Create a
            # new task so the old task cannot outrank the current selection.
            if existing is not None and latest != existing.id:
                existing = None
            if existing is not None:
                if existing.status in {"pending", "downloading"}:
                    return
                if existing.status == "done" and existing.sha and self.variants_exist(existing.sha, kind):
                    self._apply_task(session, existing, existing.sha)
                else:
                    existing.status = "pending"
                    existing.retry = 0
                    existing.error = None
                    existing.sha = None
                    existing.updated_at = utcnow()
                    session.add(existing)
                session.commit()
                return
            session.add(
                ImageTask(
                    item_id=item_id,
                    kind=kind,
                    remote_url=source,
                    status="pending",
                    target_field=target_field,
                    updated_at=utcnow(),
                )
            )
            session.commit()

    async def process_pending(self, limit: int = 8) -> int:
        with Session(self.engine) as session:
            tasks = session.exec(
                select(ImageTask)
                .where(ImageTask.status == "pending")
                .order_by(ImageTask.id)
                .limit(limit)
            ).all()
            for task in tasks:
                task.status = "downloading"
                session.add(task)
            session.commit()
            task_rows = [
                {
                    "id": t.id,
                    "item_id": t.item_id,
                    "kind": t.kind,
                    "url": t.remote_url,
                    "target": t.target_field,
                    "retry": t.retry,
                }
                for t in tasks
            ]
        if not task_rows:
            return 0
        semaphore = asyncio.Semaphore(4)

        async def work(row: dict) -> None:
            async with semaphore:
                try:
                    sha = await self.ensure(row["url"], row["kind"])
                except Exception:
                    sha = None
                with Session(self.engine) as session:
                    task = session.get(ImageTask, row["id"])
                    if task is None:
                        return
                    if sha is None:
                        task.retry += 1
                        task.error = "下载失败"
                        task.status = "broken" if task.retry >= 3 else "pending"
                    else:
                        task.sha = sha
                        task.status = "done"
                        task.error = None
                        self._apply_task(session, task, sha)
                    task.updated_at = utcnow()
                    session.add(task)
                    session.commit()

        results = await asyncio.gather(*(work(row) for row in task_rows), return_exceptions=True)
        failed = [row["id"] for row, result in zip(task_rows, results) if isinstance(result, Exception)]
        if failed:
            with Session(self.engine) as session:
                for task in session.exec(select(ImageTask).where(ImageTask.id.in_(failed))).all():
                    if task.status == "downloading":
                        task.retry += 1
                        task.status = "broken" if task.retry >= 3 else "pending"
                        task.error = "图片任务处理失败"
                        task.updated_at = utcnow()
                        session.add(task)
                session.commit()
        return len(task_rows)

    def _apply_task(self, session: Session, task: ImageTask, sha: str) -> None:
        item = session.get(Item, task.item_id)
        if item is None:
            return
        newer = session.exec(select(ImageTask.id).where(
            ImageTask.item_id == task.item_id,
            ImageTask.kind == task.kind,
            ImageTask.target_field == task.target_field,
            ImageTask.id > task.id,
        ).limit(1)).first()
        if newer is not None:
            return
        target = task.target_field or {
            "poster": "poster_path",
            "backdrop": "backdrop_path",
            "logo": "logo_path",
            "still": "still_path",
        }.get(task.kind)
        locked = item.get_locked_fields()
        if target in locked or (target and target.startswith("cast:") and "cast" in locked):
            return
        if target and target.startswith("cast:"):
            try:
                index = int(target.split(":", 1)[1])
                cast = json.loads(item.cast or "[]")
                if 0 <= index < len(cast):
                    cast[index]["avatar"] = sha
                    item.cast = json.dumps(cast, ensure_ascii=False)
            except (ValueError, json.JSONDecodeError):
                return
        elif target:
            setattr(item, target, sha)
            if target == "backdrop_path":
                color = None
                variant = self.image_dir / f"{sha}_780.webp"
                if variant.is_file():
                    try:
                        color = extract_color(variant.read_bytes())
                    except OSError:
                        color = None
                if color:
                    item.color_primary = color
        item.updated_at = utcnow()
        session.add(item)

    async def worker_loop(self, interval: float = 2.0) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.process_pending()
            except Exception:  # pragma: no cover - 队列不应中断
                processed = 0
            if processed == 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

    def start_worker(self) -> None:
        if self._worker is None:
            # A single worker owns this queue in the supported deployment. A
            # process restart otherwise leaves interrupted downloads stuck.
            with Session(self.engine) as session:
                for task in session.exec(select(ImageTask).where(
                    ImageTask.status.in_(["downloading", "done"])
                )).all():
                    if task.status == "downloading" or (
                        task.sha and not self.variants_exist(task.sha, task.kind)
                    ):
                        task.status = "pending"
                        task.updated_at = utcnow()
                        session.add(task)
                session.commit()
            self._worker = asyncio.create_task(self.worker_loop())

    # -- 过期清理 ---------------------------------------------------------
    def purge_older_than(self, days: int = 30) -> int:
        cutoff = (
            datetime.now(timezone.utc).timestamp() - days * 86400
        )
        # Referenced variants include uploads, which cannot be reconstructed
        # from a remote source and must not expire merely because they are old.
        referenced: set[str] = set()
        with Session(self.engine) as session:
            for item in session.exec(select(Item)).all():
                referenced.update(value for value in (
                    item.poster_path, item.backdrop_path, item.logo_path, item.still_path
                ) if value)
                try:
                    cast = json.loads(item.cast or "[]")
                    if isinstance(cast, list):
                        referenced.update(member["avatar"] for member in cast
                                          if isinstance(member, dict) and isinstance(member.get("avatar"), str))
                except (ValueError, TypeError):
                    # 单个条目的 cast 损坏不应阻止其它图片清理。
                    continue
            # 只保留每个 (item, kind, target_field) 最新任务的 sha。历史任务
            # 的 sha 如果继续算引用，被替换掉的图片会永久留在磁盘上。
            seen_targets: set[tuple[int, str, str | None]] = set()
            for task in session.exec(
                select(ImageTask).order_by(ImageTask.id.desc())
            ).all():
                key = (task.item_id, task.kind, task.target_field)
                if key in seen_targets:
                    continue
                seen_targets.add(key)
                if task.sha:
                    referenced.add(task.sha)
        removed = 0
        for file in self.image_dir.glob("*.webp"):
            try:
                sha = file.stem.rsplit("_", 1)[0]
                if sha not in referenced and file.stat().st_mtime < cutoff:
                    file.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
