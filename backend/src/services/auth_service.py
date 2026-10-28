"""User lookup and login helpers (DB side of authentication)."""

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import hash_password, verify_password
from core.config import settings
from models.user import User
from utils.logger import logger


class AuthError(Exception):
    """Raised for user-facing authentication failures."""


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    return await db.get(User, user_id)


async def authenticate(db: AsyncSession, username: str, password: str) -> Optional[User]:
    """Return the user on success, ``None`` on bad credentials / disabled account."""
    user = await get_user_by_username(db, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return user


async def change_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AuthError("当前密码不正确")
    if len(new_password) < settings.AUTH_PASSWORD_MIN_LENGTH:
        raise AuthError(f"新密码至少需要 {settings.AUTH_PASSWORD_MIN_LENGTH} 位")
    if new_password == current_password:
        raise AuthError("新密码不能与当前密码相同")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await db.commit()


async def ensure_initial_admin(db: AsyncSession) -> None:
    """Create the bootstrap admin once, when no account exists yet.

    Password source: ``INITIAL_ADMIN_PASSWORD`` from the environment. When that
    is empty a random one-time password is generated and printed once.
    """
    count = await db.scalar(select(func.count()).select_from(User))
    if count:
        return

    username = settings.INITIAL_ADMIN_USERNAME
    configured = settings.INITIAL_ADMIN_PASSWORD
    password = configured or secrets.token_urlsafe(12)

    db.add(
        User(
            username=username,
            password_hash=hash_password(password),
            display_name="Administrator",
            role="admin",
            must_change_password=True,
            is_active=True,
        )
    )
    await db.commit()

    if configured:
        logger.info(f"已创建初始管理员账户 '{username}'（密码来自 INITIAL_ADMIN_PASSWORD）")
    else:
        logger.warning("=" * 64)
        logger.warning("已创建初始管理员账户，请立即登录并修改密码：")
        logger.warning(f"  用户名: {username}")
        logger.warning(f"  临时密码: {password}")
        logger.warning("  该密码只显示这一次；修改后本行日志即失效。")
        logger.warning("=" * 64)
