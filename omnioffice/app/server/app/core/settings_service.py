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


def _is_local_or_private_host(url: str) -> bool:
    """判断地址是否指向本地回环 / 内网主机（缺协议时决定补 http 还是 https）。

    只取 host 部分判断，容忍带端口、带路径、带 userinfo、IPv6 字面量。
    """
    candidate = url.split("://", 1)[-1]
    # 裸 IPv6（如 ::1:8080/v1）不包裹方括号，单独识别
    if candidate.startswith("::"):
        return True
    host = candidate.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.rsplit("@", 1)[-1]  # 去掉 userinfo
    if host.startswith("["):  # IPv6 字面量 [::1]:8080
        host = host[1:].split("]", 1)[0]
    else:
        host = host.split(":", 1)[0]  # 去掉端口
    host = host.strip().lower().rstrip(".")
    if not host:
        return False
    # 主机名形式的本地/内网
    if host in ("localhost", "::1", "0.0.0.0") or host.endswith(".local"):
        return True
    if host.startswith("127."):
        return True
    # IPv4 私网段：10/8、172.16~31/12、192.168/16、169.254/16(link-local)
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() and len(p) <= 3 for p in parts):
        nums = [int(p) for p in parts]
        if nums[0] == 10:
            return True
        if nums[0] == 172 and 16 <= nums[1] <= 31:
            return True
        if nums[0] == 192 and nums[1] == 168:
            return True
        if nums[0] == 169 and nums[1] == 254:
            return True
    return False


def ensure_url_scheme(url: str) -> str:
    """URL 缺 scheme 时自动补全协议头（幂等，重复调用不会二次拼接）。

    urllib.request 遇到无 scheme 的地址会直接抛
    ``ValueError: unknown url type``，而用户填服务地址时常漏写前缀，故统一兜底。

    补全规则（仅当既无 http:// 也无 https:// 时才补；已带的原样返回）：
      - 本地回环 / 内网地址（localhost、127.x、::1、10.x、172.16~31.x、
        192.168.x、169.254.x、*.local）→ 补 ``http://``。
        这类自建服务（Ollama / LocalAI / 内网 vLLM / Xinference）几乎都是
        明文 HTTP，一律补 https 会 SSL 握手失败、表现为「连接失败」。
      - 其余（公网域名 / 公网 IP）→ 补 ``https://``。
    """
    url = url.strip()
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    scheme = "http://" if _is_local_or_private_host(url) else "https://"
    return scheme + url


# 兼容旧私有名：历史调用点（vlm 等）曾各自定义同名函数，统一后保留别名。
_ensure_url_scheme = ensure_url_scheme

