import json

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.deps import Scope
from app.services.audit import audit
from app.services.excel import (
    IMPORT_FIELDS,
    XLSX_MIME,
    autosave_excel,
    autosave_path,
    build_export,
    build_template,
    import_rows,
    parse_rows,
    preview_dict,
    read_sheet,
    suggest_mapping,
)
from app.services.storage import get_storage
from app.utils.formatting import today_ist

router = APIRouter(prefix="/api/excel", tags=["excel"])
MAX_XLSX = 5 * 1024 * 1024


def _xlsx_response(data: bytes, filename: str) -> Response:
    return Response(data, media_type=XLSX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export")
def export(scope: Scope):
    data = build_export(scope.db, scope.owner)
    return _xlsx_response(data, f"rent-data-{today_ist():%d-%b-%Y}.xlsx")


@router.get("/template")
def template(scope: Scope):
    return _xlsx_response(build_template(), "tenant-import-template.xlsx")


@router.get("/latest")
def latest_saved(scope: Scope):
    path = autosave_path(scope.owner_id)
    storage = get_storage()
    if storage.read(path) is None:
        autosave_excel(scope.owner_id)
    return {"url": storage.signed_url(path), "expires_in": 300}


async def _load(file: UploadFile) -> tuple[list[str], list[list]]:
    data = await file.read(MAX_XLSX + 1)
    if len(data) > MAX_XLSX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be 5 MB or smaller")
    if not data.startswith(b"PK"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload an .xlsx Excel file")
    try:
        headers, rows = read_sheet(data)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not read this Excel file") from e
    if not headers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The first sheet is empty")
    if len(rows) > 2000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Import at most 2000 rows at a time")
    return headers, rows


def _mapping(raw: str | None, headers: list[str]) -> dict:
    if not raw:
        return suggest_mapping(headers)
    try:
        m = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid column mapping") from e
    return {k: (v if v in headers else None) for k, v in m.items() if k in IMPORT_FIELDS}


@router.post("/import/preview")
async def import_preview(scope: Scope, file: UploadFile = File(...), mapping: str | None = Form(None)):
    headers, rows = await _load(file)
    m = _mapping(mapping, headers)
    recs = parse_rows(headers, rows, m)
    return {
        "headers": headers,
        "fields": {k: {"label": f["label"], "required": f["required"]} for k, f in IMPORT_FIELDS.items()},
        "mapping": m,
        "rows": [preview_dict(r) for r in recs],
        "valid_count": sum(1 for r in recs if not r["errors"]),
        "error_count": sum(1 for r in recs if r["errors"]),
    }


@router.post("/import/commit")
async def import_commit(bg: BackgroundTasks, scope: Scope, file: UploadFile = File(...),
                        mapping: str | None = Form(None)):
    headers, rows = await _load(file)
    recs = parse_rows(headers, rows, _mapping(mapping, headers))
    n = import_rows(scope.db, scope.owner, recs)
    audit(scope.db, scope.owner_id, "create", "import", None, {"imported": n, "skipped": len(recs) - n})
    scope.db.commit()
    bg.add_task(autosave_excel, scope.owner_id)
    return {"imported": n, "skipped": len(recs) - n}
