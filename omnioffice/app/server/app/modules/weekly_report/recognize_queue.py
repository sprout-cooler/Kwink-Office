"""识别队列：进程内线程池 + 进度广播。

设计（V10 4.x 阶段一）：
- pending 截图入队 → worker 按序取一张 → VLM 调用 → 写库 + 广播进度；
- 并发度由 RECOGNIZE_WORKERS 控制（VLM 单张 RT 长，并发摊总耗时）；
- 无 Key 时入队即失败并给出可操作错误，不静默堆积；
- 真机单容器部署阶段用进程内队列；后续若需横向扩容再换 Redis Stream，
  接口（enqueue / subscribe / get_progress）保持不动。
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any

from sqlalchemy import select

from ...core import audit
from ...core.config import settings
from ...db.models import BizCustomer, Screenshot, TaskItem
from ...db.session import SessionLocal
from .customer_link import (
    MATCH_MATCHED,
    MATCH_NONE,
    match_customer,
)
from .dateparse import DateParseError, normalize_task
from .vlm import RecognizeError, build_recognizer

# 本模块 id：用于解析该模块的 AI 覆盖配置（ai.weekly_report.*）
MODULE_ID = "weekly_report"

# 广播事件：{type, screenshotId, status, done, total, error}
_subscribers: set[asyncio.Queue] = set()
_subscribers_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None

_jobs: "queue.Queue[int | None]" = queue.Queue()
_workers: list[threading.Thread] = []
# 当前批次的进度计数（简单内存态，够用；重启后按库中状态重建）
_pending_ids: set[int] = set()
_pending_lock = threading.Lock()
# 每个任务所属的账号隔离键 —— AI 配置按账号独立，worker 必须知道这张图是谁的。
# 之前这里直接 build_recognizer(MODULE_ID) 不带 owner，多账号下会用错 Key。
_job_owners: dict[int, str] = {}


def attach_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _subscribers_lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    with _subscribers_lock:
        _subscribers.discard(q)


def _broadcast(event: dict[str, Any]) -> None:
    with _subscribers_lock:
        for q in _subscribers:
            try:
                if _loop is not None:
                    _loop.call_soon_threadsafe(q.put_nowait, event)
                else:
                    q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 慢消费者丢帧：下一条状态会覆盖，不影响最终一致性


def ensure_workers() -> None:
    """按配置的并发数拉起 worker 线程。

    并发数取「DB 应用配置 → 环境变量 → 3」的生效值；设置页改并发后需重启生效
    （线程数不宜运行期伸缩），但 AI Key / 模型改完立即生效（每张图重新解析）。
    """
    if _workers:
        return
    n = _resolve_workers()
    for i in range(n):
        t = threading.Thread(target=_worker_loop, name=f"recognizer-{i}", daemon=True)
        t.start()
        _workers.append(t)


def _resolve_workers() -> int:
    """生效并发数：app.recognize_workers（DB）> 环境变量 > 3。"""
    try:
        from ...core.settings_service import get_app_settings

        db = SessionLocal()
        try:
            return int(get_app_settings(db)["recognize_workers"]["value"])
        finally:
            db.close()
    except Exception:
        return max(1, int(settings.recognize_workers or 3))


def stop_workers() -> None:
    for _ in _workers:
        _jobs.put(None)


def enqueue(screenshot_ids: list[int], owner: str = "") -> int:
    """入队 pending 截图；返回实际入队数。

    owner 为该批截图所属账号的数据归属键，worker 据此取该账号自己的 AI 配置。
    """
    with _pending_lock:
        new_ids = [sid for sid in screenshot_ids if sid not in _pending_ids]
        _pending_ids.update(new_ids)
        for sid in new_ids:
            _job_owners[sid] = owner
    for sid in new_ids:
        _jobs.put(sid)
    return len(new_ids)


def _worker_loop() -> None:  # 独立线程：每张图用新会话，互不串扰
    while True:
        sid = _jobs.get()
        if sid is None:
            return
        try:
            _process_one(sid)
        except Exception as e:  # 兜底：任何意外不能杀掉 worker
            _mark_failed(sid, f"识别过程异常：{type(e).__name__}: {e}")
        finally:
            with _pending_lock:
                _pending_ids.discard(sid)
                _job_owners.pop(sid, None)


def _customer_names(db, owner_uid: str, limit: int = 100) -> list[str]:
    """取本账号客户名清单（注入识别提示词）。

    只取**同账号**的客户 —— 客户数据是账号隔离的，跨账号取会把
    A 账号的客户名泄漏到 B 账号的识别提示词里（既是数据泄露也是误配来源）。
    """
    try:
        stmt = (
            select(BizCustomer.name)
            .where(BizCustomer.owner_uid == owner_uid)
            .order_by(BizCustomer.updated_at.desc())
            .limit(limit)
        )
        return [n for n in db.scalars(stmt).all() if n]
    except Exception:  # noqa: BLE001 —— 取不到客户名不该让识别失败
        return []


def _customer_candidates(db, owner_uid: str) -> list[tuple[int, str]]:
    """本账号全部客户 (id, name) —— 用于把 AI 给的客户名匹配到具体客户。

    取全量（不截断）：匹配必须看全，否则同名歧义会被误判为唯一命中。
    """
    try:
        stmt = select(BizCustomer.id, BizCustomer.name).where(
            BizCustomer.owner_uid == owner_uid
        )
        return [(cid, name) for cid, name in db.execute(stmt).all() if name]
    except Exception:  # noqa: BLE001 —— 取不到就不做自动关联
        return []


def _mark_customer_source_weekly(db, owner_uid: str, customer_ids: set[int]) -> int:
    """给被周报关联到的客户自动填「来源=周报关联」（**只填空不覆盖**）。

    优先级：客户来源是**业务判断**，人工选择永远优先。
    只有 source 为空（用户从没选过）时才写入自动值。

    返回实际更新条数。
    """
    from ..biz_dashboard import constants as biz_constants

    if not customer_ids:
        return 0
    try:
        rows = (
            db.query(BizCustomer)
            .filter(BizCustomer.owner_uid == owner_uid)
            .filter(BizCustomer.id.in_(customer_ids))
            .all()
        )
        changed = 0
        for r in rows:
            if not r.source:
                r.source = biz_constants.CUSTOMER_SOURCE_AUTO
                changed += 1
        if changed:
            db.commit()
        return changed
    except Exception:  # noqa: BLE001 —— 来源自动填充失败不该让识别整体失败
        db.rollback()
        return 0


def _process_one(sid: int) -> None:
    db = SessionLocal()
    try:
        shot = db.get(Screenshot, sid)
        if shot is None:
            return
        uid = shot.owner_uid
        if shot.recognize_status != "pending":
            return

        # 每张图重新解析配置：设置页改完 Key/模型立即生效，无需重启
        recognizer = build_recognizer(MODULE_ID, owner=uid)
        if recognizer is None:
            _fail_locked(
                db, shot, uid,
                "未配置识别服务：请在「设置 → 应用配置 → AI 模型」中填写 API Key",
            )
            return

        shot.recognize_status = "processing"
        db.commit()
        _broadcast({"type": "progress", "screenshotId": sid, "uid": uid, "status": "processing"})

        # 取本账号客户名清单注入提示词 —— 让模型在名单内「指认」客户，
        # 而不是自由抽取（自由抽取会产出「XX科技公司」这类变体，匹配必然失败）。
        customer_names = _customer_names(db, uid)

        try:
            result = asyncio.run(recognizer.recognize(shot.stored_path, customer_names))
        except RecognizeError as e:
            _fail_locked(db, shot, uid, str(e))
            return
        except Exception as e:
            _fail_locked(db, shot, uid, f"识别服务调用失败：{type(e).__name__}: {e}")
            return

        # 企微一周小结：不产生任务条目，指标（413 次工作会话等）写 Setting
        # （周报汇总「线上售后数量」按会话量填，不是任务条数）。
        ws = result.get("wechat_summary")
        if result.get("type") == "wechat_summary" and ws:
            from .wechat_metrics import save_summary

            save_summary(
                db,
                shot.report_id,
                ws.get("session_count"),
                minutes=ws.get("total_minutes"),
                latest_time=ws.get("latest_time", ""),
                period_text=ws.get("period_text", ""),
                source="ai",
            )
            shot.recognize_status = "done"
            shot.recognize_error = ""
            db.commit()
            audit.log(
                "recognize.wechat_summary",
                uid,
                {"screenshotId": sid, "sessions": ws.get("session_count")},
            )
            _broadcast(
                {
                    "type": "progress",
                    "screenshotId": sid,
                    "uid": uid,
                    "status": "done",
                    "tasks": 0,
                    "wechatSessions": ws.get("session_count"),
                }
            )
            return

        # 清掉该图旧任务（重试场景），重新写入
        db.query(TaskItem).filter(TaskItem.screenshot_id == sid).delete()
        report_period = shot.report.period_start
        created = 0
        # 客户候选（匹配用）。取全量以正确识别同名歧义。
        candidates = _customer_candidates(db, uid)
        linked_customers: set[int] = set()
        for t in result.get("tasks", []):
            raw_start = t.get("start_time") or ""
            raw_end = t.get("end_time") or ""
            extra: dict[str, Any] = {"status_raw": t.get("status") or "", "warnings": []}
            # ---- 客户关联（周报 → 客户）----
            # AI 给的客户名做「指认后匹配」：唯一命中才自动关联；
            # 同名多条标 ambiguous 交人工；匹配不到标 none（**不自动建客户**）。
            cust_raw = str(t.get("customer") or "").strip()
            if cust_raw:
                cm = match_customer(cust_raw, candidates)
                extra["customer_name"] = cm.customer_name
                extra["customer_match"] = cm.match
                if cm.match == MATCH_MATCHED and cm.customer_id is not None:
                    extra["customer_id"] = cm.customer_id
                    linked_customers.add(cm.customer_id)
                elif cm.match == "ambiguous":
                    extra["customer_ambiguous_ids"] = list(cm.ambiguous_ids)
            if raw_start:
                try:
                    norm = normalize_task(raw_start, raw_end, period_start=report_period)
                    start_at, end_at = norm.start_at, norm.end_at
                    weekday = norm.weekday
                    extra["warnings"] = norm.warnings
                    extra["out_of_period"] = norm.out_of_period
                except DateParseError as e:
                    # 解析失败保留原文，校对界面标红人工处理（V10：绝不猜测）
                    start_at = end_at = ""
                    weekday = 0
                    extra["warnings"] = ["DATE_PARSE_FAILED"]
                    extra["parse_error"] = str(e)
                    extra["start_raw"] = raw_start
                    extra["end_raw"] = raw_end
            else:
                start_at = end_at = ""
                weekday = 0
                extra["warnings"] = ["START_TIME_MISSING"]

            db.add(
                TaskItem(
                    screenshot_id=sid,
                    owner_uid=shot.owner_uid,
                    partition=shot.partition,
                    title=t["title"],
                    start_at=start_at,
                    end_at=end_at,
                    raw_status=t.get("status") or "",
                    confidence=t.get("confidence") or 0.0,
                    weekday=weekday,
                    extra=extra,
                )
            )
            created += 1

        # ---- 反向写入：客户来源「周报关联」----
        # 只填空、**不覆盖**：客户来源是业务判断（这客户怎么来的），
        # 周报只提供「该客户在周报里出现过」这一弱信号，不足以推翻人工选择。
        if linked_customers:
            _mark_customer_source_weekly(db, uid, linked_customers)

        shot.recognize_status = "done"
        shot.recognize_error = ""
        db.commit()
        audit.log("recognize.done", uid, {"screenshotId": sid, "tasks": created})
        _broadcast(
            {
                "type": "progress",
                "screenshotId": sid,
                "uid": uid,
                "status": "done",
                "tasks": created,
            }
        )
    finally:
        db.close()


def _mark_failed(sid: int, message: str) -> None:
    db = SessionLocal()
    try:
        shot = db.get(Screenshot, sid)
        if shot is not None:
            _fail_locked(db, shot, shot.owner_uid, message)
    finally:
        db.close()


def _fail_locked(db, shot: Screenshot, uid: str, message: str) -> None:
    shot.recognize_status = "failed"
    shot.recognize_error = message[:500]
    db.commit()
    audit.log("recognize.failed", uid, {"screenshotId": shot.id, "error": message[:200]})
    _broadcast(
        {"type": "progress", "screenshotId": shot.id, "uid": uid, "status": "failed", "error": message[:200]}
    )


def retry_failed(db, uid: str) -> list[int]:
    """重试当前用户全部 failed 截图：重置为 pending 并入队。"""
    failed = list(
        db.scalars(
            select(Screenshot).where(
                Screenshot.owner_uid == uid, Screenshot.recognize_status == "failed"
            )
        )
    )
    ids = []
    for shot in failed:
        shot.recognize_status = "pending"
        shot.recognize_error = ""
        ids.append(shot.id)
    db.commit()
    return ids
