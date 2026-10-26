"""数据大屏编排层：客户 / 出差 / 财务 / 工时 / 分享。

分层职责：
- workload.py / geo.py 只管「怎么算 / 怎么转发」，不碰数据库与身份；
- 本文件管「算什么、记给谁、谁能看」—— 全部读写强制按 owner_uid 过滤。

**账号隔离铁律**：本模块所有业务查询一律带 `owner_uid == identity.uid` 条件。
财务数据涉敏，除 owner 过滤外还必须走 BizShare 的显式分享通道，
不存在「按 owner 查全部」这类开放接口。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.identity import Identity
from ...db.models import (
    BizCustomer,
    BizExpense,
    BizShare,
    BizTimeEntry,
    BizTrip,
    BizTripStop,
    TaskItem,
)
from . import constants, geo, workload
from .errors import (
    BizDashboardError,
    bad_amount,
    bad_date,
    bad_param,
    bad_range,
    not_found,
    required,
    share_empty_scope,
    share_expired,
    share_invalid,
)

_CN_TZ = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """把数据库取回的时间归一成 **aware UTC**。

    ⚠️ 为什么必须做这一步：
    - PostgreSQL 的 TIMESTAMP WITH TIME ZONE 取回是 aware；
    - SQLite 的 DATETIME 列取回是 **naive**（存进去的 tzinfo 被丢弃）；
    - 同一份代码在两种后端上比较 `naive < aware` 会抛
      TypeError: can't compare offset-naive and offset-aware datetimes。

    项目当前 SQLite 只用于本地开发、PostgreSQL 用于真机，但**两处都要能跑**，
    否则本地验证通过、真机炸（本项目 v1.0.25 的教训：本地测不出、真机才炸）。

    naive 值按 UTC 解读 —— 因为写入时用的就是 `datetime.now(timezone.utc)`，
    存的本来就是 UTC 时刻，只是 SQLite 不保留 tzinfo 标记。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _today() -> str:
    return datetime.now(_CN_TZ).strftime("%Y-%m-%d")


def _norm_date(value: str, field: str) -> str:
    """校验并归一化 YYYY-MM-DD。空串放行（可选字段）。"""
    text = (value or "").strip()
    if not text:
        return ""
    try:
        datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        raise bad_date(text, field) from None
    return text[:10]


def _norm_amount(value: Any) -> Decimal:
    """金额归一化：转 Decimal，负数与非数一律拒绝。

    金额用 Decimal 而非 float —— 浮点累加有 0.1+0.2 类误差，
    财务统计不可接受。
    """
    if value is None or value == "":
        return Decimal("0")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise bad_amount(value) from None
    if d < 0:
        raise bad_amount(value)
    # 最多两位小数
    return d.quantize(Decimal("0.01"))


def _norm_hours(value: Any) -> Decimal:
    """工时归一化：0 ≤ hours ≤ MAX_HOURS_PER_ENTRY。"""
    if value is None or value == "":
        return Decimal("0")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BizDashboardError("BAD_HOURS", f"工时不合法：{value}", 400) from None
    if d < 0 or d > Decimal(str(constants.MAX_HOURS_PER_ENTRY)):
        raise BizDashboardError(
            "BAD_HOURS",
            f"单条工时需在 0 ~ {constants.MAX_HOURS_PER_ENTRY} 小时之间，当前为 {value}",
            400,
        )
    return d.quantize(Decimal("0.01"))


def _opt_int(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ 客户


def list_customers(db: Session, identity: Identity, keyword: str = "") -> list[dict]:
    stmt = select(BizCustomer).where(BizCustomer.owner_uid == identity.uid)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            BizCustomer.name.ilike(like)
            | BizCustomer.contact.ilike(like)
            | BizCustomer.industry.ilike(like)
        )
    stmt = stmt.order_by(BizCustomer.updated_at.desc())
    rows = db.scalars(stmt).all()
    return [_customer_dto(c) for c in rows]


def _customer_dto(c: BizCustomer) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "contact": c.contact,
        "phone": c.phone,
        "address": c.address,
        "industry": c.industry,
        "level": c.level,
        "region": c.region,
        "tags": c.tags or [],
        "note": c.note,
        "status": c.status,
        "createdAt": c.created_at.isoformat() if c.created_at else "",
    }


