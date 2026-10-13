"""身份抽象（评估方案 4.3 要点 1：IdentityProvider 接口隔离，保留路线切换能力）。

信任链红线（避坑指南 §3.1）：
- 数据归属键只能来自可信注入（网关 X-Trim-* 头）；
- 绝不信任请求体 / 查询参数中自报的 uid；
- 后续若启用备选路线（自建登录），仅需新增 Provider 实现，业务代码零改动。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from .config import settings


@dataclass(frozen=True)
class Identity:
    uid: str
    username: str
    is_admin: bool


class IdentityProvider(Protocol):
    def resolve(self, request: Request) -> Identity | None: ...


class GatewayHeaderProvider:
    """真机形态：统一网关校验 NAS 登录态后注入 X-Trim-* 头，应用只读头。"""

    def resolve(self, request: Request) -> Identity | None:
        uid = request.headers.get("X-Trim-Userid", "").strip()
        if not uid:
            return None
        return Identity(
            uid=uid,
            username=request.headers.get("X-Trim-Username", "") or uid,
            is_admin=(request.headers.get("X-Trim-Isadmin", "").strip().lower() in ("1", "true", "yes")),
        )


class MockProvider:
    """本地开发形态：固定身份，避免依赖网关（DEV 环境矩阵）。"""

    def resolve(self, request: Request) -> Identity | None:
        return Identity(uid="1000", username="devuser", is_admin=True)


_PROVIDERS: dict[str, IdentityProvider] = {
    "gateway": GatewayHeaderProvider(),
    "mock": MockProvider(),
}


def get_provider() -> IdentityProvider:
    return _PROVIDERS.get(settings.identity_mode, GatewayHeaderProvider())


def get_identity(request: Request) -> Identity | None:
    """FastAPI 依赖入口；M1 起业务接口一律经此取身份。"""
    return get_provider().resolve(request)
