"""企微一周小结指标的持久化（线上售后数量的数据来源）。

业务背景（2026-10-13 明确）：
周报汇总区「线上售后数量」按模板口径填「企微会话量：N次」，N 来自企业微信
「一周小结」截图（如「处理了 413 次工作会话」），**不是**任务条数。

存储：复用 settings 表 key-value，零表结构迁移：
    wechat.{report_id}.sessions     会话次数（核心，缺失视为未识别）
    wechat.{report_id}.minutes      总时长分钟（选填，界面展示）
    wechat.{report_id}.latest_time  最晚时间原文（选填）
    wechat.{report_id}.period_text  小结周期原文（选填）
    wechat.{report_id}.source       ai / manual（人工修改后为 manual）
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import Setting

_KEY_PREFIX = "wechat"


def _key(report_id: int, field: str) -> str:
    return f"{_KEY_PREFIX}.{report_id}.{field}"


def save_summary(
    db: Session,
    report_id: int,
    sessions: int | None,
    *,
    minutes: int | None = None,
    latest_time: str = "",
    period_text: str = "",
    source: str = "ai",
) -> None:
    """写入/更新企微小结指标。sessions 为 None 时不覆盖已有会话量。"""
    fields: dict[str, str] = {}
    if sessions is not None:
        fields["sessions"] = str(int(sessions))
    if minutes is not None:
        fields["minutes"] = str(int(minutes))
    if latest_time:
        fields["latest_time"] = latest_time[:100]
    if period_text:
        fields["period_text"] = period_text[:50]
    if fields:
        fields["source"] = source
    for field, value in fields.items():
        _upsert(db, _key(report_id, field), value)
    db.commit()


def get_summary(db: Session, report_id: int) -> dict[str, Any]:
    """读取企微小结指标；从未识别/填写时 sessions 为 None。"""
    rows = {
        r.key: r.value
        for r in db.scalars(select(Setting).where(Setting.key.like(f"{_KEY_PREFIX}.{report_id}.%")))
    }

    def _int(field: str) -> int | None:
        v = rows.get(_key(report_id, field))
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "sessions": _int("sessions"),
        "minutes": _int("minutes"),
        "latestTime": rows.get(_key(report_id, "latest_time"), ""),
        "periodText": rows.get(_key(report_id, "period_text"), ""),
        "source": rows.get(_key(report_id, "source"), ""),
    }


def save_manual_sessions(db: Session, report_id: int, sessions: int) -> dict[str, Any]:
    """人工修正会话量（校对入口），锁定为 manual。"""
    save_summary(db, report_id, sessions, source="manual")
    return get_summary(db, report_id)


def _upsert(db: Session, key: str, value: str) -> None:
    row = db.scalar(select(Setting).where(Setting.key == key))
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def sessions_text(db: Session, report_id: int) -> str:
    """导出用：企微会话量单元格文本，口径与模板一致「企微会话量：413次」。

    未识别/未填写时回落「企微会话量：0次」（不留空、更不保留模板上周样例）。
    """
    n = get_summary(db, report_id)["sessions"]
    return f"企微会话量：{n if n is not None else 0}次"
