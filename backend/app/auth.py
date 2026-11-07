import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AppUser


bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: str | None = None) -> str:
    actual_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt.encode("ascii"), 260_000)
    return f"pbkdf2_sha256$260000${actual_salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (TypeError, ValueError):
        return False


def seed_users(db: Session) -> None:
    bootstrap = (
        (settings.personal_username, settings.personal_password, "个人用户", "personal"),
        (settings.admin_username, settings.admin_password, "治理管理员", "admin"),
        (settings.enterprise_username, settings.enterprise_password, "企业 HR", "enterprise"),
    )
    changed = False
    for username, password, display_name, role in bootstrap:
        existing = db.scalar(select(AppUser).where(AppUser.username == username))
        if existing:
            if not verify_password(password, existing.password_hash):
                existing.password_hash = hash_password(password)
                changed = True
            existing.display_name = display_name
            existing.role = role
            existing.is_active = True
            continue
        db.add(
            AppUser(
                username=username,
                password_hash=hash_password(password),
                display_name=display_name,
                role=role,
                is_active=True,
            )
        )
        changed = True
    if changed:
        db.commit()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user: AppUser) -> tuple[str, int]:
    expires_at = int(time.time()) + settings.auth_token_hours * 3600
    payload = {
        "sub": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "role": user.role,
        "exp": expires_at,
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = _b64encode(hmac.new(settings.auth_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}", expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64encode(hmac.new(settings.auth_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise ValueError("expired")
        return payload
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(401, "登录状态无效或已过期")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AppUser:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "请先登录")
    payload = decode_access_token(credentials.credentials)
    user = db.get(AppUser, payload.get("sub", ""))
    if not user or not user.is_active:
        raise HTTPException(401, "账号不存在或已停用")
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AppUser | None:
    if not credentials:
        return None
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "登录状态无效")
    payload = decode_access_token(credentials.credentials)
    user = db.get(AppUser, payload.get("sub", ""))
    if not user or not user.is_active:
        raise HTTPException(401, "账号不存在或已停用")
    return user


def require_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role != "admin":
        raise HTTPException(403, "当前账号无权进入管理端")
    return user


def require_enterprise(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role != "enterprise":
        raise HTTPException(403, "当前账号无权进入企业端")
    return user
