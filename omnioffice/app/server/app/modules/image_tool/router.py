"""图片处理模块路由：上传 / 图库 / 格式转换 / 拼接 / 压缩 / 编辑 / OCR。

异常契约（与全项目一致）：
    成功 → 业务 DTO
    失败 → {"detail": {"error": "<CODE>", "message": "<可行动中文提示>", ...}}

本文件是**唯一**把 ImageToolError 翻译成 HTTP 的地方（见 errors.ImageToolError.to_payload），
能力文件不需要知道 HTTP 的存在。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...core.identity import Identity, get_identity
from ...db.deps import get_db
from . import constants, service
from .errors import ImageToolError, asset_not_found

router = APIRouter()


def _require_identity(identity: Identity | None = Depends(get_identity)) -> Identity:
    if identity is None:
        raise HTTPException(
            status_code=401, detail={"error": "UNAUTHORIZED", "message": "未识别到网关身份"}
        )
    return identity


def _guard(fn, *args, **kwargs):
    """统一异常翻译：ImageToolError → 对应 HTTP 响应。

    刻意只捕获 ImageToolError，不吞其他异常 —— 未预期的异常必须冒泡到
    main.py 的全局处理器（那里会打完整堆栈 + 返回带 requestId 的可定位 500），
    在这里被宽泛捕获反而会掩盖真因。
    """
    try:
        return fn(*args, **kwargs)
    except ImageToolError as e:
        raise HTTPException(status_code=e.status, detail=e.to_payload()["detail"]) from None


@router.get("/capabilities")
def capabilities(identity: Identity = Depends(_require_identity)):
    """能力清单：前端格式下拉 / 质量滑块 / 拼接方式全由此驱动，新增格式前端零改动。"""
    return constants.capabilities()


@router.post("/images")
async def upload(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """上传图片原件（md5 去重，重复上传不重复占盘；文件丢失时重传即修复）。"""
    return await _guard(service.upload_images, db, identity, files)


@router.get("/images")
def list_images(
    kind: str | None = None,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """图库列表：上传原件与各能力的加工产物统一展示。"""
    return {"items": _guard(service.list_assets, db, identity, kind)}


@router.get("/images/{asset_id}/file")
def asset_file(
    asset_id: int,
    download: bool = False,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """回显 / 下载图片产物。

    归属校验在 service 内完成；文件已丢失返回 410 FILE_GONE
    （与周报原图回显同一语义，前端据此显示失效占位而非裂图）。
    """
    row = _guard(service.get_asset, db, identity, asset_id)
    if row.file_missing:
        raise HTTPException(
            status_code=410,
            detail={"error": "FILE_GONE", "message": f"图片文件已丢失（记录仍在）：{row.filename}", "id": asset_id},
        )
    return FileResponse(
        row.stored_path,
        media_type=row.content_type or "application/octet-stream",
        filename=row.filename if download else None,
    )


@router.delete("/images/{asset_id}")
def delete_image(
    asset_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """删除图片（先删记录、提交成功后才删文件；加工产物不受影响）。"""
    return _guard(service.delete_asset, db, identity, asset_id)


@router.post("/images/{asset_id}/convert")
def convert_image(
    asset_id: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """格式转换：{"targetFormat": "WEBP", "quality": 90}。

    注意路由顺序：本路由必须注册在 `/images/{asset_id}/file` 之后无冲突，
    但**不能**出现 `/images/{asset_id}` 这类单段路径吞掉子路径的情况
    （踩坑 K10：单段路由会抢先匹配并返回 422）。
    """
    return _guard(service.run_convert, db, identity, asset_id, body or {})


@router.post("/images/{asset_id}/compress")
def compress_image(
    asset_id: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """压缩：{"quality": 75} 或 {"targetBytes": 500000} 或两者组合（目标体积优先）。"""
    return _guard(service.run_compress, db, identity, asset_id, body or {})


@router.post("/images/{asset_id}/transform")
def transform_image(
    asset_id: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """编辑：{"op": "resize"|"rotate"|"crop"|"watermark", ...对应参数}。"""
    return _guard(service.run_transform, db, identity, asset_id, body or {})


@router.post("/stitch")
def stitch_images(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """拼接：{"assetIds": [1,2,3], "mode": "grid", "gap": 16, "columns": 2}。"""
    return _guard(service.run_stitch, db, identity, body or {})


@router.post("/images/{asset_id}/ocr")
def ocr_image(
    asset_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """OCR 文字提取：返回整图文本 + 每块文字的归一化位置（0~1000 千分比）。"""
    return _guard(service.run_ocr, db, identity, asset_id)
