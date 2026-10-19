"""StrmAction FastAPI 入口：API + 静态前端托管。"""

from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import api_router
from .config import ConfigManager
from .config_store import SettingsService
from .db import Database
from .deps import AppState
from .errors import register_error_handlers
from .images import ImageService
from .jobs import SchedulerService, TaskManager
from .security import SESSION_COOKIE, AuthService

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/state",
    "/api/auth/login",
    "/api/auth/setup",
}

# 原生播放器只拿 play_token，不碰 Cookie（§12.7 / §16.6）：
# 允许这两类路径用 Bearer / ?pt= 进入，具体校验在端点内完成。
PLAY_TOKEN_PATHS = re.compile(
    r"^/api/items/(?P<item_id>\d+)/(?:progress|subtitles(?:/[^/]+)?)$"
)


def _play_token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token
    token = request.query_params.get("pt")
    return token or None


class CachedStaticFiles(StaticFiles):
    def __init__(self, *args, cache_control: str = "public, max-age=31536000, immutable", **kwargs):
        self.cache_control = cache_control
        super().__init__(*args, **kwargs)

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = self.cache_control
        return response


def _find_web_dir() -> Path | None:
    candidates = []
    if os.environ.get("STRMACTION_WEB_DIR"):
        candidates.append(Path(os.environ["STRMACTION_WEB_DIR"]))
    root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            root / "frontend" / "dist",
            root / "dist",
            Path.cwd() / "frontend" / "dist",
            Path("/app/static"),
        ]
    )
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = ConfigManager(os.environ.get("STRMACTION_CONFIG"))
    config.ensure_dirs()
    db = Database(config)
    settings = SettingsService(config, db.engine)
    auth = AuthService(settings, db.engine)
    images = ImageService(settings)
    tasks = TaskManager(db.engine, settings, images)
    scheduler = SchedulerService(db.engine, settings, tasks, images)
    state = AppState(config, db, settings, auth, images, tasks, scheduler)
    app.state.app_state = state

    auth.purge_expired_sessions()
    images.start_worker()
    if os.environ.get("STRMACTION_DISABLE_SCHEDULER") != "1":
        scheduler.start()
    print(f"[startup] StrmAction {__version__} 数据目录={config.data_dir}")

    try:
        yield
    finally:
        await images.close()
        try:
            scheduler.shutdown()
        except Exception:
            pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="StrmAction",
        description="面向 .strm 媒体库的刮削、展示与播放分发服务",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    register_error_handlers(app)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api") and path not in PUBLIC_API_PATHS:
            state: AppState = request.app.state.app_state
            user = state.auth.validate_session(request.cookies.get(SESSION_COOKIE))
            if user:
                request.state.user = user
            else:
                match = PLAY_TOKEN_PATHS.match(path)
                token = _play_token_from_request(request) if match else None
                if match and token:
                    # 端点负责校验 token / item_id 是否匹配
                    request.state.play_token = token
                    request.state.play_item_id = int(match.group("item_id"))
                else:
                    code = "SETUP_REQUIRED" if state.auth.needs_setup() else "UNAUTHORIZED"
                    return JSONResponse(
                        {"error": {"code": code, "message": "请先登录"}},
                        status_code=401,
                    )
        elif path in PUBLIC_API_PATHS:
            state = request.app.state.app_state
            user = state.auth.validate_session(request.cookies.get(SESSION_COOKIE))
            if user:
                request.state.user = user
        return await call_next(request)

    app.include_router(api_router)

    images_dir = None
    try:
        config = ConfigManager(os.environ.get("STRMACTION_CONFIG"))
        images_dir = config.image_dir
    except Exception:
        images_dir = None
    if images_dir is not None:
        images_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/img",
            CachedStaticFiles(directory=str(images_dir)),
            name="images",
        )

    web_dir = _find_web_dir()
    if web_dir is not None:
        assets = web_dir / "assets"
        if assets.is_dir():
            app.mount(
                "/assets",
                CachedStaticFiles(directory=str(assets)),
                name="assets",
            )

    @app.get("/", include_in_schema=False)
    async def index():
        if web_dir is not None and (web_dir / "index.html").is_file():
            return FileResponse(
                web_dir / "index.html",
                headers={"Cache-Control": "no-cache"},
            )
        return JSONResponse(
            {
                "app": "StrmAction",
                "version": __version__,
                "message": "前端尚未构建，请运行 npm run build（或使用 Docker 镜像）",
                "docs": "/docs",
                "health": "/api/health",
            }
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "img/", "assets/", "docs", "redoc", "openapi.json")):
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "资源不存在"}},
                status_code=404,
            )
        if web_dir is not None:
            candidate = (web_dir / full_path).resolve()
            try:
                candidate.relative_to(web_dir.resolve())
            except ValueError:
                candidate = web_dir / "index.html"
            if candidate.is_file() and candidate.name != "index.html":
                return FileResponse(candidate)
            if (web_dir / "index.html").is_file():
                return FileResponse(
                    web_dir / "index.html", headers={"Cache-Control": "no-cache"}
                )
        return JSONResponse(
            {"error": {"code": "NOT_FOUND", "message": "页面不存在"}},
            status_code=404,
        )

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    config = ConfigManager(os.environ.get("STRMACTION_CONFIG"))
    server = config.effective().get("server") or {}
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("STRMACTION_HOST", server.get("host", "0.0.0.0")),
        port=int(os.environ.get("STRMACTION_PORT", server.get("port", 8080))),
        reload=False,
    )
