"""Storage abstraction: local folder in development, Supabase Storage (private bucket) in production."""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.security import create_file_token

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


class SupabaseStorage(Storage):
    def __init__(self, url: str, service_key: str, bucket: str):
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def _obj(self, path: str) -> str:
        return f"{self.base}/object/{self.bucket}/{quote(_safe(path))}"

    def save(self, path: str, data: bytes, content_type: str) -> str:
        r = httpx.post(
            self._obj(path),
            content=data,
            headers={**self.headers, "Content-Type": content_type, "x-upsert": "true"},
            timeout=30,
        )
        r.raise_for_status()
        return _safe(path)

    def read(self, path: str) -> bytes | None:
        r = httpx.get(self._obj(path), headers=self.headers, timeout=30)
        if r.status_code in (400, 404):
            return None
        r.raise_for_status()
        return r.content

    def delete(self, path: str) -> None:
        r = httpx.request(
            "DELETE",
            f"{self.base}/object/{self.bucket}",
            json={"prefixes": [_safe(path)]},
            headers=self.headers,
            timeout=30,
        )
        if r.status_code >= 400:
            log.warning("Supabase delete failed for a file: %s", r.status_code)

    def signed_url(self, path: str, seconds: int | None = None) -> str:
        s = get_settings()
        r = httpx.post(
            f"{self.base}/object/sign/{self.bucket}/{quote(_safe(path))}",
            json={"expiresIn": seconds or s.signed_url_seconds},
            headers=self.headers,
            timeout=30,
        )
        r.raise_for_status()
        signed = r.json().get("signedURL") or r.json().get("signedUrl")
        return f"{self.base}{signed}" if signed.startswith("/") else signed


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
