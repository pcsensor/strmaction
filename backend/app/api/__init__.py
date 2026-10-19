"""API 路由集合。"""

from __future__ import annotations

from fastapi import APIRouter

from . import auth, home, items, libraries, play, search, settings, system, tasks, users

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(libraries.router)
api_router.include_router(items.router)
api_router.include_router(play.router)
api_router.include_router(home.router)
api_router.include_router(search.router)
api_router.include_router(tasks.router)
api_router.include_router(settings.router)
api_router.include_router(system.router)
api_router.include_router(users.router)
