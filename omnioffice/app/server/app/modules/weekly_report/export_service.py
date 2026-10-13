"""模板版本管理与导出编排（V10 4.5 / 3.6）。

职责：
- 模板入库：上传 xlsx → 校验锚点结构 → 落 data/templates/ → 登记版本；
- 版本绑定：周报批次绑定具体模板版本（历史可追溯，不用最新模板）；
- 导出编排：填充 → 落共享目录 → LibreOffice 渲染区域截图 → 登记产物。

导出链路的两个关键约束（V10 4.3 / 8.10）：
1. **临时打印区域必须清理**：渲染完要把 print_area 还原，否则污染模板副本；
   更稳妥的做法是「渲染专用副本」，原模板文件永不改动。
2. **LibreOffice 并发上限 2**：转换是 CPU 尖峰，并发过高会拖垮 NAS（M0 S8 资源基线），
   用信号量限流而非依赖 docker compose 之外的东西。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Sequence

from fastapi import HTTPException, UploadFile
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...core import audit
from ...core.config import settings
from ...core.identity import Identity
from ...db.models import ExportArtifact, Report, TemplateVersion
from .anchors import DEFAULT_ANCHORS, AnchorError, validate_template
from .fill import FillItem, fill_weekly_report

# 模板与产物的允许大小（模板是结构化表格，不该超过 10MB）
MAX_TEMPLATE_MB = 10
# LibreOffice 并发上限（V10 4.3：转换设单机并发上限，避免 CPU 尖峰拖垮 API）
RENDER_CONCURRENCY = int(os.environ.get("RENDER_CONCURRENCY", "2"))
_render_sem = threading.Semaphore(max(1, RENDER_CONCURRENCY))

# 截图参数
PNG_DPI = 192          # V10：≥192DPI（2 倍缩放可读）
SOFFICE_TIMEOUT = 120  # 单次转换超时（秒）


# ---------------------------------------------------------------- 路径与命名


def _ensure_dir(p: Path, what: str) -> Path:
    """确保目录存在，失败时给出**可行动**的报错而不是裸 OSError。

    真机上 DATA_DIR 指向fnOS 共享目录（compose: ${TRIM_APPDEST}/share:/data）。
    该目录若未创建、权限不足、或磁盘已满，mkdir 会抛 OSError —— 此前直接冒泡
    成 500 且日志无堆栈，用户只能看到「导出失败」。这里补上明确原因与修复指引，
    并把实况写进真机诊断日志。
    """
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        detail = (
            f"目录: {p}\n目标: {what}\nDATA_DIR: {settings.data_dir}\n"
            f"错误: {type(e).__name__}: {e}\n"
            f"当前 uid: {_diag_uid()}"
        )
        print(f"[export] 目录创建失败 {p}: {type(e).__name__}: {e}", flush=True)
        _diag_trace(f"导出失败 · {what}目录创建失败", detail)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "STORAGE_UNAVAILABLE",
                "message": f"{what}目录不可用（{type(e).__name__}: {e}）。"
                           f"请检查共享目录 {settings.data_dir} 是否存在、容器是否有写权限、磁盘空间是否充足",
                "diagLog": _diag_path(),
            },
        ) from None
    # mkdir 成功不等于可写（只读挂载 / 配额满）；再探一次
    try:
        probe = p / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as e:
        detail = f"目录: {p}\n错误: {type(e).__name__}: {e}\n当前 uid: {_diag_uid()}"
        print(f"[export] 目录不可写 {p}: {type(e).__name__}: {e}", flush=True)
        _diag_trace(f"导出失败 · {what}目录不可写", detail)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "STORAGE_READONLY",
                "message": f"{what}目录只读或空间不足（{type(e).__name__}: {e}）。"
                           f"请检查 {settings.data_dir} 的挂载权限与剩余空间",
                "diagLog": _diag_path(),
            },
        ) from None
    return p


def _diag_uid() -> str:
    try:
        return str(os.getuid())
    except Exception:  # noqa: BLE001
        return "?"


def templates_root() -> Path:
    return _ensure_dir(Path(settings.data_dir) / "templates", "模板")


def exports_root(uid: str) -> Path:
    """导出根目录：data/exports/<uid>/。真机上 DATA_DIR 指向共享目录，文件管理器可见。"""
    return _ensure_dir(Path(settings.data_dir) / "exports" / uid, "导出产物")


def _safe_name(s: str, fallback: str = "周报") -> str:
    """文件名安全化。

    两道处理，缺一不可：
    1. 替换非法字符（含路径分隔符 / : * ? " < > | 与控制字符）；
    2. **剥掉 `..` 序列** —— 只替换斜杠的话，`../../etc/passwd` 会变成
       `_.._etc_passwd`，`..` 仍在。虽然产物目录由服务端固定拼接、不至于穿越，
       但留着 `..` 的文件名在文件管理器 / WebDAV 场景下容易引发误解与兼容问题。
    """
    bad = '<>:"/\\|?*\n\r\t'
    out = "".join("_" if ch in bad else ch for ch in (s or "").strip())
    # 反复剥离，防止 `....` 这类多重绕过
    while ".." in out:
        out = out.replace("..", "")
    out = out.strip(". ")
    # 纯符号（全是替换出来的 "_"）视为无效名，回落到默认 ——
    # 否则会产出一串无意义的 "___.xlsx"。
    if not out.strip("_"):
        return fallback
    return out[:80] or fallback


def report_display_name(username: str, period_start: str) -> str:
    """产物命名：周报_<姓名>_<起-止>（V10：两产物成对产出、命名一致）。"""
    from datetime import date as _date

    start = _date.fromisoformat(period_start)
    end = (start + timedelta(days=6)).isoformat()
    return f"周报_{_safe_name(username)}_{start.isoformat()}_{end}"


# ---------------------------------------------------------------- 模板入库


def _template_dto(t: TemplateVersion) -> dict:
    return {
        "id": t.id,
        "filename": t.filename,
        "version": t.version,
        "size": t.size,
        "anchorOk": bool(t.anchor_ok),
        "note": t.note,
        "createdAt": t.created_at.isoformat() if t.created_at else None,
    }


async def upload_template(
    db: Session, identity: Identity, file: UploadFile, note: str = ""
) -> dict:
    """上传模板：校验结构 → 落盘 → 登记版本。

    结构不符直接 400 阻断 —— 导入一个填充不了的模板只会把问题推迟到导出那一刻，
    那时用户已经准备好周报了，返工成本高得多。
    """
    name = file.filename or "template.xlsx"
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail={"error": "BAD_TEMPLATE_TYPE", "message": "仅支持 .xlsx 模板（.xls 需另存为 .xlsx）"},
        )
    data = await file.read()
    if len(data) > MAX_TEMPLATE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail={"error": "TEMPLATE_TOO_LARGE", "message": f"模板超过 {MAX_TEMPLATE_MB}MB"},
        )
    if not data:
        raise HTTPException(status_code=400, detail={"error": "EMPTY_FILE", "message": "模板文件为空"})

    # 结构校验（用临时文件，不污染模板目录）
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
        tf.write(data)
        tmp = Path(tf.name)
    sheet_name = ""
    try:
        try:
            wb = load_workbook(tmp)
            validate_template(wb[wb.sheetnames[0]])
            sheet_name = wb.sheetnames[0]
        except AnchorError as e:
            raise HTTPException(
                status_code=400,
                detail={"error": "ANCHOR_MISMATCH", "message": f"模板结构不符合周报模板要求：{e}"},
            ) from None
        except HTTPException:
            # 上面刚抛的 HTTPException 必须原样透传 —— 若被下面的
            # except Exception 捕获，用户会拿到「BAD_XLSX 无法解析文件」，
            # 完全丢失「结构不符」这个真正的原因（曾因此误判过一次）。
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail={"error": "BAD_XLSX", "message": f"无法解析该 xlsx 文件：{type(e).__name__}"},
            ) from None
    finally:
        tmp.unlink(missing_ok=True)

    # ---- 结构校验通过后才入库 ----
    # 注意：以下代码必须在 try/finally 之外（缩进 4 空格）。
    # 曾误缩进到 finally 块里，导致「校验失败」被 finally 的执行时机掩盖，
    # 结构不符的模板也能成功入库（anchorOk 却是 True），是严重的静默错误。
    md5 = hashlib.md5(data).hexdigest()
    existing = db.scalar(
        select(TemplateVersion).where(
            TemplateVersion.owner_uid == identity.uid, TemplateVersion.md5 == md5
        )
    )
    if existing is not None:
        return {"template": _template_dto(existing), "duplicated": True, "sheet": sheet_name}

    # 版本号 = 该用户已有模板数 + 1（同一 md5 已去重，不会撞号）
    count = len(
        list(db.scalars(select(TemplateVersion).where(TemplateVersion.owner_uid == identity.uid)))
    )
    stored = templates_root() / f"{md5}.xlsx"
    if not stored.exists():
        stored.write_bytes(data)

    row = TemplateVersion(
        owner_uid=identity.uid,
        filename=_safe_name(name, "template.xlsx"),
        stored_path=str(stored),
        md5=md5,
        size=len(data),
        version=count + 1,
        anchor_ok=1,
        note=note[:255],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log(
        "template.upload",
        identity.uid,
        {"id": row.id, "version": row.version, "size": row.size, "md5": md5[:8]},
    )
    return {"template": _template_dto(row), "duplicated": False, "sheet": sheet_name}


def list_templates(db: Session, identity: Identity) -> list[dict]:
    rows = db.scalars(
        select(TemplateVersion)
        .where(TemplateVersion.owner_uid == identity.uid)
        .order_by(TemplateVersion.version.desc())
    )
    return [_template_dto(t) for t in rows]


def _owned_template(db: Session, identity: Identity, template_id: int) -> TemplateVersion:
    t = db.get(TemplateVersion, template_id)
    if t is None or t.owner_uid != identity.uid:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "模板不存在"})
    return t


def get_template(db: Session, identity: Identity, template_id: int) -> TemplateVersion:
    return _owned_template(db, identity, template_id)


def latest_template(db: Session, identity: Identity) -> TemplateVersion | None:
    return db.scalar(
        select(TemplateVersion)
        .where(TemplateVersion.owner_uid == identity.uid)
        .order_by(TemplateVersion.version.desc())
        .limit(1)
    )


def delete_template(db: Session, identity: Identity, template_id: int) -> None:
    t = _owned_template(db, identity, template_id)
    # 若有周报批次仍绑定该版本，禁止删除（否则历史周报无法再导出）
    bound = db.scalar(
        select(Report).where(Report.owner_uid == identity.uid, Report.template_id == template_id).limit(1)
    )
    if bound is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "TEMPLATE_IN_USE",
                "message": f"已有周报批次绑定该模板（批次 #{bound.id}），请先改绑其他模板再删除",
            },
        )
    db.delete(t)
    db.commit()
    audit.log("template.delete", identity.uid, {"id": template_id})


def bind_template(db: Session, identity: Identity, report: Report, template_id: int) -> dict:
    """把模板版本绑定到周报批次（可改绑，确认后生效）。"""
    t = _owned_template(db, identity, template_id)
    report.template_id = t.id
    db.commit()
    audit.log("template.bind", identity.uid, {"reportId": report.id, "templateId": t.id})
    return {"reportId": report.id, "template": _template_dto(t)}


def resolve_template(db: Session, identity: Identity, report: Report) -> TemplateVersion:
    """解析导出该用的模板：优先批次绑定版本，其次该用户最新版本。

    两种「记录与文件不同步」都要自愈（v1.0.17）：
      - DB 有记录、文件没了 → `_assert_template_file()` 从目录找回；
      - DB 记录没了、文件还在 → `_rebuild_template_record()` 用目录里的文件重建记录。
    两者都不成立才报错（此时用户确实需要重新上传）。
    """
    if report.template_id:
        tpl = _owned_template(db, identity, report.template_id)
    else:
        tpl = latest_template(db, identity)
        if tpl is None:
            # 记录没了但磁盘上可能还有 —— 先试着重建，别让用户白填一周周报
            tpl = _rebuild_template_record(db, identity)
        if tpl is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "NO_TEMPLATE",
                    "message": "尚未上传周报模板 —— 请先在「预览与导出」页上传模板文件",
                },
            )
    _assert_template_file(db, tpl)
    return tpl


def _rebuild_template_record(db: Session, identity: Identity) -> TemplateVersion | None:
    """DB 无模板记录、但模板目录里还有可用xlsx 时，重建记录并返回。

    典型场景：清理脚本清了 DB、或容器重建后记录丢失，但共享目录里的模板文件还在。
    没有这一步，用户会看到「尚未上传模板」，而他明明上传过。
    """
    try:
        pool = sorted(
            x for x in templates_root().glob("*.xlsx")
            if x.is_file() and not x.name.startswith("~$")
        )
    except OSError as e:
        print(f"[export] 扫描模板目录失败: {type(e).__name__}: {e}", flush=True)
        return None
    if not pool:
        return None

    # 逐个校验，选结构合格的（目录里可能有半截下载的坏文件）
    chosen: Path | None = None
    for cand in pool:
        if _is_valid_template(cand):
            chosen = cand
            break
    if chosen is None:
        return None

    data = chosen.read_bytes()
    row = TemplateVersion(
        owner_uid=identity.uid,
        filename=chosen.name,
        stored_path=str(chosen),
        md5=hashlib.md5(data).hexdigest(),
        size=len(data),
        version=1,
        anchor_ok=1,
        note="自动重建（记录丢失但文件仍在）",
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[export] 模板记录重建失败: {type(e).__name__}: {e}", flush=True)
        return None
    audit.log("template.rebuilt", identity.uid, {"id": row.id, "path": str(chosen)})
    print(f"[export] 模板记录已重建: {chosen.name} (id={row.id})", flush=True)
    return row


def _assert_template_file(db: Session, tpl: TemplateVersion) -> Path:
    """确保模板文件真的在磁盘上；不在则**尝试自愈**，自愈不了才报错。

    为什么不能只抛 410（v1.0.17 修复）：
    DB 记录与磁盘文件可能不同步 —— 共享目录被清理、容器重建、挂载点变动、
    或升级过程���列都会让「记录在、文件没了」。此时让用户手动重新上传是**死路**：
    他已经填完一整周周报，却因为一个文件被告知「重新上传」。

    自愈策略（按可靠性排序）：
      1. **原路径存在** → 直接用；
      2. **模板目录里有同名/同 md5 的文件**（路径变了但内容还在）→ 修正 DB 里的路径；
      3. **目录里只有唯一一份xlsx** → 认它为丢失的那个（用户多半只有一份模板），
         重新校验锚点结构，通过后修正 DB 路径；
      4. 都不成立 → 才报错，且明确告知怎么办。
    """
    p = Path(tpl.stored_path or "")
    if p.is_file():
        return p

    tpl_dir = templates_root()
    recovered: Path | None = None

    # 策略 2：同名文件被挪了位置（最可信，优先）
    same_name = tpl_dir / p.name
    if same_name.is_file():
        recovered = same_name

    # 策略 3：在目录里找**结构合格**的候选（按 mtime 倒序，优先最近上传的）
    #
    # 注意不能只看「目录里只有一份」—— 目录里可能有半截下载的坏文件、或别处的残留。
    # 必须逐个用 validate_template 校验，找到第一个合格的即认它为丢失的那个。
    if recovered is None:
        try:
            pool = sorted(
                (x for x in tpl_dir.glob("*.xlsx")
                 if x.is_file() and not x.name.startswith("~$")),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            pool = []
        for cand in pool:
            if _is_valid_template(cand):
                recovered = cand
                break

    if recovered is None:
        detail = (
            f"模板记录 id={tpl.id} uid={tpl.owner_uid} version={tpl.version}\n"
            f"  DB 里的路径: {p}\n"
            f"  该路径是否存在: {p.is_file()}\n"
            f"  模板目录: {templates_root()}\n"
            f"  目录内容:\n{_diag_dir_listing()}"
        )
        print(f"[export] 模板文件缺失且无法自愈: {p} (templateId={tpl.id})", flush=True)
        _diag_trace("导出失败 · 模板文件缺失且无法自愈", detail)
        raise HTTPException(
            status_code=410,
            detail={
                "error": "TEMPLATE_FILE_GONE",
                "message": f"模板文件已丢失（{p.name}），且模板目录里没有可用的替代文件。"
                           f"请在「预览与导出」页重新上传一次模板（只需选文件，周报内容不会丢）",
                "diagLog": _diag_path(),
            },
        ) from None

    # 策略 2 的候选也要校验（它可能同名但内容已被破坏）
    if not _is_valid_template(recovered):
        print(f"[export] 同名模板不合格: {recovered}", flush=True)
        raise HTTPException(
            status_code=410,
            detail={
                "error": "TEMPLATE_FILE_GONE",
                "message": f"模板文件已丢失或损坏（{p.name}）。请在「预览与导出」页重新上传模板",
            },
        ) from None

    print(f"[export] 模板自愈: {p.name} -> {recovered.name} (id={tpl.id})", flush=True)
    tpl.stored_path = str(recovered)
    tpl.size = recovered.stat().st_size
    try:
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[export] 模板路径修正落库失败（不阻断导出）: {type(e).__name__}: {e}", flush=True)
    audit.log(
        "template.recovered",
        tpl.owner_uid,
        {"templateId": tpl.id, "from": str(p), "to": str(recovered)},
    )
    return recovered


def _is_valid_template(path: Path) -> bool:
    """能否作为周报模板使用：能打开 + 锚点结构合格。"""
    try:
        wb = load_workbook(path)
        validate_template(wb[wb.sheetnames[0]])
        return True
    except Exception as e:  # noqa: BLE001 —— 候选不合格就跳过，不算错误
        print(f"[export] 候选模板不合格 {path.name}: {type(e).__name__}", flush=True)
        return False


def _diag_trace(title: str, detail: str) -> None:
    """写真机诊断日志；诊断模块异常绝不能影响导出主流程。"""
    try:
        from ...core.diag import trace

        trace(title, detail)
    except Exception:  # noqa: BLE001
        pass


def _diag_path() -> str:
    try:
        from ...core.diag import diag_log_path

        return diag_log_path()
    except Exception:  # noqa: BLE001
        return "(诊断模块不可用)"


def _diag_dir_listing() -> str:
    try:
        d = templates_root()
        items = sorted(d.glob("*"))
        if not items:
            return f"    (空目录: {d})"
        return "\n".join(f"    {x.name}  {x.stat().st_size}B" for x in items)
    except OSError as e:
        return f"    (读取失败 {type(e).__name__}: {e})"


# ---------------------------------------------------------------- 导出编排


@dataclass
class ExportResult:
    artifact_id: int
    xlsx_path: str
    png_paths: list[str]
    scope: str
    status: str
    error: str = ""


def _load_tasks_for_export(
    db: Session, identity: Identity, report: Report
) -> tuple[list[FillItem], list[str], list[dict[str, Any]]]:
    """把本批次任务按**上传分区**分流为填充引擎的三路输入。

    返回 (星期块明细条目, 下周计划标题, 未落明细的条目说明)。

    分区即口径（用户按分类上传，系统不做自主判断，2026-10-13 确认）：
      - offline_done 本周线下工作 → 进 7 个星期块明细（需要 weekday 1~7）；
      - plan 下周工作计划         → 进 D23+ 计划区，按标题逐条列出（不看时间）；
      - online_done 线上售后     → **不进任何明细**，该口径由企微会话量文本体现
                                   （「企微会话量：413次」，见 wechat_metrics）。

    无时间（weekday=0）的线下任务进不了星期块，但仍计入工作汇总数量
    （汇总与时间无关），显式放入 omitted 由调用方如实告知，不静默丢弃。
    """
    from ...db.models import Screenshot, TaskItem
    from .constants import PARTITION_OFFLINE_DONE, PARTITION_PLAN

    shot_ids = select(Screenshot.id).where(Screenshot.report_id == report.id).scalar_subquery()
    rows = list(
        db.scalars(
            select(TaskItem).where(
                TaskItem.owner_uid == identity.uid,
                (TaskItem.screenshot_id.in_(shot_ids)) | (TaskItem.screenshot_id.is_(None)),
            )
        )
    )

    items: list[FillItem] = []
    plan_titles: list[str] = []
    omitted: list[dict[str, Any]] = []
    for t in rows:
        if not t.title.strip():
            continue  # 空标题由 export_readiness 阻断，不进填充
        if t.partition == PARTITION_PLAN:
            plan_titles.append(t.title.strip())
            continue
        if t.partition == PARTITION_OFFLINE_DONE and 1 <= t.weekday <= 7:
            items.append(
                FillItem(
                    weekday=t.weekday,
                    title=t.title,
                    start_at=t.start_at,
                    end_at=t.end_at,
                    status=t.raw_status,
                )
            )
            continue
        # 其余一律进 omitted：线上售后（汇总口径，由企微会话量体现）与
        # 无时间的线下任务（进不了星期块）。用户视角是「我传的这条怎么没
        # 出现在周报里」，必须如实告知，绝不静默丢弃。
        omitted.append({"title": t.title, "partition": t.partition})
    return items, plan_titles, omitted


def export_weekly_report(
    db: Session,
    identity: Identity,
    report: Report,
    scope: str = "content",
    dpi: int = PNG_DPI,
    render_png: bool = True,
) -> ExportResult:
    """导出周报：填充 xlsx → 落共享目录 → 渲染区域截图 → 登记产物。

    scope（T8 两口径）：
      - content 口径一：只截「已填充内容」的最小外接矩形；
      - full    口径二：截完整表体（A1:F26）。
    """
    if scope not in ("content", "full"):
        raise HTTPException(status_code=400, detail={"error": "BAD_SCOPE", "message": "scope 只能是 content 或 full"})

    template = resolve_template(db, identity, report)
    items, plan_titles, omitted = _load_tasks_for_export(db, identity, report)
    manual = _get_manual_texts(db, report)
    counts = _summary_counts(db, identity, report)
    # 线上售后数量按模板口径写企微会话量文本（不再按任务条数计）
    from .wechat_metrics import sessions_text

    counts["online_service"] = sessions_text(db, report.id)

    name = report_display_name(identity.username, report.period_start)
    out_dir = _ensure_dir(exports_root(identity.uid) / name, "导出产物")

    xlsx_path = out_dir / f"{name}.xlsx"

    # ---- 1. 填充（从模板副本，绝不改动模板原件）
    try:
        wb = load_workbook(template.stored_path)
        ws = wb[wb.sheetnames[0]]
        fill_weekly_report(
            ws,
            items,
            report.period_start,
            summary_counts=counts,
            # 不传 title_text：保留模板原标题「本周工作总结」，与模板逐字一致
            issue_text=manual.get("issues", ""),
            demand_text=manual.get("demands", ""),
            plan_texts=plan_titles,
        )
        wb.save(xlsx_path)
    except AnchorError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": "ANCHOR_MISMATCH", "message": f"模板结构校验失败，无法导出：{e}"},
        ) from None
    except HTTPException:
        raise
    except OSError as e:
        # 落盘失败：磁盘满 / 权限 / 目录被并发删除 —— 与「模板坏了」要区分开
        print(f"[export] 写入产物失败 {xlsx_path}: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "WRITE_FAILED",
                "message": f"导出文件写入失败（{type(e).__name__}: {e}）。"
                           f"请检查共享目录剩余空间与写入权限",
            },
        ) from None
    except Exception as e:
        print(f"[export] 填充失败: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "FILL_FAILED",
                "message": f"填充失败：{type(e).__name__}: {e}。"
                           f"若模板被手工改过，请在「预览与导出」页重新上传",
            },
        ) from None

    # ---- 2. 区域截图（失败不阻断 xlsx，标 partial）
    png_paths: list[Path] = []
    error = ""
    status = "ok"
    if render_png:
        try:
            png_paths = render_region_pngs(xlsx_path, out_dir, name, scope=scope, dpi=dpi)
            if not png_paths:
                status = "partial"
                error = "区域截图未产出（可能是 LibreOffice 不可用），xlsx 已正常导出"
        except Exception as e:
            status = "partial"
            error = f"区域截图失败：{type(e).__name__}: {e}"
    else:
        status = "partial"
        error = "本次仅导出 xlsx（未渲染截图）"

    # 无时间条目 / 线上汇总口径条目：已计入工作汇总数量，但进不了星期块明细。
    # 必须如实告知，不静默丢弃 —— 否则用户会以为「我传的截图怎么没进周报」。
    if omitted:
        detail = "、".join(o["title"][:20] for o in omitted[:3])
        more = f" 等 {len(omitted)} 条" if len(omitted) > 3 else ""
        note = f"有 {len(omitted)} 条未写入星期块明细（无时间或属线上汇总口径，已计入工作汇总数量）：{detail}{more}"
        error = f"{error}；{note}" if error else note
        if status == "ok":
            status = "partial"

    # ---- 3. 登记产物
    art = ExportArtifact(
        report_id=report.id,
        owner_uid=identity.uid,
        template_id=template.id,
        name=name,
        xlsx_path=str(xlsx_path),
        png_paths=[str(p) for p in png_paths],
        scope=scope,
        dpi=dpi,
        task_count=len(items),
        status=status,
        error=error[:500],
    )
    db.add(art)
    # 产物已落盘，这里才写库。若 DB 提交失败（PG 断连/超时），xlsx 其实已经生成，
    # 但用户会看到 500 且以为什么都没导出 —— 必须明确区分并说明文件在哪。
    try:
        db.commit()
        db.refresh(art)
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[export] 产物登记失败（文件已生成）: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "DB_COMMIT_FAILED",
                "message": f"文件已导出到共享目录，但登记导出记录失败（{type(e).__name__}）。"
                           f"请检查数据库连接；文件位于 {xlsx_path.parent}",
                "xlsx": xlsx_path.name,
            },
        ) from None
    audit.log(
        "export.done",
        identity.uid,
        {"reportId": report.id, "artifactId": art.id, "xlsx": xlsx_path.name, "png": len(png_paths), "status": status},
    )
    return ExportResult(
        artifact_id=art.id,
        xlsx_path=str(xlsx_path),
        png_paths=[str(p) for p in png_paths],
        scope=scope,
        status=status,
        error=error,
    )


def _get_manual_texts(db: Session, report: Report) -> dict[str, str]:
    from ...db.models import Setting

    out = {"issues": "", "demands": ""}
    for row in db.scalars(select(Setting).where(Setting.key.like(f"manual.{report.id}.%"))):
        out[row.key.rsplit(".", 1)[-1]] = row.value
    return out


def _summary_counts(db: Session, identity: Identity, report: Report) -> dict[str, int]:
    from .review_service import summary_of

    s = summary_of(db, identity, report)
    return {it["category"]: it["count"] for it in s["items"]}


def list_artifacts(db: Session, identity: Identity, report: Report) -> list[dict]:
    rows = db.scalars(
        select(ExportArtifact)
        .where(ExportArtifact.report_id == report.id, ExportArtifact.owner_uid == identity.uid)
        .order_by(ExportArtifact.id.desc())
    )
    out = []
    for a in rows:
        xp = Path(a.xlsx_path)
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "scope": a.scope,
                "dpi": a.dpi,
                "taskCount": a.task_count,
                "status": a.status,
                "error": a.error,
                "xlsx": xp.name,
                "xlsxExists": xp.is_file(),
                "pngs": [Path(p).name for p in (a.png_paths or [])],
                "createdAt": a.created_at.isoformat() if a.created_at else None,
            }
        )
    return out


# ---------------------------------------------------------------- 渲染链


def _soffice_bin() -> str | None:
    """定位 LibreOffice。镜像内为 soffice；本机可能只有 soffice.exe。"""
    for cand in ("soffice", "soffice.exe", "libreoffice"):
        path = shutil.which(cand)
        if path:
            return path
    return None


def render_region_pngs(
    xlsx_path: Path,
    out_dir: Path,
    name: str,
    scope: str = "content",
    dpi: int = PNG_DPI,
) -> list[Path]:
    """区域截图渲染链（V10 3.6 / 4.4）。

    流程：最小外接矩形 → 临时打印区域 → soffice 转 PDF → pdftoppm 转 PNG → 清理打印区域。

    「临时打印区域」写在**渲染专用副本**上，渲染完整个副本删除 ——
    绝不碰用户拿到的 xlsx 产物（那里面若残留 print_area，
    用户下次在 Excel 里打印就会只打印那一小块）。
    """
    soffice = _soffice_bin()
    if not soffice:
        raise RuntimeError("容器内未找到 LibreOffice（soffice），无法生成区域截图")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("容器内未找到 poppler-utils（pdftoppm），无法把 PDF 转 PNG")

    work = out_dir / f".render_{name}"
    work.mkdir(parents=True, exist_ok=True)
    tmp_xlsx = work / f"{name}.xlsx"

    try:
        # 渲染专用副本
        shutil.copy2(xlsx_path, tmp_xlsx)

        # 1) 计算打印区域
        area = _compute_print_area(tmp_xlsx, scope)

        # 2) 临时打印区域（只写在副本上）
        wb = load_workbook(tmp_xlsx)
        ws = wb[wb.sheetnames[0]]
        ws.print_area = area
        # 单页宽 + 按宽度分页（T8：超宽时按纸张宽度拆 _p1/_p2）
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        wb.save(tmp_xlsx)

        # 3) xlsx → pdf
        with _render_sem:
            proc = subprocess.run(
                [soffice, "--headless", "--norestore", "--convert-to", "pdf",
                 "--outdir", str(work), str(tmp_xlsx)],
                capture_output=True, timeout=SOFFICE_TIMEOUT,
                # HOME 必须可写（slim 镜像里已设 ENV HOME=/tmp）
                env={**os.environ, "HOME": os.environ.get("HOME", "/tmp")},
            )
        pdf = work / f"{name}.pdf"
        if not pdf.is_file():
            raise RuntimeError(
                f"LibreOffice 未产出 PDF：{(proc.stderr or b'').decode('utf-8', 'replace')[:200]}"
            )

        # 4) pdf → png
        prefix = work / name
        with _render_sem:
            proc2 = subprocess.run(
                [pdftoppm, "-png", "-r", str(dpi), "-f", "1", "-l", "3",
                 str(pdf), str(prefix)],
                capture_output=True, timeout=SOFFICE_TIMEOUT,
            )
        shots = sorted(work.glob(f"{name}-*.png"))
        if not shots:
            raise RuntimeError(
                f"pdftoppm 未产出 PNG：{(proc2.stderr or b'').decode('utf-8', 'replace')[:200]}"
            )

        # 5) 收集到导出目录并按 _p1/_p2 命名
        results: list[Path] = []
        for i, src in enumerate(shots, 1):
            suffix = "" if len(shots) == 1 else f"_p{i}"
            dst = out_dir / f"{name}{suffix}.png"
            shutil.move(str(src), dst)
            results.append(dst)
        return results
    finally:
        # 清理：整个渲染目录删除 → 打印区域随副本一起消失，产物 xlsx 保持干净
        shutil.rmtree(work, ignore_errors=True)


def _compute_print_area(xlsx_path: Path, scope: str) -> str:
    """计算打印区域字符串。

    口径一 content：最小外接矩形（A1 到「最后有内容的单元格」）。
    口径二 full：完整表体（A1:F26）。
    """
    from .anchors import COL_SOLUTION, LAST_WEEKDAY_ROW, PLAN_ROW_2

    if scope == "full":
        return f"A1:{COL_SOLUTION}{PLAN_ROW_2}"

    wb = load_workbook(xlsx_path)
    ws = wb[wb.sheetnames[0]]
    max_row = 0
    max_col = 0
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            if cell.value not in (None, ""):
                if cell.row > max_row:
                    max_row = cell.row
                c = cell.column
                if c > max_col:
                    max_col = c
    if max_row == 0:
        return "A1:F1"
    from openpyxl.utils import get_column_letter

    return f"A1:{get_column_letter(max_col)}{max_row}"
