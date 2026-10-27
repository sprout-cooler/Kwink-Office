"""数据大屏编排层：客户 / 出差 / 财务 / 工时 / 分享。

分层职责：
- workload.py / geo.py 只管「怎么算 / 怎么转发」，不碰数据库与身份；
- 本文件管「算什么、记给谁、谁能看」—— 全部读写强制按 owner_uid 过滤。

**账号隔离铁律**：本模块所有业务查询一律带 `owner_uid == identity.uid` 条件。
财务数据涉敏，除 owner 过滤外还必须走 BizShare 的显式分享通道，
不存在「按 owner 查全部」这类开放接口。
"""
from __future__ import annotations

import io
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...core.identity import Identity
from ...db.models import (
    BizCustomer,
    BizExpense,
    BizExpenseImport,
    BizShare,
    BizTimeEntry,
    BizTrip,
    BizTripStop,
    TaskItem,
)
from . import bill_import, constants, geo, workload
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
    share_pass_invalid,
    share_pass_required,
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


def _norm_customer_source(value: Any) -> str:
    """客户来源归一化：只接受字典内的 code，其余一律当空。

    不抛错的原因：来源是**辅助信息**，填错不该阻断客户建档
    （客户名才是主数据，填错来源随时可改）。
    """
    code = str(value or "").strip()
    if code in constants.CUSTOMER_SOURCE_CODES:
        return code
    return ""


def _norm_id_list(value: Any) -> list[int]:
    """任务 id 列表归一化：只保留正整数，去重且保持顺序。

    出差的 reportTaskIds 存的是周报任务 id（非本模块 id），
    所以这里只做形状校验，不做存在性校验 —— 跨模块的引用有效性
    由写入方（周报联动）保证。
    """
    if not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for v in value:
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if i > 0 and i not in seen:
            seen.add(i)
            out.append(i)
    return out


# ------------------------------------------------------------------ 客户


def list_customers(
    db: Session, identity: Identity, keyword: str = "", source: str = ""
) -> list[dict]:
    stmt = select(BizCustomer).where(BizCustomer.owner_uid == identity.uid)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            BizCustomer.name.ilike(like)
            | BizCustomer.contact.ilike(like)
            | BizCustomer.industry.ilike(like)
        )
    src = (source or "").strip()
    if src:
        stmt = stmt.where(BizCustomer.source == src)
    stmt = stmt.order_by(BizCustomer.updated_at.desc())
    rows = db.scalars(stmt).all()
    return [_customer_dto(c) for c in rows]


def list_customer_names(db: Session, owner_uid: str, limit: int = 100) -> list[str]:
    """只取客户名（供周报 AI 识别时注入「客户名单」用）。

    为什么需要它：周报识别要**指认**客户而不是自由抽取字符串 ——
    自由抽取会产出「XX科技公司」「xx科技」这类变体，与客户表对不上。
    限定在名单内指认，输出天然可精确匹配。

    限量：客户名清单会拼进提示词，客户上千时提示词会爆炸。
    超限时按更新时间倒序取（近期客户更可能是当前周报涉及的）。
    """
    stmt = (
        select(BizCustomer.name)
        .where(BizCustomer.owner_uid == owner_uid)
        .order_by(BizCustomer.updated_at.desc())
        .limit(max(1, int(limit)))
    )
    return [n for n in db.scalars(stmt).all() if n]


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
        "source": c.source,
        "sourceNote": c.source_note,
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
        source=_norm_customer_source(body.get("source")),
        source_note=(body.get("sourceNote") or "").strip(),
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
    if "source" in body:
        row.source = _norm_customer_source(body.get("source"))
    if "sourceNote" in body:
        row.source_note = (body.get("sourceNote") or "").strip()
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
        "reasonCode": t.reason_code,
        "reimburseStatus": t.reimburse_status,
        "reimburseAmount": float(t.reimburse_amount or 0),
        "reportTaskIds": list(t.report_task_ids or []),
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
    if "reasonCode" in body:
        rc = (body.get("reasonCode") or "").strip()
        # 事由是辅助分类，填错不该阻断出差记录保存
        row.reason_code = rc if rc in constants.TRIP_REASON_CODES else ""
    if "reimburseStatus" in body:
        rs = (body.get("reimburseStatus") or "").strip()
        row.reimburse_status = rs if rs in constants.REIMBURSE_STATUS_CODES else "none"
    if "reimburseAmount" in body:
        row.reimburse_amount = _norm_amount(body.get("reimburseAmount"))
    if "reportTaskIds" in body:
        row.report_task_ids = _norm_id_list(body.get("reportTaskIds"))
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
        # v1.0.32 账单导入字段（手录流水为空）
        "platform": e.platform or "",
        "orderNo": e.order_no or "",
        "counterparty": e.counterparty or "",
        "txnType": e.txn_type or "",
        "paymentMethod": e.payment_method or "",
        "importBatchId": e.import_batch_id,
    }


