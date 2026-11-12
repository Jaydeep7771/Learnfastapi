"""Argon2 password hashing (pwdlib) + JWT access/refresh issuance (PyJWT)."""

import datetime as dt
import uuid
from typing import Any, Literal

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

# Argon2id is memory-hard: a stolen password table cannot be brute-forced on GPUs
# the way bcrypt/sha256 can. pwdlib embeds salt + params inside the hash string.
_password_hash = PasswordHash.recommended()

TokenType = Literal["access", "refresh"]


def hash_password(raw: str) -> str:
    return _password_hash.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _password_hash.verify(raw, hashed)


def _create_token(
    subject: str,
    token_type: TokenType,
    expires: dt.timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": uuid.uuid4().hex,
        **(extra or {}),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_access_token(subject: str, role: str) -> str:
    s = get_settings()
    return _create_token(
        subject,
        "access",
        dt.timedelta(minutes=s.access_token_expire_minutes),
        {"role": role},
    )


def create_refresh_token(subject: str) -> str:
    s = get_settings()
    return _create_token(
        subject, "refresh", dt.timedelta(days=s.refresh_token_expire_days)
    )


def decode_token(token: str, *, expect: TokenType) -> dict[str, Any]:
    """Raises jwt.PyJWTError on bad signature, expiry, or wrong token class."""
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    if payload.get("typ") != expect:
        raise jwt.InvalidTokenError(f"expected a {expect} token")
    return payload
