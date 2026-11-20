"""
Read-only Visio (.vsdx) viewer API.

Mounted under /api/v1/visio. The uploaded file is parsed in memory into SVG
markup and returned; nothing is persisted and no file is written to disk.
"""
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from core.config import settings
from schemas.visio import VsdxParseResponse
from services.vsdx_service import VsdxError, VsdxLimits, parse_vsdx

router = APIRouter(prefix="/visio", tags=["visio"])

_CHUNK = 1024 * 1024


@router.post("/parse", response_model=VsdxParseResponse, summary="解析 VSDX 并返回只读 SVG")
async def parse_visio(file: UploadFile = File(..., description="Visio 文件（.vsdx）")):
    """Parse an uploaded .vsdx into one SVG per page. Read-only, no persistence."""
    file_name = Path(file.filename or "").name
    if not file_name.lower().endswith(".vsdx"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 .vsdx 文件",
        )

    limits = VsdxLimits.from_settings(settings)
    chunks = []
    total = 0
    try:
        while True:
            chunk = await file.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limits.max_file_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"文件超过 {limits.max_file_bytes // (1024 * 1024)} MB 上限",
                )
            chunks.append(chunk)
    finally:
        await file.close()

    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件为空",
        )

    try:
        result = await run_in_threadpool(
            parse_vsdx, b"".join(chunks), file_name, limits
        )
    except VsdxError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return VsdxParseResponse(**result)
