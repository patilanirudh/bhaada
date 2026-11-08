import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

ALGO = "HS256"


# ---------- passwords ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode())
    except ValueError:
        return False


# ---------- JWT ----------
def _encode(payload: dict, expires: timedelta) -> str:
    now = datetime.now(timezone.utc)
    data = {**payload, "iat": now, "exp": now + expires}
    return jwt.encode(data, get_settings().jwt_secret, algorithm=ALGO)


def decode_token(token: str, expected_type: str) -> dict | None:
    try:
        data = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None
    if data.get("type") != expected_type:
        return None
    return data


def create_access_token(owner_id: int) -> str:
    s = get_settings()
    return _encode({"sub": str(owner_id), "type": "access"}, timedelta(minutes=s.access_token_minutes))


def create_refresh_token(owner_id: int, token_version: int) -> str:
    s = get_settings()
    return _encode(
        {"sub": str(owner_id), "type": "refresh", "tv": token_version, "jti": secrets.token_hex(8)},
        timedelta(days=s.refresh_token_days),
    )


def password_fingerprint(password_hash: str) -> str:
    """Short hash of the current password hash: makes reset tokens single-use."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_reset_token(owner_id: int, password_hash: str) -> str:
    return _encode(
        {"sub": str(owner_id), "type": "reset", "pwf": password_fingerprint(password_hash)},
        timedelta(hours=1),
    )


def create_file_token(path: str, seconds: int) -> str:
    return _encode({"type": "file", "path": path}, timedelta(seconds=seconds))


# ---------- Fernet ----------
_dev_key_cache: bytes | None = None


def _fernet() -> Fernet:
    global _dev_key_cache
    s = get_settings()
    if s.fernet_key:
        return Fernet(s.fernet_key.encode())
    if s.is_production:
        raise RuntimeError("FERNET_KEY must be set in production")
    # Development fallback: derive a stable key from the JWT secret.
    if _dev_key_cache is None:
        _dev_key_cache = base64.urlsafe_b64encode(hashlib.sha256(s.jwt_secret.encode()).digest())
    return Fernet(_dev_key_cache)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)  # 43 chars for 32 bytes
