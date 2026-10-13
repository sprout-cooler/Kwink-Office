"""身份抽象（评估方案 4.3 要点 1：IdentityProvider 接口隔离，保留路线切换能力）。

信任链红线（避坑指南 §3.1）：
- 数据归属键只能来自可信注入（网关 X-Trim-* 头）；
- 绝不信任请求体 / 查询参数中自报的 uid；
- 后续若启用备选路线（自建登录），仅需新增 Provider 实现，业务代码零改动。

两级身份（本轮新增）：
  第一级 NAS 身份  —— 网关注入的 X-Trim-Userid，证明「是这台 NAS 的哪个系统用户」；
  第二级应用账号   —— 本应用自己的注册账号（cookie 会话），决定**数据归属键**。

业务侧只读 Identity.uid，而 uid 在登录后等于应用账号的 data_key，
因此所有既有业务表（owner_uid）天然按账号隔离，无需逐表改造。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request

from .config import settings

# Cookie 名：与 core.auth_service.COOKIE_NAME 保持一致（此处单独定义是为了
# 解析阶段不产生到 auth_service 的导入，避免身份模块与账号服务互相依赖）
_COOKIE = "oo_session"


@dataclass(frozen=True)
class Identity:
    uid: str
    username: str
    is_admin: bool


class IdentityProvider(Protocol):
    def resolve(self, request: Request) -> Identity | None: ...


def _cookie_token(request: Any) -> str:
    """读取会话 Cookie。

    WebSocket 与 HTTP 的取法不同（starlette 的 WS 也实现了 .cookies，但保险起见
    对缺失属性的对象直接返回空串，避免建连阶段因属性不存在而 500）。
    """
    cookies = getattr(request, "cookies", None)
    if cookies:
        return (cookies.get(_COOKIE) or "").strip()
    headers = getattr(request, "headers", None)
    if headers is None:
        return ""
    return _parse_cookie_header(headers.get("cookie", ""))


def _parse_cookie_header(raw: str) -> str:
    for part in (raw or "").split(";"):
        key, _, val = part.strip().partition("=")
        if key.strip() == _COOKIE:
            return val.strip()
    return ""


def _resolve_app_account(token: str) -> dict[str, Any] | None:
    """按会话 token 取应用账号；过期/无效返回 None。"""
    if not token:
        return None
    from ..db.session import SessionLocal
    from .auth_service import user_by_token

    db = SessionLocal()
    try:
        user = user_by_token(db, token)
        if user is None:
            return None
        # 复制成纯字典返回：会话关闭后 ORM 实例会脱离，避免后续惰性加载报错
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "data_key": user.data_key,
            "nas_uid": user.nas_uid,
            "is_admin": bool(user.is_admin),
        }
    except Exception as e:  # noqa: BLE001 —— 会话解析失败按「未登录」处理，不放大成 500
        print(f"[auth] 会话解析失败: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        db.close()


class GatewayHeaderProvider:
    """NAS 网关身份（第一级）：按 X-Trim-* 头解析，含 Sartup 期假网关兼容。

    注意：真机上这里是「系统级」身份，不代表应用内的某个账号。
    应用账号由 AppAccountProvider 在它之上叠加。
    """

    def resolve(self, request: Request) -> Identity | None:
        uid = request.headers.get("X-Trim-Userid", "").strip()
        if not uid:
            return None
        return Identity(
            uid=uid,
            username=request.headers.get("X-Trim-Username", "") or uid,
            is_admin=(request.headers.get("X-Trim-Isadmin", "").strip().lower() in ("1", "true", "yes")),
        )


class AppAccountProvider:
    """应用账号身份（第二级）：网关身份 + cookie 会话 → 数据归属键。

    未登录 → 返回 None → 各接口 401 → 前端展示登录页（需求「未登录访问限制」）。
    首个账号的 data_key 就是 NAS uid，因此升级前的数据仍然可见。
    """

    def resolve(self, request: Request) -> Identity | None:
        nas = GatewayHeaderProvider().resolve(request)
        if nas is None:
            return None
        if not settings.app_auth_required:
            # 逃生开关（APP_AUTH_REQUIRED=0）：退回「只有网关身份」的旧行为
            return nas
        account = _resolve_app_account(_cookie_token(request))
        if account is None:
            return None
        # 换人了：会话属于另一个 NAS 用户的应用账号时拒绝，防止跨账号串数据
        if str(account.get("nas_uid") or "") != nas.uid:
            print(
                f"[auth] 会话所属 NAS 账号({account.get('nas_uid')}) 与当前({nas.uid}) 不一致，按未登录处理",
                flush=True,
            )
            return None
        return Identity(
            uid=str(account.get("data_key") or nas.uid),
            username=str(account.get("display_name") or account.get("username") or nas.username),
            is_admin=bool(account.get("is_admin")) or nas.is_admin,
        )


class MockProvider:
    """本地开发形态：固定身份，避免依赖网关（DEV 环境矩阵）。

    mock 模式不做应用账号校验 —— 本地数据目录是开发者的私人地盘，
    强行加登录只会妨碍调试，且此时 identity.uid 仍为 "1000"，单测依赖该约定。
    """

    def resolve(self, request: Request) -> Identity | None:
        return Identity(uid="1000", username="devuser", is_admin=True)


_PROVIDERS: dict[str, IdentityProvider] = {
    "gateway": AppAccountProvider(),
    "mock": MockProvider(),
}


def get_provider() -> IdentityProvider:
    return _PROVIDERS.get(settings.identity_mode, AppAccountProvider())


def get_nas_identity(request: Request) -> Identity | None:
    """只解析 NAS 级身份（登录接口用：此时还没有应用会话）。"""
    if settings.identity_mode == "mock":
        return MockProvider().resolve(request)
    return GatewayHeaderProvider().resolve(request)


def get_identity(request: Request) -> Identity | None:
    """FastAPI 依赖入口；业务接口一律经此取身份。"""
    return get_provider().resolve(request)
