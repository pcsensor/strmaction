"""用户管理 API（v0.9 多用户体系）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session, select, func

from ..deps import (
    get_current_user,
    get_engine,
    require_admin,
    get_auth,
)
from ..errors import APIError
from ..models import User, UserLibraryAccess, Library, PlayProgress, PlayToken
from ..models import Session as SessionRow
from ..models import UserPreference
from ..schemas import (
    CurrentUser,
    UserCreate,
    UserPatch,
    UserLibrariesUpdate,
    UserOut,
    UserDetail,
)
from ..security import AuthService

router = APIRouter(prefix="/users", tags=["用户管理"])


def _begin_admin_write(db: Session) -> None:
    """把管理员数量检查与写入串行化，避免并发操作把最后一个管理员移除。"""
    db.exec(text("BEGIN IMMEDIATE"))


def _other_enabled_admins(db: Session, user_id: int) -> int:
    count = db.exec(
        select(func.count(User.id)).where(
            User.role == "admin", User.enabled == True, User.id != user_id  # noqa: E712
        )
    ).first()
    return int(count or 0)


@router.get("", response_model=list[UserOut])
async def list_users(
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
):
    """获取用户列表（仅管理员）。"""
    with Session(engine) as db:
        users = db.exec(select(User)).all()
        result = []
        for user in users:
            # 统计授权库数量
            lib_count = db.exec(
                select(func.count(UserLibraryAccess.id)).where(
                    UserLibraryAccess.user_id == user.id
                )
            ).first()
            result.append(
                UserOut(
                    id=user.id,
                    username=user.username,
                    display_name=user.display_name,
                    role=user.role,
                    enabled=user.enabled,
                    library_count=lib_count if user.role == "user" else None,
                    last_login_at=user.last_login_at,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
            )
        return result


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    admin: CurrentUser = Depends(require_admin),
    auth: AuthService = Depends(get_auth),
    engine=Depends(get_engine),
):
    """创建新用户（仅管理员）。"""
    # 校验密码强度
    error = auth.check_password_strength(body.password)
    if error:
        raise APIError(400, "WEAK_PASSWORD", error)

    with Session(engine) as db:
        # 检查用户名是否已存在
        existing = db.exec(select(User).where(User.username == body.username)).first()
        if existing:
            raise APIError(400, "USERNAME_EXISTS", "用户名已存在")

        # 创建用户
        password_hash = auth.hash_password(body.password)
        user = User(
            username=body.username,
            password_hash=password_hash,
            display_name=body.display_name,
            role=body.role,
            enabled=True,
            created_by=admin.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # 授权媒体库（管理员无需授权）
        if body.role == "user" and body.library_ids:
            for lib_id in body.library_ids:
                # 检查库是否存在
                lib = db.get(Library, lib_id)
                if not lib:
                    continue
                access = UserLibraryAccess(
                    user_id=user.id,
                    library_id=lib_id,
                )
                db.add(access)
            db.commit()

        # 返回
        lib_count = len(body.library_ids) if body.role == "user" else None
        return UserOut(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            enabled=user.enabled,
            library_count=lib_count,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


@router.get("/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: int,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
):
    """获取用户详情（仅管理员）。"""
    with Session(engine) as db:
        user = db.get(User, user_id)
        if not user:
            raise APIError(404, "USER_NOT_FOUND", "用户不存在")

        # 获取授权的库
        libraries = []
        if user.role == "user":
            lib_ids = db.exec(
                select(UserLibraryAccess.library_id).where(
                    UserLibraryAccess.user_id == user.id
                )
            ).all()
            for lib_id in lib_ids:
                lib = db.get(Library, lib_id)
                if lib:
                    libraries.append(
                        {
                            "id": lib.id,
                            "name": lib.name,
                            "type": lib.type,
                            "enabled": lib.enabled,
                        }
                    )

        return UserDetail(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            enabled=user.enabled,
            libraries=libraries,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
            created_by=user.created_by,
        )


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserPatch,
    admin: CurrentUser = Depends(require_admin),
    auth: AuthService = Depends(get_auth),
    engine=Depends(get_engine),
):
    """更新用户信息（仅管理员）。"""
    new_password_hash: str | None = None
    if body.password is not None:
        error = auth.check_password_strength(body.password)
        if error:
            raise APIError(400, "WEAK_PASSWORD", error)
        # 在写事务外完成 Argon2 计算，避免占用 SQLite 写锁。
        new_password_hash = auth.hash_password(body.password)

    with Session(engine) as db:
        _begin_admin_write(db)
        user = db.get(User, user_id)
        if not user:
            raise APIError(404, "USER_NOT_FOUND", "用户不存在")

        # 防止管理员修改自己的角色
        if user.id == admin.id and body.role is not None and body.role != user.role:
            raise APIError(400, "CANNOT_CHANGE_OWN_ROLE", "不能修改自己的角色")

        # 更新字段
        if new_password_hash is not None:
            user.password_hash = new_password_hash

        if body.display_name is not None:
            user.display_name = body.display_name

        if body.enabled is not None:
            # 防止禁用最后一个管理员
            if not body.enabled and user.role == "admin":
                if _other_enabled_admins(db, user.id) == 0:
                    raise APIError(400, "LAST_ADMIN", "不能禁用最后一个管理员")
            user.enabled = body.enabled

        if body.role is not None and body.role != user.role:
            # 防止降级最后一个管理员
            if user.role == "admin":
                if _other_enabled_admins(db, user.id) == 0:
                    raise APIError(400, "LAST_ADMIN", "不能降级最后一个管理员")
            user.role = body.role

        from ..models import utcnow

        user.updated_at = utcnow()
        db.add(user)
        db.commit()
        db.refresh(user)

        # 管理员重置他人密码后，注销对方全部会话
        if body.password is not None and user.id != admin.id:
            auth.revoke_user_sessions(user.id)
        if body.enabled is False:
            auth.revoke_user_play_tokens(user.id)

        # 统计库数量
        lib_count = None
        if user.role == "user":
            lib_count = db.exec(
                select(func.count(UserLibraryAccess.id)).where(
                    UserLibraryAccess.user_id == user.id
                )
            ).first()

        return UserOut(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            enabled=user.enabled,
            library_count=lib_count,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
):
    """删除用户（仅管理员）。"""
    with Session(engine) as db:
        _begin_admin_write(db)
        user = db.get(User, user_id)
        if not user:
            raise APIError(404, "USER_NOT_FOUND", "用户不存在")

        # 防止删除自己
        if user.id == admin.id:
            raise APIError(400, "CANNOT_DELETE_SELF", "不能删除自己")

        # 防止删除最后一个管理员
        if user.role == "admin":
            if _other_enabled_admins(db, user.id) == 0:
                raise APIError(400, "LAST_ADMIN", "不能删除最后一个管理员")

        # 级联删除相关数据
        # 1. 用户的库授权
        for access in db.exec(
            select(UserLibraryAccess).where(UserLibraryAccess.user_id == user.id)
        ).all():
            db.delete(access)

        # 2. 用户的播放进度
        for progress in db.exec(
            select(PlayProgress).where(PlayProgress.user_id == user.id)
        ).all():
            db.delete(progress)

        # 3. 用户的播放凭证
        for token in db.exec(select(PlayToken).where(PlayToken.user_id == user.id)).all():
            db.delete(token)

        # 4. 用户偏好
        preference = db.get(UserPreference, user.id)
        if preference is not None:
            db.delete(preference)

        # 5. 用户的会话
        for session in db.exec(select(SessionRow).where(SessionRow.user_id == user.id)).all():
            db.delete(session)

        # 6. 清理其他用户对它的 created_by 引用，避免外键阻止删除
        for child in db.exec(select(User).where(User.created_by == user.id)).all():
            child.created_by = None
            db.add(child)

        # 7. 删除用户
        db.delete(user)
        db.commit()


@router.put("/{user_id}/libraries", response_model=dict)
@router.post("/{user_id}/libraries", response_model=dict)
async def update_user_libraries(
    user_id: int,
    body: UserLibrariesUpdate,
    _admin: CurrentUser = Depends(require_admin),
    engine=Depends(get_engine),
):
    """更新用户的媒体库授权（仅管理员）。"""
    with Session(engine) as db:
        user = db.get(User, user_id)
        if not user:
            raise APIError(404, "USER_NOT_FOUND", "用户不存在")

        if user.role == "admin":
            raise APIError(400, "ADMIN_NO_NEED", "管理员自动拥有所有库权限，无需分配")

        # 删除现有授权
        for access in db.exec(
            select(UserLibraryAccess).where(UserLibraryAccess.user_id == user.id)
        ).all():
            db.delete(access)

        # 添加新授权
        added = 0
        for lib_id in body.library_ids:
            lib = db.get(Library, lib_id)
            if not lib:
                continue
            access = UserLibraryAccess(
                user_id=user.id,
                library_id=lib_id,
            )
            db.add(access)
            added += 1

        db.commit()

        return {"user_id": user.id, "library_count": added}
