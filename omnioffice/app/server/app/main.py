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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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


def _set_session_cookie(response: JSONResponse, token: str, expires: datetime) -> None:
    """下发会话 Cookie。

    httponly=True：JS 读不到 token，即便页面被注入脚本也偷不走登录态；
    samesite=Lax：应用会被网关嵌套展示，Strict 会连自家子路径的导航也拦掉；
    path=/：应用挂在 /app/omnioffice 下，显式给根路径，避免某些路径收不到 Cookie。
    """
    max_age = max(1, int((expires - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        "oo_session", token, max_age=max_age, httponly=True, samesite="lax", path="/"
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

    # ---------------------------------------------------------- 账号与登录态

    @router.get("/auth/status")
    def auth_status(request: Request, db: Session = Depends(get_db)):
        """登录门状态探测（本接口**不需要应用登录**，用于决定要不要弹登录页）。

        返回：
          required    是否必须登录（mock 模式 / APP_AUTH_REQUIRED=0 时为 false）
          initialized 该 NAS 账号下是否已有应用账号（没有则前端引导「初始化管理员」）
          user        当前已登录账号（未登录为 null）
        """
        from .core import auth_service
        from .core.identity import get_nas_identity

        nas = get_nas_identity(request)
        if nas is None:
            return JSONResponse(
                {"error": "UNAUTHORIZED", "message": "未识别到网关身份"}, status_code=401
            )
        required = bool(settings.app_auth_required) and settings.identity_mode != "mock"
        token = (request.cookies.get(auth_service.COOKIE_NAME) or "").strip()
        user = auth_service.user_by_token(db, token) if required else None
        if user is not None and user.nas_uid != nas.uid:
            user = None  # 会话属于另一个 NAS 账号
        return {
            "required": required,
            "initialized": auth_service.count_users(db, nas.uid) > 0,
            "user": auth_service.public_user(user) if user else None,
            "nasUser": nas.username,
            "canRegister": True,
        }

    @router.post("/auth/register")
    def auth_register(request: Request, body: dict, db: Session = Depends(get_db)):
        """注册应用账号；成功后直接登录（签发会话 Cookie）。

        该 NAS 账号下的**第一个**账号自动成为管理员，并沿用 NAS uid 作为数据
        归属键 —— 这样升级前已存在的周报/模板/导出记录仍然可见。
        """
        from .core import auth_service
        from .core.identity import get_nas_identity

        nas = get_nas_identity(request)
        if nas is None:
            return JSONResponse({"error": "UNAUTHORIZED", "message": "未识别到网关身份"}, status_code=401)

        body = body or {}
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        confirm = str(body.get("confirm") or "")
        display_name = str(body.get("displayName") or "").strip()

        err = auth_service.validate_username(username)
        if err:
            raise HTTPException(status_code=400, detail={"error": "BAD_USERNAME", "message": err})
        if confirm and confirm != password:
            raise HTTPException(
                status_code=400, detail={"error": "PASSWORD_MISMATCH", "message": "两次输入的密码不一致"}
            )
        err = auth_service.validate_password(password)
        if err:
            raise HTTPException(status_code=400, detail={"error": "WEAK_PASSWORD", "message": err})
        if auth_service.get_user_by_username(db, nas.uid, username) is not None:
            raise HTTPException(
                status_code=409, detail={"error": "USER_EXISTS", "message": f"账号「{username}」已存在"}
            )

        is_first = auth_service.count_users(db, nas.uid) == 0
        try:
            user = auth_service.create_user(
                db, nas.uid, username, password, display_name, is_admin=True if is_first else None
            )
            auth_service.purge_expired_sessions(db)
            token, expires = auth_service.issue_session(
                db, user, remember=bool(body.get("remember")),
                user_agent=request.headers.get("user-agent", ""),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        audit.log("auth.register", nas.uid, {"username": username, "admin": is_first})

        resp = {"ok": True, "user": auth_service.public_user(user), "isFirst": is_first}
        out = JSONResponse(resp)
        _set_session_cookie(out, token, expires)
        return out

    @router.post("/auth/login")
    def auth_login(request: Request, body: dict, db: Session = Depends(get_db)):
        """账号密码登录，成功后下发会话 Cookie。"""
        from .core import auth_service
        from .core.identity import get_nas_identity

        nas = get_nas_identity(request)
        if nas is None:
            return JSONResponse({"error": "UNAUTHORIZED", "message": "未识别到网关身份"}, status_code=401)

        body = body or {}
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        key = f"{nas.uid}:{username}"

        wait = auth_service.check_login_attempts(key)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail={"error": "TOO_MANY_TRIES", "message": f"密码错误次数过多，请 {wait} 秒后再试"},
            )

        user = auth_service.get_user_by_username(db, nas.uid, username)
        # 账号不存在与密码错误返回同一句提示：不泄露「这个账号存不存在」
        if user is None or not auth_service.verify_password(password, user.password_hash, user.salt):
            auth_service.note_login_failure(key)
            raise HTTPException(
                status_code=401, detail={"error": "BAD_CREDENTIALS", "message": "账号或密码不正确"}
            )
        if user.disabled:
            raise HTTPException(status_code=403, detail={"error": "DISABLED", "message": "该账号已被停用"})

        auth_service.clear_login_failures(key)
        auth_service.purge_expired_sessions(db)
        token, expires = auth_service.issue_session(
            db, user, remember=bool(body.get("remember")),
            user_agent=request.headers.get("user-agent", ""),
        )
        user.last_login_at = datetime.now(timezone.utc)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        audit.log("auth.login", nas.uid, {"username": username})

        out = JSONResponse({"ok": True, "user": auth_service.public_user(user)})
        _set_session_cookie(out, token, expires)
        return out

    @router.post("/auth/logout")
    def auth_logout(request: Request, db: Session = Depends(get_db)):
        """退出：吊销服务端会话并清除 Cookie（幂等，重复调用不报错）。"""
        from .core import auth_service

        token = (request.cookies.get(auth_service.COOKIE_NAME) or "").strip()
        if token:
            auth_service.revoke_session(db, token)
            try:
                db.commit()
            except Exception:
                db.rollback()
        out = JSONResponse({"ok": True})
        out.delete_cookie(auth_service.COOKIE_NAME, path="/")
        return out

    @router.get("/auth/me")
    def auth_me(request: Request, db: Session = Depends(get_db)):
        """当前登录账号；未登录返回 401，前端据此回到登录页。"""
        from .core import auth_service
        from .core.identity import get_nas_identity, get_provider

        nas = get_nas_identity(request)
        identity = get_provider().resolve(request)
        if nas is None or identity is None:
            return JSONResponse({"error": "UNAUTHORIZED", "message": "未登录"}, status_code=401)
        token = (request.cookies.get(auth_service.COOKIE_NAME) or "").strip()
        user = auth_service.user_by_token(db, token)
        if user is None:
            return JSONResponse({"error": "UNAUTHORIZED", "message": "登录已失效，请重新登录"}, status_code=401)
        return {
            "user": auth_service.public_user(user),
            "dataKey": identity.uid,
            "nasUser": nas.username,
        }

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
        # owner = 当前账号的数据归属键：模板之外的全部配置项按账号隔离
        owner = identity.uid
        return settings_service.get_all_settings(db, registry.list_enabled(), owner=owner)

    @router.get("/settings/export")
    def export_settings(
        includeSecrets: bool = False,
        db: Session = Depends(get_db),
        identity=Depends(get_identity),
    ):
        """把当前账号的应用配置导出为 JSON 文件下载。

        API Key 默认不导出（includeSecrets=false）—— 导出文件常被随手转发，
        默认安全；确需迁移 Key 时勾选「包含 API Key」。
        """
        from urllib.parse import quote

        from .core import settings_service
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        payload = settings_service.export_config(db, identity.uid, bool(includeSecrets))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"omnioffice-settings-{identity.username}-{stamp}.json"
        return JSONResponse(
            payload,
            headers={
                # filename* 兼容 Safari / 非 ASCII 文件名
                "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
            },
        )

    @router.post("/settings/import")
    def import_settings(
        body: dict,
        db: Session = Depends(get_db),
        identity=Depends(get_identity),
    ):
        """从配置文件恢复当前账号的应用配置（只认白名单键，越界字段忽略）。

        语义约定：配置里某项为空 = **不动它**，而不是清空 ——
        导入一份不含 Key 的文件不应把现有 Key 抹掉。
        """
        from .core import settings_service
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        try:
            result = settings_service.import_config(db, body or {}, identity.uid)
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"error": "BAD_CONFIG_FILE", "message": str(e)}) from None
        db.commit()
        audit.log("settings.import", identity.uid, {"applied": result["applied"], "skipped": len(result["skipped"])})
        return {
            "ok": True,
            "applied": result["applied"],
            "skipped": result["skipped"],
            "settings": settings_service.get_all_settings(db, registry.list_enabled(), owner=identity.uid),
        }

    @router.put("/settings/app")
    def save_app_settings(body: dict, db: Session = Depends(get_db), identity=Depends(get_identity)):
        """保存应用级通用配置（识别并发、上传大小上限等）。"""
        from .core import settings_service
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        settings_service.save_app_settings(db, body or {}, owner=identity.uid)
        db.commit()
        audit.log("settings.app.update", identity.uid, {"keys": sorted((body or {}).keys())})
        return {"ok": True, "app": settings_service.get_app_settings(db, owner=identity.uid)}

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
        settings_service.save_ai_config(db, body or {}, module, owner=identity.uid)
        db.commit()
        audit.log(
            "settings.ai.update",
            identity.uid,
            {"module": module or "default", "fields": sorted(k for k in (body or {}) if k != "api_key")},
        )
        cfg = settings_service.get_ai_config(db, module, owner=identity.uid)
        return {"ok": True, "ai": cfg}

    @router.delete("/settings/ai/{module}")
    def reset_module_ai(module: str, db: Session = Depends(get_db), identity=Depends(get_identity)):
        """清除某模块的全部 AI 覆盖，回到继承全局默认。"""
        from .core import settings_service
        if identity is None:
            return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        settings_service.reset_module_ai(db, module, owner=identity.uid)
        db.commit()
        audit.log("settings.ai.reset", identity.uid, {"module": module})
        return {"ok": True, "ai": settings_service.get_ai_config(db, module, owner=identity.uid)}

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
        saved = settings_service.resolve_ai(db, module, owner=identity.uid)
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
    # 一次性数据迁移：把升级前落在安装目录下的模板/原图搬进持久目录（v1.0.23）
    try:
        from .modules.weekly_report.export_service import migrate_legacy_data

        migrate_legacy_data()
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] 旧数据迁移跳过（不影响启动）: {type(e).__name__}: {e}", flush=True)
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
