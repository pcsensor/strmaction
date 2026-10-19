"""任务编排与定时调度（APScheduler）。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from .config_store import SettingsService
from .models import Item, Library, TaskLog, utcnow
from .scanner.sync import ScannerService, missing_cleanup
from .scraper.cache import purge_expired
from .scraper.service import ScrapeService
from .images import ImageService


def _loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


class TaskManager:
    def __init__(
        self,
        engine,
        settings: SettingsService,
        images: ImageService,
    ):
        self.engine = engine
        self.settings = settings
        self.images = images
        self.scanner = ScannerService(engine, settings)
        self._running: dict[str, int] = {}
        self._tasks: set[asyncio.Task] = set()

    # -- 任务记录 ---------------------------------------------------------
    def _create_task(self, kind: str, library_id: int | None, message: str = "") -> int:
        with Session(self.engine) as session:
            row = TaskLog(
                kind=kind,
                library_id=library_id,
                status="running",
                message=message,
                stats=json.dumps({"done": 0, "total": 0}, ensure_ascii=False),
                started_at=utcnow(),
            )
            session.add(row)
            session.commit()
            return row.id or 0

    def _update_task(self, task_id: int, **fields: Any) -> None:
        with Session(self.engine) as session:
            row = session.get(TaskLog, task_id)
            if row is None:
                return
            for key, value in fields.items():
                if key == "stats" and not isinstance(value, str):
                    value = json.dumps(value, ensure_ascii=False)
                setattr(row, key, value)
            session.add(row)
            session.commit()

    def _finish_task(self, task_id: int, status: str, stats: dict, message: str = "") -> None:
        self._update_task(
            task_id,
            status=status,
            stats=stats,
            message=message,
            finished_at=utcnow(),
        )

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- 扫描 -------------------------------------------------------------
    def start_scan(self, library_id: int) -> int:
        key = f"scan:{library_id}"
        existing = self._running.get(key)
        if existing:
            return existing
        task_id = self._create_task("scan", library_id, "扫描目录")
        self._running[key] = task_id
        self._spawn(self._run_scan(task_id, library_id, key))
        return task_id

    async def _run_scan(self, task_id: int, library_id: int, key: str) -> None:
        try:
            stats: dict[str, Any] = {}

            def progress(payload: dict) -> None:
                stats.update(payload.get("stats") or {})
                if "done" in payload:
                    stats["done"] = payload["done"]
                    stats["total"] = payload["total"]
                self._update_task(task_id, stats=payload)

            result = await asyncio.to_thread(
                self.scanner.scan_library, library_id, progress
            )
            stats = result
            message = "扫描完成"
            with Session(self.engine) as session:
                library = session.get(Library, library_id)
                auto_scrape = bool(library and library.auto_scrape)
            has_provider = self._has_provider(library_id)
            if not has_provider:
                # 未配置任何 Key：全站走文件名兜底，不把条目挂成待修正
                with Session(self.engine) as session:
                    rows = session.exec(
                        select(Item).where(
                            Item.library_id == library_id,
                            Item.match_state == "pending",
                            Item.kind.in_(["movie", "series"]),
                        )
                    ).all()
                    for row in rows:
                        row.match_state = "skipped"
                        session.add(row)
                    if rows:
                        session.commit()
            if auto_scrape and has_provider:
                with Session(self.engine) as session:
                    item_ids = [
                        i.id
                        for i in session.exec(
                            select(Item).where(
                                Item.library_id == library_id,
                                Item.kind.in_(["movie", "series"]),
                                Item.match_state.in_(
                                    ["pending", "failed", "skipped"]
                                ),
                                Item.deleted_at == None,  # noqa: E711
                            )
                        ).all()
                    ]
                if item_ids:
                    scrape_stats = await self._scrape_ids(
                        task_id, item_ids, force=False, base_stats=stats
                    )
                    stats = {**stats, "scrape": scrape_stats}
                    message = "扫描并刮削完成"
            self._finish_task(task_id, "success", stats, message)
        except Exception as exc:  # pragma: no cover
            self._finish_task(task_id, "failed", {"error": str(exc)}, f"扫描失败: {exc}")
        finally:
            self._running.pop(key, None)

    def _has_provider(self, library_id: int) -> bool:
        with Session(self.engine) as session:
            library = session.get(Library, library_id)
            if library is None:
                return False
            priority = self.settings.priority_for_library(library)
        for name in priority:
            config = self.settings.provider_config(name)
            if config.get("api_key"):
                return True
        return False

    # -- 刮削 -------------------------------------------------------------
    def start_scrape(self, library_id: int, mode: str = "pending") -> int:
        key = f"scrape:{library_id}:{mode}"
        existing = self._running.get(key)
        if existing:
            return existing
        task_id = self._create_task("scrape", library_id, "刮削元数据")
        self._running[key] = task_id
        self._spawn(self._run_scrape(task_id, library_id, mode, key))
        return task_id

    def start_refresh_item(self, item_id: int) -> int:
        key = f"refresh:item:{item_id}"
        existing = self._running.get(key)
        if existing:
            return existing
        task_id = self._create_task("refresh", None, "刷新条目元数据")
        self._running[key] = task_id
        self._spawn(self._run_single_refresh(task_id, item_id, key))
        return task_id

    async def _run_scrape(self, task_id: int, library_id: int, mode: str, key: str) -> None:
        try:
            with Session(self.engine) as session:
                query = select(Item).where(
                    Item.library_id == library_id,
                    Item.kind.in_(["movie", "series"]),
                    Item.deleted_at == None,  # noqa: E711
                )
                if mode == "pending":
                    query = query.where(
                        Item.match_state.in_(["pending", "failed", "skipped"])
                    )
                elif mode == "refresh":
                    query = query.where(Item.match_state != "manual")
                items = session.exec(query).all()
                item_ids = [i.id for i in items if i.id is not None]
            stats = await self._scrape_ids(task_id, item_ids, force=(mode == "refresh"))
            self._finish_task(task_id, "success", stats, "刮削完成")
        except Exception as exc:  # pragma: no cover
            self._finish_task(task_id, "failed", {"error": str(exc)}, f"刮削失败: {exc}")
        finally:
            self._running.pop(key, None)

    async def _run_single_refresh(self, task_id: int, item_id: int, key: str) -> None:
        try:
            service = ScrapeService(self.engine, self.settings, self.images)
            try:
                result = await service.scrape_item(item_id, force=True)
            finally:
                await service.close()
            stats = {"total": 1, "result": result}
            status = "success" if result.get("status") in {"ok", "skipped"} else "failed"
            self._finish_task(task_id, status, stats, "刷新完成")
        except Exception as exc:  # pragma: no cover
            self._finish_task(task_id, "failed", {"error": str(exc)}, f"刷新失败: {exc}")
        finally:
            self._running.pop(key, None)

    async def _scrape_ids(
        self,
        task_id: int,
        item_ids: list[int],
        *,
        force: bool,
        base_stats: dict | None = None,
    ) -> dict[str, Any]:
        service = ScrapeService(self.engine, self.settings, self.images)
        stats: dict[str, Any] = {
            **(base_stats or {}),
            "scrape_total": len(item_ids),
            "scrape_done": 0,
            "ok": 0,
            "failed": 0,
            "skipped": 0,
            "failures": [],
        }
        semaphore = asyncio.Semaphore(4)

        async def run(item_id: int) -> dict:
            async with semaphore:
                return await service.scrape_item(item_id, force=force)

        try:
            for index in range(0, len(item_ids), 4):
                chunk = item_ids[index : index + 4]
                results = await asyncio.gather(*(run(i) for i in chunk))
                for item_id, result in zip(chunk, results):
                    status = result.get("status")
                    if status == "ok":
                        stats["ok"] += 1
                    elif status in {"failed", "missing"}:
                        stats["failed"] += 1
                        if len(stats["failures"]) < 100:
                            stats["failures"].append(
                                {
                                    "item_id": item_id,
                                    "reason": result.get("reason") or status,
                                    "errors": result.get("errors"),
                                }
                            )
                    else:
                        stats["skipped"] += 1
                stats["scrape_done"] = min(len(item_ids), index + 4)
                stats["done"] = stats["scrape_done"]
                stats["total"] = len(item_ids)
                self._update_task(task_id, stats=stats)
        finally:
            await service.close()
        return stats

    # -- 刷新全库 ---------------------------------------------------------
    def start_refresh_library(self, library_id: int) -> int:
        return self.start_scrape(library_id, mode="refresh")


class SchedulerService:
    def __init__(
        self,
        engine,
        settings: SettingsService,
        tasks: TaskManager,
        images: ImageService,
    ):
        self.engine = engine
        self.settings = settings
        self.tasks = tasks
        self.images = images
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._job_ids: set[str] = set()

    def start(self) -> None:
        self.reload()
        self.scheduler.add_job(
            self._auto_refresh,
            CronTrigger(hour=4, minute=10),
            id="auto_refresh",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._cleanup,
            CronTrigger(hour=5, minute=20),
            id="cleanup",
            replace_existing=True,
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def reload(self) -> None:
        for job_id in list(self._job_ids):
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
        self._job_ids.clear()
        with Session(self.engine) as session:
            libraries = session.exec(
                select(Library).where(Library.enabled == True)  # noqa: E712
            ).all()
        for library in libraries:
            if not library.scan_cron:
                continue
            try:
                trigger = CronTrigger.from_crontab(
                    library.scan_cron, timezone="Asia/Shanghai"
                )
            except ValueError:
                continue
            job_id = f"scan:{library.id}"
            self.scheduler.add_job(
                self._scheduled_scan,
                trigger,
                args=[library.id],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=300,
            )
            self._job_ids.add(job_id)

    async def _scheduled_scan(self, library_id: int) -> None:
        self.tasks.start_scan(library_id)

    async def _auto_refresh(self) -> None:
        days = int(self.settings.scraper().get("auto_refresh_days") or 0)
        if days <= 0:
            return
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds")
        with Session(self.engine) as session:
            libraries = session.exec(
                select(Library).where(Library.enabled == True)  # noqa: E712
            ).all()
            for library in libraries:
                items = session.exec(
                    select(Item).where(
                        Item.library_id == library.id,
                        Item.kind.in_(["movie", "series"]),
                        Item.match_state.notin_(["manual", "skipped"]),  # type: ignore[attr-defined]
                        Item.updated_at < cutoff,
                    )
                ).all()
                if items:
                    self.tasks.start_scrape(library.id, mode="refresh")

    async def _cleanup(self) -> None:
        with Session(self.engine) as session:
            missing_cleanup(session, self.settings, 7)
        purge_expired(self.engine)
        self.images.purge_older_than(90)
