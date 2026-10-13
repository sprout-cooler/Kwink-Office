"""应用配置：全部来自环境变量（Compose 注入），禁止硬编码 NAS 路径（避坑指南 §1.3）。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # 网关前缀：与 manifest / ui/config 中 gatewayPrefix 保持一致
    gateway_prefix: str = os.environ.get("GATEWAY_PREFIX", "/app/omnioffice")
    # Unix Socket 路径（真机形态）；为空表示 TCP 形态（本地联调）
    socket_path: str = os.environ.get("SOCKET_PATH", "")
    tcp_port: int = int(os.environ.get("PORT", "8787"))
    # 业务数据目录：真机挂共享目录 ${TRIM_APPDEST}/share；本地为项目内 data/
    data_dir: str = os.environ.get("DATA_DIR", "data")
    # 版本号：与 manifest version 由打包体检强制一致（避坑指南 §1.3）
    app_version: str = os.environ.get("APP_VERSION", "1.0.0")
    # 身份来源：gateway=网关 X-Trim-* 头（真机/假网关）；mock=本地开发固定身份
    identity_mode: str = os.environ.get("IDENTITY_MODE", "gateway")
    # 数据库：真机由 Compose 注入 PostgreSQL；本地未注入时回退 SQLite（DATA_DIR 下）
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    # 上传约束（V10 3.10）
    upload_max_mb: int = int(os.environ.get("UPLOAD_MAX_MB", "10"))
    # 大模型配置（M2 接入；T13 已定：用户自带 Key，经 wizard 注入）
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", ""))
    # 百炼「业务空间专属域名」（wizard 独立输入项），优先于 LLM_BASE_URL。
    # 官方把接入分为 DashScope 通用域名与业务空间专属域名两类，后者并发更高、
    # 超时 3600 秒，且自 2026-09-30 起通用域名不再支持新特性。
    llm_base_url_custom: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL_CUSTOM", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    # 识别并发：VLM 单张 RT 较长，适度并发摊总耗时（V10 性能指标 20 张≤60s）
    recognize_workers: int = int(os.environ.get("RECOGNIZE_WORKERS", "3"))
    # 本地开发跨域（仅 mock 模式下前端 vite 直连时需要）
    cors_dev: bool = field(default_factory=lambda: _bool(os.environ.get("CORS_DEV")))


settings = Settings()
