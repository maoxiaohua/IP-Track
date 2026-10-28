"""
Authentication utilities shared by all three backend services.

Policy (single source of truth, so core / ipam / collector never diverge):

* Guests (no token) may issue GET / HEAD / OPTIONS plus a small whitelist of
  pure-read POST endpoints (IP lookup, subnet calculator, ...).
* Every other request - create / update / delete / trigger an action -
  requires a valid bearer token.

Passwords use PBKDF2-HMAC-SHA256 from the standard library (passlib 1.7.4 is
incompatible with bcrypt >= 4.1, so we do not depend on it).
"""
import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.config import settings

PASSWORD_SCHEME = "pbkdf2_sha256"
PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 600_000

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Endpoints reachable without a token at all.
PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    f"{settings.API_V1_PREFIX}/auth/login",
})

# Read-only work done through POST (query / compute only, no state change).
PUBLIC_READ_POST_PATHS = frozenset({
    f"{settings.API_V1_PREFIX}/lookup/ip",
    f"{settings.API_V1_PREFIX}/ipam/network-search",
    f"{settings.API_V1_PREFIX}/ipam/subnet-calculator",
    f"{settings.API_V1_PREFIX}/command-templates/match-preview",
    # Dry-run subnet parser used by the probe page before starting a sweep.
    f"{settings.API_V1_PREFIX}/subnet-probe/parse",
})


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str) -> str:
    """Return ``pbkdf2_sha256$<iterations>$<salt>$<hash>``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM, password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return "$".join((PASSWORD_SCHEME, str(PBKDF2_ITERATIONS), _b64encode(salt), _b64encode(digest)))


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time check of a password against a stored hash."""
    if not password or not stored_hash:
        return False
    try:
        scheme, iterations, salt_b64, digest_b64 = stored_hash.split("$")
        if scheme != PASSWORD_SCHEME:
            return False
        digest = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM, password.encode("utf-8"), _b64decode(salt_b64), int(iterations)
        )
        return hmac.compare_digest(digest, _b64decode(digest_b64))
    except (ValueError, TypeError, binascii.Error):
        return False


def create_access_token(
    username: str,
    user_id: int,
    role: str,
    must_change_password: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": username,
        "uid": user_id,
        "role": role,
        "mcp": bool(must_change_password),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.AUTH_TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.AUTH_ALGORITHM)


def decode_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.AUTH_ALGORITHM])
    except JWTError:
        return None


def extract_token(request: Request) -> Optional[str]:
    """Bearer header first; ``?token=`` fallback for EventSource clients."""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.query_params.get("token") or None


def _is_public_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if normalized in PUBLIC_PATHS:
        return True
    return normalized.startswith("/docs") or normalized.startswith("/redoc")


class ReadOnlyGuestMiddleware(BaseHTTPMiddleware):
    """Reject write requests made without a valid token (HTTP 401)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if _is_public_path(path):
            return await call_next(request)

        method = request.method.upper()
        if method in SAFE_METHODS:
            return await call_next(request)

        normalized = path.rstrip("/") or "/"
        if method == "POST" and normalized in PUBLIC_READ_POST_PATHS:
            return await call_next(request)

        payload = decode_token(extract_token(request))
        if not payload:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "当前为只读访客模式，请先登录后再执行该操作"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        request.state.user = payload
        return await call_next(request)


def get_current_user(request: Request) -> Dict[str, Any]:
    """FastAPI dependency for endpoints that always require a login."""
    user = getattr(request.state, "user", None)
    if not user:
        user = decode_token(extract_token(request))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
