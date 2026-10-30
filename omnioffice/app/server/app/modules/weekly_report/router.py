"""周报模块路由：截图上传/列表/跨分区移动/删除/原图回显/批次概览 + 识别触发与进度。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.identity import Identity, get_identity
from ...db.deps import get_db
from ...db.models import ExportArtifact, Screenshot, TaskItem, WeeklyPendingFile
from .constants import PARTITIONS
from . import export_service, merge_service, recognize_queue, review_service, service
from .recognize_queue import MODULE_ID
from .vlm import PROVIDER_PRESETS, build_recognizer

router = APIRouter()


def _require_identity(identity: Identity | None = Depends(get_identity)) -> Identity:
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "UNAUTHORIZED", "message": "未识别到网关身份"})
    return identity


@router.get("/state")
def state(db: Session = Depends(get_db), identity: Identity = Depends(_require_identity)):
    """当前批次概览：三分区截图数 + 识别状态计数（B 层角标/上传页统计用）。"""
    report = service.get_or_create_current_report(db, identity)
    rows = db.execute(
        select(Screenshot.partition, Screenshot.recognize_status, func.count(Screenshot.id))
        .where(Screenshot.report_id == report.id)
        .group_by(Screenshot.partition, Screenshot.recognize_status)
    ).all()
    partitions = {
        pid: {"id": pid, "label": label, "total": 0, "pending": 0, "processing": 0, "done": 0, "failed": 0}
        for pid, label in PARTITIONS
    }
    for partition, status, cnt in rows:
        if partition in partitions:
            partitions[partition]["total"] += cnt
            partitions[partition][status] = partitions[partition].get(status, 0) + cnt
    return {
        "periodStart": report.period_start,
        "partitions": list(partitions.values()),
        # 当前批次绑定的模板版本（空 = 未绑定，导出时回落最新版）；
        # 导出页据此初始化下拉，避免每次进页面默认跳到最新版造成误导出。
        "templateId": report.template_id,
    }


@router.post("/screenshots")
async def upload(
    partition: str = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    report = service.get_or_create_current_report(db, identity)
    return await service.upload_screenshots(db, identity, report, partition, files)


@router.get("/screenshots")
def list_screenshots(
    partition: str | None = None,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return {"items": service.list_screenshots(db, identity, partition)}


@router.patch("/screenshots/{shot_id}")
def move_screenshot(
    shot_id: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    partition = (body or {}).get("partition", "")
    return service.move_screenshot(db, identity, shot_id, partition)


@router.delete("/screenshots/{shot_id}")
def delete_screenshot(
    shot_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    service.delete_screenshot(db, identity, shot_id)
    return {"ok": True}


@router.post("/screenshots/purge-missing")
def purge_missing(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """一键清除原图已丢失的截图记录（历史升级遗留）。"""
    return service.purge_missing_screenshots(db, identity)


@router.get("/screenshots/{shot_id}/raw")
def screenshot_raw(
    shot_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """原图回显（缩略图、M3 校对时局部放大对照用）；归属校验后按库内路径返回。"""
    shot = service._owned_screenshot(db, identity, shot_id)
    p = Path(shot.stored_path)
    if not p.is_file():
        raise HTTPException(status_code=410, detail={"error": "FILE_GONE", "message": "原图文件已丢失"})
    return FileResponse(p, media_type=shot.content_type, filename=shot.filename)


@router.get("/tasks")
def list_tasks(
    partition: str | None = None,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """校对列表：归一化后的 start/end/weekday + 置信度分级 + 警告 + 越界标记。"""
    report = service.get_or_create_current_report(db, identity)
    return {"items": review_service.list_tasks(db, identity, partition, report)}


# ------------------------------------------------------- 校对与编辑（M3）


@router.patch("/tasks/{task_id}")
def patch_task(
    task_id: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """行内编辑：标题 / 开始时间 / 结束时间 / 归属星期 / 归属分区 / 手工归类 / 已确认。

    时间字段收**原始文本**，服务端用与识别链路相同的归一化规则重算，
    避免「AI 抄录」与「人工输入」出现两套解析口径。
    """
    report = service.get_or_create_current_report(db, identity)
    return {"item": review_service.update_task(db, identity, task_id, body or {}, report)}


@router.post("/tasks")
def create_task(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """手工新增任务（识别漏掉的工作由用户补录）。"""
    report = service.get_or_create_current_report(db, identity)
    return {"item": review_service.create_task(db, identity, body or {}, report)}


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    review_service.delete_task(db, identity, task_id)
    return {"ok": True}


@router.post("/tasks/{task_id}/move-to-shot")
def move_task_to_shot(
    task_id: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """跨截图纠错：任务挂到另一张截图下（AI 把两条截图混在一起时用）。"""
    shot_id = int((body or {}).get("screenshotId") or 0)
    if not shot_id:
        raise HTTPException(status_code=400, detail={"error": "MISSING_FIELD", "message": "缺少 screenshotId"})
    report = service.get_or_create_current_report(db, identity)
    return {"item": review_service.move_task_to_shot(db, identity, task_id, shot_id, report)}


# ------------------------------------------------------- 工作汇总 / 手工补充


@router.get("/summary")
def get_summary(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """工作汇总：四项统计 + 未分类清单（分区优先 + 关键词兜底）。"""
    report = service.get_or_create_current_report(db, identity)
    return review_service.summary_of(db, identity, report)


@router.get("/manual")
def get_manual(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """手工补充：重点问题（模板 19-20 行）/ 工作需求（21-22 行）。"""
    report = service.get_or_create_current_report(db, identity)
    return {"items": review_service.get_manual(db, identity, report)}


@router.put("/manual")
def save_manual(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    report = service.get_or_create_current_report(db, identity)
    return {"items": review_service.save_manual(db, identity, report, body or {})}


@router.get("/wechat-summary")
def get_wechat_summary(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """企微一周小结指标（线上售后数量=企微会话量的数据来源）。"""
    from . import wechat_metrics

    report = service.get_or_create_current_report(db, identity)
    return {"item": wechat_metrics.get_summary(db, report.id)}


@router.put("/wechat-summary")
def save_wechat_summary(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """人工修正企微会话量（识别不准时以人工值为准，随周报导出）。"""
    from . import wechat_metrics

    report = service.get_or_create_current_report(db, identity)
    try:
        sessions = int((body or {}).get("sessions"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail={"error": "BAD_SESSIONS", "message": "企微会话量需为非负整数"},
        ) from None
    if sessions < 0 or sessions > 1_000_000:
        raise HTTPException(
            status_code=400,
            detail={"error": "BAD_SESSIONS", "message": "企微会话量超出合理范围（0~1000000）"},
        )
    from ...core import audit

    result = wechat_metrics.save_manual_sessions(db, report.id, sessions)
    audit.log("wechat.manual_sessions", identity.uid, {"reportId": report.id, "sessions": sessions})
    return {"item": result}


@router.get("/export-readiness")
def export_readiness(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """导出前卡点：低置信度未确认 / 时间解析失败 / 越界未确认 / 标题为空 → 阻断。"""
    report = service.get_or_create_current_report(db, identity)
    return review_service.export_readiness(db, identity, report)


# ------------------------------------------------------- 模板版本与导出（M4）


@router.get("/templates")
def list_templates(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """该用户已上传的模板版本列表（按版本倒序），并标注当前批次绑定项。"""
    report = service.get_or_create_current_report(db, identity)
    items = export_service.list_templates(db, identity)
    bound_id = report.template_id
    for it in items:
        it["bound"] = (it["id"] == bound_id) if bound_id else False
    # 未显式绑定时，导出会回落最新版（列表第一项）——前端据此显示「默认使用最新版」
    return {"items": items, "boundTemplateId": bound_id, "fallbackLatestId": items[0]["id"] if items else None}


@router.post("/templates")
async def upload_template(
    file: UploadFile = File(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """上传模板：结构校验通过才入库（校验失败直接 400，不留半成品）。"""
    return await export_service.upload_template(db, identity, file, note)


@router.get("/templates/{template_id}")
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    t = export_service.get_template(db, identity, template_id)
    return {"template": {"id": t.id, "filename": t.filename, "version": t.version, "size": t.size}}


@router.get("/templates/{base_id}/diff/{target_id}")
def diff_templates(
    base_id: int,
    target_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """对比两个模板版本的单元格差异（base=参照版，target=对比版）。

    路径用 /diff/ 而非查询串，是为了避开与 GET /templates/{template_id} 的路由歧义
    （否则 "diff" 会被当模板 id 解析，直接 422）。
    """
    return export_service.diff_templates(db, identity, base_id, target_id)


@router.post("/templates/{template_id}/rollback")
def rollback_template(
    template_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """回滚到指定模板版本 —— 从旧版派生新版本（保留全部历史），并绑定到当前批次。"""
    report = service.get_or_create_current_report(db, identity)
    note = str((body or {}).get("note") or "")
    return export_service.rollback_template(db, identity, report, template_id, note)


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    export_service.delete_template(db, identity, template_id)
    return {"ok": True}


@router.put("/templates/bind")
def bind_template(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """把模板版本绑定到当前周报批次（历史周报用当时的模板，可追溯）。"""
    tid = int((body or {}).get("templateId") or 0)
    if not tid:
        raise HTTPException(status_code=400, detail={"error": "MISSING_FIELD", "message": "缺少 templateId"})
    report = service.get_or_create_current_report(db, identity)
    return export_service.bind_template(db, identity, report, tid)


@router.post("/export")
def trigger_export(
    body: dict | None = None,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """执行导出。body: {scope: content|full, dpi: int, renderPng: bool}。

    导出前会跑 export-readiness 卡点：低置信度未确认 / 时间解析失败等会 409 阻断。
    """
    body = body or {}
    report = service.get_or_create_current_report(db, identity)

    # 卡点：未就绪直接阻断（V10 3.8：低置信度必须人工处理后才允许导出）
    ready = review_service.export_readiness(db, identity, report)
    if not ready["ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "NOT_READY",
                "message": "还有未处理的问题，暂时不能导出",
                "reasons": ready["reasons"],
            },
        )

    scope = str(body.get("scope") or "content")
    dpi = int(body.get("dpi") or export_service.PNG_DPI)
    render_png = body.get("renderPng", True)

    result = export_service.export_weekly_report(
        db, identity, report, scope=scope, dpi=dpi, render_png=bool(render_png)
    )
    return {
        "artifactId": result.artifact_id,
        "name": Path(result.xlsx_path).name,
        "xlsx": Path(result.xlsx_path).name,
        "pngs": [Path(p).name for p in result.png_paths],
        "scope": result.scope,
        "status": result.status,
        "error": result.error,
    }


# ---------------------------------------------------------------- 待处理文件与合并（v1.0.35）


@router.get("/pending-file")
def get_pending_file(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """当前待处理文件的元信息（没有则 null）。"""
    return {"item": merge_service.get_pending_file_meta(db, identity)}


@router.post("/pending-file")
async def upload_pending_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """上传待处理文件（xlsx）。已存在则**替换**——全库只保留一份。"""
    data = await file.read()
    return merge_service.save_pending_file(db, identity, file.filename or "", data)


@router.delete("/pending-file")
def delete_pending_file(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return merge_service.delete_pending_file(db, identity)


@router.get("/pending-file/download")
def download_pending_file(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    p = merge_service.pending_file_path(db, identity)
    if p is None:
        raise HTTPException(
            status_code=404, detail={"error": "NO_PENDING_FILE", "message": "还没有待处理文件"}
        )
    row = db.scalar(
        select(WeeklyPendingFile).where(WeeklyPendingFile.owner_uid == identity.uid)
    )
    return FileResponse(
        p,
        filename=(row.file_name if row and row.file_name else p.name),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/pending-file/merge")
def merge_pending_file(
    body: dict | None = None,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """执行导出，并把生成的 xlsx 追加为待处理文件的一个新工作表，同时就地替换原文件。

    前置卡点：与导出一致的 export-readiness（低置信度未确认 / 时间解析失败会 409）。
    每次合并前自动备份原文件，失败自动回滚。
    """
    body = body or {}
    scope = str(body.get("scope") or "content")
    dpi = int(body.get("dpi") or export_service.PNG_DPI)
    render_png = bool(body.get("renderPng", True))

    report = service.get_or_create_current_report(db, identity)
    # 先确认有模板：没有模板时 export 会在填充阶段炸出 AttributeError，
    # 那时用户看到的是「服务内部错误」，而真实原因只是「还没上传模板」。
    if export_service.resolve_template(db, identity, report) is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "NO_TEMPLATE",
                "message": "还没有可用的周报模板，请先到「预览与导出」上传并绑定模板",
            },
        )
    ready = review_service.export_readiness(db, identity, report)
    if not ready["ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "NOT_READY",
                "message": "还有未处理的问题，暂时不能合并导出",
                "reasons": ready["reasons"],
            },
        )

    result = export_service.export_weekly_report(
        db, identity, report, scope=scope, dpi=dpi, render_png=render_png
    )
    merged = merge_service.merge_report_into_pending(
        db,
        identity,
        Path(result.xlsx_path).read_bytes(),
        # 工作表名用「周期 + 周报」（如 2026-10-26 周报）而不是产物文件名 ——
        # 后者往往超过 Excel 的 31 字符上限，会被截成「周报_devuser_2026-1...(2)」
        # 这种看不懂的名字。
        sheet_title_hint=f"{report.period_start} 周报",
        batch_id=report.id,
    )
    return {
        **merged,
        "artifactId": result.artifact_id,
        "xlsx": Path(result.xlsx_path).name,
        "pngs": [Path(p).name for p in result.png_paths],
        "status": result.status,
        "error": result.error,
    }


@router.get("/merge-history")
def merge_history(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """合并历史记录。"""
    return {"items": merge_service.list_merge_history(db, identity)}


@router.get("/export-history")
def export_history(
    q: str = "",
    templateId: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """全部导出历史（跨批次）：文件名 / 导出时间 / 所用模板及版本 / 下载与删除。"""
    return {"items": export_service.list_export_history(db, identity, q, templateId, limit)}


@router.patch("/artifacts/{artifact_id}")
def rename_artifact(
    artifact_id: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """重命名导出记录（同步改共享目录里的文件名）。"""
    name = str((body or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail={"error": "MISSING_FIELD", "message": "缺少 name"})
    return export_service.rename_artifact(db, identity, artifact_id, name)


@router.delete("/artifacts/{artifact_id}")
def delete_artifact(
    artifact_id: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """删除导出记录与其产物文件（文件已被外部清理时也能删掉记录）。"""
    return export_service.delete_artifact(db, identity, artifact_id)


@router.get("/artifacts")
def list_artifacts(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """本批次历史导出产物（成对展示：xlsx + png）。"""
    report = service.get_or_create_current_report(db, identity)
    return {"items": export_service.list_artifacts(db, identity, report)}


@router.get("/artifacts/{artifact_id}/file/{kind}")
def download_artifact(
    artifact_id: int,
    kind: str,
    index: int = 0,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """下载产物文件。kind ∈ {xlsx, png}；png 用 index 区分 _p1/_p2。"""
    art = db.get(ExportArtifact, artifact_id)
    if art is None or art.owner_uid != identity.uid:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "产物不存在"})

    if kind == "xlsx":
        path = Path(art.xlsx_path)
    elif kind == "png":
        paths = art.png_paths or []
        if not paths or index >= len(paths):
            raise HTTPException(status_code=404, detail={"error": "NO_PNG", "message": "该产物没有截图"})
        path = Path(paths[index])
    else:
        raise HTTPException(status_code=400, detail={"error": "BAD_KIND", "message": "kind 只能是 xlsx 或 png"})

    if not path.is_file():
        raise HTTPException(
            status_code=410,
            detail={"error": "FILE_GONE", "message": f"文件已被清理：{path.name}"},
        )
    return FileResponse(path, filename=path.name)


# ------------------------------------------------------- 识别触发与状态


@router.get("/recognize/status")
def recognize_status(db: Session = Depends(get_db), identity: Identity = Depends(_require_identity)):
    """识别配置与当前用户识别状态统计（前端角标/按钮可用性判断）。"""
    report = service.get_or_create_current_report(db, identity)
    rows = db.execute(
        select(Screenshot.recognize_status, func.count(Screenshot.id))
        .where(Screenshot.report_id == report.id)
        .group_by(Screenshot.recognize_status)
    ).all()
    counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    for status, cnt in rows:
        counts[status] = counts.get(status, 0) + cnt
    return {
        "configured": build_recognizer(MODULE_ID, owner=identity.uid) is not None,
        "providers": PROVIDER_PRESETS,
        "counts": counts,
        "total": sum(counts.values()),
    }


@router.post("/recognize")
def trigger_recognize(
    body: dict | None = None,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """触发识别：默认当前批次全部 pending；body.ids 可指定子集。幂等：processing/done 不重复入队。"""
    report = service.get_or_create_current_report(db, identity)
    stmt = select(Screenshot).where(
        Screenshot.report_id == report.id, Screenshot.recognize_status == "pending"
    )
    if body and isinstance(body.get("ids"), list) and body["ids"]:
        stmt = stmt.where(Screenshot.id.in_([int(i) for i in body["ids"]]))
    ids = [s.id for s in db.scalars(stmt)]
    enqueued = recognize_queue.enqueue(ids, identity.uid)
    return {"enqueued": enqueued, "pending": len(ids)}


@router.post("/recognize/retry-failed")
def retry_failed(db: Session = Depends(get_db), identity: Identity = Depends(_require_identity)):
    ids = recognize_queue.retry_failed(db, identity.uid)
    enqueued = recognize_queue.enqueue(ids, identity.uid)
    return {"enqueued": enqueued}


@router.websocket("/recognize/events")
async def recognize_events(ws: WebSocket):
    """识别进度推送（网关保留前缀转发到本路径）。

    注意：网关的 WebSocket 会话鉴权已完成（浏览器带 Cookie），此处信任连接来源，
    事件里只发进度不发业务数据本身，泄露面可控。
    """
    await ws.accept()
    q = recognize_queue.subscribe()
    try:
        # 主动心跳：网关空闲连接超时保护
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=25)
                await ws.send_text(json.dumps(event, ensure_ascii=False))
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        recognize_queue.unsubscribe(q)
