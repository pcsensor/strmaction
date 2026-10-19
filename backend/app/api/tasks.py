"""任务与日志 API（v0.9: 仅管理员）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from ..deps import get_engine, get_tasks, require_admin
from ..errors import APIError
from ..jobs import TaskManager
from ..models import TaskLog
from ..schemas import CurrentUser
from ..serializers import task_payload

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
def list_tasks(
    limit: int = Query(50, ge=1, le=200),
    kind: str | None = Query(None),
    status: str | None = Query(None),
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
):
    with Session(engine) as session:
        query = select(TaskLog)
        if kind:
            query = query.where(TaskLog.kind == kind)
        if status:
            query = query.where(TaskLog.status == status)
        rows = session.exec(
            query.order_by(TaskLog.started_at.desc(), TaskLog.id.desc()).limit(limit)
        ).all()
        return {"tasks": [task_payload(row) for row in rows]}


@router.get("/{task_id}")
def get_task(
    task_id: int,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
):
    with Session(engine) as session:
        row = session.get(TaskLog, task_id)
        if row is None:
            raise APIError(404, "TASK_NOT_FOUND", "任务不存在")
        return task_payload(row)


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: int,
    _admin: CurrentUser = Depends(require_admin),
    tasks: TaskManager = Depends(get_tasks),
):
    # 扫描/刮削任务是协作式取消：目前仅返回不可取消状态，避免误报
    raise APIError(400, "NOT_CANCELLABLE", "当前任务不支持取消")
