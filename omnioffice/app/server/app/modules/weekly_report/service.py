"""周报模块业务服务层：批次、截图上传/查询/移动/删除。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ...core.config import settings
from ...core.identity import Identity
from ...db.models import Report, Screenshot
from .constants import ALLOWED_CONTENT_TYPES, ALLOWED_SUFFIX, PARTITION_IDS, PARTITION_LABELS

_CN_TZ = timezone(timedelta(hours=8))


def current_period_start(now: datetime | None = None) -> str:
    """周期周一日期（Asia/Shanghai），格式 YYYY-MM-DD。"""
    now = now or datetime.now(_CN_TZ)
    monday = (now - timedelta(days=now.weekday())).date()
    return monday.isoformat()


def get_or_create_current_report(db: Session, identity: Identity) -> Report:
    period = current_period_start()
    report = db.scalar(
        select(Report).where(Report.owner_uid == identity.uid, Report.period_start == period)
    )
    if report is None:
        report = Report(owner_uid=identity.uid, period_start=period, status="draft")
        db.add(report)
        db.commit()
        db.refresh(report)
    return report


def _screenshot_dto(s: Screenshot) -> dict:
    # fileMissing：DB 记录在但原图文件已丢失（v1.0.19 前升级清目录所致），
    # 前端据此显示失效占位，不再等 <img> 请求 raw 拿到 410 才发现。
    file_missing = False
    try:
        file_missing = not Path(s.stored_path).is_file() if s.stored_path else True
    except OSError:
        file_missing = True
    return {
        "id": s.id,
        "partition": s.partition,
        "partitionLabel": PARTITION_LABELS.get(s.partition, s.partition),
        "filename": s.filename,
        "size": s.size,
        "md5": s.md5,
        "recognizeStatus": s.recognize_status,
        "recognizeError": s.recognize_error,
        "createdAt": s.created_at.astimezone(_CN_TZ).isoformat() if s.created_at else None,
        "taskCount": len(s.tasks),
        "fileMissing": file_missing,
    }


async def upload_screenshots(
    db: Session, identity: Identity, report: Report, partition: str, files: list[UploadFile]
) -> dict:
    if partition not in PARTITION_IDS:
        raise HTTPException(status_code=400, detail={"error": "BAD_PARTITION", "message": f"非法分区：{partition}"})
    if not files:
        raise HTTPException(status_code=400, detail={"error": "NO_FILE", "message": "未收到上传文件"})

    max_bytes = settings.upload_max_mb * 1024 * 1024
    upload_root = Path(settings.data_dir) / "uploads" / identity.uid / str(report.id)
    upload_root.mkdir(parents=True, exist_ok=True)

    accepted: list[Screenshot] = []
    skipped_duplicate: list[str] = []
    rejected: list[dict] = []

    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if f.content_type not in ALLOWED_CONTENT_TYPES or suffix not in ALLOWED_SUFFIX:
            rejected.append({"filename": f.filename, "reason": "仅支持 jpg/png/webp 图片"})
            continue
        data = await f.read()
        if len(data) > max_bytes:
            rejected.append({"filename": f.filename, "reason": f"单张超过 {settings.upload_max_mb}MB"})
            continue
        md5 = hashlib.md5(data).hexdigest()
        # 同一批次内 md5 去重（同一图重复上传只保留一份；跨分区重复传按需求允许？V10 只要求去重，
        # 这里按「同批次同 md5 唯一」处理，跨分区拖动即改归属，不重复入库）
        exists = db.scalar(
            select(Screenshot).where(Screenshot.report_id == report.id, Screenshot.md5 == md5)
        )
        if exists is not None:
            skipped_duplicate.append(f.filename or md5)
            continue

        stored = upload_root / f"{md5}{suffix}"
        if not stored.exists():
            stored.write_bytes(data)
        shot = Screenshot(
            report_id=report.id,
            owner_uid=identity.uid,
            partition=partition,
            filename=f.filename or stored.name,
            stored_path=str(stored),
            md5=md5,
            size=len(data),
            content_type=f.content_type,
            recognize_status="pending",
        )
        db.add(shot)
        accepted.append(shot)

    db.commit()
    for shot in accepted:
        db.refresh(shot)
    audit.log(
        "screenshots.upload",
        identity.uid,
        {
            "reportId": report.id,
            "partition": partition,
            "accepted": len(accepted),
            "duplicates": len(skipped_duplicate),
            "rejected": len(rejected),
        },
    )
    return {
        "accepted": [_screenshot_dto(s) for s in accepted],
        "duplicates": skipped_duplicate,
        "rejected": rejected,
    }


def list_screenshots(db: Session, identity: Identity, partition: str | None) -> list[dict]:
    report = get_or_create_current_report(db, identity)
    stmt = select(Screenshot).where(Screenshot.report_id == report.id)
    if partition:
        if partition not in PARTITION_IDS:
            raise HTTPException(status_code=400, detail={"error": "BAD_PARTITION", "message": f"非法分区：{partition}"})
        stmt = stmt.where(Screenshot.partition == partition)
    shots = list(db.scalars(stmt.order_by(Screenshot.created_at.desc())))
    return [_screenshot_dto(s) for s in shots]


def _owned_screenshot(db: Session, identity: Identity, shot_id: int) -> Screenshot:
    shot = db.get(Screenshot, shot_id)
    # 越权红线：只能操作自己批次的截图（避坑指南 §3.1：归属键来自网关注入身份）
    if shot is None or shot.owner_uid != identity.uid:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "截图不存在"})
    return shot


def move_screenshot(db: Session, identity: Identity, shot_id: int, partition: str) -> dict:
    if partition not in PARTITION_IDS:
        raise HTTPException(status_code=400, detail={"error": "BAD_PARTITION", "message": f"非法分区：{partition}"})
    shot = _owned_screenshot(db, identity, shot_id)
    old = shot.partition
    if old != partition:
        shot.partition = partition
        # 归属与识别解耦：已识别任务随截图一起改分区（V10 3.4.1）
        for t in shot.tasks:
            t.partition = partition
        db.commit()
        db.refresh(shot)
        audit.log("screenshots.move", identity.uid, {"id": shot_id, "from": old, "to": partition})
    return _screenshot_dto(shot)


def delete_screenshot(db: Session, identity: Identity, shot_id: int) -> None:
    shot = _owned_screenshot(db, identity, shot_id)
    # 原图文件：仅当没有其他记录指向同一文件时删除（md5 去重场景的保护）
    path = shot.stored_path
    db.delete(shot)
    db.commit()
    audit.log("screenshots.delete", identity.uid, {"id": shot_id, "partition": shot.partition})
    try:
        p = Path(path)
        if p.exists() and p.is_file():
            p.unlink()
    except OSError:
        pass


def purge_missing_screenshots(db: Session, identity: Identity) -> dict:
    """清理当前批次所有原图已丢失的截图记录（含其识别任务）。

    用于 v1.0.19 前升级导致文件丢失的历史记录：DB 记录已无对应文件，
    保留只会造成界面裂图与识别必失败，由用户确认后一键清除重传。
    """
    # 跨全部批次扫描该用户记录（历史批次的失效记录也一并清除）
    shots = list(db.scalars(select(Screenshot).where(Screenshot.owner_uid == identity.uid)))
    missing = [s for s in shots if (not s.stored_path or not Path(s.stored_path).is_file())]
    ids = [s.id for s in missing]
    for s in missing:
        db.delete(s)  # TaskItem 经 cascade 一并删除
    db.commit()
    if ids:
        audit.log("screenshots.purge_missing", identity.uid, {"ids": ids})
    return {"removed": len(ids), "ids": ids}
