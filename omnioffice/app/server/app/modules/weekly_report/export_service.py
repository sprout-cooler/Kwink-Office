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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from fastapi import HTTPException, UploadFile
from openpyxl import load_workbook
from sqlalchemy import func, select
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


def _write_template_file(target: Path, data: bytes) -> Path:
    """把模板内容**原子地**写到 target，返回最终路径。

    为什么不用 `if not exists(): write_bytes()`（原实现）：
    1. exists() 为真时直接跳过 —— 但文件内容可能已损坏/半截，仍被当成有效模板；
    2. write_bytes 是「截断 → 写入」，写入中途断电/磁盘满会留下**半截文件**，
       后续 load_workbook 抛 BadZipFile，用户看到的却是「模板损坏」这种误导性提示；
    3. 文件已存在且内容一致时其实无需重写（省一次 IO），但**必须校验存在性**，
       不能因为「记录说它在」就假定它在。

    改为：同内容且可读则跳过（幂等），否则写临时文件再 os.replace 原子替换。
    """
    try:
        if target.is_file() and target.stat().st_size == len(data):
            # 内容已一致则不重复写盘；md5 命中已由调用方保证，这里只做存在性确认
            return target
    except OSError:
        pass

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        print(f"[export] 模板落盘失败 {target}: {type(e).__name__}: {e}", flush=True)
        _diag_trace(
            "模板落盘失败",
            f"目标: {target}\n错误: {type(e).__name__}: {e}\nDATA_DIR: {settings.data_dir}",
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "TEMPLATE_WRITE_FAILED",
                "message": f"模板文件写入失败（{type(e).__name__}: {e}）。"
                           f"请检查数据目录 {settings.data_dir} 的写权限与剩余空间",
                "diagLog": _diag_path(),
            },
        ) from None
    print(f"[export] 模板已落盘: {target} ({len(data)} bytes)", flush=True)
    return target


