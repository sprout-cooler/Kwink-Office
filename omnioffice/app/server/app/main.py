"""全能办公室 服务端入口（FastAPI 常驻服务）。

平台关键约束（开发避坑指南 §1.2 / Agent 指南 案例 5）：
1. 统一网关按 /app/omnioffice/xxx 原样转发、保留完整前缀 →
   API 与 WS 必须同时挂 /api（本地）与 {GATEWAY_PREFIX}/api（网关）两个前缀，
   404 兜底也要按前缀区分，避免把 API 404 当 SPA 返回 HTML；
2. 前端经网关子路径访问 → index.html 必须动态注入 <base href="{prefix}/">；
3. 身份一律来自网关 X-Trim-* 头（identity.py），绝不信任客户端自报身份；
4. 静态文件服务必须做路径标准化，拒绝 .. 目录穿越（V10 8.12）。
"""
from __future__ import annotations

import asyncio
import re
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .core import audit
from .core.config import settings
from .core.diag import trace as diag_trace
from .core.identity import get_identity, get_provider
from .db.deps import get_db
from .db.session import SessionLocal, init_db
from .modules import registry
from .modules.weekly_report import recognize_queue
from .modules.weekly_report.router import router as weekly_report_router

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
_PREFIX_RE = re.compile(r"^(/app/[^/]+)")