# 内置兜底：无任何配置时也能正常渲染 UI
BUILTIN_DEFAULTS = {
    # 阿里云百炼 DashScope 通用域名（所有业务空间通用，可作为开箱默认值）。
    # ⚠️ 官方自 2026-09-30 起该域名不再支持新特性：用它调 qwen3.8 / qwen3.7 等
    # 现役模型会返回 404（地址或模型不存在）。真正可用的地址是「业务空间专属域名」
    # （{WorkspaceId}.{region}.maas.aliyuncs.com），见 AI_PROVIDERS 的 qwen_workspace。
    # 此处保留通用域名只为「未配置时 UI 不空白」，用户必须换成自己的专属域名。
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    # 默认模型：qwen3.8-flash —— 官方视觉理解推荐模型（2026-10-11 更新）中
    # 「支持图像输入 + JSON 结构化输出 + 成本低」的最优解。
    # 旧默认 qwen3-vl-plus 已不被官方作为首选推荐；qwen3-vl-flash 更是不在
    # 官方推荐列表中，部分地域直接 404，故不再作为默认。
    "model": "qwen3.8-flash",
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
        "id": "qwen3.8-flash",
        "label": "qwen3.8-flash（推荐 · 省钱均衡）",
        "tier": "recommended",
        "desc": "官方现役轻量旗舰：1M 上下文，支持图像/视频、JSON 结构化输出，"
                "延迟与费用低。周报截图识别综合首选。",
    },
    {
        "id": "qwen3.8-max",
        "label": "qwen3.8-max（旗舰 · 能力最强）",
        "tier": "strong",
        "desc": "千问迄今最强：1M 上下文、最长 2 小时视频、内置工具。"
                "版式复杂或截图模糊时用它，费用最高。",
    },
    {
        "id": "qwen3.7-plus",
        "label": "qwen3.7-plus（高能 · 稳定）",
        "tier": "stable",
        "desc": "1M 上下文，支持图像/视频、JSON 结构化输出，能力接近旗舰，费用中等。",
    },
    {
        "id": "qwen3.7-flash",
        "label": "qwen3.7-flash（省钱 · 速度优先）",
        "tier": "economy",
        "desc": "比 3.7-plus 更快更省，1M 上下文，单轮最多 256 张图。截图清晰时够用。",
    },
    {
        "id": "qwen3.6-plus",
        "label": "qwen3.6-plus（上一代 · 兼容）",
        "tier": "stable",
        "desc": "Qwen3.6 系列，1M 上下文，支持图像/视频/JSON。官方已不作为首选推荐。",
    },
    {
        "id": "qwen3.5-ocr",
        "label": "qwen3.5-ocr（文字提取专项 · 表格/手写）",
        "tier": "special",
        "desc": "专为文档、表格、试卷、手写内容优化。仅适合纯文字提取，"
                "不擅长判断任务归属与时间语义；周报识别一般不首选。",
    },
    {
        "id": "qwen3-vl-plus",
        "label": "qwen3-vl-plus（旧版 · 不推荐）",
        "tier": "legacy",
        "desc": "Qwen3-VL 系列，官方已不作为首选推荐；仅为兼容存量配置保留。"
                "新配置请用 qwen3.8-flash。",
    },
    {
        "id": "qwen3-vl-flash",
        "label": "qwen3-vl-flash（旧版 · 可能不可用）",
        "tier": "legacy",
        "desc": "已不在官方视觉模型推荐列表中，部分地域调用会返回 404。"
                "请勿在新配置中使用。",
    },
    {
        "id": "qwen-vl-max",
        "label": "qwen-vl-max（旧版 · 不推荐）",
        "tier": "legacy",
        "desc": "已从百炼推荐列表移除，仅为兼容存量配置保留。新项目请用 qwen3.8-flash。",
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
    "DashScope 存量通用域名（北京地域）。⚠️ 官方自 2026-09-30 起不再支持新特性："
    "用此域名调用 qwen3.8 / qwen3.7 等现役模型会返回 404「地址或模型不存在」。"
    "请改用「通义千问（业务空间专属域名，推荐）」，把地址换成你自己的专属域名。"
)
_QWEN_WS_NOTE = (
    "官方推荐，且北京/新加坡/东京/法兰克福/香港地域必须使用："
    "https://{WorkspaceId}.{地域}.maas.aliyuncs.com/compatible-mode/v1。"
    "最快拿法：百炼控制台「API Key」页导出 CSV，里面的 openAiCompatible 一列"
    "就是完整地址，整段粘贴到「服务地址」即可；或在创建 Key 的弹窗里复制「API Host」。"
    "优势：仅访问当前业务空间、并发承载更高、请求超时 3600 秒。"
)
# 各地域 DashScope 通用域名（官方 regions 文档，2026-10-13 更新）。
# 仅在没有专属域名时作为备选；德国（法兰克福）与日本（东京）不提供 DashScope 域名，
# 只能用业务空间专属域名。
_QWEN_REGION_NOTE = (
    "该地域的 DashScope 通用域名。各地域的 API Key 与模型列表相互独立、不能跨地域混用，"
    "请确认 API Key 归属地域与本项一致；官方仍推荐改用业务空间专属域名。"
)


def _qwen_provider(pid: str, label: str, base_url: str, note: str) -> dict:
    """构造一个百炼服务商预设（模型清单与档位说明共用一份）。"""
    return {
        "id": pid,
        "label": label,
        "baseUrl": base_url,
        "models": QWEN_MODEL_OPTIONS,
        "modelDetails": QWEN_MODELS,
        "note": note,
    }


AI_PROVIDERS = [
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
    _qwen_provider(
        "qwen",
        "通义千问（北京 · DashScope 通用域名）",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        _QWEN_DOMAIN_NOTE,
    ),
    _qwen_provider(
        "qwen_intl",
        "通义千问（新加坡 · DashScope 通用域名）",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        _QWEN_REGION_NOTE,
    ),
    _qwen_provider(
        "qwen_hk",
        "通义千问（中国香港 · DashScope 通用域名）",
        "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
        _QWEN_REGION_NOTE,
    ),
    _qwen_provider(
        "qwen_us",
        "通义千问（美国弗吉尼亚 · DashScope 通用域名）",
        "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
        _QWEN_REGION_NOTE,
    ),
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
    base_url = _ensure_url_scheme(custom_url or (wizard_values.get("llm_base_url") or "").strip())

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
        "base_url": _ensure_url_scheme(pick("base_url").strip()),
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
        # base_url 缺 scheme 时自动补 https://，避免 urllib ValueError
        if field == "base_url" and val:
            val = _ensure_url_scheme(val)
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
