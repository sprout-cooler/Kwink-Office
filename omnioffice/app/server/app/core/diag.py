"""真机排障诊断日志（v1.0.18）。

## 为什么需要它

用户在真机上报「导出 410」，而本机 mock + SQLite 复现不出来 ——
真机是 **PostgreSQL + 容器内 /data 挂载 fnOS 共享目录 + `run-as: package` 非 root**，
与开发机差异极大。没有真机日志，只能靠猜。

本模块把「环境实况 + 导出链路每个环节」写成一个文件，用户直接下载即可，
不必截图、不必翻容器日志、不必反复来回问。

## 输出位置

按优先级尝试，第一个可写的生效（并记录实际用了哪个）：

1. `DIAG_LOG_DIR` 环境变量（显式指定，最可靠）
2. `/vol2/1000/fpk/omnioffice_diag`（用户指定的 fnOS 真实路径）
3. `/vol1/1000/fpk/omnioffice_diag`（另一常见卷）
4. `DATA_DIR/diag`（容器内挂载点，至少保证有输出）

写入失败**绝不抛异常** —— 诊断工具自己把服务搞挂是最讽刺的失败。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

from .config import settings

# 候选目录：按优先级排列。
# POSIX 路径只在类 Linux 环境（真机容器）才探测 —— Windows 上 Path("/vol2/...")
# 会被解析成当前盘根下的 \vol2\...，mkdir 会真的建出一个莫名其妙的目录。
_IS_POSIX = os.name == "posix"
_VOL_CANDIDATES: tuple[str, ...] = (
    ("/vol2/1000/fpk/omnioffice_diag", "/vol1/1000/fpk/omnioffice_diag")
    if _IS_POSIX
    else ()
)

_resolved_dir: Path | None = None


def diag_dir() -> Path | None:
    """解析诊断日志目录（只解析一次并缓存）。失败返回 None。"""
    global _resolved_dir
    if _resolved_dir is not None:
        return _resolved_dir if _resolved_dir.is_dir() else None

    env_dir = os.environ.get("DIAG_LOG_DIR", "").strip()
    candidates = (
        ([env_dir] if env_dir else [])
        + list(_VOL_CANDIDATES)
        + [str(Path(settings.data_dir) / "diag")]
    )

    for raw in candidates:
        if not raw:
            continue
        try:
            p = Path(raw)
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _resolved_dir = p
            return p
        except OSError:
            continue
    return None


def diag_log_path() -> str:
    d = diag_dir()
    return str(d / "diagnostic.log") if d else "(无可写诊断目录)"


def _write(text: str) -> bool:
    """追加写入。返回是否成功。"""
    d = diag_dir()
    if d is None:
        return False
    try:
        with (d / "diagnostic.log").open("a", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        return True
    except OSError:
        return False


def _sep(title: str) -> str:
    return f"\n{'=' * 68}\n{title}\n{'=' * 68}"


# ---------------------------------------------------------------- 环境快照


def _run(cmd: list[str]) -> str:
    """跑一条命令拿输出；不可用则如实说明（不抛）。"""
    try:
        if not shutil.which(cmd[0]):
            return f"(未安装 {cmd[0]})"
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return (out.stdout or out.stderr or "(无输出)").strip()[:1200]
    except Exception as e:  # noqa: BLE001
        return f"(执行失败 {type(e).__name__}: {e})"


def _probe_dir(p: Path) -> str:
    """目录可写性探针：mkdir + 写文件，如实回报。"""
    lines = [f"路径: {p}"]
    try:
        p.mkdir(parents=True, exist_ok=True)
        lines.append("  存在: 是（本次已确保）")
    except OSError as e:
        lines.append(f"  存在: 否 —— mkdir 失败 {type(e).__name__}: {e}")
        return "\n".join(lines)
    probe = p / ".diag_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        lines.append("  可写: 是")
    except OSError as e:
        lines.append(f"  可写: 否 —— {type(e).__name__}: {e}")
    try:
        st = p.stat()
        lines.append(f"  权限: {oct(st.st_mode)[-4:]}  属主 uid={st.st_uid} gid={st.st_gid}")
    except OSError:
        pass
    return "\n".join(lines)


def _list_dir(p: Path, limit: int = 20) -> str:
    try:
        if not p.is_dir():
            return f"(目录不存在: {p})"
        items = sorted(p.iterdir(), key=lambda x: x.name)
        if not items:
            return f"(目录为空: {p})"
        out = [f"共 {len(items)} 项，列出前 {min(limit, len(items))}："]
        for it in items[:limit]:
            try:
                sz = it.stat().st_size
            except OSError:
                sz = -1
            out.append(f"  {it.name}  {sz} bytes  {'<DIR>' if it.is_dir() else ''}")
        return "\n".join(out)
    except OSError as e:
        return f"(读取失败 {type(e).__name__}: {e})"


def _count_tree(p: Path, sample: int = 8) -> str:
    """递归统计文件数与总字节，并抽样列出几项。

    截图原图可能上千张，全列会刷爆日志；这里只给数量级 + 抽样，
    足以判断「目录空了 / 数据量还在」。
    """
    try:
        if not p.is_dir():
            return f"(目录不存在: {p})"
        files: list[Path] = []
        total = 0
        for f in p.rglob("*"):
            if f.is_file():
                files.append(f)
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
        if not files:
            return f"(目录为空: {p})"
        files.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
        out = [f"文件数 {len(files)}，合计 {total} bytes（约 {total / 1024 / 1024:.1f} MB）"]
        for f in files[:sample]:
            try:
                out.append(f"  {f.relative_to(p)}  {f.stat().st_size} bytes")
            except OSError:
                continue
        if len(files) > sample:
            out.append(f"  ... 其余 {len(files) - sample} 项省略")
        return "\n".join(out)
    except OSError as e:
        return f"(读取失败 {type(e).__name__}: {e})"


def dump_screenshot_records() -> str:
    """把 DB 里的截图记录与磁盘文件对照 —— 定位「原图 410」的核心证据。

    真机事故（≤1.0.18）：用户数据挂在 ${TRIM_APPDEST}/share（安装 target），
    升级时该目录被清空，于是 DB 记录还在、原图没了，前端回显全部 410 Gone。
    这里同时给出「记录数 / 文件缺失数 / 缺失样本路径」，一眼可判定是哪一种。
    """
    return _dump_screenshot_records()


def snapshot(title: str = "环境快照") -> str:
    """采集完整环境快照 —— 真机排障的第一份证据。"""
    db_kind = "postgres" if settings.database_url.startswith("postgres") else "sqlite"
    # 不打印 DATABASE_URL 全文（可能含密码），只打协议与主机
    db_masked = ""
    if settings.database_url:
        try:
            from urllib.parse import urlparse

            u = urlparse(settings.database_url)
            db_masked = f"{u.scheme}://{u.hostname or '?'}:{u.port or '?'}/{u.path.lstrip('/')}"
        except Exception:  # noqa: BLE001
            db_masked = "(解析失败)"

    parts = [
        _sep(f"{title} · {time.strftime('%Y-%m-%d %H:%M:%S')}"),
        f"应用版本      : {settings.app_version}",
        f"诊断日志      : {diag_log_path()}",
        "",
        "[运行环境]",
        f"  Python      : {sys.version.split()[0]}",
        f"  平台        : {platform.platform()}",
        f"  运行用户 uid: {os.getuid() if hasattr(os, 'getuid') else '?'}"
        f"  gid: {os.getgid() if hasattr(os, 'getgid') else '?'}",
        f"  当前工作目录: {Path.cwd()}",
        f"  容器内 /data : {'存在' if Path('/data').is_dir() else '不存在'}"
        f"  {_probe_dir(Path('/data')) if Path('/data').is_dir() else ''}",
        "",
        "[配置]",
        f"  GATEWAY_PREFIX: {settings.gateway_prefix}",
        f"  SOCKET_PATH    : {settings.socket_path or '(未设，走 TCP)'}",
        f"  IDENTITY_MODE  : {settings.identity_mode}",
        f"  DATA_DIR       : {settings.data_dir}",
        f"  数据库类型    : {db_kind}  {db_masked}",
        "",
        "[数据目录]",
        f"  DATA_DIR 本身:\n{_probe_dir(Path(settings.data_dir))}",
        f"  模板目录:\n{_probe_dir(Path(settings.data_dir) / 'templates')}",
        f"  导出目录:\n{_probe_dir(Path(settings.data_dir) / 'exports')}",
        f"  上传目录（截图原图）:\n{_probe_dir(Path(settings.data_dir) / 'uploads')}",
        "",
        "[模板目录内容]",
        _list_dir(Path(settings.data_dir) / "templates"),
        "",
        # 截图原图 410 的定位关键：DB 有记录但文件不在了（升级清空安装 target 所致）。
        # 只列数量与抽样，避免几千张图刷爆日志。
        "[上传目录内容（抽样）]",
        _count_tree(Path(settings.data_dir) / "uploads"),
        "",
        "[用户指定的诊断路径探测（/vol2/1000/fpk）]",
        _probe_dir(Path("/vol2/1000/fpk")) if _IS_POSIX else "(非 POSIX 环境，跳过；真机容器内才会出现)",
        _list_dir(Path("/vol2/1000/fpk"), limit=10) if _IS_POSIX else "",
        "",
        "[数据库里的模板记录]",
        _dump_template_records(),
        "",
        "[数据库里的截图记录（与原图对照）]",
        _dump_screenshot_records(),
        "",
        "[渲染链依赖]",
        f"  soffice   : {shutil.which('soffice') or '(未找到)'}",
        f"  pdftoppm  : {shutil.which('pdftoppm') or '(未找到)'}",
        f"  soffice --version: {_run(['soffice', '--version'])}",
        "",
        "[挂载信息]",
        _run(["df", "-h"]),
        "",
    ]
    text = "\n".join(parts)
    ok = _write(text)
    print(f"[diag] 环境快照已写入 {diag_log_path()} (ok={ok})", flush=True)
    return text


def _dump_template_records() -> str:
    """把 DB 里的模板记录导出来 —— 与磁盘文件对照是定位 410 的关键。"""
    try:
        from sqlalchemy import text

        from ..db.session import engine

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, owner_uid, filename, stored_path, size, version FROM template_versions")
            ).fetchall()
            reports = conn.execute(
                text("SELECT id, owner_uid, period_start, template_id FROM reports")
            ).fetchall()
        if not rows:
            lines = ["(template_versions 表为空 —— 说明从未成功入库模板)"]
        else:
            lines = [f"模板记录 {len(rows)} 条："]
            for r in rows:
                exists = Path(r[3]).is_file() if r[3] else False
                lines.append(f"  id={r[0]} uid={r[1]} v{r[5]} {r[2]}")
                lines.append(f"    stored_path = {r[3]}")
                lines.append(f"    文件是否存在  : {'是' if exists else '否 ← 这就是 410 的原因'}")
        lines.append("")
        lines.append(f"周报批次 {len(reports)} 条：")
        for r in reports:
            lines.append(f"  id={r[0]} uid={r[1]} period={r[2]} template_id={r[3]}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"(读取失败 {type(e).__name__}: {e})"


def _dump_screenshot_records() -> str:
    """截图记录 × 磁盘文件对照。

    ≤1.0.18 真机事故：用户数据挂 ${TRIM_APPDEST}/share（安装 target），
    升级时该目录被清空 → DB 记录还在、原图没了 → 前端回显 410 Gone。
    这里给出「总数 / 缺失数 / 缺失样本 / 现存样本路径」，足以判定是哪一类。
    """
    try:
        from sqlalchemy import text

        from ..db.session import engine

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, owner_uid, report_id, partition, filename, stored_path "
                    "FROM screenshots ORDER BY id"
                )
            ).fetchall()
        if not rows:
            return "(screenshots 表为空 —— 说明从未上传过截图)"
        missing = [r for r in rows if not (r[5] and Path(r[5]).is_file())]
        lines = [
            f"截图记录 {len(rows)} 条，其中原图缺失 {len(missing)} 条"
            + ("  ← 这就是 410 Gone 的来源（升级清空过数据目录）" if missing else "  （全部在位）")
        ]
        if missing:
            lines.append("缺失样本（最多 10 条）：")
            for r in missing[:10]:
                lines.append(f"  id={r[0]} uid={r[1]} report={r[2]} {r[3]} {r[4]}")
                lines.append(f"    stored_path = {r[5] or '(空)'}")
        alive = [r for r in rows if r[5] and Path(r[5]).is_file()]
        if alive:
            lines.append("")
            lines.append(f"在位样本（最多 3 条，用于核对路径规则）：")
            for r in alive[:3]:
                lines.append(f"  id={r[0]} {r[4]}  →  {r[5]}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"(读取失败 {type(e).__name__}: {e})"


def trace(title: str, detail: str | None = None) -> None:
    """记录一条排障事件（异常堆栈等），同时打 stdout。"""
    block = [
        _sep(title),
        time.strftime("%Y-%m-%d %H:%M:%S"),
        detail or "",
        traceback.format_exc(),
    ]
    text = "\n".join(block)
    ok = _write(text)
    print(f"[diag] {title} -> {diag_log_path()} (ok={ok})", flush=True)


def read_all() -> str:
    """读回整份诊断日志（供 /api/health/diag 展示，用户可直接下载）。"""
    d = diag_dir()
    if d is None:
        return "(无可写诊断目录)"
    try:
        return (d / "diagnostic.log").read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(读取失败 {type(e).__name__}: {e})"