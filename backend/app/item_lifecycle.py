"""条目生命周期操作：依赖清理与条目合并。

这些操作同时被扫描器、媒体库删除和手工合并使用。集中实现可以避免某个
入口漏删 ImageTask / PlayToken 等子表，最终触发 SQLite 外键错误。
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import Session, select

from .models import ImageTask, Item, MediaFile, PlayProgress, PlaySession, PlayToken


def delete_item_dependents(
    session: Session, item_id: int, *, include_progress: bool = True
) -> None:
    """删除指向条目的子表记录；不删除条目本身。"""
    models = (ImageTask, PlaySession, PlayToken)
    for model in models:
        session.exec(delete(model).where(model.item_id == item_id))
    if include_progress:
        session.exec(delete(PlayProgress).where(PlayProgress.item_id == item_id))


def merge_items(session: Session, target: Item, source: Item) -> None:
    """把 source 合并进 target，保留目标条目与较新的播放进度。"""
    if source.id is None or target.id is None:
        raise ValueError("条目尚未持久化")
    if source.id == target.id:
        raise ValueError("不能把条目合并到自身")
    if source.library_id != target.library_id:
        raise ValueError("只能合并同一媒体库内的条目")
    if source.kind != target.kind:
        raise ValueError("只能合并同类型条目")

    for media in session.exec(
        select(MediaFile).where(MediaFile.item_id == source.id)
    ).all():
        media.item_id = target.id
        session.add(media)

    # 迁移播放进度：目标已有同用户记录时保留更新的一条，避免用户进度丢失。
    source_progress = session.exec(
        select(PlayProgress).where(PlayProgress.item_id == source.id)
    ).all()
    target_progress = {
        row.user_id: row
        for row in session.exec(
            select(PlayProgress).where(PlayProgress.item_id == target.id)
        ).all()
    }
    for row in source_progress:
        existing = target_progress.get(row.user_id)
        if existing is None:
            row.item_id = target.id
            session.add(row)
            target_progress[row.user_id] = row
            continue
        # 比较修订号；相同修订号时比较更新时间。
        newer = (row.revision or 0, row.updated_at or "") > (
            existing.revision or 0,
            existing.updated_at or "",
        )
        if newer:
            existing.position_ms = row.position_ms
            existing.duration_ms = row.duration_ms
            existing.finished = row.finished
            existing.dismissed = row.dismissed
            existing.last_client_key = row.last_client_key
            existing.revision = row.revision
            existing.client_session = row.client_session
            existing.client_sequence = row.client_sequence
            existing.updated_at = row.updated_at
            session.add(existing)
        session.delete(row)

    delete_item_dependents(session, source.id, include_progress=False)
    session.delete(source)
    session.add(target)