app = FastAPI(title="OmniOffice", version=settings.app_version, docs_url=None, redoc_url=None)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局兜底：把「裸 500」变成可定位的 500。

    为什么必须有（v1.0.16 修复）：此前服务**没有任何**全局异常处理器，
    业务链路里任何未预期的异常（目录不可写、模板文件被外部删除、
    DB 连接中断…）都直接冒泡成 FastAPI 默认的 `Internal Server Error`——
    **响应体无信息、服务日志无堆栈**。真机上只能看到「导出失败 500」，
    无从判断是磁盘满、权限不足还是文件丢失，只能反复重装试探。

    这里保证三件事：
      1. 完整堆栈打到 stdout —— fnOS 汇总进/var/apps/{appname}/var/app.log，
         可直接检索 `UNHANDLED` 定位；
      2. 同时落 audit.log（带 requestId），应用侧也能追；
      3. 返回结构化 500，error 字段给出**可行动的中文提示**而非 "Internal Server Error"。
    """
    rid = uuid.uuid4().hex[:8]
    tb = traceback.format_exc()
    path = request.url.path
    print(f"[UNHANDLED] rid={rid} {request.method} {path}\n{tb}", flush=True)
    # 落真机诊断日志 —— 用户可直接下载，不必翻容器日志
    diag_trace(f"未处理异常 rid={rid} {request.method} {path}",
               f"{type(exc).__name__}: {exc}")
    audit.log(
        "error.unhandled",
        None,
        {"rid": rid, "path": path, "method": request.method,
         "error": f"{type(exc).__name__}: {exc}"},
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "error": "INTERNAL_ERROR",
                "message": f"服务内部错误（{type(exc).__name__}），已记录编号 {rid}，请查看应用日志定位",
                "requestId": rid,
                "path": path,
            }
        },
    )


def _api_router() -> None:  # noqa: C901 —— 组装业务 API（双前缀挂载）
    from fastapi import APIRouter, Depends

    router = APIRouter()

    @router.get("/health")
    def health():
        # 公开存活探针（cmd/main status 与冒烟测试使用）
        return {"status": "ok", "version": settings.app_version}

    @router.get("/health/diag")
    def health_diag(identity=Depends(get_identity)):
        """排障诊断（v1.0.16）：把「导出 500」的常见成因逐项自检并回报。

        真机上导出失败时先看这个接口 —— 它直接回答：数据目录可不可写、
        模板在不在、产物目录建没建起来、LibreOffice 有没有。
        不必去翻容器日志。

        本接口**自身绝不抛异常**：诊断工具因为自己的 bug 而 500 是最讽刺的失败。
        """
        import shutil

        from .core.diag import diag_log_path
        from .modules.weekly_report import export_service as ES

        def probe_dir(p: Path) -> dict:
            """建目录 + 写探针文件，如实回报结果而非抛错。"""
            out: dict = {"path": str(p), "exists": False, "writable": False, "error": ""}
            try:
                p.mkdir(parents=True, exist_ok=True)
                out["exists"] = True
            except OSError as e:
                out["error"] = f"目录创建失败：{type(e).__name__}: {e}"
                return out
            try:
                probe = p / ".write_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                out["writable"] = True
            except OSError as e:
                out["error"] = f"目录不可写：{type(e).__name__}: {e}"
            return out

        uid = identity.uid if identity else "1000"
        data_root = Path(settings.data_dir)
        soffice = shutil.which("soffice") or shutil.which("soffice.exe")
        pdftoppm = shutil.which("pdftoppm")

        db_kind = "postgres" if settings.database_url.startswith("postgres") else "sqlite"
        db_ok, db_err = True, ""
        try:
            from sqlalchemy import text

            s = SessionLocal()
            try:
                s.execute(text("SELECT 1"))
            finally:
                s.close()
        except Exception as e:  # noqa: BLE001
            db_ok, db_err = False, f"{type(e).__name__}: {e}"

        tpl_count, tpl_files = 0, []
        try:
            tdir = Path(settings.data_dir) / "templates"
            if tdir.is_dir():
                tpl_files = [p.name for p in tdir.glob("*.xlsx")]
                tpl_count = len(tpl_files)
        except OSError as e:
            tpl_files = [f"<读取失败: {e}>"]

        return {
            "version": settings.app_version,
            "dataDir": str(data_root),
            "database": {"kind": db_kind, "ok": db_ok, "error": db_err},
            "directories": {
                "data": probe_dir(data_root),
                "templates": probe_dir(Path(settings.data_dir) / "templates"),
                "exports": probe_dir(Path(settings.data_dir) / "exports" / uid),
            },
            "render": {
                "soffice": soffice or "",
                "pdftoppm": pdftoppm or "",
                "available": bool(soffice and pdftoppm),
                "note": "" if (soffice and pdftoppm) else "缺少 LibreOffice：区域截图不可用，xlsx 导出不受影响",
            },
            "templates": {"count": tpl_count, "files": tpl_files[:10]},
            "diagLog": diag_log_path(),
        }

    @router.get("/health/diag/dump")
    def diag_dump(identity=Depends(get_identity)):
        """重新采集一份环境快照，并把诊断日志原文返回（用户可直接复制给我）。"""
        from .core import diag as DG

        snapshot = DG.snapshot("手动触发")
        return {
            "logPath": DG.diag_log_path(),
            "snapshot": snapshot,
            "content": DG.read_all(),
        }

    @router.get("/session")
    def session(identity=Depends(get_identity)):
        # 身份回显：M0 Spike S2 的验收探针
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED", "message": "未识别到网关身份"}, status_code=401)
        return {"uid": identity.uid, "username": identity.username, "isAdmin": identity.is_admin}

    @router.get("/modules")
    def modules(identity=Depends(get_identity)):
        # B 层导航数据源（V10 8.8）
        return {"modules": registry.list_enabled()}

    # ---------------------------------------------------------- 设置（分类配置）

    @router.get("/settings")
    def get_settings(db: Session = Depends(get_db), identity=Depends(get_identity)):
        """设置页聚合数据：应用级配置 + 全局默认 AI + 各模块独立 AI。

        模块列表来自注册表，已注册但未配置覆盖的模块也会返回，
        否则用户看不到「可为该模块单独配 AI」的入口。
        """
        from .core import settings_service
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        return settings_service.get_all_settings(db, registry.list_enabled())

    @router.put("/settings/app")
    def save_app_settings(body: dict, db: Session = Depends(get_db), identity=Depends(get_identity)):
        """保存应用级通用配置（识别并发、上传大小上限等）。"""
        from .core import settings_service
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        settings_service.save_app_settings(db, body or {})
        db.commit()
        audit.log("settings.app.update", identity.uid, {"keys": sorted((body or {}).keys())})
        return {"ok": True, "app": settings_service.get_app_settings(db)}

    @router.put("/settings/ai")
    def save_ai_settings(
        body: dict,
        module: str | None = None,
        db: Session = Depends(get_db),
        identity=Depends(get_identity),
    ):
        """保存 AI 配置。module 缺省写全局默认；传 module 则写该模块覆盖层。

        模块层传空字符串 = 清除该字段覆盖、回到继承全局默认。
        """
        from .core import settings_service
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        settings_service.save_ai_config(db, body or {}, module)
        db.commit()
        audit.log(
            "settings.ai.update",
            identity.uid,
            {"module": module or "default", "fields": sorted(k for k in (body or {}) if k != "api_key")},
        )
        cfg = settings_service.get_ai_config(db, module)
        return {"ok": True, "ai": cfg}

    @router.delete("/settings/ai/{module}")
    def reset_module_ai(module: str, db: Session = Depends(get_db), identity=Depends(get_identity)):
        """清除某模块的全部 AI 覆盖，回到继承全局默认。"""
        from .core import settings_service
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        settings_service.reset_module_ai(db, module)
        db.commit()
        audit.log("settings.ai.reset", identity.uid, {"module": module})
        return {"ok": True, "ai": settings_service.get_ai_config(db, module)}

    @router.post("/settings/ai/test")
    def test_ai_connection(
        body: dict,
        module: str | None = None,
        db: Session = Depends(get_db),
        identity=Depends(get_identity),
    ):
        """测试 AI 连通性。

        未传 api_key 时用已保存的 Key 测试（支持「保存前先试」与「保存后复验」两种用法）。
        传 api_key 时用传入值测试 —— 因此可以先填 Key 点测试，确认可用再点保存。
        """
        from .core import settings_service
        from .modules.weekly_report.vlm import probe_connection

        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)

        body = body or {}
        saved = settings_service.resolve_ai(db, module)
        api_key = (body.get("api_key") or "").strip() or saved["api_key"]
        base_url = (body.get("base_url") or "").strip() or saved["base_url"]
        model = (body.get("model") or "").strip() or saved["model"]
        # 缺 scheme 时自动补全协议头（幂等）：本地/内网补 http://，公网补 https://。
        # 复用 settings_service 的统一实现，避免此处再复制一份规则导致两处不一致。
        base_url = settings_service.ensure_url_scheme(base_url)

        ok, msg = probe_connection(base_url, model, api_key)
        audit.log("settings.ai.test", identity.uid, {"module": module or "default", "ok": ok})
        return {"ok": ok, "message": msg, "model": model, "baseUrl": base_url}

    router.include_router(weekly_report_router, prefix="/weekly-report")
    app.include_router(router, prefix="/api")
    app.include_router(router, prefix=f"{settings.gateway_prefix}/api")


_api_router()


@app.websocket("/ws")
@app.websocket(f"{settings.gateway_prefix}/ws")
async def ws_endpoint(ws: WebSocket):
    # WebSocket 建连时以 Header 绑定身份，后续消息不再重复校验（V10 8.10）
    identity = get_provider().resolve(ws)  # type: ignore[arg-type]
    await ws.accept()
    await ws.send_json({"event": "connected", "identity": identity.__dict__ if identity else None})
    try:
        while True:
            msg = await ws.receive_text()
            await ws.send_json({"event": "echo", "data": msg})
    except WebSocketDisconnect:
        return


# 显式 MIME 映射（真机坑：python:3.12-slim 无 /etc/mime.types，FileResponse 猜 .js 失败
# 会返回 application/octet-stream，浏览器拒绝执行 module script → 页面白屏）
_MIME = {
    
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json",
}


def _safe_serve_static(rel_path: str) -> FileResponse | None:
    """路径标准化 + 穿越防护（V10 8.12：拒绝 .. 目录穿越）。"""
    root = PUBLIC_DIR.resolve()
    target = (root / rel_path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        return None
    return FileResponse(target, media_type=_MIME.get(target.suffix.lower()))


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str, request: Request):
    """静态资源 + SPA 兜底；按请求前缀动态注入 <base href>（避坑指南 §1.2）。

    关键：网关保留完整前缀转发（/app/omnioffice/assets/x.js），必须先剥离前缀再查
    静态文件，否则查找失败回退成 index.html（text/html）→ 浏览器拒绝执行 JS → 白屏。
    """
    prefix = settings.gateway_prefix.strip("/")
    rel = full_path
    if rel == prefix:
        rel = ""
    elif rel.startswith(prefix + "/"):
        rel = rel[len(prefix) + 1 :]
    if rel:
        resp = _safe_serve_static(rel)
        if resp is not None:
            return resp
    index = PUBLIC_DIR / "index.html"
    if not index.is_file():
        return JSONResponse(
            {"error": "FRONTEND_NOT_BUILT", "message": "前端未构建：先执行 web 构建（vite build）"},
            status_code=503,
        )
    m = _PREFIX_RE.match(request.url.path)
    base = f"{m.group(1)}/" if m else "/"
    html = index.read_text(encoding="utf-8")
    injected = html.replace(
        "<head>",
        f'<head>\n    <base href="{base}">',
        1,
    )
    return HTMLResponse(injected)


@app.on_event("startup")
def on_startup():
    init_db()
    # 安装向导注入的值写入 DB（仅当 DB 无值，不覆盖用户后续修改）
    _inject_wizard()
    # 识别队列：worker 线程挂当前事件循环，进度经 WS 广播
    recognize_queue.attach_loop(asyncio.get_event_loop())
    recognize_queue.ensure_workers()
    # 关键启动参数必须打日志（避坑指南 §1.4）
    print(
        f"[startup] version={settings.app_version} identity_mode={settings.identity_mode} "
        f"socket={settings.socket_path or f'tcp:{settings.tcp_port}'} prefix={settings.gateway_prefix} "
        f"db={'postgres' if settings.database_url.startswith('postgres') else 'sqlite'} "
        f"ai={_ai_status()} "
        f"public={'ok' if (PUBLIC_DIR / 'index.html').is_file() else 'missing'}",
        flush=True,
    )
    audit.log("server.start", None, {"version": settings.app_version})
    # 真机排障：每次启动自动写一份环境快照到可下载位置（v1.0.18）。
    # 这样即便用户还没点导出、也没反馈问题，我们也有一份现场证据。
    # 失败不影响启动 —— 诊断是辅助能力，不能反过来成为故障源。
    try:
        from .core.diag import snapshot

        snapshot("服务启动")
    except Exception as e:  # noqa: BLE001
        print(f"[diag] 启动快照失败（不影响服务）: {type(e).__name__}: {e}", flush=True)


def _inject_wizard() -> None:
    """把 wizard 环境变量写入 settings 表（幂等，不覆盖 DB 已有值）。

    llm_base_url_custom = 百炼「业务空间专属域名」，优先于下拉选择的通用域名。
    """
    wizard = {
        "llm_api_key": settings.llm_api_key,
        "llm_base_url": settings.llm_base_url,
        "llm_base_url_custom": settings.llm_base_url_custom,
        "llm_model": settings.llm_model,
    }
    if not any(wizard.values()):
        return
    db = SessionLocal()
    try:
        from .core import settings_service
        settings_service.inject_wizard_defaults(db, wizard)
        db.commit()
    except Exception as e:  # 注入失败不应阻断启动
        db.rollback()
        print(f"[startup] wizard 注入跳过：{type(e).__name__}: {e}", flush=True)
    finally:
        db.close()


def _ai_status() -> str:
    """启动日志里的 AI 状态（只说有无 Key，不泄露内容）。"""
    db = SessionLocal()
    try:
        from .core.settings_service import resolve_ai
        cfg = resolve_ai(db, "weekly_report")
        return "configured" if cfg["api_key"] else "missing-key"
    except Exception:
        return "unknown"
    finally:
        db.close()
