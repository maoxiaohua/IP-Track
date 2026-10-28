"""
Authentication API.

Guests stay read-only; logging in unlocks create / update / delete.
Only backend-core mounts this router (it is the service that owns the users table).
"""

import asyncio
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import create_access_token, get_current_user
from core.config import settings
from core.database import get_db
from schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserPublic,
)
from services import auth_service
from utils.logger import logger

router = APIRouter(prefix="/auth", tags=["auth"])

# Simple in-memory brute-force guard: per client IP, per 5-minute window.
_FAILURE_WINDOW_SECONDS = 300
_MAX_FAILURES = 10
_failures: Dict[str, Deque[float]] = defaultdict(deque)
_failures_lock = asyncio.Lock()


def _client_ip(request: Request) -> str:
    # Behind the Vite dev proxy the peer address is the proxy, so prefer the
    # first forwarded hop when present.
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _check_throttle(ip: str) -> None:
    now = time.monotonic()
    async with _failures_lock:
        attempts = _failures[ip]
        while attempts and now - attempts[0] > _FAILURE_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= _MAX_FAILURES:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="登录失败次数过多，请 5 分钟后再试",
            )


async def _record_failure(ip: str) -> None:
    async with _failures_lock:
        _failures[ip].append(time.monotonic())


async def _clear_failures(ip: str) -> None:
    async with _failures_lock:
        _failures.pop(ip, None)


def _token_response(user, must_change: bool) -> LoginResponse:
    return LoginResponse(
        access_token=create_access_token(
            username=user.username,
            user_id=user.id,
            role=user.role,
            must_change_password=must_change,
        ),
        expires_in=settings.AUTH_TOKEN_EXPIRE_MINUTES * 60,
        user=UserPublic.model_validate(user),
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ip = _client_ip(request)
    await _check_throttle(ip)

    user = await auth_service.authenticate(db, payload.username, payload.password)
    if user is None:
        await _record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    await _clear_failures(ip)
    logger.info(f"用户 '{user.username}' 登录成功 ({ip})")
    # The token is always issued; the client is told to change the temporary
    # password before anything else.
    return _token_response(user, bool(user.must_change_password))


@router.get("/me", response_model=UserPublic)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    token_user = get_current_user(request)
    user = await auth_service.get_user_by_id(db, int(token_user.get("uid") or 0))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账户不存在或已停用")
    return UserPublic.model_validate(user)


@router.post("/change-password", response_model=UserPublic)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    token_user = get_current_user(request)
    user = await auth_service.get_user_by_id(db, int(token_user.get("uid") or 0))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账户不存在或已停用")

    new_password = payload.new_password
    if len(new_password) < settings.AUTH_PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"新密码至少需要 {settings.AUTH_PASSWORD_MIN_LENGTH} 位",
        )

    try:
        await auth_service.change_password(
            db, user, payload.current_password, new_password
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    logger.info(f"用户 '{user.username}' 修改了密码")
    return UserPublic.model_validate(user)


@router.post("/logout")
async def logout(request: Request):
    """Stateless JWT: the client drops the token; this endpoint is a no-op hook."""
    user = get_current_user(request)
    logger.info(f"用户 '{user.get('sub')}' 退出登录")
    return {"message": "已退出登录"}
