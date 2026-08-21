"""认证与用户体系（阶段1）。

users / refresh_tokens 两张表 + JWT（access 30min + refresh 30天）+ bcrypt 密码哈希。
- access token：无状态，服务端不查库，验签即过（exp + type）。
- refresh token：有状态，服务端存 SHA-256 摘要，轮换式（每次刷新作废旧 token 发新的），
  支持按用户全部吊销（登出）。
- JWT 密钥：环境变量 EXAM_BOOSTER_JWT_SECRET，缺失时生成并写入 backend/.env
  （首次启动自动落地，避免每次重启全体用户下线）。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from passlib.hash import bcrypt

from .routers.deps import get_connection

ACCESS_TOKEN_TTL = timedelta(minutes=30)
REFRESH_TOKEN_TTL = timedelta(days=30)
BCRYPT_ROUNDS = 12

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "exam-booster"

# .env 位于 backend/.env（本文件在 backend/app/ 下）
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
JWT_SECRET_ENV_KEY = "EXAM_BOOSTER_JWT_SECRET"


def _load_jwt_secret() -> str:
    """读取 JWT 密钥；缺失时生成并追加写入 backend/.env（保留现有行）。"""
    secret = os.getenv(JWT_SECRET_ENV_KEY, "").strip()
    if secret:
        return secret
    if os.path.exists(ENV_FILE):
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{JWT_SECRET_ENV_KEY}="):
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    secret = secrets.token_urlsafe(48)
    try:
        with open(ENV_FILE, "a", encoding="utf-8") as handle:
            handle.write(f"\n{JWT_SECRET_ENV_KEY}={secret}\n")
    except OSError:
        # .env 不可写时退回纯内存密钥（重启后失效，但不阻断启动）
        pass
    os.environ[JWT_SECRET_ENV_KEY] = secret
    return secret


JWT_SECRET = _load_jwt_secret()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def initialize_auth_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                replaced_by_token_hash TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
            """
        )
        # 顺手清理：启动时删除已过期 refresh token（物理删除，摘要无留存价值）
        connection.execute(
            "DELETE FROM refresh_tokens WHERE expires_at <= ?",
            (_iso(_utcnow()),),
        )


def _hash_password(password: str) -> str:
    # SHA-256 预哈希：任意长度密码 -> 32 字节 hex（64 字符 < 72 上限），再入 bcrypt
    prehashed = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return bcrypt.using(rounds=BCRYPT_ROUNDS).hash(prehashed)


def _verify_password(password: str, password_hash: str) -> bool:
    prehashed = hashlib.sha256(password.encode("utf-8")).hexdigest()
    try:
        return bcrypt.verify(prehashed, password_hash)
    except (ValueError, TypeError):
        return False


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# 用户不存在时也跑一次同代价的校验，抹平"邮箱未注册 vs 密码错误"的响应耗时差
DUMMY_BCRYPT_HASH = bcrypt.using(rounds=BCRYPT_ROUNDS).hash(
    hashlib.sha256(b"dummy-password-for-timing").hexdigest()
)


def _create_access_token(user_id: str) -> str:
    now = _utcnow()
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
        "iss": JWT_ISSUER,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """验签并校验 access token；无效/过期返回 None（不抛异常，中间件统一处理）。"""
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    return payload


def register_user(email: str, password: str, display_name: str) -> dict[str, Any]:
    """注册新用户；邮箱已存在时抛出带 code 的 ValueError。"""
    normalized_email = email.strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("邮箱格式不正确")
    if len(password) < 8:
        raise ValueError("密码至少需要 8 位")
    if len(password) > 256:
        raise ValueError("密码过长")

    now = _iso(_utcnow())
    user_id = f"user-{secrets.token_hex(8)}"
    password_hash = _hash_password(password)
    with get_connection() as connection:
        try:
            connection.execute(
                """
                INSERT INTO users (id, email, display_name, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, 'user', ?)
                """,
                (user_id, normalized_email, display_name.strip() or normalized_email, password_hash, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("该邮箱已注册") from None
    return {"id": user_id, "email": normalized_email}


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    """邮箱 + 密码校验；成功返回用户行 dict，失败返回 None。"""
    normalized_email = email.strip().lower()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, email, display_name, password_hash, role FROM users WHERE email = ?",
            (normalized_email,),
        ).fetchone()
    if row is None:
        # 仍做一次 dummy 哈希，抹平"用户不存在 vs 密码错误"的耗时差
        _verify_password(password, DUMMY_BCRYPT_HASH)
        return None
    if not _verify_password(password, row["password_hash"]):
        return None
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (_iso(_utcnow()), row["id"]),
        )
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"], "role": row["role"]}


def issue_refresh_token(user_id: str) -> str:
    """签发新的 refresh token（明文只返回一次，库中只存 SHA-256 摘要）。"""
    token = secrets.token_urlsafe(48)
    now = _utcnow()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"rt-{secrets.token_hex(8)}",
                user_id,
                _hash_refresh_token(token),
                _iso(now + REFRESH_TOKEN_TTL),
                _iso(now),
            ),
        )
    return token


def rotate_refresh_token(token: str) -> tuple[dict[str, Any], str] | None:
    """轮换 refresh token：旧 token 标记 revoked 并指向新 token；无效/过期/已吊销返回 None。

    检测到已吊销 token 被重放时，视为泄露，吊销该用户全部 refresh token（ theft-detection）。
    """
    token_hash = _hash_refresh_token(token)
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, user_id, expires_at, revoked_at
            FROM refresh_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        if row["revoked_at"] is not None:
            # 已吊销 token 再次出现：可能泄露，全端下线保平安
            connection.execute(
                "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (_iso(_utcnow()), row["user_id"]),
            )
            return None
        if row["expires_at"] <= _iso(_utcnow()):
            connection.execute(
                "UPDATE refresh_tokens SET revoked_at = ? WHERE id = ?",
                (_iso(_utcnow()), row["id"]),
            )
            return None

        user_row = connection.execute(
            "SELECT id, email, display_name, role FROM users WHERE id = ?",
            (row["user_id"],),
        ).fetchone()
        if user_row is None:
            return None

        new_token = secrets.token_urlsafe(48)
        now = _utcnow()
        connection.execute(
            "UPDATE refresh_tokens SET revoked_at = ?, replaced_by_token_hash = ? WHERE id = ?",
            (_iso(now), _hash_refresh_token(new_token), row["id"]),
        )
        connection.execute(
            """
            INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"rt-{secrets.token_hex(8)}",
                row["user_id"],
                _hash_refresh_token(new_token),
                _iso(now + REFRESH_TOKEN_TTL),
                _iso(now),
            ),
        )
    user = {
        "id": user_row["id"],
        "email": user_row["email"],
        "display_name": user_row["display_name"],
        "role": user_row["role"],
    }
    return user, new_token


def revoke_all_refresh_tokens(user_id: str) -> None:
    """登出：吊销该用户全部 refresh token。access token 自然过期（最长 30 分钟）。"""
    with get_connection() as connection:
        connection.execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (_iso(_utcnow()), user_id),
        )


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, email, display_name, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"], "role": row["role"]}


def issue_token_pair(user: dict[str, Any]) -> dict[str, Any]:
    """登录/注册/刷新成功后的统一出口：access + refresh + 用户信息。"""
    access_token = _create_access_token(user["id"])
    refresh_token = issue_refresh_token(user["id"])
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "role": user.get("role", "user"),
        },
    }
