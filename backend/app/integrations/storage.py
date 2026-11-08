"""Storage abstraction: local folder in development, Supabase Storage (private bucket) in production."""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.security import create_file_token

log = logging.getLogger(__name__)


class Storage(ABC):
    @abstractmethod
    def save(self, path: str, data: bytes, content_type: str) -> str: ...

    @abstractmethod
    def read(self, path: str) -> bytes | None: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def signed_url(self, path: str, seconds: int | None = None) -> str: ...


def _safe(path: str) -> str:
    path = path.replace("\\", "/").lstrip("/")
    if ".." in path.split("/"):
        raise ValueError("invalid storage path")
    return path


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, path: str) -> Path:
        full = (self.root / _safe(path)).resolve()
        if self.root not in full.parents:
            raise ValueError("invalid storage path")
        return full

    def save(self, path: str, data: bytes, content_type: str) -> str:
        full = self._full(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        return _safe(path)

    def read(self, path: str) -> bytes | None:
        full = self._full(path)
        return full.read_bytes() if full.exists() else None

    def delete(self, path: str) -> None:
        full = self._full(path)
        if full.exists():
            os.remove(full)

    def signed_url(self, path: str, seconds: int | None = None) -> str:
        s = get_settings()
        token = create_file_token(_safe(path), seconds or s.signed_url_seconds)
        return f"/api/files/signed?token={token}"


def auth_headers(service_key: str) -> dict[str, str]:
    """Supabase auth headers.

    New secret keys (``sb_secret_...``) are not JWTs and must be sent only in the ``apikey``
    header. Legacy ``service_role`` keys are JWTs and are also sent as a Bearer token.
    """
    if service_key.startswith("sb_"):
        return {"apikey": service_key}
    return {"apikey": service_key, "Authorization": f"Bearer {service_key}"}


class StorageError(Exception):
    """File storage failed. The message is safe to log (never contains keys)."""


class SupabaseStorage(Storage):
    def __init__(self, url: str, service_key: str, bucket: str):
        url, service_key = url.strip(), service_key.strip()
        if not url or not service_key:
            raise StorageError("Supabase storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY)")
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket.strip()
        self.headers = auth_headers(service_key)

    def _obj(self, path: str) -> str:
        return f"{self.base}/object/{self.bucket}/{quote(_safe(path))}"

    def _call(self, action: str, method: str, url: str, **kw) -> httpx.Response:
        """One HTTP call to Supabase with clear, loggable errors."""
        try:
            return httpx.request(method, url, timeout=30, **kw)
        except (httpx.HTTPError, ValueError) as e:  # ValueError/LocalProtocolError: malformed header (bad key)
            raise StorageError(f"Supabase {action} failed: {e.__class__.__name__}") from e

    @staticmethod
    def _check(action: str, r: httpx.Response) -> None:
        if r.status_code >= 300:
            try:
                body = r.json()
                reason = body.get("message") or body.get("error") or ""
            except ValueError:
                reason = r.text[:120]
            raise StorageError(f"Supabase {action} failed ({r.status_code}): {reason}".strip())

    def save(self, path: str, data: bytes, content_type: str) -> str:
        r = self._call("upload", "POST", self._obj(path), content=data,
                       headers={**self.headers, "Content-Type": content_type, "x-upsert": "true"})
        self._check("upload", r)
        return _safe(path)

    def read(self, path: str) -> bytes | None:
        r = self._call("download", "GET", self._obj(path), headers=self.headers)
        if r.status_code in (400, 404):  # Supabase answers 400 "not_found" for missing objects
            return None
        self._check("download", r)
        return r.content

    def delete(self, path: str) -> None:
        try:
            r = self._call("delete", "DELETE", f"{self.base}/object/{self.bucket}",
                           json={"prefixes": [_safe(path)]}, headers=self.headers)
            if r.status_code >= 400:
                log.warning("Supabase delete failed for a file: %s", r.status_code)
        except StorageError as e:
            log.warning("%s", e)

    def signed_url(self, path: str, seconds: int | None = None) -> str:
        s = get_settings()
        r = self._call("signed link", "POST", f"{self.base}/object/sign/{self.bucket}/{quote(_safe(path))}",
                       json={"expiresIn": seconds or s.signed_url_seconds}, headers=self.headers)
        self._check("signed link", r)
        signed = r.json().get("signedURL") or r.json().get("signedUrl") or ""
        if not signed:
            raise StorageError("Supabase signed link failed: empty response")
        return f"{self.base}{signed}" if signed.startswith("/") else signed

    def check(self) -> str:
        """Startup self-test: can we reach the bucket? Returns a short status (no secrets)."""
        r = self._call("bucket check", "GET", f"{self.base}/bucket/{self.bucket}", headers=self.headers)
        self._check("bucket check", r)
        return "ok"


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_backend == "supabase":
            _storage = SupabaseStorage(s.supabase_url, s.supabase_service_key, s.supabase_bucket)
        else:
            _storage = LocalStorage(s.local_upload_dir)
    return _storage


def set_storage(storage: Storage | None) -> None:
    global _storage
    _storage = storage


def startup_report() -> list[str]:
    """Human-readable configuration checks logged at boot (never includes secrets)."""
    s = get_settings()
    lines = []
    try:
        storage = get_storage()
        if isinstance(storage, SupabaseStorage):
            lines.append(f"storage=supabase bucket={storage.bucket} -> {storage.check()}")
        else:
            lines.append("storage=local")
    except StorageError as e:
        lines.append(f"storage FAILED: {e}")
    except Exception as e:  # never block startup
        lines.append(f"storage FAILED: {e.__class__.__name__}")
    if s.email_backend == "brevo":
        ok = bool(s.brevo_api_key and (s.email_sender_address or s.system_gmail_address))
        lines.append(f"email=brevo configured={'yes' if ok else 'NO (set BREVO_API_KEY and sender)'}")
    else:
        lines.append(f"email={s.email_backend}")
    return lines
