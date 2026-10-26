"""数据大屏路由。

异常契约（与全项目一致）：
    成功 → 业务 DTO
    失败 → {"detail": {"error": "<CODE>", "message": "<可行动中文提示>", ...}}

本文件是**唯一**把 BizDashboardError 翻译成 HTTP 的地方。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...core.identity import Identity, get_identity
from ...db.deps import get_db
from . import constants, geo, service
from .errors import BizDashboardError

router = APIRouter()


def _require_identity(identity: Identity | None = Depends(get_identity)) -> Identity:
    if identity is None:
        raise HTTPException(
            status_code=401, detail={"error": "UNAUTHORIZED", "message": "未识别到网关身份"}
        )
    return identity


def _guard(fn, *args, **kwargs):
    """统一异常翻译：BizDashboardError → 对应 HTTP 响应。

    只捕获 BizDashboardError，未预期异常必须冒泡到 main.py 的全局处理器。
    """
    try:
        return fn(*args, **kwargs)
    except BizDashboardError as e:
        raise HTTPException(status_code=e.status, detail=e.to_payload()["detail"]) from None


# ------------------------------------------------------------------ 能力清单


@router.get("/capabilities")
def capabilities(identity: Identity = Depends(_require_identity)):
    """能力清单：前端下拉全由此驱动，新增分类前端零改动。"""
    return constants.capabilities()


# ------------------------------------------------------------------ 总览


@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """大屏首屏 KPI：客户/出差/财务/工作量汇总。"""
    return _guard(service.dashboard_overview, db, identity)


# ------------------------------------------------------------------ 客户


@router.get("/customers")
def list_customers(
    keyword: str = "",
    source: str = "",
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return {"items": _guard(service.list_customers, db, identity, keyword, source)}


@router.post("/customers")
def create_customer(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.create_customer, db, identity, body or {})


@router.patch("/customers/{cid}")
def update_customer(
    cid: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.update_customer, db, identity, cid, body or {})


@router.delete("/customers/{cid}")
def delete_customer(
    cid: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.delete_customer, db, identity, cid)


# ------------------------------------------------------------------ 出差


@router.get("/trips")
def list_trips(
    status: str = "",
    customer_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return {"items": _guard(service.list_trips, db, identity, status, customer_id)}


@router.post("/trips")
def create_trip(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.create_trip, db, identity, body or {})


@router.patch("/trips/{tid}")
def update_trip(
    tid: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.update_trip, db, identity, tid, body or {})


@router.delete("/trips/{tid}")
def delete_trip(
    tid: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.delete_trip, db, identity, tid)


# ------------------------------------------------------------------ 财务


@router.get("/expenses")
def list_expenses(
    kind: str = "",
    customer_id: int | None = Query(default=None),
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return {
        "items": _guard(
            service.list_expenses, db, identity, kind, customer_id, date_from, date_to
        )
    }


@router.post("/expenses")
def create_expense(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.create_expense, db, identity, body or {})


@router.patch("/expenses/{eid}")
def update_expense(
    eid: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.update_expense, db, identity, eid, body or {})


@router.delete("/expenses/{eid}")
def delete_expense(
    eid: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.delete_expense, db, identity, eid)


# ------------------------------------------------------------------ 工时台账


@router.get("/time-entries")
def list_time_entries(
    customer_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return {"items": _guard(service.list_time_entries, db, identity, customer_id)}


@router.post("/time-entries")
def create_time_entry(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.create_time_entry, db, identity, body or {})


@router.patch("/time-entries/{tid}")
def update_time_entry(
    tid: int,
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.update_time_entry, db, identity, tid, body or {})


@router.delete("/time-entries/{tid}")
def delete_time_entry(
    tid: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    return _guard(service.delete_time_entry, db, identity, tid)


# ------------------------------------------------------------------ 工作量


@router.get("/workload")
def workload(
    granularity: str = "month",
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """工作量聚合：周报工时（只读）+ 独立台账，双口径合并。"""
    return _guard(service.workload_overview, db, identity, granularity)


# ------------------------------------------------------------------ 地图


@router.get("/map/key-status")
def map_key_status(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """地图 Key 配置状态：**只回是否已配置，绝不回明文**。"""
    return {"configured": _guard(geo.has_map_key, db, identity.uid)}


@router.put("/map/key")
def save_map_key(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """保存腾讯地图 Key（存服务端，前端不落明文）。空字符串 = 清除。"""
    key = (body or {}).get("key") or ""
    _guard(geo.set_map_key, db, identity.uid, key)
    db.commit()
    return {"ok": True, "configured": bool((key or "").strip())}


@router.get("/map/proxy")
def map_proxy(
    q: str = "",
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """腾讯地图 WebService 反代。

    前端 SDK 按官方「Key 代理」模式把请求打到这里，
    服务端注入托管的 Key —— 前端 JS 与网络面板都看不到明文 key。
    """
    return _guard(geo.proxy_ws, db, identity.uid, q)


@router.get("/map/geocode")
def geocode(
    address: str = "",
    city: str = "",
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """地址 → 经纬度（地理编码）。"""
    return _guard(geo.geocode, db, identity.uid, address, city)


# ------------------------------------------------------------------ 分享


@router.get("/shares")
def list_shares(
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """我创建的分享列表（不返回 token —— 明文只在创建时给一次）。"""
    return {"items": _guard(service.list_shares, db, identity)}


@router.post("/shares")
def create_share(
    body: dict,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """创建分享链接。**明文 token 仅此一次返回**，请立即复制。"""
    return _guard(service.create_share, db, identity, body or {})


@router.delete("/shares/{sid}")
def revoke_share(
    sid: int,
    db: Session = Depends(get_db),
    identity: Identity = Depends(_require_identity),
):
    """撤销分享：立即失效。"""
    return _guard(service.revoke_share, db, identity, sid)


@router.get("/shares/public/{token}")
def read_share(
    token: str,
    db: Session = Depends(get_db),
):
    """按令牌读取分享内容。

    ⚠️ 本接口**不要求登录** —— 接收者可能不是本 NAS 用户。
    只能读到创建者显式勾选的记录，且受有效期与撤销状态约束。
    """
    return _guard(service.read_share, db, token)
