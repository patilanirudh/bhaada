"""Serves local-storage files behind short-lived signed tokens (development / local storage only).
In production Supabase issues its own signed URLs and this route returns 404."""
from fastapi import APIRouter
from fastapi.responses import Response

from app.core.errors import Forbidden, NotFound
from app.core.security import decode_token
from app.integrations.storage import LocalStorage, get_storage
from app.utils.validators import sniff_mime

router = APIRouter(prefix="/api/files", tags=["files"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/signed")
def signed_file(token: str):
    data = decode_token(token, "file")
    if not data:
        raise Forbidden("Link expired")
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise NotFound("Not found")
    path = data["path"]
    content = storage.read(path)
    if content is None:
        raise NotFound("File not found")
    mime = sniff_mime(content) or (XLSX if path.endswith(".xlsx") else "application/octet-stream")
    return Response(content, media_type=mime, headers={
        "Content-Disposition": f'inline; filename="{path.rsplit("/", 1)[-1]}"',
        "Cache-Control": "private, max-age=60",
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
    })
