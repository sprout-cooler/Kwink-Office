"""图片处理编排层：上传、能力调用、记录登记、图库管理。

分层职责：
- 能力文件（convert/stitch/compress/transform/ocr）只管「怎么算」，
  不碰数据库、不碰身份 —— 因此可以脱离 Web 框架独立调用与复用；
- 本文件管「算什么、记给谁、文件落哪」—— 所有能力共用同一条登记链路，
  保证图库里既有上传原件也有加工产物，且都能下载/删除。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ...core.config import settings
from ...core.identity import Identity
from ...db.models import ImageAsset
from . import compress as compress_cap
from . import constants, convert, imaging, ocr, storage, stitch, transform
from .errors import ImageToolError, asset_not_found, file_gone

_CN_TZ = timezone(timedelta(hours=8))


# ------------------------------------------------------------------ 上传


async def upload_images(db: Session, identity: Identity, files: list[UploadFile]) -> dict:
    """上传图片原件。md5 去重：同一张图重复上传返回同一条记录，不重复占盘。"""
    if not files:
        raise ImageToolError("NO_IMAGE", "请先选择至少一张图片", 400)

    max_bytes = settings.upload_max_mb * 1024 * 1024
    accepted: list[dict] = []
    duplicates: list[str] = []
    rejected: list[dict] = []

    for f in files:
        name = Path(f.filename or "image").name
        data = await f.read()
        if not data:
            rejected.append({"filename": name, "reason": "文件为空"})
            continue
        if len(data) > max_bytes:
            rejected.append({"filename": name, "reason": f"单张超过 {settings.upload_max_mb}MB"})
            continue

        # 先落盘再探信息：落盘按内容 md5 命名 → 同图自动复用同一文件，
        # 避免「同名不同图」互相覆盖（周报 upload_screenshots 的历史坑）。
        fmt = imaging.guess_format(Path(name), fallback="")
        ext = storage.ext_for(fmt) if fmt else (Path(name).suffix.lstrip(".") or "png")
        stored, md5 = storage.write_bytes(identity.uid, data, ext)

        try:
            info = imaging.probe(stored)
        except ImageToolError as e:
            # 落盘后发现不是有效图片 → 立刻清掉刚写的文件，不留垃圾
            storage.remove_file(str(stored))
            rejected.append({"filename": name, "reason": e.message})
            continue

        existing = db.scalar(
            select(ImageAsset).where(
                ImageAsset.owner_uid == identity.uid,
                ImageAsset.md5 == md5,
                ImageAsset.kind == "original",
            )
        )
        if existing is not None:
            # 文件可能已被外部清理（记录在、文件没了）：重传即修复
            if not Path(existing.stored_path).is_file():
                existing.stored_path = str(stored)
                existing.size = len(data)
                db.commit()
                db.refresh(existing)
                accepted.append(_dto(existing))
                continue
            duplicates.append(name)
            continue

        row = ImageAsset(
            owner_uid=identity.uid,
            kind="original",
            filename=_safe_name(name),
            stored_path=str(stored),
            md5=md5,
            size=len(data),
            content_type=constants.MIME_BY_FORMAT.get(info.format, f.content_type or ""),
            width=info.width,
            height=info.height,
            source_id=0,
            meta={"format": info.format, "frames": info.frames, "hasAlpha": info.has_alpha},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        accepted.append(_dto(row))

    audit.log(
        "images.upload",
        identity.uid,
        {"accepted": len(accepted), "duplicates": len(duplicates), "rejected": len(rejected)},
    )
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


# ------------------------------------------------------------------ 能力编排


def run_convert(db: Session, identity: Identity, asset_id: int, body: dict) -> dict:
    row = _owned(db, identity, asset_id)
    src = storage.read_source(identity.uid, row.stored_path)
    fmt = str(body.get("targetFormat") or constants.Format.PNG).upper()
    quality = body.get("quality")
    result = convert.convert_file(src, fmt, quality=quality, drop_exif=bool(body.get("dropExif", True)))
    return _persist(db, identity, row, result, "convert", f"{Path(row.filename).stem}.{storage.ext_for(fmt)}")


def run_compress(db: Session, identity: Identity, asset_id: int, body: dict) -> dict:
    row = _owned(db, identity, asset_id)
    src = storage.read_source(identity.uid, row.stored_path)
    target_bytes = body.get("targetBytes")
    result = compress_cap.compress_file(
        src,
        target_format=body.get("targetFormat"),
        quality=body.get("quality"),
        target_bytes=int(target_bytes) if target_bytes else None,
        keep_format=bool(body.get("keepFormat", True)),
    )
    fmt = result.meta.get("targetFormat", constants.Format.JPEG)
    return _persist(db, identity, row, result, "compress", f"{Path(row.filename).stem}_compressed.{storage.ext_for(fmt)}")


def run_transform(db: Session, identity: Identity, asset_id: int, body: dict) -> dict:
    row = _owned(db, identity, asset_id)
    src = storage.read_source(identity.uid, row.stored_path)
    ratio = body.get("cropRatio")
    ratio_pair = None
    if isinstance(ratio, str) and ":" in ratio:
        a, _, b = ratio.partition(":")
        ratio_pair = (float(a or 1), float(b or 1))
    elif isinstance(ratio, (list, tuple)) and len(ratio) >= 2:
        ratio_pair = (float(ratio[0]), float(ratio[1]))

    result = transform.transform_file(
        src,
        op=str(body.get("op") or "resize"),
        target_format=body.get("targetFormat"),
        quality=body.get("quality"),
        width=body.get("width"),
        height=body.get("height"),
        angle=int(body.get("angle") or 0),
        crop_ratio=ratio_pair,
        text=str(body.get("text") or ""),
        position=str(body.get("position") or "bottom-right"),
        opacity=int(body.get("opacity") or 50),
        font_size=int(body.get("fontSize") or 0),
    )
    fmt = result.meta.get("targetFormat", constants.Format.PNG)
    suffix = "edited" if result.meta.get("op") == "watermark" else str(result.meta.get("op"))
    return _persist(db, identity, row, result, "transform", f"{Path(row.filename).stem}_{suffix}.{storage.ext_for(fmt)}")


def run_stitch(db: Session, identity: Identity, body: dict) -> dict:
    """拼接多张：入参是 asset id 列表，逐个做归属校验（防越权引用他人图片）。"""
    ids = body.get("assetIds")
    if not isinstance(ids, list) or len(ids) < 2:
        raise ImageToolError("NEED_TWO_IMAGES", "拼接至少需要选择 2 张图片", 400)
    if len(ids) > 100:
        raise ImageToolError("BAD_PARAM", "一次最多拼接 100 张图片", 400)

    rows = [_owned(db, identity, int(i)) for i in ids]
    srcs = [storage.read_source(identity.uid, r.stored_path) for r in rows]

    cols = body.get("columns")
    mode = str(body.get("mode") or "horizontal")
    if mode == "grid" and cols:
        # 指定列数时走网格的公开入口，其余方式交给 stitch 内部推导
        result = _stitch_with_columns(srcs, mode, body, int(cols))
    else:
        result = stitch.stitch_files(
            srcs,
            mode=mode,
            gap=int(body.get("gap") or 0),
            background=str(body.get("background") or "#ffffff"),
            target_format=str(body.get("targetFormat") or constants.Format.PNG),
            uniform=bool(body.get("uniform", False)),
            quality=body.get("quality"),
        )
    # 拼接是多图合成，source_id 记第一张（溯源用），完整清单在 meta.order
    name = f"stitched_{len(rows)}p.{storage.ext_for(result.info.format)}"
    return _persist(db, identity, rows[0], result, "stitch", name)


def _stitch_with_columns(srcs: list[Path], mode: str, body: dict, cols: int) -> stitch.StitchResult:
    """网格 + 指定列数（stitch.stitch_files 的默认列数推导在此被覆盖）。"""
    bg = stitch.parse_color(str(body.get("background") or "#ffffff"))
    gap = stitch.clamp_gap(body.get("gap") or 0)
    images: list[Any] = []
    try:
        for p in srcs:
            img = imaging.open_image(p)
            if getattr(img, "is_animated", False):
                raise ImageToolError(
                    "ANIMATED_NOT_SUPPORTED",
                    f"暂不支持拼接动图：{p.name}。请先转成静帧后再拼接。",
                    400,
                    filename=p.name,
                )
            images.append(img.convert("RGBA"))
        if body.get("uniform"):
            tw = max(i.width for i in images)
            th = max(i.height for i in images)
            images = [stitch.letterbox(i, tw, th, bg) for i in images]

        canvas, real_cols, rows = stitch.compose_grid(images, cols, gap, bg)
        stitch.guard_canvas(canvas)
        fmt = str(body.get("targetFormat") or constants.Format.PNG).upper()
        if fmt not in constants.OUTPUT_FORMATS:
            raise ImageToolError("UNSUPPORTED_FORMAT", f"不支持的输出格式：{body.get('targetFormat')}", 400)
        data = imaging.encode(canvas, fmt, body.get("quality"))
        info = imaging.ImageInfo(
            format=fmt, width=canvas.width, height=canvas.height, mode="RGBA", frames=1,
            has_alpha=fmt in constants.ALPHA_FORMATS, animated=False,
        )
        meta = {
            "mode": mode, "gap": gap, "background": body.get("background") or "#ffffff",
            "count": len(images), "columns": real_cols, "rows": rows,
            "uniform": bool(body.get("uniform")), "targetFormat": fmt,
            "order": [p.name for p in srcs],
        }
        return stitch.StitchResult(data=data, info=info, meta=meta)
    finally:
        for i in images:
            try:
                i.close()
            except Exception:  # noqa: BLE001
                pass


def run_ocr(db: Session, identity: Identity, asset_id: int) -> dict:
    """OCR：owner 显式传递 —— 省略会串用其他账号的 AI Key（踩坑 K9）。"""
    row = _owned(db, identity, asset_id)
    src = storage.read_source(identity.uid, row.stored_path)
    result = ocr.ocr_path(src, owner=identity.uid)
    # OCR 结果写回该图的 meta，便于前端列表直接展示而不必二次请求
    row.meta = {**(row.meta or {}), "ocr": {"text": result["text"][:2000], "blockCount": len(result["blocks"])}}
    db.commit()
    audit.log("images.ocr", identity.uid, {"id": asset_id, "blocks": len(result["blocks"])})
    return {"text": result["text"], "blocks": result["blocks"], "meta": result["meta"], "assetId": asset_id}


# ------------------------------------------------------------------ 图库


def list_assets(db: Session, identity: Identity, kind: str | None = None, limit: int = 100) -> list[dict]:
    stmt = select(ImageAsset).where(ImageAsset.owner_uid == identity.uid)
    if kind:
        stmt = stmt.where(ImageAsset.kind == kind)
    rows = list(db.scalars(stmt.order_by(ImageAsset.created_at.desc()).limit(min(limit, 500))))
    return [_dto(r) for r in rows]


def get_asset(db: Session, identity: Identity, asset_id: int) -> ImageAsset:
    return _owned(db, identity, asset_id)


def delete_asset(db: Session, identity: Identity, asset_id: int) -> dict:
    """删除图片：先删记录、提交成功后才删文件。

    顺序取自 v1.0.25 模板删除的教训 —— 反过来（先删文件）一旦删记录被拒，
    就会留下「文件没了、记录还在」的脏数据。
    文件删不掉只记日志不阻断（否则用户被永久卡死）。
    """
    row = _owned(db, identity, asset_id)
    path = row.stored_path
    md5 = row.md5
    db.delete(row)
    db.commit()
    removed = storage.remove_file(path)
    audit.log("images.delete", identity.uid, {"id": asset_id, "md5": md5[:8], "fileDeleted": removed})
    return {"ok": True, "id": asset_id, "fileDeleted": removed}


# ------------------------------------------------------------------ 内部


def _owned(db: Session, identity: Identity, asset_id: int) -> ImageAsset:
    """归属校验：不存在与不属于本人返回同一个 404（不泄露 id 是否存在）。"""
    row = db.get(ImageAsset, asset_id)
    if row is None or row.owner_uid != identity.uid:
        raise asset_not_found(asset_id)
    return row


def _persist(
    db: Session,
    identity: Identity,
    source: ImageAsset,
    result: Any,
    kind: str,
    filename: str,
) -> dict:
    """把能力产物落盘 + 登记（所有能力共用这条链路）。"""
    fmt = result.info.format
    stored, md5 = storage.write_bytes(identity.uid, result.data, storage.ext_for(fmt))
    row = ImageAsset(
        owner_uid=identity.uid,
        kind=kind,
        filename=_safe_name(filename),
        stored_path=str(stored),
        md5=md5,
        size=len(result.data),
        content_type=constants.MIME_BY_FORMAT.get(fmt, ""),
        width=result.info.width,
        height=result.info.height,
        source_id=source.id,
        meta={**result.meta, "info": result.info.as_dict()},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log(
        f"images.{kind}",
        identity.uid,
        {"sourceId": source.id, "id": row.id, "size": row.size, "width": row.width, "height": row.height},
    )
    return _dto(row)


def _dto(row: ImageAsset) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "filename": row.filename,
        "size": row.size,
        "md5": row.md5,
        "width": row.width,
        "height": row.height,
        "contentType": row.content_type,
        "sourceId": row.source_id,
        "meta": row.meta or {},
        "createdAt": row.created_at.astimezone(_CN_TZ).isoformat() if row.created_at else None,
        "fileMissing": row.file_missing,
    }


def _safe_name(name: str) -> str:
    """文件名净化：只取基名，去掉路径分隔符与控制字符，长度封顶 200。"""
    base = Path(str(name or "image")).name
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return (base or "image")[:200]