def _owned_customer(db: Session, identity: Identity, cid: int) -> BizCustomer:
    """取客户并校验归属。越权与不存在返回同一个错误。"""
    row = db.scalar(
        select(BizCustomer).where(
            BizCustomer.id == cid, BizCustomer.owner_uid == identity.uid
        )
    )
    if row is None:
        raise not_found("客户", cid)
    return row


def create_customer(db: Session, identity: Identity, body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise required("客户名称")
    row = BizCustomer(
        owner_uid=identity.uid,
        name=name,
        contact=(body.get("contact") or "").strip(),
        phone=(body.get("phone") or "").strip(),
        address=(body.get("address") or "").strip(),
        industry=(body.get("industry") or "").strip(),
        level=(body.get("level") or "").strip(),
        region=(body.get("region") or "").strip(),
        tags=[str(t).strip() for t in (body.get("tags") or []) if str(t).strip()],
        note=(body.get("note") or "").strip(),
        status=(body.get("status") or "active").strip(),
    )
    if row.status not in constants.CUSTOMER_STATUS_CODES:
        row.status = "active"
    db.add(row)
    db.commit()
    db.refresh(row)
    return _customer_dto(row)


def update_customer(db: Session, identity: Identity, cid: int, body: dict) -> dict:
    row = _owned_customer(db, identity, cid)
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise required("客户名称")
        row.name = name
    for field in ("contact", "phone", "address", "industry", "level", "region", "note"):
        if field in body:
            setattr(row, field, (body.get(field) or "").strip())
    if "tags" in body:
        row.tags = [str(t).strip() for t in (body.get("tags") or []) if str(t).strip()]
    if "status" in body:
        st = (body.get("status") or "active").strip()
        if st in constants.CUSTOMER_STATUS_CODES:
            row.status = st
    db.commit()
    db.refresh(row)
    return _customer_dto(row)


def delete_customer(db: Session, identity: Identity, cid: int) -> dict:
    """删除客户。

    ⚠️ 必须先解绑所有真外键引用并 commit，再删主表 —— 这是 v1.0.25
    ForeignKeyViolation 的教训：ORM 在同一次 flush 内的语句顺序由 mapper
    依赖图决定，实测会把 DELETE 主表排在 UPDATE 引用表**之前**，照样 FK 失败。
    """
    row = _owned_customer(db, identity, cid)
    # 1) 解绑出差
    trips = db.scalars(select(BizTrip).where(BizTrip.customer_id == cid)).all()
    for t in trips:
        t.customer_id = None
    # 2) 解绑财务
    expenses = db.scalars(select(BizExpense).where(BizExpense.customer_id == cid)).all()
    for e in expenses:
        e.customer_id = None
    # 3) 解绑工时
    entries = db.scalars(select(BizTimeEntry).where(BizTimeEntry.customer_id == cid)).all()
    for t in entries:
        t.customer_id = None
    db.commit()  # 先提交解绑，确保下一条 DELETE 不再被 FK 拦

    db.delete(row)
    db.commit()
    return {"ok": True, "id": cid, "unlinked": {
        "trips": len(trips), "expenses": len(expenses), "timeEntries": len(entries),
    }}


# ------------------------------------------------------------------ 出差


def _trip_dto(t: BizTrip, stops: list[BizTripStop] | None = None) -> dict:
    d = {
        "id": t.id,
        "customerId": t.customer_id,
        "title": t.title,
        "originName": t.origin_name,
        "originLng": t.origin_lng,
        "originLat": t.origin_lat,
        "destName": t.dest_name,
        "destLng": t.dest_lng,
        "destLat": t.dest_lat,
        "startDate": t.start_date,
        "endDate": t.end_date,
        "transport": t.transport,
        "mileageKm": float(t.mileage_km or 0),
        "costAmount": float(t.cost_amount or 0),
        "status": t.status,
        "note": t.note,
    }
    if stops is not None:
        d["stops"] = [_stop_dto(s) for s in stops]
    return d


def _stop_dto(s: BizTripStop) -> dict:
    return {
        "id": s.id,
        "seq": s.seq,
        "name": s.name,
        "lng": s.lng,
        "lat": s.lat,
        "arriveDate": s.arrive_date,
        "note": s.note,
    }


def _trip_stops(db: Session, trip_id: int) -> list[BizTripStop]:
    return list(
        db.scalars(
            select(BizTripStop)
            .where(BizTripStop.trip_id == trip_id)
            .order_by(BizTripStop.seq, BizTripStop.id)
        ).all()
    )


def list_trips(db: Session, identity: Identity, status: str = "", customer_id: int | None = None) -> list[dict]:
    stmt = select(BizTrip).where(BizTrip.owner_uid == identity.uid)
    if status:
        stmt = stmt.where(BizTrip.status == status)
    if customer_id:
        stmt = stmt.where(BizTrip.customer_id == customer_id)
    stmt = stmt.order_by(BizTrip.start_date.desc(), BizTrip.id.desc())
    rows = db.scalars(stmt).all()
    return [_trip_dto(t, _trip_stops(db, t.id)) for t in rows]


def _owned_trip(db: Session, identity: Identity, tid: int) -> BizTrip:
    row = db.scalar(
        select(BizTrip).where(BizTrip.id == tid, BizTrip.owner_uid == identity.uid)
    )
    if row is None:
        raise not_found("出差记录", tid)
    return row


def _apply_trip_body(row: BizTrip, body: dict) -> None:
    if "title" in body:
        row.title = (body.get("title") or "").strip()
    if "customerId" in body:
        row.customer_id = _opt_int(body.get("customerId"))
    for f, attr in (
        ("originName", "origin_name"),
        ("destName", "dest_name"),
        ("transport", "transport"),
        ("note", "note"),
    ):
        if f in body:
            setattr(row, attr, (body.get(f) or "").strip())
    for f, attr in (("originLng", "origin_lng"), ("originLat", "origin_lat"),
                    ("destLng", "dest_lng"), ("destLat", "dest_lat")):
        if f in body:
            v = body.get(f)
            try:
                setattr(row, attr, None if v in (None, "") else float(v))
            except (TypeError, ValueError):
                raise bad_param(f, "应为数值（经纬度）") from None
    if "mileageKm" in body:
        row.mileage_km = float(workload.to_float(body.get("mileageKm")))
    if "costAmount" in body:
        row.cost_amount = float(_norm_amount(body.get("costAmount")))
    if "startDate" in body:
        row.start_date = _norm_date(body.get("startDate"), "开始日期")
    if "endDate" in body:
        row.end_date = _norm_date(body.get("endDate"), "结束日期")
    if row.start_date and row.end_date and row.end_date < row.start_date:
        raise bad_range(row.start_date, row.end_date)
    if "status" in body:
        st = (body.get("status") or "").strip()
        if st in constants.TRIP_STATUS_CODES:
            row.status = st


def _replace_stops(db: Session, trip_id: int, stops: list) -> None:
    """整体替换途经点（先删后建，顺序按 seq）。"""
    old = db.scalars(select(BizTripStop).where(BizTripStop.trip_id == trip_id)).all()
    for s in old:
        db.delete(s)
    db.flush()
    for idx, st in enumerate(stops or [], start=1):
        if not isinstance(st, dict):
            continue
        name = (st.get("name") or "").strip()
        if not name:
            continue
        lng = st.get("lng")
        lat = st.get("lat")
        try:
            lng = None if lng in (None, "") else float(lng)
            lat = None if lat in (None, "") else float(lat)
        except (TypeError, ValueError):
            raise bad_param("stops", "经纬度应为数值") from None
        db.add(
            BizTripStop(
                trip_id=trip_id,
                seq=int(st.get("seq") or idx),
                name=name,
                lng=lng,
                lat=lat,
                arrive_date=_norm_date(st.get("arriveDate"), "途经日期"),
                note=(st.get("note") or "").strip(),
            )
        )


def create_trip(db: Session, identity: Identity, body: dict) -> dict:
    row = BizTrip(owner_uid=identity.uid)
    _apply_trip_body(row, body)
    db.add(row)
    db.flush()  # 拿到 trip_id 以便写途经点
    _replace_stops(db, row.id, body.get("stops") or [])
    db.commit()
    db.refresh(row)
    return _trip_dto(row, _trip_stops(db, row.id))


def update_trip(db: Session, identity: Identity, tid: int, body: dict) -> dict:
    row = _owned_trip(db, identity, tid)
    _apply_trip_body(row, body)
    if "stops" in body:
        _replace_stops(db, tid, body.get("stops") or [])
    db.commit()
    db.refresh(row)
    return _trip_dto(row, _trip_stops(db, tid))


def delete_trip(db: Session, identity: Identity, tid: int) -> dict:
    """删除出差：先删途经点并 commit，再解绑财务/工时，最后删主表。

    顺序不可颠倒 —— 与 v1.0.25 的教训一致。
    """
    row = _owned_trip(db, identity, tid)
    stops = db.scalars(select(BizTripStop).where(BizTripStop.trip_id == tid)).all()
    for s in stops:
        db.delete(s)
    db.commit()  # 先删子表并提交

    for e in db.scalars(select(BizExpense).where(BizExpense.trip_id == tid)).all():
        e.trip_id = None
    for t in db.scalars(select(BizTimeEntry).where(BizTimeEntry.trip_id == tid)).all():
        t.trip_id = None
    db.commit()

    db.delete(row)
    db.commit()
    return {"ok": True, "id": tid}


# ------------------------------------------------------------------ 财务


def _expense_dto(e: BizExpense) -> dict:
    return {
        "id": e.id,
        "customerId": e.customer_id,
        "tripId": e.trip_id,
        "kind": e.kind,
        "category": e.category,
        "amount": float(e.amount or 0),
        "occurredOn": e.occurred_on,
        "note": e.note,
    }


def list_expenses(
    db: Session,
    identity: Identity,
    kind: str = "",
    customer_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    stmt = select(BizExpense).where(BizExpense.owner_uid == identity.uid)
    if kind:
        stmt = stmt.where(BizExpense.kind == kind)
    if customer_id:
        stmt = stmt.where(BizExpense.customer_id == customer_id)
    if date_from:
        stmt = stmt.where(BizExpense.occurred_on >= _norm_date(date_from, "开始日期"))
    if date_to:
        stmt = stmt.where(BizExpense.occurred_on <= _norm_date(date_to, "结束日期"))
    stmt = stmt.order_by(BizExpense.occurred_on.desc(), BizExpense.id.desc())
    rows = db.scalars(stmt).all()
    return [_expense_dto(e) for e in rows]


def _owned_expense(db: Session, identity: Identity, eid: int) -> BizExpense:
    row = db.scalar(
        select(BizExpense).where(
            BizExpense.id == eid, BizExpense.owner_uid == identity.uid
        )
    )
    if row is None:
        raise not_found("财务流水", eid)
    return row


def create_expense(db: Session, identity: Identity, body: dict) -> dict:
    kind = (body.get("kind") or "expense").strip()
    if kind not in constants.EXPENSE_KIND_CODES:
        kind = "expense"
    row = BizExpense(
        owner_uid=identity.uid,
        customer_id=_opt_int(body.get("customerId")),
        trip_id=_opt_int(body.get("tripId")),
        kind=kind,
        category=(body.get("category") or "").strip(),
        amount=_norm_amount(body.get("amount")),
        occurred_on=_norm_date(body.get("occurredOn"), "发生日期") or _today(),
        note=(body.get("note") or "").strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _expense_dto(row)


def update_expense(db: Session, identity: Identity, eid: int, body: dict) -> dict:
    row = _owned_expense(db, identity, eid)
    if "kind" in body:
        k = (body.get("kind") or "").strip()
        if k in constants.EXPENSE_KIND_CODES:
            row.kind = k
    if "category" in body:
        row.category = (body.get("category") or "").strip()
    if "amount" in body:
        row.amount = _norm_amount(body.get("amount"))
    if "occurredOn" in body:
        row.occurred_on = _norm_date(body.get("occurredOn"), "发生日期")
    if "customerId" in body:
        row.customer_id = _opt_int(body.get("customerId"))
    if "tripId" in body:
        row.trip_id = _opt_int(body.get("tripId"))
    if "note" in body:
        row.note = (body.get("note") or "").strip()
    db.commit()
    db.refresh(row)
    return _expense_dto(row)


def delete_expense(db: Session, identity: Identity, eid: int) -> dict:
    row = _owned_expense(db, identity, eid)
    db.delete(row)
    db.commit()
    return {"ok": True, "id": eid}


# ------------------------------------------------------------------ 工时台账


def _entry_dto(t: BizTimeEntry) -> dict:
    return {
        "id": t.id,
        "customerId": t.customer_id,
        "tripId": t.trip_id,
        "title": t.title,
        "hours": float(t.hours or 0),
        "taskDate": t.task_date,
        "note": t.note,
    }


def list_time_entries(db: Session, identity: Identity, customer_id: int | None = None) -> list[dict]:
    stmt = select(BizTimeEntry).where(BizTimeEntry.owner_uid == identity.uid)
    if customer_id:
        stmt = stmt.where(BizTimeEntry.customer_id == customer_id)
    stmt = stmt.order_by(BizTimeEntry.task_date.desc(), BizTimeEntry.id.desc())
    rows = db.scalars(stmt).all()
    return [_entry_dto(t) for t in rows]


def create_time_entry(db: Session, identity: Identity, body: dict) -> dict:
    title = (body.get("title") or "").strip()
    if not title:
        raise required("工作事项")
    row = BizTimeEntry(
        owner_uid=identity.uid,
        customer_id=_opt_int(body.get("customerId")),
        trip_id=_opt_int(body.get("tripId")),
        title=title,
        hours=_norm_hours(body.get("hours")),
        task_date=_norm_date(body.get("taskDate"), "工作日期") or _today(),
        note=(body.get("note") or "").strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _entry_dto(row)


def update_time_entry(db: Session, identity: Identity, tid: int, body: dict) -> dict:
    row = db.scalar(
        select(BizTimeEntry).where(
            BizTimeEntry.id == tid, BizTimeEntry.owner_uid == identity.uid
        )
    )
    if row is None:
        raise not_found("工时记录", tid)
    if "title" in body:
        title = (body.get("title") or "").strip()
        if not title:
            raise required("工作事项")
        row.title = title
    if "hours" in body:
        row.hours = _norm_hours(body.get("hours"))
    if "taskDate" in body:
        row.task_date = _norm_date(body.get("taskDate"), "工作日期")
    if "customerId" in body:
        row.customer_id = _opt_int(body.get("customerId"))
    if "tripId" in body:
        row.trip_id = _opt_int(body.get("tripId"))
    if "note" in body:
        row.note = (body.get("note") or "").strip()
    db.commit()
    db.refresh(row)
    return _entry_dto(row)


def delete_time_entry(db: Session, identity: Identity, tid: int) -> dict:
    row = db.scalar(
        select(BizTimeEntry).where(
            BizTimeEntry.id == tid, BizTimeEntry.owner_uid == identity.uid
        )
    )
    if row is None:
        raise not_found("工时记录", tid)
    db.delete(row)
    db.commit()
    return {"ok": True, "id": tid}


# ------------------------------------------------------------------ 工作量聚合


def _customer_name_map(db: Session, identity: Identity) -> dict[int, str]:
    rows = db.scalars(
        select(BizCustomer).where(BizCustomer.owner_uid == identity.uid)
    ).all()
    return {c.id: c.name for c in rows}


def workload_slices(db: Session, identity: Identity) -> list[workload.WorkloadSlice]:
    """采集双口径工作量的原始切片。

    口径一：周报工时（只读 task_items）
    ⚠️ task_items 无 customer_id，因此周报工时归入「未归属客户」——
    如实呈现而非编造关联。
    """
    out: list[workload.WorkloadSlice] = []

    # ---- 口径一：周报工时（只读聚合，绝不写 task_items）----
    tasks = db.scalars(
        select(TaskItem).where(TaskItem.owner_uid == identity.uid)
    ).all()
    for t in tasks:
        hours = workload.slice_hours(t.start_at, t.end_at)
        if hours <= 0:
            continue
        out.append(
            workload.WorkloadSlice(
                source="weekly",
                title=t.title,
                task_date=(t.start_at or "")[:10],
                hours=hours,
                customer_id=0,  # 周报任务无客户字段
                customer_name="",
                category=t.stat_category or "",
                ref_id=t.id,
            )
        )

    # ---- 口径二：独立工时台账 ----
    names = _customer_name_map(db, identity)
    entries = db.scalars(
        select(BizTimeEntry).where(BizTimeEntry.owner_uid == identity.uid)
    ).all()
    for e in entries:
        out.append(
            workload.WorkloadSlice(
                source="manual",
                title=e.title,
                task_date=e.task_date,
                hours=workload.to_float(e.hours),
                customer_id=e.customer_id or 0,
                customer_name=names.get(e.customer_id or 0, ""),
                category="manual",
                ref_id=e.id,
            )
        )
    return out


def workload_overview(db: Session, identity: Identity, granularity: str = "month") -> dict:
    """工作量总览：时间桶 + 客户维度 + 双口径拆分。"""
    if granularity not in (workload.GRAN_DAY, workload.GRAN_WEEK, workload.GRAN_MONTH):
        granularity = workload.GRAN_MONTH
    slices = workload_slices(db, identity)
    buckets = workload.aggregate(slices, granularity)
    by_cust = workload.by_customer(slices)
    total = round(sum(s.hours for s in slices), 2)
    weekly = round(sum(s.hours for s in slices if s.source == "weekly"), 2)
    manual = round(sum(s.hours for s in slices if s.source == "manual"), 2)
    return {
        "granularity": granularity,
        "totalHours": total,
        "weeklyHours": weekly,
        "manualHours": manual,
        "entryCount": len(slices),
        "buckets": [
            {
                "key": b.key,
                "label": b.label,
                "hours": b.hours,
                "weeklyHours": b.weekly_hours,
                "manualHours": b.manual_hours,
                "count": b.count,
            }
            for b in buckets
        ],
        "byCustomer": by_cust,
    }


# ------------------------------------------------------------------ 大屏总览


def dashboard_overview(db: Session, identity: Identity) -> dict:
    """大屏首屏 KPI。"""
    cust_count = db.scalar(
        select(func.count()).select_from(BizCustomer).where(BizCustomer.owner_uid == identity.uid)
    )
    trip_count = db.scalar(
        select(func.count()).select_from(BizTrip).where(BizTrip.owner_uid == identity.uid)
    )
    expense_count = db.scalar(
        select(func.count()).select_from(BizExpense).where(BizExpense.owner_uid == identity.uid)
    )

    income = db.scalar(
        select(func.coalesce(func.sum(BizExpense.amount), 0)).where(
            BizExpense.owner_uid == identity.uid, BizExpense.kind == "income"
        )
    )
    expense = db.scalar(
        select(func.coalesce(func.sum(BizExpense.amount), 0)).where(
            BizExpense.owner_uid == identity.uid, BizExpense.kind == "expense"
        )
    )

    wl = workload_overview(db, identity, "month")

    # 客户维度排行（客户名映射）
    names = _customer_name_map(db, identity)
    top_customers = []
    for c in db.scalars(
        select(BizCustomer)
        .where(BizCustomer.owner_uid == identity.uid)
        .order_by(BizCustomer.updated_at.desc())
        .limit(10)
    ).all():
        top_customers.append(
            {"id": c.id, "name": c.name, "status": c.status, "industry": c.industry}
        )

    # 出差按月分布
    trip_months: dict[str, int] = {}
    for t in db.scalars(
        select(BizTrip).where(BizTrip.owner_uid == identity.uid)
    ).all():
        key = (t.start_date or "")[:7]
        if key:
            trip_months[key] = trip_months.get(key, 0) + 1

    return {
        "customers": int(cust_count or 0),
        "trips": int(trip_count or 0),
        "expenseRecords": int(expense_count or 0),
        "totalIncome": float(income or 0),
        "totalExpense": float(expense or 0),
        "balance": round(float(income or 0) - float(expense or 0), 2),
        "workload": wl,
        "topCustomers": top_customers,
        "tripsByMonth": [
            {"key": k, "label": workload.bucket_label(k), "count": v}
            for k, v in sorted(trip_months.items())
        ],
        "customerNames": names,
    }


# ------------------------------------------------------------------ 财务选择性分享


def create_share(
    db: Session,
    identity: Identity,
    body: dict,
) -> dict:
    """创建分享链接：显式勾选记录 + 有时效 + 可撤销。

    明文 token **只在此处返回一次**，库里只存 sha256 哈希。
    """
    scope_kind = (body.get("scopeKind") or "expense").strip()
    if scope_kind not in constants.SHARE_SCOPE_CODES:
        raise bad_param("scopeKind", f"不支持的分享类别：{scope_kind}")
    raw_ids = body.get("scopeIds") or []
    ids: list[int] = []
    for v in raw_ids:
        iv = _opt_int(v)
        if iv is not None and iv not in ids:
            ids.append(iv)
    if not ids:
        raise share_empty_scope()

    # 校验被勾选的记录确实属于本人（防止借分享接口探测他人记录是否存在）
    if scope_kind == "expense":
        owned = db.scalars(
            select(BizExpense.id).where(
                BizExpense.owner_uid == identity.uid, BizExpense.id.in_(ids)
            )
        ).all()
    elif scope_kind == "trip":
        owned = db.scalars(
            select(BizTrip.id).where(
                BizTrip.owner_uid == identity.uid, BizTrip.id.in_(ids)
            )
        ).all()
    else:
        owned = ids  # workload 分享按聚合口径，无需逐条校验
    valid_ids = list(owned)
    if not valid_ids:
        raise share_empty_scope()

    days = _opt_int(body.get("days")) or constants.SHARE_DEFAULT_DAYS
    if days < 1 or days > constants.SHARE_MAX_DAYS:
        raise bad_param("days", f"有效期需在 1 ~ {constants.SHARE_MAX_DAYS} 天之间")

    token = secrets.token_urlsafe(24)
    row = BizShare(
        owner_uid=identity.uid,
        title=(body.get("title") or "").strip(),
        token_hash=geo.token_hash(token),
        scope_ids=valid_ids,
        scope_kind=scope_kind,
        expires_at=_now() + timedelta(days=days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    geo.audit_share(identity.uid, "create", {"scopeKind": scope_kind, "count": len(valid_ids)})
    expires = _as_utc(row.expires_at)
    return {
        "id": row.id,
        "token": token,  # 仅此一次
        "scopeKind": scope_kind,
        "scopeCount": len(valid_ids),
        "expiresAt": expires.isoformat() if expires else "",
        "title": row.title,
    }


def list_shares(db: Session, identity: Identity) -> list[dict]:
    rows = db.scalars(
        select(BizShare)
        .where(BizShare.owner_uid == identity.uid)
        .order_by(BizShare.created_at.desc())
    ).all()
    now = _now()
    out = []
    for s in rows:
        expires = _as_utc(s.expires_at)
        expired = expires is not None and expires < now
        out.append(
            {
                "id": s.id,
                "title": s.title,
                "scopeKind": s.scope_kind,
                "scopeCount": len(s.scope_ids or []),
                "expiresAt": expires.isoformat() if expires else "",
                "revoked": bool(s.revoked),
                "expired": expired,
                "active": (not s.revoked) and (not expired),
                "viewCount": s.view_count,
                "createdAt": s.created_at.isoformat() if s.created_at else "",
            }
        )
    return out


def revoke_share(db: Session, identity: Identity, sid: int) -> dict:
    row = db.scalar(
        select(BizShare).where(BizShare.id == sid, BizShare.owner_uid == identity.uid)
    )
    if row is None:
        raise not_found("分享", sid)
    row.revoked = 1
    db.commit()
    geo.audit_share(identity.uid, "revoke", {"shareId": sid})
    return {"ok": True, "id": sid}


def read_share(db: Session, token: str) -> dict:
    """按令牌读取分享内容。

    ⚠️ 本接口**不要求应用账号登录** —— 分享链接的接收者可能不是本 NAS 的用户。
    这是唯一不按 owner_uid 过滤的读接口，但它只能读到**创建者显式勾选**的记录，
    且受有效期与撤销状态约束。

    越权/不存在/已撤销统一返回 SHARE_INVALID（不暴露分享是否存在）；
    已过期返回 SHARE_EXPIRED（可行动信息不同：找分享者续期）。
    """
    token = (token or "").strip()
    if not token:
        raise share_invalid()
    row = db.scalar(
        select(BizShare).where(BizShare.token_hash == geo.token_hash(token))
    )
    if row is None or row.revoked:
        raise share_invalid()
    expires = _as_utc(row.expires_at)
    if expires is not None and expires < _now():
        raise share_expired()

    ids = [int(i) for i in (row.scope_ids or [])]
    payload: dict[str, Any] = {
        "title": row.title,
        "scopeKind": row.scope_kind,
        "expiresAt": expires.isoformat() if expires else "",
        "owner": "分享方",  # 不泄露分享者身份
    }

    if row.scope_kind == "expense":
        rows = db.scalars(select(BizExpense).where(BizExpense.id.in_(ids))).all()
        payload["records"] = [_expense_dto(e) for e in rows]
        payload["total"] = round(sum(float(e.amount or 0) for e in rows), 2)
    elif row.scope_kind == "trip":
        rows = db.scalars(select(BizTrip).where(BizTrip.id.in_(ids))).all()
        payload["records"] = [_trip_dto(t) for t in rows]
    else:
        payload["records"] = []

    # 访问计数（察觉异常传播）
    row.view_count = (row.view_count or 0) + 1
    row.last_viewed_at = _now()
    db.commit()
    return payload
