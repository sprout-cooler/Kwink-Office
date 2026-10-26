"""校对与编辑业务层（V10 3.8）。

职责：
- 任务 DTO（含置信度分级、警告、越界标记，原图对照所需 screenshotId）；
- 行内编辑：标题 / 开始时间 / 结束时间 / 归属星期 / 统计分类（手工覆盖锁定）；
- 跨分区移动单条任务（截图不动，只改归属，归属与识别解耦）；
- 删除与手工新增（screenshot_id 为空表示纯手工录入）；
- 工作汇总聚合（复用 summary.py 的纯规则）与未分类清单；
- 手工补充（重点问题 / 工作需求）；
- 低置信度卡点判定（<0.6 且未人工处理 → 阻断导出）。

时间字段约定：前端提交**原始文本**（用户可能在原图看到「周四 10:00」），
服务端统一走 dateparse.normalize_task 归一化 —— 与识别链路完全同一条路径，
保证「AI 抄录的值」与「人工敲的值」用同一套解析规则，不会出现两套口径。
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ...core.identity import Identity
from ...db.models import Report, Screenshot, TaskItem
from .constants import PARTITION_IDS, PARTITION_LABELS, time_required
from .dateparse import DateParseError, normalize_task, parse_date
from .summary import (
    CAT_UNCLASSIFIED,
    SUMMARY_ITEMS,
    TaskView,
    compute_summary,
)

# 置信度分级门槛（V10 3.8：≥0.8 采纳 / 0.6~0.8 标黄待确认 / <0.6 标红必填）
CONF_OK = 0.8
CONF_WARN = 0.6


def _period_date(period_start: str) -> str:
    """校验并归一化周期起始日。

    dateparse.normalize_task 的 period_start 形参收的是 YYYY-MM-DD 字符串
    （其内部自行 fromisoformat），这里只做提前校验，让非法周期值在编辑入口
    就报错，而不是伪装成「时间解析失败」。
    """
    try:
        date.fromisoformat(period_start)
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "BAD_PERIOD", "message": f"周报周期起始日非法：{period_start!r}"},
        ) from e
    return period_start


def _owned_task(db: Session, identity: Identity, task_id: int) -> TaskItem:
    """越权红线：只能改自己的任务（归属键来自网关注入身份，避坑指南 §3.1）。"""
    t = db.get(TaskItem, task_id)
    if t is None or t.owner_uid != identity.uid:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "任务不存在"})
    return t


def _apply_manual_customer(db: Session, identity: Identity, t: TaskItem, value: Any) -> None:
    """人工指定任务关联的客户。

    规则：
    - 传 null / 空 → **清空关联**（人工明确表示「这条不属于任何客户」）；
    - 传 id → 必须属于**当前账号**，否则 404（不泄露客户是否存在）；
    - 写入后 customer_match = manual —— 人工值优先级最高，
      后续重新识别时**不会**被 AI 的自动匹配覆盖。

    人工指定客户时，若该客户还没有来源，顺手填「周报关联」——
    这与自动路径同一规则（只填空不覆盖）。
    """
    from ..biz_dashboard import constants as biz_constants
    from ...db.models import BizCustomer

    extra = dict(t.extra or {})

    # 清空关联
    if value in (None, "", 0, "0"):
        extra.pop("customer_id", None)
        extra.pop("customer_name", None)
        extra.pop("customer_ambiguous_ids", None)
        extra["customer_match"] = "manual"
        t.extra = extra
        return

    try:
        cid = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail={"error": "BAD_CUSTOMER", "message": "客户参数不合法"},
        ) from None

    cust = db.get(BizCustomer, cid)
    # 越权与不存在返回同一个错误码 —— 不区分「存在但不属于你」与「根本不存在」
    if cust is None or cust.owner_uid != identity.uid:
        raise HTTPException(
            status_code=404, detail={"error": "NOT_FOUND", "message": "客户不存在"}
        )

    extra["customer_id"] = cust.id
    extra["customer_name"] = cust.name
    extra["customer_match"] = "manual"
    extra.pop("customer_ambiguous_ids", None)
    t.extra = extra

    # 来源只填空不覆盖
    if not cust.source:
        cust.source = biz_constants.CUSTOMER_SOURCE_AUTO


def task_dto(t: TaskItem) -> dict[str, Any]:
    """任务 DTO。前端据此渲染置信度样式、越界标记与原图对照入口。"""
    extra = t.extra or {}
    warnings: list[str] = list(extra.get("warnings") or [])
    if t.confidence < CONF_WARN:
        level = "danger"
    elif t.confidence < CONF_OK:
        level = "warning"
    else:
        level = "normal"
    return {
        "id": t.id,
        "screenshotId": t.screenshot_id,
        "filename": extra.get("filename", ""),
        "partition": t.partition,
        "partitionLabel": PARTITION_LABELS.get(t.partition, t.partition),
        "title": t.title,
        "startAt": t.start_at,
        "endAt": t.end_at,
        "weekday": t.weekday,
        "rawStatus": t.raw_status,
        "confidence": round(float(t.confidence or 0), 3),
        "confidenceLevel": level,
        "statCategory": t.stat_category,
        # 人工是否已确认低置信度任务（Card 点「已确认」后置 true）
        "reviewed": bool(extra.get("reviewed")),
        "manual": bool(t.screenshot_id is None),
        "outOfPeriod": bool(extra.get("out_of_period")),
        "warnings": warnings,
        "parseError": extra.get("parse_error", ""),
        # 原图里 AI 抄下来的原文，用于「人工输入 vs AI 识别」对照提示
        "rawStart": extra.get("start_raw", ""),
        "rawEnd": extra.get("end_raw", ""),
        # ---- 客户关联（周报 → 客户）----
        # customerName 是识别时的客户名原文（保留作为识别证据，即使客户改名也不变）；
        # customerId 是匹配到的客户 id（人工校对后可能是人工指定的）；
        # customerMatch 说明这行是怎么来的：matched/ambiguous/none/manual。
        "customerName": extra.get("customer_name", ""),
        "customerId": extra.get("customer_id"),
        "customerMatch": extra.get("customer_match", ""),
        "customerAmbiguousIds": list(extra.get("customer_ambiguous_ids") or []),
    }


def list_tasks(
    db: Session, identity: Identity, partition: str | None, report: Report
) -> list[dict[str, Any]]:
    if partition and partition not in PARTITION_IDS:
        raise HTTPException(status_code=400, detail={"error": "BAD_PARTITION", "message": f"非法分区：{partition}"})
    shot_ids = select(Screenshot.id).where(Screenshot.report_id == report.id).scalar_subquery()
    stmt = select(TaskItem).where(
        TaskItem.owner_uid == identity.uid,
        # 手工新增的任务 screenshot_id 为 NULL，需显式纳入
        (TaskItem.screenshot_id.in_(shot_ids)) | (TaskItem.screenshot_id.is_(None)),
    )
    if partition:
        stmt = stmt.where(TaskItem.partition == partition)
    tasks = list(db.scalars(stmt.order_by(TaskItem.weekday, TaskItem.start_at, TaskItem.id)))
    # 补文件名（供前端显示「来自哪张截图」）
    shots = {
        s.id: s.filename
        for s in db.scalars(select(Screenshot).where(Screenshot.report_id == report.id))
    }
    out = []
    for t in tasks:
        d = task_dto(t)
        if t.screenshot_id and t.screenshot_id in shots:
            d["filename"] = shots[t.screenshot_id]
        out.append(d)
    return out


def _renormalize(
    task: TaskItem, start_raw: str, end_raw: str, period_start: str, is_manual: bool
) -> None:
    """用与识别链路相同的解析规则重算时间字段。"""
    extra = dict(task.extra or {})
    warnings: list[str] = [w for w in (extra.get("warnings") or []) if w != "DATE_PARSE_FAILED"]
    extra["warnings"] = warnings

    if not start_raw.strip():
        task.start_at = ""
        task.end_at = ""
        task.weekday = 0
        warnings.append("START_TIME_MISSING")
        extra.pop("parse_error", None)
        extra.pop("start_raw", None)
        extra.pop("end_raw", None)
        task.extra = extra
        return

    try:
        norm = normalize_task(start_raw, end_raw, period_start=_period_date(period_start))
        task.start_at = norm.start_at
        task.end_at = norm.end_at
        task.weekday = norm.weekday
        warnings.extend(norm.warnings)
        extra["out_of_period"] = norm.out_of_period
        # 人工修正后清除原 AI 原文，标记为已定稿
        extra["start_raw"] = start_raw
        extra["end_raw"] = end_raw
        extra.pop("parse_error", None)
    except DateParseError as e:
        # 「只有日期没有时刻」是截图里极常见的写法（如工单只显示 261012），
        # 用户在校对时往往只想补日期、不想凭空编时刻。
        # 这里退一步：把时刻补成 00:00 重新归一化，保留日期语义，
        # 并打 DATE_ONLY 标记让界面明示「时刻待补」，而不是整条判为解析失败。
        date_only = _parse_date_only(start_raw, period_start)
        if date_only is not None:
            d, out_of_period = date_only
            dt = datetime.combine(d, time.min)
            task.start_at = dt.isoformat(timespec="minutes")
            task.end_at = task.start_at
            task.weekday = d.isoweekday()
            extra["out_of_period"] = out_of_period
            extra["start_raw"] = start_raw
            extra["end_raw"] = end_raw
            warnings.append("DATE_ONLY")
            warnings.append("TIME_MISSING")
            extra.pop("parse_error", None)
        else:
            # 真解析不了：保留原文、标红必填，绝不猜测（V10 3.5）
            task.start_at = ""
            task.end_at = ""
            task.weekday = 0
            warnings.append("DATE_PARSE_FAILED")
            extra["parse_error"] = str(e)
            extra["start_raw"] = start_raw
            extra["end_raw"] = end_raw
            extra["out_of_period"] = False
    task.extra = extra


def _parse_date_only(start_raw: str, period_start: str) -> tuple[date, bool] | None:
    """仅日期文本兜底：把时刻补成 00:00 后归一化。

    返回 (日期, 是否越界)；不适合兜底时返回 None。
    条件：原文**确实解析不出任何时刻**。若文本本就带时刻却解析失败，
    说明是真的格式不认识，交由上层标记 DATE_PARSE_FAILED（不猜）。
    本函数不修改 task，由调用方统一写 extra，避免字典覆盖丢字段。
    """
    if re.search(r"\d{1,2}\s*[:：]\s*\d{2}", start_raw):
        return None  # 原文有时刻却失败 → 不兜底
    try:
        ps = date.fromisoformat(period_start)
        d = parse_date(start_raw, ps)
    except Exception:
        return None
    return d, not (ps <= d <= ps + timedelta(days=6))


def update_task(
    db: Session,
    identity: Identity,
    task_id: int,
    patch: dict[str, Any],
    report: Report,
) -> dict[str, Any]:
    """行内编辑任务。只接受白名单字段，**时间字段收原文**再走归一化。"""
    t = _owned_task(db, identity, task_id)
    before = {
        "title": t.title,
        "start": t.start_at,
        "end": t.end_at,
        "weekday": t.weekday,
        "partition": t.partition,
        "category": t.stat_category,
    }

    if "title" in patch:
        title = str(patch["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail={"error": "EMPTY_TITLE", "message": "任务标题不能为空"})
        t.title = title[:500]

    time_changed = "startTime" in patch or "endTime" in patch
    if time_changed:
        start_raw = str(patch.get("startTime") or "").strip()
        end_raw = str(patch.get("endTime") or "").strip()
        _renormalize(t, start_raw, end_raw, report.period_start, is_manual=t.screenshot_id is None)

    # 人工指定归属星期：直接改（不再回推时间，V10 允许用户以任务管理器为准）
    if "weekday" in patch and patch["weekday"] is not None:
        wd = int(patch["weekday"])
        if wd < 0 or wd > 7:
            raise HTTPException(status_code=400, detail={"error": "BAD_WEEKDAY", "message": "归属星期需在 0~7 之间"})
        t.weekday = wd

    if "partition" in patch and patch["partition"]:
        p = str(patch["partition"])
        if p not in PARTITION_IDS:
            raise HTTPException(status_code=400, detail={"error": "BAD_PARTITION", "message": f"非法分区：{p}"})
        t.partition = p

    # 手工归类（未分类清单）：写入后即锁定，自动统计不再覆盖
    if "statCategory" in patch:
        cat = str(patch["statCategory"] or "")
        from .summary import KEYWORDS, _PARTITION_CATEGORY

        allowed = set(KEYWORDS) | set(_PARTITION_CATEGORY) | {CAT_UNCLASSIFIED}
        if cat and cat not in allowed:
            raise HTTPException(status_code=400, detail={"error": "BAD_CATEGORY", "message": f"非法统计分类：{cat}"})
        t.stat_category = cat or CAT_UNCLASSIFIED
        extra = dict(t.extra or {})
        extra["manual_category"] = cat or None
        t.extra = extra

    # 「已确认」标记：低置信度任务人工核对后放行
    if "reviewed" in patch:
        extra = dict(t.extra or {})
        extra["reviewed"] = bool(patch["reviewed"])
        t.extra = extra

    # 人工指定客户（人工值优先级最高，永不被自动识别覆盖）
    if "customerId" in patch:
        _apply_manual_customer(db, identity, t, patch.get("customerId"))

    db.commit()
    db.refresh(t)
    audit.log(
        "task.update",
        identity.uid,
        {"id": task_id, "before": before, "after": {"title": t.title, "weekday": t.weekday,
                                                  "partition": t.partition, "category": t.stat_category}},
    )
    return task_dto(t)


def create_task(
    db: Session, identity: Identity, body: dict[str, Any], report: Report
) -> dict[str, Any]:
    """手工新增任务（V10 3.8：识别漏掉的工作由用户补录）。"""
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail={"error": "EMPTY_TITLE", "message": "任务标题不能为空"})
    partition = str(body.get("partition") or "offline_done")
    if partition not in PARTITION_IDS:
        raise HTTPException(status_code=400, detail={"error": "BAD_PARTITION", "message": f"非法分区：{partition}"})

    # 手工任务也要落一个批次内，保证批次范围查询能取到（截图为 NULL 的占位记录）
    placeholder = db.scalar(
        select(Screenshot).where(Screenshot.report_id == report.id, Screenshot.filename == "__manual__")
    )
    if placeholder is None:
        placeholder = Screenshot(
            report_id=report.id,
            owner_uid=identity.uid,
            partition=partition,
            filename="__manual__",
            stored_path="",
            md5="__manual__",
            size=0,
            content_type="text/plain",
            recognize_status="done",
        )
        db.add(placeholder)
        db.flush()
    else:
        placeholder.partition = partition

    task = TaskItem(
        screenshot_id=placeholder.id,
        owner_uid=identity.uid,
        partition=partition,
        title=title[:500],
        start_at="",
        end_at="",
        raw_status=str(body.get("status") or "手工录入"),
        confidence=1.0,  # 人工录入视为可信
        weekday=0,
        stat_category=CAT_UNCLASSIFIED,
        extra={"reviewed": True, "manual": True, "warnings": []},
    )
    db.add(task)
    db.flush()
    _renormalize(
        task,
        str(body.get("startTime") or "").strip(),
        str(body.get("endTime") or "").strip(),
        report.period_start,
        is_manual=True,
    )
    db.commit()
    db.refresh(task)
    audit.log("task.create", identity.uid, {"id": task.id, "partition": partition})
    d = task_dto(task)
    d["filename"] = ""
    return d


def delete_task(db: Session, identity: Identity, task_id: int) -> None:
    t = _owned_task(db, identity, task_id)
    db.delete(t)
    db.commit()
    audit.log("task.delete", identity.uid, {"id": task_id})


def move_task_to_shot(db: Session, identity: Identity, task_id: int, shot_id: int, report: Report) -> dict:
    """把某条任务移到另一张截图下（跨截图纠错：某张图识别出的任务实际来自另一张）。"""
    t = _owned_task(db, identity, task_id)
    shot = db.get(Screenshot, shot_id)
    if shot is None or shot.owner_uid != identity.uid or shot.report_id != report.id:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "截图不存在"})
    if shot.filename == "__manual__":
        raise HTTPException(status_code=400, detail={"error": "BAD_TARGET", "message": "不能挂到手工占位截图下"})
    t.screenshot_id = shot.id
    t.partition = shot.partition
    db.commit()
    db.refresh(t)
    audit.log("task.move_to_shot", identity.uid, {"taskId": task_id, "shotId": shot_id})
    return task_dto(t)


# ---------------------------------------------------------------- 工作汇总


def summary_of(db: Session, identity: Identity, report: Report) -> dict[str, Any]:
    """工作汇总：四项统计 + 未分类清单。"""
    shot_ids = select(Screenshot.id).where(Screenshot.report_id == report.id).scalar_subquery()
    tasks = list(
        db.scalars(
            select(TaskItem).where(
                TaskItem.owner_uid == identity.uid,
                (TaskItem.screenshot_id.in_(shot_ids)) | (TaskItem.screenshot_id.is_(None)),
            )
        )
    )
    views = [
        TaskView(
            id=t.id,
            partition=t.partition,
            title=t.title,
            # 手工归类写入 stat_category；仅当它是有效分类时才视为锁定，
            # 避免「重新归类为未分类」被旧值误当覆盖。
            manual_category=(t.stat_category or None) if (t.extra or {}).get("manual_category") else None,
        )
        for t in tasks
    ]
    result = compute_summary(views)

    # 未分类清单以 compute_summary 的判定结果为唯一口径。
    # 不能用 `stat_category == unclassified` 过滤 —— 该列在识别写入时是模型默认值，
    # 自动分类成功的任务在库里同样残留 unclassified，会导致清单里混进已归类的任务。
    unclassified_ids = set(result.unclassified)
    unclassified_items = [task_dto(t) for t in tasks if t.id in unclassified_ids]
    # 线上售后的真实口径是企微会话量（一周小结截图），与任务条数不同，单独带出
    from .wechat_metrics import get_summary

    wechat = get_summary(db, report.id)
    return {
        "items": [
            {"category": cat, "label": label, "count": result.counts.get(cat, 0)}
            for cat, label in SUMMARY_ITEMS
        ],
        "counts": result.counts,
        "offlineTotal": result.counts.get("offline", 0),
        "planTotal": result.counts.get("plan", 0),
        "total": result.total,
        "unclassifiedIds": result.unclassified,
        "unclassifiedItems": unclassified_items,
        "wechatSessions": wechat["sessions"],
        "wechatMinutes": wechat["minutes"],
        "wechatLatestTime": wechat["latestTime"],
        "wechatPeriodText": wechat["periodText"],
        "wechatSource": wechat["source"],
    }


# ---------------------------------------------------------------- 手工补充

MANUAL_FIELDS = ("issues", "demands")


def get_manual(db: Session, identity: Identity, report: Report) -> dict[str, Any]:
    """重点问题（模板 19-20 行）/ 工作需求（21-22 行）文本。"""
    from ...db.models import Setting

    stored = {}
    for row in db.scalars(select(Setting).where(Setting.key.like(f"manual.{report.id}.%"))):
        stored[row.key.rsplit(".", 1)[-1]] = row.value
    return {k: stored.get(k, "") for k in MANUAL_FIELDS}


def save_manual(
    db: Session, identity: Identity, report: Report, body: dict[str, Any]
) -> dict[str, Any]:
    from ...db.models import Setting

    changed: list[str] = []
    for key in MANUAL_FIELDS:
        if key not in body:
            continue
        val = str(body[key] or "").strip()
        if len(val) > 4000:
            raise HTTPException(status_code=400, detail={"error": "TOO_LONG", "message": f"{key} 内容过长（上限 4000 字）"})
        setting_key = f"manual.{report.id}.{key}"
        row = db.scalar(select(Setting).where(Setting.key == setting_key))
        if row is None:
            db.add(Setting(key=setting_key, value=val))
        else:
            row.value = val
        changed.append(key)
    db.commit()
    audit.log("manual.save", identity.uid, {"reportId": report.id, "fields": changed})
    return get_manual(db, identity, report)


# ---------------------------------------------------------------- 导出卡点


def export_readiness(db: Session, identity: Identity, report: Report) -> dict[str, Any]:
    """导出前卡点检查（V10 3.8：低置信度必须人工处理后才允许导出）。

    时间类阻断**只对「时间必填」分区生效**（见 constants.time_required）：
    线上售后是会话量汇总、下周计划尚未发生，两者截图上本就没有逐条时刻，
    强行要求填写等于逼用户编造数据。
    无时间的任务分两类去向：
      - 必填分区 → 阻断（必须补时间，否则进不了星期块明细）；
      - 非必填分区 → 不阻断，但如实告知「将只计入汇总数量、不进星期块明细」，
        避免用户以为导出的表把内容吞了。
    """
    tasks = list_tasks(db, identity, None, report)
    required = [t for t in tasks if time_required(t["partition"])]
    optional = [t for t in tasks if not time_required(t["partition"])]

    blocked = [
        t for t in tasks
        if t["confidenceLevel"] != "normal" and not t["reviewed"]
    ]
    # 时间类阻断只看必填分区
    pending_time = [t for t in required if "DATE_PARSE_FAILED" in t["warnings"]]
    out_of_period = [t for t in required if t["outOfPeriod"] and not t["reviewed"]]
    no_title = [t for t in tasks if not t["title"].strip()]
    # 未分类以汇总判定为准（与 summary_of 同口径），不用 stat_category 列
    unclassified_n = summary_of(db, identity, report)["counts"].get(CAT_UNCLASSIFIED, 0)

    reasons: list[dict[str, Any]] = []
    notices: list[dict[str, Any]] = []
    if pending_time:
        reasons.append({
            "code": "TIME_PARSE_FAILED",
            "label": "时间无法解析",
            "count": len(pending_time),
            "hint": "这些任务的时间无法自动识别，请在「识别校对」中手动填写后再导出",
        })
    if blocked:
        reasons.append({
            "code": "LOW_CONFIDENCE",
            "label": "低置信度未确认",
            "count": len(blocked),
            "hint": "置信度低于 80% 的任务需人工核对并点「已确认」后才能导出",
        })
    if out_of_period:
        reasons.append({
            "code": "OUT_OF_PERIOD",
            "label": "越界任务待确认",
            "count": len(out_of_period),
            "hint": "任务时间落在本周报周期之外，请确认归属周次后再导出",
        })
    if no_title:
        reasons.append({
            "code": "EMPTY_TITLE",
            "label": "标题为空",
            "count": len(no_title),
            "hint": "存在标题为空的任务，请补充或删除",
        })

    # ---- 非阻断提示（告知去向，但不拦住导出）----
    no_time_optional = [t for t in optional if not (t["startAt"] or "").strip()]
    if no_time_optional:
        notices.append({
            "code": "TIME_OPTIONAL",
            "label": "线上售后/下周计划无时间",
            "count": len(no_time_optional),
            "hint": "这些条目按周汇总或尚未发生，无需时间；将正常计入工作汇总数量，"
                    "但不写入星期块明细",
        })
    dropped = [t for t in required if not (t["startAt"] or "").strip()]
    if dropped:
        notices.append({
            "code": "TIME_MISSING_DETAIL",
            "label": "本周线下工作无时间",
            "count": len(dropped),
            "hint": "这些条目会计入汇总数量，但不会出现在星期块明细里；"
                    "如需按天罗列请补填时间",
        })

    return {
        "ready": len(reasons) == 0,
        "reasons": reasons,
        "notices": notices,
        # 未分类不阻断导出（可导出后在模板里留空），但要提示
        "unclassified": unclassified_n,
        "taskCount": len(tasks),
    }
