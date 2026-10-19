"""图片下载、WebP 多尺寸生成、主题色提取与异步图片队列（附录 D.7）。"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image
from sqlmodel import Session, select

from .config_store import SettingsService
from .models import ImageTask, Item, utcnow

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
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception:
            return False
        if image.mode not in {"RGB", "RGBA"}:
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
                save_image = variant.convert("RGB") if variant.mode == "RGBA" else variant
                save_image.save(target, "WEBP", quality=82, method=4)
            except Exception:
                return False
        return True

    async def read_source(self, source: str) -> bytes | None:
        if source.startswith(("http://", "https://")):
            try:
                response = await self.client().get(source)
                if response.status_code in {404, 410}:
                    return None
                response.raise_for_status()
                return response.content
            except Exception:
                return None
        path = Path(source)
        if not path.is_absolute():
            return None
        try:
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
            if not self.save_variants(sha, kind, data):
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
        return extract_color(data)

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
                    ImageTask.remote_url == source,
                    ImageTask.status.in_(["pending", "downloading", "done"]),
                )
            ).first()
            if existing is not None:
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
                sha = await self.ensure(row["url"], row["kind"])
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

        await asyncio.gather(*(work(row) for row in task_rows), return_exceptions=True)
        return len(task_rows)

    def _apply_task(self, session: Session, task: ImageTask, sha: str) -> None:
        item = session.get(Item, task.item_id)
        if item is None:
            return
        target = task.target_field or {
            "poster": "poster_path",
            "backdrop": "backdrop_path",
            "logo": "logo_path",
            "still": "still_path",
        }.get(task.kind)
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
            self._worker = asyncio.create_task(self.worker_loop())

    # -- 过期清理 ---------------------------------------------------------
    def purge_older_than(self, days: int = 30) -> int:
        cutoff = (
            datetime.now(timezone.utc).timestamp() - days * 86400
        )
        removed = 0
        for file in self.image_dir.glob("*.webp"):
            try:
                if file.stat().st_mtime < cutoff:
                    file.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
