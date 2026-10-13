"""配置管理：通用 AI + 模块独立覆盖（V10 2.4 设置页后端）。

架构（三层优先级，后者覆盖前者）：
  1. 内置兜底     — 无任何配置时的可用默认值（保证 UI 不空白）
  2. 环境变量     — wizard 注入（llm_api_key / llm_base_url / llm_model），安装向导填写
  3. 数据库       — 设置页保存的值，最高优先级，支持运行中修改即时生效

key 命名约定：
  ai.default.{base_url,model,api_key}       — 全局默认 AI（所有模块继承）
  ai.{module_id}.{base_url,model,api_key}   — 模块独立覆盖（留空 = 继承全局）
  app.{key}                                 — 应用级通用配置

安全约定：api_key 只写不读，get_* 一律返回 has_key / key_masked，绝不回传明文。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Setting

# 前端可见的 AI 配置字段
AI_FIELDS = ("base_url", "model", "api_key")

# 内置兜底：无任何配置时也能正常渲染 UI
BUILTIN_DEFAULTS = {
    # 阿里云百炼 DashScope 通用域名（所有业务空间通用，可作为开箱默认值）。
    # 注意：官方自 2026-09-30 起该域名不再支持新特性，生产环境建议改用
    # 「业务空间专属域名」预设（填写自己的 WorkspaceId，见 AI_PROVIDERS）。
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    # 默认模型：qwen3-vl-plus —— 官方现役视觉模型中性价比与 JSON 结构化输出最平衡者。
    # 旧的 qwen-vl-max / qwen-vl-plus 已从官方推荐列表移除，故不再作为默认。
    "model": "qwen3-vl-plus",
    "api_key": "",
}

# 业务空间专属域名前缀（官方地域化格式：{WorkspaceId}.{region}.maas.aliyuncs.com）
# 各地域 ID 见 https://help.aliyun.com/zh/model-studio/regions
BAILIAN_REGION_IDS = [
    ("cn-beijing", "华北2（北京）"),
    ("ap-southeast-1", "新加坡"),
    ("cn-hongkong", "中国香港"),
    ("us-east-1", "美国（弗吉尼亚）"),
    ("eu-central-1", "德国（法兰克福）"),
    ("ap-northeast-1", "日本（东京）"),
]

# ---- 百炼模型清单（按周报「截图 → 结构化 JSON」场景筛选）--------------------
# 筛选口径（依据官方 vision-model 文档，2026-10-11 更新）：
#   1. 必须支持**图像输入**（截图识别前提）；
#   2. 优先支持**结构化输出 JSON**（周报要稳定拿到 {title,start_time,end_time,status,confidence}）；
#   3. 按「识别准确率 / 成本」分档，给用户可权衡的选择。
# 说明：models 为前端下拉顺序，ordered 即展示顺序（推荐档在前）。
QWEN_MODELS = [
    {
        "id": "qwen3-vl-plus",
        "label": "qwen3-vl-plus（推荐 · 准确率与成本均衡）",
        "tier": "recommended",
        "desc": "视觉理解 + JSON 结构化输出，260K 上下文。综合最适合周报截图识别。",
    },
    {
        "id": "qwen3-vl-flash",
        "label": "qwen3-vl-flash（省钱 · 速度快）",
        "tier": "economy",
        "desc": "轻量视觉模型，延迟更低、费用更低；截图清晰时准确率接近 plus。",
    },
    {
        "id": "qwen3.8-flash",
        "label": "qwen3.8-flash（全模态通用 · 稳定）",
        "tier": "stable",
        "desc": "千问现役旗舰之一，1M 上下文，支持图像/视频/JSON。能力全面，费用中等。",
    },
    {
        "id": "qwen3.7-plus",
        "label": "qwen3.7-plus（全模态通用 · 强）",
        "tier": "strong",
        "desc": "能力接近旗舰，1M 上下文，适合模糊截图或复杂版式。费用偏高。",
    },
    {
        "id": "qwen3.5-ocr",
        "label": "qwen3.5-ocr（文字提取专项 · 表格/手写）",
        "tier": "special",
        "desc": "专为文档、表格、试卷、手写内容优化。仅适合纯文字提取，"
                "不擅长判断任务归属与时间语义；周报识别一般不首选。",
    },
    {
        "id": "qwen-vl-max",
        "label": "qwen-vl-max（旧版 · 不推荐）",
        "tier": "legacy",
        "desc": "已从百炼推荐列表移除，仅为兼容存量配置保留。新项目请用 qwen3-vl-plus。",
    },
    {
        "id": "qwen-vl-plus",
        "label": "qwen-vl-plus（旧版 · 不推荐）",
        "tier": "legacy",
        "desc": "同上，已下线。仅兼容存量配置。",
    },
]
QWEN_MODEL_IDS = [m["id"] for m in QWEN_MODELS]

# 前端下拉用的精简结构（保持既有 shape：list[str]）
QWEN_MODEL_OPTIONS = list(QWEN_MODEL_IDS)

_QWEN_DOMAIN_NOTE = (
    "DashScope 通用域名，兼容所有业务空间。官方自 2026-09-30 起不再支持新特性；"
    "生产/高并发场景建议改用下方「业务空间专属域名」。"
)
_QWEN_WS_NOTE = (
    "格式：https://{WorkspaceId}.{地域}.maas.aliyuncs.com/compatible-mode/v1。"
    "WorkspaceId 与 API Host 在百炼控制台「API Key 创建」弹窗或「业务空间管理」页复制。"
    "优势：仅访问当前业务空间、并发承载更高、请求超时 3600 秒。"
)

AI_PROVIDERS = [
    {
        "id": "qwen",
        "label": "通义千问（阿里云百炼）",
        "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": QWEN_MODEL_OPTIONS,
        "modelDetails": QWEN_MODELS,
        "note": _QWEN_DOMAIN_NOTE,
    },
    {
        "id": "qwen_workspace",
        # baseUrl 留空：WorkspaceId 因人而异，需用户在「服务地址」中自行填写，
        # 填写后本项会自动被识别为专属域名模式（见 frontend matchedProvider 逻辑）。
        "label": "通义千问（业务空间专属域名，推荐）",
        "baseUrl": "",
        "models": QWEN_MODEL_OPTIONS,
        "modelDetails": QWEN_MODELS,
        "placeholder": "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "note": _QWEN_WS_NOTE,
    },
    {
        "id": "doubao",
        "label": "豆包（火山方舟）",
        "baseUrl": "https://ark.cn-beijing.volces.com/api/v3",
        "models": [],  # 方舟按 endpoint id（ep-xxxx）调用，用户自填
    },
    {
        "id": "custom",
        "label": "自建兼容端点",
        "baseUrl": "",
        "models": [],
    },
]


def _get(db: Session, key: str) -> str:
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    return row.value if row else ""


def _set(db: Session, key: str, value: str) -> None:
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def _delete(db: Session, key: str) -> None:
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row is not None:
        db.delete(row)


# ------------------------------------------------------------------ 向导注入


def inject_wizard_defaults(db: Session, wizard_values: dict[str, str]) -> None:
    """安装向导注入的值写入 DB（仅当 DB 中无值时）。

    地址优先级：业务空间专属域名（llm_base_url_custom）> 下拉选择的 llm_base_url。
    百炼官方把接入分为「DashScope 通用域名」与「业务空间专属域名」两类，
    后者并发更高、超时 3600 秒，因此用户填了专属地址时以它为准。
    """
    custom_url = (wizard_values.get("llm_base_url_custom") or "").strip()
    base_url = custom_url or (wizard_values.get("llm_base_url") or "").strip()

    mapping = {
        "llm_api_key": "ai.default.api_key",
        "llm_base_url": "ai.default.base_url",
        "llm_model": "ai.default.model",
    }
    values = {
        "llm_api_key": (wizard_values.get("llm_api_key") or "").strip(),
        "llm_base_url": base_url,
        "llm_model": (wizard_values.get("llm_model") or "").strip(),
    }
    for env_key, setting_key in mapping.items():
        val = values[env_key]
        if val and not _get(db, setting_key):
            _set(db, setting_key, val)


# ------------------------------------------------------------------ 运行时读取


def resolve_ai(db: Session, module: str | None = None, env: Any | None = None) -> dict[str, Any]:
    """解析某模块最终生效的 AI 配置（模块覆盖 > 全局 > 环境变量 > 内置兜底）。

    识别链路的唯一入口：每次调用都读库，因此设置页改完立即生效，无需重启。
    返回明文 api_key —— 仅供服务端发起外部调用，绝不序列化给前端。
    """
    if env is None:
        from .config import settings as env

    def pick(field: str) -> str:
        # 3. 模块覆盖
        if module:
            v = _get(db, f"ai.{module}.{field}")
            if v:
                return v
        # 2. 全局默认（DB）
        v = _get(db, f"ai.default.{field}")
        if v:
            return v
        # 1. 环境变量（wizard 兜底）
        v = getattr(env, f"llm_{field}", "") or ""
        if v:
            return v
        # 0. 内置兜底
        return BUILTIN_DEFAULTS.get(field, "")

    return {
        "base_url": pick("base_url").strip(),
        "model": pick("model").strip(),
        "api_key": pick("api_key").strip(),
        "module": module,
    }


def get_ai_config(db: Session, module: str | None = None) -> dict[str, Any]:
    """脱敏视图：给前端用。api_key 只回 has_key / key_masked。"""
    resolved = resolve_ai(db, module)
    overrides = _list_module_overrides(db, module) if module else {}
    key = resolved["api_key"]
    return {
        "base_url": resolved["base_url"],
        "model": resolved["model"],
        "has_key": bool(key),
        "key_masked": (key[:3] + "***" + key[-4:]) if len(key) > 8 else ("***" if key else ""),
        "module": module,
        "module_overrides": overrides,
        "overridden": any(overrides.values()),
        # 该字段是否来自模块自身配置（false = 继承全局）
        "inherited": {f: not overrides.get(f, False) for f in AI_FIELDS},
    }


def save_ai_config(db: Session, data: dict[str, Any], module: str | None = None) -> None:
    """保存 AI 配置。module=None 写全局默认，否则写模块覆盖层。"""
    prefix = f"ai.{module}." if module else "ai.default."
    for field in AI_FIELDS:
        if field not in data:
            continue
        val = str(data[field]).strip()
        # 模块层：空字符串表示「清除覆盖、回到继承全局」
        if module and not val:
            _delete(db, f"{prefix}{field}")
            continue
        _set(db, f"{prefix}{field}", val)


def reset_module_ai(db: Session, module: str) -> None:
    """清除某模块的全部 AI 覆盖，回到继承全局默认。"""
    for field in AI_FIELDS:
        _delete(db, f"ai.{module}.{field}")


def list_modules_with_overrides(db: Session) -> set[str]:
    """扫描出已配置覆盖的模块 id。"""
    rows = db.execute(select(Setting).where(Setting.key.like("ai.%"))).scalars().all()
    mods: set[str] = set()
    for r in rows:
        parts = r.key.split(".")
        if len(parts) >= 3 and parts[1] not in ("default", ""):
            mods.add(parts[1])
    return mods


def _list_module_overrides(db: Session, module: str) -> dict[str, bool]:
    """某模块哪些字段有自己的配置（未覆盖 = 继承全局）。"""
    return {f: bool(_get(db, f"ai.{module}.{f}")) for f in AI_FIELDS}


# ------------------------------------------------------------------ 应用级配置

# 应用级配置白名单（分类设置页的「通用」分组）
APP_SETTING_KEYS = {
    "recognize_workers": {"label": "识别并发数", "type": "int", "min": 1, "max": 8,
                          "desc": "同时提交给大模型的截图数。调高更快但更费额度，默认 3"},
    "upload_max_mb": {"label": "单张截图大小上限（MB）", "type": "int", "min": 1, "max": 50,
                       "desc": "超过此大小的图片会被拒绝上传，默认 10"},
}


def get_app_settings(db: Session) -> dict[str, Any]:
    from .config import settings as env

    out: dict[str, Any] = {}
    for key, meta in APP_SETTING_KEYS.items():
        raw = _get(db, f"app.{key}")
        if not raw:
            raw = str(getattr(env, key, "") or "")
        try:
            val = int(raw) if raw else int(meta.get("min", 1))
        except ValueError:
            val = int(meta.get("min", 1))
        out[key] = {"value": max(meta["min"], min(meta["max"], val)), **meta}
    return out


def save_app_settings(db: Session, data: dict[str, Any]) -> None:
    """保存应用级配置（仅白名单键，值做范围裁剪）。"""
    for key, meta in APP_SETTING_KEYS.items():
        if key not in data:
            continue
        try:
            val = int(data[key])
        except (TypeError, ValueError):
            continue
        _set(db, f"app.{key}", str(max(meta["min"], min(meta["max"], val))))


# ------------------------------------------------------------------ 聚合视图


def get_all_settings(db: Session, modules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """设置页聚合数据。

    modules 由调用方从模块注册表传入，保证「已注册但未配置覆盖」的模块
    也会出现在设置页里（否则用户看不到可配置项）。
    """
    if modules is None:
        modules = []

    known = {m["id"]: m for m in modules}
    # 已配置覆盖但注册表里没有的模块也要露出（如历史遗留配置）
    for mid in list_modules_with_overrides(db):
        known.setdefault(mid, {"id": mid, "displayName": mid, "icon": "", "route": "", "tabs": []})

    module_views = []
    for mid, meta in known.items():
        cfg = get_ai_config(db, mid)
        module_views.append(
            {
                "id": mid,
                "displayName": meta.get("displayName", mid),
                "icon": meta.get("icon", ""),
                "route": meta.get("route", ""),
                "tabCount": len(meta.get("tabs") or []),
                "ai": cfg,
                "overridden": any(cfg["module_overrides"].values()),
            }
        )

    default = get_ai_config(db)
    return {
        "ai_default": default,
        "ai_modules": module_views,
        "providers": AI_PROVIDERS,
        "app": get_app_settings(db),
    }