def list_expenses(
    db: Session,
    identity: Identity,
    kind: str = "",
    customer_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    counterparty: str = "",
    payment_method: str = "",
) -> list[dict]:
    stmt = select(BizExpense).where(BizExpense.owner_uid == identity.uid)
    if kind:
        stmt = stmt.where(BizExpense.kind == kind)
    if customer_id:
        stmt = stmt.where(BizExpense.customer_id == customer_id)
    if (payment_method or "").strip():
        stmt = stmt.where(BizExpense.payment_method == payment_method.strip())
    if (counterparty or "").strip():
        # 交易方关键字搜索。**刻意同时匹配关联客户的名字**：
        # v1.0.32 之前录入的流水只有 customer_id、没有 counterparty，
        # 若只搜 counterparty，这些历史流水会「搜不到」，用户会以为数据丢了。
        # 这里用 OR 把历史口径一起覆盖，等于对历史数据做**读时兼容**而非写时迁移。
        kw = f"%{(counterparty or '').strip()}%"
        matched_customers = select(BizCustomer.id).where(
            BizCustomer.owner_uid == identity.uid, BizCustomer.name.like(kw)
        )
        stmt = stmt.where(
            or_(BizExpense.counterparty.like(kw), BizExpense.customer_id.in_(matched_customers))
        )
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
        # 交易方：与关联客户（customerId）是两个概念，可各自独立填写
        counterparty=(body.get("counterparty") or "").strip()[:128],
        payment_method=(body.get("paymentMethod") or "").strip()[:32],
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
    if "counterparty" in body:
        row.counterparty = (body.get("counterparty") or "").strip()[:128]
    if "paymentMethod" in body:
        row.payment_method = (body.get("paymentMethod") or "").strip()[:32]
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
    scopes, primary_kind = _resolve_scopes(db, identity, body)
    # 旧字段仍写一份（兼容已发出的旧链接与老前端）
    valid_ids = scopes.get(primary_kind) or []

    days = _opt_int(body.get("days")) or constants.SHARE_DEFAULT_DAYS
    if days < 1 or days > constants.SHARE_MAX_DAYS:
        raise bad_param("days", f"有效期需在 1 ~ {constants.SHARE_MAX_DAYS} 天之间")

    # 可选访问口令：设了之后「拿到链接」还不够，还必须输入口令。
    # 只存哈希（与 token 同策略），明文不落库。
    passcode = (body.get("passcode") or "").strip()
    pass_hash = ""
    if passcode:
        if not (constants.SHARE_PASS_MIN_LEN <= len(passcode) <= constants.SHARE_PASS_MAX_LEN):
            raise bad_param(
                "passcode",
                f"访问口令长度需在 {constants.SHARE_PASS_MIN_LEN} ~ {constants.SHARE_PASS_MAX_LEN} 个字符之间",
            )
        pass_hash = geo.token_hash(passcode)

    token = secrets.token_urlsafe(24)
    row = BizShare(
        owner_uid=identity.uid,
        title=(body.get("title") or "").strip(),
        token_hash=geo.token_hash(token),
        # v1.0.32 多类范围为实际生效字段
        scopes=scopes,
        pass_hash=pass_hash,
        # 旧字段同步写一份：保证 v1.0.31 及更早创建的链接仍能被读取
        scope_ids=valid_ids,
        scope_kind=primary_kind,
        expires_at=_now() + timedelta(days=days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    geo.audit_share(
        identity.uid,
        "create",
        {"scopes": {k: len(v) for k, v in scopes.items()}, "hasPass": bool(pass_hash)},
    )
    expires = _as_utc(row.expires_at)
    return {
        "id": row.id,
        "token": token,  # 仅此一次
        "scopes": scopes,
        "scopeKind": primary_kind,
        "scopeCount": sum(len(v) for v in scopes.values()),
        "hasPass": bool(pass_hash),
        "expiresAt": expires.isoformat() if expires else "",
        "title": row.title,
    }


def _resolve_scopes(db: Session, identity: Identity, body: dict) -> tuple[dict[str, list[int]], str]:
    """解析并校验分享范围（v1.0.32 多类）。

    支持两类入参：
    - 新：`scopes = {"expense": [1,2], "customer": [3], "workload": [], "trip": [7]}`
    - 旧：`scopeKind` + `scopeIds`（v1.0.31 及更早），自动转成新结构

    返回 (已校验的 scopes, 主类别)。主类别只用于填旧字段 scope_kind。

    ⚠️ 每一类都**逐条校验归属**：不校验的话，攻击者可以拿别人的记录 id 建分享，
    借这个免登录接口把别人的数据读出去。
    """
    raw = body.get("scopes")
    wanted: dict[str, list[int]] = {}

    if isinstance(raw, dict) and raw:
        for kind in constants.SHARE_SCOPE_CODES:
            if kind not in raw:
                continue
            if kind == "workload":
                wanted[kind] = []  # 聚合口径，键存在即表示包含
                continue
            if kind not in constants.SHARE_ID_SCOPES:
                continue
            ids: list[int] = []
            for v in raw.get(kind) or []:
                iv = _opt_int(v)
                if iv is not None and iv not in ids:
                    ids.append(iv)
            if ids:
                wanted[kind] = ids
    else:
        kind = (body.get("scopeKind") or "expense").strip()
        if kind not in constants.SHARE_SCOPE_CODES:
            raise bad_param("scopeKind", f"不支持的分享类别：{kind}")
        ids2: list[int] = []
        for v in body.get("scopeIds") or []:
            iv = _opt_int(v)
            if iv is not None and iv not in ids2:
                ids2.append(iv)
        if kind == "workload":
            wanted[kind] = []
        elif ids2:
            wanted[kind] = ids2

    if not wanted:
        raise share_empty_scope()

    valid: dict[str, list[int]] = {}
    for kind, ids in wanted.items():
        if kind == "expense":
            owned = db.scalars(
                select(BizExpense.id).where(
                    BizExpense.owner_uid == identity.uid, BizExpense.id.in_(ids)
                )
            ).all()
            if list(owned):
                valid[kind] = list(owned)
        elif kind == "customer":
            owned = db.scalars(
                select(BizCustomer.id).where(
                    BizCustomer.owner_uid == identity.uid, BizCustomer.id.in_(ids)
                )
            ).all()
            if list(owned):
                valid[kind] = list(owned)
        elif kind == "trip":
            owned = db.scalars(
                select(BizTrip.id).where(
                    BizTrip.owner_uid == identity.uid, BizTrip.id.in_(ids)
                )
            ).all()
            if list(owned):
                valid[kind] = list(owned)
        else:  # workload：聚合口径，无需逐条校验
            valid[kind] = []

    if not valid:
        raise share_empty_scope()

    # 主类别：按常量声明顺序取第一个，保证旧字段稳定可预期
    primary = next((k for k in constants.SHARE_SCOPE_CODES if k in valid), "expense")
    return valid, primary


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
        scopes = _scopes_of(s)
        out.append(
            {
                "id": s.id,
                "title": s.title,
                "scopeKind": s.scope_kind,
                "scopes": {k: len(v) for k, v in scopes.items()},
                "scopeCount": sum(len(v) for v in scopes.values()),
                "hasPass": bool(s.pass_hash),
                "expiresAt": expires.isoformat() if expires else "",
                "revoked": bool(s.revoked),
                "expired": expired,
                "active": (not s.revoked) and (not expired),
                "viewCount": s.view_count,
                "createdAt": s.created_at.isoformat() if s.created_at else "",
            }
        )
    return out


def _scopes_of(row: BizShare) -> dict[str, list[int]]:
    """取分享范围，旧数据自动回落到 scope_kind + scope_ids。

    v1.0.31 及更早创建的分享只有单类字段；这里统一成多类结构返回，
    前端不必区分新旧。
    """
    raw = row.scopes
    if isinstance(raw, dict) and raw:
        return {k: [int(i) for i in (v or [])] for k, v in raw.items()}
    if row.scope_kind:
        ids = [int(i) for i in (row.scope_ids or [])]
        if row.scope_kind == "workload" or ids:
            return {row.scope_kind: ids}
    return {}


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


def _customer_share_dto(c: BizCustomer) -> dict:
    """客户信息的**对外分享**视图（v1.0.32）。

    刻意**不含**联系人、电话、地址、备注 —— 这些是客户资料里敏感度最高的部分，
    而「分享客户信息」的典型场景是给合作方做对账/报备，并不需要联系方式。
    真要外发联系方式，应当走导出文件而不是长期有效的分享链接。
    """
    return {
        "id": c.id,
        "name": c.name,
        "industry": c.industry,
        "region": c.region,
        "level": c.level,
        "status": c.status,
        "source": c.source,
        "tags": c.tags or [],
    }


def read_share(db: Session, token: str, passcode: str = "") -> dict:
    """按令牌读取分享内容（v1.0.32：多类 + 可选口令）。

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

    # 口令校验**必须排在访问计数之前**：输错口令不该被记成一次有效访问，
    # 否则有人反复试口令会把 view_count 刷得毫无意义。
    if row.pass_hash:
        pc = (passcode or "").strip()
        if not pc:
            raise share_pass_required()
        if geo.token_hash(pc) != row.pass_hash:
            raise share_pass_invalid()

    scopes = _scopes_of(row)
    payload: dict[str, Any] = {
        "title": row.title,
        "expiresAt": expires.isoformat() if expires else "",
        "owner": "分享方",  # 不泄露分享者身份
        "hasPass": bool(row.pass_hash),
        "sections": {},
    }
    # 兼容 v1.0.31 及更早的前端：旧字段照旧给出
    payload["scopeKind"] = row.scope_kind
    payload["records"] = []
    payload["total"] = 0

    if "expense" in scopes:
        ids = scopes["expense"]
        rows = db.scalars(select(BizExpense).where(BizExpense.id.in_(ids))).all()
        items = [_expense_dto(e) for e in rows]
        payload["sections"]["expense"] = {
            "label": "财务流水",
            "count": len(items),
            "total": round(sum(float(x["amount"] or 0) for x in items), 2),
            "items": items,
        }
        payload["records"] = items
        payload["total"] = payload["sections"]["expense"]["total"]

    if "customer" in scopes:
        ids = scopes["customer"]
        rows = db.scalars(select(BizCustomer).where(BizCustomer.id.in_(ids))).all()
        items = [_customer_share_dto(c) for c in rows]
        payload["sections"]["customer"] = {
            "label": "客户信息",
            "count": len(items),
            "items": items,
        }

    if "trip" in scopes:
        ids = scopes["trip"]
        rows = db.scalars(select(BizTrip).where(BizTrip.id.in_(ids))).all()
        items = [_trip_dto(t) for t in rows]
        payload["sections"]["trip"] = {
            "label": "出差路径",
            "count": len(items),
            "items": items,
        }

    if "workload" in scopes:
        # 工作量是**聚合口径**（没有逐条记录 id），用分享者的 uid 现算一次。
        # 这里构造内部 Identity 只是为了复用既有的按人聚合逻辑，
        # 返回内容只含工时数字与客户名，不含 owner_uid。
        owner_identity = Identity(uid=row.owner_uid, username="", is_admin=False)
        overview = workload_overview(db, owner_identity, "month")
        payload["sections"]["workload"] = {
            "label": "工作量统计",
            "count": overview.get("entryCount", 0),
            "totalHours": overview.get("totalHours", 0),
            "weeklyHours": overview.get("weeklyHours", 0),
            "manualHours": overview.get("manualHours", 0),
            "items": overview.get("buckets", []),
            "byCustomer": overview.get("byCustomer", []),
        }

    # 访问计数（察觉异常传播）
    row.view_count = (row.view_count or 0) + 1
    row.last_viewed_at = _now()
    db.commit()
    return payload


# ================================================================ 账单导入（v1.0.32）


def _chunked(seq: list, size: int = 400):
    """分批：SQLite 的 SQL 变量数有上限（默认 999），订单号 IN 查询必须切片。"""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _existing_dedupe_keys(
    db: Session, identity: Identity, platform: str, rows: list
) -> set[str]:
    """查出库里已存在的去重键集合。

    为什么一次查一批而不是逐行查：账单动辄上千行，逐行查询会产生上千条 SQL，
    在 NAS 的 SQLite 上要跑几十秒。这里最多两次批量查询搞定。

    比对口径刻意**保守**（宁可多判重也不要漏判）：
    - 新行有订单号 -> 与库内同平台同订单号比对；
    - 新行无订单号 -> 与库内同日期同金额同交易方比对（不看库内有没有订单号），
      因为时间+金额+对方三者一致时，几乎必然是同一笔，漏判会导致重复记账。
    """
    keys: set[str] = set()

    order_nos = sorted({(r.order_no or "").strip() for r in rows if (r.order_no or "").strip()})
    for chunk in _chunked(order_nos):
        have = db.scalars(
            select(BizExpense.order_no).where(
                BizExpense.owner_uid == identity.uid,
                BizExpense.platform == platform,
                BizExpense.order_no.in_(chunk),
            )
        ).all()
        keys.update(f"{platform}:{o}" for o in have if o)

    no_order = [r for r in rows if not (r.order_no or "").strip()]
    if no_order:
        dates = [r.txn_time for r in no_order if r.txn_time]
        if dates:
            lo, hi = min(dates), max(dates)
            existing = db.scalars(
                select(BizExpense).where(
                    BizExpense.owner_uid == identity.uid,
                    BizExpense.platform == platform,
                    BizExpense.occurred_on >= lo,
                    BizExpense.occurred_on <= hi,
                )
            ).all()
            for e in existing:
                amount = Decimal(str(e.amount or 0))
                keys.add(
                    bill_import.build_dedupe_key(
                        platform, "", e.occurred_on or "", amount, e.counterparty or ""
                    )
                )
                if (e.order_no or "").strip():
                    keys.add(f"{platform}:{e.order_no.strip()}")
    return keys


def _apply_duplicates(rows: list, db_keys: set[str]) -> None:
    """就地标记重复行。

    同时处理两种重复：与库内历史重复、以及在**本次文件内**前面已出现过的行
    （有些平台一次导出会带多行同一订单号，如分笔支付）。
    """
    seen: set[str] = set()
    for r in rows:
        if r.status != bill_import.STATUS_OK:
            continue
        if not r.dedupe_key:
            continue
        if r.dedupe_key in db_keys:
            r.status = bill_import.STATUS_DUPLICATE
            r.reason = "与已导入的历史记录重复，已跳过"
        elif r.dedupe_key in seen:
            r.status = bill_import.STATUS_DUPLICATE
            r.reason = "与本次文件中前面的某行重复，已跳过"
        else:
            seen.add(r.dedupe_key)


def _bill_preview_payload(result, rows: list) -> dict:
    summary = {
        "total": len(rows),
        "ok": sum(1 for r in rows if r.status == bill_import.STATUS_OK),
        "duplicate": sum(1 for r in rows if r.status == bill_import.STATUS_DUPLICATE),
        "skipped": sum(1 for r in rows if r.status == bill_import.STATUS_SKIPPED),
        "failed": sum(1 for r in rows if r.status == bill_import.STATUS_FAILED),
    }
    ok_rows = [r for r in rows if r.status == bill_import.STATUS_OK]
    return {
        "encoding": result.encoding,
        "platform": result.platform,
        "headerLine": result.header_line,
        "header": result.header_cells,
        "mapping": {k: (result.header_cells[v] if v < len(result.header_cells) else "") for k, v in result.mapping.items()},
        "summary": summary,
        "amountTotal": round(sum(float(r.amount or 0) for r in ok_rows), 2),
        "rows": [r.to_dto() for r in rows],
    }


def preview_bill_import(db: Session, identity: Identity, raw: bytes, file_name: str) -> dict:
    """解析账单并给出**预览**（不写库）。

    预览必须和正式导入走**同一套去重判定**，否则会出现「预览说能导入 100 条，
    提交后只进了 80 条」的信任崩塌。
    """
    result = bill_import.parse_bill(raw, file_name)
    db_keys = _existing_dedupe_keys(db, identity, result.platform, result.rows)
    _apply_duplicates(result.rows, db_keys)
    return _bill_preview_payload(result, result.rows)


def commit_bill_import(db: Session, identity: Identity, raw: bytes, file_name: str) -> dict:
    """解析 + 去重 + 写库 + 记录批次。

    重新解析一遍而不复用预览结果：用户可能在预览之后隔了很久才点导入，
    期间库内数据已变，复用旧判定会导入重复数据。
    """
    result = bill_import.parse_bill(raw, file_name)
    db_keys = _existing_dedupe_keys(db, identity, result.platform, result.rows)
    _apply_duplicates(result.rows, db_keys)

    ok_rows = [r for r in result.rows if r.status == bill_import.STATUS_OK]
    if not ok_rows:
        # 一条都导不进去时也要留下批次记录，用户在历史里能看到「为什么没导进来」
        payload = _bill_preview_payload(result, result.rows)
        payload["batchId"] = None
        payload["imported"] = 0
        return payload

    batch = BizExpenseImport(
        owner_uid=identity.uid,
        file_name=(file_name or "")[:255],
        platform=result.platform,
        encoding=result.encoding,
        total_rows=len(result.rows),
        imported_rows=len(ok_rows),
        duplicate_rows=sum(1 for r in result.rows if r.status == bill_import.STATUS_DUPLICATE),
        failed_rows=sum(1 for r in result.rows if r.status == bill_import.STATUS_FAILED),
        amount_total=Decimal(str(round(sum(float(r.amount or 0) for r in ok_rows), 2))),
    )
    db.add(batch)
    db.flush()  # 拿到 batch.id 供明细行引用

    for r in ok_rows:
        note_parts = [p for p in (r.note, r.raw.get("note") or "") if p]
        db.add(
            BizExpense(
                owner_uid=identity.uid,
                kind=r.direction,
                # 账单的「交易分类」直接当财务类别用：这样导入的数据能立刻
                # 落在现有财务图表（按类别分组）里，而不是全堆进「未分类」。
                category=(r.txn_type or "账单导入")[:64],
                amount=r.amount,
                occurred_on=r.txn_time,
                note=" / ".join(dict.fromkeys(note_parts))[:500],
                platform=result.platform,
                order_no=(r.order_no or "")[:64],
                counterparty=(r.counterparty or "")[:128],
                txn_type=(r.txn_type or "")[:64],
                payment_method=(r.payment_method or "")[:32],
                import_batch_id=batch.id,
            )
        )
    db.commit()
    db.refresh(batch)

    payload = _bill_preview_payload(result, result.rows)
    payload["batchId"] = batch.id
    payload["imported"] = len(ok_rows)
    return payload


def list_bill_imports(db: Session, identity: Identity) -> list[dict]:
    rows = db.scalars(
        select(BizExpenseImport)
        .where(BizExpenseImport.owner_uid == identity.uid)
        .order_by(BizExpenseImport.created_at.desc())
    ).all()
    return [
        {
            "id": b.id,
            "fileName": b.file_name,
            "platform": b.platform,
            "encoding": b.encoding,
            "totalRows": b.total_rows,
            "importedRows": b.imported_rows,
            "duplicateRows": b.duplicate_rows,
            "failedRows": b.failed_rows,
            "amountTotal": float(b.amount_total or 0),
            "createdAt": b.created_at.isoformat() if b.created_at else "",
        }
        for b in rows
    ]


def delete_bill_import(db: Session, identity: Identity, batch_id: int) -> dict:
    """按批次撤销导入：删掉该批次导入的全部流水 + 批次记录本身。

    误导入整个文件时不能让用户去逐条删。
    """
    batch = db.scalar(
        select(BizExpenseImport).where(
            BizExpenseImport.id == batch_id, BizExpenseImport.owner_uid == identity.uid
        )
    )
    if batch is None:
        raise not_found("导入批次", batch_id)
    removed = db.query(BizExpense).filter(
        BizExpense.owner_uid == identity.uid, BizExpense.import_batch_id == batch_id
    ).delete(synchronize_session=False)
    db.delete(batch)
    db.commit()
    return {"id": batch_id, "removed": removed}


# ================================================================ 收支趋势与导出（v1.0.34）


def list_payment_methods(db: Session, identity: Identity) -> list[str]:
    """已用过的支付方式清单（供前端筛选下拉）。

    必须**独立于当前筛选**返回全集：若从筛选后的列表里取 distinct，
    用户选了「零钱」之后下拉就只剩「零钱」，再也切不回去。
    """
    rows = db.scalars(
        select(BizExpense.payment_method)
        .where(BizExpense.owner_uid == identity.uid, BizExpense.payment_method != "")
        .distinct()
        .order_by(BizExpense.payment_method)
    ).all()
    return [r for r in rows if r]


def expense_trend(
    db: Session,
    identity: Identity,
    granularity: str = "month",
    date_from: str = "",
    date_to: str = "",
    kind: str = "",
) -> dict:
    """按日/月聚合收支趋势。

    只做**一次分组查询**（按 bucket + kind 求和），在内存里合成收入/支出两列，
    而不是分别查两次 —— 账单动辄几千行，少一次全表扫描在 NAS 上是实打实的差距。

    occurred_on 存的是 YYYY-MM-DD 字符串，按月聚合直接取前 7 位，
    比转日期再截断便宜，且 SQLite 与 PostgreSQL 行为一致。
    """
    gran = "day" if granularity == "day" else "month"
    bucket_expr = (
        func.substr(BizExpense.occurred_on, 1, 7) if gran == "month" else BizExpense.occurred_on
    ).label("bucket")

    stmt = select(
        bucket_expr, BizExpense.kind, func.sum(BizExpense.amount).label("total")
    ).where(BizExpense.owner_uid == identity.uid, BizExpense.occurred_on != "")
    if kind in constants.EXPENSE_KIND_CODES:
        stmt = stmt.where(BizExpense.kind == kind)
    if date_from:
        stmt = stmt.where(BizExpense.occurred_on >= _norm_date(date_from, "开始日期"))
    if date_to:
        stmt = stmt.where(BizExpense.occurred_on <= _norm_date(date_to, "结束日期"))
    stmt = stmt.group_by(bucket_expr, BizExpense.kind).order_by(bucket_expr)

    agg: dict[str, dict[str, float]] = {}
    for bucket, k, total in db.execute(stmt).all():
        if not bucket:
            continue
        item = agg.setdefault(str(bucket), {"income": 0.0, "expense": 0.0})
        if k == "income":
            item["income"] += float(total or 0)
        else:
            item["expense"] += float(total or 0)

    buckets = []
    for key in sorted(agg):
        v = agg[key]
        if gran == "month" and len(key) >= 7:
            label = f"{key[:4]}年{int(key[5:7])}月"
        else:
            label = key
        buckets.append(
            {
                "key": key,
                "label": label,
                "income": round(v["income"], 2),
                "expense": round(v["expense"], 2),
                "net": round(v["income"] - v["expense"], 2),
            }
        )
    return {"granularity": gran, "buckets": buckets}


def export_expenses_xlsx(
    db: Session,
    identity: Identity,
    kind: str = "",
    customer_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    counterparty: str = "",
    payment_method: str = "",
) -> tuple[bytes, str]:
    """按当前筛选条件导出财务流水为 XLSX。

    导出**复用与列表完全相同的筛选逻辑**（直接调 list_expenses），
    否则会出现「屏幕上看到 10 条、导出 20 条」这类信任问题。

    返回 (文件字节, 建议文件名)。
    """
    # 延迟导入：openpyxl 只在真正导出时才需要，不该拖慢应用启动
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    items = list_expenses(db, identity, kind, customer_id, date_from, date_to, counterparty, payment_method)

    # 关联客户名：一次性查出，避免逐行查库
    names: dict[int, str] = {}
    if items:
        ids = [x["customerId"] for x in items if x.get("customerId")]
        if ids:
            rows = db.scalars(
                select(BizCustomer).where(
                    BizCustomer.owner_uid == identity.uid, BizCustomer.id.in_(ids)
                )
            ).all()
            names = {c.id: c.name for c in rows}

    wb = Workbook()
    ws = wb.active
    ws.title = "财务流水"

    headers = [
        "日期",
        "类型",
        "类别",
        "交易方",
        "关联客户",
        "支付方式",
        "金额",
        "订单号",
        "来源平台",
        "备注",
    ]
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="4C6FFF")
    for col, name in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r, it in enumerate(items, start=2):
        ws.cell(row=r, column=1, value=it.get("occurredOn", ""))
        ws.cell(row=r, column=2, value="收入" if it.get("kind") == "income" else "支出")
        ws.cell(row=r, column=3, value=it.get("category") or "未分类")
        ws.cell(row=r, column=4, value=it.get("counterparty") or "")
        ws.cell(row=r, column=5, value=names.get(it.get("customerId") or 0, ""))
        ws.cell(row=r, column=6, value=it.get("paymentMethod") or "")
        amt = ws.cell(row=r, column=7, value=float(it.get("amount") or 0))
        amt.number_format = "#,##0.00"
        ws.cell(row=r, column=8, value=it.get("orderNo") or "")
        ws.cell(row=r, column=9, value=constants.BILL_PLATFORM_LABELS.get(it.get("platform", ""), ""))
        ws.cell(row=r, column=10, value=it.get("note") or "")

    widths = [12, 6, 12, 20, 16, 14, 12, 22, 10, 30]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    stamp = _today().replace("-", "")
    return buf.getvalue(), f"财务流水_{stamp}.xlsx"