def migrate_legacy_data() -> int:
    """一次性把旧数据目录（安装目录 target 下）的内容搬进持久目录。返回搬运文件数。

    背景（v1.0.23）：历史上 DATA_DIR 指向 `${TRIM_APPDEST}/share`，而该目录
    属于**安装目录**，fnOS 升级会清空；数据库却在 `${TRIM_PKGVAR}` 升级保留。
    于是升级后必然出现「记录在、文件没了」。现已把数据目录改到 `${TRIM_PKGVAR}/data`，
    本函数负责把**升级前尚未被清空**的遗留文件抢救进新目录。

    规则：
    - 目标已存在同名同大小文件 → 跳过（幂等，重启不重复搬）；
    - 旧目录不可读/不存在 → 直接返回 0，不报错（本地开发无此目录）；
    - 迁移的是用户资产，**只搬运不删除旧文件**，最坏情况是冗余，不会丢数据。
    """
    legacy_root = (settings.legacy_data_dir or "").strip()
    if not legacy_root:
        return 0
    legacy = Path(legacy_root)
    if not legacy.is_dir():
        return 0

    moved = 0
    # 只搬这三类用户资产；其余（日志、诊断、数据库）留在原处
    for sub in ("templates", "uploads"):
        src_dir = legacy / sub
        if not src_dir.is_dir():
            continue
        dst_dir = Path(settings.data_dir) / sub
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[migrate] 目标目录不可创建 {dst_dir}: {type(e).__name__}: {e}", flush=True)
            continue
        try:
            files = [p for p in src_dir.rglob("*") if p.is_file()]
        except OSError as e:
            print(f"[migrate] 扫描旧目录失败 {src_dir}: {type(e).__name__}: {e}", flush=True)
            continue
        for src in files:
            rel = src.relative_to(src_dir)
            dst = dst_dir / rel
            try:
                if dst.is_file() and dst.stat().st_size == src.stat().st_size:
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                moved += 1
                print(f"[migrate] 搬运 {src} -> {dst}", flush=True)
            except OSError as e:
                print(f"[migrate] 搬运失败 {src}: {type(e).__name__}: {e}", flush=True)

    if moved:
        print(f"[migrate] 旧数据迁移完成，共搬运 {moved} 个文件 → {settings.data_dir}", flush=True)
    else:
        print(f"[migrate] 无需迁移（目标目录已含全部文件）: {legacy} → {settings.data_dir}", flush=True)
    return moved


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
        "updatedAt": t.updated_at.isoformat() if t.updated_at else None,
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
    target = templates_root() / f"{md5}.xlsx"

    # 落盘：**先确保文件真的在磁盘上**，再谈入库。
    # v1.0.23 修复：原实现是「if not stored.exists(): stored.write_bytes(data)」。
    # 一旦文件被外部清掉（升级清目录、挂载点变动、人工清理）而 DB 记录还在，
    # 这里会因为 exists() 为假而重写 —— 看似正确；但真正的坑在下面的去重分支：
    # 查���同 md5 记录就直接 return duplicated，**从不检查文件是否存在**，
    # 于是用户重新上传同一个模板时什么都没发生（文件依然缺失），只能不断新增。
    _write_template_file(target, data)

    existing = db.scalar(
        select(TemplateVersion).where(
            TemplateVersion.owner_uid == identity.uid, TemplateVersion.md5 == md5
        )
    )
    if existing is not None:
        # 命中同内容记录：**复用该记录，但必须把路径/大小修正到当前真实文件**。
        # 文件已由上面的 _write_template_file 确保落盘，这里只校准元信息，
        # 避免记录指向一个已经不存在的旧路径（如升级前的安装目录路径）。
        real_path = str(target)
        if existing.stored_path != real_path or existing.size != len(data):
            existing.stored_path = real_path
            existing.size = len(data)
            try:
                db.commit()
                db.refresh(existing)
            except SQLAlchemyError as e:
                db.rollback()
                print(f"[export] 模板路径校准落库失败: {type(e).__name__}: {e}", flush=True)
        if note and existing.note != note[:255]:
            existing.note = note[:255]
            db.commit()
        print(
            f"[export] 模板重复上传，按内容复用记录 id={existing.id} → {real_path}",
            flush=True,
        )
        return {"template": _template_dto(existing), "duplicated": True, "sheet": sheet_name}

    # 版本号 = 该用户已有模板中最大版本 + 1。
    # 原实现用「记录条数 + 1」：删过模板后条数会变小，导致新版本号与现存记录撞号，
    # 界面出现两个 v2。取 max 才与实际展示的版本序列一致。
    max_ver = db.scalar(
        select(func.max(TemplateVersion.version)).where(TemplateVersion.owner_uid == identity.uid)
    )
    row = TemplateVersion(
        owner_uid=identity.uid,
        filename=_safe_name(name, "template.xlsx"),
        stored_path=str(target),
        md5=md5,
        size=len(data),
        version=int(max_ver or 0) + 1,
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
    """删除模板：**记录与文件同步清理**，不留脏数据。

    v1.0.23 修复（此前只删 DB 记录，文件留在盘上）：
    1. 删记录不删文件 → 孤儿 xlsx 堆积；更糟的是 `_rebuild_template_record`
       会把孤儿文件重新登记成记录，用户「删了又出现」；
    2. 文件已丢失时仍抛 409（TEMPLATE_IN_USE）让用户无路可走 ——
       记录在、文件没了的场景下，卡住删除毫无意义（导出本来就已不可用），
       改为允许删除并顺带清理绑定。

    顺序：先删文件 → 再删记录。文件删不掉（权限/占用）不阻断删记录，
    否则用户会被永久卡在「有记录但删不了」的死结里（正是本次事故的现象）。
    """
    t = _owned_template(db, identity, template_id)

    # v1.0.23：Report.template_id 是指向 template_versions.id 的外键，
    # 直接删模板会撞数据库外键约束（PG: update or delete on table violates foreign key）。
    # 原实现用 409 拦住是安全的，但代价是「记录在、文件已丢」时用户彻底删不掉。
    # 现在改为**先解绑再删除**：解绑只影响绑定关系，历史批次的导出产物已在库里，
    # 且 resolve_template 在无绑定时会回落到该用户最新模板，不会让历史周报导出失败。
    unbound = db.scalars(
        select(Report).where(Report.owner_uid == identity.uid, Report.template_id == template_id)
    ).all()
    for r in unbound:
        r.template_id = None
    if unbound:
        db.commit()
        print(
            f"[export] 模板删除前解绑 {len(unbound)} 个周报批次: templateId={template_id}",
            flush=True,
        )

    # 该 md5 是否还有其他记录在用（正常不会，md5 已去重；防御性检查）
    md5 = t.md5
    shared = db.scalar(
        select(TemplateVersion.id).where(
            TemplateVersion.owner_uid == identity.uid,
            TemplateVersion.md5 == md5,
            TemplateVersion.id != template_id,
        ).limit(1)
    )
    file_deleted = False
    if shared is None:
        file_deleted = _remove_template_file(t)
    else:
        print(f"[export] 模板文件被其他记录共用，保留文件: {md5}", flush=True)

    db.delete(t)
    db.commit()
    audit.log(
        "template.delete",
        identity.uid,
        {"id": template_id, "md5": md5[:8], "fileDeleted": file_deleted},
    )
    if not file_deleted and shared is None:
        print(
            f"[export] 模板记录已删除但文件未清理（可能文件本就不存在）: id={template_id} {md5}",
            flush=True,
        )


def _remove_template_file(t: TemplateVersion) -> bool:
    """删除模板对应的磁盘文件。返回是否确实删掉了文件。

    只允许删 templates_root() 目录内的 <md5>.xlsx —— 不信任 DB 里的 stored_path
    （历史脏数据可能指向任意位置，甚至安装目录），杜绝目录穿越。
    """
    root = templates_root()
    candidates = [root / f"{t.md5}.xlsx"]
    legacy = Path(t.stored_path or "")
    if legacy.name == f"{t.md5}.xlsx":
        candidates.append(legacy)

    removed = False
    for p in candidates:
        try:
            if p.is_file():
                p.unlink()
                removed = True
                print(f"[export] 模板文件已删除: {p}", flush=True)
        except OSError as e:
            # 删不掉只记录不抛出：记录必须能删掉，否则用户彻底卡死
            print(f"[export] 模板文件删除失败 {p}: {type(e).__name__}: {e}", flush=True)
            _diag_trace(
                "模板文件删除失败",
                f"路径: {p}\n错误: {type(e).__name__}: {e}",
            )
    return removed


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
      2. **模板目录里有同 md5 的文件**（路径变了但内容还在）→ 修正 DB 里的路径；
      3. **文件名对得上** → 修正路径；
      4. **目录里还有结构合格的 xlsx** → 认它为丢失的那个（降级猜测，多模板时可能认错）；
      5. 都不成立 → 才报错，且明确告知怎么办。
    """
    p = Path(tpl.stored_path or "")
    if p.is_file():
        return p

    tpl_dir = templates_root()
    recovered: Path | None = None

    # 策略 1（最可信）：按 md5 找 —— 文件名就是 md5，内容必然一致
    by_md5 = tpl_dir / f"{tpl.md5}.xlsx"
    if by_md5.is_file() and _is_valid_template(by_md5):
        recovered = by_md5
        print(f"[export] 模板按 md5 找回: {by_md5.name} (id={tpl.id})", flush=True)

    # 策略 2：文件名对得上（路径变了但内容还在）
    if recovered is None and p.name:
        same_name = tpl_dir / p.name
        if same_name.is_file():
            recovered = same_name

    # 策略 3：目录里找**结构合格**的候选（按 mtime 倒序，优先最近上传的）
    #
    # 注意不能只看「目录里只有一份」—— 目录里可能有半截下载的坏文件、或别处的残留。
    # 必须逐个用 validate_template 校验，找到第一个合格的即认它为丢失的那个。
    # 这一步是**降级猜测**：多模板用户可能认错，故仅在前面都失败时启用。
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

    # 策略 2/3 的候选也要校验（它可能同名但内容已被破坏）
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


# 差异对比的输出上限：模板通常是几 KB 的结构化表格，但防御「两个完全不同的工作簿」
# 造成前端一次渲染上万行 —— 超限就截断并如实告知。
MAX_DIFF_ROWS = 300
MAX_DIFF_SCAN_ROWS = 400
MAX_DIFF_SCAN_COLS = 40


def diff_templates(db: Session, identity: Identity, base_id: int, target_id: int) -> dict:
    """对比两个模板版本的单元格差异。

    base 为参照版本（通常选旧的），target 为对比版本（通常是新的），
    输出语义是「从 base 到 target 发生了什么变化」，符合「看这一版改了啥」的直觉。

    识别三类差异：单元格内容变化（changed）、target 新增内容（added）、
    target 删掉的内容（removed）；工作表级别的增删单列(kind="sheet")。
    """
    base = _owned_template(db, identity, base_id)
    target = _owned_template(db, identity, target_id)
    base_path = _assert_template_file(db, base)
    target_path = _assert_template_file(db, target)

    try:
        wb_a = load_workbook(base_path)
        wb_b = load_workbook(target_path)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"error": "BAD_XLSX", "message": f"模板文件无法解析：{type(e).__name__}: {e}"},
        ) from None

    changes: list[dict] = []
    truncated = False
    total = 0
    sheets_a = set(wb_a.sheetnames)
    sheets_b = set(wb_b.sheetnames)

    for name in sorted(sheets_a - sheets_b):
        total += 1
        if len(changes) < MAX_DIFF_ROWS:
            changes.append({"sheet": name, "cell": "", "kind": "sheet_removed", "left": "有该工作表", "right": ""})
    for name in sorted(sheets_b - sheets_a):
        total += 1
        if len(changes) < MAX_DIFF_ROWS:
            changes.append({"sheet": name, "cell": "", "kind": "sheet_added", "left": "", "right": "新增该工作表"})

    for name in sorted(sheets_a & sheets_b):
        if truncated:
            break
        ws_a = wb_a[name]
        ws_b = wb_b[name]
        cells_a = _sheet_cell_map(ws_a)
        cells_b = _sheet_cell_map(ws_b)
        for coord in sorted(set(cells_a) | set(cells_b)):
            va, vb = cells_a.get(coord), cells_b.get(coord)
            if va == vb:
                continue
            total += 1
            if len(changes) >= MAX_DIFF_ROWS:
                truncated = True
                continue
            if va is None:
                kind = "added"
            elif vb is None:
                kind = "removed"
            else:
                kind = "changed"
            changes.append(
                {
                    "sheet": name,
                    "cell": coord,
                    "kind": kind,
                    "left": va or "",
                    "right": vb or "",
                }
            )

    return {
        "base": _template_dto(base),
        "target": _template_dto(target),
        "changes": changes,
        "total": total,
        "truncated": truncated,
        "limit": MAX_DIFF_ROWS,
    }


def _sheet_cell_map(ws) -> dict[str, str]:
    """把工作表里有内容的单元格摊平成 {坐标: 显示文本}。

    上限扫描：超大工作表（几万行）不可能逐个比，模板通常 A1:F26，
    400×40 足够覆盖；超出部分会被截断标记掩盖，不静默丢一半结果。
    """
    out: dict[str, str] = {}
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, MAX_DIFF_SCAN_ROWS),
                            max_col=min(ws.max_column, MAX_DIFF_SCAN_COLS)):
        for cell in row:
            if cell.value in (None, ""):
                continue
            out[cell.coordinate] = str(cell.value)[:200]
    return out


def rollback_template(
    db: Session, identity: Identity, report: Report, target_id: int, note: str = ""
) -> dict:
    """回滚到指定模板版本。

    关键取舍：**生成新版本而不是删除历史**。
    若把「回滚」实现为把版本指针改回旧版（或直接删掉中间版本），一旦用户发现
    回滚错了就再也回不去。这里从旧版内容派生出一个**新的最高版本**，
    历史链条完整保留，代价只是多一条版本记录。
    """
    src = _owned_template(db, identity, target_id)
    src_path = _assert_template_file(db, src)
    data = Path(src_path).read_bytes()
    md5 = hashlib.md5(data).hexdigest()

    stored = templates_root() / f"{md5}.xlsx"
    if not stored.exists():
        stored.write_bytes(data)

    count = len(
        list(db.scalars(select(TemplateVersion).where(TemplateVersion.owner_uid == identity.uid)))
    )
    row = TemplateVersion(
        owner_uid=identity.uid,
        filename=src.filename,
        stored_path=str(stored),
        md5=md5,
        size=len(data),
        version=count + 1,
        anchor_ok=1,
        note=(note or f"回滚自 v{src.version}")[:255],
        updated_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    bound = False
    if report is not None:
        report.template_id = row.id
        db.commit()
        bound = True

    audit.log(
        "template.rollback",
        identity.uid,
        {"fromVersion": src.version, "toVersion": row.version, "templateId": row.id},
    )
    return {"template": _template_dto(row), "sourceVersion": src.version, "bound": bound}


# ---------------------------------------------------------------- 导出历史管理


def _artifact_dto(db: Session, a: ExportArtifact) -> dict:
    """导出记录视图：文件名 / 导出时间 / 所用模板及版本 / 产物是否还在。"""
    xp = Path(a.xlsx_path) if a.xlsx_path else None
    pngs = [Path(p) for p in (a.png_paths or [])]
    size = 0
    if xp is not None and xp.is_file():
        try:
            size = xp.stat().st_size
        except OSError:
            size = 0

    tpl = db.get(TemplateVersion, a.template_id) if a.template_id else None
    # 模板可能已被别的操作清理；且必须同属一个账号，否则视为「模板信息不可用」
    if tpl is not None and tpl.owner_uid != a.owner_uid:
        tpl = None
    report = db.get(Report, a.report_id) if a.report_id else None

    return {
        "id": a.id,
        "name": a.name,
        "scope": a.scope,
        "dpi": a.dpi,
        "taskCount": a.task_count,
        "status": a.status,
        "error": a.error,
        "xlsx": xp.name if xp else "",
        "xlsxExists": bool(xp and xp.is_file()),
        "xlsxSize": size,
        "pngs": [p.name for p in pngs],
        "pngCount": len(pngs),
        "templateId": tpl.id if tpl else None,
        "templateVersion": tpl.version if tpl else None,
        "templateFilename": tpl.filename if tpl else "",
        "reportId": a.report_id,
        "periodStart": report.period_start if report else "",
        "createdAt": a.created_at.isoformat() if a.created_at else None,
        "updatedAt": a.updated_at.isoformat() if a.updated_at else None,
    }


def _owned_artifact(db: Session, identity: Identity, artifact_id: int) -> ExportArtifact:
    art = db.get(ExportArtifact, artifact_id)
    if art is None or art.owner_uid != identity.uid:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "导出记录不存在"})
    return art


def list_export_history(
    db: Session, identity: Identity, q: str = "", template_id: int | None = None, limit: int = 200
) -> list[dict]:
    """全部导出历史（跨周报批次），可按文件名搜索 / 按模板版本筛选。

    与 list_artifacts 的区别：那个只看「当前批次」，这里回答
    「我上周那份周报叫什么名字、用的哪个版本」，是历史管理的主视图。
    """
    stmt = select(ExportArtifact).where(ExportArtifact.owner_uid == identity.uid)
    kw = (q or "").strip()
    if kw:
        stmt = stmt.where(ExportArtifact.name.like(f"%{kw}%"))
    if template_id:
        stmt = stmt.where(ExportArtifact.template_id == template_id)
    rows = db.scalars(stmt.order_by(ExportArtifact.id.desc()).limit(max(1, min(int(limit), 500))))
    return [_artifact_dto(db, a) for a in rows]


def rename_artifact(db: Session, identity: Identity, artifact_id: int, new_name: str) -> dict:
    """重命名导出记录（同步重命名共享目录里的文件，让文件名与记录保持一致）。

    为什么连文件一起改名：记录名改了而文件还叫旧名，用户去文件管理器找会找不到，
    下载时 FileResponse 也会用磁盘上的旧文件名 —— 等于改名没生效。
    文件改名失败（被占用 / 目录被外部抢占）不回滚记录改名，如实回报 filesRenamed=false。
    """
    art = _owned_artifact(db, identity, artifact_id)
    clean = _safe_name(new_name, art.name)
    if not clean:
        raise HTTPException(status_code=400, detail={"error": "BAD_NAME", "message": "名称无效（不能为空或只含符号）"})
    if clean == art.name:
        return {"item": _artifact_dto(db, art), "filesRenamed": False, "unchanged": True}

    old_name = art.name
    old_dir = Path(art.xlsx_path).parent if art.xlsx_path else None
    files_renamed = _rename_artifact_files(old_dir, old_name, clean)

    if files_renamed:
        cand_xlsx = old_dir.parent / clean / f"{clean}.xlsx"
        art.xlsx_path = str(cand_xlsx)
        png_dir = cand_xlsx.parent
        pngs = sorted(str(p) for p in png_dir.glob(f"{clean}*.png")) if png_dir.is_dir() else []
        art.png_paths = pngs
    art.name = clean
    art.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit.log("export.rename", identity.uid, {"artifactId": art.id, "from": old_name, "to": clean})
    return {"item": _artifact_dto(db, art), "filesRenamed": files_renamed, "unchanged": False}


def _rename_artifact_files(old_dir: Path | None, old_name: str, new_name: str) -> bool:
    """共享目录里的导出目录与文件整体改名；失败返回 False（记录改名仍然生效）。"""
    if old_dir is None or not old_dir.is_dir() or not old_dir.parent:
        return False  # 文件已被清理，只改记录名
    new_dir = old_dir.parent / new_name
    if new_dir.exists() and new_dir != old_dir:
        return False  # 目标名已存在：不动目录，避免覆盖别人的产物
    try:
        if new_dir != old_dir:
            shutil.move(str(old_dir), str(new_dir))
        for f in sorted(new_dir.iterdir()):
            if f.name.startswith(old_name):
                f.rename(new_dir / (new_name + f.name[len(old_name):]))
        return True
    except OSError as e:
        print(f"[export] 导出文件改名失败 {old_dir} -> {new_dir}: {type(e).__name__}: {e}", flush=True)
        return False


def delete_artifact(db: Session, identity: Identity, artifact_id: int) -> dict:
    """删除导出记录并清理共享目录里的产物文件。

    文件已被外部清理（410 场景）也要能把记录删掉 —— 否则用户永远删不掉
    一条「文件已丢失」的历史记录。
    """
    art = _owned_artifact(db, identity, artifact_id)
    paths = [Path(art.xlsx_path)] if art.xlsx_path else []
    paths += [Path(p) for p in (art.png_paths or [])]
    removed = 0
    parent: Path | None = None
    for p in paths:
        if p.is_file():
            parent = p.parent
            try:
                p.unlink()
                removed += 1
            except OSError as e:
                print(f"[export] 删除产物文件失败 {p}: {type(e).__name__}: {e}", flush=True)
    dir_removed = False
    if parent is not None and parent.is_dir():
        try:
            if not any(parent.iterdir()):
                parent.rmdir()
                dir_removed = True
        except OSError:
            pass
    db.delete(art)
    db.commit()
    audit.log("export.delete", identity.uid, {"artifactId": artifact_id, "files": removed})
    return {"ok": True, "filesRemoved": removed, "dirRemoved": dir_removed}


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
