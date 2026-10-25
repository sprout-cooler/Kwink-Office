"""工作量聚合：**双口径**并存（用户明确要求二者都要）。

口径一：周报工时（只读）
    数据源是既有 task_items 表。start_at / end_at 是 ISO8601 字符串，
    时长 = end_at - start_at（小时）。
    ⚠️ 只读聚合，**绝不写 task_items** —— 那是周报批次语义，
    混入手填工时会破坏周报自身的统计口径与导出锚点。

口径二：独立工时台账
    数据源是 biz_time_entries，hours 直接存小时数。

两者合并后的大屏口径：
    - 按客户聚合：台账工时按 customer_id 归集；周报工时**无法归集到客户**
      （周报任务没有客户字段），因此周报工时只进入「未归属」桶，
      这是**如实呈现而非编造关联**；
    - 按日/周/月聚合：两口径都按日期落到对应时间桶。

纯函数设计：不碰数据库、不碰身份 —— service 层传入已取出的行对象即可调用，
便于独立验证与复用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable

# 时间桶粒度
GRAN_DAY = "day"
GRAN_WEEK = "week"
GRAN_MONTH = "month"


@dataclass
class WorkloadSlice:
    """一条工作量的最小视图（与 ORM 解耦）。"""

    source: str          # weekly（周报）| manual（台账）
    title: str = ""
    task_date: str = ""  # YYYY-MM-DD
    hours: float = 0.0
    customer_id: int = 0
    customer_name: str = ""
    category: str = ""
    ref_id: int = 0


@dataclass
class WorkloadBucket:
    """某个时间桶的聚合结果。"""

    key: str
    label: str
    hours: float = 0.0
    weekly_hours: float = 0.0
    manual_hours: float = 0.0
    count: int = 0
    by_customer: dict[int, float] = field(default_factory=dict)


def parse_iso(value: str) -> datetime | None:
    """解析 ISO8601 时间串；解析不了返回 None（不抛异常）。

    task_items.start_at / end_at 由 dateparse 模块归一化产出，
    形如 2026-10-15T10:00 或 2026-10-15T10:00:00。
    """
    if not value:
        return None
    text = value.strip().replace(" ", "T")
    if not text:
        return None
    # 补秒位：fromisoformat 在部分 3.9+ 变体上对 'YYYY-MM-DDTHH:MM' 可解析，
    # 但为兼容更严格的实现，统一补上秒。
    if len(text) == 16:
        text += ":00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    # 带 Z 后缀（UTC）
    if text.endswith("Z"):
        try:
            return datetime.fromisoformat(text[:-1])
        except ValueError:
            return None
    return None


def slice_hours(start: str, end: str) -> float:
    """由起止时间算时长（小时）。

    规则：
    - 缺任一端 → 0（无法计算时长，如跨天未标注结束的条目）；
    - 结束早于开始 → 0（识别噪声，不产出负时长）；
    - 超过 24 小时按 24 小时封顶（跨天连续任务单条按一天计，
      避免一条误识别把整月工时拉爆）。
    """
    s = parse_iso(start)
    e = parse_iso(end)
    if s is None or e is None:
        return 0.0
    delta = (e - s).total_seconds()
    if delta <= 0:
        return 0.0
    hours = delta / 3600.0
    return round(min(hours, 24.0), 2)


def bucket_key(day: str, granularity: str) -> str:
    """由 YYYY-MM-DD 计算时间桶键。

    - day   → 2026-10-15
    - week  → 2026-W42（ISO 周数，周一起算，与项目周报口径一致）
    - month → 2026-10
    """
    if not day:
        return ""
    try:
        d = datetime.strptime(day[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    if granularity == GRAN_MONTH:
        return f"{d.year:04d}-{d.month:02d}"
    if granularity == GRAN_WEEK:
        iso = d.isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    return d.strftime("%Y-%m-%d")


def bucket_label(key: str) -> str:
    """时间桶的可读标签（图表轴用）。"""
    if not key:
        return ""
    if "-W" in key:
        return f"{key[:4]}年第{key.split('W')[-1]}周"
    if len(key) == 7:
        return f"{key[:4]}年{int(key[5:7])}月"
    if len(key) >= 10:
        return f"{int(key[5:7])}月{int(key[8:10])}日"
    return key


def aggregate(
    slices: Iterable[WorkloadSlice],
    granularity: str = GRAN_MONTH,
) -> list[WorkloadBucket]:
    """按时间桶聚合工作量。"""
    buckets: dict[str, WorkloadBucket] = {}
    for s in slices:
        key = bucket_key(s.task_date, granularity)
        if not key:
            continue
        b = buckets.get(key)
        if b is None:
            b = WorkloadBucket(key=key, label=bucket_label(key))
            buckets[key] = b
        b.hours += s.hours
        b.count += 1
        if s.source == "weekly":
            b.weekly_hours += s.hours
        else:
            b.manual_hours += s.hours
        if s.customer_id:
            b.by_customer[s.customer_id] = b.by_customer.get(s.customer_id, 0.0) + s.hours
    result = sorted(buckets.values(), key=lambda b: b.key)
    for b in result:
        b.hours = round(b.hours, 2)
        b.weekly_hours = round(b.weekly_hours, 2)
        b.manual_hours = round(b.manual_hours, 2)
    return result


def by_customer(slices: Iterable[WorkloadSlice]) -> list[dict]:
    """按客户聚合工作量。

    customer_id == 0 的条目归入「未归属客户」桶 —— 周报工时必然落在这里
    （周报任务无客户字段），如实呈现而不是丢弃。
    """
    agg: dict[int, dict] = {}
    for s in slices:
        cid = s.customer_id or 0
        row = agg.get(cid)
        if row is None:
            row = {
                "customerId": cid,
                "customerName": s.customer_name or ("未归属客户" if cid == 0 else f"客户#{cid}"),
                "hours": 0.0,
                "weeklyHours": 0.0,
                "manualHours": 0.0,
                "count": 0,
            }
            agg[cid] = row
        row["hours"] += s.hours
        row["count"] += 1
        if s.source == "weekly":
            row["weeklyHours"] += s.hours
        else:
            row["manualHours"] += s.hours
    rows = sorted(agg.values(), key=lambda r: r["hours"], reverse=True)
    for r in rows:
        r["hours"] = round(r["hours"], 2)
        r["weeklyHours"] = round(r["weeklyHours"], 2)
        r["manualHours"] = round(r["manualHours"], 2)
    return rows


def to_float(value: object) -> float:
    """把 Decimal / str / int 安全转 float（None → 0）。"""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
