"""腾讯地图后端代理：Key 托管 + WebService 反代。

合规与安全设计（依据腾讯地图官方「Key 代理」文档）：
- 官方推荐的前端写法是 `window._TMapSecurityConfig = { serviceHost: "<代理地址>" }`，
  SDK 从官方 CDN 加载且**不带 key 参数**，所有业务请求打到代理地址；
- 代理端把 key 追加到转发请求的 query 上 —— key 全程只在服务端，
  **前端 JS 与网络面板都看不到明文 key**；
- 腾讯位置服务的 Referer 白名单机制同样在服务端满足。

为什么不做「前端直接带 key」：
明文 key 会被任何人从打包产物/Network 面板扒走，配额被刷爆且不可撤销。

为什么 key 存 user_settings 而不是 settings：
settings 表的 key 是全局唯一，财务大屏按账号隔离，地图 Key 应同样按账号存，
避免一号用尽全家的配额。
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse
import urllib.request
from typing import Any

from sqlalchemy.orm import Session

from ...core import audit
from ...core.settings_service import _get, _read, _set, _uset
from . import constants
from .errors import BizDashboardError, map_failed, map_not_configured, map_quota_exceeded

# 腾讯地图 WebService 返回的 JSON 顶层字段（用于区分业务错误与网络错误）
_WS_STATUS_KEYS = ("status", "message")

# ---- 地理编码缓存 ----
#
# 为什么需要缓存：腾讯位置服务对每个 Key 的每个接口限制**日调用量 1 万次**
# （官方规则：https://lbs.qq.com/faq/accountQuota/faqKey）。
# 大屏会反复渲染地图、对同一批地址反复做地理编码，
# 不缓存会迅速吃掉配额（实测用户提供的 Key 已出现「每日调用量已达上限」）。
# 官方给的第一条解法正是「对多频次的相同请求做缓存」。
#
# 缓存放进程内存：地理编码结果基本不变，重启后失效只是多花几次调用，
# 不值得为它引入持久化表（还会给升级迁移添麻烦）。
_GEOCODE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_GEOCODE_TTL = 24 * 3600.0  # 24 小时
_GEOCODE_CACHE_MAX = 500  # 最多缓存多少条，防止无限增长


def _cache_get(key: str) -> dict[str, Any] | None:
    item = _GEOCODE_CACHE.get(key)
    if item is None:
        return None
    ts, data = item
    if time.monotonic() - ts > _GEOCODE_TTL:
        _GEOCODE_CACHE.pop(key, None)
        return None
    return data


def _cache_put(key: str, data: dict[str, Any]) -> None:
    if len(_GEOCODE_CACHE) >= _GEOCODE_CACHE_MAX:
        # 超限：清掉最旧的一半（不追求精确 LRU，够用即可）
        items = sorted(_GEOCODE_CACHE.items(), key=lambda kv: kv[1][0])
        for k, _ in items[: len(items) // 2]:
            _GEOCODE_CACHE.pop(k, None)
    _GEOCODE_CACHE[key] = (time.monotonic(), data)


def get_map_key(db: Session, owner: str) -> str:
    """取地图 Key（明文，仅服务端使用，绝不返回前端）。

    读取顺序与 AI 配置同范式：**账号私有值优先，其次回落全局值**。
    全局值来自安装向导注入（首次装机即配好），
    账号私有值来自用户自己在「设置 → 经营大屏」里填的（可覆盖全局）。
    """
    return (_read(db, owner, constants.MAP_KEY_SETTING) or "").strip()


def set_map_key(db: Session, owner: str, key: str) -> None:
    """保存地图 Key 到**账号私有**位置。空字符串 = 清除。"""
    _uset(db, owner, constants.MAP_KEY_SETTING, (key or "").strip())


def inject_wizard_map_key(db: Session, key: str) -> None:
    """把安装向导填的地图 Key 写入全局 settings（仅当全局尚无值时）。

    写全局而非直接写某个账号：向导在应用级配置阶段执行，
    此时可能还没有应用账号。全局值作为所有账号的起点，
    账号自己改过之后以私有值为准（与 AI 配置的行为完全一致）。
    """
    val = (key or "").strip()
    if val and not _get(db, constants.MAP_KEY_SETTING):
        _set(db, constants.MAP_KEY_SETTING, val)


def has_map_key(db: Session, owner: str) -> bool:
    return bool(get_map_key(db, owner))


def _allowed(path: str) -> bool:
    """路径白名单校验：只放行腾讯地图实际使用的服务前缀。

    这一步是**防路径注入 / SSRF** 的关键：若不做白名单，
    攻击者可用 `../../` 或绝对 URL 让代理去请求任意地址。
    """
    if not path.startswith("/"):
        return False
    # 拒绝任何 .. 段
    if ".." in path.split("/"):
        return False
    return any(path.startswith(p) for p in constants.TENCENT_MAP_ALLOWED_PREFIXES)


def proxy_ws(db: Session, owner: str, query: str) -> dict[str, Any]:
    """反代腾讯地图 WebService 请求。

    Args:
        db: 数据库会话（取 Key）。
        owner: 当前账号（取其 Key）。
        query: 腾讯地图 SDK 传来的 query 串（不含 key）。

    Returns:
        腾讯地图返回的 JSON（已解析）。

    Raises:
        BizDashboardError: Key 未配置 / 路径不允许 / 上游调用失败。
    """
    key = get_map_key(db, owner)
    if not key:
        raise map_not_configured()

    parsed = urllib.parse.urlparse(query)
    path = parsed.path or "/"
    if not _allowed(path):
        raise BizDashboardError(
            "MAP_PATH_NOT_ALLOWED",
            "请求的地图服务不被允许",
            400,
        )

    params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    # 丢弃客户端可能夹带的 key 参数，一律用服务端托管的 Key
    params = [(k, v) for k, v in params if k != "key"]
    params.append(("key", key))

    target = f"{constants.TENCENT_MAP_WS_BASE}{path}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        target,
        headers={
            # 腾讯位置服务的 Referer 白名单在服务端满足；
            # 此处显式声明，避免上游因缺 Referer 拒绝。
            "Referer": "https://apis.map.qq.com/",
            "User-Agent": "OmniOffice-BizDashboard/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # 上游 4xx/5xx：把状态码带出来，便于定位（Key 无权限 / 配额超限 / 参数错）
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001 —— 读错误体失败不应掩盖原错误
            detail = ""
        raise map_failed(f"上游返回 HTTP {e.code}") from None
    except Exception as e:  # noqa: BLE001 —— 网络层异常统一转可行动提示
        raise map_failed("网络不可达，请检查 NAS 是否能访问外网") from None

    try:
        import json

        data = json.loads(raw)
    except ValueError:
        raise map_failed("上游返回了非 JSON 内容") from None

    if isinstance(data, dict):
        # 腾讯地图用 status=0 表示成功；非 0 时 message 是可读原因
        status = data.get("status")
        if status not in (0, "0", None):
            msg = str(data.get("message") or "未知错误")
            # 配额耗尽是用户可自行处置的问题，单独给可行动提示
            if "调用量已达到上限" in msg or "配额" in msg or "频率" in msg:
                raise map_quota_exceeded(msg)
            raise map_failed(msg)
    return data if isinstance(data, dict) else {"result": data}


def geocode(db: Session, owner: str, address: str, city: str = "") -> dict[str, Any]:
    """地址 → 经纬度（地理编码）。

    前端地图选点时调用；地址由用户输入或客户档案带入。
    **带 24 小时缓存**：腾讯对每个 Key 的每个接口有日调用量上限（默认 1 万次），
    大屏反复渲染会迅速吃满配额，缓存是最有效的缓解手段。
    """
    address = (address or "").strip()
    if not address:
        raise BizDashboardError("ADDRESS_REQUIRED", "请填写要解析的地址", 400)
    q = {"address": address}
    if city:
        q["city"] = city

    # 缓存键含账号，避免 A 账号的地址缓存被 B 账号复用造成的信息串号
    cache_key = hashlib.sha256(f"{owner}|{address}|{city}".encode("utf-8")).hexdigest()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = proxy_ws(db, owner, "/geocoder/v1/?" + urllib.parse.urlencode(q))
    _cache_put(cache_key, data)
    return data


def token_hash(token: str) -> str:
    """分享令牌的 sha256（十六进制）——只存哈希，不存明文。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def audit_share(owner: str, action: str, extra: dict[str, Any] | None = None) -> None:
    """分享相关操作留痕（谁在什么时候分享/撤销了哪些数据）。"""
    audit.log(f"biz.share.{action}", owner, extra or {})
